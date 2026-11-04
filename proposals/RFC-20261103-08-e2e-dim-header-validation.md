# E2E 第 4 列按表头名校验（Batch B 半件）

> 提案编号：RFC-20261103-08
> 提案作者：@维护者（本批由 Atlas 会话实施）
> 关联状态：已合并 (Merged)
> 影响范围：环契约 (rings) | 校验器 (validators) | 测试 (tests) | 文档计数（`shared/gates.md` / `docs/map`）

---

## 1. 现象与取证 (The Problem & Evidence)

### 1.1 触发形态（抽象）

* **规则 / 环节**：`validators/validate_e2e_index.py` 的「AC × 覆盖维度」门（`DESIGN.md` D130；解析单源 = `_support/ac_coverage.py::parse_dims_cell`，D153）。
* **触发时机**：域级 PRD 的验收标准表第 4 格被当作 E2E 覆盖维度声明时（`atlas_check` / `validate_e2e_index.py`）。
* **具体行为**：改动前（HEAD `aaa9dcb`）该门用**位置式正则**直接吃表格行第 4 格，**不看表头名**：

```python
# HEAD aaa9dcb:validators/validate_e2e_index.py:665（改动前）
for m in re.finditer(
    r"^\|\s*`?(AC-[A-Z0-9]+-\d{3})`?\s*\|[^|\n]*\|[^|\n]*\|([^|\n]+)\|", seg, re.M
):
    dims, _looks = parse_dims_cell(m.group(2))
```

于是任何 4 列 AC 表——哪怕第 4 列表头叫作 `覆盖维度` / `备注` / 别的名字——都会被当成合法声明；只有「未声明」才走 N/A。

### 1.2 客观证据与日志 (Minimal Evidence)

位置式正则对**表头不符**的表照样命中（在仓内直接复算，非推测）：

```text
$ python3 - <<'PY'
# 表头 = `覆盖维度`（不是契约名 `适用覆盖维度`）
# | AC ID | 场景 | 回指规则 | 覆盖维度 |
# | `AC-HOME-001` | 首页展示正常 | HOME-R-001 | C01-C02 |
PY
旧位置式正则命中: [('AC-HOME-001', ' C01-C02 ')]
```

同一语料改为表头 `适用覆盖维度` 后，结论完全相同——**表头在此改动前不构成判据**，这就是缺口。

> 范围声明：本批只做「表头名校验」。weak-only WARN（`blocked/skipped/prototype-pass` 记 weak、某维度只被 weak 覆盖 ⇒ WARN）**明确不在本批**，见 §5。

---

## 2. 决策与权衡 (The Decision & Trade-offs)

### 2.1 核心定案 (The Decision)

* **方案总结**：E2E 维度列改为**按表头名定位**。唯一合法表头逐字为 `适用覆盖维度`（模块常量 `E2E_DIM_HEADER`）；表头不符 ⇒ **该表按「未声明」跳过**（`declared_ac_dims` 不从中取值），门对该文件按 N/A 兜底；**逐表独立**，一张坏表不擦掉同文件的好表。
* **实现落点**：
  * 表切分复用 D153 已落地的单源 `_support/ac_coverage.py::iter_md_tables`（与 `validate_e2e_index.tables()` 已有奇偶校验钉，`tests/test_shared_kernel.py`）；
  * 单元格解析仍走 `parse_dims_cell`（D153 单源，本文件不自持第二份 parser）；
  * 新增 `collect_e2e_declared_dims(prd_files)`，逐表：表头须含 `AC ID` 与 `回指规则`，且含 `适用覆盖维度`；`dim_idx = hdr.index(E2E_DIM_HEADER)`（按名而非按位）。
* **为何这是正解**：把「列叫什么」纳入判据，消除「第 4 格写什么都算声明」的静默误读；同时因为按名取列，列顺序变化不再改变语义。`atlas_check.py:234-243` 的 N/A 语义（D153 落地）不动。

### 2.2 考虑过的备选方案及否定理由 (Considered Alternatives)

* **备选 A：暂缓（只登记缺口）**
  * *否定理由*：位置式误读是**判据性缺口**（错表头可产生假 PASS / 假 WARN），且修复面只在一个函数内；暂缓的边际收益低于其持续误导成本。
