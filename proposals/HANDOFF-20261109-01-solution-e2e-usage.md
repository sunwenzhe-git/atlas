# 交接文档：父仓跨仓 E2E（`solution e2e`）使用与判定

> **读者**：没读过 RFC、没参与实现的 agent。  
> **目标**：拿到一个 federated 多仓仓库后，能判断哪些用例属于跨仓用例、怎么配、怎么跑、怎么读结果。  
> **基线**：`/Users/sunwenzhe/Desktop/跨网传输` 的 `.atlas` 已更新到 `beace88410424417`；本文命令都以该仓为工作目录。  
> **性质**：交接材料，不提交、不进 changelog。分析采纳仓时**只读**，不要为了凑绿改任何成员仓文件。

## 快速结论（先看这 6 句）

1. **父仓**（solution 根，有 `atlas.solution.yaml` 且 `mode: federated`）持有跨仓 E2E；**成员仓**只保留自己的本地 E2E。
2. 一条用例是不是跨仓用例，不看它名字里有没有 `CROSS`，也不看它挂了哪个 AC；看它**是否必须同时观察多个仓的运行结果才能判定通过**。
3. 父仓跨仓用例的入口是：父仓 `product/e2e/cases/*.md` 分片 + 父仓 `product/e2e/e2e-index.md` 行 + 父仓 `atlas.solution.yaml` 的 `requirements[].case_ids`。**三者缺一，选择器就选不到。**
4. 单成员需求如果确实没有跨仓 E2E，写 `cross_repo_e2e: none`；**不要**把它当成 PASS，它是 `N/A`。
5. 看状态用 `atlas solution e2e status`；看配置门用 `atlas solution e2e verify`。两者退出码语义不同（`status` 会返回 3，`verify` 只返回 0/1）。
6. 二期只读视图**不写成员账本/索引**。唯一的写动作是显式 `--snapshot`，且只写父仓 `reviews/aggregate/`。

---

## 1. 这版做了什么

### 1.1 一期：父仓持跨仓 E2E 的契约与门

**解决的问题**：多仓方案里，一条业务流程会穿过多个成员仓（例如“租户页发起 → 项目页确认 → 后端写记录 → 记录页查询”）。这种流程的 E2E 如果放在任何单一成员仓，都会缺另一半环境；如果每个成员各写一半，就会互相甩锅，也会退化成 N 个控制台。

一期的做法：

- 把 **solution 根**变成合法 E2E 根：`<assets_root>/e2e/` 与单仓同构，有 `e2e-index.md`、`cases/`、`scripts/`、`reviews/`。
- 跨仓用例统一挂**虚拟页 `solution-flow`**。`pages[]` 只登记这个虚拟页，不把成员的真实页面塞进父仓索引。
- 跨仓用例在**父仓控制台**执行（`atlas console --root <solution>`），不接管成员执行。
- 用 **`requirements[].case_ids`** 做唯一选例真相；索引里的 `需求` / `关联AC` 列只做追溯，不参与选择。
- 给父仓用例加 **`成员依赖:`** 必填字段：它不承担 stale 粒度，只负责“被依赖成员缺失 ⇒ 该用例 BLOCKED”和“名字必须在清单内”。
- 增加机器门：
  - 多成员需求必须声明 `case_ids`，禁止 `cross_repo_e2e: none`；
  - 单成员需求 `case_ids` 或 `cross_repo_e2e: none` 二选一，两者都无 ⇒ FAIL；
  - `case_ids` 必须指向父仓索引里真实存在的用例；
  - 选择器必须接线（`selected` 与 `case_ids` 一致）；
  - 索引 `需求` 列与消费方一致；
  - 孤儿用例只 WARN，不自动删。

**一期边界**：不表达成员页面级 `pages[]`；只支持父仓同源网关；不做跨仓 AC crosswalk；不接管成员执行与评审。

### 1.2 二期：只读聚合视图

**解决的问题**：一期能回答“跨仓用例是谁、配了没”，但回答不了“现在各成员本地 E2E 和跨仓用例分别到什么状态”。二期加一个**只读视图**，让父仓一次看到：

- 本需求的父仓跨仓用例：执行态、评审态、成员依赖、阻断原因；
- 每个成员仓的本地 E2E 摘要：总条数、`green/red/blocked/skipped` 计数、`fresh/stale/unreviewed/legacy` 计数、最近提交情况；
- 父仓 AC 反向覆盖信号。

二期的关键取舍：

- **成员 `review_state` 按成员根重算**：用成员自己的 `repo_provenance` / `review_fingerprint`，不用父仓根。只读计算，不落盘、不重签。
- 父仓用例自身的 `review_state` 用父仓根，并标记 `solution_root=True`：有 `reviewed.pass` 但没有 run-time provenance ⇒ `stale`（fail-closed）。
- 成员 `missing`（路径缺失/不是 git）且被父仓用例 `成员依赖` 引用 ⇒ 该父仓用例 `blocked`。
- `--snapshot` 是唯一写动作，只写父仓 `<assets_root>/e2e/reviews/aggregate/`。

**二期边界**：不执行成员用例、不回写成员索引/账本、不替代成员评审、不产生第二套 runner、不做成员状态的第二份账本。

### 1.3 两期一句话区分

- **一期**：把跨仓用例**放对地方、配好选择器、装上机器门**。
- **二期**：把父仓用例和成员本地 E2E **汇总成一个只读视图**。

---

## 2. 命令手册

### 2.1 命令总表

