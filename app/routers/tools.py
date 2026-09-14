from fastapi import APIRouter
from typing import List, Dict, Any
from app.services.tools.registry import registry

router = APIRouter(prefix="/tools", tags=["Tools"])


@router.get("", response_model=List[Dict[str, Any]])
async def list_tools():
    """Returns metadata of all registered tools supported by the AI Agent."""
    return registry.get_all_info()
