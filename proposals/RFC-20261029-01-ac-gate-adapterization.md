# RFC-20261029-01（v2）：AC 门适配器化与三形态适用性

- **状态**：Batch A/B/C1/C2/D1/D2a/D2b/D3 已落地（2026-10-29）。Batch A = 内部 adapter + 诚实性；advisory 零覆盖改 WARN；Batch B = §1 框架名清理 + pytest 配置兜底迁 adapter；Batch C1 = Vitest/Jest 内置 extractor。
- **日期**：2026-10-29
- **范围**：`validators/validate_ac_alignment.py`、`validators/validate_stack_profile.py`、新增 `adapters/ac/`、`shared/stack-profile.md`、`shared/gates.md`、`docs/gates/iron-gates.md`、`docs/guide/backend-test.md`（新）、`docs/guide/legacy-adoption.md`、`templates/stack-profile.yaml`、`patches/project-wiring/apply-wiring.py`、`scripts/atlas_check.py`、`README.md`、`DESIGN.md`（D163）、`CHANGELOG.md`、`docs/map/`、测试与变异
- **关联**：D153（后端 AC × 覆盖维度；本 RFC 修订其「pytest only」v1 边界）、D130（E2E 维度，保持不动）、`shared/global-rules.md` §1（核心不得含框架名）

## 0. 评审修订摘要

独立评审结论：**accept with changes**。Critical 2 条、Major 9 条、Minor 8 条；全部逐条主审核对，未发现需要整条否决的结论。主要修订：

1. **不再把「未声明 apps」当「无 backend app」**：仅 `apps` 为非空列表且无 backend/fullstack 时整门 N/A；apps 缺失/非法 ⇒ 未验证（WARN/FAIL），避免吞掉无主 AC 的 FAIL。
2. **输入面判定下沉到 adapter**：validator 不再出现 `test_*.py`；由 adapter 返回 `input_state`，否则守恒测试咬不住语义泄漏。
3. **Batch A 不做外部 extractor 协议**：`extractor_command` / `command.py` / JSON schema / parser 扩展整体推迟到第一个真实外部 adapter 的 RFC（Batch C）。Batch A 只做内部 adapter 边界 + pytest 迁移。这符合本仓「不为不存在的第二消费者造机制」。
4. **补 schema 不变量**：`marker_scope_unsupported`（原 `pytestmark_ac_unsupported` 的通用名）、`acs = marker_acs ∪ doc_acs`、`line > 0`、`(file,line)` 唯一；删除只写不读的 `uncertain`。
5. **补 parse_errors / scan_face 状态**：非空 `parse_errors` ⇒ advisory WARN / enforce FAIL；`scan_face` ⇒ WARN，且不再只在维度子项里出现。
6. **补 `apply-wiring.py` 消费者**：不再把任意 `backend_test:` 段当 Python 工程写 `pytest.ini`；非 Python + `backend_test:` 的夹具必须证明不生成 pytest 配置。
7. **模板与 §1 清理**：`templates/stack-profile.yaml` 的 pytest 示例随 Batch A 改成通用字段；`shared/`、`rings/`、`templates/`、`patches/` 剩余的框架名清理列为**必做 Batch B**，不再标「可选」。
8. **批次重命名**：Batch A（本 RFC）/ Batch B（§1 契约清理）/ Batch C1（Vitest/Jest 内置，已落地）/ Batch C2（JUnit + 外部 extractor 协议）/ Batch D（Java/Go 结构适配器 + 多模块）。
9. **主审实测**：用夹具复现了评审指出的三条事实——无 apps + 无主 AC 当前 FAIL；`backend_test` 无 framework + 坏测试文件当前 `PASS 0%`；`parse_errors` 被吞。评审的 Critical/Major 不是纸面推断。

## 1. 问题

### 1.1 设计契约与现状的冲突

`shared/global-rules.md:8-10` 写死：

> atlas 核心、`shared/`、`rings/*/reference.md`、`templates/`、`validators/` **不得出现任何具体框架名**（语言框架、前端框架、ORM、构建器、桌面壳等一律不写）。
> 框架知识只有两个合法来源：目标项目的 `product/stack-profile.yaml` 与 `adapters/`。
> 违反即视为契约失败，与「跨项目通用」硬要求冲突。

