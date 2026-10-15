import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier

import boto3
import botocore.endpoint
import botocore.session
import pytest
from botocore.stub import Stubber
from fastapi.testclient import TestClient

from labpass import cloud_database
from labpass.app import create_app
from labpass.aws_config import AwsRuntimeError
from labpass.aws_runtime import AwsRuntime
from labpass.bootstrap_database import role_credentials
from labpass.cloud_database import CloudDatabase, CloudDatabaseSettings
from labpass.config import Settings

CA = str(Path(__file__).resolve().parents[1] / "certs/rds-global-bundle.pem")


@pytest.fixture(autouse=True)
def no_sdk_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Cloud database tests require stubbed SDK responses")

    monkeypatch.setattr(botocore.endpoint.Endpoint, "_send", forbidden)


@pytest.fixture
def cloud_settings():
    return CloudDatabaseSettings(
        "us-east-1",
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:labpass/api-AbCd12",
        "labpass.example.us-east-1.rds.amazonaws.com",
        "labpass",
        CA,
    )


@pytest.fixture
def secret_client(cloud_settings):
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
        region_name=cloud_settings.region,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    yield client
    client.close()


def response(username="labpass_api", password="private-password"):
    return {"SecretString": json.dumps({"username": username, "password": password})}


def request(settings):
    return {"SecretId": settings.db_secret_arn, "VersionStage": "AWSCURRENT"}


def test_concurrent_requests_fetch_secret_once(cloud_settings, secret_client):
    database = CloudDatabase(cloud_settings, client_factory=lambda *_: secret_client)
    barrier = Barrier(10)

    def load():
        barrier.wait(timeout=5)
        return database.get_sessions()

    try:
        with Stubber(secret_client) as stub:
            stub.add_response("get_secret_value", response(), request(cloud_settings))
            with ThreadPoolExecutor(max_workers=10) as pool:
                factories = list(pool.map(lambda _: load(), range(10)))
            assert all(factory is factories[0] for factory in factories)
            engine = factories[0].kw["bind"]
            assert engine.pool.size() == 5 and engine.pool._max_overflow == 0
            assert engine.hide_parameters
            _, args = engine.dialect.create_connect_args(engine.url)
            assert args["sslmode"] == "verify-full" and args["sslrootcert"] == CA
            stub.assert_no_pending_responses()
    finally:
        database.close()


def test_refresh_failure_retires_pool_and_backs_off(cloud_settings, secret_client, monkeypatch):
    now = [1.0]
    monkeypatch.setattr(cloud_database.time, "monotonic", lambda: now[0])
    database = CloudDatabase(cloud_settings, client_factory=lambda *_: secret_client)
    try:
        with Stubber(secret_client) as stub:
            stub.add_response("get_secret_value", response(), request(cloud_settings))
            original = database.get_sessions()
            disposed = []
            monkeypatch.setattr(original.kw["bind"], "dispose", lambda: disposed.append(True))
            now[0] += 301
            stub.add_client_error(
                "get_secret_value",
                "AccessDeniedException",
                "private-text",
                expected_params=request(cloud_settings),
            )
            for _ in range(3):
                with pytest.raises(AwsRuntimeError, match="^database_secret_unavailable$"):
                    database.get_sessions()
            assert disposed == [True]
            now[0] += 6
            stub.add_response(
                "get_secret_value", response(password="new-password"), request(cloud_settings)
            )
            refreshed = database.get_sessions()
            assert refreshed is not original
            assert refreshed.kw["bind"].url.password == "new-password"
            stub.assert_no_pending_responses()
    finally:
        database.close()
    with pytest.raises(AwsRuntimeError, match="closed"):
        database.get_sessions()


def test_master_secret_is_rejected_for_api(cloud_settings, secret_client):
    database = CloudDatabase(cloud_settings, client_factory=lambda *_: secret_client)
    try:
        with Stubber(secret_client) as stub:
            stub.add_response(
                "get_secret_value", response(username="labpass_admin"), request(cloud_settings)
            )
            with pytest.raises(AwsRuntimeError, match="unexpected_database_role"):
                database.get_sessions()
    finally:
        database.close()


