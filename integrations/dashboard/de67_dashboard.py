#!/usr/bin/env python3
"""Optional read-only DE67 workspace dashboard."""

from __future__ import annotations

import argparse
import hashlib
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import threading
import time
from typing import Any
from urllib.parse import quote
import socketserver


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _inline(text: str) -> str:
    escaped = _escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def render_markdown(text: str) -> str:
    """Render a deliberately small Markdown subset; raw HTML is always escaped."""
    result: list[str] = []
    paragraph: list[str] = []
    in_code = False
    code: list[str] = []
    list_open = False

    def flush_paragraph() -> None:
        if paragraph:
            result.append(f"<p>{_inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_open
        if list_open:
            result.append("</ul>")
            list_open = False

    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            flush_paragraph()
            close_list()
            if in_code:
                result.append(f"<pre><code>{_escape(chr(10).join(code))}</code></pre>")
                code.clear()
            in_code = not in_code
            continue
        if in_code:
            code.append(line)
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        item = re.match(r"^\s*[-*]\s+(.*)$", line)
        if heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1))
            result.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
        elif item:
            flush_paragraph()
            if not list_open:
                result.append("<ul>")
                list_open = True
            body = item.group(1)
            checked = re.match(r"^\[([ xX])\]\s*(.*)$", body)
            if checked:
                mark = "☑" if checked.group(1).lower() == "x" else "☐"
                body = f"{mark} {checked.group(2)}"
            result.append(f"<li>{_inline(body)}</li>")
        elif not line.strip():
            flush_paragraph()
            close_list()
        else:
            close_list()
            paragraph.append(line.strip())
    if in_code:
        result.append(f"<pre><code>{_escape(chr(10).join(code))}</code></pre>")
    flush_paragraph()
    close_list()
    return "\n".join(result)


def _read_snapshot(path: Path) -> tuple[str, dict[str, Any]]:
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise OSError("source changed while it was being read")
    invalid_utf8 = False
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
        invalid_utf8 = True
    return text, {
        "hash": hashlib.sha256(raw).hexdigest()[:12],
        "mtime": after.st_mtime,
        "invalid_utf8": invalid_utf8,
    }


def parse_ledger(text: str) -> dict[str, Any]:
    sections: dict[str, list[str]] = {"active": [], "waiting": [], "blocked": []}
    current: str | None = None
    for line in text.splitlines():
        heading = re.match(r"^##\s+(.+?)\s*$", line, re.I)
        if heading:
            name = heading.group(1).lower()
            if "active" in name:
                current = "active"
            elif any(label in name for label in ("waiting", "queued", "pending")):
                current = "waiting"
            elif "blocked" in name:
                current = "blocked"
            else:
                current = None
        elif current and line.strip():
            sections[current].append(line)
    active = "\n".join(sections["active"]).strip()
    waiting = "\n".join(sections["waiting"]).strip()
    blocked = "\n".join(sections["blocked"]).strip()
    first = re.search(r"[-*]\s+\[[ xX]\]\s+([^\n]+)", active)
    claim = None
    if first:
        match = re.search(r"\b(R[- ]?\d+)\b", first.group(1), re.I)
        claim = match.group(1) if match else None
    return {"active": active, "waiting": waiting, "blocked": blocked, "claim": claim}


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    safe = table.replace('"', '""')
    return {row[1] for row in connection.execute(f'PRAGMA table_info("{safe}")')}


