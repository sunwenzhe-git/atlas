# 实例⑤审查报告：coverage 为实审权威 + delta v3 字段（Batch A/B）

> 提案编号：RFC-20261031-01
> 提案作者：@sunwenzhe-git
> 关联状态：已合并 (Merged)（Batch A/B）
> 影响范围：脚本工具 (scripts) | 校验器 (_support / scripts) | 契约 (shared/independent-review.md)
> 关联取证：2026-10-31 实例⑤真实仓副本 r1/r2 + 最小夹具（见 §1.2 / §4.5 / 附录 A）
> 实施批次：Batch A（coverage 假绿 + partial 可见）/ Batch B（delta v3 字段）；两批可独立合并，Batch B 不阻塞 A

---

## 0. 范围与批次

| 批次 | 内容 | 目的 | 是否动 `schema_version` |
|---|---|---|---|
| **A** | D1 coverage 权威 + D3 `cli_status`/`failed_files` 可见 | 修「summary 报 6、实际审 4」的假绿 | 否（v2 增量可选字段） |
| **B** | D2 `head_sha` + D4 `reviewed_files` 成员/数量/`selected` 对账 | 修 delta 报告不完整与 clean 轮误红 | 是（新 delta 报告用 v3） |
| 另案 | D5 跨轮 `resolves` 台账 | 修「r1 未关闭 finding 无跨轮交代」 | 另案 RFC |

本 RFC 先落 Batch A；Batch B 在 A 合入后按同一契约继续，避免 schema 决策拖住假绿修复。

---

## 1. 现象与取证 (The Problem & Evidence)

### 1.1 触发形态（抽象）

* **规则 / 环节**：实例⑤「实现代码独立审查」的 `scripts/cli_review_convert.py`（CLI JSON → `review.json`）、`scripts/validate_review_report.py`、`_support/review_policy.py`。
* **触发时机**：真实产品 diff 的 r1 全量审查、r2 差量审查；以及 coverage / clean-delta 两个最小夹具。
* **具体行为**：
  1. **实审数假绿（Batch A）**：CLI JSON 已有 `status=partial`、`manifest.coverage.completed=4`、`failed=2`，但 `summary.files_reviewed=6`；转换器只读 `summary`，报告写 `reviewed=6`、`6/6`。r1 因 findings 整体是 WARN，但 **N/M 行是假绿**；若该轮 0 finding，报告会是 `PASS 6/6`（附录 A 夹具复现）。
  2. **delta 字段缺失（Batch B）**：r2 报告 `delta_only=true`，但 `review.json` 无 `head_sha`；`reviewed_files` 只收「有 finding 的文件」1 个，实际审了 3 个。
  3. **clean delta 误红（Batch B）**：0 finding 的 delta 轮，`reviewed_files=[]`，`validate_review_report` FAIL。
  4. **CLI 失败面不可见（Batch A）**：`status=partial`、`failed_files`、CLI warnings 均未进入 `review.json`，报告形态门仍可 PASS。

### 1.2 客观证据 (Minimal Evidence)

**E1（真实 r1，N/M 假绿）**

```text
CLI: status=partial
     manifest.coverage.completed = 4 files
     manifest.coverage.failed    = 2 files
     summary.files_reviewed      = 6
convert: "应审 6 / 实审 6"
review.json: expected=6, reviewed=6
```

两个实际未完成的文件没有被任何 Atlas 报告行点名。

**E2（真实 r2，delta 字段不完整）**

```text
review.json:
  delta_only = true
  base_sha   = <present>
  head_sha   = <absent>
  expected   = 3
  reviewed   = 3
  reviewed_files = ["src/a.ts"]      # 实际审了 3 个，只有 1 个有 finding
```

**E3（clean delta，误红）**

```text
CLI: status=complete, files_reviewed=3, comments=[]
convert: PASS 3/3, reviewed_files=[]
validate_review_report: FAIL —— `delta_only=true` 时必须提供非空 `reviewed_files` 列表
```

**E4（coverage 夹具，假绿可复现）**

```text
CLI: status=partial
     selected=6, completed=4, failed=2, summary.files_reviewed=6, comments=[]
convert: PASS 6/6
validate_review_report: PASS
```

