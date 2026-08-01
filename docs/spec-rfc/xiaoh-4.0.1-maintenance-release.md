# XiaoH 4.0.1 兼容性修复 Spec+RFC

## 状态

- 需求来源：用户于 2026-08-01 明确要求修复三个 4.0.0 缺陷并发布补丁版本。
- 基线状态：已确认。
- 目标版本：4.0.1。
- 兼容边界：保持 4.0.0 的产品能力和对外命令，不兼容边界不变。

## 问题与目标

1. 首次根写入要求 schema 1.6 task-context 和根执行绑定，但创建两者的命令本身也被无绑定门禁拒绝。4.0.1 必须提供一个严格受管、单命令、原子化的 bootstrap 入口。
2. 旧配置允许 `roots: ["/path"]`，`WorkspaceService.register` 却把列表直接传给 `dict()`。4.0.1 必须把唯一旧路径迁移为 `{"darwin": "/path"}`，同时写入当前平台根；多路径歧义必须失败关闭。
3. 更新器缺少跨清单版本的文件级所有权记录。4.0.1 必须记录精确受管文件 inventory，将退出 inventory 的文件作为 `delete` 纳入 Plan、备份、切换、写入记录和逆序补偿。

## 关键契约

### 原子 bootstrap

- 唯一预绑定写入口为受管 `guard_task_writes.py --bootstrap --task-context-base64 ... --session-id ...`。
- Hook 必须校验当前 Hook 解释器的绝对路径、受管脚本绝对路径、参数集合、会话一致性、Base64/JSON 结构和 schema 1.6；额外参数、路径仿冒、命令拼接和会话漂移均拒绝。
- bootstrap 在互斥锁内验证上下文，写入 canonical task-context 和 binding；任一步失败清除二者，不留下半绑定状态。
- 原 `--prepare --task-context` 保持兼容。

### Workspace 迁移

- 对象 roots 原样保留。
- 空列表迁移为空对象。
- 仅含一个非空字符串的列表迁移到 `darwin`。
- 多路径、非字符串或其他结构返回明确错误，不猜测平台归属。

### 受管文件退役

- 安装清单 v3 声明当前和上一版受管目录、上一版文件 inventory。
- 安装后写入 `.xiaoh-managed-runtime.json`，供后续同版本修复和升级识别旧所有权。
- 只允许删除当前或上一版明确声明的受管目录内路径，拒绝绝对路径、父目录逃逸和未声明根目录。
- 删除与普通覆盖使用同一恢复清单和事务；验证失败时必须恢复原文件及摘要。
- `guard_task_writes.py` 与 `xiaoh_security/execution.py` 在 4.0.1 中继续受管，并升级为新 bootstrap 契约，因此不作为退役文件删除。

## 验收与验证

- 无绑定时精确 bootstrap 可运行，其余写入仍失败关闭。
- 有效 bootstrap 同时产生上下文和绑定；无效输入不留下任何一个。
- 旧单 roots 配置可注册，多 roots 明确拒绝。
- 陈旧受管文件出现在 `expected_deletes`，提交后消失；事务失败后恢复。
- 定向安全、服务、安装测试和完整测试套件通过。
- 只生成仓库代码候选，不安装或更新本机 XiaoH 运行时。
