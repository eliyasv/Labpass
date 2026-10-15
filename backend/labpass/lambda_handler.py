"""Standard SQS consumer. Enable ReportBatchItemFailures on the event-source mapping."""

import json
import logging
import re

from labpass.aws_config import AwsRuntimeError, AwsSettings
from labpass.aws_runtime import DELIVERY_LEASE_SECONDS, MIN_RECORD_BUDGET_MS, AwsRuntime
from labpass.delivery import process_message

logger = logging.getLogger("labpass")
logger.setLevel(logging.INFO)
_runtime = None


def get_runtime():
    global _runtime
    if _runtime is None:
        _runtime = AwsRuntime(AwsSettings.from_env(), username="labpass_consumer")
    return _runtime


def lambda_handler(event, context):
    # Invalid invocation shapes must fail the whole batch, rather than acknowledge it.
    if not isinstance(event, dict) or not isinstance(event.get("Records"), list):
        raise AwsRuntimeError("invalid_sqs_batch")
    records = event["Records"]
    if any(
        not isinstance(record, dict)
        or not isinstance(record.get("messageId"), str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", record["messageId"])
        for record in records
    ):
        raise AwsRuntimeError("invalid_sqs_message_identity")
    failures = []
    runtime = None
    sessions = None
    initialization_failed = False
    for record in records:
        try:
            remaining = context.get_remaining_time_in_millis()
            if remaining > 60_000:
                raise AwsRuntimeError("invocation_timeout_exceeds_lease_budget")
            if remaining < MIN_RECORD_BUDGET_MS:
                raise AwsRuntimeError("insufficient_invocation_time")
            if record.get("eventSource") != "aws:sqs" or not isinstance(record.get("body"), str):
                raise AwsRuntimeError("invalid_sqs_record")
            if initialization_failed:
                raise AwsRuntimeError("aws_runtime_unavailable")
            # Load once per invocation; a shared initialization failure retries all records.
            if runtime is None:
                try:
                    runtime = get_runtime()
                except Exception:
                    initialization_failed = True
                    raise
            if record.get("eventSourceARN") != runtime.settings.queue_arn:
                raise AwsRuntimeError("unexpected_sqs_source")
            if sessions is None:
                try:
                    sessions = runtime.get_sessions()
                except Exception:
                    initialization_failed = True
                    raise
            if context.get_remaining_time_in_millis() < MIN_RECORD_BUDGET_MS:
                raise AwsRuntimeError("insufficient_invocation_time")
            process_message(
                sessions, runtime.sender, record["body"], lease_seconds=DELIVERY_LEASE_SECONDS
            )
        except Exception as error:
            failures.append({"itemIdentifier": record["messageId"]})
            logger.warning(
                json.dumps(
                    {
                        "event": "sqs_record_retry",
                        "message_id": record["messageId"],
                        "error_type": type(error).__name__,
                    }
                )
            )
    return {"batchItemFailures": failures}
