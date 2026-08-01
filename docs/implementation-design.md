# XiaoH 3.1.2 实现设计

## 产品边界

XiaoH 是根任务协调器，不是研发平台或远程交付状态机。它负责理解目标、事实核对、需求工件、专业 Agent 路由、本地实现协调、确定性验证和知识收口。仓库 CI、MR、人工 Approval 和 Playbook 远程生命周期继续由各自系统负责。

## 组件

```mermaid
flowchart LR
    U["用户目标"] --> X["xiaoh 根任务"]
    X --> R["Workspace、召回与需求基线"]
    R --> S["Spec+RFC / OpenSpec"]
    S --> A["5 个专业 Agent"]
    A --> V["测试、构建、静态、契约与安全校验"]
    V --> C["任务收口、项目进度与知识候选"]
```

- `xiaoh_runtime`：计划、安装、同步、Doctor、依赖、Workspace 和自动化绑定。
- `install-manifest.json`：唯一受管清单，固定版本、运行时目录、27 Skill 和 5 Agent。
- `agent-system`：schema 1.6 任务上下文、schema 1.2 运行记录、需求门禁和收口校验。
- Hook：保留根身份、一次性委派绑定、Agent 启停证明和 Vault 写入路径保护。
- `playbook_adapter.py`：只读绑定 worker/status 证据，不复制 Playbook 状态。
- Obsidian 模板：需求基线、任务记录、项目进度、知识候选和正式知识。

## 需求生命周期

复杂变更选择 `spec_rfc_then_openspec`；单仓局部且语义稳定的变更可用 `openspec_only`；正式类别文档使用 `class_skill`。Spec+RFC 先通过结构、完整性、矛盾项、边界和追溯校验，再由用户确认。OpenSpec 从确认修订派生，通过覆盖与追溯校验后确认。语义变化会提升 Spec 修订并重置受影响的 OpenSpec 校验状态。

## 实现与质量

实现阶段使用 Ponytail 收敛复杂度，但不削减安全、兼容、错误处理和验证。一个写入范围只有一个实现者。验证集合按风险选择：语法/格式、静态分析、单元、集成、构建、契约、迁移、安全和运行探针。失败后定位根因、检查同类路径、完整修复，再重跑受影响检查和必要回归集合。

3.1.2 没有代码评审生命周期、评审 Agent 或 Campaign 证据协议。`spec-rfc-reviewer` 与 `spec-rfc-openspec-consistency-review` 仅提供按需、单次的需求工件检查；它们不自动复查，也不参与实现或收口状态。普通代码审阅只有在用户主动要求时作为一次性咨询执行。

## 安装事务

Plan 完全只读。Setup/Update 先备份 Codex 配置、Agent、运行时、Hook、Vault 和 XiaoH 配置；拒绝符号链接管理目录；删除旧受管面；复制当前清单；替换路径占位符；合并全局契约和 Hook 配置；保存配置；执行静态验证和 Doctor。Update 只做当前 3.x 受管运行时同步/修复或明确的干净重装，不迁移旧 schema。

## 验收

- 精确 27 Skill、5 Agent，已删除的代码评审资产不存在。
- validator、委派 Hook、Vault Hook 自检通过。
- Python 编译、单元测试、companions、plan、临时安装和 Doctor 通过。
- 本机安装后版本与插件一致；Hook 变化时明确要求重启和信任。
