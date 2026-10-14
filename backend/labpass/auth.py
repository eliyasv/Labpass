"""Opaque server sessions. Store hashes, never raw session cookies."""

import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from threading import BoundedSemaphore
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from labpass.models import AuthSession, User
from labpass.rules import DomainError

# Explicit argon2-cffi defaults: 64 MiB, 3 iterations, 4 lanes, Argon2id.
HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
HASH_SLOTS = BoundedSemaphore(2)  # Bound concurrent password work per process.
DUMMY_HASH = HASHER.hash(secrets.token_urlsafe(32))
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


def hash_password(password: str) -> str:
    if not HASH_SLOTS.acquire(blocking=False):
        raise DomainError(503, "authentication_busy")
    try:
        return HASHER.hash(password)
    finally:
        HASH_SLOTS.release()


def verify_password(encoded: str | None, password: str) -> bool:
    if not HASH_SLOTS.acquire(blocking=False):
        raise DomainError(503, "authentication_busy")
    try:
        try:
            valid = HASHER.verify(encoded or DUMMY_HASH, password)
            return encoded is not None and valid
        except VerificationError, InvalidHashError:
            return False
    finally:
        HASH_SLOTS.release()


def token_hash(token: str) -> str:
    return sha256(token.encode("ascii")).hexdigest()


def csrf_token(token: str) -> str:
    # Cookie secret is the HMAC key; database token digests cannot derive this value.
    return hmac.new(token.encode("ascii"), b"labpass-csrf-v1", sha256).hexdigest()


def valid_token(token: str | None) -> bool:
    return token is not None and TOKEN_PATTERN.fullmatch(token) is not None


def require_csrf(token: str, supplied: str | None):
    if (
        not supplied
        or not supplied.isascii()
        or not secrets.compare_digest(csrf_token(token), supplied)
    ):
        raise DomainError(403, "csrf_invalid")


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    email: str
    is_admin: bool
    expires_at: datetime


def authenticate(session: Session, token: str | None) -> Principal:
    if not valid_token(token):
        raise DomainError(401, "authentication_required")
    row = session.execute(
        select(User, AuthSession.expires_at)
        .join(AuthSession, AuthSession.user_id == User.id)
        .where(AuthSession.token_hash == token_hash(token), AuthSession.expires_at > func.now())
    ).first()
    if row is None:
        raise DomainError(401, "authentication_required")
    user, expires_at = row
    return Principal(user.id, user.email, user.is_admin, expires_at)


def register(session: Session, email: str, encoded_password: str) -> User:
    user = session.scalar(
        insert(User)
        .values(email=email, password_hash=encoded_password, is_admin=False)
        .on_conflict_do_nothing()
        .returning(User)
    )
    if user is None:
        raise DomainError(409, "registration_conflict")
    return user


def login(session: Session, email: str, password: str, previous_token: str | None, ttl: int):
    user = session.scalar(select(User).where(func.lower(User.email) == email))
    encoded = user.password_hash if user is not None else None
    if not verify_password(encoded, password):
        raise DomainError(401, "invalid_credentials")
    if HASHER.check_needs_rehash(encoded):
        session.execute(
            update(User)
            .where(User.id == user.id, User.password_hash == encoded)
            .values(password_hash=hash_password(password))
        )
    if valid_token(previous_token):
        session.execute(
            delete(AuthSession).where(AuthSession.token_hash == token_hash(previous_token))
        )
    # Clear this user's expired sessions opportunistically, without touching active devices.
    session.execute(
        delete(AuthSession).where(
            AuthSession.user_id == user.id, AuthSession.expires_at <= func.now()
        )
    )
    token = secrets.token_urlsafe(32)
    now = session.scalar(select(func.now()))
    expiry = now + timedelta(seconds=ttl)
    session.add(
        AuthSession(
            token_hash=token_hash(token), user_id=user.id, created_at=now, expires_at=expiry
        )
    )
    session.flush()
    return user, token, expiry


def logout(session: Session, token: str | None):
    if valid_token(token):
        session.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(token)))
