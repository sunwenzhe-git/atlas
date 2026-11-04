# 修 #31：运行产物不再进入 `scripts_hash`

> 提案编号：RFC-20261103-09
> 提案作者：@维护者（本批由 Atlas 会话实施）
> 关联状态：已合并 (Merged)
> 影响范围：校验器/脚本 (scripts) | 环契约 (rings) | 测试 (tests) | `DESIGN.md` D128 边界补记

---

## 1. 现象与取证 (The Problem & Evidence)

### 1.1 触发形态（抽象）

* **规则 / 环节**：E2E 环的评审指纹（`DESIGN.md` D128；逐用例 `prov.fp` 见 D174）。控制台以 `scripts_hash` 判定 `review_state`（`fresh` / `stale`）。
* **触发时机**：真实跑完一条用例后（Playwright 在 `product/e2e/scripts/.atlas-run/` 写 `results.json`、`.last-run.json`、trace 等）。
* **具体行为（修复前）**：`scripts_hash` 与逐文件清单 `script_file_map` 各持一份排除清单，目录族不含 `.atlas-run`，后缀闭集只有 `.trace` / `.png` / `.webm` / `.last-run.json`。于是 `.atlas-run/results.json` 被计入指纹 ⇒ 跑一次就变指纹 ⇒ 已审条目假 `stale`，正面违反 D128「执行产物不得致指纹假漂移」。

### 1.2 客观证据与日志 (Minimal Evidence)

`duty-review/bugs.md` #31 原文记录的实证 = `REVIEW-20261103-01` Major-2 冻结副本实验：写入 `.atlas-run/results.json` 前后 `h1 ≠ h2`；而 `.last-run.json` 因后缀免疫正常。修复前的两处清单（同文件两份拷贝）：

```python
# aaa9dcb:scripts/e2e_console.py:146 / :181（scripts_hash 与 script_file_map 各一份）
any(part in rel for part in ("test-results", "playwright-report", ".atlas-auth", "node_modules"))
# :148 / :183
rel.endswith((".trace", ".png", ".webm", ".last-run.json"))
```

`_support/layout.py:120` 定义运行目录 = `product/e2e/scripts/.atlas-run`，因此 `.atlas-run/` 是整个运行产物树的唯一落点。

---

## 2. 决策与权衡 (The Decision & Trade-offs)

### 2.1 核心定案 (The Decision)

