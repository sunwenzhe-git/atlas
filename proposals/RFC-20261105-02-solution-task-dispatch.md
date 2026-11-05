# 跨仓任务编排（solution task）：父级需求 → 成员任务卡（Phase 1 增量）

> 提案编号：RFC-20261105-02
> 提案作者：Atlas 方案会话（待维护者指派独立评审）
> 关联状态：已实现（Implemented；2026-11-05，未提交；实现后评审已修 blocker）
> 影响范围：solution 契约（`shared/solution.md`）· CLI（`bin/atlas.js`）· 脚本（`scripts/atlas_solution.py`、新增 `_support/solution_task.py`）· 模板（`templates/atlas.solution.yaml`）· 测试（`tests/`）· docs/quick-start
> 关联：`RFC-20261104-02`（solution Phase 1）；`shared/solution.md`；`shared/gates.md`；`shared/single-source.md`
> 同日避号：`RFC-20261105-01` 已占用，本批取 `-02`。
> 评审修订：本版吸收 3 Blocker + 9 Major；重点改为 `--no-start`、curated context、meta 幂等、scope 单源、live status。

---

## 0. 术语

- **父级 requirement**：`solution-prd.md` 中的跨仓 AC，映射到多个成员仓的本地任务。
- **成员任务卡**：成员仓 `.trellis/tasks/<MM-DD-slug>/` 下的 Trellis 任务；由本命令创建，但不由本命令启动/领取。
- **派单**：父级 requirement → 成员任务卡的创建；**不等于**成员领取或开始执行。

---

## 1. 现象与取证

### 1.1 触发形态

- Phase 1 的父级 solution 层已有 PRD、契约锁、`status/check/lock`；父级没有 Trellis/apply。
- 「父级写一条跨仓 AC」到「三个成员仓出现对应任务」之间没有桥，必须人工逐仓建任务，容易漏成员/漏 AC/scope 不一致。

### 1.2 客观证据

- `shared/solution.md` §6：Phase 1 不提供父级 apply，apply 在成员仓。
- `_support/solution.py` 只登记 `requirements` 是否存在，不解析；`solution check` 无 requirement ↔ task 对账。
- 成员任务由各仓 `.trellis/scripts/task.py` 管理，没有跨仓队列。

### 1.3 评审取证（2026-11-05 只读评审，主审已复核）

- `task.py create` 默认 `set_active_task`；`--no-start` 才跳过（`task_store.py` create 尾部）；不传会把派单任务挂成当前 session 的 active task。
- `task.py create` 默认 assignee/creator 取 `.trellis/.developer`；三成员当前均为 `agent_learning`；不显式 `--assignee` 时人类 `list --mine` 看不到。
- `task.py start` 有 context-manifest gate：`implement.jsonl`/`check.jsonl` 为空 ⇒ 拒绝 start（`task.py` start 段）；create 在子代理平台只种空文件，必须 `task.py add-context` 才能启动。
- `task.py create` 目录名 = `MM-DD-<slug>`；同日同名拒绝，跨日同 slug 可再建，归档后同名永久拒绝；`--meta key=value` 可落 `task.json.meta`；`--slug` 拒绝路径分隔符与 `MM-DD-` 前缀。
- `--description` 会写入 `prd.md`；若 scope 同时写 manifest 和 `solution.md`，会形成三处正文。
- 现有 `shared/solution.md` / `scripts/atlas_solution.py` / `_support/solution.py` / `shared/gates.md` 仍写「只读、不碰成员」；本能力需要窄写成员 `.trellis/tasks`，必须同批改口径。

---

## 2. 决策与权衡

### 2.1 核心定案

1. **只自动化「父级 requirement → 成员任务卡」，不自动化领取/启动。**
   - `create` 固定传 `--no-start`，不设置 active task；不写 `.runtime` 当前指针。
   - `create` 后由 atlas 调 `task.py add-context` 写 curated 指针，使成员之后能正常 `/trellis:start`；仍由成员决定何时启动。
   - 「父级派单后成员自动开始」不在本 RFC；归 Phase 4 另案（需要跨仓队列/宿主调度/权限）。

