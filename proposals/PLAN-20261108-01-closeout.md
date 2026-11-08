# 收尾方案：留出验证态、duty-review 未提交文件、是否发版

> **状态注记（2026-11-08，定稿）**：最终采用**路径 A** = 保留 `单案修复（无留出集）`，依独立评审 `REVIEW-20261108-01` 确认；落点 = `RFC-20261107-01` §4.5 + `duty-review/QUEUE.md` 观察行。本文两条被否的设想如实记在此处：①「撤销单案修复、改判新增决策」——**已被否**，理由 = D156 三态是**闭集**，没有「新增决策」这一态；②「判据⑧ 本身可记 `闭族`」——**已被否**，理由 = 无子族锚（`bugs.md` 无同根段）且无族信号可翻转（判据⑧ / ⑦ 的增量不改变 `tests/test_duty_bug_families.py` 五段 verdict / 案数 / 最近日期 / 精确病案数）。以下正文保持评审时原样，不追改为「已修正」；判断 2 的缺口（须同批复冻测试）已兑现。上方 `状态：草稿（未提交）` 一行视为历史记录。

> 提案编号：`PLAN-20261108-01`
> 状态：**草稿（未提交）**，送独立评审；评审前不改 RFC / DESIGN / CHANGELOG / duty-review
> 关联：`RFC-20261107-01` / `REVIEW-20261107-01` / `DESIGN.md` D156 / D185 / D186 / D187
> 核对基准：`HEAD = cad2d5d`；工作树仅有 `duty-review/QUEUE.md`、`duty-review/bugs.md` 未提交
> 写法：每条事实主张后跟 `path:line`；核不到的显式写「核不到」，不做推断替代

## 0. 结论先行

| 判断 | 结论 | 一句话 |
|---|---|---|
| **1. 撤销「单案修复」态，改判「新增决策」、不补 QUEUE 行** | **需修正** | 方向在实质上可辩护，但 D156 只有三态、没有「新增决策」这一态；要改必须新开 D 行并改 5 处落点，不能在 RFC 里单方面声明不适用 |
| **2. `bugs.md` #50–#55 应当提交，且是发版前置** | **成立，但缺口一步** | 提交本身正确且是发版前置；但**单独提交不会转绿**——`test_current_real_file_baseline_frozen` 是「现行全文冻结」，必须在同一提交里复冻基线（`TODAY` / `FROZEN_BASELINE` / `exact` 三处） |
| **3. 本轮不发版** | **成立** | 发版门禁为硬 `RuntimeError`（`scripts/release.py:307-321`），无绕门开关；两个 playground 用例在干净 HEAD 上同样失败 |

**推荐的收尾组合**：判断 1 走「方案 A（保留单案修复 + 落 QUEUE 行）」；判断 2 按「bugs.md + 测试复冻」同批提交，QUEUE 刷新后单独或同批提交（见 §2.4）；判断 3 直接记录为「本轮不发版」。

---

## 1. 决策一：`§4.5` 的留出验证态

### 1.1 现状（`path:line`）

| 事实 | 出处 |
|---|---|
| RFC §4.5 现选的候选态 = **`单案修复（无留出集）`** | `proposals/RFC-20261107-01-impl-phase-discipline-and-skill-budget.md:208` |
| 判定权归独立 REVIEW，RFC 只给候选 | 同上 `:179` |
| 三个必填字段 = ① 评审确认 ② QUEUE 观察行（owner / 补验期限 / 升室判据 / 出室判据）③ 残留风险 | 同上 `:180` |
| ① 已满足（REVIEW 结论 go）；② **尚未落盘**；③ 已写 | 同上 `:184-186` |
| ② 的逐字行已备好，但整行里写的是「VETO_WORDS **4 条**」 | 同上 `:188-192`（批 3b 后实为 3 条，此行已过期） |
| 触发 (b) 机械命中，RFC 自认「实质误报」 | 同上 `:195-207`（结论在 `:207`） |

D156 对「单案修复」的强制要求（逐字）：

