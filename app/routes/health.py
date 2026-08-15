from fastapi import APIRouter, status
from app.config import settings

router = APIRouter(tags=["Health"])

@router.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    return {
        "status": "healthy",
        "service": "LinkPlease Instagram DM Automation",
        "api_key_configured": bool(settings.API_KEY)
    }
