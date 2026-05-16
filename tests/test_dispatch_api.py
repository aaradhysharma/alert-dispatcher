"""End-to-end HTTP tests via FastAPI's TestClient.

We deliberately avoid the `with TestClient(app)` form so the
production lifespan (which would touch the real DB path) does not
fire. Conftest's autouse fixture has already pointed the retry repo
at a per-test SQLite file.
"""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from alert_dispatcher.main import app
from alert_dispatcher.repositories import mute as mute_repo
from alert_dispatcher.repositories import retry as retry_repo

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_dispatch_happy_path_email_only_user():
    # user-2 has only "email" in their preferences.
    response = client.post(
        "/v1/dispatch",
        json={
            "user_id": "user-2",
            "event_type": "UserSignedUp",
            "payload": {"plan": "pro"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "dispatched"
    assert body["user_id"] == "user-2"
    assert body["event_type"] == "UserSignedUp"
    assert len(body["channels"]) == 1
    ch = body["channels"][0]
    assert ch["channel"] == "email"
    assert ch["status"] == "sent"
    # Recipient must be masked even in successful responses, never raw.
    assert ch["to"] == "b***@example.com"
    assert ch["error"] is None
    assert ch["retry_id"] is None


def test_dispatch_full_fanout_user():
    # user-1 has both email and slack channels.
    response = client.post(
        "/v1/dispatch",
        json={
            "user_id": "user-1",
            "event_type": "PasswordChanged",
            "payload": {},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "dispatched"
    channels = {c["channel"]: c for c in body["channels"]}
    assert set(channels.keys()) == {"email", "slack"}
    assert channels["email"]["status"] == "sent"
    assert channels["slack"]["status"] == "sent"


def test_dispatch_unknown_user_returns_404():
    response = client.post(
        "/v1/dispatch",
        json={
            "user_id": "ghost",
            "event_type": "X",
            "payload": {},
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "unknown user"


def test_dispatch_missing_required_field_returns_422():
    # event_type is required and non-empty; Pydantic should produce a 422
    # automatically -- no custom validation handler in our code.
    response = client.post(
        "/v1/dispatch",
        json={"user_id": "user-1", "payload": {}},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(err["loc"][-1] == "event_type" for err in detail)


def test_dispatch_empty_user_id_returns_422():
    response = client.post(
        "/v1/dispatch",
        json={"user_id": "", "event_type": "X", "payload": {}},
    )
    assert response.status_code == 422


def test_dispatch_muted_user_returns_status_muted_and_no_sends():
    mute_repo.mute("user-1")

    response = client.post(
        "/v1/dispatch",
        json={
            "user_id": "user-1",
            "event_type": "UserSignedUp",
            "payload": {},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "muted"
    assert body["channels"] == []
    # No retry rows should have been created either.
    assert retry_repo.list_due() == []


def test_dispatch_email_fail_persists_retry_and_does_not_500():
    # The "FAIL" substring in the event_type ends up in subject and body,
    # which the mock provider treats as a forced failure.
    response = client.post(
        "/v1/dispatch",
        json={
            "user_id": "user-2",  # email-only user, so we can isolate the failure
            "event_type": "EmailFAILExample",
            "payload": {},
        },
    )

    # Critical contract: provider failure must NOT bubble up as 500.
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partial_failure"
    assert len(body["channels"]) == 1
    ch = body["channels"][0]
    assert ch["channel"] == "email"
    assert ch["status"] == "failed"
    assert ch["to"] == "b***@example.com"  # masked in response, too
    assert ch["error"]
    assert isinstance(ch["retry_id"], int)

    # And the failure must be persisted for a future worker to pick up.
    conn = sqlite3.connect(retry_repo.get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        rows = list(conn.execute("SELECT * FROM email_retry_queue"))
    finally:
        conn.close()

    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == ch["retry_id"]
    assert row["user_id"] == "user-2"
    assert row["recipient"] == "bob@example.com"
    assert row["status"] == "pending"
    assert row["attempts"] == 1


def test_dispatch_email_fail_still_sends_slack_for_dual_channel_user():
    # user-1 has both channels; email should fail, slack should still go out.
    response = client.post(
        "/v1/dispatch",
        json={
            "user_id": "user-1",
            "event_type": "PleaseFAIL",
            "payload": {},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partial_failure"
    by_channel = {c["channel"]: c for c in body["channels"]}
    assert by_channel["email"]["status"] == "failed"
    assert by_channel["slack"]["status"] == "sent"
