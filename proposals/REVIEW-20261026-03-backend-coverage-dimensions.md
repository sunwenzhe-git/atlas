# REVIEW-20261026-03 · 跨栈覆盖维度 RFC v2 独立评审

> **对象**：`proposals/RFC-20261026-02-backend-coverage-dimensions.md` v2
> **归档注记（2026-10-26 晚）**：v2 已被同一路径的 **v3（E2E 第 4 列 + 后端第 5 列，两列两门）** 取代；本评审的结构级问题在 v3 §7.1 逐条吸收。
> **评审者**：tech-proposal-reviewer（只读；引用行号以当前工作区为准）
> **时点**：2026-10-26
> **基线**：`HEAD 7112155` + 并行 `RFC-20261026-01`（Accepted，工作区已落 `_support/layout.py`、validators/docs 改动；`install.sh` 尚未落）

## 总判定：需重大调整

方向成立：把对账单位从 E2E 用例提升到 AC、复用 C01-C14、单源解析、先 WARN 后 FAIL，都比 v1 正确。但结果模型仍是骨架错误：**项目级 N/A + 通道集合并集**无法表达「哪个适用通道必须覆盖哪些维度」，零证据与单通道结论会被整门 N/A 吞掉；`validate_ac_alignment.Result` 甚至没有 N/A 态，新门的 N/A 在 `atlas_check` 里会显示成 `ok`。同时「三处零变化」已被探针证伪，装配计数与在飞的 RFC-01 正面冲突。按现稿实现会产出新的假绿/假 N/A，必须先重写 §2.1.1–2.1.2 与 §4.3，再谈落地。

## 逐问判定

**1. 事实核对：有保留。** 探针 A/B 属实：`dims=` 当前被完全忽略（`validate_ac_alignment.py:106-149` 只读位置参数），四行 PASS。但三处漂移：`README.md:431` 实际在 430；`validate_ac_alignment.py:282` 的覆盖统计实际在 288；工作区 `docs/map/index.md:37/53/111` 已是「9 件」、测试文件 40（并行 RFC-01 已落 `_support/layout.py`），v2 的「8→10」在评审时已过期。全局 `templates/prd/global.md` 没有 AC 表（§五 是功能架构），所以「global/domain 正常双写被误判重复」不成立；跨文件重复 AC WARN 基本是空转，真正的重复早已被 `validate_prd` 判红。

**2. v1 十条必修：部分吸收。** 实质解决：2（索引行不再等于覆盖，改为分片 `覆盖维度`）、6（`mode` 只管挂载，维度恒 WARN）。部分解决：1（零证据 WARN 只在「全部适用通道可用」时生效，被 N/A 吞掉）、3/4（单源与零变化声称不成立，见 6）、5（漏 AC 文法）、7（后端门控与同一校验器既有扫描口径打架）、8（计数错、漏 `docs/map/atlas-map.html`）、9（skipif/param/类级 pytestmark 只「点名」不改变 PASS，见 9）、10（M156f 咬不住换名复制）。「M131 迁到 AC 门」是概念错误：M131 是变异编号，不是测试；应退役或重靶，不能「迁移」。

**3. AC 层并集：否决（有反例）。** 全栈 AC 声明 C01,C02，E2E 用例存在但分片没写 `覆盖维度`，后端 `dims=["C01","C02"]` ⇒ 并集完整、门 PASS，UI 证据缺口被吞（RFC §2.1.2 只对缺口做归因，PASS 不报通道分布）。多 frontend/多 backend 更糟：AC 是项目级、索引无 app 列、`backend_test` 只有一个 `test_dir`，E2E 只覆盖 A app 也会被当成全项目覆盖。`结构类`/`不可验` 两类一律跳过也过宽：「不可验」的定义是「当前 UI 无观测面」（`rings/prd/reference.md` 不可验清单节），纯性能/服务端时序恰是后端可测的，跳过等于给后端开后门。

**4. 通道适用性：否决。** 全栈项目无 `backend_test` 时，今天 E2E 维度门还能对 E2E 侧报 WARN；v2 改成整门 N/A，是功能回退。零证据 WARN 同样被 N/A 吞掉——这正是 v1 必修 1 的原病灶换了个位置。且 `validate_ac_alignment` 的既有「AC覆盖对账」在无 `backend_test` 时仍会按缺省 `backend/tests` 扫描（`:229`），同一校验器两行对「后端是否可用」给出不同答案。应改为「逐 AC 计算已知部分 + 整门标注不完整」，而不是整条 N/A。

