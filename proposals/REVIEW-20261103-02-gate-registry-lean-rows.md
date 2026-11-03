# REVIEW-20261103-02：门登记表瘦身（RFC-20261103-03）

- **被审对象**：`proposals/RFC-20261103-03-gate-registry-lean-rows.md`（已定案，实现已落、未提交）+ 工作树改动：`shared/gates.md`（E2E 行 11,696 → 1,598 + 2 处 `\|` 转义）、`shared/global-rules.md` §13 增补、`tests/test_gate_registry.py`（新建，3 钉 + 唯一性）
- **评审方式**：独立只读子 agent；全部结论附本次重跑的原始命令与输出（依 `shared/independent-review.md:188`，不引作者 §4.5）；变异验证在 `/tmp/atlas-review-20261103-02`（`cp -R` 副本，还原后 sha256 逐字节核回）；活仓零写入
- **总判定**：**accept with changes**（方向、口径、三钉、变异杀伤全部实证成立；1 处迁移审计误载 + 2 处措辞/回指缺陷须修补后收口）

## Critical

无。

## Major

1. **「select 打标（M149/150 叙述）」承载审计误载——两个声称的承载点都不含该叙述**
   审计表（RFC §5）声称承载 = `DESIGN.md` D144 行 + `proposals/RFC-20261101-01`。实测：
   - `DESIGN.md:613`（D144 行）只有病灶/定案/被否/钉四段，**无 M149/M150**；
   - `proposals/RFC-20261101-01-code-only-constraints.md` 对 `select|打标` **零命中**（其 `M150` 命中是 `docs/map` M 编号命名空间「M 编号上限 M150 → M162」（`:243-244`），与变异 M150 同号不同义）；
   - 全仓 grep `M149`：仅 `shared/gates.md`（本批钉清单裸编号）与本 RFC 自身。变异档案 `.atlas/runs/mutation-proof/` 17 个文件无 M149/M150。
   被删叙述（基线 cell 6）：「变异 **M149**（回退整页下标点击 ⇒ 4 钉红）、**M150**（打标目标改指 `all[20]` ⇒ 2 钉红），还原 sha256 逐字节一致」——现已无承载。这正是 §5 残留风险①预警的形态，且违反 RFC 自己的硬规则「查无承载的先补进对应 D 行，再删」。
   **处置**：收口前二选一——(a) 在 `DESIGN.md:613` D144 行补「⑤ 变异」一句（内容可从 `git show c80182c:shared/gates.md` 恢复，约 80 字）；(b) 改审计表该行为「变异咬合叙述无承载，行内仅存裸编号，恢复源 = c80182c」。推荐 (a)，一行改动。

## Minor

1. **「判据格原文逐字节保留」差 1 字节**：现树 cell 3 前 913 字节与基线逐字节一致；基线第 914 字节（格内**尾随空格**）被实现为指针句的前接符「；」吞掉。非空白字节全部保留，GFM 渲染无差，但「逐字节」表述严格不成立。**处置**：恢复尾随空格（把指针改为在空格后接「；**控制台…**」）或把 RFC §3 / 钉注释措辞改为「非空白字节逐字节保留」。
2. **`DESIGN.md:572`（D103 ③）出现陈旧回指**：原文「（`gates.md` 2.2 行已登记该相抵点）」——本批删除后该相抵点在 `shared/gates.md` 已 0 命中。相抵点内容本身仍在 D103 ③ 内（无信息损失），但回指悬空。**处置**：D103 该括注改为「（原登记于 gates.md 2.2 行，2026-11-03 瘦身批迁入本行）」。
3. **§2.4 升格条件语义歧义**：「任一登记行**再次**超过 2,000 字符 ⇒ 立机器棘轮」——现树已有 2 行 >2,000（`validators/validate_e2e_index.py` 3,181 / `scripts/validate_review_report.py` 2,058，基线即有），字面读触发即刻成立，与 §5「其余 12 行…逐次处理」矛盾。**处置**：补一词「新增超限（存量 >2,000 行按 §5 逐次）」。
4. **RFC §4 计数漂移**：「钉② 52 行全部 6 格」——现树 53 行（并行会话外来行，见下）；「pytest tests/ = 1,116 passed / 3 failed」——本次复跑 **1,119 passed / 5 skipped / 0 failed**（并行干扰已消，比声称更好）。无需改动，落 REVIEW 存证即可。
5. **钉②转义正则的已知限制**：`re.split(r"(?<!\\)\|")` 会把 `\\|`（字面反斜杠 + 真格界）误判为转义不切。现树仅 2 处单反斜杠 `\|`、无此形态；将来出现时钉②会误绿。留档即可，不必现在改。