def _latest(connection: sqlite3.Connection, table: str, order: str) -> dict[str, Any] | None:
    if table not in {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        return None
    columns = _table_columns(connection, table)
    if order not in columns:
        return None
    safe_table = table.replace('"', '""')
    safe_order = order.replace('"', '""')
    row = connection.execute(
        f'SELECT * FROM "{safe_table}" ORDER BY "{safe_order}" DESC LIMIT 1'
    ).fetchone()
    return dict(row) if row else None


def _active_task(connection: sqlite3.Connection) -> dict[str, Any] | None:
    columns = _table_columns(connection, "tasks")
    if not columns or "started_at" not in columns:
        return None
    terminal_columns = [
        name for name in ("completed_at", "terminal_at", "attempt_terminal_at", "abandoned_at")
        if name in columns
    ]
    where = " AND ".join(f'"{name}" IS NULL' for name in terminal_columns) or "1"
    row = connection.execute(
        f'SELECT * FROM "tasks" WHERE {where} ORDER BY "started_at" DESC LIMIT 1'
    ).fetchone()
    return dict(row) if row else None


def _completed_mutation_counts(connection: sqlite3.Connection) -> tuple[int, int, dict[str, Any] | None]:
    tables = {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    ordinary = 0
    for table in ("deadline_mutation_components", "integrity_mutation_components"):
        if table in tables and "component" in _table_columns(connection, table):
            ordinary += int(connection.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE "component" = ?', ("macro",)
            ).fetchone()[0])
    random = 0
    next_random = None
    if "random_mutation_cycles" in tables:
        columns = _table_columns(connection, "random_mutation_cycles")
        evidence_columns = [name for name in (
            "resolution_evidence", "ordinary_resolution_evidence",
            "universal_resolution_evidence",
        ) if name in columns]
        if evidence_columns:
            where = " OR ".join(f'"{name}" IS NOT NULL' for name in evidence_columns)
            random = int(connection.execute(
                f'SELECT COUNT(*) FROM "random_mutation_cycles" WHERE {where}'
            ).fetchone()[0])
            if {"cycle_number", "interval_windows", "due_after_terminal_windows"}.issubset(columns):
                unresolved = " AND ".join(f'"{name}" IS NULL' for name in evidence_columns)
                row = connection.execute(
                    f'SELECT * FROM "random_mutation_cycles" WHERE {unresolved} '
                    'ORDER BY "cycle_number" ASC LIMIT 1'
                ).fetchone()
                if row:
                    task_columns = _table_columns(connection, "tasks") if "tasks" in tables else set()
                    terminal_columns = [name for name in (
                        "attempt_terminal_at", "terminal_at", "completed_at", "abandoned_at"
                    ) if name in task_columns]
                    terminal_windows = 0
                    if terminal_columns:
                        terminal_where = " OR ".join(
                            f'"{name}" IS NOT NULL' for name in terminal_columns
                        )
                        terminal_windows = int(connection.execute(
                            f'SELECT COUNT(*) FROM "tasks" WHERE {terminal_where}'
                        ).fetchone()[0])
                    next_random = dict(row)
                    next_random["terminal_windows"] = terminal_windows
                    next_random["remaining_windows"] = max(
                        0, int(row["due_after_terminal_windows"]) - terminal_windows
                    )
    return ordinary, random, next_random


def read_clock(path: Path) -> dict[str, Any]:
    uri = f"file:{quote(str(path.resolve()).replace(os.sep, '/'), safe='/:')}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=0)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        task = _active_task(connection)
        deadline = _latest(connection, "claim_deadline_generations", "generation")
        restart = _latest(connection, "coordinator_restart_requests", "generation")
        finding = _latest(connection, "worker_findings", "reported_at")
        mutations, random_mutations, next_random = _completed_mutation_counts(connection)
        connection.execute("COMMIT")
        return {"task": task, "deadline": deadline, "restart": restart,
                "finding": finding,
                "mutations": mutations, "random_mutations": random_mutations,
                "next_random_mutation": next_random}
    finally:
        connection.close()


def process_state(workspace: Path) -> dict[str, Any]:
    pid_path = workspace / ".de67/state/coordinator-supervisor.pid"
    pid: int | None = None
    try:
        pid = int(pid_path.read_text(encoding="ascii").strip())
        os.kill(pid, 0)
    except (OSError, ValueError):
        pid = None
    coordinator = "unknown"
    try:
        output = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,command="], capture_output=True, text=True,
            timeout=1, check=False,
        ).stdout
        if pid is None:
            workspace_marker = f"--workspace {workspace}"
            for line in output.splitlines():
                match = re.match(r"\s*(\d+)\s+\d+\s+(.*)", line)
                if match and "coordinator_supervisor.py" in match.group(2) and workspace_marker in match.group(2):
                    pid = int(match.group(1))
                    break
        if pid is None:
            return {"supervisor": "absent", "coordinator": "absent", "pid": None}
        children = [line for line in output.splitlines() if re.match(rf"\s*\d+\s+{pid}\s+", line)]
        coordinator = "running" if any("codex-remote-run" in line or "codex" in line for line in children) else "waiting"
    except (OSError, subprocess.SubprocessError):
        if pid is None:
            return {"supervisor": "unknown", "coordinator": "unknown", "pid": None}
    return {"supervisor": "running", "coordinator": coordinator, "pid": pid}


