# 多仓方案层：统一模式 + 联合模式的单次初始化（Solution Layer）

> 提案编号：RFC-20261104-02
> 提案作者：Atlas 方案会话（待维护者指派独立评审）
> 关联状态：草案（Draft；已按两轮只读评审 + 2026-11-04 拍板定稿，未实现）
> 影响范围：CLI（`bin/atlas.js`）· 契约（`shared/` 新增 solution 契约）· 脚本（`scripts/`、`_support/`）· 模板（`templates/`）· apply 技能与装配（`apply/`、`skills/`、`agents/`、`patches/`、`install.py`）· 测试（`tests/`）· 宿主集成（Trellis 提交路径）
> 关联：`RFC-20261026-01`（布局配置，资产根解析）；`shared/stack-profile.md` §2；`shared/layout.md`；`shared/closeout.md`；`shared/single-source.md`；`rings/structure/reference.md`；`tests/test_nested_repo_gitlink_guard.py`
> 并行批避号：同日 `RFC-20261104-01` 已占用，本批取 `-02`。
> 修订说明：本文件替换早先「只读聚合、不承载 PRD」草稿的核心定案；取证与备选否决保留，新增双模式、实测约束、两轮评审修订与用户拍板。

---

## 0. 术语

- **solution（方案工作区）**：父级 meta git 仓，只跟踪 Atlas 资产、清单、锁、父级 PRD；成员代码仓保持独立。
- **成员（member）**：一个独立 git 仓；solution 清单声明其路径与资产归属。
- **统一模式（unified）**：全部成员 `assets: solution`；solution 拥有唯一资产集（PRD、结构事实、E2E、Trellis），成员只提供代码根。一次初始化、一份父级 PRD。
- **联合模式（federated）**：全部成员 `assets: member`；成员各自 init / adopt / 工作；solution 只拥有父级 PRD、跨仓契约锁、跨仓 E2E 与 solution stack-profile，成员资产只读聚合。父级随后整合。
- **混合（mixed）**：`import` / `export` 期间的**受支持迁移态**；`status` 必须显著标记。渐进迁移允许它持续一段时间，但每个成员必须始终只有一个资产 owner。

---

## 1. 现象与取证

### 1.1 触发形态

- **生命周期 A（父级先）**：一个产品分多个独立仓，希望父级只初始化一次，父级 PRD 是统一需求源，成员仓不再各自开户。
- **生命周期 B（子级先）**：成员仓先各自 init / adopt / 工作；父级后补产品视图与父级 PRD，整合已有成员资产，而不是重开户。
- **现状**：两种形态都落不了地——父级初始化没有承载点（资产根与代码根绑定、baseline 单 commit、git 操作只看项目根）；子级先开户后父级没有聚合层，父级 PRD / 跨仓契约只能复制或人工维护。

### 1.2 客观证据（Atlas 契约与代码）

- `shared/stack-profile.md:16`：产品级资产归属为「一个产品一份 atlas 资产」；但资产根与项目根绑定（`:8`、`:37` 的 `apps[].path` 为相对项目根路径），没有多仓语义。
- `rings/structure/reference.md:58` / `:195` / `:282`：结构事实基线是 `_meta.json.baseline` 的**单个** `{branch, commit}`；`--chain` 无漂移时自动推进。
- `shared/gates.md:57`：impact 对账门以当前仓的 `git diff` 为实际集；`shared/closeout.md:40`：`closeout_derive` 需要 git 仓库，非 git 项目直接拒绝。
- `tests/test_nested_repo_gitlink_guard.py`：嵌套仓布局已有机器红线——父仓 `git add` 子仓会落 gitlink（mode `160000`），文件级变更不进父仓 `git diff`。
- `shared/stack-profile.md:83`：图谱查询按项目根前缀过滤，不跨仓读出。

### 1.3 实测：成员目录不能 gitignore；untracked 必须逐成员展开

在临时仓（一个 JS 文件 + 成员目录）实测宿主搜索与图谱（cgc 0.6.13）：

| 成员目录布局 | Qoder Grep（ripgrep） | cgc 全量索引 |
|---|---|---|
| `.gitignore` 忽略成员 | ❌ 搜不到 | ❌ 成员代码不入图（只扫到 2 个非成员文件） |
| `.gitignore` + `.ignore` 写 `!member/**` | ✅ | ❌ 仍不入图 |
| 成员 untracked（不 ignore） | ✅ | ✅ 成员代码入图 |
| 成员是嵌套 git 仓、untracked | ✅ | ✅ 成员代码入图 |
| `.git/info/exclude` 隐藏成员 | ❌ 搜不到 | 未测（同一 ignore 栈，不可靠） |

多成员同父目录时（`members/web` + `members/api`）实测：

- `git status --porcelain` 默认只回 `?? members/`（折叠）；
- `git status --porcelain --untracked-files=all` 回 `?? members/api/`、`?? members/web/`；
- `git -c status.showUntrackedFiles=no status --porcelain` 回空——会让 `_graph`、`atlas_check`、review scope 全部失明。

硬约束：

- 成员目录必须 **untracked 且不被任何 ignore 规则覆盖**；ignore 会同时盲掉内容搜索与图谱。
- **禁止设置 `status.showUntrackedFiles=no`**（仓级 config 会盲掉所有消费者）；只用逐命令 `-uall` 或 `solution status` 做显示降噪。
- 所有读取 untracked 的消费者统一 `--untracked-files=all`，并按**逐成员根精确过滤**（不得用共同祖先豁免同目录非成员脏文件）；补「两成员同父目录」夹具。
- 加防 gitlink 守卫：成员路径进入暂存区 / 以 mode `160000` 入库即报错；成员被 ignore 也要报。
- `freshness_key` / baseline 只读 solution HEAD + `git status`，而 `?? member/` 在成员内部改动时不变 ⇒ 必须把成员 HEAD + dirty 纳入新鲜度键与 baseline 向量。

