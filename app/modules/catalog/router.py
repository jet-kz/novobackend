"""
Homepage catalog: platform categories (Food, Groceries, ...) and featured collections.
Anyone can read the active ones; admins manage them.
"""
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, status
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import get_db
from app.core.security import require_role
from app.core.serializers import model_to_dict
from app.core import audit
from app.modules.catalog.models import HomeCollection, PlatformCategory, PromoBanner
from app.modules.stores.models import Store

router = APIRouter()

CATEGORY_FIELDS = {"name", "icon", "description", "display_order", "is_active"}
COLLECTION_FIELDS = {"title", "subtitle", "badge", "image", "target_category", "display_order", "is_active"}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")[:50]


async def _get(db: AsyncSession, model, item_id: str):
    try:
        row = await db.get(model, uuid.UUID(item_id))
    except ValueError:
        row = None
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return row


def _apply(row, payload: dict, fields: set) -> None:
    for key in fields & payload.keys():
        value = payload[key]
        if key == "display_order":
            value = int(value or 0)
        elif key == "is_active":
            value = bool(value)
        elif isinstance(value, str):
            value = value.strip() or None
        setattr(row, key, value)


# ── Categories ──────────────────────────────────────────────────────────────

@router.get("/categories", status_code=status.HTTP_200_OK)
async def list_categories(include_inactive: bool = Query(False), db: AsyncSession = Depends(get_db)):
    """Homepage categories in display order, each with how many live stores it has."""
    stmt = select(PlatformCategory).order_by(PlatformCategory.display_order, PlatformCategory.name)
    if not include_inactive:
        stmt = stmt.where(PlatformCategory.is_active == True)
    rows = (await db.execute(stmt)).scalars().all()
    counts = dict((await db.execute(
        select(Store.store_type, func.count()).where(Store.is_deleted == False).group_by(Store.store_type)
    )).all())
    return {"success": True, "data": [{**model_to_dict(r), "store_count": counts.get(r.slug, 0)} for r in rows]}


@router.post("/categories", status_code=status.HTTP_201_CREATED)
async def create_category(payload: dict = Body(...), db: AsyncSession = Depends(get_db), _: dict = Depends(require_role("admin"))):
    name = str(payload.get("name") or "").strip()
    slug = _slug(payload.get("slug") or name)
    if not name or not slug:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Category name is required")
    if (await db.execute(select(PlatformCategory).where(PlatformCategory.slug == slug))).scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A category with that name already exists")
    count = (await db.execute(select(func.count()).select_from(PlatformCategory))).scalar() or 0
    row = PlatformCategory(slug=slug, name=name, display_order=count + 1, is_active=True)
    _apply(row, payload, CATEGORY_FIELDS - {"name"})
    db.add(row)
    await db.commit()
    return {"success": True, "data": model_to_dict(row)}


@router.patch("/categories/{item_id}", status_code=status.HTTP_200_OK)
async def update_category(item_id: str = Path(...), payload: dict = Body(...), db: AsyncSession = Depends(get_db), _: dict = Depends(require_role("admin"))):
    """Edit name/icon/description/order or hide a category. The slug stays fixed because stores reference it."""
    row = await _get(db, PlatformCategory, item_id)
    if "name" in payload and not str(payload["name"] or "").strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Category name is required")
    _apply(row, payload, CATEGORY_FIELDS)
    await db.commit()
    return {"success": True, "data": model_to_dict(row)}


@router.delete("/categories/{item_id}", status_code=status.HTTP_200_OK)
async def delete_category(item_id: str = Path(...), db: AsyncSession = Depends(get_db), _: dict = Depends(require_role("admin"))):
    row = await _get(db, PlatformCategory, item_id)
    in_use = (await db.execute(
        select(func.count()).select_from(Store).where(Store.store_type == row.slug, Store.is_deleted == False)
    )).scalar() or 0
    if in_use:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{in_use} store(s) use this category. Hide it instead, or move those stores first.",
        )
    await db.delete(row)
    await db.commit()
    return {"success": True, "data": None}


# ── Featured collections ────────────────────────────────────────────────────

@router.get("/collections", status_code=status.HTTP_200_OK)
async def list_collections(include_inactive: bool = Query(False), db: AsyncSession = Depends(get_db)):
    stmt = select(HomeCollection).order_by(HomeCollection.display_order, HomeCollection.created_at)
    if not include_inactive:
        stmt = stmt.where(HomeCollection.is_active == True)
    return {"success": True, "data": [model_to_dict(r) for r in (await db.execute(stmt)).scalars().all()]}


@router.post("/collections", status_code=status.HTTP_201_CREATED)
async def create_collection(payload: dict = Body(...), db: AsyncSession = Depends(get_db), _: dict = Depends(require_role("admin"))):
    if not str(payload.get("title") or "").strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Title is required")
    count = (await db.execute(select(func.count()).select_from(HomeCollection))).scalar() or 0
    row = HomeCollection(display_order=count + 1, is_active=True, target_category="all")
    _apply(row, payload, COLLECTION_FIELDS)
    row.target_category = row.target_category or "all"
    db.add(row)
    await db.commit()
    return {"success": True, "data": model_to_dict(row)}


