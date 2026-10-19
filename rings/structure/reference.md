# atlas structure — 结构基线（逆向）

> 本环为 atlas 独立 skill `atlas-structure` 的执行契约，位于 `.atlas/rings/structure/reference.md`。
> 执行前先读共享契约：`.atlas/shared/global-rules.md`、`stack-profile.md`、`single-source.md`、`layout.md`。

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
| 项目根 `README.md`（或 `_meta.json` 声明的 `truth_carriers`） | 是 | A（技术栈 + 启动）与 H（测试 / 运行）的真相源 |
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

**A 的落点（可选类）**：技术栈 + 快速启动**不入 spec**；真相源缺省是**项目根 `README.md`** 的「技术栈 / 启动」两节，或 `_meta.json` 声明的载体文件（如 `AGENTS.md`）。是否纳入由用户决定（§6 步 2）；纳入时只核对 / 补齐该两节。

**H 的落点（条件类）**：测试现状与运行方式**不入 spec**。先看根 `README.md`（或 `_meta.json` 声明的载体文件）是否已有「测试 / 运行」说明——**有则不动**；**无则经确认门补进对应载体文件**。

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
- **`页面/路由` 的口径 = 全站绝对路径**（2026-10-16 补，issue #15，D84）：模块自己的路由表写的是**模块相对**路径（如 `/create`），必须由**挂载前缀**合成后再入表——挂载关系取自站点级表「条目路径 → 懒加载 / 导入的模块文件」。若不做合成，多个模块的同名路径会撞上本表的行键 `(应用, 页面/路由)` 被折叠成**假事实**（不是少报，是多报）。**合成不出的条目不产出**（宁缺不产假路径），数量与原因在适配器产物的 `route_coverage`（`.atlas/shared/stack-profile.md` §3.2）与 stderr 同时给出。

### D. `<role>/<domain>/apis.md`（**条件类**）

**先问用户**：「后端有没有机器可读接口描述（OpenAPI / Swagger / GraphQL SDL / proto…），地址在哪？」
——描述**常在仓外**（网关 / 独立文档站 / 运行时端点），**仓内探测不到不等于没有**
（`shared/stack-profile.md` §3.5）。三选一，**不得混写**：

- **有** → 只记**真相源入口 + 访问 / 生成方式**，**不逐条复制端点**（地址在仓外也照记）。此时
  `adapters.api` 置 `null`、整类交给 agent 记指针——**不接源码枚举适配器**。
- **无**（用户确认）→ 才产出接口清单：

| 方法 | 路径 | 用途 | 请求要点 | 响应要点 | 来源模块 |
|---|---|---|---|---|---|

- **未答** → 按「地址未取证」记 `categories.D` 并在 §9 报告点名，**不得**当成「无」去枚举。

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

1. **读 profile**。缺失或字段不全 → 与用户确认后生成（确认门）。**同一次确认里办三件事**：
   - **探测图谱后端并向用户提议**声明 `graph` 段——**按栈门控**：仅当 `apps[]` 存在 `kind ∈ {backend, fullstack}` 的 app 时才探测并提议；全部 app 为 `frontend` / `mobile` 时**不提议**（实测 cgc 0.6.13：JSX 组件引用不产生调用边，两条消费面对纯 UI 栈近乎零收益；双层判据与如实口径的唯一正文见 `shared/stack-profile.md` §2）。口径必须如实：它换来的只是 `routes` 的文件枚举通道（与 regex 恒等）与 `apply` 影响面基准（对逻辑调用有效、组件叶面失真），不是「跨文件逆向分析」。项目根 `.adapter-out/` 的 git 忽略由接线自动处理（`.gitignore` 存在时追加，无则接线报告提示），无需口头另嘱。
   - **A 为可选类，先问用户是否纳入**（不纳入整类跳过、不计失败）。
   - **问 D 类形态**：后端有没有机器可读接口描述、**地址在哪**（网关 / 文档站 / 运行时端点都算；
     仓内探测不到 **≠** 没有——§4 D 与 `shared/stack-profile.md` §3.5）。答「有」⇒ 该类别走指针形态、
     `adapters.api` 置 `null`；答「无」⇒ 才落源码枚举；**未答 ⇒ 不得当「无」**，记 `categories.D`
     并在 §9 点名「未取证」。
