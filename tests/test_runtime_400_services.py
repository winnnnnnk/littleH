from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from plugins.xiaoh.xiaoh_runtime.adapters.local import LocalFileSystem
from plugins.xiaoh.xiaoh_runtime.adapters.plugins import CodexPluginFacts
from plugins.xiaoh.xiaoh_runtime.application.runtime import RuntimeApplication, RuntimePaths
from plugins.xiaoh.xiaoh_runtime.ports.protocols import ProcessResult
from plugins.xiaoh.xiaoh_runtime.installation.planner import InstallationPlanner
from plugins.xiaoh.xiaoh_runtime.services.automation import AutomationService
from plugins.xiaoh.xiaoh_runtime.services.configuration import ConfigurationService
from plugins.xiaoh.xiaoh_runtime.services.workspace import WorkspaceService


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/xiaoh"


class _PluginListRunner:
    def __init__(self, result: ProcessResult):
        self.result = result
        self.commands = []

    def run(self, command, env=None, cwd=None):
        self.commands.append(list(command))
        return self.result


class _UnexpectedPluginFacts:
    def current_facts(self):
        raise AssertionError("plugin facts must remain opt-in")


class _Clock:
    def now(self):
        raise AssertionError("clock is not used by companions")


class _AutomationStore:
    def __init__(self, tasks):
        self.tasks = {item["id"]: dict(item) for item in tasks}

    def get(self, task_id):
        return self.tasks.get(task_id)

    def list(self):
        return list(self.tasks.values())

    def create(self, logical_id, values):
        raise AssertionError("XiaoH does not create automations")

    def update(self, task_id, values):
        raise AssertionError("XiaoH does not update automations")


