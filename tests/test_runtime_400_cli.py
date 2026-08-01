from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from plugins.xiaoh.xiaoh_runtime.interface.cli import command_failure


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "plugins/xiaoh/scripts/xiaoh.py"


class Runtime400CliTests(unittest.TestCase):
    def test_plan_uses_v2_envelope_and_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            completed = _run(
                "plan",
                "--json",
                "--codex-home",
                str(root / "codex"),
                "--vault",
                str(root / "vault"),
                "--config",
                str(root / "xiaoh/config.json"),
            )
            payload = json.loads(completed.stdout)

            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertEqual("xiaoh-cli-response/v2", payload["schema_version"])
            self.assertEqual("plan", payload["operation"])
            self.assertEqual([], payload["actual_writes"])
            self.assertFalse((root / "codex").exists())
            self.assertFalse((root / "vault").exists())
            self.assertFalse((root / "xiaoh").exists())

    def test_setup_uses_transaction_response_in_explicit_temporary_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            vault = root / "vault"
            (vault / ".obsidian").mkdir(parents=True)
            completed = _run(
                "setup",
                "--json",
                "--codex-home",
                str(root / "codex"),
                "--vault",
                str(vault),
                "--config",
                str(root / "xiaoh/config.json"),
            )
            payload = json.loads(completed.stdout)

            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertEqual("committed", payload["phase"])
            self.assertTrue(payload["transaction_id"])
            self.assertEqual("runtime_unverified", payload["activation_state"])
            self.assertTrue(payload["actual_writes"])

    def test_expected_argument_failure_has_no_traceback(self) -> None:
        completed = _run("register-workspace", "--json")
        payload = json.loads(completed.stdout)

        self.assertNotEqual(0, completed.returncode)
        self.assertEqual("failed", payload["status"])
        self.assertEqual("xiaoh-cli-response/v2", payload["schema_version"])
        self.assertNotIn("Traceback", completed.stdout + completed.stderr)

    def test_command_failure_redacts_secret_material(self) -> None:
        result = command_failure(
            SimpleNamespace(command="setup"),
            ValueError(
                "token=never-expose-this Bearer abc.def password:also-never-expose"
            ),
        )

        encoded = json.dumps(result)
        self.assertNotIn("never-expose", encoded)
        self.assertNotIn("abc.def", encoded)
        self.assertIn("[REDACTED]", encoded)

    def test_companions_runs_skill_governance_without_installing(self) -> None:
        completed = _run("companions", "--json")
        payload = json.loads(completed.stdout)

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertEqual("passed", payload["status"])
        self.assertEqual("passed", payload["skill_governance"]["status"])

    def test_register_workspace_uses_explicit_config_and_reports_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "xiaoh/config.json"
            completed = _run(
                "register-workspace",
                "--json",
                "--codex-home",
                str(root / "codex"),
                "--vault",
                str(root / "vault"),
                "--config",
                str(config),
                "--workspace-id",
                "demo",
                "--project",
                "project",
                "--system",
                "system",
                "--root",
                str(root / "workspace"),
            )
            payload = json.loads(completed.stdout)

            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertEqual([str(config.resolve())], payload["actual_writes"])
            self.assertEqual("demo", payload["workspace_id"])

    def test_explicit_test_targets_override_machine_default_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            explicit = root / "explicit"
            vault = explicit / "vault"
            (vault / ".obsidian").mkdir(parents=True)
            defaults = root / "must-not-touch"
            environment = {
                **os.environ,
                "HOME": str(defaults / "home"),
                "CODEX_HOME": str(defaults / "codex"),
                "XIAOH_VAULT": str(defaults / "vault"),
                "XIAOH_CONFIG": str(defaults / "xiaoh/config.json"),
            }
            completed = subprocess.run(
                [
                    sys.executable,
                    str(LAUNCHER),
                    "setup",
                    "--json",
                    "--codex-home",
                    str(explicit / "codex"),
                    "--vault",
                    str(vault),
                    "--config",
                    str(explicit / "xiaoh/config.json"),
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
            )

            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertFalse((defaults / "codex").exists())
            self.assertFalse((defaults / "vault").exists())
            self.assertFalse((defaults / "xiaoh").exists())


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(LAUNCHER), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


if __name__ == "__main__":
    unittest.main()
