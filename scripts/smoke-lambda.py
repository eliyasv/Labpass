"""Run inside the Lambda image with Docker networking disabled and no cloud configuration."""

import json
import os
import ssl
from types import SimpleNamespace
from urllib.request import ProxyHandler, Request, build_opener

from labpass.aws_config import AwsRuntimeError
from labpass.lambda_handler import lambda_handler

if os.environ.get("LABPASS_AWS_ENABLED"):
    raise SystemExit("Offline smoke requires LABPASS_AWS_ENABLED to be absent")
assert os.getuid() != 0, "Run the offline smoke container as a non-root user"
assert (
    ssl.create_default_context(
        cafile=os.environ["LABPASS_DB_CA_FILE"]
    ).cert_store_stats()["x509_ca"]
    > 0
)

context = SimpleNamespace(get_remaining_time_in_millis=lambda: 60_000)
empty = {"Records": []}
batch = {
    "Records": [
        {"messageId": name, "eventSource": "aws:sqs", "body": "{}"}
        for name in ("one", "two")
    ]
}
failed = {"batchItemFailures": [{"itemIdentifier": name} for name in ("one", "two")]}
assert lambda_handler(empty, context) == {"batchItemFailures": []}
assert lambda_handler(batch, context) == failed
try:
    lambda_handler({}, context)
except AwsRuntimeError:
    pass
else:
    raise AssertionError("Invalid batch was accepted")

# The official base image starts its Runtime Interface Emulator on loopback port 8080.
opener = build_opener(ProxyHandler({}))
for event, expected in ((empty, {"batchItemFailures": []}), (batch, failed)):
    request = Request(
        "http://127.0.0.1:8080/2015-03-31/functions/function/invocations",
        data=json.dumps(event).encode(),
        headers={"Content-Type": "application/json"},
    )
    with opener.open(request, timeout=10) as response:
        assert json.load(response) == expected
print(
    "Lambda offline smoke passed: imports, handler and runtime emulator; no AWS calls"
)
