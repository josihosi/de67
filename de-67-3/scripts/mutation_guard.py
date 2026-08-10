#!/usr/bin/env python3
"""Validate DE-67-3 Markdown mutations without constraining their prose."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sqlite3
import sys


TASK_GUIDELINES = "test-and-task-guidelines.md"
ORCHESTRATOR_GUIDELINES = "orchestrator-guidelines.md"
GUIDELINE_FILES = (TASK_GUIDELINES, ORCHESTRATOR_GUIDELINES)
DFS_FILE = "DFS.md"
MUTATION_LEDGER = "mutation-suggestions.md"
RANDOM_MUTATION_LANES = (*GUIDELINE_FILES, DFS_FILE)
INCIDENT_KINDS = ("deadline_miss", "integrity_breach")
SKILL_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_GUIDELINES_ROOT = SKILL_ROOT / "assets" / "environment"

ATX_HEADING = re.compile(r"^[ \t]*#{1,6}[ \t]+\S.*$")
FENCE = re.compile(r"^[ \t]*(?P<marker>`{3,}|~{3,})")
CLAIM_REFERENCE = r"R-[A-Za-z0-9._-]+[ \t]+—[ \t]+\S.*?"
CLAIM_ID = re.compile(r"^R-[A-Za-z0-9._-]+$")
ACTIVE_ITEM = re.compile(rf"^- \[ \] (?P<reference>{CLAIM_REFERENCE})[ \t]*$")
RED_CLAIM = re.compile(
    rf"^(?P<lead>- )\[ \] 🔴 (?P<label>{CLAIM_REFERENCE})(?P<trailing>[ \t]*)$"
)
STABLE_CLAIM = re.compile(
    rf"^- \[(?P<status>[ xX])\](?P<red> 🔴)? "
    rf"(?P<label>{CLAIM_REFERENCE})(?P<trailing>[ \t]*)$"
)
PROTECTED_DFS_SECTIONS = (
    "## Functional contract",
    "## Project language and terminology",
)


class GuardError(RuntimeError):
    """The proposed Markdown state breaks a frozen DE-67 invariant."""


def read_markdown(path: Path) -> str:
    if not path.is_file():
        raise GuardError(f"Missing Markdown file: {path}")
    return path.read_text(encoding="utf-8")


def validate_consumed_mutation_ledger(candidate: Path) -> None:
    """Require a successful mutation candidate to consume all scratch suggestions."""

    expected = read_markdown(CANONICAL_GUIDELINES_ROOT / MUTATION_LEDGER)
    actual = read_markdown(candidate)
    if actual != expected:
        raise GuardError(
            "A successful mutation must reset mutation-suggestions.md to its empty template"
        )


def markdown_headings(text: str) -> tuple[str, ...]:
    """Return exact ATX headings outside fenced examples."""

    headings: list[str] = []
    fence_character: str | None = None
    for line in text.splitlines():
        fence = FENCE.match(line)
        if fence:
            character = fence.group("marker")[0]
            if fence_character is None:
                fence_character = character
            elif fence_character == character:
                fence_character = None
            continue
        if fence_character is None and ATX_HEADING.match(line):
            headings.append(line.rstrip())
    return tuple(headings)


def _require_frozen_headings(name: str, baseline: str, candidate: str) -> None:
    expected = markdown_headings(read_markdown(CANONICAL_GUIDELINES_ROOT / name))
    before = markdown_headings(baseline)
    after = markdown_headings(candidate)
    if not expected:
        raise GuardError(f"Canonical {name} has no frozen Markdown headings")
    if before != expected:
        raise GuardError(f"{name} baseline headings differ from the canonical template")
    if after != expected:
        raise GuardError(f"{name} candidate headings differ from the canonical template")


def validate_guideline_mutation(
    baseline_root: Path,
    candidate_root: Path,
    *,
    broader_mutation: bool,
) -> tuple[str, ...]:
    """Validate mutable bodies while keeping every guideline heading frozen."""

    if not isinstance(broader_mutation, bool):
        raise GuardError("Guideline mutation scope must be derived from a stored incident")
    changed: list[str] = []
    for name in GUIDELINE_FILES:
        baseline = read_markdown(baseline_root / name)
        candidate = read_markdown(candidate_root / name)
        _require_frozen_headings(name, baseline, candidate)
        if baseline != candidate:
            changed.append(name)

    changed_set = set(changed)
    for name in changed:
        baseline = read_markdown(baseline_root / name)
        candidate = read_markdown(candidate_root / name)
        if _meaningful_markdown(baseline) == _meaningful_markdown(candidate):
            raise GuardError(f"{name} mutation cannot be whitespace-only")
    if broader_mutation:
        if changed_set != set(GUIDELINE_FILES):
            raise GuardError(
                "A third-miss or integrity mutation must change both guideline bodies"
            )
    elif changed_set != {TASK_GUIDELINES}:
        raise GuardError(
            "An ordinary miss must change task/test guidance and leave orchestrator guidance unchanged"
        )
    return tuple(changed)


def _meaningful_markdown(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def random_review_from_state(
    state: str | Path,
    lineage_id: str,
    cycle_number: int,
) -> str:
    """Read one exact due random-review lane without changing machine state."""

    state_path = Path(state).expanduser()
    if not state_path.is_file():
        raise GuardError(f"Deadline state does not exist: {state_path}")
    try:
        connection = sqlite3.connect(state_path.resolve().as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT selected_lane, due_task_id, resolution_evidence
            FROM random_mutation_cycles
            WHERE lineage_id = ? AND cycle_number = ?
            """,
            (lineage_id, cycle_number),
        ).fetchone()
    except sqlite3.Error as error:
        raise GuardError(f"Cannot read random mutation state: {error}") from error
    finally:
        if "connection" in locals():
            connection.close()

    if row is None:
        raise GuardError(
            f"Missing random mutation cycle for {lineage_id}/{cycle_number}"
        )
    if row["due_task_id"] is None:
        raise GuardError("Random mutation cycle is not due")
    if row["resolution_evidence"] is not None:
        raise GuardError("Random mutation cycle is already resolved")
    lane = str(row["selected_lane"])
    if lane not in RANDOM_MUTATION_LANES:
        raise GuardError(f"Unsupported random mutation lane: {lane}")
    return lane


