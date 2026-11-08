# 实现期纪律收敛 + SKILL 体积预算 + 术语表禁用别名

> 提案编号：`RFC-20261107-01`
> 提案作者：@sunwenzhe
> 关联状态：批 0 评审 **go**（`REVIEW-20261107-01`）；批 1 已交付（`6ee7e43`）；批 2 已交付（`021bb38`）；批 3 进行中
> 影响范围：核心契约 (shared) | 环契约 (rings) | 测试 (tests) | 模板 (templates)
> 决策行：D185 / D186 **已定案**（`REVIEW-20261107-01`）；D187 **已定案**（批 2 落地，2026-11-07）
> 关联评审：`proposals/REVIEW-20261107-01-impl-phase-discipline-and-skill-budget.md`（结论 go）

---

## 1. 现象与取证 (The Problem & Evidence)

### 1.1 触发形态（抽象）

* **规则 / 环节**：
  - `shared/global-rules.md`：缺「实现期纪律」条款；
  - `shared/closeout.md`：步骤 4 只覆盖缺陷修复，feature / refactor 收口无改动面核对；
  - `shared/independent-review.md` §10.4 与 `shared/single-source.md`、`shared/layout.md`：边界表述在「放开实现期」后自相矛盾；
  - `skills/*/SKILL.md`：无体积预算，`frontend-design` 单文件 22,590 字符；
  - `rings/prd/reference.md` §九 与 `templates/prd/global.md`：术语表列数不一致，且无「禁用别名」。
* **触发时机**：Trellis 实现期、收口（`atlas closeout`）、skill 装配、PRD 写术语表。
* **具体行为**：Atlas 在实现期只有提醒性缺口，没有可执行的核对路径；能力宣称与新增纪律冲突；唯一重 skill 在压缩场景下有截断风险（外部实测，仓内无证据）；术语表无生产方/消费方协议。

### 1.2 客观证据与日志 (Minimal Evidence)

```text
$ wc -m < skills/frontend-design/SKILL.md
22590
$ wc -c < skills/frontend-design/SKILL.md
41453
$ grep -h '^#' skills/frontend-design/references/*.md | wc -l
159
$ grep -h '^#' skills/frontend-design/references/*.md | sort | uniq -d | wc -l
0
$ awk -F'|' 'NR>=139 && NR<=141 {print NR": "NF-2" 格"}' templates/prd/global.md
139: 3 格
140: 3 格
141: 3 格
$ awk 'END{print NR}' tests/test_*.py >/dev/null; ls tests/test_*.py | wc -l
57
$ python3 -c "print(len(open('shared/gates.md').read().splitlines()))"
174
```

能力宣称与触发表核对（**只记落点与差异摘要，不复制正文**；正文以各文件为准）：

| 落点 | 差异摘要 | 处置 |
|---|---|---|
| `docs/design/overview.md:78` | 流程节点把业务代码整体判给执行器，边界表述绝对化 | 改写 |
| `shared/independent-review.md:192` | 引用 `apply` 旧口径后落「实现过程仍不介入」 | 改写 |
| `shared/independent-review.md:225` | 以「不进本契约」界定实现期代码规范；对象写成「实现过程」 | 外科改写（对象收窄为业务代码规范的判定） |
| `shared/closeout.md:149` | 硬边界首句否掉实现期规范复盘 | 补澄清（首句保留） |
| `shared/single-source.md:43` | 归属句把「编码规范」整体排除 | 改写（排除对象收窄为判定权） |
| `shared/layout.md:97` | 同句 | 同批改写 |
| `README.md:123` | 实现期归 Trellis，Atlas 不侵入业务代码实现 | 复核为真，不改 |
| `shared/closeout.md:20` | 缺陷修复类任务 → 4 | 保留，另加实现类触发行 |
| `shared/closeout.md:25` | 任一工作单元收尾 → 1 | 不动（实现类行的步骤 1 由它覆盖，不重复声明） |

### 1.3 引子族锚（D156 触发面 (a)）

