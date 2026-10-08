# atlas 共享契约 — stack-profile 与适配器

> atlas 核心只读 `product/stack-profile.yaml` 来认识项目；本文件是它的**字段契约**与**适配器契约**的唯一正文。
> 各环按路径引用 `.atlas/shared/stack-profile.md`。

## 1. 位置与生成

- 路径：`<项目根>/product/stack-profile.yaml`。
- 由 atlas 与用户确认后生成；**生成或改写必须过用户确认门**（见 `global-rules.md` §7）。
- 字段缺失会让对应能力降级，降级行为见各环契约。

## 2. 字段契约

### `product`

产品名。项目级资产的归属维度：**一个产品一份 atlas 资产**。

### `origin`

项目的**来源形态**（2026-09-26 补）。它决定各环的**默认形态**，是 atlas 认识项目时最先读的一格。

| 取值 | 含义 | 各环默认 |
|---|---|---|
| `greenfield`（**缺省值**） | atlas 从 0 建这个产品 | testid 应然 = 用例分片、实然 = 前端源码（E1，与 adopt 同源） |
| `adopt` | 既有项目接入（接手 / 维护既有实现） | testid 实然 = 真实 UI（与 greenfield 同源）；PRD 走「增量起步」 |

- **缺省 = `greenfield`**：未声明时按既有行为处理（向后兼容，不会静默切形态），校验器记 **WARN** 提示补齐。
- **只定默认，不剥夺能力**：`origin` 只定**默认形态**；`apply` 的三问门（`apply/reference.md` §3.1）按需求逐条决定拉起哪些环（E1：原型环已移除）。
- 非法取值 = **FAIL**（`validate_stack_profile.py` 的枚举门）。
- **各环的分支正文不在本文件**：testid 真相源与抽取源见 `rings/e2e/reference.md` §4 与 `single-source.md` §1；接入动作见 `apply/reference.md`。本文件只定义这一格的取值与语义。

### `apps[]`

| 字段 | 必填 | 取值 / 含义 |
|---|---|---|
| `name` | 是 | app 标识 |
| `path` | 是 | 相对项目根的路径 |
| `kind` | 是 | `frontend` \| `backend` \| `fullstack` \| `mobile` |
| `role` | 是 | `landing` \| `legacy`（决定结构事实去向，见 `layout.md`） |
| `stack` | 是 | 自由文本，**仅供展示**；atlas 不据此做任何判断 |

### `adapters`

四个可枚举事实类别，各声明一个适配器名或 `null`：

| 键 | 对应结构事实类别 |
|---|---|
| `routes` | C 路由 / 页面清单 |
| `api` | D 接口清单 |
| `models` | E 数据模型清单 |
| `tests` | H 测试现状 |

- 值为 `null` → 该类别降级为 agent 撰写，结构基线 `README.md` 标 `maintained_by: agent`。
- 值为非空 → 必须能被解析到 `adapters/` 下的可执行脚本（解析规则见 §3.3）。

### `knowledge`

知识库（Obsidian）同步声明。**可选增强**：缺省或 `vault: null` ⇒ 跳过知识库同步，不阻断任何环。契约见 `shared/knowledge.md`。

| 字段 | 必填 | 说明 |
|---|---|---|
| `tool` | 否 | 固定 `open-zk-kb`；写入 / 检索经该 MCP |
| `vault` | 否 | vault 根绝对路径；`null` = 不启用 |
| `dir` | 否 | vault 内**唯一**的 atlas 设计目录（相对 vault 根），所有项目共用 |
| `project` | 否 | open-zk-kb 的 project 作用域 |

### `graph`（可选：代码图谱后端）

**可选增强**（2026-10-05 图谱批 1）：声明后，文件枚举 / 影响面基准等消费者走代码图谱；
段缺失或 `graph: null` = 不用图谱（合法降级，各消费者显式 `not_ready` 或回退正则）。
接触面与纪律的唯一正文见 §3.6。

| 字段 | 必填 | 说明 |
|---|---|---|
| `backend` | 声明段时必填 | 图谱后端名，枚举：`cgc`（CodeGraphContext，MIT，PyPI 包 `codegraphcontext`，可执行名 `cgc`） |
| `pinned` | 否 | 期望的后端版本（语义版本形态）；与实装失配 ⇒ 消费者显式 WARN（不阻断） |