2. **父级 AC 单源；`requirements[]` 只存映射与本地 scope。**
   - AC 正文只在 `solution-prd.md`；`requirements[].acs` 是引用，不是第二份 AC。
   - 现有 AC 表 `owner: solution|member` 仍是唯一归属声明；requirements 不得与之矛盾。
   - 清单采用扁平 per-member 条目（便于现有受限解析器）：
     ```yaml
     requirements:
       - id: REQ-001
         acs: AC-SOLUTION-001、AC-SOLUTION-002
         member: member-a
         task_slug: req-001-api
         assignee: member-a-dev        # 可选；缺省 = 成员 .trellis/.developer
         scope: "实现同步触发与查询 API"   # 单行；含 # / : 时必须加引号
       - id: REQ-001
         acs: AC-SOLUTION-001
         member: member-b
         task_slug: req-001-ui
         scope: "接入同步入口与记录页"
     ```
   - `acs` 支持 `、` / `,` 分隔，逐个校验在 `solution-prd.md` 的 AC 表定义行存在；同一 `id+member` 唯一；`member` 必须在 `members[]`；`task_slug` 必须符合 Trellis 规则且冻结。
   - `requirements` 段缺失 = 合法降级（Phase 1 只读行为不变）。

3. **命令：`atlas solution task create|status`。**
   - `create` 默认 **dry-run**；`--apply` 才写盘；stdout 明确 `DRY-RUN 未写盘，需 --apply`。
   - 写入前 preflight 全部成员：
     - manifest / requirements / AC 定义 / member / slug 合法性；
     - 成员 `task.py create --help` 能力探针（`--no-start` / `--meta` / `--assignee` / `add-context`）；
     - 同日同名、跨日同 slug、归档同名冲突；
     - `.trellis/.developer` / assignee 可解析。
   - 任一 preflight 失败 ⇒ 不写任何成员，exit 2 并指名。
   - 逐成员写入：`task.py create --no-start --assignee ... --meta solution=<名> --meta requirement=<id> --meta member=<member> --slug <slug> --description "<指针>"`；随后扫描 `tasks/` + `tasks/archive/` 的 `task.json.meta` 找到任务目录，写 `solution.md`，再 `task.py add-context <dir> implement <solution.md> "跨仓任务父级指针"` 与 `check` 同理。
   - `--description` 只放一行指针（父级 AC / `solution.md`），**不复制 scope**；scope 只在 `solution.md`。
   - 失败即停并报告已写/未写；不自动 commit/push；不做跨仓自动回滚。
   - `--resume`：已存在且 meta + `solution.md` 指针一致 ⇒ 跳过；不一致 ⇒ 拒绝，提示 `--update`。
   - `--member` 可只重试某个成员。
   - `--update`：只更新 `solution.md` 指针与父级 AC 引用；**不改**成员 `prd.md` / `task.json` / `description`。
   - `status`：只读列出 requirement → 成员任务（active/archive）存在性、task 路径、AC 定义行、契约状态；缺任务/任务删除/AC 不存在 ⇒ WARN；`--json` 可机读。

4. **任务卡形态：复用 Trellis，不另造任务系统。**
   - 任务标题带父级 AC（如 `[AC-SOLUTION-001] 跨仓同步 API`）。
   - `solution.md` 是跨仓指针 + 本地 scope + 契约 ID + 父级 PRD 相对路径；不是第二份需求。
   - 不改 Trellis 的 `task.json`/`prd.md` 结构；`--meta` 是幂等键的落点。
   - 不创建父级 `.trellis`；不写成员代码/资产；不自动 start。

5. **锁定与对账：live 状态优先，lock 只做可选快照。**
   - `solution task status` / `solution check` 实时读 manifest + 成员任务目录，不依赖 lock。
   - `atlas.solution.lock.json` 可选记录 requirements 映射；lock 缺失/早于派单只 INFO/SKIP，不误报 WARN；lock 有映射但与 live 不一致才 WARN。
   - 缺成员任务 / 任务删除 / AC 不存在 ⇒ WARN（Phase 1 增量不升 FAIL）。

