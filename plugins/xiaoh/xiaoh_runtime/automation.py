"""XiaoH modular runtime boundary."""

from __future__ import annotations

from .common import *
from .config import *
from .workspace import *

AUTOMATION_TASK_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")


def automation_path(codex: Path, task_id: str) -> Path:
    if (
        not isinstance(task_id, str)
        or not AUTOMATION_TASK_ID_PATTERN.fullmatch(task_id)
    ):
        raise ValueError(f"托管定时任务标识无效: {task_id!r}")
    return validated_descendant(
        codex / "automations",
        Path(task_id) / "automation.toml",
        "托管定时任务",
    )


def automation_snapshot(codex: Path, task_id: str) -> tuple[dict | None, str | None]:
    try:
        path = automation_path(codex, task_id)
        if tomllib is not None:
            with path.open("rb") as stream:
                value = tomllib.load(stream)
        else:
            value = parse_flat_toml(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("根节点不是对象")
        return value, None
    except (OSError, ValueError) as exc:
        return None, f"无法读取托管定时任务 {task_id}: {exc}"

def parse_flat_toml(text: str) -> dict:
    """Parse the scalar top-level subset used by Codex automation.toml files."""
    result: dict = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_-]+)\s*=\s*(.+)", line)
        if not match:
            raise ValueError(f"第 {line_number} 行不是受支持的键值")
        key, encoded = match.groups()
        if encoded.startswith('"'):
            try:
                value = json.loads(encoded)
            except json.JSONDecodeError as exc:
                raise ValueError(f"第 {line_number} 行字符串无效: {exc}") from exc
        elif encoded in {"true", "false"}:
            value = encoded == "true"
        elif re.fullmatch(r"-?\d+", encoded):
            value = int(encoded)
        elif encoded.startswith(("[", "{")):
            # Managed automation verification does not inspect arrays or inline tables.
            value = encoded
        else:
            raise ValueError(f"第 {line_number} 行值类型不受支持")
        result[key] = value
    return result

def automation_report(local: dict, codex: Path) -> dict:
    bindings = local.get("managed_automations")
    if not isinstance(bindings, dict):
        bindings = {}
    warnings: list[str] = []
    tasks: list[dict] = []
    for logical_id, template in automation_templates().items():
        binding = bindings.get(logical_id)
        if not isinstance(binding, dict):
            binding = {}
        task_id = binding.get("task_id")
        applied = binding.get("applied_template_version")
        desired = template["template_version"]
        snapshot = None
        if not isinstance(task_id, str) or not task_id:
            state = "unbound"
            if template.get("required"):
                warnings.append(f"必需的托管定时任务尚未绑定: {logical_id}")
        elif applied != desired:
            state = "drifted"
            warnings.append(f"托管定时任务版本漂移: {logical_id}（已应用 {applied}，期望 {desired}）")
        else:
            snapshot, snapshot_error = automation_snapshot(codex, task_id)
            if snapshot_error:
                state = "unreadable"
                warnings.append(snapshot_error)
            else:
                mismatches = []
                for key, expected in (
                    ("id", task_id),
                    ("name", template["name"]),
                    ("prompt", template["prompt"]),
                    ("status", template["default_status"]),
                ):
                    if snapshot.get(key) != expected:
                        mismatches.append(key)
                if mismatches:
                    state = "runtime_drifted"
                    warnings.append(
                        f"托管定时任务运行态漂移: {logical_id}（{', '.join(mismatches)}）"
                    )
                else:
                    state = "configured"
        matching_ids = []
        automation_root = codex / "automations"
        if automation_root.is_dir():
            for candidate in automation_root.glob("*/automation.toml"):
                candidate_id = candidate.parent.name
                candidate_snapshot, _ = automation_snapshot(codex, candidate_id)
                if candidate_snapshot and candidate_snapshot.get("name") == template["name"]:
                    matching_ids.append(candidate_id)
        if len(matching_ids) > 1:
            state = "duplicate"
            warnings.append(
                f"托管定时任务存在重复实例: {logical_id}（{', '.join(sorted(matching_ids))}）"
            )
        tasks.append({
            "logical_id": logical_id,
            "task_id": task_id,
            "required": bool(template.get("required")),
            "state": state,
            "applied_template_version": applied,
            "desired_template_version": desired,
            "actual_status": snapshot.get("status") if snapshot else None,
            "actual_prompt_hash": (
                hashlib.sha256(snapshot["prompt"].encode("utf-8")).hexdigest()
                if snapshot and isinstance(snapshot.get("prompt"), str)
                else None
            ),
            "matching_task_ids": sorted(matching_ids),
        })
    return {
        "status": "degraded" if warnings else "complete",
        "tasks": tasks,
        "warnings": warnings,
        "runtime_verified": not warnings,
    }

