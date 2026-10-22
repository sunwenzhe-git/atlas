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

### `graph`（可选：代码图谱后端）

**可选增强**（2026-10-05 图谱批 1）：声明后，**两个消费者**改走代码图谱——`routes` 适配器的
**文件枚举通道**（派生逻辑同一份，`§3.6`）与 `apply` 的影响面基准（`impact_report.py`）。
段缺失或 `graph: null` = 不用图谱（合法降级，各消费者显式 `not_ready` 或回退正则）。
接触面与纪律的唯一正文见 §3.6。

| 字段 | 必填 | 说明 |
|---|---|---|
| `backend` | 声明段时必填 | 图谱后端名，枚举：`cgc`（CodeGraphContext，MIT，PyPI 包 `codegraphcontext`，可执行名 `cgc`） |
| `pinned` | 否 | 期望的后端版本（语义版本形态）；与实装失配 ⇒ 消费者显式 WARN（不阻断） |

- 声明了但后端不可用 ⇒ **响亮降级**（适配器 stderr WARN + 输出 `backend_fallback`；报告器 exit 3 `not_ready`），绝不静默改道。
- 显式 `--backend graph` 而后端不可用 ⇒ 硬错（显式要求不得被静默改道）。

**生成 / 确认画像时探测并提议（2026-10-15 补；同日按实测二次收口）**：本段在出厂模板里是**注释态**，没人探测就永远不会生效——实测有用户照 README 装好了后端，而整个接入过程没有任何一步提过它，于是「装了的图谱一次没用上」。故**确认画像那一次**（`global-rules.md` §7 的画像门内）应探测后端可执行并在**可用时向用户提议**声明本段；**不可用则不提议**（别让人为一段用不上的配置买单）。声明与否由用户定；不声明 = 合法降级，不阻断任何环。

**提议按栈门控（2026-10-15 实测驱动）**：**仅当 `apps[]` 中存在 `kind ∈ {backend, fullstack}` 的 app 时才探测并提议**；全部 app 为 `frontend` / `mobile` 时**不提议**（不探测、不提、不推销）。实测（cgc 0.6.13，前端形态夹具）：**JSX 组件引用不产生任何调用边**——精确 `CALLS` 边与启发式调用边都不覆盖 `element: <Comp />` 形态。这条判据分两层：**消费层**是本层不变式——`_graph.callers` 的 Cypher 只认 `CALLS` 边（`adapters/_graph.py`），后端哪天加了渲染边也读不到，后端栈不受影响；**后端层**（0.6.13 边型普查）随版本可能变化，失配由 `pinned` 探测 WARN 感知（`§3.6`）。逻辑调用链（hook → fetch 等）不在失真内，照常有效。

**提议口径要如实（2026-10-15 按实测更新）**：本段当前换来的是——

1. **`routes` 的文件枚举通道**：与 regex 通道**产出恒等**（同一份解析逻辑、同一份剪枝，`tests/test_routes_graph_backend.py` 钉「两通道全等」），只是文件清单来源不同；
2. **`apply` 的影响面基准**（advisory）：对**逻辑调用**有效；对**组件叶面系统性失真**——JSX 渲染引用不进调用边，「改一个组件 ⇒ 报告『无依赖方』」（`impact_report.py` 输出常驻提示，`§3.6`）。

且它**不是**「跨文件逆向分析」——域聚类、解析逻辑都不走图谱（`§3.6`）。把能力说大，用户会为一个不存在的功能装依赖。**同时要交代两条代价**：

- 项目根多一个未跟踪运行时目录 `.adapter-out/` ⇒ 接线脚本在项目已有 `.gitignore` 时**自动追加**一行 `.adapter-out/`（无 `.gitignore` 的项目由接线报告显式提示手动添加；对所有项目成立，`§3.6`）；
- 后端索引存放在 cgc 的**全局共享图库**（不随项目迁移；atlas 侧一切查询按项目根前缀过滤，不跨仓读出）。

### `e2e`（含已退役的 `prototype`）

