#!/usr/bin/env python3
"""Owner-only Discord input to DE67-owned, already-running agent contexts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import re
import signal
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "de-67-3" / "scripts"))
from codex_app_server_runner import Rpc, RpcError, atomic_json


def route_message(text: str) -> tuple[str, str]:
    prefix = re.match(r"^\s*coordinator:\s*", text, re.IGNORECASE)
    return ("coordinator", text[prefix.end():]) if prefix else ("mutator", text)


def is_owner_message(message: dict[str, Any], config: dict[str, Any]) -> bool:
    author = message.get("author", {})
    return (author.get("id") == config["ownerId"] and not author.get("bot")
            and not message.get("webhook_id") and message.get("channel_id") == config["channelId"])


def split_text(text: str) -> list[str]:
    # Discord's actual content limit is 2000 UTF-16 code units.
    parts: list[str] = []
    current = ""
    size = 0
    for char in text:
        units = len(char.encode("utf-16-le")) // 2
        if size + units > 2000:
            parts.append(current)
            current, size = "", 0
        current += char
        size += units
    if current:
        parts.append(current)
    return parts


class Relay:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.workspace = Path(config["workspace"]).resolve()
        self.root = Path(config["stateDir"])
        self.jobs_dir = self.root / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state_path = self.root / "state.json"
        if not self.state_path.exists():
            raise RuntimeError("Initialize the Discord cursor at the explicit channel cutover")
        self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.jobs = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in self.jobs_dir.glob("*.json")}
        self.connections: dict[str, tuple[dict[str, Any], Rpc]] = {}
        self.history_rpc: Rpc | None = None
        self.mutator_process: subprocess.Popen[Any] | None = None
        for job in self.jobs.values():
            if job["status"] == "submitting":
                job["status"] = "uncertain"
                self.save(job)

    def save(self, job: dict[str, Any]) -> None:
        atomic_json(self.jobs_dir / f"{job['id']}.json", job)

    def recover_launches(self) -> None:
        for job in self.jobs.values():
            if job["status"] != "starting":
                continue
            receipt_path = Path(job["launch_dir"]) / "receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.exists() else {}
            if receipt.get("state") == "submitted":
                job.update(status="submitted", thread_id=receipt["thread_id"],
                           turn_id=receipt["turn_id"], run_id=receipt["run_id"])
                self.save(job)
                continue
            pid = job.get("launch_pid")
            try:
                if pid:
                    os.kill(pid, 0)
                    continue
            except ProcessLookupError:
                pass
            job.update(status="uncertain" if receipt or not pid else "failed",
                       error="Mutator launch ended before a native input receipt was available")
            if receipt.get("thread_id"):
                job["thread_id"] = receipt["thread_id"]
            self.save(job)

    def recover_launch_output(self) -> None:
        """Read new complete events from our own launches, even after server exit."""
        for job in self.jobs.values():
            if not job.get("launch_dir"):
                continue
            path = Path(job["launch_dir"]) / "output.jsonl"
            if not path.exists():
                continue
            offset = job.get("launch_read_offset", 0)
            with path.open("rb") as source:
                source.seek(offset)
                while True:
                    line = source.readline()
                    if not line or not line.endswith(b"\n"):
                        break
                    offset = source.tell()
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get("type") == "app_server.notification":
                        self.observe("mutator", event)
            if offset != job.get("launch_read_offset", 0):
                job["launch_read_offset"] = offset
                self.save(job)

    def start_mutator(self, job: dict[str, Any]) -> bool:
        path = self.workspace / ".de67/state/workspace.json"
        config = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if config.get("persistent_mutator") is not True:
            return False
        if self.mutator_process is not None:
            if self.mutator_process.poll() is None:
                return True
            self.mutator_process = None
        if any(item["status"] == "starting" for item in self.jobs.values()):
            return True
        from mutator_session import owner_prompt
        scripts = Path(__file__).resolve().parents[2] / "de-67-3/scripts"
        python = config.get("agent_transport_python") or sys.executable
        launch = self.root / "launches" / job["id"]
        launch.mkdir(parents=True, exist_ok=True)
        initial_path = launch / "input.json"
        atomic_json(initial_path, {"input": self.input_for(job), "client_id": "discord:" + job["id"],
                                  "receipt_path": str(launch / "receipt.json")})
        environment = dict(os.environ, DE67_AGENT_TRANSPORT="app-server",
            DE67_AGENT_TRANSPORT_PYTHON=python, DE67_PROCESS_ROLE="mutation-reviewer",
            DE67_COORDINATOR_MODEL="gpt-6-astra", DE67_COORDINATOR_REASONING_EFFORT="medium",
            DE67_COORDINATOR_RUN_ID="owner-message-" + job["id"],
            DE67_CODEX=self.config.get("codex") or shutil.which("codex") or "codex",
            DE67_INITIAL_INPUT_PATH=str(initial_path))
        for key in ("DE67_COORDINATOR_RESUME_SESSION", "DE67_DEADLINE_STATE", "DE67_LINEAGE"):
            environment.pop(key, None)
        for key in ("thread_id", "turn_id", "run_id", "launch_read_offset"):
            job.pop(key, None)
        job.update(status="starting", launch_dir=str(launch))
        self.save(job)
        try:
            with (launch / "output.jsonl").open("a", encoding="utf-8") as output:
                self.mutator_process = subprocess.Popen([python, str(scripts / "codex_runner.py"),
                    "--cwd", str(self.workspace)], cwd=self.workspace, env=environment,
                    stdin=subprocess.PIPE, stdout=output, stderr=output, text=True)
                job["launch_pid"] = self.mutator_process.pid
                self.save(job)
                self.mutator_process.stdin.write(owner_prompt(self.workspace, scripts, python))
                self.mutator_process.stdin.close()
        except OSError as error:
            job.update(status="failed", error=str(error))
            self.save(job)
            raise
        return True

    def log(self, event: str, **detail: Any) -> None:
        with (self.root / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"time": time.time(), "event": event, **detail}) + "\n")

    def discord(self, endpoint: str, method: str = "GET", body: Any = None) -> Any:
        config = json.loads(Path(self.config["openclawConfig"]).read_text(encoding="utf-8"))
        token = config["channels"]["discord"]["token"]
        request = urllib.request.Request("https://discord.com/api/v10" + endpoint,
            data=json.dumps(body).encode() if body is not None else None, method=method,
            headers={"Authorization": "Bot " + token, "Content-Type": "application/json",
                     "User-Agent": "DE67AgentInput/1.0"})
        while True:
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    data = response.read()
                    return json.loads(data) if data else None
            except urllib.error.HTTPError as error:
                if error.code != 429:
                    raise RuntimeError(f"Discord {method} failed: HTTP {error.code}") from None
                time.sleep(float(json.loads(error.read())["retry_after"]))

    def send(self, text: str, reply_to: str, nonce_key: str) -> None:
        for index, part in enumerate(split_text(text)):
            body: dict[str, Any] = {"content": part, "allowed_mentions": {"parse": []},
                "nonce": hashlib.sha256(f"{nonce_key}:{index}".encode()).hexdigest()[:24],
                "enforce_nonce": True}
            if index == 0:
                body["message_reference"] = {"message_id": reply_to, "fail_if_not_exists": False}
            self.discord(f"/channels/{self.config['channelId']}/messages", "POST", body)

    def accept(self, message: dict[str, Any]) -> None:
        if not is_owner_message(message, self.config) or message["id"] in self.jobs:
            return
        role, text = route_message(message.get("content", ""))
        job = {"id": message["id"], "role": role, "text": text, "status": "pending",
               "attachments": message.get("attachments", []), "created_at": time.time()}
        self.jobs[job["id"]] = job
        self.save(job)

    def input_for(self, job: dict[str, Any]) -> list[dict[str, Any]]:
        if "input" in job:
            return job["input"]
        text = job["text"]
        media: list[dict[str, Any]] = []
        for attachment in job["attachments"]:
            parsed = urllib.parse.urlparse(attachment["url"])
            if parsed.scheme != "https" or parsed.hostname not in {"cdn.discordapp.com", "media.discordapp.net"}:
                raise ValueError("Attachment is not on the Discord media service")
            folder = self.root / "media" / job["id"]
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            name = Path(attachment.get("filename", "attachment")).name
            destination = folder / (str(attachment["id"]) + "-" + name)
            if not destination.exists():
                with urllib.request.urlopen(attachment["url"], timeout=60) as response:
                    data = response.read()
                if attachment.get("size") is not None and len(data) != attachment["size"]:
                    raise ValueError("Attachment download was incomplete")
                destination.write_bytes(data)
            mime = attachment.get("content_type", "")
            if mime.startswith("image/"):
                media.append({"type": "localImage", "path": str(destination)})
            elif mime.startswith("audio/") or destination.suffix.lower() in {".ogg", ".opus", ".wav", ".mp3", ".m4a"}:
                transcript = folder / (destination.stem + ".json")
                if not transcript.exists():
                    with (folder / "transcription.log").open("a") as log:
                        subprocess.run([self.config.get("whisper", "/opt/homebrew/bin/whisper"),
                            str(destination), "--model", "turbo", "--device", "cpu", "--threads", "4",
                            "--fp16", "False", "--output_format", "json", "--output_dir", str(folder),
                            "--verbose", "False"], stdout=log, stderr=log, check=True)
                words = json.loads(transcript.read_text(encoding="utf-8")).get("text", "").strip()
                if not words:
                    raise ValueError("No speech was recognized in the audio attachment")
                text += "\n" + words
            else:
                text += f"\nAttached file: {destination}"
        if not text.strip() and not media:
            raise ValueError("The message has no text or attachments")
        job["input"] = [{"type": "text", "text": "User Message:\n" + text}, *media]
        self.save(job)
        return job["input"]

    def connect(self, role: str) -> tuple[dict[str, Any], Rpc] | None:
        path = self.workspace / ".de67" / "state" / f"{role}-input.json"
        try:
            binding = json.loads(path.read_text(encoding="utf-8"))
            if (binding.get("role") != role or binding.get("workspace") != str(self.workspace)
                    or binding.get("state") != "active"):
                return None
            os.kill(binding["server_pid"], 0)
            os.kill(binding["runner_pid"], 0)
            if not Path(binding["socket"]).exists():
                return None
        except (OSError, ValueError, KeyError):
            return None
        cached = self.connections.get(role)
        if cached and cached[0] == binding:
            return cached
        if cached:
            cached[1].close()
        rpc = Rpc(Path(binding["socket"]))
        try:
            rpc.call("initialize", {"clientInfo": {"name": "de67_owner_input", "version": "1.0"},
                                   "capabilities": {"experimentalApi": True}})
            rpc.send({"method": "initialized", "params": {}})
            thread = rpc.call("thread/read", {"threadId": binding["thread_id"], "includeTurns": False})["thread"]
            if thread["cwd"] != str(self.workspace) or thread["status"]["type"] != "active":
                rpc.close()
                return None
            # Subscribe to an already-loaded agent. Never create an agent or start a turn here.
            rpc.call("thread/resume", {"threadId": binding["thread_id"], "excludeTurns": True})
        except Exception:
            rpc.close()
            raise
        self.connections[role] = (binding, rpc)
        return binding, rpc

    def submit(self, job: dict[str, Any], binding: dict[str, Any], rpc: Rpc) -> None:
        inputs = self.input_for(job)
        job.update(status="submitting", thread_id=binding["thread_id"], turn_id=binding["turn_id"],
                   run_id=binding["run_id"])
        self.save(job)
        try:
            rpc.call("turn/steer", {"threadId": binding["thread_id"], "expectedTurnId": binding["turn_id"],
                     "input": inputs, "clientUserMessageId": "discord:" + job["id"]})
        except Exception as error:
            # Explicit rejections have not accepted input. A missing receipt is ambiguous.
            if (isinstance(error, RpcError) and error.code == -32600
                    and any(reason in str(error).lower() for reason in
                            ("thread not found", "no active turn", "does not match", "mismatch"))):
                job["status"] = "pending"
            elif isinstance(error, RpcError) and error.code is not None:
                job["status"] = "failed"
                job["error"] = str(error)
            else:
                job["status"] = "uncertain"
            self.save(job)
            raise
        job["status"] = "submitted"
        self.save(job)
        self.log("submitted", id=job["id"], role=job["role"], thread_id=job["thread_id"])

    def observe(self, role: str, message: dict[str, Any], eligible_ids: set[str] | None = None) -> None:
        payload = message.get("params", {})
        item = payload.get("item", {})
        if message.get("method") != "item/completed":
            return
        if item.get("type") == "userMessage":
            client_id = item.get("clientId", "") or ""
            job = self.jobs.get(client_id.removeprefix("discord:"))
            if (job and job["status"] in {"submitted", "submitting", "uncertain", "applied"}
                    and job.get("thread_id") == payload.get("threadId") and job["role"] == role):
                job["status"] = "applied"
                self.save(job)
                self.log("applied", id=job["id"], role=role, thread_id=job["thread_id"])
        elif item.get("type") == "agentMessage" and item.get("text"):
            final = item.get("phase") != "commentary"
            jobs = [job for job in self.jobs.values()
                    if (job["status"] == "applied" or
                        (final and job["status"] in {"awaiting_final", "reply_pending"}))
                    and (eligible_ids is None or job["id"] in eligible_ids)
                    and job["role"] == role and job.get("thread_id") == payload.get("threadId")
                    and (not payload.get("turnId") or job.get("turn_id") == payload["turnId"])]
            if jobs:
                answer = item["text"]
                for job in jobs:
                    job.update(status="reply_pending", answer=answer, reply_item_id=item["id"],
                               reply_final=final)
                    self.save(job)

    def drain(self, role: str, rpc: Rpc) -> None:
        while True:
            try:
                message = rpc.notifications.pop(0) if rpc.notifications else rpc.receive(timeout=0)
            except queue.Empty:
                return
            self.observe(role, message)

    def recover_history(self, role: str, rpc: Rpc) -> None:
        for job in self.jobs.values():
            if (job["role"] != role or job["status"] != "uncertain"
                    or not job.get("thread_id") or job.get("turn_id")):
                continue
            cursor = None
            while True:
                params = {"threadId": job["thread_id"], "limit": 100, "sortDirection": "desc"}
                if cursor:
                    params["cursor"] = cursor
                page = rpc.call("thread/items/list", params)
                receipt = next((entry for entry in page["data"]
                    if entry.get("item", entry).get("clientId") == "discord:" + job["id"]), None)
                if receipt and receipt.get("turnId"):
                    job.update(turn_id=receipt["turnId"], status="applied")
                    self.save(job)
                    break
                cursor = page.get("nextCursor")
                if not cursor:
                    break
        turns = {(job["thread_id"], job["turn_id"]) for job in self.jobs.values() if job["role"] == role
                   and job.get("thread_id") and job.get("turn_id")
                   and job["status"] in {"submitted", "applied", "uncertain", "awaiting_final"}}
        for thread_id, turn_id in turns:
            wanted = {"discord:" + job["id"] for job in self.jobs.values()
                      if job.get("thread_id") == thread_id and job.get("turn_id") == turn_id and job["status"] in
                      {"submitted", "applied", "uncertain", "awaiting_final"}}
            cursor = None
            items = []
            while wanted:
                params: dict[str, Any] = {"threadId": thread_id, "turnId": turn_id,
                                         "limit": 100, "sortDirection": "desc"}
                if cursor:
                    params["cursor"] = cursor
                page = rpc.call("thread/items/list", params)
                for entry in page["data"]:
                    items.append(entry)
                    wanted.discard(entry.get("item", entry).get("clientId"))
                cursor = page.get("nextCursor")
                if not cursor:
                    break
            seen: set[str] = set()
            for entry in reversed(items):
                item = entry.get("item", entry)
                if item.get("type") == "userMessage":
                    seen.add((item.get("clientId") or "").removeprefix("discord:"))
                self.observe(role, {"method": "item/completed", "params": {
                    "threadId": thread_id, "turnId": entry.get("turnId"), "item": item}}, seen)

    def history_connection(self) -> Rpc | None:
        if self.history_rpc is None:
            socket = Path(self.config.get("codexHome", str(Path.home() / ".codex"))) / "app-server-control/app-server-control.sock"
            if not socket.exists():
                return None
            rpc = Rpc(socket)
            try:
                rpc.call("initialize", {"clientInfo": {"name": "de67_input_receipts", "version": "1.0"},
                                       "capabilities": {"experimentalApi": True}})
                rpc.send({"method": "initialized", "params": {}})
            except Exception:
                rpc.close()
                raise
            self.history_rpc = rpc
        return self.history_rpc

    def replies(self) -> None:
        groups: dict[str, list[dict[str, Any]]] = {}
        for job in self.jobs.values():
            if job["status"] == "reply_pending":
                groups.setdefault(job["reply_item_id"], []).append(job)
        for item_id, jobs in groups.items():
            last = jobs[-1]
            self.send(f"**{last['role'].capitalize()}**\n{last['answer']}", last["id"], item_id)
            for job in jobs:
                job["status"] = "replied" if job.get("reply_final", True) else "awaiting_final"
                self.save(job)

    def reconcile(self) -> None:
        if self.mutator_process is not None:
            self.mutator_process.poll()
        self.recover_launches()
        self.recover_launch_output()
        for role in ("coordinator", "mutator"):
            cached = self.connections.get(role)
            if cached:
                try:
                    self.drain(role, cached[1])
                except RpcError:
                    cached[1].close()
                    self.connections.pop(role, None)
            relevant = [job for job in self.jobs.values() if job["role"] == role
                        and job["status"] in {"pending", "submitted", "applied", "uncertain", "awaiting_final"}]
            if not relevant:
                continue
            try:
                connected = self.connect(role)
                if connected is None:
                    if any(job["status"] != "pending" for job in relevant):
                        history_rpc = self.history_connection()
                        if history_rpc:
                            self.recover_history(role, history_rpc)
                    self.note_ended_session(relevant, None)
                    for job in relevant:
                        if job["status"] == "pending":
                            if role == "mutator":
                                try:
                                    if self.start_mutator(job):
                                        continue
                                except (ValueError, subprocess.CalledProcessError) as error:
                                    job.update(status="failed", error=str(error))
                                    self.save(job)
                                    continue
                            if not job.get("waiting_notified"):
                                self.send(f"Saved for the {role}'s next active session.", job["id"], job["id"] + ":waiting")
                                job["waiting_notified"] = True
                                self.save(job)
                    continue
                binding, rpc = connected
                self.recover_history(role, rpc)
                self.note_ended_session(relevant, binding)
                for job in relevant:
                    if job["status"] == "pending":
                        try:
                            self.submit(job, binding, rpc)
                        except (ValueError, subprocess.CalledProcessError) as error:
                            job.update(status="failed", error=str(error))
                            self.save(job)
                self.drain(role, rpc)
            except Exception as error:
                self.log("route_error", role=role, error=str(error))
                cached = self.connections.pop(role, None)
                if cached:
                    cached[1].close()
                if self.history_rpc:
                    self.history_rpc.close()
                    self.history_rpc = None
        self.replies()
        for job in self.jobs.values():
            if job["status"] in {"failed", "uncertain"} and not job.get("error_notified"):
                text = ("Delivery could not be confirmed; the message has not been resent."
                        if job["status"] == "uncertain" else "Message was not delivered: " + job["error"])
                self.send(text, job["id"], job["id"] + ":error")
                job["error_notified"] = True
                self.save(job)

    def note_ended_session(self, jobs: list[dict[str, Any]], binding: dict[str, Any] | None) -> None:
        for job in jobs:
            if job["status"] not in {"submitted", "applied", "awaiting_final"}:
                continue
            if binding and (job.get("thread_id"), job.get("turn_id")) == (
                    binding["thread_id"], binding["turn_id"]):
                continue
            if job["status"] == "submitted":
                job["status"] = "uncertain"
                self.save(job)
            elif not job.get("ended_notified"):
                self.send(f"Message reached the {job['role']}; its session ended before a final reply was observed.",
                          job["id"], job["id"] + ":ended")
                job["ended_notified"] = True
                self.save(job)

    def poll(self) -> None:
        fresh: dict[str, dict[str, Any]] = {}
        before = ""
        while True:
            page = self.discord(f"/channels/{self.config['channelId']}/messages?limit=100{before}")
            for message in page:
                if int(message["id"]) > int(self.state["cursor"]):
                    fresh[message["id"]] = message
            if len(page) < 100 or any(int(m["id"]) <= int(self.state["cursor"]) for m in page):
                break
            before = "&before=" + page[-1]["id"]
        for message in sorted(fresh.values(), key=lambda m: int(m["id"])):
            self.accept(message)
            self.state["cursor"] = message["id"]
            atomic_json(self.state_path, self.state)

    def close(self) -> None:
        for _, rpc in self.connections.values():
            rpc.close()
        if self.history_rpc:
            self.history_rpc.close()
        if self.mutator_process is not None:
            # Stop only the relay-owned runner; its adapter detects parent exit and
            # the persistent native thread remains available to the next invocation.
            if self.mutator_process.poll() is None:
                self.mutator_process.terminate()
            self.mutator_process.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    claw = json.loads(Path(config["openclawConfig"]).read_text(encoding="utf-8"))
    if claw["channels"]["discord"]["guilds"][config["guildId"]]["channels"][config["channelId"]].get("enabled") is not False:
        raise RuntimeError("This channel must be excluded from ordinary OpenClaw agent routing")
    relay = Relay(config)
    stopped = False
    def stop(_signal: int, _frame: Any) -> None:
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while not stopped:
            try:
                relay.poll()
                relay.reconcile()
            except Exception as error:
                relay.log("transport_error", error=str(error))
            time.sleep(2)
    finally:
        relay.close()


if __name__ == "__main__":
    main()
