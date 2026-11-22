# 提案标题：finish 收口新增「结构事实新鲜度」硬前置（没刷 spec 拒收）

> 提案编号：RFC-20261122-05
> 提案作者：@sunwenzhe
> 关联状态：已定案 (Accepted)——tech-proposal-reviewer 2026-11-22 终审「修后通过」，2 Critical + 5 Major + 4 Minor 全采纳（§2.4 采纳记录）
> 影响范围：脚本工具 (scripts) / 契约 (shared/gates.md) / 测试 (tests)

---

## 1. 现象与取证 (The Problem & Evidence)

### 1.1 触发形态（抽象）

* **规则 / 环节**：收口链「显式刷结构事实（`refresh_structure.py --chain`）→ `atlas workflow finish`」（`RUNBOOK.md` 收口节）。刷新是**纯纪律**：`finish_task`（`_support/workflow_finish.py`）只查 review 证明与 E2E 前置，对结构事实是否刷新**零机器判据**。
* **触发时机**：跳过刷新步骤直接 `atlas workflow finish --unit <ID>`。
* **具体行为**：**静默通过并归档**。唯一相关信号是 `atlas_check` 的「结构漂移」门——但它 (a) 恒 WARN 不置红（登记语义归收口对账人终审，既有拍板）；(b) 结构环**从未跑过**时（无 `.adapter-out/`）直接 `SKIP`，连 WARN 都没有。即「没刷 spec 就收口」在机器面上无任何出声点，只有 baseline 不自进这个静默信号。

### 1.2 客观证据与日志 (Minimal Evidence)

```text
$ python3 - <<'PY'
# 现状复现：tmp 仓 git init → 提交代码 → 手写 _meta.json baseline=旧提交 → 再提交一笔
# → atlas workflow finish --unit T-01 ⇒ 退出码 0，收口成功，无任何结构相关输出
PY
# 佐证（代码面）：
# _support/workflow_finish.py::finish_task 仅查 review（--force 可绕）+ E2E 前置 + 归档碰撞
# scripts/atlas_check.py::check_drift 无 .adapter-out/ ⇒ SKIP "结构环未跑"
# 全仓 baseline.commit ⇄ HEAD 比对仅存在于 refresh_structure.py 自进对齐检查一处
```

---

## 2. 决策与权衡 (The Decision & Trade-offs)

### 2.1 核心定案 (The Decision)

* **方案总结**：`finish_task` 新增三态前置 `check_structure_freshness(root)`（形状复刻 `check_e2e_precondition`），**FAIL ⇒ `FinishError` 拒收**；refresh 保持显式（D205 已退役 after_archive 钩子，不在 finish 里代写 spec——本门只拒绝，不代跑）。
* **判据**（唯一的机器可读新鲜度证据 = `_meta.json.baseline.commit`，全仓无 `refreshed_at` 类字段）：

| 态 | 条件 |
|---|---|
| SKIP | `.atlas/spec/structure/_meta.json` 不存在（未开户，与 `atlas_check._gate_preconditions` 的 `validate_structure` 前置同口径）；或 `.git` 不存在（非 git 仓） |
| FAIL | ① `_meta.json` 坏 JSON；② `baseline.commit` 缺失或占位（`[必填` 前缀 / `—`，覆盖模板两种兜底）；③ baseline 与 HEAD 不满足双向前缀匹配（复用 `maybe_advance_baseline` 的短 SHA 归一口径）；④ git 探测失败（`.git` 在而 `rev-parse HEAD` 不可用——硬门 fail-closed，**不与「非 git」混叠**，评审 M1）；⑤ 产品侧存在非豁免**未暂存/未跟踪**改动（porcelain `Y≠' '` 或 `X=='?'`；**纯暂存面豁免**——由 review 封口门背书，见 §2.2 C1）；⑥ 豁免面配置读盘失败（`LayoutError`，评审 m1） |
| PASS | baseline ≡ HEAD ∧ 无非豁免未暂存/未跟踪改动 |