| 段 | 字段 | 说明 |
|---|---|---|
| `prototype` | （已退役，E1） | **atlas 不再消费任何字段**；存量项目可保留（历史）或删除。原型环移除见 `3508 §92` |
| `e2e` | `runner`（`node-playwright` 单轨；`python-playwright` 已退役，B201-4/3507 BO）/ `cases_dir` / `index` / `scripts_dir` / `app_base_url`（**可含 query = 宿主注入型前提**，如 tenant；生成物负责带到每一跳，见 `rings/e2e/reference.md` §5.5；`ATLAS_BASE_URL` 只覆盖 host）/ `node_modules`（node 运行器的依赖目录：据此定位可执行文件，**并校验 `@playwright/test` 从 `e2e.scripts_dir` 出发可解析**——判据 = 依赖可导入性，不按路径存在；ESM 项目下 `NODE_PATH` 无效、不再作判据（issue #24 / `DESIGN.md` D101））/ `reset`（可选：真跑前执行的靶场重置 shell 命令串，项目相对 cwd；null = 无重置，合法降级） | 用例组织与**单段执行**（真实应用；E1 起原型靶场已退役） |
| `e2e` | `app_login`（子段：`mode` / `endpoint` / `username_field` / `password_field` / `token_key` / `storage_key` / `body_format`） | **应用靶场登录形态与取证值**（2026-09-28 补，`3509 §B101`；2026-10-16 语义改判：段是**形态声明 + 取证值**两件事，`RFC-20261015-02`）：`real` 下为 OAuth2 表单或 JSON 端点（相对 base_url 的路径）、表单字段名、响应令牌键（支持点号路径解构）、前端读取的 localStorage 键、提交体格式 `body_format`（`form` \| `json`，缺省 `form`）。生成时烘进运行器配置；**凭据仍只来自运行期环境变量**（`rings/e2e/reference.md` §7.1）。**段缺失 = 未声明**（2026-10-16 语义改判，`RFC-20261015-02` / issue #11 —— 不再是「合法降级」；第一阶段 `validate_stack_profile` WARN 指名：`app_base_url` 已声明而本段未声明；**升档 = 下一次真跑准备日**推生成器 `not_ready`（退出码 3 + 机读键 `not_ready: "app_login"`，与 `app_base_url` 同一通道；升档与现场咬合记录见 `shared/gates.md` 2.2「E2E 真跑」行）；空段（`app_login:` 后无值）= 未声明同判）。段存在但字段不齐 ⇒ 生成报错。`mode`（2026-10-12 补，`rings/e2e/reference.md` §5.8；2026-10-16 增 `none`）= `real`（**缺省** = 上述真实登录语义）\| `fabricated`（**纯前端桩项目**：不发真实登录请求，setup 直写固定假令牌进 storageState；必填字段收窄为 `storage_key`）\| **`none`（靶场无访问门：显式声明，不生成登录预置设施、不打警告——声明形态，不是降级；段内取证字段一律不得残留（含 `storage_key`）⇒ 残留 = 校验器 FAIL + 生成器报错——与 `fabricated` 的「收窄」相反是「全弃」）**； **三态之外不设第四态**（2026-10-17 D103）：靶场有门但三态都装不下（图形验证码 / cookie 会话 / 响应体无令牌）⇒ 保持未声明 + 走 `rings/e2e/reference.md` §7.1「人工会话取出」（描述路径、非机器门、明示不可复现）。 |
| `e2e` | `review`（子段：`mode` / `model`） | 独立审查执行器（语义见 `rings/e2e/reference.md` §12）；`mode`: `gate`（**缺省** = 严格审查门）\| `auto-baseline`（v0.1.0-beta.14：无报告时自动生成基线，免阻断）\| `off`（免审） |
| `e2e` | `session_preset`（子段：`keys`） | **会话预设键白名单**（2026-10-16 补，`rings/e2e/reference.md` §5.5；issue #13）：本靶场允许用例预设的**宿主注入型会话类**键（如身份 / 租户 / 管控 / 灰度类标记）。它是**项目级声明**——用例 `会话:` 行声明的键必须 ⊆ 本表，否则文本期 FAIL + 生成器中止（双保险）；以此守住 §5.7「不得用调试 / 演示参数直达某个数据态」的禁令不破：**会话 / 身份 / 权限类注入键**是合法前提（与 `app_login` 预置会话同类），**数据实体状态**仍禁。取值**不进本段**：由用例 `会话:` 行声明，运行期环境变量优先覆盖（`ATLAS_SESSION_<规范化键>`），两者皆空 ⇒ 报错中止（不静默跑成默认态 = 假绿）。**段缺失 / `keys` 为空 = 该靶场不允许任何会话预设**（用例出现 `会话:` 行即 FAIL + 中止）；`keys` 每项须匹配 `^[A-Za-z][A-Za-z0-9_.\-]*$`；键空间外 ⇒ FAIL |
| `e2e` | `query_preset`（子段：`keys` / `hash_keys`） | **宿主注入型 URL 参数白名单**（2026-10-18 补，`rings/e2e/reference.md` §5.5；`DESIGN.md` D109）：本靶场允许用例以**载入地址的常规查询串**（`window.location.search`）注入的**前提类**键（身份 / 租户 / 管控 / 灰度 / 预览壳类）。它是**项目级声明**——用例 `参数:` 行声明的键、以及 `goto` 查询串里出现的键必须 ⊆ 本表，否则文本期 FAIL + 生成器中止（双保险）；以此守住 §5.7「不得用调试 / 演示参数直达某个数据态」：**前提类注入键**合法，**数据实体状态**仍须真实界面动作。它是 `session_preset` 的**姊妹段**（同一「前提面」族，不同载体）。**取值不进本段**：值内联在 `step` 的 `goto` 查询串里；与 `e2e.app_base_url` 的 query **求并集**、**同键 ⇒ 用例胜**。**段缺失 / 对应键表为空 = 该靶场不允许该载体的 URL 参数前提**（用例出现 `参数:` / `hash参数:` 行即 FAIL + 中止）；`keys` / `hash_keys` 每项须匹配 `^[A-Za-z][A-Za-z0-9_.\-]*$`；键空间外 ⇒ FAIL。`hash_keys`（2026-10-22，D132）= **`#` 之后 hash 查询串**的白名单（HashRouter 场景，`window.location.hash` 的查询段），与 `keys` 分载体：`hash参数:` 声明的键、以及 `goto` hash 查询里的键必须 ⊆ 本表 |
| `e2e` | `seed`（子段：`hook` / `mode`） | **数据播种通道**（2026-09-28 补，`3509 §98 ⑪`）：`hook` = 项目自定实现的脚本路径（相对项目根），接口语义 = 「输入实体清单 ⇒ 保证存在」（幂等 upsert），生成时烘进 `_SEED`。`mode`（2026-10-07 补，B197-1）= **声明 / 发射解耦开关**：`enforce`（**缺省** = 现行为）= 每用例运行期播种；`declare` = `seed:` 行只参与静态对账（`rings/e2e/reference.md` §5.7 的 seed×models 门）、**不发射**运行期播种——累加链项目（运行期重播会撤销链上破坏性动作）的合法形态；取值白名单外 ⇒ 校验器 FAIL + 生成器报错。**段缺失 = 合法降级**（mode 按 enforce + hook 未声明 ⇒ 生成期 WARN + 运行期明确警告）。用例侧 `seed:` 块见 `rings/e2e/reference.md` §5.7 |
| `e2e` | `mock`（子段：`mode` / `api_prefix` / `fixtures_dir`） | **网络边界打桩通道**（2026-10-12 补，`rings/e2e/reference.md` §5.8）：`mode` = `off`（**缺省** = 现行为：分片出现 `mock:` 行 ⇒ 校验器 FAIL + 生成器中止，防全后端项目静默屏蔽真 API 回归）\| `on`（放行——纯前端 / 无后端项目的确定性 UI 验收）\| `auto`（混合穿透——未命中桩表自动穿透访问真实后端）。`on` 时 `api_prefix` 必填（以 `/` 开头）：桩路径锚定前缀 + 运行期拦截范围；`auto` 时缺省兜底为 `/`；`fixtures_dir` 可选（自定义打桩数据目录）。白名单外取值 ⇒ 校验器 FAIL + 生成器报错。用例侧 `mock:` 块见 `rings/e2e/reference.md` §5.8 |

