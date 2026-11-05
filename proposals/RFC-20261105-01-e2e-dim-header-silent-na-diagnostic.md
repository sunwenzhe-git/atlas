# E2E 维度表「表头未被采信」的可诊断化（只写设计，不含代码）

> 提案编号：RFC-20261105-01（主题段 `e2e-dim-header-silent-na-diagnostic`）
> 提案作者：@维护者（本草案由 Atlas 交互会话起草，**仅设计、未落代码、未提交**）
> 关联状态：草案 (Draft) ｜ **已按维护者裁定于 2026-11-05 定稿，待独立评审**（§8 已关闭）
> 重要裁定：本件定案 = 方案 **(b) / 落点 b1**；后端列并入（独立 reason）；H 非 canonical 表并入（另一 reason）；QUEUE 并入既有行；诊断文案不列 AC ID
> 影响范围：校验器 (validators) ｜ 环契约 (rings) ｜ 文档计数（`shared/gates.md` / `docs/map`）
> 上游依据：`DESIGN.md` D130（`DESIGN.md:599`）、D153（`DESIGN.md:628`）、H 收紧（`RFC-20261103-08` §4.5-b）
> 前置登记：`RFC-20261103-08` §4.5:154「已接受的残留面（2026-11-04 维护者拍板①）」+ `duty-review/QUEUE.md:32` 观察行

---

## 1. 现象与取证 (The Problem & Evidence)

### 1.1 触发形态（抽象）

* **规则 / 环节**：`validators/validate_e2e_index.py` 的「AC × 覆盖维度」门（`DESIGN.md` D130；解析单源 = `_support/ac_coverage.py::parse_dims_cell`，D153）。
* **触发时机**：域级 PRD §五 验收标准表的第 4 列表头**不是逐字 `适用覆盖维度`**（例如写成 `覆盖维度` / `后端适用覆盖维度` / `备注`），但该列**确实写了维度 token**，并跑 `validate_e2e_index.py` / `atlas_check`。
* **具体行为**：该表整张被跳过 → `declared_ac_dims = {}` → 门整体落 `N/A`，**输出里没有任何一行说明「这张表本来有维度声明、只是表头没被采信」**。

### 1.2 代码行证据（仓内实况，非推测）

