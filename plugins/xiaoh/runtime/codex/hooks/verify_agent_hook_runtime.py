#!/usr/bin/env python3
"""Verify the effective XiaoH Agent gate through Codex app-server hooks/list."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


RUNTIME_PROBE_ATTEMPTS = 3
RUNTIME_RESPONSE_TIMEOUT_SECONDS = 15
RUNTIME_PROBE_LOCK_TIMEOUT_SECONDS = 60


class RuntimeProbeTimeout(RuntimeError):
    """The app-server did not answer a runtime probe request in time."""


def runtime_probe_lock_path(codex_home: Path) -> Path:
    identity = hashlib.sha256(
        str(codex_home.resolve()).encode("utf-8")
    ).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / "xiaoh-runtime-probe-{}.lock".format(
        identity
    )


def try_lock(handle) -> bool:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def unlock(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def runtime_probe_lock(
    codex_home: Path,
    *,
    timeout_seconds: int = RUNTIME_PROBE_LOCK_TIMEOUT_SECONDS,
):
    lock_path = runtime_probe_lock_path(codex_home)
    with lock_path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + timeout_seconds
        while not try_lock(handle):
            if time.monotonic() >= deadline:
                raise RuntimeProbeTimeout(
                    "Codex app-server runtime probe lock remained busy for "
                    "{} seconds: {}".format(timeout_seconds, lock_path)
                )
            time.sleep(0.1)
        try:
            yield
        finally:
            unlock(handle)


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


def wait_for(output: queue.Queue, request_id: int, request_name: str) -> dict:
    while True:
        try:
            message = output.get(timeout=RUNTIME_RESPONSE_TIMEOUT_SECONDS)
        except queue.Empty as exc:
            raise RuntimeProbeTimeout(
                "Codex app-server {} request id={} timed out after {} seconds".format(
                    request_name,
                    request_id,
                    RUNTIME_RESPONSE_TIMEOUT_SECONDS,
                )
            ) from exc
        if message.get("id") == request_id:
            if "error" in message:
                raise RuntimeError(str(message["error"]))
            return message["result"]


def send(process: subprocess.Popen, message: dict) -> None:
    process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
    process.stdin.flush()


def query_hooks(executable: str, codex_home: Path, cwd: Path) -> dict:
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
        initialized = wait_for(output, 0, "initialize")
        if Path(initialized["codexHome"]).resolve() != codex_home.resolve():
            raise RuntimeError("Codex 实际 CODEX_HOME 与验收目标不一致")
        send(process, {"method": "initialized", "params": {}})
        send(process, {"method": "hooks/list", "id": 1, "params": {"cwds": [str(cwd.resolve())]}})
        return wait_for(output, 1, "hooks/list")
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()


def query_hooks_with_retry(
    executable: str,
    codex_home: Path,
    cwd: Path,
    *,
    attempts: int = RUNTIME_PROBE_ATTEMPTS,
) -> dict:
    failures = []
    for attempt in range(1, attempts + 1):
        try:
            return query_hooks(executable, codex_home, cwd)
        except RuntimeProbeTimeout as exc:
            failures.append("attempt {}/{}: {}".format(attempt, attempts, exc))
    raise RuntimeProbeTimeout(
        "Codex app-server runtime probe exhausted retries; {}".format(
            "; ".join(failures)
        )
    )


def verify(codex_home: Path, cwd: Path) -> None:
    if os.environ.get("CODEX_SANDBOX"):
        raise RuntimeError(
            "Codex app-server运行时验收不能在工具沙盒内执行；"
            "请批准doctor --runtime在非沙盒环境运行"
        )
    executable = shutil.which("codex")
    if not executable:
        raise RuntimeError("未找到 codex 命令，无法读取实际 Hook 运行时状态")
    with runtime_probe_lock(codex_home):
        result = query_hooks_with_retry(executable, codex_home, cwd)

    expected_source = (codex_home / "config.toml").resolve()
    delegation_scripts = [codex_home / "hooks/block_reserved_root_agent.py"]
    vault_scripts = [codex_home / "hooks/guard_vault_writes.py"]
    normalized_scripts = lambda paths: {
        candidate.replace("\\", "/").casefold()
        for path in paths
        for candidate in (str(path), str(path.resolve()))
    }
    hooks = [hook for item in result.get("data", []) for hook in item.get("hooks", [])]
    required = [
        ("Agent PreToolUse", {"preToolUse", "pre_tool_use"}, "^(Agent|spawn_agent)$", delegation_scripts, ()),
        ("Vault PreToolUse", {"preToolUse", "pre_tool_use"}, "^(apply_patch|exec_command)$", vault_scripts, ()),
        ("SubagentStart", {"subagentStart", "subagent_start"}, ".*", delegation_scripts, ("--subagent-start", "-subagentstart")),
        ("SubagentStop", {"subagentStop", "subagent_stop"}, ".*", delegation_scripts, ("--subagent-stop", "-subagentstop")),
    ]
    hashes = []
    for label, event_names, matcher, script_paths, command_flags in required:
        expected_scripts = normalized_scripts(script_paths)
        matches = [
            hook for hook in hooks
            if hook.get("matcher") == matcher
            and hook.get("eventName") in event_names
            and Path(hook.get("sourcePath", "")).resolve() == expected_source
            and any(script in hook.get("command", "").replace("\\", "/").casefold() for script in expected_scripts)
            and (not command_flags or any(flag in hook.get("command", "").casefold() for flag in command_flags))
        ]
        if len(matches) != 1:
            raise RuntimeError(f"Codex hooks/list 未发现唯一的xiaoh {label} 门禁")
        hook = matches[0]
        if hook.get("enabled") is not True:
            raise RuntimeError(f"xiaoh {label} 门禁已被禁用")
        if hook.get("trustStatus") != "trusted":
            raise RuntimeError(f"xiaoh {label} 门禁尚未信任，当前状态：{hook.get('trustStatus')}")
        if not hook.get("currentHash"):
            raise RuntimeError(f"Codex hooks/list 未返回 {label} 当前哈希")
        hashes.append(f"{label}={hook['currentHash']}")
    print("xiaoh运行时门禁已激活：" + ", ".join(hashes))


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
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
