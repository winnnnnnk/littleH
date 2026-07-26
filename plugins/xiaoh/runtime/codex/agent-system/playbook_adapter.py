#!/usr/bin/env python3
"""Create and verify XiaoH bindings from Playbook read-only JSON output."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RECEIPT_SCHEMA = "xiaoh-playbook-binding/v1"
DEFAULT_MAX_AGE_SECONDS = 900
MAX_SOURCE_AGE_SECONDS = 120
ALLOWED_ACTIONS = {
    "read_only_analysis",
    "design_review",
    "spec_rfc_review",
    "member_confirmation",
    "task_create",
    "openspec_authoring",
    "openspec_consistency_review",
    "openspec_confirmation",
    "task_start",
    "implementation",
    "verification",
    "code_review",
    "operations",
}
INTEGRATION_MODES = {"auto", "enabled", "disabled"}


class AdapterError(ValueError):
    pass


def normalize_integration_mode(value: Any) -> str:
    if value is True:
        return "enabled"
    if value is False:
        return "disabled"
    if isinstance(value, str) and value in INTEGRATION_MODES:
        return value
    raise AdapterError("integrations.playbook必须是auto、enabled、disabled、true或false")


def configured_integration_mode(config_path: Path | None = None) -> str:
    path = config_path or Path(
        os.environ.get("XIAOH_CONFIG", str(Path.home() / ".xiaoh/config.json"))
    ).expanduser()
    if not path.is_file():
        return "auto"
    integrations = load_json(path).get("integrations", {})
    if integrations is None:
        return "auto"
    if not isinstance(integrations, dict):
        raise AdapterError("integrations必须是JSON对象")
    return normalize_integration_mode(integrations.get("playbook", "auto"))


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AdapterError(f"无法读取JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AdapterError(f"JSON根节点必须是对象: {path}")
    return value


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def successful_payload(value: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    status = value.get("status")
    if isinstance(status, str) and status.casefold() in {"error", "failed"}:
        raise AdapterError(f"Playbook返回失败状态: {status}")
    candidates = [value]
    if isinstance(value.get("data"), dict):
        candidates.insert(0, value["data"])
    for candidate in candidates:
        child = candidate.get("child_worker_context")
        if isinstance(child, dict):
            return child, candidate
        if all(candidate.get(key) for key in ("workspace_id", "change_id", "member_worktree")):
            return candidate, candidate
    raise AdapterError("Playbook worker JSON缺少child_worker_context或必要worker字段")


def string_field(value: dict[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise AdapterError(f"Playbook worker字段缺失或无效: {key}")
    return result.strip()


def normalized_absolute_path(value: str, label: str, require_exists: bool = True) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise AdapterError(f"{label}必须是绝对路径: {value}")
    path = path.resolve(strict=False)
    if require_exists and not path.exists():
        raise AdapterError(f"{label}不存在: {path}")
    return path


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def worker_facts(worker_json: Path) -> dict[str, Any]:
    payload, envelope = successful_payload(load_json(worker_json))
    task_workspace_id = string_field(payload, "workspace_id")
    change_id = string_field(payload, "change_id")
    member = payload.get("member") or payload.get("repo")
    if not isinstance(member, str) or not member.strip():
        raise AdapterError("Playbook worker字段缺失或无效: member/repo")
    member_worktree = normalized_absolute_path(
        string_field(payload, "member_worktree"), "member_worktree"
    )
    workspace_root_value = envelope.get("workspace_root") or payload.get("workspace_root")
    if not isinstance(workspace_root_value, str) or not workspace_root_value.strip():
        raise AdapterError("Playbook worker字段缺失或无效: workspace_root")
    workspace_root = normalized_absolute_path(workspace_root_value, "workspace_root")
    allowed = payload.get("allowed_scope")
    if not isinstance(allowed, list) or not allowed:
        raise AdapterError("Playbook worker字段缺失或无效: allowed_scope")
    allowed_scope = [
        normalized_absolute_path(str(item), "allowed_scope") for item in allowed
    ]
    if any(not is_within(root, member_worktree) for root in allowed_scope):
        raise AdapterError("Playbook allowed_scope超出member_worktree")
    return {
        "task_workspace_id": task_workspace_id,
        "change_id": change_id,
        "member": member.strip(),
        "member_worktree": str(member_worktree),
        "workspace_root": str(workspace_root),
        "allowed_scope": [str(path) for path in allowed_scope],
    }


def nested_values(value: Any, key: str) -> list[str]:
    results: list[str] = []
    if isinstance(value, dict):
        for current_key, current_value in value.items():
            if current_key == key and isinstance(current_value, str) and current_value.strip():
                results.append(current_value.strip())
            results.extend(nested_values(current_value, key))
    elif isinstance(value, list):
        for item in value:
            results.extend(nested_values(item, key))
    return results


def validate_status_snapshot(status_json: Path | dict[str, Any], worker: dict[str, Any]) -> None:
    status = load_json(status_json) if isinstance(status_json, Path) else status_json
    if isinstance(status.get("status"), str) and status["status"].casefold() in {"error", "failed"}:
        raise AdapterError(f"Playbook status JSON返回失败: {status['status']}")
    workspace_ids = set(nested_values(status, "workspace_id"))
    if workspace_ids != {worker["task_workspace_id"]}:
        raise AdapterError("Playbook status与worker的workspace_id不唯一或不一致")
    change_ids = set(nested_values(status, "change_id"))
    if change_ids != {worker["change_id"]}:
        raise AdapterError("Playbook status与worker的change_id不唯一或不一致")
    states = set(nested_values(status, "current_state"))
    if len(states) != 1 or not states.issubset({"started", "blocked"}):
        raise AdapterError("Playbook task当前不是可委派的非终态")
    worktrees = set(nested_values(status, "worktree_path"))
    if worker["member_worktree"] not in {
        str(Path(value).expanduser().resolve(strict=False)) for value in worktrees
    }:
        raise AdapterError("Playbook status未证明当前member_worktree仍有效")


def source_timestamps(worker_json: Path, status_json: Path) -> dict[str, int]:
    now_ns = datetime.now(timezone.utc).timestamp() * 1_000_000_000
    worker_mtime = worker_json.stat().st_mtime_ns
    status_mtime = status_json.stat().st_mtime_ns
    for label, value in (("worker", worker_mtime), ("status", status_mtime)):
        age = (now_ns - value) / 1_000_000_000
        if age < -5 or age > MAX_SOURCE_AGE_SECONDS:
            raise AdapterError(f"Playbook {label} JSON不是刚刚生成的快照")
    if status_mtime < worker_mtime or status_mtime - worker_mtime > MAX_SOURCE_AGE_SECONDS * 1_000_000_000:
        raise AdapterError("Playbook status JSON必须紧邻worker JSON之后生成")
    return {
        "worker_contract_mtime_ns": worker_mtime,
        "status_mtime_ns": status_mtime,
    }


def current_status_snapshot(playbook: dict[str, Any]) -> dict[str, Any]:
    command = normalized_absolute_path(playbook["command"], "playbook.command")
    completed = subprocess.run(
        [
            str(command),
            "workspace", "task", "status",
            "--workspace-root", playbook["workspace_root"],
            "--workspace-id", playbook["task_workspace_id"],
            "--output", "json",
            "--full",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    if completed.returncode:
        raise AdapterError(
            "无法重新读取Playbook当前task status: "
            + (completed.stderr or completed.stdout).strip()
        )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AdapterError("Playbook当前task status不是有效JSON") from exc
    if not isinstance(value, dict):
        raise AdapterError("Playbook当前task status根节点必须是对象")
    return value


def playbook_probe(
    command: str = "playbook", mode: str = "auto"
) -> dict[str, Any]:
    mode = normalize_integration_mode(mode)
    if mode == "disabled":
        return {
            "status": "not_enabled",
            "mode": mode,
            "command": command,
            "version": None,
            "worker_json_contract": False,
            "task_status_contract": False,
            "errors": [],
        }
    executable = shutil.which(command)
    if not executable:
        if mode == "auto":
            return {
                "status": "not_enabled",
                "mode": mode,
                "command": command,
                "version": None,
                "worker_json_contract": False,
                "task_status_contract": False,
                "errors": [],
            }
        return {
            "status": "missing",
            "mode": mode,
            "command": command,
            "version": None,
            "worker_json_contract": False,
            "task_status_contract": False,
            "errors": [f"未找到Playbook命令: {command}"],
        }
    checks = {}
    errors = []
    for name, arguments, required_text in (
        ("version", ["--version"], "playbook version"),
        (
            "task_status",
            ["workspace", "task", "status", "--help"],
            "--output json",
        ),
        (
            "worker_start",
            ["workspace", "task", "worker", "start", "--help"],
            "child_worker_context",
        ),
    ):
        completed = subprocess.run(
            [executable, *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            check=False,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        checks[name] = {
            "exit_code": completed.returncode,
            "supported": completed.returncode == 0 and required_text in output,
        }
        if not checks[name]["supported"]:
            errors.append(f"Playbook {name}能力不满足小H适配要求")
    version_output = subprocess.run(
        [executable, "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )
    version = (version_output.stdout or version_output.stderr).strip() or None
    compatible = checks["task_status"]["supported"] and checks["worker_start"]["supported"]
    return {
        "status": "compatible" if compatible else "incompatible",
        "mode": mode,
        "command": executable,
        "version": version,
        "worker_json_contract": checks["worker_start"]["supported"],
        "task_status_contract": checks["task_status"]["supported"],
        "checks": checks,
        "errors": errors,
    }


def create_receipt(
    worker_json: Path,
    status_json: Path,
    output: Path,
    action: str,
    xiaoh_workspace_id: str,
    playbook_version: str | None = None,
    playbook_command: str = "playbook",
) -> dict[str, Any]:
    if action not in ALLOWED_ACTIONS:
        raise AdapterError(f"不支持的delegated action: {action}")
    if not xiaoh_workspace_id.strip():
        raise AdapterError("xiaoh_workspace_id不能为空")
    worker_json = worker_json.expanduser().resolve()
    status_json = status_json.expanduser().resolve()
    worker = worker_facts(worker_json)
    validate_status_snapshot(status_json, worker)
    timestamps = source_timestamps(worker_json, status_json)
    executable = shutil.which(playbook_command)
    if not executable:
        raise AdapterError(f"未找到Playbook命令: {playbook_command}")
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "adapter_policy": "read_only_snapshot_fail_closed",
        "xiaoh_workspace_id": xiaoh_workspace_id.strip(),
        "delegated_action": action,
        "playbook": {
            "version": playbook_version,
            "command": str(Path(executable).resolve()),
            **worker,
            "worker_contract_source": str(worker_json),
            "worker_contract_sha256": file_hash(worker_json),
            "status_source": str(status_json),
            "status_sha256": file_hash(status_json),
            **timestamps,
        },
    }
    receipt["binding_sha256"] = canonical_hash(receipt)
    output = output.expanduser().resolve()
    atomic_write_json(output, receipt)
    return {
        "status": "captured",
        "receipt_path": str(output),
        "receipt_sha256": file_hash(output),
        "receipt": receipt,
    }


def parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise AdapterError("receipt captured_at无效")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdapterError("receipt captured_at无效") from exc
    if parsed.tzinfo is None:
        raise AdapterError("receipt captured_at必须包含时区")
    return parsed.astimezone(timezone.utc)


def validate_receipt(
    receipt_path: Path,
    *,
    expected_sha256: str | None = None,
    expected_action: str | None = None,
    max_age_seconds: int | None = DEFAULT_MAX_AGE_SECONDS,
    check_sources: bool = True,
    check_live_status: bool = False,
) -> dict[str, Any]:
    receipt_path = receipt_path.expanduser().resolve()
    if expected_sha256 and file_hash(receipt_path) != expected_sha256:
        raise AdapterError("adapter receipt文件哈希不匹配")
    receipt = load_json(receipt_path)
    if receipt.get("schema_version") != RECEIPT_SCHEMA:
        raise AdapterError("不支持的adapter receipt schema")
    if not isinstance(receipt.get("xiaoh_workspace_id"), str) or not receipt["xiaoh_workspace_id"].strip():
        raise AdapterError("adapter receipt xiaoh_workspace_id无效")
    binding = receipt.pop("binding_sha256", None)
    if not isinstance(binding, str) or binding != canonical_hash(receipt):
        raise AdapterError("adapter receipt binding_sha256不匹配")
    receipt["binding_sha256"] = binding
    if receipt.get("delegated_action") not in ALLOWED_ACTIONS:
        raise AdapterError("adapter receipt delegated_action无效")
    if expected_action and receipt["delegated_action"] != expected_action:
        raise AdapterError("adapter receipt delegated_action与委派动作不一致")
    captured_at = parse_timestamp(receipt.get("captured_at"))
    age = (datetime.now(timezone.utc) - captured_at).total_seconds()
    if age < -300 or (max_age_seconds is not None and age > max_age_seconds):
        raise AdapterError(f"adapter receipt已过期: {int(age)}秒")
    playbook = receipt.get("playbook")
    if not isinstance(playbook, dict):
        raise AdapterError("adapter receipt缺少playbook对象")
    for key in (
        "task_workspace_id",
        "change_id",
        "member",
        "member_worktree",
        "workspace_root",
        "allowed_scope",
        "command",
        "worker_contract_source",
        "worker_contract_sha256",
        "worker_contract_mtime_ns",
        "status_source",
        "status_sha256",
        "status_mtime_ns",
    ):
        if key not in playbook:
            raise AdapterError(f"adapter receipt缺少playbook.{key}")
    if check_sources:
        for path_key, hash_key in (
            ("worker_contract_source", "worker_contract_sha256"),
            ("status_source", "status_sha256"),
        ):
            source = normalized_absolute_path(playbook[path_key], f"playbook.{path_key}")
            if file_hash(source) != playbook[hash_key]:
                raise AdapterError(f"adapter receipt来源已变化: {source}")
            mtime_key = (
                "worker_contract_mtime_ns"
                if path_key == "worker_contract_source"
                else "status_mtime_ns"
            )
            if source.stat().st_mtime_ns != playbook[mtime_key]:
                raise AdapterError(f"adapter receipt来源时间已变化: {source}")
        worker = worker_facts(Path(playbook["worker_contract_source"]))
        for key in (
            "task_workspace_id", "change_id", "member", "member_worktree",
            "workspace_root", "allowed_scope",
        ):
            if worker[key] != playbook[key]:
                raise AdapterError(f"adapter receipt与worker来源不一致: {key}")
        validate_status_snapshot(Path(playbook["status_source"]), worker)
    if check_live_status:
        live = current_status_snapshot(playbook)
        validate_status_snapshot(live, {
            key: playbook[key]
            for key in (
                "task_workspace_id", "change_id", "member", "member_worktree",
                "workspace_root", "allowed_scope",
            )
        })
    return receipt


def emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    probe = subparsers.add_parser("probe")
    probe.add_argument("--playbook-command", default="playbook")
    probe.add_argument("--mode", choices=sorted(INTEGRATION_MODES), default="auto")
    capture = subparsers.add_parser("capture")
    capture.add_argument("--worker-json", required=True)
    capture.add_argument("--status-json", required=True)
    capture.add_argument("--output", required=True)
    capture.add_argument("--action", required=True, choices=sorted(ALLOWED_ACTIONS))
    capture.add_argument("--xiaoh-workspace-id", required=True)
    capture.add_argument("--playbook-version")
    capture.add_argument("--playbook-command", default="playbook")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--receipt", required=True)
    verify.add_argument("--expected-sha256")
    verify.add_argument("--expected-action", choices=sorted(ALLOWED_ACTIONS))
    verify.add_argument("--max-age-seconds", type=int, default=DEFAULT_MAX_AGE_SECONDS)
    verify.add_argument("--skip-source-check", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "probe":
            result = playbook_probe(args.playbook_command, args.mode)
            emit(result)
            return 0 if result["status"] in {"compatible", "not_enabled"} else 1
        if args.command == "capture":
            emit(
                create_receipt(
                    Path(args.worker_json),
                    Path(args.status_json),
                    Path(args.output),
                    args.action,
                    args.xiaoh_workspace_id,
                    args.playbook_version,
                    args.playbook_command,
                )
            )
            return 0
        emit(
            validate_receipt(
                Path(args.receipt),
                expected_sha256=args.expected_sha256,
                expected_action=args.expected_action,
                max_age_seconds=args.max_age_seconds,
                check_sources=not args.skip_source_check,
                check_live_status=False,
            )
        )
        return 0
    except (AdapterError, OSError, subprocess.SubprocessError) as exc:
        emit({"status": "failed", "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