* **备选 B：完整 Batch B（表头校验 + weak-only WARN 一次做完）**
  * *否定理由*：weak-only 会首次把 `prototype-pass` 存量用例拉进判据（`rings/e2e/reference.md` §5.2 状态闭集 = `red|green|blocked|skipped`，`prototype-pass` 为 E0 历史终态），属于「把红灯训练成噪声」的独立风险面；应与表头校验分开评估。
* **备选 C：只做表头校验半件（本批采纳）**
  * *采纳理由*：只动一个解析函数；D130 正/反钉与 M131 在合法 4 列表头语料下逐字节不变；新增钉可把「错表头 ⇒ N/A」「一坏一好互不擦除」钉死。
* **备选 D：正式砍掉**
  * *否定理由*：缺口仍在，且 D153 的「疑似后端列」规则与第 4 列定位相关，长期会持续产生误读。
* **备选 E：把整段解析真迁 `validate_e2e_index.tables()`**
  * *否定理由*：`tables()` 是**本文件内**服务索引 / 页面表（`validate_e2e_index.py:225`，调用点 `:371` / `:529`）的切分器；D153 的方向是把「表切分 + 单元格解析」收敛到 `_support/ac_coverage.py`（同源奇偶钉已在 `tests/test_shared_kernel.py`）。真迁 `tables()` 会造成第二条切分路径或额外奇偶负担，收益为零。故采用「`iter_md_tables` + 表头索引」而不是「`tables()` 迁移」。

### 2.3 必须警惕的刺痛代价与兼容性影响 (Trade-offs)

* **行为变化面**：表头不是 `适用覆盖维度` 的 4 列 AC 表，从「按第 4 格吸收」改为「按未声明跳过」——对合法表零变化；对历史错表头表可能从 WARN 变 N/A（这正是修复目标）。**名单式记录**：不新增 WARN 文本，避免噪声。
* **存量项目**：契约 `rings/e2e/reference.md` §5.2 已写明合法表头；错表头属不规范写法，不需要 `atlas init`。
* **装配**：校验器源码改动，采纳仓需按常规 `install.sh --update` 更新装配副本（不涉及 `refresh_structure` / 事实区）。
* **性能**：由「整文件一次正则」变为「按表遍历」，PRD 体量下可忽略（不新增 I/O）。
* **不新增校验器 / 不新增测试文件**：`gates.md` 的 10 个校验器 / 52 个测试文件 / 65 条自检不变；`validate_e2e_index.py` 行数变化，按要求同步 `docs/map` 锚。

---

## 3. 改动面清单 (Affected Surface)

- [x] **契约/文档**：`rings/e2e/reference.md` §5.2；`shared/gates.md` §2.1 `validate_e2e_index.py` 行；`docs/map/gates.md` 摘要行；`docs/map/index.md` / `atlas-map.html`（锚与计数复跑后按实况更新）
- [x] **代码逻辑**：`validators/validate_e2e_index.py`（常量 `E2E_DIM_HEADER` + `collect_e2e_declared_dims` + 调用点替换）
- [x] **测试防线**：`tests/test_validators.py::test_e2e_dim_header_located_by_name`；golden `tests/fixtures/e2e_coverage_dims_golden.json` 追加 `e2e_dim_header_cases`（4 例）；变异 **M174**
- [x] **留出验证（§4.5）**：本批触发面核对命中 (b) 路径族 ⇒ 三态 = `单案修复（无留出集）`，QUEUE 观察行 owner / 期限见 `duty-review/QUEUE.md`
- [ ] **版本装配**：不涉及（无新增/删除装配件）

---

## 4. 验证与测试结果 (Verification)

```bash
# 1. 相关单元测试（含新增钉）
python3 -m pytest tests/test_validators.py -q

# 2. 出厂级全量测试套件（必须全绿）
python3 -m pytest tests/ -q

# 3. Atlas 快速自检
python3 scripts/atlas_check.py --fast

# 4. docs/map 锚与计数
python3 -m pytest tests/test_map_anchors.py -q
```

