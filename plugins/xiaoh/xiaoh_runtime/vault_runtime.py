"""XiaoH modular runtime boundary."""

from __future__ import annotations

from .common import *
from .config import *
from .workspace import *
from .automation import *
from .plugin_state import *

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
                atomic_write_text(path, updated)

def managed_vault_files() -> dict[str, dict]:
    manifest = load_json(VAULT_MANIFEST)
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError(f"{VAULT_MANIFEST} 的 files 必须是对象")
    return files

def vault_template_report(vault: Path) -> dict:
    source = RUNTIME / "obsidian/development-vault"
    warnings = []
    files = []
    effective = {item["path"]: item for item in vault_effective_report(vault)["files"]}
    for relative in managed_vault_files():
        source_path = source / relative
        destination = vault / relative
        expected = file_hash(source_path)
        actual = file_hash(destination) if destination.is_file() else None
        state = effective[relative]["state"]
        if state not in {"current", "user_customized_compatible"}:
            warnings.append(f"Vault受管模板未升级: {relative}（{state}）")
        files.append({"path": relative, "state": state, "reason": effective[relative]["reason"], "expected_hash": expected, "actual_hash": actual})
    return {"status": "degraded" if warnings else "complete", "files": files, "warnings": warnings}

def vault_effective_report(vault: Path) -> dict:
    source_root = RUNTIME / "obsidian/development-vault"
    files = []
    for relative, metadata in managed_vault_files().items():
        source = source_root / relative
        destination = vault / relative
        state = "current"
        reason = None
        if destination.is_symlink():
            state, reason = "corrupted", "managed file is a symbolic link"
        elif not destination.exists():
            state, reason = "missing", "managed file is missing"
        elif not destination.is_file():
            state, reason = "corrupted", "managed path is not a file"
        elif vault.resolve() not in destination.resolve().parents:
            state, reason = "corrupted", "managed file escapes the configured Vault"
        else:
            try:
                expected = file_hash(source)
                actual = file_hash(destination)
                text = destination.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                state, reason = "corrupted", str(exc)
            else:
                if actual == expected:
                    state = "current"
                elif actual in metadata.get("legacy_hashes", []):
                    state = "user_customized_compatible"
                    reason = "recognized compatible historical template"
                elif destination.suffix == ".base":
                    required = (
                        "filters:",
                        "properties:",
                        "views:",
                        'file.ext == "md"',
                        "is_template != true",
                    )
                    if all(fragment in text for fragment in required):
                        state = "user_customized_compatible"
                        reason = "required filters and behavior remain present"
                    else:
                        state = "incompatible_drift"
                        reason = "required filters or behavior cannot be proven"
                else:
                    state = "incompatible_drift"
                    reason = "unrecognized managed-template change"
        files.append({"path": relative, "state": state, "reason": reason})
    states = {item["state"] for item in files}
    if "corrupted" in states:
        status = "corrupted"
    elif "missing" in states:
        status = "missing"
    elif "incompatible_drift" in states:
        status = "incompatible_drift"
    elif "user_customized_compatible" in states:
        status = "user_customized_compatible"
    else:
        status = "current"
    return {"status": status, "files": files}