2. **确定范围**。列出本次要刷新的 `(role, app, domain, category)`。
3. **提议 / 更新域**：按 §2.1 聚类；已有 `_meta.json` 的 `已定稿` 域保持不变，只提议新候选域。
4. **域清单确认门**（2026-10-15 补）：把候选域表（域 id / 中文名 / 涉及 app / globs）**先交给用户过一遍，再动手铺域级文件**。域 id 是全链路键——PRD 定稿时会合并 / 拆分 / 改名，本环随后要 re-key（§2.2）⇒ 在未确认的粒度上先铺域级事实，等于确认后整批重排（实测：一次 adopt 在用户看过域表之前生成了 51 个文件，事后判定其中 6 个管理后台域应合成 1 个，域数 16 → 11）。用户不在场或明说按默认继续 ⇒ 照候选域产出，`status` 保持 `候选`，并在 §9 报告里**点名「域清单未确认」**，不得当成已定稿。
5. **逐类处理**：有适配器 → 按 §6.1 跑适配器、读 JSON、渲染 + 补语义；无 → agent 阅读代码撰写。
6. **写 `tour.md`**（L1：概况 + 域速查表 + 全局事实链接，≤ ~1.5k）与 `domains/<domain>.md`（L2 薄指针）。
7. **A / H 处理（条件）**：A 如纳入 → 核对 / 补齐根 README 两节；H → 检查根 README 是否有测试 / 运行说明，无且用户同意则补。
8. **写 `_meta.json`**（product / baseline / apps / domains / categories 状态 / **`adapter_gaps`**——本环有未接类别时非空，见 §6.1 接线前置）。
9. **跑校验（§7）**，失败则修复后重跑。
10. **出报告（§9）**。

### 6.1 适配器消费规程（agent 执行）

适配器**只产 JSON、不写文档**；渲染与语义补全由本环 agent 完成。步骤：

1. **解析适配器名**：读 `product/stack-profile.yaml` 的 `adapters`；按 `.atlas/shared/stack-profile.md` §3.3 解析到脚本；`null` 即跳过该类别（降级 agent 撰写）。
2. **按类别调用**（`--app` 归属见 §3.1）；产物一律落**项目根** `.adapter-out/`（atlas 全部中间产物的单一位点，与漂移标记 / 图谱标记同址，2026-10-15 统一，issue #8）：
   - **全局类别** `routes`：整项目调一次 → `<项目根>/.adapter-out/routes.json`。
   - **域级类别** `api` / `models` / `tests`：对每个 app 各调一次 → `<项目根>/.adapter-out/<category>/<app>.json`。
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

**接线前置（硬，2026-09-28 实测后补，`3509 §B118`；2026-10-15 扩为「非空**且逐条自洽**」+ **缺口登记**）**：**接线动作前必须先跑一次适配器，验「产出非空且逐条自洽」。**

