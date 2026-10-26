# REVIEW-20261026-02 · 后端侧覆盖维度 RFC 独立评审

> **对象**：`proposals/RFC-20261026-02-backend-coverage-dimensions.md` **v1**（收窄纯后端方案）。
> **归档注记（2026-10-26 晚）**：v1 已被 v2（跨栈并集）→ **v3（两列两门）** 取代；本评审的 10 条必修在 v3 §7.2 逐条对照。文件名沿用，内容已换。
> **评审者**：tech-proposal-reviewer（只读；引用行号以当前工作区为准）
> **时点**：2026-10-26

## 总判定：需重大调整

方向成立：C01-C14 复用、在既有 `ac` marker 上加 `dims`、共享解析、先 WARN 后 FAIL，都是合理取舍；探针也证实 `dims` 当前确被忽略、`--strict-markers` 下 kwarg 安全。但 v1 的适用范围与排除判据不是条文瑕疵，而是判据骨架错误：`声明了维度但零后端测试` 被判 N/A，而既有 AC 覆盖对账只报总数不指名 AC；`索引主表任意一行` 被当作 E2E 覆盖证明，未实现域、跳过用例、陈旧行、缺索引都会把后端缺口静默掉。再加上单源抽取会新增第 4 份索引解析器、与 `mode: enforce` 的既有契约正面冲突、装配与 docs/map 计数漏项，按现稿实现会产出假绿和契约矛盾。必须先重写 §2.1.4 与 §3，再谈落地。

## 逐问判定

1. **事实核对：通过。** `validate_ac_alignment.py:75-95` 只做 `AC_ID_RE.findall`，`:106-149` 不解析 `dims`，`:282-293` 只报总数；`validate_e2e_index.py:586-653` 的维度门只从 E2E `grid` 取 `覆盖维度`；`apply-wiring.py:219-230` 只注册 `ac`。探针 A/B 复现：带 `dims=["C01"]` 与不带输出逐行一致（四行 PASS），确属完全忽略。`--strict-markers` 夹具实测 `1 passed`。一处措辞需精确：AC 还从 docstring 兜底收集（`:167-173`），不只 marker；不影响结论。行号抽查均命中。

2. **语义复用：有保留。** 没有哪个 ID 的后端语义与前端正面冲突；C07 只是证据形态从埋点换为落库/日志，C02 同理。但「同一套」目前只是字面复用：唯一闭集正文 `rings/e2e/reference.md:178` 仍称「前端裁剪闭集」，§5.5 同；RFC 的 14 行后端映射只存在于提案，`shared/stack-profile.md:98-108` 没有承载它。C06 重试/C10 依赖容错、C09 一致性/C11 幂等在两端也重叠，映射表未给判定边界。应把映射表落到 PRD 环 §五或 `backend_test` 段，并把「前端裁剪」改为「跨栈（前端裁剪起点）」。

3. **v1 范围：否决。** 探针 S4（域 `实现中`）E2E 维度门 `PASS 0 条`，RFC 的排除规则会把该 AC 从后端门排除，后端维度无人对账；S6（E2E 用例 `skipped` 但块内有 C01/C02）E2E 门 `PASS`，排除后同样静默；S1/S2（`prd.md` 只有维度列 / PRD 写 `C99`）E2E 门 N/A。`索引缺失 ⇒ 视作纯后端` 对 `apps[].kind: fullstack` 且 E2E 尚未建的项目是假阳性/假阴性二选一。`索引陈旧 ⇒ WARN 面可见` 也不成立：新门没有为「因索引行而排除」输出任何 WARN；全 N/A 时总览行只显示末行 `PASS`，N/A 原因不可见（`atlas_check.py:209-219`：非 WARN/FAIL 分支只取 `tail` 末行）。全栈 AC 的后端维度 v1 不查可以接受，但「任意主表行 = E2E 已覆盖」不行；这是用旧门的假阳性换新门的静默。`shared/gates.md` 必须写明「索引行存在 ≠ E2E 已覆盖」，不能只写全栈并集。

