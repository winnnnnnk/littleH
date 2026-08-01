# XiaoH 3.1.2

XiaoH 是 Codex 的本地研发协调插件。它在当前根任务中理解目标、核对事实、整理需求、选择专业 Agent、推进实现、运行确定性验证，并把稳定结果写入配置的 Obsidian Vault。

3.1.2 延续 3.1.0 不兼容旧运行时的干净重构。代码评审 Agent、评审 Campaign 和旧迁移协议已经完全移除。质量门禁由确认基线、明确写入范围、测试/构建/静态/契约/安全校验和运行证据组成。两个需求工件检查 Skill 可按需检查 Spec+RFC 准入和 Spec/OpenSpec 一致性，但不自动复查，也不参与代码交付状态机。工作台允许保留结构兼容的用户视图定制，不再将合理定制误报为运行时降级。

## 能力

- 需求与方案：Workspace 路由、历史召回、需求基线、Spec+RFC、OpenSpec 追溯和方案比较。
- 工程执行：Java/前端探索、架构、实现、TDD、诊断、原型、研究、领域建模和冲突处理。
- PKI：证书、密钥、CA/RA、OCSP/CRL、信任链、算法和安全失败路径。
- 知识闭环：任务收口、项目进度、每日成果、知识候选和用户确认后的晋升。
- 本地治理：一次性 Agent 委派、Vault 路径保护、Setup、Update、Doctor 和可选 Playbook 适配。

插件精确提供 27 个 Skill 和 5 个专业 Agent。`xiaoh` 是根任务保留身份，不是子 Agent。

## 安装

安装插件后调用 `$xiaoh:xiaoh-setup`，或直接运行：

```bash
python3 plugins/xiaoh/scripts/xiaoh.py plan --json
python3 plugins/xiaoh/scripts/xiaoh.py setup --json --allow-degraded
```

安装会先创建恢复备份，再替换 XiaoH 管理的运行时目录，同时保留白名单内的本地配置、Workspace 身份、Vault 知识、无冲突自定义 Agent、其他插件和自动化偏好。Hook 变化后需要重启 Codex 并信任四个 XiaoH Hook。

## 验证

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q plugins/xiaoh tests
python3 plugins/xiaoh/scripts/xiaoh.py companions --json
python3 plugins/xiaoh/scripts/xiaoh.py doctor --json
```

Playbook 是可选集成。XiaoH 只读取 worker 和 task status 证据；Playbook CLI 的安装、升级、降级和版本切换必须由用户人工完成。

详细设计见 [实现设计](docs/implementation-design.md)，使用流程见 [XiaoH 指南](docs/xiaoh-guide.md)。旧评审系统仅保留 [历史说明](docs/history/xiaoh-review-system-history.md)。
