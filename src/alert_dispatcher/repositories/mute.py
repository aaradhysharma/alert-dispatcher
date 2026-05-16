"""In-memory mute list.

Deliberately not durable across process restart: the brief allows
choosing memory/file/DB and we pick memory to keep the surface tiny
and easy to test. The cost (mutes vanish on restart) is documented
in SUBMISSION.md so it is a known, intentional limitation rather
than a hidden bug.

The retry queue lives in SQLite because losing a failed-send record
on restart is operationally bad; losing a mute flag is recoverable
by re-muting. This is the deliberate persistence asymmetry.
"""

from __future__ import annotations

# Module-level set is fine because uvicorn runs a single worker by
# default in this project. Multi-worker deployments would need a
# shared store (Redis / DB) -- noted in SUBMISSION.md.
_muted: set[str] = set()


def is_muted(user_id: str) -> bool:
    return user_id in _muted


def mute(user_id: str) -> None:
    _muted.add(user_id)


def unmute(user_id: str) -> None:
    # discard (not remove) so unmuting an already-unmuted user is a no-op,
    # which is the friendlier API for an idempotent admin call.
    _muted.discard(user_id)


def clear() -> None:
    """Reset the mute list. Intended for tests, not production code."""
    _muted.clear()
