# RFC-20261125-01 最终双评审甲意见

冻结输入：`c8e397614ef045857c2ba64009faaf58a025f3ff43eccd301956c238b9cbc9e0`（92/92 文件匹配）。reviewer 全程未改源码、未提交/推送、未执行变异。

## Critical

1. `_support/semantic_contracts.py:120-136,536-590`：来源允许匹配 head 或 staged，且 check 不重投影。复现：暂存 `detail_url=Integer`、工作树恢复 String，enforce 仍 PASS；新增已暂存孤儿路由也 PASS。最小修复：staged 路径只认 `:0` blob，check 用临时索引重投影并比对新文件/facts。
2. `_support/workflow_receipt.py:272-278`、`_support/workflow_finish.py:765-774`：前者缺 `sys`，后者硬编码 classification=enforce。复现 shadow 校准得到 validator PASS/shadow，receipt verify 抛 NameError；仅补 import 后 receipt 以 enforce PASS。最小修复：补 import，消费并绑定 ledger 的真实 decision，enforce 仅接受 enforce。

## Major

3. `_support/workflow_receipt.py:214-228,298-343`：fresh checkout 仍从工作树读 semantic/review/origin，临时索引只算 tree。复现仅带 receipt+patch 的 clone 因缺 contracts 返回 UNVERIFIED；测试靠手工复制三件掩盖。最小修复：从重建索引取 blob 或物化临时工作树，将 review/origin 纳入 artifact，并由 CI 重跑 validator。
4. `scripts/atlas_workflow.py:398-409`：`fnmatch` 不匹配根目录 `compose.yaml` 与 `**/compose*.yaml`，verify 漏预检。最小修复：复用 `scan_sources` 的 glob 语义，并按 baseline `source_files` 覆盖删除。
5. `_support/workflow_finish.py:707-710`、`scripts/refresh_structure.py:607-609`：继承旧动态字段首个 owner/due 作为默认豁免，可沿用过期或错配豁免。最小修复：不默认继承，要求本次显式 owner/due，否则 UNVERIFIED。
6. `_support/semantic_contracts.py:228-249`：缺错误码、配置键、CLI、状态流转及 AC 观测生产者，P4 首批范围未齐；`_support/legacy_migration.py:426-439` 还会把参数化节点“一 PASS 一 SKIP”判为 verified。最小修复：接现有 adapter 或显式 UNVERIFIED 并收窄宣称；测试证据要求全部参数 case PASS。

## 验证与结论

- 533 项定向测试通过；全量当时未跑完。
- M245–M251 原/后哈希匹配冻结件，rc 0→1→0。
- 安装副本 52 个运行文件字节一致；smoke 只覆盖 off/未接入失败。
- 上轮 origin 标记、staged scope 含删除、receipt_mode fail-closed 已修；fresh/staged 仍未闭环。
- 代际回滚、Incident/Docs 主体边界及 install/atlas_check 接线已实现。
- 未完成真实域校准而保持 shadow 是诚实的，但不能宣称 enforce 或 fresh-checkout receipt 已交付。

**评审甲结论：不可交付；剩余阻断项 1–6。可保留为未发布 shadow 原型。**