### `backend_test`（后端测试调度与 AC 对账）

纯后端与全栈后端项目的自动化测试调度与验收标准对账契约（2026-10-12 补，`3507 BT` / B209-1）。**可选能力**：段缺失 = 合法降级（项目自行执行原生测试；`validate_ac_alignment` 按降级通过）。

| 字段 | 必填 | 说明 |
|---|---|---|
| `command` | 否 | 测试执行命令（收口核验命令保管；如 `pytest backend/tests`） |
| `test_dir` | 否 | 测试代码根目录（相对路径，用于 AST 提取 AC 挂载点，缺省 `backend/tests`） |
| `framework` | 否 | 测试提取器框架，枚举：`pytest`（v1 仅支持 pytest） |
| `mode` | 否 | AC 对账门禁模式，枚举：`advisory`（**缺省** = 报告覆盖缺口与对账清单，不阻断）\| `enforce`（对账缺口硬阻断） |
| `ac_marker` | 否 | 测试用例挂载 AC 的语法形态，如 `pytest_mark`（`@pytest.mark.ac("AC-xxx")`） |

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
- **产物落点约定**：`--out` 写 `<项目根>/.adapter-out/<category>[/<app>].json`（全局类别写 `routes.json`，按 app 类别写 `models/<app>.json`）。该目录是 **atlas 全部中间产物的单一位点**（适配器产物 / 漂移标记 `_drift.json` / 图谱新鲜度标记 `_graph_index.json` **同址**；2026-10-15 统一，issue #8）。它是**中间产物、非真相源**，不进注入、可覆盖重生成；**该目录必须被 git 忽略**——接线脚本在项目已有 `.gitignore` 时自动追加一行 `.adapter-out/`（2026-10-15 起，issue #8 之后对所有项目成立，不只图谱用户）；无 `.gitignore` 的项目由接线报告显式提示手动添加。

