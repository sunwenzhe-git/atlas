# 跨轮闭环持久化 + 升级可见性 + scan 通道词表（D5-a/b/c）

> 提案编号：RFC-20261101-02
> 提案作者：@sunwenzhe-git
> 关联状态：已定案 (Accepted)（用户 2026-11-01 拍板「都按你建议的来」；批次 rfc-20261101-02-closure-durability。初稿曾编号 -01，与 main `a5dfd71` 撞号后改）
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
机械字段（指纹 + 轮次 + status + 签字人）611 字符、证据正文 2086 字符（占比随口径在 17%–29% 浮动，**不作为论据**）、`by` 逐条重复 13 次（证据不可自动机生成，指纹与轮次可以）。
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

- [x] `scripts/review_closure.py`：中间轮关闭证据 + 轮次单调 + 重置语义 + `--emit-skeleton`。
- [x] `scripts/cli_review_convert.py`：`--resolves` 输入、README 的升级/声明两行、无 coverage 点名。
- [x] `_support/review_policy.py`：`CLI_STATUSES` 加 `success`。
- [x] `tests/test_review_closure.py`：跨轮持久正例 + 重置反例 + 轮次倒挂反例 + 骨架输出（M6/M7/M8）。
- [x] `tests/test_cli_review_convert.py`：`--resolves` 两形态与坏形状、`success` 词表、无 coverage 点名、README 两行。
- [x] `shared/independent-review.md` §11、`shared/closeout.md` 步骤 10、`shared/gates.md` §4。
- [x] `DESIGN.md` D180；`CHANGELOG.md` / `docs/guide/changelog.md`；`docs/concepts/review.md`；
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

## 4.1 结果实录（2026-11-01 首版）

* **全量**：首版 `pytest tests/` ⇒ 998 passed / 5 skipped；经 §4.7 修订并 rebase 到 main `a5dfd71` 后 ⇒ **1002 passed / 5 skipped**（收集 1007；main 收集 987 ⇒ 本批 +20）。`test_install_selfcheck` PASS；`test_canonical_consistency` + `test_map_anchors` 17 passed。
* **用例增量**：`tests/test_review_closure.py` 19 → **28**；`tests/test_cli_review_convert.py` 41 → **48**；`tests/test_review_report.py` 39 → **40**。
* **十枚钉子四段协议**（首版七枚 + §4.7 新增 M9/M10/M46）（基线绿 → 注入红 → sha256 逐字节还原 → 复绿，日志 `/tmp/atlas-rfc01-evidence/mutation-proof.log`）：
  * **M6**（`closer = None`，等于只认最新轮）⇒ 3 红：`test_intermediate_resolves_persists_to_later_rounds`、`test_intermediate_rereported_closure_persists`、`test_stale_intermediate_declare_warns_but_not_loudly`。
  * **M7**（去掉 `best[0] <= last_open` 的轮次判据）⇒ 2 红：`test_reopen_after_intermediate_close_is_unaccounted`、`test_declare_earlier_than_obligation_does_not_count`（**不放水侧**）。
  * **M8**（骨架不写文件）⇒ `test_emit_skeleton_lists_unaccounted` 红。
  * **M42 / M43 / M44**（`--resolves` 不落键 / 无 coverage 不点名 / README 不渲染）⇒ 各自 2 / 1 / 1 红。
  * **M45**（`CLI_STATUSES` 摘 `success`）⇒ 转换器与形态门两侧同红（2 红）。
  * 七次注入全部还原逐字节一致，复跑 116 passed。
* **H3（真实语料，误红侧）**：四轮报告 `2026083101.462`（r1 12 Major + r2 1 + r3 3 = 16 义务）——
  * 修前（main `c1e2b3a` 版脚本）：`WARN rounds 4 prior 16 resolved 3 unaccounted 13`
  * 修后（本批）：`PASS rounds 4 prior 16 resolved 16 unaccounted 0`，`via` 分布 = `resolves@r3` ×13 + `resolves` ×3
  * `--emit-skeleton` 在义务已清时输出 0 条（不误造待填项）。
