import unittest
import uuid
from types import SimpleNamespace

from app.modules.orders.service import haversine_km, pickup_code_for, price_order_items

STORE = uuid.uuid4()
OTHER_STORE = uuid.uuid4()


def product(price=1000.0, store_id=STORE, in_stock=True, **opts):
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="Jollof",
        price=price,
        store_id=store_id,
        in_stock=in_stock,
        protein_options=opts.get("protein_options", []),
        extras_options=opts.get("extras_options", []),
        option_groups=opts.get("option_groups", []),
        options=[],
    )


class PriceOrderItemsTests(unittest.TestCase):
    def test_uses_catalogue_price_not_client_price(self):
        p = product(price=2500)
        items, subtotal = price_order_items(
            [{"product_id": str(p.id), "quantity": 2, "price": 1}], {p.id: p}, STORE
        )
        self.assertEqual(items[0]["price"], 2500)
        self.assertEqual(subtotal, 5000)

    def test_addons_priced_from_product_definition(self):
        p = product(price=1000, option_groups=[{"id": "g", "options": [{"id": "chicken", "price": 700}]}])
        items, subtotal = price_order_items(
            [{"product_id": str(p.id), "quantity": 1, "addons": [{"id": "chicken", "price": 0}]}], {p.id: p}, STORE
        )
        self.assertEqual(items[0]["price"], 1700)
        self.assertEqual(subtotal, 1700)

    def test_unknown_addon_rejected(self):
        p = product()
        with self.assertRaises(ValueError):
            price_order_items([{"product_id": str(p.id), "addons": [{"id": "free-lobster", "price": 0}]}], {p.id: p}, STORE)

    def test_mixed_store_rejected(self):
        p = product(store_id=OTHER_STORE)
        with self.assertRaises(ValueError):
            price_order_items([{"product_id": str(p.id)}], {p.id: p}, STORE)

    def test_out_of_stock_rejected(self):
        p = product(in_stock=False)
        with self.assertRaises(ValueError):
            price_order_items([{"product_id": str(p.id)}], {p.id: p}, STORE)

    def test_bad_quantity_rejected(self):
        p = product()
        for qty in (0, -3, 1000):
            with self.assertRaises(ValueError):
                price_order_items([{"product_id": str(p.id), "quantity": qty}], {p.id: p}, STORE)

    def test_empty_and_unknown_products_rejected(self):
        with self.assertRaises(ValueError):
            price_order_items([], {}, STORE)
        with self.assertRaises(ValueError):
            price_order_items([{"product_id": str(uuid.uuid4())}], {}, STORE)

    def test_nested_product_shape_from_cart(self):
        p = product(price=300)
        items, _ = price_order_items([{"product": {"id": str(p.id)}, "quantity": 3}], {p.id: p}, STORE)
        self.assertEqual(items[0]["quantity"], 3)


class HelperTests(unittest.TestCase):
    def test_pickup_code_is_stable_four_digits(self):
        code = pickup_code_for("ORD-ABC")
        self.assertEqual(code, pickup_code_for("ORD-ABC"))
        self.assertTrue(code.isdigit() and len(code) == 4)

    def test_haversine(self):
        self.assertAlmostEqual(haversine_km(6.5244, 3.3792, 6.5244, 3.3792), 0.0)
        # Lagos Island -> Ikeja is roughly 9 km as the crow flies
        self.assertTrue(8.5 < haversine_km(6.5244, 3.3792, 6.6018, 3.3515) < 9.8)


if __name__ == "__main__":
    unittest.main()
