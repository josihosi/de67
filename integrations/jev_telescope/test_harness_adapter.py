import json
import os
from pathlib import Path
import tempfile
import unittest

import harness_adapter as h
import telescope as t
from test_telescope import response


class HarnessAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.log = self.root / "run.jsonl"
        self.raw = b'{"event":"move_rejected","request_id":"r1","reason":"activity_pending"}\n'
        self.log.write_bytes(self.raw)
        source = dict(path=str(self.log), offset=0, length=len(self.raw), sha256=t.digest(self.raw))
        self.row = dict(event_id="e1", run_id="run1", request_id="r1", event="move_rejected", source=source,
                        payload=json.loads(self.raw), wall_time={"unix_seconds":123})
        self.snapshot = self.save([self.row])
        self.config = dict(mode="on", paths=["run.jsonl", ".userdata/openclaw_harness/evidence-display"], cache_seconds=0)

    def save(self, rows):
        raw = t.encoded({"rows":rows})
        sha = t.digest(raw)
        path = self.root / ".userdata/openclaw_harness/evidence-display" / (sha + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return sha

    def save_rows_with_source(self, values):
        lines = [json.dumps(value, separators=(",", ":")).encode() + b"\n" for value in values]
        self.log.write_bytes(b"".join(lines))
        rows, offset = [], 0
        for index, (value, raw) in enumerate(zip(values, lines)):
            source = {"path": str(self.log), "offset": offset, "length": len(raw), "sha256": t.digest(raw)}
            rows.append({"event_id": value.get("event_id", "row-" + str(index)),
                         "run_id": value.get("run_id", "run1"),
                         "process_instance": value.get("process_instance", "proc1"),
                         "request_id": value.get("request_id", "r1"),
                         "actor_id": value.get("actor_id", "actor1"),
                         "actor_name": value.get("actor_name", "Mira"),
                         "event": value.get("event", "move_rejected"),
                         "payload": value.get("payload", {"reason": "activity_pending"}),
                         "wall_time": value.get("wall_time", {"unix_seconds": 123 + index}),
                         "source": source})
            offset += len(raw)
        return self.save(rows), rows

    def select(self, body, timeout):
        return response(body, {c["id"]:"direct" for c in body["state"]["candidates"]})

    def test_exact_historical_row_handles_and_append_are_preserved(self):
        def call(body, timeout):
            with self.log.open("ab") as f: f.write(b'{"later":true}\n')
            return self.select(body, timeout)
        packet = h.search(self.root, self.snapshot, "Why rejected?", config=self.config, call=call)
        item = packet["items"][0]
        self.assertEqual(json.loads(item["excerpt"]), self.row)
        self.assertEqual(item["handle"]["selector"], "rows.0")
        self.assertEqual(item["handle"]["source"]["sha256"], t.digest(self.raw))

    def test_known_identity_and_rejection_are_provider_free_exact_retrieval(self):
        result = h.exact(self.root, self.snapshot, {
            "run_id": "run1", "request_id": "r1", "event": "move_rejected",
        }, selectors=("run_id", "request_id", "event", "payload.reason", "payload.accepted"),
                    config=self.config)
        self.assertEqual(result["route"], "R-EFF-EVIDENCE")
        self.assertEqual(result["provider_calls"], 0)
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["rows"][0]["fields"]["payload.reason"], "activity_pending")
        self.assertEqual(result["rows"][0]["fields"]["payload.accepted"], {"unavailable": True})
        with self.assertRaisesRegex(t.TelescopeError, "unsupported_exact_filter"):
            h.exact(self.root, self.snapshot, {"status": "rejected"}, config=self.config)

    def test_exact_retrieval_revalidates_source_before_returning_known_status(self):
        self.log.write_bytes(b"changed")
        result = h.exact(self.root, self.snapshot, {"request_id": "r1"}, config=self.config)
        self.assertEqual(result["provider_calls"], 0)
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["stale_ids"], ["e1"])

    def test_real_projected_shape_matches_and_verifies_original_source(self):
        # Same shape as retained production snapshot 6cbe78f2...ddd67:
        # event_id/source at root, selected identity and dotted fields under fields.
        row = {"event_id": self.row["event_id"], "source": self.row["source"],
               "fields": {"run_id": "run1", "request_id": "r1", "event": "move_rejected",
                          "payload.reason": "activity_pending"}}
        snapshot = self.save([row])
        result = h.exact(self.root, snapshot, {"run_id": "run1", "request_id": "r1"},
                         selectors=("payload.reason",), config=self.config)
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["stale_ids"], [])
        self.assertEqual(result["retrieval"]["source_verification_reads"], 1)
        self.assertEqual(result["rows"][0]["fields"]["payload.reason"], "activity_pending")
        missing = h.exact(self.root, snapshot, {"actor_id": "actor1"}, config=self.config)
        self.assertEqual(missing["stale_ids"], [])
        self.assertEqual(missing["retrieval"]["source_verification_reads"], 0)
        self.assertEqual(missing["unavailable_filter_fields"], [{"event_id": "e1", "fields": ["actor_id"]}])
        self.log.write_bytes(b"changed")
        stale = h.exact(self.root, snapshot, {"request_id": "r1"}, config=self.config)
        self.assertEqual(stale["stale_ids"], ["e1"])
        self.assertEqual(stale["retrieval"]["source_verification_reads"], 1)

    def test_competing_explanation_uses_one_typed_provider_call(self):
        calls = []

        def call(body, timeout):
            calls.append(body)
            return response(body)

        packet = h.search(self.root, self.snapshot, "Why was movement rejected?",
                          "The request was accepted", config=self.config, call=call)
        self.assertEqual(len(calls), 1)
        self.assertEqual(packet["provider_calls"], 1)
        self.assertEqual(packet["items"], [])

    def test_frozen_evidence_compare_reports_exact_vs_typed_work(self):
        exact = h.exact(self.root, self.snapshot, {"request_id": "r1"}, config=self.config)
        calls = []

        def call(body, timeout):
            calls.append(body)
            return response(body, {body["state"]["candidates"][0]["id"]: "direct"})

        typed = h.search(self.root, self.snapshot, "Why was movement rejected?",
                         "The request was accepted", config=self.config, call=call)
        self.assertEqual(exact["rows"][0]["source"]["sha256"],
                         typed["items"][0]["handle"]["source"]["sha256"])
        self.assertEqual(exact["provider_calls"], 0)
        self.assertEqual(exact["retrieval"]["source_verification_reads"], 1)
        self.assertEqual(typed["provider_calls"], 1)
        self.assertEqual(typed["retrieval"]["candidate_source_verification_reads"], 1)
        self.assertEqual(typed["retrieval"]["selection_source_verification_reads"], 1)
        if os.environ.get("TELESCOPE_PRINT_COMPARE"):
            print("S-EFF-COMPARE " + json.dumps({
                "exact_provider_calls": exact["provider_calls"],
                "exact_source_verification_reads": exact["retrieval"]["source_verification_reads"],
                "typed_provider_calls": typed["provider_calls"],
                "typed_candidate_source_verification_reads": typed["retrieval"]["candidate_source_verification_reads"],
                "typed_selection_source_verification_reads": typed["retrieval"]["selection_source_verification_reads"],
                "typed_stub_calls": len(calls),
            }, sort_keys=True))

    def test_replaced_deleted_source_or_snapshot_is_stale(self):
        for mode in ("edit","delete","snapshot"):
            self.log.write_bytes(self.raw)
            self.snapshot = self.save([self.row])
            def call(body, timeout):
                if mode == "edit": self.log.write_bytes(b"changed")
                elif mode == "delete": self.log.unlink()
                else: (self.root / ".userdata/openclaw_harness/evidence-display" / (self.snapshot + ".json")).write_text('{}')
                return self.select(body, timeout)
            packet = h.search(self.root, self.snapshot, "move rejected", config=self.config, call=call)
            self.assertEqual(packet["items"], [])
            self.assertEqual(len(packet["stale_ids"]), 1)

    def test_off_shadow_and_provider_failure_preserve_baseline(self):
        def forbidden(*args): self.fail("off made a call")
        off=h.search(self.root,self.snapshot,"move rejected",config={**self.config,"mode":"off"},call=forbidden)
        shadow=h.search(self.root,self.snapshot,"move rejected",config={**self.config,"mode":"shadow"},call=lambda b,t:response(b))
        self.assertEqual(off["items"],shadow["items"])
        def fail(*args): raise TimeoutError()
        fallback=h.search(self.root,self.snapshot,"move rejected",config=self.config,call=fail)
        self.assertEqual(fallback["items"],off["items"])
        self.assertEqual(fallback["fallback"],"provider_timeout")

    def test_relevance_abstention_and_counterevidence(self):
        none=h.search(self.root,self.snapshot,"move rejected",config=self.config,call=lambda b,t:response(b))
        self.assertTrue(none["abstained"])
        result=h.search(self.root,self.snapshot,"move rejected","movement accepted",config=self.config,
                        call=lambda b,t:response(b,counter=[b["state"]["candidates"][0]["id"]]))
        self.assertEqual(result["items"][0]["category"],"counterevidence")

    def test_roots_limits_and_deduplication(self):
        denied=h.search(self.root,self.snapshot,"question",config={**self.config,"paths":[".userdata/openclaw_harness/evidence-display"]},call=self.select)
        self.assertEqual(denied["candidates_considered"],0)
        small=h.search(self.root,self.snapshot,"move rejected",config={**self.config,"candidate_bytes":1},call=self.select)
        self.assertTrue(small["retrieval"]["truncated"])
        duplicate=self.save([self.row,self.row])
        packet=h.search(self.root,duplicate,"move rejected",config=self.config,call=self.select)
        self.assertEqual(len(packet["items"]),1)
        self.assertEqual(len(packet["retrieval"]["duplicate_reasons"]),1)

    def test_snapshot_and_source_tampering_before_selection_rejected(self):
        self.log.write_bytes(b"tampered")
        def forbidden(*args):self.fail("stale source transmitted")
        packet=h.search(self.root,self.snapshot,"move rejected",config=self.config,call=forbidden)
        self.assertTrue(packet["no_candidates"])
        with self.assertRaises(t.TelescopeError):
            h.search(self.root,"../x","question",config=self.config)

    def test_pool_deduplicates_before_provider(self):
        _snapshot, rows = self.save_rows_with_source([
            {"event_id": "same-a"}, {"event_id": "same-b"},
        ])
        # Make the second row an exact-equivalent record, including its source
        # identity, to exercise pre-provider deduplication.
        rows[1].update(rows[0])
        snapshot = self.save(rows)
        calls = []
        packet = h.search(self.root, snapshot, "move rejected", config=self.config,
                          call=lambda body, timeout: (calls.append(body) or self.select(body, timeout)))
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0]["state"]["candidates"]), 1)
        self.assertEqual(len(packet["retrieval"]["duplicate_reasons"]), 1)
        self.assertEqual(packet["items"][0]["equivalent_handles"][0]["event_id"], "same-a")

    def test_late_relevant_row_survives_irrelevant_prefix(self):
        snapshot, _ = self.save_rows_with_source([
            {"event_id": "noise-1", "event": "weather", "payload": {"text": "unrelated"}},
            {"event_id": "noise-2", "event": "weather", "payload": {"text": "unrelated"}},
            {"event_id": "late", "event": "move_rejected", "payload": {"reason": "frame_mismatch"}},
        ])
        calls = []
        config = {**self.config, "max_candidates": 1, "max_files": 3}
        packet = h.search(self.root, snapshot, "move rejected", config=config,
                          call=lambda body, timeout: (calls.append(body) or self.select(body, timeout)))
        self.assertEqual(len(calls[0]["state"]["candidates"]), 1)
        self.assertIn("late", calls[0]["state"]["candidates"][0]["excerpt"])
        self.assertFalse(packet["retrieval"]["scan_truncated"])

    def test_distinct_observations_and_counterevidence_survive_pool(self):
        snapshot, _ = self.save_rows_with_source([
            {"event_id": "answer", "run_id": "run-a", "payload": {"result": "accepted"}},
            {"event_id": "contradiction", "run_id": "run-b", "payload": {"result": "rejected"}},
            {"event_id": "later", "process_instance": "proc-2", "payload": {"result": "rejected"}},
        ])
        calls = []
        def call(body, timeout):
            calls.append(body)
            ids = [candidate["id"] for candidate in body["state"]["candidates"]]
            return response(body, {ids[0]: "direct", ids[1]: "history", ids[2]: "consequence"}, counter=[ids[1]])
        packet = h.search(self.root, snapshot, "move rejected result", "accepted", config=self.config, call=call)
        self.assertEqual(len(calls[0]["state"]["candidates"]), 3)
        self.assertEqual(len(packet["items"]), 3)
        self.assertIn("counterevidence", [item["category"] for item in packet["items"]])

    def test_scan_and_pool_truncation_are_distinct(self):
        snapshot, _ = self.save_rows_with_source([
            {"event_id": "one"}, {"event_id": "two"},
            {"event_id": "three"}, {"event_id": "four"},
        ])
        config = {**self.config, "max_files": 2, "max_candidates": 1}
        packet = h.search(self.root, snapshot, "move rejected", config=config, call=self.select)
        retrieval = packet["retrieval"]
        self.assertEqual(retrieval["rows_scanned"], 2)
        self.assertTrue(retrieval["scan_truncated"])
        self.assertEqual(retrieval["scan_truncation_reason"], "row_scan_budget")
        self.assertTrue(retrieval["final_pool_truncated"])
        self.assertEqual(retrieval["candidate_pool_before_limit"], 2)
        self.assertEqual(len(retrieval["final_pool_omitted_ids"]), 1)


if __name__ == "__main__":unittest.main()