6. **契约口径同步。**
   - `shared/solution.md` 从「只读、不碰成员」改为「父级只窄写成员 `.trellis/tasks`（任务卡/指针/context），不写代码/资产/PRD」。
   - `scripts/atlas_solution.py` / `_support/solution.py` 的模块 docstring、`shared/gates.md` 的 solution 行「查什么/不查什么」同批改。
   - 这是 Phase 1 的**窄写例外**，不是 Phase 1 变成写模式。

7. **Phase 名称与门册。**
   - 本能力称「Phase 1 增量（solution task）」，不重编 RFC-04-02 的 Phase 3/4。
   - 新增 `tests/test_solution_task.py` ⇒ 测试文件数 +1；`shared/gates.md` 的 `solution` 行补 `task create/status` 与盲区；按 `gates.md:5` 登记，Phase 1 增量全 WARN。
   - `check_solution` 删除「requirements 不解析」WARN，改为 requirement↔task 对账（WARN）。

### 2.2 备选方案与否定理由

- **A：父级建 Trellis，任务放父级**：Phase 1 成员 apply 不消费父级任务；会变成第二套任务系统。
- **B：复制父级 AC 全文进成员任务**：违反 `shared/single-source.md`；父级 AC 更新会漂移。
- **C：直接写 `.trellis/tasks` 目录**：绕过 Trellis 的 developer/workspace/模板/校验；任务形态随版本漂移。
- **D：自动领取/自动启动**：Trellis 无跨仓队列；涉及宿主调度/并发/权限，归 Phase 4 另案。
- **E：用 `--description` 承载完整 scope**：会写入 `prd.md`，与 `solution.md`/manifest 三处正文；否定。
- **F：用目录名/slug 做幂等键**：Trellis 目录带 `MM-DD-`，跨日/归档/重命名会漂移；否定，改用 `--meta`。

### 2.3 代价与兼容性

- `create` 会写成员 `.trellis/tasks`（任务卡/context），但不 commit；失败/重复显式报告；无跨仓自动回滚。
- 成员 Trellis 版本差异：只依赖 `--no-start` / `--meta` / `--assignee` / `add-context` 稳定参数；能力探针失败即报错，不降级手写目录。
- 父级 AC 路径跨根：任务卡只存相对路径指针；成员 agent 需能读 solution 根（工作区包含）；不复制 PRD。
- `requirements` 从「只登记」升级为「解析 + 对账」；旧清单无该段仍合法。
- 锁不承担注册表职责，避免 create 未 lock 时全量假 WARN。

---

## 3. 改动面清单

- [ ] **契约/文档**：`shared/solution.md` 增 `requirements[]` 字段、`task create|status` 契约、父级窄写例外；`shared/gates.md` 的 solution 行补 task 对账/盲区；`docs/guide/quick-start.md` 增「跨仓任务」；`templates/atlas.solution.yaml` 补 requirements 注释样板。
- [ ] **CLI / 脚本**：`bin/atlas.js` help 增 `solution task`；`scripts/atlas_solution.py` 增 `task create|status`；新增 `_support/solution_task.py`（requirements 解析、AC 定义行校验、preflight、task.py 能力探针、create/no-start/meta/add-context、solution.md、幂等/resume/update、status、live 对账）。
- [ ] **现有 solution 代码**：`_support/solution.py` 的 `_manifest_text` / manifest 解析 / `check_solution` 支持 requirements；删除「requirements 不解析」WARN；`read_lock` 兼容可选 requirements。
- [ ] **模板**：可选 `templates/solution/task-pointer.md`；`templates/atlas.solution.yaml` 增 requirements 注释块（不强制字段）。
- [ ] **测试**：`tests/test_solution_task.py`（requirements/ac/member/slug 校验、dry-run 零写、preflight 零写、--no-start 无 active、add-context 后 start 可达、meta 幂等跨日/归档、resume、--update 不改 prd/task.json、缺 task.py 报错、status live/lock、scope 引号、AC 定义行）；真实 Trellis `task.py` 契约夹具（pin 版）而非纯 fake。
- [ ] **门册/计数**：新增测试文件后同步 `shared/gates.md` 的 55→56 与 `docs/map` 行数/计数；`gates.md:5` 登记行。
- [ ] **留出验证（§4.5）**：实现批按 D156 做触发面核对；草案阶段不适用。

