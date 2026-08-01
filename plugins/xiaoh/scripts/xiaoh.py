#!/usr/bin/env python3
"""Launcher for the XiaoH 4.0.0 runtime."""

from __future__ import annotations

import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

from xiaoh_runtime.interface.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
