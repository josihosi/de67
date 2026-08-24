from __future__ import annotations

import copy
import importlib.util
import itertools
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "policy_kernel.py"
SOURCE = ROOT / "assets" / "environment" / "phase3-policy.json"
CONTRACTS = ROOT / "assets" / "environment" / "phase3-contracts.json"
SPEC = importlib.util.spec_from_file_location("de67_policy_kernel", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
kernel = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = kernel
SPEC.loader.exec_module(kernel)


def source_policy() -> dict:
    return json.loads(SOURCE.read_text(encoding="utf-8"))


CASES = (
    ({"integrity_incident", "live_task"}, "review_integrity_incident"),
    ({"deadline_expired", "worker_completed"}, "record_deadline_miss"),
    ({"deadline_incident", "worker_completed"}, "review_deadline_incident"),
    ({"restart_requested", "open_claim"}, "acknowledge_restart"),
    ({"random_mutation_due"}, "review_scheduled_mutation"),
    ({"dfs_review_due", "pending_suggestions"}, "review_scheduled_mutation"),
    ({"universal_review_due"}, "review_scheduled_mutation"),
    ({"accepted_evidence"}, "apply_guarded_dfs_acceptance"),
    ({"worker_completed"}, "receive_worker_result"),
    ({"worker_finding"}, "receive_worker_result"),
    ({"worker_abandoned"}, "receive_worker_result"),
    ({"owner_reply", "blocked_ledger"}, "consume_owner_reply"),
    ({"blocked_ledger"}, "audit_blocker"),
    ({"live_task"}, "wait_for_worker_event"),
    ({"closure_ready", "open_gap", "executable_route"}, "dispatch_closure_worker"),
    ({"open_claim", "executable_route"}, "dispatch_exploration_worker"),
    ({"ledger_work", "executable_route"}, "dispatch_exploration_worker"),
    ({"red_dfs_work"}, "refill_ledger"),
    ({"dfs_complete"}, "stop"),
    (set(), "inspect_state"),
)


class PolicyKernelTests(unittest.TestCase):
    def test_source_policy_covers_legacy_decision_corpus(self) -> None:
        policy = source_policy()
        for facts, expected in CASES:
            with self.subTest(facts=facts):
                self.assertEqual(kernel.decide(policy, facts).action, expected)

    def test_compile_is_deterministic_and_round_trips(self) -> None:
        policy = source_policy()
        first = kernel.compile_policy(policy)
        second = kernel.compile_policy(copy.deepcopy(policy))
        self.assertEqual(first, second)
        self.assertEqual(kernel.load_policy_bytes(first), kernel.validate_policy(policy))

    def test_production_vocabulary_is_not_frozen_into_the_interpreter(self) -> None:
        interpreter = SCRIPT.read_text(encoding="utf-8")
        for word in (
            "review_deadline_incident", "wait_for_worker_event",
            "wake_no_later_than_item_deadline", "suggestions_pending",
            "claim_accepted", "task_completed",
        ):
            with self.subTest(word=word):
                self.assertNotIn(word, interpreter)

    def test_packaged_bytecode_exactly_matches_source(self) -> None:
        packaged = ROOT / "assets" / "environment" / "phase3-policy.d67"
        self.assertEqual(packaged.read_bytes(), kernel.compile_policy(source_policy()))

    def test_machine_candidate_guard_accepts_current_ir(self) -> None:
        guarded = kernel.guard_policy_candidate(source_policy(), kernel.load_contracts(CONTRACTS))
        self.assertEqual(kernel.policy_digest(guarded), kernel.policy_digest(source_policy()))

    def test_machine_candidate_guard_rejects_deleted_required_rule(self) -> None:
        policy = source_policy()
        policy["rules"] = [rule for rule in policy["rules"] if rule["id"] != "D1"]
        with self.assertRaisesRegex(kernel.PolicyError, "deadline-preempts-result"):
            kernel.guard_policy_candidate(policy, kernel.load_contracts(CONTRACTS))

    def test_machine_candidate_guard_rejects_redundant_rule(self) -> None:
        policy = source_policy()
        duplicate = copy.deepcopy(policy["rules"][-1])
        duplicate["id"] = "REDUNDANT"
        duplicate["priority"] = -1
        policy["rules"].append(duplicate)
        with self.assertRaisesRegex(kernel.PolicyError, "redundant"):
            kernel.guard_policy_candidate(policy, kernel.load_contracts(CONTRACTS))

    def test_machine_candidate_guard_rejects_mutation_route_that_ignores_ledger(self) -> None:
        policy = source_policy()
        deadline = next(rule for rule in policy["rules"] if rule["id"] == "D1")
        deadline["obligations"].remove("disposition_relevant_suggestions")
        with self.assertRaisesRegex(kernel.PolicyError, "required obligations"):
            kernel.guard_policy_candidate(policy, kernel.load_contracts(CONTRACTS))

    def test_machine_candidate_guard_rejects_deadline_cadence_restart_authority(self) -> None:
        policy = source_policy()
        deadline = next(rule for rule in policy["rules"] if rule["id"] == "D1")
        deadline["obligations"].remove(
            "cadence_is_observation_not_restart_authority"
        )
        with self.assertRaisesRegex(kernel.PolicyError, "required obligations"):
            kernel.guard_policy_candidate(policy, kernel.load_contracts(CONTRACTS))

    def test_machine_candidate_guard_rejects_underspecified_dispatch_clock(self) -> None:
        for rule_id in ("C1", "E1"):
            with self.subTest(rule_id=rule_id):
                policy = source_policy()
                dispatch = next(
                    rule for rule in policy["rules"] if rule["id"] == rule_id
                )
                dispatch["obligations"].remove(
                    "set_deliverable_deadline_with_problem_margin"
                )
                with self.assertRaisesRegex(kernel.PolicyError, "required obligations"):
                    kernel.guard_policy_candidate(
                        policy, kernel.load_contracts(CONTRACTS)
                    )

    def test_machine_candidate_guard_rejects_unbounded_worker_wait(self) -> None:
        policy = source_policy()
        wait = next(rule for rule in policy["rules"] if rule["id"] == "W1")
        wait["obligations"].remove("wake_no_later_than_item_deadline")
        with self.assertRaisesRegex(kernel.PolicyError, "required obligations"):
            kernel.guard_policy_candidate(policy, kernel.load_contracts(CONTRACTS))

    def test_compiled_policy_is_smaller_than_runtime_markdown(self) -> None:
        compiled = kernel.compile_policy(source_policy())
        prose = sum(
            (ROOT / "assets" / "environment" / name).stat().st_size
            for name in ("orchestrator-guidelines.md", "test-and-task-guidelines.md")
        )
        self.assertLess(len(compiled), prose)

    def test_truncated_corrupt_and_identity_mismatched_bytecode_fail_closed(self) -> None:
        compiled = kernel.compile_policy(source_policy())
        candidates = (compiled[:20], compiled[:-1], compiled[:10] + b"x" + compiled[11:])
        for candidate in candidates:
            with self.subTest(size=len(candidate)):
                with self.assertRaises(kernel.PolicyError):
                    kernel.load_policy_bytes(candidate)

    def test_duplicate_rule_id_is_rejected(self) -> None:
        policy = source_policy()
        policy["rules"].append(copy.deepcopy(policy["rules"][0]))
        with self.assertRaisesRegex(kernel.PolicyError, "unique"):
            kernel.validate_policy(policy)

    def test_rule_without_positive_predicate_is_rejected(self) -> None:
        policy = source_policy()
        policy["rules"][0].pop("all")
        with self.assertRaisesRegex(kernel.PolicyError, "positive"):
            kernel.validate_policy(policy)

    def test_equal_priority_conflicting_actions_fail_closed(self) -> None:
        policy = source_policy()
        policy["rules"].append({
            "id": "CONFLICT", "priority": 100, "all": ["integrity_incident"],
            "action": "ignore_incident", "reads": [], "obligations": [],
        })
        with self.assertRaisesRegex(kernel.PolicyError, "Ambiguous"):
            kernel.decide(policy, {"integrity_incident"})

    def test_equal_priority_same_action_unions_requirements(self) -> None:
        policy = source_policy()
        policy["rules"].append({
            "id": "I2", "priority": 100, "all": ["integrity_incident"],
            "action": "review_integrity_incident", "reads": ["extra"],
            "obligations": ["extra_check"],
        })
        decision = kernel.decide(policy, {"integrity_incident"})
        self.assertIn("extra", decision.reads)
        self.assertIn("extra_check", decision.obligations)

    def test_incidents_preempt_late_worker_results_and_acceptance(self) -> None:
        policy = source_policy()
        for incident, expected in (
            ("deadline_incident", "review_deadline_incident"),
            ("integrity_incident", "review_integrity_incident"),
        ):
            for result in ("worker_completed", "worker_finding", "accepted_evidence"):
                with self.subTest(incident=incident, result=result):
                    self.assertEqual(kernel.decide(policy, {incident, result}).action, expected)

    def test_wait_rule_requires_deadline_wakeup(self) -> None:
        decision = kernel.decide(source_policy(), {"live_task"})
        self.assertEqual(decision.action, "wait_for_worker_event")
        self.assertIn("wake_no_later_than_item_deadline", decision.obligations)

    def test_every_mutation_route_probes_pending_suggestions(self) -> None:
        policy = source_policy()
        for fact in (
            "integrity_incident", "deadline_incident", "random_mutation_due",
            "dfs_review_due", "universal_review_due",
        ):
            with self.subTest(fact=fact):
                decision = kernel.decide(policy, {fact, "pending_suggestions"})
                self.assertIn("probe_pending_suggestions", decision.obligations)
                self.assertIn("disposition_relevant_suggestions", decision.obligations)
                self.assertIn("pending_suggestions", decision.reads)

    def test_closure_dispatch_requires_full_route_clock_admission(self) -> None:
        decision = kernel.decide(
            source_policy(), {"closure_ready", "open_gap", "executable_route"}
        )
        self.assertIn("admit_full_downstream_route_to_clock", decision.obligations)
        self.assertIn("start_unique_worker_window", decision.obligations)
        self.assertIn(
            "set_deliverable_deadline_with_problem_margin",
            decision.obligations,
        )
        self.assertIn(
            "include_known_unknown_and_unpredicted_problem_margin",
            decision.obligations,
        )
        self.assertIn(
            "never_copy_one_attempt_runtime_into_whole_item_deadline",
            decision.obligations,
        )

    def test_exploration_dispatch_sizes_the_full_route_clock(self) -> None:
        for facts in (
            {"open_claim", "executable_route"},
            {"ledger_work", "executable_route"},
        ):
            with self.subTest(facts=facts):
                decision = kernel.decide(source_policy(), facts)
                self.assertEqual(decision.action, "dispatch_exploration_worker")
                self.assertIn(
                    "set_deliverable_deadline_with_problem_margin",
                    decision.obligations,
                )
                self.assertIn(
                    "include_known_unknown_and_unpredicted_problem_margin",
                    decision.obligations,
                )
                self.assertIn(
                    "never_copy_one_attempt_runtime_into_whole_item_deadline",
                    decision.obligations,
                )
                self.assertIn(
                    "forfeit_claim_window_when_next_attempt_cannot_fit",
                    decision.obligations,
                )

    def test_acceptance_requires_guarded_dfs_projection(self) -> None:
        decision = kernel.decide(source_policy(), {"accepted_evidence"})
        self.assertIn("guard_and_apply_exact_dfs_completion", decision.obligations)

    def test_deadline_incident_cadence_cannot_authorize_restart(self) -> None:
        decision = kernel.decide(
            source_policy(), {"deadline_incident", "worker_abandoned"}
        )
        self.assertEqual(decision.action, "review_deadline_incident")
        self.assertIn(
            "cadence_is_observation_not_restart_authority",
            decision.obligations,
        )
        self.assertIn(
            "review_evidence_before_proposing_change",
            decision.obligations,
        )
        self.assertIn("deadline_history", decision.reads)

    def test_live_task_prevents_second_dispatch(self) -> None:
        facts = {"live_task", "closure_ready", "open_gap", "executable_route"}
        self.assertEqual(kernel.decide(source_policy(), facts).action, "wait_for_worker_event")

    def test_owner_reply_preempts_blocker_audit(self) -> None:
        decision = kernel.decide(source_policy(), {"owner_reply", "blocked_ledger"})
        self.assertEqual(decision.action, "consume_owner_reply")

    def test_irrelevant_identifiers_do_not_change_decision(self) -> None:
        policy = source_policy()
        expected = kernel.decide(policy, {"live_task"})
        for suffix in range(50):
            observed = kernel.decide(policy, {"live_task", f"task_id:R-{suffix}"})
            self.assertEqual(observed.action, expected.action)
            self.assertEqual(observed.obligations, expected.obligations)

    def test_rule_order_does_not_change_policy_identity_or_decisions(self) -> None:
        policy = source_policy()
        reversed_policy = copy.deepcopy(policy)
        reversed_policy["rules"].reverse()
        self.assertEqual(kernel.policy_digest(policy), kernel.policy_digest(reversed_policy))
        for facts, _ in CASES:
            self.assertEqual(
                kernel.decide(policy, facts).action,
                kernel.decide(reversed_policy, facts).action,
            )

    def test_minimizer_removes_behaviorally_redundant_rule(self) -> None:
        policy = source_policy()
        duplicate = copy.deepcopy(policy["rules"][-1])
        duplicate["id"] = "REDUNDANT"
        duplicate["priority"] = -1
        policy["rules"].append(duplicate)
        minimized, removed = kernel.minimize_policy(
            policy, [(frozenset(facts), expected) for facts, expected in CASES]
        )
        self.assertIn("REDUNDANT", removed)
        for facts, expected in CASES:
            self.assertEqual(kernel.decide(minimized, facts).action, expected)

    def test_contract_corpus_keeps_every_production_rule(self) -> None:
        policy = source_policy()
        minimized, removed = kernel.minimize_policy(
            policy, [(frozenset(facts), expected) for facts, expected in CASES]
        )
        self.assertEqual(removed, ())
        self.assertEqual(len(minimized["rules"]), len(policy["rules"]))

    def test_every_rule_deletion_changes_at_least_one_contract_decision(self) -> None:
        policy = source_policy()
        for removed in policy["rules"]:
            candidate = copy.deepcopy(policy)
            candidate["rules"] = [rule for rule in candidate["rules"] if rule["id"] != removed["id"]]
            differences = [
                facts for facts, _expected in CASES
                if kernel.decide(candidate, facts).action != kernel.decide(policy, facts).action
            ]
            with self.subTest(rule=removed["id"]):
                self.assertTrue(differences)

    def test_all_single_and_pairwise_fact_combinations_decide_deterministically(self) -> None:
        policy = source_policy()
        atoms = sorted({
            atom for rule in policy["rules"]
            for key in ("all", "any", "none") for atom in rule.get(key, [])
        })
        combinations = [frozenset()] + [
            frozenset(items)
            for width in (1, 2)
            for items in itertools.combinations(atoms, width)
        ]
        for facts in combinations:
            with self.subTest(facts=facts):
                first = kernel.decide(policy, facts)
                second = kernel.decide(policy, reversed(sorted(facts)))
                self.assertEqual(first, second)

    def test_trace_rejects_late_acceptance_before_incident_review(self) -> None:
        with self.assertRaisesRegex(kernel.PolicyError, "deadline_open"):
            kernel.validate_trace(source_policy(), [
                {"event": "task_started", "task_id": "M1"},
                {"event": "deadline_expired"},
                {"event": "task_completed", "task_id": "M1"},
                {"event": "claim_accepted"},
            ])

    def test_trace_allows_completion_then_review_then_acceptance(self) -> None:
        kernel.validate_trace(source_policy(), [
            {"event": "task_started", "task_id": "M1"},
            {"event": "deadline_expired"},
            {"event": "task_completed", "task_id": "M1"},
            {"event": "deadline_incident_reviewed"},
            {"event": "claim_accepted"},
        ])

    def test_trace_rejects_mutation_that_ignores_suggestions(self) -> None:
        with self.assertRaisesRegex(kernel.PolicyError, "suggestions_pending"):
            kernel.validate_trace(source_policy(), [
                {"event": "suggestion_added"},
                {"event": "mutation_started"},
                {"event": "mutation_resolved"},
            ])

    def test_trace_accepts_explicit_suggestion_disposition(self) -> None:
        kernel.validate_trace(source_policy(), [
            {"event": "suggestion_added"},
            {"event": "mutation_started"},
            {"event": "suggestions_dispositioned"},
            {"event": "mutation_resolved"},
        ])

    def test_temporal_safety_is_mutable_policy_not_python(self) -> None:
        policy = source_policy()
        policy["trace"]["events"]["claim_accepted"]["forbids"] = []
        kernel.validate_trace(policy, [
            {"event": "deadline_expired"},
            {"event": "claim_accepted"},
        ])

    def test_guard_obligation_floor_is_mutable_contract_data(self) -> None:
        policy = source_policy()
        contracts = kernel.load_contracts(CONTRACTS)
        wait = next(rule for rule in policy["rules"] if rule["id"] == "W1")
        wait["obligations"].remove("wake_no_later_than_item_deadline")
        case = next(case for case in contracts["decision_cases"] if case["name"] == "wait")
        case["required_obligations"] = []
        guarded = kernel.guard_policy_candidate(policy, contracts)
        self.assertNotIn(
            "wake_no_later_than_item_deadline",
            kernel.decide(guarded, {"live_task"}).obligations,
        )

    def test_trace_rejects_reused_or_double_terminal_task(self) -> None:
        for events in (
            [
                {"event": "task_started", "task_id": "M1"},
                {"event": "task_started", "task_id": "M1"},
            ],
            [
                {"event": "task_started", "task_id": "M1"},
                {"event": "task_completed", "task_id": "M1"},
                {"event": "task_abandoned", "task_id": "M1"},
            ],
        ):
            with self.subTest(events=events):
                with self.assertRaises(kernel.PolicyError):
                    kernel.validate_trace(source_policy(), events)

    def test_cli_compile_inspect_and_decide(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "policy.d67"
            compiled = subprocess.run(
                [sys.executable, str(SCRIPT), "compile", "--source", str(SOURCE),
                 "--output", str(output)], text=True, capture_output=True
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            inspected = subprocess.run(
                [sys.executable, str(SCRIPT), "inspect", "--policy", str(output)],
                text=True, capture_output=True
            )
            self.assertEqual(inspected.returncode, 0, inspected.stderr)
            self.assertEqual(json.loads(inspected.stdout)["rules"], len(source_policy()["rules"]))
            decided = subprocess.run(
                [sys.executable, str(SCRIPT), "decide", "--policy", str(output),
                 "--facts", '["deadline_incident","worker_completed"]'],
                text=True, capture_output=True
            )
            self.assertEqual(decided.returncode, 0, decided.stderr)
            self.assertEqual(json.loads(decided.stdout)["action"], "review_deadline_incident")
            decompiled = subprocess.run(
                [sys.executable, str(SCRIPT), "decompile", "--policy", str(output)],
                text=True, capture_output=True,
            )
            self.assertEqual(decompiled.returncode, 0, decompiled.stderr)
            self.assertEqual(json.loads(decompiled.stdout), kernel.validate_policy(source_policy()))

    def test_cli_guard_emits_exact_packaged_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "guarded.d67"
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "guard", "--candidate", str(SOURCE),
                 "--contracts", str(CONTRACTS), "--output", str(output)],
                text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                output.read_bytes(),
                (ROOT / "assets" / "environment" / "phase3-policy.d67").read_bytes(),
            )

    def test_workspace_probe_extracts_machine_facts_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            de67 = workspace / ".de67"
            de67.mkdir()
            (de67 / "work-ledger.md").write_text(
                "## R-1\n- Active gap\n- Next executable route\n", encoding="utf-8"
            )
            (de67 / "mutation-suggestions.md").write_text(
                "## Pending suggestions\n\n- owner item\n", encoding="utf-8"
            )
            (de67 / "DFS.md").write_text("- [ ] 🔴 R-1\n", encoding="utf-8")
            state = workspace / "state.sqlite3"
            connection = sqlite3.connect(state)
            connection.executescript(
                """
                CREATE TABLE tasks (
                    lineage_id TEXT, task_id TEXT, started_at REAL, attempt_terminal_at REAL,
                    attempt_terminal_kind TEXT
                );
                CREATE TABLE claim_clocks (
                    lineage_id TEXT, claim_id TEXT, started_at REAL,
                    deadline_at REAL, phase TEXT
                );
                CREATE TABLE closure_gaps (
                    lineage_id TEXT, claim_id TEXT, closed_at REAL
                );
                INSERT INTO tasks VALUES ('project', 'M1', 1, NULL, NULL);
                INSERT INTO tasks VALUES ('foreign', 'M2', 2, 2, 'failed');
                INSERT INTO claim_clocks VALUES ('project', 'C1', 1, 5, 'closure');
                INSERT INTO claim_clocks VALUES ('foreign', 'C2', 2, 50, 'exploration');
                INSERT INTO closure_gaps VALUES ('project', 'C1', NULL);
                INSERT INTO closure_gaps VALUES ('foreign', 'C2', NULL);
                """
            )
            connection.close()
            before = state.read_bytes()
            facts = kernel.workspace_facts(workspace, state, "project", now=6)
            self.assertEqual(before, state.read_bytes())
            self.assertTrue({
                "live_task", "deadline_expired", "closure_ready", "open_gap",
                "ledger_work", "executable_route", "pending_suggestions", "red_dfs_work",
            } <= facts)
            self.assertNotIn("worker_failed", facts)

    def test_initial_red_ledger_routes_exploration_without_a_claim_clock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            de67 = workspace / ".de67"
            de67.mkdir()
            (de67 / "work-ledger.md").write_text(
                "## R-004\n- Claim status: red and unaccepted.\n"
                "- Next executable route: inspect the production owners.\n",
                encoding="utf-8",
            )
            (de67 / "DFS.md").write_text("- [ ] 🔴 R-004\n", encoding="utf-8")
            state = workspace / "state.sqlite3"
            connection = sqlite3.connect(state)
            connection.executescript(
                """
                CREATE TABLE tasks (
                    lineage_id TEXT, task_id TEXT, started_at REAL,
                    attempt_terminal_at REAL, attempt_terminal_kind TEXT
                );
                CREATE TABLE claim_clocks (
                    lineage_id TEXT, claim_id TEXT, started_at REAL,
                    deadline_at REAL, phase TEXT
                );
                CREATE TABLE closure_gaps (
                    lineage_id TEXT, claim_id TEXT, closed_at REAL
                );
                """
            )
            connection.close()

            facts = kernel.workspace_facts(workspace, state, "project", now=1)

            self.assertNotIn("open_claim", facts)
            self.assertEqual(
                kernel.decide(source_policy(), facts).action,
                "dispatch_exploration_worker",
            )

    def test_persistent_completed_result_is_consumed_then_expiry_preempts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            de67 = workspace / ".de67"
            de67.mkdir()
            (de67 / "work-ledger.md").write_text(
                "## R-004\n- Active gap\n- Next executable route: run proof.\n",
                encoding="utf-8",
            )
            (de67 / "DFS.md").write_text("- [ ] 🔴 R-004\n", encoding="utf-8")
            state = workspace / "state.sqlite3"
            connection = sqlite3.connect(state)
            connection.executescript(
                """
                CREATE TABLE tasks (
                    lineage_id TEXT, task_id TEXT, started_at REAL,
                    attempt_terminal_at REAL, attempt_terminal_kind TEXT,
                    result_received_at REAL
                );
                CREATE TABLE claim_clocks (
                    lineage_id TEXT, claim_id TEXT, started_at REAL,
                    deadline_at REAL, phase TEXT
                );
                CREATE TABLE closure_gaps (
                    lineage_id TEXT, claim_id TEXT, closed_at REAL
                );
                CREATE TABLE claim_deadline_generations (
                    lineage_id TEXT, claim_id TEXT, generation INTEGER
                );
                CREATE TABLE claim_deadline_generation_incidents (
                    lineage_id TEXT, claim_id TEXT, generation INTEGER,
                    reviewed_at REAL
                );
                INSERT INTO tasks VALUES ('project', 'M1', 0, 5, 'completed', NULL);
                INSERT INTO claim_clocks VALUES ('project', 'R-004', 0, 10, 'closure');
                INSERT INTO closure_gaps VALUES ('project', 'R-004', NULL);
                INSERT INTO claim_deadline_generations VALUES ('project', 'R-004', 1);
                """
            )
            connection.commit()

            before_receipt = kernel.workspace_facts(workspace, state, "project", now=6)
            self.assertEqual(
                kernel.decide(source_policy(), before_receipt).action,
                "receive_worker_result",
            )
            connection.execute(
                "UPDATE tasks SET result_received_at = 7 WHERE lineage_id = 'project'"
            )
            connection.commit()
            connection.close()

            after_expiry = kernel.workspace_facts(workspace, state, "project", now=11)
            self.assertNotIn("worker_completed", after_expiry)
            self.assertEqual(
                kernel.decide(source_policy(), after_expiry).action,
                "record_deadline_miss",
            )
            connection = sqlite3.connect(state)
            connection.execute(
                "INSERT INTO claim_deadline_generation_incidents VALUES "
                "('project', 'R-004', 1, 12)"
            )
            connection.commit()
            connection.close()
            after_recording = kernel.workspace_facts(
                workspace, state, "project", now=13
            )
            self.assertNotIn("deadline_expired", after_recording)
            self.assertEqual(
                kernel.decide(source_policy(), after_recording).action,
                "dispatch_closure_worker",
            )
            connection = sqlite3.connect(state)
            connection.execute(
                "UPDATE closure_gaps SET closed_at = 14 WHERE lineage_id = 'project'"
            )
            connection.commit()
            connection.close()
            acceptance_ready = kernel.workspace_facts(
                workspace, state, "project", now=15
            )
            self.assertIn("accepted_evidence", acceptance_ready)
            self.assertEqual(
                kernel.decide(source_policy(), acceptance_ready).action,
                "apply_guarded_dfs_acceptance",
            )

    def test_preserved_baseline_has_no_compiled_kernel_and_remains_recoverable(self) -> None:
        result = subprocess.run(
            [
                "git",
                "cat-file",
                "-e",
                "backup/pre-lab-lab-20260822:de-67-3/scripts/policy_kernel.py",
            ],
            capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
