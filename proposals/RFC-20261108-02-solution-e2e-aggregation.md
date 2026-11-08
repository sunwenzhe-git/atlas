# 多仓方案层 E2E：父仓持跨仓 E2E + 只读聚合视图（方案待评审）

> 提案编号：RFC-20261108-02
> 提案作者：Atlas 方案会话（待维护者指派独立评审）
> 关联状态：草案（Draft）｜**方案待评审**（未实现、未提交、未发版）
> 方向：**A —— 父仓持跨仓 E2E；聚合只做只读视图；分两期**
> 本轮：第五轮硬冲突定案（`stale`/`legacy` 按父仓模式分支、`成员依赖` 空值写法；见 §0.4）
> 上游缺陷：GitHub issue `#56` `[design-conflict] 多仓方案层 E2E 资产归属与聚合契约未定义`（open，2026-11-08）
> 台账指针：本仓 `duty-review/bugs.md` 的 `#56` 指向另一条记录（见该文件）；本方案不修改、不覆盖、不重编号、不复述其状态。
> 关联：`RFC-20261104-02` §2.1.2 / §2.1.9；`shared/solution.md`；`shared/layout.md` §5；`rings/e2e/reference.md` §10.1 / §12；`shared/gates.md`
> 本轮边界：**只改方案文档**，不改实现代码、不提交、不 push、不发版；`duty-review/bugs.md` 的既有记录不动。

---

## 0. 结论摘要

- **真实缺陷不是「归属未定义」，而是「既有归属已经是父仓持 E2E，但实现从未落地，且 `shared/solution.md:5` 漂移」。** `solution init` 早已创建 `<assets_root>/e2e/cases`、`<assets_root>/e2e/scripts`，solution stack-profile 也早已写入 `e2e.cases_dir/index/scripts_dir`（`_support/solution.py:897-905`、`:909-914`）；但 `solution init` 不创建 `e2e-index.md`，父仓控制台无法启动，选择器、逐成员 provenance、父仓 N/A 门都没有接上。因此现状是「只建了空目录，没建可运行的资产面」。
- **一期**：父仓持跨仓 E2E。补 `e2e-index.md` 骨架与 `solution e2e init` 迁移命令；父仓控制台以单根方式直接运行父仓跨仓用例；`requirements[].case_ids[]` 作为唯一选择器；**只有单成员需求允许 `cross_repo_e2e: none`，多成员需求必须给 `case_ids`**；父仓账本按**成员根**记录 provenance/fingerprint；父仓 `N/A` 门改为「未初始化 WARN / 已声明未落地 FAIL」。
- **二期（本轮标「未放行」）**：只读聚合视图。`atlas solution e2e status` 与父仓控制台的只读面板展示父仓跨仓用例 + 成员本地 E2E 摘要；**不接管成员执行、不回写成员索引/账本、不替代成员评审**。`review_state` 的来源按 §5.2 定案；父仓用例的 `成员依赖` **必填**（允许空列表，缺失 FAIL），只负责 `BLOCKED` 与清单校验、不承担 `stale` 粒度；存量用例用 `atlas solution e2e init --migrate` 批量补 `成员依赖:`。
- **B 已评估并否决**：三个阻断（清单闭集、init 目录冲突、选例恒绿）在 B 的形态下无法同时消解；A 通过「父仓本来就是 E2E 根」消解了前两个，通过 `case_ids` 显式选择器与空选 BLOCKED 消解第三个。
- **两期都必须回答**：改动面、机器门 vs 纪律、迁移、回滚、验收钉子。本文逐项给出。

### 0.1 第二轮评审修订要点

1. **B2 假绿**：骨架页面改 `未实现` + `覆盖就绪: 否`；H1 的 post-fix 绿**只限定为 `validate_e2e_index` / E2E 专项检查**，不宣称整个 `atlas solution check --strict` 绿（见 §3.2、§3.9、§4.5）。`--strict` 的既有语义是把锁缺失/未跟踪、版本或契约漂移、dirty、缺 URL 等一批 WARN 升 FAIL，**不是「只升 E2E 未初始化这一条」**；本方案不改变这个升级集合。
2. **B5 testid 命名空间**：父仓 `validate_testids` 在 solution 根返回 **N/A**（显式原因），不把成员合并成一个站点扫描；`validate_testids.py` 列入改动面（见 §3.7、§3.8）。
3. **B6 AC 校验归口**：把「`关联AC` 必须命中 `solution-prd.md` AC 表**定义行**」收进 `validate_e2e_index` 父仓模式；`solution check` 不再做第二套 E2E 语义门（见 §3.7）。
4. **I1**：`shared/solution.md:5` 替换文本保留第二句「资产归属的单源是 `atlas.solution.yaml` 的 `members[].assets`」（见 §6.1）。
5. **I2**：迁移明写手填 `AC-SOLUTION-NNN`，因为 `_prd_skeletons` 只换 frontmatter `domain_code`（见 §3.9）。
6. **I3**：补孤儿用例审计、存量需求行无 `case_ids` 的迁移清单、`case_ids` 的需求级挂靠规则；「跨需求禁止复用」改为**允许复用 + 显式声明**（见 §3.3、§3.9）。
7. **I7**：新增反面包「只把 `case_ids` 加进 known 集、不接选择器 ⇒ `solution check` 必须红」（见 §3.7、§4.5.4）。
8. **§4.5 位置**：留出验证落到模板要求的 §4.5；修正 H4 自相矛盾；注明新增测试在 pre-fix 代码上跑是 collection error，不是有意义的红（见 §4.5）。
9. **二期 B4**：`review_state` 改为**父仓按成员根重算、只读不落盘**；删除「父仓重算即红」的旧反向钉子（见 §5.2、§5.8）。
10. **二期成员依赖**：父仓用例增加 `成员依赖:` 字段，否则「依赖该成员 ⇒ BLOCKED」无法判定（见 §5.2、§5.4）。

### 0.2 第三轮评审处置索引

| 第三轮项 | 处置 |
|---|---|
| 一期阻断 1：B3 仍可绿 | 新增标量 `cross_repo_e2e: none` 进 known 集；每个 `requirement.id` 二选一，两者都无 ⇒ `solution check` **FAIL**（不是 WARN）；同步改 §3.3 审计措辞（见 §3.3、§3.7、§3.9、§3.10） |
| 一期阻断 2：H1 不可复现 | 选「把 H1 的绿限定为 `validate_e2e_index` / E2E 专项检查」，不宣称整个 `solution check --strict` 绿；写明评审实测的 `契约锁跟踪` / `锁/web` 两条与 E2E 无关的前置 FAIL（见 §3.2、§3.9、§4.5） |
| 一期阻断 3：§4.5 成色 | 只记「部分取证 / 未闭族」；删除「H1–H3 pre-fix 红」；如实写「目前无 pre-fix 红证」（见 §4.5.3、§4.5.5） |
| 二期阻断 4：`成员依赖` 可选 | 改为父仓用例**必填**（允许空列表），缺失 ⇒ `validate_e2e_index` 父仓模式 FAIL（见 §5.2、§5.4、§5.6、§5.7、§5.8） |
| 二期阻断 5：跨成员隔离样本 | 新增 H5：只改成员 B，成员 A 本地用例仍 `fresh`；**所有父仓用例转 `stale`**（见 §4.5.2、§4.5.5、§5.8） |
| 重要项：`--strict` 措辞 | 改为「既有 strict 会把锁/成员/版本/契约/dirty 等一批 WARN 升 FAIL」，删除「只升这一条」（见 §0.1、§3.2、§3.7、§3.9、§10） |
| 重要项：testid N/A 三条缓解 | ① 跨仓用例禁写成员 testid 或必须标注成员归属；② 成员 `app_hash` 变化必须重跑，只重签不算 `fresh`；③ §8.8 挂 QUEUE 观察行，带 owner 与期限（见 §3.5、§3.7、§8.8） |
| 重要项：AC 反向覆盖 | `e2e status --json` 输出 `parent.ac_coverage`；AC 零挂靠时 `verdict` 为 `INCOMPLETE`（见 §3.6、§5.2、§5.8） |
| 重要项：骨架反向视图 | 反向视图行必须用**空单元格**；写 `—` 会 `反向视图一致 FAIL`（见 §3.2、§3.9） |
| 重要项：I7 | 写明实现批必须**无条件接线选择器**；反面包不得用 monkeypatch 自证（见 §3.7、§3.10、§4.5.4） |
| 重要项：`validate_manifest` 边界 | 只做文法/去重/每需求单行；索引存在性、`需求` 一致性、选择器接线、共享声明放 `solution check`，避免跨文件检查被 `SolutionError` 提前抛出（见 §3.3、§3.7、§3.8） |

### 0.3 第四轮抽鉴定案

| 第四轮项 | 定案 |
|---|---|
| 1. `cross_repo_e2e: none` 收紧 | **多成员需求（同一 `requirement.id` ≥2 个 `member` 行）禁止 `none`，必须给 `case_ids`；只有单成员需求允许 `none`。** 理由是跨仓 E2E 只在 ≥2 成员时成立，单成员写 `none` 是事实陈述，不是免责。多成员写 `none` ⇒ `solution check` FAIL（新增钉子与反面包，见 §3.3、§3.9、§3.10、§4.5.4） |
| 2. `app_hash` 变化必须重跑 | **定为机器门，不降级为纪律。** `reviewed.pass` 绑定最近一次 run 的 `prov` / `run_id`；`_submit` 不得用提交时的当前值刷新 `fp.app`；`case_review_state` 比较对象改为 run-time prov。实现批必改项与反面包见 §3.5、§3.8、§3.10、§4.5.4 |
| 3. H5 期望修正 | 放弃逐例指纹：只改成员 B ⇒ **所有**父仓用例 `stale`，不依赖 B 的也不豁免；`成员依赖` 只负责 `BLOCKED` 与清单外成员 `FAIL`，不承担 stale 粒度。保留「成员 A 本地用例仍 `fresh`」这一半，用于区分父仓根与成员根（见 §3.5、§4.5.2、§4.5.5、§5.2、§5.8） |
| 4. 迁移工具 | 新增 `atlas solution e2e init --migrate`：为存量父仓用例批量补 `成员依赖:`，迁移时输出涉及清单；不跑迁移直接升级 ⇒ 存量用例全红是预期行为（见 §3.9、§5.6、§5.7、§5.8） |

### 0.4 第五轮硬冲突定案

| 第五轮项 | 定案 |
|---|---|
| A. `stale` vs `legacy` 二选一 + 作用域 | `case_review_state` **增加 solution/父仓模式分支**：父仓模式下「无 run-time `prov`」⇒ `stale`；单仓模式保持现状 ⇒ `legacy`。单仓分支逐字节等价，避免既有单仓账本集体变 `stale` 的 breaking（见 §3.5、§3.6、§3.8、§4.5.4、§5.2） |
| B. `成员依赖: []` 解析不出空列表 | 写入口径改为 **`成员依赖:`（冒号后留空）表示空列表**，`--migrate` 也只生成这个形态；解析侧把字面量 `[]` 归一为空列表以兼容手写（`parse_block` 对块键是 `append`，`[]` 会变成 `["[]"]`）。见 §3.8、§3.9、§4.5.4、§5.2、§5.6、§5.7、§5.8 |

---

## 1. 题面确认与根因（修正版）

### 1.1 真实缺陷：实现未落地 + 契约第 5 行漂移

| 证据 | 事实 |
|---|---|
| `_support/solution.py:897-905` | `solution init` 写入的 solution stack-profile 中已有 `e2e:` 段，含 `cases_dir: <assets_root>/e2e/cases`、`index: <assets_root>/e2e/e2e-index.md`、`scripts_dir: <assets_root>/e2e/scripts` |
| `_support/solution.py:909-914` | `_prd_skeletons()` 无条件创建 `<assets_root>/e2e/cases`、`<assets_root>/e2e/scripts`、`<assets_root>/reviews` |
| `_support/solution.py:934-945` | `solution-prd.md` 以 `templates/prd/domain.md` 为底生成；只替换 frontmatter `domain` / `domain_name` / `domain_code` / `date`，**AC 表行仍是模板的 `AC-<CODE>-001` 形态，不会自动变成 `AC-SOLUTION-NNN`** |
| `validators/validate_e2e_index.py:489-494` | 父仓因无 `e2e-index.md`、无分片，直接 `N/A「无索引且无分片 → 空骨架」` |
| `scripts/e2e_console.py:676-721` | 控制台 `snapshot()` 固定读 `<root>/<e2e.index>`；父仓无索引 ⇒ 「索引文件缺失」，无法启动 |
| `_support/solution.py:173-246` | 清单解析是受限闭集：**顶层标量**只认 `version/solution/mode`，**段**只认 `members/contracts/requirements`；`requirements` 行只认 `id/acs/member/task_slug/assignee/scope`；没有 `case_ids` / `cross_repo_e2e` |
| `_support/solution.py:173-180` | `parse_manifest_text` 的 docstring 仍写「requirements 只登记存在性（Phase 1 不解析）」，与实现（逐行解析 `id/acs/member/task_slug/assignee/scope`）不符；本方案不照抄这句，改动时顺手修正 docstring |
| `scripts/e2e_console.py:919` | `class Runner` 在 `:919`（不是 `:920`）；单根控制台/账本/回写/指纹都绑定 `<root>/<e2e>` |
| `templates/e2e/console/app.js:35` | `canRun = () => !!srcCfg().configured`；`app_base_url` 未配置时是 UI `configured=false`（执行按钮禁用 + 提示），不是进程 exit 3 |
| `shared/solution.md:5` | 原文两句：「本层不复制 PRD / 域事实 / E2E；它只拥有清单、锁、父级 PRD 与跨仓声明。资产归属的单源是 `atlas.solution.yaml` 的 `members[].assets`。」——第二句是 A 判归属的唯一锚点 |
| `shared/solution.md:15` | `<assets_root>/ # 父级 PRD / E2E / solution stack-profile`——与 `shared/layout.md:111` 一致，是正确落点 |