### 1.4 评审取证（两轮，主审已复现）

- `refresh_structure.py:619-654` 的 `maybe_advance_baseline` 脏过滤只豁免资产前缀（`clean_exempt_prefixes` 不含成员根）⇒ 成员 untracked 时 `?? member/` 会永久冻结 baseline；同父目录折叠会进一步失配。
- `validate_e2e_index.py` 的「关联AC 可达」语料只 `glob("*-prd.md")`；父级 `prd.md` 的 AC 不进语料。`validate_prd.py` 的 AC 撞号只扫域级文件；域级 PRD 还要求 `二/四/五`、FN/R/AC、三列 AC 表、`domain_code`，AC ID 三位（`AC-[A-Z0-9]+-\d{3}`）。
- `bin/atlas.js:412-428`：`apply` 是 Agent 会话技能，不是 CLI 子命令；`apply/reference.md:43` 的输入全部以单仓项目根为基准。
- `impact_reconcile.py` 只 `git diff`，untracked 不在实际集；`head` 只比 solution HEAD；`impact_report.py` 同。预测集是 solution-relative 路径，不能用 `member:path` 冒号形态。
- `closeout_derive.py:169-190` 的 `git ls-files --others` 在嵌套成员 untracked 时只回 `member/`（实测），成员内改动不触发事件行；非 git 成员则逐文件枚举，污染计数。
- `safe_commit.py` 只暂存 `.trellis/workspace|tasks`；代码提交在 Trellis Phase 3.4（`workflow.md:711`），父仓 `git add member/src/a.js` 实测 rc=0 但 index 为空。
- `_support/review_scope_core.py` 的 status map 只覆盖 solution root；成员代码不在 review scope。
- `scripts/e2e_console.py:126-128` 的 `repo_git_dirty` 与 `:356-370` 的 `ls-files -o` 在 solution 根对嵌套成员只回目录，成员改代码后 `app_hash` 不变 ⇒ console 绑定假新鲜；Phase 1 跨仓 E2E 同批改为逐成员 `-uall` + 成员 hash。
- `shared/single-source.md` §3：迁移后旧源必须**删除**（无冻结档，历史归 git）；`validate_structure.py:270-274` 在缺 `_meta.json` 时 FAIL。
- Trellis `packages` 已声明 polyrepo 语义（`git: true`），可承载成员 git-context；但代码提交仍需独立通道。

---

## 2. 决策与权衡

### 2.1 核心定案

1. **一个 solution 清单，两种规范模式，允许受支持的迁移混合。**
   - `atlas.solution.yaml` 声明 `mode: unified | federated` 与每个成员 `assets: solution | member`。
   - `unified`：唯一资产集在 solution；成员仓无 Atlas 资产；一次 init、一份父级 PRD。
   - `federated`：成员各自 init / adopt / 工作；solution 只拥有父级 PRD、契约声明/锁、跨仓 E2E、solution stack-profile。
   - `mixed`：`import` / `export` 期间的受支持迁移态；每个成员始终只有一个资产 owner，`status` 显著标记。
   - **默认模式（已拍板）**：长期默认 = 绿地无成员资产 → `unified`；已有成员资产 → `federated`；`--mode` 可覆盖。**Phase 1 构建临时只交付 federated：Phase 1 的 `init --mode unified` 必须以「Phase 2 未交付」显式退出，不得静默回退；Phase 2 交付后恢复上述长期默认。**

2. **单一归属不变量（防双真相源）。**
   - 每一条需求 / AC / 域事实 / 用例 / 结构事实只能有一个 owner 层：solution 或成员；由 `members[].assets` 决定。
   - 跨仓需求、跨仓契约、跨仓 E2E 永远归 solution；成员本地细节归成员。
   - 禁止把同一份 PRD / 域事实 / 用例复制到两层；父级 PRD 只能引用成员 PRD，不得搬运正文。
   - **AC 级归属显式化**：父级 AC 表必须有 `owner: solution | member` 列（或等价字段）；`solution check` 校验每条父级 AC 有 owner、每个 member owner 引用的 AC 在成员 PRD 中存在。
   - **机器可判的只有 AC ID 撞号、owner 声明完整性与引用可达**；「同能力异 ID」的语义重复是显式盲区，归独立评审/人工，不假装是门。

3. **父级 PRD 两种模式都存在；`solution-prd.md` 是完整的域级 PRD。**
   - solution `product/prd/prd.md` 始终是产品级需求源：产品范围、跨仓需求、覆盖矩阵、成员归属。
   - **`product/prd/solution-prd.md` 必须按现有域级 PRD 完整形态落盘**：`domain: solution`、`domain_code: SOLUTION`、`AC-SOLUTION-NNN`（三位）、§一–§十一（按现有域级 PRD 完整形态；`二/四/五` 与结构类 AC 清单小节不可缺）、FN/R/AC 与三列 AC 表；`prd.md` §五的域清单必须列出 `solution`，`README.md` 追溯总表有对应行。**实现时以 `templates/prd/domain.md` 全量为准**：frontmatter `domain_name` / `doc` / `version` / `date` / `status`；§二标题含「功能清单」，每个 FN 必须被规则服务；§四「所属功能」为第 3 列；README 追溯行 7 列且计数一致；不可验 AC 清单可选，结构类 AC 清单必填。这样不扩 `validate_e2e_index` / `validate_prd` 的语料，跨仓 E2E 的「关联AC 可达」与 AC 撞号可直接成立。
   - **拍板**：本期采用上述完整域 PRD 形态；「扩门扫 `prd.md`」作为后续备选（会改校验器与门册，不在本期）。
   - `unified`：父级 PRD + 域级 PRD 都在 solution；`federated`：父级 PRD 是跨仓层，成员域级 PRD 仍是本地细节真相源；若要求全部需求都在父级，走 `import` 变统一模式。

