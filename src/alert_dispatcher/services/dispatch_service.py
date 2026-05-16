"""Dispatch orchestration.

This module is the only place that knows the *order* of operations:
resolve user -> check mute -> resolve channels -> fan out -> persist
email failures. It deliberately depends on concrete provider/repo
modules (not abstract interfaces); for a service this size, the extra
ceremony of dependency injection or Protocols would obscure more than
it clarifies. If we ever need to swap providers per-environment, we
can revisit (see SUBMISSION.md "what I would NOT change").

This module has zero FastAPI imports. The only way the API layer
learns about an unknown user is the typed `UserNotFoundError` below;
everything else returns a normal `DispatchResponse` so the HTTP layer
stays trivial.
"""

from __future__ import annotations

import json
import logging
import time
import uuid

from alert_dispatcher import users as user_directory
from alert_dispatcher.models import (
    ChannelResult,
    DispatchRequest,
    DispatchResponse,
)
from alert_dispatcher.providers import slack as slack_provider
from alert_dispatcher.providers.email import (
    EmailProviderError,
    mask_email,
    send_email,
)
from alert_dispatcher.repositories import mute as mute_repo
from alert_dispatcher.repositories import retry as retry_repo

logger = logging.getLogger(__name__)


class UserNotFoundError(Exception):
    """Raised when the requested user_id is not in the user directory.

    A typed exception (rather than a sentinel return value) lets the
    HTTP layer map *only* this case to a 404, while still letting any
    real bug bubble up as a 500.
    """

    def __init__(self, user_id: str) -> None:
        super().__init__(f"unknown user: {user_id}")
        self.user_id = user_id


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 3)


def dispatch(req: DispatchRequest) -> DispatchResponse:
    """Run the dispatch use case for a single inbound event."""
    t0 = time.perf_counter()
    # Generate the trace_id up front so every log line for this
    # request can be correlated with the response body.
    trace_id = str(uuid.uuid4())

    user = user_directory.get_user(req.user_id)
    if user is None:
        # The API layer translates this to 404. We don't log here:
        # unknown users are common (typos, deleted accounts) and
        # logging at WARN would be noisy.
        raise UserNotFoundError(req.user_id)

    if mute_repo.is_muted(req.user_id):
        # Intentional, observable behaviour. Returning 200 with a
        # distinct status keeps the contract explicit: callers cannot
        # confuse a muted user with a successful send. SUBMISSION.md
        # explains why we did not pick 4xx for this case.
        logger.info(
            "dispatch muted user=%s event=%s trace_id=%s",
            req.user_id,
            req.event_type,
            trace_id,
        )
        return DispatchResponse(
            status="muted",
            user_id=req.user_id,
            event_type=req.event_type,
            channels=[],
            trace_id=trace_id,
            elapsed_ms=_elapsed_ms(t0),
        )

    channels = user_directory.get_user_channels(req.user_id)
    if not channels:
        # User exists but has no preferred channels. Treat as success-
        # without-side-effects rather than an error.
        logger.info(
            "dispatch no_op (no channels) user=%s event=%s trace_id=%s",
            req.user_id,
            req.event_type,
            trace_id,
        )
        return DispatchResponse(
            status="no_op",
            user_id=req.user_id,
            event_type=req.event_type,
            channels=[],
            trace_id=trace_id,
            elapsed_ms=_elapsed_ms(t0),
        )

    subject = f"[{req.event_type}] notification"
    # We serialize once and reuse, so the email body and the slack text
    # stay byte-identical -- useful when an operator is correlating
    # records across channels.
    body = json.dumps(
        {
            "user_id": req.user_id,
            "event_type": req.event_type,
            "payload": req.payload,
        }
    )

    results: list[ChannelResult] = []
    for ch in channels:
        if ch == "email":
            results.append(_attempt_email(user.user_id, user.email, subject, body, trace_id))
        elif ch == "slack":
            slack_provider.send_slack(dm=user.slack_dm, text=f"{subject}\n{body}")
            results.append(
                ChannelResult(channel="slack", status="sent", to=user.slack_dm)
            )
        else:
            # Unknown channel names are skipped, not errored: a future
            # provider added to a user's prefs but not yet supported by
            # this version should degrade gracefully.
            logger.warning(
                "unknown channel ignored channel=%s user=%s trace_id=%s",
                ch,
                req.user_id,
                trace_id,
            )

    any_failed = any(r.status == "failed" for r in results)
    status = "partial_failure" if any_failed else "dispatched"

    if not results:
        # Unreachable in practice (we returned no_op earlier), but kept
        # as a safety log so a future channel-prefs change can't silently
        # become a black hole.
        logger.error(
            "dispatch produced zero sends user=%s event=%s trace_id=%s",
            req.user_id,
            req.event_type,
            trace_id,
        )

    return DispatchResponse(
        status=status,
        user_id=req.user_id,
        event_type=req.event_type,
        channels=results,
        trace_id=trace_id,
        elapsed_ms=_elapsed_ms(t0),
    )


def _attempt_email(
    user_id: str,
    email: str,
    subject: str,
    body: str,
    trace_id: str,
) -> ChannelResult:
    """Send via email; on provider failure, persist for retry instead of crashing.

    Split out as a helper to keep the main loop readable and so the
    "catch + persist + log + return failure result" pattern lives in
    one place.
    """
    try:
        send_email(to=email, subject=subject, body=body)
        return ChannelResult(channel="email", status="sent", to=mask_email(email))
    except EmailProviderError as exc:
        # Persist BEFORE logging the success of the persist, so a
        # logging failure can't lose the retry record.
        retry_id = retry_repo.record_email_failure(
            user_id=user_id,
            recipient=email,
            subject=subject,
            body=body,
            error_message=str(exc),
        )
        # Log enough to debug (trace_id, retry_id, masked recipient,
        # short error) but never the body or the API key.
        logger.error(
            "email send failed user=%s to=%s trace_id=%s retry_id=%s error=%s",
            user_id,
            mask_email(email),
            trace_id,
            retry_id,
            exc,
        )
        return ChannelResult(
            channel="email",
            status="failed",
            to=mask_email(email),
            error=str(exc),
            retry_id=retry_id,
        )