本 RFC **不是** `duty-review/bugs.md` 的同根归纳：事项来源是外部公开实践 + 维护者现场观察（边界表述冲突、体积、术语表列数），属于「能力边界缺口 / 宣称漂移」，不是缺陷复发链。因此触发面 (a) 不成立；触发面 (b) 的原始输出见 §4.5。

---

## 2. 决策与权衡 (The Decision & Trade-offs)

### 2.1 核心定案 (The Decision)

| # | 定案 |
|---|---|
| **I1** | `skills/*/SKILL.md` 字符数 **< 20000**（常量 `SKILL_BUDGET_CHARS = 20000` 写在测试内，不读被审文件）；判据⑧只有一条字符数断言，**不建 manifest / hash / 指针校验**。批 1 外移 ≥2,590 字符；`§4.7`（`### 4.7 版面纪律（硬规则）`）与 `§4.11`（`### 4.11 页面主题锁`）不得外移；内容保全核对基线与方法见 §4.3。 |
| **I2** | `shared/global-rules.md` 新增 **§18「实现期假设处置」**；三句语义（假设归 Trellis 任务 Plan / Design、命中 §7 四条签名即停、会改 AC / 范围 / 可见行为回流 PRD）以 **D186 ②** 为准。**本 RFC 只记落点与语义边界，不复制契约正文。** |
| **I3** | `shared/closeout.md` 步骤 4 分 A / B 档（A 档 = 原 7 检查点，不动；B 档 = 4 项，测试反模式只作证据观察、不判分）；触发表新增 **「实现类任务（feature / refactor，非 bug fix）→ 4（B 档）」**，标「语义触发行，不自动派生」。**步骤 1 已由既有「任一工作单元收尾 → 1」覆盖，不重复；步骤 7 归提交纪律。** 正文口径同 D186。 |
| **I4** | 能力宣称 5 处改写 + 1 处澄清（落点见 §1.2；`README.md:123` 不改）。`VETO_WORDS` 只加 3 条精确短语（清单见 §4.6）；**不登记** `closeout.md:149` 与 `README.md:123` 的保留句；**不加** D185 / D186 豁免锚（理由见 §4.6）。 |
| **I5** | 术语表增第四列「禁用别名」：模板表头、分隔行、占位行同批改 4 格；契约写明「旧三列合法、新写四列」；生产方 `atlas-prd`、消费方 `atlas-e2e` / `atlas-apply` 各加先读；**不新增 `validate_prd` 判据**，存量项目不迁移。 |

### 2.2 考虑过的备选方案及否定理由 (Considered Alternatives)

* **备选 A：`references/_manifest.json` + 四条件判据**（路径 / 锚点 / 反向不存在 / 指针双向）
  * *否定理由*：为外移 2,590 字符引入新机器数据结构、指针分类与四条判据，维护面远大于收益；且属 D131 明确拒绝的「脆弱机器强制」形态。已撤回。
* **备选 B：影响面对账（`impact_reconcile`）扩到所有实现类改动**
  * *否定理由*：`impact_report.py` 把 `git diff` 并入 `touched_files`，报告后置生成时漏报恒为零；前置生成时测试/文档/锁文件在预测集外 ⇒ 恒假 miss；无 `impact.json` 仍 exit 3。维持现状。
* **备选 C：纯格式改动机器门（`git diff -w`）**
  * *否定理由*：只能识别空白差异；引号风格、import 排序、prettier 重排仍为非空 diff；覆盖面不足以支撑门，降为 B 档证据命令。
* **备选 D：体量阈值门**
  * *否定理由*：无实测分布，预填阈值违反「先量再动手」；撤回。
* **备选 E：测试文件存在性门**
  * *否定理由*：以「东西在不在」代替判据，D131 已否决；撤回。
* **备选 F：新增步骤 12**
  * *否定理由*：编号新增但无派生路径，且会与 D131 已裁决的步骤 4 并存；改为扩步骤 4 并分档。
