import uuid
from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from app.db.session import Base
from app.core.timezone import get_colombia_now


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, unique=True, index=True)
    city = Column(String(100), nullable=True)
    workday_start_hour = Column(Integer, default=8, nullable=False)
    workday_end_hour = Column(Integer, default=19, nullable=False)
    buffer_minutes = Column(Integer, default=10, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=get_colombia_now, onupdate=get_colombia_now, nullable=False)
