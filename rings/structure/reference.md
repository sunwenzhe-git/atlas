# atlas structure — 结构基线（逆向）

> 本环为 atlas 独立 skill `atlas-structure` 的执行契约，位于 `.atlas/rings/structure/reference.md`。
> 执行前先读共享契约：`.atlas/shared/global-rules.md`、`stack-profile.md`、`single-source.md`、`layout.md`、`knowledge.md`。

## 0. 一句话

读代码（+ 可选旧实现），产出**结构事实**，直接落在 **`.trellis/spec/structure/`**（Trellis 的路径注入层）——同一份既是项目级事实，又能被 Trellis 任务**原生注入**消费，无需再做一层桥。

- **事实区**由适配器 + 刷新脚本**确定性**维护；**语义区**由 AI / `trellis-update-spec` 维护（见 §8）。
- **与 PRD 环独立有序**：本环先跑、**提议候选域**；PRD 读本环产物并**定稿域**。两者不自动互相触发。

---

## 1. 输入

| 输入 | 必需 | 说明 |
|---|---|---|
| 代码 | 是 | 目标项目的实际代码树 |
| `product/stack-profile.yaml` | 是 | 声明 apps、role（landing/legacy）、适配器。缺失时先与用户确认后生成 |
| 项目根 `README.md` | 是 | A（技术栈 + 启动）与 H（测试 / 运行）的真相源 |
| 既有 `.trellis/spec/structure/_meta.json` | 否 | 刷新时读，保留已定稿的域 |

---

## 2. 域模型（本环负责**提议**）

**域 id 是全链路键**：`structure` 域目录 / PRD 域文件 / 索引页面表的域列 / E2E 分片 / 注入 spec 都用同一个域 slug。

### 2.1 候选域提议（从代码聚类）

对每个 app 收集**信号**，多信号投票聚类（不得依赖单一信号）：路由 / 页面目录簇 · 模块 / 目录簇 · 数据表 / 模型命名簇 · 接口路径前缀簇。

跨域或信号冲突的域标「信号冲突」。

### 2.2 域清单（= 域 SSOT，双视图）

- **机器视图**：`.trellis/spec/structure/_meta.json` 的 `domains[]`（字段见 §3.1）。
- **人读视图**：`.trellis/spec/structure/tour.md` 的**域速查表**（域 id / 中文名 / 涉及 app / globs / 状态）。

| 字段 | 含义 |
|---|---|
| `id` | ASCII kebab-case slug（全链路键） |
| `name` | 中文名 |
| `apps` | 涉及 app |
| `status` | `候选`（structure 产）/ `已定稿`（PRD 回写）/ `信号冲突`（跨域或信号打架，待裁定） |
| `globs` | 该域的**代码 globs**（L2 的 `paths:` 来源，非空） |

> PRD 在诊断阶段读 `_meta.json.domains`，可合并 / 拆分 / 改名 → **定稿后回写 `status`**。PRD 若改了域结构，本环按最终域 **re-key**（重排目录，不重读代码）。

---

## 3. 输出布局（落 `.trellis/spec/structure/`）

```
.trellis/spec/structure/
├── _meta.json              # 机器：product / baseline / apps[] / domains[] / categories
├── tour.md                 # L1：paths 块列表 ['**']，全局 router（≤ ~1.5k 字符）
├── domains/<domain>.md     # L2：paths 块列表 = 该域 globs，薄指针
├── global/                 # 全局事实（pull-only：无 paths，不注入，由 tour 链接）
│   ├── directory-map.md    # B
│   ├── routes.md           # C
│   ├── apis-shared.md      # D（无域归属 / 指针形态；可选，按需出现）
│   └── data-models-shared.md  # E（跨域共享表；可选，按需出现）
└── {current,legacy}/<domain>/   # 域级事实（pull-only：无 paths，由 domains/<d>.md 链接）
    ├── apis.md             # D（无 Swagger 时）
    └── data-models.md      # E
```

- **只有 `tour.md` 与 `domains/<domain>.md` 带 `paths:`**（被注入）；其余事实文档**无 `paths`**，靠指针按需 Read，避免撞注入预算。

