import pytest
from datetime import datetime, timezone, timedelta
from app.models.reminder import Reminder
from app.models.user_integration import UserIntegration
from app.core.timezone import get_colombia_now


@pytest.mark.asyncio
async def test_get_calendar_events_unauthorized(client):
    resp = await client.get("/calendar/events")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_calendar_events_empty(client, user_a_headers):
    resp = await client.get("/calendar/events", headers=user_a_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "events" in data
    assert "calendar_connected" in data
    assert data["calendar_connected"] is False
    assert isinstance(data["events"], list)


@pytest.mark.asyncio
async def test_get_calendar_events_with_tasks(client, user_a_headers, user_a_id, db_session):
    now = get_colombia_now()
    r = Reminder(
        user_id=user_a_id,
        description="Revisión de estrategia trimestral",
        project="Estrategia",
        priority="high",
        due_date=now + timedelta(days=2),
        estimated_minutes=90,
        completed=False
    )
    db_session.add(r)
    await db_session.commit()

    start_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    end_str = (now + timedelta(days=5)).strftime("%Y-%m-%d")

    resp = await client.get(f"/calendar/events?start={start_str}&end={end_str}", headers=user_a_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["tasks_count"] >= 1
    assert any(ev["title"] == "Revisión de estrategia trimestral" for ev in data["events"])


@pytest.mark.asyncio
async def test_create_calendar_event(client, user_a_headers):
    now = get_colombia_now() + timedelta(days=1)
    payload = {
        "title": "Sesión de Deep Work - Arquitectura",
        "start_time": now.isoformat(),
        "duration_minutes": 120,
        "description": "Diseño de modelos y contratos de API",
        "project": "Arquitectura",
        "priority": "high",
        "sync_to_google": False
    }

    resp = await client.post("/calendar/events", json=payload, headers=user_a_headers)
    assert resp.status_code == 201
    ev = resp.json()
    assert ev["title"] == "Sesión de Deep Work - Arquitectura"
    assert ev["estimated_minutes"] == 120
    assert ev["source"] == "deep_work"


@pytest.mark.asyncio
async def test_delete_calendar_event(client, user_a_headers, user_a_id, db_session):
    now = get_colombia_now()
    r = Reminder(
        user_id=user_a_id,
        description="Evento para eliminar",
        priority="low",
        due_date=now + timedelta(hours=3),
        completed=False
    )
    db_session.add(r)
    await db_session.commit()
    await db_session.refresh(r)

    resp = await client.delete(f"/calendar/events/{r.id}", headers=user_a_headers)
    assert resp.status_code == 200
    assert resp.json()["success"] is True
