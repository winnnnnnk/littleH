import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "plugins/xiaoh/scripts/xiaoh.py"
SPEC = importlib.util.spec_from_file_location("xiaoh_runtime", SCRIPT)
XIAOH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(XIAOH)


class CompanionTests(unittest.TestCase):
    def test_installs_declared_plugins_on_a_fresh_machine(self):
        installed = set()
        marketplaces = {"openai-bundled", "openai-primary-runtime"}
        calls = []

        def fake_codex(arguments):
            calls.append(arguments)
            if arguments == ["plugin", "list"]:
                return {"installed": [{"pluginId": value, "enabled": True} for value in installed]}, None
            if arguments == ["plugin", "marketplace", "list"]:
                return {"marketplaces": [{"name": value} for value in marketplaces]}, None
            if arguments[:3] == ["plugin", "marketplace", "add"]:
                marketplaces.add("ponytail")
                return {}, None
            if arguments[:2] == ["plugin", "add"]:
                installed.add(arguments[2])
                return {}, None
            self.fail(f"unexpected Codex invocation: {arguments}")

        with patch.object(XIAOH, "run_codex_json", side_effect=fake_codex), patch.object(
            XIAOH.shutil, "which", return_value=None
        ):
            result = XIAOH.companion_report(install_missing=True)

        self.assertEqual("degraded", result["status"])
        self.assertEqual(10, len(result["installed_now"]))
        self.assertTrue(all(item["status"] == "installed" for item in result["plugins"]))
        self.assertIn(
            ["plugin", "marketplace", "add", "DietrichGebert/ponytail", "--ref", "main"],
            calls,
        )
        self.assertEqual("missing", result["external_capabilities"][0]["status"])
        self.assertFalse(result["errors"])

    def test_runtime_update_preserves_existing_vault_knowledge(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex = root / "codex"
            vault = root / "vault"
            ledger = vault / "04-架构与决策/Agent进化台账.md"
            vault_agents = vault / "AGENTS.md"
            ledger.parent.mkdir(parents=True)
            ledger.write_text("retained __CODEX_HOME__ knowledge\n", encoding="utf-8")
            vault_agents.write_text("stale managed rules\n", encoding="utf-8")

            target_agents, vault_files = XIAOH.copy_runtime(codex, vault)
            XIAOH.replace_placeholders(
                [target_agents, codex / "agents", codex / "contexts", codex / "agent-system", codex / "hooks", *vault_files],
                [("__CODEX_HOME__", codex.as_posix()), ("__OBSIDIAN_VAULT__", vault.as_posix())],
            )

            self.assertEqual("retained __CODEX_HOME__ knowledge\n", ledger.read_text(encoding="utf-8"))
            self.assertIn("开发知识库规则", vault_agents.read_text(encoding="utf-8"))
            self.assertNotIn(
                "__CODEX_HOME__",
                (vault / "04-架构与决策/Agent协作角色.md").read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
