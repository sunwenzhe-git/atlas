# REVIEW-20261026-04 · 跨栈覆盖维度 RFC v3 独立评审

> **对象**：`proposals/RFC-20261026-02-backend-coverage-dimensions.md` v3
> **归档注记（2026-10-26 晚）**：v3 已按本评审收口为 **v4 / Batch A**（只落后端门；E2E 表头/weak 两处小修移交 Batch B 另立 RFC）。本评审的 11 条必修在 v4 §7.1 逐条对照。
> **评审者**：tech-proposal-reviewer（只读；行号以当前工作区为准，HEAD 漂移单独标注）
> **时点**：2026-10-26
> **基线**：`HEAD 7112155` + 并行 RFC-01 在飞（工作区 `_support` 已含未跟踪 `layout.py`，实为 9 件；`install.sh` 仍 54 条；`docs/map` 已写 9 件/40 测试文件）。v3 证据表混用 HEAD 行号，见第 1 问。

## 总判定：需重大调整（两列/两门骨架保留）

方向成立：D130 不退役、索引解析不动、后端门只 WARN、两列各查各的，都是正确取舍；两列两门比 v2 并集更能表达通道义务。但 v3 仍有四条实现级 blocker：**N/A 的行级语义会误伤正常 E2E 门**、**后端门没有“未实现域”分档**、**多 app 规则在现有 schema 下不可判定**、**备注列/错位表头从“PASS”变成“不可见的 N/A”而不是 WARN**。这些不是措辞问题；按现稿落刀会产出新的假 N/A 与假绿，必须先重写 §2.1.4、§2.1.10、§2.1.13 与 §4，再谈实现。

## 逐问判定

1. **事实核对：有保留。** 探针 A/B 属实：`/tmp/rev4-probe.Gzq7Ts` 四行全 PASS，`dims=` 确被忽略；`README.md:430` 命中；`templates/prd/global.md` 无 AC 表；`validate_prd.py:42` 是 `\d+`、`validate_e2e_index.py:81` 是 `\d{3}`；`apply-wiring.py:219` 只注册 `ac`。但 v3 的行号是 HEAD 基线：`validate_ac_alignment.py` 的 75/106/288 在工作区是 77/109/290；`validate_e2e_index.py:586` 在工作区是 596。更实质的两处事实错误：① v3 §1.1 称第 4 列是“全局可声明”，但 `rings/prd/reference.md:195`、`templates/prd/domain.md:111` 一直写“由 E2E 环门对账”，第 4 列从来不是全局；② v3 §2.1.10 说 E2E 门全 N/A 已可见，实测 `atlas_check` 对空根输出 `ok validate_e2e_index N/A`，只有 detail 是末行，N/A 原因并不可见（`/tmp/rev4-check.H5lsWG`）。

2. **两列模型：通过（有保留）。** 把第 4 列正名为 E2E、新增第 5 列，语义上成立；D130 本来就只被 E2E 门消费，所以这是措辞澄清而非语义迁移。但存量全栈项目若曾把后端维度写在第 4 列，新模型下后端门直接 N/A，RFC 需要迁移说明，不能只写“零影响”。重复维护是真实成本：同一维度两端都要各写一次，且两列之间没有任何交叉核对；单列 `C01@e2e` 语法更省单元格但迁移面更大，v3 否掉可以接受。第 5 列落地还需同步 `README.md:386-389`（公开的“AC × 覆盖维度矩阵”仍只写第 4 列）、`docs/gates/iron-gates.md:97-99`、`rings/e2e/reference.md:164`，v3 §3 均未列。

