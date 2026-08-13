from fastapi import APIRouter, Depends, status, Path, Body, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.modules.products.service import ProductService

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


@router.get("/{product_id}", status_code=status.HTTP_200_OK)
async def get_product(product_id: str = Path(...), db: AsyncSession = Depends(get_db)):
    """Get a single product with its options/addons."""
    product = await ProductService.get_by_id(db, product_id)
    return {"success": True, "message": "Product retrieved", "data": product}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_product(payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Create a new product in a store."""
    product = await ProductService.create_product(db, payload)
    return {"success": True, "message": "Product created successfully", "data": product}


@router.put("/{product_id}", status_code=status.HTTP_200_OK)
async def update_product(product_id: str = Path(...), payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Update product details (name, price, description, image, etc.)."""
    product = await ProductService.update_product(db, product_id, payload)
    return {"success": True, "message": "Product updated", "data": product}


@router.patch("/{product_id}/toggle-stock", status_code=status.HTTP_200_OK)
async def toggle_stock(product_id: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Toggle a product between in-stock and out-of-stock."""
    product = await ProductService.toggle_stock(db, product_id)
    return {"success": True, "message": f"Product marked {'in stock' if product.in_stock else 'out of stock'}", "data": product}


@router.delete("/{product_id}", status_code=status.HTTP_200_OK)
async def delete_product(product_id: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Soft-delete a product from a store."""
    await ProductService.delete_product(db, product_id)
    return {"success": True, "message": "Product removed", "data": None}
