import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/xiaoh"
AGENT_SYSTEM = PLUGIN / "runtime/codex/agent-system"


class CleanBreakRuntimeTests(unittest.TestCase):
    def test_manifest_has_exact_public_surface(self):
        manifest = json.loads((PLUGIN / "install-manifest.json").read_text())
        self.assertEqual("3.1.2", manifest["version"])
        self.assertEqual(27, len(manifest["bundled_skills"]))
        self.assertEqual(5, len(manifest["managed_agents"]))
        self.assertEqual(
            {"frontend_implementer", "java_architect", "java_code_explorer", "java_implementer", "pki_domain_expert"},
            set(manifest["managed_agents"]),
        )
        self.assertIn("spec-rfc-reviewer", manifest["bundled_skills"])
        self.assertIn("spec-rfc-openspec-consistency-review", manifest["bundled_skills"])

    def test_requirement_review_skills_are_single_pass(self):
        for name in ("spec-rfc-reviewer", "spec-rfc-openspec-consistency-review"):
            text = (PLUGIN / "skills" / name / "SKILL.md").read_text()
            self.assertIn("一次", text)
            self.assertIn("不自动", text)
            self.assertNotIn("直到获得", text)

    def test_removed_runtime_assets_do_not_exist(self):
        removed = [
            "skills/xiaoh-local-review", "skills/xiaoh-knowledge-review",
            "runtime/codex/agents/code_quality_reviewer.toml",
            "runtime/codex/agents/test_integration_verifier.toml",
            "runtime/codex/agents/pki_security_reviewer.toml",
            "compatibility", "xiaoh_runtime/upgrade", "xiaoh_runtime/_compat.py",
        ]
        self.assertEqual([], [item for item in removed if (PLUGIN / item).exists()])

    def test_validator_and_hook_self_tests(self):
        env = {**os.environ, "PYTHONPATH": str(AGENT_SYSTEM)}
        for command in (
            [sys.executable, str(AGENT_SYSTEM / "validate.py"), "--self-test"],
            [sys.executable, str(PLUGIN / "runtime/codex/hooks/block_reserved_root_agent.py"), "--self-test"],
            [sys.executable, str(PLUGIN / "runtime/codex/hooks/guard_vault_writes.py"), "--self-test"],
        ):
            completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_task_context_template_is_valid(self):
        env = {**os.environ, "PYTHONPATH": str(AGENT_SYSTEM)}
        completed = subprocess.run(
            [sys.executable, str(AGENT_SYSTEM / "validate.py"), "--task-context", str(AGENT_SYSTEM / "task-context.template.json")],
            cwd=ROOT, env=env, capture_output=True, text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_launcher_plan_is_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            completed = subprocess.run(
                [sys.executable, str(PLUGIN / "scripts/xiaoh.py"), "plan", "--json", "--codex-home", str(base / "codex"), "--vault", str(base / "vault"), "--config", str(base / "config.json")],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual("passed", payload["status"])
            self.assertFalse((base / "codex").exists())
            self.assertFalse((base / "vault").exists())

    def test_compatible_workbench_customization_is_healthy(self):
        sys.path.insert(0, str(PLUGIN))
        try:
            from xiaoh_runtime.vault_runtime import vault_template_report
            with tempfile.TemporaryDirectory() as temp:
                vault = Path(temp)
                source = PLUGIN / "runtime/obsidian/development-vault"
                for path in source.rglob("*"):
                    if path.is_file():
                        destination = vault / path.relative_to(source)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(path.read_bytes())
                workbench = vault / "00-工作台/我的工作台.base"
                workbench.write_text(workbench.read_text() + "\n# user view preference\n")
                report = vault_template_report(vault)
                item = next(item for item in report["files"] if item["path"] == "00-工作台/我的工作台.base")
                self.assertEqual("complete", report["status"])
                self.assertEqual("user_customized_compatible", item["state"])
        finally:
            sys.path.remove(str(PLUGIN))

    def test_playbook_adapter_exposes_worker_only_commands(self):
        completed = subprocess.run(
            [sys.executable, str(AGENT_SYSTEM / "playbook_adapter.py"), "--help"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(0, completed.returncode)
        self.assertIn("capture", completed.stdout)
        self.assertNotIn("capture-review", completed.stdout)

    def test_failed_verification_cannot_close(self):
        sys.path.insert(0, str(AGENT_SYSTEM))
        try:
            from xiaoh_validator.delegation import closure_rejection_reasons
            record = {
                "schema_version": "1.2", "status": "completed",
                "gates": [{"status": "passed"}],
                "verification": [{"status": "failed"}],
                "metrics": {"result_accepted": True},
            }
            self.assertTrue(closure_rejection_reasons(record))
            record["verification"][0]["status"] = "passed"
            self.assertEqual([], closure_rejection_reasons(record))
        finally:
            sys.path.remove(str(AGENT_SYSTEM))

    def test_clean_install_in_isolated_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            vault = base / "vault"
            (vault / ".obsidian").mkdir(parents=True)
            completed = subprocess.run(
                [sys.executable, str(PLUGIN / "scripts/xiaoh.py"), "setup", "--json", "--allow-degraded", "--codex-home", str(base / "codex"), "--vault", str(vault), "--config", str(base / "xiaoh.json")],
                cwd=ROOT, capture_output=True, text=True,
            )
            payload = json.loads(completed.stdout)
            self.assertIn(payload["status"], {"passed", "degraded"}, completed.stdout + completed.stderr)
            self.assertEqual([], payload["errors"])
            installed = json.loads((base / "xiaoh.json").read_text())
            self.assertEqual("3.1.2", installed["installed_version"])
            agents = {path.stem for path in (base / "codex/agents").glob("*.toml")}
            self.assertEqual(set(json.loads((PLUGIN / "install-manifest.json").read_text())["managed_agents"]), agents)
            self.assertFalse((vault / "02-领域知识/知识评审模板.md").exists())


if __name__ == "__main__":
    unittest.main()
