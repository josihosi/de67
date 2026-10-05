from __future__ import annotations

import json
from pathlib import Path
import unittest

from test_worker_library import FakeRpc, Rejected, WorkerFixture, library
from agent_mailbox import pending


class TierRpc(FakeRpc):
    def __init__(self, configured_tier="fast", *, include_tier=True):
        super().__init__()
        self.configured_tier = configured_tier
        self.include_tier = include_tier

    def call(self, method, params):
        result = super().call(method, params)
        if method in {"thread/start", "thread/resume"} and self.include_tier:
            # The installed schema returns configured serviceTier beside thread.
            result["serviceTier"] = self.configured_tier
        return result


class WorkerLibraryFastTests(WorkerFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.rpc = TierRpc()
        self.dispatcher = library.WorkerDispatcher(self.workspace, self.rpc, self.binding)

    def speed_events(self, name="pilot"):
        assignment = library.describe(self.workspace, name)["assignment"]
        return [row for row in map(json.loads, Path(assignment["events_path"]).read_text().splitlines())
                if row["method"].startswith("de67/workerSpeed/")]

    def assert_fast_params(self, method, effort):
        loaded = [params for name, params in self.rpc.calls if name == method][-1]
        self.assertEqual(loaded["model"], getattr(self, "fast_model", "gpt-6-luna"))
        self.assertEqual(loaded["serviceTier"], "fast")
        self.assertEqual(loaded["config"], {"model_reasoning_effort": effort, "features.fast_mode": True})
        turn = [params for name, params in self.rpc.calls if name == "turn/start"][-1]
        self.assertEqual(turn["effort"], effort)
        self.assertEqual(turn["serviceTierForTurn"], "fast")
        self.assertNotIn("serviceTier", turn)

    def test_luna_start_and_returned_continuation_preserve_identity_and_effort(self):
        self.worker(effort="max")
        self.assign()
        self.dispatcher.process_pending()
        self.assert_fast_params("thread/start", "max")
        original = self.returned()
        claim = library._task(self.state, "project", "task-a")["claim_id"]
        library.message(self.workspace, "pilot", "Continue the same task", environment=self.env)
        self.dispatcher.process_pending()
        self.assert_fast_params("thread/resume", "max")
        current = library.describe(self.workspace, "pilot")["assignment"]
        self.assertEqual(current["worker_id"], original["worker_id"])
        self.assertEqual(library._task(self.state, "project", "task-a")["claim_id"], claim)
        configured = [row["params"] for row in self.speed_events()
                      if row["method"] == "de67/workerSpeed/configured"]
        self.assertEqual([row["rpcMethod"] for row in configured], ["thread/start", "thread/resume"])
        for row in configured:
            self.assertEqual(row["requestedTier"], "fast")
            self.assertEqual(row["returnedConfiguredTier"], "fast")
            self.assertTrue(row["tierFieldPresent"])
            self.assertFalse(row["perTurnTelemetry"])
        self.assertEqual(self.rpc.turn_count, 2)

    def test_server_priority_alias_confirms_configured_fast_without_false_warning(self):
        self.rpc.configured_tier = "priority"
        self.worker()
        self.assign()
        self.dispatcher.process_pending()
        event = [r for r in self.speed_events() if r["method"] == "de67/workerSpeed/configured"][-1]
        self.assertEqual(event["params"]["requestedTier"], "fast")
        self.assertEqual(event["params"]["returnedConfiguredTier"], "priority")
        self.assertFalse(event["params"]["perTurnTelemetry"])
        self.assertFalse(any("Fast execution is unverified" in msg["text"]
                             for _, msg in pending(self.workspace, "coordinator")))
        self.assertEqual(self.rpc.turn_count, 1)

    def test_non_luna_dispatch_retains_existing_configuration(self):
        for model in ["gpt-6-astra"]:
            with self.subTest(model=model):
                self.worker(name=model, model=model, effort="medium")
                self.assign(name=model, task_id=model)
                self.dispatcher.process_pending()
                loaded = [p for m, p in self.rpc.calls if m == "thread/start"][-1]
                turn = [p for m, p in self.rpc.calls if m == "turn/start"][-1]
                self.assertEqual(loaded["model"], model)
                self.assertEqual(loaded["config"], {"model_reasoning_effort": "medium"})
                self.assertEqual(turn["effort"], "medium")
                self.assertNotIn("serviceTier", loaded)
                self.assertNotIn("serviceTier", turn)
                self.assertNotIn("serviceTierForTurn", turn)

    def test_astra_resume_preserves_configuration_without_fast(self):
        self.worker(model="gpt-6-astra", effort="medium")
        self.assign()
        self.dispatcher.process_pending()
        original = self.returned()
        library.message(self.workspace, "pilot", "Continue", environment=self.env)
        self.dispatcher.process_pending()
        loaded = [p for m, p in self.rpc.calls if m == "thread/resume"][-1]
        turn = [p for m, p in self.rpc.calls if m == "turn/start"][-1]
        self.assertEqual(loaded["model"], "gpt-6-astra")
        self.assertEqual(loaded["config"], {"model_reasoning_effort": "medium"})
        self.assertNotIn("serviceTier", loaded)
        self.assertNotIn("serviceTierForTurn", turn)
        self.assertEqual(turn["effort"], "medium")
        self.assertEqual(library.describe(self.workspace, "pilot")["assignment"]["worker_id"], original["worker_id"])
        self.assertEqual(self.speed_events(), [])

    def test_active_luna_steering_sends_no_speed_override_or_new_turn(self):
        self.worker()
        self.assign()
        self.dispatcher.process_pending()
        before = len(self.rpc.calls)
        evidence_before = len(self.speed_events())
        request = library.message(self.workspace, "pilot", "Use this correction", environment=self.env)
        self.dispatcher.process_pending()
        self.assertEqual([method for method, _ in self.rpc.calls[before:]], ["turn/steer"])
        params = self.rpc.calls[-1][1]
        self.assertNotIn("serviceTier", params)
        self.assertNotIn("serviceTierForTurn", params)
        self.assertNotIn("config", params)
        self.assertEqual(library.request_status(self.workspace, request["request_id"])["state"], "delivered")
        self.assertEqual(len(self.speed_events()), evidence_before)
        self.assertEqual(self.rpc.turn_count, 1)

    def test_returned_default_and_missing_tier_remain_visible_without_replay(self):
        for index, (configured, present) in enumerate([("default", True), (None, True), (None, False)]):
            with self.subTest(configured=configured, present=present):
                name = "tier-" + str(index)
                self.rpc.configured_tier, self.rpc.include_tier = configured, present
                self.worker(name=name)
                request = self.assign(name=name, task_id=name)
                self.dispatcher.process_pending()
                event = [r for r in self.speed_events(name) if r["method"] == "de67/workerSpeed/configured"][-1]
                self.assertEqual(event["params"]["returnedConfiguredTier"], configured)
                self.assertEqual(event["params"]["tierFieldPresent"], present)
                self.assertTrue(any("Fast execution is unverified" in msg["text"]
                                    for _, msg in pending(self.workspace, "coordinator")))
                self.assertEqual(library.request_status(self.workspace, request["request_id"])["state"], "submitted")
                count = len(self.rpc.calls)
                self.dispatcher.process_pending()
                self.assertEqual(len(self.rpc.calls), count)

    def test_thread_fast_refusal_rejects_before_claim_without_standard_fallback(self):
        self.worker()
        request = self.assign()
        self.rpc.fail_next = ("thread/start", Rejected("Fast tier unsupported"))
        self.dispatcher.process_pending()
        self.assertEqual(library.request_status(self.workspace, request["request_id"])["state"], "rejected")
        self.assertIsNone(library._task(self.state, "project", "task-a")["worker_id"])
        self.assertEqual(self.rpc.turn_count, 0)
        self.dispatcher.process_pending()
        self.assertEqual([m for m, _ in self.rpc.calls], ["thread/start"])

    def test_turn_fast_refusal_does_not_fallback_or_duplicate(self):
        self.worker()
        request = self.assign()
        self.rpc.fail_next = ("turn/start", Rejected("Fast tier unavailable"))
        self.dispatcher.process_pending()
        self.assertEqual(library.request_status(self.workspace, request["request_id"])["state"], "rejected")
        self.assertEqual(library.describe(self.workspace, "pilot")["status"], "failed")
        self.dispatcher.process_pending()
        turns = [p for m, p in self.rpc.calls if m == "turn/start"]
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["serviceTierForTurn"], "fast")

    def test_resume_fast_refusal_restores_previous_turn_without_resubmission(self):
        self.worker()
        self.assign()
        self.dispatcher.process_pending()
        original = self.returned()
        request = library.message(self.workspace, "pilot", "Continue", environment=self.env)
        self.rpc.fail_next = ("thread/resume", Rejected("Fast tier unavailable"))
        self.dispatcher.process_pending()
        self.assertEqual(library.request_status(self.workspace, request["request_id"])["state"], "rejected")
        current = library.describe(self.workspace, "pilot")["assignment"]
        for field in ["status", "worker_id", "turn_id", "request_id"]:
            self.assertEqual(current[field], original[field])
        count = len(self.rpc.calls)
        self.dispatcher.process_pending()
        self.assertEqual(len(self.rpc.calls), count)
        self.assertEqual(self.rpc.turn_count, 1)

    def test_lost_fast_turn_receipt_preserves_uncertainty_without_duplicate(self):
        self.worker()
        request = self.assign()
        self.rpc.fail_next = ("turn/start", TimeoutError("Receipt lost"))
        self.dispatcher.process_pending()
        self.assertEqual(library.request_status(self.workspace, request["request_id"])["state"], "uncertain")
        self.dispatcher.process_pending()
        self.assertEqual(len([p for m, p in self.rpc.calls if m == "turn/start"]), 1)
        with self.assertRaises(library.WorkerLibraryError):
            library.message(self.workspace, "pilot", "Repeat", environment=self.env)


class SolWorkerLibraryFastTests(WorkerLibraryFastTests):
    fast_model = "gpt-6.1-sol"

    def worker(self, *args, **kwargs):
        kwargs.setdefault("model", self.fast_model)
        return super().worker(*args, **kwargs)


if __name__ == "__main__":
    unittest.main()
