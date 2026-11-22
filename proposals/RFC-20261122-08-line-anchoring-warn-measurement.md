# RFC-20261122-08: 暂存区评审行级锚定——第一期 WARN 测量面（open-code-review 机制吸收）

> 提案编号：RFC-20261122-08
> 提案作者：Atlas 自动化管家
> 关联状态：草案 (Draft) · **v2**（2026-11-22 双评审「修后再审/有偏差清单」→ 18 条意见全采纳处置，见 §0.2 与 `proposals/REVIEW-20261122-08-line-anchoring-dual.md`）
> 影响范围：脚本工具 (scripts) | 共享内核 (_support) | 契约/文档 (shared) | 门登记 (gates.md) | docs/map 计数面 | tests
> 来源标的：`proposals/ANALYSIS-20261122-01-open-code-review-mechanism.md`（案一调研备忘 §7 拍板记录）+ alibaba/open-code-review `internal/diff/resolver.go`（Apache-2.0，tree `284ff013f0705ae6`）
> 拍板：2026-11-22 经 tech-proposal-reviewer 对抗评审拍板立项（评审 B-1/M-1/M-2/M-3/m-1/m-3 全采纳，见备忘 §7）
> 基线：HEAD `ac061ac`（RFC-07 批 e59b501 + golden ac061ac 已提交收口，本 RFC 落刀前置已满足）

---

## 0. 范围与来源定性（先读这个）

**一句话结论**：给实例 ⑤ 实现代码独立审查的产物加「行级锚定测量面」——第一期只 **WARN + 统计**，不改判收链、不设 FAIL 牙齿、不动 RFC-07 刚落的 cause 词表锚。

**两段式定义**（拍板 B-1/M-3 采纳）：
- **第一期（本 RFC 全部内容）**：测量面。派工包骨架加 `existing_code` 逐字锚字段 + 转换器滑窗复算**四态**统计（anchored / mismatch / unresolved / unanchored）+ 报告目录落 `anchoring-stats.json` + stderr WARN 行。**测量面本身就是取证工具**——仓内零行号漂移病案（评审 B-1 实证，见 §1.3），先测存在性再谈门。
- **第二期（不在本 RFC，另案）**：升 FAIL / 复算改写 / 摘除——只由第一期统计触发，判据写死在 §5。**不预设牙齿的原因**（拍板 M-3）：锚定红若进 verify 失败记账会被记成 `blocking_critical` 扣预算（语义错位：锚定缺失是评审产物形态问题，不是实现侧问题），修正需动 RFC-07 刚落的 `_support/workflow_causes.py` cause 词表锚——同锚别动两次自咬。

**不吸收**（对照 OCR）：跨文件重挂（`RelocateAcrossFiles`）、LLM 重定位（`RE_LOCATION_TASK`）、行号越界硬校验（T6）——一期测量面只复算不裁决；若第二期需要，按 OCR 正本另批。

### 0.1 与 RFC-20261122-07 的文件面关系（v2 改写，双评 R1-M1/R2-4）

- **代码面零交叉（证实）**：e59b501 对 `atlas_review.py` / `cli_review_convert.py` / `independent-review.md` 的 diff-stat 为空。
- **契约面同文件（如实声明）**：`shared/gates.md`（RFC-07 加了 §2.1 预算门行；本 RFC 加观察面登记行——同文件串行提交）、`docs/map/index.md` + `docs/map/atlas-map.html`（两批都动计数/行数锚）、golden 基线（ac061ac 后本 RFC 批内重录）。
- **前置状态**：RFC-07 已于 e59b501 + ac061ac 提交收口 ⇒ 本 RFC 落刀窗口**已打开**，仅需登记行与计数修改同批串行。

### 0.2 v2 修订摘要（v1 → v2，逐条对应双评审）

