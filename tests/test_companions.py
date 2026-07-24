import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "plugins/xiaoh/scripts/xiaoh.py"
SPEC = importlib.util.spec_from_file_location("xiaoh_runtime", SCRIPT)
XIAOH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(XIAOH)

CLOSEOUT_SCRIPT = (
    Path(__file__).parents[1]
    / "plugins/xiaoh/skills/xiaoh-task-closeout/scripts/closeout_key.py"
)
CLOSEOUT_SPEC = importlib.util.spec_from_file_location("xiaoh_closeout_key", CLOSEOUT_SCRIPT)
CLOSEOUT = importlib.util.module_from_spec(CLOSEOUT_SPEC)
CLOSEOUT_SPEC.loader.exec_module(CLOSEOUT)

BASELINE_SCRIPT = (
    Path(__file__).parents[1]
    / "plugins/xiaoh/skills/xiaoh-requirement-baseline/scripts/validate_baseline.py"
)
BASELINE_SPEC = importlib.util.spec_from_file_location("xiaoh_validate_baseline", BASELINE_SCRIPT)
BASELINE = importlib.util.module_from_spec(BASELINE_SPEC)
BASELINE_SPEC.loader.exec_module(BASELINE)


class CompanionTests(unittest.TestCase):
    def test_release_version_and_bundled_skill_catalog_are_consistent(self):
        root = Path(__file__).parents[1]
        version = (root / "VERSION").read_text(encoding="utf-8").strip()
        plugin = XIAOH.load_json(root / "plugins/xiaoh/.codex-plugin/plugin.json")
        dependencies = XIAOH.load_json(root / "plugins/xiaoh/dependencies.json")
        actual_skills = sorted(
            path.name
            for path in (root / "plugins/xiaoh/skills").iterdir()
            if (path / "SKILL.md").is_file()
        )

        self.assertEqual(plugin["version"], version)
        self.assertEqual(actual_skills, sorted(dependencies["bundled_skills"]))
        self.assertIn("xiaoh-knowledge-promotion", actual_skills)
        self.assertIn("xiaoh-requirement-baseline", actual_skills)

    def write_automation(self, codex, logical_id, task_id, **overrides):
        template = XIAOH.automation_templates()[logical_id]
        values = {
            "version": 1,
            "id": task_id,
            "kind": "cron",
            "name": template["name"],
            "prompt": template["prompt"],
            "status": template["default_status"],
        }
        values.update(overrides)
        path = codex / "automations" / task_id / "automation.toml"
        path.parent.mkdir(parents=True)
        path.write_text(
            "\n".join(
                f"{key} = {json.dumps(value, ensure_ascii=False)}"
                for key, value in values.items()
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    def test_installs_declared_plugins_on_a_fresh_machine(self):
        installed = set()
        marketplaces = {"openai-bundled", "openai-primary-runtime"}
        calls = []

        def fake_codex(arguments):
            calls.append(arguments)
            if arguments == ["plugin", "list"]:
                return {"installed": [{"pluginId": value, "enabled": True} for value in installed]}, None
            if arguments == ["plugin", "marketplace", "list"]:
                return {"marketplaces": [{"name": value} for value in marketplaces]}, None
            if arguments[:3] == ["plugin", "marketplace", "add"]:
                marketplaces.add("ponytail")
                return {}, None
            if arguments[:2] == ["plugin", "add"]:
                installed.add(arguments[2])
                return {}, None
            self.fail(f"unexpected Codex invocation: {arguments}")

        with patch.object(XIAOH, "run_codex_json", side_effect=fake_codex), patch.object(
            XIAOH.shutil, "which", return_value=None
        ):
            result = XIAOH.companion_report(install_missing=True)

        self.assertEqual("degraded", result["status"])
        self.assertEqual(10, len(result["installed_now"]))
        self.assertTrue(all(item["status"] == "installed" for item in result["plugins"]))
        self.assertIn(
            ["plugin", "marketplace", "add", "DietrichGebert/ponytail", "--ref", "main"],
            calls,
        )
        self.assertEqual("missing", result["external_capabilities"][0]["status"])
        self.assertFalse(result["errors"])

    def test_runtime_update_preserves_existing_vault_knowledge(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex = root / "codex"
            vault = root / "vault"
            old_ledger = vault / "04-架构与决策/Agent进化台账.md"
            ledger = vault / "90-个人系统/Agent进化台账.md"
            vault_agents = vault / "AGENTS.md"
            preferences = vault / "00-工作台/我的工作偏好.md"
            old_ledger.parent.mkdir(parents=True)
            preferences.parent.mkdir(parents=True)
            old_ledger.write_text("retained __CODEX_HOME__ knowledge\n", encoding="utf-8")
            vault_agents.write_text("stale managed rules\n", encoding="utf-8")
            preferences.write_text("my personal preferences\n", encoding="utf-8")

            target_agents, vault_files, conflicts = XIAOH.copy_runtime(codex, vault)
            XIAOH.replace_placeholders(
                [target_agents, codex / "agents", codex / "contexts", codex / "agent-system", codex / "hooks", *vault_files],
                [("__CODEX_HOME__", codex.as_posix()), ("__OBSIDIAN_VAULT__", vault.as_posix())],
            )

            self.assertFalse(conflicts)
            self.assertEqual("retained __CODEX_HOME__ knowledge\n", ledger.read_text(encoding="utf-8"))
            self.assertEqual("my personal preferences\n", preferences.read_text(encoding="utf-8"))
            self.assertIn("开发知识库规则", vault_agents.read_text(encoding="utf-8"))
            self.assertNotIn(
                "__CODEX_HOME__",
                (vault / "90-个人系统/Agent协作角色.md").read_text(encoding="utf-8"),
            )

    def test_local_config_adds_automation_bindings_without_losing_local_values(self):
        local = {
            "custom": "retained",
            "workspaces": {
                "existing": {
                    "project": "Existing project",
                    "system": "Existing system",
                    "roots": ["/existing"],
                }
            },
            "managed_automations": {
                "xiaoh.daily-progress": {
                    "task_id": "existing-task",
                    "applied_template_version": "2.0.0",
                    "status": "bound",
                }
            },
        }

        merged = XIAOH.merged_local_config(local, Path("/codex"), Path("/vault"), "2.6.0")

        self.assertEqual("retained", merged["custom"])
        self.assertEqual(
            "existing-task",
            merged["managed_automations"]["xiaoh.daily-progress"]["task_id"],
        )
        self.assertIn("xiaoh.weekly-knowledge-review", merged["managed_automations"])
        self.assertIn("existing", merged["workspaces"])

    def test_invalid_workspace_registry_is_not_silently_replaced(self):
        with self.assertRaisesRegex(ValueError, "拒绝静默覆盖"):
            XIAOH.merged_local_config(
                {"workspaces": ["legacy-entry"]},
                Path("/codex"),
                Path("/vault"),
                "2.11.0",
            )

    def test_setup_rejects_invalid_workspace_registry_before_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex = root / "codex"
            vault = root / "vault"
            config = root / "config.json"
            marker = codex / "retained.txt"
            marker.parent.mkdir()
            marker.write_text("retained\n", encoding="utf-8")
            config.write_text('{"workspaces": ["legacy-entry"]}\n', encoding="utf-8")
            args = SimpleNamespace(
                codex_home=str(codex),
                vault=str(vault),
                config=str(config),
                active_skill_root=None,
            )

            result = XIAOH.install(args, "update")
            marker_text = marker.read_text(encoding="utf-8")

        self.assertEqual("failed", result["status"])
        self.assertIn("workspaces必须是JSON对象", result["errors"][0])
        self.assertEqual("retained\n", marker_text)

    def test_workspace_registration_and_nested_resolution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex = root / "codex"
            vault = root / "vault"
            config = root / "config.json"
            workspace = root / "workspace"
            member = workspace / "base-repo/member"
            member.mkdir(parents=True)
            config.write_text("{}\n", encoding="utf-8")

            registered = XIAOH.register_workspace(
                config,
                codex,
                vault,
                "example-ra",
                "Example project",
                "RA 9.2.0",
                str(workspace),
            )
            resolved = XIAOH.resolve_workspace(XIAOH.load_json(config), member)

        self.assertEqual("passed", registered["status"])
        self.assertEqual("known", resolved["status"])
        self.assertEqual("example-ra", resolved["workspace"]["workspace_id"])
        self.assertEqual("Example project", resolved["workspace"]["project"])
        self.assertEqual("RA 9.2.0", resolved["workspace"]["system"])

    def test_workspace_registration_rejects_silent_reassignment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config.json"
            workspace = root / "workspace"
            workspace.mkdir()
            config.write_text("{}\n", encoding="utf-8")

            first = XIAOH.register_workspace(
                config, root / "codex", root / "vault",
                "first", "Project A", "System A", str(workspace),
            )
            second = XIAOH.register_workspace(
                config, root / "codex", root / "vault",
                "second", "Project B", "System B", str(workspace),
            )

        self.assertEqual("passed", first["status"])
        self.assertEqual("failed", second["status"])
        self.assertIn("禁止静默改派", second["errors"][0])

    def test_workspace_registration_rejects_conflicted_registry_without_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config.json"
            workspace = root / "workspace"
            workspace.mkdir()
            original = {
                "workspaces": {
                    "first": {
                        "project": "Project A",
                        "system": "System A",
                        "bindings": [{"root": str(workspace), "platform": XIAOH.platform.system().lower()}],
                    },
                    "second": {
                        "project": "Project B",
                        "system": "System B",
                        "bindings": [{"root": str(workspace), "platform": XIAOH.platform.system().lower()}],
                    },
                }
            }
            config.write_text(json.dumps(original), encoding="utf-8")

            result = XIAOH.register_workspace(
                config, root / "codex", root / "vault",
                "third", "Project C", "System C", str(workspace),
            )
            stored = json.loads(config.read_text(encoding="utf-8"))

        self.assertEqual("failed", result["status"])
        self.assertEqual(original, stored)

    def test_foreign_platform_binding_is_preserved_and_local_root_can_be_added(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config.json"
            workspace = root / "workspace"
            workspace.mkdir()
            current = XIAOH.platform.system().lower()
            foreign = "windows" if current != "windows" else "darwin"
            foreign_root = r"C:\workspace" if foreign == "windows" else "/Users/example/workspace"
            config.write_text(json.dumps({
                "workspaces": {
                    "example": {
                        "project": "Example project",
                        "system": "Example system",
                        "bindings": [{"root": foreign_root, "platform": foreign}],
                    }
                }
            }), encoding="utf-8")

            before = XIAOH.resolve_workspace(XIAOH.load_json(config), workspace)
            registered = XIAOH.register_workspace(
                config, root / "codex", root / "vault",
                "example", "Example project", "Example system", str(workspace),
            )
            stored = XIAOH.load_json(config)
            after = XIAOH.resolve_workspace(stored, workspace)

        self.assertEqual("unknown", before["status"])
        self.assertEqual("passed", registered["status"])
        self.assertEqual("known", after["status"])
        self.assertIn(
            {"root": foreign_root, "platform": foreign},
            stored["workspaces"]["example"]["bindings"],
        )

    def test_platformless_legacy_root_is_preserved_and_local_root_can_be_added(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config.json"
            workspace = root / "workspace"
            workspace.mkdir()
            current = XIAOH.platform.system().lower()
            foreign_root = r"C:\workspace" if current != "windows" else "/Users/example/workspace"
            config.write_text(json.dumps({
                "workspaces": {
                    "example": {
                        "project": "Example project",
                        "system": "Example system",
                        "roots": [foreign_root],
                    }
                }
            }), encoding="utf-8")

            before = XIAOH.resolve_workspace(XIAOH.load_json(config), workspace)
            registered = XIAOH.register_workspace(
                config, root / "codex", root / "vault",
                "example", "Example project", "Example system", str(workspace),
            )
            stored = XIAOH.load_json(config)
            after = XIAOH.resolve_workspace(stored, workspace)

        self.assertEqual("unknown", before["status"])
        self.assertEqual("passed", registered["status"])
        self.assertEqual("known", after["status"])
        self.assertIn(
            {"root": foreign_root, "platform": "unknown"},
            stored["workspaces"]["example"]["bindings"],
        )

    def test_unknown_workspace_is_not_guessed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "unregistered"
            target.mkdir()

            resolved = XIAOH.resolve_workspace({"workspaces": {}}, target)

        self.assertEqual("unknown", resolved["status"])
        self.assertIsNone(resolved["workspace"])

    def test_automation_report_degrades_only_for_required_unbound_task(self):
        with tempfile.TemporaryDirectory() as temporary:
            codex = Path(temporary)
            report = XIAOH.automation_report({
                "managed_automations": {
                    "xiaoh.weekly-knowledge-review": {
                        "task_id": None,
                        "applied_template_version": None,
                        "status": "unbound",
                    }
                }
            }, codex)

        self.assertEqual("degraded", report["status"])
        self.assertEqual(1, len(report["warnings"]))
        self.assertIn("xiaoh.daily-progress", report["warnings"][0])

    def test_bind_automation_preserves_config_and_records_template_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex = root / "codex"
            config = root / "config.json"
            config.write_text(
                '{"codex_home": "/codex", "obsidian_vault": "/vault", "custom": "retained"}\n',
                encoding="utf-8",
            )
            self.write_automation(codex, "xiaoh.daily-progress", "task-123")

            result = XIAOH.bind_automation(
                config,
                codex,
                Path("/vault"),
                "xiaoh.daily-progress",
                "task-123",
            )
            stored = XIAOH.load_json(config)

            self.assertEqual("passed", result["status"])
            self.assertEqual("retained", stored["custom"])
            binding = stored["managed_automations"]["xiaoh.daily-progress"]
            self.assertEqual("task-123", binding["task_id"])
            self.assertEqual("2.0.0", binding["applied_template_version"])
            self.assertEqual("ACTIVE", binding["readback"]["status"])
            self.assertTrue(config.with_suffix(".json.bak").is_file())

    def test_automation_report_detects_runtime_status_and_prompt_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            codex = Path(temporary)
            self.write_automation(
                codex,
                "xiaoh.daily-progress",
                "task-123",
                prompt="stale prompt",
                status="PAUSED",
            )
            report = XIAOH.automation_report(
                {
                    "managed_automations": {
                        "xiaoh.daily-progress": {
                            "task_id": "task-123",
                            "applied_template_version": "2.0.0",
                        }
                    }
                },
                codex,
            )

        task = next(item for item in report["tasks"] if item["logical_id"] == "xiaoh.daily-progress")
        self.assertEqual("runtime_drifted", task["state"])
        self.assertEqual("PAUSED", task["actual_status"])
        self.assertTrue(any("prompt, status" in warning for warning in report["warnings"]))

    def test_automation_report_detects_duplicate_managed_tasks(self):
        with tempfile.TemporaryDirectory() as temporary:
            codex = Path(temporary)
            self.write_automation(codex, "xiaoh.daily-progress", "task-1")
            self.write_automation(
                codex,
                "xiaoh.daily-progress",
                "task-2",
                prompt="legacy XiaoH daily prompt",
            )
            report = XIAOH.automation_report(
                {
                    "managed_automations": {
                        "xiaoh.daily-progress": {
                            "task_id": "task-1",
                            "applied_template_version": "2.0.0",
                        }
                    }
                },
                codex,
            )

        task = next(item for item in report["tasks"] if item["logical_id"] == "xiaoh.daily-progress")
        self.assertEqual("duplicate", task["state"])
        self.assertEqual(["task-1", "task-2"], task["matching_task_ids"])

    def test_python39_fallback_reads_real_automation_shape(self):
        with tempfile.TemporaryDirectory() as temporary:
            codex = Path(temporary)
            path = self.write_automation(codex, "xiaoh.daily-progress", "task-real")
            with path.open("a", encoding="utf-8") as stream:
                stream.write('rrule = "RRULE:FREQ=DAILY;BYHOUR=10;BYMINUTE=0"\n')
                stream.write('target = { type = "project", project_id = "local-1" }\n')
                stream.write('cwds = ["/workspace"]\n')
            with patch.object(XIAOH, "tomllib", None):
                snapshot, error = XIAOH.automation_snapshot(codex, "task-real")

        self.assertIsNone(error)
        self.assertEqual("task-real", snapshot["id"])
        self.assertEqual("ACTIVE", snapshot["status"])

    def test_bind_automation_rejects_paused_required_task(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex = root / "codex"
            config = root / "config.json"
            config.write_text("{}\n", encoding="utf-8")
            self.write_automation(
                codex,
                "xiaoh.daily-progress",
                "task-paused",
                status="PAUSED",
            )

            result = XIAOH.bind_automation(
                config,
                codex,
                root / "vault",
                "xiaoh.daily-progress",
                "task-paused",
            )

        self.assertEqual("failed", result["status"])
        self.assertIn("status", result["errors"][0])

    def test_atomic_config_failure_keeps_original(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.json"
            path.write_text('{"value": "original"}\n', encoding="utf-8")

            with patch.object(XIAOH.os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    XIAOH.atomic_write_json(path, {"value": "new"})

            self.assertEqual('{"value": "original"}\n', path.read_text(encoding="utf-8"))

    def test_parallel_bindings_do_not_lose_updates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex = root / "codex"
            config = root / "config.json"
            config.write_text("{}\n", encoding="utf-8")
            self.write_automation(codex, "xiaoh.daily-progress", "daily")
            self.write_automation(codex, "xiaoh.weekly-knowledge-review", "weekly")
            results = []

            def bind(logical_id, task_id):
                results.append(
                    XIAOH.bind_automation(config, codex, root / "vault", logical_id, task_id)
                )

            threads = [
                threading.Thread(target=bind, args=("xiaoh.daily-progress", "daily")),
                threading.Thread(target=bind, args=("xiaoh.weekly-knowledge-review", "weekly")),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            stored = XIAOH.load_json(config)

        self.assertEqual(["passed", "passed"], sorted(item["status"] for item in results))
        self.assertEqual(
            {"xiaoh.daily-progress", "xiaoh.weekly-knowledge-review"},
            set(stored["managed_automations"]),
        )

    def test_legacy_vault_template_is_upgraded_but_custom_edit_is_preserved(self):
        legacy_home = """# 开发知识库

- [[01-项目/项目模板|新项目模板]]
- [[02-领域知识/术语模板|领域知识模板]]
- [[03-需求与方案/方案模板|需求与方案模板]]
- [[04-架构与决策/Agent协作角色|Agent 协作角色]]
- [[04-架构与决策/Agent进化台账|Agent 进化台账]]
- [[05-开发与测试/验证记录模板|验证记录模板]]
- [[06-部署与运维/运行手册模板|运行手册模板]]
- [[07-工作记录/工作记录模板|工作记录模板]]
"""
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary)
            home = vault / "首页.md"
            custom = vault / "CONTEXT.md"
            home.write_bytes(legacy_home.replace("\n", "\r\n").encode("utf-8"))
            custom.write_text("user customization\n", encoding="utf-8")

            touched, conflicts = XIAOH.sync_vault_runtime(vault)

            self.assertIn("我的研发系统", home.read_text(encoding="utf-8"))
            self.assertTrue((vault / "00-工作台/我的工作台.base").is_file())
            self.assertTrue((vault / "00-工作台/属性与状态说明.md").is_file())
            self.assertTrue((vault / "知识库.md").is_file())
            self.assertTrue((vault / "02-领域知识/知识库.base").is_file())
            self.assertEqual("user customization\n", custom.read_text(encoding="utf-8"))
            self.assertIn("CONTEXT.md", conflicts)
            self.assertIn(home, touched)

    def test_closeout_key_is_deterministic_and_revision_sensitive(self):
        first = CLOSEOUT.build_closeout_key("codex_thread", "thread-1", "implementation", "rev-7")
        rerun = CLOSEOUT.build_closeout_key("codex_thread", "thread-1", "implementation", "rev-7")
        changed = CLOSEOUT.build_closeout_key("codex_thread", "thread-1", "implementation", "rev-8")

        self.assertEqual(first["closeout_key"], rerun["closeout_key"])
        self.assertNotEqual(first["closeout_key"], changed["closeout_key"])
        with self.assertRaises(ValueError):
            CLOSEOUT.build_closeout_key("codex_thread", "unknown", "implementation", "rev-7")

    def test_codex_closeout_identity_uses_runtime_thread_and_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Path(temporary) / "review.json"
            moved = Path(temporary) / "archive" / "accepted-review.json"
            evidence.write_text('{"accepted": true}\n', encoding="utf-8")
            moved.parent.mkdir()
            moved.write_text('{"accepted": true}\n', encoding="utf-8")
            source = CLOSEOUT.resolve_source(
                "codex_thread",
                None,
                {"CODEX_THREAD_ID": "thread-runtime"},
            )
            first = CLOSEOUT.evidence_revision([str(evidence)])
            rerun = CLOSEOUT.evidence_revision([str(moved)])
            evidence.write_text('{"accepted": true, "revision": 2}\n', encoding="utf-8")
            changed = CLOSEOUT.evidence_revision([str(evidence)])

        self.assertEqual("thread-runtime", source)
        self.assertEqual("task-complete", CLOSEOUT.resolve_stage(None, True))
        self.assertEqual(first, rerun)
        self.assertNotEqual(first, changed)
        with self.assertRaises(ValueError):
            CLOSEOUT.resolve_source(
                "codex_thread",
                "invented",
                {"CODEX_THREAD_ID": "thread-runtime"},
            )

    def test_doctor_rejects_old_enabled_plugin_even_after_runtime_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex = root / "codex"
            vault = root / "vault"
            config = root / "config.json"
            target_agents, vault_files, _ = XIAOH.copy_runtime(codex, vault)
            XIAOH.replace_placeholders(
                [
                    target_agents,
                    codex / "agents",
                    codex / "contexts",
                    codex / "agent-system",
                    codex / "hooks",
                    *vault_files,
                ],
                [
                    ("__CODEX_HOME__/AGENTS.md", target_agents.as_posix()),
                    ("__CODEX_HOME__", codex.as_posix()),
                    ("__OBSIDIAN_VAULT__", vault.as_posix()),
                    ("__USER_HOME__", root.as_posix()),
                ],
            )
            XIAOH.refresh_templates(codex)
            XIAOH.atomic_write_json(
                config,
                XIAOH.merged_local_config(
                    {},
                    codex,
                    vault,
                    XIAOH.load_json(XIAOH.PLUGIN_MANIFEST)["version"],
                ),
            )
            companions = {
                "status": "complete",
                "bundled_skills": [],
                "plugins": [],
                "external_capabilities": [],
                "installed_now": [],
                "warnings": [],
                "errors": [],
            }
            with patch.object(XIAOH, "companion_report", return_value=companions), patch.object(
                XIAOH,
                "installed_xiaoh_plugin",
                return_value=({"plugin_id": "xiaoh@xiaoh", "version": "2.6.0", "source": {}}, None),
            ):
                result = XIAOH.doctor(
                    codex,
                    vault,
                    config,
                    active_skill_root=Path(__file__).parents[1]
                    / "plugins/xiaoh/skills/xiaoh-doctor",
                )

        self.assertEqual("failed", result["status"])
        self.assertTrue(any("已启用插件版本漂移" in error for error in result["errors"]))

    def test_closeout_and_push_responsibilities_are_separated(self):
        closeout = (
            Path(__file__).parents[1]
            / "plugins/xiaoh/skills/xiaoh-task-closeout/SKILL.md"
        ).read_text(encoding="utf-8")
        progress = (
            Path(__file__).parents[1]
            / "plugins/xiaoh/skills/xiaoh-project-progress/SKILL.md"
        ).read_text(encoding="utf-8")
        daily = (
            Path(__file__).parents[1]
            / "plugins/xiaoh/skills/xiaoh-daily-progress/SKILL.md"
        ).read_text(encoding="utf-8")

        self.assertIn("before the root thread declares", closeout)
        self.assertIn("工作记录/YYYY-MM-DD.md", closeout)
        self.assertIn("07-工作记录/全局能力/YYYY-MM-DD.md", closeout)
        self.assertIn("scripts/closeout_key.py", closeout)
        self.assertIn("CODEX_THREAD_ID", closeout)
        self.assertIn("项目进度.md", progress)
        self.assertIn("does not perform task closeout", daily)
        self.assertIn("do not reconstruct, summarize, or write", daily)

    def test_project_progress_template_is_bundled(self):
        vault = (
            Path(__file__).parents[1]
            / "plugins/xiaoh/runtime/obsidian/development-vault"
        )
        template = (vault / "01-项目/项目进度模板.md").read_text(encoding="utf-8")
        workbench = (vault / "00-工作台/我的工作台.base").read_text(encoding="utf-8")
        knowledge_base = (vault / "02-领域知识/知识库.base").read_text(encoding="utf-8")
        manifest = XIAOH.managed_vault_files()

        self.assertIn("type: project_progress", template)
        self.assertIn("is_template: true", template)
        self.assertIn("## 工作线总览", template)
        self.assertIn("## 最近完成", template)
        self.assertIn("## 阻塞与风险", template)
        self.assertIn("name: 今日重点", workbench)
        self.assertIn("name: 待我确认", workbench)
        self.assertIn("name: 知识候选", workbench)
        self.assertIn("name: 项目知识", knowledge_base)
        self.assertIn("name: 领域知识", knowledge_base)
        self.assertIn("name: 可复用方法", knowledge_base)
        self.assertIn("name: 个人系统", knowledge_base)
        self.assertIn("00-工作台/我的工作台.base", manifest)
        self.assertIn("02-领域知识/知识库.base", manifest)
        self.assertIn("03-可复用方法/复用卡模板.md", manifest)
        self.assertIn("03-需求与方案/业务逻辑基线模板.md", manifest)
        self.assertIn("00-工作台/属性与状态说明.md", manifest)
        self.assertNotIn("00-工作台/我的工作偏好.md", manifest)

    def test_requirement_baseline_separates_confirmation_from_pending_input(self):
        root = Path(__file__).parents[1]
        skill = (
            root / "plugins/xiaoh/skills/xiaoh-requirement-baseline/SKILL.md"
        ).read_text(encoding="utf-8")
        template = (
            root
            / "plugins/xiaoh/runtime/obsidian/development-vault"
            / "03-需求与方案/业务逻辑基线模板.md"
        ).read_text(encoding="utf-8")

        self.assertIn("one canonical page per business topic", skill)
        self.assertIn("question", skill)
        self.assertIn("hypothesis", skill)
        for state in ("pending", "confirmed", "superseded", "rejected"):
            self.assertIn(f"`{state}`", skill)
        self.assertIn("type: requirement_baseline", template)
        self.assertIn("baseline_revision:", template)
        self.assertIn("## 确认点", template)
        self.assertIn("## 与正式工件的追溯", template)
        self.assertIn("superseded_by", template)

    def write_baseline(self, path, rows):
        path.write_text(
            "\n".join([
                "# Baseline",
                "",
                "## 确认点",
                "",
                "| " + " | ".join(BASELINE.REQUIRED_COLUMNS) + " |",
                "| " + " | ".join("---" for _ in BASELINE.REQUIRED_COLUMNS) + " |",
                *("| " + " | ".join(row) + " |" for row in rows),
                "",
                "## 修订历史",
            ]),
            encoding="utf-8",
        )

    def test_requirement_baseline_validator_enforces_evidence_ids_and_supersession(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            valid = root / "valid.md"
            self.write_baseline(valid, [
                ["REQ-1", "confirmed", "-", "rule", "reason", "turn-1", "scope", "accept", "trace", "-"],
                ["REQ-2", "superseded", "REQ-3", "old", "reason", "turn-2", "scope", "accept", "trace", "-"],
                ["REQ-3", "confirmed", "-", "new", "reason", "turn-3", "scope", "accept", "trace", "-"],
            ])
            points = BASELINE.confirmation_points(valid)
            self.assertEqual(3, len(points))

            missing_evidence = root / "missing.md"
            self.write_baseline(missing_evidence, [
                ["REQ-1", "confirmed", "-", "rule", "reason", "-", "scope", "accept", "trace", "-"],
            ])
            with self.assertRaisesRegex(ValueError, "缺少证据"):
                BASELINE.confirmation_points(missing_evidence)

            duplicate = root / "duplicate.md"
            self.write_baseline(duplicate, [
                ["REQ-1", "pending", "-", "rule", "reason", "-", "scope", "accept", "trace", "open"],
                ["REQ-1", "pending", "-", "rule", "reason", "-", "scope", "accept", "trace", "open"],
            ])
            with self.assertRaisesRegex(ValueError, "ID重复"):
                BASELINE.confirmation_points(duplicate)

    def test_requirement_baseline_validator_allows_forward_transition_only(self):
        def point(state, rule):
            return {
                "状态": state,
                "业务规则": rule,
                "设计依据": "reason",
                "证据与确认来源": "turn-1",
                "适用与排除范围": "scope",
                "验收条件": "accept",
                "影响与追溯": "trace",
                "剩余不确定项": "-",
            }

        previous = {
            "REQ-1": point("pending", "pending rule"),
            "REQ-2": point("confirmed", "confirmed rule"),
            "REQ-3": point("pending", "successor rule"),
        }
        current = {
            "REQ-1": point("confirmed", "final rule"),
            "REQ-2": point("superseded", "confirmed rule"),
            "REQ-3": point("confirmed", "successor rule"),
        }
        current["REQ-2"]["superseded_by"] = "REQ-3"
        BASELINE.validate_transition(previous, current)
        with self.assertRaisesRegex(ValueError, "非法状态转换"):
            BASELINE.validate_transition(
                {"REQ-1": point("confirmed", "rule")},
                {"REQ-1": point("pending", "rule")},
            )
        with self.assertRaisesRegex(ValueError, "原地改写"):
            BASELINE.validate_transition(
                {"REQ-1": point("confirmed", "old rule")},
                {"REQ-1": point("confirmed", "new rule")},
            )
        preexisting = {
            "REQ-1": point("confirmed", "old rule"),
            "REQ-2": point("confirmed", "other old rule"),
        }
        replaced = {
            "REQ-1": point("superseded", "old rule"),
            "REQ-2": point("confirmed", "other old rule"),
        }
        replaced["REQ-1"]["superseded_by"] = "REQ-2"
        with self.assertRaisesRegex(ValueError, "本版新增或由pending"):
            BASELINE.validate_transition(preexisting, replaced)

    def test_requirement_baseline_validator_rejects_invalid_successors_and_table(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pending_successor = root / "pending-successor.md"
            self.write_baseline(pending_successor, [
                ["REQ-1", "superseded", "REQ-2", "old", "reason", "turn-1", "scope", "accept", "trace", "-"],
                ["REQ-2", "pending", "-", "new", "reason", "-", "scope", "accept", "trace", "open"],
            ])
            with self.assertRaisesRegex(ValueError, "必须是confirmed"):
                BASELINE.confirmation_points(pending_successor)

            self_reference = root / "self-reference.md"
            self.write_baseline(self_reference, [
                ["REQ-1", "superseded", "REQ-1", "old", "reason", "turn-1", "scope", "accept", "trace", "-"],
            ])
            with self.assertRaisesRegex(ValueError, "不得指向自身"):
                BASELINE.confirmation_points(self_reference)

            missing_separator = root / "missing-separator.md"
            missing_separator.write_text(
                "\n".join([
                    "# Baseline",
                    "",
                    "## 确认点",
                    "",
                    "| " + " | ".join(BASELINE.REQUIRED_COLUMNS) + " |",
                    "| REQ-1 | confirmed | - | rule | reason | turn-1 | scope | accept | trace | - |",
                ]),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "分隔行"):
                BASELINE.confirmation_points(missing_separator)

            missing_pipe = root / "missing-leading-pipe.md"
            missing_pipe.write_text(
                "\n".join([
                    "# Baseline",
                    "",
                    "## 确认点",
                    "",
                    "| " + " | ".join(BASELINE.REQUIRED_COLUMNS) + " |",
                    "| " + " | ".join("---" for _ in BASELINE.REQUIRED_COLUMNS) + " |",
                    "REQ-1 | confirmed | - | rule | reason | turn-1 | scope | accept | trace | - |",
                ]),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "无法解析"):
                BASELINE.confirmation_points(missing_pipe)

    def test_knowledge_promotion_references_business_baseline_instead_of_copying_rules(self):
        skill = (
            Path(__file__).parents[1]
            / "plugins/xiaoh/skills/xiaoh-knowledge-promotion/SKILL.md"
        ).read_text(encoding="utf-8")

        self.assertIn("stable point IDs", skill)
        self.assertIn("Do not copy the rule text", skill)
        self.assertIn("$xiaoh:xiaoh-requirement-baseline", skill)

    def test_knowledge_promotion_has_four_exclusive_routes(self):
        skill = (
            Path(__file__).parents[1]
            / "plugins/xiaoh/skills/xiaoh-knowledge-promotion/SKILL.md"
        ).read_text(encoding="utf-8")

        self.assertIn("Select exactly one scope", skill)
        for scope in ("`project`", "`domain`", "`reusable`", "`personal_system`"):
            self.assertIn(scope, skill)
        self.assertIn("A completion list is not knowledge", skill)

    def test_vault_update_relocates_personal_system_pages(self):
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary)
            old_role = vault / "04-架构与决策/Agent协作角色.md"
            old_ledger = vault / "04-架构与决策/Agent进化台账.md"
            old_role.parent.mkdir(parents=True)
            old_role.write_text("legacy role\n", encoding="utf-8")
            old_ledger.write_text("user evolution evidence\n", encoding="utf-8")

            XIAOH.sync_vault_runtime(vault)

            self.assertFalse(old_role.exists())
            self.assertFalse(old_ledger.exists())
            self.assertTrue((vault / "90-个人系统/Agent协作角色.md").is_file())
            self.assertEqual(
                "user evolution evidence\n",
                (vault / "90-个人系统/Agent进化台账.md").read_text(encoding="utf-8"),
            )

    def test_every_managed_vault_template_exists_and_has_valid_legacy_hashes(self):
        vault = XIAOH.RUNTIME / "obsidian/development-vault"

        for relative, metadata in XIAOH.managed_vault_files().items():
            self.assertTrue((vault / relative).is_file(), relative)
            for digest in metadata.get("legacy_hashes", []):
                self.assertRegex(digest, r"^[0-9a-f]{64}$", relative)


if __name__ == "__main__":
    unittest.main()
