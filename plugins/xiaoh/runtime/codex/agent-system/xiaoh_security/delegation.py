"""Fail-closed, one-time delegation binding and attestation service."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys


BINDING_SCHEMA = "xiaoh-delegation-binding/v2"
PROOF_SCHEMA = "xiaoh-delegation-proof/v2"
MAX_BINDING_AGE_SECONDS = 900
RESERVED_IDENTITIES = {"xiaoh", "小h"}
RECEIPT_RE = re.compile(r"xiaoh-delegation-receipt:\s*([0-9a-f]{64})")
HEADER_RE = re.compile(
    r"^(task_id|task_context|authority_hash|delegated_agent):\s*(.+)$", re.M
)


def digest_bytes(value):
    return hashlib.sha256(value).hexdigest()


def canonical_hash(value):
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return digest_bytes(encoded)


def normalize(value):
    return "".join(character for character in str(value).casefold() if character.isalnum())


def deny(reason):
    return {"decision": "block", "reason": reason}


def _atomic_json(path, value, exclusive=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if exclusive:
        descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        return
    temporary = path.with_name(".{}.{}.tmp".format(path.name, secrets.token_hex(8)))
    try:
        descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


class DelegationGate:
    """Own the complete delegation binding lifecycle behind thin Hook entrypoints."""

    def __init__(self, codex_home, run_validator=True, now=None):
        self.codex_home = Path(codex_home).expanduser().resolve(strict=False)
        self.run_validator = run_validator
        self._now = now or (lambda: datetime.now(timezone.utc))

    @property
    def binding_directory(self):
        return self.codex_home / "agent-system/delegation-bindings"

    @property
    def proof_directory(self):
        return self.codex_home / "agent-system/delegation-proofs"

    def prepare(self, payload):
        tool = payload.get("tool_input")
        if not isinstance(tool, dict):
            raise ValueError("tool_input is required")
        agent = tool.get("agent_type")
        if not isinstance(agent, str) or not agent.strip():
            raise ValueError("agent_type is required")
        self._reject_reserved(agent)
        headers = self._parse_headers(tool.get("message"))
        if headers["delegated_agent"] != agent:
            raise ValueError("delegated_agent must match agent_type")
        context_path, context = self._load_context(headers)
        policy = self._policy_for(context, agent)
        round_number = int(payload.get("binding", {}).get("round", 1))
        if round_number < 1:
            raise ValueError("delegation round must be positive")
        prefix = policy.get("task_name_prefix")
        if not isinstance(prefix, str) or not prefix.strip():
            raise ValueError("task_name_prefix is required")
        nonce = secrets.token_hex(16)
        task_name = "{}__r{}__{}".format(prefix, round_number, nonce[:12])
        created_at = self._now()
        binding = {
            "schema_version": BINDING_SCHEMA,
            "task_id": headers["task_id"],
            "task_context": str(context_path),
            "authority_hash": headers["authority_hash"],
            "delegated_agent": agent,
            "action": policy.get("action"),
            "allowed_paths": policy.get("allowed_paths", []),
            "read_only": policy.get("read_only", True),
            "task_name": task_name,
            "created_at": created_at.isoformat(),
            "expires_at": (created_at + timedelta(seconds=MAX_BINDING_AGE_SECONDS)).isoformat(),
            "nonce": nonce,
            "parent_session_id": os.environ.get("CODEX_THREAD_ID", "unknown"),
        }
        binding["binding_hash"] = canonical_hash(binding)
        path = self.binding_directory / (nonce + ".json")
        _atomic_json(path, binding, exclusive=True)
        file_hash = digest_bytes(path.read_bytes())
        prepared = dict(tool)
        prepared["task_name"] = task_name
        prepared["message"] = tool["message"].rstrip() + (
            "\nexecution_binding: {}\nbinding_hash: {}\n".format(path, file_hash)
        )
        return {
            "execution_binding": str(path),
            "binding_hash": file_hash,
            "tool_input": prepared,
        }

    def pretool_decision(self, payload):
        tool = payload.get("tool_input", {})
        if not isinstance(tool, dict):
            return deny("拒绝委派：tool_input 无效。")
        agent = tool.get("agent_type") or tool.get("subagent_type")
        try:
            self._reject_reserved(agent)
        except ValueError as exc:
            return deny("拒绝委派：{}。".format(exc))
        message = tool.get("message", "")
        path_match = re.search(r"^execution_binding:\s*(.+)$", message, re.M)
        hash_match = re.search(r"^binding_hash:\s*([0-9a-f]{64})$", message, re.M)
        if not path_match or not hash_match or not isinstance(agent, str):
            return deny("拒绝委派：缺少已准备的一次性执行绑定。")
        try:
            _, binding = self._validate_binding(
                path_match.group(1).strip(), hash_match.group(1), agent
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            return deny("拒绝委派：{}。".format(exc))
        if tool.get("task_name") != binding["task_name"]:
            return deny("拒绝委派：task_name 与执行绑定不一致。")
        return None

    def start(self, payload):
        agent = payload.get("agent_type")
        task_name = payload.get("task_name")
        agent_id = str(payload.get("agent_id", "")).strip()
        if not all(isinstance(value, str) and value.strip() for value in (agent, task_name, agent_id)):
            return self._start_denied("缺少 agent_type、task_name 或 agent_id")
        try:
            self._reject_reserved(agent)
            path = self._binding_for_task_name(task_name)
            binding = self._read_and_validate_internal_binding(path, agent)
            if binding.get("task_name") != task_name:
                raise ValueError("task_name 与执行绑定不一致")
            proof_path = self._proof_path(agent_id)
            if proof_path.exists():
                raise ValueError("Agent 身份已绑定")
            claimed = path.with_suffix(".claimed")
            if claimed.exists():
                raise ValueError("执行绑定已消费")
            os.replace(str(path), str(claimed))
            receipt = secrets.token_hex(32)
            proof = {
                "schema_version": PROOF_SCHEMA,
                "source": "subagent-start-stop",
                "state": "started",
                "task_id": binding["task_id"],
                "agent": agent,
                "agent_id": agent_id,
                "authority_hash": binding["authority_hash"],
                "task_name": task_name,
                "binding_path": str(claimed),
                "binding_hash": digest_bytes(claimed.read_bytes()),
                "effective_brief": {
                    "task_id": binding["task_id"],
                    "authority_hash": binding["authority_hash"],
                    "delegated_agent": agent,
                    "action": binding["action"],
                    "allowed_paths": binding["allowed_paths"],
                    "read_only": binding["read_only"],
                    "task_name": task_name,
                    "binding_hash": binding["binding_hash"],
                    "purpose": "execution",
                },
                "receipt_hash": digest_bytes(receipt.encode("utf-8")),
                "started_at": self._now().isoformat(),
            }
            _atomic_json(proof_path, proof, exclusive=True)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            return self._start_denied(str(exc))
        context = (
            "权威 XiaoH 委派：task_id={}; action={}; task_context={}; read_only={}; allowed_paths={}. "
            "完成时原样输出：\nxiaoh-delegation-receipt: {}"
        ).format(
            binding["task_id"], binding["action"], binding["task_context"],
            binding["read_only"], json.dumps(binding["allowed_paths"], ensure_ascii=False), receipt,
        )
        return {
            "hookSpecificOutput": {
                "hookEventName": "SubagentStart",
                "additionalContext": context,
            }
        }

    def stop(self, payload):
        agent_id = str(payload.get("agent_id", "")).strip()
        if not agent_id:
            return deny("缺少 XiaoH 委派 Agent 身份")
        proof_path = self._proof_path(agent_id)
        if not proof_path.is_file():
            return deny("缺少 XiaoH 委派证明")
        try:
            proof = json.loads(proof_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return deny("XiaoH 委派证明不可读")
        if proof.get("schema_version") != PROOF_SCHEMA or proof.get("state") != "started":
            return deny("XiaoH 委派证明状态无效")
        matches = RECEIPT_RE.findall(str(payload.get("last_assistant_message", "")))
        if len(matches) != 1 or digest_bytes(matches[0].encode("utf-8")) != proof.get("receipt_hash"):
            return deny("缺少或错误的 XiaoH 委派回执")
        transcript = Path(str(payload.get("agent_transcript_path", ""))).expanduser().resolve(strict=False)
        if not transcript.is_file():
            return deny("委派转录不存在")
        proof.update(
            {
                "state": "attested",
                "attested": True,
                "transcript_path": str(transcript),
                "transcript_hash": digest_bytes(transcript.read_bytes()),
                "attested_at": self._now().isoformat(),
            }
        )
        _atomic_json(proof_path, proof)
        return None

    def _parse_headers(self, message):
        found = {}
        for key, value in HEADER_RE.findall(message or ""):
            if key in found:
                raise ValueError("duplicate delegation header: {}".format(key))
            found[key] = value.strip()
        missing = {"task_id", "task_context", "authority_hash", "delegated_agent"} - set(found)
        if missing:
            raise ValueError("missing delegation headers: {}".format(", ".join(sorted(missing))))
        return found

    def _load_context(self, headers):
        path = Path(headers["task_context"]).expanduser().resolve(strict=False)
        if not path.is_file():
            raise ValueError("task context does not exist")
        context = json.loads(path.read_text(encoding="utf-8"))
        if context.get("schema_version") != "1.6" or context.get("task_id") != headers["task_id"]:
            raise ValueError("task context identity is invalid")
        if canonical_hash(context) != headers["authority_hash"]:
            raise ValueError("authority hash does not match task context")
        if self.run_validator:
            command = [
                sys.executable,
                str(self.codex_home / "agent-system/validate.py"),
                "--task-context",
                str(path),
            ]
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=20, check=False
            )
            if completed.returncode:
                raise ValueError("task context validation failed")
        return path, context

    def _policy_for(self, context, agent):
        if agent not in context.get("routing", {}).get("delegated_agents", []):
            raise ValueError("Agent is not delegated by task context")
        policy = context.get("routing", {}).get("delegation_policies", {}).get(agent)
        if not isinstance(policy, dict) or policy.get("agent_type") != agent:
            raise ValueError("Agent delegation policy is invalid")
        if not isinstance(policy.get("action"), str) or not policy["action"]:
            raise ValueError("Agent delegation action is invalid")
        if not isinstance(policy.get("read_only"), bool):
            raise ValueError("Agent delegation read_only policy is invalid")
        if not isinstance(policy.get("allowed_paths"), list):
            raise ValueError("Agent delegation allowed_paths policy is invalid")
        return policy

    def _validate_binding(self, raw_path, expected_hash, agent):
        path = Path(raw_path).expanduser().resolve(strict=False)
        if path.parent != self.binding_directory.resolve(strict=False):
            raise ValueError("execution binding path is outside the managed directory")
        if not path.is_file() or digest_bytes(path.read_bytes()) != expected_hash:
            raise ValueError("execution binding is missing or changed")
        return path, self._read_and_validate_internal_binding(path, agent)

    def _read_and_validate_internal_binding(self, path, agent):
        binding = json.loads(path.read_text(encoding="utf-8"))
        stored_hash = binding.get("binding_hash")
        unhashed = dict(binding)
        unhashed.pop("binding_hash", None)
        if stored_hash != canonical_hash(unhashed):
            raise ValueError("execution binding integrity check failed")
        required = {
            "schema_version", "task_id", "task_context", "authority_hash",
            "delegated_agent", "action", "task_name", "created_at", "expires_at",
            "nonce", "parent_session_id", "allowed_paths", "read_only", "binding_hash",
        }
        if required - set(binding):
            raise ValueError("execution binding is incomplete")
        if binding["schema_version"] != BINDING_SCHEMA or binding["delegated_agent"] != agent:
            raise ValueError("execution binding identity is invalid")
        expires_at = datetime.fromisoformat(binding["expires_at"].replace("Z", "+00:00"))
        if expires_at.tzinfo is None or self._now() >= expires_at:
            raise ValueError("execution binding is expired")
        headers = {key: binding[key] for key in ("task_id", "task_context", "authority_hash", "delegated_agent")}
        _, context = self._load_context(headers)
        policy = self._policy_for(context, agent)
        if policy.get("action") != binding["action"]:
            raise ValueError("delegation action drifted")
        if policy.get("allowed_paths") != binding["allowed_paths"] or policy.get("read_only") != binding["read_only"]:
            raise ValueError("delegation scope drifted")
        prefix = policy.get("task_name_prefix")
        pattern = re.escape(str(prefix)) + r"__r[1-9][0-9]*__[0-9a-f]{12}"
        if not re.fullmatch(pattern, binding["task_name"]):
            raise ValueError("task_name is outside its authorized namespace")
        return binding

    def _binding_for_task_name(self, task_name):
        matches = []
        if self.binding_directory.is_dir():
            for path in self.binding_directory.glob("*.json"):
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if value.get("task_name") == task_name:
                    matches.append(path)
        if len(matches) != 1:
            raise ValueError("没有唯一可消费的 task_name 委派绑定")
        return matches[0]

    def _proof_path(self, agent_id):
        return self.proof_directory / (digest_bytes(agent_id.encode("utf-8")) + ".json")

    @staticmethod
    def _reject_reserved(agent):
        if normalize(agent) in {normalize(item) for item in RESERVED_IDENTITIES}:
            raise ValueError("xiaoh is the reserved root identity")

    @staticmethod
    def _start_denied(reason):
        return {
            "hookSpecificOutput": {
                "hookEventName": "SubagentStart",
                "additionalContext": "未授权的 XiaoH 子 Agent。",
            },
            "systemMessage": reason,
        }


def self_test():
    assert normalize("小-H") == normalize("小h")
    assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})
    assert deny("x")["decision"] == "block"
