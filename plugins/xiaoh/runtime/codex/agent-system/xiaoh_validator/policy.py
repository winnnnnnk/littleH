"""Stable validator policy constants and runtime paths."""

import os
import re
from pathlib import Path

HOME = Path.home()
CODEX = Path(os.environ.get("CODEX_HOME", str(HOME / ".codex"))).expanduser()
OBSIDIAN_VAULT = Path(os.environ.get("XIAOH_VAULT", str(HOME / "obsidian/development-vault"))).expanduser()
AGENTS_DIR = CODEX / "agents"
ROOT_AGENT = "xiaoh"
ROOT_AGENT_EXECUTION_MODES = {"main_agent_direct", "main_agent_sequential"}
ROOT_AGENT_HOOK = CODEX / "hooks/block_reserved_root_agent.py"
VAULT_WRITE_HOOK = CODEX / "hooks/guard_vault_writes.py"
ROOT_WRITE_HOOK = CODEX / "hooks/guard_task_writes.py"
HOOK_RUNTIME_VERIFIER = CODEX / "hooks/verify_agent_hook_runtime.py"
ROLE_CATALOG = OBSIDIAN_VAULT / "90-个人系统/Agent协作角色.md"
EVOLUTION_LEDGER = OBSIDIAN_VAULT / "90-个人系统/Agent进化台账.md"
SYSTEM_DIR = CODEX / "agent-system"
ROUTING_CASES = SYSTEM_DIR / "routing-cases.json"
EVOLUTION_POLICY = SYSTEM_DIR / "evolution-policy.json"
AGENT_STAGES = SYSTEM_DIR / "agent-stages.json"

ALLOWED_SANDBOXES = {"read-only", "workspace-write", "danger-full-access"}
ALLOWED_TASK_TYPES = {"analysis", "design", "implementation", "verification", "operations"}
ALLOWED_RISK_LEVELS = {"low", "medium", "high", "critical"}
ALLOWED_INTENT_DOMAINS = {"global_agent_capability", "playbook_platform", "business_project"}
ALLOWED_USER_ACTS = {"question", "hypothesis", "fact_correction", "business_decision", "execution_instruction"}
ALLOWED_BASELINE_CHANGES = {"none", "proposed", "confirmed"}
ALLOWED_EVIDENCE_STATUSES = {"not_checked", "supported", "conflicted", "insufficient"}
ALLOWED_SCOPE_REDUCTION_BASES = {"not_applicable", "evidence_supported", "explicit_business_decision"}
ALLOWED_ARTIFACT_ROUTES = {
    "direct_change",
    "openspec_only",
    "spec_rfc_then_openspec",
    "class_skill",
}
ALLOWED_EXECUTION_LANES = {"fast", "standard", "high_risk"}
ALLOWED_VERIFICATION_SCOPES = {"impact_driven", "full"}
ALLOWED_VERIFICATION_CATEGORIES = {
    "scope", "syntax", "unit", "integration", "contract", "build",
    "security", "migration_recovery", "cross_platform",
}
ALLOWED_DELEGATION_DECISIONS = {"direct", "delegate"}
ALLOWED_EFFECT_LEVELS = {"none", "reversible", "destructive", "production"}
ALLOWED_SPEC_RFC_STATUS = {"not_required", "pending", "drafting", "validating", "confirmation_pending", "confirmed"}
ALLOWED_REQUIREMENT_CHECK_STATUS = {"not_required", "pending", "passed", "failed"}
ALLOWED_RETROACTIVE_STATUS = {"not_required", "pending", "in_progress", "completed"}
ALLOWED_SKILL_STATUS = {"pending", "in_progress", "completed"}
ALLOWED_SKILL_CONFIRMATION_STATUS = {"not_required", "pending", "confirmed"}
ALLOWED_REQUIREMENT_GATE_ACTIONS = {
    "readonly_analysis", "artifact_routing", "spec_rfc_baseline", "spec_rfc_confirmation",
    "member_confirmation", "task_create", "openspec_authoring", "openspec_confirmation",
    "task_start", "implementation",
}
ALLOWED_RECALL_STATUS = {"pending", "completed", "blocked"}
ALLOWED_TASK_RELATIONS = {"new", "continuation", "historical_recovery", "similar_reuse"}
ALLOWED_MEMORY_SOURCE_KINDS = {"project_progress", "task_page", "task_closeout", "requirement_baseline", "formal_knowledge", "daily_digest"}
ALLOWED_MEMORY_SOURCE_ROLES = {"navigation", "authority", "evidence"}
ALLOWED_CURRENT_FACT_KINDS = {"code", "configuration", "spec_rfc", "openspec", "task_state", "runtime_evidence"}
ALLOWED_RUN_STATUS = {"completed", "blocked", "failed", "cancelled"}
ALLOWED_GATE_STATUS = {"passed", "failed", "blocked", "not-run", "blocked-as-required", "blocked-as-designed"}
ALLOWED_VERIFICATION_STATUS = set(ALLOWED_GATE_STATUS)
SENSITIVE_KEYS = re.compile(r"(^|_)(password|token|secret|private_key|credential)s?($|_)", re.I)
ABSOLUTE_PATH = re.compile(r"/(?:Users|home|opt|var|srv|workspace)/[^\s'\"`]+")
RESERVED_AGENT_ALIASES = {"xiaoh", "小h"}
IMPLEMENTATION_AGENTS = {"java_implementer", "frontend_implementer"}
REGISTERED_AGENTS = {"frontend_implementer", "java_architect", "java_code_explorer", "java_implementer", "pki_domain_expert"}
MAX_CONTEXT_AGE_HOURS = 24
PLAYBOOK_BINDING_MAX_AGE_SECONDS = 900
MAX_RECALL_AGE_HOURS = 24
DELEGATION_BINDING_MAX_AGE_SECONDS = 900

def root_agent_owns_worker(worker):
    return worker.get("execution_mode") in ROOT_AGENT_EXECUTION_MODES and worker.get("recommended_executor") == "main_agent"
