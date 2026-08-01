## ADDED Requirements

### Requirement: Validate third-party Skills from a versioned manifest
Third-party Skill governance SHALL use a versioned Manifest containing source repository, fixed commit, license, license digest, comparison dimensions, per-Skill decision, decision evidence, and applicable upstream and adapted digests. The validator MUST implement generic Schema, path, license, digest, and decision checks rather than hardcoding every Skill.

#### Scenario: Adapted Skill content drifts from the audited manifest
- **WHEN** an adapted Skill file changes without a matching Manifest audit update
- **THEN** governance validation fails with the affected Skill and digest mismatch
- **AND** does not fetch or overwrite content from the network

### Requirement: Require a new audit for a new upstream commit
An upstream commit change SHALL require a new comparison audit and recomputed decisions and counts. A previous zero-replacement count or per-Skill conclusion MUST NOT be inherited automatically.

#### Scenario: mattpocock skills advances upstream
- **WHEN** the declared source commit differs from the last accepted audit commit
- **THEN** the candidate remains unverified until all promoted upstream Skills are reassessed
- **AND** new source and adapted digests are recorded before release

### Requirement: Preserve accepted adapted and absorbed capabilities
The 4.0.0 capability baseline SHALL retain the adapted `codebase-design`, `diagnosing-bugs`, `domain-modeling`, `improve-codebase-architecture`, `prototype`, `research`, `resolving-merge-conflicts`, `tdd`, and `wayfinder` Skills. It SHALL retain the accepted method absorption from `ask-matt`, `grill-with-docs`, `implement`, `to-spec`, `to-tickets`, and `grilling` unless a new audited decision replaces one. For the confirmed upstream commit, adding the adapted `code-review` and absorbing `writing-great-skills` and `handoff` yields the derived baseline counts `replace=0`, `adapt_and_add=10`, `absorb_method=8`, and `exclude=4`.

#### Scenario: Skill capability inventory is generated
- **WHEN** the 4.0.0 governed Skill inventory is compared with the accepted source audit
- **THEN** every adapted Skill exists with declared files and adapted digests
- **AND** every absorbed method has a declared XiaoH target and evidence
- **AND** the decision counts match the derived 4.0.0 baseline when the upstream commit is unchanged

### Requirement: Apply Skill quality rules
Every XiaoH Skill SHALL have one primary responsibility, precise invocation conditions, explicit model-invoked or user-invoked behavior, checkable completion criteria, a single source of shared rules, and progressive disclosure for branch-specific references. Pure aliases, duplicate rules, stale sediment, and behavior-neutral instructions MUST be removed.

#### Scenario: Skill quality audit finds duplicate ownership
- **WHEN** two Skills define the same authoritative lifecycle rule or trigger for the same request
- **THEN** the audit identifies one owner
- **AND** the duplicate text is removed or replaced with a context pointer
- **AND** no confirmed capability is lost

### Requirement: Provide explicit single-pass code review
The governed code-review capability SHALL run only when the user explicitly requests review of a fixed commit, branch, tag, or merge-base. It SHALL report standards and confirmed-spec findings separately and SHALL terminate after one review without automatic repair, re-review, Campaign creation, or gate-state mutation.

#### Scenario: User explicitly reviews a non-empty diff
- **WHEN** the user provides or confirms a valid fixed point and the diff is non-empty
- **THEN** the review reports standards findings and spec findings under separate axes
- **AND** identifies a missing spec source instead of inventing one
- **AND** performs no repair and schedules no additional review

#### Scenario: Implementation completes without a review request
- **WHEN** code passes its deterministic implementation gates and the user did not request code review
- **THEN** the workflow does not invoke the code-review capability
- **AND** completion is decided from the confirmed implementation and verification requirements

### Requirement: Absorb handoff quality without creating a second fact source
Task handoff and recall behavior SHALL reference existing Spec, ADR, OpenSpec, commit, and evidence locations instead of duplicating their content, SHALL redact sensitive information, and SHALL state unresolved work and suggested Skills. It MUST NOT create a competing project history.

#### Scenario: An unfinished task is handed off
- **WHEN** a user explicitly requests handoff to another task or session
- **THEN** the handoff links the authoritative artifacts, lists unresolved and blocked work, and redacts sensitive values
- **AND** does not copy accepted requirements into a new authoritative document

### Requirement: Keep non-core upstream Skills outside the core surface
The 4.0.0 core SHALL NOT bundle `grill-me` as a pure alias, `teach` as a separate teaching workspace, or the full `setup-matt-pocock-skills` project configuration flow. Issue/PR `triage` SHALL remain an optional future extension and MUST NOT introduce a second XiaoH task or requirement state machine.

#### Scenario: Core Skill manifest is validated
- **WHEN** the 4.0.0 core Skill manifest is checked
- **THEN** the excluded core Skills are absent
- **AND** no triage label state is used as XiaoH delegation authority or OpenSpec task state
