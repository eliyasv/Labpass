"""Explicit local/operator command. Never takes a password from argv or environment."""

import argparse
from getpass import getpass

from sqlalchemy.exc import SQLAlchemyError

from labpass.auth import hash_password, register
from labpass.aws_config import AwsRuntimeError
from labpass.cloud_database import CloudDatabase
from labpass.config import Settings
from labpass.db import make_engine, make_sessions
from labpass.rules import DomainError
from labpass.schemas import Registration


def provision_admin(session, email, encoded_password):
    # Conflict refuses to promote or reset an existing account.
    user = register(session, email, encoded_password)
    user.is_admin = True
    session.flush()
    return user.id


def main():
    parser = argparse.ArgumentParser(description="Create a new LabPass administrator")
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    settings = Settings.from_env()
    password = getpass("New admin password (12–128 characters): ")
    if password != getpass("Confirm password: "):
        raise SystemExit("Passwords do not match")
    try:
        credentials = Registration(email=args.email, password=password)
    except ValueError:
        raise SystemExit(
            "Invalid email or password; password must have 12–128 characters"
        ) from None
    encoded = hash_password(credentials.password.get_secret_value())
    cloud = None
    engine = None
    try:
        if settings.cloud_database is not None:
            cloud = CloudDatabase(settings.cloud_database)
            sessions = cloud
        else:
            engine = make_engine(settings.database_url)
            sessions = make_sessions(engine)
        with sessions.begin() as session:
            admin_id = provision_admin(session, credentials.email, encoded)
        print(f"Created administrator {admin_id}")
    except DomainError as exc:
        raise SystemExit(exc.code) from None
    except AwsRuntimeError, SQLAlchemyError:
        raise SystemExit("administrator_database_unavailable") from None
    finally:
        if cloud is not None:
            cloud.close()
        elif engine is not None:
            engine.dispose()


if __name__ == "__main__":
    main()