> **模板**（骨架，含列头与 `atlas:facts` 标记）：`.atlas/templates/structure/`（`_meta.json` / `domain-tour.md` / `domain.md` / `global-{directory-map,routes}.md` / `role-{apis,data-models}.md`）。

**类别 → 落点**

| # | 类别 | 落点 | 层 |
|---|---|---|---|
| A（可选） | 技术栈 + 启动方式 | 项目根 `README.md` | 不入 spec |
| B | 目录与模块地图（含域→模块映射） | `global/directory-map.md` | 全局 |
| C | 路由与页面清单（全站总表，带「域」列） | `global/routes.md` | 全局 |
| D（条件） | 接口清单 | `{current,legacy}/<domain>/apis.md` | 域级 |
| E | 数据模型清单 | `{current,legacy}/<domain>/data-models.md` | 域级 |
| H（条件） | 测试现状与运行方式 | 项目根 `README.md` | 不入 spec |

**A 的落点（可选类）**：技术栈 + 快速启动**不入 spec**；真相源是**项目根 `README.md`** 的「技术栈 / 启动」两节。是否纳入由用户决定（§6 步 2）；纳入时只核对 / 补齐该两节。

**H 的落点（条件类）**：测试现状与运行方式**不入 spec**。先看根 `README.md` 是否已有「测试 / 运行」说明——**有则不动**；**无则经确认门补进根 `README.md`**。

**范围规则**

- `current/` 覆盖 `role: landing` 的 app；`legacy/` 仅当存在 `role: legacy` 的 app（无则整目录缺席）。
- 同 role 多 app：域级文件内按 app 加小节 /「应用」列。
- 域目录只列有内容的域；某域某类别不适用 → 一句话「本类不适用于 <域> / <应用>」。
- 绿地项目：可只有 `tour.md` + `_meta.json` 起步，域级随代码增长补齐。

---

## 4. 每类的最小必填内容

### A. 技术栈 + 快速启动（**可选类**，根 `README.md`）

纳入时，「技术栈 / 启动」两节至少含：语言 / 运行时 + 版本 · 框架与关键库 + 版本 · 包管理器 · 端口 · 依赖安装命令 · 启动 / 停止命令 · 环境变量**名称**（**绝不写值/密钥**）· 已知坑（可选）。多 app 分小节；目标选型与实测分列须注明。**改写根 README 属确认门动作**（`global-rules.md` §7），只动这两节。

### B. global/directory-map.md

| 路径 | 类型 | 职责（一句话） | 域 | 备注 |
|---|---|---|---|---|

- 一级目录全部 + 关键二级模块；`域` 列给出模块→域映射。

### C. global/routes.md

| 应用 | 页面/路由 | 域 | 用途 | 关键交互 | 实现状态 | 来源文件 |
|---|---|---|---|---|---|---|

- 单 app 项目可省略 `应用` 列；多 app 必须带 `应用` 列（首列），取 `apps[].name`。
- `实现状态` 仅 `current/` 需要：`已实现` / `部分` / `未实现`；`来源文件` 可定位；`域` 与 `_meta.json.domains` 一致（非域页面写 `—`）。

### D. `<role>/<domain>/apis.md`（**条件类**）

按项目是否自带**机器可读接口描述**（OpenAPI / Swagger / GraphQL SDL / proto 等，由适配器探测）二选一，**不得两者都写**：

- **有** → 只记**真相源入口 + 访问 / 生成方式**，**不逐条复制端点**。
- **无**（如 action / RPC 形态）→ 才产出接口清单：

| 方法 | 路径 | 用途 | 请求要点 | 响应要点 | 来源模块 |
|---|---|---|---|---|---|

### E. `<role>/<domain>/data-models.md`

| 表/模型 | 字段 | 类型 | 约束/默认 | 关系 | 枚举 |
|---|---|---|---|---|---|

- 枚举单独一小节列取值与含义；跨域共享表落 `global/data-models-shared.md` 并在域内引用。

### H. 测试现状与运行方式（**条件类**，根 `README.md`）

**不入 spec**：先看根 `README.md`；已有「测试 / 运行」说明 → 不动；无 → 经确认门补一节（测试类型 / 位置 / 覆盖范围 / 运行命令 / 现状）。