* **备选 G：Reflex 豁免台账 / 视觉冷读 / hover 探针**
  * *否定理由*：台账无读取方；冷读落错 skill（`atlas-design-review` 审决策而非视觉）；hover 当前不可稳定复现。均不采纳。
* **备选 H：worktrunk `wt merge` / `hash_port`**（整条不采纳）
  * *否定理由*：改历史、与提交纪律冲突；D148 不走本地 dev server。另：安装实测失败（§6.2），`wt` 无法进入验证面。

### 2.3 必须警惕的刺痛代价与兼容性影响 (Trade-offs)

* **零新增机器门**：本 RFC 唯一的机器判据增量是判据⑧（字符上限）；语义拦截仍靠实现审查（`impl_review.llm` 为空时 SKIP）。
* **无内容保全证明**：外移后模型是否读取 references 不可机证（见 §5）。
* **B 档无退出码**：4 项均为人工核对项，不产生 FAIL。
* **模板四列不迁移**：存量项目 PRD 保持三列合法；`.atlas/` 刷新、`product/` 永不覆盖（`shared/layout.md:9-14`）。
* **地图行数**：`shared/gates.md` 174 → 175，须同批改 `docs/map/gates.md:18` 与 `atlas-map.html:510`。

---

## 3. 改动面清单 (Affected Surface)

- [ ] **核心契约**：`shared/global-rules.md`（新增 §18）、`shared/closeout.md`（步骤 4 分档 + 触发表 + `:149` 澄清）、`shared/independent-review.md`（`:192`、`:225`）、`shared/single-source.md:43`、`shared/layout.md:97`、`shared/gates.md` §2.5 一行
- [ ] **环契约**：`rings/prd/reference.md:86` 术语表四列；`skills/atlas-prd/SKILL.md:14`、`skills/atlas-e2e/SKILL.md`、`skills/atlas-apply/SKILL.md` 先读
- [ ] **模板**：`templates/prd/global.md:139-141` 四列（表头 / 分隔 / 占位同批）
- [ ] **技能正文**：`skills/frontend-design/SKILL.md` 外移 ≥2,590 字符（`§4.7/4.11` 保留，核对方法见 §4.3）；**只并入既有 `references/*.md`，不新增文件**；若必须新增，同批改 `references/README.md:39-42` 与 `SKILL.md:33`、`:39`
- [ ] **测试防线**：`tests/test_canonical_consistency.py` 新增判据⑧（`SKILL_BUDGET_CHARS`）、`VETO_WORDS` / `VETO_EXEMPT_ANCHORS` 常量
- [ ] **留出验证（§4.5）**：三态候选 = `单案修复（无留出集）` + 必填字段（评审确认 / QUEUE 观察行 / 残留风险）+ 锚→路径族映射（见 §4.5）
- [ ] **地图与计数器**：`docs/map/gates.md:18`（174→175）、`:20`（56→57）、`docs/map/atlas-map.html:510`（174）
- [ ] **观察室**：`duty-review/QUEUE.md`（批 3 写入一行；行文见 §4.5②）
- [ ] **决策记录**：`DESIGN.md` D185 / D186 **已定案**（`REVIEW-20261107-01`）；D187 **已定案**（批 2 落地）；D131 行末定案句注记

**明确不做**：`README.md:123` 不改；不新建 `_manifest.json`；不新增校验器；不改 `scripts/`。

---

## 4. 验证与测试结果 (Verification)

### 4.1 四批与预期红

> **批 1–3 前置**：**D185 / D186 已定案**（`REVIEW-20261107-01`，2026-11-07），批 1 可开工；D187 **已定案**（批 2 落地）。Q2 的 QUEUE 行补丁在批 3 落盘，不阻断批 1。

