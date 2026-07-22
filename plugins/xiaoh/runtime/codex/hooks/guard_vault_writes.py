#!/usr/bin/env python3
"""Deny XiaoH tool calls that target an unconfigured Obsidian vault."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable


PATH_PATTERN = re.compile(
    r"(?:[\"']((?:[A-Za-z]:[\\/]|/)[^\"']+)[\"'])"
    r"|(?:^|[\s=:])((?:[A-Za-z]:[\\/]|/)[^\s\"'`;,|&<>]+)",
    re.MULTILINE,
)
PATCH_PATH = re.compile(r"^\*\*\* (?:Add|Update|Delete) File:\s*(.+?)\s*$", re.MULTILINE)


def deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def config_path() -> Path:
    return Path(os.environ.get("XIAOH_CONFIG", str(Path.home() / ".xiaoh/config.json"))).expanduser()


def configured_vault() -> Path:
    path = config_path()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        raw = value["obsidian_vault"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取小H唯一Vault配置 {path}: {exc}") from exc
    vault = Path(raw).expanduser()
    if not vault.is_absolute():
        raise ValueError(f"小H Vault配置必须是绝对路径: {vault}")
    vault = vault.resolve()
    if not (vault.is_dir() and (vault / ".obsidian").is_dir()):
        raise ValueError(f"小H配置路径不是有效Obsidian Vault: {vault}")
    return vault


def strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def extracted_paths(text: str) -> Iterable[str]:
    stripped = text.strip()
    if stripped and "\n" not in stripped:
        candidate = Path(stripped.strip("\"'"))
        if candidate.is_absolute():
            yield str(candidate)
    yield from (match.group(1).strip() for match in PATCH_PATH.finditer(text))
    for match in PATH_PATTERN.finditer(text):
        yield (match.group(1) or match.group(2)).rstrip(")]}")


def is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def vault_root(path: Path) -> Path | None:
    probe = path if path.is_dir() else path.parent
    for candidate in (probe, *probe.parents):
        if (candidate / ".obsidian").is_dir():
            return candidate.resolve()
    return None


def check_path(raw: str, base: Path, allowed: Path) -> str | None:
    candidate = Path(raw).expanduser()
    if ".." in candidate.parts:
        return f"拒绝包含上级跳转的Vault路径: {raw}"
    if not candidate.is_absolute():
        candidate = base / candidate
    lexical_root = vault_root(candidate.absolute())
    resolved = candidate.resolve(strict=False)
    root = vault_root(resolved) or lexical_root
    if root is not None and root != allowed:
        return f"拒绝写入未配置的Obsidian Vault: {root}；唯一允许路径: {allowed}"
    if lexical_root == allowed and not is_within(resolved, allowed):
        return f"拒绝通过符号链接逃逸小H Vault: {candidate}"
    return None


def decision(payload: dict[str, Any]) -> dict[str, Any] | None:
    try:
        allowed = configured_vault()
    except ValueError as exc:
        return deny(f"知识库写入门禁不可用：{exc}")
    tool_input = payload.get("tool_input", {})
    base_raw = tool_input.get("workdir") if isinstance(tool_input, dict) else None
    base_raw = base_raw or payload.get("cwd") or os.getcwd()
    base = Path(base_raw).expanduser().resolve(strict=False)
    root = vault_root(base)
    if root is not None and root != allowed:
        return deny(f"拒绝在未配置的Obsidian Vault中执行工具: {root}；唯一允许路径: {allowed}")
    seen: set[str] = set()
    for value in strings(tool_input):
        for raw in extracted_paths(value):
            if raw in seen:
                continue
            seen.add(raw)
            reason = check_path(raw, base, allowed)
            if reason:
                return deny(reason)
    return None


def self_test() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        allowed = root / "development-vault"
        decoy = root / "todolist-vault"
        for vault in (allowed, decoy):
            (vault / ".obsidian").mkdir(parents=True)
        config = root / "config.json"
        config.write_text(json.dumps({"obsidian_vault": str(allowed)}), encoding="utf-8")
        previous = os.environ.get("XIAOH_CONFIG")
        os.environ["XIAOH_CONFIG"] = str(config)
        try:
            assert decision({"cwd": str(root), "tool_input": {"path": str(allowed / "ok.md")}}) is None
            assert decision({"cwd": str(root), "tool_input": {"cmd": f'echo x > "{decoy / "wrong.md"}"'}})
            assert decision({"cwd": str(decoy), "tool_input": {"cmd": "pwd"}})
            assert decision({"cwd": str(root), "tool_input": {"path": str(allowed / ".." / "escape.md")}})
            outside = root / "outside"
            outside.mkdir()
            link = allowed / "linked"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError:
                pass
            else:
                assert decision({"cwd": str(root), "tool_input": {"path": str(link / "escape.md")}})
            config.unlink()
            assert decision({"cwd": str(root), "tool_input": {"cmd": "pwd"}})
        finally:
            if previous is None:
                os.environ.pop("XIAOH_CONFIG", None)
            else:
                os.environ["XIAOH_CONFIG"] = previous
    print("Obsidian Vault写入门禁自检通过。")


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return
    try:
        payload = json.load(sys.stdin)
        result = decision(payload) if isinstance(payload, dict) else deny("知识库写入门禁输入结构无效。")
    except (json.JSONDecodeError, TypeError):
        result = deny("知识库写入门禁输入不是有效JSON。")
    except Exception as exc:
        result = deny(f"知识库写入门禁内部校验异常（{type(exc).__name__}）。")
    if result is not None:
        json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
