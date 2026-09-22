from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "integrations" / "jev_pit_crew"))
sys.path.insert(0, str(ROOT / "de-67-3" / "scripts"))
sys.path.insert(0, str(ROOT / "de-67-3" / "tests"))

import pit_crew as pit  # noqa: E402
from test_worker_library import WorkerFixture, library  # noqa: E402


class PitCrewTests(WorkerFixture, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.guard = pit._guard_module()
        self.disposable = patch.object(self.guard, "_disposable_context_roots", return_value=())
        self.disposable.start()
        self.addCleanup(self.disposable.stop)

    def config(self, mode: str = "on", *, cooldown: float = 0, max_calls: int = 20) -> dict[str, object]:
        return {
            "mode": mode,
            "state_path": str(self.workspace / ".de67/state/pit-crew.sqlite3"),
            "max_scan_bytes": 65536,
            "max_candidates": 12,
            "max_admissions": 12,
            "cooldown_seconds": cooldown,
            "selection_timeout_seconds": 2,
            "provider_guard": {
                "mode": mode,
                "scope_id": "pit-crew-tests-" + mode,
                "state_path": str(self.workspace / ".de67/state/provider-owner.sqlite3"),
                "max_calls": max_calls,
                "max_request_bytes": 8192,
                "max_in_flight": 2,
                "timeout_seconds": 2,
                "max_retries": 0,
                "retry_backoff_seconds": 0,
            },
        }

    def assignment(self, task_id: str = "task-a", *, name: str = "pilot", objective: str = "Verify cache invalidation after writes.",
                   assumption: str | None = None) -> dict[str, object]:
        self.worker(name)
        text = "Objective: " + objective + "\n"
        if assumption:
            text += "Assumption [A-cache]: " + assumption + "\n"
        packet = self.task(task_id, text)
        self.assign(name, task_id, packet)
        return {**library.describe(self.workspace, name)["assignment"], "name": name}

    def append_final(self, assignment: dict[str, object], text: str, *, item_id: str = "final", turn_id: str = "turn-a") -> Path:
        source = self.workspace / ".de67/state/worker-library/events" / (str(assignment["id"]) + ".jsonl")
        source.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "worker_name": assignment["name"], "task_id": assignment["task_id"], "observed_at": time.time(),
            "method": "item/completed", "params": {"threadId": assignment.get("worker_id", "worker-a"),
                "turnId": turn_id, "item": {"type": "agentMessage", "id": item_id,
                "phase": "final", "text": text}},
        }
        with source.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row) + "\n")
        return source

    @staticmethod
    def notice(body: dict[str, object], timeout: float) -> dict[str, object]:
        choice = body["choice"]
        return {"choice": {"candidate_id": choice["candidate_id"], "relationship": choice["relationship"]},
                "usage": {"input_tokens": 7, "output_tokens": 2}}

    @staticmethod
    def none(body: dict[str, object], timeout: float) -> dict[str, object]:
        return {"choice": "none", "usage": {"input_tokens": 3, "output_tokens": 1}}

    def pending_mail(self) -> list[dict[str, object]]:
        from agent_mailbox import pending
        return [message for _, message in pending(self.workspace, "coordinator")]

    def candidate_rows(self, config: dict[str, object]) -> list[dict[str, object]]:
        with pit._locked(config) as db:
            return [dict(row) for row in db.execute("SELECT * FROM pit_crew_candidates ORDER BY created_at,candidate_id")]

    def test_relevant_new_evidence_on_enqueues_fixed_advisory_without_task_authority(self) -> None:
        assignment = self.assignment()
        source = self.append_final(assignment, "Evidence: observed cache invalidation after write completes.")
        result = pit.run(self.workspace, assignment, config=self.config(), source=source, selector=self.notice)
        self.assertEqual(result["mode"], "on")
        self.assertTrue(any(row.get("state") == "queued" for row in result["deliveries"]))
        messages = self.pending_mail()
        self.assertEqual(len(messages), 1)
        self.assertIn("possible relevant new evidence", messages[0]["text"])
        self.assertIn("coordinator authority remains unchanged", messages[0]["text"])
        self.assertIsNone(library._task(self.state, "project", "task-a")["attempt_terminal_at"])

    def test_duplicate_and_challenged_assumption_are_distinct_validated_relationships(self) -> None:
        assignment = self.assignment(assumption="Cache invalidation completes after every write.")
        self.assignment("task-b", name="peer", objective="Investigate cache invalidation retry behavior.")
        source = self.append_final(assignment,
            "Evidence: investigating cache invalidation retry behavior found a stale cache after write; this contradicts A-cache.")
        pit.run(self.workspace, assignment, config=self.config(), source=source, selector=self.notice)
        texts = [message["text"] for message in self.pending_mail()]
        self.assertTrue(any("duplicated investigation" in text for text in texts))
        self.assertTrue(any("challenged assumption" in text for text in texts))
        self.assertTrue(all(message["recipient"] == "coordinator" for message in self.pending_mail()))

    def test_none_independent_verification_and_long_work_do_not_create_advisories(self) -> None:
        assignment = self.assignment()
        source = self.append_final(assignment, "Evidence: observed cache invalidation after write completes.")
        result = pit.run(self.workspace, assignment, config=self.config(), source=source, selector=self.none)
        self.assertEqual(result["deliveries"], [])
        self.assertEqual(self.pending_mail(), [])

        independent = self.assignment("task-b", name="independent")
        source = self.append_final(independent,
            "Evidence: independently verifying cache invalidation after write before accepting this result.")
        result = pit.run(self.workspace, independent, config=self.config(), source=source, selector=self.notice)
        self.assertEqual(result["candidates"], [])

        long_work = self.assignment("task-c", name="longwork")
        source = self.append_final(long_work,
            "I worked for twelve hours on a difficult build and will continue ordinary verification.")
        result = pit.run(self.workspace, long_work, config=self.config(), source=source, selector=self.notice)
        self.assertEqual(result["candidates"], [])
        self.assertEqual(self.pending_mail(), [])

    def test_stale_and_unknown_selection_never_enqueue(self) -> None:
        assignment = self.assignment()
        source = self.append_final(assignment, "Evidence: observed cache invalidation after write completes.")

        def stale(body: dict[str, object], timeout: float) -> dict[str, object]:
            source.write_text('{"changed":true}\n', encoding="utf-8")
            return self.notice(body, timeout)

        result = pit.run(self.workspace, assignment, config=self.config(), source=source, selector=stale)
        self.assertTrue(any(row.get("fallback") == "stale_or_unknown_ids" for row in result["evaluations"]))
        self.assertEqual(self.pending_mail(), [])

        assignment = self.assignment("task-b", name="unknown")
        source = self.append_final(assignment, "Evidence: observed cache invalidation after write completes.")

        def unknown(body: dict[str, object], timeout: float) -> dict[str, object]:
            return {"choice": {"candidate_id": "not-a-candidate", "relationship": "relevant_new_evidence"},
                    "usage": {"input_tokens": 1, "output_tokens": 1}}

        result = pit.run(self.workspace, assignment, config=self.config(), source=source, selector=unknown)
        self.assertTrue(any(row.get("fallback") == "pit_crew_invalid_selection" for row in result["evaluations"]))
        self.assertEqual(self.pending_mail(), [])

    def test_foreign_or_unknown_task_event_cannot_use_peer_facts(self) -> None:
        assignment = self.assignment()
        self.assignment("task-b", name="peer", objective="Verify cache invalidation after writes.")
        source = self.workspace / ".de67/state/worker-library/events" / (str(assignment["id"]) + ".jsonl")
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(json.dumps({
            "worker_name": "peer", "task_id": "task-b", "method": "item/completed",
            "params": {"turnId": "foreign-turn", "item": {"type": "agentMessage", "id": "foreign-final",
            "phase": "final", "text": "Evidence: observed cache invalidation after write completes."}}
        }) + "\n", encoding="utf-8")
        result = pit.run(self.workspace, assignment, config=self.config(), source=source, selector=self.notice)
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["evaluations"], [])
        self.assertEqual(self.pending_mail(), [])

    def test_settled_or_rescoped_duplicate_peer_never_enqueues(self) -> None:
        assignment = self.assignment(objective="Investigate cache invalidation retry behavior.")
        self.assignment("task-b", name="peer", objective="Investigate cache invalidation retry behavior for writes.")
        source = self.append_final(assignment,
            "Investigating cache invalidation retry behavior found a stale cache.")

        def settle_peer(body: dict[str, object], timeout: float) -> dict[str, object]:
            with sqlite3.connect(self.state) as db:
                db.execute("UPDATE tasks SET attempt_terminal_at=? WHERE lineage_id=? AND task_id=?",
                           (time.time(), "project", "task-b"))
            return self.notice(body, timeout)

        result = pit.run(self.workspace, assignment, config=self.config(), source=source, selector=settle_peer)
        self.assertTrue(any(row.get("fallback") == "stale_or_unknown_ids" for row in result["evaluations"]))
        self.assertEqual(self.pending_mail(), [])

    def test_restart_replacement_deduplication_and_cooldown(self) -> None:
        assignment = self.assignment()
        source = self.append_final(assignment, "Evidence: observed cache invalidation after write completes.")
        config = self.config(cooldown=60)
        first = pit.run(self.workspace, assignment, config=config, source=source, selector=self.notice, now=100)
        self.assertEqual(len(self.pending_mail()), 1)
        restarted = pit.run(self.workspace, assignment, config=config, source=source, selector=self.notice, now=101)
        self.assertEqual(restarted["records"], 0)
        self.assertEqual(len(self.pending_mail()), 1)

        replacement = source.with_suffix(".replacement")
        replacement.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        os.replace(replacement, source)
        recovered = pit.run(self.workspace, assignment, config=config, source=source, selector=self.notice, now=102)
        self.assertTrue(recovered["source"]["recovered"])
        self.assertEqual(len(self.pending_mail()), 1)

        self.append_final(assignment, "Evidence: confirmed cache invalidation after write on a new source event.",
                          item_id="final-two", turn_id="turn-b")
        cooled = pit.run(self.workspace, assignment, config=config, source=source, selector=self.notice, now=103)
        self.assertTrue(any(row.get("fallback") == "cooldown" for row in cooled["evaluations"]))
        self.assertEqual(len(self.pending_mail()), 1)

        # An in-place truncation also invalidates the cursor rather than making
        # the replacement look like a safe append.
        source.write_text(source.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")
        truncated = pit.run(self.workspace, assignment, config=config, source=source, selector=self.notice, now=104)
        self.assertTrue(truncated["source"]["recovered"])

    def test_candidate_persistence_failure_replays_source_instead_of_skipping_it(self) -> None:
        assignment = self.assignment()
        source = self.append_final(assignment, "Evidence: observed cache invalidation after write completes.")
        config = self.config()
        with patch.object(pit, "_store_candidates", side_effect=pit.PitCrewError("test_store_failure")):
            with self.assertRaisesRegex(pit.PitCrewError, "test_store_failure"):
                pit.run(self.workspace, assignment, config=config, source=source, selector=self.notice)
        with pit._locked(config) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM pit_crew_sources").fetchone()[0], 0)

        retried = pit.run(self.workspace, assignment, config=config, source=source, selector=self.notice)
        self.assertEqual(retried["records"], 1)
        self.assertTrue(retried["source"]["cursor_committed"])
        self.assertEqual(len(self.pending_mail()), 1)

    def test_concurrent_and_uncertain_delivery_reconcile_without_resend(self) -> None:
        assignment = self.assignment()
        source = self.append_final(assignment, "Evidence: observed cache invalidation after write completes.")
        config = self.config()
        pit.run(self.workspace, assignment, config=config, source=source, selector=None)
        candidate = self.candidate_rows(config)[0]
        outcomes: list[str] = []
        threads = [threading.Thread(target=lambda: outcomes.append(pit._deliver(self.workspace, config, candidate, 10)))
                   for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(3)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(len(self.pending_mail()), 1)
        self.assertTrue(set(outcomes) <= {"queued", "already_queued", "reconciled", "uncertain"})

        assignment = self.assignment("task-b", name="uncertain")
        source = self.append_final(assignment, "Evidence: observed cache invalidation after write completes.")
        pit.run(self.workspace, assignment, config=config, source=source, selector=None)
        candidate = [row for row in self.candidate_rows(config) if row["task_id"] == "task-b"][0]
        key = pit._digest({"event_id": candidate["event_id"], "recipient": "coordinator",
                           "task_id": candidate["task_id"], "relationship": candidate["relationship"]})
        with pit._locked(config) as db:
            db.execute("""INSERT INTO pit_crew_emissions(emission_key,event_id,recipient,task_id,relationship,
                       candidate_id,state,mailbox_id,created_at,updated_at,error) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                       (key, candidate["event_id"], "coordinator", candidate["task_id"], candidate["relationship"],
                        candidate["candidate_id"], "prepared", None, 11, 11, None))
        self.assertEqual(pit._deliver(self.workspace, config, candidate, 12), "uncertain")
        self.assertEqual(len(self.pending_mail()), 1)
        from agent_mailbox import enqueue
        enqueue(self.workspace, "coordinator", "pit-crew:" + key, pit._message(candidate, key))
        self.assertEqual(pit._deliver(self.workspace, config, candidate, 13), "reconciled")
        self.assertEqual(len(self.pending_mail()), 2)

    def test_shadow_guard_failure_and_off_are_bounded(self) -> None:
        assignment = self.assignment()
        source = self.append_final(assignment, "Evidence: observed cache invalidation after write completes.")
        shadow = pit.run(self.workspace, assignment, config=self.config("shadow"), source=source, selector=self.notice)
        self.assertEqual(shadow["deliveries"], [])
        self.assertTrue(any(row.get("selection") == "notice" for row in shadow["evaluations"]))
        self.assertEqual(self.pending_mail(), [])

        broken_assignment = self.assignment("task-b", name="broken")
        broken_source = self.append_final(broken_assignment, "Evidence: observed cache invalidation after write completes.")
        result = pit.run(self.workspace, broken_assignment, config=self.config(max_calls=0), source=broken_source,
                         selector=lambda body, timeout: self.fail("guard should block transport"))
        self.assertTrue(any(row.get("fallback") == "disabled_budget" for row in result["evaluations"]))
        self.assertEqual(self.pending_mail(), [])

        timeout_assignment = self.assignment("task-c", name="timeout")
        timeout_source = self.append_final(timeout_assignment, "Evidence: observed cache invalidation after write completes.")
        timeout_config = self.config()
        timeout_config["provider_guard"] = {**timeout_config["provider_guard"], "scope_id": "pit-crew-timeout"}
        result = pit.run(self.workspace, timeout_assignment, config=timeout_config, source=timeout_source,
                         selector=lambda body, timeout: (_ for _ in ()).throw(TimeoutError()))
        self.assertTrue(any(row.get("fallback") == "provider_timeout" and row.get("provider_calls") == 1
                            for row in result["evaluations"]))
        bad = timeout_config
        bad["provider_guard"] = {**bad["provider_guard"], "mode": "shadow"}
        with self.assertRaisesRegex(pit.PitCrewError, "pit_crew_provider_guard_mode_mismatch"):
            pit.run(self.workspace, timeout_assignment, config=bad, source=timeout_source, selector=self.notice)

        unbounded = self.config()
        unbounded["cooldown_seconds"] = float("inf")
        with self.assertRaisesRegex(pit.PitCrewError, "pit_crew_invalid_cooldown_seconds"):
            pit.run(self.workspace, assignment, config=unbounded, source=source, selector=self.notice)

        off = pit.run(self.workspace, assignment, config={"mode": "off"}, source=source, selector=self.notice)
        self.assertEqual(off["records"], 0)

    def test_worker_hook_unconfigured_or_broken_and_package_copy_are_isolated(self) -> None:
        # The real hook is inert when unconfigured.
        assignment = self.assignment()
        self.dispatcher._audit(assignment, {"method": "thread/tokenUsage/updated", "params": {"threadId": "worker-1"}})
        self.assertFalse((self.workspace / ".de67/state/pit-crew.sqlite3").exists())

        # The only production seam is the completed audit append.  Even an
        # explicitly configured on route has no supplied selector here, so it
        # derives durable candidates without a provider call or mailbox notice.
        config_path = self.workspace / ".de67/state/workspace.json"
        config_path.write_text(json.dumps({"jev_pit_crew": self.config()}), encoding="utf-8")
        self.dispatcher._audit(assignment, {"method": "item/completed", "params": {
            "threadId": "worker-1", "turnId": "turn-hook", "item": {"type": "agentMessage",
            "id": "hook-final", "phase": "final", "text": "Evidence: observed cache invalidation after write completes."}}})
        self.assertTrue((self.workspace / ".de67/state/pit-crew.sqlite3").exists())
        self.assertTrue(self.candidate_rows(self.config()))
        self.assertEqual(self.pending_mail(), [])

        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "de67-copy"
            script = copied / "de-67-3/scripts/worker_library.py"
            script.parent.mkdir(parents=True)
            shutil.copy2(ROOT / "de-67-3/scripts/worker_library.py", script)
            spec = importlib.util.spec_from_file_location("copied_worker_library", script)
            assert spec and spec.loader
            copied_library = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(copied_library)
            config_path.write_text(json.dumps({"jev_pit_crew": {"mode": "on"}}), encoding="utf-8")
            dispatcher = object.__new__(copied_library.WorkerDispatcher)
            dispatcher.workspace = self.workspace
            copied_library.WorkerDispatcher._audit(dispatcher, {"id": "copy-absent", "name": "pilot", "task_id": "task-a"},
                                                    {"method": "thread/tokenUsage/updated", "params": {}})
            self.assertFalse((self.workspace / ".de67/state/agent-mail").exists())

            broken = copied / "integrations/jev_pit_crew/pit_crew.py"
            broken.parent.mkdir(parents=True)
            broken.write_text("raise RuntimeError('broken optional integration')\n", encoding="utf-8")
            copied_library.WorkerDispatcher._audit(dispatcher, {"id": "copy-broken", "name": "pilot", "task_id": "task-a"},
                                                    {"method": "thread/tokenUsage/updated", "params": {}})
            self.assertFalse((self.workspace / ".de67/state/agent-mail").exists())

            # A copied complete package locates its sibling guard/mailbox by its
            # own root and writes state only to the target workspace.
            for relative in ("integrations/jev_pit_crew/pit_crew.py", "integrations/jev_telescope/provider_guard.py",
                             "de-67-3/scripts/agent_mailbox.py"):
                target = copied / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, target)
            copy_spec = importlib.util.spec_from_file_location("copied_pit_crew", copied / "integrations/jev_pit_crew/pit_crew.py")
            assert copy_spec and copy_spec.loader
            copy_pit = importlib.util.module_from_spec(copy_spec)
            sys.modules["copied_pit_crew"] = copy_pit
            copy_spec.loader.exec_module(copy_pit)
            copy_guard = copy_pit._guard_module()
            with patch.object(copy_guard, "_disposable_context_roots", return_value=()):
                assignment = self.assignment("task-b", name="copied")
                source = self.append_final(assignment, "Evidence: observed cache invalidation after write completes.")
                copied_config = self.config()
                copied_config["state_path"] = str(self.workspace / ".de67/state/copied-pit-crew.sqlite3")
                copy_pit.run(self.workspace, assignment, config=copied_config, source=source, selector=self.notice)
            self.assertTrue((self.workspace / ".de67/state/copied-pit-crew.sqlite3").exists())
            self.assertFalse(any(path.suffix == ".sqlite3" for path in copied.rglob("*.sqlite3")))

    def test_boundary_candidate_needs_a_later_explicit_selector_before_delivery(self) -> None:
        assignment = self.assignment()
        config = self.config()
        (self.workspace / ".de67/state/workspace.json").write_text(
            json.dumps({"jev_pit_crew": config}), encoding="utf-8"
        )
        self.dispatcher._audit(assignment, {"method": "item/completed", "params": {
            "threadId": "worker-1", "turnId": "turn-later", "item": {"type": "agentMessage",
            "id": "later-final", "phase": "final", "text":
            "Evidence: observed cache invalidation after write completes."}}})
        self.assertEqual(self.pending_mail(), [])

        selected = pit.run(self.workspace, assignment, config=config, selector=self.notice)
        self.assertTrue(any(row.get("selection") == "notice" for row in selected["evaluations"]))
        self.assertTrue(any(row.get("state") == "queued" for row in selected["deliveries"]))
        self.assertEqual(len(self.pending_mail()), 1)


if __name__ == "__main__":
    unittest.main()
