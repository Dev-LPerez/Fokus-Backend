import pytest
import respx
import httpx
from app.services.tools.weather import WeatherTool
from app.services.tools.reminders import ReminderTool
from app.services.tools.web_search import WebSearchTool


@pytest.mark.asyncio
async def test_list_tools_endpoint(client):
    response = await client.get("/tools")
    assert response.status_code == 200
    tools = response.json()
    assert len(tools) >= 3

    tool_names = [t["name"] for t in tools]
    assert "get_weather" in tool_names
    assert "create_reminder" in tool_names
    assert "search_web" in tool_names


@pytest.mark.asyncio
async def test_weather_tool_missing_key(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "OPENWEATHER_API_KEY", "")
    tool = WeatherTool()
    result = await tool.execute(city="Montería")
    assert "error" in result
    assert result["city"] == "Montería"


@pytest.mark.asyncio
@respx.mock
async def test_weather_tool_success(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "OPENWEATHER_API_KEY", "mock_key_123")

    mock_weather_data = {
        "name": "Montería",
        "sys": {"country": "CO"},
        "main": {
            "temp": 28.5,
            "feels_like": 32.0,
            "temp_min": 28.0,
            "temp_max": 29.0,
            "humidity": 80
        },
        "weather": [{"description": "cielo claro"}],
        "wind": {"speed": 2.1}
    }

    respx.get("https://api.openweathermap.org/data/2.5/weather").mock(
        return_value=httpx.Response(200, json=mock_weather_data)
    )

    tool = WeatherTool()
    result = await tool.execute(city="Montería")

    assert result["city"] == "Montería"
    assert result["country"] == "CO"
    assert result["temperature"] == 28.5
    assert result["description"] == "cielo claro"


@pytest.mark.asyncio
@respx.mock
async def test_weather_tool_with_coordinates(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "OPENWEATHER_API_KEY", "mock_key_123")

    mock_weather_data = {
        "name": "Montería",
        "sys": {"country": "CO"},
        "main": {
            "temp": 29.0,
            "feels_like": 34.0,
            "temp_min": 28.0,
            "temp_max": 30.0,
            "humidity": 85
        },
        "weather": [{"description": "cielo despejado"}],
        "wind": {"speed": 1.8}
    }

    respx.get("https://api.openweathermap.org/data/2.5/weather").mock(
        return_value=httpx.Response(200, json=mock_weather_data)
    )

    tool = WeatherTool()
    result = await tool.execute(latitude=8.75, longitude=-75.88)

    assert result["city"] == "Montería"
    assert result["temperature"] == 29.0
    assert result["description"] == "cielo despejado"


@pytest.mark.asyncio
async def test_reminder_tool_execution(db_session, user_a_id):
    tool = ReminderTool()
    result = await tool.execute(
        description="Estudiar para el examen de IA",
        due_date="2026-08-30 18:00",
        db=db_session,
        user_id=user_a_id
    )
    assert result["description"] == "Estudiar para el examen de IA"
    assert result["success"] is True
    assert "id" in result
    assert result["user_id"] == str(user_a_id)


@pytest.mark.asyncio
async def test_reminder_tool_refuses_without_user_id(db_session):
    """Verifies strict isolation: ReminderTool fails cleanly if user_id is None without creating orphan data."""
    tool = ReminderTool()
    result = await tool.execute(
        description="Recordatorio sin usuario",
        due_date="2026-08-30 18:00",
        db=db_session,
        user_id=None
    )
    assert result["success"] is False
    assert "user_id es requerido" in result["error"]


@pytest.mark.asyncio
@respx.mock
async def test_web_search_tool_mocked():
    html_mock = """
    <html>
      <body>
        <div class="result">
          <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Ffastapi.tiangolo.com">FastAPI Documentation</a>
          <a class="result__snippet">FastAPI framework, high performance, easy to learn.</a>
        </div>
      </body>
    </html>
    """
    respx.get(url__startswith="https://html.duckduckgo.com/html/").mock(
        return_value=httpx.Response(200, text=html_mock)
    )

    tool = WebSearchTool()
    result = await tool.execute(query="FastAPI Python")
    assert result["query"] == "FastAPI Python"
    assert result["results_count"] == 1
    assert result["results"][0]["title"] == "FastAPI Documentation"
    assert result["results"][0]["link"] == "https://fastapi.tiangolo.com"