3. **后端门判据：否决。** 三个洞：① **N/A 聚合粒度错误**——v3 写“表有 <5 列 ⇒ 后端门 N/A”。多域项目中只要有一个域还是 4 列旧表，整门就 N/A，另一个域的第 5 列声明被静默吞掉；必须逐文件/逐表跳过，只有“全项目没有任何合法第 5 列”才整门 N/A。② **错位表头静默**——4 列表把表头写成“后端适用覆盖维度”、或 5 列表第 5 列是“备注”但单元格写 `C01`，v3 一律 N/A 不 WARN；这恰是 REVIEW-20261026-03 必修 4 要求“含维度形态 ⇒ WARN”的反面。③ **多 app 规则不可实现**——`validate_stack_profile.py:76` 的 `BACKEND_TEST_KEYS` 只有全局 `test_dir`，schema 没有 per-app 测试目录，“多个 backend/fullstack 且各自独立测试目录”无法判定，测试 #14 也无法构造。另：零测试 WARN 没有“未实现域”分档，`validate_e2e_index.py:638-640` 的 `dom_status == 已实现` 过滤在后端门完全缺失；PRD 先于实现，未来 AC 会永久 WARN。“留空即无义务”是合法 opt-out，但文档必须写明它是“未声明”而非“豁免”，否则“后端可测但没写”会被藏成无义务。

4. **通道适用性：有保留。** `apps` 缺失、`mobile`、`backend_test` 缺失/非 pytest/`test_dir` 缺失 ⇒ N/A，边界基本清楚；E2E 门不被吞掉也成立。但 `apps` 缺失时后端门 N/A 会掩盖“有后端测试但 profile 坏了”的项目；同一 `validate_ac_alignment` 的既有四判据仍按缺省 `backend/tests` 扫描（`validate_ac_alignment.py:237`），会出现“一行说不可用、另一行仍在扫”的双答案。`*_test.py` 项目更糟：扫描面为空 ⇒ 每条声明 AC 零测试 WARN，是满屏假红；必须区分“扫描面不支持”与“真零测试”，或直接 N/A 并点名扫描面。

5. **E2E 两处小修：有保留（偏否决）。** 表头校验有现成 `tables()`（`validate_e2e_index.py:210`），不必新写解析器；现有 D130 夹具表头正确，M131 不受影响，`## 5.` 若按表扫描也能工作（若改用 `validate_prd.section_of` 的 `## 五、` 正则则会静默失败，v3 未指定）。但“任一无表头文件 ⇒ `declared_ac_dims = {}` + N/A”会用一个坏文件擦掉好文件的声明，必须逐表处理。weak-only 方向正确，`prototype-pass` 是 E0 历史态（`rings/e2e/reference.md:170`），存量 adopt 项目若只有 prototype-pass 覆盖，会新增一片 WARN；这属于真实弱证据，但发布说明要写。M131 仍能咬缺口聚合，前提是变异同时覆盖新增的 weak 聚合。

6. **N/A 可见性：否决（现稿）。** 现实现 `atlas_check.py:217-233` 对 code 0 且无 WARN 只取末行作 detail；`validate_e2e_index` 正常 PASS 轮本来就有一个 `[N/A ] manual 走查项形态`（探针 `/tmp/rev4-e2e.e8c6U6` 第 56 行），`atlas_check` 仍显示 `ok … PASS`。v3 写“存在 `[N/A]` 行 ⇒ 行状态 N/A”有两个问题：① 正常 E2E 轮会被误标 N/A；② 实际输出是 `[N/A ]`（`f"[{status:<4}]"` 补空格），朴素搜 `[N/A]` 根本匹配不到。正确做法是：行状态保持 ok/WARN/FAIL，detail 收集 `[N/A ]` 子项；只有末行就是 `N/A`（整门不适用）才记 N/A。另需同步 `scripts/atlas_verify.py:100-106` 的 `_parse_rows` 白名单（否则 N/A 行在执行器留档中消失）与 `docs/gates/iron-gates.md:35-44` 的四态表；`Row.failed` 只认 FAIL，退出码仍 0 这一点没问题。