* **为何这是正解**：F26 已把「baseline 只在产品侧干净时自进到 HEAD」定为事实锚语义（baseline = facts 所描述代码态所在 commit）。`baseline ≡ HEAD` 是「结构事实已重锚到当前提交」的充分机器证据；未暂存/未跟踪的脏路径意味着连「暂存封口」都不曾背书过的游离改动。这把 RUNBOOK 咬合顺序从纪律钉进机器，与 review 门 / E2E 前置同为收口前置的既有模式，零新字段（读既有 `_meta.json`）、零新门组件（不进 `VALIDATORS`，校验器数不变）。
* **接线面**：`finish_task` 内接在 E2E 前置之后（最小化既有失败信息顺序变化）；`cmd_run` 经 `finish_task` 自动被覆盖；`cmd_archive` 不动（信任 completed 状态，与 review/E2E 现状同口径）。结论随 `e2e_precondition` 先例落 `task.json.structure_freshness` 留痕。**`--force` 不绕本门**（force 语义 = 跳过人工审查，非跳过事实锚；评审 M4）。
* **收口顺序契约（评审 C1 拍板）**：现行契约 = finish 时实现**仍在暂存区**（`_scope_matches` 对暂存面整体摘要封口，提交后暂存区空 ⇒ review 门必红；`cmd_run` docstring「实现已按派工单完成并 git add 暂存」）。因此本门**只判未暂存/未跟踪侧**，暂存面不入判据；「staged 增量尚未进 facts」为**显式盲区**（其内容由 review 封口门背书；commit 后下一笔 finish 由 baseline 落后硬拦 + 下轮 `--chain` 补锚）。FAIL 文案相应为：未暂存改动先暂存（并过审查）或清理，**不指引「先提交」**（那会撞 review 封口门）。
* **空转态出路（评审 C2 拍板）**：facts 由 agent 维持、无适配器的合法形态下，F26 前置③（fact_results 空 ⇒ 不推进）使 baseline **永久不可达 HEAD**，本门会把这类仓锁死。修法：`--advance-baseline`（既有「人工终审显式背书」通道）扩为同时越过前置③（`if not fact_results and not override`）——既有钉子无「空转 × override」组合，行为扩展不破钉；gates.md `refresh_structure` 行与 F26 docstring 同步修订。FAIL 文案双通道：适配器已接 ⇒ `refresh_structure.py --root . --chain`；facts 由 agent 维持 ⇒ 追加 `--advance-baseline`。
* **复用方式（单源）**：把 `maybe_advance_baseline` 内联的「SHA 双向前缀匹配」「porcelain 脏路径扫描」抽成 `refresh_structure.py` 模块级函数（行为不变，`test_refresh_facts.py` 21 条保绿；脏路径函数带 `worktree_only` 分支供门侧复用），`workflow_finish` 惰性 `sys.path` 导入；**ImportError ⇒ FAIL**（响亮指名重跑 `install.sh --update`，不走 atlas_check 的 WARN 降级模式——硬门降级 = 复制要治的静默病，评审 M2）；`_meta.json` 解析在门侧自行 `json.loads`（`load_meta` 的 `die()` 语义不可复用，评审 m3）。

### 2.2 最强反方与证伪条件 (Strongest Counterargument & Falsification)

