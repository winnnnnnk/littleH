"""Stable logical automation identity and preference preservation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from ..ports.protocols import AutomationStorePort, FileSystemPort
from .configuration import ConfigurationService


PREFERENCE_FIELDS = frozenset(
    {"schedule", "timezone", "target", "notification", "model", "reasoning", "enabled", "status"}
)


class AutomationService:
    def __init__(self, filesystem: FileSystemPort, plugin_root: Path):
        self.fs = filesystem
        self.plugin_root = filesystem.resolve(plugin_root)

    def templates(self) -> dict[str, dict[str, Any]]:
        path = self.plugin_root / "managed-automations.json"
        value = json.loads(self.fs.read_text(path))
        items = value.get("templates") if isinstance(value, dict) else None
        if not isinstance(items, list):
            raise ValueError("automation templates must be a list")
        result: dict[str, dict[str, Any]] = {}
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("automation template must be an object")
            logical_id = item.get("logical_id")
            if not isinstance(logical_id, str) or not logical_id:
                raise ValueError("automation template requires logical_id")
            if logical_id in result:
                raise ValueError(f"duplicate automation logical id: {logical_id}")
            result[logical_id] = item
        return result

    def bind_existing(
        self,
        config_path: Path,
        logical_id: str,
        task_id: str,
        store: AutomationStorePort,
    ) -> dict[str, Any]:
        template = self.templates().get(logical_id)
        if template is None:
            raise ValueError(f"unknown managed automation: {logical_id}")
        snapshot = store.get(task_id)
        if snapshot is None:
            raise ValueError(f"automation store cannot read task: {task_id}")
        mismatches = [
            key
            for key, expected in (
                ("id", task_id),
                ("name", template["name"]),
                ("prompt", template["prompt"]),
                ("status", template["default_status"]),
            )
            if snapshot.get(key) != expected
        ]
        if mismatches:
            raise ValueError(
                f"automation does not match template {logical_id}: {', '.join(mismatches)}"
            )
        configuration = ConfigurationService(self.fs)
        local = configuration.load(config_path)
        bindings = local.get("automation_bindings", {})
        if not isinstance(bindings, dict):
            raise ValueError("automation_bindings must be an object")
        bindings = dict(bindings)
        desired_binding = {
            "task_id": task_id,
            "template_version": template["template_version"],
            "managed_hash": hashlib.sha256(
                template["prompt"].encode("utf-8")
            ).hexdigest(),
            "readback": {
                "id": snapshot.get("id"),
                "name": snapshot.get("name"),
                "status": snapshot.get("status"),
            },
        }
        preferences = local.get("automation_preferences", {})
        if not isinstance(preferences, dict):
            preferences = {}
        preferences = dict(preferences)
        desired_preferences = {
            key: snapshot[key]
            for key in sorted(PREFERENCE_FIELDS)
            if key in snapshot
        }
        changed = (
            bindings.get(logical_id) != desired_binding
            or preferences.get(logical_id) != desired_preferences
        )
        bindings[logical_id] = desired_binding
        local["automation_bindings"] = bindings
        preferences[logical_id] = desired_preferences
        local["automation_preferences"] = preferences
        if changed:
            configuration.write(
                config_path,
                local,
                backup_path=config_path.with_suffix(config_path.suffix + ".bak"),
            )
        return {
            "logical_id": logical_id,
            "task_id": task_id,
            "template_version": template["template_version"],
            "actual_status": snapshot.get("status"),
            "actual_writes": [str(self.fs.resolve(config_path))] if changed else [],
        }

    def report(
        self,
        config: Mapping[str, Any],
        store: AutomationStorePort,
    ) -> dict[str, Any]:
        bindings = config.get("automation_bindings", {})
        if not isinstance(bindings, dict):
            bindings = {}
        snapshots = list(store.list())
        tasks: list[dict[str, Any]] = []
        warnings: list[str] = []
        for logical_id, template in self.templates().items():
            binding = bindings.get(logical_id, {})
            task_id = binding.get("task_id") if isinstance(binding, dict) else None
            snapshot = store.get(task_id) if isinstance(task_id, str) else None
            matches = [
                str(item.get("id"))
                for item in snapshots
                if item.get("name") == template.get("name")
            ]
            if len(matches) > 1:
                state = "duplicate"
                warnings.append(f"duplicate automation identity: {logical_id}")
            elif snapshot is None:
                state = "unbound"
                if template.get("required"):
                    warnings.append(f"required automation is unbound: {logical_id}")
            elif snapshot.get("prompt") != template.get("prompt"):
                state = "drifted"
                warnings.append(f"managed automation fields drifted: {logical_id}")
            else:
                state = "configured"
            tasks.append(
                {
                    "logical_id": logical_id,
                    "task_id": task_id,
                    "state": state,
                    "matching_task_ids": sorted(matches),
                }
            )
        return {
            "status": "degraded" if warnings else "passed",
            "tasks": tasks,
            "warnings": warnings,
        }
