"""
Canonical order lifecycle.

    PENDING -> CONFIRMED -> PREPARING -> READY_FOR_PICKUP -> RIDER_ASSIGNED -> PICKED_UP -> DELIVERED
                                                        \-> CANCELLED / FAILED

The frontend uses lowercase names (pending_merchant, ready_for_pickup, ...). Every
incoming value goes through normalize_order_status() so both spellings work, and
every transition goes through assert_transition_allowed() so the rules live in one place.
"""

PENDING = "PENDING"
CONFIRMED = "CONFIRMED"
PREPARING = "PREPARING"
READY_FOR_PICKUP = "READY_FOR_PICKUP"
RIDER_ASSIGNED = "RIDER_ASSIGNED"
PICKED_UP = "PICKED_UP"
DELIVERED = "DELIVERED"
CANCELLED = "CANCELLED"
FAILED = "FAILED"

ALL_STATUSES = {
    PENDING, CONFIRMED, PREPARING, READY_FOR_PICKUP,
    RIDER_ASSIGNED, PICKED_UP, DELIVERED, CANCELLED, FAILED,
}

TERMINAL_STATUSES = {DELIVERED, CANCELLED, FAILED}
# Kept for callers that imported the old name.
RESTRICTED_TRANSITIONS = TERMINAL_STATUSES

# Customers may cancel only before the kitchen starts work.
CANCELLABLE_STATUSES = {"CART", PENDING, CONFIRMED}

STATUS_ALIASES = {
    "pending_merchant": PENDING,
    "pending": PENDING,
    "new": PENDING,
    "placed": PENDING,  # legacy value written by old payment code
    "accepted": CONFIRMED,
    "confirmed": CONFIRMED,
    "preparing": PREPARING,
    "ready": READY_FOR_PICKUP,
    "ready_for_pickup": READY_FOR_PICKUP,
    "rider_assigned": RIDER_ASSIGNED,
    "assigned": RIDER_ASSIGNED,
    "picked_up": PICKED_UP,
    "out_for_delivery": PICKED_UP,
    "dispatched": PICKED_UP,  # legacy value
    "completed": DELIVERED,
    "delivered": DELIVERED,
    "cancelled": CANCELLED,
    "canceled": CANCELLED,
    "rejected": CANCELLED,
    "failed": FAILED,
    "cart": "CART",
}

ALLOWED_TRANSITIONS = {
    "CART": {PENDING, CANCELLED},
    PENDING: {CONFIRMED, PREPARING, CANCELLED},
    CONFIRMED: {PREPARING, CANCELLED},
    PREPARING: {READY_FOR_PICKUP, CANCELLED},
    READY_FOR_PICKUP: {RIDER_ASSIGNED, CANCELLED},
    RIDER_ASSIGNED: {PICKED_UP, READY_FOR_PICKUP, CANCELLED},
    PICKED_UP: {DELIVERED, FAILED},
}

# Which actor may move an order *into* each status.
MERCHANT_TARGETS = {CONFIRMED, PREPARING, READY_FOR_PICKUP, CANCELLED}
RIDER_TARGETS = {RIDER_ASSIGNED, PICKED_UP, DELIVERED, FAILED, READY_FOR_PICKUP}


class TransitionError(ValueError):
    pass


def normalize_order_status(raw: str | None) -> str:
    if not raw:
        raise ValueError("Status is required")
    key = str(raw).strip()
    aliased = STATUS_ALIASES.get(key.lower())
    if aliased:
        return aliased
    return key.upper()


def canonical_stored_status(raw: str | None) -> str:
    """Map legacy values already in the database (PLACED, DISPATCHED) onto the canonical set."""
    if not raw:
        return PENDING
    try:
        return normalize_order_status(raw)
    except ValueError:
        return PENDING


def assert_transition_allowed(current: str, target: str, actor: str) -> None:
    """
    actor is one of: admin, merchant, rider.
    Raises TransitionError with a user-facing message when the move is not allowed.
    """
    current = canonical_stored_status(current)
    if target not in ALL_STATUSES:
        raise TransitionError(f"Unknown order status: {target}")
    if current in TERMINAL_STATUSES:
        raise TransitionError(f"Order is already {current.lower()} and can no longer change")
    if target == current:
        raise TransitionError(f"Order is already {current.lower()}")
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise TransitionError(f"Cannot move an order from {current.lower()} to {target.lower()}")
    if actor == "admin":
        return
    if actor == "merchant" and target in MERCHANT_TARGETS:
        if target == CANCELLED and current not in {PENDING, CONFIRMED, PREPARING}:
            raise TransitionError("Merchants can only cancel orders that have not been handed to a rider")
        return
    if actor == "rider" and target in RIDER_TARGETS:
        if target == READY_FOR_PICKUP and current != RIDER_ASSIGNED:
            raise TransitionError("Only an assigned rider can release a job")
        return
    raise TransitionError(f"You are not allowed to set an order to {target.lower()}")
