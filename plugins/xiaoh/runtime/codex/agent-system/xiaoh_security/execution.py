"""Short-lived root execution binding and repository scope attestation."""

from datetime import datetime, timedelta, timezone
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import sys

from xiaoh_validator.diagnostics import Report
from xiaoh_validator.schemas import (
    ROOT_EXECUTION_BINDING_SCHEMA,
    ROOT_SCOPE_PROOF_SCHEMA,
    VERIFICATION_EVIDENCE_SCHEMA,
)
from xiaoh_validator.task_context import validate_task_context


BINDING_SCHEMA = ROOT_EXECUTION_BINDING_SCHEMA
PROOF_SCHEMA = ROOT_SCOPE_PROOF_SCHEMA
MAX_BINDING_AGE_SECONDS = 3600
PATCH_PATH_RE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File:\s*(.+)$", re.M)
WRITE_TARGET_RE = re.compile(
    r"(?:^|[;&|]\s*)(?:touch|mkdir|rm)\s+(?:-[^\s]+\s+)*([^\s;&|]+)|(?:>>?|2>>?)\s*([^\s;&|]+)"
)
READ_ONLY_COMMANDS = {"pwd", "ls", "rg", "sed"}
READ_ONLY_GIT_COMMANDS = {"status", "diff", "log", "show"}


