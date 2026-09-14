import asyncio
import json
import logging
from typing import AsyncGenerator, Dict, Any, List, Optional
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.conversation import Conversation
from app.models.message import Message
from app.core.config import settings
from app.core.timezone import get_colombia_now
from app.services.gemini_client import gemini_client, gemini_retry
from app.services.tools.registry import registry
from google.genai import types

logger = logging.getLogger(__name__)


@gemini_retry
async def _send_message_with_retry(chat, current_input):
    return await chat.send_message(current_input)


@gemini_retry
async def _send_message_stream_with_retry(chat, current_input):
    return await chat.send_message_stream(current_input)


class AgentService:
    def __init__(self):
        self.registry = registry

    async def get_or_create_conversation(
        self,
        db: AsyncSession,
        conversation_id: Optional[UUID],
        first_message: str,
        user_id: UUID
    ) -> Conversation:
        if conversation_id:
            stmt = select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id
            )
            res = await db.execute(stmt)
            conv = res.scalar_one_or_none()
            if conv:
                return conv
            else:
                # If conversation_id was provided but not found for this user, raise 404
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Conversación con ID {conversation_id} no encontrada."
                )

        # Generate title from first 30 chars of the message
        title = first_message[:30] + ("..." if len(first_message) > 30 else "")
        new_conv = Conversation(
            id=uuid4(),
            user_id=user_id,
            title=title
        )
        db.add(new_conv)
        await db.commit()
        await db.refresh(new_conv)
        return new_conv

    async def get_history_contents(self, db: AsyncSession, conversation_id: UUID) -> List[types.Content]:
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )
        res = await db.execute(stmt)
        messages = res.scalars().all()

        history: List[types.Content] = []
        for msg in messages:
            if not msg.content or not msg.content.strip():
                continue
            if msg.role == "user":
                history.append(types.Content(role="user", parts=[types.Part.from_text(text=msg.content)]))
            elif msg.role == "assistant":
                history.append(types.Content(role="model", parts=[types.Part.from_text(text=msg.content)]))
        return history

    def _get_generate_config(self) -> types.GenerateContentConfig:
        now = get_colombia_now()
        dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        dia_semana = dias[now.weekday()]
        current_date_str = now.strftime("%Y-%m-%d %H:%M:%S")

        tool_decls = [
            types.FunctionDeclaration(
                name=tool.name,
                description=tool.description,
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        k: types.Schema(
                            type=v.get("type", "STRING").upper(),
                            description=v.get("description", "")
                        ) for k, v in tool.parameters.get("properties", {}).items()
                    },
                    required=tool.parameters.get("required", [])
                )
            ) for tool in self.registry.get_all()
        ]

        return types.GenerateContentConfig(
            tools=[types.Tool(function_declarations=tool_decls)],
            system_instruction=(
                f"Eres **Fokus**: el compañero inteligente de crecimiento personal y profesional del usuario.\n"
                f"Tu propósito es ayudar al usuario a alcanzar sus metas personales, académicas y profesionales, reduciendo la fricción mental, cuidando su bienestar y protegiendo su tiempo para lo que verdaderamente importa.\n\n"

                f"### CONTEXTO TEMPORAL DEL SISTEMA:\n"
                f"- Fecha y hora actual del sistema: {current_date_str} (Zona horaria oficial: America/Bogota, UTC-5).\n"
                f"- Día y fecha: {dia_semana}, {now.strftime('%d/%m/%Y')}.\n"
                f"- Año en curso: {now.year}.\n"
                f"- REGLA TEMPORAL ESTRICTA: Usa siempre este punto de referencia ({current_date_str}) para calcular fechas relativas ('hoy', 'mañana', 'el jueves', 'en 3 días', 'la próxima semana', 'a las 3:00 PM'). Nunca asumas años ni fechas del pasado.\n\n"

                f"### QUIÉN ERES Y CÓMO AYUDAS:\n"
                f"Fokus combina empatía, claridad y ejecución real (Function Calling) conectado a Google Calendar y un tablero relacional bajo la Matriz de Eisenhower. "
                f"No eres un chatbot pasivo ni burocrático: eres un facilitador proactivo, cercano, estructurado y enfocado en el progreso sostenible del usuario.\n\n"

                f"### LO QUE PUEDES HACER (CAPACIDADES AUTÓNOMAS):\n"
                f"1. AUDITORÍA DE AGENDA Y BALANCE DE TIEMPO:\n"
                f"   - Consultar la agenda real de Google Calendar para cualquier día usando `get_calendar_agenda`.\n"
                f"   - Detectar huecos y momentos de calma disponibles usando `find_free_work_slots`.\n"
                f"   - Reservar sesiones de concentración profunda [Deep Work] o bloques de estudio/hábito usando `schedule_deep_work`, el cual sincroniza automáticamente en Google Calendar y registra la meta prioritaria.\n"
                f"2. GESTIÓN DE METAS Y PRIORIDADES (MATRIZ DE EISENHOWER):\n"
                f"   - Crear metas, proyectos o tareas con `create_reminder`, clasificándolas con claridad en: `project` (área personal o profesional: ej. 'Salud', 'Carrera', 'Estudio', 'Proyectos'), `priority` ('high' para Urgente/Crítico, 'medium' para Importante/Crecimiento, 'low' para Hábitos/Rutina), fecha límite (`due_date`) y duración estimada (`estimated_minutes`).\n"
                f"   - Listar metas pendientes o filtrar por área/prioridad usando `list_reminders`.\n"
                f"   - Celebrar y marcar metas completadas con `complete_reminder` o descartarlas con `delete_reminder`.\n"
                f"3. INVESTIGACIÓN Y APRENDIZAJE:\n"
                f"   - Buscar en la web información, recursos educativos, guías o contexto actualizado con `search_web` y sintetizarlo de manera clara y motivadora.\n"
                f"4. BIENESTAR Y CLIMA:\n"
                f"   - Consultar el clima con `get_weather` para planificar actividades al aire libre, traslados o deporte. Si no conoces la ciudad por el contexto previo, pregúntale amablemente en qué ciudad se encuentra.\n\n"

                f"### LO QUE NO PUEDES HACER (LÍMITES Y LÍNEAS ROJAS):\n"
                f"1. NO PUEDES ENVIAR CORREOS DIRECTOS O MENSAJES EXTERNOS: No posees integración de envío de emails (Gmail SMTP), WhatsApp o Slack. Si el usuario te pide 'envíale un correo a X', aclara que no puedes enviar correos por él, pero ofrécete a redactar el borrador perfecto o programar un recordatorio para enviarlo.\n"
                f"2. NO PUEDES MODIFICAR EVENTOS DE TERCEROS SIN CONSENTIMIENTO: Solo operas dentro del calendario autorizado y el tablero del usuario.\n"
                f"3. NO PUEDES INVENTAR DISPONIBILIDAD: Jamás asumas que el usuario tiene tiempo libre sin antes invocar `get_calendar_agenda` o `find_free_work_slots`.\n"
                f"4. NO DEBES SER VERBORRÁGICO: Evita respuestas excesivamente largas o saludos redundantes. Ve directo al grano con formato ejecutivo (viñetas, negritas y datos concretos).\n"
                f"5. SI GOOGLE CALENDAR NO ESTÁ CONECTADO: No finjas sincronización. Explica con cortesía que la herramienta reporta que Google Calendar no está vinculado y que puede conectarlo en un clic desde 'Ajustes > Integraciones' para habilitar el agendamiento directo en vivo."
            )
        )

    async def _execute_chat_loop(
        self,
        client,
        model_name: str,
        config: types.GenerateContentConfig,
        history: List[types.Content],
        message_text: str,
        conv_id: UUID,
        db: AsyncSession,
        user_id: UUID
    ) -> tuple[str, List[Dict[str, Any]]]:
        chat = client.aio.chats.create(
            model=model_name,
            config=config,
            history=history
        )

        tool_calls_record: List[Dict[str, Any]] = []
        final_text = ""
        max_iterations = 5
        iteration = 0
        current_input: Any = message_text

        while iteration < max_iterations:
            iteration += 1
            response = await _send_message_with_retry(chat, current_input)

            if response.function_calls:
                func_responses = []
                for fc in response.function_calls:
                    func_name = fc.name
                    func_args = fc.args if fc.args else {}

                    # Execute tool asynchronously passing db session and user_id
                    tool = self.registry.get(func_name)
                    if tool:
                        try:
                            tool_result = await tool.execute(**func_args, db=db, user_id=user_id)
                        except Exception as e:
                            tool_result = {"error": f"Tool execution failed: {str(e)}"}
                    else:
                        tool_result = {"error": f"Tool '{func_name}' not found."}

                    tool_calls_record.append({
                        "tool_name": func_name,
                        "args": func_args,
                        "result": tool_result
                    })

                    # Save tool message to database
                    tool_db_msg = Message(
                        conversation_id=conv_id,
                        role="tool",
                        content=json.dumps(tool_result, ensure_ascii=False),
                        tool_name=func_name
                    )
                    db.add(tool_db_msg)
                    await db.commit()

                    func_responses.append(
                        types.Part.from_function_response(
                            name=func_name,
                            response={"result": tool_result}
                        )
                    )

                current_input = func_responses
                continue
            else:
                final_text = response.text or ""
                break

        return final_text, tool_calls_record

    async def process_message(
        self,
        message_text: str,
        conversation_id: Optional[UUID],
        db: AsyncSession,
        user_id: UUID
    ) -> Dict[str, Any]:
        """Non-blocking async processing of chat message with retry and fallback model."""
        conv = await self.get_or_create_conversation(db, conversation_id, message_text, user_id)
        history = await self.get_history_contents(db, conv.id)

        # Save user message to database
        user_msg = Message(
            conversation_id=conv.id,
            role="user",
            content=message_text
        )
        db.add(user_msg)
        await db.commit()

        client = gemini_client.get_client()
        config = self._get_generate_config()

        try:
            final_text, tool_calls_record = await self._execute_chat_loop(
                client=client,
                model_name=settings.GEMINI_MODEL,
                config=config,
                history=history,
                message_text=message_text,
                conv_id=conv.id,
                db=db,
                user_id=user_id
            )
        except Exception as primary_exc:
            if settings.GEMINI_FALLBACK_MODEL and settings.GEMINI_FALLBACK_MODEL != settings.GEMINI_MODEL:
                logger.warning(
                    f"Modelo principal '{settings.GEMINI_MODEL}' falló ({primary_exc}). "
                    f"Intentando con fallback '{settings.GEMINI_FALLBACK_MODEL}'..."
                )
                try:
                    final_text, tool_calls_record = await self._execute_chat_loop(
                        client=client,
                        model_name=settings.GEMINI_FALLBACK_MODEL,
                        config=config,
                        history=history,
                        message_text=message_text,
                        conv_id=conv.id,
                        db=db,
                        user_id=user_id
                    )
                except Exception as fallback_exc:
                    raise fallback_exc from primary_exc
            else:
                raise primary_exc

        # Save assistant message to database
        assistant_msg = Message(
            conversation_id=conv.id,
            role="assistant",
            content=final_text
        )
        db.add(assistant_msg)
        await db.commit()

        return {
            "conversation_id": conv.id,
            "response": final_text,
            "tool_calls": tool_calls_record
        }

    async def _stream_chat_loop(
        self,
        client,
        model_name: str,
        config: types.GenerateContentConfig,
        history: List[types.Content],
        message_text: str,
        conv_id: UUID,
        db: AsyncSession,
        user_id: UUID
    ) -> AsyncGenerator[Dict[str, Any], None]:
        chat = client.aio.chats.create(
            model=model_name,
            config=config,
            history=history
        )

        max_iterations = 5
        iteration = 0
        current_input: Any = message_text

        while iteration < max_iterations:
            iteration += 1
            response = await _send_message_with_retry(chat, current_input)

            if response.function_calls:
                func_responses = []
                for fc in response.function_calls:
                    func_name = fc.name
                    func_args = fc.args if fc.args else {}

                    # Emit tool_start event
                    yield {
                        "event": "tool_start",
                        "data": {
                            "tool_name": func_name,
                            "args": func_args
                        }
                    }

                    tool = self.registry.get(func_name)
                    if tool:
                        try:
                            tool_result = await tool.execute(**func_args, db=db, user_id=user_id)
                        except Exception as e:
                            tool_result = {"error": f"Tool execution failed: {str(e)}"}
                    else:
                        tool_result = {"error": f"Tool '{func_name}' no encontrada."}

                    # Emit tool_end event
                    yield {
                        "event": "tool_end",
                        "data": {
                            "tool_name": func_name,
                            "result": tool_result
                        }
                    }

                    # Save tool message to database
                    tool_db_msg = Message(
                        conversation_id=conv_id,
                        role="tool",
                        content=json.dumps(tool_result, ensure_ascii=False),
                        tool_name=func_name
                    )
                    db.add(tool_db_msg)
                    await db.commit()

                    func_responses.append(
                        types.Part.from_function_response(
                            name=func_name,
                            response={"result": tool_result}
                        )
                    )

                # Provide ALL function responses back to Gemini for next iteration
                current_input = func_responses
                continue
            else:
                # Final text turn: smoothly stream token by token to the user
                if response.text:
                    text = response.text
                    chunk_size = 4
                    for i in range(0, len(text), chunk_size):
                        yield {
                            "event": "token",
                            "data": {"text": text[i:i+chunk_size]}
                        }
                        await asyncio.sleep(0.01)
                break

    async def process_message_stream(
        self,
        message_text: str,
        conversation_id: Optional[UUID],
        db: AsyncSession,
        user_id: UUID
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Streaming processing (SSE) with tool execution events, retry, and fallback model."""
        conv = await self.get_or_create_conversation(db, conversation_id, message_text, user_id)
        history = await self.get_history_contents(db, conv.id)

        # Notify initial conversation info
        yield {
            "event": "conversation_info",
            "data": {
                "conversation_id": str(conv.id),
                "title": conv.title
            }
        }

        # Save user message
        user_msg = Message(
            conversation_id=conv.id,
            role="user",
            content=message_text
        )
        db.add(user_msg)
        await db.commit()

        client = gemini_client.get_client()
        config = self._get_generate_config()

        full_text_chunks: List[str] = []
        selected_model = settings.GEMINI_MODEL

        try:
            async for event in self._stream_chat_loop(
                client=client,
                model_name=selected_model,
                config=config,
                history=history,
                message_text=message_text,
                conv_id=conv.id,
                db=db,
                user_id=user_id
            ):
                if event.get("event") == "token":
                    full_text_chunks.append(event.get("data", {}).get("text", ""))
                yield event
        except Exception as primary_exc:
            if settings.GEMINI_FALLBACK_MODEL and settings.GEMINI_FALLBACK_MODEL != selected_model:
                logger.warning(
                    f"Streaming con modelo principal '{selected_model}' falló ({primary_exc}). "
                    f"Reintentando stream con fallback '{settings.GEMINI_FALLBACK_MODEL}'..."
                )
                try:
                    full_text_chunks.clear()
                    async for event in self._stream_chat_loop(
                        client=client,
                        model_name=settings.GEMINI_FALLBACK_MODEL,
                        config=config,
                        history=history,
                        message_text=message_text,
                        conv_id=conv.id,
                        db=db,
                        user_id=user_id
                    ):
                        if event.get("event") == "token":
                            full_text_chunks.append(event.get("data", {}).get("text", ""))
                        yield event
                except Exception as fallback_exc:
                    yield {
                        "event": "error",
                        "data": {"message": f"Error comunicando con Gemini (tras fallback): {str(fallback_exc)}"}
                    }
                    return
            else:
                yield {
                    "event": "error",
                    "data": {"message": f"Error comunicando con Gemini: {str(primary_exc)}"}
                }
                return

        full_response = "".join(full_text_chunks)

        # Save assistant message in DB
        assistant_msg = Message(
            conversation_id=conv.id,
            role="assistant",
            content=full_response
        )
        db.add(assistant_msg)
        await db.commit()

        # Emit completion event
        yield {
            "event": "done",
            "data": {
                "conversation_id": str(conv.id),
                "full_text": full_response
            }
        }


agent_service = AgentService()
