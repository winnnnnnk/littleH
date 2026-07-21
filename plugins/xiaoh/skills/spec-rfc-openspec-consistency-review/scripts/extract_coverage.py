#!/usr/bin/env python3
"""Extract source Spec/RFC numbered items and simple OpenSpec hit hints.

Usage:
  python3 extract_coverage.py <source-spec-rfc.md> <openspec-change-dir>
"""
import re
import sys
from pathlib import Path

ITEM_RE = re.compile(r"^#{2,4}\s+((?:FR|NFR|IF|TR|ADR|TBD)-?\d+|\d+(?:\.\d+)*)(?:[：:：\s]+)(.*)$", re.I)
KEY_RE = re.compile(r"`([^`]+)`|\b([A-Za-z][A-Za-z0-9_.-]{2,})\b")


def read(path):
    return Path(path).read_text(encoding="utf-8", errors="ignore")


def source_items(src):
    items = []
    lines = read(src).splitlines()
    for index, line in enumerate(lines, 1):
        m = ITEM_RE.match(line.strip())
        if not m:
            continue
        ident = m.group(1).upper()
        title = m.group(2).strip()
        terms = []
        for term in KEY_RE.findall(line):
            value = term[0] or term[1]
            if value and value not in terms:
                terms.append(value)
        items.append({"id": ident, "title": title, "line": index, "terms": terms[:8]})
    return items


def openspec_files(change_dir):
    root = Path(change_dir)
    names = ["proposal.md", "design.md", "tasks.md"]
    files = [root / name for name in names if (root / name).exists()]
    files.extend(sorted((root / "specs").glob("**/spec.md")) if (root / "specs").exists() else [])
    return files


def hit_lines(files, item):
    needles = [item["id"], item["title"]] + item["terms"]
    needles = [n for n in needles if n]
    hits = []
    for file in files:
        try:
            lines = read(file).splitlines()
        except OSError:
            continue
        for idx, line in enumerate(lines, 1):
            if any(n in line for n in needles):
                hits.append(f"{file}:{idx}")
                break
    return hits


def main(argv):
    if len(argv) != 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    src, change = argv[1], argv[2]
    files = openspec_files(change)
    print("| 源条目 | 源行 | OpenSpec 命中线索 |")
    print("|---|---:|---|")
    for item in source_items(src):
        hits = hit_lines(files, item)
        hit_text = "<br>".join(hits[:8]) if hits else "未命中"
        print(f"| {item['id']} {item['title']} | {item['line']} | {hit_text} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