**结论**：
1. 既有设计**已经是 A**：父仓持有跨仓 E2E 目录与画像字段；成员仓保留自己的本地 E2E。归属不是未定义，而是「父仓资产面只建了目录，没建索引/入口/选择器/provenance」。
2. `shared/solution.md:5` 是漂移行；`:15` 与 `shared/layout.md:111` 一致，**只改 `:5`，不动 `:15`、不动 `layout.md:111`**。
3. 因此修复方向不是重新选归属，而是把 A 的实现补完，并把父仓 `N/A` 空骨架改为显式「未初始化 / 未落地」信号。

### 1.2 现状：父仓 / 子仓 E2E 资产、触发、评审产物

| 平面 | 资产落点 | 谁触发 | 评审产物 |
|---|---|---|---|
| 成员仓 | `<member>/<assets_root>/e2e/{e2e-index.md,cases/,scripts/,reviews/,manual.md}`；`stack-profile.yaml` 的 `e2e` 段 | 成员自己的 `atlas console` / `atlas_verify` / `e2e_trigger` | 成员 `e2e/reviews/console/events.jsonl` + `ledger.md`；成员独立审查报告；成员首跑/验收留痕 |
| solution 根 | `<assets_root>/e2e/cases`、`<assets_root>/e2e/scripts`（init 无条件建，均为空）；`<assets_root>/stack-profile.yaml` 的 `e2e` 段；**没有 `e2e-index.md`** | 无入口；`atlas console --root <solution>` 报「索引文件缺失」 | 无父仓 E2E 评审产物 |
| solution 清单 | `atlas.solution.yaml`：`version / solution / mode / members / contracts / requirements`（`assets` 是 `members[]` 字段，不是顶层键） | `atlas solution status/diff/check/lock/task` | `solution check` 只查清单/锁/PRD 骨架，不查 E2E |

- 成员本地 E2E 的账本、独立审查、执行证据都以成员根为坐标，**不属于父仓资产**。
- 父仓现有 `e2e/cases`、`e2e/scripts` 不是「误建」，而是 A 的落点；问题只是缺少索引与入口。
- 父仓没有「一个需求 → 跨仓用例集合」的选择器；`requirements[]` 只映射到成员任务卡，不映射到父仓用例。

### 1.3 为什么现状必然导致「N 个子仓 N 个控制台」

1. **E2E 环的控制台、账本、回写、指纹全部是单根契约**：`snapshot()`、`Ledger`、`Runner`、`状态` 回写都绑定 `<root>/<e2e>`（`scripts/e2e_console.py:676-721`、`:790`、`:919`）。父仓没有索引时，这个单根入口在父仓不可用。
2. **父仓 E2E 实现只到「空目录 + 画像字段」**：没有 `e2e-index.md`，没有 page 表，没有跨仓流页面，没有 `case_ids` 选择器，没有父仓账本的逐成员 provenance。
3. **`validate_e2e_index` 在父仓把「空骨架」判 `N/A`**：父仓缺失 E2E 不产生任何红/黄信号，用户只能回到成员仓逐仓启动。
4. **成员本地 E2E 与跨仓 E2E 没有职责分层**：没有契约说明「哪些用例应在父仓写、哪些留在成员」，用户只能把跨仓验收拆到成员里，逐仓 review。

**一句话**：A 的骨架已经有了，但「索引 + 入口 + 选择器 + 逐成员证据 + 父仓门」五件没接上；于是父仓无法成为跨仓 E2E 的执行面，成员仓成为唯一可用面。

### 1.4 对第一轮独立评审三个阻断的逐条回应

| 评审阻断 | 在 B 下为什么成立 | A 的消解方式 |
|---|---|---|
| 1. `e2e` 段不在 `_support/solution.py` 的 `parse_manifest_text` 闭集，落 `unknown`，`check` 只 WARN；示例还缺 `scope` | B 需要在清单里新增 top-level `e2e` 段和嵌套成员字段，解析器不支持 | **A 不新增 top-level `e2e` 段**。父仓 E2E 由既有 `<assets_root>/e2e/` 与既有 stack-profile 发现；清单只给 `requirements[]` 增加标量 `case_ids`（逗号分隔，和 `acs` 同形）与标量 `cross_repo_e2e`（唯一值 `none`），并加入解析器 known 集。所有示例都带 `scope`；`load_manifest` 可直接通过 |
| 2. `atlas solution init` 无条件建 `e2e/cases`、`e2e/scripts`，B 却把它们判 `FAIL` ⇒ 存量 solution 首次 check 即红 | B 把父仓 `e2e/` 视为「双源」，与 init 行为冲突 | **A 把这两个目录视为合法父仓资产**，不判 FAIL。init 额外补 `e2e-index.md` 骨架；存量 solution 用 `atlas solution e2e init` 幂等补齐。默认 `check` 在「未初始化」时 WARN；`--strict` 的既有语义会把锁/成员/版本/契约/dirty 等一批 WARN 升 FAIL，**不是只升这一条**。只有「清单已声明 `case_ids` 但父仓索引缺失」才直接 FAIL |
| 3. 选例不可执行：`关联AC` 在成员侧不可达，`需求` 列存量几乎全空，`selected=0` 却落回 PASS | B 依赖成员索引列做隐式选例，且合成规则不认空选 | **A 用父仓 `requirements[].case_ids[]` 显式选择器**，不依赖 `关联AC` / `需求` 列；**多成员需求必须有 `case_ids`（禁止 `none`）**，单成员需求 `case_ids` 或 `none` 二选一，两者都无 ⇒ `solution check` FAIL；`case_ids` 为空或空选 ⇒ `BLOCKED`（exit 3），永不 PASS；`skipped` / `prototype-pass` 也不能合成 PASS |

另外三条评审意见也在设计中逐条落地：`solution.md:5` 只改这一行且保留第二句；provenance/fingerprint 按成员根计算；状态词表严格使用既有闭集（见 §3.6）。

### 1.5 第二轮评审处置索引

| 评审项 | 处置落点 |
|---|---|
| B2 假绿 / `--strict` | §3.2、§3.9、§4.5.3 |
| B5 父仓 testid 命名空间 | §3.7、§3.8、§6.2 |
| B6 AC 校验归口 | §3.7 |
| I1 保留 `solution.md:5` 第二句 | §6.1 |
| I2 手填 `AC-SOLUTION-NNN` | §3.9 |
| I3 孤儿用例 / 无 `case_ids` / 挂靠 / 复用 | §3.3、§3.9 |
| I7 只加 known 集不接选择器 | §3.7、§3.10、§4.5.4 |
| §4.5 位置 / H4 矛盾 / collection error | §4.5 |
| B4 `review_state` 来源 | §5.2、§5.8 |
| 二期成员依赖字段 | §5.2、§5.4、§5.6 |
| 次要错（Runner 行号 / 顶层键 / docstring / app_base_url / index / 原 §5.1 标题（现 §6.1）/ aggregate 保留名） | §1.1、§3.9、§5.2、§6.1、§6.2 |

---

## 2. 方案选择：A（两期）；B 否决

### 2.1 A 的两期总览

| 期 | 目标 | 父仓做什么 | 父仓不做什么 |
|---|---|---|---|
| 一期 | 父仓持跨仓 E2E，单命令可跑一个需求的跨仓验收 | 父仓索引/分片/脚本/账本/控制台；`case_ids` 选择器；父仓 `N/A` 门改为显式信号；逐成员 provenance | 不迁移成员 E2E；不执行成员本地用例；不回写成员索引/账本 |
| 二期（未放行） | 只读聚合视图，父仓一次看到跨仓 + 成员本地 E2E 状态 | `atlas solution e2e status` + 父仓控制台只读面板；读取成员索引/账本并展示摘要；`review_state` 按成员根重算（只读） | 不接管成员执行；不回写成员；不替代成员评审；不新增第二套 runner |

### 2.2 B 为什么否决（不保留为并存方案）

B（成员自持 + 父仓聚合清单）在评审中触发了三个阻断，且在 B 的形态下无法同时消解：

1. **清单闭集阻断**：B 需要在 `atlas.solution.yaml` 新增 top-level `e2e` 段与 `members[].e2e` 嵌套字段；`parse_manifest_text` 只支持顶层标量与 `members/contracts/requirements` 的扁平 `- key: value`，新增段必然落 `unknown`，`solution check` 只给 WARN，聚合静默不发生。A 不新增 top-level 段，只扩 `requirements[].case_ids`，消解。
2. **init 目录阻断**：`solution init` 无条件创建 `<assets_root>/e2e/cases`、`e2e/scripts`；B 把父仓出现这两个目录判 `FAIL`，所有存量 solution 首次 `check` 即红。A 把它们定义为合法父仓资产，消解。
3. **选例恒绿阻断**：B 依赖 `关联AC`（成员侧不可达）或 `需求`（存量空）选例；`selected=0` 时合成规则只认 `FAIL/BLOCKED`，落回 `PASS`。A 用父仓 `case_ids` 显式选择器，并规定空选 `BLOCKED`，消解。

B 还有四个次生问题，A 一并避开：

- **AC 选择口径错位**：父仓用例的 AC 应是 `solution-prd.md` 的 `AC-SOLUTION-NNN`，B 依赖成员索引的 `关联AC` 会在成员侧判不可达。
- **评审词表不闭合**：B 草案使用 `fresh-passed`，不在既有四态（`unreviewed/fresh/stale/legacy`）内；A 严格使用四态。
- **provenance 错签**：B 在父仓统一计算指纹，会把成员 A 的改动签成父仓 HEAD；A 按成员根记录。
- **迁移不可回滚**：B 需要改成员/清单多处；A 的父仓 E2E 是独立目录，删目录即回滚，不碰成员账本。

---

## 3. 一期：父仓持跨仓 E2E

### 3.1 资产归属与职责边界

| 资产 | owner | 说明 |
|---|---|---|
| 父仓 `e2e-index.md` / `cases/` / `scripts/` / `reviews/console/` / `manual.md` | **solution（父仓）** | 只放**跨仓 E2E**；由父仓控制台执行、父仓账本留痕 |
| 成员本地 `e2e-index.md` / `cases/` / `scripts/` / `reviews/` | **成员** | 既有资产不迁移；父仓不执行、不回写、不重签 |
| 父仓 `stack-profile.yaml` 的 `e2e` 段 | **solution** | 父仓作为 E2E 根的运行画像：`app_base_url` = 跨仓入口网关；`node_modules` / `reset` 为必需基础项；跨仓流如需登录 / 播种 / 打桩，按 `shared/stack-profile.md` 的 `app_login` / `seed` / `mock` 子段由项目自行声明。`solution init` 当前只写基础字段，缺失子段按既有 `not_ready` / WARN 语义处理，不静默补默认 |
| 成员 `stack-profile.yaml` 的 `e2e` 段 | **成员** | 只在二期只读视图中被读取，父仓不复制 |
| `requirements[].case_ids` / `cross_repo_e2e` | **solution** | 父仓跨仓用例的显式选择器；不指向成员用例。`cross_repo_e2e: none` 是显式 opt-out（本需求没有跨仓 E2E） |
| 成员本地用例与账本 | **成员** | 二期只读展示，父仓不接管 |

**跨仓用例的落点**：跨仓 E2E 用例正文、分片、脚本、账本全部在父仓 `<assets_root>/e2e/`。成员只提供被测应用、契约与自己的本地 E2E。这样「一个需求的跨仓验收」在父仓一次执行、一次 review；成员本地 E2E 仍是成员自己的开发回路。

**环境前提**：一期只支持**经统一入口网关的同源跨仓流**。父仓 `stack-profile.yaml` 的 `e2e.app_base_url` 指向该网关；跨仓步骤通过网关路由到各成员应用。多 host 直连、每成员一个 `app_base_url` 不在本期（见 §7、§8）。这是 A 一期的硬边界，必须写进实施前置条件。

### 3.2 父仓 E2E 落点与虚拟页

```text
<solution>/<assets_root>/e2e/
├── e2e-index.md                 # 父仓跨仓 E2E 唯一入口
├── cases/solution-flow.md       # 跨仓用例分片
├── scripts/solution-flow.spec.ts# 生成物
├── reviews/console/             # 父仓控制台账本（既有单根契约）
├── reviews/aggregate/           # 二期只读快照保留名（见 §6.2）
├── manual.md                    # 跨仓手工项
└── fixtures/                    # 可选：网关/数据夹具
```

父仓索引沿用既有 `MAIN_COLUMNS` / 页面表 / 反向视图，不新增列。跨仓用例使用一个**虚拟页** `solution-flow`：

| 用例ID | 页面 | 中文标题 | 类型 | 关联AC | 需求 | 状态 | 状态原因 | 分片 |
|---|---|---|---|---|---|---|---|---|
| `E2E-SOLUTION-FLOW-001` | `solution-flow` | 跨仓下单到履约 | `acceptance` | `AC-SOLUTION-001` | `REQ-001` | `red` | | `cases/solution-flow.md#e2e-solution-flow-001` |

页面表（**骨架必须写 `未实现` + `覆盖就绪: 否`**）：

| 页面 | 路由 | 域 | 实现状态 | 覆盖就绪（可选） |
|---|---|---|---|---|
| `solution-flow` | `/` | `solution` | `未实现` | `否` |

- `solution-flow` 是「跨仓流」的虚拟页，不是某个成员的真实页面；路由 `/` 表示从入口网关根进入。它的作用是让既有 E2E 索引/AC 反向覆盖/页面表校验有合法坐标，**不声称父仓拥有真实页面**。
- 分片 `pages: [solution-flow]` 只登记这个虚拟页；实际穿越的成员页面写在用例步骤正文里。**成员页面级 `pages[]` 追溯不在父仓索引里表达**（见 §7 边界）；二期只读视图按成员索引单独展示页面级状态。
- 跨仓用例 ID 使用 `E2E-SOLUTION-FLOW-NNN`，页面 slug 大写为 `SOLUTION-FLOW`，符合既有 `E2E-<PAGE>-NNN` 文法。
- `关联AC` 必须是 `solution-prd.md` AC 表中的 `AC-SOLUTION-NNN`**定义行**；父仓 `prd_dir` 已包含 `solution-prd.md`。可达校验归 `validate_e2e_index` 父仓模式（见 §3.7），不是整份 PRD 子串包含。

