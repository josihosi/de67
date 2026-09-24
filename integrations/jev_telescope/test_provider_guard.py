import importlib.util
import io
import json
from contextlib import closing
from email.message import Message
import multiprocessing
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
from unittest.mock import patch

import provider_guard as g
import telescope as t


class StubProviderError(Exception):
    def __init__(self, status, code="provider_code", request_id="request-01", retry_after_seconds=None):
        self.status = status
        self.code = code
        self.request_id = request_id
        self.retry_after_seconds = retry_after_seconds
        super().__init__("untrusted provider body must not be logged")


def guard_config(root, *, scope="scope-01", mode="on", max_calls=8, max_retries=0,
                 retry_backoff_seconds=0, max_in_flight=2):
    return {
        "mode": mode,
        "scope_id": scope,
        "state_path": str((root / "owner-state" / "provider-guard.sqlite3").resolve()),
        "max_calls": max_calls,
        "max_request_bytes": 4096,
        "max_in_flight": max_in_flight,
        "timeout_seconds": 2,
        "max_retries": max_retries,
        "retry_backoff_seconds": retry_backoff_seconds,
    }


class Sink:
    def __init__(self):
        self.sent = []

    def send(self, value):
        self.sent.append(value)

    def close(self):
        pass


def reserve_after_start_signal(config, request_id, ready, start, results):
    """Spawn-safe worker used to prove SQLite arbitration crosses process boundaries."""
    ready.put(request_id)
    if not start.wait(5):
        results.put(("error", "start_timeout", False))
        return
    try:
        with patch.object(g, "_disposable_context_roots", return_value=()):
            admission = g.ProviderGuard(config).reserve(21, logical_request_id=request_id)
        results.put((admission.reason, admission.allowed, admission.shutdown_notice))
    except Exception:
        results.put(("error", False, False))


