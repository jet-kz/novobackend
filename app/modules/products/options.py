"""
Option groups: how a menu item is customised.

A group is one question the customer answers, e.g.

    {"id": "g1", "name": "Choose your protein", "min": 1, "max": 1,
     "options": [{"id": "o1", "name": "Chicken", "price": 0, "available": true, "max_qty": 1}, ...]}

min/max count the total quantity picked in the group, so "Extra meat (up to 3)" can be
two chicken + one beef. min >= 1 makes the group required. max_qty lets one option be
picked more than once ("2 x extra plantain").

Older products stored proteins/extras in separate columns; effective_option_groups()
presents them as groups so every client only deals with one shape.
"""
from __future__ import annotations

import uuid
from typing import Optional

MAX_GROUPS = 12
MAX_OPTIONS_PER_GROUP = 40
MAX_OPTION_QTY = 10
MAX_GROUP_PICKS = 50


class OptionGroupError(ValueError):
    pass


def _int(value, default: int, lo: int, hi: int) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _clean_option(raw, group_name: str) -> dict:
    if not isinstance(raw, dict):
        raise OptionGroupError(f"Each choice in “{group_name}” needs a name")
    name = str(raw.get("name") or "").strip()[:80]
    if not name:
        raise OptionGroupError(f"Each choice in “{group_name}” needs a name")
    try:
        price = round(float(raw.get("price") or 0), 2)
    except (TypeError, ValueError):
        raise OptionGroupError(f"“{name}” has an invalid price")
    if price < 0 or price > 10_000_000:
        raise OptionGroupError(f"“{name}” has an invalid price")
    option = {
        "id": str(raw.get("id") or "").strip()[:64] or uuid.uuid4().hex[:12],
        "name": name,
        "price": price,
        "available": raw.get("available", True) is not False,
        "max_qty": _int(raw.get("max_qty", raw.get("maxQty")), 1, 1, MAX_OPTION_QTY),
    }
    image = str(raw.get("image") or "").strip()
    if image:
        option["image"] = image[:500]
    return option


def normalize_option_groups(groups) -> list[dict]:
    """Validate what a merchant submitted. Raises OptionGroupError with a message for them."""
    if groups in (None, ""):
        return []
    if not isinstance(groups, list):
        raise OptionGroupError("Options must be a list of groups")
    if len(groups) > MAX_GROUPS:
        raise OptionGroupError(f"An item can have at most {MAX_GROUPS} option groups")

    out, seen_ids = [], set()
    for raw in groups:
        if not isinstance(raw, dict):
            raise OptionGroupError("Each option group needs a name")
        name = str(raw.get("name") or "").strip()[:80]
        if not name:
            raise OptionGroupError("Each option group needs a name, e.g. “Choose your protein”")
        options = [_clean_option(o, name) for o in (raw.get("options") or [])]
        if not options:
            raise OptionGroupError(f"Add at least one choice to “{name}”")
        if len(options) > MAX_OPTIONS_PER_GROUP:
            raise OptionGroupError(f"“{name}” has too many choices (max {MAX_OPTIONS_PER_GROUP})")
        for o in options:
            if o["id"] in seen_ids:
                o["id"] = uuid.uuid4().hex[:12]
            seen_ids.add(o["id"])

        capacity = min(sum(o["max_qty"] for o in options), MAX_GROUP_PICKS)
        min_picks = _int(raw.get("min"), 0, 0, capacity)
        max_picks = _int(raw.get("max"), capacity, 1, capacity)
        if max_picks < min_picks:
            max_picks = min_picks
        group_id = str(raw.get("id") or "").strip()[:64] or uuid.uuid4().hex[:12]
        out.append({"id": group_id, "name": name, "min": min_picks, "max": max_picks, "options": options})
    return out


