# `_support/solution.py` 拆分方案（P4，只出方案，不动代码）

> 输入：`_support/solution.py` 当前 HEAD（3,997 行，`wc -l`；按 `# ----` 分节切块合计 3,994 行）、
> `2026-11-17/design-defect-audit/outputs/design-defect-audit.md`（F2/F3）、`2026-11-17/open-issues-triage/`。
> 方法：按 `# ----------------` 分隔符切 11 块；AST 级正则抽顶层 def/class 与调用点，
> 统计跨节调用；全仓 `*.py` 扫 `.<name>` 统计外部引用；`monkeypatch.setattr` 单独扫。
> 局限：静态正则，过近似（注释/字符串内的同名 token 会多算）；没有按提交历史量每节改动频次。

## 0. 结论先行

**推荐 C：先不整体拆。只做 X（把 2 个向上调用下沉 + 顶部加节索引），并把「抽 §10」留作独立决策。**
理由不是"重构太麻烦"，而是量出来的三条：

1. 11 个块之间有 **149 次跨节调用、39 组节对**；拆文件只改变代码位置，不减少耦合。
2. 严格「零出边、可整块搬走」的只有 §1 + §4，合计 **53 行（1.3%）**；其余任何整块都带出边。
3. 145 个顶层名里 **54 个被外部引用**，测试有 **6 处 `monkeypatch.setattr(core, …)` 直接改内核模块属性**
   —— 拆分后这些补丁打的是门面，改不到真正读全局的函数，会出现"测试还绿但守卫失效"的假绿。

若维护者仍要拆，按 **方案 A** 的四步走；**不建议方案 B**（见 §3 的最强反对意见）。

## 1. 量出来的事实

### 1.1 分节与体量

| # | 节（文件内注释名） | 行范围 | 行数 | 顶层 def/class | 被外部引用的名 | 外部引用次数 |
|---|---|---|---|---|---|---|
| 0 | 模块头 | 1–104 | 104 | 2 | 1 | 70 |
| 1 | manifest | 105–110 | 6 | 1 | 1 | 4 |
| 2 | reader_version（§5.2.1） | 111–712 | 602 | 20 | 9 | 162 |
| 3 | git | 713–972 | 260 | 20 | **0** | 0 |
| 4 | contracts / lock | 973–1019 | 47 | 3 | 1 | 1 |
| 5 | definition（§1.1 / §5.2） | 1020–1733 | 714 | 29 | 13 | 133 |
| 6 | init / adopt | 1734–2307 | 574 | 20 | 4 | 138 |
| 7 | status / check | 2308–2397 | 90 | 4 | 1 | 204 |
| 8 | B-0 ⓪ 层 + 纯函数 | 2398–3042 | 645 | 23 | 12 | 40 |
| 9 | D 批：crosswalk + 契约 AC | 3043–3795 | 753 | 16 | 7 | 92 |
| 10 | 封条写侧（C 批） | 3796–3994 | 199 | 7 | 5 | 13 |

合计 3,994 行（`wc -l` 3,997，差 3 行为文件尾空行）。

### 1.2 跨节依赖密度

**总计 149 次跨节调用，39 组节对**。最重的 9 组：

| 边 | 次数 | 主要被调 |
|---|---|---|
| §6 init/adopt → §2 reader/manifest | 18 | `load_manifest`、`_manifest_version`、`_validate_name`、`_safe_rel` |
| §2 → §0 模块头 | 11 | `SolutionError` |
| §5 definition → §3 git | 11 | `_git`、`member_state`、`_head`、`_is_git` |
| §5 → §0 | 9 | `SolutionError` |
| §9 checks → §3 | 9 | `_git`、`_status_lines`、`member_state` |
| §6 → §0 | 7 | `SolutionError` |
| §8 B-0 → §3 | 7 | `_git_bytes`、`_git`、`_is_git` |
| §8 → §5 | 7 | `prd_schema_findings`、`read_lock`、`_table_header_at` |
| §9 → §8 | 7 | `_check_definition_lock`、`_check_roots`、`historical_roots` |

每节入/出度：