| 批 | 内容 | 预期红 |
|---|---|---|
| **0** | 本 RFC + D185/D186/D187 + `docs/map/gates.md:20` 56→57 + C1 取证 + worktrunk 安装实测 | 无（纯文档 / 地图陈旧行）；worktrunk 安装失败，C3 转不采纳（§6.2） |
| **1** | I1 拆分（**不加判据⑧**）；附外移前后 section 清单（三列，见 §4.3）；**只并入既有 `references/*.md`，不新增文件** | 无；收尾 `wc -m` < 20000；`§4.7` / `§4.11` 与基线 `diff` 为空（§4.3） |
| **2** | 判据⑧（常量 + 单一断言）+ I5 | 无；若批 1 未完成则判据⑧红 |
| **3** | I2 + I3 + I4 + §2.5 行 + `VETO_WORDS` + **地图 174→175 同批** + `duty-review/QUEUE.md` 观察行 1 行 | 无；漏改地图 ⇒ `docs/map/gates.md:18` / `atlas-map.html:510` 红；漏改任一宣称或误登保留句 ⇒ 判据⑦红；`grep -F '实现期纪律判据上线观察（RFC-20261107-01' duty-review/QUEUE.md` 期望 **1 行** |
| **4（延后）** | B1′：`SKILL.md §14` 六条硬检查标 Floor / Reflex / Finish | 不执行；理由与重开条件见下 |

**批 4 延后（2026-11-08 定）**：现 `skills/frontend-design/SKILL.md` 19,821 字符，距判据⑧上限 20,000 仅余 179；批 4 最少要 46 字符（六条标签）+ 图例 42（紧凑）或 70（完整），做完余量只剩 63–91，之后任何措辞增补都会被预算判据卡住。且三级标注除 §14 清单本身**无消费方**，产出无法被验证。**重开条件**：出现第二个消费方，或预算上调有依据（实测分布支撑）。

### 4.2 批 0 验证命令

```bash
python3 -c "print(len(open('shared/gates.md').read().splitlines()))"   # 期望 174（批 3 后 175）
grep -n '(57 文件)' docs/map/gates.md
git diff --name-only
python3 scripts/closeout_derive.py --diff-base HEAD --root .
```

---

### 4.3 内容保全核对（批 1 专用，可复算）

* **基线**：批 0 提交 `c0acc61` 中的 `skills/frontend-design/SKILL.md`，即 `git show c0acc61:skills/frontend-design/SKILL.md`。
* **两段锚**：`### 4.7 版面纪律（硬规则）`、`### 4.11 页面主题锁`；每段范围 = 从该标题行到下一个同级或更高级标题之前。
* **方法**（批 1 收尾执行，输出贴进批 1 提交说明）：
  1. `git show c0acc61:skills/frontend-design/SKILL.md > /tmp/skill.before.md`
  2. 从 before / after 各抽两段，分别落 `/tmp/sec47.before` / `/tmp/sec47.after` / `/tmp/sec411.before` / `/tmp/sec411.after`
  3. `diff -u /tmp/sec47.before /tmp/sec47.after` 与 `diff -u /tmp/sec411.before /tmp/sec411.after` **均须为空**
  4. `wc -m skills/frontend-design/SKILL.md` **须 < 20000**
* **section 清单（固定三列，行数 = 实际外移 section 数）**：

| before heading（原文件） | after heading（目标文件） | target file |
|---|---|---|
| `## …` | `## …` | `references/<name>.md` |

> 批 1 **只并入既有 `references/*.md`，不新增文件**。若实际必须新增：同批更新 `references/README.md:39-42`（11 中文 / 43 英文 / 54 文件）与 `SKILL.md:33`、`:39`，并在此清单登记；否则这三处保持原值。

### 4.4 批 3 §2.5 新增行（逐字候选，批 3 直接落笔）

