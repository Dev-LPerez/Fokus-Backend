import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4, UUID
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool
from cryptography.hazmat.primitives.asymmetric import ec
import jwt

from app.db.session import Base, get_db
from app.core.auth import jwks_client
from app.main import app

# In-memory async SQLite engine for testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def ec_key_pair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()
    return private_key, public_key


@pytest.fixture(scope="session")
def user_a_id():
    return uuid4()


@pytest.fixture(scope="session")
def user_b_id():
    return uuid4()


@pytest.fixture(scope="function")
def mock_jwks(ec_key_pair, mocker):
    private_key, public_key = ec_key_pair
    mock_key = mocker.MagicMock()
    mock_key.key = public_key

    def get_signing_key_side_effect(token):
        unverified_headers = jwt.get_unverified_header(token)
        if unverified_headers.get("kid") == "unknown-kid":
            raise jwt.PyJWKClientError("Unable to find a signing key that matches the 'kid'")
        return mock_key

    mocker.patch.object(
        jwks_client,
        "get_signing_key_from_jwt",
        side_effect=get_signing_key_side_effect
    )
    return private_key, public_key


@pytest.fixture(scope="function")
def user_a_headers(user_a_id, ec_key_pair, mock_jwks):
    private_key, _ = ec_key_pair
    payload = {
        "sub": str(user_a_id),
        "aud": "authenticated",
        "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
        "iat": datetime.now(timezone.utc).timestamp()
    }
    token = jwt.encode(payload, private_key, algorithm="ES256", headers={"kid": "test-kid"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="function")
def user_b_headers(user_b_id, ec_key_pair, mock_jwks):
    private_key, _ = ec_key_pair
    payload = {
        "sub": str(user_b_id),
        "aud": "authenticated",
        "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
        "iat": datetime.now(timezone.utc).timestamp()
    }
    token = jwt.encode(payload, private_key, algorithm="ES256", headers={"kid": "test-kid"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="function")
async def db_session():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestingSessionLocal() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(scope="function")
async def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