4. **solution 底座：meta repo + untracked 成员 + 逐成员展开 + 多重守卫。**
   - solution 根必须是 git 仓，只跟踪 Atlas 资产、清单、锁、父级 PRD；成员目录 untracked（不 ignore）。
   - 所有消费者读取 untracked 一律 `--untracked-files=all`，并按**逐成员根精确过滤**（不得用共同祖先豁免）；**不得设置 `status.showUntrackedFiles=no`**。
   - 守卫覆盖：成员被 **`.gitignore` / `.ignore` / `.rgignore` / `.git/info/exclude`** 任一命中即报；成员路径进暂存区或 mode `160000` 即报；非 git 成员显式报（不回退逐文件枚举）。
   - 路径只允许 solution 内相对路径，拒绝绝对路径与 `..` 逃逸（清单 schema 错误，exit 2）。
   - 检查结果 phase 1 一律 WARN（不阻塞）；若后续升 FAIL，先登记 `shared/gates.md` 行 + 坏输入必红证明。

5. **baseline 与新鲜度按归属分层；路径统一 solution-relative。**
   - `unified`：`_meta.json.baseline` 升级为 schema v2，记录 solution commit + **成员 SHA 向量**；`refresh_structure --chain` 只有全部 solution-owned 成员干净时才原子推进。成员根加入 solution 脏过滤的**豁免前缀**，并逐成员跑 `git -C <member> status --porcelain --untracked-files=all`（含 untracked 新文件）作为干净判据。
   - 同批消费者必须一起改：`render_tour` 的基线渲染、`_drift-history.jsonl` 事件维度、`--advance-baseline` 口径、`_graph.freshness_key()`（成员 HEAD + dirty 文件，`-uall`）、`impact_report` / `impact_reconcile` 的 inputs/head、`scripts/e2e_console.py` 的 `repo_git_dirty` / `app_hash`、review scope 与 `after_archive` hook 的推进时序。
   - **路径统一为 solution-relative**（如 `members/web/src/a.js` / `web-client/src/a.js`），不使用 `member:path` 冒号形态；结构化输出另带 `member` 字段。impact 预测集与实际集必须同一形态，否则双向差集必错。
   - `federated`：成员 baseline 留在成员仓；solution 锁记录成员 HEAD、成员 baseline、契约指纹；solution 只读聚合，不产生成员结构事实。
   - 两种模式下，solution 自有资产（父级 PRD、跨仓 E2E、清单/锁）的 baseline 是 solution meta repo 的 commit。

   **mixed 态消费者矩阵**（每个成员只有一个 owner）：

   | 消费者 | `assets: solution` | `assets: member` |
   |---|---|---|
   | 结构事实 / baseline | solution 拥有；进入向量 | 成员拥有；solution 锁只读 |
   | 图谱新鲜度 | solution 索引纳入成员 HEAD + dirty | 成员自己的图谱；solution 不索引该成员 |
   | impact / closeout | solution-relative diff + 成员 diff | 只读成员 `git -C <member>` diff |
   | apply | solution apply | 成员 apply |
   | E2E / testid | solution 跨仓；成员本地归成员 | 同左，成员本地不复制到 solution |

6. **命令、初始化与清单单源。**
   - `atlas solution init --mode unified|federated`：父目录建 meta 仓 / 清单 / solution 层；`unified` 只装一套 `.atlas` / `.trellis` / `product`，不碰成员仓；`federated` 在 solution 根装 solution 层所需 Atlas 资产（父级 PRD / 契约锁 / 画像），不碰成员资产。
   - **清单单源**：`atlas.solution.yaml` 是 `members` / `mode` / `assets` / `contracts` / `requirements` 的唯一来源；`stack-profile.md` §2 只引用，不重复声明成员归属。`atlas.config.yaml` 继续负责 solution 根的 `layout.assets_root`；`atlas solution init` 负责写 `atlas.config.yaml` + `atlas.solution.yaml` 并复用 `install.py` 装配。
   - `atlas solution adopt`：接入已有父目录，识别成员资产并生成 `federated` 清单；无成员资产则提示选择模式（Phase 1 只接受 federated）。
   - `atlas solution import <member>`：`federated → unified` 的成员迁移；先 `--dry-run`（dry-run 不写盘）。迁移清单必须含：成员 PRD（含 AC）、结构事实、`spec/conventions`（含 testid）、E2E（cases/index/scripts）、`.trellis/tasks`、`.trellis/workspace/<dev>`、Trellis 配置/任务钩子、AGENTS/宿主接线；移除成员 `after_archive` 等仍会刷成员结构的钩子；globs 在 `_meta.json.domains`、`domains/*.md`、PRD 域 glob 与任务上下文中统一加成员前缀；**旧源按 `shared/single-source.md` §3 迁移后删除（历史归 git），不保留冻结 archive**；同步更新 `shared/single-source.md` §1 的权威落点与 `shared/global-rules.md` 的迁移登记。
   - `atlas solution export <member>`：反向迁移（后续阶段）。
   - `status` / `check` / `lock`：只读聚合；`lock --update` 人工确认后写锁。
   - **Trellis packages（Phase 1 范围收窄）**：Phase 1 不创建 `.trellis/`；若 solution 根已有 `.trellis/config.yaml`，只校验 `packages` 是否声明成员 `path`（不校验 `git: true`）。完整生成与语义校验归 Phase 2；成员归属仍以 `atlas.solution.yaml` 为单源，不从 packages 反推。

7. **apply / 任务流。**
   - **`apply` 是技能不是子命令**（`bin/atlas.js:412-428`）：`unified` 模式必须新增/更新 apply 技能与装配契约——输入为 solution `.trellis/tasks/<需求ID>/prd.md`、solution 结构 `_meta.json`、solution routes、solution stack-profile、父级/域级 PRD、solution E2E；任务卡声明受影响成员；影响面跨成员；Phase 3.4 先按成员提交代码，再 archive / finish-work；after_archive 在成员干净后推进 baseline 向量（不得在归档后补提交）。
   - `federated` 模式 apply 仍在各成员仓按现状运行；父级 PRD 不是 apply 输入，跨仓需求由 solution 父级任务卡以指针关联成员任务。
   - 改动面包含 `apply/reference.md`、`skills/`、`agents/`、`patches/project-wiring/apply-wiring.py`、`install.py` 装配入口。

