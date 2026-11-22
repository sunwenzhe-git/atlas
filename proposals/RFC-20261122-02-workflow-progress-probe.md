# 提案标题：执行层 in_progress 任务进度只读探针（`atlas workflow progress`）

> 提案编号：`RFC-20261122-02`
> 提案作者：@sunwenzhe-git
> 关联状态：已定案 (Accepted)（v2：评审 12 条全采纳；v3 落刀回填，见 §4 与落刀注记）
> 影响范围：脚本工具 (scripts) | 文档与计数棘轮 (docs/map)

---

## 1. 现象与取证 (The Problem & Evidence)

### 1.1 触发形态（抽象）

* **规则 / 环节**：执行层任务账本（`.atlas/tasks/`，`scripts/atlas_workflow.py`）的三态状态机 `todo < in_progress < completed`（`_support/workflow_plan.py:237`）。
* **触发时机**：任务已 `dispatch`（状态 `in_progress`）之后、`verify`/`finish` 之前，任何时刻想回答「这个任务做到哪了」。
* **具体行为**：`atlas workflow status` 对 in_progress 任务只输出图标行（`▶ [ID] 标题 (in_progress)` + AC 清单，`scripts/atlas_workflow.py:369-374`）；`task.json` 只有 `id/title/status/depends_on/affected_domains/acs/created_at`（+可选 `paths`）字段（`_support/workflow_plan.py:258-268`），dispatch 之后整条链上没有任何组件回写进度。in_progress 是状态机里的**黑洞**：做没做完看状态，做到哪只能靠人肉翻四处证据。

### 1.2 客观证据：进度事实已存在，但没有聚合视图

「做到哪」的全部事实早已落盘，分散在四处，无一被聚合：

| # | 证据 | 落点 | 现有消费点 |
|---|---|---|---|
| 1 | 派工要求面 | `.atlas/tasks/<ID>/dispatch.md` | dispatch 写入后无人再读 |
| 2 | 实际改动面 | git 暂存区（`git diff --cached --name-only`） | `_has_staged_changes` 只判空非空（`scripts/atlas_workflow.py:378-384`） |
| 3 | 独立审查轮次 | `product/reviews/<date>-impl-review-<unit>/findings/<unit>.r<N>.json` | 取号用（`_next_review_round`，`scripts/atlas_workflow.py:224-235`，**按日重置**：新日期目录轮号从 1 起），不展示历史 |
| 4 | 条目覆盖矩阵填写进度 | `.atlas/tasks/<ID>/coverage-matrix.md` | 仅 finish 前 `coverage_matrix_findings` 判缺口（`_support/workflow_verify.py`），不报「填到哪了」 |

取证（`atlas workflow status` 现输出，中间态无任何进度信息）：

```text
atlas workflow 任务台账（共 1 项）：
  ▶ [UNIT-01] 某任务标题 (in_progress)
      ACs: AC-1, AC-2
```

命名契约 `product/reviews/<date>-impl-review-<unit>/findings/<unit>.r<N>.json` 现有 **4 个消费点**（按实清点）：`_support/workflow_finish.py:31`（`REVIEW_DIR_PREFIX_RE`）、`scripts/atlas_review.py:340`（目录构造源头）、`scripts/atlas_workflow.py:224`（当日取号）、`scripts/run_playground_benchmark.py:130`。消费点已多，本探针若各自拼路径即第 5 个真相源——这是 §2.2 下沉定案的直接动机。

---

## 2. 决策与权衡 (The Decision & Trade-offs)

### 2.1 核心定案 (The Decision)