4. **声明语法：有保留。** 语法本身安全：自定义 marker 接受任意 kwarg，`--strict-markers` 且 `ac` 已注册时实测通过（未注册时是 `ac` 报错，与 dims 无关）。但语义边缘未定义：类级 marker / 模块级 `pytestmark` 当前完全不解析（`:192-197` 只处理类体函数；AST 探针 `pytestmark = pytest.mark.ac("AC-MOD-001")` 未出现在结果）；`parametrize(marks=pytest.mark.skip)`、`skipif`、类级 skip 都不被识别为 skipped（探针 `test_skipif_false` / `test_param_skip` 均 `skipped=False`），会把 dims 记成覆盖；docstring 里的 AC 会被并入 `acs`（探针 `test_doc_other_ac` 得到两个 AC），按「多 AC + dims ⇒ 不记」会误伤合法单 AC 测试。`dims` 为 set / 变量 / 非字符串元素时没有「不支持 ⇒ WARN」的定义，会静默。

5. **单源重构：否决（「零变化」不成立）。** E2E 门没有可原样抽出的「索引 AC 收集」函数：主表解析原语在 `validate_e2e_index.py:69`（`MAIN_COLUMNS`）、`:197-214`（`split_row`/`tables`）、`:356-358` 只有表头等于 `MAIN_COLUMNS` 时才建 `grid`；`e2e_console.py:300-335`、`atlas_verify.py:216-225` 已各有一份索引解析。RFC 的新模块若自带 `| E2E-` 行正则，就是第 4 份解析器，与 single-source 相反。PRD 第 4 列也有两处口径：E2E 只读 `*-prd.md`（`:508`），AC 门读 `prd.md + *-prd.md`（`validate_ac_alignment.py:85-88`）；共享函数若自己 glob，E2E 会从 N/A 变 PASS/WARN（S1）。`:609-615` 是后文件覆盖前文件（S5 实测），`:612` 不校验第 4 列表头（探针：表头写「备注」、单元格 `C01` 仍 PASS），`:614` 的 `if dims:` 会吞掉 `C99`（S2 N/A）。现有 D130 测试只覆盖一个夹具（`tests/test_validators.py:1306-1356`），M131 只证明缺口聚合，不足以证明零变化；需要逐字节差分语料。

6. **判据定义：否决。** ① 「该 AC 至少有一条后端测试」把「声明了维度但零测试」判 N/A（test #10），而既有对账只输出 `已声明 AC: N / 覆盖 M`（`:282-293`），不指名缺哪条；多 AC 项目里这条 AC 可以完全静默。② 「孤儿维度」歧义：§2.1.4 说未知/孤儿 WARN，test #1 又说「无第 4 列但测试带 dims ⇒ N/A/PASS」；实现者无法判断「测试声明了 AC 未声明的维度」算孤儿还是合法附加。③ 未知维度沿用 `_parse_dims` 的 `looks` 启发式（`:595,607`）：`C99/C15` 会 WARN，但 `C1O`、`正常流`、`N/A`、空列表都不会；结构化 `dims=` 应「任何非空但解析不出的项 ⇒ WARN」。另：多 PRD 文件时 `declared_ac_dims` 后写覆盖（S5）；`validate_prd.py:580-597` 的全局唯一只查各域 `domain_code` 前缀的 own AC，不查 `prd.md`，也不禁止跨域引用，不能当作已保证。第 4 列空/`N/A`/中文需明确是 N/A 还是 WARN。

7. **假绿与绕过：有保留。** 已堵：waiver skip 不计（仅装饰器 skip/xfail）、一测多 AC 不计、声明不等于断言（已承认）。未堵：`skipif(True)`、`parametrize(marks=skip)`、类级/模块级 skip 仍被当成活跃测试（探针）；docstring AC 会改变单/多 AC 判定；`scan_backend_tests` 对语法错误文件 `except Exception: continue`（`:216-218`），解析失败 = 测试消失，门可能 N/A；只扫 `test_*.py`（`:206`），`*_test.py` 项目整目录不被看见；E2E 侧 `covered_ac_dims` 不看状态（`:619-627`），`skipped` 用例的 dims 仍可让 E2E 门 PASS（S6），与后端「skip 不计」口径不一致。「跳过测试不记维度」不够，至少要把静态不可判的 skip 形态显式列为盲区。

