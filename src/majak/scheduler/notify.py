"""Notification stub — 'the morning brief is ready'.

Routes to a channel chosen by NOTIFY_CHANNEL (email | slack | push | log).
Only 'log' is implemented; the others are clean seams. Never raises — a failed
notification must not fail the scheduled job.
"""

from __future__ import annotations

import logging

from majak.config import settings

logger = logging.getLogger(__name__)


async def notify(subject: str, body: str) -> None:
    channel = settings.notify_channel.lower()
    try:
        if channel == "log":
            logger.info("[NOTIFY] %s\n%s", subject, body)
        elif channel == "email":
            await _send_email(subject, body)
        elif channel == "slack":
            await _send_slack(subject, body)
        elif channel == "push":
            await _send_push(subject, body)
        else:
            logger.warning("Unknown NOTIFY_CHANNEL=%r; logging instead", channel)
            logger.info("[NOTIFY] %s\n%s", subject, body)
    except Exception as exc:  # noqa: BLE001 — notification failures are non-fatal
        logger.error("Notification failed on channel %s: %s", channel, exc)


async def _send_email(subject: str, body: str) -> None:
    # Seam: wire an SMTP / transactional-email provider here.
    logger.info("[NOTIFY:email→%s] %s", settings.notify_target, subject)


async def _send_slack(subject: str, body: str) -> None:
    # Seam: chat.postMessage to a DM/channel here.
    logger.info("[NOTIFY:slack→%s] %s", settings.notify_target, subject)


async def _send_push(subject: str, body: str) -> None:
    # Seam: wire a push provider (APNs/FCM) here.
    logger.info("[NOTIFY:push→%s] %s", settings.notify_target, subject)
