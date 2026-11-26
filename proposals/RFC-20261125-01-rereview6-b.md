# RFC-20261125-01 第六回评审乙意见

冻结：`5b6646c003807b9e694add3fee5f980d01a555d5ed1d3f93e31694c4ce9fd351`，92/92 匹配。未跑 mutation。

## Critical

无。

## Major

1. `_support/workflow_receipt.py:538-544`：fresh 物化后无条件用外部 evidence 覆盖重建树，可用新运行件洗掉旧 staged tree。修复：树中已有路径必须字节/hash 相等，仅允许注入树中缺失且由 staged 输入产生的产物。
2. `_support/legacy_migration.py:144-182,477-482`：inventory 只走工作树，index-only 新增文件删工作树后漏掉。修复：git ls-files 与 inventory 双向核对路径/hash，或按 index 快照运行。
3. `_support/workflow_receipt.py:448-451`：只检查 Semantic head==base，不绑定 receipt base；旧 A 投影可在 B receipt 下 PASS。修复：base/head 均等于 receipt base。

## Minor

- Docs/Incident/Topology 读取 OSError 映射 FAIL/rc1，应 UNVERIFIED/rc2。

## 结论

module mode/scope、分类哈希、运行时闭包、origin 排除、空 evidence 已通过。**阻断 Major 1–3，修复后重冻结。**