def _session_header(path: Path) -> dict[str, Any]:
    record: dict[str, Any] = {}
    with path.open("r", encoding="utf-8", errors="replace") as source:
        for _ in range(12):
            line = source.readline()
            if not line:
                break
            try:
                item = json.loads(line)
            except (TypeError, ValueError):
                continue
            payload = item.get("payload", {})
            if item.get("type") == "session_meta":
                record.update({
                    "id": payload.get("id"),
                    "parent": payload.get("parent_thread_id"),
                    "cwd": payload.get("cwd"),
                    "timestamp": payload.get("timestamp") or item.get("timestamp"),
                })
            elif item.get("type") == "turn_context":
                record["model"] = payload.get("model")
                record["effort"] = payload.get("effort")
            if record.get("id") and record.get("model"):
                break
    return record


def _session_complete(path: Path) -> bool:
    size = path.stat().st_size
    with path.open("rb") as source:
        source.seek(max(0, size - 131072))
        tail = source.read().decode("utf-8", errors="replace")
    return '"type":"task_complete"' in tail or '"type": "task_complete"' in tail


def worker_state(workspace: Path, sessions_root: Path) -> dict[str, Any]:
    """Project active Luna/Terra subagents from Codex's existing read-only session records."""
    counts = {model: {effort: 0 for effort in ("low", "medium", "high", "max")}
              for model in ("luna", "terra")}
    paths = sorted(sessions_root.glob("**/rollout-*.jsonl"), reverse=True)
    root_path: Path | None = None
    root: dict[str, Any] = {}
    target = workspace.resolve()
    for path in paths:
        candidate = _session_header(path)
        try:
            candidate_cwd = Path(candidate.get("cwd", "")).resolve()
        except (OSError, RuntimeError):
            continue
        if not candidate.get("parent") and candidate_cwd == target:
            root_path, root = path, candidate
            break
    if root_path is None or not root.get("id"):
        return {"counts": counts, "available": False, "error": "active Codex session unavailable"}
    root_mtime = root_path.stat().st_mtime
    for path in paths:
        if path == root_path or path.stat().st_mtime < root_mtime:
            continue
        candidate = _session_header(path)
        if candidate.get("parent") != root["id"] or _session_complete(path):
            continue
        model = str(candidate.get("model", "")).lower().rsplit("-", 1)[-1]
        effort = str(candidate.get("effort", "")).lower()
        if model in counts and effort in counts[model]:
            counts[model][effort] += 1
    return {"counts": counts, "available": True, "error": None}


