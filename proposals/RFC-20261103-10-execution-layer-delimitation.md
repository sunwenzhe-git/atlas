# P1-3 定界：执行层 ⇄ Atlas 的边界（四块逐块裁定）

> 提案编号：RFC-20261103-10
> 提案作者：@维护者（本批由 Atlas 会话实施）
> 关联状态：已定案 (Accepted)
> 影响范围：登记簿 (proposals) | 纯定界：**不改代码、不改门、不新增机器判据**

---

## 1. 现象与取证 (The Problem & Evidence)

### 1.1 触发形态（抽象）

* **规则 / 环节**：`proposals/BACKLOG-execution-layer.md` §5「当前 Atlas 已承担、未来需定界的执行层工作」——四块各自只有「需要定界」的登记，没有「迁出 / 保留 / 双轨」的结论；卷首边界判据（Atlas 出**判据、账本、覆盖维度、门禁**；执行层出**动作、运行、证据、报告**）只给了方向，未落到四块。
* **触发时机**：维护者拍 P1-3 = B（先做定界、不开工），前置 = `duty-review/bugs.md` #31 修复（已落 `5a36129`）。
* **具体行为（未定界时）**：自建执行层一旦开工，四块任一块都可能被两处各实现一遍——最常见的是「Atlas 继续在 `atlas_verify` 里跑 Playwright，执行层也跑一遍」⇒ 双跑清空首跑留证（D108 反面）；或「执行层直接写用例索引状态」⇒ 账本出现两个写者。

### 1.2 客观证据与日志 (Minimal Evidence)

登记面原文（`proposals/BACKLOG-execution-layer.md:50-57`，摘）：

```text
## 5. 当前 Atlas 已承担、未来需定界的执行层工作
- **Playwright 脚本生成与执行**：`scripts/gen_e2e_scripts.py`、`e2e_console.py`、`atlas_verify.py`（D150/D151）。
- **独立审查执行器**：现由 `stack-profile` 声明、宿主子代理执行；执行层若接管，须保留 fresh context、档位不低于生成者、扇出上限 4、预算熔断。
- **项目数据准备钩子**：`atlas-prepare.mjs` 的内容归项目，调度归执行层；`ATLAS_CASE_ID` 语义不得改。
- **E2E 运行目录判分载体落点**：`results.json` / `.last-run.json` 现与失败留证（trace / 截图）同目录（`.atlas-run/`）；证据面 ⇄ 判分面已契约化（`RFC-20261103-02`，`shared/global-rules.md` §17），物理**迁出 / 保留 / 双轨**待定界。
```

第 ④ 块的判定必须建立在本轮 #31 的**真实修复边界**上（`scripts/e2e_console.py:132-133`，提交 `5a36129`）：

```text
132:_RUNTIME_PATH_PARTS = ("test-results", "playwright-report", ".atlas-auth", "node_modules", ".atlas-run")
133:_RUNTIME_SUFFIXES = (".trace", ".png", ".webm", ".last-run.json")
```

即：`.atlas-run/` **整树**已排除于 `scripts_hash` 与逐文件清单 `script_file_map`；`.atlas-run/` **之外**、以白名单扩展名（`.ts` / `.js` / `.mjs` / `.json` / `.yaml` / `.yml`）落盘的运行产物**仍计入**指纹（`RFC-20261103-09` §5 遗留 1）。因此本 RFC 任何一处都不得写成「判分载体均已指纹免疫」。

---

## 2. 决策与权衡 (The Decision & Trade-offs)

### 2.1 核心定案 (The Decision)

四块**逐块**裁定，判据 = 卷首边界（判据 / 账本 / 覆盖维度 / 门禁 ⇄ 动作 / 运行 / 证据 / 报告），**按「物」不按「模块」**：同一模块可以一半迁出、一半保留。

| # | 块 | 现状承载 | 裁定 | 一句话理由 |
|---|---|---|---|---|
| ① | Playwright 脚本生成与执行（D150/D151） | `scripts/gen_e2e_scripts.py`（生成）、`scripts/e2e_console.py` / `scripts/atlas_verify.py`（执行与留档） | **双轨** | 生成 = 判据的确定性派生物，留 Atlas；执行 = 动作 / 运行 / 证据 / 报告，迁执行层 |
| ② | 独立审查执行器 | `stack-profile` 声明 + 宿主子代理执行（`shared/independent-review.md` §6/§10） | **迁出** | 判据（审查骨架 / 报告字段 / 并发阈值）留 Atlas，执行动作归执行层 |
| ③ | 项目数据准备钩子（`atlas-prepare.mjs` / `ATLAS_CASE_ID`） | 控制台与 `atlas_verify` 调用（D110/D121） | **迁出（调度面）** | 脚本内容归项目、调度归执行层；`ATLAS_CASE_ID` 语义与「失败即拒」判据留 Atlas |
| ④ | E2E 运行目录证据面 ⇄ 判分面物理落点 | `.atlas-run/` 内同目录（`_support/layout.py:120`） | **保留** | 目录族指纹排除已消除假漂移；§17 只需「可区分 + 有清单」，物理同目录不违约 |