* **H4（真实语料，不放水侧）**：把 H3 那份四轮报告复制成 `/tmp/atlas-rfc01-h4`，仅**删掉 r3 里 `aff7ef9e83b103e4` 这一条关闭声明** ⇒ `WARN rounds 4 prior 16 resolved 15 unaccounted 1`（持久化不是「只要历史上出现过声明就永远算关」，也不是把义务集缩小）。
* **H4b（重置侧，夹具）**：`test_reopen_after_intermediate_close_is_unaccounted` —— 中间轮关过、更晚一轮同指纹又 open ⇒ 回到 `unaccounted`；`test_declare_earlier_than_obligation_does_not_count` —— 声明轮次早于义务出现轮 ⇒ 不作数。
* **留出独立性（D156 三条）**：①判据输出翻转（`unaccounted 13 → 0`、`resolved 3 → 16`、`via` 新增形态）；②变异增量杀伤（M6/M7 注入后既有 19 条钉全绿而新钉红）；③结构不可达（既有夹具最多两轮，无「中间轮声明 + 最新轮未提」形态；H3 用真实四轮语料）。⇒ 三态结论 = **闭族**。

### 4.7 只读评审与修订（2026-11-01；主审逐条独立复现后才动手）

只读评审打出 **1 条阻塞 + 4 条非阻塞**，六条我全部复现成立；按「非阻塞也全修再提交」处理。

| 编号 | 判据（评审原话压缩） | 我的独立复现 | 修法 | 钉 |
|---|---|---|---|---|
| **B1 阻塞** | `state_of` 用 `obligation_level` **覆盖**本轮级别 ⇒ 只挡 `Critical→Major` 降级，反向 `Major→Critical` 升级后可被**无签字无取证**的 `intentional` 判成 `re-reported-closed@r2` 且整体 `PASS`；同一夹具 main 是 `WARN unaccounted 1` ⇒ 本批把响亮降成静默；docstring 却自称「按最严的级别判」 | `python3 scripts/review_closure.py --dir /tmp/atlas-b1-verify/report` ⇒ 分支 `PASS resolved 1`、main `WARN unaccounted 1` | 新增 `review_policy.worst_level(left,right)`；`state_of` 取较严档；义务 `level` 在重复指纹处按最严加宽 ⇒ 同一夹具改判 `WARN unaccounted 1`，而真实四轮仍 `PASS 16/16` | **M9**；配正例 `test_escalation_widening_keeps_legitimate_closure`（带取证的升级关闭仍算关，不刷红） |
| S1 | 中间轮 `resolves` 坏形状 ⇒ `exit 2`；`(unit, round)` 文件按契约不得覆盖 ⇒ 历史里一个写歪的 `status` 把闭环永久钉死 | 构造 r2 `status:"done"`：分支 rc=2，main 同夹具仍可跑出 WARN | 中间轮 ⇒「该条不作关闭证据 + warnings + 抬 WARN」；最新轮仍 `exit 2` | **M10** ⇒ 3 条红 |
| S2 | `M>N` 不判：无 coverage 时自评 `files_reviewed=999` 配 `--expected-files 2` 仍 `PASS` | 自家夹具即中招（`test_other_category_not_gated` 自评 2 / 应审 1 却判 PASS） | `review_policy.count_floor(reviewed, expected)` ⇒ `M≠N` 一律抬下限，转换器与形态门同口径；先核全仓现存报告 `M>N` = 0（不回扫不误伤） | **M46** ⇒ `test_reviewed_exceeds_expected_warns` 红 |
| S3 | 单源化后指纹带首尾空白被归一，声明由 main 的 `unknown + WARN` 变成 `resolved + PASS` | 评审夹具 `f12_space_fp` | 带首尾空白 = 形状错，显式失败（不猜、不归一后放行） | 并入 `resolves_shape_errors` 判据面 |
| S4 | 措辞与顺序：stale 提示的「N 条」实为去重指纹数；README `round ≥ {args.round}` 在 `--round 5` 会印 5；`skeleton()` 调两次；`--resolves` 形状门早于「同轮不得覆盖」，坏声明盖住重复轮次报错 | 逐条读码确认 | 改「N 个指纹」；提 `ROUND_CAP=4` 常量并标本轮 round；单次计算；同轮检查前置 | 由既有钉与新增用例覆盖 |