---

## 4. 验证与测试结果

**草案阶段未实现，未跑任何测试，不写假绿。**

实现批最低验证面：

```bash
python3 -m pytest tests/test_solution_task.py -q
python3 -m pytest tests/test_canonical_consistency.py tests/test_install_selfcheck.py -q
python3 -m pytest tests/ -q
```

变异钉子（每条至少咬红一条用例）：

- 不传 `--no-start` ⇒ `no active task` 用例红；
- create 后不 `add-context` ⇒ `start 可达` 用例红；
- 去掉 AC 定义行校验 ⇒ AC 不存在用例红；
- 去掉 member/slug 校验 ⇒ 对应用例红；
- dry-run 写盘 / preflight 失败写前成员 ⇒ 零写用例红；
- 只用目录名做幂等 ⇒ 跨日/归档幂等用例红；
- `--update` 覆盖 `prd.md`/`task.json` ⇒ 用例红；
- lock 当注册表 ⇒ create 未 lock 假 WARN 用例红；
- status 漏 archive 任务 ⇒ 用例红。

### 4.5 留出验证

- 实现批验证（2026-11-05）：全量 `pytest tests/ -q` = **1236 passed, 6 skipped**；真实 Trellis 副本实测 `create` / `--no-start` / `--meta` / `add-context` / `start` / `archive/2026-11` 通过；变异钉尚未逐条注入，门册保持 `待复核`，不冒充出厂级。
- 设计层：不适用（未改门/校验器判据；新增 `solution task` 写面登记在 `shared/gates.md`）。
- 实现批：若只新增只读 `status`/WARN 对账，写「不适用 + 触发面核对」；若把 task 对账升 FAIL 或改 `solution check` 判据，按 D156 补留出集与三态证据。

---

## 5. 验收判据

1. `atlas solution task create --requirement REQ-001 --dry-run` 在真实 Trellis 夹具上只打印计划，零写盘。
2. `--apply` 为每个成员创建任务：`task.json.meta` 含 solution/requirement/member；任务未被设为 active；`solution.md` 存在；`implement.jsonl`/`check.jsonl` 有 curated 指针；`/trellis:start` 可继续（不因空 context 拒绝）。
3. 任一成员缺 `task.py` / AC 定义行不存在 / member 不存在 / slug 冲突 ⇒ 不写任何成员，exit 2。
4. 重复 create 同一 requirement+member：同日/跨日/归档都识别并拒绝；`--resume` 一致则跳过，`--update` 只更新 `solution.md`。
5. `--description` 与 `prd.md` 不含完整 scope；scope 只在 `solution.md`；不复制父级 AC 正文。
6. `atlas solution task status --json` 实时扫描 active+archive；缺任务/任务删除/AC 不存在 WARN；lock 缺失不误报。
7. 不创建父级 `.trellis`、不自动 start、不自动 commit/push、不写成员代码/资产/PRD。
8. 无 `requirements[]` 的旧清单行为不变；单仓项目零影响。
9. 全量 `pytest tests/` 绿，canonical 无新增幻影引用，gates/docs 计数同步。

---

## 6. 拍板项（实现前）

1. **需求源**：`requirements[]` 放 `atlas.solution.yaml`（推荐；扁平 per-member）还是独立 `product/requirements/<id>.yaml`？
2. **任务卡形态**：`task.py create --no-start --meta ...` + 兄弟 `solution.md` + `add-context`（推荐），还是只写 `task.json` 扩展字段？
3. **`--update` 语义**：只更新 `solution.md` 指针（推荐），还是允许同步 description/scope？
4. **lock**：`requirements` 映射进 `atlas.solution.lock.json` 只做可选快照（推荐），还是独立 `solution-task.lock.json`？
5. **多 AC**：`acs` 用顿号/逗号分隔（推荐），还是每个 AC 一行？
6. **父级窄写授权**：是否明确允许父级 `solution task` 只写成员 `.trellis/tasks`（任务卡/指针/context），不写代码/资产/PRD？推荐是；这是本 RFC 的唯一写面。