**B2 假绿为什么这样修**：
- `validate_e2e_index` 的 `AC 反向覆盖` 只对「页面全部 `已实现`，或 `覆盖就绪: 是`」的域执行（`validators/validate_e2e_index.py:714-729`、`:761-784`）。骨架若把虚拟页写成 `已实现`/`是`，`solution` 域立即进入 AC 反向覆盖；`solution-prd` 里的 AC 尚未全部挂靠时必然出 `[WARN] AC 反向覆盖 —— 覆盖就绪域零挂靠=...`。这条 WARN 不由 `atlas solution check --strict` 清除（它不运行 `validate_e2e_index`），所以不能宣称父仓 E2E 整体绿。
- 因此骨架写 `未实现` + `覆盖就绪: 否`：AC 反向覆盖跳过 `solution` 域，H1 的 post-fix 绿才真的成立。用户真正写好跨仓用例、逐条挂靠 AC 后，再手工把页面改为 `已实现` / `覆盖就绪: 是`；此时若仍有零挂靠 AC，保持既有 WARN，不冒充绿。
- **`--strict` 措辞（第三轮修正）**：既有 `atlas solution check --strict` 会把锁缺失/锁未跟踪、版本或契约漂移、dirty、缺 URL、成员状态等一批既有 WARN 升为 FAIL（见 `_support/solution.py` 模块 docstring）。它**不是**「只升父仓 E2E 未初始化这一条」。本方案不改变 `--strict` 的既有升级集合，也不新增「只升 E2E」的例外；父仓 E2E 未初始化在默认 `check` 下是 WARN，在 `--strict` 下会随既有集合一起升 FAIL，仅此而已。
- **命令边界（H1 口径）**：`validate_e2e_index` 由 `atlas_check` 调用，没有 `--strict` 旗标；`AC 反向覆盖` 是 `validate_e2e_index` 的 WARN，不在 `solution check --strict` 的升级面。H1 的 post-fix 绿**只限定为 `validate_e2e_index` / E2E 专项检查**（无「未初始化」WARN、结构门全 PASS），**不宣称整个 `atlas solution check --strict` 绿**。
- **「E2E 专项检查」定义**：指 `solution check` 输出中的 E2E 段（每需求二选一、索引存在、`case_ids` 引用存在、选择器接线、索引 `需求` 一致性、孤儿审计），**不含**锁缺失/未跟踪、成员 URL/状态、版本或契约漂移、dirty 等既有前置。H1 只判这一段。
- **干净 `solution init` 样本的已知前置 FAIL**：评审实测表明，即使父仓 E2E 相关项全 PASS，`atlas solution check --strict` 仍会因两条与 E2E 无关的前置而 FAIL：`契约锁跟踪`（`atlas.solution.lock.json` 未被父仓 Git 跟踪）与 `锁/web`（清单与锁都没有成员 `url`）。H1 不把它们算作 E2E 失败，也不要求实现批去消除它们；H1 的判定只看 E2E 专项检查。要把整个 `--strict` 跑到绿，必须另行满足「锁已提交、成员 URL 已填、PRD 非模板」等前置，本文不把这些前置混入 H1。
- **骨架反向视图必须用空单元格**：`solution e2e init` 写的反向视图行，`断言落点用例` / `链路经过用例` 两列必须是**空单元格**；写 `—`、`-`、`N/A` 等占位符会被 `validate_e2e_index` 判 `反向视图一致 FAIL`。骨架只写页面名，不写占位符。

### 3.3 清单选择器：`requirements[].case_ids[]` 与显式 `cross_repo_e2e: none`

**不新增 top-level `e2e` 段**。父仓 E2E 是否启用，由「父仓 `e2e-index.md` 是否存在 + 是否有 `case_ids` 声明」共同决定；不需要清单开关，避免落进 `unknown`。

**选择器要求（第四轮收紧，按 `requirement.id` 聚合）**：
- **多成员需求**（同一 `requirement.id` 出现 ≥2 个 `member` 行）：**必须给 `case_ids`**。禁止写 `cross_repo_e2e: none`；写了 ⇒ `atlas solution check` **FAIL**。理由：跨仓 E2E 这个概念只在 ≥2 成员时成立；多成员需求写 `none` 等于把「被迫开多个控制台」重新合法化。
- **单成员需求**（只有 1 个 `member` 行）：二选一——给 `case_ids`，或显式写 `cross_repo_e2e: none` 声明本需求没有父仓跨仓 E2E。单成员的 `none` 是事实陈述，不是免责。
- 两者都无 ⇒ `atlas solution check` **FAIL（不是 WARN）**。这条规则按 `id` 聚合，不按 `member` 聚合。

**`cross_repo_e2e: none` 不是万能 opt-out**：它只在单成员需求合法。多成员需求必须回到 `case_ids`，让父仓一次执行、一次 review；不允许用 `none` 把多控制台问题藏掉。

清单示例（每个 `requirements[]` 行都必须有 `scope`，否则 `load_manifest` 直接报错）：

```yaml
version: 1
solution: 订单履约方案
mode: federated

members:
  - name: web
    path: web
    assets: member
    kind: frontend
  - name: api
    path: api
    assets: member
    kind: backend

contracts:
  - id: order-api
    producer: api
    producer_path: contracts/order-api.yaml
    consumer: web
    consumer_path: src/contracts/order-api.yaml

requirements:
  - id: REQ-001
    acs: AC-SOLUTION-001,AC-SOLUTION-002
    member: web
    task_slug: req-001-web
    scope: 下单到履约的跨仓主链路
    case_ids: E2E-SOLUTION-FLOW-001,E2E-SOLUTION-FLOW-002
  - id: REQ-001
    acs: AC-SOLUTION-001
    member: api
    task_slug: req-001-api
    scope: 下单接口与履约事件
  - id: REQ-002
    acs: AC-SOLUTION-003
    member: api
    task_slug: req-002-api
    scope: 库存回滚接口
    cross_repo_e2e: none          # 显式声明：本需求没有父仓跨仓 E2E
```

字段与约束：

| 字段 | 必需 | 语义 / 约束 |
|---|---|---|
| `case_ids` | 二选一之一（多成员需求：必需） | 逗号 / 顿号分隔的父仓用例 ID；每项必须匹配 `_support/case_id.py::GRAMMAR`；必须存在于父仓 `e2e-index.md` 主表；同一需求内不得重复；不得指向成员索引 |
| `case_ids` 挂靠 | — | **`case_ids` 是需求级属性，不是成员级属性**。同一 `requirement.id` 的多行成员任务中，最多一行携带 `case_ids`；携带行的 `member` 仍是任务 owner，**不代表该用例只测该成员**。校验按 `id` 聚合，不按 `member` 聚合；出现两行 ⇒ `SolutionError`（exit 2，选择器歧义） |
| `cross_repo_e2e` | 二选一之一（**仅单成员需求**） | 标量，唯一合法值 `none`（进 `requirements` known 集）。显式声明该需求没有父仓跨仓 E2E。同一 `requirement.id` 最多一行携带，且不得与 `case_ids` 同时出现；非 `none` 值 ⇒ `SolutionError`（exit 2）；与 `case_ids` 同时出现 ⇒ `SolutionError`（exit 2，清单冲突）。**同一 `requirement.id` 有 ≥2 个 `member` 行时写 `none` ⇒ `solution check` FAIL（不是 `SolutionError`，便于结构化报错）** |
| 选择器要求（按 `requirement.id` 聚合） | **必需** | **多成员需求**：必须任一成员行有 `case_ids`；写 `none` 或两者都无 ⇒ `atlas solution check` FAIL（exit 1）。**单成员需求**：`case_ids` 或 `cross_repo_e2e: none` 二选一；两者都无 ⇒ FAIL。这一条不在 `validate_manifest` 里抛 `SolutionError`，以免清单加载被提前打断 |
| 跨需求复用 | — | **允许**：同一父仓用例可被多个需求引用。复用时该用例的索引 `需求` 列必须列出全部消费方（逗号分隔，如 `REQ-001,REQ-002`）；`需求` 列与清单的声明一致性是**跨文件检查**，归 `solution check`（不是 `validate_manifest`），不一致 ⇒ `FAIL`。二期启用 `成员依赖` 后，还要求它覆盖这些需求的并集。理由：禁止复用会迫使同一跨仓流为每个需求复制一份用例，副本一漂移就产生假绿；允许复用 + 显式声明把「共享」变成可审计事实 |
| `case_ids` 为空 / 缺失 | — | `case_ids` 为空串（`case_ids:` 后无值）⇒ 运行期 `BLOCKED`（不是 PASS）。**多成员需求**缺 `case_ids`（含写 `none`）⇒ `solution check` FAIL；**单成员需求**既无 `case_ids` 也无 `none` ⇒ FAIL。单成员显式 `cross_repo_e2e: none` ⇒ `e2e status --requirement` 返回 `N/A`（exit 0）并注明「显式声明无跨仓 E2E」，不是 PASS、也不是 BLOCKED |
| `acs` | 既有 | 仍必须是 `solution-prd.md` AC 表定义行；它只做追溯，**不参与选例** |
| `需求` 列 | 既有 | 父仓索引可填 `REQ-001` 供人读，但**不参与选例**；选例唯一真相是 `case_ids`。共享用例必须列全消费方，一致性由 `solution check` 校验 |

解析器改造（**边界按第三轮修正**）：

- `parse_manifest_text` 的 `requirements` known 集加入 `case_ids`（标量，逗号/顿号分隔，与 `acs` 同形）与 `cross_repo_e2e`（标量）。
- `validate_manifest` **只做文法 / 去重 / 每需求单行 / 互斥**：`case_ids` 文法、`cross_repo_e2e` 只能是 `none`、同一 `requirement.id` 最多一行 `case_ids`、最多一行 `cross_repo_e2e`、两者不得同时出现；非法 ⇒ `SolutionError`（`solution check` 退出码 2）。
- **`validate_manifest` 不做跨文件检查**：父仓索引是否存在、`case_ids` 是否真实存在、索引 `需求` 列是否与清单一致、选择器是否接线，全部放 `solution check`（exit 1）。理由：跨文件检查需要读索引，若在 `validate_manifest` 抛 `SolutionError`，`solution check` 会在加载清单时提前退出，拿不到结构化 FAIL，也无法继续检查其它项。
- 选择器满足性判定放 `solution check` FAIL，不放 `validate_manifest`：多成员需求必须有 `case_ids`（写 `none` 也算缺失）；单成员需求 `case_ids` 或 `none` 二选一。`validate_manifest` 只保证「如果写了，文法是对的」；「多成员不得 `none` / 单成员必须二选一」是检查层语义。
- 复用 `_support/case_id.py::GRAMMAR`，把 `_support/solution.py` 登记进 `CONSUMERS`（`tests/test_tools.py` 普查钉会咬）。
- 示例清单必须带 `scope`；`solution init` 生成的样板也带 `scope`，不再出现「示例本身 load 不了」。
- 顺手修正 `parse_manifest_text` 的 docstring「requirements 只登记存在性（Phase 1 不解析）」；它与实现不符，本方案不照抄。

**孤儿用例审计（I3）**：一期由 `atlas solution check --json` 的 E2E 段输出、二期由 `atlas solution e2e status --json` 输出两个只读审计集：
- `orphan_cases`：父仓索引里存在、但没有任何 `case_ids` 指向的用例 ⇒ `WARN` + 清单；不自动删、不判 FAIL（可能是草稿或暂未挂需求的用例），但迁移清单必须逐条处理。
- `requirements_without_case_ids`：存量 `requirements[]` 中**选择器不满足**的需求 ⇒ 审计清单。判定口径（第四轮收紧）：**多成员需求**没有 `case_ids`（无论是否写了 `none`）⇒ 进清单并 `solution check` FAIL；**单成员需求**既无 `case_ids` 也无 `cross_repo_e2e: none` ⇒ 进清单并 FAIL。**单成员需求的 `cross_repo_e2e: none` 不进清单**（它是合法事实陈述）。迁移时逐条处理：补 `case_ids`，或仅单成员需求可写 `none`。

### 3.4 父仓单命令入口

```bash
# 父仓跨仓 E2E 的唯一执行入口：在 solution 根执行，--root 解析到父仓 E2E
atlas console --root <solution> --requirement REQ-001

# 存量 solution 补齐父仓 E2E 索引（幂等；不迁移成员资产）
atlas solution e2e init

# 状态：一期最小 --requirement；二期完整只读盘点（不执行、不写盘）
atlas solution e2e status [--requirement REQ-001] [--json]
```

- `atlas console --root <solution>` 走既有单根路径：`snapshot()` 读父仓 `e2e-index.md` / `cases/`，`Ledger` 写父仓 `e2e/reviews/console/`，`Runner` 跑父仓 `e2e/scripts/`。**不需要多根 runner**。
- **一期最小状态入口**：`atlas solution e2e status --requirement REQ-xxx` 只读父仓，输出选择器命中数 / `BLOCKED` / `N/A` 与 exit code；完整聚合 JSON（成员摘要、`parent.ac_coverage`）在二期。二者共用同一选择器内核，不新增第二套 runner。
- `--requirement REQ-001` 只做一件事：按 `case_ids` 过滤父仓用例；不读成员索引，不执行成员用例。
- `case_ids` 为空 / 引用了不存在的 ID ⇒ 控制台显示 `BLOCKED` 横幅，`atlas solution e2e status` 返回 exit 3 / 1；**不允许退化成「跑全部」或 `PASS`**。整个需求既无 `case_ids` 也无 `cross_repo_e2e: none` ⇒ `solution check` 已 FAIL，控制台同样 `BLOCKED`。**仅单成员需求**显式 `cross_repo_e2e: none` ⇒ 父仓控制台 `--requirement` 显示 `N/A` 横幅（不启动 runner），`atlas solution e2e status --requirement` 返回 `N/A`（exit 0），不进入执行面；**多成员需求**写 `none` ⇒ `solution check` FAIL，控制台按 `BLOCKED` 处理，不显示 `N/A`。
- 父仓 `atlas console` 不提供「切换到成员执行」的入口；成员本地用例仍由成员自己的 `atlas console` 执行。这是 A 一期的职责边界。

### 3.5 结果、证据与逐成员 provenance

父仓控制台账本沿用既有 `events.jsonl` + `ledger.md`，但事件里的 provenance 必须按成员根计算，**不能把成员 A 的改动签成父仓 HEAD**（对应 `scripts/e2e_console.py:502` / `:452`）。

