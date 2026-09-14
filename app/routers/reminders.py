from datetime import datetime
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.core.auth import get_current_user
from app.db.session import get_db
from app.models.reminder import Reminder
from app.schemas.reminder import ReminderCreate, ReminderUpdate, ReminderResponse
from app.services.google_calendar import google_calendar_service

router = APIRouter(prefix="/reminders", tags=["Reminders"])


@router.get("", response_model=List[ReminderResponse])
async def list_reminders(
    include_completed: bool = Query(default=True, description="Incluir tareas completadas"),
    project: Optional[str] = Query(default=None, description="Filtrar por proyecto"),
    priority: Optional[str] = Query(default=None, description="Filtrar por prioridad"),
    current_user: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Retorna las tareas y recordatorios del usuario autenticado."""
    stmt = select(Reminder).where(Reminder.user_id == current_user)
    if not include_completed:
        stmt = stmt.where(Reminder.completed.is_(False))
    if project:
        stmt = stmt.where(Reminder.project.ilike(f"%{project.strip()}%"))
    if priority:
        stmt = stmt.where(Reminder.priority == priority.lower().strip())

    stmt = stmt.order_by(Reminder.completed.asc(), Reminder.due_date.asc().nulls_last(), desc(Reminder.created_at))
    res = await db.execute(stmt)
    return res.scalars().all()


@router.post("", response_model=ReminderResponse, status_code=status.HTTP_201_CREATED)
async def create_reminder(
    payload: ReminderCreate,
    current_user: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Crea una nueva tarea o recordatorio, sincronizando con Google Calendar si aplica."""
    reminder = Reminder(
        user_id=current_user,
        description=payload.description.strip(),
        due_date=payload.due_date,
        project=payload.project.strip() if payload.project else None,
        priority=payload.priority.lower() if payload.priority in ("high", "medium", "low") else "medium",
        estimated_minutes=payload.estimated_minutes,
        completed=False
    )
    db.add(reminder)
    await db.commit()
    await db.refresh(reminder)

    if reminder.due_date:
        try:
            event_id = await google_calendar_service.create_event(
                user_id=current_user,
                title=reminder.description,
                description=f"Tarea: {reminder.description}" + (f"\nProyecto: {reminder.project}" if reminder.project else ""),
                due_date=reminder.due_date,
                duration_minutes=reminder.estimated_minutes or 60,
                db=db
            )
            reminder.google_event_id = event_id
            await db.commit()
            await db.refresh(reminder)
        except Exception:
            pass

    return reminder


@router.patch("/{reminder_id}", response_model=ReminderResponse)
async def update_reminder(
    reminder_id: UUID,
    payload: ReminderUpdate,
    current_user: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Actualiza campos de una tarea existente (ej. marcar completada)."""
    stmt = select(Reminder).where(
        Reminder.id == reminder_id,
        Reminder.user_id == current_user
    )
    res = await db.execute(stmt)
    reminder = res.scalar_one_or_none()

    if not reminder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recordatorio no encontrado."
        )

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(reminder, key, value)

    await db.commit()
    await db.refresh(reminder)
    return reminder


@router.delete("/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reminder(
    reminder_id: UUID,
    current_user: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Elimina una tarea existente y retira su evento en Google Calendar si estaba sincronizado."""
    stmt = select(Reminder).where(
        Reminder.id == reminder_id,
        Reminder.user_id == current_user
    )
    res = await db.execute(stmt)
    reminder = res.scalar_one_or_none()

    if not reminder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recordatorio no encontrado."
        )

    if reminder.google_event_id:
        try:
            await google_calendar_service.delete_event(
                user_id=current_user,
                event_id=reminder.google_event_id,
                db=db
            )
        except Exception:
            pass

    await db.delete(reminder)
    await db.commit()
    return None
