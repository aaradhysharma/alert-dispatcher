"""
Mock Slack provider.

Slack does NOT have a "FAIL" demo failure mode in the brief, so this
module just logs. If we ever add real Slack delivery, the shape to
copy is the email provider:
    - a custom exception class (e.g. SlackProviderError)
    - the dispatch service catches it and decides what to persist

What we deliberately log:
    - the DM target ("@alice") -- it's a handle, not PII
    - the message length, not the message body
    - only the WEBHOOK HOST -- never the path, because Slack webhook
      URLs contain a secret token in the path. Logging the host lets
      us see "we're pointing at the right cluster" without leaking it.
"""

import logging
from urllib.parse import urlparse

from alert_dispatcher.settings import get_settings

logger = logging.getLogger(__name__)


def _webhook_host() -> str:
    """Pull just the host (hooks.slack.com) out of the configured URL.

    If the URL is malformed, urlparse returns an empty netloc; we
    return a placeholder so the log line still reads cleanly.
    """
    webhook = get_settings().mock_slack_webhook
    return urlparse(webhook).netloc or "(invalid webhook URL)"


def send_slack(dm: str, text: str) -> None:
    """Pretend to send a Slack DM by logging."""
    logger.info(
        "MOCK SLACK sent dm=%s text_len=%s webhook_host=%s",
        dm,
        len(text),
        _webhook_host(),
    )
