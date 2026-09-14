import jwt
from uuid import UUID
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.config import settings

# HTTP Bearer security scheme
security = HTTPBearer(auto_error=False)

# Module-level JWKS client with in-memory public keys cache
jwks_url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json"
jwks_client = jwt.PyJWKClient(jwks_url, cache_keys=True)


def verify_token(token: str) -> dict:
    """
    Verifies Supabase JWT token using JWKS public keys (ES256/RS256).
    Validates signature, expiration, and extracts user payload.
    """
    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            options={"verify_aud": False}
        )

        if "sub" not in payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token no contiene identificador de usuario (sub)."
            )
        return payload
    except HTTPException:
        raise
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="El token ha expirado."
        )
    except (jwt.PyJWTError, Exception) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token inválido: {str(exc)}"
        )


async def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)) -> UUID:
    """
    FastAPI dependency to extract and validate Supabase JWT from Authorization header.
    Returns authenticated user's UUID.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Header de autorización 'Bearer <token>' no proporcionado o inválido."
        )

    payload = verify_token(credentials.credentials)
    try:
        user_uuid = UUID(payload["sub"])
        return user_uuid
    except (ValueError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identificador de usuario inválido en el token."
        )
