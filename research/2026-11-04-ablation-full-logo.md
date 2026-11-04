# 全门册消融普查（留一门法 LOGO）— 单快照批次

> 口径：一个真实采用方快照、10 个可摘校验器、每门一轮、4 条语料。
> **覆盖率 10/17 运行面门行（可摘子集 10/10；文档口径 10/34）**——本批不是全量普查，未覆盖项见 §6。
>
> 主体指纹：
> - 主快照 A = 装配摘要 `b4c1605d…`（源包 HEAD `d1674e3`）+ 业务 HEAD `877b80e`，`--fast` 运行面实收 **17 行**。
> - 源包 = 装配来源树，HEAD `d1674e3`，装配时间 `2026-11-04T10:45:13`。
> - 证据目录在仓外（未落入任何采用方仓）。

---

## 0. 结论先行

| 结论 | 读数 |
|---|---|
| 可摘除性 | 10 个 `validate_*.py` 全部可机械摘除并逐字节还原；**0 轮异常退出**（10/10 轮 rc=0、行数恒 17） |
| 硬依赖 | 本批未撞到（摘任一门后整轮仍完整产出 17 行） |
| 成本集中度 | `validate_testids` 独占基线门册耗时 **58.1%**（约 766 ms/轮）；其余各门 0–6.1% |
| 成本可判性 | 除 `validate_testids` 外，配对差值全部落在基线噪声带内（基线三轮 Σ 1123–1629 ms） |
| 独占接住 | 语料 4 条中 **2 条**被单一门独占接住（`validate_stack_profile`、`validate_e2e_mocks`） |
| 零门红 | 语料 4 条中 **2 条**零门红（本语料未观察到信号，**不等于门没用**） |
| 结构性不可辨 | `validate_design_exemptions`、`validate_adr` 前置未满足恒 `SKIP`，摘除后状态向量不可区分 |
| 装配一致性 | 装后 10 个校验器、摘要 `b4c1605da2b82a24` 与源包工作树重算值**逐字节一致**；行集与源包 HEAD 一致 |

---

## 1. 主快照与装前留档

### 1.1 装前（可回退证据）

| 项 | 装前值 |
|---|---|
| `.atlas/VERSION` 摘要 | `b9f708af7be8e9f8` |
| `.atlas/VERSION` 时间 | `2026-10-29T11:09:25+08:00` |
| `.atlas/VERSION` 源包 | npm 全局 harness（非本仓源包） |
| 校验器个数 | 10（`validate_*.py` 逐文件 sha256 已留档） |
| `git status --porcelain` | **39 行**（业务文件全未提交；内容 sha256 已留档） |
| `git rev-parse --show-toplevel` | 自身（git 顶层） |
| 业务 HEAD | `877b80e` |

### 1.2 装配

- 入口：源包的 `install.sh --update`（`--no-skill --no-patch --no-wiring`），未使用 `install.py` 直调。
- 装后 `.atlas/VERSION`：摘要 `b4c1605da2b82a24` / 时间 `2026-11-04T10:45:13` / 源包路径行。
- **摘要与提交的对应关系**：`VERSION` 摘要**不是** git commit，而是「装配集逐文件 sha256 聚合取前 16 位」。已用源包同一算法重算工作树，得 `b4c1605da2b82a24`，与落戳、`MANIFEST.json.digest`（252 文件基线）三者一致 ⇒ 摘要对应源包 HEAD `d1674e3` 的工作树内容，**非硬编映射**。
- 校验器个数：10（装前后同名同数，内容变化 5 个：`validate_ac_alignment`、`validate_e2e_index`、`validate_prd`、`validate_stack_profile`、`validate_testids`）。

### 1.3 装后核验与行集比对

| 项 | 值 |
|---|---|
| `atlas_check --root <主快照> --fast --json` 行数 | **17** |
| 状态分布 | `ok=8` / `WARN=4` / `SKIP=3` / `N/A=2`，`ok=true` |
| 三轮基线稳定性 | 行数与状态分布**三轮完全一致** |
| 与源包 HEAD 的 34 行文档口径 | 一致的部分：§2.2 的 5 个编排行 + 10 个校验器行；不一致见 §6 |

