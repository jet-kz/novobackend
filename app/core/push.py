"""
Web push (phone/browser notifications) via the standard Push API + VAPID.

Browsers subscribe with our public key; we sign each push with the private key. Works on Android
(Chrome, Samsung, Firefox), desktop browsers, and iPhone (iOS 16.4+) once Novo is added to the
Home Screen. A subscription that the push service reports as gone (404/410) is deleted.

To make a new key pair:  python -c "from py_vapid import Vapid01; v=Vapid01(); v.generate_keys(); ..."
(see the commit that added this file; keys are base64url raw P-256 values).
"""
import asyncio
import json
import logging

from app.core import config

logger = logging.getLogger("novo.push")


def push_enabled() -> bool:
    return bool(config.VAPID_PUBLIC_KEY and config.VAPID_PRIVATE_KEY)


def _send_one(sub: dict, payload: str) -> int:
    """Blocking send; returns the HTTP status (or 0 on network error)."""
    from pywebpush import WebPushException, webpush

    try:
        res = webpush(
            subscription_info=sub,
            data=payload,
            vapid_private_key=config.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": config.VAPID_SUBJECT},
            ttl=60 * 60 * 12,
            headers={"Urgency": "high"},
        )
        return getattr(res, "status_code", 201)
    except WebPushException as exc:
        return getattr(exc.response, "status_code", 0) or 0
    except Exception:
        logger.exception("Push send failed")
        return 0


async def send_push(subscriptions: list, title: str, body: str, url: str = "/", tag: str | None = None) -> list:
    """
    Send to each subscription (objects with endpoint/p256dh/auth). Returns the ones that are gone
    and should be deleted.
    """
    if not push_enabled() or not subscriptions:
        return []
    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag})
    results = await asyncio.gather(*[
        asyncio.to_thread(_send_one, {"endpoint": s.endpoint, "keys": {"p256dh": s.p256dh, "auth": s.auth}}, payload)
        for s in subscriptions
    ])
    return [s for s, code in zip(subscriptions, results) if code in (404, 410)]
