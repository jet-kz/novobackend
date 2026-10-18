"""
Bachs (bachs.io) hosted checkout.

Flow: create a checkout session for the order total -> redirect the customer to checkout_url ->
Bachs calls our webhook with `collection.succeeded` -> we mark the order paid. The webhook is
the source of truth; the success redirect only shows a "confirming payment" screen.

Docs: https://docs.bachs.io (checkout sessions, webhooks/overview).
"""
import hashlib
import hmac
import logging
import time
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

import httpx
from fastapi import HTTPException, status

from app.core import config

logger = logging.getLogger("novo.bachs")

# Payment statuses that mean money arrived (docs: guides/payments/statuses).
PAID_STATUSES = {"succeeded", "accepted", "overpaid"}
SIGNATURE_TOLERANCE_SECONDS = 300


def _api_url() -> str:
    if config.BACHS_API_URL:
        return config.BACHS_API_URL.rstrip("/")
    return "https://sandbox-api.bachs.io" if config.BACHS_SECRET_KEY.startswith("sk_sandbox_") else "https://api.bachs.io"


def bachs_enabled() -> bool:
    return config.BACHS_SECRET_KEY.startswith(("sk_live_", "sk_sandbox_"))


def money(amount: float) -> str:
    """Bachs takes money as a decimal string at the currency's precision, e.g. "4500.00"."""
    return str(Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class BachsService:
    @staticmethod
    def _headers() -> dict:
        return {
            "Authorization": f"Bearer {config.BACHS_SECRET_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @staticmethod
    async def create_checkout_session(
        *,
        order_id: str,
        amount: float,
        currency: str,
        reference: str,
        customer_email: Optional[str],
        customer_name: Optional[str],
        customer_phone: Optional[str],
        success_url: str,
        cancel_url: str,
    ) -> dict:
        if not bachs_enabled():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Online payment isn't available right now. Choose cash or transfer on delivery.",
            )
        customer = {k: v for k, v in {
            "email": customer_email,
            "name": (customer_name or "").strip() or None,
            "phone_number": customer_phone,
        }.items() if v}
        payload: dict[str, Any] = {
            "pricing": {"currency": currency, "amount": money(amount)},
            "reference": reference,
            "metadata": {"order_id": order_id},
            "success_url": success_url,
            "cancel_url": cancel_url,
            "expires_in_minutes": 60,
        }
        if customer:
            payload["customer"] = customer

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                res = await client.post(f"{_api_url()}/v1/checkout-sessions", json=payload, headers=BachsService._headers())
        except httpx.RequestError as exc:
            logger.warning("Bachs unreachable creating checkout for %s: %s", order_id, exc)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                                detail="Couldn't reach the payment provider. Please try again.")
        if res.status_code not in (200, 201):
            logger.error("Bachs checkout failed for %s: %s %s", order_id, res.status_code, res.text[:500])
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                                detail="The payment provider couldn't start checkout. Please try again.")
        data = res.json()
        data = data.get("data", data) if isinstance(data, dict) else {}
        if not data.get("checkout_url"):
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Payment provider returned no checkout link.")
        return {"checkout_id": data.get("checkout_id"), "checkout_url": data["checkout_url"], "expires_at": data.get("expires_at")}

    @staticmethod
    async def get_checkout_session(checkout_id: str) -> Optional[dict]:
        if not bachs_enabled():
            return None
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                res = await client.get(f"{_api_url()}/v1/checkout-sessions/{checkout_id}", headers=BachsService._headers())
        except httpx.RequestError:
            return None
        if res.status_code != 200:
            return None
        data = res.json()
        return data.get("data", data) if isinstance(data, dict) else None


