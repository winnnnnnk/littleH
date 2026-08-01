"""Thin command-line interface for XiaoH 4.0.1."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping, NoReturn, Optional, Sequence

from ..adapters.automation import LocalAutomationStore
from ..adapters.local import LocalFileSystem, SubprocessRunner, SystemClock
from ..adapters.plugins import CodexPluginFacts
from ..application.runtime import RuntimeApplication, RuntimePaths
from ..services.configuration import ConfigurationService
from ..services.redaction import redact_text


CLI_RESPONSE_SCHEMA = "xiaoh-cli-response/v2"
SUPPORTED_COMMANDS = (
    "plan",
    "setup",
    "update",
    "ensure-runtime",
    "doctor",
    "companions",
    "bind-automation",
    "resolve-workspace",
    "register-workspace",
)
LIST_FIELDS = (
    "errors",
    "warnings",
    "actual_writes",
    "unresolved_items",
    "recovery_conditions",
)
PLUGIN_ROOT = Path(__file__).resolve().parents[2]


class CLIArgumentError(ValueError):
    pass


class XiaoHArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise CLIArgumentError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = XiaoHArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in SUPPORTED_COMMANDS:
        command = commands.add_parser(name)
        command.add_argument("--json", action="store_true")
        if name != "companions":
            command.add_argument("--codex-home")
            command.add_argument("--vault")
            command.add_argument("--config")
        if name in {"setup", "update", "ensure-runtime", "doctor"}:
            command.add_argument("--active-skill-root")
        if name == "doctor":
            command.add_argument("--runtime", action="store_true")
        if name == "companions":
            command.add_argument("--install", action="store_true")
            command.add_argument("--runtime", action="store_true")
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


def normalize_response(result: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(result)
    source_schema = normalized.get("schema_version")
    if source_schema and source_schema != CLI_RESPONSE_SCHEMA:
        normalized["payload_schema_version"] = source_schema
    normalized["schema_version"] = CLI_RESPONSE_SCHEMA
    normalized.setdefault("status", "failed")
    normalized.setdefault("operation", "unknown")
    for key in LIST_FIELDS:
        value = normalized.get(key)
        if value is None:
            normalized[key] = []
        elif isinstance(value, list):
            normalized[key] = value
        elif isinstance(value, tuple):
            normalized[key] = list(value)
        else:
            normalized[key] = [value]
    return normalized


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    fs = LocalFileSystem()
    application = RuntimeApplication(
        fs,
        SystemClock(),
        PLUGIN_ROOT,
        process_runner=SubprocessRunner(),
        automation_store_factory=LocalAutomationStore,
        plugin_facts=CodexPluginFacts(SubprocessRunner()),
    )
    if args.command == "companions":
        return application.companions(args.install, args.runtime)
    paths = resolve_paths(args, fs)
    if args.command == "plan":
        return application.plan("plan", paths)
    if args.command in {"setup", "update", "ensure-runtime"}:
        operation = "update" if args.command == "ensure-runtime" else args.command
        return application.install(operation, paths, Path.home())
    if args.command == "doctor":
        active = Path(args.active_skill_root) if args.active_skill_root else None
        return application.doctor(paths, args.runtime, active)
    if args.command == "resolve-workspace":
        return application.resolve_workspace(paths, Path(args.path))
    if args.command == "register-workspace":
        return application.register_workspace(
            paths,
            args.workspace_id,
            args.project,
            args.system,
            Path(args.root),
        )
    if args.command == "bind-automation":
        return application.bind_automation(paths, args.logical_id, args.task_id)
    raise ValueError(f"unsupported command: {args.command}")


def resolve_paths(args: argparse.Namespace, fs: LocalFileSystem) -> RuntimePaths:
    config = Path(
        args.config
        or os.environ.get("XIAOH_CONFIG")
        or Path.home() / ".xiaoh/config.json"
    ).expanduser()
    local = ConfigurationService(fs).load(config, missing_ok=True)
    codex = Path(
        args.codex_home
        or os.environ.get("CODEX_HOME")
        or local.get("codex_home")
        or Path.home() / ".codex"
    ).expanduser()
    vault = Path(
        args.vault
        or os.environ.get("XIAOH_VAULT")
        or local.get("obsidian_vault")
        or Path.home() / "obsidian/development-vault"
    ).expanduser()
    return RuntimePaths(fs.resolve(codex), fs.resolve(vault), fs.resolve(config))


def command_failure(args: argparse.Namespace, exc: Exception) -> dict[str, Any]:
    return {
        "status": "failed",
        "operation": getattr(args, "command", "unknown"),
        "errors": [redact_text(f"{type(exc).__name__}: {exc}")],
        "warnings": [],
        "actual_writes": [],
        "unresolved_items": ["command_failed"],
        "recovery_conditions": ["repair the input or target condition, then retry once"],
    }


def exit_code(result: Mapping[str, Any]) -> int:
    status = result.get("status")
    if status in {"passed", "complete"}:
        return 0
    return 1


def emit(result: Mapping[str, Any], as_json: bool) -> None:
    normalized = normalize_response(result)
    if as_json:
        print(json.dumps(normalized, ensure_ascii=False, indent=2))
        return
    print(f"XiaoH: {normalized['status']}")
    for error in normalized["errors"]:
        print(f"ERROR: {error}", file=sys.stderr)
    for warning in normalized["warnings"]:
        print(f"WARNING: {warning}", file=sys.stderr)
    if normalized.get("activation_state") == "runtime_unverified":
        print("Files are installed; restart, trust Hooks manually, then run runtime Doctor.")


def main(argv: Optional[Sequence[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    raw = list(argv) if argv is not None else sys.argv[1:]
    args = argparse.Namespace(
        command=raw[0] if raw and raw[0] in SUPPORTED_COMMANDS else "unknown",
        json="--json" in raw,
    )
    try:
        args = build_parser().parse_args(raw)
        result = normalize_response(dispatch(args))
    except Exception as exc:
        result = normalize_response(command_failure(args, exc))
    emit(result, getattr(args, "json", False))
    return exit_code(result)
