from fastapi import APIRouter, Depends, status, Path, Body
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import get_current_user
from app.modules.carts.service import CartService

router = APIRouter()


@router.get("", status_code=status.HTTP_200_OK)
async def get_cart(db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get the current user's active cart including all items."""
    cart = await CartService.get_cart(db, current_user["user_id"])
    return {"success": True, "message": "Cart retrieved successfully", "data": cart}


@router.post("/items", status_code=status.HTTP_200_OK)
async def add_item(payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Add a product to the cart. Cart is locked to one store — mixing stores is rejected."""
    cart = await CartService.add_item(db, current_user["user_id"], payload)
    return {"success": True, "message": "Item added to cart", "data": cart}


@router.patch("/items/{item_id}", status_code=status.HTTP_200_OK)
async def update_item_quantity(item_id: str = Path(...), payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Update quantity of a specific cart item. Set to 0 to remove."""
    cart = await CartService.update_item(db, current_user["user_id"], item_id, payload.get("quantity", 1))
    return {"success": True, "message": "Cart item updated", "data": cart}


@router.delete("/items/{item_id}", status_code=status.HTTP_200_OK)
async def remove_item(item_id: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Remove a specific item from the cart."""
    cart = await CartService.remove_item(db, current_user["user_id"], item_id)
    return {"success": True, "message": "Item removed from cart", "data": cart}


@router.delete("", status_code=status.HTTP_200_OK)
async def clear_cart(db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Clear the entire cart (all items). Useful after checkout or when switching store."""
    await CartService.clear_cart(db, current_user["user_id"])
    return {"success": True, "message": "Cart cleared", "data": None}
