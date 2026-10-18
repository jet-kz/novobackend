"""
Outbound email transport. Sends as config.MAIL_FROM (info@novong.com).

Transport is chosen from the environment: Resend's HTTPS API when RESEND_API_KEY is set,
otherwise SMTP. send_email() never raises; it logs and returns False so a mail outage
can't break a request. Use send_in_background() for notifications nobody is waiting on.
"""
import asyncio
import logging
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

import httpx

from app.core import config

logger = logging.getLogger("novo.mailer")

# Strong refs so background sends aren't garbage-collected mid-flight.
_background_tasks: set[asyncio.Task] = set()


def mail_enabled() -> bool:
    return bool(config.RESEND_API_KEY or (config.SMTP_HOST and config.SMTP_PASSWORD))


def _sender() -> str:
    return formataddr((config.MAIL_FROM_NAME, config.MAIL_FROM))


async def _send_resend(to: list[str], subject: str, html: str, text: str) -> None:
    payload = {"from": _sender(), "to": to, "subject": subject, "html": html, "text": text}
    if config.MAIL_REPLY_TO:
        payload["reply_to"] = config.MAIL_REPLY_TO
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {config.RESEND_API_KEY}"},
            json=payload,
        )
    if res.status_code >= 300:
        raise RuntimeError(f"Resend {res.status_code}: {res.text[:300]}")


async def _send_smtp(to: list[str], subject: str, html: str, text: str) -> None:
    import aiosmtplib

    msg = EmailMessage()
    msg["From"] = _sender()
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=config.MAIL_FROM.split("@")[-1])
    if config.MAIL_REPLY_TO:
        msg["Reply-To"] = config.MAIL_REPLY_TO
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    security = config.SMTP_SECURITY
    await aiosmtplib.send(
        msg,
        hostname=config.SMTP_HOST,
        port=config.SMTP_PORT,
        username=config.SMTP_USERNAME or config.MAIL_FROM,
        password=config.SMTP_PASSWORD,
        use_tls=security == "ssl",
        start_tls=security == "starttls",
        timeout=20,
    )


async def send_email(to: str | list[str], subject: str, html: str, text: str) -> bool:
    recipients = [r for r in ([to] if isinstance(to, str) else to) if r]
    if not recipients:
        return False
    if not mail_enabled():
        logger.warning("Email not configured; skipped %r to %s", subject, recipients)
        return False
    try:
        if config.RESEND_API_KEY:
            await _send_resend(recipients, subject, html, text)
        else:
            await _send_smtp(recipients, subject, html, text)
        logger.info("Sent %r to %s", subject, recipients)
        return True
    except Exception:
        logger.exception("Failed to send %r to %s", subject, recipients)
        return False


def run_in_background(coro) -> None:
    """Schedule a coroutine (usually a notification) without awaiting it."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
