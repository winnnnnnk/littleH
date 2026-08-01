"""Independent diagnostic execution and aggregation."""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, Optional, Protocol, Sequence

from ..capabilities.skills import SkillGovernance
from ..domain.models import DiagnosticResult, DiagnosticStatus, DoctorReport
from ..ports.protocols import AutomationStorePort, FileSystemPort, ProcessRunnerPort
from ..services.automation import AutomationService
from ..services.configuration import ConfigurationService
from ..services.redaction import redact_mapping, redact_text
from ..services.workspace import WorkspaceService


VERSION = "4.0.0"
REQUIRED_AGENTS = frozenset(
    {
        "frontend_implementer",
        "java_architect",
        "java_code_explorer",
        "java_implementer",
        "pki_domain_expert",
    }
)
REQUIRED_HOOKS = (
    "block_reserved_root_agent.py",
    "block_reserved_root_agent.ps1",
    "guard_vault_writes.py",
    "guard_task_writes.py",
    "verify_agent_hook_runtime.py",
)


@dataclass(frozen=True)
class DiagnosticContext:
    filesystem: FileSystemPort
    plugin_root: Path
    codex_home: Path
    vault: Path
    config_path: Path
    process_runner: Optional[ProcessRunnerPort] = None
    runtime_requested: bool = False
    active_skill_root: Optional[Path] = None
    runtime_facts: Mapping[str, Any] = field(default_factory=dict)
    platform_name: Optional[str] = None
    automation_store: Optional[AutomationStorePort] = None


class Diagnostic(Protocol):
    diagnostic_id: str

    def run(self, context: DiagnosticContext) -> DiagnosticResult: ...


class DoctorRunner:
    def __init__(self, diagnostics: Sequence[Diagnostic]):
        self.diagnostics = tuple(diagnostics)

    def run(self, context: DiagnosticContext) -> DoctorReport:
        results: list[DiagnosticResult] = []
        for diagnostic in self.diagnostics:
            started = time.monotonic()
            try:
                result = diagnostic.run(context)
            except Exception as exc:
                result = DiagnosticResult(
                    diagnostic_id=diagnostic.diagnostic_id,
                    status=DiagnosticStatus.FAILED,
                    errors=[redact_text(f"{type(exc).__name__}: {exc}")],
                    remediation=["repair this diagnostic input, then run Doctor once"],
                    runtime_checked=context.runtime_requested,
                )
            duration = max(0, int((time.monotonic() - started) * 1000))
            results.append(replace(result, duration_ms=duration))
        return DoctorReport.from_diagnostics(
            results,
            installation_status=_installation_status(context),
        )


def default_diagnostics() -> tuple[Diagnostic, ...]:
    return (
        PluginDiagnostic(),
        SkillGovernanceDiagnostic(),
        LoadedSkillDiagnostic(),
        ManagedRuntimeDiagnostic(),
        AgentDiagnostic(),
        HookDiagnostic(),
        ValidatorDiagnostic(),
        VaultDiagnostic(),
        WorkspaceDiagnostic(),
        AutomationDiagnostic(),
        PlaybookDiagnostic(),
    )


