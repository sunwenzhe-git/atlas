# 实现期纪律收敛 + SKILL 体积预算 + 术语表禁用别名

> 提案编号：`RFC-20261107-01`
> 提案作者：@sunwenzhe
> 关联状态：草案 (Draft)
> 影响范围：核心契约 (shared) | 环契约 (rings) | 测试 (tests) | 模板 (templates)
> 决策行：D185 / D186 / D187（**候选，待独立 REVIEW 定案**）

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

能力宣称与触发表原文（逐行复核）：

```text
README.md:123                  由内置的 Trellis 任务系统承担，Atlas 本身不侵入业务代码实现。   → 真，不改
docs/design/overview.md:78     业务代码归执行器，Atlas 不碰业务实现                               → 改
shared/independent-review.md:192  收口侧设门，实现过程仍不介入                                     → 改
shared/independent-review.md:225  实现期的代码规范…不进本契约——atlas 不介入实现过程（§10 引言既定边界） → 外科改
shared/closeout.md:149         不做业务代码实现期规范复盘（BP 边界…）                             → 补澄清
shared/single-source.md:43     编码规范不由 atlas 收口                                           → 保留 + 补边界
shared/layout.md:97            编码规范不由 atlas 收口                                           → 保留 + 补边界
shared/closeout.md:20          缺陷修复类任务 → 4（修复验证 7 检查点）                            → 保留，新增实现类行
shared/closeout.md:25          任一工作单元收尾 → 1                                              → 不动
```

### 1.3 引子族锚（D156 触发面 (a)）

本 RFC **不是** `duty-review/bugs.md` 的同根归纳：事项来源是外部公开实践 + 维护者现场观察（边界表述冲突、体积、术语表列数），属于「能力边界缺口 / 宣称漂移」，不是缺陷复发链。因此触发面 (a) 不成立；触发面 (b) 的原始输出见 §4.5。

---

## 2. 决策与权衡 (The Decision & Trade-offs)

### 2.1 核心定案 (The Decision)

| # | 定案 |
|---|---|
| **I1** | `skills/*/SKILL.md` 字符数 ≤ **20,000**。预算常量 `SKILL_BUDGET_CHARS = 20000` 写在测试内（不读被审文件）；判据⑧只有一条断言（字符数），**不建 manifest、不建 hash、不做指针分类或双向校验**。批 1 拆分时附「外移前后 section 清单」人工核对一次；`§4.7/4.11` 摘要（`SKILL.md:21` 明示保留）不得外移。 |
| **I2** | `shared/global-rules.md` 新增 §18：实现期假设落 Trellis Plan/Design（不建台账），命中 §7 四条签名动作即停；会改变 AC / 范围 / 用户可见行为 ⇒ 回流 PRD 决策。 |
| **I3** | `shared/closeout.md` 步骤 4 分档：A 档（bug fix）原 7 检查点不变；B 档（feature / refactor）4 项——可追溯性、纯空白证据命令、纯后端验证命令、测试反模式自查（**只作证据观察，不判分**）。触发表新增一行「实现类任务（feature / refactor，非 bug fix）→ 4（B 档）→ 1 → 7」，并标「语义触发行，不自动派生」。 |
| **I4** | 能力宣称 5 处改写 + 1 处澄清（`overview.md:78`、`independent-review.md:192`、`:225`、`closeout.md:149`、`single-source.md:43`、`layout.md:97`）；`README.md:123` 保留不改。`VETO_WORDS` 只加精确被否短语；D185/D186 进豁免锚。 |
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
* **备选 H：worktrunk `wt merge` / `hash_port`**
  * *否定理由*：改历史、与提交纪律冲突；D148 不走本地 dev server。不采纳。

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
- [ ] **技能正文**：`skills/frontend-design/SKILL.md` 外移 ≥2,590 字符（`§4.7/4.11` 保留）
- [ ] **测试防线**：`tests/test_canonical_consistency.py` 新增判据⑧（`SKILL_BUDGET_CHARS`）、`VETO_WORDS` / `VETO_EXEMPT_ANCHORS` 常量
- [ ] **留出验证（§4.5）**：不适用 + 触发面核对（见 §4.5）
- [ ] **地图与计数器**：`docs/map/gates.md:18`（174→175）、`:20`（56→57）、`docs/map/atlas-map.html:510`（174）
- [ ] **决策记录**：`DESIGN.md` D185 / D186 / D187；D131 行末指向性注记

