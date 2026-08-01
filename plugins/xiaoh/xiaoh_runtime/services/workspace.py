"""Workspace registration and unique longest-root resolution."""

from __future__ import annotations

import os
import platform
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping, Optional


class WorkspaceService:
    def __init__(self, platform_name: Optional[str] = None):
        self.platform_name = (platform_name or platform.system()).lower()

    def resolve(self, config: Mapping[str, Any], path: Path) -> dict[str, Any]:
        workspaces = config.get("workspaces", {})
        if not isinstance(workspaces, dict):
            return {"status": "failed", "errors": ["workspaces must be an object"]}
        candidate_path = self._normalized(str(path))
        matches: list[tuple[int, str, Mapping[str, Any], str]] = []
        for workspace_id, workspace in workspaces.items():
            if not isinstance(workspace_id, str) or not isinstance(workspace, dict):
                continue
            root = self._active_root(workspace)
            if root is None:
                continue
            normalized_root = self._normalized(root)
            if _contains(normalized_root, candidate_path, self.platform_name):
                matches.append((len(normalized_root), workspace_id, workspace, normalized_root))
        if not matches:
            return {"status": "unresolved", "path": candidate_path, "candidates": []}
        strongest = max(item[0] for item in matches)
        winners = sorted((item for item in matches if item[0] == strongest), key=lambda item: item[1])
        if len(winners) != 1:
            return {
                "status": "conflict",
                "path": candidate_path,
                "candidates": [item[1] for item in winners],
                "errors": ["multiple equally strong Workspace roots own the path"],
            }
        _, workspace_id, workspace, root = winners[0]
        return {
            "status": "resolved",
            "workspace_id": workspace_id,
            "project": workspace.get("project"),
            "system": workspace.get("system"),
            "root": root,
            "path": candidate_path,
            "candidates": [workspace_id],
        }

    def register(
        self,
        config: Mapping[str, Any],
        workspace_id: str,
        project: str,
        system: str,
        root: Path,
    ) -> dict[str, Any]:
        if not all(value.strip() for value in (workspace_id, project, system)):
            raise ValueError("workspace id, project, and system are required")
        result = dict(config)
        workspaces = result.get("workspaces", {})
        if not isinstance(workspaces, dict):
            raise ValueError("workspaces must be an object")
        workspaces = dict(workspaces)
        existing = workspaces.get(workspace_id, {})
        if existing and not isinstance(existing, dict):
            raise ValueError(f"invalid Workspace: {workspace_id}")
        roots = dict(existing.get("roots", {})) if isinstance(existing, dict) else {}
        roots[self.platform_name] = self._normalized(str(root))
        workspaces[workspace_id] = {
            "project": project,
            "system": system,
            "roots": roots,
        }
        result["workspaces"] = workspaces
        return result

    def report(self, config: Mapping[str, Any]) -> dict[str, Any]:
        workspaces = config.get("workspaces", {})
        errors: list[str] = []
        warnings: list[str] = []
        if not isinstance(workspaces, dict):
            errors.append("workspaces must be an object")
            workspaces = {}
        roots: dict[str, list[str]] = {}
        for workspace_id, workspace in workspaces.items():
            if not isinstance(workspace_id, str) or not isinstance(workspace, dict):
                errors.append(f"invalid Workspace entry: {workspace_id}")
                continue
            active = self._active_root(workspace)
            if active is None:
                warnings.append(f"Workspace has no {self.platform_name} root: {workspace_id}")
                continue
            roots.setdefault(self._normalized(active), []).append(workspace_id)
        for root, owners in roots.items():
            if len(owners) > 1:
                errors.append(f"Workspace root conflict: {root}: {', '.join(sorted(owners))}")
        return {
            "status": "failed" if errors else ("degraded" if warnings else "passed"),
            "workspaces": workspaces,
            "errors": errors,
            "warnings": warnings,
        }

    def _active_root(self, workspace: Mapping[str, Any]) -> Optional[str]:
        roots = workspace.get("roots", {})
        if not isinstance(roots, dict):
            return None
        value = roots.get(self.platform_name)
        if value is None and self.platform_name.startswith("win"):
            value = roots.get("windows")
        if value is None and self.platform_name in {"darwin", "macos"}:
            value = roots.get("macos") or roots.get("darwin")
        return value if isinstance(value, str) and value.strip() else None

    def _normalized(self, value: str) -> str:
        if self.platform_name.startswith("win"):
            return str(PureWindowsPath(value)).rstrip("\\/").casefold()
        return os.path.normpath(value)


def _contains(root: str, candidate: str, platform_name: str) -> bool:
    separator = "\\" if platform_name.startswith("win") else os.sep
    return candidate == root or candidate.startswith(root.rstrip("\\/") + separator)
