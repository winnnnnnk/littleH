# xiaoh稳定任务授权与单次执行绑定分离 Spec+RFC

- 状态：Accepted
- 修订：1
- 目标版本：2.16.0
- 意图域：`global_agent_capability`
- 确认日期：2026-07-27

## 1. 背景

xiaoh 2.15.0 的任务上下文同时保存长期任务授权、具体 `task_name`、Playbook
短时收据和运行期证据。多轮独立评审要求同一角色启动多个真实 Agent
会话，而 Codex 协作运行时不允许重复创建相同的子任务名称。刷新
`task_name` 或 Playbook 收据又会改变完整任务上下文哈希，使前一轮已认证证据
失效，导致“必须多轮评审”与“一个角色只能使用一个固定名称及上下文哈希”形成
循环依赖。

这不是 Playbook 安装依赖问题，也不应通过放宽独立评审、伪造 Agent 身份、
延长短时凭证或复制 Playbook 状态解决。

## 2. 目标

1. 任务的稳定授权在多轮评审、Agent 重启和 Playbook 收据刷新之间保持不变。
2. 每次正式 Agent 启动都获得唯一、短时、一次性的执行绑定。
3. 独立模式与 Playbook 受管模式共享同一本地评审生命周期。
4. Playbook 继续独占当前受管任务状态，xiaoh只绑定某一时点的权威事实。
5. 保持身份、角色、动作、范围、Workspace、状态、时效和防重放门禁。
6. 保留 schema 1.5 历史审计能力，并提供显式迁移路径。
7. macOS/Linux 的 Python Hook 与 Windows PowerShell Hook 行为一致。

## 3. 非目标

- 不修改、安装、升级、降级或重新配置 Playbook。
- 不创建第二套受管任务状态机。
- 不让未受管任务因本机存在 Playbook CLI 自动变为受管任务。
- 不把短时凭证变成长效授权。
- 不允许旧证据通过修改上下文或默认值重新生效。
- 不为未来可能出现的远程签名服务或 OS 隔离密钥预建抽象。

## 4. 方案比较

### 4.1 最小改动方案

允许 `delegation_names` 为每个角色配置多个固定名称，并在上下文哈希计算时忽略
Playbook 收据字段。

优点是修改文件较少。缺点是稳定授权仍混入运行期实例，固定名称池会耗尽或产生
并发冲突；忽略部分字段还会形成两个难以解释的“上下文哈希”，并继续让本地评审
依赖可变上下文结构。这只能缓解当前两轮评审，不能正确表达生命周期。

### 4.2 最合适改动方案（选定）

将职责拆成两个工件：

- schema 1.6 任务上下文：只保存稳定任务授权，产生确定性 `authority_hash`。
- `xiaoh-delegation-binding/v1`：每次正式 Agent 启动生成唯一、短时、一次性的执行绑定。

本地评审清单绑定 `authority_hash`；每轮证据绑定各自的执行凭证、Agent 会话、
运行记录和（受管时）Playbook 收据。职责边界与实际生命周期一致，可独立验证，
也不会把 Playbook 变成xiaoh核心依赖。

## 5. 稳定任务授权

schema 1.6 保留：

- `task_id`、`revision`、目标、行为、风险和停止条件；
- 意图域、交互证据和已确认决策；
- Workspace、允许路径、禁止动作和验收标准；
- 可委派角色、每个角色允许的动作；
- 每个角色允许的 `task_name` 命名空间；
- 独立评审角色和交付模式；
- Playbook 的静态任务身份（仅在明确受管时）；
- 事实源、验证和输出契约。

schema 1.6 不保存：

- 具体 `task_name`；
- Agent 运行时 ID、会话 ID、随机数和时间戳；
- Playbook 收据路径、哈希、worker 源文件和短时状态快照；
- 评审工件摘要、Git HEAD 和单轮运行证据。

`authority_hash` 是任务上下文规范 JSON 的 SHA-256。它覆盖全部稳定授权字段，
任务上下文本身不得声明自己的哈希。实现只能由验证器计算，调用方不得覆盖。

以下变化必须创建新的上下文修订并使旧授权停止用于新动作：

- 目标、意图域、角色、允许动作、范围或 Workspace 变化；
- 受管任务静态身份或独立评审要求变化；
- 验收、禁止动作或停止条件发生实质变化。

以下变化不得改变 `authority_hash`：

- 新评审轮次或新的唯一 `task_name`；
- Playbook 收据刷新；
- Agent 会话和运行记录变化；
- Git HEAD、评审对象或验证证据变化。

## 6. 单次执行绑定

每次正式 Agent 启动前，由受信任 Hook 生成
`xiaoh-delegation-binding/v1`，至少包含：

- 稳定上下文绝对路径和 `authority_hash`；
- `task_id`、角色、实际 `agent_type`；
- 本次唯一 `task_name`；
- 唯一 delegated action；
- 评审轮次和用途（适用时）；
- 不可变执行或评审对象摘要（适用时）；
- Playbook 适配收据路径和 SHA-256（受管时），独立模式为 `null`；
- 准备者根会话、随机 nonce、`prepared_at` 和 `expires_at`；
- Hook 路径和哈希。

`routing.delegation_policies` 按角色声明：

- 唯一允许动作；
- 实际 `agent_type`；
- `task_name_prefix`；
- 是否允许评审轮次和用途字段。

具体名称使用 `<prefix>__r<round>__<random>` 或等价唯一格式。验证器只接受
授权前缀且符合语法的名称，不在稳定上下文中预分配实例名。

