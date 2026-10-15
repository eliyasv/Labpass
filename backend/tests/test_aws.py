import json
import os
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import boto3
import botocore.endpoint
import botocore.session
import pytest
from botocore.stub import Stubber
from sqlalchemy import func, select

from labpass import aws_relay, aws_runtime, lambda_handler
from labpass.aws_config import AwsRuntimeError, AwsSettings
from labpass.aws_runtime import AwsRuntime, SesSender, database_url, make_aws_client
from labpass.models import Booking, EmailDelivery, OutboxEvent, Workshop
from labpass.outbox import Envelope, publish_batch
from labpass.services import create_booking

CA_FILE = str(Path(__file__).resolve().parents[1] / "certs/rds-global-bundle.pem")


@pytest.fixture(autouse=True)
def forbid_aws_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("AWS tests must use Stubber; no HTTP request is allowed")

    monkeypatch.setattr(botocore.endpoint.Endpoint, "_send", forbidden)


@pytest.fixture
def settings():
    # Fictional test identifiers only; no infrastructure is created or looked up.
    return AwsSettings(
        region="us-east-1",
        queue_arn="arn:aws:sqs:us-east-1:123456789012:labpass-confirmations",
        db_secret_arn="arn:aws:secretsmanager:us-east-1:123456789012:secret:labpass/db-AbCd12",
        db_host="labpass.example.us-east-1.rds.amazonaws.com",
        db_name="labpass",
        sender_email="no-reply@example.com",
        db_ca_file=CA_FILE,
    )


