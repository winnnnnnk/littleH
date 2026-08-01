"""Vault template classification and customization preservation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..ports.protocols import FileSystemPort


@dataclass(frozen=True)
class VaultAssetDecision:
    relative: str
    source: Path
    target: Path
    action: str
    state: str
    source_digest: str
    target_digest: str | None
    reason: str | None = None


class VaultService:
    def __init__(self, filesystem: FileSystemPort, plugin_root: Path):
        self.fs = filesystem
        self.plugin_root = filesystem.resolve(plugin_root)
        self.source_root = self.plugin_root / "runtime/obsidian/development-vault"
        self.manifest_path = self.plugin_root / "runtime/obsidian/managed-vault-files.json"

    def plan(self, vault: Path) -> list[VaultAssetDecision]:
        manifest = self._manifest()
        previous = self._previous_hashes(vault)
        decisions: list[VaultAssetDecision] = []
        for source in self.fs.iter_files(self.source_root):
            relative = source.relative_to(self.source_root).as_posix()
            target = _contained(vault, Path(relative))
            source_digest = self.fs.digest(source)
            if source_digest is None:
                raise ValueError(f"cannot digest Vault source: {source}")
            target_digest = self.fs.digest(target)
            metadata = manifest.get(relative)
            if not isinstance(metadata, dict):
                action = "create" if target_digest is None else "preserve"
                state = "missing" if target_digest is None else "user_content"
                reason = None if target_digest is None else "seed-once user asset already exists"
            else:
                action, state, reason = self._classify_managed(
                    source,
                    target,
                    source_digest,
                    target_digest,
                    metadata,
                    previous.get(relative),
                )
            decisions.append(
                VaultAssetDecision(
                    relative,
                    source,
                    target,
                    action,
                    state,
                    source_digest,
                    target_digest,
                    reason,
                )
            )
        return decisions

    def state_document(
        self,
        decisions: list[VaultAssetDecision],
        previous_document: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        previous_files = (
            previous_document.get("files", {})
            if isinstance(previous_document, dict)
            else {}
        )
        if not isinstance(previous_files, dict):
            previous_files = {}
        files: dict[str, str] = {}
        for item in decisions:
            if item.relative not in self._manifest():
                continue
            if item.action in {"create", "overwrite", "preserve"} and item.state in {
                "missing",
                "current",
                "recognized_managed_version",
            }:
                files[item.relative] = item.source_digest
            elif isinstance(previous_files.get(item.relative), str):
                files[item.relative] = previous_files[item.relative]
        return {
            "schema_version": "xiaoh-managed-vault/v2",
            "template_version": "4.0.1",
            "files": files,
        }

    def report(self, vault: Path) -> dict[str, Any]:
        decisions = self.plan(vault)
        warnings = [
            f"preserved Vault customization: {item.relative} ({item.state})"
            for item in decisions
            if item.state in {"user_customized_compatible", "customization_conflict"}
        ]
        errors = [
            f"unsafe Vault asset: {item.relative} ({item.state})"
            for item in decisions
            if item.state == "corrupted"
        ]
        return {
            "status": "failed" if errors else ("degraded" if warnings else "passed"),
            "files": [
                {
                    "path": item.relative,
                    "state": item.state,
                    "reason": item.reason,
                    "expected_hash": item.source_digest,
                    "actual_hash": item.target_digest,
                }
                for item in decisions
            ],
            "errors": errors,
            "warnings": warnings,
        }

    def _classify_managed(
        self,
        source: Path,
        target: Path,
        source_digest: str,
        target_digest: str | None,
        metadata: Mapping[str, Any],
        previous_digest: Any,
    ) -> tuple[str, str, str | None]:
        if self.fs.is_symlink(target):
            return "conflict", "corrupted", "managed Vault path is a symlink"
        if target_digest is None:
            return "create", "missing", None
        if target_digest == source_digest:
            return "preserve", "current", None
        legacy = metadata.get("legacy_hashes", [])
        if not isinstance(legacy, list):
            raise ValueError(f"legacy_hashes must be a list: {source}")
        if target_digest in legacy or target_digest == previous_digest:
            return "overwrite", "recognized_managed_version", "safe managed upgrade"
        if target.suffix == ".base" and self._compatible_base(target):
            return (
                "preserve",
                "user_customized_compatible",
                "required filters and behavior remain present",
            )
        return (
            "preserve",
            "customization_conflict",
            "unrecognized managed-template change preserved for the user",
        )

    def _compatible_base(self, path: Path) -> bool:
        try:
            text = self.fs.read_text(path)
        except (OSError, UnicodeError):
            return False
        return all(
            fragment in text
            for fragment in (
                "filters:",
                "properties:",
                "views:",
                'file.ext == "md"',
                "is_template != true",
            )
        )

    def _manifest(self) -> dict[str, Any]:
        value = json.loads(self.fs.read_text(self.manifest_path))
        files = value.get("files") if isinstance(value, dict) else None
        if not isinstance(files, dict):
            raise ValueError("managed Vault manifest files must be an object")
        return files

    def _previous_hashes(self, vault: Path) -> dict[str, Any]:
        path = vault / ".xiaoh-managed.json"
        if not self.fs.is_file(path):
            return {}
        try:
            value = json.loads(self.fs.read_text(path))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        files = value.get("files") if isinstance(value, dict) else None
        return files if isinstance(files, dict) else {}


def _contained(root: Path, relative: Path) -> Path:
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Vault managed path escapes root: {relative}")
    root_resolved = root.resolve(strict=False)
    target = root / relative
    try:
        target.resolve(strict=False).relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"Vault managed path escapes root: {target}") from exc
    return target