class PluginDiagnostic:
    diagnostic_id = "plugin"

    def run(self, context: DiagnosticContext) -> DiagnosticResult:
        plugin_manifest = _json_object(
            context, context.plugin_root / ".codex-plugin/plugin.json"
        )
        install_manifest = _json_object(
            context, context.plugin_root / "install-manifest.json"
        )
        dependencies = _json_object(
            context, context.plugin_root / "dependencies.json"
        )
        versions = {
            "plugin": plugin_manifest.get("version"),
            "install": install_manifest.get("version"),
        }
        errors = [
            f"{name} manifest version is {version!r}, expected {VERSION}"
            for name, version in versions.items()
            if version != VERSION
        ]
        if install_manifest.get("schema_version") != "xiaoh-install-manifest/v2":
            errors.append("install manifest schema is not supported")
        install_skills = install_manifest.get("bundled_skills")
        dependency_skills = dependencies.get("bundled_skills")
        if install_skills != dependency_skills:
            errors.append("install manifest and dependency Skill inventories differ")
        manifest_agents = install_manifest.get("managed_agents")
        if set(manifest_agents or []) != REQUIRED_AGENTS:
            errors.append("install manifest does not declare the exact five managed Agents")
        facts = {
            "candidate_version": VERSION,
            "manifest_versions": versions,
            "bundled_skill_count": len(install_skills) if isinstance(install_skills, list) else None,
            "managed_agent_count": len(manifest_agents) if isinstance(manifest_agents, list) else None,
        }
        if context.runtime_requested:
            active = context.runtime_facts.get("active_plugin")
            if not isinstance(active, dict):
                return DiagnosticResult(
                    self.diagnostic_id,
                    DiagnosticStatus.UNVERIFIED,
                    facts=facts,
                    errors=errors,
                    warnings=["current-process plugin facts are unavailable"],
                    remediation=["restart Codex and provide current plugin facts"],
                    runtime_checked=True,
                )
            facts["active_plugin"] = redact_mapping(active)
            if active.get("version") != VERSION:
                errors.append("current process did not load XiaoH 4.0.0")
        return DiagnosticResult(
            self.diagnostic_id,
            DiagnosticStatus.FAILED if errors else DiagnosticStatus.PASSED,
            facts=facts,
            errors=errors,
            remediation=["synchronize the plugin manifests"] if errors else [],
            runtime_checked=context.runtime_requested,
        )


class SkillGovernanceDiagnostic:
    diagnostic_id = "skill-governance"

    def run(self, context: DiagnosticContext) -> DiagnosticResult:
        report = SkillGovernance(context.filesystem, context.plugin_root).validate()
        report_status = report.get("status")
        status = {
            "passed": DiagnosticStatus.PASSED,
            "degraded": DiagnosticStatus.DEGRADED,
            "failed": DiagnosticStatus.FAILED,
        }.get(report_status if isinstance(report_status, str) else "", DiagnosticStatus.FAILED)
        return DiagnosticResult(
            self.diagnostic_id,
            status,
            facts={
                "decision_counts": report.get("decision_counts", {}),
                "audited_skills": report.get("audited_skills", []),
            },
            errors=report.get("errors", []),
            warnings=report.get("warnings", []),
            remediation=["repair Skill source or quality drift"]
            if status == DiagnosticStatus.FAILED
            else [],
            runtime_checked=context.runtime_requested,
        )


class LoadedSkillDiagnostic:
    diagnostic_id = "loaded-skill"

    def run(self, context: DiagnosticContext) -> DiagnosticResult:
        if context.active_skill_root is None:
            return DiagnosticResult(
                self.diagnostic_id,
                DiagnosticStatus.UNVERIFIED,
                facts={"root": None},
                warnings=["current loaded Skill root is unavailable"],
                remediation=["run Doctor from a new root task and pass the active Skill root"],
                runtime_checked=context.runtime_requested,
            )
        root = context.filesystem.resolve(context.active_skill_root)
        manifest = _find_plugin_manifest(context, root)
        if manifest is None:
            return DiagnosticResult(
                self.diagnostic_id,
                DiagnosticStatus.FAILED,
                facts={"root": str(root)},
                errors=["loaded Skill root has no parent plugin manifest"],
                remediation=["load the Skill from the installed XiaoH plugin"],
                runtime_checked=context.runtime_requested,
            )
        value = _json_object(context, manifest)
        version = value.get("version")
        errors = [] if version == VERSION else [f"loaded Skill version is {version!r}, expected {VERSION}"]
        return DiagnosticResult(
            self.diagnostic_id,
            DiagnosticStatus.FAILED if errors else DiagnosticStatus.PASSED,
            facts={"root": str(root), "version": version},
            errors=errors,
            remediation=["restart into the XiaoH 4.0.0 Skill"] if errors else [],
            runtime_checked=context.runtime_requested,
        )


