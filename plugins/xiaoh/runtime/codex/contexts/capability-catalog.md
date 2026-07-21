# 能力目录

## 协调与治理

- 意图域隔离：区分全局能力、平台能力和业务项目。
- 上下文门禁：校验目标、范围、事实源、验收与停止条件。
- 委派门禁：保护 `xiaoh` 根身份并认证正式专业 Agent 运行。
- 证据闭环：任务上下文、运行记录、验证和独立评审可追溯。
- 配置进化：依据真实运行证据提出改进候选，不自动扩大权限。

## 专业角色

- `java_code_explorer`：只读探索 Java 代码与影响面。
- `java_architect`：架构、接口、依赖和实施边界判断。
- `java_implementer`：在单一授权范围内实现 Java 变更。
- `frontend_implementer`：在单一授权范围内实现前端变更。
- `pki_domain_expert`：PKI 语义、生命周期和验收判断。
- `pki_security_reviewer`：密码、密钥、信任边界与安全专项评审。
- `test_integration_verifier`：测试矩阵、独立验证和集成证据审计。
- `code_quality_reviewer`：正确性、回归、并发、性能和测试缺口评审。

## 通用 Skill

- `spec-rfc`：把需求整理为可评审的 Spec/RFC。
- `spec-rfc-reviewer`：判断方案是否达到开发准入标准。
- `spec-rfc-openspec-consistency-review`：审核源文档与 OpenSpec 工件一致性。
- `fit-for-purpose-engineering`：比较最小改动与更符合业务目标的实现路径。