- 判据：`items` 为空**且**不是 D 类的合法指针形态（有 `spec_entry`、无 `items`）⇒ **不得接线**。
- 判据（2026-10-15 补，issue #4）：`items` **非空但逐条不自洽**（条目自称的形态与产出的事实矛盾，如 `location` 是 `.test.ts` 而 `run_command` 是 `python3 -m pytest`）⇒ **同样不得接线**。`§B118` 只识别了「产出为空」那一类假绿灯，**没覆盖「产出非空但内容错」**——而后者更危险：它带着合法形态混进事实区，并随 `--chain` 反复回来。
- **不接线时必须在 `_meta.json.adapter_gaps` 登记缺口**（2026-10-15 补，issue #3 ④）：形如 `{"routes": "0 命中（文件式路由 + .tsx）"}`（类别 → 为什么没接 / 探测为空的取证）；下轮前置满足后删掉该项。**不登记的话两种性质完全不同的处境在产物里同形**（都是 `maintained_by: agent`）：(a) 设计结论「源即真相，不接」（缺口是结论）；(b) **工具覆盖不足**（逐件判定表判「接」，但本栈 0 命中，缺口是工具的问题）。采用者会把 (b) 读成 (a)，而该类别 `structure ↔ 代码` 的对账平面**永久缺口、且无人知道它不是预期的**——`§B118` 论证了「把缺口伪装成配门比诚实缺口更糟」，本条补的是反面：**把工具覆盖不足伪装成审慎的设计结论，同样是伪装**。`validate_structure` 读该字段并对非空值出 `WARN`（`atlas_check` 体检报告可见）。
- 做法：不自洽的字段一律**留空**（`null` = 无主张），并在 stderr 出声点名；不要把矛盾条目包装成合法产出。适配器侧的对应纪律见 `shared/stack-profile.md` §3.2 的 `tests` 条。
- 判据（2026-10-16 补，issue #16，D85）：**渲染可读回** —— 事实表单元格的取值必须能被 `parse_rows` 逐单元格读回（多行取值由写侧单行化为 `<br>`，见 `render_table`）。判据 = 重跑 `refresh_structure --apply` **两遍**：第二遍**零键级漂移**且字节幂等；`WARN[render_table]`（渲染内自校）不得出现。反过来说，「接线后每轮都报**同一批** `+` 键」正是本判据被违反的现场形态——那不是源码变更，是**写入即损坏**（事实丢行 + 幻影漂移 + baseline 棘轮永冻结）。
- 理由（实测）：本轮对真实项目做只读探针（**未改 `stack-profile.yaml`**）：`routes` **0 条**（不认本栈的**文件式路由**：`frontend/src/routes/` + `routeTree.gen.ts`）、`models` **0 字段 / 0 源文件**、`api` **0 items 但有 `spec_entry=/openapi.json`**（✓ 正是 D 类「有描述」的合法形态）。
- 危害：**把缺口伪装成配门** —— 接上线后事实表是空的（或错的），而「diff 即对账」会给出「无差集」的绿灯 ⇒ 比现在**诚实的缺口**更糟（同族：`§B92`/`§B95`/`§B110` 的「看起来在跑」）。
- 因此：**适配器对本栈的覆盖**是「三接」的前置；前置未满足时，正确处置 = **不接线** + **在 `_meta.json.adapter_gaps` 登记缺口**（上面那条；此前写作「把缺口写进台账 `§B118`」，而那个台账**不在本仓** ⇒ 缺口被记在采用者读不到的地方），而不是把 `null` 换成会空转（或会产错事实）的适配器名。

---

## 7. 校验清单（本环门）

| 项 | 判定 |
|---|---|
| 域模型 | `_meta.json.domains` 存在；域 id 全产品唯一；域目录与 `domains[]` 一致；`global/routes.md` 的「域」列均在 `domains[]` 内；每个域 `globs` 非空 |
| 类别覆盖 | `global/`：directory-map / routes 齐；**每个存在的 role 目录下**每个域子目录含 apis + data-models 各 1 份（域可只在部分 role 有内容）。**A / H 不入 spec**：须在 `_meta.json.categories` 注明 —— `A: covered\|skipped`；`H: covered\|added`（**`greenfield` 下亦可用 `skipped`，`adopt` 下不可** —— 既有项目必须把「怎么跑」记下来，所以只能是 `covered`（README 本就有）或 `added`（本轮补写）。2026-09-27 补，`3509 §B82`）。**写法（2026-10-15 补）**：处置是**枚举声明**，须写在字段**首位**——可选一个 `<标签>:` 前缀（`A: covered` / `H：covered`），token 之后接 `：` / `（` 再写取证文本，或就此结束；如 `covered：根 README「技术栈」「快速开始」两节齐备`。**只是「提到了」该词不算声明**（`待核准：…核准后补写为 added`、`covered 与否未定` 一律 FAIL）——判据读的是状态，不是措辞 |
| 适配器缺口 | `_meta.json.adapter_gaps` 缺失或为**空对象** ⇒ 无缺口（不产行）；**非空对象** ⇒ `WARN` 逐条指名（不是 FAIL——「未接」本身不是缺陷，但**必须可见**，否则「设计结论不接」与「工具覆盖不足」在产物里同形）；形态非法（非对象）⇒ `FAIL`。2026-10-15 补，issue #3 ④ |
| D 类接线态 | `adapters.api` **已接线**但 `categories.D` 锚定声明为**指针 / 未取证**形态、或 `adapter_gaps` 登记了 `api` ⇒ `WARN` 指名（接线态与形态声明跨产物混写——`shared/stack-profile.md` §3.5：该形态**不得接**源码枚举适配器，`adapters.api` 应置 null）。锚定声明口径（F38 同族）：token 在首位 + 显式分隔符，散文提及不算声明；profile 不存在 / `adapters.api` 未声明 ⇒ 不产行（profile 合法性归 `validate_stack_profile`）。2026-10-15 补 |
| D 形态 | `apis.md` 要么清单、要么「真相源入口 + 访问方式」；不得混写 |
| 指针预算 | 对每个域校验 `len(tour.md) + len(domains/<d>.md)` ≤ `.trellis/config.yaml` 的 `spec_injection.max_total_chars`（默认 9500）；超出须缩 L1 / 拆域 |
| 注入结构 | `tour.md` 与 `domains/*.md` 的 `paths:` 为**块列表**（标量会被判 malformed → 不注入） |
| 占位符 | 无未完成 / 待填字样。**例外**：① 代码语法 `...`；② A 的「待决策」小节；③ 描述占位符规则的行本身 |
| 表格列 | 每张表列头与 §4 一致 |
| 来源可定位 | `来源文件` 路径按**项目根**解析真实存在；短引用允许再按**所属 app 根**解析（`_meta.json.apps[].path`）；**spec 内相对引用合法**（F34b，R8：结构文档引用兄弟 spec 相对文件时以 `.trellis/spec/structure/` 为锚——幻影引用照拦） |
| 密钥泄漏 | 全文不含密钥 / 令牌 / 密码**值**；环境变量只写名称 |
| 元数据一致 | `_meta.json` 与磁盘实际文件集合一致 |
| 幂等 | 重跑后**事实区标记外**内容字节不变 |

