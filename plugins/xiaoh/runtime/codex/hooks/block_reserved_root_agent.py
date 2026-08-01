#!/usr/bin/env python3
"""Fail-closed one-time delegation gate for XiaoH specialist Agents."""

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "xiaoh-delegation-binding/v1"
PROOF_SCHEMA = "xiaoh-delegation-proof/v1.3"
RESERVED = {"xiaoh", "小h"}
RECEIPT_RE = re.compile(r"xiaoh-delegation-receipt:\s*([0-9a-f]{64})")
HEADER_RE = re.compile(r"^(task_id|task_context|authority_hash|delegated_agent):\s*(.+)$", re.M)


def digest_bytes(value):
    return hashlib.sha256(value).hexdigest()


def canonical_hash(value):
    return digest_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())


def normalize(value):
    return "".join(ch for ch in str(value).casefold() if ch.isalnum())


def deny(reason):
    return {"decision": "block", "reason": reason}


def parse_headers(message):
    found = {}
    for key, value in HEADER_RE.findall(message or ""):
        if key in found:
            raise ValueError("duplicate delegation header: {}".format(key))
        found[key] = value.strip()
    missing = {"task_id", "task_context", "authority_hash", "delegated_agent"} - set(found)
    if missing:
        raise ValueError("missing delegation headers: {}".format(", ".join(sorted(missing))))
    return found


def load_context(headers, home, run_validator=True):
    path = Path(headers["task_context"]).expanduser().resolve()
    if not path.is_file():
        raise ValueError("task context does not exist")
    context = json.loads(path.read_text(encoding="utf-8"))
    if context.get("schema_version") != "1.6" or context.get("task_id") != headers["task_id"]:
        raise ValueError("task context identity is invalid")
    if canonical_hash(context) != headers["authority_hash"]:
        raise ValueError("authority hash does not match task context")
    if run_validator:
        completed = subprocess.run([sys.executable, str(home / "agent-system/validate.py"), "--task-context", str(path)], capture_output=True, text=True, timeout=20)
        if completed.returncode:
            raise ValueError("task context validation failed")
    return path, context


def policy_for(context, agent):
    if agent not in context.get("routing", {}).get("delegated_agents", []):
        raise ValueError("Agent is not delegated by task context")
    policy = context.get("routing", {}).get("delegation_policies", {}).get(agent)
    if not isinstance(policy, dict) or policy.get("agent_type") != agent:
        raise ValueError("Agent delegation policy is invalid")
    return policy


def binding_dir(home):
    path = home / "agent-system/delegation-bindings"
    path.mkdir(parents=True, exist_ok=True)
    return path


