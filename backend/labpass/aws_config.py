"""Explicit cloud configuration, separate from the credential-free local stack."""

import os
import re
import ssl
from dataclasses import dataclass
from pathlib import Path

from email_validator import EmailNotValidError, validate_email


class AwsRuntimeError(Exception):
    """Safe error codes only: upstream exceptions can contain secrets or mail."""


@dataclass(frozen=True)
class AwsSettings:
    region: str
    queue_arn: str
    db_secret_arn: str
    db_host: str
    db_name: str
    sender_email: str
    db_ca_file: str
    db_port: int = 5432

    def __post_init__(self):
        if not re.fullmatch(r"(?:us|eu|ap|ca|sa|me|af|il|mx)-[a-z]+-\d+", self.region):
            raise AwsRuntimeError("invalid_aws_region")
        queue = re.fullmatch(
            rf"arn:aws:sqs:{re.escape(self.region)}:(\d{{12}}):([A-Za-z0-9_-]{{1,80}})",
            self.queue_arn,
        )
        if queue is None:
            # Standard queues only; FIFO requires different batch failure ordering.
            raise AwsRuntimeError("invalid_standard_queue_arn")
        if not re.fullmatch(
            rf"arn:aws:secretsmanager:{re.escape(self.region)}:{queue[1]}:secret:"
            r"[A-Za-z0-9/_+=.@-]+-[A-Za-z0-9]{6}",
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
            normalized = validate_email(
                self.sender_email, check_deliverability=False, allow_smtputf8=False
            ).ascii_email.lower()
        except EmailNotValidError:
            raise AwsRuntimeError("invalid_ses_sender") from None
        if normalized != self.sender_email:
            raise AwsRuntimeError("invalid_ses_sender")
        try:
            if not Path(self.db_ca_file).is_absolute():
                raise ValueError
            ssl.create_default_context(cafile=self.db_ca_file)
        except OSError, ValueError:
            raise AwsRuntimeError("invalid_database_ca_file") from None

    @property
    def queue_url(self):
        _, _, _, region, account, name = self.queue_arn.split(":")
        return f"https://sqs.{region}.amazonaws.com/{account}/{name}"

    @classmethod
    def from_env(cls):
        if os.environ.get("LABPASS_AWS_ENABLED") != "true":
            raise AwsRuntimeError("aws_runtime_not_enabled")
        names = {
            "region": "AWS_REGION",
            "queue_arn": "LABPASS_QUEUE_ARN",
            "db_secret_arn": "LABPASS_DB_SECRET_ARN",
            "db_host": "LABPASS_DB_HOST",
            "db_name": "LABPASS_DB_NAME",
            "sender_email": "LABPASS_SES_FROM",
            "db_ca_file": "LABPASS_DB_CA_FILE",
        }
        values = {field: os.environ.get(name, "") for field, name in names.items()}
        if not all(values.values()):
            raise AwsRuntimeError("missing_aws_configuration")
        try:
            port = int(os.environ.get("LABPASS_DB_PORT", "5432"))
        except ValueError:
            raise AwsRuntimeError("invalid_database_port") from None
        return cls(**values, db_port=port)
