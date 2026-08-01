# Runtime maintenance requirements

## Bootstrap

系统必须允许唯一受管 bootstrap 命令在首次绑定前运行，并拒绝仿冒、拼接、额外参数、无效结构或会话不一致的命令。成功时上下文和绑定必须同时可见；失败时二者都不可见。

## Workspace compatibility

系统必须将旧单路径 roots 列表迁移到 darwin 映射；歧义列表不得静默选择。

## Managed-file lifecycle

系统必须从可信受管 inventory 识别退役文件，将删除纳入安装计划、恢复备份、实际写入和补偿事务，并限制删除范围不超出已声明受管目录。
