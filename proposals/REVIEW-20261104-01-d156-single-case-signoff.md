# 评审记录：D156 三态签核（单案修复 · 无留出集）—— RFC-20261103-08 / RFC-20261103-09

> 评审编号：REVIEW-20261104-01
> 评审对象：`proposals/RFC-20261103-08-e2e-dim-header-validation.md` §4.5、`proposals/RFC-20261103-09-e2e-scripts-hash-run-artifacts.md` §4.5（对应 `54ad6e7`、`5a36129`）
> 评审结论：**两份均「准予（单案修复成立）」—— 0 条阻塞项，4 条附条件整改（不改变本次判定）**
> 评审者：外部评审（fresh context；未参与 `54ad6e7` / `5a36129` 的设计、实施与变异注入；评审在三个提交落盘之后开始）
> 评审方式：只读复核 + 规则比对 + 命令重放（原始输出见 §5）

---

## 1. 判定摘要

| RFC | 作者 §4.5 结论 | 本记录判定 | 一句话理由 |
|---|---|---|---|
| RFC-20261103-08（P1-1 表头校验） | 单案修复（无留出集） | **准予** | 仓内不存在任何「第 4 格语义 ≠ 表头名」的冻结 PRD 语料；唯一真实 PRD 样本表头合法，不产生翻转 |
| RFC-20261103-09（#31 运行产物排除） | 单案修复（无留出集） | **准予** | 仓内不存在任何 `.atlas-run/` 冻结语料（`git ls-files` 零命中）；任何候选都是现场构造的同一运行目录 |

**准入口径**（`shared/gates.md:107`，D156 行）：留出独立性三条缺一即按「同夹具变体」驳回——① 判据输出翻转（仅 WARN 文本 / 日志 / 通道变化不算）；② 变异增量杀伤；③ 结构不可达（夹具不可由既有钉夹具只改日期串 / 通道 / 增删行得到）。三态之一 `单案修复（无留出集）` 须「评审确认 + QUEUE 观察行 owner/期限 + 残留风险入 RFC §4.5」；「唯一判定记录 = 那份 RFC §4.5 + 其 REVIEW」。

**三态必要条件复核**：

| 条件 | RFC-08 | RFC-09 |
|---|---|---|
| 评审确认（本记录） | ✅ 本文 §2 | ✅ 本文 §3 |
| QUEUE 观察行 owner + 期限 | ✅ `duty-review/QUEUE.md:32` | ✅ `duty-review/QUEUE.md:33` |
| 残留风险入 RFC §4.5 | ⚠️ 部分（见 C4） | ⚠️ 部分（见 C4） |

---

## 2. RFC-20261103-08 逐条独立性

原文 = `RFC-20261103-08:152`。

| 条 | 作者主张 | 本记录结论 | 可复核依据 |
|---|---|---|---|
| ① 判据输出翻转 | 「本缺口只能由同一 AC 表的表头串翻转」 | **成立，但表述过窄**（见 C3） | 翻转的必要条件是「第 4 格语义与表头名 `适用覆盖维度` 不一致」；表头合法但列位错（`适用覆盖维度` 不在第 4 格）同样翻转：探针 `noncanonical_order -> {'AC-APP-001': {'C01'}}` |
| ② 变异增量杀伤 | M174 注入后既有钉全绿、新钉红 | **成立** | `.atlas/runs/mutation-proof/M174.txt` 四段齐全（基线绿 → 注入红 → sha256 还原 → 复绿） |
| ③ 结构不可达 | 「任何独立语料仍需构造同一张 AC 表并改表头」 | **成立** | 仓内无冻结历史 PRD 批次：`git grep -n "覆盖维度" -- "*.md"` 除模板/文档/proposals 外，唯一真实 PRD 样本 `tests/fixtures/verify_playground/product/prd/home-prd.md:41` 用的是合法表头 `适用覆盖维度` ⇒ 不翻转；其余候选只能由该样本/新钉夹具改表头或加减列得到 |

**对 ② 的独立说明**：② 证明的是「新钉有杀伤力」，不是「留出集存在」。作者把 ② 列为「无留出集」的依据属于借用论证——结论不受影响（①②③ 只需 ①③ 支撑「无可行留出集」），但措辞应避免让读者以为 ② 本身证明了独立性。

