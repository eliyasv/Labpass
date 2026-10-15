"""Secrets Manager database access for concurrent API requests and operator jobs."""

import os
import re
import ssl
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from botocore.exceptions import BotoCoreError, ClientError

from labpass.aws_config import AwsRuntimeError
from labpass.aws_runtime import SECRET_TTL_SECONDS, database_url, make_aws_client
from labpass.db import make_engine, make_sessions


@dataclass(frozen=True)
class CloudDatabaseSettings:
    region: str
    db_secret_arn: str
    db_host: str
    db_name: str
    db_ca_file: str
    db_port: int = 5432

    def __post_init__(self):
        if not re.fullmatch(r"(?:us|eu|ap|ca|sa|me|af|il|mx)-[a-z]+-\d+", self.region):
            raise AwsRuntimeError("invalid_aws_region")
        if not re.fullmatch(
            rf"arn:aws:secretsmanager:{re.escape(self.region)}:\d{{12}}:secret:"
            r"[A-Za-z0-9!/_+=.@-]+-[A-Za-z0-9]{6}",
            self.db_secret_arn,
        ):
            raise AwsRuntimeError("invalid_database_secret_arn")
        if not re.fullmatch(
            r"[a-z0-9]+(?:[.-][a-z0-9]+)*", self.db_host
        ) or not self.db_host.endswith(f".{self.region}.rds.amazonaws.com"):
            raise AwsRuntimeError("invalid_rds_hostname")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", self.db_name):
            raise AwsRuntimeError("invalid_database_name")
        if type(self.db_port) is not int or not 1 <= self.db_port <= 65535:
            raise AwsRuntimeError("invalid_database_port")
        try:
            if not Path(self.db_ca_file).is_absolute():
                raise ValueError
            ssl.create_default_context(cafile=self.db_ca_file)
        except OSError, ValueError:
            raise AwsRuntimeError("invalid_database_ca_file") from None

    @classmethod
    def from_env(cls):
        if os.environ.get("LABPASS_AWS_ENABLED") != "true":
            raise AwsRuntimeError("aws_runtime_not_enabled")
        names = {
            "region": "AWS_REGION",
            "db_secret_arn": "LABPASS_DB_SECRET_ARN",
            "db_host": "LABPASS_DB_HOST",
            "db_name": "LABPASS_DB_NAME",
            "db_ca_file": "LABPASS_DB_CA_FILE",
        }
        values = {field: os.environ.get(name, "") for field, name in names.items()}
        if not all(values.values()):
            raise AwsRuntimeError("missing_cloud_database_configuration")
        try:
            port = int(os.environ.get("LABPASS_DB_PORT", "5432"))
        except ValueError:
            raise AwsRuntimeError("invalid_database_port") from None
        return cls(**values, db_port=port)


def make_api_engine(url):
    return make_engine(url, pool_size=5, max_overflow=0)


class CloudDatabase:
    def __init__(
        self,
        settings,
        *,
        username="labpass_api",
        client_factory=make_aws_client,
        engine_factory=make_api_engine,
    ):
        self.settings = settings
        self._username = username
        self._client = client_factory("secretsmanager", settings)
        self._engine_factory = engine_factory
        self._lock = Lock()
        self._engine = self._sessions = None
        self._expires_at = 0
        self._retry_at = 0
        self._closed = False

    def get_sessions(self):
        with self._lock:
            if self._closed:
                raise AwsRuntimeError("database_runtime_closed")
            if self._sessions is not None and time.monotonic() < self._expires_at:
                return self._sessions
            if time.monotonic() < self._retry_at:
                raise AwsRuntimeError("database_secret_unavailable")
            self._discard_pool()
            try:
                response = self._client.get_secret_value(
                    SecretId=self.settings.db_secret_arn, VersionStage="AWSCURRENT"
                )
            except BotoCoreError, ClientError:
                self._retry_at = time.monotonic() + 5
                raise AwsRuntimeError("database_secret_unavailable") from None
            url = database_url(self.settings, response.get("SecretString"))
            if url.username != self._username:
                raise AwsRuntimeError("unexpected_database_role")
            self._engine = self._engine_factory(url)
            self._sessions = make_sessions(self._engine)
            self._expires_at = time.monotonic() + SECRET_TTL_SECONDS
            return self._sessions

    def __call__(self):
        return self.get_sessions()()

    def begin(self):
        return self.get_sessions().begin()

    def _discard_pool(self):
        if self._engine is not None:
            self._engine.dispose()
        self._engine = self._sessions = None
        self._expires_at = 0

    def close(self):
        with self._lock:
            self._closed = True
            self._discard_pool()
            self._client.close()