**编号撞车（评审同时发现）**：本提案初稿占用 `RFC-20261101-01`，而 main 的 `a5dfd71`（非门约束登记）已用同号 ⇒ 本批改号 **RFC-20261101-02**，引用面（DESIGN D180 / `shared/gates.md` 两行与 §4 条 / 两处 changelog / concepts / iron-gates / 契约 §11 / 三个测试文件注释）逐处辨主后改，main 自有引用 3 处未被误改（已核对 `main:shared/gates.md` 第 53/54 行原本不含该编号）。

**M45 编号归属**：摘 `CLI_STATUSES` 中 `success` 这一变异只记在 `tests/test_cli_review_convert.py` 名下，但它同时使 `tests/test_review_report.py` 红一条；门册两行已写明「编号属 `test_cli_review_convert.py`」，避免引用面歧义。

**对 §4.1 首版自述的两处更正（诚实优先）**：

1. 首版写「七次注入全部还原逐字节一致」——首跑日志里 **M43 因锚点命中 2 次而未能注入**（同批日志含 `无效钉子/异常计数 = 1`），换唯一锚点重试后才成立。逐文件 sha256 复核现已在协议输出里逐条打印（`还原 sha256 一致`），但首版把「一次重试后成功」写成「七次全绿」不准确。
2. 「机械字段占 23%」随口径不同落在 17%–29%，属软陈述；`--resolves` 的必要性改由可核数支撑（13 条 / 93 行 / 4849 字节 + `by` 逐条重复 + 实测指纹写错会落 `unknown_resolves`）。

### 4.5 留出验证（D156）

* 触发判据级变化：`resolved` 的成立条件从「仅最新轮」扩到「最后一条证据」⇒ 需要既有红/绿两侧留出。
* H3（误红侧）：真实四轮报告——修前 `WARN unaccounted 13`，修后应 `PASS unaccounted 0`。
* H4（不得放水侧）：同一份 r4 报告，把 r3 的某条声明换成**更晚轮又 open** 的形态 ⇒ 应回到 `unaccounted`。
  两者都不是既有夹具只改路径可得（既有夹具最多两轮）。

### 4.8 第二轮只读评审与再修订（2026-11-01）

复审专打第一轮的修复本身，打出 **1 条阻塞 + 6 项风险**，逐条复现成立后全修（含上一轮我自己声明但未兑现的一项）。

| 编号 | 判据 | 我的复现 | 修法 | 钉 |
|---|---|---|---|---|
| **B1 残留（阻塞）** | 级别加宽挂在 `relevant()` **之后** ⇒ 升级那一轮只要标 `pre_existing=true` 就跳过加宽，义务仍按陈旧 `Major` 判；两条关闭路径（声明侧 `declares_close`、重报侧 `resolved_by_fp`）都按它放行 | `/tmp/b1-e2`（r1 `Major` → r2 同指纹 `Critical`+`pre_existing` → r3 无签字 `intentional` 声明）：修前 `PASS resolved 1`，修后 `WARN unaccounted 1 invalid 1`；改成「最新轮降级重报」形态则修前 `PASS resolved`、修后 `carried` + 矛盾告警 | 加宽改读 `events[fp]` 的**全部 check 出现**（含被标 `pre_existing`、已关闭的条目），移出 `relevant()` 分支 | **M11**（声明侧 + 重报侧两条用例） |
| R1 | 历史里 `level` 是 `list`/`dict` ⇒ `ranks.get()` 抛 `TypeError`、**裸 traceback rc=1**（本族脚本退出码只有 0 与 2），`closure.json` 不落盘 | 评审夹具 `e3`（r2 `level: ["Critical"]`）⇒ 修前 rc=1 | `worst_level` 只认字符串档位，不可哈希的一侧不参与加严 | **M12** |
| R2 | `M>N` 只由状态映射抬下限，但形态门的对账行仍按 `rev < exp` 出文案 ⇒ 报告 `WARN` 而行显示 `[PASS]`、README 只标「少审」 | 构造 `expected=3 / reviewed=4`：修前该行 `[PASS]` | 门侧补「多报 `M>N`」分支；README 同步 `nm_note` 三态（少审 / 多报 / 齐） | **M47** |
| R3 | 文案未随 `count_floor` 同步：契约 §3 的字段条、门册形态门行、两个脚本的 docstring 仍写单边 `reviewed < expected`；契约的 `cli_status` 词表也漏了 `success` | 逐处 grep | 全部改为 `M≠N`（并注明两侧含义）；词表补 `success` 并标其为 `ocr scan` 完成态 | 由 `test_canonical_consistency` 与新增用例覆盖 |
| R4 | 上一轮我声明「`skeleton()` 单次计算」但没做 | `grep` 到两处调用 | 改为算一次并复用 | **M8** 既有钉覆盖 |
| R5 | `ROUND_CAP` 没单源：内核 `validate_v2_report_fields` 仍硬编码 `r >= 4`，转换器另定义一个 | 读码 | 内核定义 `ROUND_CAP = 4`，转换器 `ROUND_CAP = review_policy.ROUND_CAP`，报错文案与 README 都用它 | **M44**/既有钉覆盖 |
| R6 | 同一指纹在最新轮同时出现 open 与带签字 `fixed` ⇒ `any(closed)` 判 `resolved`；而中间轮同形态被 `best <= last_open` 拒 ⇒ 口径不一致，且形态门的指纹去重排除了 `fixed` 条目、不会报重复 | 评审夹具 `E7` | 最新轮改为「有 open 即未关闭」：混排 ⇒ `carried` + 矛盾告警 + **抬 WARN**（与 `downgraded`/孤儿同档） | **M13** |
| R7 | 改号只落文件面：分支名与 RFC 头部「批次 rfc-20261101-01…」仍带 `-01` | `git branch --show-current` | 分支改名 `rfc-20261101-02-closure-durability`，RFC 头部标注入稿曾撞号 | — |