| 位置 | 事实 |
|---|---|
| [validate_e2e_index.py:94](file:///Users/sunwenzhe/Desktop/atlas/validators/validate_e2e_index.py#L94) | 唯一合法表头写死：`E2E_DIM_HEADER = "适用覆盖维度"` |
| [validate_e2e_index.py:104-112](file:///Users/sunwenzhe/Desktop/atlas/validators/validate_e2e_index.py#L104-L112) | `is_canonical_ac_header`：前三列须按序 `AC ID` / `场景`（仅显式两形态）/ `回指规则` |
| [validate_e2e_index.py:389-390](file:///Users/sunwenzhe/Desktop/atlas/validators/validate_e2e_index.py#L389-L390) | `if not is_canonical_ac_header(hdr) or E2E_DIM_HEADER not in hdr: continue` —— **静默 `continue`，无任何记账** |
| [validate_e2e_index.py:400-401](file:///Users/sunwenzhe/Desktop/atlas/validators/validate_e2e_index.py#L400-L401) | 只有解析出非空 `dims` 才写 `declared[acid] = dims`（跨表**后者覆盖前者**，无并集、无重复告警） |
| [validate_e2e_index.py:731-732](file:///Users/sunwenzhe/Desktop/atlas/validators/validate_e2e_index.py#L731-L732) | `if not declared_ac_dims:` ⇒ `res.add("AC × 覆盖维度", "N/A", "域级 PRD 验收标准表未声明「适用覆盖维度」列（按需启用）")`；**同一函数的 PASS/WARN 出口是互斥分支**，故任何只挂在这个 N/A 分支上的诊断，在一坏一好（`declared` 非空）时永远不会出现——坏表被好表"压制" |
| [validate_e2e_index.py:1347-1349](file:///Users/sunwenzhe/Desktop/atlas/validators/validate_e2e_index.py#L1347-L1349) | 渲染器 `level not in ("PASS", "N/A")` 才打印 detail ⇒ **N/A 的 detail 在 CLI 输出里根本不出现**；`atlas_check` 只能读到 `[N/A ] AC × 覆盖维度` 这一行（[atlas_check.py:237-240](file:///Users/sunwenzhe/Desktop/atlas/scripts/atlas_check.py#L237-L240)） |
| [validate_e2e_index.py:222-234](file:///Users/sunwenzhe/Desktop/atlas/validators/validate_e2e_index.py#L222-L234) | `Result.status` 只认 `FAIL / WARN / N/A / PASS`，**没有 `SKIP` 态**（选方案 (c) 必须先补这一层） |
| [validate_ac_alignment.py:133-139](file:///Users/sunwenzhe/Desktop/atlas/validators/validate_ac_alignment.py#L133-L139) | D153 的后端门对 `后端适用覆盖维度` 位于第 4 列会出 WARN（「疑似与 E2E 列位混淆」），但**仅在 backend 通道可用时**（多后端 / 无 `backend_test` / 无 `test_dir` ⇒ 整门 N/A） |
| [validate_ac_alignment.py:164-185](file:///Users/sunwenzhe/Desktop/atlas/validators/validate_ac_alignment.py#L164-L185) | 「疑似后端列」扫描：只扫表头含 `维度/备注/后端` 或列位 ≥5 的列，**显式排除第 4 列 `适用覆盖维度`**；命中只 WARN、不判维度缺口 |

> **机制总结**：当前「表头正确性」是**接受面**（进则采信、不进则静默），不是**判据面**。接受面失败的代价是整表消失，且 `N/A` 的 detail 连输出都不打印——所以**"有维度但表头写错" 与 "项目根本没启用维度" 在输出上完全同形**。

### 1.3 「静默」会掩盖什么

* **单表场景**：唯一一张 AC 表把第 4 列写成 `覆盖维度`，内容 `C01-C02`，用例只覆盖 `C01` ⇒ 门报 `N/A`（"按需启用"），**`C02` 的覆盖缺口永不出现**；维护者/执行者会把 `N/A` 读成「本项目没启用这个门」，而事实是「声明了、被丢掉了」。
* **多表场景**：同文件一坏一好。好表里的 AC 照常对账；**只出现在坏表里的 AC 完全没有声明** → 它在判定面上不存在（`declared_ac_dims` 里没有键），不报缺口、不计入 `total_declared`、也不进 detail。门仍可 `PASS`/`WARN`，看起来"这一批维度没问题"。更糟的是：若诊断只挂在 `if not declared_ac_dims` 分支，**好表的存在会直接压掉坏表的诊断**（§1.2 末行），坏表在整个输出里完全消失。
* **跨门场景**：表头误写成 `后端适用覆盖维度` 时，D153 后端门会出「疑似列位混淆」WARN——**但只在 backend 通道可用时才出**；纯前端项目该 WARN 也消失 ⇒ 两个门都不出声。
* **为什么现在才立项**：这不是新发现的缺陷，而是 `RFC-20261103-08` §4.5 里**显式接受**的残留面（[RFC-20261103-08:154](file:///Users/sunwenzhe/Desktop/atlas/proposals/RFC-20261103-08-e2e-dim-header-validation.md#L154)「表头写错 ⇒ 无任何信号」）；上一批的选择是「不新增 WARN 文本」，观察行 = [QUEUE.md:32](file:///Users/sunwenzhe/Desktop/atlas/duty-review/QUEUE.md#L32)。本 RFC 是维护者要求**把这一条单独立项**，不是重开 D130 的裁决。

### 1.4 与 D130 / H 的关系（本 RFC 不动接受面）

* **D130**（`DESIGN.md:599`）原文 ③：「域级 PRD 验收标准表增加可选第 4 列 `适用覆盖维度`，**前三列保持不变**」；④：「未声明第 4 列的项目 ⇒ N/A 兜底，**绝不产生破坏存量的永久红门**」。→ 本 RFC **不改**第 4 列的名字、不改前三列、不把 N/A 升 FAIL（方案 (d) 会直接违反 ④）。
* **H**（`RFC-20261103-08` §4.5-b，2026-11-04）：`collect_e2e_declared_dims` 追加「前三列须按序 canonical，否则该表 N/A；第二列只认 `场景` / `场景（Given / When / Then）` 两形态」。→ 于是现在**有两个独立的静默失败面**：① 表头名不是 `适用覆盖维度`；② 表头名对但前三列/列序不 canonical。**维护者已裁定：两面都并入同一诊断，但必须用不同 reason**（① `misspelled_header` / `backend_column`，② `header_ok_order_rejected`；判别输入见 §3.1）。

---

## 2. 决策与权衡 (The Decision & Trade-offs)

> 四案只描述**设计**（改哪个函数、输出什么 token、动不动 verdict、存量会不会突然红、对 D153 的影响），保留作为裁决留痕。
> **维护者已于 2026-11-05 裁定：选 (b)，落点 b1。** 下文 §2.3 / §2.4 仅作被否记录，不作为待选方案。

### 2.1 方案 (a)：保持静默，只把残留写进发布说明（现状）

* **改哪个函数**：无。`collect_e2e_declared_dims` 保持 `continue`；`validate` 保持 `N/A`；渲染器保持「N/A 不打印 detail」。
* **输出 token**：不变（`[N/A ] AC × 覆盖维度`，无明细）。
* **改 verdict**：不。
* **存量突然红**：不会。
* **对 D153「疑似后端列」**：无影响。
* **代价**：缺口继续不可见；`N/A` 同时代表「未启用」和「写了但丢了」，两种语义**永久同形**。观察行只能靠真实仓「坏表头表有真实维度且无人发现 ⇒ 缺口逃逸」来触发升室——这个升室条件本身要求先发生事故，属**事后取证**。
* **已定事实**：这正是 2026-11-04 拍板① 接受的状态；选 (a) = 明确「接受面缺口不在机器面解决」。

### 2.2 方案 (b)：门输出加一条中性诊断（**已裁定采用；落点 b1**；不改判定）

* **改哪个函数**：
  * 新增（或扩返回）一个只读扫描：在 `collect_e2e_declared_dims` 的同一次表遍历里，把「未采信且有维度内容」的表记为一个**证据对象**（文件 + 第几列表头 + 分类），建议单源函数名 `collect_unaccepted_dim_tables(prd_files)`，与 `collect_e2e_declared_dims` 共用 `iter_md_tables` / `strip_md_cell` / `parse_dims_cell`；
  * `validate()` 的**三个出口**（PASS / WARN / N/A）共用同一 `note` 拼接：诊断不再挂在 `N/A` 分支（`:731-732`）里，而是与 `declared_ac_dims` 无关的独立量（§3.1）；
  * **必需附带（渲染器 `:1348` 写死）**：

    ```python
    if c["detail"] and (c["level"] not in ("PASS",) or "未采信表=" in c["detail"]):
    ```

    即 **7 处 `N/A` 全开**（维持既有口径），**`PASS` 仅在带 `note` 时**才多打一行 detail（`WARN` 原本就打印，不受影响）。备选口径 `or c["check"] == "AC × 覆盖维度"`：每个 PASS 仓每次多 1 行覆盖摘要，**若采用须在同一处（本段）记明**，默认不采用。
* **输出 token**：`[N/A ] AC × 覆盖维度 —— 未采信表=1（home-prd.md 第4列表头「覆盖维度」）`；一坏一好时 `[PASS ]` / `[WARN ]` 行同样带该段；合法表场景**逐字节不变**。
* **改 verdict**：**不改**（level 仍只由 `declared_ac_dims` 决定；不产生 WARN，不改退出码，不改 `atlas_check` 行状态）。
* **存量突然红**：不会。**状态与退出码不变**，但 7 处 `N/A` 行的 detail 会变长且**默认可见**，带诊断的 `PASS` 行也会多出可见 detail（渲染器只对带 `note` 的 PASS 开路）；`atlas_check` 汇总行仍读同一行文本，只是更长。
* **对 D153「疑似后端列」**：**已裁定纳入** —— 第 4 列 `后端适用覆盖维度` 的表会被本诊断以独立 reason `backend_column` 点名，文案明写「后端列，非 E2E 列」；与 D153 后端门在通道可用时的「疑似列位混淆」WARN **会重复点名一次**，此重复是**已知代价**，写入 §4.5 残留，不属于需再裁决项。若排除后端表头，纯前端仓（backend 门 N/A）将完全静默 ⇒ 已否决排除。
* **子形状对比（已裁定 b1）**：
  * **b1（并入现有 N/A 的 detail，需改渲染器）**：不新增 check 行；`Result.checks` 数量不变；语义最贴切（"这一门为何 N/A"）；代价是渲染器改动放开**本文件全部 7 处 `N/A` 的 detail 以及带诊断的 `PASS`**（[validate_e2e_index.py:417](file:///Users/sunwenzhe/Desktop/atlas/validators/validate_e2e_index.py#L417) 门控态 / [:600](file:///Users/sunwenzhe/Desktop/atlas/validators/validate_e2e_index.py#L600) 反向视图一致 / [:620](file:///Users/sunwenzhe/Desktop/atlas/validators/validate_e2e_index.py#L620) 关联AC 可达 / [:680](file:///Users/sunwenzhe/Desktop/atlas/validators/validate_e2e_index.py#L680) AC 反向覆盖 / [:732](file:///Users/sunwenzhe/Desktop/atlas/validators/validate_e2e_index.py#L732) AC × 覆盖维度 / [:782](file:///Users/sunwenzhe/Desktop/atlas/validators/validate_e2e_index.py#L782) 零证据用例须挂结构类 AC / [:1306](file:///Users/sunwenzhe/Desktop/atlas/validators/validate_e2e_index.py#L1306) manual 走查项形态）——除目标门外，另 **6 处 detail 会开始打印**；已核事实：这 6 处 detail 均为固定中文短语，**不含路径 / 项目名 / AC ID**，故不会把项目标识带进汇总行。
  * **b2（新增一条只统计的 PASS 行）**：无需改渲染器；信号在 `atlas_check` 行里独立可见；代价是**新增一条永远 PASS 的行**——「PASS」天然被读成"通过了"，与「只是记了个数」冲突，且 `Result.status` 全 N/A 判定会被这条 PASS 行破坏（[validate_e2e_index.py:232](file:///Users/sunwenzhe/Desktop/atlas/validators/validate_e2e_index.py#L232) 要求 `levels <= {"N/A"}` 才整门 N/A）。b2 需要额外处理这一处，故不推荐。

### 2.3 方案 (c)：结构性信号（N/A → 带 reason 的 SKIP，或新增计数子项）

* **改哪个函数**：
  * `validate()` 的 `N/A` 分支改为 `SKIP`（仅当「声明为空 ∧ 存在未采信表」），reason = 「表头未识别」；
  * `Result.status` 与 `Result.add` 需接受 `SKIP`（现在闭集只有 FAIL/WARN/N/A/PASS）；
  * 渲染器新增 `[SKIP]` 打印；
  * `atlas_check.check_validators` 新增 `[SKIP` 分支（否则落到 `:246` 的 `else` → 行状态 `ok` —— **SKIP 会被显示成 ok，这是本方案最大的假绿风险**）；
  * 若 `atlas_verify._parse_rows` 对行状态有闭集断言（D153 落过 N/A 兼容），需同步确认。
* **输出 token**：`[SKIP ] AC × 覆盖维度 —— 表头未识别：1 张表（home-prd.md:覆盖维度）`；`atlas_check` 行 = `SKIP <reason>`。
* **改 verdict**：**语义上是"通道"变化**（N/A → SKIP），退出码仍 0、不置红；但会改变 `atlas_check` 的行状态取值，进而影响任何按行状态做统计的消费面（控制台 / 巡检脚本）。
* **存量突然红**：不会红，但**会改变存量 `atlas_check` 总览的分布**（N/A 变 SKIP），属可见的"新增状态值"，不是零成本。
* **对 D153 影响**：同上（后端列会被判成 SKIP 表头未识别），且 D153 的 N/A 语义（`[N/A ]` 进 detail、整门 N/A 才行级 N/A）会与 SKIP 形成第二套"未走到这一步"的表达——两套并存容易漂。
* **代价**：面最宽（validator + 编排器 + 渲染 + 下游状态闭集），收益与 (b) 接近（仍然是"看得见"，不是"判得准"）。**（c）是"更响的 (b)"，不是更强的门。**

### 2.4 方案 (d)：收紧为 FAIL（最激进，不建议）

* **改哪个函数**：`collect_e2e_declared_dims` 把「未采信且有维度内容」直接 `res.add(..., "FAIL", ...)`，或让 `validate()` 在任何未采信表存在时置 FAIL。
* **输出 token**：`[FAIL] AC × 覆盖维度 —— 表头未被采信：1 张表`。
* **改 verdict**：**是**。退出码 1；`atlas_check` 该行 FAIL。
* **存量突然红**：**会**。任何把第 4 列写成 `备注` / `说明` 且散文里出现 `C01` 的存量表都会红（`has_dim_claim` 的 `Cc\d{1,2}` 会把「参见 C02」这类散文算作维度形态）；任何表头笔误的仓也会红。
* **为什么不建议**：
  1. **直接违反 D130 ④**「绝不产生破坏存量的永久红门」，属推翻已落地裁决 ⇒ 需走 **DR1（旧行号 + 新证据）**，代价远大于收益；
  2. **判据精度不够**：本信号只能证明"表头不像契约名且有维度形态"，不能证明"作者本意就是 E2E 维度列"（可能是后端列、可能是备注里的引用）；把不确定意图升成阻断 = 假红制造机；
  3. **修理路径不对**：表头写错是**文本规范问题**，契约（`rings/e2e/reference.md:336`）已逐字写明表头；把文本错误变成门禁红，会迫使执行者去改门而不是改表。
* **对 D153 影响**：后端列会被 E2E 门判 FAIL 而同时被后端门判 WARN ⇒ 两个门对同一张表给出相反强度，不可接受。

### 2.5 考虑过但被否的"真修复"变体（记录，防重开）

* **B′：近似表头也采信**（把 `覆盖维度` / `*维度` / 第 4 列位置一并吸收，退回 `RFC-20261103-08` 之前的位置式语义）。
  * *否定理由*：这正是上一批判定为**误读**并修掉的形态（RFC-20261103-08 §1.2）；按近似把声明吸收回来会重新引入「第 4 格写什么都算声明」的假采信，且会把后端列当 E2E 列。若维护者要"真修复"，那属于另一个命题（**声明回收**），应单独评估，不在本 RFC。
* **C′：只在文档里提醒，不改任何输出**。等价于 (a)，不重复。

---

## 3. 判据精确化（以方案 (b1) 为基准的真值表）

### 3.1 判据定义（写死，落地时必须逐字实现）

对每个 `*-prd.md` 文件、每张由 `_support/ac_coverage.iter_md_tables` 切出的表（`hdr` 经 `strip_md_cell`）：

```text
AC 表        := hdr 含 `AC ID` 且至少一行在该列匹配 AC_RE
已采信(E)    := is_canonical_ac_header(hdr) ∧ (`适用覆盖维度` ∈ hdr)
有维度内容   := ∃ 行 r（AC 行）∃ 列 j≥3：parse_dims_cell(r[j]) 命中的 dims 非空
未采信有维度 := ¬已采信 ∧ 有维度内容 ∧ 能落到三种 reason 之一   # 逐表 → collect_unaccepted_dim_tables
# 注：`∧ 能落到三种 reason 之一` **仅用于可达性证明**（保证三分支穷尽 ¬已采信），
#     不得实装为 `reason 缺失 ⇒ continue`——那会把 §3.1 的"落不到 reason = bug"降级成静默跳过。
采信声明     := 已采信 ∧ 维度格非空 → declared_ac_dims            # 逐表 → collect_e2e_declared_dims
诊断出现     := len(collect_unaccepted_dim_tables(prd_files)) > 0 # 与 declared_ac_dims 无关
```

**收集器签名（写死）**：

```python
def collect_unaccepted_dim_tables(prd_files: list[Path]) -> list[dict]
# 每项: {"file": <PRD 文件名>, "col": <1 基列号>, "header": <表头原文>, "reason": <三选一>}
# 与 collect_e2e_declared_dims 复用同一遍 iter_md_tables 扫描，但两个聚合互不依赖、互不覆盖
```

**拼接点（写死，必须能写成"与 `declared_ac_dims` 无关"）**：

```text
note       := "" if not unaccepted else "未采信表=N（file 第K列表头「hdr」…）"
level      := 只由 declared_ac_dims 决定（D130 的 PASS / WARN / N/A 语义不变）
输出       := res.add("AC × 覆盖维度", level, base_detail + note)   # 三个分支共用同一拼接
```

* 诊断的拼接**移出 `if not declared_ac_dims` 分支**（现状 [:731-732](file:///Users/sunwenzhe/Desktop/atlas/validators/validate_e2e_index.py#L731-L732)）：PASS / WARN / N/A 三条出口都要拼 `note`，`N/A` 只决定整门状态，**不决定诊断是否出现**。
* **这条同时修掉"一坏一好互相压制"**：好表产出的 `declared_ac_dims` 非空时，坏表诊断不再被 `if not declared_ac_dims` 吞掉（#7 / #8 / #14）。这正是 `RFC-20261103-08`「逐表处理，一张坏表不能擦掉同表的好表」原则的另一半：**一张好表也不能擦掉同表坏表的诊断**。

> **为什么 `有维度内容` 不排除 `适用覆盖维度` 列**：案例 #9（`场景 / AC ID / 回指规则 / 适用覆盖维度`）的唯一维度格子就在该列；若在这里排除它，`header_ok_order_rejected` 变成不可达分支。合法表由判定式里的 **`¬已采信`** 独立排除（#1/#1b/#12），不靠列名筛选。

* **只扫第 4 列及之后（`j ≥ 3`，0 基）**：避开前三列（尤其 `场景` 列）里的散文 `C01`，把假红面压到最小；这与 D153 的疑似扫描（`i >= 4` 或表头含 `维度/备注/后端`）**方向一致但判据独立**——D153 判后端声明，本诊断判"E2E 声明被丢"。
* **用 `parse_dims_cell` 判"有内容"、不用 `has_dim_claim` 宽匹配**：`C99` 这类未知写法 `parse_dims_cell` 返回空集 ⇒ **不算**"被丢弃的声明"（属另一条盲区，见 §3.3）。
* **三种 reason 的判别输入（已裁定：三种都发诊断，但必须区分；判别只依赖三个输入，无启发式）**：

  | 输入 | 取值 | 含义 |
  |---|---|---|
  | I1 | `适用覆盖维度` ∈ `hdr` ? | 表头名是否写对 |
  | I2 | `is_canonical_ac_header(hdr)` ? | 前三列/列序是否通过 H |
  | I3 | 按列序 `j` 升序扫描 `j≥3` 时，**第一个**「`hdr[j] != 适用覆盖维度` 且该列有维度内容」的列的表头字面值 | 误写的那个表头叫啥（可能是 `后端适用覆盖维度`） |

  判别顺序（互相排斥，逐表只出一条）：

  ```text
  (1) I1 ∧ ¬I2                       ⇒ reason = header_ok_order_rejected  # 成因：列序/前三列，非表头名
  (2) ¬I1 ∧ I3表头 == 后端适用覆盖维度 ⇒ reason = backend_column          # 成因：把后端列当 E2E 列
  (3) ¬I1 ∧ I3表头 != 后端适用覆盖维度 ⇒ reason = misspelled_header       # 成因：表头名笔误/自造
  ```

  * 若一张表同时有误写列（`j=3`）与后端列（`j=4`）：**按列序最小者定 reason** ⇒ `misspelled_header`，后端列不再单独点名（避免同表两条诊断）。这是**确定性**取舍，不留给实现自由裁量。
  * `header_ok_order_rejected` 与 `backend_column` / `misspelled_header` **不会同时出现**（前者要求 I1 真，后两者要求 I1 假）。
* **不列 AC ID（钉子级硬约束，见 §5）**：诊断只给「文件 + 第几列 + 表头原文 + 计数」。理由：既有钉 [test_validators.py:1545](file:///Users/sunwenzhe/Desktop/atlas/tests/test_validators.py#L1545) 与 [:1618](file:///Users/sunwenzhe/Desktop/atlas/tests/test_validators.py#L1618) 明确断言「错表头时 `AC-HOME-001` 不出现在 detail」，列出 AC ID 会让那两条钉翻红（而它们正是 M174/H 的反面包）。

### 3.2 真值表（每行一个输入 → 确定输出；基准 = (b1)）

| # | 输入（域级 PRD §五） | `declared_ac_dims` | 门 level / detail | 诊断条数 | 存量是否变红 |
|---|---|---|---|---|---|
| 1 | 4 列，表头逐字 `适用覆盖维度`，`C01-C02`，用例只覆盖 C01 | `{AC-001:{C01,C02}}` | `WARN` / `AC-HOME-001缺C02`（与今天逐字节一致） | 0 | 否 |
| 1b | 4 列，表头逐字 `适用覆盖维度`，第 4 格空 / `—`（**合法表、无声明**） | `{}` | `N/A` / 原文，**不含任何诊断文案** | 0（对偶钉基准） | 否 |
| 2 | 4 列，表头 `覆盖维度`，`C01-C02` | `{}` | `N/A` / 原文 + `未采信表=1（home-prd.md 第4列表头「覆盖维度」）` | 1（`misspelled_header`） | 否（N/A 变长） |
| 3 | 4 列，表头 `后端适用覆盖维度`，`C01-C02` | `{}` | `N/A` / 原文 + `未采信表=1（…「后端适用覆盖维度」= 后端列，非 E2E 列）` | 1（`backend_column`） | 否 |
| 4 | 4 列，表头 `覆盖维度`，第 4 格空 / `—` / 纯散文 | `{}` | `N/A` / 原文（无附加） | 0 | 否 |
| 5 | 3 列（`AC ID` / `场景` / `回指规则`） | `{}` | `N/A` / 原文（无附加） | 0 | 否 |
| 6 | 5 列，`适用覆盖维度` 出现**两次**（列 3、列 4），两格各有 `C01` / `C03` | `{AC-001: 列3的声明}`（`hdr.index` 取第一个） | `WARN`/缺口按列 3 算；列 4 静默 | 0（**盲区**：重复列不诊断） | 否 |
| 7 | 同文件两张 AC 表：好表（canonical，`AC-001` `C01`）+ 坏表（`覆盖维度`，`AC-002` `C03-C04`） | `{AC-001:{C01}}` | `PASS`（用例覆盖 C01）或 `WARN`（缺 C01 以外的声明）——只按好表算；`AC-002` 不参与判定 | 1（`misspelled_header`；旧设计下被 `declared` 压制为 0） | 否 |
| 8 | 同文件两张 AC 表：好表（`AC-001` `C01`）+ 坏表（`覆盖维度`，同一 `AC-001` 另写 `C03-C04`） | `{AC-001:{C01}}` | `WARN`（缺 C02，与 `test_e2e_dim_header_located_by_name` 的 mixed 断言一致） | 1 | 否 |
| 9 | 有 `适用覆盖维度`，但前三列写成 `场景`/`AC ID`/`回指规则`（H 已拒），第 4 格有 `C01` | `{}` | `N/A` / 原文 + `未采信表=1（…表头正确但列序未通过）` | 1（`header_ok_order_rejected`） | 否 |
| 10 | 4 列，表头 `覆盖维度`，第 4 格 `C99`（越界写法） | `{}`（`parse_dims_cell` 空集） | `N/A` / 原文（无附加） | 0（**盲区**） | 否 |
| 11 | 5 列：`覆盖维度`（列 3，`C01`）+ `后端适用覆盖维度`（列 4，`C02`） | `{}` | `N/A` / 原文 + `未采信表=1（…「覆盖维度」）` | 1（`misspelled_header`；按列序最小者，后端列**不**单独点名） | 否 |
| 12 | 5 列 canonical：`后端适用覆盖维度`（列 3，`C02`）+ 逐字 `适用覆盖维度`（列 4，`C01`） | `{AC-001:{C01}}` | 按今天正常判定；后端门可能另出 D153 WARN | 0（已采信，**合法后端列不触发**本诊断） | 否 |
| 13 | 5 列 canonical：`覆盖维度`（列 3，`C02`）+ 逐字 `适用覆盖维度`（列 4，`C01`） | `{AC-001:{C01}}` | 按今天正常判定（列 3 静默丢弃） | 0（已采信；**§3.3-6 盲区**） | 否 |
| 14 | **一坏一好、坏表在前**：坏表（`覆盖维度`，`AC-002` `C03-C04`）+ 好表（canonical，`AC-001` `C01`），**夹具固定"用例覆盖 C01"** | `{AC-001:{C01}}`（好表声明**照常统计**） | **`PASS`（确定性，不是 PASS/WARN）**；detail = 基础文案 + `未采信表=1（…「覆盖维度」）` | 1（`misspelled_header`；旧设计下被 `declared` 压制为 0） | 否 |

* **易假绿一条**：#2 / #7 —— 门输出 `N/A` 或 `PASS`，但实际有维度声明被丢弃；`N/A` 尤其会被读成"未启用"。旧实现里 #7/#14 连诊断都没有（被 `declared` 压制）。诊断只让"丢了"可见，**不会把声明拣回来**（缺口仍不判）。
* **易假红一条**：#3 / #6 若改用 `has_dim_claim` +「任意列」宽判据 —— `备注` 里的「参见 C02」也会被当「被丢弃的 E2E 声明」；在 (b) 下是噪声文案，在 (d) 下直接假红。故 §3.1 把判据收窄到 `j≥3` + `parse_dims_cell` + **`¬已采信`**（已采信表整体不诊断，含同时带合法后端列的 canonical 表）。

**按 B1 修订后的三 reason 可达性（逐行重算）**：

| reason | 命中行 | 可达条件 |
|---|---|---|
| `misspelled_header` | #2 / #7 / #8 / #11 | `¬I1 ∧ I3 表头 ≠ 后端适用覆盖维度` |
| `backend_column` | #3 | `¬I1 ∧ I3 表头 == 后端适用覆盖维度` |
| `header_ok_order_rejected` | #9（**B1 后唯一可达路径**：唯一维度格在 `适用覆盖维度` 列，若该列被排除则永不命中） | `I1 ∧ ¬I2` |

* 收敛为 0 的三类：#1 / #1b / #12 由 **`¬已采信`**（合法表）收敛；#4 / #5 / #10 由 **无维度内容**（空 `parse_dims_cell`）收敛；#6 因重复列所在表**已采信**而收敛（盲区留 §3.3-1）。

**实现约束（评审要求，写死）**：正常态签名固定为 `reason: <三选一>`，**不得把 `Optional[...]` 写进签名**；`reason=None` **只存在于 M190 注入态，正常态不可达**。reason 分支必须**穷尽 `¬已采信`**——不允许出现没有 `else` 的 `if/elif`；当前三分支恰好穷尽（`¬I1 ∧ I3==后端`、`¬I1 ∧ I3!=后端`、`I1 ∧ ¬I2`）。**出现「已判未采信却落不到 reason」= 兜底 reason 缺失 = bug**，不是可忽略分支。**不得**为 `I1∧I2` 补第四种兜底 reason（那是改设计，不是改变异）；M190 是靠"允许 `reason=None`"跨过 #1/#12 的分类缺口，而不是靠新增 reason。

**渲染约束（评审阻断项，写死进 `:1348`）**：

```python
if c["detail"] and (c["level"] not in ("PASS",) or "未采信表=" in c["detail"]):
```

* 语义：7 处 `N/A` 全开（维持既有口径）；**`PASS` 仅当 detail 带 `note` 时才打印**；`WARN` 原本就打印。
* **`未采信表=` 是字面量哨兵**：note 文案一旦变更（如改文案终稿、加 reason 前缀），**必须同步改 `:1348` 判定式与主钉第 6 条**——这是文案与判定式的显式耦合，不是实现细节；改文案漏改这两处 = 诊断静默消失。
* 备选口径 `or c["check"] == "AC × 覆盖维度"`：会让每个 PASS 仓每次多 1 行覆盖摘要（无条件）；**若采用须在此处记明**，默认不采用。
* 这条与 §2.2 的渲染器段落、§4.5 残留 4、§5.3 M189 是对同一判定的四处落点，**任一处单独改都会造成"文本有、CLI 无"**。

### 3.3 明确不覆盖（本 RFC 显式盲区，不得事后声称已覆盖）

1. 重复 `适用覆盖维度` 列（#6）：`hdr.index()` 取第一个，第二列静默丢弃；
2. 越界/未知写法（`C99` / `C15`）出现在 PRD 列（#10）：`parse_dims_cell` 空集 ⇒ 既不诊断也不缺口；
3. 同一 AC 在多张**合法**表重复声明：后者覆盖前者，无冲突告警（`declared[acid] = dims`）；
4. 诊断**不改变判定面**：被丢弃的维度仍不参与缺口计算，`total_declared` 不计入；
5. 诊断不覆盖前 3 列内部的维度散文（`场景` 列里写 `C01` 不算声明，也不算丢失）；
6. **「已采信表里的错名列」整体不诊断**：`AC ID / 场景 / 回指规则 / 覆盖维度`（col4 写 `C02`）`+ 适用覆盖维度`（col5 写 `C01`）⇒ `I1 ∧ I2` ⇒ 已采信 ⇒ **col4 的声明静默丢弃、不诊断**。这是 `¬已采信` 收敛的**必然代价**（与 #12 只差 col4 列名：col4 为合法后端列时不诊断是正确，col4 为自造列名时则是本条盲区）。将来不得把 #12 当作"已覆盖本盲区"。

---

## 4. 系统性修复三态判断（D156，`shared/gates.md:107`）

**逐条判（原文见 `shared/gates.md:106-107`）**：

| 触发条 | 判定 | 依据 |
|---|---|---|
| **(a) RFC §1 引子族锚（`bugs.md` 同根归纳）或 ≥3 条独立审查重复 finding** | **否（按本草案写法）** | §1 不引 `bugs.md` 同根归纳；缺口来源是 `RFC-20261103-08` §4.5:154 的**显式已接受残留** + `QUEUE.md:32` 观察行，不是新发现的同根族。`bugs.md` E2E 段无「表头」条目（实查：`grep -n "表头" duty-review/bugs.md` 零命中）。独立审查重复 finding 亦无 ≥3 条。 |
| **(b) 改门 / 校验器 / 契约判据且 diff 落在 DR4 段级锚路径族** | **命中** | 落地 diff 必然触及 `validators/validate_e2e_index.py` + `rings/e2e/reference.md` + `shared/gates.md` + `tests/test_validators.py`；E2E 段「契约字段 / 守卫面 ⇔ 生成器沉淀不同步」路径族保守包含前两者（与 `RFC-20261103-08` §4.5 同口径）。**落地时必须由作者附 `git diff --name-only` + `python3 scripts/closeout_derive.py --diff-base HEAD` 原始输出，评审自行重跑并留原文**（草案阶段无 diff，不能代跑）。 |

**三态结论 = `单案修复（无留出集）`**（选 (b) / (c) 时）：

* 留出独立性三条：① 要求「判据输出翻转（verdict / 案数 / 最近日期 / 精确病案数至少一项）」——(b) 只改 N/A 的 detail 文本，(c) 只改通道（N/A→SKIP），**两者都被 ① 明文排除**（"仅 WARN 文本 / 日志 / 通道变化不算"）⇒ 不可能拿出合格的翻转证据；
* ② 变异增量杀伤可以做到（M188），但那证明的是"新钉有效"，不是"留出案独立"；
* ③ 结构不可达：任何候选语料仍是"手写一张 AC 表 + 改第 4 列表头"，与既有钉夹具同族。
* ⇒ 只能走 `单案修复（无留出集）`：**必须**由独立评审确认「确无可行留出集」+ QUEUE 观察行 owner / 补验期限 + 残留风险写进本 RFC §4.5；**不得宣称闭族**。
* 若维护者选 (d)（verdict 翻转）：① 可满足（坏表头从 N/A 变 FAIL，属判据输出翻转），仍需 ②③ 与 pre-fix 红证；但由于 (d) 不建议（§2.4），本 RFC 不为其准备留出集。

**若改判据却无法闭族，如何登记（落地时照抄）**：

* `duty-review/QUEUE.md` 观察室：**已裁定并入既有 `RFC-20261103-08` 行（`QUEUE.md:32`）**，不新开第三条；在该行备注里写明「RFC-20261105-01 为**同一缺口的补充**（可见化），**不是新缺口**」。升室条件改写为「真实仓出现坏表头表有真实维度但诊断仍未出现（回归）」/「诊断出现但缺口仍无人处理 ⇒ 说明可见化不足以收敛」；owner + 期限见 §8 剩余确认项。
* `bugs.md` 指针行：`- 留出验证：RFC-20261105-01 / REVIEW-20261105-01`（无状态 / 无日期 / 无 `#NN`）。

## 4.5 留出验证（形状已定稿；落地时补原始输出）

* **触发面核对**：(a) 否（§4 表）；(b) 命中（路径族，落地附原始命令输出）。
* **留出集**：**无**（按 §4 三态论证：①排除文案/通道变化；③同夹具族）。
* **pre-fix / post-fix**：落地时按「新增钉 + M188」给 pre-fix 红（摘掉诊断 ⇒ 钉红）与 post-fix 绿。
* **反面包**：既有四条钉全绿 + 合法表输出逐字节不变 + 对偶钉（合法表无诊断文案）。
* **三态结论**：`单案修复（无留出集）`；评审确认 + QUEUE 观察行 owner / 期限 + 残留风险入本节；**不宣称闭族**。
* **残留面（本批显式接受，不得事后当作已解决）**：
  1. **与 D153 重复点名**：`后端适用覆盖维度` 表在 backend 通道可用时，会被本诊断（`backend_column`）与 D153 后端门（「疑似列位混淆」WARN）各点一次；属维护者 2026-11-05 明确接受的代价（为保证纯前端仓也有信号）。
  2. **诊断不拣回声明**：坏表头的维度仍不参与缺口计算、不计入 `total_declared`；"看得见"不等于"判得准"。
  3. §3.3 **六条**盲区（重复列 / 未知写法 / 跨表同 AC 覆盖 / 非判定 / 前三列散文 / 已采信表内错名列）。
  4. 渲染器放开后，本校验器**全部 7 处** `N/A` 的 detail 都会开始打印（除目标门 `:732` 外，另有 `:417` / `:600` / `:620` / `:680` / `:782` / `:1306` 共 6 处；均已核为固定中文短语，不含路径 / 项目名 / AC ID）；**另加：带诊断的 `PASS` 行**（仅当 `detail` 含 `未采信表=`，见 §3.1 渲染约束）。输出面变宽，非缺陷。
* **唯一判定记录** = 本节 + `REVIEW-20261105-01`（不新增台账）。

---

## 5. 测试钉与变异（定案 b1；默认不新增测试文件）

### 5.1 钉子级硬约束（不是注释，由钉强制）

**H-1｜诊断文案不得出现任何 AC ID。** 判据层（§3.1）只产出「文件名 + 列位 + 表头原文 + 计数」；任何把 `AC-HOME-001` 之类写进 detail 的实现都会让 `test_e2e_dim_header_unaccepted_table_is_diagnosed` 与既有 `test_validators.py:1545/1618` 同时红。钉内断言用**通配**而非单值：`re.search(r"AC-[A-Z0-9]+-\d+", detail) is None`（覆盖 `AC-HOME-001` / `AC-BE-002` 等），且该断言写在**每一条错表头 case** 上。

### 5.2 两条钉（主钉 + 对偶反面包）

* **落点**：`tests/test_validators.py`（既有文件），紧跟 `test_e2e_dim_header_requires_canonical_first_three_columns` 之后。
* **主钉**：`test_e2e_dim_header_unaccepted_table_is_diagnosed`（正向；**分组**：有维度的错表头 = #2/#3/#9/#11/#14/#7/#8，无维度/无表 = #4/#5）：
  1. **按 case 的期望状态逐条断言**（不再整组断言同一个 level）：#2/#3/#9/#11 ⇒ `N/A`；#7 ⇒ `PASS` 或 `WARN`（由好表覆盖情况决定）；**#14 ⇒ `== "PASS"`**（夹具固定"用例覆盖 C01"，确定性）；#8 ⇒ `WARN`。**不得把 #7/#8/#14 归入"level 仍 N/A"的整组断言**（这是既有复核指出的 `:243-244` 风险）。**#14 必须钉死 PASS**：若 #14 落 `WARN`，旧判定式本就打印 detail ⇒ 第 6 条的 #14 侧不咬，M189 就只剩 N/A 半边。
  2. **有维度的错表头（#2/#3/#9/#11/#7/#8/#14）**：detail 含文件名、1 基列号、表头原文与 reason 词；**且 H-1 通配断言通过**。
  3. **同组**逐例断言三种 reason（`misspelled_header` / `backend_column` / `header_ok_order_rejected`）；#11 断言 `misspelled_header` 且**不出现** `后端列，非 E2E 列`（列序最小者优先）。
  4. **压制回归（本次结构修复的正向钉）**：#7 / #14 断言「好表声明照常统计（`declared` 含 AC-001）+ 坏表诊断同时出现」，即**诊断条数 == 1 且 level 不是 N/A**；旧实现下该断言必红（诊断被 `if not declared_ac_dims` 吞掉）。
  5. **仅此组**：#4 / #5（无维度内容 / 4 列以下）⇒ 诊断 0 条，输出与今天逐字一致；**不套用第 2/3 条**。
  6. **渲染面**：对 #2（`N/A`）与 #14（**`PASS`**）各断言 CLI 行含诊断文本（N/A 行必须出现 `[N/A ]` + detail；#14 的 **PASS** 行必须因 `note` 而出现 detail，否则 b1 渲染器改动无钉保护）。
* **对偶钉（维护者新增）**：`test_e2e_dim_header_accepted_has_no_diagnostic`
  * 输入 = §3.2 **#1 / #1b / #12 / #13**（合法表：一例有维度但用例只覆盖 C01；一例第 4 格为空；一例 canonical 5 列带合法后端列；一例 canonical 5 列带自造错名列=盲区 6）；
  * 断言 A（收集器级，M190 的直接杀伤面）：`collect_unaccepted_dim_tables(cases) == []`；
  * 断言 B：`res.checks` 的 `AC × 覆盖维度` **detail 与今天逐字节一致**；detail 与渲染行**均不含**禁词表 `未采信` / `表头未识别` / `表头正确但列序未通过` / `后端列，非 E2E 列` 任一（含 `表头正确但列序未通过` 是因为 #9 的实际文案走这条；任何兜底分支不论走哪条 reason 都会被咬住）；
  * **防的是什么**：(i) 防收集器漏掉 `¬已采信` 条件而「诊断泛化到所有 AC 表」——即把合法表也点名（#12 专门看住"合法后端列不被误当 E2E 声明"）；(ii) 防 b1 的渲染器放开（`N/A` detail 开始打印）被顺手做成「所有 N/A 都带诊断文案」——**放开打印 ≠ 泛化诊断**，两者必须解耦。断言 A 是 (i) 的硬面，也是 M190 的专用杀伤面。
* **夹具**：`tests/fixtures/e2e_coverage_dims_golden.json` 追加键 `e2e_dim_header_reject_cases`（每例 `{header, cells, expect_reason|null}`），**不新建 Fixture 文件**。
* **反面包**：既有四条钉必须全绿不动 —— `test_e2e_index_coverage_dimensions_pass_and_warn`（M131）、`test_e2e_dim_header_located_by_name`（M174）、`test_e2e_dim_header_requires_canonical_first_three_columns`（H）、`test_is_canonical_ac_header_only_two_scene_forms`（H 收紧）。

### 5.3 变异（仓内实况：M191 已被 teardown、M192 已被 run_python 占用；M188–M190 空闲，本批按此取号；M131 是旧号，不续用）

| 号 | 手法 | 预期红/绿 |
|---|---|---|
| **M188** | 删诊断聚合（`collect_unaccepted_dim_tables` 恒返回空 / 删 detail 拼接） | 主钉红；对偶钉绿；既有四条钉绿 |
| **M189** | 渲染器判定式回退为旧的 `level not in ("PASS","N/A")`（`:` 原句） | 主钉第 6 条红，**跨两种 level**：#2（N/A，detail 不打印）与 #14（PASS，note 不打印）；对偶钉绿（合法表无 note，PASS 本就不打印 detail，输出不变） |
| **M190** | **在收集器注入**：`collect_unaccepted_dim_tables` 去掉 `¬已采信` 守卫（**实测注入面仅此一行**）；`reason=None` 与"`未采信表=N（…）` 格式化无条件执行"是**设计约束、不是本次注入面**——摘守卫后 #1 已落到既有 `header_ok_order_rejected`，无需第四种兜底 reason（报告 `M190.txt` 如实登记该差异） | **对偶钉红**：断言 A（`collect_unaccepted_dim_tables` 对 #1/#12/#13 返回 `[]`）先红；#1 `AC ID/场景/回指规则/适用覆盖维度` + `C01-C02` 的 suspects 非空（`reason=header_ok_order_rejected`），渲染面撞禁词 `未采信`；主钉绿（错表头照常诊断，#14 仍 `PASS`）；既有钉绿 |

* 四段协议（基线 GREEN → 注入 RED → 逐字节还原 → 复绿），报告 `.atlas/runs/mutation-proof/M188.txt` / `M189.txt` / `M190.txt`（各含注入 diff）。
* **M189 的一一对应**：钉必须同时断言 N/A 行（#2）与带 note 的 PASS 行（#14）；只断言其一时，回退旧判定式只会让另一半红，另一半"假绿"。两条断言落在同一钉内、共用一个回退注入，故仍是一变异对一钉。主钉实现为"先收集两条 CLI 行、再统一断言"，失败信息同时打印两条行（`M189.txt` 实测 `{'N/A': …, 'PASS': …}` 两行均无 `未采信表=`）。
* **M190 注入面收窄**：`reason=None` 与"无条件格式化"是防止未来把诊断绑进 reason 分类的**设计约束**，本批未注它们；实测注入面只有守卫行。报告不得据此宣称"`reason=None` 路径已验证"。
* **计数不变**：钉仍是 2 个测试函数（主钉 + 对偶钉，收集器断言并入对偶钉），`shared/gates.md:47` 的 `185 → 187` 不变；不新增测试文件。

---

## 6. 计数与 docs/map 影响

| 计数面 | 当前 | (a) | (b1)/(b2) | (c) | (d) |
|---|---|---|---|---|---|
| 校验器 10（`atlas_check.VALIDATORS`，[docs/map/index.md:106](file:///Users/sunwenzhe/Desktop/atlas/docs/map/index.md#L106)） | 10 | 不动 | 不动（仍改同一校验器） | 不动 | 不动 |
| 出厂测试文件 56（[index.md:108](file:///Users/sunwenzhe/Desktop/atlas/docs/map/index.md#L108) / [gates.md:114](file:///Users/sunwenzhe/Desktop/atlas/shared/gates.md#L114)） | 56 | 不动 | **不动**（钉进既有 `test_validators.py`） | 不动 | 不动 |
| `install.py` 自检 66 条（[index.md:113](file:///Users/sunwenzhe/Desktop/atlas/docs/map/index.md#L113)） | 66 | 不动 | 不动 | 不动 | 不动 |
| 共享内核 14 件（[index.md:112](file:///Users/sunwenzhe/Desktop/atlas/docs/map/index.md#L112)） | 14 | 不动 | 不动（复用既有 `iter_md_tables` / `parse_dims_cell`，**不新增解析器**） | 不动 | 不动 |
| `shared/gates.md:47` 自述「`test_validators.py` 185 条」 | 185 | 不动 | **187**（+2 钉：主钉 + 对偶钉；该行人工计数需同步；canonical 对账门只查「N 个测试文件」类，不查这一行，但写死计数不对账会踩 `3509 §B105` 的旧教训） | 187 | 187 |

> 表内 (c)/(d) 列仅为被否案留痕；**定案 = b1**（2026-11-05 裁定）。

**「改文案不改判定」（选 (b1)）要动的文档面**：

* `shared/gates.md` §2.1 `validate_e2e_index.py` 行（`:47`）：在「AC × 覆盖维度列按表头名定位」后加半句「未采信表 ⇒ 该门 detail 点名（PASS/WARN/N/A 三出口；不改判定；三种 reason 分列）」，并把 `185` → `187`。
* `rings/e2e/reference.md:336` 与 `:615`：「表头不符 ⇒ 该表按未声明（N/A）」后补「并在 detail 点名未采信表（**不因同文件另有合法表而消失**；不改判定）」。
* `docs/map/gates.md:55` 摘要行：追加「+ 未采信表诊断」。
* `docs/map/index.md` / `atlas-map.html`：**计数不变**（10 / 56 / 66 / 14 全不动）；`install.py` 自检 66 条本批未触及，**未逐条重数**（不作"已复核"宣称）；`atlas-map.html:355` 的 tip 文案可选更新（无锚）。
* 锚点实查：`docs/map/` 内**没有**指向 `validate_e2e_index.py` 的「符号（path:line）」锚（`grep -rn "validate_e2e_index" docs/map/` 仅 `atlas-map.html:355`、`e2egen.md:64`、`gates.md:55` 三处纯文本），故函数体行号漂移不会触发 `test_map_anchors.py`；但按纪律落地仍须跑 `python3 -m pytest tests/test_map_anchors.py -q`。

**「改判定」（选 (c)/(d)）额外要动的面**：

* (c)：`scripts/atlas_check.py`（`[SKIP` 分支）+ `shared/gates.md` §2.2 编排行（新增状态取值）+ 渲染器 + 可能的 `atlas_verify._parse_rows` 状态闭集；`gates.md` 的「10 校验器」不变。
* (d)：`DESIGN.md` §12 **必须新增决策行**（显式推翻 D130 ④ 的「绝不产生破坏存量的永久红门」），并走 DR1（旧行号 `DESIGN.md:599` + 新证据）；`gates.md` §2.1 行改「错表头 ⇒ FAIL」；`rings/e2e/reference.md:336/615` 的「N/A 兜底」全部改写；`docs/map/gates.md:55` 同步。

**全量复跑留证（2026-11-05，实现后评审应修 7）**：

* 命令：`PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/ -q -p no:cacheprovider`
* 结果（27 分钟后人工中断）：`269 passed, 2 skipped in 1623.48s (0:27:03)`，`KeyboardInterrupt` 落在
  `/opt/homebrew/.../python3.12/selectors.py:415`；中断前日志在 `17%` 后连续 54 个点、**超过 2 分钟字节数零增长**。
* 卡点定位（单跑复现）：`tests/test_atlas_verify_playground.py::test_playground_red_batch_keeps_evidence_and_skips_archive`
  单独运行同样挂起（74.07s 后中断、`no tests ran`）。该用例是真跑级 Playwright 批（注红 → 跑 E2E → 查 trace），
  属本沙箱环境下无法跑完的用例，**与本批改动无关**。
* **结论修正**：此前"全量 exit 1 只是沙箱拦写盘"的归因**撤回**（未留证据，不再宣称）。可证的是：`test_validators.py`
  187 条单跑 `187 passed in 1.47s`、无拦截行；全量在本机卡在该 Playwright 用例，未产出最终汇总，
  故"全绿"不作宣称。全量最终结论待有浏览器能力的 CI 环境复跑。

---

## 7. 编号与同日撞号

* **实查（起草时刻，2026-11-05 当日）**：`ls proposals/ | grep 20261105` = **零命中**（最近为 2026-11-04 的 `RFC-20261104-01` / `RFC-20261104-02`）；`ls proposals/ | grep REVIEW-20261105` = 零命中。
* ⇒ 本草案占 **`RFC-20261105-01`**；评审号预留 **`REVIEW-20261105-01`**。
* 若同日出现第二份 RFC（并行会话）⇒ 按 `proposals/README.md:60` 保留先落盘者，后到者文件名加主题后缀（本件后缀 = `-e2e-dim-header-silent-na-diagnostic`），并在引用裁决行时**点名自己引用哪一份**；评审同理（第二份加 `-e2e-dim-header-diagnostic`）。
* 不铸造 D / M / F / R 号：D 号归 `DESIGN.md` §12 落地时分配，M 号按 §5 续 **M188–M190**。

---

## 8. 已关闭的裁定与默认口径

> **已按维护者裁定于 2026-11-05 定稿。** 下表 1–8 为已关闭项（留痕，不再讨论）；§8.2 为默认口径（不阻塞实施）。

### 8.1 已关闭（维护者 2026-11-05 裁定）

| # | 决策点 | 裁定 | 落地后果 |
|---|---|---|---|
| 1 | 选案 | **(b)，落点 b1** | 诊断拼进现有 `AC × 覆盖维度` 行的 detail，**PASS / WARN / N/A 三出口共用、与 `declared_ac_dims` 无关**（独立收集器 `collect_unaccepted_dim_tables`）；并**放开渲染器对 `N/A` 的打印，以及带诊断的 `PASS`/`WARN`**（`:1348` 判定式见 §3.1）；不改 verdict、不新开永远 PASS 的计数行 |
| 2 | `后端适用覆盖维度` 表 | **纳入，独立 reason `backend_column`** | 与 D153 在 backend 通道可用时重复点名一次 = 已知代价，已写进 §4.5 残留 1 |
| 3 | H 的非 canonical 表 | **并入同一诊断，独立 reason `header_ok_order_rejected`** | 判别输入 I1/I2/I3 + 互斥优先序写死（§3.1）；不会与另两种 reason 同时出现 |
| 4 | QUEUE 登记 | **并入 `RFC-20261103-08` 行（`QUEUE.md:32`），不新开第三条** | 行内注明「RFC-20261105-01 为同一缺口的补充（可见化），不是新缺口」；升室条件按 §4 改写 |
| 5 | 诊断文案含 AC ID | **禁止（钉子级硬约束 H-1）** | §5.1 用通配断言 `AC-[A-Z0-9]+-\d+` 强制；保住 `test_validators.py:1545/1618` 两条反面包 |
| 6 | 重复维度列（两列同名） | **登记盲区** | §3.3-1；`hdr.index()` 取第一个，第二列仍静默 |
| 7 | PRD 列未知写法（`C99`/`C15`） | **另批** | §3.3-2；沿用后端门 `unknown_dim_tokens` 口径时再评估 |
| 8 | 「`N/A` detail 不打印」缺陷 | **并入 b1 作为附带修改** | 渲染器改为「`N/A` 全开 + 带诊断的 `PASS` 才开」（§3.1）；7 处 `N/A` detail 开始打印（除 `:732` 外另 6 处，均为固定中文短语，不含路径/项目名/AC ID），另加带 `未采信表=` 的 PASS 行 |

### 8.2 默认口径（不阻塞实施）

| # | 事项 | 口径 | 影响 |
|---|---|---|---|
| A | **QUEUE 行 owner / 期限** | **沿用 `QUEUE.md:32` 的 owner/期限**；是否重设只影响到期复评的时点 | 不重设则按原期限复评；重设只在行内追加第二段期限与起点，不构成"缺要件" |
| B | **诊断文案终稿**（§2.2/§3.2 样例：`未采信表=1（home-prd.md 第4列表头「覆盖维度」）` 等） | 默认照用（三种 reason 各一句固定模板，常量集中一处） | 若要改措辞，只发生在实施时同步 §3.2 表格与 §5 断言字面量，不影响判据/verdict |

---

## 9. 明确范围外（本批不得顺手实现）

1. 「声明回收 / 近似表头采信」（§2.5 B′）——另一命题，需单独 RFC；
2. weak-only WARN（`blocked/skipped/prototype-pass` 记 weak）——`RFC-20261103-08` §5 已明确范围外；
3. 重复列 / 未知写法 / 跨表同 AC 冲突（§3.3）——本批只登记盲区；
4. 任何「改判定」的变体（(d)）——若你要选，本 RFC 需重写 §2.4 与 §4 并走 DR1；
5. 全量 pytest / 全仓跑（本草案阶段不跑、不需要）。