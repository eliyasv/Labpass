import pytest
from alembic import command
from alembic.config import Config
from conftest import ROOT, migrate
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from labpass.services import create_booking


def test_migration_round_trip_and_model_agreement(engine, sessions):
    with engine.begin() as connection:
        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["connection"] = connection
        command.check(config)
        migrate(connection, "downgrade", "base")
        assert set(inspect(connection).get_table_names()) == {"alembic_version"}
        migrate(connection)
        command.check(config)
    assert "outbox_events" in inspect(engine).get_table_names()


def test_upgrade_preserves_legacy_bookings_and_locks_credentials(engine, sessions, data):
    with sessions.begin() as session:
        booking_id = create_booking(session, data["users"][0], data["workshop"], "legacy-key").id
    with engine.begin() as connection:
        migrate(connection, "downgrade", "0001")
        assert "password_hash" not in {c["name"] for c in inspect(connection).get_columns("users")}
        migrate(connection)
        assert (
            connection.scalar(
                text("SELECT password_hash FROM users WHERE id=:id"), {"id": data["users"][0]}
            )
            is None
        )
        assert (
            connection.scalar(text("SELECT status FROM bookings WHERE id=:id"), {"id": booking_id})
            == "active"
        )
        assert (
            connection.scalar(
                text("SELECT reserved FROM workshops WHERE id=:id"), {"id": data["workshop"]}
            )
            == 1
        )
        assert connection.scalar(text("SELECT count(*) FROM outbox_events")) == 1
        assert connection.scalar(text("SELECT count(*) FROM idempotency_records")) == 1


def test_case_collisions_abort_upgrade_without_data_loss(engine, sessions):
    with engine.begin() as connection:
        migrate(connection, "downgrade", "0001")
        connection.execute(
            text(
                "INSERT INTO users (id,email) VALUES "
                "('00000000-0000-0000-0000-000000000001','User@example.test'),"
                "('00000000-0000-0000-0000-000000000002','user@example.test')"
            )
        )
    try:
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                migrate(connection)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0001"
            assert connection.scalar(text("SELECT count(*) FROM users")) == 2
            assert "password_hash" not in {
                column["name"] for column in inspect(connection).get_columns("users")
            }
    finally:
        # Remove only this test's conflicting fixtures, then restore the schema head.
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM users"))
            migrate(connection)


def test_readiness_requires_authentication_migration(engine, client):
    with engine.begin() as connection:
        migrate(connection, "downgrade", "0001")
    try:
        response = client.get("/api/health/ready")
        assert response.status_code == 500
        assert response.json() == {"detail": "database_error"}
    finally:
        with engine.begin() as connection:
            migrate(connection)
    assert client.get("/api/health/ready").status_code == 200


def test_background_upgrade_preserves_pending_events(engine, sessions, data):
    with engine.begin() as connection:
        migrate(connection, "downgrade", "0002")
        connection.execute(
            text(
                "INSERT INTO bookings (id,user_id,workshop_id,status) "
                "VALUES (:id,:user,:workshop,'active')"
            ),
            {"id": data["other"], "user": data["users"][0], "workshop": data["workshop"]},
        )
        connection.execute(
            text(
                "INSERT INTO outbox_events (id,booking_id,event_type,payload) "
                "VALUES (:id,:booking,'booking.confirmed.v1','{}')"
            ),
            {"id": data["admin"], "booking": data["other"]},
        )
        migrate(connection)
        row = connection.execute(
            text(
                "SELECT published_at, publish_attempts, next_attempt_at, failed_at "
                "FROM outbox_events WHERE id=:id"
            ),
            {"id": data["admin"]},
        ).one()
        assert row.published_at is None and row.publish_attempts == 0
        assert row.next_attempt_at is not None and row.failed_at is None
        assert connection.scalar(text("SELECT count(*) FROM email_deliveries")) == 0


def test_readiness_requires_background_migration(engine, client):
    with engine.begin() as connection:
        migrate(connection, "downgrade", "0002")
    try:
        assert client.get("/api/health/ready").status_code == 500
    finally:
        with engine.begin() as connection:
            migrate(connection)
    assert client.get("/api/health/ready").status_code == 200