8. **门禁档位：否决。** `shared/stack-profile.md:107` 写 `enforce（对账缺口硬阻断）`；`docs/gates/iron-gates.md:69` 写「支持 advisory 预警与 enforce 硬阻断」；`docs/guide/legacy-adoption.md:125` 同。RFC 却说 `backend_test.mode: enforce 也不升 FAIL`。这不是措辞分歧：采用者会把 `enforce` 理解为维度缺口也阻断，实际只 WARN。必须改契约：要么把 `mode` 明确限定为「AC 挂载覆盖」，另设 `coverage_dimensions_mode`；要么在 v1 就让 enforce 下维度缺口 FAIL。并把「v1 维度缺口恒 WARN、enforce 不升」写进 `gates.md` 的「不查什么」。

9. **兼容性与改动面：否决。** ① 零影响不成立：RFC 下一行就承认「已声明第 4 列、有后端独占 AC 但没写 dims ⇒ 新增 WARN」（`:144-145`）；且新门没有 `backend_test` 段存在性/`framework: pytest` 门控，`backend_test` 缺失但 PRD 有第 4 列、仓库有 `backend/tests/*.py` 的项目也会新增 WARN，违反「段缺失 = 合法降级」（`shared/stack-profile.md:98`）。② 装配面：`install.sh` 整目录拷贝 `_support` 能带上新文件，但自检是显式清单；不新增 `check` 行，`test_install_selfcheck.py` 不会验证它，RFC 的「pytest test_install_selfcheck 确认被装配」是假的。新增 check 行又会推红 `shared/gates.md:77` 的 54 条、`docs/map/index.md:58/112` 的 54 条与 `install.sh` 行数、`test_canonical_consistency.py:240`、`test_map_anchors.py:263/266`；新增 `_support/ac_coverage.py` 本身就把 `docs/map/index.md:37/53/111` 的「8 件」变成 9。③ `atlas_check.py:84-86` 的 `validate_ac_alignment` 前置是 `product/prd/prd.md`，不是「任一 PRD」；域级 PRD-only 项目会被 SKIP。④ 与 RFC-01 并非「无文件冲突」：RFC-01 §3 同时改 `install.sh`、`shared/stack-profile.md`、`shared/gates.md`、`rings/*`、`README`、`docs/*`、`validate_ac_alignment.py`、`validate_e2e_index.py`，还新增 `_support/layout.py`；`_support` 计数会变 10，install check 计数要合并，D152/M156 也可能撞号。

10. **测试与变异：否决。** 矩阵 10 行，§3 却写「新增 8 条」（`:165`）；#10 的期望是假的（见⑥）；#1 与「孤儿 WARN」冲突；#6 的「N/A 或只算后端独占」没有可断言的唯一结果；#9 的「dims 但无 ac」在 `dims` 只能挂在 `ac` 上的语法里应写成 `@pytest.mark.ac(dims=...)`。缺坏输入：类级/pytestmark/parametrize、skipif、xfail 条件、docstring AC、`*_test.py`、语法错误、`dims=[]`、`dims` 为 set/变量、PRD 第 4 列表头为「备注」、多 PRD 重复 AC、索引缺失/fullstack、未实现域、skipped 用例、`|E2E-` 无空格/前置空格、索引正文提及。M156a「摘 dims 解析 ⇒ 3/4/7 红」对 #7 不成立：摘掉解析后 skipped 测试本来就不贡献 dims，缺口 WARN 仍在，除非 #7 断言「C01 未被计入且由另一条活跃测试覆盖 C02」。M156c 只证明两侧都用了共享函数，不证明没有第二份拷贝；需要 `tests/test_shared_kernel.py` 式的结构唯一性 + 函数对象同一性钉。「逐字节一致」要指定语料与比较口径（`checks[]`，排除 `root`），否则不可执行。

11. **叙事与边界：有保留。** 「应然资产/对账门 ⇄ 执行层」的划界正确，§8 没有承诺生成/执行测试，符合 `BACKLOG-execution-layer.md`；EL-01/EL-02 是上下游，不构成重复。但 EL-02 的完成判据明确写「覆盖维度 C04/C11/C12/C14 可对账」，RFC-02 落地后应回写 EL-02 / §8 指针，否则 backlog 仍把已完成的能力记成缺口。「适配器接口预留」只有一句话，没有函数签名/位置，属于不可验证承诺，建议删掉或写成具体接口。

12. **编号与归档：通过（有保留）。** 当前 `DESIGN.md` 最大 D151、gates 最大 M155，D152/M156 空闲；`RFC-20261026-02` 与评审名 `proposals/REVIEW-20261026-02-backend-coverage-dimensions.md` 符合现有命名（对照 `REVIEW-20261026-01-backfill-write-surface.md`）。但 RFC-01 也在等 D 编号且其 §3 明确要改同一批文件；D152/M156 只能作为占位，落地顺序确定后重排。

