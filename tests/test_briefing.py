import pytest
import respx
import httpx
from datetime import datetime, timezone, timedelta
from cryptography.fernet import Fernet

from app.core.config import settings
from app.core.encryption import encrypt_token
from app.models.reminder import Reminder
from app.models.user_integration import UserIntegration


@pytest.fixture(autouse=True)
def setup_briefing_env(monkeypatch):
    test_key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", test_key)
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "mock_client_id")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "mock_client_secret")
    monkeypatch.setattr(settings, "OPENWEATHER_API_KEY", "mock_weather_key")


@pytest.mark.asyncio
async def test_briefing_unauthorized(client):
    response = await client.get("/briefing")
    assert response.status_code == 401


@pytest.mark.asyncio
@respx.mock
async def test_briefing_without_calendar(client, user_a_headers, user_a_id, db_session):
    # Mock Weather API
    respx.get("https://api.openweathermap.org/data/2.5/weather").mock(
        return_value=httpx.Response(200, json={
            "name": "Bogotá",
            "sys": {"country": "CO"},
            "main": {"temp": 18.5, "feels_like": 18.0, "temp_min": 15.0, "temp_max": 20.0, "humidity": 65},
            "weather": [{"description": "cielo claro"}]
        })
    )

    # Add reminders: 1 high priority, 1 medium, 1 completed
    r1 = Reminder(
        user_id=user_a_id,
        description="Llamar a inversionistas",
        priority="high",
        project="Finanzas",
        completed=False
    )
    r2 = Reminder(
        user_id=user_a_id,
        description="Comprar café",
        priority="low",
        completed=False
    )
    r3 = Reminder(
        user_id=user_a_id,
        description="Tarea terminada",
        priority="high",
        completed=True
    )
    db_session.add_all([r1, r2, r3])
    await db_session.commit()

    response = await client.get("/briefing?city=Bogotá", headers=user_a_headers)
    assert response.status_code == 200

    data = response.json()
    assert "date" in data
    assert data["calendar_connected"] is False
    assert data["events_today"] == []
    assert data["pending_tasks_count"] == 2
    assert len(data["critical_tasks"]) == 1
    assert data["critical_tasks"][0]["description"] == "Llamar a inversionistas"
    assert data["critical_tasks"][0]["project"] == "Finanzas"
    assert "Google Calendar" in data["free_slots_summary"]
    assert data["weather"]["temp"] == 19 or data["weather"]["temp"] == 18
    assert data["weather"]["description"] == "cielo claro"


@pytest.mark.asyncio
@respx.mock
async def test_briefing_with_calendar_connected(client, user_a_headers, user_a_id, db_session):
    # Mock Weather API
    respx.get("https://api.openweathermap.org/data/2.5/weather").mock(
        return_value=httpx.Response(200, json={
            "name": "Bogotá",
            "sys": {"country": "CO"},
            "main": {"temp": 20.0, "feels_like": 20.0, "temp_min": 18.0, "temp_max": 22.0, "humidity": 60},
            "weather": [{"description": "parcialmente nublado"}]
        })
    )

    # Connect Google Calendar
    integration = UserIntegration(
        user_id=user_a_id,
        provider="google_calendar",
        access_token_encrypted=encrypt_token("mock_access_briefing"),
        refresh_token_encrypted=encrypt_token("mock_refresh_briefing"),
        token_expires_at=datetime.now(timezone.utc) + timedelta(hours=2)
    )
    db_session.add(integration)
    await db_session.commit()

    # Mock Google Calendar API
    respx.get("https://www.googleapis.com/calendar/v3/calendars/primary/events").mock(
        return_value=httpx.Response(200, json={
            "items": [
                {
                    "id": "briefing_event_1",
                    "summary": "Daily Standup de Ingeniería",
                    "start": {"dateTime": "2026-09-03T09:00:00-05:00"},
                    "end": {"dateTime": "2026-09-03T09:30:00-05:00"},
                    "status": "confirmed"
                }
            ]
        })
    )

    response = await client.get("/briefing", headers=user_a_headers)
    assert response.status_code == 200

    data = response.json()
    assert data["calendar_connected"] is True
    assert len(data["events_today"]) == 1
    assert data["events_today"][0]["summary"] == "Daily Standup de Ingeniería"
    assert "Deep Work" in data["free_slots_summary"]
    assert "libres" in data["free_slots_summary"]


