"""HTTP tests for POST /v1/mute and POST /v1/unmute."""

from fastapi.testclient import TestClient

from alert_dispatcher.main import app
from alert_dispatcher.repositories import mute as mute_repo

client = TestClient(app)


def test_mute_then_dispatch_returns_muted():
    mute_repo.clear()
    assert client.post("/v1/mute", json={"user_id": "user-1"}).json() == {
        "user_id": "user-1",
        "muted": True,
    }
    dispatch = client.post(
        "/v1/dispatch",
        json={"user_id": "user-1", "event_type": "UserSignedUp", "payload": {}},
    )
    assert dispatch.status_code == 200
    assert dispatch.json()["status"] == "muted"
    assert dispatch.json()["channels"] == []


def test_unmute_restores_dispatch():
    mute_repo.clear()
    client.post("/v1/mute", json={"user_id": "user-1"})
    assert client.post("/v1/unmute", json={"user_id": "user-1"}).json() == {
        "user_id": "user-1",
        "muted": False,
    }
    dispatch = client.post(
        "/v1/dispatch",
        json={"user_id": "user-1", "event_type": "UserSignedUp", "payload": {}},
    )
    assert dispatch.json()["status"] == "dispatched"
    assert len(dispatch.json()["channels"]) >= 1


def test_mute_empty_user_id_returns_422():
    response = client.post("/v1/mute", json={"user_id": ""})
    assert response.status_code == 422
