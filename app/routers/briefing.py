import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.auth import get_current_user
from app.core.timezone import COLOMBIA_TZ, get_colombia_now
from app.db.session import get_db, AsyncSessionLocal
from app.models.reminder import Reminder
from app.schemas.briefing import BriefingResponse
from app.services.google_calendar import google_calendar_service
from app.services.tools.weather import WeatherTool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/briefing", tags=["Executive Briefing"])


def _format_time_str(dt_str: str) -> str:
    try:
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        return dt.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return dt_str


def _generate_slots_summary(slots: List[Dict[str, Any]], calendar_connected: bool) -> str:
    if not calendar_connected:
        return "Conecta tu Google Calendar para auditar tus bloques de Deep Work."
    if not slots:
        return "No tienes bloques libres de al menos 1 hora disponibles hoy para Deep Work."

    best_slot = max(slots, key=lambda s: s.get("duration_minutes", 0))
    duration = best_slot.get("duration_minutes", 0)

    if duration % 60 == 0:
        h = duration // 60
        hours_str = f"{h} hora" if h == 1 else f"{h} horas"
    else:
        hours_str = f"{round(duration / 60, 1)} horas"

    start_fmt = _format_time_str(best_slot.get("start", ""))
    end_fmt = _format_time_str(best_slot.get("end", ""))

    return f"Tienes {hours_str} libres entre {start_fmt} y {end_fmt} para Deep Work."


@router.get("", response_model=BriefingResponse)
async def get_daily_briefing(
    city: Optional[str] = Query(default=None, description="Ciudad para consultar el clima"),
    lat: Optional[float] = Query(default=None, description="Latitud geográfica del usuario"),
    lon: Optional[float] = Query(default=None, description="Longitud geográfica del usuario"),
    current_user: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Daily Standup & Executive Briefing:
    Aggregates current weather (using user coordinates or specified city), Google Calendar schedule,
    critical/high-priority tasks, and available Deep Work focus slots for today.
    """
    now_col = get_colombia_now()
    today = now_col.date()
    day_start = datetime(today.year, today.month, today.day, 0, 0, 0, tzinfo=COLOMBIA_TZ)
    day_end = datetime(today.year, today.month, today.day, 23, 59, 59, tzinfo=COLOMBIA_TZ)

    # 1. Check calendar integration and query pending reminders from db
    integration = await google_calendar_service.get_user_integration(current_user, db)
    calendar_connected = integration is not None

    stmt = (
        select(Reminder)
        .where(Reminder.user_id == current_user, Reminder.completed.is_(False))
        .order_by(Reminder.due_date.asc().nulls_last())
    )
    reminders_res = await db.execute(stmt)
    reminders = reminders_res.scalars().all()

    # 2. Coroutines for external I/O running concurrently via asyncio.gather
    async def fetch_calendar():
        if not calendar_connected:
            return []
        try:
            return await google_calendar_service.list_events(
                user_id=current_user,
                time_min=day_start,
                time_max=day_end,
                db=db
            )
        except Exception as exc:
            logger.warning(f"Error consultando calendario para briefing: {exc}")
            return []

    async def fetch_weather():
        tool = WeatherTool()
        is_default = False
        if lat is not None and lon is not None:
            res = await tool.execute(latitude=lat, longitude=lon)
        elif city and city.strip():
            res = await tool.execute(city=city.strip())
        else:
            is_default = True
            res = await tool.execute(city="Bogotá")

        if "error" in res:
            return {
                "city": res.get("city") or city or "Ubicación desconocida",
                "country": "",
                "temp": None,
                "description": res.get("error"),
                "is_default_location": is_default
            }

        return {
            "city": res.get("city") or city or "Ubicación actual",
            "country": res.get("country", ""),
            "temp": round(res["temperature"]) if res.get("temperature") is not None else None,
            "description": res.get("description"),
            "is_default_location": is_default
        }

    # Parallel execution of external integrations
    events_today, weather = await asyncio.gather(
        fetch_calendar(),
        fetch_weather()
    )

    # 3. Calculate free slots using retrieved calendar events
    if calendar_connected:
        free_slots = await google_calendar_service.find_free_slots(
            user_id=current_user,
            target_date=today,
            min_duration_minutes=60,
            events=events_today
        )
    else:
        free_slots = []

    critical_tasks = [
        {
            "id": str(r.id),
            "description": r.description,
            "due_date": r.due_date.isoformat() if r.due_date else None,
            "project": r.project,
            "priority": r.priority,
            "estimated_minutes": r.estimated_minutes
        }
        for r in reminders
        if r.priority == "high"
    ]

    free_slots_summary = _generate_slots_summary(free_slots, calendar_connected)

    return BriefingResponse(
        date=today.isoformat(),
        weather=weather,
        calendar_connected=calendar_connected,
        events_today=events_today,
        critical_tasks=critical_tasks,
        pending_tasks_count=len(reminders),
        free_slots_summary=free_slots_summary
    )
