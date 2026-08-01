#!/usr/bin/env python3
"""Print simple source-item to OpenSpec hit hints."""

import re
import sys
from pathlib import Path

ITEM_RE = re.compile(r"^#{2,4}\s+((?:FR|NFR|IF|TR|ADR|TBD)-?\d+|\d+(?:\.\d+)*)(?:[：:\s]+)(.*)$", re.I)


def read(path):
    return Path(path).read_text(encoding="utf-8", errors="ignore")


def main(argv):
    if len(argv) != 3:
        print("usage: extract_coverage.py <source-spec-rfc.md> <openspec-change-dir>", file=sys.stderr)
        return 2
    source, root = Path(argv[1]), Path(argv[2])
    targets = [path for path in (root / "proposal.md", root / "design.md", root / "tasks.md") if path.is_file()]
    if (root / "specs").is_dir():
        targets.extend(sorted((root / "specs").glob("**/spec.md")))
    target_lines = {path: read(path).splitlines() for path in targets}
    print("| 源条目 | 源行 | OpenSpec 命中线索 |")
    print("|---|---:|---|")
    for number, line in enumerate(read(source).splitlines(), 1):
        match = ITEM_RE.match(line.strip())
        if not match:
            continue
        item_id, title = match.group(1).upper(), match.group(2).strip()
        hits = []
        for path, lines in target_lines.items():
            for target_number, target_line in enumerate(lines, 1):
                if item_id in target_line or (title and title in target_line):
                    hits.append("{}:{}".format(path, target_number))
                    break
        print("| {} {} | {} | {} |".format(item_id, title, number, "<br>".join(hits) or "未命中"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
