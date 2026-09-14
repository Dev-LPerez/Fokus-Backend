from pydantic import BaseModel
from typing import List, Optional, Dict, Any


class BriefingResponse(BaseModel):
    date: str
    weather: Dict[str, Any]
    calendar_connected: bool
    events_today: List[Dict[str, Any]]
    critical_tasks: List[Dict[str, Any]]
    pending_tasks_count: int
    free_slots_summary: str