## 混树核对（并行会话改动，非本批范围）

- `scripts/atlas_eval.py` 登记行（HEAD `f17bc82` 引入，`shared/gates.md:56`）：实测 6 格、位于 §2.1 机器门段（脚本门归属正确）、引用 `RFC-20261103-06`，与本批改动无列结构/行序冲突。
- `check-all.py` 计数 48 → 49（工作树）：实测 `tests/` 下 `test_*.py` 恰 49 个（**含本批新增 `test_gate_registry.py`**）——两个会话的计数与实体互相咬合，无矛盾。
- `shared/global-rules.md` §17 与 `shared/single-source.md` 新行属并行会话 `RFC-20261103-02`（证据面/判分面），非本批；本批「不改 single-source.md」的声明成立。

## 复核记录（本次重跑命令 + 原始输出）

**R1 复跑新钉（活仓工作树）**
```
$ python3 -m pytest tests/test_gate_registry.py -v
tests/test_gate_registry.py::test_e2e_row_is_unique_and_within_cap PASSED [ 33%]
tests/test_gate_registry.py::test_every_row_has_exactly_six_cells PASSED [ 66%]
tests/test_gate_registry.py::test_every_cell_nonempty PASSED             [100%]
============================== 3 passed in 0.02s ===============================
```

**R2 口径重测**（脚本：RFC §1.1 写死口径——`## 2. 登记表` 至 `## 3.`、`|` 开头、排除首格 `门` 与分隔行；切分 `re.split(r"(?<!\\)\|")`）
```
$ python3 -I /tmp/atlas-review-scripts/metrics.py
== WORKTREE ==
rows=53  total_chars=46310  median=782  mean=873.8
>1200: 13  >2000: 2  max=3181 (5.4% of file 58788)
dates=132  Dnums=60  issue#=40
rows with !=6 cells: []
empty cells: []
E2E rows: 1  E2E row len=1598
top3 longest: [('`validators/validate_e2e_index.py`', 3181), ('`scripts/validate_review_report.py`…', 2058), ('`scripts/cli_review_convert.py`…', 1964)]
== BASELINE c80182c ==
rows=52  total_chars=55604  median=769.0  mean=1069.3
>1200: 13  >2000: 3  max=11696 (17.2% of file 68081)
dates=157  Dnums=91  issue#=46
rows with !=6 cells: [(2, '`validators/validate_stack_profile.py`', 7), (11, '`scripts/cli_review_convert.py`（实例 ⑤ 专用，', 7), (23, '`E2E 真跑`', 7)]
empty cells: []
E2E rows: 1  E2E row len=11696
```
基线 8 项指标（52 / 55,604 / 769 / 1,069.3 / 13 / 3 / 11,696 / 17.2%）与 RFC §1.1 基线表**逐项一致**（含行内含 157/91/46）。现树 E2E 行 1,598 ≤ 1,600；53 行（= 52 + 外来 atlas_eval 行）全部 6 格、无空格。