def verify_webhook_signature(raw_body: bytes, headers) -> bool:
    """
    HMAC-SHA256 over "{timestamp}.{raw_body}". The docs name the headers X-Bachs-Signature(-V2) /
    X-Bachs-Timestamp while the dashboard says Bachs-Signature, so both spellings are accepted, and
    any of them may carry either a bare hex digest or the "t=...,v1=..." form.
    """
    # Comma-separated: one signing secret per webhook endpoint (account events, connected-account events).
    secrets_list = [s.strip() for s in config.BACHS_WEBHOOK_SECRET.split(",") if s.strip()]
    if not secrets_list:
        return False
    candidates: list[str] = []
    timestamp = headers.get("x-bachs-timestamp") or headers.get("bachs-timestamp") or ""
    for name in ("x-bachs-signature-v2", "bachs-signature-v2", "x-bachs-signature", "bachs-signature"):
        value = (headers.get(name) or "").strip()
        if not value:
            continue
        if "=" not in value:
            candidates.append(value)
            continue
        for part in value.split(","):
            key, _, item = part.strip().partition("=")
            if key == "t":
                timestamp = item
            elif key.startswith("v") and item:
                candidates.append(item)
    try:
        if abs(time.time() - int(timestamp)) > SIGNATURE_TOLERANCE_SECONDS:
            return False
    except (TypeError, ValueError):
        return False
    message = f"{timestamp}.".encode() + raw_body
    for secret in secrets_list:
        expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
        if any(hmac.compare_digest(expected, c) for c in candidates):
            return True
    return False


# ── Connect (merchant & rider payouts) ───────────────────────────────────────
# Docs: connect/accounts, connect/onboarding, connect/split-payments/separate-transfers,
# connect/payouts, connect/acting-as-an-account (X-Account-Id).

class BachsError(Exception):
    def __init__(self, status_code: int, message: str, code: str | None = None):
        super().__init__(message)
        self.status_code, self.message, self.code = status_code, message, code


async def bachs_request(
    method: str,
    path: str,
    *,
    json: Optional[dict] = None,
    params: Optional[dict] = None,
    account_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> dict:
    """Call the Bachs API. Raises BachsError with Bachs' own message on failure."""
    if not bachs_enabled():
        raise BachsError(503, "Bachs isn't configured on the server yet.")
    headers = BachsService._headers()
    if account_id:
        headers["X-Account-Id"] = account_id
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            res = await client.request(method, f"{_api_url()}{path}", json=json, params=params, headers=headers)
    except httpx.RequestError as exc:
        raise BachsError(502, f"Couldn't reach Bachs: {exc}")
    try:
        body = res.json()
    except ValueError:
        body = {}
    if res.status_code >= 400:
        detail = body.get("detail") or body.get("message") or body.get("error") or res.text[:300]
        if isinstance(detail, dict):
            detail = detail.get("message") or str(detail)
        logger.warning("Bachs %s %s -> %s %s", method, path, res.status_code, str(detail)[:300])
        raise BachsError(res.status_code, str(detail), body.get("error_code") or body.get("code"))
    return body.get("data", body) if isinstance(body, dict) and isinstance(body.get("data"), (dict, list)) else body


def capability_status(account: dict, name: str) -> str:
    """Capabilities may come back as {"payouts": "active"}, {"payouts": {"status": ...}} or a list."""
    caps = account.get("capabilities") or {}
    if isinstance(caps, list):
        for cap in caps:
            if isinstance(cap, dict) and (cap.get("name") or cap.get("type") or cap.get("capability")) == name:
                return str(cap.get("status") or "")
        return ""
    value = caps.get(name)
    if isinstance(value, dict):
        return str(value.get("status") or "")
    return str(value or "")


def requirements_due(account: dict) -> list:
    req = account.get("requirements") or {}
    if isinstance(req, dict):
        due = req.get("currently_due") or req.get("past_due") or []
        return list(due) if isinstance(due, list) else []
    return []


def available_amount(balances, currency: str = "NGN") -> float:
    """Pull the available amount for a currency out of a /v1/balances response."""
    items = balances
    if isinstance(balances, dict):
        items = balances.get("balances") or balances.get("available") or balances.get("items") or [balances]
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        if str(item.get("currency") or currency).upper() != currency:
            continue
        value = item.get("available_balance", item.get("available", item.get("amount")))
        if isinstance(value, dict):
            value = value.get("amount")
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0
