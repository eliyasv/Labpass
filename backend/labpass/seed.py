"""Idempotent development fixtures; never executed at application startup."""

from uuid import UUID

from labpass.config import Settings
from labpass.db import make_engine, make_sessions
from labpass.models import Workshop

WORKSHOP_ID = UUID("00000000-0000-0000-0000-000000000020")


def main():
    settings = Settings.from_env()
    if settings.cookie_secure:
        raise RuntimeError("Demo seed is restricted to loopback development configuration")
    engine = make_engine(settings.database_url)
    try:
        with make_sessions(engine).begin() as session:
            if session.get(Workshop, WORKSHOP_ID) is None:
                session.add(
                    Workshop(id=WORKSHOP_ID, title="AWS and DevOps foundations", capacity=20)
                )
        print(f"workshop={WORKSHOP_ID}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
