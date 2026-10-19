"""
Promo codes a store runs for its own customers.

The store pays for these (funding RESTAURANT): the discount comes out of the store's share,
never Novo's. Rules below keep codes sensible and are shown to merchants as-is.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.modules.pricing.models import PromotionCampaign, PromotionRedemption

RULES = {
    "code_pattern": r"^[A-Z0-9]{4,16}$",
    "min_percent": 5,
    "max_percent": 50,
    "min_fixed": 100,
    # A fixed discount can be at most half the minimum order (so ₦1,000 off needs a ₦2,000 minimum).
    "fixed_max_share_of_min_order": 0.5,
    "max_live_codes": 5,
    "max_days": 90,
    "max_per_customer": 10,
    "max_total_uses": 100000,
}

TYPES = {"PERCENTAGE", "FIXED", "FREE_DELIVERY"}


def rules_for_display() -> dict:
    return {
        "min_percent": RULES["min_percent"],
        "max_percent": RULES["max_percent"],
        "min_fixed": RULES["min_fixed"],
        "fixed_needs_min_order_multiple": int(1 / RULES["fixed_max_share_of_min_order"]),
        "max_live_codes": RULES["max_live_codes"],
        "max_days": RULES["max_days"],
        "max_per_customer": RULES["max_per_customer"],
        "code_format": "4–16 letters or numbers, e.g. JOLLOF20",
        "funded_by": "your store",
    }


def _bad(msg: str):
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)


def _num(payload: dict, key: str, default=None) -> Optional[float]:
    v = payload.get(key, default)
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        _bad(f"{key.replace('_', ' ').capitalize()} must be a number")


def _when(v) -> Optional[datetime]:
    if v in (None, ""):
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        _bad("Use a valid date")
    # Stored as naive UTC like the rest of the pricing tables.
    if dt.tzinfo:
        dt = (dt - dt.utcoffset()).replace(tzinfo=None)
    return dt


def state_of(c: PromotionCampaign, now: Optional[datetime] = None) -> str:
    now = now or datetime.utcnow()
    if c.deleted_at:
        return "archived"
    if not c.is_active:
        return "paused"
    if c.starts_at and c.starts_at > now:
        return "scheduled"
    if c.ends_at and c.ends_at <= now:
        return "ended"
    if c.usage_limit and (c.current_redemptions or 0) >= c.usage_limit:
        return "used_up"
    return "live"


def validate_terms(payload: dict, existing: Optional[PromotionCampaign] = None) -> dict:
    """Check a merchant's promo against RULES. Returns clean column values."""
    out: dict = {}
    promo_type = str(payload.get("promo_type") or (existing.promo_type if existing else "PERCENTAGE")).upper()
    if promo_type not in TYPES:
        _bad("Choose percentage off, amount off or free delivery")
    out["promo_type"] = promo_type

    value = _num(payload, "discount_value")
    if value is None and existing:
        value = existing.discount_value
    min_order = _num(payload, "min_order_amount")
    if min_order is None:
        min_order = existing.min_order_amount if existing else 0.0
    if min_order < 0 or min_order > 1_000_000:
        _bad("Minimum order must be between ₦0 and ₦1,000,000")
    out["min_order_amount"] = round(min_order, 2)

    if promo_type == "PERCENTAGE":
        if value is None or not (RULES["min_percent"] <= value <= RULES["max_percent"]):
            _bad(f"Percentage off must be between {RULES['min_percent']}% and {RULES['max_percent']}%")
        out["discount_value"] = round(value, 2)
        cap = _num(payload, "max_discount_amount")
        if cap is None and existing and "max_discount_amount" not in payload:
            cap = existing.max_discount_amount
        if cap is not None and cap < RULES["min_fixed"]:
            _bad(f"The discount cap must be at least ₦{RULES['min_fixed']}")
        out["max_discount_amount"] = round(cap, 2) if cap is not None else None
    elif promo_type == "FIXED":
        if value is None or value < RULES["min_fixed"]:
            _bad(f"Amount off must be at least ₦{RULES['min_fixed']}")
        if value > min_order * RULES["fixed_max_share_of_min_order"]:
            need = value / RULES["fixed_max_share_of_min_order"]
            _bad(f"₦{value:,.0f} off needs a minimum order of at least ₦{need:,.0f}")
        out["discount_value"] = round(value, 2)
        out["max_discount_amount"] = None
    else:
        out["discount_value"] = 0.0
        out["max_discount_amount"] = None

    starts = _when(payload["starts_at"]) if "starts_at" in payload else (existing.starts_at if existing else None)
    ends = _when(payload["ends_at"]) if "ends_at" in payload else (existing.ends_at if existing else None)
    starts = starts or datetime.utcnow()
    if not ends:
        _bad(f"Set an end date (at most {RULES['max_days']} days after it starts)")
    if ends <= starts:
        _bad("The end date must be after the start date")
    if ends - starts > timedelta(days=RULES["max_days"]):
        _bad(f"A promo can run for at most {RULES['max_days']} days")
    out["starts_at"], out["ends_at"] = starts, ends

    per_user = int(_num(payload, "per_user_limit") or (existing.per_user_limit if existing else 1))
    if not (1 <= per_user <= RULES["max_per_customer"]):
        _bad(f"Uses per customer must be between 1 and {RULES['max_per_customer']}")
    out["per_user_limit"] = per_user

    total = payload.get("usage_limit", existing.usage_limit if existing else None)
    if total in ("", None):
        out["usage_limit"] = None
    else:
        total = int(float(total))
        if not (1 <= total <= RULES["max_total_uses"]):
            _bad("Total uses must be at least 1")
        out["usage_limit"] = total

    name = str(payload.get("name") or (existing.name if existing else "") or "").strip()[:80]
    out["name"] = name or None
    desc = payload.get("description", existing.description if existing else None)
    out["description"] = (str(desc).strip()[:300] or None) if desc else None
    return out