* **清单单源**：新增模块常量 `_RUNTIME_PATH_PARTS`（含 `.atlas-run`）与 `_RUNTIME_SUFFIXES`，`scripts_hash`（[:153](file:///Users/sunwenzhe/Desktop/atlas/scripts/e2e_console.py#L153)）与 `script_file_map`（[:188](file:///Users/sunwenzhe/Desktop/atlas/scripts/e2e_console.py#L188)）共用，消除「两处清单一处漏」的根因。
* **修复边界（写死）**：排除以「目录族 `test-results/`、`playwright-report/`、`.atlas-auth/`、`node_modules/`、`.atlas-run/` + 后缀 `*.trace`、`*.png`、`*.webm`、`*.last-run.json`」为界。
  * 已排除：`.atlas-run/` 树内的 `results.json`、`.last-run.json`、trace/截图等全部运行产物。
  * 仍计入：`product/e2e/scripts/` 下**其它**白名单扩展名（`.ts` / `.js` / `.mjs` / `.json` / `.yaml` / `.yml`）与 `atlas-prepare.mjs`——真实脚本内容变化仍致指纹变化。
  * **不宣称**「判分载体均已指纹免疫」：`.atlas-run/` 之外的运行产物（例如项目把 `results.json` 写到 `scripts/` 根）仍会被计入，见 §5 遗留。
* **D128 / D174 表述核对**：
  * D128 ① 的目标句「执行产物不得致指纹假漂移」本来就包含此案；本批为实现补齐，并在 D128 ① 边界补记 `.atlas-run/`，**不新增 D 行**（语义未变）。
  * D174 的 `prov.fp = {script, block, rest, shared, app}` 按内容判定：`script` 指用例自身 spec、`shared` 指 import 闭包、`app` 排除 E2E 环——`.atlas-run/results.json` 不参与这三者，故 D174 表述**仍成立**；本批只消除旧账本回退口径（D128 HEAD+全局散列）的假漂移来源。

### 2.2 考虑过的备选方案及否定理由 (Considered Alternatives)

* **备选 A：只在两处目录族补 `.atlas-run`（不改常量）**
  * *否定理由*：能修本次症状，但两份清单继续各自维护；下一次新增运行目录/后缀仍会单边漏。采用「补 `.atlas-run` + 常量化单源」。
* **备选 B：只显式排除 `results.json`**
  * *否定理由*：`.atlas-run/` 内还有 trace.zip、截图、nested `.last-run.json` 之外的运行件；逐文件名列举会继续漏。
* **备选 C：只在 `scripts_hash` 排除、`script_file_map` 不动**
  * *否定理由*：逐文件清单仍把 `results.json` 当脚本键，控制台按文件复算会继续漂移；且保留两份清单的分叉。
* **备选 D：把 `scripts/` 下所有 `.json` 排除**
  * *否定理由*：一刀切会造成假绿（真实脚本/数据 `.json` 变化不再触发 `stale`），违反「真实脚本内容变化仍影响指纹」的钉。

### 2.3 必须警惕的刺痛代价与兼容性影响 (Trade-offs)

* **指纹语义**：在 `.atlas-run/` 内的历史账本从「可能 stale」变为「fresh/按内容判定」——这是修复目标；不会把已审条目错误地变成未审。
* **误伤面**：若项目把**手写脚本**放在 `.atlas-run/` 下（不符合约定），将不再参与指纹；契约已明写该目录是运行产物落点。
* **装配**：`scripts/e2e_console.py` 改动，采纳仓按常规 `install.sh --update` 生效。
* **计数**：不新增脚本、不新增测试文件 ⇒ `install.py` 65 条、`gates.md` 52 个测试文件、10 个校验器均不变。

---

## 3. 改动面清单 (Affected Surface)

- [x] **代码逻辑**：`scripts/e2e_console.py`（两份清单常量化 + `.atlas-run` 入族）
- [x] **测试防线**：`tests/test_e2e_console.py::test_scripts_hash_excludes_runtime_artifacts_and_whitelists_scripts` 扩 3 断言；变异 **M175**
- [x] **契约/文档**：`rings/e2e/reference.md` §10.1 指纹行「#31 修复边界」；`DESIGN.md` D128 ① 边界补记；`duty-review/bugs.md` #31 → `已修·待复验`
- [x] **留出验证（§4.5）**：触发面 (b) 命中 ⇒ 三态 = `单案修复（无留出集）`，观察行见 `duty-review/QUEUE.md`
- [ ] **版本装配**：不涉及

---

## 4. 验证与测试结果 (Verification)

```bash
python3 -m pytest tests/ -q
python3 scripts/atlas_check.py --fast
python3 -m pytest tests/test_map_anchors.py -q       # 未动计数/锚，仍复跑
python3 -m pytest tests/test_gate_registry.py -q
```

* **钉的三条断言**：① `.atlas-run/` 三件（`results.json` / 嵌套 `.last-run.json` / `trace.zip`）写入后 `scripts_hash` 不变，且 `script_file_map` 不出现 `.atlas-run` 键；② 运行产物**内容再变**仍不变（不是仅首次创建免疫）；③ 改 `demo.spec.ts` ⇒ 哈希变化（防一刀切假绿）。
* **结果**：全量 `1144 passed, 5 skipped in 1705.24s (0:28:25)`；`atlas_check --fast` = exit 0，但源包态 10 个校验器全部 `SKIP 校验器不存在`（仅 write-claim / ablation 行真跑），**不构成门证据**；门证据 = 全量 pytest + 定向钉；`test_map_anchors` = 8 passed；`python3 -m pytest tests/test_gate_registry.py -q` = **3 passed**（原记 9 passed 有误）。
* **M175 四段协议**：基线 GREEN → 注入（摘 `_RUNTIME_PATH_PARTS` 里的 `.atlas-run`）RED → 逐字节还原（sha256 一致）→ 复绿；报告 = `.atlas/runs/mutation-proof/M175.txt`。

### 4.5 留出验证（系统性修复必填；`RFC-20261026-03`）

* **(a) §1 引子族锚 / ≥3 条独立重复 finding**：否——单条 `bugs.md` #31 + 1 条 REVIEW finding（Major-2）。
* **(b) 改脚本/契约判据且 diff 落在 DR4 段级锚路径族**：**命中**。原始 `git show --stat`（提交 `5a36129`，11 个文件；此前正文手抄只列 5 个，属截断）：

```text
$ git show --stat --oneline 5a36129
5a36129 fix(e2e): keep run artifacts out of scripts hash (#31)
 DESIGN.md                                          |   2 +-
 docs/map/atlas-map.html                            |   4 +-
 docs/map/e2egen.md                                 |   4 +-
 docs/map/index.md                                  |   2 +-
 duty-review/QUEUE.md                               |   1 +
 duty-review/bugs.md                                |   2 +-
 ...W-20261103-04-e2e-scripts-hash-run-artifacts.md |  51 ++++++++++
 ...C-20261103-09-e2e-scripts-hash-run-artifacts.md | 106 ++++++++++++++++++++++
 rings/e2e/reference.md                             |   2 +-
 scripts/e2e_console.py                             |  15 ++-
 tests/test_e2e_console.py                          |  16 ++++
 11 files changed, 193 insertions(+), 12 deletions(-)
```

E2E 段「指纹假漂移」族的路径族含 `scripts/e2e_console.py` + `rings/e2e/reference.md` ⇒ 保守判命中；`closeout_derive` 原始输出见 RFC-20261103-08 §4.5 同形（步骤 1/2/3/5/7 均自动/人工触发，本清单不含语义触发行）。
* **留出集可行性（三条独立性）**：① 判据输出翻转的输入不止 `.atlas-run/` 下某一文件——目录内任一文件（`results.json` / `.last-run.json` / trace / 截图 / 嵌套件）及其内容变化都能翻转 `scripts_hash` 或判分，但它们都必须落在 `.atlas-run/` 这一运行目录内（同夹具族）；② M175 证明注入后既有钉绿而新钉红，但新钉夹具即 #31 的变体；③ 任何「独立」语料仍需构造同一运行目录 ⇒ 结构不可达。=> **无可行留出集**。
* **残留面（显式）**：`_RUNTIME_PATH_PARTS` / `_RUNTIME_SUFFIXES` 已单源，但白名单扩展名（`.ts` / `.js` / `.mjs` / `.json` / `.yaml` / `.yml`）与 `atlas-prepare.mjs` 的枚举仍在 `scripts_hash` 与 `script_file_map` 各写一份（`scripts/e2e_console.py:160-165` / `:195-200`）；新增扩展名时仍可能单边漏。
* **pre-fix 红**：有——`REVIEW-20261103-01` Major-2 冻结副本（h1≠h2）。
* **post-fix 绿**：§4 钉全绿 + M175 还原复绿。
* **反面包**：真实脚本内容变化仍致哈希变化（断言③）。
* **三态**：`单案修复（无留出集）`——不宣称闭族；观察行 = `duty-review/QUEUE.md` 观察室（owner = 本批实施者；补验期限 = 首个真实仓真跑后 2 周）。
* **评审**：`proposals/REVIEW-20261103-04-e2e-scripts-hash-run-artifacts.md`（技术方案 + 事实核查 + 重放）。

---

## 5. 遗留（显式，不冒充已覆盖）

1. `product/e2e/scripts/` 根下、非 `.atlas-run/` 的运行产物若仍以白名单扩展名出现，仍会计入指纹（本批未排除，避免一刀切假绿）；
2. `app` 散列（D174）与 `shared` import 闭包不在本批范围；未做全量判分载体盘点；
3. #31 的「真实仓复验」未完成——状态 `已修·待复验`，出库前需一次真实跑后控制台不再假 `stale` 的实证。