- 声明了但后端不可用 ⇒ **响亮降级**（适配器 stderr WARN + 输出 `backend_fallback`；报告器 exit 3 `not_ready`），绝不静默改道。
- 显式 `--backend graph` 而后端不可用 ⇒ 硬错（显式要求不得被静默改道）。

### `e2e`（含已退役的 `prototype`）

| 段 | 字段 | 说明 |
|---|---|---|
| `prototype` | （已退役，E1） | **atlas 不再消费任何字段**；存量项目可保留（历史）或删除。原型环移除见 `3508 §92` |
| `e2e` | `runner`（`python-playwright` \| `node-playwright`）/ `cases_dir` / `index` / `scripts_dir` / `app_base_url` / `node_modules`（node 运行器的依赖目录，`atlas_check` 据此定位可执行与 NODE_PATH）/ `reset`（可选：真跑前执行的靶场重置 shell 命令串，项目相对 cwd；null = 无重置，合法降级） | 用例组织与**单段执行**（真实应用；E1 起原型靶场已退役） |
| `e2e` | `app_login`（子段：`endpoint` / `username_field` / `password_field` / `token_key` / `storage_key`） | **应用靶场登录预置的取证值**（2026-09-28 补，`3509 §B101`）：OAuth2 表单端点（相对 base_url 的路径）、表单字段名、响应令牌键、前端读取的 localStorage 键。生成时烘进运行器配置；**凭据仍只来自运行期环境变量**（`rings/e2e/reference.md` §7.1）。**段缺失 = 合法降级**（跳过登录预置 + 生成与运行期明确警告）；段存在但字段不齐 ⇒ 生成报错 |
| `e2e` | `review` / `review.model` | 独立审查执行器（语义见 `rings/e2e/reference.md` §12） |
| `e2e` | `seed`（子段：`hook` / `mode`） | **数据播种通道**（2026-09-28 补，`3509 §98 ⑪`）：`hook` = 项目自定实现的脚本路径（相对项目根），接口语义 = 「输入实体清单 ⇒ 保证存在」（幂等 upsert），生成时烘进 `_SEED`。`mode`（2026-10-07 补，B197-1）= **声明 / 发射解耦开关**：`enforce`（**缺省** = 现行为）= 每用例运行期播种；`declare` = `seed:` 行只参与静态对账（`rings/e2e/reference.md` §5.7 的 seed×models 门）、**不发射**运行期播种——累加链项目（运行期重播会撤销链上破坏性动作）的合法形态；取值白名单外 ⇒ 校验器 FAIL + 生成器报错。**段缺失 = 合法降级**（mode 按 enforce + hook 未声明 ⇒ 生成期 WARN + 运行期明确警告）。用例侧 `seed:` 块见 `rings/e2e/reference.md` §5.7 |

**`review` 字段的两条口径（写死）**：

1. **只定 `null` 的语义** —— `null` = 用会话环境的默认子代理机制；**非空取值的解析规则由执行器定义**（目前只有一个执行器，为不存在的第二个造机制 = 空头契约）。
2. 契约**不写任何具体工具名 / 模型名**（`global-rules.md` §1）；两条硬要求（审查者 **fresh context** / **档位不得低于生成者**）在 `shared/independent-review.md` §5。

## 3. 适配器契约

适配器是独立可执行脚本，只做「代码 → 结构化事实」，**输出结构化数据、不写文档**。

### 3.1 调用

```
<adapter> --root <代码根> [--app <name>] --out <json 路径>
```

- `--root` 传**项目根**（`source_file` 用项目根相对路径）；`--app` 传 `apps[].name` 时只扫该 app。
- **域级类别**（`api` / `models` / `tests`）的 `items` 需归属到 app（契约字段无 app 列）⇒ 由调用方**按 app 各调一次**再合并；**全局类别**（`routes`）可整项目调一次。
- **产物落点约定**：`--out` 写 `<项目根>/.trellis/spec/structure/.adapter-out/<category>[/<app>].json`（全局类别写 `.adapter-out/routes.json`，按 app 类别写 `.adapter-out/models/<app>.json`）。它是**中间产物、非真相源**，不进注入、可覆盖重生成。

### 3.2 输出 JSON

```json
{
  "category": "routes",
  "items": [ { "...": "见下表的类别字段" } ],
  "source_files": ["相对路径", "..."],
  "adapter_version": "0.1.0"
}
```

**每类 `items[]` 字段**（`?` = 可空）。适配器只出**机械可抽**字段；用途 / 交互 / 语义等由 agent 补（见 `rings/structure/reference.md` §4）：

