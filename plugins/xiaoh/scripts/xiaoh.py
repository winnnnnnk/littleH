#!/usr/bin/env python3
"""Launcher for the XiaoH 3.1.2 modular runtime."""

from __future__ import annotations

import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

from xiaoh_runtime.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