- `DESIGN.md:631`：「三态 `闭族` / `未闭族` / `单案修复（无留出集：评审确认 + QUEUE 观察行 owner/期限 + 残留风险）`」；同格写明「唯一判定记录 = 那份 RFC §4.5 + 其 REVIEW（不新增台账）」。
- `shared/gates.md:108`：「三态 = `闭族` / `未闭族` / `单案修复（无留出集）`（后者须评审确认 + QUEUE 观察行 owner/期限 + 残留风险入 RFC §4.5）……`bugs.md` 指针行 `- 留出验证：RFC-… / REVIEW-…`（无状态 / 无日期 / 无 `#NN`）」。
- 同口径复述：`proposals/README.md:46`、`proposals/TEMPLATE.md:88`、`duty-review/README.md:32`、`duty-review/README.md:55`、`shared/closeout.md:75`、`shared/independent-review.md:188`。

### 1.2 判断：需修正

三点核对结果：

1. **「撤销该态」与 D156 直接冲突**：D156 的三态是**闭集**，`gates.md:108` 用「三态 = …」限定，`proposals/README.md:46` 与 `TEMPLATE.md:88` 同样只列三项。「新增决策」不是其中任何一项，也没有「非修复类可豁免」的旁路。判定权在 REVIEW（`RFC:179`），但 REVIEW 只能在三态里选，不能发明第四态。
2. **「D186 是通用决策行 ⇒ 不适用单案」是实质理由，不是程序出口**：RFC 自己的措辞也是「机械命中、实质误报」（`:207`），并没有主张「不触发」。D156 对误报只要求**记录误报**（gates.md:108 的「记映射与误报」），未给「误报 ⇒ 免三态」的出口。
3. **是否要记「曾评估单案修复、为何不选」**：若走方案 B（改 D 行），**必须记**（D 行格式要求写清被否方案，`DESIGN.md:631` 的「③ 被否」列即此惯例）；若走方案 A，不需要。

没有任何机器判据依赖该态：`grep -rn "单案修复\|QUEUE" tests/*.py scripts/*.py` 零命中。唯一相关的机器面是指针行**形状**钉（`tests/test_duty_bug_families.py` 里的 19 条），它只约束「若写了指针行，不得带状态 / 日期 / `#NN`」，不要求必须写。⇒ 这是一处**纯契约面**改动，不涉及测试返工。

### 1.3 动作（精确到文件与行）

**方案 A（推荐，合规最小）**：保留 `单案修复（无留出集）`，把缺口补齐。

1. `proposals/RFC-20261107-01-impl-phase-discipline-and-skill-budget.md:191`：逐字行里「VETO_WORDS **4 条**精确短语」→ **3 条**（与 `tests/test_canonical_consistency.py:304-308` 现值一致）。
2. `duty-review/QUEUE.md`：把 `RFC:192` 的逐字行原样落盘（落盘时机依赖 §2 的未提交文件处理）。
3. `proposals/RFC-20261107-01-impl-phase-discipline-and-skill-budget.md:185`：状态由「尚未写入」改为「已落盘 + 验收 grep 结果」。
4. `duty-review/bugs.md` 自感知段（`:60` 段头下）补指针行：`- 留出验证：RFC-20261107-01 / REVIEW-20261107-01`（格式按 `shared/gates.md:108`：无状态 / 无日期 / 无 `#NN`）。

**方案 B（若要正式改判定）**：不是「撤销」，而是「修订 D156」——新增一条 D 行（编号按 `DESIGN.md` §12 顺延），并在**同一批**改 5 处落点：`DESIGN.md:631`、`shared/gates.md:108`、`proposals/README.md:46`、`proposals/TEMPLATE.md:88`、`duty-review/README.md:32`。D 行须写「曾评估 `单案修复` 为何不选」，并交独立评审。

### 1.4 前置条件

- 方案 A：`duty-review/QUEUE.md` 可写（当前有未提交改动，须先按 §2 处置，否则如 RFC `:185` 所述会把无关改动带进提交）。
- 方案 B：新 D 行获批 + 5 处落点同批改 + 独立评审；`shared/gates.md` 行数若增行，需同批更新地图锚（`docs/map/gates.md:18`、`docs/map/atlas-map.html:510`）。

### 1.5 风险 / 若被否的替代

- 方案 A 的代价：多一行 QUEUE 观察 + 一行指针；收益：零契约改动、零返工。**方案 B 的成本（1 条新 D 行 + 5 处契约 + 评审轮次）远大于省掉一行观察行**，也与 `shared/global-rules.md` §12「先量再动手」相悖。
- 方案 A 的风险：QUEUE 观察行的「30 天零假阳假阴」实际无人回看（既有机制惯性）；这不因本方案加剧，属 D156 既有盲区。
- 若评审否定方案 A：备选是判 `未闭族`（诚实但语义不符——本轮并未宣称修复任何族），不推荐。

