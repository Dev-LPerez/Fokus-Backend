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
from app.services.tools.reminders import (
    ReminderTool,
    ListRemindersTool,
    CompleteReminderTool,
    DeleteReminderTool
)


@pytest.fixture(autouse=True)
def setup_reminder_env(monkeypatch):
    test_key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", test_key)
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "mock_client_id")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "mock_client_secret")


@pytest.mark.asyncio
async def test_create_reminder_without_calendar(db_session, user_a_id):
    tool = ReminderTool()
    result = await tool.execute(
        description="Estudiar para el parcial",
        due_date="2026-08-30 14:00",
        db=db_session,
        user_id=user_a_id
    )
    assert result["success"] is True
    assert result["description"] == "Estudiar para el parcial"
    assert result["calendar_synced"] is False
    assert "Conecta tu Google Calendar" in result.get("note", "")
    assert result["completed"] is False
    assert result["google_event_id"] is None


@pytest.mark.asyncio
@respx.mock
async def test_create_reminder_with_calendar_connected(db_session, user_a_id):
    # Connect calendar for user_a
    integration = UserIntegration(
        user_id=user_a_id,
        provider="google_calendar",
        access_token_encrypted=encrypt_token("valid_access_token_123"),
        refresh_token_encrypted=encrypt_token("valid_refresh_token_456"),
        token_expires_at=datetime.now(timezone.utc) + timedelta(hours=2)
    )
    db_session.add(integration)
    await db_session.commit()

    # Mock Google Calendar API
    respx.post("https://www.googleapis.com/calendar/v3/calendars/primary/events").mock(
        return_value=httpx.Response(201, json={"id": "cal_evt_100"})
    )

    tool = ReminderTool()
    result = await tool.execute(
        description="Presentación final de proyecto",
        due_date="2026-09-01 09:00",
        db=db_session,
        user_id=user_a_id
    )

    assert result["success"] is True
    assert result["calendar_synced"] is True
    assert result["google_event_id"] == "cal_evt_100"


@pytest.mark.asyncio
async def test_list_reminders_tool(db_session, user_a_id, user_b_id):
    # Create reminders for user_a
    r1 = Reminder(user_id=user_a_id, description="Tarea pendiente 1", completed=False)
    r2 = Reminder(user_id=user_a_id, description="Tarea completada 2", completed=True)
    # Create reminder for user_b
    r3 = Reminder(user_id=user_b_id, description="Tarea usuario B", completed=False)

    db_session.add_all([r1, r2, r3])
    await db_session.commit()

    list_tool = ListRemindersTool()

    # List pending only (default)
    res_pending = await list_tool.execute(include_completed=False, db=db_session, user_id=user_a_id)
    assert res_pending["success"] is True
    assert res_pending["total"] == 1
    assert res_pending["reminders"][0]["description"] == "Tarea pendiente 1"

    # List all including completed
    res_all = await list_tool.execute(include_completed=True, db=db_session, user_id=user_a_id)
    assert res_all["success"] is True
    assert res_all["total"] == 2


@pytest.mark.asyncio
async def test_complete_reminder_tool(db_session, user_a_id, user_b_id):
    r = Reminder(user_id=user_a_id, description="Hacer la compra", completed=False)
    db_session.add(r)
    await db_session.commit()
    await db_session.refresh(r)

    complete_tool = CompleteReminderTool()

    # User B cannot complete User A's reminder
    forbidden_res = await complete_tool.execute(
        reminder_id=str(r.id),
        db=db_session,
        user_id=user_b_id
    )
    assert forbidden_res["success"] is False
    assert "no pertenece" in forbidden_res["error"]

    # User A completes own reminder
    success_res = await complete_tool.execute(
        reminder_id=str(r.id),
        db=db_session,
        user_id=user_a_id
    )
    assert success_res["success"] is True
    assert success_res["completed"] is True

    await db_session.refresh(r)
    assert r.completed is True


@pytest.mark.asyncio
@respx.mock
async def test_delete_reminder_tool_with_calendar_event(db_session, user_a_id, user_b_id):
    # Setup integration for user_a
    integration = UserIntegration(
        user_id=user_a_id,
        provider="google_calendar",
        access_token_encrypted=encrypt_token("valid_access_token_123"),
        refresh_token_encrypted=encrypt_token("valid_refresh_token_456"),
        token_expires_at=datetime.now(timezone.utc) + timedelta(hours=2)
    )
    r = Reminder(
        user_id=user_a_id,
        description="Reunión a borrar",
        google_event_id="cal_event_to_delete"
    )
    db_session.add_all([integration, r])
    await db_session.commit()
    await db_session.refresh(r)

    # Mock delete calendar event API
    respx.delete("https://www.googleapis.com/calendar/v3/calendars/primary/events/cal_event_to_delete").mock(
        return_value=httpx.Response(204)
    )

    delete_tool = DeleteReminderTool()

    # User B cannot delete User A's reminder
    forbidden_res = await delete_tool.execute(
        reminder_id=str(r.id),
        db=db_session,
        user_id=user_b_id
    )
    assert forbidden_res["success"] is False

    # User A deletes own reminder
    success_res = await delete_tool.execute(
        reminder_id=str(r.id),
        db=db_session,
        user_id=user_a_id
    )
    assert success_res["success"] is True
    assert success_res["calendar_deleted"] is True

    # Confirm removed from db
    stmt = select(Reminder).where(Reminder.id == r.id)
    rem_check = (await db_session.execute(stmt)).scalar_one_or_none()
    assert rem_check is None
