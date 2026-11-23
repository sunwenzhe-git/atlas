# Atlas 遗留问题核实与处置排序

- 对象：`/Users/sunwenzhe/Desktop/atlas`，`main` @ `96fcd8b`（v0.3.0-beta.2 之后 10 笔已推送，其中 8 笔为账本批次）
- 日期：2026-11-17
- 性质：**只读排期判断件**。未改代码、未提交、未推送；**未实跑任何测试或复现命令**。
- 依据：静态阅读源码 / 契约 / git 历史；出处见每条「现状」。审计基线 = `2026-11-17/design-defect-audit/outputs/design-defect-audit.md`（下称「审计」），已落地边界 = `2026-11-17/ledger-design/outputs/ledger-design.md`（下称「设计案」）。
- 结论口径：**成立** = 原问题仍在且未被任何近期改动触及；**部分失效** = 结构还在但代价已降；**已缓解** = 有替代机制；**无法核实** = 缺环境或仓内无数据。

---

## 0. 一页摘要

八项里 **六项仍然成立、一项部分落地（preflight 未落）、一项无环境无法核实**。三条最该注意的判断：

1. **第 1 项比审计时更具体**：不只是「CI 只跑 2 个文件」，而是 D100 的两条替代门（全量测试纪律、CHANGELOG 各批记账）在最近这批里也都没有留下可核实的痕迹——`CHANGELOG.md` 在 HEAD 上无 `[Unreleased]` 段、无 11-17 条目，而这批全是 `feat`/`fix` 且触装配面。
2. **第 7 项的答案是「没落」**：`preflight` 在 `scripts/`、`shared/` 零命中（同名 `preflight()` 是 E2E 登录态预检，与本议题无关）；设计案步 5、步 6 都未执行。也就是说，**第 1 项与第 7 项是同一件事的两面**，不应排成两条。
3. **第 5 项是最便宜的欠账**：`git mv tests/changelog_guard.py scripts/changelog_guard.py` 之后，`tests/test_sync_automation.py:29-30` 的 `import changelog_guard` 仍然可用（它已把 `scripts` 放进 `sys.path`），装配面（`install.py:568-569`、`package.json.files`）自动覆盖。**不需要改代码**。

排序（详见 §9）：`1+7` → `5` → `6` → `2A` → `4` → `2B/2C` → `3`；`8` 挂环境条件。

> **笔数口径**：任务里说的「最近七笔」在 `dd80869..96fcd8b` 区间内实为 **8 笔账本提交**（`9d0d52d`、`23d771e`、`b0c230d`、`99acadc`、`7fb581a`、`1a17306`、`0357bea`、`0eac771`），另两笔是 `de6990a`（RFC 模板）与 `96fcd8b`（审计留档）。下文统一按 8 笔计。

---

## 1. 只有发版门、没有批次门（D100 的前提已失效）

### 现状

| 事实 | 位置 |
|---|---|
| D100 定案原文：「pre-commit 不上；启用留待 CI 一起落」「维护者明示接受该风险」；载体 = 显式跑纪律 | `DESIGN.md:569` |
| D100 的替代门写法：「批次闭环的全量测试纪律（CHANGELOG 各批带测试计数）优先于提交时延」 | `DESIGN.md:569` 同格 |
| CI 在 `push: main` 与 `PR` 上只跑 `test_cli_commands.py` + `test_project_wiring.py` | `.github/workflows/tests.yml:3-5`、`:30-33`、`:88-92` |
| 测试文件实况 **81** 个（审计日 80，本批 `test_ledger_snapshot.py` +1） | `ls tests/test_*.py` |
| 唯一强制点 = 发版：canonical + 全量 pytest | `scripts/release.py:308-321` |
| 仓内无常驻钩子（`.git/hooks` 只有 sample），也无 `.pre-commit-config.yaml` / husky / lefthook | 目录实况 |
| 本批 8 笔（`9d0d52d`…`0eac771`）全是 `feat`/`fix`、触 `scripts/`+`shared/`，但 `CHANGELOG.md` 无 `[Unreleased]` 段、无 2026-11-17 条目 | `head -15 CHANGELOG.md`；`grep -n 2026-11-17 CHANGELOG.md` 零命中 |
| 新增的派生数字门确实是「真判据」，但只存在于测试文件里，没人按批调用 | `tests/test_canonical_consistency.py:269`（`check_ledger_tokens`）、`tests/test_map_anchors.py:278`（`check_snapshot`） |

**日常提交有没有任何窄门**：没有。既无钩子，也无 CI 侧 canonical/ledger 检查，也没有任何「批次收口脚本」；`shared/closeout.md:40-52` 的步骤 1 只调用 `closeout_derive.py`（派生步骤清单，不改判据）与 `atlas_check.py`（需 `.atlas/` + `product/`，源包内恒 SKIP，见审计 F7）。

### 是否仍然成立

**成立，且范围扩大了一格**：审计说「CI 只跑 2 个」，本次补充的事实是「D100 自己写的两条替代门也没在跑」——本批 8 笔可以核实到的是：既无 CI 全量，也无 changelog 记账。本批是否在本地跑过全量 **无法核实**（提交信息不带计数、`.atlas/runs/check-events.jsonl` 只记录 `atlas_check` 且停在 2026-11-05）。

### 处置建议

**做（换种做法：不装钩子、不搬全量，只加一条三文件 pytest 组合）**，但不要重新开 D100 的战场（它反对的是 pre-commit 钩子，不是 CI）：

1. **批次门 = 一个 pytest 组合命令，不新写判据**：
   ```bash
   python3 -m pytest tests/test_canonical_consistency.py tests/test_map_anchors.py \
                     tests/test_ledger_snapshot.py -q
   ```
   依据：这三个文件的判据全是纯文本/AST 比对，`grep subprocess` 在三处均零命中 ⇒ 不依赖 git 历史、不依赖网络、不依赖浏览器。可达性上属于「CI 与本地同一条命令」。
