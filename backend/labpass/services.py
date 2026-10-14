"""Caller owns the transaction; lock order is user, workshop, booking.

The user lock serializes scoped idempotency keys even across different workshops.
The workshop lock serializes inventory changes across users and processes.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from labpass.models import Booking, IdempotencyRecord, OutboxEvent, User, Workshop
from labpass.rules import DomainError, require_capacity, require_seat


def lock_user(session: Session, user_id: UUID) -> User:
    user = session.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise DomainError(401, "unknown_user")
    return user


def lock_workshop(session: Session, workshop_id: UUID) -> Workshop:
    workshop = session.scalar(select(Workshop).where(Workshop.id == workshop_id).with_for_update())
    if workshop is None:
        raise DomainError(404, "workshop_not_found")
    return workshop


def create_booking(session: Session, user_id: UUID, workshop_id: UUID, key: str) -> Booking:
    user = lock_user(session, user_id)
    payload = {"operation": "create_booking", "workshop_id": str(workshop_id)}
    previous = session.get(IdempotencyRecord, (user_id, key))
    if previous is not None:
        if previous.payload != payload:
            raise DomainError(409, "idempotency_payload_mismatch")
        # A cancelled booking stays cancelled on retry; a retry never reserves again.
        return session.get(Booking, previous.booking_id)

    workshop = lock_workshop(session, workshop_id)
    active = session.scalar(
        select(Booking.id).where(
            Booking.user_id == user_id,
            Booking.workshop_id == workshop_id,
            Booking.status == "active",
        )
    )
    if active is not None:
        raise DomainError(409, "already_booked")
    require_seat(workshop.capacity, workshop.reserved)

    booking = Booking(id=uuid4(), user_id=user_id, workshop_id=workshop_id, status="active")
    workshop.reserved += 1
    session.add(booking)
    session.flush()  # Establish booking FK before idempotency/outbox inserts.
    session.add(IdempotencyRecord(user_id=user_id, key=key, payload=payload, booking_id=booking.id))
    session.add(
        OutboxEvent(
            id=uuid4(),
            booking_id=booking.id,
            event_type="booking.confirmed.v1",
            payload={
                "booking_id": str(booking.id),
                "user_id": str(user.id),
                "workshop_id": str(workshop.id),
                "recipient": user.email,
                "workshop_title": workshop.title,
            },
        )
    )
    session.flush()
    return booking


def cancel_booking(session: Session, user_id: UUID, booking_id: UUID) -> Booking:
    lock_user(session, user_id)
    # Read only the workshop ID before its lock, avoiding stale ORM booking state.
    workshop_id = session.scalar(
        select(Booking.workshop_id).where(Booking.id == booking_id, Booking.user_id == user_id)
    )
    if workshop_id is None:
        raise DomainError(404, "booking_not_found")
    workshop = lock_workshop(session, workshop_id)
    booking = session.scalar(select(Booking).where(Booking.id == booking_id).with_for_update())
    if booking.status == "active":
        booking.status = "cancelled"
        booking.cancelled_at = datetime.now(UTC)
        workshop.reserved -= 1
        session.flush()
    return booking


def change_capacity(session: Session, user_id: UUID, workshop_id: UUID, capacity: int) -> Workshop:
    user = lock_user(session, user_id)
    if not user.is_admin:
        raise DomainError(403, "admin_required")
    workshop = lock_workshop(session, workshop_id)
    require_capacity(capacity, workshop.reserved)
    workshop.capacity = capacity
    session.flush()
    return workshop