---

## 2. 决策二：`duty-review` 两个未提交文件

### 2.1 现状（`path:line`）

| 事实 | 出处 |
|---|---|
| `bugs.md` 改动 = **新增 6 行**（#50–#55），无删改、无夹带 | `git diff -- duty-review/bugs.md`；新行位于 `duty-review/bugs.md:65-70`，段头 `:60` |
| 6 行字段一致：`〔日期 2026-11-07｜状态 开放｜族 判据可被形态满足｜证 issue #NN〕` | 同上 |
| `QUEUE.md` 改动 = **仅替换 1 行机器状态行** | `duty-review/QUEUE.md:71` |
| 该行现称「工作树干净」「未推提交 ×4（6ee6319/2fd6911/ac08af0/5571e53）」 | 同上 |
| 实际未推 = **7 个提交**（`git rev-list --count origin/main..HEAD`）；工作树**不干净**（两文件未提交） | 命令实测 |
| 冻结钉当前红：`自感知上报（§15 缺陷族）` 期望 8、实收 14 | `tests/test_duty_bug_families.py:56`；全量日志 `FAILED tests/test_duty_bug_families.py::test_current_real_file_baseline_frozen` |
| 冻结钉的 `TODAY = 2026-11-03`；新行日期是 2026-11-07（相对 TODAY 属「未来」⇒ 会额外触发 WARN） | `tests/test_duty_bug_families.py:47`、`:417`（`assert all(r["warns"] == [])`） |
| `exact` 断言只放行 E2E 段（#31），其余必须为 `None` | 同上 `:418-420` |

### 2.2 判断：成立，但缺口一步

- 「应当提交、且是发版前置」**成立**：该测试是「对现行 `bugs.md` 全文逐段冻结」（`:410-411` docstring），文件不改则长期红，红即挡 `pytest tests/`，也就是 `scripts/release.py:315-321` 的门。
- 「提交后转绿」**不成立**：冻结钉的语义是**每次 `bugs.md` 变化都同批复冻**。只提交 `bugs.md`，测试仍红（count 8 vs 14）。必须同批改三处，期望值为：

| 落点 | 现值 | 提交后应为 |
|---|---|---|
| `tests/test_duty_bug_families.py:47` `TODAY` | `2026-11-03` | `2026-11-07`（复冻日） |
| `:56` `自感知上报（§15 缺陷族）` | `(8, "2026-10-17", "升室候选")` | `(14, "2026-11-07", "升室候选")` |
| `:419-420` `exact` 断言 | 仅 E2E = 1，其余 `None` | 自感知上报 = **6**，其余（含 E2E = 1）不变 |
| `:410-412` docstring 复冻日期说明 | 2026-11-03 | 2026-11-07 |

（上表数值由 `family` 解析器按 `TODAY = 2026-11-07` 实算：自感知 count 14、last_date `2026-11-07`、verdict `升室候选`、warns 0、exact 6；其余四段不变。）

### 2.3 动作

1. 同批提交：`duty-review/bugs.md`（6 行）+ `tests/test_duty_bug_families.py`（上表 4 处）。
2. 提交前复跑：`pytest tests/test_duty_bug_families.py -q`，期望全绿。
3. 提交信息按 duty-review 惯例只写记录，不复述业务内容。

### 2.4 `QUEUE.md` 能否同批提交

- **是同一批产物**（同一份 2026-11-07 巡检记录），但不是同一件事：`bugs.md` 是存量记录，`QUEUE.md` 是机器状态快照。
- **现状不建议原样提交**：该行（`QUEUE.md:71`）称「工作树干净」「未推 ×4」，与 `HEAD = cad2d5d` 的实况（未推 7、工作树两文件未提交）不符；提交会把一条错误状态钉进历史。
- 建议二选一（**需拍板**）：
  - **A**：按现状重写该行（未推 7 / 工作树残留项写实）后与 `bugs.md` 同批提交；
  - **B**：`QUEUE.md` 本轮不动（保持你既有改动），只提交 `bugs.md` + 测试复冻；`QUEUE.md` 留到下次巡检整批刷新。