* **方案总结**：新增只读子命令 `atlas workflow progress --unit <ID>`，把上表四路证据实时聚合为一个进度视图。纯派生物：**不写盘、不改状态、零新字段、零新门**，全部格子从机器可验证证据推导，无任何自由文本进度输入。
* **为何这是正解**：进度缺失不是「没地方记」，而是「记了没人看」——四路证据已客观存在，缺的只是聚合交付面。做只读探针**不新增**判据面（注意：探针判据全是路径级存在性/计数，`git add` 空 hunk 也算「命中」——这不是内容级证据，AC 落没落仍只认 verify；盲区见 §2.3 注记）。它同时杜绝了「执行方回写 progress 字段」那条路必然引入的自感知缺陷族（历史缺陷 #1/#4：判据可被措辞/配置满足——自由文本 progress 字段就是措辞面）。

四格视图定义（每格只报机器可验证的存在性/计数/取值，不做 AC 级判定）：

| 格 | 内容 | 判据 |
|---|---|---|
| 派工 | dispatch.md 存在性、AC 条数、paths 范围 | 文件存在 + task.json 字段 |
| 实现 | 暂存文件**中性计数**：「paths 内 N / paths 外 M」+ 明细；明示**范围外含其他在途任务的正常暂存，不暗示跑偏**（暂存区是仓库级，多卡在途是账本常态——`status` 的 `--unit` 前缀过滤 `atlas_workflow.py:357-358` 即为证） | `git diff --cached --name-only`；git 不可用显示「非 git 环境」（与「暂存区为空」**分开呈现**，不复用 `_has_staged_changes` 的吞错口径）；暂存为空明说「暂存区为空」 |
| 审查 | 轮次计数按（目录日期, 轮号）排序：**「跨 N 日共 M 轮」分段表述**（轮号按日重置，跨目录直接求和会重复计数）；最近轮 = 排序键最大者，verdict 从 json 读，读不到标 `unknown` | 扫 `product/reviews/*-impl-review-<unit>/findings/<unit>.r*.json`（路径构造下沉共享，见 §2.2） |
| 对账 | coverage-matrix 四列（PRD/设计文档/实现/E2E）各「已填 k / 总 n / UNRESOLVED x」 | 复用 `workflow_verify.py` 表格解析（§2.2 同刀提为公共入口） |

* **范围收缩（防过度设计）**：AC 逐条「落了没」是 `verify` 的职责，探针不判。探针只报范围覆盖与证据存在性。
* **交付面**：终端四格表 + `--json` 机读（对齐 `status --json` 惯例）。
* **边界分支**：`--unit` 给组 ID（plan 拆出的 `<unit>-NN`）时不猜落点，列出成员卡并要求精确 ID（与 status 的前缀过滤行为区分开，写进反面包）；task.json 解析失败的坏卡指名「task.json 解析失败」而非「未找到任务卡」（`load_tasks` 现静默跳过坏卡，`workflow_plan.py:299-300`，探针须显式区分，误导排障方向）。

### 2.2 最强反方与证伪条件 (Strongest Counterargument & Falsification)

* **最强反方论证**：进度探针是「仪表盘幻觉」。in_progress 单元生命周期短（run 闭环 plan→dispatch→verify→finish 一次跑完），真正的进度信号就是 verify 过/不过，中间态探针的实际查阅频率趋近于零；而它引入一个必须长期维护的解析器——命名契约已有 4 个消费点（§1.2 清点），探针成为第 5 个后，命名契约一旦漂移，伤害面从「取号错轮」扩大到「进度显示错」。该反方同时否决两个备选：①「执行方回写 progress 字段到 task.json」（新增写入面与措辞满足缺陷族，比探针更糟）；②「往 dispatch.md 里追加人工勾选清单」（自由文本面，同缺陷族）——但它否决不了「什么都不做」，这是本方案必须正面回答的对手。
* **对反方的回应**：查阅频率低 ≠ 零价值——本 RFC 的动机正来自真实卡壳时刻（维护者面对 in_progress 卡不知道该看暂存区还是 findings）。命名契约漂移的代价用**下沉共享构造**缓解：v1 曾主张探针 import `_next_review_round`，评审证伪（该函数在 `scripts/` 侧，`_support/` 分层单向、反向 import 会循环导入；且它用 `date.today()` 只构造当日目录，提供不了探针所需的跨日期 glob）。定案：把目录名 pattern 与 `<unit>.r<N>.json` 文件名正则**下沉到 `_support`**（归宿 `workflow_finish.py:31` 既有 `REVIEW_DIR_PREFIX_RE` 所在层级，扩展为完整的「reviews 目录 + findings 文件」公共构造函数），当日取号（`_next_review_round` 改为调用方）与跨日 glob（探针）双方 import 同一构造——契约改名时全部消费点自动跟随，探针不成为第二真相源。`_first_table`/`_strip_fences`（现为 `workflow_verify.py` 下划线私有）同刀提升为公共入口，避免跨模块 import 私有名。
* **证伪条件**（形态复用 `shared/independent-review.md` §11）：