| 意见 | v2 处置 |
|---|---|
| R1-M1 / R2-4 零交叉声称 | §0.1 改写（上表）；「git status 实证」过期表述撤回 |
| R1-M2 diff 基准只写 staged | §2.1-件② 补**基准三模式推导**（staged→`HEAD..INDEX`；from/to→`ref_from..ref_to`；delta→`base_sha..head_sha`；先例 `atlas_review.py:483-486`）+ 转换器加 `--diff-base/--diff-head` 参数、atlas_review 组装 conv 命令处加传；基准不可得 ⇒ `unresolvable` 档，不计 mismatch 分子 |
| R1-M3 三态口径漏「复算无果」 | 三态→**四态**：anchored / mismatch（在别处命中=漂移）/ **unresolved（报了行号+L1/L2 均无果）** / unanchored(legacy\|no_field)；§5 分子分母同步 |
| R1-M4 统计面永不 die 未给实现约束 | §2.1-件② 写死三条：①复算与落盘全程 `try/except (OSError, subprocess.SubprocessError)` → WARN 降级继续；②stats 写在 review.json/README **之后**（链尾最后一步）；③钉1 加「stats 写失败 ⇒ 退出码与 review.json 产物不变」断言 |
| R1-M5 executor 混跑/no_field 判据不自洽 | **executor 字段保留、判据按轨收窄**：executor 取值 = cli.json 顶层 `executor` 键（session 骨架已有 `session-subagent`，`atlas_review.py:221`；CLI 产物无此键 ⇒ `unknown`）；§5 升降档判据**只收 executor=session-subagent 的窗**，unknown/cli 轮统计照记、注明「分轨外」；OCR「天然无字段」断言撤回——OCR `code_comment` 工具层**强制** existing_code（`internal/tool/code_comment.go:142-144`），其 `--format json` 产物是否透传**未核实**（通道受限），分轨设计下两种情况均兼容 |
| R1-M6 证伪命令不可复跑 | §2.2 命令改**直跑转换器**（`cli_review_convert.py --input <四态夹具> --out <tmp>`）；`atlas review` 端到端另列可选 |
| R2-2 棘轮「四处」一误三漏 | §3 棘轮清单重写：删 apply.md 咬合（不成立——其行数锚不指向本批改动件）；**补三处**：`docs/map/index.md`〔共享内核=28→29〕、`shared/gates.md` 191 行 ×2（`docs/map/gates.md:18` + `atlas-map.html:564`）、`atlas-map.html:496`〔契约转换器 458 行〕；保留出厂测试文件数 87→88 三面 |
| R2-2 算法边界未讨论 | §2.1-件② 补：`-U0` 显式选型（只取 +/- 行，hunk 头计数器语义同 changelog_guard.py:9-11,45 先例）、`\ No newline at end of file` 跳过、binary/纯 rename 无 hunk ⇒ 该文件 unresolvable；「无新增进程」改「**新增一次** `git diff` 子进程（毫秒级，滑窗实测 3.8ms @万行×10 条）」 |
| R2-5 golden 咬面低估 | §2.3 改宽口径：golden `runs[].tree.files` 212 文件内容哈希，本 RFC **五个改动件全在表内**（atlas_review.py / cli_review_convert.py / independent-review.md / gates.md）+ 新 `_support/line_anchor.py` 成新条目（workflow_causes.py 先例 ac061ac）⇒ 批内全量重录 |
| R1-m1 分章 rider 无独立注记 | §3 补 rider 单独验收/回滚注记（一行字，验收=派工包含该行；回滚=单行删除，不牵连锚定统计口径） |
| R1-m2 管道措辞不准 | 「现成管道」改指 `atlas_review.py:483-486`（scope manifest 的模式推导先例）+ changelog_guard hunk 头解析先例；进程表述见上 |
| R1-m3 匹配确定性未指定 | §2.1-件② 写死：**首处命中即 resolved**（从文件头顺序扫描）；无并列策略（一期不需要） |
| R1-m4 窗口数与窗单位 | §5 窗单位定义（同 --unit 一轮 verify→convert 链，round 号唯一）；摘除判据 **2 窗→3 窗**（对齐 gates.md:57 impact_reconcile「连续 3 单」先例）；升档维持 2 窗（另案复议有缓冲） |
| R1-m5 接线落点 | §2.1-件② 接线锚从 convert() 纯函数体（:146-165，无 I/O）改到 **main() 调 convert() 之后、报告写盘链尾**（复算需 git 子进程与 root，落盘需 outdir——均 main() 职责） |
| R1-m6 指令行位置 | existing_code 要求从「探索预算」段（:244-250）移到「## 产物」段（:255-257）——产物形态归产物段 |
| R2-1 §1.4 :286-288 弱证据 | 引用降级为「字段存在性 :120/:127；语义支撑 :120 docstring」 |
| R2-3 计数先例确认 | 棘轮清单附实测现值（tests 87 / 共享内核 28 / gates.md 191 / 转换器 458） |
| R2-6 统计落盘安全 | §2.3 补旁证：全仓无 anchoring/stats 撞名；`review_closure.py:116-131` 孤儿扫描只 glob findings/ 子目录、`validate_review_report.py:77-93` 只读指名文件、`evidence_archive.py:130` 包容性归档；同形态先例 `impact_reconcile.py:137` |

