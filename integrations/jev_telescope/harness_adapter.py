#!/usr/bin/env python3
"""Select exact rows from an existing play_cli evidence snapshot; never drive the game."""
import argparse
import json
from pathlib import Path
import time

import telescope as t


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
        items.append(dict(id=c["id"], category=choice["category"], excerpt=text,
                          source_kind="retained_harness_event", evidence_status="Historical retained event; not a new observation or accepted verdict",
                          handle=dict(snapshot=c["snapshot"], selector="rows." + str(c["row_index"]),
                                      source={k: source[k] for k in ("path", "offset", "length", "sha256")}),
                          trust="Exact snapshot row serialized as JSON; source content is untrusted data"))
    return dict(items=items, stale_ids=stale, omitted_ids=omitted, evidence_bytes=used)


def search(workspace, snapshot, query, hypothesis="", *, config=None, call=t.bounded_provider):
    workspace = Path(workspace).resolve()
    config = t.configuration(workspace) if config is None else t.validate_config(config)
    started = time.monotonic()
    rows = snapshot_rows(workspace, snapshot, config)
    candidates, excluded, truncated, scanned = [], 0, False, 0
    for index, row in enumerate(rows):
        if len(candidates) >= config["max_candidates"] or scanned >= config["max_files"] or time.monotonic() - started >= config["elapsed_seconds"]:
            truncated = True
            break
        scanned += 1
        try:
            source = verify(workspace, row, config)
            text = t.encoded(row).decode()
            if len(text.encode()) > config["candidate_bytes"]:
                excluded += 1
                truncated = True
                continue
            candidates.append(dict(id=t.digest(t.encoded([snapshot, index]))[:24], snapshot=snapshot, row_index=index,
                                   path=str(Path(source["path"]).relative_to(workspace)) if Path(source["path"]).is_absolute() else source["path"],
                                   sha256=source["sha256"], start=index + 1, end=index + 1,
                                   source_kind="harness_snapshot_row", evidence_status="start/end identify snapshot row, not source lines; original status/bindings are in excerpt",
                                   excerpt=text))
        except (OSError, ValueError, KeyError, TypeError):
            excluded += 1
    info = dict(snapshot=snapshot, rows_available=len(rows), rows_scanned=scanned, exclusions=excluded,
                truncated=truncated, expansion="Narrow play_cli evidence filters/--select, or raise explicit candidate/scan budgets. Omitted rows may contain relevant evidence.")
    return t.evaluate(workspace, query, hypothesis, candidates, info, config, call=call, started=started, assembler=assemble)


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