def proof_dir(home):
    path = home / "agent-system/delegation-proofs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def prepare(payload, home, run_validator=True):
    tool = payload.get("tool_input")
    if not isinstance(tool, dict):
        raise ValueError("tool_input is required")
    agent = tool.get("agent_type")
    if not isinstance(agent, str) or not agent:
        raise ValueError("agent_type is required")
    if normalize(agent) in {normalize(item) for item in RESERVED}:
        raise ValueError("xiaoh is the reserved root identity")
    headers = parse_headers(tool.get("message"))
    if headers["delegated_agent"] != agent:
        raise ValueError("delegated_agent must match agent_type")
    context_path, context = load_context(headers, home, run_validator)
    policy = policy_for(context, agent)
    nonce = secrets.token_hex(16)
    round_number = int(payload.get("binding", {}).get("round", 1))
    if round_number < 1:
        raise ValueError("delegation round must be positive")
    prefix = policy.get("task_name_prefix")
    if not isinstance(prefix, str) or not prefix:
        raise ValueError("task_name_prefix is required")
    task_name = "{}__r{}__{}".format(prefix, round_number, nonce[:12])
    binding = {"schema_version": SCHEMA, "task_id": headers["task_id"], "task_context": str(context_path), "authority_hash": headers["authority_hash"], "delegated_agent": agent, "action": policy.get("action"), "task_name": task_name, "created_at": datetime.now(timezone.utc).isoformat(), "nonce": nonce, "parent_session_id": os.environ.get("CODEX_THREAD_ID", "unknown")}
    binding["binding_hash"] = canonical_hash(binding)
    path = binding_dir(home) / (nonce + ".json")
    path.write_text(json.dumps(binding, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prepared = dict(tool)
    prepared["task_name"] = task_name
    prepared["message"] = tool["message"].rstrip() + "\nexecution_binding: {}\nbinding_hash: {}\n".format(path, digest_bytes(path.read_bytes()))
    return {"execution_binding": str(path), "binding_hash": digest_bytes(path.read_bytes()), "tool_input": prepared}


def validate_binding(path, expected_hash, agent, home):
    path = Path(path).expanduser().resolve()
    if not path.is_file() or digest_bytes(path.read_bytes()) != expected_hash:
        raise ValueError("execution binding is missing or changed")
    binding = json.loads(path.read_text(encoding="utf-8"))
    stored = binding.pop("binding_hash", None)
    if stored != canonical_hash(binding):
        raise ValueError("execution binding integrity check failed")
    binding["binding_hash"] = stored
    if binding.get("schema_version") != SCHEMA or binding.get("delegated_agent") != agent:
        raise ValueError("execution binding identity is invalid")
    headers = {key: binding[key] for key in ("task_id", "task_context", "authority_hash", "delegated_agent")}
    _, context = load_context(headers, home, True)
    policy_for(context, agent)
    return path, binding


def pretool_decision(payload, home):
    tool = payload.get("tool_input", {})
    agent = tool.get("agent_type") or tool.get("subagent_type") or tool.get("task_name")
    if normalize(agent) in {normalize(item) for item in RESERVED}:
        return deny("拒绝委派：xiaoh 是根线程保留身份。")
    message = tool.get("message", "")
    match_path = re.search(r"^execution_binding:\s*(.+)$", message, re.M)
    match_hash = re.search(r"^binding_hash:\s*([0-9a-f]{64})$", message, re.M)
    if not match_path or not match_hash or not isinstance(agent, str):
        return deny("拒绝委派：缺少已准备的一次性执行绑定。")
    try:
        _, binding = validate_binding(match_path.group(1).strip(), match_hash.group(1), agent, home)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return deny("拒绝委派：{}。".format(exc))
    if tool.get("task_name") != binding["task_name"]:
        return deny("拒绝委派：task_name 与执行绑定不一致。")
    return None


def start(payload, home):
    agent = payload.get("agent_type")
    if not isinstance(agent, str):
        return {"hookSpecificOutput": {"additionalContext": "未授权的 XiaoH 子 Agent。"}, "systemMessage": "缺少 agent_type"}
    candidates = []
    for path in binding_dir(home).glob("*.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if value.get("delegated_agent") == agent:
            candidates.append((path.stat().st_mtime, path, value))
    if not candidates:
        return {"hookSpecificOutput": {"additionalContext": "未授权的 XiaoH 子 Agent。"}, "systemMessage": "没有可消费的委派绑定"}
    _, path, binding = max(candidates)
    claimed = path.with_suffix(".claimed")
    os.replace(path, claimed)
    agent_id = str(payload.get("agent_id", ""))
    receipt = secrets.token_hex(32)
    proof = {"schema_version": PROOF_SCHEMA, "source": "subagent-start-stop", "state": "started", "task_id": binding["task_id"], "agent": agent, "agent_id": agent_id, "authority_hash": binding["authority_hash"], "task_name": binding["task_name"], "binding_path": str(claimed), "binding_hash": digest_bytes(claimed.read_bytes()), "receipt_hash": digest_bytes(receipt.encode()), "started_at": datetime.now(timezone.utc).isoformat()}
    proof_path = proof_dir(home) / (digest_bytes(agent_id.encode()) + ".json")
    if proof_path.exists():
        return {"hookSpecificOutput": {"additionalContext": "未授权的 XiaoH 子 Agent。"}, "systemMessage": "Agent 身份已绑定"}
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    context = "权威 XiaoH 委派：task_id={}; action={}; task_context={}. 完成时原样输出：\nxiaoh-delegation-receipt: {}".format(binding["task_id"], binding["action"], binding["task_context"], receipt)
    return {"hookSpecificOutput": {"additionalContext": context}}


def stop(payload, home):
    agent_id = str(payload.get("agent_id", ""))
    proof_path = proof_dir(home) / (digest_bytes(agent_id.encode()) + ".json")
    if not proof_path.is_file():
        return {"decision": "block", "reason": "缺少 XiaoH 委派证明"}
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    matches = RECEIPT_RE.findall(payload.get("last_assistant_message", ""))
    if len(matches) != 1 or digest_bytes(matches[0].encode()) != proof.get("receipt_hash"):
        return {"decision": "block", "reason": "缺少或错误的 XiaoH 委派回执"}
    transcript = Path(str(payload.get("agent_transcript_path", ""))).expanduser().resolve()
    if not transcript.is_file():
        return {"decision": "block", "reason": "委派转录不存在"}
    proof.update({"state": "attested", "agent_transcript_path": str(transcript), "agent_transcript_hash": digest_bytes(transcript.read_bytes()), "attested_at": datetime.now(timezone.utc).isoformat()})
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return None


def self_test():
    assert normalize("小-H") == normalize("小h")
    assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})
    assert deny("x")["decision"] == "block"
    print("agent delegation hook self-test passed")


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--subagent-start", action="store_true")
    parser.add_argument("--subagent-stop", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test(); return
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = None
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
    if not isinstance(payload, dict):
        result = {"hookSpecificOutput": {"additionalContext": "未授权的 XiaoH 子 Agent。"}, "systemMessage": "Hook 输入不是有效 JSON"} if args.subagent_start else deny("Hook 输入不是有效 JSON")
        json.dump(result, sys.stdout, ensure_ascii=False); return
    try:
        if args.prepare:
            result = prepare(payload, home)
        elif args.subagent_start:
            result = start(payload, home)
        elif args.subagent_stop:
            result = stop(payload, home) or {}
        else:
            result = pretool_decision(payload, home) or {}
    except Exception as exc:
        result = deny("委派门禁失败：{}".format(exc))
    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