| 命令 | 做什么 | 什么时候用 | 写盘 | 退出码 |
|---|---|---|---|---|
| `atlas solution e2e init` | 幂等创建父仓 `<assets_root>/e2e/e2e-index.md` 骨架和 `cases/`、`scripts/`、`reviews/` 目录；索引已存在则跳过 | 父仓第一次接管 E2E；或索引被误删后重建 | 写父仓索引骨架/目录 | 0；参数/不是父仓等错误 2 |
| `atlas solution e2e init --migrate` | 在 `init` 基础上，扫描父仓 `product/e2e/cases/*.md`，给每个缺少 `成员依赖` 的 `atlas-case` 块追加一行 `成员依赖:`（冒号后留空），并打印涉及的文件/用例清单 | 二期升级前，存量父仓用例补必填字段 | 写父仓分片文件 | 0；错误 2 |
| `atlas solution e2e status` | 人读的只读聚合视图：每条需求的选择器状态、父仓用例、成员摘要 | 日常盘点；改配置后看是否还 BLOCKED | **不写盘** | 0（PASS/INCOMPLETE/N/A）；1（FAIL）；3（BLOCKED）；2（不是父仓/清单解析失败） |
| `atlas solution e2e status --json` | 同一视图的机读 JSON（`schema:1`、`kind: solution-e2e-readonly-view`、`readonly:true`） | 给 CI/另一个 agent 消费；精确定位字段 | **不写盘** | 同上 |
| `atlas solution e2e status --json --snapshot` | 同上，并另写一份父仓只读快照到 `<assets_root>/e2e/reviews/aggregate/` | 需要留一份“今天看到的聚合结果”作证据 | 只写父仓 `aggregate/` 一个 JSON | 同上 |
| `atlas solution e2e verify` | 只跑 `父仓 E2E *` 专项检查：索引、选择器、`case_ids` 引用、选择器接线、`需求` 列一致、孤儿审计；不把锁/契约的 WARN 混进来 | 改完 `atlas.solution.yaml` / 父仓索引 / 分片后，快速看配置门是否过 | **不写盘** | 0（PASS）；1（任一 `父仓 E2E` 检查 FAIL）；2（不是父仓/清单错误） |

补充：

- `status` 的退出码来自合成后的 `verdict`；`INCOMPLETE` 和 `N/A` 都是 **0**，但都**不是绿**。不要只看退出码。
- `verify` **不会**返回 3；它只有 PASS/FAIL。`BLOCKED` 是 `status` 的概念。
- 任何命令都要求 `--root` 指向 **solution 根**，不是 `.atlas/`，也不是某个成员仓。

### 2.2 在 `/Users/sunwenzhe/Desktop/跨网传输` 直接执行

该仓 `.atlas` 已更新到 `beace88410424417`，直接跑：

```bash
cd /Users/sunwenzhe/Desktop/跨网传输

# 1) 人读总览
python3 .atlas/scripts/atlas_solution.py --root . e2e status

# 2) 机读总览（分析用这个）
python3 .atlas/scripts/atlas_solution.py --root . e2e status --json

# 3) 只看某条需求
python3 .atlas/scripts/atlas_solution.py --root . e2e status --requirement REQ-XN-SYNC-PUSH --json

# 4) 留一份只读快照（唯一会写盘的 status 形态；只写父仓 aggregate/）
python3 .atlas/scripts/atlas_solution.py --root . e2e status --json --snapshot

# 5) 配置门
python3 .atlas/scripts/atlas_solution.py --root . e2e verify --json

# 6) 看真实退出码（不要被管道吞掉）
python3 .atlas/scripts/atlas_solution.py --root . e2e status --json >/tmp/xn-status.json
echo "status exit=$?"
python3 .atlas/scripts/atlas_solution.py --root . e2e verify --json >/tmp/xn-verify.json
echo "verify exit=$?"
```

如果 `.atlas` 落后（例如提示 `unrecognized arguments: --snapshot`），先从本地源包更新该仓的 `.atlas`：

```bash
bash /Users/sunwenzhe/Desktop/atlas/install.sh \
  --target /Users/sunwenzhe/Desktop/跨网传输 --update
```

这是刷新包产物，不会改成员仓的 `product/` 资产；但 `--update` 本身是写动作，分析任务里不要随手跑，除非确认 `.atlas` 版本不对。

### 2.3 初始化/迁移的典型顺序

```bash
# 新父仓第一次接管 E2E
python3 .atlas/scripts/atlas_solution.py --root . e2e init

# 二期升级：给存量父仓用例补 成员依赖:
python3 .atlas/scripts/atlas_solution.py --root . e2e init --migrate

# 迁移只补空列表，不猜依赖；真实依赖要人工在分片里补
# 然后跑配置门
python3 .atlas/scripts/atlas_solution.py --root . e2e verify
```

不跑 `--migrate` 就直接升级，存量父仓用例会因为缺 `成员依赖` 被判 FAIL；这是**预期行为**，不是 bug。

### 2.4 一次分析的标准动作

1. 在 solution 根读 `atlas.solution.yaml`：先列出 `members[]`、`requirements[]`，确认哪些需求是单成员、哪些是多成员。
2. 跑 `e2e status --json`：记下 `verdict`、退出码、每条需求的 `state/reason`、`parent.cases`、每个成员的 `state/counts/review`。
3. 对每条需求核对选择器：`case_ids` 指向的 ID 是否真的在父仓索引里；`cross_repo_e2e: none` 是否只用在单成员需求上。
4. 对候选用例按第 4 节的 4 问分类：全“是”才是父仓跨仓用例；任何一问“否”就留在成员仓。
5. 如果要补配置：先写父仓分片，再写父仓索引行，最后写 `case_ids`；跑 `e2e verify`，再跑 `e2e status --json`。全程不改成员仓。

