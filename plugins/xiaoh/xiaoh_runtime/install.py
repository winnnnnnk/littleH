"""XiaoH modular runtime boundary."""

from __future__ import annotations

from .common import *
from .config import *
from .workspace import *
from .automation import *
from .plugin_state import *
from .vault_runtime import *
from .doctor import *


def plan_installation(args):
    """Build the read-only 3.1.2 clean-install plan."""
    codex, vault, config_path = resolve_paths(args)
    local = load_json(config_path, {}) if config_path.is_file() else {}
    target_version = load_json(PLUGIN_MANIFEST)["version"]
    return {
        "status": "passed",
        "operation": getattr(args, "command", "plan"),
        "source_version": local.get("installed_version"),
        "target_version": target_version,
        "mode": "same_version_sync" if local.get("installed_version") == target_version else "clean_install",
        "codex_home": str(codex),
        "obsidian_vault": str(vault),
        "config": str(config_path),
        "errors": [],
        "warnings": [],
        "actual_writes": [],
        "unresolved_items": [],
        "recovery_conditions": [],
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
    companions = companion_report(install_missing=True)
    if companions.get("errors"):
        return {
            "status": "failed",
            "operation": mode,
            "codex_home": str(codex),
            "obsidian_vault": str(vault),
            "companions": companions,
            "errors": [
                "配套能力或治理资产校验失败，未执行安装或更新",
                *companions["errors"],
            ],
            "warnings": companions.get("warnings", []),
        }
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    backup = config_path.parent / f"backups/{timestamp}"
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
    for name in ("contexts", "agent-system", "hooks"):
        target = codex / name
        if target.is_symlink():
            return {
                "status": "failed",
                "operation": mode,
                "codex_home": str(codex),
                "obsidian_vault": str(vault),
                "backup": str(backup),
                "errors": [f"受管目录不能是符号链接: {target}"],
            }
        if target.exists():
            shutil.rmtree(target)
    for legacy_agent in (
        "code_quality_reviewer",
        "frontend_implementer",
        "java_architect",
        "java_code_explorer",
        "java_implementer",
        "pki_domain_expert",
        "pki_security_reviewer",
        "test_integration_verifier",
    ):
        target = codex / "agents" / f"{legacy_agent}.toml"
        if target.is_symlink() or target.is_file():
            target.unlink()
    removed_vault_asset = vault / "02-领域知识/知识评审模板.md"
    if removed_vault_asset.is_symlink() or removed_vault_asset.is_file():
        removed_vault_asset.unlink()
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
