"""Configuration loading, validation, merge, locking, and atomic writing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Tuple

from ..ports.protocols import FileSystemPort


SENSITIVE_FRAGMENTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "cookie",
    "private_key",
    "private-key",
    "credential",
)

AUTOMATION_PREFERENCE_FIELDS = (
    "schedule",
    "timezone",
    "target",
    "notification",
    "model",
    "reasoning",
    "enabled",
)


class ConfigurationService:
    def __init__(self, filesystem: FileSystemPort):
        self.fs = filesystem

    def load(self, path: Path, missing_ok: bool = False) -> dict[str, Any]:
        if not self.fs.exists(path):
            if missing_ok:
                return {}
            raise ValueError(f"XiaoH configuration does not exist: {path}")
        try:
            value = json.loads(self.fs.read_text(path))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid XiaoH configuration: {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"XiaoH configuration must be a JSON object: {path}")
        return value

    def write(
        self,
        path: Path,
        value: Mapping[str, Any],
        backup_path: Path | None = None,
    ) -> None:
        document = dict(value)
        self.validate(document)
        lock_path = path.with_suffix(path.suffix + ".lock")
        with self.fs.lock(lock_path):
            if backup_path is not None and self.fs.is_file(path):
                self.fs.copy(path, backup_path)
            self.fs.write_text_atomic(
                path,
                json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            )

    def validate(self, value: Mapping[str, Any]) -> None:
        for key in ("workspaces", "preferences", "automation_preferences", "integrations"):
            if key in value and not isinstance(value[key], dict):
                raise ValueError(f"{key} must be a JSON object")
        installed_version = value.get("installed_version")
        if installed_version is not None and not isinstance(installed_version, str):
            raise ValueError("installed_version must be a string")

    def import_312_durable_state(
        self, source: Mapping[str, Any]
    ) -> Tuple[dict[str, Any], list[dict[str, Any]]]:
        """Import the allowlisted user state, never old runtime authority evidence."""
        imported: dict[str, Any] = {}
        evidence: list[dict[str, Any]] = []
        for key in ("workspaces", "preferences"):
            value = source.get(key)
            if isinstance(value, dict):
                imported[key] = _redact_mapping(value)
                evidence.append(_import_evidence(key, "imported"))
        automations = source.get("managed_automations")
        preferences: dict[str, dict[str, Any]] = {}
        if isinstance(automations, dict):
            for logical_id, binding in automations.items():
                if not isinstance(logical_id, str) or not isinstance(binding, dict):
                    continue
                preference = {
                    key: binding[key]
                    for key in AUTOMATION_PREFERENCE_FIELDS
                    if key in binding and not _is_sensitive_key(key)
                }
                if preference:
                    preferences[logical_id] = preference
                    evidence.append(_import_evidence(f"automation:{logical_id}", "imported"))
        if preferences:
            imported["automation_preferences"] = preferences
        integrations = source.get("integrations")
        if isinstance(integrations, dict):
            safe_integrations = _redact_mapping(integrations, drop_sensitive=True)
            if safe_integrations:
                imported["integrations"] = safe_integrations
                evidence.append(_import_evidence("integrations", "imported"))
        self.validate(imported)
        return imported, evidence

    def merged_runtime_config(
        self,
        durable: Mapping[str, Any],
        codex_home: Path,
        vault: Path,
        version: str,
    ) -> dict[str, Any]:
        result = dict(durable)
        result.update(
            {
                "schema_version": "xiaoh-config/v2",
                "installed_version": version,
                "codex_home": str(self.fs.resolve(codex_home)),
                "obsidian_vault": str(self.fs.resolve(vault)),
            }
        )
        self.validate(result)
        return result


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace(" ", "_")
    return any(fragment in normalized for fragment in SENSITIVE_FRAGMENTS)


def _redact_mapping(
    value: Mapping[str, Any], drop_sensitive: bool = True
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            continue
        if _is_sensitive_key(key):
            if not drop_sensitive:
                result[key] = "[REDACTED]"
            continue
        if isinstance(item, dict):
            result[key] = _redact_mapping(item, drop_sensitive=drop_sensitive)
        elif isinstance(item, list):
            result[key] = [
                _redact_mapping(entry, drop_sensitive=drop_sensitive)
                if isinstance(entry, dict)
                else entry
                for entry in item
            ]
        else:
            result[key] = item
    return result


def _import_evidence(source: str, result: str) -> dict[str, str]:
    return {
        "source": source,
        "conversion_version": "4.0.1",
        "result": result,
        "conflict_status": "none",
    }
