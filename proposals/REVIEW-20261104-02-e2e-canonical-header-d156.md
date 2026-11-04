# 评审记录：H（强制 canonical AC 表头前三列）D156 三态复核

> 评审编号：REVIEW-20261104-02（当日 `REVIEW-20261104-01` 已被 `REVIEW-20261104-01-d156-single-case-signoff` 占用；本记录主题不同，按 `proposals/README.md:60` 无需再加主题后缀，但保留主题段以便区分）
> 评审对象：`proposals/RFC-20261103-08-e2e-dim-header-validation.md` §4.5-b（`715fa0c` / `d2defd2`）；判据 `49689f3`
> 评审结论：**准予——`单案修复（无留出集）` 成立**，附 4 条非阻断整改（C1–C4）。**不宣称闭族。**
> 评审者：外部评审（fresh context；未参与 H 的设计、实施、注释与变异注入；评审在 `49689f3` / `715fa0c` / `d2defd2` 落盘之后开始）
> 评审方式：只读复核 + 规则比对 + 独立重放（在 `/tmp` 用 `git archive 49689f3^` 解出旧树，未改仓内任何文件；原始输出见 §7）

---

## 1. 判定摘要

| 问题 | 判定 | 一句话理由 |
|---|---|---|
| 三态准入（`单案修复（无留出集）`） | **成立** | 输出翻转、反面包、逐表独立均实测成立；③ 的结论成立但作者的论证措辞错位（C2） |
| `场景` 前缀接受 | **有窄漏洞，非阻断** | `startswith("场景")` 会放行任意 `场景…`；影响面是 WARN 级假采信，建议收成两形态显式白名单（C3） |
| 附带改动是否污染判据面 | **不污染，但有一条未被钉住的行为变化** | `_script_inventory` 重构改了 scripts 目录内 `atlas-prepare.mjs` 的哈希 key；与 H 判据无关，不得作为 H 的证据（C4） |
| 计数 183→184 | **一致** | 实测 `184 tests collected`，`shared/gates.md:47` 声明同值 |
| 台账形式闭环 | **未闭合** | `duty-review/QUEUE.md:38` 的 REVIEW 指针仍指 `REVIEW-20261104-01`；RFC §4.5-b 仍写「QUEUE 暂缓」（C1） |

---

## 2. 三态准入逐条（`shared/gates.md:107`）

判据原文口径：留出独立性三条缺一按「同夹具变体」驳回——① 判据输出翻转；② 变异增量杀伤；③ 结构不可达（夹具不可由既有钉夹具只改日期串 / 通道 / 增删行得到）。`单案修复（无留出集）` 须「评审确认 + QUEUE 观察行 owner/期限 + 残留风险入 RFC §4.5」。

| 条 | 作者主张（§4.5-b:162-169） | 本记录结论 | 重放依据 |
|---|---|---|---|
| ① 判据输出翻转 | 旧判据下新钉 `1 failed`，改后 `2 passed` | **成立（实测）** | 旧树重放：非 canonical 列序 `场景 / AC ID / 回指规则 / 适用覆盖维度` 在旧判据下得 `PASS`；新判据下同案 `N/A`。见 §7 ① |
| ② 变异增量杀伤 | 未写，无 M 号 | **不适用（单案态不要求）；但无四段留档** | `.atlas/runs/mutation-proof/` 内无 H 相关条目（`grep -l "canonical\|前三列"` 零命中）。pre-fix 红可视为「回退修复」型退化，但未按四段协议落档 ⇒ 只能算 ①，不能算 ② |
| ③ 结构不可达 | 「翻转输入即表头前三列的次序 / 取值本身，任何『独立』语料仍需构造同一张 AC 表并改表头 ⇒ 同夹具族、结构不可达」 | **结论成立，论证错位** | 见下 |