E4 与 E1 同根：**报告把 CLI 自报的 `summary` 当成实审数，而不读取 CLI 自己给出的 coverage。**

### 1.3 影响

* 违反「缺权威输入不得给通过」（`shared/independent-review.md` §2.6）：CLI 已声明 2 个文件失败，报告仍以 6/6 放行。
* 违反 N/M 对账目的：N/M 本来抓「静默少审」，summary 与 coverage 冲突时反而把少审洗白。
* delta 轮无法证明「修没修、审了哪些文件」；clean 轮还会被误红。
* 工具失败（`partial`）不可见，报告级结论无法区分「审完 0 问题」与「没审成」。

---

## 2. 决策与权衡 (The Decision & Trade-offs)

### 2.1 核心定案 (The Decision)

#### Batch A：coverage 权威 + CLI 失败面可见

**D1：coverage 是实审事实的唯一权威；覆盖所有轮次（含非 delta）；summary 只是自报。**

* 当 CLI JSON 存在 `manifest.coverage` 时：
  * `reviewed` = `completed[].path` 去重后的数量；**暂只算 completed**；
  * `reviewed_files` = completed 的排序路径列表（Batch B 才把它写入 delta 报告）；
  * `failed_files` = `failed[].path` 的排序列表；
  * `waived_files` / `reused_files` 分别记录，**不计入 reviewed**（`reused` 语义未确认，见 §5）；
  * `summary.files_reviewed` 与 coverage 不一致时，以 coverage 为准，并把差异写入 `cli_warnings` / README。
* 无 coverage 的旧 CLI：继续用 `summary.files_reviewed`；delta 轮必须显式 `--reviewed-files`，否则拒绝产出（Batch B）。
* **绝不**再用 `checks[].target` 反推 `reviewed_files`。
* **必须同步**：`shared/independent-review.md` §10.2 的 M 定义、`docs/concepts/review.md` §3、`docs/gates/iron-gates.md` §8、`shared/gates.md` 实例⑤/报告门行的 M 口径——否则契约与代码互斥。

**D3：CLI 失败面必须可见，分级按优先级表。**

| 条件 | 结果 |
|---|---|
| 无任何 completed（且无 comments / findings） | converter exit 2：没有发生审查，不得产出可放行报告 |
| 任一阻断性 Critical | **FAIL**（WARN 下限不得把 Critical 降级） |
| `status=partial` / `failed`，或 `failed_files` 非空，且有产出 | 状态下限 **WARN**（工具失败 ≠ 代码 finding） |
| `status=skipped` / `unknown` | 只记录，不额外抬 WARN；`expected>0` 时由现有 `reviewed<expected` 自然 WARN；合法 SKIP 由收口层处理 |
| 其余 | 按现有状态映射 |

* `review.json` 新增可选字段：`cli_status`（`complete` / `completed` / `partial` / `failed` / `skipped` / `unknown`）、`failed_files`、`waived_files`、`cli_warnings`。
* 校验器复算状态时同样应用该 WARN 下限；`cli_status` 取值进闭集校验；单源 helper 放在 `_support/review_policy.py`，防转换器/校验器两端漂移。

#### Batch B：delta 报告 v3 字段

**D2：delta 必须有 `head_sha`；新 delta 报告升 `schema_version=3`。**

* 转换器新增 `--head-sha`；**不再用 `--to` 兼取 head**——现有 `--from/--to` 同用会把 N 改成 `git diff` 全量数（`scripts/cli_review_convert.py:129-135`），与「N = preview Will review」冲突。
* `--delta-only` 时：
  * 缺 `--head-sha` ⇒ exit 2，明确报「delta 报告缺 head_sha」；
  * 使用 `--head-sha` 写 `head_sha`；`base_sha` 继续用 `--base-sha`；
  * `reviewed_files` 由 coverage completed（或显式 `--reviewed-files`）写入，不再由 findings 反推；
  * `--reviewed-files` = 逗号分隔路径列表；去重、排序、统一 `/`；与 coverage 冲突时以显式参数为准并 WARN；
  * 新报告 `schema_version=3`；v2 报告维持旧语义，**不回扫**；v2 delta 缺 `head_sha` 只 WARN，不 FAIL。
* 校验器：`schema_version=3` 且 `delta_only=true` 时，`head_sha` 非空、`reviewed_files` 非空、数量与 `reviewed` 一致；v2 不新增硬 FAIL。