## 1. 现象与取证

### 1.1 触发形态（抽象）

* **规则 / 环节**：实例 ⑤（`shared/independent-review.md` §10）实现代码独立审查的产物链：`cli.json` comments[] → `scripts/cli_review_convert.py` → `review.json` → 判收。
* **触发时机**：每次 `atlas review` / `atlas workflow verify` 产出 findings。
* **具体行为**：`comments[].start_line/end_line` 由审查 LLM **自报**，转换器直通采信——`scripts/cli_review_convert.py:152-153` 只处理「0/缺行号 ⇒ `path:?（定位失败，人工定位）`」这一种**显式**未锚定形态；「报了行号但报错位置」（漂移）无任何检测、无统计、无声音。审查者 LLM 换模型 / 换 prompt / 上下文压缩后，行号错位既不可见也不可查。

### 1.2 客观证据（三条，均为设计级旁证，非病案）

1. **仓内指纹层已防御行号漂移、产物层无对应物**：`_support/review_policy.py:101-109` `compute_fingerprint` docstring 原文——「基于文件路径（**排除易漂移的行号**）+ 检查类别 + 核心摘要首行计算哈希」（`clean_target_file` :71-74 剥行号/行区间）。**跨轮去重不受行号漂移影响**这个设计决定，本身就是「行号确实易漂」的仓内承认；但产物展示层（`target` 字段）对行号正确性零防御——防御只做到了去重层。
2. **OCR 规模化先例**：alibaba/open-code-review（55.2k★，两年内部验证）把「Position drift」列为三大病灶之一（其 README.md:78 原文核实），解法 = `existing_code` 逐字锚 + 确定性滑窗复算（`internal/diff/resolver.go`：`extractSideLines` hunk 头计数器推算 + `normalizeLine` 剥 `+/-`/trim + `matchConsecutive` 滑窗 + `resolveFromFileContent` 全文回退，评审二实抓逐点吻合）+ LLM 行号永不直接采信 + T6 行号越界硬校验（其 ASSURANCE_CASE.md）。算法可整体对照移植（评审二实测 naive 纯 Python 滑窗 **3.8ms** @万行×10 条 3 行摘录）。
3. **既有降级形态连续**：`cli_review_convert.py:152-153` 的 `path:?（定位失败，人工定位）` 已是「未锚定显式降级」先例——本 RFC 的 unanchored 档与之连续，不是新造形态。

### 1.3 病案声明（诚实条款）

**仓内零行号漂移病案**：`duty-review/bugs.md` 自感知上报族八案均为「判据可被形态满足」，无一行号案（:58 唯一「行号」命中是重开程序措辞）；存量 proposals grep `start_line` 零漂移实例（评审二复核）。因此本 RFC **不是 bug 修复**，不引用「自感知上报族行号漂移」为病案；立项依据 = 证据 1（仓内设计级承认）+ 证据 2（外部规模化先例）+ 测量面零风险（WARN 不置红）。若第一期统计≈0，按 §5 摘除判据退出——这正是 D206 减法引擎友好的形态。

### 1.4 pre_existing 产物面（复算锚层设计的硬约束）

`_support/review_policy.py:120`（「pre_existing=True（存量代码问题）⇒ 不阻断」docstring）与 :127（判定行）：`pre_existing=true` 的 finding 指向**不在本次 diff 里的存量代码**（语义支撑 :120 docstring；字段存在性另见 :286-288 v2 schema 校验）——纯「暂存区 diff hunk 区间」锚对它结构性空转（评审 M-1）。复算必须两级：hunk 新侧 → 全工作树文件回退。

## 2. 决策与权衡

### 2.1 核心定案

三个改动件，退出码契约（0/1/2）全程不变：