**对 ③ 的独立判定**：作者的表述接近同义反复——「要测表头判据，输入当然是表头」。这不是「结构不可达」，而是「我能构造的语料长得一样」。按 `REVIEW-20261104-01:38` 与 `:42` 已立的口径，③ 的实质依据应是「**仓内无冻结的非 canonical 表头语料**，任何候选只能由样本/新钉夹具手写改表头或加减列得到」。本记录自行重跑该依据：

- `git grep -n "AC ID" -- "*.md" | grep -v proposals/`：仓内所有 AC 表前三列均为 `AC ID` / `场景…` / `回指规则`（`templates/prd/domain.md:107`、`rings/prd/reference.md:196`、`tests/fixtures/verify_playground/product/prd/home-prd.md:41`）。
- 唯一真实 PRD 样本 `home-prd.md:41` 是 canonical 5 列（`场景（Given / When / Then）`），不翻转。
- 其余「独立」候选只能手写构造，属同一 AC 表夹具族 ⇒ 无可行留出集。

**故 ③ 成立，但 §4.5-b 的措辞须改为上述「无冻结语料」表述（C2，不改变判定）。**

**三态必要条件的实体核对**：

| 条件 | 现状 | 判定 |
|---|---|---|
| 评审确认 | 本记录 | ✅ |
| QUEUE 观察行 owner + 期限 | `duty-review/QUEUE.md:38`：owner = `master`；期限 = 首个真实仓跑 `validate_e2e_index` 后 2 周（不晚于下个 beta 后 2 周，先到为准） | ✅ 实体齐；❌ REVIEW 指针指 `REVIEW-20261104-01`（见 C1） |
| 残留风险入 RFC §4.5 | `RFC-20261103-08:168`「残留面」已写：表头错 ⇒ 无任何信号；第二列前缀属模板兼容口径，出现第二变体须显式登记 | ✅；但 `:169` 仍写「QUEUE 观察行暂缓」，与台账现状（`:38` 已存在）矛盾（C1） |

---

## 3. `场景` 前缀接受是否有漏洞；是否与 D130 一致

**判据事实**：`validators/validate_e2e_index.py:99-110` 中 `hdr[1].startswith("场景")`，第一列 / 第三列逐字，列序严格；`collect_e2e_declared_dims` 在 `:387` 逐表判定，坏表 `continue`、好表照收。

**漏洞（窄）**：前缀会放行一切以 `场景` 开头的第二列——`场景数量` / `场景说明` / `场景化数据` 等。要造成假采信，还需同时满足：第一列逐字 `AC ID`、第三列逐字 `回指规则`、表内另有 `适用覆盖维度` 列。现实语料极难同时命中；且该门输出是 **WARN 级**（AC × 覆盖维度缺口），不是 FAIL 级假绿。故定级 **应修（非阻断）**：建议把前缀收成显式两形态白名单（`场景` ｜ `场景（Given / When / Then）`），既保住 `templates/prd/domain.md:107`，又闭合任意前缀。

**与 D130 的一致性**：`DESIGN.md:599` 的 D130 原文是「域级 PRD 验收标准表增加可选第 4 列…前三列保持不变」；`templates/prd/domain.md:113` 又写「前三列固定（`AC ID` ｜ 场景 ｜ 回指规则）」，而同文件 `:107` 的表头实际是 `场景（Given / When / Then）`。即「固定」在仓内本就包含带括注的场景列。前缀判定是对该既成口径的显式化，**语义上仍指场景列，与 D130 的立意一致**；不一致的只是「固定」一词的字面强度。建议 C3 一并把 `templates/prd/domain.md:113` 的「固定」改成「固定语义与次序，第二列允许 `场景（Given / When / Then）` 括注」，免得下一位读者再把前缀当任意匹配。

**附带记录**：单元格经 `strip_md_cell` 后，`场景 （Given / When / Then）`（`场景` 后有空格）会被判 N/A；属可接受残留（模板不带空格）。

---

## 4. 附带改动是否被夹带进判据面

**（a）`_script_inventory` 单源重构（`scripts/e2e_console.py:140-186`）**