### 2.5 前置条件

- 无契约依赖（无测试读 `QUEUE.md`；`grep -rn "QUEUE" tests/ scripts/` 零命中）。
- 若选 §2.4-A，则 §1.3 方案 A 的第 2 步（落观察行）可以同批完成。

### 2.6 风险 / 若被否的替代

- 风险：复冻测试等于「按当前文本校准基线」，若 6 条记录本身有误，冻结也会把错误固化；本轮已核对 6 行字段格式一致、来源明确（`证 issue #50`–`#55`）。
- 若被否（不提交）：`test_duty_bug_families` 长期红，全量门恒不可过，发版永久阻塞；替代只能是「删掉 6 行记录」——会丢你现场采集的存量，不推荐。

---

## 3. 决策三：本轮不发版

### 3.1 现状（`path:line`）

| 事实 | 出处 |
|---|---|
| 发版门禁 = 先 canonical，再 `pytest tests/ -q`；非零即 `raise RuntimeError`，无 skip / force 参数 | `scripts/release.py:307-321` |
| 版本落点现值 `0.2.0-beta.31` | `package.json:3` |
| 根 `CHANGELOG.md` **无 `[Unreleased]`**，release 会静默跳过该步 | `scripts/release.py:277-288`（`if "## [Unreleased]" in ...`） |
| `docs/guide/changelog.md` 已有 `[Unreleased]`（`cad2d5d` 补） | 文件头部 `## [Unreleased]` |
| 两份 CHANGELOG 存在历史漂移：`beta.30` / `beta.31` 段正文不同（root 有 D184 标注与三条明细，docs 为精简版），且 root 缺 `[Unreleased]` | `diff CHANGELOG.md docs/guide/changelog.md` |
| 两例 playground 失败与本次改动无关：在干净 HEAD（`021bb38`，另建 worktree）单跑同文件 **2 failed**（`[FAIL] 停在 run 步；已完步:['pre']`） | 基线 worktree 实测 |
| 失败机制：`run` 步 = `atlas_check.py`（`scripts/atlas_verify.py:109-122`）；其内部嵌套 `pytest .atlas/tests` 上限 900s（`scripts/atlas_check.py:266`）；本轮观测到嵌套 pytest 长时间 0% CPU 停滞 | 会话内进程观测 + 上述行号 |
| 副本态不会递归：装配副本内 `install.sh` 不存在 ⇒ `pytestmark` 整体 skip | `tests/test_atlas_verify_playground.py:35`、`:114-119` |
| 具体卡在嵌套套件的哪条用例 | **核不到**（无 py-spy / 无法取 Python 栈；只知嵌套层整体非零/超时） |

### 3.2 判断：成立

- 绕门不可能：`run_test_suite()` 无 `--skip` / 环境变量开关，唯一出路是改代码绕过测试（`release.py` 或测试），属违规。
- 两例属**既有环境红**，不是本批引入：干净 HEAD 上同样 2 failed。
- 结论：本轮只做「收尾记录 + 未提交文件清理」，不发版。

### 3.3 动作

1. 不跑 `release.py`、不打标、不推。
2. 在 `duty-review/bugs.md` 或下次巡检里登记「playground 两例既有环境红（复现于 `021bb38`）」——**建议登记，属于流水线自感知上报的典型现场**（`shared/global-rules.md` §15）。
3. 若要定位：让嵌套套件单独跑并输出 `-v` 到日志，再取最后一个通过用例的下一条；本轮未做。

### 3.4 前置条件（将来发版时）

见 §4。

### 3.5 风险 / 若被否的替代

- 风险：两例长期红会让「全量绿」失去信号意义，后续真回归可能被当成既有红忽略。→ 建议至少登记一条观察（§3.3-2）。
- 若评审认为「可以发版」：唯一合规路径是把两例修绿，或给出「该两例不计入发版门」的契约依据——后者目前**不存在**（`release.py:316` 跑整个 `tests/`）。

---

## 4. 发版前置清单（将来执行，按依赖顺序）

