# 跨轮闭环持久化 + 升级可见性 + scan 通道词表（D5-a/b/c）

> 提案编号：RFC-20261101-01
> 提案作者：@sunwenzhe-git
> 关联状态：已定案 (Accepted)（用户 2026-11-01 拍板「都按你建议的来」；批次 rfc-20261101-01-closure-durability）
> 影响范围：脚本工具 (scripts) | 契约 (shared/independent-review.md) | 门册观测面 (shared/gates.md)
> 关联取证：2026-10-31→11-01 真实实例⑤四轮运行（`2026083101.462`，nanwang 克隆）
> 　`/tmp/atlas-impl-review-20261031-204905/nanwang/product/reviews/2026-10-31-impl-review-dashboard-topn/EVIDENCE-r1-r4.md`

---

## 1. 现象与取证（三条缺陷全部来自真实运行，不是设想）

### D5-a　`resolves` 不跨轮持久 ⇒ 每轮被迫重贴整本历史

`review_closure.py` 的义务集覆盖**所有** prior 轮（`round < latest`）里未关闭的 Critical/Major，
但「已关闭」的证据只看**最新轮**：最新轮同指纹重报并闭合，或最新轮 `review.json.resolves` 声明。
于是上一轮正式关闭的项，到再下一轮又变回「没交代」。真实四轮实录：

```text
# r3 落账（义务 = r1 的 12 Major + r2 的 1 Major = 13，逐条 resolves 带 by+evidence）
review_closure …  PASS  rounds 3 prior 13 carried 0 resolved 13 unaccounted 0

# r4 落账（本轮只该交代 r3 的 3 条 Major，并已如实声明）
review_closure …  WARN  rounds 4 prior 16 carried 0 resolved  3 unaccounted 13   ← 误红
```

**危害**：要避免误红，操作者必须把 r1..rN 所有历史关闭在每一轮重新贴一遍。这与契约 §4
「同一问题跨轮不得重复贴」直接冲突，也与 D5 立项动机（治静默丢账，而不是制造重复劳动）相反。
三轮时不暴露，四轮才撞出来。

### D5-b　`escalation` 在人读留痕上不可见

4 轮收敛上限（D129）触发时，转换器**强制**要求 `--escalate-to`/`--escalate-reason`，
但只写进 `review.json`；`README.md` 里 0 次出现（实测 `grep -c` = 0）。
升级复议是「交给谁、为什么交」的纪律事件，恰恰是人要看的那一面。

### D5-c　scan 通道的状态词表与权威面缺口

`ocr scan`（整文件补审通道）顶层 `status` 是 `"success"`，不在 `review_policy.CLI_STATUSES` 的
六个取值里 ⇒ 转换器按 `unknown` 记录并落一条 `cli_warnings`（实录：
`"<cli> [status] 未知 CLI status='success'，按 unknown 记录"`）。
行为是安全的（不猜、只记），但报告上看不出「这是一次完整成功的扫描」。
另外 scan **不产出** `manifest.coverage` ⇒ 实审数 M 只能回退自评 `summary.files_reviewed`，
正是 Batch A 在 review 通道上消灭的信任面，而现在报告里没有任何一行点名它。

### 附带诉求（同批，成本低）

真实手写 13 条 `resolves` 的体量：93 行 / 4849 字节，机械字段（指纹 + 轮次 + status + 签字人）
占输入字符 **23%**、`by` 逐条重复 13 次，证据正文占 77%（证据不可自动机生成，指纹可以）。
⇒ 需要 `--resolves` 输入 + 义务骨架输出。

## 2. 决策与权衡

### 2.1 D5-a 修法：闭合以「该指纹的最后一条证据」为准

义务项 `fp`（最早在未关闭状态出现的轮次记为 `k`）判 `resolved`，当且仅当
**所有证据里最后一条是「关闭」**，否则 `carried`（最新轮仍 open）或 `unaccounted`：

| 证据 | 所在轮 | `via` 记法 |
|---|---|---|
| 最新轮同指纹重报且已带签字取证关闭 | latest | `re-reported`（保持既有字串） |
| 最新轮 `review.json.resolves` 声明关闭 | latest | `resolves`（保持既有字串） |
| **中间轮**的 `resolves` 声明关闭 | `k < r < latest` | `resolves@rN`（新增） |
| **中间轮**同指纹重报并带取证关闭 | `k < r < latest` | `re-reported-closed@rN`（新增） |
| 同指纹在更晚轮又出现为 open | 任意 prior 轮 | **重置为未关闭**（不认更早的关闭） |

规则要点（与既有语义完全一致，只是把「同一套判据」应用到中间轮）：

* `fixed`/`false_positive` 必须带 `by`+`evidence` 才算关闭；
* `intentional`/`ignored` 不得关闭 Critical——按**义务项所在轮的级别**判（沿用 `43dca7f` 的 R1 修法）；
* 关闭声明的轮次必须 **晚于**义务出现轮次（`r > k`），历史不能倒着关；
* 中间轮 `resolves` 的**形状**错误（非数组 / 非对象 / 空指纹 / status 越界 / 重复指纹）⇒ **exit 2**，
  与最新轮同源；缺取证不算形状错，只是「不算关闭」。
* 中间轮里匹配不到任何义务的声明 ⇒ 进 `warnings`（可见，不额外抬状态）。

### 2.2 D5-b 修法：README 渲染升级与跨轮声明

`cli_review_convert.py` 的 README 总结段加两行（有则渲染，无则不出现）：

