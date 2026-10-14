"""This milestone deliberately supports local queue/mail endpoints only."""

import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from sqlalchemy.engine import make_url


@dataclass(frozen=True)
class BackgroundSettings:
    database_url: str = field(repr=False)
    queue_endpoint: str
    smtp_host: str
    smtp_port: int = 1025

    def __post_init__(self):
        if make_url(self.database_url).drivername != "postgresql+psycopg":
            raise ValueError("Background tasks require PostgreSQL with psycopg")
        try:
            endpoint = urlsplit(self.queue_endpoint)
            valid = (
                endpoint.scheme == "http"
                and endpoint.hostname in {"queue", "127.0.0.1", "localhost", "::1"}
                and endpoint.port is not None
                and 1 <= endpoint.port <= 65535
                and not endpoint.username
                and not endpoint.password
                and endpoint.path in {"", "/"}
                and not endpoint.query
                and not endpoint.fragment
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("An explicit local SQS endpoint is required")
        if (
            self.smtp_host not in {"mailpit", "127.0.0.1", "localhost", "::1"}
            or not 1 <= self.smtp_port <= 65535
        ):
            raise ValueError("SMTP is restricted to the local mail capture service")

    @classmethod
    def from_env(cls):
        return cls(
            os.environ.get("DATABASE_URL", ""),
            os.environ.get("LABPASS_QUEUE_ENDPOINT", ""),
            os.environ.get("LABPASS_SMTP_HOST", ""),
            int(os.environ.get("LABPASS_SMTP_PORT", "1025")),
        )