父仓事件新增结构：

```json
{
  "kind": "submit",
  "case": "E2E-SOLUTION-FLOW-001",
  "provenance": {
    "parent": {
      "head": "<solution HEAD>",
      "git_dirty": false,
      "scripts_hash": "<父仓 E2E scripts 指纹>"
    },
    "members": [
      {
        "name": "web",
        "path": "web",
        "head": "<web HEAD>",
        "git_dirty": false,
        "app_hash": "<web 应用内容指纹>",
        "index_sha256": "<web 本地 e2e-index.md 哈希>"
      },
      {
        "name": "api",
        "path": "api",
        "head": "<api HEAD>",
        "git_dirty": false,
        "app_hash": "<api 应用内容指纹>",
        "index_sha256": "<api 本地 e2e-index.md 哈希>"
      }
    ]
  }
}
```

规则：

- 父仓用例的 review fingerprint = 父仓脚本/分片指纹 + **全部成员的 `app_hash`**。任一成员应用内容变化 ⇒ **全部父仓用例 `stale`**；不做逐例 `成员依赖` 粒度豁免，`成员依赖` 只负责 `BLOCKED` 与清单校验（见 §5.2）。
- **`app_hash` 变化必须重跑（第四轮定为机器门，不降级为纪律）**：`reviewed.pass` 必须绑定最近一次 run 的 `prov` / `run_id`，而不是提交时的工作区当前值。具体实现约束：
  - `Runner._run` 的 `done` 事件携带 run-time `prov`（含 `run_id`、`app_hash`、逐用例 `fp`），由控制台随该次结果保存，并在 `_submit` 原样回传；
  - `_submit` 对 `reviewed.pass` 的用例**不得**用 `review_fingerprint(root)` 的当前值刷新 `fp.app`；`_compact` 取 `entry.prov`（run-time），不是 `current`；
  - `case_review_state` 的比较对象改为「`reviewed.prov.fp` vs 当前指纹」；**父仓模式下**`reviewed.pass` 没有 run-time `prov` ⇒ `stale`（fail-closed），不是 `fresh`；**单仓模式保持现状**（无 prov ⇒ `legacy`，既有行为逐字节不变）；
  - 成员应用内容变了，**父仓模式下**只重新勾选评审通过（重签）**不算 `fresh`**，必须重跑；重跑前旧 `reviewed.pass` 一律 `stale`。
- **重跑绑定反例**：先在旧 `app_hash` 上 run + 评审通过，再改成员应用，然后只点「提交」不重跑 ⇒ 必须仍 `stale`。若提交时用当前值刷新 `fp.app`，这条会假绿，属于实现批必咬反面包。
- `app_hash` 按成员根用既有 `app_fingerprint(member)` 计算（`scripts/e2e_console.py:452`），不复制成员源码、不在父仓重算成单一哈希。
- `repo_provenance(root)`（`:502`）在 solution 根扩展为 `parent + members[]`；单仓根保持原返回形状，逐字节不变。
- 成员本地账本的 provenance 仍由成员自己的控制台写入；父仓二期只读展示，**不重算、不重签、不覆盖**。
- 父仓证据只落父仓 `.atlas-evidence/<run-id>/`；成员证据留在成员根，二期只引用路径。

### 3.6 状态词表与合成规则（闭合，无新词）

**执行状态**严格使用既有闭集：`red` / `prototype-pass` / `green` / `blocked` / `skipped`。

**评审状态**严格使用既有四态（`scripts/e2e_console.py:520-535`）：

| 状态 | 定义 |
|---|---|
| `unreviewed` | 尚未标记评审通过 |
| `fresh` | 评审指纹与当前内容一致（有效评审） |
| `stale` | 评审后脚本块 / 文件内共享代码 / 共享脚本 / 应用代码变化；**父仓模式下，`reviewed.pass` 无 run-time `prov` 也归 `stale`**（fail-closed） |
| `legacy` | 历史账本条目无可用指纹，来源无法验证（**仅单仓模式**；父仓模式同一条件走 `stale`） |

**不引入 `fresh-passed`、`passed`、`skipped-review` 等新词。** 评审是否通过用 `reviewed.pass` 布尔字段表达；状态只用上述四态。

合成规则（父仓 `atlas solution e2e status` / 控制台横幅共用同一内核）：

| 条件 | `run_verdict` |
|---|---|
| **单成员需求**显式 `cross_repo_e2e: none` | **`N/A`**（exit 0），注明「显式声明无跨仓 E2E」；不是 PASS，也不进入执行面。多成员需求写 `none` 已在 `solution check` FAIL，不进此表 |
| `selected == 0`（`case_ids` 为空 / 过滤后为空） | **`BLOCKED`**（exit 3），不是 PASS |
| 任一选中用例 `red` | `FAIL`（exit 1） |
| 无 `red`，但有 `blocked` / `skipped` / `prototype-pass` | `BLOCKED`（exit 3）；`prototype-pass` 不算验收绿 |
| 全部选中用例 `green` | `PASS` |

| 条件 | `review_verdict` |
|---|---|
| 全部选中且非 `blocked/skipped` 的用例 `review_state == fresh` | `PASS` |
| 任一 `unreviewed` / `stale` / `legacy` | `INCOMPLETE` |
| 父仓账本与用例集合对不上（缺条 / 序号重复 / 指纹缺失） | `FAIL` |

**AC 反向覆盖进 `verdict`（第三轮补）**：`AC 反向覆盖` 的 WARN 不在 `solution check` 检查面里，不能靠 `--strict` 或 `solution check` 表达。因此 `atlas solution e2e status --json` 必须输出 `parent.ac_coverage`（`ac_total` / `attached` / `zero_attached[]`）；当父仓域已 `覆盖就绪`（页面 `已实现` 或 `覆盖就绪: 是`）且存在零挂靠 AC 时，`verdict` 记为 **`INCOMPLETE`**，不得显示为 PASS。骨架 `未实现` / `覆盖就绪: 否` 时 `ac_coverage` 标 `not_ready`，不参与 `verdict`。

**一期口径**：一期不新增 `solution check` 的 AC 覆盖门；一期的 AC 覆盖信号仍只看 `validate_e2e_index` 的 WARN（`atlas_check`）。`parent.ac_coverage` 随二期 `e2e status` 提供；二期之前不得把「`solution check` 绿」解释为 AC 全覆盖。

`verdict` = `FAIL` > `BLOCKED` > `INCOMPLETE` > `PASS` 的最高严重度；`INCOMPLETE` 与 `N/A` 都不能显示为绿。

### 3.7 机器门 vs 纪律（一期）

**父仓模式判定**：`--root` 下存在 `atlas.solution.yaml` 且清单 `mode: federated` ⇒ 父仓模式；单仓无清单 ⇒ 旧行为，逐字节不变。`validate_testids` 的 N/A 只在这个条件下触发；`--root` 指向 `.atlas` 或单仓根时仍按 `stack-profile.apps` 正常扫描。

| 环节 | 机器门 | 纪律 |
|---|---|---|
| `case_ids` / `cross_repo_e2e` 文法、去重、每需求单行、互斥 | ✅ `validate_manifest`，非法 exit 2（只做清单内检查，不读索引） | — |
| 选择器要求（多成员必须 `case_ids`；单成员二选一） | ✅ `solution check` **FAIL（exit 1，不是 WARN）**；多成员写 `none` 或缺 `case_ids` ⇒ 红；单成员两者都无 ⇒ 红；单成员显式 `none` 合法 | 迁移逐条补选择器；仅单成员可 opt-out |
| `case_ids` 指向父仓索引中真实存在的用例 | ✅ `solution check` / `e2e status`（跨文件检查，不在 `validate_manifest`） | — |
| `case_ids` 已声明但选择器未接线 | ✅ `solution check` **FAIL**：发现任一 `case_ids` 就必须调用选择器内核并校验 `selected` 集合；内核缺失 / 未接线 / 清单非空但内核返回空 ⇒ FAIL（见 §4.5.4 反面包 I7），不是 WARN。**实现批必须无条件接线选择器**（真实 CLI / 控制台路径），不得只在 fixture / monkeypatch 里注入。清单 `case_ids` 本身为空串 ⇒ 运行期 `BLOCKED`（不是 FAIL，也不是 PASS） | — |
| 父仓 `e2e-index.md` 存在 | ✅ `atlas solution check` 未初始化 WARN；`--strict` 会随既有升级集合把它升 FAIL（不是「只升这一条」）；`validate_e2e_index` 父仓模式输出同语义 WARN；已声明 `case_ids` 但无索引 ⇒ FAIL | — |
| 父仓索引列头 / ID 唯一 / 索引↔分片 / 页面表 / 反向视图 / 状态词表 / 状态原因 | ✅ 复用 `validate_e2e_index`；反向视图空单元格规则见 §3.2 | — |
| 父仓用例 `关联AC` 是 `solution-prd.md` AC 表**定义行** | ✅ `validate_e2e_index` 父仓模式：解析 AC 表行（复用 `:735-743` 的 `dom_acs` 提取），不是整份 PRD 子串；`solution check` 不做这条语义门 | — |
| 父仓 `validate_testids` 命名空间 | ✅ 在 solution 根返回 **N/A**。三个理由：① 父仓 `stack-profile.yaml` 的 `apps:` 把每个成员按 `path: web` 写成前端应用，合并成一个站点扫描会把跨仓同名 testid 误判为撞名；② 虚拟页 `solution-flow` 不是真实页面，标 `已实现` 会报「已实现但无对应 testid」；③ 跨仓用例的 testid 首段按 page slug 归属，会落到不存在的虚拟页。成员本地 testid 在成员根各自校验 | **N/A 的三条缓解（第三轮补）**：① 跨仓用例**禁写成员 testid**；确需断言的，必须在步骤 / `expected` 里显式标注成员归属（如「成员 `web`：testid `...`」），由评审复核，不依赖父仓自动机验；② 成员 `app_hash` 变化后必须**重跑**，只重签不算 `fresh`（见 §3.5）；③ §8.8 挂 QUEUE 观察行，带 owner 与期限 |
| `selected > 0` 且选中集 == `case_ids` | ✅ 控制台/status 同一选择器 | — |
| 孤儿用例 / 无选择器需求 | ✅ 一期 `solution check --json` 的 E2E 段、二期 `e2e status --json` 输出审计集；`orphan_cases` 只 WARN + 清单，不自动删；`requirements_without_case_ids`（既无 `case_ids` 也无 `cross_repo_e2e: none`）⇒ `solution check` FAIL | 迁移逐条确认 |
| 逐成员 provenance / `app_hash` / stale | ✅ 父仓账本与成员根对账 | — |
| 父仓账本只写父仓，成员账本不被写 | ✅ 测试对账成员账本 mtime/hash | — |
| 跨仓流是否真的端到端（不是只跑了入口页） | ❌ | ✅ 评审判断 + 用例步骤审查 |
| 网关是否代表集成环境（不是各自 dev） | ❌ | ✅ 环境纪律 / 评审确认 |
| `solution-flow` 虚拟页是否掩盖了成员页面级缺口 | ❌ | ✅ 评审判断；二期视图辅助 |
| 一个需求的跨仓用例集是否充分覆盖所有成员 | ❌ | ✅ 需求评审 / 独立审查 |

**B6 归口说明**：E2E 语义门唯一归 `validate_e2e_index`（经 `atlas_check` 调用）；`solution check` 只做**清单内 + 跨文件的一致性**（文法/去重/每需求单行/互斥在 `validate_manifest`；选择器要求缺失、引用存在、索引 `需求` 一致性、选择器接线在 `solution check`），**不再**解析 PRD AC 表。两套门语义不并存；跨文件检查不得塞回 `validate_manifest` 抛 `SolutionError`。

### 3.8 改动面（一期）

