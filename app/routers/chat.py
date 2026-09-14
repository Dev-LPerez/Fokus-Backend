import json
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.auth import get_current_user
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.agent import agent_service

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.post("", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest,
    stream: bool = Query(True, description="Whether to stream response with Server-Sent Events"),
    current_user: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Sends a message to the AI agent (Protected by Supabase JWT Auth).
    If stream=True, returns SSE stream (text/event-stream).
    If stream=False, returns standard JSON ChatResponse.
    """
    if stream:
        async def event_generator():
            try:
                async for event in agent_service.process_message_stream(
                    message_text=request.message,
                    conversation_id=request.conversation_id,
                    db=db,
                    user_id=current_user
                ):
                    event_type = event.get("event", "message")
                    data_str = json.dumps(event.get("data", {}), ensure_ascii=False)
                    yield f"event: {event_type}\ndata: {data_str}\n\n"
            except HTTPException as e:
                err_data = json.dumps({"message": str(e.detail)}, ensure_ascii=False)
                yield f"event: error\ndata: {err_data}\n\n"
            except Exception as e:
                err_data = json.dumps({"message": str(e)}, ensure_ascii=False)
                yield f"event: error\ndata: {err_data}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )
    else:
        try:
            result = await agent_service.process_message(
                message_text=request.message,
                conversation_id=request.conversation_id,
                db=db,
                user_id=current_user
            )
            return ChatResponse(
                conversation_id=result["conversation_id"],
                response=result["response"],
                tool_calls=result["tool_calls"]
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error procesando mensaje: {str(e)}")
