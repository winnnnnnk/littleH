# Spec/RFC 到 OpenSpec 一致性审核清单

## 高风险词

审核时优先追踪源文档中的以下词语，它们通常代表强约束或失败边界：

- 必须、不得、禁止、仅、只、全部、任一、至少、最多
- 前置、发布前、安装前、人工处置、阻止、中断、失败、报错
- 兼容、保持不变、不影响、回滚、恢复、备份
- 唯一、null、空值、索引、触发器、约束、主键、事务
- warning、error、日志、可诊断、国际化、测试、验证
- TBD、待确认、假设、来源、用户确认、准入评审补充

## 覆盖矩阵示例

| 源文档条目 | OpenSpec 位置 | 结论 | 说明 |
|---|---|---|---|
| FR-005：仅 public 配置按 config_name 唯一定位 t_config | proposal.md / specs/public-db-config-sync/spec.md / specs/db-config-sync/spec.md | 覆盖 | proposal 写业务规则，specs 写可测试场景 |
| TR-003：public 历史 active 记录前置处置 | proposal.md / tasks.md | 部分覆盖 | 如果 tasks 未包含前置 SQL，则必须补齐 |
| NFR-003：多条 active 记录可诊断 | specs/public-db-config-sync/spec.md | 覆盖 | 需确认错误信息包含 config_name |

## 漏项高发区

1. 源文档的“发布前置检查”只写进 proposal，漏写到 tasks。
2. 源文档的“现有行为保持兼容”没有写进 specs 的回归场景。
3. 源文档的“失败/阻止/不得继续”在 OpenSpec 中被弱化成 warning。
4. 源文档的“仅 public”在 OpenSpec 中被扩大成所有配置。
5. 源文档的测试策略只写到 proposal，没有拆进 tasks。
6. 源文档的回滚计划没有写进 design 或 tasks。
7. MODIFIED spec 没有复制完整原 requirement，归档后会丢旧场景。
8. OpenSpec 新增了设计建议，但没有标注是“设计推导”还是“源文档确认”。

## 审核证据要求

每个问题至少给出：

- 源文档依据：章节、编号或原文摘要。
- OpenSpec 位置：文件和章节；能定位行号时给行号。
- 差异判断：缺失、部分覆盖、语义漂移、弱化、无来源新增。
- 影响：为什么会影响实现或验收。
- 建议：最小修正方式。

## 判定补充

- 结构校验失败，结论至少为 BLOCKED。
- 核心 FR 缺失，结论为 BLOCKED。
- 发布前置检查缺失且影响数据安全，结论为 BLOCKED。
- 只有 tasks 拆分不够细，但 proposal/specs 完整，通常为 PASS_WITH_FINDINGS。
- OpenSpec 有合理设计推导但未标注来源，通常为 PASS_WITH_FINDINGS；若改变需求语义，则为 BLOCKED。
