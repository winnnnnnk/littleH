"""External-effect ports used by XiaoH application services."""

from .protocols import (
    AutomationStorePort,
    ClockPort,
    FileSystemPort,
    PluginFactsPort,
    ProcessResult,
    ProcessRunnerPort,
)

__all__ = [
    "AutomationStorePort",
    "ClockPort",
    "FileSystemPort",
    "PluginFactsPort",
    "ProcessResult",
    "ProcessRunnerPort",
]