* **最强反方论证**：「干净树要求与暂存封口契约互斥」——成立过：初版判据把暂存面算脏，修复指引「先提交 → refresh → finish」在提交后撞 `_scope_matches` 的暂存摘要封口（实审文件未暂存），两门合取不可满足，主路径 finish 变不可达。**修法采纳 (a)**：脏判据收窄到未暂存/未跟踪侧，暂存面由 review 封口门背书并把「staged 增量未进 facts」写进显式盲区（备选 (b)「改收口顺序为 commit → finish + review 锚改到 commit」是大改，超出本 RFC 范围，明确否决）。次强反方：「机器判不了台账语义，本门把『漂移登记归人终审』的 WARN 拍板偷偷升格成硬门」——部分成立（评审 M3）：本门不读 `_drift.json`、不直接判漂移登记语义，但**未终审漂移经 F26 baseline 冻结，在「有已提交改动」场景间接阻断 finish**——间接后果明写于此并拍板接受（出路径 = 对账终审后下轮零漂移 `--apply` 吸收，或 `--advance-baseline` 显式背书；gates.md 盲区列同步声明）。第三反方：「空转态仓永久锁死」——成立过（评审 C2），修法见 §2.1。被否决的备选：①finish 内联自动跑 `--chain`（= 复活 D205 刚退役的钩子语义 + 静默写 spec 违反写盘报备纪律 + 适配器失败耦合收口）；②只升格 `atlas_check` 漂移门为 FAIL（违背登记语义归人终审的既有拍板，且 SKIP 盲区依旧）；③只查 baseline≡HEAD 不管脏树（「改码→刷新→不提交→finish」路径 HEAD 与 baseline 双双未动，照样 PASS）。
* **证伪条件**：
  * `discriminating_check{command: "tmp 仓构造 baseline≡HEAD ∧ 无未暂存/未跟踪改动 ∧ 实现已暂存（v4 scope 报告封口一致）→ atlas workflow finish", expected_if_false: "退出码 0"}` —— 若拒收，说明本门越权把暂存面算脏、与 review 封口门互斥（C1 复发，方案错）。
  * `discriminating_check{command: "tmp 仓构造 baseline=旧提交 ∧ HEAD 已前移（提交后未刷新）→ atlas workflow finish", expected_if_false: "退出码 1 且文案含 refresh_structure.py 与 --advance-baseline 双通道"}` —— 若放行，堵漏目标未达成。
  * `discriminating_check{command: "tmp 仓构造 baseline≡HEAD ∧ 干净树 ∧ 手改事实表内容（行内改值不增删键）→ atlas workflow finish", expected_if_false: "退出码 0（PASS）"}` —— 若拒收，说明本门越权判了内容级一致性（声明盲区被违反）。
  * `discriminating_check{command: "无适配器空转态仓（baseline 落后）→ refresh_structure.py --chain --advance-baseline → atlas workflow finish", expected_if_false: "baseline 推进到 HEAD 且 finish 退出码 0"}` —— 若仍 FAIL，空转态出路不可达（C2 复发）。
* **其他备选**：`refreshed_at` 时间戳类判据——被否：`_meta.json` 现无该字段，新增字段 = 新字段面；且 mtime/rebase/checkout 下时间戳语义脆弱。

### 2.3 必须警惕的刺痛代价与兼容性影响 (Trade-offs)

* **存量 adopt 仓**：升级咬合点 = `install.sh --update`。升级后**首次** finish 若 baseline 落后 ⇒ FAIL 一次，按 FAIL 文案跑一次刷新（`--chain` / 空转态加 `--advance-baseline`）即过——期望的纪律咬合，发版说明须写明。
* **非结构类提交的保守成本**：任何已提交改动（含纯文档）都使 baseline 落后 ⇒ 下次 finish 前须跑一次 `--chain`（幂等、零漂移时仅重锚）。F26 保守 ratchet 的既有语义，本门不加宽。
* **适配器可用性耦合**：`--chain` 任一适配器失败 ⇒ exit 2 ⇒ finish 前置过不了。fail-closed 属预期；适配器需服务在跑的仓，收口日须先起栈（与 E2E 真跑前置同域）。**适配器根本未接**的仓走 `--advance-baseline` 通道（§2.1 空转态出路）。
* **`--dry-run` 不变**：仍短路在前置之前（现状语义，写进盲区）。**源包本仓自身**无 `.atlas/spec/structure/_meta.json` ⇒ 门对源仓恒 SKIP——冒烟验证只能 tmp 仓，不得误期 dogfooding 覆盖（评审 m4）。
* **执行耗时**：finish 增加两次本地 git 调用（rev-parse / status --porcelain）+ 一次 JSON 读，秒级以下。
* **长期维护**：无新配置、无新门组件；判据单源在 `refresh_structure.py`，退役路径 = 删检查 + 删 gates.md 行，生命周期与 F26 基线机制同寿。

