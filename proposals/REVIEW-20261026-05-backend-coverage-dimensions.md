# REVIEW-20261026-05 · Batch A 后端门 v4 短评审

> **对象**：`proposals/RFC-20261026-02-backend-coverage-dimensions.md` v4 / Batch A
> **归档注记（2026-10-26 晚）**：v4 已按本评审升级为 **v4.1**，5 条必修全部落（见 v4.1 §7.3）。
> **评审者**：tech-proposal-reviewer（只读）
> **时点**：2026-10-26
> **基线**：`HEAD 7112155` + RFC-01 在飞。工作区实况：`_support/` 9 件（含未跟踪 `layout.py`）、`install.sh` 55 条 `check`、`docs/map` 9 件/55 条/40 测试文件、`DESIGN.md` 最大 D151、`shared/gates.md` 最大 M155。

## 总判定：修后通过

Batch A 的边界收口成立：只落后端门、E2E 判据不动、索引解析不动、D130/M131 不碰，方向正确。但现稿仍有四条会让实现出错或产生永久假 WARN 的问题：**标准 4 列 E2E 表会被“疑似后端列”规则误判**、**整门 N/A 在现有早退下不可达**、**类方法去重键写错**、**E2E 抽取的“零变化证明”没有可执行落点**。这些是局部实现级修正，不需要推翻骨架，故判“修后通过”。

## 逐问判定

1. **N/A 子项与早退：有保留（近否决）。** `validate_ac_alignment.py:250-252` 早退加的是 `AC对账门禁运行态 PASS`；`Result.status:55-61` 没有 N/A 分支，全 N/A 会返回 PASS；且完整路径恒有四条 PASS/WARN/FAIL。因此后端门**子 N/A 可达**（有 PRD AC 或 tests、但无合法后端列时），**整门 N/A 不可达**。`atlas_check` 的 padded 匹配可行（`:899` 用 `{status:<4}`，`N/A` 输出为 `[N/A ]`）；`atlas_verify._parse_rows:102` 白名单加 `N/A` 可行；`--json` 加值可行，但 `ok` 仍是 `not rows.failed`（`:814`），N/A 不会置红。**最小修法**：早退改 `res.add("AC对账门禁运行态", "N/A", ...)`，`Result.status` 加 `if self.checks and statuses <= {"N/A"}: return "N/A"`，并同步 `shared/stack-profile.md:100` 的“按降级通过”改为“按 N/A”；若不想改早退，则删掉“全 N/A ⇒ N/A”这句话，只保留子项 detail。两条路必须二选一，不能像现稿两头都写。

2. **逐表/表头定位：否决（现稿会误伤存量）。** `rings/prd/reference.md:193-196` 与 `templates/prd/domain.md:105` 的标准 4 列表，第 4 列就是 `适用覆盖维度`，单元格合法写 `C01, C02`。v4 §2.1.4 写“找不到后端表头 ⇒ 任一单元格含 `C\d{1,2}` ⇒ WARN”，这会把每个启用 D130 的存量项目判成 WARN，直接违反“存量前端项目零影响”。我用 `validate_e2e_index.tables()` 解析标准 4 列表，`any C-digit cell=True`。3 列夹具合法（`tests/test_validate_ac_alignment.py:46`）；`## 5.` 若按全文件表扫描可解析，若误用 `validate_prd.section_of`（`:198`）会静默失败，v4 未指定。6 列/列序变化按表头名可行。**修法**：疑似扫描只对“表头含 维度/备注/后端 或列位≥5”的列生效，永远排除表头为 `适用覆盖维度` 的列；每表最多一条 WARN；只有全项目无合法后端列才整门 N/A。另：`templates/prd/domain.md` 新列若复制现有 `[可选：C01-C14 ... C01, C02]` 占位，会被解析成真实 C01/C02/C14 声明并触发零测试 WARN，模板单元格应写 `N/A` 或留空。