| 文件 | 改动 |
|---|---|
| `_support/solution.py` | `parse_manifest_text` 的 requirements known 集加 `case_ids` / `cross_repo_e2e`；`_manifest_text` 序列化这两个键；`validate_manifest` **只做**文法 / 去重 / 每需求单行 / 互斥；**不读索引、不做跨文件检查**；`_prd_skeletons` 增加 `e2e-index.md` 骨架（反向视图空单元格）；`_solution_profile` 已含 e2e 字段，保持；修正 `parse_manifest_text` docstring；登记 `case_id` 消费者 |
| `_support/solution_e2e.py`（新增，若评审接受） | 父仓 E2E 单源内核：读父仓索引、`case_ids` 选择、`selected=0`/缺失判定、孤儿审计、逐成员 summary；供 `atlas_solution.py` / `e2e_console.py` / 二期 status 共用，避免三处各写一遍 |
| `scripts/atlas_solution.py` | `solution e2e init`（二期含 `--migrate`，见 §5.7）；`solution check` 增加父仓 E2E 检查（**多成员需求禁 `none`、单成员二选一 FAIL**、索引存在、`case_ids` 引用存在、选择器接线、索引 `需求` 一致性、孤儿审计、N/A 改显式信号）；`solution e2e status` 二期入口（含 `parent.ac_coverage`） |
| `scripts/e2e_console.py` | `--requirement` 过滤；solution 根 provenance 扩展为 `parent + members[]`；父仓用例 fingerprint 纳入**全部成员** `app_hash`；`Runner._run` 的 `done` 事件携带 run-time `prov` / `run_id`；`_submit` / `_compact` 对 `reviewed.pass` 使用 run-time prov，**不得**刷新当前 `fp.app`；`case_review_state` **增加 solution/父仓模式分支**：父仓模式比较 run-time `prov`、无 prov ⇒ `stale`，**单仓分支逐字节等价**（无 prov 仍 `legacy`、改应用后重签仍 `fresh` 的既有语义不变）。这个分支是必须的，否则所有既有单仓账本会因无 run-time `prov` 集体变 `stale`，属于 breaking |
| `_support/case_block.py`（二期） | `_BLOCK_KEYS` 增加 `成员依赖`；解析侧把**空值**（`成员依赖:` 冒号后无内容）与字面量 `[]` 都归一为空列表；序列化空列表统一写 `成员依赖:`（不写 `[]`），避免 `parse_block` 的 `append` 语义把 `[]` 解析成 `["[]"]` |
| `validators/validate_e2e_index.py` | 增加 `require_e2e` / 父仓模式：无索引时不再 N/A，改为 WARN（未初始化）或 FAIL（已声明 case_ids 但缺资产）；父仓 `关联AC 可达` 改为 **AC 表定义行**校验；孤儿用例审计；父仓 `parent.ac_coverage` 统计（供 `e2e status` 复用）；单仓默认 N/A 语义不变 |
| `validators/validate_testids.py` | solution 根（存在 `atlas.solution.yaml`）返回 **N/A** + 原因；不把 `stack-profile.apps` 的成员合并成一个站点扫描；单仓行为不变 |
| `templates/atlas.solution.yaml` | 补 `requirements[].case_ids` 与 `cross_repo_e2e: none` 注释样板；补 `scope` 示例 |
| `shared/solution.md` | 只改 `:5`（保留第二句）；§2 表加 `case_ids` / `cross_repo_e2e`；新增「父仓跨仓 E2E」小节（虚拟页、网关、选择器、多成员禁 `none` / 单成员二选一、账本） |
| `rings/e2e/reference.md` §10.1 / §5.5 | solution 根是合法 E2E 根；`solution-flow` 虚拟页；跨仓用例 `pages[]` 只登记虚拟页；网关前提；反向视图空单元格；`reviews/aggregate/` 登记为保留名；二期 `成员依赖` 必填字段 |
| `shared/gates.md` | 登记「solution 跨仓 E2E（父仓索引/选择器/逐成员 provenance）」门行，六列齐全；testid 门行「不查什么」补 solution 根 N/A；同步行数 |
| `docs/map/gates.md:18` | `shared/gates.md` 行数锚值按 `test_map_anchors.py` 实际口径更新（当前地图写 175、`wc -l` 实测 174，说明锚口径与 `wc -l` 不同；不手抄第二套数字） |
| `docs/map/atlas-map.html` | 同一锚值同步；门册 `points`/`files` 文案同步 |
| `bin/atlas.js` | `solution e2e init`（含 `--migrate`）/ `solution e2e status` 子命令；`console --requirement` 选项 |
| `tests/test_solution_e2e.py`（新增） | 清单 `case_ids` / `cross_repo_e2e`、**多成员需求写 `none` ⇒ FAIL**、单成员二选一 FAIL、选择器、空选 BLOCKED、缺失 ID FAIL、`需求` 一致性（solution check）、孤儿审计、AC 表定义行、init 幂等与 `--migrate`（反向视图空单元格 / `成员依赖:` 批量补齐 / 输出清单）、父仓 N/A 改信号、逐成员 provenance、选择器未接线 FAIL（真实路径，非 monkeypatch） |
| `tests/test_e2e_console_solution.py`（新增） | 父仓控制台单根运行、`--requirement` 过滤、只写父仓账本、成员账本不变、成员 app 改动导致**全部父仓用例** stale、**重签不重跑仍 `stale`**、**run 后改 app 再提交仍 `stale`**、`cross_repo_e2e: none` 仅单成员返回 N/A、**单仓模式无 prov 仍 `legacy` / 父仓模式无 prov ⇒ `stale`** |
| `tests/test_tools.py` | `case_id` 消费者登记普查钉加入 `_support/solution.py` |
| `tests/test_map_anchors.py` | 门册行数锚更新后必须复绿 |

### 3.9 迁移与回滚（一期）

**存量 solution 迁移**（不碰成员仓）：

1. 拉取新版本后执行 `atlas solution e2e init`。它只做幂等补齐：
   - 若 `<assets_root>/e2e/e2e-index.md` 不存在，写入空骨架（主表列头 + `solution-flow` 页面行 `未实现` / `覆盖就绪: 否` + 反向视图行）；
   - **反向视图行的「断言落点用例」「链路经过用例」两列必须是空单元格**；写 `—` / `-` / `N/A` 会 `反向视图一致 FAIL`；
   - 不覆盖已有索引、不写用例、不动成员目录；
   - **二期升级前再加 `--migrate`**：为存量父仓用例批量补 `成员依赖:`（冒号后留空，不写 `[]`），见 §5.7；不跑迁移直接升级 ⇒ 存量用例全红是预期行为。
2. 打开 `<assets_root>/prd/solution-prd.md`，**手填 `AC-SOLUTION-NNN`**：`_prd_skeletons` 只替换 frontmatter 的领域字段（含 `domain_code`，`_support/solution.py:942-943`），**不改 AC 表行**，表行仍是模板继承的 `AC-<CODE>-001`；不手改 ⇒ 父仓 `关联AC` 直接不可达。父仓跨仓用例的 `关联AC` 必须指向这些定义行，仅出现在散文里不算可达。
3. 逐个 `requirement.id` 满足选择器要求（第四轮收紧）：
   - **多成员需求（≥2 个 `member` 行）：必须给 `case_ids`**（同一需求最多一行携带）；**禁止 `cross_repo_e2e: none`**，写了 ⇒ `atlas solution check` FAIL；
   - **单成员需求：二选一**——给 `case_ids`，或显式写 `cross_repo_e2e: none`；
   - 两者都不写 ⇒ `atlas solution check` FAIL，不再是「可以不加」。共享用例必须在索引 `需求` 列列出全部消费方（一致性由 `solution check` 校验）。
4. 一期跑 `atlas solution check --json`，读 E2E 段逐条处理 `orphan_cases` 与 `requirements_without_case_ids`；二期同一内核由 `atlas solution e2e status --json` 输出。
   - 孤儿用例 ⇒ 补 `case_ids` 挂到需求，或确认是草稿并保留（审计不自动删）；
   - `requirements_without_case_ids` ⇒ 按第 3 步补 `case_ids`；仅**单成员需求**可改写成 `cross_repo_e2e: none`，多成员需求不能；**每一条同时是 `solution check` FAIL**。
5. 在父仓 `stack-profile.yaml` 设置 `e2e.app_base_url` 为集成网关。未设置时：
   - 父仓控制台是 UI `configured=false`（执行按钮禁用 + 提示）；若通过 CLI 强行按需求启动，显示 `BLOCKED` 横幅，不启动 runner；
   - 二期 `atlas solution e2e status` 把「网关未配置」计入 `BLOCKED`（exit 3）。三者语义分开，不混用。
6. `atlas solution check` 在「父仓 E2E 未初始化」时 WARN；`--strict` 会随**既有升级集合**（锁缺失/未跟踪、版本或契约漂移、dirty、缺 URL、成员状态等）把它一起升 FAIL，**不是只升这一条**。但「多成员需求缺 `case_ids` / 单成员二选一缺失」和「已声明 `case_ids` 但索引缺失」在**默认 `check`** 就 FAIL，不等 `--strict`。`AC 反向覆盖` 是 `validate_e2e_index`（`atlas_check`）的 WARN，不在 `solution check --strict` 的升级面；两个命令分开看，不混成一句「全绿」。
7. **H1 的绿不要求上一条全部通过**：干净 `solution init` 样本上，`atlas solution check --strict` 仍可能因 `契约锁跟踪`（锁未提交）与 `锁/<member>`（无 `url`）等与 E2E 无关的前置 FAIL。H1 只看 `validate_e2e_index` / E2E 专项检查；要整个 `--strict` 绿，需另行提交锁、填成员 URL、替换 PRD 模板。

**成员仓**：零改动。成员本地索引/分片/脚本/账本/画像都不迁移；成员自己的 `atlas console` 行为不变。

**回滚**（父仓 E2E 是独立目录）：

1. 删除 `<assets_root>/e2e/`（父仓跨仓 E2E 资产整体消失）；
2. 从 `atlas.solution.yaml` 移除 `case_ids` 与 `cross_repo_e2e` 行；
3. 如需彻底回到旧行为，恢复 `shared/solution.md:5` 与门册行；**不碰任何成员账本/索引**。

回滚不需要 `git revert` 成员仓，不需要清理成员数据；父仓账本随目录删除，成员账本原样保留。

### 3.10 验收钉子（一期）

| 钉子 | 咬红形态 |
|---|---|
| 清单 `case_ids` 文法 / 重复 / 多行 | 非法 ID、同需求两行 `case_ids` 仍通过 ⇒ 红 |
| 多成员需求禁 `none`（B3 收紧） | 同一 `requirement.id` 有 ≥2 个 `member` 行、写 `cross_repo_e2e: none` 仍通过 ⇒ 红（必须 FAIL）；多成员缺 `case_ids` 仍 WARN/PASS ⇒ 红 |
| 单成员二选一（B3） | 单成员 `requirement.id` 既无 `case_ids` 也无 `cross_repo_e2e: none`，`solution check` 仍 WARN/PASS ⇒ 红（必须 FAIL） |
| `cross_repo_e2e` 文法 / 互斥 | 写 `cross_repo_e2e: yes` 不报错，或与 `case_ids` 同时出现仍通过 ⇒ 红 |
| 选择器空选 | `case_ids` 为空 / 过滤后为空仍 PASS ⇒ 红（必须 BLOCKED） |
| 显式 opt-out | 单成员 `cross_repo_e2e: none` 被当 PASS 或 BLOCKED ⇒ 红（必须 N/A）；多成员 `none` 被当 N/A ⇒ 红（必须 FAIL） |
| 选择器指向不存在 ID | 引用父仓索引不存在的 ID 仍通过 ⇒ 红 |
| `需求` / `关联AC` 不被当选择器 | 只改 `需求` 列就能改变选例 ⇒ 红（选例必须只认 `case_ids`） |
| 选择器未接线（I7） | 只把 `case_ids` 加进 known 集、不接选择器，`solution check` 只 WARN 或 PASS ⇒ 红（必须 FAIL）；只靠 monkeypatch / fixture 注入选择器也算未接线 ⇒ 红 |
| 父仓 N/A 门 | 父仓无索引仍返回 N/A 且无 WARN/FAIL ⇒ 红 |
| 已声明未落地 | 有 `case_ids` 但无父仓索引仍 PASS ⇒ 红 |
| AC 表定义行 | 父仓 `关联AC` 只在散文出现、不在 AC 表定义行仍 PASS ⇒ 红 |
| 父仓 testid 命名空间 | solution 根仍把成员合并扫描、同名 testid 互撞或虚拟页报「已实现但无 testid」⇒ 红（必须 N/A） |
| 孤儿用例 / 无选择器需求 | 审计集为空或漏报 ⇒ 红；`requirements_without_case_ids` 有内容但 `solution check` 不 FAIL ⇒ 红 |
| 共享用例声明 | 跨需求复用但 `需求` 列未列全消费方 ⇒ `solution check` 不红 ⇒ 红 |
| 逐成员 provenance / 重跑绑定 | 成员 A 改应用内容，任一父仓用例仍 `fresh` ⇒ 红；成员 B 账本被重签 ⇒ 红；成员 `app_hash` 变化后只重签仍显示 `fresh` ⇒ 红；run 后改成员应用、提交时刷新 `fp.app` 使 `reviewed.pass` 仍 `fresh` ⇒ 红（`reviewed.pass` 必须绑定 run-time prov / `run_id`） |
| 模式分支（第五轮） | 父仓模式下无 run-time `prov` 返回 `legacy` 或 `fresh` ⇒ 红（必须 `stale`）；单仓模式下无 run-time `prov` 返回 `stale` ⇒ 红（必须保持 `legacy`）；单仓既有账本被这次改动翻转 ⇒ 红 |
| 跨成员隔离 | 只改成员 B ⇒ **全部**父仓用例必须 `stale`；不依赖 B 的父仓用例仍 `fresh` ⇒ 红。成员 A 的**本地**用例 `review_state` 必须仍 `fresh`；用父仓根算 A 本地 `current` 把 A 拖成 `stale` ⇒ 红 |
| 迁移工具 | 存量父仓用例缺 `成员依赖` 时，`atlas solution e2e init --migrate` 不补 `成员依赖:`、不输出涉及清单，或迁移后仍 FAIL ⇒ 红；不跑迁移直接升级却未按预期全红 ⇒ 红 |
| 写边界 | 父仓控制台写成员索引/账本，或成员账本 mtime/hash 变化 ⇒ 红 |
| AC 反向覆盖 | `e2e status --json` 缺 `parent.ac_coverage` ⇒ 红；`覆盖就绪` 域零挂靠 AC 时 `verdict` 仍 PASS ⇒ 红（必须 INCOMPLETE） |
| 状态合成 | `skipped` / `prototype-pass` / `selected=0` 合成 PASS ⇒ 红；`fresh-passed` 等新词出现 ⇒ 红 |
| 单仓回归 | 单仓空骨架从 N/A 变成 FAIL，或单仓控制台输出变化 ⇒ 红 |
| 地图锚 | 门册加行后 `docs/map/gates.md:18` / `atlas-map.html` 锚值未按 `test_map_anchors` 口径更新 ⇒ 红 |

---

## 4. 验证与测试结果

> 本节按 `proposals/TEMPLATE.md` 的 §4 / §4.5 形态落。**本轮方案阶段未实跑**，结论一律标「未实跑」，不写假绿。

### 4.1 测试命令

```bash
# 一期实现批
python3 -m pytest tests/test_solution_e2e.py tests/test_e2e_console_solution.py -q
python3 -m pytest tests/test_tools.py tests/test_map_anchors.py -q
python3 -m pytest tests/ -q
python3 scripts/atlas_check.py --fast

# 二期实现批（未放行；放行后才跑）
python3 -m pytest tests/test_solution_e2e_view.py -q
```

### 4.2 本轮结果

- **未实跑**：本轮只改方案文档，没有实现代码，也没有新增测试文件；不提供假绿结果。
- 实现批必须补齐本节的实际输出（命令 + 结果），并完成 §4.5。

### 4.5 留出验证

本方案改变父仓 E2E 门控（父仓 `N/A` → 显式未初始化/未落地）、`case_ids` 选择器、`cross_repo_e2e`（多成员禁 `none` / 单成员二选一）与 AC 定义行校验，属于**系统性修复触发**，必须做留出验证。

#### 4.5.1 触发面核对

