import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from labpass.app import create_app
from labpass.auth import hash_password, token_hash
from labpass.config import Settings
from labpass.models import AuthSession, Base, User, Workshop

ROOT = Path(__file__).resolve().parents[1]
TEST_ORIGIN = "http://127.0.0.1:8000"
TEST_PASSWORD = "test-password-with-entropy"


def migrate(connection, operation="upgrade", target="head"):
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection"] = connection
    getattr(command, operation)(config, target)


@pytest.fixture(scope="session")
def engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail("TEST_DATABASE_URL is required: tests must run against real PostgreSQL")
    if not url.startswith("postgresql+psycopg://"):
        pytest.fail("Tests require PostgreSQL with psycopg")
    schema = "labpass_test_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    test_engine = create_engine(
        url,
        pool_size=105,
        max_overflow=0,
        pool_timeout=20,
        isolation_level="READ COMMITTED",
        connect_args={
            "connect_timeout": 5,
            "application_name": schema,
            "options": f"-csearch_path={schema} -clock_timeout=20000 -cstatement_timeout=30000",
        },
    )
    try:
        with test_engine.begin() as connection:
            migrate(connection)
        yield test_engine
    finally:
        test_engine.dispose()
        # Only remove the randomly named schema created by this fixture.
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def sessions(engine):
    with engine.begin() as connection:
        tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
        connection.execute(text(f"TRUNCATE {tables} CASCADE"))
    return sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def data(sessions, encoded_password):
    with sessions.begin() as session:
        admin = User(
            id=uuid4(), email="admin@example.test", is_admin=True, password_hash=encoded_password
        )
        users = [
            User(id=uuid4(), email=f"user-{i}@example.test", password_hash=encoded_password)
            for i in range(100)
        ]
        workshop = Workshop(id=uuid4(), title="Cloud workshop", capacity=20)
        other = Workshop(id=uuid4(), title="Other workshop", capacity=10)
        session.add_all([admin, *users, workshop, other])
        session.flush()
        tokens = {user.id: secrets.token_urlsafe(32) for user in [admin, *users]}
        now = datetime.now(UTC)
        session.add_all(
            [
                AuthSession(
                    token_hash=token_hash(token),
                    user_id=user_id,
                    created_at=now,
                    expires_at=now + timedelta(hours=1),
                )
                for user_id, token in tokens.items()
            ]
        )
    return {
        "admin": admin.id,
        "users": [u.id for u in users],
        "workshop": workshop.id,
        "other": other.id,
        "tokens": tokens,
    }


@pytest.fixture
def client(engine, sessions):
    with TestClient(
        create_app(Settings(str(engine.url), TEST_ORIGIN, False), engine=engine),
        base_url=TEST_ORIGIN,
        headers={"Origin": TEST_ORIGIN},
    ) as client:
        yield client


@pytest.fixture(scope="session")
def encoded_password():
    return hash_password(TEST_PASSWORD)