**件① 派工包骨架与指令（`scripts/atlas_review.py` `write_review_request`，:213-265）**
- 产物骨架（:219-235）comments[] 示例加字段：`"existing_code": "<finding 指向代码的逐字摘录，1-5 行>"`。
- 指令行（**「## 产物」段 :255-257**，评审 R1-m6）加两条：①「每条 finding 必须带 `existing_code` 逐字摘录（从 diff 或相关文件原样复制，禁止改写/重排/缩进调整）」；②**分章审查顺序一行字**（案二 plannotator guided review 排序学说吸收，拍板决策点 4）：「先审变更核心（heart），再审其后果（consequences），最后审胶水（glue：配置/注册/样板）」。
- 同函数一次落刀（拍板 m-1）：不在其他批触碰本函数。

**件② 滑窗复算 + 统计（新 `_support/line_anchor.py` 单源 + `scripts/cli_review_convert.py` main() 链尾接线，评审 R1-m5）**
- 算法单源 `_support/line_anchor.py`（纯标准库，OCR `resolver.go` 同算法移植；模块惯例套 `_support/siblings.py:22-27` load_module）：
  - **diff 基准三模式推导**（评审 R1-M2；先例 `atlas_review.py:483-486`）：staged ⇒ `HEAD..INDEX`；`--from/--to` ⇒ `ref_from..ref_to`；delta ⇒ `base_sha..head_sha`。转换器加 `--diff-base/--diff-head` 参数，`atlas_review.py` 组装 conv 命令处（:495-499）加传；基准不可得（非 git 仓/裸 ref 解析失败）⇒ 该轮全部 `unresolvable`，不计 mismatch 分子。
  - **解析**（评审复核 R-3/R-4 处方）：命令**分模式**——staged ⇒ `git diff --cached -U0 --no-renames`（`INDEX` 不是合法 ref，`--cached` 默认对 HEAD）；range/delta ⇒ `git diff <base>..<head> -U0 --no-renames`（-U0 只取 +/- 行，hunk 头计数器语义同 `changelog_guard.py:9-11,45` `HUNK_RE` 仓内先例）；`\ No newline at end of file` 元行跳过；binary 文件段（`Binary files … differ`）⇒ 该文件 unresolvable（`--no-renames` 下纯 rename 产生 delete+add hunk，有 hunk 可复算，无特例）；**comment 的 path 不在 diff 输出 ⇒ 跳 L1 直入 L2**（pre_existing 口径前提，不算 unresolvable）。
  - **normalize**：逐行 strip 首尾空白 → 剥行首 `+`/`-` → 跳空行（OCR `normalizeLine`/`splitAndNormalize` 同款）。
  - **两级匹配**：L1 = diff hunk 新侧（context+added；-U0 下即纯 added 行，行号由 hunk 头计数器推算）→ L2 = 全工作树文件回退（pre_existing/上下文发现兼容，§1.4）。**首处命中即 resolved**（文件头顺序扫描，无并列策略——评审 R1-m3）。复算**只读**：不改写行号、不改 target、不进指纹。
- **四态定义**（评审 R1-M3；统计的分子分母全在此，防口径漂移；**anchored 谓词**按复核 R-2 处方写死）：
  - `anchored`：报了行号且复算命中，**reported 区间与 resolved 区间相交（含子集）**——摘录 1-5 行是报告区间的子集不是漂移；
  - `mismatch`：报了行号，复算命中但**无交集**（真实漂移观测）；
  - `unresolved`：报了行号，L1/L2 均无果（摘录被改写/hallucinated 的候选信号，单独计数不与 mismatch 混）；
  - `unanchored`：行号 0/缺，分两档——`unanchored(legacy)`（字段存在但行号 0/缺）与 `unanchored(no_field)`（字段缺失；session 骨架更新后不该出现，外部 CLI 产物可能整轮出现）；
  - `unresolvable`：基准不可得/无 hunk/binary，整轮或单文件级，不计入漂移率。
