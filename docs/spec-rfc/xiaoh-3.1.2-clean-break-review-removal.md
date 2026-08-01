> 文档生成时间：2026-08-01 12:35:56 CST
> 最近修订时间：2026-08-01 20:00:00 CST
> 生成方式：spec-rfc
> 修订：5（修复兼容工作台定制被误报为降级的问题）

# XiaoH 3.1.2 干净重构与需求工件检查边界

## 1. 背景与目标

XiaoH 在 2.3.0 后逐步加入 Spec/OpenSpec 审核，在 2.15.0 后加入强制多角色本地评审。到 3.0.0，评审已演化为带轮次、快照、发现账本、修复证明和继承规则的独立状态机。它提高了证据强度，但也造成同一工作反复评审、修复不彻底后重新入场、运行时间不可预测，以及评审内核本身需要被评审的问题。

3.1.2 延续 3.1.0 的干净重构：彻底移除代码评审状态机与自动复查机制，不兼容旧运行时和旧评审协议，同时保留 2.17.3 中全部非代码评审产品能力、当前有价值的工程 Skill、确定性验证、安全分析、知识管理和运行时治理。3.1.1 恢复两个按需的需求工件检查 Skill；3.1.2 修复工作台兼容定制被误报为降级的问题。两次补丁均不恢复自动循环或代码交付门禁。

## 2. 范围

### 保留

- 根线程协调、事实核对、方案比较、自主推进和用户决策边界。
- Workspace 归属、项目历史召回、需求基线、Spec+RFC、OpenSpec 追溯和用户确认。
- Java/前端探索、架构、实现、TDD、诊断、原型、研究、领域建模和冲突处理。
- PKI 领域与安全分析。
- 格式、静态分析、构建、测试、契约、追溯和运行证据等确定性验证。
- 任务收口、项目进度、每日成果、知识候选和用户确认后的知识晋升。
- Setup、Update、Doctor、Hook、Vault 路径保护、Playbook 可选适配和第三方 Skill 来源治理。

### 删除

- 代码评审与知识评审 Skill、全部评审 Agent、评审 Campaign、轮次与收敛协议。
- Review Unit、Semantic Patch Set、Evidence Envelope、Finding Ledger、Repair-Ready 和相关 schema、CLI、测试与证据生成器。
- Spec+RFC 与 Spec/OpenSpec 检查不再是自动生命周期门禁；保留两个按需、单次检查 Skill。
- 每周知识评审；知识候选改为由 xiaoh 整理并由用户确认后直接晋升。
- 旧兼容目录、旧 Python import bridge、旧升级迁移协议和旧 OpenSpec 实现工件。

## 3. 功能基线

3.1.2 对外提供 27 个 Skill：

`codebase-design`、`diagnosing-bugs`、`domain-modeling`、`fit-for-purpose-engineering`、`humanizer`、`improve-codebase-architecture`、`prototype`、`research`、`resolving-merge-conflicts`、`spec-rfc`、`spec-rfc-reviewer`、`spec-rfc-openspec-consistency-review`、`tdd`、`wayfinder`、`xiaoh-core`、`xiaoh-daily-progress`、`xiaoh-doctor`、`xiaoh-knowledge-promotion`、`xiaoh-playbook-adapter`、`xiaoh-project-recall`、`xiaoh-project-progress`、`xiaoh-requirement-baseline`、`xiaoh-requirement-routing`、`xiaoh-setup`、`xiaoh-task-closeout`、`xiaoh-update`、`xiaoh-workspace-routing`。

提供 5 个专业 Agent：`frontend_implementer`、`java_architect`、`java_code_explorer`、`java_implementer`、`pki_domain_expert`。`xiaoh` 仍是根线程保留身份。原 PKI 安全判断并入 `pki_domain_expert`。

## 4. 新业务流程

