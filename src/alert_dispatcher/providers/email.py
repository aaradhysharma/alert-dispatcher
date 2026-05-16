"""Mock email provider with safe logging.

Why this module owns email-specific masking:
  - The legal/PII rule (mask emails in logs) is most likely to be
    violated by code that already knows the raw email. Putting
    `mask_email` in the same module as the only code that legitimately
    handles the raw address keeps the blast radius small and makes
    code review on this rule a single-file check.

What this module does NOT do:
  - It does not write to the retry queue. That decision (and the
    choice to keep going on the other channels) belongs to the
    dispatch service, not the provider. The provider's job is just
    "deliver or raise".
"""

from __future__ import annotations

import logging

from alert_dispatcher.settings import get_settings

logger = logging.getLogger(__name__)


class EmailProviderError(Exception):
    """Raised when the (mock) email provider fails to deliver.

    A dedicated exception type lets the dispatch service catch *only*
    provider failures and not, say, programming errors -- which we
    want to keep crashing the request with a real 500.
    """


def mask_email(email: str) -> str:
    """Mask the local part of an email for logging.

    Examples:
        alice@example.com -> a***@example.com
        ab@x.com          -> a***@x.com
        a@x.com           -> a***@x.com
        @x.com            -> ***@x.com
        bad               -> ***
        ""                -> ***

    We always keep at most the first character of the local part. This
    is a deliberate tradeoff: we lose useful debugging detail (e.g.
    distinguishing alice@ from arthur@) in exchange for a uniform mask
    that is hard to misuse.
    """
    if not email or "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    if not local:
        return f"***@{domain}"
    return f"{local[0]}***@{domain}"


def _api_key_tail() -> str:
    """Return the API key formatted for log lines.

    Per project rules, never log the full key. We emit only the last
    four characters with a `***` prefix so log scrapers cannot trivially
    reconstruct anything sensitive.
    """
    key = get_settings().mock_email_api_key
    return f"***{key[-4:]}" if len(key) >= 4 else "***"


def send_email(to: str, subject: str, body: str) -> None:
    """Send an email via the mock provider.

    Raises EmailProviderError if the subject or body contains the
    substring "FAIL" (case-insensitive). This is the documented demo
    failure mode from docs/questions.md, used to exercise the retry path.
    """
    blob = f"{subject}\n{body}"
    if "FAIL" in blob.upper():
        # On failure we still want a log line, but a leaner one: never
        # log the body (it could contain PII), and always mask the
        # recipient. The exception carries the human-readable reason.
        logger.warning(
            "MOCK EMAIL failed to=%s subject=%s body_len=%s",
            mask_email(to),
            subject,
            len(body),
        )
        raise EmailProviderError("Mock Email Provider: upstream timeout (simulated)")

    logger.info(
        "MOCK EMAIL sent to=%s subject=%s body_len=%s api_key=%s",
        mask_email(to),
        subject,
        len(body),
        _api_key_tail(),
    )
