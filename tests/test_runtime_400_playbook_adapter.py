"""Playbook 0.0.41 task-status contract tests for the XiaoH adapter."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


REAL_SUBPROCESS_RUN = subprocess.run
ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = (
    ROOT / "plugins/xiaoh/runtime/codex/agent-system/playbook_adapter.py"
)
SPEC = importlib.util.spec_from_file_location("xiaoh_playbook_adapter", ADAPTER_PATH)
ADAPTER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ADAPTER)


class Runtime400PlaybookAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.worktree = self.root / "member-a"
        self.worktree.mkdir()
        self._git("init", "-b", "feature/status-contract")
        self._git("config", "user.email", "xiaoh@example.invalid")
        self._git("config", "user.name", "XiaoH Test")
        (self.worktree / "README.md").write_text("fixture\n", encoding="utf-8")
        self._git("add", "README.md")
        self._git("commit", "-m", "fixture")
        self.head = self._git("rev-parse", "HEAD").stdout.strip()
        self.worker_path = self.root / "worker.json"
        self.status_path = self.root / "status.json"
        self.worker = {
            "workspace_id": "workspace-a",
            "change_id": "change-a",
            "member": "member-a",
            "member_worktree": str(self.worktree),
            "workspace_root": str(self.root),
            "allowed_scope": [str(self.worktree)],
        }
        self.status = {
            "workspace_id": "workspace-a",
            "change_id": "change-a",
            "members": [
                {
                    "repo": "member-a",
                    "branch": "feature/status-contract",
                    "head": self.head[:12],
                    "base_sync": {"branch": "develop", "status": "up_to_date"},
                    "sdd": {"provider": "openspec", "state": "confirmed", "tasks": "complete"},
                }
            ],
            "blockers": [],
            "next_actions": [{"action": "finalize_task", "member": "member-a"}],
            "refreshed_at": "2026-08-03T09:00:00+08:00",
            "task_truth_path": str(self.root / "task-truth.yaml"),
        }
        self._write_snapshots()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _git(self, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *arguments],
            cwd=self.worktree,
            capture_output=True,
            text=True,
            check=True,
        )

    def _write_snapshots(self) -> None:
        self.worker_path.write_text(json.dumps(self.worker), encoding="utf-8")
        self.status_path.write_text(json.dumps(self.status), encoding="utf-8")

    @staticmethod
    def _probe_command(arguments, **kwargs):
        suffix = tuple(arguments[1:])
        if suffix == ("--version",):
            return SimpleNamespace(
                returncode=0,
                stdout="playbook version 0.0.41 (2026-08-02 06:36)\n",
                stderr="",
            )
        if suffix == ("workspace", "task", "status", "--help"):
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    "usage: playbook workspace task status --workspace-id <id> "
                    "workspace_id change_id members blockers next_actions "
                    "refreshed_at task_truth_path"
                ),
                stderr="",
            )
        return REAL_SUBPROCESS_RUN(arguments, **kwargs)

    def _probe(self, with_evidence: bool):
        with patch.object(ADAPTER.shutil, "which", return_value=sys.executable), patch.object(
            ADAPTER.subprocess, "run", side_effect=self._probe_command
        ):
            return ADAPTER.playbook_probe(
                sys.executable,
                "auto",
                self.worker_path if with_evidence else None,
                self.status_path if with_evidence else None,
            )

    def test_probe_separates_command_contract_from_evidence_validation(self) -> None:
        command_only = self._probe(with_evidence=False)
        actual = self._probe(with_evidence=True)

        self.assertEqual("available", command_only["status"])
        self.assertTrue(command_only["task_status_contract"])
        self.assertFalse(command_only["task_status_evidence_contract"])
        self.assertEqual("unverified", command_only["status_contract"])
        self.assertEqual("compatible", actual["status"])
        self.assertTrue(actual["task_status_evidence_contract"])
        self.assertEqual("task_status_public_v1", actual["status_contract"])

    def test_public_status_contract_binds_worker_and_git_identity(self) -> None:
        self.status["members"].append(
            {
                "repo": "read-only-context",
                "branch": None,
                "head": None,
                "base_sync": {"branch": "develop", "status": "unknown"},
                "sdd": {"provider": "openspec", "state": "missing", "tasks": "missing"},
                "issue": {"status": "not_created"},
            }
        )
        self.status["next_actions"] = None
        self._write_snapshots()
        validation = ADAPTER.validate_task_status(self.status_path, self.worker)

        self.assertEqual("task_status_public_v1", validation["contract"])
        self.assertEqual("member-a", validation["member"]["repo"])

    def test_public_status_contract_rejects_identity_and_shape_mismatches(self) -> None:
        cases = {
            "workspace": ("workspace_id", "other-workspace"),
            "change": ("change_id", "other-change"),
            "branch": ("members.0.branch", "feature/other"),
            "head": ("members.0.head", "0" * 12),
        }
        for label, (path, value) in cases.items():
            with self.subTest(label=label):
                payload = json.loads(json.dumps(self.status))
                if path.startswith("members.0."):
                    payload["members"][0][path.rsplit(".", 1)[1]] = value
                else:
                    payload[path] = value
                self.status_path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(ADAPTER.AdapterError):
                    ADAPTER.validate_task_status(self.status_path, self.worker)

        malformed = json.loads(json.dumps(self.status))
        malformed["members"] = {}
        self.status_path.write_text(json.dumps(malformed), encoding="utf-8")
        with self.assertRaises(ADAPTER.AdapterError):
            ADAPTER.validate_task_status(self.status_path, self.worker)

        extra = json.loads(json.dumps(self.status))
        extra["phase"] = "implementation"
        self.status_path.write_text(json.dumps(extra), encoding="utf-8")
        with self.assertRaises(ADAPTER.AdapterError):
            ADAPTER.validate_task_status(self.status_path, self.worker)

        invalid_action = json.loads(json.dumps(self.status))
        invalid_action["next_actions"] = [{"action": "run_arbitrary_command"}]
        self.status_path.write_text(json.dumps(invalid_action), encoding="utf-8")
        with self.assertRaises(ADAPTER.AdapterError):
            ADAPTER.validate_task_status(self.status_path, self.worker)

        invalid_blocker = json.loads(json.dumps(self.status))
        invalid_blocker["blockers"] = [{"code": "unknown_security_bypass"}]
        self.status_path.write_text(json.dumps(invalid_blocker), encoding="utf-8")
        with self.assertRaises(ADAPTER.AdapterError):
            ADAPTER.validate_task_status(self.status_path, self.worker)

    def test_receipt_records_and_revalidates_status_contract(self) -> None:
        output = self.root / "receipt.json"
        captured = ADAPTER.create_receipt(
            self.worker_path,
            self.status_path,
            output,
            "implementation",
            "xiaoh-workspace-a",
            playbook_command=sys.executable,
        )

        self.assertEqual(
            "task_status_public_v1",
            captured["receipt"]["playbook"]["status_contract"],
        )
        ADAPTER.validate_receipt(output)

        payload = json.loads(self.status_path.read_text(encoding="utf-8"))
        payload["workspace_id"] = "other-workspace"
        self.status_path.write_text(json.dumps(payload), encoding="utf-8")
        captured["receipt"]["playbook"]["status_sha256"] = ADAPTER.file_hash(
            self.status_path
        )
        receipt_without_binding = {
            key: value
            for key, value in captured["receipt"].items()
            if key != "binding_sha256"
        }
        captured["receipt"]["binding_sha256"] = ADAPTER.canonical_hash(
            receipt_without_binding
        )
        output.write_text(json.dumps(captured["receipt"]), encoding="utf-8")
        with self.assertRaises(ADAPTER.AdapterError):
            ADAPTER.validate_receipt(output)


if __name__ == "__main__":
    unittest.main()
