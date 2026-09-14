import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from cryptography.hazmat.primitives.asymmetric import ec
import jwt


@pytest.mark.asyncio
async def test_auth_valid_token(client, user_a_headers):
    response = await client.get("/conversations", headers=user_a_headers)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_auth_missing_header(client):
    response = await client.get("/conversations")
    assert response.status_code == 401
    assert "no proporcionado o inválido" in response.json()["detail"]


@pytest.mark.asyncio
async def test_auth_expired_token(client, ec_key_pair, mock_jwks):
    private_key, _ = ec_key_pair
    # Expired 1 hour ago
    payload = {
        "sub": str(uuid4()),
        "aud": "authenticated",
        "exp": (datetime.now(timezone.utc) - timedelta(hours=1)).timestamp(),
        "iat": (datetime.now(timezone.utc) - timedelta(hours=2)).timestamp()
    }
    token = jwt.encode(payload, private_key, algorithm="ES256", headers={"kid": "test-kid"})
    response = await client.get("/conversations", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert "ha expirado" in response.json()["detail"]


@pytest.mark.asyncio
async def test_auth_invalid_signature(client, ec_key_pair, mock_jwks):
    # Sign with a different unexpected private key
    other_key = ec.generate_private_key(ec.SECP256R1())
    payload = {
        "sub": str(uuid4()),
        "aud": "authenticated",
        "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
        "iat": datetime.now(timezone.utc).timestamp()
    }
    token = jwt.encode(payload, other_key, algorithm="ES256", headers={"kid": "test-kid"})
    response = await client.get("/conversations", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert "Token inválido" in response.json()["detail"]


@pytest.mark.asyncio
async def test_auth_unknown_kid(client, ec_key_pair, mock_jwks):
    private_key, _ = ec_key_pair
    payload = {
        "sub": str(uuid4()),
        "aud": "authenticated",
        "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
        "iat": datetime.now(timezone.utc).timestamp()
    }
    token = jwt.encode(payload, private_key, algorithm="ES256", headers={"kid": "unknown-kid"})
    response = await client.get("/conversations", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_rejects_algorithm_confusion_hs256(client, mock_jwks):
    """
    Security test: verifies that tokens signed with symmetric HS256 (e.g. using public key as secret)
    are strictly rejected to prevent algorithm confusion attacks.
    """
    payload = {
        "sub": str(uuid4()),
        "aud": "authenticated",
        "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
        "iat": datetime.now(timezone.utc).timestamp()
    }
    # Attacker tries signing with HS256 using a symmetric secret
    fake_secret = "attacker_secret_key_with_32_bytes_length!"
    fake_token = jwt.encode(payload, fake_secret, algorithm="HS256", headers={"kid": "test-kid"})
    response = await client.get("/conversations", headers={"Authorization": f"Bearer {fake_token}"})
    assert response.status_code == 401
    assert "Token inválido" in response.json()["detail"]



@pytest.mark.asyncio
async def test_public_endpoints_unprotected(client):
    """Health and Tools endpoints should remain public without auth."""
    res_health = await client.get("/health")
    assert res_health.status_code == 200

    res_tools = await client.get("/tools")
    assert res_tools.status_code == 200