## 必修项

1. **重写 v1 适用范围：零测试不是 N/A。** 改：declared dims + backend-exclusive AC 即入范围；无活跃后端测试 ⇒ WARN（指名 AC 与全部维度），或扩展「AC覆盖对账」逐 AC 指名；test #10 改期望。为什么：N/A + 总数比例会把「声明了但没人测」藏掉。验证：两 AC 夹具（一覆盖一零测试）⇒ WARN 指名后者，`atlas_check` 总览可见。

2. **重写排除判据：索引行 ≠ E2E 覆盖。** 改：用 `MAIN_COLUMNS` 主表解析，仅在 AC 属于已实现域、行状态非 blocked/skipped、且 E2E 维度门实际计入时排除；缺失索引且有 `kind: frontend|fullstack` app 或 shards ⇒ N/A/SKIP 带原因，不视作纯后端；排除数量/AC 写进 detail。为什么：S4/S6/S1 会静默。验证：S4/S6 变 WARN；fullstack 无索引 N/A；备注列/无空格行不被误排除。

3. **补单源边界。** 改：把 `split_row`/`tables`/`MAIN_COLUMNS` 一并收进 `_support` 并改三消费者，或明确 v1 只是窄读并删掉「单源」宣称；把 `parse_dims`/`parse_declared_dims`/`parse_index_grid` 加进 `tests/test_shared_kernel.py` 唯一性/别名钉。为什么：否则新增第 4 份索引解析器。验证：本地复制一份解析器 ⇒ 结构钉红；两侧函数对象同一。

4. **补零变化证明。** 改：共享 PRD 列解析显式接收 `*-prd.md` 列表；保留 `if dims:`、`looks`、后写覆盖、已实现域过滤、`total_declared`；新增 old/new `checks[]` 差分语料（prd.md、重复 AC、备注列、C99、skipped、未实现域）。为什么：现有 D130 测试一个夹具不够。验证：同一 root 下 old/new JSON `checks` 逐字节相等；新增字段不出现。

5. **PRD 侧严格化。** 改：校验第 4 列表头 `适用覆盖维度`、限定 §五、AC 文法与声明门一致；非空但解析不出的 token（C99/C1O/中文/N/A）⇒ WARN；空/`N/A`/无列 ⇒ N/A。为什么：备注列 `C01` 现在会 PASS（探针），PRD 写 `C99` 会让整门 N/A。验证：备注列/坏 token 夹具 WARN 或 N/A，不静默 PASS。

6. **修 enforce 契约。** 改：`shared/stack-profile.md:107`、`docs/gates/iron-gates.md:69`、`docs/guide/legacy-adoption.md:125`、`README.md:431` 明确 `mode` 只管 AC 挂载；维度 v1 恒 WARN，或加 `coverage_dimensions_mode`；写进 gates「不查什么」。为什么：三处契约说硬阻断。验证：enforce 夹具维度缺口 ⇒ WARN 不 FAIL；文档不再承诺硬阻断。

7. **加 opt-in/非 pytest 门控。** 改：`backend_test` 缺失或 `framework != pytest` ⇒ N/A（带原因），不新增 WARN；保持 `test_baseline_all_pass`。为什么：「段缺失 = 合法降级」。验证：4 列 PRD + Python 测试 + 无 `backend_test` ⇒ N/A，旧测试不变。

8. **补装配与文档面。** 改：`install.sh` 新增 check 行，`shared/gates.md:77` 54→55，`docs/map/index.md:37/53/111/58/112` 8→9、54→55/行数，`test_canonical_consistency.py`/`test_map_anchors.py` 计数；`scripts/atlas_check.py` 前置若保留 `prd.md` 需在契约写明。为什么：不改则 full suite 红或自检漏件。验证：`install.sh --target /tmp/probe --force` exit 0；`test_install_selfcheck_paths_exist` 含新文件；`test_map_anchors` 绿。

9. **补语法边界。** 改：类级/pytestmark/parametrize/skipif/xfail 条件、docstring AC、unsupported dims 形态，逐项支持或 WARN+盲区；dims 的 AC 必须在 marker 参数内，docstring AC 不参与 dims 归属。为什么：探针显示 skipif/param skip 会计入、docstring AC 会误伤。验证：AST 夹具逐项断言。

