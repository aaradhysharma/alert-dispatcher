"""
Mock email provider.

This module is the ONLY place in the codebase that touches a raw
email address. That is on purpose:
    - The legal/PII rule says "never log raw emails".
    - If raw addresses only flow through ONE file, breaking that rule
      becomes a single-file mistake to catch in code review.

The mask helper, the API key formatter, and the send function all
live together so the rule is enforced where the data actually is.
"""

import logging

from alert_dispatcher.settings import get_settings

# Each module gets its own logger named after the module path. That
# way the operator can filter logs to just "the email provider"
# (alert_dispatcher.providers.email) when debugging.
logger = logging.getLogger(__name__)


class EmailProviderError(Exception):
    """Raised when the (mock) email provider fails to deliver.

    We use a dedicated exception class (instead of plain RuntimeError)
    so the dispatch service can `except EmailProviderError:` -- that
    catches ONLY provider failures. Real bugs (TypeError, KeyError, ...)
    will still bubble up and cause a 500, which is what we want.
    """


def mask_email(email: str) -> str:
    """Hide the local part of an email for logging.

    Examples:
        alice@example.com -> a***@example.com
        ab@x.com          -> a***@x.com
        a@x.com           -> a***@x.com
        @x.com            -> ***@x.com
        not-an-email      -> ***
        ""                -> ***

    We always show at most one character of the local part. Yes, we
    lose some debugging info (we can't tell alice from arthur), but
    a uniform mask is much harder to misuse than a "show first 3 chars"
    rule that someone might tweak later.
    """
    # Treat empty / weird inputs the same way: don't pretend they're
    # valid emails, just return the safe placeholder.
    if not email or "@" not in email:
        return "***"

    # str.partition() splits "alice@example.com" into
    # ("alice", "@", "example.com"). Always returns 3 items, even when
    # the separator isn't present, so it doesn't crash on weird input.
    local, _, domain = email.partition("@")

    # If the local part is empty (e.g. "@x.com"), there's nothing to
    # show -- just emit the placeholder for the local part.
    if not local:
        return f"***@{domain}"

    return f"{local[0]}***@{domain}"


def _api_key_tail() -> str:
    """Return the API key formatted for log lines.

    Per the project rules: never log the full key. We show only the
    last 4 characters, with a "***" prefix. If the key is too short
    we just emit "***" with no suffix.
    """
    key = get_settings().mock_email_api_key
    if len(key) >= 4:
        return f"***{key[-4:]}"
    return "***"


def send_email(to: str, subject: str, body: str) -> None:
    """Send a fake email.

    The exercise spec says: if the substring "FAIL" appears in the
    subject OR the body (case-insensitive), the provider should raise.
    This is the demo failure mode used to exercise the retry path.

    We don't actually call any network service -- we just log.
    """
    # Combine subject + body once so we only do the upper-case search
    # once. .upper() makes the check case-insensitive.
    blob = f"{subject}\n{body}"
    if "FAIL" in blob.upper():
        # We still log, but VERY carefully:
        #   - mask the recipient
        #   - log only the body length, not the body itself
        #   - never log the API key
        logger.warning(
            "MOCK EMAIL failed to=%s subject=%s body_len=%s",
            mask_email(to),
            subject,
            len(body),
        )
        # Raising is how we signal failure to the dispatch service;
        # the service will catch it, persist a retry row, and continue.
        raise EmailProviderError("Mock Email Provider: upstream timeout (simulated)")

    # Happy path log line. Same masking rules apply: the recipient is
    # masked and only the API key SUFFIX is logged.
    logger.info(
        "MOCK EMAIL sent to=%s subject=%s body_len=%s api_key=%s",
        mask_email(to),
        subject,
        len(body),
        _api_key_tail(),
    )
