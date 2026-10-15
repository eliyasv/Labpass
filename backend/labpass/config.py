import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from sqlalchemy.engine import make_url

from labpass.cloud_database import CloudDatabaseSettings


@dataclass(frozen=True)
class Settings:
    database_url: str | None = field(repr=False)
    public_origin: str = "https://localhost"
    cookie_secure: bool = True
    session_ttl_seconds: int = 8 * 60 * 60
    cloud_database: CloudDatabaseSettings | None = None

    def __post_init__(self):
        if (self.database_url is None) == (self.cloud_database is None):
            raise RuntimeError("Configure exactly one database connection source")
        if (
            self.database_url is not None
            and make_url(self.database_url).drivername != "postgresql+psycopg"
        ):
            raise RuntimeError("DATABASE_URL must use postgresql+psycopg")
        if self.cloud_database is not None and not self.cookie_secure:
            raise RuntimeError("Cloud API requires Secure cookies")
        try:
            origin = urlsplit(self.public_origin)
            origin_port = origin.port
        except ValueError:
            raise RuntimeError("APP_ORIGIN contains an invalid host or port") from None
        if (
            origin.scheme not in {"http", "https"}
            or not origin.hostname
            or origin.username is not None
            or origin.password is not None
            or origin.path
            or origin.query
            or origin.fragment
            or (origin_port is not None and origin_port < 1)
        ):
            raise RuntimeError("APP_ORIGIN must be an HTTP(S) origin without a path or credentials")
        if self.cookie_secure and origin.scheme != "https":
            raise RuntimeError("Secure cookies require an HTTPS APP_ORIGIN")
        if not self.cookie_secure and origin.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise RuntimeError("Insecure cookies are restricted to loopback development")
        if self.session_ttl_seconds <= 0:
            raise RuntimeError("Session lifetime must be positive")

    @property
    def cookie_name(self):
        return "__Host-labpass_session" if self.cookie_secure else "labpass_session"

    @classmethod
    def from_env(cls):
        mode = os.environ.get("LABPASS_AWS_ENABLED", "false")
        if mode not in {"true", "false"}:
            raise RuntimeError("LABPASS_AWS_ENABLED must be true or false")
        url = os.environ.get("DATABASE_URL", "")
        cloud = None
        if mode == "true":
            if url:
                raise RuntimeError("Cloud API must not set DATABASE_URL")
            cloud = CloudDatabaseSettings.from_env()
        elif not url:
            raise RuntimeError("DATABASE_URL is required")
        # Validate the DB driver first, without echoing configuration values.
        if url and make_url(url).drivername != "postgresql+psycopg":
            raise RuntimeError("DATABASE_URL must use postgresql+psycopg")
        origin = os.environ.get("APP_ORIGIN", "")
        if not origin:
            raise RuntimeError("APP_ORIGIN is required")
        secure = os.environ.get("LABPASS_COOKIE_SECURE", "true")
        if secure not in {"true", "false"}:
            raise RuntimeError("LABPASS_COOKIE_SECURE must be true or false")
        return cls(url or None, origin, secure == "true", cloud_database=cloud)
