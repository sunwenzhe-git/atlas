# RFC-20261125-01 第九回评审甲意见

冻结：`211e6609d36d14c112456b2d47ca91688c949ab8c224b6e40f978b3a9d510509`，92/92 匹配，332 tests passed。未写文件/提交/推送/mutation。

## Critical

无。

## Major

1. `_support/legacy_migration.py:349-387,590-601`：Git 元数据失败被当成非 Git 仓跳过核对，损坏 .git/HEAD 后 migrate/check PASS0。修复：区分非仓与仓内 HEAD/ls-tree 失败，后者 migration_unverified/rc2。
2. `_support/runtime_topology.py:270-276`、`_support/workflow_finish.py:739-745`、`_support/workflow_receipt.py:594-601`：scope 是产物级；identity UNVERIFIED 无来源，可被错误降 WARN。修复：identity 记录来源，逐字段裁决，在面/来源不明保持 UNVERIFIED，finish/fresh 共用 helper。

## Minor

- Incident 批量 check 把单案 I/O UNVERIFIED2 聚合成 FAIL1，应优先保留 UNVERIFIED。
- Docs `_evidence_digest` 吞 OSError，应传播 DocsIOError。
- recognized+unknown 未真正共用，根 openspec 路径可漏；三处共用分类函数。

## 结论

**阻断 Major 1–2，修复后重冻结。**