### 3.2 输出 JSON

```json
{
  "category": "routes",
  "items": [ { "...": "见下表的类别字段" } ],
  "source_files": ["相对路径", "..."],
  "adapter_version": "0.1.0",
  "route_coverage": { "...": "仅 routes：识别与挂载合成的覆盖计数，见下" }
}
```

**每类 `items[]` 字段**（`?` = 可空）。适配器只出**机械可抽**字段；用途 / 交互 / 语义等由 agent 补（见 `rings/structure/reference.md` §4）：

| category | `items[]` 字段 | 备注 |
|---|---|---|
| `routes` | `path` · `name?` · `component?` · `auth?` · `params?` · `source_file` · `status?` | `status` 仅 landing（`current/`）需要 |
| `api` | `method` · `path` · `summary?` · `source_module` · `source_file` | 有机器可读描述时**不产 `items`**，改产 `{category:"api", spec_entry:"…", source_files:[…]}`（见 §3.5） |
| `models` | 每字段一行：`table` · `field` · `type` · `constraints?` · `default?` · `relation?` · `enum?` · `source_file`；另加顶层 `enums[]`：`{table, field, values:[{value, meaning}]}` | 对应 `data-models.md` 表；`source_file` 供「表→域」归属（C7） |
| `tests` | `type`(unit/integration/e2e/other) · `location` · `run_command?` · `status?` | `status` 属运行事实，适配器留空由 agent 补 |

- **`route_coverage`（仅 `routes`；2026-10-16 补，issue #15，D83/D84）**：识别与挂载合成的**覆盖计数**，形如 `{declared, site_level, mounted, skipped_items, skipped:[{file, reason, items}]}`。语义 = 「声明路由表的文件数 → 站点级 / 已挂载 / 未解析（逐文件原因）」。
  - **为何要它**：候选闸与挂载前缀都会丢弃条目（命名不匹配、前缀求不出），而丢弃**必须可见**——不完整的事实表冒充「structure ⇔ 代码」配门比诚实缺口更糟（`global-rules.md` §15 同族）。同理须在 stderr 逐文件列出未解析原因。
  - **未解析的条目一律不产出**（宁缺不产假路径）：回退成模块相对路径会与其它模块的同名路径撞行键，被 `dedup_by_row_key` 折叠成**假事实**，比缺口更糟。