async def merchant_for_user(db: AsyncSession, user_id: str):
    from app.modules.merchants.models import Merchant

    res = await db.execute(
        select(Merchant).where(Merchant.owner_id == user_id, Merchant.is_deleted == False).order_by(Merchant.created_at)
    )
    merchant = res.scalars().first()
    if not merchant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Set up your store first")
    return merchant


async def _stats(db: AsyncSession, ids: list[str]) -> dict:
    if not ids:
        return {}
    rows = await db.execute(
        select(PromotionRedemption.campaign_id, func.count(), func.coalesce(func.sum(PromotionRedemption.discount_applied), 0))
        .where(PromotionRedemption.campaign_id.in_(ids))
        .group_by(PromotionRedemption.campaign_id)
    )
    return {cid: {"uses": int(n), "discount_given": round(float(total), 2)} for cid, n, total in rows.all()}


def serialize(c: PromotionCampaign, stats: Optional[dict] = None) -> dict:
    s = stats or {}
    return {
        "id": c.id,
        "code": c.code,
        "name": c.name,
        "description": c.description,
        "promo_type": c.promo_type,
        "discount_value": c.discount_value,
        "min_order_amount": c.min_order_amount,
        "max_discount_amount": c.max_discount_amount,
        "usage_limit": c.usage_limit,
        "per_user_limit": c.per_user_limit,
        "starts_at": c.starts_at.isoformat() + "Z" if c.starts_at else None,
        "ends_at": c.ends_at.isoformat() + "Z" if c.ends_at else None,
        "is_active": bool(c.is_active),
        "state": state_of(c),
        "uses": s.get("uses", c.current_redemptions or 0),
        "discount_given": s.get("discount_given", 0.0),
        "funding_source": c.funding_source,
        "applicable_merchant_id": c.applicable_merchant_id,
    }


