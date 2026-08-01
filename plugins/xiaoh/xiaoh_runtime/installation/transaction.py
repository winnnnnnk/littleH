"""Compensating XiaoH installation transaction."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Set

from ..diagnostics.doctor import DiagnosticContext, DoctorRunner, default_diagnostics
from ..domain.models import (
    ActivationState,
    InstallationTransaction,
    RecoveryManifest,
    TransactionPhase,
)
from ..ports.protocols import ClockPort, FileSystemPort
from ..services.redaction import redact_text
from .candidate import CandidateBuilder, CandidateBundle, SwitchAsset
from .planner import InstallationPlanner
from .recovery import RecoveryManager


@dataclass(frozen=True)
class InstallRequest:
    operation: str
    root: Path
    codex_home: Path
    vault: Path
    config_path: Path
    user_home: Optional[Path] = None


@dataclass
class FaultInjector:
    points: Set[str] = field(default_factory=set)

    def __call__(self, point: str) -> None:
        if point in self.points:
            raise RuntimeError(f"fault injected at {point}")


class TransactionalInstaller:
    def __init__(
        self,
        filesystem: FileSystemPort,
        clock: ClockPort,
        plugin_root: Path,
        fault_injector: Optional[Callable[[str], None]] = None,
    ):
        self.fs = filesystem
        self.clock = clock
        self.plugin_root = filesystem.resolve(plugin_root)
        self.fault = fault_injector or FaultInjector()

    def execute(self, request: InstallRequest) -> dict[str, Any]:
        transaction = InstallationTransaction.new(request.operation)
        transaction_root = (
            self.fs.resolve(request.config_path).parent
            / "transactions"
            / transaction.transaction_id
        )
        candidate_root = transaction_root / "candidate"
        timestamp = self.clock.now().strftime("%Y%m%d-%H%M%S")
        backup_root = (
            self.fs.resolve(request.config_path).parent
            / "backups"
            / f"{timestamp}-{transaction.transaction_id[:8]}"
        )
        journal = transaction_root / "transaction.json"
        bundle: CandidateBundle | None = None
        recovery = RecoveryManifest(transaction.transaction_id, str(backup_root))
        static_doctor: dict[str, Any] | None = None
        plan = None
        self.fs.mkdir(transaction_root)
        self._write_journal(journal, transaction)
        try:
            plan = InstallationPlanner(self.fs, self.plugin_root).create_plan(
                request.operation,
                request.codex_home,
                request.vault,
                request.config_path,
            )
            transaction.record_plan(
                plan.expected_creates + plan.expected_overwrites
            )
            self._write_journal(journal, transaction)
            self.fault("plan")
            bundle = CandidateBuilder(self.fs, self.plugin_root).build(
                transaction.transaction_id,
                candidate_root,
                self.fs.resolve(request.codex_home),
                self.fs.resolve(request.vault),
                self.fs.resolve(request.config_path),
                self.fs.resolve(request.user_home or request.root),
            )
            self.fault("candidate")
            transaction.advance(TransactionPhase.CANDIDATE_VALIDATED)
            self._write_journal(journal, transaction)

            recovery = RecoveryManager(self.fs).create_manifest(
                transaction.transaction_id, backup_root, bundle.assets
            )
            if not recovery.complete or recovery.errors:
                raise RuntimeError("recovery backup is incomplete: " + "; ".join(recovery.errors))
            self.fault("backup")
            transaction.advance(TransactionPhase.BACKED_UP)
            self._write_journal(journal, transaction)

            transaction.advance(TransactionPhase.SWITCHING)
            self._write_journal(journal, transaction)
            for index, asset in enumerate(bundle.assets):
                if asset.action == "preserve":
                    continue
                self.fault(f"switch:{index}")
                self.fault(f"switch:{asset.asset_type}")
                self._apply(asset)
                transaction.record_write(
                    str(asset.target),
                    asset.old_digest,
                    asset.new_digest,
                    TransactionPhase.SWITCHING,
                )
                self._write_journal(journal, transaction)

            transaction.advance(TransactionPhase.VERIFYING)
            self._write_journal(journal, transaction)
            self.fault("static-doctor")
            static_doctor = DoctorRunner(default_diagnostics()).run(
                DiagnosticContext(
                    filesystem=self.fs,
                    plugin_root=self.plugin_root,
                    codex_home=self.fs.resolve(request.codex_home),
                    vault=self.fs.resolve(request.vault),
                    config_path=self.fs.resolve(request.config_path),
                )
            ).to_dict()
            if static_doctor["errors"]:
                raise RuntimeError(
                    "static Doctor failed: " + "; ".join(static_doctor["errors"])
                )
            transaction.advance(TransactionPhase.COMMITTED)
            self._write_journal(journal, transaction)
            if self.fs.exists(candidate_root):
                self.fs.remove(candidate_root)
            return self._success_result(
                request, transaction, recovery, bundle, static_doctor, plan.to_dict()
            )
        except Exception as exc:
            transaction.record_error(redact_text(f"{type(exc).__name__}: {exc}"))
            recovery_actions = []
            if transaction.actual_writes:
                recovery_actions = RecoveryManager(self.fs).compensate(
                    recovery,
                    transaction.actual_writes,
                    self.fault,
                )
                transaction.recovery_actions.extend(recovery_actions)
                recovered = bool(recovery_actions) and all(
                    action.status == "restored" for action in recovery_actions
                )
                transaction.advance(
                    TransactionPhase.ROLLED_BACK
                    if recovered
                    else TransactionPhase.RECOVERY_REQUIRED
                )
            self._write_journal(journal, transaction)
            return self._failure_result(request, transaction, recovery, bundle, plan)

    def _apply(self, asset: SwitchAsset) -> None:
        target = asset.target
        if self.fs.is_symlink(target):
            raise ValueError(f"managed target cannot be a symlink: {target}")
        if self.fs.is_dir(asset.candidate):
            stage = target.parent / f".xiaoh-stage-{target.name}"
            if self.fs.exists(stage):
                self.fs.remove(stage)
            self.fs.copy(asset.candidate, stage)
            if self.fs.exists(target):
                self.fs.remove(target)
            self.fs.replace(stage, target)
        else:
            self.fs.write_bytes_atomic(target, self.fs.read_bytes(asset.candidate))
        if self.fs.digest(target) != asset.new_digest:
            raise ValueError(f"managed write digest mismatch: {target}")
        if asset.asset_type in {"codex-agent-system", "codex-hooks"}:
            for path in self.fs.iter_files(target):
                if path.suffix in {".py", ".ps1"} and path.name in {
                    "validate.py",
                    "playbook_adapter.py",
                    "block_reserved_root_agent.py",
                    "block_reserved_root_agent.ps1",
                    "guard_vault_writes.py",
                    "guard_task_writes.py",
                    "verify_agent_hook_runtime.py",
                }:
                    self.fs.chmod_executable(path)

    def _write_journal(
        self, journal: Path, transaction: InstallationTransaction
    ) -> None:
        self.fs.write_text_atomic(
            journal,
            json.dumps(
                transaction.to_dict(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )

    def _success_result(
        self,
        request: InstallRequest,
        transaction: InstallationTransaction,
        recovery: RecoveryManifest,
        bundle: CandidateBundle,
        doctor: dict[str, Any],
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema_version": "xiaoh-cli-response/v2",
            "status": "degraded" if bundle.conflicts else "passed",
            "operation": request.operation,
            "version": "4.0.0",
            "transaction_id": transaction.transaction_id,
            "phase": transaction.phase.value,
            "backup": recovery.backup_root,
            "recovery": recovery.to_dict(),
            "recovery_actions": [],
            "activation_state": ActivationState.RUNTIME_UNVERIFIED.value,
            "activation_requirements": ["restart_required", "trust_required", "runtime_doctor_required"],
            "actual_writes": transaction.actual_writes,
            "preserved_assets": bundle.preserved_assets,
            "conflicts": bundle.conflicts,
            "doctor": doctor,
            "plan": plan,
            "errors": [],
            "warnings": [
                *doctor["warnings"],
                *(
                    ["Vault customizations were preserved: " + ", ".join(bundle.conflicts)]
                    if bundle.conflicts
                    else []
                ),
            ],
            "unresolved_items": list(bundle.conflicts),
            "recovery_conditions": [
                "keep the backup until a new-root runtime Doctor verifies activation"
            ],
            "codex_home": str(self.fs.resolve(request.codex_home)),
            "obsidian_vault": str(self.fs.resolve(request.vault)),
            "config": str(self.fs.resolve(request.config_path)),
        }

    def _failure_result(
        self,
        request: InstallRequest,
        transaction: InstallationTransaction,
        recovery: RecoveryManifest,
        bundle: CandidateBundle | None,
        plan: Any,
    ) -> dict[str, Any]:
        activation = (
            ActivationState.RECOVERY_REQUIRED
            if transaction.phase == TransactionPhase.RECOVERY_REQUIRED
            else ActivationState.RUNTIME_UNVERIFIED
        )
        return {
            "schema_version": "xiaoh-cli-response/v2",
            "status": "failed",
            "operation": request.operation,
            "version": "4.0.0",
            "transaction_id": transaction.transaction_id,
            "phase": transaction.phase.value,
            "backup": recovery.backup_root if recovery.complete else None,
            "recovery": recovery.to_dict(),
            "recovery_actions": [
                {
                    "target": action.target,
                    "action": action.action,
                    "expected_digest": action.expected_digest,
                    "restored_digest": action.restored_digest,
                    "status": action.status,
                    "error": action.error,
                }
                for action in transaction.recovery_actions
            ],
            "activation_state": activation.value,
            "actual_writes": transaction.actual_writes,
            "preserved_assets": bundle.preserved_assets if bundle else [],
            "conflicts": bundle.conflicts if bundle else [],
            "plan": plan.to_dict() if plan is not None else None,
            "errors": transaction.errors,
            "warnings": [],
            "unresolved_items": [
                "manual recovery required"
                if activation == ActivationState.RECOVERY_REQUIRED
                else "installation transaction failed"
            ],
            "recovery_conditions": [
                "inspect the transaction and recovery manifests before retrying"
            ],
            "codex_home": str(self.fs.resolve(request.codex_home)),
            "obsidian_vault": str(self.fs.resolve(request.vault)),
            "config": str(self.fs.resolve(request.config_path)),
        }
