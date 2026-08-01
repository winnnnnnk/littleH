# XiaoH 4.0.1

XiaoH 是 Codex 的本地研发协调插件。它在当前根任务中理解目标、核对事实、整理需求、选择专业 Agent、推进实现、运行确定性验证，并把稳定结果写入配置的 Obsidian Vault。

4.0.1 是 4.0.0 重写后的兼容性修复版本：补齐首次根绑定的原子 bootstrap、旧 Workspace roots 迁移和退出受管清单文件的事务化清理。4.0.0 的产品能力和内部断代边界保持不变。

## 能力

- 需求与方案：Workspace 路由、历史召回、需求基线、Spec+RFC、OpenSpec 追溯和方案比较。
- 工程执行：Java/前端探索、架构、实现、TDD、诊断、原型、研究、领域建模和冲突处理。
- PKI：证书、密钥、CA/RA、OCSP/CRL、信任链、算法和安全失败路径。
- 知识闭环：任务收口、项目进度、每日成果、知识候选和用户确认后的晋升。
- 本地治理：一次性精确 Agent 委派、Vault 路径保护、事务化 Setup/Update、完整 Doctor、Skill 来源治理和可选 Playbook 只读适配。

插件精确提供 28 个 Skill 和 5 个专业 Agent。`xiaoh` 是根任务保留身份，不是子 Agent。

## 安装

安装插件后调用 `$xiaoh:xiaoh-setup`，或直接运行：

```bash
python3 plugins/xiaoh/scripts/xiaoh.py plan --json
python3 plugins/xiaoh/scripts/xiaoh.py setup --json
```

安装会先在独立目录构建和校验完整候选，再创建可验证恢复备份，随后切换 XiaoH 管理的目标。失败时结果只能是完整回滚或明确的 `recovery_required`。它保留受支持的配置、Workspace 身份、Vault 知识与兼容工作台定制、无冲突自定义 Agent、其他插件和自动化偏好。Hook 变化后仍需用户重启 Codex、审阅并信任四个 XiaoH Hook，之后由新根任务执行运行时 Doctor；静态安装成功不等于运行时已激活。

## 验证

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q plugins/xiaoh tests
python3 plugins/xiaoh/scripts/xiaoh.py companions --json
python3 plugins/xiaoh/scripts/xiaoh.py doctor --json
```

`companions` 只盘点配套能力并执行 Skill 来源与质量校验，不安装插件。`plan` 和 `doctor` 均为只读。机器输出统一使用 `xiaoh-cli-response/v2`；安装状态和激活状态分别报告。

Playbook 是可选集成。XiaoH 只读取 worker 和 task status 证据；Playbook CLI 的安装、升级、降级和版本切换必须由用户人工完成。

4.0.0 的确认基线见 [Spec+RFC](docs/spec-rfc/xiaoh-4.0.0-runtime-rewrite.md) 与 [OpenSpec](openspec/changes/xiaoh-400-runtime-rewrite/README.md)；4.0.1 补丁见 [维护版本 Spec+RFC](docs/spec-rfc/xiaoh-4.0.1-maintenance-release.md) 与 [OpenSpec](openspec/changes/xiaoh-401-maintenance-release/proposal.md)。旧评审系统仅保留 [历史说明](docs/history/xiaoh-review-system-history.md)。