| 门 | 对账平面 | 查什么 | **不查什么** | 预算 + 触发物 | 假绿测试（等级） |
|---|---|---|---|---|---|
| **实现期假设处置与收口分档**（`global-rules.md` §18 + `closeout.md` 步骤 4 B 档，2026-11-07，`RFC-20261107-01` / D186） | 实现期假设 ⇔ 任务记录 / 收口证据 | `[语义]` ① 实现期新假设落 Trellis 任务 Plan / Design（不另建台账）；② 命中 §7 四条签名动作 ⇒ 先停并取确认；③ 会改变 AC / 范围 / 用户可见行为 ⇒ 回流 PRD 决策；④ 实现类任务（feature / refactor，非 bug fix）收口按步骤 4 B 档 4 项自证：可追溯性 / 纯空白证据命令 / 纯后端验证命令 / 测试反模式（**只作证据观察，不判分**） | 假设**是否真被记录**（无机器判据）；B 档 4 项证据**是否充分**（归独立审查）；测试反模式**是否成立**（只观察）；§7 四条签名之外的越权（归用户确认门） | 实现期任务落笔 / 收口时（人按触发表自查） | **不设机器判据**（语义项，`3509 §96`）；B 档无退出码；不新增校验器 |

---

### 4.5 留出验证（D156，`shared/gates.md` §2.5）

**先分开两件事**：

* **判定权**：三态（`闭族` / `未闭族` / `单案修复（无留出集）`）**只能由独立 REVIEW 判定**；本节只给候选结论与证据，**不构成判定**。
* **必填字段**（D156；`shared/gates.md:108` + `DESIGN.md:631`）：① 评审确认；② QUEUE 观察行（观察项 / owner / 补验期限 / 升室判据 / 出室判据，逐字文见下）；③ 残留风险。

| 必填项 | 当前状态 |
|---|---|
| ① 评审确认 | **已确认：态 = `单案修复（无留出集）`**（独立只读评审 `REVIEW-20261108-01`，非作者自审、非方案方转录；全文见下） |
| ② QUEUE 观察行 | **逐字行见下，尚未写入** `duty-review/QUEUE.md`。**未写入原因（批 3 再次确认）**：该文件存在用户既有未提交改动；写入一行会把无关改动连带进本次提交，故批 3 继续「不动、不提交」，由维护者在该文件改动处理完后写入。**行落盘前 D156 只能标「候选，待行落盘」**；行落盘后验收 = `grep -F '实现期纪律判据上线观察（RFC-20261107-01' duty-review/QUEUE.md` 期望 **1 行**。 |
| ③ 残留风险 | ① 判据⑧可被规避（压缩空白 / 塞 frontmatter / 整段搬进单个 references）；② 外移内容是否被模型读取无机器证明（§5 盲区 1–2）；③ 判据⑦新增词若误伤未来合法表述，需人工豁免；④ B 档 4 项无退出码，可能流于形式；⑤ I5 四列模板对存量三列项目存在不迁移窗口。 |

**① 评审确认全文（`REVIEW-20261108-01` 原样转录）**：

**已确认：态 = `单案修复（无留出集）`**（独立只读评审 `REVIEW-20261108-01`，非作者自审、非方案方转录）

独立评审对「确无可行留出集」的确认：**成立**。理由三条，逐条对应 D156 留出独立性：

(a) 无子族锚 —— `duty-review/bugs.md` 中没有与本 RFC 同根的缺陷族记录（`RFC:1.3` 已认定触发面 (a) 不成立），不存在可供挂「族内留出案」的段。

(b) 无族信号可翻转 —— D156 留出独立性 ①要求「verdict / 案数 / 最近日期 / 精确病案数」至少一项发生翻转。本 RFC 的机器判据增量只有判据⑧（`skills/*/SKILL.md` < 20000 字符，单条断言）与判据⑦（`VETO_WORDS` 新增 3 条精确短语），B 档 4 项无退出码，`tests/test_duty_bug_families.py` 的五段 verdict 不受本 RFC 影响 ⇒ 可翻转信号为零。

(c) 全集即被测对象 —— 本次被改文件（`skills/frontend-design/SKILL.md`、5 处能力宣称、模板 / 环契约）本身就是被测对象，不存在「未被本批改动的同族样本」；迁移由本批自己执行，独立性 ②（变异增量杀伤：既有钉全绿而留出案红）与 ③（结构不可达：夹具不可由既有钉夹具只改日期串 / 通道 / 增删行得到）逐条不成立。