**5. E2E 维度门退役：有保留（偏否决）。** 删除 check 行会改变 `validate_e2e_index` 的 `checks[]`；对全栈无 `backend_test` 的项目，原来的 WARN 会彻底消失且无人察觉。`test_e2e_index_coverage_dimensions_pass_and_warn` 改成「已退役」形态钉是必要的，但它是弱钉：只能证明名字不在，不能证明 AC 门接手了 N/A/WARN/PASS/未知四态；v2 的 21 条矩阵没有复刻 D130 的 `C01-C02` 区间展开与 `C01正常流` 中文邻接，M156a 也就咬不到这两条解析边界。

**6. 单源收口：否决（「零变化」已证伪）。** 探针：`|E2E-HOME-001|...`（无空格）行，`validate_e2e_index.tables/split_row` 能解析，`atlas_verify._index_case_ids` 返回空集、`_index_state_of` 返回 None（它要求 `"| E2E-"`，且状态写死 `cells[6]`）。所以「收口三处 + 逐字节一致」不可能同时成立：要么改 `atlas_verify` 的行为，要么保留两套入口。另有三处硬点：① `validate_structure.py:72` 已有同名 `split_row`，把 `split_row` 加进 `tests/test_shared_kernel.py:218` 的唯一性白名单会立刻红，必须改名或把守卫限定在索引消费者；② 删除 `parse_block`/`strip_inline_comment` 的模块级别名会打红 `test_consumer_aliases_are_the_kernel_objects`（`:244`），v2 未列；③ `load_module` 与 `from _support...` 混用会产生两个模块对象，函数对象钉失效；④ E2E 校验器仍自读 `UNVER_LIST_HEAD`/`STRUCT_LIST_HEAD`（`:84/88/559/672`），`parse_prd_assets` 若只服务 AC 门就是第二份 PRD 清单解析器。

**7. 严格 PRD 解析：否决（会误判真实形态）。** 现有 `tests/test_validate_ac_alignment.py:44-50` 的夹具是 3 列表；合法项目也允许 3 列（`validate_prd` 只要求含 `AC ID`+`回指规则`）。v2 §2.1.6 写「第 4 列必须叫 适用覆盖维度，否则 WARN」，与测试 #11「无第 4 列 ⇒ N/A」自相矛盾；按前句实现，全部存量 3 列 AC 测试转 WARN、`test_baseline_all_pass` 直接红。第二个真实形态：4 列但第 4 列是「备注」（合法，`validate_prd` 不禁止），备注里写 `P0` 也会被 WARN「不是适用覆盖维度」——项目根本没启用维度却新增噪声。第三：只认 `## 五、验收标准`，`## 5. 验收标准` / `## 五 验收标准` 会静默 N/A，比旧门更窄。第四：AC 文法不统一，`validate_prd.py:42` 与 `validate_ac_alignment.py:39` 是 `\d+`，`validate_e2e_index.py:81` 是 `\d{3}`；v2 未指定用哪套。

**8. 后端语法边界：有保留。** 结构化 `dims=` 与 PRD 散文共用 `parse_dims` 会把 `dims=["C01C02"]`、`dims=["C01正常流"]` 解析成合法维度；结构化输入应逐元素精确匹配 `^C(0[1-9]|1[0-4])$`，否则「未知词 WARN」被宽松解析绕过。`PyTestACVisitor.visit_ClassDef` 会对类方法二次访问（`:192-197` + `generic_visit`），新逻辑若按测试条目计数会重复。类级/模块级 `pytestmark` 只处理 skip 不处理 AC 挂载，v2 的「uncertain 计入」需要新增 AST 分支而不是既有 visitor 的开关。`*_test.py` 与语法错误已明写，可接受，但 `*_test.py` 项目会得到满屏「缺维度」WARN，detail 必须点名扫描面。

**9. 设计覆盖 vs 执行证据：必须改。** 允许 skipped/uncertain 计入本身可以作为「设计层门」，但当前 `atlas_check.py:193-217` 对 PASS 行只显示末行 `PASS`，WARN/FAIL 才展开 detail；因此「计入但 detail 点名」在唯一用户可见面上不可见，等于 PASS。E2E 的 `blocked`/`red` 也未点名，v2 只写了 `skipped`。判定：**可接受为设计层门，但必须让「仅由 skipped/uncertain 满足」的 AC 产出 WARN 行**（或让该行状态变 WARN），并在 `shared/gates.md` 的盲区里写「声明覆盖 ≠ 执行覆盖」。

