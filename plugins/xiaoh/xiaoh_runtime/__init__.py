"""XiaoH modular local runtime.

Public behavior is exposed through :mod:`xiaoh_runtime.cli`. Domain modules
import lower-level dependencies directly so package import order cannot
create a partially initialized runtime.
"""