> **组件清单不做**（增删频繁必漂、无强消费者）；「页面 / 域 → 组件」由 Trellis 侧按路径扫代码现得。

---

## 5. 生成方式与标注区块

| 类别 | 生成方式 |
|---|---|
| A、H（落根 README） | 人 / agent 撰写（确认门） |
| B、C、D、E 的可枚举部分 | **适配器脚本抽取**（profile 声明了才跑；规程见 §6.1） |
| 域提议聚类、B 语义部分、无适配器时全部 | **agent 阅读代码撰写**，标 `maintained_by: agent` |

**标注区块（事实区 / 语义区）**：事实类内容包在标记内，供刷新脚本确定性覆盖；标记外的语义内容由 AI 保留：

```markdown
<!-- atlas:facts:begin -->
| ... | 由适配器 + 刷新脚本生成，重跑覆盖 |
<!-- atlas:facts:end -->

## 语义说明
...agent / AI 维护，重跑保留...
```

**自动渲染（D69）**：`refresh_structure.py --apply` 读 `.adapter-out/*.json` **自动重写事实区表**：
- **行键级单元格合并**——适配器只填「可枚举列」，既有行的**语义列保留**，语义列留空的行由校验器记 **WARN** 指名（提示补，非 FAIL；`§B121`），消失的行从事实表移除；
- **归属算法**：条目 `source_file` → 所属 app（最长 `apps[].path` 前缀）→ role（`landing`→`current/`、`legacy`→`legacy/`）→ 域（最长 `glob` 命中）；
- **无域命中** → 落 `global/apis-shared.md` / `global/data-models-shared.md`，并在域内引用或补 globs；
- 无 `.adapter-out/` 时**跳过**事实表，由 agent / 适配器维持（不覆盖）。

适配器契约（调用方式、输出 JSON、每类 `items` 字段）**正文唯一落在 `.atlas/shared/stack-profile.md` §3**，本文件不重复。

---

## 6. 执行步骤

1. **读 profile**。缺失或字段不全 → 与用户确认后生成（确认门）。
2. **确定范围**。列出本次要刷新的 `(role, app, domain, category)`；**A 为可选类，先问用户是否纳入**（不纳入整类跳过、不计失败）。
3. **提议 / 更新域**：按 §2.1 聚类；已有 `_meta.json` 的 `已定稿` 域保持不变，只提议新候选域。
4. **逐类处理**：有适配器 → 按 §6.1 跑适配器、读 JSON、渲染 + 补语义；无 → agent 阅读代码撰写。
5. **写 `tour.md`**（L1：概况 + 域速查表 + 全局事实链接，≤ ~1.5k）与 `domains/<domain>.md`（L2 薄指针）。
6. **A / H 处理（条件）**：A 如纳入 → 核对 / 补齐根 README 两节；H → 检查根 README 是否有测试 / 运行说明，无且用户同意则补。
7. **写 `_meta.json`**（product / baseline / apps / domains / categories 状态）。
8. **跑校验（§7）**，失败则修复后重跑。
9. **出报告（§9）**。

### 6.1 适配器消费规程（agent 执行）

适配器**只产 JSON、不写文档**；渲染与语义补全由本环 agent 完成。步骤：

1. **解析适配器名**：读 `product/stack-profile.yaml` 的 `adapters`；按 `.atlas/shared/stack-profile.md` §3.3 解析到脚本；`null` 即跳过该类别（降级 agent 撰写）。
2. **按类别调用**（`--app` 归属见 §3.1）：
   - **全局类别** `routes`：整项目调一次 → `.adapter-out/routes.json`。
   - **域级类别** `api` / `models` / `tests`：对每个 app 各调一次 → `.adapter-out/<category>/<app>.json`。
   - 命令：`python3 <脚本> --root <项目根> [--app <name>] --out <上述路径>`。
   - **文件枚举通道**（2026-10-05 图谱批 1）：profile 声明 `graph.backend` 时 routes 适配器自动走图谱枚举（用前现刷，契约见 `shared/stack-profile.md` §3.6）；后端不可用 ⇒ 适配器**显式降级** regex（stderr WARN + `backend_fallback` 字段）。§9 报告须标注实际通道：`adapter:routes(backend:graph|regex)`。