**D4：`reviewed_files` 的成员与数量对账（先 WARN）。**

* `delta_only=true` 时：
  * `reviewed_files` 去重排序；`failed_files` 去重排序；两者不相交；
  * `len(reviewed_files) != reviewed` ⇒ WARN；
  * 每个 `checks[]` / `other[]` 的 target 文件必须 ∈ `reviewed_files`；若 ∈ `failed_files` ⇒ WARN「finding 落在失败文件」；两者都不在 ⇒ WARN「finding 超出 coverage」；target 为 `?` / 空路径时跳过成员对账（无法归属）；
  * coverage `selected` 存在时：`len(selected) != expected` ⇒ WARN；`selected` 应能被 `completed ∪ reused ∪ failed ∪ waived` 解释；解释不了 ⇒ WARN（Batch B 首版不 exit 2，留证据再升）。
* 空 `reviewed_files` 维持现有 FAIL。

**D5：跨轮闭环另案，不在本批。**

* 「上一轮 open Critical/Major 必须在下一轮有交代」需要独立 `resolves` 台账；现有契约明确「同一问题跨轮不得重复贴」（`docs/gates/iron-gates.md` §8），不能靠强制同指纹重报。
* 另开 RFC，先 WARN、后议升档；本批只修报告事实链。

**D6：不新增 `atlas_check` 硬门。**

* 只改实例⑤的转换器 / 报告形态门 / 契约字段；不装依赖、不改检查编排、不新增 profile 开关。

### 2.2 考虑过的备选方案及否定理由 (Considered Alternatives)

* **A. 继续信任 `summary.files_reviewed`**：E1/E4 已证明会假绿；否定。
* **B. 用 `git diff --name-only` 当 M/N**：会包含 CLI 明确排除的测试文件；实例⑤契约要求 N 取 `--preview` 的 Will review 数；否定。
* **C. 用 findings 反推 `reviewed_files`**：r2 实测 1/3，clean 轮为空；否定。
* **D. 对 `partial` 直接 FAIL**：工具失败不是代码 finding；且会让可用的 4 个文件结论被整体作废；先 WARN 可见，否定 FAIL。
* **E. 对 `reviewed_files` 数量不一致直接 FAIL**：与 `M<N` 同族，首版过严；先 WARN，留升级证据。
* **F. 本批直接 bump 所有报告到 `schema_version=3`**：非 delta 报告没有 head_sha 需求，先只让新 delta 报告 v3；v2 历史报告保持兼容。
* **G. 把跨轮闭环塞进 `validate_review_report`**：与「跨轮不得重复贴」冲突，且需要独立台账；否定。
* **H. 只支持 OCR 的 manifest 字段**：其他 CLI 无 coverage；保留 `--reviewed-files` 显式通道，否定单一实现。
* **I. 用 `--to` 兼取 head_sha**：会改 N，且缺 `--from` 直接报错（`scripts/cli_review_convert.py:129-135`）；否定。

### 2.3 必须警惕的刺痛代价与兼容性影响 (Trade-offs)

* **所有轮次的 `reviewed` 可能变小**：coverage 存在时以 completed 为准；E1 类 partial 轮会从 6/6 变 4/6 WARN。这是把假绿改成真话，不是回归。**非 delta 报告不再「仍按 summary」——D1 覆盖所有轮次；兼容的是无 coverage 的旧 CLI。**
* **v2/v3 兼容**：新 delta 报告 v3；v2 历史报告保持旧语义，validator 不因缺 `head_sha` 回扫旧报告。新 v3 报告缺 `head_sha` ⇒ FAIL；v2 delta 缺 `head_sha` ⇒ WARN。
* **OCR 版本差异**：`manifest.coverage` 是 OCR v1.13.3 的字段；旧版本无 coverage ⇒ 走 fallback。若字段语义变化（`reused`），按 §5 处理。
* **调用面**：delta 调用必须补 `--head-sha`；`shared/closeout.md` 步骤 10 同步；不再允许用 `--to` 兼取。
* **无运行时代价**：只读 JSON 字段，无新增依赖；测试成本可忽略。
* **装配面**：`install.sh` 整目录拷贝 `.atlas/scripts/`，无装配逻辑变更；存量副本需 `--update` 刷新脚本，跑 `test_install_selfcheck` 证明包面一致。

