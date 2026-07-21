#!/usr/bin/env python3
"""Verify the effective XiaoH Agent gate through Codex app-server hooks/list."""

from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path


def command_for(executable: str) -> list[str]:
    if os.name == "nt" and Path(executable).suffix.casefold() in {".cmd", ".bat"}:
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", executable, "app-server", "--listen", "stdio://"]
    return [executable, "app-server", "--listen", "stdio://"]


def read_messages(stream, output: queue.Queue) -> None:
    for line in stream:
        try:
            output.put(json.loads(line))
        except json.JSONDecodeError:
            continue


def wait_for(output: queue.Queue, request_id: int) -> dict:
    while True:
        message = output.get(timeout=15)
        if message.get("id") == request_id:
            if "error" in message:
                raise RuntimeError(str(message["error"]))
            return message["result"]


def send(process: subprocess.Popen, message: dict) -> None:
    process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
    process.stdin.flush()


def verify(codex_home: Path, cwd: Path) -> None:
    executable = shutil.which("codex")
    if not executable:
        raise RuntimeError("未找到 codex 命令，无法读取实际 Hook 运行时状态")
    process = subprocess.Popen(
        command_for(executable),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
    )
    output: queue.Queue = queue.Queue()
    threading.Thread(target=read_messages, args=(process.stdout, output), daemon=True).start()
    try:
        send(process, {
            "method": "initialize", "id": 0,
            "params": {"clientInfo": {"name": "xiaoh_gate_verifier", "title": "XiaoH Gate Verifier", "version": "1.0.0"}},
        })
        initialized = wait_for(output, 0)
        if Path(initialized["codexHome"]).resolve() != codex_home.resolve():
            raise RuntimeError("Codex 实际 CODEX_HOME 与验收目标不一致")
        send(process, {"method": "initialized", "params": {}})
        send(process, {"method": "hooks/list", "id": 1, "params": {"cwds": [str(cwd.resolve())]}})
        result = wait_for(output, 1)
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()

    expected_source = (codex_home / "config.toml").resolve()
    script_paths = [
        codex_home / "hooks/block_reserved_root_agent.py",
        codex_home / "hooks/block_reserved_root_agent.ps1",
    ]
    expected_scripts = {
        candidate.replace("\\", "/").casefold()
        for path in script_paths
        for candidate in (str(path), str(path.resolve()))
    }
    hooks = [hook for item in result.get("data", []) for hook in item.get("hooks", [])]
    required = [
        ("PreToolUse", {"preToolUse", "pre_tool_use"}, "^(Agent|spawn_agent)$", ()),
        ("SubagentStart", {"subagentStart", "subagent_start"}, ".*", ("--subagent-start", "-subagentstart")),
        ("SubagentStop", {"subagentStop", "subagent_stop"}, ".*", ("--subagent-stop", "-subagentstop")),
    ]
    hashes = []
    for label, event_names, matcher, command_flags in required:
        matches = [
            hook for hook in hooks
            if hook.get("matcher") == matcher
            and hook.get("eventName") in event_names
            and Path(hook.get("sourcePath", "")).resolve() == expected_source
            and any(script in hook.get("command", "").replace("\\", "/").casefold() for script in expected_scripts)
            and (not command_flags or any(flag in hook.get("command", "").casefold() for flag in command_flags))
        ]
        if len(matches) != 1:
            raise RuntimeError(f"Codex hooks/list 未发现唯一的小H {label} 门禁")
        hook = matches[0]
        if hook.get("enabled") is not True:
            raise RuntimeError(f"小H {label} 门禁已被禁用")
        if hook.get("trustStatus") != "trusted":
            raise RuntimeError(f"小H {label} 门禁尚未信任，当前状态：{hook.get('trustStatus')}")
        if not hook.get("currentHash"):
            raise RuntimeError(f"Codex hooks/list 未返回 {label} 当前哈希")
        hashes.append(f"{label}={hook['currentHash']}")
    print("Agent 委派运行时门禁已激活：" + ", ".join(hashes))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex-home", type=Path, required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    args = parser.parse_args()
    try:
        verify(args.codex_home, args.cwd)
    except (RuntimeError, KeyError, OSError, queue.Empty) as exc:
        print(f"运行时门禁验收失败：{exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
