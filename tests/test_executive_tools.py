import pytest
import respx
import httpx
from datetime import datetime, timezone, timedelta
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.core.config import settings
from app.core.encryption import encrypt_token
from app.models.reminder import Reminder
from app.models.user_integration import UserIntegration
from app.services.tools.calendar_agenda import (
    GetCalendarAgendaTool,
    FindFreeWorkSlotsTool,
    ScheduleDeepWorkTool
)
from app.services.tools.reminders import ReminderTool, ListRemindersTool


@pytest.fixture(autouse=True)
def setup_executive_env(monkeypatch):
    test_key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", test_key)
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "mock_client_id")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "mock_client_secret")


@pytest.mark.asyncio
async def test_get_calendar_agenda_not_connected(db_session, user_a_id):
    tool = GetCalendarAgendaTool()
    res = await tool.execute(db=db_session, user_id=user_a_id, date_str="2026-06-15")
    assert res["success"] is False
    assert res["calendar_connected"] is False
    assert "no está conectado" in res["error"]


@pytest.mark.asyncio
@respx.mock
async def test_get_calendar_agenda_success(db_session, user_a_id):
    integration = UserIntegration(
        user_id=user_a_id,
        provider="google_calendar",
        access_token_encrypted=encrypt_token("access_123"),
        refresh_token_encrypted=encrypt_token("refresh_123"),
        token_expires_at=datetime.now(timezone.utc) + timedelta(hours=2)
    )
    db_session.add(integration)
    await db_session.commit()

    respx.get("https://www.googleapis.com/calendar/v3/calendars/primary/events").mock(
        return_value=httpx.Response(200, json={
            "items": [
                {
                    "id": "event_meeting",
                    "summary": "Reunión de Estrategia",
                    "start": {"dateTime": "2026-06-15T10:00:00-05:00"},
                    "end": {"dateTime": "2026-06-15T11:00:00-05:00"},
                    "status": "confirmed"
                }
            ]
        })
    )

    tool = GetCalendarAgendaTool()
    res = await tool.execute(db=db_session, user_id=user_a_id, date_str="2026-06-15")
    assert res["success"] is True
    assert res["total_events"] == 1
    assert res["events"][0]["summary"] == "Reunión de Estrategia"


@pytest.mark.asyncio
@respx.mock
async def test_find_free_work_slots(db_session, user_a_id):
    integration = UserIntegration(
        user_id=user_a_id,
        provider="google_calendar",
        access_token_encrypted=encrypt_token("access_123"),
        refresh_token_encrypted=encrypt_token("refresh_123"),
        token_expires_at=datetime.now(timezone.utc) + timedelta(hours=2)
    )
    db_session.add(integration)
    await db_session.commit()

    respx.get("https://www.googleapis.com/calendar/v3/calendars/primary/events").mock(
        return_value=httpx.Response(200, json={
            "items": [
                {
                    "id": "event_midday",
                    "summary": "Reunión de Equipo",
                    "start": {"dateTime": "2026-06-15T10:00:00-05:00"},
                    "end": {"dateTime": "2026-06-15T12:00:00-05:00"},
                    "status": "confirmed"
                }
            ]
        })
    )

    tool = FindFreeWorkSlotsTool()
    res = await tool.execute(db=db_session, user_id=user_a_id, date_str="2026-06-15", duration_minutes=60)
    assert res["success"] is True
    # 08:00 - 10:00 (120 min) and 12:00 - 19:00 (420 min)
    assert res["total_slots"] == 2
    assert res["free_slots"][0]["start"] == "2026-06-15 08:00"
    assert res["free_slots"][0]["duration_minutes"] == 120


@pytest.mark.asyncio
@respx.mock
async def test_schedule_deep_work_success(db_session, user_a_id):
    integration = UserIntegration(
        user_id=user_a_id,
        provider="google_calendar",
        access_token_encrypted=encrypt_token("access_123"),
        refresh_token_encrypted=encrypt_token("refresh_123"),
        token_expires_at=datetime.now(timezone.utc) + timedelta(hours=2)
    )
    db_session.add(integration)
    await db_session.commit()

    # Free slots query returns empty items -> entire workday free
    respx.get("https://www.googleapis.com/calendar/v3/calendars/primary/events").mock(
        return_value=httpx.Response(200, json={"items": []})
    )

    # Google Calendar event creation
    respx.post("https://www.googleapis.com/calendar/v3/calendars/primary/events").mock(
        return_value=httpx.Response(201, json={"id": "mock_deep_work_event_123"})
    )

    tool = ScheduleDeepWorkTool()
    res = await tool.execute(
        task_description="Rediseñar arquitectura de microservicios",
        project="Backend Core",
        duration_minutes=90,
        target_date="2026-06-15",
        db=db_session,
        user_id=user_a_id
    )

    assert res["success"] is True
    assert res["google_event_id"] == "mock_deep_work_event_123"
    assert res["project"] == "Backend Core"
    assert res["priority"] == "high"
    assert res["duration_minutes"] == 90

    # Verify Reminder was created in database with high priority and project
    stmt = select(Reminder).where(Reminder.google_event_id == "mock_deep_work_event_123")
    db_reminder = (await db_session.execute(stmt)).scalar_one_or_none()
    assert db_reminder is not None
    assert "[Deep Work]" in db_reminder.description
    assert db_reminder.project == "Backend Core"
    assert db_reminder.priority == "high"
    assert db_reminder.estimated_minutes == 90


@pytest.mark.asyncio
async def test_reminders_project_and_priority_filter(db_session, user_a_id):
    create_tool = ReminderTool()
    list_tool = ListRemindersTool()

    # Create task 1 for Project Acme
    await create_tool.execute(
        description="Enviar cotización",
        project="Cliente Acme",
        priority="high",
        estimated_minutes=30,
        db=db_session,
        user_id=user_a_id
    )

    # Create task 2 for Project Internal
    await create_tool.execute(
        description="Actualizar dependencias",
        project="Infraestructura",
        priority="low",
        estimated_minutes=45,
        db=db_session,
        user_id=user_a_id
    )

    # Filter by project Acme
    res_acme = await list_tool.execute(
        project="Acme",
        db=db_session,
        user_id=user_a_id
    )
    assert res_acme["success"] is True
    assert res_acme["total"] == 1
    assert res_acme["reminders"][0]["description"] == "Enviar cotización"
    assert res_acme["reminders"][0]["priority"] == "high"

    # Filter by priority low
    res_low = await list_tool.execute(
        priority="low",
        db=db_session,
        user_id=user_a_id
    )
    assert res_low["success"] is True
    assert res_low["total"] == 1
    assert res_low["reminders"][0]["project"] == "Infraestructura"