- **触发面 (b)**：改门 / 校验器 / 契约判据，diff 将落在 DR4 段级锚路径族（`validators/`、`shared/`、`rings/`、`scripts/`）。
- **本轮状态**：未改代码，无法粘贴 `git diff --name-only` 与 `scripts/closeout_derive.py` 路径族对照的原始输出；实现批必须补两条命令的原始输出（命令 + 输出，可复算），不得只写「无命中」。
- **不触发 (a)**：本文不是 `bugs.md` 同根归纳引子族，也没有 ≥3 条独立审查重复 finding 作为触发依据；触发依据是 (b)。

#### 4.5.2 留出集（不参与开发调试）

| 样本 | 形态 | 用途 |
|---|---|---|
| H1 | **干净 `solution init` 样本**：`init` 已建空 `e2e/cases`、`e2e/scripts`，无 `e2e-index.md`；锁未提交、成员 `url` 未填、`solution-prd.md` 仍是模板 | 验证父仓不再 N/A：`atlas solution check` 默认 WARN；`e2e init` 后 `validate_e2e_index` 全 PASS 且无「未初始化」WARN。**H1 的绿只限定为 `validate_e2e_index` / E2E 专项检查**；不宣称 `atlas solution check --strict` 整绿（`契约锁跟踪` / `锁/<member>` 与 E2E 无关，见 §3.2） |
| H2 | 父仓有 1 条跨仓用例 + `requirements[].case_ids` 指向它 | 验证选择器命中 1 条；控制台可执行；`selected=1` |
| H3 | 父仓有 `case_ids`，但**成员 A** 应用内容改动 | 验证**所有**父仓用例 `stale`（父仓 fingerprint 纳入全部成员 `app_hash`，不做逐例豁免）；成员 B 账本不被重签 |
| H4（对照） | 单仓空骨架（无索引/无分片） | 验证单仓仍 N/A，未被父仓 `require_e2e` 误伤；**pre-fix 绿、post-fix 绿**，不是 pre-fix 红 |
| H5（二期 · 跨成员隔离） | 父仓有两条用例：一条 `成员依赖: [web, api]`，一条 `成员依赖: [web]`；只改**成员 B（api）** 的应用内容 | 验证根隔离：成员 A（web）的**本地**用例 `review_state` 仍为 `fresh`；**所有**父仓用例转 `stale`——不依赖 B 的也不豁免（`成员依赖` 不承担 stale 粒度）。用于区分「用父仓根算 `current` 把成员 A 本地用例拖 stale」这个错误 |

#### 4.5.3 pre-fix 现状 / post-fix 目标

**pre-fix 现状（如实记，不冒充红证）**：

| 样本 | 修复前可观测到的 | 是否 pre-fix 红 |
|---|---|---|
| H1 | `python3 validators/validate_e2e_index.py --root <solution>` 输出 `N/A「无索引且无分片 → 空骨架」`；这是**静默 N/A**，不是 FAIL/WARN | **否**，没有红证 |
| H2 | 现有 `atlas solution check` / `e2e_console.py snapshot` 没有 `case_ids` 选择器；没有可执行入口产生「空选落回 PASS」的红信号 | **否**，没有信号 |
| H3 | 现有 `repo_provenance` 只给父仓 HEAD / 父仓指纹，成员 A 改动不会让父仓用例 stale；现有测试没有对应断言 | **否**，没有信号 |
| H4 | 单仓空骨架，pre-fix 与 post-fix 都应保持 N/A 绿 | **否**，对照绿 |
| H5 | 跨成员隔离在现有实现里不存在（没有 `成员依赖`），无法产生红信号 | **否**，没有信号 |

- **结论：目前无 pre-fix 红证。** 按 D156 本轮只能记「**部分取证 / 未闭族**」；不得写成闭族或红证。
- **新增测试不能制造 pre-fix 红**：直接跑 `pytest tests/test_solution_e2e.py` 在 pre-fix 代码上是 collection error（文件/导入不存在），不是有意义的红。pre-fix 只用上表既有命令/静态事实记录。
- **H1 的 `--strict` 前置**：即便 E2E 专项全 PASS，干净 `solution init` 样本的 `atlas solution check --strict` 仍会 FAIL 在 `契约锁跟踪`（锁未提交）与 `锁/web`（清单与锁都无 `url`）。这是 H1 判定的排除项，不是 E2E 红，也不能拿来充 pre-fix 红。

**post-fix 目标（未实跑，实现批补证）**：

- H1：`validate_e2e_index` 全 PASS，且无「未初始化」WARN；`solution check` 的 **E2E 专项检查**无 FAIL。**不要求整个 `atlas solution check --strict` 绿**。
- H2：`selected=1`，父仓控制台可跑 1 条。
- H3：**所有**父仓用例 `stale`；成员 B 账本哈希不变。
- H4：单仓仍 N/A。
- H5：成员 A **本地**用例 `review_state` 仍 `fresh`；**所有**父仓用例转 `stale`（不依赖 B 的也不豁免）。
- **口径**：H1 的绿 = E2E 结构可运行 + 无「未初始化」WARN，不代表 AC 全覆盖；`AC 反向覆盖` 由 `e2e status --json` 的 `parent.ac_coverage` / `INCOMPLETE` 表达（见 §3.6），不走 `solution check --strict`。

#### 4.5.4 反面包（每条都必须咬红）

1. 摘掉 `case_ids` / `cross_repo_e2e` 校验 ⇒ 非法/重复/多行仍通过 ⇒ 红。
2. 摘掉 `selected=0` 的 BLOCKED ⇒ 空选落回 PASS ⇒ 红。
3. 摘掉父仓 `require_e2e` ⇒ 父仓无索引仍 N/A ⇒ 红。
4. 摘掉「全部成员 `app_hash` 汇总」⇒ 成员 A 改动不影响父仓用例 review 态 ⇒ 红。
5. 摘掉「父仓只写父仓账本」断言 ⇒ 成员账本被写 ⇒ 红。
6. 摘掉 `skipped/prototype-pass` 的 BLOCKED 合成 ⇒ 它们被当绿 ⇒ 红。
7. 摘掉 `app.js` 成员命名空间（若二期复用草稿）⇒ 同名 `cid` 撞草稿 ⇒ 红。
8. **I7 反面包**：只把 `case_ids` 加进 `parse_manifest_text` 的 known 集、**不接选择器** ⇒ `solution check` **必须 FAIL**（不是只不 WARN、也不是 PASS）⇒ 红。实现批必须**无条件接线选择器**（真实 CLI / 控制台路径）；若反面包靠 monkeypatch / fixture 注入选择器才变红，视为未接线，反面包不成立。
9. **B6 反面包**：把父仓 `关联AC 可达` 退回整份 PRD 子串包含 ⇒ `关联AC` 只在散文出现仍 PASS ⇒ 红（必须命中 AC 表定义行）。
10. **B5 反面包**：让 solution 根重新合并扫描成员 `stack-profile.apps` ⇒ 同名 testid 互撞 / 虚拟页「已实现但无 testid」⇒ 红（必须 N/A）。
11. **B3 反面包**：同一 `requirement.id` 有 ≥2 个成员行、既无 `case_ids` 也无 `cross_repo_e2e: none`，`solution check` 仍 WARN/PASS ⇒ 红（必须 FAIL）。
12. **`cross_repo_e2e` 收紧反面包（第四轮）**：同一 `requirement.id` 有 ≥2 个成员行、写了 `cross_repo_e2e: none`、没有 `case_ids`，`solution check` 仍 WARN/PASS ⇒ 红（**多成员需求写 `none` ⇒ 必须 FAIL**）；单成员需求写 `none` 无 `case_ids` ⇒ 必须 PASS（这是合法 fact，不是免责）。
13. **跨成员隔离反面包（二期）**：把成员 `current` 改用父仓根计算 ⇒ 只改成员 B 时**成员 A 的本地用例**也转 `stale` ⇒ 红（必须仍 `fresh`）。反向：只改成员 B 时让「不依赖 B 的父仓用例」保持 `fresh` ⇒ 红（必须全部 `stale`）。
14. **重跑绑定反面包（第四轮，机器门）**：run + 评审通过后改成员应用，只点「提交」不重跑，`_submit` 用提交时当前值刷新 `fp.app` ⇒ `reviewed.pass` 仍 `fresh` ⇒ 红（必须仍 `stale`）。实现批必须改 `_submit` 与 `case_review_state` 的比较对象为 run-time `prov`；只重签不重跑不算 `fresh`。
15. **迁移反面包（第四轮）**：存量父仓用例缺 `成员依赖` 时，`atlas solution e2e init --migrate` 不补 `成员依赖:`、不输出涉及清单，或迁移后仍 FAIL ⇒ 红。
16. **模式分支反面包（第五轮，硬冲突 A）**：单仓模式下给旧账本（无 run-time `prov`）重算 `review_state` ⇒ 必须仍 `legacy`；若返回 `stale` ⇒ 红。父仓模式下同一条件 ⇒ 必须 `stale`；若返回 `legacy` 或 `fresh` ⇒ 红。单仓分支必须与改动前逐字节等价（既有「改应用后重签仍 `fresh`」样本不得翻转）。
17. **`成员依赖` 空值反面包（第五轮，硬冲突 B）**：写 `成员依赖:`（冒号后无值）⇒ 必须解析为空列表，不得判「清单外成员 ⇒ FAIL」；写 `成员依赖: []` ⇒ 必须归一为空列表（不得得到 `["[]"]`）；`--migrate` 产物必须能被自身校验直接通过。

#### 4.5.5 三态结论

- **本轮结论：部分取证 / 未闭族。** 目前无 pre-fix 红证：H1 是 N/A 静默，H2/H3/H5 是「没有信号」，H4 只是对照绿（见 §4.5.3）。
- **post-fix 期望口径（第四轮定案）**：H3 / H5 里「只改一个成员 ⇒ **所有**父仓用例 `stale`」是父仓 fingerprint 纳入全部成员 `app_hash` 的直接结果，不做逐例 `成员依赖` 豁免；`成员依赖` 只负责 `BLOCKED` 与清单外成员 `FAIL`。H5 的另一半「成员 A **本地**用例仍 `fresh`」用于证明成员根与父仓根没有被混算。
- **实现批判定**：
  - `闭族`：pre-fix 红证成立（有 FAIL/WARN 级既有命令输出，或可复算的既有断言红），H4 对照绿；post-fix 全绿；反面包全红。本轮不满足。
  - `未闭族`：任一 pre-fix 红未复现，或 post-fix 仍红，或反面包有未咬红。**本轮即此态。**
  - `单案修复（无留出集）`：若 H1–H5 任一装配样本或网关环境无法提供，不得用「单案修复」替代；必须补齐样本后重跑，或由评审确认残留风险 + QUEUE 观察行 owner / 补验期限。
- **耗时与评审**：设计 + 运行耗时、评审轮次在实现批记录；唯一判定记录 = 本节 + 其 REVIEW（不新增台账；`bugs.md` 指针行按模板只留 `- 留出验证：RFC-… / REVIEW-…`，无状态 / 无日期 / 无 `#NN`）。

#### 4.5.6 运行命令

```bash
# pre-fix：既有命令（不需要新增测试文件）
python3 validators/validate_e2e_index.py --root <solution>
python3 scripts/atlas_check.py --fast --root <solution>
python3 scripts/atlas_solution.py check --root <solution>
# 注意：H1 只取 validate_e2e_index / E2E 专项结果；
# 上面的 solution check --strict 若因「契约锁跟踪」「锁/<member>」等与 E2E 无关的前置 FAIL，
# 必须原样记录，不计入 H1 判定，也不宣称整个命令绿。

# post-fix：新增测试 + 全量（一期）
python3 -m pytest tests/test_solution_e2e.py tests/test_e2e_console_solution.py -q
python3 -m pytest tests/test_tools.py tests/test_map_anchors.py -q
python3 -m pytest tests/ -q
python3 scripts/atlas_check.py --fast

# 二期（未放行；放行后才跑）
atlas solution e2e init --migrate   # 存量父仓用例批量补 `成员依赖:`，并输出涉及清单
python3 -m pytest tests/test_solution_e2e_view.py -q
```

---

## 5. 二期：只读聚合视图（未放行）

> **本轮标「未放行」**：以下内容是待评审设计，不是已定案。B4 的 `review_state` 来源按 §5.2 / §5.4 定案；`成员依赖` 已按第三轮意见定为**必填**（允许空列表，缺失 FAIL），待评审确认后进入实现批。

### 5.1 范围

二期只做**一个只读视图**：父仓一次看到「本需求的父仓跨仓用例 + 各成员本地 E2E 摘要」。它不执行成员用例、不回写成员索引/账本、不替成员做 review。

- 父仓跨仓用例：仍然只在父仓控制台执行与 review（一期能力）。
- 成员本地 E2E：只读展示成员索引、账本里的评审事实、`stale`、`unreviewed` 数、最近提交序号；**不在父仓落盘重签**。
- 视图不产生新的 E2E 真相源；成员本地状态仍以成员 `events.jsonl` 为准。

### 5.2 数据源与字段

**B4 本轮选择（未放行，待评审）：`review_state` 由父仓按成员根重算，只读不落盘。**
- 父仓调用与成员控制台同一个 `case_review_state(cid, snap, current)`（`scripts/e2e_console.py:520-535`）；`snap` 来自成员 `events.jsonl` 的最新快照，`current` 由**成员根**的 `snapshot(member_root)` / 指纹面计算。
- 成员账本仍是唯一评审真相源：`reviewed.pass` + `prov` 不动；父仓只读 `reviewed.pass` 与 `prov`，重算 `fresh/stale/legacy/unreviewed` 展示，**不写回**成员账本/索引。
- **比较对象是 run-time `prov`（第四轮定案）**：`reviewed.pass` 绑定该用例最近一次 run 的 `prov`（含 `run_id`、`app_hash`、逐用例 `fp`）；`case_review_state` 用 `reviewed.prov.fp` 对当前指纹比较，**不得**用提交时的当前值刷新 `fp.app`。**父仓模式下**无 run-time `prov` 的旧记录按 `stale`（fail-closed）；重签不重跑不算 `fresh`。**单仓模式保持现状**：无 prov 仍 `legacy`，既有语义不变。父仓视图只读这个结果，不参与重算口径的定义。
- 更新时机：视图每次运行重算，不存储、不缓存为真相源。
- 旧反向钉子「父仓重算成员 review_state ⇒ 红」**删除**；改为「父仓把重算结果写回成员账本/索引 ⇒ 红」「父仓用父仓根（而非成员根）计算成员 `current` ⇒ 红」。

