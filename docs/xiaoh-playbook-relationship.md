# XiaoH 与 Playbook 的关系

XiaoH 可独立运行。Playbook 只在任务上下文明确标记为受管时启用。

XiaoH 负责需求理解、项目历史、任务上下文、专业 Agent 委派、本地实现协调、确定性验证和知识收口。Playbook 负责受管 Workspace、task/member/worker、远程 MR、pipeline、人工 Approval、合并和清理等平台事实。

适配器只读取当前 worker JSON 和 task status JSON，生成一次性 worker receipt。receipt 绑定 XiaoH Workspace 身份、Playbook task Workspace 身份、change、member、worktree、allowed scope、action 和源文件摘要。源状态变化、超时或范围不一致时失效。

XiaoH 不修改 Playbook 来适配自己，不复制其状态机，也不把未受管任务因为本机存在 `playbook` 命令就自动升级为受管任务。Playbook CLI 的安装、升级、降级、重装、版本切换和安装源切换始终由用户人工执行。
