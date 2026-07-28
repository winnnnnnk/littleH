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
python3 __CODEX_HOME__/agent-system/validate.py --routing-case java-single-repo-fix --intent-domain business_project --selected-agents java_code_explorer,java_implementer,test_integration_verifier,code_quality_reviewer
python3 __CODEX_HOME__/agent-system/validate.py --requirement-gate /absolute/path/task-context.json --action task_create
python3 __CODEX_HOME__/agent-system/validate.py --requirement-gate /absolute/path/task-context.json --action spec_rfc_confirmation
python3 __CODEX_HOME__/agent-system/validate.py --local-review-manifest /absolute/path/local-review-manifest.json --task-context /absolute/path/task-context.json
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
- 路由案例是否引用已注册角色，实现任务是否至少包含两个独立判断角色，高风险案例是否包含独立判断角色。
- schema 1.6稳定授权与路由案例是否明确区分全局 Agent 能力、Playbook 平台和业务项目，并区分提问、假设、事实纠正、业务决策和执行指令。
- schema 1.6业务上下文是否绑定已完成的项目历史召回清单及哈希，并完整记录证据冲突、范围缩减与兼容默认值依据、需求工件路由、显式Skill执行、Spec+RFC准入评审、OpenSpec一致性评审、追溯和遗漏补救状态。
- Agent 阶段登记是否覆盖全部角色，Obsidian Sandbox 是否与 TOML 一致。
- 公共契约、上下文索引、模板和进化台账是否存在。

## 存放规则

- 任务上下文包和原始运行证据属于任务事实，应放在对应 Playbook task evidence 或项目任务目录，不集中复制到 Obsidian。
- 实现任务的当前证据目录只保留一份`xiaoh-local-review/v1`最终清单；被修复取代的轮次报告保留为审计证据，但不能冒充当前验收。
- Obsidian 只记录稳定结论、阶段评审和配置进化摘要。
- `authority_hash` 使用schema 1.6任务上下文规范JSON的SHA-256，只覆盖稳定授权；具体Agent实例、评审对象和Playbook短时收据由一次性执行绑定承载。
- 任务上下文从schema 1.2起使用不可变修订链：`revision: 1`的`previous_context`为`null`；稳定授权变化时创建新文件，并用`previous_context.path/hash`指向上一版，不直接覆盖旧文件。schema 1.3新增唯一意图域；schema 1.4新增交互证据；schema 1.5新增项目历史召回；schema 1.6分离稳定授权和运行时绑定。新任务使用1.6，1.2至1.5仅兼容历史审计。收据刷新、新评审轮次和评审对象变化不修改稳定上下文。
- 运行记录 schema 1.1 仅保留为可审计的历史格式，不能参与 v1.2 成功收口。schema 1.2 的记录只有在全部 `gates` 和 `verification` 为 `passed`、`metrics.result_accepted` 为 `true` 时才计入成功 Agent；高风险独立评审还必须包含通过的 `independent_review` gate。
- schema 1.2 的非根 Agent 完成记录必须同时绑定 Hook 原子生成的委派证明和真实 Codex 转录。传统 `Agent` 调用的历史证明绑定父会话、turn 和 tool use；当前协作工具的正式证明必须由一次性意图、`SubagentStart` 实际 `agent_id` 与 developer context、`SubagentStop` 随机回执认证共同形成。原始 `message` 只是不可信传输文本；证明绑定从当前任务上下文确定的权威有效简报、上下文哈希、角色、任务名、Hook 哈希和官方转录路径。旧上下文证明、跨会话意图、未认证启动证明或重复证明不能参与收口。
- 任何包含密码、令牌、私钥、生产凭据或不必要敏感材料的上下文包都不得创建。

## 路由回归

`routing-cases.json` 是调度基线，不是固定工作流。每个案例先固定 `intent_domain`，再判断角色集合；`required_agents` 是该案例的最小集合，`optional_agents` 必须由当前任务事实触发，未列出的角色会被判定为过度路由。实际执行顺序、实例数量、并行能力和可写 worktree 仍由 Playbook 决定。

小H的路由规则、角色描述或角色结构变化后，应逐个读取案例 prompt，独立给出选择结果，再用 `--routing-case` 校验。不能直接照抄案例答案冒充回归结果。

`xiaoh` 是当前根线程的保留身份，不是自定义 Agent。路由案例的 `root_agent` 记录协调责任；`required_agents`、`optional_agents` 和 `--selected-agents` 只包含实际委派的专业子 Agent。校验器发现 `agents/xiaoh.toml` 或委派列表中的 `xiaoh` 时必须失败。

每次正式委派先声明`task_id`、`task_context`、`authority_hash`和`delegated_agent`。`task_name`按角色命名空间生成，不写入稳定上下文。根线程把候选`tool_input`和本轮参数交给`--prepare`，再原样使用返回的、已增加`execution_binding`与`binding_hash`的最终`tool_input`。`SubagentStart`原子消费绑定、重验稳定授权和当前Playbook状态并绑定真实`agent_id`；`SubagentStop`认证回执和官方转录，生成schema 1.3证明。缺少绑定、证据目标冲突或任何消费异常时统一注入只读限制。首次安装或Hook变更后必须完全重启Codex并重新信任Hook。收口采用“稳定authority + 已消费执行绑定 + schema 1.3委派证明 + Agent转录 + v1.2运行记录”的组合证据。

## 进化评估

运行记录中的 `metrics` 保存上下文补充、越界、验证失败、逃逸缺陷和结果采纳情况。`--evaluate-runs` 聚合指定目录中的真实记录；跨 workspace 时可重复传入该参数。显式追加 `--sync-stage-evidence` 只把 `evidence_runs` 和 `last_evaluated_at` 写回 `agent-stages.json`，不会改变阶段。工具根据 `evolution-policy.json` 输出阶段评审建议；阶段变化仍由小H复核并遵守用户确认门禁。

## 当前边界

校验器只解析当前 Agent 文件使用的扁平 TOML 清单字段，不实现通用 TOML 解析器。以后若角色清单引入嵌套 TOML 结构，再改用 Codex 自带解析入口或正式 TOML 库。