3. **读 JSON 渲染事实表**：`items` 逐行填「可枚举列」；遇到 `api` 的指针形态（有 `spec_entry`、无 `items`）→ 按 §4 D 的「有描述」写法只记真相源入口，**不得**补清单。
4. **补语义列**：`域` / `用途` / `关键交互`（C）、`请求要点` / `响应要点`（D）等非机械列由 agent 阅读代码后填写；候选域归属按 `_meta.json.domains` 的域→globs 映射。
5. **标注**：事实类表格包进 `<!-- atlas:facts:begin/end -->`（`global/*.md`、`{current,legacy}/<domain>/*.md`）；标记外的语义说明保留。
6. **报告**：按 §9 第 2 条标明每个 `(role, app, domain, category)` 是 `adapter:<名>` 还是 `agent`。

> 适配器**不直接改写文档**：它只产 JSON；渲染由 `refresh_structure.py --apply` 完成（读 `.adapter-out/*.json` → 重写 `atlas:facts` 标记内的行键级单元格，语义列保留、新增行语义列留空记 WARN；2026-09-20 落地，D69）。无 `.adapter-out/` 时跳过该类别，由 agent / 适配器维持（不覆盖）。

### 6.2 适配器接线判据与「diff 即对账」（2026-09-28 定，`3508 §98 ⑩` 定形 + 批 6 第 8 项落地）

**接线** = 把 `stack-profile.yaml` 的 `adapters.<类别>` 从 `null` 改为真实适配器名。此前全 `null` ⇒ 结构事实全由 agent 撰写 ⇒ **`structure ↔ 代码` 对账平面是缺口**（事实随每域实现过期一次）。

**判据（满足其一才接；两者皆无 ⇒ 源即真相，不接）**：

| 判据 | 含义 |
|---|---|
| ① **聚合价值** | 事实**散落多处、源难以直接阅读**（抽取 = 把散落的收拢，读者不必再读源码） |
| ② **第三方对账方** | 存在**需要与该事实对账的另一工件**（抽取 = 给对账方一个可 diff 的基准） |

**两者皆无 ⇒ 不接**：抽取即拷贝，拷贝即漂移面（源本身已是唯一真相且易读，再抽一份只是多一个会过期的副本）。

**逐件判定（2026-09-28）**：

| 类别 | ① 聚合 | ② 对账方 | 结论 |
|---|---|---|---|
| `routes` | 有（前后端聚合） | 有（PRD 页面清单 / E2E 索引页面表） | **接** |
| `api` | 有（装饰器散落各文件） | 无 | **接** |
| `models` | 有 | 有（**seed × models 静态对账**，见 `rings/e2e/reference.md` §5.7） | **接** |
| `tests` | 无 | 无 | **不接** |

**「diff 即对账」（接线后本平面的门）**：接线后适配器输出 = **确定性集合** ⇒ `structure ↔ 代码` 从「缺口」转为**配门**：重跑适配器 → `refresh_structure.py --apply` → 事实区与代码的差集 = 待更新面（新增行 / 消失行 / 变化行）；判据 = 重跑后事实区无未吸收的差集。

**F 类退役（2026-09-30，用户拍板「直接删」，`3508 §156`）**：F 类（设计 token）整体移除——类别清单 / 模板 / 校验器判据 / `tokens` 适配器键与脚本 / 产物文件全删；实现期视觉参考 = 前端样式表本身（真相源迁移登记见 `single-source.md` §3）。

**未接类别**：由 agent 撰写（标 `maintained_by: agent`）；**未接 ≠ 缺陷**，而是「源即真相」的判定结果。

**接线前置（硬，2026-09-28 实测后补，`3509 §B118`）**：**接线动作前必须先跑一次适配器，验「产出非空」。**

