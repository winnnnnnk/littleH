#!/usr/bin/env python3
"""Bind XiaoH execution to read-only Playbook worker and status evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

RECEIPT_SCHEMA = "xiaoh-playbook-binding/v1"
DEFAULT_MAX_AGE_SECONDS = 900
INTEGRATION_MODES = {"auto", "enabled", "disabled"}
ALLOWED_ACTIONS = {"read_only_analysis", "design", "member_confirmation", "task_create", "openspec_authoring", "openspec_confirmation", "task_start", "implementation", "verification", "operations"}
PUBLIC_STATUS_REQUIRED_KEYS = {
    "workspace_id", "change_id", "members", "blockers", "next_actions",
    "refreshed_at", "task_truth_path",
}
PUBLIC_STATUS_OPTIONAL_KEYS = {"task_session_relation"}
PUBLIC_MEMBER_REQUIRED_KEYS = {"repo", "branch", "head", "base_sync", "sdd"}
PUBLIC_MEMBER_OPTIONAL_KEYS = {
    "issue", "mr", "pipeline", "ai_review", "human_approval",
}
PUBLIC_STATUS_CONTRACT = "task_status_public_v1"
BASE_SYNC_STATUSES = {"up_to_date", "outdated", "missing", "unknown"}
SDD_STATES = {"missing", "pending_confirmation", "confirmed", "stale", "archived", "unknown"}
SDD_TASKS = {"missing", "incomplete", "complete", "unknown"}
ISSUE_STATUSES = {"not_created", "opened", "closed", "missing", "unknown"}
MR_STATUSES = {"not_created", "opened", "merged", "closed", "missing", "unknown"}
MERGE_STATUSES = {"mergeable", "conflict", "checking", "blocked", "unknown"}
PIPELINE_STATUSES = {"not_started", "pending", "running", "passed", "failed", "canceled", "skipped", "manual", "unknown"}
AI_REVIEW_STATUSES = {"not_started", "in_progress", "changes_requested", "approved", "stale", "disabled", "unknown"}
HUMAN_APPROVAL_STATUSES = {"not_started", "pending", "approved", "unknown"}
BLOCKER_CODES = {
    "sdd_missing", "sdd_confirmation_required", "sdd_stale", "sdd_unknown",
    "worktree_unavailable", "local_git_unknown", "commit_static_failed",
    "commit_static_required", "commit_static_unknown", "handoff_blocked",
    "base_branch_missing", "base_outdated", "base_sync_unknown", "issue_missing",
    "issue_blocked", "mr_missing", "merge_conflict", "mr_blocked",
    "pipeline_failed", "pipeline_canceled", "pipeline_skipped", "pipeline_manual",
    "pipeline_unknown", "local_review_changes_required", "local_review_required",
    "local_review_unknown", "ai_review_decision_required",
    "ai_review_changes_requested", "ai_review_stale", "ai_review_unknown",
    "human_approval_required", "human_approval_unknown",
    "post_merge_validation_required", "post_merge_validation_unknown",
    "remote_state_unknown",
}
NEXT_ACTIONS = {
    "create_sdd", "confirm_sdd", "update_sdd", "create_issue",
    "resolve_issue_blocker", "start_task", "run_commit", "fix_commit_static",
    "resolve_merge_conflict", "resolve_mr_blocker", "sync_target_branch",
    "push_branch", "create_mr", "complete_handoff", "wait_mergeability",
    "wait_pipeline", "fix_pipeline", "run_manual_pipeline", "start_local_review",
    "address_local_review", "confirm_ai_review_decision", "request_ai_review",
    "wait_ai_review", "address_ai_review", "wait_human_approval",
    "run_post_merge_validation", "finalize_task",
}
TASK_SESSION_RELATION_KEYS = {
    "code", "relation", "workspace_id", "member", "members", "message",
    "managed_command_policy", "takeover_requires_user_authorization",
    "takeover_commands_after_authorization",
}


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


def _non_empty_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdapterError("Playbook task status field {} is invalid".format(field))
    return value.strip()


def _record(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AdapterError("Playbook task status field {} must be an object".format(field))
    return value


def _record_list(value: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise AdapterError("Playbook task status field {} must be an object list".format(field))
    return value


def _enum(value: Any, allowed: set[str], field: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise AdapterError("Playbook task status field {} has an unsupported value".format(field))
    return value


def _nullable_text(value: Any, field: str) -> Optional[str]:
    if value is None:
        return None
    return _non_empty_text(value, field)


def _nullable_short_sha(value: Any, field: str) -> Optional[str]:
    if value is None:
        return None
    text = _non_empty_text(value, field)
    if not re.fullmatch(r"[0-9a-f]{12}", text):
        raise AdapterError("Playbook task status field {} must be a 12-character SHA".format(field))
    return text


def _current_git_identity(worktree: str) -> tuple[str, str]:
    branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=worktree,
        capture_output=True, text=True, timeout=15, check=False,
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=worktree,
        capture_output=True, text=True, timeout=15, check=False,
    )
    if branch.returncode or head.returncode:
        raise AdapterError("Playbook member worktree Git identity is unavailable")
    return branch.stdout.strip(), head.stdout.strip()


def _validate_needs(items: Any, field: str, value_key: str, allowed: set[str]) -> None:
    for index, item in enumerate(_record_list(items, field)):
        expected = {value_key, "member"} if "member" in item else {value_key}
        if set(item) != expected:
            raise AdapterError("Playbook task status {} item fields are invalid".format(field))
        _enum(item.get(value_key), allowed, "{}[{}].{}".format(field, index, value_key))
        if "member" in item:
            _non_empty_text(item["member"], "{}[{}].member".format(field, index))


def _validate_task_session_relation(value: Any, workspace_id: str) -> None:
    relation = _record(value, "task_session_relation")
    if set(relation) != TASK_SESSION_RELATION_KEYS:
        raise AdapterError("Playbook task status session relation fields are invalid")
    if (
        relation.get("code") != "TASK_SESSION_UNRELATED"
        or relation.get("relation") != "unrelated"
        or relation.get("workspace_id") != workspace_id
        or relation.get("managed_command_policy") != "execute_with_warning"
        or relation.get("takeover_requires_user_authorization") is not True
    ):
        raise AdapterError("Playbook task status session relation is invalid")
    _nullable_text(relation.get("member"), "task_session_relation.member")
    members = relation.get("members")
    commands = relation.get("takeover_commands_after_authorization")
    if not isinstance(members, list) or any(
        not isinstance(member, str) or not member.strip() for member in members
    ):
        raise AdapterError("Playbook task status session relation members are invalid")
    if not isinstance(commands, list) or any(
        not isinstance(command, str) or not command.strip() for command in commands
    ):
        raise AdapterError("Playbook task status session relation commands are invalid")
    _non_empty_text(relation.get("message"), "task_session_relation.message")


def _validate_public_member(value: Any, index: int) -> dict[str, Any]:
    member = _record(value, "members[{}]".format(index))
    keys = set(member)
    if not PUBLIC_MEMBER_REQUIRED_KEYS.issubset(keys) or not keys.issubset(
        PUBLIC_MEMBER_REQUIRED_KEYS | PUBLIC_MEMBER_OPTIONAL_KEYS
    ):
        raise AdapterError("Playbook task status member fields do not match the 0.0.41 contract")
    _non_empty_text(member.get("repo"), "members[{}].repo".format(index))
    _nullable_text(member.get("branch"), "members[{}].branch".format(index))
    _nullable_short_sha(member.get("head"), "members[{}].head".format(index))
    base_sync = _record(member.get("base_sync"), "members[{}].base_sync".format(index))
    sdd = _record(member.get("sdd"), "members[{}].sdd".format(index))
    if set(base_sync) != {"branch", "status"} or set(sdd) != {"provider", "state", "tasks"}:
        raise AdapterError("Playbook task status member nested fields do not match the 0.0.41 contract")
    _non_empty_text(base_sync.get("branch"), "members[{}].base_sync.branch".format(index))
    _enum(base_sync.get("status"), BASE_SYNC_STATUSES, "members[{}].base_sync.status".format(index))
    _non_empty_text(sdd.get("provider"), "members[{}].sdd.provider".format(index))
    _enum(sdd.get("state"), SDD_STATES, "members[{}].sdd.state".format(index))
    _enum(sdd.get("tasks"), SDD_TASKS, "members[{}].sdd.tasks".format(index))
    if "issue" in member:
        issue = _record(member["issue"], "members[{}].issue".format(index))
        if set(issue) != {"status"}:
            raise AdapterError("Playbook task status issue fields are invalid")
        _enum(issue.get("status"), ISSUE_STATUSES, "members[{}].issue.status".format(index))
    if "mr" in member:
        mr = _record(member["mr"], "members[{}].mr".format(index))
        if set(mr) != {"status", "merge_status", "head"}:
            raise AdapterError("Playbook task status MR fields are invalid")
        _enum(mr.get("status"), MR_STATUSES, "members[{}].mr.status".format(index))
        _enum(mr.get("merge_status"), MERGE_STATUSES, "members[{}].mr.merge_status".format(index))
        _nullable_short_sha(mr.get("head"), "members[{}].mr.head".format(index))
    if "pipeline" in member:
        pipeline = _record(member["pipeline"], "members[{}].pipeline".format(index))
        if set(pipeline) != {"status", "head"}:
            raise AdapterError("Playbook task status pipeline fields are invalid")
        _enum(pipeline.get("status"), PIPELINE_STATUSES, "members[{}].pipeline.status".format(index))
        _nullable_short_sha(pipeline.get("head"), "members[{}].pipeline.head".format(index))
    if "ai_review" in member:
        review = _record(member["ai_review"], "members[{}].ai_review".format(index))
        skip_remote = review.get("skip_remote")
        if set(review) != {"skip_remote", "status", "head"} or (
            skip_remote is not None and not isinstance(skip_remote, bool)
        ):
            raise AdapterError("Playbook task status AI review fields are invalid")
        _enum(review.get("status"), AI_REVIEW_STATUSES, "members[{}].ai_review.status".format(index))
        _nullable_short_sha(review.get("head"), "members[{}].ai_review.head".format(index))
    if "human_approval" in member:
        approval = _record(member["human_approval"], "members[{}].human_approval".format(index))
        if set(approval) != {"status"}:
            raise AdapterError("Playbook task status human approval fields are invalid")
        _enum(approval.get("status"), HUMAN_APPROVAL_STATUSES, "members[{}].human_approval.status".format(index))
    return member


def validate_task_status(path: Path, worker: dict[str, Any]) -> dict[str, Any]:
    status = successful_payload(load_json(Path(path).expanduser().resolve()))
    keys = set(status)
    if not PUBLIC_STATUS_REQUIRED_KEYS.issubset(keys) or not keys.issubset(
        PUBLIC_STATUS_REQUIRED_KEYS | PUBLIC_STATUS_OPTIONAL_KEYS
    ):
        raise AdapterError("Playbook task status fields do not match the 0.0.41 contract")
    workspace_id = _non_empty_text(status.get("workspace_id"), "workspace_id")
    change_id = _non_empty_text(status.get("change_id"), "change_id")
    expected_workspace = str(worker.get("task_workspace_id") or worker.get("workspace_id") or "")
    expected_change = str(worker.get("change_id") or "")
    if workspace_id != expected_workspace or change_id != expected_change:
        raise AdapterError("Playbook task status task identity does not match the worker")
    members = [
        _validate_public_member(member, index)
        for index, member in enumerate(status["members"])
    ] if isinstance(status["members"], list) else None
    if members is None:
        raise AdapterError("Playbook task status members must be a list")
    _validate_needs(status["blockers"], "blockers", "code", BLOCKER_CODES)
    if status["next_actions"] is not None:
        _validate_needs(status["next_actions"], "next_actions", "action", NEXT_ACTIONS)
    _non_empty_text(status.get("refreshed_at"), "refreshed_at")
    _non_empty_text(status.get("task_truth_path"), "task_truth_path")
    relation = status.get("task_session_relation")
    if relation is not None:
        _validate_task_session_relation(relation, workspace_id)
    expected_member = str(worker.get("member") or "")
    matches = [member for member in members if member["repo"] == expected_member]
    if len(matches) != 1:
        raise AdapterError("Playbook task status does not uniquely identify the worker member")
    member = matches[0]
    if member["branch"] is None or member["head"] is None:
        raise AdapterError("Playbook task status does not prove the worker member Git identity")
    branch, head = _current_git_identity(str(worker.get("member_worktree") or ""))
    if member["branch"] != branch or member["head"] != head[:12]:
        raise AdapterError("Playbook task status member Git identity does not match the worktree")
    return {"contract": PUBLIC_STATUS_CONTRACT, "status": status, "member": member}


def _task_status_command_supported(executable: str) -> tuple[bool, int]:
    completed = subprocess.run(
        [executable, "workspace", "task", "status", "--help"],
        capture_output=True, text=True, timeout=15, check=False,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    markers = PUBLIC_STATUS_REQUIRED_KEYS | {"--workspace-id"}
    return completed.returncode == 0 and all(marker in output for marker in markers), completed.returncode


def playbook_probe(command="playbook", mode="auto", worker_json=None, status_json=None, **kwargs):
    if mode not in INTEGRATION_MODES:
        raise AdapterError("invalid integration mode")
    if mode == "disabled":
        return {"status": "not_enabled", "mode": mode, "command": command, "version": None, "worker_json_contract": False, "task_status_contract": False, "task_status_evidence_contract": False, "status_contract": "unverified", "errors": []}
    executable = shutil.which(command)
    if not executable:
        status = "not_enabled" if mode == "auto" else "missing"
        return {"status": status, "mode": mode, "command": command, "version": None, "worker_json_contract": False, "task_status_contract": False, "task_status_evidence_contract": False, "status_contract": "unverified", "errors": [] if status == "not_enabled" else ["Playbook command not found"]}
    completed = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=15, check=False)
    errors = [] if completed.returncode == 0 else ["Playbook version check failed"]
    status_command_supported, status_help_exit = _task_status_command_supported(executable)
    if not status_command_supported:
        errors.append("Playbook task status command contract is unsupported")
    evidence_compatible = False
    status_contract = "unverified"
    if (worker_json is None) != (status_json is None):
        errors.append("worker and status evidence must be supplied together")
        status_contract = "incompatible"
    if worker_json is not None and status_json is not None:
        try:
            worker = worker_facts(Path(worker_json))
            validation = validate_task_status(Path(status_json), worker)
            evidence_compatible = True
            status_contract = validation["contract"]
        except (OSError, ValueError, AdapterError) as exc:
            errors.append(str(exc))
            status_contract = "incompatible"
    return {
        "status": "compatible" if not errors and evidence_compatible else ("available" if not errors else "incompatible"),
        "mode": mode,
        "command": str(Path(executable).resolve()),
        "version": (completed.stdout or completed.stderr).strip() or None,
        "worker_json_contract": completed.returncode == 0,
        "task_status_contract": status_command_supported,
        "task_status_evidence_contract": evidence_compatible,
        "command_surface_contract": status_command_supported,
        "status_contract": status_contract,
        "checks": {"version": {"exit_code": completed.returncode, "supported": completed.returncode == 0}, "task_status": {"exit_code": status_help_exit, "supported": status_command_supported}},
        "errors": errors,
    }


def create_receipt(worker_json: Path, status_json: Path, output: Path, action: str, xiaoh_workspace_id: str, playbook_version=None, playbook_command="playbook"):
    if action not in ALLOWED_ACTIONS:
        raise AdapterError("unsupported delegated action: {}".format(action))
    executable = shutil.which(playbook_command)
    if not executable:
        raise AdapterError("Playbook command not found")
    worker_json, status_json = worker_json.expanduser().resolve(), status_json.expanduser().resolve()
    facts = worker_facts(worker_json)
    validation = validate_task_status(status_json, facts)
    receipt = {"schema_version": RECEIPT_SCHEMA, "binding_kind": "worker", "captured_at": datetime.now(timezone.utc).isoformat(), "adapter_policy": "read_only_snapshot_fail_closed", "xiaoh_workspace_id": xiaoh_workspace_id, "delegated_action": action, "playbook": {"version": playbook_version, "command": str(Path(executable).resolve()), **facts, "worker_contract_source": str(worker_json), "worker_contract_sha256": file_hash(worker_json), "status_source": str(status_json), "status_sha256": file_hash(status_json), "status_contract": validation["contract"]}}
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
        worker = worker_facts(Path(receipt["playbook"]["worker_contract_source"]))
        validation = validate_task_status(Path(receipt["playbook"]["status_source"]), worker)
        if validation["contract"] != receipt["playbook"].get("status_contract"):
            raise AdapterError("Playbook task status contract changed")
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