8. **成员代码提交：Atlas 侧 `solution_commit --member`，不改上游 Trellis。**
   - 新增 `atlas solution commit --member <name> [--paths ...]`（或等价 `scripts/solution_commit.py`）。`--paths` 一律 solution-relative，先校验每个路径属于该成员并转换为成员相对路径；默认只取任务卡声明的受影响路径，不暂存成员仓其他 WIP。
   - 提交前 preflight 全部成员（路径存在 / 归属正确 / 成员可提交）；任一 preflight 失败不提交任何成员；逐成员提交，失败即停并报告已提交 / 未提交清单，不做跨仓自动回滚。
   - 提交后用 `git -C <member> diff-tree --no-commit-id --name-only -r HEAD` 校验路径确实入库（`git show` 只证明 HEAD 存在，不够）。
   - 任务卡必须声明受影响成员（`members[]`，schema 由 solution 契约定义）；`solution check` / apply 校验。`unified` 收口顺序 = Phase 3.4 成员提交 → 资产提交 → archive / after_archive 推进 baseline 向量；`federated` 由成员自己的 Trellis 流程提交。
   - `workflow.md` Phase 3.4 与 `task_store` / `config.yaml` 的 `after_archive` 接线进改动面；不修改 `safe_commit` 的暂存范围；禁止在父仓 `git add` 成员路径（实测 rc=0 但 index 空）。

9. **联合模式 E2E / 测试画像。**
   - Phase 1 采用**单网关** `app_base_url`；多 host / `targets[]` 留 Phase 4。
   - solution 最小 `stack-profile`：`product`、`apps[]`（指向成员路径）、`e2e` 段；`app_login` / `seed` / `mock` 通过显式继承一个成员画像（`inherit: <member>` 或逐字段重复）获得，不能静默缺失。
   - solution testid 只由**跨仓 cases** 派生；成员本地 testid 留在成员，不复制薄桩。
   - `e2e.reset` 在 Phase 1 只支持 solution 根执行；成员内重置留显式 `cwd` 扩展（后续阶段）。

10. **门册、结构校验与 phase 1 边界。**
   - `atlas solution check` 是新的自动检查：按 `shared/gates.md:5` 登记一行（含「不查什么」与坏输入证明）；Phase 1 语义漂移全 WARN；清单 schema / 路径逃逸是 CLI 输入错误（exit 2），不是门。
   - federated 模式 solution 根无成员结构事实时，`validate_structure` 不得直接 FAIL：生成最小 `_meta.json`（`apps: []` / `domains: []`）或以显式 `SKIP` + 原因跳过；不得静默。
   - 若后续把任一 WARN 升 FAIL，先登记门册并补「喂坏输入必红」。
   - 契约漂移 phase 1 WARN，先用真实多仓项目量化噪音。

11. **单仓零影响。** 无 solution 清单 = 旧行为；solution 命令只在 cwd 或 `--solution` 指定目录存在清单时生效。

### 2.2 考虑过的备选方案及否定理由

- **备选 A：父目录 `git init`，成员目录 gitignore**
  - 否定理由：实测同时盲掉 Qoder Grep 与 cgc；`.ignore` 只能救 Grep，救不了图谱。
- **备选 B：submodule**
  - 否定理由：父仓 `git diff` 只展开到子模块指针，文件级变更不可见。
- **备选 C：合并成 monorepo**
  - 否定理由：合法的单仓多 app 形态（`apps[]` 已覆盖），但属组织级仓拓扑 / 发布线决策；本层不阻止 monorepo，只是不为它服务。
- **备选 D：只做统一模式**
  - 否定理由：不满足「成员先各自初始化/工作、父级后整合」。
- **备选 E：只做联合模式（只读聚合，PRD 留各仓）**
  - 否定理由：不满足「父级一次初始化 + 父级 PRD 单一真相源」。
- **备选 F：两层各存一份产品 PRD**
  - 否定理由：双真相源，必然漂移。
- **备选 G：把父级 AC 直接写 `prd.md` 并扩门**
  - 否定理由：会改 `validate_e2e_index` / `validate_prd` 判据，需同批登记 gates 行与坏输入证明；本期用完整 `solution-prd.md` 复用现有语料，风险更低。
- **备选 H：phase 1 直接把契约漂移 / ignore / gitlink 做成硬门**
  - 否定理由：无真实多仓数据前属投机硬门；phase 1 先 WARN，升档另立门行。
- **备选 I：改 Trellis `safe_commit` / Phase 3.4 承载成员提交**
  - 否定理由：`safe_commit` 只负责 `.trellis` 资产；改上游会扩大兼容面。Atlas 侧 `solution_commit` 边界更清楚，宿主升级不受影响。
- **备选 J：跨仓代码图谱 / 调用链影响面**
  - 否定理由：图谱查询按项目根前缀过滤、不跨仓读出；成本大，登记为后续能力。

### 2.3 必须警惕的刺痛代价与兼容性影响

