from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.modules.analytics.service import AnalyticsService

router = APIRouter()

@router.get("", status_code=status.HTTP_200_OK)
async def list_analytics(db: AsyncSession = Depends(get_db)):
    analytics = await AnalyticsService.get_analytics(db)
    return {
        "success": True,
        "message": "Analytics compiled successfully",
        "data": analytics
    }