@pytest.fixture
def clients(settings):
    core = botocore.session.Session()
    store = core.get_component("config_store")
    for name, value in (
        ("profile", None),
        ("config_file", os.devnull),
        ("credentials_file", os.devnull),
    ):
        store.set_config_variable(name, value)
    session = boto3.Session(botocore_session=core)
    clients = {
        name: session.client(
            name,
            region_name=settings.region,
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        for name in ("secretsmanager", "sesv2", "sqs")
    }
    yield clients
    for client in clients.values():
        client.close()


class Context:
    def __init__(self, remaining=60_000):
        self.remaining = remaining

    def get_remaining_time_in_millis(self):
        return self.remaining


def record(settings, message_id, body):
    return {
        "messageId": message_id,
        "body": body,
        "eventSource": "aws:sqs",
        "eventSourceARN": settings.queue_arn,
    }


def envelopes(sessions, data, count=1):
    results = []
    with sessions.begin() as session:
        for user in data["users"][:count]:
            booking = create_booking(session, user, data["workshop"], "aws-email")
            event = session.scalar(select(OutboxEvent).where(OutboxEvent.booking_id == booking.id))
            results.append(Envelope(event_id=event.id, event_type=event.event_type))
    return results


def expected_mail(sessions, envelope, settings):
    with sessions() as session:
        payload = session.get(OutboxEvent, envelope.event_id).payload
    return {
        "FromEmailAddress": settings.sender_email,
        "Destination": {"ToAddresses": [payload["recipient"]]},
        "Content": {
            "Simple": {
                "Subject": {"Data": "Your LabPass reservation", "Charset": "UTF-8"},
                "Body": {
                    "Text": {
                        "Data": "Your reservation was received for "
                        f"{payload['workshop_title']}.\n\n"
                        f"Booking reference: {payload['booking_id']}\n"
                        "Check My bookings in LabPass for its current status.\n",
                        "Charset": "UTF-8",
                    }
                },
            }
        },
    }


def handler_runtime(monkeypatch, settings, sessions, clients):
    runtime = SimpleNamespace(
        settings=settings,
        sender=SesSender(clients["sesv2"], settings.sender_email),
        get_sessions=lambda: sessions,
    )
    monkeypatch.setattr(lambda_handler, "get_runtime", lambda: runtime)
    return runtime


@pytest.mark.parametrize(
    "changes",
    [
        {"region": "us-gov-west-1"},
        {"queue_arn": "arn:aws:sqs:us-east-1:123456789012:queue.fifo"},
        {"queue_arn": "arn:aws:sqs:eu-west-1:123456789012:queue"},
        {"db_secret_arn": "arn:aws:secretsmanager:us-east-1:999999999999:secret:db-AbCd12"},
        {"db_host": "localhost"},
        {"db_host": "db.example.us-east-1.rds.amazonaws.com.evil.example"},
        {"db_name": "db?sslmode=disable"},
        {"db_port": 0},
        {"sender_email": "someone@example.test"},
        {"sender_email": "Name <someone@example.com>"},
        {"db_ca_file": "/missing/rds.pem"},
        {"db_ca_file": "relative.pem"},
    ],
)
def test_unsafe_cloud_configuration_is_rejected(settings, changes):
    with pytest.raises(AwsRuntimeError):
        replace(settings, **changes)


def test_cloud_mode_requires_explicit_enable_and_complete_configuration(monkeypatch):
    monkeypatch.delenv("LABPASS_AWS_ENABLED", raising=False)
    with pytest.raises(AwsRuntimeError, match="not_enabled"):
        AwsSettings.from_env()
    monkeypatch.setenv("LABPASS_AWS_ENABLED", "true")
    monkeypatch.delenv("LABPASS_QUEUE_ARN", raising=False)
    with pytest.raises(AwsRuntimeError, match="missing_aws_configuration"):
        AwsSettings.from_env()


@pytest.mark.parametrize(
    "secret",
    [
        None,
        "bad json",
        "null",
        "[]",
        "{}",
        '{"username":"u","password":7}',
        '{"username":"u","password":""}',
        '{"username":"u","password":"bad\\u0000password"}',
    ],
)
def test_invalid_secrets_fail_without_exposing_inputs(settings, secret):
    with pytest.raises(AwsRuntimeError, match="^invalid_database_secret$"):
        database_url(settings, secret)


def test_secret_password_is_encoded_and_tls_cannot_be_overridden(settings):
    password = "strange@:/?&sslmode=disable#% password"
    url = database_url(settings, json.dumps({"username": "worker", "password": password}))
    assert url.password == password
    assert url.query == {"sslmode": "verify-full", "sslrootcert": CA_FILE}
    assert password not in str(url)
    assert url.host == settings.db_host
    engine = aws_runtime.make_cloud_engine(url)
    try:
        _, connection_args = engine.dialect.create_connect_args(url)
        assert connection_args["sslmode"] == "verify-full"
        assert connection_args["sslrootcert"] == CA_FILE
    finally:
        engine.dispose()


def test_invalid_ca_contents_are_rejected(settings, tmp_path):
    ca = tmp_path / "invalid.pem"
    ca.write_text("not a certificate")
    with pytest.raises(AwsRuntimeError, match="invalid_database_ca_file"):
        replace(settings, db_ca_file=str(ca))


def test_sdk_ignores_endpoint_override_and_disables_hidden_retries(settings, monkeypatch):
    core = botocore.session.Session()
    core.set_credentials("test", "test")
    store = core.get_component("config_store")
    store.set_config_variable("profile", None)
    store.set_config_variable("config_file", os.devnull)
    store.set_config_variable("credentials_file", os.devnull)
    isolated_session = boto3.Session(botocore_session=core)
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://127.0.0.1:1")
    monkeypatch.setattr(boto3, "Session", lambda: isolated_session)
    client = make_aws_client("sqs", settings)
    config = client.meta.config
    assert client.meta.endpoint_url == "https://sqs.us-east-1.amazonaws.com"
    assert config.retries["total_max_attempts"] == 1
    assert (config.connect_timeout, config.read_timeout) == (2, 5)
    client.close()


def test_runtime_refreshes_secret_and_disposes_pool_without_stale_fallback(
    settings, clients, monkeypatch
):
    now = [1000]
    monkeypatch.setattr(aws_runtime.time, "monotonic", lambda: now[0])
    runtime = AwsRuntime(settings, client_factory=lambda name, _: clients[name])
    params = {"SecretId": settings.db_secret_arn, "VersionStage": "AWSCURRENT"}
    with Stubber(clients["secretsmanager"]) as stub:
        for password in ("first-password", "rotated-password"):
            stub.add_response(
                "get_secret_value",
                {"SecretString": json.dumps({"username": "worker", "password": password})},
                params,
            )
        stub.add_client_error(
            "get_secret_value", "AccessDeniedException", "secret details", expected_params=params
        )
        first = runtime.get_sessions()
        first_pool = runtime._engine.pool
        assert first.kw["bind"].url.password == "first-password"
        assert runtime.get_sessions() is first
        now[0] += 301
        second = runtime.get_sessions()
        assert second is not first and first.kw["bind"].pool is not first_pool
        assert second.kw["bind"].url.password == "rotated-password"
        assert second.kw["bind"].hide_parameters is True
        now[0] += 301
        with pytest.raises(AwsRuntimeError, match="^database_secret_unavailable$"):
            runtime.get_sessions()
        assert runtime._engine is None and runtime._sessions is None
        stub.assert_no_pending_responses()
    runtime.close()


def test_sqs_relay_uses_cloud_queue_and_real_database(settings, clients, sessions, data):
    envelope = envelopes(sessions, data)[0]
    runtime = AwsRuntime(settings, client_factory=lambda name, _: clients[name])
    with Stubber(clients["sqs"]) as stub:
        stub.add_response(
            "send_message",
            {"MessageId": "accepted"},
            {"QueueUrl": settings.queue_url, "MessageBody": envelope.model_dump_json()},
        )
        assert publish_batch(sessions, runtime.publisher) == 1
        stub.assert_no_pending_responses()
    with sessions() as session:
        assert session.get(OutboxEvent, envelope.event_id).published_at is not None
    runtime.close()


@pytest.mark.parametrize("batch_size", [3, 10])
def test_handler_partial_failure_duplicate_and_booking_preservation(
    settings, clients, sessions, data, monkeypatch, caplog, batch_size
):
    one, two = envelopes(sessions, data, count=2)
    handler_runtime(monkeypatch, settings, sessions, clients)
    event = {
        "Records": [
            record(settings, "one", one.model_dump_json()),
            record(settings, "two", two.model_dump_json()),
            record(settings, "poison", "bad json"),
        ]
    }
    event["Records"].extend(
        record(settings, f"duplicate-{index}", one.model_dump_json())
        for index in range(batch_size - 3)
    )
    with Stubber(clients["sesv2"]) as stub:
        stub.add_response(
            "send_email", {"MessageId": "accepted"}, expected_mail(sessions, one, settings)
        )
        stub.add_client_error(
            "send_email",
            "MessageRejected",
            "private recipient and secret",
            expected_params=expected_mail(sessions, two, settings),
        )
        expected = {"batchItemFailures": [{"itemIdentifier": "two"}, {"itemIdentifier": "poison"}]}
        assert lambda_handler.lambda_handler(event, Context()) == expected
        # No SES calls are allowed on redelivery of recorded success or pending retry.
        assert lambda_handler.lambda_handler(event, Context()) == expected
        stub.assert_no_pending_responses()
    assert "private recipient" not in caplog.text
    with sessions() as session:
        sent = session.get(EmailDelivery, one.event_id)
        retry = session.get(EmailDelivery, two.event_id)
        assert sent.status == "sent" and sent.attempts == 1
        assert retry.status == "retry" and retry.attempts == 1
        assert session.get(Workshop, data["workshop"]).reserved == 2
        assert all(row.status == "active" for row in session.scalars(select(Booking)))


def test_handler_cancelled_booking_skips_ses(settings, clients, sessions, data, monkeypatch):
    from labpass.services import cancel_booking

    envelope = envelopes(sessions, data)[0]
    with sessions.begin() as session:
        event = session.get(OutboxEvent, envelope.event_id)
        cancel_booking(session, data["users"][0], event.booking_id)
    handler_runtime(monkeypatch, settings, sessions, clients)
    with Stubber(clients["sesv2"]):
        assert lambda_handler.lambda_handler(
            {"Records": [record(settings, "cancelled", envelope.model_dump_json())]}, Context()
        ) == {"batchItemFailures": []}
    with sessions() as session:
        assert session.get(EmailDelivery, envelope.event_id).status == "skipped"


def test_missing_ses_acceptance_id_remains_retryable(
    settings, clients, sessions, data, monkeypatch
):
    envelope = envelopes(sessions, data)[0]
    handler_runtime(monkeypatch, settings, sessions, clients)
    with Stubber(clients["sesv2"]) as stub:
        stub.add_response("send_email", {}, expected_mail(sessions, envelope, settings))
        assert lambda_handler.lambda_handler(
            {"Records": [record(settings, "one", envelope.model_dump_json())]}, Context()
        ) == {"batchItemFailures": [{"itemIdentifier": "one"}]}
        stub.assert_no_pending_responses()
    with sessions() as session:
        assert session.get(EmailDelivery, envelope.event_id).status == "retry"


@pytest.mark.parametrize("remaining", [29_999, 61_000])
def test_handler_time_budget_defers_without_loading_runtime(settings, monkeypatch, remaining):
    monkeypatch.setattr(lambda_handler, "get_runtime", lambda: pytest.fail("must not initialize"))
    assert lambda_handler.lambda_handler(
        {"Records": [record(settings, "one", "body"), record(settings, "two", "body")]},
        Context(remaining),
    ) == {"batchItemFailures": [{"itemIdentifier": "one"}, {"itemIdentifier": "two"}]}


def test_handler_rechecks_time_after_secret_fetch(settings, monkeypatch):
    context = Context()

    def get_sessions():
        context.remaining = 20_000
        return object()

    runtime = SimpleNamespace(settings=settings, get_sessions=get_sessions)
    monkeypatch.setattr(lambda_handler, "get_runtime", lambda: runtime)
    assert lambda_handler.lambda_handler(
        {"Records": [record(settings, "one", "body")]}, context
    ) == {"batchItemFailures": [{"itemIdentifier": "one"}]}


def test_handler_does_not_read_secret_for_another_queue(settings, monkeypatch):
    runtime = SimpleNamespace(
        settings=settings, get_sessions=lambda: pytest.fail("must not read secret")
    )
    monkeypatch.setattr(lambda_handler, "get_runtime", lambda: runtime)
    wrong = {**record(settings, "wrong", "body"), "eventSourceARN": settings.queue_arn + "-other"}
    assert lambda_handler.lambda_handler({"Records": [wrong]}, Context()) == {
        "batchItemFailures": [{"itemIdentifier": "wrong"}]
    }


def test_handler_initialization_failure_retries_entire_batch_once(settings, monkeypatch, caplog):
    calls = []

    def broken():
        calls.append(1)
        raise RuntimeError("private credentials")

    monkeypatch.setattr(lambda_handler, "get_runtime", broken)
    assert lambda_handler.lambda_handler(
        {"Records": [record(settings, "one", "body"), record(settings, "two", "body")]}, Context()
    ) == {"batchItemFailures": [{"itemIdentifier": "one"}, {"itemIdentifier": "two"}]}
    assert calls == [1] and "private credentials" not in caplog.text


@pytest.mark.parametrize(
    "event", [{}, {"Records": None}, {"Records": [{}]}, {"Records": [{"messageId": ""}]}]
)
def test_handler_invalid_shape_fails_whole_batch(event):
    with pytest.raises(AwsRuntimeError):
        lambda_handler.lambda_handler(event, Context())


def test_empty_batch_has_no_runtime_or_network_dependency(monkeypatch):
    monkeypatch.setattr(lambda_handler, "get_runtime", lambda: pytest.fail("must not initialize"))
    assert lambda_handler.lambda_handler({"Records": []}, Context()) == {"batchItemFailures": []}


def test_relay_validate_does_not_construct_runtime(settings, monkeypatch, capsys):
    monkeypatch.setattr(aws_relay.AwsSettings, "from_env", lambda **_: settings)
    monkeypatch.setattr(aws_relay, "AwsRuntime", lambda _: pytest.fail("must not initialize"))
    monkeypatch.setattr("sys.argv", ["aws_relay", "--validate"])
    assert aws_relay.main() == 0
    assert "no AWS calls made" in capsys.readouterr().out


def test_relay_configuration_has_no_ses_dependency(settings, monkeypatch):
    for name, value in {
        "LABPASS_AWS_ENABLED": "true",
        "AWS_REGION": settings.region,
        "LABPASS_QUEUE_ARN": settings.queue_arn,
        "LABPASS_DB_SECRET_ARN": settings.db_secret_arn,
        "LABPASS_DB_HOST": settings.db_host,
        "LABPASS_DB_NAME": settings.db_name,
        "LABPASS_DB_CA_FILE": settings.db_ca_file,
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("LABPASS_SES_FROM", raising=False)
    assert AwsSettings.from_env(require_sender=False).sender_email is None
    with pytest.raises(AwsRuntimeError, match="missing_aws_configuration"):
        AwsSettings.from_env()


def test_relay_runtime_does_not_create_ses_client(settings, clients):
    created = []

    def factory(name, _):
        created.append(name)
        return clients[name]

    runtime = AwsRuntime(replace(settings, sender_email=None), client_factory=factory)
    try:
        assert runtime.sender is None
        assert created == ["secretsmanager", "sqs"]
    finally:
        runtime.close()


def test_ses_acceptance_followed_by_failed_db_commit_retains_claim(
    settings, clients, sessions, data, monkeypatch
):
    from sqlalchemy import event as sqlalchemy_event
    from sqlalchemy.orm import Session

    envelope = envelopes(sessions, data)[0]
    handler_runtime(monkeypatch, settings, sessions, clients)
    accepted = []

    def fail_completion(session):
        if accepted:
            raise RuntimeError("DB completion commit unavailable")

    def mark_accepted(**kwargs):
        accepted.append(1)

    clients["sesv2"].meta.events.register("after-call.sesv2.SendEmail", mark_accepted)
    sqlalchemy_event.listen(Session, "before_commit", fail_completion)
    try:
        with Stubber(clients["sesv2"]) as stub:
            stub.add_response(
                "send_email", {"MessageId": "accepted"}, expected_mail(sessions, envelope, settings)
            )
            result = lambda_handler.lambda_handler(
                {"Records": [record(settings, "ambiguous", envelope.model_dump_json())]}, Context()
            )
            assert result == {"batchItemFailures": [{"itemIdentifier": "ambiguous"}]}
            stub.assert_no_pending_responses()
    finally:
        sqlalchemy_event.remove(Session, "before_commit", fail_completion)
        clients["sesv2"].meta.events.unregister("after-call.sesv2.SendEmail", mark_accepted)
    with sessions() as session:
        row = session.get(EmailDelivery, envelope.event_id)
        assert row.status == "sending" and row.attempts == 1
        now = session.scalar(select(func.clock_timestamp()))
        assert now + timedelta(seconds=110) < row.lease_until <= now + timedelta(seconds=120)
