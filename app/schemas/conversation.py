from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from uuid import UUID
from datetime import datetime


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    role: str
    content: Optional[str] = None
    tool_name: Optional[str] = None
    created_at: datetime


class ConversationCreate(BaseModel):
    title: Optional[str] = "Nueva conversación"


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: Optional[str] = None
    created_at: datetime


class ConversationDetailResponse(ConversationResponse):
    messages: List[MessageResponse] = []
