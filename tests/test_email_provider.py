"""
Tests for providers/email.py.

The email provider is the only place that touches a raw email address,
so its tests focus on the two rules it owns:
    1. mask the local part of every address it logs
    2. raise EmailProviderError on the documented "FAIL" substring
"""

import logging

import pytest

from alert_dispatcher.providers.email import (
    EmailProviderError,
    mask_email,
    send_email,
)


# ----------------------------------------------------------------------
# mask_email() unit tests
# ----------------------------------------------------------------------
# Grouping with a class is just for readability in pytest output; we
# don't need any setup/teardown.
class TestMaskEmail:
    def test_normal_address(self):
        assert mask_email("alice@example.com") == "a***@example.com"

    def test_two_char_local(self):
        # We always show only ONE character of the local part.
        assert mask_email("ab@x.com") == "a***@x.com"

    def test_single_char_local(self):
        assert mask_email("a@x.com") == "a***@x.com"

    def test_empty_local(self):
        # "@x.com" has nothing before the @, so nothing to show.
        assert mask_email("@x.com") == "***@x.com"

    def test_missing_at_sign(self):
        # Garbage in -> safe placeholder out.
        assert mask_email("not-an-email") == "***"

    def test_empty_string(self):
        assert mask_email("") == "***"


# ----------------------------------------------------------------------
# send_email() integration tests (still no network -- it's a mock)
# ----------------------------------------------------------------------
class TestSendEmail:
    def test_happy_path_logs_masked_recipient(self, caplog):
        # caplog is a pytest fixture that captures log records so we
        # can assert on them.
        with caplog.at_level(logging.INFO, logger="alert_dispatcher.providers.email"):
            send_email(to="alice@example.com", subject="hi", body="hello")

        # Join all log messages so a single assert sweeps them.
        full_log = "\n".join(r.getMessage() for r in caplog.records)
        # The full address must NEVER appear anywhere in our logs.
        assert "alice@example.com" not in full_log
        # The masked form should appear instead.
        assert "a***@example.com" in full_log

    def test_happy_path_logs_only_api_key_suffix(self, caplog):
        with caplog.at_level(logging.INFO, logger="alert_dispatcher.providers.email"):
            send_email(to="alice@example.com", subject="hi", body="hello")
        full_log = "\n".join(r.getMessage() for r in caplog.records)
        # conftest.py set the test key to "test-key-abcd1234".
        # Only the last 4 chars ("1234") should ever be logged.
        assert "test-key-abcd1234" not in full_log
        assert "***1234" in full_log

    def test_fail_in_subject_raises(self):
        # Every "with pytest.raises(...)" block expects an exception
        # of that type to be thrown inside the block.
        with pytest.raises(EmailProviderError):
            send_email(to="alice@example.com", subject="please FAIL", body="ok")

    def test_fail_in_body_raises(self):
        with pytest.raises(EmailProviderError):
            send_email(to="alice@example.com", subject="ok", body="this will FAIL")

    def test_fail_is_case_insensitive(self):
        # Lowercase "fail" must trigger the same failure path.
        with pytest.raises(EmailProviderError):
            send_email(to="alice@example.com", subject="fail now", body="...")

    def test_failure_log_does_not_include_body_or_full_email(self, caplog):
        # Even on failure, we must not leak PII into logs.
        body = "secret payload alice@example.com"
        with caplog.at_level(logging.WARNING, logger="alert_dispatcher.providers.email"):
            with pytest.raises(EmailProviderError):
                send_email(to="alice@example.com", subject="FAIL", body=body)
        full_log = "\n".join(r.getMessage() for r in caplog.records)
        # No raw email...
        assert "alice@example.com" not in full_log
        # ...and no body content.
        assert "secret payload" not in full_log
