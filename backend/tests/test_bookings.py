from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import IntegrityError

from labpass.models import Booking, IdempotencyRecord, OutboxEvent, Workshop
from labpass.rules import DomainError
from labpass.services import cancel_booking, change_capacity, create_booking


def counts(sessions, workshop_id):
    with sessions() as session:
        workshop = session.get(Workshop, workshop_id)
        active = session.scalar(
            select(func.count())
            .select_from(Booking)
            .where(Booking.workshop_id == workshop_id, Booking.status == "active")
        )
        events = session.scalar(select(func.count()).select_from(OutboxEvent))
        keys = session.scalar(select(func.count()).select_from(IdempotencyRecord))
        assert workshop.reserved == active
        assert 0 <= active <= workshop.capacity
        return active, events, keys


def attempt(sessions, user, workshop, key):
    try:
        with sessions.begin() as session:
            return create_booking(session, user, workshop, key).id
    except DomainError as exc:
        return exc.code


def test_100_distinct_users_compete_for_20_seats(engine, sessions, data):
    barrier = Barrier(101, timeout=20)

    def worker(i):
        with sessions.begin() as session:
            session.execute(text("SELECT 1"))  # Check out a distinct live connection first.
            barrier.wait()
            try:
                return create_booking(
                    session, data["users"][i], data["workshop"], f"load-{i:04d}"
                ).id
            except DomainError as exc:
                return exc.code

    # Hold inventory until all 100 workers demonstrably wait on database locks.
    with ThreadPoolExecutor(max_workers=100) as executor:
        with sessions.begin() as holder:
            holder.execute(
                select(Workshop).where(Workshop.id == data["workshop"]).with_for_update()
            )
            futures = [executor.submit(worker, i) for i in range(100)]
            barrier.wait()
            deadline = monotonic() + 15
            waiting = 0
            while monotonic() < deadline:
                with engine.connect() as observer:
                    waiting = observer.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE application_name = current_setting('application_name') "
                            "AND wait_event_type = 'Lock'"
                        )
                    )
                if waiting == 100:
                    break
                sleep(0.02)
            assert waiting == 100, f"Expected 100 overlapping lock waiters, observed {waiting}"
        results = [future.result(timeout=30) for future in futures]
    assert sum(not isinstance(result, str) for result in results) == 20
    assert results.count("workshop_full") == 80
    assert counts(sessions, data["workshop"]) == (20, 20, 20)


def race(sessions, actions):
    barrier = Barrier(len(actions), timeout=15)

    def worker(action):
        with sessions.begin() as session:
            session.execute(text("SELECT 1"))
            barrier.wait()
            try:
                return action(session)
            except DomainError as exc:
                return exc.code

    with ThreadPoolExecutor(max_workers=len(actions)) as executor:
        return list(executor.map(worker, actions))


def test_simultaneous_identical_retries(sessions, data):
    def action(session):
        return create_booking(session, data["users"][0], data["workshop"], "same-key").id

    results = race(sessions, [action] * 12)
    assert len(set(results)) == 1
    assert counts(sessions, data["workshop"]) == (1, 1, 1)


def test_simultaneous_different_keys_one_active_booking(sessions, data):
    results = race(
        sessions,
        [
            lambda session, i=i: (
                create_booking(session, data["users"][0], data["workshop"], f"unique-{i:04d}").id
            )
            for i in range(12)
        ],
    )
    assert results.count("already_booked") == 11
    assert counts(sessions, data["workshop"]) == (1, 1, 1)


def test_key_payload_and_user_scope(sessions, data):
    user = data["users"][0]
    original = attempt(sessions, user, data["workshop"], "shared-key")
    assert attempt(sessions, user, data["workshop"], "shared-key") == original
    assert attempt(sessions, user, data["other"], "shared-key") == "idempotency_payload_mismatch"
    other_user = attempt(sessions, data["users"][1], data["workshop"], "shared-key")
    assert other_user != original
    assert counts(sessions, data["workshop"]) == (2, 2, 2)


