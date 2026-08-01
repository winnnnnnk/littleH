## ADDED Requirements

### Requirement: Produce a read-only installation plan
Before any managed write, the installer SHALL produce an `InstallationPlan` containing target version, resolved paths, asset inventory, conflicts, expected creates, expected overwrites, expected deletes, preserved assets, candidate requirements, backup requirements, unresolved items, and recovery conditions. Plan generation MUST NOT modify the target environment.

#### Scenario: Plan a clean installation
- **WHEN** a caller requests a plan for explicit Codex, Vault, and XiaoH configuration roots
- **THEN** the response contains a complete expected-write and conflict inventory
- **AND** `actual_writes` is empty
- **AND** no target file, configuration, plugin, Vault item, or automation binding changes

### Requirement: Build and validate an isolated candidate
The installer SHALL build Agent, Hook, Validator, contracts, configuration templates, Vault managed templates, and runtime files in an isolated candidate root. The candidate MUST pass manifest, digest, Schema, path, permission, placeholder, and independent-source checks before backup or switching.

#### Scenario: Candidate source cannot be independently verified
- **WHEN** the candidate source is missing, aliases the active loaded cache, contains an unexpected managed file, or fails a digest check
- **THEN** candidate validation returns `unverified` or `failed`
- **AND** no backup, delete, switch, configuration write, or automation mutation begins

#### Scenario: Candidate paths are rendered into contract templates
- **WHEN** candidate construction replaces Codex, XiaoH, Vault, or user path placeholders
- **THEN** the run-record template context hash is recomputed from the rendered task-context template
- **AND** the installed templates pass authority-hash validation without manual repair

### Requirement: Create a complete recovery manifest
Immediately before the first managed write, the installer SHALL create and validate a `RecoveryManifest`. Every recoverable item MUST record asset type, source, backup path, restore target, digest, and size. Incomplete backup, path escape, digest failure, or insufficient space MUST stop the transaction.

#### Scenario: Backup verification fails
- **WHEN** any required backup item cannot be copied or its digest cannot be verified
- **THEN** the transaction stops before the first managed write
- **AND** reports the incomplete item and recovery precondition
- **AND** does not mark the backup complete

### Requirement: Execute a compensating transaction
The installer SHALL record `planned`, `candidate_validated`, `backed_up`, `switching`, `verifying`, `committed`, `rolled_back`, and `recovery_required` phases. Each managed write MUST record target, old digest, new digest, phase, and result. A failure after the first write MUST trigger compensating recovery.

#### Scenario: Managed-root switch fails after an earlier write
- **WHEN** one managed root was switched and a later root or configuration write fails
- **THEN** the installer stops subsequent writes
- **AND** restores every recorded changed target in reverse order
- **AND** verifies restored digests
- **AND** returns `rolled_back` only when restoration is complete, otherwise `recovery_required`

### Requirement: Separate deployment from activation
The installation receipt SHALL distinguish `files_installed`, `restart_required`, `trust_required`, `runtime_unverified`, `verified`, and `recovery_required`. A committed file transaction MUST NOT imply that the current Codex process loaded the candidate.

#### Scenario: Files committed but runtime not restarted
- **WHEN** static verification passes and the transaction commits but no new-root runtime Doctor evidence exists
- **THEN** the receipt reports the applicable restart and trust requirements
- **AND** activation remains `runtime_unverified`
- **AND** does not report `verified`

### Requirement: Make installation and update idempotent
Repeated setup or update with the same candidate and user inputs SHALL NOT create duplicate Agents, Hook blocks, automation bindings, configuration blocks, or unnecessary file changes.

#### Scenario: Run the same installation twice in isolation
- **WHEN** the same candidate is installed twice into the same temporary target roots
- **THEN** the second plan reports no unnecessary managed changes
- **AND** no duplicate configuration, Agent, Hook, or automation identity exists
- **AND** user customizations remain preserved

### Requirement: Keep repository development isolated from the real machine
All 4.0.0 implementation and verification work SHALL use explicit temporary roots or test Adapters. The work covered by this change MUST NOT install or update the real XiaoH runtime.

#### Scenario: Execute the complete candidate E2E suite
- **WHEN** the E2E suite performs plan, candidate build, backup, switch, verification, receipt, and fault recovery
- **THEN** every write is contained in the test roots
- **AND** real `~/.codex`, real `~/.xiaoh`, the configured Obsidian Vault, plugin cache, and Playbook CLI remain unchanged
- **AND** the final artifact is labelled a code candidate rather than an installed runtime