- **统一模式是一次项目模型升级**：structure 基线、图谱新鲜度、impact、closeout、apply、Trellis 提交路径都要多根感知；现有成员资产按已拍板的渐进策略在 Phase 3 逐个 `import`（不一次性迁移），每次迁入都要改域 globs 与任务路径加成员前缀并重置该成员的 baseline 向量。
- **联合模式不是零成本**：父级 PRD 必须遵守单一归属；成员 PRD 的跨仓 AC 不能与父级重复；`solution-prd.md` 是完整域 PRD，不是薄 AC 文件。
- **untracked 成员的 git 噪音**：solution `git status` 显示 `?? member/` 或 `?? members/`；只用 `-uall` + `solution status` 降噪，**禁止 `status.showUntrackedFiles=no`**。`atlas_check` 的 `git_dirty` 与 `impact_report` 的 `dirty_files` 也要排除成员根。
- **图谱新鲜度**：成员改动不改变 solution `git status`；`freshness_key` 不扩展就会静默用旧图。统一模式必须同批修，不能留到后续。多成员同父目录必须用 `-uall`，否则折叠成 `?? members/`。
- **成员提交**：`safe_commit` 不承载代码提交；`solution_commit --member` 必须断言提交存在，防止父仓 `git add` 的静默 no-op。
- **closeout / impact 的 untracked 语义**：嵌套成员 untracked 时 `ls-files --others` 只回 `member/`；非 git 成员会逐文件枚举。必须显式成员 diff 并集，禁止静默逐文件回退；路径统一 solution-relative。
- **review scope**：现有 `review_scope_core` 只覆盖 solution root；成员代码必须进 scope 或显式登记盲区，不能静默漏审。
- **成员 Atlas 版本不一致**：联合模式只读稳定字段（`_meta.json` 的 baseline / apps / domains、`stack-profile.yaml`），未知字段忽略并 WARN。
- **命名（已拍板）**：Trellis 已有 `.trellis/workspace/`（开发者工作区）；本层统一用 `atlas.solution.*` 与 `atlas solution`，不再使用 workspace 称呼。
- **打包面**：新增脚本 / 模板 / 契约文档要同步 `install.py` 装配、`package.json.files`、自检计数与 docs/map；`install.sh` 是薄 wrapper，不单列拷贝表。
- **测试计数**：新增测试文件会改变 `shared/gates.md` 的「测试文件数 / c() 条数」；实现批必须同步，不得留假计数。

---

## 3. 改动面清单

- [ ] **契约/文档**：新增 solution 契约文档（落地时与模板同批创建）；改写 `shared/stack-profile.md:16` 为「solution / 成员资产归属」；`shared/stack-profile.md` §2 只增加 solution stack-profile 的引用字段，不重复 `members[].assets`（单源在 `atlas.solution.yaml`）；`shared/layout.md` 补 solution 根 / 成员 `assets_root` 解析；`shared/closeout.md` / `shared/gates.md` 登记 solution check 行与多根口径；`shared/single-source.md` / `shared/global-rules.md` 登记迁移落点与删除纪律；`rings/structure/reference.md` 基线 v2；`apply/reference.md` 双模式输入；`docs/guide/quick-start.md` 增统一/联合两节。
- [ ] **CLI / 脚本**：`bin/atlas.js` 增 `solution` 子命令（init / adopt / import / export / status / check / lock / commit）；新增 `scripts/atlas_solution.py`；新增 `scripts/solution_commit.py`（按成员提交并断言）；新增 `_support/solution.py`（成员解析、成员 git 操作、baseline 向量、freshness key 扩展、`-uall`、ignore/gitlink/非 git 守卫）；改 `scripts/refresh_structure.py`（baseline v2、成员根豁免、原子推进、`render_tour`）；改 `adapters/_graph.py`（freshness key 成员维度 + `-uall`）；改 `scripts/impact_report.py` / `scripts/impact_reconcile.py` / `scripts/closeout_derive.py`（solution-relative 聚合、成员 untracked、diff-base/head 漂移）；改 `scripts/atlas_check.py`（`git_dirty` 排除成员根 + `-uall`）；改 `_support/review_scope_core.py` / `scripts/cli_review_convert.py`（成员 review scope）；改 `scripts/e2e_console.py`（成员 hash / dirty）；Trellis `packages` 校验（Phase 1）/生成（Phase 2）；`workflow.md` Phase 3.4 / `task_store` / `config.yaml` after_archive 接线。
- [ ] **apply / 装配**：`apply/reference.md` 的 `unified` 输入与任务卡契约；`skills/atlas-apply`（或等价技能桩）；`agents/`；`patches/project-wiring/apply-wiring.py`；`install.py` 装配入口；成员 `after_archive` 钩子的迁移/移除。
- [ ] **模板**：新增 `templates/atlas.solution.yaml`；solution 最小 `stack-profile` 模板（含 `inherit: <member>` 的 e2e 子段说明）；`templates/stack-profile.yaml` 同步 solution 引用字段（不重复成员归属）；`templates/prd/domain.md` 作为 `solution-prd.md` 的完整形态依据（不改模板正文，仅在契约中引用）。
- [ ] **测试**：`tests/test_atlas_solution.py`（双模式 init / adopt / import / export 幂等 / 路径逃逸 / 只读保护 / 锁更新 / dry-run 不写盘）；`test_solution_baseline.py`（成员 dirty 阻止推进 / 向量原子推进 / 成员根豁免 / 同父目录 `-uall`）；`test_solution_freshness.py`（成员改动触发图谱刷新 / 无全局 showUntrackedFiles）；`test_solution_impact_closeout.py`（solution-relative、成员 untracked、非 git 成员、diff-base/head 漂移）；`test_solution_guards.py`（`.gitignore`/`.ignore`/`.rgignore`/info-exclude / gitlink / 非 git 成员）；`test_solution_apply.py`（unified 任务归档 / 成员提交 / 父级 AC 可达 / `solution_commit` 断言）；`test_solution_single_source.py`（AC ID 撞号 + owner 声明 + 引用可达；语义重复显式盲区）；`test_solution_migration.py`（import 迁移清单 / globs 重写 / 钩子移除 / 旧源删除 / dry-run）；`test_solution_prd_shape.py`（`solution-prd.md` 完整域 PRD / §五 / README 追溯行）；`test_solution_review_scope.py`（成员代码进 review scope）；`test_solution_e2e_profile.py`（单网关 / 继承 app_login/seed/mock / testid 不双桩）；canonical 引用面同批核对。
- [ ] **留出验证（§4.5）**：实现批按 D156 做触发面核对；草案阶段不适用。
- [ ] **版本装配**：`package.json.files`（目录级）、`install.py` 装配、自检计数、`docs/map` 计数在实现批同步；新增测试文件后同步 `shared/gates.md` 的计数。