**10. 前置与装配：有保留（部分否决）。** 把前置从 `product/prd/prd.md` 改为目录：`prd.md` 是 PRD 环强制全局件（`rings/prd/reference.md` §2；`validate_prd.py:293` 缺它即 FAIL），「域级 PRD-only 项目」不是合法形态。改成目录后，只有 `product/prd/README.md` 的项目会被 AC 门判 `PASS 门禁降级通过`（探针实测），`atlas_check` 从 SKIP 变 ok，比现状更假。要改就改成「`prd.md` 或任一 `*-prd.md`」，并让空目录返回 N/A/SKIP；同时必须走 RFC-01 的 `_support/layout.py`，不能硬写 `product/prd`。装配面：`install.sh` 当前 54 条静态 `^check`（另有 skill 循环），`_support` 8 条 check；v2 的 54→56 可加，但工作区 `_support` 已是 9（layout.py），落地后是 11；RFC-01 已 Accepted 且在飞，它会先 +1，所以是 55→57 而非 54→56。`docs/map/index.md:58` 的 `install.sh`(580 行)、`atlas-map.html:172/501` 的「内核 ×9」「门册 146 行」、`docs/map/gates.md:56` 的 AC 门描述都未列入。

**11. 测试与变异：有保留。** 21 条覆盖主干，但缺：全局 `prd.md` 重复 AC、合法「备注」列、`## 5.` 标题变体、5 列（维度在第五列）、多 app、未实现域（v1 的 S4）、`blocked`/`red` E2E、`|E2E-` 无空格（直接覆盖 `atlas_verify`）、列顺序变化、类级 pytestmark 带 AC。M156f「本地复制一份索引解析器」只咬同名复制（守卫按 `^def <name>(` 计数），换名复制不红；应加函数对象同一性 + 逐消费者行为钉。§4.3 的「逐字节一致」没有可执行 harness，且与「删除一条 E2E check」自相矛盾：`checks[]` 必然少一行，必须明确比较口径（排除退役行/只比索引解析结果）。

**12. 编号与协调：有保留。** 当前 `DESIGN.md` 最大 D151、gates 最大 M155，D152/M156 空闲；但 RFC-01 已 Accepted 且先落，D152 可能被它占用，v2 的「建议 D152」只能当占位。评审报告应命名 `REVIEW-20261026-03-backend-coverage-dimensions.md`（评审序号独立于 RFC 序号；已有 01=backfill、02=RFC-02 v1）。v2 与 RFC-01 的重叠列得不全：还漏 `docs/map/atlas-map.html`、`docs/map/gates.md`、`templates/stack-profile.yaml:94`、`README.md:430`、`atlas_check` 前置的 layout 化。

**13. 叙事与边界：有保留。** §8 的「不新增执行层」划界正确，EL-01/EL-02 是上下游而非重复。但「跨栈」过度承诺：后端只支持 Python/pytest（`BACKEND_TEST_FRAMEWORKS=("pytest",)`）、E2E 只有 node-playwright、单 `test_dir`、AC/用例/测试都没有 app 归属、`mobile` 直接不参与。多 app/monorepo 下「项目级并集」不成立，必须在 `gates.md` 明写边界，或给数据模型加 app 维度。

## 必修项

1. **重写结果模型：逐 AC × 适用通道，而不是项目级并集。** 改：每个 AC 同时算 `union_complete` 与 `per_channel_missing`；任一适用通道「有资产但零维度贡献」⇒ WARN 并归因；「全部适用通道可用」且每通道无缺口才 PASS。为什么：否则全栈 AC 的 UI 缺口会被后端覆盖吞掉（§2.1.2 的反例）。验证：全栈夹具，E2E 用例存在但不写 `覆盖维度`，后端覆盖全部 ⇒ 必须 WARN「E2E 未覆盖 C01」。

2. **拆掉「整门 N/A」：N/A 不能吞零证据与单通道结论。** 改：先逐 AC 算已知部分；通道不可用只标注「结论不完整」，零证据恒 WARN；仅当无任何 AC 声明维度或无适用通道时才整门 N/A。同时给 `Result` 增加 N/A 态并让 `atlas_check` 可见，否则 N/A 会显示成 ok。验证：全栈无 `backend_test` 夹具 ⇒ 出现 E2E 侧 WARN + 不完整说明，而不是 N/A；`atlas_check` 行不是 ok。

