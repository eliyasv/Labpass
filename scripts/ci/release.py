"""Protected application releases for an already provisioned LabPass foundation."""

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import boto3
from botocore.config import Config

ROOT = Path(__file__).resolve().parents[2]
TF = ["terraform", f"-chdir={ROOT / 'infra/foundation'}"]
REGION = "us-east-1"
HEX_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
ENVIRONMENTS = ("labpass-publish", "labpass-plan", "labpass-apply")
UPDATE_FIELDS = {
    **{
        f'module.application.aws_launch_template.runtime["{name}"]': {
            "user_data",
            "latest_version",
            "default_version",
        }
        for name in ("api", "relay", "bootstrap", "migration")
    },
    "module.application.aws_autoscaling_group.api[0]": {"launch_template"},
    "module.application.aws_autoscaling_group.relay[0]": {"launch_template"},
    "module.confirmations.aws_lambda_function.confirmations[0]": {
        "image_uri",
        "code_sha256",
        "last_modified",
        "source_code_hash",
        "version",
        "qualified_arn",
        "qualified_invoke_arn",
        "source_code_size",
        "signing_job_arn",
        "signing_profile_version_arn",
    },
    "module.confirmations.aws_lambda_alias.confirmations[0]": {"function_version"},
}


def run(args, *, capture=False, **kwargs):
    return subprocess.run(
        args, cwd=ROOT, check=True, text=True, capture_output=capture, **kwargs
    )


def client(service):
    return boto3.client(
        service,
        region_name=REGION,
        config=Config(
            ignore_configured_endpoint_urls=True,
            connect_timeout=5,
            read_timeout=30,
            retries={"total_max_attempts": 3, "mode": "standard"},
        ),
    )


def required(name, pattern=None):
    value = os.environ.get(name, "")
    if not value or (pattern and re.fullmatch(pattern, value) is None):
        raise ValueError(f"Missing or invalid {name}")
    return value


def github(path):
    request = urllib.request.Request(
        "https://api.github.com/" + path,
        headers={
            "Authorization": "Bearer " + required("GH_TOKEN"),
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2026-03-10",
        },
    )
    # URL is fixed to the GitHub API; paths use validated repository/environment names.
    with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310
        return json.load(response)


