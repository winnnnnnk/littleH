#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
args=(doctor)
if [[ "${1:-}" == "--runtime" ]]; then
  args+=(--runtime)
elif [[ $# -gt 0 ]]; then
  echo "用法: $0 [--runtime]" >&2
  exit 2
fi
python3 "$ROOT/plugins/xiaoh/scripts/xiaoh.py" "${args[@]}"
