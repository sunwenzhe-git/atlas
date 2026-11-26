# RFC-20261125-01 第五回评审甲意见

冻结：`bd05c567aa5833a0d1afb0c2118daf5aee982949b482cdd99913ec859deb7088`，92/92 匹配，定向 395 passed。只读，未跑 mutation。

## Critical

1. `_support/semantic_contracts.py:234-239,585-593,676-683`：历史 head 投影可形成 completion PASS，但当前 staged tree 实际不同。修复：完成态强制 staged tree 重投影，receipt 拒绝 head≠base。

## Major

1. `_support/workflow_receipt.py:335-338`：build 添加 origin 后 semantic 重投影变化。修复：排除 origin/receipt 运行件。
2. `_support/workflow_receipt.py:245-248,501-545`：代码哈希只覆盖 validator 脚本，重放丢 mode/Docs/Incident scope。修复：绑定运行时闭包，按 receipt mode/ID 重放。

## Minor

- `_support/classification_contract.py:143-147,192-208`：空 evidence 可 auto PASS。修复：top1 evidence 非空。

## 结论

第三轮 4 项关闭；第四轮多数关闭。**不可交付，修复后重冻结。**
