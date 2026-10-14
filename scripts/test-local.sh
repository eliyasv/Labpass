#!/usr/bin/env bash
# Requires Python dependencies installed in .venv and PostgreSQL 18 binaries on PATH.
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for task_binary in initdb pg_ctl createdb; do
  command -v "$task_binary" >/dev/null || { echo "Missing $task_binary" >&2; exit 1; }
done
task_tmp="$(mktemp -d /tmp/labpass-tests.XXXXXX)"
cleanup() {
  if [ -f "$task_tmp/data/postmaster.pid" ]; then
    pg_ctl -D "$task_tmp/data" -m fast -w stop >/dev/null
  fi
  # Keep the cluster and logs for inspection. This script deletes no existing database.
  echo "Test database files: $task_tmp"
}
trap cleanup EXIT
mkdir "$task_tmp/socket"
initdb -D "$task_tmp/data" --auth-local=trust --auth-host=reject --encoding=UTF8 --locale=C >/dev/null
pg_ctl -D "$task_tmp/data" -l "$task_tmp/postgres.log" \
  -o "-k $task_tmp/socket -p 55439 -c listen_addresses='' -c max_connections=160" -w start
createdb -h "$task_tmp/socket" -p 55439 labpass_test
export TEST_DATABASE_URL="postgresql+psycopg:///labpass_test?host=$task_tmp/socket&port=55439"
cd "$task_root/backend"
"$task_root/.venv/bin/python" -m pytest "$@"
