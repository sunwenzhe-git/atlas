# RFC-20261125-01 最终独立评审甲意见

冻结：`122c58b851e6c5d18eb2478d00b18c7b80813a8ea8314d9ff2cfb112974d47d1`，94/94 匹配。只读。

## Critical

1. `scripts/atlas_check.py:118-132,391-393`：删除 migration manifest 但保留 generations，或仅有 contracts/expected.json 时，前置 SKIP、整体 rc0，绕过 UNVERIFIED2/FAIL1。修复：前置识别二类资产并跑 validator。第十四回 Critical 重开。

## Major

1. fresh 阻断：`_support/workflow_receipt.py:340-352,548-557` 与 `validators/validate_migration.py:136-138`：source_manifest+receipt enforce 时，证据 tree 无 origin、重放索引含 origin，校验恒 UNVERIFIED2，finish 失败。修复：重放索引排除 ORIGIN_REL。
2. 漏审：`_support/workflow_receipt.py:143-145,428-442` 与 `_support/workflow_finish.py:101-115`：审查普通文件后改 symlink 并暂存，ACDMR 漏 T 致 scope 不变，未重审仍 PASS。修复：三处 filter 加 T。

## Minor

1. `_support/classification_contract.py:173-220`：直调 classify_record(record, scorer, explicit_type="bug", mode="off") 得 PASS0。修复：入口验 mode，off 返 UNVERIFIED2。

## 结论

阻断。历史 Critical/Major 未见其它重开。