- 方向正确：`scripts_hash:167` 与 `script_file_map:185` 现在消费同一清单，符合 #31 的「不另写第二份枚举」。
- **但存在一条未被钉住的行为变化**：旧 `scripts_hash` 对 `scripts/` 目录内的 `atlas-prepare.mjs` 用 key `atlas-prepare.mjs`；新实现 `:161` 用 `scripts/atlas-prepare.mjs`。项目根钩子的 key 不变（`tests/test_e2e_console.py:1009` 只钉了这一支）。即：**钩子放在 `scripts/` 内的项目，`scripts_hash` 会一次性漂移**，且当前无钉。
- 与 H 的关系：**零**。它是 (b) 路径族内的另一处改动，不能拿来当 H 的独立性证据；须单独立记录或补钉（C4）。

**（b）计数 183→184（`shared/gates.md:47`）**

- 实测 `python3 -m pytest tests/test_validators.py --collect-only -q` = **184 tests collected**，与 `:47` 的「184 条本轮跑绿」一致。
- H 只新增 1 个测试函数、未新增测试文件，`shared/gates.md:113` 的 52 个测试文件不变 ⇒ 计数链自洽。
- **不影响 H 的三态结论**：计数是台账同步，不改变任何判据输出。

---

## 5. 残留（供 QUEUE 观察行引用）

1. **静默 N/A**：表头写错 ⇒ 该表完全无信号（连 WARN 都没有）；若项目把唯一 AC 表写成非 canonical，门只会「什么都不说」，不会提示「你的表没被采信」。这是已接受残留，但观察行须明确「无人误读为维度全丢」。
2. **前缀第三变体**：`场景数量` / `场景说明` 等以 `场景` 开头的异义列会被采信；出现任何新变体须显式登记并重评。
3. **首个真实仓非 canonical 表**：若真实仓出现「合规 canonical 表却被判 N/A」或「非 canonical 被采信」，按 QUEUE 升室判据复评。
4. **`scripts/` 内 `atlas-prepare.mjs` 的哈希 key 漂移**（§4a）：无钉、无基线记录；与本件无关，但不能混入本件的证据链。
5. **无 M 四段留档**：H 只有 pre-fix 红；`.atlas/runs/mutation-proof/` 无对应条目。

---

## 6. 附条件整改（不改变「准予」）

- **C1（台账闭环，须做）**：`duty-review/QUEUE.md:38` 的 REVIEW 指针由 `REVIEW-20261104-01-d156-single-case-signoff` 改为本记录；同时把 `RFC-20261103-08:169` 的「缺独立评审复验与 QUEUE 观察行…暂缓」改为「已由 `REVIEW-20261104-02` 复验、`QUEUE.md:38` 已立观察行」。在改指前，**不得在台账宣称本件为 `单案修复`**（实体虽齐，指针仍指向不裁决 H 的记录，违反「唯一判定记录 = 那份 RFC §4.5 + 其 REVIEW」）。
- **C2（论证措辞，须做）**：§4.5-b「留出集」一句改为「仓内无冻结的非 canonical 表头语料（`git grep` 见 §7 ④）；唯一真实 PRD 样本为 canonical 5 列；任何候选只能手写构造 ⇒ 无可行留出集」，删去「翻转输入即表头本身」这种同义反复。
- **C3（前缀收紧，建议同批）**：`is_canonical_ac_header` 的第二列改为显式两形态（`场景` / `场景（Given / When / Then）`），并在 `templates/prd/domain.md:113` 把「固定」补成「固定语义与次序 + 允许括注」。若暂不收，须把「任意 `场景…` 前缀」写进残留面与 QUEUE 观察项 ③。
- **C4（夹带改动，须单独记录）**：为 `scripts/atlas-prepare.mjs` 的哈希 key 变化补一条钉（`tests/test_e2e_console.py` 内既有 `scripts_hash` 钉加分支）或写进 `RFC-20261103-09` §5 遗留，明确「这是单源化的预期基线漂移，不是 H 的一部分」。