7. **单源与零变化：有保留。** 只抽 `parse_dims_cell`/`parse_dim_token`/`parse_dims_list`、不碰索引解析，边界正确；`_parse_dims` 闭包、`declared_ac_dims`、`bad_case_dims`、`total_declared` 的现有实现（`validate_e2e_index.py:607/619/627/628/660`）可保留，改调用共享函数后行为应一致。但 `tests/test_shared_kernel.py:219-241` 的唯一性守卫只匹配顶层 `^def <name>(`，换名复制或嵌套复制不会红；函数对象钉只能证明“别名指向同一对象”，证明不了“实际调用的不是本地副本”。M159 只咬同名复制，咬不住“保留别名、实际走本地 `_parse_dims`”的写法。隐藏的第二份解析器（`validate_structure.split_row:72`、`atlas_verify` 窄解析、`parse_block`/`strip_inline_comment` 别名）v3 未碰，正确；但新增的 PRD 第 5 列表解析是第三份 PRD 表定位实现，应至少复用 `tables()`/`table_with_all_cols` 的定位口径。

8. **豁免语义：有保留。** “`不可验`/`结构类` 只豁免 E2E、后端列照查”方向正确；但这两个清单今天并不豁免 E2E 维度门（只豁免“AC 反向覆盖”，`validate_e2e_index.py:559-573`），所以“只豁免 E2E 列”表述会让人误以为维度门已减清单。后端列照查是对的。“第 5 列留空 = 无义务”是必要条件，但需要一句反滥用：不得用留空把“后端可测但没写”洗成无义务；是否需要后端专用豁免清单，v3 §5 仍留开放，至少应在 `gates.md` 写明“留空 = 未声明，不是豁免”。

9. **评审吸收：否决（部分）。** §7.1 的“多 app 未建模”是假吸收（规则不可实现）；“整门 N/A 吞零证据”只解决了通道分离，没解决未实现域；“3 列/备注列误伤”把 REVIEW-03 要求的 WARN 改成了静默 N/A；“`Result` N/A 态”引出了上面的行级误判。§7.2 的零测试 WARN、索引行不等于覆盖、单源边界、enforce 四处、opt-in 三重门是真吸收；但零变化没有可执行 harness，装配计数漏了测试条数，语法边界漏了类/模块 `pytestmark` 与 docstring-only 零测试，M159 咬不住换名/嵌套复制。M156a-e、M157、M158 的设计基本能咬；M156e 的 #14 夹具在 schema 下不存在。

10. **RFC-01 协调：有保留。** RFC-01 §3 确实覆盖 `install.sh`、`shared/*`、`rings/*`、`docs/*`、`_support/layout.py`、validators、`atlas_check` 前置；v3 的 9→10 / 55→56 在 RFC-01 落地后正确，但“未落地 8→9 / 54→55”与它自己声明的基线（工作区已 9/54）矛盾。v3 未列 `README.md:386-389`、`docs/gates/iron-gates.md:35-44/97-99`、`rings/e2e/reference.md:164`、`scripts/atlas_verify.py`、`tests/test_validators.py` 的 146 条与 `tests/test_atlas_check.py` 的 42 条（`shared/gates.md:45/65`，`test_canonical_consistency.py:231-266` 会对账）、`BACKLOG-execution-layer.md` §8。D152/M156 在 HEAD 空闲（D151/M155 为最大），但 RFC-01 已 Accepted 且在飞，v3 只给 D 留了“顺延”，M156a-e/M157-159 没有占位说明；两者都可能撞号。

11. **测试与变异：否决（不足）。** 16+7 覆盖主干，但缺：4 列表头写成“后端适用覆盖维度”、维度在第 6 列、多 PRD 混合 4/5 列、同 AC 重复行、第 5 列 `N/A`/`—`/`-`、第 5 列区间/中文邻接、`dims` 字符串/元组/逗号串、类级/模块级 `pytestmark` 带 AC、docstring-only 的零测试、类方法二次访问、`skipif(False)`、`*_test.py`、未实现域、`mode: enforce` 下缺维度必须 WARN 而不是 FAIL、`atlas_check --json` 的 N/A 行、`atlas_verify` 对 N/A 行的处理、`## 5.` 标题、`prototype-pass` weak。§4.4 的“逐字节一致”没有可执行 harness（语料、比较口径、golden 文件都没定）；M159 需要行为钉（monkeypatch 共享函数后 E2E 输出必须变，或调用计数），不能只做对象同一性。

