"""Read-only access to Codex automation facts for explicit binding."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from ..ports.protocols import FileSystemPort

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None


TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")


class LocalAutomationStore:
    """Codex owns mutations; this Adapter exposes readback to XiaoH CLI."""

    def __init__(self, filesystem: FileSystemPort, codex_home: Path):
        self.fs = filesystem
        self.root = filesystem.resolve(codex_home) / "automations"

    def get(self, task_id: str) -> Optional[Mapping[str, Any]]:
        path = self._path(task_id)
        if not self.fs.is_file(path):
            return None
        raw = self.fs.read_bytes(path)
        if tomllib is not None:
            value = tomllib.loads(raw.decode("utf-8"))
        else:
            value = _parse_flat_toml(raw.decode("utf-8"))
        return value if isinstance(value, dict) else None

    def create(self, logical_id: str, values: Mapping[str, Any]) -> str:
        raise PermissionError("Codex automation creation requires the supported host tool")

    def update(self, task_id: str, values: Mapping[str, Any]) -> None:
        raise PermissionError("Codex automation updates require the supported host tool")

    def list(self) -> Sequence[Mapping[str, Any]]:
        result = []
        for path in self.fs.iter_files(self.root):
            if path.name != "automation.toml":
                continue
            value = self.get(path.parent.name)
            if value is not None:
                result.append(value)
        return result

    def _path(self, task_id: str) -> Path:
        if not isinstance(task_id, str) or TASK_ID.fullmatch(task_id) is None:
            raise ValueError(f"invalid automation task id: {task_id!r}")
        target = self.root / task_id / "automation.toml"
        try:
            target.resolve(strict=False).relative_to(self.root.resolve(strict=False))
        except ValueError as exc:
            raise ValueError("automation path escapes its root") from exc
        if self.fs.is_symlink(target) or self.fs.is_symlink(target.parent):
            raise ValueError("automation path cannot contain a symlink")
        return target


def _parse_flat_toml(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_-]+)\s*=\s*(.+)", line)
        if match is None:
            raise ValueError(f"unsupported automation TOML at line {line_number}")
        key, encoded = match.groups()
        if encoded.startswith('"'):
            result[key] = json.loads(encoded)
        elif encoded in {"true", "false"}:
            result[key] = encoded == "true"
        elif re.fullmatch(r"-?\d+", encoded):
            result[key] = int(encoded)
        else:
            result[key] = encoded
    return result
