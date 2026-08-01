"""Read-only installation planning."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..domain.models import AssetChange, InstallationPlan
from ..ports.protocols import FileSystemPort


RUNTIME_VERSION = "4.0.1"
INSTALL_MANIFEST_SCHEMA = "xiaoh-install-manifest/v3"
MANAGED_RUNTIME_STATE_SCHEMA = "xiaoh-managed-runtime/v1"
MANAGED_ROOT_FILES = (
    ("runtime/codex/AGENTS.md", "AGENTS.md", "contract"),
    ("runtime/codex/root-agent-hook.toml", "config.toml", "hook-config"),
)


class InstallationPlanner:
    def __init__(self, filesystem: FileSystemPort, plugin_root: Path):
        self.fs = filesystem
        self.plugin_root = self.fs.resolve(plugin_root)

    def create_plan(
        self,
        operation: str,
        codex_home: Path,
        vault: Path,
        config_path: Path,
    ) -> InstallationPlan:
        codex = self.fs.resolve(codex_home)
        vault_root = self.fs.resolve(vault)
        config = self.fs.resolve(config_path)
        manifest = self._load_manifest()
        source_version = self._installed_version(config)
        plan = InstallationPlan(
            operation=operation,
            target_version=RUNTIME_VERSION,
            source_version=source_version,
            mode="same_version_sync" if source_version == RUNTIME_VERSION else "clean_install",
            codex_home=str(codex),
            obsidian_vault=str(vault_root),
            config=str(config),
            candidate_requirements=[
                "manifest and managed digests valid",
                "all managed paths remain inside candidate roots",
                "no unresolved placeholders",
                "candidate source is independent from the active loaded cache",
            ],
            backup_requirements=[
                "every changed existing target has a verified backup item",
                "backup paths remain inside the transaction backup root",
                "available space covers the complete recovery set",
            ],
            recovery_conditions=[
                "a failure after the first managed write triggers reverse-order compensation",
                "rolled_back is reported only after restored digests match",
            ],
        )
        for directory in manifest["managed_runtime_directories"]:
            source_root = self._safe_source(Path("runtime/codex") / directory)
            target_root = _safe_target(codex, Path(directory), "Codex managed directory")
            self._classify_tree(plan, source_root, target_root, f"codex-{directory}")
        current_files = self._managed_runtime_files(manifest)
        for relative in sorted(self._previous_managed_files(codex, manifest) - current_files):
            target = _safe_target(codex, Path(relative), "retired managed runtime")
            if self.fs.exists(target):
                plan.assets.append(
                    AssetChange(
                        "retired-managed-runtime",
                        "managed inventory",
                        str(target),
                        "delete",
                        old_digest=self.fs.digest(target),
                    )
                )
                _record_action(plan, str(target), "delete")
        state_target = _safe_target(
            codex, Path(".xiaoh-managed-runtime.json"), "managed runtime state"
        )
        state_action = "overwrite" if self.fs.exists(state_target) else "create"
        plan.assets.append(
            AssetChange("managed-runtime-state", "generated", str(state_target), state_action)
        )
        _record_action(plan, str(state_target), state_action)
        for source_relative, target_relative, asset_type in MANAGED_ROOT_FILES:
            source = self._safe_source(Path(source_relative))
            target = _safe_target(codex, Path(target_relative), "Codex managed file")
            self._classify_file(plan, source, target, asset_type)
        vault_source = self._safe_source(Path("runtime/obsidian/development-vault"))
        self._classify_tree(plan, vault_source, vault_root, "vault-template")
        config_action = "overwrite" if self.fs.exists(config) else "create"
        plan.assets.append(
            AssetChange("configuration", "generated", str(config), config_action)
        )
        _record_action(plan, str(config), config_action)
        self._preserve_custom_agents(plan, codex, set(manifest["managed_agents"]))
        return plan

    def _load_manifest(self) -> dict[str, Any]:
        path = self._safe_source(Path("install-manifest.json"))
        value = json.loads(self.fs.read_text(path))
        if not isinstance(value, dict):
            raise ValueError("install manifest must be a JSON object")
        if value.get("schema_version") != INSTALL_MANIFEST_SCHEMA:
            raise ValueError("install manifest schema is not supported")
        if value.get("version") != RUNTIME_VERSION:
            raise ValueError("install manifest version is not supported")
        for key in (
            "managed_runtime_directories",
            "previous_managed_runtime_directories",
            "managed_agents",
            "previous_managed_runtime_files",
        ):
            if not isinstance(value.get(key), list):
                raise ValueError(f"install manifest {key} must be a list")
        return value

    def _managed_runtime_files(self, manifest: dict[str, Any]) -> set[str]:
        files: set[str] = set()
        for directory in manifest["managed_runtime_directories"]:
            source = self._safe_source(Path("runtime/codex") / directory)
            for path in self.fs.iter_files(source):
                files.add((Path(directory) / path.relative_to(source)).as_posix())
        return files

    def _previous_managed_files(
        self, codex: Path, manifest: dict[str, Any]
    ) -> set[str]:
        values: Any = manifest["previous_managed_runtime_files"]
        state_path = codex / ".xiaoh-managed-runtime.json"
        if self.fs.is_file(state_path):
            try:
                state = json.loads(self.fs.read_text(state_path))
            except (OSError, UnicodeError, json.JSONDecodeError):
                state = None
            if (
                isinstance(state, dict)
                and state.get("schema_version") == MANAGED_RUNTIME_STATE_SCHEMA
            ):
                values = state.get("managed_files")
        if not isinstance(values, list):
            raise ValueError("managed runtime inventory must be a list")
        result: set[str] = set()
        allowed_roots = set(manifest["managed_runtime_directories"]) | set(
            manifest["previous_managed_runtime_directories"]
        )
        for value in values:
            relative = Path(str(value))
            if (
                not isinstance(value, str)
                or not value.strip()
                or relative.is_absolute()
                or ".." in relative.parts
            ):
                raise ValueError("managed runtime inventory contains an unsafe path")
            if not relative.parts or relative.parts[0] not in allowed_roots:
                raise ValueError("managed runtime inventory is outside declared directories")
            result.add(relative.as_posix())
        return result

    def _installed_version(self, config: Path) -> str | None:
        if not self.fs.is_file(config):
            return None
        try:
            value = json.loads(self.fs.read_text(config))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        version = value.get("installed_version") if isinstance(value, dict) else None
        return version if isinstance(version, str) else None

    def _classify_tree(
        self,
        plan: InstallationPlan,
        source_root: Path,
        target_root: Path,
        asset_type: str,
    ) -> None:
        for source in self.fs.iter_files(source_root):
            relative = source.relative_to(source_root)
            target = _safe_target(target_root, relative, asset_type)
            self._classify_file(plan, source, target, asset_type)

    def _classify_file(
        self,
        plan: InstallationPlan,
        source: Path,
        target: Path,
        asset_type: str,
    ) -> None:
        source_digest = self.fs.digest(source)
        target_digest = self.fs.digest(target)
        if target_digest is None:
            action = "create"
        elif target_digest == source_digest:
            action = "preserve"
        else:
            action = "overwrite"
        plan.assets.append(
            AssetChange(
                asset_type=asset_type,
                source=str(source),
                target=str(target),
                action=action,
                old_digest=target_digest,
                new_digest=source_digest,
                size=self.fs.size(source),
            )
        )
        _record_action(plan, str(target), action)

    def _preserve_custom_agents(
        self, plan: InstallationPlan, codex: Path, managed_agents: set[str]
    ) -> None:
        agents = codex / "agents"
        for path in self.fs.iter_children(agents):
            if path.suffix == ".toml" and path.stem not in managed_agents:
                plan.preserved_assets.append(str(path))

    def _safe_source(self, relative: Path) -> Path:
        return _safe_target(self.plugin_root, relative, "plugin source")


def _safe_target(root: Path, relative: Path, label: str) -> Path:
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{label} escapes its root: {relative}")
    root_resolved = root.resolve(strict=False)
    target = root / relative
    target_resolved = target.resolve(strict=False)
    try:
        target_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"{label} escapes its root: {target}") from exc
    current = root
    for part in relative.parts:
        if current.is_symlink():
            raise ValueError(f"{label} contains a symlink: {current}")
        current = current / part
    if current.is_symlink():
        raise ValueError(f"{label} contains a symlink: {current}")
    return target


def _record_action(plan: InstallationPlan, target: str, action: str) -> None:
    if action == "create":
        plan.expected_creates.append(target)
    elif action == "overwrite":
        plan.expected_overwrites.append(target)
        plan.backup_requirements.append(f"backup existing target: {target}")
    elif action == "delete":
        plan.expected_deletes.append(target)
        plan.backup_requirements.append(f"backup existing target: {target}")
    else:
        plan.preserved_assets.append(target)