class Dashboard:
    def __init__(self, workspace: Path, refresh_seconds: int = 0,
                 sessions_root: Path | None = None) -> None:
        self.workspace = workspace
        self.refresh_seconds = refresh_seconds
        self.sessions_root = sessions_root or Path.home() / ".codex/sessions"
        self._lock = threading.Lock()
        self._good: dict[str, dict[str, Any]] = {}

    def _markdown_source(self, name: str, path: Path) -> dict[str, Any]:
        try:
            text, identity = _read_snapshot(path)
            value = {"text": text, "html": render_markdown(text), "identity": identity,
                     "observed": time.time(), "stale": False, "error": None}
            self._good[name] = value
            return value
        except Exception as error:  # display failure is deliberately isolated
            previous = dict(self._good.get(name, {}))
            previous.update({"stale": bool(previous), "error": str(error), "observed": time.time()})
            return previous

    def _clock_source(self, path: Path) -> dict[str, Any]:
        try:
            value = {"data": read_clock(path), "observed": time.time(), "stale": False, "error": None}
            self._good["clock"] = value
            return value
        except Exception as error:
            previous = dict(self._good.get("clock", {}))
            previous.update({"stale": bool(previous), "error": str(error), "observed": time.time()})
            return previous

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            root = self.workspace / ".de67"
            dfs = self._markdown_source("dfs", root / "DFS.md")
            ledger = self._markdown_source("ledger", root / "work-ledger.md")
            clock = self._clock_source(root / "state/deadlines.sqlite3")
            try:
                process = process_state(self.workspace)
                process_error = None
            except Exception as error:
                process, process_error = {}, str(error)
            try:
                workers = worker_state(self.workspace, self.sessions_root)
            except Exception as error:
                workers = {"counts": {}, "available": False, "error": str(error)}
            return {"dfs": dfs, "ledger": ledger, "clock": clock, "process": process,
                    "workers": workers, "process_error": process_error, "observed": time.time()}

    def render(self, tab: str) -> bytes:
        state = self.snapshot()
        dfs, ledger, clock = state["dfs"], state["ledger"], state["clock"]
        ledger_data = parse_ledger(ledger.get("text", ""))
        clock_data = clock.get("data", {})
        task = clock_data.get("task") or {}
        deadline = clock_data.get("deadline") or {}
        restart = clock_data.get("restart") or {}
        finding = clock_data.get("finding") or {}
        next_random = clock_data.get("next_random_mutation") or {}
        process = state["process"]
        workers = state["workers"]
        now = time.time()
        deadline_at = deadline.get("deadline_at") or task.get("deadline_at")
        remaining = "—"
        if isinstance(deadline_at, (int, float)):
            seconds = int(deadline_at - now)
            sign = "−" if seconds < 0 else ""
            seconds = abs(seconds)
            remaining = f"{sign}{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
        random_remaining = next_random.get("remaining_windows")
        if random_remaining is None:
            random_note = ""
        elif random_remaining == 0:
            random_note = "Random mutation due now"
        else:
            suffix = "result" if random_remaining == 1 else "results"
            random_note = f"Next random in {random_remaining} worker {suffix}"
        finding_age = ""
        if isinstance(finding.get("reported_at"), (int, float)):
            age_seconds = max(0, int(now - finding["reported_at"]))
            if age_seconds < 60:
                finding_age = f"{age_seconds}s ago"
            elif age_seconds < 3600:
                finding_age = f"{age_seconds // 60}m ago"
            else:
                finding_age = f"{age_seconds // 3600}h ago"

        def lamp(label: str, value: str, tone: str) -> str:
            return f'<div class="lamp"><span class="dot {tone}"></span><small>{_escape(label)}</small><strong>{_escape(value)}</strong></div>'

        supervisor = process.get("supervisor", "unknown")
        coordinator = process.get("coordinator", "unknown")
        work_value = "Blocked" if ledger_data["blocked"] else (task.get("task_id") or ledger_data["claim"] or "Idle")
        work_tone = (
            "red" if ledger_data["blocked"] else
            "green" if ledger_data["active"] and supervisor == "running" else
            "yellow" if ledger_data["active"] else "grey"
        )
        nav = '<nav><a class="%s" href="/">Overview</a><a class="%s" href="/dfs">DFS</a><a href="?refresh=1">Refresh</a></nav>' % (
            "selected" if tab == "overview" else "", "selected" if tab == "dfs" else "")
        meta = f'<meta http-equiv="refresh" content="{self.refresh_seconds}">' if self.refresh_seconds else ""
        source_bits = []
        for label, source in (("Markdown", ledger), ("DFS", dfs), ("SQLite", clock)):
            tone = "yellow" if source.get("stale") else "red" if source.get("error") else "green"
            detail = source.get("error") or source.get("identity", {}).get("hash") or "healthy"
            source_bits.append(f'<span><i class="dot {tone}"></i>{_escape(label)} <em>{_escape(detail)}</em></span>')
        if tab == "dfs":
            body = f'<section class="document">{dfs.get("html", "<p>DFS unavailable.</p>")}</section>'
        else:
            cards = "".join([
                lamp("Supervisor", supervisor.title(), "green" if supervisor == "running" else "grey"),
                lamp("Coordinator", coordinator.title(), "green" if coordinator == "running" else "yellow" if coordinator == "waiting" else "grey"),
                lamp("Work", work_value, work_tone),
                f'<div class="metric"><small>Deadline</small><strong>{remaining}</strong></div>',
                f'<div class="metric"><small>Mutations</small><strong>{_escape((clock_data.get("mutations", 0) + clock_data.get("random_mutations", 0)) if clock_data else "—")}</strong><span class="metric-note">{_escape(random_note)}</span></div>',
            ])
            worker_counts = workers.get("counts", {})
            if workers.get("available"):
                rows = "".join(
                    f'<tr><th>{model.title()}</th>' + "".join(
                        f'<td class="{"active-count" if worker_counts.get(model, {}).get(effort, 0) else ""}">{_escape(worker_counts.get(model, {}).get(effort, 0))}</td>'
                        for effort in ("low", "medium", "high", "max")
                    ) + "</tr>" for model in ("luna", "terra")
                )
                worker_body = f'<table><thead><tr><th>Model</th><th>Low</th><th>Medium</th><th>High</th><th>Max</th></tr></thead><tbody>{rows}</tbody></table>'
            else:
                worker_body = f'<p class="subtle">Unavailable · {_escape(workers.get("error", "unknown source"))}</p>'
            workers_html = f'<section class="workers"><h2>Active workers</h2>{worker_body}</section>'
            active_html = render_markdown(ledger_data["active"]) if ledger_data["active"] else "<p>None.</p>"
            waiting_html = render_markdown(ledger_data["waiting"]) if ledger_data["waiting"] else "<p>None.</p>"
            blocked_html = render_markdown(ledger_data["blocked"]) if ledger_data["blocked"] else "<p>None.</p>"
            details = " · ".join(filter(None, [
                f'claim {_escape(task.get("claim_id"))}' if task.get("claim_id") else "",
                f'gap {_escape(task.get("closure_gap_id"))} r{_escape(task.get("closure_gap_revision"))}' if task.get("closure_gap_id") else "",
                f'deadline generation {_escape(deadline.get("generation"))}' if deadline.get("generation") else "",
                f'restart {_escape(restart.get("generation"))}' if restart.get("generation") else "",
            ]))
            finding_html = ""
            if finding:
                finding_html = (
                    '<div class="activity"><small>Latest finding</small>'
                    f'<strong>{_escape(finding.get("task_id", ""))}</strong>'
                    f'<span>{_escape(finding.get("short_verdict", ""))}</span>'
                    f'<em>{_escape(finding_age)}</em></div>'
                )
            body = f'<div class="status">{cards}</div>{workers_html}{finding_html}<section><h2>Active work ledger</h2><div class="subtle">{details}</div>{active_html}</section><section><h2>Waiting work</h2>{waiting_html}</section><section><h2>Blocked work</h2>{blocked_html}</section>'
        page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8">{meta}