---

## 4. 验证与测试结果

**草案阶段未实现，未跑任何测试，不写假绿。**

实现批的最低验证面（不是当前结果）：

```bash
python3 -m pytest tests/test_atlas_solution.py tests/test_solution_baseline.py \
      tests/test_solution_freshness.py tests/test_solution_impact_closeout.py \
      tests/test_solution_guards.py tests/test_solution_apply.py \
      tests/test_solution_single_source.py tests/test_solution_migration.py \
      tests/test_solution_prd_shape.py tests/test_solution_review_scope.py \
      tests/test_solution_e2e_profile.py -q
python3 -m pytest tests/test_canonical_consistency.py tests/test_install_selfcheck.py -q
python3 -m pytest tests/ -q
python3 scripts/atlas_check.py --fast
```

实现批要求的变异钉子（每条至少咬红一条用例）：

- 摘掉成员 dirty / HEAD 检查 ⇒ `test_solution_baseline.py` 红；
- 摘掉成员根豁免（`?? member/` 计入脏）⇒ `test_solution_baseline.py` 红；
- 用默认 `git status` 不展开同父目录成员 ⇒ `test_solution_baseline.py` 红；
- 设置 `status.showUntrackedFiles=no` ⇒ `test_solution_freshness.py` 红；
- 摘掉 freshness key 的成员维度 ⇒ `test_solution_freshness.py` 红；
- 允许成员被任一 ignore 文件命中 ⇒ `test_solution_guards.py` 红；
- 允许成员路径进暂存区 / gitlink ⇒ `test_solution_guards.py` 红；
- 非 git 成员回退逐文件枚举 ⇒ `test_solution_impact_closeout.py` 红；
- 父仓 `git add` 成员路径、或提交后不断言 ⇒ `test_solution_apply.py` 红；
- 父级 AC 不可达 / AC 撞号漏检 / owner 缺失 ⇒ `test_solution_single_source.py` 与 `test_solution_prd_shape.py` 红；
- `dry-run` 写盘、`import` 漏迁任务/钩子或旧源不删除 ⇒ `test_solution_migration.py` 红；
- 成员代码不在 review scope ⇒ `test_solution_review_scope.py` 红；
- solution E2E 出现成员 testid 薄桩或缺少登录/播种 → `test_solution_e2e_profile.py` 红；
- 成员改代码但 `e2e_console` 的 `app_hash` 不变 / `repo_git_dirty` 恒脏 ⇒ `test_solution_e2e_profile.py` 红；
- `solution_commit` 路径未转换 / preflight 失败仍提交 / 只 `git show` 不 `diff-tree` ⇒ `test_solution_apply.py` 红；
- `after_archive` 先于成员提交仍推进 baseline ⇒ `test_solution_baseline.py` 红。

### 4.5 留出验证

- **草案阶段**：不适用（未改门 / 校验器 / 契约判据，未落地）。
- **实现批**：按 D156 判定触发面。若只新增只读入口、不改判据，写「不适用 + 触发面核对」；若最终决定注册门行或改校验器，必须补留出集、pre-fix 红、post-fix 绿与三态结论，并粘贴 `git diff --name-only` 与 `scripts/closeout_derive.py` 的原始输出。

---

## 5. 验收判据

1. **统一模式一次初始化**：`atlas solution init --mode unified`（Phase 2）在工作区生成唯一资产集与清单；成员仓不出现 `.atlas` / `.trellis` / `product`；父级 PRD 与域级 PRD 只在 solution 存在。
2. **联合模式事后整合**：`atlas solution adopt` 不移动、不复制成员资产；父级 PRD、`solution-prd.md`、契约声明与锁生成；`status` 能聚合成员 baseline / 分支 / 契约状态。
3. **父级 AC 可达**：`solution-prd.md` 按 `templates/prd/domain.md` 全量落盘，AC 能被 E2E 索引「关联AC 可达」读到；父级/成员 AC ID 撞号与 owner 缺失被检出；语义重复作为显式盲区记录。
4. **单一归属**：同一 AC ID / 用例 / 域事实不会同时出现在 solution 与成员两层；归属声明缺失或 AC ID 撞号 ⇒ 报告；mixed 态每个成员只有一个 owner。
5. **迁移**：`import` 先 dry-run 且不写盘，迁移 PRD/结构/E2E/任务/workspace/测试约定/钩子，旧源删除（历史归 git），globs 加成员前缀，baseline 向量重置；`status` 从 `mixed` 回到 `unified`；`export` 反向可行（后续阶段）。
6. **搜索 / 图谱可见性**：成员目录 untracked 且不被 `.gitignore` / `.ignore` / `.rgignore` / info-exclude 命中；所有消费者用 `-uall`，无全局 `showUntrackedFiles=no`；成员改动后 cgc 图谱新鲜度键变化；`atlas_check` 与 `impact_report` 的脏文件计数不把 `?? member/` 或 `?? members/` 计入；`e2e_console` 的 `app_hash` 随成员改动变化、`repo_git_dirty` 不因 solution 根 `?? members/` 恒脏。
7. **基线正确性**：任一成员 dirty / HEAD 移动 ⇒ solution baseline 不推进并指名成员；全部干净 ⇒ 向量原子推进；`render_tour` 正确渲染向量；`after_archive` 在成员提交后推进。
8. **影响面 / 收口**：成员内部改动不会被 solution `git diff` 漏掉；actual 集以 solution-relative 路径聚合（含 untracked）；工作区 untracked 成员目录不污染 closeout 列表；非 git 成员显式报错而非逐文件回退；review scope 覆盖成员代码或显式登记盲区。
9. **Trellis / apply**：统一模式任务收口用 `solution_commit --member`（preflight / 路径转换 / `diff-tree` 断言）按成员仓提交；Phase 3.4 成员提交先于 archive / after_archive；`apply` 技能读取 solution 任务/PRD/结构/画像；联合模式成员 Trellis 与 apply 行为不变。
10. **单仓零影响 + 门禁纪律**：无清单时 `atlas check` / `apply` / `review` / `closeout` 行为零变化；`atlas solution check` 已在 `shared/gates.md` 登记并配坏输入证明；Phase 1 工作区 check 无语义硬门；实现批全量 `pytest tests/` 绿，canonical 无新增幻影引用，`shared/gates.md` 计数同步。

