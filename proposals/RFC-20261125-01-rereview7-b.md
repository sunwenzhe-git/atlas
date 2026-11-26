# RFC-20261125-01 第七回评审乙意见

冻结：`8a4e4a44cb985cd6ea1a0c19df57f6105c7d2f61127cbfda40f5d6ba763e6d9b`，92/92 匹配，定向 240 passed。未跑 mutation。

## Critical

无。

## Major

1. `_support/workflow_receipt.py:540-550`：fresh evidence 可回填 base 有、重建 tree 无的暂存删除路径。修复：禁止回填删除路径，并校验 evidence 模块产物白名单。
2. `_support/legacy_migration.py:358-376,584-587`：index 反向核对漏 OpenSpec/Trellis 未知格式。修复：_indexed_paths 与 inventory 使用同一 recognized+unknown 判定。

## Minor

- Docs/Incident 内层 I/O 被吞成确定性 stale/evidence-missing。修复：I/O 上抛至模块边界 UNVERIFIED/rc2。

## 结论

Semantic base 绑定、Incident 关闭聚合、空白 evidence 拒绝、Topology I/O 已通过。**阻断 Major 1–2，修复后重冻结。**
