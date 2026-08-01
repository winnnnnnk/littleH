## ADDED Requirements

### Requirement: Execute independent diagnostics completely
Doctor SHALL execute every diagnostic whose dependencies are available and whose execution remains safe. A failed diagnostic MUST NOT prevent unrelated diagnostics from running.

#### Scenario: Multiple independent faults exist
- **WHEN** plugin, Vault, automation, and Validator faults are present in the same target
- **THEN** Doctor returns a result for each independently executable diagnostic in one report
- **AND** does not stop after the first failure

### Requirement: Report explicit skipped diagnostics
When a diagnostic cannot run because a required fact is absent or continuing would be unsafe, Doctor SHALL return `skipped` with a concrete `skipped_reason`. It MUST NOT treat a skipped diagnostic as passed.

#### Scenario: Runtime Hook evidence is unavailable
- **WHEN** static files can be inspected but current-process Hook evidence is unavailable
- **THEN** static diagnostics still run
- **AND** the runtime Hook diagnostic is marked `skipped` or `unverified` with the missing evidence
- **AND** effective status does not claim an active runtime gate

### Requirement: Return structured diagnostic evidence
Every `DiagnosticResult` SHALL contain diagnostic_id, status, facts, errors, warnings, skipped_reason, remediation, runtime_checked, and duration_ms. `DoctorReport` SHALL aggregate installation status, activation state, diagnostics, errors, warnings, and unresolved items.

#### Scenario: Doctor returns mixed results
- **WHEN** some diagnostics pass, one degrades, and one fails
- **THEN** the report preserves each diagnostic status and evidence separately
- **AND** computes an effective status that reflects the failed and degraded results
- **AND** provides remediation without changing the target

### Requirement: Keep Doctor free of repair side effects
Doctor SHALL diagnose and aggregate only. It MUST NOT install companions, rewrite configuration, update templates, repair files, bind automation, or trigger another Doctor run.

#### Scenario: Doctor finds a repairable configuration drift
- **WHEN** a managed configuration block is missing or drifted
- **THEN** Doctor reports the drift and a remediation action
- **AND** leaves the configuration byte-for-byte unchanged
- **AND** terminates after the single requested run

### Requirement: Verify activation only from current runtime evidence
Doctor SHALL mark activation `verified` only when plugin, loaded Skill, managed runtime, Agent, Hook, Validator, Vault, required automation, and applicable integration evidence all satisfy the confirmed runtime criteria in a new root task.

#### Scenario: Installed version matches but loaded Skill is stale
- **WHEN** configuration reports 4.0.0 but the current process loaded a different Skill version or drifted content
- **THEN** installation may be reported as files installed
- **AND** activation remains `runtime_unverified` or failed
- **AND** Doctor does not mark the runtime `verified`
