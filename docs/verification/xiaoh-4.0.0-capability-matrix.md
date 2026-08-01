# XiaoH 4.0.0 能力与验证矩阵

这份矩阵把 3.1.2 已确认的产品能力映射到 4.0.0 的实现和确定性验证。它只说明仓库候选代码，不代表本机运行时已经安装或激活。

| 能力 | 4.0.0 所有者 | 主要验证 |
|---|---|---|
| 根任务承担 `xiaoh` 身份，且不能委派同名子 Agent | 全局契约、委派安全内核 | `test_reserved_root_identity_cannot_be_prepared`、Validator 全局校验 |
| 五个专业 Agent 的固定清单和路由 | Agent 清单、任务上下文 Validator | Doctor Agent 诊断、隔离安装清单测试、任务上下文模板校验 |
| 意图域、事实分类、需求路由和用户确认 | 全局契约、需求 Skill、Validator | Validator 自检、任务上下文和需求门禁校验 |
| Spec+RFC 准入和 Spec/OpenSpec 一致性检查 | `spec-rfc-reviewer`、`spec-rfc-openspec-consistency-review` | Skill 质量治理、单次执行约束 |
| 工程分析、设计、TDD、诊断、原型、研究和领域建模 | 对应类 Skill 和专业 Agent | Skill 来源 Manifest、Skill 质量审计、五 Agent 清单测试 |
| Workspace 注册、平台绑定和唯一最长根解析 | `WorkspaceService` | 最长根和等强冲突测试 |
| 用户长期配置和 3.1.2 持久资产导入 | `ConfigurationService` | 敏感字段剔除、旧绑定和事务证据拒绝测试 |
| Vault 模板同步、用户内容和兼容工作台定制保留 | `VaultService` | 自定义工作台保留、托管摘要和路径安全测试 |
| 项目召回、需求基线、任务收口、项目进度和知识晋升 | 现有知识类 Skill | Skill 质量治理、Vault 模板清单、全局契约 |
| 每日成果自动化的稳定逻辑身份和偏好保留 | `AutomationService`、自动化存储 Port | 绑定读取、模板一致性、缺失和重复状态诊断 |
| Plan、Setup、Update 和 Doctor | 应用层、事务安装器、Doctor | 只读 Plan、阶段故障注入、补偿恢复、幂等和完整诊断测试 |
| 一次性 Agent 委派和完成证明 | `xiaoh_security.delegation` | 精确 `task_name`、原子消费、漂移、角色、`SubagentStart` 上下文协议、回执和转录负例 |
| 单一 Obsidian Vault 写入范围 | `xiaoh_security.vault_guard` | 其他 Vault、上级跳转和符号链接逃逸负例 |
| Playbook 可选只读适配 | Doctor、`playbook_adapter.py` | 命令策略测试、只读版本探测、禁止版本变更契约 |
| 用户显式代码评审 | `code-review` Skill | 固定比较点、标准轴和需求轴、单次只报告约束测试 |
| 三档通用编码流程和低风险直接改动 | `xiaoh-core`、需求路由、任务上下文 Validator | 通道误降级、`direct_change` 风险信号、Agent 收益和验证摘要测试 |
| 根任务写入授权、真实范围证明和来源/验证证据闭环 | `xiaoh_security.execution`、`guard_task_writes.py`、Validator | 越界补丁/命令、shell/提交逃逸、既有改动接管、来源/日志摘要漂移和完成覆盖测试 |
| mattpocock/skills 吸收和后续漂移控制 | `SkillGovernance` | 固定提交、许可证、摘要、`0/10/8/4` 决策和新提交重审测试 |

## 4.0.0 有意断开的内部兼容

4.0.0 不读取或恢复 2.x 和 3.1.2 的 Hook 信任、一次性绑定、委派证明、安装事务、旧模块入口或内部 Schema。它只导入明确允许的用户长期配置、Workspace 身份、Vault 内容和自动化偏好。公共命令继续保留 `plan`、`setup`、`update`、`ensure-runtime`、`doctor`、`companions`、Workspace 和自动化概念，机器响应统一使用 `xiaoh-cli-response/v2`。