2. **接进两处**：`shared/closeout.md` 步骤 1（在 `atlas_check` 之后加一行，注明「源包内用，采纳仓跳过」）；`.github/workflows/tests.yml` 的 POSIX job 加一步同样命令。二者都不改判据。
3. **压时预算的判据**：先在 CI 上量一次 p95；若 >60s，就只留 `test_map_anchors.py` + `test_canonical_consistency.py`（`test_ledger_snapshot.py` 的覆盖被前者的 `check_ledger_tokens` 包含）。**不得**为省时间改判据。
4. **不装 git hook**（尊重 D100）。若维护者要「强制」而非「纪律」，那是新的裁决，见 §10 拍板项 A。

### 改动面与成本量级

`shared/closeout.md` +1 行；`.github/workflows/tests.yml` +1 step。**XS**（不改代码、不改判据、不新增测试文件）。

### 依赖与前置条件

- 无代码依赖（D201 已把判据做成可独立调用的函数）。
- **流程前提**：本仓是「直接推 main」，所以本地必须在 **push 前**跑；CI 只能当兜底（推后才红 = 已产生一次修复提交，正是审计说的返工形态）。
- 需要一次真实计时（本次未跑，按约束不测）。

### 若不做，持续付什么

每一次改动到发版之间无机器反馈；账本漂移只能由发版日 535s 门（`release.py:308-321`）发现，随后补「清障」提交。历史数据：检索到 39 笔计数/锚/基线类提交（`git log --pretty=format:'%s' | grep -cE '清障|计数|基线|回正|锚'`），其中 3 天内 3 次发版门清障（`bf0e297` / `65eee1d` / `efb83c1`）。本批新机制上线仅 1 天，**还不能**证明成本已降。

---

## 2. 内核分层倒置（`_support` → `validators`）

### 现状

| 事实 | 位置 |
|---|---|
| 内核加载校验器，**不是 1 处而是 6 处**（审计只举了第 1 处） | `_support/solution_e2e.py:67`、`:168`、`:287`、`:318`、`:431`、`:467` — 全部 `load_module("validate_e2e_index")` |
| 该依赖是**写在文档里的有意选择**（不是疏忽） | `_support/solution_e2e.py:15`：「索引/分片解析复用既有校验器（同一份解析，不另写）」 |
| 校验器反向依赖内核 | `validators/validate_e2e_index.py:736`、`:815`（`load_module("solution").load_manifest`） |
| 内核回指内核（惰性） | `_support/solution.py:3307`、`:3334`、`:3654`（`_load_sibling("solution_task"/"solution_e2e")`） |
| 为避环写的注释 | `_support/solution_seal.py:5-6`、`_support/solution_task.py:9-10` |
| 加载器 **3 套** | `_support/siblings.py:23`（`load_module`，带 `sys.modules` 缓存）；`_support/solution.py:70`（`_load_sibling`，另一套缓存键）；`scripts/atlas_solution.py:25`（`_load_solution`，**不写 `sys.modules`**） |
| `semver_lt` **2 份，语义相反** | 内核：不可解析 ⇒ `False`（`_support/solution.py:126-134`）；CLI：不可解析 ⇒ **退回字符串比较**（`scripts/atlas_solution.py:219-226`） |
| `_git` 同名实现 **7 处**（生产侧） | `_support/solution.py:718`、`_support/solution_seal.py:54`、`adapters/_graph.py:172`、`scripts/ablation.py:187`、`scripts/atlas_eval.py:62`、`scripts/refresh_structure.py:609`、`validators/validate_task_card.py:38`；另有 `scripts/e2e_console.py:121/129/142/164` 四个窄封装 |
| 单源守卫只盯 **11 个函数名**，且只扫模块级 `def` | `tests/test_shared_kernel.py:227-243`（`allowed` 字典 11 项） |

### 是否仍然成立

**成立**，且比审计更硬：审计说「有两份 semver」，本次确认二者在**不可解析输入**上结论相反；这正是 `tests/test_shared_kernel.py:222-226` 自己记录的 B197-1 根因形态（双端各写一套 ⇒ 判据分叉）。当前唯一受影响面是 `--allow-dangling-acs` 的注册窗口（`scripts/atlas_solution.py:229-231`），但「窗口」会随版本推进关闭，届时两处结论仍可能不同。

### 处置建议

**做**，拆成三刀，按「先止血、再正骨」：

- **步 A（正确性，XS）**：抽 `_support/semver.py`，只暴露一个签名 `lt(raw: str, bound: str) -> bool`（不可解析一律 `False`，与内核现行语义一致）；`_support/solution.py:126` 与 `scripts/atlas_solution.py:219` 改为引用它。配 1 条钉：`"not-a-version"` 与 `"0.4.0"` 在两入口同结论。
- **步 B（结构，M）**：把 `validate_e2e_index` 里被内核消费的解析面（`tables` / `MAIN_COLUMNS` / `gather_shards`）迁到 `_support/e2e_index_core.py`，validator 与 `solution_e2e` 都指它；`solution_e2e` 的 6 处 `load_module` 全部删掉。
- **步 C（收敛，M）**：`_support/gitcmd.py` 收 7 处 `_git`（先只收「同名同签名」的 7 处，`e2e_console` 的 4 个窄封装留到最后）。
- **守卫换成「棘轮」而不是白名单**（XS，可立刻做）：
  - 在 `tests/test_shared_kernel.py` 加 `KNOWN_REVERSE_EDGES`，值 = 当前 6 个 `solution_e2e.py` 行号/符号，判据 = 「实际反向边集合必须是该集合的子集」⇒ **今天绿，新增即红**；
  - 步 B 落完后把该集合清空 ⇒ 同一判据变成「零反向边」。
  - 这比「把 11 个函数名扩到 20 个」有效：它锁的是**方向**，不是名字。

