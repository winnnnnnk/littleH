#!/usr/bin/env python3
"""Bind XiaoH execution to read-only Playbook worker and status evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECEIPT_SCHEMA = "xiaoh-playbook-binding/v1"
DEFAULT_MAX_AGE_SECONDS = 900
INTEGRATION_MODES = {"auto", "enabled", "disabled"}
ALLOWED_ACTIONS = {"read_only_analysis", "design", "member_confirmation", "task_create", "openspec_authoring", "openspec_confirmation", "task_start", "implementation", "verification", "operations"}


class AdapterError(RuntimeError):
    pass


def configured_integration_mode(config_path=None):
    path = Path(config_path or os.environ.get("XIAOH_CONFIG", str(Path.home() / ".xiaoh/config.json"))).expanduser()
    if not path.is_file():
        return "auto"
    value = load_json(path).get("integrations", {}).get("playbook", "auto")
    return value if value in INTEGRATION_MODES else "auto"


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AdapterError("JSON evidence must be an object")
    return value


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def successful_payload(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("status") in {"failed", "error"}:
        raise AdapterError("Playbook evidence reports failure")
    payload = value.get("data")
    return payload if isinstance(payload, dict) else value


def worker_facts(path: Path) -> dict[str, Any]:
    payload = successful_payload(load_json(path))
    required = ["workspace_id", "change_id", "member_worktree", "allowed_scope"]
    missing = [key for key in required if not payload.get(key)]
    if missing:
        raise AdapterError("Playbook worker fields missing: {}".format(", ".join(missing)))
    member = payload.get("member") or payload.get("repo")
    if not isinstance(member, str) or not member.strip():
        raise AdapterError("Playbook worker field member/repo is missing")
    worktree = Path(payload["member_worktree"]).expanduser().resolve()
    allowed = [Path(item).expanduser().resolve() for item in payload["allowed_scope"]]
    if not worktree.is_dir() or not allowed or any(root != worktree and worktree not in root.parents for root in allowed):
        raise AdapterError("Playbook worker scope is invalid")
    workspace_root = Path(payload.get("workspace_root") or worktree.parent).expanduser().resolve()
    facts = {
        "task_workspace_id": str(payload["workspace_id"]), "change_id": str(payload["change_id"]),
        "member": member.strip(), "member_worktree": str(worktree), "workspace_root": str(workspace_root),
        "allowed_scope": [str(item) for item in allowed],
    }
    for key in ("execution_mode", "recommended_executor"):
        if payload.get(key) is not None:
            facts[key] = str(payload[key])
    return facts


def playbook_probe(command="playbook", mode="auto", worker_json=None, status_json=None, **kwargs):
    if mode not in INTEGRATION_MODES:
        raise AdapterError("invalid integration mode")
    if mode == "disabled":
        return {"status": "not_enabled", "mode": mode, "command": command, "version": None, "errors": []}
    executable = shutil.which(command)
    if not executable:
        status = "not_enabled" if mode == "auto" else "missing"
        return {"status": status, "mode": mode, "command": command, "version": None, "errors": [] if status == "not_enabled" else ["Playbook command not found"]}
    completed = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=15, check=False)
    errors = [] if completed.returncode == 0 else ["Playbook version check failed"]
    if (worker_json is None) != (status_json is None):
        errors.append("worker and status evidence must be supplied together")
    if worker_json is not None and status_json is not None:
        try:
            worker_facts(Path(worker_json))
            load_json(Path(status_json))
        except (OSError, ValueError, AdapterError) as exc:
            errors.append(str(exc))
    return {"status": "compatible" if not errors and worker_json else ("available" if not errors else "incompatible"), "mode": mode, "command": str(Path(executable).resolve()), "version": (completed.stdout or completed.stderr).strip() or None, "worker_json_contract": not errors, "task_status_contract": bool(worker_json and not errors), "errors": errors}


def create_receipt(worker_json: Path, status_json: Path, output: Path, action: str, xiaoh_workspace_id: str, playbook_version=None, playbook_command="playbook"):
    if action not in ALLOWED_ACTIONS:
        raise AdapterError("unsupported delegated action: {}".format(action))
    executable = shutil.which(playbook_command)
    if not executable:
        raise AdapterError("Playbook command not found")
    worker_json, status_json = worker_json.expanduser().resolve(), status_json.expanduser().resolve()
    facts = worker_facts(worker_json)
    load_json(status_json)
    receipt = {"schema_version": RECEIPT_SCHEMA, "binding_kind": "worker", "captured_at": datetime.now(timezone.utc).isoformat(), "adapter_policy": "read_only_snapshot_fail_closed", "xiaoh_workspace_id": xiaoh_workspace_id, "delegated_action": action, "playbook": {"version": playbook_version, "command": str(Path(executable).resolve()), **facts, "worker_contract_source": str(worker_json), "worker_contract_sha256": file_hash(worker_json), "status_source": str(status_json), "status_sha256": file_hash(status_json)}}
    receipt["binding_sha256"] = canonical_hash(receipt)
    atomic_write_json(output.expanduser().resolve(), receipt)
    return {"status": "captured", "receipt_path": str(output.expanduser().resolve()), "receipt_sha256": file_hash(output.expanduser().resolve()), "receipt": receipt}


def validate_receipt(path: Path, expected_sha256=None, expected_action=None, max_age_seconds=DEFAULT_MAX_AGE_SECONDS, check_sources=True, **kwargs):
    path = path.expanduser().resolve()
    if expected_sha256 and file_hash(path) != expected_sha256:
        raise AdapterError("receipt file hash changed")
    receipt = load_json(path)
    if receipt.get("schema_version") != RECEIPT_SCHEMA or receipt.get("binding_kind") != "worker":
        raise AdapterError("unsupported receipt schema or binding kind")
    if expected_action and receipt.get("delegated_action") != expected_action:
        raise AdapterError("receipt action does not match")
    captured = datetime.fromisoformat(receipt["captured_at"].replace("Z", "+00:00"))
    if abs((datetime.now(timezone.utc) - captured).total_seconds()) > max_age_seconds:
        raise AdapterError("receipt is stale")
    if receipt.get("binding_sha256") != canonical_hash({key: value for key, value in receipt.items() if key != "binding_sha256"}):
        raise AdapterError("receipt binding hash changed")
    if check_sources:
        for source_key, hash_key in (("worker_contract_source", "worker_contract_sha256"), ("status_source", "status_sha256")):
            source = Path(receipt["playbook"][source_key])
            if not source.is_file() or file_hash(source) != receipt["playbook"][hash_key]:
                raise AdapterError("Playbook source changed: {}".format(source))
    return receipt


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    probe = sub.add_parser("probe"); probe.add_argument("--playbook-command", default="playbook"); probe.add_argument("--mode", choices=sorted(INTEGRATION_MODES), default="auto"); probe.add_argument("--worker-json"); probe.add_argument("--status-json")
    capture = sub.add_parser("capture"); capture.add_argument("--worker-json", required=True); capture.add_argument("--status-json", required=True); capture.add_argument("--output", required=True); capture.add_argument("--action", required=True, choices=sorted(ALLOWED_ACTIONS)); capture.add_argument("--xiaoh-workspace-id", required=True); capture.add_argument("--playbook-version"); capture.add_argument("--playbook-command", default="playbook")
    verify = sub.add_parser("verify"); verify.add_argument("--receipt", required=True); verify.add_argument("--expected-sha256"); verify.add_argument("--expected-action", choices=sorted(ALLOWED_ACTIONS)); verify.add_argument("--max-age-seconds", type=int, default=DEFAULT_MAX_AGE_SECONDS); verify.add_argument("--skip-source-check", action="store_true")
    return parser


def main():
    args = build_parser().parse_args()
    try:
        if args.command == "probe":
            result = playbook_probe(args.playbook_command, args.mode, Path(args.worker_json) if args.worker_json else None, Path(args.status_json) if args.status_json else None); emit(result); return 0 if result["status"] in {"available", "compatible", "not_enabled"} else 1
        if args.command == "capture":
            emit(create_receipt(Path(args.worker_json), Path(args.status_json), Path(args.output), args.action, args.xiaoh_workspace_id, args.playbook_version, args.playbook_command)); return 0
        emit(validate_receipt(Path(args.receipt), args.expected_sha256, args.expected_action, args.max_age_seconds, not args.skip_source_check)); return 0
    except (AdapterError, OSError, ValueError, subprocess.SubprocessError) as exc:
        emit({"status": "failed", "error": str(exc)}); return 1


if __name__ == "__main__":
    raise SystemExit(main())
