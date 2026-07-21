# 变更记录

## 2.1.1 - 2026-07-21

- 增加macOS与Windows GitHub Actions验证矩阵。
- 增加双系统安装、诊断和`develop`分支使用说明。
- 修正Windows下Hook路径分隔符造成的配置漂移误判。

## 2.1.0 - 2026-07-21

- 增加业务需求工件路由和总体需求基线门禁。
- 新增`xiaoh-requirement-routing` Skill。
- 增加显式Skill执行状态、Spec+RFC、OpenSpec追溯与遗漏补救状态。
- 增加member确认、task create、OpenSpec确认、task start和实现前的确定性校验入口。
- 补充需求工件路由回归案例。

## 2.0.0 - 2026-07-21

- 改造成Codex原生Marketplace Plugin。
- 新增`xiaoh-core`、`xiaoh-setup`、`xiaoh-doctor`、`xiaoh-update`。
- 使用单一跨平台Python运行器完成备份、安装、更新和诊断。
- 保留显式Hook信任门禁，不在插件安装阶段隐式修改全局配置。
- npm发布继续延后。

## 1.4.0 - 2026-07-21

- 将小H完整拆分为可移植的通用协调能力。
- 移除客户、项目、仓库、真实证据和本机路径。
- 增加 macOS/Linux、Windows 安装与隔离验证能力。
- 支持通过 `CODEX_HOME` 和 `XIAOH_VAULT` 配置目标目录。
- 保留根线程身份门禁、专业角色、任务证据协议和空白 Obsidian 模板。
- 仓库仅保留可安装源码；发行压缩包和校验产物不纳入版本控制。
- 增加不受 Git 跟踪的 `config.local.json` 本地路径配置。