**R3 判据格保真（逐字节对比）**
```
$ python3 -I /tmp/atlas-review-scripts/e2e_cell3_diff.py
first divergence at index 913; cur[913:993]='；**控制台 / 生成器侧判据**（prepare / `ATLAS_CASE_ID` / …'
ref[913:993]=' '
similarity: 0.8977
replace: ref[913:914] (1) -> cur[913:1120] (207)
$ python3 -I /tmp/atlas-review-scripts/e2e_all_cells.py
cur3 without pointer: len 913
baseline cell3:       len 914 repr tail: 'sue #38 原案 SKIP 被否） '
equal to baseline minus trailing space: True
equal to baseline byte-exact: False
cell 1/2/5: equal=True   cell 4: 58 → 77（末尾追加「；人工会话取出（D103）见 §7.1」）  cell 6: 6,956 → 333
```
结论：判据本体 913/914 字节逐字节一致；差异 = 基线格内尾随空格 1 字节被指针前接符「；」取代（Minor-1）。cell 4 的指针是 §5 审计表预告的「行内留一行指针」，但 §3 改动面清单未列，属文档遗漏（并入 Minor-1 措辞修正即可）。cell 6 钉清单 13 组编号 + 四段协议留档位（`.atlas/runs/mutation-proof/`）+「咬合史归 `DESIGN.md` D 行」一行锚，各注解 ≤ 20 字，符合 §2.1 口径。

**R4 删除段承载抽验（§5 审计表抽 3 段 + 加验）**
- ① D108 首次咬合 / 28 失败构件：
```
$ grep -n "28 失败构件" DESIGN.md
577:| D108 | …⑤ **出库判定（2026-10-25 真跑日出库，D148 首轮）**：红轮 28 失败构件（trace.zip + 截图成对）/ 绿轮零构件，两面实证（咬合记录 = `shared/gates.md` 2.2「D108 首次咬合」）；**落点勘误随批**… ✓
```
（留存窗口在 `rings/e2e/reference.md` §7.1「失败留证」条亦有：「留存窗口 = 到下一次 `playwright test` 起跑」）
- ② select 打标 M149/M150：**不成立**（见 Major-1；原始输出：`grep -rn "M149" --include="*.md" --include="*.py"` 全仓仅 `shared/gates.md` + `proposals/RFC-20261103-03`；`grep "M149\|M150" proposals/RFC-20261101-01*.md` 仅 `:243-244` 的 docs/map M 编号；`grep "M149" DESIGN.md` 零命中）
- ③ 人工会话取出整段（3,697 字符溢出格）：
```
$ grep -n "人工会话取出" rings/e2e/reference.md
2 hits（§7.1 内，行偏移 46718 / 50833）：「**人工会话取出（描述路径，非机器门）**（2026-10-17 维护者拍板，`DESIGN.md` D103…）：…playwright codegen --save-storage=…」
$ grep -o "关窗\|幂等\|短命令\|相抵\|not_ready" DESIGN.md | sort | uniq -c
   4 关窗 / 20 幂等 / 1 短命令 / 4 相抵 / 9 not_ready   （D103 行 = DESIGN.md:572，含四纪律 + D80② 相抵全文）✓
```
严格说 §7.1 条缺「短命令」与 D80② 相抵两点，由 D103 补齐——审计表写的是「§7.1 + D103」双承载，**成立**；但由此产生 Minor-2 的陈旧回指。
- 加验（其余审计行）：MB10/11（`reference.md` §7.1 + D108 ✓）、MB1–3（D104 ✓）、MB19/20/22/23（D150/D151，DESIGN.md 命中 2/3/1/1 ✓）、M94/95（D110/D111 ✓）、M121–125（D121–D124 ✓）、M128/129/156–159（D127/D128/D174 ✓）、app_login 升档（D80②/D149/D101 ✓）、「首个真跑级 2026-10-04 逐页真跑」（DESIGN.md「逐页真跑」×2，均指向 gates 2.2 仓内记录 ✓）。**11 行审计行 10 行成立、1 行误载。**