3. **零测试 opt-in：有保留（可接受的显式取舍）。** 用“后端列 opt-in + 留空 + 一条汇总 WARN + 不读域状态”替代 review-04 的域分档，是 v1 的合理收窄；v4 已写明“留空=未声明，不是豁免”，且把“无 `test_*.py`”降为一条扫描面 WARN，噪声可控。残余风险是 PRD 先写列、测试后补时 WARN 长期存在，作者可能用留空消音，等于藏缺口。建议最小补一句硬约束并加测试：5 列单元格空白/`N/A`/`—`/`-` 不 WARN；`test_dir` 无任何 `test_*.py` 时不逐 AC 报零测试。不需要在本批引入 `domain_status`。

4. **AST weak：有保留（会漏/会误判）。** `PyTestACVisitor.visit_ClassDef:195-200` 先带 prefix 访问方法，再 `generic_visit`，同方法二次入列；探针得到 `TestX.test_m` 与 `test_m` 同一 `line 7`。v4 的去重键 `(file, name, line)` 因 name 不同**不去重**，应改为 `(file, line)` 或先在 visitor 内统一 name。模块级 `pytestmark` 是 `Assign`，现有 visitor 不读；探针 `pytestmark = pytest.mark.skipif(False)` 不影响 `skipped`。`skipif(False)` 也仍 `skipped=False`（v4 说保守 weak，需实现并测试）。类/模块 `pytestmark` 若带 `pytest.mark.ac(...)`，v4 只把它用于 weak，AC 会被忽略；要么支持 AC，要么在契约写明“pytestmark 只作 weak，AC 必须函数装饰器”。`parametrize(marks=...)` 可做，但 `pytest.param(..., marks=...)` 未提。

5. **E2E 纯抽取 golden：有保留（可做，但“证明”未落地）。** 闭包依赖 `_DIM_TOKEN`/`_dim_range_re`/`_dim_code_re`/`_dim_looks_re`（`validate_e2e_index.py:602-605`），抽取时须一并搬走；返回 `(dims, looks)`，`bad_case_dims` 的 `looks` 必须保留，v4 未给签名。我在 `/tmp/rev5` 做了等价抽取：7 组语料（`C01-C02`、`C01正常流`、`N/A`、空、`C99`、`C01`、`C01-C03`）改前/改后 `checks[]` JSON 完全一致，共 55 条，`checks` 本身不含 root。可见“逐字节 `checks[]`（排除 root）”可执行，但必须提交 golden 文件或“HEAD 模块 vs 新模块”的一次性脚本；现稿只有口号。`tests/test_shared_kernel.py:218-241` 的唯一性守卫只匹配 `^def <name>(`，须把 `parse_dims_cell` 加进 `allowed`；对象钉（`:244-256`）只证明别名，不证明调用点。`M-Фf` 需行为钉：monkeypatch `validate_e2e_index.parse_dims_cell`，断言 `AC × 覆盖维度` 结果变化；否则“保留别名、实际走本地副本”不红。抽取代价小、收益真，建议保留，但作为独立第一提交，先 golden 后接后端门。

### 附加检查