def ensure_current():
    if required("GITHUB_REF") != "refs/heads/dev":
        raise ValueError("Releases require the dev branch")
    if required("GITHUB_RUN_ATTEMPT") != "1":
        raise ValueError("Start a new release run instead of rerunning individual jobs")
    repository = required("GITHUB_REPOSITORY", r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
    sha = required("GITHUB_SHA", r"[0-9a-f]{40}")
    if github(f"repos/{repository}/git/ref/heads/dev")["object"]["sha"] != sha:
        raise ValueError("The release commit is no longer the dev head")


def check_environment(settings, branches):
    reviewers = [
        rule
        for rule in settings.get("protection_rules", [])
        if rule.get("type") == "required_reviewers" and rule.get("reviewers")
    ]
    policy = settings.get("deployment_branch_policy") or {}
    allowed = branches.get("branch_policies", [])
    if not reviewers or not policy.get("custom_branch_policies"):
        raise ValueError(
            "Release environments require reviewers and a custom dev-only branch rule"
        )
    if (
        branches.get("total_count", len(allowed)) != 1
        or len(allowed) != 1
        or allowed[0].get("name") != "dev"
        or allowed[0].get("type", "branch") != "branch"
    ):
        raise ValueError("Release environments must allow only the exact dev branch")


def preflight():
    ensure_current()
    repository = required("GITHUB_REPOSITORY", r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
    for environment in ENVIRONMENTS:
        path = f"repos/{repository}/environments/{environment}"
        check_environment(github(path), github(path + "/deployment-branch-policies"))
    required("AWS_ACCOUNT_ID", r"[0-9]{12}")
    required("WORKLOAD_NAME_PREFIX", r"labpass-[a-z0-9][a-z0-9-]{0,29}")


def ensure_account():
    if client("sts").get_caller_identity()["Account"] != required(
        "AWS_ACCOUNT_ID", r"[0-9]{12}"
    ):
        raise ValueError("AWS account differs from the approved target")


def output(name, value):
    if "\n" in str(value) or "\r" in str(value):
        raise ValueError("Invalid workflow output")
    with open(required("GITHUB_OUTPUT"), "a") as stream:
        stream.write(f"{name}={value}\n")


def publish():
    ensure_current()
    ensure_account()
    account = required("AWS_ACCOUNT_ID", r"[0-9]{12}")
    prefix = required("WORKLOAD_NAME_PREFIX", r"labpass-[a-z0-9][a-z0-9-]{0,29}")
    registry = f"{account}.dkr.ecr.{REGION}.amazonaws.com"
    credentials = client("ecr").get_authorization_token()["authorizationData"][0]
    user, password = (
        base64.b64decode(credentials["authorizationToken"]).decode().split(":", 1)
    )
    with tempfile.TemporaryDirectory(prefix="labpass-docker-") as docker_config:
        docker = ["docker", "--config", docker_config]
        run(
            docker + ["login", "--username", user, "--password-stdin", registry],
            input=password,
            capture=True,
        )
        tag = (
            required("GITHUB_SHA", r"[0-9a-f]{40}")
            + "-"
            + required("GITHUB_RUN_ID", r"[0-9]+")
        )
        bundle = Path(required("RELEASE_BUNDLE"))
        for image in ("api", "lambda"):
            ensure_current()
            run(["docker", "load", "--input", str(bundle / f"{image}.tar")])
            destination = f"{registry}/{prefix}/{image}:{tag}"
            run(["docker", "tag", f"labpass-{image}:ci", destination])
            run(docker + ["push", destination])
            digest = client("ecr").describe_images(
                repositoryName=f"{prefix}/{image}",
                imageIds=[{"imageTag": tag}],
            )["imageDetails"][0]["imageDigest"]
            if HEX_DIGEST.fullmatch(digest) is None:
                raise ValueError("ECR returned an invalid digest")
            output(f"{image}_digest", digest)


def release_config():
    config = json.loads(required("FOUNDATION_TFVARS_JSON"))
    if (
        not isinstance(config, dict)
        or {"origin_verify_token", "origin_verify_previous_token"} & config.keys()
    ):
        raise ValueError(
            "Keep origin tokens in protected secrets, outside public configuration"
        )
    for key, value in {
        "aws_account_id": required("AWS_ACCOUNT_ID", r"[0-9]{12}"),
        "aws_region": REGION,
        "name_prefix": required(
            "WORKLOAD_NAME_PREFIX", r"labpass-[a-z0-9][a-z0-9-]{0,29}"
        ),
    }.items():
        if key in config and config[key] != value:
            raise ValueError(
                "Foundation configuration differs from delivery role scope"
            )
        config[key] = value
    if any(
        not isinstance(config.get(key), dict)
        for key in ("application", "frontend", "confirmation_worker")
    ):
        raise ValueError(
            "Provision application hosting, frontend delivery and the worker first"
        )
    if (
        config["application"].get("api_desired_capacity", 0) < 2
        or config["application"].get("relay_desired_capacity", 0) < 1
    ):
        raise ValueError(
            "Application releases require an already running API and relay fleet"
        )
    for variable, field in (
        ("API_DIGEST", "application"),
        ("LAMBDA_DIGEST", "confirmation_worker"),
    ):
        digest = required(variable)
        if HEX_DIGEST.fullmatch(digest) is None:
            raise ValueError("Release images require immutable digests")
        config[field]["image_digest"] = digest
    config["origin_verify_token"] = required("ORIGIN_VERIFY_TOKEN", r"[0-9a-f]{64}")
    previous = os.environ.get("ORIGIN_VERIFY_PREVIOUS_TOKEN", "")
    if previous:
        if not re.fullmatch(r"[0-9a-f]{64}", previous):
            raise ValueError("Invalid previous origin token")
        config["origin_verify_previous_token"] = previous
    return config


def config_hash(config):
    return hashlib.sha256(
        json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate_plan(plan):
    if plan.get("errored", False) or not plan.get("complete", True):
        raise ValueError("Terraform did not produce an applyable plan")
    summary = []
    for resource in plan.get("resource_changes", []):
        if resource.get("mode") == "data":
            continue
        if resource.get("previous_address"):
            raise ValueError("Release plans cannot change resource addresses")
        change = resource["change"]
        if change["actions"] == ["no-op"]:
            continue
        if not plan.get("applyable", True):
            raise ValueError("Terraform did not produce an applyable plan")
        address = resource["address"]
        if change["actions"] != ["update"] or address not in UPDATE_FIELDS:
            raise ValueError(
                "Release plans permit only updates to existing runtime resources"
            )
        before, after = change.get("before") or {}, change.get("after") or {}
        changed = {
            key
            for key in before.keys() | after.keys()
            if before.get(key) != after.get(key)
        }
        if changed - UPDATE_FIELDS[address]:
            raise ValueError(
                "Infrastructure or runtime configuration changes require a separate operator plan"
            )
        summary.append(address)
    return summary


def init_backend():
    bucket = required("STATE_BUCKET", r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]")
    run(
        TF
        + [
            "init",
            "-input=false",
            "-reconfigure",
            "-lockfile=readonly",
            f"-backend-config=bucket={bucket}",
            "-backend-config=key=foundation/terraform.tfstate",
            f"-backend-config=region={REGION}",
            "-backend-config=encrypt=true",
            "-backend-config=use_lockfile=true",
        ]
    )
    addresses = set(run(TF + ["state", "list"], capture=True).stdout.splitlines())
    if not set(UPDATE_FIELDS).issubset(addresses):
        raise ValueError("The complete foundation must already exist in remote state")


def plan():
    ensure_current()
    ensure_account()
    config = release_config()
    init_backend()
    with tempfile.TemporaryDirectory(prefix="labpass-plan-") as temporary:
        work = Path(temporary)
        variables = work / "release.tfvars.json"
        variables.write_text(json.dumps(config))
        variables.chmod(0o600)
        saved = work / "release.tfplan"
        run(
            TF
            + [
                "plan",
                "-input=false",
                "-lock-timeout=60s",
                f"-var-file={variables}",
                f"-out={saved}",
            ],
            capture=True,
        )
        parsed = json.loads(
            run(TF + ["show", "-json", str(saved)], capture=True).stdout
        )
        addresses = validate_plan(parsed)
        plan_bytes = saved.read_bytes()
        manifest = {
            "schema": 1,
            "sha": required("GITHUB_SHA"),
            "run_id": required("GITHUB_RUN_ID"),
            "config_hash": config_hash(config),
            "plan_hash": hashlib.sha256(plan_bytes).hexdigest(),
        }
        manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
        s3 = client("s3")
        bucket = required("STATE_BUCKET")
        if s3.get_bucket_versioning(Bucket=bucket).get("Status") != "Enabled":
            raise ValueError("Release plans require a private versioned bucket")
        prefix = f"plans/{required('GITHUB_RUN_ID', r'[0-9]+')}/"
        for name, content in (("plan", plan_bytes), ("manifest", manifest_bytes)):
            result = s3.put_object(
                Bucket=bucket,
                Key=prefix + name,
                Body=content,
                ServerSideEncryption="AES256",
                IfNoneMatch="*",
                ChecksumSHA256=base64.b64encode(
                    hashlib.sha256(content).digest()
                ).decode(),
            )
            version = result.get("VersionId")
            if not version or version == "null":
                raise ValueError("S3 did not return a versioned release object")
            output(f"{name}_version", version)
        output("manifest_hash", hashlib.sha256(manifest_bytes).hexdigest())
        with open(required("GITHUB_STEP_SUMMARY"), "a") as stream:
            stream.write("Release commit: `" + manifest["sha"] + "`\n\n")
            stream.write(
                "Planned runtime updates:\n\n"
                + "\n".join(f"- `{address}`" for address in addresses)
            )
            stream.write(
                "\n\nThe full plan is stored in private versioned S3, outside GitHub artifacts.\n"
            )


def verify_manifest(manifest_bytes, plan_bytes, config):
    if hashlib.sha256(manifest_bytes).hexdigest() != required(
        "MANIFEST_HASH", r"[0-9a-f]{64}"
    ):
        raise ValueError("Release manifest checksum mismatch")
    manifest = json.loads(manifest_bytes)
    expected = {
        "schema": 1,
        "sha": required("GITHUB_SHA"),
        "run_id": required("GITHUB_RUN_ID"),
        "config_hash": config_hash(config),
        "plan_hash": hashlib.sha256(plan_bytes).hexdigest(),
    }
    if manifest != expected:
        raise ValueError(
            "The approved release differs from the current commit, configuration or plan"
        )


def migrate(config):
    instance = required("MIGRATION_INSTANCE_ID", r"i-[0-9a-f]{17}")
    details = client("ec2").describe_instances(InstanceIds=[instance])["Reservations"][
        0
    ]["Instances"][0]
    tags = {tag["Key"]: tag["Value"] for tag in details.get("Tags", [])}
    account = required("AWS_ACCOUNT_ID")
    prefix = required("WORKLOAD_NAME_PREFIX")
    if (
        details["State"]["Name"] != "running"
        or details.get("PublicIpAddress")
        or tags.get("Project") != "LabPass"
        or tags.get("Component") != "migration"
        or details.get("IamInstanceProfile", {}).get("Arn")
        != f"arn:aws:iam::{account}:instance-profile/{prefix}-migration"
    ):
        raise ValueError(
            "The migration target is not the dedicated private operator instance"
        )
    ssm = client("ssm")
    command = ssm.send_command(
        InstanceIds=[instance],
        DocumentName=f"{prefix}-release-migration",
        DocumentVersion="$DEFAULT",
        Parameters={"ImageDigest": [config["application"]["image_digest"]]},
        TimeoutSeconds=600,
    )["Command"]["CommandId"]
    deadline = time.monotonic() + 660
    while time.monotonic() < deadline:
        try:
            invocation = ssm.get_command_invocation(
                CommandId=command, InstanceId=instance
            )
        except ssm.exceptions.InvocationDoesNotExist:
            time.sleep(5)
            continue
        status = invocation["Status"]
        if status == "Success":
            return
        if status not in {"Pending", "InProgress", "Delayed"}:
            raise ValueError("Migration failed; runtime rollout has not started")
        time.sleep(5)
    raise ValueError(
        "Migration did not finish; inspect SSM before starting another release"
    )


def wait_fleets(outputs):
    asg = client("autoscaling")
    names = [outputs["api_asg_name"], outputs["relay_asg_name"]]
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        complete = True
        for name in names:
            group = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[name])[
                "AutoScalingGroups"
            ][0]
            refreshes = asg.describe_instance_refreshes(
                AutoScalingGroupName=name, MaxRecords=1
            )["InstanceRefreshes"]
            if refreshes:
                status = refreshes[0]["Status"]
                if status in {
                    "Failed",
                    "Cancelled",
                    "RollbackFailed",
                    "RollbackSuccessful",
                }:
                    raise ValueError(
                        "EC2 refresh failed; inspect the fleet before another release"
                    )
                if status != "Successful":
                    complete = False
            instances = group["Instances"]
            desired = group["DesiredCapacity"]
            if (
                desired < 1
                or len(instances) != desired
                or any(
                    item["LifecycleState"] != "InService"
                    or item["HealthStatus"] != "Healthy"
                    or any(
                        item.get("LaunchTemplate", {}).get(key)
                        != group["LaunchTemplate"].get(key)
                        for key in ("LaunchTemplateId", "Version")
                    )
                    for item in instances
                )
            ):
                complete = False
        if complete:
            return
        time.sleep(15)
    raise ValueError("EC2 refresh did not finish within the release deadline")


def publish_frontend(config):
    ensure_current()
    bundle = Path(required("FRONTEND_BUNDLE"))
    if not (bundle / "index.html").is_file() or not (bundle / "assets").is_dir():
        raise ValueError("Frontend release artifact is incomplete")
    bucket = f"{config['name_prefix']}-{config['aws_account_id']}-frontend"
    run(
        [
            "aws",
            "s3",
            "cp",
            str(bundle / "assets"),
            f"s3://{bucket}/assets/",
            "--recursive",
            "--cache-control",
            "public,max-age=31536000,immutable",
            "--region",
            REGION,
        ]
    )
    run(
        [
            "aws",
            "s3",
            "cp",
            str(bundle),
            f"s3://{bucket}/",
            "--recursive",
            "--exclude",
            "assets/*",
            "--exclude",
            "index.html",
            "--cache-control",
            "no-cache",
            "--region",
            REGION,
        ]
    )
    ensure_current()
    run(
        [
            "aws",
            "s3",
            "cp",
            str(bundle / "index.html"),
            f"s3://{bucket}/index.html",
            "--content-type",
            "text/html",
            "--cache-control",
            "no-cache",
            "--region",
            REGION,
        ]
    )


def apply():
    ensure_current()
    ensure_account()
    config = release_config()
    init_backend()
    s3 = client("s3")
    objects = {}
    for name in ("plan", "manifest"):
        result = s3.get_object(
            Bucket=required("STATE_BUCKET"),
            Key=f"plans/{required('GITHUB_RUN_ID', r'[0-9]+')}/{name}",
            VersionId=required(f"{name.upper()}_VERSION"),
        )
        objects[name] = result["Body"].read()
    verify_manifest(objects["manifest"], objects["plan"], config)
    with tempfile.TemporaryDirectory(prefix="labpass-apply-") as temporary:
        saved = Path(temporary) / "approved.tfplan"
        saved.write_bytes(objects["plan"])
        saved.chmod(0o600)
        validate_plan(
            json.loads(run(TF + ["show", "-json", str(saved)], capture=True).stdout)
        )
        ensure_current()
        migrate(config)
        ensure_current()
        run(TF + ["apply", "-input=false", "-lock-timeout=60s", str(saved)])
        outputs = json.loads(
            run(TF + ["output", "-json", "application_hosting"], capture=True).stdout
        )
        wait_fleets(outputs)
        function = client("lambda").get_function_configuration(
            FunctionName=f"{config['name_prefix']}-confirmations", Qualifier="live"
        )
        if (
            function.get("State") != "Active"
            or function.get("LastUpdateStatus", "Successful") != "Successful"
        ):
            raise ValueError("Lambda alias is not ready")
        publish_frontend(config)
        origin = config["application"]["public_origin"]
        if not re.fullmatch(r"https://[a-z0-9.-]+", origin):
            raise ValueError("Invalid public smoke origin")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(origin + "/api/health/ready", timeout=15) as response:  # nosec B310
            if json.load(response) != {"status": "ok"}:
                raise ValueError("CloudFront readiness smoke failed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("preflight", "publish", "plan", "apply"))
    args = parser.parse_args()
    os.umask(0o077)
    try:
        {"preflight": preflight, "publish": publish, "plan": plan, "apply": apply}[
            args.operation
        ]()
    except ValueError as error:
        raise SystemExit(str(error)) from None
    except Exception as error:  # noqa: BLE001 -- sanitize SDK/process errors at the CLI boundary.
        raise SystemExit(
            f"Release failed ({type(error).__name__}); no automatic rollback performed"
        ) from None


if __name__ == "__main__":
    main()
