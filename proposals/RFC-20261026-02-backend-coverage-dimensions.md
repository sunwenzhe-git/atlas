# 后端通道 AC × 覆盖维度对账（Batch A：第 5 列 + 后端门；E2E 行为不动）

> 提案编号：`RFC-20261026-02`（v4.1 / Batch A；v1 纯后端、v2 并集、v3 两列两门均已评审；本版按 `REVIEW-20261026-04` 收口为「只落后端门，E2E 行为不动」，并落 `REVIEW-20261026-05` 的 5 条必修）
> 基线：RFC-01 已落地（`e7f3bcf`，**D152**，`v0.2.0-beta.12`）；本版已按该基线 rebase，**决策编号 = D153**
> 评审记录：`REVIEW-20261026-02`（v1）、`REVIEW-20261026-03`（v2）、`REVIEW-20261026-04`（v3）、`REVIEW-20261026-05`（v4 Batch A，修后通过）
> 关联状态：草案 (Draft)（待针对性评审；通过后按 `DESIGN.md` 当前最大 D 编号登记；RFC-01 已占 D152 ⇒ 本提案 D153）
> 并行提案：`RFC-20261026-01`（项目布局，**已落地 `e7f3bcf` / D152**；本提案已按该基线 rebase）
> **Batch B（另立 RFC，暂不实施）**：E2E 第 4 列表头校验 + weak-only WARN；见 §10。

---

## 0. 一句话

**只补后端通道**：PRD 验收表新增可选列 `后端适用覆盖维度`；`validate_ac_alignment.py` 新增 `AC × 覆盖维度（后端通道）`，读取后端测试的 `@pytest.mark.ac(..., dims=[...])` 并与该列对账。
第 4 列 `适用覆盖维度` 维持 D130 的 E2E 语义；**E2E 门的行为、D130、M131、索引解析全部不动**。

---

## 1. 现象与取证 (The Problem & Evidence)

### 1.1 触发形态（抽象）

* **规则 / 环节**：`rings/prd/reference.md` §五 AC 表第 4 列 `适用覆盖维度` 由 E2E 门消费；后端 / 全栈项目给 AC 声明后端维度（`C07` 审计、`C09` 一致性、`C11` 幂等、`C14` 安全）时，后端测试只挂 `@pytest.mark.ac("AC-xxx")`。
* **具体行为**：`validate_ac_alignment.py` 全 PASS——它只收集 AC ID，不解析维度列，也不解析测试上的维度声明；E2E 门又只读第 4 列。**后端维度声明无对账面。**

### 1.2 客观证据