---

## 3. 字段契约

### 3.1 `atlas.solution.yaml` 的 `requirements[]`

每条需求行至少要有 `id`、`acs`、`member`、`task_slug`、`scope`。跨仓选择器只有两个字段：

| 字段 | 形态 | 规则 |
|---|---|---|
| `case_ids` | **标量字符串**，逗号/顿号分隔，例如 `E2E-SOLUTION-FLOW-001,E2E-SOLUTION-FLOW-004` | 不写 YAML 列表；ID 必须符合 `E2E-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d{3}`；同一 `requirement.id` 最多一行携带 |
| `cross_repo_e2e` | 唯一合法值 `none` | 只允许单成员需求；同一 `requirement.id` 最多一行携带；不得与 `case_ids` 同时出现 |

**选择器满足性**：

- **多成员需求**（同一个 `requirement.id` 出现 ≥2 个 `member` 行）**必须**有 `case_ids`；写 `cross_repo_e2e: none` 或两者都无 ⇒ `verify` FAIL、`status` 为该需求 `blocked`。
- **单成员需求**：`case_ids` 或 `cross_repo_e2e: none` **二选一**；两者都无 ⇒ FAIL/blocked；两者都有 ⇒ 清单加载直接报错（互斥）。
- 同一 `id + member` 不能重复。

**最小样例（单成员，确实没有跨仓 E2E）**：

```yaml
requirements:
  - id: REQ-XN-SYNC-BACKEND
    acs: AC-SOLUTION-001,AC-SOLUTION-003
    member: app-management-svc
    task_slug: cross-sync-backend
    scope: 实现统一触发与记录查询接口
    cross_repo_e2e: none
```

**最小样例（单成员，但有跨仓用例）**：

```yaml
requirements:
  - id: REQ-XN-SYNC-PUSH
    acs: AC-SOLUTION-001,AC-SOLUTION-008
    member: devops-track-web
    task_slug: cross-sync-push
    scope: pushCrossSync 改调统一入口
    case_ids: E2E-SOLUTION-FLOW-001,E2E-SOLUTION-FLOW-002
```

**多成员样例（`case_ids` 只写在其中一行）**：

```yaml
requirements:
  - id: REQ-XN-SYNC-FLOW
    acs: AC-SOLUTION-001
    member: hc-unify-application
    task_slug: cross-sync-record-page
    scope: 记录页接真实接口
    case_ids: E2E-SOLUTION-FLOW-001
  - id: REQ-XN-SYNC-FLOW
    acs: AC-SOLUTION-001
    member: app-management-svc
    task_slug: cross-sync-backend
    scope: 统一触发与记录查询接口
```

注意：`requirements` 的解析器只支持受限 YAML 子集，`case_ids:` 后面**不要**换行写 `- E2E-...` 列表；否则列表项会被忽略，选择器看起来“配了但没生效”。

### 3.2 父仓用例块的 `成员依赖:`

位置：父仓 `product/e2e/cases/*.md` 的每个 `## <ID> <标题>` 小节下、紧随的 ` ```atlas-case ` 块内。

```text
成员依赖:
  - hc-unify-application
  - app-management-svc
```

规则：

- **必填**。父仓模式下缺这个键 ⇒ `validate_e2e_index` 的“成员依赖必填”检查 FAIL。
- 允许空列表，规范写法是**冒号后留空**：

```text
成员依赖:
```

- 手写字面量 `成员依赖: []` 解析侧也会归一为空列表，但**不要这样写**；`--migrate` 生成的也是冒号留空形态。
- 每个值必须是 `atlas.solution.yaml` 里 `members[].name` 的成员名，不能写路径，也不能写 `kind`。清单外成员 ⇒ FAIL。
- 共享用例（同一个 case 被多个需求用 `case_ids` 引用）的 `成员依赖` 必须是这些需求成员的**并集**；不一致 ⇒ FAIL。
- `成员依赖` **不承担 stale 粒度**。父仓用例的 `fresh/stale` 由父仓 fingerprint 决定，fingerprint 纳入**全部成员**的 `app_hash`；任一成员应用变化 ⇒ 所有父仓用例 `stale`，不依赖该成员的也不豁免。

### 3.3 父仓 `product/e2e/e2e-index.md`

主表列头必须**逐字**如下（顺序固定）：

| 用例ID | 页面 | 中文标题 | 类型 | 关联AC | 需求 | 状态 | 状态原因 | 分片 |
|---|---|---|---|---|---|---|---|---|

字段规则：

- `用例ID`：符合 `E2E-<大写段>-NNN`，且与分片 `## <ID>` 一致。
- `页面`：父仓跨仓用例统一写 `solution-flow`。
- `类型`：`smoke` / `acceptance` / `exception` / `permission`。
- `关联AC`：**一格一个 AC ID**（如 `AC-SOLUTION-001`），不要写逗号串；只做追溯，不参与选择器。
- `需求`：可写多个，用 `、` / `,` / `，` / 空格分隔；必须与 `case_ids` 的消费方一致。
- `状态`：`red` / `prototype-pass` / `green` / `blocked` / `skipped`。`prototype-pass` 是 E0 历史态，不再产生，也不算绿。
- `状态原因`：`blocked` / `skipped` **必须**有原因，其余状态必须留空；有原因时必须是 `前缀：说明`（中文全角冒号），前缀只能是 `ENV_ISSUE` / `NOT_IMPLEMENTED` / `SPEC_AMBIGUOUS` / `BLOCKED_DEP` / `DEFERRED` / `OUT_OF_SCOPE` / `OTHER`。
- `分片`：相对链接 `cases/<file>.md#<id 小写>`，必须可达，且分片标题与 `中文标题` 一致。
- 页面表：`solution-flow | / | solution | 未实现/已实现 | 否/是`。
- **反向视图空单元格规则**：`页面 ↔ 用例` 表中没有内容的列要**留空**（两个 `|` 之间什么也不写）。写 `—`、`无`、`N/A` 都会导致“反向视图一致”检查 FAIL。

