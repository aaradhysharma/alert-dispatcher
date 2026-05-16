"""Tests for the SQLite-backed retry queue.

We exercise the read-side helpers too even though no production code
calls them yet; they're part of the documented retry contract and we
want a regression net before a worker is wired up later.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from alert_dispatcher.repositories import retry as retry_repo


def _all_rows() -> list[sqlite3.Row]:
    conn = sqlite3.connect(retry_repo.get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        return list(conn.execute("SELECT * FROM email_retry_queue"))
    finally:
        conn.close()


def test_init_db_is_idempotent():
    # Conftest already called init_db once; calling again must not raise.
    retry_repo.init_db()
    retry_repo.init_db()


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
    assert row["attempts"] == 1
    assert row["max_attempts"] == retry_repo.DEFAULT_MAX_ATTEMPTS
    assert row["status"] == "pending"
    # Timestamps should be ISO-8601 strings parseable as UTC datetimes.
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
    assert {r["status"] for r in _all_rows() if r["id"] == row_id_2} == {"exhausted"}


def test_bump_attempt_increments_and_reschedules():
    row_id = retry_repo.record_email_failure(
        user_id="user-1",
        recipient="a@b.com",
        subject="s",
        body="b",
        error_message="first",
    )
    future = "2099-01-01T00:00:00+00:00"
    retry_repo.bump_attempt(row_id, "second", future)
    row = _all_rows()[0]
    assert row["attempts"] == 2
    assert row["error_message"] == "second"
    assert row["next_attempt_at"] == future


def test_list_due_excludes_future_rows():
    # Freshly recorded rows have next_attempt_at = now + 60s, so they
    # should NOT be considered due immediately.
    retry_repo.record_email_failure(
        user_id="user-1",
        recipient="a@b.com",
        subject="s",
        body="b",
        error_message="e",
    )
    assert retry_repo.list_due() == []


def test_list_due_includes_past_rows():
    # Insert directly so we can backdate next_attempt_at.
    conn = sqlite3.connect(retry_repo.get_db_path())
    try:
        conn.execute(
            """
            INSERT INTO email_retry_queue
                (user_id, recipient, subject, body, error_message,
                 attempts, max_attempts, status,
                 created_at, last_attempt_at, next_attempt_at)
            VALUES (?, ?, ?, ?, ?, 1, 5, 'pending', ?, ?, ?)
            """,
            (
                "user-1",
                "a@b.com",
                "s",
                "b",
                "e",
                datetime.now(UTC).isoformat(),
                datetime.now(UTC).isoformat(),
                "1970-01-01T00:00:00+00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    due = retry_repo.list_due()
    assert len(due) == 1
    assert due[0]["user_id"] == "user-1"