**R5 变异验证（/tmp 副本，四段协议）**
```
# 基线绿（副本 = 活仓工作树态，sha256 f46b7de2d42ba085…901ecff0f85f4837818ccbd275314a1eef65876074e887c9）
$ python3 -I -m pytest tests/test_gate_registry.py -q   →  3 passed in 0.03s
# 变异①：E2E 行加长至 1,745 → 钉①红
E   AssertionError: E2E 真跑行 1745 > 1600（回长即拆）
FAILED tests/test_gate_registry.py::test_e2e_row_is_unique_and_within_cap   (1 failed, 2 passed)
# 还原（sha256 一致）→ 变异②：插入 7 格假行 → 钉②红
E   AssertionError: 格数 7 ≠ 6（游离竖线）：| `评审变异假门` …
FAILED tests/test_gate_registry.py::test_every_row_has_exactly_six_cells   (1 failed, 2 passed)
# 还原（sha256 一致）→ 变异③：清空 cell 5 → 钉③红（复跑两次，确定性）
E   AssertionError: 第 5 格为空：| `E2E 真跑` | 用例 ⇔ 真实应用 | …
FAILED tests/test_gate_registry.py::test_every_cell_nonempty               (1 failed, 2 passed)
# 还原（sha256 = f46b7de2…，逐字节一致）→ 复绿
$ python3 -I -m pytest tests/test_gate_registry.py -q   →  3 passed in 0.02s
```
三钉各自只杀自己的变异，杀伤面干净。（首轮变异③曾误现双红——系我方命令序列失误：变异②的 7 格行未还原即叠加；verbatim 复跑证实无钉间耦合。）

**R6 §4.5 触发面核对（补作者缺的原始输出）**
```
$ git diff --name-only HEAD -- shared/gates.md shared/global-rules.md tests/test_gate_registry.py
shared/gates.md
shared/global-rules.md
（tests/test_gate_registry.py 为未跟踪新文件，不入 diff——补：git status --porcelain shared/ tests/ 显示 `?? tests/test_gate_registry.py`）
$ python3 scripts/closeout_derive.py --diff-base HEAD
本清单不含语义触发行，正文自查
本轮改动 10 个文件（atlas 自有对账面 5 个；业务面 5 个，只计条数）
[自动] 步骤 1 —— 触发：任一工作单元收尾；改契约 / 模板 / 校验器 / 脚本 / skill 瘦桩…
[自动] 步骤 2 —— 触发：改契约 / 模板 / 校验器 / 脚本 / skill 瘦桩…
[人工] 步骤 3 —— 触发：改动触及核心业务链路 / 权限 / CI / 依赖 / 契约…
[人工] 步骤 5 —— 触发：改契约 / 模板 / 校验器 / 脚本 / skill 瘦桩…
[人工] 步骤 7 —— 触发：改契约 / 模板 / 校验器 / 脚本 / skill 瘦桩…
$ grep -n "契约\|脚本.*tests" scripts/closeout_derive.py   （族映射）
84:        ("契约", ("shared/", "rings/", "apply/", "atlas.config.yaml")),
74:        ("脚本", ("scripts/", "tests/")),
```
⇒ (b) **命中成立**：`shared/gates.md` 落「契约」族、`tests/test_gate_registry.py` 落「脚本」族（:74 注释明言 tests 并入脚本族），触发步骤 1/2/3/5/7。**「单案修复（无留出集）」确认成立**，理由三条：① 仓内本无按格消费登记行的机器判据（RFC §1.2 自证：无消费者），故不存在被收紧/翻转的**旧** verdict；② pre-fix 红证明（R7）钉①②对现存对象可咬（对象存在、判据非恒真），强于留出集；③ R5 变异增量杀伤已当场重放。QUEUE 观察行文本见文末。

**R7 pre-fix 红复核（c80182c 内容套同口径钉）**
```
# /tmp 副本 shared/gates.md ← git show c80182c:shared/gates.md
$ python3 -I -m pytest tests/test_gate_registry.py -v
::test_e2e_row_is_unique_and_within_cap FAILED [ 33%]
::test_every_row_has_exactly_six_cells FAILED [ 66%]
::test_every_cell_nonempty PASSED             [100%]
E   AssertionError: E2E 真跑行 11696 > 1600（回长即拆）
E   AssertionError: 格数 7 ≠ 6（游离竖线）：| `validators/validate_stack_profile.py`
2 failed, 1 passed in 0.04s
```
钉①（11,696 > 1,600）、钉②（3 行 7 格）拆行前即红，RFC §4.5 声称**成立**（任务书原文「钉①③」为笔误，RFC 自己写的是 ①②，与实测相符；钉③拆行前即绿——基线无空格格）。同实验附带证明：HEAD 态（本批未落）钉①②同样红 ⇒ 钉确实把守本批未提交改动。