---

## 6. 拍板记录（2026-11-04）

1. **命名**：采用 `solution`。Trellis 的 `.trellis/workspace/` 保持原义；本层命令与文件统一 `atlas solution` / `atlas.solution.*`，不再使用 workspace 称呼。
2. **默认模式**：长期默认 = 绿地无成员资产 → `unified`；已有成员资产 → `federated`；`--mode` 可覆盖。Phase 1 构建只交付 federated，`init --mode unified` 显式拒绝并提示 Phase 2。
3. **父级 AC 落点**：`product/prd/solution-prd.md`，且必须是完整域 PRD（`domain_code: SOLUTION`、`AC-SOLUTION-NNN`、FN/R/AC、§五三列 AC 表、结构类 AC 清单；`prd.md` §五列出 `solution`，README 追溯行）。扩门扫 `prd.md` 留作后续备选。
4. **迁移策略**：渐进 `import`。现有成员资产先保持 `federated`，Phase 3 逐个迁入 `unified`；不采用一次性大爆炸迁移；迁移后旧源删除（历史归 git）。
5. **Phase 顺序**：先 Phase 1（联合模式），再 Phase 2（统一模式 + multi-root actual 同批）；已定。
6. **成员提交**：采用 Atlas 侧 `solution_commit --member`（solution-relative 路径转换、跨成员 preflight、失败报告、`diff-tree` 断言），不改上游 Trellis 的 `safe_commit`；Phase 3.4 必须在 archive / after_archive 前完成成员提交。
7. **跨仓 E2E**：Phase 1 单网关 `app_base_url`；多 host / `targets[]` 留 Phase 4；solution 从成员画像继承 `app_login` / `seed` / `mock`。
8. **父级任务索引**：联合模式下可选；仅当存在跨仓需求时建议建立。
9. **实现批验证门槛**：多仓 freshness 必须在真实 cgc 上复测通过才允许 Phase 2 合入；这是验证门槛，不是开放设计问题。

---

## 7. 分期与试点

- **Phase 1（联合模式可用）**：清单 / 父级 PRD + 完整 `solution-prd.md` / 契约锁 / `status` / `check` / `adopt` / solution 最小画像 / Trellis packages 校验（仅当 `.trellis/config.yaml` 已存在；生成归 Phase 2）；只读聚合，不改成员资产；无语义硬门；Phase 1 `init` 只接受 federated（unified 显式拒绝并提示 Phase 2）；e2e_console 成员 hash / dirty 同批修（跨仓 E2E 依赖）。满足「子级先工作、父级后整合」；现有成员资产保持 `federated`。

> **状态注记（2026-11-07）**：Phase 1 后续新增的 `atlas solution check --strict` 是 **opt-in** 的结构 / 可复现门（锁缺失、未跟踪、与父仓 HEAD 不一致、成员 dirty、缺 URL、版本/契约漂移 ⇒ FAIL 且 exit 1）；默认 `check` 仍全 WARN，不判跨仓语义兼容。原「无语义硬门」的决策段落保持不变。

- **Phase 2（统一模式核心，含多根对账）**：`init --mode unified`；solution 自有资产；baseline v2 + 成员向量 + 成员根豁免 + `-uall`；freshness key 多根；**impact / closeout 的 actual 并集与 baseline v2 同批交付**；structure / PRD / E2E / apply 技能在 solution；Trellis packages 生成 + 工作区 Trellis；`solution_commit --member` + Phase 3.4 / task_store 时序；**统一模式不得在 multi-root actual 完成前开放**，防止假绿。
- **Phase 3（跨仓聚合与迁移）**：跨仓 AC 聚合；`import` / `export` 迁移；mixed 态收口；现有成员资产按已拍板的渐进策略逐个迁入（旧源删除，历史归 git；每次迁完回到可运行状态）。
- **Phase 4（可选增强）**：多 host / `targets[]`、跨仓影响面 / 图谱、成员拆分导出、更多宿主集成。
- **试点**：同一真实多仓产品先跑 Phase 1 的联合整合，量化父级 PRD 与契约锁噪音；Phase 2 再迁入统一模式，记录 baseline 重置、globs 重写、Trellis 任务迁移成本。试点数据决定 Phase 3 是否升门。

---

## 8. 评审回执（2026-11-04）

### 8.1 第一轮（workspace 草稿）

只读评审 3 Blocker / 10 Major / 4 Minor；主审已逐条复现并回写。评审时本层暂名 workspace，2026-11-04 拍板改名 solution；下表旧称按语义对应。