<meta name="viewport" content="width=device-width,initial-scale=1"><title>DE67</title>
<style>
:root{{--bg:#101318;--panel:#1a1e24;--line:#343a43;--text:#eee9df;--muted:#9ca3ad;--green:#75c84c;--yellow:#f0bc28;--red:#e05248;--blue:#75a7d8}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:15px system-ui,sans-serif}}main{{max-width:1180px;margin:auto;padding:24px}}header{{display:flex;align-items:baseline;gap:22px}}h1{{font-size:25px;margin:0}}header span,.subtle{{color:var(--muted)}}nav{{display:flex;margin:18px 0;border-bottom:1px solid var(--line)}}nav a{{color:var(--muted);text-decoration:none;padding:10px 16px}}nav a.selected{{color:var(--text);border:1px solid var(--line);border-bottom-color:var(--bg);border-radius:6px 6px 0 0;margin-bottom:-1px}}nav a:last-child{{margin-left:auto}}.status{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}}.lamp,.metric,section,.activity{{background:var(--panel);border:1px solid var(--line);border-radius:7px}}.lamp,.metric{{padding:13px 14px;min-height:82px}}small{{display:block;color:var(--muted);margin-bottom:10px}}strong{{font-size:18px}}.metric-note{{display:block;color:var(--muted);font-size:11px;margin-top:5px;white-space:nowrap}}.workers{{padding:12px 16px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:7px 12px;text-align:center;border-top:1px solid var(--line)}}thead th{{border-top:0;color:var(--muted);font-size:12px;font-weight:500}}tbody th{{text-align:left}}td{{font-variant-numeric:tabular-nums;color:var(--muted)}}td.active-count{{color:var(--green);font-weight:700}}.activity{{display:grid;grid-template-columns:100px max-content 1fr max-content;align-items:center;gap:12px;margin-top:10px;padding:10px 14px}}.activity small{{margin:0}}.activity strong{{font-size:13px}}.activity span{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.activity em{{color:var(--muted);font-style:normal;font-size:12px}}.dot{{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:8px}}.green{{background:var(--green)}}.yellow{{background:var(--yellow)}}.red{{background:var(--red)}}.grey{{background:#737983}}section{{margin-top:12px;padding:16px}}h2{{font-size:16px;margin:0 0 12px}}h3{{font-size:15px}}p,li{{line-height:1.55}}code{{background:#11151a;padding:2px 4px;border-radius:3px}}pre{{overflow:auto;background:#11151a;padding:12px;border-radius:5px}}footer{{display:flex;gap:25px;flex-wrap:wrap;color:var(--muted);padding:14px 4px}}footer em{{font-style:normal;color:#747c87;margin-left:5px}}.document{{padding:22px}}@media(max-width:900px){{.status{{grid-template-columns:1fr 1fr 1fr}}}}@media(max-width:600px){{.status{{grid-template-columns:1fr 1fr}}header span{{display:none}}.activity{{grid-template-columns:1fr}}.activity span{{white-space:normal}}}}
</style></head><body><main><header><h1>DE67</h1><span>{_escape(self.workspace.name)}</span></header>{nav}{body}<footer>{''.join(source_bits)}</footer></main></body></html>'''
        return page.encode("utf-8")


def serve(workspace: Path, bind: str, port: int, refresh_seconds: int,
          sessions_root: Path | None = None) -> None:
    dashboard = Dashboard(workspace.resolve(), refresh_seconds, sessions_root)

    class Server(ThreadingHTTPServer):
        def server_bind(self) -> None:
            # HTTPServer normally reverse-resolves the bind address only to populate
            # server_name. That can stall service startup on offline/home DNS.
            socketserver.TCPServer.server_bind(self)
            self.server_name = str(self.server_address[0])
            self.server_port = int(self.server_address[1])

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path not in ("/", "/dfs"):
                self.send_error(404)
                return
            try:
                payload = dashboard.render("dfs" if path == "/dfs" else "overview")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(payload)
            except Exception as error:
                payload = f"Dashboard display error: {_escape(error)}".encode("utf-8")
                self.send_response(503)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:
            print(f"dashboard: {format % args}")

    server = Server((bind, port), Handler)
    print(f"DE67 dashboard: http://{bind}:{server.server_port} ({workspace})")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--refresh-seconds", type=int, default=0)
    parser.add_argument("--codex-sessions", type=Path, default=None,
                        help="Codex session root used for optional active-worker counts")
    args = parser.parse_args()
    if args.refresh_seconds < 0:
        parser.error("--refresh-seconds cannot be negative")
    serve(args.workspace, args.bind, args.port, args.refresh_seconds, args.codex_sessions)


if __name__ == "__main__":
    main()
