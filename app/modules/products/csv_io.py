"""
Menu / catalogue spreadsheets: a standard CSV per store type that merchants download,
fill in (or export their current items), and upload back.

Every row is checked before anything is saved. A row with an `id` (or the same name as an
existing item) updates that item; otherwise it creates a new one.

Options column, one group per `;`:
    Choose your protein (required): Chicken=0, Beef=500; Extras (up to 3): Plantain=300 x3, Egg=200
  (required) = must pick; (up to N) = max picks; "x3" lets one choice be added 3 times.
"""
from __future__ import annotations

import csv
import io
import re
from typing import Optional

from app.modules.products.options import OptionGroupError, normalize_option_groups

MAX_ROWS = 1000
MAX_BYTES = 1_000_000

KINDS = ("food", "grocery", "pharmacy")
YES = {"yes", "y", "true", "1", "available", "in stock"}
NO = {"no", "n", "false", "0", "sold out", "out of stock", "unavailable"}
SPICE = ["Not spicy", "Mild", "Medium", "Hot", "Extra hot"]
DOSAGE_FORMS = ["Tablet", "Capsule", "Syrup", "Suspension", "Injection", "Cream", "Ointment", "Drops", "Inhaler", "Sachet", "Device", "Other"]

COMMON = ["id", "name", "price", "section", "description", "in_stock", "image_url"]
EXTRA = {
    "food": ["prep_time_minutes", "spice_level", "serves", "calories", "options"],
    "grocery": ["brand", "size", "unit", "options"],
    "pharmacy": ["brand", "strength", "dosage_form", "pack_size", "requires_prescription", "options"],
}
REQUIRED = {"food": {"name", "price"}, "grocery": {"name", "price"}, "pharmacy": {"name", "price", "requires_prescription"}}

# Column -> key inside product.specs
SPEC_KEYS = {
    "spice_level": "spicyLevel", "serves": "serves", "calories": "calories",
    "brand": "brand", "size": "size", "unit": "unit",
    "strength": "strength", "dosage_form": "dosageForm", "pack_size": "packSize",
}

EXAMPLES = {
    "food": [
        ["", "Party Jollof Rice", "3500", "Rice dishes", "Smoky firewood jollof", "yes", "", "25", "Medium", "1 person", "",
         "Choose your protein (required): Chicken=0, Beef=500, Fish=700; Extras (up to 3): Plantain=300 x3, Coleslaw=400"],
        ["", "Pepper Soup", "4200", "Soups", "Goat meat pepper soup", "yes", "", "20", "Hot", "1 person", "", "Swallow (required): Eba=0, Pounded yam=300"],
        ["", "Chapman", "1500", "Drinks", "", "yes", "", "5", "Not spicy", "", "", ""],
    ],
    "grocery": [
        ["", "Golden Penny Spaghetti", "950", "Pasta & noodles", "", "yes", "", "Golden Penny", "500g", "pack", ""],
        ["", "Peak Milk Powder", "3200", "Dairy", "Full cream", "yes", "", "Peak", "400g", "tin", "Size (required): 400g tin=0, 900g refill=2600"],
        ["", "Rice (local)", "1800", "Grains", "Ofada rice", "yes", "", "", "1kg", "bag", "Weight (required): 1kg=0, 5kg=7000"],
    ],
    "pharmacy": [
        ["", "Paracetamol 500mg", "600", "Pain relief", "", "yes", "", "Emzor", "500mg", "Tablet", "Pack of 12", "no", ""],
        ["", "Amoxicillin 500mg", "2500", "Antibiotics", "", "yes", "", "", "500mg", "Capsule", "Pack of 21", "yes", ""],
        ["", "Vitamin C Syrup", "1800", "Vitamins", "", "yes", "", "", "100mg/5ml", "Syrup", "100ml bottle", "no", ""],
    ],
}