12. **叙事与边界：有保留。** §8 的“应然资产/对账门 ⇄ 执行层”划界正确，不重复 EL-01/EL-02；但 §8 说要回写 EL-02 指针，§3 却没列 `proposals/BACKLOG-execution-layer.md`。“跨栈”是过度承诺：后端仅 Python/pytest、E2E 仅 node-playwright、单 `test_dir`、无 app 归属、`*_test.py` 不扫、mobile 不参与；应把“Python/pytest + 单 app”写进标题下的边界句。另“零影响/零变化/不产生 FAIL”要分开说：后端门不产生 FAIL 为真；零影响在可见面上不为真（新增 N/A 子项与行状态变化）；零变化未被证明。

13. **编号与归档：有保留。** 评审报告应命名 `proposals/REVIEW-20261026-04-backend-coverage-dimensions.md`（01=backfill，02=RFC-02 v1，03=RFC-02 v2）。D152/M156 在 HEAD 空闲，但 RFC-01 可能先占；v3 的“建议 D152”应改为显式占位（D-Ф/M-Ф），落地时按 RFC-01 实际占用重排。

14. **是否还有更简单的解：有。** 两列两门骨架成立，不必推翻；最简单的减法是**把 E2E 表头校验与 weak-only 拆成独立小批/RFC**，后端门独立落，避免 E2E 门的任何回归拖住后端能力。列定位建议按表头名而不是硬编码“第 5 列”，既支持 6 列备注，也能把“后端表头写在第 4 列”判成 WARN 而不是静默 N/A。若作者只把上述 blocker 换成措辞、不重写判据与测试，应退回“需重大调整”。

## 必修项

