import importlib.util
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
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

PLAYBOOK_ADAPTER_SCRIPT = (
    Path(__file__).parents[1]
    / "plugins/xiaoh/runtime/codex/agent-system/playbook_adapter.py"
)
PLAYBOOK_ADAPTER_SPEC = importlib.util.spec_from_file_location(
    "xiaoh_playbook_adapter", PLAYBOOK_ADAPTER_SCRIPT
)
PLAYBOOK_ADAPTER = importlib.util.module_from_spec(PLAYBOOK_ADAPTER_SPEC)
PLAYBOOK_ADAPTER_SPEC.loader.exec_module(PLAYBOOK_ADAPTER)

VALIDATOR_SCRIPT = (
    Path(__file__).parents[1]
    / "plugins/xiaoh/runtime/codex/agent-system/validate.py"
)
sys.path.insert(0, str(VALIDATOR_SCRIPT.parent))
VALIDATOR_SPEC = importlib.util.spec_from_file_location("xiaoh_validator", VALIDATOR_SCRIPT)
VALIDATOR = importlib.util.module_from_spec(VALIDATOR_SPEC)
VALIDATOR_SPEC.loader.exec_module(VALIDATOR)

DELEGATION_HOOK_SCRIPT = (
    Path(__file__).parents[1]
    / "plugins/xiaoh/runtime/codex/hooks/block_reserved_root_agent.py"
)
DELEGATION_HOOK_SPEC = importlib.util.spec_from_file_location(
    "xiaoh_delegation_hook", DELEGATION_HOOK_SCRIPT
)
DELEGATION_HOOK = importlib.util.module_from_spec(DELEGATION_HOOK_SPEC)
DELEGATION_HOOK_SPEC.loader.exec_module(DELEGATION_HOOK)


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
        self.assertIn("xiaoh-playbook-adapter", actual_skills)
        self.assertIn("xiaoh-project-recall", actual_skills)

    def test_validator_self_test_recall_path_is_platform_absolute(self):
        manifest_path = VALIDATOR.example_memory_recall()["manifest_path"]
        self.assertTrue(Path(manifest_path).is_absolute(), manifest_path)

    def write_project_recall_fixture(self, root, memory_kind="requirement_baseline"):
        vault = root / "vault"
        vault.mkdir()
        (vault / ".obsidian").mkdir()
        memory = vault / "03-需求与方案" / "业务规则基线.md"
        memory.parent.mkdir()
        memory.write_text("# 业务规则基线\n", encoding="utf-8")
        index = vault / "01-项目" / "项目总览.md"
        index.parent.mkdir()
        index.write_text("# 项目总览\n", encoding="utf-8")
        current = root / "current-code.java"
        current.write_text("class Current {}\n", encoding="utf-8")
        config = root / "xiaoh.json"
        config.write_text(
            json.dumps({
                "obsidian_vault": str(vault),
                "workspaces": {
                    "workspace-1": {
                        "project": "Example project",
                        "system": "Example system",
                        "bindings": [{
                            "root": str(root),
                            "platform": XIAOH.platform.system().lower(),
                        }],
                    }
                },
            }),
            encoding="utf-8",
        )
        created_at = datetime.now(timezone.utc).isoformat()
        manifest = {
            "schema_version": "xiaoh-project-recall/v1",
            "created_at": created_at,
            "task_id": "recall-test",
            "workspace_id": "workspace-1",
            "project": "Example project",
            "system": "Example system",
            "task_relation": "continuation",
            "query": {
                "summary": "继续现有业务规则实现",
                "topics": ["业务规则"],
                "task_ids": ["task-1"],
                "keywords": ["rule"],
            },
            "memory_sources": [{
                "kind": memory_kind,
                "path": str(memory),
                "sha256": hashlib.sha256(memory.read_bytes()).hexdigest(),
                "role": "navigation" if memory_kind == "daily_digest" else "authority",
                "point_ids": ["BR-001"],
                "relevance": "提供已确认业务规则",
            }],
            "checked_indexes": [{
                "path": str(index),
                "sha256": hashlib.sha256(index.read_bytes()).hexdigest(),
                "relevance": "项目级召回入口",
            }],
            "no_relevant_history_reason": None,
            "current_fact_sources": [{
                "kind": "code",
                "path": str(current),
                "sha256": hashlib.sha256(current.read_bytes()).hexdigest(),
                "relevance": "核对当前实现",
            }],
            "current_fact_scope": "当前业务规则实现",
            "material_conflicts": [],
            "unresolved": [],
            "recommended_baseline": "沿用BR-001并以当前代码作为实现事实",
        }
        manifest_path = root / "evidence/recall/recall.json"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        recall = {
            "status": "completed",
            "workspace_id": "workspace-1",
            "task_relation": "continuation",
            "manifest_path": str(manifest_path),
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "completed_at": created_at,
        }
        return config, manifest_path, manifest, recall

    def business_context_with_recall(self, root, recall):
        template = json.loads(
            (
                Path(__file__).parents[1]
                / "plugins/xiaoh/runtime/codex/agent-system/task-context.template.json"
            ).read_text(encoding="utf-8")
        )
        source = root / "source.md"
        source.write_text("source\n", encoding="utf-8")
        template["task_id"] = "recall-test"
        template["intent"]["domain"] = "business_project"
        template["scope"].update({
            "workspace": str(root),
            "repositories": [],
            "allowed_paths": [str(root)],
            "prohibited_actions": ["external writes"],
        })
        template["sources"] = [{
            "path": str(source),
            "purpose": "current test facts",
            "required": True,
        }]
        template["memory_recall"] = recall
        template["requirements"] = VALIDATOR.example_requirements()
        template["freshness"]["checked_at"] = datetime.now(timezone.utc).isoformat()
        return template

    def test_project_recall_manifest_is_required_before_requirement_routing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, _, _, recall = self.write_project_recall_fixture(root)
            context = self.business_context_with_recall(root, recall)
            report = VALIDATOR.Report()
            with patch.dict(os.environ, {"XIAOH_CONFIG": str(config)}):
                VALIDATOR.validate_task_context(context, report)
                VALIDATOR.validate_requirement_gate(
                    context, "artifact_routing", report
                )

        self.assertFalse(report.errors, report.errors)

    def test_project_recall_rejects_tampering_digest_only_and_legacy_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, manifest_path, manifest, recall = self.write_project_recall_fixture(root)

            tampered = dict(recall)
            tampered["manifest_sha256"] = "0" * 64
            tampered_report = VALIDATOR.Report()
            context = self.business_context_with_recall(root, tampered)
            with patch.dict(os.environ, {"XIAOH_CONFIG": str(config)}):
                VALIDATOR.validate_requirement_gate(
                    context, "artifact_routing", tampered_report
                )
            self.assertTrue(any("does not match" in error for error in tampered_report.errors))

            wrong_workspace = dict(recall)
            wrong_workspace["workspace_id"] = "workspace-2"
            workspace_report = VALIDATOR.Report()
            with patch.dict(os.environ, {"XIAOH_CONFIG": str(config)}):
                VALIDATOR.validate_memory_recall(
                    wrong_workspace, context, workspace_report, require_completed=True
                )
            self.assertTrue(any(
                "does not match configured Workspace" in error
                for error in workspace_report.errors
            ))

            outside_manifest = root / "outside-recall.json"
            outside_manifest.write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            outside_manifest_recall = dict(recall)
            outside_manifest_recall.update({
                "manifest_path": str(outside_manifest),
                "manifest_sha256": hashlib.sha256(
                    outside_manifest.read_bytes()
                ).hexdigest(),
            })
            outside_manifest_report = VALIDATOR.Report()
            with patch.dict(os.environ, {"XIAOH_CONFIG": str(config)}):
                VALIDATOR.validate_memory_recall(
                    outside_manifest_recall,
                    context,
                    outside_manifest_report,
                    require_completed=True,
                )
            self.assertTrue(any(
                "outside the authorized evidence directory" in error
                for error in outside_manifest_report.errors
            ))

            manifest["memory_sources"][0].update({
                "kind": "daily_digest",
                "role": "navigation",
            })
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            digest_only = dict(recall)
            digest_only["manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            digest_report = VALIDATOR.Report()
            with patch.dict(os.environ, {"XIAOH_CONFIG": str(config)}):
                VALIDATOR.validate_memory_recall(
                    digest_only, context, digest_report, require_completed=True
                )
            self.assertTrue(any(
                "requires a distinct non-digest authority or evidence source" in error
                for error in digest_report.errors
            ))

            legacy = self.business_context_with_recall(root, recall)
            legacy["schema_version"] = "1.4"
            legacy.pop("memory_recall")
            legacy_report = VALIDATOR.Report()
            VALIDATOR.validate_requirement_gate(
                legacy, "artifact_routing", legacy_report, check_paths=False
            )
            self.assertTrue(any("schema 1.5" in error for error in legacy_report.errors))

            legacy["routing"].update({
                "delegated_agents": ["java_code_explorer"],
                "delegation_names": {
                    "java_code_explorer": "legacy_business_exploration"
                },
                "selection_reason": "read-only historical exploration",
            })
            legacy_delegation_report = VALIDATOR.Report()
            VALIDATOR.validate_task_context(
                legacy, legacy_delegation_report, check_paths=False
            )
            self.assertTrue(any(
                "formal delegation requires schema 1.5" in error
                for error in legacy_delegation_report.errors
            ))

    def test_project_recall_binds_task_and_rejects_weak_or_ambiguous_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, manifest_path, manifest, recall = self.write_project_recall_fixture(root)
            context = self.business_context_with_recall(root, recall)

            cases = []

            cross_task = json.loads(json.dumps(manifest))
            cross_task["task_id"] = "another-task"
            cases.append((cross_task, "task_id does not match"))

            empty_query = json.loads(json.dumps(manifest))
            empty_query["query"].update({"topics": [], "task_ids": [], "keywords": []})
            cases.append((empty_query, "requires at least one topic"))

            duplicate_path = json.loads(json.dumps(manifest))
            duplicate_path["memory_sources"].append({
                **duplicate_path["memory_sources"][0],
                "kind": "daily_digest",
                "role": "navigation",
                "point_ids": [],
            })
            cases.append((duplicate_path, "duplicate file identities"))

            missing_point_ids = json.loads(json.dumps(manifest))
            missing_point_ids["memory_sources"][0]["point_ids"] = []
            cases.append((missing_point_ids, "point_ids must be a non-empty list"))

            cross_list_duplicate = json.loads(json.dumps(manifest))
            cross_list_duplicate["checked_indexes"][0] = {
                "path": cross_list_duplicate["memory_sources"][0]["path"],
                "sha256": cross_list_duplicate["memory_sources"][0]["sha256"],
                "relevance": "重复使用历史来源作为索引",
            }
            cases.append((cross_list_duplicate, "reuses a file identity"))

            for candidate, expected in cases:
                with self.subTest(expected=expected):
                    manifest_path.write_text(json.dumps(candidate), encoding="utf-8")
                    candidate_recall = dict(recall)
                    candidate_recall["manifest_sha256"] = hashlib.sha256(
                        manifest_path.read_bytes()
                    ).hexdigest()
                    candidate_report = VALIDATOR.Report()
                    with patch.dict(os.environ, {"XIAOH_CONFIG": str(config)}):
                        VALIDATOR.validate_memory_recall(
                            candidate_recall,
                            context,
                            candidate_report,
                            require_completed=True,
                        )
                    self.assertTrue(
                        any(expected in error for error in candidate_report.errors),
                        candidate_report.errors,
                    )

    def test_project_recall_rejects_file_identity_aliases(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, manifest_path, manifest, recall = self.write_project_recall_fixture(root)
            context = self.business_context_with_recall(root, recall)
            source = Path(manifest["memory_sources"][0]["path"])
            aliases = [
                source.with_name("业务规则基线-alias.md"),
                source.with_name("业务规则基线-别名.md"),
            ]
            for alias in aliases:
                os.link(source, alias)

            same_list = json.loads(json.dumps(manifest))
            same_list["memory_sources"].append({
                **same_list["memory_sources"][0],
                "kind": "formal_knowledge",
                "path": str(aliases[0]),
                "role": "authority",
                "point_ids": [],
            })
            cross_list = json.loads(json.dumps(manifest))
            cross_list["checked_indexes"][0] = {
                "path": str(aliases[1]),
                "sha256": cross_list["memory_sources"][0]["sha256"],
                "relevance": "同一物理文件的Unicode别名",
            }

            for candidate in (same_list, cross_list):
                with self.subTest(candidate=candidate):
                    manifest_path.write_text(json.dumps(candidate), encoding="utf-8")
                    candidate_recall = dict(recall)
                    candidate_recall["manifest_sha256"] = hashlib.sha256(
                        manifest_path.read_bytes()
                    ).hexdigest()
                    report = VALIDATOR.Report()
                    with patch.dict(os.environ, {"XIAOH_CONFIG": str(config)}):
                        VALIDATOR.validate_memory_recall(
                            candidate_recall,
                            context,
                            report,
                            require_completed=True,
                        )
                    self.assertTrue(any(
                        "file identit" in error for error in report.errors
                    ), report.errors)

    def test_empty_history_requires_content_bound_checked_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, manifest_path, manifest, recall = self.write_project_recall_fixture(root)
            manifest["memory_sources"] = []
            manifest["checked_indexes"] = []
            manifest["no_relevant_history_reason"] = "未发现匹配历史"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            recall["manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            context = self.business_context_with_recall(root, recall)
            report = VALIDATOR.Report()
            with patch.dict(os.environ, {"XIAOH_CONFIG": str(config)}):
                VALIDATOR.validate_memory_recall(
                    recall, context, report, require_completed=True
                )
            self.assertTrue(any(
                "requires at least one checked index" in error
                for error in report.errors
            ))

    def test_all_formal_delegation_domains_require_schema_15(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, _, _, recall = self.write_project_recall_fixture(root)
            for domain in ("global_agent_capability", "playbook_platform"):
                with self.subTest(domain=domain):
                    context = self.business_context_with_recall(root, recall)
                    context["schema_version"] = "1.4"
                    context.pop("memory_recall")
                    context["intent"]["domain"] = domain
                    context["routing"].update({
                        "delegated_agents": ["java_code_explorer"],
                        "delegation_names": {
                            "java_code_explorer": "{}_review".format(domain)
                        },
                        "selection_reason": "formal read-only review",
                    })
                    report = VALIDATOR.Report()
                    VALIDATOR.validate_task_context(
                        context, report, check_paths=False
                    )
                    self.assertTrue(any(
                        "formal delegation requires schema 1.5" in error
                        for error in report.errors
                    ), report.errors)

    def test_project_recall_skill_declares_targeted_read_and_current_fact_reconciliation(self):
        skill = (
            Path(__file__).parents[1]
            / "plugins/xiaoh/skills/xiaoh-project-recall/SKILL.md"
        ).read_text(encoding="utf-8")

        self.assertIn("Do not batch-read the Vault", skill)
        self.assertIn("Daily digests only as navigation", skill)
        self.assertIn("current_fact_sources", skill)
        self.assertIn("memory_recall", skill)

    def test_project_recall_rejects_stale_or_out_of_vault_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, manifest_path, manifest, recall = self.write_project_recall_fixture(root)
            context = self.business_context_with_recall(root, recall)

            memory_path = Path(manifest["memory_sources"][0]["path"])
            memory_path.write_text("# changed after recall\n", encoding="utf-8")
            content_report = VALIDATOR.Report()
            with patch.dict(os.environ, {"XIAOH_CONFIG": str(config)}):
                VALIDATOR.validate_memory_recall(
                    recall, context, content_report, require_completed=True
                )
            self.assertTrue(any(
                "sha256 does not match path" in error
                for error in content_report.errors
            ))

            stale = (
                datetime.now(timezone.utc) - timedelta(hours=25)
            ).isoformat()
            manifest["created_at"] = stale
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            stale_recall = dict(recall)
            stale_recall.update({
                "completed_at": stale,
                "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            })
            stale_report = VALIDATOR.Report()
            with patch.dict(os.environ, {"XIAOH_CONFIG": str(config)}):
                VALIDATOR.validate_memory_recall(
                    stale_recall, context, stale_report, require_completed=True
                )
            self.assertTrue(any("stale or from the future" in error for error in stale_report.errors))

            manifest["created_at"] = recall["completed_at"]
            manifest["memory_sources"][0]["path"] = str(root / "current-code.java")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            outside_recall = dict(recall)
            outside_recall["manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            outside_report = VALIDATOR.Report()
            with patch.dict(os.environ, {"XIAOH_CONFIG": str(config)}):
                VALIDATOR.validate_memory_recall(
                    outside_recall, context, outside_report, require_completed=True
                )
            self.assertTrue(any("outside the configured Vault" in error for error in outside_report.errors))

    def test_project_recall_allows_explained_empty_history_and_blocks_pending_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, manifest_path, manifest, recall = self.write_project_recall_fixture(root)
            manifest["memory_sources"] = []
            manifest["no_relevant_history_reason"] = (
                "项目索引、进度页和主题基线均无匹配记录"
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            recall["manifest_sha256"] = hashlib.sha256(
                manifest_path.read_bytes()
            ).hexdigest()
            context = self.business_context_with_recall(root, recall)
            empty_report = VALIDATOR.Report()
            with patch.dict(os.environ, {"XIAOH_CONFIG": str(config)}):
                VALIDATOR.validate_requirement_gate(
                    context, "artifact_routing", empty_report
                )
            self.assertFalse(empty_report.errors, empty_report.errors)

            pending = dict(recall)
            pending.update({
                "status": "pending",
                "manifest_path": None,
                "manifest_sha256": None,
                "completed_at": None,
            })
            context["memory_recall"] = pending
            pending_report = VALIDATOR.Report()
            VALIDATOR.validate_requirement_gate(
                context, "artifact_routing", pending_report, check_paths=False
            )
            self.assertTrue(any(
                "project memory recall must be completed" in error
                for error in pending_report.errors
            ))

    def test_workspace_resolution_ignores_foreign_and_unknown_platform_bindings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current = XIAOH.platform.system().lower()
            foreign = "windows" if current != "windows" else "darwin"
            target = root / "workspace"
            target.mkdir()
            config = root / "xiaoh.json"

            for entry in (
                {"project": "P", "system": "S", "bindings": [{
                    "root": str(target), "platform": foreign,
                }]},
                {"project": "P", "system": "S", "roots": [str(target)]},
            ):
                with self.subTest(entry=entry):
                    data = {"obsidian_vault": str(root), "workspaces": {"ws": entry}}
                    config.write_text(json.dumps(data), encoding="utf-8")
                    with patch.dict(os.environ, {"XIAOH_CONFIG": str(config)}):
                        with self.assertRaisesRegex(ValueError, "not registered"):
                            VALIDATOR.resolve_configured_workspace(target)
                    self.assertEqual("unknown", XIAOH.resolve_workspace(data, target)["status"])

            data = {
                "obsidian_vault": str(root),
                "workspaces": {"ws": {
                    "project": "P",
                    "system": "S",
                    "bindings": [{"root": str(target), "platform": current}],
                }},
            }
            config.write_text(json.dumps(data), encoding="utf-8")
            with patch.dict(os.environ, {"XIAOH_CONFIG": str(config)}):
                resolved = VALIDATOR.resolve_configured_workspace(target)
            self.assertEqual("ws", resolved["workspace_id"])
            self.assertEqual("known", XIAOH.resolve_workspace(data, target)["status"])

    def test_subagent_start_timeout_fails_closed(self):
        with patch.object(
            DELEGATION_HOOK,
            "consume_subagent_start",
            side_effect=subprocess.TimeoutExpired(["validator"], 45),
        ):
            response = DELEGATION_HOOK.handle_subagent_start({}, Path("/tmp"))

        self.assertIn(
            "XIAOH_UNAUTHORIZED_SUBAGENT",
            response["hookSpecificOutput"]["additionalContext"],
        )
        self.assertIn("委派证明生成失败", response["systemMessage"])

    def test_subagent_start_revalidates_non_playbook_recall_after_prepare(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, manifest_path, manifest, recall = self.write_project_recall_fixture(root)
            codex = root / "codex"
            vault = Path(json.loads(config.read_text())["obsidian_vault"])
            XIAOH.copy_runtime(codex, vault, config)
            context = self.business_context_with_recall(root, recall)
            context["routing"].update({
                "delegated_agents": ["java_code_explorer"],
                "delegation_names": {
                    "java_code_explorer": "recall_window_review"
                },
                "selection_reason": "verify the post-prepare recall window",
            })
            context_path = root / "task-context.json"
            context_path.write_text(json.dumps(context), encoding="utf-8")
            context_hash = hashlib.sha256(context_path.read_bytes()).hexdigest()
            message = (
                "task_id: recall-test\n"
                f"task_context: {context_path}\n"
                f"context_hash: {context_hash}\n"
                "delegated_agent: java_code_explorer\n\n"
                "Read-only recall verification."
            )
            payload = {
                "tool_input": {
                    "task_name": "recall_window_review",
                    "agent_type": "java_code_explorer",
                    "fork_turns": "none",
                    "message": message,
                }
            }
            environment = {
                "CODEX_HOME": str(codex),
                "CODEX_THREAD_ID": "recall-window-thread",
                "XIAOH_CONFIG": str(config),
            }
            with patch.dict(os.environ, environment):
                intent_path = DELEGATION_HOOK.prepare_delegation_intent(
                    payload, codex, run_validator=False
                )
                intent = json.loads(intent_path.read_text(encoding="utf-8"))
                runtime = {
                    "session_id": "recall-window-thread",
                    "agent_type": "java_code_explorer",
                }
                DELEGATION_HOOK.validate_pending_intent(intent, runtime, codex)

                manifest_bytes = manifest_path.read_bytes()
                manifest_path.write_text("{}\n", encoding="utf-8")
                with self.assertRaisesRegex(
                    ValueError, "task context is no longer valid"
                ):
                    DELEGATION_HOOK.validate_pending_intent(
                        intent, runtime, codex
                    )

                manifest_path.write_bytes(manifest_bytes)
                memory_path = Path(manifest["memory_sources"][0]["path"])
                memory_path.write_text("# changed after prepare\n", encoding="utf-8")
                with self.assertRaisesRegex(
                    ValueError, "task context is no longer valid"
                ):
                    DELEGATION_HOOK.validate_pending_intent(
                        intent, runtime, codex
                    )

    def write_playbook_snapshots(self, root, **worker_overrides):
        worktree = root / "member-worktree"
        worktree.mkdir(exist_ok=True)
        worker = {
            "workspace_id": "pb-task-workspace",
            "change_id": "change-1",
            "member": "member-a",
            "member_worktree": str(worktree),
            "allowed_scope": [str(worktree)],
        }
        worker.update(worker_overrides)
        worker_path = root / "worker.json"
        status_path = root / "status.json"
        worker_path.write_text(
            json.dumps({
                "status": "ok",
                "data": {
                    "workspace_root": str(root),
                    "child_worker_context": worker,
                },
            }),
            encoding="utf-8",
        )
        status_path.write_text(
            json.dumps({
                "status": "ok",
                "data": {
                    "workspace_id": "pb-task-workspace",
                    "change_id": "change-1",
                    "task_next": {"current_state": "started"},
                    "local_worktree_facts": [
                        {"worktree_path": str(worktree.resolve())}
                    ],
                },
            }),
            encoding="utf-8",
        )
        return worker_path, status_path, worktree

    def test_playbook_adapter_capture_and_verify_bind_one_action(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker, status, worktree = self.write_playbook_snapshots(root)
            output = root / "binding.json"
            captured = PLAYBOOK_ADAPTER.create_receipt(
                worker,
                status,
                output,
                "implementation",
                "stable-xiaoh-workspace",
                "playbook version 0.0.40",
                sys.executable,
            )
            verified = PLAYBOOK_ADAPTER.validate_receipt(
                output,
                expected_sha256=captured["receipt_sha256"],
                expected_action="implementation",
            )

        self.assertEqual("captured", captured["status"])
        self.assertEqual("stable-xiaoh-workspace", verified["xiaoh_workspace_id"])
        self.assertEqual(str(worktree.resolve()), verified["playbook"]["member_worktree"])
        self.assertEqual("implementation", verified["delegated_action"])

    def test_playbook_integration_modes_keep_standalone_core_available(self):
        with patch.object(PLAYBOOK_ADAPTER.shutil, "which", return_value=None):
            automatic = PLAYBOOK_ADAPTER.playbook_probe(mode="auto")
            enabled = PLAYBOOK_ADAPTER.playbook_probe(mode="enabled")
        with patch.object(PLAYBOOK_ADAPTER.shutil, "which") as lookup:
            disabled = PLAYBOOK_ADAPTER.playbook_probe(mode="disabled")

        self.assertEqual("not_enabled", automatic["status"])
        self.assertEqual("auto", automatic["mode"])
        self.assertFalse(automatic["errors"])
        self.assertEqual("missing", enabled["status"])
        self.assertEqual("enabled", enabled["mode"])
        self.assertEqual("not_enabled", disabled["status"])
        lookup.assert_not_called()

    def test_playbook_integration_mode_reads_auto_boolean_and_rejects_invalid(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "config.json"
            self.assertEqual(
                "auto", PLAYBOOK_ADAPTER.configured_integration_mode(config)
            )
            config.write_text(
                '{"integrations":{"playbook":true}}\n', encoding="utf-8"
            )
            self.assertEqual(
                "enabled", PLAYBOOK_ADAPTER.configured_integration_mode(config)
            )
            config.write_text(
                '{"integrations":{"playbook":false}}\n', encoding="utf-8"
            )
            self.assertEqual(
                "disabled", PLAYBOOK_ADAPTER.configured_integration_mode(config)
            )
            config.write_text(
                '{"integrations":{"playbook":"sometimes"}}\n', encoding="utf-8"
            )
            with self.assertRaisesRegex(
                PLAYBOOK_ADAPTER.AdapterError, "integrations.playbook"
            ):
                PLAYBOOK_ADAPTER.configured_integration_mode(config)

    def test_playbook_adapter_report_reflects_configured_mode_when_cli_is_missing(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            XIAOH.subprocess, "run"
        ) as invoke:
            missing_command = str(Path(temporary) / "missing-playbook")
            automatic = XIAOH.playbook_adapter_report(
                {"integrations": {"playbook": "auto"}},
                playbook_command=missing_command,
            )
            enabled = XIAOH.playbook_adapter_report(
                {"integrations": {"playbook": "enabled"}},
                playbook_command=missing_command,
            )
            disabled = XIAOH.playbook_adapter_report(
                {"integrations": {"playbook": "disabled"}},
                playbook_command=missing_command,
            )
            invoke.assert_not_called()

        self.assertEqual(("auto", "not_enabled"), (automatic["mode"], automatic["status"]))
        self.assertEqual(("enabled", "missing"), (enabled["mode"], enabled["status"]))
        self.assertEqual(("disabled", "not_enabled"), (disabled["mode"], disabled["status"]))

    def test_playbook_adapter_rejects_ambiguous_status_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker, status, _ = self.write_playbook_snapshots(root)
            status.write_text(
                json.dumps({
                    "status": "ok",
                    "data": [
                        {"workspace_id": "pb-task-workspace", "change_id": "change-1"},
                        {"workspace_id": "other-workspace", "change_id": "change-1"},
                    ],
                }),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(PLAYBOOK_ADAPTER.AdapterError, "不唯一或不一致"):
                PLAYBOOK_ADAPTER.create_receipt(
                    worker,
                    status,
                    root / "binding.json",
                    "implementation",
                    "stable-xiaoh-workspace",
                    playbook_command=sys.executable,
                )

    def test_playbook_adapter_rejects_stale_or_changed_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker, status, _ = self.write_playbook_snapshots(root)
            output = root / "binding.json"
            captured = PLAYBOOK_ADAPTER.create_receipt(
                worker,
                status,
                output,
                "verification",
                "stable-xiaoh-workspace",
                playbook_command=sys.executable,
            )
            receipt = json.loads(output.read_text(encoding="utf-8"))
            receipt["captured_at"] = (
                datetime.now(timezone.utc) - timedelta(hours=1)
            ).isoformat()
            receipt.pop("binding_sha256")
            receipt["binding_sha256"] = PLAYBOOK_ADAPTER.canonical_hash(receipt)
            output.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaisesRegex(PLAYBOOK_ADAPTER.AdapterError, "已过期"):
                PLAYBOOK_ADAPTER.validate_receipt(
                    output,
                    expected_sha256=PLAYBOOK_ADAPTER.file_hash(output),
                    expected_action="verification",
                )

            PLAYBOOK_ADAPTER.create_receipt(
                worker,
                status,
                output,
                "verification",
                "stable-xiaoh-workspace",
                playbook_command=sys.executable,
            )
            status.write_text('{"status":"ok","changed":true}', encoding="utf-8")
            with self.assertRaisesRegex(PLAYBOOK_ADAPTER.AdapterError, "来源已变化"):
                PLAYBOOK_ADAPTER.validate_receipt(
                    output,
                    expected_sha256=PLAYBOOK_ADAPTER.file_hash(output),
                    expected_action="verification",
                )

    def test_managed_context_binding_matches_receipt_identity_and_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker, status, worktree = self.write_playbook_snapshots(root)
            output = root / "binding.json"
            captured = PLAYBOOK_ADAPTER.create_receipt(
                worker,
                status,
                output,
                "implementation",
                "stable-xiaoh-workspace",
                playbook_command=sys.executable,
            )
            context = {
                "intent": {"domain": "business_project"},
                "scope": {"allowed_paths": [str(worktree.resolve())]},
                "routing": {
                    "delegated_agents": ["java_implementer"],
                    "delegated_actions": {"java_implementer": "implementation"},
                },
                "playbook": {
                    "managed": True,
                    "workspace_id": "pb-task-workspace",
                    "xiaoh_workspace_id": "stable-xiaoh-workspace",
                    "task_workspace_id": "pb-task-workspace",
                    "change_id": "change-1",
                    "member": "member-a",
                    "member_worktree": str(worktree.resolve()),
                    "workspace_root": str(root.resolve()),
                    "allowed_scope": [str(worktree.resolve())],
                    "worker_contract_source": str(worker.resolve()),
                    "adapter_receipt": str(output.resolve()),
                    "adapter_receipt_sha256": captured["receipt_sha256"],
                },
            }
            report = VALIDATOR.Report()
            with patch.object(
                VALIDATOR,
                "playbook_probe",
                return_value={"status": "compatible", "errors": []},
            ):
                receipt = VALIDATOR.validate_playbook_binding(
                    context,
                    report,
                    check_paths=True,
                    require_binding=True,
                    check_live_status=False,
                )

        self.assertFalse(report.errors)
        self.assertEqual("implementation", receipt["delegated_action"])

    def test_managed_context_rejects_incompatible_playbook_probe(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker, status, worktree = self.write_playbook_snapshots(root)
            output = root / "binding.json"
            captured = PLAYBOOK_ADAPTER.create_receipt(
                worker,
                status,
                output,
                "implementation",
                "stable-xiaoh-workspace",
                playbook_command=sys.executable,
            )
            context = {
                "intent": {"domain": "business_project"},
                "scope": {"allowed_paths": [str(worktree.resolve())]},
                "routing": {
                    "delegated_agents": ["java_implementer"],
                    "delegated_actions": {"java_implementer": "implementation"},
                },
                "playbook": {
                    "managed": True,
                    "workspace_id": "pb-task-workspace",
                    "xiaoh_workspace_id": "stable-xiaoh-workspace",
                    "task_workspace_id": "pb-task-workspace",
                    "change_id": "change-1",
                    "member": "member-a",
                    "member_worktree": str(worktree.resolve()),
                    "workspace_root": str(root.resolve()),
                    "allowed_scope": [str(worktree.resolve())],
                    "worker_contract_source": str(worker.resolve()),
                    "adapter_receipt": str(output.resolve()),
                    "adapter_receipt_sha256": captured["receipt_sha256"],
                },
            }
            report = VALIDATOR.Report()
            with patch.object(
                VALIDATOR,
                "playbook_probe",
                return_value={
                    "status": "incompatible",
                    "errors": ["worker contract unavailable"],
                },
            ):
                receipt = VALIDATOR.validate_playbook_binding(
                    context,
                    report,
                    check_paths=True,
                    require_binding=True,
                    check_live_status=False,
                )

        self.assertIsNone(receipt)
        self.assertTrue(report.errors)
        self.assertIn("requires a compatible adapter probe", report.errors[0])

    def test_managed_context_formal_binding_fails_closed_when_receipt_missing(self):
        context = {
            "intent": {"domain": "business_project"},
            "routing": {
                "delegated_agents": ["java_implementer"],
                "delegated_actions": {"java_implementer": "implementation"},
            },
            "playbook": {"managed": True},
        }
        report = VALIDATOR.Report()

        VALIDATOR.validate_playbook_binding(
            context, report, check_paths=False, require_binding=True
        )

        self.assertTrue(report.errors)
        self.assertIn("lacks XiaoH adapter binding", report.errors[0])

    def test_managed_context_is_forbidden_when_playbook_integration_is_disabled(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "config.json"
            config.write_text(
                '{"integrations":{"playbook":false}}\n', encoding="utf-8"
            )
            report = VALIDATOR.Report()
            with patch.dict(
                os.environ, {"XIAOH_CONFIG": str(config)}, clear=False
            ):
                VALIDATOR.validate_playbook_binding(
                    {
                        "intent": {"domain": "business_project"},
                        "routing": {},
                        "playbook": {"managed": True},
                    },
                    report,
                    check_paths=True,
                    require_binding=True,
                )

        self.assertTrue(report.errors)
        self.assertIn("integrations.playbook is disabled", report.errors[0])

    def test_playbook_adapter_rejects_old_or_terminal_source_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker, status, worktree = self.write_playbook_snapshots(root)
            old = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
            os.utime(worker, (old, old))
            os.utime(status, (old, old))
            with self.assertRaisesRegex(PLAYBOOK_ADAPTER.AdapterError, "不是刚刚生成"):
                PLAYBOOK_ADAPTER.create_receipt(
                    worker,
                    status,
                    root / "old-binding.json",
                    "implementation",
                    "stable-xiaoh-workspace",
                    playbook_command=sys.executable,
                )

            worker, status, _ = self.write_playbook_snapshots(root)
            status.write_text(
                json.dumps({
                    "status": "ok",
                    "data": {
                        "workspace_id": "pb-task-workspace",
                        "change_id": "change-1",
                        "task_next": {"current_state": "completed"},
                        "local_worktree_facts": [
                            {"worktree_path": str(worktree.resolve())}
                        ],
                    },
                }),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(PLAYBOOK_ADAPTER.AdapterError, "非终态"):
                PLAYBOOK_ADAPTER.create_receipt(
                    worker,
                    status,
                    root / "terminal-binding.json",
                    "implementation",
                    "stable-xiaoh-workspace",
                    playbook_command=sys.executable,
                )

    def test_managed_context_rejects_every_scope_outside_task_authorization(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside"
            outside.mkdir()
            worker, status, worktree = self.write_playbook_snapshots(root)
            worker_payload = json.loads(worker.read_text(encoding="utf-8"))
            worker_payload["data"]["child_worker_context"]["allowed_scope"] = [
                str(worktree.resolve()),
                str(outside.resolve()),
            ]
            worker.write_text(json.dumps(worker_payload), encoding="utf-8")
            with self.assertRaisesRegex(PLAYBOOK_ADAPTER.AdapterError, "超出member_worktree"):
                PLAYBOOK_ADAPTER.create_receipt(
                    worker,
                    status,
                    root / "binding.json",
                    "implementation",
                    "stable-xiaoh-workspace",
                    playbook_command=sys.executable,
                )

    def test_historical_receipt_can_be_audited_without_current_freshness(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker, status, _ = self.write_playbook_snapshots(root)
            output = root / "binding.json"
            PLAYBOOK_ADAPTER.create_receipt(
                worker,
                status,
                output,
                "verification",
                "stable-xiaoh-workspace",
                playbook_command=sys.executable,
            )
            receipt = json.loads(output.read_text(encoding="utf-8"))
            receipt["captured_at"] = (
                datetime.now(timezone.utc) - timedelta(hours=1)
            ).isoformat()
            receipt.pop("binding_sha256")
            receipt["binding_sha256"] = PLAYBOOK_ADAPTER.canonical_hash(receipt)
            output.write_text(json.dumps(receipt), encoding="utf-8")

            verified = PLAYBOOK_ADAPTER.validate_receipt(
                output,
                expected_sha256=PLAYBOOK_ADAPTER.file_hash(output),
                expected_action="verification",
                max_age_seconds=None,
                check_live_status=False,
            )

        self.assertEqual("verification", verified["delegated_action"])

    def test_playbook_adapter_rechecks_live_status_before_delegation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker, status, worktree = self.write_playbook_snapshots(root)
            output = root / "binding.json"
            PLAYBOOK_ADAPTER.create_receipt(
                worker,
                status,
                output,
                "implementation",
                "stable-xiaoh-workspace",
                playbook_command=sys.executable,
            )
            current = {
                "status": "ok",
                "workspace_id": "pb-task-workspace",
                "change_id": "change-1",
                "task_next": {"current_state": "started"},
                "local_worktree_facts": [
                    {"worktree_path": str(worktree.resolve())}
                ],
            }
            completed = SimpleNamespace(
                returncode=0,
                stdout=json.dumps(current),
                stderr="",
            )
            with patch.object(
                PLAYBOOK_ADAPTER.subprocess, "run", return_value=completed
            ) as invoked:
                PLAYBOOK_ADAPTER.validate_receipt(
                    output,
                    expected_sha256=PLAYBOOK_ADAPTER.file_hash(output),
                    expected_action="implementation",
                    check_live_status=True,
                )

        invoked.assert_called_once()

    def test_managed_delegation_effective_brief_binds_action_and_worker_scope(self):
        context = {
            "intent": {"domain": "business_project"},
            "routing": {
                "delegated_actions": {"java_implementer": "implementation"},
            },
            "playbook": {
                "managed": True,
                "adapter_receipt": "/evidence/binding.json",
                "adapter_receipt_sha256": "a" * 64,
                "task_workspace_id": "pb-task-workspace",
                "member": "member-a",
                "member_worktree": "/workspace/member-a",
                "workspace_root": "/workspace",
                "allowed_scope": ["/workspace/member-a"],
            },
        }
        brief = DELEGATION_HOOK.effective_brief(
            {
                "task_id": "task-1",
                "task_context": "/evidence/task-context.json",
                "context_hash": "b" * 64,
                "delegated_agent": "java_implementer",
            },
            {"agent_type": "java_implementer", "task_name": "implementation"},
            context,
        )

        self.assertEqual("1.1", brief["schema_version"])
        self.assertEqual("implementation", brief["delegated_action"])
        self.assertEqual(["/workspace/member-a"], brief["playbook_allowed_scope"])

    def test_managed_delegation_effective_brief_rejects_missing_binding(self):
        context = {
            "intent": {"domain": "business_project"},
            "routing": {
                "delegated_actions": {"java_implementer": "implementation"},
            },
            "playbook": {"managed": True},
        }

        with self.assertRaisesRegex(ValueError, "lacks"):
            DELEGATION_HOOK.effective_brief(
                {
                    "task_id": "task-1",
                    "task_context": "/evidence/task-context.json",
                    "context_hash": "b" * 64,
                    "delegated_agent": "java_implementer",
                },
                {"agent_type": "java_implementer", "task_name": "implementation"},
                context,
            )

    def test_subagent_start_revalidates_managed_playbook_binding(self):
        context = {
            "intent": {"domain": "business_project"},
            "playbook": {"managed": True},
        }
        completed = SimpleNamespace(returncode=1, stdout="stale binding", stderr="")
        with patch.object(
            DELEGATION_HOOK.subprocess, "run", return_value=completed
        ) as invoked:
            with self.assertRaisesRegex(ValueError, "no longer valid"):
                DELEGATION_HOOK.revalidate_managed_playbook_context(
                    context,
                    Path("/evidence/task-context.json"),
                    Path("/codex"),
                )

        invoked.assert_called_once()

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

        self.assertEqual("complete", result["status"])
        self.assertEqual(10, len(result["installed_now"]))
        self.assertTrue(all(item["status"] == "installed" for item in result["plugins"]))
        self.assertIn(
            ["plugin", "marketplace", "add", "DietrichGebert/ponytail", "--ref", "main"],
            calls,
        )
        self.assertEqual("missing", result["external_capabilities"][0]["status"])
        self.assertFalse(result["warnings"])
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
        self.assertEqual("auto", merged["integrations"]["playbook"])

    def test_local_config_preserves_integration_values_and_rejects_invalid_shape(self):
        merged = XIAOH.merged_local_config(
            {
                "integrations": {
                    "playbook": False,
                    "future-adapter": {"enabled": True},
                }
            },
            Path("/codex"),
            Path("/vault"),
            "2.13.0",
        )

        self.assertEqual("disabled", merged["integrations"]["playbook"])
        self.assertEqual(
            {"enabled": True}, merged["integrations"]["future-adapter"]
        )
        with self.assertRaisesRegex(ValueError, "integrations必须是JSON对象"):
            XIAOH.merged_local_config(
                {"integrations": []},
                Path("/codex"),
                Path("/vault"),
                "2.13.0",
            )

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

    def test_setup_rejects_invalid_integration_mode_before_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex = root / "codex"
            vault = root / "vault"
            config = root / "config.json"
            marker = codex / "retained.txt"
            marker.parent.mkdir()
            marker.write_text("retained\n", encoding="utf-8")
            config.write_text(
                '{"integrations":{"playbook":"sometimes"}}\n',
                encoding="utf-8",
            )
            args = SimpleNamespace(
                codex_home=str(codex),
                vault=str(vault),
                config=str(config),
                active_skill_root=None,
            )

            result = XIAOH.install(args, "update")
            marker_text = marker.read_text(encoding="utf-8")

        self.assertEqual("failed", result["status"])
        self.assertIn("integrations.playbook", result["errors"][0])
        self.assertEqual("retained\n", marker_text)

    def test_custom_config_path_is_bound_into_every_runtime_hook(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex = root / "codex"
            vault = root / "vault"
            config = root / "custom/xiaoh.json"
            config.parent.mkdir()
            config.write_text(
                json.dumps(
                    {
                        "obsidian_vault": str(vault),
                        "integrations": {"playbook": "disabled"},
                    }
                ),
                encoding="utf-8",
            )

            XIAOH.copy_runtime(codex, vault, config)
            rendered = (codex / "config.toml").read_text(encoding="utf-8")

        self.assertNotIn("__XIAOH_CONFIG__", rendered)
        self.assertEqual(8, rendered.count(f'--config "{config.resolve().as_posix()}"'))

    def test_hook_config_argument_controls_validator_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "custom.json"
            config.write_text(
                '{"integrations":{"playbook":"disabled"}}\n', encoding="utf-8"
            )
            previous = os.environ.pop("XIAOH_CONFIG", None)
            try:
                remaining = DELEGATION_HOOK.runtime_arguments(
                    ["--config", str(config), "--subagent-start"]
                )
                mode = PLAYBOOK_ADAPTER.configured_integration_mode()
            finally:
                if previous is None:
                    os.environ.pop("XIAOH_CONFIG", None)
                else:
                    os.environ["XIAOH_CONFIG"] = previous

        self.assertEqual(["--subagent-start"], remaining)
        self.assertEqual("disabled", mode)

    def test_isolated_runtime_global_validator_accepts_bound_custom_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex = root / "codex"
            vault = root / "vault"
            config = root / "custom/xiaoh.json"
            target_agents, vault_files, _ = XIAOH.copy_runtime(
                codex, vault, config
            )
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
                    ("__XIAOH_CONFIG__", config.as_posix()),
                    ("__OBSIDIAN_VAULT__", vault.as_posix()),
                    ("__USER_HOME__", root.as_posix()),
                ],
            )
            XIAOH.refresh_templates(codex)
            config.parent.mkdir(parents=True, exist_ok=True)
            XIAOH.atomic_write_json(
                config,
                XIAOH.merged_local_config(
                    {"integrations": {"playbook": "disabled"}},
                    codex,
                    vault,
                    XIAOH.load_json(XIAOH.PLUGIN_MANIFEST)["version"],
                ),
            )
            environment = {
                **os.environ,
                "CODEX_HOME": str(codex),
                "XIAOH_CONFIG": str(config),
                "XIAOH_VAULT": str(vault),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            completed = subprocess.run(
                [sys.executable, str(codex / "agent-system/validate.py")],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=environment,
                check=False,
            )

        self.assertEqual(
            0, completed.returncode, completed.stderr or completed.stdout
        )

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