**可照抄的最小索引样例**（注意 `链路经过用例` 是空单元格，不写 `—`）：

```markdown
# E2E 总索引（父仓跨仓 E2E）

| 用例ID | 页面 | 中文标题 | 类型 | 关联AC | 需求 | 状态 | 状态原因 | 分片 |
|---|---|---|---|---|---|---|---|---|
| E2E-SOLUTION-FLOW-001 | solution-flow | 租户发起跨网同步后记录页可见新批次 | acceptance | AC-SOLUTION-001 | REQ-XN-SYNC-PUSH | green | | [cases/solution-flow.md#e2e-solution-flow-001](cases/solution-flow.md#e2e-solution-flow-001) |

## 页面表（页 ↔ 路由 ↔ 实现状态 / 覆盖就绪）

| 页面 | 路由 | 域 | 实现状态 | 覆盖就绪（可选） |
|---|---|---|---|---|
| solution-flow | / | solution | 未实现 | 否 |

## 页面 ↔ 用例

| 页面 | 断言落点用例 | 链路经过用例 |
|---|---|---|
| solution-flow | E2E-SOLUTION-FLOW-001 | |
```

**对应的分片样例**（`product/e2e/cases/solution-flow.md`）：

````markdown
## E2E-SOLUTION-FLOW-001 租户发起跨网同步后记录页可见新批次

```atlas-case
id: E2E-SOLUTION-FLOW-001
pages:
  - solution-flow
precondition:
  - 统一入口网关可用（父仓 e2e.app_base_url）
step:
  - goto /#/amp/orgList
  - click tenant-sync-entry
  - click cross-sync-confirm
expected:
  - visible cross-sync-batch-row
testid:
  - tenant-sync-entry
  - cross-sync-confirm
  - cross-sync-batch-row
成员依赖:
  - hc-unify-application
  - app-management-svc
```
````

注意：

- 分片必须放在父仓 `<assets_root>/e2e/cases/` 下，且必须是 `## <ID>` + 紧随 `atlas-case` 块的形态；只放在别处的文档不会被 `gather_shards` 看到。
- `members` 里没有本地 E2E 不阻断父仓用例；只有成员 **路径缺失/不是 git**（`missing`）且被 `成员依赖` 引用时才阻断。

### 3.4 `reviews/aggregate/` 的落点与保留名

- 路径：`<assets_root>/e2e/reviews/aggregate/<YYYY-MM-DD>-<REQ|ALL>.json`。
- `aggregate` 是 `reviews/` 下的**保留名**，与 `console/`、`<日期>-first-run`、`<日期>-acceptance-<域>`、`<日期>-verify` 同列；它不参与“找最新审查报告”的报告定位（保留名且无 `review.json` ⇒ 跳过）。
- 文件头声明 `kind: "solution-e2e-readonly-view"`、`readonly: true`、`note`（说明成员评审以成员 `events.jsonl` 为准，本文件不是成员状态的第二份账本）。
- 它是一次快照，不是历史账本；同一天同一需求重跑会覆盖同名文件。
- 不要把它当成员评审真相源，也不要手工改它来“修正”视图。

---

## 4. 什么算跨仓用例

### 4.1 可操作判据（逐条打勾，不靠定义）

对一条候选用例，按下面 4 问检查：

1. **判定是否需要同时观察多个仓？**  
   通过条件是否依赖另一个仓的运行结果（目标侧回查、跨库/跨服务数据、联合状态），而不是只断言本仓 UI？
2. **是否无法在单个成员仓的本地 E2E 里独立执行？**  
   只起本仓应用时，是不是缺另一半环境/缺父仓统一网关，导致根本跑不起来或跑了也证明不了？
3. **失败是否能定位到“跨仓契约/编排”？**  
   它验证的是成员之间的接口契约、数据落点或流程编排，而不是某个仓内部的页面细节？
4. **是否由某个 solution 需求直接决定完成度？**  
   它是否应该出现在父仓 `requirements[].case_ids` 里，作为该需求的验收证据？

**4 问全“是” ⇒ 父仓跨仓用例。任何一问“否” ⇒ 留在成员仓本地。**

补充：以下都**不构成**判据：

- 用例名字里有 `CROSS` / `SYNC` / `跨网`；
- 关联了 `AC-SOLUTION-*`；
- 数据来自后端；
- 文件放在父仓目录下（放错位置也不会被选择器看到）。

### 4.2 三个正例

1. **租户页发起 → 项目页确认 → 后端写记录 → 记录页可见新批次**  
   通过条件同时依赖 `hc-unify-application`、`devops-track-web`、`app-management-svc` 三个仓的运行结果；任一本仓单独起服务都无法证明。⇒ 父仓用例。

2. **记录页按批次号搜索，断言后端真实批次与 7 列字段**  
   只起 `hc-unify-application` 时只能看到前端 mock/空数据；必须配合 `app-management-svc` 的真实接口与库。⇒ 父仓用例。

