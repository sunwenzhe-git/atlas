# 判据⑧ 装配副本态恒红（#56）—— D156 留出验证记录

> 提案编号：`RFC-20261108-01`
> 关联缺陷：`duty-review/bugs.md` #56（`## 自感知上报（§15 缺陷族）` 段）
> 修复提交：`0c8d196`（现行）；中间态 `5a02e3b` 曾用 `install.sh` 判别，已被取代
> 判定记录：本节 §4.5 + `REVIEW-20261108-02`（唯一判定记录，不新增台账）
> 判定：**`未闭族`**——由 `REVIEW-20261108-02` 独立判定；本文件承载证据，不自行改判
> 基线：HEAD `0c8d196`

---

## 1. 现象与取证 (The Problem & Evidence)

### 1.1 触发形态（抽象）

* **规则 / 环节**：判据⑧（`tests/test_canonical_consistency.py` 的 `check_skill_budget`，`SKILL_BUDGET_CHARS = 20000`）。
* **触发时机**：采纳仓内跑 `pytest .atlas/tests`（`atlas_check` 的「对齐测试(.atlas/tests)」门）。
* **具体行为**：装配副本的 `PKG_ROOT = 采纳仓的 .atlas/`，其根下按设计**没有** `skills/`。判据⑧扫不到 `skills/*/SKILL.md` 时按 fail-closed 判红 ⇒ 整条「对齐测试」门 FAIL ⇒ 嵌套 `atlas_check` FAIL ⇒ `atlas_verify` 停在 run 步 ⇒ `test_atlas_verify_playground` 两例红。

### 1.2 根因

判据⑧的被审对象（`skills/*/SKILL.md` 字符预算）只在源包存在，装配副本不携带根 `skills/`。原实现把「扫面为空」当「判据失效」处理，未区分「源包被删掉 skills/」与「本来就是装配副本」两种形态。

### 1.3 修复（`0c8d196`）

扫面为空时，按**装配戳**分流：根下存在 `VERSION` 或 `MANIFEST.json` ⇒ 判 `N/A`（`ok=True, skip=True`）；两者都不存在 ⇒ 仍 fail-closed。装配戳由 `install` 侧写入，源包根两者都不存在，故删任何普通文件都藏不住判据。

同批新增三条钉：

| 钉 | 锁的行为 |
|---|---|
| `test_skill_budget_fail_closed_without_skills_or_stamp` | 源包态「无 `skills/` 且无装配戳」⇒ fail-closed（反面包） |
| `test_skill_budget_assembled_copy_is_na` | 根有 `VERSION` 或 `MANIFEST.json` ⇒ 判 `N/A`（`skip=True`） |
| `test_skill_budget_counts_chars_when_skills_present` | 有 `skills/` 即按字符数判，装配戳不改变结论 |

### 1.4 数量取证（按粒度分开记，不混写）

| 粒度 | 命令 | pre-fix（`021bb38`） | post-fix |
|---|---|---|---|
| 采纳仓**整包** | `pytest .atlas/tests` | `1 failed / 1209 passed`（现场记录） | **未复跑**（无真实采纳仓在场） |
| 单文件 | `pytest tests/test_canonical_consistency.py` | `1 failed / 9 passed`（该提交 10 条用例；现场记录） | `5a02e3b`：`10 passed`（10 条用例）；`0c8d196`：`13 passed`（本机实测） |

* 「1209 passed」是**整包**粒度；「10 passed」是**单文件**粒度。两者不可互相替代。
* 采纳仓整包 pre-fix 现场记录的 1 failed 即判据⑧；单文件 pre-fix 的 1 failed 是同一条判据。

---

## 2. 决策与权衡 (The Decision & Trade-offs)

### 2.1 核心定案

1. **用装配戳判别副本态**，不做「有 `skills/` 就判、没有就跳过」的弱化：后者会让源包删掉 `skills/` 后静默通过，属 D185 明禁的假阴形态。
2. **戳的选择 = `VERSION` / `MANIFEST.json`**，不用 `install.sh`：`install.sh` 是包内普通文件，源包同样携带，删掉它就能把源包伪装成「非副本」，判据可被形态满足。装配戳由安装器写入，源包根不存在。
3. **不改 install 侧**：本次只改判据的识别方式与测试钉，不动装配产物格式。

### 2.2 考虑过的备选方案及否定理由

