import uuid
from sqlalchemy import Column, String, DateTime, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from app.db.session import Base
from app.core.timezone import get_colombia_now


class UserIntegration(Base):
    __tablename__ = "user_integrations"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_user_integrations_user_provider"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    provider = Column(String, nullable=False)
    access_token_encrypted = Column(Text, nullable=False)
    refresh_token_encrypted = Column(Text, nullable=False)
    token_expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=get_colombia_now, nullable=False)
