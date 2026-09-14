import uuid
from sqlalchemy import Column, String, DateTime, Text, Index, Boolean, Integer
from sqlalchemy.dialects.postgresql import UUID
from app.db.session import Base
from app.core.timezone import get_colombia_now


class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    description = Column(Text, nullable=False)
    due_date = Column(DateTime(timezone=True), nullable=True)
    completed = Column(Boolean, default=False, nullable=False)
    google_event_id = Column(Text, nullable=True)
    project = Column(String, nullable=True)
    priority = Column(String, nullable=False, default="medium")
    estimated_minutes = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=get_colombia_now, nullable=False)

