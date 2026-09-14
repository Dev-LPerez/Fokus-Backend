import logging
from datetime import datetime, date, timedelta
from typing import Any, Dict, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import COLOMBIA_TZ, get_colombia_now
from app.db.session import AsyncSessionLocal
from app.models.reminder import Reminder
from app.services.google_calendar import (
    google_calendar_service,
    GoogleCalendarNotConnected,
    GoogleCalendarError
)
from .base import BaseTool

logger = logging.getLogger(__name__)


def _parse_target_date(date_str: Optional[str]) -> date:
    if not date_str:
        return get_colombia_now().date()
    try:
        return date.fromisoformat(date_str.strip())
    except ValueError:
        return get_colombia_now().date()


class GetCalendarAgendaTool(BaseTool):
    name = "get_calendar_agenda"
    description = "Consulta y retorna los eventos y reuniones programadas en Google Calendar para un día determinado (por defecto la fecha actual)."
    parameters = {
        "type": "object",
        "properties": {
            "date_str": {
                "type": "string",
                "description": "Fecha a consultar en formato 'YYYY-MM-DD'. Si se omite, usa la fecha de hoy."
            }
        },
        "required": []
    }

    async def execute(
        self,
        date_str: Optional[str] = None,
        db: Optional[AsyncSession] = None,
        user_id: Optional[UUID] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        if user_id is None:
            return {
                "success": False,
                "error": "user_id es requerido para consultar la agenda del calendario."
            }

        target_date = _parse_target_date(date_str)
        day_start = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=COLOMBIA_TZ)
        day_end = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59, tzinfo=COLOMBIA_TZ)

        async def _run(session: AsyncSession) -> Dict[str, Any]:
            try:
                events = await google_calendar_service.list_events(
                    user_id=user_id,
                    time_min=day_start,
                    time_max=day_end,
                    db=session
                )
                return {
                    "success": True,
                    "date": target_date.isoformat(),
                    "total_events": len(events),
                    "events": events
                }
            except GoogleCalendarNotConnected:
                return {
                    "success": False,
                    "error": "Google Calendar no está conectado. Conecta tu cuenta en Integraciones para consultar la agenda.",
                    "calendar_connected": False,
                    "events": []
                }
            except Exception as exc:
                logger.error(f"Error consultando agenda de calendario: {exc}")
                return {
                    "success": False,
                    "error": f"Error al consultar Google Calendar: {str(exc)}"
                }

        if db is not None:
            return await _run(db)
        async with AsyncSessionLocal() as session:
            return await _run(session)