- **统计落盘**：`<报告目录>/anchoring-stats.json`：`{"executor": "session-subagent|unknown", "diff_mode": "staged|range|delta|none", "total": N, "anchored": n1, "mismatch": n2, "unresolved": n3, "unanchored_legacy": n4, "unanchored_no_field": n5, "unresolvable": n6, "comments": [{"path", "reported": [s,e]|null, "resolved": [s,e]|null, "state": "..."}]}`。executor 取值 = cli.json 顶层 `executor` 键**记录原值**（session 骨架已有 `session-subagent`，`atlas_review.py:221`；无键 ⇒ `unknown`；外部 CLI 自带其他值照记原值——复核 R-5 处置，**判据窗只认 `session-subagent`**，其余值统计照记、注明分轨外）。**不动 review.json v4 schema、不动判收链**；落盘无消费者冲突（评审二核验：`review_closure.py:116-131` 只 glob findings/ 子目录、`validate_review_report.py:77-93` 只读指名文件、`evidence_archive.py:130` 包容性归档；同形态先例 `impact_reconcile.py:137`）。
- **三条实现约束（评审 R1-M4，写死）**：①复算与落盘全程 `try/except (OSError, subprocess.SubprocessError)` → stderr WARN 降级继续，**永不 die**（与转换器 14 处 `SystemExit(die)` 快速失败文化隔离）；②stats 写在 review.json/README **之后**（写盘链尾最后一步），任何失败只出 WARN 行不留半截产物；③钉1 加「stats 写失败 ⇒ 退出码与 review.json 产物不变」断言。
- **WARN 行**（stderr 出声不置红）：`WARN（行级锚定）: anchored n1 / mismatch n2 / unresolved n3 / unanchored n4+n5 / unresolvable n6 —— 明细 <报告目录>/anchoring-stats.json`。

**件③ 契约正本同步**
- `shared/independent-review.md` §10.1（:204 输出契约段）：补一行「comments[] 宜带 `existing_code` 逐字摘录（锚定复算输入；缺失按 unanchored 计，不判错）」+ :200 session 执行器描述句同步。
- `shared/stack-profile.md` impl_review 表（:110-122）：**核实后不涉及**（执行器配置契约，不涉产物 comments schema）——评审 M-2 的该侧同步项核实后不适用，注记留痕。
- `shared/gates.md`：观察面登记行——照 `gates.md:57` impact_reconcile 先例格式（WARN-only 判据 + 行内观察窗/升档规则 + M 编号变异钉），并填齐「**不查什么**」（不裁决/不改写/不进指纹/不置红）与假绿测试列（M 钉锚 `test_line_anchor`），判据值全在本行。

### 2.2 最强反方与证伪条件

* **最强反方论证**：「仓内零病案，测量面大概率测出漂移率≈0，白加一个字段和一套复算。」——此反方若成立，否决的是「直接立 FAIL 门」与「复算不符即改写行号」两个备选；对测量面本身它不是否决而是**验收路径之一**：统计≈0 ⇒ 按 §5 摘除判据退出（字段成本 = 骨架一行 + 复算毫秒级实测 3.8ms，摘除后零残留），测量面恰是 D206 减法引擎的标准输入。测量面的不对称代价与 OCR 反思过滤同构：误报（把好行号算成 mismatch）只花统计面几行日志；漏报（漂移被静默吸收）会让「行号错位的人工复核成本」永久隐身。
* **证伪条件**（复用 `shared/independent-review.md` §11 `discriminating_check{command, expected_if_false}` 形态；评审 R1-M6 改直跑转换器）：
  - `{command: "python3 scripts/cli_review_convert.py --input tests/fixtures/line_anchor/four-state.json --out <tmp> --unit RFC08-T --expected-files 1 --diff-base HEAD --diff-head HEAD  # 空 diff ⇒ L1 空 ⇒ L2 全文回退兜底；夹具 grounding：comments 的 path 指向 tests/fixtures/line_anchor/ 下已提交的已知内容文件，L2 全文匹配确定性可复跑（复核 R-1 处置）。四态夹具（correct/mismatch/unresolved/unanchored-legacy 各 1 条 + no-field 变体轮）→ 断言 anchoring-stats.json 六计数与夹具逐字一致 + stderr WARN 行 + review.json 判收链零影响", expected_if_false: "任一计数错位、WARN 缺失、stats 写失败时退出码/产物变化（钉1 反例）、或 review.json 字段/指纹变化"}`
  - 端到端（可选，不进判别命令）：`atlas workflow verify --unit <真实ID>` 真跑一轮后核对 anchoring-stats.json 与报告目录一致性。