**R8 单一真相源**
```
$ git status --porcelain shared/      → 仅 M gates.md / M global-rules.md / M single-source.md，无 ?? 新文件
$ ls shared/                          → 8 个 .md，无 gates-detail 或任何新目录
$ git diff HEAD -- shared/global-rules.md  §13 新 bullet：
「**门登记表同口径**（2026-11-03，`RFC-20261103-03`）：`shared/gates.md` 登记行只写「判据 + 不查什么 + 预算/触发物 + 取证等级 + 一行锚」；轮次咬合流水归 `DESIGN.md` D 行与留档，**表内不再追加**——锚指路，不复述。」
```
与 RFC §2.1 第 1 条**逐字一致**。`shared/single-source.md` 的新行（运行目录清单）属并行会话 RFC-20261103-02。✓ 无新增真相源。

**R9 全量与门禁**
```
$ python3 -m pytest tests/ -q            →  1119 passed, 5 skipped in 381.39s（0 failed）
$ python3 -m pytest tests/test_map_anchors.py tests/test_canonical_consistency.py -q
                                          →  17 passed in 2.42s（docs/map/gates.md:18「shared/gates.md(173 行)」与工作树 wc -l = 173 一致）
$ python3 scripts/atlas_check.py --fast  →  OK（SKIP 均合法降级态，与 RFC §4 一致）
$ sed -n '340,350p' install.sh           →  shared/ 与 tests/ 整目录 cp -R 进 .atlas/（RFC §3 装配面声称证实）
```

## 残留风险

1. 迁移审计 1/11 行误载（Major-1）：M149/M150 咬合叙述现仅存于 git 历史（`c80182c`），不补录则历史之外不可复算。
2. 新钉只守「结构 + 单行长度 + E2E 唯一性」，不守「判据是否被迁走」——判据格 913 字节保真本次人工核过（R3），后续改写无机器钉，属已知留白（RFC §5 已如实登记）。
3. `\|` 转义使原样字符串搜索失配（`partial|failed` → `partial\|failed`）；按 `\|` 归一后搜索。钉②的 `\\|` 误判限制见 Minor-5。
4. 存量 12 行 >1,200（另 2 行 >2,000）不解决，靠 §2.4 升格条件逐次处理——但该触发的字面歧义（Minor-3）可能导致「永远不触发」或「即刻触发」两种误读。

## QUEUE 观察行建议文本（收口时由实施者贴入 `duty-review/QUEUE.md` 观察室）

> - **门登记表瘦身形态钉观察（`RFC-20261103-03`，2026-11-03）**：`tests/test_gate_registry.py` 三钉（E2E 行 ≤1,600 且唯一 / 全行 6 格 / 无空格格）只守结构，不守判据内容迁移完整性。观察项 = 后续登记行编辑是否出现「判据文本被搬走只留锚」「`\\|` 双反斜杠形态致钉②误绿」「把 1,600 写进契约正文」；升室判据 = 任一登记行被新脚本按格消费且解析与 6 格口径错位 ⇒ 按 DR2 议把解析函数升机器门；出室判据 = 第一次登记表实质变更时三钉无误报且判据格抽查仍非空白字节漂移 ⇒ 归档。**三态 = 单案修复（无留出集）**（独立评审 REVIEW-20261103-02 确认：无旧判据 verdict 翻转，pre-fix 红已证判据可咬）。owner = 本批实施者；补验期限 = 下一次 `shared/gates.md` 登记表变更前（不晚于下一个 beta 发版后 2 周，先到为准）。

## 结论

方向与实现质量成立：基线口径 8 项逐项复现、判据格 913/914 字节保真、三钉四段协议全过、全量 1,119 passed / 0 failed、无新增真相源、§13 同口径落地。**收口条件 = 修复 Major-1（D144 补一句 M149/M150 咬合记录）+ 顺手处理 Minor-1/2/3（一处措辞、一处陈旧回指、一处触发条件消歧）**；三项均为一行级改动，不涉判据与结构。按此修补后可收口为 accept。