---

## 8. 维护（事实区 / 语义区）

| 通道 | 谁跑 | 何时 | 覆盖 |
|---|---|---|---|
| **语义** | `trellis-update-spec`（AI）/ 人工 | Finish 原生步骤 | 经验 / 规范 / 坑（标记外） |
| **事实** | **刷新脚本**（`--chain`：读适配器 → 填 `atlas:facts` 区 → L2 指针单遍化；F26 基线自进——`--chain` 无漂移且四前置满足时自动推进 `_meta.json.baseline`，漂移冻结待终审，显式 `--apply` 零变化承诺永不推进，`--advance-baseline` 显式越过） | **`after_finish` hook**（`.trellis/config.yaml.hooks.after_finish`，R7 原位迁移为 `--chain`）或手动 | 表 / 字段 / 路由 / 接口 / token（标记内） |

- 事实刷新是**纯脚本**，适合 shell hook；hook 失败只告警、不阻塞任务。
- hook 用**单行登记**（官方扩展点），不改 `workflow.md` 结构——Trellis 升级时冲突最小。
- **适配器失败语义（F25 拍板，2026-10-15）**：`--chain` 下任一适配器非零退出 / 解析不到脚本 ⇒ 中止链条、不进 refresh、exit 2；中止前已落盘适配器产物 = 上一轮一致态，残留无害。
- **history 与 baseline 正交**：`_drift-history.jsonl` 记漂移**事件流**（追溯），`baseline.commit` 记快照**锚点**（对账位），两者不互相背负，无需互斥设计。
- 刷新脚本实现依赖适配器（未决 B1）；未接适配器的类别由 AI 维持。**D 类指针形态豁免（F33，R8）**：`global/apis-shared.md` 真相源行命中 app 名 ⇒ 该域 `apis.md` 缺失合规（覆盖判据内建），免手写域级指针文件。`tests` 适配器产物存在时，`tour.md` 项目概况渲染其 `run_command`（F29 消费披露）。
- 结构刷新（或域定稿）后**重跑本环**或**手动跑刷新脚本**（`--apply` 的行为零变化承诺保留）。

---

## 9. 报告格式

1. **域清单变化**（新增 / 信号冲突 / 已定稿保留；**未经用户过目的候选域必须显式标注「未确认」**，见 §6 步 4）
2. **刷新的类别**（按 role/app/domain 分组，标明 `adapter:<名>` 或 `agent`）
3. **A / H / D 处置**（A 纳入？H README 已有 / 已补？**D 形态 = 指针 / 清单 / 未取证**）
4. **未发现 / 无法取证**及取证范围（**含 `_meta.json.adapter_gaps` 的未接类别**：逐条说明是「设计结论：源即真相」还是「工具覆盖不足」——两者不可混为一谈，见 §6.1）
5. **校验结果**（通过 / 失败项，含指针预算）
6. **下一步建议**（例如：`atlas prd` 读 `_meta.json.domains` 定稿域）
