"""XiaoH modular runtime boundary."""

from __future__ import annotations

from .common import *
from .config import *
from .workspace import *
from .automation import *
from .plugin_state import *
from .vault_runtime import *

def effective_doctor_view(
    result: dict,
    codex: Path,
    vault: Path,
    runtime: bool,
    config_path: Path | None = None,
) -> dict:
    vault_effective = vault_effective_report(vault)
    required_core = (
        codex / "agent-system/validate.py",
        codex / "agent-system/xiaoh_validator",
        codex / "hooks/block_reserved_root_agent.py",
        codex / "hooks/guard_vault_writes.py",
    )
    core_missing = [str(path) for path in required_core if not path.exists()]
    core_errors = list(result.get("errors", []))
    core_status = "failed" if core_missing or core_errors else "complete"
    hook_errors = [
        error
        for error in result.get("errors", [])
        if "Hook" in error or "/hooks/" in error or "hook" in error.casefold()
    ]
    if hook_errors:
        runtime_gate_status = "failed"
    elif (
        runtime
        and not result.get("errors")
    ):
        runtime_gate_status = "active"
    else:
        runtime_gate_status = "static_valid_runtime_unverified"
    adapter = result.get("playbook_adapter", {})
    mode = adapter.get("mode")
    if mode in {"disabled", "auto"} and adapter.get("status") != "compatible":
        integration_status = "not_enabled"
    elif mode == "enabled" and adapter.get("status") != "compatible":
        integration_status = "degraded"
    else:
        integration_status = "complete"
    required_automation_failures = [
        task
        for task in result.get("automations", {}).get("tasks", [])
        if task.get("required") and task.get("state") != "configured"
    ]
    automation_status = "degraded" if required_automation_failures else "complete"
    vault_status = vault_effective["status"]
    customization_status = (
        "user_customized_compatible"
        if vault_status == "user_customized_compatible"
        else "none"
    )
    if (
        core_status == "failed"
        or runtime_gate_status == "failed"
        or vault_status == "corrupted"
    ):
        effective_status = "failed"
    elif (
        runtime_gate_status != "active"
        or integration_status == "degraded"
        or automation_status == "degraded"
        or vault_status in {"missing", "incompatible_drift"}
    ):
        effective_status = "degraded"
    else:
        effective_status = "complete"
    return {
        "legacy_status": result["status"],
        "effective_status": effective_status,
        "core_status": core_status,
        "runtime_gate_status": runtime_gate_status,
        "integration_status": integration_status,
        "automation_status": automation_status,
        "vault_status": vault_status,
        "customization_status": customization_status,
        "installation_status": "current" if result.get("plugin_version") == result.get("installed_version") else "drifted",
        "components": {
            "core": {"missing": core_missing, "errors": core_errors},
            "runtime_gate": {
                "static_errors": hook_errors,
                "runtime_checked": runtime,
            },
            "integration": adapter,
            "automation": {"required_failures": required_automation_failures},
            "vault": vault_effective,
        },
    }

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
            "java_code_explorer,java_implementer",
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
    effective_status: bool = False,
    run_commands: bool = True,
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
    candidate_plugin_root = None
    if active_plugin_error:
        errors.append(f"无法验证已启用插件及独立候选源: {active_plugin_error}")
    elif active_plugin["version"].partition("+codex.")[0] != plugin_version.partition("+codex.")[0]:
        errors.append(
            f"小H已启用插件版本漂移: 当前 {active_plugin['version']}，检查器 {plugin_version}"
        )
    else:
        active_source = active_plugin.get("source")
        if (
            isinstance(active_source, dict)
            and active_source.get("source") == "local"
            and isinstance(active_source.get("path"), str)
            and active_source["path"].strip()
        ):
            candidate_plugin_root = (
                Path(active_source["path"]).expanduser().resolve()
            )
            if not (
                candidate_plugin_root / ".codex-plugin/plugin.json"
            ).is_file():
                errors.append(
                    "已启用插件的本地候选源缺少plugin.json: {}".format(
                        candidate_plugin_root
                    )
                )
                candidate_plugin_root = None
        else:
            errors.append(
                "已启用插件未提供可独立验证的本地候选源，当前线程插件内容保持unverified"
            )
    loaded_skill_version = None
    loaded_skill_content = {
        "status": "unverified",
        "root": None,
        "drifted_files": [],
    }
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
            loaded_plugin_root = skill_manifest.parent.parent.resolve()
            if candidate_plugin_root is None:
                raise ValueError("缺少可独立验证的插件候选源")
            if candidate_plugin_root == loaded_plugin_root:
                raise ValueError(
                    "插件候选源与当前已加载插件根相同，无法独立验证内容"
                )
            drifted_files = plugin_content_drift(
                loaded_plugin_root,
                candidate_plugin_root,
            )
            loaded_skill_content = {
                "status": "drifted" if drifted_files else "current",
                "root": str(loaded_plugin_root),
                "candidate_root": str(candidate_plugin_root),
                "drifted_files": drifted_files,
            }
            if loaded_skill_version.partition("+codex.")[0] != plugin_version.partition("+codex.")[0]:
                errors.append(
                    f"当前线程Skill版本漂移: 已加载 {loaded_skill_version}，检查器 {plugin_version}"
                )
            elif drifted_files:
                errors.append(
                    "当前线程插件内容漂移: 同版本但有{}个候选受管文件未激活".format(
                        len(drifted_files)
                    )
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
        warnings.append(
            "保留未由xiaoh管理的既有 Agent: " + ", ".join(unexpected)
        )

    override = codex / "AGENTS.override.md"
    active_agents = override if override.exists() and override.read_text(encoding="utf-8").strip() else codex / "AGENTS.md"
    if not active_agents.exists() or "<!-- global-agent-common-contract:start -->" not in active_agents.read_text(encoding="utf-8"):
        errors.append("生效的 AGENTS 文件缺少小H公共契约")
    playbook_version_policy = playbook_version_policy_report(active_agents)
    errors.extend(playbook_version_policy["errors"])
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
    if not errors and run_commands:
        for command in commands:
            result = subprocess.run(command, env=env, capture_output=True, text=True, encoding="utf-8")
            if result.returncode:
                summary = (result.stderr or result.stdout).strip()
                errors.append(f"命令失败: {' '.join(command)}\n{summary}")
                break
    result = {
        "status": "failed" if errors else ("degraded" if warnings or companions["warnings"] else "passed"),
        "codex_home": str(codex),
        "obsidian_vault": str(vault),
        "config": str(config_path),
        "plugin_version": plugin_version,
        "installed_version": installed_version,
        "active_plugin": active_plugin,
        "loaded_skill_version": loaded_skill_version,
        "loaded_skill_content": loaded_skill_content,
        "runtime_checked": runtime,
        "capabilities": companions,
        "automations": automations,
        "workspace_registry": workspace_registry,
        "playbook_adapter": playbook_adapter,
        "playbook_version_policy": playbook_version_policy,
        "vault_templates": vault_templates,
        "warnings": list(dict.fromkeys([*companions["warnings"], *warnings])),
        "errors": errors,
    }
    if effective_status:
        result.update(
            effective_doctor_view(
                result, codex, vault, runtime, config_path=config_path
            )
        )
    return result