def test_rds_managed_secret_name_is_valid_for_bootstrap(cloud_settings):
    arn = (
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
        "rds!db-00000000-0000-0000-0000-000000000001-AbCd12"
    )
    assert replace(cloud_settings, db_secret_arn=arn).db_secret_arn == arn


@pytest.mark.parametrize(
    "changes",
    [
        {"region": "bad"},
        {"db_host": "localhost"},
        {"db_port": False},
        {"db_name": "labpass?sslmode=disable"},
        {"db_ca_file": "relative.pem"},
        {"db_secret_arn": "arn:aws:secretsmanager:eu-west-1:123456789012:secret:db-AbCd12"},
    ],
)
def test_cloud_database_rejects_unsafe_configuration(cloud_settings, changes):
    with pytest.raises(AwsRuntimeError):
        replace(cloud_settings, **changes)


def test_api_cloud_configuration_has_no_queue_or_sender_dependency(cloud_settings, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LABPASS_QUEUE_ARN", raising=False)
    monkeypatch.delenv("LABPASS_SES_FROM", raising=False)
    values = {
        "LABPASS_AWS_ENABLED": "true",
        "AWS_REGION": cloud_settings.region,
        "LABPASS_DB_SECRET_ARN": cloud_settings.db_secret_arn,
        "LABPASS_DB_HOST": cloud_settings.db_host,
        "LABPASS_DB_NAME": cloud_settings.db_name,
        "LABPASS_DB_CA_FILE": CA,
        "APP_ORIGIN": "https://labpass.example.com",
        "LABPASS_COOKIE_SECURE": "true",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    settings = Settings.from_env()
    assert settings.database_url is None and settings.cloud_database == cloud_settings
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://localhost/labpass")
    with pytest.raises(RuntimeError, match="must not set"):
        Settings.from_env()
    monkeypatch.delenv("DATABASE_URL")
    monkeypatch.setenv("LABPASS_COOKIE_SECURE", "false")
    with pytest.raises(RuntimeError, match="Secure cookies"):
        Settings.from_env()


def test_cloud_api_secret_outage_has_safe_503(cloud_settings, secret_client, caplog):
    database = CloudDatabase(cloud_settings, client_factory=lambda *_: secret_client)
    try:
        with Stubber(secret_client) as stub:
            stub.add_client_error(
                "get_secret_value",
                "AccessDeniedException",
                "private-password",
                expected_params=request(cloud_settings),
            )
            app = create_app(
                Settings(None, "https://labpass.example.com", cloud_database=cloud_settings),
                session_provider=database,
            )
            with TestClient(app, base_url="https://labpass.example.com") as client:
                assert client.get("/api/health/live").status_code == 200
                result = client.get("/api/health/ready")
                assert result.status_code == 503 and result.headers["Retry-After"] == "1"
                assert "private-password" not in result.text + caplog.text
    finally:
        database.close()


def test_cloud_api_owns_credential_runtime(
    cloud_settings, secret_client, engine, sessions, monkeypatch
):
    database = CloudDatabase(
        cloud_settings, client_factory=lambda *_: secret_client, engine_factory=lambda _: engine
    )
    origin = "https://labpass.example.com"
    monkeypatch.setattr("labpass.app.CloudDatabase", lambda _: database)
    try:
        with Stubber(secret_client) as stub:
            stub.add_response("get_secret_value", response(), request(cloud_settings))
            with TestClient(
                create_app(Settings(None, origin, cloud_database=cloud_settings)),
                base_url=origin,
                headers={"Origin": origin},
            ) as client:
                assert client.get("/api/health/ready").status_code == 200
                assert (
                    client.post(
                        "/api/auth/register",
                        json={"email": "cloud@example.test", "password": "long-cloud-password"},
                    ).status_code
                    == 201
                )
                login = client.post(
                    "/api/auth/login",
                    json={"email": "cloud@example.test", "password": "long-cloud-password"},
                )
                assert login.status_code == 200
                assert "Secure" in login.headers["set-cookie"]
                assert client.get("/api/auth/me").status_code == 200
                assert (
                    client.post(
                        "/api/auth/logout", headers={"X-CSRF-Token": login.json()["csrf_token"]}
                    ).status_code
                    == 204
                )
            stub.assert_no_pending_responses()
    finally:
        database.close()


def test_role_secret_reuses_existing_credentials(cloud_settings, secret_client):
    with Stubber(secret_client) as stub:
        stub.add_response("get_secret_value", response(), request(cloud_settings))
        assert role_credentials(secret_client, cloud_settings.db_secret_arn, "labpass_api") == (
            "labpass_api",
            "private-password",
        )


def test_missing_role_secret_is_initialized_once(cloud_settings, secret_client, monkeypatch):
    from labpass import bootstrap_database

    monkeypatch.setattr(bootstrap_database.secrets, "token_urlsafe", lambda _: "generated-password")
    token = "00000000-0000-0000-0000-000000000099"
    monkeypatch.setattr(bootstrap_database, "uuid4", lambda: token)
    arn = cloud_settings.db_secret_arn
    with Stubber(secret_client) as stub:
        stub.add_client_error(
            "get_secret_value", "ResourceNotFoundException", expected_params=request(cloud_settings)
        )
        stub.add_response(
            "put_secret_value",
            {"ARN": arn, "VersionId": token},
            {
                "SecretId": arn,
                "ClientRequestToken": token,
                "SecretString": json.dumps(
                    {"username": "labpass_api", "password": "generated-password"}
                ),
                "VersionStages": ["AWSCURRENT"],
            },
        )
        assert role_credentials(secret_client, arn, "labpass_api") == (
            "labpass_api",
            "generated-password",
        )
        stub.assert_no_pending_responses()


def test_access_denial_does_not_overwrite_role_secret(cloud_settings, secret_client):
    with Stubber(secret_client) as stub:
        stub.add_client_error(
            "get_secret_value", "AccessDeniedException", expected_params=request(cloud_settings)
        )
        with pytest.raises(AwsRuntimeError, match="unavailable"):
            role_credentials(secret_client, cloud_settings.db_secret_arn, "labpass_api")


@pytest.mark.parametrize("mode", ["duplicate", "other-account", "master-secret"])
def test_bootstrap_rejects_invalid_secret_boundaries(cloud_settings, mode):
    from labpass.bootstrap_database import validate_secret_arns

    arns = {
        key: f"arn:aws:secretsmanager:us-east-1:123456789012:secret:{key}-AbCd12"
        for key in ["api", "relay", "consumer", "migration"]
    }
    if mode == "duplicate":
        arns["api"] = arns["relay"]
    elif mode == "other-account":
        arns["api"] = arns["api"].replace("123456789012", "999999999999")
    else:
        arns["api"] = cloud_settings.db_secret_arn
    with pytest.raises(AwsRuntimeError, match="invalid_role_secret_arns"):
        validate_secret_arns(cloud_settings, arns)


def test_worker_rejects_wrong_database_role(cloud_settings, secret_client):
    from types import SimpleNamespace

    clients = SimpleNamespace(close=lambda: None)
    settings = SimpleNamespace(
        **cloud_settings.__dict__,
        sender_email="no-reply@example.com",
        queue_url="https://sqs.us-east-1.amazonaws.com/123456789012/test",
    )
    runtime = AwsRuntime(
        settings,
        client_factory=lambda service, _: secret_client if service == "secretsmanager" else clients,
        username="labpass_relay",
    )
    try:
        with Stubber(secret_client) as stub:
            stub.add_response("get_secret_value", response(), request(cloud_settings))
            with pytest.raises(AwsRuntimeError, match="unexpected_database_role"):
                runtime.get_sessions()
    finally:
        runtime.close()