- 判据：`items` 为空**且**不是 D 类的合法指针形态（有 `spec_entry`、无 `items`）⇒ **不得接线**。
- 理由（实测）：本轮对真实项目做只读探针（**未改 `stack-profile.yaml`**）：`routes` **0 条**（不认本栈的**文件式路由**：`frontend/src/routes/` + `routeTree.gen.ts`）、`models` **0 字段 / 0 源文件**、`api` **0 items 但有 `spec_entry=/openapi.json`**（✓ 正是 D 类「有描述」的合法形态）。
- 危害：**把缺口伪装成配门** —— 接上线后事实表是空的，而「diff 即对账」会给出「无差集」的绿灯 ⇒ 比现在**诚实的缺口**更糟（同族：`§B92`/`§B95`/`§B110` 的「看起来在跑」）。
- 因此：**适配器对本栈的覆盖**是「三接」的前置；前置未满足时，正确处置 = **不接线** + 把缺口写进台账（`§B118`），而不是把 `null` 换成会空转的适配器名。

---

## 7. 校验清单（本环门）

| 项 | 判定 |
|---|---|
| 域模型 | `_meta.json.domains` 存在；域 id 全产品唯一；域目录与 `domains[]` 一致；`global/routes.md` 的「域」列均在 `domains[]` 内；每个域 `globs` 非空 |
| 类别覆盖 | `global/`：directory-map / routes 齐；**每个存在的 role 目录下**每个域子目录含 apis + data-models 各 1 份（域可只在部分 role 有内容）。**A / H 不入 spec**：须在 `_meta.json.categories` 注明 —— `A: covered\|skipped`；`H: covered\|added`（**`greenfield` 下亦可用 `skipped`，`adopt` 下不可** —— 既有项目必须把「怎么跑」记下来，所以只能是 `covered`（README 本就有）或 `added`（本轮补写）。2026-09-27 补，`3509 §B82`） |
| D 形态 | `apis.md` 要么清单、要么「真相源入口 + 访问方式」；不得混写 |
| 指针预算 | 对每个域校验 `len(tour.md) + len(domains/<d>.md)` ≤ `.trellis/config.yaml` 的 `spec_injection.max_total_chars`（默认 9500）；超出须缩 L1 / 拆域 |
| 注入结构 | `tour.md` 与 `domains/*.md` 的 `paths:` 为**块列表**（标量会被判 malformed → 不注入） |
| 占位符 | 无未完成 / 待填字样。**例外**：① 代码语法 `...`；② A 的「待决策」小节；③ 描述占位符规则的行本身 |
| 表格列 | 每张表列头与 §4 一致 |
| 来源可定位 | `来源文件` 路径按**项目根**解析真实存在；短引用允许再按**所属 app 根**解析（`_meta.json.apps[].path`） |
| 密钥泄漏 | 全文不含密钥 / 令牌 / 密码**值**；环境变量只写名称 |
| 元数据一致 | `_meta.json` 与磁盘实际文件集合一致 |
| 幂等 | 重跑后**事实区标记外**内容字节不变 |

---

## 8. 维护（事实区 / 语义区）

| 通道 | 谁跑 | 何时 | 覆盖 |
|---|---|---|---|
| **语义** | `trellis-update-spec`（AI）/ 人工 | Finish 原生步骤 | 经验 / 规范 / 坑（标记外） |
| **事实** | **刷新脚本**（读适配器 → 填 `atlas:facts` 区 → 推进 `_meta.json.baseline`） | **`after_finish` hook**（`.trellis/config.yaml.hooks.after_finish`）或手动 | 表 / 字段 / 路由 / 接口 / token（标记内） |

- 事实刷新是**纯脚本**，适合 shell hook；hook 失败只告警、不阻塞任务。
- hook 用**单行登记**（官方扩展点），不改 `workflow.md` 结构——Trellis 升级时冲突最小。
- 刷新脚本实现依赖适配器（未决 B1）；未接适配器的类别由 AI 维持。
- 结构刷新（或域定稿）后**重跑本环**或**手动跑刷新脚本**。

---

## 9. 报告格式

1. **域清单变化**（新增 / 信号冲突 / 已定稿保留）
2. **刷新的类别**（按 role/app/domain 分组，标明 `adapter:<名>` 或 `agent`）
3. **A / H 处置**（A 纳入？H README 已有 / 已补）
4. **未发现 / 无法取证**及取证范围
5. **校验结果**（通过 / 失败项，含指针预算）
6. **下一步建议**（例如：`atlas prd` 读 `_meta.json.domains` 定稿域）
