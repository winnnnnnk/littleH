## ADDED Requirements

### Requirement: Preserve the XiaoH root identity
The active root task SHALL carry the XiaoH identity. `xiaoh` MUST NOT be registered or delegated as a child Agent. The governed specialist set SHALL contain only `frontend_implementer`, `java_architect`, `java_code_explorer`, `java_implementer`, and `pki_domain_expert`.

#### Scenario: Runtime inventory is validated
- **WHEN** the managed Agent inventory and root contract are inspected
- **THEN** no `xiaoh` Agent definition exists
- **AND** all five required specialist definitions exist
- **AND** an unexpected governed Agent produces a diagnostic finding

### Requirement: Preserve formal delegation authorization
Formal delegation SHALL require a valid task context, authority hash, delegated role, one-time execution binding, role match, random receipt, transcript, and stop proof. Missing, expired, reused, or drifted evidence MUST fail closed.

#### Scenario: Execution binding is reused
- **WHEN** a second Agent start attempts to consume an already consumed binding
- **THEN** the Hook rejects the start
- **AND** no delegated authority is injected
- **AND** the failure evidence identifies binding reuse without exposing sensitive content

#### Scenario: SubagentStart transports the delegation context
- **WHEN** the Hook accepts a valid one-time binding at SubagentStart
- **THEN** its JSON output identifies `hookEventName` as `SubagentStart`
- **AND** `additionalContext` contains the authoritative task brief and random completion receipt
- **AND** a read-only runtime protocol probe rejects an installed Hook that omits either required output field

### Requirement: Preserve Hook and Validator security invariants
Hook and Validator implementations SHALL preserve task-context, run-record, routing, root-protection, atomic-consumption, transcript-proof, and Vault-write invariants. Refactoring MUST NOT split an atomic decision into a bypassable sequence.

#### Scenario: Task context drifts after preparation
- **WHEN** the task context content or authority hash changes between binding preparation and Agent start
- **THEN** the start is rejected
- **AND** the binding cannot authorize the drifted context

### Requirement: Bind root writes to actual task scope
Before a root task performs repository writes, the runtime SHALL create a short-lived execution binding from the validated task context and current repository state. PreToolUse SHALL reject missing, expired, drifted, or clearly out-of-scope writes. Final closure SHALL require a scope proof computed from the actual pre/post repository state; shell parsing is a preventive check and MUST NOT be represented as complete command understanding.

#### Scenario: A command changes a file outside the allowed paths
- **WHEN** the final repository state contains a task-introduced change outside `scope.allowed_paths`
- **THEN** scope attestation fails even if the pre-tool command parser did not identify the target
- **AND** the task cannot be recorded as completed

#### Scenario: A task touches a pre-existing user change
- **WHEN** a file was already dirty at binding time and the task changes it without listing it in `scope.preexisting_changes`
- **THEN** scope attestation fails
- **AND** the unrelated user change remains visibly unresolved

### Requirement: Isolate delegated write scopes
Each delegated policy SHALL declare `allowed_paths` and `read_only`. A write-capable delegated scope MUST be contained in the root task scope, and concurrent write-capable policies MUST NOT overlap. The effective SubagentStart brief SHALL carry those constraints.

#### Scenario: Two delegated writers overlap
- **WHEN** two delegated policies can write the same path or ancestor/descendant paths
- **THEN** the task context is rejected before delegation preparation

### Requirement: Fail closed on untrusted paths and evidence
The runtime SHALL reject path escape, unsafe managed symlinks, digest mismatch, unverified candidate source, invalid Schema, and insufficient permission or trust evidence before the related side effect.

#### Scenario: Managed asset resolves outside its root
- **WHEN** a managed relative path or symlink resolves outside the declared plugin, Codex, Vault, candidate, or backup root
- **THEN** validation fails
- **AND** no content is read from or written to the escaped target for the managed operation

### Requirement: Exclude sensitive data from evidence
Plans, logs, backup manifests, transaction receipts, Doctor reports, handoff content, and Skill audit evidence MUST NOT contain passwords, tokens, cookies, private keys, or unrelated personally identifiable data.

#### Scenario: Source configuration contains a sensitive field
- **WHEN** an asset classifier or diagnostic processes a source document containing a credential-like value
- **THEN** the output records only the permitted non-sensitive fact or a redacted marker
- **AND** the secret value does not appear in logs, manifests, receipts, or test snapshots

### Requirement: Respect manual external authority boundaries
XiaoH SHALL NOT install, update, downgrade, relink, or change the source of Playbook CLI; SHALL NOT rewrite the Codex plugin cache; and SHALL NOT approve Hook trust on behalf of the user.

#### Scenario: Doctor detects an incompatible Playbook version
- **WHEN** the optional Playbook integration is enabled and the installed CLI version is incompatible
- **THEN** XiaoH reports the version, path, impact, and recommended manual action
- **AND** executes no Playbook version-changing command
