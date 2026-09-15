import logging
from datetime import datetime, date, timedelta
from typing import Any, Dict, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import COLOMBIA_TZ, get_colombia_now
from app.db.session import AsyncSessionLocal
from app.models.reminder import Reminder
from app.models.user_preference import UserPreference
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
    description = "Consulta y retorna los eventos y reuniones programadas en Google Calendar para un día determinado, detectando solapamientos (conflictos) y reuniones prioritarias/clave."
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
                now_col = get_colombia_now()
                is_today = (target_date == now_col.date())
                tomorrow_date = (target_date + timedelta(days=1)).isoformat()

                enriched_events = []
                for ev in events:
                    ev_copy = dict(ev)
                    if is_today:
                        end_val = ev.get("end")
                        start_val = ev.get("start")
                        try:
                            if end_val and len(end_val) > 10:
                                end_dt = datetime.fromisoformat(end_val)
                                if end_dt.tzinfo is None:
                                    end_dt = end_dt.replace(tzinfo=COLOMBIA_TZ)
                                else:
                                    end_dt = end_dt.astimezone(COLOMBIA_TZ)

                                start_dt = None
                                if start_val and len(start_val) > 10:
                                    start_dt = datetime.fromisoformat(start_val)
                                    if start_dt.tzinfo is None:
                                        start_dt = start_dt.replace(tzinfo=COLOMBIA_TZ)
                                    else:
                                        start_dt = start_dt.astimezone(COLOMBIA_TZ)

                                if end_dt <= now_col:
                                    ev_copy["time_status"] = "past"
                                elif start_dt and start_dt <= now_col < end_dt:
                                    ev_copy["time_status"] = "in_progress"
                                else:
                                    ev_copy["time_status"] = "upcoming"
                        except Exception:
                            pass
                    enriched_events.append(ev_copy)

                conflicts = google_calendar_service.detect_conflicts(enriched_events)
                key_meetings = [ev for ev in enriched_events if ev.get("is_key_meeting")]

                return {
                    "success": True,
                    "date": target_date.isoformat(),
                    "is_today": is_today,
                    "current_time": now_col.strftime("%H:%M") if is_today else None,
                    "total_events": len(enriched_events),
                    "events": enriched_events,
                    "key_meetings": key_meetings,
                    "total_key_meetings": len(key_meetings),
                    "conflicts": conflicts,
                    "has_conflicts": len(conflicts) > 0,
                    "suggested_next_date": tomorrow_date if is_today else None
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
    description = "Calcula los bloques de tiempo libres en la jornada laboral del usuario para agendar trabajo o llamadas sin generar colisiones. Si se consulta para hoy, tiene en cuenta la hora de la consulta, descarta bloques que ya pasaron, aplica descansos/smart buffers y sugiere evaluar el día siguiente si no hay disponibilidad."
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
            },
            "buffer_minutes": {
                "type": "integer",
                "description": "Minutos de descanso/margen entre reuniones (ej. 10 o 15 minutos). Opcional."
            }
        },
        "required": []
    }

    async def execute(
        self,
        date_str: Optional[str] = None,
        duration_minutes: int = 60,
        buffer_minutes: Optional[int] = None,
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
                # Cargar preferencias de jornada si existen
                effective_buffer = buffer_minutes if buffer_minutes is not None else 0
                workday_start = 8
                workday_end = 19

                try:
                    pref_stmt = select(UserPreference).where(UserPreference.user_id == user_id)
                    pref_res = await session.execute(pref_stmt)
                    user_pref = pref_res.scalar_one_or_none()
                    if user_pref:
                        if buffer_minutes is None:
                            effective_buffer = user_pref.buffer_minutes or 0
                        workday_start = user_pref.workday_start_hour or 8
                        workday_end = user_pref.workday_end_hour or 19
                except Exception as e:
                    logger.warning(f"No se pudieron cargar preferencias de usuario: {e}")

                slots = await google_calendar_service.find_free_slots(
                    user_id=user_id,
                    target_date=target_date,
                    min_duration_minutes=duration_minutes,
                    workday_start_hour=workday_start,
                    workday_end_hour=workday_end,
                    buffer_minutes=effective_buffer,
                    db=session
                )
                now_col = get_colombia_now()
                is_today = (target_date == now_col.date())
                tomorrow_date = (target_date + timedelta(days=1)).isoformat()

                if not is_today:
                    return {
                        "success": True,
                        "date": target_date.isoformat(),
                        "is_today": False,
                        "min_duration_minutes": duration_minutes,
                        "total_slots": len(slots),
                        "free_slots": slots
                    }

                available_slots = []
                past_slots = []

                for slot in slots:
                    try:
                        s_dt = datetime.strptime(slot["start"], "%Y-%m-%d %H:%M").replace(tzinfo=COLOMBIA_TZ)
                        e_dt = datetime.strptime(slot["end"], "%Y-%m-%d %H:%M").replace(tzinfo=COLOMBIA_TZ)

                        if e_dt <= now_col:
                            # Slot completamente en el pasado
                            past_slots.append({
                                **slot,
                                "status": "past",
                                "note": "Este horario ya transcurrió."
                            })
                        elif s_dt < now_col < e_dt:
                            # Slot en curso
                            rem_minutes = int((e_dt - now_col).total_seconds() / 60)
                            if rem_minutes >= duration_minutes:
                                available_slots.append({
                                    "start": now_col.strftime("%Y-%m-%d %H:%M"),
                                    "end": slot["end"],
                                    "duration_minutes": rem_minutes,
                                    "original_start": slot["start"],
                                    "status": "in_progress",
                                    "note": f"Hueco en curso con {rem_minutes} minutos disponibles restantes."
                                })
                            else:
                                past_slots.append({
                                    **slot,
                                    "status": "insufficient_remaining_time",
                                    "remaining_minutes": rem_minutes,
                                    "note": f"Tiempo restante ({rem_minutes} min) inferior al mínimo de {duration_minutes} min."
                                })
                        else:
                            # Slot futuro en el día de hoy
                            available_slots.append({
                                **slot,
                                "status": "future_available"
                            })
                    except Exception:
                        available_slots.append(slot)

                day_ended = (len(available_slots) == 0)
                current_time_str = now_col.strftime("%H:%M")

                if day_ended:
                    note = (
                        f"Hora de la consulta: {current_time_str}. Todos los huecos de la jornada de hoy ({len(past_slots)} bloques) "
                        f"ya pasaron o la jornada concluyó. Ya no es posible apartar tiempo para esos horarios de hoy. "
                        f"Informa al usuario que ya no se puede apartar tiempo para hoy debido a que el horario ya pasó, y procede a ofrecerle revisar la disponibilidad para mañana ({tomorrow_date}) si lo desea."
                    )
                else:
                    note = (
                        f"Hora de la consulta: {current_time_str}. Quedan {len(available_slots)} hueco(s) de trabajo disponible(s) hoy a partir de este momento. "
                        f"{len(past_slots)} bloque(s) previos ya pasaron y no se pueden apartar."
                    )

                return {
                    "success": True,
                    "date": target_date.isoformat(),
                    "is_today": True,
                    "current_time": current_time_str,
                    "min_duration_minutes": duration_minutes,
                    "total_slots": len(available_slots),
                    "free_slots": available_slots,
                    "past_slots": past_slots,
                    "day_ended": day_ended,
                    "suggested_next_date": tomorrow_date,
                    "message": note
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
                is_today = (t_date == now_col.date())
                tomorrow_date = (t_date + timedelta(days=1)).isoformat()
                if is_today:
                    return {
                        "success": False,
                        "error": f"No hay ningún bloque libre disponible de al menos {duration_minutes} minutos para lo que queda de hoy ({now_col.strftime('%H:%M')}), ya que los horarios previos ya transcurrieron.",
                        "is_today": True,
                        "current_time": now_col.strftime("%H:%M"),
                        "day_ended": True,
                        "suggested_next_date": tomorrow_date,
                        "suggestion": f"Informa al usuario que ya no hay disponibilidad hoy porque los horarios ya pasaron, y pregúntale si desea programar el bloque de Deep Work para mañana ({tomorrow_date}).",
                        "available_slots": slots
                    }
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
