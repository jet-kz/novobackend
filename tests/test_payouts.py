"""Payout safety checks and Bachs response parsing. No network: bachs_request is patched."""
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.security import get_current_user
from app.main import app
from app.modules.payments.bachs_service import available_amount, capability_status, requirements_due
from app.modules.payouts.models import PayoutAccount
from app.modules.payouts.service import PayoutService

CUSTOMER = {"user_id": "cust-1", "email": "c@example.com", "roles": ["customer"], "raw_payload": {}}


class ParsingTests(unittest.TestCase):
    def test_capability_shapes(self):
        self.assertEqual(capability_status({"capabilities": {"payouts": "active"}}, "payouts"), "active")
        self.assertEqual(capability_status({"capabilities": {"payouts": {"status": "pending_review"}}}, "payouts"), "pending_review")
        self.assertEqual(capability_status({"capabilities": [{"name": "transfers", "status": "active"}]}, "transfers"), "active")
        self.assertEqual(capability_status({}, "payouts"), "")

    def test_requirements(self):
        self.assertEqual(requirements_due({"requirements": {"currently_due": ["persons.0.dob"]}}), ["persons.0.dob"])
        self.assertEqual(requirements_due({}), [])

    def test_available_amount(self):
        self.assertEqual(available_amount([{"currency": "NGN", "available_balance": "1500.50"}]), 1500.5)
        self.assertEqual(available_amount({"balances": [{"currency": "USD", "available": "9"}, {"currency": "NGN", "available": "20"}]}), 20.0)
        self.assertEqual(available_amount([]), 0.0)


class FakeDB:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass


class SettleGuardTests(unittest.IsolatedAsyncioTestCase):
    async def _settle(self, account, owed, amount):
        with patch.object(PayoutService, "account_for", AsyncMock(return_value=account)), \
             patch.object(PayoutService, "refresh_account", AsyncMock(side_effect=lambda db, a: a)), \
             patch.object(PayoutService, "earnings", AsyncMock(return_value={"owed": owed})), \
             patch("app.modules.payouts.service.bachs_request", AsyncMock(return_value={"id": "tr_1", "status": "paid"})) as req:
            result = await PayoutService.settle(FakeDB(), "merchant", "m-1", amount, None, "admin-1")
            return result, req

    def _account(self, transfers=True):
        return PayoutAccount(owner_type="merchant", owner_id="m-1", user_id="u-1", bachs_account_id="acct_1", transfers_enabled=transfers)

    async def test_cannot_settle_more_than_owed(self):
        with self.assertRaises(HTTPException):
            await self._settle(self._account(), owed=1000, amount=1500)

    async def test_unverified_account_blocked(self):
        with self.assertRaises(HTTPException) as ctx:
            await self._settle(self._account(transfers=False), owed=1000, amount=500)
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_no_account_blocked(self):
        with self.assertRaises(HTTPException):
            await self._settle(None, owed=1000, amount=500)

    async def test_settlement_transfers_with_idempotency_key(self):
        with patch("app.modules.notifications.service.settlement_sent"):
            settlement, req = await self._settle(self._account(), owed=1000, amount=400)
        self.assertEqual(settlement.status, "paid")
        self.assertEqual(settlement.bachs_transfer_id, "tr_1")
        args, kwargs = req.call_args
        self.assertEqual(args[:2], ("POST", "/v1/transfers"))
        self.assertEqual(kwargs["json"]["amount"], "400.00")
        self.assertEqual(kwargs["json"]["destination"], "acct_1")
        self.assertTrue(kwargs["idempotency_key"].startswith("novo-settlement-"))


class RouteAccessTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[get_current_user] = lambda: CUSTOMER
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_customer_cannot_settle(self):
        res = self.client.post("/api/v1/payouts/admin/settle", json={"payee_type": "merchant", "payee_id": "x", "amount": 1})
        self.assertEqual(res.status_code, 403)

    def test_customer_has_no_payouts(self):
        self.assertEqual(self.client.get("/api/v1/payouts/me").status_code, 403)


if __name__ == "__main__":
    unittest.main()