**明确不做**：`README.md:123` 不改；不新建 `_manifest.json`；不新增校验器；不改 `scripts/`；不写 REVIEW 文件。

---

## 4. 验证与测试结果 (Verification)

### 4.1 四批与预期红

| 批 | 内容 | 预期红 |
|---|---|---|
| **0** | 本 RFC + D185/D186/D187 + `docs/map/gates.md:20` 56→57 + C1/worktrunk 探测 | 无（纯文档 / 地图陈旧行） |
| **1** | I1 拆分（**不加判据⑧**）；附外移前后 section 清单 | 无；收尾复量 <20,000，`§4.7/4.11` 逐字仍在 |
| **2** | 判据⑧（常量 + 单一断言）+ I5 | 无；若批 1 未完成则判据⑧红 |
| **3** | I2 + I3 + I4 + §2.5 行 + `VETO_WORDS` + **地图 174→175 同批** | 无；漏改地图 ⇒ `docs/map/gates.md:18` / `atlas-map.html:510` 红；漏改任一宣称 ⇒ 判据⑦红 |
| **4（可选）** | B1′：`SKILL.md §14` 六条硬检查标 Floor / Reflex / Finish | 无；复查 I1 预算余量 |

### 4.2 批 0 验证命令

```bash
python3 -c "print(len(open('shared/gates.md').read().splitlines()))"   # 期望 174（批 3 后 175）
grep -n '(57 文件)' docs/map/gates.md
git diff --name-only
python3 scripts/closeout_derive.py --diff-base HEAD --root .
```

---

### 4.5 留出验证（D156，`shared/gates.md` §2.5）

* **触发面核对**：(a) §1.3 已述，非 `bugs.md` 同根归纳 ⇒ 不触发；(b) 本 RFC 触及门 / 契约判据（判据⑧、判据⑦常量、步骤 4 范围、§2.5 行）⇒ **候选触发**。原始输出如下（批 0 实收）：

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

* **三态结论（候选，最终判定留给独立 REVIEW）**：`单案修复（无留出集）`——理由：判据⑧是新增静态上限，无既有判据翻转面可留出；判据⑦只改常量集合、不改判定逻辑；步骤 4 B 档无退出码。若 REVIEW 认定「契约判据变更」必须留出，则补留出集候选：`skills/frontend-design/SKILL.md` 字符数从 22,590 → <20,000 的单次迁移（独立性存疑：迁移由本批自己执行，见 §5 盲区）。
* **D 行状态**：D185 / D186 / D187 均标「候选，待独立 REVIEW 定案」；REVIEW 归位后再改为已定案。

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

### 6.2 worktrunk 可用性探测

```text
$ command -v wt
（无输出）
$ brew info worktrunk
worktrunk: stable 0.81.0 (bottled), HEAD
CLI for Git worktree management, designed for parallel AI agent workflows
Conflicts with: wiredtiger (both install `wt`)
Not installed
```

- **结论**：可安装（brew 有 bottled formula），**未安装**，可用性未验证；`wt` 与 `wiredtiger` 存在二进制名冲突。
- **处置**：按拍板「装不上才删」——可安装 ⇒ C3 保留在待取证，不删除；不自行安装（系统变更待确认）。

---

## 7. 交叉指认（与既有条款的咬合面）

| 既有条款 | 咬合关系 | 本批动作 |
|---|---|---|
| `DESIGN.md:600` D131（步骤 4 = bug fix 7 检查点） | 本批扩其作用域 | D186 明文扩面；D131 行末补指向注记，正文不动 |
| `DESIGN.md:631` D156（留出验证三态） | 本 RFC 候选触发 | §4.5 只写候选结论，由 REVIEW 定 |
| `DESIGN.md:653` D177（前端复用记录归任务） | 与「假设记录归 Trellis」同源 | 不引用 D177；由 D186 承载 |
| `shared/gates.md` §2.5（流程门 10 行） | 新增 1 行纪律 | 174→175，地图同批 |
| `tests/test_canonical_consistency.py:301-328`（判据⑦） | 宣称守卫 | 同批改写后再加 `VETO_WORDS` |
| `shared/layout.md:9-14`（`.atlas/` 刷新、`product/` 不覆盖） | 模板变更不迁移存量 | I5 明写「不迁移」 |
