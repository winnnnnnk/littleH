"""Delegation integrity checks without a review lifecycle."""

from xiaoh_validator.runtime import *
from xiaoh_validator.policy import *
from xiaoh_validator.diagnostics import Report
from xiaoh_validator.evidence import *


def closure_rejection_reasons(record, reviewer_agents=None):
    reasons = []
    if not isinstance(record, dict) or record.get("schema_version") != "1.2":
        reasons.append("run record must use schema 1.2")
        return reasons
    if record.get("status") != "completed":
        reasons.append("run record is not completed")
    for group in ("gates", "verification"):
        entries = record.get(group)
        if not isinstance(entries, list) or not entries:
            reasons.append("{} must be non-empty".format(group))
        elif any(item.get("status") != "passed" for item in entries if isinstance(item, dict)):
            reasons.append("{} contains a non-passing result".format(group))
    if record.get("metrics", {}).get("result_accepted") is not True:
        reasons.append("result was not accepted")
    return reasons


def expected_effective_brief(context, agent, action, task_name, binding_hash=None, **extra):
    brief = {
        "task_id": context.get("task_id"),
        "authority_hash": task_authority_hash(context),
        "delegated_agent": agent,
        "action": action,
        "task_name": task_name,
        "purpose": "execution",
    }
    if binding_hash:
        brief["binding_hash"] = binding_hash
    return brief


def validate_attested_binding(proof, expected_brief, transcript_path, report):
    if not isinstance(proof, dict):
        report.error("delegation proof must be an object")
        return
    for key, value in expected_brief.items():
        if proof.get("effective_brief", {}).get(key) != value:
            report.error("delegation proof effective_brief.{} does not match".format(key))
    if proof.get("transcript_path") != transcript_path:
        report.error("delegation proof transcript_path does not match")
    if proof.get("attested") is not True:
        report.error("delegation proof must be attested")


def validate_delegation_proof(runtime_evidence, data, context, context_path, report, check_paths):
    proof_path = Path(str(runtime_evidence.get("delegation_proof_path", ""))).expanduser()
    proof_hash = runtime_evidence.get("delegation_proof_hash")
    if not proof_path.is_absolute():
        report.error("delegation_proof_path must be absolute")
        return
    if not re.fullmatch(r"[0-9a-f]{64}", str(proof_hash)):
        report.error("delegation_proof_hash must be a lowercase SHA-256 digest")
        return
    if not check_paths:
        return
    if not proof_path.is_file():
        report.error("delegation proof does not exist: {}".format(proof_path))
        return
    if file_sha256(proof_path) != proof_hash:
        report.error("delegation proof hash does not match")
        return
    try:
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        report.error("delegation proof is invalid JSON: {}".format(exc))
        return
    if proof.get("schema_version") != DELEGATION_PROOF_SCHEMA:
        report.error("delegation proof schema is not supported")
    if proof.get("task_id") != data.get("task_id") or proof.get("agent") != data.get("agent"):
        report.error("delegation proof identity does not match run record")
    if proof.get("authority_hash") != task_authority_hash(context):
        report.error("delegation proof authority hash does not match task context")


def validate_interaction_gate(context, action, report):
    interaction = context.get("interaction")
    if not isinstance(interaction, dict):
        report.error("task context interaction must be an object")
        return
    if interaction.get("user_act") not in ALLOWED_USER_ACTS:
        report.error("interaction.user_act is invalid")
    if interaction.get("evidence_status") not in ALLOWED_EVIDENCE_STATUSES:
        report.error("interaction.evidence_status is invalid")
    if action != "readonly_analysis" and interaction.get("user_act") in {"question", "hypothesis"}:
        report.error("questions and hypotheses do not authorize side effects")
    conflicts = interaction.get("material_conflicts")
    if action != "readonly_analysis" and isinstance(conflicts, list) and conflicts:
        report.error("material evidence conflicts must be resolved before side effects")
    reduction = interaction.get("scope_reduction", {})
    if reduction.get("present") is True and reduction.get("basis") not in {"evidence_supported", "explicit_business_decision"}:
        report.error("scope reduction requires evidence or an explicit business decision")


def validate_execution_binding(binding, context, context_path, agent, action, report, check_paths=True, **kwargs):
    if not isinstance(binding, dict):
        report.error("execution binding must be an object")
        return
    required = ["schema_version", "task_id", "authority_hash", "delegated_agent", "action", "task_name", "created_at", "nonce"]
    if not require_keys(binding, required, "execution binding", report):
        return
    if binding["schema_version"] != DELEGATION_BINDING_SCHEMA:
        report.error("execution binding schema is not supported")
    expected = {
        "task_id": context.get("task_id"),
        "authority_hash": task_authority_hash(context),
        "delegated_agent": agent,
        "action": action,
    }
    for key, value in expected.items():
        if binding.get(key) != value:
            report.error("execution binding {} does not match".format(key))
    if agent not in context.get("routing", {}).get("delegated_agents", []):
        report.error("execution binding agent is not delegated by task context")
    policy = context.get("routing", {}).get("delegation_policies", {}).get(agent, {})
    if policy.get("agent_type") != agent or policy.get("action") != action:
        report.error("execution binding violates delegation policy")
    prefix = policy.get("task_name_prefix")
    if not isinstance(prefix, str) or not re.fullmatch(re.escape(prefix) + r"__r[1-9][0-9]*__[0-9a-f]{8,64}", str(binding.get("task_name"))):
        report.error("execution binding task_name is outside its authorized namespace")
    created = parse_timestamp(binding.get("created_at"), "execution binding created_at", report)
    if created and abs((datetime.now(timezone.utc) - created).total_seconds()) > DELEGATION_BINDING_MAX_AGE_SECONDS:
        report.error("execution binding is stale")