| 位置 | 现状 |
|---|---|
| [rings/prd/reference.md:195](file:///Users/sunwenzhe/Desktop/atlas/rings/prd/reference.md#L195) | 第 4 列由 E2E 环门对账；没有后端列 |
| [validators/validate_e2e_index.py:586](file:///Users/sunwenzhe/Desktop/atlas/validators/validate_e2e_index.py#L586) | 维度对账只读 E2E 用例分片 |
| [validators/validate_ac_alignment.py:75](file:///Users/sunwenzhe/Desktop/atlas/validators/validate_ac_alignment.py#L75) | 只收集 AC ID，不读维度列 |
| [validators/validate_ac_alignment.py:106](file:///Users/sunwenzhe/Desktop/atlas/validators/validate_ac_alignment.py#L106) | 装饰器解析只认 AC / skip / waiver，无 `dims` |
| [validators/validate_ac_alignment.py:288](file:///Users/sunwenzhe/Desktop/atlas/validators/validate_ac_alignment.py#L288) | 覆盖对账只统计「有测试挂载的 AC 数」 |
| [shared/stack-profile.md:98](file:///Users/sunwenzhe/Desktop/atlas/shared/stack-profile.md#L98) | `backend_test` 段无维度约定 |
| [patches/project-wiring/apply-wiring.py:219](file:///Users/sunwenzhe/Desktop/atlas/patches/project-wiring/apply-wiring.py#L219) | 只注册 `ac` marker；`dims=` 是 kwarg，不需要新注册 |

**探针 A（缺口证明）**：5 列 PRD 第 5 列声明 `C01,C02,C11`，后端测试只写 `dims=["C01"]`：

```text
validate_ac_alignment @ /tmp/rev4-probe.Gzq7Ts
  [PASS] 无主AC拦截
  [PASS] 无效跳过拦截
  [PASS] AC覆盖对账 —— 已声明 AC: 1，后端测试挂载覆盖: 1 (100.0%)
  [PASS] 差量防回退
PASS
```

第 5 列与 `dims` 均被忽略，缺口真实存在。

### 1.3 评审结论（为什么只做 Batch A）

`REVIEW-20261026-04` 判定：两列/两门骨架成立，但 v3 把 E2E 表头校验、E2E weak-only WARN 与后端门绑在一起，导致 **N/A 行语义**、**未实现域分档**、**多 app 规则**、**备注/错位表头** 四类 blocker 互相纠缠。评审建议拆分：**后端门先落，E2E 两处小修另立小批**。本版按此收口。

---

## 2. 决策与权衡 (The Decision & Trade-offs)

### 2.1 核心定案

1. **只做后端通道**：
   * PRD §五 AC 表新增**可选列** `后端适用覆盖维度`（按表头名定位，不硬编码“第 5 列”；实际落在第 5 列）；
   * 第 4 列 `适用覆盖维度` 维持 E2E（D130 原样，不改判据、不改输出）；
   * 后端门只读 `*-prd.md` 的 `后端适用覆盖维度` 列，不读 `prd.md`、不读 E2E 索引/分片。
2. **新判据**：`validate_ac_alignment.py` 增加 `AC × 覆盖维度（后端通道）`：
   * 逐 AC 对账 `declared`（后端列）与 `active ∪ weak`（后端测试 `dims`）；
   * 缺维度 / 仅弱证据 / 零测试 / 未知 / 孤儿 ⇒ **WARN**（一条 check 行，detail 列清单）；
   * 无合法后端列、后端通道不适用/不可用 ⇒ **N/A**；
   * **v1 只 WARN，不 FAIL**；`backend_test.mode: enforce` 只覆盖 AC 挂载，不覆盖维度。
3. **后端通道适用/可用**：
   * `apps[]` 存在 `kind ∈ {backend, fullstack}` ⇒ 适用；
   * `apps[]` 中 backend/fullstack 数量 **> 1** ⇒ **N/A「多后端应用未建模」**（现有 schema 只有一个全局 `test_dir`，不做 per-app 猜测）；
   * `apps` 缺失/为空 ⇒ N/A「未声明 apps」；
   * `backend_test` 段存在 ∧（`framework` 缺失或 = `pytest`）∧ `test_dir` 目录存在 ⇒ 可用；否则 N/A + 原因。
4. **逐文件 / 逐表聚合**：
   * 每个 `*-prd.md` 独立找 AC 表、独立读后端列；一个 4 列旧表或错表头文件只跳过自身；
   * 只有**全项目没有任何合法后端列**才整门 N/A（防一个旧文件吞掉另一个域的第 5 列声明）。
5. **错位 / 备注列不再静默**：
   * 后端列表头不在预期位置（如写在第 4 列）但单元格含维度形态（`C\d{1,2}`）⇒ **WARN「疑似后端维度列但列位/表头不符」**；
   * 5 列表头是「备注」但单元格含维度形态 ⇒ **同 WARN**；
   * 无维度形态 ⇒ N/A，不误伤合法备注列。
6. **零测试的处理（v1 明确取舍）**：
   * **后端列 = opt-in**：填了即声明后端义务；域未实现/尚未准备时**留空**，不算缺口；
   * 声明了但零测试 ⇒ **一条汇总 WARN**，detail 列 AC 清单（不逐条刷屏）；
   * **不读域实现状态**（PRD `status` 是文档状态，结构事实的 `实现状态` 是路由级、E2E 页面表是前端页级；v1 不为零测试 WARN 引入跨环读）。这是有意的范围收窄，写入 `gates.md`。
7. **后端语法**：
   ```python
   @pytest.mark.ac("AC-ORDER-001", dims=["C01", "C02", "C11"])
   def test_create_order_idempotent():
       ...
   ```
   * `dims` 接受 list / tuple / 逗号分隔字符串；元素**精确匹配** `^C(0[1-9]|1[0-4])$`；
   * 只作用于 marker AC；docstring AC 仍参与既有 AC 覆盖，但**不参与 dims 归属、不计入零测试判断**；
   * marker AC 数 ≠ 1 ∧ `dims` ⇒ WARN 且不记维度；`dims` 空/非字面量 ⇒ WARN；未知/孤儿 ⇒ WARN；
   * `skip`/`xfail`（含 waiver）、`skipif`、`parametrize(marks=...)`、类级/模块级 `pytestmark` ⇒ **weak**；其余 ⇒ **active**；
   * `active` 覆盖缺维度 ⇒ WARN；仅 `weak` 覆盖 ⇒ **WARN「仅弱证据」**；
   * 类方法二次访问去重；`*_test.py` 不扫 ⇒ 扫描面 WARN；语法错误文件 ⇒ WARN 点名。
8. **N/A 可见性（只做最小修）**：
   * `validate_ac_alignment.Result`：**全部 check 都是 N/A** ⇒ `status = "N/A"`；否则维持 PASS/WARN/FAIL；
   * **早退改 N/A**：`validate_ac_alignment` 的早退（无 PRD AC 且无 tests）由 `AC对账门禁运行态 PASS` 改 `N/A`；`shared/stack-profile.md:100` 的「段缺失 = 按降级通过」改「按 N/A」；否则整门 N/A 不可达；
   * `scripts/atlas_check.py`：子项 N/A 只进 detail（匹配 padded `[N/A ]`），**行状态保持 ok/WARN/FAIL**；只有整门末行 `N/A` 才把行状态记 `N/A`；
   * `scripts/atlas_verify.py` 的 `_parse_rows` 白名单接受 `N/A`；`--json` 新增该整门状态值并写文档；
   * **不把 E2E 轮里的子项 N/A 提升为行 N/A**（避免误伤正常 E2E PASS）。
9. **单源**：新增 `_support/ac_coverage.py`（`parse_dims_cell` / `parse_dim_token` / `parse_dims_list`）。
   E2E 门只做**纯函数抽取**（本地 `_parse_dims` 改调共享函数，判据/输出零变化，golden `checks[]` 证明）；**不碰** `MAIN_COLUMNS`/`split_row`/`tables`/`gather_shards`/`atlas_verify` 窄解析/`parse_block` 别名/`validate_structure.split_row`。
10. **`enforce` 澄清**：四处同步（`shared/stack-profile.md:107`、`templates/stack-profile.yaml:94`、`docs/gates/iron-gates.md:69`、`docs/guide/legacy-adoption.md:125`）——`mode` 只管 AC 挂载；维度缺口恒 WARN。
11. **不改**：D130 的 C01-C14 闭集、E2E 门主体判据、E2E `覆盖维度:` 字段、索引解析三消费者、`apply-wiring.py`、delta baseline schema、`validate_prd.py` 列头要求（5 列合法）。
12. **Batch B 不做**：E2E 第 4 列表头校验、E2E weak-only WARN、`prototype-pass` 分档——全部留到独立 RFC（§10）。

### 2.1.1 列的语义

| 列 | 语义 | 消费者 |
|---|---|---|
| 第 4 列 `适用覆盖维度` | E2E 通道（D130 原样） | `validate_e2e_index` |
| `后端适用覆盖维度`（按表头名定位） | 后端通道（新） | `validate_ac_alignment` |

* 同一维度两端都要 ⇒ 两列各写一次；只由一端负责 ⇒ 只写该列。
* 后端列留空 = **未声明后端义务**，不是“豁免”；文档明写，不得用留空把「后端可测但没写」洗成无义务。
* 存量全栈项目若曾把后端维度写在第 4 列：新模型下后端门 N/A；迁移 = 把后端维度移到后端列（发布说明写明）。

### 2.1.2 后端语义映射

| ID | 后端典型证据形态 |
|---|---|
| C01 正常流 | happy path、事务提交、返回体 |
| C02 异常流 | 4xx/5xx、事务回滚、补偿 |
| C03 边界值 | 分页上限、超大 payload、长度/精度边界 |
| C04 权限约束 | 鉴权、越权、租户隔离 |
| C05 并发竞争 | 并发写、锁、乐观版本冲突 |
| C06 失败重试 | 重试策略、退避、幂等重放 |
| C07 审计埋点 | 审计表、操作日志、事件 |
| C08 会话恢复 | token 过期、刷新、重新鉴权 |
| C09 数据一致性 | 事务、最终一致、跨表/跨服务 |
| C10 依赖容错 | 下游失败、熔断、降级 |
| C11 操作幂等 | 幂等键、重复提交、去重 |
| C12 输入校验 | schema / 类型 / 注入前校验 |
| C13 状态转换 | 领域状态机、非法跃迁 |
| C14 安全防护 | 注入、越权、敏感字段、脱敏 |

落 `shared/stack-profile.md` §`backend_test`（canonical），不只留在 RFC。

### 2.1.3 后端门判据（逐 AC）

```text
declared = 后端列（AC 维度集合）
active   = 未被 skip/uncertain 标记的、带 marker AC 的测试 dims 并集
weak     = skip/xfail/skipif/param/类级 pytestmark 测试 dims 并集
covered  = active ∪ weak
missing  = declared - covered            ⇒ WARN
weak_only= (declared ∩ weak) - active    ⇒ WARN（仅弱证据）
零测试   = declared 非空 ∧ 无任何 marker AC 的测试 ⇒ 汇总 WARN
未知/孤儿/非字面量 dims                  ⇒ WARN
```

* 一条 check 行汇总；detail 列 `零测试=...` / `缺维度=...` / `仅弱证据=...` / `未知=...`（cap 8 + 计数）。
* 只 WARN；既有四条判据（无主 AC / 无效跳过 / AC 覆盖 / 差量）不变。
* 无 waiver 的 skip/xfail 仍走既有 `无效跳过拦截` FAIL；本门只处理维度。

### 2.1.4 后端列解析

* 每个 `*-prd.md` 独立找同时含 `AC ID` 与 `回指规则` 的 AC 表；按**表头名** `后端适用覆盖维度` 定位列（支持 6 列 / 列序变化）。
* 找不到该表头：
  * 只对「表头含 `维度` / `备注` / `后端`，或列位 ≥5」的列做 `C\d{1,2}` 扫描；
  * **永远排除表头为 `适用覆盖维度` 的列**（标准 4 列 E2E 表的合法维度列，不得误判）；
  * 命中 ⇒ 每表最多一条 **WARN「疑似后端维度列但表头/列位不符」**；
  * 未命中 ⇒ N/A（合法 3/4 列 / 备注列）。
* 模板占位：`templates/prd/domain.md` 的后端列占位必须是空 / `N/A`，**不得**写 `C01, C02` 示例（会被解析成真实声明并触发零测试 WARN）。
* 单元格空 / `N/A` / `—` / `-` ⇒ 无后端义务；非空但解析不出 ⇒ WARN。
* 支持 `C01-C03` 区间与 `C01正常流` 中文邻接（`parse_dims_cell`）。
* 跨 PRD 重复 AC 的后端列声明 ⇒ WARN（`validate_prd` 已查唯一性）。
* AC 文法沿用 `AC-[A-Z0-9]+-\d+`；非 3 位 ⇒ WARN「不符合 NNN 契约」。
* 只有全项目没有任何合法后端列 ⇒ 整门 N/A；否则逐表聚合，一个坏表不擦掉好表。

### 2.1.5 AST 与证据强度

* `dims` 解析：marker AC 只读位置参数中的 AC；docstring AC 分离；`dims` 精确 token；多 AC/空/非字面量/未知/孤儿 ⇒ WARN。
* `skip`/`xfail` 装饰器：weak（waiver 仍走既有跳过门）。
* `skipif`：weak（保守；`skipif(False)` 也记 weak）。
* `parametrize(..., marks=...)` 含 skip/xfail/skipif：weak；`pytest.param(..., marks=...)` 同。
* 类级 / 模块级 `pytestmark` 含 skip/xfail/skipif：该类的所有方法 / 该文件所有测试 weak。
* **`pytestmark` 带 `ac` 不在 v1 支持范围**：`pytestmark` 只读 skip/xfail/skipif；AC 必须函数装饰器（契约写明，测试钉住）。
* 类方法二次访问：新门按 `(file, line)` 去重（既有 AC 覆盖计数不变；`(file, name, line)` 因 prefix 不同不去重）。
* `test_dir` 中无 `test_*.py`：一条 WARN「扫描面无 test_*.py」，不再逐 AC 零测试 WARN；存在 `*_test.py` 未扫描 ⇒ 一条 WARN 点名。
* 语法解析失败：一条 WARN 点名文件。

### 2.1.6 N/A 可见性（最小修）

* `validate_ac_alignment.Result.status`：全 N/A ⇒ `N/A`；否则 PASS/WARN/FAIL。
* `atlas_check.py`：
  * `code == 0` 且无 WARN：detail = 末行 `[N/A ]` 子项（padded 匹配）+ tail；**行状态仍 ok**；
  * 整门末行就是 `N/A` ⇒ 行状态 `N/A`；
  * `--json` 增加整门 `"N/A"` 值；
  * 正常 E2E PASS 轮里的 `[N/A ] manual` 子项**不会**把行标成 N/A。
* `atlas_verify._parse_rows` 接受 `N/A`，执行器留档不丢行。
* 文档：`docs/gates/iron-gates.md:35-44` 补「子项 N/A 进 detail；整门不适用才是行 N/A」。

### 2.1.7 单源与不动面

| 解析对象 | 唯一实现 | 消费者 |
|---|---|---|
| 维度 token / 区间 / 中文邻接 | `_support/ac_coverage.py::parse_dims_cell` | E2E 门（纯抽取）、后端门、测试 |
| 精确 token | `_support/ac_coverage.py::parse_dim_token` | 后端门、测试 |
| 结构化 `dims` | `_support/ac_coverage.py::parse_dims_list` | 后端门、测试 |
| E2E 索引 / 分片 | **不动** | E2E 门、控制台、`atlas_verify` |
| 后端列 | 后端门内窄解析（按表头名） | 后端门、测试 |

E2E 门只把本地 `_parse_dims` 替换为共享函数；`declared_ac_dims`/`bad_case_dims`/`total_declared` 逻辑不动。golden `checks[]` 证明零变化。

### 2.2 备选方案及否定理由

* **A. v2 跨通道并集**：全栈 UI 缺口被后端证据吞掉；评审反例成立。
* **B. v3 两列 + E2E 两处小修一起落**：N/A 行语义、`prototype-pass` weak、表头解析互相纠缠；评审建议拆分。
* **C. 单列内联限定**：新语法/新解析器/存量迁移；两列更直观。
* **D. 独立 `ac_dim` marker**：需要第二个 marker + 改 `apply-wiring.py`；`dims=` 零配置。
* **E. docstring 声明维度**：散文不显眼；`waiver:` 是例外声明，不是覆盖数据。
* **F. 独立 manifest**：第二真相源，必漂。
* **G. 复制 `parse_dims`**：中文邻接/区间/未知词三个边界会漂。
* **H. v1 直接 FAIL**：语义真实性不可机判；先 WARN。
* **I. 后端专用 B01-B14**：违背复用目标。

### 2.3 刺痛代价与兼容性

| 项 | 影响 |
|---|---|
| 存量前端项目 | 零影响：E2E 门判据/输出不变；仅共享函数抽取（golden 证明） |
| 存量后端/全栈项目 | 没写后端列 ⇒ 后端门 N/A，零影响；写了但测试没 `dims=` ⇒ 汇总 WARN（不阻断） |
| 全栈项目 | 第 4 列仍 E2E；后端维度移到后端列；两门独立 |
| 零测试 | 后端列 opt-in；未实现域留空；汇总 WARN 列清单，不逐条刷屏 |
| 多 app | `apps` backend/fullstack > 1 ⇒ N/A「未建模」；单 app 项目正常 |
| 非 pytest / `*_test.py` | 后端门 N/A 或一条扫描面 WARN，不再满屏假红 |
| N/A 可见性 | `atlas_check` 子项 N/A 进 detail；整门 N/A 才行级 N/A；`atlas_verify` 接受 |
| 装配 | 新增 `_support/ac_coverage.py`：RFC-01 落地后 `_support` 9→10、install 55→56；未落地按 rebase 基线 |
| 运行时 | 多一次 AST 扫描 + 一次 PRD 读取；可忽略 |

---

## 3. 改动面清单 (Affected Surface)

> 行号/计数以 **RFC-01 落地后**基线为准；并行未落时按落地序合并。D/M 编号用占位，落地时按实际最大编号重排。

- [ ] **共享内核**：新增 `_support/ac_coverage.py`（三个解析函数）
- [ ] **校验器**：`validators/validate_ac_alignment.py`（后端列解析、`dims` AST、active/weak、汇总判据、`Result` N/A）；`validators/validate_e2e_index.py`（**仅**把本地 `_parse_dims` 改调共享函数，判据/输出零变化）
- [ ] **脚本**：`scripts/atlas_check.py`（子项 N/A detail、整门 N/A 行状态、`--json`）；`scripts/atlas_verify.py`（`_parse_rows` 接受 N/A）
- [ ] **共享契约**：`shared/gates.md`（AC 对齐行 + 后端维度判据/盲区；E2E 行不变；install 自检计数；测试条数）；`shared/stack-profile.md`（`dims` 语法、后端映射、`mode` 澄清）
- [ ] **环契约**：`rings/prd/reference.md:192/195`（后端列）；`rings/e2e/reference.md:178/320-322`（第 4 列 = E2E；后端列指针，Batch B 另案）
- [ ] **模板**：`templates/prd/domain.md:105/111`（后端列；**占位 = 空 / `N/A`**，不得写 `C01, C02` 示例）；`templates/stack-profile.yaml:90-95`（`dims` 示例、enforce 措辞）
- [ ] **公开文档**：`README.md:386-390`（AC 矩阵补后端列）、`README.md:430`（AC 对齐门）、`docs/gates/iron-gates.md:35-44`（N/A 子项）、`:68-69`（AC 门）、`:97-99`（E2E 门指针）、`docs/guide/legacy-adoption.md:118-132`、`docs/map/gates.md:56`、`docs/map/index.md` / `docs/map/atlas-map.html`（内核/自检/行数/测试计数）
- [ ] **测试防线**：`tests/test_validate_ac_alignment.py`（后端门 16+ 条，见 §4.1）；`tests/test_validators.py`（E2E 抽取 golden，D130/M131 保持）；`tests/test_shared_kernel.py`（三个解析函数 + `allowed` 加 `parse_dims_cell` + 函数对象/行为钉）；`tests/test_atlas_check.py`（N/A 子项/整门 N/A）；`tests/test_atlas_verify.py`（N/A 行）；`tests/fixtures/e2e_coverage_dims_golden.json`（新增 golden）；`tests/test_canonical_consistency.py` / `tests/test_map_anchors.py` 计数
- [ ] **计数具体面**：`shared/gates.md:77` 55→56、`:45`/`:65` 测试条数更新；`docs/map/index.md:37/58/111-112`（9→10、719→720、9→10、55→56）；`docs/map/atlas-map.html:172/393/527/529`（内核 ×9→×10、`54 条` 三处）；`README.md:394`；`BACKLOG-execution-layer.md` §8
- [ ] **装配**：`install.sh` 自检 +1（`_support/ac_coverage.py`）
- [ ] **决策与流水**：`DESIGN.md`（D 占位；D130 追加「第 4 列 = E2E；后端列另立」注记）、`CHANGELOG.md`、`docs/guide/changelog.md`
- [ ] **协调**：`RFC-20261026-01`（`install.sh`、`shared/*`、`rings/*`、`docs/*`、`_support` 计数、`atlas_check` layout 前置、D 编号）；`BACKLOG-execution-layer.md` §8

---

## 4. 验证与测试计划 (Verification)

### 4.1 后端门测试矩阵（`tests/test_validate_ac_alignment.py`）

| # | 场景 | 期望 |
|---|---|---|
| 1 | 后端列 `C01,C02`，`dims` 全覆盖 | `PASS` |
| 2 | 缺 `C11` | `WARN`，detail 指名 |
| 3 | 后端列声明、零测试 | 汇总 `WARN`，detail 列 AC |
| 4 | 仅 waiver skip 测试覆盖 | `WARN`「仅弱证据」 |
| 5 | `skipif` / `parametrize(marks=skip)` / 类级 `pytestmark` | `WARN`「仅弱证据」 |
| 6 | 一测多 AC + `dims` | `WARN`，不记维度 |
| 7 | marker AC + docstring 另一个 AC + `dims` | 维度只记 marker AC；docstring AC 不计零测试 |
| 8 | `dims=[]` / set / 变量 / 非字符串 | `WARN`「形态不支持」 |
| 9 | `dims=["C99"]` / `["C01正常流"]` / `["C01C02"]` | `WARN` 未知 token |
| 10 | 3 列 / 4 列 / 后端表头「备注」无维度形态 | `N/A` |
| 11 | 后端表头写在第 4 列 / 备注列含 `C01` | `WARN`「疑似后端维度列但列位/表头不符」 |
| 12 | 多 PRD：一个 4 列 + 一个后端列 | 后者仍被查；不整门 N/A |
| 13 | 后端列 `C99` / 自由文本 | `WARN` |
| 14 | `test_dir` 仅 `*_test.py` | 一条扫描面 `WARN`，不逐 AC 零测试 |
| 15 | 语法错误测试文件 | `WARN` 点名文件 |
| 16 | 无 `backend_test` / `framework: unittest` / 无 backend app | `N/A` + 原因 |
| 17 | 双 backend app | `N/A`「多后端应用未建模」 |
| 18 | 第 4 列 AC 在 `不可验` / `结构类` 清单 | **不豁免**后端列；照查 |
| 19 | AC 编号 2 位 | `WARN`「不符合 NNN 契约」 |
| 20 | `mode: enforce` + 维度缺口 | `WARN`，不是 FAIL |
| 21 | 标准 4 列 E2E 表（第 4 列 `适用覆盖维度` 写 `C01,C02`） | **不产生后端 WARN**；后端门 N/A |
| 22 | 模板后端列占位空 / `N/A` | `N/A`，不 WARN |
| 23 | `dims` 元组 / 逗号串 / 字符串 | 正确解析；非字面量 WARN |
| 24 | 模块级 `pytestmark` 含 skip | 该文件全部 weak；`pytestmark` 带 `ac` 不支持（文档/测试） |
| 25 | 类方法 | 只入列一次（`(file, line)` 去重） |
| 26 | `skipif(False)` | weak（保守） |
| 27 | `pytest.param(..., marks=skip)` | weak |
| 28 | `atlas_check --json` / `atlas_verify` 的 N/A 行 | 出现且不丢 |
| 29 | 空根 `validate_ac_alignment` | 整门 `N/A`（早退改 N/A） |

### 4.2 E2E 纯抽取 golden（`tests/test_validators.py`）

* 既有 D130 正/反测试 + M131 全绿；
* 同一组 well-formed 语料（`C01正常流`、`C01-C03`、`C99`、空、`N/A`、多 PRD、重复 AC）改前/改后 `checks[]` 逐字节一致（排除 `root`）；
* 提交 `tests/fixtures/e2e_coverage_dims_golden.json`（7 组语料的 `checks[]`，不含 `root`）；测试加载新输出比对，**不是口号**；
* `tests/test_shared_kernel.py::test_definitions_are_single_sourced` 的 `allowed` 加 `parse_dims_cell`；
* **行为钉**：monkeypatch `validate_e2e_index.parse_dims_cell`，断言 `AC × 覆盖维度` 输出变化；若 E2E 门实际走本地副本，输出不变 ⇒ 红；
* 抽取签名 `parse_dims_cell(raw) -> (set[str], bool)`；`_DIM_TOKEN` / `_dim_range_re` / `_dim_code_re` / `_dim_looks_re` 一并搬入 `_support/ac_coverage.py`；`bad_case_dims` 的 `looks` 必须保留。

### 4.3 `atlas_check` / `atlas_verify` N/A

* 正常 E2E PASS 轮（含 `[N/A ] manual` 子项）⇒ 行仍 `ok`，detail 含子项；
* `validate_ac_alignment` 全 N/A ⇒ 行 `N/A`；
* `atlas_verify._parse_rows` 不丢 N/A 行；
* `--json` 含整门 N/A。

### 4.4 变异钉（编号占位）

* **M-Фa**：摘后端 `dims` 解析 ⇒ #1/#2 红。
* **M-Фb**：缺失维度聚合恒为空 ⇒ #2 红。
* **M-Фc**：删零测试汇总 ⇒ #3 红。
* **M-Фd**：删 weak-only 规则 ⇒ #4/#5 红。
* **M-Фe**：删后端通道适用/可用闸 ⇒ #16/#17 红。
* **M-Фf**：`parse_dims_cell` 退回本地复制 ⇒ `test_shared_kernel` 唯一性/函数对象钉红；再加 monkeypatch 行为钉：E2E 门必须实际调用共享函数，否则红。
* 四段协议（注入 → 红 → 还原 → 逐字节一致），原始输出落 `.atlas/runs/mutation-proof/`。

### 4.5 装配与全量

```bash
python3 -m pytest tests/test_validate_ac_alignment.py tests/test_validators.py -q
python3 -m pytest tests/test_shared_kernel.py tests/test_atlas_check.py tests/test_atlas_verify.py -q
python3 -m pytest tests/ -q
python3 scripts/atlas_check.py --fast
bash install.sh --target /tmp/probe --force     # 期望 exit 0
```

---

## 5. 开放问题

1. **未实现域分档**：v1 用「后端列 opt-in + 汇总 WARN」代替域实现状态；若真实项目噪声大，下一批再引入显式 `backend_test.domain_status` 或读页面表。
2. **多 app / monorepo**：v1 `apps` backend/fullstack > 1 ⇒ N/A；是否给 AC/测试加 app 归属？
3. **执行证据**：v1 是设计覆盖（active/weak）；是否接 JUnit，把 weak-only 升为执行证据检查？
4. **后端专用豁免**：UI 的 `不可验`/`结构类` 不豁免后端；v1 出路 = 后端列留空。是否需要后端专用清单？
5. **`*_test.py` / 非 pytest**：v1 只扫 `test_*.py` + pytest；扩展会改既有覆盖率/基线，另案。
6. **AC 文法**：`validate_prd`/`validate_ac_alignment` 是 `\d+`，`validate_e2e_index` 是 `\d{3}`；v1 只 WARN 非 3 位，是否另案统一。
7. **`atlas_check` 的 `N/A` 状态**：`--json` 消费者需适配；是否只在文本总览显示、JSON 保持 `ok`？
8. **`dim_mode`**：是否给 `backend_test` 增加 `dim_mode: advisory | off`，让「声明了但暂不查」显式化（下一批；代价是 schema 多一个键）。

---

## 6. 落地顺序与回滚

1. **等 RFC-01 落地并 rebase**（`_support/layout.py`、`install.sh`、`docs/map`、validators 的 layout 化）。
2. 抽 `_support/ac_coverage.py`，E2E 门纯替换 + golden 证明。
3. `validate_ac_alignment.py` 接后端列 + `dims` + active/weak + 汇总判据 + `Result` N/A。
4. `atlas_check` / `atlas_verify` 的 N/A 可见性。
5. 契约 / 模板 / 文档 / 计数 / 决策行同步。
6. 装配探针 + 全量测试。

**回滚**：单批 revert。无 schema/状态迁移；后端列是可选项；`dims=` 是可选项；E2E 判据/输出未变；索引解析未动。

---

## 7. 评审吸收对照

### 7.1 `REVIEW-20261026-04`（v3）的 blocker

| 评审问题 | Batch A 落点 |
|---|---|
| N/A 行语义误伤正常 E2E | §2.1.6：子项 N/A 只进 detail；只有整门末行 N/A 才行级 N/A；**早退改 N/A**，让整门 N/A 可达 |
| 未实现域无分档 | §2.1 第 6 条：后端列 opt-in；未实现域留空；汇总 WARN；不读跨环状态（显式取舍） |
| 多 app 规则不可判定 | §2.1 第 3 条：backend/fullstack > 1 ⇒ N/A「未建模」 |
| 整门 N/A 擦除好表 | §2.1.4：逐文件/逐表；一个坏表只跳过自身 |
| 备注/错位表头静默 | §2.1 第 5 条：含维度形态 ⇒ WARN |
| AST weak 实现不了 | §2.1.5：skipif/param/类级/模块级 pytestmark、类方法去重 |
| `*_test.py` 满屏假红 | §2.1.5：一条扫描面 WARN；不逐 AC 零测试 |
| 零变化无 harness / M159 只咬同名 | §4.2/§4.4：golden `checks[]` + 函数对象/无本地解析器钉 |
| enforce 文档/测试 | §2.1 第 10 条 + #20 |
| 装配/文档计数 | §3：README 386-390、iron-gates 35-44/97-99、shared/gates、docs/map/atlas-map、atlas_verify、BACKLOG |
| D/M 编号 | §3 占位，落地时重排 |
| E2E 两处小修拖住后端 | §10：Batch B 另立 RFC，本批不做 |

### 7.2 前两轮评审的必修

| 必修 | Batch A 落点 |
|---|---|
| 零测试不是 N/A | 汇总 WARN（§2.1.3） |
| 索引行 ≠ E2E 覆盖 | 后端门不读索引；E2E 门 D130 原样 |
| 单源边界 | 三个共享解析函数；索引解析不动（§2.1.7） |
| 零变化证明 | E2E 纯抽取 golden（§4.2） |
| PRD 严格化 | 按表头名定位；3/4 列 N/A；错位/备注 WARN（§2.1.4） |
| enforce 契约 | 四处同步；维度恒 WARN（§2.1 第 10 条） |
| opt-in / 非 pytest | 三重门 + 多 app N/A（§2.1 第 3 条） |
| 装配与文档面 | §3 全列 |
| 语法边界 | 精确 token / docstring 分离 / weak 形态 / 扫描面（§2.1.5） |
| 变异 | M-Фa-f（§4.4） |

### 7.3 `REVIEW-20261026-05`（Batch A）的 5 条必修

| 必修 | 落点 |
|---|---|
| 「疑似后端列」误伤标准 4 列 E2E 表 | §2.1.4：扫描只限「表头含 维度/备注/后端 或列位 ≥5」，排除 `适用覆盖维度`；#21 |
| 整门 N/A 不可达 | §2.1.6：早退 `PASS`→`N/A`；`Result.status` 全 N/A 分支；`stack-profile.md:100` 改口；#29 |
| 类方法去重键写错 / pytestmark AC | §2.1.5：`(file, line)`；`pytestmark` 只读 skip/xfail/skipif，AC 不支持（写明）；#24/#25/#26 |
| E2E 零变化无落点 / M-Фf 不咬 | §4.2：`e2e_coverage_dims_golden.json`、`allowed` 加 `parse_dims_cell`、monkeypatch 行为钉；§4.4 M-Фf |
| 模板占位制造假声明 | §2.1.4 / §3：`templates/prd/domain.md` 后端列占位 = 空 / `N/A`；#22 |

---

## 8. 与执行层边界的关系

本提案**不新增执行层能力**，也不生成/运行测试脚本；声明由项目测试代码承载，判据由 Atlas 校验器承载。属于 Atlas 契约层；与 `BACKLOG-execution-layer.md` 的 EL-01/EL-02 是上下游，不重复。落地后回写 EL-02 指针。

---

## 9. 附：探针复现

```bash
P=$(mktemp -d /tmp/atlas-dim-probe.XXXXXX)
mkdir -p "$P/product/prd" "$P/backend/tests"

cat > "$P/product/prd/test-prd.md" <<'EOF'
# 测试域 PRD
## 五、验收标准
| AC ID | 场景（Given / When / Then） | 回指规则 | 适用覆盖维度 | 后端适用覆盖维度 |
|---|---|---|---|---|
| `AC-TEST-001` | Given 合法输入 When 提交 Then 返回成功且落盘 | `R-001` |  | `C01, C02, C11` |
EOF

cat > "$P/product/stack-profile.yaml" <<'EOF'
product: 探针项目
origin: greenfield
apps:
  - name: backend
    path: backend
    kind: backend
    role: landing
    stack: python
backend_test:
  test_dir: backend/tests
  mode: advisory
  ac_marker: pytest_mark
EOF

cat > "$P/backend/tests/test_sample.py" <<'EOF'
import pytest

@pytest.mark.ac("AC-TEST-001", dims=["C01"])
def test_normal_flow_only():
    assert True
EOF

python3 validators/validate_ac_alignment.py --root "$P"
```

**当前输出**：四行全 PASS（后端列与 `dims` 均被忽略）。落地后预期：新增 `[WARN] AC × 覆盖维度（后端通道） —— AC-TEST-001 缺 C02,C11；后端=C01`。

---

## 10. Batch B（另立 RFC，暂不实施）

以下两项**不在本批**，避免 E2E 回归拖住后端能力：

1. **E2E 第 4 列表头校验**：第 4 列必须叫 `适用覆盖维度`；否则 `declared_ac_dims = {}` + N/A；逐表处理，不用一个坏文件擦掉好文件。
2. **E2E weak-only WARN**：用例状态 `blocked` / `skipped` / `prototype-pass` 记为 weak；某声明维度仅由 weak 用例覆盖 ⇒ WARN；`red` / `green` 仍 active；`prototype-pass` 的存量噪声需发布说明。

Batch B 需单独处理：D130/M131 回归、`prototype-pass` 迁移、表头解析（复用 `tables()`）、`atlas_check` 子项 N/A 的同一套语义。建议编号 `RFC-20261026-05`（占位，未起草）。

**隐式耦合（Batch A 必须认识）**：Batch A 的「疑似后端列」扫描必须认识第 4 列 `适用覆盖维度`，否则会把标准 E2E 表误判成后端列。这不是“只落后端门”能完全隔离的；Batch B 做表头校验时一并收敛。
