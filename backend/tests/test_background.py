import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event, Lock
from uuid import uuid4

import pytest
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from labpass.background import consume_once, reset_failed
from labpass.background_config import BackgroundSettings
from labpass.delivery import (
    Claim,
    DeliveryError,
    SendError,
    claim_delivery,
    fail_delivery,
    finish_delivery,
    process_message,
    process_sqs_batch,
)
from labpass.models import Booking, EmailDelivery, OutboxEvent, Workshop
from labpass.outbox import Envelope, PublicationError, publish_batch
from labpass.services import cancel_booking, create_booking


@pytest.fixture
def confirmation(sessions, data):
    with sessions.begin() as session:
        booking = create_booking(session, data["users"][0], data["workshop"], "email-test")
        event = session.scalar(select(OutboxEvent).where(OutboxEvent.booking_id == booking.id))
        return Envelope(event_id=event.id, event_type=event.event_type)


class Recorder:
    def __init__(self):
        self.bodies = []
        self.claims = []

    def publish(self, body):
        self.bodies.append(body)

    def send(self, claim):
        self.claims.append(claim)


def due(sessions, envelope, *, expire=False):
    with sessions.begin() as session:
        row = session.get(EmailDelivery, envelope.event_id)
        row.next_attempt_at = func.clock_timestamp() - timedelta(seconds=1)
        if expire:
            row.lease_until = func.clock_timestamp() - timedelta(seconds=1)


def test_relay_publishes_stable_identity_without_recipient(sessions, confirmation):
    publisher = Recorder()
    assert publish_batch(sessions, publisher) == 1
    assert publish_batch(sessions, publisher) == 0
    assert json.loads(publisher.bodies[0]) == confirmation.model_dump(mode="json")
    assert "recipient" not in publisher.bodies[0]
    with sessions() as session:
        row = session.get(OutboxEvent, confirmation.event_id)
        assert row.published_at is not None and row.publish_attempts == 1


def test_publication_failure_has_bounded_retries_and_preserves_booking(sessions, confirmation):
    class Broken:
        def publish(self, body):
            raise PublicationError("failure")

    assert publish_batch(sessions, Broken(), max_attempts=2) == 1
    assert publish_batch(sessions, Broken(), max_attempts=2) == 0
    with sessions.begin() as session:
        row = session.get(OutboxEvent, confirmation.event_id)
        assert row.last_error_code == "publish_failed"
        assert row.publish_attempts == 1 and row.failed_at is None
        row.next_attempt_at = func.clock_timestamp() - timedelta(seconds=1)
    assert publish_batch(sessions, Broken(), max_attempts=2) == 1
    assert publish_batch(sessions, Broken(), max_attempts=2) == 0
    with sessions() as session:
        row = session.get(OutboxEvent, confirmation.event_id)
        assert row.failed_at is not None and row.published_at is None
        assert row.publish_attempts == 2
        assert session.get(Booking, row.booking_id).status == "active"
        assert session.get(Workshop, session.get(Booking, row.booking_id).workshop_id).reserved == 1


def test_two_relays_really_overlap_without_claiming_same_event(sessions, data):
    with sessions.begin() as session:
        for user in data["users"][:2]:
            create_booking(session, user, data["workshop"], "concurrent-relay")
    barrier = Barrier(2)
    bodies = []
    lock = Lock()

    class Paused:
        def publish(self, body):
            with lock:
                bodies.append(body)
            # Both external publishes must be reached while their actual row locks are held.
            barrier.wait(timeout=5)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(publish_batch, sessions, Paused(), limit=1) for _ in range(2)]
        assert [future.result(timeout=10) for future in futures] == [1, 1]
    assert len({json.loads(body)["event_id"] for body in bodies}) == 2


