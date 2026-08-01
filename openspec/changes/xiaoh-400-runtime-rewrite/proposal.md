## Why

XiaoH 3.1.2 已完成产品能力收敛，但内部依赖、安装恢复、Doctor 完整性和 Skill 治理仍会造成修改范围扩大、故障后状态不确定和问题逐轮暴露。XiaoH 4.0.0 需要在保留产品能力和用户长期资产语义的前提下重建运行时，并先形成不安装本机的仓库候选。

源基线：`docs/spec-rfc/xiaoh-4.0.0-runtime-rewrite.md`，修订 4。

## What Changes

- **BREAKING**：不兼容 2.x 或 3.1.2 的内部运行时、安装状态、事务证据和内部 Schema；保留 3.1.2 产品能力及用户长期资产导入语义。
- 采用单向模块分层和 Ports/Adapters，禁止星号导入和循环依赖。
- 将配置、Workspace、Vault、自动化、插件事实和配套能力收敛到明确所有者。
- 建立只读安装计划、隔离候选、恢复清单、补偿事务和激活状态。
- 将 Doctor 改为独立诊断器聚合，一次返回全部可安全执行的诊断。
- 在契约保护下重写根身份、委派 Hook、Vault Hook 和 Validator。
- 将第三方 Skill 治理改为 Manifest 驱动，整理 XiaoH Skill，并引入显式单次代码评审。
- 为通用编码开发加入三档执行通道、直接改动边界、Agent 收益门槛和收敛式验证证据。
- 将根任务和委派写入绑定到路径范围，以真实 Git 前后状态证明改动，并要求来源与验证结果提供可复算摘要。
- 保留薄 CLI 和结构化响应，真实记录预计写入、实际写入和恢复结果。
- 全部开发和验证使用仓库与临时目录；通过后删除旧生产实现并停在可安装候选状态，不安装本机。

## Capabilities

### New Capabilities

- `runtime-architecture`: 3.1.2 产品行为基线、单向模块架构、外部依赖端口和旧实现退出条件。
- `runtime-services`: 配置、Workspace、Vault、自动化和用户长期资产的所有权及生命周期。
- `transactional-installation`: 安装计划、隔离候选、恢复清单、补偿事务、幂等和未来干净安装。
- `complete-doctor`: 独立诊断器、完整聚合、跳过语义、修复边界和激活状态。
- `runtime-security`: 根身份、正式委派、Hook、Validator、敏感数据和失败关闭不变量。
- `governed-skills`: Manifest 驱动的第三方 Skill 治理、Skill 质量整理和显式单次代码评审。
- `development-flow`: 工件路由与执行通道分离、低风险直接改动、委派收益门槛和一次性验证收敛。
- `runtime-cli`: CLI 命令概念、稳定响应外壳、结构化错误和可安装候选边界。

### Modified Capabilities

无。`openspec/specs/` 当前没有已归档主规格，本 change 创建 4.0.0 初始能力规格。

## Impact

- 主要影响 `plugins/xiaoh/xiaoh_runtime/`、`plugins/xiaoh/scripts/xiaoh.py`、受管 Hook、Validator、Skill、运行时模板和测试。
- 新增版本化安装、诊断和第三方 Skill Manifest Schema。
- CI 将把类型检查、lint、契约、故障注入、幂等和跨平台隔离安装作为正式门禁。
- Codex 插件缓存、Playbook CLI、真实 `~/.codex`、真实 `~/.xiaoh` 和真实 Obsidian Vault 不在本阶段写入范围。
- 实际本机安装、重启、Hook 信任和运行时验收需要后续单独授权。