AC 线是 **`validators/` 中唯一把框架知识写进可执行判据且未适配器化**的地方（不是全仓唯一出现框架名的地方——`shared/`、`rings/`、`templates/` 仍有示例，见 Batch B）：

- `validators/validate_ac_alignment.py:104` 有 `PyTestACVisitor`，文件内 `pytest.mark.ac` / `pytestmark` / `skip` / `xfail` 等 pytest 名字 20+ 处；
- `validators/validate_stack_profile.py:78` 硬编码 `BACKEND_TEST_FRAMEWORKS = ("pytest",)`；
- `shared/stack-profile.md:107` 把 `framework` 枚举写成 `pytest`，`:111` 把标记写成 `@pytest.mark.ac(...)`；
- `shared/gates.md:48` 把 `@pytest.mark.ac(...)` 写进门定义；
- D153（`DESIGN.md:628`）明确边界「v1 单 `test_dir`、pytest only、`test_*.py` only、无 app 维度」。

这不是意外，是一个被接受的 v1 例外；但它与 §1 的硬约束冲突，且没有退出条件。结果是：结构事实有适配器隔离，AC 门没有——「不限制技术栈」在结构环成立，在 AC 环不成立。

### 1.2 三形态的适用性错误

`validate_testids.py:17` 是正确范式：无前端 app ⇒ 整门 `N/A`，且明确「本文件不得出现任何具体框架名」。AC 门缺的正是这两条：

- `scripts/atlas_check.py:88` 给 `validate_ac_alignment` 的前置只查 `<资产根>/prd/prd.md` 是否存在，不查有没有 backend app，也不认域级 `*-prd.md`；
- `validate_ac_alignment.py` 的前四条判据在 `backend_channel_reason()` 之前执行，`backend_channel_reason()` 只作用于第五条维度子项；
- 因此：**纯前端项目只要写了 `prd.md`，也会跑 AC 门**；没有 `test_*.py` 时，advisory 报 `PASS 0%`，enforce 报「零测试挂载」；
- 纯后端 Java/TS/Go：同样看不见测试；全栈 Java/TS：只有 UI 的 E2E 通道，后端 AC 没有机器门。

主审夹具复现（2026-10-29）：

- 无 stack-profile、PRD 有 `AC-X-001`、`backend/tests/test_dangle.py` 挂 `AC-X-999` ⇒ 当前 `FAIL 无主AC拦截`。如果按 v1 草案「无 backend kind ⇒ N/A」，这条 FAIL 会被吞掉。
- backend app + `backend_test: {test_dir: backend/tests}`（无 framework）+ 一个语法错误的 `test_bad.py` + PRD 有 AC ⇒ 当前 `PASS`，`AC覆盖对账 0%`，`parse_errors` 完全不可见。

### 1.3 后果

- 假绿：无 Python 测试但 PRD 有 AC ⇒ advisory `PASS 0%`，使用者以为后端 AC 已被对账；
- 假红：enforce 下同一份 TS/Java 测试存在但门看不见 ⇒ `FAIL 零测试挂载`，看起来像项目没写测试；
- 假适用：纯前端项目被 backend AC 门扫，得到 0% 覆盖或无意义的 enforcement；
- 契约漂移：`shared/` 与 `validators/` 里出现框架名，`global-rules.md` §1 形同虚设；
- 扩展方式错误：每接一个语言就在 validator 里加分支，核心越来越知道具体框架；
- 装配污染：`patches/project-wiring/apply-wiring.py:288-319` 把任意声明的 `backend_test:` 当 Python，给 Vitest/JUnit 项目写 `pytest.ini`。

## 2. 目标 / 非目标

### 2.1 目标

