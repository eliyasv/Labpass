from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    __table_args__ = (Index("users_email_case_insensitive", func.lower(email), unique=True),)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="auth_sessions_lifetime_positive"),
        Index("auth_sessions_user", "user_id"),
        Index("auth_sessions_expiry", "expires_at"),
    )
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Workshop(Base):
    __tablename__ = "workshops"
    __table_args__ = (
        CheckConstraint("capacity >= 0", name="workshops_capacity_nonnegative"),
        CheckConstraint(
            "reserved >= 0 AND reserved <= capacity", name="workshops_inventory_bounds"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(200))
    capacity: Mapped[int] = mapped_column(Integer)
    reserved: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'cancelled')", name="bookings_status_valid"),
        CheckConstraint(
            "(status = 'active' AND cancelled_at IS NULL) OR "
            "(status = 'cancelled' AND cancelled_at IS NOT NULL)",
            name="bookings_cancellation_consistent",
        ),
        Index(
            "bookings_one_active_per_user_workshop",
            "user_id",
            "workshop_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index("bookings_workshop_status", "workshop_id", "status"),
        Index("bookings_user_created", "user_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    workshop_id: Mapped[UUID] = mapped_column(ForeignKey("workshops.id"))
    status: Mapped[str] = mapped_column(String(16), server_default=text("'active'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    booking_id: Mapped[UUID] = mapped_column(ForeignKey("bookings.id"))


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("booking_id", "event_type", name="outbox_booking_event_unique"),
        Index(
            "outbox_unpublished_created",
            "created_at",
            postgresql_where=text("published_at IS NULL"),
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    booking_id: Mapped[UUID] = mapped_column(ForeignKey("bookings.id"))
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publish_attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))


class EmailDelivery(Base):
    __tablename__ = "email_deliveries"
    __table_args__ = (
        CheckConstraint("attempts >= 0", name="email_deliveries_attempts_nonnegative"),
        CheckConstraint(
            "(status = 'sending' AND lease_token IS NOT NULL AND lease_until IS NOT NULL "
            "AND completed_at IS NULL) OR "
            "(status = 'retry' AND lease_token IS NULL AND lease_until IS NULL "
            "AND completed_at IS NULL) OR "
            "(status IN ('sent', 'skipped', 'failed') AND lease_token IS NULL "
            "AND lease_until IS NULL AND completed_at IS NOT NULL)",
            name="email_deliveries_state_consistent",
        ),
    )
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("outbox_events.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(16), server_default=text("'retry'"))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    lease_token: Mapped[UUID | None]
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