def validate_random_review_mutation(
    baseline_root: Path,
    candidate_root: Path,
    *,
    selected_lane: str,
) -> tuple[str, ...]:
    """Validate exactly the stored random lane, including a safe DFS no-op."""

    if selected_lane not in RANDOM_MUTATION_LANES:
        raise GuardError(f"Unsupported random mutation lane: {selected_lane}")
    baseline_files = {
        name: read_markdown(baseline_root / name)
        for name in (*GUIDELINE_FILES, DFS_FILE)
    }
    candidate_files = {
        name: read_markdown(candidate_root / name)
        for name in (*GUIDELINE_FILES, DFS_FILE)
    }
    for name in GUIDELINE_FILES:
        _require_frozen_headings(
            name, baseline_files[name], candidate_files[name]
        )

    changed = tuple(
        name
        for name in (*GUIDELINE_FILES, DFS_FILE)
        if baseline_files[name] != candidate_files[name]
    )
    if selected_lane in GUIDELINE_FILES:
        if changed != (selected_lane,):
            raise GuardError(
                f"Random review selected {selected_lane}; no other mutable file may change"
            )
        if _meaningful_markdown(baseline_files[selected_lane]) == _meaningful_markdown(
            candidate_files[selected_lane]
        ):
            raise GuardError("Random guideline mutation cannot be whitespace-only")
        return changed

    if any(name in changed for name in GUIDELINE_FILES):
        raise GuardError("A DFS random review cannot change either guideline file")
    if not changed:
        return ()
    if changed != (DFS_FILE,):
        raise GuardError("An applied DFS random review must change only DFS.md")
    validate_random_dfs_mutation(
        baseline_root / DFS_FILE,
        candidate_root / DFS_FILE,
    )
    return changed


