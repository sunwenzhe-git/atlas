# 实现代码独立审查派工单 — ANCHOR-W1

> 由 `atlas review` 生成（`impl_review.executor: session`）。本文件是**指针**，不复制正文。

## 独立性要求（硬）
- 派一个 **fresh-context 子代理** 执行审查：**不得**继承实现/生成时的上下文。
- 子代理只读下面的指针，不读整仓；**只写产物**，不得改业务代码、不得改暂存区。

## 权威输入
- 背景：`/private/tmp/atlas-anchor-window/product/reviews/2026-11-22-impl-review-ANCHOR-W1/background.md`
- 输入清单：`/private/tmp/atlas-anchor-window/product/reviews/2026-11-22-impl-review-ANCHOR-W1/inputs/MANIFEST.json`（按清单读当前文件，不拷贝）
- 审查焦点三问：`.atlas/shared/independent-review.md` §10.4

## 探索预算（硬）
- 只读本单指针与实审集（你产物 `manifest.coverage.selected[]` 的 N 个文件）；工具调用上界 **≤ N + 8 次**（N = 实审文件数，自行计数）。
- 禁入 `product/reviews/`（含 findings/）与 `.atlas/tasks/` 的历史轮产物；round ≥ 2 的复审只审上轮 findings 涉及文件及其直接引用。
- 逃生门：发现流程异常（脏工作区 / 轮次产物矛盾）允许扩面，但必须在 cli.json `warnings` 登记扩面理由。

## 审查范围
- 模式：暂存区（HEAD..INDEX）
- 应审文件：在产物 `manifest.coverage.selected[]` 中逐项列出本次实审范围（缺该项 ⇒ 应审 N 不可得，转换器拒绝产出）

## 产物
- 写到：`/private/tmp/atlas-anchor-window/product/reviews/2026-11-22-impl-review-ANCHOR-W1/cli.json`
- 每条 finding 必须带 `existing_code`：finding 指向代码的**逐字摘录**（1-5 行，从 diff 或相关文件原样复制，禁止改写/重排/缩进调整）——行号锚定复算输入，缺失按 unanchored 统计（不判错，RFC-20261122-08）。
- 审查顺序：先审变更核心（heart），再审其后果（consequences），最后审胶水（glue：配置/注册/样板）。
- 形态（CLI 同构 JSON，供 `cli_review_convert.py` 转换）：

```json
{
  "status": "completed",
  "executor": "session-subagent",
  "summary": {
    "files_reviewed": 0,
    "comments": 0
  },
  "comments": [
    {
      "severity": "critical|high|medium|low",
      "category": "bug|security|performance|maintainability|test|style|documentation",
      "path": "src/a.ts",
      "start_line": 1,
      "end_line": 2,
      "existing_code": "<finding 指向代码的逐字摘录，1-5 行>",
      "content": "<问题描述 + 证据链（file:line）>",
      "suggestion_code": ""
    }
  ],
  "warnings": [],
  "manifest": {
    "coverage": {
      "selected": [
        {
          "path": "src/a.ts"
        }
      ],
      "completed": [
        {
          "path": "src/a.ts"
        }
      ],
      "failed": [],
      "waived": [],
      "reused": []
    }
  }
}
```

## 完成后
- 复跑 `atlas workflow verify --unit <ID>`（或 `atlas review --unit <ID> --staged`）：读取本轮 `cli.json`，继续 scope manifest → 转换 → 校验 → 闭环。
- `finish` 仍只认 `review.json` 为 PASS；本派工包本身**不是通过**。
