import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from conftest import TEST_ORIGIN, TEST_PASSWORD
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_api import identity

from labpass.app import create_app
from labpass.auth import HASH_SLOTS, HASHER, hash_password, register, token_hash
from labpass.config import Settings
from labpass.create_admin import provision_admin
from labpass.models import AuthSession, User
from labpass.rules import DomainError


def sign_in(client, email="user-0@example.test", password=TEST_PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_registration_login_me_logout(client, sessions, caplog):
    caplog.set_level(logging.INFO, logger="labpass")
    body = {"email": "NewUser@Example.test", "password": TEST_PASSWORD}
    registered = client.post("/api/auth/register", json=body)
    assert registered.status_code == 201
    assert registered.json()["email"] == "newuser@example.test"
    assert registered.json()["is_admin"] is False
    assert "password" not in registered.text
    assert client.get("/api/auth/me").status_code == 401  # Registration is not auto-login.
    with sessions() as session:
        user = session.get(User, registered.json()["id"])
        assert user.password_hash.startswith("$argon2id$")
        assert user.password_hash != TEST_PASSWORD
        assert HASHER.verify(user.password_hash, TEST_PASSWORD)
    response = sign_in(client, body["email"])
    assert response.status_code == 200
    token = client.cookies.get("labpass_session")
    csrf = response.json()["csrf_token"]
    assert token not in response.text and response.headers["Cache-Control"] == "no-store"
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    assert "Max-Age=28800" in cookie and "Domain=" not in cookie
    assert client.get("/api/auth/me").json() == response.json()
    with sessions() as session:
        stored = session.scalar(select(AuthSession))
        assert stored.token_hash == token_hash(token) and stored.token_hash != token
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/logout").status_code == 204
    assert (
        client.get("/api/auth/me", headers={"Cookie": f"labpass_session={token}"}).status_code
        == 401
    )
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(AuthSession)) == 0
    assert TEST_PASSWORD not in caplog.text and token not in caplog.text and csrf not in caplog.text


def test_duplicate_registration_and_no_public_admin(client, data):
    body = {"email": "USER-0@example.test", "password": TEST_PASSWORD}
    assert client.post("/api/auth/register", json=body).status_code == 409
    assert client.post("/api/auth/register", json={**body, "is_admin": True}).status_code == 422
    assert (
        client.post("/api/auth/register", json={**body, "user_id": str(data["admin"])}).status_code
        == 422
    )


def test_invalid_credentials_are_generic_and_do_not_create_sessions(client, sessions, data):
    for email, password in (
        ("user-0@example.test", "wrong-password"),
        ("missing@example.test", TEST_PASSWORD),
    ):
        response = sign_in(client, email, password)
        assert response.status_code == 401
        assert response.json() == {"detail": "invalid_credentials"}
        assert "Set-Cookie" not in response.headers
    with sessions.begin() as session:
        session.get(User, data["users"][0]).password_hash = None
    assert sign_in(client).json() == {"detail": "invalid_credentials"}
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(AuthSession)) == 101


def test_login_rotates_current_session_and_csrf(client, data):
    first = sign_in(client)
    old = client.cookies.get("labpass_session")
    second = sign_in(client)
    assert first.status_code == second.status_code == 200
    assert client.cookies.get("labpass_session") != old
    assert first.json()["csrf_token"] != second.json()["csrf_token"]
    assert (
        client.get("/api/auth/me", headers={"Cookie": f"labpass_session={old}"}).status_code == 401
    )
    response = client.post(
        "/api/bookings",
        json={"workshop_id": str(data["workshop"])},
        headers={"Idempotency-Key": "first-key", "X-CSRF-Token": first.json()["csrf_token"]},
    )
    assert response.status_code == 403


def test_expiry_is_enforced_server_side(client, sessions, data):
    token = data["tokens"][data["users"][0]]
    with sessions.begin() as session:
        stored = session.get(AuthSession, token_hash(token))
        stored.created_at = datetime.now(UTC) - timedelta(hours=2)
        stored.expires_at = datetime.now(UTC) - timedelta(hours=1)
    assert client.get("/api/auth/me", headers=identity(data["users"][0], data)).status_code == 401
    # Expired sessions can still be explicitly cleared; retries remain harmless.
    assert (
        client.post("/api/auth/logout", headers=identity(data["users"][0], data)).status_code == 204
    )


