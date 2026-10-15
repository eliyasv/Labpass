"""Provision role secrets, schema ownership, migrations and runtime table grants."""

import argparse
import json
import secrets
from dataclasses import replace
from uuid import uuid4

from botocore.exceptions import ClientError

from labpass.aws_config import AwsRuntimeError
from labpass.aws_runtime import database_credentials, database_url, make_aws_client
from labpass.cloud_database import CloudDatabaseSettings, make_api_engine
from labpass.database_roles import ROLE_NAMES, bootstrap_roles, grant_runtime_privileges
from labpass.migrate import upgrade


def role_credentials(client, secret_arn, username):
    try:
        response = client.get_secret_value(SecretId=secret_arn, VersionStage="AWSCURRENT")
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceNotFoundException":
            raise AwsRuntimeError("database_secret_unavailable") from None
        password = secrets.token_urlsafe(48)
        client.put_secret_value(
            SecretId=secret_arn,
            ClientRequestToken=str(uuid4()),
            SecretString=json.dumps({"username": username, "password": password}),
            VersionStages=["AWSCURRENT"],
        )
        return username, password
    credentials = database_credentials(response.get("SecretString"))
    if credentials[0] != username:
        raise AwsRuntimeError("unexpected_database_role")
    return credentials


def validate_secret_arns(settings, secret_arns):
    if set(secret_arns) != set(ROLE_NAMES) or len(set(secret_arns.values())) != 4:
        raise AwsRuntimeError("invalid_role_secret_arns")
    account = settings.db_secret_arn.split(":")[4]
    for arn in secret_arns.values():
        replace(settings, db_secret_arn=arn)
        if arn.split(":")[4] != account or arn == settings.db_secret_arn:
            raise AwsRuntimeError("invalid_role_secret_arns")


def provision(settings, secret_arns, client):
    validate_secret_arns(settings, secret_arns)
    master = client.get_secret_value(SecretId=settings.db_secret_arn, VersionStage="AWSCURRENT")
    url = database_url(settings, master.get("SecretString"))
    if url.username != "labpass_admin":
        raise AwsRuntimeError("unexpected_bootstrap_database_role")
    master_engine = make_api_engine(url)
    migration_engine = None
    try:
        with master_engine.connect() as connection:
            try:
                with connection.begin():
                    raw = connection.connection.driver_connection
                    with raw.cursor() as cursor:
                        cursor.execute(
                            "SELECT pg_advisory_lock(hashtext(current_database()), "
                            "hashtext('labpass_database_bootstrap'))"
                        )
                    credentials = {
                        key: role_credentials(client, arn, ROLE_NAMES[key])
                        for key, arn in secret_arns.items()
                    }
                    bootstrap_roles(raw, credentials, ROLE_NAMES)
                migration_url = database_url(
                    settings,
                    json.dumps(
                        {
                            "username": credentials["migration"][0],
                            "password": credentials["migration"][1],
                        }
                    ),
                )
                migration_engine = make_api_engine(migration_url)
                with migration_engine.begin() as migration_connection:
                    upgrade(migration_connection)
                    grant_runtime_privileges(
                        migration_connection.connection.driver_connection, ROLE_NAMES
                    )
            finally:
                # The session lock spans secret creation, committed roles and migrations.
                connection.invalidate()
    finally:
        if migration_engine is not None:
            migration_engine.dispose()
        master_engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for component in ROLE_NAMES:
        parser.add_argument(f"--{component}-secret-arn", required=True)
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    client = None
    try:
        settings = CloudDatabaseSettings.from_env()
        arns = {key: getattr(args, f"{key}_secret_arn") for key in ROLE_NAMES}
        validate_secret_arns(settings, arns)
        if args.validate:
            print("Database bootstrap configuration valid")
            return 0
        client = make_aws_client("secretsmanager", settings)
        provision(settings, arns, client)
        print("Database roles, migrations and grants applied")
        return 0
    except Exception:
        print("database_bootstrap_failed")
        return 1
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