**对 ③ 的边界说明**：「增删列」不在 `gates.md:107` 的枚举（日期串 / 通道 / 增删行）内。按 ③ 的立意（夹具不可由既有钉夹具仅作结构微调得到），加列与加行同属微调，应一并排除；即便按最宽口径承认「加列可构造候选」，该候选仍是一张手写 AC 表，不是「未参与挖弱点的语料」，不满足 D155 对留出集的语义。故 ③ 结论成立，仅需把措辞从「枚举」改成「立意」。

**判定：准予。** 前提不成立面为零；剩余问题为表述精度（C3）与测试覆盖（C4），均不构成「存在可行留出集」。

---

## 3. RFC-20261103-09 逐条独立性

原文 = `RFC-20261103-09:93`。

| 条 | 作者主张 | 本记录结论 | 可复核依据 |
|---|---|---|---|
| ① 判据输出翻转 | 「翻转只能由 `.atlas-run/` 下的同一文件触发」 | **成立，但表述不精确**（见 C2） | 修复前翻转由 `.atlas-run/` 下**任意白名单扩展名文件**触发（不止 `results.json`）；`scripts/` 根下白名单扩展名的运行产物在修复后仍计入（RFC-09 §2.1 自述）。「仅运行产物类路径可触发」这层意思成立 |
| ② 变异增量杀伤 | M175 注入后既有钉绿、新钉红 | **成立** | `.atlas/runs/mutation-proof/M175.txt` 四段齐全（sha256 还原逐字节一致） |
| ③ 结构不可达 | 「任何独立语料仍需构造同一运行目录」 | **成立** | 仓内无任何 `.atlas-run/` 冻结语料：`git ls-files \| grep -E "atlas-run\|last-run\.json\|results\.json"` 零命中；`gitignore` 面使真实跑产物不可能入库 |

**与 P1-1 的同构问题**：② 同样只证明钉的杀伤力；③ 的实质依据是「本仓无冻结语料」，与「构造方式是否同夹具」无关——这一点作者未写出，建议补一句，否则 ③ 读起来像循环论证。

**判定：准予。** 但 RFC §4.5 (b) 的证据形式不合格（C1），需整改后回填，不影响三态。

---

## 4. 对维护者第 3 问：同会话复核能否作为 D156 的独立评审记录

**结论：不能——当复核者是实施者本人，或复核者继承了实施时的上下文时。能——当复核者 fresh context 且未参与实施，即使同一工作树、同一天。**

依据两条，均为硬规则：

1. `shared/gates.md:107`：「**由独立评审当场重放，不由作者自证**」；同一行又规定「唯一判定记录 = 那份 RFC §4.5 + 其 REVIEW」。若 REVIEW 由作者写，判定记录就退化为自证，与 D155 立条动机（两轮虚假留出集）直接冲突。
2. `shared/independent-review.md:105`：「审查者必须 **fresh context**——不得继承生成时的上下文」。判据是「上下文来源」，不是「时间戳」或「是否第三方」。

因此：
- `REVIEW-20261103-03` / `REVIEW-20261103-04` 不合格——两份自述「评审与实施同一会话；非第三方独立评审」（`REVIEW-20261103-03:6`、`REVIEW-20261103-04:6`），属规则点名的「作者自证」。
- 本记录合格——评审在三个提交落盘后开始，未参与实施，未继承生成上下文；不因「与上一份对抗式评审同属一个评审会话」而失效（该对抗式评审同样在提交之后、且未参与实施）。

**推论（需维护者动作）**：`duty-review/QUEUE.md:32-33` 的观察行仍指向不合约的 REVIEW-03/04，应改指本记录（见 C5）。

---

## 5. 重放命令与原始输出

