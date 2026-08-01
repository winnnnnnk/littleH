"""Data-first domain model for the XiaoH 4.0.0 runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping, Optional, Sequence
from uuid import uuid4


class StringEnum(str, Enum):
    """Python 3.9 compatible string enum."""

    def __str__(self) -> str:
        return self.value


class DiagnosticStatus(StringEnum):
    PASSED = "passed"
    DEGRADED = "degraded"
    FAILED = "failed"
    SKIPPED = "skipped"
    UNVERIFIED = "unverified"


class ActivationState(StringEnum):
    FILES_INSTALLED = "files_installed"
    RESTART_REQUIRED = "restart_required"
    TRUST_REQUIRED = "trust_required"
    RUNTIME_UNVERIFIED = "runtime_unverified"
    VERIFIED = "verified"
    RECOVERY_REQUIRED = "recovery_required"


class TransactionPhase(StringEnum):
    PLANNED = "planned"
    CANDIDATE_VALIDATED = "candidate_validated"
    BACKED_UP = "backed_up"
    SWITCHING = "switching"
    VERIFYING = "verifying"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    RECOVERY_REQUIRED = "recovery_required"


@dataclass(frozen=True)
class AssetChange:
    asset_type: str
    source: str
    target: str
    action: str
    old_digest: Optional[str] = None
    new_digest: Optional[str] = None
    size: int = 0
    reason: Optional[str] = None


@dataclass
class InstallationPlan:
    operation: str
    target_version: str
    codex_home: str
    obsidian_vault: str
    config: str
    source_version: Optional[str] = None
    mode: str = "clean_install"
    assets: list[AssetChange] = field(default_factory=list)
    expected_creates: list[str] = field(default_factory=list)
    expected_overwrites: list[str] = field(default_factory=list)
    expected_deletes: list[str] = field(default_factory=list)
    preserved_assets: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    candidate_requirements: list[str] = field(default_factory=list)
    backup_requirements: list[str] = field(default_factory=list)
    unresolved_items: list[str] = field(default_factory=list)
    recovery_conditions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "failed" if self.errors else ("degraded" if self.conflicts else "passed")

    def to_dict(self) -> dict[str, Any]:
        value = _primitive(asdict(self))
        value.update(
            {
                "schema_version": "xiaoh-installation-plan/v2",
                "status": self.status,
                "paths": {
                    "codex_home": self.codex_home,
                    "obsidian_vault": self.obsidian_vault,
                    "config": self.config,
                },
                "asset_inventory": value["assets"],
                "expected_writes": list(
                    dict.fromkeys(self.expected_creates + self.expected_overwrites)
                ),
                "actual_writes": [],
            }
        )
        return value


@dataclass(frozen=True)
class RecoveryItem:
    asset_type: str
    source: str
    backup_path: str
    restore_target: str
    digest: Optional[str]
    size: int
    existed: bool = True
    complete: bool = False


@dataclass
class RecoveryManifest:
    transaction_id: str
    backup_root: str
    items: list[RecoveryItem] = field(default_factory=list)
    complete: bool = False
    errors: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: _utc_now())

    def to_dict(self) -> dict[str, Any]:
        value = _primitive(asdict(self))
        value.update(
            {
                "schema_version": "xiaoh-recovery-manifest/v2",
                "completeness_status": "complete" if self.complete and not self.errors else "incomplete",
            }
        )
        return value


@dataclass(frozen=True)
class TransactionWrite:
    target: str
    old_digest: Optional[str]
    new_digest: Optional[str]
    phase: TransactionPhase
    result: str = "written"


@dataclass(frozen=True)
class RecoveryAction:
    target: str
    action: str
    expected_digest: Optional[str]
    restored_digest: Optional[str]
    status: str
    error: Optional[str] = None


_ALLOWED_TRANSITIONS: Mapping[TransactionPhase, frozenset[TransactionPhase]] = {
    TransactionPhase.PLANNED: frozenset({TransactionPhase.CANDIDATE_VALIDATED}),
    TransactionPhase.CANDIDATE_VALIDATED: frozenset({TransactionPhase.BACKED_UP}),
    TransactionPhase.BACKED_UP: frozenset(
        {TransactionPhase.SWITCHING, TransactionPhase.ROLLED_BACK}
    ),
    TransactionPhase.SWITCHING: frozenset(
        {
            TransactionPhase.VERIFYING,
            TransactionPhase.ROLLED_BACK,
            TransactionPhase.RECOVERY_REQUIRED,
        }
    ),
    TransactionPhase.VERIFYING: frozenset(
        {
            TransactionPhase.COMMITTED,
            TransactionPhase.ROLLED_BACK,
            TransactionPhase.RECOVERY_REQUIRED,
        }
    ),
    TransactionPhase.COMMITTED: frozenset(),
    TransactionPhase.ROLLED_BACK: frozenset(),
    TransactionPhase.RECOVERY_REQUIRED: frozenset(),
}


@dataclass
class InstallationTransaction:
    transaction_id: str
    operation: str
    phase: TransactionPhase = TransactionPhase.PLANNED
    writes: list[TransactionWrite] = field(default_factory=list)
    recovery_actions: list[RecoveryAction] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    planned_writes: list[str] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: _utc_now())
    updated_at: str = field(default_factory=lambda: _utc_now())
    phase_history: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def new(cls, operation: str) -> "InstallationTransaction":
        started = _utc_now()
        return cls(
            transaction_id=uuid4().hex,
            operation=operation,
            started_at=started,
            updated_at=started,
            phase_history=[{"phase": TransactionPhase.PLANNED.value, "at": started}],
        )

    def advance(self, phase: TransactionPhase) -> None:
        if phase not in _ALLOWED_TRANSITIONS[self.phase]:
            raise ValueError(
                "illegal transaction transition: "
                f"{self.phase.value} -> {phase.value}"
            )
        self.phase = phase
        self.updated_at = _utc_now()
        self.phase_history.append({"phase": phase.value, "at": self.updated_at})

    def record_plan(self, targets: Iterable[str]) -> None:
        self.planned_writes = list(dict.fromkeys(targets))
        self.updated_at = _utc_now()

    def record_error(self, error: str) -> None:
        self.errors.append(error)
        self.updated_at = _utc_now()

    def record_write(
        self,
        target: str,
        old_digest: Optional[str],
        new_digest: Optional[str],
        phase: TransactionPhase,
        result: str = "written",
    ) -> None:
        write = TransactionWrite(target, old_digest, new_digest, phase, result)
        if write not in self.writes:
            self.writes.append(write)
            self.updated_at = _utc_now()

    @property
    def actual_writes(self) -> list[str]:
        return list(dict.fromkeys(item.target for item in self.writes if item.result == "written"))

    def to_dict(self) -> dict[str, Any]:
        value = _primitive(asdict(self))
        value["actual_writes"] = self.actual_writes
        value["schema_version"] = "xiaoh-install-transaction/v2"
        if self.phase == TransactionPhase.COMMITTED:
            value["result"] = "committed"
        elif self.phase == TransactionPhase.ROLLED_BACK:
            value["result"] = "rolled_back"
        elif self.phase == TransactionPhase.RECOVERY_REQUIRED:
            value["result"] = "recovery_required"
        elif self.errors:
            value["result"] = "failed"
        else:
            value["result"] = "in_progress"
        return value


@dataclass
class InstallationReceipt:
    transaction_id: str
    phase: TransactionPhase
    activation_state: ActivationState
    backup: Optional[str]
    actual_writes: list[str]
    recovery: list[RecoveryAction] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _primitive(asdict(self))


@dataclass
class DiagnosticResult:
    diagnostic_id: str
    status: DiagnosticStatus
    facts: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped_reason: Optional[str] = None
    remediation: list[str] = field(default_factory=list)
    runtime_checked: bool = False
    duration_ms: int = 0

    def __post_init__(self) -> None:
        if self.status == DiagnosticStatus.SKIPPED and not self.skipped_reason:
            raise ValueError("skipped diagnostic requires skipped_reason")

    def to_dict(self) -> dict[str, Any]:
        return _primitive(asdict(self))


DEFAULT_ACTIVATION_DIAGNOSTICS: tuple[str, ...] = (
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
)


@dataclass
class DoctorReport:
    status: str
    installation_status: str
    activation_state: ActivationState
    diagnostics: list[DiagnosticResult]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unresolved_items: list[str] = field(default_factory=list)

    @classmethod
    def from_diagnostics(
        cls,
        diagnostics: Iterable[DiagnosticResult],
        installation_status: str,
        required_for_activation: Sequence[str] = DEFAULT_ACTIVATION_DIAGNOSTICS,
    ) -> "DoctorReport":
        items = list(diagnostics)
        errors = [message for item in items for message in item.errors]
        warnings = [message for item in items for message in item.warnings]
        unresolved = [
            item.diagnostic_id
            for item in items
            if item.status
            in {
                DiagnosticStatus.FAILED,
                DiagnosticStatus.SKIPPED,
                DiagnosticStatus.UNVERIFIED,
            }
        ]
        if any(item.status == DiagnosticStatus.FAILED for item in items):
            status = "failed"
        elif any(
            item.status
            in {
                DiagnosticStatus.DEGRADED,
                DiagnosticStatus.SKIPPED,
                DiagnosticStatus.UNVERIFIED,
            }
            for item in items
        ):
            status = "degraded"
        else:
            status = "passed"
        by_id = {item.diagnostic_id: item for item in items}
        activated = bool(required_for_activation) and all(
            diagnostic_id in by_id
            and by_id[diagnostic_id].status == DiagnosticStatus.PASSED
            and by_id[diagnostic_id].runtime_checked
            for diagnostic_id in required_for_activation
        )
        activation = (
            ActivationState.VERIFIED
            if activated
            else ActivationState.RUNTIME_UNVERIFIED
        )
        return cls(
            status=status,
            installation_status=installation_status,
            activation_state=activation,
            diagnostics=items,
            errors=list(dict.fromkeys(errors)),
            warnings=list(dict.fromkeys(warnings)),
            unresolved_items=list(dict.fromkeys(unresolved)),
        )

    def to_dict(self) -> dict[str, Any]:
        effective_status = (
            self.status
            if self.status in {"failed", "degraded"}
            else (
                "passed"
                if self.activation_state == ActivationState.VERIFIED
                else "degraded"
            )
        )
        return {
            "schema_version": "xiaoh-doctor-report/v2",
            "status": self.status,
            "effective_status": effective_status,
            "operation": "doctor",
            "installation_status": self.installation_status,
            "activation_state": self.activation_state.value,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "errors": self.errors,
            "warnings": self.warnings,
            "unresolved_items": self.unresolved_items,
            "actual_writes": [],
            "recovery_conditions": [],
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _primitive(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _primitive(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_primitive(item) for item in value]
    return value
