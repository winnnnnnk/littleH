# Design

- 在根 Hook 中增加精确白名单 bootstrap 命令，并由 `RootExecutionGate.bootstrap` 在互斥锁和失败清理下生成上下文与绑定。
- 在 Workspace 注册边界集中迁移旧单元素 roots 列表。
- 将安装清单升级为 v3，持久化文件级受管 inventory；Planner、Candidate、Recovery 和 Transaction 共同承接 delete 动作。
- 两个用户点名的旧文件继续由新版本管理，并与 bootstrap 契约兼容。
