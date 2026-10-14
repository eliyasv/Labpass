"""One locked event per transaction; external publication precedes DB acknowledgement."""

import json
import logging
from datetime import timedelta
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from labpass.models import OutboxEvent

logger = logging.getLogger("labpass")


class Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: UUID
    event_type: Literal["booking.confirmed.v1"]


class PublicationError(Exception):
    """Publication was rejected or its result is unknown; retry the stable event ID."""


class Publisher(Protocol):
    def publish(self, body: str) -> None: ...


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(300, 2 ** min(attempts, 9)))


def publish_one(sessions, publisher: Publisher, *, max_attempts=5) -> bool:
    with sessions.begin() as session:
        row = session.scalar(
            select(OutboxEvent)
            .where(
                OutboxEvent.published_at.is_(None),
                OutboxEvent.failed_at.is_(None),
                OutboxEvent.next_attempt_at <= func.clock_timestamp(),
            )
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if row is None:
            return False
        row.publish_attempts += 1
        if row.event_type != "booking.confirmed.v1":
            row.failed_at = func.clock_timestamp()
            row.last_error_code = "unsupported_event_type"
            outcome = "failed"
        elif row.publish_attempts > max_attempts:
            row.failed_at = func.clock_timestamp()
            row.last_error_code = "publish_attempts_exhausted"
            outcome = "failed"
        else:
            body = Envelope(event_id=row.id, event_type=row.event_type).model_dump_json()
            try:
                publisher.publish(body)
            except PublicationError:
                row.last_error_code = "publish_failed"
                row.next_attempt_at = func.clock_timestamp() + backoff(row.publish_attempts)
                if row.publish_attempts >= max_attempts:
                    row.failed_at = func.clock_timestamp()
                outcome = "failed" if row.failed_at is not None else "retry"
            else:
                row.published_at = func.clock_timestamp()
                row.last_error_code = None
                outcome = "published"
        event_id, booking_id, attempts = row.id, row.booking_id, row.publish_attempts
    # A failed DB commit must not be logged as successful publication bookkeeping.
    logger.info(
        json.dumps(
            {
                "event": "outbox_attempt",
                "event_id": str(event_id),
                "booking_id": str(booking_id),
                "outcome": outcome,
                "attempts": attempts,
            }
        )
    )
    return True


def publish_batch(sessions, publisher: Publisher, *, limit=10, max_attempts=5) -> int:
    if not 1 <= limit <= 100 or not 1 <= max_attempts <= 100:
        raise ValueError("Batch/attempt limits must be between 1 and 100")
    processed = 0
    for _ in range(limit):
        if not publish_one(sessions, publisher, max_attempts=max_attempts):
            break
        processed += 1
    return processed