class Runtime400ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fs = LocalFileSystem()

    def test_installation_plan_is_complete_and_byte_for_byte_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex = root / "codex"
            vault = root / "vault"
            config = root / "xiaoh/config.json"
            before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))

            plan = InstallationPlanner(self.fs, PLUGIN).create_plan(
                operation="setup",
                codex_home=codex,
                vault=vault,
                config_path=config,
            )

            after = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
            payload = plan.to_dict()
            self.assertEqual(before, after)
            self.assertEqual("4.0.0", payload["target_version"])
            self.assertEqual([], payload["actual_writes"])
            self.assertTrue(payload["assets"])
            self.assertFalse(
                any(
                    "__pycache__" in item["source"]
                    or item["source"].endswith((".pyc", ".pyo"))
                    for item in payload["assets"]
                )
            )
            self.assertIn(str(config.resolve()), payload["expected_creates"])
            self.assertTrue(payload["candidate_requirements"])
            self.assertTrue(payload["backup_requirements"])
            self.assertTrue(payload["recovery_conditions"])

    def test_configuration_import_keeps_only_durable_non_sensitive_state(self) -> None:
        source = {
            "installed_version": "3.1.2",
            "workspaces": {"demo": {"project": "p", "system": "s", "roots": {"darwin": "/tmp/p"}}},
            "preferences": {"language": "zh-CN"},
            "managed_automations": {
                "daily": {
                    "task_id": "old-runtime-id",
                    "schedule": "0 9 * * *",
                    "timezone": "Asia/Shanghai",
                    "enabled": False,
                }
            },
            "integrations": {"playbook": "auto", "token": "secret-token"},
            "delegation_bindings": {"one-time": {"receipt": "secret"}},
            "transaction": {"phase": "switching"},
            "password": "do-not-copy",
        }

        imported, evidence = ConfigurationService(self.fs).import_312_durable_state(source)
        encoded = json.dumps(imported, ensure_ascii=False)

        self.assertEqual(source["workspaces"], imported["workspaces"])
        self.assertEqual("0 9 * * *", imported["automation_preferences"]["daily"]["schedule"])
        self.assertNotIn("task_id", imported["automation_preferences"]["daily"])
        self.assertNotIn("secret-token", encoded)
        self.assertNotIn("delegation_bindings", imported)
        self.assertNotIn("transaction", imported)
        self.assertTrue(all(item["conversion_version"] == "4.0.0" for item in evidence))

    def test_workspace_uses_unique_longest_active_platform_root(self) -> None:
        service = WorkspaceService(platform_name="darwin")
        config = {
            "workspaces": {
                "parent": {"project": "p", "system": "s", "roots": {"darwin": "/work"}},
                "child": {"project": "p2", "system": "s2", "roots": {"darwin": "/work/child"}},
            }
        }

        result = service.resolve(config, Path("/work/child/src"))

        self.assertEqual("resolved", result["status"])
        self.assertEqual("child", result["workspace_id"])

    def test_workspace_rejects_equal_strength_conflict(self) -> None:
        service = WorkspaceService(platform_name="darwin")
        config = {
            "workspaces": {
                "one": {"project": "p", "system": "s", "roots": {"darwin": "/work/same"}},
                "two": {"project": "p2", "system": "s2", "roots": {"darwin": "/work/same"}},
            }
        }

        result = service.resolve(config, Path("/work/same/src"))

        self.assertEqual("conflict", result["status"])
        self.assertEqual(["one", "two"], result["candidates"])

    def test_plugin_facts_allowlist_excludes_paths_and_secrets(self) -> None:
        runner = _PluginListRunner(
            ProcessResult(
                0,
                json.dumps(
                    {
                        "plugins": [
                            {
                                "id": "example",
                                "name": "Example",
                                "version": "1.2.3",
                                "enabled": True,
                                "path": "/private/plugin/path",
                                "access_token": "never-expose-this",
                                "nested": {"password": "never-expose-this"},
                            }
                        ]
                    }
                ),
            )
        )

        facts = CodexPluginFacts(runner).current_facts()
        encoded = json.dumps(facts)

        self.assertEqual([["codex", "plugin", "list", "--json"]], runner.commands)
        self.assertEqual("available", facts["status"])
        self.assertEqual(
            {"id": "example", "name": "Example", "version": "1.2.3", "enabled": True},
            facts["plugins"][0],
        )
        self.assertNotIn("/private/plugin/path", encoded)
        self.assertNotIn("never-expose-this", encoded)

    def test_plugin_facts_failure_is_reported_without_raw_output(self) -> None:
        runner = _PluginListRunner(
            ProcessResult(1, "token=never-expose-this", "password=never-expose-this")
        )

        facts = CodexPluginFacts(runner).current_facts()

        self.assertEqual("unavailable", facts["status"])
        self.assertNotIn("never-expose-this", json.dumps(facts))

    def test_companion_plugin_query_is_explicitly_opt_in(self) -> None:
        application = RuntimeApplication(
            self.fs,
            _Clock(),
            PLUGIN,
            plugin_facts=_UnexpectedPluginFacts(),
        )

        result = application.companions()

        self.assertEqual("passed", result["status"])
        self.assertEqual("not_checked", result["plugin_facts"]["status"])

    def test_automation_binding_preserves_preferences_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "xiaoh/config.json"
            ConfigurationService(self.fs).write(
                config,
                {
                    "schema_version": "xiaoh-config/v2",
                    "installed_version": "4.0.0",
                    "automation_preferences": {},
                },
            )
            template = AutomationService(self.fs, PLUGIN).templates()[
                "xiaoh.daily-progress"
            ]
            store = _AutomationStore(
                [
                    {
                        "id": "task-1",
                        "name": template["name"],
                        "prompt": template["prompt"],
                        "status": template["default_status"],
                        "schedule": "0 8 * * *",
                        "timezone": "Asia/Shanghai",
                        "notification": "silent",
                    }
                ]
            )
            application = RuntimeApplication(
                self.fs,
                _Clock(),
                PLUGIN,
                automation_store_factory=lambda filesystem, codex_home: store,
            )
            paths = RuntimePaths(root / "codex", root / "vault", config)

            first = application.bind_automation(
                paths, "xiaoh.daily-progress", "task-1"
            )
            after_first = config.read_bytes()
            second = application.bind_automation(
                paths, "xiaoh.daily-progress", "task-1"
            )
            saved = json.loads(config.read_text(encoding="utf-8"))

            self.assertEqual([str(config.resolve())], first["actual_writes"])
            self.assertEqual([], second["actual_writes"])
            self.assertEqual(after_first, config.read_bytes())
            self.assertEqual(
                {
                    "schedule": "0 8 * * *",
                    "timezone": "Asia/Shanghai",
                    "notification": "silent",
                    "status": "ACTIVE",
                },
                saved["automation_preferences"]["xiaoh.daily-progress"],
            )

    def test_automation_report_detects_duplicate_logical_identity(self) -> None:
        template = AutomationService(self.fs, PLUGIN).templates()[
            "xiaoh.daily-progress"
        ]
        store = _AutomationStore(
            [
                {"id": "one", "name": template["name"], "prompt": template["prompt"]},
                {"id": "two", "name": template["name"], "prompt": template["prompt"]},
            ]
        )

        report = AutomationService(self.fs, PLUGIN).report({}, store)

        self.assertEqual("degraded", report["status"])
        self.assertEqual("duplicate", report["tasks"][0]["state"])


if __name__ == "__main__":
    unittest.main()
