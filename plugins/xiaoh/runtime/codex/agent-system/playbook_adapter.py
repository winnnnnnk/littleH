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
import time
from datetime import datetime, timedelta, timezone
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
STATUS_REVIEW_ACTIONS = {
    "read_only_analysis",
    "design_review",
    "spec_rfc_review",
    "openspec_consistency_review",
}
BINDING_KINDS = {"worker", "status_review"}
INTEGRATION_MODES = {"auto", "enabled", "disabled"}
ACTIVE_TASK_PHASES = {
    "specification",
    "implementation",
    "handoff",
    "remote_review",
    "ready_to_finalize",
}
AGGREGATE_TASK_PHASES = ACTIVE_TASK_PHASES | {"mixed"}
NONTERMINAL_TRUTH_STATES = {"active", "unknown"}
AGGREGATE_NONTERMINAL_TRUTH_STATES = NONTERMINAL_TRUTH_STATES | {"mixed"}
NONTERMINAL_CLOSURE_STATES = {"open", "ready_for_review"}
PUBLIC_STATUS_FIELDS = (
    "workspace_id",
    "change_id",
    "members",
    "blockers",
    "next_actions",
    "refreshed_at",
    "task_truth_path",
)
PUBLIC_STATUS_KEYS = set(PUBLIC_STATUS_FIELDS)
STATUS_REVIEW_CONTRACTS = {"task_truth_v1", "task_status_public_v1"}
PUBLIC_MEMBER_BASE_FIELDS = {"repo", "branch", "head", "base_sync", "sdd"}
PUBLIC_MEMBER_OPTIONAL_FIELDS = {
    "issue",
    "mr",
    "pipeline",
    "ai_review",
    "human_approval",
}
PUBLIC_ENUMS = {
    "base_sync": {"up_to_date", "outdated", "missing", "unknown"},
    "sdd_state": {
        "missing",
        "pending_confirmation",
        "confirmed",
        "stale",
        "archived",
        "unknown",
    },
    "sdd_tasks": {"missing", "incomplete", "complete", "unknown"},
    "issue": {"not_created", "opened", "closed", "missing", "unknown"},
    "mr": {"not_created", "opened", "merged", "closed", "missing", "unknown"},
    "merge": {"mergeable", "conflict", "checking", "blocked", "unknown"},
    "pipeline": {
        "not_started",
        "pending",
        "running",
        "passed",
        "failed",
        "canceled",
        "skipped",
        "manual",
        "unknown",
    },
    "ai_review": {
        "not_started",
        "in_progress",
        "changes_requested",
        "approved",
        "stale",
        "disabled",
        "unknown",
    },
    "human_approval": {"not_started", "pending", "approved", "unknown"},
    "blocker": {
        "sdd_missing",
        "sdd_confirmation_required",
        "sdd_stale",
        "sdd_unknown",
        "worktree_unavailable",
        "local_git_unknown",
        "implementation_gate_failed",
        "implementation_gate_stale",
        "implementation_gate_unknown",
        "finalize_gate_failed",
        "finalize_gate_stale",
        "finalize_gate_unknown",
        "handoff_blocked",
        "base_branch_missing",
        "base_outdated",
        "base_sync_unknown",
        "issue_missing",
        "issue_blocked",
        "mr_missing",
        "merge_conflict",
        "mr_blocked",
        "pipeline_failed",
        "pipeline_canceled",
        "pipeline_skipped",
        "pipeline_manual",
        "pipeline_unknown",
        "ai_review_decision_required",
        "ai_review_changes_requested",
        "ai_review_stale",
        "ai_review_unknown",
        "human_approval_required",
        "human_approval_unknown",
        "post_merge_validation_required",
        "post_merge_validation_unknown",
        "remote_state_unknown",
    },
    "action": {
        "create_sdd",
        "confirm_sdd",
        "update_sdd",
        "create_issue",
        "resolve_issue_blocker",
        "start_task",
        "run_implementation_gate",
        "fix_implementation_gate",
        "run_finalize_gate",
        "fix_finalize_gate",
        "resolve_merge_conflict",
        "resolve_mr_blocker",
        "sync_target_branch",
        "push_branch",
        "create_mr",
        "complete_handoff",
        "wait_mergeability",
        "wait_pipeline",
        "fix_pipeline",
        "run_manual_pipeline",
        "confirm_ai_review_policy",
        "request_ai_review",
        "wait_ai_review",
        "address_ai_review",
        "wait_human_approval",
        "run_post_merge_validation",
        "finalize_task",
    },
}


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
    facts = {
        "task_workspace_id": task_workspace_id,
        "change_id": change_id,
        "member": member.strip(),
        "member_worktree": str(member_worktree),
        "workspace_root": str(workspace_root),
        "allowed_scope": [str(path) for path in allowed_scope],
    }
    execution_mode = payload.get("execution_mode")
    recommended_executor = payload.get("recommended_executor")
    if execution_mode is not None or recommended_executor is not None:
        facts["execution_mode"] = string_field(payload, "execution_mode")
        facts["recommended_executor"] = string_field(payload, "recommended_executor")
    return facts


def task_context_binding_hash(context: dict[str, Any]) -> str:
    if context.get("schema_version") == "1.6":
        return canonical_hash(context)
    normalized = json.loads(json.dumps(context, ensure_ascii=False))
    playbook = normalized.get("playbook")
    if isinstance(playbook, dict):
        playbook["adapter_receipt"] = None
        playbook["adapter_receipt_sha256"] = None
    return canonical_hash(normalized)