def _legacy_group(group_id: str, name: str, items, required_single: bool) -> Optional[dict]:
    options = []
    for raw in items or []:
        if isinstance(raw, dict) and raw.get("id") is not None and raw.get("name"):
            opt = {
                "id": str(raw["id"]),
                "name": str(raw["name"]),
                "price": float(raw.get("price") or 0),
                "available": raw.get("available", True) is not False,
                "max_qty": 1,
            }
            if raw.get("image"):
                opt["image"] = raw["image"]
            options.append(opt)
    if not options:
        return None
    if required_single:
        return {"id": group_id, "name": name, "min": 1, "max": 1, "options": options}
    return {"id": group_id, "name": name, "min": 0, "max": len(options), "options": options}


def effective_option_groups(product) -> list[dict]:
    """The groups a customer chooses from, whatever format the product was saved in."""
    stored = getattr(product, "option_groups", None) or []
    groups = []
    for g in stored:
        if not isinstance(g, dict):
            continue
        options = [
            {
                "id": str(o.get("id")),
                "name": o.get("name") or "",
                "price": float(o.get("price") or 0),
                "available": o.get("available", True) is not False,
                "max_qty": _int(o.get("max_qty", o.get("maxQty")), 1, 1, MAX_OPTION_QTY),
                **({"image": o["image"]} if o.get("image") else {}),
            }
            for o in (g.get("options") or [])
            if isinstance(o, dict) and o.get("id") is not None
        ]
        if not options:
            continue
        capacity = sum(o["max_qty"] for o in options)
        min_picks = _int(g.get("min"), 0, 0, capacity)
        max_picks = max(_int(g.get("max"), capacity, 1, capacity), min_picks)
        groups.append({"id": str(g.get("id") or uuid.uuid4().hex[:12]), "name": g.get("name") or "Options",
                       "min": min_picks, "max": max_picks, "options": options})
    if groups:
        return groups

    legacy = [
        _legacy_group("protein", "Choose your protein", getattr(product, "protein_options", None), True),
        _legacy_group("extras", "Add extras", getattr(product, "extras_options", None), False),
    ]
    return [g for g in legacy if g]


def price_selection(product, selections) -> tuple[list[dict], float]:
    """
    Check a customer's picks against the product's groups and price them.
    selections: [{"id": option_id, "quantity": n}, ...]. Returns (addons, addon_total per unit).
    Raises ValueError with a customer-facing message.
    """
    groups = effective_option_groups(product)
    index = {}
    for g in groups:
        for o in g["options"]:
            index[o["id"]] = (g, o)
    # Options saved in the old product_options table have no group rules.
    loose = {str(o.id): (o.name, float(o.price or 0)) for o in (getattr(product, "options", None) or [])}

    picked: dict[str, int] = {}
    for sel in selections if isinstance(selections, list) else []:
        oid = str(sel.get("id")) if isinstance(sel, dict) and sel.get("id") is not None else None
        if oid is None or (oid not in index and oid not in loose):
            raise ValueError(f"An option for {product.name} is no longer available")
        qty = _int(sel.get("quantity", 1), 1, 1, MAX_OPTION_QTY) if isinstance(sel, dict) else 1
        picked[oid] = picked.get(oid, 0) + qty

    addons, total = [], 0.0
    for g in groups:
        count = 0
        for o in g["options"]:
            qty = picked.get(o["id"], 0)
            if not qty:
                continue
            if not o["available"]:
                raise ValueError(f"{o['name']} is sold out for {product.name}")
            if qty > o["max_qty"]:
                raise ValueError(f"You can add at most {o['max_qty']} × {o['name']}")
            count += qty
            total += o["price"] * qty
            addons.append({"id": o["id"], "name": o["name"], "group": g["name"], "price": o["price"], "quantity": qty})
        if count < g["min"]:
            need = "one option" if g["min"] == 1 else f"{g['min']} options"
            raise ValueError(f"Choose {need} for “{g['name']}” on {product.name}")
        if count > g["max"]:
            raise ValueError(f"You can pick at most {g['max']} for “{g['name']}” on {product.name}")

    for oid, qty in picked.items():
        if oid in loose and oid not in index:
            name, price = loose[oid]
            total += price * qty
            addons.append({"id": oid, "name": name, "price": price, "quantity": qty})
    return addons, round(total, 2)