1. **三形态适用性**：纯前端 ⇒ AC 门整门 `N/A`；纯后端/全栈 ⇒ AC 门适用；纯后端时 testid/E2E 继续 `N/A`。
2. **框架知识下沉**：AC 提取器移出 `validators/`，落到 `adapters/ac/`；validator 只消费归一化记录，不再出现具体框架名或 `test_*.py` 这类文件命名约定。
3. **未验证 ≠ PASS**：有 backend app、声明了 extractor、但没有可用 extractor ⇒ advisory `WARN` / enforce `FAIL`；不得报 PASS。
4. **行为兼容**：既有 Python/pytest 项目的对账结果不变（除 1.2 的纯前端 N/A、零覆盖 WARN、parse_errors 可见三项修正）。
5. **可执行的不变量**：新增「validators 不得出现框架名/测试文件命名约定」守恒测试。
6. **装配不污染**：非 Python 项目的 `backend_test:` 不再触发 `pytest.ini`。

### 2.2 非目标

- **Batch A 不做外部 extractor 协议**（`extractor_command`、JSON schema、`command.py`、`_support/stack_profile.py` 解析扩展）；这些随第一个真实外部 adapter（Batch C）一起做。
- 不在本 RFC 内实现 TypeScript/Java/Go 的具体 extractor；它们作为 Batch C1/C2。
- 不解决多 backend app / Maven-Gradle 多模块的建模；保持现有 `>1 backend/fullstack app ⇒ N/A`，另立 Batch D。
- 不重写 E2E / testid / PRD 门。
- 不把「部分覆盖」升级为 FAIL；当前 enforce 只在零挂载时 FAIL，100 条 AC 只挂 1 条仍 PASS。这是本 RFC 明示的剩余边界，不在本批解决。
- 不改变 `backend_test.command` 的执行语义（它仍是收口核验命令，不由本门执行）。

## 3. 设计

### 3.1 适配器边界（Batch A：内部 Python API）

新增：

```text
adapters/ac/
├── __init__.py      # registry: resolve(name) / available() / DEFAULT / ExtractResult
└── pytest.py        # 从 validator 迁出的 PyTestACVisitor + scan_*（唯一 pytest 知识落点）
```

- `adapters/` 是 `global-rules.md` §1 的合法框架知识落点；`validators/` 只 import registry，不 import 具体框架。
- registry 的 `DEFAULT` 由 `adapters/ac/__init__.py` 定义（当前为 pytest），用于兼容「`backend_test` 存在但未声明 extractor/framework」的存量项目；contract 不写具体名字。
- 适配器接口（Batch A 是 Python 函数契约，不是 JSON 协议）：

```python
@dataclass
class ExtractResult:
    tests: list[dict]                 # 归一化记录，见 3.2
    parse_errors: list[str]           # 逐文件解析失败原因
    scan_face: list[str]              # 扫描面提示（未扫描的命名族 / 空扫描面）
    input_state: str                  # "present" | "absent"

def resolve(name: str) -> Adapter | None
def available() -> list[str]
```

- `pytest.py` 的 `input_state` 在**适配器内部**用 `test_*.py` / `*_test.py` 判定；validator 不再出现这些模式。
- 加载方式：validator 已把包根加入 `sys.path`；用 `import adapters.ac`（`adapters` 是无 `__init__.py` 的 namespace package，`adapters/ac/__init__.py` 作为子包可用）。需在源包与 `.atlas/` 装配态双跑；不依赖 `_support/siblings.load_module`（其搜索面只有 `scripts/validators/_support`）。
- `validate_stack_profile.py` 不再硬编码支持列表；只校验字段形态与互斥关系。支持性由 AC 门在运行时通过 registry 判定（未知 ⇒ 未验证）。

### 3.2 归一化记录契约

`tests[]` 每项字段：

```text
name, file, line, acs, marker_acs, doc_acs,
dims, dims_bad, dims_shape_ok, dims_present,
skipped, waiver, weak, marker_scope_unsupported
```

不变量（validator 在消费前校验，违反 ⇒ `FAIL`）：