### 2.4 评审采纳记录（tech-proposal-reviewer，2026-11-22，修后通过）

| 编号 | 意见 | 采纳 |
|---|---|---|
| C1 | 脏判据含暂存面 ⇒ 与 review 封口门互斥，修复指引死胡同 | §2.1 收窄为未暂存/未跟踪侧 + 盲区显式声明 + 证伪条件① + C1 形态端到端必测 |
| C2 | 空转态仓（无适配器）baseline 永不可达 ⇒ 永久锁死 | §2.1 `--advance-baseline` 扩越前置③ + 双通道文案 + 证伪条件④ + 空转态 e2e 用例 |
| M1 | `rev-parse` 失败混叠成「非 git」SKIP（fail-open） | FAIL ④：`.git` 存在性判非 git，`.git` 在而探测失败 ⇒ FAIL |
| M2 | ImportError 降级若 SKIP = 复制静默病 | 改 FAIL 指名重跑 install.sh + 降级分支钉 |
| M3 | 「不升格 WARN」声明与间接后果不符 | §2.2 次强反方明写间接阻断 + gates.md 盲区列同步 |
| M4 | `--force` 交互未定义 | §2.1 明写 force 不绕本门 + 用例钉 |
| M5 | 测试缺口（C1/C2 e2e、git 故障、降级、空转态、git identity；M196 应为代码变异） | §3 测试清单扩至 ~10 条；M196 重定义为「摘 `finish_task` 门调用 ⇒ FAIL 钉变绿」 |
| m1 | `clean_exempt_prefixes` 可抛 `LayoutError` | FAIL ⑥ 捕获归 FAIL |
| m2 | 占位检测漏 `—` 兜底 | FAIL ② 覆盖两种占位 |
| m3 | `load_meta` 的 `die()` 不可复用 | 门侧自行 `json.loads` |
| m4 | 源仓自身恒 SKIP，冒烟口径 | §2.3 注明 |

---

## 3. 改动面清单 (Affected Surface)

- [x] **代码逻辑**：`scripts/refresh_structure.py`（抽模块级 `sha_matches_prefix`；`maybe_advance_baseline` 改调 + `--advance-baseline` 扩越前置③；docstring 同步；脏路径扫描未抽——门侧脏面语义不同〔未暂存/未跟踪〕，改用 `git diff --name-only` ∪ `ls-files --others` 精确两查询，F26 ④ 内联扫描零改动）；`_support/workflow_finish.py`（`check_structure_freshness` + `_git_out` / `_load_refresh_helpers` / `_worktree_dirty_paths` + `finish_task` 接线 + `task.json.structure_freshness` 留痕）；`scripts/atlas_workflow.py`（`cmd_finish` 输出加「结构事实」行 + dry-run 文案补名）
- [x] **契约/文档**：`shared/gates.md` §2.1 新登记一行 + `refresh_structure` 行补 advance-baseline 扩展；`RUNBOOK.md` 收口节补硬校验说明与双通道；`docs/map/cli.md` 行描述同步（棘轮 `refresh_count_anchors --write` + `ledger_snapshot --write`〔M196 上限〕+ `test_map_anchors --fix` 符号锚已跑）
- [x] **测试防线**：`tests/test_atlas_workflow.py` +11 用例（SKIP 无 meta / SKIP 非 git / FAIL 坏 JSON / FAIL 占位×2 / FAIL stale〔M196 载体〕/ FAIL 未暂存脏三态〔未跟踪/未暂存改/暂存放行〕/ FAIL git 探测失败 / PASS 已锚干净 / **C1 形态 e2e** / ImportError 降级 FAIL / **空转态出路 e2e**）
- [x] **留出验证（§4.5）**：触发面核对 (b) 命中（见下）
- [x] **版本装配**：不涉及（纯 scripts/_support/tests 面，装配清单已覆盖）；CHANGELOG [Unreleased] 一条

---

## 4. 验证与测试结果 (Verification)