1. xiaoh 理解目标，区分事实、假设、推断、决策和未知项。
2. 确定唯一意图域；业务项目先解析 Workspace，再定向召回历史并与当前事实对账。
3. 路由需求工件。复杂变更形成 Spec+RFC，执行结构、完整性、矛盾项、边界和追溯校验后由用户确认。
4. 从确认基线派生 OpenSpec，执行覆盖和追溯校验后由用户确认。
5. 在 schema 1.6 上下文与一次性 Hook binding 下探索、设计或实现。
6. 实现完成后运行风险相称的确定性验证。失败时按根因修复全部同类路径，并只重跑受影响检查和必要回归集合。
7. 证据满足验收条件后收口任务、刷新项目进度并生成知识候选。

流程中没有自动审核、复审或评审轮次。两个需求工件检查 Skill 只在用户明确要求或上层任务明确点名时执行一次，工件修改不会自动触发下一轮。用户主动要求代码审阅时，可使用宿主或独立通用能力，但它不属于 XiaoH 产品门禁或状态机。

## 5. 架构与接口

- 插件根 `install-manifest.json` 固定 3.1.2 管理面、27 Skill 和 5 Agent。
- 工作台 `.base` 保留关键过滤器和结构时允许用户定制；Doctor 仅对缺失、损坏、越界或不可证明兼容的变化降级。
- `xiaoh_runtime` 负责 plan、setup/update、doctor、companion 检测、Workspace 和自动化绑定。
- `validate.py` 只验证全局安装、任务上下文、需求门禁、一次性委派 binding、运行记录和任务收口。
- `playbook_adapter.py` 只支持 probe、worker receipt capture 和 verify。
- 委派 Hook 保留一次性绑定、角色校验、SubagentStart 权威注入、SubagentStop 随机回执和转录证明。

## 6. 数据与安装

3.1.2 不读取或迁移旧 runtime schema。安装先生成恢复备份，再删除 XiaoH 管理的 contexts、agent-system、hooks 和已知旧 Agent 文件，随后复制当前清单。允许保留的用户数据通过显式白名单带入：配置扩展、Workspace 身份、配置的 Vault 与知识、兼容的工作台视图定制、无冲突的自定义 Agent、其他插件和自动化偏好。

`xiaoh-update` 仅表示同版本同步/修复或用户明确要求的干净重装，不表示旧 schema 迁移。Hook 内容变化后必须重启 Codex 并重新信任。

## 7. 安全、权限与异常

- Playbook CLI 的安装和版本变化仍是人工边界。
- Vault 仅允许写入配置声明的唯一根目录。
- 委派上下文、角色、binding、回执或转录不一致时失败关闭。
- 安装目标为符号链接、路径冲突或备份失败时停止写入。
- 确定性验证失败不得标记完成；必须报告根因、修复范围、剩余风险和恢复条件。

## 8. 验收标准

- 插件版本为 3.1.2，清单精确列出 27 Skill、5 Agent。
- 删除项在插件和安装后的受管运行时中均不存在。
- Python 全量编译、单元测试、validator/Hooks 自检、companions、plan、临时目录 setup/doctor 全部通过。
- 当前机器干净重装成功，备份路径可定位；安装后 Doctor 通过或只存在明确的重启/Hook 信任状态。
- README、指南、实现设计和 Playbook 关系文档与新流程一致。
- 评审历史仅保留 `docs/history/xiaoh-review-system-history.md`。

## 9. 发布与回退

发布顺序为：候选静态校验 → 临时目录安装验证 → 本机恢复备份 → 3.1.2 干净安装 → Doctor → 重启与 Hook 信任 → runtime Doctor。若安装失败，保留失败证据并从本次恢复备份人工恢复；不得自动重新激活旧评审协议。

## 10. TBD 列表

- 无阻塞 TBD。
- 远程仓库自身的 MR、人工 Approval 或 CI 规则不属于 XiaoH 自有评审能力，由各仓库和 Playbook 继续管理。
