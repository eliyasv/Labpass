"""Durable claims coordinate senders; post-send DB failure can still duplicate email."""

import json
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Protocol
from uuid import UUID, uuid4

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from labpass.models import Booking, EmailDelivery, OutboxEvent, User
from labpass.outbox import Envelope, backoff

logger = logging.getLogger("labpass")


class DeliveryError(Exception):
    """The queue message must remain unacknowledged for retry or DLQ redrive."""


class SendError(Exception):
    """Mail acceptance failed or is unknown; message contents must not be logged."""


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    booking_id: UUID
    user_id: UUID
    workshop_id: UUID
    recipient: str = Field(min_length=3, max_length=254)
    workshop_title: str = Field(min_length=1, max_length=200)

    @field_validator("recipient")
    @classmethod
    def valid_recipient(cls, value):
        try:
            normalized = validate_email(
                value, check_deliverability=False, allow_smtputf8=False, test_environment=True
            ).ascii_email.lower()
        except EmailNotValidError:
            raise ValueError("Invalid recipient") from None
        if normalized != value:
            raise ValueError("Recipient must be normalized")
        return value


@dataclass(frozen=True)
class Claim:
    event_id: UUID
    token: UUID
    confirmation: Confirmation = field(repr=False)


class Sender(Protocol):
    def send(self, claim: Claim) -> None: ...


def claim_delivery(sessions, envelope: Envelope, *, lease_seconds=90, max_attempts=5):
    if not 30 <= lease_seconds <= 3600 or not 1 <= max_attempts <= 100:
        raise ValueError("Invalid lease or retry limit")
    with sessions.begin() as session:
        event = session.get(OutboxEvent, envelope.event_id)
        if event is None or event.event_type != envelope.event_type:
            raise DeliveryError("unknown_event")
        try:
            confirmation = Confirmation.model_validate(event.payload)
        except ValidationError:
            raise DeliveryError("invalid_event") from None
        booking = session.get(Booking, event.booking_id)
        user = session.get(User, booking.user_id) if booking is not None else None
        if (
            booking is None
            or user is None
            or confirmation.booking_id != booking.id
            or confirmation.user_id != booking.user_id
            or confirmation.workshop_id != booking.workshop_id
            or confirmation.recipient != user.email
        ):
            raise DeliveryError("invalid_event")
        session.execute(insert(EmailDelivery).values(event_id=event.id).on_conflict_do_nothing())
        row = session.scalar(
            select(EmailDelivery)
            .where(EmailDelivery.event_id == event.id)
            .with_for_update(skip_locked=True)
        )
        if row is None:
            return "busy"
        now = session.scalar(select(func.clock_timestamp()))
        if row.status in {"sent", "skipped"}:
            return "duplicate"
        if row.status == "failed":
            return "failed"
        if (row.status == "sending" and row.lease_until > now) or row.next_attempt_at > now:
            return "busy"
        if booking.status == "cancelled":
            row.status = "skipped"
            row.lease_token = row.lease_until = None
            row.completed_at = now
            return "skipped"
        if row.attempts >= max_attempts:
            row.status = "failed"
            row.lease_token = row.lease_until = None
            row.completed_at = now
            row.last_error_code = "send_attempts_exhausted"
            return "failed"
        row.attempts += 1
        row.status = "sending"
        row.lease_token = uuid4()
        row.lease_until = now + timedelta(seconds=lease_seconds)
        row.last_error_code = None
        return Claim(event.id, row.lease_token, confirmation)


def finish_delivery(sessions, claim: Claim):
    with sessions.begin() as session:
        result = session.execute(
            update(EmailDelivery)
            .where(
                EmailDelivery.event_id == claim.event_id,
                EmailDelivery.status == "sending",
                EmailDelivery.lease_token == claim.token,
                EmailDelivery.lease_until > func.clock_timestamp(),
            )
            .values(
                status="sent",
                completed_at=func.clock_timestamp(),
                lease_token=None,
                lease_until=None,
                last_error_code=None,
            )
        )
        if result.rowcount != 1:
            raise DeliveryError("lease_lost_after_send")


def fail_delivery(sessions, claim: Claim, *, max_attempts):
    with sessions.begin() as session:
        row = session.scalar(
            select(EmailDelivery)
            .where(
                EmailDelivery.event_id == claim.event_id,
                EmailDelivery.status == "sending",
                EmailDelivery.lease_token == claim.token,
                EmailDelivery.lease_until > func.clock_timestamp(),
            )
            .with_for_update()
        )
        if row is None:
            return
        row.status = "failed" if row.attempts >= max_attempts else "retry"
        row.completed_at = func.clock_timestamp() if row.status == "failed" else None
        row.lease_token = row.lease_until = None
        row.last_error_code = "send_failed"
        row.next_attempt_at = func.clock_timestamp() + backoff(row.attempts)


def process_message(sessions, sender: Sender, body: str, *, lease_seconds=90, max_attempts=5):
    try:
        envelope = Envelope.model_validate_json(body)
    except ValidationError:
        raise DeliveryError("invalid_message") from None
    claim = claim_delivery(
        sessions, envelope, lease_seconds=lease_seconds, max_attempts=max_attempts
    )
    if claim in ("busy", "failed"):
        raise DeliveryError(claim)
    if isinstance(claim, Claim):
        try:
            sender.send(claim)
        except SendError:
            fail_delivery(sessions, claim, max_attempts=max_attempts)
            raise DeliveryError("send_failed") from None
        finish_delivery(sessions, claim)
        outcome = "sent"
        booking_id = str(claim.confirmation.booking_id)
    else:
        outcome, booking_id = claim, None
    logger.info(
        json.dumps(
            {
                "event": "email_delivery",
                "event_id": str(envelope.event_id),
                "booking_id": booking_id,
                "outcome": outcome,
            }
        )
    )
    return outcome


def process_sqs_batch(event, processor):
    """Return Lambda's partial-batch contract; successful records are not retried."""
    failures = []
    for record in event["Records"]:
        try:
            processor(record["body"])
        except Exception:
            # Bodies, credentials and exception text are intentionally not logged.
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