边界声明：

- 本确认**不引用** `REVIEW-20261107-01` 的批 1「go」代替。该 REVIEW `:5` 的 go 只回答「批 1 可否开工」，其 `:26` 明写「在行落盘前，D156 只能标『候选，待行落盘』」，不构成三态判定。
- 触发面 (b) 的机械命中与「实质误报」判读已记于 `RFC:195-207`；按 `shared/gates.md:108`「记映射与误报」记录，**不改变**态判定。
- 因触发面 (a) 不成立，`bugs.md` 本轮**不新增**指针行；若日后挂入某缺陷族，再按 `shared/gates.md:108` 补 `- 留出验证：RFC-20261107-01 / REVIEW-20261108-01`（无状态 / 无日期 / 无 `#NN`）。
- 唯一判定记录 = 本 RFC §4.5 + `REVIEW-20261108-01`（不新增台账）。

**② QUEUE 观察行（逐字；仅作待落盘记录，不写入 `duty-review/QUEUE.md`；待用户确认 duty-review 未提交改动后落盘）**：

```text
- **实现期纪律判据上线观察（RFC-20261107-01，2026-11-07）**：观察项 = 判据⑧（`skills/*/SKILL.md` < 20000 字符，常量 `SKILL_BUDGET_CHARS`）与判据⑦（`VETO_WORDS` 新增 3 条精确短语：「不碰业务实现」「实现过程仍不介入」「不介入实现过程」）上线后的假阳 / 假阴，含 §4.6 明确不登记的保留句（`shared/closeout.md:149`、`README.md:123`）是否被误伤、旧宣称是否漏放；owner = @sunwenzhe；补验期限 = 2026-12-07（自 2026-11-07 起 30 天；期间若 `shared/` 或 `skills/*/SKILL.md` 发生相关变更，取变更日与 2026-12-07 中较早者）；升室判据 = 满足任一即升室按 DR2 议调：① 出现 ≥1 例判据误伤合法表述（假阳）且需人工豁免；② 出现 ≥1 例旧宣称漏放（假阴）且需改判；③ `VETO_WORDS` 在观察期内需第二次增删；出室判据 = 至 2026-12-07 且以下三条同时成立即归档、D156 转「定案」：① 零假阳 / 零假阴（或全部为已按 §4.5「锚→路径族」映射记录且未改判据的误报）；② 判据⑧ / 判据⑦ 未被回退或放宽；③ 本行在 `duty-review/QUEUE.md` 留存满期。
```

* **触发面 (a)**：§1.3 已述，非 `bugs.md` 同根归纳 ⇒ 不触发。
* **触发面 (b)**：本 RFC 改门 / 契约判据 ⇒ 机械命中。按 §2.5 要求记「锚 → 路径族」映射与误报：

| 锚（判据落点） | 路径族（DR4 口径 A 聚类单元） | 近 30 天 fix 类提交触达次数 | 误报判读 |
|---|---|---|---|
| 判据⑧ / 判据⑦（`tests/test_canonical_consistency.py`） | `tests/` | 7 | 判据高频扩展入口，非同一病根复发 |
| 判据⑦ 扫描面 + 5 处宣称 | `shared/` | `gates.md` 60 / `independent-review.md` 13 / `closeout.md` 8 / `single-source.md` 3 / `layout.md` 1 | 门登记总账与契约台账，触达来自不同主题的新增 / 修订 |
| 步骤 4 范围 / `:149` 澄清 | `shared/` | `closeout.md` 8 | 同上 |
| §2.5 新增行 | `shared/` | `gates.md` 60 | 同上 |
| I5 术语表四列 | `templates/` / `rings/` / `skills/` | `templates/prd/global.md` 0 / `rings/prd/reference.md` 6 / `skills/*` 1 | 模板与环契约编辑，非缺陷复发 |
| 文档宣称 | `docs/` | `atlas-map.html` 30 / `changelog.md` 35 / `map/gates.md` 8 / `design/overview.md` 2 | 地图与 changelog 是交付面 |

  * 计数命令：`git log --since="30 days ago" --name-only --pretty=format: --grep='fix\|修\|红\|回归' | sed '/^$/d' | sort | uniq -c | sort -rn`
  * **误报结论**：口径 A 只数「同一路径 30 天内被 fix 类提交触达 ≥3 次」，**不区分病根**；本 RFC 的锚落在台账类 / 交付面文件上，族计数必然 ≥3，**属机械命中、实质误报**。口径 B（`bugs.md` 段 + 段首同根归纳）未命中（§1.3）。
