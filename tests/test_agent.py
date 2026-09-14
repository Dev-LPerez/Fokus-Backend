import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from fastapi import HTTPException
from google.genai.errors import APIError
from app.services.agent import agent_service, _send_message_with_retry
from app.core.config import settings
from app.models.conversation import Conversation
from app.models.reminder import Reminder
from sqlalchemy import select


@pytest.mark.asyncio
async def test_agent_process_message_mocked(mocker, db_session, user_a_id):
    mock_chat = AsyncMock()
    mock_response = MagicMock()
    mock_response.function_calls = None
    mock_response.text = "¡Hola! ¿En qué puedo ayudarte hoy?"
    mock_chat.send_message.return_value = mock_response

    mock_client = MagicMock()
    mock_client.aio.chats.create.return_value = mock_chat

    mocker.patch("app.services.agent.gemini_client.get_client", return_value=mock_client)

    result = await agent_service.process_message(
        message_text="Hola",
        conversation_id=None,
        db=db_session,
        user_id=user_a_id
    )

    assert result["response"] == "¡Hola! ¿En qué puedo ayudarte hoy?"
    assert result["tool_calls"] == []
    assert "conversation_id" in result

    # Verify conversation in DB has user_a_id
    stmt = select(Conversation).where(Conversation.id == result["conversation_id"])
    conv = (await db_session.execute(stmt)).scalar_one_or_none()
    assert conv is not None
    assert conv.user_id == user_a_id


@pytest.mark.asyncio
async def test_gemini_retry_on_rate_limit(mocker):
    """Tests that transient 429 rate limits trigger retry and succeed."""
    call_count = 0
    mock_chat = AsyncMock()
    
    async def mock_send_message(content):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise APIError(429, "Resource has been exhausted (rate limit)")
        mock_response = MagicMock()
        mock_response.function_calls = None
        mock_response.text = "Respuesta tras reintento exitoso"
        return mock_response

    mock_chat.send_message.side_effect = mock_send_message

    res = await _send_message_with_retry(mock_chat, "test prompt")
    assert res.text == "Respuesta tras reintento exitoso"
    assert call_count == 2


@pytest.mark.asyncio
async def test_gemini_no_retry_on_non_transient_error(mocker):
    """Tests that non-transient errors like ValueError do not trigger retries."""
    call_count = 0
    mock_chat = AsyncMock()

    async def mock_send_message(content):
        nonlocal call_count
        call_count += 1
        raise ValueError("Invalid parameter value")

    mock_chat.send_message.side_effect = mock_send_message

    with pytest.raises(ValueError, match="Invalid parameter value"):
        await _send_message_with_retry(mock_chat, "test prompt")
    
    assert call_count == 1


@pytest.mark.asyncio
async def test_fallback_model_activation(mocker, db_session, user_a_id):
    """Tests that if primary model fails, fallback model is invoked."""
    mock_client = MagicMock()
    
    primary_chat = AsyncMock()
    primary_chat.send_message.side_effect = Exception("Primary model unavailable")

    fallback_chat = AsyncMock()
    fallback_response = MagicMock()
    fallback_response.function_calls = None
    fallback_response.text = "Respuesta desde el modelo fallback"
    fallback_chat.send_message.return_value = fallback_response

    def mock_create_chat(model, config, history):
        if model == settings.GEMINI_MODEL:
            return primary_chat
        elif model == settings.GEMINI_FALLBACK_MODEL:
            return fallback_chat
        return primary_chat

    mock_client.aio.chats.create.side_effect = mock_create_chat
    mocker.patch("app.services.agent.gemini_client.get_client", return_value=mock_client)

    result = await agent_service.process_message(
        message_text="Pregunta compleja",
        conversation_id=None,
        db=db_session,
        user_id=user_a_id
    )

    assert result["response"] == "Respuesta desde el modelo fallback"


