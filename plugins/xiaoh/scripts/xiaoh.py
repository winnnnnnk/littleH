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
from datetime import datetime
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
RUNTIME = PLUGIN_ROOT / "runtime"
PLUGIN_MANIFEST = PLUGIN_ROOT / ".codex-plugin/plugin.json"
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
    return Path.home() / ".xiaoh/config.json"


def load_json(path: Path, default: dict | None = None) -> dict:
    if not path.exists() and default is not None:
        return default
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"{path} 必须包含 JSON 对象")
    return value


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
                path.write_text(updated, encoding="utf-8")


def copy_runtime(codex: Path, vault: Path) -> Path:
    source = RUNTIME / "codex"
    for name in ("agents", "contexts", "agent-system", "hooks"):
        shutil.copytree(source / name, codex / name, dirs_exist_ok=True)
    reserved = codex / "agents/xiaoh.toml"
    if reserved.exists():
        reserved.unlink()
    shutil.copytree(RUNTIME / "obsidian/development-vault", vault, dirs_exist_ok=True)

    incoming = (source / "AGENTS.md").read_text(encoding="utf-8")
    override = codex / "AGENTS.override.md"
    target_agents = override if override.exists() and override.read_text(encoding="utf-8").strip() else codex / "AGENTS.md"
    merged = target_agents.read_text(encoding="utf-8") if target_agents.exists() else ""
    for marker in ("codebase-memory-mcp", "global-agent-common-contract"):
        merged = merge_marked_block(merged, incoming, marker)
    target_agents.write_text(merged.rstrip() + "\n", encoding="utf-8")

    config_path = codex / "config.toml"
    config = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    config = update_agents_section(config)
    hook = (source / "root-agent-hook.toml").read_text(encoding="utf-8")
    hook = hook.replace("__CODEX_HOME__", codex.as_posix())
    config = merge_config_block(config, hook, "xiaoh-root-agent-hook")
    config_path.write_text(config.rstrip() + "\n", encoding="utf-8")
    return target_agents


def refresh_templates(codex: Path) -> None:
    template = codex / "agent-system/task-context.template.json"
    run_record = codex / "agent-system/run-record.template.json"
    context = load_json(template)
    context["freshness"]["checked_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    template.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    record = load_json(run_record)
    record["context_hash"] = hashlib.sha256(template.read_bytes()).hexdigest()
    run_record.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def doctor(codex: Path, vault: Path, runtime: bool = False) -> dict:
    errors: list[str] = []
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
    config_path = codex / "config.toml"
    config = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    for expected in ("max_threads = 4", "max_depth = 1", "interrupt_message = true", "# xiaoh-root-agent-hook:start"):
        if expected not in config:
            errors.append(f"config.toml 缺少: {expected}")
    for required in (
        codex / "agent-system/validate.py",
        codex / "hooks/block_reserved_root_agent.py",
        codex / "hooks/block_reserved_root_agent.ps1",
        vault / "04-架构与决策/Agent协作角色.md",
        vault / "04-架构与决策/Agent进化台账.md",
    ):
        if not required.exists():
            errors.append(f"缺少文件: {required}")

    commands = [
        [sys.executable, str(codex / "agent-system/validate.py"), "--self-test"],
        [sys.executable, str(codex / "hooks/block_reserved_root_agent.py"), "--self-test"],
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
            "java_code_explorer,java_implementer,test_integration_verifier",
        ],
    ]
    if runtime:
        commands.append(
            [sys.executable, str(codex / "hooks/verify_agent_hook_runtime.py"), "--codex-home", str(codex), "--cwd", os.getcwd()]
        )
    env = os.environ.copy()
    env.update({"CODEX_HOME": str(codex), "XIAOH_VAULT": str(vault)})
    if not errors:
        for command in commands:
            result = subprocess.run(command, env=env, capture_output=True, text=True)
            if result.returncode:
                summary = (result.stderr or result.stdout).strip()
                errors.append(f"命令失败: {' '.join(command)}\n{summary}")
                break
    return {
        "status": "passed" if not errors else "failed",
        "codex_home": str(codex),
        "obsidian_vault": str(vault),
        "runtime_checked": runtime,
        "errors": errors,
    }


def install(args: argparse.Namespace, mode: str) -> dict:
    codex, vault, config_path = resolve_paths(args)
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
    ):
        backup_item(source, backup / relative)

    codex.mkdir(parents=True, exist_ok=True)
    vault.mkdir(parents=True, exist_ok=True)
    target_agents = copy_runtime(codex, vault)
    replace_placeholders(
        [target_agents, codex / "agents", codex / "contexts", codex / "agent-system", codex / "hooks", vault],
        [
            ("__CODEX_HOME__/AGENTS.md", target_agents.as_posix()),
            ("__CODEX_HOME__", codex.as_posix()),
            ("__OBSIDIAN_VAULT__", vault.as_posix()),
            ("__USER_HOME__", Path.home().as_posix()),
        ],
    )
    refresh_templates(codex)
    for executable in (
        codex / "agent-system/validate.py",
        codex / "hooks/block_reserved_root_agent.py",
        codex / "hooks/verify_agent_hook_runtime.py",
    ):
        executable.chmod(executable.stat().st_mode | 0o111)

    version = load_json(PLUGIN_MANIFEST)["version"]
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "codex_home": str(codex),
                "obsidian_vault": str(vault),
                "installed_version": version,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    result = doctor(codex, vault)
    result.update({"operation": mode, "version": version, "backup": str(backup), "config": str(config_path)})
    return result


def emit(result: dict, as_json: bool) -> int:
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
        if result["status"] == "passed" and result.get("operation"):
            print("重启 Codex，在 /hooks 中审核并信任三个 XiaoH Hook，然后运行 doctor --runtime。")
    return 0 if result["status"] == "passed" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "setup", "update", "doctor"):
        command = subparsers.add_parser(name)
        command.add_argument("--codex-home")
        command.add_argument("--vault")
        command.add_argument("--config")
        command.add_argument("--json", action="store_true")
        if name == "doctor":
            command.add_argument("--runtime", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
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
    if args.command in {"setup", "update"}:
        return emit(install(args, args.command), args.json)
    return emit(doctor(codex, vault, args.runtime), args.json)


if __name__ == "__main__":
    raise SystemExit(main())