### 改动面与成本量级

A：2 文件 + 1 新文件（~30 行）+ 1 钉 → **XS/S**。
B：1 新文件（~200 行搬移）、validator 顶部 1 段、`solution_e2e` 6 行、守卫 1 条 → **M**。
C：1 新文件（~60 行）+ 7 处调用点 → **M**（最大风险是 `solution_seal` 的超时/二进制开关差异，必须逐处对齐）。

### 依赖与前置条件

- A、守卫棘轮：**无依赖**，可立即做。
- B：需确认 `tables` / `gather_shards` 是否被 validator 的其它路径以「模块属性」方式引用（`validate_e2e_index` 内多处 `mod.tables`），搬移时要保留转导出，不能只改 import。
- C：应在第 3 项（拆 `solution.py`）**之前**做，否则会先把一份 `_git` 拆进新文件、再回来收敛。

### 若不做，持续付什么

- 每次改 E2E 索引解析要同时想到 validator 与内核两侧；守卫不覆盖，只有真跑才暴露。
- 新增同类重复仍会逃逸（守卫只认 11 个名字），漂移成本按「入口数 × 判据数」增长。
- 一个可判定的错误窗口：版本字符串不可解析时，CLI 放行、内核拒绝（或反向），且不会红。

---

## 3. `_support/solution.py` 单体

### 现状

| 事实 | 实测 |
|---|---|
| 行数 | **3,997** 行（`wc -l`） |
| 分节 | **10** 个 `# ---` 段：`manifest`:102、`reader_version`:108、`git`:716、`contracts/lock`:976、`definition`:1023、`init/adopt`:1737、`status/check`:2311、`B-0 ⓪ 层`:2401、`crosswalk`:3046、`封条写侧`:3799 |
| 近 14 天改动 | **4,223 增 / 226 删 = 4,449 行**（`git log --since='2026-11-03' --numstat -- _support/solution.py`） |
| 配套 | `solution_seal.py` 1,822 行 / `solution_e2e.py` 606 行 / `solution_task.py` 435 行 |
| 消费者 | `solution_e2e`、`solution_task`、`atlas_apply_seal`、`validate_ac_alignment`、`validate_apply_record`、`validate_e2e_index`、测试 |

### 是否仍然成立

**成立，零变化**（行数、分节、改动量都与审计时一致；本批 8 笔未触碰该文件）。

### 处置建议

**做（换种做法：按变化频率切，不按文件大小切）**，且只切低耦合段：

1. **步 1（S）**：`git` 段（:716-975，约 260 行）→ `_support/solution_git.py`；`solution.py` 保留同名转导出（`from .solution_git import *` 不可用——本仓是 path 加载，改用 `_load_sibling` + 模块级赋值），其它 7 个消费者零改动。
2. **步 2（M）**：封条写侧（:3799-3997，199 行）→ 并入 `_support/solution_seal.py` 或同级 `solution_seal_write.py`；该段已有 76 条封条钉 + 22 条卡钉兜底，是行为不变最容易证明的一段。
3. **步 3（M/L）**：`crosswalk`（:3046-3798，753 行）→ `_support/solution_crosswalk.py`。`definition`（:1023-1736）与 `B-0`（:2401-3045）**本轮不动**——它们是判据最密、耦合最高的两段，动了就没有「行为不变」的证明面。
4. **不做**：一次性切 6 个模块（会同时改 6 个消费者的 path 加载 + 触发 `test_atlas_solution.py` 的大量 `load_module_path` 断言）。

### 改动面与成本量级

步 1 **S**（纯移动 + 转导出）；步 2 **M**；步 3 **M/L**。合计 **M**，可分三批独立回滚。

### 依赖与前置条件

- 步 1 **依赖第 2 项步 C**（先有 `gitcmd.py`，否则等于把第 7 份 `_git` 搬个家）。
- 步 3 建议在**第 2 项步 B**之后（crosswalk 会用到 e2e/AC 解析单源）。
- 全程不改函数体；判据靠现有套件（本次未跑，按约束不执行）。

### 若不做，持续付什么

- 并行会话改同一文件必冲突（仓内 `QUEUE.md` 有「在途批未提交」先例；D100 也把「多会话并行」写成前提）。
- 评审只能抽样：单个 diff 面 4,449 行/14 天，人类评审对判据变更的覆盖率无法保证。
- 这是**效率成本**，不是**正确性成本**——所以排序应低于第 1、2、6 项（见 §9）。

---

## 4. 决策台账只追加、无现行视图

### 现状

| 事实 | 实测 |
|---|---|
| §12 决策行 | **199** 行（`awk` 在 `:458`–`:680` 段内计 `^\| *D[0-9]`；审计写 211，口径差可能含子项/跨表行，本次以可机读的 199 为准） |
| 作废信息的三种形态 | ① 前言整段（`DESIGN.md:460`，一段话列 D8 / D45 / D46-47 / D48 / D49-53 部分 / D54-59 / D67 / D68 部分）；② 删除线 **2** 行（`:534` D71、`:540` D75）；③ 行内注记 **3** 处（`【已退役 2026-09-30…】` 等） |
| 机器可读性 | 零。`test_canonical_consistency.py` 只判 §13 的四个状态词与校验器清单，§12 无任何判据 |
| 是否已有「现行视图」 | 无。`grep 现行决策` 只命中两份 2026-11-17 文档；`scripts/ledger_snapshot.py:14-15` 明确「决策理由不派生」 |
| 具体矛盾例 | D72（`:537`，CI 分级「延后（依赖 B4）」）与 D100（`:569`，pre-commit「留待 CI」）相隔 32 行，单独读任一行都会误判现状 |

