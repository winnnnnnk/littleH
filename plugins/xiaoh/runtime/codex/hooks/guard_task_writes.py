#!/usr/bin/env python3
"""Thin Hook and CLI entrypoint for root-task scope and Vault write guards."""

import argparse
import json
import os
from pathlib import Path
import sys


AGENT_SYSTEM = Path(__file__).resolve().parent.parent / "agent-system"
if str(AGENT_SYSTEM) not in sys.path:
    sys.path.insert(0, str(AGENT_SYSTEM))

from xiaoh_security.execution import RootExecutionGate, self_test as execution_self_test  # noqa: E402
from xiaoh_security.vault_guard import VaultWriteGuard, deny  # noqa: E402


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--attest", action="store_true")
    parser.add_argument("--run-verification")
    parser.add_argument("--task-context")
    parser.add_argument("--session-id")
    parser.add_argument("--binding")
    parser.add_argument("--binding-hash")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    gate = RootExecutionGate(codex_home)
    if args.self_test:
        execution_self_test()
        print("根任务执行范围门禁自检通过。")
        return 0
    if args.prepare:
        if not args.task_context:
            parser.error("--prepare requires --task-context")
        print(json.dumps(gate.prepare(args.task_context, args.session_id), ensure_ascii=False))
        return 0
    if args.attest:
        if not args.binding or not args.binding_hash:
            parser.error("--attest requires --binding and --binding-hash")
        proof = gate.attest(args.binding, args.binding_hash)
        print(json.dumps(proof, ensure_ascii=False))
        return 0 if proof["status"] == "passed" else 1
    if args.run_verification:
        if not args.binding or not args.binding_hash:
            parser.error("--run-verification requires --binding and --binding-hash")
        evidence = gate.run_verification(
            args.binding, args.binding_hash, args.run_verification
        )
        print(json.dumps(evidence, ensure_ascii=False))
        return 0 if evidence["status"] == "passed" else 1
    config = Path(
        args.config or os.environ.get("XIAOH_CONFIG", str(Path.home() / ".xiaoh/config.json"))
    ).expanduser()
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            result = deny("根任务写入门禁输入结构无效。")
        else:
            result = gate.decision(payload)
            if result is None:
                result = VaultWriteGuard(config).decision(payload)
    except (json.JSONDecodeError, TypeError):
        result = deny("根任务写入门禁输入不是有效JSON。")
    except Exception as exc:
        result = deny("根任务写入门禁内部校验异常（{}）。".format(type(exc).__name__))
    if result is not None:
        json.dump(result, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
