"""Tests for the in-memory mute repository."""

from __future__ import annotations

from alert_dispatcher.repositories import mute as mute_repo


def test_unknown_user_is_not_muted():
    assert mute_repo.is_muted("user-1") is False


def test_mute_then_is_muted():
    mute_repo.mute("user-1")
    assert mute_repo.is_muted("user-1") is True


def test_unmute_removes_user():
    mute_repo.mute("user-1")
    mute_repo.unmute("user-1")
    assert mute_repo.is_muted("user-1") is False


def test_unmute_unknown_user_is_a_no_op():
    # Idempotent: should not raise even if the user wasn't muted.
    mute_repo.unmute("user-1")
    assert mute_repo.is_muted("user-1") is False


def test_mute_is_idempotent():
    mute_repo.mute("user-1")
    mute_repo.mute("user-1")
    assert mute_repo.is_muted("user-1") is True