### 是否仍然成立

**成立**。审计 F5 的「结构性结论」没有被 D201 触及：D201 只清数字，明确把「决策理由」列在「不要试图算」清单里（`scripts/ledger_snapshot.py:14-15`）。

### 处置建议

**做（换种做法：不写「全量生成器」，只加标记 + 只读渲染 + 双向钉）**：

1. **标记（一次性，S）**：只给 `DESIGN.md:460` 前言点名的那些行加行尾机器标记——`〔作废 by E1〕` / `〔部分作废 by E1〕` / `〔退役 2026-09-30〕`。范围可枚举：前言列出的 ID + 两条删除线 + 三处行内注记，约 20-25 行。**只加标记，不改正文。**
2. **渲染（S）**：`scripts/decision_index.py`，读 `## 12.` 到 `## 13.` 之间的行，过滤掉含 `〔作废` 的行，输出「ID | 结论首句（≤40 字） | 原行号」到 **stdout**，不落文件（避免制造第七套账本）。
3. **钉（S）**：1 条双向判据——
   - 前言里点名的每个 ID ⇒ 该行必须有标记；
   - 每个标记 ⇒ 该 ID 必须在前言或删除线里出现过。
   这样「前言加了一条、忘了标记」和「标了废、前言没写理由」都会红。
4. **不做**：拆成「史 / 法」两文件（会打断所有历史行号引用，收益不抵成本）；不把 199 行全量结构化。

### 改动面与成本量级

`DESIGN.md` 约 20-25 行行尾追加；新增 1 个 ~40 行脚本 + 1 条测试。**S**（半天内）。

### 依赖与前置条件

- 无代码依赖。
- 与第 1 项共用「批次门」入口：`decision_index.py` 的形态钉可挂进同一条 preflight（非阻塞，可后置）。
- 需一次性人工判定「哪些是部分作废」——这是判断面，机器不能替代；但只需做一次。

### 若不做，持续付什么

- 每个新会话/新接手者都要跨 199 行做一致性推理；「按已废决策施工」的风险随 `proposals/` 与交接文档数量线性增长。
- 决策越加越多，前言会继续变长，最终只能靠人肉维护——这正是审计 F5 的二阶影响②。

---

## 5. `changelog_guard` 落在 `tests/`、不随包

### 现状

| 事实 | 位置 |
|---|---|
| 守卫实际路径 | `tests/changelog_guard.py`（`ls scripts/changelog_guard.py` 不存在） |
| 装配面不含 `tests` | `install.py:568-569`（`pkg_dirs` 10 项，无 `tests`）；`package.json.files` 无 `tests` |
| 装配覆盖面常量也不含 `tests` | `scripts/pkg_digest.py:55-56`（`ASSEMBLY_COVER_DIRS` 11 项，无 `tests`） |
| 仍是 shadow，且明写未接清单 | `shared/closeout.md:34`：「只报不阻（`--enforce` 已留但未接本清单）」 |
| RFC 承诺 | `proposals/RFC-20261114-04-sync-automation.md:32`（落点写的是 `scripts/`）、`:60`（「`--update` 后副本获得两脚本」） |
| 唯一引用者 | `tests/test_sync_automation.py:29-30`（`import changelog_guard`） |
| 本批实证 | 8 笔 `feat`/`fix` 触 `scripts/`+`shared/`，两份 changelog 都没有 `[Unreleased]` 段；若守卫已接线，本批会被 would-flag |

### 是否仍然成立

**成立**，且新增一条反例：本批 8 笔**正好**是守卫设计来拦的形态（触装配面的 feat/fix + 两份 changelog 零新增），但因为没接线，它一声没响。

### 处置建议

**做——这是八项里最便宜的一件，且不需要改代码**：

1. `git mv tests/changelog_guard.py scripts/changelog_guard.py`。
   - `tests/test_sync_automation.py:26-28` 已把 `HERE.parent / "scripts"` 加进 `sys.path`，`:30` 的 `import changelog_guard` **继续可用**（只是解析到新位置）。
   - `changelog_guard.py:36` 的 `DEFAULT_ROOT = HERE.parent` 在 `scripts/` 下仍是包根，语义不变。
   - 装配面自动覆盖：`install.py` 的 `pkg_dirs` 与 `package.json.files` 都含 `scripts`。
2. 同步两处文字：`shared/closeout.md:34` 的路径、`tests/changelog_guard.py:2` docstring 里的「本阶段不接 closeout」不要删（仍是事实）。
3. **不要顺手接 `--enforce`**：`closeout.md:34` 已写明前提是「先改成当日写账」，实测 26/30 会被 would-flag；现在开硬门会把整个历史账变成常红。
4. **顺手修一个使用陷阱**：守卫缺省 range = `origin/main..HEAD`（`changelog_guard.py:16-17`），推送后为空 ⇒ exit 2。搬到 `scripts/` 后应在 docstring 写明「已推送批次用 `--range <base>..HEAD`」，否则它在新位置同样跑不起来。

### 改动面与成本量级

1 次 `git mv` + 2 处文字。**XS**（10 分钟），零测试改动预期。

### 依赖与前置条件

- 无。但**建议排在第 1 项同一批**：第 1 项的 preflight 若要含 changelog 检查，得先让守卫在随包位置。
- 需拍板「权威是哪份」，见 §10 拍板项 B。

### 若不做，持续付什么

