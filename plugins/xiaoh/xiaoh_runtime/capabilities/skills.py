"""Manifest-driven third-party Skill and Skill-quality governance."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..ports.protocols import FileSystemPort


DECISIONS = frozenset({"replace", "adapt_and_add", "absorb_method", "exclude"})
EXPECTED_FIXED_COUNTS = {
    "replace": 0,
    "adapt_and_add": 10,
    "absorb_method": 8,
    "exclude": 4,
}
SHA256 = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")


class SkillGovernance:
    def __init__(self, filesystem: FileSystemPort, plugin_root: Path):
        self.fs = filesystem
        self.plugin_root = filesystem.resolve(plugin_root)

    def validate(self) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []
        dependencies = self._load_object(self.plugin_root / "dependencies.json", errors)
        if dependencies.get("schema_version") != "xiaoh-dependencies/v2":
            errors.append("dependencies schema is not supported")
        companion_plugins = dependencies.get("codex_plugins", [])
        if not isinstance(companion_plugins, list):
            errors.append("codex_plugins must be a list")
        elif any(
            not isinstance(item, dict) or item.get("auto_install") is not False
            for item in companion_plugins
        ):
            errors.append("companion plugins must remain manual-install recommendations")
        plugin = self._load_object(
            self.plugin_root / ".codex-plugin/plugin.json", errors
        )
        bundled = dependencies.get("bundled_skills", [])
        if not _unique_strings(bundled):
            errors.append("dependencies bundled_skills must be unique strings")
            bundled = []
        sources = dependencies.get("third_party_skill_sources", [])
        if not isinstance(sources, list) or not sources:
            errors.append("third-party Skill sources must be a non-empty list")
            sources = []
        aggregate_counts = {decision: 0 for decision in DECISIONS}
        audited_skills: list[str] = []
        for source in sources:
            if not isinstance(source, dict):
                errors.append("third-party Skill source must be an object")
                continue
            source_id = source.get("id", "unknown")
            license_path = self._member(source.get("license_file"), errors, f"{source_id} license")
            manifest_path = self._member(
                source.get("comparison_manifest"), errors, f"{source_id} manifest"
            )
            if license_path is not None:
                actual_license = self.fs.digest(license_path)
                if actual_license != source.get("license_sha256"):
                    errors.append(f"{source_id} license digest mismatch")
            if manifest_path is None:
                continue
            manifest = self._load_object(manifest_path, errors)
            counts, names = self._validate_manifest(
                source,
                manifest,
                plugin.get("version"),
                set(bundled),
                errors,
            )
            aggregate_counts = {
                decision: aggregate_counts[decision] + counts.get(decision, 0)
                for decision in DECISIONS
            }
            audited_skills.extend(names)
        quality = self.audit_quality(bundled)
        errors.extend(quality["errors"])
        warnings.extend(quality["warnings"])
        return {
            "status": "failed" if errors else ("degraded" if warnings else "passed"),
            "schema_version": "xiaoh-skill-governance-report/v1",
            "decision_counts": {
                key: aggregate_counts[key]
                for key in ("replace", "adapt_and_add", "absorb_method", "exclude")
            },
            "audited_skills": sorted(set(audited_skills)),
            "quality": quality,
            "errors": list(dict.fromkeys(errors)),
            "warnings": list(dict.fromkeys(warnings)),
        }

    def audit_quality(self, bundled: Iterable[str]) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []
        entries: list[dict[str, Any]] = []
        content_owners: dict[str, str] = {}
        for name in sorted(bundled):
            skill_root = self.plugin_root / "skills" / name
            skill_file = skill_root / "SKILL.md"
            item_errors: list[str] = []
            if not self.fs.is_file(skill_file):
                item_errors.append("missing SKILL.md")
                text = ""
            else:
                text = self.fs.read_text(skill_file)
                identity, description, fields = _frontmatter(text)
                if fields != {"name", "description"}:
                    item_errors.append("frontmatter must contain only name and description")
                if identity != name:
                    item_errors.append("frontmatter name does not match folder")
                if not description or len(description.strip()) < 20:
                    item_errors.append("description does not define a useful invocation condition")
                elif re.search(
                    r"(?i)\b(use(?: only)? when|use for|when the user|after|before)\b|当|用户|需要|用于",
                    description,
                ) is None:
                    item_errors.append("description does not state when the Skill should be used")
                if "[TODO" in text or "TODO:" in text:
                    item_errors.append("Skill contains unfinished TODO text")
                body = text.split("---", 2)[-1].strip()
                if len(body) < 120:
                    item_errors.append("Skill is a pure alias or lacks executable guidance")
                if re.search(
                    r"(?i)\b(report|return|output|write|deliver|complete|stop|record|produce|verify)\b|"
                    r"报告|输出|写入|完成|验证|记录|收口|返回|停止",
                    body,
                ) is None:
                    item_errors.append("Skill lacks an observable completion or output rule")
                if len(body) > 12000 and not self.fs.is_dir(skill_root / "references"):
                    item_errors.append("large Skill lacks progressive-disclosure references")
                if re.search(r"(?i)\b(TODO|FIXME)\b|3\.1\.2|2\.18\.0", body):
                    item_errors.append("Skill contains stale or unfinished sediment")
                digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
                if digest in content_owners:
                    item_errors.append(
                        f"duplicates authoritative body of {content_owners[digest]}"
                    )
                else:
                    content_owners[digest] = name
            errors.extend(f"Skill {name}: {message}" for message in item_errors)
            entries.append(
                {
                    "skill": name,
                    "status": "failed" if item_errors else "passed",
                    "checks": {
                        "responsibility": "passed",
                        "invocation": "passed",
                        "completion": "passed",
                        "single_source": "passed",
                        "progressive_disclosure": "passed",
                        "sediment": "passed",
                    }
                    if not item_errors
                    else {},
                    "errors": item_errors,
                }
            )
        return {
            "status": "failed" if errors else ("degraded" if warnings else "passed"),
            "skills": entries,
            "errors": errors,
            "warnings": warnings,
        }

    def _validate_manifest(
        self,
        dependency_source: Mapping[str, Any],
        manifest: Mapping[str, Any],
        plugin_version: Any,
        bundled: set[str],
        errors: list[str],
    ) -> tuple[dict[str, int], list[str]]:
        source_id = dependency_source.get("id", "unknown")
        if manifest.get("schema_version") != "xiaoh-third-party-skills/v2":
            errors.append(f"{source_id} third-party manifest schema is invalid")
        source = manifest.get("source")
        if not isinstance(source, dict):
            errors.append(f"{source_id} source facts must be an object")
            source = {}
        for field in (
            "repository",
            "commit",
            "license",
            "copyright",
            "license_sha256",
        ):
            if source.get(field) != dependency_source.get(field):
                errors.append(f"{source_id} source field mismatch: {field}")
        if COMMIT.fullmatch(str(source.get("commit", ""))) is None:
            errors.append(f"{source_id} source commit is not a fixed SHA")
        audit = manifest.get("comparison_audit")
        if not isinstance(audit, dict):
            errors.append(f"{source_id} comparison audit must be an object")
            audit = {}
        if audit.get("audited") is not True:
            errors.append(f"{source_id} comparison audit is not accepted")
        if audit.get("fixed_source_commit") != source.get("commit"):
            errors.append(f"{source_id} source commit changed; new audit required")
        if audit.get("target_version") != plugin_version:
            errors.append(f"{source_id} audit target does not match plugin version")
        future = audit.get("future_source_policy")
        if not isinstance(future, dict) or any(
            future.get(key) is not True
            for key in (
                "new_audit_required",
                "counts_must_be_recomputed",
                "prior_zero_replacement_count_is_not_inherited",
            )
        ):
            errors.append(f"{source_id} future-source re-audit policy is incomplete")
        dimensions = manifest.get("comparison_dimensions")
        if (
            not isinstance(dimensions, list)
            or not _unique_strings(dimensions)
            or len(dimensions) < 4
        ):
            errors.append(f"{source_id} comparison dimensions are incomplete")
        decisions = manifest.get("decisions")
        if not isinstance(decisions, list):
            errors.append(f"{source_id} decisions must be a list")
            decisions = []
        names: list[str] = []
        counts = {decision: 0 for decision in DECISIONS}
        evidence = manifest.get("decision_evidence")
        if not isinstance(evidence, dict):
            errors.append(f"{source_id} decision evidence must be an object")
            evidence = {}
        for item in decisions:
            if not isinstance(item, dict):
                errors.append(f"{source_id} decision must be an object")
                continue
            skill = item.get("skill")
            decision = item.get("decision")
            if not isinstance(skill, str) or not skill:
                errors.append(f"{source_id} decision has invalid Skill name")
                continue
            names.append(skill)
            if decision not in DECISIONS:
                errors.append(f"{source_id} has unsupported decision: {skill}: {decision}")
                continue
            counts[decision] += 1
            if not isinstance(item.get("reason"), str) or not item["reason"].strip():
                errors.append(f"{source_id} decision lacks reason: {skill}")
            evidence_item = evidence.get(skill)
            if not isinstance(evidence_item, dict) or not evidence_item.get("evidence_basis"):
                errors.append(f"{source_id} decision lacks evidence: {skill}")
            if decision == "adapt_and_add":
                self._validate_adapted(source_id, skill, item, bundled, errors)
            elif decision == "absorb_method":
                self._validate_absorbed(source_id, skill, item, errors)
            elif decision == "exclude":
                if skill in bundled or self.fs.exists(self.plugin_root / "skills" / skill):
                    errors.append(f"{source_id} excluded Skill is bundled: {skill}")
            elif decision == "replace":
                assessment = item.get("replacement_assessment")
                if not isinstance(assessment, dict):
                    errors.append(f"{source_id} replacement lacks assessment: {skill}")
        if len(names) != len(set(names)):
            errors.append(f"{source_id} decisions contain duplicate Skill names")
        if set(evidence) != set(names):
            errors.append(f"{source_id} evidence does not exactly cover decisions")
        expected = audit.get("expected_counts")
        if counts != expected:
            errors.append(f"{source_id} decision counts do not match the audit")
        if source.get("commit") == dependency_source.get("commit") and counts != EXPECTED_FIXED_COUNTS:
            errors.append(f"{source_id} unchanged commit does not match accepted 4.0.0 counts")
        return counts, names

    def _validate_adapted(
        self,
        source_id: Any,
        skill: str,
        item: Mapping[str, Any],
        bundled: set[str],
        errors: list[str],
    ) -> None:
        if skill not in bundled:
            errors.append(f"{source_id} adapted Skill is not bundled: {skill}")
        files = item.get("files")
        if not isinstance(files, list) or not _unique_strings(files):
            errors.append(f"{source_id} adapted file list is invalid: {skill}")
            return
        root = self.plugin_root / "skills" / skill
        actual = sorted(
            path.relative_to(root).as_posix()
            for path in self.fs.iter_files(root)
        )
        if sorted(files) != actual:
            errors.append(f"{source_id} adapted file inventory drift: {skill}")
            return
        for relative in files:
            if _unsafe_relative(relative):
                errors.append(f"{source_id} adapted path escapes Skill root: {skill}: {relative}")
                return
        digest = _aggregate_digest(self.fs, root, files)
        if digest != item.get("adapted_aggregate_sha256"):
            errors.append(f"{source_id} adapted digest mismatch: {skill}")
        if SHA256.fullmatch(str(item.get("upstream_aggregate_sha256", ""))) is None:
            errors.append(f"{source_id} upstream digest is invalid: {skill}")

    def _validate_absorbed(
        self,
        source_id: Any,
        skill: str,
        item: Mapping[str, Any],
        errors: list[str],
    ) -> None:
        target = item.get("target")
        if not isinstance(target, str) or not target.strip():
            errors.append(f"{source_id} absorbed method lacks target: {skill}")
            return
        for relative in (part.strip() for part in target.split(" and ")):
            if _unsafe_relative(relative) or not self.fs.exists(self.plugin_root / relative):
                errors.append(f"{source_id} absorbed target is invalid: {skill}: {relative}")

    def _member(
        self, relative: Any, errors: list[str], label: str
    ) -> Path | None:
        if not isinstance(relative, str) or _unsafe_relative(relative):
            errors.append(f"{label} path is invalid")
            return None
        target = self.plugin_root / relative
        if self.fs.is_symlink(target) or not self.fs.is_file(target):
            errors.append(f"{label} file is missing or unsafe")
            return None
        try:
            target.resolve(strict=True).relative_to(self.plugin_root.resolve(strict=True))
        except (OSError, RuntimeError, ValueError):
            errors.append(f"{label} path escapes plugin root")
            return None
        return target

    def _load_object(self, path: Path, errors: list[str]) -> dict[str, Any]:
        try:
            value = json.loads(self.fs.read_text(path))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"invalid JSON document {path}: {exc}")
            return {}
        if not isinstance(value, dict):
            errors.append(f"JSON document must be an object: {path}")
            return {}
        return value


def _frontmatter(text: str) -> tuple[str | None, str | None, set[str]]:
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if match is None:
        return None, None, set()
    values: dict[str, str] = {}
    current_key: str | None = None
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if separator:
            current_key = key.strip()
            values[current_key] = value.strip().strip("'\"")
        elif current_key is not None and line[:1].isspace():
            values[current_key] = (values[current_key] + " " + line.strip()).strip()
    if values.get("description") in {">", ">-", "|", "|-"}:
        values["description"] = ""
    return values.get("name"), values.get("description"), set(values)


def _unique_strings(value: Any) -> bool:
    return (
        isinstance(value, list)
        and all(isinstance(item, str) and item for item in value)
        and len(value) == len(set(value))
    )


def _unsafe_relative(value: str) -> bool:
    path = Path(value)
    return path.is_absolute() or ".." in path.parts


def _aggregate_digest(
    filesystem: FileSystemPort, root: Path, files: Iterable[str]
) -> str:
    lines = "".join(
        f"{filesystem.digest(root / relative)}  {relative}\n"
        for relative in sorted(files)
    )
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()
