import os

import boto3
import botocore.session
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from labpass.outbox import PublicationError

QUEUE_NAME = "labpass-confirmations"
DLQ_NAME = "labpass-confirmations-dlq"


def make_local_sqs(settings):
    # Explicit endpoint and dummy credentials bypass every real AWS credential provider.
    # SDK scoped configuration normally inspects shared files even with explicit keys.
    core = botocore.session.Session()
    config_store = core.get_component("config_store")
    for name, value in (
        ("profile", None),
        ("config_file", os.devnull),
        ("credentials_file", os.devnull),
    ):
        config_store.set_config_variable(name, value)
    return boto3.Session(botocore_session=core).client(
        "sqs",
        endpoint_url=settings.queue_endpoint,
        region_name="us-east-1",
        aws_access_key_id="local",
        aws_secret_access_key="local",
        config=Config(
            connect_timeout=2, read_timeout=5, retries={"total_max_attempts": 1}, proxies={}
        ),
    )


class SqsQueue:
    def __init__(self, client, queue_url):
        self.client, self.queue_url = client, queue_url

    def publish(self, body):
        try:
            self.client.send_message(QueueUrl=self.queue_url, MessageBody=body)
        except BotoCoreError, ClientError:
            raise PublicationError("queue_publication_failed") from None

    def receive(self, *, wait=2, limit=10, visibility=120):
        return self.client.receive_message(
            QueueUrl=self.queue_url,
            MaxNumberOfMessages=limit,
            WaitTimeSeconds=wait,
            VisibilityTimeout=visibility,
        ).get("Messages", [])

    def acknowledge(self, receipt):
        self.client.delete_message(QueueUrl=self.queue_url, ReceiptHandle=receipt)

    def retry_later(self, receipt, *, visibility=120):
        self.client.change_message_visibility(
            QueueUrl=self.queue_url, ReceiptHandle=receipt, VisibilityTimeout=visibility
        )


def get_local_queue(settings, name=QUEUE_NAME):
    client = make_local_sqs(settings)
    url = client.get_queue_url(QueueName=name)["QueueUrl"]
    # Use the configured base even if the emulator advertises another host.
    from urllib.parse import urlsplit

    url = settings.queue_endpoint.rstrip("/") + urlsplit(url).path
    return SqsQueue(client, url)
