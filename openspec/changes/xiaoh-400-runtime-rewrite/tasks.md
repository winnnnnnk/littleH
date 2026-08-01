## 1. Freeze the 3.1.2 behavior and safety baseline

- [x] 1.1 Inventory every confirmed 3.1.2 product capability and map it to a contract test or deterministic verification. `[runtime-architecture: Preserve the confirmed product baseline]`
- [x] 1.2 Add root identity, five-Agent inventory, task-context, run-record, routing, binding-consumption, receipt, transcript, and Vault-write contract tests. `[runtime-security]`
- [x] 1.3 Add repository-test guards proving that test setup, update, Doctor, automation, and import cannot resolve to the real Codex, XiaoH, Vault, plugin-cache, or Playbook locations. `[transactional-installation: Keep repository development isolated from the real machine]`
- [x] 1.4 Capture the current CLI command, response-field, and exit-code baseline, and list the intentional 4.0.0 Schema breaks. `[runtime-cli]`

Blocking edge: tasks 1.1 through 1.4 block public-entrypoint replacement and deletion of the 3.1.2 implementation.

## 2. Establish the new runtime architecture

- [x] 2.1 Create the domain models for installation plans, recovery manifests, transactions, receipts, diagnostic results, Doctor reports, activation states, assets, and Skill audits. `[runtime-architecture]`
- [x] 2.2 Define minimal Ports for filesystem, process, clock, plugin-manager facts, and automation storage, with temporary or in-memory test Adapters. `[runtime-architecture: Isolate external side effects behind ports]`
- [x] 2.3 Create application use-case boundaries for plan, setup, update, Doctor, Workspace, and automation without changing public entrypoints. `[runtime-architecture]`
- [x] 2.4 Add an automated dependency gate that rejects star imports, prohibited layer directions, and runtime import cycles. `[runtime-architecture: Enforce directional module dependencies]`
- [x] 2.5 Add macOS and Windows path-behavior tests for the new Ports and Adapters. `[runtime-architecture: Preserve cross-platform behavior with minimal dependencies]`

Blocking edge: tasks 2.1 and 2.2 block new installation, Doctor, and runtime-service implementations.

## 3. Deliver the complete Doctor tracer

- [x] 3.1 Implement the `DiagnosticResult` and `DoctorReport` aggregation path with pass, degrade, fail, skip, and unverified semantics. `[complete-doctor]`
- [x] 3.2 Implement independent plugin, loaded-Skill, managed-runtime, Agent, Hook, Validator, Vault, Workspace, automation, and Playbook diagnostics through explicit dependencies. `[complete-doctor: Execute independent diagnostics completely]`
- [x] 3.3 Ensure a failed diagnostic does not stop unrelated safe diagnostics, while unsafe or dependency-blocked diagnostics return an explicit skip reason. `[complete-doctor]`
- [x] 3.4 Implement effective installation and activation status from current evidence, including stale loaded-Skill and untrusted-Hook cases. `[complete-doctor: Verify activation only from current runtime evidence]`
- [x] 3.5 Add tests proving Doctor performs no repair write, companion installation, automation binding, configuration update, or automatic second run. `[complete-doctor: Keep Doctor free of repair side effects]`

## 4. Deliver the transactional installation tracer

- [x] 4.1 Implement read-only asset classification and `InstallationPlan`, including conflicts, expected writes, expected deletes, preserved assets, unresolved items, and recovery conditions. `[transactional-installation: Produce a read-only installation plan]`
- [x] 4.2 Implement isolated candidate rendering and validation for Agent, Hook, Validator, contracts, configuration templates, Vault templates, placeholders, permissions, digests, and independent source. `[transactional-installation: Build and validate an isolated candidate]`
- [x] 4.3 Implement `RecoveryManifest` creation with item source, backup path, restore target, digest, size, completeness, path-escape, and space checks. `[transactional-installation: Create a complete recovery manifest]`
- [x] 4.4 Implement the installation transaction state machine and one durable record for all phase transitions and actual writes. `[transactional-installation: Execute a compensating transaction]`
- [x] 4.5 Implement per-root local switching and reverse-order compensating recovery with restored-digest verification. `[transactional-installation: Execute a compensating transaction]`
- [x] 4.6 Implement installation receipts and deployment-versus-activation states without claiming runtime verification. `[transactional-installation: Separate deployment from activation]`
- [x] 4.7 Add same-input setup and update tests proving no duplicate managed files, configuration blocks, Hook blocks, Agents, or automation identities. `[transactional-installation: Make installation and update idempotent]`
- [x] 4.8 Add stage-by-stage fault injection for candidate, backup, switching, configuration, Vault, static Doctor, compensation, and interrupted recovery. `[transactional-installation]`

