#!/usr/bin/env python3
"""Credential-free, local durable admission for optional provider requests.

The guard deliberately owns no credential, HTTP client, or provider-specific funds
classifier.  It accepts a callable transport only after recording admission in an
owner-selected SQLite file.  That makes the same guard usable by Telescope and a
future optional integration without making either one a background service.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import math
import os
import re
import sqlite3
import tempfile
import time
from typing import Any, Callable, Iterator
import uuid


MODES = {"off", "shadow", "on"}
STATES = {"ready", "disabled_funds", "disabled_budget", "auth_error", "transient_open"}
# TypeSafe's current public API documents authentication, validation, 429 rate
# limiting, and 529 overload, but no exhausted-credit/prepaid-expiry contract.
# Never turn an undocumented code (especially 429) into this latch.
FUNDS_CLASSIFICATION = "unavailable_no_authoritative_provider_contract"
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_SQLITE_INTEGER_MAX = (1 << 63) - 1

DEFAULTS = {
    "mode": "off",
    "scope_id": None,
    "state_path": None,
    "max_calls": None,
    "max_request_bytes": None,
    "max_in_flight": None,
    "timeout_seconds": None,
    "max_retries": None,
    "retry_backoff_seconds": None,
    "max_total_tokens": None,
    "per_request_token_ceiling": None,
}
_REQUIRED_ENABLED = (
    "scope_id", "state_path", "max_calls", "max_request_bytes", "max_in_flight",
    "timeout_seconds", "max_retries", "retry_backoff_seconds",
)


class GuardError(ValueError):
    """A safe, caller-facing guard failure.  Its reason never contains request data."""

    def __init__(self, reason: str, status: dict[str, Any] | None = None):
        self.reason = reason
        self.status = dict(status or {})
        super().__init__(reason)


class DispatchError(GuardError):
    """A transport error after one or more durable admissions."""

    def __init__(self, cause: Exception, attempts: int, status: dict[str, Any]):
        self.cause = cause
        self.attempts = attempts
        super().__init__(failure_reason(cause), status)


@dataclass(frozen=True)
class Admission:
    admission_id: str | None
    logical_request_id: str | None
    allowed: bool
    reason: str | None
    status: dict[str, Any]
    shutdown_notice: bool = False


@dataclass(frozen=True)
class DispatchResult:
    value: Any
    attempts: int
    status: dict[str, Any]
    shutdown_notice: bool = False


@dataclass(frozen=True)
class _Outcome:
    status: dict[str, Any]
    shutdown_notice: bool
    retry: bool = False
    backoff_seconds: float = 0.0
    post_dispatch_failure: str | None = None


def _integer(value: Any, name: str, minimum: int) -> int:
    if type(value) is not int or value < minimum or value > _SQLITE_INTEGER_MAX:
        raise GuardError(f"provider_guard_invalid_{name}")
    return value


def _number(value: Any, name: str, minimum: float) -> float:
    if type(value) not in (int, float) or isinstance(value, bool):
        raise GuardError(f"provider_guard_invalid_{name}")
    try:
        number = float(value)
    except OverflowError as error:
        raise GuardError(f"provider_guard_invalid_{name}") from error
    if not math.isfinite(number) or number < minimum:
        raise GuardError(f"provider_guard_invalid_{name}")
    return number


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise GuardError(f"provider_guard_invalid_{name}")
    return value


def _disposable_context_roots() -> tuple[Path, ...]:
    """Known local roots whose lifecycle cannot own durable paid-admission state."""
    locations = [tempfile.gettempdir()]
    locations.extend(value for name in ("TMPDIR", "TMP", "TEMP", "XDG_RUNTIME_DIR", "DE67_RUNNER_ACTIVE_DIR")
                     if (value := os.environ.get(name)))
    locations.append(os.environ.get("CODEX_HOME") or str(Path.home() / ".codex"))
    roots: list[Path] = []
    for location in locations:
        try:
            root = Path(location).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        if root not in roots:
            roots.append(root)
    return tuple(roots)


def validate_config(value: Any) -> dict[str, Any]:
    """Validate explicit owner configuration without supplying paid-mode limits."""
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise GuardError("unknown_provider_guard_configuration")
    config = {**DEFAULTS, **value}
    if config["mode"] not in MODES:
        raise GuardError("provider_guard_invalid_mode")
    if config["mode"] == "off":
        return config
    missing = [name for name in _REQUIRED_ENABLED if name not in value]
    if missing:
        raise GuardError("provider_guard_missing_" + "_".join(missing))
    config["scope_id"] = _identifier(config["scope_id"], "scope_id")
    if not isinstance(config["state_path"], str) or not config["state_path"]:
        raise GuardError("provider_guard_invalid_state_path")
    state_path = Path(config["state_path"])
    if not state_path.is_absolute():
        raise GuardError("provider_guard_state_path_must_be_absolute")
    try:
        state_path = state_path.resolve()
    except (OSError, RuntimeError) as error:
        raise GuardError("provider_guard_invalid_state_path") from error
    package_dir = Path(__file__).resolve().parent
    if state_path.is_relative_to(package_dir):
        raise GuardError("provider_guard_state_inside_package")
    if any(state_path.is_relative_to(root) for root in _disposable_context_roots()):
        raise GuardError("provider_guard_state_in_disposable_context")
    config["state_path"] = str(state_path)
    config["max_calls"] = _integer(config["max_calls"], "max_calls", 0)
    config["max_request_bytes"] = _integer(config["max_request_bytes"], "max_request_bytes", 1)
    config["max_in_flight"] = _integer(config["max_in_flight"], "max_in_flight", 1)
    config["timeout_seconds"] = _number(config["timeout_seconds"], "timeout_seconds", 0.000001)
    config["max_retries"] = _integer(config["max_retries"], "max_retries", 0)
    config["retry_backoff_seconds"] = _number(config["retry_backoff_seconds"], "retry_backoff_seconds", 0)
    if config["max_total_tokens"] is None and config["per_request_token_ceiling"] is not None:
        raise GuardError("provider_guard_token_ceiling_without_total")
    if config["max_total_tokens"] is not None:
        config["max_total_tokens"] = _integer(config["max_total_tokens"], "max_total_tokens", 0)
        if "per_request_token_ceiling" not in value:
            raise GuardError("provider_guard_missing_per_request_token_ceiling")
        config["per_request_token_ceiling"] = _integer(
            config["per_request_token_ceiling"], "per_request_token_ceiling", 1)
    return config


def _safe_text(value: Any) -> str | None:
    return value if isinstance(value, str) and _IDENTIFIER.fullmatch(value) else None


def public_failure(error: BaseException) -> dict[str, Any]:
    """Project only documented, nonsecret error fields; never stringify the body/error."""
    fields: dict[str, Any] = {}
    status = getattr(error, "status", None)
    if type(status) is int and 100 <= status <= 599:
        fields["status"] = status
    code = _safe_text(getattr(error, "code", None))
    if code is not None:
        fields["code"] = code
    request_id = _safe_text(getattr(error, "request_id", None))
    if request_id is not None:
        fields["request_id"] = request_id
    retry_after_seconds = getattr(error, "retry_after_seconds", None)
    if type(retry_after_seconds) in (int, float) and not isinstance(retry_after_seconds, bool):
        try:
            retry_after_seconds = float(retry_after_seconds)
        except OverflowError:
            retry_after_seconds = None
        if retry_after_seconds is not None and math.isfinite(retry_after_seconds) and retry_after_seconds >= 0:
            fields["retry_after_seconds"] = retry_after_seconds
    return fields


def failure_reason(error: BaseException) -> str:
    if isinstance(error, TimeoutError):
        return "provider_timeout"
    status = public_failure(error).get("status")
    return f"provider_http_{status}" if status is not None else "provider_failure"


def failure_class(error: BaseException) -> str:
    if isinstance(error, TimeoutError):
        return "transient"
    status = public_failure(error).get("status")
    if status in {401, 403}:
        return "auth"
    if status in {429, 529}:
        return "transient"
    # Funds stay intentionally unavailable until a provider documents a safe code.
    return "other"


class ProviderGuard:
    """Scope-bound admissions in a local SQLite owner selected by configuration."""

    def __init__(self, config: dict[str, Any] | None, *, clock: Callable[[], float] = time.time,
                 sleeper: Callable[[float], None] = time.sleep):
        self.config = validate_config(config)
        self._clock = clock
        self._sleeper = sleeper

    @property
    def enabled(self) -> bool:
        return self.config["mode"] != "off"

    @property
    def state_path(self) -> Path:
        return Path(self.config["state_path"])

    def _off_status(self) -> dict[str, Any]:
        return {"mode": "off", "effective_state": "ready",
                "funds_classification": FUNDS_CLASSIFICATION, "shutdown_notice": False}

    def _state_unavailable_status(self) -> dict[str, Any]:
        """Describe a storage failure without guessing a durable effective state."""
        return {"mode": self.config["mode"], "scope_id": self.config["scope_id"],
                "state_error": "provider_guard_state_unavailable",
                "funds_classification": FUNDS_CLASSIFICATION, "shutdown_notice": False}

    def _connect(self) -> sqlite3.Connection:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(str(self.state_path), timeout=5, isolation_level=None)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA foreign_keys=ON")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS provider_guard_scopes(
                    scope_id TEXT PRIMARY KEY,
                    effective_state TEXT NOT NULL,
                    state_reason TEXT,
                    retry_not_before REAL,
                    state_epoch INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS provider_guard_admissions(
                    admission_id TEXT PRIMARY KEY,
                    scope_id TEXT NOT NULL REFERENCES provider_guard_scopes(scope_id),
                    logical_request_id TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    parent_admission_id TEXT,
                    admission_state TEXT NOT NULL,
                    request_bytes INTEGER NOT NULL,
                    reserved_tokens INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    dispatched_at REAL,
                    finished_at REAL,
                    outcome TEXT,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    provider_status INTEGER,
                    provider_code TEXT,
                    provider_request_id TEXT,
                    UNIQUE(scope_id, logical_request_id, attempt)
                );
                CREATE TABLE IF NOT EXISTS provider_guard_admission_epochs(
                    admission_id TEXT PRIMARY KEY REFERENCES provider_guard_admissions(admission_id),
                    scope_id TEXT NOT NULL REFERENCES provider_guard_scopes(scope_id),
                    state_epoch INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS provider_guard_admissions_scope_state
                    ON provider_guard_admissions(scope_id, admission_state);
                CREATE TABLE IF NOT EXISTS provider_guard_notices(
                    scope_id TEXT NOT NULL REFERENCES provider_guard_scopes(scope_id),
                    state_epoch INTEGER NOT NULL,
                    effective_state TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(scope_id, state_epoch, effective_state)
                );
            """)
            return db
        except (OSError, sqlite3.Error) as error:
            try:
                db.close()
            except UnboundLocalError:
                pass
            raise GuardError("provider_guard_state_unavailable", self._state_unavailable_status()) from error

    @contextmanager
    def _locked(self) -> Iterator[sqlite3.Connection]:
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            now = self._clock()
            db.execute("""INSERT OR IGNORE INTO provider_guard_scopes
                       (scope_id,effective_state,state_reason,retry_not_before,state_epoch,created_at,updated_at)
                       VALUES (?, 'ready', NULL, NULL, 0, ?, ?)""",
                       (self.config["scope_id"], now, now))
            yield db
            db.commit()
        except GuardError:
            try:
                db.rollback()
            except sqlite3.Error:
                pass
            raise
        except (OSError, sqlite3.Error) as error:
            try:
                db.rollback()
            except sqlite3.Error:
                pass
            raise GuardError("provider_guard_state_unavailable", self._state_unavailable_status()) from error
        except Exception:
            try:
                db.rollback()
            except sqlite3.Error:
                pass
            raise
        finally:
            db.close()

    def _scope(self, db: sqlite3.Connection) -> sqlite3.Row:
        row = db.execute("SELECT * FROM provider_guard_scopes WHERE scope_id=?", (self.config["scope_id"],)).fetchone()
        if row is None:  # _locked always creates it; retain a safe invariant if storage changes underneath us.
            raise GuardError("provider_guard_state_unavailable")
        return row

    def _transition(self, db: sqlite3.Connection, state: str, reason: str | None = None,
                    retry_not_before: float | None = None) -> bool:
        if state not in STATES:
            raise GuardError("provider_guard_invalid_state")
        row = self._scope(db)
        if row["effective_state"] == state and row["state_reason"] == reason and row["retry_not_before"] == retry_not_before:
            return False
        now = self._clock()
        epoch = row["state_epoch"] + 1
        db.execute("""UPDATE provider_guard_scopes
                   SET effective_state=?, state_reason=?, retry_not_before=?, state_epoch=?, updated_at=?
                   WHERE scope_id=?""", (state, reason, retry_not_before, epoch, now, self.config["scope_id"]))
        if state not in {"disabled_funds", "disabled_budget"}:
            return False
        cursor = db.execute("""INSERT OR IGNORE INTO provider_guard_notices
                             (scope_id,state_epoch,effective_state,created_at) VALUES (?,?,?,?)""",
                            (self.config["scope_id"], epoch, state, now))
        return cursor.rowcount == 1

    def _refresh_transient(self, db: sqlite3.Connection) -> None:
        row = self._scope(db)
        if (row["effective_state"] == "transient_open" and row["retry_not_before"] is not None
                and row["retry_not_before"] <= self._clock()):
            self._transition(db, "ready")

    def _totals(self, db: sqlite3.Connection) -> dict[str, int]:
        """Aggregate token charges in Python so a conservative saturation cannot overflow SQLite SUM()."""
        counts = db.execute("""
            SELECT COUNT(*) AS calls_reserved,
                   COUNT(CASE WHEN admission_state='completed' THEN 1 END) AS calls_completed,
                   COUNT(CASE WHEN admission_state='in_flight' THEN 1 END) AS in_flight,
                   COUNT(CASE WHEN admission_state != 'reserved' THEN 1 END) AS calls_exposed
            FROM provider_guard_admissions
            WHERE scope_id=? AND admission_state NOT IN ('cancelled', 'blocked')
        """, (self.config["scope_id"],)).fetchone()
        charges = db.execute("""
            SELECT admission_state,reserved_tokens,input_tokens,output_tokens
            FROM provider_guard_admissions
            WHERE scope_id=? AND admission_state NOT IN ('cancelled', 'blocked')
        """, (self.config["scope_id"],)).fetchall()
        return {
            "calls_reserved": counts["calls_reserved"] or 0,
            "calls_completed": counts["calls_completed"] or 0,
            "in_flight": counts["in_flight"] or 0,
            "calls_exposed": counts["calls_exposed"] or 0,
            "reserved_tokens": sum(row["reserved_tokens"] for row in charges),
            "exposed_tokens": sum(row["reserved_tokens"] for row in charges
                                  if row["admission_state"] != "reserved"),
            "input_tokens": sum(row["input_tokens"] or 0 for row in charges),
            "output_tokens": sum(row["output_tokens"] or 0 for row in charges),
        }

    def _budget_reason(self, db: sqlite3.Connection) -> str | None:
        totals = self._totals(db)
        if totals["calls_exposed"] >= self.config["max_calls"]:
            return "max_calls"
        maximum = self.config["max_total_tokens"]
        if maximum is not None and totals["exposed_tokens"] >= maximum:
            return "max_total_tokens"
        return None

    def _enforce_budget(self, db: sqlite3.Connection) -> bool:
        row = self._scope(db)
        if row["effective_state"] != "ready":
            return False
        reason = self._budget_reason(db)
        if reason is not None:
            return self._transition(db, "disabled_budget", reason)
        return False

    def _status(self, db: sqlite3.Connection) -> dict[str, Any]:
        row, totals = self._scope(db), self._totals(db)
        return {
            "mode": self.config["mode"],
            "scope_id": self.config["scope_id"],
            "effective_state": row["effective_state"],
            "state_reason": row["state_reason"],
            "state_epoch": row["state_epoch"],
            "retry_not_before": row["retry_not_before"] if row["effective_state"] == "transient_open" else None,
            "calls_reserved": totals["calls_reserved"] or 0,
            "calls_completed": totals["calls_completed"] or 0,
            "in_flight": totals["in_flight"] or 0,
            "reserved_tokens": totals["reserved_tokens"] or 0,
            "input_tokens": totals["input_tokens"] or 0,
            "output_tokens": totals["output_tokens"] or 0,
            "funds_classification": FUNDS_CLASSIFICATION,
        }

    def _status_result(self, db: sqlite3.Connection, shutdown_notice: bool = False) -> dict[str, Any]:
        """Attach this operation's one-time terminal-budget observation to its status."""
        return {**self._status(db), "shutdown_notice": bool(shutdown_notice)}

    def status(self) -> dict[str, Any]:
        if not self.enabled:
            return self._off_status()
        with self._locked() as db:
            self._refresh_transient(db)
            notice = self._enforce_budget(db)
            return self._status_result(db, notice)

    def _local_request_id(self, value: str | None) -> str:
        return _identifier(value, "request_id") if value is not None else "local-" + uuid.uuid4().hex

    def reserve(self, request_bytes: int, *, logical_request_id: str | None = None, attempt: int = 0,
                parent_admission_id: str | None = None) -> Admission:
        """Reserve a potential dispatch; callers must still call ``start`` before transport."""
        if not self.enabled:
            return Admission(None, None, False, "provider_guard_off", self._off_status())
        _integer(request_bytes, "request_bytes", 0)
        _integer(attempt, "attempt", 0)
        logical_request_id = self._local_request_id(logical_request_id)
        if parent_admission_id is not None:
            _identifier(parent_admission_id, "parent_admission_id")
        if request_bytes > self.config["max_request_bytes"]:
            status = self.status()
            return Admission(None, logical_request_id, False, "provider_request_exceeds_bound", status,
                             bool(status.get("shutdown_notice")))
        reserved_tokens = self.config["per_request_token_ceiling"] or 0
        with self._locked() as db:
            self._refresh_transient(db)
            notice = self._enforce_budget(db)
            status = self._status_result(db, notice)
            if status["effective_state"] != "ready":
                return Admission(None, logical_request_id, False, status["effective_state"], status, notice)
            if status["calls_reserved"] >= self.config["max_calls"]:
                return Admission(None, logical_request_id, False, "provider_budget_reserved", status, notice)
            if (self.config["max_total_tokens"] is not None
                    and status["reserved_tokens"] + reserved_tokens > self.config["max_total_tokens"]):
                return Admission(None, logical_request_id, False, "provider_budget_reserved", status, notice)
            admission_id = "admission-" + uuid.uuid4().hex
            now = self._clock()
            db.execute("""INSERT INTO provider_guard_admissions
                       (admission_id,scope_id,logical_request_id,attempt,parent_admission_id,admission_state,
                        request_bytes,reserved_tokens,created_at)
                       VALUES (?,?,?,?,?,'reserved',?,?,?)""",
                       (admission_id, self.config["scope_id"], logical_request_id, attempt,
                        parent_admission_id, request_bytes, reserved_tokens, now))
            db.execute("""INSERT INTO provider_guard_admission_epochs(admission_id,scope_id,state_epoch)
                       VALUES (?,?,?)""", (admission_id, self.config["scope_id"], status["state_epoch"]))
            return Admission(admission_id, logical_request_id, True, None,
                             self._status_result(db, notice), notice)

    def start(self, admission: Admission, *, deadline: float | None = None) -> Admission:
        """Re-admit immediately before dispatch; a queued reservation is never permission to send."""
        if not self.enabled or not admission.allowed or admission.admission_id is None:
            return Admission(admission.admission_id, admission.logical_request_id, False,
                             admission.reason or "provider_guard_off", self._off_status())
        with self._locked() as db:
            self._refresh_transient(db)
            notice = self._enforce_budget(db)
            row = db.execute("""SELECT admission.*, epoch.state_epoch AS admission_epoch
                              FROM provider_guard_admissions AS admission
                              LEFT JOIN provider_guard_admission_epochs AS epoch
                                ON epoch.admission_id=admission.admission_id AND epoch.scope_id=admission.scope_id
                              WHERE admission.admission_id=? AND admission.scope_id=?""",
                             (admission.admission_id, self.config["scope_id"])).fetchone()
            status = self._status_result(db, notice)
            if row is None or row["admission_state"] != "reserved":
                return Admission(admission.admission_id, admission.logical_request_id, False,
                                 "provider_admission_not_pending", status, notice)
            if status["effective_state"] != "ready":
                db.execute("UPDATE provider_guard_admissions SET admission_state='blocked', finished_at=?, outcome=? WHERE admission_id=?",
                           (self._clock(), status["effective_state"], admission.admission_id))
                return Admission(admission.admission_id, admission.logical_request_id, False,
                                 status["effective_state"], self._status_result(db, notice), notice)
            if row["admission_epoch"] != status["state_epoch"]:
                db.execute("""UPDATE provider_guard_admissions
                           SET admission_state='blocked', finished_at=?, outcome='provider_admission_epoch_invalidated'
                           WHERE admission_id=? AND scope_id=? AND admission_state='reserved'""",
                           (self._clock(), admission.admission_id, self.config["scope_id"]))
                return Admission(admission.admission_id, admission.logical_request_id, False,
                                 "provider_admission_epoch_invalidated", self._status_result(db))
            if status["in_flight"] >= self.config["max_in_flight"]:
                return Admission(admission.admission_id, admission.logical_request_id, False,
                                 "provider_concurrency_limited", status)
            maximum = self.config["max_total_tokens"]
            if maximum is not None:
                totals = self._totals(db)
                if totals["exposed_tokens"] + row["reserved_tokens"] > maximum:
                    db.execute("""UPDATE provider_guard_admissions
                               SET admission_state='blocked', finished_at=?, outcome='provider_budget_reserved'
                               WHERE admission_id=? AND scope_id=? AND admission_state='reserved'""",
                               (self._clock(), admission.admission_id, self.config["scope_id"]))
                    return Admission(admission.admission_id, admission.logical_request_id, False,
                                     "provider_budget_reserved", self._status_result(db))
            if deadline is not None and time.monotonic() >= deadline:
                db.execute("""UPDATE provider_guard_admissions
                           SET admission_state='cancelled', finished_at=?, outcome='deadline_before_dispatch'
                           WHERE admission_id=? AND scope_id=? AND admission_state='reserved'""",
                           (self._clock(), admission.admission_id, self.config["scope_id"]))
                return Admission(admission.admission_id, admission.logical_request_id, False,
                                 "provider_timeout_before_dispatch", self._status_result(db))
            db.execute("UPDATE provider_guard_admissions SET admission_state='in_flight', dispatched_at=? WHERE admission_id=?",
                       (self._clock(), admission.admission_id))
            return Admission(admission.admission_id, admission.logical_request_id, True, None,
                             self._status_result(db))

    def _cancel(self, admission: Admission) -> None:
        if admission.admission_id is None:
            return
        with self._locked() as db:
            db.execute("""UPDATE provider_guard_admissions SET admission_state='cancelled', finished_at=?, outcome='not_dispatched'
                       WHERE admission_id=? AND scope_id=? AND admission_state='reserved'""",
                       (self._clock(), admission.admission_id, self.config["scope_id"]))

    def _cancel_before_dispatch(self, admission: Admission) -> dict[str, Any]:
        """Undo a just-started admission when the local deadline elapsed before transport ran."""
        if admission.admission_id is None:
            return self.status()
        with self._locked() as db:
            cursor = db.execute("""UPDATE provider_guard_admissions
                       SET admission_state='cancelled', finished_at=?, outcome='deadline_before_dispatch'
                       WHERE admission_id=? AND scope_id=? AND admission_state='in_flight'""",
                       (self._clock(), admission.admission_id, self.config["scope_id"]))
            # A concurrent observer can latch the just-started admission at a
            # terminal budget exactly before this local deadline check.  This
            # path is the proof that transport never ran, so reopen only that
            # now-unexhausted budget state; any remaining exposure keeps it
            # latched and queued work remains conservatively invalidated.
            if (cursor.rowcount == 1 and self._scope(db)["effective_state"] == "disabled_budget"
                    and self._budget_reason(db) is None):
                self._transition(db, "ready", "pre_dispatch_cancelled")
            return self._status_result(db)

    def recover_abandoned_in_flight(self, *, owner_confirmed: bool) -> dict[str, Any]:
        """Release explicitly confirmed-dead local callers without refunding their exposure."""
        if not owner_confirmed:
            raise GuardError("provider_owner_recovery_required", self.status())
        if not self.enabled:
            raise GuardError("provider_guard_off", self._off_status())
        with self._locked() as db:
            # This is deliberately owner-confirmed rather than time-based: a
            # slow live transport can still incur usage after its timeout.
            cursor = db.execute("""UPDATE provider_guard_admissions
                               SET admission_state='unknown', finished_at=?, outcome='owner_confirmed_abandoned'
                               WHERE scope_id=? AND admission_state='in_flight'""",
                                (self._clock(), self.config["scope_id"]))
            notice = self._enforce_budget(db)
            return {**self._status_result(db, notice), "recovered_admissions": cursor.rowcount}

    def cancel_abandoned_reservations(self, *, owner_confirmed: bool) -> dict[str, Any]:
        """Release only owner-confirmed-dead callers that never reached transport."""
        if not owner_confirmed:
            raise GuardError("provider_owner_reservation_recovery_required", self.status())
        if not self.enabled:
            raise GuardError("provider_guard_off", self._off_status())
        with self._locked() as db:
            cursor = db.execute("""UPDATE provider_guard_admissions
                               SET admission_state='cancelled', finished_at=?, outcome='owner_confirmed_abandoned_reservation'
                               WHERE scope_id=? AND admission_state='reserved'""",
                                (self._clock(), self.config["scope_id"]))
            return {**self._status_result(db), "cancelled_reservations": cursor.rowcount}

    def _finish(self, admission: Admission, *, outcome: str, result: Any | None = None,
                failure: Exception | None = None) -> _Outcome:
        if admission.admission_id is None:
            raise GuardError("provider_admission_missing")
        classification = failure_class(failure) if failure is not None else "success"
        fields = public_failure(failure) if failure is not None else {}
        usage = result.get("usage") if isinstance(result, dict) else None
        input_tokens = usage.get("input_tokens") if isinstance(usage, dict) else None
        output_tokens = usage.get("output_tokens") if isinstance(usage, dict) else None
        usage_unrepresentable = any(type(value) is int and value > _SQLITE_INTEGER_MAX
                                    for value in (input_tokens, output_tokens))
        if type(input_tokens) is not int or input_tokens < 0 or input_tokens > _SQLITE_INTEGER_MAX:
            input_tokens = None
        if type(output_tokens) is not int or output_tokens < 0 or output_tokens > _SQLITE_INTEGER_MAX:
            output_tokens = None
        observed_tokens = sum(value for value in (input_tokens, output_tokens) if value is not None)
        if observed_tokens > _SQLITE_INTEGER_MAX:
            usage_unrepresentable = True
        if usage_unrepresentable:
            # Keep the transport attempt durable and conservatively charged even
            # when a provider value cannot fit SQLite's signed INTEGER columns.
            input_tokens = output_tokens = None
            observed_tokens = _SQLITE_INTEGER_MAX
        with self._locked() as db:
            state = "unknown" if usage_unrepresentable or (classification == "transient" and isinstance(failure, TimeoutError)) else (
                "failed" if failure is not None else "completed")
            recorded_outcome = "provider_usage_unrepresentable" if usage_unrepresentable else outcome
            cursor = db.execute("""UPDATE provider_guard_admissions
                       SET admission_state=?, finished_at=?, outcome=?, input_tokens=?, output_tokens=?,
                           reserved_tokens=CASE WHEN reserved_tokens>? THEN reserved_tokens ELSE ? END,
                           provider_status=?, provider_code=?, provider_request_id=?
                       WHERE admission_id=? AND scope_id=? AND admission_state='in_flight'""",
                       (state, self._clock(), recorded_outcome, input_tokens, output_tokens, observed_tokens,
                        observed_tokens, fields.get("status"), fields.get("code"), fields.get("request_id"),
                        admission.admission_id, self.config["scope_id"]))
            if cursor.rowcount != 1:
                raise GuardError("provider_admission_not_in_flight", self._status_result(db))
            scope = self._scope(db)
            current = scope["effective_state"]
            notice = False
            retry, backoff = False, 0.0
            if classification == "auth" and current in {"ready", "transient_open"}:
                self._transition(db, "auth_error", "provider_authentication")
            elif classification == "transient":
                advertised = fields.get("retry_after_seconds")
                configured = self.config["retry_backoff_seconds"]
                # A provider-advertised retry wait is a minimum, not a cap.  The
                # owner-selected backoff can be more conservative, but neither
                # setting may cause us to retry before the provider permits it.
                backoff = max(configured, advertised) if advertised is not None else configured
                retry_not_before = self._clock() + backoff
                if current == "ready":
                    self._transition(db, "transient_open", failure_reason(failure), retry_not_before)
                    retry = True
                elif (current == "transient_open"
                      and (scope["retry_not_before"] is None or retry_not_before > scope["retry_not_before"])):
                    # Concurrent in-flight calls may finish in either order;
                    # a later provider-directed wait can only extend the latch.
                    self._transition(db, "transient_open", failure_reason(failure), retry_not_before)
            elif current == "ready":
                notice = self._enforce_budget(db)
            return _Outcome(self._status_result(db, notice), notice, retry, backoff,
                            "provider_usage_unrepresentable" if usage_unrepresentable else None)

    def dispatch(self, payload: Any, *, request_bytes: int, timeout: float,
                 transport: Callable[[Any, float], Any], logical_request_id: str | None = None) -> DispatchResult:
        """Call ``transport`` only after durable reserve/start; retryable attempts re-enter both steps."""
        if not self.enabled:
            raise GuardError("provider_guard_off", self._off_status())
        timeout = _number(timeout, "dispatch_timeout", 0.000001)
        deadline = time.monotonic() + min(timeout, self.config["timeout_seconds"])
        parent_admission_id: str | None = None
        attempts = 0
        last_failure: Exception | None = None
        for attempt in range(self.config["max_retries"] + 1):
            try:
                admission = self.reserve(request_bytes, logical_request_id=logical_request_id, attempt=attempt,
                                         parent_admission_id=parent_admission_id)
            except GuardError as admission_error:
                if last_failure is not None:
                    raise DispatchError(last_failure, attempts, admission_error.status) from None
                raise
            if not admission.allowed:
                if last_failure is not None:
                    raise DispatchError(last_failure, attempts, admission.status) from None
                raise GuardError(admission.reason or "provider_admission_denied", admission.status)
            try:
                started = self.start(admission, deadline=deadline)
            except GuardError as admission_error:
                if last_failure is not None:
                    raise DispatchError(last_failure, attempts, admission_error.status) from None
                raise
            if not started.allowed:
                try:
                    self._cancel(admission)
                except GuardError as cancellation_error:
                    if last_failure is not None:
                        raise DispatchError(last_failure, attempts, cancellation_error.status) from None
                    raise
                if last_failure is not None:
                    raise DispatchError(last_failure, attempts, started.status) from None
                raise GuardError(started.reason or "provider_admission_denied", started.status)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                try:
                    status = self._cancel_before_dispatch(started)
                except GuardError as admission_error:
                    if last_failure is not None:
                        raise DispatchError(last_failure, attempts, admission_error.status) from None
                    raise
                if last_failure is not None:
                    raise DispatchError(last_failure, attempts, status) from None
                raise GuardError("provider_timeout_before_dispatch", status)
            attempts += 1
            try:
                value = transport(payload, remaining)
            except Exception as error:
                last_failure = error
                try:
                    outcome = self._finish(started, outcome=failure_reason(error), failure=error)
                except GuardError as finish_error:
                    # The transport already ran, even if a concurrent owner
                    # recovery or state failure prevents its final record.
                    raise DispatchError(error, attempts, finish_error.status) from None
                if outcome.retry and attempt < self.config["max_retries"]:
                    remaining = deadline - time.monotonic()
                    # Reaching the caller's deadline leaves no time for an
                    # actual retry.  Keep the durable transient latch intact
                    # instead of shortening a provider-directed wait.
                    if outcome.backoff_seconds < remaining:
                        if outcome.backoff_seconds > 0:
                            self._sleeper(outcome.backoff_seconds)
                        if time.monotonic() < deadline:
                            parent_admission_id = started.admission_id
                            continue
                raise DispatchError(error, attempts, outcome.status) from None
            try:
                outcome = self._finish(started, outcome="provider_response", result=value)
            except GuardError as finish_error:
                raise DispatchError(finish_error, attempts, finish_error.status) from None
            if outcome.post_dispatch_failure is not None:
                raise DispatchError(GuardError(outcome.post_dispatch_failure, outcome.status), attempts,
                                    outcome.status) from None
            return DispatchResult(value, attempts, outcome.status, outcome.shutdown_notice)
        raise GuardError("provider_retry_exhausted", self.status())

    def record_confirmed_funds_exhaustion(self) -> None:
        """Reserved for a future documented contract; it must not infer funds from current errors."""
        raise GuardError("provider_funds_classification_unavailable", self.status())

    def reset_funds_latch(self, *, owner_confirmed: bool) -> dict[str, Any]:
        """Only an explicit owner action may clear a persisted funding latch."""
        if not owner_confirmed:
            raise GuardError("provider_owner_reset_required", self.status())
        if not self.enabled:
            raise GuardError("provider_guard_off", self._off_status())
        with self._locked() as db:
            row = self._scope(db)
            if row["effective_state"] == "disabled_funds":
                self._transition(db, "ready", "owner_reset")
            return self._status_result(db)

    def reset_auth_latch(self, *, owner_confirmed: bool) -> dict[str, Any]:
        """Require an explicit owner confirmation before retrying after corrected credentials."""
        if not owner_confirmed:
            raise GuardError("provider_owner_auth_reset_required", self.status())
        if not self.enabled:
            raise GuardError("provider_guard_off", self._off_status())
        with self._locked() as db:
            row = self._scope(db)
            if row["effective_state"] == "auth_error":
                self._transition(db, "ready", "owner_auth_reset")
            return self._status_result(db)


def guarded_dispatch(config: dict[str, Any] | None, payload: Any, *, request_bytes: int, timeout: float,
                     transport: Callable[[Any, float], Any], logical_request_id: str | None = None) -> DispatchResult:
    """Convenience boundary for adapters that do not need to retain a guard instance."""
    return ProviderGuard(config).dispatch(payload, request_bytes=request_bytes, timeout=timeout,
                                          transport=transport, logical_request_id=logical_request_id)