| category | `items[]` 字段 | 备注 |
|---|---|---|
| `routes` | `path` · `name?` · `component?` · `auth?` · `params?` · `source_file` · `status?` | `status` 仅 landing（`current/`）需要 |
| `api` | `method` · `path` · `summary?` · `source_module` · `source_file` | 有机器可读描述时**不产 `items`**，改产 `{category:"api", spec_entry:"…", source_files:[…]}`（见 §3.5） |
| `models` | 每字段一行：`table` · `field` · `type` · `constraints?` · `default?` · `relation?` · `enum?` · `source_file`；另加顶层 `enums[]`：`{table, field, values:[{value, meaning}]}` | 对应 `data-models.md` 表；`source_file` 供「表→域」归属（C7） |
| `tests` | `type`(unit/integration/e2e/other) · `location` · `run_command?` · `status?` | `status` 属运行事实，适配器留空由 agent 补 |

- `items` 与渲染出的 markdown 表**逐行对应**；适配器不产表格外的语义列。
- 目录地图（B）**无适配器键**，恒由 agent 撰写。
- **域级类别**（`api` / `models` / `tests`）的 `items` 按**代码键**（模块 / 表 / 页面）给出；**按域分组由 structure 环依 `_meta.json.domains` 的域→globs 映射完成**——适配器不认产品域。

### 3.3 名字 → 脚本解析

- `stack-profile.adapters` 的值是**适配器名**，解析顺序：
  1. `<项目根>/.atlas/adapters/<名字>`（包内首批）；
  2. `<项目根>/.atlas/adapters/<名字>.py`（Python 入口）；
  3. 目标项目根下同名可执行文件（项目自带）。
- 解析失败 → 视为未提供，该类别降级为 agent 撰写，并在结构基线 README 记为「适配器缺失」风险。

### 3.4 约束

- **只读**代码；**幂等**（同输入同输出）。
- 失败时非零退出，且不产出半成品。
- 不写文档；渲染进标记区块由 agent 完成（见 `global-rules.md` §4）。

### 3.5 D 类（接口）的条件形态

项目是否自带**机器可读接口描述**（OpenAPI / Swagger / GraphQL SDL / proto 等）由适配器探测，核心不认框架：

- **有** → 用一个读取该描述的适配器（如 `openapi`）声明到 `adapters.api`；结构基线的 `*/apis.md` 只记**真相源入口 + 访问方式**，不逐条抽取。
- **无** → 用从源码抽取的适配器，或降级为 agent 撰写接口清单。

### 3.6 图谱接触面（`adapters/_graph.py`；2026-10-05 图谱批 1 定形）

**全线只有 `_graph.py` 允许接触图谱后端**（防腐层）：后端可换、确定性契约单点实现、
降级语义统一定义。任何脚本不得自行拼后端 CLI 或读图数据库。

- **调用**：`import _graph`（同包 `adapters/` 内）；入口 `detect / ensure_index / query / callers / symbols_in_files / file_paths / load_graph_config`。
- **用前现刷（唯一更新机制）**：每个消费者查询前调 `ensure_index()`——新鲜度键 =
  git HEAD + 脏文件集的 sha1，键一致直接返回，不一致全量重建并写新鲜度标记
  （`.adapter-out/_graph_index.json`）。没有独立更新节拍、没有 watch 守护进程；
  **过期状态在消费时构造性不存在**。
- **确定性**：所有查询带 `ORDER BY`、输出键序固定，同代码态重跑字节一致——上层
  可 diff、可对账的前提；对账面（批 2 impact 门）以此为先决条件。
- **影响面口径（`impact_report.py` + `_graph.callers`）**：调用方查询是 **name 级匹配**
  ——同名多定义并入，影响面**偏宽（保守）**；框架入口 / 反射 / 跨语言引用不在静态
  调用图内，**无边 ≠ 无人用**。故 impact 报告是 **advisory 基准**（apply §4 的结构
  证据之一），收口对账以实际 diff 为准；对账门属批 2，本批不判罚。
- **产物**：`impact_report.py --root . --task <需求ID>` 落
  `.trellis/tasks/<ID>/impact.json + impact.md`（`--out` 可指定任意目录）；三态同
  `gen_e2e_scripts` 先例：前置未声明 / 后端不可用 ⇒ exit 3 `not_ready`；输入为空 ⇒
  exit 1；成功 ⇒ 字节可复现的双文件。
