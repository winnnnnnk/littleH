"""XiaoH validator evidence boundary."""

import copy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import platform

from xiaoh_validator.policy import HOME, ROOT_AGENT, SENSITIVE_KEYS
def load_json(path, report):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report.error("{}: {}".format(path, exc))
        return None

def configured_xiaoh_path():
    return Path(
        os.environ.get("XIAOH_CONFIG", str(HOME / ".xiaoh/config.json"))
    ).expanduser().resolve(strict=False)

def configured_xiaoh_data():
    config_path = configured_xiaoh_path()
    value = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("XiaoH config must be a JSON object")
    return value

def configured_vault_path():
    value = configured_xiaoh_data()
    vault = value.get("obsidian_vault")
    if not isinstance(vault, str) or not vault.strip():
        raise ValueError("XiaoH config lacks obsidian_vault")
    return Path(vault).expanduser().resolve(strict=False)

def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def path_sha256(path):
    """Hash one file or a directory tree without following symlinks."""
    path = Path(path).expanduser()
    if path.is_symlink():
        raise ValueError("evidence path must not be a symlink")
    path = path.resolve(strict=False)
    if path.is_file():
        return file_sha256(path)
    if not path.is_dir():
        raise ValueError("evidence path does not exist")
    digest = hashlib.sha256()
    for child in sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()):
        if child.is_symlink():
            raise ValueError("evidence directory must not contain symlinks")
        relative = child.relative_to(path).as_posix()
        kind = "directory" if child.is_dir() else "file"
        digest.update((kind + "\0" + relative + "\0").encode("utf-8"))
        if child.is_file():
            digest.update(file_sha256(child).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()

def canonical_json_hash(value):
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

def task_authority_hash(context):
    if not isinstance(context, dict) or context.get("schema_version") != "1.6":
        raise ValueError("authority hash requires task context schema 1.6")
    return canonical_json_hash(context)

def migrate_task_context_15_to_16(source, source_path):
    if source.get("schema_version") != "1.5":
        raise ValueError("only task context schema 1.5 can migrate to 1.6")
    migrated = copy.deepcopy(source)
    migrated["schema_version"] = "1.6"
    migrated["revision"] = source["revision"] + 1
    migrated["previous_context"] = {
        "path": str(source_path.expanduser().resolve()),
        "hash": file_sha256(source_path),
    }
    routing = migrated["routing"]
    names = routing.pop("delegation_names", {})
    actions = routing.pop("delegated_actions", {})
    routing["delegation_policies"] = {
        agent: {
            "agent_type": agent,
            "action": actions[agent],
            "task_name_prefix": names[agent],
            "allowed_paths": migrated.get("scope", {}).get("allowed_paths", []),
            "read_only": agent not in {"java_implementer", "frontend_implementer"},
        }
        for agent in routing.get("delegated_agents", [])
    }
    delegated = routing.get("delegated_agents", [])
    scope = migrated.setdefault("scope", {})
    scope.setdefault("preexisting_changes", [])
    for item in migrated.get("sources", []):
        if isinstance(item, dict):
            source_path = Path(str(item.get("path", ""))).expanduser()
            item.setdefault("kind", "directory" if source_path.is_dir() else "file")
            item.setdefault("sha256", path_sha256(source_path) if source_path.exists() else None)
    verification_items = migrated.get("verification", [])
    for index, item in enumerate(verification_items):
        if isinstance(item, dict):
            item.setdefault("id", "migrated-verification-{}".format(index + 1))
            item.setdefault("category", "contract")
            item.setdefault("required", True)
    if migrated.get("task_type") == "implementation" and not any(
        isinstance(item, dict) and item.get("category") == "scope"
        for item in verification_items
    ):
        verification_items.append({
            "id": "migrated-scope-proof",
            "category": "scope",
            "command": "attest root execution scope",
            "expected": "passed scope proof",
            "required": True,
        })
    risk = migrated.get("risk_level")
    lane = "high_risk" if risk in {"high", "critical"} else ("fast" if risk == "low" and not delegated else "standard")
    migrated["execution"] = {
        "lane": lane,
        "selection_reason": "Derived from the accepted schema 1.5 risk and delegation state.",
        "verification_scope": "full" if lane == "high_risk" else "impact_driven",
        "impact_surfaces": ["migrated accepted task scope"],
        "verification_profile": {
            "required_categories": sorted({
                item.get("category") for item in verification_items
                if isinstance(item, dict) and item.get("required") is True
            }),
            "not_applicable": [],
        },
        "effects": {"level": "none", "authorized": False, "evidence": None},
        "delegation": {
            "decision": "delegate" if delegated else "direct",
            "authorized": bool(delegated),
            "benefits": ["preserve accepted delegated specialist scope"] if delegated else [],
            "reason": "Preserve the accepted schema 1.5 delegation decision." if delegated else "No accepted delegated scope exists.",
        },
    }
    playbook = migrated["playbook"]
    for key in (
        "binding_kind", "stage", "worker_contract_source",
        "adapter_receipt", "adapter_receipt_sha256",
    ):
        playbook.pop(key, None)
    migrated["freshness"] = {
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "checked_by": ROOT_AGENT,
    }
    return migrated

def file_identity(path):
    resolved = Path(path).resolve(strict=False)
    try:
        metadata = resolved.stat()
    except OSError:
        return ("path", os.path.normcase(str(resolved)))
    return ("file", metadata.st_dev, metadata.st_ino)

def resolve_configured_workspace(workspace_path):
    value = configured_xiaoh_data()
    registry = value.get("workspaces")
    if not isinstance(registry, dict):
        raise ValueError("XiaoH config workspaces must be a JSON object")
    target = Path(workspace_path).expanduser().resolve(strict=False)
    current_platform = platform.system().lower()
    matches = []
    for workspace_id, entry in registry.items():
        if not isinstance(workspace_id, str) or not isinstance(entry, dict):
            continue
        candidates = []
        bindings = entry.get("bindings")
        if isinstance(bindings, list):
            candidates.extend(
                binding.get("root")
                for binding in bindings
                if isinstance(binding, dict)
                and isinstance(binding.get("platform"), str)
                and binding["platform"].lower() == current_platform
            )
        else:
            roots = entry.get("roots")
            legacy_platform = entry.get("platform", "unknown")
            if (
                isinstance(roots, list)
                and isinstance(legacy_platform, str)
                and legacy_platform.lower() == current_platform
            ):
                candidates.extend(roots)
        for raw_root in candidates:
            if not isinstance(raw_root, str) or not raw_root.strip():
                continue
            root = Path(raw_root).expanduser().resolve(strict=False)
            if target == root or path_is_covered(str(target), [str(root)]):
                matches.append((len(root.parts), workspace_id, entry, root))
    if not matches:
        raise ValueError("scope.workspace is not registered in XiaoH config")
    strongest_length = max(match[0] for match in matches)
    strongest = [match for match in matches if match[0] == strongest_length]
    workspace_ids = {match[1] for match in strongest}
    if len(workspace_ids) != 1:
        raise ValueError("scope.workspace matches conflicting XiaoH workspace registrations")
    _, workspace_id, entry, root = strongest[0]
    project = entry.get("project")
    system = entry.get("system")
    if not isinstance(project, str) or not project.strip():
        raise ValueError("registered XiaoH workspace lacks project")
    if not isinstance(system, str) or not system.strip():
        raise ValueError("registered XiaoH workspace lacks system")
    return {
        "workspace_id": workspace_id,
        "project": project,
        "system": system,
        "matched_root": str(root),
    }

def require_keys(data, keys, label, report):
    if not isinstance(data, dict):
        report.error("{} must be a JSON object".format(label))
        return False
    missing = [key for key in keys if key not in data]
    if missing:
        report.error("{} missing keys: {}".format(label, ", ".join(missing)))
        return False
    return True

def find_sensitive_keys(value, prefix=""):
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            location = "{}.{}".format(prefix, key).strip(".")
            if SENSITIVE_KEYS.search(key):
                found.append(location)
            found.extend(find_sensitive_keys(child, location))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(find_sensitive_keys(child, "{}[{}]".format(prefix, index)))
    return found

def normalize_agent_name(value):
    if not isinstance(value, str):
        return ""
    return "".join(character for character in value.casefold() if character.isalnum())

def parse_timestamp(value, label, report):
    if not isinstance(value, str) or not value.strip():
        report.error("{} must be an ISO-8601 timestamp".format(label))
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        report.error("{} must be an ISO-8601 timestamp".format(label))
        return None
    if parsed.tzinfo is None:
        report.error("{} must include a timezone".format(label))
        return None
    return parsed

def validate_string_list(value, label, report, non_empty=False):
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        report.error("{} must be a list of non-empty strings".format(label))
        return []
    if non_empty and not value:
        report.error("{} must be a non-empty list".format(label))
    if len(value) != len(set(value)):
        report.error("{} contains duplicates".format(label))
    return value

def path_is_covered(path, allowed_paths):
    candidate = Path(path).resolve(strict=False)
    for allowed in allowed_paths:
        root = Path(allowed).resolve(strict=False)
        if candidate == root or root in candidate.parents:
            return True
    return False

def validate_result_entries(entries, label, required_keys, allowed_statuses, report):
    if not isinstance(entries, list):
        report.error("{} must be a list".format(label))
        return
    for index, entry in enumerate(entries):
        item_label = "{}[{}]".format(label, index)
        if not require_keys(entry, required_keys, item_label, report):
            continue
        for key in required_keys:
            if not isinstance(entry[key], str) or not entry[key].strip():
                report.error("{}.{} must be a non-empty string".format(item_label, key))
        status = entry.get("status")
        if not isinstance(status, str) or status not in allowed_statuses:
            report.error("{}.status must be one of {}".format(item_label, sorted(allowed_statuses)))

def non_empty_or_none(value):
    return value is None or (isinstance(value, str) and bool(value.strip()))