**第二轮后的实况数**：`tests/test_review_closure.py` **34** 条（M1–M13）、`tests/test_cli_review_convert.py` **49** 条（M42–M46，M45 编号属该文件）、`tests/test_review_report.py` **41** 条（M35/M36/M40/M41/M47）；全量 **1007 passed / 5 skipped**（收集 1012；main 987 ⇒ +25）；`wc -l` = `review_closure.py` 389、`cli_review_convert.py` 366、`_support/review_policy.py` 343、`validate_review_report.py` 221、`shared/gates.md` 170；`test_canonical_consistency` + `test_map_anchors` 17 passed；安装自检 PASS。

**七枚钉子第二轮四段协议**（M9/M10/M11/M12/M13/M46/M47）：基线 124 passed → 逐条注入各红 1–3 条（红目与预期完全对得上，无「注入无人红」的哑钉）→ 每次 `sha256 逐字节一致` 还原 → 复绿 124 passed。日志 `/tmp/atlas-rfc01-evidence/mutation-proof-round2.log`。

**真实四轮语料未被后续修复带坏**：`PASS rounds 4 prior 16 carried 0 resolved 16 unaccounted 0`（`via` = 13× `resolves@r3` + 3× `resolves`）；删一条中间声明仍回 `unaccounted 1`。全仓 `reviewed > expected` 的存量报告 = **0**（`count_floor` 收紧不回扫打红），语料 5 份报告 validator 全 `rc=0`。

**本轮教训（写进流程）**：第一轮我修的是「降级」方向并自称两个方向都挡住——实际加宽挂在 `relevant()` 之后，`pre_existing` 一标就整条跳过。**「对称方向都覆盖」这种话必须配一条反向夹具**，否则就是自我表扬。M11 就是那条反向夹具。

## 5. 开放问题

1. 义务去重目前按「最早出现轮次」锚定（`k` = 第一次未关闭出现的轮）。隔轮重复出现是否该以最近一次为准，
   等真实数据出现歧义再定。
2. `via` 字符串会被 `closure.json` 消费方读到；新增 `…@rN` 形态是否需要结构化字段（`declared_in_round`），
   等真有消费方再定。
3. 第 5 轮（超出上限的复验）如何登记，本批只保证 `--round 5` 仍走「必须登记升级」。
4. scan 通道的 M 无权威：若将来 OCR 给 scan 也产 coverage，转换器无需改动（`cov["present"]` 自动走权威侧）。