---

## 3. 改动面清单 (Affected Surface)

- [ ] **契约/文档**：
  - `shared/independent-review.md` §3（新字段）、§10.2（M = coverage completed，不再是 summary 汇总数）；**不是 §10.3**。
  - `docs/concepts/review.md` §3（M 口径）；`docs/gates/iron-gates.md` §8（报告形态/历史兼容）；`shared/gates.md` 实例⑤/报告门行（N/M 口径与取证等级）。
  - `shared/closeout.md` 步骤 10：delta 调用补 `--head-sha`（以及 `--delta-only --base-sha` 示例）；明确不得用 `--to` 兼取。
  - `README.md` 实例⑤描述；`docs/map/review.md` 锚点/行数；`DESIGN.md` 新增 D178；`CHANGELOG.md` / `docs/guide/changelog.md` 按发布批同步。
- [ ] **代码逻辑**：
  - `scripts/cli_review_convert.py`：读 `manifest.coverage`；新增 `--head-sha`、`--reviewed-files`；写 `cli_status` / `failed_files` / `waived_files` / `cli_warnings` / `head_sha` / `reviewed_files`；partial/failed 的 WARN 下限；无 completed 的拒绝出口；delta v3。
  - `_support/review_policy.py`：coverage 计数与状态下限的单源 helper；delta v3 的 `head_sha` 必备、`reviewed_files` 成员/数量/`selected` 对账；v2 维持旧语义。
  - `scripts/validate_review_report.py`：v3 分支；`cli_status` / `failed_files` 纳入复算；输出行点名失败文件。
- [ ] **测试防线**：
  - `tests/test_cli_review_convert.py`：coverage 假绿、clean delta、head_sha、fallback、partial/failed、selected 不一致、target 成员、comments=null。
  - `tests/test_review_report.py`：v3 delta 缺 head_sha FAIL、数量/成员不一致 WARN、partial WARN、Critical+partial 仍 FAIL、v2 兼容回归。
- [ ] **留出验证（§4.5）**：H1 coverage 假绿、H2 clean delta 误红；pre-fix 红证见 §4.5 / 附录 A；post-fix 绿证待实现后补。
- [ ] **装配/回归**：`pytest tests/test_install_selfcheck.py`（脚本改了但装配列表未变）；副本 `--update` 后 `python3 .atlas/scripts/atlas_check.py --fast`。
- [ ] **版本装配**：无新增依赖；`package.json` / 版本号由发版批处理，不在本 RFC 内改。

---

## 4. 验证与测试结果 (Verification)

> 本节在草案阶段先写测试矩阵与 pre-fix 红证；post-fix 绿证在实现后回填。

### 4.1 测试矩阵

