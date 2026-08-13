from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException, status
from app.modules.carts.models import Cart, CartItem
from app.modules.products.models import Product
import uuid

class CartService:
    @staticmethod
    async def get_cart(db: AsyncSession, customer_id: str):
        result = await db.execute(select(Cart).where(Cart.customer_id == customer_id))
        cart = result.scalar_one_or_none()
        if not cart:
            return None
        items_result = await db.execute(select(CartItem).where(CartItem.cart_id == cart.id))
        return {"cart": cart, "items": items_result.scalars().all()}

    @staticmethod
    async def add_item(db: AsyncSession, customer_id: str, data: dict):
        product_id = data.get("product_id")
        quantity = data.get("quantity", 1)
        addons = data.get("addons")

        # Look up the product to enforce store lock
        prod_result = await db.execute(select(Product).where(Product.id == product_id, Product.is_deleted == False))
        product = prod_result.scalar_one_or_none()
        if not product:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

        # Get or create cart
        cart_result = await db.execute(select(Cart).where(Cart.customer_id == customer_id))
        cart = cart_result.scalar_one_or_none()

        if cart:
            # Enforce store lock
            if cart.store_id and str(cart.store_id) != str(product.store_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cart is locked to another store. Clear your cart before adding from a different store."
                )
        else:
            cart = Cart(customer_id=customer_id, store_id=product.store_id)
            db.add(cart)
            await db.flush()

        # Check if item already in cart
        existing_result = await db.execute(
            select(CartItem).where(CartItem.cart_id == cart.id, CartItem.product_id == product_id)
        )
        existing_item = existing_result.scalar_one_or_none()

        if existing_item:
            existing_item.quantity += quantity
        else:
            db.add(CartItem(cart_id=cart.id, product_id=product_id, quantity=quantity, addons=addons))

        await db.commit()
        return await CartService.get_cart(db, customer_id)

    @staticmethod
    async def update_item(db: AsyncSession, customer_id: str, item_id: str, quantity: int):
        cart_result = await db.execute(select(Cart).where(Cart.customer_id == customer_id))
        cart = cart_result.scalar_one_or_none()
        if not cart:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart not found")

        item_result = await db.execute(select(CartItem).where(CartItem.id == item_id, CartItem.cart_id == cart.id))
        item = item_result.scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found in cart")

        if quantity <= 0:
            await db.delete(item)
        else:
            item.quantity = quantity
        await db.commit()
        return await CartService.get_cart(db, customer_id)

    @staticmethod
    async def remove_item(db: AsyncSession, customer_id: str, item_id: str):
        cart_result = await db.execute(select(Cart).where(Cart.customer_id == customer_id))
        cart = cart_result.scalar_one_or_none()
        if not cart:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart not found")
        item_result = await db.execute(select(CartItem).where(CartItem.id == item_id, CartItem.cart_id == cart.id))
        item = item_result.scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found in cart")
        await db.delete(item)
        await db.commit()
        return await CartService.get_cart(db, customer_id)

    @staticmethod
    async def clear_cart(db: AsyncSession, customer_id: str):
        cart_result = await db.execute(select(Cart).where(Cart.customer_id == customer_id))
        cart = cart_result.scalar_one_or_none()
        if cart:
            items_result = await db.execute(select(CartItem).where(CartItem.cart_id == cart.id))
            for item in items_result.scalars().all():
                await db.delete(item)
            cart.store_id = None
            await db.commit()