* **三态候选（只候选）**：`单案修复（无留出集）`。理由：判据⑧是新增静态上限，无既有判据可翻转；判据⑦只改常量集合、不改判定逻辑；B 档无退出码。若 REVIEW 认定机械命中即须按触发态处理，则**本 RFC 无可行留出集**（迁移由本批自己执行，独立性三条均不成立），应由 REVIEW 明确驳回或接受。
* **原始输出**（批 0 实收）：

```text
$ git diff --name-only
DESIGN.md
docs/map/gates.md
duty-review/QUEUE.md
duty-review/bugs.md

（注：`proposals/RFC-20261107-01-...md` 为新增未跟踪文件，`git diff --name-only` 不列；`duty-review/QUEUE.md` / `duty-review/bugs.md` 是批 0 之前既有的他人改动，不随批 0 提交。）

$ python3 scripts/closeout_derive.py --diff-base HEAD --root .
本清单不含语义触发行，正文自查
本轮改动 5 个文件（atlas 自有对账面 1 个；业务面 4 个，只计条数）
[自动] 步骤 1 —— 触发：任一工作单元收尾；改 `DESIGN.md` §12 决策（尤其含「被否：」的行）/ 撤回或收窄某项能力宣称（判据指针：closeout.md §2 步骤 1）
```

* **D 行状态**：D185 / D186 **已定案**（`REVIEW-20261107-01`）；D187 **已定案**（批 2 落地）。D156 = `单案修复（无留出集）`：三态已由独立评审 `REVIEW-20261108-01` 明示确认，该确认独立作出、不引用 `REVIEW-20261107-01` 的批 1 go；现状记「三态已确认，QUEUE 观察行未落盘」，不得标「候选」。QUEUE 观察行落盘且 `grep -F '实现期纪律判据上线观察（RFC-20261107-01' duty-review/QUEUE.md` 返回 1 行后，转「定案」。

### 4.6 批 3 的 `VETO_WORDS`（逐字清单）

```python
VETO_WORDS = [
    "不碰业务实现",              # docs/design/overview.md:78
    "实现过程仍不介入",          # shared/independent-review.md:192
    "不介入实现过程",            # shared/independent-review.md:225
]
```

* **不登记** `不做业务代码实现期规范复盘`（`shared/closeout.md` 终稿保留该句）；**不登记** `不侵入业务代码实现`（`README.md:123` 保留）；**不登记** `编码规范不由 atlas 收口`——该句为真（`shared/single-source.md:43` / `shared/layout.md:97` 定稿保留），禁止它属过度 sweep。登记任一句都会在批 3 首次跑判据⑦时自红。
* **不加 D185 / D186 到 `VETO_EXEMPT_ANCHORS`**：判据⑦扫描面 = `docs/**.md`（除 `.vitepress`）+ `shared/**.md` + 顶层 `README.md`（`tests/test_canonical_consistency.py:311-328`）；`DESIGN.md` 与 `proposals/**` **不在扫描面**，加了也对它们无效。5 处宣称同批改写后不留 veto 短语，无需豁免锚；若批 3 实测某行必须保留短语，再在该行同处加 `D186` 指针并单独议锚。
* **顺序**：改写与登记**同批**（先改后登记），否则未改写的旧句会让判据⑦在批 3 中途红。

---

## 5. A1 四条盲区（显式登记，不假装有机器证明）

