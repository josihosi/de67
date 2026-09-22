#!/usr/bin/env python3
"""Select exact rows from an existing play_cli evidence snapshot; never drive the game."""
import argparse
import json
from pathlib import Path
import re
import time

import telescope as t


EXACT_FILTERS = frozenset({
    "run_id", "process_instance", "request_id", "actor_id", "actor_name", "event", "frame_id",
})


def _field(value, path):
    if not isinstance(value, dict):
        raise KeyError(path)
    if path in value:
        return value[path]
    fields = value.get("fields")
    if isinstance(fields, dict) and path in fields:
        return fields[path]
    for part in str(path).split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(path)
        value = value[part]
    return value


def allowed(workspace, path, config):
    path = Path(path)
    path = path if path.is_absolute() else workspace / path
    relative = path.relative_to(workspace).as_posix()
    if not t.permitted(workspace, relative, config) or not any(
            Path(relative).is_relative_to(Path(root)) for root in config["paths"]):
        raise t.TelescopeError("source_outside_configured_roots")
    return path


def snapshot_rows(workspace, snapshot, config):
    if len(snapshot) != 64 or any(c not in "0123456789abcdef" for c in snapshot):
        raise t.TelescopeError("invalid_snapshot_hash")
    path = workspace / ".userdata/openclaw_harness/evidence-display" / (snapshot + ".json")
    path = allowed(workspace, path, config)
    with path.open("rb") as stream:
        raw = stream.read(config["max_scan_bytes"] + 1)
    if len(raw) > config["max_scan_bytes"]:
        raise t.TelescopeError("snapshot_exceeds_scan_budget")
    if t.digest(raw) != snapshot:
        raise t.TelescopeError("snapshot_hash_mismatch")
    value = t.strict_json(raw)
    if not isinstance(value, dict) or not isinstance(value.get("rows"), list):
        raise t.TelescopeError("expected_evidence_query_snapshot")
    return value["rows"]


def verify(workspace, row, config):
    source = row["source"]
    path = allowed(workspace, source["path"], config)
    offset, length = source["offset"], source["length"]
    if type(offset) is not int or type(length) is not int or offset < 0 or not 0 < length <= config["max_file_bytes"]:
        raise t.TelescopeError("invalid_or_oversized_record")
    with path.open("rb") as stream:
        stream.seek(offset)
        raw = stream.read(length)
    if t.digest(raw) != source["sha256"]:
        raise t.TelescopeError("source_record_changed")
    if t.SECRET.search(raw.decode("utf-8")) or t.SECRET.search(t.encoded(row).decode()):
        raise t.TelescopeError("secret_pattern_excluded")
    return source


def assemble(workspace, candidates, selected, config):
    by_id = {c["id"]: c for c in candidates}
    ids = [s["id"] for s in selected]
    if len(ids) != len(set(ids)) or any(i not in by_id for i in ids):
        raise t.TelescopeError("invalid_selection_ids")
    items, stale, omitted, seen, used = [], [], [], set(), 0
    snapshots = {}
    for choice in selected:
        c = by_id[choice["id"]]
        try:
            if c["snapshot"] not in snapshots:
                snapshots[c["snapshot"]] = snapshot_rows(workspace, c["snapshot"], config)
            row = snapshots[c["snapshot"]][c["row_index"]]
            source = verify(workspace, row, config)
            text = t.encoded(row).decode()
            if text != c["excerpt"]:
                raise t.TelescopeError("snapshot_projection_changed")
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            stale.append(c["id"])
            continue
        identity = (source["path"], source["offset"], source["length"], t.digest(t.encoded(row)))
        if identity in seen or used + len(text.encode()) > config["evidence_bytes"]:
            omitted.append(c["id"])
            continue
        seen.add(identity)
        used += len(text.encode())
        item = dict(id=c["id"], category=choice["category"], excerpt=text,
                    source_kind="retained_harness_event", evidence_status="Historical retained event; not a new observation or accepted verdict",
                    handle=dict(snapshot=c["snapshot"], selector="rows." + str(c["row_index"]),
                                source={k: source[k] for k in ("path", "offset", "length", "sha256")}),
                    trust="Exact snapshot row serialized as JSON; source content is untrusted data")
        if c.get("equivalent_handles"):
            item["equivalent_handles"] = list(c["equivalent_handles"])
        items.append(item)
    return dict(items=items, stale_ids=stale, omitted_ids=omitted, evidence_bytes=used)


