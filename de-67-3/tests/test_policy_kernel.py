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
from deadline_harness import DeadlineHarness  # noqa: E402


def source_policy() -> dict:
    return json.loads(SOURCE.read_text(encoding="utf-8"))


CASES = (
    ({"integrity_incident", "live_task"}, "wait_for_mutation_quiescence"),
    ({"integrity_incident"}, "retire_for_mutation_review"),
    ({"deadline_incident", "worker_completed"}, "retire_for_mutation_review"),
    ({"restart_requested", "open_claim"}, "acknowledge_restart"),
    ({"random_mutation_due"}, "retire_for_mutation_review"),
    ({"random_mutation_due", "live_task"}, "wait_for_mutation_quiescence"),
    ({"dfs_review_due", "pending_suggestions"}, "retire_for_mutation_review"),
    ({"universal_review_due"}, "retire_for_mutation_review"),
    ({"accepted_evidence"}, "review_dfs_acceptance"),
    ({"worker_completed"}, "receive_worker_result"),
    ({"worker_finding"}, "receive_worker_result"),
    ({"worker_abandoned"}, "receive_worker_result"),
    ({"owner_reply", "blocked_ledger"}, "consume_owner_reply"),
    ({"blocked_ledger"}, "audit_blocker"),
    ({"unbound_task"}, "spawn_worker"),
    ({"live_task"}, "wait_for_worker_event"),
    ({"closure_ready", "open_gap", "executable_route"}, "dispatch_closure_worker"),
    ({"open_claim", "executable_route"}, "dispatch_exploration_worker"),
    ({"ledger_work", "executable_route"}, "dispatch_exploration_worker"),
    ({"red_dfs_work"}, "refill_ledger"),
    ({"dfs_complete"}, "stop"),
    (set(), "inspect_state"),
)


