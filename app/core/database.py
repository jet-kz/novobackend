from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core import config

# Configure async engine with production-ready connection pooling
engine = create_async_engine(
    config.DATABASE_URL,
    echo=config.DEBUG,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=1800,
)

# Async session generator
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

from sqlalchemy.types import UserDefinedType

class Geography(UserDefinedType):
    cache_ok = True  # Required for SQLAlchemy 1.4+ caching

    def __init__(self, geometry_type="Point", srid=4326):
        self.geometry_type = geometry_type
        self.srid = srid

    def get_col_spec(self, **kw):
        return f"GEOGRAPHY({self.geometry_type}, {self.srid})"

    def result_processor(self, dialect, coltype):
        """
        Convert the raw WKB hex string that PostGIS returns
        into a JSON-serializable {"longitude": x, "latitude": y} dict.
        Falls back gracefully to None if parsing fails.
        """
        def process(value):
            if value is None:
                return None
            try:
                import struct, binascii
                # Handle both hex strings and raw bytes
                if isinstance(value, str):
                    raw = binascii.unhexlify(value)
                else:
                    raw = bytes(value)
                # WKB EWKB layout: 1 byte order + 4 byte type + 4 byte SRID (if present) + 8 + 8 for x,y
                byte_order = raw[0]
                fmt = "<" if byte_order == 1 else ">"
                # Read geometry type (includes SRID flag in EWKB)
                geom_type = struct.unpack_from(f"{fmt}I", raw, 1)[0]
                has_srid = bool(geom_type & 0x20000000)
                offset = 5 + (4 if has_srid else 0)
                lon, lat = struct.unpack_from(f"{fmt}dd", raw, offset)
                return {"longitude": round(lon, 8), "latitude": round(lat, 8)}
            except Exception:
                # Return raw value as str so it doesn't break the response
                return str(value)
        return process

# Setup declarative Base
Base = declarative_base()

# FastAPI Route dependency
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

