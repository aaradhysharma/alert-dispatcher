"""
SQLite-backed retry queue for failed email sends.

The big picture:
    When the email provider raises an error, the dispatch service does
    NOT try again on the same request (that would slow down the API
    response). Instead, we INSERT a row into a SQLite table. Later,
    a separate worker process can read the table and retry.

    In this exercise we only build the table + the "record a failure"
    function + helpers a worker would use. The worker itself is NOT
    implemented (described in SUBMISSION.md).

Why SQLite:
    - Survives process restart (unlike an in-memory list).
    - Comes with Python's standard library (`import sqlite3`), so we
      don't have to add a dependency to pyproject.toml (which is
      locked).
    - Easy to inspect from a terminal:
          sqlite3 alert_dispatcher.db "select * from email_retry_queue;"

Backoff (when to retry next):
    For this exercise we use a simple fixed delay of 60 seconds.
    A real implementation would use exponential backoff with jitter.
    The change point is `_DEFAULT_BACKOFF_SECONDS` below.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

# The path to the SQLite file. It's a module-level variable (not a
# constant) so tests can swap it for a temp file via set_db_path().
_DB_PATH: str = "alert_dispatcher.db"

# How long after a failure before the worker should try again.
# Fixed for now; see module docstring.
_DEFAULT_BACKOFF_SECONDS = 60

# How many total attempts before a row is marked "exhausted".
# Defined here in code, not in env, on purpose: we are NOT allowed to
# touch settings.py / .env.example for this exercise.
DEFAULT_MAX_ATTEMPTS = 5


def set_db_path(path: str) -> None:
    """Override the SQLite file path. Used by tests to isolate state."""
    global _DB_PATH
    _DB_PATH = path


def get_db_path() -> str:
    """Return the current DB path. Used by tests for direct queries."""
    return _DB_PATH


# Helper that opens a connection, hands it to the caller, then commits
# and closes. The `@contextmanager` decorator lets us use it like:
#     with _connect() as conn:
#         conn.execute(...)
# which is shorter than open/try/commit/close every time.
@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_DB_PATH)
    # row_factory=Row lets us access columns by name: row["user_id"]
    # instead of row[1]. Easier to read.
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create the table and index if they don't exist.

    Safe to call on every app startup ("CREATE TABLE IF NOT EXISTS").
    main.py calls this once via FastAPI's lifespan hook.
    """
    with _connect() as conn:
        # Triple-quoted string: the SQL is multiple statements, so we
        # use executescript() instead of execute().
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

            -- Index helps a future worker quickly find rows that are
            -- pending AND due to be retried. Without it, the worker
            -- would have to scan the whole table.
            CREATE INDEX IF NOT EXISTS idx_email_retry_status_next
                ON email_retry_queue(status, next_attempt_at);
            """
        )


def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO-8601 string.

    SQLite has no native timestamp type, so we store timestamps as
    text. ISO-8601 sorts correctly as a string, which is the only
    thing we need for the "find rows due to retry" query.
    """
    return datetime.now(UTC).isoformat()


def record_email_failure(
    user_id: str,
    recipient: str,
    subject: str,
    body: str,
    error_message: str,
    *,                           # everything after * must be passed by keyword
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> int:
    """Persist a failed email send. Returns the new row id.

    `attempts` starts at 1 because the failure already happened once;
    we are recording the attempt that just failed, not a future one.

    `error_message` is truncated to 500 chars as a safety net: the
    upstream provider's error string MUST NOT contain the API key, but
    we'd rather chop it short than risk leaking something we missed.
    """
    now = datetime.now(UTC)
    next_at = (now + timedelta(seconds=_DEFAULT_BACKOFF_SECONDS)).isoformat()
    now_iso = now.isoformat()

    # Belt-and-braces truncation. (error_message or "") handles the
    # weird case where someone passed None.
    truncated_error = (error_message or "")[:500]

    with _connect() as conn:
        # The "?" placeholders are how sqlite3 handles parameter
        # binding safely. NEVER build SQL with f-strings -- that's
        # how SQL injection happens.
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
                now_iso,    # last_attempt_at == created_at on first insert
                next_at,
            ),
        )
        # lastrowid can technically be None per the type stubs, hence
        # the `or 0` fallback. In practice it always returns the new id.
        return int(cur.lastrowid or 0)


def list_due() -> list[sqlite3.Row]:
    """Return rows that a worker should retry now.

    Used by the future worker (not by the live HTTP path).
    """
    with _connect() as conn:
        cur = conn.execute(
            "SELECT * FROM email_retry_queue "
            "WHERE status = 'pending' AND next_attempt_at <= ? "
            "ORDER BY next_attempt_at",
            (_utcnow_iso(),),
        )
        return list(cur.fetchall())


def mark_succeeded(row_id: int) -> None:
    """Worker says: this row's retry finally worked. Stop trying."""
    with _connect() as conn:
        conn.execute(
            "UPDATE email_retry_queue "
            "SET status = 'succeeded', last_attempt_at = ? "
            "WHERE id = ?",
            (_utcnow_iso(), row_id),
        )


def mark_exhausted(row_id: int) -> None:
    """Worker says: too many attempts, give up on this row."""
    with _connect() as conn:
        conn.execute(
            "UPDATE email_retry_queue "
            "SET status = 'exhausted', last_attempt_at = ? "
            "WHERE id = ?",
            (_utcnow_iso(), row_id),
        )


def bump_attempt(row_id: int, error_message: str, next_attempt_at: str) -> None:
    """Worker says: tried again, still failed. Reschedule.

    The worker computes the new `next_attempt_at` (so it can choose its
    own backoff strategy) and passes it in.
    """
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
