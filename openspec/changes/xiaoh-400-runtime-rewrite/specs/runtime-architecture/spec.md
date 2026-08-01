## ADDED Requirements

### Requirement: Preserve the confirmed product baseline
The XiaoH 4.0.0 runtime SHALL preserve the confirmed XiaoH 3.1.2 product outcomes while replacing the internal implementation. The baseline MUST cover root identity, the five specialist Agents, formal delegation, requirement routing, Workspace, Vault, knowledge workflows, automation, optional Playbook read integration, and the confirmed Skill capability surface.

#### Scenario: Candidate preserves every baseline capability
- **WHEN** the 4.0.0 candidate is evaluated against the product capability inventory
- **THEN** every confirmed capability has a passing contract test or executable verification
- **AND** no capability is removed solely because its 3.1.2 implementation was deleted

### Requirement: Enforce directional module dependencies
The runtime SHALL separate domain, application, ports, adapters, installation, diagnostics, capabilities, runtime services, and interface responsibilities. Modules MUST use explicit imports and MUST NOT contain prohibited dependency directions or import cycles.

#### Scenario: Dependency gate checks the candidate
- **WHEN** the repository dependency gate analyzes the 4.0.0 runtime
- **THEN** no runtime module uses a star import
- **AND** no lower layer imports the CLI interface or a concrete external Adapter
- **AND** no module cycle is reported

### Requirement: Isolate external side effects behind ports
The domain and application rules SHALL access file systems, processes, clocks, plugin-manager facts, and automation storage through explicit Ports. Domain code MUST NOT read environment variables, invoke subprocesses, or resolve real user paths directly.

#### Scenario: Core rules run with test adapters
- **WHEN** unit and application tests provide in-memory or temporary-directory Adapters
- **THEN** planning, state transitions, diagnostic aggregation, and recovery decisions execute without accessing a real Codex installation

### Requirement: Preserve cross-platform behavior with minimal dependencies
The runtime SHALL support the existing macOS, Windows, and Python compatibility range and SHALL prefer the Python standard library and Codex-native capabilities. A new runtime dependency MUST have documented functional, security, or cross-platform necessity.

#### Scenario: Cross-platform candidate validation
- **WHEN** CI runs the supported Python matrix on macOS and Windows
- **THEN** syntax, unit, contract, integration, entrypoint, and isolated-install checks pass
- **AND** no macOS-only path or file-system assumption is required

### Requirement: Remove the legacy production implementation
After the new implementation passes all candidate gates, every public production entrypoint SHALL invoke only the 4.0.0 implementation. The repository MUST NOT retain a second executable legacy runtime, 2.x compatibility branch, or removed review lifecycle.

#### Scenario: Final candidate has one production path
- **WHEN** the final dependency and source inventory is generated
- **THEN** all public entrypoints resolve to the 4.0.0 implementation
- **AND** no legacy runtime callsite, old review Campaign, or P0/R1/R2/P3 lifecycle asset remains
- **AND** Git history remains the code rollback mechanism
