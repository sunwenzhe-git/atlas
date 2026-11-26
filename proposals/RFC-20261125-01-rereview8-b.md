# RFC-20261125-01 第八回评审乙意见

冻结：`ed40f39ef8b09cd0ae9c1eaed41aca98e8f0589089a627262ecb1c8110e13c9d`，92/92 匹配，514 tests passed。未改树/提交/推送。

## Critical

无。

## Major

1. `_support/legacy_migration.py:371-391,599-605`：HEAD 收全部 docs/*，index/inventory 只收 md/代码，config.mts/LICENSE/PNG/HTML 被误判暂存删除。修复：三处共用 recognized/unknown 谓词。
2. `_support/workflow_finish.py:733-745`、`_support/workflow_receipt.py:568-591`：动态字段不在暂存面时 finish WARN0，fresh UNVERIFIED2，digest 对拍失败。修复：receipt 绑定 scope，重放按同字段级 scope 裁决。
3. `_support/incident.py:436-457`：空白 verified_by 或逾期 action 空白 waiver 可关闭。修复：必填字符串 strip。

## Minor

- Incident/Docs OSError 吞成不存在/False 再 FAIL1，应上抛模块边界 UNVERIFIED2。
- Docs 嵌套相对链接先查根，根 README 存在可掩盖文档目录缺文件。修复：按文档目录解析，仅 / 开头按根。

## 结论

fresh 删除防护/白名单/冲突、未知格式、Incident fresh 聚合、Semantic base、空白 evidence 已闭合。**阻断 Major 1–3，修复后重冻结。**