10. **修变异。** 改：M156a 的 #7 重设计；新增「skipped dims 被计入 ⇒ #7 红」「多 AC dims 被计入 ⇒ #5 红」「索引排除被删 ⇒ #6 红」；M156c 加结构钉。为什么：现 M156a 不一定咬。验证：四段协议、注入 diff、还原 sha256。

## 建议项

1. 把 `rings/e2e/reference.md` 的「前端裁剪」改为「跨栈（前端裁剪起点）」，映射表落到 canonical，不只留在 RFC。
2. `shared/gates.md` §3 增加「AC × 维度（后端）」平面行；E2E 行「不查什么」加「后端维度（v1 不含）」；回写 `BACKLOG-execution-layer.md` EL-02/§8。
3. 增加 `coverage_dimensions` opt-in / union 下一批；v1 明确全栈盲区的出路（删维度还是等 union），避免用户为消 WARN 造假用例。
4. 测试补 string/tuple/`dims=[]`/变量/`*_test.py`/语法错误；`dims` 非字面量统一 WARN。
5. RFC-01 协调：D152/M156 用占位，install/docs 计数合并，删除「无文件冲突」。

## 结构级问题

- **骨架问题（单源边界）**：RFC 把「索引 AC 收集」当作可从 E2E 门原样抽出的函数，但 E2E 门没有这个函数；表解析原语仍在 `validate_e2e_index.py`，且 console/atlas_verify 已有各自解析。按现稿会新增第 4 份索引解析器，与 single-source 目标相反。要么扩大重构（把索引表解析也收进 `_support` 并改三处消费者），要么降格宣称 v1 只是窄读。
- **条文问题（可修但必须重写）**：v1 排除判据、零测试 N/A、enforce 冲突、装配/docs 计数与 opt-in 门控。这些不是措辞，是判据与改动面。
- **并行 RFC**：RFC-01 与本提案在 `install.sh`、`shared/stack-profile.md`、`shared/gates.md`、`rings/*`、`README`、`docs/*`、两个校验器、`DESIGN.md` 上重叠，且 `_support`/install check 计数与 D152/M156 编号需合并排序；「无文件冲突」不成立。

## 附：取证清单

- 读：RFC 全文；`REVIEW-20261026-01`；`validators/validate_ac_alignment.py`、`validate_e2e_index.py`（335-358/508-653）、`validate_prd.py`（580-597）；`tests/test_validate_ac_alignment.py`、`tests/test_validators.py`（1306-1356）；`rings/prd/reference.md` §五、`rings/e2e/reference.md` §5.1/5.2/5.5/8.2；`shared/gates.md`、`shared/stack-profile.md`、`apply-wiring.py`；`install.sh`、`package.json`、`docs/map/index.md`、`tests/test_install_selfcheck.py`、`tests/test_canonical_consistency.py`、`tests/test_map_anchors.py`；`DESIGN.md` D130/D131/D151；`RFC-20261026-01` §3。
- 探针：`/tmp/atlas-dim-probe.iMnGQo` 复现 A/B（四行 PASS，`dims` 完全忽略）；`/tmp/atlas_dim_ast_probe.py`（`pytestmark` 未收、`skipif`/param skip 未识别、docstring AC 并入、类方法重复计数、坏文件静默）；`/tmp/atlas_dim_e2e_probe.py` S1-S6（`prd.md`/C99 N/A、skipped dims 计入且可 PASS、未实现域 PASS 0、重复 AC 后写覆盖）；`/tmp/atlas_dim_header_probe.py`（第 4 列「备注」写 C01 仍 PASS）；`pytest --strict-markers` 夹具（`1 passed`）。
- 未修改仓库；所有夹具在 `/tmp`。`git status` 仅显示任务开始前已存在的 `proposals/README.md` 修改与新增提案文件。

---

> **主审复核（2026-10-26，非评审者）**：抽查了 `install.sh` 自检清单、`docs/map/index.md` 的 8 件/54 条、`validate_ac_alignment` 前置只认 `product/prd/prd.md`、RFC-01 §3 改动面重叠，均属实。仅将「全 N/A 的门行不显示」修正为「总览只显示末行 `PASS`、N/A 原因不可见」——门行本身仍在，结论不变。
