"""Cloud relay entry point; local Compose continues to use labpass.background."""

import argparse
import logging
import signal
from threading import Event

from labpass.aws_config import AwsSettings
from labpass.aws_runtime import AwsRuntime
from labpass.outbox import publish_batch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--validate", action="store_true", help="Validate config without AWS calls")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    runtime = None
    stopped = Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stopped.set())
    try:
        settings = AwsSettings.from_env()
        if args.validate:
            print("AWS worker configuration is valid; no AWS calls made")
            return 0
        runtime = AwsRuntime(settings, username="labpass_relay")
        while not stopped.is_set():
            try:
                processed = publish_batch(runtime.get_sessions(), runtime.publisher, limit=5)
            except Exception:
                # Secret strings, DB parameters and SDK exception text are never logged.
                logging.error('{"event":"aws_relay_retry"}')
                if args.once:
                    return 1
                stopped.wait(5)
            else:
                if args.once:
                    print(f"Processed outbox rows: {processed}")
                    return 0
                stopped.wait(1)
    except Exception:
        logging.error('{"event":"aws_relay_startup_failed"}')
        return 1
    finally:
        if runtime is not None:
            try:
                runtime.close()
            except Exception:
                logging.error('{"event":"aws_relay_shutdown_failed"}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
