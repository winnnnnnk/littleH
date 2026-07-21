---
name: spec-rfc-openspec-consistency-review
description: 当需要审核由 Spec/RFC 文档生成的 OpenSpec proposal、design、specs、tasks 是否完整承接源文档、无遗漏、无语义漂移、无无来源新增内容时使用。适用于用户要求“比对 Spec/RFC 和 OpenSpec 是否一致”“审核 OpenSpec 是否遗漏 Spec/RFC 细节”“检查 proposal/design/specs/tasks 是否忠实转换源文档”等场景。
---

# Spec/RFC 到 OpenSpec 一致性审核

## 目标

这个 skill 用于审核 OpenSpec 产物是否忠实承接源 Spec/RFC 文档。它不负责生成 OpenSpec，也不负责审核实现代码；它只回答一个问题：当前 OpenSpec 是否完整、准确、可追溯地表达了源 Spec/RFC。

重点检查：遗漏、语义漂移、约束弱化、前置条件丢失、风险和回滚缺失、测试策略缺失、OpenSpec 结构错误、无来源新增内容。

## 什么时候使用

在以下场景必须使用：

1. 用户要求审核 Spec/RFC 生成的 OpenSpec 是否一致。
2. 用户要求检查 OpenSpec proposal、design、specs、tasks 是否遗漏源文档细节。
3. OpenSpec 是从 `docs/spec-rfc/*.md`、RFC、PRD、设计文档或会议需求整理而来，并准备进入实现前准入。
4. 用户要求判断 OpenSpec 是否可以进入编码阶段。
5. 用户要求输出覆盖矩阵、差异清单、遗漏项或语义偏差报告。

不适合替代：

1. `spec-rfc-reviewer`：它审核源 Spec/RFC 本身是否达到准入质量。
2. `openspec-verify-change`：它验证实现是否符合 OpenSpec。
3. 代码 review、测试 review 或发布验收。

## 输入

至少需要：

1. 源 Spec/RFC 文档路径。
2. OpenSpec change 目录路径，通常包含 `proposal.md`、`design.md`、`specs/**/spec.md`、`tasks.md`。

可选输入：

1. 项目 `AGENTS.md`、`openspec/project.md`、代码地图或领域约束。若当前仓库存在这些文件，审核时必须叠加项目约束，不得只按通用 OpenSpec 规则判断。
2. 用户指定的重点检查项，例如 DB、接口、兼容性、安全、发布前置检查。

## 工作流程

1. 读取 `references/checklist.md`，用其中的高风险词、漏项高发区和覆盖矩阵示例作为本次审核清单。
2. 读取源 Spec/RFC 文档，提取结构化条目：背景、目标、FR、NFR、外部接口、数据规则、过渡要求、前置条件、约束、风险、测试、回滚、TBD、术语。
3. 读取 OpenSpec artifacts：`proposal.md`、`design.md`、`specs/**/spec.md`、`tasks.md`。不存在的 artifact 标为缺失。
4. 若源文档和 change 目录都是本地文件，优先运行 `scripts/extract_coverage.py <source-spec-rfc.md> <openspec-change-dir>` 生成初版覆盖线索；脚本结果只能作为线索，不能替代人工语义判断。
5. 建立覆盖矩阵：每个源条目至少映射到一个 OpenSpec 位置。位置要精确到文件和章节，能到行号更好。
6. 检查语义一致性：判断 OpenSpec 是否改变了源文档中的 MUST/SHALL、范围、条件、异常路径、前置条件或回滚语义。
7. 检查弱化项：源文档的“必须、不得、仅、全部、前置、阻止、失败”是否被写成模糊建议或遗漏验收条件。
8. 检查无来源新增项：OpenSpec 是否新增了源文档没有依据的功能、范围、技术方案、数据规则或承诺。若是合理推导，标为“推导”，不能标为“已确认事实”。
9. 检查 specs 质量：每个 capability 是否有对应 spec；ADDED/MODIFIED 是否合理；每个 requirement 是否有 `#### Scenario:`；场景是否可测试。
10. 检查 tasks 可执行性：任务是否覆盖实现、测试、文档、验证、回滚和前置检查；是否只是泛泛任务。
11. 运行或建议运行 `openspec validate <change-id> --strict`。如果已运行，记录结果；如果不能运行，说明原因。
12. 输出审核报告和结论。


## 辅助资源

- `references/checklist.md`：审核前必须读取，包含高风险词、漏项高发区、覆盖矩阵示例和判定补充。
- `scripts/extract_coverage.py`：当源 Spec/RFC 和 OpenSpec change 都在本地时使用，用于生成源条目到 OpenSpec 文件的初版命中线索。脚本不会判断语义一致性，只用于减少漏扫。