**成员索引路径不硬编码 `product`**：`members[].index` 按成员自己的 `assets_root` / `layout` / `stack-profile.yaml` 解析，例如 `<member_assets_root>/e2e/e2e-index.md`；不得假定所有成员都是 `product`。

父仓用例的**成员依赖字段**（二期，**必填**）：分片 `atlas-case` 块新增 `成员依赖:` 列表键：

```text
成员依赖:
  - web
  - api

# 不依赖任何成员：冒号后留空（空列表的规范写法，不写 `[]`）
成员依赖:
```

- **空列表写法（第五轮定案）**：规范形态是 `成员依赖:` 冒号后无值；`--migrate` 生成的也是这个形态。解析侧同时把字面量 `[]` 归一为空列表以兼容手写——因为 `parse_block` 对块键是 `append`，直接写 `成员依赖: []` 会被解析成 `["[]"]`，再被判「清单外成员 ⇒ FAIL」，迁移产物按自身校验必红。
- **必填（第三轮修正）**：每条父仓跨仓用例都必须有 `成员依赖`，允许空列表（规范写法 `成员依赖:`）。缺失 ⇒ `validate_e2e_index` 父仓模式 **FAIL**（输入错误），不是「不填就不判定」。
- 每个值必须是清单 `members[].name` 的成员名；不在清单 ⇒ `validate_e2e_index` 父仓模式 `FAIL`（输入错误）。
- **职责边界（第四轮定案）**：`成员依赖` 只负责两件事——被依赖成员 `missing` 时该父仓用例 `BLOCKED`，以及名字必须在清单内。它**不承担 `stale` 粒度**：父仓 fingerprint 纳入**全部成员**的 `app_hash`，任一成员应用变化 ⇒ **所有**父仓用例 `stale`，不依赖该成员的用例也不豁免。
- `缺失` 与 `BLOCKED` 的具体判定：被依赖成员 `state=missing`（路径缺失 / 非 git）时，该父仓用例判 `BLOCKED`；`index_invalid` / `no_local_e2e` 不直接阻断父仓用例（父仓执行依赖的是成员应用，不是成员本地 E2E），只在视图中 `WARN`。
- 共享用例（被多个需求引用）的 `成员依赖` 必须覆盖这些需求的并集；不一致 ⇒ `solution check` `FAIL`。

```json
{
  "schema": 1,
  "kind": "solution-e2e-readonly-view",
  "requirement": "REQ-001",
  "verdict": "PASS|INCOMPLETE|BLOCKED|FAIL|N/A",
  "parent": {
    "index": "<assets_root>/e2e/e2e-index.md",
    "case_ids": ["E2E-SOLUTION-FLOW-001", "E2E-SOLUTION-FLOW-002"],
    "ac_coverage": {
      "state": "ready|not_ready",
      "ac_total": 5,
      "attached": 5,
      "zero_attached": []
    },
    "cases": [
      {
        "id": "E2E-SOLUTION-FLOW-001",
        "status": "green",
        "review_state": "fresh",
        "members": ["web", "api"],
        "evidence": ".atlas-evidence/<run>/manifest.json"
      }
    ],
    "provenance": {"parent": {"head": "..."}, "members": [{"name": "web", "head": "...", "app_hash": "..."}]}
  },
  "members": [
    {
      "name": "web",
      "path": "web",
      "state": "ok|no_local_e2e|index_invalid|missing",
      "index": "<web_assets_root>/e2e/e2e-index.md",
      "counts": {"total": 12, "green": 9, "red": 1, "blocked": 1, "skipped": 1},
      "review": {"fresh": 8, "stale": 1, "unreviewed": 2, "legacy": 1},
      "ledger": "<web_assets_root>/e2e/reviews/console/events.jsonl",
      "latest_seq": 42,
      "reason": null
    }
  ]
}
```

字段规则：

- `verdict`：按 §3.6 的最高严重度合成；`parent.ac_coverage.state=ready` 且 `zero_attached` 非空 ⇒ `INCOMPLETE`；**单成员需求**显式 `cross_repo_e2e: none` ⇒ `N/A`（多成员需求写 `none` 在 `solution check` 已 FAIL，不会进入视图）；`FAIL > BLOCKED > INCOMPLETE > PASS`，`N/A` 单列且不显示为绿。
- `parent.case_ids` 来自清单，只读展示；父仓用例状态来自父仓账本。
- `parent.ac_coverage`：由父仓索引的 AC 表定义行 + 父仓用例 `关联AC` 计算。`state=not_ready`（骨架 `未实现` / `覆盖就绪: 否`）时不参与 `verdict`；`state=ready` 且 `zero_attached` 非空 ⇒ `verdict=INCOMPLETE`（见 §3.6），不得显示 PASS。
- `members[].counts` / `review` 从成员索引与账本**读取**；`review` 四态由父仓按成员根重算（见上），不落盘。
- `members[].state`：
  - `ok` = 索引可解析；
  - `no_local_e2e` = 成员没有本地 E2E（合法，父仓不判红）；
  - `index_invalid` = 索引缺失/列头不符/分片不一致（视图 WARN，父仓不替成员判红）；
  - `missing` = 成员路径缺失/不是 git（视图 BLOCKED；若父仓跨仓用例的 `成员依赖` 含该成员，则该用例本身 BLOCKED）。
- 视图不写任何成员文件；`--json` 输出到 stdout，父仓可选写 `<assets_root>/e2e/reviews/aggregate/<日期>-<REQ>.json` 作为只读快照（写父仓自己的目录，且该目录是保留名，见 §6.2）。

### 5.3 入口与展示

```bash
atlas solution e2e status [--requirement REQ-001] [--json]
```

- 默认人读：父仓跨仓用例表 + 成员摘要表 + 缺失/冲突清单 + 一句「本视图只读，成员评审以成员账本为准」。
- `--json`：上述 schema，供 CI/父仓控制台只读面板消费。
- 父仓控制台增加「跨仓 E2E 概览」只读面板：只展示，不提供「执行」「提交」「review」按钮；成员本地行只显示状态与链接，不打开执行草稿。
- **`templates/e2e/console/app.js` 的草稿键**：现为 `atlas-console-draft:v3:${src}`，只按 `src`；如果二期面板复用用例详情/草稿，必须改成 `DRAFT_KEY(member, src)` 或按 `member/case` 命名空间，否则两个成员同名 `cid` 会撞。默认设计是只读面板不创建草稿；若实现选择复用详情，上述键改造是强制项。

### 5.4 缺失 / 冲突：红还是跳过（二期）

| 情形 | 视图表现 | 是否红 |
|---|---|---|
| 成员本地无 E2E | `state=no_local_e2e`，显示原因 | **不红**（成员资产，父仓不拥有） |
| 成员索引不可解析 / 分片不一致 | `state=index_invalid`，WARN | **不红**（父仓跨仓用例若 `成员依赖` 含该成员，也只 WARN 不 BLOCKED——父仓执行依赖成员应用，不是成员本地 E2E） |
| 成员路径缺失 / 非 git | `state=missing`，BLOCKED 标记 | 若父仓跨仓用例的 `成员依赖` 含该成员 ⇒ 该用例 **BLOCKED**；否则视图只提示 |
| 清单成员重复 / 名称非法 | `solution check` FAIL（既有） | **红**（输入冲突） |
| 父仓用例缺 `成员依赖` | `validate_e2e_index` 父仓模式 FAIL | **红**（输入错误；空列表 `[]` 合法） |
| `成员依赖` 含清单外成员 | `validate_e2e_index` FAIL | **红**（输入错误） |
| 父仓 `case_ids` 指向缺失用例 | 视图显示 `parent` 缺失项 | **红**（父仓资产冲突） |
| 父仓索引缺失 | `parent` 状态 `missing` | **红/WARN**：已声明 `case_ids` ⇒ FAIL；未声明 ⇒ WARN |

二期视图的「红」只用于父仓自己的资产/输入冲突；成员本地 E2E 的缺口按成员自己的门处理，父仓不越权判红。

**`成员依赖` 不参与 `stale` 判定（第四轮定案）**：上表里它只影响三处——缺失 FAIL、清单外成员 FAIL、被依赖成员 `missing` ⇒ 该用例 BLOCKED。父仓用例的 `fresh/stale` 一律由父仓 fingerprint（父仓脚本/分片 + 全部成员 `app_hash`）决定：任一成员应用变化 ⇒ 全部父仓用例 `stale`，与 `成员依赖` 是否包含该成员无关。

### 5.5 机器门 vs 纪律（二期）

| 环节 | 机器门 | 纪律 |
|---|---|---|
| 视图只读（不写成员、不执行） | ✅ 测试对账成员文件 mtime/hash；无 runner 调用 | — |
| 父仓 `case_ids` 与父仓索引一致 | ✅ 复用一期选择器 | — |
| `成员依赖` 必填 / 名字合法 / 共享声明一致 | ✅ `validate_e2e_index` 父仓模式（缺失或非法 FAIL）+ `solution check`（共享声明） | — |
| 成员索引可解析 / 计数一致 | ✅ 读取校验，`index_invalid` 可复算 | — |
| 成员 `review_state` 按成员根重算 | ✅ 同一 `case_review_state` 内核，比较对象是 run-time `prov`；父仓根计算 ⇒ 红；H5 必须证明：只改 B ⇒ 成员 A **本地**用例仍 `fresh`，且**所有**父仓用例 `stale` | 只读展示，不落盘 |
| AC 反向覆盖 | ✅ `parent.ac_coverage` 必出；`覆盖就绪` 域零挂靠 ⇒ `verdict=INCOMPLETE` | 不替代 `validate_e2e_index` 的 WARN |
| 成员本地 E2E 是否充分 | ❌ | ✅ 成员自己的评审 |
| 跨仓用例是否覆盖所有成员 | ❌ | ✅ 需求评审 |
| 视图是否被误当第二真相源 | 部分（文件头声明 + 无写接口） | ✅ 评审/流程纪律 |

### 5.6 改动面（二期）

| 文件 | 改动 |
|---|---|
| `scripts/atlas_solution.py` | `solution e2e status`：读父仓 + 成员摘要；`--json`；可选只读快照；`solution e2e init --migrate`：批量补 `成员依赖:` 并输出涉及清单 |
| `_support/solution_e2e.py` | 复用一期内核，增加 `read_member_summary(member_root)`；按成员根重算 `review_state`；只读 |
| `_support/case_block.py` | `_BLOCK_KEYS` 增加 `成员依赖`（列表键）；空值（`成员依赖:`）与字面量 `[]` 都归一为空列表；空列表序列化写 `成员依赖:` |
| `validators/validate_e2e_index.py` | 父仓模式校验 `成员依赖` **必填**（缺失 FAIL）、名字合法、共享用例声明一致性；`parent.ac_coverage` 所需的 AC 挂靠统计 |
| `scripts/e2e_console.py` | 只读面板数据接口（若控制台内嵌）；不提供执行/提交路由 |
| `templates/e2e/console/app.js` | 只读面板；若复用详情/草稿，`DRAFT_KEY` 加 member 命名空间 |
| `shared/solution.md` / `rings/e2e/reference.md` | 只读视图契约：字段、红/不红边界、非第二真相源声明；`成员依赖` **必填**（允许空列表）；`parent.ac_coverage` |
| `docs/map/gates.md` / `atlas-map.html` | 若二期新增门行，同步锚值（与一期分开计） |
| `tests/test_solution_e2e_view.py`（新增） | 只读性、缺失/冲突分级、按成员根重算、成员账本不被重签、`app.js` 草稿键不撞、`成员依赖` 必填（缺失 FAIL）/ BLOCKED、**`成员依赖:` 空值 ⇒ 空列表、`成员依赖: []` ⇒ 归一为空列表**、`parent.ac_coverage` / `INCOMPLETE`、**跨成员隔离（只改 B：A 本地仍 fresh，所有父仓用例 stale）**、`init --migrate` 批量补 `成员依赖:` 与输出清单 |
| `tests/test_e2e_console_solution.py` | 只读面板不触发执行/提交 |

### 5.7 迁移与回滚（二期）

- 成员侧无数据迁移：二期只读成员既有索引/账本；成员零改动。
- 父仓侧有一个**前置迁移**：父仓用例**必须补 `成员依赖`**。用 `atlas solution e2e init --migrate`（等价 `atlas e2e migrate`）为存量父仓用例批量补 `成员依赖:`（冒号后留空；**不写 `[]`**，因为 `parse_block` 对块键是 `append`，`[]` 会被解析成 `["[]"]`）；迁移必须**输出涉及清单**（逐文件/逐用例 ID），供人工确认后再改语义。
- **不跑迁移直接升级 ⇒ 存量父仓用例全红是预期行为**：`validate_e2e_index` 父仓模式对缺失 `成员依赖` 判 FAIL，不提供「缺失就不判定」的兼容路径。先迁移、后跑门。
- 已有一期用例若确有成员依赖，迁移只补空列表，不猜语义；真实依赖由人工在迁移输出清单上逐条补，补错（漏成员）不会导致 stale 漏判（父仓 fingerprint 用全部成员 `app_hash`），只会漏掉 `BLOCKED`。
- 回滚：删除 `atlas solution e2e status` 子命令与只读面板；`--migrate` 写入的 `成员依赖:` 可保留（对一期无影响），不删除任何成员/父仓 E2E 数据；无账本变更需要撤销。

### 5.8 验收钉子（二期）