def kind_for_store_type(store_type: Optional[str]) -> str:
    t = (store_type or "").lower()
    if "pharm" in t or "drug" in t or "chemist" in t:
        return "pharmacy"
    if any(k in t for k in ("restaurant", "food", "kitchen", "bakery", "cafe", "drink", "bar")):
        return "food"
    return "grocery"


def columns(kind: str) -> list[str]:
    return COMMON + EXTRA[kind]


def _safe(value) -> str:
    """Stop spreadsheet apps treating a cell as a formula (CSV injection)."""
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def _write(kind: str, rows: list[list]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(columns(kind))
    for r in rows:
        w.writerow([_safe(c) for c in r])
    # BOM so Excel opens ₦ and accents correctly.
    return "﻿" + buf.getvalue()


def template_csv(kind: str) -> str:
    return _write(kind, EXAMPLES[kind])


# ── options text <-> groups ──────────────────────────────────────────────────

def _default_max(min_picks: int, options: list[dict]) -> int:
    """What parse_options assumes when the cell has no "(up to N)"."""
    capacity = sum(max(1, o.get("max_qty") or 1) for o in options)
    return 1 if min_picks == 1 and len(options) > 1 else capacity


def format_options(groups: list[dict]) -> str:
    parts = []
    for g in groups or []:
        opts = g.get("options", [])
        min_picks = g.get("min") or 0
        tags = []
        if min_picks == 1:
            tags.append("required")
        elif min_picks > 1:
            tags.append(f"pick at least {min_picks}")
        if (g.get("max") or 0) != _default_max(min_picks, opts):
            tags.append(f"up to {g['max']}")
        head = g.get("name", "Options") + (f" ({', '.join(tags)})" if tags else "")
        choices = []
        for o in opts:
            price = float(o.get("price") or 0)
            c = f"{o['name']}={int(price) if price.is_integer() else price}"
            if (o.get("max_qty") or 1) > 1:
                c += f" x{o['max_qty']}"
            if o.get("available") is False:
                c += " (sold out)"
            choices.append(c)
        parts.append(f"{head}: {', '.join(choices)}")
    return "; ".join(parts)


_HEAD = re.compile(r"^(?P<name>[^()]+?)\s*(?:\((?P<tags>[^)]*)\))?$")
_CHOICE = re.compile(r"^(?P<name>.+?)\s*(?:=\s*(?P<price>[\d.,]+))?\s*(?:x\s*(?P<qty>\d+))?\s*(?P<out>\(sold out\))?$", re.I)


def parse_options(text: str) -> list[dict]:
    """Parse the options cell. Raises ValueError with a message for the merchant."""
    text = (text or "").strip()
    if not text:
        return []
    groups = []
    for chunk in [c.strip() for c in text.split(";") if c.strip()]:
        if ":" not in chunk:
            raise ValueError(f"“{chunk[:40]}” needs a group name, then a colon, then the choices")
        head, body = chunk.split(":", 1)
        m = _HEAD.match(head.strip())
        if not m:
            raise ValueError(f"Can't read the group name “{head.strip()[:40]}”")
        name = m.group("name").strip()
        tags = (m.group("tags") or "").lower()
        min_picks, max_picks = 0, None
        if "required" in tags:
            min_picks = 1
        at_least = re.search(r"at least\s*(\d+)", tags)
        if at_least:
            min_picks = int(at_least.group(1))
        up_to = re.search(r"up to\s*(\d+)", tags)
        if up_to:
            max_picks = int(up_to.group(1))
        options = []
        for raw in [c.strip() for c in body.split(",") if c.strip()]:
            cm = _CHOICE.match(raw)
            if not cm:
                raise ValueError(f"Can't read the choice “{raw[:40]}” in {name}")
            price = (cm.group("price") or "0").replace(",", "")
            try:
                price_v = float(price)
            except ValueError:
                raise ValueError(f"“{raw[:40]}” has an invalid price")
            options.append({
                "name": cm.group("name").strip(),
                "price": price_v,
                "max_qty": int(cm.group("qty") or 1),
                "available": not cm.group("out"),
            })
        if not options:
            raise ValueError(f"{name} has no choices")
        if max_picks is None:
            max_picks = _default_max(min_picks, options)
        groups.append({"name": name, "min": min_picks, "max": max(max_picks, min_picks), "options": options})
    try:
        return normalize_option_groups(groups)
    except OptionGroupError as exc:
        raise ValueError(str(exc))


# ── export ───────────────────────────────────────────────────────────────────

def export_csv(kind: str, products: list) -> str:
    from app.modules.products.options import effective_option_groups

    rows = []
    for p in products:
        specs = p.specs if isinstance(p.specs, dict) else {}
        base = [
            str(p.id), p.name, f"{p.price:g}", (p.category.name if getattr(p, "category", None) else ""),
            p.description or "", "yes" if p.in_stock else "no", p.image or "",
        ]
        extra = []
        for col in EXTRA[kind]:
            if col == "options":
                extra.append(format_options(effective_option_groups(p)))
            elif col == "prep_time_minutes":
                extra.append(str(p.preparation_time_minutes or ""))
            elif col == "requires_prescription":
                extra.append("yes" if specs.get("requiresPrescription") else "no")
            else:
                extra.append(specs.get(SPEC_KEYS[col], "") or "")
        rows.append(base + extra)
    return _write(kind, rows)


# ── import ───────────────────────────────────────────────────────────────────

def _price(raw: str) -> float:
    clean = re.sub(r"[₦,\s]|NGN", "", raw or "", flags=re.I)
    v = float(clean)
    if not (0 < v <= 10_000_000):
        raise ValueError
    return round(v, 2)


def _yes_no(raw: str, default: Optional[bool]) -> Optional[bool]:
    v = (raw or "").strip().lower()
    if not v:
        return default
    if v in YES:
        return True
    if v in NO:
        return False
    raise ValueError


def _pick(raw: str, allowed: list[str]) -> Optional[str]:
    v = (raw or "").strip()
    if not v:
        return None
    for a in allowed:
        if a.lower() == v.lower():
            return a
    raise ValueError


def parse_rows(csv_text: str, kind: str, existing: list) -> dict:
    """
    Validate an uploaded CSV against the store's current items.
    existing: products in the store (id, name). Returns {"rows": [...], "file_errors": [...], ...}.
    Each row: {"line", "action": create|update|skip, "name", "errors": [...], "warnings": [...], "data": {...}}
    """
    if kind not in KINDS:
        return {"file_errors": ["Unknown template type"], "rows": []}
    if len(csv_text.encode("utf-8")) > MAX_BYTES:
        return {"file_errors": ["File is larger than 1 MB. Split it into smaller files."], "rows": []}
    text = csv_text.lstrip("﻿")
    try:
        reader = csv.DictReader(io.StringIO(text))
        header = [h.strip().lower() for h in (reader.fieldnames or [])]
    except csv.Error as exc:
        return {"file_errors": [f"Couldn't read the file as CSV ({exc})"], "rows": []}
    reader.fieldnames = header
    missing = sorted(REQUIRED[kind] - set(header))
    if missing:
        return {"file_errors": [f"Missing column(s): {', '.join(missing)}. Download the {kind} template and keep its header row."], "rows": []}
    unknown = [h for h in header if h and h not in columns(kind)]

    by_id = {str(p.id): p for p in existing}
    by_name = {}
    for p in existing:
        by_name.setdefault(p.name.strip().lower(), p)

    rows, seen_names, seen_ids = [], {}, set()
    try:
        records = list(reader)
    except csv.Error as exc:
        return {"file_errors": [f"Couldn't read the file as CSV ({exc})"], "rows": []}
    if len(records) > MAX_ROWS:
        return {"file_errors": [f"At most {MAX_ROWS} items per file. Split it into smaller files."], "rows": []}

    for i, rec in enumerate(records, start=2):
        get = lambda col: (rec.get(col) or "").strip().lstrip("'") if rec.get(col) is not None else ""  # noqa: E731
        if not any((v or "").strip() for v in rec.values() if isinstance(v, str)):
            continue  # blank line
        errors, warnings, data = [], [], {}
        name = get("name")
        if not (2 <= len(name) <= 120):
            errors.append("Name is required (2–120 characters)")
        data["name"] = name

        try:
            data["price"] = _price(get("price"))
        except (ValueError, TypeError):
            errors.append("Price must be a number above 0, e.g. 3500")

        section = get("section")
        if len(section) > 100:
            errors.append("Section is longer than 100 characters")
        data["category"] = section or None
        desc = get("description")
        if len(desc) > 1000:
            errors.append("Description is longer than 1000 characters")
        data["description"] = desc or None
        try:
            stock = _yes_no(get("in_stock"), True)
            data["inStock"] = stock
        except ValueError:
            errors.append("in_stock must be yes or no")
        img = get("image_url")
        if img and not (img.startswith("https://") and len(img) <= 500):
            errors.append("image_url must be an https:// link (or leave it empty)")
        data["image"] = img or None

        specs = {}
        if kind == "food":
            prep = get("prep_time_minutes")
            if prep:
                try:
                    v = int(float(prep))
                    if not 1 <= v <= 240:
                        raise ValueError
                    data["preparationTimeMinutes"] = v
                    specs["prepTime"] = f"{v} min"
                except ValueError:
                    errors.append("prep_time_minutes must be a whole number from 1 to 240")
            try:
                spice = _pick(get("spice_level"), SPICE)
                if spice:
                    specs["spicyLevel"] = spice
            except ValueError:
                errors.append(f"spice_level must be one of: {', '.join(SPICE)}")
            for col in ("serves", "calories"):
                if get(col):
                    specs[SPEC_KEYS[col]] = get(col)[:40]
        elif kind == "grocery":
            for col in ("brand", "size", "unit"):
                if get(col):
                    specs[SPEC_KEYS[col]] = get(col)[:60]
        else:
            for col in ("brand", "strength", "pack_size"):
                if get(col):
                    specs[SPEC_KEYS[col]] = get(col)[:60]
            try:
                form = _pick(get("dosage_form"), DOSAGE_FORMS)
                if form:
                    specs["dosageForm"] = form
            except ValueError:
                errors.append(f"dosage_form must be one of: {', '.join(DOSAGE_FORMS)}")
            try:
                rx = _yes_no(get("requires_prescription"), None)
                if rx is None:
                    errors.append("requires_prescription must be yes or no for every pharmacy item")
                else:
                    specs["requiresPrescription"] = rx
            except ValueError:
                errors.append("requires_prescription must be yes or no")
        data["specs"] = specs

        if "options" in header:
            try:
                data["optionGroups"] = parse_options(get("options"))
            except ValueError as exc:
                errors.append(f"Options: {exc}")

        # Which item does this row update?
        rid = get("id")
        target = None
        if rid:
            target = by_id.get(rid)
            if not target:
                errors.append("This id isn't one of your items. Clear the id cell to add it as a new item.")
            elif rid in seen_ids:
                errors.append("This id appears twice in the file")
            seen_ids.add(rid)
        elif name:
            target = by_name.get(name.lower())
        key = name.lower()
        if key and key in seen_names:
            errors.append(f"Same name as row {seen_names[key]}")
        seen_names.setdefault(key, i)

        rows.append({
            "line": i,
            "name": name,
            "action": "update" if target else "create",
            "product_id": str(target.id) if target else None,
            "errors": errors,
            "warnings": warnings,
            "data": data,
        })

    return {
        "file_errors": [] if rows else ["The file has no items. Add one item per row under the header."],
        "warnings": [f"Ignored unknown column(s): {', '.join(unknown)}"] if unknown else [],
        "rows": rows,
        "summary": {
            "create": sum(1 for r in rows if r["action"] == "create" and not r["errors"]),
            "update": sum(1 for r in rows if r["action"] == "update" and not r["errors"]),
            "errors": sum(1 for r in rows if r["errors"]),
        },
    }
