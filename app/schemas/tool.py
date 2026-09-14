from pydantic import BaseModel
from typing import Dict, Any, List


class ToolParameter(BaseModel):
    type: str
    description: str
    enum: List[str] | None = None


class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any]
