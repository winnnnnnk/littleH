"""One application boundary for each public runtime use case."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from ..capabilities.skills import SkillGovernance
from ..diagnostics.doctor import DiagnosticContext, DoctorRunner, default_diagnostics
from ..installation.planner import InstallationPlanner
from ..installation.transaction import InstallRequest, TransactionalInstaller
from ..ports.protocols import (
    AutomationStorePort,
    ClockPort,
    FileSystemPort,
    PluginFactsPort,
    ProcessRunnerPort,
)
from ..services.automation import AutomationService
from ..services.configuration import ConfigurationService
from ..services.workspace import WorkspaceService


@dataclass(frozen=True)
class RuntimePaths:
    codex_home: Path
    vault: Path
    config: Path


class RuntimeApplication:
    def __init__(
        self,
        filesystem: FileSystemPort,
        clock: ClockPort,
        plugin_root: Path,
        process_runner: Optional[ProcessRunnerPort] = None,
        automation_store_factory: Optional[
            Callable[[FileSystemPort, Path], AutomationStorePort]
        ] = None,
        plugin_facts: Optional[PluginFactsPort] = None,
    ):
        self.fs = filesystem
        self.clock = clock
        self.plugin_root = filesystem.resolve(plugin_root)
        self.process_runner = process_runner
        self.automation_store_factory = automation_store_factory
        self.plugin_facts = plugin_facts

    def plan(self, operation: str, paths: RuntimePaths) -> dict[str, Any]:
        return InstallationPlanner(self.fs, self.plugin_root).create_plan(
            operation, paths.codex_home, paths.vault, paths.config
        ).to_dict()

    def install(self, operation: str, paths: RuntimePaths, user_home: Path) -> dict[str, Any]:
        root = self.fs.resolve(paths.config).parent.parent
        request = InstallRequest(
            operation=operation,
            root=root,
            codex_home=paths.codex_home,
            vault=paths.vault,
            config_path=paths.config,
            user_home=user_home,
        )
        return TransactionalInstaller(self.fs, self.clock, self.plugin_root).execute(request)

    def doctor(
        self,
        paths: RuntimePaths,
        runtime_requested: bool,
        active_skill_root: Optional[Path],
    ) -> dict[str, Any]:
        runtime_facts = self._runtime_facts(active_skill_root)
        report = DoctorRunner(default_diagnostics()).run(
            DiagnosticContext(
                filesystem=self.fs,
                plugin_root=self.plugin_root,
                codex_home=self.fs.resolve(paths.codex_home),
                vault=self.fs.resolve(paths.vault),
                config_path=self.fs.resolve(paths.config),
                process_runner=self.process_runner if runtime_requested else None,
                runtime_requested=runtime_requested,
                active_skill_root=active_skill_root,
                runtime_facts=runtime_facts,
                automation_store=(
                    self.automation_store_factory(self.fs, paths.codex_home)
                    if runtime_requested and self.automation_store_factory is not None
                    else None
                ),
            )
        ).to_dict()
        report.update(
            {
                "codex_home": str(self.fs.resolve(paths.codex_home)),
                "obsidian_vault": str(self.fs.resolve(paths.vault)),
                "config": str(self.fs.resolve(paths.config)),
            }
        )
        return report

    def _runtime_facts(self, active_skill_root: Optional[Path]) -> dict[str, Any]:
        if active_skill_root is None:
            return {}
        current = self.fs.resolve(active_skill_root)
        for parent in (current, *current.parents):
            manifest = parent / ".codex-plugin/plugin.json"
            if self.fs.is_file(manifest):
                value = self._json_object(manifest)
                return {
                    "active_plugin": {
                        "name": value.get("name"),
                        "version": value.get("version"),
                        "root": str(parent),
                    }
                }
        return {}

    def companions(
        self, install_requested: bool = False, runtime_requested: bool = False
    ) -> dict[str, Any]:
        if install_requested:
            return {
                "status": "failed",
                "operation": "companions",
                "errors": [
                    "XiaoH 4.0.1 does not install plugins or external capabilities; use their owning installer manually"
                ],
                "warnings": [],
            }
        dependencies = self._json_object(self.plugin_root / "dependencies.json")
        missing = [
            name
            for name in dependencies.get("bundled_skills", [])
            if not self.fs.is_file(self.plugin_root / "skills" / name / "SKILL.md")
        ]
        governance = SkillGovernance(self.fs, self.plugin_root).validate()
        errors = ["missing bundled Skills: " + ", ".join(missing)] if missing else []
        errors.extend(governance["errors"])
        plugin_facts = {"status": "not_checked", "plugins": []}
        if runtime_requested:
            plugin_facts = (
                dict(self.plugin_facts.current_facts())
                if self.plugin_facts is not None
                else {
                    "status": "unavailable",
                    "plugins": [],
                    "warning": "Codex plugin facts adapter is unavailable",
                }
            )
        warnings = list(governance["warnings"])
        warning = plugin_facts.get("warning")
        if isinstance(warning, str):
            warnings.append(warning)
        return {
            "status": "failed" if errors else ("degraded" if warnings else "passed"),
            "operation": "companions",
            "version": "4.0.1",
            "bundled_skills": dependencies.get("bundled_skills", []),
            "codex_plugins": dependencies.get("codex_plugins", []),
            "external_capabilities": dependencies.get("external_capabilities", []),
            "skill_governance": governance,
            "plugin_facts": plugin_facts,
            "errors": list(dict.fromkeys(errors)),
            "warnings": list(dict.fromkeys(warnings)),
        }

    def resolve_workspace(self, paths: RuntimePaths, requested: Path) -> dict[str, Any]:
        local = ConfigurationService(self.fs).load(paths.config, missing_ok=True)
        result = WorkspaceService().resolve(local, requested)
        return {
            **result,
            "status": "failed" if result["status"] == "conflict" else "passed",
            "resolution": result["status"],
            "operation": "resolve-workspace",
            "codex_home": str(self.fs.resolve(paths.codex_home)),
            "obsidian_vault": str(self.fs.resolve(paths.vault)),
            "config": str(self.fs.resolve(paths.config)),
            "errors": result.get("errors", []),
            "warnings": result.get("warnings", []),
        }

    def register_workspace(
        self,
        paths: RuntimePaths,
        workspace_id: str,
        project: str,
        system: str,
        root: Path,
    ) -> dict[str, Any]:
        configuration = ConfigurationService(self.fs)
        local = configuration.load(paths.config, missing_ok=True)
        if not local:
            local = configuration.merged_runtime_config(
                {}, paths.codex_home, paths.vault, "4.0.1"
            )
        updated = WorkspaceService().register(
            local, workspace_id, project, system, root
        )
        configuration.write(
            paths.config,
            updated,
            backup_path=paths.config.with_suffix(paths.config.suffix + ".bak"),
        )
        return {
            "status": "passed",
            "operation": "register-workspace",
            "workspace_id": workspace_id,
            "workspace": updated["workspaces"][workspace_id],
            "codex_home": str(self.fs.resolve(paths.codex_home)),
            "obsidian_vault": str(self.fs.resolve(paths.vault)),
            "config": str(self.fs.resolve(paths.config)),
            "actual_writes": [str(self.fs.resolve(paths.config))],
            "errors": [],
            "warnings": [],
        }

    def bind_automation(
        self,
        paths: RuntimePaths,
        logical_id: str,
        task_id: str,
    ) -> dict[str, Any]:
        if self.automation_store_factory is None:
            raise RuntimeError("automation store adapter is unavailable")
        facts = AutomationService(self.fs, self.plugin_root).bind_existing(
            paths.config,
            logical_id,
            task_id,
            self.automation_store_factory(self.fs, paths.codex_home),
        )
        return {
            "status": "passed",
            "operation": "bind-automation",
            **facts,
            "codex_home": str(self.fs.resolve(paths.codex_home)),
            "obsidian_vault": str(self.fs.resolve(paths.vault)),
            "config": str(self.fs.resolve(paths.config)),
            "actual_writes": facts.get("actual_writes", []),
            "errors": [],
            "warnings": [],
        }

    def _json_object(self, path: Path) -> dict[str, Any]:
        value = json.loads(self.fs.read_text(path))
        if not isinstance(value, dict):
            raise ValueError(f"JSON document must be an object: {path}")
        return value
