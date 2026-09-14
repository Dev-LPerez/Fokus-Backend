import pytest
from app.models.reminder import Reminder
from app.models.conversation import Conversation
from app.models.user_integration import UserIntegration
from app.models.user_onboarding import UserOnboarding


@pytest.mark.asyncio
async def test_onboarding_status_unauthorized(client):
    response = await client.get("/onboarding/status")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_onboarding_status_fresh_user(client, user_a_headers):
    response = await client.get("/onboarding/status", headers=user_a_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["has_seen_onboarding"] is False
    assert data["has_calendar_connected"] is False
    assert data["has_created_task"] is False
    assert data["has_started_chat"] is False
    assert data["tasks_count"] == 0
    assert len(data["suggested_starter_prompts"]) > 0


@pytest.mark.asyncio
async def test_onboarding_status_old_user_with_activity_still_gets_onboarding(client, user_a_headers, user_a_id, db_session):
    """
    CRÍTICO: Usuarios antiguos con tareas, calendarios o conversaciones previas
    DEBEN recibir el onboarding si nunca han completado explícitamente este flujo nuevo.
    """
    # 1. Simulate an existing "old" user with previous tasks
    r = Reminder(
        user_id=user_a_id,
        description="Tarea creada antes de la función de onboarding",
        priority="high",
        project="Antiguo",
        completed=False
    )
    db_session.add(r)
    await db_session.commit()

    # 2. Check status: despite having created tasks, has_seen_onboarding MUST be False!
    response = await client.get("/onboarding/status", headers=user_a_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["has_seen_onboarding"] is False
    assert data["has_created_task"] is True
    assert data["tasks_count"] == 1


@pytest.mark.asyncio
async def test_complete_onboarding(client, user_a_headers):
    """
    Verifica que al invocar POST /onboarding/complete, el estado de onboarding
    pasa a ser has_seen_onboarding = True de forma persistente.
    """
    # Complete onboarding
    resp = await client.post("/onboarding/complete", headers=user_a_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True

    # Now verify GET status reflects completion
    status_resp = await client.get("/onboarding/status", headers=user_a_headers)
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["has_seen_onboarding"] is True


@pytest.mark.asyncio
async def test_seed_starter_tasks(client, user_a_headers):
    payload = {"project_name": "Proyecto Demo"}
    response = await client.post("/onboarding/seed-tasks", json=payload, headers=user_a_headers)
    assert response.status_code == 201
    tasks = response.json()
    assert len(tasks) == 4
    assert all(t["project"] == "Proyecto Demo" for t in tasks)