### 2.2 硬接口（写死，可检查）

**权威与写者**（每一行只有一个权威侧；「可检查落点」全部指向**既有**机器面，本 RFC 不新增判据）：

| 跨边界物 | 权威侧 | 唯一写者 | 跨边界形态 | 失败归属 | 可检查落点（既有） |
|---|---|---|---|---|---|
| 判据：AC 账本 / 用例索引 / 覆盖维度 / 门定义 | **Atlas** | Atlas | 执行层**只读** | 判据或门误判 ⇒ Atlas | `validators/`、`atlas_check` 退出码 |
| 生成物：spec / `playwright.config.ts` / setup / `atlas-hold.ts` | **Atlas** | Atlas（确定性派生） | 执行层只读，不得手改 | 生成物与契约不符 ⇒ Atlas「生成物最新」门 | `atlas_check`「生成物最新」行 |
| 动作序列：pre → run → report | **执行层** | 执行层 | 顺序与前置由 Atlas 契约声明（D150 四步） | 排错、起不动、429、预算熔断 ⇒ 执行层 | 报告里「已跑 M/N」字段（EL-16） |
| 账本写面：索引状态回填 / 控制台 `events.jsonl` | **Atlas** | Atlas（`e2e_console.writeback` / `atlas_verify` backfill） | 执行层交 `results.json`，由 Atlas 回填 | 回填错写 ⇒ Atlas | `validate_e2e_index.py`、D151 |
| 运行：进程启动 / 并发 / 超时 / 预算 | **执行层** | 执行层 | Atlas 只声明上限（扇出 ≤4、180s prepare、120s 用例） | 超限 / 超时 ⇒ 执行层，结论 = 未执行 | `shared/independent-review.md` §6、D110/D121 |
| 证据：`trace.zip` / `test-failed-*.png` / `*.webm` | **执行层** | 执行层 | Atlas **只读**证据面（§17） | 证据缺失 ⇒ 执行层（不得折算成 pass） | `rings/e2e/reference.md` §10.1 二分表 |
| 报告：`results.json`（机器面）+ 人读报告 | **执行层** | 执行层产出，**字段集由 Atlas 定** | `status` / `expected` 等字段不得擅自扩展 | schema 漂移 ⇒ Atlas 门或回填报错 | §10.1 判分面清单 |
| 环境 / 准备失败 | **执行层** | 执行层 | 必须显式标注 `env` / `prep_failed` | 环境红 / 准备失败 ⇒ 执行层，不得记 pass，也不得记用例 fail | D110「失败即拒」、bugs.md「栈起没起」观察行 |

**四条硬约束（跨块）**：

1. **单运行器**：同一工作树同一时刻只允许一个 Playwright 运行器（D108 单跑 + 首跑留证窗口）。双轨期间若执行层接管运行，`atlas_verify` 的 run 步必须显式移交给执行层，不得两边各跑一次。
2. **账本单写者**：执行层不得写 `product/e2e/cases/*.md` 索引状态、`reviews/console/events.jsonl` 与任何回填面；只交 `results.json` 与报告。
3. **生成物只读**：执行层不得改写 `product/e2e/scripts/` 下的生成物；发现生成物与契约不符 ⇒ 上报 Atlas 重新生成，不得就地修补（否则「生成物最新」门的对照基线失效）。
4. **语义冻结**：`ATLAS_CASE_ID`（D121：逐用例 = 用例 ID；批级 = `verify-batch`）、环境键（`ATLAS_BASE_URL` / `ATLAS_SLOWMO` / `ATLAS_WAIT_TIMEOUT_MS` / `ATLAS_EXPECT_TIMEOUT` / `ATLAS_REFRESH_SETTLE` / `ATLAS_REQUEST_TRACE` / `ATLAS_KEEP_OPEN` / `ATLAS_RESULT_FILE`）与 `results.json` 字段集，迁出后**逐字节不变**；扩展须另立 RFC。

### 2.3 第 ④ 块的判定依据（#31 真实边界，逐项）

* **已排除（`scripts_hash` / `script_file_map` 均不收录）**：`.atlas-run/` **整树**——含 `results.json`、`.last-run.json`、`trace.zip`、截图、`*.webm` 与任意嵌套文件；以及目录族 `test-results/`、`playwright-report/`、`.atlas-auth/`、`node_modules/`；后缀 `.trace` / `.png` / `.webm` / `.last-run.json`。
* **仍计入**：`product/e2e/scripts/` 下白名单扩展名（`.ts` / `.js` / `.mjs` / `.json` / `.yaml` / `.yml`）与 `atlas-prepare.mjs`。即**真实脚本内容变化仍驱动指纹变化**（防一刀切假绿的钉：`tests/test_e2e_console.py` 断言③）。
* **判定**：`保留`——物理同目录。理由是**两个动机都不再指向迁出**：(a) 指纹假漂移已由目录族排除消除（`5a36129` / M175）；(b) §17 的纪律只要求「证据面与判分面可区分且有清单」，`rings/e2e/reference.md` §10.1 二分表已满足。
* **升格条件（原样保留，不改）**：出现第一个自动改进 / 诊断消费者，或目录出现清单外第三类载体 ⇒ 白名单升机器门 + 评估判分载体物理迁出（另立 RFC）。
* **遗留（显式，不冒充已覆盖）**：
  1. `.atlas-run/` 之外、以白名单扩展名落盘的运行产物仍计入指纹（`RFC-20261103-09` §5 遗留 1）；若项目把判分载体写到 `scripts/` 根，本块判定须重议；
  2. D174 的 `app` 散列与 `shared` import 闭包未做判分载体全量盘点；
  3. 真实的「自动消费者」尚未出现 ⇒ 升格条件的第一支未验证。

