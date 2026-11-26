# RFC-20261125-01 第二回评审乙意见

冻结输入：`9ecf7a2002f068e8b088188e8560666ba927133e826a85661c663096fa1449a5`（92/92 文件匹配，评审前后零漂移）。reviewer 未跑测试/mutation。

## Critical

无。

## Major

1. `_support/semantic_contracts.py:234-243,484-493`：`--head` 指向 Integer 提交、index 仍为 String 时按 index 投影并 PASS。`:335-337,388-392`：期望 `test_a`、同文件实际仅 `test_b` 也匹配。修复：head≠base 时物化 head tree；测试契约按完整 node 比对，adapter 不支持则 UNVERIFIED。
2. `_support/workflow_finish.py:748-764` 只验校准 rc；合法 `decision=shadow` 且 receipt 默认 shadow 仍收口。`_support/workflow_receipt.py:161-182` 仅检查 input_digest 形状，全局分类文件可跨任务复用。修复：无条件要求 decision=enforce，比对任务 input digest 与校准 scorer_version。
3. `_support/workflow_receipt.py:214-248`：先覆盖 review artifact、暂存 origin，后才校验分类/schema；失败可破坏旧 receipt 并残留 origin。修复：全部预检后写产物，失败恢复 index/artifacts。
4. `adapters/topology_compose.py:44-47` 动态服务名 UNVERIFIED id 为 file:line，finish 无法从 items 反查来源，无关任务也被阻断。修复：UNVERIFIED 直接携带 source_file，按暂存路径判 scope。

## 结论

旧轮 staged 重投影、review artifact/origin/fresh、Topology staged/根目录 glob、JUnit 全 case、owner/due 不继承、UNVERIFIED rc2 不扣预算、无 adapter UNVERIFIED 均通过。

**不可交付；阻断 Major 1–4，修复后补回归。**
