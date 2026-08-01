# XiaoH 4.0.0 需求追溯表

这份表只回答三个问题：需求由谁实现、用什么验证、当前证据是否足够。`passed` 表示仓库内已有实现并通过本地确定性验证；`ci_pending` 表示门禁已经配置，但还没有本次远端运行结果。

## 功能需求

| 需求 | 实现证据 | 主要验证 | 状态 |
|---|---|---|---|
| FR-001 产品能力基线 | 能力矩阵、28 个 Skill、5 个专业 Agent、应用用例 | Skill 治理、Doctor、安装和安全测试 | passed |
| FR-002 根身份与委派安全 | `xiaoh_security.delegation`、Validator v2 Schema | 根身份、精确任务名、一次性消费、漂移、角色、`SubagentStart` 上下文、回执和转录测试 | passed |
| FR-003 单向模块架构 | domain、ports、services、capabilities、diagnostics、installation、application、adapters、interface | Python 3.9、显式导入、依赖方向和循环门禁 | passed |
| FR-004 配置、Workspace、Vault、自动化 | 四个独立 Service 和对应 Port/Adapter | 配置导入、最长根、冲突、定制保留、自动化幂等和重复身份测试 | passed |
| FR-005 完整安装计划 | `InstallationPlanner`、`InstallationPlan` v2 | 逐字节只读、资产清单、预计写入和恢复条件测试 | passed |
| FR-006 隔离运行时候选 | `CandidateBuilder` | 独立根拒绝、清单、摘要、权限、模板上下文摘要重绑定和隔离安装测试 | passed |
| FR-007 恢复清单和备份 | `RecoveryManager`、`RecoveryManifest` v2 | 完整备份、摘要、空间和逐阶段故障测试 | passed |
| FR-008 补偿式安装事务 | `TransactionalInstaller`、事务 v2 | 非法阶段、实际写入一次记录、回滚和恢复失败测试 | passed |
| FR-009 用户长期资产 | 配置导入、Vault 合并、自定义 Agent 保留 | 3.1.2 非敏感资产导入和定制保留测试 | passed |
| FR-010 一次完整 Doctor | 11 个独立 Diagnostic、`DoctorRunner` | 混合结果、异常隔离、零写入和完整诊断清单测试 | passed |
| FR-011 部署与激活分离 | ActivationState、安装回执、Loaded Skill 和 Hook 诊断 | 已安装但未加载不得标记 verified 的测试 | passed |
| FR-012 Hook 与 Validator | 薄 Hook 入口、`xiaoh_security`、`xiaoh_validator` | 自检、Codex Hook JSON 契约、只读运行时协议探针、负向授权和 Vault 路径测试 | passed |
| FR-013 第三方 Skill 治理 | Manifest v2、`SkillGovernance` | 固定提交、许可证、摘要漂移和新提交重审测试 | passed |
| FR-014 显式单次代码评审 | `code-review` Skill | 固定比较点、双轴、单次、无修复和无 Campaign 测试 | passed |
| FR-015 全部 Skill 整理 | 通用 Skill 质量门禁、core handoff、recall 导航 | 职责、触发、完成、单一事实源、渐进披露、沉积和 handoff 测试 | passed |
| FR-016 稳定 CLI | 薄 Dispatcher、CLI response v2 | Plan、Setup、Workspace、参数失败和脱敏测试 | passed |
| FR-017 仓库隔离验证 | 显式临时根、假 Port、候选报告 | 默认路径覆盖保护和临时根 E2E 测试 | passed |
| FR-018 删除旧实现 | 公共入口切换到新 interface，旧扁平模块删除 | 旧模块缺失、单一入口和依赖门禁 | passed |
| FR-019 按风险收敛的通用编码流程 | schema 1.6 `execution`、`direct_change`、核心 Skill 与 Validator | 三档通道、误降级、委派收益、验证摘要和 Skill 契约测试 | passed |
| FR-020 根执行绑定与实际写入范围 | `xiaoh_security.execution`、`guard_task_writes.py`、根 Hook | 无绑定、明确越界补丁/命令、shell 逃逸、提交后逃逸和既有改动接管测试 | passed |
| FR-021 来源和验证可核验证据 | task-context/run-record Validator、来源树摘要、范围证明 | 结构空壳、来源漂移、重复验证 ID、日志漂移、必需验证覆盖和范围证明测试 | passed |

