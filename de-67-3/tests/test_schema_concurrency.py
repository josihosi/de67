"""Schema reopening is safe when two real SQLite connections interleave."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
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
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "clock.sqlite3"
            with DeadlineHarness(state):
                pass
            ready = threading.Barrier(2)
            connect = sqlite3.connect

            class InterleavedConnection(sqlite3.Connection):
                def executescript(self, sql):
                    if "CREATE TRIGGER" in sql and "claim_acceptance_closure_sequence_is_immutable" in sql:
                        # executescript commits pending backfill writes before its
                        # first statement. Schedule both constructors at that gap.
                        self.commit()
                        ready.wait(timeout=10)
                    return super().executescript(sql)

            def selected_connect(*args, **kwargs):
                return connect(*args, **kwargs, factory=InterleavedConnection)

            def reopen():
                with DeadlineHarness(state) as harness:
                    return harness.connection.execute(
                        "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' "
                        "AND name='claim_acceptance_closure_sequence_is_immutable'"
                    ).fetchone()[0]

            with patch("deadline_harness.sqlite3.connect", side_effect=selected_connect):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    self.assertEqual(list(pool.map(lambda _: reopen(), range(2))), [1, 1])


if __name__ == "__main__":
    unittest.main()
