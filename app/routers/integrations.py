import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID
import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.encryption import encrypt_token
from app.db.session import get_db
from app.models.user_integration import UserIntegration

router = APIRouter(prefix="/integrations", tags=["integrations"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"


def create_oauth_state(user_id: UUID) -> str:
    secret = settings.TOKEN_ENCRYPTION_KEY or "default_secret_key_for_dev_state"
    payload = {
        "user_id": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
        "purpose": "google_calendar_oauth"
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def verify_oauth_state(state: str) -> UUID:
    secret = settings.TOKEN_ENCRYPTION_KEY or "default_secret_key_for_dev_state"
    try:
        payload = jwt.decode(state, secret, algorithms=["HS256"])
        if payload.get("purpose") != "google_calendar_oauth":
            raise ValueError("Propósito de token state inválido.")
        return UUID(payload["user_id"])
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Parámetro state inválido o expirado: {str(exc)}"
        )


@router.get("/google/connect")
async def connect_google_calendar(
    user_id: UUID = Depends(get_current_user)
):
    """
    Genera la URL de consentimiento OAuth 2.0 de Google con el scope de Calendar Events.
    Devuelve la URL para que el frontend redirija al usuario.
    """
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GOOGLE_CLIENT_ID no está configurado en las variables de entorno."
        )

    state = create_oauth_state(user_id)
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": CALENDAR_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state
    }
    auth_url = f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"
    return {"url": auth_url}


@router.get("/google/callback")
async def google_calendar_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Endpoint de redirección tras autorización en Google.
    Intercambia el código de autorización por tokens, los almacena cifrados y redirige al frontend.
    """
    frontend_base = settings.FRONTEND_URL.rstrip("/")

    if error:
        return RedirectResponse(
            url=f"{frontend_base}/settings?google=error&detail={urllib.parse.quote(error)}",
            status_code=status.HTTP_302_FOUND
        )

    if not code or not state:
        return RedirectResponse(
            url=f"{frontend_base}/settings?google=error&detail=missing_code_or_state",
            status_code=status.HTTP_302_FOUND
        )

    try:
        user_id = verify_oauth_state(state)
    except HTTPException:
        return RedirectResponse(
            url=f"{frontend_base}/settings?google=error&detail=invalid_state",
            status_code=status.HTTP_302_FOUND
        )

    # Exchange code for tokens with Google
    async with httpx.AsyncClient(timeout=15.0) as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            }
        )

    if token_resp.status_code != 200:
        detail_msg = urllib.parse.quote(f"token_exchange_failed_{token_resp.status_code}")
        return RedirectResponse(
            url=f"{frontend_base}/settings?google=error&detail={detail_msg}",
            status_code=status.HTTP_302_FOUND
        )

    tokens = token_resp.json()
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token", "")
    expires_in = tokens.get("expires_in", 3600)

    if not access_token:
        return RedirectResponse(
            url=f"{frontend_base}/settings?google=error&detail=missing_access_token",
            status_code=status.HTTP_302_FOUND
        )

    now_utc = datetime.now(timezone.utc)
    token_expires_at = now_utc + timedelta(seconds=expires_in)

    # Upsert user_integrations record
    stmt = select(UserIntegration).where(
        UserIntegration.user_id == user_id,
        UserIntegration.provider == "google_calendar"
    )
    result = await db.execute(stmt)
    integration = result.scalar_one_or_none()

    if integration:
        integration.access_token_encrypted = encrypt_token(access_token)
        if refresh_token:
            integration.refresh_token_encrypted = encrypt_token(refresh_token)
        integration.token_expires_at = token_expires_at
    else:
        integration = UserIntegration(
            user_id=user_id,
            provider="google_calendar",
            access_token_encrypted=encrypt_token(access_token),
            refresh_token_encrypted=encrypt_token(refresh_token),
            token_expires_at=token_expires_at
        )
        db.add(integration)

    await db.commit()

    return RedirectResponse(
        url=f"{frontend_base}/settings?google=connected",
        status_code=status.HTTP_302_FOUND
    )


@router.delete("/google")
async def disconnect_google_calendar(
    user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Desconecta la cuenta de Google Calendar del usuario eliminando sus tokens cifrados.
    """
    stmt = delete(UserIntegration).where(
        UserIntegration.user_id == user_id,
        UserIntegration.provider == "google_calendar"
    )
    result = await db.execute(stmt)
    await db.commit()

    if result.rowcount == 0:
        return {
            "success": True,
            "message": "Google Calendar ya estaba desconectado."
        }

    return {
        "success": True,
        "message": "Google Calendar desconectado exitosamente."
    }


@router.get("/status")
async def get_integrations_status(
    user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Consulta el estado de conexión de las integraciones externas del usuario.
    """
    stmt = select(UserIntegration).where(
        UserIntegration.user_id == user_id,
        UserIntegration.provider == "google_calendar"
    )
    result = await db.execute(stmt)
    integration = result.scalar_one_or_none()

    is_connected = integration is not None
    expires_at = integration.token_expires_at.isoformat() if (integration and integration.token_expires_at) else None

    return {
        "google_calendar": {
            "connected": is_connected,
            "token_expires_at": expires_at
        }
    }
