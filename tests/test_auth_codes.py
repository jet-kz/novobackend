"""Email verification / password reset codes: hashing, attempt limits, consumption."""
import unittest
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from app.modules.auth.models import EmailCode
from app.modules.auth.service import CODE_MAX_ATTEMPTS, AuthService, _hash_code


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeSession:
    """Returns one preset EmailCode for every query and counts commits."""

    def __init__(self, record):
        self.record = record
        self.commits = 0

    async def execute(self, _stmt):
        return _Result(self.record)

    async def commit(self):
        self.commits += 1


def make_code(code="123456", purpose="signup", attempts=0):
    return EmailCode(
        email="ada@example.com",
        purpose=purpose,
        code_hash=_hash_code("ada@example.com", purpose, code),
        attempts=attempts,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )


class ConsumeCodeTests(unittest.IsolatedAsyncioTestCase):
    async def test_correct_code_is_consumed(self):
        record = make_code()
        db = FakeSession(record)
        self.assertTrue(await AuthService._consume_code(db, "ada@example.com", "signup", " 123456 "))
        self.assertIsNotNone(record.consumed_at)

    async def test_wrong_code_counts_an_attempt(self):
        record = make_code()
        db = FakeSession(record)
        with self.assertRaises(HTTPException) as ctx:
            await AuthService._consume_code(db, "ada@example.com", "signup", "000000")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(record.attempts, 1)
        self.assertIsNone(record.consumed_at)

    async def test_locked_after_max_attempts(self):
        record = make_code(attempts=CODE_MAX_ATTEMPTS)
        with self.assertRaises(HTTPException) as ctx:
            await AuthService._consume_code(FakeSession(record), "ada@example.com", "signup", "123456")
        self.assertEqual(ctx.exception.status_code, 429)

    async def test_code_is_bound_to_purpose(self):
        record = make_code(purpose="signup")
        with self.assertRaises(HTTPException):
            await AuthService._consume_code(FakeSession(record), "ada@example.com", "reset", "123456")

    async def test_no_live_code(self):
        self.assertFalse(await AuthService._consume_code(FakeSession(None), "ada@example.com", "signup", "123456"))


if __name__ == "__main__":
    unittest.main()
