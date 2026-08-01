#!/usr/bin/env python3
import argparse
import json
import hashlib
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path


def derive_counts(stdout, stderr, exit_code):
    combined = stdout + "\n" + stderr
    unittest_count = re.search(r"Ran (\d+) tests?", combined)
    if unittest_count:
        executed = int(unittest_count.group(1))
        terminal = re.search(r"(?:OK|FAILED)(?: \(([^\n]*)\))?\s*$", combined.strip())
        if terminal is None:
            raise ValueError("unittest terminal summary is missing")
        values = {
            key: int(value)
            for key, value in re.findall(
                r"(failures|errors|skipped|expected failures|unexpected successes)=(\d+)",
                terminal.group(1) or "",
            )
        }
        failed = sum(values.get(key, 0) for key in ("failures", "errors", "unexpected successes"))
        skipped = values.get("skipped", 0)
        expected_failures = values.get("expected failures", 0)
        passed = executed - failed - skipped - expected_failures
        if passed < 0 or (exit_code == 0) != (failed == 0):
            raise ValueError("unittest terminal counts are inconsistent")
        return executed, passed, failed, skipped, expected_failures
    try:
        document = json.loads(stdout)
    except (TypeError, json.JSONDecodeError):
        document = None
    totals = document.get("summary", {}).get("totals") if isinstance(document, dict) else None
    if isinstance(totals, dict) and all(
        type(totals.get(key)) is int for key in ("items", "passed", "failed")
    ):
        return totals["items"], totals["passed"], totals["failed"], 0, 0
    return 1, 1 if exit_code == 0 else 0, 0 if exit_code == 0 else 1, 0, 0


def atomic_write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".command-result-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(
        description="Run one command and persist its source-bound result."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a command is required after --")
    completed = subprocess.run(
        command, check=False, capture_output=True, text=True, encoding="utf-8"
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    exit_code = completed.returncode
    executed, passed, failed, skipped, expected_failures = derive_counts(
        completed.stdout, completed.stderr, exit_code
    )
    atomic_write(
        args.output,
        {
            "schema_version": "xiaoh-command-evidence/v2",
            "command": shlex.join(command),
            "exit_code": exit_code,
            "executed_count": executed,
            "passed_count": passed,
            "failed_count": failed,
            "skipped_count": skipped,
            "expected_failure_count": expected_failures,
            "stdout": completed.stdout,
            "stdout_sha256": hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest(),
            "stderr": completed.stderr,
            "stderr_sha256": hashlib.sha256(completed.stderr.encode("utf-8")).hexdigest(),
        },
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
