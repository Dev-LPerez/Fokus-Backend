from typing import Optional, List, Literal
from datetime import datetime
from pydantic import BaseModel, Field


class CalendarEventItem(BaseModel):
    id: str = Field(..., description="ID único del evento o tarea")
    title: str = Field(..., description="Título o descripción del evento")
    start: str = Field(..., description="Fecha/hora de inicio en formato ISO o fecha YYYY-MM-DD")
    end: str = Field(..., description="Fecha/hora de fin en formato ISO o fecha YYYY-MM-DD")
    source: Literal["google_calendar", "task", "deep_work"] = Field(
        ..., description="Origen del evento (Google Calendar, tarea o bloque Deep Work)"
    )
    description: Optional[str] = Field(default="", description="Descripción adicional o notas")
    all_day: bool = Field(default=False, description="Indica si el evento dura todo el día")
    priority: Optional[str] = Field(default=None, description="Prioridad si proviene de tareas (high, medium, low)")
    project: Optional[str] = Field(default=None, description="Proyecto contenedor si aplica")
    completed: Optional[bool] = Field(default=None, description="Estado de compleción si proviene de tareas")
    estimated_minutes: Optional[int] = Field(default=None, description="Duración estimada en minutos")
    google_event_id: Optional[str] = Field(default=None, description="ID asociado en Google Calendar si está sincronizado")


class CalendarAgendaResponse(BaseModel):
    calendar_connected: bool = Field(..., description="Indica si el usuario tiene Google Calendar conectado")
    start_range: str = Field(..., description="Fecha/hora inicial del rango consultado")
    end_range: str = Field(..., description="Fecha/hora final del rango consultado")
    events: List[CalendarEventItem] = Field(default_factory=list, description="Eventos y tareas unificados en el rango")
    google_events_count: int = Field(default=0, description="Total de eventos de Google Calendar en el rango")
    tasks_count: int = Field(default=0, description="Total de tareas del usuario en el rango")


class CreateCalendarEventRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, description="Título del evento o tarea")
    start_time: datetime = Field(..., description="Fecha y hora de inicio")
    duration_minutes: int = Field(default=60, ge=15, le=480, description="Duración en minutos")
    description: Optional[str] = Field(default="", description="Notas o descripción")
    project: Optional[str] = Field(default="Calendario", description="Proyecto asociado")
    priority: Optional[str] = Field(default="medium", description="Prioridad (high, medium, low)")
    sync_to_google: bool = Field(default=True, description="Sincronizar a Google Calendar si está conectado")