class ManagedRuntimeDiagnostic:
    diagnostic_id = "managed-runtime"

    def run(self, context: DiagnosticContext) -> DiagnosticResult:
        manifest = _json_object(context, context.plugin_root / "install-manifest.json")
        directories = manifest.get("managed_runtime_directories", [])
        if not isinstance(directories, list):
            raise ValueError("managed_runtime_directories must be a list")
        missing: list[str] = []
        symlinks: list[str] = []
        checked = 0
        for directory in directories:
            if not isinstance(directory, str):
                raise ValueError("managed runtime directory must be a string")
            source = context.plugin_root / "runtime/codex" / directory
            target = context.codex_home / directory
            if context.filesystem.is_symlink(target):
                symlinks.append(str(target))
                continue
            for source_file in context.filesystem.iter_files(source):
                checked += 1
                target_file = target / source_file.relative_to(source)
                if not context.filesystem.is_file(target_file):
                    missing.append(str(target_file))
        errors = [*(f"unsafe managed symlink: {path}" for path in symlinks)]
        if missing:
            errors.append(f"{len(missing)} managed runtime files are missing")
        return DiagnosticResult(
            self.diagnostic_id,
            DiagnosticStatus.FAILED if errors else DiagnosticStatus.PASSED,
            facts={"checked_files": checked, "missing_files": missing, "symlinks": symlinks},
            errors=errors,
            remediation=["run an authorized XiaoH setup or update transaction"] if errors else [],
            runtime_checked=context.runtime_requested,
        )


class AgentDiagnostic:
    diagnostic_id = "agents"

    def run(self, context: DiagnosticContext) -> DiagnosticResult:
        agents_root = context.codex_home / "agents"
        actual = {
            path.stem
            for path in context.filesystem.iter_children(agents_root)
            if path.suffix == ".toml" and context.filesystem.is_file(path)
        }
        errors: list[str] = []
        warnings: list[str] = []
        if "xiaoh" in actual:
            errors.append("reserved root identity xiaoh is registered as a child Agent")
        missing = sorted(REQUIRED_AGENTS - actual)
        if missing:
            errors.append("missing managed Agents: " + ", ".join(missing))
        unexpected = sorted(actual - REQUIRED_AGENTS)
        if unexpected:
            warnings.append("preserved custom Agents: " + ", ".join(unexpected))
        return DiagnosticResult(
            self.diagnostic_id,
            DiagnosticStatus.FAILED if errors else (DiagnosticStatus.DEGRADED if warnings else DiagnosticStatus.PASSED),
            facts={"managed_agents": sorted(actual & REQUIRED_AGENTS), "custom_agents": unexpected},
            errors=errors,
            warnings=warnings,
            remediation=["restore the exact five-Agent managed inventory"] if errors else [],
            runtime_checked=context.runtime_requested,
        )


class HookDiagnostic:
    diagnostic_id = "hooks"

    def run(self, context: DiagnosticContext) -> DiagnosticResult:
        missing = [
            name
            for name in REQUIRED_HOOKS
            if not context.filesystem.is_file(context.codex_home / "hooks" / name)
        ]
        config_path = context.codex_home / "config.toml"
        config = context.filesystem.read_text(config_path) if context.filesystem.is_file(config_path) else ""
        if "# xiaoh-root-agent-hook:start" not in config:
            missing.append("config.toml:xiaoh-root-agent-hook")
        errors = ["missing Hook assets: " + ", ".join(missing)] if missing else []
        facts: dict[str, Any] = {"missing": missing, "trust": "not_checked"}
        if context.runtime_requested and not errors:
            trust = context.runtime_facts.get("hooks_trusted")
            if trust is not True and context.process_runner is not None:
                verifier = context.codex_home / "hooks/verify_agent_hook_runtime.py"
                result = context.process_runner.run(
                    [
                        sys.executable,
                        str(verifier),
                        "--codex-home",
                        str(context.codex_home),
                        "--cwd",
                        str(context.plugin_root),
                    ]
                )
                trust = result.returncode == 0
                facts["runtime_probe_returncode"] = result.returncode
                if result.stdout.strip():
                    facts["runtime_probe"] = redact_text(result.stdout.strip(), limit=200)
            facts["trust"] = trust
            if trust is not True:
                return DiagnosticResult(
                    self.diagnostic_id,
                    DiagnosticStatus.UNVERIFIED,
                    facts=facts,
                    warnings=["current Hook trust evidence is unavailable or untrusted"],
                    remediation=["trust the XiaoH Hooks manually, then open a new root task"],
                    runtime_checked=True,
                )
        return DiagnosticResult(
            self.diagnostic_id,
            DiagnosticStatus.FAILED if errors else DiagnosticStatus.PASSED,
            facts=facts,
            errors=errors,
            remediation=["restore Hook files and the managed config block"] if errors else [],
            runtime_checked=context.runtime_requested,
        )


