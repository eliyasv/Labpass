"""Run via Compose exec -T consumer python < scripts/smoke-background.py; no AWS calls."""

import json
import os
import secrets
import time
from http.cookiejar import CookieJar
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener
from uuid import uuid4

from labpass.background_config import BackgroundSettings
from labpass.config import Settings
from labpass.db import make_engine, make_sessions
from labpass.models import EmailDelivery, OutboxEvent
from labpass.outbox import Envelope
from labpass.queue import get_local_queue
from sqlalchemy import select

opener = build_opener(HTTPCookieProcessor(CookieJar()))
csrf = None


def request(method, path, body=None, *, key=None):
    headers = {"Origin": os.environ["APP_ORIGIN"]}
    if csrf:
        headers["X-CSRF-Token"] = csrf
    if key:
        headers["Idempotency-Key"] = key
    if body is not None:
        headers["Content-Type"] = "application/json"
    with opener.open(
        Request(
            "http://web:8080" + path,
            method=method,
            headers=headers,
            data=json.dumps(body).encode() if body is not None else None,
        ),
        timeout=10,
    ) as response:
        return json.load(response) if response.status != 204 else None


def main():
    global csrf
    credentials = {
        "email": f"email-smoke-{uuid4().hex}@example.test",
        "password": secrets.token_urlsafe(24),
    }
    request("POST", "/api/auth/register", credentials)
    csrf = request("POST", "/api/auth/login", credentials)["csrf_token"]
    workshops = request("GET", "/api/workshops")
    workshop = next((row for row in workshops if row["available"] > 0), None)
    assert workshop is not None, "Seed a workshop with an available seat first"
    booking = request(
        "POST", "/api/bookings", {"workshop_id": workshop["id"]}, key=str(uuid4())
    )
    engine = make_engine(Settings.from_env().database_url)
    sessions = make_sessions(engine)
    try:
        deadline = time.monotonic() + 30
        state = None
        while time.monotonic() < deadline:
            with sessions() as session:
                event = session.scalar(
                    select(OutboxEvent).where(OutboxEvent.booking_id == booking["id"])
                )
                delivery = session.get(EmailDelivery, event.id)
                if delivery:
                    state = delivery.status
                if event.published_at is not None and state == "sent":
                    break
            time.sleep(0.25)
        else:
            raise TimeoutError(
                f"Confirmation was not captured within 30s (state={state}); inspect relay/consumer logs"
            )
        query = urlencode({"query": booking["id"]})
        with opener.open(
            "http://mailpit:8025/api/v1/search?" + query, timeout=5
        ) as response:
            result = json.load(response)
        assert result["messages_count"] == 1 and len(result["messages"]) == 1, (
            "Expected one captured confirmation containing the booking reference"
        )
        assert result["messages"][0]["Subject"] == "Your LabPass reservation"
        queue = get_local_queue(BackgroundSettings.from_env())
        queue.publish(
            Envelope(event_id=event.id, event_type=event.event_type).model_dump_json()
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            counts = queue.client.get_queue_attributes(
                QueueUrl=queue.queue_url,
                AttributeNames=[
                    "ApproximateNumberOfMessages",
                    "ApproximateNumberOfMessagesNotVisible",
                ],
            )["Attributes"]
            if all(int(value) == 0 for value in counts.values()):
                break
            time.sleep(0.25)
        else:
            raise TimeoutError("Duplicate queue message was not acknowledged")
        with opener.open(
            "http://mailpit:8025/api/v1/search?" + query, timeout=5
        ) as response:
            assert json.load(response)["messages_count"] == 1, (
                "Duplicate delivery sent another email"
            )
        print(
            f"Background smoke passed: booking={booking['id']} event={event.id}; published, sent, captured once and duplicate suppressed"
        )
    finally:
        engine.dispose()
        request("POST", f"/api/bookings/{booking['id']}/cancel")
        request("POST", "/api/auth/logout")


if __name__ == "__main__":
    main()
