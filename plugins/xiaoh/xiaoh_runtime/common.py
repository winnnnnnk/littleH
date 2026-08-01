#!/usr/bin/env python3
"""Install, update, and diagnose the XiaoH local runtime."""

from __future__ import annotations

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

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import platform
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.9 and 3.10
    tomllib = None

if os.name == "nt":
    import msvcrt
else:
    import fcntl


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
RUNTIME = PLUGIN_ROOT / "runtime"
PLUGIN_MANIFEST = PLUGIN_ROOT / ".codex-plugin/plugin.json"
DEPENDENCY_MANIFEST = PLUGIN_ROOT / "dependencies.json"
AUTOMATION_MANIFEST = PLUGIN_ROOT / "managed-automations.json"
VAULT_MANIFEST = RUNTIME / "obsidian/managed-vault-files.json"
REQUIRED_AGENTS = {
    "frontend_implementer",
    "java_architect",
    "java_code_explorer",
    "java_implementer",
    "pki_domain_expert",
}
TEXT_EXTENSIONS = {".md", ".toml", ".json", ".py", ".js", ".yaml", ".yml", ".txt"}
PLAYBOOK_VERSION_POLICY_FRAGMENTS = (
    "## Playbook CLI版本维护边界",
    "只允许用户人工执行",
    "`playbook --version`",
    "`playbook version check`",
    "`playbook version update`",
    "`npm link`",
    "“继续”“自动推进”或同类授权不包含Playbook版本变更权限",
    "不安装命令级机械门禁",
)

class UpgradeRolledBack(RuntimeError):
    def __init__(
        self,
        journal_path: Path,
        message: str,
        actual_writes: list[str] | None = None,
    ):
        super().__init__(message)
        self.journal_path = journal_path
        self.actual_writes = actual_writes or []

class UpgradeMutationError(RuntimeError):
    def __init__(
        self,
        journal_path: Path,
        message: str,
        actual_writes: list[str],
    ):
        super().__init__(message)
        self.journal_path = journal_path
        self.actual_writes = actual_writes

def default_local_config() -> Path:
    configured = os.environ.get("XIAOH_CONFIG")
    return Path(configured).expanduser() if configured else Path.home() / ".xiaoh/config.json"

def load_json(path: Path, default: dict | None = None) -> dict:
    if not path.exists() and default is not None:
        return default
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"{path} 必须包含 JSON 对象")
    return value

def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()

def canonical_json_hash(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validated_descendant(root: Path, relative: Path | str, label: str) -> Path:
    """Return a root-contained path with no symlinked managed components."""
    root = Path(root).expanduser()
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{label}不得逃逸受管根目录: {relative}")
    candidate = root / relative
    root_resolved = root.resolve(strict=False)
    candidate_resolved = candidate.resolve(strict=False)
    try:
        candidate_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"{label}不得逃逸受管根目录: {candidate}") from exc
    current = root
    for part in relative.parts:
        if current.is_symlink():
            raise ValueError(f"{label}路径不允许包含符号链接: {current}")
        current = current / part
    if current.is_symlink():
        raise ValueError(f"{label}路径不允许包含符号链接: {current}")
    return candidate


def backup_item(source: Path, destination: Path) -> None:
    """Copy an existing file or directory into its requested backup location."""
    if not source.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True)
    else:
        shutil.copy2(source, destination)


def atomic_write_text(path: Path, text: str, backup: Path | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.exists():
        backup_item(path, backup)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            temporary.chmod(path.stat().st_mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)

def atomic_write_json(path: Path, value: dict, backup: Path | None = None) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n", backup)

@contextmanager
def config_lock(config_path: Path):
    """Serialize XiaoH config read-modify-write operations across processes."""
    lock_path = config_path.with_suffix(config_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
