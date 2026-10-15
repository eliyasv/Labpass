"""Offline security regressions for release approval, plan scope and migration ordering."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

SPEC = importlib.util.spec_from_file_location(
    "labpass_release", Path(__file__).resolve().parents[1] / "ci/release.py"
)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


@pytest.fixture
def context(monkeypatch):
    settings = {
        "GITHUB_REF": "refs/heads/dev",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_REPOSITORY": "example/labpass",
        "GITHUB_SHA": "a" * 40,
        "GITHUB_RUN_ID": "123",
        "AWS_ACCOUNT_ID": "123456789012",
        "WORKLOAD_NAME_PREFIX": "labpass-demo",
        "API_DIGEST": "sha256:" + "a" * 64,
        "LAMBDA_DIGEST": "sha256:" + "b" * 64,
        "ORIGIN_VERIFY_TOKEN": "0" * 64,
        "FOUNDATION_TFVARS_JSON": json.dumps(
            {
                "application": {"api_desired_capacity": 2, "relay_desired_capacity": 1},
                "frontend": {},
                "confirmation_worker": {},
            }
        ),
    }
    for key, value in settings.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("ORIGIN_VERIFY_PREVIOUS_TOKEN", raising=False)
    monkeypatch.setattr(
        release, "github", Mock(return_value={"object": {"sha": "a" * 40}})
    )
    return settings


def change(address, before, after, actions=None):
    return {
        "resource_changes": [
            {
                "address": address,
                "mode": "managed",
                "change": {
                    "actions": actions or ["update"],
                    "before": before,
                    "after": after,
                },
            }
        ]
    }


@pytest.mark.parametrize(
    "address,field",
    [
        ('module.application.aws_launch_template.runtime["api"]', "user_data"),
        (
            'module.application.aws_launch_template.runtime["migration"]',
            "latest_version",
        ),
        ("module.application.aws_autoscaling_group.api[0]", "launch_template"),
        ("module.confirmations.aws_lambda_function.confirmations[0]", "image_uri"),
        ("module.confirmations.aws_lambda_alias.confirmations[0]", "function_version"),
    ],
)
def test_plan_accepts_only_runtime_release_fields(address, field):
    assert release.validate_plan(change(address, {field: "old"}, {field: "new"})) == [
        address
    ]


@pytest.mark.parametrize(
    "address,field,actions",
    [
        (
            'module.application.aws_launch_template.runtime["api"]',
            "user_data",
            ["create"],
        ),
        (
            'module.application.aws_launch_template.runtime["api"]',
            "user_data",
            ["delete", "create"],
        ),
        (
            'module.application.aws_launch_template.runtime["api"]',
            "iam_instance_profile",
            ["update"],
        ),
        (
            "module.application.aws_autoscaling_group.api[0]",
            "desired_capacity",
            ["update"],
        ),
        (
            "module.confirmations.aws_lambda_function.confirmations[0]",
            "role",
            ["update"],
        ),
        (
            "module.confirmations.aws_lambda_function.confirmations[0]",
            "environment",
            ["update"],
        ),
        ("aws_lambda_event_source_mapping.confirmations[0]", "enabled", ["update"]),
        ('aws_iam_role.runtime["api"]', "assume_role_policy", ["update"]),
        ("aws_db_instance.main", "engine_version", ["update"]),
        ("aws_cloudfront_distribution.site[0]", "origin", ["update"]),
    ],
)
def test_plan_rejects_creation_replacement_privilege_and_configuration_changes(
    address, field, actions
):
    with pytest.raises(ValueError):
        release.validate_plan(change(address, {field: "old"}, {field: "new"}, actions))


@pytest.mark.parametrize("flag", [{"complete": False}, {"errored": True}])
def test_invalid_terraform_plan_is_rejected(flag):
    with pytest.raises(ValueError):
        release.validate_plan(flag)


def test_no_infrastructure_change_is_valid_for_a_frontend_release():
    assert (
        release.validate_plan(
            {"applyable": False, "complete": True, "resource_changes": []}
        )
        == []
    )
    plan = change(
        "module.confirmations.aws_lambda_function.confirmations[0]",
        {"code_sha256": "old"},
        {"code_sha256": None},
    )
    assert release.validate_plan(plan) == [
        "module.confirmations.aws_lambda_function.confirmations[0]"
    ]
    with pytest.raises(ValueError):
        release.validate_plan({**plan, "applyable": False})


@pytest.mark.parametrize("actions", [["no-op"], ["update"]])
def test_release_rejects_resource_address_changes(actions):
    plan = change(
        'module.application.aws_launch_template.runtime["api"]', {}, {}, actions
    )
    plan["resource_changes"][0]["previous_address"] = (
        'aws_launch_template.runtime["api"]'
    )
    with pytest.raises(ValueError, match="cannot change resource addresses"):
        release.validate_plan(plan)


@pytest.mark.parametrize(
    "name,value",
    [
        ("GITHUB_REF", "refs/heads/feat/unreviewed"),
        ("GITHUB_RUN_ATTEMPT", "2"),
        ("GITHUB_REPOSITORY", "../malicious?token=x"),
    ],
)
def test_release_ref_and_retry_guards(context, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        release.ensure_current()


def test_release_rejects_a_superseded_commit(context):
    release.github.return_value = {"object": {"sha": "b" * 40}}
    with pytest.raises(ValueError, match="no longer"):
        release.ensure_current()


def test_environment_protections_require_reviewers_and_exact_branch():
    settings = {
        "protection_rules": [{"type": "required_reviewers", "reviewers": [{"id": 7}]}],
        "deployment_branch_policy": {"custom_branch_policies": True},
    }
    branch = {"branch_policies": [{"name": "dev", "type": "branch"}], "total_count": 1}
    release.check_environment(settings, branch)
    for mutation in ({}, {"protection_rules": []}, {"deployment_branch_policy": {}}):
        invalid = copy.deepcopy(settings)
        invalid.update(mutation)
        if not mutation:
            invalid = {}
        with pytest.raises(ValueError):
            release.check_environment(invalid, branch)
    for invalid in (
        [],
        [{"name": "*", "type": "branch"}],
        [{"name": "dev", "type": "tag"}],
        [{"name": "dev", "type": "branch"}, {"name": "main", "type": "branch"}],
    ):
        with pytest.raises(ValueError):
            release.check_environment(settings, {"branch_policies": invalid})


@pytest.mark.parametrize(
    "mutation",
    [
        {"aws_account_id": "000000000000"},
        {"origin_verify_token": "token"},
        {"name_prefix": "labpass-other"},
        {"frontend": None},
        {"application": {"api_desired_capacity": 0, "relay_desired_capacity": 0}},
    ],
)
def test_release_config_rejects_wrong_scope_and_public_secret(
    context, monkeypatch, mutation
):
    config = json.loads(context["FOUNDATION_TFVARS_JSON"])
    config.update(mutation)
    monkeypatch.setenv("FOUNDATION_TFVARS_JSON", json.dumps(config))
    with pytest.raises(ValueError):
        release.release_config()


def test_manifest_binds_commit_run_configuration_and_binary(context, monkeypatch):
    config = release.release_config()
    plan = b"private binary Terraform plan"
    manifest = {
        "schema": 1,
        "sha": context["GITHUB_SHA"],
        "run_id": "123",
        "config_hash": release.config_hash(config),
        "plan_hash": hashlib.sha256(plan).hexdigest(),
    }
    content = json.dumps(manifest).encode()
    monkeypatch.setenv("MANIFEST_HASH", hashlib.sha256(content).hexdigest())
    release.verify_manifest(content, plan, config)
    for altered_plan, altered_config in (
        (plan + b"tampered", config),
        (plan, {**config, "frontend": None}),
    ):
        with pytest.raises(ValueError):
            release.verify_manifest(content, altered_plan, altered_config)
    monkeypatch.setenv("GITHUB_RUN_ID", "999")
    with pytest.raises(ValueError):
        release.verify_manifest(content, plan, config)
    with pytest.raises(ValueError, match="checksum"):
        release.verify_manifest(content + b" ", plan, config)


@pytest.fixture
def migration_host(context, monkeypatch):
    monkeypatch.setenv("MIGRATION_INSTANCE_ID", "i-" + "0" * 17)
    details = {
        "State": {"Name": "running"},
        "Tags": [
            {"Key": "Project", "Value": "LabPass"},
            {"Key": "Component", "Value": "migration"},
        ],
        "IamInstanceProfile": {
            "Arn": "arn:aws:iam::123456789012:instance-profile/labpass-demo-migration"
        },
    }
    ec2, ssm = Mock(), Mock()
    ec2.describe_instances.return_value = {"Reservations": [{"Instances": [details]}]}
    ssm.send_command.return_value = {"Command": {"CommandId": "mock-command"}}
    ssm.get_command_invocation.return_value = {"Status": "Success"}
    monkeypatch.setattr(release, "client", lambda name: {"ec2": ec2, "ssm": ssm}[name])
    return details, ssm


@pytest.mark.parametrize(
    "mutation",
    [
        {"PublicIpAddress": "192.0.2.1"},
        {"State": {"Name": "stopped"}},
        {"Tags": []},
        {
            "IamInstanceProfile": {
                "Arn": "arn:aws:iam::123456789012:instance-profile/admin"
            }
        },
    ],
)
def test_migration_refuses_wrong_operator(migration_host, mutation):
    details, ssm = migration_host
    details.update(mutation)
    with pytest.raises(ValueError):
        release.migrate(release.release_config())
    ssm.send_command.assert_not_called()


def test_migration_uses_digest_only_and_stops_on_failure(migration_host):
    _, ssm = migration_host
    config = release.release_config()
    release.migrate(config)
    parameters = ssm.send_command.call_args.kwargs
    assert parameters["DocumentName"] == "labpass-demo-release-migration"
    assert parameters["Parameters"] == {
        "ImageDigest": [config["application"]["image_digest"]]
    }
    ssm.get_command_invocation.return_value = {"Status": "Failed"}
    with pytest.raises(ValueError, match="rollout has not started"):
        release.migrate(config)


def test_apply_never_starts_after_failed_migration(context, monkeypatch):
    monkeypatch.setattr(release, "ensure_account", lambda: None)
    monkeypatch.setattr(release, "init_backend", lambda: None)
    monkeypatch.setattr(release, "verify_manifest", lambda *_: None)
    monkeypatch.setenv("STATE_BUCKET", "private-state")
    monkeypatch.setenv("PLAN_VERSION", "one")
    monkeypatch.setenv("MANIFEST_VERSION", "two")
    s3 = Mock()
    s3.get_object.return_value = {"Body": Mock(read=lambda: b"private")}
    monkeypatch.setattr(release, "client", lambda _: s3)
    run = Mock(return_value=SimpleNamespace(stdout='{"resource_changes": []}'))
    monkeypatch.setattr(release, "run", run)
    monkeypatch.setattr(
        release, "migrate", Mock(side_effect=ValueError("migration failed"))
    )
    with pytest.raises(ValueError, match="migration failed"):
        release.apply()
    assert all("apply" not in call.args[0] for call in run.call_args_list)
    assert {call.kwargs["VersionId"] for call in s3.get_object.call_args_list} == {
        "one",
        "two",
    }


def test_rollout_waits_for_actual_instance_template_and_refresh(context, monkeypatch):
    asg = Mock()
    template = {"LaunchTemplateId": "lt-mock", "Version": "3"}
    current = {
        "LaunchTemplate": template,
        "LifecycleState": "InService",
        "HealthStatus": "Healthy",
    }
    old = {**current, "LaunchTemplate": {**template, "Version": "2"}}
    group = {"LaunchTemplate": template, "DesiredCapacity": 1, "Instances": [old]}
    asg.describe_auto_scaling_groups.return_value = {"AutoScalingGroups": [group]}
    asg.describe_instance_refreshes.return_value = {
        "InstanceRefreshes": [{"Status": "Successful"}]
    }
    monkeypatch.setattr(release, "client", lambda _: asg)

    def finish(_):
        group["Instances"] = [
            {
                **current,
                "LaunchTemplate": {**template, "LaunchTemplateName": "optional"},
            }
        ]

    sleeper = Mock(side_effect=finish)
    monkeypatch.setattr(release.time, "sleep", sleeper)
    release.wait_fleets({"api_asg_name": "api", "relay_asg_name": "relay"})
    sleeper.assert_called_once()
    asg.describe_instance_refreshes.return_value = {
        "InstanceRefreshes": [{"Status": "Failed"}]
    }
    with pytest.raises(ValueError, match="refresh failed"):
        release.wait_fleets({"api_asg_name": "api", "relay_asg_name": "relay"})


def test_frontend_uploads_index_last_and_never_deletes_old_assets(
    context, monkeypatch, tmp_path
):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html></html>")
    monkeypatch.setenv("FRONTEND_BUNDLE", str(tmp_path))
    run = Mock()
    monkeypatch.setattr(release, "run", run)
    release.publish_frontend(release.release_config())
    commands = [call.args[0] for call in run.call_args_list]
    assert len(commands) == 3
    assert commands[0][4].endswith("/assets/")
    assert commands[-1][4].endswith("/index.html")
    assert all("--delete" not in command for command in commands)
