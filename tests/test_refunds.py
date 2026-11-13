"""Refund rules: Bachs request shape, failure handling, admin validation. No network or database."""
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.security import get_current_user
from app.main import app
from app.modules.orders.models import Order
from app.modules.payments.bachs_service import BachsError
from app.modules.payments.models import PaymentTransaction, Refund
from app.modules.payments.refunds import RefundService, _bachs_status, bachs_charge_id, cancel_reason_code

ADMIN = {"user_id": "admin-1", "email": "a@example.com", "roles": ["admin"], "raw_payload": {}}
CUSTOMER = {"user_id": "cust-1", "email": "c@example.com", "roles": ["customer"], "raw_payload": {}}


class _Result:
    def __init__(self, value=None):
        self.value = value

    def scalars(self):
        return self

    def first(self):
        return self.value


class FakeDB:
    def __init__(self, prior_refund=None):
        self.prior_refund = prior_refund
        self.added = []
        self.commits = 0

    async def execute(self, *_args, **_kwargs):
        return _Result(self.prior_refund)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1


def _order(status="CANCELLED"):
    return Order(id="ORD-1", status=status, payment_status="paid", total=5000.0, currency="NGN")


def _txn(charge_id="ch_123", provider="bachs", amount=5000.0):
    return PaymentTransaction(
        payment_id=uuid.uuid4(), txn_type="charge", provider=provider, provider_reference=f"{provider}:{charge_id}",
        amount=amount, currency="NGN", status="success", provider_metadata={"charge_id": charge_id, "checkout_id": "chk_1"},
    )


class HelperTests(unittest.TestCase):
    def test_charge_id(self):
        self.assertEqual(bachs_charge_id(_txn()), "ch_123")
        self.assertIsNone(bachs_charge_id(_txn(provider="paystack")))
        no_meta = _txn()
        no_meta.provider_metadata = {}
        no_meta.provider_reference = "bachs:chk_9"  # a checkout id is not refundable
        self.assertIsNone(bachs_charge_id(no_meta))

    def test_status_mapping(self):
        # The docs disagree ('success' vs 'paid'); both mean done.
        self.assertEqual(_bachs_status("success"), "succeeded")
        self.assertEqual(_bachs_status("paid"), "succeeded")
        self.assertEqual(_bachs_status("failed"), "failed")
        self.assertEqual(_bachs_status("processing"), "processing")

    def test_cancel_reasons(self):
        self.assertEqual(cancel_reason_code("merchant", "CANCELLED"), "store_cancelled")
        self.assertEqual(cancel_reason_code("rider", "FAILED"), "delivery_failed")
        self.assertEqual(cancel_reason_code(None, "CANCELLED"), "customer_cancelled")


class RefundChargeTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, txn, db=None, bachs=None, **kwargs):
        db = db or FakeDB()
        bachs = bachs or AsyncMock(return_value={"refund_id": "rfnd_1", "status": "processing"})
        with patch("app.modules.payments.refunds.bachs_request", bachs), \
             patch.object(RefundService, "sync_order_status", AsyncMock()), \
             patch.object(RefundService, "_notify"):
            refund = await RefundService.refund_charge(db, _order(), txn, reason_code="store_cancelled", **kwargs)
        return refund, bachs, db

    async def test_full_refund_omits_amount(self):
        refund, bachs, _ = await self._run(_txn())
        method, path = bachs.call_args.args
        body = bachs.call_args.kwargs["json"]
        self.assertEqual((method, path), ("POST", "/v1/refunds"))
        self.assertEqual(body["charge_id"], "ch_123")
        self.assertNotIn("amount", body)
        self.assertEqual(body["idempotency_key"], refund.reference)
        self.assertEqual(refund.status, "processing")
        self.assertEqual(refund.provider_refund_id, "rfnd_1")
        self.assertEqual(refund.bearer, "platform")

    async def test_partial_refund_sends_amount(self):
        refund, bachs, _ = await self._run(_txn(), amount=1200, bearer="merchant")
        self.assertEqual(bachs.call_args.kwargs["json"]["amount"], "1200.00")
        self.assertEqual(refund.amount, 1200)
        self.assertEqual(refund.bearer, "merchant")

    async def test_cannot_refund_more_than_paid(self):
        with self.assertRaises(HTTPException):
            await self._run(_txn(), amount=6000)

    async def test_one_refund_per_charge(self):
        with self.assertRaises(HTTPException) as ctx:
            await self._run(_txn(), db=FakeDB(prior_refund=Refund(status="processing")))
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_insufficient_balance_is_saved_as_failed(self):
        bachs = AsyncMock(side_effect=BachsError(400, "Insufficient balance to refund"))
        refund, _, db = await self._run(_txn(), bachs=bachs)
        self.assertEqual(refund.status, "failed")
        self.assertIn("Top up", refund.failure_reason)
        self.assertIn(refund, db.added)

    async def test_conflict_recovers_existing_refund(self):
        calls = [BachsError(409, "A refund already exists for this charge"), {"refund_id": "rfnd_9", "status": "success"}]

        async def fake(*_a, **_k):
            item = calls.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        refund, _, _ = await self._run(_txn(), bachs=AsyncMock(side_effect=fake))
        self.assertEqual(refund.status, "succeeded")
        self.assertEqual(refund.provider_refund_id, "rfnd_9")

    async def test_non_bachs_payment_needs_manual_refund(self):
        refund, bachs, _ = await self._run(_txn(provider="paystack"))
        bachs.assert_not_called()
        self.assertEqual(refund.status, "failed")
        self.assertIn("bank transfer", refund.failure_reason)


class AdminRefundApiTests(unittest.TestCase):
    def tearDown(self):
        app.dependency_overrides.clear()

    def _as(self, user):
        app.dependency_overrides[get_current_user] = lambda: user
        return TestClient(app)

    def test_validation(self):
        client = self._as(ADMIN)
        url = "/api/v1/admin/orders/ORD-1/refund"
        self.assertEqual(client.post(url, json={}).status_code, 400)
        self.assertEqual(client.post(url, json={"method": "manual"}).status_code, 400)
        self.assertEqual(client.post(url, json={"method": "bachs", "bearer": "customer"}).status_code, 400)
        self.assertEqual(client.post(url, json={"method": "bachs", "reason": "nope"}).status_code, 400)
        self.assertEqual(client.post(url, json={"method": "bachs", "amount": "abc"}).status_code, 400)

    def test_customers_cannot_refund(self):
        client = self._as(CUSTOMER)
        self.assertEqual(client.post("/api/v1/admin/orders/ORD-1/refund", json={"method": "bachs"}).status_code, 403)
        # The old self-service endpoint is gone.
        self.assertIn(client.post("/api/v1/payments/00000000-0000-0000-0000-000000000000/refunds", json={}).status_code, (404, 405))


if __name__ == "__main__":
    unittest.main()
