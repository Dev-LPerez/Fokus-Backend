from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict
from uuid import UUID


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="The user prompt or question")
    conversation_id: Optional[UUID] = Field(None, description="Optional conversation ID to resume")


class ToolCallInfo(BaseModel):
    tool_name: str
    args: Dict[str, Any]
    result: Optional[Any] = None


class ChatResponse(BaseModel):
    conversation_id: UUID
    response: str
    tool_calls: List[ToolCallInfo] = Field(default_factory=list)


class StreamEvent(BaseModel):
    event: str  # e.g., "tool_start", "tool_end", "token", "error", "done"
    data: Any
