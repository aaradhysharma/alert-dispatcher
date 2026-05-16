"""
Dispatch service.

This is the file that actually decides what happens for an inbound
event. The HTTP layer in api/dispatch.py just hands us a validated
DispatchRequest and turns whatever we return into JSON.

Order of operations (read top-to-bottom in `dispatch()` below):
    1. Look up the user. Unknown user -> raise UserNotFoundError
       (the API layer maps this to a 404).
    2. Is the user muted? If yes, return immediately with status="muted"
       and DO NOT call any provider.
    3. What channels does the user want? If none, return "no_op".
    4. Build the email subject and body once (so the email and the
       slack message are byte-identical -- helpful when correlating
       logs across channels).
    5. For each channel, call its provider:
         - "email" -> if it raises, persist a retry row and record a
                       failed channel result (do NOT re-raise).
         - "slack" -> just log; the mock never raises.
         - anything else -> log a warning and skip.
    6. If any channel failed, top-level status is "partial_failure";
       otherwise it's "dispatched".

This module has zero `from fastapi import ...`. Keeping it free of HTTP
imports means we can unit-test it directly without spinning up an app.
"""

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
    """Raised when the user_id in the request is not in our directory.

    A custom exception (rather than returning None) lets the API layer
    catch ONLY this case and turn it into 404. Programming bugs still
    bubble up as 500.
    """

    def __init__(self, user_id: str) -> None:
        super().__init__(f"unknown user: {user_id}")
        self.user_id = user_id


def dispatch(req: DispatchRequest) -> DispatchResponse:
    """Run the dispatch flow for a single event."""

    # time.perf_counter() is the right clock for measuring elapsed time
    # (it's monotonic and high-resolution; time.time() can jump backwards
    # if the system clock is adjusted).
    t0 = time.perf_counter()

    # A unique id for this request. We put it in the response AND in
    # every log line for this request so an operator can grep their way
    # through a problem.
    trace_id = str(uuid.uuid4())

    # ---- step 1: who is this user? -------------------------------------
    user = user_directory.get_user(req.user_id)
    if user is None:
        # No log line here on purpose: typos and deleted accounts are
        # common, logging at WARN would be noisy. The 404 itself is
        # enough signal for the caller.
        raise UserNotFoundError(req.user_id)

    # ---- step 2: are they muted? ---------------------------------------
    if mute_repo.is_muted(req.user_id):
        # Muted is a deliberate, observable behaviour. We log at INFO
        # because operators sometimes want to see "yes the system saw
        # this event but didn't send -- by design".
        logger.info(
            "dispatch muted user=%s event=%s trace_id=%s",
            req.user_id, req.event_type, trace_id,
        )
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        return DispatchResponse(
            status="muted",
            user_id=req.user_id,
            event_type=req.event_type,
            channels=[],
            trace_id=trace_id,
            elapsed_ms=elapsed,
        )

    # ---- step 3: what channels does this user want? --------------------
    channels = user_directory.get_user_channels(req.user_id)
    if not channels:
        # The user exists but no preferences are set. Treat as a
        # success-without-side-effects rather than an error -- this
        # avoids surprising clients with a 4xx when they did nothing
        # wrong.
        logger.info(
            "dispatch no_op (no channels) user=%s event=%s trace_id=%s",
            req.user_id, req.event_type, trace_id,
        )
        elapsed = round((time.perf_counter() - t0) * 1000, 3)
        return DispatchResponse(
            status="no_op",
            user_id=req.user_id,
            event_type=req.event_type,
            channels=[],
            trace_id=trace_id,
            elapsed_ms=elapsed,
        )

    # ---- step 4: build the message once --------------------------------
    subject = f"[{req.event_type}] notification"
    # We serialize the body once and reuse it. Both the email body and
    # the slack text contain the same JSON, which makes it easier to
    # correlate "did the same event go out on both channels?" later.
    body = json.dumps({
        "user_id": req.user_id,
        "event_type": req.event_type,
        "payload": req.payload,
    })

    # ---- step 5: fan out to each channel -------------------------------
    results: list[ChannelResult] = []

    for ch in channels:
        if ch == "email":
            # Try to send. If the provider raises, we persist a retry
            # row and record a "failed" channel result, but we DO NOT
            # re-raise -- other channels (e.g. slack) should still run.
            try:
                send_email(to=user.email, subject=subject, body=body)
                results.append(ChannelResult(
                    channel="email",
                    status="sent",
                    to=mask_email(user.email),  # masked even on success
                ))
            except EmailProviderError as exc:
                # Persist FIRST. If the logging library has a problem,
                # we'd rather lose a log line than lose the retry row.
                retry_id = retry_repo.record_email_failure(
                    user_id=user.user_id,
                    recipient=user.email,
                    subject=subject,
                    body=body,
                    error_message=str(exc),
                )

                # Then log enough context to debug, with PII rules:
                #   - masked recipient (never raw)
                #   - no body (could contain PII)
                #   - no API key (handled inside the provider, but
                #     we don't include it here either)
                logger.error(
                    "email send failed user=%s to=%s trace_id=%s "
                    "retry_id=%s error=%s",
                    user.user_id, mask_email(user.email),
                    trace_id, retry_id, exc,
                )

                results.append(ChannelResult(
                    channel="email",
                    status="failed",
                    to=mask_email(user.email),
                    error=str(exc),
                    retry_id=retry_id,
                ))

        elif ch == "slack":
            # The mock slack never raises. If/when we point at a real
            # Slack, copy the email try/except shape above.
            slack_provider.send_slack(dm=user.slack_dm, text=f"{subject}\n{body}")
            results.append(ChannelResult(
                channel="slack",
                status="sent",
                to=user.slack_dm,  # not PII; safe to return as-is
            ))

        else:
            # Unknown channel string in the user's prefs. We skip it
            # (instead of erroring) so adding a new channel later is a
            # non-breaking change for old user records.
            logger.warning(
                "unknown channel ignored channel=%s user=%s trace_id=%s",
                ch, req.user_id, trace_id,
            )

    # ---- step 6: build the top-level response --------------------------
    # If ANY channel failed, the overall status is "partial_failure".
    # Otherwise everything went through and we say "dispatched".
    any_failed = any(r.status == "failed" for r in results)
    overall = "partial_failure" if any_failed else "dispatched"

    # Defensive log: in theory we already caught the no-channels case
    # earlier and returned "no_op", but if a future change breaks that
    # path we want a loud signal rather than a silent black hole.
    if not results:
        logger.error(
            "dispatch produced zero sends user=%s event=%s trace_id=%s",
            req.user_id, req.event_type, trace_id,
        )

    elapsed = round((time.perf_counter() - t0) * 1000, 3)
    return DispatchResponse(
        status=overall,
        user_id=req.user_id,
        event_type=req.event_type,
        channels=results,
        trace_id=trace_id,
        elapsed_ms=elapsed,
    )
