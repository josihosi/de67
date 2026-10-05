"""Prompt boundaries plus real scoped validator, policy and worker handoff controls.

RPC fixtures exercise dispatch, not model judgment or actual-use adoption.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import codex_runner
import coordinator_supervisor as supervisor
import mutation_guard as guard
import mutator_session
import policy_kernel
from test_worker_library import WorkerFixture, library


def fs():
    return "Status: Refrozen\n" + "".join(
        f"<!-- DE67:DFS-SLICE:BEGIN id=R-{key}-S001 claim=R-{key} -->\n"
        f"- [ ] 🔴 R-{key} — Current outcome {key}\n"
        f"Old tactic {key}.\n"
        f"<!-- DE67:DFS-SLICE:END id=R-{key}-S001 claim=R-{key} -->\n"
        for key in ("task-a", "task-b")
    )


class PromptBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        (self.workspace / ".de67").mkdir()
        (self.workspace / ".de67/mutation-suggestions.md").write_text(
            "## Pending suggestions\n"
            "- Owner-authorized [trigger]: Repair installed adapter\n"
            "- Owner-authorized [defer]: Unrelated future improvement\n"
        )

    def prompt(self, kind):
        return supervisor.mutation_reviewer_prompt(
            self.workspace, self.workspace / "state", "project",
            supervisor.MutationGate(kind, "exact-id", None))

    def test_event_batch_excludes_deferred_queue_and_broad_usage_sweep(self):
        prompt = self.prompt("owner-suggestion")
        self.assertIn("Repair installed adapter", prompt)
        self.assertNotIn("Unrelated future improvement", prompt)
        self.assertNotIn(supervisor.mutation_maintenance_contract(), prompt)
        self.assertNotIn("Disposition every pending owner entry", prompt)
        self.assertIn("No coordinator or roster worker is active", prompt)
        self.assertIn("quiet exclusive review", prompt)

    def test_incident_gate_does_not_absorb_unrelated_owner_triggers(self):
        prompt = self.prompt("incident-review")
        self.assertIn("exact incident identity", prompt)
        self.assertNotIn("Repair installed adapter", prompt)

    def test_periodic_review_preserves_complete_queue_and_efficiency_work(self):
        for kind in ("random", "random mutation"):
            prompt = self.prompt(kind)
            self.assertIn("complete pending section", prompt)
            self.assertIn("Disposition every pending owner entry", prompt)
            self.assertIn(supervisor.mutation_maintenance_contract(), prompt)

    def test_owner_and_coordinator_share_authority_and_affected_owner_boundary(self):
        contract = supervisor.scoped_product_clarification_contract()
        owner = mutator_session.owner_prompt(self.workspace, ROOT / "scripts", sys.executable)
        self.assertIn(contract, owner)
        self.assertIn(contract, supervisor.coordinator_ledger_contract())
        for requirement in (
            "explicitly owner-authorized", "same current product outcome",
            "agent report", "grants no authority", "rejected/unclear authority",
            "Respect owner stops", "validate_scoped_dfs_amendment",
            "safe handoff", "affected owner", "Independent work continues",
            "pending input", "task/save/clock", "quiet exclusive review",
        ):
            self.assertIn(requirement, contract)
        self.assertNotIn("Before changing active method or product state", owner)

    def test_fresh_runner_keeps_event_scope_and_original_bindings(self):
        gate = supervisor.MutationGate("owner-suggestion", "exact-id", None)
        bindings = "\nCurrent invocation bindings (use these values directly; exact)\n{}"
        prompt = self.prompt(gate.kind) + bindings
        env = {"DE67_PROCESS_ROLE": "mutation-reviewer",
               **supervisor.mutation_reviewer_environment(gate)}
        result = codex_runner.current_coordinator_prompt(self.workspace, prompt, env)
        self.assertEqual(result, prompt)
        self.assertNotIn(supervisor.mutation_maintenance_contract(), result)
        self.assertTrue(result.endswith(bindings))

    def test_missing_or_invalid_runner_gate_cannot_infer_broader_authority(self):
        prompt = self.prompt("owner-suggestion") + "\nCurrent invocation bindings (use these values directly; exact)\n{}"
        env = {"DE67_PROCESS_ROLE": "mutation-reviewer"}
        self.assertEqual(codex_runner.current_coordinator_prompt(self.workspace, prompt, env), prompt)
        for raw in ("bad json", "[]", '{}', '{"kind":false}'):
            with self.assertRaises(codex_runner.RunnerError):
                codex_runner.current_coordinator_prompt(self.workspace, prompt,
                    {**env, "DE67_MUTATION_GATE_JSON": raw})


class ScopedHandoffTests(WorkerFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.worker("affected", model="gpt-6.1-sol")
        self.worker("independent", model="gpt-6.1-sol")
        self.spec = self.workspace / ".de67/FS.md"
        self.spec.write_text(fs())
        (self.workspace / ".de67/work-ledger.md").write_text(
            "- [ ] R-task-a — Current outcome task-a\n"
            "  - DFS slices: `R-task-a-S001`\n"
            "  - Assignment task-a: Correct the authorized caller.\n"
            "  - Assignment task-b: Continue independent evidence.\n")
        for task in ("task-a", "task-b"):
            self.harness.start_task("project", task, "R-task-a", 3600, now=time.time())
        packets = {call["task_id"]: call["dispatch_packet"] for call in
                   policy_kernel.unbound_worker_spawns(self.workspace, self.state, "project")}
        for worker, task in (("affected", "task-a"), ("independent", "task-b")):
            packet = packets[task]
            self.assign(worker, task, (Path(packet["path"]), packet["sha256"]))
        self.dispatcher.process_pending()

    def clocks(self):
        return [tuple(row) for row in self.harness.connection.execute(
            "SELECT task_id,started_at,deadline_at,worker_id,released_at "
            "FROM tasks LEFT JOIN worker_claims USING(lineage_id,task_id) ORDER BY task_id")]

    def facts(self):
        return policy_kernel.workspace_facts(self.workspace, self.state, "project", now=time.time())

    def test_authorized_scoped_amendment_reaches_owner_with_independent_work_running(self):
        before = self.clocks()
        proposed = self.workspace / "candidate-FS.md"
        proposed.write_text(fs().replace("Old tactic task-a.", "Use the real physical connector; preserve refusal."))
        self.assertEqual(guard.validate_scoped_dfs_amendment(self.spec, proposed, ("R-task-a",)),
                         ("R-task-a-S001",))
        self.spec.write_text(proposed.read_text())
        ledger = self.workspace / ".de67/work-ledger.md"
        ledger.write_text(ledger.read_text().replace("Correct the authorized caller.",
            "Correct the physical connector; preserve genuine refusal."))
        update = "Owner-authorized same-outcome clarification for task-a: use the real physical connector; preserve refusal. Same task/save/clock and input owner."
        queued = library.message(self.workspace, "affected", update, environment=self.env)
        self.dispatcher.process_pending()
        steering = [params for method, params in self.rpc.calls if method == "turn/steer"]
        self.assertEqual(len(steering), 1)
        self.assertEqual(steering[0]["input"][0]["text"], update)
        self.assertEqual(library.request_status(self.workspace, queued["request_id"])["state"], "delivered")
        self.assertEqual(library.describe(self.workspace, "independent")["assignment"]["status"], "running")
        self.assertEqual(self.clocks(), before)
        self.assertEqual(library._task(self.state, "project", "task-a")["claim_id"],
                         library._task(self.state, "project", "task-b")["claim_id"])
        self.assertNotIn("pending_suggestions", self.facts())
        self.assertIsNone(supervisor.mutation_gate(self.state, "project", self.workspace))

    def test_explicit_trigger_remains_gate_and_deferred_proposal_does_not(self):
        queue = self.workspace / ".de67/mutation-suggestions.md"
        queue.write_text("## Pending suggestions\n- Owner-authorized [defer]: Future improvement\n")
        self.assertNotIn("pending_suggestions", self.facts())
        queue.write_text("## Pending suggestions\n- Owner-authorized [trigger]: Installed method change\n")
        self.assertIn("pending_suggestions", self.facts())
        self.assertIsNone(supervisor.mutation_gate(self.state, "project", self.workspace))
        self.returned("affected")
        self.returned("independent")
        self.assertEqual(supervisor.mutation_gate(self.state, "project", self.workspace).kind, "owner-suggestion")

    def test_lost_affected_worker_ownership_rejects_handoff_without_other_worker_input(self):
        with self.harness.connection:
            self.harness.connection.execute(
                "UPDATE worker_claims SET worker_id='other-owner' WHERE task_id='task-a'")
        calls = len(self.rpc.calls)
        with self.assertRaisesRegex(library.WorkerLibraryError, "no longer owns"):
            library.message(self.workspace, "affected", "Clarification", environment=self.env)
        self.assertEqual(len(self.rpc.calls), calls)
        self.assertEqual(library.describe(self.workspace, "independent")["assignment"]["status"], "running")

    def test_noncoordinator_cannot_send_authority_or_take_worker_input(self):
        with self.assertRaisesRegex(library.WorkerLibraryError, "Only the current Sol"):
            library.message(self.workspace, "affected", "Bug label grants authority", environment={})
        self.assertFalse(any(method == "turn/steer" for method, _ in self.rpc.calls))

    def test_scope_validator_rejects_missing_authority_claims_and_unrelated_or_accepted_changes(self):
        proposed = self.workspace / "candidate-FS.md"
        cases = [
            (fs().replace("Old tactic task-a.", "Repair"), ()),
            (fs().replace("Old tactic task-b.", "Repair"), ("R-task-a",)),
            (fs().replace("[ ] 🔴 R-task-a", "[x] R-task-a"), ("R-task-a",)),
        ]
        for text, claims in cases:
            proposed.write_text(text)
            with self.assertRaises(guard.GuardError):
                guard.validate_scoped_dfs_amendment(self.spec, proposed, claims)
        self.assertEqual(self.spec.read_text(), fs())


if __name__ == "__main__":
    unittest.main()
