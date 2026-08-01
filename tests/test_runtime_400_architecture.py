"""Executable architecture constraints for the XiaoH 4.0 runtime."""

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "plugins/xiaoh/xiaoh_runtime"
AGENT_SYSTEM = ROOT / "plugins/xiaoh/runtime/codex/agent-system"
HOOKS = ROOT / "plugins/xiaoh/runtime/codex/hooks"


ALLOWED_INTERNAL = {
    "domain": {"domain"},
    "ports": {"ports"},
    "services": {"domain", "ports", "services"},
    "capabilities": {"ports", "capabilities"},
    "diagnostics": {"domain", "ports", "services", "capabilities", "diagnostics"},
    "installation": {
        "domain", "ports", "services", "capabilities", "diagnostics", "installation"
    },
    "adapters": {"ports", "adapters"},
    "application": {
        "domain", "ports", "services", "capabilities", "diagnostics",
        "installation", "application",
    },
    "interface": {
        "domain", "ports", "services", "capabilities", "diagnostics",
        "installation", "adapters", "application", "interface",
    },
}


class Runtime400ArchitectureTests(unittest.TestCase):
    def test_old_flat_runtime_modules_are_absent(self):
        old = {
            "automation.py", "cli.py", "common.py", "config.py", "doctor.py",
            "install.py", "plugin_state.py", "vault_runtime.py", "workspace.py",
        }
        self.assertEqual([], sorted(path.name for path in RUNTIME.iterdir() if path.name in old))

    def test_python_39_syntax_and_no_star_imports(self):
        files = [
            path
            for root in (RUNTIME, AGENT_SYSTEM, HOOKS)
            for path in root.rglob("*.py")
        ]
        stars = []
        for path in files:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path), feature_version=(3, 9))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and any(
                    alias.name == "*" for alias in node.names
                ):
                    stars.append(str(path.relative_to(ROOT)))
        self.assertEqual([], stars)

    def test_runtime_dependency_direction_and_cycles(self):
        graph = {}
        violations = []
        for path in RUNTIME.rglob("*.py"):
            module = _module_name(path)
            source_layer = _layer(path)
            graph[module] = set()
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or node.level == 0:
                    continue
                target = _resolve_relative(module, path.name == "__init__.py", node.level, node.module)
                if not target.startswith("xiaoh_runtime."):
                    continue
                graph[module].add(target)
                target_parts = target.split(".")
                target_layer = target_parts[1] if len(target_parts) > 1 else None
                if target_layer and target_layer not in ALLOWED_INTERNAL[source_layer]:
                    violations.append(
                        "{} may not import {}".format(
                            path.relative_to(ROOT), target
                        )
                    )
        self.assertEqual([], violations)
        cycle = _first_cycle(graph)
        self.assertEqual([], cycle, " -> ".join(cycle))


def _module_name(path):
    relative = path.relative_to(RUNTIME.parent).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _layer(path):
    parts = path.relative_to(RUNTIME).parts
    return "interface" if len(parts) == 1 else parts[0]


def _resolve_relative(module, is_package, level, child):
    base = module.split(".") if is_package else module.split(".")[:-1]
    if level > 1:
        base = base[: -(level - 1)]
    if child:
        base.extend(child.split("."))
    return ".".join(base)


def _first_cycle(graph):
    visiting = set()
    visited = set()
    path = []

    def visit(node):
        if node in visiting:
            index = path.index(node)
            return path[index:] + [node]
        if node in visited:
            return []
        visiting.add(node)
        path.append(node)
        for child in graph.get(node, ()):
            cycle = visit(child)
            if cycle:
                return cycle
        path.pop()
        visiting.remove(node)
        visited.add(node)
        return []

    for node in graph:
        cycle = visit(node)
        if cycle:
            return cycle
    return []


if __name__ == "__main__":
    unittest.main()
