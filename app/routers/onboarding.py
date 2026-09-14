from datetime import datetime, timezone, timedelta
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.auth import get_current_user
from app.core.timezone import get_colombia_now
from app.db.session import get_db
from app.models.reminder import Reminder
from app.models.conversation import Conversation
from app.models.user_integration import UserIntegration
from app.models.user_onboarding import UserOnboarding
from app.schemas.onboarding import (
    OnboardingStatusResponse,
    CompleteOnboardingResponse,
    SeedTasksRequest,
)
from app.schemas.reminder import ReminderResponse

router = APIRouter(prefix="/onboarding", tags=["Onboarding"])

DEFAULT_STARTER_PROMPTS = [
    "Audita mi agenda en Google Calendar y busca bloques de Deep Work para hoy.",
    "Organiza mis prioridades pendientes utilizando la Matriz de Eisenhower.",
    "Dame mi Daily Briefing matutino: clima de hoy y compromisos clave.",
    "Agenda un bloque de concentración de 90 minutos para avanzar en mi proyecto."
]


@router.get("/status", response_model=OnboardingStatusResponse)
async def get_onboarding_status(
    current_user: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Evalúa la activación del usuario:
    - ¿Ha visto/completado explícitamente el nuevo onboarding? (Persistido en user_onboardings).
      Tanto usuarios nuevos como usuarios antiguos que nunca completaron este onboarding
      tendrán has_seen_onboarding = False para garantizar que reciban la inducción.
    - ¿Tiene Google Calendar conectado?
    - ¿Ha creado tareas o recordatorios?
    - ¿Ha iniciado conversaciones en el chat?
    - Entrega prompts sugeridos para acelerar el Time-to-Value.
    """
    # 1. Check persistent onboarding completion
    onb_stmt = select(UserOnboarding).where(UserOnboarding.user_id == current_user)
    onb_res = await db.execute(onb_stmt)
    user_onb = onb_res.scalar_one_or_none()
    has_seen = bool(user_onb and user_onb.has_seen)

    # 2. Check Google Calendar integration
    cal_stmt = select(UserIntegration).where(
        UserIntegration.user_id == current_user,
        UserIntegration.provider == "google_calendar"
    )
    cal_res = await db.execute(cal_stmt)
    has_calendar = cal_res.scalar_one_or_none() is not None

    # 3. Check task count
    task_count_stmt = select(func.count(Reminder.id)).where(Reminder.user_id == current_user)
    task_res = await db.execute(task_count_stmt)
    tasks_count = task_res.scalar() or 0

    # 4. Check conversation count
    conv_count_stmt = select(func.count(Conversation.id)).where(Conversation.user_id == current_user)
    conv_res = await db.execute(conv_count_stmt)
    conv_count = conv_res.scalar() or 0

    return OnboardingStatusResponse(
        has_seen_onboarding=has_seen,
        has_calendar_connected=has_calendar,
        has_created_task=tasks_count > 0,
        has_started_chat=conv_count > 0,
        tasks_count=tasks_count,
        suggested_starter_prompts=DEFAULT_STARTER_PROMPTS
    )


@router.post("/complete", response_model=CompleteOnboardingResponse)
async def complete_onboarding(
    current_user: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Registra que el usuario (nuevo o antiguo) ha visto y completado/descartado
    el flujo de onboarding de forma persistente.
    """
    onb_stmt = select(UserOnboarding).where(UserOnboarding.user_id == current_user)
    onb_res = await db.execute(onb_stmt)
    user_onb = onb_res.scalar_one_or_none()

    if not user_onb:
        user_onb = UserOnboarding(
            user_id=current_user,
            has_seen=True,
            completed_at=get_colombia_now()
        )
        db.add(user_onb)
    else:
        user_onb.has_seen = True
        user_onb.completed_at = get_colombia_now()

    await db.commit()
    return CompleteOnboardingResponse(
        success=True,
        message="Onboarding completado exitosamente"
    )


@router.post("/seed-tasks", response_model=List[ReminderResponse], status_code=status.HTTP_201_CREATED)
async def seed_starter_tasks(
    payload: SeedTasksRequest,
    current_user: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Puebla tareas iniciales realistas para experimentar de inmediato la Matriz de Eisenhower
    y la reserva de bloques de Deep Work sin empezar desde cero.
    """
    project = (payload.project_name or "Estrategia Q1").strip()
    now = datetime.now(timezone.utc)

    starter_definitions = [
        {
            "description": "Definir prioridades de alto impacto para la semana",
            "priority": "high",
            "estimated_minutes": 60,
            "due_date": now + timedelta(hours=4),
        },
        {
            "description": "Revisar agenda y bloquear 90 min de Deep Work",
            "priority": "high",
            "estimated_minutes": 90,
            "due_date": now + timedelta(hours=8),
        },
        {
            "description": "Auditar correo y responder solicitudes urgentes",
            "priority": "medium",
            "estimated_minutes": 30,
            "due_date": now + timedelta(days=1),
        },
        {
            "description": "Explorar comandos del Copiloto Ejecutivo en /chat",
            "priority": "low",
            "estimated_minutes": 15,
            "due_date": now + timedelta(days=2),
        },
    ]

    created_reminders = []
    for item in starter_definitions:
        r = Reminder(
            user_id=current_user,
            description=item["description"],
            project=project,
            priority=item["priority"],
            estimated_minutes=item["estimated_minutes"],
            due_date=item["due_date"],
            completed=False
        )
        db.add(r)
        created_reminders.append(r)

    await db.commit()
    for r in created_reminders:
        await db.refresh(r)

    return created_reminders
