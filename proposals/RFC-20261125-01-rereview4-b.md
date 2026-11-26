# RFC-20261125-01 第四回评审乙意见

冻结：`e4ec574f58c400d974ecbbf5ec0741aa0d92bf6fdc407c37bec99f5b238baad7`，92/92 匹配，定向 242 passed。未跑 mutation。

## Critical

无。

## Major

1. `_support/workflow_finish.py:861-869`：verify 后 restore origin，最终索引≠receipt tree，即时 current-tree 校验 FAIL。修复：验证后不改树，补 finish 后即时复核。
2. `_support/workflow_receipt.py:371-430,443-551`：fresh 未重跑 Semantic/Docs/Incident/Topology。修复：物化重建树，重跑全部 in-scope validator 并绑定代码哈希。
3. `_support/workflow_receipt.py:206-228`：auto 分类只验字段类型，不看有限数/范围/margin/top1/阈值。修复：补数值一致性与校准门槛校验。

## Minor

- `_support/governance_schema.py:195-199`：先拒绝 N/A，reason/owner/due 检查不可达。修复：允许合法 N/A 再验三字段。

## 结论

第三轮 4 项已关闭。**阻断 Major 1–3，修复后重冻结。**
