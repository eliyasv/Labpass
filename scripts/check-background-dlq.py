"""Run only in an isolated test consumer with LABPASS_DLQ_CHECK=true."""

import json
import os
import time
from uuid import uuid4

from labpass.background_config import BackgroundSettings
from labpass.queue import DLQ_NAME, get_local_queue

if os.environ.get("LABPASS_DLQ_CHECK") != "true":
    raise SystemExit(
        "Explicit LABPASS_DLQ_CHECK=true is required: this inserts a poison message"
    )
settings = BackgroundSettings.from_env()
queue = get_local_queue(settings)
dlq = get_local_queue(settings, DLQ_NAME)
body = json.dumps({"event_id": str(uuid4()), "event_type": "unsupported.dlq-test"})
queue.publish(body)
deadline = time.monotonic() + 80
while time.monotonic() < deadline:
    messages = dlq.receive(wait=0, visibility=0)
    if any(message["Body"] == body for message in messages):
        print(
            "DLQ check passed: poison message redriven after bounded receives; retained for inspection"
        )
        break
    time.sleep(1)
else:
    raise SystemExit(
        "Poison message was not redriven within 80s; inspect consumer and queue state"
    )