**34 行口径的分解**（`shared/gates.md`）：§2.1 机器门 20 行、§2.2 编排检查 9 行、§2.3 装配面 3 行、§2.4 运行期门 2 行，合计 34。
其中 `--fast` 只覆盖 §2.2 的 9 行（并把其中「`validate_*` 每器一行」展开成 10 行），再叠加 2 个代码独有行（`审查报告形态`、`执行串行`）= 17 行。

### 1.4 pytest 基线（副本，非主快照）

| 项 | 值 |
|---|---|
| 运行位置 | 主快照的临时副本（仅测试用；主快照与全部摘门轮次都在主快照树上） |
| 收集数 | **1149** |
| 结果 | **1142 passed / 5 skipped / 2 deselected**，478 s |
| 未跑完的 2 例 | `tests/test_atlas_verify_playground.py` 的两个 playground 用例：内层 `pytest .atlas/tests` 长时间不返回 |
| 结论措辞 | 记为「1149 收集 + 2 例嵌套 playground 段未跑完」，**不写全绿** |

---

## 2. 表 T1：可消融性盘点

### 2.1 可摘除候选（10 个校验器，全部实摘）

| # | 门（校验器） | 类别 | 依据 | 本批轮次 |
|---|---|---|---|---|
| 1 | `validate_stack_profile` | **A 纯判据** | 无写操作 | G-01 |
| 2 | `validate_structure` | **A 纯判据** | 无写操作 | G-02 |
| 3 | `validate_e2e_index` | **A 纯判据** | 无写操作 | G-03 |
| 4 | `validate_testids` | **B 带副作用** | 写 `.trellis/spec/conventions/testid.md` 薄桩 | G-04 |
| 5 | `validate_e2e_mocks` | **A 纯判据** | 无写操作 | G-05 |
| 6 | `validate_ac_alignment` | **B 带副作用** | 写 `.atlas/runs/backend-ac-alignment.json` 基线 | G-06 |
| 7 | `validate_prd` | **A 纯判据** | 无写操作 | G-07 |
| 8 | `validate_design_exemptions` | **A 纯判据** | 无写操作 | G-08 |
| 9 | `validate_adr` | **A 纯判据** | 无写操作 | G-09 |
| 10 | `validate_walkthrough` | **A 纯判据** | 无写操作 | G-10 |

写操作统计（`write_text|write_bytes|open(...,'w')|mkdir|shutil.*|os.replace` 命中数）：仅 `validate_testids`=2、`validate_ac_alignment`=2，其余 8 个为 0。

### 2.2 不可摘除 / 未纳入

| 段 | 行/资产 | 类别 | 运行面是否有行 | 本批处置 |
|---|---|---|---|---|
| §2.1 | 10 个脚本型门（`gen_e2e_scripts`、`refresh_structure`、`gen_testid_stub`、`cli_review_convert`、`validate_review_report`、`review_scope`、`atlas_eval`、`impact_reconcile`、`closeout_derive`、`backflow`） | C 生产型 / 独立 CLI | 否（`atlas_eval` 明确不进 `atlas_check`） | 不摘 |
| §2.1 | `atlas_check.py` 本体 | D 编排流程 | — | 不摘（摘了就没有门册） |
| §2.2 | `生成物最新`、`写面残留`、`结构漂移`、`消融残留`、`装配版本` | D 编排流程 | 是（`atlas_check.py` 内联函数） | **未纳入 LOGO**（无独立文件可摘） |
| §2.2 | `审查报告形态`、`执行串行` | D/A（调 `scripts/validate_review_report.py` / 内联） | 是（代码独有，文档无） | **未纳入 LOGO** |
| §2.2 | `对齐测试(.atlas/tests)` | B 带副作用（跑子测试） | 是，但 `--fast` 跳过 | **未纳入 LOGO** |
| §2.2 | `E2E 真跑` | 运行期真跑 | 是，但 `--fast` 跳过 | **未纳入 LOGO** |
| §2.2 | `跨页终态断言落首列页` | — | **否**（无独立行，判据在 `validate_e2e_index` 内） | 不可摘 |
| §2.3 | `install.py` 自检、`test_install_selfcheck.py`、`apply-wiring.py` | C/D 装配面 | 否（装配期） | 不摘 |
| §2.4 | `test_<page>__zero_step_baseline`、完成门 | 运行期（需真跑 E2E） | 否 | 不摘 |
| 代码独有 | `项目布局配置`、`布局提示（code）` | D 条件行 | 条件出现 | 不摘 |

