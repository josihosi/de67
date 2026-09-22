#!/usr/bin/env python3
"""Optional, provider-free evidence advisories for the DE67 coordinator.

Pit Crew consumes the durable worker-library JSONL stream.  It is deliberately
not a coordinator, scheduler, or provider client: it can only create a compact
candidate and, after an explicitly supplied typed selector validates it, enqueue
one fixed-format advisory to the existing coordinator mailbox.  The worker
library invokes :func:`observe_boundary` lazily; that boundary never supplies a
selector, credential, or transport.

An owner or deterministic test may call :func:`run` with a selector callable.
That callable is admitted through Jev Telescope's existing credential-free
``provider_guard.py``.  This module supplies no HTTP transport, so installing or
enabling the package alone cannot make a provider request.
"""
from __future__ import annotations

from contextlib import contextmanager, closing
from dataclasses import dataclass
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import sys
import time
from typing import Any, Callable, Iterator, Mapping


MODES = {"off", "shadow", "on"}
RELATIONSHIPS = {
    "relevant_new_evidence",
    "duplicated_investigation",
    "challenged_assumption",
}
_WORDS = re.compile(r"[a-z][a-z0-9_-]{2,}")
_ASSUMPTION = re.compile(
    r"^\s*(?:active\s+)?assumption(?:\s*\[?([A-Za-z0-9._:-]+)\]?)?\s*:\s*(.+)$",
    re.IGNORECASE,
)
_OBJECTIVE = re.compile(r"^\s*(?:assignment\s+outcome|objective)\s*:\s*(.+)$", re.IGNORECASE)
_INDEPENDENT_VERIFICATION = re.compile(r"\bindependent(?:ly)?\b.{0,32}\bverif", re.IGNORECASE)
_STOP_WORDS = {
    "about", "after", "again", "against", "also", "analysis", "another", "assignment",
    "before", "being", "between", "build", "could", "current", "does", "evidence",
    "from", "have", "implementation", "into", "more", "must", "only", "possible",
    "prove", "requested", "result", "should", "task", "that", "their", "there",
    "these", "this", "through", "under", "using", "verify", "with", "work", "worker",
}
DEFAULTS: dict[str, Any] = {
    "mode": "off",
    "state_path": None,
    "max_scan_bytes": None,
    "max_candidates": None,
    "max_admissions": None,
    "cooldown_seconds": None,
    "selection_timeout_seconds": None,
    "provider_guard": {"mode": "off"},
}
_ENABLED_FIELDS = (
    "state_path",
    "max_scan_bytes",
    "max_candidates",
    "max_admissions",
    "cooldown_seconds",
    "selection_timeout_seconds",
    "provider_guard",
)


class PitCrewError(ValueError):
    """A local validation or evidence error; it never grants coordinator authority."""


@dataclass(frozen=True)
class TaskFact:
    task_id: str
    objective: str
    assumptions: tuple[tuple[str, str], ...]
    packet: str
    packet_sha256: str


