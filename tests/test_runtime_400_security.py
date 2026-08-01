"""Security contract tests for XiaoH 4.0 Hook and Validator boundaries."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
AGENT_SYSTEM = ROOT / "plugins/xiaoh/runtime/codex/agent-system"
HOOKS = ROOT / "plugins/xiaoh/runtime/codex/hooks"
sys.path.insert(0, str(AGENT_SYSTEM))

from xiaoh_security.delegation import DelegationGate, canonical_hash  # noqa: E402
from xiaoh_security.execution import RootExecutionGate  # noqa: E402
from xiaoh_security.vault_guard import VaultWriteGuard  # noqa: E402
from xiaoh_validator.delegation import validate_execution_binding  # noqa: E402
from xiaoh_validator.diagnostics import Report  # noqa: E402
from xiaoh_validator.global_validation import validate_agent_catalog  # noqa: E402
from xiaoh_validator.run_record import validate_run_record  # noqa: E402
from xiaoh_validator.requirements import example_requirements, validate_requirements  # noqa: E402
from xiaoh_validator.task_context import validate_task_context  # noqa: E402


class Runtime400DelegationSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / ".codex"
        self.context_path = self.root / "task-context.json"
        self.context = {
            "schema_version": "1.6",
            "task_id": "task-400",
            "routing": {
                "root_agent": "xiaoh",
                "delegated_agents": ["java_implementer"],
                "delegation_policies": {
                    "java_implementer": {
                        "agent_type": "java_implementer",
                        "action": "implementation",
                        "task_name_prefix": "runtime400",
                        "allowed_paths": [str(self.root)],
                        "read_only": False,
                    }
                },
            },
        }
        self._write_context()
        self.gate = DelegationGate(self.home, run_validator=False)

    def tearDown(self):
        self.temporary.cleanup()

    def _write_context(self):
        self.context_path.write_text(
            json.dumps(self.context, ensure_ascii=False), encoding="utf-8"
        )

    def _prepare(self, agent="java_implementer"):
        authority_hash = canonical_hash(self.context)
        message = (
            "task_id: task-400\n"
            "task_context: {}\n"
            "authority_hash: {}\n"
            "delegated_agent: {}\n"
        ).format(self.context_path, authority_hash, agent)
        return self.gate.prepare(
            {"tool_input": {"agent_type": agent, "message": message}}
        )

    def test_exact_task_name_is_required_and_binding_is_single_use(self):
        prepared = self._prepare()
        wrong = self.gate.start(
            {
                "agent_type": "java_implementer",
                "task_name": "runtime400__r1__deadbeefdead",
                "agent_id": "agent-1",
            }
        )
        self.assertIn("systemMessage", wrong)
        task_name = prepared["tool_input"]["task_name"]
        started = self.gate.start(
            {
                "agent_type": "java_implementer",
                "task_name": task_name,
                "agent_id": "agent-1",
            }
        )
        self.assertEqual(
            "SubagentStart",
            started["hookSpecificOutput"]["hookEventName"],
        )
        self.assertIn("xiaoh-delegation-receipt", started["hookSpecificOutput"]["additionalContext"])
        reused = self.gate.start(
            {
                "agent_type": "java_implementer",
                "task_name": task_name,
                "agent_id": "agent-2",
            }
        )
        self.assertIn("systemMessage", reused)

    def test_context_drift_and_role_mismatch_fail_closed(self):
        prepared = self._prepare()
        task_name = prepared["tool_input"]["task_name"]
        mismatch = self.gate.start(
            {
                "agent_type": "java_architect",
                "task_name": task_name,
                "agent_id": "agent-wrong",
            }
        )
        self.assertIn("systemMessage", mismatch)
        self.context["revision"] = 2
        self._write_context()
        drift = self.gate.start(
            {
                "agent_type": "java_implementer",
                "task_name": task_name,
                "agent_id": "agent-drift",
            }
        )
        self.assertIn("systemMessage", drift)

    def test_receipt_and_transcript_are_both_required_for_attestation(self):
        prepared = self._prepare()
        task_name = prepared["tool_input"]["task_name"]
        started = self.gate.start(
            {
                "agent_type": "java_implementer",
                "task_name": task_name,
                "agent_id": "agent-3",
            }
        )
        additional = started["hookSpecificOutput"]["additionalContext"]
        receipt = re.search(r"xiaoh-delegation-receipt: ([0-9a-f]{64})", additional).group(1)
        wrong = self.gate.stop(
            {"agent_id": "agent-3", "last_assistant_message": "no receipt"}
        )
        self.assertEqual("block", wrong["decision"])
        missing = self.gate.stop(
            {
                "agent_id": "agent-3",
                "last_assistant_message": "xiaoh-delegation-receipt: {}".format(receipt),
                "agent_transcript_path": str(self.root / "missing.jsonl"),
            }
        )
        self.assertEqual("block", missing["decision"])
        transcript = self.root / "agent.jsonl"
        transcript.write_text('{"type":"event_msg"}\n', encoding="utf-8")
        self.assertIsNone(
            self.gate.stop(
                {
                    "agent_id": "agent-3",
                    "last_assistant_message": "xiaoh-delegation-receipt: {}".format(receipt),
                    "agent_transcript_path": str(transcript),
                }
            )
        )
        proof_files = list(self.gate.proof_directory.glob("*.json"))
        proof = json.loads(proof_files[0].read_text(encoding="utf-8"))
        self.assertEqual("attested", proof["state"])
        self.assertTrue(proof["attested"])
        self.assertNotIn(receipt, proof_files[0].read_text(encoding="utf-8"))

    def test_reserved_root_identity_cannot_be_prepared(self):
        with self.assertRaisesRegex(ValueError, "reserved root identity"):
            self._prepare("xiaoh")

    def test_validator_accepts_v2_binding_and_rejects_expired_binding(self):
        prepared = self._prepare()
        binding_path = Path(prepared["execution_binding"])
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
        report = Report()
        validate_execution_binding(
            binding,
            self.context,
            self.context_path,
            "java_implementer",
            "implementation",
            report,
            check_paths=False,
        )
        self.assertEqual([], report.errors)
        binding["expires_at"] = datetime(2000, 1, 1, tzinfo=timezone.utc).isoformat()
        unhashed = dict(binding)
        unhashed.pop("binding_hash")
        binding["binding_hash"] = canonical_hash(unhashed)
        expired = Report()
        validate_execution_binding(
            binding,
            self.context,
            self.context_path,
            "java_implementer",
            "implementation",
            expired,
            check_paths=False,
        )
        self.assertTrue(any("expired" in error or "stale" in error for error in expired.errors))


class Runtime400VaultSecurityTests(unittest.TestCase):
    def test_other_vault_parent_escape_and_symlink_escape_are_denied(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            allowed = root / "allowed"
            other = root / "other"
            outside = root / "outside"
            for path in (allowed, other):
                (path / ".obsidian").mkdir(parents=True)
            outside.mkdir()
            config = root / "config.json"
            config.write_text(
                json.dumps({"obsidian_vault": str(allowed)}), encoding="utf-8"
            )
            guard = VaultWriteGuard(config)
            self.assertIsNone(
                guard.decision({"cwd": str(root), "tool_input": {"path": str(allowed / "ok.md")}})
            )
            self.assertIsNotNone(
                guard.decision({"cwd": str(root), "tool_input": {"path": str(other / "bad.md")}})
            )
            self.assertIsNotNone(
                guard.decision({"cwd": str(root), "tool_input": {"path": str(allowed / ".." / "bad.md")}})
            )
            link = allowed / "linked"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("symlinks are not available")
            self.assertIsNotNone(
                guard.decision({"cwd": str(root), "tool_input": {"path": str(link / "bad.md")}})
            )

    def test_hook_entrypoints_keep_self_test_contract(self):
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "cp1252"
        for script in ("block_reserved_root_agent.py", "guard_vault_writes.py", "guard_task_writes.py"):
            completed = subprocess.run(
                [sys.executable, str(HOOKS / script), "--self-test"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                env=environment,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)

    def test_subagent_start_entrypoint_emits_codex_hook_protocol_shape(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(HOOKS / "block_reserved_root_agent.py"),
                "--subagent-start",
            ],
            input="[]",
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        response = json.loads(completed.stdout)
        self.assertEqual(
            "SubagentStart",
            response["hookSpecificOutput"]["hookEventName"],
        )
        self.assertEqual(
            "未授权的 XiaoH 子 Agent。",
            response["hookSpecificOutput"]["additionalContext"],
        )


class Runtime400ValidatorContractTests(unittest.TestCase):
    def test_agent_catalog_has_only_the_five_specialists(self):
        report = Report()

        validate_agent_catalog(
            report,
            agents_dir=ROOT / "plugins/xiaoh/runtime/codex/agents",
        )

        self.assertEqual([], report.errors)
        self.assertEqual(
            [
                "frontend_implementer",
                "java_architect",
                "java_code_explorer",
                "java_implementer",
                "pki_domain_expert",
            ],
            report.details["managed_agents"],
        )

    def test_task_context_template_and_routing_contract(self):
        template = json.loads(
            (AGENT_SYSTEM / "task-context.template.json").read_text(encoding="utf-8")
        )
        report = Report()
        validate_task_context(
            template,
            report,
            check_paths=False,
            check_freshness=False,
        )
        self.assertEqual([], report.errors)
        self.assertEqual("fast", template["execution"]["lane"])
        self.assertEqual(
            "impact_driven", template["execution"]["verification_scope"]
        )

        drifted = json.loads(json.dumps(template))
        drifted["routing"]["delegated_agents"] = ["unknown_agent"]
        drifted["routing"]["delegation_policies"] = {
            "unknown_agent": {
                "agent_type": "unknown_agent",
                "action": "implementation",
                "task_name_prefix": "unknown",
            }
        }
        invalid = Report()
        validate_task_context(
            drifted,
            invalid,
            check_paths=False,
            check_freshness=False,
        )
        self.assertTrue(any("unregistered agents" in error for error in invalid.errors))

    def test_execution_lane_rejects_unsafe_downgrade_and_unjustified_delegation(self):
        template = json.loads(
            (AGENT_SYSTEM / "task-context.template.json").read_text(encoding="utf-8")
        )

        high_risk_fast = json.loads(json.dumps(template))
        high_risk_fast["risk_level"] = "high"
        invalid = Report()
        validate_task_context(
            high_risk_fast,
            invalid,
            check_paths=False,
            check_freshness=False,
        )
        self.assertTrue(any("fast execution lane requires risk_level=low" in error for error in invalid.errors))

        delegated_without_agent = json.loads(json.dumps(template))
        delegated_without_agent["execution"]["delegation"] = {
            "decision": "delegate",
            "authorized": True,
            "benefits": ["parallel investigation"],
            "reason": "Parallel work would shorten discovery.",
        }
        invalid = Report()
        validate_task_context(
            delegated_without_agent,
            invalid,
            check_paths=False,
            check_freshness=False,
        )
        self.assertTrue(any("delegate decision requires delegated_agents" in error for error in invalid.errors))

        destructive = json.loads(json.dumps(template))
        destructive["execution"]["effects"] = {
            "level": "destructive",
            "authorized": False,
            "evidence": None,
        }
        invalid = Report()
        validate_task_context(
            destructive, invalid, check_paths=False, check_freshness=False
        )
        self.assertTrue(any("explicit authorization evidence" in error for error in invalid.errors))

    def test_direct_change_requires_no_new_requirement_or_risk_signal(self):
        requirements = example_requirements()
        requirements.update({
            "artifact_route": "direct_change",
            "route_reason": "A reproduced local defect has one reversible root-cause fix.",
            "risk_signals": [],
            "required_gates": ["deterministic_verification"],
            "spec_rfc": {
                "status": "not_required",
                "reference": None,
                "revision": 0,
                "validation_status": "not_required",
                "confirmed_by_user": False,
                "confirmed_at": None,
            },
            "openspec": {
                "status": "not_required",
                "traceability_status": "not_required",
                "validated_spec_rfc_revision": None,
                "confirmed_by_user": False,
                "confirmed_at": None,
            },
            "bypass": {"reason": "No durable behavior or contract changes."},
            "skill_execution": {"explicitly_requested": [], "records": []},
        })
        report = Report()
        validate_requirements(requirements, report)
        self.assertEqual([], report.errors)

        requirements["risk_signals"] = ["security"]
        invalid = Report()
        validate_requirements(requirements, invalid)
        self.assertTrue(any("direct_change requires empty" in error for error in invalid.errors))

    def test_run_record_template_and_closure_contract(self):
        template = json.loads(
            (AGENT_SYSTEM / "run-record.template.json").read_text(encoding="utf-8")
        )
        report = Report()

        validate_run_record(template, report, check_paths=False)

        self.assertEqual([], report.errors)

        incomplete = json.loads(json.dumps(template))
        del incomplete["outputs"]["verification_summary"]
        invalid = Report()
        validate_run_record(incomplete, invalid, check_paths=False)
        self.assertTrue(any("completed run record outputs" in error for error in invalid.errors))

        hostile = json.loads(json.dumps(template))
        hostile["verification"][0]["id"] = []
        hostile["verification"][0]["status"] = {}
        invalid = Report()
        validate_run_record(hostile, invalid, check_paths=False)
        self.assertTrue(invalid.errors)

    def test_task_context_rejects_structural_shells_and_unscoped_delegation(self):
        template = json.loads(
            (AGENT_SYSTEM / "task-context.template.json").read_text(encoding="utf-8")
        )
        malformed = json.loads(json.dumps(template))
        malformed["behavior"] = {}
        malformed["scope"] = {}
        malformed["sources"] = [42]
        malformed["confirmed_decisions"] = "not-a-list"
        malformed["acceptance"] = [42]
        malformed["verification"] = [42]
        malformed["output_contract"] = {}
        malformed["stop_conditions"] = "not-a-list"

        report = Report()
        validate_task_context(
            malformed, report, check_paths=False, check_freshness=False
        )

        self.assertGreaterEqual(len(report.errors), 8)

        hostile = json.loads(json.dumps(template))
        hostile["task_type"] = {}
        hostile["risk_level"] = []
        hostile["sources"][0]["kind"] = []
        hostile["verification"][0]["id"] = []
        hostile["verification"][0]["category"] = {}
        hostile["execution"]["lane"] = []
        hostile["execution"]["effects"]["level"] = {}
        hostile_report = Report()
        validate_task_context(
            hostile, hostile_report, check_paths=False, check_freshness=False
        )
        self.assertTrue(hostile_report.errors)

        delegated = json.loads(json.dumps(template))
        delegated["routing"]["delegated_agents"] = ["java_implementer"]
        delegated["routing"]["delegation_policies"] = {
            "java_implementer": {
                "agent_type": "java_implementer",
                "action": "implementation",
                "task_name_prefix": "bounded",
                "allowed_paths": [],
                "read_only": False,
            }
        }
        delegated["execution"]["delegation"] = {
            "decision": "delegate",
            "authorized": True,
            "benefits": ["write isolation"],
            "reason": "A bounded writer owns one isolated path.",
        }
        invalid = Report()
        validate_task_context(
            delegated, invalid, check_paths=False, check_freshness=False
        )
        self.assertTrue(any("allowed_paths" in error for error in invalid.errors))

    def test_task_context_source_digest_and_verification_identity_are_checked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            source.write_text("accepted\n", encoding="utf-8")
            template = json.loads(
                (AGENT_SYSTEM / "task-context.template.json").read_text(encoding="utf-8")
            )
            template["scope"] = {
                "workspace": str(root),
                "repositories": [],
                "allowed_paths": [str(root)],
                "preexisting_changes": [],
                "prohibited_actions": ["write outside scope"],
            }
            template["sources"] = [{
                "path": str(source),
                "purpose": "accepted fact",
                "required": True,
                "kind": "file",
                "sha256": "0" * 64,
            }]
            template["verification"] = [{
                "id": "scope-proof",
                "category": "scope",
                "command": "verify scope",
                "expected": "exit code 0",
                "required": True,
            }]
            report = Report()
            validate_task_context(
                template, report, check_paths=True, check_freshness=False
            )
            self.assertTrue(any("source sha256" in error for error in report.errors))

            duplicate = json.loads(json.dumps(template))
            duplicate["sources"] = []
            duplicate["verification"] *= 2
            invalid = Report()
            validate_task_context(
                duplicate, invalid, check_paths=False, check_freshness=False
            )
            self.assertTrue(any("verification id" in error for error in invalid.errors))

    def test_completed_run_requires_matching_verification_and_scope_proof(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context = json.loads(
                (AGENT_SYSTEM / "task-context.template.json").read_text(encoding="utf-8")
            )
            context["task_id"] = "evidence-task"
            context["task_type"] = "implementation"
            context["verification"] = [{
                "id": "scope-proof",
                "category": "scope",
                "command": "attest root scope",
                "expected": "passed",
                "required": True,
            }]
            context_path = root / "context.json"
            context_path.write_text(json.dumps(context), encoding="utf-8")
            context_hash = canonical_hash(context)
            log = root / "scope-evidence.json"
            log.write_text(json.dumps({
                "schema_version": "xiaoh-verification-evidence/v1",
                "task_id": "evidence-task",
                "context_hash": context_hash,
                "binding_hash": "1" * 64,
                "verification_id": "scope-proof",
                "category": "scope",
                "command": "attest root scope",
                "expected": "passed",
                "exit_code": 0,
                "started_at": "2026-08-01T10:00:10+08:00",
                "ended_at": "2026-08-01T10:00:20+08:00",
                "output_sha256": "2" * 64,
            }), encoding="utf-8")
            changed = str(root / "changed.txt")
            proof = {
                "schema_version": "xiaoh-root-scope-proof/v1",
                "task_id": "evidence-task",
                "context_hash": context_hash,
                "binding_hash": "1" * 64,
                "status": "passed",
                "changed_paths": [changed],
                "scope_violations": [],
                "preexisting_change_violations": [],
            }
            proof_path = root / "proof.json"
            proof_path.write_text(json.dumps(proof), encoding="utf-8")
            record = json.loads(
                (AGENT_SYSTEM / "run-record.template.json").read_text(encoding="utf-8")
            )
            record.update({
                "task_id": "evidence-task",
                "context_pack": str(context_path),
                "context_hash": context_hash,
                "started_at": "2026-08-01T10:00:00+08:00",
                "ended_at": "2026-08-01T10:01:00+08:00",
            })
            record["verification"] = [{
                "id": "scope-proof",
                "category": "scope",
                "command": "attest root scope",
                "status": "passed",
                "summary": "scope passed",
                "exit_code": 0,
                "started_at": "2026-08-01T10:00:10+08:00",
                "ended_at": "2026-08-01T10:00:20+08:00",
                "evidence_path": str(log),
                "evidence_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
            }]
            record["outputs"]["changed_scope"] = [changed]
            record["execution_evidence"] = {
                "scope_proof_path": str(proof_path),
                "scope_proof_sha256": hashlib.sha256(proof_path.read_bytes()).hexdigest(),
            }
            report = Report()
            validate_run_record(record, report, check_paths=True)
            self.assertEqual([], report.errors)

            forged = json.loads(json.dumps(record))
            forged["verification"][0]["evidence_sha256"] = "0" * 64
            forged["execution_evidence"] = None
            invalid = Report()
            validate_run_record(forged, invalid, check_paths=True)
            self.assertTrue(any("evidence hash" in error for error in invalid.errors))
            self.assertTrue(any("execution_evidence" in error for error in invalid.errors))


class Runtime400RootExecutionSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "XiaoH Test"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "xiaoh@example.invalid"], check=True)
        (self.repo / "allowed").mkdir()
        (self.repo / "other").mkdir()
        (self.repo / "allowed" / "owned.txt").write_text("base\n", encoding="utf-8")
        (self.repo / "allowed" / "baseline.txt").write_text("accepted\n", encoding="utf-8")
        (self.repo / "other" / "user.txt").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "base"], check=True)
        self.context_path = self.root / "task-context.json"
        template = json.loads(
            (AGENT_SYSTEM / "task-context.template.json").read_text(encoding="utf-8")
        )
        template["task_id"] = "root-scope-task"
        template["task_type"] = "implementation"
        template["scope"] = {
            "workspace": str(self.repo),
            "repositories": [str(self.repo)],
            "allowed_paths": [str(self.repo / "allowed")],
            "preexisting_changes": [],
            "prohibited_actions": ["write outside scope"],
        }
        source = self.repo / "allowed" / "baseline.txt"
        template["sources"] = [{
            "path": str(source.resolve()),
            "purpose": "accepted implementation baseline",
            "required": True,
            "kind": "file",
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }]
        template["freshness"]["checked_at"] = datetime.now(timezone.utc).isoformat()
        template["execution"]["verification_profile"] = {
            "required_categories": ["scope"],
            "not_applicable": [],
        }
        template["verification"] = [{
            "id": "scope-proof",
            "category": "scope",
            "command": "python3 -c \"print('scope')\"",
            "expected": "passed scope proof",
            "required": True,
        }]
        self.context = template
        self.context_path.write_text(json.dumps(template), encoding="utf-8")
        self.gate = RootExecutionGate(self.root / ".codex", now=lambda: datetime.now(timezone.utc))

    def tearDown(self):
        self.temporary.cleanup()

    def test_binding_blocks_known_out_of_scope_patch_and_attests_real_diff(self):
        prepared = self.gate.prepare(self.context_path, session_id="root-session")
        with self.assertRaisesRegex(ValueError, "unattested"):
            self.gate.prepare(self.context_path, session_id="root-session")
        blocked = self.gate.decision({
            "session_id": "root-session",
            "cwd": str(self.repo),
            "tool_name": "apply_patch",
            "tool_input": {"patch": "*** Update File: other/user.txt\n"},
        })
        self.assertEqual("block", blocked["decision"])
        blocked_command = self.gate.decision({
            "session_id": "root-session",
            "cwd": str(self.repo),
            "tool_name": "exec_command",
            "tool_input": {"cmd": "touch other/escaped.txt"},
        })
        self.assertEqual("block", blocked_command["decision"])

        (self.repo / "allowed" / "owned.txt").write_text("task\n", encoding="utf-8")
        proof = self.gate.attest(prepared["binding_path"], prepared["binding_hash"])
        self.assertEqual("passed", proof["status"])
        self.assertEqual(
            [str((self.repo / "allowed" / "owned.txt").resolve())], proof["changed_paths"]
        )

    def test_attestation_finds_shell_escape_and_preexisting_change_takeover(self):
        prepared = self.gate.prepare(self.context_path, session_id="root-session")
        (self.repo / "other" / "user.txt").write_text("escaped\n", encoding="utf-8")
        proof = self.gate.attest(prepared["binding_path"], prepared["binding_hash"])
        self.assertEqual("failed", proof["status"])
        self.assertIn(str((self.repo / "other" / "user.txt").resolve()), proof["scope_violations"])

        (self.repo / "other" / "user.txt").write_text("base\n", encoding="utf-8")
        dirty = self.repo / "allowed" / "owned.txt"
        dirty.write_text("user change\n", encoding="utf-8")
        prepared = self.gate.prepare(self.context_path, session_id="second-session")
        dirty.write_text("task replaced it\n", encoding="utf-8")
        proof = self.gate.attest(prepared["binding_path"], prepared["binding_hash"])
        self.assertEqual("failed", proof["status"])
        self.assertIn(str(dirty.resolve()), proof["preexisting_change_violations"])

    def test_attestation_includes_changes_committed_after_binding(self):
        prepared = self.gate.prepare(self.context_path, session_id="commit-session")
        escaped = self.repo / "other" / "user.txt"
        escaped.write_text("committed escape\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", str(escaped)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "escape"], check=True)

        proof = self.gate.attest(prepared["binding_path"], prepared["binding_hash"])

        self.assertEqual("failed", proof["status"])
        self.assertIn(str(escaped.resolve()), proof["scope_violations"])

    def test_controlled_verification_binds_command_result_to_context(self):
        prepared = self.gate.prepare(self.context_path, session_id="verify-session")

        evidence = self.gate.run_verification(
            prepared["binding_path"], prepared["binding_hash"], "scope-proof"
        )

        self.assertEqual("passed", evidence["status"])
        payload = json.loads(Path(evidence["evidence_path"]).read_text(encoding="utf-8"))
        self.assertEqual(canonical_hash(self.context), payload["context_hash"])
        self.assertEqual("python3 -c \"print('scope')\"", payload["command"])


class Runtime400CommandPolicyTests(unittest.TestCase):
    def test_managed_runtime_contains_no_forbidden_playbook_or_trust_mutations(self):
        forbidden = re.compile(
            r"playbook\s+version\s+update|npm\s+(?:install|update|uninstall|link|unlink).*playbook|"
            r"(?:trust|plugin-cache).*(?:write|replace|unlink|remove)",
            re.IGNORECASE,
        )
        runtime = ROOT / "plugins/xiaoh"
        offenders = []
        for path in runtime.rglob("*"):
            if path.suffix not in {".py", ".sh", ".ps1"} or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if forbidden.search(text):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual([], offenders)


if __name__ == "__main__":
    unittest.main()
