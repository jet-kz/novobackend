"""Admin console access rules (no database: checks fail before any query)."""
import unittest

from fastapi.testclient import TestClient

from app.core.security import get_current_user
from app.main import app

CUSTOMER = {"user_id": "cust-1", "email": "c@example.com", "roles": ["customer"], "raw_payload": {}}
ADMIN = {"user_id": "admin-1", "email": "a@example.com", "roles": ["admin"], "raw_payload": {}}


class AdminAccessTests(unittest.TestCase):
    def tearDown(self):
        app.dependency_overrides.clear()

    def _as(self, user):
        app.dependency_overrides[get_current_user] = lambda: user
        return TestClient(app)

    def test_customers_blocked_from_admin_api(self):
        client = self._as(CUSTOMER)
        for method, path in (("get", "/api/v1/admin/overview"), ("get", "/api/v1/admin/users"),
                             ("get", "/api/v1/admin/orders"), ("post", "/api/v1/admin/users/x/suspend")):
            self.assertEqual(getattr(client, method)(path).status_code, 403, path)

    def test_plain_admin_cannot_manage_admins(self):
        client = self._as(ADMIN)
        self.assertEqual(client.post("/api/v1/admin/admins", json={"email": "new@example.com"}).status_code, 403)
        self.assertEqual(client.put("/api/v1/admin/users/x/admin", json={"grant": True}).status_code, 403)

    def test_cannot_suspend_yourself(self):
        res = self._as(ADMIN).post("/api/v1/admin/users/admin-1/suspend", json={})
        self.assertEqual(res.status_code, 400)

    def test_refund_needs_reference(self):
        res = self._as(ADMIN).post("/api/v1/admin/orders/ORD-1/refund", json={})
        self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main()
