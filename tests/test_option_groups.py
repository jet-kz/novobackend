import unittest
import uuid
from types import SimpleNamespace

from app.modules.orders.service import delivery_code_for, eta_minutes, pickup_code_for, price_order_items
from app.modules.products.options import (
    OptionGroupError,
    effective_option_groups,
    normalize_option_groups,
    price_selection,
)

STORE = uuid.uuid4()

PROTEIN = {
    "id": "protein", "name": "Choose your protein", "min": 1, "max": 1,
    "options": [
        {"id": "chicken", "name": "Chicken", "price": 0},
        {"id": "beef", "name": "Beef", "price": 500},
        {"id": "goat", "name": "Goat meat", "price": 900, "available": False},
    ],
}
EXTRAS = {
    "id": "extras", "name": "Extras", "min": 0, "max": 3,
    "options": [
        {"id": "plantain", "name": "Plantain", "price": 300, "max_qty": 3},
        {"id": "egg", "name": "Boiled egg", "price": 200},
    ],
}


def product(groups=None, **legacy):
    return SimpleNamespace(
        id=uuid.uuid4(), name="Jollof", price=2000.0, store_id=STORE, in_stock=True,
        option_groups=groups or [], protein_options=legacy.get("protein", []),
        extras_options=legacy.get("extras", []), options=[],
    )


class NormalizeTests(unittest.TestCase):
    def test_fills_ids_and_clamps_limits(self):
        out = normalize_option_groups([{"name": "Size", "min": 5, "max": 9, "options": [{"name": "Big", "price": "100"}]}])
        g = out[0]
        self.assertTrue(g["id"] and g["options"][0]["id"])
        self.assertEqual((g["min"], g["max"]), (1, 1))  # one option, picked once at most
        self.assertEqual(g["options"][0]["price"], 100.0)

    def test_rejects_nameless_group_and_empty_group(self):
        with self.assertRaises(OptionGroupError):
            normalize_option_groups([{"name": "", "options": [{"name": "x"}]}])
        with self.assertRaises(OptionGroupError):
            normalize_option_groups([{"name": "Drinks", "options": []}])

    def test_rejects_negative_price(self):
        with self.assertRaises(OptionGroupError):
            normalize_option_groups([{"name": "Drinks", "options": [{"name": "Coke", "price": -5}]}])

    def test_legacy_columns_become_groups(self):
        p = product(protein=[{"id": "p1", "name": "Fish", "price": 300}], extras=[{"id": "e1", "name": "Salad", "price": 200}])
        groups = effective_option_groups(p)
        self.assertEqual([g["name"] for g in groups], ["Choose your protein", "Add extras"])
        self.assertEqual(groups[0]["min"], 1)
        self.assertEqual(groups[1]["min"], 0)


class SelectionTests(unittest.TestCase):
    def test_prices_quantities(self):
        p = product([PROTEIN, EXTRAS])
        addons, total = price_selection(p, [{"id": "beef"}, {"id": "plantain", "quantity": 2}])
        self.assertEqual(total, 500 + 600)
        self.assertEqual({a["id"]: a["quantity"] for a in addons}, {"beef": 1, "plantain": 2})

    def test_required_group_enforced(self):
        with self.assertRaises(ValueError) as ctx:
            price_selection(product([PROTEIN, EXTRAS]), [{"id": "plantain"}])
        self.assertIn("Choose your protein", str(ctx.exception))

    def test_group_max_enforced(self):
        with self.assertRaises(ValueError):
            price_selection(product([PROTEIN]), [{"id": "chicken"}, {"id": "beef"}])
        with self.assertRaises(ValueError):
            price_selection(product([PROTEIN, EXTRAS]), [{"id": "chicken"}, {"id": "plantain", "quantity": 3}, {"id": "egg"}])

    def test_sold_out_option_rejected(self):
        with self.assertRaises(ValueError):
            price_selection(product([PROTEIN]), [{"id": "goat"}])

    def test_per_option_quantity_cap(self):
        with self.assertRaises(ValueError):
            price_selection(product([PROTEIN, EXTRAS]), [{"id": "chicken"}, {"id": "egg", "quantity": 2}])

    def test_order_line_includes_options(self):
        p = product([PROTEIN, EXTRAS])
        items, subtotal = price_order_items(
            [{"product_id": str(p.id), "quantity": 2, "addons": [{"id": "beef"}, {"id": "egg"}]}], {p.id: p}, STORE
        )
        self.assertEqual(items[0]["price"], 2700)
        self.assertEqual(subtotal, 5400)


class DeliveryCodeTests(unittest.TestCase):
    def test_stable_four_digits_and_distinct_from_pickup(self):
        code = delivery_code_for("ORD-1")
        self.assertEqual(code, delivery_code_for("ORD-1"))
        self.assertRegex(code, r"^\d{4}$")
        self.assertNotEqual(code, pickup_code_for("ORD-1"))

    def test_eta_reasonable(self):
        # ~3.3 km across Warri
        self.assertTrue(5 <= eta_minutes(5.5167, 5.7500, 5.5400, 5.7700) <= 20)
        self.assertEqual(eta_minutes(5.5, 5.7, 5.5, 5.7), 1)


if __name__ == "__main__":
    unittest.main()