class ValidatorDiagnostic:
    diagnostic_id = "validator"

    def run(self, context: DiagnosticContext) -> DiagnosticResult:
        entrypoint = context.codex_home / "agent-system/validate.py"
        if not context.filesystem.is_file(entrypoint):
            return DiagnosticResult(
                self.diagnostic_id,
                DiagnosticStatus.FAILED,
                facts={"entrypoint": str(entrypoint)},
                errors=["Validator entrypoint is missing"],
                remediation=["restore the managed Validator package"],
                runtime_checked=context.runtime_requested,
            )
        if context.process_runner is None:
            return DiagnosticResult(
                self.diagnostic_id,
                DiagnosticStatus.PASSED,
                facts={"entrypoint": str(entrypoint), "self_test": "not_requested"},
                runtime_checked=context.runtime_requested,
            )
        result = context.process_runner.run([sys.executable, str(entrypoint), "--self-test"])
        errors = [] if result.returncode == 0 else [
            "Validator self-test failed: "
            + redact_text((result.stderr or result.stdout).strip(), limit=200)
        ]
        return DiagnosticResult(
            self.diagnostic_id,
            DiagnosticStatus.FAILED if errors else DiagnosticStatus.PASSED,
            facts={"entrypoint": str(entrypoint), "returncode": result.returncode},
            errors=errors,
            remediation=["repair the Validator contract failure"] if errors else [],
            runtime_checked=context.runtime_requested,
        )


class VaultDiagnostic:
    diagnostic_id = "vault"

    def run(self, context: DiagnosticContext) -> DiagnosticResult:
        errors: list[str] = []
        if not context.filesystem.is_dir(context.vault / ".obsidian"):
            errors.append(f"not an Obsidian Vault: {context.vault}")
        required = (
            "90-个人系统/Agent协作角色.md",
            "90-个人系统/Agent进化台账.md",
        )
        missing = [name for name in required if not context.filesystem.is_file(context.vault / name)]
        if missing:
            errors.append("missing Vault runtime files: " + ", ".join(missing))
        return DiagnosticResult(
            self.diagnostic_id,
            DiagnosticStatus.FAILED if errors else DiagnosticStatus.PASSED,
            facts={"root": str(context.filesystem.resolve(context.vault)), "missing": missing},
            errors=errors,
            remediation=["select the configured real Vault or restore managed templates"] if errors else [],
            runtime_checked=context.runtime_requested,
        )


class WorkspaceDiagnostic:
    diagnostic_id = "workspace"

    def run(self, context: DiagnosticContext) -> DiagnosticResult:
        config = ConfigurationService(context.filesystem).load(context.config_path, missing_ok=True)
        report = WorkspaceService(context.platform_name).report(config)
        return DiagnosticResult(
            self.diagnostic_id,
            DiagnosticStatus.FAILED if report["errors"] else (DiagnosticStatus.DEGRADED if report["warnings"] else DiagnosticStatus.PASSED),
            facts={"workspace_count": len(report["workspaces"])},
            errors=report["errors"],
            warnings=report["warnings"],
            remediation=["repair conflicting Workspace roots"] if report["errors"] else [],
            runtime_checked=context.runtime_requested,
        )