---

## 3. 表 T2：LOGO 签名矩阵（17 行 × 基线 + 10 轮）

`=` 表示与基线同状态；其余为逐门摘除轮的实际状态。

| 门行 | 基线×3 | G-01 | G-02 | G-03 | G-04 | G-05 | G-06 | G-07 | G-08 | G-09 | G-10 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `validate_stack_profile` | WARN | **SKIP** | = | = | = | = | = | = | = | = | = |
| `validate_structure` | ok | = | **SKIP** | = | = | = | = | = | = | = | = |
| `validate_e2e_index` | WARN | = | = | **SKIP** | = | = | = | = | = | = | = |
| `validate_testids` | ok | = | = | = | **SKIP** | = | = | = | = | = | = |
| `validate_e2e_mocks` | ok | = | = | = | = | **SKIP** | = | = | = | = | = |
| `validate_ac_alignment` | N/A | = | = | = | = | = | **SKIP** | = | = | = | = |
| `validate_prd` | WARN | = | = | = | = | = | = | **SKIP** | = | = | = |
| `validate_design_exemptions` | SKIP | = | = | = | = | = | = | = | **SKIP** | = | = |
| `validate_adr` | SKIP | = | = | = | = | = | = | = | = | **SKIP** | = |
| `validate_walkthrough` | WARN | = | = | = | = | = | = | = | = | = | **SKIP** |
| `生成物最新` | SKIP | = | = | = | = | = | = | = | = | = | = |
| `审查报告形态` | ok | = | = | = | = | = | = | = | = | = | = |
| `执行串行` | ok | = | = | = | = | = | = | = | = | = | = |
| `结构漂移` | ok | = | = | = | = | = | = | = | = | = | = |
| `装配版本` | ok | = | = | = | = | = | = | = | = | = | = |
| `写面残留` | ok | = | = | = | = | = | = | = | = | = | = |
| `消融残留` | N/A | ok | ok | ok | ok | ok | ok | ok | ok | ok | ok |

读数：

1. **无溢出**：除被摘行本身外，其余 16 行状态**零变化**——说明这 10 门在本快照上互不串联（无门依赖另一门的产物来置态）。
2. `消融残留` 由 `N/A` → `ok` 是**设计行为**（摘除窗口内存在 `ABLATION` 标记且真相源可达），不是信号；本批统一用默认状态根，早期用 `--state-root` 指向别处时该行会误报 `WARN 存在 ABLATION 提示但无 active 真相源`（工具自指伪影，已规避）。
3. `validate_design_exemptions` / `validate_adr`：**基线即 `SKIP`**，摘除轮与基线在状态向量上除被摘行外完全相同 ⇒ 这 2 门在本快照上**不可辨**，LOGO 无法给出其贡献。
4. `validate_ac_alignment`：`N/A` → `SKIP` 属弱可辨（本快照无 AC 对账面）。

---

## 4. 表 T3：成本份额（基线三轮）

分母说明：Σ = 17 行 `duration_ms` 之和；三轮 Σ 分别为 **1629 / 1206 / 1123 ms**（波动 ±22%，即噪声带）。