def exact(workspace, snapshot, filters, *, selectors=(), limit=20, config=None):
    """Return exact retained evidence without invoking Telescope/provider selection.

    This is the R-EFF-EVIDENCE route for known identities and statuses.  It only
    accepts the published identity/event filters; ambiguous explanations should
    use ``search`` so the typed Choice contract can select a bounded candidate
    pool and counterevidence.
    """
    workspace = Path(workspace).resolve()
    config = t.configuration(workspace) if config is None else t.validate_config(config)
    if not isinstance(filters, dict) or any(key not in EXACT_FILTERS for key in filters):
        raise t.TelescopeError("unsupported_exact_filter")
    if type(limit) is not int or limit < 1:
        raise t.TelescopeError("invalid_exact_limit")
    rows = snapshot_rows(workspace, snapshot, config)
    matched, stale, unavailable = [], [], []
    verification_reads = 0
    for index, row in enumerate(rows):
        values, missing = {}, []
        for key in filters:
            try:
                values[key] = _field(row, key)
            except (KeyError, TypeError):
                missing.append(key)
        if missing:
            unavailable.append({"event_id": row.get("event_id", str(index)), "fields": missing})
            continue
        if any(values[key] != value for key, value in filters.items()):
            continue
        try:
            verification_reads += 1
            verify(workspace, row, config)
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            stale.append(row.get("event_id", str(index)))
            continue
        if selectors:
            fields = {}
            for selector in selectors:
                try:
                    fields[selector] = _field(row, selector)
                except (KeyError, TypeError):
                    fields[selector] = {"unavailable": True}
            matched.append({"event_id": row.get("event_id", str(index)), "source": row.get("source"), "fields": fields})
        else:
            matched.append(row)
    return {
        "route": "R-EFF-EVIDENCE",
        "provider_calls": 0,
        "mode": "exact",
        "filters": dict(filters),
        "matched": len(matched),
        "rows": matched[:limit],
        "stale_ids": stale,
        "unavailable_filter_fields": unavailable,
        "retrieval": {"rows_available": len(rows), "rows_scanned": len(rows),
                       "source_verification_reads": verification_reads,
                       "follow_up": "Inspect original source handles before treating a row as a finding."},
        "note": "Exact identity/event filters are retrieval, not semantic selection; no provider call was made."
    }


