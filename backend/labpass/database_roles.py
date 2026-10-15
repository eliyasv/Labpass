"""Database role bootstrap and explicit table grants, outside Terraform state."""

import re

from psycopg import sql

ROLE_NAMES = {
    "api": "labpass_api",
    "relay": "labpass_relay",
    "consumer": "labpass_consumer",
    "migration": "labpass_migration",
}
TABLE_GRANTS = {
    "api": {
        "users": "SELECT, INSERT, UPDATE",
        "auth_sessions": "SELECT, INSERT, UPDATE, DELETE",
        "workshops": "SELECT, INSERT, UPDATE",
        "bookings": "SELECT, INSERT, UPDATE",
        "idempotency_records": "SELECT, INSERT",
        "outbox_events": "SELECT, INSERT",
        "email_deliveries": "SELECT",
    },
    "relay": {"outbox_events": "SELECT, UPDATE"},
    "consumer": {
        "users": "SELECT",
        "bookings": "SELECT",
        "outbox_events": "SELECT",
        "email_deliveries": "SELECT, INSERT, UPDATE",
    },
}


def validate_roles(roles):
    if set(roles) != set(ROLE_NAMES) or len(set(roles.values())) != 4:
        raise ValueError("invalid_database_roles")
    if any(not re.fullmatch(r"labpass_[a-z0-9_]{1,54}", role) for role in roles.values()):
        raise ValueError("invalid_database_roles")


def bootstrap_roles(connection, credentials, roles=ROLE_NAMES):
    validate_roles(roles)
    if set(credentials) != set(roles):
        raise ValueError("missing_database_credentials")
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), current_user")
        database, owner = cursor.fetchone()
        for component, role in roles.items():
            username, password = credentials[component]
            if username != role:
                raise ValueError("unexpected_database_role")
            cursor.execute(
                "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
                "FROM pg_roles WHERE rolname = %s",
                (role,),
            )
            existing = cursor.fetchone()
            if existing is None:
                cursor.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
            elif any(existing):
                raise ValueError("privileged_database_role_exists")
            cursor.execute(
                "SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.member "
                "WHERE r.rolname = %s LIMIT 1",
                (role,),
            )
            if cursor.fetchone() is not None:
                raise ValueError("database_role_has_memberships")
            cursor.execute(
                sql.SQL("ALTER ROLE {} LOGIN NOINHERIT PASSWORD {}").format(
                    sql.Identifier(role), sql.Literal(password)
                )
            )
        # Membership lets the RDS bootstrap administrator transfer schema ownership.
        cursor.execute(
            sql.SQL("GRANT {} TO {}").format(
                sql.Identifier(roles["migration"]), sql.Identifier(owner)
            )
        )
        cursor.execute(
            sql.SQL("ALTER SCHEMA public OWNER TO {}").format(sql.Identifier(roles["migration"]))
        )
        cursor.execute(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database))
        )
        cursor.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
        for role in roles.values():
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(database), sql.Identifier(role)
                )
            )
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role))
            )


def grant_runtime_privileges(connection, roles=ROLE_NAMES):
    validate_roles(roles)
    with connection.cursor() as cursor:
        cursor.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC")
        for component, grants in TABLE_GRANTS.items():
            role = sql.Identifier(roles[component])
            cursor.execute(
                sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(role)
            )
            for table, privileges in grants.items():
                cursor.execute(
                    sql.SQL("GRANT {} ON TABLE public.{} TO {}").format(
                        sql.SQL(privileges), sql.Identifier(table), role
                    )
                )
