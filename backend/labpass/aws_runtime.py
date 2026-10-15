"""Bounded AWS calls and refreshed Secrets Manager credentials for cloud workers."""

import json
import re
import time

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import URL, create_engine

from labpass.aws_config import AwsRuntimeError
from labpass.db import make_sessions
from labpass.delivery import SendError
from labpass.mail import confirmation_text
from labpass.queue import SqsQueue

SECRET_TTL_SECONDS = 300
DELIVERY_LEASE_SECONDS = 120
MIN_RECORD_BUDGET_MS = 30_000


def make_aws_client(service, settings):
    # The execution role supplies credentials. No embedded keys or local endpoints.
    return boto3.Session().client(
        service,
        region_name=settings.region,
        config=Config(
            connect_timeout=2,
            read_timeout=5,
            retries={"total_max_attempts": 1},
            ignore_configured_endpoint_urls=True,
        ),
    )


def database_credentials(secret):
    try:
        value = json.loads(secret)
        username, password = value["username"], value["password"]
        if (
            not isinstance(username, str)
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", username)
            or not isinstance(password, str)
            or not 1 <= len(password) <= 1024
            or "\x00" in password
        ):
            raise ValueError
    except ValueError, TypeError, KeyError:
        raise AwsRuntimeError("invalid_database_secret") from None
    return username, password


def database_url(settings, secret):
    """RDS-managed secrets contain username/password; host/db come from configuration."""
    username, password = database_credentials(secret)
    return URL.create(
        "postgresql+psycopg",
        username=username,
        password=password,
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
        query={"sslmode": "verify-full", "sslrootcert": settings.db_ca_file},
    )


def make_cloud_engine(url):
    # One connection per serial worker/Lambda environment; concurrency is capped in IaC.
    return create_engine(
        url,
        hide_parameters=True,
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
        pool_timeout=3,
        isolation_level="READ COMMITTED",
        connect_args={
            "connect_timeout": 3,
            "options": "-c lock_timeout=3000 -c statement_timeout=3000",
        },
    )


class SesSender:
    def __init__(self, client, sender_email):
        self.client, self.sender_email = client, sender_email

    def send(self, claim):
        try:
            response = self.client.send_email(
                FromEmailAddress=self.sender_email,
                Destination={"ToAddresses": [claim.confirmation.recipient]},
                Content={
                    "Simple": {
                        "Subject": {"Data": "Your LabPass reservation", "Charset": "UTF-8"},
                        "Body": {"Text": {"Data": confirmation_text(claim), "Charset": "UTF-8"}},
                    }
                },
            )
        except BotoCoreError, ClientError:
            raise SendError("ses_acceptance_failed_or_unknown") from None
        if not response.get("MessageId"):
            raise SendError("ses_acceptance_failed_or_unknown")


class AwsRuntime:
    """One serial process owns this cache; no connections are shared across processes."""

    def __init__(
        self,
        settings,
        *,
        client_factory=make_aws_client,
        engine_factory=make_cloud_engine,
        username=None,
    ):
        self.settings = settings
        self._username = username
        self._engine_factory = engine_factory
        self._secret_client = client_factory("secretsmanager", settings)
        self.sender = SesSender(client_factory("sesv2", settings), settings.sender_email)
        self.publisher = SqsQueue(client_factory("sqs", settings), settings.queue_url)
        self._engine = self._sessions = None
        self._expires_at = 0

    def get_sessions(self):
        if self._sessions is not None and time.monotonic() < self._expires_at:
            return self._sessions
        # Retire old credentials before refresh; a failed refresh cannot use a stale pool.
        self._discard_pool()
        try:
            response = self._secret_client.get_secret_value(
                SecretId=self.settings.db_secret_arn, VersionStage="AWSCURRENT"
            )
        except BotoCoreError, ClientError:
            raise AwsRuntimeError("database_secret_unavailable") from None
        url = database_url(self.settings, response.get("SecretString"))
        if self._username is not None and url.username != self._username:
            raise AwsRuntimeError("unexpected_database_role")
        self._engine = self._engine_factory(url)
        self._sessions = make_sessions(self._engine)
        self._expires_at = time.monotonic() + SECRET_TTL_SECONDS
        return self._sessions

    def _discard_pool(self):
        if self._engine is not None:
            self._engine.dispose()
        self._engine = self._sessions = None
        self._expires_at = 0

    def close(self):
        self._discard_pool()
        for client in (self._secret_client, self.sender.client, self.publisher.client):
            client.close()
