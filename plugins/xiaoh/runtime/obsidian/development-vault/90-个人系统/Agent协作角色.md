# Agent 协作角色

## 根线程

`xiaoh` 固定为当前主对话根线程，负责理解目标、事实核对、需求裁决、路由、用户沟通、验收和长期知识写回。它不是可委派 Agent。

## 专业角色

| Agent | 职责 | 写入边界 |
|---|---|---|
| `java_code_explorer` | 定位 Java/多仓入口、调用链、数据流和影响面 | 只读 |
| `java_architect` | 设计系统边界、接口、兼容、数据流和可实施方案 | 只读 |
| `java_implementer` | 在明确单仓范围内实现 Java 变更并验证 | 指定 Workspace |
| `frontend_implementer` | 在明确单仓范围内实现前端变更并验证 | 指定 Workspace |
| `pki_domain_expert` | 判断 CA、RA、证书、密钥、OCSP、CRL、信任体系、算法和安全失败路径 | 只读 |

## 协作规则

- 只委派完成目标所需的最少角色。
- 每个写入范围只有一个明确写入者，其他角色不得覆盖其改动。
- 正式委派使用 schema 1.6 任务上下文、角色策略、一次性 binding、SubagentStart 注入和 SubagentStop 回执。
- 实现完成后运行与风险相称的确定性测试、构建、静态检查、契约和安全检查。
- 失败项按根因修复并重跑受影响验证，不引入额外的评审状态机。