| # | 节 | 出（节/次） | 入（节/次） |
|---|---|---|---|
| 0 | 模块头 | 0 / 0 | 6 / 34 |
| 1 | manifest | 0 / 0 | 3 / 4 |
| 2 | reader_version | 4 / 14 | 7 / 33 |
| 3 | git | 2 / 2 | 6 / 34 |
| 4 | contracts/lock | **0 / 0** | 3 / 3 |
| 5 | definition | 6 / 30 | 5 / 21 |
| 6 | init/adopt | 6 / 37 | 1 / 1 |
| 7 | status/check | 4 / 4 | 1 / 4 |
| 8 | B-0 | 4 / 16 | 2 / 8 |
| 9 | D 批 checks | 8 / 37 | 5 / 7 |
| 10 | 封条写侧 | 5 / 9 | **0 / 0** |

两条关键发现：

- **§2 有 2 条向上出边**：→§6 `_valid_task_slug`（1 次）、→§9 `_assets_root`（1 次）。这打破了"底→顶"的直觉分层，是任何自底向上拆分的**前置阻塞**。
- **`_assets_root` 一条被 5 个节调用**（§2/§5/§6/§8/§10）。它不是纯叶子，而是"被所有人借用的路径助手"——下沉它一次性消掉 5 条向上的边。

### 1.3 外部引用面

145 个顶层名，**54 个被 `_support/solution.py` 之外引用**（tests 为主，`scripts/atlas_solution.py` 次之）。最重的前几名：

| 名 | 总引用 | 主要引用方 |
|---|---|---|
| `status` | 204 | `tests/test_validate_ac_alignment.py`(51)、`tests/test_validators.py`(45) |
| `load_manifest` | 111 | `tests/test_atlas_solution.py`(42)、`tests/test_apply_record.py`(42) |
| `init_solution` | 106 | `tests/test_atlas_solution.py`(77) |
| `check_solution` | 82 | `tests/test_atlas_solution.py`(58) |
| `SolutionError` | 70 | `tests/test_atlas_solution.py`(38)、`scripts/atlas_solution.py`(8) |
| `write_lock` / `read_lock` | 60 / 37 | apply-record 与 solution 测试 |
| `migrate_manifest` | 27 | `tests/test_atlas_solution.py`(23) |
| `semver_lt` | 9 | 2A 的单源钉 |

**模块属性补丁面（拆分真正的雷）**：`tests/test_atlas_solution.py` 有 6 处直接改内核模块属性：

- `core._TOOL_PACKAGE_ROOT` ×3（版本/工具包根替换）
- `core.PRD_SCHEMA_2_FROM` ×2（schema 门切换）
- `core.iter_lock_history` ×1（断言"不得读历史"）

这些函数拆分后在自己的新模块里解析全局，**门面上 `setattr` 不会生效**——测试仍会通过，但守的东西没了。

### 1.4 能整块搬走且不需要反向引用的

严格满足「出边 = 0」的只有：**§1 manifest（6 行）+ §4 contracts/lock（47 行）= 53 行**。

另有两条"半个候选"：

- **§10 封条写侧（199 行，入边 = 0）**：没有任何内核块调用它，它是纯顶层消费者（CLI render / seal 操作）。但出边 5 节/9 次，搬走后要向前引用门面或底层模块，处理不好会形成 import 环。
- **§3 git（260 行，外部引用 = 0）**：没有任何外部代码引用它的名字，出边只有 2 次（`SolutionError`、`_validate_url`）。只要先把这两个名字下沉，它就是一个干净叶子。

## 2. 方案 A：自底向上三步 + 门面（结构性拆分）

### 2.1 边界

| 新模块 | 内容 | 估计行数 |
|---|---|---|
| `_support/solution_base.py` | §0（除可变全局）+ §1 + §2 + §3 + §4 + 下沉的 `_assets_root` / `_valid_task_slug` | ~1,030 |
| `_support/solution_core.py` | §5 + §7 + §8 + §9 | ~2,200 |
| `_support/solution_ops.py` | §6 + §10 | ~773 |
| `_support/solution.py` | 只留门面：import 三个模块并 re-export 145 个名 + `SolutionError` | ~40 |
| `_support/solution_state.py` | `PRD_SCHEMA_2_FROM`、`_TOOL_PACKAGE_ROOT` 等可变全局（见 2.3） | ~15 |

