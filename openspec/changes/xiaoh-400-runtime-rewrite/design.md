## Context

XiaoH 3.1.2 已完成产品能力收敛和初步模块化，但当前 Python 运行时仍通过星号导入和交叉依赖共享实现细节。`plugin_state.py` 同时处理插件事实、Skill 来源、配套能力和 Playbook，Doctor 将大量诊断集中在一个函数中，安装器则在备份后直接修改目标路径。

本设计以 `docs/spec-rfc/xiaoh-4.0.0-runtime-rewrite.md` 修订 4 为唯一需求源。目标版本是 XiaoH 4.0.0。它保留 3.1.2 的产品能力和用户长期资产导入语义，但不保留旧内部运行时、安装状态、事务证据或内部 Schema 兼容。

本 change 的交付边界是仓库内可安装候选。开发和验证不得修改真实 `~/.codex`、`~/.xiaoh`、真实 Obsidian Vault、插件缓存或 Playbook CLI。

## Goals / Non-Goals

**Goals:**

- 将运行时重建为单向分层、显式依赖和可替换外部 Adapter。
- 固定 3.1.2 产品行为和 Hook/Validator 安全不变量，再替换内部实现。
- 建立完整安装计划、隔离候选、恢复清单、补偿事务和激活状态。
- 让 Doctor 一次聚合全部可安全执行的独立诊断。
- 将第三方 Skill 来源与决策改为 Manifest 驱动。
- 整理 XiaoH Skill，并提供显式、单次、非门禁的代码评审。
- 以三档执行通道降低低风险编码成本，并通过直接改动、Agent 收益和验证收敛契约防止误降级。
- 通过临时目录、故障注入、幂等和跨平台测试形成 4.0.0 候选。
- 验收后删除旧生产实现。

**Non-Goals:**

- 不安装、升级或切换本机 XiaoH。
- 不重启 Codex，不请求 Hook 信任，不运行真实激活验收。
- 不恢复 2.x 或 3.1.2 内部兼容。
- 不恢复旧代码评审 Campaign、P0/R1/R2/P3 生命周期或自动重评。
- 不把 Issue/PR triage、教学工作台或第二套项目设置纳入核心。
- 不修改 Codex 插件缓存或 Playbook CLI。
- 不引入远程服务、数据库或无必要第三方运行时依赖。

## Decisions

### 1. 采用单向分层和 Ports/Adapters

目标结构：

```text
interface
    ↓
application
    ↓
domain ← installation / diagnostics / capabilities
    ↑
ports
    ↑
adapters
```

- `domain` 保存纯状态、规则、结果和状态转换。
- `application` 编排 setup、update、doctor、workspace 和 automation 用例。
- `ports` 定义文件系统、进程、时钟、插件管理器和自动化存储接口。
- `adapters` 实现本地文件系统及 Codex 集成。
- `installation` 管理安装计划到恢复的生命周期。
- `diagnostics` 提供彼此独立、无修复副作用的诊断器。
- `capabilities` 管理插件事实、配套能力和第三方 Skill 治理。
- `interface` 只处理 CLI 参数和输出。

选择这一方案是为了让核心规则在临时环境和模拟 Adapter 中完整验证。继续使用共享 `common.py` 与星号导入无法形成可信边界；按函数拆文件则会产生浅模块。

### 2. 以行为契约保留产品能力

4.0.0 不复制 3.1.2 内部结构。重写前先按根身份、CLI、Agent、Skill、Hook、Validator、Workspace、Vault、自动化和 Playbook 固定产品行为测试。新实现以这些行为和已确认 Spec 为准。

开发期间允许旧实现作为测试参照存在。所有公共入口切换到新实现并通过验收后，旧生产实现必须删除。

### 3. 安装采用隔离候选和跨根补偿事务

安装流程：

```text
Resolve
→ Plan
→ Build Candidate
→ Validate Candidate
→ Create Recovery Manifest
→ Backup
→ Switch Managed Roots
→ Write Configuration
→ Static Doctor
→ Commit Receipt
→ Await Restart/Trust
→ Runtime Doctor
→ Verified
```