* **测试结果**：`tests/test_validators.py` = **183 passed, 0 failed**（新增 1 条钉）；`tests/test_map_anchors.py` = **8 passed**；全量见 §4.1。
* **自检结论**：`atlas_check --fast` = exit 0，但**源包态 10 个校验器全部 `SKIP 校验器不存在`**（只有 write-claim / ablation 行真跑），**不构成门证据**；门证据 = 全量 pytest + 定向钉。
* **M174 四段协议**：基线 GREEN → 注入 RED → 逐字节还原（sha256 一致）→ 复绿；报告 = `.atlas/runs/mutation-proof/M174.txt`（含注入 diff）。

### 4.1 全量实跑摘要

```text
$ PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/ -q -p no:cacheprovider
........................................................................ [ 75%]
........................................................................ [ 81%]
........................................................................ [ 87%]
........................................................................ [ 93%]
.....................................................................    [100%]
1144 passed, 5 skipped in 1715.33s (0:28:35)
```

> 两个附加 flag 只关闭 `.pytest_cache` / `__pycache__` 写入（沙箱对仓目录只读），不改变用例集合与判定；`tests/test_atlas_verify_playground.py` 单独实跑 = `2 passed in 1236.12s (0:20:36)`。

### 4.5 留出验证（系统性修复必填；`RFC-20261026-03`）

* **触发面核对**：
  * **(a) RFC §1 引子族锚 / ≥3 条独立审查重复 finding**：否——§1 是单条判据缺口，未引用 `bugs.md` 同根归纳，也无 ≥3 条独立重复 finding。
  * **(b) 改门 / 校验器 / 契约判据且 diff 落在 DR4 段级锚路径族**：**命中**。原始命令输出：

```text
$ git diff --name-only
docs/map/gates.md
duty-review/QUEUE.md
rings/e2e/reference.md
shared/gates.md
tests/fixtures/e2e_coverage_dims_golden.json
tests/test_validators.py
validators/validate_e2e_index.py

$ python3 scripts/closeout_derive.py --diff-base HEAD
本清单不含语义触发行，正文自查
本轮改动 7 个文件（atlas 自有对账面 5 个；业务面 2 个，只计条数）
[自动] 步骤 1 —— 触发：任一工作单元收尾；改契约 / 模板 / 校验器 / 脚本 / skill 瘦桩；改动触及核心业务链路 / 权限 / CI / 依赖 / 契约（判据指针：closeout.md §2 步骤 1）
[自动] 步骤 2 —— 触发：改契约 / 模板 / 校验器 / 脚本 / skill 瘦桩（判据指针：closeout.md §2 步骤 2）
[人工] 步骤 3 —— 触发：改动触及核心业务链路 / 权限 / CI / 依赖 / 契约（判据指针：closeout.md §2 步骤 3）
[人工] 步骤 5 —— 触发：改契约 / 模板 / 校验器 / 脚本 / skill 瘦桩（判据指针：closeout.md §2 步骤 5）
[人工] 步骤 7 —— 触发：改契约 / 模板 / 校验器 / 脚本 / skill 瘦桩（判据指针：closeout.md §2 步骤 7）
```

  * **锚 → 路径族映射与误报**：E2E 段同根归纳（「契约字段 / 守卫面 ⇔ 生成器沉淀不同步」）的手工路径族含 `rings/e2e/reference.md` 与 `validators/validate_e2e_index.py`；本批 diff 两者均触及 ⇒ 保守判命中。**误报说明**：本批缺陷是「列定位方式」而非「生成器未同步字段」，路径族信号偏保守，未据此扩族。