* 升级复议：`- **升级复议（round ≥ 4 收敛上限）**：→ \`<to>\`：<reason>`；
* 跨轮声明：`- 跨轮关闭声明：N 条（`resolves`，由 `review_closure.py` 对账，非门）`。

### 2.3 D5-c 修法：词表加 `success`，无 coverage 点名

* `CLI_STATUSES` 加 `"success"`（scan 通道的完成态）⇒ 忠实记录，不再假 `unknown`；
  **不**因此改变 `cli_warn_floor`（只有 `partial|failed` 抬下限）。
* `convert()` 在 `manifest.coverage` 缺失时追加一条 `cli_warnings`：
  `无 coverage ⇒ 实审数取 CLI 自评 summary.files_reviewed（无权威，M 可被高估）`。
  只点名，不改状态（`cli_warnings` 不参与 `warn_floor`），存量通道行为不变。

### 2.4 `--resolves` 输入 + 义务骨架

* `--resolves <file>`：接受 `[...]` 或 `{"by": "<缺省签字人>", "resolves": [...]}`；
  条目缺 `by` 时继承顶层缺省；形状错误 ⇒ 显式失败（与 `--from/--to`、`--head-sha` 同类的输入门）。
* `review_closure.py --emit-skeleton <file>`：把当轮 `unaccounted` 义务打成待填骨架
  （`fingerprint` / `prior_round` / `level` / `target` 预填，`status`/`by`/`evidence` 留空）。
  纯输出，不参与判定，不改状态。

### 2.5 被否方案

* **每轮要求重贴全部历史**（当前行为的"文档化"）：与契约 §4 冲突，且实测 13 条 × 每轮的成本不可持续。
* **`closure.json` 增量累积历史**（把上一轮 closure 的结果读回当基线）：新增一层产物依赖，
  closure 被删/被改就跑错；轮次历史已在 `findings/<unit>.rN.json` 里，不必另立真相源。
* **只把义务集限制为"上一轮"**（不做全历史）：会漏掉隔轮丢失（r1 报、r2/r3 都没提、r4 消失），
  而那正是 D5 要治的形态。
* **把中间轮的 `unknown` 声明也 WARN**：历史声明里的冗余项不改变判据结论，只进 `warnings`；
  判据级新面一律 WARN 起步的规则不适用于纯噪声面。
* **给 scan 通道补 coverage**：外部 CLI 不由我们决定，只能按它给的事实记录 + 点名自评面。

## 3. 改动面

- [ ] `scripts/review_closure.py`：中间轮关闭证据 + 轮次单调 + 重置语义 + `--emit-skeleton`。
- [ ] `scripts/cli_review_convert.py`：`--resolves` 输入、README 的升级/声明两行、无 coverage 点名。
- [ ] `_support/review_policy.py`：`CLI_STATUSES` 加 `success`。
- [ ] `tests/test_review_closure.py`：跨轮持久正例 + 重置反例 + 轮次倒挂反例 + 骨架输出（M6/M7/M8）。
- [ ] `tests/test_cli_review_convert.py`：`--resolves` 两形态与坏形状、`success` 词表、无 coverage 点名、README 两行。
- [ ] `shared/independent-review.md` §11、`shared/closeout.md` 步骤 10、`shared/gates.md` §4。
- [ ] `DESIGN.md` D180；`CHANGELOG.md` / `docs/guide/changelog.md`；`docs/concepts/review.md`；
      `docs/gates/iron-gates.md`；`docs/map/*`（行数与门册快照）。

## 4. 验证

```bash
pytest tests/test_review_closure.py tests/test_cli_review_convert.py tests/test_review_report.py
pytest tests/                                   # 全量出厂
python3 tests/test_install_selfcheck.py
# 真实四轮语料复跑：r4 应 PASS 16 条（13 via resolves@r3 + 3 via resolves）
python3 scripts/review_closure.py --dir <四轮报告目录>
python3 scripts/review_closure.py --dir <四轮报告目录> --emit-skeleton /tmp/skeleton.json
```

变异钉子（编号属各自测试文件）：M6 摘掉中间轮证据 ⇒ 跨轮持久用例红；
M7 去掉轮次单调/重置校验 ⇒ 重置与倒挂用例红；M8 骨架输出不写文件 ⇒ 骨架用例红；
`--resolves` / 词表 / README 渲染各自的钉子见 §4 实录。

### 4.5 留出验证（D156）

* 触发判据级变化：`resolved` 的成立条件从「仅最新轮」扩到「最后一条证据」⇒ 需要既有红/绿两侧留出。
* H3（误红侧）：真实四轮报告——修前 `WARN unaccounted 13`，修后应 `PASS unaccounted 0`。
* H4（不得放水侧）：同一份 r4 报告，把 r3 的某条声明换成**更晚轮又 open** 的形态 ⇒ 应回到 `unaccounted`。
  两者都不是既有夹具只改路径可得（既有夹具最多两轮）。

## 5. 开放问题

1. 义务去重目前按「最早出现轮次」锚定（`k` = 第一次未关闭出现的轮）。隔轮重复出现是否该以最近一次为准，
   等真实数据出现歧义再定。
2. `via` 字符串会被 `closure.json` 消费方读到；新增 `…@rN` 形态是否需要结构化字段（`declared_in_round`），
   等真有消费方再定。
3. 第 5 轮（超出上限的复验）如何登记，本批只保证 `--round 5` 仍走「必须登记升级」。
4. scan 通道的 M 无权威：若将来 OCR 给 scan 也产 coverage，转换器无需改动（`cov["present"]` 自动走权威侧）。