- `marker_acs` / `doc_acs` 为字符串数组，`acs == marker_acs ∪ doc_acs`；
- `line` 为正整数，`(file, line)` 在本次结果内唯一（判据 5 用它去重）；
- `file` 为项目根相对路径；
- `dims_present` 为真时，`dims`/`dims_bad`/`dims_shape_ok` 必须存在；`dims` 只作用于单 AC marker（一测多 AC 带 dims ⇒ 现有 WARN）；
- `marker_scope_unsupported` 为通用名（原 `pytestmark_ac_unsupported`）：模块/类级 AC 标记不支持；pytest adapter 负责映射；
- 删除 `uncertain`（当前只写不读，是死字段）。

下游五条判据消费归一化记录；`backend_channel_reason()` 改为通用通道状态，不再出现 `framework != "pytest"`（见 3.3/3.4）。

### 3.3 适用性判定（顺序固定，所有 N/A 分支显式 return）

1. **形状**：
   - `profile.apps` 是**非空列表**且无 `kind ∈ {backend, fullstack}` ⇒ 加「门控态」`N/A`，整门 return。
   - `profile.apps` 缺失/非列表：**不 N/A**；这是「无法判定通道」，进入未验证分支（保留旧 DEFAULT 扫描输入面的能力）。
2. **输入面**（由 adapter 的 `input_state` 给出，不用文件名）：
   - 无 PRD AC 且 `input_state == "absent"` ⇒ 整门 `N/A`（无输入面，含 greenfield）。
3. **extractor 解析**：
   - `backend_test` 缺失：用 registry `DEFAULT` 做 legacy 发现；
   - `backend_test` 存在且声明 `extractor`/`framework`：解析该名字；
   - `backend_test` 存在但未声明 extractor/framework：用 `DEFAULT` 发现；若 `input_state == "absent"` ⇒ `[UNVERIFIED]`（不假设是 pytest，避免 Java/TS 假 ZERO-COVERAGE）；
   - 未知 extractor ⇒ `[UNVERIFIED]`（advisory WARN / enforce FAIL），整门 return，不执行前四条。
4. **执行**：extractor 返回记录后，跑五条判据 + 提取完整性判据（3.4）。

`backend_test` 缺失且 backend app + PRD AC + 无输入面：advisory `[ZERO-COVERAGE]` WARN / enforce FAIL——「合法降级」不等于「可以 0% PASS」；如果项目确实没有任何后端测试，它应当是可见的缺口，而不是 PASS。

### 3.4 状态语义

不新增状态枚举，沿用 `PASS / WARN / N/A / FAIL`，用 detail 前缀区分：

| 场景 | advisory | enforce | detail 前缀 |
|---|---|---|---|
| 非空 apps 且无 backend/fullstack | `N/A` | `N/A` | `[N/A]` |
| 无 PRD AC + adapter 无输入面 | `N/A` | `N/A` | `[N/A]` |
| apps 缺失/非法 | `WARN` | `FAIL` | `[UNVERIFIED]` |
| backend app + 未知 extractor | `WARN` | `FAIL` | `[UNVERIFIED]` |
| backend app + `backend_test` 无 extractor + 无输入面 | `WARN` | `FAIL` | `[UNVERIFIED]` |
| backend app + 有 AC 但零挂载测试 | `WARN`（修正，原 PASS） | `FAIL` | `[ZERO-COVERAGE]` |
| extractor 输出 schema 非法 / 命令失败 | `FAIL` | `FAIL` | `[EXTRACTOR]` |
| 非空 `parse_errors` | `WARN` | `FAIL` | `[PARSE]` |
| 非空 `scan_face` | `WARN` | `WARN` | `[SCAN]` |
| 无主 AC / 无 waiver skip | `FAIL` | `FAIL` | — |
| 全部通过 | `PASS` | `PASS` | — |

- `parse_errors` / `scan_face` 必须作为独立 check 输出，不再只在维度子项的 `else` 分支里拼接；否则坏测试文件会被静默吞掉（主审已复现）。
- 纯前端/合法降级用 `N/A`，与 `validate_testids` 一致；不要把「不适用」和「无法验证」混成同一个状态。
- 所有 N/A 分支显式 `return res`，避免 `Result.status` 的「全 N/A 才 N/A」把后续 PASS 吞成整门 PASS。

### 3.5 契约与文档变更

