"""Enforce workflow trust boundaries, immutable pins and scoped scan exceptions."""

import datetime
import hashlib
import importlib.util
import io
import json
import re
import tarfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def workflow(name):
    # BaseLoader retains the Actions key `on` instead of coercing it to YAML 1.1 true.
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


class WorkflowControls(unittest.TestCase):
    def test_external_actions_use_full_commit_shas(self):
        files = list((ROOT / ".github").rglob("*.yml"))
        for path in files:
            document = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
            def visit(value):
                if isinstance(value, dict):
                    if "uses" in value and not value["uses"].startswith("./"):
                        self.assertRegex(value["uses"], r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}$", str(path))
                    for item in value.values():
                        visit(item)
                elif isinstance(value, list):
                    for item in value:
                        visit(item)
            visit(document)

    def test_pr_jobs_cannot_request_oidc_or_repository_writes(self):
        ci = workflow("ci.yml")
        self.assertNotIn("pull_request_target", ci["on"])
        self.assertEqual(ci["permissions"], {"contents": "read"})
        for job in ci["jobs"].values():
            self.assertNotIn("environment", job)
            self.assertNotIn("write", (job.get("permissions") or {}).values())
            self.assertNotIn("configure-aws-credentials", json.dumps(job))
        gate = ci["jobs"]["ci-gate"]
        self.assertEqual(set(gate["needs"]), set(ci["jobs"]) - {"ci-gate"})
        self.assertEqual(gate["if"], "always()")
        self.assertIn("!= 'success'", gate["steps"][0]["run"])

    def test_release_requires_verification_and_exact_protected_environments(self):
        release = workflow("release.yml")
        self.assertEqual(set(release["on"]), {"workflow_dispatch"})
        self.assertEqual(release["concurrency"]["cancel-in-progress"], "false")
        jobs = release["jobs"]
        self.assertEqual(jobs["verify"]["uses"], "./.github/workflows/ci.yml")
        self.assertNotIn("secrets", jobs["verify"])
        self.assertIn("verify", jobs["publish"]["needs"])
        self.assertEqual(jobs["plan"]["needs"], "publish")
        self.assertIn("plan", jobs["apply"]["needs"])
        for name in ("publish", "plan", "apply"):
            job = jobs[name]
            self.assertEqual(job["if"], "github.ref == 'refs/heads/dev'")
            self.assertEqual(job["environment"], "labpass-" + name)
            self.assertEqual(job["permissions"], {"contents": "read", "id-token": "write"})
            steps = job["steps"]
            authentication = next(i for i, step in enumerate(steps) if "configure-aws-credentials@" in step.get("uses", ""))
            self.assertTrue(any(step.get("uses") == "./.github/actions/release-tools" for step in steps[:authentication]))
            self.assertEqual(steps[authentication]["with"]["allowed-account-ids"], "${{ vars.AWS_ACCOUNT_ID }}")
        self.assertNotIn("upload-artifact", json.dumps(jobs["plan"]))

    def test_scanners_and_dependency_installs_fail_closed(self):
        ci = workflow("ci.yml")
        steps = json.dumps(ci["jobs"]["security"]["steps"])
        for tool in ("gitleaks git", "bandit", "pip-audit", "npm --prefix frontend audit", "trivy config", "actionlint"):
            self.assertIn(tool, steps)
        image_steps = json.dumps(ci["jobs"]["images"]["steps"])
        self.assertIn("--severity HIGH,CRITICAL --exit-code 1", image_steps)
        self.assertNotIn("--ignore-unfixed", image_steps)
        self.assertIn("--target release", image_steps)
        self.assertIn('find_spec(\\"pip\\") is None', image_steps)
        self.assertIn('find_spec(\\"ensurepip\\") is None', image_steps)
        self.assertIn("Offline Lambda runtime verification", image_steps)
        self.assertNotIn("continue-on-error", json.dumps(ci))
        for filename in ("backend/requirements.lock", "backend/requirements-dev.lock", "security/requirements.lock"):
            lock = (ROOT / filename).read_text()
            self.assertNotIn("--index-url", lock)
            for entry in re.split(r"\n(?=[A-Za-z0-9])", lock):
                if "==" in entry:
                    self.assertIn("--hash=sha256:", entry, filename)

    def test_security_tool_downloads_have_https_release_urls_and_sha256(self):
        for tool in json.loads((ROOT / "security/tools.json").read_text()).values():
            self.assertRegex(tool["sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(tool["url"].startswith("https://github.com/"))
            self.assertIn("/releases/download/", tool["url"])

    def test_scan_exceptions_expire_and_are_file_scoped(self):
        exceptions = yaml.safe_load((ROOT / "security/trivy-exceptions.yaml").read_text())
        for entries in exceptions.values():
            for entry in entries:
                self.assertTrue(entry["statement"])
                self.assertGreaterEqual(entry["expired_at"], datetime.date.today())
                self.assertTrue(entry["paths"])
                for path in entry["paths"]:
                    self.assertNotIn("*", path)
                    self.assertTrue((ROOT / path).is_file())


class VerifiedInstaller(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("install_tools", ROOT / "scripts/ci/install-tools.py")
        cls.installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.installer)

    def archive(self, *, symlink=False):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            member = tarfile.TarInfo("scanner")
            if symlink:
                member.type = tarfile.SYMTYPE
                member.linkname = "/etc/passwd"
                archive.addfile(member)
            else:
                member.size = 4
                archive.addfile(member, io.BytesIO(b"tool"))
            unrelated = tarfile.TarInfo("../../outside")
            unrelated.size = 3
            archive.addfile(unrelated, io.BytesIO(b"bad"))
        return stream.getvalue()

    def test_extracts_only_verified_regular_binary(self):
        content = self.archive()
        self.assertEqual(self.installer.binary_from_archive(content, "scanner", hashlib.sha256(content).hexdigest()), b"tool")

    def test_rejects_tampered_archive_before_parsing(self):
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.installer.binary_from_archive(b"not an archive", "scanner", "0" * 64)

    def test_rejects_binary_symlinks(self):
        content = self.archive(symlink=True)
        with self.assertRaisesRegex(ValueError, "regular file"):
            self.installer.binary_from_archive(content, "scanner", hashlib.sha256(content).hexdigest())


if __name__ == "__main__":
    unittest.main()