| 门行 | b1 | b2 | b3 | 均值 ms | 占门册 Σ 均值 | 摘除轮 Σ（Δ vs 基线均值） |
|---|---|---|---|---|---|---|
| `validate_testids` | 954 | 669 | 676 | **766.3** | **58.1%** | 466（**-853**） |
| `validate_prd` | 105 | 73 | 64 | 80.7 | 6.1% | 1128（-191） |
| `validate_structure` | 94 | 78 | 68 | 80.0 | 6.1% | 1351（+32） |
| `生成物最新` | 93 | 63 | 54 | 70.0 | 5.3% | —（未摘） |
| `validate_ac_alignment` | 67 | 82 | 47 | 65.3 | 5.0% | 1160（-159） |
| `validate_e2e_index` | 59 | 69 | 56 | 61.3 | 4.6% | 1087（-232） |
| `validate_e2e_mocks` | 53 | 53 | 49 | 51.7 | 3.9% | 1081（-238） |
| `validate_walkthrough` | 64 | 43 | 42 | 49.7 | 3.8% | 1149（-170） |
| `validate_stack_profile` | 51 | 53 | 41 | 48.3 | 3.7% | 1393（+74） |
| `装配版本` | 83 | 21 | 24 | 42.7 | 3.2% | —（未摘） |
| `消融残留` | 6 | 2 | 2 | 3.3 | 0.3% | —（未摘） |
| `validate_design_exemptions` | — | — | — | 0 | 0.0% | 1148（-171） |
| `validate_adr` | — | — | — | 0 | 0.0% | 1116（-203） |
| `审查报告形态` | 0 | 0 | 0 | 0 | 0.0% | — |
| `执行串行` | 0 | 0 | 0 | 0 | 0.0% | — |
| `结构漂移` | — | — | — | 0 | 0.0% | — |
| `写面残留` | — | — | — | 0 | 0.0% | — |

读数：

- **成本绝对集中于 `validate_testids`**（58.1%）。摘除轮 Σ 降至 466 ms，Δ = −853 ms，**显著超出噪声带**，是唯一可用配对差值直接归因的门。
- 其余门 Δ 全在 −238…+74 ms，**均落在基线 1123–1629 ms 的波动区间内**，不可归因（`-170`/`-203` 之类的数字不能读成「该门耗时 170/203 ms」）。
- `duration_ms` 为 `None` 的行（`design_exemptions`、`adr`、`结构漂移`、`写面残留`）说明该行**没有可计时的执行段**（提前返回），不是 0 ms 的实测。
- 绝对 ms **不可跨环境比**；本表只用于同机同快照内的份额排序。

---

## 5. 表 T4a / T4b：语料矩阵

语料在**隔离副本**（去掉 `node_modules` / `.git`，约 39 MB）上投放，每条投放后跑一轮 `--fast` 全门册，跑完即还原并抽查 sha256。

### T4a 语料可摘性

| 语料 | 投放位（业务资产） | 期望触发 | 实测触发 | 可摘性判定 |
|---|---|---|---|---|
| X1 未知 graph backend | `product/stack-profile.yaml` | `validate_stack_profile` | 仅该门 `WARN→FAIL` | **独占接住** |
| X2 testid 重复登记 | `product/` 用例资产 | `validate_testids` | **无门红**（状态零变化） | 未观察到（不得判「门无用」） |
| X3 分片 `mock:` 行（mode 缺省 off） | `product/e2e/cases/` 分片 | `validate_e2e_mocks` | 仅该门 `ok→FAIL` | **独占接住** |
| X4 走查三问表缺失 | 走查资产 | `validate_walkthrough` | **无门红**（状态零变化） | 未观察到（不得判「门无用」） |

### T4b 状态矩阵（只列变化；基线红集 = `stack_profile` WARN / `e2e_index` WARN / `prd` WARN / `walkthrough` WARN）

| 语料 | `stack_profile` | `e2e_index` | `e2e_mocks` | `prd` | `walkthrough` | 其余 12 行 | 判定档 |
|---|---|---|---|---|---|---|---|
| X1 | WARN→**FAIL** | WARN | ok | WARN | WARN | 不变 | 独占接住 |
| X2 | WARN | WARN | ok | WARN | WARN | 不变 | **零门红** |
| X3 | WARN | WARN | ok→**FAIL** | WARN | WARN | 不变 | 独占接住 |
| X4 | WARN | WARN | ok | WARN | WARN | 不变 | **零门红** |

读数：