@pytest.mark.parametrize("token", ["short", "x" * 43, "x" * 1000, "!" * 43])
def test_forged_sessions_are_rejected(client, token):
    assert (
        client.get("/api/auth/me", headers={"Cookie": f"labpass_session={token}"}).status_code
        == 401
    )


@pytest.mark.parametrize("origin", [None, "null", "https://evil.example", TEST_ORIGIN + ".evil"])
def test_origin_rejection_for_credential_endpoints(client, origin):
    client.headers.pop("Origin")
    headers = {} if origin is None else {"Origin": origin}
    for path in ("/api/auth/register", "/api/auth/login"):
        response = client.post(
            path, headers=headers, json={"email": "new@example.test", "password": TEST_PASSWORD}
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "origin_not_allowed"


def test_csrf_and_cross_site_rejection(client, data):
    credentials = identity(data["users"][0], data)
    body = {"workshop_id": str(data["workshop"])}
    headers = {"Cookie": credentials["Cookie"], "Idempotency-Key": "first-key"}
    assert client.post("/api/bookings", headers=headers, json=body).status_code == 403
    headers["X-CSRF-Token"] = "wrong"
    assert client.post("/api/bookings", headers=headers, json=body).status_code == 403
    headers["X-CSRF-Token"] = credentials["X-CSRF-Token"]
    headers["Sec-Fetch-Site"] = "cross-site"
    assert client.post("/api/bookings", headers=headers, json=body).status_code == 403
    headers.pop("Sec-Fetch-Site")
    assert client.post("/api/bookings", headers=headers, json=body).status_code == 200
    assert (
        client.post("/api/auth/logout", headers={"Cookie": credentials["Cookie"]}).status_code
        == 403
    )
    assert client.get("/api/auth/me", headers=credentials).status_code == 200


def test_real_logins_cannot_impersonate_other_user(client, engine, data):
    first = sign_in(client)
    assert first.status_code == 200
    booked = client.post(
        "/api/bookings",
        json={"workshop_id": str(data["workshop"])},
        headers={
            "Idempotency-Key": "first-key",
            "X-CSRF-Token": first.json()["csrf_token"],
            "X-User-ID": str(data["admin"]),
        },
    )
    assert booked.status_code == 200
    assert booked.json()["user_id"] == str(data["users"][0])
    with TestClient(
        create_app(Settings(str(engine.url), TEST_ORIGIN, False), engine=engine),
        base_url=TEST_ORIGIN,
        headers={"Origin": TEST_ORIGIN},
    ) as other:
        logged = sign_in(other, "user-1@example.test")
        assert logged.status_code == 200
        assert other.get("/api/bookings").json() == []
        headers = {"X-CSRF-Token": logged.json()["csrf_token"], "X-User-ID": str(data["admin"])}
        assert (
            other.post(f"/api/bookings/{booked.json()['id']}/cancel", headers=headers).status_code
            == 404
        )
        assert (
            other.post(
                "/api/admin/workshops", headers=headers, json={"title": "Cloud", "capacity": 2}
            ).status_code
            == 403
        )


def test_sessions_work_across_instances_and_roles_are_read_from_db(client, engine, sessions, data):
    response = sign_in(client, "admin@example.test")
    token = client.cookies.get("labpass_session")
    with TestClient(
        create_app(Settings(str(engine.url), TEST_ORIGIN, False), engine=engine),
        base_url=TEST_ORIGIN,
        headers={"Origin": TEST_ORIGIN},
    ) as other:
        headers = {
            "Cookie": f"labpass_session={token}",
            "X-CSRF-Token": response.json()["csrf_token"],
        }
        assert other.get("/api/auth/me", headers=headers).json()["user"]["is_admin"]
        with sessions.begin() as session:
            session.get(User, data["admin"]).is_admin = False
        assert not other.get("/api/auth/me", headers=headers).json()["user"]["is_admin"]
        assert (
            other.post(
                "/api/admin/workshops", headers=headers, json={"title": "Cloud", "capacity": 2}
            ).status_code
            == 403
        )


def test_secure_cookie_attributes(engine, sessions, data):
    origin = "https://labpass.example.com"
    with TestClient(
        create_app(Settings(str(engine.url), origin), engine=engine),
        base_url=origin,
        headers={"Origin": origin},
    ) as secure:
        response = sign_in(secure)
        assert response.status_code == 200
        cookie = response.headers["Set-Cookie"]
        assert cookie.startswith("__Host-labpass_session=")
        assert "Secure" in cookie and "HttpOnly" in cookie and "Domain=" not in cookie
        assert secure.get("/api/auth/me").status_code == 200


def test_sensitive_validation_inputs_are_not_echoed(client, caplog):
    caplog.set_level(logging.INFO, logger="labpass")
    for password in ("secret123", "s" * 129):
        response = client.post(
            "/api/auth/register", json={"email": "new@example.test", "password": password}
        )
        assert response.status_code == 422
        assert password not in response.text and password not in caplog.text
        assert "input" not in response.text


def test_login_commit_failure_does_not_issue_cookie(client, data):
    def fail_commit(session):
        raise OperationalError("hidden", {}, Exception("failure"))

    event.listen(Session, "before_commit", fail_commit)
    try:
        response = sign_in(client)
    finally:
        event.remove(Session, "before_commit", fail_commit)
    assert response.status_code == 503 and "Set-Cookie" not in response.headers
    assert sign_in(client).status_code == 200


def test_logout_failure_keeps_session_for_retry(client, data):
    signed = sign_in(client)
    token = client.cookies.get("labpass_session")

    def fail_commit(session):
        raise OperationalError("hidden", {}, Exception("failure"))

    event.listen(Session, "before_commit", fail_commit)
    try:
        response = client.post(
            "/api/auth/logout", headers={"X-CSRF-Token": signed.json()["csrf_token"]}
        )
    finally:
        event.remove(Session, "before_commit", fail_commit)
    assert response.status_code == 503 and "Set-Cookie" not in response.headers
    assert client.cookies.get("labpass_session") == token
    assert client.get("/api/auth/me").status_code == 200
    assert (
        client.post(
            "/api/auth/logout", headers={"X-CSRF-Token": signed.json()["csrf_token"]}
        ).status_code
        == 204
    )


def test_concurrent_registration_database_uniqueness(sessions, encoded_password):
    barrier = Barrier(2, timeout=10)

    def worker(email):
        try:
            with sessions.begin() as session:
                session.execute(text("SELECT 1"))
                barrier.wait()
                return register(session, email, encoded_password).id
        except DomainError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(worker, ["user@example.test", "USER@example.test"]))
    assert results.count("registration_conflict") == 1
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1