1. **重写 N/A 表示。** 改：`atlas_check` 行状态保持 ok/WARN/FAIL，detail 收集 `[N/A ]` 子项；只有整门末行 N/A 才记 N/A；匹配 padded 格式。为什么：正常 E2E PASS 轮含 N/A 子项，现规则会误标 N/A；`[N/A]` 字符串匹配不到。验证：正常 E2E 夹具行仍 ok/PASS 且 detail 含 N/A；全 N/A 夹具行 N/A；`--json` 含 N/A；`atlas_verify._parse_rows` 不丢 N/A。
2. **给后端门加“未实现域”分档。** 改：读域实现状态（可显式允许读 e2e-index 页面表，或新增 profile 键），只有已实现域零测试才 WARN；未实现域 N/A/明细。为什么：PRD 先于实现，否则未来 AC 永久 WARN。验证：`实现中`/`未开始` 夹具不逐条 WARN；已实现域零测试 WARN。
3. **修多 app 规则。** 改：删“各自独立测试目录”这一不可判定条件，明写“`apps[]` 中 backend/fullstack 数量 > 1 ⇒ 后端门 N/A（未建模）”，或给 schema 加 per-app `test_dir`。为什么：现有 `BACKEND_TEST_KEYS` 只有全局 `test_dir`，测试 #14 无法构造。验证：双 backend app 夹具 N/A + 原因。
4. **逐表/逐文件聚合，禁止全局擦除。** 改：一个 4 列 PRD 或一个错表头文件只跳过自身；只有全项目无合法表才整门 N/A。为什么：多域项目会被一个旧文件吞掉全部第 5 列声明。验证：一个 4 列 + 一个 5 列 PRD，后者仍被查；一个错表头 + 一个正确表头，后者仍生效。
5. **错位/备注列不再静默。** 改：4 列表头为“后端适用覆盖维度”、5 列表头为“备注”但单元格含维度形态 ⇒ WARN“疑似维度列但表头/列位不符”；无维度形态才 N/A。为什么：REVIEW-03 必修 4 明确要求；否则“备注列写 C01”从 PASS 变成不可见 N/A，仍是假绿。验证：两个夹具均 WARN，且 `atlas_check` 行可见。
6. **补齐 active/weak 的 AST 与测试。** 改：`skipif`、`parametrize(marks=...)`、类级/模块级 `pytestmark`、docstring AC 分离、零测试只看 marker AC、类方法二次访问去重。为什么：现 visitor 只认 skip/xfail，v3 的 weak 定义实现不了。验证：逐项 AST 夹具；docstring AC 不计 dims、不计零测试。
7. **`*_test.py`/语法错误/无 `test_*.py` 不要满屏零测试 WARN。** 改：扫描面无 pytest 文件时 N/A 或一条 WARN 点名扫描面；语法错误单独 WARN 并点名文件。为什么：否则非 pytest 命名项目每条 AC 假红。验证：`*_test.py` 夹具只出一条扫描面 WARN。
8. **补 enforce 测试与文档。** 改：`mode: enforce` 下第 5 列有声明但缺维度 ⇒ 维度 WARN（AC 零挂载的既有 FAIL 不变）；四处文档同步。为什么：v3 的“只 WARN”在 enforce 零挂载时会被既有 FAIL 覆盖，需写明。验证：enforce 夹具维度缺口是 WARN，不是 FAIL。
9. **补零变化 harness 与 M159 行为钉。** 改：well-formed 语料 + golden `checks[]` JSON（排除 `root`）逐字节比较；M159 用 monkeypatch/调用计数证明 E2E 实际走共享函数，而非只查别名。为什么：现 M159 咬不住换名/嵌套复制。验证：注入本地副本 ⇒ 行为钉红；还原逐字节一致。
10. **补文档与计数面。** 改：`README.md:386-389`、`docs/gates/iron-gates.md:35-44/97-99`、`rings/e2e/reference.md:164`、`shared/gates.md:45/65`（146→153、42→43+）、`docs/map/index.md:58/112`（580→581、54→56）、`docs/map/atlas-map.html:172/501`（9→10、146→行数）、`scripts/atlas_verify.py`、`BACKLOG-execution-layer.md` §8。为什么：这些都会被 `test_canonical_consistency`/`test_map_anchors` 或公开文档契约咬住。验证：对应测试绿。
11. **D/M 编号占位。** 改：D152→D-Ф、M156a-e/M157-159→M-Ф，落地时按 RFC-01 实际占用重排。为什么：RFC-01 在飞且未登记编号。验证：DESIGN/gates 登记与实际一致。

## 建议项

1. **拆分 E2E 小修**：表头校验与 weak-only 独立成批，后端门先落；代价是多一次评审，收益是 E2E 回归不拖后端。
2. **列按表头名定位**：支持 6 列表与“后端列写在第 4 列”的 WARN；代价是解析稍复杂，收益是减少静默 N/A。
3. **迁移说明**：全栈项目第 4 列不再代表后端，补第 5 列；可给一次性 WARN“有 backend app 且第 5 列未声明，后端维度不查”，但会带来噪声。
4. **后端专用豁免清单**：若真实项目出现“后端也不可验”的 AC，v1 的“留空”会丢失声明；可留到下一批，但文档先写“留空=未声明”。
5. **PASS 行也打印通道分布**：不只打印缺口，减少“后端门 N/A 被当成没问题”。
6. **状态词表文档 sweep**：`docs/ecosystem/pi-extensions.md:189` 的“四态”需加 N/A 或注明内部子态。

## 结构级问题

- **骨架问题（N/A 表示）**：`atlas_check` 只有行级状态，没有子项状态；把“某子项 N/A”提升为“整门 N/A”会把正常 PASS 误标，把“不提升”又会让 N/A 不可见。必须先定“子项 N/A 只进 detail、整门不适用才升行状态”，否则 v3 的表头修复与后端门 N/A 都不可见。
- **边界问题（后端门范围 vs 跨环数据）**：后端门声称“不读 E2E 索引/分片”，但要区分“未实现域”与“已实现零测试”就必须有实现状态；这是骨架级取舍，必须在 RFC 里二选一并写明。
- **数据模型问题（多 app）**：`backend_test` 只有全局 `test_dir`，AC/用例/测试没有 app 归属；v3 的“多 app 未建模”规则无法实现，属数据模型缺口，不是条文。