3. **推送入口调用统一网关后，后端目标租户/项目事项被创建**  
   入口在 `devops-track-web`，落点在 `app-management-svc`；验收证据在目标侧回查。⇒ 父仓用例。

### 4.3 三个反例（看着像，其实不是）

1. **“记录页表头 7 列展示 / 空态 / 筛选交互”**  
   看着像记录页跨仓流，其实只断言 `hc-unify-application` 自己的渲染与交互；接口返回受控数据即可。⇒ 成员本地用例，不要因为“数据来自后端”就搬父仓。

2. **“后端创建批次接口的幂等/并发抢占”**  
   看着像同步主链路，其实只依赖 `app-management-svc` 一个服务和它的库；用后端集成测试或单仓 E2E 就能判定。⇒ 成员本地用例；父仓 E2E 不替代后端单仓 API 测试。

3. **“项目列表工具栏显示跨网同步入口 / 看板视图隐藏入口”**  
   名字里有“跨网同步”，但只断言 `devops-track-web` 自己的路由与按钮显隐，不观察其他仓。⇒ 成员本地用例（该仓现有 `E2E-PROJECT-LIST-001/002` 就是这类）。

再补一个**文档级反例**：一份“跨网同步 V1 验收用例汇总清单”（169 条）看起来像父仓用例全集，但它把用例归属到三个成员任务卡，且没有 `## <ID>` + `atlas-case` 分片格式、也不在 `cases/` 下。它不是父仓用例，选择器也选不到；不能因为它在父仓仓库里就当已配置。

### 4.4 为什么归父仓，而不是成员仓

- **责任边界**：跨仓流的生命周期跨多个成员，任何单成员仓都不能对它负责；成员仓只对“本仓应用在这条流里的行为”负责。
- **唯一入口**：跨仓用例走父仓统一网关，父仓的索引/选择器/账本是它唯一的真相源；成员仓改本地用例不会影响父仓选择器。
- **可定位**：父仓用例失败时，能沿着 `atlas.solution.yaml` 的 `contracts[]` 定位到跨仓契约，而不是在某个成员仓里猜。
- **防退化**：如果每个成员各写一半，就会出现 N 个控制台、两套账本、互相甩锅；一期/二期的结构就是为了避免这个。

---

## 5. 状态与判定

### 5.1 执行态（5 个词，闭集）

| 状态 | 含义 | 能否合成 PASS |
|---|---|---|
| `red` | 执行失败 | 否，直接 FAIL |
| `prototype-pass` | E0 历史终态，存量可能还在，**不再产生** | 否，按非绿处理 |
| `green` | 执行通过 | 是（还要看评审态） |
| `blocked` | 环境/依赖未就绪，未执行；必须带 `状态原因` | 否，BLOCKED |
| `skipped` | 主动跳过；必须带 `状态原因` | 否，BLOCKED |

### 5.2 评审态（4 个词，闭集）

| 状态 | 含义 | 何时出现 |
|---|---|---|
| `unreviewed` | 尚未标记评审通过 | 账本里没有该用例的 `reviewed.pass` |
| `fresh` | 评审指纹与当前内容一致，评审有效 | 有 `reviewed.pass`，且 `prov.fp` 与当前指纹一致 |
| `stale` | 评审后用例脚本块 / 同文件块外代码 / 共享脚本 / 应用代码发生变化 | 指纹不一致；**父仓模式下，有 `reviewed.pass` 但没有 run-time `prov` 也归 `stale`（fail-closed）** |
| `legacy` | 历史账本条目没有可用指纹，来源无法验证 | **仅单仓模式**；父仓模式同一条件走 `stale` |

两个容易混淆的点：

- **成员**的 `review_state` 用**成员根**重算，单仓分支没有 `solution_root`；所以成员账本里没有 prov 的旧条目会显示 `legacy`。
- **父仓用例**的 `review_state` 用父仓根 + `solution_root=True`；没有 run-time prov 的 `reviewed.pass` 会显示 `stale`，不是 `legacy`。

### 5.3 `verdict` 合成规则

严重度优先级：**`FAIL` > `BLOCKED` > `INCOMPLETE` > `PASS`**；`N/A` 单列，不显示为绿。

实现里的判定顺序（从高到低）：

1. 任一需求选择器状态 `fail`，或任一选中父仓用例 `red` ⇒ **`FAIL`**，exit 1。
2. 任一需求选择器 `blocked`（没配选择器 / 父仓索引不可解析 / 命中 0 条）⇒ **`BLOCKED`**，exit 3。
3. 所有需求都是 `na`（单成员显式 `cross_repo_e2e: none`）⇒ **`N/A`**，exit 0。
4. 没有任何需求行 ⇒ **`BLOCKED`**，exit 3。
5. 没有传 root（纯选择器单元调用）⇒ 只判选择器；AC 覆盖拿不到 root，通常是 `PASS`。
6. 有 root 时：任一父仓用例被 `missing` 成员阻断，或任一父仓用例状态 **不是 `green`** ⇒ **`BLOCKED`**，exit 3。
7. 任一父仓用例评审态 **不是 `fresh`** ⇒ **`INCOMPLETE`**，exit 0。
8. `parent.ac_coverage.state = ready` 且存在零挂靠 AC ⇒ **`INCOMPLETE`**，exit 0。
9. 否则 **`PASS`**，exit 0。

