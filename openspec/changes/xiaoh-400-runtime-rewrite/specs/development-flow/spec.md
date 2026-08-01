## ADDED Requirements

### Requirement: Select one risk-proportional execution lane
Every coding task SHALL select exactly one `execution_lane`: `fast`, `standard`, or `high_risk`. `artifact_route` SHALL remain the requirement-source decision while `execution_lane` controls implementation and verification depth. The two decisions MUST NOT create a second task state machine.

#### Scenario: A reproduced local defect has no durable semantic change
- **WHEN** the change is low-risk, local, reversible, has clear acceptance, and introduces no business, interface, security, data, transaction, migration, compatibility, or architecture decision
- **THEN** the task may select `execution_lane=fast` and `artifact_route=direct_change`
- **AND** records a non-empty reason and impact-driven verification
- **AND** escalates if implementation discovers a new semantic choice or risk signal

#### Scenario: A high-risk change attempts to use a lighter lane
- **WHEN** the task risk is high or critical
- **THEN** the Validator requires `execution_lane=high_risk`
- **AND** requires full applicable verification rather than impact-only verification

### Requirement: Delegate only when authorized benefit is material
Agent delegation SHALL occur only when the user has authorized Agent use and the bounded specialist task has a stated material professional, parallel, or write-isolation benefit. An execution lane MUST NOT grant delegation authority.

#### Scenario: Delegation has no authorized bounded benefit
- **WHEN** a task records delegation without explicit authorization, a material benefit, a reason, or a target delegated Agent
- **THEN** the Validator rejects the task context
- **AND** XiaoH continues directly when safe or requests the missing authority when delegation is necessary

### Requirement: Converge deterministic verification into one evidence summary
Verification SHALL be derived from changed interfaces, callers, contracts, data or security boundaries, and build dependencies. The first verification pass SHALL complete every independent safe check once and produce one complete failure set. Repairs SHALL target shared root causes, rerun affected checks, and finish with the lane's closeout gates.

#### Scenario: Independent checks find multiple symptoms with one root cause
- **WHEN** the first verification pass reports multiple related failures
- **THEN** XiaoH groups them in one complete failure set
- **AND** repairs the shared root cause instead of starting a new review cycle for each symptom
- **AND** reruns affected checks before the final lane closeout

#### Scenario: A completed task is recorded
- **WHEN** a schema 1.2 run record uses `status=completed`
- **THEN** its outputs include conclusion, changed scope, verification summary, and unresolved items
- **AND** the user receives remaining risk without an automatic code-review invocation

### Requirement: Bind completion to source and verification evidence
Required task sources SHALL carry current path-type and digest evidence. Each required verification SHALL have a stable identifier, category, command, expected result, and evidence requirement. A completed run MUST cover every required verification with matching command, zero exit status, bounded timestamps, and an existing evidence artifact whose digest is valid.

#### Scenario: A run self-asserts a passing verification
- **WHEN** a completed run marks a verification as passed but omits the evidence artifact, uses a different command, or provides a drifting digest
- **THEN** the Validator rejects task closure
- **AND** no review or natural-language summary can replace the missing deterministic evidence

#### Scenario: A required source changes after task authorization
- **WHEN** a required file or directory digest no longer matches the task context
- **THEN** the task context is stale and must be refreshed before side effects continue
