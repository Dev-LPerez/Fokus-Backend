import uuid
from sqlalchemy import Column, DateTime, Boolean
from sqlalchemy.dialects.postgresql import UUID
from app.db.session import Base
from app.core.timezone import get_colombia_now


class UserOnboarding(Base):
    __tablename__ = "user_onboardings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, unique=True, index=True)
    has_seen = Column(Boolean, default=True, nullable=False)
    completed_at = Column(DateTime(timezone=True), default=get_colombia_now, nullable=False)