注意第 6 条是“非 `green` 即 BLOCKED”，所以 `blocked`、`skipped`、`prototype-pass`、空状态都会进 BLOCKED；走到第 7 条时所有用例执行态已经全是 `green`，评审检查只决定是 `INCOMPLETE` 还是继续往下。

### 5.4 哪些组合**不能**合成 PASS

| 组合 | 结果 | 说明 |
|---|---|---|
| 任一选中用例 `red` | `FAIL` | 最高优先级 |
| 任一需求选择器没配 / 索引不可解析 / 命中 0 条 | `BLOCKED` | 输入问题，不是执行问题 |
| 任一父仓用例 `blocked` / `skipped` / `prototype-pass` / 空状态 | `BLOCKED` | 非绿即阻断 |
| 被 `成员依赖` 引用的成员 `missing` | `BLOCKED` | 路径缺失/不是 git |
| 任一父仓用例 `unreviewed` / `stale`（父仓不产生 `legacy`） | `INCOMPLETE` | 执行绿但评审证据不成立 |
| `ac_coverage.state=ready` 且 `zero_attached` 非空 | `INCOMPLETE` | 父仓域已就绪，但仍有 AC 没挂用例 |
| 单成员显式 `cross_repo_e2e: none` | `N/A` | 不是 PASS，也不进入执行面 |
| 所有选中用例 `green` + 所有评审 `fresh` + AC 无零挂靠 | `PASS` | 唯一的绿 |

再强调一次：**`INCOMPLETE` 和 `N/A` 的退出码是 0，但不是“通过”**。分析时不要用 `exit 0` 代替 `verdict == "PASS"`。

---

## 6. 只读边界

### 6.1 聚合视图读什么

`atlas solution e2e status` 只读：

- 父仓：`atlas.solution.yaml`、`product/e2e/e2e-index.md`、`product/e2e/cases/*.md`、`product/e2e/reviews/console/events.jsonl`、父仓 git 指纹；
- 每个成员：成员自己的索引/分片/账本、成员根 git 指纹。

它**不**：

- 调用执行器，不跑 Playwright；
- 调用成员控制台的提交路径，不 `append` 成员账本；
- 回写成员 `e2e-index.md` 的 `状态` 列；
- 改写成员 `events.jsonl` 或 `ledger.md`；
- 用父仓根计算成员 `current`。

### 6.2 唯一的写动作

`status` 只有显式 `--snapshot` 才会写，且只写：

```text
<assets_root>/e2e/reviews/aggregate/<YYYY-MM-DD>-<REQ|ALL>.json
```

`write_snapshot` 是 `_support/solution_e2e.py` 里唯一的写文件函数；调用条件是 `snapshot and root is not None`。除此之外，`status` / `status --json` / `verify` 都不写盘。

`init` / `init --migrate` 是**另外的写命令**，只写父仓骨架/分片，不属于视图；不要和分析用的 `status` 混为一谈。

### 6.3 机制证据（不是声明）

- 代码路径：`read_member_summary()` 用 `Ledger(path, "只读视图")` + `ledger.read()` + `ledger.committed_snapshot(...)`；`Ledger` 的写方法（`append`）在视图路径里没有被调用。
- 代码路径：成员 `review_state` 的 `current` 来自 `repo_provenance(member_path)` + `review_fingerprint(member_path)`，不是父仓根。
- 测试：
  - `tests/test_solution_e2e_view.py::test_view_is_read_only_member_files_untouched`：调用前后对成员文件做哈希，断言零变化；
  - `tests/test_solution_e2e_view.py::test_snapshot_writes_only_parent_aggregate`：断言只新增父仓 `aggregate/` 文件；
  - `tests/test_solution_e2e_view.py::test_member_review_state_recomputed_at_member_root_h5`：只改成员 B 后，成员 A 本地仍 `fresh`，所有父仓用例转 `stale`。

### 6.4 agent 分析纪律

分析采纳仓时：

- **不得**为了让视图变绿，去改成员仓的 `e2e-index.md` 状态；
- **不得**手工追加/改写成员 `events.jsonl`，也不要把旧评审“重签”成新指纹；
- **不得**为了让父仓用例不 BLOCKED，随手删/改 `成员依赖`；
- **不得**为了让需求从 blocked 变 N/A，给真实跨仓需求硬加 `cross_repo_e2e: none`；
- **不得**手工改 `reviews/aggregate/*.json`；
- 发现问题只**报告**：它属于成员仓自己的执行/评审流程，或属于父仓配置问题；修复动作要落在正确的仓、正确的流程里。

---

## 7. 实例：`跨网传输` 现状（只读实测，2026-11-09）

> 本节只描述现状；**没有修改该仓任何文件**。数字会变，下次分析先重跑 `status --json`。

### 7.1 当前视图

在 `/Users/sunwenzhe/Desktop/跨网传输` 执行：

```bash
python3 .atlas/scripts/atlas_solution.py --root . e2e status --json
```

实测结果：

- `verdict = BLOCKED`，`exit = 3`；
- 三条需求全部 `state = blocked`，原因都是：`单成员需求必须二选一：case_ids 或 cross_repo_e2e: none`；
- `parent.index.state = ok`，但 `parent.cases = []`，`parent.case_ids = []`；
- `parent.ac_coverage = { state: not_ready, ac_total: 13, attached: 0, zero_attached: [AC-SOLUTION-001..013] }`；
- 成员：
  - `app-management-svc`：`no_local_e2e`；
  - `devops-track-web`：6 条（green 2 / blocked 4），评审 `unreviewed 6`；
  - `hc-unify-application`：6 条（green 6），评审 `stale 5 / unreviewed 1`。

