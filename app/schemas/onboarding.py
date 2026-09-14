from typing import Optional, List
from pydantic import BaseModel, Field


class OnboardingStatusResponse(BaseModel):
    has_seen_onboarding: bool = Field(
        ...,
        description="Indica si el usuario completó o omitió el onboarding explícitamente"
    )
    has_calendar_connected: bool = Field(
        ...,
        description="Indica si el usuario tiene Google Calendar conectado"
    )
    has_created_task: bool = Field(
        ...,
        description="Indica si el usuario ha creado al menos una tarea o compromiso"
    )
    has_started_chat: bool = Field(
        ...,
        description="Indica si el usuario ha iniciado al menos una conversación"
    )
    tasks_count: int = Field(
        default=0,
        description="Cantidad actual de tareas registradas para el usuario"
    )
    suggested_starter_prompts: List[str] = Field(
        default_factory=list,
        description="Comandos y preguntas sugeridas para el primer valor"
    )


class CompleteOnboardingResponse(BaseModel):
    success: bool = True
    message: str = "Onboarding completado exitosamente"


class SeedTasksRequest(BaseModel):
    project_name: Optional[str] = Field(
        default="Mi Primer Proyecto",
        description="Nombre del proyecto contenedor para las tareas iniciales"
    )
