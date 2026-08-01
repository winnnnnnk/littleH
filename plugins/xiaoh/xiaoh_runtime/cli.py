"""XiaoH modular runtime boundary."""

from __future__ import annotations

from .common import *
from .config import *
from .workspace import *
from .automation import *
from .plugin_state import *
from .doctor import *
from .install import *


CLI_RESPONSE_SCHEMA = "xiaoh-cli-response/v1"
CLI_RESPONSE_LIST_FIELDS = (
    "errors",
    "warnings",
    "actual_writes",
    "unresolved_items",
    "recovery_conditions",
)


class CLIArgumentError(ValueError):
    """Argument parsing failed before a command handler was selected."""


class XiaoHArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CLIArgumentError(message)


def normalize_response(result: dict) -> dict:
    """Apply the stable JSON envelope without discarding command-specific fields."""
    normalized = dict(result)
    source_schema = normalized.get("schema_version")
    if source_schema and source_schema != CLI_RESPONSE_SCHEMA:
        normalized["payload_schema_version"] = source_schema
    normalized["schema_version"] = CLI_RESPONSE_SCHEMA
    normalized.setdefault("status", "failed")
    for key in CLI_RESPONSE_LIST_FIELDS:
        value = normalized.get(key)
        normalized[key] = (
            value
            if isinstance(value, list)
            else list(value)
            if isinstance(value, tuple)
            else []
            if value is None
            else [value]
        )
    return normalized


def emit(result: dict, as_json: bool, allow_degraded: bool = False) -> int:
    result = normalize_response(result)
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"XiaoH: {result['status']}")
        print(f"Codex: {result.get('codex_home', 'unresolved')}")
        print(f"Obsidian: {result.get('obsidian_vault', 'unresolved')}")
        if result.get("backup"):
            print(f"Backup: {result['backup']}")
        if "effective_status" in result:
            for key in (
                "effective_status",
                "core_status",
                "runtime_gate_status",
                "integration_status",
                "automation_status",
                "vault_status",
                "customization_status",
                "installation_status",
            ):
                print(f"{key}: {result[key]}")
        for error in result.get("errors", []):
            print(f"ERROR: {error}", file=sys.stderr)
        for warning in result.get("warnings", []):
            print(f"WARNING: {warning}", file=sys.stderr)
        if result["status"] == "passed" and result.get("operation"):
            print("重启 Codex，在 /hooks 中信任四个 XiaoH Hook，然后运行 doctor --runtime。")
        elif result["status"] == "degraded" and result.get("operation"):
            print(
                "小H核心运行时已部署，但初始化尚未完成；请在新Codex任务中运行"
                " $xiaoh:xiaoh-setup 或 $xiaoh:xiaoh-update 完成托管任务校准。"
            )
    if "effective_status" in result:
        return 0 if result["effective_status"] == "complete" else 1
    return (
        0
        if result["status"] in {"passed", "complete"}
        or (allow_degraded and result["status"] == "degraded")
        else 1
    )

def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

def build_parser() -> argparse.ArgumentParser:
    parser = XiaoHArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in SUPPORTED_COMMANDS:
        command = subparsers.add_parser(name)
        if name != "companions":
            command.add_argument("--codex-home")
            command.add_argument("--vault")
            command.add_argument("--config")
        if name in {"setup", "update", "ensure-runtime", "doctor"}:
            command.add_argument("--active-skill-root")
        command.add_argument("--json", action="store_true")
        if name in {"setup", "update"}:
            command.add_argument("--allow-degraded", action="store_true")
        if name == "update":
            command.add_argument("--transactional", action="store_true")
        if name == "doctor":
            command.add_argument("--runtime", action="store_true")
            command.add_argument("--effective-status", action="store_true")
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


def command_failure(args: argparse.Namespace, exc: Exception) -> dict:
    return {
        "status": "failed",
        "operation": getattr(args, "command", "unknown"),
        "codex_home": str(
            Path(getattr(args, "codex_home", None) or Path.home() / ".codex")
            .expanduser()
        ),
        "obsidian_vault": str(
            Path(getattr(args, "vault", None) or "unresolved").expanduser()
        ),
        "config": str(
            Path(getattr(args, "config", None) or default_local_config())
            .expanduser()
        ),
        "errors": [f"{type(exc).__name__}: {exc}"],
        "warnings": [],
        "actual_writes": [],
        "unresolved_items": ["command_failed"],
        "recovery_conditions": ["修复输入、配置或文件系统错误后重试"],
    }


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "companions":
        result = normalize_response(companion_report(args.install))
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
        return emit(plan_installation(args), args.json)
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
    if args.command in {"setup", "update", "ensure-runtime"}:
        result = install(args, args.command)
        return emit(
            result,
            args.json,
            getattr(args, "allow_degraded", False),
        )
    active_skill_root = Path(args.active_skill_root) if args.active_skill_root else None
    return emit(
        doctor(
            codex,
            vault,
            config_path,
            args.runtime,
            active_skill_root,
            effective_status=getattr(args, "effective_status", False),
        ),
        args.json,
    )


def main() -> int:
    configure_stdio()
    raw_args = sys.argv[1:]
    args = argparse.Namespace(
        command=(
            raw_args[0]
            if raw_args and raw_args[0] in SUPPORTED_COMMANDS
            else "unknown"
        ),
        json="--json" in raw_args,
        allow_degraded="--allow-degraded" in raw_args,
        codex_home=None,
        vault=None,
        config=None,
    )
    try:
        args = build_parser().parse_args()
        return dispatch(args)
    except Exception as exc:
        return emit(
            command_failure(args, exc),
            getattr(args, "json", False),
            getattr(args, "allow_degraded", False),
        )