class FindFreeWorkSlotsTool(BaseTool):
    name = "find_free_work_slots"
    description = "Calcula los bloques de tiempo libres en la jornada laboral del usuario para agendar trabajo o llamadas sin generar colisiones."
    parameters = {
        "type": "object",
        "properties": {
            "date_str": {
                "type": "string",
                "description": "Fecha a evaluar en formato 'YYYY-MM-DD'. Si se omite, usa la fecha de hoy."
            },
            "duration_minutes": {
                "type": "integer",
                "description": "Duración mínima en minutos requerida para los bloques libres (por defecto 60)."
            }
        },
        "required": []
    }

    async def execute(
        self,
        date_str: Optional[str] = None,
        duration_minutes: int = 60,
        db: Optional[AsyncSession] = None,
        user_id: Optional[UUID] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        if user_id is None:
            return {
                "success": False,
                "error": "user_id es requerido para calcular huecos libres en el calendario."
            }

        target_date = _parse_target_date(date_str)

        async def _run(session: AsyncSession) -> Dict[str, Any]:
            try:
                slots = await google_calendar_service.find_free_slots(
                    user_id=user_id,
                    target_date=target_date,
                    min_duration_minutes=duration_minutes,
                    db=session
                )
                return {
                    "success": True,
                    "date": target_date.isoformat(),
                    "min_duration_minutes": duration_minutes,
                    "total_slots": len(slots),
                    "free_slots": slots
                }
            except GoogleCalendarNotConnected:
                return {
                    "success": False,
                    "error": "Google Calendar no está conectado. Conecta tu cuenta en Integraciones para auditar tu disponibilidad.",
                    "calendar_connected": False,
                    "free_slots": []
                }
            except Exception as exc:
                logger.error(f"Error calculando huecos libres: {exc}")
                return {
                    "success": False,
                    "error": f"Error al calcular huecos libres: {str(exc)}"
                }

        if db is not None:
            return await _run(db)
        async with AsyncSessionLocal() as session:
            return await _run(session)


class ScheduleDeepWorkTool(BaseTool):
    name = "schedule_deep_work"
    description = "Busca el mejor hueco libre disponible en Google Calendar y programa un bloque de trabajo enfocado [Deep Work], registrándolo simultáneamente como tarea de alta prioridad."
    parameters = {
        "type": "object",
        "properties": {
            "task_description": {
                "type": "string",
                "description": "Descripción clara del objetivo o tarea del bloque de trabajo enfocado (ej. 'Diseño de arquitectura API', 'Revisión informe financiero')."
            },
            "project": {
                "type": "string",
                "description": "Proyecto, cliente o área a la que pertenece el bloque. Opcional."
            },
            "duration_minutes": {
                "type": "integer",
                "description": "Duración requerida en minutos para la sesión de enfoque (por defecto 90)."
            },
            "target_date": {
                "type": "string",
                "description": "Fecha para programar la sesión en formato 'YYYY-MM-DD'. Si se omite, usa la fecha actual."
            }
        },
        "required": ["task_description"]
    }

    async def execute(
        self,
        task_description: str,
        project: Optional[str] = None,
        duration_minutes: int = 90,
        target_date: Optional[str] = None,
        db: Optional[AsyncSession] = None,
        user_id: Optional[UUID] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        if user_id is None:
            return {
                "success": False,
                "error": "user_id es requerido para programar un bloque de Deep Work."
            }

        t_date = _parse_target_date(target_date)

        async def _run(session: AsyncSession) -> Dict[str, Any]:
            try:
                # 1. Auditar huecos libres
                slots = await google_calendar_service.find_free_slots(
                    user_id=user_id,
                    target_date=t_date,
                    min_duration_minutes=duration_minutes,
                    db=session
                )
            except GoogleCalendarNotConnected:
                return {
                    "success": False,
                    "error": "Google Calendar no está conectado. Para agendar bloques de Deep Work es necesario conectar Google Calendar.",
                    "calendar_connected": False
                }
            except Exception as exc:
                return {
                    "success": False,
                    "error": f"Error al buscar disponibilidad: {str(exc)}"
                }

            now_col = get_colombia_now()
            selected_slot = None
            slot_start_dt = None

            for slot in slots:
                try:
                    s_dt = datetime.strptime(slot["start"], "%Y-%m-%d %H:%M").replace(tzinfo=COLOMBIA_TZ)
                    e_dt = datetime.strptime(slot["end"], "%Y-%m-%d %H:%M").replace(tzinfo=COLOMBIA_TZ)

                    # Si es hoy, aseguramos que empiece en el futuro
                    if t_date == now_col.date() and s_dt < now_col:
                        if (e_dt - now_col).total_seconds() / 60 >= duration_minutes:
                            selected_slot = slot
                            slot_start_dt = now_col.replace(second=0, microsecond=0)
                            break
                        else:
                            continue
                    else:
                        selected_slot = slot
                        slot_start_dt = s_dt
                        break
                except Exception:
                    continue

            if not selected_slot or not slot_start_dt:
                return {
                    "success": False,
                    "error": f"No hay ningún bloque libre disponible de al menos {duration_minutes} minutos en {t_date.isoformat()}.",
                    "available_slots": slots
                }

            slot_end_dt = slot_start_dt + timedelta(minutes=duration_minutes)

            # 2. Crear evento en Google Calendar
            cal_title = f"[Deep Work] {task_description}"
            cal_desc = f"Bloque de enfoque profundo: {task_description}" + (f"\nProyecto: {project}" if project else "")

            try:
                event_id = await google_calendar_service.create_event(
                    user_id=user_id,
                    title=cal_title,
                    description=cal_desc,
                    due_date=slot_start_dt,
                    duration_minutes=duration_minutes,
                    end_date=slot_end_dt,
                    db=session
                )
            except Exception as exc:
                return {
                    "success": False,
                    "error": f"Error al crear el bloque en Google Calendar: {str(exc)}"
                }

            # 3. Registrar tarea ejecutiva en reminders
            reminder = Reminder(
                user_id=user_id,
                description=cal_title,
                due_date=slot_start_dt,
                completed=False,
                google_event_id=event_id,
                project=project,
                priority="high",
                estimated_minutes=duration_minutes
            )
            session.add(reminder)
            await session.commit()
            await session.refresh(reminder)

            return {
                "success": True,
                "message": f"Bloque de Deep Work programado con éxito de {slot_start_dt.strftime('%Y-%m-%d %H:%M')} a {slot_end_dt.strftime('%Y-%m-%d %H:%M')}.",
                "task_id": str(reminder.id),
                "google_event_id": event_id,
                "scheduled_start": slot_start_dt.strftime("%Y-%m-%d %H:%M"),
                "scheduled_end": slot_end_dt.strftime("%Y-%m-%d %H:%M"),
                "duration_minutes": duration_minutes,
                "project": project,
                "priority": "high"
            }

        if db is not None:
            return await _run(db)
        async with AsyncSessionLocal() as session:
            return await _run(session)
