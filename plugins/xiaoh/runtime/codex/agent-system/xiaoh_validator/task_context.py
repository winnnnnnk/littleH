"""Task-context and requirement lifecycle validation."""

from datetime import datetime, timezone
from pathlib import Path
import re

from xiaoh_validator.policy import (
    ALLOWED_DELEGATION_DECISIONS,
    ALLOWED_EXECUTION_LANES,
    ALLOWED_EFFECT_LEVELS,
    ALLOWED_INTENT_DOMAINS,
    ALLOWED_REQUIREMENT_GATE_ACTIONS,
    ALLOWED_RISK_LEVELS,
    ALLOWED_TASK_TYPES,
    ALLOWED_VERIFICATION_SCOPES,
    ALLOWED_VERIFICATION_CATEGORIES,
    MAX_CONTEXT_AGE_HOURS,
    REGISTERED_AGENTS,
    ROOT_AGENT,
)
from xiaoh_validator.evidence import (
    parse_timestamp,
    path_is_covered,
    path_sha256,
    require_keys,
    validate_string_list,
)
from xiaoh_validator.requirements import validate_memory_recall, validate_requirements
from xiaoh_validator.delegation import validate_interaction_gate


SHA256_RE = re.compile(r"[0-9a-f]{64}")


def _validate_task_shape(data, report, check_paths):
    behavior = data.get("behavior")
    if require_keys(behavior, ["current", "target"], "behavior", report):
        for key in ("current", "target"):
            if not isinstance(behavior[key], str) or not behavior[key].strip():
                report.error("behavior.{} must be a non-empty string".format(key))

    scope = data.get("scope")
    task_allowed = []
    if require_keys(
        scope,
        ["workspace", "repositories", "allowed_paths", "preexisting_changes", "prohibited_actions"],
        "scope",
        report,
    ):
        workspace = scope["workspace"]
        if not isinstance(workspace, str) or not workspace.strip():
            report.error("scope.workspace must be a non-empty string")
        elif check_paths and not Path(workspace).expanduser().is_absolute():
            report.error("scope.workspace must be an absolute path")
        for key in ("repositories", "allowed_paths", "preexisting_changes"):
            values = validate_string_list(
                scope[key], "scope.{}".format(key), report, non_empty=key == "allowed_paths"
            )
            for value in values:
                if check_paths and not Path(value).expanduser().is_absolute():
                    report.error("scope.{} must contain absolute paths".format(key))
            if key == "allowed_paths":
                task_allowed = values
        validate_string_list(
            scope["prohibited_actions"], "scope.prohibited_actions", report, non_empty=True
        )
        for path in scope.get("preexisting_changes", []):
            if isinstance(path, str) and not path_is_covered(path, task_allowed):
                report.error("scope.preexisting_changes must be inside scope.allowed_paths")

    sources = data.get("sources")
    if not isinstance(sources, list) or not sources:
        report.error("sources must be a non-empty list")
    else:
        for index, source in enumerate(sources):
            label = "sources[{}]".format(index)
            if not require_keys(source, ["path", "purpose", "required", "kind", "sha256"], label, report):
                continue
            for key in ("path", "purpose"):
                if not isinstance(source[key], str) or not source[key].strip():
                    report.error("{}.{} must be a non-empty string".format(label, key))
            if not isinstance(source["kind"], str) or source["kind"] not in {"file", "directory"}:
                report.error("{}.kind must be file or directory".format(label))
            if not isinstance(source["required"], bool):
                report.error("{}.required must be a boolean".format(label))
            digest = source["sha256"]
            if digest is not None and not SHA256_RE.fullmatch(str(digest)):
                report.error("{}.sha256 must be a lowercase SHA-256 digest".format(label))
            path = Path(str(source["path"])).expanduser()
            if check_paths and source["required"]:
                if not path.is_absolute():
                    report.error("{}.path must be absolute".format(label))
                elif not path.exists():
                    report.error("required source does not exist: {}".format(path))
                elif digest is None:
                    report.error("required source sha256 is missing: {}".format(path))
                elif source["kind"] == "file" and not path.is_file():
                    report.error("source kind does not match file: {}".format(path))
                elif source["kind"] == "directory" and not path.is_dir():
                    report.error("source kind does not match directory: {}".format(path))
                else:
                    try:
                        actual = path_sha256(path)
                    except (OSError, ValueError) as exc:
                        report.error("cannot hash source {}: {}".format(path, exc))
                    else:
                        if actual != digest:
                            report.error("source sha256 does not match {}".format(path))

    validate_string_list(data.get("confirmed_decisions"), "confirmed_decisions", report, non_empty=True)
    validate_string_list(data.get("acceptance"), "acceptance", report, non_empty=True)
    validate_string_list(data.get("stop_conditions"), "stop_conditions", report, non_empty=True)

    output = data.get("output_contract")
    if require_keys(output, ["format", "required_fields"], "output_contract", report):
        if not isinstance(output["format"], str) or not output["format"].strip():
            report.error("output_contract.format must be a non-empty string")
        validate_string_list(
            output["required_fields"], "output_contract.required_fields", report, non_empty=True
        )

    verification = data.get("verification")
    verification_ids = set()
    categories = set()
    if not isinstance(verification, list) or not verification:
        report.error("verification must be a non-empty list")
    else:
        for index, item in enumerate(verification):
            label = "verification[{}]".format(index)
            if not require_keys(item, ["id", "category", "command", "expected", "required"], label, report):
                continue
            for key in ("id", "category", "command", "expected"):
                if not isinstance(item[key], str) or not item[key].strip():
                    report.error("{}.{} must be a non-empty string".format(label, key))
            verification_id = item["id"]
            if isinstance(verification_id, str) and verification_id in verification_ids:
                report.error("verification id must be unique: {}".format(verification_id))
            if not isinstance(verification_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", verification_id):
                report.error("{}.id must be a safe stable identifier".format(label))
            else:
                verification_ids.add(verification_id)
            if not isinstance(item["category"], str) or item["category"] not in ALLOWED_VERIFICATION_CATEGORIES:
                report.error("{}.category is invalid".format(label))
            else:
                categories.add(item["category"])
            if not isinstance(item["required"], bool):
                report.error("{}.required must be a boolean".format(label))
    return task_allowed, categories


def validate_requirement_gate(context, action, report, check_paths=True, **kwargs):
    if action not in ALLOWED_REQUIREMENT_GATE_ACTIONS:
        report.error("requirement gate action must be one of {}".format(sorted(ALLOWED_REQUIREMENT_GATE_ACTIONS)))
        return
    validate_interaction_gate(context, action, report)
    if context.get("intent", {}).get("domain") != "business_project":
        report.error("requirement lifecycle gates apply only to business_project contexts")
        return
    validate_memory_recall(context.get("memory_recall"), context, report, check_paths=check_paths, require_completed=action != "readonly_analysis")
    requirements = context.get("requirements")
    if not isinstance(requirements, dict):
        report.error("business_project requirement gate requires requirements state")
        return
    route = requirements.get("artifact_route")
    spec = requirements.get("spec_rfc", {})
    openspec = requirements.get("openspec", {})
    retro = requirements.get("retroactive_normalization", {})
    gated = {"member_confirmation", "task_create", "openspec_authoring", "openspec_confirmation", "task_start", "implementation"}
    if action == "spec_rfc_confirmation" and route == "spec_rfc_then_openspec" and spec.get("validation_status") != "passed":
        report.error("Spec+RFC deterministic validation must pass before user confirmation")
    if action in gated and retro.get("required") is True and retro.get("status") != "completed":
        report.error("retroactive normalization must be completed before {}".format(action))
    if action in gated and route == "spec_rfc_then_openspec" and spec.get("status") != "confirmed":
        report.error("confirmed Spec+RFC is required before {}".format(action))
    if action in {"openspec_confirmation", "task_start", "implementation"} and route == "spec_rfc_then_openspec":
        if openspec.get("status") != "passed" or openspec.get("traceability_status") != "passed":
            report.error("OpenSpec deterministic validation and traceability must pass before {}".format(action))
        if openspec.get("confirmed_by_user") is not True:
            report.error("OpenSpec user confirmation is required before {}".format(action))
    records = {str(item.get("name", "")).lstrip("$"): item for item in requirements.get("skill_execution", {}).get("records", []) if isinstance(item, dict)}
    if action in gated:
        for requested in requirements.get("skill_execution", {}).get("explicitly_requested", []):
            record = records.get(str(requested).lstrip("$"), {})
            if record.get("status") != "completed" or record.get("validation_status") != "passed" or not record.get("evidence"):
                report.error("explicitly requested Skill {} lacks completed validation evidence".format(requested))


def validate_task_context(data, report, check_paths=True, check_freshness=True, **kwargs):
    required = ["schema_version", "revision", "previous_context", "task_id", "intent", "task_type", "risk_level", "goal", "behavior", "scope", "sources", "confirmed_decisions", "interaction", "routing", "execution", "playbook", "memory_recall", "requirements", "acceptance", "verification", "output_contract", "stop_conditions", "freshness"]
    if not require_keys(data, required, "task context", report):
        return
    if data["schema_version"] != "1.6":
        report.error("active task context must use schema 1.6")
    if not isinstance(data["revision"], int) or isinstance(data["revision"], bool) or data["revision"] < 1:
        report.error("task context revision must be a positive integer")
    for key in ("task_id", "goal"):
        if not isinstance(data[key], str) or not data[key].strip():
            report.error("task context {} must be a non-empty string".format(key))
    if not isinstance(data["task_type"], str) or data["task_type"] not in ALLOWED_TASK_TYPES:
        report.error("task_type is invalid")
    if not isinstance(data["risk_level"], str) or data["risk_level"] not in ALLOWED_RISK_LEVELS:
        report.error("risk_level is invalid")
    task_allowed, verification_categories = _validate_task_shape(data, report, check_paths)
    intent = data["intent"]
    if not isinstance(intent, dict) or not isinstance(intent.get("domain"), str) or intent.get("domain") not in ALLOWED_INTENT_DOMAINS:
        report.error("intent.domain is invalid")
        return
    domain = intent["domain"]
    validate_interaction_gate(data, "readonly_analysis", report)
    routing = data["routing"]
    if not isinstance(routing, dict) or routing.get("root_agent") != ROOT_AGENT:
        report.error("routing.root_agent must be xiaoh")
        return
    agents = validate_string_list(routing.get("delegated_agents"), "routing.delegated_agents", report)
    unknown = set(agents) - REGISTERED_AGENTS
    if unknown:
        report.error("routing references unregistered agents: {}".format(", ".join(sorted(unknown))))
    policies = routing.get("delegation_policies")
    if not isinstance(policies, dict) or set(policies) != set(agents):
        report.error("routing.delegation_policies must exactly cover delegated_agents")
    else:
        for agent in agents:
            policy = policies[agent]
            if not isinstance(policy, dict):
                report.error("delegation policy for {} is invalid".format(agent))
                continue
            if policy.get("agent_type") != agent or not isinstance(policy.get("action"), str) or not isinstance(policy.get("task_name_prefix"), str):
                report.error("delegation policy for {} is invalid".format(agent))
            read_only = policy.get("read_only")
            if not isinstance(read_only, bool):
                report.error("delegation policy for {} read_only must be a boolean".format(agent))
            policy_paths = validate_string_list(
                policy.get("allowed_paths"),
                "routing.delegation_policies.{}.allowed_paths".format(agent),
                report,
                non_empty=read_only is False,
            )
            for path in policy_paths:
                if not path_is_covered(path, task_allowed):
                    report.error("delegation policy for {} allowed_paths exceed task scope".format(agent))
        writers = [
            (agent, policies[agent].get("allowed_paths", []))
            for agent in agents
            if isinstance(policies.get(agent), dict) and policies[agent].get("read_only") is False
        ]
        for index, (left_agent, left_paths) in enumerate(writers):
            for right_agent, right_paths in writers[index + 1:]:
                if any(
                    path_is_covered(left, [right]) or path_is_covered(right, [left])
                    for left in left_paths for right in right_paths
                ):
                    report.error("write-capable delegation policies overlap: {}, {}".format(left_agent, right_agent))
    execution = data["execution"]
    if require_keys(
        execution,
        ["lane", "selection_reason", "verification_scope", "impact_surfaces", "verification_profile", "effects", "delegation"],
        "execution",
        report,
    ):
        lane = execution["lane"]
        verification_scope = execution["verification_scope"]
        if not isinstance(lane, str) or lane not in ALLOWED_EXECUTION_LANES:
            report.error("execution.lane must be one of {}".format(sorted(ALLOWED_EXECUTION_LANES)))
        if not isinstance(execution["selection_reason"], str) or not execution["selection_reason"].strip():
            report.error("execution.selection_reason must be a non-empty string")
        if not isinstance(verification_scope, str) or verification_scope not in ALLOWED_VERIFICATION_SCOPES:
            report.error("execution.verification_scope must be one of {}".format(sorted(ALLOWED_VERIFICATION_SCOPES)))
        validate_string_list(execution["impact_surfaces"], "execution.impact_surfaces", report, non_empty=True)
        profile = execution["verification_profile"]
        if require_keys(profile, ["required_categories", "not_applicable"], "execution.verification_profile", report):
            required_categories = validate_string_list(
                profile["required_categories"],
                "execution.verification_profile.required_categories",
                report,
                non_empty=True,
            )
            for category in required_categories:
                if category not in ALLOWED_VERIFICATION_CATEGORIES:
                    report.error("execution verification category is invalid: {}".format(category))
                elif category not in verification_categories:
                    report.error("execution verification category lacks a verification item: {}".format(category))
            not_applicable = profile["not_applicable"]
            if not isinstance(not_applicable, list):
                report.error("execution.verification_profile.not_applicable must be a list")
            else:
                for index, item in enumerate(not_applicable):
                    if not require_keys(item, ["category", "reason"], "execution.verification_profile.not_applicable[{}]".format(index), report):
                        continue
                    if not isinstance(item["category"], str) or item["category"] not in ALLOWED_VERIFICATION_CATEGORIES or not isinstance(item["reason"], str) or not item["reason"].strip():
                        report.error("execution verification not_applicable entry is invalid")
            if data["task_type"] == "implementation":
                minimum = {"scope"}
                if lane == "standard":
                    minimum.add("contract")
                elif lane == "high_risk":
                    minimum.update({"contract", "security"})
                missing = minimum - set(required_categories)
                if missing:
                    report.error("{} implementation lane requires verification categories: {}".format(lane, ", ".join(sorted(missing))))
        effects = execution["effects"]
        if require_keys(effects, ["level", "authorized", "evidence"], "execution.effects", report):
            if not isinstance(effects["level"], str) or effects["level"] not in ALLOWED_EFFECT_LEVELS:
                report.error("execution.effects.level is invalid")
            if not isinstance(effects["authorized"], bool):
                report.error("execution.effects.authorized must be a boolean")
            evidence = effects["evidence"]
            if evidence is not None and (not isinstance(evidence, str) or not evidence.strip()):
                report.error("execution.effects.evidence must be null or a non-empty string")
            if isinstance(effects["level"], str) and effects["level"] in {"destructive", "production"}:
                if effects["authorized"] is not True or not isinstance(evidence, str) or not evidence.strip():
                    report.error("destructive or production effects require explicit authorization evidence")
            elif effects["authorized"] is True:
                report.error("non-destructive effects must not claim destructive authorization")
            interaction = data.get("interaction") if isinstance(data.get("interaction"), dict) else {}
            if isinstance(interaction.get("user_act"), str) and interaction.get("user_act") in {"question", "hypothesis"} and (
                data.get("task_type") in {"implementation", "operations"} or effects["level"] != "none"
            ):
                report.error("questions and hypotheses do not authorize side effects")
        if lane == "fast" and data["risk_level"] != "low":
            report.error("fast execution lane requires risk_level=low")
        if isinstance(data["risk_level"], str) and data["risk_level"] in {"high", "critical"} and lane != "high_risk":
            report.error("high or critical risk requires execution.lane=high_risk")
        if lane == "fast" and verification_scope != "impact_driven":
            report.error("fast execution lane requires impact-driven verification")
        if lane == "high_risk" and verification_scope != "full":
            report.error("high_risk execution lane requires full verification")
        delegation = execution["delegation"]
        if require_keys(
            delegation,
            ["decision", "authorized", "benefits", "reason"],
            "execution.delegation",
            report,
        ):
            decision = delegation["decision"]
            if not isinstance(decision, str) or decision not in ALLOWED_DELEGATION_DECISIONS:
                report.error("execution.delegation.decision must be one of {}".format(sorted(ALLOWED_DELEGATION_DECISIONS)))
            if not isinstance(delegation["authorized"], bool):
                report.error("execution.delegation.authorized must be a boolean")
            benefits = validate_string_list(
                delegation["benefits"], "execution.delegation.benefits", report
            )
            if not isinstance(delegation["reason"], str) or not delegation["reason"].strip():
                report.error("execution.delegation.reason must be a non-empty string")
            if decision == "delegate":
                if delegation["authorized"] is not True:
                    report.error("delegate decision requires explicit authorization")
                if not benefits:
                    report.error("delegate decision requires at least one material benefit")
                if not agents:
                    report.error("delegate decision requires delegated_agents")
            elif agents:
                report.error("delegated_agents require execution.delegation.decision=delegate")
            elif delegation["authorized"] is True or benefits:
                report.error("direct delegation decision must not claim authorization or benefits")
    if domain == "business_project":
        validate_requirements(data.get("requirements"), report)
        if (
            isinstance(data.get("requirements"), dict)
            and isinstance(execution, dict)
            and data["requirements"].get("artifact_route") == "direct_change"
            and execution.get("lane") != "fast"
        ):
            report.error("direct_change artifact route requires execution.lane=fast")
        validate_memory_recall(data.get("memory_recall"), data, report, check_paths=check_paths, check_freshness=check_freshness, require_completed=bool(agents))
    else:
        if data.get("requirements") is not None or data.get("memory_recall") is not None:
            report.error("requirements and memory_recall must be null outside business_project")
    freshness = data["freshness"]
    if not isinstance(freshness, dict):
        report.error("freshness must be an object")
    else:
        checked = parse_timestamp(freshness.get("checked_at"), "freshness.checked_at", report)
        if check_freshness and checked and abs((datetime.now(timezone.utc) - checked).total_seconds()) > MAX_CONTEXT_AGE_HOURS * 3600:
            report.error("task context freshness is stale")