def review_facts(task_context_json: Path, artifacts: list[str]) -> dict[str, Any]:
    task_context_json = task_context_json.expanduser()
    if not task_context_json.is_absolute() or task_context_json.is_symlink():
        raise AdapterError("status_review task context必须是非符号链接绝对路径")
    task_context_json = task_context_json.resolve()
    context = load_json(task_context_json)
    if context.get("schema_version") != "1.6":
        raise AdapterError("status_review要求schema 1.6 task context")
    if context.get("intent", {}).get("domain") != "business_project":
        raise AdapterError("status_review仅适用于business_project task context")
    playbook = context.get("playbook")
    if not isinstance(playbook, dict) or playbook.get("managed") is not True:
        raise AdapterError("status_review要求Playbook受管task context")
    volatile_fields = {
        "binding_kind",
        "stage",
        "worker_contract_source",
        "adapter_receipt",
        "adapter_receipt_sha256",
        "review_artifacts",
    }
    declared_volatile = volatile_fields & set(playbook)
    if declared_volatile:
        raise AdapterError(
            "schema 1.6 task context不得包含运行时绑定字段: "
            + ", ".join(sorted(declared_volatile))
        )

    def required_context_field(key: str) -> str:
        value = playbook.get(key)
        if not isinstance(value, str) or not value.strip():
            raise AdapterError(f"status_review task context缺少playbook.{key}")
        return value.strip()

    task_workspace_id = required_context_field("task_workspace_id")
    if playbook.get("workspace_id") != task_workspace_id:
        raise AdapterError("playbook.workspace_id必须等于task_workspace_id")
    workspace_root = normalized_absolute_path(
        required_context_field("workspace_root"), "playbook.workspace_root"
    )
    member_worktree = normalized_absolute_path(
        required_context_field("member_worktree"), "playbook.member_worktree"
    )
    if (
        not workspace_root.is_dir()
        or not member_worktree.is_dir()
        or not is_within(member_worktree, workspace_root)
    ):
        raise AdapterError("playbook.member_worktree不属于workspace_root")

    raw_scope = playbook.get("allowed_scope")
    if not isinstance(raw_scope, list) or not raw_scope:
        raise AdapterError("status_review要求非空playbook.allowed_scope")
    allowed_scope = []
    for value in raw_scope:
        if not isinstance(value, str) or not value.strip():
            raise AdapterError("playbook.allowed_scope包含无效路径")
        requested = Path(value).expanduser()
        if not requested.is_absolute():
            raise AdapterError("playbook.allowed_scope必须使用绝对路径")
        resolved = requested.resolve(strict=False)
        if not resolved.exists() or not is_within(resolved, member_worktree):
            raise AdapterError("playbook.allowed_scope超出或不存在于member_worktree")
        allowed_scope.append(resolved)

    scope_paths = context.get("scope", {}).get("allowed_paths")
    if not isinstance(scope_paths, list) or not scope_paths:
        raise AdapterError("status_review要求非空scope.allowed_paths")
    context_scope = []
    for value in scope_paths:
        if not isinstance(value, str) or not value.strip():
            raise AdapterError("scope.allowed_paths包含无效路径")
        requested = Path(value).expanduser()
        if not requested.is_absolute():
            raise AdapterError("scope.allowed_paths必须使用绝对路径")
        resolved = requested.resolve(strict=False)
        if not resolved.exists():
            raise AdapterError("scope.allowed_paths包含不存在路径")
        context_scope.append(resolved)
    if not artifacts:
        raise AdapterError("status_review至少需要一个artifact")
    requested_artifacts = []
    for value in artifacts:
        if not isinstance(value, str) or not value.strip():
            raise AdapterError("status_review artifact包含无效路径")
        requested = Path(value).expanduser()
        if not requested.is_absolute():
            requested = member_worktree / requested
        requested_artifacts.append(requested.resolve(strict=False))
    if len(set(requested_artifacts)) != len(requested_artifacts):
        raise AdapterError("status_review artifact不得重复")
    entries = []
    for artifact in requested_artifacts:
        if (
            not artifact.is_file()
            or not is_within(artifact, member_worktree)
            or not any(is_within(artifact, root) or artifact == root for root in allowed_scope)
            or not any(is_within(artifact, root) or artifact == root for root in context_scope)
        ):
            raise AdapterError(f"status_review artifact不在授权范围内: {artifact}")
        entries.append(
            {
                "path": str(artifact),
                "sha256": file_hash(artifact),
                "mtime_ns": artifact.stat().st_mtime_ns,
            }
        )
    entries.sort(key=lambda item: item["path"])
    if len({entry["path"] for entry in entries}) != len(entries):
        raise AdapterError("status_review artifact不得重复")
    return {
        "task_workspace_id": task_workspace_id,
        "change_id": required_context_field("change_id"),
        "member": required_context_field("member"),
        "member_worktree": str(member_worktree),
        "workspace_root": str(workspace_root),
        "allowed_scope": [str(path) for path in allowed_scope],
        "task_context_source": str(task_context_json),
        "task_context_binding_sha256": task_context_binding_hash(context),
        "review_artifacts": [str(path) for path in sorted(requested_artifacts)],
        "artifacts": entries,
        "artifact_manifest_sha256": canonical_hash(entries),
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


def status_contract_snapshot(
    status_json: Path | dict[str, Any], worker: dict[str, Any]
) -> tuple[dict[str, Any], Path | None]:
    envelope = load_json(status_json) if isinstance(status_json, Path) else status_json
    if set(envelope) == PUBLIC_STATUS_KEYS:
        raw_path = envelope.get("task_truth_path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise AdapterError("Playbook status task_truth_path无效")
        requested = Path(raw_path).expanduser()
        if not requested.is_absolute():
            raise AdapterError("Playbook status task_truth_path必须是绝对路径")
        if requested.is_symlink():
            raise AdapterError("Playbook status task_truth_path不得是符号链接")
        source = normalized_absolute_path(raw_path, "status task_truth_path")
        if not source.is_file():
            raise AdapterError(f"Playbook Task Truth不是普通文件: {source}")
        workspace_root = Path(worker["workspace_root"]).resolve(strict=False)
        if not is_within(source, workspace_root):
            raise AdapterError("Playbook Task Truth超出workspace_root")
        expected = (
            workspace_root
            / ".playbook-workspace"
            / "truth"
            / "tasks"
            / worker["task_workspace_id"]
            / "task-truth.yaml"
        ).resolve(strict=False)
        if source != expected:
            raise AdapterError("Playbook status task_truth_path不是规范Task Truth路径")
        return envelope, status_json if isinstance(status_json, Path) else None
    evidence = envelope.get("evidence")
    if not isinstance(evidence, dict) or "raw_json_path" not in evidence:
        return envelope, status_json if isinstance(status_json, Path) else None
    raw_path = evidence["raw_json_path"]
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise AdapterError("Playbook status evidence.raw_json_path无效")
    requested = Path(raw_path).expanduser()
    if not requested.is_absolute():
        raise AdapterError("Playbook status evidence.raw_json_path必须是绝对路径")
    if requested.is_symlink():
        raise AdapterError("Playbook status evidence.raw_json_path不得是符号链接")
    source = normalized_absolute_path(raw_path, "status evidence.raw_json_path")
    if not source.is_file():
        raise AdapterError(f"Playbook status原始证据不是普通文件: {source}")
    workspace_root = Path(worker["workspace_root"]).resolve(strict=False)
    if not is_within(source, workspace_root):
        raise AdapterError("Playbook status原始证据超出workspace_root")
    return load_json(source), source


def status_task(status: dict[str, Any]) -> dict[str, Any] | None:
    task = status.get("task")
    if isinstance(task, dict):
        return task
    data = status.get("data")
    if isinstance(data, dict) and isinstance(data.get("task"), dict):
        return data["task"]
    return None


def normalized_status_worktrees(status: dict[str, Any]) -> set[str]:
    return {
        str(Path(value).expanduser().resolve(strict=False))
        for value in nested_values(status, "worktree_path")
    }


def validate_old_status_contract(status: dict[str, Any], worker: dict[str, Any]) -> str | None:
    states = set(nested_values(status, "current_state"))
    if not states:
        return None
    if len(states) != 1 or not states.issubset({"started", "blocked"}):
        raise AdapterError("Playbook task当前不是可委派的非终态")
    if worker["member_worktree"] not in normalized_status_worktrees(status):
        raise AdapterError("Playbook status未证明当前member_worktree仍有效")
    return "legacy_current_state"


def closure_objects(status: dict[str, Any], task: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [
        task.get("workspace_closure"),
        status.get("workspace_closure"),
        (status.get("workspace_state") or {}).get("closure")
        if isinstance(status.get("workspace_state"), dict)
        else None,
    ]
    return [closure for closure in candidates if isinstance(closure, dict)]


def closure_states(status: dict[str, Any], task: dict[str, Any]) -> set[str]:
    return {
        closure["status"].strip()
        for closure in closure_objects(status, task)
        if isinstance(closure.get("status"), str)
        and closure["status"].strip()
    }


def validate_active_phase(
    value: Any, label: str, *, allow_mixed: bool = False
) -> str:
    phase = value.strip() if isinstance(value, str) else ""
    allowed = AGGREGATE_TASK_PHASES if allow_mixed else ACTIVE_TASK_PHASES
    if phase not in allowed:
        raise AdapterError(f"Playbook {label}不是明确的可委派活动阶段")
    return phase


def validate_new_status_contract(
    status: dict[str, Any], worker: dict[str, Any]
) -> str:
    task = status_task(status)
    if task is None:
        raise AdapterError("Playbook task当前不是可委派的非终态")
    legacy_states = set(nested_values(status, "current_state"))
    if legacy_states and (
        len(legacy_states) != 1
        or not legacy_states.issubset({"started", "blocked"})
    ):
        raise AdapterError("Playbook新旧状态契约包含终态或冲突事实")
    task_status = validate_active_phase(
        task.get("status"), "task.status", allow_mixed=True
    )
    task_phase = validate_active_phase(
        task.get("truth_phase"), "task.truth_phase", allow_mixed=True
    )
    if task_status != task_phase:
        raise AdapterError("Playbook task.status与task.truth_phase不一致")
    task_terminal = task.get("truth_terminal")
    if task_terminal not in AGGREGATE_NONTERMINAL_TRUTH_STATES:
        raise AdapterError("Playbook task.truth_terminal不是明确的非终态事实")
    closure_facts = closure_objects(status, task)
    closures = closure_states(status, task)
    if (
        len(closures) != 1
        or not closures.issubset(NONTERMINAL_CLOSURE_STATES)
        or not closure_facts
        or any(closure.get("truth_status") != "valid" for closure in closure_facts)
    ):
        raise AdapterError("Playbook closure.status未证明任务仍为非终态")
    filesystem = task.get("filesystem")
    code_view = task.get("code_view")
    cleaned_facts = [
        source.get("cleaned")
        for source in (filesystem, code_view)
        if isinstance(source, dict) and isinstance(source.get("cleaned"), bool)
    ]
    if True in cleaned_facts:
        raise AdapterError("Playbook task事实表明工作区已清理")
    if False not in cleaned_facts:
        raise AdapterError("Playbook task未提供明确的未清理事实")
    members = task.get("members")
    if not isinstance(members, list):
        raise AdapterError("Playbook task.members缺失")
    matching = [
        member
        for member in members
        if isinstance(member, dict)
        and (member.get("repo") == worker["member"] or member.get("member") == worker["member"])
    ]
    if len(matching) != 1:
        raise AdapterError("Playbook status未唯一证明当前member")
    member = matching[0]
    member_status = validate_active_phase(member.get("status"), "member.status")
    member_phase = validate_active_phase(member.get("phase"), "member.phase")
    if member_status != member_phase:
        raise AdapterError("Playbook member.status与member.phase不一致")
    if member.get("truth_terminal") not in NONTERMINAL_TRUTH_STATES:
        raise AdapterError("Playbook member.truth_terminal不是明确的非终态事实")
    data = status.get("data")
    canonicals = [
        task.get("canonical_terminal_state"),
        status.get("canonical_terminal_state"),
        data.get("canonical_terminal_state") if isinstance(data, dict) else None,
        member.get("canonical_terminal_state"),
    ]
    for canonical in canonicals:
        if not isinstance(canonical, dict):
            continue
        terminal_status = canonical.get("status")
        if canonical.get("terminal") is True or terminal_status in {
            "closed_loop",
            "completed",
            "closed",
            "cleaned",
            "merged",
        }:
            raise AdapterError("Playbook canonical terminal state已进入终态")
    worktree = member.get("worktree_path")
    if not isinstance(worktree, str) or (
        str(Path(worktree).expanduser().resolve(strict=False))
        != worker["member_worktree"]
    ):
        raise AdapterError("Playbook status中的当前member worktree缺失或不一致")
    return "task_truth_v1"


def current_git_identity(worktree: str) -> tuple[str, str]:
    commands = (
        ("root", ["rev-parse", "--show-toplevel"]),
        ("branch", ["rev-parse", "--abbrev-ref", "HEAD"]),
        ("head", ["rev-parse", "--short=12", "HEAD"]),
    )
    values: dict[str, str] = {}
    for label, arguments in commands:
        completed = subprocess.run(
            ["git", "-C", worktree, *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )
        value = completed.stdout.strip()
        if completed.returncode or not value:
            raise AdapterError(f"无法核对当前member worktree Git {label}")
        values[label] = value
    if str(Path(values["root"]).resolve(strict=False)) != worktree:
        raise AdapterError("Playbook member_worktree不是当前Git仓库根目录")
    return values["branch"], values["head"]


def require_public_record(
    value: Any, fields: set[str], label: str
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise AdapterError(f"Playbook公共status {label}结构无效")
    return value


def require_public_text(value: Any, label: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise AdapterError(f"Playbook公共status {label}无效")


def require_public_head(value: Any, label: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or len(value) != 12 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise AdapterError(f"Playbook公共status {label}无效")


def require_public_enum(value: Any, enum: str, label: str) -> None:
    if value not in PUBLIC_ENUMS[enum]:
        raise AdapterError(f"Playbook公共status {label}无效")


def validate_public_refreshed_at(value: Any) -> None:
    require_public_text(value, "refreshed_at")
    try:
        if len(value) != 29 or value[10] != "T" or value[19] != ".":
            raise ValueError
        refreshed_at = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z")
    except ValueError as exc:
        raise AdapterError("Playbook公共status refreshed_at格式无效") from exc
    if refreshed_at.utcoffset() != timedelta(hours=8):
        raise AdapterError("Playbook公共status refreshed_at不是北京时间")
    age = (datetime.now(timezone.utc) - refreshed_at.astimezone(timezone.utc)).total_seconds()
    if age < -5 or age > MAX_SOURCE_AGE_SECONDS:
        raise AdapterError("Playbook公共status refreshed_at不是刚刚生成的快照")


def validate_public_member(value: Any, index: int) -> dict[str, Any]:
    label = f"members[{index}]"
    if not isinstance(value, dict):
        raise AdapterError(f"Playbook公共status {label}结构无效")
    optional = set(value) & PUBLIC_MEMBER_OPTIONAL_FIELDS
    if set(value) != PUBLIC_MEMBER_BASE_FIELDS | optional:
        raise AdapterError(f"Playbook公共status {label}结构无效")
    require_public_text(value.get("repo"), f"{label}.repo")
    require_public_text(value.get("branch"), f"{label}.branch", nullable=True)
    require_public_head(value.get("head"), f"{label}.head", nullable=True)
    base_sync = require_public_record(
        value.get("base_sync"), {"branch", "status"}, f"{label}.base_sync"
    )
    require_public_text(base_sync.get("branch"), f"{label}.base_sync.branch")
    require_public_enum(
        base_sync.get("status"), "base_sync", f"{label}.base_sync.status"
    )
    sdd = require_public_record(
        value.get("sdd"), {"provider", "state", "tasks"}, f"{label}.sdd"
    )
    require_public_text(sdd.get("provider"), f"{label}.sdd.provider")
    require_public_enum(sdd.get("state"), "sdd_state", f"{label}.sdd.state")
    require_public_enum(sdd.get("tasks"), "sdd_tasks", f"{label}.sdd.tasks")
    if "issue" in value:
        issue = require_public_record(value["issue"], {"status"}, f"{label}.issue")
        require_public_enum(issue.get("status"), "issue", f"{label}.issue.status")
    if "mr" in value:
        mr = require_public_record(
            value["mr"], {"status", "merge_status", "head"}, f"{label}.mr"
        )
        require_public_enum(mr.get("status"), "mr", f"{label}.mr.status")
        require_public_enum(
            mr.get("merge_status"), "merge", f"{label}.mr.merge_status"
        )
        require_public_head(mr.get("head"), f"{label}.mr.head", nullable=True)
    if "pipeline" in value:
        pipeline = require_public_record(
            value["pipeline"], {"status", "head"}, f"{label}.pipeline"
        )
        require_public_enum(
            pipeline.get("status"), "pipeline", f"{label}.pipeline.status"
        )
        require_public_head(
            pipeline.get("head"), f"{label}.pipeline.head", nullable=True
        )
    if "ai_review" in value:
        review = require_public_record(
            value["ai_review"], {"status", "head"}, f"{label}.ai_review"
        )
        require_public_enum(
            review.get("status"), "ai_review", f"{label}.ai_review.status"
        )
        require_public_head(
            review.get("head"), f"{label}.ai_review.head", nullable=True
        )
    if "human_approval" in value:
        approval = require_public_record(
            value["human_approval"], {"status"}, f"{label}.human_approval"
        )
        require_public_enum(
            approval.get("status"),
            "human_approval",
            f"{label}.human_approval.status",
        )
    return value


def validate_public_needs(status: dict[str, Any]) -> None:
    blockers = status.get("blockers")
    if not isinstance(blockers, list):
        raise AdapterError("Playbook公共status blockers无效")
    for index, blocker_value in enumerate(blockers):
        if not isinstance(blocker_value, dict):
            raise AdapterError(f"Playbook公共status blockers[{index}]结构无效")
        fields = {"code", "member"} if "member" in blocker_value else {"code"}
        blocker = require_public_record(
            blocker_value, fields, f"blockers[{index}]"
        )
        require_public_enum(
            blocker.get("code"), "blocker", f"blockers[{index}].code"
        )
        if "member" in blocker:
            require_public_text(blocker["member"], f"blockers[{index}].member")
    actions = status.get("next_actions")
    if actions is None:
        return
    if not isinstance(actions, list):
        raise AdapterError("Playbook公共status next_actions无效")
    for index, action_value in enumerate(actions):
        if not isinstance(action_value, dict):
            raise AdapterError(f"Playbook公共status next_actions[{index}]结构无效")
        fields = {"action", "member"} if "member" in action_value else {"action"}
        action = require_public_record(
            action_value, fields, f"next_actions[{index}]"
        )
        require_public_enum(
            action.get("action"), "action", f"next_actions[{index}].action"
        )
        if "member" in action:
            require_public_text(action["member"], f"next_actions[{index}].member")


def validate_public_status_contract(
    status: dict[str, Any], worker: dict[str, Any]
) -> str:
    if set(status) != PUBLIC_STATUS_KEYS:
        raise AdapterError("Playbook公共status字段集合不符合契约")
    require_public_text(status.get("workspace_id"), "workspace_id")
    require_public_text(status.get("change_id"), "change_id")
    validate_public_refreshed_at(status.get("refreshed_at"))
    require_public_text(status.get("task_truth_path"), "task_truth_path")
    members = status.get("members")
    if not isinstance(members, list):
        raise AdapterError("Playbook公共status members缺失")
    validated_members = [
        validate_public_member(member, index)
        for index, member in enumerate(members)
    ]
    validate_public_needs(status)
    matching = [
        member
        for member in validated_members
        if member.get("repo") == worker["member"]
    ]
    if len(matching) != 1:
        raise AdapterError("Playbook公共status未唯一证明当前member")
    member = matching[0]
    branch = member.get("branch")
    head = member.get("head")
    if not isinstance(branch, str) or not branch.strip():
        raise AdapterError("Playbook公共status未证明当前member branch")
    if not isinstance(head, str) or len(head) != 12:
        raise AdapterError("Playbook公共status未证明当前member HEAD")
    mr = member.get("mr")
    if isinstance(mr, dict) and mr.get("status") in {"merged", "unknown"}:
        raise AdapterError("Playbook公共status未证明当前member处于明确非终态")
    if any(
        blocker.get("code") == "remote_state_unknown"
        and blocker.get("member", worker["member"]) == worker["member"]
        for blocker in status["blockers"]
    ):
        raise AdapterError("Playbook公共status远端事实不足以证明当前member非终态")
    if status.get("next_actions") == []:
        raise AdapterError("Playbook公共status表明任务已清理")
    current_branch, current_head = current_git_identity(worker["member_worktree"])
    if current_branch != branch or current_head != head:
        raise AdapterError("Playbook公共status与当前member Git身份不一致")
    return "task_status_public_v1"


def validate_status_snapshot(
    status_json: Path | dict[str, Any], worker: dict[str, Any]
) -> dict[str, Any]:
    status, source = status_contract_snapshot(status_json, worker)
    if isinstance(status.get("status"), str) and status["status"].casefold() in {"error", "failed"}:
        raise AdapterError(f"Playbook status JSON返回失败: {status['status']}")
    workspace_ids = set(nested_values(status, "workspace_id"))
    if workspace_ids != {worker["task_workspace_id"]}:
        raise AdapterError("Playbook status与worker的workspace_id不唯一或不一致")
    change_ids = set(nested_values(status, "change_id"))
    if change_ids != {worker["change_id"]}:
        raise AdapterError("Playbook status与worker的change_id不唯一或不一致")
    if set(status) == PUBLIC_STATUS_KEYS:
        contract = validate_public_status_contract(status, worker)
    elif status_task(status) is not None:
        contract = validate_new_status_contract(status, worker)
    else:
        contract = validate_old_status_contract(status, worker)
    if contract is None:
        raise AdapterError("Playbook task当前不是可委派的非终态")
    semantics = status_semantic_snapshot(status, worker, contract)
    return {
        "contract": contract,
        "source": str(source) if source else None,
        "semantics": semantics,
        "semantics_sha256": canonical_hash(semantics),
    }


def status_semantic_snapshot(
    status: dict[str, Any], worker: dict[str, Any], contract: str
) -> dict[str, Any]:
    if contract == "task_status_public_v1":
        member = next(
            item
            for item in status["members"]
            if isinstance(item, dict) and item.get("repo") == worker["member"]
        )
        mr = member.get("mr")
        return {
            "contract": contract,
            "member": {
                "repo": member.get("repo"),
                "branch": member.get("branch"),
                "head": member.get("head"),
                "mr_status": mr.get("status") if isinstance(mr, dict) else None,
            },
            "blockers": status.get("blockers"),
            "next_actions": status.get("next_actions"),
        }
    if contract != "task_truth_v1":
        return {
            "contract": contract,
            "current_state": sorted(set(nested_values(status, "current_state"))),
        }
    task = status_task(status)
    if task is None:
        raise AdapterError("Playbook task状态语义缺失")
    members = task.get("members")
    matching = [
        member
        for member in members if isinstance(members, list) and isinstance(member, dict)
        and (member.get("repo") == worker["member"] or member.get("member") == worker["member"])
    ]
    if len(matching) != 1:
        raise AdapterError("Playbook status未唯一证明当前member")
    member = matching[0]
    filesystem = task.get("filesystem")
    code_view = task.get("code_view")
    return {
        "contract": contract,
        "task": {
            "status": task.get("status"),
            "truth_phase": task.get("truth_phase"),
            "truth_terminal": task.get("truth_terminal"),
            "filesystem_cleaned": (
                filesystem.get("cleaned") if isinstance(filesystem, dict) else None
            ),
            "code_view_cleaned": (
                code_view.get("cleaned") if isinstance(code_view, dict) else None
            ),
        },
        "member": {
            "status": member.get("status"),
            "phase": member.get("phase"),
            "truth_terminal": member.get("truth_terminal"),
            "worktree_path": str(
                Path(member["worktree_path"]).expanduser().resolve(strict=False)
            ),
        },
        "closures": sorted(closure_states(status, task)),
        "closure_truth": sorted(
            canonical_hash(closure)
            for closure in closure_objects(status, task)
        ),
    }


def source_timestamps(
    worker_json: Path, status_json: Path, contract_source: Path | None = None
) -> dict[str, int]:
    now_ns = datetime.now(timezone.utc).timestamp() * 1_000_000_000
    worker_mtime = worker_json.stat().st_mtime_ns
    status_mtime = status_json.stat().st_mtime_ns
    source_mtime = contract_source.stat().st_mtime_ns if contract_source else status_mtime
    for label, value in (
        ("worker", worker_mtime),
        ("status", status_mtime),
        ("status contract", source_mtime),
    ):
        age = (now_ns - value) / 1_000_000_000
        if age < -5 or age > MAX_SOURCE_AGE_SECONDS:
            raise AdapterError(f"Playbook {label} JSON不是刚刚生成的快照")
    if (
        min(status_mtime, source_mtime) < worker_mtime
        or max(status_mtime, source_mtime) - worker_mtime
        > MAX_SOURCE_AGE_SECONDS * 1_000_000_000
    ):
        raise AdapterError("Playbook status JSON必须紧邻worker JSON之后生成")
    result = {
        "worker_contract_mtime_ns": worker_mtime,
        "status_mtime_ns": status_mtime,
    }
    if contract_source and contract_source != status_json:
        result["status_contract_mtime_ns"] = source_mtime
    return result


def status_source_timestamps(
    status_json: Path, contract_source: Path | None = None
) -> dict[str, int]:
    now_ns = datetime.now(timezone.utc).timestamp() * 1_000_000_000
    status_mtime = status_json.stat().st_mtime_ns
    source_mtime = contract_source.stat().st_mtime_ns if contract_source else status_mtime
    for label, value in (("status", status_mtime), ("status contract", source_mtime)):
        age = (now_ns - value) / 1_000_000_000
        if age < -5 or age > MAX_SOURCE_AGE_SECONDS:
            raise AdapterError(f"Playbook {label} JSON不是刚刚生成的快照")
    if abs(source_mtime - status_mtime) > MAX_SOURCE_AGE_SECONDS * 1_000_000_000:
        raise AdapterError("Playbook status wrapper与原始证据不是紧邻快照")
    result = {"status_mtime_ns": status_mtime}
    if contract_source and contract_source != status_json:
        result["status_contract_mtime_ns"] = source_mtime
    return result


def current_status_snapshot(
    playbook: dict[str, Any],
) -> tuple[dict[str, Any], int, int]:
    command = normalized_absolute_path(playbook["command"], "playbook.command")
    started_ns = time.time_ns()
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
    finished_ns = time.time_ns()
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
    return value, started_ns, finished_ns


def validate_live_status_snapshot(
    playbook: dict[str, Any], worker: dict[str, Any]
) -> dict[str, Any]:
    live, started_ns, finished_ns = current_status_snapshot(playbook)
    validation = validate_status_snapshot(live, worker)
    source_value = validation.get("source")
    if not source_value:
        return validation
    source = normalized_absolute_path(source_value, "Playbook live status raw evidence")
    source_mtime = source.stat().st_mtime_ns
    if source_mtime < started_ns or source_mtime > finished_ns:
        raise AdapterError(
            "Playbook live status原始证据不是由本次status命令生成"
        )
    return validation


def playbook_probe(
    command: str = "playbook",
    mode: str = "auto",
    worker_json: Path | None = None,
    status_json: Path | None = None,
    check_source_freshness: bool = True,
    require_worker: bool = True,
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
    for name, arguments, required_markers in (
        ("version", ["--version"], ("playbook version",)),
        (
            "task_status",
            ["workspace", "task", "status", "--help"],
            ("--output json", "--full"),
        ),
        (
            "worker_start",
            ["workspace", "task", "worker", "start", "--help"],
            ("child_worker_context",),
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
            "supported": completed.returncode == 0
            and any(marker in output for marker in required_markers),
        }
        if not checks[name]["supported"] and (
            name != "worker_start" or require_worker
        ):
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
    command_compatible = checks["task_status"]["supported"] and (
        checks["worker_start"]["supported"] or not require_worker
    )
    evidence_compatible = False
    status_contract = "unverified"
    if (worker_json is None) != (status_json is None):
        errors.append("Playbook probe必须同时提供worker和status证据")
        status_contract = "incompatible"
    elif worker_json is not None and status_json is not None and command_compatible:
        try:
            worker = worker_facts(worker_json.expanduser().resolve())
            validation = validate_status_snapshot(
                status_json.expanduser().resolve(), worker
            )
            if check_source_freshness:
                contract_source = (
                    Path(validation["source"]).resolve()
                    if validation["source"]
                    else status_json.expanduser().resolve()
                )
                source_timestamps(
                    worker_json.expanduser().resolve(),
                    status_json.expanduser().resolve(),
                    contract_source,
                )
            evidence_compatible = True
            status_contract = validation["contract"]
        except (AdapterError, OSError) as exc:
            errors.append(f"Playbook实际状态契约不兼容: {exc}")
            status_contract = "incompatible"
    status = (
        "incompatible"
        if not command_compatible or status_contract == "incompatible"
        else ("compatible" if evidence_compatible else "available")
    )
    return {
        "status": status,
        "mode": mode,
        "command": executable,
        "version": version,
        "worker_json_contract": checks["worker_start"]["supported"],
        "task_status_contract": evidence_compatible,
        "command_surface_contract": command_compatible,
        "status_contract": status_contract,
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
    validation = validate_status_snapshot(status_json, worker)
    contract_source = (
        Path(validation["source"]).resolve()
        if validation["source"]
        else status_json
    )
    timestamps = source_timestamps(worker_json, status_json, contract_source)
    executable = shutil.which(playbook_command)
    if not executable:
        raise AdapterError(f"未找到Playbook命令: {playbook_command}")
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "binding_kind": "worker",
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
            "status_contract": validation["contract"],
            "status_semantics": validation["semantics"],
            "status_semantics_sha256": validation["semantics_sha256"],
            **timestamps,
        },
    }
    if contract_source != status_json:
        receipt["playbook"].update(
            {
                "status_contract_source": str(contract_source),
                "status_contract_sha256": file_hash(contract_source),
            }
        )
    receipt["binding_sha256"] = canonical_hash(receipt)
    output = output.expanduser().resolve()
    atomic_write_json(output, receipt)
    return {
        "status": "captured",
        "receipt_path": str(output),
        "receipt_sha256": file_hash(output),
        "receipt": receipt,
    }


def create_review_receipt(
    task_context_json: Path,
    status_json: Path,
    artifacts: list[str],
    output: Path,
    action: str,
    playbook_version: str | None = None,
    playbook_command: str = "playbook",
) -> dict[str, Any]:
    if action not in STATUS_REVIEW_ACTIONS:
        raise AdapterError(f"status_review不支持delegated action: {action}")
    status_json = status_json.expanduser().resolve()
    review = review_facts(task_context_json, artifacts)
    validation = validate_status_snapshot(status_json, review)
    if validation["contract"] not in STATUS_REVIEW_CONTRACTS:
        raise AdapterError(
            "status_review要求Playbook可验证的当前状态契约"
        )
    contract_source = (
        Path(validation["source"]).resolve()
        if validation["source"]
        else status_json
    )
    timestamps = status_source_timestamps(status_json, contract_source)
    executable = shutil.which(playbook_command)
    if not executable:
        raise AdapterError(f"未找到Playbook命令: {playbook_command}")
    context = load_json(Path(review["task_context_source"]))
    xiaoh_workspace_id = context["playbook"].get("xiaoh_workspace_id")
    if not isinstance(xiaoh_workspace_id, str) or not xiaoh_workspace_id.strip():
        raise AdapterError("status_review task context缺少xiaoh_workspace_id")
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "binding_kind": "status_review",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "adapter_policy": "read_only_status_review_fail_closed",
        "xiaoh_workspace_id": xiaoh_workspace_id.strip(),
        "delegated_action": action,
        "playbook": {
            "version": playbook_version,
            "command": str(Path(executable).resolve()),
            **review,
            "status_source": str(status_json),
            "status_sha256": file_hash(status_json),
            "status_contract": validation["contract"],
            "status_semantics": validation["semantics"],
            "status_semantics_sha256": validation["semantics_sha256"],
            **timestamps,
        },
    }
    if contract_source != status_json:
        receipt["playbook"].update(
            {
                "status_contract_source": str(contract_source),
                "status_contract_sha256": file_hash(contract_source),
            }
        )
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
    binding_kind = receipt.get("binding_kind", "worker")
    if binding_kind not in BINDING_KINDS:
        raise AdapterError("adapter receipt binding_kind无效")
    if (
        binding_kind == "status_review"
        and receipt.get("delegated_action") not in STATUS_REVIEW_ACTIONS
    ):
        raise AdapterError("status_review receipt不得授权写入或编码动作")
    if expected_action and receipt["delegated_action"] != expected_action:
        raise AdapterError("adapter receipt delegated_action与委派动作不一致")
    captured_at = parse_timestamp(receipt.get("captured_at"))
    age = (datetime.now(timezone.utc) - captured_at).total_seconds()
    if age < -300 or (max_age_seconds is not None and age > max_age_seconds):
        raise AdapterError(f"adapter receipt已过期: {int(age)}秒")
    playbook = receipt.get("playbook")
    if not isinstance(playbook, dict):
        raise AdapterError("adapter receipt缺少playbook对象")
    if (
        binding_kind == "status_review"
        and playbook.get("status_contract") not in STATUS_REVIEW_CONTRACTS
    ):
        raise AdapterError(
            "status_review receipt要求Playbook可验证的当前状态契约"
        )
    required_playbook_fields = [
        "task_workspace_id",
        "change_id",
        "member",
        "member_worktree",
        "workspace_root",
        "allowed_scope",
        "command",
        "status_source",
        "status_sha256",
        "status_mtime_ns",
    ]
    if binding_kind == "worker":
        required_playbook_fields.extend(
            [
                "worker_contract_source",
                "worker_contract_sha256",
                "worker_contract_mtime_ns",
            ]
        )
    else:
        required_playbook_fields.extend(
            [
                "task_context_source",
                "task_context_binding_sha256",
                "review_artifacts",
                "artifacts",
                "artifact_manifest_sha256",
                "status_semantics",
                "status_semantics_sha256",
            ]
        )
    for key in required_playbook_fields:
        if key not in playbook:
            raise AdapterError(f"adapter receipt缺少playbook.{key}")
    if check_sources:
        source_pairs = [
            ("status_source", "status_sha256"),
            ("status_contract_source", "status_contract_sha256"),
        ]
        if binding_kind == "worker":
            source_pairs.insert(
                0, ("worker_contract_source", "worker_contract_sha256")
            )
        for path_key, hash_key in source_pairs:
            if path_key not in playbook:
                continue
            source = normalized_absolute_path(playbook[path_key], f"playbook.{path_key}")
            if file_hash(source) != playbook[hash_key]:
                raise AdapterError(f"adapter receipt来源已变化: {source}")
            mtime_key = {
                "status_source": "status_mtime_ns",
                "status_contract_source": "status_contract_mtime_ns",
                "worker_contract_source": "worker_contract_mtime_ns",
            }[path_key]
            if source.stat().st_mtime_ns != playbook[mtime_key]:
                raise AdapterError(f"adapter receipt来源时间已变化: {source}")
        if binding_kind == "worker":
            worker = worker_facts(Path(playbook["worker_contract_source"]))
        else:
            context_source = normalized_absolute_path(
                playbook["task_context_source"], "playbook.task_context_source"
            )
            context = load_json(context_source)
            if (
                task_context_binding_hash(context)
                != playbook["task_context_binding_sha256"]
            ):
                raise AdapterError("adapter receipt task context绑定已变化")
            artifacts = playbook.get("artifacts")
            if not isinstance(artifacts, list) or not artifacts:
                raise AdapterError("status_review receipt artifacts无效")
            artifact_paths = []
            for artifact_entry in artifacts:
                if not isinstance(artifact_entry, dict):
                    raise AdapterError("status_review receipt artifact条目无效")
                artifact_value = artifact_entry.get("path")
                if not isinstance(artifact_value, str) or not artifact_value.strip():
                    raise AdapterError("status_review receipt artifact路径无效")
                artifact = normalized_absolute_path(
                    artifact_value, "status_review artifact"
                )
                if (
                    not artifact.is_file()
                    or file_hash(artifact) != artifact_entry.get("sha256")
                    or artifact.stat().st_mtime_ns != artifact_entry.get("mtime_ns")
                ):
                    raise AdapterError(f"status_review artifact已变化: {artifact}")
                artifact_paths.append(str(artifact))
            worker = review_facts(context_source, artifact_paths)
            if (
                worker["artifact_manifest_sha256"]
                != playbook["artifact_manifest_sha256"]
            ):
                raise AdapterError("status_review artifact manifest已变化")
            if worker["review_artifacts"] != playbook["review_artifacts"]:
                raise AdapterError("status_review权威artifact清单已变化")
        for key in (
            "task_workspace_id", "change_id", "member", "member_worktree",
            "workspace_root", "allowed_scope",
        ):
            if worker[key] != playbook[key]:
                raise AdapterError(f"adapter receipt与worker来源不一致: {key}")
        for key in (
            "execution_mode",
            "recommended_executor",
            "task_context_binding_sha256",
            "artifact_manifest_sha256",
        ):
            if key in playbook and worker.get(key) != playbook[key]:
                raise AdapterError(f"adapter receipt与绑定来源不一致: {key}")
        validation = validate_status_snapshot(Path(playbook["status_source"]), worker)
        resolved_source = validation["source"] or playbook["status_source"]
        if resolved_source != playbook.get("status_contract_source", playbook["status_source"]):
            raise AdapterError("adapter receipt与status原始证据来源不一致")
        if (
            "status_contract" in playbook
            and validation["contract"] != playbook["status_contract"]
        ):
            raise AdapterError("adapter receipt与status状态契约不一致")
        if binding_kind == "status_review" and (
            validation["semantics"] != playbook["status_semantics"]
            or validation["semantics_sha256"] != playbook["status_semantics_sha256"]
        ):
            raise AdapterError("status_review捕获状态语义已变化")
    if check_live_status:
        live_validation = validate_live_status_snapshot(
            playbook,
            {
                key: playbook[key]
                for key in (
                    "task_workspace_id", "change_id", "member", "member_worktree",
                    "workspace_root", "allowed_scope",
                )
            },
        )
        if binding_kind == "status_review" and (
            live_validation["semantics"] != playbook["status_semantics"]
            or live_validation["semantics_sha256"]
            != playbook["status_semantics_sha256"]
        ):
            raise AdapterError("status_review实时任务状态语义已变化")
    return receipt


def emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    probe = subparsers.add_parser("probe")
    probe.add_argument("--playbook-command", default="playbook")
    probe.add_argument("--mode", choices=sorted(INTEGRATION_MODES), default="auto")
    probe.add_argument("--worker-json")
    probe.add_argument("--status-json")
    capture = subparsers.add_parser("capture")
    capture.add_argument("--worker-json", required=True)
    capture.add_argument("--status-json", required=True)
    capture.add_argument("--output", required=True)
    capture.add_argument("--action", required=True, choices=sorted(ALLOWED_ACTIONS))
    capture.add_argument("--xiaoh-workspace-id", required=True)
    capture.add_argument("--playbook-version")
    capture.add_argument("--playbook-command", default="playbook")
    capture_review = subparsers.add_parser("capture-review")
    capture_review.add_argument("--task-context", required=True)
    capture_review.add_argument("--status-json", required=True)
    capture_review.add_argument("--artifact", action="append", required=True)
    capture_review.add_argument("--output", required=True)
    capture_review.add_argument(
        "--action", required=True, choices=sorted(STATUS_REVIEW_ACTIONS)
    )
    capture_review.add_argument("--playbook-version")
    capture_review.add_argument("--playbook-command", default="playbook")
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
            result = playbook_probe(
                args.playbook_command,
                args.mode,
                Path(args.worker_json) if args.worker_json else None,
                Path(args.status_json) if args.status_json else None,
            )
            emit(result)
            return 0 if result["status"] in {"available", "compatible", "not_enabled"} else 1
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
        if args.command == "capture-review":
            emit(
                create_review_receipt(
                    Path(args.task_context),
                    Path(args.status_json),
                    args.artifact,
                    Path(args.output),
                    args.action,
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