```text
① 基线
$ git log --oneline -4
0299914 docs(proposals): delimit execution layer boundary (P1-3)
5a36129 fix(e2e): keep run artifacts out of scripts hash (#31)
54ad6e7 fix(validators): require E2E dimension header name
aaa9dcb docs(proposals): close three RFCs that already landed

② 提交真实改动面（评审侧重跑，不引作者自述）
$ git diff --name-only aaa9dcb 54ad6e7
docs/map/gates.md
duty-review/QUEUE.md
proposals/REVIEW-20261103-03-e2e-dim-header-validation.md
proposals/RFC-20261103-08-e2e-dim-header-validation.md
rings/e2e/reference.md
shared/gates.md
tests/fixtures/e2e_coverage_dims_golden.json
tests/test_validators.py
validators/validate_e2e_index.py

$ git diff --name-only 54ad6e7 5a36129
DESIGN.md
docs/map/atlas-map.html
docs/map/e2egen.md
docs/map/index.md
duty-review/QUEUE.md
duty-review/bugs.md
proposals/REVIEW-20261103-04-e2e-scripts-hash-run-artifacts.md
proposals/RFC-20261103-09-e2e-scripts-hash-run-artifacts.md
rings/e2e/reference.md
scripts/e2e_console.py
tests/test_e2e_console.py

③ 收口触发映射（脚本内纯函数 derive，喂入 ② 的文件清单，不读工作树 diff）
54ad6e7 steps = {1, 2, 3, 5, 7}, unmatched = []
5a36129 steps = {1, 2, 3, 5, 7}, unmatched = []

④ 留出语料是否存在
$ git grep -n "覆盖维度" -- "*.md" | grep -v proposals/
（仅 templates/ docs/ README/ DESIGN.md 命中，表头均为合法 `适用覆盖维度`）
$ git show HEAD:tests/fixtures/verify_playground/product/prd/home-prd.md | grep 覆盖维度
41:| AC ID | 场景（Given / When / Then） | 回指规则 | 适用覆盖维度 |
$ git ls-files | grep -E "atlas-run|last-run\.json|results\.json"
（零命中）

⑤ 变异四段
.atlas/runs/mutation-proof/M174.txt / M175.txt：基线绿 → 注入红 → sha256 还原（13e4950… / 55c773d…）→ 复绿
```

---

## 6. 附条件整改（不改变「准予」，但需落盘）

- **C1（RFC-09 §4.5 (b)）**：证据清单是手抄截断，非原始输出。原文列 5 个文件，实际 `git diff --name-only 54ad6e7 5a36129` 为 **11 个**（漏 `docs/map/*` 四项、`duty-review/QUEUE.md`、两份 proposals）。违反 `gates.md:107`「作者侧定档必须附原始输出」。整改：重贴完整清单；三态结论不变（(b) 两种口径都命中）。
- **C2（RFC-09 §4.5 ①）**：「同一文件」应为「`.atlas-run/` 下任意白名单扩展名产物」。
- **C3（RFC-08 §4.5 ①）**：「只能由表头串翻转」应为「由第 4 格语义与表头名不一致触发」（列位错同样翻转）。
- **C4（两份 §4.5 残留风险）**：未记入已知残留面——RFC-08：canonical 5 列布局未入新钉/golden；RFC-09：排除清单与包含白名单非单源（`scripts/e2e_console.py:157/:192` 双写、prep 键 `:161` vs `:196` 不一致）。
- **C5（台账指针）**：`duty-review/QUEUE.md:32-33` 的 REVIEW 指针需由 REVIEW-03/04 改为本记录。

---

## 7. 本记录不能证明什么

- **不能证明实现无残留缺陷**：本记录只做 D156 三态准入，不重审代码质量；已知残留（P1-1 canonical 5 列未钉、#31 包含面双写）在 C4 已列，仍按「未闭族」看待。
- **不能证明仓外语料不存在**：只能证明**本仓当前无冻结语料**；真实仓一旦出现「错表头 PRD」或「`.atlas-run/` 之外的运行产物」，须按 QUEUE 观察行升室重评。
- **不能替代实现评审与门证据**：本记录不重放全量测试、不构成 `atlas_check` 门绿；门证据仍以 `5a36129` / `54ad6e7` 各自的全量结果为准。
- **不能证明三态永真**：`单案修复（无留出集）` 是当下判定，不宣称闭族；观察行到期（首个真实仓 PRD 跑门后 2 周 / 首个真实仓真跑后 2 周）必须复评。