每个受管根尽量通过同一父目录中的重命名实现局部原子切换。Codex、Vault 和 XiaoH 配置可能跨文件系统，因此全局一致性由事务日志和补偿恢复维护，不宣称全局原子。

`InstallationPlan` 记录预计变更，`RecoveryManifest` 记录可恢复备份，`InstallationTransaction` 记录阶段和实际写入，`InstallationReceipt` 记录最终状态和激活要求。

第一次受管写入前失败时丢弃候选。第一次写入后失败时停止后续写入，并按事务反向恢复。恢复摘要完全匹配时返回 `rolled_back`；无法完整恢复时返回 `recovery_required`。

### 4. Doctor 采用完整诊断聚合

Doctor 接收诊断器集合并执行所有依赖满足且安全的诊断。单个诊断失败不阻止其他独立诊断。只有依赖缺失或继续执行不安全时，关联诊断返回 `skipped` 和原因。

每项 `DiagnosticResult` 包含 diagnostic_id、status、facts、errors、warnings、skipped_reason、remediation、runtime_checked 和 duration_ms。Doctor 只聚合并计算 effective_status，不修复问题。

### 5. 部署状态与激活状态分离

至少使用以下状态：

- `files_installed`
- `restart_required`
- `trust_required`
- `runtime_unverified`
- `verified`
- `recovery_required`

安装事务提交只证明文件部署结果。只有用户人工完成必要的重启和 Hook 信任，并在新根任务运行运行时 Doctor 通过后，状态才是 `verified`。

### 6. Hook 与 Validator 先固定安全契约再重写

需要保持的安全不变量包括：根身份保护、任务上下文 Schema、运行记录 Schema、路由校验、一次性 execution binding、原子消费、角色匹配、随机回执、转录证明和 Vault 写入范围校验。

Hook 或 Validator 的拆分不能把一个原子安全判断拆成可绕过的窗口。来源、路径、权限、绑定或证据不可信时必须失败关闭。

### 7. 第三方 Skill 治理由 Manifest 驱动

Manifest 保存来源仓库、固定提交、许可证、来源摘要、逐 Skill 决策和决策证据。`adapt_and_add` 保存上游与改造后摘要，`absorb_method` 保存目标，`exclude` 保存理由。

通用校验器只验证 Schema、路径、许可证、摘要和决策一致性，不硬编码每一个 Skill。上游提交变化必须重新审核，系统不自动覆盖已经审核的 Skill。

### 8. Skill 整理和代码评审边界

全部 Skill 根据触发条件、职责、上下文成本、完成条件、单一事实源和渐进披露重新审核。

`code-review` 作为用户显式调用的单次能力加入。它固定比较点，将规范轴和需求轴分开报告，结束后不自动修复、不自动重评、不创建 Campaign，也不成为实现门禁。

`writing-great-skills` 的方法进入 Skill 质量规则。`handoff` 的引用既有工件、脱敏和未完成状态表达进入现有交接与召回能力。`triage` 保持核心范围外。

在已确认上游提交不变时，22 个正式 Skill 的 4.0.0 决策数量由已确认逐项决定推导为：`replace=0`、`adapt_and_add=10`、`absorb_method=8`、`exclude=4`。如果发布前上游提交变化，这些数量必须重新计算，不能作为新提交的预设结论。

### 9. CLI 保持薄入口和统一响应

保留 plan、setup、update、doctor、workspace 和自动化命令概念。公共响应外壳包含 schema_version、status、operation、errors、warnings、actual_writes、unresolved_items 和 recovery_conditions。

安装响应增加 transaction_id、phase、backup、recovery 和 activation_state。CLI 不维护领域规则和事务转换。

### 10. 隔离验证和质量门禁

所有安装、更新、Doctor、自动化和用户资产导入测试必须显式使用临时路径或模拟 Adapter。测试不得通过默认路径落入真实用户目录。

CI 覆盖单元、契约、集成、E2E、故障注入、幂等、类型检查、lint 和跨平台验证。适用门禁不得使用 `continue-on-error` 掩盖失败。

### 11. 工件路由与执行通道正交

