import logging
from typing import Any, Dict, Optional, List
from uuid import UUID
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.core.timezone import COLOMBIA_TZ
from app.db.session import AsyncSessionLocal
from app.models.reminder import Reminder
from app.services.google_calendar import (
    google_calendar_service,
    GoogleCalendarNotConnected,
    GoogleCalendarError
)
from .base import BaseTool

logger = logging.getLogger(__name__)


def _parse_due_date(due_date_str: str) -> Optional[datetime]:
    formats = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d"
    ]
    for fmt in formats:
        try:
            parsed = datetime.strptime(due_date_str.replace("Z", "+0000"), fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=COLOMBIA_TZ)
            return parsed
        except ValueError:
            continue
    return None


class ReminderTool(BaseTool):
    name = "create_reminder"
    description = "Crea y guarda una tarea o recordatorio. Permite clasificar por proyecto/cliente, prioridad y duración estimada. Si el usuario tiene Google Calendar conectado y se proporciona fecha límite, se sincroniza automáticamente."
    parameters = {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Descripción clara del recordatorio o tarea (ej. 'Comprar leche', 'Entrega de informe')"
            },
            "due_date": {
                "type": "string",
                "description": "Fecha y hora límite en formato ISO 8601 o 'YYYY-MM-DD HH:MM'. Opcional."
            },
            "project": {
                "type": "string",
                "description": "Nombre del proyecto, cliente o área (ej. 'Backend API', 'Cliente Acme', 'Finanzas'). Opcional."
            },
            "priority": {
                "type": "string",
                "description": "Nivel de prioridad: 'high' (urgente/crítico), 'medium' (importante), 'low' (rutina). Por defecto 'medium'."
            },
            "estimated_minutes": {
                "type": "integer",
                "description": "Duración estimada en minutos para completar la tarea. Opcional."
            }
        },
        "required": ["description"]
    }

    async def execute(
        self,
        description: str,
        due_date: Optional[str] = None,
        project: Optional[str] = None,
        priority: str = "medium",
        estimated_minutes: Optional[int] = None,
        db: Optional[AsyncSession] = None,
        user_id: Optional[UUID] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        if user_id is None:
            return {
                "success": False,
                "error": "user_id es requerido para crear y asociar el recordatorio al usuario.",
                "description": description
            }

        parsed_date = _parse_due_date(due_date) if due_date else None
        valid_priority = priority.lower() if priority and priority.lower() in ("high", "medium", "low") else "medium"

        async def _run(session: AsyncSession) -> Dict[str, Any]:
            reminder = Reminder(
                user_id=user_id,
                description=description,
                due_date=parsed_date,
                completed=False,
                project=project,
                priority=valid_priority,
                estimated_minutes=estimated_minutes
            )
            session.add(reminder)
            await session.commit()
            await session.refresh(reminder)

            calendar_synced = False
            calendar_note = None

            if parsed_date:
                try:
                    event_id = await google_calendar_service.create_event(
                        user_id=user_id,
                        title=description,
                        description=f"Recordatorio: {description}" + (f"\nProyecto: {project}" if project else ""),
                        due_date=parsed_date,
                        db=session,
                        duration_minutes=estimated_minutes or 60
                    )
                    reminder.google_event_id = event_id
                    await session.commit()
                    await session.refresh(reminder)
                    calendar_synced = True
                except GoogleCalendarNotConnected:
                    calendar_synced = False
                    calendar_note = "Conecta tu Google Calendar para recibir notificaciones automáticas."
                except Exception as exc:
                    logger.warning(f"No se pudo sincronizar el recordatorio con Google Calendar: {exc}")
                    calendar_synced = False
                    calendar_note = f"No se pudo sincronizar con Google Calendar: {str(exc)}"

            res = {
                "success": True,
                "id": str(reminder.id),
                "user_id": str(reminder.user_id),
                "description": reminder.description,
                "due_date": reminder.due_date.isoformat() if reminder.due_date else None,
                "completed": reminder.completed,
                "google_event_id": reminder.google_event_id,
                "project": reminder.project,
                "priority": reminder.priority,
                "estimated_minutes": reminder.estimated_minutes,
                "calendar_synced": calendar_synced,
                "created_at": reminder.created_at.isoformat()
            }
            if calendar_note:
                res["note"] = calendar_note
            return res

        try:
            if db is not None:
                return await _run(db)
            else:
                async with AsyncSessionLocal() as session:
                    return await _run(session)
        except Exception as exc:
            return {
                "success": False,
                "error": f"Error al guardar el recordatorio en la base de datos: {str(exc)}",
                "description": description
            }


class ListRemindersTool(BaseTool):
    name = "list_reminders"
    description = "Lista las tareas y recordatorios registrados por el usuario actual, con filtros opcionales por estado, proyecto o prioridad."
    parameters = {
        "type": "object",
        "properties": {
            "include_completed": {
                "type": "boolean",
                "description": "Si es True, incluye también las tareas ya completadas. Por defecto es False (solo pendientes)."
            },
            "project": {
                "type": "string",
                "description": "Filtrar por nombre de proyecto o cliente. Opcional."
            },
            "priority": {
                "type": "string",
                "description": "Filtrar por prioridad ('high', 'medium', 'low'). Opcional."
            }
        },
        "required": []
    }

    async def execute(
        self,
        include_completed: bool = False,
        project: Optional[str] = None,
        priority: Optional[str] = None,
        db: Optional[AsyncSession] = None,
        user_id: Optional[UUID] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        if user_id is None:
            return {
                "success": False,
                "error": "user_id es requerido para consultar los recordatorios."
            }

        async def _run(session: AsyncSession) -> Dict[str, Any]:
            stmt = select(Reminder).where(Reminder.user_id == user_id)
            if not include_completed:
                stmt = stmt.where(Reminder.completed.is_(False))
            if project:
                stmt = stmt.where(Reminder.project.ilike(f"%{project.strip()}%"))
            if priority:
                stmt = stmt.where(Reminder.priority == priority.lower().strip())
            stmt = stmt.order_by(Reminder.created_at.desc())

            res = await session.execute(stmt)
            reminders = res.scalars().all()

            items = [
                {
                    "id": str(r.id),
                    "description": r.description,
                    "due_date": r.due_date.isoformat() if r.due_date else None,
                    "completed": r.completed,
                    "google_event_id": r.google_event_id,
                    "project": r.project,
                    "priority": r.priority,
                    "estimated_minutes": r.estimated_minutes,
                    "created_at": r.created_at.isoformat()
                } for r in reminders
            ]
            return {
                "success": True,
                "total": len(items),
                "reminders": items
            }

        try:
            if db is not None:
                return await _run(db)
            else:
                async with AsyncSessionLocal() as session:
                    return await _run(session)
        except Exception as exc:
            return {
                "success": False,
                "error": f"Error al listar recordatorios: {str(exc)}"
            }


class CompleteReminderTool(BaseTool):
    name = "complete_reminder"
    description = "Marca un recordatorio o tarea existente como completada."
    parameters = {
        "type": "object",
        "properties": {
            "reminder_id": {
                "type": "string",
                "description": "El ID (UUID) del recordatorio o tarea a marcar como completada."
            }
        },
        "required": ["reminder_id"]
    }

    async def execute(
        self,
        reminder_id: str,
        db: Optional[AsyncSession] = None,
        user_id: Optional[UUID] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        if user_id is None:
            return {
                "success": False,
                "error": "user_id es requerido para completar el recordatorio."
            }

        try:
            target_uuid = UUID(reminder_id)
        except ValueError:
            return {
                "success": False,
                "error": f"ID de recordatorio inválido: '{reminder_id}'."
            }

        async def _run(session: AsyncSession) -> Dict[str, Any]:
            stmt = select(Reminder).where(
                Reminder.id == target_uuid,
                Reminder.user_id == user_id
            )
            res = await session.execute(stmt)
            reminder = res.scalar_one_or_none()

            if not reminder:
                return {
                    "success": False,
                    "error": "Recordatorio no encontrado o no pertenece a tu usuario."
                }

            reminder.completed = True
            await session.commit()
            await session.refresh(reminder)

            return {
                "success": True,
                "id": str(reminder.id),
                "description": reminder.description,
                "completed": True,
                "message": f"Tarea '{reminder.description}' marcada como completada exitosamente."
            }

        try:
            if db is not None:
                return await _run(db)
            else:
                async with AsyncSessionLocal() as session:
                    return await _run(session)
        except Exception as exc:
            return {
                "success": False,
                "error": f"Error al completar recordatorio: {str(exc)}"
            }


class DeleteReminderTool(BaseTool):
    name = "delete_reminder"
    description = "Elimina un recordatorio o tarea existente. Si tenía un evento sincronizado en Google Calendar, también lo elimina del calendario."
    parameters = {
        "type": "object",
        "properties": {
            "reminder_id": {
                "type": "string",
                "description": "El ID (UUID) del recordatorio o tarea a eliminar."
            }
        },
        "required": ["reminder_id"]
    }

    async def execute(
        self,
        reminder_id: str,
        db: Optional[AsyncSession] = None,
        user_id: Optional[UUID] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        if user_id is None:
            return {
                "success": False,
                "error": "user_id es requerido para eliminar el recordatorio."
            }

        try:
            target_uuid = UUID(reminder_id)
        except ValueError:
            return {
                "success": False,
                "error": f"ID de recordatorio inválido: '{reminder_id}'."
            }

        async def _run(session: AsyncSession) -> Dict[str, Any]:
            stmt = select(Reminder).where(
                Reminder.id == target_uuid,
                Reminder.user_id == user_id
            )
            res = await session.execute(stmt)
            reminder = res.scalar_one_or_none()

            if not reminder:
                return {
                    "success": False,
                    "error": "Recordatorio no encontrado o no pertenece a tu usuario."
                }

            calendar_deleted = False
            if reminder.google_event_id:
                try:
                    calendar_deleted = await google_calendar_service.delete_event(
                        user_id=user_id,
                        event_id=reminder.google_event_id,
                        db=session
                    )
                except Exception as exc:
                    logger.warning(f"No se pudo eliminar el evento en Google Calendar: {exc}")

            await session.delete(reminder)
            await session.commit()

            return {
                "success": True,
                "id": str(target_uuid),
                "message": "Recordatorio eliminado exitosamente.",
                "calendar_deleted": calendar_deleted
            }

        try:
            if db is not None:
                return await _run(db)
            else:
                async with AsyncSessionLocal() as session:
                    return await _run(session)
        except Exception as exc:
            return {
                "success": False,
                "error": f"Error al eliminar recordatorio: {str(exc)}"
            }
