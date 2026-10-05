"""Schema reopening is safe when two real SQLite connections interleave."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from deadline_harness import DeadlineHarness


class SchemaConcurrencyTests(unittest.TestCase):
    def test_concurrent_reopen_keeps_the_closure_guard(self):
        self.assert_concurrent_reopen("claim_acceptance_closure_sequence_is_immutable")

    def test_concurrent_reopen_keeps_terminal_insert_validation(self):
        self.assert_concurrent_reopen("task_terminal_kind_is_valid_on_insert")

    def test_concurrent_reopen_keeps_terminal_update_validation(self):
        self.assert_concurrent_reopen("task_terminal_kind_is_valid_on_update")

    def assert_concurrent_reopen(self, trigger):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "clock.sqlite3"
            with DeadlineHarness(state):
                pass
            ready = threading.Barrier(2)
            connect = sqlite3.connect

            class InterleavedConnection(sqlite3.Connection):
                def executescript(self, sql):
                    match = re.search(r"CREATE TRIGGER(?: IF NOT EXISTS)? " + re.escape(trigger) + r"\b", sql)
                    if match:
                        # Run actual preceding drops/backfills, then schedule both
                        # connections at the real autocommit gap before CREATE.
                        super().executescript(sql[:match.start()])
                        self.commit()
                        ready.wait(timeout=10)
                        return super().executescript(sql[match.start():])
                    return super().executescript(sql)

            def selected_connect(*args, **kwargs):
                return connect(*args, **kwargs, factory=InterleavedConnection)

            def reopen():
                with DeadlineHarness(state) as harness:
                    return harness.connection.execute(
                        "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' "
                        "AND name=?", (trigger,)
                    ).fetchone()[0]

            with patch("deadline_harness.sqlite3.connect", side_effect=selected_connect):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    self.assertEqual(list(pool.map(lambda _: reopen(), range(2))), [1, 1])


if __name__ == "__main__":
    unittest.main()
