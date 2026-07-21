import importlib.util
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


if __name__ == "__main__":
    unittest.main()