同一仓执行 `e2e verify --json`：`verdict = FAIL`，exit 1；`父仓 E2E 索引` PASS（0 条用例），三条 `父仓 E2E 选择器` FAIL，其余 `case_ids 引用` / `选择器接线` / `需求列一致` / `孤儿用例` PASS。

为什么 `status` 是 3、`verify` 是 1：`status` 把选择器问题合成 `BLOCKED`；`verify` 只判配置门的 PASS/FAIL。两者说的其实是同一件事：**三条需求都没配选择器**。

### 7.2 三条需求为什么 blocked，以及两种正确处置

三条需求在 `atlas.solution.yaml` 里都是**单成员**，且都既没有 `case_ids`，也没有 `cross_repo_e2e: none`：

| 需求 | 成员 | 现状 |
|---|---|---|
| `REQ-XN-SYNC-BACKEND` | `app-management-svc` | 无 `case_ids`、无 `cross_repo_e2e` |
| `REQ-XN-SYNC-RECORD-PAGE` | `hc-unify-application` | 无 `case_ids`、无 `cross_repo_e2e` |
| `REQ-XN-SYNC-PUSH` | `devops-track-web` | 无 `case_ids`、无 `cross_repo_e2e` |

这是**选择器输入问题**，不是执行失败。两条正确处置，二选一：

1. **确实没有跨仓 E2E**（该需求只在单仓内部验收）  
   在该需求行补：

   ```yaml
   cross_repo_e2e: none
   ```

   结果：该需求 `state=na`，整体 `verdict=N/A`（exit 0），**不是 PASS**。`verify` 的选择器检查会 PASS。

2. **确实有跨仓 E2E**  
   先把父仓用例真正落成：
   - 在 `product/e2e/cases/*.md` 写 `## <ID> <标题>` + `atlas-case` 块（含 `id` / `pages: [solution-flow]` / `precondition` / `step` / `expected` / `testid` / `成员依赖`）；
   - 在 `product/e2e/e2e-index.md` 主表加行（`页面=solution-flow`，`分片` 指向该分片，`状态` 初始可用 `blocked` + `ENV_ISSUE：...`）；
   - 在该需求行补 `case_ids: <这些 ID>`。

   然后：

   ```bash
   python3 .atlas/scripts/atlas_solution.py --root . e2e verify
   python3 .atlas/scripts/atlas_solution.py --root . e2e status --json
   ```

   `verify` 的选择器/引用/接线应转 PASS；`status` 仍可能是 `BLOCKED`（用例没执行）或 `INCOMPLETE`（执行绿但评审不 fresh）——这是正常的，不要为了变绿去改状态。

**错误处置**（看到要制止）：

- 把 `cross_repo_e2e: none` 加到真实跨仓需求上，只为了消掉 blocked；
- 把成员本地用例 ID 直接写进父仓 `case_ids`（父仓索引里没有 ⇒ FAIL）；
- 把 `product/e2e/cross-network-sync-v1-cases.md` 当分片，直接写进 `case_ids`；
- 手工把成员索引改成 green，或伪造账本。

### 7.3 13 条 solution AC 全部 `not_ready` 意味着什么

`ac_total = 13`、`attached = 0`、`state = not_ready`、`zero_attached` 列出 `AC-SOLUTION-001..013`。

含义：

- 13 条 AC **定义行**在 `product/prd/solution-prd.md` 里是齐的；
- 但父仓索引目前 **0 条用例**，所以没有任何 AC 被 `关联AC` 挂靠（`attached=0`）；
- 父仓页面表里 `solution-flow` 还是骨架：`未实现` + `覆盖就绪: 否`，所以反向覆盖状态是 `not_ready`，**不参与 verdict**。

这不等于“13 条 AC 全部没实现”，也不等于“AC 反向覆盖通过了”。它只说明：**父仓 AC 覆盖门还没进入可判定状态**。

一个容易踩的坑：如果只把 `solution-flow` 改成 `已实现` / `覆盖就绪: 是`，却不加任何父仓用例，`ac_coverage` 会变成 `ready` 且 `zero_attached` 非空 ⇒ `verdict` 直接变 `INCOMPLETE`。正确顺序是先有用例挂 AC，再声明域就绪。

### 7.4 `devops-track-web` 4 条 blocked 怎么读

成员索引 6 条：`green 2`、`blocked 4`。4 条 blocked 的 `状态原因` 都是：

- `ENV_ISSUE：宿主 localhost:8000 未启动，E2E 未执行`；
- 其中 `E2E-PROJECT-LIST-005` 另需字典 `cross-net/targetIp` **已配置**；
- `E2E-PROJECT-LIST-006` 另需字典 `cross-net/targetIp` **未配置**。

解读：

- 这是**执行环境未就绪**，不是代码失败，也不是“已经通过”；
- 4 条都还没执行，视图的 `blocked` 计数如实反映；
- 6 条全部 `unreviewed`，因为该成员没有 `reviews/console/events.jsonl`（没有提交过评审账本）；
- 父仓视图不会把它们改成 green，也不会因为成员 blocked 就直接让父仓 verdict 变红（除非某条父仓用例的 `成员依赖` 引用了 `missing` 成员，而该成员是 `ok`，不是 `missing`）。

要变成有评审证据的状态：启动 `localhost:8000` 宿主应用 → 在成员仓跑控制台 → 执行并人工评审 → 提交账本。不要在索引里手改。

### 7.5 `hc-unify-application` 5 条 stale 怎么读