---

## 7. 分期

- **Phase 1 增量（本 RFC）**：`solution task create|status` + requirements 解析 + live 对账（WARN）；不自动领取、不父级 apply、不写成员代码。
- **Phase 2**：unified 模式接入父级 apply/Trellis；task 映射与 workspace 任务进一步合并。
- **Phase 4（另案）**：跨仓队列/自动领取/宿主调度；需要新的权限与并发模型，不在本 RFC。

---

## 8. 评审回执（2026-11-05）

只读评审 3 Blocker + 9 Major；主审已按 Trellis 源码复核并回写：

| 编号 | 结论 | 修订落点 |
|---|---|---|
| B1 create 默认 active/assignee 是 agent | 接受；`--no-start` + 显式 `--assignee` | §2.1.1、§2.1.3、§5.2 |
| B2 start 被 empty context gate 拒绝 | 接受；create 后 `add-context` implement/check | §2.1.1、§2.1.3、§5.2 |
| B3 幂等键/update 无落点 | 接受；`--meta solution/requirement/member`，扫 active+archive，slug 冻结 | §2.1.2、§2.1.3、§5.4 |
| M1 scope 三处正文 | 接受；description 只放指针，scope 只在 `solution.md` | §2.1.3、§2.2-E |
| M2 lock 当注册表 | 接受；live 优先，lock 只可选快照 | §2.1.5、§5.6 |
| M3 只读契约残留 | 接受；同批改 `shared/solution.md` / docstring / gates 行 | §2.1.6、§3 |
| M4 AC 归属双源 | 接受；AC 表 owner 唯一，requirements 只引用 | §2.1.2 |
| M5 单值 ac 不够 | 接受；`acs` 顿号/逗号分隔 | §2.1.2、§6.5 |
| M6 preflight 缺 slug/能力探针 | 接受；preflight 加 slug 规则 + task.py 能力探针 | §2.1.3 |
| M7 部分失败不可续跑 | 接受；`--resume` / `--member` | §2.1.3、§5.4 |
| M8 fake task.py 掩盖真实形态 | 接受；真实 Trellis 契约夹具 | §3、§4 |
| M9 门册/分期冲突 | 接受；改称 Phase 1 增量，登记 gates 行与计数 | §2.1.7、§3 |
| Minor（manifest/template/check 文案、dry-run 提示、scope `#`、AC 定义行） | 接受 | §2.1.2、§2.1.3、§3、§5 |

### 8.1 实现后评审（2026-11-05）

实现后只读评审 2 Blocker + 7 Major；主审已复核并修复：

| 编号 | 结论 | 修订落点 |
|---|---|---|
| 归档布局 `archive/<YYYY-MM>/` 扫不到 | 接受；`_task_json` 改 `rglob`，slug 冲突扫全部任务目录 | `_support/solution_task.py` |
| 部分写/status 漏 context | 接受；`_context_ok`、`--resume` 补 context、`status` 报 context WARN | `_support/solution_task.py`、测试 |
| `--dry-run` 未暴露 | 接受；CLI 增加 `--dry-run`，默认仍 dry-run | `scripts/atlas_solution.py` |
| assignee 解析与 Trellis 不一致 | 接受；`TRELLIS_DEVELOPER` → 成员 `.developer` → 主 worktree | `_support/solution_task.py` |
| 跨日 slug、`--update` 无任务、status 空 requirement | 接受；改 rglob 冲突、update 需已存在、status 报不存在 | `_support/solution_task.py` |
| 成员未知键静默 | 接受；`check_solution` 报 WARN | `_support/solution.py` |
| 测试/fake 与真实行为差距 | 接受；补 archive/context/跨日/assignee env/CLI dry-run，真实 Trellis 探针可 skip | `tests/test_solution_task.py` |
| RFC 状态/结果未回写 | 接受；本文件状态与 §4 已更新 | 本 RFC |
