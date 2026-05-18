"""
Pydantic models used across the app.

Why one file:
    The project is small (one endpoint, a handful of channels). Splitting
    these models across a `models/` package would mean lots of tiny files
    and more imports for no real benefit. If this grows, the natural next
    step is to split per-feature: dispatch.py, users.py, retry.py.

Why Pydantic at all:
    FastAPI uses these classes to:
      1. Parse the incoming JSON.
      2. Validate it (e.g. user_id must be a non-empty string).
      3. Auto-return 422 with field-level errors if anything is wrong.
    That's why we don't need a custom validation handler in api/dispatch.py.
"""

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request body for POST /v1/dispatch
# ---------------------------------------------------------------------------
class MuteRequest(BaseModel):
    """Body for POST /v1/mute and POST /v1/unmute."""

    user_id: str = Field(..., min_length=1)


class MuteStatusResponse(BaseModel):
    user_id: str
    muted: bool


class DispatchRequest(BaseModel):
    # The target user's id. min_length=1 so an empty string fails validation.
    user_id: str = Field(..., min_length=1)

    # The kind of event we're notifying about (e.g. "UserSignedUp").
    event_type: str = Field(..., min_length=1)

    # Free-form data attached to the event. Could be empty {}; we don't
    # peek inside, we just pass it through to the channels.
    payload: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# A user record returned by users.py
# ---------------------------------------------------------------------------
class User(BaseModel):
    user_id: str
    email: str
    slack_dm: str  # e.g. "@alice"


# ---------------------------------------------------------------------------
# Result of trying ONE channel for ONE user
# ---------------------------------------------------------------------------
# Note: status is a plain string (not an Enum) on purpose. We log it,
# return it in JSON, and check it in tests; an Enum would just add
# .value calls everywhere without buying us anything.
class ChannelResult(BaseModel):
    channel: str          # "email" or "slack"
    status: str           # "sent" or "failed"
    to: str               # masked email for email; raw DM handle for slack
    error: str | None = None      # only set when status == "failed"
    retry_id: int | None = None   # only set when an email failure was persisted


# ---------------------------------------------------------------------------
# Top-level response body for POST /v1/dispatch
# ---------------------------------------------------------------------------
# `status` is one of:
#   "dispatched"        -> all channels succeeded
#   "partial_failure"   -> at least one channel failed (today: only email)
#   "muted"             -> user is on the mute list, no sends were attempted
#   "no_op"             -> user exists but has no channel preferences
class DispatchResponse(BaseModel):
    status: str
    user_id: str
    event_type: str
    channels: list[ChannelResult] = Field(default_factory=list)
    trace_id: str
    elapsed_ms: float | None = None