def _hash_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _canonical_hash(value):
    return _hash_bytes(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def _file_digest(path):
    path = Path(path)
    if not path.is_file():
        return "missing"
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(".{}.{}.tmp".format(path.name, secrets.token_hex(8)))
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


def _covered(path, roots):
    candidate = Path(path).expanduser().resolve(strict=False)
    resolved_roots = [Path(root).expanduser().resolve(strict=False) for root in roots]
    return any(candidate == root or root in candidate.parents for root in resolved_roots)


def _git_snapshot(repo):
    completed = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise ValueError("cannot read repository status: {}".format(repo))
    parts = completed.stdout.split(b"\0")
    snapshot = {}
    index = 0
    while index < len(parts):
        raw = parts[index]
        index += 1
        if not raw:
            continue
        text = raw.decode("utf-8", errors="surrogateescape")
        if len(text) < 4:
            raise ValueError("invalid git status entry")
        status = text[:2]
        relative = text[3:]
        if status[:1] in {"R", "C"} or status[1:2] in {"R", "C"}:
            index += 1
        absolute = (repo / relative).resolve(strict=False)
        snapshot[str(absolute)] = {
            "status": status,
            "sha256": _file_digest(absolute),
        }
    return snapshot


def _git_diff_paths(repo, before_head, after_head):
    if before_head == after_head:
        return []
    completed = subprocess.run(
        ["git", "-C", str(repo), "diff", "--name-only", "-z", before_head, after_head],
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise ValueError("cannot compare repository HEAD: {}".format(repo))
    return [
        str((repo / raw.decode("utf-8", errors="surrogateescape")).resolve(strict=False))
        for raw in completed.stdout.split(b"\0") if raw
    ]


class RootExecutionGate:
    """Bind root-task authority to paths and attest actual repository changes."""

    def __init__(self, codex_home, now=None):
        self.codex_home = Path(codex_home).expanduser().resolve(strict=False)
        self._now = now or (lambda: datetime.now(timezone.utc))

    @property
    def binding_directory(self):
        return self.codex_home / "agent-system/root-execution-bindings"

    @property
    def proof_directory(self):
        return self.codex_home / "agent-system/root-scope-proofs"

    @property
    def context_directory(self):
        return self.codex_home / "agent-system/root-task-contexts"

    def bootstrap(self, context, session_id=None):
        """Atomically persist a validated context and its first root binding."""
        session = session_id or os.environ.get("CODEX_THREAD_ID")
        if not isinstance(session, str) or not session.strip():
            raise ValueError("root execution requires a session id")
        if not isinstance(context, dict) or context.get("schema_version") != "1.6":
            raise ValueError("root execution requires task context schema 1.6")
        self._validate_context(context)
        context_path = self.context_directory / (self._session_key(session) + ".json")
        binding_path = self.binding_directory / (self._session_key(session) + ".json")
        lock_path = self.binding_directory / ".bootstrap.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(str(lock_path), os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            if os.path.getsize(lock_path) == 0:
                os.write(descriptor, b"\0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX)
            if binding_path.exists() or context_path.exists():
                raise ValueError("root session already has an unattested execution binding")
            _atomic_json(context_path, context)
            try:
                result = self._prepare_validated(context, context_path, session)
            except Exception:
                context_path.unlink(missing_ok=True)
                binding_path.unlink(missing_ok=True)
                raise
        finally:
            if os.name == "nt":
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            os.close(descriptor)
        result["task_context"] = str(context_path)
        return result

    def prepare(self, task_context, session_id=None):
        context_path = Path(task_context).expanduser().resolve(strict=False)
        if not context_path.is_file():
            raise ValueError("task context does not exist")
        context = json.loads(context_path.read_text(encoding="utf-8"))
        if context.get("schema_version") != "1.6":
            raise ValueError("root execution requires task context schema 1.6")
        self._validate_context(context)
        session = session_id or os.environ.get("CODEX_THREAD_ID")
        if not isinstance(session, str) or not session.strip():
            raise ValueError("root execution requires a session id")
        return self._prepare_validated(context, context_path, session)

    def _validate_context(self, context):
        report = Report()
        validate_task_context(context, report, check_paths=True, check_freshness=True)
        if report.errors:
            raise ValueError("task context validation failed: {}".format("; ".join(report.errors)))

    def _prepare_validated(self, context, context_path, session):
        scope = context.get("scope")
        if not isinstance(scope, dict):
            raise ValueError("task context scope is invalid")
        allowed = self._absolute_paths(scope.get("allowed_paths"), "scope.allowed_paths", non_empty=True)
        repositories = self._absolute_paths(scope.get("repositories"), "scope.repositories", non_empty=True)
        preexisting = self._absolute_paths(scope.get("preexisting_changes", []), "scope.preexisting_changes")
        if any(not _covered(path, allowed) for path in preexisting):
            raise ValueError("preexisting_changes must be inside allowed_paths")
        baselines = []
        for repo in repositories:
            if not (repo / ".git").exists():
                raise ValueError("scope repository is not a Git repository: {}".format(repo))
            head = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
            )
            if head.returncode:
                raise ValueError("cannot resolve repository HEAD: {}".format(repo))
            baselines.append({"root": str(repo), "head": head.stdout.strip(), "status": _git_snapshot(repo)})
        created = self._now()
        binding = {
            "schema_version": BINDING_SCHEMA,
            "task_id": context.get("task_id"),
            "task_context": str(context_path),
            "context_hash": _canonical_hash(context),
            "session_id": session,
            "allowed_paths": [str(path) for path in allowed],
            "preexisting_changes": [str(path) for path in preexisting],
            "repositories": baselines,
            "created_at": created.isoformat(),
            "expires_at": (created + timedelta(seconds=MAX_BINDING_AGE_SECONDS)).isoformat(),
            "nonce": secrets.token_hex(16),
        }
        binding["binding_hash"] = _canonical_hash(binding)
        path = self.binding_directory / (self._session_key(session) + ".json")
        if path.exists():
            raise ValueError("root session already has an unattested execution binding")
        _atomic_json(path, binding)
        return {"binding_path": str(path), "binding_hash": _hash_bytes(path.read_bytes())}

    def decision(self, payload):
        tool_name = str(payload.get("tool_name") or payload.get("tool") or "")
        tool_input = payload.get("tool_input", {})
        command = str(tool_input.get("cmd") or tool_input.get("command") or "") if isinstance(tool_input, dict) else ""
        if tool_name == "exec_command" and self._is_read_only_command(command):
            return None
        if tool_name == "exec_command" and self._is_bootstrap_command(command, payload):
            return None
        try:
            binding = self._active_binding(str(
                payload.get("session_id") or payload.get("thread_id")
                or os.environ.get("CODEX_THREAD_ID") or ""
            ))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {"decision": "block", "reason": "拒绝根任务写入：{}。".format(exc)}
        if tool_name == "apply_patch" and isinstance(tool_input, dict):
            patch = str(tool_input.get("patch") or tool_input.get("input") or "")
            cwd = Path(str(payload.get("cwd") or ".")).expanduser().resolve(strict=False)
            allowed = [Path(path).resolve(strict=False) for path in binding["allowed_paths"]]
            for raw in PATCH_PATH_RE.findall(patch):
                target = Path(raw.strip())
                target = target.resolve(strict=False) if target.is_absolute() else (cwd / target).resolve(strict=False)
                if not _covered(target, allowed):
                    return {"decision": "block", "reason": "拒绝根任务写入：目标超出 scope.allowed_paths（{}）。".format(target)}
        if tool_name == "exec_command" and command:
            cwd = Path(str(payload.get("cwd") or ".")).expanduser().resolve(strict=False)
            allowed = [Path(path).resolve(strict=False) for path in binding["allowed_paths"]]
            for match in WRITE_TARGET_RE.finditer(command):
                raw = next((value for value in match.groups() if value), "").strip("'\"")
                target = Path(raw).expanduser()
                target = target.resolve(strict=False) if target.is_absolute() else (cwd / target).resolve(strict=False)
                if not _covered(target, allowed):
                    return {"decision": "block", "reason": "拒绝根任务写入：命令目标超出 scope.allowed_paths（{}）。".format(target)}
        return None

    @staticmethod
    def _is_read_only_command(command):
        try:
            lexer = shlex.shlex(command, posix=os.name != "nt", punctuation_chars=";&|<>")
            lexer.whitespace_split = True
            tokens = list(lexer)
        except ValueError:
            return False
        if not tokens or any(token in {";", "&", "&&", "|", "||", "<", ">", ">>"} for token in tokens):
            return False
        if any("$(" in token or "`" in token for token in tokens):
            return False
        executable = Path(tokens[0]).name
        if executable in READ_ONLY_COMMANDS:
            return executable != "pwd" or len(tokens) == 1
        if executable != "git" or len(tokens) < 2:
            return False
        if tokens[1] in READ_ONLY_GIT_COMMANDS:
            return True
        return tokens[1:3] == ["branch", "--show-current"] and len(tokens) == 3

    def _is_bootstrap_command(self, command, payload):
        """Allow exactly the managed bootstrap CLI before a binding exists."""
        try:
            tokens = shlex.split(command, posix=os.name != "nt")
        except ValueError:
            return False
        if len(tokens) != 7:
            return False
        executable, script, bootstrap, context_flag, encoded, session_flag, session = tokens
        if (
            not Path(executable).is_absolute()
            or Path(executable).resolve(strict=False)
            != Path(sys.executable).resolve(strict=False)
        ):
            return False
        expected_script = (self.codex_home / "hooks/guard_task_writes.py").resolve(strict=False)
        if Path(script).expanduser().resolve(strict=False) != expected_script:
            return False
        if (bootstrap, context_flag, session_flag) != (
            "--bootstrap", "--task-context-base64", "--session-id"
        ):
            return False
        payload_session = str(
            payload.get("session_id") or payload.get("thread_id")
            or os.environ.get("CODEX_THREAD_ID") or ""
        )
        if not payload_session or session != payload_session:
            return False
        if len(encoded) > 262144:
            return False
        try:
            decoded = base64.b64decode(encoded.encode("ascii"), validate=True)
            context = json.loads(decoded.decode("utf-8"))
        except (ValueError, UnicodeError, json.JSONDecodeError):
            return False
        return isinstance(context, dict) and context.get("schema_version") == "1.6"

    def attest(self, binding_path, binding_file_hash):
        path = Path(binding_path).expanduser().resolve(strict=False)
        if not path.is_file() or _hash_bytes(path.read_bytes()) != binding_file_hash:
            raise ValueError("root execution binding is missing or changed")
        binding = self._validate_binding(json.loads(path.read_text(encoding="utf-8")))
        context_path = Path(binding["task_context"])
        context = json.loads(context_path.read_text(encoding="utf-8"))
        if _canonical_hash(context) != binding["context_hash"]:
            raise ValueError("task context drifted after root binding")
        allowed = [Path(value).resolve(strict=False) for value in binding["allowed_paths"]]
        accepted_preexisting = {str(Path(value).resolve(strict=False)) for value in binding["preexisting_changes"]}
        changed = []
        scope_violations = []
        preexisting_violations = []
        current_heads = {}
        for baseline in binding["repositories"]:
            repo = Path(baseline["root"])
            current = _git_snapshot(repo)
            before = baseline["status"]
            head = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
            )
            current_head = head.stdout.strip() if head.returncode == 0 else None
            committed = _git_diff_paths(repo, baseline["head"], current_head) if current_head else []
            status_changed = {
                changed_path
                for changed_path in set(before) | set(current)
                if before.get(changed_path) != current.get(changed_path)
            }
            for changed_path in sorted(status_changed | set(committed)):
                changed.append(changed_path)
                if not _covered(changed_path, allowed):
                    scope_violations.append(changed_path)
                if changed_path in before and changed_path not in accepted_preexisting:
                    preexisting_violations.append(changed_path)
            current_heads[str(repo)] = current_head
        proof = {
            "schema_version": PROOF_SCHEMA,
            "task_id": binding["task_id"],
            "context_hash": binding["context_hash"],
            "binding_hash": binding["binding_hash"],
            "status": "passed" if not scope_violations and not preexisting_violations else "failed",
            "changed_paths": sorted(set(changed)),
            "scope_violations": sorted(set(scope_violations)),
            "preexisting_change_violations": sorted(set(preexisting_violations)),
            "repository_heads": current_heads,
            "attested_at": self._now().isoformat(),
        }
        proof_path = self.proof_directory / (binding["nonce"] + ".json")
        _atomic_json(proof_path, proof)
        if proof["status"] == "passed":
            os.replace(str(path), str(path.with_suffix(".attested")))
        result = dict(proof)
        result["proof_path"] = str(proof_path)
        result["proof_sha256"] = _hash_bytes(proof_path.read_bytes())
        return result

    def run_verification(self, binding_path, binding_file_hash, verification_id):
        path = Path(binding_path).expanduser().resolve(strict=False)
        if not path.is_file() or _hash_bytes(path.read_bytes()) != binding_file_hash:
            raise ValueError("root execution binding is missing or changed")
        binding = self._validate_binding(json.loads(path.read_text(encoding="utf-8")))
        context = json.loads(Path(binding["task_context"]).read_text(encoding="utf-8"))
        if _canonical_hash(context) != binding["context_hash"]:
            raise ValueError("task context drifted after root binding")
        matches = [
            item for item in context.get("verification", [])
            if isinstance(item, dict) and item.get("id") == verification_id
        ]
        if len(matches) != 1:
            raise ValueError("verification id is not uniquely authorized")
        verification = matches[0]
        command = verification["command"]
        started = self._now()
        completed = subprocess.run(
            command,
            cwd=context["scope"]["workspace"],
            shell=True,
            capture_output=True,
            text=False,
            check=False,
        )
        ended = self._now()
        output = completed.stdout + b"\0" + completed.stderr
        evidence = {
            "schema_version": VERIFICATION_EVIDENCE_SCHEMA,
            "task_id": binding["task_id"],
            "context_hash": binding["context_hash"],
            "binding_hash": binding["binding_hash"],
            "verification_id": verification["id"],
            "category": verification["category"],
            "command": command,
            "expected": verification["expected"],
            "exit_code": completed.returncode,
            "started_at": started.isoformat(),
            "ended_at": ended.isoformat(),
            "output_sha256": _hash_bytes(output),
        }
        evidence_path = self.codex_home / "agent-system/verification-evidence" / binding["nonce"] / (verification_id + ".json")
        _atomic_json(evidence_path, evidence)
        return {
            "id": verification["id"],
            "category": verification["category"],
            "command": command,
            "status": "passed" if completed.returncode == 0 else "failed",
            "summary": "controlled verification exited {}".format(completed.returncode),
            "exit_code": completed.returncode,
            "started_at": evidence["started_at"],
            "ended_at": evidence["ended_at"],
            "evidence_path": str(evidence_path),
            "evidence_sha256": _hash_bytes(evidence_path.read_bytes()),
        }

    def _active_binding(self, session_id):
        if not session_id:
            raise ValueError("缺少根任务执行绑定")
        path = self.binding_directory / (self._session_key(session_id) + ".json")
        if not path.is_file():
            raise ValueError("缺少根任务执行绑定")
        binding = self._validate_binding(json.loads(path.read_text(encoding="utf-8")))
        if binding.get("session_id") != session_id:
            raise ValueError("根任务执行绑定会话不匹配")
        context = json.loads(Path(binding["task_context"]).read_text(encoding="utf-8"))
        if _canonical_hash(context) != binding["context_hash"]:
            raise ValueError("根任务上下文已漂移")
        return binding

    def _validate_binding(self, binding):
        stored = binding.get("binding_hash")
        unhashed = dict(binding)
        unhashed.pop("binding_hash", None)
        if binding.get("schema_version") != BINDING_SCHEMA or stored != _canonical_hash(unhashed):
            raise ValueError("根任务执行绑定完整性校验失败")
        expires = datetime.fromisoformat(str(binding.get("expires_at", "")).replace("Z", "+00:00"))
        if expires.tzinfo is None or self._now() >= expires:
            raise ValueError("根任务执行绑定已过期")
        return binding

    @staticmethod
    def _absolute_paths(values, label, non_empty=False):
        if not isinstance(values, list) or (non_empty and not values):
            raise ValueError("{} must be {}list".format(label, "a non-empty " if non_empty else "a "))
        result = []
        for value in values:
            path = Path(str(value)).expanduser()
            if not isinstance(value, str) or not value.strip() or not path.is_absolute():
                raise ValueError("{} must contain absolute paths".format(label))
            result.append(path.resolve(strict=False))
        return result

    @staticmethod
    def _session_key(session_id):
        return _hash_bytes(session_id.encode("utf-8"))


def self_test():
    assert _canonical_hash({"a": 1, "b": 2}) == _canonical_hash({"b": 2, "a": 1})
    assert _covered("/tmp/a/b", [Path("/tmp/a")])