3. **重做「零变化」口径。** 改：要么保留 `atlas_verify` 的窄解析作为显式适配器，要么承认并列出行为变化（`|E2E-` 无空格、列顺序、坏行）；保留 `parse_block`/`strip_inline_comment`/`MAIN_COLUMNS`/`tables` 的模块级别名；`split_row` 改名或限定守卫范围；统一 `load_module` 导入通道。为什么：探针已证 `atlas_verify` 与 `tables` 在无空格行上分叉。验证：同一索引（含 `|E2E-` 无空格、列序打乱、坏行）跑三消费者，输出差异逐项列出并断言；`test_shared_kernel` 函数对象钉绿。

4. **给 PRD 解析写死分支。** 改：3 列 ⇒ N/A；第 4 列表头非 `适用覆盖维度` 且单元格不含维度形态 ⇒ 忽略（不 WARN）；含维度形态 ⇒ WARN；`适用覆盖维度` 按表头定位而非硬编码第四列；标题接受 `## 五、` / `## 五 ` / `## 5.`；AC 文法二选一并写进契约。为什么：现有 3 列夹具与合法「备注」列会被误伤，标题变体会静默 N/A。验证：三个夹具（3 列、4 列备注写 P0、4 列备注写 C01）+ 标题变体，期望分别为 N/A、N/A、WARN、能解析。

5. **skipped/uncertain 覆盖必须变成可见 WARN。** 改：任一维度的唯一来源是 skipped/uncertain（含 E2E `blocked`/`red`）⇒ 该 AC 记 WARN 并在 detail 点名数量；不要只用 PASS + detail。为什么：`atlas_check` 只看末行，PASS 的 detail 不可见。验证：只有 skipped 用例覆盖的 AC ⇒ 行级 WARN，`atlas_check` 展开可见。

6. **补齐 enforce 契约第四处。** 改：`templates/stack-profile.yaml:94` 的 `enforce（缺口硬阻断）` 改为「仅 AC 挂载；维度恒 WARN」，与 `shared/stack-profile.md:107`、`docs/gates/iron-gates.md:69`、`docs/guide/legacy-adoption.md:125` 同步。为什么：模板会发到每个项目，是采用者最先读到的契约。验证：全文检索「缺口硬阻断」只剩历史语境。

7. **按 RFC-01 重排装配计数。** 改：`_support` 9→11（不是 8→10）、install 55→57（或按落地序）、`docs/map/index.md:37/53/111/58`、`docs/map/atlas-map.html:172/501`、`docs/map/gates.md:56`、`shared/gates.md:77`、`test_canonical_consistency`/`test_map_anchors` 全部重算；前置解析走 `layout`。为什么：当前工作区已 9 件，RFC-01 还会 +1；写 10 会直接推红 map 门。验证：`pytest tests/test_map_anchors.py tests/test_canonical_consistency.py` 绿，`install.sh --target /tmp/probe` exit 0。

8. **给「未实现域」与「零证据」分档。** 改：读页面表/域状态（或至少读域 PRD frontmatter）把「域未实现」的 AC 记为 N/A/明细，不逐条 WARN；已实现域零证据才 WARN。为什么：PRD 先于实现，v2 会对所有未来 AC 永久 WARN，且丢掉 D130 的 S4 分档。验证：`实现中`/`未开始` 域夹具不产生逐条 WARN，detail 报「未实现域 N 条」；已实现域零测试 ⇒ WARN。

9. **收窄豁免。** 改：`不可验`/`结构类` 只豁免 E2E 通道（或要求理由里声明「后端亦不可验」）；后端通道仍参与。为什么：「不可验」是 UI 观测面定义，后端可测的 AC 被跳过就是假绿。验证：不可验清单中的 AC 声明 C13、后端无 dims ⇒ WARN，不被豁免。

10. **修测试与变异。** 改：补 `C01-C03` 区间、`C01正常流` 邻接、多 app、未实现域、`blocked`、`|E2E-` 无空格、列序、5 列维度；M156f 改为「换名复制也红」的结构钉 + 函数对象钉；M131 明确退役/重靶；提供可执行的 old/new 差分脚本（排除退役 check 行）。为什么：现矩阵咬不到解析边界，M156f 咬不到真正的第二份实现。

## 建议项

1. 把检查名改为「AC × 覆盖维度（声明）」，避免被读成执行证据。
2. `parse_prd_assets` 同时供 E2E 校验器读取豁免清单，消灭第二份清单解析；`AC_RE` 收敛为一处文法。
3. 更新 `rings/e2e/reference.md:178`、`templates/e2e/case-shard.md:26`、`templates/prd/domain.md:111` 的「前端裁剪 / E2E 门对账」措辞，不能只改指针。
4. `docs/map/gates.md:56` 的 AC 门描述补「维度对账」；`README.md:430` 行号修正。
5. 增加 `C01@e2e` 之类的通道限定作为下一批；本批至少在 detail 里永远打印通道分布，不只打印缺口。
6. 若坚持「设计覆盖」，把 skipped/uncertain 计数写进 PASS 的末行摘要（`atlas_check` 可见面）。