* **其他备选（已否）**：
  - 直接 FAIL 门：评审 M-3 否（cause 词表撞锚 + 语义错位）；
  - 复算不符自动改写行号：否——改写会掩盖漂移统计，一期只记不改；
  - 复算放 `make_review_inputs.py`（输入面）：否——锚定是产物面属性，错位；
  - 沿用 OCR 全套四层漏斗含跨文件重挂与 LLM 重定位：否——一期不需要，另批按需；
  - executor 字段砍掉、判据只看 session 轮：否——CLI 产物可能透传 existing_code（OCR 工具层强制字段），分轨保留复算收益（评审 R1-M5 处置 = 保留字段 + 判据分轨）。

### 2.3 必须警惕的刺痛代价与兼容性影响

- **兼容性**：存量采纳仓升级后，首轮 session 产物若派工包未刷新 ⇒ `unanchored(no_field)`，**不计错不置红**（分档设计正是为此）；外部 CLI 执行器产物 executor=unknown ⇒ **分轨外**，统计照记不进判据窗。字段宜带（WARN 面用语）非必备，v4 判收链零变化。
- **执行耗时**：新增一次 `git diff` 子进程 + 滑窗复算——评审二实测 naive 纯 Python **3.8ms**（万行文件 × 10 条 3 行摘录，含归一化），毫秒级有量级余量。
- **存量项目**：拉取后无需重新 `atlas init`；下次 `install.sh --update` 咬合。
- **golden**：咬面比派工包骨架更宽——golden `runs[].tree.files`（212 安装树文件）内容哈希，本 RFC 五个改动件全在表内（`.atlas/scripts/atlas_review.py`、`.atlas/scripts/cli_review_convert.py`、`.atlas/shared/independent-review.md`、`.atlas/shared/gates.md`）+ 新 `_support/line_anchor.py` 成新条目（workflow_causes.py 先例见 ac061ac）⇒ **批内全量重录**，维持「worktree 对已提交树录」纪律。前置（RFC-07 golden ac061ac 已提交）已满足。
- **长期维护**：`_support/line_anchor.py` 一个纯函数模块 + 转换器一处链尾接线；生命周期到 §5 升降档判据触发（升档另批或摘除），非永久门。

## 3. 改动面清单

- [ ] **契约/文档**：`shared/independent-review.md` §10.1（comments 字段行 + session 描述句）；`shared/gates.md` 观察面登记行（:57 先例格式）；`shared/stack-profile.md` **无同步项**（核实注记见 §2.1-件③）
- [ ] **代码逻辑**：`_support/line_anchor.py`（新，算法单源）；`scripts/cli_review_convert.py`（main() 链尾接线 + `--diff-base/--diff-head` 参数 + 统计落盘 + WARN 行）；`scripts/atlas_review.py`（`write_review_request` 骨架字段 + 「## 产物」段指令行；conv 命令组装 :495-499 加传基准）
- [ ] **测试防线**：`tests/test_line_anchor.py`（新文件，4 钉见 §4）
- [ ] **docs/map 计数面与棘轮清单**（评审二实测现值，落刀批**同批全修**）：
  - `tests/test_*.py` 文件数 87→**88**：`docs/map/index.md:108`〔数：出厂测试文件=87〕+ `shared/gates.md:129`〔数：出厂测试文件=87〕+ `docs/map/atlas-map.html:308` 两措辞（`87 文件` + `87 个测试文件`）
  - `_support/*.py` 共享内核文件数 28→**29**：`docs/map/index.md`〔数：共享内核=28〕（RFC-07 已 bump 27→28 先例）
  - `shared/gates.md` 行数 191→**N**：`docs/map/gates.md:18` + `atlas-map.html:564` 两处「191 行」锚
  - `scripts/cli_review_convert.py` 行数 458→**N**：`atlas-map.html:496`「契约转换器 458 行」锚
  - ~~`apply.md` 行数锚~~：**不咬**（评审二证伪——其锚不指向本批改动件；v1 预警误列，撤）
- [ ] **golden 重录**：批内全量（§2.3 宽口径），`--record` 对已提交树录
- [ ] **留出验证（§4.5）**：**不适用**——本 RFC 非门/校验器判据变更（WARN 观察面，无判据翻转）；触发面核对：(a) 是否改门/校验器/契约判据 ⇒ 改 gates.md 登记行（观察面行，无既有判据翻转）、§10.1 加字段行（宜带非必备，无判据）；(b) 是否落 DR4 段级锚路径族 ⇒ 否。
- [ ] **版本装配**：package.json 随发版批（不单动）

