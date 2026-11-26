# RFC-20261125-01 第二回评审甲意见

起始冻结：`9ecf7a2002f068e8b088188e8560666ba927133e826a85661c663096fa1449a5`，92/92 匹配。收尾因修复期间 9 文件漂移发现聚合 `6a54a746…`；本意见仅针对起始快照。reviewer 只读，未跑 mutation。

## Critical

无。

## Major

1. `_support/workflow_receipt.py:167-174` 仅校验分类 input_digest 形状，可跨任务复用。修复：任务卡保存 classification_input_digest，finish/receipt 强等。
2. `_support/workflow_finish.py:739-746` 在 cause 为空时回退 stale；ATLAS_INCIDENT_MODE=off + resolves_incidents 得到 incident_not_resolved/rc1/charged。修复：UNVERIFIED 按模块映射 `*_unverified`，rc2 不扣。
3. `scripts/atlas_workflow.py:351-356` 只比较工作树扫描集与 baseline；stage compose.extra.yaml 后删工作树文件，precheck=False。修复：直接按 scan_globs 匹配 staged 路径。
4. `_support/legacy_migration.py:382-402,472-475` 只识别函数装饰器，XPASS 正则受 -qq/ANSI 影响；模块/类级 xfail 可 verified=True。修复：收集模块/类 marker、去 ANSI、禁 XPASS。
5. `_support/semantic_contracts.py:335-337,388-392` 将 file.py::test_x 截成文件路径，节点不存在仍假 PASS。修复：节点级事实或无节点 adapter 显式 UNVERIFIED。
6. `_support/governance_io.py:163-184` rollback 只验 previous_pointer.files 中列出的文件；删一个键仍可切到缺件代际。修复：验完整文件集合与 canonical digest。

## 结论

其余列明项未发现阻断。**不可交付；修复后重新冻结再评。**