---

## 7. 重放与原始输出

```text
① pre-fix 红（/tmp 旧树，未改仓内文件）
$ git archive 49689f3^ | tar -x -C /tmp/atlas-replay
$ git show 49689f3:tests/test_validators.py > /tmp/atlas-replay/tests/test_validators.py
$ git show 49689f3:tests/fixtures/e2e_coverage_dims_golden.json \
    > /tmp/atlas-replay/tests/fixtures/e2e_coverage_dims_golden.json
$ cd /tmp/atlas-replay && python3 -m pytest \
    tests/test_validators.py::test_e2e_dim_header_requires_canonical_first_three_columns -q
E  AssertionError: ({'columns': ['场景', 'AC ID', '回指规则', '适用覆盖维度'], 'accepted': False},
                     {'check': 'AC × 覆盖维度', 'level': 'PASS', 'detail': '0 条覆盖就绪 AC 声明维度全量覆盖'})
E  assert 'PASS' == 'N/A'
1 failed in 0.28s

② post-fix 绿（仓内）
$ python3 -m pytest tests/test_validators.py::test_e2e_dim_header_requires_canonical_first_three_columns \
    tests/test_validators.py::test_e2e_dim_header_located_by_name -q
2 passed in 0.07s

③ 提交声称的两组回归
$ python3 -m pytest tests/test_validators.py tests/test_e2e_console.py -q
215 passed in 2.25s
$ python3 -m pytest tests/test_map_anchors.py -q
8 passed in 0.13s

④ 留出语料是否存在（仓内）
$ git grep -n "AC ID" -- "*.md" | grep -v proposals/
（AC 表头仅见 DESIGN.md:191 / docs/design/prd-ring.md:79 / rings/prd/reference.md:147,196 /
  templates/prd/domain.md:107 / tests/fixtures/verify_playground/product/prd/home-prd.md:41，
  前三列均为 AC ID / 场景… / 回指规则；其余命中为「结构类 / 不可验 AC 清单」两列表，不含适用覆盖维度）

⑤ 计数
$ python3 -m pytest tests/test_validators.py --collect-only -q
184 tests collected in 0.04s

⑥ H 的变异留档
$ grep -l -i "canonical\|前三列" .atlas/runs/mutation-proof/*.txt
（零命中）
```

---

## 8. 本记录证明什么 / 不能证明什么

**证明了什么**：

- 「旧判据会把非 canonical 列序按 PASS 采信、新判据按 N/A」在**同一夹具、同一断言**下可重放（§7①/②），且反面包覆盖接受与拒绝、逐表独立不串味（新钉 mixed 用例）。
- 仓内**当前**不存在可翻转为非 canonical 的冻结 PRD 语料（§7④）⇒ 无可行留出集，`单案修复（无留出集）` 的实体条件成立。
- 提交声称的 215 / 8 / 184 三个数字与本机重放一致。
- `_script_inventory` 的重构与 H 判据互不依赖；H 的三态不因它而成立或失效。

**不能证明什么**：

- **不能证明闭族**：本件只把「前三列」收紧；表头错 = 静默 N/A 的假绿面仍在，第二列前缀的异义变体仍可能被采信（C3）。
- **不能证明仓外语料无翻转**：只能证明本仓无冻结语料；真实仓一旦出现非 canonical 表头或新场景列变体，须按 QUEUE 升室重评。
- **不能证明前缀与 D130 字面完全一致**：D130 / 模板的「固定」本就含括注变体；本记录只判「语义与次序一致」，不替维护者改口径。
- **不能替代实现评审与门证据**：本记录不重放全量测试套件，不构成 `atlas_check` 门绿；#31 重构那条基线漂移未在本件取证（C4）。
- **不能证明三态永真**：`单案修复` 是当下判定，不是闭族；观察行到期必须复评。