- 对采纳仓的承诺继续欠着（RFC 明写「副本获得两脚本」）；这是**对外契约**层面的欠账，不是内部风格。
- 两份 changelog 继续分叉（审计实测 `diff` 163 行），读者不知道哪份权威。
- 守卫已付实现与测试成本，但贡献为零（shadow + 不在装配面），是纯沉没成本。

---

## 6. 退役的 `prototype` 仍作缺省来源

### 现状

| 事实 | 位置 |
|---|---|
| 旧事件无 `source` ⇒ 视为 `prototype`（读侧） | `scripts/e2e_console.py:1446-1448`（`last_submit`）、`:1465`（`committed_snapshot`） |
| 同一缺省写入内核统计 | `_support/solution_e2e.py:448`（`e.get("source", "prototype") == "app"`） |
| `prototype-pass` 仍是合法状态 | `validators/validate_e2e_index.py:226`（`STATES = {..., "prototype-pass", ...}`） |
| 仍解析 `prototype` 段 | `_support/stack_profile.py:22`（`_DEFAULTS`）、`:116`（`_DICT_SECTIONS`） |
| 但该段已被判 N/A | `validators/validate_stack_profile.py:435`（「prototype 段（已退役 E1）」N/A） |
| 文档已把 `prototype-pass` 定义成 E0 历史终态 | `shared/global-rules.md:94`、`apply/reference.md:275`、`docs/design/e2e-ring.md:118` |

### 是否仍然成立

**成立（文档侧已缓解，代码侧未动）**。语义反转仍然存在：`source` 缺失时，**新事件**也会被归进已退役来源，读侧无法区分新旧（审计 F8 的最强反对已驳倒「只影响旧数据」）。E1 切点日期 `2026-09-27` 在 `DESIGN.md:460` 有明确记载，可作为归因分界。

### 处置建议

**做**，一次三行 + 一条钉：

1. 抽一个 `_event_source(e)`（放 `scripts/e2e_console.py`，由 `solution_e2e` 经既有加载器复用）：
   ```python
   E1_CUTOVER = "2026-09-27"          # E1 原型退役；DESIGN.md D-前言
   def event_source(e):
       if e.get("source"):
           return e["source"]
       return "prototype" if (e.get("ts") or "") < E1_CUTOVER else "unknown"
   ```
   替换 `e2e_console.py:1448`、`:1465`、`solution_e2e.py:448` 三处缺省。
2. **`prototype-pass` 不删**：保留在 `STATES`，只加注释 `# legacy=E0 历史终态，E1 起不产生`。删它会破坏存量索引的可读性（`shared/single-source.md:37` 记着存量行仍为 `prototype-pass`）。
3. `stack_profile` 的 `prototype` 段**保留解析**（旧 profile 要能读），但可把 `_DEFAULTS` 里的 `"prototype": {}` 删掉——不影响读取，只让「未声明即空」变成「未声明即不存在」。这属可选，非必需。
4. 钉 1 条：`ts < E1` 且无 `source` ⇒ `prototype`；`ts >= E1` 且无 `source` ⇒ `unknown`；有 `source` ⇒ 原值。

### 改动面与成本量级

3 行替换 + 1 个 helper + 1 条钉。**XS**。

### 依赖与前置条件

- **需拍板**：以 `2026-09-27` 作归因分界是否可接受。若采纳仓存在 9-27 之后仍由原型产生、且未写 `source` 的事件，会被归到 `unknown`（统计口径变化，但**不会**错归到退役来源）。见 §10 拍板项 C。
- 建议留一个版本周期再删 `prototype` 分支（审计建议），本次只改缺省，不删读法。

### 若不做，持续付什么

- 统计口径悄悄错：新事件漏写 `source` 会被算进已退役来源，且没有任何门会红。
- 每次有人问「现在还有没有原型来源」，答案只能靠读代码语义反推。

---

## 7. 方案乙的「批次 preflight」是否随最近一批落地（任务称七笔，实为 8 笔）

### 现状

**结论：没有落地。** 逐项比对设计案 §7 的六步：

| 设计案步骤 | 落地状态 | 证据 |
|---|---|---|
| 步 1 生成器 + 测试（不接线） | ✅ 已落 | `9d0d52d`：`scripts/ledger_snapshot.py`（217 行）、`tests/test_ledger_snapshot.py` |
| 步 2 index 快照改受管块 + 字节门 | ✅ 已落 | `23d771e`：`tests/test_map_anchors.py:278-301` 改「重渲染后逐字节不变」 |
| 步 3 gates 计数改引用 + 删正则 + 重锚 | ✅ 已落（删了 5 条，不是 4 条） | `b0c230d`；M20′/M22′/M23′/M24′ 在 `tests/test_canonical_consistency.py:530/541/556/566` |
| 步 4 章节删版本行 | ✅ 已落 | `99acadc`（7 个章节文件 + index） |
| **步 5 `--preflight` + closeout 接线** | ❌ **未落** | `grep -rn preflight scripts/ shared/` 只命中 `_support/auth_state.py:479` 与 `scripts/e2e_console.py:1519`（E2E 登录态预检，与批次门无关）；`shared/closeout.md:40-52` 无该步 |
| **步 6 changelog 权威 + guard 移位** | ❌ **未落** | 见第 5 项 |

8 笔里另有 4 笔是计划外补丁/收口：`7fb581a`（校验器数转占位 + D201 裁决）、`0357bea`（「编排门行」登记为派生键）、`1a17306`（html 文件条目计数纳入值域）、`0eac771`（变异钉登记完整性）。这些都属于「把派生面补齐」，**不构成批次门**。

**还差一处才算自洽**：`shared/gates.md:80` 仍是字面「数量 = `atlas_check.VALIDATORS` 长度，当前 12」，而 `tests/test_canonical_consistency.py:607` 正是读这个字面数字作判据。也就是说 D201 宣称的「计数一律派生」在这行不成立——它是「被旧判据锁住的字面量」，改校验器数时仍要手改两处（生成器已经能算 `校验器` 键，见 `scripts/ledger_snapshot.py:92`）。

