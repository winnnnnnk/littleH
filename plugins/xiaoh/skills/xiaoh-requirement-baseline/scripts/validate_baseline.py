#!/usr/bin/env python3
"""Validate XiaoH requirement-baseline confirmation points."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REQUIRED_COLUMNS = [
    "ID",
    "状态",
    "superseded_by",
    "业务规则",
    "设计依据",
    "证据与确认来源",
    "适用与排除范围",
    "验收条件",
    "影响与追溯",
    "剩余不确定项",
]
ALLOWED_STATES = {"pending", "confirmed", "superseded", "rejected"}
ALLOWED_TRANSITIONS = {
    "pending": {"pending", "confirmed", "rejected"},
    "confirmed": {"confirmed", "superseded"},
    "superseded": {"superseded"},
    "rejected": {"rejected"},
}
EMPTY_VALUES = {"", "-", "—", "待确认", "unknown", "未知"}
IMMUTABLE_FIELDS = [
    "业务规则",
    "设计依据",
    "证据与确认来源",
    "适用与排除范围",
    "验收条件",
    "影响与追溯",
    "剩余不确定项",
]


def cells(line: str) -> list[str]:
    return [value.strip().strip("`") for value in line.strip().strip("|").split("|")]


def confirmation_points(path: Path) -> dict[str, dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    try:
        section = next(index for index, line in enumerate(lines) if line.strip() == "## 确认点")
        header_index = next(
            index for index in range(section + 1, len(lines))
            if lines[index].lstrip().startswith("|")
        )
    except StopIteration as exc:
        raise ValueError("缺少“确认点”章节或表格") from exc
    header = cells(lines[header_index])
    if header != REQUIRED_COLUMNS:
        raise ValueError("确认点表头必须为: " + " | ".join(REQUIRED_COLUMNS))
    separator_index = header_index + 1
    if separator_index >= len(lines):
        raise ValueError("确认点表格缺少Markdown分隔行")
    separator = cells(lines[separator_index])
    if len(separator) != len(header) or any(
        not re.fullmatch(r":?-{3,}:?", value) for value in separator
    ):
        raise ValueError("确认点表格缺少或包含无效Markdown分隔行")
    points: dict[str, dict[str, str]] = {}
    for line in lines[separator_index + 1:]:
        if line.startswith("## "):
            break
        if not line.strip():
            continue
        if not line.lstrip().startswith("|"):
            raise ValueError(f"确认点表格包含无法解析的内容: {line}")
        values = cells(line)
        if len(values) != len(header):
            raise ValueError(f"确认点列数错误: {line}")
        point = dict(zip(header, values))
        point_id = point["ID"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", point_id):
            raise ValueError(f"确认点ID无效: {point_id!r}")
        if point_id in points:
            raise ValueError(f"确认点ID重复: {point_id}")
        if point["状态"] not in ALLOWED_STATES:
            raise ValueError(f"确认点状态无效: {point_id}: {point['状态']}")
        if point["状态"] == "confirmed" and point["证据与确认来源"] in EMPTY_VALUES:
            raise ValueError(f"confirmed确认点缺少证据来源: {point_id}")
        points[point_id] = point
    for point_id, point in points.items():
        successor = point["superseded_by"]
        if point["状态"] == "superseded":
            if successor in EMPTY_VALUES:
                raise ValueError(f"superseded确认点缺少superseded_by: {point_id}")
            if successor not in points:
                raise ValueError(f"superseded_by目标不存在: {point_id} -> {successor}")
            if successor == point_id:
                raise ValueError(f"superseded确认点不得指向自身: {point_id}")
            if points[successor]["状态"] != "confirmed":
                raise ValueError(
                    f"superseded_by目标必须是confirmed: {point_id} -> {successor}"
                )
        elif successor not in EMPTY_VALUES:
            raise ValueError(f"非superseded确认点不得设置superseded_by: {point_id}")
    return points


def validate_transition(previous: dict[str, dict[str, str]], current: dict[str, dict[str, str]]) -> None:
    for point_id, old in previous.items():
        if point_id not in current:
            raise ValueError(f"历史确认点被删除: {point_id}")
        new_state = current[point_id]["状态"]
        if new_state not in ALLOWED_TRANSITIONS[old["状态"]]:
            raise ValueError(f"非法状态转换: {point_id}: {old['状态']} -> {new_state}")
        if old["状态"] in {"confirmed", "superseded", "rejected"}:
            for field in IMMUTABLE_FIELDS:
                if old.get(field) != current[point_id].get(field):
                    raise ValueError(f"历史确认点被原地改写: {point_id}: {field}")
        if old["状态"] == "confirmed" and new_state == "superseded":
            successor = current[point_id]["superseded_by"]
            previous_successor = previous.get(successor)
            if previous_successor is not None and previous_successor["状态"] != "pending":
                raise ValueError(
                    f"取代目标必须是本版新增或由pending转为confirmed: "
                    f"{point_id} -> {successor}"
                )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args()
    try:
        current = confirmation_points(args.baseline)
        if args.previous:
            validate_transition(confirmation_points(args.previous), current)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"baseline validation failed: {exc}", file=sys.stderr)
        return 1
    print(f"baseline validation passed: {len(current)} confirmation points")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
