#!/usr/bin/env python3
"""Thin Codex Hook entrypoint for XiaoH's delegation gate."""

import argparse
import json
import os
from pathlib import Path
import sys


AGENT_SYSTEM = Path(__file__).resolve().parent.parent / "agent-system"
if str(AGENT_SYSTEM) not in sys.path:
    sys.path.insert(0, str(AGENT_SYSTEM))

from xiaoh_security.delegation import DelegationGate, deny, self_test  # noqa: E402


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--subagent-start", action="store_true")
    parser.add_argument("--subagent-stop", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("agent delegation hook self-test passed")
        return 0
    try:
        payload = json.load(sys.stdin)
    except (TypeError, json.JSONDecodeError):
        payload = None
    codex_home = Path(
        os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))
    ).expanduser()
    if not isinstance(payload, dict):
        if args.subagent_start:
            result = {
                "hookSpecificOutput": {
                    "hookEventName": "SubagentStart",
                    "additionalContext": "未授权的 XiaoH 子 Agent。",
                },
                "systemMessage": "Hook 输入不是有效 JSON",
            }
        else:
            result = deny("Hook 输入不是有效 JSON")
    else:
        gate = DelegationGate(codex_home)
        try:
            if args.prepare:
                result = gate.prepare(payload)
            elif args.subagent_start:
                result = gate.start(payload)
            elif args.subagent_stop:
                result = gate.stop(payload) or {}
            else:
                result = gate.pretool_decision(payload) or {}
        except Exception as exc:
            result = deny("委派门禁失败：{}".format(exc))
    json.dump(result, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
