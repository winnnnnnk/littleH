"""XiaoH modular runtime boundary."""

from __future__ import annotations

from .common import *


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
        if (
            not isinstance(logical_id, str)
            or not logical_id
            or not isinstance(version, str)
            or not version
        ):
            raise ValueError(
                f"{AUTOMATION_MANIFEST} 模板缺少 logical_id 或 template_version"
            )
        if logical_id in result:
            raise ValueError(
                f"{AUTOMATION_MANIFEST} 包含重复 logical_id: {logical_id}"
            )
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

def resolve_paths(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    config_path = Path(args.config).expanduser() if args.config else default_local_config()
    local = load_json(config_path, {})
    codex_value = args.codex_home or os.environ.get("CODEX_HOME") or local.get("codex_home")
    vault_value = args.vault or os.environ.get("XIAOH_VAULT") or local.get("obsidian_vault")
    codex = Path(codex_value).expanduser() if codex_value else Path.home() / ".codex"
    vault = Path(vault_value).expanduser() if vault_value else Path.home() / "obsidian/development-vault"
    return codex.resolve(), vault.resolve(), config_path.resolve()


def marked_block(text: str, marker: str) -> str | None:
    start = f"<!-- {marker}:start -->"
    end = f"<!-- {marker}:end -->"
    match = re.search(re.escape(start) + r"[\s\S]*?" + re.escape(end), text)
    return match.group(0) if match else None


def markdown_section(text: str, heading: str) -> str | None:
    match = re.search(
        rf"^{re.escape(heading)}\s*$[\s\S]*?(?=^##\s|\Z)",
        text,
        re.MULTILINE,
    )
    return match.group(0).strip() if match else None


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
