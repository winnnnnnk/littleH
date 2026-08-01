# XiaoH 4.0.0 可安装代码候选报告

## 结论

仓库中的 XiaoH 已切换到 4.0.0 单一运行时实现。旧的扁平运行时模块已经删除，公共入口只引用新的分层代码。候选代码可以在隔离路径中完成 Plan、事务安装、静态 Doctor、失败补偿和同输入幂等验证。

本报告不表示本机 XiaoH 已升级。此次工作没有运行真实 Setup 或 Update，没有修改真实 `~/.codex`、`~/.xiaoh`、Obsidian Vault、插件缓存、Hook 信任或 Playbook CLI，也没有重启 Codex。

## 版本与公共契约

- 插件版本：`4.0.0`
- 安装清单：`xiaoh-install-manifest/v2`
- 本地配置：`xiaoh-config/v2`
- CLI 响应：`xiaoh-cli-response/v2`
- 委派绑定：`xiaoh-delegation-binding/v2`
- 委派证明：`xiaoh-delegation-proof/v2`
- 根执行绑定：`xiaoh-root-execution-binding/v1`
- 根范围证明：`xiaoh-root-scope-proof/v1`
- 第三方 Skill 审核：`xiaoh-third-party-skills/v2`
- 专业 Agent：5 个
- 捆绑 Skill：28 个

## 已完成的实现

- 运行时按 domain、ports、services、capabilities、diagnostics、installation、application、adapters 和 interface 分层，并由自动化依赖门禁限制方向和循环。
- Setup 和 Update 使用只读 Plan、独立候选、恢复清单、逐目标切换、实际写入记录、静态 Doctor 和逆序补偿。
- Doctor 独立执行插件、Skill 治理、已加载 Skill、受管运行时、Agent、Hook、Validator、Vault、Workspace、自动化和 Playbook 诊断。Hook 运行时验收同时检查注册、信任、文件摘要和 `SubagentStart` 响应协议；单项失败不会截断其他安全诊断。
- 委派 Hook 使用精确 `task_name`、启动时上下文复核、过期检查、原子一次性消费、符合 Codex 协议的 `SubagentStart` 上下文、随机回执和转录摘要证明。
- 根写入 Hook 把短时任务绑定、补丁/明确命令目标检查和 Vault 路径校验合并为一个入口；结束时从真实 Git 状态、文件摘要和提交差异生成范围证明。
- Validator 现在完整校验任务行为、范围、来源摘要、决策、验证身份/类别和输出契约；必需检查由根绑定控制的入口执行并生成证据 JSON，完成记录必须提供匹配的退出码、时间、证据摘要和根范围证明，不能只自述通过。
- 委派策略明确区分只读与写入范围；写 Agent 的范围必须包含于根任务范围且不能互相重叠。
- `companions` 只盘点能力并执行 Skill 来源和质量校验，不安装插件。
- 代码评审只由用户显式触发，固定比较点，单次报告标准轴和需求轴，不自动修复、复审或改变门禁。
- 通用编码流程使用 `fast`、`standard` 和 `high_risk` 三档；低风险直接改动、Agent 收益和验证证据由任务上下文与 Validator 约束。
- 候选构建在路径占位符替换后重新绑定任务上下文摘要，确保安装后的运行记录模板不会因 `context_hash` 漂移失效。

## 验证证据

本地候选验收执行了以下命令：

```bash
python3 -m compileall -q plugins/xiaoh tests
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 plugins/xiaoh/runtime/codex/agent-system/validate.py --self-test
python3 plugins/xiaoh/runtime/codex/hooks/block_reserved_root_agent.py --self-test
python3 plugins/xiaoh/runtime/codex/hooks/guard_vault_writes.py --self-test
python3 plugins/xiaoh/runtime/codex/hooks/guard_task_writes.py --self-test
python3 plugins/xiaoh/scripts/xiaoh.py companions --json
```

当前本地阶段证据：

- 本地平台：macOS Darwin 25.5.0 arm64，Python 3.9.6。
- 单元、契约、隔离集成、故障注入和幂等测试：68 项全部通过。
- Python 编译和 3.9 语法门禁：通过；AST `feature_version=(3, 9)` 也覆盖了全部运行时代码、Validator 和 Hook。
- Validator 自检、委派 Hook、根写入 Hook、Vault Hook 自检：全部通过。
- `companions`：通过；28 个捆绑 Skill、5 个专业 Agent 和 mattpocock/skills `0/10/8/4` 决策基线一致。
- JSON、Shell、Git diff 和 GitHub Actions YAML 静态检查：通过。
- OpenSpec CLI 1.4.1 严格校验：`xiaoh-400-runtime-rewrite` 有效。
- OpenSpec 实施任务：64 项中 62 项已完成；只保留远端跨平台矩阵及其最终复跑两项。
- macOS、Windows、Python 3.9 和 3.11：CI 已配置为阻断矩阵，本地阶段未运行远端矩阵。
- 类型检查、lint 和 coverage：CI 已改为阻断，不再忽略失败。本地环境未安装这些开发工具，因此最终状态以 CI 为准。
- PowerShell 入口解析：Windows CI 已配置为阻断；本机没有 PowerShell，未做本地解析。
- Skill Creator 标准脚本：本地系统 Python 缺少 PyYAML，未安装额外依赖。仓库内无依赖 Skill 治理已验证 frontmatter、路径、来源、许可证和摘要。

## 已知限制和后续人工边界

正式版本从当前代码候选进入本机安装前，必须完成源码基线固定、远端质量门禁、真实只读 Plan、恢复清单、用户授权、重启信任和运行时验收。完整步骤见 [XiaoH 4.0.0 正式版本安装准入清单](xiaoh-4.0.0-formal-install-readiness.md)。

- 运行时激活只能在用户安装后确认。需要重启 Codex，由用户审阅并信任 Hook，再从新根任务运行 `doctor --runtime`。
- 仓库候选的 `SubagentStart` 输出协议和完整绑定、回执、转录证明生命周期已经通过隔离测试；`additionalContext` 是否由当前 Codex 进程实际传入专业 Agent，仍需在授权安装、重启和信任后通过一次真实委派验收。
- 真实自动化的创建和更新由 Codex 支持的自动化工具负责。XiaoH 只读取并绑定现有任务。
- 配套插件和外部能力只提供建议与状态，不由 XiaoH 自动安装。
- Playbook CLI 的安装、升级、降级、重装、链接和版本切换始终由用户人工完成。
- 在跨平台 CI、类型检查或 lint 通过之前，候选不能标记为最终发布包。

## 停止点

候选代码验收后停止。下一阶段只有在用户另行授权安装时，才可以执行真实 Setup、重启、Hook 信任和运行时 Doctor。
