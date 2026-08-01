"""XiaoH modular runtime boundary."""

from __future__ import annotations

from .common import *
from .config import *
from .automation import *

def run_codex_json(arguments: list[str]) -> tuple[dict | None, str | None]:
    codex = shutil.which("codex")
    if not codex:
        return None, "未找到Codex CLI，跳过配套插件检测"
    result = subprocess.run(
        [codex, *arguments, "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode:
        return None, (result.stderr or result.stdout).strip()
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        return None, f"Codex CLI返回了无效JSON: {error}"
    return value, None

def installed_xiaoh_plugin() -> tuple[dict | None, str | None]:
    snapshot, error = run_codex_json(["plugin", "list"])
    if error:
        return None, error
    matches = [
        item
        for item in snapshot.get("installed", [])
        if item.get("pluginId") == "xiaoh@xiaoh" and item.get("enabled")
    ]
    if len(matches) != 1:
        return None, f"无法唯一识别已启用的xiaoh插件: {len(matches)}"
    item = matches[0]
    version = item.get("version")
    if not isinstance(version, str) or not version:
        return None, "已启用的xiaoh插件缺少版本"
    return {
        "plugin_id": item["pluginId"],
        "version": version,
        "source": item.get("source"),
    }, None

def plugin_content_drift(
    loaded_root: Path,
    candidate_root: Path | None = None,
) -> list[str]:
    """Return changed, missing, extra, or symlinked managed plugin paths."""
    candidate_root = (candidate_root or PLUGIN_ROOT).expanduser().resolve()
    loaded_root = loaded_root.expanduser().resolve()
    owned = (
        ".codex-plugin",
        "scripts",
        "skills",
        "runtime",
        "third_party",
    )
    root_files = (
        "dependencies.json",
        "managed-automations.json",
        "install-manifest.json",
    )

    def managed_files(root: Path) -> dict[str, Path]:
        files: dict[str, Path] = {}
        for name in owned:
            managed_root = root / name
            if managed_root.is_symlink():
                files[name] = managed_root
                continue
            if not managed_root.is_dir():
                continue
            for path in managed_root.rglob("*"):
                relative = path.relative_to(root)
                if (
                    "__pycache__" in relative.parts
                    or path.suffix in {".pyc", ".pyo"}
                ):
                    continue
                if path.is_symlink() or path.is_file():
                    files[relative.as_posix()] = path
        for name in root_files:
            path = root / name
            if path.is_symlink() or path.is_file():
                files[name] = path
        return files

    candidate_files = managed_files(candidate_root)
    loaded_files = managed_files(loaded_root)
    drift = []
    for relative in sorted(set(candidate_files) | set(loaded_files)):
        candidate = candidate_files.get(relative)
        loaded = loaded_files.get(relative)
        if (
            candidate is None
            or loaded is None
            or candidate.is_symlink()
            or loaded.is_symlink()
            or file_hash(loaded) != file_hash(candidate)
        ):
            drift.append(relative)
    return sorted(set(drift))

def governed_skill_source_errors(dependencies: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(dependencies, dict):
        return ["依赖清单必须是对象"]
    supported_decisions = {"replace", "adapt_and_add", "absorb_method", "exclude"}
    promoted_skills = {
        "ask-matt",
        "code-review",
        "codebase-design",
        "diagnosing-bugs",
        "domain-modeling",
        "grill-with-docs",
        "implement",
        "improve-codebase-architecture",
        "prototype",
        "research",
        "resolving-merge-conflicts",
        "setup-matt-pocock-skills",
        "tdd",
        "to-spec",
        "to-tickets",
        "triage",
        "wayfinder",
        "grill-me",
        "grilling",
        "handoff",
        "teach",
        "writing-great-skills",
    }
    confirmed_source = {
        "id": "mattpocock-skills",
        "repository": "https://github.com/mattpocock/skills",
        "commit": "2ab958093e83e0ec752e6c1c5932da465bf23e0c",
        "license": "MIT",
        "copyright": "Copyright (c) 2026 Matt Pocock",
        "license_file": "third_party/mattpocock-skills/LICENSE",
        "license_sha256": (
            "0e7ac423bf2c6e223b7c5b156f8cf72da49d748e56a1641402c31f22ad07dbb5"
        ),
        "comparison_manifest": "third_party/mattpocock-skills/manifest.json",
    }
    confirmed_comparison_source = {
        "repository": "https://github.com/mattpocock/skills",
        "commit": "2ab958093e83e0ec752e6c1c5932da465bf23e0c",
        "license": "MIT",
        "copyright": "Copyright (c) 2026 Matt Pocock",
        "license_file": "LICENSE",
        "license_sha256": (
            "0e7ac423bf2c6e223b7c5b156f8cf72da49d748e56a1641402c31f22ad07dbb5"
        ),
    }
    confirmed_comparison_sha256 = (
        "e3d8a98192f86b4ec429aac066b564a80db2fb841bbd84371a5627061746bee2"
    )
    confirmed_counts = {
        "replace": 0,
        "adapt_and_add": 9,
        "absorb_method": 6,
        "exclude": 7,
    }
    confirmed_decisions = {
        "ask-matt": "absorb_method",
        "code-review": "exclude",
        "codebase-design": "adapt_and_add",
        "diagnosing-bugs": "adapt_and_add",
        "domain-modeling": "adapt_and_add",
        "grill-with-docs": "absorb_method",
        "implement": "absorb_method",
        "improve-codebase-architecture": "adapt_and_add",
        "prototype": "adapt_and_add",
        "research": "adapt_and_add",
        "resolving-merge-conflicts": "adapt_and_add",
        "setup-matt-pocock-skills": "exclude",
        "tdd": "adapt_and_add",
        "to-spec": "absorb_method",
        "to-tickets": "absorb_method",
        "triage": "exclude",
        "wayfinder": "adapt_and_add",
        "grill-me": "exclude",
        "grilling": "absorb_method",
        "handoff": "exclude",
        "teach": "exclude",
        "writing-great-skills": "exclude",
    }
    confirmed_dimensions = [
        "goal_coverage",
        "engineering_correctness",
        "user_interaction_burden",
        "compatibility_and_migration",
        "security_and_permissions",
        "evidence_and_verifiability",
        "implementation_and_operations_cost",
        "future_evolution",
    ]
    confirmed_upstream_aggregates = {
        "codebase-design": "eb0921d92984b430750d428d7161272da87e6a1585c88dbc67844d719694925c",
        "diagnosing-bugs": "22a99713ed2896d3b4ad315a12cbb5f461a024e0dc14955891d39e850c9522d2",
        "domain-modeling": "d0fd29934f2c3b3f4c93497b9fb481da82f562e0ee7b52316a776d0c2ad34830",
        "improve-codebase-architecture": "dd64bcc0abd45cd072e5978a6ae0a3d4e0a964fa456e5378151b0c313d832b0e",
        "prototype": "acc61b14f6c37d0321f1c5c0ccecec23521e01ac2e96a28afb0bb1fad4328e29",
        "research": "6698b44d94e85d06ff92588ea5205554b973b2b23d3d1ea9a0148a3ce6655d2e",
        "resolving-merge-conflicts": "96aca5d1519714ae2e2695e7ea9f3caff0de8836010e14411f4d28d6d5e8e515",
        "tdd": "76cc3e435800682c53cf5869c748976320e278a4d3e19abf79fe5f974671addf",
        "wayfinder": "2e68a02c970281a97d51762f8b5639649f0a1cfe1b8cc2b6fe16e1a549cb6837",
    }
    confirmed_absorb_targets = {
        "ask-matt": "skills/xiaoh-core/SKILL.md",
        "grill-with-docs": "skills/spec-rfc/SKILL.md and skills/domain-modeling/SKILL.md",
        "implement": "skills/xiaoh-core/SKILL.md",
        "to-spec": "skills/spec-rfc/SKILL.md",
        "to-tickets": "skills/spec-rfc/references/openspec-handoff.md",
        "grilling": "skills/spec-rfc/SKILL.md and skills/domain-modeling/SKILL.md",
    }
    confirmed_excluded_skills = {
        "setup-matt-pocock-skills",
        "code-review",
        "triage",
        "grill-me",
        "handoff",
        "teach",
        "writing-great-skills",
    }

    def plugin_member(
        relative: object, label: str, expected_kind: str
    ) -> Path | None:
        if not isinstance(relative, str):
            errors.append(f"{label}路径无效")
            return None
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            errors.append(f"{label}路径越界: {relative}")
            return None
        if PLUGIN_ROOT.is_symlink():
            errors.append(f"{label}插件根目录不能是符号链接: {PLUGIN_ROOT}")
            return None
        target = PLUGIN_ROOT / path
        cursor = PLUGIN_ROOT
        for part in path.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                errors.append(f"{label}路径包含符号链接: {cursor}")
                return None
        try:
            resolved_root = PLUGIN_ROOT.resolve(strict=True)
            resolved_target = target.resolve(strict=True)
            resolved_target.relative_to(resolved_root)
        except (OSError, RuntimeError, ValueError):
            errors.append(f"{label}缺失、越界或不可解析: {target}")
            return None
        if expected_kind == "file" and not target.is_file():
            errors.append(f"{label}缺失或不是普通文件: {target}")
            return None
        if expected_kind == "directory" and not target.is_dir():
            errors.append(f"{label}缺失或不是目录: {target}")
            return None
        return target

    sources = dependencies.get("third_party_skill_sources")
    if not isinstance(sources, list):
        return ["第三方Skill来源必须是列表"]
    if dependencies.get("schema_version") != "1.0":
        errors.append("依赖清单schema版本无效")
    try:
        plugin_version = load_json(PLUGIN_MANIFEST).get("version")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"无法读取插件版本: {exc}")
        plugin_version = None
    audited_versions = {"3.0.0", "3.1.0", "3.1.1", "3.1.2"}
    if plugin_version in audited_versions and sources != [confirmed_source]:
        errors.append(f"{plugin_version}第三方Skill来源必须精确包含确认的唯一来源")
    if plugin_version not in audited_versions:
        errors.append(
            "当前插件版本缺少可信的第三方Skill比较基线，必须失败关闭"
        )
    for source_index, source in enumerate(sources):
        if not isinstance(source, dict):
            errors.append(f"第三方Skill来源条目无效: {source_index}")
            continue
        source_id = source.get("id")
        if not isinstance(source_id, str) or not source_id:
            errors.append(f"第三方Skill来源缺少有效id: {source_index}")
            source_id = f"unknown-{source_index}"
        license_path = plugin_member(
            source.get("license_file"), f"第三方来源{source_id}许可证", "file"
        )
        comparison_path = plugin_member(
            source.get("comparison_manifest"),
            f"第三方来源{source_id}比较清单",
            "file",
        )
        if license_path and file_hash(license_path) != source.get("license_sha256"):
            errors.append(f"第三方来源{source_id}许可证摘要不匹配")
        if comparison_path is None:
            continue
        try:
            comparison = load_json(comparison_path)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"第三方来源{source_id}比较清单无效: {exc}")
            continue
        if not isinstance(comparison, dict):
            errors.append(f"第三方来源{source_id}比较清单必须是对象")
            continue
        comparison_fields = {
            "schema_version",
            "source",
            "comparison_audit",
            "comparison_dimensions",
            "replacement_policy",
            "decisions",
            "decision_evidence",
        }
        if set(comparison) != comparison_fields:
            errors.append(f"第三方来源{source_id}比较清单字段集合无效")
        if comparison.get("schema_version") != "xiaoh-third-party-skills/v1":
            errors.append(f"第三方来源{source_id}比较清单schema版本无效")
        if comparison.get("comparison_dimensions") != confirmed_dimensions:
            errors.append(f"第三方来源{source_id}比较维度与确认基线不匹配")
        declared_source = comparison.get("source")
        if not isinstance(declared_source, dict):
            errors.append(f"第三方来源{source_id}来源信息无效")
            continue
        if plugin_version in audited_versions:
            if declared_source != confirmed_comparison_source:
                errors.append(f"第三方来源{source_id}比较清单来源与确认基线不匹配")
            if file_hash(comparison_path) != confirmed_comparison_sha256:
                errors.append(f"第三方来源{source_id}比较清单摘要与确认基线不匹配")
        for field in ("repository", "commit", "license", "copyright", "license_sha256"):
            if declared_source.get(field) != source.get(field):
                errors.append(f"第三方来源{source_id}字段不一致: {field}")
        audit = comparison.get("comparison_audit", {})
        audit_fields = {
            "audit_id",
            "target_version",
            "audited",
            "fixed_source_commit",
            "expected_counts",
            "future_source_policy",
        }
        if (
            not isinstance(audit, dict)
            or set(audit) != audit_fields
            or audit.get("audited") is not True
            or not isinstance(audit.get("audit_id"), str)
            or not audit.get("audit_id").strip()
            or not isinstance(audit.get("target_version"), str)
            or not audit.get("target_version").strip()
            or not isinstance(audit.get("fixed_source_commit"), str)
            or not audit.get("fixed_source_commit").strip()
        ):
            errors.append(f"第三方来源{source_id}缺少已确认比较基线")
            audit = {}
        if audit.get("fixed_source_commit") != declared_source.get("commit"):
            errors.append(f"第三方来源{source_id}比较基线未绑定固定提交")
        expected_audit_version = plugin_version
        if audit.get("target_version") != expected_audit_version:
            errors.append(f"第三方来源{source_id}比较基线目标版本不匹配")
        if plugin_version in audited_versions:
            actual_source = {
                field: source.get(field) for field in confirmed_source
            }
            if actual_source != confirmed_source:
                errors.append(
                    f"第三方来源{source_id}未绑定固定来源身份"
                )
        future_policy = audit.get("future_source_policy", {})
        future_policy_fields = {
            "new_audit_required",
            "counts_must_be_recomputed",
            "prior_zero_replacement_count_is_not_inherited",
        }
        if not (
            isinstance(future_policy, dict)
            and set(future_policy) == future_policy_fields
            and future_policy.get("new_audit_required") is True
            and future_policy.get("counts_must_be_recomputed") is True
            and future_policy.get("prior_zero_replacement_count_is_not_inherited")
            is True
        ):
            errors.append(f"第三方来源{source_id}缺少未来版本重新评估策略")
        replacement_policy = comparison.get("replacement_policy")
        if (
            not isinstance(replacement_policy, dict)
            or set(replacement_policy)
            != {"hard_gates", "minimum_confirmed_product_benefits"}
        ):
            errors.append(f"第三方来源{source_id}替换策略无效")
            replacement_policy = {}
        hard_gates = replacement_policy.get("hard_gates", [])
        if (
            not isinstance(hard_gates, list)
            or any(not isinstance(gate, str) for gate in hard_gates)
            or len(set(hard_gates)) != len(hard_gates)
            or set(hard_gates)
            != {"compatibility", "security", "permissions", "evidence"}
        ):
            errors.append(f"第三方来源{source_id}替换硬门禁不完整")
            hard_gates = []
        minimum_benefits = replacement_policy.get(
            "minimum_confirmed_product_benefits"
        )
        if (
            not isinstance(minimum_benefits, int)
            or isinstance(minimum_benefits, bool)
            or minimum_benefits != 1
        ):
            errors.append(f"第三方来源{source_id}替换收益门槛无效")
            minimum_benefits = 1
        decisions = comparison.get("decisions")
        if not isinstance(decisions, list):
            errors.append(f"第三方来源{source_id}缺少逐项比较")
            continue
        names = [
            item.get("skill")
            for item in decisions
            if isinstance(item, dict) and isinstance(item.get("skill"), str)
        ]
        if len(decisions) != 22 or len(set(names)) != 22:
            errors.append(f"第三方来源{source_id}逐项比较必须唯一覆盖22个Skill")
        counts = {
            decision: sum(
                item.get("decision") == decision
                for item in decisions
                if isinstance(item, dict)
            )
            for decision in supported_decisions
        }
        expected_counts = audit.get("expected_counts")
        if (
            not isinstance(expected_counts, dict)
            or set(expected_counts) != supported_decisions
            or any(
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
                for value in expected_counts.values()
            )
            or sum(expected_counts.values()) != len(promoted_skills)
        ):
            errors.append(f"第三方来源{source_id}比较分类计数无效")
            expected_counts = {}
        if counts != expected_counts:
            errors.append(f"第三方来源{source_id}分类计数不匹配: {counts}")
        if (
            declared_source.get("commit") == confirmed_source["commit"]
            and counts != confirmed_counts
        ):
            errors.append(f"第三方来源{source_id}当前固定提交分类基线不匹配")
        actual_decisions = {
            item.get("skill"): item.get("decision")
            for item in decisions
            if isinstance(item, dict)
            and isinstance(item.get("skill"), str)
            and isinstance(item.get("decision"), str)
        }
        if plugin_version in audited_versions and actual_decisions != confirmed_decisions:
            errors.append(f"第三方来源{source_id}逐项决策与确认基线不匹配")
        excluded_skills = {
            item.get("skill")
            for item in decisions
            if isinstance(item, dict) and item.get("decision") == "exclude"
        }
        if (
            declared_source.get("commit") == confirmed_source["commit"]
            and excluded_skills != confirmed_excluded_skills
        ):
            errors.append(f"第三方来源{source_id}固定提交排除Skill集合不匹配")
        bundled_skills = dependencies.get("bundled_skills")
        if (
            not isinstance(bundled_skills, list)
            or any(not isinstance(skill, str) for skill in bundled_skills)
            or len(bundled_skills) != len(set(bundled_skills))
        ):
            errors.append("受管Skill注册必须是无重复字符串列表")
            bundled_skills = []
        for excluded_skill in sorted(confirmed_excluded_skills):
            excluded_path = PLUGIN_ROOT / "skills" / excluded_skill
            if excluded_path.exists() or excluded_path.is_symlink():
                errors.append(
                    f"第三方来源{source_id}排除Skill不得进入受管发布: "
                    f"{excluded_skill}"
                )
            if excluded_skill in bundled_skills:
                errors.append(
                    f"第三方来源{source_id}排除Skill不得注册为受管Skill: "
                    f"{excluded_skill}"
                )
        missing_adapted = sorted(
            {
                skill
                for skill, decision in confirmed_decisions.items()
                if decision == "adapt_and_add"
            }
            - set(bundled_skills)
        )
        if missing_adapted:
            errors.append(
                f"第三方来源{source_id}适配Skill未全部注册: {missing_adapted}"
            )
        if set(names) != promoted_skills:
            missing = sorted(promoted_skills - set(names))
            unexpected = sorted(set(names) - promoted_skills)
            errors.append(
                f"第三方来源{source_id}promoted Skill集合不匹配: "
                f"missing={missing}, unexpected={unexpected}"
            )
        evidence = comparison.get("decision_evidence")
        if not isinstance(evidence, dict) or set(evidence) != set(names):
            errors.append(f"第三方来源{source_id}逐项证据未唯一覆盖22个Skill")
            evidence = {}
        for item in decisions:
            if not isinstance(item, dict):
                errors.append(f"第三方来源{source_id}逐项比较条目无效")
                continue
            skill = item.get("skill")
            decision = item.get("decision")
            if not isinstance(skill, str):
                errors.append(f"第三方来源{source_id}逐项Skill名称无效")
                continue
            if not isinstance(decision, str) or decision not in supported_decisions:
                errors.append(
                    f"第三方来源{source_id}包含未知分类: {skill}: {decision}"
                )
                continue
            expected_item_fields = {
                "adapt_and_add": {
                    "skill",
                    "decision",
                    "files",
                    "upstream_aggregate_sha256",
                    "adapted_aggregate_sha256",
                    "reason",
                },
                "absorb_method": {"skill", "decision", "target", "reason"},
                "exclude": {"skill", "decision", "reason"},
                "replace": {
                    "skill",
                    "decision",
                    "replacement_assessment",
                    "reason",
                },
            }.get(decision)
            if expected_item_fields and set(item) != expected_item_fields:
                errors.append(f"第三方来源{source_id}逐项比较字段集合无效: {skill}")
            reason = item.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                errors.append(f"第三方来源{source_id}逐项理由无效: {skill}")
            decision_evidence = evidence.get(skill, {})
            expected_status = {
                "adapt_and_add": "adapted_and_forward_tested",
                "absorb_method": "absorbed_and_contract_tested",
                "exclude": "excluded",
                "replace": "replacement_audited_and_benefit_confirmed",
            }.get(decision)
            if not (
                isinstance(decision_evidence, dict)
                and set(decision_evidence) == {"status", "evidence_basis"}
                and isinstance(decision_evidence.get("status"), str)
                and decision_evidence.get("status").strip()
                and isinstance(decision_evidence.get("evidence_basis"), str)
                and decision_evidence.get("evidence_basis").strip()
            ):
                errors.append(f"第三方来源{source_id}逐项证据无效: {skill}")
            elif expected_status and decision_evidence.get("status") != expected_status:
                errors.append(f"第三方来源{source_id}逐项证据状态与决策不匹配: {skill}")
            if (
                decision == "absorb_method"
                and plugin_version in audited_versions
                and item.get("target") != confirmed_absorb_targets.get(skill)
            ):
                errors.append(f"第三方来源{source_id}吸收目标与确认基线不匹配: {skill}")
            if decision == "replace":
                assessment = item.get("replacement_assessment", {})
                if (
                    not isinstance(assessment, dict)
                    or set(assessment)
                    != {"hard_gates", "confirmed_product_benefits"}
                ):
                    errors.append(
                        f"第三方来源{source_id}替换证据结构无效: {skill}"
                    )
                    assessment = {}
                gate_results = assessment.get("hard_gates", {})
                benefits = assessment.get("confirmed_product_benefits", [])
                if (
                    not isinstance(gate_results, dict)
                    or set(gate_results) != set(hard_gates)
                    or not all(value is True for value in gate_results.values())
                    or not isinstance(benefits, list)
                    or any(
                        not isinstance(benefit, str) or not benefit.strip()
                        for benefit in benefits
                    )
                    or len(benefits) < minimum_benefits
                ):
                    errors.append(f"第三方来源{source_id}替换证据未通过硬门禁: {skill}")
            if decision != "adapt_and_add":
                continue
            if (
                plugin_version in audited_versions
                and item.get("upstream_aggregate_sha256")
                != confirmed_upstream_aggregates.get(skill)
            ):
                errors.append(f"第三方来源{source_id}上游Skill摘要与确认基线不匹配: {skill}")
            files = item.get("files")
            if not isinstance(skill, str) or not isinstance(files, list):
                errors.append(f"第三方来源{source_id}适配Skill清单无效")
                continue
            if (
                any(not isinstance(relative, str) for relative in files)
                or len(set(files)) != len(files)
                or any(
                    Path(relative).is_absolute() or ".." in Path(relative).parts
                    for relative in files
                )
            ):
                errors.append(
                    f"第三方来源{source_id}适配Skill文件清单无效: {skill}"
                )
                continue
            skill_root = plugin_member(
                f"skills/{skill}",
                f"第三方来源{source_id}适配Skill",
                "directory",
            )
            actual_files: list[str] = []
            unsafe = False
            if skill_root is None:
                continue
            for path in skill_root.rglob("*"):
                if path.is_symlink():
                    errors.append(f"第三方来源{source_id}适配Skill包含符号链接: {path}")
                    unsafe = True
                elif path.is_file():
                    actual_files.append(path.relative_to(skill_root).as_posix())
            if unsafe:
                continue
            if sorted(files) != sorted(actual_files):
                errors.append(f"第三方来源{source_id}适配Skill文件清单漂移: {skill}")
                continue
            digest_lines = "".join(
                f"{file_hash(skill_root / relative)}  {relative}\n"
                for relative in sorted(files)
            )
            digest = hashlib.sha256(digest_lines.encode()).hexdigest()
            if digest != item.get("adapted_aggregate_sha256"):
                errors.append(f"第三方来源{source_id}适配Skill摘要漂移: {skill}")
            skill_file = skill_root / "SKILL.md"
            try:
                skill_text = skill_file.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                errors.append(f"第三方来源{source_id}适配Skill入口不可读: {skill}: {exc}")
            else:
                frontmatter = re.match(r"^---\n(.*?)\n---\n", skill_text, re.S)
                identity = None
                if frontmatter:
                    for line in frontmatter.group(1).splitlines():
                        key, separator, value = line.partition(":")
                        if separator and key.strip() == "name":
                            identity = value.strip().strip("\"'")
                            break
                if identity != skill:
                    errors.append(f"第三方来源{source_id}适配Skill身份不匹配: {skill}")
    return errors

def governed_install_asset_errors() -> list[str]:
    """Validate the exact clean-install asset inventory for this plugin."""
    manifest_path = PLUGIN_ROOT / "install-manifest.json"
    try:
        manifest = load_json(manifest_path)
        dependencies = load_json(DEPENDENCY_MANIFEST)
        plugin = load_json(PLUGIN_MANIFEST)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return [f"安装资产清单无效: {exc}"]
    errors: list[str] = []
    expected_fields = {
        "schema_version",
        "version",
        "managed_runtime_directories",
        "bundled_skills",
        "managed_agents",
    }
    if set(manifest) != expected_fields:
        errors.append("安装清单字段集合无效")
    if manifest.get("schema_version") != "xiaoh-install-manifest/v1":
        errors.append("安装清单schema版本无效")
    if manifest.get("version") != plugin.get("version"):
        errors.append("安装清单版本与插件版本不一致")
    if manifest.get("managed_runtime_directories") != [
        "agents", "contexts", "agent-system", "hooks"
    ]:
        errors.append("安装清单受管目录无效")
    if manifest.get("bundled_skills") != dependencies.get("bundled_skills"):
        errors.append("安装清单Skill与依赖清单不一致")
    if set(manifest.get("managed_agents", [])) != REQUIRED_AGENTS:
        errors.append("安装清单Agent与运行时清单不一致")
    for skill in manifest.get("bundled_skills", []):
        if not isinstance(skill, str) or not (PLUGIN_ROOT / "skills" / skill / "SKILL.md").is_file():
            errors.append(f"安装清单Skill缺失: {skill}")
    for agent in manifest.get("managed_agents", []):
        if not isinstance(agent, str) or not (RUNTIME / "codex/agents" / f"{agent}.toml").is_file():
            errors.append(f"安装清单Agent缺失: {agent}")
    return errors

def companion_report(install_missing: bool = False) -> dict:
    manifest = load_json(DEPENDENCY_MANIFEST)
    warnings: list[str] = []
    governance_errors = (
        governed_skill_source_errors(manifest)
        + governed_install_asset_errors()
    )
    errors = list(governance_errors)
    installed_now: list[str] = []
    plugins: list[dict] = []

    plugin_snapshot, plugin_error = run_codex_json(["plugin", "list"])
    marketplace_snapshot, marketplace_error = run_codex_json(["plugin", "marketplace", "list"])
    if plugin_error:
        warnings.append(plugin_error)
        installed_ids: set[str] = set()
    else:
        installed_ids = {
            item["pluginId"]
            for item in plugin_snapshot.get("installed", [])
            if item.get("enabled")
        }
    if marketplace_error:
        marketplace_names: set[str] = set()
    else:
        marketplace_names = {
            item["name"] for item in marketplace_snapshot.get("marketplaces", [])
        }

    for dependency in manifest["codex_plugins"]:
        plugin_id = dependency["id"]
        marketplace = plugin_id.rsplit("@", 1)[-1]
        installed = plugin_id in installed_ids
        detail = {**dependency, "status": "installed" if installed else "missing"}
        if (
            not installed
            and install_missing
            and not governance_errors
            and dependency.get("auto_install")
            and not plugin_error
        ):
            source = dependency.get("marketplace_source")
            if source and marketplace not in marketplace_names:
                arguments = ["plugin", "marketplace", "add", source]
                if dependency.get("marketplace_ref"):
                    arguments.extend(["--ref", dependency["marketplace_ref"]])
                _, error = run_codex_json(arguments)
                if error:
                    detail["install_error"] = error
                else:
                    marketplace_names.add(marketplace)
            if not detail.get("install_error"):
                _, error = run_codex_json(["plugin", "add", plugin_id])
                if error:
                    detail["install_error"] = error
                else:
                    detail["status"] = "installed"
                    installed_ids.add(plugin_id)
                    installed_now.append(plugin_id)
        if detail["status"] != "installed":
            message = f"配套插件不可用: {plugin_id}（{dependency['purpose']}）"
            if detail.get("install_error"):
                message += f": {detail['install_error']}"
            if dependency["level"] == "required":
                errors.append(message)
            elif dependency["level"] == "recommended":
                warnings.append(message)
        plugins.append(detail)

    external: list[dict] = []
    for dependency in manifest.get("external_capabilities", []):
        available = any(shutil.which(command) for command in dependency.get("commands", []))
        detail = {**dependency, "status": "available" if available else "missing"}
        if not available:
            message = f"外部增强能力不可用: {dependency['id']}（{dependency['purpose']}）"
            if dependency["level"] == "required":
                errors.append(message)
            elif dependency["level"] == "recommended":
                warnings.append(message)
        external.append(detail)

    return {
        "status": "failed" if errors else ("degraded" if warnings else "complete"),
        "bundled_skills": manifest["bundled_skills"],
        "third_party_skill_sources": manifest.get("third_party_skill_sources", []),
        "plugins": plugins,
        "external_capabilities": external,
        "installed_now": installed_now,
        "warnings": list(dict.fromkeys(warnings)),
        "errors": errors,
    }

def playbook_adapter_report(
    local: dict, playbook_command: str = "playbook"
) -> dict:
    mode = integration_mode(local, "playbook")
    adapter = RUNTIME / "codex/agent-system/playbook_adapter.py"
    if not adapter.is_file():
        return {
            "status": "missing",
            "mode": mode,
            "version": None,
            "errors": [f"缺少xiaoh Playbook适配器: {adapter}"],
        }
    if mode == "disabled":
        return {
            "status": "not_enabled",
            "mode": mode,
            "command": playbook_command,
            "version": None,
            "worker_json_contract": False,
            "task_status_contract": False,
            "errors": [],
        }
    executable = shutil.which(playbook_command)
    if not executable:
        return {
            "status": "not_enabled" if mode == "auto" else "missing",
            "mode": mode,
            "command": playbook_command,
            "version": None,
            "worker_json_contract": False,
            "task_status_contract": False,
            "errors": (
                [] if mode == "auto"
                else [f"未找到Playbook命令: {playbook_command}"]
            ),
        }
    completed = subprocess.run(
        [
            sys.executable,
            str(adapter),
            "probe",
            "--mode",
            mode,
            "--playbook-command",
            executable,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "status": "incompatible",
            "mode": mode,
            "version": None,
            "errors": [(completed.stderr or completed.stdout).strip() or "适配器未返回JSON"],
        }
    if not isinstance(result, dict):
        return {
            "status": "incompatible",
            "mode": mode,
            "version": None,
            "errors": ["适配器返回值不是JSON对象"],
        }
    return result

def playbook_version_policy_report(active_agents: Path) -> dict:
    bundled_agents = RUNTIME / "codex/AGENTS.md"
    heading = PLAYBOOK_VERSION_POLICY_FRAGMENTS[0]
    bundled_text = (
        bundled_agents.read_text(encoding="utf-8")
        if bundled_agents.is_file()
        else ""
    )
    bundled_contract = marked_block(
        bundled_text, "global-agent-common-contract"
    )
    canonical_section = markdown_section(bundled_contract or "", heading)
    files = []
    errors = []
    for label, path in (
        ("bundled", bundled_agents),
        ("active", active_agents),
    ):
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        contract = marked_block(text, "global-agent-common-contract")
        section = markdown_section(contract or "", heading)
        missing = [
            fragment
            for fragment in PLAYBOOK_VERSION_POLICY_FRAGMENTS
            if fragment not in (section or "")
        ]
        section_matches = (
            canonical_section is not None and section == canonical_section
        )
        if missing:
            errors.append(
                f"{label} AGENTS缺少Playbook CLI版本维护边界: "
                + ", ".join(missing)
            )
        elif not section_matches:
            errors.append(
                f"{label} AGENTS的Playbook CLI版本维护边界与捆绑规范不一致"
            )
        files.append(
            {
                "kind": label,
                "path": str(path),
                "status": (
                    "complete"
                    if not missing and section_matches
                    else "missing"
                ),
                "inside_managed_contract": contract is not None and section is not None,
                "matches_bundled_section": section_matches,
                "missing_fragments": missing,
            }
        )
    return {
        "status": "complete" if not errors else "missing",
        "mechanical_gate": False,
        "files": files,
        "errors": errors,
    }
