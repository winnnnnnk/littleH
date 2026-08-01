"""Task-context and requirement lifecycle validation."""

from xiaoh_validator.runtime import *
from xiaoh_validator.policy import *
from xiaoh_validator.diagnostics import Report
from xiaoh_validator.evidence import *
from xiaoh_validator.requirements import *
from xiaoh_validator.delegation import *


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
    records = {str(item.get("name", "")).removeprefix("$"): item for item in requirements.get("skill_execution", {}).get("records", []) if isinstance(item, dict)}
    if action in gated:
        for requested in requirements.get("skill_execution", {}).get("explicitly_requested", []):
            record = records.get(str(requested).removeprefix("$"), {})
            if record.get("status") != "completed" or record.get("validation_status") != "passed" or not record.get("evidence"):
                report.error("explicitly requested Skill {} lacks completed validation evidence".format(requested))


def validate_task_context(data, report, check_paths=True, check_freshness=True, **kwargs):
    required = ["schema_version", "revision", "previous_context", "task_id", "intent", "task_type", "risk_level", "goal", "behavior", "scope", "sources", "confirmed_decisions", "interaction", "routing", "playbook", "memory_recall", "requirements", "acceptance", "verification", "output_contract", "stop_conditions", "freshness"]
    if not require_keys(data, required, "task context", report):
        return
    if data["schema_version"] != "1.6":
        report.error("active task context must use schema 1.6")
    if not isinstance(data["revision"], int) or isinstance(data["revision"], bool) or data["revision"] < 1:
        report.error("task context revision must be a positive integer")
    for key in ("task_id", "goal"):
        if not isinstance(data[key], str) or not data[key].strip():
            report.error("task context {} must be a non-empty string".format(key))
    if data["task_type"] not in ALLOWED_TASK_TYPES:
        report.error("task_type is invalid")
    if data["risk_level"] not in ALLOWED_RISK_LEVELS:
        report.error("risk_level is invalid")
    intent = data["intent"]
    if not isinstance(intent, dict) or intent.get("domain") not in ALLOWED_INTENT_DOMAINS:
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
            if policy.get("agent_type") != agent or not isinstance(policy.get("action"), str) or not isinstance(policy.get("task_name_prefix"), str):
                report.error("delegation policy for {} is invalid".format(agent))
    if domain == "business_project":
        validate_requirements(data.get("requirements"), report)
        validate_memory_recall(data.get("memory_recall"), data, report, check_paths=check_paths, check_freshness=check_freshness, require_completed=bool(agents))
    else:
        if data.get("requirements") is not None or data.get("memory_recall") is not None:
            report.error("requirements and memory_recall must be null outside business_project")
    if not isinstance(data["acceptance"], list) or not data["acceptance"]:
        report.error("acceptance must be a non-empty list")
    if not isinstance(data["verification"], list) or not data["verification"]:
        report.error("verification must be a non-empty list")
    freshness = data["freshness"]
    if not isinstance(freshness, dict):
        report.error("freshness must be an object")
    else:
        checked = parse_timestamp(freshness.get("checked_at"), "freshness.checked_at", report)
        if check_freshness and checked and abs((datetime.now(timezone.utc) - checked).total_seconds()) > MAX_CONTEXT_AGE_HOURS * 3600:
            report.error("task context freshness is stale")
