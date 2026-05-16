"""
Shared test setup.

A "conftest.py" is auto-loaded by pytest for every test in this folder
(and subfolders). Use it to:
    - set environment variables BEFORE the app code imports them
    - declare fixtures (reusable test setup) that any test can ask for
"""

import os

# IMPORTANT: env vars must be set BEFORE any import that calls
# get_settings(), because pydantic-settings reads them at construction
# time. We can't rely on a developer's local .env (CI doesn't have one)
# so we set predictable test values up front.
os.environ.setdefault("MOCK_EMAIL_API_KEY", "test-key-abcd1234")
os.environ.setdefault(
    "MOCK_SLACK_WEBHOOK", "https://hooks.slack.com/services/T0/B0/XYZ"
)

# Now it's safe to import package code.
import pytest  # noqa: E402

from alert_dispatcher.repositories import mute as mute_repo  # noqa: E402
from alert_dispatcher.repositories import retry as retry_repo  # noqa: E402


# A "fixture" is something a test can take as an argument and pytest
# wires it up automatically. autouse=True means EVERY test gets this
# without having to ask for it.
#
# Why autouse: the most common test bug on a small suite is one test
# leaving state behind that breaks the next test. We pay the cost of
# isolating state once, here, instead of debugging flakes later.
@pytest.fixture(autouse=True)
def _isolated_state(tmp_path):
    # tmp_path is a pytest built-in fixture: a fresh temp directory
    # that's automatically cleaned up after the test.
    db_path = tmp_path / "retry.db"

    # Point the retry repository at the temp DB and create the schema.
    retry_repo.set_db_path(str(db_path))
    retry_repo.init_db()

    # Make sure no previous test left someone muted.
    mute_repo.clear()

    yield  # the test runs here

    # Belt-and-braces cleanup after the test.
    mute_repo.clear()