### 3.1 分章 rider 注记（评审 R1-m1）

指令行②（heart→consequences→glue）以 rider 身份随本批落，单独验收/回滚：**验收** = 派工包含该行（tests/test_atlas_review.py:164-177 子串断言风格补一条）；**回滚** = 单行删除，不牵连锚定统计口径与四态定义。测量面（anchoring 统计）不承载该 rider 的效果评估——其收益另行观察，不写死判据。

## 4. 测试钉规划（落刀批实施；本草案只列清单）

| 钉 | 内容 | 杀伤目标 |
|---|---|---|
| 钉1 | 四态+变体合成夹具（correct/mismatch/unresolved/unanchored-legacy 各 1 条；no-field 与 unresolvable 变体轮）→ anchoring-stats.json 六计数逐字断言 + WARN 行断言 + review.json 判收链零影响断言 + **stats 写失败（模拟 OSError）⇒ 退出码与产物不变**断言 | 复算主链 + 证伪条件 + R1-M4 约束③ |
| 钉2 | pre_existing finding（行号指向 diff 外存量代码）→ L2 全文回退命中 ⇒ anchored；-U0 下 hunk 头计数器推算行号正确性（含 `\ No newline` 元行） | 两级锚层（M-1）+ 解析边界 |
| 钉3 | 外部 CLI 形态产物（无 executor 键 + 无 existing_code）⇒ executor=unknown 分轨外 + unanchored(no_field)，退出码仍 0；三种 diff 基准（staged/range/delta）模式推导各一例 | 分档兼容 + R1-M2 基准推导 |
| 钉4 | 变异钉：删 normalize 的 `+/-` 剥离（或 hunk 头计数器错 1）⇒ 钉1 夹具 mismatch 计数翻转 | 归一化/行号推算防退化 |

## 5. 第一期验收与升降档判据（第二期触发物，写死在此）

- **窗单位**（评审 R1-m4）：一个「窗」= 同一 `--unit` 的一轮 verify→convert 链（round 号唯一）产生的 anchoring-stats.json；「真实窗」= 非 §4 合成夹具的轮。**判据窗 = executor=session-subagent 的真实窗**（评审 R1-M5 分轨）；executor=unknown（外部 CLI）轮统计照记、注明分轨外、不进判据。
- **验收**：≥1 个真实判据窗产出 anchoring-stats.json，六态计数经钉1 形态核对；统计随报告目录留档可复查。
- **升档判据（DR2 触发，2 窗）**：连续 ≥2 个真实判据窗 `mismatch / (anchored + mismatch + unresolved)` > 10%（阈值实测后可修）⇒ 另批议第二期（FAIL 门 / 复算改写 / LLM 重定位，含与 RFC-07 cause 词表的协调预留）。unresolved 单独列升档观察（hallucinated 摘录信号），不与 mismatch 混计。
- **摘除判据（D206 减法触发，3 窗——对齐 gates.md:57「连续 3 单」先例）**：连续 ≥3 个真实判据窗 mismatch=0 且 unresolved=0 且 unanchored(no_field)=0（session 骨架已刷新前提下字段无增噪）⇒ 另批议摘除 `existing_code` 字段与复算接线（算法模块留 tests 夹具退役）。
- **观察义务**：anchoring-stats.json 明细数组保留逐条 reported/resolved 对照——第二期评审的证据输入。

## 6. 落刀窗口与登记

1. **前置**：RFC-20261122-07 批已收口（e59b501 + golden ac061ac）⇒ 窗口已打开；代码面零交叉（e59b501 diff-stat 实证），契约面 `shared/gates.md` + docs/map 计数面同文件已串行化（§0.1）。
2. **落刀**：§3 清单一次批（代码 + 契约 + tests 4 钉 + 棘轮四组计数 + golden 全量重录同批）；登记行提交串行。
3. **登记**：QUEUE.md 观察室 65 行已挂拍板注记；本 RFC 双评审记录落 `proposals/REVIEW-20261122-08-line-anchoring-dual.md`（已落，含 v2 处置逐条）。
