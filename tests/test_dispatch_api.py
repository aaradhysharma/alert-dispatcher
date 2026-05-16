"""
End-to-end HTTP tests using FastAPI's TestClient.

TestClient lets us call the API in-process (no real network). We
deliberately do NOT use `with TestClient(app) as client:` -- the
`with` form would trigger the lifespan hook, which calls init_db()
on the production DB path. The conftest fixture has already pointed
us at a per-test temp DB, so we want lifespan OFF for tests.
"""

import sqlite3

from fastapi.testclient import TestClient

from alert_dispatcher.main import app
from alert_dispatcher.repositories import mute as mute_repo
from alert_dispatcher.repositories import retry as retry_repo

# One client object reused across tests in this file -- starting one
# is cheap, but reusing keeps the test output tidy.
client = TestClient(app)


def test_health():
    # Trivial sanity test for the liveness endpoint.
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_dispatch_happy_path_email_only_user():
    # user-2 has only "email" in their channel preferences, so we
    # expect a single channel result coming back.
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
    # Even on success, the recipient must be MASKED in the response.
    assert ch["to"] == "b***@example.com"
    assert ch["error"] is None
    assert ch["retry_id"] is None


def test_dispatch_full_fanout_user():
    # user-1 has both email and slack. Both should go out.
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

    # Build a quick {"email": {...}, "slack": {...}} dict so we don't
    # have to care about list ordering.
    channels = {c["channel"]: c for c in body["channels"]}
    assert set(channels.keys()) == {"email", "slack"}
    assert channels["email"]["status"] == "sent"
    assert channels["slack"]["status"] == "sent"


def test_dispatch_unknown_user_returns_404():
    response = client.post(
        "/v1/dispatch",
        json={"user_id": "ghost", "event_type": "X", "payload": {}},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "unknown user"


def test_dispatch_missing_required_field_returns_422():
    # event_type is required. Pydantic should reject this with 422
    # automatically -- there is no custom 422 handler in our code.
    response = client.post(
        "/v1/dispatch",
        json={"user_id": "user-1", "payload": {}},
    )
    assert response.status_code == 422

    detail = response.json()["detail"]
    # FastAPI/Pydantic returns a list of error objects; we just want
    # to confirm event_type was the field flagged.
    assert any(err["loc"][-1] == "event_type" for err in detail)


def test_dispatch_empty_user_id_returns_422():
    # min_length=1 on user_id should reject an empty string.
    response = client.post(
        "/v1/dispatch",
        json={"user_id": "", "event_type": "X", "payload": {}},
    )
    assert response.status_code == 422


def test_dispatch_muted_user_returns_status_muted_and_no_sends():
    # Pre-mute user-1, then dispatch.
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
    # No channels attempted -> no channel results.
    assert body["channels"] == []
    # And no retry rows should exist either: muted means we skipped
    # the providers entirely.
    assert retry_repo.list_due() == []


def test_dispatch_email_fail_persists_retry_and_does_not_500():
    # Putting "FAIL" in the event_type means the substring shows up
    # in the email subject AND the JSON body, which the mock provider
    # treats as a forced failure.
    response = client.post(
        "/v1/dispatch",
        json={
            "user_id": "user-2",  # email-only user, isolates the failure
            "event_type": "EmailFAILExample",
            "payload": {},
        },
    )

    # CRITICAL: the request must NOT 500 just because email failed.
    # That's the whole point of the retry path.
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partial_failure"
    assert len(body["channels"]) == 1

    ch = body["channels"][0]
    assert ch["channel"] == "email"
    assert ch["status"] == "failed"
    assert ch["to"] == "b***@example.com"   # masked in the response
    assert ch["error"]
    assert isinstance(ch["retry_id"], int)

    # And the failure must be persisted in SQLite for a future worker.
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
    # The DB stores the RAW recipient (the worker needs it to retry).
    # Our PII rule is about LOGS, not about the retry queue itself.
    assert row["recipient"] == "bob@example.com"
    assert row["status"] == "pending"
    assert row["attempts"] == 1


def test_dispatch_email_fail_still_sends_slack_for_dual_channel_user():
    # user-1 has both channels. If email fails, slack should still go.
    # This is the "non-crashing partial failure" contract from the brief.
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