class PolicyKernelTests(unittest.TestCase):
    def test_worker_outcome_contract_keeps_bootstrap_and_validation_in_one_outcome(self) -> None:
        contract = kernel.worker_outcome_contract()

        self.assertIn("repository-owned implementation", contract)
        self.assertIn("inside this task", contract)
        self.assertIn("non-credit bootstrap", contract)
        self.assertIn("validate the fresh output independently", contract)
        self.assertIn("do not query the unchanged prerequisite again", contract)
        self.assertIn("A disproved strategy is progress, not a task exit", contract)
        self.assertIn("contradicted assigned outcome", contract)
        self.assertIn("authorized route you have genuinely exhausted", contract)
        self.assertNotIn("formal finding only for a disproved strategy", contract)

    def test_worker_helper_contract_keeps_one_owner_and_native_freedom(self) -> None:
        contract = kernel.worker_helper_contract()

        self.assertIn("Terra worker", contract)
        self.assertIn("consider an optional Luna helper", contract)
        self.assertIn("bounded work can return independently", contract)
        self.assertIn("isolated live playtest witness", contract)
        self.assertIn("focused test run", contract)
        self.assertIn("compact charter and isolated run context", contract)
        self.assertIn("smallest journal-cited witness", contract)
        self.assertIn("own any repair", contract)
        self.assertIn('fork_turns="none"', contract)
        self.assertIn("as many as the runtime permits", contract)
        self.assertIn("work or wait while they run", contract)
        self.assertIn("remain responsible for the whole outcome", contract)
        self.assertIn("do not own deadline tasks", contract)
        self.assertIn("avoid overlapping source edits", contract)
        self.assertIn("shared mutable runtime state", contract)
        self.assertIn("explicit exclusive ownership", contract)
        self.assertIn("If you are Luna, do not delegate further", contract)
        self.assertNotIn("must delegate", contract)

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
        deadline["obligations"].remove("perform_no_mutation")
        with self.assertRaisesRegex(kernel.PolicyError, "required obligations"):
            kernel.guard_policy_candidate(policy, kernel.load_contracts(CONTRACTS))

    def test_machine_candidate_guard_rejects_deadline_coordinator_retirement(self) -> None:
        policy = source_policy()
        deadline = next(rule for rule in policy["rules"] if rule["id"] == "D1")
        deadline["obligations"].remove("exit_to_external_supervisor")
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
                    "size_one_generous_claim_deadline_for_full_route"
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
        policy["rules"][1].pop("all")
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
            "none": ["live_task"], "action": "retire_for_mutation_review", "reads": ["extra"],
            "obligations": ["extra_check"],
        })
        decision = kernel.decide(policy, {"integrity_incident"})
        self.assertIn("extra", decision.reads)
        self.assertIn("extra_check", decision.obligations)

    def test_incidents_preempt_late_worker_results_and_acceptance(self) -> None:
        policy = source_policy()
        for incident, expected in (
            ("deadline_incident", "retire_for_mutation_review"),
            ("integrity_incident", "retire_for_mutation_review"),
        ):
            for result in ("worker_completed", "worker_finding", "accepted_evidence"):
                with self.subTest(incident=incident, result=result):
                    self.assertEqual(kernel.decide(policy, {incident, result}).action, expected)

    def test_wait_rule_requires_deadline_wakeup(self) -> None:
        decision = kernel.decide(source_policy(), {"live_task"})
        self.assertEqual(decision.action, "wait_for_worker_event")
        self.assertIn("wake_no_later_than_item_deadline", decision.obligations)

    def test_fact_only_unbound_decision_does_not_require_workspace_injection(self) -> None:
        result = subprocess.run(
            [
                sys.executable, str(SCRIPT), "decide", "--policy",
                str(ROOT / "assets/environment/phase3-policy.d67"),
                "--facts", '["unbound_task"]',
            ],
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["action"], "spawn_worker")
        self.assertNotIn("worker_spawns", payload)

    def test_every_worker_result_requires_a_convergence_disposition(self) -> None:
        for fact in ("worker_completed", "worker_finding", "worker_abandoned"):
            with self.subTest(fact=fact):
                decision = kernel.decide(source_policy(), {fact})
                self.assertEqual(decision.action, "receive_worker_result")
                self.assertIn("evaluate_convergence_after_every_worker", decision.obligations)
                self.assertIn(
                    "transition_to_named_independently_provable_closure_gaps_when_finite",
                    decision.obligations,
                )
                self.assertIn(
                    "record_specific_uncertainty_before_more_exploration",
                    decision.obligations,
                )

    def test_every_mutation_route_retires_without_mutating(self) -> None:
        policy = source_policy()
        for fact in (
            "integrity_incident", "deadline_incident", "random_mutation_due",
            "dfs_review_due", "universal_review_due",
        ):
            with self.subTest(fact=fact):
                decision = kernel.decide(policy, {fact, "pending_suggestions"})
                self.assertEqual(decision.action, "retire_for_mutation_review")
                self.assertIn("perform_no_mutation", decision.obligations)
                self.assertIn("exit_to_external_supervisor", decision.obligations)
                self.assertNotIn("pending_suggestions", decision.reads)

    def test_closure_dispatch_requires_full_route_clock_admission(self) -> None:
        decision = kernel.decide(
            source_policy(), {"closure_ready", "open_gap", "executable_route"}
        )
        self.assertIn("admit_full_downstream_route_to_clock", decision.obligations)
        self.assertIn("start_unique_worker_window", decision.obligations)
        self.assertIn(
            "size_one_generous_claim_deadline_for_full_route",
            decision.obligations,
        )
        self.assertIn("delegate_executable_work_to_roster_worker", decision.obligations)
        self.assertIn("include_worker_lifecycle_and_uncertainty_margin", decision.obligations)
        self.assertIn("delegate_evidence_sized_worker_retrieval", decision.obligations)

    def test_exploration_dispatch_sizes_the_full_route_clock(self) -> None:
        for facts in (
            {"open_claim", "executable_route"},
            {"ledger_work", "executable_route"},
        ):
            with self.subTest(facts=facts):
                decision = kernel.decide(source_policy(), facts)
                self.assertEqual(decision.action, "dispatch_exploration_worker")
                self.assertIn(
                    "size_one_generous_claim_deadline_for_full_route",
                    decision.obligations,
                )
                self.assertIn(
                    "delegate_executable_work_to_roster_worker",
                    decision.obligations,
                )
                self.assertIn(
                    "include_worker_lifecycle_and_uncertainty_margin",
                    decision.obligations,
                )
                self.assertIn(
                    "delegate_evidence_sized_worker_retrieval",
                    decision.obligations,
                )

    def test_acceptance_requires_guarded_dfs_projection(self) -> None:
        decision = kernel.decide(source_policy(), {"accepted_evidence"})
        self.assertIn("guard_and_apply_exact_dfs_completion", decision.obligations)

    def test_deadline_incident_retires_to_external_reviewer(self) -> None:
        decision = kernel.decide(
            source_policy(), {"deadline_incident", "worker_abandoned"}
        )
        self.assertEqual(decision.action, "retire_for_mutation_review")
        self.assertIn("exit_to_external_supervisor", decision.obligations)

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
        case = next(
            case for case in contracts["decision_cases"]
            if case["name"] == "wait"
        )
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
            self.assertEqual(json.loads(decided.stdout)["action"], "retire_for_mutation_review")
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
                CREATE TABLE worker_claims (
                    lineage_id TEXT, task_id TEXT, released_at REAL
                );
                INSERT INTO tasks VALUES ('project', 'M1', 1, NULL, NULL);
                INSERT INTO tasks VALUES ('foreign', 'M2', 2, 2, 'failed');
                INSERT INTO worker_claims VALUES ('project', 'M1', NULL);
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

    def test_workspace_probe_does_not_turn_deferred_suggestion_into_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            de67 = workspace / ".de67"
            de67.mkdir()
            (de67 / "work-ledger.md").write_text("", encoding="utf-8")
            (de67 / "DFS.md").write_text("- [ ] 🔴 R-1\n", encoding="utf-8")
            suggestions = de67 / "mutation-suggestions.md"
            suggestions.write_text(
                "## Pending suggestions\n\n- [defer]: review this later\n",
                encoding="utf-8",
            )
            state = workspace / "state.sqlite3"
            connection = sqlite3.connect(state)
            connection.execute(
                "CREATE TABLE tasks (lineage_id TEXT, task_id TEXT, "
                "started_at REAL, attempt_terminal_at REAL, "
                "attempt_terminal_kind TEXT)"
            )
            connection.commit()
            connection.close()

            facts = kernel.workspace_facts(workspace, state, "project", now=1)
            self.assertNotIn("pending_suggestions", facts)
            self.assertNotEqual(
                kernel.decide(source_policy(), facts).action,
                "retire_for_mutation_review",
            )

            suggestions.write_text(
                "## Pending suggestions\n\n- [trigger]: review this now\n",
                encoding="utf-8",
            )
            facts = kernel.workspace_facts(workspace, state, "project", now=1)
            self.assertIn("pending_suggestions", facts)

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

    def test_normalized_restart_recovers_named_closure_gap_without_live_clock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            de67 = workspace / ".de67"
            de67.mkdir()
            (de67 / "work-ledger.md").write_text(
                "## Current delivery frontier\n\n"
                "- Active work: `R-008-natural-bandit` needs observation.\n"
                "- Proof boundary: record the natural return boundary.\n\n"
                "## Other work\n\n"
                "- Active work: `R-014-other-gap` is unrelated.\n",
                encoding="utf-8",
            )
            (de67 / "DFS.md").write_text("- [ ] 🔴 R-008\n", encoding="utf-8")
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
                CREATE TABLE claim_deadline_generations (
                    lineage_id TEXT, claim_id TEXT, generation INTEGER,
                    started_at REAL, deadline_at REAL, retired_at REAL
                );
                CREATE TABLE closure_gaps (
                    lineage_id TEXT, claim_id TEXT, gap_id TEXT, closed_at REAL
                );
                INSERT INTO claim_clocks VALUES ('project', 'R-008', 1, 100, 'closure');
                INSERT INTO claim_deadline_generations
                    VALUES ('project', 'R-008', 1, 1, 100, 50);
                INSERT INTO closure_gaps
                    VALUES ('project', 'R-008', 'R-008-natural-bandit', NULL);
                INSERT INTO closure_gaps
                    VALUES ('project', 'R-014', 'R-014-other-gap', NULL);
                """
            )
            connection.close()

            facts = kernel.workspace_facts(workspace, state, "project", now=60)

            self.assertNotIn("open_claim", facts)
            self.assertIn("closure_ready", facts)
            self.assertIn("open_gap", facts)
            self.assertIn("executable_route", facts)
            self.assertEqual(
                kernel.decide(source_policy(), facts).action,
                "dispatch_closure_worker",
            )

    def test_new_live_handoff_supersedes_the_previous_terminal_result(self) -> None:
        """Replay the R-008 loop: an old finding must not mask a new live worker."""
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            de67 = workspace / ".de67"
            de67.mkdir()
            (de67 / "work-ledger.md").write_text(
                "## R-008\n- Active gap\n- Next executable route\n", encoding="utf-8"
            )
            (de67 / "DFS.md").write_text("- [ ] 🔴 R-008\n", encoding="utf-8")
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
                CREATE TABLE worker_claims (
                    lineage_id TEXT, task_id TEXT, released_at REAL
                );
                INSERT INTO tasks VALUES ('project', 'R-008-closure-002', 10, 20, 'finding');
                INSERT INTO tasks VALUES ('project', 'R-008-closure-003', 30, NULL, NULL);
                INSERT INTO worker_claims VALUES ('project', 'R-008-closure-003', NULL);
                INSERT INTO claim_clocks VALUES ('project', 'R-008', 1, 1000, 'closure');
                INSERT INTO closure_gaps VALUES ('project', 'R-008', NULL);
                """
            )
            connection.close()

            facts = kernel.workspace_facts(workspace, state, "project", now=40)

            self.assertIn("live_task", facts)
            self.assertNotIn("worker_finding", facts)
            self.assertEqual(
                kernel.decide(source_policy(), facts).action,
                "wait_for_worker_event",
            )

    def test_bare_task_is_unbound_until_a_worker_claim_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            state = workspace / "state.sqlite3"
            connection = sqlite3.connect(state)
            connection.executescript(
                """
                CREATE TABLE tasks (
                    lineage_id TEXT, task_id TEXT, started_at REAL,
                    attempt_terminal_at REAL, attempt_terminal_kind TEXT
                );
                CREATE TABLE worker_claims (
                    lineage_id TEXT, task_id TEXT, released_at REAL
                );
                INSERT INTO tasks VALUES ('project', 'route-a', 1, NULL, NULL);
                """
            )
            connection.close()

            facts = kernel.workspace_facts(workspace, state, "project", now=2)

            self.assertIn("unbound_task", facts)
            self.assertNotIn("live_task", facts)


    def test_opened_tasks_inject_exact_parallel_spawn_calls_before_wait(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            state = workspace / "state.sqlite3"
            with DeadlineHarness(state) as harness:
                harness.start_task("project", "explore", "R-008", 100, now=0)
                harness.complete_task("project", "explore", "exploration proof", now=1)
                harness.transition_claim_to_closure(
                    "project", "R-008", "explore", "Natural routes remain.",
                    "Use independent production evidence.",
                    gaps=[
                        ("G-BANDIT", "Observe the actual bandit return boundary.",
                         "Add the owned scenario and portable build route, then capture fresh "
                         "renderer transcripts from their output."),
                        ("G-CANNIBAL", "Observe the actual cannibal contact boundary.",
                         "Trace native contact inputs without manufacturing lifecycle state."),
                    ],
                    now=2,
                )
                harness.start_task(
                    "project", "R-008-closure-119", "R-008", 100,
                    phase="closure", gap_id="G-BANDIT", now=3,
                )
                harness.start_task(
                    "project", "R-008-closure-120", "R-008", 100,
                    phase="closure", gap_id="G-CANNIBAL", now=4,
                )

            facts = kernel.workspace_facts(workspace, state, "project", now=5)
            decision = kernel.decide(source_policy(), facts)
            calls = kernel.unbound_worker_spawns(workspace, state, "project")

            self.assertEqual(decision.action, "spawn_worker")
            self.assertEqual([call["task_id"] for call in calls], [
                "R-008-closure-119", "R-008-closure-120",
            ])
            self.assertEqual(
                calls[0]["task_name"],
                "task_522d3030382d636c6f737572652d313139",
            )
            arguments = calls[0]["example_call"]["arguments"]
            self.assertEqual(arguments["fork_turns"], "none")
            self.assertEqual(arguments["model"], "gpt-5.6-terra")
            packet = Path(calls[0]["dispatch_packet"]["path"])
            packet_text = packet.read_text(encoding="utf-8")
            self.assertIn("Read your complete task brief", arguments["message"])
            self.assertIn(str(packet), arguments["message"])
            self.assertIn(calls[0]["dispatch_packet"]["sha256"], arguments["message"])
            self.assertNotIn("DE67", arguments["message"])
            self.assertNotIn("DE67", packet_text)
            self.assertNotIn("Observe the actual bandit return boundary", arguments["message"])
            self.assertIn("Observe the actual bandit return boundary", packet_text)
            self.assertIn("Add the owned scenario and portable build route", packet_text)
            self.assertIn("Keep repository-owned implementation", packet_text)
            self.assertIn("non-credit bootstrap", packet_text)
            self.assertIn("validate the fresh output independently", packet_text)
            self.assertIn("A disproved strategy is progress, not a task exit", packet_text)
            self.assertIn("contradicted assigned outcome", packet_text)
            self.assertNotIn("formal finding only for a disproved strategy", arguments["message"])
            self.assertNotIn(
                "Return completion evidence, a formal finding, or abandonment",
                arguments["message"],
            )
            self.assertIn("do not mutate coordinator deadline state", packet_text)
            self.assertIn("consider an optional Luna helper", packet_text)
            self.assertIn("bounded work can return independently", packet_text)
            self.assertIn("compact charter and isolated run context", packet_text)
            self.assertIn("smallest journal-cited witness", packet_text)
            self.assertIn("as many as the runtime permits", packet_text)
            self.assertIn("must collect or stop every helper", packet_text)
            self.assertIn("avoid overlapping source edits", packet_text)
            self.assertNotIn("must delegate", packet_text)
            self.assertIn("Announcing an assignment is not delegation", calls[0]["instruction"])
            self.assertIn("wait_agent", calls[0]["instruction"])
            self.assertNotEqual(calls[0]["task_name"], calls[1]["task_name"])
            result = subprocess.run(
                [
                    sys.executable, str(SCRIPT), "decide", "--policy",
                    str(ROOT / "assets/environment/phase3-policy.d67"),
                    "--workspace", str(workspace), "--state", str(state),
                    "--lineage", "project", "--now", "5",
                ],
                text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            injected = json.loads(result.stdout)
            self.assertEqual(injected["action"], "spawn_worker")
            self.assertEqual(len(injected["worker_spawns"]), 2)
            self.assertIn("one distinct worker", injected["parallel_dispatch"])
            self.assertEqual(
                injected["coordinator_next_action"],
                "Spawn every listed worker, then call wait_agent for the spawned worker ids. Do not finish the coordinator turn while a worker result is outstanding.",
            )
            with DeadlineHarness(state) as harness:
                harness.claim_worker(
                    "project", "R-008-closure-119", "worker-one",
                    "coordinator-one", "supervisor-one", now=6,
                )
            mixed_facts = kernel.workspace_facts(workspace, state, "project", now=7)
            mixed_calls = kernel.unbound_worker_spawns(workspace, state, "project")
            self.assertIn("live_task", mixed_facts)
            self.assertIn("unbound_task", mixed_facts)
            self.assertEqual(kernel.decide(source_policy(), mixed_facts).action, "spawn_worker")
            self.assertEqual([call["task_id"] for call in mixed_calls], [
                "R-008-closure-120",
            ])

    def test_opened_exploration_task_injects_matching_ledger_and_dfs_route(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            de67 = workspace / ".de67"
            de67.mkdir()
            (de67 / "work-ledger.md").write_text(
                "# Work ledger\n\n- [ ] R-NEW — Repair the native launch boundary and "
                "prove one fresh gameplay frame.\n\n- [ ] R-OTHER — Unrelated work.\n",
                encoding="utf-8",
            )
            (de67 / "DFS.md").write_text(
                "<!-- DE67:DFS-SLICE:BEGIN id=R-NEW-S001 claim=R-NEW -->\n"
                "- [ ] 🔴 R-NEW — Native launch must reach gameplay without injected state.\n"
                "<!-- DE67:DFS-SLICE:END id=R-NEW-S001 claim=R-NEW -->\n",
                encoding="utf-8",
            )
            state = workspace / "state.sqlite3"
            with DeadlineHarness(state) as harness:
                harness.start_task("project", "R-NEW-exploration-001", "R-NEW", 100, now=1)

            calls = kernel.unbound_worker_spawns(workspace, state, "project")

            self.assertEqual(len(calls), 1)
            message = calls[0]["example_call"]["arguments"]["message"]
            packet = Path(calls[0]["dispatch_packet"]["path"])
            packet_text = packet.read_text(encoding="utf-8")
            self.assertNotIn("Repair the native launch boundary", message)
            self.assertIn("Repair the native launch boundary", packet_text)
            self.assertIn("Native launch must reach gameplay", packet_text)
            self.assertNotIn("Unrelated work", packet_text)

    def test_large_worker_brief_is_not_echoed_to_coordinator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            de67 = workspace / ".de67"
            de67.mkdir()
            large_route = "worker-only-evidence " * 4000
            (de67 / "work-ledger.md").write_text(
                f"- [ ] R-LARGE — {large_route}\n", encoding="utf-8"
            )
            (de67 / "DFS.md").write_text(
                "<!-- DE67:DFS-SLICE:BEGIN id=R-LARGE-S001 claim=R-LARGE -->\n"
                "- [ ] 🔴 R-LARGE — Prove the large route.\n"
                "<!-- DE67:DFS-SLICE:END id=R-LARGE-S001 claim=R-LARGE -->\n",
                encoding="utf-8",
            )
            state = workspace / "state.sqlite3"
            with DeadlineHarness(state) as harness:
                harness.start_task(
                    "project", "R-LARGE-exploration-001", "R-LARGE", 100, now=1
                )

            call = kernel.unbound_worker_spawns(workspace, state, "project")[0]
            coordinator_json = json.dumps(call, sort_keys=True)
            packet = Path(call["dispatch_packet"]["path"])

            self.assertLess(len(coordinator_json), 2000)
            self.assertNotIn("worker-only-evidence", coordinator_json)
            self.assertIn("worker-only-evidence", packet.read_text(encoding="utf-8"))

    def test_worker_packet_keeps_current_route_and_only_latest_history_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            de67 = workspace / ".de67"
            de67.mkdir()
            (de67 / "work-ledger.md").write_text(
                "- [ ] R-HISTORY — Finish the current product outcome.\n"
                "  - DFS slices: `R-HISTORY-S001`\n"
                "  - Known footing: The reusable foundation is already proved.\n"
                "  - Current progress: The implementation compiles.\n"
                "  - Current evidence: Focused test A passes.\n"
                "  - Current uncertainty: The live boundary remains unproved.\n"
                "  - Attempt 001: obsolete-history-one must not reach the worker.\n"
                "  - Attempt 002: obsolete-history-two must not reach the worker.\n"
                "  - Waiting work: Keep this newest no-replay lesson.\n"
                "  - Subtasks:\n"
                "    - [done] build :: Compile the implementation.\n"
                "    - [open] witness :: Prove the live boundary.\n",
                encoding="utf-8",
            )
            (de67 / "DFS.md").write_text(
                "<!-- DE67:DFS-SLICE:BEGIN id=R-HISTORY-S001 claim=R-HISTORY -->\n"
                "Prove the relevant mechanism and live boundary.\n"
                "<!-- DE67:DFS-SLICE:END -->\n",
                encoding="utf-8",
            )
            state = workspace / "state.sqlite3"
            with DeadlineHarness(state) as harness:
                harness.start_task(
                    "project", "R-HISTORY-exploration-001", "R-HISTORY", 100, now=1
                )

            call = kernel.unbound_worker_spawns(workspace, state, "project")[0]
            packet_text = Path(call["dispatch_packet"]["path"]).read_text(encoding="utf-8")

            self.assertIn("Finish the current product outcome", packet_text)
            self.assertIn("Known footing", packet_text)
            self.assertIn("Current progress", packet_text)
            self.assertIn("Current evidence", packet_text)
            self.assertIn("Current uncertainty", packet_text)
            self.assertIn("Keep this newest no-replay lesson", packet_text)
            self.assertIn("Prove the live boundary", packet_text)
            self.assertNotIn("obsolete-history-one", packet_text)
            self.assertNotIn("obsolete-history-two", packet_text)

    def test_exploration_route_does_not_match_longer_claim_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            de67 = workspace / ".de67"
            de67.mkdir()
            (de67 / "work-ledger.md").write_text(
                "- [ ] R-10 — Wrong longer-prefix route.\n\n"
                "- [ ] R-1 — Exact short route.\n",
                encoding="utf-8",
            )
            (de67 / "DFS.md").write_text(
                "<!-- DE67:DFS-SLICE:BEGIN id=R-10-S001 claim=R-10 -->\n"
                "- [ ] 🔴 R-10 — Wrong longer-prefix slice.\n"
                "<!-- DE67:DFS-SLICE:END id=R-10-S001 claim=R-10 -->\n"
                "<!-- DE67:DFS-SLICE:BEGIN id=R-1-S001 claim=R-1 -->\n"
                "- [ ] 🔴 R-1 — Exact short slice.\n"
                "<!-- DE67:DFS-SLICE:END id=R-1-S001 claim=R-1 -->\n",
                encoding="utf-8",
            )

            ledger, dfs = kernel._exploration_route(
                workspace, "R-1", "R-1-exploration-001"
            )

            self.assertIn("Exact short route", ledger)
            self.assertNotIn("Wrong longer-prefix route", ledger)
            self.assertIn("Exact short slice", dfs)
            self.assertNotIn("Wrong longer-prefix slice", dfs)

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