## 附：取证清单

- **读**：v3 全文；`REVIEW-20261026-02/03/01`；`validators/validate_ac_alignment.py` 全文；`validators/validate_e2e_index.py`（69/190-225/306-322/340-370/490-520/530-680）；`scripts/atlas_check.py`（60-130/180-235/780-924）；`scripts/atlas_verify.py`（90-135/240-275/325-355/405-430）；`validators/validate_prd.py`（42/198-231/260-263/580-625）；`validators/validate_stack_profile.py`（38/76/120-150/301-317）；`_support/layout.py`、`_support/siblings.py`；`tests/test_validate_ac_alignment.py`、`tests/test_validators.py`（1306-1356）、`tests/test_shared_kernel.py`（200-290）、`tests/test_atlas_check.py`、`tests/test_canonical_consistency.py`（220-291）、`tests/test_map_anchors.py`（200-385）；`shared/gates.md`（41-77/107）、`shared/stack-profile.md`（32-45/98-108）、`shared/layout.md`；`rings/prd/reference.md` §五、`rings/e2e/reference.md`（164/170/178/320-322/591）；`templates/prd/domain.md`、`templates/prd/global.md`、`templates/e2e/case-shard.md`、`templates/stack-profile.yaml`；`README.md`（386-389/430）、`docs/gates/iron-gates.md`（35-44/68-69/97-99）、`docs/guide/legacy-adoption.md`（118-141）、`docs/map/index.md`（37/53/58/107-112）、`docs/map/gates.md`（50-60）、`docs/map/atlas-map.html`（172/249/501）、`docs/ecosystem/pi-extensions.md:189`；`DESIGN.md` D130/D151、`RFC-20261026-01` §3、`BACKLOG-execution-layer.md` §8。
- **只读探针/命令**：
  - `/tmp/rev4-probe.Gzq7Ts`：5 列 PRD + `dims=["C01"]` ⇒ 四行全 PASS，exit 0（复现 v3 探针 A）。
  - `/tmp/rev4-e2e.e8c6U6`：第 4 列表头“备注”、单元格 `C01` ⇒ `[PASS] AC × 覆盖维度`，整体 PASS；正确表头同样 PASS。正常夹具第 56 行有 `[N/A ] manual 走查项形态`，但 `atlas_check --fast` 仍 `ok validate_e2e_index PASS`。
  - `/tmp/rev4-check.H5lsWG`：空 `.atlas` 根 ⇒ `ok validate_e2e_index N/A`，exit 0（N/A 原因不可见）。
  - `python3 -m pytest tests/test_validate_ac_alignment.py tests/test_validators.py::test_e2e_index_coverage_dimensions_pass_and_warn tests/test_shared_kernel.py -q` ⇒ 18 passed。
  - `grep -c '^check ' install.sh` = 54；`_support/*.py` = 9（含未跟踪 `layout.py`）；`docs/map/index.md` 已 9 件/40 测试文件；`shared/gates.md` 146 行；`DESIGN.md` 最大 D151；`shared/gates.md` 最大 M155。
- **未修改仓库**；所有夹具在 `/tmp`；工作区已有的 RFC-01 改动未被触碰。

---

> **主审复核（2026-10-26，非评审者）**：抽查 `README.md:386-390`（AC × 覆盖维度矩阵仍只写第 4 列）、`docs/gates/iron-gates.md:35-44`（行级只有 ok/WARN/SKIP/FAIL，无 N/A）与 `:97-99`、`docs/ecosystem/pi-extensions.md:189`（四态）、`BACKEND_TEST_KEYS` 只有全局 `test_dir`、PRD 域 `status: draft` 是文档状态（模板明写「不挂实现状态」）、E2E 域状态过滤在 `validate_e2e_index.py:638-640`，均属实。行号漂移（工作区 77/109/290、596）已确认。评审结论不变。