- 「独占接住」= 该语料只让一个门置红，且该门就是设计上的责任门 ⇒ 这 2 门在对应语料维度上有**独立信号**。
- 「零门红」= 本语料**没被任何门接住**。可能是语料构造不到位（投放点不在门的判据面上），也可能是门存在盲区；**单凭零命中不能推出门无用**，需下一批换投放点复测。
- X2 / X4 的失败面**不在已覆盖的判据上**，属本批语料设计缺口（见 §6）。

---

## 6. 缺口清单

| # | 缺口 | 事实 | 影响 |
|---|---|---|---|
| 1 | **覆盖率** | 运行面 17 行中只有 10 行可摘（10/17）；文档口径 34 行中只有 10 个校验器行（10/34） | 7 个编排行、10 个脚本型门、2 个跳过行、5 个装配/运行期行**本批无结论** |
| 2 | 文档-代码行集差异（代码有、文档无） | `审查报告形态`、`执行串行` 在 `atlas_check.py` 有行，`shared/gates.md` 检索命中 0；`项目布局配置`、`布局提示（code）` 同为条件行且无文档 | 文档口径 34 行**不完整**；按文档对账会漏 4 个运行面行 |
| 3 | 文档-代码行集差异（文档有、代码无） | §2.2 `跨页终态断言落首列页` 无独立代码行（判据内嵌在 `validate_e2e_index`） | 该行**无法单独摘除**，本批不可测 |
| 4 | `--fast` 盲区 | `对齐测试(.atlas/tests)`、`E2E 真跑` 被 `--fast` 跳过 | 2 行未纳入 LOGO |
| 5 | **结构性不可辨** | `validate_design_exemptions`、`validate_adr` 基线即 `SKIP`（前置未满足） | 摘除后除被摘行外零变化 ⇒ 无法评估其收益/风险 |
| 6 | 弱可辨 | `validate_ac_alignment` 基线 `N/A` | 摘除后仅 `N/A→SKIP`，信息量低 |
| 7 | `消融残留` 行不携带门册信号 | 摘除窗口内恒 `ok`；用非默认状态根时曾误报 `WARN`（工具自指伪影） | 该行在 LOGO 矩阵里是恒定噪声项，已用默认状态根规避 |
| 8 | 工具适用性 | `ablation.py` **未拒绝**（触碰面 `.atlas/validators/` 为 **untracked**，`.atlas` 在 git 索引中 0 个文件），故**未退**「批次 02 §1 手工 sha256 协议」，也未改工具 | 无 |
| 9 | 沙箱环境限制（首次） | `ablation.py` 对 `~/.atlas-ablation/roots/<hash>` 做 `chmod 700`，被沙箱拒 | 规避方式：begin 前 `rm -rf` 该 hash 目录（由工具自行创建即可通过）；未改工具 |
| 10 | **pytest 基线未全绿** | 副本可写；收集 **1149** 例。整跑在 18% 处卡于 `tests/test_atlas_verify_playground.py` 的**嵌套 playground 段**（内层 `pytest .atlas/tests` 长时间不返回）；deselect 该 2 例后整跑完成：**1142 passed + 5 skipped + 2 deselected，478 s** | 2 例**未跑完**；**不得写成全绿**；且 LOGO 各轮只跑门册、不跑 pytest，「摘门后测试仍绿」本批无证据 |
| 11 | 语料样本量 | 4 条语料、单快照 | 不能估计门的召回率；X2/X4 零命中需换投放点复测 |
| 12 | 运行期产物变动 | `.atlas/runs/check-events.jsonl` 追加增长（2743 B → 15419 B）；`.atlas/runs/` 下另有 3 个 10-29 的历史嵌套副本（`runs/runs/…`） | 均为 untracked 运行期产物，不影响 `git status`（仍 39 行）；装后即时基线记为 3 文件、收尾为 6 文件，属追加/历史残留而非业务改动 |

---

## 7. 这批能说明 / 不能说明

### 能说明

