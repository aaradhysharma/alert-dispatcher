"""
Tests for the SQLite retry queue.

We test the worker-facing helpers (list_due, mark_succeeded, etc.) too,
even though no production code calls them yet. They're part of the
documented retry contract; we want a regression net before a worker
is wired up later.
"""

import sqlite3
from datetime import UTC, datetime

from alert_dispatcher.repositories import retry as retry_repo


def _all_rows() -> list[sqlite3.Row]:
    """Read every row from the retry table.

    Helper used by several tests below. Opens its own connection (the
    repo opens/closes per call too) and returns the rows as a list.
    """
    conn = sqlite3.connect(retry_repo.get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        return list(conn.execute("SELECT * FROM email_retry_queue"))
    finally:
        conn.close()


def test_record_email_failure_inserts_row_with_expected_defaults():
    row_id = retry_repo.record_email_failure(
        user_id="user-1",
        recipient="alice@example.com",
        subject="[X] notification",
        body='{"k":"v"}',
        error_message="upstream timeout",
    )
    assert isinstance(row_id, int) and row_id > 0

    rows = _all_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row["user_id"] == "user-1"
    assert row["recipient"] == "alice@example.com"
    assert row["subject"] == "[X] notification"
    assert row["body"] == '{"k":"v"}'
    assert row["error_message"] == "upstream timeout"
    # First insert: attempts starts at 1 (we already failed once).
    assert row["attempts"] == 1
    assert row["max_attempts"] == retry_repo.DEFAULT_MAX_ATTEMPTS
    assert row["status"] == "pending"
    # All three timestamps should parse as ISO-8601. fromisoformat raises
    # if they don't, which is the assertion we want.
    datetime.fromisoformat(row["created_at"])
    datetime.fromisoformat(row["last_attempt_at"])
    datetime.fromisoformat(row["next_attempt_at"])


def test_error_message_is_truncated_to_500_chars():
    huge = "x" * 5000
    retry_repo.record_email_failure(
        user_id="user-1",
        recipient="a@b.com",
        subject="s",
        body="b",
        error_message=huge,
    )
    # Defense-in-depth against an upstream provider sending us a
    # huge error string that might contain something sensitive.
    assert len(_all_rows()[0]["error_message"]) == 500


def test_mark_succeeded_and_exhausted():
    row_id = retry_repo.record_email_failure(
        user_id="user-1",
        recipient="a@b.com",
        subject="s",
        body="b",
        error_message="e",
    )
    retry_repo.mark_succeeded(row_id)
    assert _all_rows()[0]["status"] == "succeeded"

    row_id_2 = retry_repo.record_email_failure(
        user_id="user-2",
        recipient="b@b.com",
        subject="s",
        body="b",
        error_message="e",
    )
    retry_repo.mark_exhausted(row_id_2)

    # Build a small set of statuses for just the second row.
    statuses = {r["status"] for r in _all_rows() if r["id"] == row_id_2}
    assert statuses == {"exhausted"}


def test_bump_attempt_increments_and_reschedules():
    row_id = retry_repo.record_email_failure(
        user_id="user-1",
        recipient="a@b.com",
        subject="s",
        body="b",
        error_message="first",
    )
    # Far-future timestamp so we can prove the column was written.
    future = "2099-01-01T00:00:00+00:00"
    retry_repo.bump_attempt(row_id, "second", future)

    row = _all_rows()[0]
    assert row["attempts"] == 2
    assert row["error_message"] == "second"
    assert row["next_attempt_at"] == future


def test_list_due_returns_only_past_rows():
    # Insert one PAST row (should be returned) and one FUTURE row
    # (should NOT be returned). One test covers both behaviors.
    #
    # We insert directly via SQL so we can backdate the timestamp;
    # record_email_failure() always uses "now + 60s" which would
    # never look due to list_due().
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(retry_repo.get_db_path())
    try:
        conn.executemany(
            """
            INSERT INTO email_retry_queue
                (user_id, recipient, subject, body, error_message,
                 attempts, max_attempts, status,
                 created_at, last_attempt_at, next_attempt_at)
            VALUES (?, ?, ?, ?, ?, 1, 5, 'pending', ?, ?, ?)
            """,
            [
                ("past-user", "a@b.com", "s", "b", "e", now, now,
                 "1970-01-01T00:00:00+00:00"),       # due
                ("future-user", "a@b.com", "s", "b", "e", now, now,
                 "2099-01-01T00:00:00+00:00"),       # not due yet
            ],
        )
        conn.commit()
    finally:
        conn.close()

    due = retry_repo.list_due()
    user_ids = [row["user_id"] for row in due]
    assert user_ids == ["past-user"]
