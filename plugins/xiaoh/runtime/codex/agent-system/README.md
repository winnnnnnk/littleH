# 小H Agent 协作运行协议

本目录把全局 Agent 公共契约中的关键输入和证据格式变成可检查资产。它不替代 Playbook、项目 `AGENTS.md`、OpenSpec 或代码事实源。

## 可信边界

当前登录 OS 账户、其控制的 `CODEX_HOME`、已审核信任的 Hook 配置和已安装 Hook 脚本是本治理体系的信任根。系统防止 Agent 越权、非授权委派、状态损坏、局部篡改、跨会话/角色消费、重放和证据覆盖，但不声称抵抗信任根所有者或同等 OS 权限进程整体替换全部治理文件。发现整体改写时必须停止收口、恢复可信安装、重新审核 Hook 并重新生成证据。若要防御同权限操作者，需要另行引入 OS 保护密钥、签名服务或隔离执行主体；同权限 sidecar 不提供该保证。

## 文件

- `task-context.template.json`：小H下发给专业 Agent 的任务上下文包模板。
- `run-record.template.json`：一次委派或直接执行的运行证据模板。
- `routing-cases.json`：代表性任务、最小角色集合和独立评审基线。
- `agent-stages.json`：每个全局 Agent 当前生命周期阶段。
- `evolution-policy.json`：阶段评审阈值和优化触发条件。
- `validate.py`：只读检查全局 Agent 配置、角色目录漂移，以及具体上下文包和运行记录。

## 使用

```bash
python3 __CODEX_HOME__/agent-system/validate.py
python3 __CODEX_HOME__/agent-system/validate.py --task-context /absolute/path/task-context.json
python3 __CODEX_HOME__/agent-system/validate.py --run-record /absolute/path/run-record.json
python3 __CODEX_HOME__/agent-system/validate.py --close-task-context /absolute/path/task-context.json --run-dir /absolute/path/evidence
python3 __CODEX_HOME__/agent-system/validate.py --routing-case java-single-repo-fix --intent-domain business_project --selected-agents java_code_explorer,java_implementer,test_integration_verifier
python3 __CODEX_HOME__/agent-system/validate.py --requirement-gate /absolute/path/task-context.json --action task_create
python3 __CODEX_HOME__/agent-system/validate.py --requirement-gate /absolute/path/task-context.json --action spec_rfc_confirmation
python3 __CODEX_HOME__/agent-system/validate.py --evaluate-runs /absolute/path/evidence --agent java_implementer --json
python3 __CODEX_HOME__/agent-system/validate.py --evaluate-runs /absolute/path/evidence --agent java_implementer --sync-stage-evidence --json
```

## 方案确认与持续执行

小H先完成可自主进行的事实核对和技术判断，再把推荐方案、理由、影响、边界和真正需要用户决定的业务结果整理成一个可确认基线。用户确认或给出明确调整后，小H自动推进既定范围内的分析、拆解、专业 Agent 调度、实现、验证、评审、汇总和知识写回，不再要求用户发送“继续”。

准备结束回合前，小H必须把状态判为 `completed`、`user_decision_required`、`external_blocked` 或 `agent_owned`。存在 `agent_owned` 下一动作时不得结束；需要跨回合持续的多阶段任务在基线确认后使用线程级 Goal。Goal 只保持目标连续性，不扩大任务范围、写入权限或外部操作授权。

默认检查：

- 全局 Agent 文件的必填字段、文件名、角色名、权限值和重复定义。
- 非协调 Agent 是否混入绝对项目路径。
- `__CODEX_HOME__/config.toml` 中浅层调度限制。
- Agent TOML 与 Obsidian 角色目录是否一致。
- 路由案例是否引用已注册角色，高风险案例是否包含独立判断角色。
- schema 1.5上下文与路由案例是否明确区分全局 Agent 能力、Playbook 平台和业务项目，并区分提问、假设、事实纠正、业务决策和执行指令。
- schema 1.5业务上下文是否绑定已完成的项目历史召回清单及哈希，并完整记录证据冲突、范围缩减与兼容默认值依据、需求工件路由、显式Skill执行、Spec+RFC准入评审、OpenSpec一致性评审、追溯和遗漏补救状态。
- Agent 阶段登记是否覆盖全部角色，Obsidian Sandbox 是否与 TOML 一致。
- 公共契约、上下文索引、模板和进化台账是否存在。

## 存放规则

