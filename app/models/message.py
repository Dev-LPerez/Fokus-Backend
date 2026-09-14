import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey, CheckConstraint, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.core.timezone import get_colombia_now


class Message(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=True)
    tool_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=get_colombia_now, nullable=False)

    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant', 'tool')", name="check_valid_role"),
    )

    # Relationship
    conversation = relationship("Conversation", back_populates="messages")
