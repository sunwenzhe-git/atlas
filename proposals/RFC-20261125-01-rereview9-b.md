# RFC-20261125-01 第九回评审乙意见

冻结：`211e6609d36d14c112456b2d47ca91688c949ab8c224b6e40f978b3a9d510509`，92/92 匹配，358 tests passed。未改树/提交/推送/mutation。

## Critical

1. `_support/workflow_finish.py:741-745`：_git_out 失败且 staged_files=None 时，动态 topology scope 无法判定仍降 WARN0；fresh fail-closed，裁决不一致。修复：暂存面读取失败抛 environment/rc2，仅成功且证明不在 scope 才降 WARN，共用 helper。

## Major

1. `_support/runtime_topology.py:427-440`：同代快速路径不验旧指针，篡改 business_digest 后 refresh PASS0 不修复，check FAIL1。修复：快速路径前 _verify_generation，损坏拒绝或重建指针。

## Minor

- `_support/docs_governance.py:699-713`：_evidence_digest 吞 PermissionError 改哈希证据字符串，二次读取失败仍可写 attestation。修复：OSError 抛 DocsIOError。
- `_support/incident.py:606-611,666-671`：异常分支再次 _selected_mode 读不可读 config，PermissionError 逸出。修复：异常分支用不重读配置的保守模式。

## 结论

其余复核通过。**阻断 Critical 1/Major 2，修复后重冻结。**
