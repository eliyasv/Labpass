"""Local relay/consumer entry points; no real AWS or internet mail configuration."""

import argparse
import json
import logging
import signal
import smtplib
import time
from pathlib import Path
from threading import Event

from sqlalchemy import and_, func, or_, select, update

from labpass.background_config import BackgroundSettings
from labpass.db import make_engine, make_sessions
from labpass.delivery import DeliveryError, process_message
from labpass.mail import LocalSmtpSender
from labpass.models import EmailDelivery, OutboxEvent
from labpass.outbox import publish_batch
from labpass.queue import DLQ_NAME, get_local_queue

logger = logging.getLogger("labpass")


def reset_failed(sessions, action, event_id):
    """Operator-only reset; sent deliveries and live leases cannot be reset."""
    with sessions.begin() as session:
        if action == "retry-outbox":
            result = session.execute(
                update(OutboxEvent)
                .where(
                    OutboxEvent.id == event_id,
                    OutboxEvent.failed_at.is_not(None),
                    OutboxEvent.published_at.is_(None),
                )
                .values(
                    failed_at=None,
                    publish_attempts=0,
                    next_attempt_at=func.clock_timestamp(),
                    last_error_code=None,
                )
            )
        elif action == "retry-delivery":
            result = session.execute(
                update(EmailDelivery)
                .where(
                    EmailDelivery.event_id == event_id,
                    or_(
                        EmailDelivery.status == "failed",
                        and_(
                            EmailDelivery.status == "sending",
                            EmailDelivery.lease_until <= func.clock_timestamp(),
                        ),
                    ),
                )
                .values(
                    status="retry",
                    attempts=0,
                    completed_at=None,
                    lease_token=None,
                    lease_until=None,
                    next_attempt_at=func.clock_timestamp(),
                    last_error_code=None,
                )
            )
        else:
            raise ValueError("Unknown reset action")
        return result.rowcount


def consume_once(sessions, queue, sender):
    messages = queue.receive(limit=1)
    acknowledged = 0
    for message in messages:
        try:
            process_message(sessions, sender, message["Body"])
            queue.acknowledge(message["ReceiptHandle"])
            acknowledged += 1
        except Exception as exc:
            logger.warning(
                json.dumps(
                    {
                        "event": "queue_message_retry",
                        "message_id": message.get("MessageId"),
                        "error_type": type(exc).__name__,
                    }
                )
            )
            # If this also fails, normal queue visibility expiry still enables retry.
            # Unknown post-send failures must not exhaust the queue's receive budget
            # before the 90-second delivery lease can be reclaimed.
            fast_failure = isinstance(exc, DeliveryError) and str(exc) in {
                "invalid_message",
                "unknown_event",
                "invalid_event",
                "failed",
            }
            queue.retry_later(message["ReceiptHandle"], visibility=10 if fast_failure else 120)
    return acknowledged


def health(settings, sessions, queue, role):
    # Each worker runs alone in a container with a private /tmp; this file holds no data.
    heartbeat = Path(f"/tmp/labpass-{role}-heartbeat")  # nosec B108
    if not heartbeat.exists() or time.time() - heartbeat.stat().st_mtime > 60:
        raise RuntimeError("worker_heartbeat_stale")
    with sessions() as session:
        session.execute(select(OutboxEvent.publish_attempts).limit(1))
        session.execute(select(EmailDelivery.event_id).limit(1))
    queue.client.get_queue_attributes(QueueUrl=queue.queue_url, AttributeNames=["QueueArn"])
    if role == "consumer":
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=5) as smtp:
            smtp.noop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=[
            "relay",
            "consumer",
            "health",
            "status",
            "retry-outbox",
            "retry-delivery",
            "replay-dlq",
        ],
    )
    parser.add_argument("--role", choices=["relay", "consumer"])
    parser.add_argument("--event-id", type=str)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = BackgroundSettings.from_env()
    engine = make_engine(settings.database_url, pool_size=2, max_overflow=0)
    sessions = make_sessions(engine)
    try:
        if args.action == "status":
            with sessions() as session:
                print(
                    json.dumps(
                        {
                            "outbox_pending": session.scalar(
                                select(func.count())
                                .select_from(OutboxEvent)
                                .where(
                                    OutboxEvent.published_at.is_(None),
                                    OutboxEvent.failed_at.is_(None),
                                )
                            ),
                            "outbox_failed": session.scalar(
                                select(func.count())
                                .select_from(OutboxEvent)
                                .where(OutboxEvent.failed_at.is_not(None))
                            ),
                            "deliveries": dict(
                                session.execute(
                                    select(EmailDelivery.status, func.count()).group_by(
                                        EmailDelivery.status
                                    )
                                ).all()
                            ),
                        }
                    )
                )
            return
        if args.action in {"retry-outbox", "retry-delivery"}:
            from uuid import UUID

            if not args.event_id:
                parser.error("--event-id is required")
            event_id = UUID(args.event_id)
            if reset_failed(sessions, args.action, event_id) != 1:
                raise SystemExit("No matching failed record or expired lease; nothing changed")
            print("Failed record reset; delivery replay also requires replay-dlq")
            return
        queue = get_local_queue(settings)
        if args.action == "health":
            if not args.role:
                parser.error("--role is required")
            health(settings, sessions, queue, args.role)
            return
        if args.action == "replay-dlq":
            dlq = get_local_queue(settings, DLQ_NAME)
            replayed = 0
            for message in dlq.receive(wait=0):
                queue.publish(message["Body"])
                dlq.acknowledge(message["ReceiptHandle"])
                replayed += 1
            print(f"Replayed {replayed} messages; duplicates remain safe")
            return
        stopping = Event()
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, lambda *_: stopping.set())
        sender = LocalSmtpSender(settings)
        while not stopping.is_set():
            try:
                if args.action == "relay":
                    publish_batch(sessions, queue, limit=5)
                else:
                    consume_once(sessions, queue, sender)
                Path(f"/tmp/labpass-{args.action}-heartbeat").touch()  # nosec B108
            except Exception as exc:
                logger.error(
                    json.dumps(
                        {
                            "event": "background_iteration_failed",
                            "role": args.action,
                            "error_type": type(exc).__name__,
                        }
                    )
                )
                if args.once:
                    raise SystemExit(
                        "Background iteration failed; inspect sanitized logs"
                    ) from None
            if args.once:
                return
            stopping.wait(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
