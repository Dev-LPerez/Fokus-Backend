from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from typing import List
from uuid import UUID

from app.db.session import get_db
from app.core.auth import get_current_user
from app.models.conversation import Conversation
from app.models.message import Message
from app.schemas.conversation import ConversationResponse, ConversationDetailResponse

router = APIRouter(prefix="/conversations", tags=["Conversations"])


@router.get("", response_model=List[ConversationResponse])
async def list_conversations(
    limit: int = 50,
    offset: int = 0,
    current_user: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Lists all conversations for the authenticated user ordered by creation date descending."""
    stmt = (
        select(Conversation)
        .where(Conversation.user_id == current_user)
        .order_by(desc(Conversation.created_at))
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    conversations = result.scalars().all()
    return conversations


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: UUID,
    current_user: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Gets conversation detail along with its messages, scoped to the authenticated user."""
    stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.user_id == current_user
    )
    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversación con ID {conversation_id} no encontrada."
        )

    # Fetch messages
    msg_stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    msg_result = await db.execute(msg_stmt)
    messages = msg_result.scalars().all()

    return ConversationDetailResponse(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        messages=messages
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: UUID,
    current_user: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Deletes a conversation and its messages via cascade, scoped to authenticated user."""
    stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.user_id == current_user
    )
    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversación con ID {conversation_id} no encontrada."
        )

    await db.delete(conversation)
    await db.commit()
    return None
