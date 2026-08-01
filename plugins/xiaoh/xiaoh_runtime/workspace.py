"""XiaoH modular runtime boundary."""

from __future__ import annotations

from .common import *
from .config import *

def normalized_workspace_root(value: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Workspace root必须是非空字符串")
    root = Path(value).expanduser()
    if not root.is_absolute():
        raise ValueError(f"Workspace root必须是绝对路径: {value}")
    return root.resolve()

def workspace_registry_report(local: dict) -> dict:
    registry = local.get("workspaces", {})
    errors: list[str] = []
    warnings: list[str] = []
    entries: list[dict] = []
    seen_roots: dict[str, str] = {}
    current_platform = platform.system().lower()
    if not isinstance(registry, dict):
        return {
            "status": "failed",
            "entries": [],
            "errors": ["workspaces必须是JSON对象"],
            "warnings": [],
        }
    for workspace_id, entry in sorted(registry.items()):
        if not isinstance(workspace_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", workspace_id):
            errors.append(f"无效workspace_id: {workspace_id!r}")
            continue
        if not isinstance(entry, dict):
            errors.append(f"Workspace {workspace_id} 必须是JSON对象")
            continue
        project = entry.get("project")
        system = entry.get("system")
        roots = entry.get("roots")
        bindings = entry.get("bindings")
        if not isinstance(project, str) or not project.strip():
            errors.append(f"Workspace {workspace_id} 缺少project")
        if not isinstance(system, str) or not system.strip():
            errors.append(f"Workspace {workspace_id} 缺少system")
        if bindings is None:
            if not isinstance(roots, list) or not roots:
                errors.append(f"Workspace {workspace_id} 缺少roots或bindings")
                continue
            # Legacy `roots` did not always record a platform. Treat those
            # bindings as preserved history until this machine is explicitly
            # rebound; guessing the current platform breaks cross-OS moves.
            binding_platform = entry.get("platform", "unknown")
            bindings = [{"root": value, "platform": binding_platform} for value in roots]
        elif not isinstance(bindings, list) or not bindings:
            errors.append(f"Workspace {workspace_id} bindings必须是非空数组")
            continue
        normalized: list[str] = []
        normalized_bindings: list[dict] = []
        for binding in bindings:
            if not isinstance(binding, dict):
                errors.append(f"Workspace {workspace_id} binding必须是JSON对象")
                continue
            value = binding.get("root")
            binding_platform = binding.get("platform")
            if not isinstance(value, str) or not value.strip():
                errors.append(f"Workspace {workspace_id} binding缺少root")
                continue
            if not isinstance(binding_platform, str) or not binding_platform.strip():
                errors.append(f"Workspace {workspace_id} binding缺少platform")
                continue
            binding_platform = binding_platform.lower()
            if binding_platform != current_platform:
                normalized_bindings.append({"root": value, "platform": binding_platform, "active": False})
                warnings.append(
                    f"Workspace异平台路径待本机绑定: {workspace_id}: {binding_platform}: {value}"
                )
                continue
            try:
                root = normalized_workspace_root(value)
            except (OSError, RuntimeError, ValueError) as exc:
                errors.append(f"Workspace {workspace_id} root无效: {exc}")
                continue
            encoded = str(root)
            owner = seen_roots.get(encoded)
            if owner and owner != workspace_id:
                errors.append(f"Workspace root重复归属: {encoded} -> {owner}, {workspace_id}")
            else:
                seen_roots[encoded] = workspace_id
            if not root.is_dir():
                warnings.append(f"Workspace本机路径不存在，需重新绑定: {workspace_id}: {encoded}")
            normalized.append(encoded)
            normalized_bindings.append({
                "root": encoded,
                "platform": binding_platform,
                "active": True,
            })
        entries.append({
            "workspace_id": workspace_id,
            "project": project,
            "system": system,
            "roots": normalized,
            "bindings": normalized_bindings,
        })
    return {
        "status": "failed" if errors else ("degraded" if warnings else "passed"),
        "entries": entries,
        "errors": errors,
        "warnings": warnings,
    }

def resolve_workspace(local: dict, target: Path) -> dict:
    registry = workspace_registry_report(local)
    if registry["errors"]:
        return {"status": "conflict", "path": str(target.resolve()), **registry}
    resolved = target.expanduser().resolve()
    matches: list[tuple[int, dict, str]] = []
    for entry in registry["entries"]:
        for encoded in entry["roots"]:
            root = Path(encoded)
            if resolved == root or resolved.is_relative_to(root):
                matches.append((len(root.parts), entry, encoded))
    if not matches:
        return {
            "status": "unknown",
            "path": str(resolved),
            "workspace": None,
            "warnings": registry["warnings"],
            "errors": [],
        }
    longest = max(item[0] for item in matches)
    strongest = [item for item in matches if item[0] == longest]
    workspace_ids = {item[1]["workspace_id"] for item in strongest}
    if len(workspace_ids) != 1:
        return {
            "status": "conflict",
            "path": str(resolved),
            "workspace": None,
            "warnings": registry["warnings"],
            "errors": ["当前路径匹配多个同级Workspace: " + ", ".join(sorted(workspace_ids))],
        }
    _, entry, root = strongest[0]
    return {
        "status": "known",
        "path": str(resolved),
        "workspace": {**entry, "matched_root": root},
        "warnings": registry["warnings"],
        "errors": [],
    }

def register_workspace(
    config_path: Path,
    codex: Path,
    vault: Path,
    workspace_id: str,
    project: str,
    system: str,
    root_value: str,
) -> dict:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", workspace_id):
        error = "workspace_id只能包含小写字母、数字、点、下划线和连字符"
    elif not project.strip() or not system.strip():
        error = "project和system不能为空"
    else:
        error = None
    try:
        root = normalized_workspace_root(root_value)
        if not root.is_dir():
            raise ValueError(f"Workspace root不存在或不是目录: {root}")
    except (OSError, RuntimeError, ValueError) as exc:
        error = str(exc)
        root = Path(root_value).expanduser()
    if error:
        return {
            "status": "failed",
            "codex_home": str(codex),
            "obsidian_vault": str(vault),
            "errors": [error],
            "warnings": [],
        }
    with config_lock(config_path):
        local = load_json(config_path, {})
        registry = local.get("workspaces")
        if registry is None:
            registry = {}
        elif not isinstance(registry, dict):
            return {
                "status": "failed",
                "codex_home": str(codex),
                "obsidian_vault": str(vault),
                "errors": ["workspaces必须是JSON对象，拒绝静默覆盖"],
                "warnings": [],
            }
        registry_report = workspace_registry_report({"workspaces": registry})
        if registry_report["errors"]:
            return {
                "status": "failed",
                "codex_home": str(codex),
                "obsidian_vault": str(vault),
                "errors": registry_report["errors"],
                "warnings": registry_report["warnings"],
            }
        existing_resolution = resolve_workspace({"workspaces": registry}, root)
        if existing_resolution["status"] == "conflict":
            return {
                "status": "failed",
                "codex_home": str(codex),
                "obsidian_vault": str(vault),
                "errors": existing_resolution["errors"],
                "warnings": existing_resolution["warnings"],
            }
        if (
            existing_resolution["status"] == "known"
            and existing_resolution["workspace"]["workspace_id"] != workspace_id
        ):
            return {
                "status": "failed",
                "codex_home": str(codex),
                "obsidian_vault": str(vault),
                "errors": [
                    f"{root} 已归属 {existing_resolution['workspace']['workspace_id']}，禁止静默改派"
                ],
                "warnings": [],
            }
        entry = registry.get(workspace_id)
        if entry is not None and (
            not isinstance(entry, dict)
            or entry.get("project") != project
            or entry.get("system") != system
        ):
            return {
                "status": "failed",
                "codex_home": str(codex),
                "obsidian_vault": str(vault),
                "errors": [f"{workspace_id} 已绑定其他项目或系统，禁止静默覆盖"],
                "warnings": [],
            }
        if isinstance(entry, dict) and isinstance(entry.get("bindings"), list):
            bindings = [dict(binding) for binding in entry["bindings"] if isinstance(binding, dict)]
        elif isinstance(entry, dict):
            legacy_platform = entry.get("platform", "unknown")
            bindings = [
                {"root": value, "platform": legacy_platform}
                for value in entry.get("roots", [])
                if isinstance(value, str)
            ]
        else:
            bindings = []
        current_platform = platform.system().lower()
        if not any(
            binding.get("platform") == current_platform
            and binding.get("root") == str(root)
            for binding in bindings
        ):
            bindings.append({"root": str(root), "platform": current_platform})
        registry[workspace_id] = {
            "project": project,
            "system": system,
            "bindings": bindings,
            "confirmed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        local["workspaces"] = registry
        atomic_write_json(config_path, local, config_path.with_suffix(config_path.suffix + ".bak"))
    return {
        "status": "passed",
        "codex_home": str(codex),
        "obsidian_vault": str(vault),
        "config": str(config_path),
        "workspace": {
            "workspace_id": workspace_id,
            "project": project,
            "system": system,
            "root": str(root),
        },
        "errors": [],
        "warnings": [],
    }
