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

HOOK_RUNTIME_SCRIPT = (
    Path(__file__).parents[1]
    / "plugins/xiaoh/runtime/codex/hooks/verify_agent_hook_runtime.py"
)
HOOK_RUNTIME_SPEC = importlib.util.spec_from_file_location(
    "xiaoh_hook_runtime", HOOK_RUNTIME_SCRIPT
)
HOOK_RUNTIME = importlib.util.module_from_spec(HOOK_RUNTIME_SPEC)
HOOK_RUNTIME_SPEC.loader.exec_module(HOOK_RUNTIME)


class CompanionTests(unittest.TestCase):
    def test_hook_runtime_probe_retries_timeout_then_succeeds(self):
        expected = {"data": [{"hooks": []}]}
        with patch.object(
            HOOK_RUNTIME,
            "query_hooks",
            side_effect=[
                HOOK_RUNTIME.RuntimeProbeTimeout("hooks/list timed out"),
                expected,
            ],
        ) as query:
            actual = HOOK_RUNTIME.query_hooks_with_retry(
                "codex", Path("/tmp/codex"), Path("/tmp/workspace")
            )

        self.assertEqual(expected, actual)
        self.assertEqual(2, query.call_count)

    def test_hook_runtime_probe_reports_all_exhausted_timeouts(self):
        with patch.object(
            HOOK_RUNTIME,
            "query_hooks",
            side_effect=HOOK_RUNTIME.RuntimeProbeTimeout(
                "hooks/list request id=1 timed out after 15 seconds"
            ),
        ) as query:
            with self.assertRaisesRegex(
                HOOK_RUNTIME.RuntimeProbeTimeout,
                r"exhausted retries.*attempt 1/3.*attempt 3/3.*hooks/list",
            ):
                HOOK_RUNTIME.query_hooks_with_retry(
                    "codex", Path("/tmp/codex"), Path("/tmp/workspace")
                )

        self.assertEqual(3, query.call_count)

    def test_hook_runtime_probe_lock_timeout_has_actionable_diagnostic(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            HOOK_RUNTIME, "try_lock", return_value=False
        ), patch.object(
            HOOK_RUNTIME.time, "monotonic", side_effect=[0, 61]
        ):
            with self.assertRaisesRegex(
                HOOK_RUNTIME.RuntimeProbeTimeout,
                r"lock remained busy for 60 seconds: .*xiaoh-runtime-probe-",
            ):
                with HOOK_RUNTIME.runtime_probe_lock(Path(temporary)):
                    self.fail("busy runtime probe lock must fail closed")

    def test_hook_runtime_probe_rejects_sandbox_as_non_authoritative(self):
        with patch.dict(os.environ, {"CODEX_SANDBOX": "seatbelt"}):
            with self.assertRaisesRegex(
                RuntimeError,
                r"不能在工具沙盒内执行.*批准doctor --runtime在非沙盒环境运行",
            ):
                HOOK_RUNTIME.verify(Path("/tmp/codex"), Path("/tmp/workspace"))

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
        self.assertIn("xiaoh-local-review", actual_skills)
        self.assertIn("humanizer", actual_skills)

    def test_user_facing_documentation_uses_bundled_humanizer_policy(self):
        root = Path(__file__).parents[1]
        readme = (root / "README.md").read_text(encoding="utf-8")
        guide = (root / "docs/xiaoh-guide.md").read_text(encoding="utf-8")
        core = (
            root / "plugins/xiaoh/skills/xiaoh-core/SKILL.md"
        ).read_text(encoding="utf-8")
        contract = (
            root / "plugins/xiaoh/runtime/codex/AGENTS.md"
        ).read_text(encoding="utf-8")

        self.assertIn("[认识小H](docs/xiaoh-guide.md)", readme)
        self.assertIn("独立`humanizer`", guide)
        self.assertIn("`xiaoh:humanizer`", guide)
        self.assertIn("同一份文档不会连续调用两个版本", guide)
        self.assertIn("$xiaoh:humanizer", core)
        self.assertIn("Never run both on the same document", core)
        self.assertIn("面向用户的文档表达", contract)
        self.assertIn("两者是替代关系", contract)

        user_docs = [
            root / "README.md",
            root / "docs/xiaoh-guide.md",
            root / "docs/implementation-design.md",
            root / "docs/xiaoh-playbook-relationship.md",
        ]
        for path in user_docs:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("—", text, path)
            self.assertNotIn("–", text, path)

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

    def write_local_review_fixture(
        self, root, mode="standalone", mixed_first_round=False
    ):
        context = json.loads(
            (
                Path(__file__).parents[1]
                / "plugins/xiaoh/runtime/codex/agent-system/task-context.template.json"
            ).read_text(encoding="utf-8")
        )
        context["schema_version"] = "1.5"
        context["routing"].pop("delegation_policies", None)
        context["playbook"].update({
            "stage": None,
            "worker_contract_source": None,
        })
        source = root / "source.md"
        source.write_text("implementation facts\n", encoding="utf-8")
        context.update({
            "task_id": "local-review-test",
            "task_type": "implementation",
            "risk_level": "medium",
            "sources": [{
                "path": str(source),
                "purpose": "implementation facts",
                "required": True,
            }],
        })
        context["scope"].update({
            "workspace": str(root),
            "repositories": [],
            "allowed_paths": [str(root)],
            "prohibited_actions": ["external writes"],
        })
        context["routing"].update({
            "delegated_agents": [
                "java_implementer",
                "code_quality_reviewer",
                "test_integration_verifier",
            ],
            "delegation_names": {
                "java_implementer": "implement",
                "code_quality_reviewer": "quality_review",
                "test_integration_verifier": "test_review",
            },
            "delegated_actions": {
                "java_implementer": "implementation",
                "code_quality_reviewer": "code_review",
                "test_integration_verifier": "verification",
            },
            "independent_review_required": True,
            "independent_review_agents": [
                "code_quality_reviewer",
                "test_integration_verifier",
            ],
        })
        context["freshness"]["checked_at"] = datetime.now(timezone.utc).isoformat()
        if mode == "playbook_managed":
            context["playbook"]["managed"] = True
        context_path = root / "task-context.json"
        context_path.write_text(
            json.dumps(context, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        context_hash = hashlib.sha256(context_path.read_bytes()).hexdigest()
        codex_root = root / "codex"
        system_dir = codex_root / "agent-system"
        proof_dir = system_dir / "delegation-proofs"
        sessions_dir = codex_root / "sessions"
        hook_path = root / "hooks" / "block_reserved_root_agent.py"
        proof_dir.mkdir(parents=True)
        sessions_dir.mkdir(parents=True)
        hook_path.parent.mkdir(parents=True)
        hook_path.write_text("# test hook\n", encoding="utf-8")
        self.local_review_runtime = {
            "codex": codex_root,
            "system_dir": system_dir,
            "hook": hook_path,
        }
        artifact_path = root / "accepted-artifact.bin"
        artifact_path.write_bytes(b"accepted artifact")
        subject = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        round_evidence = []
        for round_number, verdict, blocking_findings in (
            (1, "changes_requested", 1),
            (2, "passed", 0),
        ):
            evidence = {}
            for reviewer in (
                "code_quality_reviewer",
                "test_integration_verifier",
            ):
                reviewer_verdict = verdict
                reviewer_findings = blocking_findings
                if (
                    mixed_first_round
                    and round_number == 1
                    and reviewer == "test_integration_verifier"
                ):
                    reviewer_verdict = "passed"
                    reviewer_findings = 0
                run_path = root / "{}-round-{}-run.json".format(
                    reviewer, round_number
                )
                agent_id = "{}-round-{}-agent".format(reviewer, round_number)
                parent_id = "root-thread"
                task_name = context["routing"]["delegation_names"][reviewer]
                agent_path = "/root/{}".format(task_name)
                claim = {
                    "schema_version": "xiaoh-local-review-claim/v1",
                    "task_id": context["task_id"],
                    "context_hash": context_hash,
                    "reviewer": reviewer,
                    "round": round_number,
                    "subject_value": subject,
                    "verdict": reviewer_verdict,
                    "blocking_findings": reviewer_findings,
                }
                canonical_claim = json.dumps(
                    claim,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                receipt = "{}-round-{}-receipt".format(reviewer, round_number)
                attested_message = (
                    "review complete\n"
                    "xiaoh-local-review-claim: {}\n"
                    "xiaoh-delegation-receipt: {}"
                ).format(canonical_claim, receipt)
                transcript_path = sessions_dir / "{}.jsonl".format(agent_id)
                transcript_events = [
                    {
                        "type": "session_meta",
                        "payload": {
                            "id": agent_id,
                            "parent_thread_id": parent_id,
                            "source": {
                                "subagent": {
                                    "thread_spawn": {
                                        "agent_role": reviewer,
                                        "agent_path": agent_path,
                                    }
                                }
                            },
                        },
                    },
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "agent_message",
                            "author": "/root",
                            "recipient": agent_path,
                            "content": [{
                                "type": "input_text",
                                "text": "Message Type: NEW_TASK\nTask name: {}".format(
                                    agent_path
                                ),
                            }],
                        },
                    },
                    {"type": "event_msg", "payload": {"type": "task_complete"}},
                ]
                transcript_path.write_text(
                    "\n".join(json.dumps(item) for item in transcript_events) + "\n",
                    encoding="utf-8",
                )
                now = datetime.now(timezone.utc).isoformat()
                proof_path = proof_dir / "{}.json".format(agent_id)
                effective_brief = {
                    "schema_version": "1.0",
                    "task_id": context["task_id"],
                    "task_context": str(context_path.resolve()),
                    "context_hash": context_hash,
                    "delegated_agent": reviewer,
                    "agent_type": reviewer,
                    "task_name": task_name,
                    "authority": "task_context_is_authoritative",
                }
                proof = {
                    "schema_version": "1.2",
                    "state": "attested",
                    "prepared_at": now,
                    "started_at": now,
                    "attested_at": now,
                    "source": "subagent-start-stop",
                    "session_id": parent_id,
                    "turn_id": "turn-{}".format(round_number),
                    "stop_turn_id": "stop-turn-{}".format(round_number),
                    "agent_id": agent_id,
                    "task_id": context["task_id"],
                    "task_context": str(context_path.resolve()),
                    "context_hash": context_hash,
                    "delegated_agent": reviewer,
                    "agent_type": reviewer,
                    "task_name": task_name,
                    "effective_brief": effective_brief,
                    "effective_brief_hash": hashlib.sha256(
                        json.dumps(
                            effective_brief,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest(),
                    "transport_message_hash": "1" * 64,
                    "receipt_hash": hashlib.sha256(
                        receipt.encode("utf-8")
                    ).hexdigest(),
                    "agent_transcript_path": str(transcript_path.resolve()),
                    "last_message_hash": hashlib.sha256(
                        attested_message.encode("utf-8")
                    ).hexdigest(),
                    "hook_path": str(hook_path),
                    "hook_hash": hashlib.sha256(hook_path.read_bytes()).hexdigest(),
                }
                proof_path.write_text(json.dumps(proof), encoding="utf-8")
                run_record = {
                    "schema_version": "1.2",
                    "run_id": "{}-round-{}".format(reviewer, round_number),
                    "task_id": context["task_id"],
                    "agent": reviewer,
                    "role": "independent reviewer",
                    "selection_reason": "local review fixture",
                    "context_pack": str(context_path),
                    "status": "completed",
                    "context_hash": context_hash,
                    "started_at": now,
                    "ended_at": now,
                    "gates": [{
                        "name": "independent_review",
                        "status": "passed",
                        "evidence": str(proof_path),
                    }],
                    "verification": [{
                        "command": "review",
                        "status": "passed",
                        "summary": "review completed",
                    }],
                    "outputs": {
                        "local_review": {
                            "round": round_number,
                            "subject_value": subject,
                            "verdict": reviewer_verdict,
                            "blocking_findings": reviewer_findings,
                            "claim_hash": hashlib.sha256(
                                canonical_claim.encode("utf-8")
                            ).hexdigest(),
                        }
                    },
                    "runtime_evidence": {
                        "source": "codex-runtime",
                        "agent_type": reviewer,
                        "task_name": task_name,
                        "agent_id": agent_id,
                        "parent_agent_id": parent_id,
                        "transcript_path": str(transcript_path),
                        "transcript_hash": hashlib.sha256(
                            transcript_path.read_bytes()
                        ).hexdigest(),
                        "terminal_event": "task_complete",
                        "delegation_proof_path": str(proof_path),
                        "delegation_proof_hash": hashlib.sha256(
                            proof_path.read_bytes()
                        ).hexdigest(),
                    },
                    "rework": {"count": 0, "reasons": []},
                    "metrics": {
                        "context_supplements": 0,
                        "boundary_violations": 0,
                        "verification_failures": 0,
                        "escaped_defects": 0,
                        "result_accepted": reviewer_verdict == "passed",
                    },
                    "agent_improvement_candidates": [],
                }
                run_path.write_text(json.dumps(run_record), encoding="utf-8")
                report_path = root / "{}-round-{}-report.json".format(
                    reviewer, round_number
                )
                report_path.write_text(
                    json.dumps({
                        "schema_version": "xiaoh-local-review-evidence/v1",
                        "task_id": context["task_id"],
                        "context_hash": context_hash,
                        "reviewer": reviewer,
                        "round": round_number,
                        "subject_value": subject,
                        "verdict": reviewer_verdict,
                        "blocking_findings": reviewer_findings,
                        "attested_message": attested_message,
                        "run_record": {
                            "path": str(run_path),
                            "sha256": hashlib.sha256(run_path.read_bytes()).hexdigest(),
                        },
                    }),
                    encoding="utf-8",
                )
                evidence[reviewer] = {
                    "reviewer": reviewer,
                    "path": str(report_path),
                    "sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
                }
            round_evidence.append(evidence)
        manifest = {
            "schema_version": "xiaoh-local-review/v1",
            "task_id": context["task_id"],
            "task_context": {
                "path": str(context_path),
                "sha256": hashlib.sha256(context_path.read_bytes()).hexdigest(),
            },
            "mode": mode,
            "subject": {
                "kind": "artifact_digest",
                "repository": None,
                "artifact_path": str(artifact_path),
                "value": subject,
            },
            "implementers": ["java_implementer"],
            "rounds": [
                {
                    "number": 1,
                    "subject_value": subject,
                    "reviewers": list(evidence),
                    "verdict": "changes_requested",
                    "blocking_findings": 1 if mixed_first_round else 2,
                    "evidence": list(round_evidence[0].values()),
                },
                {
                    "number": 2,
                    "subject_value": subject,
                    "reviewers": list(evidence),
                    "verdict": "passed",
                    "blocking_findings": 0,
                    "evidence": list(round_evidence[1].values()),
                },
            ],
            "final_status": "passed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        return context, context_path, manifest, round_evidence

    def test_implementation_context_requires_two_independent_review_roles(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context, _, _, _ = self.write_local_review_fixture(root)
            context["routing"]["independent_review_agents"] = [
                "code_quality_reviewer"
            ]
            report = VALIDATOR.Report()
            VALIDATOR.validate_task_context(context, report, check_paths=False)

        self.assertTrue(any(
            "at least two independent review roles" in error
            for error in report.errors
        ), report.errors)

    def write_v16_delegation_fixture(self, root):
        home = root / "codex"
        (home / "agents").mkdir(parents=True)
        (home / "hooks").mkdir()
        (home / "agent-system").mkdir()
        (home / "hooks/block_reserved_root_agent.py").write_bytes(
            DELEGATION_HOOK_SCRIPT.read_bytes()
        )
        (home / "agent-system/validate.py").write_bytes(
            VALIDATOR_SCRIPT.read_bytes()
        )
        (home / "agent-system/playbook_adapter.py").write_bytes(
            PLAYBOOK_ADAPTER_SCRIPT.read_bytes()
        )
        for reviewer in ("code_quality_reviewer", "test_integration_verifier"):
            (home / "agents" / "{}.toml".format(reviewer)).write_text(
                'name = "{}"\n'.format(reviewer), encoding="utf-8"
            )
        source = root / "source.md"
        source.write_text("v1.6 delegation facts\n", encoding="utf-8")
        context = json.loads(
            (
                Path(__file__).parents[1]
                / "plugins/xiaoh/runtime/codex/agent-system/task-context.template.json"
            ).read_text(encoding="utf-8")
        )
        context.update({
            "task_id": "delegation-v16-test",
            "task_type": "implementation",
            "risk_level": "high",
            "sources": [{
                "path": str(source),
                "purpose": "v1.6 delegation facts",
                "required": True,
            }],
        })
        context["scope"].update({
            "workspace": str(root),
            "repositories": [],
            "allowed_paths": [str(root)],
            "prohibited_actions": ["external writes"],
        })
        context["routing"].update({
            "delegated_agents": [
                "code_quality_reviewer",
                "test_integration_verifier",
            ],
            "delegation_policies": {
                "code_quality_reviewer": {
                    "agent_type": "code_quality_reviewer",
                    "action": "code_review",
                    "task_name_prefix": "quality",
                },
                "test_integration_verifier": {
                    "agent_type": "test_integration_verifier",
                    "action": "verification",
                    "task_name_prefix": "verification",
                },
            },
            "independent_review_required": True,
            "independent_review_agents": [
                "code_quality_reviewer",
                "test_integration_verifier",
            ],
        })
        context["freshness"]["checked_at"] = datetime.now(timezone.utc).isoformat()
        context_path = root / "task-context-v16.json"
        context_path.write_text(json.dumps(context), encoding="utf-8")
        return home, context, context_path

    def test_v16_execution_bindings_allow_unique_multi_round_task_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, context, context_path = self.write_v16_delegation_fixture(root)
            authority = VALIDATOR.task_authority_hash(context)
            previous_thread = os.environ.get("CODEX_THREAD_ID")
            os.environ["CODEX_THREAD_ID"] = "v16-parent"
            bindings = []
            try:
                for round_number, suffix in ((1, "a1b2c3d4"), (2, "e5f6a7b8")):
                    task_name = "quality__r{}__{}".format(round_number, suffix)
                    message = (
                        "task_id: delegation-v16-test\n"
                        "task_context: {}\n"
                        "authority_hash: {}\n"
                        "delegated_agent: code_quality_reviewer\n"
                    ).format(context_path, authority)
                    payload = {
                        "binding": {
                            "review_round": round_number,
                            "purpose": "local_review",
                            "subject_digest": "a" * 64,
                        },
                        "tool_input": {
                            "task_name": task_name,
                            "agent_type": "code_quality_reviewer",
                            "message": message,
                        },
                    }
                    binding_path = DELEGATION_HOOK.prepare_delegation_intent(
                        payload, home, run_validator=False
                    )
                    binding_bytes = binding_path.read_bytes()
                    binding = json.loads(binding_bytes)
                    self.assertEqual(authority, binding["authority_hash"])
                    self.assertEqual(round_number, binding["review_round"])
                    prepared_message = (
                        message.rstrip()
                        + "\nexecution_binding: {}\nbinding_hash: {}\n".format(
                            binding_path,
                            hashlib.sha256(binding_bytes).hexdigest(),
                        )
                    )
                    checked_payload = {
                        "tool_input": {
                            "task_name": binding["task_name"],
                            "agent_type": "code_quality_reviewer",
                            "message": prepared_message,
                        }
                    }
                    self.assertIsNone(
                        DELEGATION_HOOK.decision(
                            checked_payload,
                            codex_home=home,
                            run_validator=False,
                            write_proof=False,
                        )
                    )
                    bindings.append(hashlib.sha256(binding_bytes).hexdigest())
                    binding_path.unlink()
            finally:
                if previous_thread is None:
                    os.environ.pop("CODEX_THREAD_ID", None)
                else:
                    os.environ["CODEX_THREAD_ID"] = previous_thread
        self.assertEqual(2, len(set(bindings)))

    def test_v16_subagent_start_consumes_binding_and_attests_schema_13_proof(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, context, context_path = self.write_v16_delegation_fixture(root)
            authority = VALIDATOR.task_authority_hash(context)
            message = (
                "task_id: delegation-v16-test\n"
                "task_context: {}\n"
                "authority_hash: {}\n"
                "delegated_agent: code_quality_reviewer\n"
            ).format(context_path, authority)
            payload = {
                "binding": {
                    "review_round": 1,
                    "purpose": "local_review",
                    "subject_digest": "a" * 64,
                },
                "tool_input": {
                    "task_name": "quality__r1__a1b2c3d4",
                    "agent_type": "code_quality_reviewer",
                    "message": message,
                },
            }
            environment = {
                "CODEX_HOME": str(home),
                "CODEX_THREAD_ID": "v16-parent",
            }
            with patch.dict(os.environ, environment):
                binding_path = DELEGATION_HOOK.prepare_delegation_intent(
                    payload, home, run_validator=True
                )
                started = DELEGATION_HOOK.consume_subagent_start(
                    {
                        "hook_event_name": "SubagentStart",
                        "session_id": "v16-parent",
                        "turn_id": "turn-1",
                        "agent_id": "quality-agent-1",
                        "agent_type": "code_quality_reviewer",
                    },
                    home,
                )
                self.assertIsNotNone(started)
                proof_path, injected = started
                proof = json.loads(proof_path.read_text(encoding="utf-8"))
                self.assertEqual("1.3", proof["schema_version"])
                self.assertEqual(authority, proof["authority_hash"])
                self.assertEqual(
                    VALIDATOR.canonical_json_hash(proof["effective_brief"]),
                    proof["effective_brief_hash"],
                )
                receipts = DELEGATION_HOOK.RECEIPT_PATTERN.findall(injected)
                self.assertEqual(1, len(receipts))
                transcript_path = root / "quality.jsonl"
                transcript_path.write_text("{}\n", encoding="utf-8")
                result = DELEGATION_HOOK.attest_subagent_stop(
                    {
                        "hook_event_name": "SubagentStop",
                        "session_id": "v16-parent",
                        "turn_id": "turn-2",
                        "agent_id": "quality-agent-1",
                        "agent_type": "code_quality_reviewer",
                        "agent_transcript_path": str(transcript_path),
                        "last_assistant_message": (
                            "passed\nxiaoh-delegation-receipt: " + receipts[0]
                        ),
                        "stop_hook_active": True,
                    },
                    home,
                )
                self.assertIsNone(result)
                self.assertFalse(binding_path.exists())
                proof = json.loads(proof_path.read_text(encoding="utf-8"))
                self.assertEqual("attested", proof["state"])
                proof_report = VALIDATOR.Report()
                run_record = {
                    "task_id": context["task_id"],
                    "context_hash": authority,
                    "agent": "code_quality_reviewer",
                    "outputs": {
                        "local_review": {
                            "round": 1,
                            "subject_value": "a" * 64,
                        }
                    },
                }
                runtime_evidence = {
                    "parent_agent_id": "v16-parent",
                    "agent_type": "code_quality_reviewer",
                    "task_name": proof["task_name"],
                    "agent_id": "quality-agent-1",
                    "transcript_path": str(transcript_path),
                    "delegation_proof_path": str(proof_path),
                    "delegation_proof_hash": hashlib.sha256(
                        proof_path.read_bytes()
                    ).hexdigest(),
                }
                with patch.object(
                    VALIDATOR, "SYSTEM_DIR", home / "agent-system"
                ), patch.object(
                    VALIDATOR,
                    "ROOT_AGENT_HOOK",
                    home / "hooks/block_reserved_root_agent.py",
                ):
                    VALIDATOR.validate_delegation_proof(
                        runtime_evidence,
                        run_record,
                        context,
                        context_path,
                        proof_report,
                        True,
                    )
                self.assertFalse(proof_report.errors, proof_report.errors)

                (home / "hooks/block_reserved_root_agent.py").write_text(
                    "# trusted hook upgraded after attestation\n", encoding="utf-8"
                )
                historical_report = VALIDATOR.Report()
                with patch.object(
                    VALIDATOR, "SYSTEM_DIR", home / "agent-system"
                ), patch.object(
                    VALIDATOR,
                    "ROOT_AGENT_HOOK",
                    home / "hooks/block_reserved_root_agent.py",
                ):
                    VALIDATOR.validate_delegation_proof(
                        runtime_evidence,
                        run_record,
                        context,
                        context_path,
                        historical_report,
                        True,
                    )
                self.assertFalse(historical_report.errors, historical_report.errors)

                proof["hook_hash"] = "f" * 64
                proof_path.write_text(json.dumps(proof), encoding="utf-8")
                runtime_evidence["delegation_proof_hash"] = hashlib.sha256(
                    proof_path.read_bytes()
                ).hexdigest()
                mismatch_report = VALIDATOR.Report()
                with patch.object(
                    VALIDATOR, "SYSTEM_DIR", home / "agent-system"
                ), patch.object(
                    VALIDATOR,
                    "ROOT_AGENT_HOOK",
                    home / "hooks/block_reserved_root_agent.py",
                ):
                    VALIDATOR.validate_delegation_proof(
                        runtime_evidence,
                        run_record,
                        context,
                        context_path,
                        mismatch_report,
                        True,
                    )
                self.assertTrue(
                    any(
                        "historical execution binding hook_hash does not match delegation proof"
                        in error
                        for error in mismatch_report.errors
                    ),
                    mismatch_report.errors,
                )

    def test_v16_execution_binding_rejects_expired_binding(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, context, context_path = self.write_v16_delegation_fixture(root)
            authority = VALIDATOR.task_authority_hash(context)
            message = (
                "task_id: delegation-v16-test\n"
                "task_context: {}\n"
                "authority_hash: {}\n"
                "delegated_agent: code_quality_reviewer\n"
            ).format(context_path, authority)
            previous_thread = os.environ.get("CODEX_THREAD_ID")
            os.environ["CODEX_THREAD_ID"] = "v16-parent"
            try:
                binding_path = DELEGATION_HOOK.prepare_delegation_intent(
                    {
                        "binding": {
                            "review_round": 1,
                            "purpose": "local_review",
                            "subject_digest": "a" * 64,
                        },
                        "tool_input": {
                            "task_name": "quality__r1__a1b2c3d4",
                            "agent_type": "code_quality_reviewer",
                            "message": message,
                        },
                    },
                    home,
                    run_validator=False,
                )
                binding = json.loads(binding_path.read_text(encoding="utf-8"))
                binding["prepared_at"] = (
                    datetime.now(timezone.utc) - timedelta(minutes=20)
                ).isoformat()
                binding["expires_at"] = (
                    datetime.now(timezone.utc) - timedelta(minutes=5)
                ).isoformat()
                report = VALIDATOR.Report()
                VALIDATOR.validate_execution_binding(
                    binding, context, context_path, report
                )
            finally:
                if previous_thread is None:
                    os.environ.pop("CODEX_THREAD_ID", None)
                else:
                    os.environ["CODEX_THREAD_ID"] = previous_thread
        self.assertTrue(
            any("execution binding is expired" in error for error in report.errors),
            report.errors,
        )

    def test_v16_execution_binding_rejects_wrong_namespace_and_action(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, context, context_path = self.write_v16_delegation_fixture(root)
            authority = VALIDATOR.task_authority_hash(context)
            message = (
                "task_id: delegation-v16-test\n"
                "task_context: {}\n"
                "authority_hash: {}\n"
                "delegated_agent: code_quality_reviewer\n"
            ).format(context_path, authority)
            denied = DELEGATION_HOOK.decision(
                {
                    "tool_input": {
                        "task_name": "verification__r1__a1b2c3d4",
                        "agent_type": "code_quality_reviewer",
                        "message": message,
                    }
                },
                codex_home=home,
                run_validator=False,
                write_proof=False,
                allow_unbound_v16=True,
            )
            self.assertEqual(
                "deny",
                denied["hookSpecificOutput"]["permissionDecision"],
            )

    def test_v16_hook_passes_delegated_binding_to_requirement_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, context, context_path = self.write_v16_delegation_fixture(root)
            worktree = root / "worktree"
            worktree.mkdir()
            context["intent"] = {"domain": "business_project"}
            context["routing"]["delegation_policies"][
                "code_quality_reviewer"
            ]["action"] = "implementation"
            context["playbook"] = {
                "managed": True,
                "workspace_id": "task-workspace",
                "xiaoh_workspace_id": "stable-workspace",
                "task_workspace_id": "task-workspace",
                "change_id": "change-1",
                "member": "member-a",
                "member_worktree": str(worktree),
                "workspace_root": str(root),
                "allowed_scope": [str(worktree)],
            }
            context_path.write_text(json.dumps(context), encoding="utf-8")
            authority = VALIDATOR.task_authority_hash(context)
            binding_path = root / "binding.json"
            binding = {
                "task_id": context["task_id"],
                "task_context": str(context_path.resolve()),
                "authority_hash": authority,
                "delegated_agent": "code_quality_reviewer",
                "agent_type": "code_quality_reviewer",
                "task_name": "quality__r1__a1b2c3d4",
                "action": "implementation",
            }
            binding_path.write_text(json.dumps(binding), encoding="utf-8")
            binding_hash = hashlib.sha256(binding_path.read_bytes()).hexdigest()
            message = (
                "task_id: {}\n"
                "task_context: {}\n"
                "authority_hash: {}\n"
                "delegated_agent: code_quality_reviewer\n"
                "execution_binding: {}\n"
                "binding_hash: {}\n"
            ).format(
                context["task_id"],
                context_path,
                authority,
                binding_path,
                binding_hash,
            )
            completed = subprocess.CompletedProcess([], 0, "{}", "")
            with patch.object(
                DELEGATION_HOOK.subprocess, "run", return_value=completed
            ) as run:
                result = DELEGATION_HOOK.decision(
                    {
                        "tool_input": {
                            "task_name": binding["task_name"],
                            "agent_type": "code_quality_reviewer",
                            "message": message,
                        }
                    },
                    codex_home=home,
                    run_validator=True,
                    write_proof=False,
                )
            commands = [call.args[0] for call in run.call_args_list]

        self.assertIsNone(result)
        gate_commands = [
            command for command in commands if "--requirement-gate" in command
        ]
        self.assertEqual(1, len(gate_commands))
        self.assertIn("--delegated-execution-binding", gate_commands[0])
        self.assertIn(str(binding_path), gate_commands[0])

    def test_schema_15_migration_preserves_scope_and_creates_stable_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context, context_path, _, _ = self.write_local_review_fixture(root)
            migrated = VALIDATOR.migrate_task_context_15_to_16(
                context, context_path
            )
            report = VALIDATOR.Report()
            VALIDATOR.validate_task_context(
                migrated, report, check_paths=False
            )
        self.assertFalse(report.errors, report.errors)
        self.assertEqual("1.6", migrated["schema_version"])
        self.assertEqual(context["scope"], migrated["scope"])
        self.assertNotIn("delegation_names", migrated["routing"])
        self.assertRegex(
            VALIDATOR.task_authority_hash(migrated), r"^[0-9a-f]{64}$"
        )

    def test_local_review_manifest_accepts_two_round_standalone_convergence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context, context_path, manifest, _ = self.write_local_review_fixture(root)
            report = VALIDATOR.Report()
            with patch.object(
                VALIDATOR, "CODEX", self.local_review_runtime["codex"]
            ), patch.object(
                VALIDATOR, "SYSTEM_DIR", self.local_review_runtime["system_dir"]
            ), patch.object(
                VALIDATOR, "ROOT_AGENT_HOOK", self.local_review_runtime["hook"]
            ):
                VALIDATOR.validate_local_review_manifest(
                    manifest, context, context_path, report
                )

        self.assertFalse(report.errors, report.errors)

    def test_local_review_manifest_aggregates_mixed_reviewer_outcomes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context, context_path, manifest, _ = self.write_local_review_fixture(
                root, mixed_first_round=True
            )
            report = VALIDATOR.Report()
            with patch.object(
                VALIDATOR, "CODEX", self.local_review_runtime["codex"]
            ), patch.object(
                VALIDATOR, "SYSTEM_DIR", self.local_review_runtime["system_dir"]
            ), patch.object(
                VALIDATOR, "ROOT_AGENT_HOOK", self.local_review_runtime["hook"]
            ):
                VALIDATOR.validate_local_review_manifest(
                    manifest, context, context_path, report
                )

        self.assertFalse(report.errors, report.errors)

    def test_local_review_manifest_rejects_forged_round_aggregation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context, context_path, manifest, _ = self.write_local_review_fixture(
                root, mixed_first_round=True
            )
            manifest["rounds"][0]["verdict"] = "passed"
            manifest["rounds"][0]["blocking_findings"] = 2
            report = VALIDATOR.Report()
            with patch.object(
                VALIDATOR, "CODEX", self.local_review_runtime["codex"]
            ), patch.object(
                VALIDATOR, "SYSTEM_DIR", self.local_review_runtime["system_dir"]
            ), patch.object(
                VALIDATOR, "ROOT_AGENT_HOOK", self.local_review_runtime["hook"]
            ):
                VALIDATOR.validate_local_review_manifest(
                    manifest, context, context_path, report
                )

        self.assertTrue(
            any(
                "does not aggregate reviewer evidence" in error
                for error in report.errors
            ),
            report.errors,
        )
        self.assertTrue(
            any(
                "must equal the sum of reviewer findings" in error
                for error in report.errors
            ),
            report.errors,
        )

    def test_local_review_manifest_rejects_mode_drift_stale_evidence_and_one_round(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context, context_path, manifest, evidence = self.write_local_review_fixture(root)
            manifest["mode"] = "playbook_managed"
            manifest["rounds"] = manifest["rounds"][-1:]
            evidence[-1]["code_quality_reviewer"]["sha256"] = "0" * 64
            report = VALIDATOR.Report()
            with patch.object(VALIDATOR, "validate_run_record", return_value=None):
                VALIDATOR.validate_local_review_manifest(
                    manifest, context, context_path, report
                )

        self.assertTrue(any("does not match playbook.managed" in error for error in report.errors))
        self.assertTrue(any("at least two review rounds" in error for error in report.errors))

    def test_local_review_manifest_rejects_reused_authenticated_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context, context_path, manifest, _ = self.write_local_review_fixture(root)
            first_entry = manifest["rounds"][0]["evidence"][0]
            second_entry = manifest["rounds"][1]["evidence"][0]
            first_report = json.loads(
                Path(first_entry["path"]).read_text(encoding="utf-8")
            )
            second_report_path = Path(second_entry["path"])
            second_report = json.loads(
                second_report_path.read_text(encoding="utf-8")
            )
            second_report["run_record"] = first_report["run_record"]
            second_report_path.write_text(
                json.dumps(second_report), encoding="utf-8"
            )
            second_entry["sha256"] = hashlib.sha256(
                second_report_path.read_bytes()
            ).hexdigest()
            report = VALIDATOR.Report()
            with patch.object(VALIDATOR, "validate_run_record", return_value=None):
                VALIDATOR.validate_local_review_manifest(
                    manifest, context, context_path, report
                )

        self.assertTrue(any(
            "run record cannot be reused" in error
            or "run record content cannot be reused" in error
            for error in report.errors
        ), report.errors)

    def test_local_review_manifest_rejects_reused_runtime_attestation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context, context_path, manifest, _ = self.write_local_review_fixture(root)
            first_report = json.loads(
                Path(manifest["rounds"][0]["evidence"][0]["path"]).read_text(
                    encoding="utf-8"
                )
            )
            second_entry = manifest["rounds"][1]["evidence"][0]
            second_report_path = Path(second_entry["path"])
            second_report = json.loads(
                second_report_path.read_text(encoding="utf-8")
            )
            first_run = json.loads(
                Path(first_report["run_record"]["path"]).read_text(encoding="utf-8")
            )
            second_run_path = Path(second_report["run_record"]["path"])
            second_run = json.loads(second_run_path.read_text(encoding="utf-8"))
            second_run["runtime_evidence"] = first_run["runtime_evidence"]
            second_run_path.write_text(json.dumps(second_run), encoding="utf-8")
            second_report["run_record"]["sha256"] = hashlib.sha256(
                second_run_path.read_bytes()
            ).hexdigest()
            second_report_path.write_text(
                json.dumps(second_report), encoding="utf-8"
            )
            second_entry["sha256"] = hashlib.sha256(
                second_report_path.read_bytes()
            ).hexdigest()
            report = VALIDATOR.Report()
            with patch.object(VALIDATOR, "validate_run_record", return_value=None):
                VALIDATOR.validate_local_review_manifest(
                    manifest, context, context_path, report
                )

        self.assertTrue(any(
            "runtime_evidence.agent_id cannot be reused" in error
            or "runtime_evidence.transcript_hash cannot be reused" in error
            or "runtime_evidence.delegation_proof_hash cannot be reused" in error
            for error in report.errors
        ), report.errors)

    def test_task_closure_allows_distinct_multi_round_reviewer_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context_path = root / "task-context.json"
            context_path.write_text("{}\n", encoding="utf-8")
            context = {
                "task_id": "multi-round-closeout",
                "task_type": "implementation",
                "risk_level": "high",
                "routing": {
                    "root_agent": "xiaoh",
                    "delegated_agents": [
                        "java_implementer",
                        "code_quality_reviewer",
                        "test_integration_verifier",
                    ],
                    "independent_review_agents": [
                        "code_quality_reviewer",
                        "test_integration_verifier",
                    ],
                },
                "output_contract": {"required_fields": []},
            }
            (root / "manifest.json").write_text(
                json.dumps({"schema_version": "xiaoh-local-review/v1"}),
                encoding="utf-8",
            )
            agents = [
                "xiaoh",
                "java_implementer",
                "code_quality_reviewer",
                "code_quality_reviewer",
                "test_integration_verifier",
                "test_integration_verifier",
            ]
            for index, agent in enumerate(agents):
                record = {
                    "run_id": "run-{}".format(index),
                    "task_id": context["task_id"],
                    "context_pack": str(context_path),
                    "context_hash": "a" * 64,
                    "status": "completed",
                    "agent": agent,
                    "outputs": {},
                    "runtime_evidence": {
                        "delegation_proof_hash": "{:064x}".format(index + 1)
                    },
                }
                (root / "run-{}.json".format(index)).write_text(
                    json.dumps(record), encoding="utf-8"
                )
            report = VALIDATOR.Report()
            with patch.object(
                VALIDATOR,
                "load_context_chain",
                return_value=[(context_path.resolve(), "a" * 64, context)],
            ), patch.object(
                VALIDATOR, "validate_local_review_manifest", return_value=None
            ), patch.object(
                VALIDATOR, "validate_run_record", return_value=None
            ), patch.object(
                VALIDATOR, "closure_rejection_reasons", return_value=[]
            ):
                VALIDATOR.validate_task_closure(context_path, root, report)

        self.assertFalse(
            any("conflicting completed records" in error for error in report.errors),
            report.errors,
        )

    def test_local_review_manifest_rejects_unbound_artifact_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context, context_path, manifest, _ = self.write_local_review_fixture(root)
            Path(manifest["subject"]["artifact_path"]).write_bytes(b"changed")
            report = VALIDATOR.Report()
            with patch.object(VALIDATOR, "validate_run_record", return_value=None):
                VALIDATOR.validate_local_review_manifest(
                    manifest, context, context_path, report
                )

        self.assertTrue(any(
            "does not match artifact_path content" in error
            for error in report.errors
        ), report.errors)

    def test_local_review_manifest_rejects_incomplete_repository_set(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repositories = []
            heads = []
            for name in ("repo-a", "repo-b"):
                repository = root / name
                repository.mkdir()
                subprocess.run(["git", "init", "-q", str(repository)], check=True)
                subprocess.run(
                    ["git", "-C", str(repository), "config", "user.email", "test@example.com"],
                    check=True,
                )
                subprocess.run(
                    ["git", "-C", str(repository), "config", "user.name", "Test"],
                    check=True,
                )
                tracked = repository / "tracked.txt"
                tracked.write_text(name + "\n", encoding="utf-8")
                subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
                subprocess.run(
                    ["git", "-C", str(repository), "commit", "-qm", "initial"],
                    check=True,
                )
                repositories.append(str(repository))
                heads.append(
                    subprocess.run(
                        ["git", "-C", str(repository), "rev-parse", "HEAD"],
                        capture_output=True,
                        text=True,
                        check=True,
                    ).stdout.strip()
                )
            context, context_path, manifest, _ = self.write_local_review_fixture(root)
            context["scope"]["repositories"] = repositories
            context_path.write_text(json.dumps(context), encoding="utf-8")
            artifact_path = Path(manifest["subject"]["artifact_path"])
            artifact_path.write_text(
                json.dumps({
                    "schema_version": "xiaoh-repository-set/v1",
                    "repositories": [{
                        "path": repositories[0],
                        "commit": heads[0],
                    }],
                }),
                encoding="utf-8",
            )
            manifest["subject"]["value"] = hashlib.sha256(
                artifact_path.read_bytes()
            ).hexdigest()
            report = VALIDATOR.Report()
            with patch.object(VALIDATOR, "validate_run_record", return_value=None):
                VALIDATOR.validate_local_review_manifest(
                    manifest, context, context_path, report
                )
            artifact_path.write_text("[]", encoding="utf-8")
            manifest["subject"]["value"] = hashlib.sha256(
                artifact_path.read_bytes()
            ).hexdigest()
            non_object_report = VALIDATOR.Report()
            with patch.object(VALIDATOR, "validate_run_record", return_value=None):
                VALIDATOR.validate_local_review_manifest(
                    manifest, context, context_path, non_object_report
                )

        self.assertTrue(any(
            "must cover every scoped repository exactly once" in error
            for error in report.errors
        ), report.errors)
        self.assertTrue(any(
            "multi-repository artifact must be a JSON object" in error
            for error in non_object_report.errors
        ), non_object_report.errors)

    def test_local_review_manifest_rejects_changed_git_head(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repo"
            repository.mkdir()
            subprocess.run(["git", "init", "-q", str(repository)], check=True)
            subprocess.run(
                ["git", "-C", str(repository), "config", "user.email", "test@example.com"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repository), "config", "user.name", "Test"],
                check=True,
            )
            tracked = repository / "tracked.txt"
            tracked.write_text("one\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repository), "add", "tracked.txt"], check=True)
            subprocess.run(["git", "-C", str(repository), "commit", "-qm", "one"], check=True)
            context, context_path, manifest, _ = self.write_local_review_fixture(root)
            context["scope"]["repositories"] = [str(repository)]
            context_path.write_text(
                json.dumps(context, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            first_head = subprocess.run(
                ["git", "-C", str(repository), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            manifest["task_context"]["sha256"] = hashlib.sha256(
                context_path.read_bytes()
            ).hexdigest()
            manifest["subject"] = {
                "kind": "git_commit",
                "repository": str(repository),
                "artifact_path": None,
                "value": first_head,
            }
            for round_item in manifest["rounds"]:
                round_item["subject_value"] = first_head
                for entry in round_item["evidence"]:
                    evidence_path = Path(entry["path"])
                    evidence_report = json.loads(
                        evidence_path.read_text(encoding="utf-8")
                    )
                    evidence_report["subject_value"] = first_head
                    run_path = Path(evidence_report["run_record"]["path"])
                    run_record = json.loads(run_path.read_text(encoding="utf-8"))
                    run_record["outputs"]["local_review"]["subject_value"] = first_head
                    run_path.write_text(json.dumps(run_record), encoding="utf-8")
                    evidence_report["run_record"]["sha256"] = hashlib.sha256(
                        run_path.read_bytes()
                    ).hexdigest()
                    evidence_path.write_text(
                        json.dumps(evidence_report), encoding="utf-8"
                    )
                    entry["sha256"] = hashlib.sha256(
                        evidence_path.read_bytes()
                    ).hexdigest()
            tracked.write_text("two\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repository), "commit", "-qam", "two"], check=True)
            report = VALIDATOR.Report()
            with patch.object(VALIDATOR, "validate_run_record", return_value=None):
                VALIDATOR.validate_local_review_manifest(
                    manifest, context, context_path, report
                )

        self.assertTrue(any("Git HEAD changed" in error for error in report.errors), report.errors)

    def test_local_review_manifest_rejects_dirty_git_worktree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repo"
            repository.mkdir()
            subprocess.run(["git", "init", "-q", str(repository)], check=True)
            subprocess.run(
                ["git", "-C", str(repository), "config", "user.email", "test@example.com"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repository), "config", "user.name", "Test"],
                check=True,
            )
            tracked = repository / "tracked.txt"
            tracked.write_text("one\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repository), "add", "tracked.txt"], check=True)
            subprocess.run(["git", "-C", str(repository), "commit", "-qm", "one"], check=True)
            context, context_path, manifest, _ = self.write_local_review_fixture(root)
            context["scope"]["repositories"] = [str(repository)]
            context_path.write_text(
                json.dumps(context, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            head = subprocess.run(
                ["git", "-C", str(repository), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            manifest["task_context"]["sha256"] = hashlib.sha256(
                context_path.read_bytes()
            ).hexdigest()
            manifest["subject"] = {
                "kind": "git_commit",
                "repository": str(repository),
                "artifact_path": None,
                "value": head,
            }
            tracked.write_text("dirty\n", encoding="utf-8")
            report = VALIDATOR.Report()
            with patch.object(VALIDATOR, "validate_run_record", return_value=None):
                VALIDATOR.validate_local_review_manifest(
                    manifest, context, context_path, report
                )

        self.assertTrue(any(
            "requires a clean worktree" in error for error in report.errors
        ), report.errors)

    def test_implementation_closure_requires_one_local_review_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context, context_path, _, _ = self.write_local_review_fixture(root)
            report = VALIDATOR.Report()
            VALIDATOR.validate_task_closure(context_path, root, report)

        self.assertTrue(any(
            "exactly one current local review manifest" in error
            for error in report.errors
        ), report.errors)

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
            self.assertTrue(any("schema 1.6" in error for error in legacy_report.errors))

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

    def test_hook_cli_forces_utf8_for_unicode_context_paths(self):
        environment = {**os.environ, "PYTHONIOENCODING": "cp1252"}
        completed = subprocess.run(
            [sys.executable, str(DELEGATION_HOOK_SCRIPT), "--self-test"],
            text=True,
            encoding="utf-8",
            capture_output=True,
            env=environment,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("self-test passed", completed.stdout)

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
                "delegation_policies": {
                    "java_code_explorer": {
                        "agent_type": "java_code_explorer",
                        "action": "read_only_analysis",
                        "task_name_prefix": "recall_window_review",
                    }
                },
                "selection_reason": "verify the post-prepare recall window",
            })
            context_path = root / "task-context.json"
            context_path.write_text(json.dumps(context), encoding="utf-8")
            context_hash = VALIDATOR.task_authority_hash(context)
            message = (
                "task_id: recall-test\n"
                f"task_context: {context_path}\n"
                f"authority_hash: {context_hash}\n"
                "delegated_agent: java_code_explorer\n\n"
                "Read-only recall verification."
            )
            payload = {
                "binding": {
                    "review_round": 1,
                    "purpose": "recall_verification",
                    "subject_digest": "a" * 64,
                },
                "tool_input": {
                    "task_name": "recall_window_review__r1__a1b2c3d4",
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

    def write_new_playbook_snapshots(
        self,
        root,
        *,
        phase="implementation",
        closure="open",
        truth_terminal="unknown",
        member_worktree=None,
        filesystem_cleaned=False,
    ):
        worker_path, _, worktree = self.write_playbook_snapshots(root)
        effective_worktree = member_worktree or str(worktree.resolve())
        raw_path = root / "status.raw.json"
        status_path = root / "status.json"
        raw_path.write_text(
            json.dumps({
                "status": "ok",
                "task": {
                    "workspace_id": "pb-task-workspace",
                    "change_id": "change-1",
                    "status": phase,
                    "truth_phase": phase,
                    "truth_terminal": truth_terminal,
                    "filesystem": {"cleaned": filesystem_cleaned},
                    "code_view": {"cleaned": filesystem_cleaned},
                    "workspace_closure": {"status": closure, "truth_status": "valid"},
                    "members": [{
                        "repo": "member-a",
                        "workspace_id": "pb-task-workspace",
                        "change_id": "change-1",
                        "status": phase,
                        "phase": phase,
                        "truth_terminal": truth_terminal,
                        "worktree_path": effective_worktree,
                    }],
                },
                "workspace_closure": {"status": closure, "truth_status": "valid"},
                "workspace_state": {
                    "closure": {"status": closure, "truth_status": "valid"}
                },
            }),
            encoding="utf-8",
        )
        status_path.write_text(
            json.dumps({
                "status": "success",
                "workspace_id": "pb-task-workspace",
                "evidence": {"raw_json_path": str(raw_path.resolve())},
            }),
            encoding="utf-8",
        )
        return worker_path, status_path, raw_path, worktree

    def write_public_playbook_snapshots(self, root, *, mr_status=None):
        root.mkdir(parents=True, exist_ok=True)
        worktree = root / "member-worktree"
        worktree.mkdir()
        subprocess.run(
            ["git", "init", "-q", "-b", "feature/test", str(worktree)],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(worktree), "config", "user.name", "XiaoH Test"],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(worktree),
                "config",
                "user.email",
                "xiaoh-test@example.invalid",
            ],
            check=True,
        )
        (worktree / "tracked.txt").write_text("test\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(worktree), "add", "tracked.txt"], check=True
        )
        subprocess.run(
            ["git", "-C", str(worktree), "commit", "-qm", "fixture"], check=True
        )
        head = subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", "--short=12", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        worker_path = root / "worker.json"
        worker_path.write_text(
            json.dumps({
                "status": "ok",
                "data": {
                    "workspace_root": str(root),
                    "child_worker_context": {
                        "workspace_id": "pb-task-workspace",
                        "change_id": "change-1",
                        "member": "member-a",
                        "member_worktree": str(worktree),
                        "allowed_scope": [str(worktree)],
                        "execution_mode": "main_agent_direct",
                        "recommended_executor": "main_agent",
                    },
                },
            }),
            encoding="utf-8",
        )
        truth_path = (
            root
            / ".playbook-workspace"
            / "truth"
            / "tasks"
            / "pb-task-workspace"
            / "task-truth.yaml"
        )
        truth_path.parent.mkdir(parents=True)
        truth_path.write_text(
            "schema_version: playbook-task-truth/v1\n", encoding="utf-8"
        )
        member = {
            "repo": "member-a",
            "branch": "feature/test",
            "head": head,
            "base_sync": {"branch": "develop", "status": "up_to_date"},
            "sdd": {
                "provider": "openspec",
                "state": "confirmed",
                "tasks": "incomplete",
            },
        }
        if mr_status is not None:
            member["mr"] = {
                "status": mr_status,
                "merge_status": "mergeable",
                "head": head,
            }
        status_path = root / "status.json"
        status_path.write_text(
            json.dumps({
                "workspace_id": "pb-task-workspace",
                "change_id": "change-1",
                "members": [member],
                "blockers": [],
                "next_actions": [
                    {"action": "run_implementation_gate", "member": "member-a"}
                ],
                "refreshed_at": datetime.now(
                    timezone(timedelta(hours=8))
                ).isoformat(timespec="milliseconds"),
                "task_truth_path": str(truth_path),
            }),
            encoding="utf-8",
        )
        return worker_path, status_path, truth_path, worktree

    def write_status_review_fixture(self, root):
        _, status, raw, worktree = self.write_new_playbook_snapshots(
            root, phase="specification", truth_terminal="active"
        )
        docs = worktree / "docs"
        docs.mkdir()
        artifact = docs / "spec-rfc.md"
        artifact.write_text("# Spec+RFC\n", encoding="utf-8")
        context_path = root / "task-context.json"
        context = {
            "schema_version": "1.5",
            "task_id": "pb-task-workspace",
            "intent": {"domain": "business_project"},
            "scope": {"allowed_paths": [str(docs.resolve())]},
            "routing": {
                "root_agent": "xiaoh",
                "delegated_agents": ["java_architect"],
                "delegated_actions": {"java_architect": "spec_rfc_review"},
            },
            "playbook": {
                "managed": True,
                "binding_kind": "status_review",
                "workspace_id": "pb-task-workspace",
                "xiaoh_workspace_id": "stable-xiaoh-workspace",
                "task_workspace_id": "pb-task-workspace",
                "change_id": "change-1",
                "member": "member-a",
                "member_worktree": str(worktree.resolve()),
                "workspace_root": str(root.resolve()),
                "allowed_scope": [str(docs.resolve())],
                "review_artifacts": [str(artifact.resolve())],
                "worker_contract_source": None,
                "adapter_receipt": None,
                "adapter_receipt_sha256": None,
            },
        }
        context_path.write_text(
            json.dumps(context, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return context, context_path, status, raw, worktree, artifact

    def test_status_review_binding_uses_status_and_artifacts_without_worker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context, context_path, status, _, _, artifact = (
                self.write_status_review_fixture(root)
            )
            output = root / "review-binding.json"
            captured = PLAYBOOK_ADAPTER.create_review_receipt(
                context_path,
                status,
                [str(artifact)],
                output,
                "spec_rfc_review",
                playbook_command=sys.executable,
            )
            context["playbook"]["adapter_receipt"] = str(output.resolve())
            context["playbook"]["adapter_receipt_sha256"] = captured[
                "receipt_sha256"
            ]
            context_path.write_text(
                json.dumps(context, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            verified = PLAYBOOK_ADAPTER.validate_receipt(
                output,
                expected_sha256=captured["receipt_sha256"],
                expected_action="spec_rfc_review",
            )

        self.assertEqual("status_review", verified["binding_kind"])
        self.assertEqual(
            "task_truth_v1", verified["playbook"]["status_contract"]
        )
        self.assertEqual(
            str(artifact.resolve()), verified["playbook"]["artifacts"][0]["path"]
        )
        self.assertNotIn("worker_contract_source", verified["playbook"])

    def test_status_review_binding_rejects_write_actions_and_changed_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context, context_path, status, _, _, artifact = (
                self.write_status_review_fixture(root)
            )
            with self.assertRaisesRegex(
                PLAYBOOK_ADAPTER.AdapterError, "不支持delegated action"
            ):
                PLAYBOOK_ADAPTER.create_review_receipt(
                    context_path,
                    status,
                    [str(artifact)],
                    root / "write-binding.json",
                    "implementation",
                    playbook_command=sys.executable,
                )

            output = root / "review-binding.json"
            captured = PLAYBOOK_ADAPTER.create_review_receipt(
                context_path,
                status,
                [str(artifact)],
                output,
                "spec_rfc_review",
                playbook_command=sys.executable,
            )
            context["playbook"]["adapter_receipt"] = str(output.resolve())
            context["playbook"]["adapter_receipt_sha256"] = captured[
                "receipt_sha256"
            ]
            context_path.write_text(json.dumps(context), encoding="utf-8")
            PLAYBOOK_ADAPTER.validate_receipt(output)
            artifact.write_text("# changed\n", encoding="utf-8")
            with self.assertRaisesRegex(
                PLAYBOOK_ADAPTER.AdapterError, "artifact已变化"
            ):
                PLAYBOOK_ADAPTER.validate_receipt(output)

            artifact.write_text("# Spec+RFC\n", encoding="utf-8")
            receipt = json.loads(output.read_text(encoding="utf-8"))
            receipt["playbook"]["artifacts"][0]["sha256"] = (
                PLAYBOOK_ADAPTER.file_hash(artifact)
            )
            receipt["playbook"]["artifacts"][0]["mtime_ns"] = (
                artifact.stat().st_mtime_ns
            )
            receipt["playbook"]["artifact_manifest_sha256"] = (
                PLAYBOOK_ADAPTER.canonical_hash(receipt["playbook"]["artifacts"])
            )
            receipt.pop("binding_sha256")
            receipt["binding_sha256"] = PLAYBOOK_ADAPTER.canonical_hash(receipt)
            output.write_text(json.dumps(receipt), encoding="utf-8")
            context["playbook"]["member"] = "other-member"
            context_path.write_text(json.dumps(context), encoding="utf-8")
            with self.assertRaisesRegex(
                PLAYBOOK_ADAPTER.AdapterError, "task context绑定已变化"
            ):
                PLAYBOOK_ADAPTER.validate_receipt(output)

    def test_status_review_binding_rejects_artifact_symlink_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context, context_path, status, _, worktree, _ = (
                self.write_status_review_fixture(root)
            )
            outside = root / "outside.md"
            outside.write_text("outside\n", encoding="utf-8")
            escaped = worktree / "docs/escaped.md"
            escaped.symlink_to(outside)
            context["playbook"]["review_artifacts"] = [str(escaped)]
            context_path.write_text(json.dumps(context), encoding="utf-8")

            with self.assertRaisesRegex(
                PLAYBOOK_ADAPTER.AdapterError, "不在授权范围"
            ):
                PLAYBOOK_ADAPTER.create_review_receipt(
                    context_path,
                    status,
                    [str(escaped)],
                    root / "escaped-binding.json",
                    "spec_rfc_review",
                    playbook_command=sys.executable,
                )

    def test_status_review_binding_requires_complete_declared_artifact_set(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context, context_path, status, _, _, artifact = (
                self.write_status_review_fixture(root)
            )
            second = artifact.parent / "design.md"
            second.write_text("# Design\n", encoding="utf-8")
            context["playbook"]["review_artifacts"].append(str(second.resolve()))
            context_path.write_text(json.dumps(context), encoding="utf-8")

            with self.assertRaisesRegex(
                PLAYBOOK_ADAPTER.AdapterError, "artifact集合必须.*完全一致"
            ):
                PLAYBOOK_ADAPTER.create_review_receipt(
                    context_path,
                    status,
                    [str(artifact)],
                    root / "incomplete-binding.json",
                    "spec_rfc_review",
                    playbook_command=sys.executable,
                )

    def test_status_review_binding_rejects_live_phase_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context, context_path, status, raw, _, artifact = (
                self.write_status_review_fixture(root)
            )
            output = root / "review-binding.json"
            captured = PLAYBOOK_ADAPTER.create_review_receipt(
                context_path,
                status,
                [str(artifact)],
                output,
                "spec_rfc_review",
                playbook_command=sys.executable,
            )
            context["playbook"]["adapter_receipt"] = str(output.resolve())
            context["playbook"]["adapter_receipt_sha256"] = captured[
                "receipt_sha256"
            ]
            context_path.write_text(json.dumps(context), encoding="utf-8")
            live = json.loads(raw.read_text(encoding="utf-8"))
            live["task"]["status"] = "implementation"
            live["task"]["truth_phase"] = "implementation"
            live["task"]["members"][0]["status"] = "implementation"
            live["task"]["members"][0]["phase"] = "implementation"

            with patch.object(
                PLAYBOOK_ADAPTER,
                "current_status_snapshot",
                return_value=(live, 1, 2),
            ):
                with self.assertRaisesRegex(
                    PLAYBOOK_ADAPTER.AdapterError, "实时任务状态语义已变化"
                ):
                    PLAYBOOK_ADAPTER.validate_receipt(
                        output, check_live_status=True
                    )

    def test_status_review_rejects_legacy_while_worker_binding_accepts_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, context_path, status, _, worktree, artifact = (
                self.write_status_review_fixture(root)
            )
            status.write_text(
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
            with self.assertRaisesRegex(
                PLAYBOOK_ADAPTER.AdapterError, "可验证的当前状态契约"
            ):
                PLAYBOOK_ADAPTER.create_review_receipt(
                    context_path,
                    status,
                    [str(artifact)],
                    root / "legacy-review-binding.json",
                    "spec_rfc_review",
                    playbook_command=sys.executable,
                )

            worker_root = root / "worker-case"
            worker_root.mkdir()
            worker, worker_status, _ = self.write_playbook_snapshots(worker_root)
            captured = PLAYBOOK_ADAPTER.create_receipt(
                worker,
                worker_status,
                root / "legacy-worker-binding.json",
                "implementation",
                "stable-xiaoh-workspace",
                playbook_command=sys.executable,
            )
            self.assertEqual(
                "legacy_current_state",
                captured["receipt"]["playbook"]["status_contract"],
            )

    def test_validator_accepts_status_review_and_rejects_worker_action(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context, context_path, status, _, _, artifact = (
                self.write_status_review_fixture(root)
            )
            output = root / "review-binding.json"
            captured = PLAYBOOK_ADAPTER.create_review_receipt(
                context_path,
                status,
                [str(artifact)],
                output,
                "spec_rfc_review",
                playbook_command=sys.executable,
            )
            context["playbook"]["adapter_receipt"] = str(output.resolve())
            context["playbook"]["adapter_receipt_sha256"] = captured[
                "receipt_sha256"
            ]
            context_path.write_text(json.dumps(context), encoding="utf-8")
            report = VALIDATOR.Report()
            with patch.object(
                VALIDATOR,
                "playbook_probe",
                return_value={
                    "status": "available",
                    "errors": [],
                    "checks": {"task_status": {"supported": True}},
                },
            ):
                receipt = VALIDATOR.validate_playbook_binding(
                    context,
                    report,
                    check_paths=True,
                    require_binding=True,
                    check_live_status=False,
                )

            self.assertFalse(report.errors, report.errors)
            self.assertEqual("status_review", receipt["binding_kind"])

            context["routing"]["delegated_actions"] = {
                "java_architect": "implementation"
            }
            report = VALIDATOR.Report()
            with patch.object(
                VALIDATOR,
                "playbook_probe",
                return_value={
                    "status": "available",
                    "errors": [],
                    "checks": {"task_status": {"supported": True}},
                },
            ):
                VALIDATOR.validate_playbook_binding(
                    context,
                    report,
                    check_paths=True,
                    require_binding=True,
                    check_live_status=False,
                )
            self.assertTrue(
                any(
                    "delegated_action与委派动作不一致" in error
                    or "read-only review actions only" in error
                    for error in report.errors
                ),
                report.errors,
            )

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

    def test_v16_managed_execution_binding_refreshes_receipt_without_changing_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker, status, worktree = self.write_playbook_snapshots(root)
            receipts = []
            for index in (1, 2):
                output = root / "binding-{}.json".format(index)
                receipts.append((
                    output,
                    PLAYBOOK_ADAPTER.create_receipt(
                        worker,
                        status,
                        output,
                        "implementation",
                        "stable-xiaoh-workspace",
                        playbook_command=sys.executable,
                    ),
                ))
            hook = root / "block_reserved_root_agent.py"
            hook.write_text("# binding hook\n", encoding="utf-8")
            context = {
                "schema_version": "1.6",
                "task_id": "managed-v16",
                "routing": {
                    "delegated_agents": ["java_implementer"],
                    "delegation_policies": {
                        "java_implementer": {
                            "agent_type": "java_implementer",
                            "action": "implementation",
                            "task_name_prefix": "managed_impl",
                        }
                    },
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
                },
            }
            context_path = root / "managed-context.json"
            context_path.write_text(json.dumps(context), encoding="utf-8")
            authority = VALIDATOR.task_authority_hash(context)
            for index, (receipt_path, captured) in enumerate(receipts, 1):
                now = datetime.now(timezone.utc)
                nonce = "{:064x}".format(index)
                binding = {
                    "schema_version": "xiaoh-delegation-binding/v1",
                    "prepared_at": now.isoformat(),
                    "expires_at": (now + timedelta(minutes=10)).isoformat(),
                    "session_id": "root-session",
                    "task_id": "managed-v16",
                    "task_context": str(context_path.resolve()),
                    "authority_hash": authority,
                    "delegated_agent": "java_implementer",
                    "agent_type": "java_implementer",
                    "task_name": "managed_impl__r{}__{}".format(
                        index, nonce[:16]
                    ),
                    "action": "implementation",
                    "review_round": index,
                    "purpose": "implementation",
                    "subject_digest": "a" * 64,
                    "playbook_adapter_receipt": str(receipt_path.resolve()),
                    "playbook_adapter_receipt_sha256": captured["receipt_sha256"],
                    "nonce": nonce,
                    "hook_path": str(hook.resolve()),
                    "hook_hash": hashlib.sha256(hook.read_bytes()).hexdigest(),
                }
                report = VALIDATOR.Report()
                VALIDATOR.validate_execution_binding(
                    binding,
                    context,
                    context_path,
                    report,
                    check_live_status=False,
                )
                self.assertFalse(report.errors, report.errors)
                self.assertEqual(authority, binding["authority_hash"])

    def test_historical_playbook_receipt_survives_source_progression(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker, status, _ = self.write_playbook_snapshots(root)
            receipt_path = root / "historical-receipt.json"
            captured = PLAYBOOK_ADAPTER.create_receipt(
                worker,
                status,
                receipt_path,
                "implementation",
                "stable-xiaoh-workspace",
                playbook_command=sys.executable,
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            context = {
                "schema_version": "1.6",
                "intent": {"domain": "business_project"},
                "playbook": {"managed": True},
            }
            proof = {
                "started_at": receipt["captured_at"],
                "effective_brief": {
                    "action": "implementation",
                    "playbook_adapter_receipt": str(receipt_path),
                    "playbook_adapter_receipt_sha256": captured["receipt_sha256"],
                },
            }
            worker.write_text(
                worker.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )
            status.write_text(
                status.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )
            report = VALIDATOR.Report()
            VALIDATOR.validate_playbook_receipt_at_agent_start(
                context, proof, report
            )
        self.assertFalse(report.errors, report.errors)

    def test_playbook_adapter_legacy_blocked_state_remains_nonterminal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker, status, _ = self.write_playbook_snapshots(root)
            payload = json.loads(status.read_text(encoding="utf-8"))
            payload["data"]["task_next"]["current_state"] = "blocked"
            status.write_text(json.dumps(payload), encoding="utf-8")

            result = PLAYBOOK_ADAPTER.validate_status_snapshot(
                status, PLAYBOOK_ADAPTER.worker_facts(worker)
            )

        self.assertEqual("legacy_current_state", result["contract"])

    def test_playbook_adapter_accepts_new_active_task_truth_contract(self):
        for phase in ("specification", "implementation"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                worker, status, raw, worktree = self.write_new_playbook_snapshots(
                    root, phase=phase
                )
                output = root / "binding.json"

                captured = PLAYBOOK_ADAPTER.create_receipt(
                    worker,
                    status,
                    output,
                    "implementation",
                    "stable-xiaoh-workspace",
                    playbook_command=sys.executable,
                )
                receipt = PLAYBOOK_ADAPTER.validate_receipt(output)

                self.assertEqual(
                    "task_truth_v1", receipt["playbook"]["status_contract"]
                )
                self.assertEqual(
                    str(raw.resolve()),
                    receipt["playbook"]["status_contract_source"],
                )
                self.assertEqual(
                    str(worktree.resolve()), receipt["playbook"]["member_worktree"]
                )
                self.assertEqual("captured", captured["status"])

    def test_playbook_adapter_accepts_dedicated_public_status_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker, status, truth, worktree = self.write_public_playbook_snapshots(
                root
            )
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
            receipt = PLAYBOOK_ADAPTER.validate_receipt(
                output, check_live_status=False
            )
            live = json.loads(status.read_text(encoding="utf-8"))
            live["refreshed_at"] = datetime.now(
                timezone(timedelta(hours=8))
            ).isoformat(timespec="milliseconds")
            with patch.object(
                PLAYBOOK_ADAPTER,
                "current_status_snapshot",
                return_value=(live, 1, 2),
            ):
                PLAYBOOK_ADAPTER.validate_receipt(
                    output, check_live_status=True
                )

        self.assertEqual("captured", captured["status"])
        self.assertEqual(
            "task_status_public_v1", receipt["playbook"]["status_contract"]
        )
        self.assertNotIn("status_contract_source", receipt["playbook"])
        self.assertEqual(
            str(worktree.resolve()), receipt["playbook"]["member_worktree"]
        )

    def test_status_review_accepts_dedicated_public_status_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, status, _, worktree = self.write_public_playbook_snapshots(root)
            docs = worktree / "docs"
            docs.mkdir()
            artifact = docs / "spec-rfc.md"
            artifact.write_text("# Spec+RFC\n", encoding="utf-8")
            context_path = root / "task-context.json"
            context_path.write_text(
                json.dumps({
                    "schema_version": "1.5",
                    "task_id": "pb-task-workspace",
                    "intent": {"domain": "business_project"},
                    "scope": {"allowed_paths": [str(docs.resolve())]},
                    "routing": {
                        "root_agent": "xiaoh",
                        "delegated_agents": ["java_architect"],
                        "delegated_actions": {
                            "java_architect": "spec_rfc_review"
                        },
                    },
                    "playbook": {
                        "managed": True,
                        "binding_kind": "status_review",
                        "workspace_id": "pb-task-workspace",
                        "xiaoh_workspace_id": "stable-xiaoh-workspace",
                        "task_workspace_id": "pb-task-workspace",
                        "change_id": "change-1",
                        "member": "member-a",
                        "member_worktree": str(worktree.resolve()),
                        "workspace_root": str(root.resolve()),
                        "allowed_scope": [str(docs.resolve())],
                        "review_artifacts": [str(artifact.resolve())],
                        "worker_contract_source": None,
                        "adapter_receipt": None,
                        "adapter_receipt_sha256": None,
                    },
                }),
                encoding="utf-8",
            )
            output = root / "review-binding.json"
            captured = PLAYBOOK_ADAPTER.create_review_receipt(
                context_path,
                status,
                [str(artifact)],
                output,
                "spec_rfc_review",
                playbook_command=sys.executable,
            )
            receipt = PLAYBOOK_ADAPTER.validate_receipt(
                output, check_live_status=False
            )
            live = json.loads(status.read_text(encoding="utf-8"))
            live["refreshed_at"] = datetime.now(
                timezone(timedelta(hours=8))
            ).isoformat(timespec="milliseconds")
            with patch.object(
                PLAYBOOK_ADAPTER,
                "current_status_snapshot",
                return_value=(live, 1, 2),
            ):
                PLAYBOOK_ADAPTER.validate_receipt(
                    output, check_live_status=True
                )

        self.assertEqual("captured", captured["status"])
        self.assertEqual("status_review", receipt["binding_kind"])
        self.assertEqual(
            "task_status_public_v1", receipt["playbook"]["status_contract"]
        )

    def test_playbook_adapter_public_status_rejects_terminal_and_git_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker, status, _, _ = self.write_public_playbook_snapshots(
                root, mr_status="merged"
            )
            with self.assertRaisesRegex(
                PLAYBOOK_ADAPTER.AdapterError, "明确非终态"
            ):
                PLAYBOOK_ADAPTER.validate_status_snapshot(
                    status, PLAYBOOK_ADAPTER.worker_facts(worker)
                )

            payload = json.loads(status.read_text(encoding="utf-8"))
            payload["members"][0].pop("mr")
            payload["members"][0]["head"] = "0" * 12
            status.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                PLAYBOOK_ADAPTER.AdapterError, "Git身份不一致"
            ):
                PLAYBOOK_ADAPTER.validate_status_snapshot(
                    status, PLAYBOOK_ADAPTER.worker_facts(worker)
                )

    def test_playbook_adapter_public_status_rejects_malformed_nested_shape(self):
        cases = {
            "missing base_sync": lambda value: value["members"][0].pop(
                "base_sync"
            ),
            "unknown blocker": lambda value: value["blockers"].append(
                {"code": "not-a-playbook-blocker"}
            ),
            "unknown action": lambda value: value.__setitem__(
                "next_actions", [{"action": "not-a-playbook-action"}]
            ),
            "empty refreshed_at": lambda value: value.__setitem__(
                "refreshed_at", ""
            ),
            "non-object member": lambda value: value["members"].append(
                "not-a-member"
            ),
        }
        for label, mutate in cases.items():
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                worker, status, _, _ = self.write_public_playbook_snapshots(root)
                payload = json.loads(status.read_text(encoding="utf-8"))
                mutate(payload)
                status.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(PLAYBOOK_ADAPTER.AdapterError):
                    PLAYBOOK_ADAPTER.validate_status_snapshot(
                        status, PLAYBOOK_ADAPTER.worker_facts(worker)
                    )

    def test_playbook_adapter_public_status_rejects_truth_escape_and_cleaned(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker, status, _, _ = self.write_public_playbook_snapshots(root)
            payload = json.loads(status.read_text(encoding="utf-8"))
            outside = root.parent / f"{root.name}-outside-truth.yaml"
            outside.write_text("truth\n", encoding="utf-8")
            try:
                payload["task_truth_path"] = str(outside)
                status.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(
                    PLAYBOOK_ADAPTER.AdapterError, "超出workspace_root"
                ):
                    PLAYBOOK_ADAPTER.validate_status_snapshot(
                        status, PLAYBOOK_ADAPTER.worker_facts(worker)
                    )
            finally:
                outside.unlink(missing_ok=True)

            _, status, _, _ = self.write_public_playbook_snapshots(
                root / "cleaned"
            )
            cleaned_worker = status.parent / "worker.json"
            payload = json.loads(status.read_text(encoding="utf-8"))
            payload["next_actions"] = []
            status.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                PLAYBOOK_ADAPTER.AdapterError, "已清理"
            ):
                PLAYBOOK_ADAPTER.validate_status_snapshot(
                    status, PLAYBOOK_ADAPTER.worker_facts(cleaned_worker)
                )

    def test_playbook_adapter_public_status_rejects_uncertain_and_stale_facts(self):
        cases = {
            "unknown mr": lambda value, _root: value["members"][0].update({
                "mr": {
                    "status": "unknown",
                    "merge_status": "unknown",
                    "head": None,
                }
            }),
            "unknown remote": lambda value, _root: value.__setitem__(
                "blockers",
                [{"code": "remote_state_unknown", "member": "member-a"}],
            ),
            "stale refreshed_at": lambda value, _root: value.__setitem__(
                "refreshed_at", "2026-01-01T00:00:00.000+08:00"
            ),
            "noncanonical truth": lambda value, root: value.__setitem__(
                "task_truth_path", str(root / "other-task-truth.yaml")
            ),
        }
        for label, mutate in cases.items():
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                worker, status, _, _ = self.write_public_playbook_snapshots(root)
                payload = json.loads(status.read_text(encoding="utf-8"))
                if label == "noncanonical truth":
                    (root / "other-task-truth.yaml").write_text(
                        "truth\n", encoding="utf-8"
                    )
                mutate(payload, root)
                status.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(PLAYBOOK_ADAPTER.AdapterError):
                    PLAYBOOK_ADAPTER.validate_status_snapshot(
                        status, PLAYBOOK_ADAPTER.worker_facts(worker)
                    )

    def test_playbook_adapter_accepts_mixed_aggregate_for_active_member(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker, status, raw, _ = self.write_new_playbook_snapshots(root)
            payload = json.loads(raw.read_text(encoding="utf-8"))
            payload["task"]["status"] = "mixed"
            payload["task"]["truth_phase"] = "mixed"
            payload["task"]["truth_terminal"] = "mixed"
            payload["task"]["members"].append({
                "repo": "member-b",
                "workspace_id": "pb-task-workspace",
                "change_id": "change-1",
                "status": "specification",
                "phase": "specification",
                "truth_terminal": "active",
                "worktree_path": str(root / "other-worktree"),
            })
            raw.write_text(json.dumps(payload), encoding="utf-8")

            result = PLAYBOOK_ADAPTER.validate_status_snapshot(
                status, PLAYBOOK_ADAPTER.worker_facts(worker)
            )

        self.assertEqual("task_truth_v1", result["contract"])

    def test_playbook_adapter_accepts_code_view_as_explicit_uncleaned_fact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker, status, raw, _ = self.write_new_playbook_snapshots(root)
            payload = json.loads(raw.read_text(encoding="utf-8"))
            payload["task"].pop("filesystem")
            raw.write_text(json.dumps(payload), encoding="utf-8")

            result = PLAYBOOK_ADAPTER.validate_status_snapshot(
                status, PLAYBOOK_ADAPTER.worker_facts(worker)
            )

        self.assertEqual("task_truth_v1", result["contract"])

    def test_playbook_adapter_rejects_new_terminal_contracts(self):
        cases = (
            {"phase": "completed"},
            {"closure": "closed"},
            {"truth_terminal": "cleaned"},
            {"filesystem_cleaned": True},
            {"truth_terminal": "merged", "phase": "finalize_cleanup"},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                worker, status, _, _ = self.write_new_playbook_snapshots(
                    root, **overrides
                )

                with self.assertRaises(PLAYBOOK_ADAPTER.AdapterError):
                    PLAYBOOK_ADAPTER.validate_status_snapshot(
                        status, PLAYBOOK_ADAPTER.worker_facts(worker)
                    )

    def test_playbook_adapter_rejects_legacy_marker_mixed_with_new_terminal_facts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker, status, raw, _ = self.write_new_playbook_snapshots(
                root, phase="completed", truth_terminal="cleaned",
                filesystem_cleaned=True,
            )
            payload = json.loads(raw.read_text(encoding="utf-8"))
            payload["current_state"] = "started"
            raw.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(PLAYBOOK_ADAPTER.AdapterError):
                PLAYBOOK_ADAPTER.validate_status_snapshot(
                    status, PLAYBOOK_ADAPTER.worker_facts(worker)
                )

            worker, status, raw, _ = self.write_new_playbook_snapshots(root)
            payload = json.loads(raw.read_text(encoding="utf-8"))
            payload["current_state"] = "completed"
            raw.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(PLAYBOOK_ADAPTER.AdapterError, "新旧状态契约"):
                PLAYBOOK_ADAPTER.validate_status_snapshot(
                    status, PLAYBOOK_ADAPTER.worker_facts(worker)
                )

    def test_playbook_adapter_rejects_any_conflicting_canonical_terminal_fact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker, status, raw, _ = self.write_new_playbook_snapshots(root)
            payload = json.loads(raw.read_text(encoding="utf-8"))
            payload["task"]["canonical_terminal_state"] = {
                "status": "open",
                "terminal": False,
            }
            payload["canonical_terminal_state"] = {
                "status": "closed_loop",
                "terminal": True,
            }
            raw.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(
                PLAYBOOK_ADAPTER.AdapterError, "canonical terminal"
            ):
                PLAYBOOK_ADAPTER.validate_status_snapshot(
                    status, PLAYBOOK_ADAPTER.worker_facts(worker)
                )

            worker, status, raw, _ = self.write_new_playbook_snapshots(root)
            payload = json.loads(raw.read_text(encoding="utf-8"))
            payload["task"]["members"][0]["canonical_terminal_state"] = {
                "status": "merged",
                "terminal": True,
            }
            raw.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                PLAYBOOK_ADAPTER.AdapterError, "canonical terminal"
            ):
                PLAYBOOK_ADAPTER.validate_status_snapshot(
                    status, PLAYBOOK_ADAPTER.worker_facts(worker)
                )

    def test_playbook_adapter_rejects_invalid_closure_truth(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker, status, raw, _ = self.write_new_playbook_snapshots(root)
            payload = json.loads(raw.read_text(encoding="utf-8"))
            payload["task"]["workspace_closure"]["truth_status"] = "invalid"
            payload["workspace_closure"]["truth_status"] = "invalid"
            payload["workspace_state"]["closure"]["truth_status"] = "invalid"
            raw.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(PLAYBOOK_ADAPTER.AdapterError, "closure.status"):
                PLAYBOOK_ADAPTER.validate_status_snapshot(
                    status, PLAYBOOK_ADAPTER.worker_facts(worker)
                )

    def test_playbook_adapter_rejects_new_identity_and_worktree_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker, status, raw, worktree = self.write_new_playbook_snapshots(root)
            payload = json.loads(raw.read_text(encoding="utf-8"))
            payload["task"]["members"][0]["change_id"] = "other-change"
            raw.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(PLAYBOOK_ADAPTER.AdapterError, "change_id"):
                PLAYBOOK_ADAPTER.validate_status_snapshot(
                    status, PLAYBOOK_ADAPTER.worker_facts(worker)
                )

            worker, status, raw, _ = self.write_new_playbook_snapshots(
                root, member_worktree=str(root / "missing-worktree")
            )
            with self.assertRaisesRegex(PLAYBOOK_ADAPTER.AdapterError, "worktree"):
                PLAYBOOK_ADAPTER.validate_status_snapshot(
                    status, PLAYBOOK_ADAPTER.worker_facts(worker)
                )

            worker, status, raw, _ = self.write_new_playbook_snapshots(root)
            payload = json.loads(raw.read_text(encoding="utf-8"))
            payload["task"]["members"][0].pop("worktree_path")
            raw.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(PLAYBOOK_ADAPTER.AdapterError, "worktree"):
                PLAYBOOK_ADAPTER.validate_status_snapshot(
                    status, PLAYBOOK_ADAPTER.worker_facts(worker)
                )

            worker, status, raw, _ = self.write_new_playbook_snapshots(root)
            raw.unlink()
            with self.assertRaisesRegex(PLAYBOOK_ADAPTER.AdapterError, "不存在"):
                PLAYBOOK_ADAPTER.validate_status_snapshot(
                    status, PLAYBOOK_ADAPTER.worker_facts(worker)
                )

    def test_playbook_adapter_probe_requires_actual_status_contract_for_compatible(self):
        def completed(arguments, **_kwargs):
            output = {
                ("--version",): "playbook version 0.0.40-snapshot",
                ("workspace", "task", "status", "--help"): "--full",
                (
                    "workspace",
                    "task",
                    "worker",
                    "start",
                    "--help",
                ): "child_worker_context",
            }.get(tuple(arguments[1:]), "")
            return SimpleNamespace(returncode=0, stdout=output, stderr="")

        with tempfile.TemporaryDirectory() as temporary, patch.object(
            PLAYBOOK_ADAPTER.shutil, "which", return_value=sys.executable
        ), patch.object(PLAYBOOK_ADAPTER.subprocess, "run", side_effect=completed):
            root = Path(temporary)
            worker, status, raw, _ = self.write_new_playbook_snapshots(root)
            command_only = PLAYBOOK_ADAPTER.playbook_probe(sys.executable, "auto")
            actual = PLAYBOOK_ADAPTER.playbook_probe(
                sys.executable, "auto", worker, status
            )
            payload = json.loads(raw.read_text(encoding="utf-8"))
            payload["task"]["status"] = "closed"
            raw.write_text(json.dumps(payload), encoding="utf-8")
            terminal = PLAYBOOK_ADAPTER.playbook_probe(
                sys.executable, "auto", worker, status
            )
            worker, status, raw, _ = self.write_new_playbook_snapshots(root)
            old = (datetime.now(timezone.utc) - timedelta(days=1)).timestamp()
            for source in (worker, status, raw):
                os.utime(source, (old, old))
            stale = PLAYBOOK_ADAPTER.playbook_probe(
                sys.executable, "auto", worker, status
            )

        self.assertEqual("available", command_only["status"])
        self.assertEqual("unverified", command_only["status_contract"])
        self.assertEqual("compatible", actual["status"])
        self.assertTrue(actual["task_status_contract"])
        self.assertEqual("incompatible", terminal["status"])
        self.assertFalse(terminal["task_status_contract"])
        self.assertEqual("incompatible", stale["status"])
        self.assertIn("不是刚刚生成", stale["errors"][0])

    def test_playbook_status_review_probe_does_not_require_worker_start(self):
        def completed(arguments, **_kwargs):
            output = {
                ("--version",): "playbook version 0.0.40",
                ("workspace", "task", "status", "--help"): "--full",
                (
                    "workspace",
                    "task",
                    "worker",
                    "start",
                    "--help",
                ): "",
            }.get(tuple(arguments[1:]), "")
            return SimpleNamespace(
                returncode=0 if output else 1, stdout=output, stderr=""
            )

        with patch.object(
            PLAYBOOK_ADAPTER.shutil, "which", return_value=sys.executable
        ), patch.object(
            PLAYBOOK_ADAPTER.subprocess, "run", side_effect=completed
        ):
            review = PLAYBOOK_ADAPTER.playbook_probe(
                sys.executable, "auto", require_worker=False
            )
            worker = PLAYBOOK_ADAPTER.playbook_probe(
                sys.executable, "auto", require_worker=True
            )

        self.assertEqual("available", review["status"])
        self.assertFalse(review["worker_json_contract"])
        self.assertFalse(review["errors"])
        self.assertEqual("incompatible", worker["status"])

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

    def test_playbook_adapter_rejects_status_before_worker_and_raw_source_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker, status, raw, _ = self.write_new_playbook_snapshots(root)
            later = datetime.now(timezone.utc).timestamp() + 1
            os.utime(worker, (later, later))
            with self.assertRaisesRegex(PLAYBOOK_ADAPTER.AdapterError, "紧邻worker"):
                PLAYBOOK_ADAPTER.create_receipt(
                    worker,
                    status,
                    root / "out-of-order.json",
                    "implementation",
                    "stable-xiaoh-workspace",
                    playbook_command=sys.executable,
                )

            worker, status, raw, _ = self.write_new_playbook_snapshots(root)
            output = root / "binding.json"
            PLAYBOOK_ADAPTER.create_receipt(
                worker,
                status,
                output,
                "implementation",
                "stable-xiaoh-workspace",
                playbook_command=sys.executable,
            )
            raw.write_text('{"status":"ok","changed":true}', encoding="utf-8")
            with self.assertRaisesRegex(PLAYBOOK_ADAPTER.AdapterError, "来源已变化"):
                PLAYBOOK_ADAPTER.validate_receipt(output)

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

    def test_managed_main_agent_direct_requirement_gate_accepts_empty_delegation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker, status, worktree = self.write_playbook_snapshots(
                root,
                execution_mode="main_agent_direct",
                recommended_executor="main_agent",
            )
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
                "schema_version": "1.6",
                "intent": {"domain": "business_project"},
                "memory_recall": {},
                "scope": {"allowed_paths": [str(worktree.resolve())]},
                "routing": {
                    "root_agent": "xiaoh",
                    "delegated_agents": [],
                    "delegation_policies": {},
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
                },
                "requirements": VALIDATOR.example_requirements(),
            }
            report = VALIDATOR.Report()

            def offline_receipt(path, **kwargs):
                kwargs["check_live_status"] = False
                return PLAYBOOK_ADAPTER.validate_receipt(path, **kwargs)

            with patch.object(
                VALIDATOR, "validate_memory_recall"
            ), patch.object(
                VALIDATOR, "validate_receipt", side_effect=offline_receipt
            ), patch.object(
                VALIDATOR,
                "playbook_probe",
                return_value={"status": "compatible", "errors": []},
            ):
                VALIDATOR.validate_requirement_gate(
                    context,
                    "implementation",
                    report,
                    check_paths=True,
                    root_playbook_receipt=output,
                    root_playbook_receipt_sha256=captured["receipt_sha256"],
                    check_playbook_live_status=False,
                )

        self.assertFalse(report.errors)

    def test_managed_delegated_requirement_gate_accepts_execution_binding(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker, status, worktree = self.write_playbook_snapshots(root)
            receipt_path = root / "binding.json"
            captured = PLAYBOOK_ADAPTER.create_receipt(
                worker,
                status,
                receipt_path,
                "implementation",
                "stable-xiaoh-workspace",
                playbook_command=sys.executable,
            )
            hook = root / "hook.py"
            hook.write_text("# hook\n", encoding="utf-8")
            context = {
                "schema_version": "1.6",
                "task_id": "managed-delegated",
                "intent": {"domain": "business_project"},
                "memory_recall": {},
                "scope": {"allowed_paths": [str(worktree.resolve())]},
                "routing": {
                    "root_agent": "xiaoh",
                    "delegated_agents": ["java_implementer"],
                    "delegation_policies": {
                        "java_implementer": {
                            "agent_type": "java_implementer",
                            "action": "implementation",
                            "task_name_prefix": "managed_impl",
                        }
                    },
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
                },
                "requirements": VALIDATOR.example_requirements(),
            }
            context_path = root / "context.json"
            context_path.write_text(json.dumps(context), encoding="utf-8")
            now = datetime.now(timezone.utc)
            nonce = "1" * 64
            binding = {
                "schema_version": "xiaoh-delegation-binding/v1",
                "prepared_at": now.isoformat(),
                "expires_at": (now + timedelta(minutes=10)).isoformat(),
                "session_id": "root-session",
                "task_id": context["task_id"],
                "task_context": str(context_path),
                "authority_hash": VALIDATOR.task_authority_hash(context),
                "delegated_agent": "java_implementer",
                "agent_type": "java_implementer",
                "task_name": "managed_impl__r1__{}".format(nonce[:16]),
                "action": "implementation",
                "review_round": 1,
                "purpose": "implementation",
                "subject_digest": "a" * 64,
                "playbook_adapter_receipt": str(receipt_path),
                "playbook_adapter_receipt_sha256": captured["receipt_sha256"],
                "nonce": nonce,
                "hook_path": str(hook),
                "hook_hash": hashlib.sha256(hook.read_bytes()).hexdigest(),
            }
            report = VALIDATOR.Report()

            def offline_receipt(path, **kwargs):
                kwargs["check_live_status"] = False
                return PLAYBOOK_ADAPTER.validate_receipt(path, **kwargs)

            with patch.object(
                VALIDATOR, "validate_memory_recall"
            ), patch.object(
                VALIDATOR, "validate_receipt", side_effect=offline_receipt
            ):
                VALIDATOR.validate_requirement_gate(
                    context,
                    "implementation",
                    report,
                    delegated_execution_binding=binding,
                    delegated_execution_binding_context_path=context_path,
                    check_playbook_live_status=False,
                )

        self.assertFalse(report.errors, report.errors)

    def test_managed_delegated_binding_rejects_main_agent_direct_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker, status, worktree = self.write_playbook_snapshots(
                root,
                execution_mode="main_agent_direct",
                recommended_executor="main_agent",
            )
            receipt_path = root / "root-binding.json"
            captured = PLAYBOOK_ADAPTER.create_receipt(
                worker,
                status,
                receipt_path,
                "implementation",
                "stable-xiaoh-workspace",
                playbook_command=sys.executable,
            )
            hook = root / "hook.py"
            hook.write_text("# hook\n", encoding="utf-8")
            context = {
                "schema_version": "1.6",
                "task_id": "managed-delegated-root-receipt",
                "intent": {"domain": "business_project"},
                "memory_recall": {},
                "scope": {"allowed_paths": [str(worktree.resolve())]},
                "routing": {
                    "root_agent": "xiaoh",
                    "delegated_agents": ["java_implementer"],
                    "delegation_policies": {
                        "java_implementer": {
                            "agent_type": "java_implementer",
                            "action": "implementation",
                            "task_name_prefix": "managed_impl",
                        }
                    },
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
                },
                "requirements": VALIDATOR.example_requirements(),
            }
            context_path = root / "context.json"
            context_path.write_text(json.dumps(context), encoding="utf-8")
            now = datetime.now(timezone.utc)
            nonce = "2" * 64
            binding = {
                "schema_version": "xiaoh-delegation-binding/v1",
                "prepared_at": now.isoformat(),
                "expires_at": (now + timedelta(minutes=10)).isoformat(),
                "session_id": "root-session",
                "task_id": context["task_id"],
                "task_context": str(context_path),
                "authority_hash": VALIDATOR.task_authority_hash(context),
                "delegated_agent": "java_implementer",
                "agent_type": "java_implementer",
                "task_name": "managed_impl__r1__{}".format(nonce[:16]),
                "action": "implementation",
                "review_round": 1,
                "purpose": "implementation",
                "subject_digest": "a" * 64,
                "playbook_adapter_receipt": str(receipt_path),
                "playbook_adapter_receipt_sha256": captured["receipt_sha256"],
                "nonce": nonce,
                "hook_path": str(hook),
                "hook_hash": hashlib.sha256(hook.read_bytes()).hexdigest(),
            }

            def offline_receipt(path, **kwargs):
                kwargs["check_live_status"] = False
                return PLAYBOOK_ADAPTER.validate_receipt(path, **kwargs)

            root_report = VALIDATOR.Report()
            binding_report = VALIDATOR.Report()
            gate_report = VALIDATOR.Report()
            with patch.object(
                VALIDATOR, "validate_receipt", side_effect=offline_receipt
            ):
                VALIDATOR.validate_root_playbook_receipt(
                    context,
                    receipt_path,
                    captured["receipt_sha256"],
                    "implementation",
                    root_report,
                    check_live_status=False,
                )
                VALIDATOR.validate_execution_binding(
                    binding,
                    context,
                    context_path,
                    binding_report,
                    check_live_status=False,
                )
            with patch.object(
                VALIDATOR, "validate_memory_recall"
            ), patch.object(
                VALIDATOR, "validate_receipt", side_effect=offline_receipt
            ):
                VALIDATOR.validate_requirement_gate(
                    context,
                    "implementation",
                    gate_report,
                    delegated_execution_binding=binding,
                    delegated_execution_binding_context_path=context_path,
                    check_playbook_live_status=False,
                )

        self.assertFalse(root_report.errors, root_report.errors)
        for report in (binding_report, gate_report):
            self.assertTrue(
                any(
                    "professional execution binding cannot use a "
                    "main_agent_direct Playbook receipt" in error
                    for error in report.errors
                ),
                report.errors,
            )

    def test_schema_16_managed_scope_must_intersect_task_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, context, _ = self.write_v16_delegation_fixture(root)
            in_scope = root / "in-scope"
            outside = root / "outside"
            in_scope.mkdir()
            outside.mkdir()
            context["scope"]["allowed_paths"] = [str(in_scope)]
            context["playbook"] = {
                "managed": True,
                "workspace_id": "task-workspace",
                "xiaoh_workspace_id": "stable-workspace",
                "task_workspace_id": "task-workspace",
                "change_id": "change-1",
                "member": "member-a",
                "member_worktree": str(outside),
                "workspace_root": str(root),
                "allowed_scope": [str(outside)],
            }
            report = VALIDATOR.Report()
            VALIDATOR.validate_task_context(
                context, report, check_paths=False
            )

        self.assertTrue(
            any(
                "outside task scope.allowed_paths" in error
                for error in report.errors
            ),
            report.errors,
        )

    def test_managed_main_agent_direct_rejects_forged_root_and_wrong_action(self):
        for root_agent, receipt_action, expected_error in (
            ("not-xiaoh", "implementation", "requires the current XiaoH root agent"),
            ("xiaoh", "verification", "delegated_action与委派动作不一致"),
        ):
            with self.subTest(
                root_agent=root_agent, receipt_action=receipt_action
            ), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                worker, status, worktree = self.write_playbook_snapshots(
                    root,
                    execution_mode="main_agent_direct",
                    recommended_executor="main_agent",
                )
                output = root / "binding.json"
                captured = PLAYBOOK_ADAPTER.create_receipt(
                    worker,
                    status,
                    output,
                    receipt_action,
                    "stable-xiaoh-workspace",
                    playbook_command=sys.executable,
                )
                context = {
                    "intent": {"domain": "business_project"},
                    "scope": {"allowed_paths": [str(worktree.resolve())]},
                    "routing": {
                        "root_agent": root_agent,
                        "delegated_agents": [],
                        "delegated_actions": {},
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
                    VALIDATOR.validate_playbook_binding(
                        context,
                        report,
                        check_paths=True,
                        require_binding=True,
                        check_live_status=False,
                        expected_action="implementation",
                    )

                self.assertTrue(
                    any(expected_error in error for error in report.errors),
                    report.errors,
                )

    def test_managed_binding_offline_structure_check_remains_fail_closed(self):
        base = {
            "intent": {"domain": "business_project"},
            "scope": {"allowed_paths": ["/workspace/member-a"]},
            "playbook": {
                "managed": True,
                "workspace_id": "pb-task-workspace",
                "xiaoh_workspace_id": "stable-xiaoh-workspace",
                "task_workspace_id": "pb-task-workspace",
                "change_id": "change-1",
                "member": "member-a",
                "member_worktree": "/workspace/member-a",
                "workspace_root": "/workspace",
                "allowed_scope": ["/workspace/member-a"],
                "worker_contract_source": "/evidence/worker.json",
                "adapter_receipt": "/evidence/binding.json",
                "adapter_receipt_sha256": "a" * 64,
            },
        }
        cases = (
            (
                {
                    "root_agent": "xiaoh",
                    "delegated_agents": ["java_implementer"],
                    "delegated_actions": {},
                },
                "keys must equal delegated_agents",
            ),
            (
                {
                    "root_agent": "xiaoh",
                    "delegated_agents": [],
                    "delegated_actions": {},
                },
                "requires worker identity and receipt path validation",
            ),
        )
        for routing, expected_error in cases:
            with self.subTest(expected_error=expected_error):
                context = json.loads(json.dumps(base))
                context["routing"] = routing
                report = VALIDATOR.Report()
                VALIDATOR.validate_playbook_binding(
                    context,
                    report,
                    check_paths=False,
                    require_binding=True,
                    check_freshness=False,
                    expected_action="implementation",
                )
                self.assertTrue(
                    any(expected_error in error for error in report.errors),
                    report.errors,
                )

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

    def test_v16_run_evaluation_loads_context_without_full_path_checks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, context, context_path = self.write_v16_delegation_fixture(root)
            authority = VALIDATOR.task_authority_hash(context)
            run_record = json.loads(
                (
                    Path(__file__).parents[1]
                    / "plugins/xiaoh/runtime/codex/agent-system/run-record.template.json"
                ).read_text(encoding="utf-8")
            )
            run_record.update({
                "run_id": "v16-evaluation-reviewer",
                "task_id": context["task_id"],
                "agent": "code_quality_reviewer",
                "context_pack": str(context_path),
                "context_hash": authority,
                "runtime_evidence": {
                    "source": "codex-runtime",
                    "agent_type": "code_quality_reviewer",
                    "task_name": "quality__r7__12345678abcdef00",
                    "agent_id": "quality-agent",
                    "parent_agent_id": "root-agent",
                    "transcript_path": str(root / "not-read-in-metric-evaluation.jsonl"),
                    "transcript_hash": "a" * 64,
                    "terminal_event": "task_complete",
                    "delegation_proof_path": str(
                        home / "agent-system/delegation-proofs/not-read-in-metric-evaluation.json"
                    ),
                    "delegation_proof_hash": "b" * 64,
                },
            })
            report = VALIDATOR.Report()
            with patch.object(
                VALIDATOR, "AGENTS_DIR", home / "agents"
            ), patch.object(
                VALIDATOR, "SYSTEM_DIR", home / "agent-system"
            ):
                VALIDATOR.validate_run_record(
                    run_record, report, check_paths=False
                )
            self.assertFalse(report.errors, report.errors)

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

    def test_playbook_adapter_rechecks_new_live_status_wrapper(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker, status, raw, _ = self.write_new_playbook_snapshots(root)
            output = root / "binding.json"
            PLAYBOOK_ADAPTER.create_receipt(
                worker,
                status,
                output,
                "implementation",
                "stable-xiaoh-workspace",
                playbook_command=sys.executable,
            )
            def completed(*_args, **_kwargs):
                raw.write_bytes(raw.read_bytes())
                return SimpleNamespace(
                    returncode=0,
                    stdout=status.read_text(encoding="utf-8"),
                    stderr="",
                )

            with patch.object(
                PLAYBOOK_ADAPTER.subprocess, "run", side_effect=completed
            ) as invoked:
                PLAYBOOK_ADAPTER.validate_receipt(
                    output,
                    expected_sha256=PLAYBOOK_ADAPTER.file_hash(output),
                    expected_action="implementation",
                    check_live_status=True,
                )

        invoked.assert_called_once()

    def test_playbook_adapter_rejects_live_wrapper_pointing_to_old_raw(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker, status, _, _ = self.write_new_playbook_snapshots(root)
            output = root / "binding.json"
            PLAYBOOK_ADAPTER.create_receipt(
                worker,
                status,
                output,
                "implementation",
                "stable-xiaoh-workspace",
                playbook_command=sys.executable,
            )
            completed = SimpleNamespace(
                returncode=0,
                stdout=status.read_text(encoding="utf-8"),
                stderr="",
            )
            with patch.object(
                PLAYBOOK_ADAPTER.subprocess, "run", return_value=completed
            ):
                with self.assertRaisesRegex(
                    PLAYBOOK_ADAPTER.AdapterError, "本次status命令生成"
                ):
                    PLAYBOOK_ADAPTER.validate_receipt(
                        output,
                        expected_sha256=PLAYBOOK_ADAPTER.file_hash(output),
                        expected_action="implementation",
                        check_live_status=True,
                    )

    def test_playbook_adapter_rejects_empty_raw_path_across_all_entry_points(self):
        def probe_command(arguments, **_kwargs):
            output = {
                ("--version",): "playbook version 0.0.40-snapshot",
                ("workspace", "task", "status", "--help"): "--output json",
                (
                    "workspace",
                    "task",
                    "worker",
                    "start",
                    "--help",
                ): "child_worker_context",
            }.get(tuple(arguments[1:]), "")
            return SimpleNamespace(returncode=0, stdout=output, stderr="")

        for invalid_path in ("", None):
            with self.subTest(raw_json_path=invalid_path), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                worker, status, raw, _ = self.write_new_playbook_snapshots(root)
                wrapper = json.loads(raw.read_text(encoding="utf-8"))
                wrapper["evidence"] = {"raw_json_path": invalid_path}
                status.write_text(json.dumps(wrapper), encoding="utf-8")

                with self.assertRaisesRegex(
                    PLAYBOOK_ADAPTER.AdapterError, "raw_json_path无效"
                ):
                    PLAYBOOK_ADAPTER.create_receipt(
                        worker,
                        status,
                        root / "invalid-binding.json",
                        "implementation",
                        "stable-xiaoh-workspace",
                        playbook_command=sys.executable,
                    )

                with patch.object(
                    PLAYBOOK_ADAPTER.shutil, "which", return_value=sys.executable
                ), patch.object(
                    PLAYBOOK_ADAPTER.subprocess, "run", side_effect=probe_command
                ):
                    probe = PLAYBOOK_ADAPTER.playbook_probe(
                        sys.executable, "auto", worker, status
                    )
                self.assertEqual("incompatible", probe["status"])
                self.assertIn("raw_json_path无效", probe["errors"][0])

                worker, status, raw, _ = self.write_new_playbook_snapshots(root)
                output = root / "binding.json"
                PLAYBOOK_ADAPTER.create_receipt(
                    worker,
                    status,
                    output,
                    "implementation",
                    "stable-xiaoh-workspace",
                    playbook_command=sys.executable,
                )
                live = json.loads(raw.read_text(encoding="utf-8"))
                live["evidence"] = {"raw_json_path": invalid_path}
                completed = SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(live),
                    stderr="",
                )
                with patch.object(
                    PLAYBOOK_ADAPTER.subprocess, "run", return_value=completed
                ):
                    with self.assertRaisesRegex(
                        PLAYBOOK_ADAPTER.AdapterError, "raw_json_path无效"
                    ):
                        PLAYBOOK_ADAPTER.validate_receipt(
                            output,
                            expected_sha256=PLAYBOOK_ADAPTER.file_hash(output),
                            expected_action="implementation",
                            check_live_status=True,
                        )

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

    def test_doctor_routing_smoke_includes_both_implementation_reviewers(self):
        commands = XIAOH.doctor_commands(Path("/tmp/codex"))
        routing_command = next(
            command for command in commands if "--routing-case" in command
        )
        selected = routing_command[routing_command.index("--selected-agents") + 1]
        self.assertEqual(
            "java_code_explorer,java_implementer,code_quality_reviewer,"
            "test_integration_verifier",
            selected,
        )

    def test_playbook_version_policy_is_bundled_and_deployed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex = root / "codex"
            vault = root / "vault"
            active_agents, _, _ = XIAOH.copy_runtime(codex, vault)
            report = XIAOH.playbook_version_policy_report(active_agents)

        self.assertEqual("complete", report["status"])
        self.assertFalse(report["mechanical_gate"])
        self.assertTrue(
            all(item["status"] == "complete" for item in report["files"])
        )

    def test_playbook_version_policy_reports_active_contract_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            active_agents = Path(temporary) / "AGENTS.md"
            bundled = (
                XIAOH.RUNTIME / "codex/AGENTS.md"
            ).read_text(encoding="utf-8")
            active_agents.write_text(
                bundled.replace(
                    "不安装命令级机械门禁",
                    "不改变用户的终端使用方式",
                ),
                encoding="utf-8",
            )
            report = XIAOH.playbook_version_policy_report(active_agents)

        self.assertEqual("missing", report["status"])
        self.assertFalse(report["mechanical_gate"])
        self.assertTrue(
            any("active AGENTS缺少" in error for error in report["errors"])
        )

    def test_playbook_version_policy_rejects_missing_delegated_authority_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            active_agents = Path(temporary) / "AGENTS.md"
            bundled = (
                XIAOH.RUNTIME / "codex/AGENTS.md"
            ).read_text(encoding="utf-8")
            active_agents.write_text(
                bundled.replace(
                    "- Playbook、Workspace、项目Skill或错误恢复输出中出现版本更新命令时，只能将其标记为人工边界；用户对业务任务的“继续”“自动推进”或同类授权不包含Playbook版本变更权限。\n",
                    "",
                ),
                encoding="utf-8",
            )
            report = XIAOH.playbook_version_policy_report(active_agents)

        self.assertEqual("missing", report["status"])
        self.assertTrue(
            any("继续”" in error for error in report["errors"])
        )

    def test_playbook_version_policy_must_remain_inside_managed_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            active_agents = Path(temporary) / "AGENTS.md"
            bundled = (
                XIAOH.RUNTIME / "codex/AGENTS.md"
            ).read_text(encoding="utf-8")
            contract = XIAOH.marked_block(
                bundled, "global-agent-common-contract"
            )
            section = XIAOH.markdown_section(
                contract, XIAOH.PLAYBOOK_VERSION_POLICY_FRAGMENTS[0]
            )
            active_agents.write_text(
                bundled.replace(section + "\n\n", "") + "\n" + section + "\n",
                encoding="utf-8",
            )
            report = XIAOH.playbook_version_policy_report(active_agents)

        active = next(
            item for item in report["files"] if item["kind"] == "active"
        )
        self.assertEqual("missing", report["status"])
        self.assertFalse(active["inside_managed_contract"])

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