```text
discriminating_check{
  command: 构造 in_progress 卡 + git add 1 个 paths 内文件 + 1 个 paths 外文件
           + 跨 2 个日期目录共 3 轮 findings 后运行 `atlas workflow progress --unit <ID>`,
  expected_if_false: ① paths 外文件未落「范围外」或被计入「命中」（归因错误）；
                     ② 轮次未按（日期,轮号）排序 / 计数非「跨 2 日共 3 轮」（跨日语义错）
                     ——任一命中即本方案错
}
```

反面包：`todo` 卡跑 progress 输出「未派工」且不写盘不改状态；`completed`/archived 卡给出终态指引（`status --all`）；组 ID 列成员卡不猜落点；坏卡指名 task.json 解析失败；非需求驱动卡（无 coverage-matrix.md）对账格显示「无矩阵」不报错（对齐 `workflow_verify.py` 的「不制造假阳性」口径）。

### 2.3 必须警惕的刺痛代价与兼容性影响 (Trade-offs)

* **兼容性**：零新门零新字段，不破坏任何既有判据；存量任务卡（无 findings / 无矩阵 / 未暂存）各格显示「无证据」级文案，不报错、不 WARN（纯展示无判据风险）。
* **探针盲区（随 cli.md 落地时注记）**：「命中 = 路径级存在性，非内容级证据」——探针不做内容判定，AC 级结论仍只认 verify 与 review.json。
* **执行耗时**：探针每次跑一次 `git diff --cached --name-only` + 若干文件读，毫秒级；不进 run 闭环热路径，`status` 保持轻量（进度探针不塞进 `status`，避免台账遍历变慢——语义与成本都不同，故独立子命令）。
* **存量项目**：拉取后需 `atlas upgrade` 重装配才获得新 CLI 动词；不需要刷新事实。
* **长期维护成本**：`_support/workflow_progress.py` 是薄聚合层 + `_support` 侧一处共享构造（`_next_review_round` 改为消费方）；生命周期与执行层账本同寿，无独立退役面。

---

## 3. 改动面清单 (Affected Surface)

- [ ] **代码逻辑**：新增 `_support/workflow_progress.py`（探针聚合层）；`_support` 侧新增 reviews 路径公共构造（归宿 `workflow_finish.py` 的 `REVIEW_DIR_PREFIX_RE` 层级，扩展为目录+文件名完整构造），`scripts/atlas_workflow.py` 的 `_next_review_round` 改为消费方（行为不变，轮次取号回归绿为准）；`_support/workflow_verify.py` 的 `_first_table`/`_strip_fences` 提升为公共入口（探针 import，verify 自身调用点不变）；`scripts/atlas_workflow.py` 注册 `progress` 子命令
- [ ] **契约/文档**：`docs/guide/quick-start.md` 流程节一句话（探针盲区注记随此落地：「命中 = 路径级存在性，非内容级证据」）
- [ ] **docs/map**：`docs/map/cli.md:19` 的 `atlas_workflow.py` 行——**动词清单补 `progress`** + 行数锚（526）随实现重刷；`docs/map/index.md:108` 与 `docs/map/gates.md:4` 的〔数:出厂测试文件=86〕→ 87（新增 tests 文件触发）
- [ ] **测试防线**：新增 `tests/test_workflow_progress.py`——四格各至少 1 正钉 + 变异钉（暂存区空/非 git 环境区分/范围外归因、findings 零轮/跨日排序、矩阵 UNRESOLVED、todo 卡反面包、组 ID 拒绝、坏卡指名、_next_review_round 消费公共构造后取号回归）。新增 tests 文件咬红 `test_canonical_consistency` / `test_map_anchors` 守卫——按上面 docs/map 三处落点同步修后跑三面
- [ ] **留出验证（§4.5）**：不适用——非系统性修复（无门/判据改动，触发面核对 a/b 均不命中：不引子族、不改既有判据），落刀时按模板粘贴两条核对命令原始输出
- [ ] **版本装配**：不涉及（无新依赖；CLI 动词随装配面自然下发）