@pytest.mark.asyncio
@respx.mock
async def test_briefing_with_coordinates(client, user_a_headers, user_a_id, db_session):
    respx.get("https://api.openweathermap.org/data/2.5/weather").mock(
        return_value=httpx.Response(200, json={
            "name": "Montería",
            "sys": {"country": "CO"},
            "main": {"temp": 29.4, "feels_like": 34.0, "temp_min": 28.0, "temp_max": 30.0, "humidity": 80},
            "weather": [{"description": "cielo claro"}]
        })
    )

    response = await client.get("/briefing?lat=8.75&lon=-75.88", headers=user_a_headers)
    assert response.status_code == 200

    data = response.json()
    assert data["weather"]["city"] == "Montería"
    assert data["weather"]["temp"] == 29
    assert data["weather"]["is_default_location"] is False


@pytest.mark.asyncio
async def test_briefing_no_location_returns_location_required(client, user_a_headers, user_a_id):
    # Solicitud a briefing sin parámetros y sin preferencias guardadas
    response = await client.get("/briefing", headers=user_a_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["weather"]["location_required"] is True
    assert data["weather"]["city"] is None
    assert "ubicación" in data["weather"]["message"]


@pytest.mark.asyncio
@respx.mock
async def test_briefing_uses_saved_user_preference_city(client, user_a_headers, user_a_id, db_session):
    from app.models.user_preference import UserPreference

    pref = UserPreference(
        user_id=user_a_id,
        city="Medellín",
        buffer_minutes=15
    )
    db_session.add(pref)
    await db_session.commit()

    respx.get("https://api.openweathermap.org/data/2.5/weather").mock(
        return_value=httpx.Response(200, json={
            "name": "Medellín",
            "sys": {"country": "CO"},
            "main": {"temp": 24.0, "feels_like": 25.0, "temp_min": 22.0, "temp_max": 26.0, "humidity": 65},
            "weather": [{"description": "nubes dispersas"}]
        })
    )

    response = await client.get("/briefing", headers=user_a_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["weather"]["city"] == "Medellín"
    assert data["weather"]["location_required"] is False
    assert data["weather"]["temp"] == 24


@pytest.mark.asyncio
@respx.mock
async def test_briefing_detects_conflicts_and_overdue_tasks(client, user_a_headers, user_a_id, db_session):
    from app.core.timezone import get_colombia_now

    # Conectar Google Calendar
    integration = UserIntegration(
        user_id=user_a_id,
        provider="google_calendar",
        access_token_encrypted=encrypt_token("mock_access"),
        refresh_token_encrypted=encrypt_token("mock_refresh"),
        token_expires_at=datetime.now(timezone.utc) + timedelta(hours=2)
    )
    db_session.add(integration)

    # Tarea vencida de ayer
    now_col = get_colombia_now()
    yesterday = now_col - timedelta(days=1)
    overdue_reminder = Reminder(
        user_id=user_a_id,
        description="Enviar reporte mensual vencido",
        priority="high",
        due_date=yesterday,
        completed=False
    )
    db_session.add(overdue_reminder)
    await db_session.commit()

    # Mock de 2 eventos que se solapan
    respx.get("https://www.googleapis.com/calendar/v3/calendars/primary/events").mock(
        return_value=httpx.Response(200, json={
            "items": [
                {
                    "id": "conf_1",
                    "summary": "Reunión Estratégica",
                    "start": {"dateTime": f"{now_col.strftime('%Y-%m-%d')}T10:00:00-05:00"},
                    "end": {"dateTime": f"{now_col.strftime('%Y-%m-%d')}T11:00:00-05:00"}
                },
                {
                    "id": "conf_2",
                    "summary": "Demo con Cliente",
                    "description": "https://meet.google.com/abc-def-ghi",
                    "start": {"dateTime": f"{now_col.strftime('%Y-%m-%d')}T10:30:00-05:00"},
                    "end": {"dateTime": f"{now_col.strftime('%Y-%m-%d')}T11:30:00-05:00"}
                }
            ]
        })
    )

    response = await client.get("/briefing?city=Cali", headers=user_a_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["has_conflicts"] is True
    assert len(data["conflicts"]) == 1
    assert data["conflicts"][0]["overlap_minutes"] == 30
    assert data["total_overdue_tasks"] == 1
    assert data["overdue_tasks"][0]["description"] == "Enviar reporte mensual vencido"
    # Verificar que reconoció la reunión clave
    demo_event = [ev for ev in data["events_today"] if ev["id"] == "conf_2"][0]
    assert demo_event["is_key_meeting"] is True


