from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.db.session import get_db

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("")
async def health_check(db: AsyncSession = Depends(get_db)):
    """Health check endpoint to verify service and database connection."""
    db_status = "healthy"
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "database": db_status
            }
        )

    return {
        "status": "healthy",
        "database": db_status
    }