- **review-04 的 11 条**：真吸收的是多 app（#3）、enforce（#8）、逐表聚合的骨架（#4）、D/M 占位（#11）；部分吸收的是 N/A（#1，Result 不可达）、逐表/备注（#4/#5，误伤 E2E 列）、AST（#6，去重键与 pytestmark AC）、零变化（#9，无 golden 落点、无行为钉）、计数（#10，无具体目标数）；零测试分档（#2）是显式取舍而非吸收。**假吸收**：“AST weak 实现不了”“零变化 harness/M159”“错位/备注不再静默”“Result N/A”四处，现稿文字已覆盖，实现口径仍不成立。
- **Batch B 隔离**：基本成立（不读索引/分片），但“疑似后端列”规则会读 E2E 第 4 列，必须白名单 `适用覆盖维度`；`atlas_check` 行 N/A 还会把空 E2E 项目从今天的 `ok validate_e2e_index N/A`（`test_validators.py:1291-1293`）改成 `N/A` 行。这不是 validator 行为变化，但不能宣称“可见面零变化”。
- **计数**：9→10 / 55→56 对当前工作区正确（install 55、`_support` 9）。漏了具体落点：`shared/gates.md:77` 55→56、`:45` 146→146+n、`:65` 42→42+n；`docs/map/index.md:37/111` 9→10、`:112` 55→56、`:58` 719 行；`docs/map/atlas-map.html` 的 `54 条` 有 3 处（393/527/529）、`内核 ×9`（172）；`README.md:394`、`BACKLOG-execution-layer.md` §8。`atlas-map.html` 的 `54 条` 不被 `test_map_anchors` 咬住，必须手工 sweep。
- **测试/变异**：20 条矩阵不够。缺：5/6 列、空白/`N/A`/`—`/`-` 单元格、标准 4 列 E2E 含 `C01` 必须不 WARN、`## 5.`、`dims` 元组/逗号串/字符串、`skipif(False)`、模块级 `pytestmark`、类方法双访问计数、docstring-only 零测试、无 `test_*.py`、`*_test.py` 与 `test_*.py` 混存、语法错误+好文件、跨 PRD 重复 AC、仅全局 `prd.md`、enforce+零测试、`atlas_check --json`/`atlas_verify` 的 N/A 行。M-Фa–e 基本能咬；M-Фf 不咬（唯一性未加 `parse_dims_cell`）。另缺：未知/孤儿 dims、docstring 分离、类/模块 weak、N/A 行、去重、`looks` 丢失的变异。
- **D/M 占位**：v4 已用 D 占位、M-Фa–f，正确；`DESIGN.md` 最大 D151、gates 最大 M155，D152/M156 确实可能被 RFC-01 占用，保持占位即可。

## 必修项

1. **修“疑似后端列”误伤**：只对表头含 维度/备注/后端 或列位≥5 的列做 `C\d` 扫描，排除 `适用覆盖维度` 列；每表最多一条 WARN。为什么：标准 4 列 E2E 表会永久 WARN。验证：标准 4 列 `C01,C02` ⇒ 无后端 WARN；4 列 `备注` 写 `C01` ⇒ WARN；5 列正常后端 ⇒ 只按表头解析。
2. **定死 N/A 语义**：早退改 N/A + `Result.status` 加全 N/A 分支 + `stack-profile.md:100` 改口；或删掉“全 N/A ⇒ N/A”。为什么：现稿的整门 N/A 不可达，`atlas_verify`/`--json` 改动没有触发面。验证：空根 `validate_ac_alignment` ⇒ N/A；正常 E2E PASS 含 `[N/A ] manual` 行仍 `ok`；N/A 行进 `_parse_rows`。
3. **修类方法去重与 pytestmark 口径**：去重键改 `(file, line)`；模块/类 `pytestmark` 带 AC 要么支持、要么写明不支持；补 `skipif(False)` 测试。为什么：现键因 name 前缀不同不去重，会重复计数/错误 weak。验证：类方法只入列一次；模块 `pytestmark` 的 skip 使该文件全部 weak；`skipif(False)` 为 weak 且被测试钉住。
4. **让 E2E 零变化可执行**：提交 golden `checks[]`；`test_shared_kernel` 的 `allowed` 加 `parse_dims_cell`；加 monkeypatch 行为钉。为什么：现稿的“逐字节”和 M-Фf 都咬不住本地副本。验证：注入本地副本 ⇒ 行为钉红；还原后 `checks[]` 逐字节一致。
5. **模板不制造假声明**：`templates/prd/domain.md` 后端列占位写 `N/A`/空，不写 `C01, C02` 示例。为什么：占位会被 `parse_dims_cell` 解析成真实声明并触发零测试 WARN。验证：新模板 PRD 无 `dims` 测试 ⇒ 后端门 N/A，不 WARN。

## 建议项

