"""Isolated candidate rendering and validation."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ..ports.protocols import FileSystemPort
from ..services.configuration import ConfigurationService
from ..services.vault import VaultService


TEXT_EXTENSIONS = {".md", ".toml", ".json", ".py", ".js", ".yaml", ".yml", ".txt"}
INSTALL_MANIFEST_SCHEMA = "xiaoh-install-manifest/v3"
MANAGED_RUNTIME_STATE_SCHEMA = "xiaoh-managed-runtime/v1"


@dataclass(frozen=True)
class SwitchAsset:
    candidate: Path
    target: Path
    asset_type: str
    action: str
    old_digest: str | None
    new_digest: str | None


@dataclass
class CandidateBundle:
    root: Path
    assets: list[SwitchAsset]
    manifest_path: Path
    preserved_assets: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


class CandidateBuilder:
    def __init__(self, filesystem: FileSystemPort, plugin_root: Path):
        self.fs = filesystem
        self.plugin_root = filesystem.resolve(plugin_root)

    def build(
        self,
        transaction_id: str,
        candidate_root: Path,
        codex_home: Path,
        vault: Path,
        config_path: Path,
        user_home: Path,
    ) -> CandidateBundle:
        root = self.fs.resolve(candidate_root)
        self._validate_independent_root(root, codex_home, vault, config_path)
        if self.fs.exists(root):
            raise ValueError(f"candidate root already exists: {root}")
        self.fs.mkdir(root)
        manifest = self._install_manifest()
        assets: list[SwitchAsset] = []
        preserved: list[str] = []
        conflicts: list[str] = []

        candidate_codex = root / "codex"
        for directory in manifest["managed_runtime_directories"]:
            source = self.plugin_root / "runtime/codex" / directory
            candidate = candidate_codex / directory
            if directory == "agents":
                managed = set(manifest["managed_agents"])
                target_agents = codex_home / "agents"
                for existing in self.fs.iter_children(target_agents):
                    if existing.suffix != ".toml" or existing.stem in managed:
                        continue
                    if self.fs.is_symlink(existing):
                        raise ValueError(f"custom Agent cannot be a symlink: {existing}")
                    self.fs.copy(existing, candidate / existing.name)
                    preserved.append(str(existing))
            self.fs.copy(source, candidate)
            reserved = candidate / "xiaoh.toml"
            if self.fs.exists(reserved):
                self.fs.remove(reserved)
            assets.append(self._switch_asset(candidate, codex_home / directory, f"codex-{directory}"))

        managed_files = self._managed_runtime_files(manifest)
        previous_files = self._previous_managed_files(codex_home, manifest)
        for relative in sorted(previous_files - managed_files):
            target = self._managed_target(codex_home, relative)
            if self.fs.exists(target):
                assets.append(
                    SwitchAsset(
                        root / "deletions" / relative,
                        target,
                        "retired-managed-runtime",
                        "delete",
                        self.fs.digest(target),
                        None,
                    )
                )

        runtime_state_candidate = root / "codex-root/.xiaoh-managed-runtime.json"
        self.fs.write_text_atomic(
            runtime_state_candidate,
            json.dumps(
                {
                    "schema_version": MANAGED_RUNTIME_STATE_SCHEMA,
                    "version": "4.0.1",
                    "managed_files": sorted(managed_files),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )
        assets.append(
            self._switch_asset(
                runtime_state_candidate,
                codex_home / ".xiaoh-managed-runtime.json",
                "managed-runtime-state",
            )
        )

        agents_target = self._active_agents_target(codex_home)
        agents_candidate = root / "codex-root" / agents_target.name
        current_agents = self.fs.read_text(agents_target) if self.fs.is_file(agents_target) else ""
        incoming_agents = self.fs.read_text(self.plugin_root / "runtime/codex/AGENTS.md")
        merged_agents = current_agents
        for marker in ("codebase-memory-mcp", "global-agent-common-contract"):
            merged_agents = _merge_marked_block(merged_agents, incoming_agents, marker)
        self.fs.write_text_atomic(agents_candidate, merged_agents.rstrip() + "\n")
        assets.append(self._switch_asset(agents_candidate, agents_target, "contract"))

        config_target = codex_home / "config.toml"
        config_candidate = root / "codex-root/config.toml"
        current_config = self.fs.read_text(config_target) if self.fs.is_file(config_target) else ""
        incoming_hook = self.fs.read_text(self.plugin_root / "runtime/codex/root-agent-hook.toml")
        rendered_hook = incoming_hook.replace("__CODEX_HOME__", codex_home.as_posix())
        rendered_hook = rendered_hook.replace("__XIAOH_CONFIG__", config_path.as_posix())
        rendered_hook = rendered_hook.replace("__PYTHON_WINDOWS__", Path(sys.executable).resolve().as_posix())
        merged_config = _merge_config_block(
            _update_agents_section(current_config), rendered_hook, "xiaoh-root-agent-hook"
        )
        self.fs.write_text_atomic(config_candidate, merged_config.rstrip() + "\n")
        assets.append(self._switch_asset(config_candidate, config_target, "hook-config"))

        vault_service = VaultService(self.fs, self.plugin_root)
        vault_decisions = vault_service.plan(vault)
        for item in vault_decisions:
            if item.action in {"create", "overwrite"}:
                candidate = root / "vault" / item.relative
                self.fs.copy(item.source, candidate)
                assets.append(self._switch_asset(candidate, item.target, "vault-template"))
            elif item.state in {"user_customized_compatible", "customization_conflict", "user_content"}:
                preserved.append(item.relative)
                if item.state == "customization_conflict":
                    conflicts.append(item.relative)
        state_candidate = root / "vault/.xiaoh-managed.json"
        previous_state = self._optional_json(vault / ".xiaoh-managed.json")
        self.fs.write_text_atomic(
            state_candidate,
            json.dumps(
                vault_service.state_document(vault_decisions, previous_state),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )
        assets.append(
            self._switch_asset(state_candidate, vault / ".xiaoh-managed.json", "vault-state")
        )

        configuration = ConfigurationService(self.fs)
        old_config = configuration.load(config_path, missing_ok=True)
        durable, _ = configuration.import_312_durable_state(old_config)
        generated = configuration.merged_runtime_config(
            durable, codex_home, vault, "4.0.1"
        )
        config_candidate_json = root / "local/config.json"
        self.fs.write_text_atomic(
            config_candidate_json,
            json.dumps(generated, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        assets.append(self._switch_asset(config_candidate_json, config_path, "configuration"))

        replacements = (
            ("__CODEX_HOME__/AGENTS.md", agents_target.as_posix()),
            ("__CODEX_HOME__", codex_home.as_posix()),
            ("__XIAOH_CONFIG__", config_path.as_posix()),
            ("__OBSIDIAN_VAULT__", vault.as_posix()),
            ("__USER_HOME__", user_home.as_posix()),
            ("__PYTHON_WINDOWS__", Path(sys.executable).resolve().as_posix()),
        )
        self._replace_placeholders(root, replacements)
        self._bind_template_hash(root)
        assets = [
            item
            if item.action == "delete"
            else self._switch_asset(item.candidate, item.target, item.asset_type)
            for item in assets
        ]
        self._validate_assets(root, assets)
        manifest_path = root / "candidate-manifest.json"
        self.fs.write_text_atomic(
            manifest_path,
            json.dumps(
                {
                    "schema_version": "xiaoh-candidate/v1",
                    "transaction_id": transaction_id,
                    "version": "4.0.1",
                    "assets": [
                        {
                            "candidate": str(item.candidate),
                            "target": str(item.target),
                            "asset_type": item.asset_type,
                            "action": item.action,
                            "old_digest": item.old_digest,
                            "new_digest": item.new_digest,
                            "size": 0 if item.action == "delete" else self.fs.size(item.candidate),
                        }
                        for item in assets
                    ],
                    "conflicts": conflicts,
                    "preserved_assets": sorted(set(preserved)),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )
        return CandidateBundle(root, assets, manifest_path, sorted(set(preserved)), conflicts)

    def _switch_asset(self, candidate: Path, target: Path, asset_type: str) -> SwitchAsset:
        old_digest = self.fs.digest(target)
        new_digest = self.fs.digest(candidate)
        action = "preserve" if old_digest == new_digest else ("create" if old_digest is None else "overwrite")
        return SwitchAsset(candidate, target, asset_type, action, old_digest, new_digest)

    def _install_manifest(self) -> dict[str, Any]:
        value = json.loads(self.fs.read_text(self.plugin_root / "install-manifest.json"))
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != INSTALL_MANIFEST_SCHEMA
            or value.get("version") != "4.0.1"
        ):
            raise ValueError("candidate requires the 4.0.1 install manifest")
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
            source = self.plugin_root / "runtime/codex" / directory
            for path in self.fs.iter_files(source):
                files.add((Path(directory) / path.relative_to(source)).as_posix())
        return files

    def _previous_managed_files(
        self, codex_home: Path, manifest: dict[str, Any]
    ) -> set[str]:
        state = self._optional_json(codex_home / ".xiaoh-managed-runtime.json")
        values = (
            state.get("managed_files")
            if isinstance(state, dict)
            and state.get("schema_version") == MANAGED_RUNTIME_STATE_SCHEMA
            else manifest["previous_managed_runtime_files"]
        )
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

    def _managed_target(self, codex_home: Path, relative: str) -> Path:
        target = (codex_home / relative).resolve(strict=False)
        try:
            target.relative_to(codex_home.resolve(strict=False))
        except ValueError as exc:
            raise ValueError("managed runtime inventory escapes Codex home") from exc
        return target

    def _active_agents_target(self, codex_home: Path) -> Path:
        override = codex_home / "AGENTS.override.md"
        if self.fs.is_file(override) and self.fs.read_text(override).strip():
            return override
        return codex_home / "AGENTS.md"

    def _optional_json(self, path: Path) -> dict[str, Any] | None:
        if not self.fs.is_file(path):
            return None
        try:
            value = json.loads(self.fs.read_text(path))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def _replace_placeholders(
        self, root: Path, replacements: Iterable[tuple[str, str]]
    ) -> None:
        for path in self.fs.iter_files(root):
            if path.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            try:
                text = self.fs.read_text(path)
            except UnicodeError:
                continue
            rendered = text
            for old, new in replacements:
                rendered = rendered.replace(old, new)
            if rendered != text:
                self.fs.write_text_atomic(path, rendered)

    def _bind_template_hash(self, root: Path) -> None:
        system = root / "codex/agent-system"
        context_path = system / "task-context.template.json"
        record_path = system / "run-record.template.json"
        context = json.loads(self.fs.read_text(context_path))
        record = json.loads(self.fs.read_text(record_path))
        encoded = json.dumps(
            context,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        record["context_hash"] = hashlib.sha256(encoded).hexdigest()
        self.fs.write_text_atomic(
            record_path,
            json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        )

    def _validate_assets(self, root: Path, assets: list[SwitchAsset]) -> None:
        targets: set[str] = set()
        for item in assets:
            if item.action != "delete" and not self.fs.exists(item.candidate):
                raise ValueError(f"candidate asset is missing: {item.candidate}")
            if item.action != "delete":
                try:
                    item.candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
                except ValueError as exc:
                    raise ValueError(f"candidate asset escapes root: {item.candidate}") from exc
            if str(item.target) in targets:
                raise ValueError(f"duplicate candidate target: {item.target}")
            targets.add(str(item.target))
            if item.action != "delete" and item.new_digest is None:
                raise ValueError(f"candidate asset has no digest: {item.candidate}")
        for path in self.fs.iter_files(root):
            if path.suffix.lower() in TEXT_EXTENSIONS:
                text = self.fs.read_text(path)
                if re.search(r"__XIAOH_[A-Z_]*__|__CODEX_HOME__|__OBSIDIAN_VAULT__|__USER_HOME__", text):
                    raise ValueError(f"unresolved candidate placeholder: {path}")

    def _validate_independent_root(
        self, candidate: Path, codex_home: Path, vault: Path, config_path: Path
    ) -> None:
        candidate = self.fs.resolve(candidate)
        roots = {
            self.plugin_root,
            self.fs.resolve(codex_home),
            self.fs.resolve(vault),
            self.fs.resolve(config_path),
        }
        if any(
            candidate == root or candidate in root.parents or root in candidate.parents
            for root in roots
        ):
            raise ValueError("candidate root must be independent from source and targets")


def _merge_marked_block(current: str, incoming: str, marker: str) -> str:
    start = f"<!-- {marker}:start -->"
    end = f"<!-- {marker}:end -->"
    pattern = re.compile(re.escape(start) + r"[\s\S]*?" + re.escape(end))
    source = pattern.search(incoming)
    if source is None:
        raise ValueError(f"source contract is missing marker: {marker}")
    existing = pattern.search(current)
    if existing is not None:
        return current[: existing.start()] + source.group(0) + current[existing.end() :]
    separator = "\n\n" if current.strip() else ""
    return current.rstrip() + separator + source.group(0) + "\n"


def _merge_config_block(current: str, incoming: str, marker: str) -> str:
    start = f"# {marker}:start"
    end = f"# {marker}:end"
    pattern = re.compile(re.escape(start) + r"[\s\S]*?" + re.escape(end))
    source = pattern.search(incoming)
    if source is None:
        raise ValueError(f"source config is missing marker: {marker}")
    existing = pattern.search(current)
    if existing is not None:
        return current[: existing.start()] + source.group(0) + current[existing.end() :]
    separator = "\n\n" if current.strip() else ""
    return current.rstrip() + separator + source.group(0) + "\n"


def _update_agents_section(config: str) -> str:
    values = {"max_threads": "4", "max_depth": "1", "interrupt_message": "true"}
    match = re.search(r"^\[agents\]\s*$([\s\S]*?)(?=^\[|\Z)", config, re.MULTILINE)
    if match is None:
        block = "[agents]\nmax_threads = 4\nmax_depth = 1\ninterrupt_message = true\n"
        return config.rstrip() + ("\n\n" if config.strip() else "") + block
    section = match.group(0)
    for key, value in values.items():
        pattern = rf"^{re.escape(key)}\s*=.*$"
        if re.search(pattern, section, re.MULTILINE):
            section = re.sub(pattern, f"{key} = {value}", section, flags=re.MULTILINE)
        else:
            section = section.rstrip() + f"\n{key} = {value}\n"
    return config[: match.start()] + section + config[match.end() :]