为什么 §7 必须跟 §9 在一起：§9 → §7 有 4 次调用（`_check_acceptance_cutover` / `_lock_contract` / `_lock_member`）。把 §7 放进 ops 会形成 core ⇄ ops 环。

### 2.2 迁移顺序（4 步，每步一个可回滚提交）

0. **前置（仍在单体内）**：把 `_assets_root`（§9）与 `_valid_task_slug`（§6）上移到 §0 附近；
   把 `PRD_SCHEMA_2_FROM` / `_TOOL_PACKAGE_ROOT` 迁到 `solution_state.py`，内核各处改成
   `state.X` 读。→ 消掉 6 条向上边，且把 6 处测试补丁的目标变成 `state`。
1. **抽 base**：搬 §0–§4，门面 re-export；`solution_core/ops` 还不存在，`solution.py` 仍持有其余代码。
2. **抽 core**：搬 §5/§7/§8/§9，import base；门面 re-export 增量。
3. **抽 ops**：搬 §6/§10，import base+core；门面收尾。
4. **收尾**：删掉门面里的残留转发，`共享内核` 计数按门刷新。

每步回滚 = revert 该提交，门面保证外部 import 面不变；不允许"只抽一半就停"（§4 反对意见）。

### 2.3 对 import 面与测试的影响

- 外部 54 个名全部经门面保留，`scripts/atlas_solution.py` / validators / tests 的 `core.X` 调用**不用改**。
- 6 处模块属性补丁必须改目标（`core` → `solution_state` / `solution_base`），否则**守卫静默失效**；这是本方案最容易被漏掉的成本。
- `monkeypatch.setattr(cli, "_load_solution", …)`（1 处）不受影响。
- 测试文件不需要拆；`preflight.py` 已把 `_support/*.py` 改动映射到引用它的测试，可作为每步的窄门。
- 账本：每新增一个 `_support/*.py`，`共享内核` 计数 +1（`docs/map/index.md` / `shared/gates.md` / `atlas-map.html`），需跑 `ledger_snapshot --write` + `refresh_count_anchors.py --write`。

### 2.4 能不能顺带消掉 P1 的 6 处反向依赖

**不能，且不相关**。那 6 处是 `_support/solution_e2e.py → validators/validate_e2e_index`（索引/分片解析），
与 `solution.py` 的分节无关。消它要抽 `_support/e2e_index_core.py`（排序 P3 / 2B）。

### 2.5 最强反对意见

- **拆到一半必停**：第 1 步之后，仓库变成「1 个 3k 行单体 + 1k 行 base + 门面」。此时导航成本**比不拆更高**
  （两个文件 + 一层 re-export 跳转），而 core/ops 的收益要等第 2、3 步才出现。历史上这类重构最常见的死法就是这个中间态。
- **核心块仍然巨大**：A 拆完最大模块 2,200 行，仍是单体，只是把「4k 一眼看不完」变成「2.2k 一眼看不完 + 两个小弟」。
- **149 次跨节调用不会因搬家减少**；如果目标是降低耦合，A 不解决，只解决"文件长度"。
- 与并行会话的冲突面：一次搬 1k 行会在这 4k 文件上造成长窗口，期间别人的改动要么冲突、要么被要求 rebase。

## 3. 方案 B：叶子优先，小步外移（低风险、低收益）

### 3.1 边界与顺序

1. **B1**：§10 封条写侧（199 行，入边 0）→ `_support/solution_render.py`。
2. **B2**：§1+§4（53 行，出边 0）→ `_support/solution_contracts.py`。
3. **B3**：§3 git（260 行，外部引用 0）→ `_support/solution_git.py`；先把 `SolutionError` / `_validate_url` 下沉。
4. **B4**：§7 status/check（90 行）→ `_support/solution_status.py`（需 §9 先接受它被外移，或把调用改为注入）。

