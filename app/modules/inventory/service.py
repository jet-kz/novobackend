import csv
import io
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException, status
from app.modules.inventory.models import InventoryItem, InventoryAdjustment
from app.modules.products.models import Product


class InventoryService:
    @staticmethod
    async def get_by_product(db: AsyncSession, product_id: str):
        result = await db.execute(select(InventoryItem).where(InventoryItem.product_id == product_id))
        item = result.scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory item not found")
        return item

    @staticmethod
    async def create(db: AsyncSession, data: dict):
        item = InventoryItem(**data)
        db.add(item)
        await db.commit()
        await db.refresh(item)
        return item

    @staticmethod
    async def adjust(db: AsyncSession, product_id: str, data: dict):
        result = await db.execute(select(InventoryItem).where(InventoryItem.product_id == product_id))
        item = result.scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory item not found")

        qty_delta = int(data.get("quantity", 0))
        item.quantity = max(0, item.quantity + qty_delta)

        adjustment = InventoryAdjustment(
            inventory_item_id=item.id,
            adjustment_type=data.get("adjustment_type", "adjustment"),
            quantity=qty_delta,
            reason=data.get("reason")
        )
        db.add(adjustment)
        await db.commit()
        await db.refresh(item)
        return item

    @staticmethod
    async def get_low_stock(db: AsyncSession):
        result = await db.execute(select(InventoryItem))
        all_items = result.scalars().all()
        return [i for i in all_items if i.quantity <= i.low_stock_threshold]

    @staticmethod
    async def import_from_csv(db: AsyncSession, csv_contents: str) -> dict:
        """
        Parses a CSV file containing inventory levels and product images.
        Expected columns:
        - product_id / productid (required) — UUID string
        - quantity / qty (required) — integer
        - low_stock_threshold / threshold / low_stock (optional) — integer
        - image / image_url / img (optional) — string url
        """
        f = io.StringIO(csv_contents.strip())
        reader = csv.DictReader(f)

        if not reader.fieldnames:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Empty CSV file or missing headers"
            )

        processed_count = 0
        updated_inventory = []
        errors = []

        for index, row in enumerate(reader, start=1):
            # Normalize row keys to lowercase and strip whitespace
            norm_row = {
                (k.strip().lower() if k else ""): (v.strip() if v else "")
                for k, v in row.items() 
                if k is not None
            }

            p_id_str = norm_row.get("product_id") or norm_row.get("productid")
            qty_str = norm_row.get("quantity") or norm_row.get("qty")
            threshold_str = norm_row.get("low_stock_threshold") or norm_row.get("threshold") or norm_row.get("low_stock")
            img_val = norm_row.get("image") or norm_row.get("image_url") or norm_row.get("img")

            if not p_id_str:
                errors.append(f"Row {index}: Missing product_id")
                continue
            if qty_str is None or qty_str == "":
                errors.append(f"Row {index}: Missing quantity")
                continue

            try:
                product_id = uuid.UUID(p_id_str)
            except ValueError:
                errors.append(f"Row {index}: Invalid product_id format (must be UUID)")
                continue

            try:
                quantity = int(qty_str)
            except ValueError:
                errors.append(f"Row {index}: Invalid quantity value (must be integer)")
                continue

            low_stock_threshold = 5
            if threshold_str:
                try:
                    low_stock_threshold = int(threshold_str)
                except ValueError:
                    errors.append(f"Row {index}: Invalid low_stock_threshold value (must be integer)")
                    continue

            # 1. Verify target product exists and is not deleted
            prod_result = await db.execute(
                select(Product).where(Product.id == product_id, Product.is_deleted == False)
            )
            product = prod_result.scalar_one_or_none()
            if not product:
                errors.append(f"Row {index}: Product with ID {p_id_str} not found or is deleted")
                continue

            # 2. Update product image if provided
            if img_val:
                product.image = img_val
                db.add(product)

            # 3. Upsert inventory item
            inv_result = await db.execute(
                select(InventoryItem).where(InventoryItem.product_id == product_id)
            )
            item = inv_result.scalar_one_or_none()

            if item:
                # Update existing inventory item
                old_qty = item.quantity
                item.quantity = max(0, quantity)
                item.low_stock_threshold = low_stock_threshold
                db.add(item)

                # Record stock adjustment log
                qty_diff = quantity - old_qty
                adjustment = InventoryAdjustment(
                    inventory_item_id=item.id,
                    adjustment_type="import",
                    quantity=qty_diff,
                    reason=f"CSV bulk import (set to {quantity})"
                )
                db.add(adjustment)
            else:
                # Create a new inventory record
                item = InventoryItem(
                    product_id=product_id,
                    quantity=max(0, quantity),
                    low_stock_threshold=low_stock_threshold
                )
                db.add(item)
                await db.flush()  # Populates item.id/uuid for the child adjustment relation

                adjustment = InventoryAdjustment(
                    inventory_item_id=item.id,
                    adjustment_type="import",
                    quantity=quantity,
                    reason="CSV bulk import (initialized)"
                )
                db.add(adjustment)

            processed_count += 1
            updated_inventory.append({
                "product_id": str(product_id),
                "quantity": quantity,
                "low_stock_threshold": low_stock_threshold,
                "image_updated": bool(img_val)
            })

        if processed_count > 0:
            await db.commit()

        return {
            "success": True,
            "processed_count": processed_count,
            "updated_items": updated_inventory,
            "errors": errors
        }
