"""SQLite-backed retry queue for failed email sends.

Why SQLite (and only stdlib `sqlite3`):
  - Restart-durable, which is the whole point of a retry queue.
  - Zero new dependencies (`pyproject.toml` is locked).
  - Trivially inspectable in a review session (`sqlite3 alert_dispatcher.db`).

What lives here:
  - The schema (one table) and an idempotent `init_db()`.
  - `record_email_failure(...)` -- the only function called from the
    live HTTP path. Kept tiny so it does not slow the response.
  - `list_due()`, `mark_succeeded()`, `mark_exhausted()`, `bump_attempt()`
    -- helpers for a future background worker. The worker itself is
    intentionally NOT implemented in this exercise; SUBMISSION.md
    describes its semantics.

Backoff is a fixed 60s for v1. A real implementation would use
exponential backoff with jitter -- noted in SUBMISSION.md.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

# Default DB path. Tests override this with `set_db_path(tmp)` so each
# test runs against an isolated file.
_DB_PATH: str = "alert_dispatcher.db"

# Fixed backoff window for the exercise. Documented in SUBMISSION.md.
_DEFAULT_BACKOFF_SECONDS = 60

# Cap on attempts before a row is moved to status='exhausted'. Defined
# in code (not env) deliberately, so we don't need to touch settings.py
# (which is locked) or .env.example.
DEFAULT_MAX_ATTEMPTS = 5


def set_db_path(path: str) -> None:
    """Override the SQLite file path. Used by tests to isolate state."""
    global _DB_PATH
    _DB_PATH = path


def get_db_path() -> str:
    return _DB_PATH


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """Short-lived connection. We open/close per call to keep the
    SQLite footprint trivial; this service is low-QPS by design.
    """
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create the retry table and supporting index if they don't exist.

    Idempotent: safe to call on every app startup.
    """
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS email_retry_queue (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         TEXT    NOT NULL,
                recipient       TEXT    NOT NULL,
                subject         TEXT    NOT NULL,
                body            TEXT    NOT NULL,
                error_message   TEXT    NOT NULL,
                attempts        INTEGER NOT NULL DEFAULT 1,
                max_attempts    INTEGER NOT NULL DEFAULT 5,
                status          TEXT    NOT NULL DEFAULT 'pending',
                created_at      TEXT    NOT NULL,
                last_attempt_at TEXT    NOT NULL,
                next_attempt_at TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_email_retry_status_next
                ON email_retry_queue(status, next_attempt_at);
            """
        )


def _utcnow_iso() -> str:
    # ISO-8601 UTC. SQLite has no native timestamp type, so we use
    # text and accept the small comparison cost; the index keeps
    # the worker scan O(log n).
    return datetime.now(UTC).isoformat()


def record_email_failure(
    user_id: str,
    recipient: str,
    subject: str,
    body: str,
    error_message: str,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> int:
    """Persist a failed email send and return the row id.

    `attempts` starts at 1 because the failure already happened once;
    we record the in-flight attempt rather than the next one.

    `error_message` is truncated to 500 chars to keep the table small
    and to bound any accidental sensitive content; the upstream
    provider must NOT include the API key in its error message, but
    truncation is a cheap defense in depth.
    """
    now = datetime.now(UTC)
    next_at = (now + timedelta(seconds=_DEFAULT_BACKOFF_SECONDS)).isoformat()
    now_iso = now.isoformat()
    truncated_error = (error_message or "")[:500]

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO email_retry_queue (
                user_id, recipient, subject, body, error_message,
                attempts, max_attempts, status,
                created_at, last_attempt_at, next_attempt_at
            ) VALUES (?, ?, ?, ?, ?, 1, ?, 'pending', ?, ?, ?)
            """,
            (
                user_id,
                recipient,
                subject,
                body,
                truncated_error,
                max_attempts,
                now_iso,
                now_iso,
                next_at,
            ),
        )
        # SQLite always assigns a non-null rowid for AUTOINCREMENT; cast
        # purely to satisfy strict type checkers.
        return int(cur.lastrowid or 0)


def list_due() -> list[sqlite3.Row]:
    """Return rows the future worker should attempt now."""
    with _connect() as conn:
        cur = conn.execute(
            "SELECT * FROM email_retry_queue "
            "WHERE status = 'pending' AND next_attempt_at <= ? "
            "ORDER BY next_attempt_at",
            (_utcnow_iso(),),
        )
        return list(cur.fetchall())


def mark_succeeded(row_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE email_retry_queue "
            "SET status = 'succeeded', last_attempt_at = ? "
            "WHERE id = ?",
            (_utcnow_iso(), row_id),
        )


def mark_exhausted(row_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE email_retry_queue "
            "SET status = 'exhausted', last_attempt_at = ? "
            "WHERE id = ?",
            (_utcnow_iso(), row_id),
        )


def bump_attempt(row_id: int, error_message: str, next_attempt_at: str) -> None:
    """Record a failed retry: increment attempts and reschedule."""
    truncated = (error_message or "")[:500]
    with _connect() as conn:
        conn.execute(
            "UPDATE email_retry_queue "
            "SET attempts = attempts + 1, "
            "    last_attempt_at = ?, "
            "    next_attempt_at = ?, "
            "    error_message = ? "
            "WHERE id = ?",
            (_utcnow_iso(), next_attempt_at, truncated, row_id),
        )