@router.patch("/collections/{item_id}", status_code=status.HTTP_200_OK)
async def update_collection(item_id: str = Path(...), payload: dict = Body(...), db: AsyncSession = Depends(get_db), _: dict = Depends(require_role("admin"))):
    row = await _get(db, HomeCollection, item_id)
    _apply(row, payload, COLLECTION_FIELDS)
    row.target_category = row.target_category or "all"
    if not row.title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Title is required")
    await db.commit()
    return {"success": True, "data": model_to_dict(row)}


@router.delete("/collections/{item_id}", status_code=status.HTTP_200_OK)
async def delete_collection(item_id: str = Path(...), db: AsyncSession = Depends(get_db), _: dict = Depends(require_role("admin"))):
    row = await _get(db, HomeCollection, item_id)
    await db.delete(row)
    await db.commit()
    return {"success": True, "data": None}


# ── Promo banners ───────────────────────────────────────────────────────────

BANNER_FIELDS = {"title", "subtitle", "image", "cta_label", "link_url", "placement", "show_text", "display_order", "is_active"}
BANNER_PLACEMENTS = {"home", "shop"}


def _parse_when(value):
    if value in (None, ""):
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Use a valid date for the schedule")
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _valid_link(link: str) -> bool:
    return (link.startswith("/") and not link.startswith("//")) or link.startswith("https://")


def _apply_banner(row: PromoBanner, payload: dict) -> None:
    for key in BANNER_FIELDS & payload.keys():
        value = payload[key]
        if key == "display_order":
            value = int(value or 0)
        elif key in ("is_active", "show_text"):
            value = bool(value)
        elif isinstance(value, str):
            value = value.strip() or None
        setattr(row, key, value)
    for key in ("starts_at", "ends_at"):
        if key in payload:
            setattr(row, key, _parse_when(payload[key]))

    if not row.image or not str(row.image).startswith("https://"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Upload a banner image")
    if row.link_url and not _valid_link(row.link_url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Link must be a page on Novo (starting with /) or an https:// address",
        )
    row.placement = row.placement if row.placement in BANNER_PLACEMENTS else "home"
    if row.starts_at and row.ends_at and row.ends_at <= row.starts_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The end date must be after the start date")


def _banner_dict(row: PromoBanner) -> dict:
    data = model_to_dict(row)
    now = datetime.now(timezone.utc)
    if not row.is_active:
        data["state"] = "hidden"
    elif row.starts_at and row.starts_at > now:
        data["state"] = "scheduled"
    elif row.ends_at and row.ends_at <= now:
        data["state"] = "ended"
    else:
        data["state"] = "live"
    return data


@router.get("/banners", status_code=status.HTTP_200_OK)
async def list_banners(placement: str = Query("home"), include_inactive: bool = Query(False), db: AsyncSession = Depends(get_db)):
    """Live banners for a placement, in order. The admin screen passes include_inactive to see everything."""
    stmt = select(PromoBanner).order_by(PromoBanner.display_order, PromoBanner.created_at)
    if placement != "all":
        stmt = stmt.where(PromoBanner.placement == placement)
    rows = [_banner_dict(r) for r in (await db.execute(stmt)).scalars().all()]
    if not include_inactive:
        rows = [r for r in rows if r["state"] == "live"]
    return {"success": True, "data": rows}


@router.post("/banners", status_code=status.HTTP_201_CREATED)
async def create_banner(payload: dict = Body(...), db: AsyncSession = Depends(get_db), actor: dict = Depends(require_role("admin"))):
    count = (await db.execute(select(func.count()).select_from(PromoBanner))).scalar() or 0
    row = PromoBanner(display_order=count + 1, is_active=True, show_text=True, placement="home")
    _apply_banner(row, payload)
    db.add(row)
    await db.flush()
    audit.record(db, actor, "banner.create", "banner", row.id, {"title": row.title})
    await db.commit()
    return {"success": True, "data": _banner_dict(row)}


@router.post("/banners/reorder", status_code=status.HTTP_200_OK)
async def reorder_banners(payload: dict = Body(...), db: AsyncSession = Depends(get_db), _: dict = Depends(require_role("admin"))):
    for position, item_id in enumerate(payload.get("ids") or [], start=1):
        row = await _get(db, PromoBanner, str(item_id))
        row.display_order = position
    await db.commit()
    return {"success": True, "data": None}


@router.patch("/banners/{item_id}", status_code=status.HTTP_200_OK)
async def update_banner(item_id: str = Path(...), payload: dict = Body(...), db: AsyncSession = Depends(get_db), actor: dict = Depends(require_role("admin"))):
    row = await _get(db, PromoBanner, item_id)
    _apply_banner(row, payload)
    audit.record(db, actor, "banner.update", "banner", row.id, {"title": row.title, "active": row.is_active})
    await db.commit()
    return {"success": True, "data": _banner_dict(row)}


@router.delete("/banners/{item_id}", status_code=status.HTTP_200_OK)
async def delete_banner(item_id: str = Path(...), db: AsyncSession = Depends(get_db), actor: dict = Depends(require_role("admin"))):
    row = await _get(db, PromoBanner, item_id)
    audit.record(db, actor, "banner.delete", "banner", row.id, {"title": row.title})
    await db.delete(row)
    await db.commit()
    return {"success": True, "data": None}