def bind_automation(config_path: Path, codex: Path, vault: Path, logical_id: str, task_id: str) -> dict:
    templates = automation_templates()
    if logical_id not in templates:
        return {
            "status": "failed",
            "codex_home": str(codex),
            "obsidian_vault": str(vault),
            "config": str(config_path),
            "errors": [f"未知托管定时任务: {logical_id}"],
            "warnings": [],
        }
    template = templates[logical_id]
    snapshot, snapshot_error = automation_snapshot(codex, task_id)
    if snapshot_error:
        return {
            "status": "failed",
            "codex_home": str(codex),
            "obsidian_vault": str(vault),
            "config": str(config_path),
            "errors": [snapshot_error],
            "warnings": [],
        }
    mismatches = [
        key
        for key, expected in (
            ("id", task_id),
            ("name", template["name"]),
            ("prompt", template["prompt"]),
            ("status", template["default_status"]),
        )
        if snapshot.get(key) != expected
    ]
    if mismatches:
        return {
            "status": "failed",
            "codex_home": str(codex),
            "obsidian_vault": str(vault),
            "config": str(config_path),
            "errors": [f"托管定时任务与模板不一致: {logical_id}（{', '.join(mismatches)}）"],
            "warnings": [],
        }
    with config_lock(config_path):
        local = load_json(config_path)
        bindings = local.get("managed_automations")
        if not isinstance(bindings, dict):
            bindings = {}
            local["managed_automations"] = bindings
        bindings[logical_id] = {
            "task_id": task_id,
            "applied_template_version": template["template_version"],
            "status": "bound",
            "readback": {
                "status": snapshot.get("status"),
                "name": snapshot.get("name"),
                "prompt_hash": hashlib.sha256(snapshot["prompt"].encode("utf-8")).hexdigest(),
                "verified_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            },
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        atomic_write_json(config_path, local, config_path.with_suffix(config_path.suffix + ".bak"))
    return {
        "status": "passed",
        "operation": "bind-automation",
        "codex_home": str(codex),
        "obsidian_vault": str(vault),
        "config": str(config_path),
        "logical_id": logical_id,
        "task_id": task_id,
        "template_version": template["template_version"],
        "actual_status": snapshot.get("status"),
        "errors": [],
        "warnings": [],
    }

def reconcile_automation_candidates(local: dict, stage_codex: Path) -> dict:
    bindings = local.get("managed_automations")
    if not isinstance(bindings, dict):
        bindings = {}
    pending: list[str] = []
    updated: list[str] = []
    paths: list[Path] = []
    for logical_id, template in automation_templates().items():
        binding = bindings.get(logical_id)
        if not isinstance(binding, dict):
            binding = {}
        task_id = binding.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            if template.get("required"):
                pending.append(logical_id)
            continue
        path = automation_path(stage_codex, task_id)
        snapshot, snapshot_error = automation_snapshot(stage_codex, task_id)
        if snapshot_error:
            pending.append(logical_id)
            continue
        if snapshot.get("id") != task_id:
            raise ValueError(f"自动化稳定身份冲突: {logical_id}: {task_id}")
        text = path.read_text(encoding="utf-8")
        changed = False
        for key, desired in (
            ("name", template["name"]),
            ("prompt", template["prompt"]),
            ("status", template["default_status"]),
        ):
            pattern = re.compile(rf"(?m)^{re.escape(key)}\s*=.*$")
            matches = pattern.findall(text)
            if len(matches) != 1:
                raise ValueError(f"自动化字段无法安全对账: {logical_id}: {key}")
            replacement = f"{key} = {json.dumps(desired, ensure_ascii=False)}"
            updated_text = pattern.sub(replacement, text, count=1)
            changed = changed or updated_text != text
            text = updated_text
        if changed:
            atomic_write_text(path, text)
            updated.append(logical_id)
        refreshed, refreshed_error = automation_snapshot(stage_codex, task_id)
        if refreshed_error:
            raise ValueError(refreshed_error)
        bindings[logical_id] = {
            **binding,
            "task_id": task_id,
            "applied_template_version": template["template_version"],
            "status": "bound",
            "readback": {
                "status": refreshed.get("status"),
                "name": refreshed.get("name"),
                "prompt_hash": hashlib.sha256(
                    refreshed["prompt"].encode("utf-8")
                ).hexdigest(),
                "verified_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            },
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        paths.append(path)
    local["managed_automations"] = bindings
    return {
        "status": "pending" if pending else "complete",
        "pending": pending,
        "updated": updated,
        "paths": paths,
    }
