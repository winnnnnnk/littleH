from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from plugins.xiaoh.xiaoh_runtime.adapters.local import LocalFileSystem
from plugins.xiaoh.xiaoh_runtime.capabilities.skills import SkillGovernance


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/xiaoh"


class Runtime400SkillGovernanceTests(unittest.TestCase):
    def test_fixed_source_manifest_and_adapted_skills_validate(self) -> None:
        report = SkillGovernance(LocalFileSystem(), PLUGIN).validate()

        self.assertEqual("passed", report["status"], report)
        self.assertEqual(
            {"replace": 0, "adapt_and_add": 10, "absorb_method": 8, "exclude": 4},
            report["decision_counts"],
        )
        self.assertEqual([], report["errors"])
        dependencies = json.loads((PLUGIN / "dependencies.json").read_text(encoding="utf-8"))
        self.assertEqual("xiaoh-dependencies/v2", dependencies["schema_version"])
        self.assertTrue(all(item["auto_install"] is False for item in dependencies["codex_plugins"]))

    def test_adapted_skill_drift_fails_without_overwriting_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            plugin = Path(temp) / "xiaoh"
            shutil.copytree(PLUGIN, plugin)
            skill = plugin / "skills/code-review/SKILL.md"
            skill.write_text(skill.read_text(encoding="utf-8") + "\ndrift\n", encoding="utf-8")
            before = skill.read_bytes()

            report = SkillGovernance(LocalFileSystem(), plugin).validate()

            self.assertEqual("failed", report["status"])
            self.assertTrue(any("code-review" in error and "digest" in error for error in report["errors"]))
            self.assertEqual(before, skill.read_bytes())

    def test_changed_upstream_commit_requires_a_new_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            plugin = Path(temp) / "xiaoh"
            shutil.copytree(PLUGIN, plugin)
            manifest = plugin / "third_party/mattpocock-skills/manifest.json"
            value = json.loads(manifest.read_text(encoding="utf-8"))
            value["source"]["commit"] = "f" * 40
            manifest.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            report = SkillGovernance(LocalFileSystem(), plugin).validate()

            self.assertEqual("failed", report["status"])
            self.assertTrue(any("new audit" in error for error in report["errors"]))

    def test_code_review_is_explicit_single_pass_and_non_mutating(self) -> None:
        text = (PLUGIN / "skills/code-review/SKILL.md").read_text(encoding="utf-8")

        for required in ("explicitly asks", "fixed point", "Review once", "Do not repair"):
            self.assertIn(required, text)
        for forbidden in ("automatically create a Campaign", "automatic re-review", "run /setup-matt"):
            self.assertNotIn(forbidden, text)

    def test_handoff_is_a_redacted_navigation_layer_not_a_second_history(self) -> None:
        text = (PLUGIN / "skills/xiaoh-core/SKILL.md").read_text(encoding="utf-8")

        for required in (
            "compact navigation layer",
            "what remains unresolved",
            "Remove tokens, credentials, private keys, cookies",
            "Suggest an available Skill only when it directly helps",
            "not a second state store",
        ):
            self.assertIn(required, text)

    def test_core_uses_risk_lanes_and_convergent_verification(self) -> None:
        text = (PLUGIN / "skills/xiaoh-core/SKILL.md").read_text(encoding="utf-8")

        for required in (
            "fast",
            "standard",
            "high_risk",
            "impact-driven verification",
            "material benefit",
            "one complete failure set",
            "verification evidence summary",
        ):
            self.assertIn(required, text)
        self.assertIn("Do not invoke `code-review` unless the user explicitly asks", text)


if __name__ == "__main__":
    unittest.main()
