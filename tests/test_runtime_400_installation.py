from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from plugins.xiaoh.xiaoh_runtime.adapters.local import LocalFileSystem, SystemClock
from plugins.xiaoh.xiaoh_runtime.installation.candidate import CandidateBuilder
from plugins.xiaoh.xiaoh_runtime.installation.transaction import (
    FaultInjector,
    InstallRequest,
    TransactionalInstaller,
)


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/xiaoh"


class _SecretFault:
    def __call__(self, point: str) -> None:
        if point == "plan":
            raise RuntimeError(
                "token=never-expose-this Bearer abc.def password:also-never-expose"
            )


class Runtime400InstallationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fs = LocalFileSystem()

    def test_isolated_setup_commits_with_verified_backup_and_unverified_activation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            request = _request(Path(temp))
            result = TransactionalInstaller(self.fs, SystemClock(), PLUGIN).execute(request)

            self.assertEqual("passed", result["status"], result)
            self.assertEqual("committed", result["phase"])
            self.assertEqual("runtime_unverified", result["activation_state"])
            self.assertTrue(result["actual_writes"])
            self.assertTrue(result["recovery"]["complete"])
            self.assertEqual(
                "xiaoh-recovery-manifest/v2",
                result["recovery"]["schema_version"],
            )
            self.assertEqual("complete", result["recovery"]["completeness_status"])
            self.assertEqual(
                "xiaoh-installation-plan/v2",
                result["plan"]["schema_version"],
            )
            self.assertTrue(Path(result["backup"]).is_dir())
            installed = json.loads(request.config_path.read_text(encoding="utf-8"))
            self.assertEqual("4.0.0", installed["installed_version"])
            self.assertEqual(
                {
                    "frontend_implementer",
                    "java_architect",
                    "java_code_explorer",
                    "java_implementer",
                    "pki_domain_expert",
                },
                {path.stem for path in (request.codex_home / "agents").glob("*.toml")},
            )
            self.assertFalse(any("__pycache__" in path.parts for path in request.codex_home.rglob("*")))
            self.assertEqual([], list(request.codex_home.rglob("*.pyc")))
            context = json.loads(
                (request.codex_home / "agent-system/task-context.template.json").read_text(
                    encoding="utf-8"
                )
            )
            record = json.loads(
                (request.codex_home / "agent-system/run-record.template.json").read_text(
                    encoding="utf-8"
                )
            )
            authority_hash = hashlib.sha256(
                json.dumps(
                    context,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            self.assertEqual(authority_hash, record["context_hash"])

    def test_failure_after_first_managed_write_rolls_back_every_changed_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            request = _request(Path(temp))
            request.codex_home.mkdir(parents=True)
            old_agents = request.codex_home / "agents"
            old_agents.mkdir()
            (old_agents / "custom.toml").write_text("old = true\n", encoding="utf-8")
            before = _snapshot(request.root)
            injector = FaultInjector({"switch:1"})

            result = TransactionalInstaller(
                self.fs, SystemClock(), PLUGIN, fault_injector=injector
            ).execute(request)

            self.assertEqual("failed", result["status"])
            self.assertEqual("rolled_back", result["phase"])
            self.assertTrue(result["actual_writes"])
            self.assertEqual(before, _snapshot(request.root, exclude_internal=True))
            self.assertTrue(all(item["status"] == "restored" for item in result["recovery_actions"]))

    def test_recovery_failure_is_never_reported_as_rolled_back(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            request = _request(Path(temp))
            injector = FaultInjector({"switch:1", "recovery:0"})

            result = TransactionalInstaller(
                self.fs, SystemClock(), PLUGIN, fault_injector=injector
            ).execute(request)

            self.assertEqual("failed", result["status"])
            self.assertEqual("recovery_required", result["phase"])
            self.assertEqual("recovery_required", result["activation_state"])

    def test_every_transaction_stage_has_a_deterministic_fault_outcome(self) -> None:
        before_switch = {"plan", "candidate", "backup"}
        after_switch = {"switch:vault-template", "switch:configuration", "static-doctor"}
        for point in sorted(before_switch | after_switch):
            with self.subTest(point=point), tempfile.TemporaryDirectory() as temp:
                request = _request(Path(temp))
                result = TransactionalInstaller(
                    self.fs,
                    SystemClock(),
                    PLUGIN,
                    fault_injector=FaultInjector({point}),
                ).execute(request)

                self.assertEqual("failed", result["status"])
                if point in before_switch:
                    self.assertEqual([], result["actual_writes"])
                    self.assertNotEqual("recovery_required", result["phase"])
                else:
                    self.assertEqual("rolled_back", result["phase"])
                    self.assertTrue(result["actual_writes"])
                    self.assertTrue(
                        all(
                            action["status"] == "restored"
                            for action in result["recovery_actions"]
                        )
                    )

    def test_same_input_second_install_has_no_unnecessary_managed_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            request = _request(Path(temp))
            installer = TransactionalInstaller(self.fs, SystemClock(), PLUGIN)
            first = installer.execute(request)
            second = installer.execute(request)

            self.assertEqual("passed", first["status"], first)
            self.assertEqual("passed", second["status"], second)
            self.assertEqual([], second["actual_writes"])

    def test_custom_agent_and_vault_customization_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            request = _request(Path(temp))
            custom_agent = request.codex_home / "agents/custom_agent.toml"
            custom_agent.parent.mkdir(parents=True)
            custom_agent.write_text("name = 'custom'\n", encoding="utf-8")
            workbench = request.vault / "00-工作台/我的工作台.base"
            workbench.parent.mkdir(parents=True)
            source = PLUGIN / "runtime/obsidian/development-vault/00-工作台/我的工作台.base"
            workbench.write_text(source.read_text(encoding="utf-8") + "\n# user preference\n", encoding="utf-8")

            result = TransactionalInstaller(self.fs, SystemClock(), PLUGIN).execute(request)

            self.assertEqual("passed", result["status"], result)
            self.assertEqual("name = 'custom'\n", custom_agent.read_text(encoding="utf-8"))
            self.assertIn("# user preference", workbench.read_text(encoding="utf-8"))
            self.assertIn(
                "00-工作台/我的工作台.base",
                result["preserved_assets"],
            )

    def test_candidate_root_cannot_overlap_source_or_managed_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            builder = CandidateBuilder(self.fs, PLUGIN)
            codex = root / "codex"
            vault = root / "vault"
            config = root / "xiaoh/config.json"
            for candidate in (PLUGIN / "nested-candidate", codex / "candidate", vault):
                with self.assertRaisesRegex(ValueError, "must be independent"):
                    builder._validate_independent_root(candidate, codex, vault, config)

    def test_failure_receipt_and_transaction_journal_redact_secret_material(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            request = _request(Path(temp))
            result = TransactionalInstaller(
                self.fs,
                SystemClock(),
                PLUGIN,
                fault_injector=_SecretFault(),
            ).execute(request)
            journal = next((request.root / "xiaoh/transactions").glob("*/transaction.json"))
            encoded = json.dumps(result) + journal.read_text(encoding="utf-8")

            self.assertEqual("failed", result["status"])
            self.assertNotIn("never-expose", encoded)
            self.assertNotIn("abc.def", encoded)
            self.assertIn("[REDACTED]", encoded)


def _request(root: Path) -> InstallRequest:
    vault = root / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    return InstallRequest(
        operation="setup",
        root=root,
        codex_home=root / "codex",
        vault=vault,
        config_path=root / "xiaoh/config.json",
    )


def _snapshot(root: Path, exclude_internal: bool = False) -> dict[str, bytes]:
    result = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if exclude_internal and relative.startswith("xiaoh/"):
            continue
        result[relative] = path.read_bytes()
    return result


if __name__ == "__main__":
    unittest.main()