def broader_mutation_from_incident(
    state: str | Path,
    lineage_id: str,
    task_id: str,
    incident_kind: str,
) -> bool:
    """Derive guideline scope from one exact, stored deadline incident."""

    if incident_kind not in INCIDENT_KINDS:
        raise GuardError(f"Unsupported incident kind: {incident_kind}")
    state_path = Path(state).expanduser()
    if not state_path.is_file():
        raise GuardError(f"Deadline state does not exist: {state_path}")
    try:
        connection = sqlite3.connect(state_path.resolve().as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT cadence_threshold
            FROM incidents
            WHERE lineage_id = ? AND task_id = ? AND kind = ?
            """,
            (lineage_id, task_id, incident_kind),
        ).fetchone()
    except sqlite3.Error as error:
        raise GuardError(f"Cannot read deadline state: {error}") from error
    finally:
        if "connection" in locals():
            connection.close()

    if row is None:
        raise GuardError(
            f"Missing stored {incident_kind} incident for {lineage_id}/{task_id}"
        )
    return incident_kind == "integrity_breach" or row["cadence_threshold"] is not None


def _outside_fences(text: str):
    fence_character: str | None = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        fence = FENCE.match(line)
        if fence:
            character = fence.group("marker")[0]
            if fence_character is None:
                fence_character = character
            elif fence_character == character:
                fence_character = None
            continue
        if fence_character is None:
            yield line_number, line


def _normalize_reference(value: str) -> str:
    normalized = " ".join(value.strip().split())
    if normalized.startswith("🔴 "):
        normalized = normalized[2:].strip()
    for prefix in ("DFS claim:", "Claim:"):
        if normalized.casefold().startswith(prefix.casefold()):
            normalized = normalized[len(prefix) :].strip()
            break
    return normalized


def _stable_key(value: str) -> str:
    for separator in (" — ", " – ", ": "):
        if separator in value:
            return value.split(separator, 1)[0].strip()
    return value


def _same_claim(reference: str, label: str) -> bool:
    return reference == label or _stable_key(reference) == _stable_key(label)


def _selected_claim_id(selected_claim: str) -> str:
    claim_id = _stable_key(_normalize_reference(selected_claim))
    if not CLAIM_ID.fullmatch(claim_id):
        raise GuardError(f"Selected claim has no valid R-id: {selected_claim}")
    return claim_id


def validate_accepted_task_state(
    state: str | Path,
    lineage_id: str,
    task_id: str,
    selected_claim: str,
) -> str:
    """Require accepted, matching, breach-free task state before DFS closure."""

    state_path = Path(state).expanduser()
    if not state_path.is_file():
        raise GuardError(f"Deadline state does not exist: {state_path}")
    expected_claim = _selected_claim_id(selected_claim)
    try:
        connection = sqlite3.connect(state_path.resolve().as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT tasks.claim_id,
                   tasks.completed_at,
                   tasks.completion_evidence,
                   tasks.integrity_breached_at,
                   EXISTS (
                       SELECT 1 FROM incidents
                       WHERE incidents.lineage_id = tasks.lineage_id
                         AND incidents.task_id = tasks.task_id
                         AND incidents.kind = 'integrity_breach'
                   ) AS has_integrity_incident
            FROM tasks
            WHERE tasks.lineage_id = ? AND tasks.task_id = ?
            """,
            (lineage_id, task_id),
        ).fetchone()
    except sqlite3.Error as error:
        raise GuardError(f"Cannot read deadline state: {error}") from error
    finally:
        if "connection" in locals():
            connection.close()

    if row is None:
        raise GuardError(f"Unknown deadline task: {lineage_id}/{task_id}")
    if row["claim_id"] != expected_claim:
        raise GuardError(
            f"Deadline task claim {row['claim_id']} does not match selected claim {expected_claim}"
        )
    if row["integrity_breached_at"] is not None or row["has_integrity_incident"]:
        raise GuardError("An integrity breach invalidates DFS completion")
    if row["completed_at"] is None:
        raise GuardError("Deadline task has not been accepted")
    evidence = row["completion_evidence"]
    if evidence is None or not str(evidence).strip():
        raise GuardError("Accepted deadline task has no completion evidence")
    return expected_claim


