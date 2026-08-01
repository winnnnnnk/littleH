# XiaoH 4.0.1 代码候选报告

## 结论

XiaoH 4.0.1 已完成代码层修复和隔离验证，可以作为补丁版本候选。当前仓库没有执行本机安装、插件更新、提交、推送或远端发布。

## 修复结果

- 根写入门禁增加原子 bootstrap。首次绑定前只接受当前 Hook 解释器和受管脚本组成的精确命令；命令拼接、脚本仿冒、会话不一致和无效上下文继续失败关闭。
- `WorkspaceService.register` 能迁移旧单路径 roots 列表；多路径歧义返回明确错误。
- 安装清单升级到 v3。更新器记录文件级 inventory，将退役文件纳入 Plan、恢复备份、事务写入和失败补偿。
- `guard_task_writes.py` 与 `xiaoh_security/execution.py` 没有被删除。两者已更新为 4.0.1 契约，因此从 4.0.0 升级后不会继续运行旧逻辑。

## 验证

| 类别 | 命令 | 结果 |
| --- | --- | --- |
| 完整测试 | `python3 -m unittest discover -s tests` | 75 项通过 |
| 安全回归 | `python3 -m unittest tests.test_runtime_400_security` | 通过 |
| 安装与迁移 | `python3 -m unittest tests.test_runtime_400_installation tests.test_runtime_400_services` | 通过 |
| Validator | `python3 plugins/xiaoh/runtime/codex/agent-system/validate.py` | 通过 |
| Hook 自检 | `python3 plugins/xiaoh/runtime/codex/hooks/guard_task_writes.py --self-test` | 通过 |
| 静态 Doctor | `./verify.sh` | 代码候选可用；本机运行时未切换，因此激活状态保持 degraded |

受管验证证据保存在当前任务绑定对应的 `verification-evidence` 目录。Doctor 的 degraded 只说明当前进程仍在使用已安装版本，以及 Workspace 和自动化存在既有运行时提示，不表示 4.0.1 候选测试失败。

## 后续人工边界

仓库候选确认后，仍需由用户决定是否提交、推送、发布插件和安装到本机。安装完成后需要重启、信任更新后的 Hook，并运行 runtime Doctor。