def _encoded(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    raw = value if isinstance(value, bytes) else _encoded(value)
    return hashlib.sha256(raw).hexdigest()


def _integer(value: Any, name: str, minimum: int) -> int:
    if type(value) is not int or value < minimum or value > (1 << 63) - 1:
        raise PitCrewError("pit_crew_invalid_" + name)
    return value


def _number(value: Any, name: str, minimum: float) -> float:
    if type(value) not in (int, float) or isinstance(value, bool) or value < minimum:
        raise PitCrewError("pit_crew_invalid_" + name)
    try:
        number = float(value)
    except (OverflowError, ValueError) as error:
        raise PitCrewError("pit_crew_invalid_" + name) from error
    if number == float("inf") or number != number:
        raise PitCrewError("pit_crew_invalid_" + name)
    return number


def _relative(workspace: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(workspace.resolve()).as_posix()
    except (OSError, ValueError) as error:
        raise PitCrewError("pit_crew_source_outside_workspace") from error


def _module(path: Path, name: str) -> Any:
    """Load a sibling optional module without adding a package-wide import dependency."""
    if not path.is_file():
        raise PitCrewError("pit_crew_optional_dependency_unavailable")
    name = name + "_" + _digest(str(path.resolve()))[:16]
    loaded = sys.modules.get(name)
    if loaded is not None:
        return loaded
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise PitCrewError("pit_crew_optional_dependency_unavailable")
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[name] = loaded
    try:
        spec.loader.exec_module(loaded)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return loaded


def _guard_module() -> Any:
    return _module(Path(__file__).resolve().parent.parent / "jev_telescope" / "provider_guard.py",
                   "_de67_pit_crew_guard")


def _mailbox_module() -> Any:
    return _module(Path(__file__).resolve().parents[2] / "de-67-3" / "scripts" / "agent_mailbox.py",
                   "_de67_pit_crew_mailbox")


def validate_config(workspace: Path, value: Any) -> dict[str, Any]:
    """Require an owner-selected, bounded enabled configuration.

    No values are invented for an enabled route.  The state belongs to the target
    workspace's durable DE67 state, never the installed package or a temp runner.
    """
    workspace = Path(workspace).resolve()
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise PitCrewError("unknown_pit_crew_configuration")
    config = {**DEFAULTS, **value}
    if config["mode"] not in MODES:
        raise PitCrewError("pit_crew_invalid_mode")
    if config["mode"] == "off":
        return config
    missing = [field for field in _ENABLED_FIELDS if field not in value]
    if missing:
        raise PitCrewError("pit_crew_missing_" + "_".join(missing))
    if not isinstance(config["state_path"], str) or not config["state_path"]:
        raise PitCrewError("pit_crew_invalid_state_path")
    state = Path(config["state_path"])
    if not state.is_absolute():
        raise PitCrewError("pit_crew_state_path_must_be_absolute")
    try:
        state = state.resolve()
        state.relative_to(workspace / ".de67" / "state")
    except (OSError, ValueError) as error:
        raise PitCrewError("pit_crew_state_outside_workspace_state") from error
    config["state_path"] = str(state)
    config["max_scan_bytes"] = _integer(config["max_scan_bytes"], "max_scan_bytes", 512)
    config["max_candidates"] = _integer(config["max_candidates"], "max_candidates", 1)
    config["max_admissions"] = _integer(config["max_admissions"], "max_admissions", 0)
    config["cooldown_seconds"] = _number(config["cooldown_seconds"], "cooldown_seconds", 0)
    config["selection_timeout_seconds"] = _number(
        config["selection_timeout_seconds"], "selection_timeout_seconds", 0.001
    )
    try:
        guard = _guard_module()
        config["provider_guard"] = guard.validate_config(config["provider_guard"])
    except PitCrewError:
        raise
    except Exception as error:
        raise PitCrewError("pit_crew_provider_guard_unavailable") from error
    if config["provider_guard"].get("mode") != config["mode"]:
        raise PitCrewError("pit_crew_provider_guard_mode_mismatch")
    return config


def configuration(workspace: Path) -> dict[str, Any]:
    workspace = Path(workspace).resolve()
    path = workspace / ".de67" / "state" / "workspace.json"
    if not path.exists():
        return {**DEFAULTS}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise PitCrewError("pit_crew_workspace_configuration_unavailable") from error
    if not isinstance(value, dict):
        raise PitCrewError("pit_crew_workspace_configuration_invalid")
    return validate_config(workspace, value.get("jev_pit_crew", {}))


def _source_path(workspace: Path, assignment: Mapping[str, Any], source: Path | None = None) -> Path:
    path = (Path(source) if source is not None else
            workspace / ".de67" / "state" / "worker-library" / "events" /
            (str(assignment.get("id", "")) + ".jsonl"))
    try:
        path = path.resolve()
        path.relative_to(workspace / ".de67" / "state" / "worker-library" / "events")
    except (OSError, ValueError) as error:
        raise PitCrewError("pit_crew_source_outside_worker_events") from error
    return path


def _event_path_marker(path: Path) -> str:
    stat = path.stat()
    return ":".join(str(value) for value in (stat.st_dev, stat.st_ino))


def _packet_fact(workspace: Path, task_id: str, packet: str | Path | None) -> TaskFact | None:
    if not packet:
        return None
    try:
        path = Path(packet).resolve()
        path.relative_to(workspace / ".de67" / "state" / "worker-dispatch")
        raw = path.read_bytes()
    except (OSError, ValueError):
        return None
    if len(raw) > 65536:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    objective = ""
    assumptions: list[tuple[str, str]] = []
    for line in text.splitlines():
        if not objective and (match := _OBJECTIVE.match(line)):
            objective = match.group(1).strip()[:480]
        if match := _ASSUMPTION.match(line):
            value = match.group(2).strip()[:480]
            if value:
                identifier = match.group(1) or _digest([task_id, value])[:16]
                assumptions.append((identifier, value))
    if not objective:
        # A prepared assignment without an explicit objective is not enough to
        # infer a relationship.  It remains visible to ordinary coordination.
        return None
    return TaskFact(task_id, objective, tuple(assumptions[:8]), str(path), _digest(raw))


def _active_task(workspace: Path, assignment: Mapping[str, Any], task_id: str) -> bool:
    state, lineage = assignment.get("state_path"), assignment.get("lineage")
    if not isinstance(state, str) or not isinstance(lineage, str) or not task_id:
        return False
    try:
        with closing(sqlite3.connect(Path(state).resolve().as_uri() + "?mode=ro", uri=True)) as db:
            row = db.execute("SELECT attempt_terminal_at FROM tasks WHERE lineage_id=? AND task_id=?",
                             (lineage, task_id)).fetchone()
    except (OSError, sqlite3.Error):
        return False
    return row is not None and row[0] is None


def _task_facts(workspace: Path, assignment: Mapping[str, Any]) -> dict[str, TaskFact]:
    """Read only durable packet references for still-active exact task IDs."""
    result: dict[str, TaskFact] = {}
    own_id = str(assignment.get("task_id", ""))
    own = _packet_fact(workspace, own_id, assignment.get("packet"))
    if own is not None and _active_task(workspace, assignment, own_id):
        result[own_id] = own
    registry = workspace / ".de67" / "state" / "worker-library" / "registry.sqlite3"
    if not registry.exists():
        return result
    try:
        with closing(sqlite3.connect(registry.as_uri() + "?mode=ro", uri=True)) as db:
            rows = db.execute("SELECT task_id,packet,state_path,lineage FROM assignments").fetchall()
    except (OSError, sqlite3.Error):
        return result
    for task_id, packet, state, lineage in rows:
        if not isinstance(task_id, str) or task_id in result:
            continue
        peer = {"task_id": task_id, "packet": packet, "state_path": state, "lineage": lineage}
        fact = _packet_fact(workspace, task_id, packet)
        if fact is not None and _active_task(workspace, peer, task_id):
            result[task_id] = fact
    return result


def _tokens(text: str) -> set[str]:
    return {word for word in _WORDS.findall(text.lower()) if word not in _STOP_WORDS}


def _shared(left: str, right: str) -> set[str]:
    return _tokens(left) & _tokens(right)


def _evidence_items(record: Mapping[str, Any], task_id: str) -> Iterator[tuple[str, str, str]]:
    """Yield stable logical evidence identities from final worker messages only."""
    method = record.get("method")
    params = record.get("params")
    if not isinstance(method, str) or not isinstance(params, dict):
        return
    items: list[Mapping[str, Any]] = []
    if method == "item/completed" and isinstance(params.get("item"), dict):
        items = [params["item"]]
    elif method == "turn/completed" and isinstance(params.get("turn"), dict):
        raw = params["turn"].get("items", [])
        items = [item for item in raw if isinstance(item, dict)]
    for position, item in enumerate(items):
        if item.get("type") != "agentMessage" or item.get("phase") not in (None, "final", "final_answer"):
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        turn_id = params.get("turnId") or (params.get("turn") or {}).get("id") or "unknown-turn"
        item_id = item.get("id") or ("position-" + str(position))
        if not isinstance(turn_id, str) or not isinstance(item_id, str):
            continue
        identity = _digest({"task_id": task_id, "turn_id": turn_id, "item_id": item_id,
                            "text_sha256": _digest(text.encode("utf-8"))})
        yield identity, text.strip(), str(item_id)


def _candidate_rows(event_id: str, evidence: str, fact: TaskFact,
                    peers: Mapping[str, TaskFact], handle: Mapping[str, Any]) -> list[dict[str, Any]]:
    lower = evidence.lower()
    # Explicit independent verification and ordinary long work are not evidence
    # of a duplicate or a stuck worker.  Pit Crew never has a "stuck" class.
    if _INDEPENDENT_VERIFICATION.search(lower):
        return []
    rows: list[dict[str, Any]] = []
    relevant = _shared(evidence, fact.objective)
    if len(relevant) >= 2 and any(marker in lower for marker in ("evidence", "finding", "observed", "confirmed", "contradict")):
        rows.append({"relationship": "relevant_new_evidence", "related_task_id": None,
                     "assumption_id": None, "assumption": None})
    if any(marker in lower for marker in ("contradict", "challenge", "inconsistent", "falsif")):
        for assumption_id, assumption in fact.assumptions:
            if len(_shared(evidence, assumption)) >= 2:
                rows.append({"relationship": "challenged_assumption", "related_task_id": None,
                             "assumption_id": assumption_id, "assumption": assumption})
    if any(marker in lower for marker in ("investigat", "search", "analy", "implement")):
        for peer_id, peer in sorted(peers.items()):
            if peer_id != fact.task_id and len(_shared(fact.objective, peer.objective)) >= 2:
                rows.append({"relationship": "duplicated_investigation", "related_task_id": peer_id,
                             "assumption_id": None, "assumption": peer.objective})
    candidates: list[dict[str, Any]] = []
    for row in rows:
        candidate_id = _digest({"event_id": event_id, "task_id": fact.task_id, **row})
        candidates.append({"candidate_id": candidate_id, "event_id": event_id, "task_id": fact.task_id,
                           "objective": fact.objective, "packet": fact.packet,
                           "packet_sha256": fact.packet_sha256, "evidence": evidence[:640],
                           "handle": dict(handle), **row})
    return candidates


@contextmanager
def _locked(config: Mapping[str, Any]) -> Iterator[sqlite3.Connection]:
    path = Path(str(config["state_path"]))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(path), timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS pit_crew_sources(
                source_path TEXT PRIMARY KEY, marker TEXT NOT NULL, cursor INTEGER NOT NULL,
                generation INTEGER NOT NULL, anchor_offset INTEGER, anchor_length INTEGER,
                anchor_sha256 TEXT, updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pit_crew_evidence(
                event_id TEXT PRIMARY KEY, source_path TEXT NOT NULL, source_offset INTEGER NOT NULL,
                source_length INTEGER NOT NULL, source_sha256 TEXT NOT NULL, source_generation INTEGER NOT NULL,
                task_id TEXT NOT NULL, item_id TEXT NOT NULL, evidence TEXT NOT NULL, observed_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pit_crew_candidates(
                candidate_id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES pit_crew_evidence(event_id),
                task_id TEXT NOT NULL, relationship TEXT NOT NULL, related_task_id TEXT,
                objective TEXT NOT NULL, assumption_id TEXT, assumption TEXT,
                packet TEXT NOT NULL, packet_sha256 TEXT NOT NULL, evidence TEXT NOT NULL,
                handle_json TEXT NOT NULL, created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pit_crew_evaluations(
                candidate_id TEXT NOT NULL REFERENCES pit_crew_candidates(candidate_id), mode TEXT NOT NULL,
                selection TEXT NOT NULL, fallback TEXT, provider_calls INTEGER NOT NULL,
                input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
                elapsed_seconds REAL NOT NULL, created_at REAL NOT NULL,
                PRIMARY KEY(candidate_id, mode)
            );
            CREATE TABLE IF NOT EXISTS pit_crew_emissions(
                emission_key TEXT PRIMARY KEY, event_id TEXT NOT NULL, recipient TEXT NOT NULL,
                task_id TEXT NOT NULL, relationship TEXT NOT NULL, candidate_id TEXT NOT NULL,
                state TEXT NOT NULL, mailbox_id TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                error TEXT, UNIQUE(event_id, recipient, task_id, relationship)
            );
            CREATE INDEX IF NOT EXISTS pit_crew_candidates_created
                ON pit_crew_candidates(created_at, candidate_id);
        """)
        # Existing pre-release state can predate the bounded replacement anchor.
        # Additive migration keeps it readable without making package state own
        # behavior or requiring an out-of-band migration command.
        columns = {row[1] for row in db.execute("PRAGMA table_info(pit_crew_sources)")}
        for name, declaration in (("anchor_offset", "INTEGER"), ("anchor_length", "INTEGER"),
                                  ("anchor_sha256", "TEXT")):
            if name not in columns:
                db.execute("ALTER TABLE pit_crew_sources ADD COLUMN " + name + " " + declaration)
        # ``executescript`` commits any pending transaction in sqlite3.  Establish
        # the write lock only after schema setup so source cursors and emission
        # reservations are actually serialized across concurrent callers.
        db.execute("BEGIN IMMEDIATE")
        yield db
        db.commit()
    except (OSError, sqlite3.Error) as error:
        try:
            db.rollback()
        except (sqlite3.Error, UnboundLocalError):
            pass
        raise PitCrewError("pit_crew_state_unavailable") from error
    finally:
        try:
            db.close()
        except UnboundLocalError:
            pass


def _read_incremental(workspace: Path, assignment: Mapping[str, Any], config: Mapping[str, Any],
                      *, source: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = _source_path(workspace, assignment, source)
    if not path.exists():
        return [], {"source": _relative(workspace, path), "missing": True, "recovered": False}
    try:
        marker, size = _event_path_marker(path), path.stat().st_size
    except OSError as error:
        raise PitCrewError("pit_crew_source_unavailable") from error
    source_name = _relative(workspace, path)
    def anchor(end: int) -> tuple[int, int, str]:
        length = min(4096, end)
        offset = end - length
        try:
            with path.open("rb") as stream:
                stream.seek(offset)
                raw = stream.read(length)
        except OSError as error:
            raise PitCrewError("pit_crew_source_unavailable") from error
        if len(raw) != length:
            raise PitCrewError("pit_crew_source_changed_during_read")
        return offset, length, _digest(raw)

    with _locked(config) as db:
        row = db.execute("SELECT marker,cursor,generation,anchor_offset,anchor_length,anchor_sha256 FROM pit_crew_sources WHERE source_path=?",
                         (source_name,)).fetchone()
        cursor, generation, recovered = 0, 0, False
        if row is not None:
            cursor, generation = int(row["cursor"]), int(row["generation"])
            if row["marker"] != marker or size < cursor:
                cursor, generation, recovered = 0, generation + 1, True
            elif row["anchor_sha256"] is not None:
                try:
                    observed_anchor = anchor(cursor)
                except PitCrewError:
                    cursor, generation, recovered = 0, generation + 1, True
                else:
                    expected_anchor = (row["anchor_offset"], row["anchor_length"], row["anchor_sha256"])
                    if observed_anchor != expected_anchor:
                        cursor, generation, recovered = 0, generation + 1, True
        initial_truncated = False
        if cursor == 0 and size > config["max_scan_bytes"]:
            cursor = max(0, size - config["max_scan_bytes"])
            initial_truncated = cursor > 0
        try:
            with path.open("rb") as stream:
                stream.seek(cursor)
                raw = stream.read(config["max_scan_bytes"] + 1)
        except OSError as error:
            raise PitCrewError("pit_crew_source_unavailable") from error
        if len(raw) > config["max_scan_bytes"]:
            raw = raw[:config["max_scan_bytes"]]
        if initial_truncated and b"\n" in raw:
            discarded, raw = raw.split(b"\n", 1)
            cursor += len(discarded) + 1
        complete = raw.rfind(b"\n") + 1
        raw = raw[:complete]
        end = cursor + len(raw)
        anchor_offset, anchor_length, anchor_sha = anchor(end)
    records: list[dict[str, Any]] = []
    offset = cursor
    for line in raw.splitlines(keepends=True):
        clean = line.rstrip(b"\r\n")
        length = len(line)
        if clean:
            try:
                record = json.loads(clean)
            except (UnicodeDecodeError, ValueError):
                record = None
            if isinstance(record, dict):
                records.append({"record": record, "offset": offset, "length": length,
                                "sha256": _digest(clean), "generation": generation})
        offset += length
    # Do not advance the durable cursor yet.  A process failure after this point
    # must replay (and harmlessly deduplicate) the source records rather than
    # skip evidence whose candidates were not durably stored.  ``run`` commits
    # this checkpoint only after ``_store_candidates`` succeeds.
    return records, {"source": source_name, "cursor": end, "generation": generation,
                     "recovered": recovered, "initial_truncated": initial_truncated,
                     "_checkpoint": {"marker": marker, "cursor": end, "generation": generation,
                                     "anchor_offset": anchor_offset, "anchor_length": anchor_length,
                                     "anchor_sha256": anchor_sha}}


def _commit_source(workspace: Path, config: Mapping[str, Any], source_info: Mapping[str, Any], now: float) -> bool:
    """Advance a source only after its compact evidence was made durable.

    Concurrent readers may observe overlapping append-only bytes.  The source
    table therefore only moves forward for a generation; a later replacement
    generation wins over an older observer.  If the source changed after the
    read, leave its cursor untouched so the next pass recovers it rather than
    recording an unjustified high-water mark.
    """
    checkpoint = source_info.get("_checkpoint")
    source_name = source_info.get("source")
    if not isinstance(checkpoint, dict) or not isinstance(source_name, str):
        return False
    required = ("marker", "cursor", "generation", "anchor_offset", "anchor_length", "anchor_sha256")
    if any(name not in checkpoint for name in required):
        return False
    try:
        path = _source_path(Path(workspace), {}, Path(workspace) / source_name)
        marker, size = _event_path_marker(path), path.stat().st_size
        cursor = int(checkpoint["cursor"])
        anchor_offset, anchor_length = int(checkpoint["anchor_offset"]), int(checkpoint["anchor_length"])
        if marker != checkpoint["marker"] or size < cursor:
            return False
        with path.open("rb") as stream:
            stream.seek(anchor_offset)
            anchor = stream.read(anchor_length)
        if (len(anchor) != anchor_length or _digest(anchor) != checkpoint["anchor_sha256"]):
            return False
        generation = int(checkpoint["generation"])
    except (OSError, TypeError, ValueError, PitCrewError):
        return False
    with _locked(config) as db:
        db.execute("""INSERT INTO pit_crew_sources(source_path,marker,cursor,generation,anchor_offset,
                   anchor_length,anchor_sha256,updated_at) VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(source_path) DO UPDATE SET marker=excluded.marker,cursor=excluded.cursor,
                   generation=excluded.generation,anchor_offset=excluded.anchor_offset,
                   anchor_length=excluded.anchor_length,anchor_sha256=excluded.anchor_sha256,
                   updated_at=excluded.updated_at
                   WHERE excluded.generation > pit_crew_sources.generation
                      OR (excluded.generation = pit_crew_sources.generation
                          AND excluded.marker = pit_crew_sources.marker
                          AND excluded.cursor >= pit_crew_sources.cursor)""",
                   (source_name, checkpoint["marker"], cursor, generation, anchor_offset, anchor_length,
                    checkpoint["anchor_sha256"], now))
    return True


def _store_candidates(workspace: Path, assignment: Mapping[str, Any], config: Mapping[str, Any],
                      records: list[dict[str, Any]], now: float) -> list[str]:
    facts = _task_facts(workspace, assignment)
    own_task_id = assignment.get("task_id")
    expected_worker = assignment.get("name")
    if not isinstance(own_task_id, str) or not own_task_id:
        return []
    new: list[str] = []
    for item in records:
        record = item["record"]
        task_id = record.get("task_id")
        # The worker-library source is assignment-bound.  Peer task facts are
        # relationship context only; a row claiming another task cannot become
        # evidence for this assignment merely because that task is active.
        if task_id != own_task_id or task_id not in facts:
            continue
        if isinstance(expected_worker, str) and record.get("worker_name") != expected_worker:
            continue
        fact = facts[task_id]
        for evidence_id, evidence, item_id in _evidence_items(record, task_id):
            handle = {"path": item.get("source"), "offset": item["offset"], "length": item["length"],
                      "sha256": item["sha256"], "generation": item["generation"], "item_id": item_id}
            if not isinstance(handle["path"], str):
                handle["path"] = _relative(workspace, _source_path(workspace, assignment))
            with _locked(config) as db:
                existing = db.execute("SELECT event_id FROM pit_crew_evidence WHERE event_id=?", (evidence_id,)).fetchone()
                db.execute("""INSERT INTO pit_crew_evidence(event_id,source_path,source_offset,source_length,
                           source_sha256,source_generation,task_id,item_id,evidence,observed_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET
                           source_path=excluded.source_path,source_offset=excluded.source_offset,
                           source_length=excluded.source_length,source_sha256=excluded.source_sha256,
                           source_generation=excluded.source_generation,evidence=excluded.evidence""",
                           (evidence_id, handle["path"], handle["offset"], handle["length"], handle["sha256"],
                            handle["generation"], task_id, item_id, evidence, now))
                if existing is not None:
                    db.execute("UPDATE pit_crew_candidates SET handle_json=? WHERE event_id=?",
                               (_encoded(handle).decode("utf-8"), evidence_id))
                    continue
                candidates = _candidate_rows(evidence_id, evidence, fact, facts, handle)
                for candidate in candidates[:config["max_candidates"]]:
                    db.execute("""INSERT OR IGNORE INTO pit_crew_candidates(candidate_id,event_id,task_id,
                               relationship,related_task_id,objective,assumption_id,assumption,packet,
                               packet_sha256,evidence,handle_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                               (candidate["candidate_id"], candidate["event_id"], candidate["task_id"],
                                candidate["relationship"], candidate["related_task_id"], candidate["objective"],
                                candidate["assumption_id"], candidate["assumption"], candidate["packet"],
                                candidate["packet_sha256"], candidate["evidence"],
                                _encoded(candidate["handle"]).decode("utf-8"), now))
                    new.append(candidate["candidate_id"])
    return new


def _fresh(workspace: Path, assignment: Mapping[str, Any], candidate: Mapping[str, Any]) -> bool:
    relationship = candidate.get("relationship")
    if relationship not in RELATIONSHIPS:
        return False
    if not _active_task(workspace, assignment, str(candidate["task_id"])):
        return False
    try:
        packet = Path(str(candidate["packet"])).resolve()
        packet.relative_to(workspace / ".de67" / "state" / "worker-dispatch")
        if _digest(packet.read_bytes()) != candidate["packet_sha256"]:
            return False
        handle = json.loads(candidate["handle_json"])
        # Candidate state is durable but not an authority to read arbitrary
        # workspace files.  Revalidate the original worker-event root before
        # reopening its byte handle.
        path = _source_path(workspace, assignment, workspace / handle["path"])
        with path.open("rb") as stream:
            stream.seek(int(handle["offset"]))
            raw = stream.read(int(handle["length"]))
        if _digest(raw.rstrip(b"\r\n")) != handle["sha256"]:
            return False
        related = candidate.get("related_task_id")
        if relationship == "duplicated_investigation":
            # The peer is part of the claimed relationship, so its current task
            # status and objective must still match before we can name it in an
            # advisory.  A settled or re-scoped peer fails closed.
            if not isinstance(related, str) or not related:
                return False
            peer = _task_facts(workspace, assignment).get(related)
            return peer is not None and peer.objective == candidate.get("assumption")
        return related is None
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _choice_body(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {"schema": "de67.pit-crew.choice.v1", "choice": {
        "candidate_id": candidate["candidate_id"], "relationship": candidate["relationship"],
        "task_id": candidate["task_id"], "related_task_id": candidate["related_task_id"],
        "objective": candidate["objective"], "assumption_id": candidate["assumption_id"],
        "assumption": candidate["assumption"], "evidence": candidate["evidence"],
        "handle": json.loads(candidate["handle_json"]),
    }, "allowed": ["notice", "none"]}


def _usage(value: Any) -> tuple[int, int]:
    usage = value.get("usage", {}) if isinstance(value, dict) else {}
    if not isinstance(usage, dict):
        return 0, 0
    values: list[int] = []
    for field in ("input_tokens", "output_tokens"):
        value = usage.get(field, 0)
        values.append(value if type(value) is int and value >= 0 else 0)
    return values[0], values[1]


def _selected(value: Any, candidate: Mapping[str, Any]) -> bool:
    if not isinstance(value, dict) or set(value) - {"choice", "usage"}:
        raise PitCrewError("pit_crew_invalid_selection")
    choice = value.get("choice")
    if choice == "none":
        return False
    if not isinstance(choice, dict) or set(choice) != {"candidate_id", "relationship"}:
        raise PitCrewError("pit_crew_invalid_selection")
    if choice["candidate_id"] != candidate["candidate_id"] or choice["relationship"] != candidate["relationship"]:
        raise PitCrewError("pit_crew_invalid_selection")
    return True


def _record_evaluation(config: Mapping[str, Any], candidate_id: str, mode: str, selection: str,
                       fallback: str | None, calls: int, input_tokens: int, output_tokens: int,
                       elapsed: float, now: float) -> None:
    with _locked(config) as db:
        db.execute("""INSERT OR REPLACE INTO pit_crew_evaluations(candidate_id,mode,selection,fallback,
                   provider_calls,input_tokens,output_tokens,elapsed_seconds,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                   (candidate_id, mode, selection, fallback, calls, input_tokens, output_tokens, elapsed, now))


def _already_evaluated(config: Mapping[str, Any], candidate_id: str, mode: str) -> bool:
    with _locked(config) as db:
        row = db.execute("SELECT fallback FROM pit_crew_evaluations WHERE candidate_id=? AND mode=?",
                         (candidate_id, mode)).fetchone()
    # A caller that previously had no selector may make one explicit, safe local
    # evaluation later.  Other failures are retained rather than auto-retried.
    return row is not None and row["fallback"] != "selection_transport_unavailable"


def _cooling(config: Mapping[str, Any], candidate: Mapping[str, Any], now: float) -> bool:
    if config["cooldown_seconds"] == 0:
        return False
    with _locked(config) as db:
        row = db.execute("""SELECT 1 FROM pit_crew_emissions WHERE recipient='coordinator' AND task_id=?
                          AND relationship=? AND state IN ('queued','delivered') AND updated_at>=?
                          ORDER BY updated_at DESC LIMIT 1""",
                         (candidate["task_id"], candidate["relationship"], now - config["cooldown_seconds"])).fetchone()
    return row is not None


def _message(candidate: Mapping[str, Any], emission_key: str) -> str:
    handle = json.loads(candidate["handle_json"])
    relation = candidate["relationship"].replace("_", " ")
    target = (" Related active task: " + candidate["related_task_id"] + "."
              if candidate["related_task_id"] else "")
    assumption = (" Assumption " + candidate["assumption_id"] + " may be challenged."
                  if candidate["assumption_id"] else "")
    return ("Pit Crew evidence advisory [" + emission_key + "]: possible " + relation +
            " for active task " + candidate["task_id"] + "." + target + assumption +
            " Original evidence: " + handle["path"] + " @ byte " + str(handle["offset"]) +
            " (sha256 " + handle["sha256"] + "). This is advisory evidence only; coordinator authority remains unchanged.")


def _matching_mailbox(workspace: Path, emission_key: str) -> dict[str, Any] | None:
    try:
        mailbox = _mailbox_module()
        root = mailbox.mailbox(workspace, "coordinator")
        for path in root.glob("*.json"):
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("sender") == "pit-crew:" + emission_key and value.get("recipient") == "coordinator":
                return value
    except (OSError, UnicodeError, ValueError, PitCrewError):
        return None
    return None


def _deliver(workspace: Path, config: Mapping[str, Any], candidate: Mapping[str, Any], now: float) -> str:
    key = _digest({"event_id": candidate["event_id"], "recipient": "coordinator",
                   "task_id": candidate["task_id"], "relationship": candidate["relationship"]})
    created = False
    with _locked(config) as db:
        row = db.execute("SELECT state,mailbox_id FROM pit_crew_emissions WHERE emission_key=?", (key,)).fetchone()
        if row is None:
            db.execute("""INSERT INTO pit_crew_emissions(emission_key,event_id,recipient,task_id,relationship,
                       candidate_id,state,mailbox_id,created_at,updated_at,error) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                       (key, candidate["event_id"], "coordinator", candidate["task_id"], candidate["relationship"],
                        candidate["candidate_id"], "prepared", None, now, now, None))
            created = True
        elif row["mailbox_id"]:
            return "already_queued"
    # A pre-existing prepare is intentionally uncertain: a caller may have died
    # after enqueue but before recording its UUID.  Reconcile the real mailbox;
    # never blindly resend a coordinator advisory.
    observed = _matching_mailbox(workspace, key)
    if observed is not None:
        with _locked(config) as db:
            db.execute("UPDATE pit_crew_emissions SET state='queued',mailbox_id=?,updated_at=?,error=NULL WHERE emission_key=?",
                       (observed.get("id"), now, key))
        return "reconciled"
    if not created:
        with _locked(config) as db:
            db.execute("UPDATE pit_crew_emissions SET state='uncertain',updated_at=?,error=? WHERE emission_key=?",
                       (now, "mailbox_record_not_found_after_prepared", key))
        return "uncertain"
    try:
        mailbox = _mailbox_module()
        message = mailbox.enqueue(workspace, "coordinator", "pit-crew:" + key, _message(candidate, key))
    except Exception:
        with _locked(config) as db:
            db.execute("UPDATE pit_crew_emissions SET state='uncertain',updated_at=?,error=? WHERE emission_key=?",
                       (now, "mailbox_enqueue_uncertain", key))
        return "uncertain"
    with _locked(config) as db:
        db.execute("UPDATE pit_crew_emissions SET state='queued',mailbox_id=?,updated_at=?,error=NULL WHERE emission_key=?",
                   (message.get("id"), now, key))
    return "queued"


def _pending(config: Mapping[str, Any], mode: str, limit: int) -> list[sqlite3.Row]:
    with _locked(config) as db:
        rows = db.execute("""SELECT c.* FROM pit_crew_candidates c
                          LEFT JOIN pit_crew_evaluations e ON e.candidate_id=c.candidate_id AND e.mode=?
                          WHERE e.candidate_id IS NULL OR e.fallback='selection_transport_unavailable'
                          ORDER BY c.created_at,c.candidate_id LIMIT ?""", (mode, limit)).fetchall()
    return rows


def run(workspace: Path, assignment: Mapping[str, Any], *, config: Mapping[str, Any] | None = None,
        source: Path | None = None, selector: Callable[[dict[str, Any], float], Any] | None = None,
        now: float | None = None) -> dict[str, Any]:
    """Incrementally derive, validate, evaluate, and (only in ``on``) enqueue notices.

    ``selector`` is intentionally dependency-injected.  It is suitable for an
    owner-authorized future adapter or a controlled stub; this package has no
    fallback HTTP transport and never reads a credential.
    """
    workspace = Path(workspace).resolve()
    config = configuration(workspace) if config is None else validate_config(workspace, dict(config))
    if config["mode"] == "off":
        return {"mode": "off", "records": 0, "candidates": [], "evaluations": [], "deliveries": []}
    now = time.time() if now is None else _number(now, "now", 0)
    records, source_info = _read_incremental(workspace, assignment, config, source=source)
    # Preserve the exact source passed by a direct caller while the normal
    # boundary derives it from the assignment ID.
    if source is not None:
        for record in records:
            record["source"] = _relative(workspace, _source_path(workspace, assignment, source))
    candidate_ids = _store_candidates(workspace, assignment, config, records, now)
    source_info = dict(source_info)
    source_info["cursor_committed"] = _commit_source(workspace, config, source_info, now)
    source_info.pop("_checkpoint", None)
    evaluations: list[dict[str, Any]] = []
    deliveries: list[dict[str, Any]] = []
    if selector is None:
        return {"mode": config["mode"], "records": len(records), "candidates": candidate_ids,
                "evaluations": evaluations, "deliveries": deliveries, "source": source_info,
                "limitations": "Provider-free package; no selector was supplied at this boundary."}
    for candidate in _pending(config, config["mode"], config["max_admissions"]):
        candidate = dict(candidate)
        if _already_evaluated(config, candidate["candidate_id"], config["mode"]):
            continue
        if not _fresh(workspace, assignment, candidate):
            _record_evaluation(config, candidate["candidate_id"], config["mode"], "none", "stale_or_unknown_ids",
                               0, 0, 0, 0, now)
            evaluations.append({"candidate_id": candidate["candidate_id"], "fallback": "stale_or_unknown_ids"})
            continue
        if _cooling(config, candidate, now):
            _record_evaluation(config, candidate["candidate_id"], config["mode"], "none", "cooldown",
                               0, 0, 0, 0, now)
            evaluations.append({"candidate_id": candidate["candidate_id"], "fallback": "cooldown"})
            continue
        if selector is None:
            _record_evaluation(config, candidate["candidate_id"], config["mode"], "none",
                               "selection_transport_unavailable", 0, 0, 0, 0, now)
            evaluations.append({"candidate_id": candidate["candidate_id"], "fallback": "selection_transport_unavailable"})
            continue
        started, calls, input_tokens, output_tokens = time.monotonic(), 0, 0, 0
        try:
            guard = _guard_module()
            body = _choice_body(candidate)
            result = guard.guarded_dispatch(config["provider_guard"], body, request_bytes=len(_encoded(body)),
                                             timeout=config["selection_timeout_seconds"], transport=selector,
                                             logical_request_id="pit-crew:" + candidate["candidate_id"])
            calls = result.attempts
            input_tokens, output_tokens = _usage(result.value)
            selected = _selected(result.value, candidate)
            if not _fresh(workspace, assignment, candidate):
                raise PitCrewError("stale_or_unknown_ids")
            _record_evaluation(config, candidate["candidate_id"], config["mode"],
                               "notice" if selected else "none", None, calls, input_tokens, output_tokens,
                               time.monotonic() - started, now)
            evaluations.append({"candidate_id": candidate["candidate_id"], "selection": "notice" if selected else "none",
                                "provider_calls": calls, "usage": {"input_tokens": input_tokens,
                                                                        "output_tokens": output_tokens}})
            if selected and config["mode"] == "on":
                delivery = _deliver(workspace, config, candidate, now)
                deliveries.append({"candidate_id": candidate["candidate_id"], "state": delivery})
        except Exception as error:
            attempts = getattr(error, "attempts", None)
            if type(attempts) is int and attempts >= 0:
                calls = max(calls, attempts)
            fallback = (str(error) if isinstance(error, PitCrewError) else
                        getattr(error, "reason", None) or "selection_guard_failure")
            _record_evaluation(config, candidate["candidate_id"], config["mode"], "none", str(fallback), calls,
                               input_tokens, output_tokens, time.monotonic() - started, now)
            evaluations.append({"candidate_id": candidate["candidate_id"], "fallback": str(fallback),
                                "provider_calls": calls})
    return {"mode": config["mode"], "records": len(records), "candidates": candidate_ids,
            "evaluations": evaluations, "deliveries": deliveries, "source": source_info,
            "limitations": "Provider-free package; selector output is advisory only and no coordinator action is implied."}


def observe_boundary(workspace: Path, assignment: Mapping[str, Any]) -> None:
    """Best-effort worker-library hook.  It must never disturb normal coordination."""
    try:
        config = configuration(Path(workspace))
        if config["mode"] != "off":
            # No selector is supplied at the normal event boundary.  This keeps
            # slow/provider work out of the coordinator's critical path and makes
            # the package provider-free until an explicit caller evaluates it.
            run(Path(workspace), assignment, config=config)
    except Exception:
        # Broken, absent, malformed, or unfunded optional integration is inert.
        return
