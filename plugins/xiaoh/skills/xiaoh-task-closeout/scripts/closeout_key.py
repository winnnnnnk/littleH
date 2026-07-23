#!/usr/bin/env python3
"""Build a deterministic XiaoH closeout key from stable task evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path


PLACEHOLDERS = {"", "unknown", "none", "n/a", "待确认", "待补充"}


def required(value: str, label: str) -> str:
    normalized = value.strip()
    if normalized.lower() in PLACEHOLDERS or normalized in PLACEHOLDERS:
        raise ValueError(f"{label}缺少稳定值")
    return normalized


def slug(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-").lower()
    return result[:48] or "id"


def build_closeout_key(
    source_kind: str,
    source_id: str,
    stage_id: str,
    accepted_revision: str,
) -> dict:
    identity = {
        "source_kind": required(source_kind, "source_kind"),
        "source_id": required(source_id, "source_id"),
        "stage_id": required(stage_id, "stage_id"),
        "accepted_revision": required(accepted_revision, "accepted_revision"),
    }
    canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    key = (
        f"xiaoh-closeout:{slug(identity['source_kind'])}:"
        f"{slug(identity['source_id'])}:{slug(identity['stage_id'])}:{digest[:16]}"
    )
    return {"closeout_key": key, "identity": identity, "identity_sha256": digest}


def resolve_source(source_kind: str, source_id: str | None, environ: dict | None = None) -> str:
    environ = os.environ if environ is None else environ
    if source_kind == "playbook_task":
        return required(source_id or "", "Playbook task ID")
    runtime_id = required(environ.get("CODEX_THREAD_ID", ""), "CODEX_THREAD_ID")
    if source_id and required(source_id, "source_id") != runtime_id:
        raise ValueError("source_id与当前CODEX_THREAD_ID不一致")
    return runtime_id


def resolve_stage(stage_id: str | None, final: bool) -> str:
    if final:
        if stage_id:
            raise ValueError("--final与--stage-id不能同时使用")
        return "task-complete"
    return required(stage_id or "", "stage_id")


def evidence_revision(paths: list[str]) -> str:
    if not paths:
        raise ValueError("普通Codex任务必须提供至少一个已验收证据路径")
    evidence = []
    for value in paths:
        path = Path(value).expanduser().resolve()
        if not path.is_file():
            raise ValueError(f"证据文件不存在: {path}")
        evidence.append(hashlib.sha256(path.read_bytes()).hexdigest())
    canonical = json.dumps(sorted(evidence), separators=(",", ":"))
    return "evidence-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-kind", choices=("playbook_task", "codex_thread"), required=True)
    parser.add_argument("--source-id")
    stage = parser.add_mutually_exclusive_group(required=True)
    stage.add_argument("--stage-id")
    stage.add_argument("--final", action="store_true")
    revision = parser.add_mutually_exclusive_group(required=True)
    revision.add_argument("--accepted-revision")
    revision.add_argument("--evidence-path", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        source_id = resolve_source(args.source_kind, args.source_id)
        if args.source_kind == "codex_thread":
            if args.accepted_revision:
                raise ValueError("普通Codex任务必须由--evidence-path计算验收修订")
            accepted_revision = evidence_revision(args.evidence_path)
        else:
            accepted_revision = (
                required(args.accepted_revision, "accepted_revision")
                if args.accepted_revision
                else evidence_revision(args.evidence_path)
            )
        result = build_closeout_key(
            args.source_kind,
            source_id,
            resolve_stage(args.stage_id, args.final),
            accepted_revision,
        )
    except ValueError as exc:
        parser.error(str(exc))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["closeout_key"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
