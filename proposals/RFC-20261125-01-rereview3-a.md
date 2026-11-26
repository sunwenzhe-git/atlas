# RFC-20261125-01 第三回评审甲意见

冻结输入：`10179fad227feb5262d889e967ab43b8ebc51577fa5364dac94f9fb89caeda7b`（92/92 匹配，评审前后零漂移）。只读，未跑 mutation。

## Critical

1. `_support/workflow_finish.py:680-683,832-843`：finish 不校验 review 来源却硬传 workflow。直跑 review 的同形 PASS 报告可 completed/receipt PASS。修复：verify 成功写绑定 unit/review hash/scope 的来源标记，finish enforce 校验，补直跑反例。

## Major

2. `_support/legacy_migration.py:461-486`：保留 -qq，动态 xfail 的 XPASS 汇总可 verified=true。修复：剥离 quiet/verbosity 后固定 -vv，识别 ANSI 清理后的 xpassed 汇总。
3. `_support/workflow_finish.py:719-735`：finish topology 重算读取工作树，暂存动态模板后工作树恢复 HEAD 仍 PASS。修复：finish 物化 staged 快照。
4. `_support/docs_governance.py:629-635,680-684`：任意已存在 commit 可作 --no-impact 证据。修复：commit 必须触及并验证相关 source/doc 路径，拒绝裸 hash。

## 结论

其余列明项通过。**不可交付；修复 Critical 1 与 Major 2–4。**