def worker_finding_from_state(
    state: str | Path,
    lineage_id: str,
    task_id: str,
) -> tuple[str, str]:
    """Read one exact, unresolved worker finding without mutating deadline state."""

    state_path = Path(state).expanduser()
    if not state_path.is_file():
        raise GuardError(f"Deadline state does not exist: {state_path}")
    try:
        connection = sqlite3.connect(state_path.resolve().as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT tasks.claim_id,
                   tasks.completed_at,
                   tasks.integrity_breached_at,
                   worker_findings.kind,
                   worker_findings.evidence,
                   EXISTS (
                       SELECT 1 FROM incidents
                       WHERE incidents.lineage_id = tasks.lineage_id
                         AND incidents.task_id = tasks.task_id
                         AND incidents.kind = 'integrity_breach'
                   ) AS has_integrity_incident
            FROM tasks
            JOIN worker_findings
              ON worker_findings.lineage_id = tasks.lineage_id
             AND worker_findings.task_id = tasks.task_id
            WHERE tasks.lineage_id = ? AND tasks.task_id = ?
            """,
            (lineage_id, task_id),
        ).fetchone()
    except sqlite3.Error as error:
        raise GuardError(f"Cannot read worker finding state: {error}") from error
    finally:
        if "connection" in locals():
            connection.close()

    if row is None:
        raise GuardError(f"Missing stored worker finding for {lineage_id}/{task_id}")
    if row["kind"] not in ("blocker", "unexpected"):
        raise GuardError(f"Unsupported worker finding kind: {row['kind']}")
    if row["evidence"] is None or not str(row["evidence"]).strip():
        raise GuardError("Stored worker finding has no evidence")
    if row["completed_at"] is not None:
        raise GuardError("A completed task cannot authorize DFS expansion")
    if row["integrity_breached_at"] is not None or row["has_integrity_incident"]:
        raise GuardError("An integrity breach invalidates the worker finding")
    return str(row["claim_id"]), str(row["kind"])


def _markdown_sections(text: str) -> tuple[tuple[int, int, str], ...]:
    """Return heading positions and levels outside fenced examples."""

    sections: list[tuple[int, int, str]] = []
    fence_character: str | None = None
    for index, line in enumerate(text.splitlines(keepends=True)):
        body = line.rstrip("\r\n")
        fence = FENCE.match(body)
        if fence:
            character = fence.group("marker")[0]
            if fence_character is None:
                fence_character = character
            elif fence_character == character:
                fence_character = None
            continue
        if fence_character is not None:
            continue
        heading = ATX_HEADING.match(body)
        if heading:
            stripped = body.rstrip()
            sections.append((index, len(stripped) - len(stripped.lstrip("#")), stripped))
    return tuple(sections)


def _exact_markdown_section(text: str, heading: str) -> str:
    lines = text.splitlines(keepends=True)
    sections = _markdown_sections(text)
    matches = [section for section in sections if section[2] == heading]
    if len(matches) != 1:
        raise GuardError(f"DFS must contain exactly one {heading!r} section")
    start, level, _ = matches[0]
    end = len(lines)
    for index, other_level, _ in sections:
        if index > start and other_level <= level:
            end = index
            break
    return "".join(lines[start:end])


def _stable_claim_records(dfs_text: str) -> tuple[tuple[str, str, bool, str], ...]:
    records: list[tuple[str, str, bool, str]] = []
    for _, line in _outside_fences(dfs_text):
        match = STABLE_CLAIM.match(line)
        if match:
            label = _normalize_reference(match.group("label"))
            records.append(
                (
                    _selected_claim_id(label),
                    match.group("status"),
                    match.group("red") is not None,
                    line,
                )
            )
    return tuple(records)


def _claims_by_id(
    records: tuple[tuple[str, str, bool, str], ...],
    version: str,
) -> dict[str, tuple[str, str, bool, str]]:
    claims: dict[str, tuple[str, str, bool, str]] = {}
    for record in records:
        claim_id = record[0]
        if claim_id in claims:
            raise GuardError(f"{version} DFS has duplicate stable claim id: {claim_id}")
        claims[claim_id] = record
    return claims


def _require_baseline_line_subsequence(baseline: str, candidate: str) -> None:
    remaining = iter(candidate.splitlines(keepends=True))
    for baseline_line in baseline.splitlines(keepends=True):
        if not any(line == baseline_line for line in remaining):
            raise GuardError(
                "DFS expansion cannot delete or rewrite any baseline line"
            )


def _validate_append_only_dfs(
    before: Path,
    candidate: Path,
    *,
    task_claim_id: str | None,
) -> tuple[str, ...]:
    baseline = read_markdown(before)
    proposed = read_markdown(candidate)
    for heading in PROTECTED_DFS_SECTIONS:
        if _exact_markdown_section(baseline, heading) != _exact_markdown_section(
            proposed, heading
        ):
            raise GuardError(f"DFS expansion cannot change {heading}")
    _require_baseline_line_subsequence(baseline, proposed)

    baseline_records = _stable_claim_records(baseline)
    candidate_records = _stable_claim_records(proposed)
    baseline_by_id = _claims_by_id(baseline_records, "Baseline")
    candidate_by_id = _claims_by_id(candidate_records, "Candidate")

    if task_claim_id is not None:
        task_claim_id = _selected_claim_id(task_claim_id)
        task_claim = baseline_by_id.get(task_claim_id)
        if task_claim is None or task_claim[1] != " " or not task_claim[2]:
            raise GuardError(
                "Worker finding task claim is not exactly one still-red DFS claim: "
                f"{task_claim_id}"
            )

    candidate_positions = {
        record[0]: index for index, record in enumerate(candidate_records)
    }
    prior_position = -1
    for record in baseline_records:
        claim_id = record[0]
        candidate_record = candidate_by_id.get(claim_id)
        if candidate_record is None:
            raise GuardError(f"DFS expansion cannot delete stable claim {claim_id}")
        if candidate_record[3] != record[3]:
            raise GuardError(
                f"DFS expansion cannot rename, rewrite, or change status of stable claim {claim_id}"
            )
        position = candidate_positions[claim_id]
        if position <= prior_position:
            raise GuardError("DFS expansion cannot reorder existing stable claims")
        prior_position = position

    new_records = [
        record for record in candidate_records if record[0] not in baseline_by_id
    ]
    if not new_records:
        raise GuardError("DFS expansion must add at least one new red claim")
    for record in new_records:
        if record[1] != " " or not record[2] or RED_CLAIM.match(record[3]) is None:
            raise GuardError(f"New DFS claim must be unchecked and red: {record[0]}")
    return tuple(record[0] for record in new_records)


def validate_dfs_expansion(before: Path, candidate: Path, task_claim_id: str) -> tuple[str, ...]:
    """Preserve the frontier for an expansion authorized by a worker finding."""

    return _validate_append_only_dfs(
        before,
        candidate,
        task_claim_id=task_claim_id,
    )


def validate_random_dfs_mutation(before: Path, candidate: Path) -> tuple[str, ...]:
    """Allow only a same-contract append-only DFS refinement with new red work."""

    return _validate_append_only_dfs(
        before,
        candidate,
        task_claim_id=None,
    )


def red_dfs_claims(dfs_text: str) -> tuple[str, ...]:
    claims: list[str] = []
    for _, line in _outside_fences(dfs_text):
        match = RED_CLAIM.match(line)
        if match:
            claims.append(_normalize_reference(match.group("label")))
    return tuple(claims)


def active_work_items(ledger_text: str) -> tuple[str, ...]:
    items: list[str] = []
    for _, line in _outside_fences(ledger_text):
        match = ACTIVE_ITEM.match(line)
        if match:
            items.append(_normalize_reference(match.group("reference")))
    return tuple(items)


def validate_work_ledger(ledger: Path, dfs: Path) -> tuple[str, ...]:
    """Require at most ten active entries, each tied to one still-red DFS claim."""

    items = active_work_items(read_markdown(ledger))
    if len(items) > 10:
        raise GuardError(f"Work ledger has {len(items)} active items; maximum is 10")

    red_claims = red_dfs_claims(read_markdown(dfs))
    for reference in items:
        matches = [claim for claim in red_claims if _same_claim(reference, claim)]
        if not matches:
            raise GuardError(f"Work item does not reference a still-red DFS claim: {reference}")
        if len(matches) > 1:
            raise GuardError(f"Work item reference is ambiguous in the DFS: {reference}")
    return items


def validate_dfs_completion(before: Path, after: Path, selected_claim: str) -> str:
    """Allow exactly one selected red marker to become an accepted marker."""

    baseline = read_markdown(before)
    candidate = read_markdown(after)
    selected = _normalize_reference(selected_claim)
    lines = baseline.splitlines(keepends=True)
    matches: list[tuple[int, re.Match[str], str]] = []
    for index, line in enumerate(lines):
        body = line.rstrip("\r\n")
        match = RED_CLAIM.match(body)
        if match:
            label = _normalize_reference(match.group("label"))
            if _same_claim(selected, label):
                matches.append((index, match, label))

    if len(matches) != 1:
        raise GuardError(
            f"Selected claim must identify exactly one still-red DFS claim: {selected}"
        )

    index, match, label = matches[0]
    original = lines[index]
    body = original.rstrip("\r\n")
    ending = original[len(body) :]
    lines[index] = (
        f"{match.group('lead')}[x] {match.group('label')}"
        f"{match.group('trailing')}{ending}"
    )
    expected = "".join(lines)
    if candidate != expected:
        raise GuardError(
            "DFS completion must only change the selected '[ ] 🔴' marker to '[x]'"
        )
    return label


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    guidelines = commands.add_parser("guidelines", help="Validate guideline mutation scope")
    guidelines.add_argument("--baseline", type=Path, required=True)
    guidelines.add_argument("--candidate", type=Path, required=True)
    guidelines.add_argument("--state", type=Path, required=True)
    guidelines.add_argument("--lineage", required=True)
    guidelines.add_argument("--task", required=True)
    guidelines.add_argument("--incident-kind", choices=INCIDENT_KINDS, required=True)
    guidelines.add_argument("--ledger-candidate", type=Path, required=True)

    ledger = commands.add_parser("work-ledger", help="Validate active work against red DFS claims")
    ledger.add_argument("--ledger", type=Path, required=True)
    ledger.add_argument("--dfs", type=Path, required=True)

    completion = commands.add_parser("complete-dfs", help="Validate one accepted DFS claim")
    completion.add_argument("--before", type=Path, required=True)
    completion.add_argument("--after", type=Path, required=True)
    completion.add_argument("--claim", required=True)
    completion.add_argument("--state", type=Path, required=True)
    completion.add_argument("--lineage", required=True)
    completion.add_argument("--task", required=True)

    expansion = commands.add_parser(
        "expand-dfs", help="Validate expansion from one stored worker finding"
    )
    expansion.add_argument("--before", type=Path, required=True)
    expansion.add_argument("--candidate", type=Path, required=True)
    expansion.add_argument("--state", type=Path, required=True)
    expansion.add_argument("--lineage", required=True)
    expansion.add_argument("--task", required=True)
    expansion.add_argument("--ledger-candidate", type=Path, required=True)

    random_review = commands.add_parser(
        "random-review",
        help="Validate one due random improvement-review lane",
    )
    random_review.add_argument("--baseline", type=Path, required=True)
    random_review.add_argument("--candidate", type=Path, required=True)
    random_review.add_argument("--state", type=Path, required=True)
    random_review.add_argument("--lineage", required=True)
    random_review.add_argument("--cycle", type=int, required=True)
    random_review.add_argument("--ledger-candidate", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        if arguments.command == "guidelines":
            broader_mutation = broader_mutation_from_incident(
                arguments.state,
                arguments.lineage,
                arguments.task,
                arguments.incident_kind,
            )
            changed = validate_guideline_mutation(
                arguments.baseline,
                arguments.candidate,
                broader_mutation=broader_mutation,
            )
            validate_consumed_mutation_ledger(arguments.ledger_candidate)
            print("ok: guideline mutation; changed " + ", ".join(changed))
        elif arguments.command == "work-ledger":
            items = validate_work_ledger(arguments.ledger, arguments.dfs)
            print(f"ok: {len(items)} active work items")
        elif arguments.command == "complete-dfs":
            validate_accepted_task_state(
                arguments.state,
                arguments.lineage,
                arguments.task,
                arguments.claim,
            )
            claim = validate_dfs_completion(
                arguments.before, arguments.after, arguments.claim
            )
            print(f"ok: completed {claim}")
        elif arguments.command == "expand-dfs":
            task_claim, finding_kind = worker_finding_from_state(
                arguments.state,
                arguments.lineage,
                arguments.task,
            )
            added = validate_dfs_expansion(
                arguments.before,
                arguments.candidate,
                task_claim,
            )
            validate_consumed_mutation_ledger(arguments.ledger_candidate)
            print(
                f"ok: {finding_kind} finding expanded {task_claim}; added "
                + ", ".join(added)
            )
        else:
            lane = random_review_from_state(
                arguments.state,
                arguments.lineage,
                arguments.cycle,
            )
            changed = validate_random_review_mutation(
                arguments.baseline,
                arguments.candidate,
                selected_lane=lane,
            )
            if changed:
                validate_consumed_mutation_ledger(arguments.ledger_candidate)
            if changed:
                print(
                    f"ok: random review cycle {arguments.cycle}; changed "
                    + ", ".join(changed)
                )
            else:
                print(
                    f"ok: random review cycle {arguments.cycle}; guarded DFS no-op"
                )
    except (GuardError, OSError, UnicodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
