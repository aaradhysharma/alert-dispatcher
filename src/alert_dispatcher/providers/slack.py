"""Mock Slack provider.

The mock provider does not raise -- there is no demo failure mode
for Slack in docs/questions.md. If/when one is added, mirror the
shape of `providers.email` (custom exception + retry persistence
in the dispatch service).
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from alert_dispatcher.settings import get_settings

logger = logging.getLogger(__name__)


def _webhook_host() -> str:
    """Extract just the host from the configured webhook URL.

    We log only the host so a misconfigured webhook path (which can
    contain secret tokens) is not leaked into log aggregation.
    """
    webhook = get_settings().mock_slack_webhook
    return urlparse(webhook).netloc or "(invalid webhook URL)"


def send_slack(dm: str, text: str) -> None:
    """Send a Slack DM via the mock provider."""
    logger.info(
        "MOCK SLACK sent dm=%s text_len=%s webhook_host=%s",
        dm,
        len(text),
        _webhook_host(),
    )