## 7. Hook 生命周期

### 7.1 PreToolUse / prepare

1. 校验 schema 1.6 稳定上下文并重新计算 `authority_hash`。
2. 校验请求角色、`agent_type`、动作和 `task_name` 命名空间。
3. 受管任务重新校验当前 Playbook 收据；独立任务禁止携带该收据。
4. 原子写入一次性执行绑定；相同会话、角色和名称不得覆盖既有绑定。

委派消息头改为：

```text
task_id: ...
task_context: /absolute/path
authority_hash: ...
delegated_agent: ...
execution_binding: /absolute/path
binding_hash: ...
```

### 7.2 SubagentStart

1. 重新校验稳定上下文、执行绑定、Hook 自身和实际 Agent 身份。
2. 原子消费执行绑定并写入真实运行时 Agent ID。
3. 生成随机回执，把权威有效简报作为 developer context 注入。
4. 任一不一致均失败关闭；原始 transport message 不授予权限。

### 7.3 SubagentStop

校验随机回执、实际 Agent 身份、转录、执行绑定和受管收据的启动时有效性，
生成不可覆盖的委派证明。证明保存本次绑定哈希和稳定 `authority_hash`。

Playbook 收据只要求在 Agent 启动时满足：

```text
captured_at <= agent_started_at <= expires_at
```

任务收口不要求旧收据仍处于当前时间的有效期内，但必须验证该收据内容、来源哈希、
当时状态和启动时序没有被篡改。

## 8. 本地多轮评审

最终 `xiaoh-local-review/v1` 清单绑定：

- 稳定任务上下文路径和 `authority_hash`；
- 交付模式和实现者；
- 当前 Git HEAD、完整仓库集合或不可变工件摘要；
- 连续评审轮次；
- 每个角色每轮独立的执行绑定、委派证明、运行记录、原始报告和结论。

每一轮必须使用新的真实 Agent 会话和唯一 `task_name`。第一轮发现问题后由实现者
修复；工件摘要变化会使旧轮次只保留为返工历史。收敛轮必须绑定当前最终对象。

刷新 Playbook 收据、生成新的执行绑定或进入下一轮不得改变 `authority_hash`，
也不得使已经完成且当时有效的历史轮次变成“伪造”或“过期”。范围、角色或任务
静态身份变化则必须新建上下文修订，旧清单不能用于当前交付。

## 9. Playbook 边界

- `playbook.managed=false`：完整执行xiaoh独立流程；即使 CLI 已安装也不启用适配。
- `playbook.managed=true`：每次正式动作都绑定当前适用的 Playbook worker 或
  status-review 收据；缺失、不兼容或状态失效时失败关闭。
- Playbook 收据进入单次执行绑定，不进入稳定任务上下文。
- xiaoh不改变 Playbook task、member、MR、pipeline、Approval、归档或清理状态。
- 本地评审通过后，受管模式才允许向 Playbook 交付
  `ready_for_integration=true` 或触发远程评审。

## 10. 兼容与迁移

1. schema 1.2–1.5 保持只读历史审计。
2. 2.16.0 不允许 schema 1.5 发起新的正式委派或新生命周期动作。
3. 活动任务通过显式迁移命令生成 schema 1.6 修订；原文件和哈希保持不变。
4. 迁移复制稳定字段，把具体名称转换为按角色的命名空间策略，并把 Playbook
   短时字段移出任务上下文。
5. 迁移后必须重新校验并由根线程确认其没有扩大角色、动作或范围。
6. 历史运行记录继续引用原 schema 1.5 上下文，不伪造为 schema 1.6 证据。

## 11. 安全与失败策略

必须拒绝：

- 错误角色、`agent_type`、action、任务、上下文或命名空间；
- Workspace、change、member、worktree 或 allowed scope 不一致；
- 过期、未来、来源变化或状态终止的 Playbook 收据；
- 执行绑定重放、跨角色消费、覆盖或上下文替换；
- 运行期凭证写回稳定上下文；
- 旧 schema 用于新正式委派；
- 评审对象变化后复用旧收敛结论。

本设计不声称抵抗控制同一 OS 账户和全部 Hook 安装目录的操作者；该场景仍按治理
信任根失陷处理。

## 12. 验收与测试

必须覆盖：

1. 独立模式两轮、多角色、唯一名称通过。
2. 受管模式两轮之间刷新收据，`authority_hash` 不变且历史证据有效。
3. specification、implementation 等明确活动阶段按契约放行。
4. completed、closed、cleaned 等终态拒绝。
5. 错误角色、action、scope、Workspace、member、worktree 拒绝。
6. 过期、顺序错误、源文件变化和收据重放拒绝。
7. Git HEAD 或工件摘要变化只使评审对象失效，不改变稳定授权。
8. scope、角色或静态受管身份变化使旧授权失效。
9. schema 1.5 只读审计和显式 1.6 迁移通过。
10. Python 与 PowerShell Hook 行为一致。
11. `validate.py --self-test --json`、全部单元测试、doctor 和安装一致性检查通过。

## 13. 发布与回滚

发布时同步源码插件、版本元数据、本机已安装插件和部署运行时，并核对文件哈希。
回滚时恢复 2.15.0 安装包与运行时；2.16.0 生成的 schema 1.6 和执行绑定保留为
只读证据，不降格或改写为 schema 1.5。回滚后不得继续使用依赖 1.6 的活动任务，
需等待重新升级或由用户明确建立新的兼容任务。
