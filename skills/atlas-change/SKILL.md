---
name: atlas-change
description: 需求变更或缺陷实现后自动执行 canonical 落点、diff 回推与 finish 封印；适用于需求变更、bug fix、现场/联调/测试期缺陷及台账查询。
---

# atlas-change

## 自动流程

1. **确认 canonical 落点**
   - 已有任务卡：读取 `task.json.requirement_root`，确认 `requirement.md` 类型为 `需求变更` 或 `缺陷`。
   - 新建落点：运行 `atlas change --unit <slug> --requirement <base#R-NN> --report <报告.md> --stage prod|integration|test`。
   - `需求变更` 证据住 `work/变更请求.md`；`缺陷` 证据住 `work/缺陷报告.md`；两者都必须有 `record.json`。

2. **实现并暂存**
   - 按任务卡实现，先暂存实现文件。
   - 普通 blob 与删除之外的对象类型会被回推内核拒绝。

3. **verify 自动回推**
   - 直接运行 `atlas workflow verify --unit <task-id>`，不必手动调用 change 命令。
   - verify 在独立评审前自动分析 staged diff、回推文档、运行校验器，并只暂存 exact 产物。
   - 缺报告、缺根因/变更原因或存在未签字冲突时停在评审前；补齐决策文件后用 `atlas change --unit <task-id> --from staged --decision-file <file> --auto-stage --json` 重跑。

4. **finish 自动封印**
   - 运行 `atlas workflow finish --unit <task-id>`。
   - finish 发现记录缺失/过期会自动补跑；若产物变化，必须重跑 verify 生成新鲜审查锚。
   - 完成判据：`review.json.change_backflow` 存在，finish rc0；`--force` 不能绕过回推门。

5. **提交后补链**
   - 运行 `atlas change link <slug> --commit <sha> [--pr <url>]`。
   - 完成判据：`atlas change show <slug>` 能看到 commit/PR 与 append-only 历史。

## 无父级缺陷路由

口头报的历史缺陷若无父级需求落点（`atlas change --unit <落点slug> …` 报「落点不存在」时）：

- **不建变更/缺陷落点**：台账必须锚定既有需求，无父级就不建台账。
- **直填建卡**：`atlas workflow plan --unit <任务卡ID>`（无 `--requirement`），现象/期望/实际证据写进任务卡 PRD；走同一条独立审查 verify/finish 门，审查与收口一分不少。
- 两个 `--unit` 记号不同：`atlas change` 的 `--unit` 是落点 slug，`atlas workflow plan` 的 `--unit` 是任务卡 ID，不要把 slug 直填成卡 ID。

## 查询与兼容

- `atlas change show <slug>`：查看单条台账。
- `atlas change list --target <path|AC|clause>`：反查变更/缺陷。
- `atlas bug` 是缺陷兼容别名；已有 `bug_backflow` 审查锚只读兼容，新评审统一写 `change_backflow`。

## 权威边界

- 类型、关联需求与状态以 `requirement.md` 为准；证据以对应 `work/` 报告为准；审计元数据以 `record.json` 为准。
- 语义冲突只报告，不替用户选边；精确改写必须来自签字决策文件。
- 双落点规则与字段契约见 `.atlas/shared/single-source.md`、`.atlas/rings/prd/reference.md`、`.atlas/templates/bug/record.schema.json`。