脚本示例：

```bash
python3 __CODEX_HOME__/skills/spec-rfc-openspec-consistency-review/scripts/extract_coverage.py docs/spec-rfc/example.md openspec/changes/example-change
```

## 审核维度

### 覆盖性

检查源文档中的每个重要条目是否在 OpenSpec 中出现，尤其是：

1. 功能需求和验收标准。
2. 非功能需求。
3. 数据规则、查询条件、字段绑定、唯一性、空值规则。
4. 外部接口、CLI、资源目录、数据库对象。
5. 过渡要求、发布前置检查、人工处置规则。
6. 约束和假设。
7. 风险缓解。
8. 测试策略。
9. 回滚计划。
10. TBD 和待确认项。

### 一致性

重点检查：

1. 源文档限定“仅 A”时，OpenSpec 是否扩大到 B。
2. 源文档要求“必须失败/阻止/不得继续”时，OpenSpec 是否变成 warning 或建议。
3. 源文档要求“保持兼容”时，OpenSpec 是否修改了既有行为。
4. 源文档要求“发布前置检查”时，OpenSpec 是否写成实现阶段可选项。
5. 源文档中的优先级、来源和确认状态是否被保留或合理转写。
6. OpenSpec 中新增的技术方案是否有源文档依据或设计推导标注。

### OpenSpec 结构质量

检查：

1. `proposal.md` 是否说明 Why、What Changes、Capabilities、Impact。
2. `design.md` 是否说明关键决策、备选方案、风险、迁移和回滚。
3. `specs/` 是否按 capability 拆分。
4. MODIFIED requirement 是否复制完整原 requirement 并修改，而不是只写增量片段。
5. 每个 requirement 是否至少有一个 `#### Scenario:`。
6. `tasks.md` 是否使用 `- [ ] X.Y` 可跟踪格式。
7. `openspec validate <change-id> --strict` 是否通过。

## 输出格式

默认输出中文报告，使用以下结构：

```markdown
## 结论

结论：PASS / PASS_WITH_FINDINGS / BLOCKED

一句话说明能否进入下一阶段。

## 覆盖矩阵

| 源文档条目 | OpenSpec 位置 | 结论 | 说明 |
|---|---|---|---|
| FR-001 ... | proposal.md / specs/... | 覆盖 / 部分覆盖 / 缺失 | ... |

## 发现的问题

### P0 阻塞

- 问题：...
  依据：源文档 ...；OpenSpec ...
  影响：...
  建议：...

### P1 必改

- ...

### P2 建议

- ...

## 无来源新增项

| OpenSpec 内容 | 位置 | 判断 | 建议 |
|---|---|---|---|

## 语义漂移或弱化项

| 源语义 | OpenSpec 语义 | 风险 | 建议 |
|---|---|---|---|

## 验证

- `openspec validate <change-id> --strict`：通过 / 未通过 / 未执行
- 其他检查：...

## 最小修正建议

1. ...
2. ...
```

## 结论规则

- `PASS`：源文档关键条目均覆盖，无阻塞遗漏，无明显语义漂移，OpenSpec strict 校验通过或无需运行。
- `PASS_WITH_FINDINGS`：存在轻微遗漏、表达弱化或可改进项，但不影响进入下一阶段。
- `BLOCKED`：存在关键需求遗漏、语义反转、前置条件丢失、风险/回滚缺失、spec 格式不合法，或 strict 校验失败。

## 规则

1. 不凭记忆判断一致性，必须同时读取源 Spec/RFC 和 OpenSpec artifact。
2. 不把 OpenSpec 写得更完整就视为一致；新增内容必须能追溯来源或明确标为推导。
3. 不只检查 proposal，必须检查 proposal、design、specs、tasks 的整体承接关系。
4. 不把 `openspec validate` 通过等同于内容一致；它只证明结构合法。
5. 源文档中的“必须、不得、仅、全部、前置、失败、阻止、回滚、人工处置”是高风险词，必须重点追踪。
6. 如果源文档和项目规则冲突，标注冲突并说明需要人工确认，不自行改写事实。
7. 输出以发现和证据为主，避免泛泛表扬。
8. 如果没有发现问题，明确说明“未发现一致性问题”，并列出仍未验证的范围。

## 常见问题

1. 只看 OpenSpec，不回到源 Spec/RFC。
2. 只核对标题，不核对验收标准和失败路径。
3. 只看 proposal，漏掉 specs/tasks 是否完整。
4. 把源文档的发布前置检查漏写到 tasks。
5. 把“public only”“仅对某类配置”扩展成所有配置。
6. 把 TBD 写成已确认事实。
7. MODIFIED requirement 只写新增场景，没有复制完整原 requirement。