Blocking edge: tasks 4.1 through 4.6 block setup/update CLI cutover.

## 5. Rebuild runtime services

- [x] 5.1 Rebuild configuration loading, Schema validation, locking, merging, backup-aware atomic writing, and path resolution behind one service. `[runtime-services: Centralize configuration ownership]`
- [x] 5.2 Rebuild Workspace registration, platform bindings, conflict detection, and unique longest-root resolution behind one repository. `[runtime-services: Resolve Workspace ownership consistently]`
- [x] 5.3 Rebuild Vault synchronization with managed hashes, legacy hashes, previous-applied hashes, customization preservation, and real-path enforcement. `[runtime-services: Protect Vault user content]`
- [x] 5.4 Rebuild automation template reconciliation, stable identity, user-preference preservation, duplicate detection, and readback through the automation-store Port. `[runtime-services: Reconcile automation by stable logical identity]`
- [x] 5.5 Implement fixture-driven 3.1.2 user durable asset import and explicit rejection of old managed runtime and authorization evidence. `[runtime-services: Import only user durable assets]`
- [x] 5.6 Implement read-only plugin-manager and Playbook integration reports without cache, version, or Hook-trust mutation. `[runtime-services: Respect external ownership boundaries]`

## 6. Rebuild Hook and Validator internals under contract

- [x] 6.1 Rebuild the Validator package while preserving task-context, run-record, routing, closure, and thin-entrypoint contracts. `[runtime-security: Preserve Hook and Validator security invariants]`
- [x] 6.2 Rebuild root-Agent delegation preparation, atomic binding consumption, role match, Codex `SubagentStart` context transport, random receipt, transcript, and stop-proof handling without a bypassable split. `[runtime-security: Preserve formal delegation authorization]`
- [x] 6.3 Rebuild Vault write guarding with canonical real-path, allowed-root, and operation-scope checks. `[runtime-security: Fail closed on untrusted paths and evidence]`
- [x] 6.4 Add negative tests for path escape, managed symlink, digest drift, binding reuse, context drift, role mismatch, missing proof, and untrusted Hook evidence. `[runtime-security]`
- [x] 6.5 Add redaction tests for plans, logs, manifests, receipts, Doctor reports, handoff content, and Skill audit evidence. `[runtime-security: Exclude sensitive data from evidence]`
- [x] 6.6 Add command-policy tests proving XiaoH never changes Playbook CLI versions, plugin cache ownership, or Hook trust. `[runtime-security: Respect manual external authority boundaries]`
- [x] 6.7 Add public-entrypoint contract tests and a read-only runtime protocol probe for the Codex `SubagentStart` response shape. `[runtime-security: Preserve formal delegation authorization]`
- [x] 6.8 Add root execution binding, pre-tool write-scope checks, actual Git-diff scope attestation, and pre-existing-change protection. `[runtime-security: Bind root writes to actual task scope]`
- [x] 6.9 Bind delegated read/write policies to non-overlapping task paths and carry them in the effective brief. `[runtime-security: Isolate delegated write scopes]`

Blocking edge: the affected public Hook or Validator entrypoint cannot switch until its matching baseline and negative tests pass.

## 7. Rebuild Skill governance and capability quality