class ProviderGuardTests(unittest.TestCase):
    def setUp(self):
        self._real_disposable_context_roots = g._disposable_context_roots
        self._ordinary_fixture_roots = patch.object(g, "_disposable_context_roots", return_value=())
        self._ordinary_fixture_roots.start()
        self.addCleanup(self._ordinary_fixture_roots.stop)
        self.temp = tempfile.TemporaryDirectory(prefix=".provider-guard-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def dispatch(self, guard, transport, *, request_id="request-01"):
        return guard.dispatch({"bounded": "payload"}, request_bytes=21, timeout=1,
                              transport=transport, logical_request_id=request_id)

    def rows(self, config):
        with closing(sqlite3.connect(config["state_path"])) as db:
            return db.execute("""SELECT admission_state,outcome,provider_status,provider_code,
                                      provider_request_id,parent_admission_id
                               FROM provider_guard_admissions WHERE scope_id=? ORDER BY created_at, admission_id""",
                              (config["scope_id"],)).fetchall()

    def simulate_legacy_funds_latch(self, config):
        """Model the future documented transition without inventing a current classifier."""
        with closing(sqlite3.connect(config["state_path"])) as db:
            db.execute("""UPDATE provider_guard_scopes SET effective_state='disabled_funds',
                       state_reason='authoritative_legacy_record', retry_not_before=NULL,
                       state_epoch=state_epoch+1, updated_at=updated_at+1 WHERE scope_id=?""",
                       (config["scope_id"],))
            db.commit()

    def test_off_never_dispatches_or_creates_owner_state(self):
        called = []
        with self.assertRaisesRegex(g.GuardError, "provider_guard_off"):
            self.dispatch(g.ProviderGuard({"mode": "off"}), lambda payload, timeout: called.append(payload))
        self.assertEqual(called, [])
        self.assertFalse((self.root / "owner-state").exists())

    def test_request_bound_blocks_before_transport(self):
        config = {**guard_config(self.root, scope="request-bound-01"), "max_request_bytes": 20}
        called = []
        with self.assertRaisesRegex(g.GuardError, "provider_request_exceeds_bound"):
            self.dispatch(g.ProviderGuard(config), lambda payload, timeout: called.append(payload))
        self.assertEqual(called, [])
        self.assertEqual(g.ProviderGuard(config).status()["effective_state"], "ready")

    def test_in_flight_accounting_survives_an_overlapping_admission_check(self):
        config = guard_config(self.root, scope="inflight-01", max_calls=3, max_in_flight=1)
        entered, release, result = threading.Event(), threading.Event(), []

        def transport(payload, timeout):
            entered.set()
            self.assertTrue(release.wait(2))
            return {"usage": {"input_tokens": 4, "output_tokens": 1}}

        thread = threading.Thread(target=lambda: result.append(self.dispatch(g.ProviderGuard(config), transport)))
        thread.start()
        self.assertTrue(entered.wait(2))
        observed = g.ProviderGuard(config).status()
        self.assertEqual(observed["in_flight"], 1)
        blocked = g.ProviderGuard(config).reserve(21, logical_request_id="overlap-01")
        self.assertTrue(blocked.allowed)
        self.assertFalse(g.ProviderGuard(config).start(blocked).allowed)
        release.set()
        thread.join()
        settled = g.ProviderGuard(config).status()
        self.assertEqual(settled["in_flight"], 0)
        self.assertEqual(settled["calls_completed"], 1)
        self.assertEqual(result[0].status["input_tokens"], 4)

    def test_budget_and_auth_are_distinct_terminal_states(self):
        budget_config = guard_config(self.root, scope="budget-01", max_calls=1)
        budget = g.ProviderGuard(budget_config)
        first = self.dispatch(budget, lambda payload, timeout: {"usage": {"input_tokens": 3, "output_tokens": 2}})
        self.assertEqual(first.status["effective_state"], "disabled_budget")
        with self.assertRaisesRegex(g.GuardError, "disabled_budget"):
            self.dispatch(g.ProviderGuard(budget_config), lambda payload, timeout: self.fail("budget dispatched"))

        auth_config = guard_config(self.root, scope="auth-01")
        with self.assertRaises(g.DispatchError) as raised:
            self.dispatch(g.ProviderGuard(auth_config), lambda payload, timeout: (_ for _ in ()).throw(StubProviderError(401)))
        self.assertEqual(raised.exception.status["effective_state"], "auth_error")
        self.assertEqual(g.ProviderGuard(auth_config).status()["effective_state"], "auth_error")
        self.assertNotEqual(g.ProviderGuard(auth_config).status()["effective_state"], "disabled_budget")

    def test_only_explicit_owner_auth_reset_reopens_corrected_credentials(self):
        config = guard_config(self.root, scope="auth-reset-01")
        with self.assertRaises(g.DispatchError):
            self.dispatch(g.ProviderGuard(config),
                          lambda payload, timeout: (_ for _ in ()).throw(StubProviderError(401)),
                          request_id="auth-reset-failure-01")
        guard = g.ProviderGuard(config)
        with self.assertRaisesRegex(g.GuardError, "provider_owner_auth_reset_required"):
            guard.reset_auth_latch(owner_confirmed=False)
        self.assertEqual(guard.status()["effective_state"], "auth_error")
        self.assertEqual(guard.reset_auth_latch(owner_confirmed=True)["effective_state"], "ready")
        recovered = self.dispatch(g.ProviderGuard(config),
                                  lambda payload, timeout: {"usage": {"input_tokens": 1, "output_tokens": 1}},
                                  request_id="auth-reset-success-01")
        self.assertEqual(recovered.attempts, 1)
        self.assertEqual(recovered.status["effective_state"], "ready")

    def test_rate_limit_overload_timeout_and_undocumented_funds_stay_distinct(self):
        for scope, error, expected in (
            ("rate-01", StubProviderError(429, "rate_limited", "rate-01"), "transient_open"),
            ("overload-01", StubProviderError(529, "overloaded", "overload-01"), "transient_open"),
            ("timeout-01", TimeoutError(), "transient_open"),
            ("funds-unknown-01", StubProviderError(402, "credit_exhausted", "funds-01"), "ready"),
        ):
            with self.subTest(scope=scope):
                config = guard_config(self.root, scope=scope, retry_backoff_seconds=60)
                guard = g.ProviderGuard(config)
                with self.assertRaises(g.DispatchError) as raised:
                    self.dispatch(guard, lambda payload, timeout, error=error: (_ for _ in ()).throw(error))
                self.assertEqual(raised.exception.status["effective_state"], expected)
                self.assertNotEqual(raised.exception.status["effective_state"], "disabled_funds")
                self.assertEqual(raised.exception.status["funds_classification"], g.FUNDS_CLASSIFICATION)
        timeout_rows = self.rows(guard_config(self.root, scope="timeout-01"))
        self.assertEqual(timeout_rows[0][0], "unknown")
        funds_rows = self.rows(guard_config(self.root, scope="funds-unknown-01"))
        self.assertEqual(funds_rows[0][2:5], (402, "credit_exhausted", "funds-01"))

    def test_retry_is_a_fresh_durable_admission(self):
        config = guard_config(self.root, scope="retry-01", max_retries=1, retry_backoff_seconds=0)
        guard, calls = g.ProviderGuard(config), []

        def transport(payload, timeout):
            calls.append(timeout)
            if len(calls) == 1:
                raise StubProviderError(429, "rate_limited", "retry-01")
            return {"usage": {"input_tokens": 2, "output_tokens": 1}}

        result = self.dispatch(guard, transport, request_id="retry-request-01")
        self.assertEqual(result.attempts, 2)
        self.assertEqual(len(calls), 2)
        rows = self.rows(config)
        self.assertEqual([row[0] for row in rows], ["failed", "completed"])
        self.assertIsNotNone(rows[1][5])
        self.assertEqual(result.status["calls_reserved"], 2)

    def test_retry_after_wait_is_not_shortened_or_retried_past_deadline(self):
        now, sleeps, calls = [100.0], [], []

        def monotonic():
            return now[0]

        def sleeper(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        config = {**guard_config(self.root, scope="retry-after-01", max_retries=1,
                                 retry_backoff_seconds=1), "timeout_seconds": 10}
        guard = g.ProviderGuard(config, clock=monotonic, sleeper=sleeper)

        def eventually_succeeds(payload, timeout):
            calls.append(timeout)
            if len(calls) == 1:
                raise StubProviderError(429, "rate_limited", "retry-after-01", retry_after_seconds=4)
            return {"usage": {"input_tokens": 2, "output_tokens": 1}}

        with patch.object(g.time, "monotonic", side_effect=monotonic):
            result = guard.dispatch({}, request_bytes=21, timeout=10,
                                    transport=eventually_succeeds, logical_request_id="retry-after-request-01")
        self.assertEqual(result.attempts, 2)
        self.assertEqual(sleeps, [4.0])
        self.assertEqual(len(calls), 2)

        deadline_now, deadline_sleeps, deadline_calls = [200.0], [], []

        def deadline_monotonic():
            return deadline_now[0]

        def deadline_sleeper(seconds):
            deadline_sleeps.append(seconds)
            deadline_now[0] += seconds

        deadline_config = guard_config(self.root, scope="retry-after-deadline-01",
                                       max_retries=1, retry_backoff_seconds=1)
        deadline_guard = g.ProviderGuard(deadline_config, clock=deadline_monotonic,
                                         sleeper=deadline_sleeper)

        def always_rate_limited(payload, timeout):
            deadline_calls.append(timeout)
            raise StubProviderError(429, "rate_limited", "retry-after-deadline-01", retry_after_seconds=4)

        with patch.object(g.time, "monotonic", side_effect=deadline_monotonic), self.assertRaises(g.DispatchError) as raised:
            deadline_guard.dispatch({}, request_bytes=21, timeout=3, transport=always_rate_limited,
                                    logical_request_id="retry-after-deadline-request-01")
        self.assertEqual(raised.exception.attempts, 1)
        self.assertEqual(len(deadline_calls), 1)
        self.assertEqual(deadline_sleeps, [])
        self.assertEqual(raised.exception.status["effective_state"], "transient_open")
        self.assertEqual(raised.exception.status["retry_not_before"], 204.0)

    def test_retry_admission_denial_preserves_prior_provider_failure(self):
        config = guard_config(self.root, scope="retry-denied-01", max_calls=1,
                              max_retries=1, retry_backoff_seconds=0)
        calls = []

        def rate_limited(payload, timeout):
            calls.append(timeout)
            raise StubProviderError(429, "rate_limited", "retry-denied-01")

        with self.assertRaises(g.DispatchError) as raised:
            self.dispatch(g.ProviderGuard(config), rate_limited, request_id="retry-denied-request-01")
        self.assertEqual(len(calls), 1)
        self.assertEqual(raised.exception.attempts, 1)
        self.assertIsInstance(raised.exception.cause, StubProviderError)
        self.assertEqual(raised.exception.cause.status, 429)
        self.assertEqual(raised.exception.status["effective_state"], "disabled_budget")

    def test_overlapping_auth_failure_upgrades_a_transient_latch(self):
        config = guard_config(self.root, scope="overlap-auth-01", max_in_flight=2)
        guard = g.ProviderGuard(config)
        first = guard.start(guard.reserve(21, logical_request_id="overlap-auth-rate-01"))
        second = guard.start(guard.reserve(21, logical_request_id="overlap-auth-auth-01"))
        self.assertTrue(first.allowed)
        self.assertTrue(second.allowed)
        guard._finish(first, outcome="provider_http_429",
                      failure=StubProviderError(429, "rate_limited", "overlap-auth-rate-01", 5))
        outcome = guard._finish(second, outcome="provider_http_401",
                                failure=StubProviderError(401, "unauthorized", "overlap-auth-auth-01"))
        self.assertEqual(outcome.status["effective_state"], "auth_error")
        self.assertIsNone(outcome.status["retry_not_before"])
        self.assertEqual(g.ProviderGuard(config).status()["effective_state"], "auth_error")

    def test_overlapping_retry_after_extends_the_transient_latch(self):
        now = [100.0]
        config = guard_config(self.root, scope="overlap-retry-after-01", max_in_flight=2)
        guard = g.ProviderGuard(config, clock=lambda: now[0])
        first = guard.start(guard.reserve(21, logical_request_id="overlap-retry-first-01"))
        second = guard.start(guard.reserve(21, logical_request_id="overlap-retry-later-01"))
        self.assertTrue(first.allowed)
        self.assertTrue(second.allowed)
        first_outcome = guard._finish(first, outcome="provider_http_429",
                                      failure=StubProviderError(429, "rate_limited", "overlap-retry-first-01", 2))
        self.assertEqual(first_outcome.status["retry_not_before"], 102.0)
        now[0] = 101.0
        later_outcome = guard._finish(second, outcome="provider_http_529",
                                      failure=StubProviderError(529, "overloaded", "overlap-retry-later-01", 5))
        self.assertEqual(later_outcome.status["effective_state"], "transient_open")
        self.assertEqual(later_outcome.status["retry_not_before"], 106.0)
        now[0] = 102.0
        self.assertEqual(guard.status()["retry_not_before"], 106.0)

    def test_status_reports_budget_notice_and_telescope_preserves_it(self):
        status_config = guard_config(self.root, scope="status-notice-01", max_calls=0)
        first_status = g.ProviderGuard(status_config).status()
        self.assertTrue(first_status["shutdown_notice"])
        self.assertFalse(g.ProviderGuard(status_config).status()["shutdown_notice"])

        source = self.root / "source.py"
        source.write_text("def bounded_selection():\n    return 'candidate'\n")
        telescope_config = t.validate_config({"mode": "on", "paths": ["source.py"], "cache_seconds": 0,
                                              "provider_guard": guard_config(self.root, scope="telescope-notice-01",
                                                                             max_calls=0)})
        pool, info = t.gather(self.root, "bounded selection", [], telescope_config, 10**12)
        packet = t.evaluate(self.root, "bounded selection", "", pool, info, telescope_config,
                            call=lambda body, timeout: self.fail("budget-latched guard dispatched"))
        self.assertEqual(packet["fallback"], "disabled_budget")
        self.assertEqual(packet["provider_calls"], 0)
        self.assertTrue(packet["provider_guard"]["shutdown_notice"])

    def test_observed_usage_above_reservation_latches_token_budget(self):
        config = {**guard_config(self.root, scope="observed-token-budget-01", max_calls=8),
                  "max_total_tokens": 1000, "per_request_token_ceiling": 100}
        result = self.dispatch(g.ProviderGuard(config),
                               lambda payload, timeout: {"usage": {"input_tokens": 800, "output_tokens": 500}},
                               request_id="observed-token-budget-request-01")
        self.assertEqual(result.status["effective_state"], "disabled_budget")
        self.assertEqual(result.status["state_reason"], "max_total_tokens")
        self.assertEqual(result.status["reserved_tokens"], 1300)
        self.assertTrue(result.shutdown_notice)
        with self.assertRaisesRegex(g.GuardError, "disabled_budget"):
            self.dispatch(g.ProviderGuard(config), lambda payload, timeout: self.fail("over-budget dispatched"),
                          request_id="observed-token-budget-next-01")

    def test_unrepresentable_usage_is_unknown_charged_and_keeps_telescope_baseline(self):
        huge_usage = g._SQLITE_INTEGER_MAX + 1
        config = {**guard_config(self.root, scope="unrepresentable-token-01", max_calls=8),
                  "max_total_tokens": 1000, "per_request_token_ceiling": 100}
        with self.assertRaises(g.DispatchError) as raised:
            self.dispatch(g.ProviderGuard(config),
                          lambda payload, timeout: {"usage": {"input_tokens": huge_usage, "output_tokens": 0}},
                          request_id="unrepresentable-token-request-01")
        self.assertEqual(raised.exception.attempts, 1)
        self.assertEqual(raised.exception.cause.reason, "provider_usage_unrepresentable")
        self.assertEqual(raised.exception.status["effective_state"], "disabled_budget")
        self.assertEqual(raised.exception.status["in_flight"], 0)
        self.assertEqual(raised.exception.status["reserved_tokens"], g._SQLITE_INTEGER_MAX)
        with closing(sqlite3.connect(config["state_path"])) as db:
            row = db.execute("SELECT admission_state,outcome,input_tokens,output_tokens FROM provider_guard_admissions").fetchone()
        self.assertEqual(row, ("unknown", "provider_usage_unrepresentable", None, None))

        source = self.root / "source.py"
        source.write_text("def bounded_selection():\n    return 'candidate'\n")
        telescope_config = t.validate_config({"mode": "on", "paths": ["source.py"], "cache_seconds": 0,
                                              "provider_guard": {**config, "scope_id": "telescope-unrepresentable-token-01"}})
        pool, info = t.gather(self.root, "bounded selection", [], telescope_config, 10**12)

        def oversized_response(body, timeout):
            answers = {}
            for key, question in body["questions"].items():
                choice = next(iter(question["criteria"]))
                answers[key] = {"type": "choice", "choice": choice, "confidence": 1,
                                "probabilities": {option: float(option == choice) for option in question["criteria"]}}
            return {"model": "jev-test", "answers": answers,
                    "usage": {"input_tokens": huge_usage, "output_tokens": 0}}

        packet = t.evaluate(self.root, "bounded selection", "", pool, info, telescope_config,
                            call=oversized_response)
        self.assertEqual(packet["provider_calls"], 1)
        self.assertTrue(packet["fallback"])
        self.assertEqual(packet["items"], t.assemble(
            self.root, pool, [{"id": candidate["id"], "category": "baseline_match"} for candidate in pool],
            telescope_config)["items"])

    def test_unrepresentable_charge_saturates_without_aggregate_overflow(self):
        config = {**guard_config(self.root, scope="saturated-token-total-01", max_calls=8),
                  "max_total_tokens": g._SQLITE_INTEGER_MAX, "per_request_token_ceiling": 1}
        first = self.dispatch(g.ProviderGuard(config),
                              lambda payload, timeout: {"usage": {"input_tokens": 1, "output_tokens": 0}},
                              request_id="saturated-token-first-01")
        self.assertEqual(first.status["effective_state"], "ready")
        with self.assertRaises(g.DispatchError) as raised:
            self.dispatch(g.ProviderGuard(config),
                          lambda payload, timeout: {"usage": {"input_tokens": g._SQLITE_INTEGER_MAX + 1,
                                                             "output_tokens": 0}},
                          request_id="saturated-token-second-01")
        self.assertEqual(raised.exception.status["effective_state"], "disabled_budget")
        self.assertEqual(raised.exception.status["reserved_tokens"], g._SQLITE_INTEGER_MAX + 1)
        settled = g.ProviderGuard(config).status()
        self.assertEqual(settled["in_flight"], 0)
        self.assertEqual(settled["reserved_tokens"], g._SQLITE_INTEGER_MAX + 1)

    def test_retry_admission_exception_preserves_the_prior_attempt(self):
        config = guard_config(self.root, scope="retry-admission-error-01", max_retries=1,
                              retry_backoff_seconds=0)
        guard = g.ProviderGuard(config)
        reserve = guard.reserve

        def unavailable_on_retry(request_bytes, **kwargs):
            if kwargs["attempt"] == 1:
                raise g.GuardError("provider_guard_state_unavailable",
                                   {"state_error": "provider_guard_state_unavailable", "shutdown_notice": False})
            return reserve(request_bytes, **kwargs)

        with patch.object(guard, "reserve", side_effect=unavailable_on_retry), self.assertRaises(g.DispatchError) as raised:
            self.dispatch(guard, lambda payload, timeout: (_ for _ in ()).throw(
                StubProviderError(429, "rate_limited", "retry-admission-error-01")),
                          request_id="retry-admission-error-request-01")
        self.assertEqual(raised.exception.attempts, 1)
        self.assertIsInstance(raised.exception.cause, StubProviderError)
        self.assertEqual(raised.exception.cause.status, 429)
        self.assertEqual(raised.exception.status["state_error"], "provider_guard_state_unavailable")

    def test_retry_cleanup_exception_preserves_the_prior_attempt(self):
        config = guard_config(self.root, scope="retry-cleanup-error-01", max_retries=1,
                              retry_backoff_seconds=0)
        guard = g.ProviderGuard(config)
        start, starts = guard.start, []

        def deny_retry(admission, **kwargs):
            starts.append(admission.admission_id)
            if len(starts) == 1:
                return start(admission, **kwargs)
            return g.Admission(admission.admission_id, admission.logical_request_id, False,
                               "provider_concurrency_limited",
                               {"state_error": "provider_guard_state_unavailable", "shutdown_notice": False})

        cleanup_error = g.GuardError("provider_guard_state_unavailable",
                                     {"state_error": "provider_guard_state_unavailable", "shutdown_notice": False})
        with patch.object(guard, "start", side_effect=deny_retry), \
                patch.object(guard, "_cancel", side_effect=cleanup_error), \
                self.assertRaises(g.DispatchError) as raised:
            self.dispatch(guard, lambda payload, timeout: (_ for _ in ()).throw(
                StubProviderError(429, "rate_limited", "retry-cleanup-error-01")),
                          request_id="retry-cleanup-error-request-01")
        self.assertEqual(raised.exception.attempts, 1)
        self.assertIsInstance(raised.exception.cause, StubProviderError)
        self.assertEqual(raised.exception.cause.status, 429)
        self.assertEqual(raised.exception.status["state_error"], "provider_guard_state_unavailable")

    def test_expired_admission_is_cancelled_before_transport_or_usage_accounting(self):
        def assert_cancelled_when(expire_start):
            now, called = [0.0], []
            config = guard_config(self.root, scope="deadline-before-dispatch-" + str(expire_start), max_calls=3)
            guard = g.ProviderGuard(config, clock=lambda: now[0])
            start = guard.start

            def delayed_start(admission, **kwargs):
                if not expire_start:
                    started = start(admission, **kwargs)
                    now[0] = 2.0
                    return started
                now[0] = 2.0
                return start(admission, **kwargs)

            with patch.object(g.time, "monotonic", side_effect=lambda: now[0]), \
                    patch.object(guard, "start", side_effect=delayed_start), \
                    self.assertRaisesRegex(g.GuardError, "provider_timeout_before_dispatch"):
                guard.dispatch({}, request_bytes=21, timeout=1,
                               transport=lambda payload, timeout: called.append((payload, timeout)),
                               logical_request_id="deadline-before-dispatch-request-" + str(expire_start))
            self.assertEqual(called, [])
            self.assertEqual(guard.status()["calls_reserved"], 0)
            self.assertEqual(guard.status()["in_flight"], 0)
            with closing(sqlite3.connect(config["state_path"])) as db:
                row = db.execute("SELECT admission_state,outcome FROM provider_guard_admissions").fetchone()
            self.assertEqual(row, ("cancelled", "deadline_before_dispatch"))

        for expire_start in (True, False):
            with self.subTest(expire_start=expire_start):
                assert_cancelled_when(expire_start)

    def test_pretransport_deadline_cancellation_reopens_only_its_budget_latch(self):
        config = guard_config(self.root, scope="deadline-budget-race-01", max_calls=1)
        guard = g.ProviderGuard(config)
        started = guard.start(guard.reserve(21, logical_request_id="deadline-budget-race-01"))
        self.assertTrue(started.allowed)
        observed = guard.status()
        self.assertEqual(observed["effective_state"], "disabled_budget")
        self.assertTrue(observed["shutdown_notice"])

        released = guard._cancel_before_dispatch(started)
        self.assertEqual(released["effective_state"], "ready")
        self.assertEqual(released["calls_reserved"], 0)
        self.assertEqual(released["in_flight"], 0)
        self.assertTrue(guard.reserve(21, logical_request_id="deadline-budget-race-retry-01").allowed)

    def test_owner_confirmed_recovery_releases_only_abandoned_in_flight_slots(self):
        config = guard_config(self.root, scope="owner-recovery-01", max_calls=3, max_in_flight=1)
        guard = g.ProviderGuard(config)
        abandoned = guard.start(guard.reserve(21, logical_request_id="owner-recovery-abandoned-01"))
        self.assertTrue(abandoned.allowed)
        waiting = guard.start(guard.reserve(21, logical_request_id="owner-recovery-waiting-01"))
        self.assertFalse(waiting.allowed)
        guard._cancel(waiting)
        with self.assertRaisesRegex(g.GuardError, "provider_owner_recovery_required"):
            guard.recover_abandoned_in_flight(owner_confirmed=False)
        recovered = guard.recover_abandoned_in_flight(owner_confirmed=True)
        self.assertEqual(recovered["recovered_admissions"], 1)
        self.assertEqual(recovered["in_flight"], 0)
        self.assertEqual(recovered["calls_reserved"], 1)
        next_admission = guard.start(guard.reserve(21, logical_request_id="owner-recovery-next-01"))
        self.assertTrue(next_admission.allowed)
        with self.assertRaisesRegex(g.GuardError, "provider_admission_not_in_flight"):
            guard._finish(abandoned, outcome="provider_response", result={"usage": {"input_tokens": 1, "output_tokens": 1}})
        with closing(sqlite3.connect(config["state_path"])) as db:
            row = db.execute("SELECT admission_state,outcome FROM provider_guard_admissions WHERE admission_id=?",
                             (abandoned.admission_id,)).fetchone()
        self.assertEqual(row, ("unknown", "owner_confirmed_abandoned"))

    def test_owner_confirmed_reservation_recovery_releases_pre_start_capacity(self):
        config = guard_config(self.root, scope="reservation-recovery-01", max_calls=1)
        guard = g.ProviderGuard(config)
        abandoned = guard.reserve(21, logical_request_id="reservation-recovery-abandoned-01")
        self.assertTrue(abandoned.allowed)
        with self.assertRaisesRegex(g.GuardError, "provider_owner_reservation_recovery_required"):
            guard.cancel_abandoned_reservations(owner_confirmed=False)
        recovered = guard.cancel_abandoned_reservations(owner_confirmed=True)
        self.assertEqual(recovered["cancelled_reservations"], 1)
        self.assertEqual(recovered["calls_reserved"], 0)
        self.assertFalse(guard.start(abandoned).allowed)
        self.assertTrue(guard.reserve(21, logical_request_id="reservation-recovery-next-01").allowed)
        with closing(sqlite3.connect(config["state_path"])) as db:
            row = db.execute("SELECT admission_state,outcome FROM provider_guard_admissions WHERE admission_id=?",
                             (abandoned.admission_id,)).fetchone()
        self.assertEqual(row, ("cancelled", "owner_confirmed_abandoned_reservation"))

    def test_recovered_late_completion_preserves_the_attempt_count(self):
        config = guard_config(self.root, scope="recovered-late-completion-01", max_calls=3)
        guard = g.ProviderGuard(config)

        def recovered_before_finish(payload, timeout):
            guard.recover_abandoned_in_flight(owner_confirmed=True)
            return {"usage": {"input_tokens": 1, "output_tokens": 1}}

        with self.assertRaises(g.DispatchError) as raised:
            self.dispatch(guard, recovered_before_finish, request_id="recovered-late-completion-request-01")
        self.assertEqual(raised.exception.attempts, 1)
        self.assertEqual(raised.exception.cause.reason, "provider_admission_not_in_flight")
        self.assertEqual(raised.exception.status["calls_reserved"], 1)
        self.assertEqual(raised.exception.status["in_flight"], 0)

    def test_queued_reservation_rechecks_a_committed_latch_before_dispatch(self):
        config = guard_config(self.root, scope="queue-01", max_calls=1)
        first = g.ProviderGuard(config)
        queued = first.reserve(21, logical_request_id="queued-01")
        self.assertTrue(queued.allowed)
        self.simulate_legacy_funds_latch(config)
        started = first.start(queued)
        self.assertFalse(started.allowed)
        self.assertEqual(started.reason, "disabled_funds")
        self.assertEqual(first.status()["effective_state"], "disabled_funds")
        self.assertEqual(self.rows(config)[0][0], "blocked")

    def test_reserved_capacity_denies_without_terminal_budget_latch(self):
        config = guard_config(self.root, scope="reserved-capacity-01", max_calls=1)
        guard = g.ProviderGuard(config)
        queued = guard.reserve(21, logical_request_id="reserved-capacity-first-01")
        denied = guard.reserve(21, logical_request_id="reserved-capacity-second-01")
        self.assertTrue(queued.allowed)
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.reason, "provider_budget_reserved")
        self.assertFalse(denied.shutdown_notice)
        self.assertEqual(guard.status()["effective_state"], "ready")
        self.assertTrue(guard.start(queued).allowed)

    def test_queued_start_rechecks_a_lowered_call_budget(self):
        config = guard_config(self.root, scope="queued-call-recheck-01", max_calls=2,
                              max_in_flight=2)
        guard = g.ProviderGuard(config)
        active = guard.start(guard.reserve(21, logical_request_id="queued-call-active-01"))
        queued = guard.reserve(21, logical_request_id="queued-call-pending-01")
        self.assertTrue(active.allowed)
        self.assertTrue(queued.allowed)

        lowered = g.ProviderGuard({**config, "max_calls": 1})
        blocked = lowered.start(queued)
        self.assertFalse(blocked.allowed)
        self.assertEqual(blocked.reason, "disabled_budget")
        self.assertTrue(blocked.shutdown_notice)
        self.assertEqual(blocked.status["state_reason"], "max_calls")
        with closing(sqlite3.connect(config["state_path"])) as db:
            row = db.execute("SELECT admission_state,outcome FROM provider_guard_admissions WHERE admission_id=?",
                             (queued.admission_id,)).fetchone()
        self.assertEqual(row, ("blocked", "disabled_budget"))

    def test_queued_start_rechecks_token_capacity_after_observed_usage(self):
        config = {**guard_config(self.root, scope="queued-token-recheck-01", max_calls=8, max_in_flight=2),
                  "max_total_tokens": 1000, "per_request_token_ceiling": 100}
        guard = g.ProviderGuard(config)
        active = guard.start(guard.reserve(21, logical_request_id="queued-token-active-01"))
        queued = guard.reserve(21, logical_request_id="queued-token-pending-01")
        self.assertTrue(active.allowed)
        self.assertTrue(queued.allowed)
        first = guard._finish(active, outcome="provider_response",
                              result={"usage": {"input_tokens": 950, "output_tokens": 0}})
        self.assertEqual(first.status["effective_state"], "ready")
        blocked = guard.start(queued)
        self.assertFalse(blocked.allowed)
        self.assertEqual(blocked.reason, "provider_budget_reserved")
        self.assertEqual(guard.status()["reserved_tokens"], 950)
        with closing(sqlite3.connect(config["state_path"])) as db:
            row = db.execute("SELECT admission_state,outcome FROM provider_guard_admissions WHERE admission_id=?",
                             (queued.admission_id,)).fetchone()
        self.assertEqual(row, ("blocked", "provider_budget_reserved"))

    def test_blocked_queued_admission_does_not_consume_exposure_budget(self):
        now = [100.0]
        config = guard_config(self.root, scope="blocked-queue-budget-01", max_calls=2,
                              max_in_flight=2, retry_backoff_seconds=1)
        guard = g.ProviderGuard(config, clock=lambda: now[0])
        active = guard.start(guard.reserve(21, logical_request_id="blocked-queue-active-01"))
        queued = guard.reserve(21, logical_request_id="blocked-queue-pending-01")
        self.assertTrue(active.allowed)
        self.assertTrue(queued.allowed)
        guard._finish(active, outcome="provider_http_429",
                      failure=StubProviderError(429, "rate_limited", "blocked-queue-active-01"))
        blocked = guard.start(queued)
        self.assertFalse(blocked.allowed)
        self.assertEqual(blocked.reason, "transient_open")
        now[0] = 102.0
        reopened = guard.status()
        self.assertEqual(reopened["effective_state"], "ready")
        self.assertEqual(reopened["calls_reserved"], 1)
        self.assertEqual(sorted(row[0] for row in self.rows(config)), ["blocked", "failed"])

    def test_concurrent_workers_emit_one_durable_shutdown_notice(self):
        seed_config = guard_config(self.root, scope="notice-01", max_calls=2)
        self.dispatch(g.ProviderGuard(seed_config),
                      lambda payload, timeout: {"usage": {"input_tokens": 1, "output_tokens": 1}},
                      request_id="notice-seed-01")
        config = guard_config(self.root, scope="notice-01", max_calls=1)
        context = multiprocessing.get_context("spawn")
        ready, start, results = context.Queue(), context.Event(), context.Queue()
        processes = [context.Process(target=reserve_after_start_signal,
                                     args=(config, f"worker-{index}", ready, start, results))
                     for index in range(2)]
        try:
            for process in processes:
                process.start()
            self.assertEqual({ready.get(timeout=5), ready.get(timeout=5)}, {"worker-0", "worker-1"})
            start.set()
            outcomes = [results.get(timeout=5) for _ in processes]
            for process in processes:
                process.join(5)
                self.assertFalse(process.is_alive())
                self.assertEqual(process.exitcode, 0)
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                process.join()
            for queue in (ready, results):
                queue.close()
                queue.join_thread()
        self.assertEqual(sum(outcome[2] for outcome in outcomes), 1)
        self.assertTrue(all(outcome[:2] == ("disabled_budget", False) for outcome in outcomes))

    def test_restart_and_copied_package_share_the_owner_state(self):
        config = guard_config(self.root, scope="restart-01", max_calls=1)
        self.dispatch(g.ProviderGuard(config), lambda payload, timeout: {"usage": {"input_tokens": 1, "output_tokens": 1}})
        self.assertEqual(g.ProviderGuard(config).status()["effective_state"], "disabled_budget")

        copied = self.root / "copied-package"
        copied.mkdir()
        copied_file = copied / "provider_guard.py"
        shutil.copy2(Path(g.__file__), copied_file)
        spec = importlib.util.spec_from_file_location("copied_provider_guard", copied_file)
        copied_module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = copied_module
        spec.loader.exec_module(copied_module)
        with patch.object(copied_module, "_disposable_context_roots", return_value=()):
            copied_guard = copied_module.ProviderGuard(config)
        self.assertEqual(copied_guard.status()["effective_state"], "disabled_budget")
        with self.assertRaisesRegex(copied_module.GuardError, "disabled_budget"):
            copied_guard.dispatch({}, request_bytes=1, timeout=1,
                                  transport=lambda payload, timeout: self.fail("copied package dispatched"))

    def test_only_explicit_owner_reset_clears_a_persisted_funds_latch(self):
        config = guard_config(self.root, scope="funds-reset-01")
        guard = g.ProviderGuard(config)
        guard.status()
        self.simulate_legacy_funds_latch(config)
        restored = g.ProviderGuard(config)
        self.assertEqual(restored.status()["effective_state"], "disabled_funds")
        with self.assertRaisesRegex(g.GuardError, "provider_owner_reset_required"):
            restored.reset_funds_latch(owner_confirmed=False)
        self.assertEqual(restored.status()["effective_state"], "disabled_funds")
        self.assertEqual(restored.reset_funds_latch(owner_confirmed=True)["effective_state"], "ready")
        with self.assertRaisesRegex(g.GuardError, "provider_funds_classification_unavailable"):
            restored.record_confirmed_funds_exhaustion()

    def test_reset_cannot_revive_a_pre_latch_reserved_admission(self):
        config = guard_config(self.root, scope="funds-epoch-01")
        guard = g.ProviderGuard(config)
        queued = guard.reserve(21, logical_request_id="pre-latch-01")
        self.assertTrue(queued.allowed)
        self.simulate_legacy_funds_latch(config)
        self.assertEqual(g.ProviderGuard(config).status()["effective_state"], "disabled_funds")
        restored = g.ProviderGuard(config)
        self.assertEqual(restored.reset_funds_latch(owner_confirmed=True)["effective_state"], "ready")
        stale = restored.start(queued)
        self.assertFalse(stale.allowed)
        self.assertEqual(stale.reason, "provider_admission_epoch_invalidated")
        with closing(sqlite3.connect(config["state_path"])) as db:
            row = db.execute("""SELECT admission.admission_state,admission.outcome,epoch.state_epoch,
                                      scope.state_epoch FROM provider_guard_admissions AS admission
                               LEFT JOIN provider_guard_admission_epochs AS epoch ON epoch.admission_id=admission.admission_id
                               JOIN provider_guard_scopes AS scope ON scope.scope_id=admission.scope_id
                               WHERE admission.admission_id=?""", (queued.admission_id,)).fetchone()
        self.assertEqual(row[:2], ("blocked", "provider_admission_epoch_invalidated"))
        self.assertLess(row[2], row[3])

    def test_config_rejects_nonfinite_bounds_and_disposable_owner_paths(self):
        for key, values in (("timeout_seconds", (float("nan"), float("inf"), float("-inf"))),
                            ("retry_backoff_seconds", (float("nan"), float("inf"), float("-inf")))):
            for value in values:
                with self.subTest(key=key, value=value):
                    with self.assertRaisesRegex(g.GuardError, "provider_guard_invalid_" + key):
                        g.validate_config({**guard_config(self.root, scope="finite-" + key), key: value})
        with self.assertRaisesRegex(g.GuardError, "provider_guard_invalid_max_total_tokens"):
            g.validate_config({**guard_config(self.root, scope="oversized-token-bound-01"),
                               "max_total_tokens": g._SQLITE_INTEGER_MAX + 1,
                               "per_request_token_ceiling": 1})
        with patch.object(g, "_disposable_context_roots", self._real_disposable_context_roots):
            with self.assertRaisesRegex(g.GuardError, "provider_guard_state_in_disposable_context"):
                g.validate_config({**guard_config(self.root, scope="temp-owner-01"),
                                   "state_path": str(Path(tempfile.gettempdir()) / "provider-guard.sqlite3")})
            with patch.dict(os.environ, {"CODEX_HOME": str(self.root / "disposable-codex")}, clear=False):
                with self.assertRaisesRegex(g.GuardError, "provider_guard_state_in_disposable_context"):
                    g.validate_config({**guard_config(self.root, scope="agent-owner-01"),
                                       "state_path": str(self.root / "disposable-codex" / "provider-guard.sqlite3")})
        self.assertNotIn("retry_after_seconds",
                         g.public_failure(StubProviderError(429, retry_after_seconds=float("inf"))))
        self.assertNotIn("retry_after_seconds",
                         t.ProviderFailure(429, retry_after_seconds=float("inf")).public())

    def test_child_boundary_preserves_only_safe_error_fields(self):
        headers = Message()
        headers["x-typesafe-request-id"] = "request-safe-01"
        error = urllib.error.HTTPError("https://api.typesafe.ai/v1/systemone", 402, "bad",
                                       headers, io.BytesIO(b'{"error":{"code":"credit_exhausted"},"raw":"api_key=must-not-cross"}'))
        sink = Sink()
        with patch.object(t, "provider", side_effect=error):
            t._provider_child(sink, {}, 1)
        self.assertFalse(sink.sent[0][0])
        envelope = sink.sent[0][1]
        self.assertEqual(envelope, {"kind": "http", "status": 402, "code": "credit_exhausted",
                                    "request_id": "request-safe-01"})
        self.assertNotIn("must-not-cross", json.dumps(envelope))

    def test_malformed_and_secret_failures_keep_telescope_baseline(self):
        source = self.root / "source.py"
        source.write_text("def bounded_selection():\n    return 'candidate'\n")
        config = t.validate_config({"mode": "on", "paths": ["source.py"], "cache_seconds": 0,
                                    "provider_guard": guard_config(self.root, scope="telescope-01")})
        pool, info = t.gather(self.root, "bounded selection", [], config, 10**12)
        malformed = t.evaluate(self.root, "bounded selection", "", pool, info, config,
                               call=lambda body, timeout: {"not": "a valid response"})
        self.assertEqual(malformed["fallback"], "malformed_response")
        self.assertEqual(malformed["provider_guard"]["effective_state"], "ready")
        secret = "api_key=must-not-appear-in-output"
        failure = t.evaluate(self.root, "bounded selection", "", pool, info,
                             {**config, "provider_guard": guard_config(self.root, scope="telescope-02")},
                             call=lambda body, timeout: (_ for _ in ()).throw(OSError(secret)))
        self.assertEqual(failure["items"], malformed["items"])
        self.assertEqual(failure["fallback"], "provider_failure_or_invalid_output")
        self.assertNotIn(secret, json.dumps(failure))

    def test_unavailable_guard_state_preserves_telescope_baseline_without_dispatch(self):
        source = self.root / "source.py"
        source.write_text("def bounded_selection():\n    return 'candidate'\n")
        blocked_parent = self.root / "not-a-directory"
        blocked_parent.write_text("owner storage unavailable")
        config = t.validate_config({"mode": "on", "paths": ["source.py"], "cache_seconds": 0,
                                    "provider_guard": {**guard_config(self.root, scope="telescope-state-01"),
                                                       "state_path": str(blocked_parent / "provider.sqlite3")}})
        pool, info = t.gather(self.root, "bounded selection", [], config, 10**12)
        packet = t.evaluate(self.root, "bounded selection", "", pool, info, config,
                            call=lambda body, timeout: self.fail("unavailable guard dispatched"))
        self.assertEqual(packet["fallback"], "provider_guard_state_unavailable")
        self.assertEqual(packet["items"], t.assemble(self.root, pool,
                                                        [{"id": c["id"], "category": "baseline_match"} for c in pool],
                                                        config)["items"])
        self.assertEqual(packet["provider_guard"]["state_error"], "provider_guard_state_unavailable")

    def test_mismatched_or_off_guard_never_dispatches_telescope(self):
        source = self.root / "source.py"
        source.write_text("def bounded_selection():\n    return 'candidate'\n")
        config = t.validate_config({"mode": "on", "paths": ["source.py"], "cache_seconds": 0,
                                    "provider_guard": {"mode": "off"}})
        pool, info = t.gather(self.root, "bounded selection", [], config, 10**12)
        packet = t.evaluate(self.root, "bounded selection", "", pool, info, config,
                            call=lambda body, timeout: self.fail("mismatched guard dispatched"))
        self.assertEqual(packet["fallback"], "provider_guard_mode_mismatch")
        self.assertEqual(packet["provider_calls"], 0)
        self.assertEqual(packet["items"], t.assemble(self.root, pool,
                                                        [{"id": c["id"], "category": "baseline_match"} for c in pool],
                                                        config)["items"])

    def test_retry_admission_denial_keeps_telescope_failure_and_call_count(self):
        source = self.root / "source.py"
        source.write_text("def bounded_selection():\n    return 'candidate'\n")
        config = t.validate_config({"mode": "on", "paths": ["source.py"], "cache_seconds": 0,
                                    "provider_guard": guard_config(self.root, scope="telescope-retry-denied-01",
                                                                   max_calls=1, max_retries=1,
                                                                   retry_backoff_seconds=0)})
        pool, info = t.gather(self.root, "bounded selection", [], config, 10**12)
        calls = []

        def rate_limited(body, timeout):
            calls.append(timeout)
            raise t.ProviderFailure(429, "rate_limited", "telescope-retry-denied-01")

        packet = t.evaluate(self.root, "bounded selection", "", pool, info, config, call=rate_limited)
        self.assertEqual(len(calls), 1)
        self.assertEqual(packet["fallback"], "provider_http_429")
        self.assertEqual(packet["provider_calls"], 1)
        self.assertEqual(packet["provider_error"], {"status": 429, "code": "rate_limited",
                                                      "request_id": "telescope-retry-denied-01"})
        self.assertEqual(packet["provider_guard"]["effective_state"], "disabled_budget")


if __name__ == "__main__":
    unittest.main()
