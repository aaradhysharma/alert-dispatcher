"""
Tests for the in-memory mute repository.

These are tiny on purpose. The repo is a thin wrapper around a Python
set, so we mostly want to confirm the API is what callers expect.
"""

from alert_dispatcher.repositories import mute as mute_repo


def test_unknown_user_is_not_muted():
    # By default nobody is muted.
    assert mute_repo.is_muted("user-1") is False


def test_mute_then_is_muted():
    mute_repo.mute("user-1")
    assert mute_repo.is_muted("user-1") is True


def test_unmute_removes_user():
    mute_repo.mute("user-1")
    mute_repo.unmute("user-1")
    assert mute_repo.is_muted("user-1") is False


def test_unmute_unknown_user_is_a_no_op():
    # Should NOT raise -- unmuting someone who isn't muted is fine.
    mute_repo.unmute("user-1")
    assert mute_repo.is_muted("user-1") is False


def test_mute_is_idempotent():
    # Calling mute() twice is harmless.
    mute_repo.mute("user-1")
    mute_repo.mute("user-1")
    assert mute_repo.is_muted("user-1") is True
