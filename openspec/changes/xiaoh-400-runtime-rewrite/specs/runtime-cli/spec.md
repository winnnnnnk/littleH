## ADDED Requirements

### Requirement: Preserve stable command concepts through a thin entrypoint
The XiaoH CLI SHALL retain plan, setup, update, doctor, workspace, and automation command concepts. The executable entrypoint SHALL parse arguments, call one application use case, normalize the response, and choose an exit code without implementing domain or transaction rules.

#### Scenario: CLI dispatches a doctor request
- **WHEN** a caller invokes Doctor with explicit roots and output mode
- **THEN** the entrypoint constructs the request and calls the Doctor application use case once
- **AND** formats the returned report without reimplementing diagnostic policy

### Requirement: Return a common structured response envelope
Every CLI command SHALL return schema_version, status, operation, errors, warnings, actual_writes, unresolved_items, and recovery_conditions. Missing list fields SHALL normalize to empty lists without discarding command-specific payload fields.

#### Scenario: A read-only command succeeds without writes
- **WHEN** plan or Doctor returns a successful command-specific payload
- **THEN** the normalized response contains the common fields
- **AND** `actual_writes` is empty
- **AND** the command-specific facts remain present

### Requirement: Report installation and recovery facts accurately
Setup and update responses SHALL include transaction_id, phase, backup, recovery, and activation_state. `actual_writes` MUST equal the recorded successful managed writes and MUST NOT be a placeholder.

#### Scenario: Installation rolls back after two writes
- **WHEN** a transaction records two successful writes and then completes compensation
- **THEN** the response identifies both writes, the failed phase, the recovery actions, and `rolled_back`
- **AND** does not report `committed` or `verified`

### Requirement: Convert expected failures into stable errors
Argument, path, configuration, candidate, transaction, diagnostic, and integration failures SHALL produce stable structured errors and exit codes. Normal failure reporting MUST NOT expose an uncontextualized traceback.

#### Scenario: CLI receives an invalid configuration path
- **WHEN** the requested configuration cannot be parsed or validated
- **THEN** the command returns `failed` with a contextual error and non-zero exit code
- **AND** performs no managed write
- **AND** does not print a raw traceback as the normal response

### Requirement: Label repository output as a code candidate
Until a separately authorized real installation and runtime Doctor succeed, the 4.0.0 repository artifact SHALL be described as a code candidate. CLI tests and release evidence MUST NOT claim that the current machine runs 4.0.0.

#### Scenario: Repository acceptance gates pass
- **WHEN** all 4.0.0 repository and isolated-environment gates pass
- **THEN** the release evidence reports the artifact as an installable code candidate
- **AND** reports that local installation, restart, trust, and runtime verification were not performed