* **A. 保持 fail-closed，让采纳仓接受整条门恒红**：门失去信号意义，红被训练成噪声（`#17` 已立过同类教训）。否。
* **B. 扫面为空即判 `N/A`（不判别）**：源包删 `skills/` 后判据消失，假阴面扩大。否。
* **C. 用 `install.sh` 判别（`5a02e3b`）**：源包同样有 `install.sh`，删掉即可伪装。已被 `0c8d196` 取代。
* **D. 让装配副本也携带根 `skills/`**：改变分发形态、增大装配体积，且与判据⑧「只判源包 skill 体积」的定位冲突。否。
* **E. 先修「加文件即假阴」再修本缺陷**：见 §4.5「未取证 / 不成立项」与 §5，牵动 install 侧，需另行立项。

### 2.3 刺痛代价与兼容性影响

| 项 | 影响 |
|---|---|
| 采纳仓 | 判据⑧在装配态转 `N/A`，不再拖垮「对齐测试」门 |
| 源包 | 行为不变（有 `skills/` 照常按字符数判；无 `skills/` 且无戳仍 fail-closed） |
| 假阴面 | 新增一条：根上带 `VERSION` / `MANIFEST.json` 却实际是源包 ⇒ 静默 `N/A`（已登记为残留风险，见 §4.5） |

---

## 3. 改动面清单 (Affected Surface)

| # | 文件 | 动作 |
|---|---|---|
| 1 | `tests/test_canonical_consistency.py` | `check_skill_budget` 改用装配戳分流；+3 钉（`0c8d196`） |
| 2 | `duty-review/bugs.md` | 落 #56；`证` 锚 = `0c8d196`；D156 说明改为中性指针行（本批） |
| 3 | `tests/test_duty_bug_families.py` | 复冻基线（`0c8d196` 已随 #56 落库；本批**不再改动**） |
| 4 | `proposals/RFC-20261108-01-judgement8-assembled-copy-heldout.md` | 本文件（留出验证记录） |
| 5 | `proposals/REVIEW-20261108-02-judgement8-assembled-copy-heldout.md` | 独立 REVIEW 归档 |

---

## 4. 验证与测试 (Verification)

### 4.1 pre-fix 红 / post-fix 绿（判据级重放）

用 `git show <rev>:tests/test_canonical_consistency.py` 取两版文件到 `/tmp`，把 `PKG_ROOT` 指到临时空根，分别加 `VERSION` / `MANIFEST.json`，直调 `check_skill_budget()`：

```text
== pre-021bb38
  empty         ok=False skip=False detail=未扫到 skills/*/SKILL.md —— 判据失效，fail-closed
  VERSION       ok=False skip=False detail=未扫到 skills/*/SKILL.md —— 判据失效，fail-closed
  MANIFEST.json ok=False skip=False detail=未扫到 skills/*/SKILL.md —— 判据失效，fail-closed
== post-0c8d196
  empty         ok=False skip=False detail=未扫到 skills/*/SKILL.md 且无装配戳 —— 判据失效，fail-closed
  VERSION       ok=True  skip=True  detail=装配副本态（根有 VERSION / MANIFEST.json 装配戳）：判据⑧ N/A —— 被审对象只在源包
  MANIFEST.json ok=True  skip=True  detail=装配副本态（根有 VERSION / MANIFEST.json 装配戳）：判据⑧ N/A —— 被审对象只在源包
```

### 4.2 反面包

`test_skill_budget_fail_closed_without_skills_or_stamp`：无 `skills/` 且无装配戳 ⇒ 仍 fail-closed，**不误伤源包态**。

### 4.3 变异

在 `/tmp` 副本把装配戳分支摘成 `if False:`，跑 `test_skill_budget_assembled_copy_is_na`：

```text
FAILED .../test_canonical_consistency.py::test_skill_budget_assembled_copy_is_na - AssertionError:
  未扫到 skills/*/SKILL.md 且无装配戳 —— 判据失效，fail-closed
1 failed in 0.10s
```

红因恰为「装配态病例复红」，不牵连其他钉。

### 4.4 全量与台账

```bash
python3 duty-review/families.py duty-review/bugs.md
python3 -m pytest tests/test_duty_bug_families.py tests/test_canonical_consistency.py tests/test_map_anchors.py -q
```

本批落盘后的实测结果见 §4.6。

### 4.5 留出验证（D156，`shared/gates.md` §2.5）

**判定权**：三态只能由独立 REVIEW 判定。本节的候选结论与 `REVIEW-20261108-02` 一致 = **`未闭族`**；不宣称 `闭族`。

| 项 | 结论 |
|---|---|
| 三态 | **`未闭族`**（`REVIEW-20261108-02`） |
| 触发面 | (a) 不成立（`#56` 段首同根归纳为「判据可被形态 / 措辞 / 配置满足」，但本缺陷不是该族的新同根归纳）；(b) 命中（改测试内判据且 diff 落在 `tests/` 路径族）——按 §2.5 记映射与误报，不另立族 |