合计外移 ~602 行（15%），剩余单体约 3.4k 行。每步独立可回滚。

### 3.2 对 import 面与测试的影响

- B1/B4 的导出名（`render_check`/`render_diff`/`freeze_seal`/`status`）被外部引用，需要门面转发；
  门面转发 + 新模块反向 import 门面 ⇒ **import 环**，只能靠函数内惰性 import 缓解——这正是 P1 棘轮点名过的反模式。
- B2 无外部引用，最干净；B3 次之。
- 6 处模块属性补丁：B2 不涉及，B1/B4 不涉及，B3 不涉及——**这是 B 唯一优于 A 的地方**。

### 3.3 能否消掉 P1 的 6 处反向依赖

**不能**。同 §2.4。

### 3.4 最强反对意见

- **收益太小**：外移 15%，剩余仍是单体；"文件短了"不等于"好读了"，尤其 B1/B3 会引入新的惰性 import。
- **制造新的反向依赖**：新模块 import 旧单体，等于把 P1 刚钉死的「内核 ↔ 上层」倒置复制一份；棘轮只盯 validators，不会拦这个。
- **B4 的边界不稳**：§7 被 §9 调用，未来 §9 再长，仍要回头改，属于"拆了但没解耦"。
- 它最大的价值是"无痛"，但无痛也意味着无感——半年后没人记得为什么要这 4 个文件。

## 4. 允许的结论 C：先不拆，只做 X

### 4.1 X 是什么

1. **X1（有明确收益，风险≈0）**：把 `_assets_root` 与 `_valid_task_slug` 上移，消掉 6 条向上边
   （§2→§6、§2→§9、§5/§8/§10→§9 的 `_assets_root`）。这让后续任何拆分都不再被"底层反向调用顶层"卡住。
2. **X2（可读性，风险≈0）**：在模块 docstring 顶部加 11 行的节索引（节名 + 职责 + 关键入口名，不写行号），
   让 `grep` 之前先有一张地图。
3. **X3（可选，独立决策）**：只抽 §10（199 行、入边 0）。它的边界最干净，是"唯一一个拆了不会让导航变差"的块。

### 4.2 为什么证据支持 C

- 严格零出边的只有 53 行（1.3%）；要拆到有意义，必须处理 §2 的 2 条向上边与 §9→§7 的 4 次调用。
- 外部引用 54/145、模块属性补丁 6 处——拆分不是纯搬运，是**改动测试契约**。
- 单体的真实成本在"改一处要读四节"，而 X2 的索引对这件事的收益/成本比高于 A 的第一步。
- 但 C 也有代价：不解决并行会话在同一 4k 文件上的 merge 冲突；如果冲突成本是主因，C 不够。

### 4.3 建议的决策规则

- 若痛点是**"找不到代码"** ⇒ 做 X1+X2，观察一个迭代；仍痛再上 A。
- 若痛点是**"多人同时改 solution.py 冲突"** ⇒ 直接上 A（只有 A 真正物理拆开），并接受 4 步中间态。
- 若痛点是**"测试太慢/太脆"** ⇒ A/B 都不解决，先做测试分层（不在本方案范围）。

## 5. 未量、需要补的证据（动手前）

- **每节的改动频次**（近 90 天）：决定 A 的拆分优先级，也能验证"§9/§6 最热"的假设。本次没量，因为需要按 diff 行归属逐提交解析。
- **每节的独立测试覆盖**：A 拆完后，哪些测试只触一个模块、可以按模块并行，未量。
- **并行会话冲突率**：`git log --merges` / 冲突文件统计，未量。

## 6. 验收与门（无论选哪个）

- 每步：`python3 scripts/preflight.py --files <本步改动>` → 再跑全量（本仓纪律：全量绿才推）。
- 账本：`共享内核` 计数、`最大单件文件` 可能变化，必须 `ledger_snapshot.py --write` + `refresh_count_anchors.py --write`，canonical / map_anchors 全绿。
- CHANGELOG：每批一行（`shared/closeout.md` 规则）。
- 6 处模块属性补丁在每步迁移后必须显式重指向，并跑对应测试确认补丁仍生效（不能只看绿）。