### 是否仍然成立

对「preflight 落没落」这个问题：**未落地，且没有任何地方宣称已落地**（`CHANGELOG.md` 无该批条目、`DESIGN.md:677` 的 D201 只登记了派生计数，没登 preflight）。这属于**执行中断**，不是**宣称漂移**——性质比第 5 项轻。

### 处置建议

**做（换种做法：不新增 `--preflight` 子命令，与第 1 项合并）**：

1. 采第 1 项的建议（pytest 三文件组合 + closeout 一行 + CI 一步）。**不新写 `--preflight` 子命令**——当前没有 `atlas` 的 `--preflight` 命名空间，为一个组合命令引入 argparse 分支不划算。
2. 收掉 `shared/gates.md:80` 的字面量：改成 `〔数:校验器=12〕`；`check_gates_gates_are_scheduled` 的正则改为读占位值。1 处正文 + 1 处判据。
3. 在 D201 行（`DESIGN.md:677`）补一句「批次门见 `shared/closeout.md` 步骤 1」——避免下一次又出现「设计案有、实现无、没人发现」。

### 改动面与成本量级

同第 1 项（XS）+ `gates.md:80` 与 1 条判据（XS）。合计 **S**。

### 依赖与前置条件

- 第 1 项先做（同一入口）。
- 第 5 项应先做（若 preflight 之后要含 changelog 检查）。
- 需一次真实计时确认三文件组合 <60s（本次未跑）。

### 若不做，持续付什么

- 设计案里「频率必须 ≥ 改动频率」的判断落不了地；D201 的收益（数字不再手抄）只减少「改数字」这一类提交，不减少「发版才发现」这一类。
- 派生面会继续留下「一处被旧判据锁住的字面量」这种半迁移形态，下一次改动仍要两处同步。

---

## 8. 跨网传输复验（环境已不存在）

### 现状

无法核实。仓内没有该环境的任何快照、日志或锁副本；`.atlas/runs/check-events.jsonl` 只到 2026-11-05 且全部 `fast=true`（审计 F7 已记录）。因此本项只能交付**「有环境时照做」的复验单**，判定标准全部对齐代码里的现行语义。

### 是否仍然成立

**无法核实**（缺：父仓工作树 + 三成员仓 checkout + `atlas.solution.lock.json` + `.atlas/` 装配副本 + 三枚封条文件）。

### 处置建议

**做（换种做法：现在只交清单，环境回来再执行）——现在就把清单写进收口文档（不需要环境），等环境回来照跑。** 清单如下。

#### 前置条件（缺一即 BLOCKED，不得降级执行）

1. 父仓工作树干净：`git status --porcelain` 为空。封条链复算以 HEAD 为准，脏树会报 `seal_worktree_dirty`（`shared/gates.md:67`）。
2. 完整克隆（非 shallow）：封条路径的 L 序列、`epoch_origin_history`、`--full-history` 判据都依赖历史（`_support/solution_seal.py:402-413`、`shared/solution.md:128`）。
3. 父仓已装配 `.atlas/`，且 `.atlas/VERSION` == 源包版本：`atlas_check` 从 `<root>/.atlas/validators/` 取校验器（`scripts/atlas_check.py:239`），未装配 ⇒ 全部 SKIP。
4. 三成员仓已 checkout 到 `atlas.solution.lock.json` 的 `members[].head` / `branch`；缺工作区 ⇒ 只能 `--lenient`，而**有封条时 `--lenient` 恒 exit 2**（`scripts/atlas_solution.py:485-488`）。
5. `python3 >= 3.10`、`node >= 20`、`git`。**不需要** Playwright（`--fast` 不跑真跑面）。

#### 复验 1：父仓编排门

```bash
python3 .atlas/scripts/atlas_check.py --fast
```

- **判定**：exit 0；逐行无 `FAIL`。`SKIP` 是一等结论、必须带原因（`shared/closeout.md:51`），不得当通过。
- **可接受的 WARN**：`生成物最新` 在无 `--page` 时为 SKIP/WARN（`scripts/atlas_check.py:356/395`）；`独立审查未执行` WARN（`:402`）。
- **重点看** `validate_apply_record`：封条 findings 全部由它出（`shared/gates.md:67`）。
- **分流**：`seal_frozen_modified` ⇒ 封条文件在 `frozen_at` 之后被改过或 `frozen_at` 不是 HEAD 祖先（`_support/solution_seal.py:697-717`）；`seal_worktree_dirty` ⇒ 先清树。

#### 复验 2：方案层检查

```bash
python3 .atlas/scripts/atlas_solution.py check --strict
```

- **禁止** `--lenient`（有封条 ⇒ exit 2，`scripts/atlas_solution.py:485-488`）。
- **判定**：exit 0（`data["overall"] != "FAIL"`，`:503`）；stdout 无 `[FAIL]`。
- **分流**：`member_head_mismatch` / 清单与锁 `path`/`url` 不一致 ⇒ 成员仓不在锁点或清单漂移；`definition_commit_unverifiable` ⇒ 锁文件历史里 `definition.commit` 曾为非 null 现为 null（`shared/solution.md:128`）。

#### 复验 3：三成员仓

```bash
# 逐个成员仓根执行
python3 .atlas/scripts/atlas_check.py --fast
```

- **前置**：每个成员仓有自己的 `.atlas/` 装配副本（同一版本）。
- **判定**：无 `FAIL`。成员侧 `card_absent` 恒 WARN（不是 FAIL，`shared/gates.md:68`）；`evidence_columns_parent_only` 是成员侧合法 N/A（`shared/gates.md:70`）。
- **记录**：逐成员仓 `git rev-parse HEAD`，与锁 `members[].head` 对照。

#### 复验 4：锁里三枚封条锚是否仍 frozen

```bash
python3 - <<'PY'
import json, pathlib
lock = json.loads(pathlib.Path("atlas.solution.lock.json").read_text(encoding="utf-8"))
print("assets_root:", lock.get("layout_assets_root"))
for path, a in (lock.get("seal_anchors") or {}).items():
    print(path, a.get("state"), a.get("frozen_at"), a.get("anchor"), a.get("renewal_seq"))
PY
```

- **判定**：
  1. `seal_anchors` 恰好 **3** 个键（一成员一枚；多出/少出都要记原因）；
  2. 每枚 `state == "frozen"`（合法值只剩 `active` / `retired` / `frozen`，`_support/solution_seal.py:32`）；
  3. `frozen_at` == 该路径最后一枚封条提交：`git log -1 --format=%H -- <path>` 应等于 `frozen_at`，且 `frozen_at` 是 HEAD 祖先（`_support/solution_seal.py:697-711`）；
  4. 每个成员的 `members[].head` == 该成员仓 `git rev-parse HEAD`。
- **分流**：任一 `state != frozen` ⇒ 有人在冻结后做了 `lock --update` 或新签封条；`seal_frozen_modified` 出现 ⇒ 冻结后该路径有新提交或删除提交（`_support/solution_seal.py:707`）。

#### 记录模板（照抄填入）

| 项 | 命令 | 退出码 | FAIL 数 | 关键 WARN/SKIP | 结论 |
|---|---|---|---|---|---|
| 父仓 `atlas_check --fast` | 复验 1 | | | | |
| 父仓 `solution check --strict` | 复验 2 | | | | |
| 成员 A/B/C `--fast` | 复验 3 | | | | |
| 三枚封条锚 | 复验 4 | — | — | — | frozen ×3 |
| HEAD / 锁对照 | 见上 | — | — | — | |

### 改动面与成本量级

**不改代码**。有环境时人工 **约 30 分钟**（含三成员仓逐个跑）；无环境时 0，但清单本身应当落进 `shared/closeout.md` 或发布 runbook，否则下次又要重写。

### 依赖与前置条件

环境（父仓 + 三成员仓 + 装配副本 + 完整 git 历史）；第 2 项步 C 完成前不要顺手跑任何「收敛后」的临时脚本。

### 若不做，持续付什么

- 跨仓/封条链路是**唯一没有源包回归覆盖**的面：`tests/` 里全是夹具，真实装配态的行为没有第二条证据。
- 三枚 `frozen` 锚是历史防篡改的支点；它若被静默改动，只能在下一次真实发版时以「莫名其妙变红」的形式暴露。

---

## 9. 排序（一页）

### 9.1 打分口径

`优先级 = (持续成本 × 风险) / 实施成本`，三列各按 3/2/1 记（实施成本 3 = 最贵）。**不按发现顺序，也不按审计编号。**

| 项 | 持续成本 | 风险 | 实施成本 | 分值 | 顺序 |
|---|---|---|---|---|---|
| **1 + 7**（批次门 + preflight） | 3（每次发版清障） | 3（未验证改动直达 main） | 1（1 行文档 + 1 步 CI） | **9.0** | **P0** |
| **5**（guard 移位） | 2（对外承诺欠账） | 2（双 changelog 分叉） | 1（10 分钟，零代码） | **4.0** | **P0（同批）** |
| **6**（prototype 缺省） | 2（口径悄悄错） | 3（正确性） | 1（3 行 + 1 钉） | **6.0** | **P1** |
| **2A**（semver 单源 + 反向边棘轮） | 2 | 3（结论相反） | 1（~30 行 + 1 钉） | **6.0** | **P1** |
| **4**（决策现行视图） | 2（每个新会话） | 2（按废决策施工） | 1.5（20 行标记 + 40 行脚本） | **2.7** | **P2** |
| **2B / 2C**（e2e 核心抽取 / `_git` 收敛） | 2 | 2 | 2 | **2.0** | **P3** |
| **3**（拆单体） | 2（并行冲突 / 评审抽样） | 1（效率非正确性） | 3 | **0.7** | **P4** |
| **8**（跨网复验） | —（无环境即为 0） | 3（唯一无覆盖面） | — | 条件触发 | **B** |

第 5 项分值低于第 6/2A，仍放进 P0：它**零代码、10 分钟**，且与第 1 项共用 `shared/closeout.md` 同一处落点；单开一批反而是浪费。

### 9.2 执行顺序与依赖

```
P0（同一批，1 次提交或 2 次）
  ├─ 5   git mv guard → scripts/  + closeout.md:34 路径 + docstring 用法
  ├─ 1   三文件 pytest 组合 → closeout 步骤 1 + CI 一步
  └─ 7   收掉 gates.md:80 字面量 + D201 行补一句指针
        （1 与 7 是同一条，必须合并做；分开做会出现「门有了、判据还在手抄」）

P1（各自独立，可并行）
  ├─ 6   event_source() 三处替换 + 1 钉（需拍板 C）
  └─ 2A  _support/semver.py + 2 处引用 + 反向边棘轮（KNOWN_REVERSE_EDGES = 当前 6 处）

P2
  └─ 4   标记 20-25 行 + decision_index.py + 双向钉

P3
  ├─ 2B  e2e_index_core 抽取（清空棘轮集合）
  └─ 2C  gitcmd.py 收 7 处

P4
  └─ 3   步 1 依赖 2C；步 3 依赖 2B
```

