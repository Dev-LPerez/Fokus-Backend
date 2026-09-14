from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseTool(ABC):
    name: str
    description: str
    parameters: Dict[str, Any]

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Any:
        """Executes the tool with the given keyword arguments."""
        pass

    def get_gemini_declaration(self) -> Dict[str, Any]:
        """Returns the function declaration formatted for Gemini function calling."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    def get_info(self) -> Dict[str, Any]:
        """Returns standard information about the tool for API endpoints."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }
