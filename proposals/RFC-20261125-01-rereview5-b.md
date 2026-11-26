# RFC-20261125-01 第五回评审乙意见

冻结：`bd05c567aa5833a0d1afb0c2118daf5aee982949b482cdd99913ec859deb7088`，92/92 匹配，定向 258 passed。未跑 mutation。

## Critical

无。

## Major

1. `_support/workflow_receipt.py:540-545`：重放未传 mode/task scope，Docs enforce 被重放成 shadow，Incident 从指定 ID 变全部。修复：传 --mode、--doc-id、resolves ID。
2. `_support/legacy_migration.py:454-459,492-493`、`validators/validate_migration.py:124-126`：证据登记 index tree，却在工作树跑测试；暂存失败/工作树通过可 PASS。修复：全部暂存快照执行或拒绝差异。
3. `_support/workflow_receipt.py:502-508`：classification 代码哈希在空重放集合时被跳过。修复：先验全部 in-scope 哈希。

## 结论

历史 Critical 关闭。**阻断 Major 1–3，修复后重冻结。**
