#!/usr/bin/env bash
set -euo pipefail

component="${1:-}"
operation="${2:-}"
case "$component" in api|relay|bootstrap|migration) ;; *) exit 64 ;; esac
case "$operation" in pull|run|stop|job) ;; *) exit 64 ;; esac
name="labpass-$component"
export AWS_CONFIG_FILE=/dev/null AWS_SHARED_CREDENTIALS_FILE=/dev/null
export AWS_IGNORE_CONFIGURED_ENDPOINT_URLS=true AWS_PAGER=""
unset AWS_PROFILE AWS_DEFAULT_PROFILE AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN

if [[ "$operation" == stop ]]; then
  docker stop --time 30 "$name" >/dev/null 2>&1 || true
  docker rm --force "$name" >/dev/null 2>&1 || true
  exit 0
fi

config="${LABPASS_CONFIG_ROOT:-/etc/labpass}/$component"
read -r image < "$config/image"
read -r region < "$config/region"
read -r log_group < "$config/log-group"
[[ "$image" =~ ^[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/[a-z0-9/_-]+@sha256:[a-f0-9]{64}$ ]] || exit 65
[[ "$region" =~ ^[a-z]{2}-[a-z]+-[0-9]+$ ]] || exit 65
[[ "$log_group" =~ ^/labpass/[a-z0-9/-]+$ ]] || exit 65
registry="${image%%/*}"
[[ "$registry" == *."$region".amazonaws.com ]] || exit 65

if [[ "$operation" == pull ]]; then
  credential_dir="$(mktemp -d "${LABPASS_RUNTIME_ROOT:-/run}/labpass-ecr.XXXXXX")"
  trap 'rm -rf -- "$credential_dir"' EXIT
  aws ecr get-login-password --region "$region" |
    docker --config "$credential_dir" login --username AWS --password-stdin "$registry"
  docker --config "$credential_dir" pull "$image"
  exit 0
fi

command=()
options=()
if [[ "$operation" == run ]]; then
  case "$component" in
    api) options+=(--publish 8000:8000) ;;
    relay) command=(python -m labpass.aws_relay) ;;
    *) exit 64 ;;
  esac
else
  options+=(--rm)
  case "$component" in
    migration) command=(python -m labpass.migrate) ;;
    bootstrap)
      command=(python -m labpass.bootstrap_database)
      for role in api relay consumer migration; do
        key="LABPASS_${role^^}_SECRET_ARN"
        value="$(awk -v key="$key" '
          index($0, key "=") == 1 {print substr($0, length(key) + 2); found=1; exit}
          END {if (!found) exit 1}
        ' "$config/runtime.env")"
        [[ -n "$value" ]] || exit 65
        command+=("--$role-secret-arn" "$value")
      done
      ;;
    *) exit 64 ;;
  esac
fi

exec docker run --name "$name" --init --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m --cap-drop ALL \
  --security-opt no-new-privileges:true --pids-limit 256 --memory 512m \
  --user 10001:10001 --stop-timeout 30 --env-file "$config/runtime.env" \
  --log-driver awslogs --log-opt "awslogs-region=$region" \
  --log-opt "awslogs-group=$log_group" --log-opt awslogs-create-group=false \
  "${options[@]}" "$image" "${command[@]}"
