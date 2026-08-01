#!/usr/bin/env python3
"""Thin Codex Hook entrypoint for XiaoH's single-Vault write guard."""

import argparse
import json
import os
from pathlib import Path
import sys


AGENT_SYSTEM = Path(__file__).resolve().parent.parent / "agent-system"
if str(AGENT_SYSTEM) not in sys.path:
    sys.path.insert(0, str(AGENT_SYSTEM))

from xiaoh_security.vault_guard import VaultWriteGuard, deny, self_test  # noqa: E402


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("Obsidian Vault写入门禁自检通过。")
        return 0
    config = Path(
        args.config
        or os.environ.get("XIAOH_CONFIG", str(Path.home() / ".xiaoh/config.json"))
    ).expanduser()
    try:
        payload = json.load(sys.stdin)
        result = (
            VaultWriteGuard(config).decision(payload)
            if isinstance(payload, dict)
            else deny("知识库写入门禁输入结构无效。")
        )
    except (json.JSONDecodeError, TypeError):
        result = deny("知识库写入门禁输入不是有效JSON。")
    except Exception as exc:
        result = deny("知识库写入门禁内部校验异常（{}）。".format(type(exc).__name__))
    if result is not None:
        json.dump(result, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