- **`tests` 的 `run_command` 由测试文件的后缀族推定，配置只在同族内细化命令**（2026-10-15 补，issue #4）：`.py` ⇒ Python 族（有 pytest 配置 ⇒ `python3 -m pytest`）；`.ts/.js/.tsx/.jsx` ⇒ Node 族（playwright / vitest / jest / `package.json scripts.test` 依次取命令）。**配置探测扫整项目**，不随 `--app` 收窄——配置是项目级的、落在项目根；只有测试文件盘点按 app 收窄（否则逐 app 调用拿不到根级配置，命令被静默降级成 `null`）。
- **后缀族与配置族冲突时不产矛盾条目**（2026-10-15 补）：item 仍出（测试文件存在是事实），`run_command` 置 `null`（**不作主张**），并在 stderr 报 `WARN[tests]` 点名该文件与冲突的配置，**退出码恒 0**——非零会被 `refresh_structure --chain` 当成适配器失败而中止整条链。反例即 issue #4：根有仅声明 atlas `ac` marker 的 `pytest.ini`，全仓唯一测试文件是 `.test.ts`，旧实现给出 `python3 -m pytest` 这条**错误事实**，且「非空且形态合法」骗过接线前置（`§B118` 只识别「产出为空」）。

- `items` 与渲染出的 markdown 表**逐行对应**；适配器不产表格外的语义列。
- **`items` 的粒度 = 渲染行键**（2026-10-15 补）：适配器按**代码里的事实**出行、**不做行键去重**
  （同一端点被两个域各调一次是两条合法事实，各进各的域文件）；同一事实文件内的**重复行键**
  由 `refresh_structure.py` 折叠（D69，行键级合并以「行键唯一」为前提）。
- **`api` 的 `method` 取值**（2026-10-15 补）：HTTP 形态记动词（`GET`/`POST`/…）；
  **RPC / action 形态**（调用点看不出传输动词、也没有 URL）记 **`RPC`**，`path` 记**方法名本身**
  ——**不合成 URL、不猜动词**（合成即编事实；`@action` 这类合成路径的形态是**框架事实**，不是通则）。
- **`routes` 的 `auth`**（2026-10-15 记实）：只记**可静态取证的认证门**；授权门（如
  `needRight: isSuperAdmin`）**不是** `auth`，交 agent 在「关键交互」语义列补。注意渲染表当前
  **没有 `auth` 列**——该字段只对读 `.adapter-out/routes.json` 的 agent 可见。
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

**判定顺序（2026-10-15 补，用户实测驱动）——先问人，再问代码**：

1. **先问用户**：后端有没有**机器可读接口描述**（OpenAPI / Swagger / GraphQL SDL / proto…），地址在哪？
   这一问不可省——描述**常常不在本仓库**：网关、独立文档站、运行时端点都算。实测有接入项目的
   `categories.D` 记着「后端经网关暴露 RPC action；网关文档地址不随仓库分发」：**仓内探测不到，
   但描述确实存在**。**判定权在用户，不在适配器探测结果。**
   - **有**（地址可在仓外）⇒ **指针形态**：`*/apis.md` 只记**真相源入口 + 访问方式**，**不逐条复制
     端点**；`_meta.json.categories.D` 记形态 + 地址取证；**该类别不接源码枚举适配器**
     （`adapters.api` 置 `null`，整类交给 agent 记指针）——清单与指针同时存在即混写（§7 判 FAIL）。
   - **无**（用户确认）⇒ 落源码枚举，见下。
   - **未答** ⇒ **不得默认按「无」处理**：按「有描述但地址未取证」记进 `categories.D`，并在结构环
     §9 报告里点名（同域清单确认门的口径）。
2. **仓库内探测不到描述文件 ≠ 无描述**：那只是「仓内没有」。旧口径让「适配器探测结果」直接决定形态，
   会把「有网关描述的前端项目」误判成「无描述」⇒ 去枚举调用点，产出一张本不该存在的清单。

**有描述时用什么适配器**：声明一个读取该描述的适配器——**包内暂无出厂实现**（需仓内文件形态时，
项目可自带，见 §3.3 第 3 条）；**仓外的地址形态无需适配器**，指针由 agent 记。

- **转指针形态必须出声**（2026-10-15 补）：探测到描述而**丢弃**源码抽到的端点时，适配器须在
  stderr 报出丢弃条数——静默切换形态会让用户只看到「接口清单是空的」而无从查因
  （同族：`gates.md` 的「看起来在跑」）。
- **纯前端项目也是合法形态**：**仅当用户确认「无描述」**时，前端调用点（如点分方法名的 RPC 调用）
  才是 D 类唯一的机械可抽源；D42 的「不收前端 client 调用」以「存在后端 / 描述侧真相源」为前提
  （见 `DESIGN.md` D42 的窄化声明）。

