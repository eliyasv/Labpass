"""Cloud migration entry point using the restricted schema-owner secret."""

from pathlib import Path

from alembic import command
from alembic.config import Config

from labpass.cloud_database import CloudDatabase, CloudDatabaseSettings
from labpass.database_roles import grant_runtime_privileges


def upgrade(connection):
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


def main():
    database = None
    try:
        database = CloudDatabase(CloudDatabaseSettings.from_env(), username="labpass_migration")
        with database.get_sessions().kw["bind"].begin() as connection:
            upgrade(connection)
            grant_runtime_privileges(connection.connection.driver_connection)
        print("Database migrations applied")
        return 0
    except Exception:
        print("database_migration_failed")
        return 1
    finally:
        if database is not None:
            database.close()


if __name__ == "__main__":
    raise SystemExit(main())
