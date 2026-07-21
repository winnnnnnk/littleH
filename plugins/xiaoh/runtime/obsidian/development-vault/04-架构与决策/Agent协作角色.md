---
status: active
source_of_truth: __CODEX_HOME__/AGENTS.md + __CODEX_HOME__/agents
last_validated: 2026-07-18
tags:
  - agents
  - collaboration
  - governance
---

# Agent 协作角色

更新时间：2026-07-18

## 总体原则

- 用户统一与小H沟通，小H负责需求理解、上下文选择、任务拆分、调度、冲突裁决、验收和汇报。
- 全局 Agent 是跨客户、跨项目复用的能力角色；永久定义中不保存具体客户、项目、仓库、分支或环境信息。
- 所有角色的公共执行职责以 `__CODEX_HOME__/AGENTS.md` 中的 `Global Agent Common Contract` 为准，本页不复制执行规则。
- 全局 `AGENTS.md` 是根线程小H的执行事实源；各 Agent TOML 只定义可委派的专业子 Agent；本页是供人阅读的目录与调度说明。
- 角色阶段、使用反馈和配置改进记录：[[Agent进化台账]]。
- 任务上下文包、运行证据与自动校验协议：`__CODEX_HOME__/agent-system/README.md`。
- 专业 Agent 是常驻配置，不是常驻运行进程；只有任务需要时才启动。
- 默认最多同时运行 4 个 Agent 线程，子 Agent 不再递归创建下级 Agent。
- 同一个 repo/worktree 同一时间只允许一个实现 Agent 写入。
- 使用完成当前目标所需的最少角色；一次性客户知识、特殊算法或专项排障使用临时 Agent。
- 高风险设计或实现必须由未承担该实现的适用判断角色独立评审，小H负责综合但不替代专业判断。

## 全局角色

| Agent | 角色类型 | 核心职责 | Sandbox | 典型触发场景 |
|---|---|---|---|---|
| `xiaoh` | 根线程协调者/判断者（非 TOML Agent） | 用户沟通、需求理解、上下文路由和总控验收 | `inherit-current-task` | 所有长期工作入口；禁止作为子 Agent 创建 |
| `pki_domain_expert` | 思考者/判断者 | PKI 领域语义、标准符合性和验收约束 | `read-only` | 证书、密钥、信任和生命周期问题 |
| `java_architect` | 思考者/判断者 | 架构边界、依赖、技术方案和取舍 | `read-only` | 新功能、系统改造、跨边界影响 |
| `java_code_explorer` | 思考者/取证者 | 代码入口、调用链、数据流和影响面证据 | `read-only` | 代码理解、故障定位、改动前分析 |
| `java_implementer` | 执行者 | Java 实现与单仓验证 | `workspace-write` | 已确认的 Java 编码任务 |
| `frontend_implementer` | 执行者 | 前端实现与验证 | `workspace-write` | 前端应用、页面或共享组件任务 |
| `test_integration_verifier` | 执行者/判断者 | 验收矩阵、授权范围验证和集成证据审计 | `workspace-write` | 实现后验证和交付门禁 |
| `code_quality_reviewer` | 判断者 | 正确性、回归、并发、性能和测试缺口评审 | `read-only` | 实现完成后的独立评审 |
| `pki_security_reviewer` | 判断者 | PKI 和密码安全专项评审 | `read-only` | 涉及密钥、证书、算法和信任边界 |

## 默认组合

| 任务类型 | 默认角色组合 |
|---|---|
| 需求/领域分析 | 小H + PKI 领域专家；复杂系统增加 Java 架构专家 |
| 单仓 Java 功能 | 小H + 代码探索 + Java 实现 + 测试验证 |
| 跨仓改造 | 小H + Java 架构 + 代码探索；实现阶段按独立 repo 分派实现 Agent |
| PKI 安全敏感变更 | 常规组合 + PKI 安全评审 |
| 前后端联动 | 小H + Java 架构 + Java 实现 + 前端实现，分 repo 写入 |
| 交付前评审 | 小H + 代码质量评审 + 测试验证；安全敏感时增加 PKI 安全评审 |

## 临时 Agent 使用条件

- 某一客户或版本特有知识，不值得全局复用。
- 只在一次任务中使用的算法、协议、数据迁移或故障场景。
- 需要大量同类只读盘点，可以拆成相互独立的批次。
- 临时 Agent 必须有明确输入、允许范围、输出格式和结束条件；结果经小H验收后，仅把长期有效的确认事实写入上下文。

## Playbook 关系

- 全局 Agent 定义可复用能力，不复制具体 workspace 的状态机和命令。
- 进入 Playbook 受管环境后，小H按 workspace 规则、runtime/worker 返回和 task state 调度角色。
- 专业 Agent 是叶子执行者、思考者或判断者，不绕过 Playbook 推进任务状态和交付生命周期。

## 可执行契约

- 小H使用 `__CODEX_HOME__/agent-system/task-context.template.json` 形成任务级上下文包；Playbook 受管任务以 worker/task 返回为状态事实源，模板不覆盖其内容。
- 正式委派和高风险直接执行使用 `__CODEX_HOME__/agent-system/run-record.template.json` 记录角色选择、上下文版本、门禁、验证、返工与改进候选。
- 正式委派消息必须绑定 `task_id`、任务上下文绝对路径、SHA-256 和已登记专业角色；高风险任务只有在实现与独立评审完成记录通过 closure 校验后才能收口。
- 工具层必须同时提供匹配的 `agent_type`，运行转录中的 `session_meta.source.subagent.thread_spawn.agent_role` 也必须证明该角色；缺少这一证据的通用子线程只能提供咨询意见，不能记为专业 Agent 完成记录。
- Agent TOML 或本角色目录变化后执行 `python3 __CODEX_HOME__/agent-system/validate.py`，检查角色注册、权限声明和目录漂移。
- 代表性调度基线位于 `__CODEX_HOME__/agent-system/routing-cases.json`；它检查最小角色集合，不替代 Playbook 对顺序、并发和 worktree 的决定。
- 运行记录保存在任务 evidence，Vault 只记录稳定结论和阶段性进化摘要。
- 表格中的 `Sandbox` 使用 TOML 原始机器值；校验器会阻止 TOML 与本页权限说明发生漂移。
