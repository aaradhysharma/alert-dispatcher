"""
Mute list, stored in memory.

What "muted" means:
    If a user is muted, the dispatch service must NOT call any provider
    for that user. It returns status="muted" instead of trying to send.

Why memory and not SQLite or a file:
    The brief explicitly allows in-memory. It's the smallest thing that
    makes the feature testable. The trade-off:
        - mutes vanish on process restart (recoverable: just re-mute)
        - mutes are NOT shared between uvicorn workers (single-worker
          dev setup is fine; multi-worker would need Redis/DB)
    These are listed in SUBMISSION.md as known limitations.

Why retry uses SQLite but mute uses memory:
    Losing a "we failed to send an email" record is bad: a real notice
    might never go out. Losing a mute flag is recoverable: the user (or
    admin) can re-mute. So we pay the cost of SQLite where it matters,
    not where it doesn't. This is the deliberate persistence asymmetry.
"""

# A plain Python set is enough: O(1) membership checks, no duplicates.
# We keep it module-level (a "global") so all parts of the app share it.
_muted: set[str] = set()


def is_muted(user_id: str) -> bool:
    """Return True if this user is currently muted."""
    return user_id in _muted


def mute(user_id: str) -> None:
    """Add user_id to the mute list. Calling twice is a no-op."""
    _muted.add(user_id)


def unmute(user_id: str) -> None:
    """Remove user_id from the mute list.

    We use `discard` (not `remove`) so unmuting someone who isn't muted
    doesn't raise an error. That makes this safer to call from an
    admin endpoint or a script.
    """
    _muted.discard(user_id)


def clear() -> None:
    """Wipe the mute list. Tests use this to start clean."""
    _muted.clear()