### 3.6 图谱接触面（`adapters/_graph.py`；2026-10-05 图谱批 1 定形）

**全线只有 `_graph.py` 允许接触图谱后端**（防腐层）：后端可换、确定性契约单点实现、
降级语义统一定义。任何脚本不得自行拼后端 CLI 或读图数据库。

- **调用**：`import _graph`（同包 `adapters/` 内）；入口 `detect / ensure_index / query / callers / symbols_in_files / file_paths / load_graph_config`。
- **用前现刷（唯一更新机制）**：每个消费者查询前调 `ensure_index()`——新鲜度键 =
  git HEAD + 脏文件集的 sha1，键一致直接返回，不一致全量重建并写新鲜度标记
  （`.adapter-out/_graph_index.json`）。没有独立更新节拍、没有 watch 守护进程；
  **过期状态在消费时构造性不存在**。非 git 工作树 ⇒ 指纹算不出来 ⇒ 显式 WARN +
  每次全量重建（不硬崩，也不拿无法验证新鲜度的索引装新鲜）。
- **落点 = 项目根 `.adapter-out/`**，与适配器产物、漂移标记**同址**（2026-10-15 统一，issue #8）。
  该目录是 **atlas 全部中间产物的单一位点**；设计档案 `docs/design/structure-ring.md` 的目录树
  原本就是这么写的，实现一度漂成两处（本层在项目根、结构环产物在 `.trellis/spec/structure/` 下）
  ⇒ 同名两处，现场出现「`git status` 里有 `.adapter-out/`，而「结构漂移」门说『无 .adapter-out
  产物目录』」的自相矛盾——排查者会先怀疑门坏，而不是去比对基准。统一后该矛盾**构造性消失**，
  且漂移门的 SKIP 文案带实际路径。
  代价 = 项目根多一个未跟踪目录 ⇒ **`.adapter-out/` 必须被 git 忽略**——接线脚本在项目
  已有 `.gitignore` 时自动追加一行（无 `.gitignore` 的项目在接线报告里显式提示手动添加）；
  **不启用图谱的项目也会因结构环产物而需要它**。
- **工作树纪律**：**后端自己的索引库不得落进项目工作树**——存储位置是后端的事，一旦它把库
  文件写在 cwd，新鲜度键就会把「写索引 ⇒ 键变化 ⇒ 再索引」自激成永不稳定的全量重建。
- **枚举范围纪律（2026-10-15 收口）**：图谱通道给出的文件清单**必须过与 regex 通道同一份
  剪枝**（`IGNORE_DIRS` + `.venv*` + 后缀池）后才准用。理由：regex 通道走 `iter_files` 天然剪
  依赖 / 构建目录，而 `cgc index` **不带 exclude 旗标**——后端若不理 gitignore，
  `node_modules`/`dist` 里的源文件会整批进枚举池并产出**假事实**。两通道枚举范围不等价，
  「两通道全等」这条判据本身就失效（`tests/test_routes_graph_backend.py` 第 5 侧）。
- **并发**：`ensure_index` 无互锁，**单进程假设**；两个消费者并行会各做一次全量重建。
- **确定性**：所有查询带 `ORDER BY`、输出键序固定，同代码态重跑字节一致——上层
  可 diff、可对账的前提；对账面（批 2 impact 门）以此为先决条件。
- **影响面口径（`impact_report.py` + `_graph.callers`）**：调用方查询是 **name 级匹配**
  ——同名多定义并入，影响面**偏宽（保守）**；框架入口 / 反射 / 跨语言引用、**以及 JSX 组件
  的渲染引用**（2026-10-15 实测：组件被使用不产生调用边——消费层只认 `CALLS` 边）不在静态
  调用图内，**无边 ≠ 无人用**。故 impact 报告是 **advisory 基准**（apply §4 的结构
  证据之一），收口对账以实际 diff 为准；对账门属批 2，本批不判罚。
- **产物**：`impact_report.py --root . --task <需求ID>` 落
  `.trellis/tasks/<ID>/impact.json + impact.md`（`--out` 可指定任意目录）；三态同
  `gen_e2e_scripts` 先例：前置未声明 / 后端不可用 ⇒ exit 3 `not_ready`；输入为空 ⇒
  exit 1；成功 ⇒ 字节可复现的双文件。