### 2.4 考虑过的备选方案及否定理由 (Considered Alternatives)

* **备选 A：四块全部迁出执行层**
  * *否定理由*：生成物是判据的确定性派生物（零业务常数、`生成物最新` 门看守），迁出即造第二个判据源；账本与门禁迁出更直接违反卷首边界。
* **备选 B：四块全部保留在 Atlas**
  * *否定理由*：动作 / 运行 / 证据 / 报告本就是执行层的产出；保留会让 Atlas 继续长执行器，正是「两处各长一套」要防的形态。
* **备选 C：① 整块保留（含运行）**
  * *否定理由*：D150 已把 `run` 落在 `atlas_verify`；执行层再跑一次即双跑，首跑留证被第二次起跑清空（D108 反面）。
* **备选 D：④ 判分载体物理迁出**
  * *否定理由*：当前无清单外第三类载体、无自动消费者，迁出收益为零；且会牵动 `atlas_verify` / 控制台的读取路径与「起跑即清空 outputDir」语义，属自找回归。触发升格条件时再另立 RFC。

### 2.5 必须警惕的刺痛代价与兼容性影响 (Trade-offs)

* **本 RFC 零代码、零门、零测试钉**：只改登记簿与提案文件。既有 1144 项测试与 `atlas_check --fast` 不受影响。
* **过渡期风险**：双轨切分前，`atlas_verify` 仍是唯一运行者；切分时必须一次性把 run 步移交并删除旧入口，不得保留两条并行通道。
* **执行层实现自由度**：进程形态、并发实现、工具选择归执行层；但 fresh context、档位不低于生成者、扇出 ≤4、预算熔断、`executed` 标记等**判据**不随迁出而放宽。

---

## 3. 改动面清单 (Affected Surface)

- [x] **登记簿**：`proposals/BACKLOG-execution-layer.md` §5 四块各追加定界结论 + 日期 + 落点（遵守 §7 只增不删）
- [x] **值班台账**：`duty-review/QUEUE.md` P1-3 归档行追加交付记录
- [x] **提案记录**：本 RFC + `proposals/REVIEW-20261103-05-execution-layer-delimitation.md`
- [ ] **代码逻辑**：无（纯定界）
- [ ] **测试防线**：无新判据 ⇒ 无新钉、无变异
- [ ] **留出验证（§4.5）**：不适用（未改门 / 校验器 / 契约判据）
- [ ] **版本装配**：不涉及

---

## 4. 验证与测试结果 (Verification)

```bash
python3 -m pytest tests/ -q
python3 scripts/atlas_check.py --fast
python3 -m pytest tests/test_map_anchors.py tests/test_gate_registry.py -q
```

* **结果**：全量 `1144 passed, 5 skipped in 1726.90s (0:28:46)`；`atlas_check --fast` = `OK`；`test_map_anchors` + `test_gate_registry` = 11 passed。

### 4.5 留出验证（系统性修复必填；`RFC-20261026-03`）

* **触发面核对**：**(a) 否**（非系统性修复，无族锚、无 ≥3 条重复 finding）；**(b) 否**——本批 `git diff --name-only` 只落 `proposals/`、`duty-review/`，对照 `scripts/closeout_derive.py:event_path_tokens`（契约族 = `shared/`、`rings/`、`apply/`、`atlas.config.yaml`；脚本族 = `scripts/`、`tests/`）**零命中**，且本批未改门 / 校验器 / 契约判据。
* **结论**：`不适用`（纯文档定界，不产生判据变化）。

---

## 5. 遗留与后续（显式）

1. **只定界、不落代码**：执行层尚未自建；四块的切分点落地须另立 RFC（含 EL-05 的调度语义统一）。
2. **④ 的遗留**见 §2.3：`.atlas-run/` 之外的判分载体仍计入指纹；自动消费者未出现。
3. **② 的形态选择**（CLI 进程 vs 子代理）归 `product/stack-profile.yaml` 的 `impl_review` 声明，执行层接管后不得降低独立性判据。
4. 本 RFC 的「可检查落点」全部引用既有机器面；若后续有人把其中任一条升成机器门，按 `shared/gates.md` 流程另立 RFC，不在本文件内扩判据。
