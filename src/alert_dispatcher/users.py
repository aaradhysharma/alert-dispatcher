"""Hardcoded user directory.

Lives here (rather than a database) so the exercise stays runnable with
zero infrastructure. The lookup helpers are the only part the rest of
the app should call -- swapping the implementation for a real user
service later is then a single-file change.
"""

from __future__ import annotations

from alert_dispatcher.models import User

# Internal directory. Kept private (underscore prefix) so callers go
# through the lookup helpers below rather than mutating the dict.
_HARDCODED_USERS: dict[str, User] = {
    "user-1": User(user_id="user-1", email="alice@example.com", slack_dm="@alice"),
    "user-2": User(user_id="user-2", email="bob@example.com", slack_dm="@bob"),
    "user-3": User(user_id="user-3", email="carol@example.com", slack_dm="@carol"),
}

# Channel preferences per user. Channels are evaluated in the order
# given. Unknown channel names are logged and skipped, not errored,
# so adding a new provider later is a non-breaking change.
_HARDCODED_PREFS: dict[str, list[str]] = {
    "user-1": ["email", "slack"],
    "user-2": ["email"],
    "user-3": ["slack"],
}


def get_user(user_id: str) -> User | None:
    """Return the user, or None if the id is unknown."""
    return _HARDCODED_USERS.get(user_id)


def get_user_channels(user_id: str) -> list[str]:
    """Return a fresh copy of the user's channel preferences.

    Returning a copy prevents callers from mutating the directory.
    """
    return list(_HARDCODED_PREFS.get(user_id, []))
