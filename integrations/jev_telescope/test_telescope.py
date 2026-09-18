import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import telescope as t


def slow_child(connection, body, timeout):
    time.sleep(10)


def response(body, kinds=None, counter=()):
    kinds = kinds or {}
    answers = {}
    for key, question in body["questions"].items():
        chosen = ("yes" if key[:-8] in counter else "no") if key.endswith("_counter") else kinds.get(key, "irrelevant")
        answers[key] = dict(type="choice", choice=chosen, confidence=1,
                            probabilities={option: float(option == chosen) for option in question["criteria"]})
    return dict(model="jev-test", answers=answers, usage=dict(input_tokens=100, output_tokens=10))


class TelescopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "source.py").write_text("def order():\n    pending_order = 'move'\n    return pending_order\n")
        (self.root / "unrelated.py").write_text("# order of paint colors\ncolors = ['blue']\n")
        self.config = t.validate_config(dict(mode="on", paths=["source.py", "unrelated.py"], cache_seconds=0))
        self.pool, self.info = t.gather(self.root, "order", [], self.config, time.monotonic() + 10)
        self.target = next(c["id"] for c in self.pool if c["path"] == "source.py")

    def run_eval(self, call, config=None, pool=None, hypothesis=""):
        return t.evaluate(self.root, "order", hypothesis, self.pool if pool is None else pool,
                          dict(self.info), config or self.config, call=call)

    def test_mixed_pool_selects_exact_source(self):
        packet = self.run_eval(lambda body, timeout: response(body, {self.target: "direct"}))
        self.assertEqual([i["id"] for i in packet["items"]], [self.target])
        item = packet["items"][0]
        self.assertEqual(item["excerpt"], (self.root / item["path"]).read_text())
        self.assertEqual(item["sha256"], t.digest((self.root / item["path"]).read_bytes()))
        self.assertEqual(item["handle"]["lines"], [1, 3])

    def test_all_irrelevant_is_valid_abstention_not_failure(self):
        packet = self.run_eval(lambda body, timeout: response(body))
        self.assertTrue(packet["abstained"])
        self.assertEqual(packet["items"], [])
        self.assertIsNone(packet["fallback"])

    def test_counterevidence_has_independent_selection_and_budget_priority(self):
        other = next(c["id"] for c in self.pool if c["id"] != self.target)
        config = {**self.config, "evidence_bytes": len((self.root / "source.py").read_bytes())}
        packet = self.run_eval(lambda body, timeout: response(body, {other: "direct"}, [self.target]),
                               config, hypothesis="Order was never stored")
        self.assertEqual([i["id"] for i in packet["items"]], [self.target])
        self.assertEqual(packet["items"][0]["category"], "counterevidence")

    def test_malformed_unknown_partial_and_invalid_probabilities_fallback(self):
        def unknown(value): value["answers"]["unknown"] = next(iter(value["answers"].values()))
        def partial(value): value["answers"].pop(self.target)
        def malformed(value): value["answers"][self.target] = None
        def bad_probability(value): value["answers"][self.target]["confidence"] = float("nan")
        def partial_distribution(value): value["answers"][self.target]["probabilities"].pop("direct")
        for mutate in (unknown, partial, malformed, bad_probability, partial_distribution):
            with self.subTest(mutate=mutate.__name__):
                def call(body, timeout):
                    value = response(body)
                    mutate(value)
                    return value
                packet = self.run_eval(call)
                self.assertTrue(packet["fallback"])
                self.assertEqual(len(packet["items"]), 2)
                self.assertFalse(packet["abstained"])

    def test_duplicate_json_and_duplicate_selected_ids_rejected(self):
        with self.assertRaises(t.TelescopeError):
            t.strict_json('{"answers":{},"answers":{}}')
        for selection in ([{"id": self.target, "category": "direct"}] * 2,
                          [{"id": "unknown", "category": "direct"}]):
            with self.assertRaises(t.TelescopeError):
                t.assemble(self.root, self.pool, selection, self.config)

    def test_timeout_provider_failure_and_credentials_fallback(self):
        for error in (TimeoutError(), OSError("secret provider content"), t.TelescopeError("missing_credentials")):
            def call(body, timeout): raise error
            packet = self.run_eval(call)
            self.assertTrue(packet["fallback"])
            self.assertNotIn("secret provider content", json.dumps(packet))
            self.assertEqual(len(packet["items"]), 2)
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(t.TelescopeError, "missing_credentials"):
                t.provider({}, 1)

    def test_budget_exhaustion_does_not_call_provider(self):
        def forbidden(*args): self.fail("provider called")
        for override in ({"max_calls": 0}, {"input_bytes": 1}):
            packet = self.run_eval(forbidden, {**self.config, **override})
            self.assertIn("budget_exhausted", packet["fallback"])
            self.assertEqual(packet["provider_calls"], 0)
        packet = t.evaluate(self.root, "order", "", self.pool, self.info, self.config,
                            call=forbidden, started=time.monotonic() - 100)
        self.assertEqual(packet["fallback"], "provider_budget_exhausted")

    def test_source_edit_or_deletion_never_uses_old_lines(self):
        for delete in (False, True):
            with self.subTest(delete=delete):
                def call(body, timeout):
                    if delete: (self.root / "source.py").unlink()
                    else: (self.root / "source.py").write_text("changed uncommitted source")
                    return response(body, {self.target: "direct"})
                packet = self.run_eval(call)
                self.assertEqual(packet["items"], [])
                self.assertEqual(packet["stale_ids"], [self.target])
                self.assertFalse(packet["abstained"])

    def test_overlapping_excerpts_are_not_repeated(self):
        original = next(c for c in self.pool if c["id"] == self.target)
        overlapping = {**original, "id": "overlap", "start": 2, "excerpt": "".join(original["excerpt"].splitlines(keepends=True)[1:])}
        packet = t.assemble(self.root, [original, overlapping],
                            [{"id": c["id"], "category": "direct"} for c in [original, overlapping]], self.config)
        self.assertEqual(len(packet["items"]), 1)
        self.assertEqual(packet["omitted_ids"], ["overlap"])

    def test_cache_reuse_and_query_hypothesis_source_model_invalidation(self):
        config = {**self.config, "cache_seconds": 3600}
        calls = []
        def call(body, timeout):
            calls.append(body)
            return response(body, {self.target: "direct"})
        self.run_eval(call, config)
        cached = self.run_eval(call, config)
        self.assertTrue(cached["cache_hit"])
        self.assertEqual(cached["provider_usage"], {})
        self.run_eval(call, config, hypothesis="not stored")
        self.run_eval(call, {**config, "model": "different-model"})
        t.evaluate(self.root, "different query", "", self.pool, self.info, config, call=call)
        (self.root / "source.py").write_text("# order changed\n")
        t.search(self.root, "order", config=config, call=call)
        self.assertEqual(len(calls), 5)

    def test_off_and_shadow_preserve_identical_baseline_items(self):
        def forbidden(*args): self.fail("off called provider")
        off = self.run_eval(forbidden, {**self.config, "mode": "off"})
        shadow = self.run_eval(lambda body, timeout: response(body), {**self.config, "mode": "shadow"})
        self.assertEqual(off["items"], shadow["items"])
        self.assertFalse(shadow["abstained"])
        telemetry = list((self.root / ".de67/state/jev-telescope/comparisons").glob("*.json"))
        self.assertEqual(len(telemetry), 1)
        self.assertEqual(json.loads(telemetry[0].read_text())["selected"], [])
        self.assertNotIn("pending_order", telemetry[0].read_text())

    def test_secret_symlink_and_custom_exclusion(self):
        (self.root / ".env").write_text("order=secret")
        (self.root / "leak.py").write_text('token = "abcdefghijklmnopqrstuvwx"\n# order\n')
        (self.root / "link.py").symlink_to(self.root / "source.py")
        config = {**self.config, "paths": ["."], "excludes": ["unrelated.py"]}
        pool, info = t.gather(self.root, "order", [], config, time.monotonic() + 10)
        self.assertEqual([c["path"] for c in pool], ["source.py"])
        self.assertGreaterEqual(info["exclusions"], 3)

    def test_candidate_and_evidence_limits_visible(self):
        config = {**self.config, "max_candidates": 1, "evidence_bytes": 1, "mode": "off"}
        result = t.search(self.root, "order", config=config)
        self.assertTrue(result["retrieval"]["truncated"])
        self.assertEqual(result["candidates_considered"], 1)
        self.assertEqual(result["items"], [])
        self.assertEqual(len(result["omitted_ids"]), 1)

    def test_historical_index_uses_original_receipt_and_detects_changes(self):
        state = self.root / ".de67/state"
        state.mkdir(parents=True)
        source = state / "deadlines.sqlite3"
        evidence = json.dumps({"receipt_id": "receipt1", "receipt": {"status": "inconclusive", "finding": "order stored"}})
        with sqlite3.connect(source) as db:
            db.execute("CREATE TABLE worker_checkpoints(lineage_id, task_id, sequence, kind, evidence)")
            db.execute("INSERT INTO worker_checkpoints VALUES ('p','task',1,'result-receipt-v1',?)", (evidence,))
        with sqlite3.connect(state / "work-context.sqlite3") as db:
            db.execute("CREATE TABLE receipts(source,lineage,task,sequence,receipt_id,recorded_at,search_text)")
            db.execute("INSERT INTO receipts VALUES (?,'p','task',1,'receipt1',100,'order')", (str(source),))
        config = {**self.config, "receipt_index": True, "paths": [], "mode": "off"}
        pool, info = t.gather(self.root, "order", [], config, time.monotonic() + 10)
        packet = t.evaluate(self.root, "order", "", pool, info, config)
        self.assertEqual(packet["items"][0]["excerpt"], evidence)
        self.assertEqual(packet["items"][0]["recorded_at"], 100)
        with sqlite3.connect(source) as db:
            db.execute("UPDATE worker_checkpoints SET evidence='changed'")
        packet = t.evaluate(self.root, "order", "", pool, info, config)
        self.assertEqual(packet["items"], [])
        self.assertEqual(len(packet["stale_ids"]), 1)

    def test_optional_discovery_off_is_unchanged(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "de-67-3/scripts"))
        from instruction_context import common_guidance, FALLBACK_GUIDANCE
        self.assertEqual(common_guidance(self.root), FALLBACK_GUIDANCE)
        state = self.root / ".de67/state"
        state.mkdir(parents=True)
        config = state / "workspace.json"
        config.write_text(json.dumps({"jev_telescope": {"mode": "off"}}))
        self.assertEqual(common_guidance(self.root), FALLBACK_GUIDANCE)
        config.write_text(json.dumps({"jev_telescope": {"mode": "shadow"}}))
        self.assertIn("--workspace", common_guidance(self.root))
        self.assertIn("not a per-turn step", common_guidance(self.root))

    def test_provider_wall_deadline_terminates_child(self):
        started = time.monotonic()
        with patch.object(t, "_provider_child", slow_child):
            with self.assertRaises(TimeoutError):
                t.bounded_provider({}, .05)
        self.assertLess(time.monotonic() - started, 3)

    def test_queries_with_secrets_never_transmit(self):
        def forbidden(*args): self.fail("secret transmitted")
        packet = t.evaluate(self.root, "api_key=abcdefghijklmnopqrstuvwxyz", "", self.pool,
                            self.info, self.config, call=forbidden)
        self.assertEqual(packet["fallback"], "secret_pattern_in_query")
        self.assertEqual(packet["provider_calls"], 0)

    def test_evaluation_uses_same_pool_and_budget_without_network(self):
        import evaluate
        cases = self.root / "cases.json"
        cases.write_text(json.dumps({"cases": [dict(id="order", query="order", hypothesis="",
                         paths=["source.py", "unrelated.py"], terms=["order"],
                         important_anchors=["pending_order"], counter_anchors=[])]}))
        def call(body, timeout):
            kinds = {c["id"]: "direct" for c in body["state"]["candidates"] if "pending_order" in c["excerpt"]}
            return response(body, kinds)
        report = evaluate.run(self.root, live=True, cases_path=cases, call=call)
        row = report["cases"][0]
        self.assertEqual(row["missing_label_anchors"], [])
        self.assertEqual(row["baseline"]["coverage"], row["jev"]["coverage"])
        self.assertEqual(row["jev"]["unlabeled_return_count"], 0)

    def test_http_adapter_posts_documented_schema_and_rejects_duplicate_json(self):
        body = t.request_body("order", "", self.pool, self.config)
        raw = t.encoded(response(body))
        class Reply:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit): return raw
        class Opener:
            def open(inner, request, timeout):
                self.assertEqual(request.full_url, t.ENDPOINT)
                self.assertEqual(request.get_method(), "POST")
                self.assertEqual(json.loads(request.data), body)
                return Reply()
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "fake-test-key"}), patch.object(t.urllib.request, "build_opener", return_value=Opener()):
            self.assertEqual(t.provider(body, 1)["model"], "jev-test")
            raw = b'{"answers": {}, "answers": {}}'
            with self.assertRaises(t.TelescopeError):
                t.provider(body, 1)


if __name__ == "__main__":
    unittest.main()