---

## 4. 验证与测试结果 (Verification)

落刀前本地必须全绿（本节落刀时回填）：

```bash
pytest tests/test_workflow_progress.py
pytest tests/
python3 scripts/atlas_check.py --fast
```

* **测试结果**：`pytest tests/` = 1929 passed, 6 skipped（工作树 3 红，全部归属并行会话在飞漂移：`e2e_console.py` 工作树改行致 e2egen.md 行数/符号锚 ×4 + 未跟踪 `RFC-20261122-01` 引用未声明字段；两者均不在本批提交面，干净树口径不存在）；本批新增 `tests/test_workflow_progress.py` 14 条全绿（四格正钉 / 归因变异钉〔范围外不计入命中〕/ 跨日排序钉〔旧日期大轮号不盖新日期〕/ unknown 兜底 / 组 ID / 手写卡无矩阵 / 非 git vs 暂存空 / 只读逐字节快照 / 取号按日重置回归）
* **自检结论**：`atlas_check --fast` = OK

### 落刀注记（实现期对提案的三处修订）

1. **评审 Minor-8 被证伪回收**：评审假设「`load_tasks` 静默跳过坏卡（workflow_plan.py:299-300）」，实况是**指名抛 `PlanError`**（`raise PlanError(f"任务卡损坏或不可读：{p}（{exc}）")`，被 main 捕获 die(2)）——坏卡拦截既有机制已满足，探针不再自带 corrupt 分支（死代码零容，已删）。
2. **审查格字段口径落实**：轮文件与终报同构（`cli_review_convert.py` 同一 review dict 写两处），「verdict 从 json 读」落实为 `status ∈ {PASS, WARN, FAIL}` + `ok`，坏 json 标 `UNKNOWN`。
3. **改动面两处评审漏网补齐**：`docs/map/atlas-map.html:307` 有「出厂测试 ×86」计数（评审 grep 完整词「出厂测试文件」漏掉 `×N` 形态）⇒ ×87 三形态同步；`shared/gates.md:127` 的〔数:出厂测试文件〕占位与 `docs/map` 占位（含〔数:共享内核〕26→27，探针新件入 `_support/`）由 `ledger_snapshot.py --write` 统一刷 4 处。计数锚分工实跑验证：行数/×N 归 `tests/refresh_count_anchors.py`（本批手工等价写，避开并行会话在飞的 `e2e_console.py` 行数），〔数:…〕占位归 `scripts/ledger_snapshot.py --write`。

---

## 附：评审记录

2026-11-22 tech-proposal-reviewer 独立评审（round 1）：**修后通过**——0 Blocker / 3 Major / 7 Minor / 2 Nit，12 条全采纳。修复要点：Major-1 单源复用主张证伪 → 改为下沉共享构造；Major-2 改动面三处落点失实（shared/gates.md 无 workflow 门行 / atlas-map.html 无该计数 / apply.md 行数锚不涉及）→ 按实重写；Major-3 暂存区全局性归因 → 中性计数文案。