def search(workspace, snapshot, query, hypothesis="", *, config=None, call=t.bounded_provider):
    workspace = Path(workspace).resolve()
    config = t.configuration(workspace) if config is None else t.validate_config(config)
    started = time.monotonic()
    rows = snapshot_rows(workspace, snapshot, config)
    candidates, excluded, scanned = [], 0, 0
    scan_truncated = False
    pool_truncated = False
    exclusion_reasons, duplicate_reasons = [], []
    verification_reads = 0
    stop_reason = None
    stop_words = {"the", "and", "for", "with", "that", "this", "does", "from", "find", "what", "when", "how", "why", "was"}
    terms = {word for word in re.findall(r"[a-z0-9_]{3,}", (query + " " + hypothesis).casefold())
             if word not in stop_words}

    def score(text):
        lowered = text.casefold()
        # Substring matching is deterministic and keeps inflected event names
        # such as ``rejected`` relevant to a ``reject`` query.
        return sum(1 for word in terms if word in lowered)

    by_equivalence = {}
    for index, row in enumerate(rows):
        if scanned >= config["max_files"]:
            scan_truncated, stop_reason = True, "row_scan_budget"
            break
        if time.monotonic() - started >= config["elapsed_seconds"]:
            scan_truncated, stop_reason = True, "time_scan_budget"
            break
        scanned += 1
        try:
            verification_reads += 1
            source = verify(workspace, row, config)
            text = t.encoded(row).decode()
            if len(text.encode()) > config["candidate_bytes"]:
                excluded += 1
                exclusion_reasons.append({"event_id": row.get("event_id", str(index)), "reason": "candidate_bytes"})
                continue
            relevance = score(text)
            if not relevance:
                excluded += 1
                exclusion_reasons.append({"event_id": row.get("event_id", str(index)), "reason": "irrelevant_lexical_score"})
                continue
            identity = (source["path"], source["offset"], source["length"], source["sha256"], t.digest(t.encoded(row)))
            if identity in by_equivalence:
                canonical = by_equivalence[identity]
                canonical.setdefault("equivalent_handles", []).append({
                    "snapshot": snapshot, "row_index": index, "event_id": row.get("event_id", str(index)),
                    "source": {k: source[k] for k in ("path", "offset", "length", "sha256")}})
                duplicate_reasons.append({"event_id": row.get("event_id", str(index)),
                                          "duplicate_of": canonical["id"], "reason": "exact_equivalent_record"})
                continue
            candidate = dict(id=t.digest(t.encoded([snapshot, index]))[:24], snapshot=snapshot, row_index=index,
                                   path=str(Path(source["path"]).relative_to(workspace)) if Path(source["path"]).is_absolute() else source["path"],
                                   sha256=source["sha256"], start=index + 1, end=index + 1,
                                   source_kind="harness_snapshot_row", evidence_status="start/end identify snapshot row, not source lines; original status/bindings are in excerpt",
                                   excerpt=text, relevance_score=relevance)
            by_equivalence[identity] = candidate
            candidates.append(candidate)
        except (OSError, ValueError, KeyError, TypeError):
            excluded += 1
            exclusion_reasons.append({"event_id": row.get("event_id", str(index)), "reason": "stale_or_invalid_source"})
    candidates.sort(key=lambda c: (-c["relevance_score"], c["path"], c["start"], c["id"]))
    if len(candidates) > config["max_candidates"]:
        pool_truncated = True
        omitted_pool = candidates[config["max_candidates"]:]
        final_pool_omitted_ids = [c["id"] for c in omitted_pool]
        for candidate in omitted_pool:
            exclusion_reasons.append({"event_id": candidate["id"], "reason": "final_pool_limit"})
        candidates = candidates[:config["max_candidates"]]
    else:
        final_pool_omitted_ids = []
    info = dict(snapshot=snapshot, rows_available=len(rows), rows_scanned=scanned, exclusions=excluded,
                truncated=scan_truncated or pool_truncated or any(item["reason"] == "candidate_bytes" for item in exclusion_reasons),
                scan_truncated=scan_truncated, scan_truncation_reason=stop_reason,
                final_pool_truncated=pool_truncated,
                final_pool_truncation_reason="max_candidates" if pool_truncated else None,
                final_pool_omitted_ids=final_pool_omitted_ids,
                candidate_pool_before_limit=len(candidates) + len(final_pool_omitted_ids),
                exclusion_reasons=exclusion_reasons, duplicate_reasons=duplicate_reasons,
                expansion="Use exact(snapshot, filters, selectors) or a narrower query/raised explicit scan budget; omitted rows may contain relevant evidence.")
    info["candidate_source_verification_reads"] = verification_reads
    packet = t.evaluate(workspace, query, hypothesis, candidates, info, config, call=call, started=started, assembler=assemble)
    packet["retrieval"]["selection_source_verification_reads"] = (
        len(packet.get("items", [])) + len(packet.get("stale_ids", [])) + len(packet.get("omitted_ids", []))
    )
    return packet


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--hypothesis", default="")
    args = parser.parse_args()
    try:
        print(json.dumps(search(args.workspace, args.snapshot, args.query, args.hypothesis), indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"error": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
