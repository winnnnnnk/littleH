from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from plugins.xiaoh.xiaoh_runtime.adapters.local import LocalFileSystem
from plugins.xiaoh.xiaoh_runtime.diagnostics.doctor import (
    AutomationDiagnostic,
    DiagnosticContext,
    DoctorRunner,
    HookDiagnostic,
    PlaybookDiagnostic,
    PluginDiagnostic,
    default_diagnostics,
)
from plugins.xiaoh.xiaoh_runtime.domain.models import DiagnosticResult, DiagnosticStatus
from plugins.xiaoh.xiaoh_runtime.ports.protocols import ProcessResult
from plugins.xiaoh.runtime.codex.hooks import verify_agent_hook_runtime


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/xiaoh"


class _ExplodingDiagnostic:
    diagnostic_id = "exploding"

    def run(self, context: DiagnosticContext) -> DiagnosticResult:
        raise RuntimeError("diagnostic failed token=never-expose-this")


class _PassingDiagnostic:
    diagnostic_id = "passing"

    def run(self, context: DiagnosticContext) -> DiagnosticResult:
        return DiagnosticResult(self.diagnostic_id, DiagnosticStatus.PASSED)


class _TrustRunner:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode
        self.commands = []

    def run(self, command, env=None, cwd=None):
        self.commands.append(list(command))
        return ProcessResult(
            self.returncode,
            "trusted token=never-expose-this" if self.returncode == 0 else "",
            "secret=never-expose-this" if self.returncode else "",
        )


class _PlaybookRunner:
    def __init__(self, responses):
        self.responses = list(responses)
        self.commands = []

    def run(self, command, env=None, cwd=None):
        self.commands.append(list(command))
        return self.responses.pop(0)


class _AutomationStore:
    def __init__(self, tasks):
        self.tasks = {item["id"]: dict(item) for item in tasks}

    def get(self, task_id):
        return self.tasks.get(task_id)

    def list(self):
        return list(self.tasks.values())

    def create(self, logical_id, values):
        raise AssertionError("Doctor must not create automations")

    def update(self, task_id, values):
        raise AssertionError("Doctor must not update automations")