`artifact_route` 只回答需求事实源是什么，`execution_lane` 只回答实现和验证投入多少。系统使用 `fast`、`standard` 和 `high_risk` 三档；两者不创建另一套任务状态机。

只有低风险、局部、可逆、验收明确且不产生新持久语义的改动可以使用 `direct_change`。发现业务、接口、安全、数据、事务、迁移、兼容或架构选择时立即升级工件路由和执行通道。

Agent 默认不使用。只有用户已授权，且专业能力、并行发现或写入隔离对明确边界带来实质收益时才正式委派。执行通道不能替代授权。

验证从变更影响面推导。首轮完成全部独立安全检查并形成一个完整失败集，随后按共同根因修复、重跑受影响检查，最后执行通道收口门禁。完成记录提供一次验证证据摘要。代码评审仍只在用户明确要求时单次触发。

### 12. 权限、范围和完成使用可复算证据

schema 1.6 任务上下文完整校验 behavior、scope、sources、decisions、verification 和 output contract。必需来源记录 file/directory 类型和 SHA-256；验证项记录稳定 ID、类别、命令、期望和必需标记。实现通道至少包含 scope 类别，高风险通道还要求 contract 与 security 类别。

根任务在写入前生成 `xiaoh-root-execution-binding/v1`：绑定当前上下文摘要、允许路径、明确接管的既有改动、仓库 HEAD 和 dirty/untracked 文件摘要。Hook 对 `apply_patch` 和能够可靠识别目标的常见写命令做前置拒绝。任意 shell 的最终权限结论不依赖命令解析，而由 Git status、文件摘要和绑定前后提交差异形成 `xiaoh-root-scope-proof/v1`。

schema 1.2 完成记录中的通过项必须提供验证 ID、类别、原命令、零退出码、起止时间、证据文件和摘要。根实现任务还必须引用通过的范围证明，且 `outputs.changed_scope` 与证明中的真实路径完全一致。

委派策略使用根任务范围的子集，并显式记录 `read_only`。多个写 Agent 路径不得相交；只读 Agent 可以共享读取范围。该约束进入一次性绑定和 `SubagentStart` effective brief。

## Risks / Trade-offs

- [全面重写造成功能倒退] → 重写前冻结 3.1.2 产品行为和安全契约，按能力建立追溯测试。
- [分层过度导致浅接口] → 只为真实外部副作用和独立变化原因建立 Port，不按函数机械拆分。
- [补偿恢复实现不完整] → 对候选、备份、每个切换阶段、配置、Vault、Doctor 和恢复本身执行故障注入。
- [跨平台重命名或文件占用差异] → 在 Adapter 层处理平台差异，并在 macOS、Windows CI 验证。
- [Doctor 输出过多] → 结构化分组并提供 remediation，但不恢复首错退出。
- [代码评审重新演变为门禁] → 通过显式触发、单次终止和禁止自动修复的契约测试固定边界。
- [Skill Manifest 被当作自动更新源] → Manifest 只描述已审核固定来源，不允许运行时远程覆盖。
- [测试误写真实本机] → 集成入口要求显式根路径，并增加真实路径保护测试。
- [快速通道掩盖真实风险] → Validator 限定低风险、影响面验证和无风险信号，发现新语义立即升级。
- [Agent 协调成本超过收益] → 同时要求用户授权、明确实质收益和目标 Agent。
- [验证失败逐个暴露] → 首轮聚合全部独立安全检查，按共同根因修复并只重跑受影响检查。
- [通用 shell 解析产生虚假安全感] → 只把确定目标检查作为前置减险，最终使用真实 Git 状态、摘要和提交差异证明净改动。
- [新绑定增加流程成本] → 只在实现写入时准备一次、收口时证明一次，不增加代码评审或重复全量检查。

## Source Traceability

