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
from app.db.session import get_db
from app.models.reminder import Reminder
from app.models.user_preference import UserPreference
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
    Aggregates current weather (using user coordinates, specified city or saved preference),
    Google Calendar schedule, detected meeting conflicts, critical/high-priority tasks,
    overdue tasks, and available Deep Work focus slots for today.
    """
    now_col = get_colombia_now()
    today = now_col.date()
    day_start = datetime(today.year, today.month, today.day, 0, 0, 0, tzinfo=COLOMBIA_TZ)
    day_end = datetime(today.year, today.month, today.day, 23, 59, 59, tzinfo=COLOMBIA_TZ)

    # 1. Check calendar integration, user preferences and query pending reminders from db
    integration = await google_calendar_service.get_user_integration(current_user, db)
    calendar_connected = integration is not None

    user_pref = None
    try:
        pref_stmt = select(UserPreference).where(UserPreference.user_id == current_user)
        pref_res = await db.execute(pref_stmt)
        user_pref = pref_res.scalar_one_or_none()
    except Exception as e:
        logger.warning(f"Error consultando preferencias de usuario en briefing: {e}")
        await db.rollback()

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
        target_city = city.strip() if (city and city.strip()) else (user_pref.city if user_pref and user_pref.city else None)

        if lat is not None and lon is not None:
            res = await tool.execute(latitude=lat, longitude=lon)
        elif target_city:
            res = await tool.execute(city=target_city)
        else:
            # No location provided and no saved city preference - DO NOT default to Bogotá
            return {
                "city": None,
                "country": "",
                "temp": None,
                "description": "Ubicación no configurada",
                "is_default_location": False,
                "location_required": True,
                "message": "Para mostrar el clima en tu Daily Briefing, permite el acceso a tu ubicación o configura tu ciudad en preferencias."
            }

        if "error" in res:
            return {
                "city": res.get("city") or target_city or "Ubicación desconocida",
                "country": "",
                "temp": None,
                "description": res.get("error"),
                "is_default_location": is_default,
                "location_required": False
            }

        return {
            "city": res.get("city") or target_city or "Ubicación actual",
            "country": res.get("country", ""),
            "temp": round(res["temperature"]) if res.get("temperature") is not None else None,
            "description": res.get("description"),
            "is_default_location": is_default,
            "location_required": False
        }

    # Parallel execution of external integrations
    events_today, weather = await asyncio.gather(
        fetch_calendar(),
        fetch_weather()
    )

    # 3. Detect meeting conflicts in calendar
    conflicts = google_calendar_service.detect_conflicts(events_today) if calendar_connected else []

    # 4. Calculate free slots using retrieved calendar events and user workday/buffer preferences
    workday_start = user_pref.workday_start_hour if user_pref else 8
    workday_end = user_pref.workday_end_hour if user_pref else 19
    buffer_min = user_pref.buffer_minutes if user_pref else 0

    if calendar_connected:
        free_slots = await google_calendar_service.find_free_slots(
            user_id=current_user,
            target_date=today,
            min_duration_minutes=60,
            workday_start_hour=workday_start,
            workday_end_hour=workday_end,
            buffer_minutes=buffer_min,
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

    # 5. Detect overdue tasks from previous days
    overdue_tasks = [
        {
            "id": str(r.id),
            "description": r.description,
            "due_date": r.due_date.isoformat() if r.due_date else None,
            "project": r.project,
            "priority": r.priority,
            "estimated_minutes": r.estimated_minutes
        }
        for r in reminders
        if r.due_date and r.due_date < day_start
    ]

    free_slots_summary = _generate_slots_summary(free_slots, calendar_connected)

    return BriefingResponse(
        date=today.isoformat(),
        weather=weather,
        calendar_connected=calendar_connected,
        events_today=events_today,
        critical_tasks=critical_tasks,
        pending_tasks_count=len(reminders),
        free_slots_summary=free_slots_summary,
        conflicts=conflicts,
        has_conflicts=len(conflicts) > 0,
        overdue_tasks=overdue_tasks,
        total_overdue_tasks=len(overdue_tasks)
    )
