"""Seed a local workshop first; exercises real auth and creates/cancels a booking."""

import json
import os
import secrets
import time
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener
from uuid import uuid4

BASE_URL = f"http://127.0.0.1:{int(os.environ.get('LABPASS_PORT', '8000'))}"
WORKSHOP_ID = "00000000-0000-0000-0000-000000000020"
OPENER = build_opener(HTTPCookieProcessor(CookieJar()))
CSRF_TOKEN = None


def request(method, path, body=None, key=None, expected=200, *, timeout=10):
    headers = {"Origin": BASE_URL}
    if CSRF_TOKEN is not None:
        headers["X-CSRF-Token"] = CSRF_TOKEN
    if body is not None:
        headers["Content-Type"] = "application/json"
    if key is not None:
        headers["Idempotency-Key"] = key
    req = Request(
        BASE_URL + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers=headers,
    )
    try:
        response = OPENER.open(req, timeout=timeout)
    except HTTPError as exc:
        if exc.code != expected:
            exc.close()
            raise
        response = exc
    with response:
        assert response.status == expected, f"{method} {path}: HTTP {response.status}"
        assert response.headers["X-Request-ID"]
        assert response.headers["Cache-Control"] == "no-store"
        return json.load(response) if response.status != 204 else None


def wait_until_ready(timeout=30):
    """Retry only the readiness GET while the API starts, within a fixed deadline."""
    deadline = time.monotonic() + timeout
    last_error = None
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            result = request("GET", "/api/health/ready", timeout=min(2, remaining))
        except HTTPError as exc:
            if exc.code != 503:
                raise
            last_error = exc
        except (ConnectionError, TimeoutError, URLError) as exc:
            last_error = exc
        else:
            assert result == {"status": "ok"}, (
                f"Unexpected readiness response: {result!r}"
            )
            return
        time.sleep(min(0.25, max(0, deadline - time.monotonic())))
    raise TimeoutError(
        f"API not ready at {BASE_URL} after {timeout}s (last error: {last_error}). "
        "Inspect 'docker compose logs api migrate'."
    ) from last_error


def main():
    global CSRF_TOKEN
    try:
        wait_until_ready()
    except TimeoutError as exc:
        raise SystemExit(str(exc)) from None
    credentials = {
        "email": f"smoke-{uuid4().hex}@example.test",
        "password": secrets.token_urlsafe(24),
    }
    user = request("POST", "/api/auth/register", credentials, expected=201)
    assert not user["is_admin"]
    signed = request("POST", "/api/auth/login", credentials)
    CSRF_TOKEN = signed["csrf_token"]
    assert request("GET", "/api/auth/me") == signed
    before = request("GET", f"/api/workshops/{WORKSHOP_ID}")["available"]
    assert before > 0, "Seeded workshop has no free seats"
    key = str(uuid4())
    body = {"workshop_id": WORKSHOP_ID}
    booking = request("POST", "/api/bookings", body, key)
    assert booking["status"] == "active"
    assert request("POST", "/api/bookings", body, key) == booking
    assert request("GET", f"/api/workshops/{WORKSHOP_ID}")["available"] == before - 1
    assert any(row["id"] == booking["id"] for row in request("GET", "/api/bookings"))
    cancel_path = f"/api/bookings/{booking['id']}/cancel"
    cancelled = request("POST", cancel_path)
    assert cancelled["status"] == "cancelled"
    assert request("POST", cancel_path) == cancelled
    assert request("POST", "/api/bookings", body, key) == cancelled
    assert request("GET", f"/api/workshops/{WORKSHOP_ID}")["available"] == before
    request("POST", "/api/auth/logout", expected=204)
    assert (
        request("GET", "/api/auth/me", expected=401)["detail"]
        == "authentication_required"
    )
    print(
        "HTTP smoke passed: register, login, me, booking, retry, history, cancellation, logout"
    )


if __name__ == "__main__":
    main()