```bash
# 结构新鲜度族 + 全文件：tests/test_atlas_workflow.py 71 passed（60 既有保绿 + 11 新增）
# 判据单源保绿：tests/test_refresh_facts.py 21 passed
# 棘轮三面：tests/test_refresh_facts.py + test_canonical_consistency.py + test_map_anchors.py 52 passed
# 全量出厂套件（排除 playground 真跑口径）：1968 passed, 6 skipped, 0 failed（7m54s）
# 自检：python3 scripts/atlas_check.py --fast ⇒ OK（源仓形态，校验器未装配 ⇒ 各行 SKIP 属预期）
```

**手工冒烟（tmp 仓，真实 CLI 输出面）**：态1 baseline 全零占位 + HEAD 前移 ⇒ `FAIL` 带双通道命令；态2 重锚后 ⇒ `PASS`（`结构事实：PASS —— baseline ≡ HEAD（…）`）收口归档；态3 未跟踪 `stray.txt` ⇒ `FAIL` 指名且不指引提交。源包本仓自身无 `_meta.json` ⇒ 本门对源仓恒 SKIP（§2.3 m4 声明口径，冒烟只能 tmp 仓）。

**M196 四段协议**：注入（`finish_task` 门调用替换为恒 SKIP）→ 钉红（`test_finish_structure_blocks_stale_baseline` FAILED，变异被检出）→ 还原（`git diff --stat` 仅剩本批新增 114 行，逐字节一致）→ 复绿（1 passed）。

### 4.5 留出验证（系统性修复必填；`RFC-20261026-03`）

**触发面核对 (b)**：改门 + 判据，diff 落 `scripts/`、`_support/`、`tests/`、契约与 docs。两条命令原始输出（2026-11-22，可复算）：

```text
$ git diff --name-only HEAD
RUNBOOK.md
_support/workflow_finish.py
docs/map/adapters.md
docs/map/atlas-map.html
docs/map/cli.md
docs/map/gates.md
docs/map/index.md
scripts/atlas_workflow.py
scripts/refresh_structure.py
shared/gates.md
tests/test_atlas_workflow.py

$ python3 scripts/closeout_derive.py --root . --diff-base HEAD
本清单不含语义触发行，正文自查
本轮改动 12 个文件（atlas 自有对账面 5 个；业务面 7 个，只计条数）
[自动] 步骤 1 —— 触发：任一工作单元收尾；改契约 / 模板 / 校验器 / 脚本 / skill 瘦桩；改动触及核心业务链路 / 权限 / CI / 依赖 / 契约（判据指针：closeout.md §2 步骤 1）
[自动] 步骤 2 —— 触发：改契约 / 模板 / 校验器 / 脚本 / skill 瘦桩（判据指针：closeout.md §2 步骤 2）
[人工] 步骤 3 —— 触发：改动触及核心业务链路 / 权限 / CI / 依赖 / 契约（判据指针：closeout.md §2 步骤 3）
[人工] 步骤 5 —— 触发：改契约 / 模板 / 校验器 / 脚本 / skill 瘦桩（判据指针：closeout.md §2 步骤 5）
[人工] 步骤 7 —— 触发：改契约 / 模板 / 校验器 / 脚本 / skill 瘦桩（判据指针：closeout.md §2 步骤 7）
[WARN] atlas 自有面文件未命中任何触发行：_support/workflow_finish.py（触发表可能漏了一行，或这张表该扩了）
```

**留出集判定**：本批为新门首标（非既有门缺陷修复），锚 = §1 引子（收口静默通过无机器出声点，用户 2026-11-22 指认）+ 评审 C1/C2 两个独立 Critical（均经代码证实）。判据输出翻转钉 = M196 载体 `test_finish_structure_blocks_stale_baseline`（stale ⇒ FAIL 翻转）+ 空转态出路 e2e（FAIL→重锚→PASS 状态机翻转）；变异增量杀伤已实测（M196 注入即红）；三态结论 = **单案修复（无留出集）**——首标门无「修复前红样本」可比（修复前该面无任何判据输出），评审确认两 Critical 场景已折入必测。