@pytest.mark.asyncio
async def test_chat_endpoint_json(client, mocker, user_a_headers):
    mocker.patch(
        "app.routers.chat.agent_service.process_message",
        return_value={
            "conversation_id": "83101238-d0bb-487d-a818-ca282bb8fec0",
            "response": "Respuesta simulada del asistente",
            "tool_calls": []
        }
    )

    response = await client.post(
        "/chat?stream=false",
        json={"message": "Hola"},
        headers=user_a_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["response"] == "Respuesta simulada del asistente"
    assert data["conversation_id"] == "83101238-d0bb-487d-a818-ca282bb8fec0"


@pytest.mark.asyncio
async def test_chat_tool_execution_with_user_id(mocker, db_session, user_a_id):
    """Phase A5 criterion: Confirms that reminders created via agent get the user's ID."""
    mock_chat = AsyncMock()

    # 1. First model response: requests create_reminder tool call
    mock_fc = MagicMock()
    mock_fc.name = "create_reminder"
    mock_fc.args = {
        "description": "Entregar taller de IA",
        "due_date": "2026-08-30 20:00"
    }

    mock_res_1 = MagicMock()
    mock_res_1.function_calls = [mock_fc]
    mock_res_1.text = None

    # 2. Second model response: confirms creation
    mock_res_2 = MagicMock()
    mock_res_2.function_calls = None
    mock_res_2.text = "He creado tu recordatorio para entregar el taller de IA."

    mock_chat.send_message.side_effect = [mock_res_1, mock_res_2]

    mock_client = MagicMock()
    mock_client.aio.chats.create.return_value = mock_chat
    mocker.patch("app.services.agent.gemini_client.get_client", return_value=mock_client)

    result = await agent_service.process_message(
        message_text="Recuérdame entregar el taller de IA",
        conversation_id=None,
        db=db_session,
        user_id=user_a_id
    )

    assert "taller de IA" in result["response"]
    assert len(result["tool_calls"]) == 1
    assert result["tool_calls"][0]["tool_name"] == "create_reminder"

    # Verify reminder saved in database has user_a_id
    stmt = select(Reminder).where(Reminder.description == "Entregar taller de IA")
    reminder = (await db_session.execute(stmt)).scalar_one_or_none()
    assert reminder is not None
    assert reminder.user_id == user_a_id


@pytest.mark.asyncio
async def test_user_cannot_resume_another_users_conversation(
    client,
    db_session,
    user_a_id,
    user_b_headers
):
    """Security test: User B receives 404 when trying to resume User A's conversation via /chat."""
    # 1. Create a conversation owned by User A
    conv_a_id = uuid4()
    conv_a = Conversation(id=conv_a_id, user_id=user_a_id, title="Conversación Privada de A")
    db_session.add(conv_a)
    await db_session.commit()

    # 2. User B tries to send a message resuming User A's conversation in non-streaming mode
    response_json = await client.post(
        "/chat?stream=false",
        json={"message": "Quiero acceder a este chat", "conversation_id": str(conv_a_id)},
        headers=user_b_headers
    )
    assert response_json.status_code == 404
    assert "no encontrada" in response_json.json()["detail"]

    # 3. User B tries to send a message resuming User A's conversation in streaming mode
    response_stream = await client.post(
        "/chat?stream=true",
        json={"message": "Quiero acceder por stream", "conversation_id": str(conv_a_id)},
        headers=user_b_headers
    )
    assert response_stream.status_code == 200
    stream_content = response_stream.text
    assert "event: error" in stream_content
    assert "no encontrada" in stream_content


@pytest.mark.asyncio
async def test_agent_invokes_get_calendar_agenda(mocker, db_session, user_a_id):
    """Verifies that asking for today's schedule triggers get_calendar_agenda."""
    mock_chat = AsyncMock()

    # 1. First model response calls get_calendar_agenda
    mock_fc = MagicMock()
    mock_fc.name = "get_calendar_agenda"
    mock_fc.args = {"date_str": "2026-09-04"}

    mock_res_1 = MagicMock()
    mock_res_1.function_calls = [mock_fc]
    mock_res_1.text = None

    # 2. Second model response summarizes agenda
    mock_res_2 = MagicMock()
    mock_res_2.function_calls = None
    mock_res_2.text = "Hoy tienes 2 reuniones programadas y 3 horas libres para trabajo enfocado."

    mock_chat.send_message.side_effect = [mock_res_1, mock_res_2]

    mock_client = MagicMock()
    mock_client.aio.chats.create.return_value = mock_chat
    mocker.patch("app.services.agent.gemini_client.get_client", return_value=mock_client)

    result = await agent_service.process_message(
        message_text="¿Cómo viene mi día hoy?",
        conversation_id=None,
        db=db_session,
        user_id=user_a_id
    )

    assert len(result["tool_calls"]) == 1
    assert result["tool_calls"][0]["tool_name"] == "get_calendar_agenda"
    assert "reuniones programadas" in result["response"]


@pytest.mark.asyncio
async def test_agent_invokes_schedule_deep_work(mocker, db_session, user_a_id):
    """Verifies that asking to block focus time triggers schedule_deep_work."""
    mock_chat = AsyncMock()

    # 1. First model response calls schedule_deep_work
    mock_fc = MagicMock()
    mock_fc.name = "schedule_deep_work"
    mock_fc.args = {
        "task_description": "Informe del cliente",
        "duration_minutes": 120,
        "project": "Cliente Acme"
    }

    mock_res_1 = MagicMock()
    mock_res_1.function_calls = [mock_fc]
    mock_res_1.text = None

    # 2. Second model response confirms deep work
    mock_res_2 = MagicMock()
    mock_res_2.function_calls = None
    mock_res_2.text = "He bloqueado 2 horas de Deep Work en tu calendario para el Informe del cliente."

    mock_chat.send_message.side_effect = [mock_res_1, mock_res_2]

    mock_client = MagicMock()
    mock_client.aio.chats.create.return_value = mock_chat
    mocker.patch("app.services.agent.gemini_client.get_client", return_value=mock_client)

    result = await agent_service.process_message(
        message_text="Bloquea 2 horas para trabajar en el informe del cliente",
        conversation_id=None,
        db=db_session,
        user_id=user_a_id
    )

    assert len(result["tool_calls"]) == 1
    assert result["tool_calls"][0]["tool_name"] == "schedule_deep_work"
    assert "Deep Work" in result["response"]