1. 在**一个真实采用方快照**上，10 个校验器均可机械摘除、跑完仍能完整产出 17 行、还原后 10 个 `.py` 逐文件 sha256 与装后基线**完全一致**。
2. **无硬依赖**：摘任一门都没有把整轮打断（10/10 rc=0）。
3. 门与门之间在本快照上**不串联**：除被摘行外 16 行状态零变化。
4. 成本分布**高度集中**：`validate_testids` 一个门占 58.1%，且是唯一配对差值超出噪声带的门。
5. `validate_stack_profile` 与 `validate_e2e_mocks` 在对应语料上能被**独占接住** ⇒ 有独立信号。
6. 2 个门在本快照上**结构性不可辨**（恒 `SKIP`）——这是快照前置条件问题，不是门的问题。

### 不能说明

1. **不能说明「某门没用」**。零命中（X2/X4）只说明**本语料没打中判据面**；零命中不得作为删门依据。
2. **不能说明跨环境/跨项目的成本排序**。绝对 ms 不可比；本表仅同机同快照内排序。
3. **不能说明 7 个编排行的行为**——它们不是独立文件，本批未摘、未测。
4. **不能说明 `对齐测试`、`E2E 真跑`、§2.3 装配面、§2.4 运行期门**——均未纳入。
5. **不能说明 WARN 处置效果**（本批无 WARN 处置样本）。
6. **不能说明 pytest 全绿**——基线 1149 收集、1142 passed / 5 skipped / **2 例因嵌套 playground 段卡死被 deselect**（未跑完，见缺口 10）；且各轮摘门后**没有配套跑 pytest**，因此「摘门后测试仍全绿」这类断言本批**无法给出**。
7. 不能把「≥ 2 门同红」判成冗余——本批语料里没有出现多门同红样本。

---

## 8. 复算声明（可复算）

- **主快照仓未提交、业务文件零改动**：全程未执行任何 git 写操作（无 `add` / `commit` / `checkout` / `stash` / `reset` / 分支操作）。
- 收尾复核：`git status --porcelain` = **39 行**，内容 sha256 与装前一致；`git diff` 全文 sha256 与装前一致；业务资产组（`product/` 47 文件、`src/` 1364 文件、`.trellis/spec/conventions` 1 文件）组哈希与装后基线逐组相同。
- 摘门面只碰 `.atlas/validators/<gate>.py`（10 次摘除 → 10 次还原，每次还原后 10 个 `.py` 的 sha256 与装后基线一致）；`.atlas` 在 git 索引中 0 个文件（untracked），故 39 行不受任何影响。
- 收尾无 active 消融（`ablation.py status` 输出 `no active ablation`；`.atlas/ABLATION` 不存在）。
- 报告主体用指纹（装配摘要 / 业务 HEAD / 源包 HEAD）代替项目名与绝对路径。

### 复算步骤（任意人可重跑）

```
# 1) 装配后基线
cat <主快照>/.atlas/VERSION            # 摘要 / 时间 / 源包
sha256sum <主快照>/.atlas/validators/*.py
git -C <主快照> status --porcelain | wc -l   # 期望 39

# 2) 单门摘除一轮（示例）
python3 scripts/ablation.py begin --root <主快照> --id G-04 \
  --patch <删除 validate_testids.py 的 unified diff> \
  --scope validators:validate_testids --allow-dirty --timebox 30
python3 scripts/atlas_check.py --root <主快照> --fast --json
python3 scripts/ablation.py restore --root <主快照> --id G-04
sha256sum <主快照>/.atlas/validators/*.py   # 必须与 1) 完全一致

# 3) 源包摘要复核
python3 scripts/pkg_digest.py <源包>         # 期望 b4c1605da2b82a24
```

---

## 9. 需维护者决定

1. `validate_design_exemptions` / `validate_adr` 在缺前置的快照上恒 `SKIP`：是接受「不可辨」，还是要求在普查快照里补齐前置（`design_exemptions` 声明 / ADR 目录）再测？
2. 文档-代码行集差异（`审查报告形态`、`执行串行`、`项目布局配置`、`布局提示（code）`、`跨页终态断言落首列页`）：补文档还是补代码行，需一次裁定。
3. 7 个编排行是否值得单独做「内联函数级」消融（需要改 `atlas_check.py`，本批口径不允许）。
4. pytest 嵌套 playground 段卡死：是否单独立项定位（当前只能记为未跑完）。
