from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from uuid import UUID
from datetime import datetime


class ReminderCreate(BaseModel):
    description: str = Field(..., min_length=1)
    due_date: Optional[datetime] = None
    project: Optional[str] = None
    priority: str = Field(default="medium")
    estimated_minutes: Optional[int] = None


class ReminderUpdate(BaseModel):
    description: Optional[str] = Field(default=None, min_length=1)
    due_date: Optional[datetime] = None
    completed: Optional[bool] = None
    project: Optional[str] = None
    priority: Optional[str] = None
    estimated_minutes: Optional[int] = None


class ReminderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    description: str
    due_date: Optional[datetime] = None
    completed: bool = False
    google_event_id: Optional[str] = None
    project: Optional[str] = None
    priority: str = "medium"
    estimated_minutes: Optional[int] = None
    created_at: datetime
