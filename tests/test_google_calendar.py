import pytest
import respx
import httpx
from datetime import datetime, timezone, timedelta
from cryptography.fernet import Fernet

from app.core.config import settings
from app.core.encryption import encrypt_token, decrypt_token
from app.models.user_integration import UserIntegration
from app.services.google_calendar import (
    google_calendar_service,
    GoogleCalendarNotConnected,
    GoogleCalendarError
)


@pytest.fixture(autouse=True)
def setup_calendar_test_env(monkeypatch):
    test_key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", test_key)
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "mock_client_id")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "mock_client_secret")


@pytest.mark.asyncio
async def test_google_calendar_not_connected_raises(db_session, user_a_id):
    with pytest.raises(GoogleCalendarNotConnected):
        await google_calendar_service.create_event(
            user_id=user_a_id,
            title="Tarea de prueba",
            description="Descripción",
            due_date=datetime.now(timezone.utc) + timedelta(days=1),
            db=db_session
        )


@pytest.mark.asyncio
@respx.mock
async def test_google_calendar_create_and_delete_event(db_session, user_a_id):
    # Setup active integration
    integration = UserIntegration(
        user_id=user_a_id,
        provider="google_calendar",
        access_token_encrypted=encrypt_token("valid_access_token_123"),
        refresh_token_encrypted=encrypt_token("valid_refresh_token_456"),
        token_expires_at=datetime.now(timezone.utc) + timedelta(hours=2)
    )
    db_session.add(integration)
    await db_session.commit()

    # Mock Google Calendar create event API
    respx.post("https://www.googleapis.com/calendar/v3/calendars/primary/events").mock(
        return_value=httpx.Response(201, json={"id": "mock_google_event_777", "summary": "Reunión"})
    )

    due = datetime.now(timezone.utc) + timedelta(days=1)
    event_id = await google_calendar_service.create_event(
        user_id=user_a_id,
        title="Reunión",
        description="Reunión con el equipo",
        due_date=due,
        db=db_session
    )

    assert event_id == "mock_google_event_777"

    # Mock Google Calendar delete event API
    respx.delete("https://www.googleapis.com/calendar/v3/calendars/primary/events/mock_google_event_777").mock(
        return_value=httpx.Response(204)
    )

    deleted = await google_calendar_service.delete_event(
        user_id=user_a_id,
        event_id="mock_google_event_777",
        db=db_session
    )
    assert deleted is True


@pytest.mark.asyncio
@respx.mock
async def test_google_calendar_token_auto_refresh(db_session, user_a_id):
    # Setup expired integration
    integration = UserIntegration(
        user_id=user_a_id,
        provider="google_calendar",
        access_token_encrypted=encrypt_token("expired_access_token"),
        refresh_token_encrypted=encrypt_token("valid_refresh_token_abc"),
        token_expires_at=datetime.now(timezone.utc) - timedelta(minutes=10)
    )
    db_session.add(integration)
    await db_session.commit()

    # Mock token refresh endpoint
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(200, json={
            "access_token": "refreshed_access_token_new",
            "expires_in": 3600
        })
    )

    # Mock create event API
    respx.post("https://www.googleapis.com/calendar/v3/calendars/primary/events").mock(
        return_value=httpx.Response(201, json={"id": "new_event_123"})
    )

    event_id = await google_calendar_service.create_event(
        user_id=user_a_id,
        title="Nueva tarea tras refresh",
        description="Descripción",
        due_date=datetime.now(timezone.utc) + timedelta(hours=5),
        db=db_session
    )

    assert event_id == "new_event_123"

    # Verify db updated with new access token
    await db_session.refresh(integration)
    assert decrypt_token(integration.access_token_encrypted) == "refreshed_access_token_new"


@pytest.mark.asyncio
async def test_google_calendar_list_and_slots_not_connected(db_session, user_a_id):
    with pytest.raises(GoogleCalendarNotConnected):
        await google_calendar_service.list_events(
            user_id=user_a_id,
            time_min=datetime(2026, 5, 10, 8, 0),
            time_max=datetime(2026, 5, 10, 19, 0),
            db=db_session
        )

    with pytest.raises(GoogleCalendarNotConnected):
        await google_calendar_service.find_free_slots(
            user_id=user_a_id,
            target_date="2026-05-10",
            min_duration_minutes=60,
            db=db_session
        )


