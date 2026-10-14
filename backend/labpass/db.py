from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_engine(url: str, *, pool_size: int = 10, max_overflow: int = 10):
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=15,
        isolation_level="READ COMMITTED",
        connect_args={
            "connect_timeout": 5,
            "options": "-c lock_timeout=10000 -c statement_timeout=15000",
        },
    )


def make_sessions(engine):
    return sessionmaker(engine, expire_on_commit=False)