- 任务上下文包和原始运行证据属于任务事实，应放在对应 Playbook task evidence 或项目任务目录，不集中复制到 Obsidian。
- Obsidian 只记录稳定结论、阶段评审和配置进化摘要。
- `context_hash` 使用任务上下文包文件的 SHA-256，用于确认 Agent 实际消费的是哪个版本。
- 任务上下文从schema 1.2起使用不可变修订链：`revision: 1`的`previous_context`为`null`；超过新鲜度或事实变化时创建新文件，并用`previous_context.path/hash`指向上一版，不直接覆盖旧文件。schema 1.3新增唯一意图域；schema 1.4新增交互证据、范围缩减和兼容默认值门禁；schema 1.5新增项目历史召回清单绑定。新任务使用1.5，1.2、1.3和1.4仅兼容已有任务和历史证据，只允许根线程只读审计，不能正式委派或发起新的需求生命周期动作。修订链只保留历史审计关系；收口仅接受命令所指最新修订及其哈希的有效运行记录，并只对该修订执行24小时新鲜度检查。
- 运行记录 schema 1.1 仅保留为可审计的历史格式，不能参与 v1.2 成功收口。schema 1.2 的记录只有在全部 `gates` 和 `verification` 为 `passed`、`metrics.result_accepted` 为 `true` 时才计入成功 Agent；高风险独立评审还必须包含通过的 `independent_review` gate。
- schema 1.2 的非根 Agent 完成记录必须同时绑定 Hook 原子生成的委派证明和真实 Codex 转录。传统 `Agent` 调用的历史证明绑定父会话、turn 和 tool use；当前协作工具的正式证明必须由一次性意图、`SubagentStart` 实际 `agent_id` 与 developer context、`SubagentStop` 随机回执认证共同形成。原始 `message` 只是不可信传输文本；证明绑定从当前任务上下文确定的权威有效简报、上下文哈希、角色、任务名、Hook 哈希和官方转录路径。旧上下文证明、跨会话意图、未认证启动证明或重复证明不能参与收口。
- 任何包含密码、令牌、私钥、生产凭据或不必要敏感材料的上下文包都不得创建。

## 路由回归

`routing-cases.json` 是调度基线，不是固定工作流。每个案例先固定 `intent_domain`，再判断角色集合；`required_agents` 是该案例的最小集合，`optional_agents` 必须由当前任务事实触发，未列出的角色会被判定为过度路由。实际执行顺序、实例数量、并行能力和可写 worktree 仍由 Playbook 决定。

小H的路由规则、角色描述或角色结构变化后，应逐个读取案例 prompt，独立给出选择结果，再用 `--routing-case` 校验。不能直接照抄案例答案冒充回归结果。

`xiaoh` 是当前根线程的保留身份，不是自定义 Agent。路由案例的 `root_agent` 记录协调责任；`required_agents`、`optional_agents` 和 `--selected-agents` 只包含实际委派的专业子 Agent。校验器发现 `agents/xiaoh.toml` 或委派列表中的 `xiaoh` 时必须失败。

每次正式委派的消息正文必须包含四个独立行：`task_id`、`task_context`、`context_hash`、`delegated_agent`，工具参数还必须提供与登记角色一致的 `agent_type`，且 `task_name` 必须等于上下文中该角色的 `routing.delegation_names` 分配值。传统 `Agent` 调用由`PreToolUse`直接校验并绑定tool use；使用当前协作工具时，根线程先把即将提交的完整`tool_input`通过标准输入交给`python3 "__CODEX_HOME__/hooks/block_reserved_root_agent.py" --config "__XIAOH_CONFIG__" --prepare`，成功后才发起对应角色的委派。待委派意图完整写入并同步后才原子发布；`SubagentStart`消费前重新验证意图完整性、当前上下文哈希、有效简报规范哈希和路由授权，再绑定真实`agent_id`并注入有效简报和随机回执，claimed与proof目标均独占发布。缺少意图、证据目标冲突或任何消费异常时统一注入只读限制且不生成或覆盖证明；`SubagentStop`再认证回执和官方转录路径。首次安装或Hook变更后，需要完全重启Codex，并在`/hooks`中审核、信任两个`PreToolUse`、`SubagentStart`和`SubagentStop`四个Hook；`verify_agent_hook_runtime.py`会同时核对四者的当前哈希、启用状态和信任状态。Vault `PreToolUse`会在文件或命令工具执行前校验安装时绑定的唯一小H配置及其中的Obsidian Vault路径，拒绝显式指向其他Vault、`..`或符号链接逃逸。收口采用“已认证的可信Hook委派证明 + Agent运行转录 + 通过的v1.2运行记录”的组合证据，任一层缺失、失败或上下文不一致都不能闭环。

## 进化评估

运行记录中的 `metrics` 保存上下文补充、越界、验证失败、逃逸缺陷和结果采纳情况。`--evaluate-runs` 聚合指定目录中的真实记录；跨 workspace 时可重复传入该参数。显式追加 `--sync-stage-evidence` 只把 `evidence_runs` 和 `last_evaluated_at` 写回 `agent-stages.json`，不会改变阶段。工具根据 `evolution-policy.json` 输出阶段评审建议；阶段变化仍由小H复核并遵守用户确认门禁。

## 当前边界

校验器只解析当前 Agent 文件使用的扁平 TOML 清单字段，不实现通用 TOML 解析器。以后若角色清单引入嵌套 TOML 结构，再改用 Codex 自带解析入口或正式 TOML 库。