#### 已取证项（机械证据成立）

1. **pre-fix 红**：装配戳不识别时，`VERSION` / `MANIFEST.json` 空根均判 fail-closed；采纳仓整包 `1 failed / 1209 passed`（现场记录）。
2. **post-fix 绿**：同夹具在 `0c8d196` 判 `N/A`；单文件 `13 passed`（本机实测）。
3. **反面包**：源包态「无 `skills/` 且无装配戳」仍 fail-closed（钉在案）。
4. **变异杀伤**：摘装配戳分支 ⇒ 装配态病例复红，其余钉不受牵连（§4.3）。
5. **口径说明**：整包粒度与单文件粒度的数字已分开记录（§1.4），不互相代替。

#### 未取证 / 不成立项

1. **无合格留出集**：唯一候选就是**发现该缺陷的那个装配态**（采纳仓 `.atlas/`），它参与了挖弱点，违反 D156「未参与挖弱点」。仓内不存在第二个未参与该修复的真实装配态。
2. **「结构不可达」按严格读法不成立**：该夹具不是不可由既有钉夹具得到——既有钉夹具就是空根；往空根里加一个 `VERSION` 文件即可得到「装配戳副本」形态。因此独立性第 ③ 条不成立。
3. **独立性第 ② 条（变异增量杀伤）只证明钉有牙**，不证明留出集存在；不得拿它替代 ①/③。
4. **真实采纳仓复验未取证**：本机无 `.atlas/tests`，也无第二个已装配的采纳仓；修复后未在真实采纳仓重跑整包。

#### 残留风险与盲区

1. **假阴面（本次不修）**：任何根上带 `VERSION` 或 `MANIFEST.json` 却无 `skills/` 的树都会被**静默判 `N/A`**，包括「源包根误放了一个 `VERSION`」的情形。现有反面包只覆盖「无戳 ⇒ fail-closed」，未覆盖「有戳但其实是源包」。
   * **为何不现在动**：堵这一面需要让「装配戳」具备源包无法仿造的内容（例如 install 侧写入的清单字段 / 签名），会牵动 `install` 侧的装配产物格式与向后兼容；属独立立项，不塞进本次最小修复。
2. **戳的存在性判别是形态判别**：只要文件名存在即判副本，不校验内容与来源；与 `#1/#4/#6/#7` 同族的「判据可被形态满足」风险仍在，只是从「无戳」面移到了「有戳」面。
3. **未参与挖弱点**无法机判：本次只能如实记「无合格留出集」，不能证明未来不会出现。

#### 补验路径与重开条件

**补验路径**（满足任一即可重评三态）：

1. 在**未参与本次修复**的真实采纳仓（由 `install` 装配、根下无 `skills/`、有装配戳）跑 `pytest .atlas/tests`，确认判据⑧不再致红，且整包除已知环境红外无新增失败。
2. 构造一个**结构不同**的装配态（例如装配后根下另有 `skills/`，或 `VERSION` 与 `MANIFEST.json` 只居其一的变体），确认判据⑧按字符数判而非静默 `N/A`。

**重开条件**（出现任一即按 DR1/DR2 重新立批）：

1. `install` 侧新增 / 改名 / 移除装配戳，或装配副本开始携带根 `skills/`。
2. 真实采纳仓出现「判据⑧ 该红未红」或「该 `N/A` 却红」的实例。
3. 另行立项修复「加文件即假阴」面时，本记录随之重评。
4. `REVIEW-20261108-02` 的判定被后续独立评审推翻。

### 4.6 本批落盘实测

见最终回复中的实测输出；本节只登记判定与证据位置，不复制命令输出。

---

## 5. 本次不做的事

* **不修「加文件即假阴」面**：只在 §4.5 登记，理由 = 牵动 install 侧，需另行立项。
* **不改 #56 的段落归类**：仍留在 `## 自感知上报（§15 缺陷族）`。
* **不回冻、不改 `tests/test_duty_bug_families.py` 基线**：`0c8d196` 已随 #56 落库复冻；本批只把 `bugs.md` 的 D156 说明改为中性指针行，指针行不带状态 / 日期 / `#NN`，不改变五段三值。
* **不改判 `闭族` / `单案修复（无留出集）`**：前者无合格留出集；后者要求的三件（独立评审确认 / QUEUE 观察行 / RFC 残留风险记录）对 #56 不成立，且「无留出集」不等于「留出不合格」。
