---
name: spec-rfc-openspec-consistency-review
description: 比对已确认的 Spec+RFC 与 OpenSpec proposal、design、specs、tasks，检查是否完整承接、可追溯、无语义漂移和无无来源新增。用户要求核对两类工件一致性、查找 OpenSpec 漏项或判断派生工件能否进入实现时使用。
---

# Spec+RFC 到 OpenSpec 一致性检查

对一个明确的 Spec+RFC 修订和一个完整 OpenSpec change 执行一次检查。只检查工件，不生成或修改实现，不启动 Agent，也不自动追加复查轮次。

## 必要输入

- 已确认的源 Spec+RFC 路径和修订号。
- OpenSpec change 目录，包括存在的 `proposal.md`、`design.md`、`specs/**/spec.md` 和 `tasks.md`。
- 适用的项目规则。缺少必要工件时结论为 `BLOCKED`。

## 工作流程

1. 读取 [检查清单](references/checklist.md)。
2. 从源工件提取 FR、NFR、接口、数据、权限、安全、兼容、迁移、失败行为、测试、回滚、风险和 TBD。
3. 读取全部 OpenSpec artifacts，记录缺失文件。
4. 本地文件可用时运行 `scripts/extract_coverage.py <spec-rfc.md> <change-dir>` 生成覆盖线索；线索不能替代语义判断。
5. 建立源条目到 OpenSpec 文件、章节和任务的覆盖矩阵。
6. 检查 MUST/不得/仅/全部/前置/失败/回滚等强约束是否被遗漏或弱化。
7. 检查 OpenSpec 新增内容是否有来源；合理推导必须标为推导，不能伪装成确认需求。
8. 检查 Requirement/Scenario 和 tasks 是否可测试、可执行并追溯当前 Spec 修订。
9. 可用时运行 `openspec validate <change-id> --strict` 并记录结果。
10. 输出一次性结论；工件变化后仅在用户或上层流程再次调用时重新检查。

## 输出

```markdown
## 结论
结论：PASS / PASS_WITH_FINDINGS / BLOCKED
源修订：<revision>

## 覆盖矩阵
| 源条目 | OpenSpec位置 | 结论 | 说明 |
|---|---|---|---|

## 阻塞与问题
- [P0/P1/P2] 源证据、目标位置、影响、修正建议

## 无来源新增
| 内容 | 位置 | 判断 | 建议 |
|---|---|---|---|

## 验证与未覆盖范围
- strict validation：...
- 未验证：...
```

## 结论规则

- `PASS`：关键条目全部承接，无语义漂移、无未标注新增，结构校验通过或明确不适用。
- `PASS_WITH_FINDINGS`：只有不改变业务结果的轻微表达或任务拆分问题。
- `BLOCKED`：关键条目缺失、强约束弱化、语义反转、无来源范围扩大、必要 artifact 缺失或 strict validation 失败。
