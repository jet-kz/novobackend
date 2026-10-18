"""
Homepage catalog: platform categories (Food, Groceries, ...) and featured collections.
Anyone can read the active ones; admins manage them.
"""
import re
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, status
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import get_db
from app.core.security import require_role
from app.core.serializers import model_to_dict
from app.modules.catalog.models import HomeCollection, PlatformCategory
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