1. `duty-review/bugs.md` 6 行已提交 + 测试已复冻（§2.2），`test_duty_bug_families` 绿。
2. playground 两例绿（或至少有定位结论 + 契约依据排除）。
3. 根 `CHANGELOG.md` 补 `## [Unreleased]`，内容与 `docs/guide/changelog.md` 同口径（否则 `release.py:280` 不生成版本段，GitHub Release 正文会空）。
4. 决定两份 CHANGELOG 的 beta.30/31 段漂移是否对齐（当前无测试约束，但发版会同时写两份）。
5. 工作树干净；`origin/main..HEAD` 的未推提交数确认。
6. 版本推导：现 `0.2.0-beta.31`（`package.json:3`）⇒ 预期 **`0.2.0-beta.32`**（按 prerelease 自增）。
7. 网络代理 7897 + npm registry 轮询（`atlas-release` 技能描述口径；该技能文件不在仓内，细节**核不到**）。

---

## 5. 剩余悬置项现状

| 项 | 现状 | 出处 |
|---|---|---|
| **C1** 压缩后规则是否丢失 | **未取证**：本机 `~/.claude` 无 `projects/` transcript，`hooks/` 仅 `context-mode-cache-heal.mjs`；Trae CN 会话无法确定性触发压缩 | `RFC:255-260` |
| **C3** worktrunk `wt merge` / `hash_port` | **不采纳**：安装实测失败，整条删除，并入备选 H | `RFC:262`（§6.2 标题）、`:287` |
| **C2 / C4** | **核不到**：本 RFC 与 `REVIEW-20261107-01` 全文无 `C2` / `C4` 编号；可能来自其他文档，需你指路径 | `grep -rn "C2\|C4"` 两文件零命中 |
| **批 4**（§14 六条标 Floor/Reflex/Finish） | **延后**：19,821 字符 + 46 标签 + 42/70 图例 ⇒ 余量仅 63–91；无第二消费方 | `RFC:135`、`:137` |
| **「7 条不采纳」** | **核不到「7」**：§2.2 实为 **8 条**备选（A `:80` – H `:94`）：整条不采纳 3（B / G / H）、撤回 3（A / D / E）、降格 1（C，降为 B 档证据命令）、改形 1（F，改为扩步骤 4） | `RFC:80-94` |

---

## 6. 四条盲区（沿用 `RFC:244-250` 既有口径，不升格）

1. **内容存在 ≠ 模型会读**：references 会被装配，但无证据证明压缩后模型会打开（`RFC:246`）。
2. **外移是否丢约束无机器证明**：判据⑧只数字符，不校验被移内容（`RFC:247`）。
3. **字符预算可被规避**：压缩空白 / 塞 frontmatter / 整段搬进单个 references 均可通过（`RFC:248`）。
4. **一次性人工核对不可复算**：无留痕格式、无二次执行路径（`RFC:249`）。

以上四条均为**已知盲区**，本方案不据此推断任何「已保全 / 已生效」结论。

---

## 7. 需用户拍板

1. **判断 1 走 A 还是 B**：A = 保留 `单案修复` + 落 QUEUE 行（推荐，零契约改动）；B = 新开 D 行修订 D156，允许非修复类新增决策不走三态（成本高，需评审）。**推荐 A。**
2. **`QUEUE.md` 怎么处置**：① 刷新机器状态行后与 `bugs.md` 同批提交；② 本轮不动，只提交 `bugs.md` + 测试复冻。**推荐 ①（一次巡检整批落）**；若选 ②，§1.3 方案 A 的第 2 步必须顺延。
3. **是否同意「提交 `bugs.md` 必须同批复冻测试」**（§2.2 表）。**推荐同意**；否则该测试不会转绿。

（实现细节不上抛：行号、命令、期望值均已写在上文，评审可直接复跑。）

---

## 8. 评审入口（建议核对清单）

- [ ] 判断 1：D156 是否真的封闭三态（`DESIGN.md:631` / `gates.md:108` / `proposals/README.md:46` / `TEMPLATE.md:88`）——若无第四态，方案 A 是否唯一合规最小解。
- [ ] 判断 2：复冻四处的期望值是否可由 `duty-review/families.py` 复算（命令：按 `TODAY = 2026-11-07` 跑 `test_current_real_file_baseline_frozen`）。
- [ ] 判断 2 附加：`QUEUE.md:71` 的「未推 ×4 / 工作树干净」是否与原样提交冲突。
- [ ] 判断 3：`release.py:307-321` 是否确无绕门开关。
- [ ] 全篇：是否有「核不到」被写成结论。