class Runtime400DoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fs = LocalFileSystem()

    def test_unexpected_failure_does_not_stop_independent_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context = DiagnosticContext(
                filesystem=self.fs,
                plugin_root=PLUGIN,
                codex_home=root / "codex",
                vault=root / "vault",
                config_path=root / "xiaoh.json",
            )
            report = DoctorRunner([_ExplodingDiagnostic(), _PassingDiagnostic()]).run(context)

            statuses = {item.diagnostic_id: item.status.value for item in report.diagnostics}
            self.assertEqual("failed", statuses["exploding"])
            self.assertEqual("passed", statuses["passing"])
            self.assertNotIn("never-expose-this", json.dumps(report.to_dict()))

    def test_default_doctor_reports_every_independent_area_and_never_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex = root / "codex"
            vault = root / "vault"
            config = root / "xiaoh.json"
            codex.mkdir()
            vault.mkdir()
            config.write_text("{}\n", encoding="utf-8")
            before = _snapshot(root)
            context = DiagnosticContext(
                filesystem=self.fs,
                plugin_root=PLUGIN,
                codex_home=codex,
                vault=vault,
                config_path=config,
            )

            report = DoctorRunner(default_diagnostics()).run(context).to_dict()

            self.assertEqual(before, _snapshot(root))
            ids = {item["diagnostic_id"] for item in report["diagnostics"]}
            self.assertEqual(
                {
                    "plugin",
                    "skill-governance",
                    "loaded-skill",
                    "managed-runtime",
                    "agents",
                    "hooks",
                    "validator",
                    "vault",
                    "workspace",
                    "automation",
                    "playbook",
                },
                ids,
            )
            self.assertGreaterEqual(
                sum(item["status"] == "failed" for item in report["diagnostics"]),
                3,
            )
            self.assertEqual([], report["actual_writes"])
            self.assertEqual("xiaoh-doctor-report/v2", report["schema_version"])
            self.assertIn(report["effective_status"], {"degraded", "failed"})

    def test_matching_install_version_does_not_claim_runtime_activation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex = root / "codex"
            vault = root / "vault"
            config = root / "xiaoh.json"
            codex.mkdir()
            (vault / ".obsidian").mkdir(parents=True)
            config.write_text(
                json.dumps(
                    {
                        "schema_version": "xiaoh-config/v2",
                        "installed_version": "4.0.0",
                        "codex_home": str(codex),
                        "obsidian_vault": str(vault),
                    }
                ),
                encoding="utf-8",
            )
            context = DiagnosticContext(
                filesystem=self.fs,
                plugin_root=PLUGIN,
                codex_home=codex,
                vault=vault,
                config_path=config,
                runtime_requested=True,
                active_skill_root=None,
                runtime_facts={},
            )

            report = DoctorRunner(default_diagnostics()).run(context)

            self.assertEqual("runtime_unverified", report.activation_state.value)
            loaded_skill = next(
                item for item in report.diagnostics if item.diagnostic_id == "loaded-skill"
            )
            self.assertEqual(DiagnosticStatus.UNVERIFIED, loaded_skill.status)

    def test_runtime_hook_probe_is_read_only_and_redacts_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex = root / "codex"
            hooks = codex / "hooks"
            hooks.mkdir(parents=True)
            for name in (
                "block_reserved_root_agent.py",
                "block_reserved_root_agent.ps1",
                "guard_vault_writes.py",
                "guard_task_writes.py",
                "verify_agent_hook_runtime.py",
            ):
                (hooks / name).write_text("# hook\n", encoding="utf-8")
            (codex / "config.toml").write_text(
                "# xiaoh-root-agent-hook:start\n", encoding="utf-8"
            )
            runner = _TrustRunner()
            context = DiagnosticContext(
                filesystem=self.fs,
                plugin_root=PLUGIN,
                codex_home=codex,
                vault=root / "vault",
                config_path=root / "config.json",
                process_runner=runner,
                runtime_requested=True,
            )

            result = HookDiagnostic().run(context)

            self.assertEqual(DiagnosticStatus.PASSED, result.status)
            self.assertTrue(result.facts["trust"])
            self.assertNotIn("never-expose-this", json.dumps(result.to_dict()))
            self.assertEqual("--codex-home", runner.commands[0][2])

    def test_runtime_hook_probe_rejects_invalid_subagent_start_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            codex = Path(temp) / "codex"
            hooks = codex / "hooks"
            hooks.mkdir(parents=True)
            delegation_hook = hooks / "block_reserved_root_agent.py"
            delegation_hook.write_text(
                "import json\n"
                "print(json.dumps({'hookSpecificOutput': "
                "{'additionalContext': 'missing event name'}}))\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "hookEventName"):
                verify_agent_hook_runtime.verify_subagent_start_protocol(codex)

            delegation_hook.write_text(
                "import json\n"
                "print(json.dumps({'hookSpecificOutput': {"
                "'hookEventName': 'SubagentStart', "
                "'additionalContext': 'unauthorized'}}))\n",
                encoding="utf-8",
            )

            verify_agent_hook_runtime.verify_subagent_start_protocol(codex)

    def test_plugin_runtime_facts_redact_nested_sensitive_values(self) -> None:
        context = DiagnosticContext(
            filesystem=self.fs,
            plugin_root=PLUGIN,
            codex_home=Path("/tmp/codex"),
            vault=Path("/tmp/vault"),
            config_path=Path("/tmp/config.json"),
            runtime_requested=True,
            runtime_facts={
                "active_plugin": {
                    "version": "4.0.0",
                    "nested": {"access_token": "never-expose-this"},
                }
            },
        )

        result = PluginDiagnostic().run(context)

        self.assertEqual(DiagnosticStatus.PASSED, result.status)
        self.assertNotIn("never-expose-this", json.dumps(result.to_dict()))

    def test_enabled_playbook_runs_only_two_read_only_version_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "config.json"
            config.write_text(
                json.dumps({"integrations": {"playbook": "enabled"}}),
                encoding="utf-8",
            )
            runner = _PlaybookRunner(
                [
                    ProcessResult(0, "playbook 9.9.9 token=never-expose-this"),
                    ProcessResult(0, "compatible secret=never-expose-this"),
                ]
            )
            context = DiagnosticContext(
                filesystem=self.fs,
                plugin_root=PLUGIN,
                codex_home=root / "codex",
                vault=root / "vault",
                config_path=config,
                process_runner=runner,
                runtime_requested=True,
            )

            result = PlaybookDiagnostic().run(context)

            self.assertEqual(DiagnosticStatus.PASSED, result.status)
            self.assertEqual(
                [["playbook", "--version"], ["playbook", "version", "check"]],
                runner.commands,
            )
            self.assertNotIn("never-expose-this", json.dumps(result.to_dict()))

    def test_playbook_compatibility_check_failure_is_actionable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "config.json"
            config.write_text(
                json.dumps({"integrations": {"playbook": True}}),
                encoding="utf-8",
            )
            runner = _PlaybookRunner(
                [ProcessResult(0, "playbook 9.9.9"), ProcessResult(1, "", "incompatible")]
            )
            context = DiagnosticContext(
                filesystem=self.fs,
                plugin_root=PLUGIN,
                codex_home=root / "codex",
                vault=root / "vault",
                config_path=config,
                process_runner=runner,
                runtime_requested=True,
            )

            result = PlaybookDiagnostic().run(context)

            self.assertEqual(DiagnosticStatus.FAILED, result.status)
            self.assertIn("Playbook version check failed", result.errors)
            self.assertEqual(["maintain the Playbook CLI manually"], result.remediation)

    def test_runtime_automation_diagnostic_reads_back_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "config.json"
            template = json.loads(
                (PLUGIN / "managed-automations.json").read_text(encoding="utf-8")
            )["templates"][0]
            config.write_text(
                json.dumps(
                    {
                        "automation_bindings": {
                            template["logical_id"]: {"task_id": "task-1"}
                        }
                    }
                ),
                encoding="utf-8",
            )
            store = _AutomationStore(
                [
                    {
                        "id": "task-1",
                        "name": template["name"],
                        "prompt": template["prompt"],
                    }
                ]
            )
            before = config.read_bytes()
            context = DiagnosticContext(
                filesystem=self.fs,
                plugin_root=PLUGIN,
                codex_home=root / "codex",
                vault=root / "vault",
                config_path=config,
                runtime_requested=True,
                automation_store=store,
            )

            result = AutomationDiagnostic().run(context)

            self.assertEqual(DiagnosticStatus.PASSED, result.status)
            self.assertTrue(result.runtime_checked)
            self.assertEqual("configured", result.facts["tasks"][0]["state"])
            self.assertEqual(before, config.read_bytes())

    def test_runtime_automation_diagnostic_is_unverified_without_store(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "config.json"
            template = json.loads(
                (PLUGIN / "managed-automations.json").read_text(encoding="utf-8")
            )["templates"][0]
            config.write_text(
                json.dumps(
                    {
                        "automation_bindings": {
                            template["logical_id"]: {"task_id": "task-1"}
                        }
                    }
                ),
                encoding="utf-8",
            )
            context = DiagnosticContext(
                filesystem=self.fs,
                plugin_root=PLUGIN,
                codex_home=root / "codex",
                vault=root / "vault",
                config_path=config,
                runtime_requested=True,
            )

            result = AutomationDiagnostic().run(context)

            self.assertEqual(DiagnosticStatus.UNVERIFIED, result.status)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


if __name__ == "__main__":
    unittest.main()
