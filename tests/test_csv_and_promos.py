import csv
import io
import unittest
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

from fastapi import HTTPException

from app.modules.pricing import merchant_promos
from app.modules.products import csv_io


def product(name, price=1000.0, **kw):
    return SimpleNamespace(
        id=uuid.uuid4(), name=name, price=price, description=kw.get("description"), in_stock=True, image=None,
        category=SimpleNamespace(name=kw.get("section", "Mains")), specs=kw.get("specs", {}),
        preparation_time_minutes=kw.get("prep", 20), option_groups=kw.get("groups", []),
        protein_options=[], extras_options=[], options=[],
    )


def rows_of(text):
    return list(csv.reader(io.StringIO(text.lstrip("﻿"))))


class TemplateTests(unittest.TestCase):
    def test_templates_parse_cleanly(self):
        for kind in csv_io.KINDS:
            result = csv_io.parse_rows(csv_io.template_csv(kind), kind, [])
            self.assertEqual(result["file_errors"], [], kind)
            self.assertEqual(result["summary"]["errors"], 0, (kind, [r["errors"] for r in result["rows"]]))
            self.assertEqual(result["summary"]["create"], 3)

    def test_kind_for_store_type(self):
        self.assertEqual(csv_io.kind_for_store_type("restaurant"), "food")
        self.assertEqual(csv_io.kind_for_store_type("pharmacy"), "pharmacy")
        self.assertEqual(csv_io.kind_for_store_type("supermarket"), "grocery")


class ImportTests(unittest.TestCase):
    def test_validation_errors(self):
        text = "name,price,in_stock,image_url\nA,abc,maybe,http://x\n"
        r = csv_io.parse_rows(text, "food", [])["rows"][0]
        joined = " ".join(r["errors"])
        self.assertIn("Name is required", joined)
        self.assertIn("Price must be a number", joined)
        self.assertIn("in_stock", joined)
        self.assertIn("https://", joined)

    def test_missing_required_column(self):
        r = csv_io.parse_rows("name,price\nParacetamol,500\n", "pharmacy", [])
        self.assertTrue(r["file_errors"])
        self.assertIn("requires_prescription", r["file_errors"][0])

    def test_pharmacy_needs_prescription_answer_and_known_form(self):
        text = "name,price,requires_prescription,dosage_form\nAmoxil,2500,,Pill\n"
        errs = " ".join(csv_io.parse_rows(text, "pharmacy", [])["rows"][0]["errors"])
        self.assertIn("requires_prescription", errs)
        self.assertIn("dosage_form", errs)

    def test_price_formats(self):
        r = csv_io.parse_rows('name,price\nRice,"₦1,800"\n', "grocery", [])["rows"][0]
        self.assertEqual(r["errors"], [])
        self.assertEqual(r["data"]["price"], 1800)

    def test_matches_existing_by_name_and_id(self):
        jollof = product("Jollof")
        text = f"id,name,price\n,jollof,3000\n{jollof.id},Jollof special,3200\n"
        rows = csv_io.parse_rows(text, "food", [jollof])["rows"]
        self.assertEqual(rows[0]["action"], "update")
        self.assertEqual(rows[1]["action"], "update")
        bad = csv_io.parse_rows(f"id,name,price\n{uuid.uuid4()},X item,100\n", "food", [jollof])["rows"][0]
        self.assertTrue(bad["errors"])

    def test_duplicate_names_flagged(self):
        rows = csv_io.parse_rows("name,price\nSuya,1000\nsuya,1200\n", "food", [])["rows"]
        self.assertTrue(rows[1]["errors"])

    def test_formula_cells_are_neutralised_on_export(self):
        p = product("=HYPERLINK(evil)")
        out = rows_of(csv_io.export_csv("food", [p]))
        self.assertTrue(out[1][1].startswith("'="))
        # and read back as the plain name
        back = csv_io.parse_rows(csv_io.export_csv("food", [p]), "food", [p])["rows"][0]
        self.assertEqual(back["name"], "=HYPERLINK(evil)")


class OptionsTextTests(unittest.TestCase):
    def test_parse(self):
        groups = csv_io.parse_options("Choose your protein (required): Chicken=0, Beef=500; Extras (up to 3): Plantain=300 x3, Egg=200")
        self.assertEqual([g["name"] for g in groups], ["Choose your protein", "Extras"])
        self.assertEqual((groups[0]["min"], groups[0]["max"]), (1, 1))
        self.assertEqual(groups[1]["max"], 3)
        self.assertEqual(groups[1]["options"][0]["max_qty"], 3)

    def test_round_trip(self):
        text = "Size (required): Small=0, Large=800; Drinks (up to 2): Coke=500, Water=200 (sold out)"
        groups = csv_io.parse_options(text)
        again = csv_io.parse_options(csv_io.format_options(groups))
        strip = lambda gs: [(g["name"], g["min"], g["max"], [(o["name"], o["price"], o["available"]) for o in g["options"]]) for g in gs]  # noqa: E731
        self.assertEqual(strip(groups), strip(again))

    def test_bad_options(self):
        with self.assertRaises(ValueError):
            csv_io.parse_options("Protein Chicken, Beef")


class PromoRuleTests(unittest.TestCase):
    def ends(self, days=7):
        return (datetime.utcnow() + timedelta(days=days)).isoformat()

    def test_percentage_bounds(self):
        with self.assertRaises(HTTPException):
            merchant_promos.validate_terms({"promo_type": "PERCENTAGE", "discount_value": 70, "ends_at": self.ends()})
        ok = merchant_promos.validate_terms({"promo_type": "PERCENTAGE", "discount_value": 20, "ends_at": self.ends()})
        self.assertEqual(ok["discount_value"], 20)

    def test_fixed_needs_twice_the_min_order(self):
        with self.assertRaises(HTTPException) as ctx:
            merchant_promos.validate_terms({"promo_type": "FIXED", "discount_value": 1000, "min_order_amount": 1500, "ends_at": self.ends()})
        self.assertIn("2,000", ctx.exception.detail)
        merchant_promos.validate_terms({"promo_type": "FIXED", "discount_value": 1000, "min_order_amount": 2000, "ends_at": self.ends()})

    def test_needs_end_date_within_limit(self):
        with self.assertRaises(HTTPException):
            merchant_promos.validate_terms({"promo_type": "FREE_DELIVERY"})
        with self.assertRaises(HTTPException):
            merchant_promos.validate_terms({"promo_type": "FREE_DELIVERY", "ends_at": self.ends(120)})

    def test_state(self):
        now = datetime.utcnow()
        c = SimpleNamespace(deleted_at=None, is_active=True, starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=1),
                            usage_limit=10, current_redemptions=10)
        self.assertEqual(merchant_promos.state_of(c), "used_up")
        c.current_redemptions = 2
        self.assertEqual(merchant_promos.state_of(c), "live")
        c.is_active = False
        self.assertEqual(merchant_promos.state_of(c), "paused")


if __name__ == "__main__":
    unittest.main()