| # | 输入 | 期望 |
|---|---|---|
| C1 | coverage `selected=5/completed=3/failed=1/waived=1`，`status=partial`，0 comments | `reviewed=3`、`failed_files=1`、`waived_files=1`、`status=WARN`；validator 行可见 |
| C2 | clean delta：`completed=3`，0 comments，`head_sha` 提供 | `reviewed_files` 3 个、`status=PASS`、v3；validator PASS |
| C3 | delta：3 completed，1 finding 落在 1 个文件 | `reviewed_files` 3 个（不是 1 个） |
| C4 | delta 无 `--head-sha` | converter exit 2，报 `head_sha` |
| C5 | delta 无 coverage 且无 `--reviewed-files` | converter exit 2（不回落 findings） |
| C6 | delta 无 coverage，但显式 `--reviewed-files a,b,c` | `reviewed_files` 3 个 |
| C7 | `status=failed`、`completed=0`、comments 空 | converter exit 2 |
| C8 | 非 delta、有 coverage、0 comments、status=partial | `reviewed=4`、WARN（D1 覆盖所有轮次） |
| C9 | coverage `reused` 非空 | 当前只记录 `reused_files`，不计 reviewed；用例钉住该口径 |
| C10 | coverage `selected` 6、`expected` 5 | WARN `selected≠expected` |
| C11 | finding target 在 failed 文件 / 不在 coverage | WARN 点名 |
| C12 | `comments=null` | 维持 exit 2（现有拒绝） |
| C13 | `checks[].target` 为 `?` / 空路径 | 跳过成员对账，不崩溃、不误报 |
| C14 | `reviewed_files` 与 `failed_files` 有交集 | WARN 点名交集 |
| C15 | coverage 路径含 `\` 或重复项 | 统一为 `/` 后去重排序 |
| V1 | v3 delta 报告缺 `head_sha` | validator FAIL |
| V2 | v3 delta 报告 `reviewed=3`、`reviewed_files` 1 个 | validator WARN（非 FAIL） |
| V3 | `cli_status=partial`、无 Major/Critical | validator WARN 下限 |
| V4 | `Critical + partial` | validator FAIL（WARN 下限不得降级） |
| V5 | v2 非 delta 旧 GOOD 报告 | 仍 PASS（回归） |
| V6 | v2 delta 缺 `head_sha` | WARN，不 FAIL（兼容） |
| V7 | `executed=False + complete`；`pre_existing Critical`；`round>=4` | 保持既有 WARN/FAIL/escalation 语义 |
| V8 | `status=skipped` / `unknown` | 不额外抬 WARN；`expected>0` 由 M<N 自然 WARN |

### 4.2 变异钉子（编号按测试文件自成序列）

* **M37**：摘掉 coverage 读取（退回 summary）⇒ C1/C8 红。
* **M38**：摘掉 `head_sha` 推导/必备 ⇒ C4/V1 红。
* **M39**：摘掉 `reviewed_files` 成员/数量对账 ⇒ C3/C11/V2 红。
* **M40**：摘掉 `cli_status` 的 WARN 下限 ⇒ C1/V3 红。
* **M41**：把 `cli_status` 下限误写成可降级 Critical ⇒ V4 红。
* **四段协议（2026-10-31 实跑）**：M37 基线绿 → 注入后 `reviewed 6≠3` 红 → sha256 `a074…` 还原 → 复绿；M40 基线绿 → 注入后 validator exit 1 红 → sha256 `24e3…` 还原 → 复绿；M41 基线绿 → 注入后 converter exit 0/WARN 红 → sha256 `31d5…` 还原 → 复绿。日志在 `/tmp/atlas-batch-a-evidence/`。
* **四段协议（2026-10-31 Batch B）**：M38 基线绿 → 摘 `head_sha` 必备后 missing-head 测试 `0≠2` 红 → sha256 `f0b0…` 还原 → 复绿；M39 基线绿 → 摘 `reviewed_files` 数量对账后 count 测试无 reviewed 警告红 → sha256 `7830…` 还原 → 复绿。日志在 `/tmp/atlas-batch-b-evidence/`。

> **编号说明（主审抽查）**：README 明确「编号在各自测试文件内自成序列，同一号在不同门含义不同」（`README.md:367`）。M37–M39 属 `tests/test_cli_review_convert.py`（该文件已有 M130c；本批暂用 RFC 内部标签，落盘前可顺延为 M131–M133）；M40–M41 接 `tests/test_review_report.py` 现有 M35/M36。其他测试文件里的同号不构成撞号。

### 4.5 留出验证（系统性修复必填；`RFC-20261026-03`）

* **触发面核对**：(b) 改转换器 / 校验器 / 契约判据，diff 落在 `scripts/`、`_support/`、`shared/` 路径族；触发，必须走留出验证。触发 (a) 不适用（本批无 ≥3 条独立审查重复 finding；实例⑤单次真实取证 + 一次子代理评审，不足以冒充 (a)）。
* **留出集（与 §4.1 夹具结构不同，未参与挖弱点）**：
  * **H1（coverage 假绿）**：`selected=6`、`completed=4`、`failed=2`、`summary.files_reviewed=6`、0 comments。预期修复后 `reviewed=4`、`failed_files=2`、WARN；与 C1 的 5/3/1/1 结构不同。
  * **H2（clean delta 误红）**：delta、`completed=2`、`reused=1`、0 comments、`head_sha` 提供、显式 `--reviewed-files` 提供。预期修复后 `reviewed_files` 2 个、`reused_files` 1 个、**WARN（reused 不计 M ⇒ 2<3 如实 M<N）**，但 validator 不再 FAIL；与 C2 的 3/3 结构不同。
* **独立性三条**：
  1. **判据输出翻转**：H1 的 `reviewed` 6→4、status PASS→WARN（C1 为 5→3）；H2 的 validator FAIL→WARN（不再误红；M<N 如实 WARN）。
  2. **变异增量杀伤**：M37/M38 除对应 C 系列外，分别咬 H1/H2（落盘后实测）。
  3. **结构不可达**：现有测试没有 coverage / clean-delta 形态；H1/H2 与 C1/C2 的集合大小、waived/reused 维度不同，不能由既有夹具只改路径/措辞得到。
* **pre-fix 红（本轮已实跑，附录 A 可复现）**：
  * H1（6/4/2）：当前转换器 `PASS 6/6`，validator `PASS`（假绿）；`reviewed` 不读 coverage。见附录 A.1。
  * H2（2 completed + 1 reused）：v2 legacy 模拟（当前 v2 路径）`reviewed_files=[]`，validator `FAIL`（误红）；v3 路径 post-fix 为 `reviewed_files` 2 + `reused_files` 1 + WARN（M<N）。见附录 A.2 / `/tmp/atlas-batch-b-evidence/`。
* **post-fix 绿（Batch A H1，2026-10-31 实跑）**：H1 6/4/2 夹具 → `WARN 应审 6 / 实审 4`、`failed_files=2`、`cli_status=partial`；validator 输出 `[WARN] CLI 审查状态` + `[WARN] 应审/实审对账`，退出码 0。真实 r1 payload 同形复跑同样得到 4/6 + `failed_files` 2 + `partial`；证据见本次会话 `/tmp/atlas-batch-a-evidence/`（H1 与真实 r1 两份 log/json）。
* **post-fix（Batch B H2，2026-10-31 实跑）**：H2 2 completed + 1 reused → `reviewed=2`、`reviewed_files` 2、`reused_files` 1、`status=WARN`（M<N），validator `delta 对账 PASS` + `应审/实审 WARN`，退出码 0；不再 FAIL。
* **真实 r2 v3（2026-10-31 实跑）**：真实 r2 CLI `cli-r2-gemini.json` 以 Batch B 重转 → `schema_version=3`、`head_sha=31ad5ee…`、`reviewed_files/completed_files/selected_files` 各 3、`delta 对账 PASS`、应审/实审 3/3、状态 `WARN`（1 条 Major）；validator PASS。报告在 `/tmp/atlas-impl-review-20261031-204905/nanwang/product/reviews/2026-10-31-impl-review-dashboard-topn-r2-v3/`。
* **反面包**：非 delta、无 coverage 的旧 GOOD 报告仍 PASS（V5）；C1 的合法 3–4 文件结论不得被整体作废（WARN 不是 FAIL）；Critical+partial 仍 FAIL（V4）。
* **三态结论**：Batch A H1 = `闭族`；Batch B H2 = `闭族`（FAIL→WARN，不再误红；`reused` 不计 M 的 M<N 是如实结果）。跨轮 D5 另案。

### 4.6 常规验证命令

```bash
pytest tests/test_cli_review_convert.py tests/test_review_report.py
pytest tests/
python3 scripts/atlas_check.py --fast
python3 tests/test_install_selfcheck.py
```

* **结果（2026-10-31）**：聚焦 **80 passed**（Batch A 52 + Batch B 28）；Batch B 后全量 `pytest tests/` **962 passed, 5 skipped**；`tests/test_install_selfcheck.py` **PASS**；`tests/test_map_anchors.py` **8 passed**。`atlas_check --fast` 在源包工作树无目标资产，按源包态不适用；装配副本回归另行。

---

## 5. 开放问题与风险 (Open Questions)

1. **`reused` 的语义**：OCR coverage 的 `reused` 是「复用已审结果」还是「复用缓存但未审」？未确认前**只算 completed**，`reused_files` 只记录；确认后再决定是否并入 reviewed。
2. **`waived` 的语义**：`waived` 是规则豁免还是未审？本批只记录 `waived_files`，不计 reviewed；若不透明，报告行点名。
3. **`head_sha` 的兼容**：新 delta 报告 v3；v2 历史报告保持旧语义、不回扫。若外部项目有 v2 delta 报告，缺 `head_sha` 只 WARN。
4. **数量/成员不一致 WARN vs FAIL**：首版 WARN；若真实仓再次出现 1/3 且 WARN 被忽略，再按证据升 FAIL。
5. **`skipped` 的出口**：本批只记录 + 依赖 M<N；不把合法 SKIP 一律 exit 2。若 CLI 未来支持「合法跳过」，需新增区分字段，不靠状态名猜。
6. **coverage 字段稳定性**：OCR v1.13.3 的 `manifest.coverage.{selected,completed,reused,failed,waived}` 是否跨版本稳定；不稳定时以 `--reviewed-files` 显式通道为准。
7. **跨轮闭环**：`resolves` 台账的字段、触发条件、WARN/FAIL 分级另案；本批不实现，避免与「同一问题跨轮不得重复贴」冲突。
8. **`selected` 与 expected 的最终口径**：N 仍以 preview Will review 为准；coverage `selected` 只作对账信号，不一致先 WARN，不改 N。
9. **v2 delta 兼容通道**：显式 `--schema-version 2` 的 delta 报告只用于历史兼容；新调用与 `closeout.md` 步骤 10 固定 v3。v2 缺 `head_sha` 只 WARN，但不得成为新报告的常规路径；若被当绕过通道，另案收窄。

---

## 附录 A：pre-fix 最小复现（可复跑）

> 以下夹具使用泛化路径，不含产品/业务数据。当前代码（未实现本 RFC）运行结果即 §4.5 的 pre-fix 红。

**A.1 coverage 假绿夹具**

```bash
mkdir -p /tmp/atlas-coverage-prefix-red
cat > /tmp/atlas-coverage-prefix-red/payload.json <<'JSON'
{
  "status": "partial",
  "summary": {"files_reviewed": 6, "comments": 0, "budget_exceeded": false},
  "comments": [],
  "warnings": [],
  "manifest": {"coverage": {
    "selected": [{"path":"src/a.ts"},{"path":"src/b.ts"},{"path":"src/c.ts"},{"path":"src/d.ts"},{"path":"src/e.ts"},{"path":"src/f.ts"}],
    "completed": [{"path":"src/a.ts"},{"path":"src/b.ts"},{"path":"src/c.ts"},{"path":"src/d.ts"}],
    "failed": [{"path":"src/e.ts"},{"path":"src/f.ts"}]
  }}
}
JSON
python3 scripts/cli_review_convert.py --root /tmp/atlas-coverage-prefix-red \
  --input /tmp/atlas-coverage-prefix-red/payload.json --out report --unit U2 --round 1 \
  --scope "coverage mismatch fixture" --expected-files 6