成员索引 6 条全 `green`；账本只有 1 条 2026-11-02 的 submit，覆盖 5 条 `reviewed.pass`，另 1 条用例没有评审记录。

实测差异（只读计算）：

- 旧 provenance：`head = b9eb13f5...`、`app = f3f8f8d7b2559496`；
- 当前：`head = 2977f54...`、`app = 5589d939839213c3`；
- 5 条已评审用例的 `fp.block`（用例自己的脚本块）和 `fp.rest`（同文件块外代码）都与当前不一致；`shared_hash` 未变（`c87be840d6b10ed0`）。

解读：

- `green` 是**执行态**，`stale` 是**评审态**：执行当时是绿的，但评审证据绑定的内容已经变了，不能算 `fresh`；
- 变化至少包括应用代码（`app_hash` 变了），且脚本块/同文件代码也变了；
- `E2E-CROSS-NETWORK-SYNC-005` 是 `green` 但没有账本记录 ⇒ `unreviewed`；
- 账本里还有一条 `E2E-APP-WORKFLOW-DETAIL-025`，但当前索引里没有它 ⇒ 孤儿账本条目；视图只统计当前索引里的用例，所以它不显示，也不代表父仓用例；
- 要让 5 条重新 `fresh`：在成员仓重跑这些用例并重新人工评审、提交新账本（带新的 run-time `prov`）。**只重签旧记录不算 fresh**。

### 7.6 父仓 `parent.cases = []` 与 169 条汇总清单

父仓 `product/e2e/e2e-index.md` 主表 0 行，`product/e2e/cases/` 只有 `.gitkeep`。因此：

- `parent.cases = []`，没有可执行的父仓跨仓用例；
- `case_ids` 即使现在写，也选不到任何用例（会 FAIL 或 blocked）；
- 父仓仓库里那份 `product/e2e/cross-network-sync-v1-cases.md` 是**汇总文档**（169 条，归属三个成员任务卡），不是分片：
  - 不在 `cases/` 下；
  - 没有 `## <ID>` + `atlas-case` 块（实测 0 个 `atlas-case` 围栏）；
  - 因此 `gather_shards` 看不到，选择器也选不到。

分析结论要写清楚：**这 169 条目前不是父仓用例，只是成员侧候选用例的汇总**。其中哪些真正属于跨仓用例，要按第 4 节的 4 问重新判，不能按文档标题或归属表直接搬。

---

## 8. 已知缺口（二期放行范围之外）

以下是“这版没做/没保证”的清单。看到绿的视图时，不要把下面这些当成已经覆盖。

| # | 缺口 | 影响 |
|---|---|---|
| 1 | 只有 CLI/JSON 聚合视图，没有父仓控制台的“跨仓 E2E 概览”只读面板 | agent 只能读命令输出，不能指望网页面板 |
| 2 | 没有分别输出 `run_verdict` / `review_verdict`，只有一个合成 `verdict` | 从 JSON 不能直接区分“执行红”还是“评审不 fresh”，要看 `parent.cases[].status/review_state` 或成员 `counts/review` |
| 3 | `skipped` / `prototype-pass` 走的是“非 green ⇒ BLOCKED”的兜底分支，不是独立命名分支 | 结果正确（都不会 PASS），但 JSON 里看不出 BLOCKED 的具体来源；需结合 `parent.cases[].status` 判断 |
| 4 | 评审侧的“父仓账本与用例集合对不上（缺条/序号重复/指纹缺失）⇒ FAIL”没有实现为 FAIL | 账本缺条只会显示 `unreviewed`；账本损坏不会自动变红，不能假设视图会兜底 |
| 5 | 父仓 testid **没有机器校验**：solution 根 `validate_testids` 返回 N/A | 父仓用例的 `testid:` 只靠人工/纪律；跨成员同名 testid 不会被机器发现 |
| 6 | 成员 `index_invalid` 不会让父仓 verdict 变 BLOCKED；只有 `missing` + `成员依赖` 才阻断 | 成员索引坏了只在 `members[].state` 里告警；不要以为视图会替成员判红 |
| 7 | `parent.ac_coverage` 只统计“AC 定义行 + 父仓用例 `关联AC` 挂靠” | 不做跨仓 AC crosswalk，也不校验父仓用例挂的 AC 是否语义正确；`not_ready` 时不参与 verdict |
| 8 | `--snapshot` 文件名是 `日期-REQ.json` 或 `日期-ALL.json` | 同一天同一需求重跑会覆盖；它是一次快照，不是历史账本，也不会被自动回读校验 |
| 9 | `latest_seq` 实际是 submit 事件条数，不是最后一条事件的 `seq` | 非连续/跨日时不要把它当账本序号用 |
| 10 | 跨仓 E2E 只支持父仓同源网关（`e2e.app_base_url`） | 不支持多 host 直连 / 每个成员自己的 `app_base_url`；成员页面级 `pages[]` 也不在父仓索引里表达 |
| 11 | `atlas e2e migrate` 别名未实现 | 只能用 `atlas solution e2e init --migrate` |
| 12 | `gather_shards` 只扫 `<assets_root>/e2e/cases/*.md` | 放在别处、或不是 `## <ID>` + `atlas-case` 形态的文档，不会被索引/选择器看到 |

最后一句：**“视图是绿的”只代表父仓用例执行 `green`、评审 `fresh`、AC 无零挂靠；它不代表成员本地 E2E 充分，也不代表跨仓流覆盖了所有成员页面。** 后两者仍是需求评审与成员评审的职责。