async def list_mine(db: AsyncSession, merchant_id: str) -> list[dict]:
    res = await db.execute(
        select(PromotionCampaign)
        .where(PromotionCampaign.applicable_merchant_id == merchant_id, PromotionCampaign.deleted_at.is_(None))
        .order_by(PromotionCampaign.created_at.desc())
    )
    rows = res.scalars().all()
    stats = await _stats(db, [r.id for r in rows])
    return [serialize(r, stats.get(r.id)) for r in rows]


async def _live_count(db: AsyncSession, merchant_id: str, exclude: Optional[str] = None) -> int:
    res = await db.execute(
        select(PromotionCampaign).where(
            PromotionCampaign.applicable_merchant_id == merchant_id,
            PromotionCampaign.deleted_at.is_(None),
            PromotionCampaign.is_active == True,
        )
    )
    return sum(1 for c in res.scalars().all() if c.id != exclude and state_of(c) in ("live", "scheduled"))


async def create(db: AsyncSession, merchant_id: str, payload: dict) -> dict:
    code = re.sub(r"\s+", "", str(payload.get("code") or "")).upper()
    if not re.match(RULES["code_pattern"], code):
        _bad("Code must be 4–16 letters or numbers, e.g. JOLLOF20")
    taken = await db.execute(select(PromotionCampaign).where(func.upper(PromotionCampaign.code) == code))
    if taken.scalar_one_or_none():
        _bad("That code is already taken on Novo. Try another.")
    if await _live_count(db, merchant_id) >= RULES["max_live_codes"]:
        _bad(f"You can run at most {RULES['max_live_codes']} codes at once. Pause or delete one first.")
    terms = validate_terms(payload)
    campaign = PromotionCampaign(
        code=code,
        name=terms.pop("name") or code,
        funding_source="RESTAURANT",
        merchant_funding_share=1.0,
        applicable_merchant_id=merchant_id,
        is_active=True,
        current_redemptions=0,
        **terms,
    )
    db.add(campaign)
    await db.commit()
    return serialize(campaign)


async def _own(db: AsyncSession, merchant_id: str, promo_id: str) -> PromotionCampaign:
    c = await db.get(PromotionCampaign, promo_id)
    if not c or c.deleted_at or c.applicable_merchant_id != merchant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promotion not found")
    return c


async def update(db: AsyncSession, merchant_id: str, promo_id: str, payload: dict) -> dict:
    c = await _own(db, merchant_id, promo_id)
    if "is_active" in payload and len(payload) == 1:
        turning_on = bool(payload["is_active"])
        if turning_on and not c.is_active and await _live_count(db, merchant_id, exclude=c.id) >= RULES["max_live_codes"]:
            _bad(f"You can run at most {RULES['max_live_codes']} codes at once. Pause another first.")
        c.is_active = turning_on
        await db.commit()
        return serialize(c)

    used = (c.current_redemptions or 0) > 0
    if used and any(k in payload for k in ("promo_type", "discount_value", "min_order_amount", "max_discount_amount")):
        # Customers already used it on these terms; changing them would rewrite history.
        _bad("This code has been used, so its discount can't change. You can still change the end date and limits, or make a new code.")
    terms = validate_terms(payload, existing=c)
    for k, v in terms.items():
        if k == "name":
            c.name = v or c.name
        else:
            setattr(c, k, v)
    if "is_active" in payload:
        c.is_active = bool(payload["is_active"])
    await db.commit()
    return serialize(c)


async def delete(db: AsyncSession, merchant_id: str, promo_id: str) -> str:
    c = await _own(db, merchant_id, promo_id)
    return await remove(db, c)


async def remove(db: AsyncSession, c: PromotionCampaign) -> str:
    """Unused codes are deleted; used ones are archived so order history stays intact."""
    if (c.current_redemptions or 0) > 0:
        c.is_active = False
        c.deleted_at = datetime.utcnow()
        await db.commit()
        return "archived"
    await db.delete(c)
    await db.commit()
    return "deleted"
