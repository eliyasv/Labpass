import json
import os
from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from labpass.auth import hash_password, login, register
from labpass.database_roles import ROLE_NAMES, bootstrap_roles, grant_runtime_privileges
from labpass.delivery import process_message
from labpass.migrate import upgrade
from labpass.models import EmailDelivery, OutboxEvent, User, Workshop
from labpass.outbox import publish_batch
from labpass.services import cancel_booking, create_booking


def test_bootstrap_pipeline_recovers_after_grant_failure(restricted_database, monkeypatch):
    from pathlib import Path

    import boto3
    import botocore.endpoint
    import botocore.session
    from botocore.stub import Stubber

    from labpass import bootstrap_database
    from labpass.cloud_database import CloudDatabaseSettings

    url, roles, credentials, owner_engine, _ = restricted_database
    master_arn = "arn:aws:secretsmanager:us-east-1:123456789012:secret:master-AbCd12"
    arns = {
        key: f"arn:aws:secretsmanager:us-east-1:123456789012:secret:{key}-AbCd12" for key in roles
    }
    settings = CloudDatabaseSettings(
        "us-east-1",
        master_arn,
        "db.example.us-east-1.rds.amazonaws.com",
        url.database,
        str(Path(__file__).resolve().parents[1] / "certs/rds-global-bundle.pem"),
    )
    core = botocore.session.Session()
    store = core.get_component("config_store")
    for name, value in (
        ("profile", None),
        ("config_file", os.devnull),
        ("credentials_file", os.devnull),
    ):
        store.set_config_variable(name, value)
    client = boto3.Session(botocore_session=core).client(
        "secretsmanager",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    monkeypatch.setattr(
        botocore.endpoint.Endpoint, "_send", lambda *_: pytest.fail("No AWS network allowed")
    )
    monkeypatch.setattr(bootstrap_database, "ROLE_NAMES", roles)
    monkeypatch.setattr(
        bootstrap_database,
        "make_api_engine",
        lambda configured: create_engine(
            url.set(
                username=owner_engine.url.username
                if configured.username == "labpass_admin"
                else configured.username
            ),
            hide_parameters=True,
        ),
    )
    grant = bootstrap_database.grant_runtime_privileges

    def fail_grants(*args):
        raise RuntimeError("injected_grant_failure")

    monkeypatch.setattr(bootstrap_database, "grant_runtime_privileges", fail_grants)
    try:
        with Stubber(client) as stub:
            for _ in range(2):
                stub.add_response(
                    "get_secret_value",
                    {
                        "SecretString": json.dumps(
                            {"username": "labpass_admin", "password": "private"}
                        )
                    },
                    {"SecretId": master_arn, "VersionStage": "AWSCURRENT"},
                )
                for key, arn in arns.items():
                    stub.add_response(
                        "get_secret_value",
                        {
                            "SecretString": json.dumps(
                                {"username": credentials[key][0], "password": credentials[key][1]}
                            )
                        },
                        {"SecretId": arn, "VersionStage": "AWSCURRENT"},
                    )
            with pytest.raises(RuntimeError, match="injected_grant_failure"):
                bootstrap_database.provision(settings, arns, client)
            monkeypatch.setattr(bootstrap_database, "grant_runtime_privileges", grant)
            bootstrap_database.provision(settings, arns, client)
            stub.assert_no_pending_responses()
        booking(restricted_database)
    finally:
        client.close()


@pytest.fixture
def restricted_database():
    suffix = uuid4().hex[:16]
    database = "labpass_role_test_" + suffix
    operator = "labpass_operator_" + suffix
    roles = {key: f"labpass_{key}_{suffix}" for key in ROLE_NAMES}
    credentials = {key: (role, "role-password-with-'quoted-value") for key, role in roles.items()}
    base_url = make_url(os.environ["TEST_DATABASE_URL"])
    admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
    owner_engine = migration_engine = None
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE ROLE "{operator}" LOGIN CREATEROLE')
            connection.exec_driver_sql(f'CREATE DATABASE "{database}" OWNER "{operator}"')
        url = base_url.set(database=database)
        owner_engine = create_engine(url.set(username=operator), hide_parameters=True)
        with owner_engine.begin() as connection:
            bootstrap_roles(connection.connection.driver_connection, credentials, roles)
        migration_engine = create_engine(url.set(username=roles["migration"]), hide_parameters=True)
        with migration_engine.begin() as connection:
            upgrade(connection)
            grant_runtime_privileges(connection.connection.driver_connection, roles)
        yield url, roles, credentials, owner_engine, migration_engine
    finally:
        for engine in (owner_engine, migration_engine):
            if engine is not None:
                engine.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
            for role in [*roles.values(), operator]:
                connection.exec_driver_sql(f'DROP ROLE IF EXISTS "{role}"')
        admin.dispose()


@contextmanager
def runtime(restricted_database, component):
    url, roles, _, _, _ = restricted_database
    engine = create_engine(url.set(username=roles[component]), hide_parameters=True)
    try:
        yield engine, sessionmaker(engine, expire_on_commit=False)
    finally:
        engine.dispose()


def booking(restricted_database):
    with runtime(restricted_database, "api") as (_, sessions):
        with sessions.begin() as session:
            user = register(
                session, f"roles-{uuid4().hex}@example.test", hash_password("roles-password-long")
            )
            workshop = Workshop(id=uuid4(), title="Role verification", capacity=20)
            session.add(workshop)
            session.flush()
            result = create_booking(session, user.id, workshop.id, "role-verification")
            event = session.scalar(select(OutboxEvent).where(OutboxEvent.booking_id == result.id))
            return user.id, workshop.id, result.id, event.id


def test_restricted_api_auth_booking_and_cancel(restricted_database):
    user_id, workshop_id, booking_id, _ = booking(restricted_database)
    with runtime(restricted_database, "api") as (_, sessions):
        with sessions.begin() as session:
            retry = create_booking(session, user_id, workshop_id, "role-verification")
            assert retry.id == booking_id
            assert cancel_booking(session, user_id, booking_id).status == "cancelled"
        with sessions.begin() as session:
            user = session.get(User, user_id)
            principal, token, expiry = login(session, user.email, "roles-password-long", None, 3600)
            assert principal.id == user_id and token and expiry


@pytest.mark.parametrize("component", ["api", "relay", "consumer"])
@pytest.mark.parametrize(
    "statement",
    [
        "CREATE TABLE public.forbidden_table(id integer)",
        "DROP TABLE public.workshops CASCADE",
        "TRUNCATE public.workshops CASCADE",
        "CREATE SCHEMA forbidden_schema",
        "SELECT * FROM public.alembic_version",
    ],
)
def test_runtime_cannot_migrate_or_truncate(restricted_database, component, statement):
    with runtime(restricted_database, component) as (engine, _):
        with pytest.raises(DBAPIError) as error, engine.begin() as connection:
            connection.exec_driver_sql(statement)
        assert error.value.orig.sqlstate == "42501"


@pytest.mark.parametrize("component", ["relay", "consumer"])
def test_workers_cannot_change_inventory(restricted_database, component):
    booking(restricted_database)
    with runtime(restricted_database, component) as (engine, _):
        with pytest.raises(DBAPIError) as error, engine.begin() as connection:
            connection.exec_driver_sql("UPDATE public.workshops SET reserved = 0")
        assert error.value.orig.sqlstate == "42501"


def test_relay_and_consumer_can_process_with_restricted_grants(restricted_database):
    _, _, _, event_id = booking(restricted_database)

    class Publisher:
        bodies = []

        def publish(self, body):
            self.bodies.append(body)

    class Sender:
        claims = []

        def send(self, claim):
            self.claims.append(claim)

    publisher, sender = Publisher(), Sender()
    with runtime(restricted_database, "relay") as (_, sessions):
        assert publish_batch(sessions, publisher) == 1
    with runtime(restricted_database, "consumer") as (_, sessions):
        process_message(sessions, sender, publisher.bodies[0])
        process_message(sessions, sender, publisher.bodies[0])
        assert len(sender.claims) == 1
        with sessions() as session:
            assert session.get(EmailDelivery, event_id).status == "sent"


def test_bootstrap_is_repeatable_without_rotating_secrets(restricted_database):
    _, roles, credentials, owner_engine, migration_engine = restricted_database
    with owner_engine.begin() as connection:
        bootstrap_roles(connection.connection.driver_connection, credentials, roles)
    with migration_engine.begin() as connection:
        upgrade(connection)
        grant_runtime_privileges(connection.connection.driver_connection, roles)
    booking(restricted_database)


def test_bootstrap_rejects_privileged_existing_roles(restricted_database):
    _, roles, credentials, owner_engine, _ = restricted_database
    admin = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        with admin.begin() as connection:
            connection.exec_driver_sql(f'ALTER ROLE "{roles["api"]}" CREATEDB')
    finally:
        admin.dispose()
    with pytest.raises(ValueError, match="privileged"), owner_engine.begin() as connection:
        bootstrap_roles(connection.connection.driver_connection, credentials, roles)


def test_credentials_match_database_roles(restricted_database):
    _, roles, credentials, owner_engine, _ = restricted_database
    wrong = dict(credentials, api=(roles["migration"], "wrong-password"))
    with (
        pytest.raises(ValueError, match="unexpected_database_role"),
        owner_engine.begin() as connection,
    ):
        bootstrap_roles(connection.connection.driver_connection, wrong, roles)