- 把 `tables()`/`split_row` 的表格分块与分隔行口径抽到 `_support`，或至少加与 `validate_e2e_index.tables()` 的 parity 测试；代价是多一个共享件，收益是避免第四份 PRD 表定位实现漂移。
- 给 `backend_test` 增加 `dim_mode: advisory|off`（下一批），让“声明了但暂不查”显式化；代价是 schema 多一个键，收益是减少留空消音。
- `atlas_check` 的 PASS 行也打印通道分布（后端 N/A/无声明/通过），减少“N/A 被当成没问题”；代价是输出更长。
- 同步 `docs/gates/iron-gates.md` 的“四态”标题与 `docs/ecosystem/pi-extensions.md:189` 的“四态”表述，加入 N/A。

## 结构级问题

- **门级 N/A 缺失**：`validate_ac_alignment` 只有 PASS/WARN/FAIL，早退又用 PASS；在决定“早退是 N/A 还是 PASS”之前，`atlas_check`/`atlas_verify` 的 N/A 改动没有稳定的触发面。
- **第四份 PRD 表解析器**：后端门内窄解析与 `validate_prd._table_rows`、`validate_e2e_index.tables()`、`validate_structure.split_row` 并存；不共享就需 parity 测试，否则表头/分隔行口径会漂。
- **Batch A 与 E2E 列的隐式耦合**：疑似扫描必须认识 `适用覆盖维度` 才不会误伤；这不是“只落后端门”能完全隔离的，需在 §10 明写。
- **visitor 双访问**：类方法二次入列是既有结构，新增 weak/dims 若不先归一化记录，计数与去重会继续分叉。

## 附：取证清单

- **读**：v4 全文；`REVIEW-20261026-04`；`validators/validate_ac_alignment.py` 全文；`validators/validate_e2e_index.py`（182-198/210-221/530-663）；`scripts/atlas_check.py`（53-95/108-130/203-233/805-920）；`scripts/atlas_verify.py`（93-105）；`validators/validate_prd.py`（198-235/519-523）；`tests/test_validate_ac_alignment.py`、`tests/test_validators.py`（1290-1350）、`tests/test_shared_kernel.py`（218-256）、`tests/test_canonical_consistency.py`（215-295）、`tests/test_map_anchors.py`（250-270/355-375）；`rings/prd/reference.md` §五、`templates/prd/domain.md:105-111`、`shared/stack-profile.md:100/107`、`shared/gates.md:45/48/65/77`、`docs/gates/iron-gates.md:35-44/97-99`、`docs/map/index.md:37/58/111-112`、`docs/map/atlas-map.html:172/393/527/529`、`README.md:394`、`BACKLOG-execution-layer.md` §8、`DESIGN.md` D151、`RFC-20261026-01` §3。
- **只读探针/命令**：
  - `pytest tests/test_validate_ac_alignment.py tests/test_validators.py::test_e2e_index_coverage_dimensions_pass_and_warn tests/test_shared_kernel.py -q` ⇒ **18 passed**。
  - `/tmp/rev5/probe_extract.py`：抽取 `_parse_dims` 到独立模块并替换调用，7 组语料 `checks[]` 全部一致，55 条，无 root。
  - 早退探针：空根 ⇒ `AC对账门禁运行态 PASS`；4 列 E2E 表 + 普通测试 ⇒ 四行 PASS。
  - visitor 探针：`TestX.test_m` 与 `test_m` 同 `line 7` 双入列；模块 `pytestmark`、`skipif(False)` 均未计 weak。
  - `tables()` 探针：标准 4 列表 `any C-digit cell=True`。
  - `grep -c '^check ' install.sh` = 55；`_support/*.py` = 9；`docs/map/index.md` 9/55/40；`wc -l install.sh` = 719。
- **未修改仓库**；所有夹具在 `/tmp`；工作区 RFC-01 改动未触碰。

---

> **主审复核（2026-10-26，非评审者）**：抽查“标准 4 列 E2E 表会被疑似扫描误判”“早退加 PASS 导致整门 N/A 不可达”“类方法双入列”“`parse_dims_cell` 未在唯一性白名单”四条，均属实。评审结论「修后通过」不变。
