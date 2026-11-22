# 第一个真实锚定判据窗留档（RFC-20261122-08 §5 验收，ANCHOR-W1）

> 实测时间：2026-11-22 · 执行环境：`/tmp/atlas-anchor-window`（verify_playground fixture 净场拷贝 + 独立 git 仓，BENCHMARK-20261119-02/03 同款）
> 流程：`atlas workflow plan → dispatch → 实现（注入真实违例）→ git add → verify（session 执行器 PENDING exit 2）→ fresh-context 子代理独立审查写 cli.json → 复跑 verify`——完整四阶段链，非夹具直跑。
> 子代理独立性：审查者 fresh-context，未被告知违例系注入；探索预算 13/14 工具调用，未改业务代码与暂存区。

## 六态计数（`anchoring-stats.json`，原件见同目录）

`executor=session-subagent`（判据窗 ✓）· `diff_mode=staged` · `grounding_ok=true`
**total=2：anchored 2 / mismatch 0 / unresolved 0 / unanchored 0 / unresolvable 0**

| finding | reported | resolved | state | 复算层 |
|---|---|---|---|---|
| critical：`site/index.html:4` 点击文案违例（**审查者独立抓到注入违例**，AC-HOME-001 对齐） | [4,4] | [4,4] | anchored | L1 staged diff |
| low：`.atlas/tasks/ANCHOR-W1/dispatch.md:30-34` 章节序号重复 | [30,34] | [31,34] | **anchored** | L2 全文回退 |

## 三个首窗观察

1. **R-2 相交谓词实战验证**：第 2 条 reported[30,34] vs resolved[31,34]——摘录为报告区间的**位移子集**，按 v1「行号一致」口径会误判 mismatch，四态相交口径正确判 anchored。复核 R-2 处方的价值在第一窗即兑现。
2. **判收链正确行为**：critical 违例 ⇒ `atlas review` FAIL（steps 7，validator 全 PASS 但 critical 存在）⇒ 域不收口——锚定测量面 WARN 出声（stderr）且判收链零变化，与 RFC 约束完全一致。
3. **样本量声明（诚实条款）**：单窗 2 条 anchored 只证明**机制工作**（复算/谓词/落盘/分轨全链真实轮走通），**不构成**「无漂移」证据——升档判据（≥2 窗 >10%）与摘除判据（≥3 窗全零）的窗口计数从本窗起算，继续积累。

## 验收判定

RFC §5 验收条款「≥1 个真实任务窗产出 anchoring-stats.json，六态计数经钉 1 形态核对」——**满足**。观察窗开启（本窗 = 窗 1）。
