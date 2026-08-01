"""Read-only Codex plugin-manager facts."""

from __future__ import annotations

import json
from typing import Any, Mapping

from ..ports.protocols import PluginFactsPort, ProcessRunnerPort


SAFE_PLUGIN_FIELDS = (
    "id",
    "name",
    "version",
    "installed",
    "enabled",
    "status",
    "marketplace",
)


class CodexPluginFacts(PluginFactsPort):
    def __init__(self, process_runner: ProcessRunnerPort):
        self.runner = process_runner

    def current_facts(self) -> Mapping[str, Any]:
        result = self.runner.run(["codex", "plugin", "list", "--json"])
        if result.returncode != 0:
            return {
                "status": "unavailable",
                "plugins": [],
                "warning": "Codex plugin list read failed",
            }
        try:
            value = json.loads(result.stdout)
        except (TypeError, json.JSONDecodeError):
            return {
                "status": "invalid",
                "plugins": [],
                "warning": "Codex plugin list returned invalid JSON",
            }
        if isinstance(value, dict):
            raw_plugins = value.get("plugins", value.get("data", []))
        else:
            raw_plugins = value
        if not isinstance(raw_plugins, list):
            return {
                "status": "invalid",
                "plugins": [],
                "warning": "Codex plugin list returned an unsupported shape",
            }
        plugins = [
            {
                key: item[key]
                for key in SAFE_PLUGIN_FIELDS
                if key in item and isinstance(item[key], (str, bool, int, type(None)))
            }
            for item in raw_plugins
            if isinstance(item, dict)
        ]
        return {"status": "available", "plugins": plugins}