- `shared/stack-profile.md`：`backend_test` 改成通用字段（`extractor` / `ac_marker` / `mode`），**不再枚举 pytest**；具体示例移到 `docs/guide/backend-test.md`。`framework` 保留为 `extractor` 的兼容别名。
- `shared/gates.md` / `docs/gates/iron-gates.md`：AC 行改成通用描述；删除该行的 pytest 名字；补状态表与「未验证 / parse_errors」盲区。其余非 AC 行的框架名清理归 Batch B。
- `docs/guide/backend-test.md`（新）：pytest / Vitest/Jest / JUnit 5 的标记示例、归一化记录说明、外部 extractor 协议**标注为 Batch C2**；只放示例并回指契约，避免形成第二正文。
- `docs/guide/legacy-adoption.md`：更新示例；说明「原生 extractor 是能力矩阵的一部分，不是技术栈上限」。
- `templates/stack-profile.yaml`：4 行注释改成通用 `extractor: <adapter>` / `ac_marker: <adapter-specific>`，删除「framework: pytest（v1 仅支持）」。
- `README.md`：加「三形态 × 能力矩阵」，区分原生机器抽取 vs agent 维护。
- `DESIGN.md`：新增 D163，记录 AC 门适配器化与三形态适用性；D153 的「pytest only」边界标注为被本 RFC 修订（v1 边界退出），不改写 D153 历史行。
- `docs/map/`：更新计数/锚点；跑 `test_map_anchors`、`test_canonical_consistency`。
- `CHANGELOG.md`：记录行为变更（纯前端 N/A、零覆盖 WARN、parse_errors 可见、apply-wiring 不再误写 pytest.ini）。

### 3.6 守恒测试（关键）

新增 `tests/test_no_framework_names.py`：

- **Batch A 范围**：`validators/*.py`。
- 用 AST 收集 import / `Name` / `Attribute` / `Constant`，对 denylist（`pytest`、`jest`、`vitest`、`junit`、`testng`、`spring`、`fastapi`、`flask`、`django`、`nestjs`、`express`、`mocha` 等）做**标识符/导入级**匹配，不做裸子串匹配；加一个含 `expression` 的负向夹具，证明不误报。
- 语义钉：`validate_ac_alignment.py` 不得出现 `test_*.py` / `test_` 文件 glob、不得 `import ast` 做测试解析、不得出现 `pytestmark` / `mark` / `skipif` / `PyTestACVisitor`。
- 当前 `validate_ac_alignment.py` / `validate_stack_profile.py` 会立刻红；这正是把隐藏例外变成红点的机制。
- **Batch B 范围（必做）**：扩展到 `shared/`、`rings/`、`templates/`、`patches/`；当前约 19 处框架名，示例迁到 `docs/`，不能以「可选」长期挂账。

## 4. 迁移与兼容

- `backend_test.framework: pytest` 继续可用：映射为 `extractor: pytest`；若同时声明 `extractor` 且不一致 ⇒ `validate_stack_profile` FAIL。
- 既有 Python/pytest 项目的记录与判据不变；pytest adapter 是原 `PyTestACVisitor` 的机械迁移（含 `marker_scope_unsupported` 的通用化）。
- 行为变更（必须写 CHANGELOG）：
  1. 纯前端/无 backend app 的 AC 门从 `PASS 0%` 变为 `N/A`；
  2. 有 backend app + PRD AC + 零挂载：advisory 从 `PASS` 变为 `WARN`；
  3. `framework: unittest` 等非 pytest、非注册 extractor：从「维度 N/A、前四条照跑」变为 `[UNVERIFIED]` WARN/FAIL（更新 `tests/test_validate_ac_alignment.py:567-578`）；
  4. `parse_errors` 从被吞变为 `[PARSE]` WARN/FAIL；
  5. 非 Python + `backend_test:` 不再生成 `pytest.ini`。