@pytest.mark.asyncio
@respx.mock
async def test_google_calendar_list_events_success(db_session, user_a_id):
    integration = UserIntegration(
        user_id=user_a_id,
        provider="google_calendar",
        access_token_encrypted=encrypt_token("valid_token_xyz"),
        refresh_token_encrypted=encrypt_token("refresh_xyz"),
        token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
    )
    db_session.add(integration)
    await db_session.commit()

    mock_items = [
        {
            "id": "event_1",
            "summary": "Sprint Planning",
            "description": "Revisión quincenal",
            "start": {"dateTime": "2026-05-10T09:00:00-05:00"},
            "end": {"dateTime": "2026-05-10T10:00:00-05:00"},
            "status": "confirmed"
        },
        {
            "id": "event_cancelled",
            "summary": "Cancelada",
            "start": {"dateTime": "2026-05-10T11:00:00-05:00"},
            "end": {"dateTime": "2026-05-10T12:00:00-05:00"},
            "status": "cancelled"
        },
        {
            "id": "event_allday",
            "summary": "Feriado",
            "start": {"date": "2026-05-10"},
            "end": {"date": "2026-05-10"},
            "status": "confirmed"
        }
    ]

    respx.get("https://www.googleapis.com/calendar/v3/calendars/primary/events").mock(
        return_value=httpx.Response(200, json={"items": mock_items})
    )

    events = await google_calendar_service.list_events(
        user_id=user_a_id,
        time_min=datetime(2026, 5, 10, 0, 0),
        time_max=datetime(2026, 5, 10, 23, 59),
        db=db_session
    )

    assert len(events) == 2
    assert events[0]["id"] == "event_1"
    assert events[0]["summary"] == "Sprint Planning"
    assert events[1]["id"] == "event_allday"


@pytest.mark.asyncio
@respx.mock
async def test_google_calendar_find_free_slots_math(db_session, user_a_id):
    integration = UserIntegration(
        user_id=user_a_id,
        provider="google_calendar",
        access_token_encrypted=encrypt_token("valid_token_xyz"),
        refresh_token_encrypted=encrypt_token("refresh_xyz"),
        token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
    )
    db_session.add(integration)
    await db_session.commit()

    # Events in day:
    # 09:00 - 10:30 (A)
    # 10:00 - 11:30 (B, overlapping -> 09:00 to 11:30)
    # 14:00 - 15:00 (C)
    mock_items = [
        {
            "id": "ev_a",
            "summary": "Reunión A",
            "start": {"dateTime": "2026-05-10T09:00:00-05:00"},
            "end": {"dateTime": "2026-05-10T10:30:00-05:00"}
        },
        {
            "id": "ev_b",
            "summary": "Reunión B",
            "start": {"dateTime": "2026-05-10T10:00:00-05:00"},
            "end": {"dateTime": "2026-05-10T11:30:00-05:00"}
        },
        {
            "id": "ev_c",
            "summary": "Reunión C",
            "start": {"dateTime": "2026-05-10T14:00:00-05:00"},
            "end": {"dateTime": "2026-05-10T15:00:00-05:00"}
        }
    ]

    respx.get("https://www.googleapis.com/calendar/v3/calendars/primary/events").mock(
        return_value=httpx.Response(200, json={"items": mock_items})
    )

    # Test with min 60 mins -> should return:
    # 08:00 - 09:00 (60 min)
    # 11:30 - 14:00 (150 min)
    # 15:00 - 19:00 (240 min)
    slots_60 = await google_calendar_service.find_free_slots(
        user_id=user_a_id,
        target_date="2026-05-10",
        min_duration_minutes=60,
        db=db_session,
        workday_start_hour=8,
        workday_end_hour=19
    )
    assert len(slots_60) == 3
    assert slots_60[0] == {"start": "2026-05-10 08:00", "end": "2026-05-10 09:00", "duration_minutes": 60}
    assert slots_60[1] == {"start": "2026-05-10 11:30", "end": "2026-05-10 14:00", "duration_minutes": 150}
    assert slots_60[2] == {"start": "2026-05-10 15:00", "end": "2026-05-10 19:00", "duration_minutes": 240}

    # Test with min 90 mins -> 08:00-09:00 (60 min) should be filtered out
    slots_90 = await google_calendar_service.find_free_slots(
        user_id=user_a_id,
        target_date="2026-05-10",
        min_duration_minutes=90,
        db=db_session,
        workday_start_hour=8,
        workday_end_hour=19
    )
    assert len(slots_90) == 2
    assert slots_90[0]["duration_minutes"] == 150
    assert slots_90[1]["duration_minutes"] == 240

