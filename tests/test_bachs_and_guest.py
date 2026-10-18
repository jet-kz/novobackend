"""Bachs webhook signatures, Bachs payment checks, guest checkout validation."""
import hashlib
import hmac
import time
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core import config
from app.main import app
from app.modules.orders.models import Order
from app.modules.orders.service import OrderService, hash_guest_token
from app.modules.payments.bachs_service import money, verify_webhook_signature
from app.modules.payments.service import PaymentService

SECRET = "whsec_test"


def _sign(body: bytes, ts: int | None = None) -> dict:
    ts = ts or int(time.time())
    sig = hmac.new(SECRET.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return {"x-bachs-timestamp": str(ts), "x-bachs-signature": sig}


class WebhookSignatureTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(config, "BACHS_WEBHOOK_SECRET", SECRET)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_valid_signature(self):
        body = b'{"type":"collection.succeeded"}'
        self.assertTrue(verify_webhook_signature(body, _sign(body)))

    def test_v2_header(self):
        body = b"{}"
        ts = int(time.time())
        sig = _sign(body, ts)["x-bachs-signature"]
        self.assertTrue(verify_webhook_signature(body, {"x-bachs-signature-v2": f"t={ts},v1=deadbeef,v1={sig}"}))

    def test_dashboard_header_spelling(self):
        body = b'{"type":"collection.succeeded"}'
        ts = int(time.time())
        sig = _sign(body, ts)["x-bachs-signature"]
        self.assertTrue(verify_webhook_signature(body, {"bachs-signature": f"t={ts},v1={sig}"}))
        self.assertTrue(verify_webhook_signature(body, {"bachs-timestamp": str(ts), "bachs-signature": sig}))

    def test_tampered_body_rejected(self):
        headers = _sign(b'{"amount":"100.00"}')
        self.assertFalse(verify_webhook_signature(b'{"amount":"1.00"}', headers))

    def test_stale_timestamp_rejected(self):
        body = b"{}"
        self.assertFalse(verify_webhook_signature(body, _sign(body, int(time.time()) - 3600)))

    def test_no_secret_configured_rejects(self):
        with patch.object(config, "BACHS_WEBHOOK_SECRET", ""):
            body = b"{}"
            self.assertFalse(verify_webhook_signature(body, _sign(body)))

    def test_webhook_route_requires_signature(self):
        res = TestClient(app).post("/api/v1/payments/webhook/bachs", content=b'{"type":"collection.succeeded"}')
        self.assertEqual(res.status_code, 401)


class FakeDB:
    def __init__(self, order):
        self.order = order

    async def get(self, _model, key):
        return self.order if self.order and key == self.order.id else None


class BachsCollectionTests(unittest.IsolatedAsyncioTestCase):
    def _order(self):
        return Order(id="ORD-1", total=4500.0, currency="NGN", payment_status="unpaid")

    async def test_underpayment_rejected(self):
        with self.assertRaises(HTTPException):
            await PaymentService.apply_bachs_collection(
                FakeDB(self._order()), {"metadata": {"order_id": "ORD-1"}, "amount": "4000.00", "currency": "NGN", "charge_id": "ch_1"}
            )

    async def test_wrong_currency_rejected(self):
        with self.assertRaises(HTTPException):
            await PaymentService.apply_bachs_collection(
                FakeDB(self._order()), {"metadata": {"order_id": "ORD-1"}, "amount": "4500.00", "currency": "USD", "charge_id": "ch_1"}
            )

    async def test_unknown_order_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            await PaymentService.apply_bachs_collection(FakeDB(None), {"metadata": {"order_id": "nope"}})
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_full_payment_recorded(self):
        order = self._order()
        with patch.object(PaymentService, "record_charge", return_value={"verified": True}) as rec:
            await PaymentService.apply_bachs_collection(
                FakeDB(order), {"metadata": {"order_id": "ORD-1"}, "amount": "4500.00", "currency": "NGN", "charge_id": "ch_9"}
            )
        self.assertEqual(rec.call_args.kwargs["reference"], "bachs:ch_9")
        self.assertEqual(rec.call_args.kwargs["amount"], 4500.0)

    def test_money_format(self):
        self.assertEqual(money(4500), "4500.00")
        self.assertEqual(money(1234.565), "1234.57")


class GuestCheckoutTests(unittest.IsolatedAsyncioTestCase):
    def test_contact_validation(self):
        ok = {"customer_name": "Ada", "customer_phone": "0803 123 4567", "customer_email": "ADA@x.com"}
        self.assertEqual(OrderService._validate_guest_contact(ok), ("Ada", "0803 123 4567", "ada@x.com"))
        for bad in (
            {**ok, "customer_phone": "123"},
            {**ok, "customer_name": ""},
            {**ok, "customer_email": "not-an-email"},
        ):
            with self.assertRaises(HTTPException):
                OrderService._validate_guest_contact(bad)

    def test_email_optional(self):
        _, _, email = OrderService._validate_guest_contact({"customer_name": "Ada", "customer_phone": "08031234567"})
        self.assertIsNone(email)

    async def test_guest_token_must_match(self):
        order = Order(id="ORD-2", guest_token_hash=hash_guest_token("right"))
        self.assertIs(await OrderService.load_guest_order(FakeDB(order), "ORD-2", "right"), order)
        with self.assertRaises(HTTPException):
            await OrderService.load_guest_order(FakeDB(order), "ORD-2", "wrong")

    async def test_account_orders_not_reachable_by_guest_route(self):
        order = Order(id="ORD-3", guest_token_hash=None)
        with self.assertRaises(HTTPException):
            await OrderService.load_guest_order(FakeDB(order), "ORD-3", "anything")


if __name__ == "__main__":
    unittest.main()


class CheckoutPayloadTests(unittest.IsolatedAsyncioTestCase):
    async def _payload(self, email):
        from unittest.mock import AsyncMock, MagicMock
        from app.modules.payments import bachs_service

        res = MagicMock(status_code=201)
        res.json.return_value = {"checkout_id": "chk_1", "checkout_url": "https://sandbox-checkout.bachs.io/c/x"}
        client = MagicMock()
        client.post = AsyncMock(return_value=res)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        with patch.object(config, "BACHS_SECRET_KEY", "sk_sandbox_test"), \
             patch.object(bachs_service.httpx, "AsyncClient", return_value=client):
            await bachs_service.BachsService.create_checkout_session(
                order_id="ORD-1", amount=100, currency="NGN", reference="ORD-1-a", customer_email=email,
                customer_name="Ada", customer_phone="0800", success_url="https://x/s", cancel_url="https://x/c",
            )
        return client.post.call_args.kwargs["json"]

    async def test_guest_without_email_sends_no_customer(self):
        # Bachs rejects a customer object without email/customer_id.
        self.assertNotIn("customer", await self._payload(None))

    async def test_customer_with_email_included(self):
        payload = await self._payload("ada@example.com")
        self.assertEqual(payload["customer"]["email"], "ada@example.com")
        self.assertEqual(payload["pricing"], {"currency": "NGN", "amount": "100.00"})


class GuestCardEmailTests(unittest.IsolatedAsyncioTestCase):
    async def test_card_needs_email(self):
        with self.assertRaises(HTTPException) as ctx:
            await OrderService.create_guest_order(None, {"customer_name": "Ada", "customer_phone": "08031234567", "payment_method": "card"})
        self.assertIn("email", ctx.exception.detail)