**依赖边（硬）**：`7 ← 1`（同一入口）；`3.1 ← 2C`（否则把第 7 份 `_git` 搬家）；`3.3 ← 2B`（否则带着环拆）；`8 ← 环境`。
**独立可并行**：`5`、`6`、`2A`、`4` 互不依赖。

### 9.3 每条「先做」的理由（一句话）

- **1+7 先做**：它是唯一「不修就一直付利息」的门；而且本批 8 笔已经证明——新机制写成测试函数不会自己开始跑。
- **5 第二**：同一处文档落点、零代码、清掉一条对外承诺；顺手做最省。
- **6 与 2A 并列第三**：都是「3 行以内的正确性修正」，风险高于第 4 项但成本低于第 3 项。
- **4 第四**：成本低、收益是「未来每个会话」，但没有正确性风险，所以不抢在 6/2A 前面。
- **2B/2C 第五**：结构债，做大之前先把守卫棘轮装上（2A 一起），否则做一半又漂。
- **3 最后**：成本最高、风险最低；且它的第一步依赖 2C，天然排后。
- **8 挂起**：没环境时唯一的动作是「把清单放进 runbook」，不需要排期。

### 9.4 验收判据（不动代码即可观测）

1. 连续 10 个活跃日，`git log --pretty=format:'%s' | grep -cE '清障|计数|基线|回正|锚'` 的日增 ≤2；
2. 连续 5 个批次，推送前 preflight 零红（CI 日志可证）；
3. `docs/map` / `shared/gates.md` / `DESIGN.md` 不再出现在 fix 类提交 Top10；
4. D100 行（`DESIGN.md:569`）的「留待 CI」有明确兑现物可指（CI 那一步 + closeout 那一行）。

---

## 10. 需维护者拍板的取舍

| # | 取舍 | 选项 | 建议 | 不拍板的后果 |
|---|---|---|---|---|
| **A** | D100 的「CI 一起落」算不算兑现 | ① 只加 CI 的 3 文件 step + closeout 一行（不改 D100）；② 装 git hook（等于推翻 D100 的「不上」）；③ 加分支保护 required check | **①** | 第 1 项无法收口；若选 ② 必须新开裁决行，不能夹在实现提交里 |
| **B** | 两份 changelog 谁权威 | ① `CHANGELOG.md` 唯一权威，`docs/guide/changelog.md` 声明为面向读者的摘要；② 维持双写，只把 guard 判据从「各加一行」改为「同版本段条目集合一致」；③ 合并成一份 | **①**（迁移成本最低，不动站点） | 第 5 项只能搬文件，不能声明语义；读者继续不知道信哪份 |
| **C** | `prototype` 缺省归因的切点 | ① 以 `2026-09-27`（E1）为界，之后归 `unknown`；② 保留 `prototype` 一个版本周期，下个 beta 再切；③ 不切，只在文档声明 | **①**（代码侧 3 行；②会让「统计口径悄悄错」再续一个周期） | 第 6 项只能停留在文档声明 |
| **D** | 批次门在哪个时点跑 | ① 本地 push 前（纪律）+ CI 兜底；② 只在 CI（推后才发现）；③ 只在发版 | **①** | 若选 ②/③，第 1 项的「发现点前移」收益减半 |

---

## 11. 无法核实清单（缺什么）

| 项 | 缺的东西 | 影响 |
|---|---|---|
| 第 1 项 | 本批 8 笔是否在本地跑过全量（无提交级证据；无 CI 记录入口） | 只能说「没有可核实的证据」，不能断言「没跑」 |
| 第 1 项 | `atlas_check` 在源包内能否完整跑（审计 F7 说恒 SKIP） | 建议的 preflight 因此不用 `atlas_check`，改用 pytest 组合 |
| 第 3 项 | 14 天改动的**评审覆盖率**（无 PR 数据，审计 §1） | 只能报 diff 行数，不能报「评审看到了几成」 |
| 第 4 项 | 审计写 211 行、本次可机读 199 行 | 差 12 行的来源未定位（可能含子项/跨表行）；不影响结论 |
| 第 8 项 | 全部（环境、锁、封条、成员仓） | 只能给清单，不能给结论 |
| 全部 | 未跑任何测试/复现命令（任务约束） | 所有「应绿」都是静态推断；每条建议落地时需补一次真实执行 |

---

## 附录：本次只读取证命令

```bash
# 1) 发版门 / CI 面
grep -n "Run CLI and wiring" -A2 .github/workflows/tests.yml
sed -n '308,321p' scripts/release.py
ls tests/test_*.py | wc -l          # 81
ls .git/hooks | grep -v sample      # 空

# 2) 分层 / 重复实现
grep -rn 'load_module("validate_' _support/*.py
grep -rn "def _git(" --include='*.py' .
grep -rn "def semver_lt" --include='*.py' .

# 3) 单体
wc -l _support/solution.py
grep -n "^# ---" _support/solution.py
git log --since='2026-11-03' --numstat --pretty=format:'' -- _support/solution.py | awk '{a+=$1;d+=$2} END {print a,d}'

# 4) 决策台账
awk 'NR>=458 && NR<=680 && /^\| *D[0-9]/ {c++} END {print c}' DESIGN.md
sed -n '460p' DESIGN.md

# 5) changelog guard
ls scripts/changelog_guard.py tests/changelog_guard.py
sed -n '568,569p' install.py
python3 -c "import json;print(json.load(open('package.json'))['files'])"

# 6) prototype
grep -n '"prototype"' scripts/e2e_console.py _support/solution_e2e.py

# 7) preflight
grep -rn "preflight" scripts/ shared/ | grep -v preflight_test
```

只读声明：以上均为无副作用命令；未执行测试套件、未启动浏览器、未修改任何被审文件、未做 git 写操作。
