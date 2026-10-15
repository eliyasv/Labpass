"""Run the actual host shell helper with offline AWS/Docker command stand-ins."""

import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "infra/foundation/templates/labpass-service.sh"
)
IMAGE = (
    "123456789012.dkr.ecr.us-east-1.amazonaws.com/labpass-demo/api@sha256:" + "a" * 64
)


@pytest.fixture
def host(tmp_path):
    binaries = tmp_path / "bin"
    binaries.mkdir()
    calls = tmp_path / "calls.jsonl"
    runtime = tmp_path / "run"
    runtime.mkdir()
    for component in ("api", "relay", "bootstrap", "migration"):
        config = tmp_path / "config" / component
        config.mkdir(parents=True)
        for name, value in {
            "image": IMAGE,
            "region": "us-east-1",
            "log-group": f"/labpass/labpass-demo/{component}",
        }.items():
            (config / name).write_text(value + "\n")
        environment = "LABPASS_AWS_ENABLED=true\n"
        for role in ("api", "relay", "consumer", "migration"):
            environment += f"LABPASS_{role.upper()}_SECRET_ARN=arn:aws:secretsmanager:us-east-1:123456789012:secret:mock-{role}-AbCd12\n"
        (config / "runtime.env").write_text(environment)

    stand_in = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["HOST_TEST_CALLS"], "a") as output:
    output.write(json.dumps({"name": name, "args": args,
        "has_credentials": "AWS_ACCESS_KEY_ID" in os.environ,
        "profile": os.environ.get("AWS_PROFILE"),
        "config_file": os.environ.get("AWS_CONFIG_FILE")}) + "\\n")
if name == "aws":
    if os.environ.get("HOST_TEST_FAILURE") == "aws": sys.exit(1)
    print("fixture-ecr-token")
elif "login" in args:
    if sys.stdin.read().strip() != "fixture-ecr-token": sys.exit(2)
    directory = Path(args[args.index("--config") + 1])
    (directory / "config.json").write_text("fixture-auth")
    if os.environ.get("HOST_TEST_FAILURE") == "login": sys.exit(1)
elif "pull" in args:
    directory = Path(args[args.index("--config") + 1])
    if not (directory / "config.json").exists(): sys.exit(3)
    if os.environ.get("HOST_TEST_FAILURE") == "pull": sys.exit(1)
"""
    for name in ("aws", "docker"):
        executable = binaries / name
        executable.write_text(stand_in)
        executable.chmod(0o700)

    environment = dict(
        os.environ,
        PATH=f"{binaries}:{os.environ['PATH']}",
        LABPASS_CONFIG_ROOT=str(tmp_path / "config"),
        LABPASS_RUNTIME_ROOT=str(runtime),
        HOST_TEST_CALLS=str(calls),
        AWS_PROFILE="must-not-load",
        AWS_ACCESS_KEY_ID="must-not-use",
    )

    def run(component, operation, **updates):
        return subprocess.run(
            ["bash", str(SCRIPT), component, operation],
            check=False,
            env=dict(environment, **updates),
            text=True,
            capture_output=True,
            timeout=10,
        )

    def recorded():
        return (
            [json.loads(line) for line in calls.read_text().splitlines()]
            if calls.exists()
            else []
        )

    return tmp_path, run, recorded


def test_digest_pull_uses_temporary_auth_and_instance_role(host):
    root, run, recorded = host
    result = run("api", "pull")
    assert result.returncode == 0, result.stderr
    calls = recorded()
    aws_call = next(call for call in calls if call["name"] == "aws")
    assert aws_call["args"] == ["ecr", "get-login-password", "--region", "us-east-1"]
    assert all(
        not call["has_credentials"] and call["profile"] is None for call in calls
    )
    assert aws_call["config_file"] == "/dev/null"
    assert calls[-1]["args"][-2:] == ["pull", IMAGE]
    assert "fixture-ecr-token" not in result.stdout + result.stderr
    assert list((root / "run").iterdir()) == []


@pytest.mark.parametrize("failure", ["aws", "login", "pull"])
def test_pull_failure_is_not_ignored_and_auth_is_removed(host, failure):
    root, run, _ = host
    result = run("api", "pull", HOST_TEST_FAILURE=failure)
    assert result.returncode != 0
    assert "fixture-ecr-token" not in result.stdout + result.stderr
    assert list((root / "run").iterdir()) == []


def test_api_container_is_bounded_and_publishes_only_api_port(host):
    _, run, recorded = host
    assert run("api", "run").returncode == 0
    args = recorded()[0]["args"]
    assert args[0] == "run" and args[-1] == IMAGE
    assert args[args.index("--publish") + 1] == "8000:8000"
    assert args[args.index("--user") + 1] == "10001:10001"
    assert args[args.index("--cap-drop") + 1] == "ALL"
    assert args[args.index("--memory") + 1] == "512m"
    assert "--read-only" in args and "--init" in args
    assert args[args.index("--log-driver") + 1] == "awslogs"
    assert "awslogs-create-group=false" in args


def test_relay_has_no_published_port(host):
    _, run, recorded = host
    assert run("relay", "run").returncode == 0
    args = recorded()[0]["args"]
    assert "--publish" not in args
    assert args[-4:] == [IMAGE, "python", "-m", "labpass.aws_relay"]


@pytest.mark.parametrize("component", ["bootstrap", "migration"])
def test_operator_jobs_require_explicit_job_operation(host, component):
    _, run, recorded = host
    assert run(component, "run").returncode == 64
    assert recorded() == []
    assert run(component, "job").returncode == 0
    args = recorded()[0]["args"]
    assert "--publish" not in args and "--rm" in args
    if component == "bootstrap":
        assert "labpass.bootstrap_database" in args
        for role in ("api", "relay", "consumer", "migration"):
            assert f"--{role}-secret-arn" in args
    else:
        assert args[-3:] == ["python", "-m", "labpass.migrate"]


@pytest.mark.parametrize(
    "component,operation",
    [("other", "run"), ("api", "other"), ("api", "job"), ("relay", "job")],
)
def test_invalid_component_or_operation_cannot_launch_a_container(
    host, component, operation
):
    _, run, recorded = host
    assert run(component, operation).returncode == 64
    assert recorded() == []


@pytest.mark.parametrize(
    "name,value",
    [
        ("image", "image:latest"),
        ("region", "us-west-2"),
        ("log-group", "bad-log-group"),
    ],
)
def test_invalid_configuration_fails_before_external_commands(host, name, value):
    root, run, recorded = host
    (root / "config/api" / name).write_text(value + "\n")
    assert run("api", "pull").returncode == 65
    assert recorded() == []


def test_bootstrap_with_missing_role_arn_does_not_start(host):
    root, run, recorded = host
    (root / "config/bootstrap/runtime.env").write_text("LABPASS_AWS_ENABLED=true\n")
    assert run("bootstrap", "job").returncode != 0
    assert recorded() == []


def test_stop_targets_only_the_component_container(host):
    _, run, recorded = host
    assert run("api", "stop").returncode == 0
    assert [call["args"] for call in recorded()] == [
        ["stop", "--time", "30", "labpass-api"],
        ["rm", "--force", "labpass-api"],
    ]


def test_stop_does_not_depend_on_deployment_configuration(host):
    root, run, recorded = host
    (root / "config/api").rename(root / "config/api-unavailable")
    assert run("api", "stop").returncode == 0
    assert [call["args"][-1] for call in recorded()] == ["labpass-api", "labpass-api"]