1. **内容存在 ≠ 模型会读**：references 会被 `install` 装配，但无证据证明压缩后模型会打开它们。
2. **外移是否丢约束无机器证明**：判据⑧只数 SKILL.md 字符，不校验被移内容；只能靠批 1 的一次性人工核对。
3. **字符预算可被规避**：压缩空白、塞 frontmatter、把内容整体挪进单个 references 文件，均可通过。
4. **一次性人工核对不可复算**：无留痕格式、无二次执行路径；清单只进提交说明与本 RFC 附注。

---

## 6. 取证附录（批 0 内完成）

### 6.1 C1：压缩后规则是否丢失 —— **未取证**

- 本机 `~/.claude` 无 `projects/` transcript 存储；`hooks/` 仅 `context-mode-cache-heal.mjs`，未见 `SessionStart` / `PreCompact`。
- Trae CN 会话内无法确定性触发上下文压缩；无「压缩前 / 压缩后」的 additionalContext 快照。
- **缺什么**：①可复现的 compact 触发途径；②压缩前后的规则快照；③「规则是否仍在」的判读口径。
- **结论**：C1 保持待取证，不进入契约；不编造实录。

### 6.2 C3 worktrunk —— **不采纳（安装实测失败）**

```text
$ command -v wt
（无输出）
$ brew list --formula | grep -x worktrunk
（无输出）
$ ls -d /opt/homebrew/Cellar/worktrunk
（不存在）
$ brew install worktrunk
…退出 1：Dir.rmdir: Operation not permitted @ dir_s_rmdir
  - /opt/homebrew/var/homebrew/tmp/.cellar/verify-…/homebrew-tar…
  from unpack_strategy/tar.rb:40 → sandbox_operation.rb:31
```

尝试记录（4 次，均为同一失败点）：

| # | 方式 | 结果 |
|---|---|---|
| 1 | `brew install worktrunk`（默认） | 失败：`sandbox_operation.rb extract` 内 `Dir.rmdir` EPERM |
| 2 | 关闭 Trae 沙箱后重跑 | 同一失败点 |
| 3 | `HOMEBREW_NO_SANDBOX=1` | 同一失败点 |
| 4 | `HOMEBREW_TEMP=/tmp/brew-tmp` | 同一失败点（仍落在 `/opt/homebrew/var/homebrew/tmp/.cellar`） |

* **结论**：**装不上**（Homebrew 解包阶段的临时目录清理被系统拒绝），`wt --version` / `wt list --help` 无法实测。
* **处置**：按拍板「装不上就整条删除，记入不采纳」——**C3 整条删除**，不保留半条；`wt merge` / `hash_port` 一并归入已否的备选 H（§2.2），不再单列。
* **残留痕迹**：无（`wt` 不在 PATH、`brew list` 无 `worktrunk`、`Cellar` 无目录）。

---

## 7. 交叉指认（与既有条款的咬合面）

| 既有条款 | 咬合关系 | 本批动作 |
|---|---|---|
| `DESIGN.md` D131（步骤 4 = bug fix 7 检查点） | 本批扩其作用域（**D186 已定案**） | D186 明文扩面；D131 行末注记已改为定案句，正文不动 |
| `DESIGN.md` D156（留出验证三态） | 本 RFC 机械命中触发面 (b) | §4.5 只写候选结论与必填字段，判定归 REVIEW |
| `DESIGN.md:653` D177（前端复用记录归任务） | 与「假设记录归 Trellis」同源 | 不引用 D177；由 D186 承载 |
| `shared/gates.md` §2.5（流程门 10 行） | 新增 1 行纪律 | 174→175，地图同批 |
| `tests/test_canonical_consistency.py:301-328`（判据⑦） | 宣称守卫 | 同批改写后再加 `VETO_WORDS` |
| `shared/layout.md:9-14`（`.atlas/` 刷新、`product/` 不覆盖） | 模板变更不迁移存量 | I5 明写「不迁移」 |