- `apply-wiring.py`：`is_python_project()` 不再用「任意 `backend_test:`」作为 Python 证据；改为 `framework: pytest` / `extractor: pytest` / Python 特征文件/`stack` 声明。新增「Vitest/JUnit + `backend_test:` 不生成 pytest.ini」钉子。pytest.ini 生成逻辑本身迁入 `adapters/ac/pytest.py` 留给 Batch B（Batch A 先修行为）。
- `atlas_check.py`：AC 前置从 `prd.md` 单文件改为 PRD 目录（或 `prd.md`/任一 `*-prd.md`），让域级 PRD 项目也能进入 AC 门；加 `atlas_check` 夹具。
- 安装：`adapters/` 已递归装配；`install.sh` 自检新增 `adapters/ac/__init__.py`、`adapters/ac/pytest.py` 存在性检查。`package.json.files` 已含 `adapters`，无需新增顶层项。
- `atlas_check` / `atlas_verify` 已支持 `N/A`（D153）；本 RFC 不新增状态枚举，解析面不变。

## 5. 测试与变异

### 5.1 测试矩阵（三形态 × extractor 有无 × 输入/输出）

| # | 夹具 | 期望 |
|---|---|---|
| 1 | 纯前端 + PRD AC + 无 backend app | 整门 `N/A`，不写 baseline |
| 2 | 纯后端 Python + pytest + 正常测试 | 与变更前逐字段一致 |
| 3 | 全栈 Python + pytest | 与变更前一致 |
| 4 | 纯后端 Java/TS + `backend_test` 无 extractor + 有非 `.py` 测试 | `[UNVERIFIED]` WARN/FAIL，不报 ZERO-COVERAGE |
| 5 | 纯后端 + 未知 extractor | `[UNVERIFIED]` WARN/FAIL |
| 6 | 无 stack-profile / apps 缺失 + 无主 AC | 仍 `FAIL 无主AC拦截`，不被 N/A 吞 |
| 7 | apps 缺失 + PRD AC + 无输入面 | `[UNVERIFIED]`，不 PASS |
| 8 | backend app + `backend_test` 缺失 + 默认 `backend/tests` 有 pytest | 仍扫描（legacy） |
| 9 | backend app + `backend_test` 缺失 + 无测试 + PRD AC | `[ZERO-COVERAGE]` WARN/FAIL |
| 10 | 坏 `test_*.py` + 无维度列 | `[PARSE]` WARN/FAIL，不再整体 PASS |
| 11 | `scan_face` 非空（未扫描命名族） | `[SCAN]` WARN 可见 |
| 12 | `framework: unittest` | `[UNVERIFIED]` WARN/FAIL（行为变更） |
| 13 | 多 backend app | 现有 `N/A` 不变 |
| 14 | 非 Python + `backend_test:`（apply-wiring） | 不生成 `pytest.ini` |
| 15 | 仅域级 `*-prd.md` + `atlas_check` | 不再 SKIP，进入 AC 门 |

补充：

- `tests/test_ac_adapters.py`（新）：registry `resolve`/`available`/`DEFAULT`；pytest adapter 与原 scanner 记录逐字段对拍；`input_state` 三态；schema 不变量（`acs` 并集、`line`、`(file,line)` 唯一、`marker_scope_unsupported`）。
- `tests/test_validate_ac_alignment.py`：更新上述夹具；每例同时断言整门 `res.status` 与 detail 前缀。
- `tests/test_validators.py` / `tests/test_stack_profile_graph.py`：更新 `framework` 枚举断言；新增 `extractor`/`framework` 别名冲突、非法形态。
- `tests/test_install_selfcheck.py`：新增 `adapters/ac/` 装配自检。
- `tests/test_map_anchors.py` / `tests/test_canonical_consistency.py`：若 gates/map 计数变更，同步更新。

### 5.2 变异证明

- **M-AC1**：删掉「非空 apps 且无 backend ⇒ N/A」早退 ⇒ 纯前端夹具红。
- **M-AC2**：删掉「未知 extractor ⇒ 未验证」分支 ⇒ 未知 extractor 夹具变 PASS，钉红。
- **M-AC3**：validator 直接 import pytest adapter / 绕过 registry ⇒ 守恒测试红。
- **M-AC4**：删掉 `parse_errors` 检查 ⇒ 坏测试文件夹具变 PASS，钉红。
- **M-AC5**：pytest adapter 忽略 `skip`/`waiver` ⇒ 既有无效跳过钉红。
- **M-AC6**：删掉零覆盖 WARN 分支 ⇒ 零覆盖夹具变 PASS，钉红。
- 四段协议：注入 diff → 目标钉红 → 逐字节还原 → 复绿。

