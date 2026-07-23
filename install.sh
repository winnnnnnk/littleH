#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
CODEX_TARGET="${CODEX_HOME:-$HOME/.codex}"

for command_name in codex python3; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "缺少必需命令: $command_name" >&2
    exit 1
  fi
done

mkdir -p "$CODEX_TARGET"
codex plugin marketplace add "$ROOT" --json
codex plugin add xiaoh@xiaoh --json
python3 "$ROOT/plugins/xiaoh/scripts/xiaoh.py" setup --allow-degraded
