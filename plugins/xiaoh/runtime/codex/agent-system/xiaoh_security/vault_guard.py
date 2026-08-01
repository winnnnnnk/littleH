"""Fail-closed guard for XiaoH's single configured Obsidian Vault."""

import json
import os
from pathlib import Path
import re
import tempfile


PATH_PATTERN = re.compile(
    r"(?:[\"']((?:[A-Za-z]:[\\/]|/)[^\"']+)[\"'])"
    r"|(?:^|[\s=:])((?:[A-Za-z]:[\\/]|/)[^\s\"'`;,|&<>]+)",
    re.MULTILINE,
)
PATCH_PATH = re.compile(r"^\*\*\* (?:Add|Update|Delete) File:\s*(.+?)\s*$", re.MULTILINE)


def deny(reason):
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            for text in _strings(item):
                yield text
    elif isinstance(value, list):
        for item in value:
            for text in _strings(item):
                yield text


def _extracted_paths(text):
    stripped = text.strip()
    if stripped and "\n" not in stripped:
        candidate = Path(stripped.strip("\"'"))
        if candidate.is_absolute():
            yield str(candidate)
    for match in PATCH_PATH.finditer(text):
        yield match.group(1).strip()
    for match in PATH_PATTERN.finditer(text):
        yield (match.group(1) or match.group(2)).rstrip(")]}")


def _vault_root(path):
    probe = path if path.is_dir() else path.parent
    for candidate in (probe,) + tuple(probe.parents):
        if (candidate / ".obsidian").is_dir():
            return candidate.resolve()
    return None


def _is_within(path, root):
    return path == root or root in path.parents


class VaultWriteGuard:
    """Authorize only writes that cannot target or escape another Vault."""

    def __init__(self, config_path):
        self.config_path = Path(config_path).expanduser().resolve(strict=False)

    def configured_vault(self):
        try:
            value = json.loads(self.config_path.read_text(encoding="utf-8"))
            raw = value["obsidian_vault"]
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError(
                "无法读取xiaoh唯一Vault配置 {}: {}".format(self.config_path, exc)
            )
        vault = Path(raw).expanduser()
        if not vault.is_absolute():
            raise ValueError("xiaoh Vault配置必须是绝对路径: {}".format(vault))
        vault = vault.resolve(strict=False)
        if not (vault.is_dir() and (vault / ".obsidian").is_dir()):
            raise ValueError("xiaoh配置路径不是有效Obsidian Vault: {}".format(vault))
        return vault

    def decision(self, payload):
        try:
            allowed = self.configured_vault()
        except ValueError as exc:
            return deny("知识库写入门禁不可用：{}".format(exc))
        tool_input = payload.get("tool_input", {})
        base_raw = tool_input.get("workdir") if isinstance(tool_input, dict) else None
        base_raw = base_raw or payload.get("cwd") or os.getcwd()
        base = Path(base_raw).expanduser().resolve(strict=False)
        root = _vault_root(base)
        if root is not None and root != allowed:
            return deny(
                "拒绝在未配置的Obsidian Vault中执行工具: {}；唯一允许路径: {}".format(
                    root, allowed
                )
            )
        seen = set()
        for value in _strings(tool_input):
            for raw in _extracted_paths(value):
                if raw in seen:
                    continue
                seen.add(raw)
                reason = self._check_path(raw, base, allowed)
                if reason:
                    return deny(reason)
        return None

    @staticmethod
    def _check_path(raw, base, allowed):
        candidate = Path(raw).expanduser()
        if ".." in candidate.parts:
            return "拒绝包含上级跳转的Vault路径: {}".format(raw)
        if not candidate.is_absolute():
            candidate = base / candidate
        lexical_root = _vault_root(candidate.absolute())
        resolved = candidate.resolve(strict=False)
        root = _vault_root(resolved) or lexical_root
        if root is not None and root != allowed:
            return "拒绝写入未配置的Obsidian Vault: {}；唯一允许路径: {}".format(
                root, allowed
            )
        if lexical_root == allowed and not _is_within(resolved, allowed):
            return "拒绝通过符号链接逃逸xiaoh Vault: {}".format(candidate)
        return None


def self_test():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        allowed = root / "development-vault"
        decoy = root / "decoy-vault"
        for vault in (allowed, decoy):
            (vault / ".obsidian").mkdir(parents=True)
        config = root / "config.json"
        config.write_text(json.dumps({"obsidian_vault": str(allowed)}), encoding="utf-8")
        guard = VaultWriteGuard(config)
        assert guard.decision({"cwd": str(root), "tool_input": {"path": str(allowed / "ok.md")}}) is None
        assert guard.decision({"cwd": str(root), "tool_input": {"path": str(decoy / "wrong.md")}})
        assert guard.decision({"cwd": str(root), "tool_input": {"path": str(allowed / ".." / "escape.md")}})
