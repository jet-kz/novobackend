"""Push subscription validation and gone-subscription cleanup."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core import push
from app.main import app

VALID = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": {"p256dh": "k", "auth": "a"}}


class SubscribeRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_rejects_non_https_endpoint(self):
        res = self.client.post("/api/v1/notifications/push/subscribe", json={"subscription": {**VALID, "endpoint": "http://x"}})
        self.assertEqual(res.status_code, 400)

    def test_needs_account_or_guest_order(self):
        res = self.client.post("/api/v1/notifications/push/subscribe", json={"subscription": VALID})
        self.assertEqual(res.status_code, 401)

    def test_public_key_endpoint(self):
        res = self.client.get("/api/v1/notifications/push/key")
        self.assertEqual(res.status_code, 200)
        self.assertIn("public_key", res.json()["data"])


class SendPushTests(unittest.IsolatedAsyncioTestCase):
    async def test_gone_subscriptions_reported(self):
        subs = [SimpleNamespace(endpoint=f"https://p/{i}", p256dh="k", auth="a") for i in range(3)]
        codes = iter([201, 410, 404])
        with patch.object(push, "push_enabled", return_value=True), \
             patch.object(push, "_send_one", side_effect=lambda sub, payload: next(codes)):
            gone = await push.send_push(subs, "t", "b")
        self.assertEqual([s.endpoint for s in gone], ["https://p/1", "https://p/2"])

    async def test_disabled_sends_nothing(self):
        with patch.object(push, "push_enabled", return_value=False):
            self.assertEqual(await push.send_push([SimpleNamespace(endpoint="x", p256dh="k", auth="a")], "t", "b"), [])


if __name__ == "__main__":
    unittest.main()
