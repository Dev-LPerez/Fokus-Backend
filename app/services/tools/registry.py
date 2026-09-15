from typing import Dict, List, Any, Optional
from .base import BaseTool
from .weather import WeatherTool
from .reminders import (
    ReminderTool,
    ListRemindersTool,
    CompleteReminderTool,
    DeleteReminderTool
)
from .web_search import WebSearchTool
from .calendar_agenda import (
    GetCalendarAgendaTool,
    FindFreeWorkSlotsTool,
    ScheduleDeepWorkTool
)
from .user_profile import SetUserLocationTool


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        # Register default tools
        self.register(WeatherTool())
        self.register(ReminderTool())
        self.register(ListRemindersTool())
        self.register(CompleteReminderTool())
        self.register(DeleteReminderTool())
        self.register(WebSearchTool())
        self.register(GetCalendarAgendaTool())
        self.register(FindFreeWorkSlotsTool())
        self.register(ScheduleDeepWorkTool())
        self.register(SetUserLocationTool())

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def get_all(self) -> List[BaseTool]:
        return list(self._tools.values())

    def get_gemini_declarations(self) -> List[Dict[str, Any]]:
        return [tool.get_gemini_declaration() for tool in self._tools.values()]

    def get_all_info(self) -> List[Dict[str, Any]]:
        return [tool.get_info() for tool in self._tools.values()]


# Singleton registry instance
registry = ToolRegistry()
