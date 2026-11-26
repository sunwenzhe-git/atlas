# RFC-20261125-01 最终双评审乙意见

冻结输入：`c8e397614ef045857c2ba64009faaf58a025f3ff43eccd301956c238b9cbc9e0`（92 文件总 SHA256 匹配，0 漂移）。512 测试通过；M245–M251 证据链一致；安装 48 文件一致。未跑 mutation/check。receipt 临时索引修复有效。

## Critical

1. `_support/semantic_contracts.py:129`：暂存 Integer、工作树 String 时 refresh/check 仍 PASS0，receipt 错绑漂移。修复：按 staged blob 抽取，不一致即 UNVERIFIED。

## Major

2. `scripts/atlas_workflow.py:398-409`：根 `compose.yaml` 不匹配 `**/compose*.yaml`；实测预检跳过而 check FAIL。修复：复用 `scan_sources`，解析失败 rc2。
3. `_support/legacy_migration.py:427-439`：2 参数 1 skip 仍 migration PASS0。修复：收齐节点全部 JUnit case，禁 skip/xfail。
4. `_support/workflow_finish.py:765-774`：只验全局校准、硬编码 enforce，未绑定任务结果/off；未分类/弃权可收口。修复：绑定结果、用真实 mode。
5. `shared/schemas/semantic-expected.json:10-15`：缺错误码/config/CLI/状态流转/AC 投影，不符 §6.2。修复：补适配器、kind、反例。

## 校准与结论

无真实 owner/scorer 预测，§15 未完成；留 shadow/UNVERIFIED 诚实，不能称 enforce。

**评审乙结论：不可交付；阻断 Critical 1、Major 2–5；修复后重测。**
