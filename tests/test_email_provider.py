"""Unit tests for the email provider.

The provider is the only place that handles raw email addresses, so
its tests focus on the two rules it owns:
  1. Mask the local part of every address it logs.
  2. Raise EmailProviderError on the documented FAIL substring.
"""

from __future__ import annotations

import logging

import pytest

from alert_dispatcher.providers.email import (
    EmailProviderError,
    mask_email,
    send_email,
)


class TestMaskEmail:
    def test_normal_address(self):
        assert mask_email("alice@example.com") == "a***@example.com"

    def test_two_char_local(self):
        # We always show only the first character; "ab@x.com" becomes "a***@x.com".
        assert mask_email("ab@x.com") == "a***@x.com"

    def test_single_char_local(self):
        assert mask_email("a@x.com") == "a***@x.com"

    def test_empty_local(self):
        assert mask_email("@x.com") == "***@x.com"

    def test_missing_at_sign(self):
        assert mask_email("not-an-email") == "***"

    def test_empty_string(self):
        assert mask_email("") == "***"


class TestSendEmail:
    def test_happy_path_logs_masked_recipient(self, caplog):
        with caplog.at_level(logging.INFO, logger="alert_dispatcher.providers.email"):
            send_email(to="alice@example.com", subject="hi", body="hello")
        # The full address must never appear in any log record.
        full_log = "\n".join(r.getMessage() for r in caplog.records)
        assert "alice@example.com" not in full_log
        assert "a***@example.com" in full_log

    def test_happy_path_logs_only_api_key_suffix(self, caplog):
        with caplog.at_level(logging.INFO, logger="alert_dispatcher.providers.email"):
            send_email(to="alice@example.com", subject="hi", body="hello")
        full_log = "\n".join(r.getMessage() for r in caplog.records)
        # We seeded the test key as "test-key-abcd1234"; only "1234" is allowed.
        assert "test-key-abcd1234" not in full_log
        assert "***1234" in full_log

    def test_fail_in_subject_raises(self):
        with pytest.raises(EmailProviderError):
            send_email(to="alice@example.com", subject="please FAIL", body="ok")

    def test_fail_in_body_raises(self):
        with pytest.raises(EmailProviderError):
            send_email(to="alice@example.com", subject="ok", body="this will FAIL")

    def test_fail_is_case_insensitive(self):
        with pytest.raises(EmailProviderError):
            send_email(to="alice@example.com", subject="fail now", body="...")

    def test_failure_log_does_not_include_body_or_full_email(self, caplog):
        # Defense-in-depth: even on failure, no PII should leak into logs.
        body = "secret payload alice@example.com"
        with caplog.at_level(logging.WARNING, logger="alert_dispatcher.providers.email"):
            with pytest.raises(EmailProviderError):
                send_email(to="alice@example.com", subject="FAIL", body=body)
        full_log = "\n".join(r.getMessage() for r in caplog.records)
        assert "alice@example.com" not in full_log
        assert "secret payload" not in full_log