### 5.3 全量门

- `pytest tests/` 全绿；
- `install.sh --target /tmp/atlas-ac-probe --force` exit 0，自检含新文件；
- `test_map_anchors` / `test_canonical_consistency` 绿；
- 手动跑纯前端、pytest、未知 extractor、坏测试文件四个夹具，确认输出分别为 `N/A` / 原行为 / `[UNVERIFIED]` / `[PARSE]`。

## 6. 分批落地

- **Batch A（本 RFC）**：3.1–3.6；内部 adapter 边界 + pytest 迁移；shape/status；`apply-wiring` 行为修复；`atlas_check` 前置；模板 4 行；AC 行契约；守恒测试（validators）；D163；测试/变异/文档/CHANGELOG。
- **Batch B（必做，docs/patches 清理）**：`shared/`、`rings/`、`templates/`、`patches/` 剩余约 19 处框架名清理；示例迁 `docs/`；`apply-wiring.py` 的 pytest.ini 生成逻辑迁 `adapters/ac/pytest.py`；守恒测试扩到这些目录。可与 Batch A 并行，但不晚于下一个正式版。
- **Batch C1（已落地）**：Vitest/Jest 内置 extractor（`adapters/ac/js.py`）；标记约定、测试、文档见 D164。
- **Batch C2（已落地）**：JUnit 5 内置 extractor + 外部 `extractor_command` JSON 协议（argv / 无 shell / 超时 / schema）；见 D165。
- **Batch D1（已落地）**：Java Spring `api` + JUnit 测试清单适配器。
- **Batch D2a（已落地）**：JPA 模型抽取 + 单 app 多模块 `test_dir: .` 盘点。
- **Batch D2b（已落地）**：多 backend app 统一 `test_dir` 全局 AC 对账。
- **Batch D3（已落地）**：JPA 跨文件继承/Embeddable + Go API/测试清单/模型结构适配器；Go AC 需外部 `extractor_command`。

## 7. 评审结论核对（主审）

| 评审项 | 结论 | 处理 |
|---|---|---|
| C1 未声明 apps 被当无 backend app | **成立**（主审夹具：无 apps + 无主 AC 当前 FAIL） | 3.3 规则 1 只对非空 apps 生效；缺失/非法走未验证 |
| C2 validator 仍用 `test_*.py` 判定输入面 | **成立** | 输入面下沉 adapter `input_state`；加语义守恒钉 |
| M1 schema 缺 `pytestmark_ac_unsupported` / 不变量 | **成立** | 通用 `marker_scope_unsupported` + 并集/line/唯一性校验；删 `uncertain` |
| M2 「下游五条不改」与「无 pytest」矛盾 | **成立** | `backend_channel_reason` 改通用通道状态；更新旧钉 |
| M3 无 extractor 默认 pytest 造成假 ZERO-COVERAGE | **成立**（主审夹具：PASS 0%） | DEFAULT 仅在显式 pytest 或输入面 present 时生效；否则未验证 |
| M4 `parse_errors`/`scan_face` 被吞 | **成立**（主审夹具：坏测试文件 PASS） | 独立 check：`[PARSE]` WARN/FAIL、`[SCAN]` WARN |
| M5 apply-wiring 把任意 `backend_test:` 当 Python | **成立** | Batch A 修探测；pytest.ini 生成迁 adapter 放 Batch B |
| M6 模板仍写 pytest / Batch D 可选 | **成立** | 模板随 Batch A；§1 清理改必做 Batch B |
| M7 `extractor_command` flow list 解析不可用 | **成立** | 外部协议整体推迟 Batch C |
| M8 外部协议无真实消费者、失败语义未闭合 | **成立** | 采纳：Batch A 不做 `command.py`/JSON schema |
| M9 测试矩阵不完整 | **成立** | 5.1 扩为 15 格 |
| m1 `Result.status` 吞 N/A | **成立** | 所有 N/A 分支显式 return |
| m2 `load_module` 不搜 adapters | **成立** | 用 `import adapters.ac`；源包/装配态双跑 |
| m3 「唯一违反 §1」措辞过强 | **成立** | 改为「validators 中唯一可执行判据未适配器化」；Batch B 清其余 |
| m4 `unittest` 行为变更未列 | **成立** | §4 明列并更新旧钉 |
| m5 denylist 子串误报 | **成立** | AST 标识符级匹配 + `expression` 负向夹具 |
| m6 `uncertain` 死字段 | **成立** | 从 schema 删除 |
| m7 `atlas_check` 只认 `prd.md` | **成立** | 前置改 PRD 目录；加域级 PRD 夹具 |
| m8 未验证分支先于「无输入面 N/A」 | **成立** | 3.3 顺序：形状 → 无 PRD AC 且无输入 → extractor |