| 钉子 | 咬红形态 |
|---|---|
| 只读性 | 视图调用执行器 / 写成员索引 / 追加成员账本 ⇒ 红 |
| `review_state` 来源 | 父仓用父仓根计算成员 `current` ⇒ 红；父仓把重算结果写回成员账本/索引 ⇒ 红；成员账本 `reviewed.pass` 被改写 ⇒ 红 |
| 跨成员隔离 | 只改成员 B 的应用内容，成员 A 的**本地** `review_state` 从 `fresh` 变 `stale` ⇒ 红；只改 B 时让「不依赖 B 的父仓用例」保持 `fresh` ⇒ 红（必须**所有**父仓用例 `stale`） |
| 迁移工具 | 存量父仓用例缺 `成员依赖` 时，`--migrate` 不补 `成员依赖:`、不输出涉及清单，或迁移后仍 FAIL ⇒ 红；不跑迁移直接升级却未按预期全红 ⇒ 红 |
| 成员依赖必填 | 父仓用例缺 `成员依赖` 仍通过 ⇒ 红（必须 FAIL）；写 `成员依赖:`（冒号后留空）被误判缺失或判成清单外成员 ⇒ 红（必须解析为空列表）；写 `成员依赖: []` 得到 `["[]"]` ⇒ 红（必须归一为空列表） |
| 成员依赖 | `成员依赖` 含清单外成员仍通过 ⇒ 红；依赖成员 `missing` 时用例仍 PASS ⇒ 红（必须 BLOCKED） |
| AC 覆盖 | `--json` 缺 `parent.ac_coverage` ⇒ 红；`覆盖就绪` 域 `zero_attached` 非空但 `verdict` 仍 PASS ⇒ 红（必须 INCOMPLETE） |
| 缺失分级 | 成员无本地 E2E 被误判红，或父仓 `case_ids` 缺失被误判 `no_local_e2e` ⇒ 红 |
| 草稿键 | 两个成员同名 `cid` 共用 `atlas-console-draft:v3:${src}` ⇒ 红 |
| 第二真相源 | 视图输出被写入提交并当作父仓账本 ⇒ 红（必须在文件头声明只读） |

---

## 6. 契约修正与地图锚

### 6.1 `shared/solution.md:5`：不动 `:15` / `layout.md:111`，只修 `:5` 的漂移

- **只改 `:5`**：把「本层不复制 PRD / 域事实 / E2E」改为「本层不复制成员 PRD / 域事实 / 成员 E2E；父仓持有跨仓 E2E，成员保留本地 E2E。**资产归属的单源是 `atlas.solution.yaml` 的 `members[].assets`。**」
- **补选择器口径**：父仓跨仓 E2E 的清单选择器是 `requirements[].case_ids`；**多成员需求必须有 `case_ids`（禁止 `none`）**，单成员需求 `case_ids` 或 `cross_repo_e2e: none` 二选一，两者都无 ⇒ `solution check` FAIL。
- **第二句必须保留**：它是 A 判归属的唯一锚点；替换时不能只留前半句。
- **不改 `:15`**：`<assets_root>/ # 父级 PRD / E2E / solution stack-profile` 已与 `shared/layout.md:111` 一致，是正确落点。
- **不改 `shared/layout.md:111`**：同一落点，动了会造成第三处漂移。

### 6.2 `rings/e2e/reference.md` §10.1 / §5.5

补四条：

1. solution 根是合法 E2E 根：`<assets_root>/e2e/` 与单仓同构；父仓控制台单根运行。
2. 跨仓用例使用虚拟页 `solution-flow`（`domain: solution`，路由 `/`）；`pages[]` 只登记虚拟页，成员页面级追踪在二期只读视图中按成员展示。
3. 一期跨仓流的运行前提是统一入口网关（父仓 `e2e.app_base_url`）；多 host 直连不在本期。
4. `reviews/` 下的 **`aggregate/`** 登记为保留名：与 `<日期>-first-run` / `<日期>-acceptance-<域>` / `<日期>-verify` / `console/` 同列，**不参与** `rings/e2e/reference.md` §7.1 / §12.6 的报告定位；保留名且无 `review.json` ⇒ 跳过，带 `review.json` ⇒ 按报告校验。二期 `成员依赖` 字段登记在 §5.5 用例块字段表，并注明**必填（允许空列表）**；骨架反向视图行注明**空单元格**。

### 6.3 门册与地图锚

- `shared/gates.md` 新增一行「solution 跨仓 E2E」门行（六列：门 / 对账平面 / 查什么 / 不查什么 / 预算 / 假绿测试等级）；testid 门行「不查什么」补「solution 根 N/A」。
- 新增一行 ⇒ `shared/gates.md` 行数变化。当前 `docs/map/gates.md:18` 写 `(175 行)`，而 `wc -l shared/gates.md` 实测 174（说明地图锚口径与 `wc -l` 不同）；实现批必须按 `tests/test_map_anchors.py` 的实际口径重新计算并同步 `docs/map/atlas-map.html`。**以测试实际口径为准，不手抄第二套数字。**

---

## 7. 不做什么（越界边界）

1. **不把成员本地 E2E 迁到父仓**。成员资产不迁移，`unified` / `import` 另案。
2. **不在父仓执行成员本地用例**。父仓只执行父仓跨仓用例；成员本地用例仍由成员控制台执行。
3. **不在二期回写成员索引/账本、不替代成员 review**。二期只读；成员评审以成员 `events.jsonl` 为准。
4. **不新增第二套 runner / 不并行 / 不自动重试**。复用既有单根 Runner；并发保持 1。
5. **不支持多 host 直连**。一期只支持统一入口网关的同源跨仓流；多 host、每成员 `app_base_url`、跨 host 登录态另案。
6. **不在父仓索引里表达成员页面级 `pages[]`**。跨仓用例只登记虚拟页 `solution-flow`；成员页面级追踪在二期只读视图里按成员展示。
7. **不做跨仓 AC crosswalk**。`AC-SOLUTION-NNN` 仍归 `solution-prd.md`；成员 AC 映射另案。
8. **不改单仓 `validate_e2e_index` 的默认 `N/A` 语义**。父仓的 `require_e2e` 是 solution 层模式；单仓空骨架行为保持不变。
9. **不改单仓 `validate_testids` 行为**。solution 根 N/A 是 solution 层模式；单仓仍按 `stack-profile.apps` 正常扫描。
10. **不改 `duty-review/bugs.md` 的既有 `#56`**。本文只留指针，不复述其状态，也不新建第三份副本。
11. **不把 `关联AC` / `需求` 列当选择器**。选择器唯一真相是 `case_ids`；两列只做追溯/人读。**多成员需求必须有 `case_ids`（禁止 `cross_repo_e2e: none`）；单成员需求**才可以用显式 `cross_repo_e2e: none` 表达「没有跨仓 E2E」，不能靠留空表达。

---

## 8. 重开条件

1. **没有统一入口网关，或成员必须多 host 直连**：一期「父仓单 `app_base_url`」不成立，需要重新设计多 host 靶场/登录态。
2. **一条跨仓流必须同时断言两个成员页面的终态**，无法用虚拟页 `solution-flow` 承载：需要新的跨仓用例形态或回到 B 的聚合执行。
3. **成员本地 E2E 必须纳入父仓同一次 review**：A 的边界是「父仓 review 跨仓验收，成员 review 本地」，若业务要求一次 review 覆盖全部成员用例，需要重新评估 B 或成员执行接管。
4. **`unified` 模式落地**：父仓成为唯一资产 owner，本方案的跨仓/本地分层需要重新定义。
5. **虚拟页 `solution-flow` 反复掩盖成员页面级缺口**：评审无法从父仓索引判断跨仓流实际覆盖了哪些成员页面，且二期只读视图也不足以补足。
6. **`case_ids` 维护成本失控**：需求/用例频繁变动，`case_ids` 成为手工第二真相源，且无法用父仓索引派生。
7. **父仓跨仓用例需要成员本地夹具/登录态而父仓无法复现**：环境边界被突破，需要重新定义父仓画像或成员协作方式。
8. **跨仓用例的成员 testid 需要父仓机器门校验**：当前 solution 根 `validate_testids` 为 N/A；若要求父仓逐 testid 校验，需要引入成员命名空间或按 `成员依赖` 分成员扫描。
   - **QUEUE 观察行**：`solution-testid-namespace`；owner：方案维护者（实现批开工时指派）；期限：**二期实现批复审前**（或一期上线后 30 天内，以先到者为准）。到期未闭环 ⇒ 升级为二期阻断，不允许继续以 N/A + 纪律缓解长期存在。
   - 观察内容：跨仓用例是否出现未标注归属的成员 testid；成员 `app_hash` 变化后是否只重签未重跑；评审是否因 testid 归属产生误判。三项任一有反例 ⇒ 提前重开。

---

## 9. 改动面总表

| 类别 | 文件 | 期 |
|---|---|---|
| 契约 | `shared/solution.md`（只改 `:5`，保留第二句；§2 `case_ids` / `cross_repo_e2e`；新小节） | 一期 |
| 契约 | `rings/e2e/reference.md` §10.1 / §5.5（父仓根 / 虚拟页 / 网关 / 反向视图空单元格 / `aggregate` 保留名 / `成员依赖` 必填） | 一期 + 二期 |
| 契约 | `shared/gates.md`（门行 + 行数；testid 门「不查什么」补 solution 根 N/A） | 一期 |
| 契约 | `docs/map/gates.md:18`、`docs/map/atlas-map.html`（按 `test_map_anchors` 口径同步） | 一期 |
| 解析 | `_support/solution.py`（`case_ids` / `cross_repo_e2e` known 集；只做文法/去重/单行/互斥；init 骨架；docstring；case_id 消费者） | 一期 |
| 内核 | `_support/solution_e2e.py`（新增：选择器 / 索引 / 孤儿审计 / 成员摘要 / 分级 / `ac_coverage`） | 一期 + 二期 |
| 用例块 | `_support/case_block.py`（`成员依赖` 列表键，允许空列表） | 二期 |
| CLI/脚本 | `scripts/atlas_solution.py`（`e2e init` / `check` / `e2e status`） | 一期 + 二期 |
| 控制台 | `scripts/e2e_console.py`（`--requirement` / 逐成员 provenance / fingerprint） | 一期 |
| 控制台 | `templates/e2e/console/app.js`（只读面板；若复用草稿则 `DRAFT_KEY` 按成员命名） | 二期 |
| 校验器 | `validators/validate_e2e_index.py`（`require_e2e` 父仓模式 / AC 定义行 / 孤儿审计 / `成员依赖` / 共享声明） | 一期 + 二期 |
| 校验器 | `validators/validate_testids.py`（solution 根 N/A，单仓不变） | 一期 |
| 模板 | `templates/atlas.solution.yaml`（`case_ids` / `cross_repo_e2e` + `scope` 示例） | 一期 |
| CLI | `bin/atlas.js`（`solution e2e init/status`、`console --requirement`） | 一期 + 二期 |
| 测试 | `tests/test_solution_e2e.py`、`tests/test_e2e_console_solution.py`、`tests/test_solution_e2e_view.py` | 一期 + 二期 |
| 测试 | `tests/test_tools.py`（case_id 消费者）、`tests/test_map_anchors.py`（锚值） | 一期 |

---

## 10. 待拍板 / 需用户决策

1. **确认方向**：A + 两期（一期父仓持跨仓 E2E；二期只读聚合视图），B 只在 §2.2 留否决记录，不并存。
2. **网关前提**：一期只支持统一入口网关的同源跨仓流；是否接受？若现有方案成员多 host 直连，需要先补网关或改为重开条件 §8.1。
3. **虚拟页**：父仓跨仓用例使用 `solution-flow` 虚拟页（`domain: solution`，路由 `/`，骨架 `未实现` / `覆盖就绪: 否`）；是否接受？替代方案是扩索引页面表增加「跨仓流」类型，改动更大。
4. **选择器**：`requirements[].case_ids`（需求级、逗号分隔、每需求最多一行）作为唯一选择器；**多成员需求（同一 `requirement.id` ≥2 个 `member` 行）必须有 `case_ids`，禁止 `cross_repo_e2e: none`**；只有单成员需求可用 `none`；两者都不写 ⇒ `solution check` FAIL，是否接受？`需求` / `关联AC` 不参与选例；跨需求复用按 §3.3 的「允许 + 显式声明」是否接受？
5. **状态合成**：`selected=0` / `skipped` / `prototype-pass` 一律 `BLOCKED`；**单成员需求**显式 `cross_repo_e2e: none` 为 `N/A`（多成员写 `none` 是 FAIL，不是 N/A）；仅全 `green` + 全 `fresh` 才 `PASS`；是否确认？
6. **父仓 `check` 档位**：未初始化默认 WARN；`--strict` 按**既有升级集合**（锁/成员/版本/契约/dirty 等）一起升 FAIL，**不是只升 E2E 这一条**；多成员需求缺 `case_ids` / 单成员二选一缺失、已声明 `case_ids` 但无索引直接 FAIL；`AC 反向覆盖` 不进 `solution check`，由 `e2e status --json` 的 `parent.ac_coverage` / `INCOMPLETE` 表达；是否确认？
7. **父仓 testid 门**：solution 根 `validate_testids` 返回 N/A，成员 testid 在成员根各自校验；三条缓解见 §3.7（禁写/标注成员归属、`app_hash` 变化必须重跑、§8.8 QUEUE 观察行）；是否接受？若要求父仓机器校验，走 §8.8 重开条件。
8. **二期放行**：`review_state` 按成员根重算（只读不落盘）+ `成员依赖` **必填**（允许空列表，缺失 FAIL）+ 跨成员隔离样本 H5；是否接受？接受后才进入二期实现批。
9. **地图锚**：新增门行后 `shared/gates.md` 行数变化，`docs/map/gates.md:18` 与 `atlas-map.html` 按 `test_map_anchors.py` 实际口径同步；实现批执行，本轮不改。
10. **台账**：本仓 `bugs.md` 的 `#56` 与 GitHub `#56` 撞号；本题若落本地台账，编号由维护者另定，本文只留 GitHub 指针，不复述 `bugs.md` 状态。本轮不动 `bugs.md`。

---

## 11. 本轮状态

- 本文件状态：**方案待评审**；本轮为第五轮硬冲突定案修订；只改方案文档，未改实现代码；未提交、未 push、未发版。
- **未实跑测试**（方案阶段不写假绿）；§4.2 与 §4.5 的留出验证标注「未实跑 / 部分取证」，实现批补证。
- **§4.5 三态**：部分取证 / 未闭族；目前无 pre-fix 红证（见 §4.5.3 / §4.5.5）。
- `duty-review/bugs.md`、`duty-review/QUEUE.md` 未被修改。
- 下一步：独立评审；通过后按一期 → 二期拆实现批，每批先补 §4.5 留出验证与反面包，再改门册/地图锚。
