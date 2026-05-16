"""Shared Pydantic models.

This single file is intentional for the current scope. If the project
grows, the natural next split is `models/dispatch.py`, `models/users.py`,
`models/retry.py` -- but for an exercise-sized service one file keeps
imports cheap and the surface obvious.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class DispatchRequest(BaseModel):
    """Inbound payload for POST /v1/dispatch.

    FastAPI/Pydantic enforce these constraints automatically and respond
    with a 422 on violation, so the HTTP layer never needs custom
    validation handlers.
    """

    user_id: str = Field(..., min_length=1, description="Target user identifier.")
    event_type: str = Field(..., min_length=1, description="Domain event name.")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary event-specific data; opaque to the dispatcher.",
    )


class User(BaseModel):
    """Resolved user record returned by the user directory."""

    user_id: str
    email: str
    slack_dm: str


class ChannelResult(BaseModel):
    """Result of attempting to deliver a notification on a single channel."""

    channel: Literal["email", "slack"]
    status: Literal["sent", "failed"]
    # `to` is always the masked form for email and the raw DM handle for slack;
    # this is the value safe to expose in API responses and logs.
    to: str
    # Populated only on failure. Short, sanitized provider error text.
    error: str | None = None
    # Populated only on email failure: the row id in the retry queue,
    # so callers can correlate this response with the persisted record.
    retry_id: int | None = None


# Top-level outcome of a dispatch call. We expose this as a string union
# (rather than an enum) to keep API JSON shape stable and easy to read.
DispatchStatus = Literal["dispatched", "partial_failure", "muted", "no_op"]


class DispatchResponse(BaseModel):
    """Structured response body for POST /v1/dispatch."""

    status: DispatchStatus
    user_id: str
    event_type: str
    channels: list[ChannelResult] = Field(default_factory=list)
    trace_id: str
    elapsed_ms: float | None = None
