# RFC-20261125-01 第七回评审甲意见

冻结：`8a4e4a44cb985cd6ea1a0c19df57f6105c7d2f61127cbfda40f5d6ba763e6d9b`，92/92 匹配，定向 240 passed。只读，未跑 mutation。

## Major

1. `_support/legacy_migration.py:358-376,578-587`：只核对工作树 inventory 与当前 index，未核对 HEAD 已跟踪路径；git rm docs/guide.md 后迁移仍 PASS。修复：HEAD/index/inventory 双向核对，显式拒绝暂存删除或按 index 快照生成。

## Minor

- Docs/Incident 内层读取 OSError 被转成 docs_stale/incident_evidence_missing、FAIL/rc1。修复：I/O 原样上抛至模块边界，映射 UNVERIFIED/rc2。
- `scripts/atlas_docs.py`、`scripts/atlas_topology.py` 外层 OSError 仍 FAIL/rc1。修复：统一走 *_unverified/rc2。

## 结论

**阻断；修复后重新冻结复核。**