def test_publish_success_before_db_failure_republishes_same_event(sessions, confirmation):
    publisher = Recorder()

    def fail_commit(session):
        raise RuntimeError("commit failure")

    sqlalchemy_event.listen(Session, "before_commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="commit failure"):
            publish_batch(sessions, publisher, limit=1)
    finally:
        sqlalchemy_event.remove(Session, "before_commit", fail_commit)
    assert publish_batch(sessions, publisher, limit=1) == 1
    assert publisher.bodies[0] == publisher.bodies[1]


def test_consumer_duplicate_does_not_resend(sessions, confirmation):
    sender = Recorder()
    assert process_message(sessions, sender, confirmation.model_dump_json()) == "sent"
    assert process_message(sessions, sender, confirmation.model_dump_json()) == "duplicate"
    assert len(sender.claims) == 1


def test_competing_consumer_cannot_send_during_live_lease(sessions, confirmation):
    sending, release = Event(), Event()
    sender = Recorder()

    class Paused:
        def send(self, claim):
            sender.send(claim)
            sending.set()
            assert release.wait(timeout=5)

    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(process_message, sessions, Paused(), confirmation.model_dump_json())
        assert sending.wait(timeout=5)
        try:
            with pytest.raises(DeliveryError, match="busy"):
                process_message(sessions, sender, confirmation.model_dump_json())
        finally:
            release.set()
        assert future.result(timeout=10) == "sent"
    assert len(sender.claims) == 1


def test_expired_lease_is_reclaimed_and_old_owner_is_fenced(sessions, confirmation):
    first = claim_delivery(sessions, confirmation)
    assert isinstance(first, Claim)
    due(sessions, confirmation, expire=True)
    second = claim_delivery(sessions, confirmation)
    assert isinstance(second, Claim) and first.token != second.token
    with pytest.raises(DeliveryError, match="lease_lost"):
        finish_delivery(sessions, first)
    fail_delivery(sessions, first, max_attempts=5)
    finish_delivery(sessions, second)
    with sessions() as session:
        assert session.get(EmailDelivery, confirmation.event_id).status == "sent"


def test_email_failure_backoff_exhaustion_preserves_booking(sessions, confirmation):
    class Broken:
        def send(self, claim):
            raise SendError("failure")

    with pytest.raises(DeliveryError, match="send_failed"):
        process_message(sessions, Broken(), confirmation.model_dump_json(), max_attempts=2)
    with pytest.raises(DeliveryError, match="busy"):
        process_message(sessions, Broken(), confirmation.model_dump_json(), max_attempts=2)
    due(sessions, confirmation)
    with pytest.raises(DeliveryError, match="send_failed"):
        process_message(sessions, Broken(), confirmation.model_dump_json(), max_attempts=2)
    with pytest.raises(DeliveryError, match="failed"):
        process_message(sessions, Recorder(), confirmation.model_dump_json(), max_attempts=2)
    with sessions() as session:
        row = session.get(EmailDelivery, confirmation.event_id)
        assert row.status == "failed" and row.attempts == 2
        event = session.get(OutboxEvent, confirmation.event_id)
        booking = session.get(Booking, event.booking_id)
        assert booking.status == "active"
        assert session.get(Workshop, booking.workshop_id).reserved == 1


def test_cancelled_before_processing_suppresses_email(sessions, confirmation):
    with sessions.begin() as session:
        event = session.get(OutboxEvent, confirmation.event_id)
        booking = session.get(Booking, event.booking_id)
        cancel_booking(session, booking.user_id, booking.id)
    sender = Recorder()
    assert process_message(sessions, sender, confirmation.model_dump_json()) == "skipped"
    assert sender.claims == []
    assert process_message(sessions, sender, confirmation.model_dump_json()) == "duplicate"


def test_email_acceptance_then_recording_failure_documents_duplicate_window(sessions, confirmation):
    sender = Recorder()

    class FailAfterSend:
        def send(self, claim):
            sender.send(claim)
            raise RuntimeError("crash after acceptance")

    with pytest.raises(RuntimeError, match="after acceptance"):
        process_message(sessions, FailAfterSend(), confirmation.model_dump_json())
    due(sessions, confirmation, expire=True)
    assert process_message(sessions, sender, confirmation.model_dump_json()) == "sent"
    assert len(sender.claims) == 2  # Deliberately demonstrates why exactly-once is not promised.


@pytest.mark.parametrize(
    "body",
    [
        "bad json",
        "{}",
        '{"event_id":"no"}',
        json.dumps({"event_id": str(uuid4()), "event_type": "unknown"}),
    ],
)
def test_poison_messages_are_not_accepted(sessions, body):
    with pytest.raises(DeliveryError, match="invalid_message"):
        process_message(sessions, Recorder(), body)


def test_unknown_event_and_tampered_payload_are_rejected(sessions, confirmation):
    with pytest.raises(DeliveryError, match="unknown_event"):
        process_message(
            sessions,
            Recorder(),
            Envelope(event_id=uuid4(), event_type="booking.confirmed.v1").model_dump_json(),
        )
    with sessions.begin() as session:
        event = session.get(OutboxEvent, confirmation.event_id)
        event.payload = {**event.payload, "recipient": "other@example.test"}
    with pytest.raises(DeliveryError, match="invalid_event"):
        process_message(sessions, Recorder(), confirmation.model_dump_json())


def test_partial_batch_failures_do_not_retry_successful_records():
    processed = []

    def processor(body):
        processed.append(body)
        if body == "bad":
            raise DeliveryError("invalid_message")

    result = process_sqs_batch(
        {
            "Records": [
                {"messageId": "one", "body": "good"},
                {"messageId": "two", "body": "bad"},
                {"messageId": "three", "body": "also good"},
            ]
        },
        processor,
    )
    assert result == {"batchItemFailures": [{"itemIdentifier": "two"}]}
    assert processed == ["good", "bad", "also good"]


def test_success_before_ack_failure_is_safe_on_redelivery(sessions, confirmation):
    class Queue:
        def receive(self, **kwargs):
            return [
                {
                    "Body": confirmation.model_dump_json(),
                    "ReceiptHandle": "receipt",
                    "MessageId": "message",
                }
            ]

        def acknowledge(self, receipt):
            raise RuntimeError("ack failed")

        def retry_later(self, receipt, *, visibility):
            assert visibility == 120

    sender = Recorder()
    assert consume_once(sessions, Queue(), sender) == 0
    assert consume_once(sessions, Queue(), sender) == 0
    assert len(sender.claims) == 1


@pytest.mark.parametrize(
    "endpoint",
    [
        "",
        "https://sqs.us-east-1.amazonaws.com",
        "http://evil.example:9324",
        "http://user:password@queue:9324",
        "http://queue:9324/path",
    ],
)
def test_runtime_cannot_accidentally_use_real_aws(endpoint):
    with pytest.raises(ValueError, match="local SQS"):
        BackgroundSettings("postgresql+psycopg://local/db", endpoint, "mailpit")


def test_runtime_cannot_send_internet_email():
    with pytest.raises(ValueError, match="local mail"):
        BackgroundSettings("postgresql+psycopg://local/db", "http://queue:9324", "smtp.example.com")


def test_operator_reset_refuses_live_or_sent_claim_and_allows_expired_claim(sessions, confirmation):
    first = claim_delivery(sessions, confirmation)
    assert reset_failed(sessions, "retry-delivery", confirmation.event_id) == 0
    due(sessions, confirmation, expire=True)
    assert reset_failed(sessions, "retry-delivery", confirmation.event_id) == 1
    with pytest.raises(DeliveryError, match="lease_lost"):
        finish_delivery(sessions, first)
    assert process_message(sessions, Recorder(), confirmation.model_dump_json()) == "sent"
    assert reset_failed(sessions, "retry-delivery", confirmation.event_id) == 0


def test_operator_outbox_reset_only_retries_failed_unpublished_event(sessions, confirmation):
    assert reset_failed(sessions, "retry-outbox", confirmation.event_id) == 0
    with sessions.begin() as session:
        row = session.get(OutboxEvent, confirmation.event_id)
        row.failed_at = func.clock_timestamp()
        row.publish_attempts = 5
    assert reset_failed(sessions, "retry-outbox", confirmation.event_id) == 1
    assert publish_batch(sessions, Recorder()) == 1
    assert reset_failed(sessions, "retry-outbox", confirmation.event_id) == 0
