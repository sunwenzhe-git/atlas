---
name: atlas-bug
description: 修复已知缺陷时执行 canonical 落点、diff 回推与 finish 封印；适用于 bug fix、现场/联调/测试期缺陷及缺陷台账查询。
---

# atlas-bug

## 流程

1. **定位缺陷落点**
   - 已有任务卡：读取 `task.json.requirement_root`，确认 `requirement.md` 类型恰为 `缺陷`。
   - 无任务卡：运行 `atlas bug --unit <slug> --requirement <base#R-NN> --report <缺陷报告.md> --stage prod|integration|test`。
   - 完成判据：canonical 根为 `<assets_root>/requirements/<slug>/`，且 `work/缺陷报告.md`、`record.json` 存在。

2. **实现并暂存**
   - 按任务卡实现修复，先暂存实现文件。
   - 完成判据：`git diff --cached` 只含本缺陷实现变更；普通 blob 与删除之外的对象类型会被 `atlas bug` 前置拒绝。

3. **回推**
   - 运行 `atlas bug --unit <slug> --from staged --root-cause "<根因>" --json`。
   - 返回 `needs_decision` 时，读取列出的冲突，取得签字决策文件后带 `--decision-file` 重跑。
   - 完成判据：返回 `backflow_status=applied`，相关校验器 rc0，`record.json` 与变化文档已暂存。

4. **验证与收口**
   - 运行 `atlas workflow verify --unit <task-id>`，再运行 `atlas workflow finish --unit <task-id>`。
   - 完成判据：verify 的 `review.json.bug_backflow` 锚存在，finish rc0；缺锚、记录过期、index/worktree 分叉或未暂存产物都会被阻断。

5. **提交后补链**
   - 运行 `atlas bug link <slug> --commit <sha> [--pr <url>]`。
   - 完成判据：`atlas bug show <slug>` 能看到 commit/PR 与 append-only 历史。

## 查询

- `atlas bug show <slug>`：查看单条台账。
- `atlas bug list --target <path|AC|clause>`：反查最近缺陷。

## 权威边界

- 缺陷状态与关联需求以 `requirement.md` 为准；现象证据以 `work/缺陷报告.md` 为准；审计元数据以 `record.json` 为准。
- 语义冲突只报告，不替用户选边；精确改写必须来自签字决策文件。
- 双落点规则与字段契约见 `.atlas/shared/single-source.md`、`.atlas/rings/prd/reference.md`、`.atlas/templates/bug/record.schema.json`。
