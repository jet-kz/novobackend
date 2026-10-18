from fastapi import APIRouter, Depends, status, Path, Body, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.core.access import assert_store_access
from app.modules.products.service import ProductService


async def _assert_product_access(db: AsyncSession, product_id: str, current_user: dict):
    store_id = await ProductService.get_store_id(db, product_id)
    await assert_store_access(db, store_id, current_user)

router = APIRouter()


@router.get("", status_code=status.HTTP_200_OK)
async def list_products(
    store_id: Optional[str] = Query(None),
    category_id: Optional[str] = Query(None),
    in_stock: Optional[bool] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """List products. Filter by store, category, or stock availability."""
    products = await ProductService.get_products(db, store_id=store_id, category_id=category_id, in_stock=in_stock)
    return {"success": True, "message": "Products retrieved successfully", "data": products}


@router.get("/categories", status_code=status.HTTP_200_OK)
async def list_categories(store_id: Optional[str] = Query(None), db: AsyncSession = Depends(get_db)):
    """List product categories, optionally filtered by store."""
    categories = await ProductService.get_categories(db, store_id=store_id)
    return {"success": True, "message": "Categories retrieved", "data": categories}


@router.post("/categories", status_code=status.HTTP_201_CREATED)
async def create_section(payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Owner/admin: add a menu section (e.g. "Rice dishes", "Drinks") to a store."""
    store = await assert_store_access(db, payload.get("store_id"), current_user)
    section = await ProductService.create_section(db, store.id, str(payload.get("name") or ""))
    return {"success": True, "message": "Section created", "data": section}


@router.put("/categories/reorder", status_code=status.HTTP_200_OK)
async def reorder_sections(payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Owner/admin: set section order. Body: {store_id, ids: [...]} in display order."""
    store = await assert_store_access(db, payload.get("store_id"), current_user)
    sections = await ProductService.reorder_sections(db, store.id, payload.get("ids") or [])
    return {"success": True, "message": "Sections reordered", "data": sections}


@router.patch("/categories/{section_id}", status_code=status.HTTP_200_OK)
async def rename_section(section_id: str = Path(...), payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    section = await ProductService._section(db, section_id)
    await assert_store_access(db, section.store_id, current_user)
    data = await ProductService.rename_section(db, section, str(payload.get("name") or ""))
    return {"success": True, "message": "Section renamed", "data": data}


@router.delete("/categories/{section_id}", status_code=status.HTTP_200_OK)
async def delete_section(section_id: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Owner/admin: remove a section. Its items stay on the menu, unsectioned."""
    section = await ProductService._section(db, section_id)
    await assert_store_access(db, section.store_id, current_user)
    await ProductService.delete_section(db, section)
    return {"success": True, "message": "Section removed", "data": None}


@router.get("/{product_id}", status_code=status.HTTP_200_OK)
async def get_product(product_id: str = Path(...), db: AsyncSession = Depends(get_db)):
    """Get a single product with its options/addons."""
    product = await ProductService.get_by_id(db, product_id)
    return {"success": True, "message": "Product retrieved", "data": product}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_product(payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Owner/admin: create a new product in a store."""
    await assert_store_access(db, payload.get("store_id") or payload.get("storeId"), current_user)
    product = await ProductService.create_product(db, payload)
    return {"success": True, "message": "Product created successfully", "data": product}


@router.put("/{product_id}", status_code=status.HTTP_200_OK)
async def update_product(product_id: str = Path(...), payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Owner/admin: update product details (name, price, description, image, etc.)."""
    await _assert_product_access(db, product_id, current_user)
    payload.pop("store_id", None)
    payload.pop("storeId", None)
    product = await ProductService.update_product(db, product_id, payload)
    return {"success": True, "message": "Product updated", "data": product}


@router.patch("/{product_id}/toggle-stock", status_code=status.HTTP_200_OK)
async def toggle_stock(product_id: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Owner/admin: toggle a product between in-stock and out-of-stock."""
    await _assert_product_access(db, product_id, current_user)
    product = await ProductService.toggle_stock(db, product_id)
    in_stock = product.get("in_stock") if isinstance(product, dict) else getattr(product, "in_stock", True)
    return {"success": True, "message": f"Product marked {'in stock' if in_stock else 'out of stock'}", "data": product}


@router.delete("/{product_id}", status_code=status.HTTP_200_OK)
async def delete_product(product_id: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Owner/admin: soft-delete a product from a store."""
    await _assert_product_access(db, product_id, current_user)
    await ProductService.delete_product(db, product_id)
    return {"success": True, "message": "Product removed", "data": None}