未采纳/降级：

- 评审建议「Batch A 连外部协议一起砍掉」——**采纳**；`extractor_command` 全部进 Batch C2。
- 评审指出「部分覆盖仍假绿」——**确认是边界，不在本 RFC 修**；在文档中明示，不宣称「AC 覆盖已完全诚实」。
- 评审指出 `shared/`/`rings/`/`templates/` 其余框架名——**不在 Batch A 阻塞**，但**列为必做 Batch B**，不标可选。

## 8. 验收标准

1. 纯前端夹具（有 PRD AC、无 backend app）：AC 门整门 `N/A`，exit 0，不写 baseline。
2. 纯后端 Python + pytest 夹具：与变更前逐字段一致；既有 `tests/test_validate_ac_alignment.py` 全绿（除明确列出的行为变更）。
3. 纯后端 + 未知 extractor：advisory `WARN`、enforce `FAIL`，detail 含 `[UNVERIFIED]`，绝不 `PASS`。
4. 无 stack-profile + 无主 AC：仍 `FAIL`，不被形状 N/A 吞。
5. 坏 `test_*.py` + 无维度列：`[PARSE]` WARN/FAIL，不再整体 PASS。
6. 非 Python + `backend_test:`：不生成 `pytest.ini`。
7. `validators/` 无 denylist 框架名、无 `test_*.py` / `import ast` 测试解析；守恒测试绿。
8. `pytest tests/` 全绿；`install.sh` 探针 exit 0；map/canonical 钉绿。
9. 文档：`shared/stack-profile.md` / `shared/gates.md` 的 AC 行不再把 pytest 写成枚举/门定义；`docs/guide/backend-test.md` 有 pytest/Vitest/JUnit 示例；`templates/stack-profile.yaml` 不再写「v1 仅支持 pytest」。

## 9. 风险

- **迁移耦合**：pytest adapter 从 validator 迁出后，`adapters` 是 namespace package、`adapters/ac` 是子包；需源包与 `.atlas/` 装配态双跑，避免 import 路径在测试/安装态分叉。
- **行为变更**：纯前端 `PASS → N/A`、零覆盖 `PASS → WARN`、`unittest` 未验证、parse_errors 可见，会影响存量项目的 `atlas check` 输出与测试断言；必须写 CHANGELOG 并逐个更新钉子。
- **§1 清理范围**：Batch B 约 19 处框架名，若拖到下一个正式版之后，§1 仍是空话；必须排期。
- **apply-wiring 二次污染**：Batch A 只修「非 Python 不写 pytest.ini」，pytest.ini 生成逻辑仍在 patch 里；Batch B 必须迁走，否则新 adapter 仍可能被塞 pytest 配置。
- **部分覆盖仍假绿**：本 RFC 不修「100 条 AC 挂 1 条也 PASS」；文档不得把它写成已解决。
- **二次失望**：Batch A 让门诚实（未验证 WARN/FAIL），但 TS/Java 采用者仍需要 Batch C 才能真正对账；README 能力矩阵必须写清「Batch A = 不再假绿，Batch C = 真正支持」。
