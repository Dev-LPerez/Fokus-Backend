import pytest
import respx
import httpx
from datetime import datetime, timezone, timedelta
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.core.config import settings
from app.core.encryption import decrypt_token
from app.models.user_integration import UserIntegration
from app.routers.integrations import create_oauth_state


@pytest.fixture(autouse=True)
def setup_encryption_key(monkeypatch):
    test_key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", test_key)
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "mock_client_id.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "mock_client_secret")
    monkeypatch.setattr(settings, "GOOGLE_REDIRECT_URI", "http://localhost:8000/integrations/google/callback")
    monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:3000")


@pytest.mark.asyncio
async def test_google_connect_unauthorized(client):
    response = await client.get("/integrations/google/connect")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_google_connect_success(client, user_a_headers):
    response = await client.get("/integrations/google/connect", headers=user_a_headers)
    assert response.status_code == 200
    data = response.json()
    assert "url" in data
    assert "accounts.google.com" in data["url"]
    assert "calendar.events" in data["url"]
    assert "state=" in data["url"]


@pytest.mark.asyncio
@respx.mock
async def test_google_callback_success(client, db_session, user_a_id):
    state = create_oauth_state(user_a_id)

    mock_token_response = {
        "access_token": "mock_google_access_token_abc123",
        "refresh_token": "mock_google_refresh_token_xyz987",
        "expires_in": 3600,
        "token_type": "Bearer"
    }

    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(200, json=mock_token_response)
    )

    response = await client.get(
        f"/integrations/google/callback?code=mock_auth_code&state={state}",
        follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers["location"] == "http://localhost:3000/settings?google=connected"

    # Verify integration stored in database
    stmt = select(UserIntegration).where(
        UserIntegration.user_id == user_a_id,
        UserIntegration.provider == "google_calendar"
    )
    result = await db_session.execute(stmt)
    integration = result.scalar_one_or_none()

    assert integration is not None
    assert decrypt_token(integration.access_token_encrypted) == "mock_google_access_token_abc123"
    assert decrypt_token(integration.refresh_token_encrypted) == "mock_google_refresh_token_xyz987"
    assert integration.token_expires_at is not None


@pytest.mark.asyncio
async def test_google_callback_invalid_state(client):
    response = await client.get(
        "/integrations/google/callback?code=mock_auth_code&state=invalid.jwt.token",
        follow_redirects=False
    )
    assert response.status_code == 302
    assert "detail=invalid_state" in response.headers["location"]


@pytest.mark.asyncio
async def test_google_callback_error_param(client):
    response = await client.get(
        "/integrations/google/callback?error=access_denied",
        follow_redirects=False
    )
    assert response.status_code == 302
    assert "detail=access_denied" in response.headers["location"]


@pytest.mark.asyncio
async def test_integrations_status_and_disconnect(client, db_session, user_a_id, user_a_headers):
    # Initially not connected
    status_resp = await client.get("/integrations/status", headers=user_a_headers)
    assert status_resp.status_code == 200
    assert status_resp.json()["google_calendar"]["connected"] is False

    # Insert integration
    integration = UserIntegration(
        user_id=user_a_id,
        provider="google_calendar",
        access_token_encrypted="enc_acc",
        refresh_token_encrypted="enc_ref",
        token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
    )
    db_session.add(integration)
    await db_session.commit()

    # Now status is connected
    status_resp = await client.get("/integrations/status", headers=user_a_headers)
    assert status_resp.status_code == 200
    assert status_resp.json()["google_calendar"]["connected"] is True

    # Disconnect
    del_resp = await client.delete("/integrations/google", headers=user_a_headers)
    assert del_resp.status_code == 200
    assert del_resp.json()["success"] is True

    # Status is disconnected again
    status_resp = await client.get("/integrations/status", headers=user_a_headers)
    assert status_resp.status_code == 200
    assert status_resp.json()["google_calendar"]["connected"] is False
