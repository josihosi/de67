import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

import de67_dashboard as dashboard


class SubscriptionTests(unittest.TestCase):
    now = 2_000_000_000
    week = 604800

    def response(self, used=75, elapsed=.5, **changes):
        window = dict(usedPercent=used, windowDurationMins=10080,
                      resetsAt=self.now + self.week * (1-elapsed))
        window.update(changes)
        return {"rateLimitsByLimitId": {"codex": {"primary": window}}}

    def test_weekly_can_be_primary_or_secondary_and_ignores_spark(self):
        data = self.response()
        bucket = data["rateLimitsByLimitId"]["codex"]
        bucket["secondary"] = bucket.pop("primary")
        bucket["primary"] = dict(usedPercent=99, windowDurationMins=300)
        data["rateLimitsByLimitId"]["spark"] = {"secondary": dict(usedPercent=0, windowDurationMins=10080)}
        state = dashboard.weekly_subscription(data, self.now)
        self.assertEqual((state["remaining"], state["pace"], state["ngmi"]), (25, 1.5, True))
        del data["rateLimitsByLimitId"]["codex"]
        self.assertFalse(dashboard.weekly_subscription(data, self.now)["available"])

    def test_legacy_and_missing_values(self):
        bucket = self.response()["rateLimitsByLimitId"]["codex"]
        self.assertTrue(dashboard.weekly_subscription({"rateLimits": bucket}, self.now)["available"])
        for value in (None, True, float('nan'), '75'):
            self.assertFalse(dashboard.weekly_subscription(self.response(used=value), self.now)["available"])
        state = dashboard.weekly_subscription(self.response(resetsAt=None), self.now)
        self.assertIsNone(state["pace"])
        self.assertIn('pace unknown', dashboard.render_subscription(state))

    def test_pace_boundary_and_reset(self):
        self.assertFalse(dashboard.weekly_subscription(self.response(used=50), self.now)["ngmi"])
        self.assertTrue(dashboard.weekly_subscription(self.response(used=51), self.now)["ngmi"])
        for elapsed in (0, 1, 1.1, -.1):
            self.assertIsNone(dashboard.weekly_subscription(self.response(elapsed=elapsed), self.now)["pace"])

    def test_render_lowercase_and_stale_forecast_suppression(self):
        state = dashboard.weekly_subscription(self.response(), self.now)
        markup = dashboard.render_subscription(state)
        self.assertIn('>ngmi<', markup)
        self.assertNotIn('NGMI', markup)
        self.assertIn('aria-valuenow="25"', markup)
        stale = dashboard.render_subscription(dict(state, stale=True))
        self.assertNotIn('>ngmi<', stale)
        self.assertNotIn('1.50×', stale)
        self.assertIn('stale reading', stale)
        self.assertEqual(dashboard.render_subscription(None), '')

    def test_async_read_is_cached_and_failure_preserves_last_good(self):
        entered = threading.Event()
        release = threading.Event()
        def fetch(_):
            entered.set()
            release.wait(2)
            return self.response()
        usage = dashboard.SubscriptionUsage('unused')
        with patch.object(dashboard, 'read_subscription_limits', side_effect=fetch) as read:
            self.assertFalse(usage.snapshot()["available"])
            self.assertTrue(entered.wait(1))
            usage.snapshot()
            self.assertEqual(read.call_count, 1)
            release.set()
            self.wait_done(usage)
            self.assertEqual(usage.snapshot()["remaining"], 25)
            self.assertEqual(read.call_count, 1)
        with patch.object(dashboard, 'read_subscription_limits', side_effect=RuntimeError):
            usage._next = 0
            usage.snapshot()
            self.wait_done(usage)
            self.assertTrue(usage.snapshot()["stale"])
            self.assertEqual(usage.snapshot()["remaining"], 25)

    def wait_done(self, usage):
        end = time.monotonic() + 3
        while usage._running and time.monotonic() < end:
            time.sleep(.01)
        self.assertFalse(usage._running)

    def test_stdio_handshake_and_exact_read_only_methods(self):
        # A real subprocess exercises pipes/flush/cleanup on each supported OS.
        script = """
import sys,json
a=json.loads(sys.stdin.readline());assert a['method']=='initialize'
print(json.dumps({'id':a['id'],'result':{}}),flush=True)
assert json.loads(sys.stdin.readline())['method']=='initialized'
b=json.loads(sys.stdin.readline());assert b['method']=='account/rateLimits/read'
print(json.dumps({'id':b['id'],'result':{'rateLimits':{}}}),flush=True)
sys.stdin.read()
"""
        real_popen = subprocess.Popen
        children = []
        def launch(argv, **kwargs):
            self.assertEqual(argv, ['test-codex', 'app-server', '--listen', 'stdio://'])
            process = real_popen([sys.executable, '-u', '-c', script], **kwargs)
            children.append(process)
            return process
        with patch.object(dashboard.subprocess, 'Popen', side_effect=launch):
            self.assertEqual(dashboard.read_subscription_limits('test-codex'), {'rateLimits': {}})
        self.assertIsNotNone(children[0].poll())

    def test_timeout_closes_owned_process(self):
        real_popen = subprocess.Popen
        children = []
        def launch(argv, **kwargs):
            process = real_popen([sys.executable, '-u', '-c', 'import time; time.sleep(30)'], **kwargs)
            children.append(process)
            return process
        with patch.object(dashboard.subprocess, 'Popen', side_effect=launch):
            with self.assertRaises(TimeoutError):
                dashboard.read_subscription_limits('test-codex', timeout=.1)
        self.assertIsNotNone(children[0].poll())


if __name__ == '__main__':
    unittest.main()
