import botocore.configloader
import pytest
from botocore.stub import Stubber

from labpass.background_config import BackgroundSettings
from labpass.outbox import PublicationError
from labpass.queue import SqsQueue, make_local_sqs


@pytest.fixture
def queue():
    settings = BackgroundSettings(
        "postgresql+psycopg://local/db", "http://127.0.0.1:9324", "mailpit"
    )
    client = make_local_sqs(settings)
    yield SqsQueue(client, "http://127.0.0.1:9324/000000000000/queue")
    client.close()


def test_sqs_sdk_parameters_and_receipt_handle_ack(queue):
    with Stubber(queue.client) as stub:
        stub.add_response(
            "send_message",
            {"MessageId": "message"},
            {"QueueUrl": queue.queue_url, "MessageBody": "body"},
        )
        queue.publish("body")
        stub.add_response(
            "receive_message",
            {
                "Messages": [
                    {"MessageId": "message", "ReceiptHandle": "latest-receipt", "Body": "body"}
                ]
            },
            {
                "QueueUrl": queue.queue_url,
                "MaxNumberOfMessages": 1,
                "WaitTimeSeconds": 2,
                "VisibilityTimeout": 120,
            },
        )
        assert queue.receive(limit=1)[0]["ReceiptHandle"] == "latest-receipt"
        stub.add_response(
            "delete_message", {}, {"QueueUrl": queue.queue_url, "ReceiptHandle": "latest-receipt"}
        )
        queue.acknowledge("latest-receipt")
        stub.add_response(
            "change_message_visibility",
            {},
            {
                "QueueUrl": queue.queue_url,
                "ReceiptHandle": "latest-receipt",
                "VisibilityTimeout": 120,
            },
        )
        queue.retry_later("latest-receipt")
        stub.assert_no_pending_responses()


def test_sqs_publication_errors_are_sanitized(queue):
    with Stubber(queue.client) as stub:
        stub.add_client_error(
            "send_message", "ServiceUnavailable", "private recipient in upstream text"
        )
        with pytest.raises(PublicationError, match="queue_publication_failed") as caught:
            queue.publish("private message body")
        assert "private" not in str(caught.value)


def test_local_client_does_not_read_shared_aws_configuration(monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "personal-profile-that-must-not-be-used")
    monkeypatch.setenv("AWS_CONFIG_FILE", "/must-not-read/personal-aws-config")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/must-not-read/personal-aws-credentials")
    accessed = []
    original = botocore.configloader.raw_config_parse

    def record_path(filename, *args, **kwargs):
        accessed.append(filename)
        return original(filename, *args, **kwargs)

    monkeypatch.setattr(botocore.configloader, "raw_config_parse", record_path)
    settings = BackgroundSettings(
        "postgresql+psycopg://local/db", "http://127.0.0.1:9324", "mailpit"
    )
    client = make_local_sqs(settings)
    try:
        assert accessed and set(accessed) == {"/dev/null"}
        assert client.meta.endpoint_url == settings.queue_endpoint
    finally:
        client.close()
