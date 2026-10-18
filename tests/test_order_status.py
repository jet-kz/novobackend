import unittest

from app.modules.orders.status import (
    STATUS_ALIASES,
    TransitionError,
    assert_transition_allowed,
    canonical_stored_status,
    normalize_order_status,
)


class OrderStatusMappingTests(unittest.TestCase):
    def test_frontend_aliases_map_to_backend_statuses(self):
        self.assertEqual(normalize_order_status("pending_merchant"), "PENDING")
        self.assertEqual(normalize_order_status("preparing"), "PREPARING")
        self.assertEqual(normalize_order_status("ready_for_pickup"), "READY_FOR_PICKUP")
        self.assertEqual(normalize_order_status("rider_assigned"), "RIDER_ASSIGNED")
        self.assertEqual(normalize_order_status("picked_up"), "PICKED_UP")
        self.assertEqual(normalize_order_status("out_for_delivery"), "PICKED_UP")
        self.assertEqual(normalize_order_status("delivered"), "DELIVERED")
        self.assertEqual(normalize_order_status("cancelled"), "CANCELLED")

    def test_lifecycle_steps_stay_distinct(self):
        # Regression: ready/rider_assigned/picked_up used to collapse into PREPARING/DISPATCHED.
        steps = ["pending_merchant", "preparing", "ready_for_pickup", "rider_assigned", "picked_up", "delivered"]
        self.assertEqual(len({normalize_order_status(s) for s in steps}), len(steps))

    def test_legacy_stored_values_are_mapped(self):
        self.assertEqual(canonical_stored_status("PLACED"), "PENDING")
        self.assertEqual(canonical_stored_status("DISPATCHED"), "PICKED_UP")
        self.assertEqual(canonical_stored_status(None), "PENDING")

    def test_empty_status_raises(self):
        with self.assertRaises(ValueError):
            normalize_order_status("")

    def test_alias_table_covers_core_journey(self):
        for key in ("pending", "confirmed", "preparing", "ready_for_pickup", "rider_assigned", "picked_up", "delivered"):
            self.assertIn(key, STATUS_ALIASES)


class TransitionRuleTests(unittest.TestCase):
    def test_full_happy_path_is_allowed(self):
        path = [
            ("PENDING", "CONFIRMED", "merchant"),
            ("CONFIRMED", "PREPARING", "merchant"),
            ("PREPARING", "READY_FOR_PICKUP", "merchant"),
            ("READY_FOR_PICKUP", "RIDER_ASSIGNED", "rider"),
            ("RIDER_ASSIGNED", "PICKED_UP", "rider"),
            ("PICKED_UP", "DELIVERED", "rider"),
        ]
        for current, target, actor in path:
            assert_transition_allowed(current, target, actor)

    def test_rider_can_finish_after_accepting(self):
        # Regression: DISPATCHED was terminal, so pickup/delivery after acceptance always failed.
        assert_transition_allowed("RIDER_ASSIGNED", "PICKED_UP", "rider")
        assert_transition_allowed("DISPATCHED", "DELIVERED", "rider")

    def test_terminal_states_are_final(self):
        for terminal in ("DELIVERED", "CANCELLED", "FAILED"):
            with self.assertRaises(TransitionError):
                assert_transition_allowed(terminal, "PREPARING", "admin")

    def test_no_skipping_steps(self):
        with self.assertRaises(TransitionError):
            assert_transition_allowed("PENDING", "DELIVERED", "admin")
        with self.assertRaises(TransitionError):
            assert_transition_allowed("READY_FOR_PICKUP", "PICKED_UP", "rider")

    def test_merchant_cannot_do_rider_steps(self):
        with self.assertRaises(TransitionError):
            assert_transition_allowed("READY_FOR_PICKUP", "RIDER_ASSIGNED", "merchant")
        with self.assertRaises(TransitionError):
            assert_transition_allowed("PICKED_UP", "DELIVERED", "merchant")

    def test_rider_cannot_do_merchant_steps(self):
        with self.assertRaises(TransitionError):
            assert_transition_allowed("PENDING", "CONFIRMED", "rider")
        with self.assertRaises(TransitionError):
            assert_transition_allowed("PREPARING", "CANCELLED", "rider")

    def test_merchant_cannot_cancel_after_handoff(self):
        with self.assertRaises(TransitionError):
            assert_transition_allowed("RIDER_ASSIGNED", "CANCELLED", "merchant")
        assert_transition_allowed("RIDER_ASSIGNED", "CANCELLED", "admin")


if __name__ == "__main__":
    unittest.main()