def test_admin_provisioning_refuses_existing_account(sessions, encoded_password, data):
    with sessions.begin() as session:
        new_id = provision_admin(session, "operator@example.test", encoded_password)
    with pytest.raises(DomainError, match="registration_conflict"):
        with sessions.begin() as session:
            provision_admin(session, "user-0@example.test", encoded_password)
    with sessions() as session:
        assert session.get(User, new_id).is_admin
        assert not session.get(User, data["users"][0]).is_admin


def test_password_rehash_upgrade(client, sessions, data):
    from argon2 import PasswordHasher

    old_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
    with sessions.begin() as session:
        session.get(User, data["users"][0]).password_hash = old_hasher.hash(TEST_PASSWORD)
    assert sign_in(client).status_code == 200
    with sessions() as session:
        encoded = session.get(User, data["users"][0]).password_hash
        assert HASHER.verify(encoded, TEST_PASSWORD) and not HASHER.check_needs_rehash(encoded)


def test_password_work_is_bounded():
    assert HASH_SLOTS.acquire(blocking=False)
    assert HASH_SLOTS.acquire(blocking=False)
    try:
        with pytest.raises(DomainError, match="authentication_busy"):
            hash_password(TEST_PASSWORD)
    finally:
        HASH_SLOTS.release()
        HASH_SLOTS.release()


def test_password_hashes_are_salted():
    assert hash_password(TEST_PASSWORD) != hash_password(TEST_PASSWORD)