* **留出集**：**无**。可行性核对（三条独立性逐条）：①判据输出翻转的输入不止表头串——表切分（`iter_md_tables` 的段 / 表识别）、列序与列数、单元格内容同样能翻转判定；但它们都必须构造同一张 AC 表（同一夹具族）才生效，属同夹具变体；②变异增量杀伤：M174 已证明注入后既有钉全绿而新钉红，但新钉夹具本身即 §1 探针的变体；③结构不可达：任何「独立」语料仍需构造同一张 AC 表并改表头，结构上不可达。=> 确无可行留出集。
* **残留面（显式）**：canonical 5 列 AC 表（`AC ID` / `场景` / `回指规则` / … / `适用覆盖维度`）的整表定位在 golden 中**曾无钉**——`e2e_dim_header_cases` 只钉表头接受 / 拒绝 4 例，均为单列表头、不含整表列序；本批未补，后续以「强制前三列 + canonical 5 列 golden」补。
* **已接受的残留面（2026-11-04 维护者拍板①）**：表头写错 ⇒ **无任何信号**（含诊断 WARN）——门对该表按 N/A 跳过，不告警、不计入计数；此为已接受的残留面，不是待修缺陷。
* **pre-fix 红**：不适用（无留出集）；§1.2 已给出位置式正则对错表头的命中取证。
* **post-fix 绿**：新增钉 + golden 4 例全绿（§4）。
* **反面包**：合法表头（`适用覆盖维度`）语料在改动前后结论一致（D130 钉 + 本批 §4 的 WARN/PASS 子断言）。
* **三态结论**：`单案修复（无留出集）`——**不宣称闭族**。残留风险与观察 = `duty-review/QUEUE.md` 观察室「E2E 维度列表头校验观察」，owner = 本批实施者，补验期限 = 首个真实仓 PRD 跑该门后 2 周（不晚于下一个 beta 发版后 2 周）。
* **耗时与评审**：设计 + 实施 + 四段变异证明为本轮一次完成；评审 = `proposals/REVIEW-20261103-03-e2e-dim-header-validation.md`（技术方案 + 事实核查）。

### 4.5-b 后续收紧（2026-11-04，H：前三列 canonical；D156）

* **变更**：`collect_e2e_declared_dims` 增加「表头前三列须按序为 `AC ID` / `场景` / `回指规则`，否则该表按 N/A」。第二列按前缀接受模板的 `场景（Given / When / Then）` 变体——**前缀判定是有意的，且前缀固定为 `场景`，不是任意前缀**（逐字相等会把仓内 canonical 模板 `templates/prd/domain.md` 的 5 列表判死）；第一列与第三列逐字，列序严格。
* **pre-fix 红**：`python3 -m pytest tests/test_validators.py::test_e2e_dim_header_requires_canonical_first_three_columns -q` → **1 failed**：非 canonical 列序（`场景 | AC ID | 回指规则 | 适用覆盖维度`）被旧判据按 PASS 采信。
* **post-fix 绿**：同一钉 + 旧 4 列钉 = **2 passed**；`python3 -m pytest tests/test_validators.py tests/test_e2e_console.py -q` = **215 passed in 2.47s**。
* **反面包**：canonical 4 列（旧表）与 canonical 5 列（模板 `场景（Given / When / Then）`）均按 WARN 采信；非 canonical 列序与前三列错位均 N/A 且不点名 AC；一坏一好两张表 ⇒ 只报好表缺口（坏表 C03/C04 不串味）。
* **留出集**：**无**。翻转输入即表头前三列的次序 / 取值本身，任何「独立」语料仍需构造同一张 AC 表并改表头 ⇒ 同夹具族、结构不可达。
* **残留面**：表头写错 ⇒ 无任何信号（含 WARN），即上述已接受残留面；第二列前缀匹配属模板兼容口径，未来若出现第二个场景列变体须显式登记。
* **三态结论**：`单案修复（无留出集）` **候选**——**未闭族**。缺独立评审复验与 `duty-review/QUEUE.md` 观察行（QUEUE 正被 S2 会话占用，按并行守卫暂缓）；二者落地前不得自称闭族。

---

## 5. 明确范围外（后续案）

以下**不在本批**，不得顺手实现：

1. **weak-only WARN**：`blocked/skipped/prototype-pass` 记 weak、某维度只被 weak 覆盖 ⇒ WARN；
2. **`prototype-pass` 语义变更**：本批完全不动；
3. Batch B 的其他内容（如后端列与 E2E 列并集 / 交叉校验等）；
4. `bugs.md` #31（`results.json` 仍计入 `scripts_hash`）—— 属另一轮前置。

后续案启动条件：等真实仓出现「weak 覆盖被当成 active 覆盖」或「错表头导致缺口逃逸」的实例（见 QUEUE 观察行），按 DR2 另批立 RFC。