| Source | OpenSpec capability | Implementation task groups |
|---|---|---|
| FR-001 | `runtime-architecture` | 1, 10 |
| FR-002 | `runtime-security` | 1, 6 |
| FR-003 | `runtime-architecture` | 2 |
| FR-004 | `runtime-services` | 5 |
| FR-005 | `transactional-installation` | 4 |
| FR-006 | `transactional-installation` | 4 |
| FR-007 | `transactional-installation` | 4 |
| FR-008 | `transactional-installation` | 4 |
| FR-009 | `runtime-services`, `transactional-installation` | 4, 5 |
| FR-010 | `complete-doctor` | 3 |
| FR-011 | `transactional-installation`, `complete-doctor` | 3, 4 |
| FR-012 | `runtime-security` | 1, 6 |
| FR-013 | `governed-skills` | 7 |
| FR-014 | `governed-skills` | 7 |
| FR-015 | `governed-skills` | 7 |
| FR-016 | `runtime-cli` | 8 |
| FR-017 | `transactional-installation` | 1, 9, 10 |
| FR-018 | `runtime-architecture` | 10 |
| FR-019 | `development-flow`, `runtime-security`, `governed-skills` | 6, 7, 8 |
| FR-020 | `runtime-security`, `development-flow` | 6, 8, 9 |
| FR-021 | `development-flow`, `runtime-security` | 6, 8, 9 |
| NFR-001 | `runtime-security` | 1, 6 |
| NFR-002 | `transactional-installation` | 4 |
| NFR-003 | `transactional-installation`, `runtime-services` | 4, 5 |
| NFR-004 | `runtime-architecture` | 2 |
| NFR-005 | `transactional-installation`, `complete-doctor`, `runtime-cli` | 3, 4, 8 |
| NFR-006 | `runtime-architecture` | 2 |
| NFR-007 | `runtime-architecture` | 2, 9 |
| NFR-008 | `runtime-architecture`, `runtime-cli` | 9 |
| NFR-009 | `transactional-installation` | 1, 9, 10 |
| NFR-010 | `runtime-architecture` | 2 |
| NFR-011 | `development-flow` | 7, 9 |
| NFR-012 | `runtime-security`, `development-flow` | 6, 8, 9 |
| IF-001 | `runtime-cli` | 8 |
| IF-002 | `runtime-services` | 5 |
| IF-003 | `runtime-architecture`, `transactional-installation` | 2, 4 |
| IF-004 | `transactional-installation`, `complete-doctor`, `runtime-security` | 3, 4, 6 |
| IF-005 | `runtime-services` | 5 |
| IF-006 | `runtime-services` | 5 |
| IF-007 | `runtime-services`, `runtime-security` | 5, 6 |
| IF-008 | `governed-skills` | 7 |
| IF-009 | `development-flow`, `runtime-security` | 6, 8 |
| IF-010 | `runtime-security`, `development-flow` | 6, 8, 9 |
| TR-001 | `runtime-architecture` | 1 |
| TR-002 | `runtime-architecture` | 10 |
| TR-003 | `runtime-services` | 5 |
| TR-004 | `runtime-cli` | 8, 10 |
| TR-005 | `transactional-installation` | 10 |

## Migration Plan

1. 保存并确认 4.0.0 Spec+RFC、共享语言和 ADR。
2. 生成并确认本 OpenSpec change。
3. 在独立代码变更中冻结 3.1.2 行为和安全契约。
4. 建立新分层、领域模型、Ports/Adapters 和依赖门禁。
5. 依次实现插件与 Skill 治理、Doctor、安装事务、运行时服务、Hook/Validator 和 CLI。
6. 整理 Skill 并加入受限版代码评审。
7. 完成故障注入、幂等和跨平台隔离验证。
8. 切换公共入口并删除旧生产实现。
9. 形成 4.0.0 可安装候选并停止，不安装本机。
10. 固化三档执行通道、直接改动、Agent 收益门槛和收敛式验证证据。
11. 固化根执行绑定、委派路径隔离、受控验证证据和真实 Git 范围证明。
11. 固化根执行绑定、真实范围证明、来源摘要、验证日志和委派路径隔离。

代码层回滚使用 Git 提交边界。未来真实安装的回滚由 RecoveryManifest 和 InstallationTransaction 负责，但不在本 change 的执行授权范围内。

## Open Questions

无阻塞性开放问题。实际本机安装、重启、Hook 信任和运行时 Doctor 需要未来单独授权，不属于当前 change。