## 非功能需求

| 需求 | 实现和验证 | 状态 |
|---|---|---|
| NFR-001 安全与失败关闭 | 路径逃逸、符号链接、绑定过期、上下文漂移、角色不匹配、证明缺失和敏感输出负例 | passed |
| NFR-002 可恢复性 | 所有事务阶段故障注入，区分 rolled_back 与 recovery_required | passed |
| NFR-003 幂等性 | 同输入安装第二次零受管写入；自动化第二次绑定零配置写入 | passed |
| NFR-004 可测试性 | 文件系统、进程、时钟、插件事实和自动化均可替换 | passed |
| NFR-005 可观测性 | Plan、事务、恢复、Doctor、激活和 actual_writes 使用版本化结构 | passed |
| NFR-006 模块深度和局部性 | 单向依赖门禁、无循环、外部副作用集中在 Adapter | passed |
| NFR-007 跨平台 | macOS/Windows 与 Python 3.9/3.11 阻断矩阵已经配置；本地 Python 3.9 macOS 已通过 | ci_pending |
| NFR-008 确定性验证 | compile、测试、Validator、Hook、OpenSpec 均为阻断；CI 类型和 lint 不再允许忽略失败 | ci_pending |
| NFR-009 本机零副作用 | 本次只运行仓库检查、假 Adapter 和临时根测试，没有运行真实 Setup、Update 或运行态 Doctor | passed |
| NFR-010 最小外部依赖 | 4.0.0 运行时只使用 Python 标准库和 Codex 原生边界 | passed |
| NFR-011 流程收敛效率 | 影响面验证、上下文证据复用、完整失败集、根因修复和单次收口 | passed |
| NFR-012 证据不可仅靠自我声明 | 上下文摘要、来源 SHA-256、命令证据、根范围证明和负向伪造测试 | passed |

## 外部接口与过渡

| 范围 | 证据 | 状态 |
|---|---|---|
| IF-001 CLI | `plugins/xiaoh/scripts/xiaoh.py` 只委派给新 interface | passed |
| IF-002 插件管理器 | `companions --runtime` 才执行只读列表；只保留安全字段，不安装、不改缓存 | passed |
| IF-003 文件系统 | FileSystem Port、原子写、锁、真实路径和隔离根 | passed |
| IF-004 Hook 信任与运行时验证 | 只读核对 Hook 注册、信任和摘要，并执行 `SubagentStart` 响应协议探针；激活保持 runtime_unverified，信任由用户完成 | passed |
| IF-005 Vault | 唯一配置 Vault、受管摘要、用户定制保留和路径门禁 | passed |
| IF-006 自动化 | 只绑定已存在任务，保留偏好并读回，不创建或更新外部任务 | passed |
| IF-007 Playbook | 仅允许 `playbook --version` 和 `playbook version check`；版本维护仍属人工边界 | passed |
| IF-008 第三方 Skill Manifest | 固定来源、许可证、提交、摘要、决策和审计证据 | passed |
| IF-009 任务执行与收口证据 | schema 1.6 通道与委派决策、schema 1.2 完成证据摘要 | passed |
| IF-010 根执行绑定与范围证明 | `guard_task_writes.py`、`xiaoh_security.execution`、run-record scope proof 校验 | passed |
| TR-001 至 TR-003 | 行为矩阵、单一路径切换、3.1.2 用户资产 Fixture | passed |
| TR-004 | 4.0.0 可安装代码候选报告 | passed |
| TR-005 | 未执行本机安装、重启、Hook 信任或运行时 Doctor | passed |

## 非目标核对

- 没有保留 2.x 或 3.1.2 的内部运行时、Schema、Hook 信任、委派绑定或事务状态。
- 没有恢复默认代码评审、自动修复、自动复审或 Campaign。
- 没有引入第二套 Workspace、项目历史、需求或任务状态机。
- 没有把 triage、grill-me、teach 或完整 setup-matt-pocock-skills 放入核心能力。
- 没有安装配套插件，没有改变 Playbook CLI，也没有自动信任 Hook。