- [x] 7.1 Define the versioned third-party Skill Manifest Schema and generic path, license, digest, decision, and evidence validator. `[governed-skills: Validate third-party Skills from a versioned manifest]`
- [x] 7.2 Migrate the accepted mattpocock/skills audit into the new Manifest; verify the unchanged-commit baseline counts `0/10/8/4`, or recompute all source facts and decisions if the upstream commit changed before release. `[governed-skills: Require a new audit for a new upstream commit]`
- [x] 7.3 Verify the ten adapted Skills and eight absorbed methods remain present and traceable after Skill restructuring. `[governed-skills: Preserve accepted adapted and absorbed capabilities]`
- [x] 7.4 Audit every XiaoH Skill for ownership, invocation mode, completion criteria, single-source rules, progressive disclosure, duplication, sediment, and pure aliases. `[governed-skills: Apply Skill quality rules]`
- [x] 7.5 Add the user-invoked, fixed-point, single-pass code-review Skill with separate standards and spec axes and no repair, re-review, Campaign, or gate mutation. `[governed-skills: Provide explicit single-pass code review]`
- [x] 7.6 Integrate handoff linking, redaction, unresolved-work, and suggested-Skill behavior into existing handoff or recall ownership without a new authoritative history. `[governed-skills: Absorb handoff quality without creating a second fact source]`
- [x] 7.7 Verify `grill-me`, `teach`, and full `setup-matt-pocock-skills` are absent from the core, and triage state is not used as XiaoH authority. `[governed-skills: Keep non-core upstream Skills outside the core surface]`
- [x] 7.8 Add `fast`, `standard`, and `high_risk` execution lanes plus the low-risk `direct_change` artifact route without creating a second workflow state machine. `[development-flow: Select one risk-proportional execution lane]`
- [x] 7.9 Add the explicit-authorization and material-benefit delegation threshold to the core workflow. `[development-flow: Delegate only when authorized benefit is material]`

## 8. Cut over the CLI and public runtime surface

- [x] 8.1 Implement the thin CLI dispatcher and common `xiaoh-cli-response/v2` normalization without domain or transaction rules. `[runtime-cli]`
- [x] 8.2 Wire plan and Doctor commands to the new application use cases and verify read-only responses. `[runtime-cli: Preserve stable command concepts through a thin entrypoint]`
- [x] 8.3 Wire setup and update to the new transaction use cases with accurate transaction, backup, recovery, activation, and actual-write fields. `[runtime-cli: Report installation and recovery facts accurately]`
- [x] 8.4 Wire Workspace and automation commands to the new runtime services. `[runtime-cli]`
- [x] 8.5 Convert argument, configuration, path, candidate, transaction, diagnostic, and integration failures into stable responses and exit codes without normal-path tracebacks. `[runtime-cli: Convert expected failures into stable errors]`
- [x] 8.6 Update manifest, templates, documentation, and release evidence to label 4.0.0 as a repository code candidate until a later authorized installation. `[runtime-cli: Label repository output as a code candidate]`
- [x] 8.7 Require schema 1.6 execution-lane evidence and schema 1.2 completion summaries; reject unsafe lane downgrade and unjustified delegation. `[development-flow: Converge deterministic verification into one evidence summary]`
- [x] 8.8 Enforce complete task-context structures, source digests, verification identities/categories, and evidence-backed closure coverage. `[development-flow: Bind completion to source and verification evidence]`

## 9. Complete deterministic and cross-platform verification

- [x] 9.1 Run the complete unit, contract, integration, temporary-root E2E, fault-injection, and idempotency suites locally without touching real user paths. `[all capabilities]`
- [x] 9.2 Make syntax, type checking, lint, contract, and test failures blocking in CI; remove applicable `continue-on-error` quality gates. `[runtime-architecture; runtime-cli]`
- [ ] 9.3 Run the supported macOS, Windows, and Python matrix, including entrypoints, path behavior, file occupancy, symlinks, and line-ending cases. `[runtime-architecture: Preserve cross-platform behavior with minimal dependencies]`
- [x] 9.4 Verify every Spec+RFC FR, NFR, interface boundary, failure behavior, and non-goal has implementation and test evidence. `[source revision 4]`
- [x] 9.5 Add contract tests for execution lanes, direct changes, Agent benefit thresholds, complete failure-set guidance, and verification evidence summaries. `[development-flow]`

## 10. Remove the old implementation and produce the candidate

- [x] 10.1 Switch every public entrypoint to the new implementation only after its baseline, integration, and negative tests pass. `[runtime-architecture: Remove the legacy production implementation]`
- [x] 10.2 Delete the old runtime modules, compatibility branches, dead code, and removed review assets; verify no callsite remains. `[runtime-architecture: Remove the legacy production implementation]`
- [ ] 10.3 Re-run the complete deterministic and cross-platform acceptance suite against the single remaining implementation. `[all capabilities]`
- [x] 10.4 Produce the XiaoH 4.0.0 installable code-candidate report with version, evidence, known limits, and explicit statements that local installation, restart, Hook trust, and runtime verification were not performed. `[runtime-cli: Label repository output as a code candidate]`
- [x] 10.5 Stop after candidate acceptance; do not run real setup, update, installation, restart, trust, or runtime Doctor. `[transactional-installation: Keep repository development isolated from the real machine]`
