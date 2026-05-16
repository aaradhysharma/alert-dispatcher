"""
Hardcoded user directory.

In a real product this would be a database table or a call to a user
service. For the exercise, we keep three users in a Python dict so the
app runs with zero infrastructure.

Everything else in the codebase only uses the helper functions below
(`get_user`, `get_user_channels`). That way, when we eventually swap
this for a real DB, we only have to change this one file.
"""

from alert_dispatcher.models import User

# Underscore prefix == "treat as private; don't import directly".
# Anyone outside this module should call `get_user()` instead.
_HARDCODED_USERS: dict[str, User] = {
    "user-1": User(user_id="user-1", email="alice@example.com", slack_dm="@alice"),
    "user-2": User(user_id="user-2", email="bob@example.com",   slack_dm="@bob"),
    "user-3": User(user_id="user-3", email="carol@example.com", slack_dm="@carol"),
}

# Channel preferences. The dispatcher walks this list in order and
# tries to deliver on each channel. Unknown channel names are skipped
# (with a log warning), not errored, so we can add a new channel later
# without breaking existing users.
_HARDCODED_PREFS: dict[str, list[str]] = {
    "user-1": ["email", "slack"],   # both
    "user-2": ["email"],            # email only
    "user-3": ["slack"],            # slack only
}


def get_user(user_id: str) -> User | None:
    """Return the User object, or None if the id is unknown.

    Returning None (rather than raising) lets the caller decide what to
    do. The dispatch service turns this into a domain-specific
    UserNotFoundError so the API layer can map it to a 404.
    """
    return _HARDCODED_USERS.get(user_id)


def get_user_channels(user_id: str) -> list[str]:
    """Return a COPY of the user's channel list.

    We return a copy (via `list(...)`) so a caller that mutates the
    returned list cannot accidentally change our directory.
    Unknown user -> empty list, which the dispatcher treats as "no_op".
    """
    return list(_HARDCODED_PREFS.get(user_id, []))