def sync_vault_runtime(vault: Path) -> tuple[list[Path], list[str]]:
    source = RUNTIME / "obsidian/development-vault"
    touched: list[Path] = []
    conflicts: list[str] = []
    managed = managed_vault_files()
    state_path = vault / ".xiaoh-managed.json"
    state = load_json(state_path, {"schema_version": "1.0", "files": {}})
    previous_files = state.get("files")
    if not isinstance(previous_files, dict):
        previous_files = {}
    next_files: dict[str, str] = {}
    for old_relative, new_relative in (
        ("04-架构与决策/Agent协作角色.md", "90-个人系统/Agent协作角色.md"),
        ("04-架构与决策/Agent进化台账.md", "90-个人系统/Agent进化台账.md"),
    ):
        old_path = vault / old_relative
        new_path = vault / new_relative
        if old_path.is_file() and not new_path.exists():
            new_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(old_path, new_path)
        elif old_path.is_file() and new_path.exists():
            conflicts.append(old_relative)
    for source_path in source.rglob("*"):
        relative = source_path.relative_to(source).as_posix()
        destination = vault / relative
        if source_path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif relative in managed:
            destination.parent.mkdir(parents=True, exist_ok=True)
            source_digest = file_hash(source_path)
            current_digest = file_hash(destination) if destination.is_file() else None
            legacy = managed[relative].get("legacy_hashes", [])
            if (
                current_digest is None
                or current_digest == source_digest
                or current_digest in legacy
                or current_digest == previous_files.get(relative)
            ):
                if current_digest != source_digest:
                    shutil.copy2(source_path, destination)
                    touched.append(destination)
                next_files[relative] = source_digest
            else:
                conflicts.append(relative)
        elif not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)
            touched.append(destination)
    for relative in ("AGENTS.md", "90-个人系统/Agent协作角色.md"):
        destination = vault / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, destination)
        if destination not in touched:
            touched.append(destination)
    (vault / ".obsidian").mkdir(exist_ok=True)
    atomic_write_json(
        state_path,
        {
            "schema_version": "1.0",
            "template_version": load_json(PLUGIN_MANIFEST)["version"],
            "files": next_files,
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
    )
    if state_path not in touched:
        touched.append(state_path)
    return touched, conflicts

def copy_runtime(
    codex: Path,
    vault: Path,
    config_path: Path | None = None,
    render_codex: Path | None = None,
    render_config: Path | None = None,
) -> tuple[Path, list[Path], list[str]]:
    rendered_codex = render_codex or codex
    rendered_config = render_config or config_path or default_local_config()
    source = RUNTIME / "codex"
    for name in ("agents", "contexts", "agent-system", "hooks"):
        shutil.copytree(source / name, codex / name, dirs_exist_ok=True)
    reserved = codex / "agents/xiaoh.toml"
    if reserved.exists():
        reserved.unlink()
    vault_files, vault_conflicts = sync_vault_runtime(vault)

    incoming = (source / "AGENTS.md").read_text(encoding="utf-8")
    override = codex / "AGENTS.override.md"
    target_agents = override if override.exists() and override.read_text(encoding="utf-8").strip() else codex / "AGENTS.md"
    merged = target_agents.read_text(encoding="utf-8") if target_agents.exists() else ""
    for marker in ("codebase-memory-mcp", "global-agent-common-contract"):
        merged = merge_marked_block(merged, incoming, marker)
    atomic_write_text(target_agents, merged.rstrip() + "\n")

    codex_config_path = codex / "config.toml"
    config = codex_config_path.read_text(encoding="utf-8") if codex_config_path.exists() else ""
    config = update_agents_section(config)
    hook = (source / "root-agent-hook.toml").read_text(encoding="utf-8")
    hook = hook.replace("__CODEX_HOME__", rendered_codex.as_posix())
    hook = hook.replace("__PYTHON_WINDOWS__", Path(sys.executable).resolve().as_posix())
    hook = hook.replace(
        "__XIAOH_CONFIG__",
        rendered_config.expanduser().resolve().as_posix(),
    )
    config = merge_config_block(config, hook, "xiaoh-root-agent-hook")
    atomic_write_text(codex_config_path, config.rstrip() + "\n")
    return target_agents, vault_files, vault_conflicts

def refresh_templates(codex: Path) -> None:
    template = codex / "agent-system/task-context.template.json"
    run_record = codex / "agent-system/run-record.template.json"
    context = load_json(template)
    context["freshness"]["checked_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    atomic_write_json(template, context)
    record = load_json(run_record)
    record["context_hash"] = (
        canonical_json_hash(context)
        if context.get("schema_version") == "1.6"
        else hashlib.sha256(template.read_bytes()).hexdigest()
    )
    atomic_write_json(run_record, record)