## 结构级问题

- **骨架问题（结果模型）**：单个门状态 + 集合并集无法表达「每个适用通道必须覆盖到哪些维度」。必须改成 AC × 通道的矩阵结果，再聚合出门状态；否则「跨栈」只是把两个单通道结论取并，弱于被它替换的 E2E 门。
- **骨架问题（N/A 表示）**：`validate_ac_alignment.Result` 没有 N/A 态，`atlas_check` 对 PASS 只显示末行；v2 大量使用 N/A，等于在唯一可见面上制造 ok。
- **边界问题（多 app）**：AC、用例、后端测试都没有 app 归属，`backend_test` 只有一个 `test_dir`；多 frontend/多 backend/monorepo 无法成立。要么在契约里声明「单 app 项目」范围，要么给数据模型加 app 维度。

## 附：取证清单

- 读：RFC 全文；`REVIEW-20261026-02`；`REVIEW-20261026-01`（格式）；`validate_ac_alignment.py`、`validate_e2e_index.py`（69/197-217/301-317/549-555/612-653/659-666）、`validate_prd.py`（42/259/293-295）、`validate_stack_profile.py`（78 KINDS/ROLES/BACKEND_TEST_FRAMEWORKS）、`validate_structure.py:72`；`e2e_console.py:207-209/300-335`；`atlas_verify.py:215-231/268/314`；`_support/siblings.py`、`case_block.py`；`tests/test_validate_ac_alignment.py:44-50/83-97`、`tests/test_shared_kernel.py:218-256`、`tests/test_validators.py:1306-1356`、`tests/test_atlas_verify.py`、`tests/test_map_anchors.py:230-290`、`tests/test_canonical_consistency.py:221-291`；`install.sh:402-492`；`shared/gates.md:45/48/77`；`shared/stack-profile.md:107`；`templates/prd/global.md`/`domain.md:103-130`、`templates/stack-profile.yaml:94`、`templates/e2e/case-shard.md:25-27`；`rings/prd/reference.md:188-215`、`rings/e2e/reference.md:164/178/320-322/591`；`docs/map/index.md:37/53/58/107-112`、`docs/map/gates.md:56`、`docs/map/atlas-map.html:172/249/501`；`DESIGN.md:599`、D151；`RFC-20261026-01` §3；`BACKLOG-execution-layer.md:18-19/76`。
- 只读探针（`/tmp/rev3/probe`）：`atlas_verify._index_case_ids` 对 `|E2E-HOME-001|...` 返回空集、`_index_state_of` 返回 None；`validate_e2e_index.tables/split_row` 同文可解析。`validate_ac_alignment`：3 列 PRD ⇒ PASS；4 列「备注」写 C01 ⇒ 仍 PASS（静默）；仅 `product/prd/README.md` ⇒ `PASS 门禁降级通过`。
- 计数：`grep -c '^check ' install.sh` = 54；`_support/*.py` 实际 9（含 RFC-01 未跟踪 `layout.py`）；`docs/map` 工作区已写 9 件/40 测试文件；HEAD 为 8/39；`shared/gates.md` 146 行。
- 未修改仓库；`git status` 中的 `docs/map/*`、`shared/gates.md`、`validators/*`、`_support/layout.py`、`tests/test_layout.py` 为评审开始前已存在的并行 RFC-01 改动。

---

> **主审复核（2026-10-26，非评审者）**：抽查了工作区计数（`_support` 9 / 测试 40 / install 54）、`templates/prd/global.md` 无 AC 表、`validate_prd` 强制全局 `prd.md`、`README`/`validate_ac_alignment`/`validate_prd`/`validate_e2e_index`/`validate_structure` 的行号漂移、`split_row` 重名、`test_shared_kernel` 的别名钉、`UNVER_LIST_HEAD`/`STRUCT_LIST_HEAD`、`atlas_verify` 窄解析分叉、`templates/stack-profile.yaml:94` 的 enforce 措辞、RFC-01 已 Accepted，均属实。行号已在正文按实际修正（README 430、ac_alignment 288、prd 42、e2e 81、structure 72）。评审结论不变。
