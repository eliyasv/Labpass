import json
import logging
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.orm import Session

from labpass.auth import csrf_token


def identity(user, data):
    token = data["tokens"].get(user, "x" * 43)
    return {
        "Cookie": f"labpass_session={token}",
        "X-CSRF-Token": csrf_token(token),
        "Origin": "http://127.0.0.1:8000",
    }


def book(client, data, user=None, key="first-key", **extra):
    return client.post(
        "/api/bookings",
        headers={**identity(user or data["users"][0], data), "Idempotency-Key": key},
        json={"workshop_id": str(data["workshop"]), **extra},
    )


def test_booking_http_flow(client, data):
    assert client.get("/api/health/live").status_code == 200
    assert client.get("/api/health/ready").status_code == 200
    available = client.get(f"/api/workshops/{data['workshop']}").json()["available"]
    assert available == 20
    response = book(client, data)
    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    booking = response.json()
    assert booking["status"] == "active"
    assert book(client, data).json() == booking
    assert book(client, data, key="other-key").json()["detail"] == "already_booked"
    history = client.get("/api/bookings", headers=identity(data["users"][0], data)).json()
    assert history == [booking]
    for _ in range(2):
        response = client.post(
            f"/api/bookings/{booking['id']}/cancel", headers=identity(data["users"][0], data)
        )
        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"
    assert client.get(f"/api/workshops/{data['workshop']}").json()["available"] == 20
    assert book(client, data).json()["status"] == "cancelled"


def test_authenticated_identity_and_ownership(client, data):
    response = client.post(
        "/api/bookings",
        headers={"Idempotency-Key": "first-key"},
        json={"workshop_id": str(data["workshop"])},
    )
    assert response.status_code == 401
    assert book(client, data, user=uuid4()).status_code == 401
    booking = book(client, data).json()
    other = identity(data["users"][1], data)
    assert client.post(f"/api/bookings/{booking['id']}/cancel", headers=other).status_code == 404
    assert client.get("/api/bookings", headers=other).json() == []
    assert (
        client.patch(
            f"/api/admin/workshops/{data['workshop']}/capacity",
            headers=other,
            json={"capacity": 100},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/admin/workshops", headers=other, json={"title": "Cloud", "capacity": 10}
        ).status_code
        == 403
    )


def test_legacy_identity_header_cannot_authenticate(client, data):
    response = client.post(
        "/api/bookings",
        headers={"X-User-ID": str(data["admin"]), "Idempotency-Key": "first-key"},
        json={"workshop_id": str(data["workshop"])},
    )
    assert response.status_code == 401


def test_admin_capacity_and_creation(client, data):
    admin = identity(data["admin"], data)
    assert book(client, data).status_code == 200
    url = f"/api/admin/workshops/{data['workshop']}/capacity"
    assert client.patch(url, headers=admin, json={"capacity": 0}).status_code == 409
    assert client.patch(url, headers=admin, json={"capacity": 1}).json()["available"] == 0
    assert book(client, data, user=data["users"][1]).status_code == 409
    assert client.patch(url, headers=admin, json={"capacity": 2}).status_code == 200
    assert book(client, data, user=data["users"][1]).status_code == 200
    new = client.post(
        "/api/admin/workshops", headers=admin, json={"title": "  Kubernetes  ", "capacity": 0}
    )
    assert new.status_code == 201 and new.json()["title"] == "Kubernetes"


def test_request_validation(client, data):
    admin = identity(data["admin"], data)
    for capacity in (-1, 1.5, True, "2", 1_000_001):
        assert (
            client.patch(
                f"/api/admin/workshops/{data['workshop']}/capacity",
                headers=admin,
                json={"capacity": capacity},
            ).status_code
            == 422
        )
    assert (
        client.post(
            "/api/admin/workshops", headers=admin, json={"title": " ", "capacity": 2}
        ).status_code
        == 422
    )
    assert book(client, data, unexpected=True).status_code == 422
    assert book(client, data, key="short").status_code == 422
    assert client.get("/api/workshops?limit=101").status_code == 422
    assert client.get("/api/workshops?offset=-1").status_code == 422
    assert client.get("/api/workshops/not-a-uuid").status_code == 422
    assert client.get(f"/api/workshops/{uuid4()}").status_code == 404


@pytest.mark.parametrize(
    "error_type,status,detail",
    [
        (OperationalError, 503, "database_unavailable_retry_same_key"),
        (PoolTimeoutError, 503, "database_unavailable_retry_same_key"),
        (IntegrityError, 500, "database_error"),
    ],
)
def test_commit_failure_returns_error_and_retry_is_safe(
    client, data, sessions, caplog, error_type, status, detail
):
    from test_bookings import counts

    caplog.set_level(logging.INFO, logger="labpass")

    def fail_commit(session):
        if error_type is PoolTimeoutError:
            raise error_type("must-not-log")
        raise error_type("hidden SQL", {"secret": "must-not-log"}, Exception("commit failed"))

    event.listen(Session, "before_commit", fail_commit)
    try:
        response = book(client, data)
    finally:
        event.remove(Session, "before_commit", fail_commit)
    assert response.status_code == status
    assert response.json() == {"detail": detail}
    assert "must-not-log" not in caplog.text
    assert "hidden SQL" not in response.text
    assert counts(sessions, data["workshop"]) == (0, 0, 0)
    assert book(client, data).status_code == 200
    assert counts(sessions, data["workshop"]) == (1, 1, 1)


def test_structured_logs_include_ids_without_payloads(client, data, caplog):
    caplog.set_level(logging.INFO, logger="labpass")
    response = book(client, data)
    assert response.status_code == 200
    records = [json.loads(record.message) for record in caplog.records if record.name == "labpass"]
    committed = next(row for row in records if row["event"] == "booking_request_committed")
    assert committed["request_id"] == response.headers["X-Request-ID"]
    assert committed["booking_id"] == response.json()["id"]
    assert committed["event_id"] != "None"
    assert "user-0@example.test" not in caplog.text
    assert "first-key" not in caplog.text