class AutomationDiagnostic:
    diagnostic_id = "automation"

    def run(self, context: DiagnosticContext) -> DiagnosticResult:
        config = ConfigurationService(context.filesystem).load(context.config_path, missing_ok=True)
        manifest = _json_object(context, context.plugin_root / "managed-automations.json")
        templates = manifest.get("templates", [])
        required = []
        for item in templates:
            if not isinstance(item, dict) or not item.get("required", True):
                continue
            logical_id = item.get("logical_id")
            if isinstance(logical_id, str):
                required.append(logical_id)
        bindings = config.get("automation_bindings", {})
        if not isinstance(bindings, dict):
            bindings = {}
        missing = [item for item in required if item not in bindings]
        if context.runtime_requested and context.automation_store is not None:
            report = AutomationService(
                context.filesystem, context.plugin_root
            ).report(config, context.automation_store)
            return DiagnosticResult(
                self.diagnostic_id,
                DiagnosticStatus.DEGRADED
                if report["status"] == "degraded"
                else DiagnosticStatus.PASSED,
                facts={"required": required, "tasks": report["tasks"]},
                warnings=report["warnings"],
                remediation=(
                    ["repair or rebind the affected automation identity"]
                    if report["warnings"]
                    else []
                ),
                runtime_checked=True,
            )
        if missing:
            return DiagnosticResult(
                self.diagnostic_id,
                DiagnosticStatus.DEGRADED,
                facts={"required": required, "missing": missing},
                warnings=["required automation identities are not bound: " + ", ".join(missing)],
                remediation=["bind automation through the supported automation store"],
                runtime_checked=context.runtime_requested,
            )
        if context.runtime_requested:
            return DiagnosticResult(
                self.diagnostic_id,
                DiagnosticStatus.UNVERIFIED,
                facts={"required": required, "missing": []},
                warnings=["automation runtime readback adapter is unavailable"],
                remediation=["run Doctor with the supported automation store adapter"],
                runtime_checked=False,
            )
        return DiagnosticResult(
            self.diagnostic_id,
            DiagnosticStatus.PASSED,
            facts={"required": required, "missing": []},
            runtime_checked=context.runtime_requested,
        )


class PlaybookDiagnostic:
    diagnostic_id = "playbook"

    def run(self, context: DiagnosticContext) -> DiagnosticResult:
        config = ConfigurationService(context.filesystem).load(context.config_path, missing_ok=True)
        integrations = config.get("integrations", {})
        mode = integrations.get("playbook", "auto") if isinstance(integrations, dict) else "invalid"
        if mode in {False, "disabled", "auto"}:
            return DiagnosticResult(
                self.diagnostic_id,
                DiagnosticStatus.PASSED,
                facts={"mode": "disabled" if mode in {False, "disabled"} else "auto_not_managed"},
                runtime_checked=context.runtime_requested,
            )
        if mode not in {True, "enabled"}:
            return DiagnosticResult(
                self.diagnostic_id,
                DiagnosticStatus.FAILED,
                facts={"mode": mode},
                errors=["invalid integrations.playbook mode"],
                remediation=["set Playbook integration to auto, enabled, or disabled"],
                runtime_checked=context.runtime_requested,
            )
        if context.process_runner is None:
            return DiagnosticResult(
                self.diagnostic_id,
                DiagnosticStatus.UNVERIFIED,
                facts={
                    "mode": "enabled",
                    "commands": ["playbook --version", "playbook version check"],
                },
                warnings=["Playbook read-only version evidence is unavailable"],
                remediation=["run the two read-only Playbook version checks manually"],
                runtime_checked=context.runtime_requested,
            )
        version = context.process_runner.run(["playbook", "--version"])
        compatibility = context.process_runner.run(["playbook", "version", "check"])
        errors = []
        if version.returncode != 0:
            errors.append("Playbook --version failed")
        if compatibility.returncode != 0:
            errors.append("Playbook version check failed")
        return DiagnosticResult(
            self.diagnostic_id,
            DiagnosticStatus.FAILED if errors else DiagnosticStatus.PASSED,
            facts={
                "mode": "enabled",
                "version_output": redact_text(version.stdout.strip(), limit=200),
                "version_check_output": redact_text(
                    compatibility.stdout.strip(), limit=200
                ),
            },
            errors=errors,
            remediation=["maintain the Playbook CLI manually"] if errors else [],
            runtime_checked=context.runtime_requested,
        )


def _json_object(context: DiagnosticContext, path: Path) -> dict[str, Any]:
    try:
        value = json.loads(context.filesystem.read_text(path))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON document: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON document must be an object: {path}")
    return value


def _find_plugin_manifest(context: DiagnosticContext, root: Path) -> Optional[Path]:
    for candidate in (root, *root.parents):
        manifest = candidate / ".codex-plugin/plugin.json"
        if context.filesystem.is_file(manifest):
            return manifest
    return None


def _installation_status(context: DiagnosticContext) -> str:
    try:
        config = ConfigurationService(context.filesystem).load(
            context.config_path, missing_ok=True
        )
    except ValueError:
        return "invalid_configuration"
    return "files_installed" if config.get("installed_version") == VERSION else "not_installed"