# 当前输出：PASS 6/6；review.json reviewed=6；validate_review_report PASS
```

**A.2 clean delta 误红夹具（H2：2 completed + 1 reused）**

```bash
mkdir -p /tmp/atlas-delta-prefix-red
cat > /tmp/atlas-delta-prefix-red/payload.json <<'JSON'
{
  "status": "complete",
  "summary": {"files_reviewed": 3, "comments": 0, "budget_exceeded": false},
  "comments": [],
  "warnings": [],
  "manifest": {"coverage": {
    "selected": [{"path":"src/a.ts"},{"path":"src/b.ts"},{"path":"src/c.ts"}],
    "completed": [{"path":"src/a.ts"},{"path":"src/b.ts"}],
    "reused": [{"path":"src/c.ts"}]
  }}
}
JSON
# pre-fix（v2 legacy 模拟）：当前旧语义
python3 scripts/cli_review_convert.py --root /tmp/atlas-delta-prefix-red \
  --input /tmp/atlas-delta-prefix-red/payload.json --out report2 --unit U1 --round 2 \
  --scope "clean delta fixture" --expected-files 3 --delta-only --schema-version 2 --base-sha 1111111
# 输出：WARN 3/2；review.json reviewed_files=[]；validate_review_report FAIL

# post-fix（v3）：Batch B
# python3 scripts/cli_review_convert.py ... --schema-version 3 --head-sha 2222222 \
#   --reviewed-files src/a.ts,src/b.ts
# 输出：WARN 3/2（M<N，reused 不计 M）；reviewed_files 2；validator delta 对账 PASS + 应审/实审 WARN
```