def test_simultaneous_key_reuse_different_payload(sessions, data):
    results = race(
        sessions,
        [
            lambda session, workshop=workshop: (
                create_booking(session, data["users"][0], workshop, "shared-key").id
            )
            for workshop in (data["workshop"], data["other"])
        ],
    )
    assert results.count("idempotency_payload_mismatch") == 1
    assert sum(counts(sessions, w)[0] for w in (data["workshop"], data["other"])) == 1


def test_cancellation_retries_and_rebooking(sessions, data):
    user, workshop = data["users"][0], data["workshop"]
    original = attempt(sessions, user, workshop, "first-key")
    results = race(sessions, [lambda session: cancel_booking(session, user, original).status] * 12)
    assert results == ["cancelled"] * 12
    assert counts(sessions, workshop) == (0, 1, 1)
    with sessions.begin() as session:
        replay = create_booking(session, user, workshop, "first-key")
        assert replay.id == original and replay.status == "cancelled"
    assert counts(sessions, workshop) == (0, 1, 1)
    assert attempt(sessions, user, workshop, "second-key") != original
    assert counts(sessions, workshop) == (1, 2, 2)


def test_booking_cancellation_race(sessions, data):
    user, workshop = data["users"][0], data["workshop"]
    original = attempt(sessions, user, workshop, "first-key")
    results = race(
        sessions,
        [
            lambda session: cancel_booking(session, user, original).status,
            lambda session: create_booking(session, user, workshop, "second-key").id,
        ],
    )
    assert results[0] == "cancelled"
    active, events, keys = counts(sessions, workshop)
    if results[1] == "already_booked":
        assert (active, events, keys) == (0, 1, 1)
    else:
        assert (active, events, keys) == (1, 2, 2)


def test_capacity_change_race(sessions, data):
    with sessions.begin() as session:
        change_capacity(session, data["admin"], data["workshop"], 1)
    results = race(
        sessions,
        [
            lambda session: change_capacity(session, data["admin"], data["workshop"], 0).capacity,
            lambda session: (
                create_booking(session, data["users"][0], data["workshop"], "first-key").id
            ),
        ],
    )
    if results[0] == 0:
        assert results[1] == "workshop_full"
        assert counts(sessions, data["workshop"]) == (0, 0, 0)
    else:
        assert results[0] == "capacity_below_reservations"
        assert counts(sessions, data["workshop"]) == (1, 1, 1)


def test_outbox_insert_failure_rolls_back_everything(engine, sessions, data):
    def fail_outbox(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO outbox_events"):
            raise RuntimeError("simulated outbox persistence failure")

    event.listen(engine, "before_cursor_execute", fail_outbox)
    try:
        with pytest.raises(RuntimeError, match="outbox persistence failure"):
            with sessions.begin() as session:
                create_booking(session, data["users"][0], data["workshop"], "first-key")
    finally:
        event.remove(engine, "before_cursor_execute", fail_outbox)
    assert counts(sessions, data["workshop"]) == (0, 0, 0)
    assert not isinstance(attempt(sessions, data["users"][0], data["workshop"], "first-key"), str)


def test_database_constraints(sessions, data):
    original = attempt(sessions, data["users"][0], data["workshop"], "first-key")
    with pytest.raises(IntegrityError):
        with sessions.begin() as session:
            session.add(
                Booking(
                    id=uuid4(),
                    user_id=data["users"][0],
                    workshop_id=data["workshop"],
                    status="active",
                )
            )
    with pytest.raises(IntegrityError):
        with sessions.begin() as session:
            session.get(Workshop, data["workshop"]).capacity = 0
    with sessions() as session:
        assert session.get(Booking, original).status == "active"
    assert counts(sessions, data["workshop"]) == (1, 1, 1)


def test_missing_workshop_does_not_consume_key(sessions, data):
    assert attempt(sessions, data["users"][0], uuid4(), "first-key") == "workshop_not_found"
    assert counts(sessions, data["workshop"]) == (0, 0, 0)
