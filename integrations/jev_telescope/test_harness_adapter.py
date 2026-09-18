import json
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

    def test_replaced_deleted_source_or_snapshot_is_stale(self):
        for mode in ("edit","delete","snapshot"):
            self.log.write_bytes(self.raw)
            self.snapshot = self.save([self.row])
            def call(body, timeout):
                if mode == "edit": self.log.write_bytes(b"changed")
                elif mode == "delete": self.log.unlink()
                else: (self.root / ".userdata/openclaw_harness/evidence-display" / (self.snapshot + ".json")).write_text('{}')
                return self.select(body, timeout)
            packet = h.search(self.root, self.snapshot, "question", config=self.config, call=call)
            self.assertEqual(packet["items"], [])
            self.assertEqual(len(packet["stale_ids"]), 1)

    def test_off_shadow_and_provider_failure_preserve_baseline(self):
        def forbidden(*args): self.fail("off made a call")
        off=h.search(self.root,self.snapshot,"question",config={**self.config,"mode":"off"},call=forbidden)
        shadow=h.search(self.root,self.snapshot,"question",config={**self.config,"mode":"shadow"},call=lambda b,t:response(b))
        self.assertEqual(off["items"],shadow["items"])
        def fail(*args): raise TimeoutError()
        fallback=h.search(self.root,self.snapshot,"question",config=self.config,call=fail)
        self.assertEqual(fallback["items"],off["items"])
        self.assertEqual(fallback["fallback"],"provider_timeout")

    def test_relevance_abstention_and_counterevidence(self):
        none=h.search(self.root,self.snapshot,"question",config=self.config,call=lambda b,t:response(b))
        self.assertTrue(none["abstained"])
        result=h.search(self.root,self.snapshot,"question","movement accepted",config=self.config,
                        call=lambda b,t:response(b,counter=[b["state"]["candidates"][0]["id"]]))
        self.assertEqual(result["items"][0]["category"],"counterevidence")

    def test_roots_limits_and_deduplication(self):
        denied=h.search(self.root,self.snapshot,"question",config={**self.config,"paths":[".userdata/openclaw_harness/evidence-display"]},call=self.select)
        self.assertEqual(denied["candidates_considered"],0)
        small=h.search(self.root,self.snapshot,"question",config={**self.config,"candidate_bytes":1},call=self.select)
        self.assertTrue(small["retrieval"]["truncated"])
        duplicate=self.save([self.row,self.row])
        packet=h.search(self.root,duplicate,"question",config=self.config,call=self.select)
        self.assertEqual(len(packet["items"]),1)
        self.assertEqual(len(packet["omitted_ids"]),1)

    def test_snapshot_and_source_tampering_before_selection_rejected(self):
        self.log.write_bytes(b"tampered")
        def forbidden(*args):self.fail("stale source transmitted")
        packet=h.search(self.root,self.snapshot,"question",config=self.config,call=forbidden)
        self.assertTrue(packet["no_candidates"])
        with self.assertRaises(t.TelescopeError):
            h.search(self.root,"../x","question",config=self.config)


if __name__ == "__main__":unittest.main()
