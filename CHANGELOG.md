# 变更记录

## 3.1.2 - 2026-08-01

- 将“优先级”列纳入“待我确认”默认工作台视图。
- Doctor 复用现有 Vault 有效性判定：结构完整的 `.base` 用户定制视为兼容，不再误报整体降级。
- 缺失、损坏、越界或关键过滤器丢失的工作台仍然失败关闭并给出告警。

## 3.1.1 - 2026-08-01

- 恢复两个按需、单次的需求工件检查 Skill：`spec-rfc-reviewer` 与 `spec-rfc-openspec-consistency-review`。
- 两个 Skill 不自动复查、不进入代码交付状态机，也不恢复 Review Campaign、代码评审 Agent 或轮次协议。
- 将已变化的插件内容发布为新的补丁版本，避免 `3.1.0` 同版本缓存与源码内容不一致。
- 保持 27 Skill、5 专业 Agent，以及无代码评审生命周期的干净产品边界。

## 3.1.0 - 2026-08-01

- 完成不兼容旧运行时的干净重构。
- 完全移除代码评审 Skill、评审 Agent、Campaign 状态机、相关 schema、CLI、测试生成器和每周知识评审自动化。
- 删除旧兼容目录、Python import bridge、升级迁移协议和旧 OpenSpec 实现工件。
- 保留 2.17.3 的全部非代码评审产品能力，并纳入当前有价值的工程 Skill；最终提供 27 Skill 和 5 专业 Agent。
- 将 PKI 安全判断并入 `pki_domain_expert`。
- Spec+RFC 与 OpenSpec 改用确定性结构、完整性和追溯校验，加上明确的用户确认。
- 实现质量改为确认基线、单一写入责任、根因修复、风险相称的测试/构建/静态/契约/安全校验和 schema 1.2 运行证据。
- `xiaoh-update` 只用于当前 3.x 受管运行时同步/修复或明确的干净重装，不再迁移旧 runtime schema。
- 新增 `install-manifest.json`，精确约束受管目录、27 Skill 和 5 Agent。
- Playbook 适配只保留 worker/status 只读 receipt；Playbook CLI 版本维护继续是用户人工边界。
- 评审系统演进和移除原因统一保存在 [历史说明](docs/history/xiaoh-review-system-history.md)。
