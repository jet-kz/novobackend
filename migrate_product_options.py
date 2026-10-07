import asyncio
from sqlalchemy import text
from app.core.database import engine

async def migrate():
    print("Running database migration for product options and specs...")
    async with engine.begin() as conn:
        for stmt in [
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS protein_options JSONB DEFAULT '[]'::jsonb;",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS extras_options JSONB DEFAULT '[]'::jsonb;",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS specs JSONB DEFAULT '{}'::jsonb;",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS option_groups JSONB DEFAULT '[]'::jsonb;",
        ]:
            print(f"Executing: {stmt}")
            await conn.execute(text(stmt))
    print("SUCCESS: Migration completed successfully!")

if __name__ == "__main__":
    asyncio.run(migrate())
