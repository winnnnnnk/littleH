#!/usr/bin/env python3
"""Install, update, and diagnose the XiaoH local runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import platform
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.9 and 3.10
    tomllib = None

if os.name == "nt":
    import msvcrt
else:
    import fcntl


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
RUNTIME = PLUGIN_ROOT / "runtime"
PLUGIN_MANIFEST = PLUGIN_ROOT / ".codex-plugin/plugin.json"
DEPENDENCY_MANIFEST = PLUGIN_ROOT / "dependencies.json"
AUTOMATION_MANIFEST = PLUGIN_ROOT / "managed-automations.json"
VAULT_MANIFEST = RUNTIME / "obsidian/managed-vault-files.json"
REQUIRED_AGENTS = {
    "code_quality_reviewer",
    "frontend_implementer",
    "java_architect",
    "java_code_explorer",
    "java_implementer",
    "pki_domain_expert",
    "pki_security_reviewer",
    "test_integration_verifier",
}
TEXT_EXTENSIONS = {".md", ".toml", ".json", ".py", ".js", ".yaml", ".yml", ".txt"}


def default_local_config() -> Path:
    configured = os.environ.get("XIAOH_CONFIG")
    return Path(configured).expanduser() if configured else Path.home() / ".xiaoh/config.json"


def load_json(path: Path, default: dict | None = None) -> dict:
    if not path.exists() and default is not None:
        return default
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"{path} 必须包含 JSON 对象")
    return value


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def canonical_json_hash(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def atomic_write_text(path: Path, text: str, backup: Path | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.exists():
        backup_item(path, backup)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            temporary.chmod(path.stat().st_mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_json(path: Path, value: dict, backup: Path | None = None) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n", backup)


@contextmanager
def config_lock(config_path: Path):
    """Serialize XiaoH config read-modify-write operations across processes."""
    lock_path = config_path.with_suffix(config_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def automation_templates() -> dict[str, dict]:
    manifest = load_json(AUTOMATION_MANIFEST)
    templates = manifest.get("templates")
    if not isinstance(templates, list):
        raise ValueError(f"{AUTOMATION_MANIFEST} 的 templates 必须是数组")
    result: dict[str, dict] = {}
    for template in templates:
        if not isinstance(template, dict):
            raise ValueError(f"{AUTOMATION_MANIFEST} 包含无效模板")
        logical_id = template.get("logical_id")
        version = template.get("template_version")
        if not isinstance(logical_id, str) or not logical_id or not isinstance(version, str) or not version:
            raise ValueError(f"{AUTOMATION_MANIFEST} 模板缺少 logical_id 或 template_version")
        if logical_id in result:
            raise ValueError(f"{AUTOMATION_MANIFEST} 包含重复 logical_id: {logical_id}")
        result[logical_id] = template
    return result


def integration_mode(local: dict, name: str) -> str:
    integrations = local.get("integrations", {})
    if integrations is None:
        integrations = {}
    if not isinstance(integrations, dict):
        raise ValueError("integrations必须是JSON对象")
    value = integrations.get(name, "auto")
    if value is True:
        return "enabled"
    if value is False:
        return "disabled"
    if isinstance(value, str) and value in {"auto", "enabled", "disabled"}:
        return value
    raise ValueError(f"integrations.{name}必须是auto、enabled、disabled、true或false")


def merged_local_config(local: dict, codex: Path, vault: Path, version: str) -> dict:
    result = dict(local)
    result.update({
        "codex_home": str(codex),
        "obsidian_vault": str(vault),
        "installed_version": version,
    })
    bindings = result.get("managed_automations")
    if not isinstance(bindings, dict):
        bindings = {}
    else:
        bindings = dict(bindings)
    for logical_id in automation_templates():
        binding = bindings.get(logical_id)
        if not isinstance(binding, dict):
            bindings[logical_id] = {
                "task_id": None,
                "applied_template_version": None,
                "status": "unbound",
            }
    result["managed_automations"] = bindings
    workspaces = result.get("workspaces")
    if workspaces is None:
        result["workspaces"] = {}
    elif isinstance(workspaces, dict):
        result["workspaces"] = dict(workspaces)
    else:
        raise ValueError("workspaces必须是JSON对象，拒绝静默覆盖")
    integrations = result.get("integrations")
    if integrations is None:
        integrations = {}
    elif not isinstance(integrations, dict):
        raise ValueError("integrations必须是JSON对象，拒绝静默覆盖")
    else:
        integrations = dict(integrations)
    integrations["playbook"] = integration_mode({"integrations": integrations}, "playbook")
    result["integrations"] = integrations
    return result


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


def automation_snapshot(codex: Path, task_id: str) -> tuple[dict | None, str | None]:
    path = codex / "automations" / task_id / "automation.toml"
    try:
        if tomllib is not None:
            with path.open("rb") as stream:
                value = tomllib.load(stream)
        else:
            value = parse_flat_toml(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("根节点不是对象")
        return value, None
    except (OSError, ValueError) as exc:
        return None, f"无法读取托管定时任务 {task_id}: {path}: {exc}"


def parse_flat_toml(text: str) -> dict:
    """Parse the scalar top-level subset used by Codex automation.toml files."""
    result: dict = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_-]+)\s*=\s*(.+)", line)
        if not match:
            raise ValueError(f"第 {line_number} 行不是受支持的键值")
        key, encoded = match.groups()
        if encoded.startswith('"'):
            try:
                value = json.loads(encoded)
            except json.JSONDecodeError as exc:
                raise ValueError(f"第 {line_number} 行字符串无效: {exc}") from exc
        elif encoded in {"true", "false"}:
            value = encoded == "true"
        elif re.fullmatch(r"-?\d+", encoded):
            value = int(encoded)
        elif encoded.startswith(("[", "{")):
            # Managed automation verification does not inspect arrays or inline tables.
            value = encoded
        else:
            raise ValueError(f"第 {line_number} 行值类型不受支持")
        result[key] = value
    return result


def automation_report(local: dict, codex: Path) -> dict:
    bindings = local.get("managed_automations")
    if not isinstance(bindings, dict):
        bindings = {}
    warnings: list[str] = []
    tasks: list[dict] = []
    for logical_id, template in automation_templates().items():
        binding = bindings.get(logical_id)
        if not isinstance(binding, dict):
            binding = {}
        task_id = binding.get("task_id")
        applied = binding.get("applied_template_version")
        desired = template["template_version"]
        snapshot = None
        if not isinstance(task_id, str) or not task_id:
            state = "unbound"
            if template.get("required"):
                warnings.append(f"必需的托管定时任务尚未绑定: {logical_id}")
        elif applied != desired:
            state = "drifted"
            warnings.append(f"托管定时任务版本漂移: {logical_id}（已应用 {applied}，期望 {desired}）")
        else:
            snapshot, snapshot_error = automation_snapshot(codex, task_id)
            if snapshot_error:
                state = "unreadable"
                warnings.append(snapshot_error)
            else:
                mismatches = []
                for key, expected in (
                    ("id", task_id),
                    ("name", template["name"]),
                    ("prompt", template["prompt"]),
                    ("status", template["default_status"]),
                ):
                    if snapshot.get(key) != expected:
                        mismatches.append(key)
                if mismatches:
                    state = "runtime_drifted"
                    warnings.append(
                        f"托管定时任务运行态漂移: {logical_id}（{', '.join(mismatches)}）"
                    )
                else:
                    state = "configured"
        matching_ids = []
        automation_root = codex / "automations"
        if automation_root.is_dir():
            for candidate in automation_root.glob("*/automation.toml"):
                candidate_id = candidate.parent.name
                candidate_snapshot, _ = automation_snapshot(codex, candidate_id)
                if candidate_snapshot and candidate_snapshot.get("name") == template["name"]:
                    matching_ids.append(candidate_id)
        if len(matching_ids) > 1:
            state = "duplicate"
            warnings.append(
                f"托管定时任务存在重复实例: {logical_id}（{', '.join(sorted(matching_ids))}）"
            )
        tasks.append({
            "logical_id": logical_id,
            "task_id": task_id,
            "required": bool(template.get("required")),
            "state": state,
            "applied_template_version": applied,
            "desired_template_version": desired,
            "actual_status": snapshot.get("status") if snapshot else None,
            "actual_prompt_hash": (
                hashlib.sha256(snapshot["prompt"].encode("utf-8")).hexdigest()
                if snapshot and isinstance(snapshot.get("prompt"), str)
                else None
            ),
            "matching_task_ids": sorted(matching_ids),
        })
    return {
        "status": "degraded" if warnings else "complete",
        "tasks": tasks,
        "warnings": warnings,
        "runtime_verified": not warnings,
    }


def bind_automation(config_path: Path, codex: Path, vault: Path, logical_id: str, task_id: str) -> dict:
    templates = automation_templates()
    if logical_id not in templates:
        return {
            "status": "failed",
            "codex_home": str(codex),
            "obsidian_vault": str(vault),
            "config": str(config_path),
            "errors": [f"未知托管定时任务: {logical_id}"],
            "warnings": [],
        }
    template = templates[logical_id]
    snapshot, snapshot_error = automation_snapshot(codex, task_id)
    if snapshot_error:
        return {
            "status": "failed",
            "codex_home": str(codex),
            "obsidian_vault": str(vault),
            "config": str(config_path),
            "errors": [snapshot_error],
            "warnings": [],
        }
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
        return {
            "status": "failed",
            "codex_home": str(codex),
            "obsidian_vault": str(vault),
            "config": str(config_path),
            "errors": [f"托管定时任务与模板不一致: {logical_id}（{', '.join(mismatches)}）"],
            "warnings": [],
        }
    with config_lock(config_path):
        local = load_json(config_path)
        bindings = local.get("managed_automations")
        if not isinstance(bindings, dict):
            bindings = {}
            local["managed_automations"] = bindings
        bindings[logical_id] = {
            "task_id": task_id,
            "applied_template_version": template["template_version"],
            "status": "bound",
            "readback": {
                "status": snapshot.get("status"),
                "name": snapshot.get("name"),
                "prompt_hash": hashlib.sha256(snapshot["prompt"].encode("utf-8")).hexdigest(),
                "verified_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            },
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        atomic_write_json(config_path, local, config_path.with_suffix(config_path.suffix + ".bak"))
    return {
        "status": "passed",
        "operation": "bind-automation",
        "codex_home": str(codex),
        "obsidian_vault": str(vault),
        "config": str(config_path),
        "logical_id": logical_id,
        "task_id": task_id,
        "template_version": template["template_version"],
        "actual_status": snapshot.get("status"),
        "errors": [],
        "warnings": [],
    }


def run_codex_json(arguments: list[str]) -> tuple[dict | None, str | None]:
    codex = shutil.which("codex")
    if not codex:
        return None, "未找到Codex CLI，跳过配套插件检测"
    result = subprocess.run(
        [codex, *arguments, "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode:
        return None, (result.stderr or result.stdout).strip()
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        return None, f"Codex CLI返回了无效JSON: {error}"
    return value, None


def installed_xiaoh_plugin() -> tuple[dict | None, str | None]:
    snapshot, error = run_codex_json(["plugin", "list"])
    if error:
        return None, error
    matches = [
        item
        for item in snapshot.get("installed", [])
        if item.get("pluginId") == "xiaoh@xiaoh" and item.get("enabled")
    ]
    if len(matches) != 1:
        return None, f"无法唯一识别已启用的小H插件: {len(matches)}"
    item = matches[0]
    version = item.get("version")
    if not isinstance(version, str) or not version:
        return None, "已启用的小H插件缺少版本"
    return {
        "plugin_id": item["pluginId"],
        "version": version,
        "source": item.get("source"),
    }, None


def companion_report(install_missing: bool = False) -> dict:
    manifest = load_json(DEPENDENCY_MANIFEST)
    warnings: list[str] = []
    errors: list[str] = []
    installed_now: list[str] = []
    plugins: list[dict] = []

    plugin_snapshot, plugin_error = run_codex_json(["plugin", "list"])
    marketplace_snapshot, marketplace_error = run_codex_json(["plugin", "marketplace", "list"])
    if plugin_error:
        warnings.append(plugin_error)
        installed_ids: set[str] = set()
    else:
        installed_ids = {
            item["pluginId"]
            for item in plugin_snapshot.get("installed", [])
            if item.get("enabled")
        }
    if marketplace_error:
        marketplace_names: set[str] = set()
    else:
        marketplace_names = {
            item["name"] for item in marketplace_snapshot.get("marketplaces", [])
        }

    for dependency in manifest["codex_plugins"]:
        plugin_id = dependency["id"]
        marketplace = plugin_id.rsplit("@", 1)[-1]
        installed = plugin_id in installed_ids
        detail = {**dependency, "status": "installed" if installed else "missing"}
        if not installed and install_missing and dependency.get("auto_install") and not plugin_error:
            source = dependency.get("marketplace_source")
            if source and marketplace not in marketplace_names:
                arguments = ["plugin", "marketplace", "add", source]
                if dependency.get("marketplace_ref"):
                    arguments.extend(["--ref", dependency["marketplace_ref"]])
                _, error = run_codex_json(arguments)
                if error:
                    detail["install_error"] = error
                else:
                    marketplace_names.add(marketplace)
            if not detail.get("install_error"):
                _, error = run_codex_json(["plugin", "add", plugin_id])
                if error:
                    detail["install_error"] = error
                else:
                    detail["status"] = "installed"
                    installed_ids.add(plugin_id)
                    installed_now.append(plugin_id)
        if detail["status"] != "installed":
            message = f"配套插件不可用: {plugin_id}（{dependency['purpose']}）"
            if detail.get("install_error"):
                message += f": {detail['install_error']}"
            if dependency["level"] == "required":
                errors.append(message)
            elif dependency["level"] == "recommended":
                warnings.append(message)
        plugins.append(detail)

    external: list[dict] = []
    for dependency in manifest.get("external_capabilities", []):
        available = any(shutil.which(command) for command in dependency.get("commands", []))
        detail = {**dependency, "status": "available" if available else "missing"}
        if not available:
            message = f"外部增强能力不可用: {dependency['id']}（{dependency['purpose']}）"
            if dependency["level"] == "required":
                errors.append(message)
            elif dependency["level"] == "recommended":
                warnings.append(message)
        external.append(detail)

    return {
        "status": "failed" if errors else ("degraded" if warnings else "complete"),
        "bundled_skills": manifest["bundled_skills"],
        "plugins": plugins,
        "external_capabilities": external,
        "installed_now": installed_now,
        "warnings": list(dict.fromkeys(warnings)),
        "errors": errors,
    }


def playbook_adapter_report(
    local: dict, playbook_command: str = "playbook"
) -> dict:
    mode = integration_mode(local, "playbook")
    adapter = RUNTIME / "codex/agent-system/playbook_adapter.py"
    if not adapter.is_file():
        return {
            "status": "missing",
            "mode": mode,
            "version": None,
            "errors": [f"缺少小H Playbook适配器: {adapter}"],
        }
    if mode == "disabled":
        return {
            "status": "not_enabled",
            "mode": mode,
            "command": playbook_command,
            "version": None,
            "worker_json_contract": False,
            "task_status_contract": False,
            "errors": [],
        }
    executable = shutil.which(playbook_command)
    if not executable:
        return {
            "status": "not_enabled" if mode == "auto" else "missing",
            "mode": mode,
            "command": playbook_command,
            "version": None,
            "worker_json_contract": False,
            "task_status_contract": False,
            "errors": (
                [] if mode == "auto"
                else [f"未找到Playbook命令: {playbook_command}"]
            ),
        }
    completed = subprocess.run(
        [
            sys.executable,
            str(adapter),
            "probe",
            "--mode",
            mode,
            "--playbook-command",
            executable,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "status": "incompatible",
            "mode": mode,
            "version": None,
            "errors": [(completed.stderr or completed.stdout).strip() or "适配器未返回JSON"],
        }
    if not isinstance(result, dict):
        return {
            "status": "incompatible",
            "mode": mode,
            "version": None,
            "errors": ["适配器返回值不是JSON对象"],
        }
    return result


def resolve_paths(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    config_path = Path(args.config).expanduser() if args.config else default_local_config()
    local = load_json(config_path, {})
    codex_value = args.codex_home or os.environ.get("CODEX_HOME") or local.get("codex_home")
    vault_value = args.vault or os.environ.get("XIAOH_VAULT") or local.get("obsidian_vault")
    codex = Path(codex_value).expanduser() if codex_value else Path.home() / ".codex"
    vault = Path(vault_value).expanduser() if vault_value else Path.home() / "obsidian/development-vault"
    return codex.resolve(), vault.resolve(), config_path.resolve()


def merge_marked_block(current: str, incoming: str, marker: str) -> str:
    start = f"<!-- {marker}:start -->"
    end = f"<!-- {marker}:end -->"
    pattern = re.compile(re.escape(start) + r"[\s\S]*?" + re.escape(end))
    match = pattern.search(incoming)
    if not match:
        raise ValueError(f"源文件缺少区块: {marker}")
    existing = pattern.search(current)
    if existing:
        return current[: existing.start()] + match.group(0) + current[existing.end() :]
    separator = "\n\n" if current.strip() else ""
    return current.rstrip() + separator + match.group(0) + "\n"


def merge_config_block(current: str, incoming: str, marker: str) -> str:
    start = f"# {marker}:start"
    end = f"# {marker}:end"
    pattern = re.compile(re.escape(start) + r"[\s\S]*?" + re.escape(end))
    match = pattern.search(incoming)
    if not match:
        raise ValueError(f"源配置缺少区块: {marker}")
    existing = pattern.search(current)
    if existing:
        return current[: existing.start()] + match.group(0) + current[existing.end() :]
    separator = "\n\n" if current.strip() else ""
    return current.rstrip() + separator + match.group(0) + "\n"


def update_agents_section(config: str) -> str:
    values = {"max_threads": "4", "max_depth": "1", "interrupt_message": "true"}
    match = re.search(r"^\[agents\]\s*$([\s\S]*?)(?=^\[|\Z)", config, re.MULTILINE)
    if not match:
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


def backup_item(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True)
    else:
        shutil.copy2(source, destination)


def replace_placeholders(roots: list[Path], replacements: list[tuple[str, str]]) -> None:
    for root in roots:
        paths = [root] if root.is_file() else root.rglob("*")
        for path in paths:
            if not path.is_file() or path.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            text = path.read_text(encoding="utf-8")
            updated = text
            for old, new in replacements:
                updated = updated.replace(old, new)
            if updated != text:
                atomic_write_text(path, updated)


def managed_vault_files() -> dict[str, dict]:
    manifest = load_json(VAULT_MANIFEST)
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError(f"{VAULT_MANIFEST} 的 files 必须是对象")
    return files


def vault_template_report(vault: Path) -> dict:
    source = RUNTIME / "obsidian/development-vault"
    warnings = []
    files = []
    for relative in managed_vault_files():
        source_path = source / relative
        destination = vault / relative
        expected = file_hash(source_path)
        actual = file_hash(destination) if destination.is_file() else None
        state = "current" if actual == expected else ("missing" if actual is None else "drifted")
        if state != "current":
            warnings.append(f"Vault受管模板未升级: {relative}（{state}）")
        files.append({"path": relative, "state": state, "expected_hash": expected, "actual_hash": actual})
    return {"status": "degraded" if warnings else "complete", "files": files, "warnings": warnings}


def sync_vault_runtime(vault: Path) -> tuple[list[Path], list[str]]:
    source = RUNTIME / "obsidian/development-vault"
    touched: list[Path] = []
    conflicts: list[str] = []
    managed = managed_vault_files()
    state_path = vault / ".xiaoh-managed.json"
    state = load_json(state_path, {"schema_version": "1.0", "files": {}})
    previous_files = state.get("files")
    if not isinstance(previous_files, dict):
        previous_files = {}
    next_files: dict[str, str] = {}
    for old_relative, new_relative in (
        ("04-架构与决策/Agent协作角色.md", "90-个人系统/Agent协作角色.md"),
        ("04-架构与决策/Agent进化台账.md", "90-个人系统/Agent进化台账.md"),
    ):
        old_path = vault / old_relative
        new_path = vault / new_relative
        if old_path.is_file() and not new_path.exists():
            new_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(old_path, new_path)
        elif old_path.is_file() and new_path.exists():
            conflicts.append(old_relative)
    for source_path in source.rglob("*"):
        relative = source_path.relative_to(source).as_posix()
        destination = vault / relative
        if source_path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif relative in managed:
            destination.parent.mkdir(parents=True, exist_ok=True)
            source_digest = file_hash(source_path)
            current_digest = file_hash(destination) if destination.is_file() else None
            legacy = managed[relative].get("legacy_hashes", [])
            if (
                current_digest is None
                or current_digest == source_digest
                or current_digest in legacy
                or current_digest == previous_files.get(relative)
            ):
                if current_digest != source_digest:
                    shutil.copy2(source_path, destination)
                    touched.append(destination)
                next_files[relative] = source_digest
            else:
                conflicts.append(relative)
        elif not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)
            touched.append(destination)
    for relative in ("AGENTS.md", "90-个人系统/Agent协作角色.md"):
        destination = vault / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, destination)
        if destination not in touched:
            touched.append(destination)
    (vault / ".obsidian").mkdir(exist_ok=True)
    atomic_write_json(
        state_path,
        {
            "schema_version": "1.0",
            "template_version": load_json(PLUGIN_MANIFEST)["version"],
            "files": next_files,
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
    )
    if state_path not in touched:
        touched.append(state_path)
    return touched, conflicts


def copy_runtime(
    codex: Path, vault: Path, config_path: Path | None = None
) -> tuple[Path, list[Path], list[str]]:
    source = RUNTIME / "codex"
    for name in ("agents", "contexts", "agent-system", "hooks"):
        shutil.copytree(source / name, codex / name, dirs_exist_ok=True)
    reserved = codex / "agents/xiaoh.toml"
    if reserved.exists():
        reserved.unlink()
    vault_files, vault_conflicts = sync_vault_runtime(vault)

    incoming = (source / "AGENTS.md").read_text(encoding="utf-8")
    override = codex / "AGENTS.override.md"
    target_agents = override if override.exists() and override.read_text(encoding="utf-8").strip() else codex / "AGENTS.md"
    merged = target_agents.read_text(encoding="utf-8") if target_agents.exists() else ""
    for marker in ("codebase-memory-mcp", "global-agent-common-contract"):
        merged = merge_marked_block(merged, incoming, marker)
    atomic_write_text(target_agents, merged.rstrip() + "\n")

    codex_config_path = codex / "config.toml"
    config = codex_config_path.read_text(encoding="utf-8") if codex_config_path.exists() else ""
    config = update_agents_section(config)
    hook = (source / "root-agent-hook.toml").read_text(encoding="utf-8")
    hook = hook.replace("__CODEX_HOME__", codex.as_posix())
    hook = hook.replace("__PYTHON_WINDOWS__", Path(sys.executable).resolve().as_posix())
    hook = hook.replace(
        "__XIAOH_CONFIG__",
        (config_path or default_local_config()).expanduser().resolve().as_posix(),
    )
    config = merge_config_block(config, hook, "xiaoh-root-agent-hook")
    atomic_write_text(codex_config_path, config.rstrip() + "\n")
    return target_agents, vault_files, vault_conflicts


def refresh_templates(codex: Path) -> None:
    template = codex / "agent-system/task-context.template.json"
    run_record = codex / "agent-system/run-record.template.json"
    context = load_json(template)
    context["freshness"]["checked_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    atomic_write_json(template, context)
    record = load_json(run_record)
    record["context_hash"] = (
        canonical_json_hash(context)
        if context.get("schema_version") == "1.6"
        else hashlib.sha256(template.read_bytes()).hexdigest()
    )
    atomic_write_json(run_record, record)


def doctor_commands(codex: Path, runtime: bool = False) -> list[list[str]]:
    commands = [
        [sys.executable, str(codex / "agent-system/validate.py"), "--self-test"],
        [sys.executable, str(codex / "hooks/block_reserved_root_agent.py"), "--self-test"],
        [sys.executable, str(codex / "hooks/guard_vault_writes.py"), "--self-test"],
        [sys.executable, str(codex / "agent-system/validate.py"), "--task-context", str(codex / "agent-system/task-context.template.json")],
        [sys.executable, str(codex / "agent-system/validate.py"), "--run-record", str(codex / "agent-system/run-record.template.json")],
        [
            sys.executable,
            str(codex / "agent-system/validate.py"),
            "--routing-case",
            "java-single-repo-fix",
            "--intent-domain",
            "business_project",
            "--selected-agents",
            "java_code_explorer,java_implementer,code_quality_reviewer,test_integration_verifier",
        ],
    ]
    if runtime:
        commands.append(
            [sys.executable, str(codex / "hooks/verify_agent_hook_runtime.py"), "--codex-home", str(codex), "--cwd", os.getcwd()]
        )
    return commands


def doctor(
    codex: Path,
    vault: Path,
    config_path: Path,
    runtime: bool = False,
    active_skill_root: Path | None = None,
) -> dict:
    companions = companion_report()
    errors: list[str] = list(companions["errors"])
    warnings: list[str] = []
    local: dict = {}
    config_error = None
    try:
        local = load_json(config_path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        config_error = exc
        errors.append(f"小H本地配置无效: {config_path}: {exc}")
    try:
        playbook_adapter = playbook_adapter_report(local)
    except ValueError as exc:
        playbook_adapter = {
            "status": "invalid_configuration",
            "mode": None,
            "version": None,
            "errors": [str(exc)],
        }
        errors.append(f"小H集成配置无效: {exc}")
    if (
        playbook_adapter.get("mode") == "enabled"
        and playbook_adapter.get("status") != "compatible"
    ):
        adapter_errors = playbook_adapter.get("errors") or [
            "实际worker/status状态契约尚未验证: "
            + str(playbook_adapter.get("status"))
        ]
        warnings.extend(
            "Playbook适配器: " + message
            for message in adapter_errors
        )
    plugin_version = load_json(PLUGIN_MANIFEST)["version"]
    active_plugin, active_plugin_error = installed_xiaoh_plugin()
    if active_plugin_error:
        warnings.append(f"无法验证已启用插件版本: {active_plugin_error}")
    elif active_plugin["version"].partition("+codex.")[0] != plugin_version.partition("+codex.")[0]:
        errors.append(
            f"小H已启用插件版本漂移: 当前 {active_plugin['version']}，检查器 {plugin_version}"
        )
    loaded_skill_version = None
    if active_skill_root is None:
        warnings.append("当前线程实际Skill版本未验证；请从xiaoh-doctor Skill传入--active-skill-root")
    else:
        skill_root = active_skill_root.expanduser().resolve()
        try:
            skill_manifest = next(
                candidate / ".codex-plugin/plugin.json"
                for candidate in (skill_root, *skill_root.parents)
                if (candidate / ".codex-plugin/plugin.json").is_file()
            )
            loaded_skill_version = load_json(skill_manifest)["version"]
            if loaded_skill_version.partition("+codex.")[0] != plugin_version.partition("+codex.")[0]:
                errors.append(
                    f"当前线程Skill版本漂移: 已加载 {loaded_skill_version}，检查器 {plugin_version}"
                )
        except (OSError, KeyError, StopIteration, TypeError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"无法验证当前线程Skill根目录: {skill_root}: {exc}")
    if config_error is None:
        try:
            configured_vault = Path(local["obsidian_vault"]).expanduser().resolve()
            installed_version = local["installed_version"]
            if not isinstance(installed_version, str):
                raise ValueError("installed_version必须是字符串")
            if configured_vault != vault:
                errors.append(f"Vault参数与小H配置不一致: {vault} != {configured_vault}")
            if installed_version.partition("+codex.")[0] != plugin_version.partition("+codex.")[0]:
                errors.append(f"小H运行时版本漂移: 已部署 {installed_version}，当前插件 {plugin_version}")
        except (KeyError, TypeError, ValueError) as exc:
            installed_version = None
            errors.append(f"小H本地配置无效: {config_path}: {exc}")
    else:
        installed_version = None
    automations = automation_report(local, codex)
    warnings.extend(automations["warnings"])
    workspace_registry = workspace_registry_report(local)
    errors.extend(workspace_registry["errors"])
    warnings.extend(workspace_registry["warnings"])
    if not (vault / ".obsidian").is_dir():
        errors.append(f"配置路径不是有效Obsidian Vault: {vault}")
    vault_templates = vault_template_report(vault)
    warnings.extend(vault_templates["warnings"])
    actual_agents = {path.stem for path in (codex / "agents").glob("*.toml")}
    if "xiaoh" in actual_agents:
        errors.append("保留根线程 xiaoh 被错误注册为子 Agent")
    missing = sorted(REQUIRED_AGENTS - actual_agents)
    if missing:
        errors.append("缺少 Agent: " + ", ".join(missing))
    unexpected = sorted(actual_agents - REQUIRED_AGENTS)
    if unexpected:
        errors.append("存在未登记 Agent: " + ", ".join(unexpected))

    override = codex / "AGENTS.override.md"
    active_agents = override if override.exists() and override.read_text(encoding="utf-8").strip() else codex / "AGENTS.md"
    if not active_agents.exists() or "<!-- global-agent-common-contract:start -->" not in active_agents.read_text(encoding="utf-8"):
        errors.append("生效的 AGENTS 文件缺少小H公共契约")
    codex_config_path = codex / "config.toml"
    config = codex_config_path.read_text(encoding="utf-8") if codex_config_path.exists() else ""
    for expected in (
        "max_threads = 4", "max_depth = 1", "interrupt_message = true",
        "# xiaoh-root-agent-hook:start", "guard_vault_writes.py",
    ):
        if expected not in config:
            errors.append(f"config.toml 缺少: {expected}")
    for required in (
        codex / "agent-system/validate.py",
        codex / "agent-system/playbook_adapter.py",
        codex / "hooks/block_reserved_root_agent.py",
        codex / "hooks/guard_vault_writes.py",
        vault / "90-个人系统/Agent协作角色.md",
        vault / "90-个人系统/Agent进化台账.md",
    ):
        if not required.exists():
            errors.append(f"缺少文件: {required}")

    commands = doctor_commands(codex, runtime)
    env = os.environ.copy()
    env.update({"CODEX_HOME": str(codex), "XIAOH_VAULT": str(vault), "XIAOH_CONFIG": str(config_path)})
    if not errors:
        for command in commands:
            result = subprocess.run(command, env=env, capture_output=True, text=True, encoding="utf-8")
            if result.returncode:
                summary = (result.stderr or result.stdout).strip()
                errors.append(f"命令失败: {' '.join(command)}\n{summary}")
                break
    return {
        "status": "failed" if errors else ("degraded" if warnings or companions["warnings"] else "passed"),
        "codex_home": str(codex),
        "obsidian_vault": str(vault),
        "config": str(config_path),
        "plugin_version": plugin_version,
        "installed_version": installed_version,
        "active_plugin": active_plugin,
        "loaded_skill_version": loaded_skill_version,
        "runtime_checked": runtime,
        "capabilities": companions,
        "automations": automations,
        "workspace_registry": workspace_registry,
        "playbook_adapter": playbook_adapter,
        "vault_templates": vault_templates,
        "warnings": list(dict.fromkeys([*companions["warnings"], *warnings])),
        "errors": errors,
    }


def install(args: argparse.Namespace, mode: str) -> dict:
    codex, vault, config_path = resolve_paths(args)
    try:
        local = load_json(config_path, {})
        integration_mode(local, "playbook")
        workspace_registry = workspace_registry_report(local)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "failed",
            "operation": mode,
            "codex_home": str(codex),
            "obsidian_vault": str(vault),
            "errors": [f"小H本地配置无效，未执行安装或更新: {config_path}: {exc}"],
        }
    if workspace_registry["errors"]:
        return {
            "status": "failed",
            "operation": mode,
            "codex_home": str(codex),
            "obsidian_vault": str(vault),
            "errors": workspace_registry["errors"],
            "warnings": workspace_registry["warnings"],
        }
    existing_agents = {path.stem for path in (codex / "agents").glob("*.toml")}
    conflicts = sorted(existing_agents - REQUIRED_AGENTS)
    if conflicts:
        return {
            "status": "failed",
            "operation": mode,
            "codex_home": str(codex),
            "obsidian_vault": str(vault),
            "errors": ["现有未登记 Agent 需要先纳入角色目录或移出: " + ", ".join(conflicts)],
        }
    companions = companion_report(install_missing=True)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    backup = Path.home() / f".xiaoh/backups/{timestamp}"
    for source, relative in (
        (codex / "AGENTS.md", "codex/AGENTS.md"),
        (codex / "AGENTS.override.md", "codex/AGENTS.override.md"),
        (codex / "config.toml", "codex/config.toml"),
        (codex / "agents", "codex/agents"),
        (codex / "contexts", "codex/contexts"),
        (codex / "agent-system", "codex/agent-system"),
        (codex / "hooks", "codex/hooks"),
        (vault, "obsidian/development-vault"),
        (config_path, "local/config.json"),
    ):
        backup_item(source, backup / relative)

    codex.mkdir(parents=True, exist_ok=True)
    vault.mkdir(parents=True, exist_ok=True)
    target_agents, vault_files, vault_conflicts = copy_runtime(
        codex, vault, config_path
    )
    replace_placeholders(
        [target_agents, codex / "agents", codex / "contexts", codex / "agent-system", codex / "hooks", *vault_files],
        [
            ("__CODEX_HOME__/AGENTS.md", target_agents.as_posix()),
            ("__CODEX_HOME__", codex.as_posix()),
            ("__XIAOH_CONFIG__", config_path.as_posix()),
            ("__OBSIDIAN_VAULT__", vault.as_posix()),
            ("__USER_HOME__", Path.home().as_posix()),
        ],
    )
    refresh_templates(codex)
    for executable in (
        codex / "agent-system/validate.py",
        codex / "agent-system/playbook_adapter.py",
        codex / "hooks/block_reserved_root_agent.py",
        codex / "hooks/guard_vault_writes.py",
        codex / "hooks/verify_agent_hook_runtime.py",
    ):
        executable.chmod(executable.stat().st_mode | 0o111)

    version = load_json(PLUGIN_MANIFEST)["version"]
    with config_lock(config_path):
        local = load_json(config_path, {})
        try:
            merged = merged_local_config(local, codex, vault, version)
        except ValueError as exc:
            return {
                "status": "failed",
                "operation": mode,
                "codex_home": str(codex),
                "obsidian_vault": str(vault),
                "errors": [str(exc)],
            }
        atomic_write_json(config_path, merged)
    active_skill_root = (
        Path(args.active_skill_root).expanduser().resolve()
        if getattr(args, "active_skill_root", None)
        else None
    )
    result = doctor(codex, vault, config_path, active_skill_root=active_skill_root)
    if vault_conflicts:
        result["warnings"] = [
            *result["warnings"],
            "Vault受管模板存在用户修改，未自动覆盖: " + ", ".join(vault_conflicts),
        ]
        if result["status"] == "passed":
            result["status"] = "degraded"
    result["capabilities"] = companions
    result.update({"operation": mode, "version": version, "backup": str(backup), "config": str(config_path)})
    return result


def emit(result: dict, as_json: bool, allow_degraded: bool = False) -> int:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"XiaoH: {result['status']}")
        print(f"Codex: {result['codex_home']}")
        print(f"Obsidian: {result['obsidian_vault']}")
        if result.get("backup"):
            print(f"Backup: {result['backup']}")
        for error in result.get("errors", []):
            print(f"ERROR: {error}", file=sys.stderr)
        for warning in result.get("warnings", []):
            print(f"WARNING: {warning}", file=sys.stderr)
        if result["status"] == "passed" and result.get("operation"):
            print("重启 Codex，在 /hooks 中审核并信任四个 XiaoH Hook，然后运行 doctor --runtime。")
        elif result["status"] == "degraded" and result.get("operation"):
            print(
                "小H核心运行时已部署，但初始化尚未完成；请在新Codex任务中运行"
                " $xiaoh:xiaoh-setup 或 $xiaoh:xiaoh-update 完成托管任务校准。"
            )
    return 0 if result["status"] == "passed" or (allow_degraded and result["status"] == "degraded") else 1


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in (
        "plan", "setup", "update", "doctor", "companions", "bind-automation",
        "resolve-workspace", "register-workspace",
    ):
        command = subparsers.add_parser(name)
        if name != "companions":
            command.add_argument("--codex-home")
            command.add_argument("--vault")
            command.add_argument("--config")
        if name in {"setup", "update", "doctor"}:
            command.add_argument("--active-skill-root")
        command.add_argument("--json", action="store_true")
        if name in {"setup", "update"}:
            command.add_argument("--allow-degraded", action="store_true")
        if name == "doctor":
            command.add_argument("--runtime", action="store_true")
        if name == "companions":
            command.add_argument("--install", action="store_true")
        if name == "bind-automation":
            command.add_argument("--logical-id", required=True)
            command.add_argument("--task-id", required=True)
        if name == "resolve-workspace":
            command.add_argument("--path", default=os.getcwd())
        if name == "register-workspace":
            command.add_argument("--workspace-id", required=True)
            command.add_argument("--project", required=True)
            command.add_argument("--system", required=True)
            command.add_argument("--root", required=True)
    return parser


def main() -> int:
    configure_stdio()
    args = build_parser().parse_args()
    if args.command == "companions":
        result = companion_report(args.install)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"XiaoH capabilities: {result['status']}")
            for warning in result["warnings"]:
                print(f"WARNING: {warning}", file=sys.stderr)
            for error in result["errors"]:
                print(f"ERROR: {error}", file=sys.stderr)
        return 1 if result["status"] == "failed" else 0
    codex, vault, config_path = resolve_paths(args)
    if args.command == "plan":
        return emit(
            {
                "status": "passed",
                "codex_home": str(codex),
                "obsidian_vault": str(vault),
                "config": str(config_path),
                "existing_codex": codex.exists(),
                "existing_vault": vault.exists(),
                "errors": [],
            },
            args.json,
        )
    if args.command == "bind-automation":
        return emit(bind_automation(config_path, codex, vault, args.logical_id, args.task_id), args.json)
    if args.command == "resolve-workspace":
        resolution = resolve_workspace(load_json(config_path, {}), Path(args.path))
        result = {
            **resolution,
            "resolution": resolution["status"],
            "status": "failed" if resolution["status"] == "conflict" else "passed",
            "codex_home": str(codex),
            "obsidian_vault": str(vault),
            "config": str(config_path),
        }
        return emit(result, args.json)
    if args.command == "register-workspace":
        return emit(
            register_workspace(
                config_path, codex, vault, args.workspace_id, args.project, args.system, args.root
            ),
            args.json,
        )
    if args.command in {"setup", "update"}:
        return emit(install(args, args.command), args.json, args.allow_degraded)
    active_skill_root = Path(args.active_skill_root) if args.active_skill_root else None
    return emit(doctor(codex, vault, config_path, args.runtime, active_skill_root), args.json)


if __name__ == "__main__":
    raise SystemExit(main())
