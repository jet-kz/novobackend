"""
Payment helpers plus route-level authorization checks.
Route tests override auth and never reach the database: they assert the request is
rejected by role checks before any query runs.
"""
import hashlib
import hmac
import unittest

from fastapi.testclient import TestClient

from app.core import config
from app.core.security import get_current_user
from app.main import app
from app.modules.addresses.service import _map_fields
from app.modules.payments.service import amount_covers_order, order_id_from_reference, valid_paystack_signature

CUSTOMER = {"user_id": "cust-1", "email": "c@example.com", "roles": ["customer"], "raw_payload": {}}


class PaymentHelperTests(unittest.TestCase):
    def test_reference_maps_back_to_order(self):
        self.assertEqual(order_id_from_reference("ORD-ABC123_1700000000000"), "ORD-ABC123")
        self.assertEqual(order_id_from_reference("ORD-ABC123"), "ORD-ABC123")

    def test_underpayment_rejected(self):
        self.assertTrue(amount_covers_order(550000, 5500.0))
        self.assertFalse(amount_covers_order(10000, 5500.0))
        self.assertFalse(amount_covers_order(0, 1.0))

    def test_webhook_signature(self):
        body = b'{"event":"charge.success"}'
        sig = hmac.new(b"sk_test_x", body, hashlib.sha512).hexdigest()
        self.assertTrue(valid_paystack_signature(body, sig, "sk_test_x"))
        self.assertFalse(valid_paystack_signature(body, sig, "other"))
        self.assertFalse(valid_paystack_signature(body, "", "sk_test_x"))
        self.assertFalse(valid_paystack_signature(body, sig, ""))


class AddressMappingTests(unittest.TestCase):
    def test_frontend_field_names_accepted(self):
        out = _map_fields({"title": "Work", "address": "12 Adeola Street", "city": "Lagos"})
        self.assertEqual(out["label"], "Work")
        self.assertEqual(out["address_text"], "12 Adeola Street, Lagos")

    def test_city_not_duplicated(self):
        out = _map_fields({"address": "12 Adeola Street, Lagos", "city": "Lagos"})
        self.assertEqual(out["address_text"], "12 Adeola Street, Lagos")


class UnauthenticatedAccessTests(unittest.TestCase):
    def setUp(self):
        self._prev = config.ALLOW_INSECURE_DEV_AUTH
        config.ALLOW_INSECURE_DEV_AUTH = False
        self.client = TestClient(app)

    def tearDown(self):
        config.ALLOW_INSECURE_DEV_AUTH = self._prev

    def test_protected_routes_require_token(self):
        for method, path in [
            ("get", "/api/v1/orders"),
            ("post", "/api/v1/orders"),
            ("get", "/api/v1/wallets"),
            ("get", "/api/v1/auth/me"),
        ]:
            res = getattr(self.client, method)(path, **({"json": {}} if method == "post" else {}))
            self.assertEqual(res.status_code, 401, f"{method.upper()} {path} -> {res.status_code}")

    def test_unsigned_webhook_rejected(self):
        res = self.client.post("/api/v1/payments/webhook", json={"event": "charge.success", "data": {"reference": "ORD-1"}})
        self.assertEqual(res.status_code, 401)


class CustomerRoleTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[get_current_user] = lambda: CUSTOMER
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_admin_only_routes_forbidden_for_customer(self):
        for method, path, body in [
            ("post", "/api/v1/wallets/credit", {"amount": 1_000_000}),
            ("post", "/api/v1/payments/00000000-0000-0000-0000-000000000000/transactions", {"status": "success"}),
            ("get", "/api/v1/users", None),
            ("get", "/api/v1/riders", None),
            ("get", "/api/v1/merchants", None),
            ("patch", "/api/v1/stores/00000000-0000-0000-0000-000000000000/verify", {}),
            ("get", "/api/v1/pricing/rules/commission", None),
        ]:
            kwargs = {"json": body} if body is not None else {}
            res = getattr(self.client, method)(path, **kwargs)
            self.assertEqual(res.status_code, 403, f"{method.upper()} {path} -> {res.status_code}")

    def test_rider_only_routes_forbidden_for_customer(self):
        res = self.client.patch("/api/v1/riders/me/status", json={"status": "online"})
        self.assertEqual(res.status_code, 403)

    def test_missing_status_is_a_400_not_a_crash(self):
        # Regression: a `status` query param shadowed fastapi.status and this path raised a 500.
        res = self.client.patch("/api/v1/orders/ORD-X/status", json={})
        self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main()
