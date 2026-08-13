from fastapi import APIRouter, Depends, status, Path, Body, UploadFile, File, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.modules.inventory.service import InventoryService

router = APIRouter()


@router.get("/product/{product_id}", status_code=status.HTTP_200_OK)
async def get_inventory(product_id: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get current inventory levels for a specific product."""
    inventory = await InventoryService.get_by_product(db, product_id)
    return {"success": True, "message": "Inventory retrieved", "data": inventory}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_inventory(payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Initialize inventory tracking for a product."""
    inventory = await InventoryService.create(db, payload)
    return {"success": True, "message": "Inventory initialized", "data": inventory}


@router.post("/product/{product_id}/adjust", status_code=status.HTTP_200_OK)
async def adjust_inventory(product_id: str = Path(...), payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Apply a stock adjustment (restock, deduction). Positive = restock, negative = deduction."""
    inventory = await InventoryService.adjust(db, product_id, payload)
    return {"success": True, "message": "Inventory adjusted", "data": inventory}


@router.get("/low-stock", status_code=status.HTTP_200_OK)
async def get_low_stock(db: AsyncSession = Depends(get_db), current_user: dict = Depends(require_role("merchant_owner"))):
    """Get all products that are at or below their low stock threshold."""
    items = await InventoryService.get_low_stock(db)
    return {"success": True, "message": "Low stock items retrieved", "data": items}


@router.post("/import", status_code=status.HTTP_200_OK)
async def import_inventory_csv(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Import inventory quantities and optional product image URLs from a CSV file.
    Expected columns: product_id, quantity, low_stock_threshold (optional), image (optional)
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must be a CSV file (.csv)"
        )

    try:
        contents = await file.read()
        csv_contents = contents.decode("utf-8-sig")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to decode CSV file: {str(e)}"
        )

    result = await InventoryService.import_from_csv(db, csv_contents)
    return result
