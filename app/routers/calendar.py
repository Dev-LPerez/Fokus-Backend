import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from uuid import UUID
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_

from app.core.auth import get_current_user
from app.core.timezone import COLOMBIA_TZ, get_colombia_now
from app.db.session import get_db
from app.models.reminder import Reminder
from app.models.user_integration import UserIntegration
from app.services.google_calendar import google_calendar_service, GoogleCalendarError, GoogleCalendarNotConnected
from app.schemas.calendar import (
    CalendarAgendaResponse,
    CalendarEventItem,
    CreateCalendarEventRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calendar", tags=["Calendar"])


def _parse_iso_or_fallback(date_str: Optional[str], default_dt: datetime) -> datetime:
    if not date_str:
        return default_dt
    try:
        # Handle simple date YYYY-MM-DD
        if len(date_str) == 10:
            parsed = datetime.strptime(date_str, "%Y-%m-%d")
            return parsed.replace(tzinfo=COLOMBIA_TZ)
        # Handle ISO format
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=COLOMBIA_TZ)
        return dt
    except Exception:
        return default_dt


@router.get("/events", response_model=CalendarAgendaResponse)
async def get_calendar_events(
    start: Optional[str] = Query(None, description="Fecha de inicio (ISO o YYYY-MM-DD)"),
    end: Optional[str] = Query(None, description="Fecha de fin (ISO o YYYY-MM-DD)"),
    current_user: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Retorna la agenda unificada (Google Calendar + Tareas locales con fecha)
    para cualquier rango temporal solicitado (día, semana, mes, año).
    """
    now = get_colombia_now()

    # Default range: start of current month to end of current month + 7 days buffer
    default_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    default_end = default_start + timedelta(days=45)

    start_dt = _parse_iso_or_fallback(start, default_start)
    end_dt = _parse_iso_or_fallback(end, default_end)

    # 1. Check Google Calendar integration
    integration = await google_calendar_service.get_user_integration(current_user, db)
    calendar_connected = integration is not None

    google_events: List[Dict[str, Any]] = []
    if calendar_connected:
        try:
            google_events = await google_calendar_service.list_events(
                user_id=current_user,
                time_min=start_dt,
                time_max=end_dt,
                db=db
            )
        except GoogleCalendarNotConnected:
            calendar_connected = False
        except Exception as exc:
            logger.warning(f"Error consultando eventos de Google Calendar para {current_user}: {exc}")
            # Do not crash the entire agenda if Google API fails or has expired scope
            google_events = []

    # 2. Query user tasks/reminders in range
    tasks_stmt = select(Reminder).where(
        Reminder.user_id == current_user,
        Reminder.due_date.isnot(None),
        Reminder.due_date >= start_dt,
        Reminder.due_date <= end_dt
    ).order_by(Reminder.due_date.asc())

    tasks_res = await db.execute(tasks_stmt)
    user_tasks = tasks_res.scalars().all()

    # 3. Transform and unify events
    unified_items: List[CalendarEventItem] = []
    synced_google_ids = set()

    for task in user_tasks:
        if task.google_event_id:
            synced_google_ids.add(task.google_event_id)

        task_start = task.due_date
        duration = task.estimated_minutes or 60
        task_end = task_start + timedelta(minutes=duration)

        is_deep_work = "deep work" in (task.description or "").lower() or (task.project or "").lower() == "deep work"

        unified_items.append(
            CalendarEventItem(
                id=str(task.id),
                title=task.description,
                start=task_start.isoformat(),
                end=task_end.isoformat(),
                source="deep_work" if is_deep_work else "task",
                description=f"Proyecto: {task.project or 'General'}",
                all_day=False,
                priority=task.priority,
                project=task.project,
                completed=task.completed,
                estimated_minutes=task.estimated_minutes,
                google_event_id=task.google_event_id
            )
        )

    # Add Google Calendar events (excluding duplicates already tracked as tasks)
    for gev in google_events:
        gid = gev.get("id")
        if gid in synced_google_ids:
            continue

        g_summary = gev.get("summary") or "Sin título"
        g_start = gev.get("start") or ""
        g_end = gev.get("end") or ""
        g_desc = gev.get("description") or ""

        all_day = "T" not in g_start and len(g_start) == 10
        is_deep_work = "deep work" in g_summary.lower()

        unified_items.append(
            CalendarEventItem(
                id=f"gcal_{gid}",
                title=g_summary,
                start=g_start,
                end=g_end,
                source="deep_work" if is_deep_work else "google_calendar",
                description=g_desc,
                all_day=all_day,
                google_event_id=gid
            )
        )

    # Sort all events chronologically
    unified_items.sort(key=lambda item: item.start)

    return CalendarAgendaResponse(
        calendar_connected=calendar_connected,
        start_range=start_dt.isoformat(),
        end_range=end_dt.isoformat(),
        events=unified_items,
        google_events_count=len(google_events),
        tasks_count=len(user_tasks)
    )


@router.post("/events", response_model=CalendarEventItem, status_code=status.HTTP_201_CREATED)
async def create_calendar_event(
    payload: CreateCalendarEventRequest,
    current_user: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Crea un nuevo evento o compromiso directamente desde el calendario,
    sincronizando con Google Calendar si está conectado.
    """
    due_date = payload.start_time
    if due_date.tzinfo is None:
        due_date = due_date.replace(tzinfo=COLOMBIA_TZ)

    end_date = due_date + timedelta(minutes=payload.duration_minutes)

    google_event_id: Optional[str] = None
    if payload.sync_to_google:
        try:
            google_event_id = await google_calendar_service.create_event(
                user_id=current_user,
                title=payload.title,
                description=payload.description or f"Compromiso: {payload.project}",
                due_date=due_date,
                end_date=end_date,
                duration_minutes=payload.duration_minutes,
                db=db
            )
        except GoogleCalendarNotConnected:
            google_event_id = None
        except Exception as exc:
            logger.warning(f"No se pudo sincronizar evento a Google Calendar: {exc}")
            google_event_id = None

    is_deep_work = "deep work" in payload.title.lower() or (payload.project or "").lower() == "deep work"

    reminder = Reminder(
        user_id=current_user,
        description=payload.title,
        project=payload.project or "Calendario",
        priority=payload.priority or "medium",
        due_date=due_date,
        estimated_minutes=payload.duration_minutes,
        google_event_id=google_event_id,
        completed=False
    )
    db.add(reminder)
    await db.commit()
    await db.refresh(reminder)

    return CalendarEventItem(
        id=str(reminder.id),
        title=reminder.description,
        start=due_date.isoformat(),
        end=end_date.isoformat(),
        source="deep_work" if is_deep_work else "task",
        description=payload.description or f"Proyecto: {reminder.project}",
        all_day=False,
        priority=reminder.priority,
        project=reminder.project,
        completed=False,
        estimated_minutes=reminder.estimated_minutes,
        google_event_id=google_event_id
    )


@router.delete("/events/{event_id}", status_code=status.HTTP_200_OK)
async def delete_calendar_event(
    event_id: str,
    current_user: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Elimina un evento o tarea del calendario y retira el evento de Google Calendar
    si estaba vinculado.
    """
    # 1. Check if it's a local Reminder UUID
    try:
        task_uuid = UUID(event_id)
        task_stmt = select(Reminder).where(
            Reminder.id == task_uuid,
            Reminder.user_id == current_user
        )
        task_res = await db.execute(task_stmt)
        task = task_res.scalar_one_or_none()

        if task:
            if task.google_event_id:
                try:
                    await google_calendar_service.delete_event(current_user, task.google_event_id, db)
                except Exception as exc:
                    logger.warning(f"Error borrando evento en Google Calendar: {exc}")

            await db.delete(task)
            await db.commit()
            return {"success": True, "message": "Tarea eliminada exitosamente"}
    except ValueError:
        # Not a UUID, likely a Google Calendar event ID (e.g. gcal_123 or raw ID)
        pass

    # 2. Check if it's a raw Google Calendar event ID
    raw_gcal_id = event_id.replace("gcal_", "")
    try:
        await google_calendar_service.delete_event(current_user, raw_gcal_id, db)
        return {"success": True, "message": "Evento de Google Calendar eliminado"}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No se pudo eliminar el evento del calendario: {str(exc)}"
        )
