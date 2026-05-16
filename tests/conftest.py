"""Test setup shared by all tests.

Order matters here: the env vars must be set BEFORE any module that
calls `get_settings()` is imported, otherwise pydantic-settings will
fail to construct because the required keys aren't present. We can't
rely on a developer's local `.env` (CI doesn't have one) so we set
deterministic test values up front.
"""

from __future__ import annotations

import os

# Set BEFORE importing anything from the package.
os.environ.setdefault("MOCK_EMAIL_API_KEY", "test-key-abcd1234")
os.environ.setdefault(
    "MOCK_SLACK_WEBHOOK", "https://hooks.slack.com/services/T0/B0/XYZ"
)

import pytest  # noqa: E402

from alert_dispatcher.repositories import mute as mute_repo  # noqa: E402
from alert_dispatcher.repositories import retry as retry_repo  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path):
    """Give every test a fresh SQLite file and an empty mute set.

    Autouse so individual tests don't have to remember to opt in;
    state leakage between tests is the most common source of flakes
    on this kind of suite.
    """
    db_path = tmp_path / "retry.db"
    retry_repo.set_db_path(str(db_path))
    retry_repo.init_db()
    mute_repo.clear()
    yield
    mute_repo.clear()
