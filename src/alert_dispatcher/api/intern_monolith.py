"""
WARNING: This module is intentionally low-quality "intern prototype" code.

Do not refactor here unless you are the candidate completing the exercise.
The business wants this logic professionalized — see docs/questions.md.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request

from alert_dispatcher.settings import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["dispatch"])

# ---------------------------------------------------------------------------
# "Configuration" — intern left users/prefs in code; secrets moved to .env
# ---------------------------------------------------------------------------

# Pretend user directory (should be DB — nobody had time)
HARDCODED_USERS: dict[str, dict[str, str]] = {
    "user-1": {"email": "alice@example.com", "slack_dm": "@alice"},
    "user-2": {"email": "bob@example.com", "slack_dm": "@bob"},
    "user-3": {"email": "carol@example.com", "slack_dm": "@carol"},
}

# Who wants what channel (also should be DB / service)
HARDCODED_PREFS: dict[str, list[str]] = {
    "user-1": ["email", "slack"],
    "user-2": ["email"],
    "user-3": ["slack"],
}


def _send_mock_email(to: str, subject: str, body: str) -> None:
    """
    Fake email provider. For interview demos, include the substring "FAIL"
    (case-insensitive) in the subject **or** JSON body to force a failure
    (see docs/questions.md).
    """
    blob = f"{subject}\n{body}"
    if "FAIL" in blob.upper():
        raise RuntimeError("Mock Email Provider: upstream timeout (simulated)")
    key = get_settings().mock_email_api_key
    tail = key[-4:] if len(key) >= 4 else "****"
    logger.info(
        "MOCK EMAIL to=%s subject=%s body_len=%s api_key_tail=%s",
        to,
        subject,
        len(body),
        tail,
    )


def _send_mock_slack(dm: str, text: str) -> None:
    webhook = get_settings().mock_slack_webhook
    host = urlparse(webhook).netloc or "(invalid webhook URL)"
    logger.info("MOCK SLACK dm=%s text_len=%s webhook_host=%s", dm, len(text), host)


@router.post("/v1/dispatch")
async def dispatch_everything_in_one_function(request: Request) -> dict[str, Any]:
    """
    Single mega-endpoint: parse JSON, validate-ish, fan out to channels, log.

    Known issues (by design for the exercise):
    - Malformed JSON -> opaque 500
    - Provider errors bubble up as 500
    - No persistence, no retries, no tests
    """
    t0 = time.perf_counter()
    raw = await request.body()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        # Intern error handling: swallow detail, return generic 500
        logger.exception("bad json")
        raise HTTPException(status_code=500, detail="Internal Server Error") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Internal Server Error")

    user_id = payload.get("user_id")
    event_type = payload.get("event_type")
    data = payload.get("payload", {})

    if not user_id or not isinstance(user_id, str):
        raise HTTPException(status_code=500, detail="Internal Server Error")
    if not event_type or not isinstance(event_type, str):
        raise HTTPException(status_code=500, detail="Internal Server Error")
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="Internal Server Error")

    # Intern "compatibility": sometimes clients send extra noise keys — ignored
    for k in list(payload.keys()):
        if k not in {"user_id", "event_type", "payload"}:
            logger.debug("ignoring unknown top-level field field=%s", k)

    if user_id not in HARDCODED_USERS:
        raise HTTPException(status_code=404, detail="unknown user")

    user = HARDCODED_USERS[user_id]
    channels = HARDCODED_PREFS.get(user_id, [])
    if not channels:
        return {
            "status": "no_op",
            "detail": "user has no channels configured",
            "trace_id": str(uuid.uuid4()),
        }

    # Legacy marketing naming — nobody documented why these exist
    if event_type == "UserSignedUp" and isinstance(data.get("plan"), str):
        plan = data.get("plan")
        logger.info("signup plan=%s user=%s", plan, user_id)
    elif event_type == "PaymentFailed":
        logger.warning("payment failed user=%s raw=%s", user_id, json.dumps(data)[:500])
    else:
        logger.info("generic event event_type=%s user=%s", event_type, user_id)

    subject = f"[{event_type}] notification"
    body = json.dumps({"user_id": user_id, "event_type": event_type, "payload": data})

    sent: list[dict[str, Any]] = []

    # Linear fan-out with nested logic — easy to break when extending
    for ch in channels:
        if ch == "email":
            _send_mock_email(to=user["email"], subject=subject, body=body)
            sent.append({"channel": "email", "to": user["email"]})
        elif ch == "slack":
            _send_mock_slack(dm=user["slack_dm"], text=f"{subject}\n{body}")
            sent.append({"channel": "slack", "to": user["slack_dm"]})
        else:
            logger.warning("unknown channel ignored channel=%s user=%s", ch, user_id)

    # Duplicate-ish metrics nobody reads
    if len(sent) == 0:
        logger.error("dispatch produced zero sends user=%s event=%s", user_id, event_type)

    elapsed_ms = (time.perf_counter() - t0) * 1000
    return {
        "status": "dispatched",
        "user_id": user_id,
        "event_type": event_type,
        "channels": sent,
        "elapsed_ms": round(elapsed_ms, 3),
        "trace_id": str(uuid.uuid4()),
    }


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