| 编号 | 结论 | 修订落点 |
|---|---|---|
| B1 baseline 永久冻结 | 接受（`clean_exempt_prefixes` 不含成员根，已复现） | §2.1.5、§3、§4、§5.7 |
| B2 父级 AC 不可达 | 接受（E2E 语料只 `*-prd.md`，已复现） | §2.1.3、§2.2-G、§5.3 |
| B3 `apply` 全链缺失 | 接受（apply 是技能，输入全按单仓） | §2.1.7、§3、§5.9 |
| M1 契约/消费者漏列 | 接受（含 `render_tour`、layout 资产根、baseline 消费者） | §2.1.5、§3 |
| M2 impact 多根不足 | 接受（untracked 盲、head 只比 solution） | §2.1.5、§3、§4、§5.8 |
| M3 closeout 漏成员 | 接受（`ls-files --others` 只回 `member/`，已实测） | §2.1.5、§3、§4 |
| M4 ignore 守卫不足 | 接受（`.ignore` 不进 `git check-ignore`） | §2.1.4、§3、§4 |
| M5 import 丢任务/双源 | 接受 | §2.1.6、§3、§4、§5.5 |
| M6 safe_commit 静默丢提交 | 接受（父仓 `git add` rc=0 但 index 空，已实测） | §2.1.8、§3、§4、§5.9 |
| M7 单一归属判据/门册 | 部分接受：语义重复降为显式盲区；solution check phase 1 全 WARN；升 FAIL 先登记 gates 行 | §2.1.2、§2.1.10、§5.10 |
| M8 联合 E2E 无画像 | 接受（solution 最小 `stack-profile`/apps/reset） | §2.1.9、§3、§5 |
| M9 开放问题自相矛盾 | 接受（改为 §6 拍板记录） | §6 |
| M10 阶段盲窗 | 接受（multi-root actual 与 baseline v2 同批进 Phase 2；否则不开放 unified） | §7 |
| Minor dirty 计数 | 接受（`atlas_check`/`impact_report` 排除成员根） | §2.3、§3、§5.6 |
| Minor 打包面 | 部分接受：`install.py` 是装配单源，`install.sh` 是薄 wrapper，不单列拷贝表；`package.json.files` 与自检计数仍须同步 | §2.3、§3 |
| Minor 非 git 成员 | 接受（显式报错，禁止逐文件回退） | §2.1.4、§3、§5.8 |
| Minor E2E reset cwd | 接受（成员内重置需显式 cwd，不默默用错根） | §2.1.9 |

### 8.2 第二轮（solution 定稿）

第二轮 3 Blocker / 6 Major / 2 Minor；主审已抽验并回写：

| 编号 | 结论 | 修订落点 |
|---|---|---|
| B1 untracked 折叠 / `showUntrackedFiles=no` 盲区 | 接受（默认 status 只回 `?? members/`；`-uall` 才逐成员；config 会让消费者全盲，已实测） | §1.3、§2.1.4、§2.1.5、§3、§4、§5.6 |
| B2 `solution-prd.md` 非即插即用 | 接受（`validate_prd` 要求完整域 PRD；已读门源码） | §2.1.3、§3、§4、§5.3、§6.3 |
| B3 成员提交选错文件 | 接受（`safe_commit` 只暂存 `.trellis`；代码提交在 Phase 3.4，已读源码/实测） | §2.1.8、§3、§4、§5.9、§6.6 |
| M1 `member:path` 与预测集不一致 / review scope 漏成员 | 接受（统一 solution-relative；review scope 进改动面） | §2.1.5、§3、§4、§5.8 |
| M2 manifest 双源 / init 职责未定 | 接受（`atlas.solution.yaml` 单源；`atlas.config.yaml` + `install.py` 职责写明；Trellis packages 派生） | §2.1.6、§3 |
| M3 mixed 语义 / 归档违反 single-source | 接受（受支持迁移态 + 消费者矩阵；旧源删除，历史归 git） | §0、§2.1.5、§2.1.6、§5.5 |
| M4 门册/调度矛盾；归属声明无形态 | 接受（登记 solution check 行；AC owner 列；federated 最小 `_meta`/显式 SKIP） | §2.1.2、§2.1.10、§3、§5.4 |
| M5 E2E 画像不足 | 接受（单网关 Phase 1；继承 `app_login`/`seed`/`mock`；testid 不双桩；reset cwd 延后） | §2.1.9、§3、§4、§5 |
| M6 Phase 1 默认指向未交付 unified | 接受（Phase 1 只接受 federated；长期默认 Phase 2 恢复） | §2.1.1、§6.2、§7 |
| m1 钉子错位/缺正反控 | 接受（钉子归位；补 render_tour/dirty/owner/mixed/路径逃逸/dry-run 正反控） | §4 |
| m2 计数/开放项/回执 | 接受（实现批同步 gates 计数；回执分两轮；`e2e.reset` 已定 Phase 1 范围；`package.json.files` 为目录级） | §3、§4、§8 |

### 8.3 窄复核（B1/B2/B3，2026-11-04）

只复核三处修复是否闭合；结论：

- **B1：未闭合 → 已补。** `scripts/e2e_console.py:126-128` 的 `repo_git_dirty` 与 `:356-370` 的 `ls-files -o` 在 solution 根对嵌套成员只回目录，成员改代码后 `app_hash` 不变；已加入 §1.4 / §2.1.5 / §3 / §4 / §5.6，并把「共同祖先过滤」改为逐成员根精确过滤（共同祖先会豁免同目录非成员脏文件）。
- **B2：闭合（按模板）→ 已补字段。** 以 `templates/prd/domain.md` 全量为准，补 `domain_name` / `doc` / `version` / `date` / `status`、§二「功能清单」、FN→规则、§四「所属功能」第 3 列、README 7 列计数；结构类 AC 清单必填、不可验清单可选。
- **B3：未闭合 → 已补。** 补 Phase 3.4 成员提交入口、`solution_commit` 的 solution-relative 路径转换 / preflight / 失败报告 / `diff-tree` 断言、任务卡 `members[]` schema，以及 Phase 3.4 → archive → after_archive 的时序；`safe_commit` 不改。
- **窄复核原判定**：可进 Phase 1；B1 的 `e2e_console` 与 B3 在 Phase 1/Phase 2 前同批闭合。本 RFC 已将 `e2e_console` 放入 Phase 1，`solution_commit` 放入 Phase 2。
