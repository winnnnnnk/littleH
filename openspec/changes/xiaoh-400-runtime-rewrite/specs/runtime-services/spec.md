## ADDED Requirements

### Requirement: Centralize configuration ownership
The configuration service SHALL own configuration loading, Schema validation, locking, merging, backup-aware atomic writing, and path resolution. Other services MUST NOT duplicate these rules.

#### Scenario: Concurrent configuration update
- **WHEN** an application use case updates XiaoH configuration
- **THEN** the configuration service validates the current document, acquires the configured lock, applies one merge, and performs one atomic write
- **AND** invalid configuration stops the use case before unrelated managed writes begin

### Requirement: Resolve Workspace ownership consistently
The Workspace service SHALL own registration, cross-platform bindings, conflict detection, longest-root resolution, and project/system ownership. A path MUST NOT resolve to more than one equally strong Workspace.

#### Scenario: Workspace path has one strongest owner
- **WHEN** a path is resolved against registered active-platform bindings
- **THEN** the service returns the unique longest matching Workspace
- **AND** an equal-strength ownership conflict returns a failed or conflict result without guessing

### Requirement: Protect Vault user content
The Vault service SHALL distinguish user content, managed templates, and historical content. It MUST NOT silently overwrite a managed template that the user changed outside an accepted managed hash, and it MUST resolve the configured real Vault path before a write.

#### Scenario: Managed template contains user customization
- **WHEN** the installed template digest is not the current managed digest, a declared legacy digest, or the last applied managed digest
- **THEN** the service records a customization conflict
- **AND** preserves the user's file
- **AND** reports a degraded or unresolved result rather than overwriting it

### Requirement: Reconcile automation by stable logical identity
The automation service SHALL manage templates, stable logical identity, user schedule and notification preferences, binding, readback verification, and duplicate detection. An unavailable automation store MUST NOT be reported as a successful binding.

#### Scenario: Repeated automation reconciliation
- **WHEN** reconciliation runs twice with the same template and existing stable binding
- **THEN** no duplicate task is created
- **AND** user-controlled schedule, time zone, notification, and enablement preferences remain unchanged
- **AND** the second readback matches the expected managed fields

### Requirement: Import only user durable assets
The 4.0.0 clean-install import SHALL support Vault user notes, non-managed templates, Workspace registrations, user preferences, custom Agents, automation preferences, and non-sensitive integration references. It MUST NOT import old Hook files, Validator files, temporary delegation bindings, receipts, unfinished transactions, review state, passwords, tokens, cookies, or private keys.

#### Scenario: Import a 3.1.2 user-asset fixture
- **WHEN** the importer receives a validated 3.1.2 fixture containing both user assets and old managed state
- **THEN** only allowlisted user durable assets appear in the candidate result
- **AND** old managed runtime and authorization evidence are excluded
- **AND** each imported item records its source, conversion version, result, and conflict status

### Requirement: Respect external ownership boundaries
The runtime services SHALL treat the Codex plugin manager as the owner of plugin installation and cache switching, Hook trust as a user action, and Playbook CLI version maintenance as a user-only action.

#### Scenario: External integration reports a version or source problem
- **WHEN** the plugin source or Playbook version cannot be verified
- **THEN** XiaoH reports the observed facts, impact, and required manual action
- **AND** does not rewrite the plugin cache, install a Playbook version, or claim Hook trust
