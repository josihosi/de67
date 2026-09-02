#!/usr/bin/env python3
"""Write one read-only Luna summary of current de67 activity."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any


def _session_header_and_last_message(path: Path) -> tuple[dict[str, Any], str | None]:
    header: dict[str, Any] = {}
    last: str | None = None
    with path.open("r", encoding="utf-8", errors="replace") as source:
        for line in source:
            try:
                item = json.loads(line)
            except (TypeError, ValueError):
                continue
            payload = item.get("payload", {})
            if item.get("type") == "session_meta":
                header = {"id": payload.get("id"), "parent": payload.get("parent_thread_id"),
                          "cwd": payload.get("cwd")}
            if (item.get("type") == "response_item" and payload.get("type") == "message"
                    and payload.get("role") == "assistant"):
                message = " ".join(
                    str(part.get("text", "")) for part in payload.get("content", [])
                    if isinstance(part, dict)
                ).strip()
                if message:
                    last = message
    return header, last


def activity_payload(workspace: Path, sessions_root: Path) -> dict[str, Any]:
    target = workspace.resolve()
    sessions: list[dict[str, Any]] = []
    for path in sessions_root.glob("**/rollout-*.jsonl"):
        try:
            header, message = _session_header_and_last_message(path)
            if Path(str(header.get("cwd", ""))).resolve() != target or not message:
                continue
            sessions.append({**header, "message": message, "mtime": path.stat().st_mtime_ns})
        except (OSError, RuntimeError):
            continue
    newest = max(sessions, key=lambda item: int(item["mtime"]), default=None)
    relevant: list[dict[str, Any]] = []
    if newest:
        by_id = {str(item.get("id")): item for item in sessions if item.get("id")}
        root_id = str(newest.get("id"))
        while by_id.get(root_id, {}).get("parent") in by_id:
            root_id = str(by_id[root_id]["parent"])
        family = {root_id}
        changed = True
        while changed:
            changed = False
            for item in sessions:
                if item.get("parent") in family and item.get("id") not in family:
                    family.add(str(item["id"]))
                    changed = True
        relevant = [{"thread_id": item.get("id"), "parent": item.get("parent"),
                     "latest_message": item.get("message")}
                    for item in sessions if item.get("id") in family]
    return {
        "workspace": workspace.name,
        "work_ledger": (workspace / ".de67/work-ledger.md").read_text(
            encoding="utf-8", errors="replace"
        ),
        "current_thread_messages": relevant,
    }


def _prompt(evidence: dict[str, Any]) -> str:
    return (
        "You are the read-only de67 dashboard fratbro narrator. Explain the current work to the "
        "repository owner in one short, natural paragraph. Start from first principles and assume "
        "the reader knows nothing about the project, task IDs, acronyms, attempt history, or prior "
        "updates. Say what concrete feature or behavior is being built or tested, what the worker "
        "actually did or observed, whether that is meaningful progress or churn, and what happens "
        "next. Use casual plain language, but stay crisp, clear, factual, and grounded in the "
        "evidence. Translate process language instead of repeating it. Do not use headings, labels, "
        "bullet points, JSON, or administrative jargon. Do not advise, steer, edit, or run tools. "
        "Do not claim more than the supplied evidence. Return only the paragraph.\n\n"
        "CURRENT EVIDENCE:\n" + json.dumps(evidence, ensure_ascii=False)
    )


def run_luna(workspace: Path, evidence: dict[str, Any], codex: str) -> str:
    # Run outside the observed workspace so this narrator session cannot become
    # fresh project activity and recursively trigger another narration.
    command = [codex, "exec", "--sandbox", "read-only", "--json", "--skip-git-repo-check",
               "-C", str(workspace.parent), "-m", "gpt-5.6-luna",
               "-c", "model_reasoning_effort=medium", "-"]
    completed = subprocess.run(
        command, input=_prompt(evidence), text=True, capture_output=True, check=False
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "Luna narrator failed")
    answer: str | None = None
    for line in completed.stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        item = event.get("item", {})
        if event.get("type") == "item.completed" and item.get("type") == "agent_message":
            answer = item.get("text")
    if not answer:
        raise RuntimeError("Luna narrator returned no final message")
    return " ".join(answer.split())


def write_cache(cache: Path, value: dict[str, Any]) -> None:
    cache.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=cache.parent, delete=False
    ) as temporary:
        json.dump(value, temporary, ensure_ascii=False, indent=2)
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    temporary_path.replace(cache)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--signature", required=True)
    parser.add_argument("--codex", default=os.environ.get("DE67_CODEX", "codex"))
    parser.add_argument("--codex-sessions", type=Path, default=Path.home() / ".codex/sessions")
    args = parser.parse_args()
    codex = shutil.which(args.codex)
    if not codex:
        parser.error(f"Codex CLI was not found: {args.codex}")
    workspace = args.workspace.resolve()
    evidence = activity_payload(workspace, args.codex_sessions.resolve())
    summary = run_luna(workspace, evidence, codex)
    write_cache(args.cache.resolve(), {
        "signature": args.signature, "summary": summary, "evidence": evidence
    })


if __name__ == "__main__":
    main()
