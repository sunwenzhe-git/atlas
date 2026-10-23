# atlas — 项目级工作流设计

> 状态：设计定稿 + 决策记录（**历史与依据**）。**操作契约的唯一权威** = `.atlas/shared/` + `.atlas/rings/*/reference.md` + `.atlas/apply/reference.md` + `.atlas/skills/*/SKILL.md`；本文与它们冲突时以操作契约为准，设计依据见 `3507` 决策记录。
> **现行口径**：atlas = **三环（structure / prd / e2e）+ apply**；testid **应然 = 用例分片**、**实然 = 前端源码**；E2E **单段**执行（`e2e.app_base_url`）。
> 依附上游：Trellis（已初始化于业务仓库 `.trellis/`）。版本对齐见 `RUNBOOK.md` §0（**不在此处写死版本号**）。

---

## 1. 背景与目标

### 1.1 为什么要有 atlas

项目级资产（结构事实 / PRD / E2E）与需求级执行长期被捏在一起：同一件事在多处文档里重复表达、随需求漂移；E2E 用例与真实 UI 之间没有可机器校验的锚点，导致"用例写了但跑不起来、跑了也不知道对不对"。

atlas 的目标：**把项目级与需求级彻底分成两层，各自单一真相源，用机器可校验的契约把两者绑死。**

### 1.2 产物归属

- atlas 的产物全部活在**业务仓库内部**：`.atlas/`（包）、`product/`（PRD / E2E）、`.trellis/spec/structure/`（结构事实）——只认这三个相对位置，仓库叫什么名与 atlas 无关。
- 业务仓库自带完整链路（契约 + 模板 + 校验器 + skill 瘦桩），可独立运行，不依赖仓库外的任何文档。

### 1.3 硬约束

1. **跨项目通用**。atlas 会被分发到所有项目，核心流程、模板、校验脚本**不得包含任何具体框架知识**。
2. **不改 Trellis 的硬编码点**。Trellis 的开箱机制（hook、状态机、skill 发现）保持原样，atlas 只在官方支持的改动面上做文章。
3. **一切可校验**。凡是"两边必须一致"的关系，都要有脚本能判定，不靠人记。

---

## 2. 设计原则

| 原则 | 含义 |
|---|---|
| 两层正交 | 项目级资产与需求级任务互不嵌套；需求"流过"项目级资产，而不是改变它的层级 |
| 单一真相源 | 每类信息只有一个权威位置；其余都是派生视图或引用 |
| 机器可校验 | 双向引用、ID 唯一性、链接可达性由脚本判定，不靠约定 |
| 前置而非后补 | 应然（PRD / E2E）在实现之前更新完毕 |
| 增量而非重写 | 资产是 living 的；需求增量合并，不整体重建 |
| 适配器隔离 | 具体框架知识全部下沉到适配器与 `stack-profile.yaml`，核心不认框架 |
| 不造第二份文档 | 需求卡复用 Trellis 原生 `prd.md`；不设 inbox |

---

## 3. 两层模型（产物分层，不是入口模型）

> 「两层」说的是**产物怎么分层**（事实基线 + 应然资产 在上、需求级增量在下），**不是入口公理**——需求级只是最常见的主路径，atlas 另有六类非需求入口（见下方入口矩阵；`3509 §B123`，用户 2026-09-29 指出）。

```
┌─────────────────────────── 项目级（atlas，living 资产） ───────────────────────────┐
│                                                                                   │
│   structure ──> prd ──> e2e                                                       │
│   (实然事实)     (应然叙事      (应然验收用例 +                                    │
│    legacy/current  + 规格条目)    testid 应然清单 + 机器可读索引)                    │
│        ▲                ▲              ▲                                         │
│        └────────────────┴──────────────┘                                         │
│                         需求在此增量合并（前置）                                    │
└───────────────────────────────────────────────────────────────────────────────────┘
                                    ▲
                                    │ atlas apply <需求ID>
                                    │
┌─────────────────────────── 需求级（Trellis 原生） ─────────────────────────────────┐
│  Plan(1.x) ──> Execute ──> Finish                                                  │
│  task create / prd.md / implement / check / update-spec / finish-work              │
└───────────────────────────────────────────────────────────────────────────────────┘
```

- **项目级**回答"这个产品是什么、长什么样、怎么算做对了"。
- **需求级**回答"这一次改什么、怎么改、改完怎么验收"。
- 两层通过 `atlas apply` 衔接（需求路径如上图单向：应然更新先于实现；`apply` 另有非需求模式，见下方入口矩阵）。
- **结构环与 PRD 环相互独立**：`prd` 以 `structure` 产物为输入，但**不由 `structure` 自动触发**（PRD 会持续独立更新；见 D34）。

### 3.0 入口矩阵（需求 = 主路径，非唯一入口）

契约里的非需求入口**早已存在**（`apply/reference.md` §1 四模式 + §3.1 三问全否 + §3.2 第 4 形态），此处只做汇总表述：

| 入口 | 载体 |
|---|---|
| 需求级（主路径） | `apply <需求ID>`（prd → e2e）；三问全否 ⇒ 只走 structure + Trellis 纯加法 |
| 开户 / 接入 | `apply all`（全新项目）/ `apply adopt`（老项目首次接 atlas） |
| 治理 / 补账 | 台账条目处置、用例基线清零、审查 finding 清理（独立写面） |
| 上游回流 | `apply backfill`（下游发现的上游缺口，攒批 ≤ 10 条/批） |
| 无需求卡修订 | `apply` §3.2 第 4 形态（应然资产修订，不经需求卡） |
| 事实刷新 | `after_finish` hook 自动跑 `refresh_structure.py`（不经人） |
| 纪元 / 退役 | 生命周期三件套（先例：E1 原型环移除 + 迁移与失义清单） |

### 3.1 职责边界：atlas = 约束层

> 决策 **D72**（2026-09-22）。对标外部「Harness 五层」（约束 / 对抗验证 / 证据 / 状态写入 / 边界对齐）后的定界。

atlas **只收口约束层**——项目级应然资产、唯一事实源、三类入口（人类 / Agent / 机器可读索引）。其余四层按**所属阶段**分工，不并入 atlas：

| Harness 层 | 归属 | atlas 的作为 |
|---|---|---|
| 约束层（规则 + 索引） | **atlas** | 三环 + `apply` 的本职。五类约束中：任务目标 / 非目标 = PRD（`templates/prd/global.md` §六）；验收条件 = AC + 追溯链；事实源优先级沿用 **D45** 的修订版（E1：AC ＞ 用例分片应然清单 ＞ structure 参考基线）+ `global-rules.md §8`（取证 ≠ 应然）；禁止动作 = 各环已有成文禁令（`global-rules.md §5` 占位符禁令、E2E 反作弊 D53） |
| 对抗验证（多角色分审 / 验收裁决） | 兼有 | atlas 收口**对自身产物**的审查（当前 = `atlas prd review`，`rings/prd/reference.md §8`）；**对实现代码**的审查归 Trellis。E2E 是否补独立审查 → 实跑后按证据定 |
| 证据层（可视化 / 对账 / 复现） | 实现阶段归 Trellis | atlas 只保留确定性校验器（**数量与取证等级见 `shared/gates.md`**，不在本文件复述）与 E2E 状态机（`red → green`；`prototype-pass` = E0 历史终态）。HTML 可视化验证报告、**测试覆盖状态机跳转检测**、用例级复现命令 / 回归说明 → 延后（依赖 `3509 §B4`，`§C9`） |
| 状态写入（目标复述 / 长任务可接续） | 实现阶段归 Trellis | apply 只记影响面清单与执行记录（`.trellis/tasks/<需求ID>/atlas-apply.md`）；agent 目标复述 / 长任务阶段持久化不属 atlas |
| 边界对齐（风险分层门禁 / 回滚） | 兼有 | atlas 侧 = 用户确认门（`global-rules.md §7`）+ E2E 完成门（硬门 + `blocked` 显式例外）+ apply 覆盖门（D62）；CI Gate 分级与回滚机制兜底 → 延后（依赖 `3509 §B4`，`§C10`） |

**一句话**：atlas 管「应然是什么、以什么为准、怎么算做对了」；「代码写得对不对、能不能过、错了怎么退」属需求级实现层（Trellis）。

---

## 4. 目录布局

```
<业务仓库>/
├── .trellis/                        # Trellis 原生（需求级）
│   ├── workflow.md                  # 流程 SSOT —— atlas 在此插一步（见 §7）
│   ├── config.yaml
│   ├── spec/structure/              # ★ 结构事实（逆向产物；atlas 结构环写此目录）
│   │   ├── _meta.json               #   机器：product/baseline/apps[]/domains[]/categories
│   │   ├── tour.md                  #   L1：paths ['**']
│   │   ├── domains/<domain>.md      #   L2：paths = 域 globs
│   │   ├── global/                  #   directory-map / routes
│   │   └── {current,legacy}/<domain>/{apis,data-models}.md
│   └── tasks/<NN-slug>/             # 需求级：prd.md = 需求卡；task id = 需求 ID
├── .atlas/                          # atlas 包（install.sh 装配；包产物）
│   ├── shared/                      #   共享契约（三环共同遵守）
│   ├── rings/                       #   各环执行契约 reference.md
│   ├── apply/                       #   跨环增量契约
│   ├── scripts/                     #   refresh_structure.py（事实区刷新；after_finish hook）+ backflow.py（回灌助手）
│   ├── _support/                    #   共享内核（模块加载 / profile / 用例块单源解析）
│   └── templates/  adapters/  validators/  patches/
├── README.md                        # A（技术栈 / 启动，可选）+ H（测试 / 运行，条件）
├── .impeccable/config.json          # impeccable detect 配置（可选外部工具；`detector.ignoreRules` 与 product/design.md 的 detect 豁免双向对账）
├── product/                         # atlas 项目级文档（非 Trellis，靠 skill 读写）
│   ├── stack-profile.yaml           # 技术栈画像：声明用哪些适配器（见 §9）
│   ├── design.md                    # 视觉设计档案（frontend-design skill 写；atlas 只读：走查门对照 + 豁免对账，见 §10）
│   ├── prd/                         # 项目级 PRD：全局 + 域级
│   │   ├── README.md                #   追溯总表 + 索引
│   │   ├── prd.md                   #   全局（唯一）
│   │   └── <domain>-prd.md          #   域级（每域一份）
│   └── e2e/
│       ├── e2e-index.md             # 总索引（唯一入口，机器可校验）
│       └── cases/<page>.md          # 页面分片（中文用例详情）
├── <app1>/  <app2>/                 # 实际代码
└── .agents/skills/atlas-*/          # atlas skill 瘦桩（由 install.sh 装配；指回 .atlas/）
```

**分工理由**：结构事实落 **`.trellis/spec/structure/`**——它既是**项目级事实**（PRD / E2E 按需 Read），又能被 Trellis **原生注入**消费；事实区由刷新脚本确定性维护，语义区由 AI / `trellis-update-spec` 维护（见 §5.1、§7）。

---

## 5. 项目级资产规格

### 5.1 structure（结构基线）

**6 类内容（4 入 `.trellis/spec/structure/`：B–E，D 条件；A / H 落项目根 `README.md`）**：

| # | 类别 | 性质 |
|---|---|---|
| A（可选） | 技术栈 + 启动方式（端口、依赖、启动/停止、已知坑）；落点 = **项目根 `README.md`** | 约定 |
| B | 目录与模块地图（每模块一句话职责） | 事实 + 语义 |
| C | 路由与页面清单（路径、用途、关键交互、实现状态） | 事实 |
| D（条件） | 接口清单（方法、路径、请求/响应要点、来源模块）；有机器可读描述时只记真相源入口 | 事实 |
| E | 数据模型清单（表/字段/关系/枚举） | 事实 |
| H（条件） | 测试现状与运行方式；落点 = **项目根 `README.md`**（README 已有则不动） | 事实 |

> G（testid / selector 约定）归 **E2E 环**；I（编码规范）不由 atlas 收口——两者均移出 structure（决策 D35）。
> F（设计 token）**已退役删除**（2026-09-30 用户拍板「直接删」，`3508 §156`）：类别清单 / 模板 / 校验器判据 / 适配器键与产物文件全删；实现期视觉参考 = 前端样式表本身（`rings/structure/reference.md` §6.2）。

**域模型（本环负责提议）**：本环按路由/页面簇、模块簇、表/模型命名簇、接口路径前缀**聚类出候选域**，写入 `.trellis/spec/structure/_meta.json.domains`（含域 → globs；人读视图在 `tour.md` 域速查表）；PRD 诊断阶段读它并**定稿回写**。**域 id 是全链路键**（PRD / E2E / 注入 spec）。

**两层结构**：全局层 `global/`（`directory-map` / `routes`）+ 域级层 `{current,legacy}/<domain>/`（`apis` / `data-models`）。仅 `tour.md`（L1，`paths ['**']`）与 `domains/<d>.md`（L2，域 globs）带 `paths:` 被注入；其余事实文档无 `paths`、按需 Read。A（技术栈）与 H（测试）落项目根 `README.md`。

**二分法（跨项目关键）**：

- **约定/决策类**（A、G、I，以及 B/F 的语义部分）：项目**一开始就定**，由人/agent 撰写。绿地项目初始必填。
- **事实类**（B、C、D、E、F、H 中可枚举的部分）：**由适配器脚本从代码抽取**，可重复运行。绿地项目起步为空，随代码增长自动补齐。

**单一真相源**：结构事实 SSOT = `.trellis/spec/structure/`；域清单 = `_meta.json.domains`（机器）+ `tour.md`（人读）。A（技术栈+启动，可选）与 H（测试/运行，条件）真相源 = **项目根 `README.md`**，不入 spec。D（接口）为**条件类**：有机器可读描述时只记真相源入口，不逐条复制。编码规范与 testid 约定**不在本环产出**。

**legacy / current 双份**：

- `legacy/`：旧实现的事实（仅重构/存量项目需要）。
- `current/`：落地实现的事实；每个需求收口时增量回写。
- 同一功能在 `current/` 中标注实现状态，从而能表达"这个功能在新实现里还没做"。

### 5.2 prd（全局 + 域级两级）

**立场**：PRD 是**应然**，只写产品应该是什么样，**不写实现进度、不挂状态**。实然进度由 `.trellis/spec/structure/current/` 的实现状态与 E2E 用例 `status` 承载。

- `prd.md`（全局）：产品定位 / 目标用户与角色 / 核心场景 / 产品形态与入口 / 功能架构（域清单）/ **范围与处置** / 页面结构全景 / 非功能需求 / 术语表 / 风险与依赖 / 修订记录。
- `<domain>-prd.md`（域级，按**产品功能域**划分，非代码模块）：域概述 / 功能清单（带需求类别）/ 功能详细说明（描述·用户流程含全部异常路径·状态机·字段规范·六类文案·异常处理）/ 业务规则 Rule Set / 验收标准 / Assumptions & Defaults / 变更记录。

**编号**：功能 `FN-<DOMAIN>-NNN`；规则 `<DOMAIN>-R-NNN`；AC `AC-<DOMAIN>-NNN`。

**需求类别**（PMBOK 式）：功能性 / 非功能性 / **迁移性**（必带 owner + 结束条件）/ 约束。

**追溯链**：功能 → 规则 → AC → E2E 用例，**双向**强制（无 AC 的规则、无规则来源的 AC、无 AC 的功能、无域归属的页面都不合格）。E2E 用例的 `prd_ref` 回指 **AC ID**。

**AC 写法**：Given / When / Then + 样例类型（正向 / 反向 / 边界 / 异常），每个关键功能至少覆盖四类。

**流程**：四段式——诊断（四视角，每轮 ≤3 问，能查 structure 就不问）→ 定位对齐（概念版，固定 8 行）→ 范围冻结（需显式"确认"）→ 逐域落地 + 全局收口。

**质量机制**：零占位符（缺失只有三个出口：**建议默认值** / **Assumptions & Defaults** / **待决策登记表**——后者用于"产品方尚未决定"的结构性待定，每行须含 议题 / 现状取证 / 建议默认值 / 影响面 / 决策人）；**待决策表非空 ⇒ 只产出全局 PRD 与追溯总表，不产出域级 PRD**；**取证与应然必须分开表述**（现有实现里读到的是"参考基线"，不得写成结论）；需求四准则（完整 / 无歧义 / 一致 / 可测）；内容归属禁止重复（技术表结构唯一归 `.trellis/spec/structure/`）。

**治理工件**：`atlas prd review` 独立审查（只审不改，改后全量复审）；`.atlas/validators/validate_prd.py` 确定性校验（5 参数 → PASS/WARN/FAIL + waste test 全 YES）。

### 5.3 e2e（用例与索引）

**组织形态：页面分片 + 总索引。**

- `e2e/cases/<page>.md`：页面分片，含该页用例的中文步骤与预期详情。
- `e2e/e2e-index.md`：总索引，唯一入口，机器可校验的严格表格。
- 索引主表列（已定）：`用例ID | 页面 | 中文标题 | 类型 | 关联AC | 需求 | 状态 | 状态原因 | 分片`（末列带锚点链接）；另含**页面表**（`页面 / 路由 / 域 / 实现状态`，E1 起为 slug 与 URL 的唯一真相源）与反向视图 `页面 ↔ 用例`。字段划分、格式与词表见 canonical **`.atlas/rings/e2e/reference.md`**。
- **页面 slug = 分片文件名**（E1）：slug 规则正文归 E2E 环契约 §3.1；「页 ↔ 真实路由」映射的唯一真相源 = 索引**页面表**。

**三条硬规则（B 方案成立的前提，不可协商）**：

1. **总索引是唯一入口**，且机器可校验：ID 全站唯一、每个 ID 都有可达分片链接、分片里没有索引外的孤儿用例。
2. **每条用例只存在于一个分片**：归到它的**断言落点页**；跨页面流程在用例内记 `pages: [a, b, c]` 全链路，绝不复制。
3. **分片键只认页面**，不允许"临时归到别处"。

**跨页面用例的处理**：索引里额外生成「页面 ↔ 用例」双向视图，因此从链路上任何一页都能找到该用例。

**用例字段（索引 vs 分片，无同一字段两处出现）**：

- 索引主表：`ID · 页面 · 中文标题 · 类型 · 关联AC · 需求 · 执行目标 · 状态 · 状态原因 · 分片链接`。
- 分片 `atlas-case` 块：`id · intent · pages · precondition · step · expected · testid`。
- **状态类字段（`状态`/`状态原因`）只在索引**（执行结果回写处）；**`testid` 只在分片**（`validate_testids.py` 只读分片）。
- 完整语法、词表与 ID 规则（`E2E-<PAGE>-NNN`、每页独立、删除不复用）见 canonical `.atlas/rings/e2e/reference.md` §5。

**testid 规范**：

- 命名：`<页面slug>-<元素语义名>[-<变体>]`，如 `config-llm-add-btn`、`prompt-list-item`。页面段用路由 slug，元素段用语义名；**禁止样式/位置命名**。
- 覆盖：**必要元素**——所有可交互元素（按钮/输入/链接/列表项）+ E2E 需要断言的展示元素；其余不打。
- 约束：全站唯一、不复用、重命名必须同步 E2E 引用。
- **机器双向校验（E1）**：用例分片的 `testid:` **应然**集合 ⇔ 前端源码的**实然**集合，按页对账；已实现页多一个或少一个都报错，未实现页 SKIP / WARN（`实现状态` 见页面表）。

**脚本生成与执行**：

- 从用例分片**生成 Playwright 脚本**，与页面分片一一对应。
- 靠 `baseURL` 执行：地址唯一来源 = `e2e.app_base_url`（E1 单段），脚本不硬编码，由运行器原生配置承载。
- 执行结果**回写**索引里的 `状态`。
- **单段执行（E1）**：真实应用（真前端 + 真后端）一次跑；首跑红先按 `rings/e2e/reference.md` §5.4「首跑分类协议」三分类，**不分类不得批量回写状态**。

**状态机与完成门**：

```
red ──(真实应用单段通过)──> green
  └────────────> blocked / skipped（必须带 状态原因）
```

- **完成门 = 硬门 + 显式例外**：需求相关用例必须全部在真实应用上跑过且 `green` 才允许 Trellis 收口/提交；确实做不到的必须标 `blocked`，写明原因与后续去向，方可例外收口。
- 收口动作 = 对应用例全 `green` + `current/` 结构事实回写 + 索引与页面表已更新 + Trellis `finish` 归档。

### 5.4 apply（需求式跨环增量）

> canonical 执行契约：`.atlas/apply/reference.md`（本节为设计摘要，冲突时以契约与 `shared/*`、各环契约为准）。

- **定位**：atlas 唯一编排件，跨三环（E1）。四模式——`apply <需求ID>`（需求式跨环增量）、`apply adopt`（旧项目一次性开户）、`all`（按序跑三环全量）与 `backfill`（回流原语，`3509 §99`）。另有**不经本环的第 4 种形态** = 无需求卡的应然资产修订（见 §5.4 末与 `apply/reference.md` §3.2）。
- **参与环与顺序（D60）**：`apply <需求ID>` = `prd → e2e`（E1）；`structure` **不参与**（实然，实现后由 `after_finish` hook / `update-spec` 维护），唯一例外 = 本次 PRD 定稿改了域清单 ⇒ 末尾追一次 structure **re-key**。`all` = `structure → prd → e2e`。
- **参与判据（D51/E14）**：不以需求大小，按「是否改变应然 UI」——改 UI ⇒ PRD 文案 / 流程面落细 + 用例分片写明新元素的 testid **应然**（E1）；不改 UI ⇒ 复用既有 testid、只补用例；纯后端不可见 ⇒ 不产 E2E 用例；`prd` 恒参与。
- **影响面识别（D61）**：agent 语义判断 + 结构证据（`routes.md` / `_meta.json.domains` / 索引页面表），产出结构化清单（受影响域 / 页 / 变更性质 / 证据）；低置信、歧义、映射不到 ⇒ 一次性 ≤3 问，不猜；禁 regex 判语义。
- **增量边界与覆盖（D62）**：各环只落受影响增量（PRD 受影响域章节 + 追溯总表行 / E2E 受影响分片 + 索引行 + 页面表行）；单页单域增量常规，整页重建 / 删页 / 全量重生成 / 删既有产物 / 改 profile ⇒ 过确认门。
- **`all`（D63）**：顺序固定、幂等、断点续跑（失败 / 门控停在该环，下游不静默跳过；重跑按产物存在跳过）、门控态不判失败。
- **回写与报告（D65）**：执行记录 = `.trellis/tasks/<需求ID>/atlas-apply.md`；apply 在实现前跑，**不回写** E2E 执行状态（新用例置 `red`）；不改需求卡 `prd.md`。
- **挂载（D64）**：Trellis Plan `#### 1.6 项目级资产更新` `[required · once]` + `[workflow-state:planning]` 面包屑 enforcement；不新增 Trellis 状态；失败停在 planning。
- **patches（D66）**：`patches/workflow-plan-apply/`（锚点幂等、可重放）；前置把 `trellis` CLI 升到项目 `.trellis/.version`（否则 `trellis update` 可能冲掉补丁）。

---

## 6. atlas 命令面

**每环一个独立 skill**（各自 `description` 只含本环触发词），`apply` 是跨环编排 skill。skill 名即命令名：

| skill | 作用 | 模式 |
|---|---|---|
| `atlas-structure` | 生成 / 刷新结构基线（跑适配器抽取 + 补语义） | 全量或按类 |
| `atlas-prd` | 生成 / 重排 PRD 双层（含 `prd review`） | 全量 |
| `atlas-e2e` | 生成 / 刷新用例分片、总索引、Playwright 脚本、跑校验 | 全量或按页 |
| `atlas-apply` | **跨环编排**：`apply <需求ID>`（需求式增量）+ `apply adopt`（开户）+ `all`（按序跑三环） | 增量 / 全量 |
| `atlas-design-review` | 独立审查第 3 类实例：对设计主张做一次独立复核（`shared/independent-review.md`） | 按次 |

- 共享契约集中在 `.atlas/shared/`，各 skill 按路径引用，不复制（见 D27–D30）。
- **三环与 `apply` 的区别（E1）**：三环是"按阶段全量"，`apply` 是"按需求跨环增量"。两者是不同模式，不合并。
- **需求级入口**：不需要新命令，就是 Trellis 原生（`/trellis:start` 或 `trellis`）。

---

## 7. 需求级流程与 Trellis 挂载

### 7.1 一条需求的完整生命周期

> 本节只讲**主路径**（需求级）；开户 / 回流 / 刷新等非需求入口见 §3.0 入口矩阵。

1. 你提出需求（自然语言，会话里说）。
2. Trellis 走它原生的 Plan 入口：建 task（`NN-slug`）、写需求级 `prd.md`。
   - **需求 ID = Trellis task id**；**需求卡 = 该 `prd.md`**；不另建 inbox。
3. Plan 阶段执行被插入的 `[required · once]` 步骤：**`atlas apply <需求ID>`**（应然前置更新）。
4. `task start` → Execute：Trellis 实现（`implement` / `check`）。
5. 收口：跑真实应用验收 E2E → 全 `green`（或 `blocked` 带原因）→ 回写 `current/` 结构事实 → Trellis `update-spec` + `finish`。

### 7.2 挂载方式（改 `.trellis/workflow.md`）

- 在 **Phase 1 Plan** 里加一个步骤（如 `#### 1.6 项目级资产更新`），内容 = 调 `atlas apply`。
- 在对应 `[workflow-state:planning]` 面包屑块里加一条 enforcement 行，使其**每轮自动提醒**（见 §8.2）。
- 允许的既有改动面：`.trellis/workflow.md` 是流程 SSOT，官方支持本地修改，`trellis update` 遇 hash 分歧会提示而非静默覆盖。
- **不改**：Trellis 的状态机（`planning / in_progress / completed` 三状态）、hook 里的解析逻辑。atlas 不新增 Trellis 状态——因为 Trellis 没有任何 CLI 子命令能写自定义状态，新增状态会造成"状态永远不出现"的死结。

---

## 8. Trellis 约束（已核实，设计必须遵守）

### 8.1 可改动面

| 对象 | 可否改 | 说明 |
|---|---|---|
| `.trellis/workflow.md` | 可改 | hash 跟踪；用户改动受保护，升级时提示冲突 |
| `.trellis/config.yaml` | 可改 | 同上 |
| `.trellis/spec/**` | 可改 | 默认不被 update 刷新 |
| `.trellis/tasks/`、`.trellis/workspace/` | 可改 | 用户数据，保留 |
| `.trellis/scripts/**` | 谨慎 | hash 跟踪，升级会提示 |
| project-local skill（新名字） | 可改 | **不被跟踪，永不被 update 触碰** |
| bundled skill 目录（`trellis-meta` 等） | 不要改 | `trellis update` 会覆盖 |

### 8.2 自动触发的两个层次

1. **确定性**：`.claude/hooks/inject-workflow-state.py` 每轮注入 `[workflow-state:<status>]` 面包屑，内容取自 `workflow.md` 的标签块。写成 `[required · once]` 的步骤会**每轮出现**。
2. **概率性**：skill 命中靠 `description` 让模型判断，不是硬触发。且 Trellis 要求建 task 前必须获得用户同意，所以实际是"自动提醒 + 你点头"。

**结论**：把 `atlas apply` 写成 Plan 的 `[required · once]` 步骤 + 一条面包屑 enforcement 行，才可靠。

### 8.3 会踩的硬编码点

- `common/workflow_phase.py` 写死了边界标题 `## Phase 1: Plan` —— 不要重命名它。
- `get_step` 只认 `#### <数字>.<数字>` 形式的步骤号 —— 新步骤必须沿用 `X.Y` 编号。
- `/trellis:continue` 的路由表只认 `planning / in_progress / completed`。
- 无 `set-status` 类子命令；`task.py start` 只会把 `planning → in_progress`。

---

## 9. 跨项目分发

### 9.1 包结构（独立 Git 仓库）

```
atlas/
├── README.md
├── DESIGN.md                        # 本文件
├── install.sh                       # 装进任意项目；可重装、可升级
├── shared/                          # 三环共享契约（全局规则 / stack-profile+适配器 / 单一真相源 / 布局 / **门总账 gates.md** / **收口清单 closeout.md**）
├── skills/                          # 平台装配单元：一个环一个瘦桩
│   ├── atlas-structure/SKILL.md     #   指回 .atlas/rings/structure/reference.md
│   ├── atlas-prd/SKILL.md
│   ├── atlas-e2e/SKILL.md
│   ├── atlas-apply/SKILL.md         #   跨环编排：apply + adopt + all
│   └── atlas-design-review/SKILL.md #   独立审查第 3 类实例（设计主张复核）
├── rings/                           # 各环执行契约：<ring>/reference.md（structure / prd / e2e）
├── apply/                           # 跨环增量契约：reference.md（apply + adopt + all）
├── scripts/                         # refresh_structure.py（结构事实区刷新；after_finish hook）+ gen_e2e_scripts.py + gen_testid_stub.py + make_review_inputs.py + atlas_check.py + e2e_console.py + mutation_proof.py + backflow.py（回灌助手，2026-10-12）
├── _support/                        # 共享内核（2026-10-12 单源批）：siblings.py（随包模块加载器）/ stack_profile.py（profile 单源解析）/ case_block.py（用例块单源解析）——scripts 与 validators 共同消费
├── patches/workflow-plan-apply/     # 锚点补丁：往 workflow.md 插 1.6 + 面包屑 enforcement
│   ├── spec.json                    #   补丁载荷
│   ├── apply-patches.py             #   锚点式幂等应用器（复用现有模式）
│   └── *.insert.md                  #   插入片段
├── patches/project-wiring/          # 四触点接线（幂等）：AGENTS.md 指针段 + after_finish hook + pytest marker 兜底 + pi 宿主扩展
├── extensions/                      # 宿主扩展（2026-10-15 纳入装配）：pi.ts（`/atlas` 控制台 + 开户态判定 + 提示注入）
├── templates/                       # stack-profile / prd / 结构 / e2e 用例 / 评审控制台模板
├── adapters/                        # 各栈事实抽取器（见 §9.3）
├── validators/                      # 机器校验脚本（见 §10）
└── tests/                           # 回归测试（含装配面自检 test_install_selfcheck.py）
```

### 9.2 stack-profile.yaml

每个项目根放一份，声明"用什么适配器"，核心只读它、不认识任何框架：

```yaml
product: <产品名>
apps:
  - name: <app 标识>
    path: <相对路径>
    kind: frontend | backend | fullstack | mobile
    stack: <自由文本，仅作展示>
adapters:
  routes: <adapter 名 | null>
  api: <adapter 名 | null>
  models: <adapter 名 | null>
  tests: <adapter 名 | null>
```

未声明适配器（`null`）的类别，退回 agent 撰写。

### 9.3 适配器

- 只负责"从代码抽取可枚举事实"，输出结构化的中间产物，不写文档。
- 按栈实现，如 `vue-router`、`fastapi`、`sqlalchemy`、`pyxle`、`electron` 等；命名不绑定具体项目。
- 没有对应适配器的技术栈：该类别由 agent 撰写，并在结构基线里标注为"人工维护"。

### 9.4 安装产物

`install.sh` 在目标项目里落地：

1. **整包 → `<目标>/.atlas/`**（`shared/`、`rings/`、`apply/`、`templates/`、`adapters/`、`validators/`、`patches/`、`tests/`、`_support/`）；属包产物，默认刷新。
2. 每个 `skills/atlas-*/` → 各平台 skill 目录（瘦桩 `SKILL.md`，指回 `.atlas/`）；并清理历史单入口 `atlas` skill。
3. `.trellis/workflow.md` 的 Plan 步骤补丁（锚点幂等；`--no-patch` 可跳过）。
4. `product/` 目录骨架 + `stack-profile.yaml` 模板（既有内容永不覆盖）。
5. **项目接线**（`patches/project-wiring/`，幂等；`--no-wiring` 可跳过）：`<目标>/AGENTS.md` 的 `<!-- ATLAS:START/END -->` 指针段（置于 Trellis 区块**外**，不被 `trellis update` 覆盖）+ `.trellis/config.yaml` 的 `after_finish` hook（`refresh_structure.py`）。补的是「新项目 agent 一开会话就知道本项目用 atlas、契约在哪、需求级怎么走、撞到规则不合业务往哪上报（§15）」的入口（D73）。
6. 回归自检（含 Plan 补丁、AGENTS.md 指针段、`after_finish` hook 三项生效检查）。

### 9.5 平台适配

至少覆盖：**Claude Code、opencode、Codex、Pi**。
- 对应目录：`.claude/skills/`、`.agents/skills/`（opencode/共享）、`.codex/`、`.pi/`（pi 走 `.agents/skills` + extension/prompts）。
- skill 只依赖 `name` + `description` frontmatter，触发短语写进 `description`。
- 命名避开 Trellis 保留名：`trellis-meta` / `trellis-spec-bootstrap` / `trellis-session-insight` / `trellis-channel`。
- 升级同步：配置驱动 + 白名单 + 冲突台账（上游更新与本地改动的覆盖逐条留痕，不静默覆盖）。

---

## 10. 机器校验

| 校验 | 时机 | 判定 |
|---|---|---|
| 索引 ID 唯一 | `atlas e2e`、`atlas apply` | 全站无重复 |
| 索引 ↔ 分片双向可达 | 同上 | 无孤儿、无死链 |
| 分片 `testid:` 应然 ⇔ 前端源码实然（E1） | `atlas e2e`、`atlas apply` | 已实现页双向集合相等；未实现页 SKIP |
| 用例必填字段完整 | 同上 | `id` / `pages` / `precondition` / `step` / `expected` / `testid` 非空 |
| `关联AC` 可达 | 同上 | 指向域级 PRD 中存在的 AC |
| `状态原因` 完整性 | 同上 | `blocked` / `skipped` 必填 |
| 结构事实抽取可重复 | `atlas structure` | 重跑产物与磁盘一致（无手工漂移） |
| `stack-profile` 合法 | `install.sh`、`atlas *` | 适配器名可解析 |
| 设计档案 detect 豁免 ⇔ `.impeccable` 配置 | `atlas_check`、档案 / 配置改动后 | `detect:<rule-id>` ⇔ `detector.ignoreRules` 双向集合相等；无档案 `SKIP`（三态） |

默认在 atlas 各环与 `apply` 时跑；**可选**再加 git pre-commit 钩子做兜底。

**实现状态**：9 个校验器（`validate_{structure,stack_profile,prd,testids,e2e_index,design_exemptions,e2e_mocks,ac_alignment,adr}.py`）+ `scripts/atlas_check.py`（门总览：校验器 / 出厂测试 / 生成物 / 真跑，**一门一行 `ok|FAIL|WARN|SKIP`**）。

**门总账与收口清单（2026-09-28 落地，`3509 §B112`/`§B114`）**：所有门登记在 `shared/gates.md`（含**对账平面 / 显式盲区 / 验证预算 / 假绿测试取证等级**三列）—— **不在表 = 不存在**；人侧收口步骤表 = `shared/closeout.md`（此前被多处定形引用却长期不存在）。`SKIP` 是**一等结论**（未就绪），不是通过。

---

## 11. 接入起点（新项目）

**最小可用基线**（不必等全站建完）：

1. `stack-profile.yaml` + 约定类结构（A / G / I）。
2. PRD 骨架（定位 + 用户 + 已有功能条目）或（绿地时）仅产品定位。
3. E2E：空索引 + **页面表**（未实现页记 `未开始`）+ 校验脚本可用。

**启动顺序按项目现状自适应**：

| 项目形态 | 顺序 |
|---|---|
| 绿地（`origin: greenfield`，等价入口 `apply all`） | stack-profile + 约定 → PRD 骨架 → 空索引 + 页面表 → 开始接需求（事实类随代码由适配器补齐） |
| 重构 / 存量（`origin: adopt`，`apply adopt` 开户） | legacy structure 事实（适配器抽取）→ PRD 开到「开户最小集」（只登记基线，不全量重述）→ 不预设 E2E（由后续需求按三问门长出）→ 开户交尾出实现期薄桩（老页面 testid 实然盘点，`apply/reference.md` §1）→ 开始接需求 |
| 纯存量自描述（`origin: adopt`） | structure 事实 + PRD（当前功能条目，开户最小集）→ 不预设 E2E → 开户交尾出实现期薄桩（老页面 testid 实然盘点）→ 开始接需求 |

存量两行的 E2E 口径 = `apply/reference.md` §1 adopt 教义（开户不预设 E2E；E1 原型环已移除），2026-09-29 对齐（`B146-1`）；交尾薄桩为**交割物显式化**（缺失由 `validate_testids` 自动补齐，非门禁前置），2026-10-15 补。

**绿地为什么是友好的**：事实类内容由适配器从代码生成，**没代码就没有事实**，不是"没建完"；而 E2E 先行在绿地上价值更大——用例本身就是规格。

---

## 12. 决策记录

> **E1（2026-09-27，原型环移除）作废的决策**：D8（两段式执行模型）、D45（依据来源含原型）、D46/D47（页面 = 原型文件名 / testid 双向锚原型）、D48（`执行目标` 字段，另已于 2026-09-23 退役）、D49–D53 中依赖原型的部分、D54–D59（原型产物布局 / URL / 交互分级 / 生成流程 / 应然 token / 原型环范围）、D67（`validate_prototype.py` / `serve_prototype.py`）。**D68 部分有效**（生成器已落地，两段式部分作废）。**现行口径**见 `.atlas/shared/` + `rings/*/reference.md`；历史依据见 `3508 §92`。下表保留原文，供追溯「当初为什么这么定」。

| # | 决策 | 结论 |
|---|---|---|
| D1 | 运行边界 | atlas 全链路活在业务仓库内部（`.atlas/` / `product/` / `.trellis/spec/structure/`），可独立运行 |
| D2 | 外层旧资产 | 只当一次性素材，不继承口径 |
| D3 | 层次模型 | 项目级（atlas）与需求级（Trellis）正交 |
| D4 | 需求与资产的关系 | 需求增量合并进项目级资产（living） |
| D5 | 资产归属维度 | 产品维度；逆向事实分 `legacy` / `current` |
| D6 | 结构基线内容 | 全局层 + 域级层；5 必填（B–F，D 条件）+ A/H 落项目根 `README.md`；G 归 E2E、I 移出（见 D35/D37） |
| D7 | 结构基线生成 | 二分：约定类人写 + 事实类适配器抽取（跨项目要求） |
| D8 | E2E 执行模型 | 两段式；用例真相源 = 索引；testid 真相源 = 原型 |
| D9 | E2E 组织 | 页面分片 + 总索引；三条硬规则 |
| D10 | E2E 脚本 | 从分片生成 Playwright，`baseURL` 切换目标 |
| D11 | 状态机 | `red → prototype-pass → green`；旁支 `blocked / skipped` |
| D12 | 完成门 | 硬门 + 显式例外 |
| D13 | testid 规范 | `<页面slug>-<语义名>[-<变体>]`；必要元素；双向校验 |
| D14 | atlas 形态 | ~~单入口 skill + 分环子命令 + `apply`~~ → 已修订，见 D27 |
| D15 | 资产位置 | 结构事实进 `.trellis/spec/structure/`；PRD/原型/E2E 进 `product/`；A（可选）/ H（条件）进项目根 `README.md`；编码规范与 testid 约定**移出 structure**（见 D35） |
| D16 | PRD 形态 | 全局 + 域级两级；域按**产品功能域**划分并映射到 structure 模块；应然不挂状态；需求类别含「迁移性」 |
| D17 | 原型形态 | 纯静态多页 HTML；按 PRD 重新设计；全站目标、增量补齐 |
| D18 | Trellis 改动机制 | 直接改 `.trellis/workflow.md` |
| D19 | 需求 ID / 需求卡 | = Trellis task id / task 的 `prd.md`；不建 inbox |
| D20 | 资产更新时机 | 前置（实现之前） |
| D21 | 分发方式 | 独立工作流包 + `install.sh` + 锚点补丁 + 适配器 + `stack-profile` |
| D22 | 需求级挂载 | Trellis Plan 阶段 `[required · once]` 步骤 = `atlas apply` |
| D23 | 命名 | atlas |
| D24 | 文档位置 | 本文件 |
| D25 | 平台适配 | 至少 Claude Code / opencode / Codex / Pi |
| D26 | 接入起点 | 最小可用基线；顺序按项目现状自适应 |
| D27 | skill 粒度（修订 D14） | 每环一个独立 skill（`atlas-structure` / `atlas-prd` / `atlas-prototype` / `atlas-e2e`），`apply` 独立为 `atlas-apply`（`apply` + `all`）；每个 `SKILL.md` 的 `description` 只含本环触发词 |
| D28 | 共享契约 | 四环共用契约集中 `shared/` 单一副本，各 skill 按路径引用，不复制 |
| D29 | 装配模型 | `install.sh` 把整包装到 `<目标>/.atlas/`；平台 skill 目录只放瘦桩 `SKILL.md` 指回 `.atlas/`；顺带修掉模板 / 适配器 / 校验器装不进目标项目的黑洞 |
| D30 | 适配器契约归属 | 适配器 JSON 契约由 structure 契约迁至 `shared/stack-profile.md`（适配器由 profile 声明，非 structure 私有） |
| D31 | ~~逆向首建同程~~ | 已撤销，见 D34 |
| D32 | A 类（技术栈+启动）可选 | A 由用户决定是否逆向；不纳入即整类跳过、不计失败。纳入时落点 = **项目根 `README.md`**（受控例外，仅「技术栈 / 启动」两节 + 确认门），不落 `structure/` |
| D33 | D 类（接口）条件化 | 有机器可读接口描述（OpenAPI / Swagger / …）→ 只记真相源入口不复制端点；无 → 才抽清单。探测属适配器（`shared/stack-profile.md` §3.5） |
| D34 | 逆向与 PRD 解耦 | 撤销 D31：逆向只产结构、**不自动触发 PRD**；PRD 环独立运行、按需读逆向产物（PRD 会持续更新，绑定逆盛会误触发） |
| D35 | 结构类目收缩 | G（testid）移出至 **E2E 环**；I（编码规范）删除。结构 = 全局层 + 域级层（B–F，D 条件）；H 改条件类落根 README（见 D37） |
| D36 | 域模型 | structure 从代码**提议候选域**（路由/模块/表/接口前缀聚类）→ `_meta.json.domains`；PRD 定稿回写。域 id 为全链路键；仅 `tour.md` / `domains/<d>.md` 带 `paths:` |
| D37 | 结构事实落 Trellis spec（方案 C） | 结构事实从 `product/structure/` 迁到 **`.trellis/spec/structure/`**：Trellis 任务**原生注入**消费，PRD/原型/E2E 按需 Read；撤销 D35 的「逆向零 `.trellis` 交互」；不再要独立桥 |
| D38 | 事实刷新机制 | **事实区**由 `refresh_structure.py` 确定性刷新，登记为 `.trellis/config.yaml` 的 **`after_finish` hook**（单行扩展点，升级冲突最小；hook 只跑 shell 正好）；**语义区**由 AI / `trellis-update-spec` 维护 |
| D39 | 适配器粒度与调用约定 | 一类脚本一个**通用名**（`routes` / `models`，非 `vue-router` / `sqlalchemy` 多名）；框架识别收在适配器内部。`--root` 传**项目根**（`source_file` 用项目根相对路径），`--app` 传 `apps[].name` 过滤；**域级类别按 app 各调一次**再合并（items 无 app 列），**全局类别整项目一次** |
| D40 | 结构环契约修正（随 D39 落地） | ① C 表多 app 前置 `应用` 列（单 app 可省）；② `_meta.json.categories.A` 值域改 `covered\|skipped`；③「每域 2 份」限定在**存在的 role 目录**内；④「来源可定位」允许按所属 app 根回退解析；⑤ `adapters` 去掉 `components` 键（落地 `shared/stack-profile.md` 早已去掉） |
| D41 | 适配器消费规程与产物落点 | 适配器**不自动改写文档**：由 structure 环 agent 按 **global 类别整项目一次 / 域级类别按 app 各一次** 调用，JSON 落 `<项目根>/.adapter-out/<category>[/<app>].json`（中间产物、非真相源；该目录是 atlas 全部中间产物的**单一位点**——适配器产物 / 漂移标记 / 图谱新鲜度标记同址，2026-10-15 统一，issue #8），再读 JSON 渲染事实表 + 补语义列。「事实区自动渲染 + 表→域映射」为后续独立项 |
| D42 | 适配器口径补齐（第二批） | ① `api`：Swagger 描述（落盘或运行时 `spec_entry`）→ 指针，无描述才源码抽 `@action`/装饰器清单；**不收**出站调用与前端 client 调用——**窄化声明（2026-10-15）**：该禁令以「存在后端 / 描述侧真相源」为前提；**纯前端无描述态下，前端调用点即 D 类唯一机械可抽源**（点分方法名 RPC 调用，`shared/stack-profile.md` §3.5），此时收它是补缺口而非违反本决策；② 【已退役 2026-09-30，F 类整体删除】`tokens`：只抽样式表自定义属性，`kind` 加第 6 值 `other`；③ `tests`：`type` 定 `unit\|integration\|e2e\|other`，`status` 留空由 agent 补 |
| D43 | 校验器面（本批） | 新增 `validate_stack_profile.py`（`null`=OK / 非 null 解析不到=FAIL / `app.path` 缺失=WARN）与 `validate_prd.py`（门控态追溯项 N/A 不 FAIL；链接**双基准**解析；机器检不了的子项降 WARN）；CLI 统一 `--root [--json]`、`{ok,status,checks[]}`、PASS/WARN→exit 0、FAIL→exit 1。`validate_testids.py` / `validate_e2e_index.py` 待 prototype/E2E 环契约 |
| D44 | 陈旧结构产物清理 + PRD 引用语义重映射 | 删除 `product/structure/`（D37 后遗留）；canonical 模板旧路径改 `.trellis/spec/structure/`；PRD 引用按新布局**逐条语义重映射**（routes/directory-map→`global/`，tech-stack/tests→根 `README.md`，apis/data-models→`<role>/<domain>/`），工作区路径改指项目内 `.atlas/` |
| D45 | E2E 依据来源（硬优先级） | ①业务预期唯一来自**域级 PRD 的 AC**；②交互与 `data-testid` 来自**原型**；③`.trellis/spec/structure/` 只作**参考基线**。三禁令：禁止用真实实现/旧实现行为反推预期；禁止用原型行为当业务规则；禁止无 AC 来源的用例（`prd_ref` 必填） |
| D46 | E2E 组织与格式 | `page` = **原型文件名**（去扩展名；`/`→`home`，带参取业务段）；索引主表列 `用例ID\|页面\|中文标题\|类型\|关联AC\|需求\|执行目标\|状态\|状态原因\|分片`（末列带锚点链接）+ 反向视图 `页面 ↔ 用例`；分片用 `## <ID> 标题` + ` ```atlas-case ` 行式键值块；**状态类字段只在索引**，`testid` 只在分片 |
| D47 | testid 规范与双向校验 | **唯一硬锚**（脚本一律以 testid 定位，不用语义/样式选择器）；命名 `<页面slug>-<语义名>[-<变体>]`；**分页等价**双向校验（有分片的页集合必须相等，未建分片页 WARN）；实现期薄桩落 `.trellis/spec/conventions/testid.md`（派生视图，正文唯一在 `rings/e2e/reference.md` §4） |
| D48 | E2E 用例词表与 ID | `类型` 保留用途四值（`smoke\|acceptance\|exception\|permission`，29119-4 仅作生成提示）；`执行目标` 为**最低目标**（`prototype` 原型期即须通过且实现后仍须过 app；`app` 仅真实应用可验），`--target app` 跑全量；`状态` `red→prototype-pass→green` + `blocked/skipped`；`状态原因` = `<枚举>：<中文说明>`（`ENV_ISSUE/NOT_IMPLEMENTED/SPEC_AMBIGUOUS/BLOCKED_DEP/DEFERRED/OUT_OF_SCOPE/OTHER`）；ID `E2E-<PAGE>-NNN` 每页独立、三位定长、删除不复用 |
| D49 | E2E 质量门（B 档） | 结构门（字段/ID/链接/孤儿/词表/`prd_ref`）**FAIL**；有意义门：`expected` 空或占位/断言数<1/`skipped` 无原因 **FAIL**，不可判定词与纯跳转步骤 **WARN**；语义判不了的（3 问准入、去重 intent）写进契约执行纪律，不进校验器 |
| D50 | E2E 脚本与执行（**E1 已作废**：`--target` 与 `prototype.base_url` 随原型环退役） | 运行器由 `e2e.runner` 决定；**一页一脚本**、派生可重生成（定制放 `scripts/_support/`）；`baseURL` 不硬编码，值取自 `prototype.base_url` 与 `e2e.app_base_url`、由 `--target` 选择；两段式；结果回写索引 `状态` |
| D51 | 页面原型前置判据 | 不按需求大小，按**是否改变应然 UI**：改 UI → 原型**增量**更新（仅受影响页/区域 + 打 testid）为硬前置；不改 UI（规则/数据）→ 复用既有 testid，只产 `执行目标=app` 用例；纯后端不可见 → 本环不产用例。影响面识别归 `apply` |
| D52 | E2E 环本轮范围 | 先落**设计**（`rings/e2e/reference.md` + `skills/atlas-e2e/SKILL.md` + `shared/layout.md` 落点）；`validate_{testids,e2e_index}.py` 代码、`install.sh` 装配、脚本生成器**延后**到真跑时落地 |
| D53 | E2E 结果断言与数据前提（源 Autonoma 经验） | 采纳用例写作硬规则：①禁把瞬时反馈（toast/成功提示/弹窗关闭）当验证；②持久化写（create/edit/delete/save）必须**刷新后复断言**（例外：校验被拒 / 纯导航鉴权 / 会话内短暂态）；③断言须落在与被操作控件**不同的真相源**；④编辑/切换类断言**前后两端**；⑤文案须为**渲染后可见文案**（禁 i18n key / 枚举 / 组件名）；⑥步骤禁"或 / 等 / e.g."二选一；⑦新增分片字段 **`intent`**（可证伪一句话声明）；⑧测试数据由本环**自行 mock**（确定性、可重跑、用例间独立，不引外部造数服务）。取证见 `research/e2e-open-source-survey.md` §1.7 |
| D54 | 原型产物布局与页标识 | `product/prototype/` = `README.md`（页索引 + 「原型 ↔ 真实路由」映射，**本环唯一权威**）+ `tokens.css`（应然 token 唯一源）+ `index.html`（评审壳：左页索引 + 右功能概览，**不算页**）+ `<slug>.html`（页 = 映射表列出者）；**页面标识（slug 与文件名）规则正文归原型环**（静态取末段 / 带参取业务段 / 根 `→` home）；E2E §3.1 改为按名引用（不再复述规则） |
| D55 | 原型 URL 与静态服务默认 | 原型 URL 与真实路由**逐字一致**（静态服务器支持无扩展名解析）；默认 `serve_command` = 随包纯标准库服务器脚本（端口 `4173`）、默认 `base_url` = `http://127.0.0.1:4173`；无 python 的项目在 profile 覆盖并降级为带 `.html`（零分支承诺失效）；两字段写回 profile 过确认门 |
| D56 | 原型交互分级 | **L1** 纯前端必须真交互（跳转 / 覆盖层 / 页签折叠 / 表单本地校验 / 列表本地筛选排序分页）；**L2** 后端动作可页面内 mock（**仅会话内**）但须以不可见 `data-atlas-sim="<动作>"` 标边界、**不得伪装已持久化**；**L3** 允许纯静态（保留元素与 testid）；六类状态经**不可见触发**（`?state=`）演示；`执行目标=prototype` 用例只覆盖 L1 + L2 会话内 |
| D57 | 原型生成流程 / 增量 / 门控态 | 全量 = 读 §七 → 出设计方向 → 建页清单（README）→ 逐页生成 → 评审壳 → 校验报告；增量判据 = **是否改变应然 UI**，仅改受影响页/区域，影响面归 `apply`；单页增量常规、整页重建 / 删页 / 全量重生成过确认门；**门控态 = 只落空骨架（README 表头 + 空态评审壳），零业务页面、不杜撰，校验器记 N/A** |
| D58 | 原型应然 token 与设计方向 | 应然 token 唯一源 = `product/prototype/tokens.css`（生成器**内联**进各页、与源**字节一致**防漂移）；`.trellis/spec/structure/global/design-tokens.md` 只作**参考基线**（实然）；逐页开画前先出一句**框架无关**的「设计方向」并确认，不点名任何框架 / 字库 |
| D59 | 原型环本轮范围（**E1 已作废**，`3508 §92`） | 先落**设计**（`rings/prototype/reference.md` + `skills/atlas-prototype/SKILL.md` + `shared/{single-source,layout}.md` + E2E §3.1 指针）；`scripts/serve_prototype.py`、`validators/validate_prototype.py`、`install.sh` 自检、`stack-profile` 两字段写回**延后**到真跑 |
| D60 | apply 参与环与顺序（**E1 已修订**；原值含 `prototype`） | `apply <需求ID>` = **`prd → e2e`**；`structure` **不参与**（实然，实现后由 `after_finish` hook / `update-spec` 维护）；唯一例外 = 本次 PRD 定稿改了域清单 ⇒ 末尾追一次 structure **re-key**（structure 契约 §2.2）。`all` = **`structure → prd → e2e`**（`apply/reference.md` §3/§6） |
| D61 | 影响面识别 | **agent 语义判断 + 结构证据约束**（需求卡 / `routes.md` / `_meta.json.domains` / 原型页表）；产结构化清单（受影响域 / 页 / 变更性质 / 证据）；低置信、歧义、映射不到 ⇒ 一次性 ≤3 问，不猜；**禁** regex 判语义（D53/E16 反例） |
| D62 | apply 增量边界与覆盖门 | 各环只落受影响增量（PRD 受影响域章节 + 追溯总表行 / 原型受影响页区 + testid / E2E 受影响分片 + 索引行）；单页单域增量常规；整页重建 / 删页 / 全量重生成 / 删既有产物 / 改 profile ⇒ 过确认门 |
| D63 | apply `all` 模式 | 顺序固定；幂等；断点续跑（失败 / 门控停在该环，下游不静默跳过；重跑按产物存在跳过，对齐 Trellis `[once]`）；门控态不判失败 |
| D64 | apply × Trellis 挂接 | 需求 ID = task id；Plan `#### 1.6 项目级资产更新` `[required · once]` + `[workflow-state:planning]`（含 inline）面包屑 enforcement；**不新增 Trellis 状态**、不改状态机 / hook 解析；失败停在 planning、不得进入实现 |
| D65 | apply 回写与报告 | 执行记录 = `.trellis/tasks/<需求ID>/atlas-apply.md`；apply 在实现前跑、**不回写** E2E 执行状态（新用例置 `red`）；不改需求卡 `prd.md`；`green` 回写在原型期 / 实现后 / 收口 |
| D66 | patches 实现 | `patches/workflow-plan-apply/`（`spec.json` + 锚点幂等 `apply-patches.py` + 片段）；只做外科式插入、以 `<!-- atlas:apply:<id> -->` 判幂等、可重放；`install.sh` 装配（`--no-patch` 可跳过）；**前置 B2**（`trellis` CLI 升到项目 `.trellis/.version`）；回归测试 `tests/test_apply_patches.py` |
| D67 | 校验器与原型服务器落地（2026-09-20） | 实现 `validators/validate_prototype.py`、`validate_testids.py`、`validate_e2e_index.py`（纯 stdlib、无框架名、门控态 `N/A`、CLI `--root [--json]`、PASS/WARN→0 FAIL→1）与 `scripts/serve_prototype.py`（无扩展名解析静态服务器，默认 `127.0.0.1:4173`）；`install.sh` 自检覆盖两者；回归测试 `tests/test_validators.py`。**关闭 C5 的三项校验器**，并解除原型/E2E 环的「代码延后（D52/D59）」；`stack-profile` 两字段写回仍属原型 skill 的确认门动作 |
| D68 | E2E 脚本生成器 | `scripts/gen_e2e_scripts.py`：产**可运行的 testid 冒烟骨架**（`goto(<页面 URL>)` + 分片 `testid` 存在性断言；中文 `step`/`expected` 作注释）；**深断言放 `_support/`**（不覆盖，`hooks.deep_assert`）；地址**不硬编码**、由运行器原生配置承载（`--target` 选 `prototype.base_url` / `e2e.app_base_url`）；一页一脚本、派生可重生成、dry-run 缺省 |
| D69 | 事实区自动渲染（C7） | `refresh_structure.py --apply` 读 `.adapter-out/*.json` 自动重写事实区表：**行键级单元格合并**（适配器填可枚举列、既有行**语义列保留**、新增行语义列留空→校验器 WARN、消失行移除）；归属 = 条目 `source_file` → app（最长 path 前缀）→ role（`landing`→`current/`）→ 域 globs（最长命中），**无命中落 `global/{apis,data-models}-shared.md`**；无 `.adapter-out/` 时跳过（agent 维持）。**items 粒度 = 渲染行键**（2026-10-15 补）：适配器**不去重**（items 是代码里的事实，同一端点被两个域各调一次是两条合法事实，各进各的域文件），同一目标文件内的**重复行键**在渲染期折叠为首行（`dedup_by_row_key`）——否则表里出现同键重复行，而语义列在重复键上没有归属可言 |
| D70 | 适配器脚手架与指南 | 新增 `adapters/_scaffold.py`（可复制填空的适配器模板，强制 `source_file`）+ `adapters/README.md`（契约 §3 落成步骤）；把「无适配器 → `null` → agent 撰写」作为**一等降级**；`models` 条目补 `source_file`（支撑 D69 域归属）。**框架知识只允许出现在适配器内** |
| ~~D71~~ | **【已退役 2026-10-14】** 知识库（Obsidian）维护契约（2026-09-20） | 新增 `shared/knowledge.md`：知识库保存**设计依据与讨论**（「为什么这么定」），与产物分层、不复制正文。**可选增强**——`stack-profile.knowledge.vault` 为 `null`/缺省 ⇒ 整体跳过、不阻断任何环。写入/检索**经 open-zk-kb MCP**（不手写 vault 文件）；vault 内**唯一 atlas 设计目录**（跨项目共用，不按项目分目录）。四环与 `apply` **收口必做**（`global-rules.md` §9）；只写持久设计与依据（决策/讨论/被否/纠正/未决），不写进度与产物正文；契约变更**仓库 canonical 与知识库两处同改**。`stack-profile` 增 `knowledge` 段（`tool/vault/dir/project`）；`install.sh` **不写用户 vault**（只落 profile 草稿 + 自检契约存在） |
| D76 | 设计档案契约登记 + 豁免机器对账门（2026-10-08，`3508 §200` / `ATLAS-UPSTREAM #182`） | `product/design.md`（视觉设计档案）登记为项目级应然文件：**写者 = frontend-design skill**（atlas 包外；atlas 不生产、不覆盖、只读两个触点）——① 走查单确认门前对照视觉方向一致性（`rings/prd/reference.md` §4·八）；② 档案「已有豁免」的 `detect:<rule-id>` 必须与 `.impeccable/config.json` 的 `detector.ignoreRules` **双向集合相等**，新校验器 `validate_design_exemptions.py`（无档案 ⇒ SKIP 三态；变异 M43）。缘起：档案生于 frontend-design skill 吸收 impeccable 精华（`3508 §199`），项目根落点撞 atlas 产物归属与 `DESIGN.md` 契约名 ⇒ 用户拍板固定落 `product/`。被否：按 `.atlas/` 存在与否嗅探两种落点（双落点 = 漂移面）；校验器内嵌 impeccable 规则表（第三方升级会误伤） |

| D72 | 职责边界 = 约束层（2026-09-22，对标 Harness） | atlas **只收口约束层**（应然资产 / 唯一事实源 / 三类入口），Harness 其余四层按阶段分工、不并入：① 对抗验证——atlas 只审自身产物（当前 `prd review`），实现代码审查归 Trellis；② 证据层——只留确定性校验器 + E2E 状态机，可视化报告与「测试覆盖状态跳转」检测延后（依赖 B4）；③ 状态写入——只记影响面与 `atlas-apply.md`，目标复述 / 长任务持久化归 Trellis；④ 边界对齐——atlas 侧 = 确认门 + 完成门 + apply 覆盖门，CI 分级与回滚延后（依赖 B4）。**G1 原型/E2E 审查、G2 可视化证据、G3 CI·回滚登记为未决（`3509 §C8–C10`），实跑后按证据 promote**。理由：Harness 是项目跑了两个月的事后归纳（非蓝图），atlas 尚未端到端跑通一条需求（`3509` 批 6 登记（该机制原属 §13 待实现事项；§13 现只放指针，逐项状态以 `3509` 为准）），在未运行的设计上预置机制是拿猜测赌契约。详见 §3.1 |
| D73 | 项目接线自动化（2026-09-22） | 新增 `patches/project-wiring/`（`apply-wiring.py` + `agent-pointer.md` + README），`install.sh` 作为第 6 步装配（幂等、`--no-wiring` 可跳过）：① `<目标>/AGENTS.md` 在 `<!-- TRELLIS:END -->` **之后**写 `<!-- ATLAS:START/END -->` 指针段——位于 Trellis 区块**外**故不被 `trellis update` 覆盖；② `.trellis/config.yaml` 幂等登记 `after_finish` hook。**修的是两处此前靠手工、且升级会被冲掉的接线**（install.sh 原本完全不碰 AGENTS.md）。回归测试 `tests/test_project_wiring.py`（11 用例）。属 `global-rules.md §7` 确认门动作，由显式安装触发 |
| D74 | 定位表述定稿：身份 ≠ 实现分工（2026-09-29，`3508 §129` 设计树 A–F） | **身份** = atlas 是覆盖「立项 → 需求 → 应然资产 → 实现 → 验收 → 收口」的**全流程 vibecoding 工作流**，项目级应然资产跨项目分发、机器可校验；**实现分工** = 「需求级执行」由执行器承担（**当前 = Trellis**，依附其官方可改面，不改状态机与 hook 解析），执行器可替换是未来可能而非现行契约。改面：`README.md` 开场 + §定位（删「分层正交」作身份表述——它降为产物分层的实施细节，归 `DESIGN.md` §3/§8）；`patches/project-wiring/agent-pointer.md` 标题与首行同步（重装配后注入各业务仓库 AGENTS.md）。被否：把「atlas = 项目级资产层」当身份（一次分工决策 D72 静默改写身份，实证 `3508 §129`）；「执行器 adapter」先行（无实跑取证） |
| ~~D75~~ | **【已退役 2026-10-14】** 知识库双通道 + KB 投影对账门（2026-09-29，`3509 §B116`/`§B121` 拍板「按推荐走」） | **双通道**：短 note 经 MCP（store/get），**长 note 定点/批量修订直接编辑文件** + 收口跑 `kb_index_refresh.mjs` + `kb_projection_check.mjs` 对账（`shared/knowledge.md` §3 重写；原「不手写 vault 文件」与历轮实践矛盾，且 open-zk-kb 无文件监听 ⇒ 手改不重索引会静默漂）。**对账门**：`atlas/scripts/kb_projection_check.mjs` 用包内解析器逐篇逐字段比对投影（`.index/knowledge.db`）⇔ vault 本体，四类漂移指名，入 `gates.md` 2.1（测试 + 三类变异咬合）；`atlas_check` 对校验器 WARN 行从静默当 ok 改为显式 `WARN` 行。配套：`embeddings:{enabled:false}` 落 `~/.config/open-zk-kb/config.yaml`（本机不可达 HF CDN，local 兜底使 rebuild/embed 每次白试下载 = MCP 超时根因）。被否：坚持 MCP 单一通道（唯一可行通道就是直接编辑，实证 `§B116` 硬证据）；拆短 note 方案（丢历史、覆盖风险） |

| D77 | 图谱后端隔离层的边界与落点（2026-10-15 收口，用户实测回报驱动） | ① **消费面就两处**：`routes` 的文件枚举通道（派生逻辑与 regex 同一份）与 `apply` 影响面基准（`impact_report.py`）——**不做**域聚类（域归 `rings/structure/reference.md` §2.1 多信号投票）、**不替**任何适配器的解析层；② **落点 = 项目根 `.adapter-out/`**——**与适配器产物、漂移标记同址**（2026-10-15 统一，issue #8：该目录是 atlas 全部中间产物的单一位点，设计档案目录树原本即如此；此前实现漂成同名两处 ⇒ 现场「`git status` 有 `.adapter-out/` 而漂移门说『无产物目录』」）；**后端自己的索引库不得落进项目工作树**（否则新鲜度键自激成永不稳定的全量重建）；启用图谱的项目应 gitignore 该目录；③ **枚举范围纪律**：图谱通道的文件清单必须过与 regex 同一份 `IGNORE_DIRS` 剪枝（`cgc index` 无 exclude 旗标，否则依赖目录进池产假事实）；④ **启用方式**：出厂注释态 + 确认画像时探测并**提议**（不自动声明——画像不该替用户承诺环境依赖能力，且图谱有持续成本）；⑤ 非 git 工作树 ⇒ WARN + 每次全量重建（不硬崩）；`ensure_index` **单进程假设**。缘起：README 原称图谱供给结构抽取「跨文件端点到模型映射 / 级联依赖自动归域」，实装无此事 ⇒ 文档按实情收窄，同时把上面五条纪律定形。被否：把图谱能力做上去（当前 name 级调用图抓不到 ORM / 属性访问边，做跨文件映射会往 canonical 事实表灌批量假事实）；自动声明（持续成本 + 承诺环境依赖）。详见 `docs/innovations/code-graph.md` |

| D79 | 门册五件遗留态收口——真跑裁决记录归一 / AC 升档规则落档 / D77 否决面词汇钉 / impact 观察窗 / 装配生效面文案（2026-10-15，评审修后采纳） | ① **真跑记录裁决**：以 gates 2.2「E2E 真跑」行的仓内记录（**逐页真跑 + 咬出真红，`3508 §166`/`§187`/`§190`**）为事实，纠正三处 2026-09-28 批残留的「真栈未跑/首次真栈执行未发生」措辞（gates 2.4 完成门 = 域收口事件、与真跑门独立；`DESIGN.md` §13 项、`rings/e2e` §16、上限声明）；「暂不真跑」裁决（2026-09-28）标注为已被执行反推，双台账会话号（`3509 §111`/`3508 §111`）并列引用；取证上限改**逐格**：真跑级只给字面咬过的行、须附咬合证据，未覆盖行保持出厂级、不预填；首跑协议 = 1 app × 1 页最小切片，留档 `product/e2e/reviews/<日期>/`；E0 产物残留重生成绑真跑准备日。② **AC 反向覆盖升 FAIL 规则落档**：触发 = 零挂靠清零 + 清零态实测全绿一次 ⇔ WARN 分支改 FAIL（不设 profile 开关——灰度即「看起来在跑」面）；升档日 source/copy 分叉按回灌批收口；校验器 WARN detail 的外仓 P9 死指针改为 gates 行锚。③ **D77 否决面词汇钉（canonical 判据⑦，治标）**：黑名单（`Leiden/拓扑聚类/自动归域/端点到模型/阻断全仓`）出现在活语境 ⇒ 红，豁免锚 = 行内 D77/D78（**局部自持，不得并入 `RETIRE_MARKS`**——共享会串门到 ①③⑤）；扫面收窄到 git 跟踪源 md（`rglob` 不认 .gitignore，`.vitepress/dist` 编译产物会漂判据）；**首跑咬合 4 处**（`docs/design/overview.md` 三处 + `prd-ring.md:124`——D78 ④ 收窄漏网，sweep 应按词 grep 不按清单改文件）；`rings`、`apply`、`patches` 三目录不扫 = 显式盲区；closeout 新增宣称 sweep 触发行（改被否裁决 ⇒ 全仓 grep + 词表同批登记）。④ **impact 观察窗**：不加代码——台账 = `impact_reconcile` 已无条件落盘的 `impact-reconcile.json`；升 FAIL 触发 = 裁决日起**连续 3 单**漏报 0 且无**同文件**重复漏报；升档后 miss ⇒ FAIL、over 保持 WARN（分档防良性偏宽钉死收口）；判据值全落 gates 行、不赖仓外 `3509 §B191-1` 数字。⑤ **装配版本门文案升级**：WARN detail 给齐两支路生效路径（npm 全局态 `atlas upgrade`+`atlas update` / 本地源仓 `install.sh`）+ `backflow.py` 三态明细通道；不做第二套文件级 diff（防腐）；同批三处回写（`test_atlas_check` 断言钉 M68 / gates 2.2 行 / `pkg_digest.py` docstring）。被否：--record 追加台账（盘上已有按单产物，双视图=两处正文）；版本门内重算 diff；AC 升档加灰度开关；判据⑦并入 `RETIRE_MARKS`；以「待复核」复述未真跑行。变异：M67（摘 `VETO_WORDS` 一个词 ⇒ 判据⑦喂坏输入用例红）/ M68（摘 WARN 文案动作词 ⇒ `test_atlas_check` 文案钉红）；两枚还原逐字节一致。设计评审：tech-proposal-reviewer 子代理，五件全「修后采纳」，本行按其修正点落地 |

| D78 | 图谱收益实测改判 + 接线第 5 触点 + 跨产物声明一致门（2026-10-15，issue #2 复审驱动） | ① **前端栈实测改判**：cgc 0.6.13 前端形态夹具实测——JSX 组件引用不产生任何调用边（`CALLS` 与启发式调用边均不覆盖 `element: <Comp />`），且 atlas 消费层只认 `CALLS` 边（`_graph.callers` 写死边型，后端加渲染边也读不到）⇒ 图谱对纯 UI 栈的两条消费面近乎零收益（routes 通道与 regex **恒等**；impact 对组件叶面系统性失真），逻辑调用链不受影响 ⇒ **提议按栈门控**（`apps[]` 存在 `kind ∈ {backend, fullstack}` 才探测并提议；字面枚举，不复用 `FRONTEND_KINDS`——该词表把 fullstack 归前端面，语义相反），撤回一轮排定的「atlas_check 图谱探测提醒」（对目标栈无收益的能力不需要发现通道）；② **接线第 5 触点**：`apply-wiring.py` 在目标项目**已有** `.gitignore` 时幂等追加一行 `.adapter-out/`（子串幂等、`!.adapter-out` 负模式不打架、无文件不首创；**无退役对称**——单向追加不改名撤回，gates 2.3 登记）；③ **跨产物声明一致门**：`validate_structure` 判接线态 ⇔ 形态 / 缺口登记（`adapters.api` 已接线但 `categories.D` 锚定声明为指针 / 未取证、或 `adapter_gaps.api` ⇒ WARN；F38 锚定声明同族；落 validate_structure 而非 stack_profile 的理由 = 三态前置复用，结构环未跑 ⇒ 整器 SKIP）；④ **文档收窄补漏**：03 收窄漏掉 `docs/design/structure-ring.md` 的「调用拓扑候选域聚类 / Leiden」宣称（与 D77 ① 直接冲突）及 `README` / `docs/concepts/rings.md` / `token-engineering` / `innovations` 开场的溢出措辞；`impact_report` 常驻「无调用方」提示句补 JSX 渲染引用。被否：为前端把渲染边能力在 atlas 侧补齐（D77 已否一次）；用指令通道解决 `.gitignore`（issue #2 姊妹缺陷实证「口头提议」会漂——`rings/structure` §6 步 1 的提议条款在实际接入里从未生效过）；判据落 validate_stack_profile（其前置只判 profile 存在，三态要自造，且跨产物读取归结构环平面对齐）。实测依据存档：cgc 0.6.13 /tmp 夹具复测数据见当时评审记录（callers 空集 + 边型普查 CALLS/CONTAINS/HEURISTIC_CALLS/IMPORTS/INHERITS）。 |

| D80 | 靶场登录预置：`app_login.mode` 三态声明 + 「段缺失」撤销合法降级（分两阶段升档）（2026-10-16，`RFC-20261015-02` / issue #11，评审修后采纳 + 用户拍板时间锚） | ① **字段落点**：`e2e.app_login.mode` 增 **`none`**（靶场无访问门，显式声明非降级）——家族先例 `e2e.mock.mode: off` / `e2e.review.mode: off`（「在 X 段里用 mode 值声明 X 通道不需要」）；不新增顶层 `e2e.auth`（与用例级 `auth` 同词不同作用域易误读 + 「有没有门」与「有没有取证值」拆两处 = 两真相源）；`none` ⇒ 段内五取证字段一律不得残留（含 `storage_key`——无门项目的存储键没有消费方；与 `fabricated` 的「收窄」相反 = 「全弃」，两条判据同构成镜像）；**空段 = 未声明**。② **段缺失语义改判**：不再是「合法降级」——硬要求（§7.1 登录态硬）的输入不得靠「缺失即静默放行」吸收。**分两阶段**：第一阶段 `validate_stack_profile` WARN 指名（`app_base_url` 已声明 = 项目准备真跑而 `app_login` 未声明；**文案必须中性**——本器判不了靶场有没有门，不得断言「每次都需人工登录」）；**升档 = 下一次真跑准备日（时间锚，无条件）**把未声明推给生成器 `not_ready`（退出码 3 + 机读键 `not_ready: "app_login"`，与 `app_base_url` 同一通道；SKIP 原因两态扩三态）——**第 1 次咬合（升档依据）= 2026-10-15 现场**（pass1→pass5 会话失效 + 人工登录，issue #11 取证），登记 `gates.md` 2.2「E2E 真跑」行（D79 ④ 判据值全落 gates 纪律）。被否：只加 WARN 不改语义（F37 同族「只会通过的门」）；顶层 `e2e.auth`；`app_login` 必填段——**诚实化**：② 的第二阶段效果（无门项目也须写 `{mode: none}`）与「必填段 + none 豁免」在结果上等价，真正的落点理由 = 撞名 + 单一真相源，不是「必填档做不到」；立即 FAIL（`未就绪 ≠ 失败`，永久红门 = 背景噪声）；用例侧信号精确收紧（备选 E——用例级 `auth` 缺省 `preset`，会把没逐条标 `auth: none` 的无门项目一并误挡，判据塌缩成全网收紧）。③ **产出方**：adopt 开户问数「靶场接入取证」（`app_base_url` + 登录形态三选一必须显式，凭据询问**不落盘**）+ 三问第 3 问判「是」而未声明 ⇒ 兜底追问（UX 加速器，判据正文仍是机器门——D78「指令通道会漂」的教训在此分流）。④ **`_support/stack_profile.py` 的 `yaml_scalar` null 家族收窄为 YAML 口径**（只认 `null`/`~`/空；裸 `none` 是合法字符串）——否则 `mode: none` 被吞成 null ⇒ 缺省判据读成 `real`，整个三态判据静默失效（单点修；全量回归无受影响夹具）。⑤ **词表守恒补缺**：`APP_LOGIN_MODES` 是唯一无「⊆ 模板 ⊆ 契约正文」守恒钉的 MODES 族（`SEED_MODES`/`ORIGINS`/`RUNNERS` 都有）⇒ 本批补上。变异：**M69**（none 字段互斥卸恒真 ⇒ 残留夹具绿）/ **M70**（WARN 前提挂错 ⇒ 未到期项目变吹）/ **M71**（none 分支仍生成 setup/storageState ⇒ 红）/ **M72**（yaml_scalar 收窄退回 ⇒ `test_profile_scalar_forms` 红）。设计评审：tech-proposal-reviewer 子代理「修后采纳」——评审改写了原稿自相矛盾的升档条件（原「被咬过一次」，按字面现场已满足且无台账落点）、指定了机读键、列清 `生成物最新` 门连带 SKIP 与 5 处残留措辞坐标，v2 据此落地。 |

| D81 | 走查与 E2E 控制台：术语交叉指认 + `manual.md` 定位收窄 + 产出方与存在性披露（2026-10-16，`RFC-20261015-01` / issue #10，评审修后采纳 + 用户拍板「硬门保留」） | ① **缺陷③的根因 = 术语撞车**：「走查」一词被两道不同阶段的门共用（跨 `3507 AQ` / `3508 §170` 两份决策记录复用同一 B124 标签，仓内无外史日志可直证原决策——措辞按「标签复用造成可误读现场」落，不归罪提报人）。定案 = **使用既有两名 + 撞车点交叉指认**：`走查单确认门`（`gates.md` 2.5，硬，=e2e §6.2 前置门）保留、`验收走查门`（`gates.md` 2.5，不阻塞后续域）保留；`rings/e2e/reference.md:383`/`:569` 与 prd §八 标题下补互指，`docs/design/e2e-ring.md` 措辞对齐。**不发明第三名、不全局改名**：波及 7 源文件 + 开户模板节标题 `templates/prd/domain.md:149`，与存量域 PRD 节名脱节，可逆性最差。② **缺陷②「双写无主」判为伪冲突**：`manual.md` 的契约定位 = 「**控制台盖不住的手工项**」（B124 原话），而收口走查的符合性对照物明文指向**已确认的 §八 节**（e2e `:176`）——两者结构 / 消费者 / 变更源全不同，不构成双写 ⇒ 不建回填协议；弱单向关联（回指旅程号）也**不做**（无下游消费者 = 第二真相源滑坡预备件）。③ **死锁自然消解**：§八 入口来自功能六件套，不依赖 e2e 环的索引页面表；「manual.md 页面列须按页面表路由」的前置依赖只在把 `manual.md` 当走查载体时才产生——不造该依赖，§6.2 **无需改软**；同批给 §6.2 补边界句（门只约束「本环不落笔用例」，不约束手工项登记）。④ **缺陷①（manual.md 无产出方）**：产出方 = **e2e 环**（页面表就绪后盘点落项，e2e §10 执行纪律 5）+ **验收走查现场新识别手工项授权人侧当场直写**（评审补的盲区——收口走查在 e2e 环收工之后，现场发现无授权落点会让缺陷①在运行时复发）。⑤ **存在性可见**：不采纳 issue 的「开户落空 manual.md」（零占位符 + 空文件不区分「评估过为 0」与「忘了」）；改双落地——控制台 `manual_state: missing` ⇒ meta 行显式「未创建」（**M73**：摘通道 ⇒ 用例红）；评估留痕落 **§5.4 收口走查留痕 README**（per-域持久、本来就要跑）的「手工项：N 项 / 已评估：0 / 待评估」行——**不发明 §11 新报告行**（「评估过没有」是 per-域跨时间状态，不是「每次变更」状态，语义不闭合）。⑥ **明示翻转触发器**：走查单确认门若在真实项目上连续挡住两批以上需求的 e2e 落笔（gates 台账可查）⇒ 重议改软。被否：issue 方案 A（manual.md 定为走查唯一正文——①拆掉「实现前看见流程」的功能 ②制造页面表依赖再拆门 ③为消灭伪冲突废真门）；issue 备选（删 B124「不阻塞」句——运行期控制台走查本来就构成不了落笔用例的前置，删了授权就没了）；全局改名（见 ①）。设计评审：tech-proposal-reviewer 子代理「修后采纳」——修正草案 3 处事实错误（validate_prd 取证来源、B124 段落指认 §10.1 非 §5.4、草案混入 RFC-02 的责任面段落）+ 指认评审漏掉的 `:176` 对照文本，v2 据此落地。 |
| D82 | 用例 ID 文法单源与 `PAGE` 段推导写全（2026-10-16，issue #14，评审修后采纳 + 用户拍板守卫形态） | ① **契约写全推导**：`rings/e2e/reference.md` §5.3 原只写「`PAGE` = 页面 slug 的**大写**」，多段 slug 没有解 ⇒ 补「**只做大小写变换、不做分段变换**」（连字符原样保留、不设收敛与 `slug → PAGE` 映射表），并给出机器可读形态。② **文法单源**：同文法体原在 `validators/validate_e2e_index.py` 与 `scripts/e2e_console.py` 两处各存一份（各自只支持单段 ⇒ 前者门恒红、后者映射取不到），经 `_support/case_id.py` 收敛为唯一实现；**锚点仍各留**（整格判定 vs 从生成产物取 ID 前缀，两者不是同一判定）。载体已就位（`_support` 已在装配白名单、`load_module` 已泛化查找、两消费方已 import）⇒ 新增 1 文件 + 2 处取用，不动装配与加载机制。③ **无裸正则普查钉**（`tests/test_tools.py`）：① 文法字面量持有者集合恰为 `{_support/case_id.py}`（新增消费者绕过单源自写裸正则 ⇒ 红）；② `CONSUMERS` 登记面 ⇔ 实况（假登记 ⇒ 红）。白名单局限留档（动态拼装扫不到）。④ **不新增报响门**：`node_ids` 取不到 node id 时下游已 409（非假绿）；立门会在「生成前的合法中途态」假红（`未就绪 ≠ 失败` 同族）+ 触 §12 先量。⑤ **模板占位符**给形态引导（`templates/e2e/{e2e-index,case-shard}.md`）。被否：纯同步钉（不共享实现 —— 把登记面内的漂移留给守卫；同语言的逐字节双拷贝在本包已有单源先例 `_support/case_block.py`，跨语言对才用同步钉 `test_f30…`）；收敛为单段（各读数实测碰撞或丢双射，且需新增映射表）；顺手统一 `AC_RE`（PRD 环明文禁止多段 `CODE`，单段是有意收紧）。变异：**M74**（单源文法退回单段 ⇒ 文法钉子红）/ **M75**（普查面内注入自写裸正则 ⇒ 普查钉红）；两枚还原逐字节一致。设计评审：`atlas-reviewer` 子代理（实例④；本决策属 §7 高风险 ⇒ 一律人工）—— 0 `Critical` / 2 `Major`（守卫形态的成本论证与源码脱节）/ 3 `Minor`（假选项碰撞证据、不升响理由、引用标识符），全部落地。 |
| D83 | 路由适配器**识别完整性**（两形态）+ 覆盖率出声（2026-10-16，`RFC-20261016-01` / issue #15，评审修后采纳） | ① **候选判据从「文件名」改成「内容」**：旧闸要求文件名含 `rout` 或父目录 `router` ⇒ 模块入口表（`index.*`）被**静默排除**（实测：11 个声明文件只扫到 1 个）；同文件对「常量路径」有 WARN（出声道具在手边）而候选闸无声 ⇒ 不完整的事实表冒充对账基准。② **JSX `<Route>` 形态无解析器** ⇒ 新增解析器（带**同文件嵌套深度栈**：`<Route path="a">…<Route path="b"/>` ⇒ `a/b`）。③ **覆盖率出声**：stderr 逐行 + 输出 JSON 增 `route_coverage`（契约正文登记在 `shared/stack-profile.md` §3.2）。④ **评审纠正的口径**：「模块相对路径」本身**不是原契约未履行的缺陷**——C 类只规定全站总表与行键口径，跨文件挂载推断属**新增能力** ⇒ 本项只承担缺陷面，能力面拆 D84。 | 
| D84 | 路由表**挂载前缀合成**（2026-10-16，`RFC-20261016-01` / issue #15，评审修后采纳） | ① **为何必须**：模块级表写的是**模块相对**路径（`/create`），而 C 类是全站总表、渲染行键是 `(应用, 页面/路由)` ⇒ 多模块同名路径被 `dedup_by_row_key` 折叠成**假事实**（不是少报，是多报）；故 D83 必须有 D84 兜住，否则连「放宽闸」这一步都不能做。② **口径**：站点表条目「路径 → 懒加载 / 导入的模块文件」即挂载关系；模块标识符 → 文件用「目录前缀命中 + **该文件也声明表**过滤，仍不唯一则未解析」（评审 F1：尾段字面相等恒不命中）。③ **歧义口径**（评审 F2）：入边 ≥2 / 成环 / 基名不可求值 ⇒ **未解析 + 计数，条目一律不产出**（宁缺不产假路径）。④ **站点级 vs 模块级用本地证据**（本文件是否挂载了自己的 router）而**不看 basename**——否则「别名解析失效」会被字面量 basename 兜住（缺陷不可观测），而「无入边 + 无 basename」的模块表会静默退化成站点级、把相对路径泄成全站路径（两条都是假事实）。⑤ **交叉自证**：模块自带字面量 basename 与合成前缀不一致 ⇒ WARN 并采用前缀（公开路径由挂载方定义）。⑥ **明确不收**：页内 tab 驱动的伪路由（不是路由声明，继续由 agent 语义撰写）。 | 
| D85 | 事实区渲染：**「写出 ⇒ 读回」不变式** + 渲染即自校（2026-10-16，`RFC-20261016-01` / issue #16，评审修后采纳） | ① **写侧单行化**：单元格换行 → `<br>`（**保行结构**，不用空格把成员粘起来——实测类型字面量会出现该形态）+ 裸 `|` 转义 ⇒ 逐单元格往返一致；此前多行取值把一行撑成多行，`parse_rows` 丢首行、跳续行 ⇒ 事实丢行 + 每轮判「新增」⇒ 漂移标记常驻、baseline 棘轮**永不释放**。② **`_norm` 把 `<br>` 与换行视作等价**（评审 F3：「键稳定」否则是无条件误断言）。③ **渲染即自校**（评审 F4）：对**渲染出的字符串**逐单元格比对，**与是否写盘解耦**（dry-run 同样出品）；不一致 ⇒ stderr WARN——取 WARN 不取硬错（`after_finish` hook 只告警不阻塞），真正会咬的门是同名单测。④ 存量自愈：下一轮 `--apply` 整块重写事实区，无需迁移脚本。⑤ 契约面：`rings/structure/reference.md` §6.2 接线前置补「渲染可读回」判据。 | 
| D86 | 装配面**三张表**同步：`package.json.files` 补 `tests`（2026-10-16，`RFC-20261016-01` / issue #17 附带） | ① **根因**：`install.sh` 拷贝列表含 `tests`、`pkg_digest.ASSEMBLY_COVER_DIRS` 也算它，但 `package.json.files` 不发布它 ⇒ npm 分发不含 `tests/` ⇒ 经 npm 全局包装配的项目**恒无** `.atlas/tests` ⇒ `atlas_check` 全量模式的包自检门恒 `FAIL`（退出码 4），而 `--fast` 一跑就 OK——采用者侧一道自己修不了的红（把红灯训练成噪声）。② **修法**：补 `files` 条目 + 给 F30 的守恒钉补第三条腿（`files` ⊇ `install.sh` 拷贝列表）。不采「`atlas_check` 遇缺就 SKIP」：那会把「装配面不完整」洗成「这一步没走到」（同族：把缺口伪装成合法降级）。**D91 收窄注记（2026-10-16）**：本否决成立于根因未修时——彼时采用者出路不可达（旧发行版装配不出 `tests`），SKIP 确属洗白；根因落地（本批 ①）之后，残余态「`.atlas/tests` 不在场」由 F53 前置判据记 `SKIP`（`RFC-20261016-02` D91，评审 B-1 处置）；**根因面（装配三表同步）不得改靠 SKIP 吸收，本条前半句维持不变**。 | 
| D87 | testid 契约共享元素**「一零件一名」** + 同文件**静态常量解析**（2026-10-16，issue #19） | ① **共享元素取名策略**：共享元素只取**一个** testid，页面段 = 归属页（`tid_owner`），**不随渲染页变化** ⇒「同一 testid 在多页渲染」合法——**唯一性判据 = 声明处计数，不是渲染点计数**；不采用「按当前页 slug 派生前缀」的模板机制作为共享元素的默认形态（前缀随页漂 = 第二真相源，机器判不出声明处归属）。② 「抽取器接受的声明形态」清单（4 类）+「常驻槽位口径」补反假绿条款：占位槽取「**与用例断言期望相反**」的态。③ **同文件静态常量解析**（`validators/validate_testids.py` 新增 `CONST_DECL` / `IDENT_TESTID_ATTR`）：`const X = 'a-b-c'` … `data-testid={X}` 与字面量**同档**——计入声明处计数（跨文件重名照报）、参与双向集合两侧判罚（孤儿照判）、同常量同文件引 ≥2 次计入同文件重复（WARN 指名）；**非静态初始化式 / 跨文件导入 / 未在本文件声明的标识符一律不解析**（宁缺不猜）。钉 4 条（`tests/test_validators.py` 94 → 98）。 |
| D88 | **应然落点**——应然 testid 的承载元素成为声明式、可机检的资产（2026-10-16，issue #20） | ① **背景（现场实证）**：应然清单取自 AC 文字，双向集合门只比「值集合相等」⇒ 一个**永不渲染的死字面量**就能把门凑绿而用例仍红（三条应然 id 有两条的控件在该产品根本不存在，门只能报「前端没这个字面量」，指不出「控件压根没有」）。② **契约 §5.5 新增可选字段 `落点:`**（`- <tid> <相对项目根的路径>`），分档：声明了但不对（文件不存在 / 文件内解析不到该 id）= **假陈述 ⇒ FAIL**；未登记 = 纪律缺口（存量过渡）⇒ **WARN**；§5.1 字段表同步，`_support/case_block.py` `_BLOCK_KEYS` 增 `落点`（单源解析器是其唯一入口）。③ **抽取面单源化**：`file_testid_decls(clean_text, pages)` 把「单文件可解析的 testid 声明」抽成唯一实现（静态字面量 / 同文件静态常量 + 单层引用 / 可枚举模板 / 命令式注入），`collect_testids_expanded` 与落点门共用（防「抽取器看到了、落点门看不到」的半通）；`shard_landings` 按 `tid_owner` 归页（与 `shard_testids` 同规）。④ **顺带修同族缺陷**：`case_testid_usage` 原为手写行扫描（只认 step / expected / testid 三个小节键）⇒ 新增数组键会把条目误吸进 testid 集合（实测：命名规范把 `<tid> <路径>` 当违规名报），改走单源 `parse_block`。钉 4 条（98 → 102）。 |
| D89 | **会话前提「会话:」通道**——宿主注入型会话态可声明·可隔离·可机检（2026-10-16，issue #13） | ① **背景**：有类需求的被测属性本身就是「会话被宿主以注入参数载入 ⇒ 界面呈相应形态」（身份 / 租户 / 管控 / 灰度类）。契约原无通道（`goto` 带 `?` 即 FAIL、`auth` 只管登录态、`seed:` 绑数据实体）⇒ 只能写散文 precondition，断言在初始态即成立 ⇒ 撞 §5.6 R9 恒真禁制，两条豁免通道都不适用。② **契约 §5.5 新增可选字段 `会话:`**（`- <键>=<值>`）：**前提构造，等同 step**；编译为首屏导航**前**注册的 `addInitScript`，写入 **`sessionStorage`**（非 localStorage：`storageState` 只覆盖 localStorage，且它跨标签页/跨用例持续 ⇒ 污染后续用例——含「不传参 ⇒ 保持可用」对照用例钉）。③ **与 R9 的关系**：零步基线**不施加** `会话:` ⇒ 依赖该前提的断言在基线不成立，R9 自动满足，不必也不得借 `initial:`。④ **取值优先级**：用例声明值兜底，运行期 `ATLAS_SESSION_<键>` 优先覆盖；两者皆空 ⇒ 运行期报错中止。⑤ **键白名单 = stack-profile 的 `e2e.session_preset.keys`**：白名单外 / 未声明 ⇒ 文本期 FAIL + 生成器中止（双保险）；白名单是项目级声明，正是 §5.7 禁令的边界落点——会话 / 身份 / 权限 / 灰度类注入键是前提（同 `app_login`），数据实体状态仍只能用真实界面动作达到。⑥ profile 解析补**块列表**形态（`<键>:` + `- 项`，惰化物化 ⇒ 既有 profile 零变化）。钉 8 条（校验器 4 / 生成器 4，含「零步基线测试体不得出现 `atlasSessionPreset`」）（102 → 106）。 |
| D90 | **守卫: 路径**——带参页面的元素齐全守卫不再导航到匹配不上的地址（2026-10-16，issue #23） | ① **背景（两条条文合取后不可用）**：§3.1 明定页面表 `路由` 列取**业务段**（`/x` 而非 `/x/:id`），而生成器 `page_urls()` 把该列当**唯一** URL 来源用于用例体开头的**元素齐全守卫**导航 ⇒ 带参页面的守卫落到路由匹配不上的地址，页面不渲染 ⇒ 守卫 goto 后即红，用例自身的带参 `goto` 来不及生效；同一列还被 §8.2 的「goto 路径 ∈ 页面表」门当**前缀锚**用 ⇒ 一个字段被两种**相反**语义的用途消费。② **契约 §5.5 新增可选标量键 `守卫:`**：值 = 一条具体路径，守卫导航改用它；**缺省回落页面表路由 ⇒ 对无参页面逐字节零变化**。③ **新门行「守卫 路径 ∈ 页面表」**：值须命中页面表 `路由` 列（口径同 §8.2：精确，或非根路由的子路径前缀命中）；判定抽成 `_route_hit()` 与 goto 路径门**共用**（同一套口径，不两处各写）。④ **零步基线仍用页面表路由**（本字段是用例级、基线是页级产物）；基线在带参页探不到元素时按「null = 不成立」处理，不产生假阳性。⑤ **实现坑（已记入内核注释）**：`守卫` 是标量键，**不得登记进** `_BLOCK_KEYS`——该元组内每个键都初始化为 list，入了就变数组（实测 `'list' object has no attribute 'strip'`）。钉 4 条（校验器 2 / 生成器 2，含零变化承诺的 diff 证明）（106 → 108）。 |
| D91 | `atlas_check` 包自检门的**前置降级**：缺 `.atlas/tests` 记 `SKIP`（2026-10-16，`RFC-20261016-02` / issue #17 残余，tech-proposal-reviewer 评审「有阻塞问题」修后采纳） | ① **残余面**：D86 修根因（分发表补 `tests`），但 `check_factory`（`scripts/atlas_check.py`）无前置判据——存量装配（beta.17 及以前发行版的 npm 装配态）与源包开发态（仓根无 `.atlas/`）仍 pytest exit-4 恒红 `FAIL`，且全量恒红 / `--fast` 恒绿两相反结论并存（issue #17 本体：「红灯训练成噪声」）。② **定案**：前置判据「`.atlas/tests` 不是目录（含路径被文件占用的装配损坏形态——评审 M-1，判定一道覆盖不对在场者谎称「未找到」）⇒ `SKIP` + 两层文案（判据面 = 实测路径 + 三形态点名：旧发行版装配态 / 源包开发态 / 装配损坏；出路 = `pytest tests`（源包）+ `install.sh` / `atlas upgrade`（重装走齐）+ pytest 可用性提示——评审 m-3/m-2 的动作词齐组进钉）；目录**在场** ⇒ 行为逐字节不变，真红仍 `FAIL`（反面钉 A-2 防「把真失败一并降级成 SKIP」）。③ **与 D86 的收窄关系（评审 B-1，阻塞件）**：见 D86 ② 的 D91 收窄注记——D86 的否决只在「出路不可达」时成立，根因落地后 SKIP = 合法降级（本仓章程）；**装配面根因永远不得改靠 SKIP 吸收（F47 三表同步钉维持）**。④ **盲区显式化而不改判据（评审 M-2/m-4）**：pytest 解释器可用性（无 pytest ⇒ `FAIL` 指名，环境缺失可自修）与「目录在场但零用例 ⇒ `no tests ran` 仍 `FAIL`（装配损坏值得查）」两条不进机器判据，落 `gates.md` 2.2 行「不查什么」列。⑤ 被否：缺目录记 `ok`（把「未走到」伪装成「走过且绿」）；`WARN`（性质是「没跑」不是「跑过、判据不咬」，混污染真 WARN 语义）；挪进 `--fast`（丢真实自检能力且门行同样缺席）；装配时打印「包自检需在源包跑」（issue 原后半句——常装配 = 常态噪声，吸收进 SKIP 文案的出路层）。变异 **M76**（前置分支摘除 ⇒ `test_f53_factory_gate_skips_when_tests_dir_absent` 红；还原逐字节一致）。`tests/test_atlas_check.py` 22 → 24 条。 |
| D92 | 装配器版本戳挂**干跑闸门**——「干跑不产生装配态变更」（2026-10-16，`RFC-20261016-03` / issue #21，tech-proposal-reviewer 评审「修后采纳」） | ① **病灶**：戳写入是 install.sh 全脚本唯一的裸写（run() 外、无 DRY_RUN 判据），守卫挂 `[ "$DRY_RUN" -eq 0 ]`（预览语义，合理）⇒ `--update --dry-run` 一次（守卫放行、载荷未拷、戳却更新为源包当前摘要）+ 一次被守卫拒住的真跑 = 副本「戳新/内容旧」，被装配版本门（**自写自读闭环**，只比戳与源包摘要）报 ok「一致」——对账门被干跑洗成假绿；干跑**首装**还经 `stamp_file` 的 mkdir 残留 `<target>/.atlas/`（未上报同族面，评审 A-2），卡随后的真首装。② **定案**：戳写入块整体挂 `DRY_RUN` 判据（干跑只出声 `[dry-run] 装配版本戳（未落盘）`）；真跑路径逐字节不变（落戳仍最后一步、失败仍 F37 硬错）；不采「包进 run()」——run 只对子命令生效，对裸 heredoc 管段属假闸门。③ **不采**（issue 建议③）：给装配版本门加副本内容抽检——摘要算法口径为**源包布局**而立，副本清单口径（副本本地改动 / VERSION 自环 / `__pycache__` / `runs/`）未立案就上判据 ⇒ 回灌批在路即 WARN 风暴，留待独立 RFC。变异 **M77**（摘干跑闸 ⇒ `test_f54_dry_run_writes_nothing_and_leaves_no_residue_on_fresh_target` 红；还原逐字节一致）。 |
| D93 | 脏树守卫按 porcelain **状态列分两语义**——已跟踪未提交改动 ⇒ 拒，触点整目录未跟踪 ⇒ WARN 放行 + 双摘要可见化（2026-10-16，`RFC-20261016-03` / issue #22，评审「修后采纳」） | ① **病灶**：守卫只读路径列（`cut -c4-` 後判 `case`），`.atlas/` 整目录未跟踪被 porcelain 折叠成 `?? .atlas/`、`.atlas/*` 判据照命中 ⇒ 守卫恒拒 ⇒ `--force` 被逼成常规、主力语义（护已跟踪的未提交改动）被噪声淹没时反照失效。② **定案**：守卫读整行，XY 列分桶——`??` 进 `UNTRACKED_TOUCH`，其余进 `DIRTY_TOUCH`；`DIRTY_TOUCH` 非空 ⇒ F34 行为逐字节不变（`--force` 越过，文案保留）；`UNTRACKED_TOUCH` 非空且 `DIRTY_TOUCH` 为空 ⇒ WARN 放行，文案**双摘要可见化**（副本 `.atlas/VERSION` 首行 ⇔ 当前源包 `pkg_digest` 摘要，同录出声）+ 出路先行（ATLAS-UPSTREAM.md / `backflow.py`）；两桶皆非空 ⇒ 拒优先，拒通知并录未跟踪项。`--force` 语义未漂移：仍 = 越过拒绝的 exceptional 头寸。③ **评审 B-1（major）取舍**：其首选「戳相等才放行、不等/缺回落拒」不采——npm 升级链路最常见形态恰是「未跟踪且已过期」（副本旧发行版装配、源包已前进）⇒ 每次合法升级被逼 `--force` = **issue #22 病灶复现**；采纳下限 = 双摘要可见化让丢失风险出声，而非把风险藏进恒拒；「未跟踪 ⇒ git 无基线 ⋯ 本就不在守卫主语义的护力范围内」留档。④ **不采**：porcelain v2（触点全 ASCII、rename 前缀保守命中）；项目级「装配目录不入库」开关（porcelain 状态列已携带全部所需信息，不造第二份声明）；「未跟踪必答确认」（= `--force` 改名常规化）。变异 **M78**（未跟踪桶改指脏桶 ⇒ F55 钉前半红；后半为 F34 回归钉非变异钉；还原逐字节一致）。`tests/test_install_selfcheck.py` 7 → 9 条。 |
| D94 | 行内 `#` 注释剥除**收敛为单源出口**（内核 `strip_inline_comment`），守卫门自带剥注释（2026-10-16，issue #R1 + #R3，I3） | ① **病灶**：同一 `atlas-case` 块内口径分裂 —— 列表项由消费侧 `parse_line` 的 `partition("#")` 剥（「机器只看 `#` 之前」），**标量键不剥**（`_support/case_block.py` 的 `d[k] = v` 分支）⇒ `守卫:` 值把注释整段当值，又作为 JS 单引号字面量发射（`page.goto('/x   # 说明')`），且路径门的前缀命中口径把「合法前缀 + 尾随垃圾」判 PASS ⇒ 无门可见；`validate_e2e_index.py` 另有多处手写 `split("#", 1)[0].strip()`，而守卫门**完全不剥**。② **定案**：`case_block.py` 的**标量分支**改经内核 `_support/stack_profile.strip_inline_comment`（经包内 bootstrap 取用；**不**新增第二份实现 ⇒ `test_definitions_are_single_sourced` 与 `is` 同一性钉同时咬合）；**列表项逐字节不变**（其 `#` 是给人读的 note，由 `parse_line` 单点消费）；校验器多处手写口径收敛为同一函数对象；**守卫门内取值路径**（`:684-687`）自带剥注释（F3，上下游双保险）。③ **能力边界（不 oversell）**：F1/F3 **不**关闭「合法前缀 + **无注释的真垃圾尾**」（`/x/1/FUZZY` 仍 PASS）——那需要「值形态」判据 + 契约增量（`:285` 的前缀口径属**有意设计**，单独收紧会把合法带参路径打红），登记为独立待办；前缀命中口径**不动**；`validators/validate_e2e_index.py` 既有的 `_code()`（按任意 `#` 截断）与其余文本期门仍在本次收敛面之外，登记为残余。④ **不采**：契约层「块内注释只允许出现在列表项」+ 门拒绝（把合法的给人读注释当违规，且要改全部存量分片）。变异 **M83**（标量分支还原 `d[k] = v` ⇒ 内核钉红）/ **M84**（守卫门摘 `strip_inline_comment` ⇒ 门钉红）；还原逐字节一致。 | **⑥ ③ 的残余已清偿（2026-10-17，issue #30 收尾批）**：`validate_e2e_index` 的 `_code()`（`line.split("#", 1)[0].strip()` = 第二份口径）与其**9 处**内联 `split("#", 1)[0]`、`gen_e2e_scripts` 的 **3 处**同类、`_parse_mock_line` 的 `partition("#")`、`initial:` 理由检测的 `partition("#")`（撞路径里的 `#` ⇒ 把路径尾巴当理由 = **假「有理由」**）全部改走内核 `strip_inline_comment`；`e2e.reset` 取值清洗的 `.strip("\"'")`（两端同剥 ⇒ 吃掉结尾引号）改为只剥**成对**引号（`_reset_command`）。钉：**结构钉**（行解析器的代码行里不得出现 `split("#"`）+ `initial:` 假理由双侧 + `_code` 保真 + `_reset_command` 行为；变异 **MB8**（`_code` 退回 split）· **MB9**（`_reset_command` 退回两端同剥）两枚咬中、还原逐字节一致。**残留**：无（D94 ③ 字面全真）。 | **⑦ 值形态判据 —— 判接受（非待办，2026-10-17 独立评审）**：前缀命中的「合法前缀 + 垃圾尾」假 PASS 通道判**接受**：① 无现场实例（全仓仅 ③ 自陈的理论例）；② 前缀命中是 `rings/e2e/reference.md` §8.2 **契约有意设计**（带参页面友好），单独收紧会误伤合法带参路径；③ 唯一可行的收紧（structure 事实派生值形态）会引入**跨环第二真相源**（撞 `reference.md:470`「页面 URL 唯一来源 = 页面表」）并需重写规范化规则 ⇒ 成本/风险高于收益。**本项登记为「已知边界（明示接受）」，不是未修缺陷 —— 下次巡检不得重报。** 不做案 A（字符白名单）。**明确不成立的兜底理由**：「真跑 404 ⇒ 元素守卫必红」**不成立** —— 壳层 testid 也在页面应然清单（`reference.md` §3.2）⇒ NotFound 在壳内渲染时守卫仍绿；且真跑在地址空 / 靶场不可达时 `SKIP`、`blocked` 不可执行、D103 人工会话不可复现（评审 MUST）。**升判口径（维护者，非自动）**：仅当维护者拍板，按「**页面表路由自派生壳前缀 + structure 事实仅作 `:param` 段数佐证**」立项；**不设**「出现实例即自动升判」。评审记录：`proposals/REVIEW-2026-10-17-route-value-form.{md,json}`、方案 `RFC-20261017-03`。 |
| D95 | 元素齐全守卫的 id 面 **回归契约正文**（`reference.md` §7.1「每条用例的 `testid:` 清单守卫」），空表不再静默吸收（2026-10-16，issue #R2/#R2'，**行为恢复**） | ① **病灶**：守卫面取自 `case["step"][0]`（commit `b18df53` 把 `case["testid"]` 应然清单**替换**而来）⇒ `goto` / `refresh` 首步无 testid ⇒ **守卫恒空**（`for (const id of [])` = 守卫消失），而解死锁的专门机制契约早已给出（§4 常驻槽位「动作产物元素以 **hidden 占位槽**满足『用例开始时 count=1』」）——实现绕过了既有机制。② **定案**：`ids = json.dumps(case.get("testid") or [])`；**尺子重定向**（不删断言）：原把「空表」钉成期望的 `test_guard_only_watches_first_step_target` 改为断「守卫面 = 该用例 `testid:` 应然清单且非空（含动态项）」，另立新钉「首步为 `goto` 的用例 ⇒ 守卫面非空」。③ **已知代价（显式登记，不静默）**：这是**对采用方的行为恢复**，非纯 bugfix——未被契约合规（无占位槽）的动态元素会开始真红，那是正确反馈；`validate_testids.py` 的「应然落点 / 常驻槽位」门是静态侧前置拦截，二者互为双保险。变异 **M79**（守卫面改回 `first_step_tids` ⇒ 新钉红；还原逐字节一致）。 |
| D96 | `click` / `hover` 的 **`{ force: true }` 默认写进契约** + `native` 步级开关（2026-10-16，issue #R4，契约 `rings/e2e/reference.md` §5.5） | ① **病灶**：生成器对 `click`/`hover` 无条件追加 `{ force: true }`（跳过 *receives events / stable* 检查），而环契约内 **0 处**记载 ⇒ 对「某控件不可交互 / 置灰点不动」这类**被测属性本身**，该属性无法被证伪；动机只留在 CHANGELOG ⇒ 「产出与依据」脱节。② **定案**：契约 §5.5 的 `click` / `hover` 条目补——**缺省 `force: true`**（动机：遮罩 / 动画 / 父容器拦截造成假红）+ **适用边界（硬）**（被测属性 = 可操作性 / 不可交互 / 用户不可达的用例**不得**依赖该默认）+ **步级开关** `click <tid> native` / `hover <tid> native`（不追加 `force`，保留 `.first()` 的 strict-mode 修复）+ **值域封闭**（第三位仅 `native` 或缺省，其它值 ⇒ 校验器 FAIL + 生成器报错中止）。③ **不采**：撤销默认 `force`（遮罩类假红是更常见的病灶，收窄 = 把常态逼回假红）；全局关闭开关（粒度应是步级 —— 同一用例内两种需要可共存）。变异 **M80**（`step_force_arg` 恒返 force ⇒ `native` 钉红）/ **M81**（值域判据摘除 ⇒ 坏值钉红）；还原逐字节一致。 |
| D97 | `testid:` **项**带行内注释时「纯在场守卫豁免」静默失效（2026-10-16，issue #R1 同族未爆现场 S1，`tests/test_gen_e2e_scripts.py` 钉子） | ① **病灶**：`gen_e2e_scripts.py` 零步基线探针的 `case_testids = set(c.get("testid") or [])` 用**未剥注释**的值，而紧邻的 `step_operated_testids` 走已剥的 `parse_line` ⇒ 集合比对碰带注释项即静默不命中（F24 规则二的「纯在场守卫豁免」判据失效，无任何机器面可见）。② **定案**：`case_testids` 逐项经**同一** `strip_inline_comment`（I3）；行为等价性由钉子证明（无注释时集合逐元素不变）。③ **不采**：改 F24 规则二判据口径（报告的是**解析层**缺口，不是规则问题）。变异 **M82**（`case_testids` 改回未剥 ⇒ 钉子红；还原逐字节一致）。 |
| D98 | E2E 动词 **`dispatch`**：合成事件直发成文（2026-10-17，v3 真跑 004 复跑复现驱动，用户拍板采纳） | ① **病灶（force/native 双灭）**：v3 便利贴表面常态遮罩 + 新增入场动画——`force` 点击在连发窗口被吞（期望 2→1，5s 轮询纹丝不动，二跑复跑复现）；`native` 因可点性检查永不过而**整用例挂死**（三跑/四跑实证，点选与删除两个 testid 均遭遇）⇒ 现行点击二模在该表面表达不出「等稳定」（固定 sleep 被契约明禁、`waitFor` 只能等可见而元素恒可见）。② **定案**：`dispatch <tid>` = `dispatchEvent('click')` 直达 React 合成事件 handler（绕 hit-testing / 可点性检查的整面；预置脚本的 `dispatchEvent` 为运行先例；黑盒探针实证**动画窗口内 0 节拍直发两删连中**，同一窗口 force 全灭）；不追加 `force`（绕行本义，无此概念）；**适用边界（硬）**与 `native` 同家族——被测属性 = 可操作性 / 不可交互 / 用户不可达的用例不得用（可点性绕过 ⇒ 该属性无法被证伪）；**值域封闭**：无第三位，出现任何取值 ⇒ 校验器 FAIL + 生成器报错中止——兼职治当日实证的「旧安装副本对陌生第三词静默吸收」（.atlas 副本无 D96 时 `native` 不生效也不报错）。③ **被否**：固定 sleep（「固定等待在共享靶场必飘 ⇒ 假绿通道」原有口径不变）；产品侧 settle（去留由维护者对 spark-flow 自行决，本条不约束产品）；把连发 add 重排成串行（相邻步仍零间隔，无立足点）。④ **发射/值域钉**：`tests/test_gen_e2e_scripts.py` 动词样例守恒表 +1 词条 + `test_dispatch_verb_emits_synthetic_event_without_force` +1（直发形态 + force 不沾 + 第三位 ValueError）；`tests/test_validators.py` `dispatch` 值域门 +1（gates 行计数 **112 条**已同步）；变异 **M87**（摘 dispatch 发射分支 ⇒ 发射钉红，还原逐字节一致，sha `348d8316…`）。设计依据 = v3 三跑/四跑 error-context + 探针（/tmp，不合入）。 |
| D99 | `stack-profile.yaml` 字段集**定稿**（2026-10-17，巡检决策队列**案 2** 维护者拍 A——「等 v3 切片全绿日一次定稿」） | ① **冻结口径**：以**现行实现实收面**为 v1 基线——读取面 = `_support/stack_profile.py`，声明面 = `shared/stack-profile.md` §3（两侧正本对账即为清单）；**此后新增 / 删除字段一律起独立决策行**（D80/D89/D90 先例路径），「草稿」语境退役。② 文档 / 模板存量「以草稿为准」措辞**随触碰顺手清**，不专项发扫（最小动作）。③ §14 首行由本行承接退役。④ 被否：两栏制（稳定字段 / 活字段分列）——冻结后再开「活」栏 = 给字段集开第二真相源（D86 同族教训）；现在冻结字段本身（切片全绿前字段还在被真实场景加压，冻结会立刻吃变更流程）。 |
| D100 | git **pre-commit 校验兜底不启用**（2026-10-17，巡检决策队列**案 4** 维护者拍 A） | ① **定案**：校验兜底维持显式跑——`pytest tests/` 全量 + `scripts/atlas_check.py` 前闸；pre-commit 不上；启用留待 CI 一起落（本行同步收口 `DESIGN.md` §14 悬案原第二行 + 属 D72 ④「CI 分级与回滚延后（依赖 B4）」的前置形态）。② 被否：**pytest 最小钩**——多会话并行开发下「跳过验证直接提交」的窗口真实存在，维护者明示接受该风险：批次闭环的全量测试纪律（CHANGELOG 各批带测试计数）优先于提交时延。③ 载体口径（factcheck v2「硬条款必须指名载体」）：现行校验的载体 = **显式跑纪律**，pre-commit / CI 是未来形态——不假装已是门。 |
| D101 | node 轨运行器判据**换本体**：从「可执行文件存在」改为「`@playwright/test` 可解析」，全局兜底改为**可生效的修复**（2026-10-17，issue #24；现场 = 百炼/v2前端真跑准备日） | ① **病灶**：判据写在两处（`scripts/atlas_check.py` + `scripts/e2e_console.py`，连 `_is_node_playwright` 都是两份拷贝），且两处都只问「binary 在不在」；而 `shared/gates.md` 2.2「E2E 真跑」行**早已写明**「解释器按**依赖可导入性**选（不按路径存在）」——是实现漂离了已落口径，**不是设计选择**。ESM 项目（`package.json` `"type": "module"`）上暴露为**半生效**：全局兜底（F19）找得到 binary，但 Node 的 ESM 解析器**不读 `NODE_PATH`**（该通道属 CJS）⇒ `@playwright/test` 解析不到，错误落到运行期（`Cannot find package '@playwright/test'`），且被门计成「跑失败 / 无结果」——**真原因不可见**。② **定案**：判据本体 = 「**从 `e2e.scripts_dir` 出发 `@playwright/test` 可解析**」（探针 = `node --input-type=module -e "import('@playwright/test')"`，解析基准 = cwd，本机实测），解析 / 探针 / 修复**全部收敛到 `_support/pw_runner.py`**（`_support/` 单源惯例，消除两份拷贝）；修复手段 = **幂等软链**（本机实测能让 ESM 解析生效、且不把全局版本混进项目依赖的唯一通道），且只在 `source == "global"` 时发生——项目自装目录里缺模块是**项目自身缺口**，给软链会把全局版本混进项目依赖（版本漂移源）⇒ 不修只报；软链落点 = **Node 从 scripts 起向上搜索的首个 `node_modules`**（声明的 `e2e.node_modules` 是二进制所在目录，**未必在搜索路径上**）。③ **档位（同一判据、两种反应——判据本体单源，反应面正当分叉）**：门 = 不成立 ⇒ `FAIL` 点名真原因；全局兜底修复成功 ⇒ **降 `WARN`**（跑得起来、但结论依赖**机器全局状态**、非项目自足——不假装 `ok`，也不把有确定性补救的事判红成噪声，§§「红灯训练成噪声」旧教训）；执行器 = 修复 + 复检 + **输出「用了全局什么」**，修不好 ⇒ 起跑前诚实拒绝（不起注定失败的子进程）。④ **被否**：`NODE_PATH` 继续当判据（ESM 下无效）；链接位被占时覆盖（= 替人删文件）；把「用了全局」做成**一次性事件**（它是**跑的前提事实**，每次结论都该降档 / 输出 ⇒ `global_note` 与「本次是否动手」解耦）；项目自装缺模块时也给软链（版本漂移源）。⑤ **发射/值域钉**：`tests/test_atlas_check.py` **24 → 25 条**（+`test_check_e2e_module_unresolvable_fails_loudly`：坏输入 ⇒ `FAIL` 点名「依赖可导入性」；`test_check_e2e_global_playwright_detected` 由假 `ok` 改钉 **`WARN` + 行内写明全局与软链 + 幂等再跑**），`tests/test_e2e_console.py` **+3**（修复合规路径 / 无全局如实拒绝 / 链接位被占拒绝覆盖）；同批顺手补 `install.sh` 对 `_support/case_id.py` 的装配自检（存量漏登记：包内件一直在装配面上、却不在自检清单 ⇒ 自检 44 → **46 条**）；变异 **M88**（判据退回「binary 存在即 ok」⇒ 门侧坏输入钉红）/ **M89**（摘软链步 ⇒ 执行器侧修复钉红）/ **M90**（摘 `global_note` ⇒ 降档与输出齐红），三枚咬合、还原逐字节一致。设计依据 = 百炼/v2前端现场（`product/e2e/scripts` 下 `playwright test --list` 报 `Cannot find package '@playwright/test'`；加 `NODE_PATH` 仍红；补软链后 10 条用例可收集）。 |
| D102 | 复发**自动可见**（DR4 口径 B：段级族规模 × 活跃窗）+ 「**可执行性判据本体**」写成流程门（2026-10-17，维护者拍板选项 **B**；承接 issue #24 / D101 的复发信号） | ① **病灶**：D101 那条属「**判据可被形态满足**」族（`#1/#4/#6/#7` 首批，beta.17 修过一轮；`#20`、`#24` 两轮复见），而 DR4「同类 ≥3 次 ⇒ 需立机器门**或契约条款**」的判定**此前全凭人工裁量**——族规模没人算、复发靠撞见。同日已落**口径 A**（fix 类提交触达路径 30 天 ≥3）判**复发速率**；**口径 B 补族规模**：聚类单元 = `duty-review/bugs.md` 的**段 + 段首「同根归纳」行**，计数 = 段内 `#NN` 去重（**上界近似**，含交叉引用），**升室判据 = 同根归纳在案 ∧ 案数 ≥3 ∧ 段内最近日期落在近 30 天**（三项齐 = 这族**近来还在长**）⇒ 巡检输出一行「升室候选」；只满足前两项 ⇒ 记「族已静默」**不升室**（同一族清算完还天天喊 = 把红灯训练成噪声，本仓旧教训故设活跃窗）。② **契约条款（语义项，不假装是门）**：`shared/gates.md` 2.5 新增「**可执行性判据本体**」流程门——判据必须问「**能不能真的用**」，不得以「东西在不在 / 文字写没写」代替；这类前置判据（运行器 / 解释器 / 依赖模块 / 外部工具）须具备 ① 一次性功能性探针（真跑一次：import / `--list` / dry-run）② **反面包**（东西在、但用不了 ⇒ 必须红）③ 失败原因**不得被吞**；**明示不设机器判据**（`3509 §96` 口径），给写门者与独立审查一把尺子，附人工追问清单三条。③ **为什么不做通解**：判「判据 ≠ 它要保护的性质」要读**意图** ⇒ 语义，机器判不了；硬立通用门 = **用可被形态满足的门去治可被形态满足的病**（同族递归）。故本决策刻意只做「让复发被看见 + 给写门一把尺子」，并如实记录：该族复发**都发生在老门老代码上**（纪律只覆盖「新增/修改门」那一刻）——机器门治不了「没人回头看」。④ **被否**：立通用机器门（同上）；只按「有没有探针调用」这个**形态**判（写个假探针即过）；口径 B 不带活跃窗（落刀后实测：4 段全被点名，其中 structure 段是**无活跃案的历史族** ⇒ 噪声，故加窗）。⑤ **落地与实跑**：口径 B 的实现抽为**单源模块** `duty-review/families.py`（原稿是 shell 内联 python —— 本仓大忌：无钉、形状一漂即**静默归零**，而静默归零恰好让本机制要治的「复发靠撞见」原样回来）；`scripts/duty_signals.sh` 改为调它（只读、不落盘；实跑 = **3 族升室候选**（E2E 14 案 / 安装与装配 3 案 / 自感知 8 案，均有 2026-10-17 新案）+ **1 族自动静默**（structure，无日期取证））；钉 = 新增 `tests/test_duty_bug_families.py`（4 条：解析面 = 文件面 / 真实库数得出族规模 / 判定真值表 + 活跃窗边界（日期**正好** = cutoff ⇒ 仍活跃）/ 空输入不炸），变异 **M91**（计数正则从段内全文退回行首 ⇒ 静默归零 ⇒ 钉红，还原逐字节一致）；`duty-review/README.md` §2 DR4 补口径 B + §4 信号面**指名单源实现** + 口径 A 显式标注；
| D103 | `e2e.app_login` **不开第四形态**：不可自动预置的靶场走「**人工会话取出**」**描述路径**（2026-10-17，维护者拍板；承接 issue #26 / QUEUE 案 7） | ① **现场**：靶场**有访问门**但三态**都装不下**——图形验证码（`login_captcha`）+ 服务端 **cookie 会话**（`COOKIE_JSESSIONID`）+ 登录**响应体无令牌**（`data` 是 URL 串）⇒ **无形态可声明**，而 `validate_stack_profile` 的 WARN 只说「请声明」= **死胡同**（编号 #26 已出库；取证见本行 ① 的现场描述）。② **定案（维护者原话：「我想让 ai 主动给人生成这种类似的命令」+「不用非要机器门吧，描述不是也可以」）**：**不加字段、不加门**，落**描述 + 出路文案**——`rings/e2e/reference.md` §7.1 增「人工会话取出（描述路径，非机器门）」节：AI 主动给人 `playwright codegen --save-storage=<e2e.scripts_dir>/.atlas-auth/state.json "<e2e.app_base_url>"`，人登录一次；**四条纪律**（关窗才落盘 / 会话短命令要立即跑 / `<scripts_dir>/.gitignore` 已含 `.atlas-auth/` 且生成器 setup 有**幂等守卫**（无凭据 + 已有合法 state ⇒ 保留，不覆盖人的会话）/ 它是**运行期凭据不是应然资产**）；`shared/stack-profile.md` §2 `app_login` 行注明「**三态之外不设第四态**」；`validate_stack_profile` 的 WARN 由「请声明」改为**给出路**（含命令原型，钉 `test_stack_profile_login_unstated_warn_gives_a_way_out` + 变异 **M93**）。③ **对 D80 ② 的注记（显式登记，不静默）**：D80 的「段缺失不再是合法降级 ⇒ 升档 = `not_ready: app_login`」与本行**相抵于一类项目**（有门但无形态可声明）——该升档落地时**须先把这一类排除**，否则会把「如实未声明」罚成 not_ready（`gates.md` 2.2 行已登记该相抵点）。④ **被否**：补第四形态 `manual` / `session_import`（= 契约增量四处同改 + 把**不可复现**固化成标准姿势；当前只有一个项目撞到）；把这类靶场塞进 `real`（一个形态说两件事）；用 `mode: none` 充数（与事实相反）。⑤ **能力边界（不得 oversell）**：该路径**不可复现**（每轮要人登录 ⇒ CI 上不可用）、会话短命 ⇒ 是**兜底**而非 `app_login` 的替代形态；**无机器判据**，如实登记为纪律与盲区面。设计依据 = 百炼/v2前端真跑准备日现场（登录表单三字段 + cookie 会话取证；真跑门已能跑到用例，三条红全在未登录态）。 |
| D104 | **宿主注入型 base query 由生成物转发**（`e2e.app_base_url` 的 query 带到每一跳）；路由列保持**路径形态**（可含 `#`）（2026-10-17，维护者拍板「先 2 后 1」+ 两轮独立评审通过后落刀；issue #27） | ① **病灶**：某类应用把宿主注入的前提（tenant）**只从 `window.location.search` 读**（无 sessionStorage 回落）⇒ `会话:` 通道（`D89`，sessionStorage）**送不到**；`goto` 又不得带 `?`（§5.7）；而 base 一旦带 query，**绝对路径会丢 query**（`new URL('/console/#/x', '…?switchAgent=7202')` ⇒ query 消失）。三条各自成立 ⇒ **无合法写法**。② **被否的第一案（A）**：让页面表 `路由` 允许 hash 相对形态 `#/…`（`new URL('#/x', base)` 能保住 base 的 path+query）。**落刀时被实测推翻**：`.atlas-case` 里 `goto #/…` 的 `#` 前有空格 ⇒ 按 `D94` 的行内注释语义被截断成 `'goto'`（`守卫:` 标量同样）⇒ **该值形态物理不可写**；救它要改 D94 刚收敛的共享注释语义，回归面过大（`proposals/RFC-20261017-01` §9.1）。③ **定案（B′，评审建议的「生成期纯函数变换」而非运行期助手）**：路由列保持**路径形态**（`/console/#/app/agent/detail`；`#` 紧邻 `/` ⇒ 不被注释语义吞）⇒ 上一轮评审的四处消费者（validator `page_rows`/`_route_hit`、生成器 `page_urls`、控制台 `page_routes`）**无需改动**（形态换成 path-form 后全命中）；改由**生成期**把 base 的 query 并进**三处**导航发射面（`step` 的 `goto` / 元素齐全守卫 / 零步基线 `data.url`；单源 `_support/url_merge.py`，与评审 MUST 的「三处不是一处」对齐）；控制台手工「打开」的地址构造同步修正（**第五消费者**，旧 `base + path` 在 base 带 query 时产畸形 URL）。④ **口径（三条，写进 `rings/e2e/reference.md` §5.5）**：base 无 query ⇒ 生成物**逐字节零变化**；`ATLAS_BASE_URL` **只覆盖 host、不覆盖 base 的 query**；**边界明示**——base query 成为前提后，「它缺席时」的行为**无法用同一份用例表达**（`会话:`/`auth: none` 不在同一消费面、不构成逃逸口），该场景超出契约范围，要 opt-out 须另起决策行（触 `D99` 字段集冻结）。⑤ **被否**：`会话:` 扩「URL 参数档」（触 D99 + reload 打断 SPA）；运行期 TS 助手（要反取 `test.info().project.use.baseURL`，隐式脆）；把「同名键以目标为准」写成生效口径（§5.7 下目标永无 query ⇒ 不可达死条款，只保留为扩展位）。⑥ **钉与变异**：值保真（`/console/#/…` 在 case 块可写 + 两道门 PASS）/ 三处齐并 / 无 query 零变化 / 控制台绝对地址，变异 **MB1**（注释语义改成任何 `#` 都截断）· **MB2**（合并函数退回 identity）· **MB3**（去掉无 query 短路），三枚均咬、还原逐字节一致；评审记录 = `proposals/REVIEW-2026-10-17-source-batch.md`（A 轮，2 MUST）+ `proposals/REVIEW-2026-10-17-Bprime.md`（B′ 轮，10 MUST）。 |`duty-review/bugs.md` 自感知段补「同根归纳」**锚行**（此前该族无锚 ⇒ 只能靠 E2E 段的虚高计数间接看见）。全量 **480 passed / 4 skipped**、测试文件 32 → **33**（`shared/gates.md` 计数行同步）。**明示盲区**：跨段同族机器串不起来（靠条目里手写的「同族复发」交叉引用，且**被指段落也要留一行**）；段是人工按环分的（分段漂 ⇒ 计数漂）；`bugs.md` 无日期字段，时间窗只认段内文本日期（无 ⇒ 视为静默）。 | ⑦ **列表项剥注释口径统一（D94 ③ 残余清偿，改判 D94 ② 对列表项的例外）**：落刀现场发现 **step 的 `goto` 丢了 hash 段**（守卫/基线正常、只有列表项受害）——`parse_line` 用的是 `line.partition("#")`（**任何** `#` 都截断，D94 ② 的旧例外），而 `/console/#/app/agent/detail/1` 这类**路径形态含 hash** 的值必然被砍成 `/console/`。**旧行号** = `DESIGN.md` D94 ②「列表项逐字节不变（其 `#` 是给人读的 note，由 `parse_line` 单点消费）」；**新证据** = 本批 v2 重生成产物的 `page.goto('/console/?switchAgent=7202')`（hash 段消失）。改判：`parse_line` 改走内核 `strip_inline_comment`（`#` 前有空白/行首才算注释、引号内不算）⇒ 路径里的 `#` 保留、尾随说明照剥；钉（`parse_line` 值保真）+ 变异 **MB4**（退回 `partition` ⇒ 红）。其余两处 `partition("#")`（`_parse_mock_line` / `initial:` 理由检测）**无现场证据、未动**，仍在 D94 ③ 的残余登记内。 |
| D105 | 生成的运行器配置**必须声明 `expect.timeout` 下限**（2026-10-17，issue #28；真跑现场驱动） | ① **病灶**：#27 落地后真跑仍 `3 failed 1 passed`，而**元素真在**（探针实测 `disabled=true` + 合规 `aria-label`）、三处导航 URL 全对 ⇒ 红因是**断言超时**：生成的 `playwright.config.ts` **没有 `expect` 段** ⇒ 继承 Playwright **默认 5s**，而该应用首屏实测 **14,184ms**（dev bundle 13.8MB）⇒「元素还没渲染」被误判成「元素不存在」= **假红**。② **定案**：生成器在两处 config 分支都发射 `expect: { timeout: Number(process.env.ATLAS_EXPECT_TIMEOUT ?? 20_000) }`（缺省 20s，仍远小于 test 超时；`ATLAS_EXPECT_TIMEOUT` 为运维覆盖口，与 `ATLAS_SLOWMO` 同族）。**它不是「固定等待」**：`expect` 是轮询式 auto-wait，本改只抬高**上限**，不引入 sleep，不破 §5.5「不得固定等待」。③ **被否**：只给守卫 `toHaveCount` 加 timeout（其余断言仍 5s，慢一点又撞）；调 test 超时（那只是兜底，不解决断言级假红）；固定 sleep（契约明禁，且共享靶场必飘）。④ **代价（如实）**：真失败从 5s 变 20s 才红；可在慢环境调低。⑤ **钉与变异**：`test_runner_config_declares_expect_timeout_floor`（配置含 `expect: {` + `20_000` + 覆盖口），变异 **MB5**（摘掉发射 ⇒ 红，还原逐字节一致）。 |
| D106 | **真跑门的执行 cwd = 生成物目录**（2026-10-17，issue #29；真跑现场驱动） | ① **病灶**：#27/#28 落地后真跑仍 `3 failed 1 passed`，而同一份产物 **`cd scripts` 直跑 8.2s 全绿** （`--grep E2E-APP-AGENT-DETAIL-001`）——差异 = **cwd**：`atlas_check` 用 `cwd=项目根` + `-c <相对路径>` 跑，而生成物里的相对路径全是 **cwd 相对**的（`storageState: ".atlas-auth/state.json"`、`outputDir: ".atlas-run"`、mock fixture）⇒ Playwright 把 storageState 解析到 `<root>/.atlas-auth/`（**并在那儿写了一个空 state**）⇒ **读不到人的会话** ⇒ 未登录态跑用例 ⇒ 断言 20s 超时**假红**。控制台（`e2e_console`）本来就是 `cd scripts` 再跑。② **定案**：本门改为 **`cwd=<scripts_dir>` + `-c playwright.config.ts`**（与执行器同一口径，两个入口不再各说各话）。③ **被否**：把生成物里的相对路径全改成绝对路径（派生件带机器绝对路径 = 不可移植、且破「生成物 = 确定性派生物」）；只修 setup 的 state 路径（其余相对路径仍会漂）。④ **教训**：**「同一份产物在两个入口下跑出不同结论」必须先查 cwd / 环境**，否则会把执行器差异误判成用例或实现缺陷（本轮依次误判为「超时不足」→ 已由 D105 兜住超时面，再查出真因 = cwd）。⑤ **钉与变异**：`test_check_e2e_runs_with_scripts_dir_as_cwd`（截 `run()` 的 (cmd, cwd)，断言 cwd = scripts 且 cmd 里无相对配置路径），变异 **MB6**（退回 root + 相对 `-c` ⇒ 红，还原逐字节一致）。 |
| D107 | 零步基线**每个探针都必须「缺席即判不成立」，不得等挂载**（2026-10-17，issue #30；真跑现场驱动） | ① **病灶**：`atlas_check --page app-agent-detail` ⇒ 两条真用例全绿，唯零步基线 `Test timeout of 30000ms exceeded`。带参页面的页级路由本就不渲染详情（`D104` 允许的形态），而 `attr` 探针发射的是 `getByTestId(t).first().getAttribute(n)` —— **无 `count()` 守卫**，Playwright 对**未挂载**元素的 `getAttribute` 会等到默认超时 ⇒ 4 探针 × 2 趟撑爆 test 预算。契约 §5.5 早已明写「基线探不到元素按 `null = 不成立` 处理」⇒ **等挂载 = 违约**（A1 判错，非项目缺陷）。② **定案**：`attr` 探针加 `count() > 0 &&` 前置（缺席 ⇒ `false` = 不成立）；并把该性质上升为**生成器的通用不变式**：**任何探针表达式都必须带缺席守卫**（`count()) > 0` 或 `tsVis(` / `tsVisible(` / `atlasValueOf(`）——由通用钉守着，防未来新增动词再犯。③ **被否**：给基线设更大的 test 超时（把「等挂载」合法化，掩盖违约）；带参页面跳过基线（契约 §5.5 已选择「回 null」而非「跳过」）；只在 v2 侧声明 `守卫:`（那是**资产选择题**，不修 atlas 违约面）。④ **钉与变异**：`test_zero_step_probes_never_wait_for_attachment`（对**全部**探针做守卫检查）+ 变异 **MB7**（摘 `attr` 的守卫 ⇒ 红，还原逐字节一致）。⑤ **出库判定**：探针行为属**运行面** ⇒ 待下一轮真跑复验后出库。 |
| D108 | E2E 真跑失败**自动留证**——trace / screenshot 只在失败落盘（2026-10-18，`proposals/RFC-20261018-01-e2e-failure-evidence`；外部发版雷达首跑 5 条机制级情报中唯一采纳项，独立评审两轮 + 维护者拍板「按推荐继续」） | ① **病灶**：真跑偶发红（节拍类）现场的取证上限 = 文本尾部 80 行（`e2e_console.py:520`（采集即截）/ `:582`（docstring 失败才带尾）/ `:591-592`（落账条件）），元素几何 / 命中点 / 时序类判据只能靠 `/tmp` 临时探针（跨会话不可复算；D98 动词批与案 6 两次付费先例）；`duty-review/bugs.md` 未解观察（hover 禁用按钮首跑偶发 `Element is not visible`，3 连跑全绿）的**升判条件**「复现 ≥2 次且能给出固定节拍证据（trace / 连续截图）⇒ 转 DR4」悬空在等证据源（`bugs.md:17`）。② **定案**：生成物两轨 playwright 配置补 `trace: 'retain-on-failure'` + `screenshot: 'only-on-failure'`——失败现场自动落 trace（DOM 快照 + 网络 + 操作日志，trace viewer 可逐帧回放）与截图到 Playwright 缺省 `test-results/`，**全绿轮零新增构件**；不溯及已装配副本 ⇒ **咬合点 = 下一次 `install.sh --update` / 首装重装配**，重装配前「契约已声明留证而现场无 trace」属**如实态、非缺陷**，巡检不得误报（对齐 `shared/single-source.md` §3 迁移仪式「新源生效 ⇔ 旧源显式失效」）；留证含业务内容，只落采纳仓本地、不进 atlas 上报通道（§15 零业务上下文出站面不破）；不解决 D103「人工会话取出 ⇒ CI 不可复现」盲区（trace 只重放**已发生**的失败，真身是登录态不是取证手段）。③ **被否**：`video` 缓行（trace 自带回放器，video 是粗粒度投影，多一键 = 双轨同构面 +2 无收益；缓行条件 = 实跑出现 trace 覆盖不了的取证需求才另起决策行）；全量常录 `on`（磁盘 × 每用例，成功轮留证无消费方）；留证键加环境开关（= 给「成功轮也留证」开后门）；独立录制管理器 / 上传通道 / 轮转清理（运行时平台机制，Atlas 零运行时）；**失败自动重试 N 次**（与「节拍类首跑不坐实、复跑复现才改判」（`bugs.md` E2E 段）方向相反，会把真缺陷静默吸收成绿——**防复读机裁决**已落 `duty-review/QUEUE.md` 归档区，外部情报再提 retry 引用可径行否决）；托管云沙盒会话（违「项目自足」，同归档区裁决）。④ **钉与变异**：钉 3 条——`test_failure_evidence_both_tracks_declare_trace`（双轨同构：`mode:none` 轨与预置登录轨都必须含两键）/ `test_failure_evidence_values_are_closed`（值形态封闭：恰为 retain-on-failure / only-on-failure，`video` 混入 / `on` 常录 ⇒ 红）/ `test_failure_evidence_has_no_override_switch`（无覆盖口），`tests/test_gen_e2e_scripts.py` 74 → **77** 条；变异 **MB10**（摘 none 轨 trace/screenshot 行）/ **MB11**（值改 `on`），`mutation_proof` 四段协议双绿（基线 3 passed → 注入 rc=1 → 还原逐字节一致 → 复绿），注入 diff 摘录于 `proposals/REVIEW-2026-10-18-e2e-failure-evidence.md`；契约条 = `rings/e2e/reference.md` §7.1「失败留证（硬，失败才落盘）」，门行 = `shared/gates.md` 2.2。⑤ **出库判定**：接线面（生成器 + 契约 + 门行）已立并全量 497 绿；**真跑留证咬合 = 下一次重装配后的真跑**（注红用例 ⇒ `test-results/` 出 trace、全绿轮零构件），咬合记录登 `shared/gates.md` 2.2 行（D98 / D101 先例）后出库。 |
| D109 | **逐用例宿主注入 URL 参数通道**：`goto` 查询门**重靶** + 项目级白名单（2026-10-18；字段与门落在 `rings/e2e/reference.md` §5.5 / §8.2；采用方现场驱动） | ① **病灶**：`会话:`（D89）解决的是 **sessionStorage** 那一个消费面；而某类应用的被测参数**只从载入地址的常规查询串读**（`window.location.search`）⇒ **无合法写法**（`goto` 带 `?` 是硬 FAIL、`auth` 只管登录态、`seed:` 绑数据实体）—— D104 ① 已把这条记为「三条各自成立 ⇒ 无合法写法」，当日改选 B′（base query 全局转发）并把「`会话:` 扩 URL 参数档」列入被否清单。采用方现场（2026-10-18）：两条用例被迫写成**同一前提**（都走 sessionStorage）⇒ 重复，而查询串那一面**零覆盖**。② **重靶取证（关键，本行的依据）**：原门（§5.7，2026-09-23；事故 `3509 §B20` = `E2E-LOGIN-003` 断言 `?state=forbidden` 演示横幅**自身文案**）的**靶子随 E1 原型环退役而消失** —— `?state=` 只出现在本文件 `:460` 的**已作废**决策行（D8 两段式 / D56 原型交互分级）；E1 后**无任何决策行**重新论证该门；`duty-review/bugs.md` 与 `CHANGELOG.md` **零起**该门事故；今日它在 D104 ① 里的身份是「无合法写法」的**阻碍** = 制造成本，而非拦事故。该门今日真正剩下的（`reference.md` 旧 §5.7 邻域的那条）是**另一族、不限于原型**的纪律：「前置数据态只能用真实界面动作达到」—— **而这族边界在重靶前后都由项目级白名单守**，与「`goto` 带不带 `?`」无关 ⇒ 取舍只剩成本与表达力。③ **定案**：（a）门**重靶** `goto 不带查询参数` → **`goto 查询键须已声明`**（键须 ① ∈ `e2e.query_preset.keys` ∧ ② ∈ 本用例 `参数:`；**原靶仍在 FAIL 面内**：未声明键照样红）；（b）用例块新增可选 `参数:`（**只声明键**，值内联在 `step` 的 `goto` 查询串里 = 单一来源），**守卫导航取该用例首个带参 `goto` 的查询串**（否则守卫读的是**无前提的 DOM**：参数决定「哪些元素在场」的页面上守卫会在 `goto` 后即红）；（c）`_support/url_merge.merge_base_query` 的「目标自带 `?` ⇒ 原样返回」**暗位转正为并集档**（base 在前、**同键 ⇒ 用例胜**）——该分支原注释即写着「§5.7 下不可达，**为未来扩展留位**」，且既有生成物无一带 query 的 `goto` ⇒ **零回归**；（d）三道新门（声明有效 / 值形态 / 同键双载体）+ 生成期同源中止（双保险）。④ **被否**：（A）「值只写 `参数:` 行、`goto` 保持无 query」—— 其立论之一是「保住 §5.7 事故防护」，取证后该论据**作废**（见 ②），取舍只剩成本与表达力，B 胜；其余照 D104 ⑤（运行期 TS 助手 / 把「同名键以目标为准」写成通则）。⑤ **边界（如实登记，不得 oversell）**：允许带白名单查询串后，「数据态直达」那族纪律的**机器面只剩白名单本身**（「项目说合法就合法」）—— 与 `会话:` 同族、是本设计的本来形态；登记以防后人以为还有别的网在兜。⑥ **钉与变异**：`tests/test_validators.py` **116 → 123**（重靶钉改名 1 + `参数:` 门 6）；`tests/test_gen_e2e_scripts.py` **+6**（两处导航面承载 / 基线不施加 / 无白名单中止 / 白名单外中止 / 死声明中止 / 值形态中止）；`_support/url_merge.py` 并集档（原「原样保留」单元钉随之改判）。变异 **MB12**（并集档退回「原样返回」⇒ 单元钉 + 守卫承载钉齐红）、**MB13**（守卫不追加用例参数 ⇒ 守卫面钉红），两枚均四段协议通过、还原逐字节一致，注入 diff 见任务件 `.trellis/tasks/10-18-atlas-url-param-channel/check-report.md`。设计依据 = 采用方现场（`src/entry/main/app.tsx:18/:36` 两个消费面 + `validators/validate_e2e_index.py` 旧门 + `_support/url_merge.py:48`）。 |
| D110 | 控制台**逐用例数据准备钩子**：项目自带 `product/e2e/scripts/atlas-prepare.mjs` ⇒ 执行前必跑、失败即拒（2026-10-18，v3 现场实证移植批；病灶账 = `duty-review/bugs.md` 005/006 链 companion；契约条 = `rings/e2e/reference.md` §10「执行」行 / `e2e_console` docstring） | ① **病灶**：共享状态型靶场（SPA + 服务端态）的用例 `precondition` 属**文档性声明**、运行器不自动归零 ⇒ 残留实体使 count 类断言系统性偏移（现场实测 Expected 1 · Received 5）；且控制台此前对「执行前重置」零消费——`e2e.reset`（`shared/stack-profile.md` §2）只被 `atlas_check` 真跑门执行（**批级**：整轮一次），逐条执行面无 per-case 前提通道。② **定案**：执行器在每条用例**计时起点之前**跑该脚本（`node <e2e.scripts_dir>/atlas-prepare.mjs`，cwd = 项目根，180s 上限，**不占**用例超时窗）；失败（非零）/ 超时 / 起不动 ⇒ **拒绝执行该条**：`done` 事件按完整形状写入（`ok=False` / `exit` 如实 / `prep_failed=True`），失败原文进「输出」面板——不静默跑注定偏移的用例（对齐执行器「解析不成立 ⇒ 诚实拒绝」同族口径）。③ **与 `e2e.reset` 的关系（登记，防后人重复起案）**：**不并轨**——`reset` 是批级且值形态为 shell 命令串（项目在 profile 声明）、本钩子是逐条且文件约定（项目在 `<e2e.scripts_dir>` 放脚本），现场 `reset: null`、两粒度各占一格；控制台若要消费 `reset` 须另起决策行。④ **被否**：由生成脚本内自查归零（把环境初值达序藏进生成物 = 静默吸收）；自动执行 precondition 声明（人读文档，无机器可执行形态）；prepare 失败仍照跑（偏离移用例 = 假绿通道）。⑤ **钉与变异**：`tests/test_e2e_console.py` **13 → 14**（钩子先于真跑 / 失败拒绝并带 `prep_failed` / 起不动 `exit=-2` 三型一钉）；变异 **M94**（摘 prepare 钩子段 ⇒ 钉红，还原逐字节一致）。设计依据 = v3 装配副本手改（现场实证可用）；主仓移植时审校掉装配副本失败路径的 `self._lines` 属性错拼（会 AttributeError 让执行线程挂死、`running` 永真），统一改走 `self._emit`（持锁 + notify）。 |
| D111 | `refresh` 落盘节拍参数化：发射 `ATLAS_REFRESH_SETTLE` 注入的 `waitForTimeout`（先等后刷），默认 0 行为不变（2026-10-18，v3 现场实证移植批；病灶账 = `duty-review/bugs.md` 005 链；契约条 = `rings/e2e/reference.md` §7.1 / §5.5 `refresh` 行） | ① **病灶**：`refresh` 裸 `reload` 对启用**节流型自动保存**的项目（距上次成功保存 < 节流窗则延迟落库）必丢步骤编辑内容（现场实测 Expected 1 · Received 0——刷新发生在保存落库之前）。② **定案**：发射**先等后刷**两行——`await page.waitForTimeout(Number(process.env.ATLAS_REFRESH_SETTLE || "0"));` + `await page.reload();`；**默认 0 ⇒ 生成物行为与既有契约一致**。通道选择同 F11：Playwright `test` CLI 无逐用例注入面，env 是唯一通道。③ **零业务常数（硬）**：毫秒数**不进生成器**——它属项目侧**运行时**前提，现场以 `ATLAS_REFRESH_SETTLE=<毫秒>` 于启动面注入（对齐 `ATLAS_SLOWMO` / `ATLAS_EXPECT_TIMEOUT` 同族）；它也不是 §5.5「固定 sleep」禁令所指（该禁令管**用例正文**不把共享靶场节拍写死；本行是执行环境配置面）。④ **被否**：硬编码任何项目常数进源包（§15 零业务上下文纪律）；生成期读项目配置算节拍（生成物 = 确定性派生物，节拍是运行时动态值）。⑤ **钉与变异**：`tests/test_gen_e2e_scripts.py` **83 → 84**（先等后刷顺序钉）；变异 **M95**（摘 `waitForTimeout` 发射行 ⇒ 钉红，还原逐字节一致）。 |
| D112 | `select` 动词的选项定位**不得取「可访问名全等」**：三级降级 + 命中不唯一即拒绝（2026-10-19，v2 真跑现场驱动；契约 §5.5 `select` 行） | ① **病灶**：生成物的非原生分支发射 `getByRole('option', { name: label, exact: true })` —— 即「可访问名**全等**」。而组件常把描述文案塞进选项内（ant Select 的标准用法）⇒ 选项的可访问名 = **标签 + 描述**（现场实测 `文本对话基于LLM的对话型交互，适合进行复杂的多轮对话`）⇒ 全等恒不命中；失败形态是 **30s 定位超时**（不是断言失败），现场看不出真因。该前设自 B173-1（2026-10-04）落地起就在（「label = 可访问名」只在「选项内只有标签」时成立）。② **定案**：三级降级定位 + 唯一性判据 —— ① `title` 属性**全等** → ② 可见文本**前缀** → ③ 名称**包含**；候选**只取几何可见元素**（`getBoundingClientRect()` 非零）；**命中数 ≠ 1 ⇒ 拒绝**并抛「列出可见选项」的错误（下一次失败可诊断，而不是等超时）。③ **被否**：只把 `exact: true` 去掉而仅留「包含」一档 —— 当某标签是另一标签的前缀（如 `文本` 命中 `文本生成` / `文本对话`）会 `.first()` **静默选错项** = 假绿通道，正是本仓反复治的那类；改用 `getByText` / testid 定位选项（选项在组件内部、无应然 testid，且契约定「语义只定行为不定 DOM 机制」）；为该组件单开通路（组件实现不被 E2E 应然约束）。④ **钉与变异**：`tests/test_gen_e2e_scripts.py` +1（`test_select_option_locating_is_label_based_and_rejects_ambiguity`：无 `exact: true` / 三级标记齐 / 唯一性判据 + 响亮文案 / 几何可见过滤 / 原生分支仍在）；变异 **MB14**（摘掉唯一性拒绝 ⇒ 该钉红）/ **MB15**（把 `exact: true` 形态写回发射 ⇒ 该钉红），两枚四段协议通过、还原逐字节一致。设计依据 = v2 真跑现场（`app-workflow-detail.spec.ts` 的 `select … 文本对话` 步，error-context + trace 留档）。 |
| D113 | testid 双向集合门的「动态名」诊断必须与应然集合口径一致：文案改指 §4 正规形态，判据由词形启发式改为**结构模式**匹配（2026-10-19，上游 issue #24；契约 §4 / §5.5） | ① **病灶**：`:623` 的 FAIL 诊断宣称「动态列表项如 `*-item` …仅在 `step`/`expected` 中引用即可」——该豁免自 2026-09-25（§B40/§B64）起已不存在（`shard_testids`：用例侧集合 = `testid:` 声明 ∪ `step`/`expected` 派生，**两侧都进本门**）⇒ 照建议操作仍判「缺失」；且触发判据是词形启发式（缺失名含 `item` 子串）⇒ 同类 `` `<prefix>-<运行期序号>` `` 不触发（漏提示），名字恰含该子串的真漏实现反被附上错指引（错提示）。② **定案**：只修诊断、**判定强度零变化**。文案改指 §4 正规形态（容器 + 计数 / 稳定样例行 / 类型级静态名）；判据改为**结构模式**——取源里模板 testid 的 `${…}` → `.+?`、字面段 `re.escape`，**只保留字面总长 ≥ 3** 的模板（全占位符模板会退化成 `^.+?$` 匹配一切，会把真漏实现误判成模板派生）；收集走 `collect_testids_expanded` 的**可选出参**（不动返回元数：该 5 元组已被 4 处调用方按位解包）。③ **被否**：用「静态前缀」当判据——模板以 `${slug}` 开头时前缀为空，而这恰是本仓最常见形态（实测）⇒ 判据恒不触发，等于没修；真开「按序号寻址」的豁免通道——削弱静态门（模板整段删除后双向集合门不再报红，缺陷从静态可判退化为只能靠真跑），且当前无具体业务需要，缺口已上报（上游 issue #24，kind: `tool-semantic`）；无条件附提示——对绝大多数「真漏实现」是噪声，诊断的价值在于精确。④ **钉与变异**：`tests/test_validators.py` +2（`test_testids_dynamic_name_hint_matches_actual_scope`：判定强度未变「缺失仍点名」+ 指向 §4 正规形态 + 旧句必须消失 + 夹具自检「缺失名不含 `item`」；`test_testids_plain_missing_gets_no_dynamic_hint`：不命中任何模板结构 ⇒ 不得附动态指引）；变异 **M96**（整段回退旧诊断）/ **M97**（只退判据为词形子串），两枚四段协议通过、还原后 sha256 与基线一致。独立复核：`proposals/RFC-20261019-01.review.md`（7/7 主张成立、改动面未发现遗漏、可直接落地）。 |
| D114 | 元素齐全守卫拆两段：**页面就绪锚点 + 纯在场声明**；动作产物元素改由 step / 断言的自动等待承接，**hidden 占位槽不再是必需形态**（2026-10-19，上游 issue #26；契约 §4.1 / §5.5 / §7.1） | ① **病灶**：#R2（2026-10-16）把守卫面从 `first_step_tids` 改回「用例 `testid:` 全量清单」后，守卫对**动作产物元素**（上传卡 / 导入结果 / 列表行 / 画布注释节点 / 动态变量行…）施加「用例开始时 count=1」，而这类元素初始态必然为 0 ⇒ 未执行任何 step 即死锁（v3 现场实测：同一批用例 2 passed / 9 failed，恒定 22.x 秒）。契约当时把解法指向实现侧 §4.1「hidden 占位槽」⇒ **测试义务被搬进产品 DOM**，并衍生三条**无机器判据**的隐式约定：占位须排在动作目标之后（否则 `first()` 命中隐藏元素）、字面量按声明文件唯一、占位可交互态须取断言反面（防假绿）——其中 DOM 序一条在 v3 实测踩中，且**任何校验器都发现不了**。次生病灶：`count` 断言被迫写成「真实数 + 1」（测试工件污染业务语义）；前一用例残留会被折叠成「页面未加载」的守卫失败（v3 实测 `Expected 1 / Received 2`，把「数据脏」与「页面没渲染」混成同一信号）。② **定案**：守卫拆两段 —— ① **页面就绪锚点** `await atlasAwaitAnyDeclared(page, <全量清单>, ATLAS_WAIT_TIMEOUT_MS)`：声明的 id **任意一个**在场即视为页面已渲染（`expect.poll` 原生轮询；超时点名**整份清单**）；② 声明里的**其余 id 一律不在 `goto` 时刻要求运行时在场**：被 step 触达的由该 step 的原生自动等待承接、被 expected 触达的由断言的自动轮询承接（§5.5 §B99「轮询等元素出现」语义不变）。守卫面**不会退化成空表**（锚点恒发射且带全量清单，直接回应 #R2 对「空表 = 静默消失」的裁决）。默认形态落地后：实现侧**不需要** hidden 占位槽、`count` 断言回到纯业务数。③ **被否**：保留全量 presence 而把占位槽改由**测试侧注入**（`page.evaluate` 追加/移除）——能解耦产品 DOM，但需生成器反知「哪些是动态」，且注入物的移除与断言取样之间存在时序窗口（会污染 `count` 读数）；退化为「只守 `step[0]`」——#R2 已证会得空表（静默消失）；把守卫整个删掉——失去「页面没渲染 / 路由或鉴权不对」的快速响亮失败（改在 step 里以 30s 定位超时表现，真因不可诊断）；要求分片为每个动态元素显式声明相位（`pre:` 项）——表达力更强但把成本转嫁到分片写作，当前无多相位需求。④ **钉与变异**：`tests/test_gen_e2e_scripts.py` **85 → 86**（新增 `test_guard_is_anchor_only_and_never_backfills_presence`：混合夹具（含「仅声明 / 从不触达」的 id）⇒ 锚点带全量清单、且**任何** presence 循环都不得出现；并把 #R2 三枚旧钉按新形态**重构而非删除** —— `test_guard_watches_case_testid_list_not_first_step` / `test_goto_first_step_keeps_guard_non_empty` / `test_testid_guard_uses_auto_wait_not_immediate_count` 的守卫面断言改为锚点面 + 「不得出现全量 presence 循环」）；变异 **MD114**（恢复任一段 presence 循环：全量或子集）⇒ 上述 3 枚钉红；还原逐字节一致、86 绿。⑤ **同日修正（现场回灌，2026-10-19）**：首版曾保留「纯在场声明」段（`guard_only = testid: − step − expected` 逐个 `toHaveCount(1)`）——真跑当场证伪：**静态双向集合门要求「源码里的每个实然 testid 必须被某条用例声明」**，于是「声明但不操作 / 不断言」是该门的**唯一合法补全形态**；再对它在 `goto` 时刻要求运行时在场 = 把「静态门的补全需求」误当「初始态断言」⇒ 面板 / 弹层未打开时该元素必然为 0，两条合法用例死锁（Expected 1 / Received 0）。故删该段：守卫回到**单段页面就绪锚点**，声明完整性由静态门负责、运行时在场由触碰它的 step / 断言负责。**兼容面（硬）**：存量项目的占位槽**不强制回退**（保留即继续满足第 ② 段；其 `count` 期望里的 +1 亦不变）⇒ 本决策对存量生成物是**增量可用**、非破坏性迁移；v3 将在下一次 `atlas update` 后一次性收编（删槽 + 回退 count +1 + 重跑全量）。 |
| D115 | 用例执行必须串行（并发 = 1）正文落定 + 机器判据：生成物须 `workers: 1` + `fullyParallel: false`（2026-10-19，契约 §7.1；`atlas_check` 新常驻门「执行串行」）| ① **病灶**：该纪律此前只活在**实现**里（生成器两处 config 发射 + 控制台「并发=1」）——契约正文只在 §10「执行」行描述**控制台**的「一次一条」，**没有**一条正面条款要求**生成物**串行；生成器注释把出处写成「rings/e2e §8」，而 §8 实为校验清单（8.1 validate_testids / 8.2 validate_e2e_index / 8.3 validate_e2e_mocks）⇒ **引用漂移**、读注释的人找不到依据；更关键：**没有任何机器判据** ⇒ 手改生成的 config 或封装运行方式注入 `--workers=N` 时无人报错，而靶场是共享有状态环境 ⇒ 打乱「零步基线先于改态用例」的定义序 = 恒真误报 / 前提被前序污染。② **定案**：① 契约 §7.1 增正文条「用例执行必须串行（并发 = 1）」，写明理由与边界（**跨域并行**仅在声明**独立靶场**时允许，同域顺序不得改变）；② `atlas_check` 增常驻门「执行串行」：读 `product/e2e/scripts/playwright.config.ts`，缺 `workers: 1` 或 `fullyParallel: false` ⇒ **FAIL**（正确性纪律而非新鲜度 ⇒ 不降 WARN）；③ 生成器两处注释的出处由 §8 改为 §7.1。③ **被否**：判 WARN（并行会污染前提，属正确性问题；WARN 可被无视而门应咬人）；在生成器内自检（生成器即发射方，自检恒真）；直接实现「同域分组串行 / 跨域并行」（当前无「独立靶场」声明机制，需另起决策行 + stack-profile 字段 ⇒ 先落纪律与门）。④ **钉与变异**：`tests/test_gen_e2e_scripts.py` +1（`test_config_declares_serial_execution`：配置含串行声明 + 注释出处指向 §7.1 且不得再出现 `§8`）；`tests/test_atlas_check.py` +1（`test_serial_execution_gate_bites_on_parallel_config`：合规 ⇒ ok、改成 `workers: 4 / fullyParallel: true` ⇒ FAIL）；变异 **MD115a**（摘掉生成器的 `workers: 1` 发射）⇒ `test_config_declares_serial_execution` 红；**MD115b**（摘掉门里的 `workers` 判据）⇒ `test_serial_execution_gate_bites_on_parallel_config` 红（该钉**逐判据隔离**：只破 `workers` / 只破 `fullyParallel` 都必须 FAIL，否则「两判据同破」的夹具会让任意一条判据被摘掉时仍绿）；两枚均还原逐字节一致、518 passed。 |
| D116 | `attr` 动词新增**空值形态** `""` / `(空)`：断言「该属性**缺席或为空串**」—— 补上「否定属性」的表达面（2026-10-19，契约 §5.5；`scripts/gen_e2e_scripts.py` 两处发射点）| ① **病灶**：`attr` 只能表达「属性等于某值」，**没有**「属性应该缺席」的形态 —— 生成器 `if not name or not val: raise` 直接拒空值，且发射写死 `getAttribute(n) === "<值>"`。而「**不**带某标记」是一类真实 AC 属性：现场 = 管控（`fileUploadAccess`）只在**运行态**给入口写合规文案（`aria-label`）并置灰，**研发态**入口不得消费该 guard ⇒「研发态该入口**不带**合规文案」才是这条 AC 的可证伪机器面；而它的兄弟形态「该入口可用（`enabled`）」在同一控件上**不是稳定态**（面板对空模板文件有自动回填，删除后约 600ms 被写回并落库 ⇒ `enabled` 只在瞬态窗口成立）⇒ 观测面必须靠**边界标记**，不能靠可用性。② **定案**：① 契约 §5.5 `attr` 行补空值形态与语义（缺席或空串）；② 两处发射点（断言行 `ts_case` / 探针表达式）统一 `?? ''` 归一后比对，断言行走 `expect.poll`（轮询 + 与探针**同形** = 单源）；③ 非空期望**逐字节不变**（零回归承诺）。**实测依据（非推断）**：缺席属性的 `getAttribute` 返回 `null`（**不是** `""`）⇒ `toHaveAttribute(name, "")` 对缺席判 **FAIL**（= 半通状态），故不得用它发射空值档。③ **被否**：`not.toHaveAttribute(name)`——只覆盖「缺席」半档、丢「空串」；在实现侧给该入口加一个「未被管控」的标记属性——为测试改产品语义、且要动共享组件；把该 AC 判为不可测——观测面确实存在（边界标记），只是此前没有表达能力。④ **钉与变异**：`tests/test_gen_e2e_scripts.py` 同族钉子 `test_value_and_attr_keep_same_semantics` **扩展**（不增用例数）：`""` / `(空)` 两写法均须发射 `?? '').toBe('')` 且**不得**出现 `toHaveAttribute(name, …)`；非空期望须仍走 `toHaveAttribute` 且不含 `?? ''`（零回归）。变异 **MD116**（把空值档换回 `toHaveAttribute(name, "")`）⇒ 该钉红；还原后 sha256 逐字节一致、全量 **518 passed / 0 failed / 4 skipped**。 |
| D117 | `select` 的就绪门改为**按命中态轮询采样**：不得依赖全局候选集的 `attached`（2026-10-19，v2 真跑现场驱动；契约 §5.5 `select` 行） | ① **病灶**：非原生分支点开触发器后以 `page.locator('[role=option],[role=menuitem]').first().waitFor({state:'attached'})` 作就绪门，而**采样用的是同一套选择器**。被测页（v2 工作流详情）顶部导航本身是 9~10 个常驻 `[role=menuitem]` ⇒ 门被环境项秒满足、形同虚设；rc-select 的下拉挂载后有一段「未定位（`getBoundingClientRect` 零盒）」窗口，而采样对候选做几何可见过滤 ⇒ 采样落在该窗口内，候选只剩导航项。失败文案：`select：…-test-mode-select 的选项里找不到唯一「文本对话」；可见选项=["应用市场","应用管理","应用评估","应用观测","MCP市场","MCP管理","组件市场","组件管理","素材库"]`。**反证（关键）**：失败快照里触发器已 `combobox [expanded]`、`listbox` 内两个选项都在（`文本生成`[selected] / `文本对话`）⇒ 下拉确实开了，采样比「可见」早了一步。复现：整份 `--repeat-each=3` ⇒ 12 次中 **2 红**（均为该用例）；冷启/负载下必中。② **定案**：就绪与采样**合并为一个判据** —— `page.evaluate` 返回三值 `status`（`unique` / `none` / `ambiguous`），外层用 **`expect.poll`**（与页面就绪锚点同一轮询原语）等到 `status !== 'none'`：**0 命中 = 未就绪** ⇒ 轮询至 `ATLAS_WAIT_TIMEOUT_MS`；**>1 命中 = 歧义** ⇒ **立即**拒绝（D112 语义不变，不轮询）；**唯一** ⇒ 点击。三级降级（`title` 全等 → 可见文本前缀 → 名称包含）、几何可见过滤、响亮文案（列出可见选项）、原生 `<select>` 分支**逐项不变**。③ **被否**：把就绪门「锚到触发器自己的 listbox」（读 `aria-owns`/`aria-controls` 等它可见）—— 现场确有 `aria-owns="rc_select_3_list"`，但该属性只在部分组件族的 DOM 契约下成立，与「语义只定行为、不定 DOM 机制」相抵；轮询式采样与组件无关，且顺带覆盖「选项异步到达」这一更一般的情形。加固定 `waitForTimeout` 作轮询间隔 —— 撞 §5.5「生成物不得含固定等待」既有门（本单首版即被该门当场吹红）；把「未就绪」也立即拒绝 —— 等于把该 helper 的适用面收窄到「下拉同步渲染」的组件。④ **钉与变异**：`tests/test_gen_e2e_scripts.py` +1（`test_select_polls_until_options_are_positioned_and_refuses_ambiguity`：旧就绪门必须消失 / 轮询原语 = `expect.poll` 且**不得**用固定等待 / 三值齐 / 歧义立即拒绝 / 响亮文案不变 / 原生分支仍在）；D112 原钉的唯一性判据断言按新形态**重构而非删除**（`ok:false` → 三值 `status`）；变异 **MB16**（把轮询段退回单次采样 ⇒ 该钉红），四段协议通过、还原 sha256 逐字节一致；全量 `pytest tests -q` ⇒ **519 passed / 0 failed / 4 skipped**。设计依据 = v2 真跑（2 red + `trace.zip` + `error-context.md` + 页面快照）。 |
| D118 | 生成物等待超时的**上限口径统一**：`ATLAS_WAIT_TIMEOUT_MS` 缺省 10s → **20s**，并留环境覆盖口（2026-10-19，v2 真跑现场驱动；契约 §7.1 + §5.5 `waitFor` / `download` 两行） | ① **病灶**：同一份生成物里两个「等界面」的上限**口径不一致** —— 断言侧已按 D105 抬到 **20s**（`ATLAS_EXPECT_TIMEOUT` 可覆盖，理由是同一应用首屏实测 **14,184ms**），而**页面就绪锚点**（连带 `waitFor` / `download` / `select` 就绪轮询）用的 `ATLAS_WAIT_TIMEOUT_MS` 仍**写死 `10_000`、无覆盖口**（`scripts/gen_e2e_scripts.py:1476`）⇒ 上限比该应用**已知最坏首屏还短** ⇒ 冷启 / 负载下**间歇性假红**。**现场（v2）**：整份真跑首轮 `9 passed / 1 failed`，红的那条（`E2E-MARKET-APP-AGENT-001`）倒在锚点 10s（`元素齐全守卫：声明的 testid 无一在场`）；同口径探针（同一 `storageState` + 同 `sessionStorage` 预设）实测该元素 **2.2~2.5s** 出现且 `disabled=true` + 合规 `aria-label` 全对 ⇒ **语义全对，只是量尺比被测对象短**；复跑 `--repeat-each=3` ⇒ 该条 **3/3 绿**、全量 **28 passed / 0 failed / 0 flaky**。**这不是「放宽判定」**：被测属性（首屏渲染）真实且可证伪，D105 已就同一应用记过 14.18s 的实测。② **定案**：① `ATLAS_WAIT_TIMEOUT_MS` 发射为 `Number(process.env.ATLAS_WAIT_TIMEOUT_MS ?? 20_000)`（缺省与 D105 的 `expect` 下限**同值**、运维可覆盖，与 `ATLAS_EXPECT_TIMEOUT` / `ATLAS_SLOWMO` 同族）；② 契约 §7.1 增正文条「**等待超时下限（硬）**」，并把 §5.5 `waitFor` / `download` 两行的「默认 10s」同步改为 20s（同一个常量、同一次口径变更，不得只改一处）；③ 派生物确定性不受影响（常量在**每页共用头**，重生成即整体一次变更）。③ **被否**：只加环境口、缺省仍 10s（默认行为不变 ⇒ 别的项目 / 别人的会话照样踩）；给锚点单开一个常量、与 `waitFor` 分开（同一件事两个数字，正是本决策要消掉的病）；把等待改成固定 `sleep` 或「整份用例重试」（§5.5 禁固定等待；重试会掩盖真失败并让红变绿）。④ **钉与变异**：`tests/test_gen_e2e_scripts.py` +1（`test_wait_timeout_cap_is_20s_and_overridable`：发射面须含 `20_000` + `process.env.ATLAS_WAIT_TIMEOUT_MS`，且**不得**再出现写死的 `const ATLAS_WAIT_TIMEOUT_MS = 10_000;`）；变异 **MD118**（退回写死 10_000）⇒ 该钉红；还原后 sha256 逐字节一致、全量 `pytest tests -q` 绿。设计依据 = v2 真跑（首轮 1 red + 失败原文 + 探针耗时 + 复跑 3/3）。**E2E 级反证**（装后实测）：`ATLAS_WAIT_TIMEOUT_MS=200` ⇒ 该用例红在锚点（`Timeout 200ms exceeded while waiting on the predicate`）；而 `=1500` 那轮绿 ⇒ 同一页逐轮渲染耗时在 **<1.5s ~ 2.2s** 间波动（**波动本身**就是 10s 写死会成为掷硬币的机制）。 |
| D119 | 自感知上报与工件健壮性一揽子定案（2026-10-19；#25, #27/#33, #28, #29, #30, #34, #35，控制台守卫） | ① **#35 登录预置深度取值与 JSON 支持**：`token_key` 点号分段查找解构，空值或非字符串大声抛错并阻断损坏的 `state.json`；引入 `body_format: form | json`（默认 `form` 严格保持向下兼容）；统一 try-catch 拦截登录请求与 JSON 解析异常并输出状态码与截断响应；优先保留本地合法存量 `stateFile`（保护 `codegen` 录制产物）。② **#27/#33 测试目录与文件过滤**：`validate_testids.py` 扫描过滤 `__tests__`、`test`、`tests`、`__mocks__`、`__snapshots__`、`e2e`、`fixtures` 目录及 `*.test.*`、`*.spec.*`、`*.cy.*`、`*.stories.*` 文件，消除测试断言回声引发的假全站重复。③ **#34 应然先行落点门分档**：应然落点门联动 `product/e2e/e2e-index.md` 页面表 `实现状态`，未实现/实现中页面的未落地落点降级为 WARN（未实现页落点待落地），翻档为已实现后严格 FAIL（防死字面量假陈述）。④ **#29 域级 PRD 核心资产门**：`validate_prd.py` 严格校验域级 PRD 核心资产（二/四/五章及 `#### 结构类 AC 清单`），兼顾存量接管开户最小集。⑤ **#25 结构环事实载体解绑根 README**：`_meta.json` 引入 `truth_carriers` 支持语义别名与自解释注释，契约散文与生成器提示文解绑根 README。⑥ **#28 存量零 testid 三步推进链**：契约写明三步链，利用 `blocked` 状态与 `test.skip` 隔离待埋点与业务失败。⑦ **#30 独立审查 executed 标记**：`review.json` 引入 `executed: boolean`（缺省 true 向后兼容），基线写入口注入 false。⑧ **控制台守卫**：`scripts/e2e_console.py` `snapshot()` 读索引前加存在性检查，抛 `SnapshotError` 防线程崩溃。 |
| D120 | 步骤与断言动词支持**多实例序位下标** `[N]`（0 起始）：消除 `.first()` 单一语义造成的同名重复行分支零覆盖（2026-10-19，issue #31；契约 §5.5；`scripts/gen_e2e_scripts.py` 发射点） | ① **病灶**：生成器此前对动作与断言一律死板发射 `.first()`（Strict Mode 归一的副产物）。在列表行、表格行、重复项控件等界面中，某些操作只在非首行可用（如上移按钮在首行恒 `disabled`），分片无序位参数导致动作既无法表达也无法覆盖，强行点首行产生 no-op，相应业务分支（如 `handleMove(i, i-1)`）在测试套件中零机器覆盖。② **定案**：① 步骤动作与断言动词的 target testid 均支持 `[N]` 下标语法（0 起始，如 `click move-btn[1]`、`fill input[2] val`、`visible item[1]`），发射为 Playwright 原生 `.nth(N)`；② 省略下标时保持缺省 `.first()` 语义（100% 向后兼容）；③ `validate_testids.py` 的 `case_testid_usage` 自动将 `tid[N]` 归一为 `base_tid` 参与双向集合与落点门对账，用例 `testid:` 声明与 `落点:` 无需重复写下标；④ 钉子：`test_subscript_nth_index_emits_nth_locator` 与 `test_testids_subscript_index_resolves_to_base_id`。 |
| D121 | 数据准备钩子向项目脚本传**用例上下文** `ATLAS_CASE_ID`（2026-10-20，D110 细化；`scripts/e2e_console.py` 调用点；契约 §10「执行」） | ① **病灶**：D110 的 prepare 钩子只有「脚本路径」一个约定，运行器不传任何用例上下文 ⇒ 项目只能写**全局前置**：任意一组用例的数据前提（某类节点/实体）缺失时，同一项目里与之无关的用例也会在 prepare 阶段被一并拒绝执行（实测：控制台 14 条用例中 5 条依赖某节点，该节点缺失导致其余 9 条同样跑不了）。prepare 的语义本应是「准备**当前用例**依赖的数据」，缺上下文使其退化为全局闸门。② **定案**：运行器调用 prepare 时在子进程 env 注入 `ATLAS_CASE_ID` = 当前用例 ID（与 `ATLAS_BASE_URL`/`ATLAS_SLOWMO` 同一注入通道）；项目脚本可据此分段执行，不读该变量的存量脚本行为**逐字节不变**（纯增量、向后兼容）；契约 §10「执行」与 `e2e_console` docstring 同步。③ **被否**：给 prepare 传 argv 位置参数（存量脚本会把未知参数当路径/选项，破坏兼容）；由运行器解析项目用例的 precondition 自动归零（precondition 是文档性声明，无机器可执行形态——D110 ④ 同判）；把「缺失即跳过」的降级写进运行器（会掩盖用例级前置不足，偏离移用例 = 假绿通道）。④ **钉与变异**：`tests/test_e2e_console.py` 的 prepare 钉三元组扩为四元组（cmd/cwd/timeout/**ATLAS_CASE_ID**）；变异 **M121**：摘 env 注入 ⇒ 钉红（case 上下文丢失），还原逐字节一致。 |
| D122 | `select` 的**选项候选集**纳入组件库可见选项类名（2026-10-20；`scripts/gen_e2e_scripts.py` 发射点；契约 §5.5） | ① **病灶**：候选集只取 `[role=option],[role=menuitem]`。Ant Design Select 的可见项是 `.ant-select-item-option`（带 `title`，**无 role=option**），页面上仅有的 `role=option` 是零宽的 a11y 镜像（值为 model/template 且 `getBoundingClientRect().width === 0`）⇒ 下拉已真实打开，采样仍只看到顶部导航的 `menuitem`，报「可见选项=[导航项…]」并判 none，定位失败被当成用例失败（假红）。② **定案**：候选集追加 `[class*="select-item-option"]`（`*=` 兼容自定义前缀，如 `msc-ant`；并排除选项内部 `-content` / `-state` 子节点——它们同样命中类名但不可独立选择，不排除时无 title 的选项会在前缀/包含两级重复命中 ⇒ 假歧义），`atlasPick` 与最终点击用同一选择器；几何可见门、三级降级与歧义拒绝语义不变（候选变宽后仍由「唯一命中」兜底，歧义即拒）。③ **被否**：按零宽 `role=option` 的 value 取项（语义是值不是标签，且零宽不可点）；放宽到全部带 `title` 的元素（工具提示等环境项会制造歧义）；项目侧在用例里硬编码组件类名（应然资产不应绑定 UI 库实现）。④ **钉与变异**：`test_select_option_locating_is_label_based_and_rejects_ambiguity` 增候选集断言（两处选择器各一）；变异 **M122**：从两处选择器摘掉 `select-item-option` ⇒ 钉红，还原逐字节一致。 |
| D123 | `upload` 动作在 ESM 项目（`package.json` `type: module`）改用 `import.meta.url` 解析 fixture 路径（2026-10-20；`scripts/gen_e2e_scripts.py` 发射点；契约 §5.5/§7.1） | ① **病灶**：生成物用 `resolve(__dirname, '..', 'fixtures', …)` 定位 fixture；CJS 项目可用，但 `package.json` 声明 `type: module` 时 Playwright 按 ESM 执行，`__dirname` 未定义 ⇒ 运行期 `ReferenceError: __dirname is not defined`，所有 upload 用例必红（实测）。② **定案**：生成期读取 `<root>/package.json` 的 `type`；`module` ⇒ 发射 `fileURLToPath(new URL('../fixtures/<rel>', import.meta.url))` 且页头导入 `node:url`；否则保持 `resolve(__dirname, …)`（CJS 项目生成物逐字节不变）。两种形态均按脚本文件位置解析，不依赖进程 cwd。③ **被否**：运行期 try/catch 单形态兼容（ESM 的 `import.meta` 与 CJS 的 `__dirname` 在语法/求值时机上互斥）；依赖进程 cwd（控制台从 scripts 跑、`atlas_check` 从项目根跑，两载体不同）；项目侧手改用例（生成物重跑覆盖）。④ **钉与变异**：新增 `test_upload_renders_esm_safe_path_for_module_projects`（ESM 形态 + 页头导入 + 无 `__dirname`）；既有 CJS 用例继续钉原形态；变异 **M123**：去掉 esm 分支 ⇒ ESM 钉红，还原逐字节一致。 |
| D124 | E2E 就绪门补**浏览器就绪判据**（2026-10-20，issue #38；`_support/pw_runner.py::probe_browser`；两道消费者 = `atlas_check`「E2E 真跑」门 + `e2e_console` 起跑前置；契约 §10「执行」、gates 2.2 行同步） | ① **病灶**：就绪判据只有「模块可解析」一件事（D101）——npm 装包**不自动下载浏览器**（须另跑 `npx playwright install chromium`），项目在 `e2e.node_modules` 子包自装 `@playwright/test` 后未装浏览器 ⇒ 门判「就绪」、真跑在 launch 阶段才炸（`Executable does not exist at …/ms-playwright/chromium-*`），错误落到 Playwright 内部报错、非门的显式输出 = 门谎报就绪（响亮原则破口；D101 同族——真跑依赖「模块可解析 **加** 浏览器可执行」两件事，门只判了一件）。② **定案**：判据分层 = ① 模块可解析（D101 已有）+ ② **浏览器可执行存在**——路径由 playwright **自算**（node 侧 `chromium.executablePath()`，走其自带 registry，自动吃 `PLAYWRIGHT_BROWSERS_PATH` 与所装版本 revision，Python 侧不猜路径；2026-10-20 本机实证：未下载的浏览器该调用**返回计算路径而不抛错** ⇒ 「算得出」≠「装了」，存在性必须本侧判）；`ATLAS_PLAYWRIGHT_CHANNEL` 已设 ⇒ launch 走系统通道浏览器，缓存判据**旁路**。门不成立 ⇒ **FAIL 指名安装命令**；控制台 ⇒ 起跑前诚实拒绝（同一内核，不造第二份）。③ **被否**：issue #38 原案「真跑门 SKIP + install 命令」——SKIP 语义 = 「前置未声明」（gates 总则 3，如 `app_base_url` 空），此处 E2E 意图已声明、依赖装了一半，与同门「运行器可执行不存在 ⇒ FAIL + npm i 提示」先例同族，FAIL 更诚实；Python 侧硬编码 `~/…/ms-playwright` 路径猜测（`PLAYWRIGHT_BROWSERS_PATH` 可重定向 ⇒ 假拒）；给 stack-profile 加 postinstall 引导字段（重——文档一句话足够，暂不做）。④ **钉与变异**：`tests/test_atlas_check.py::test_check_e2e_fails_loud_when_browser_missing`（FAIL + install 指名 + 真跑不起：`failures[0].command` 空 + 无 e2e-summary）+ `tests/test_e2e_console.py::test_probe_browser_three_states`（路径存在 / 不存在给 install 出路 / 探针报错给尾行原因 / **channel 旁路不 spawn**）+ `::test_start_refuses_when_browser_missing`（起跑前拒绝）；既有 6 条真跑钉（主题 ≠ 浏览器判据）补旁路假件；变异 **M124**（摘门内判据退回恒真 ⇒ 门侧钉红）/ **M125**（摘控制台判据 ⇒ 起跑钉红），四段协议含注入 diff、还原逐字节一致。`tests/test_atlas_check.py` 30 → 31 条。 |
| D125 | 控制台前置准备钩子环境与前端诊断补齐：`NODE_PATH` 注入与 `prep_failed` UI 消费（2026-10-20，D110/D121 细化；`scripts/e2e_console.py`、`templates/e2e/console/app.js`；契约 §10「执行」） | ① **病灶**：两处缺陷同属 prepare 钩子闭环不完整：① **依赖脱节**：`e2e_console.py` 在执行真跑用例时通过 `env["NODE_PATH"] = str(nm_dir)` 传入了项目依赖路径，但在执行 `atlas-prepare.mjs` 前置钩子时仅注入了 `ATLAS_CASE_ID`，遗漏了 `NODE_PATH` ⇒ 当 `product/e2e/scripts/` 目录下未独立自建 `node_modules`（复用项目根依赖）时，前置脚本引入包（如 `@playwright/test` 或工具库）直接在模块加载期报 `ERR_MODULE_NOT_FOUND`（exit=1 · 0s）；② **归因误导**：后端虽然在 `done` 事件里标记了 `"prep_failed": True`，但前端 UI `templates/e2e/console/app.js` 根本未消费该字段（`patch` 漏存），仍走普通失败逻辑，导致 UI 状态 badge 显示红色的 `失败`，且横幅直接提示 *“问题在用例本身的话回对话改用例后重生成脚本”*。使用者在用例和脚本里排查，被误导而忽略了用例根本没起跑、前置准备失败的事实。② **定案**：① `scripts/e2e_console.py`：执行 `atlas-prepare.mjs` 时，若 `nm_dir` 存在，注入 `prep_env["NODE_PATH"] = str(nm_dir)`，确保准备脚本运行环境与真跑测试子进程严格对齐；② `templates/e2e/console/app.js`：`patch` 记录 `prep_failed: Boolean(d.prep_failed)`；状态 badge 分流：`e.prep_failed` 时显示 `<span class="pill warn">前置失败</span>`（区分用例执行失败 `bad: 失败`）；错误摘录显示 `（前置数据准备 atlas-prepare 失败，点「输出」看日志）`；顶层通告分流：`d.prep_failed` 时提示 `${id} 前置数据准备 atlas-prepare 失败——点「输出」看日志；与用例脚本本身无关。`（消除“改用例”误导）。③ **被否**：前置失败时吞掉错误、静默继续跑用例（D110 已定：注定状态偏移的用例不能跑）；将前置状态与用例失败混为一谈、仅靠输出日志区分（现场实证：0s 失败时绝大多数人第一反应是脚本写错，前端必须在视觉和指引上有显式分流）。④ **钉与变异**：`tests/test_e2e_console.py`：① `test_prepare_hook_runs_before_case_and_refuses_on_failure`：扩展断言，验证 `fake_run` 收到的 `env` 中包含 `NODE_PATH` 且等于 `str(nm_dir)`；② `test_console_app_js_handles_prep_failed_distinctly`：验证 `app.js` 包含 `prep_failed` 分流，状态展示 `前置失败`，且通告显式注明 `与用例脚本本身无关`。变异 **M126**：从 `e2e_console.py` 摘掉 `prep_env["NODE_PATH"]` 注入 ⇒ 钉红；还原逐字节一致。 |
| D126 | 控制台持窗模式关闭 Playwright 自身 test timeout（2026-10-21，issue #39；`scripts/e2e_console.py` 起跑命令；契约 §10.1 执行行） | ① **病灶**：留窗语义由 `atlas-hold.ts` 的 auto fixture 在 **teardown 阶段**等待人工关窗承载；但 Playwright 的默认 test timeout（30s）**覆盖 fixture teardown**，等待到 30s 即报 `Tearing down "atlasHold" exceeded the test timeout of 30000ms` 并结束 worker ⇒ 浏览器在用例跑完后约 30s 自动关闭，「不自动关闭」形同虚设。更隐蔽的是结果哨兵在进入留窗前已写 `exitstatus:0`，控制台据此显示「通过」并可能显示「窗口已保留」，与现场（窗口已关）不一致。② **定案**：持窗模式（`keep_open=True`，控制台默认有头）给 `playwright test` 追加 `--timeout=0`，关闭运行器自身 test timeout；控制台的 wall-clock `--timeout`（默认 120s）恢复为**唯一超时真相源**——到点 `kill` 并如实报「超时」，与 §10.1 既有表述一致。自动关窗模式（`--auto-close` / `--no-head`）不传该旗标，保留运行器原生 30s 兜底，避免控制台异常退出后留下无主进程。③ **被否**：在生成的 `playwright.config.ts` 里写 `timeout: 0`（会把直跑 / `atlas_check` 真跑门一并变成无超时，且需所有项目重生成）；缩短或加长 hold 等待（不解决 teardown 超时语义）；把留窗移到 test body 末尾（body 同样受 30s 限制，且失败路径无法统一）；设置 `globalTimeout=0`（默认本就是 0，管不到 test timeout）。④ **钉与变异**：`tests/test_e2e_console.py::test_runner_disables_playwright_test_timeout_only_in_hold_mode`——持窗命令必含 `--timeout=0` 且带 `ATLAS_KEEP_OPEN=1`，自动关窗命令不得含该旗标；变异 **M127**：摘掉持窗分支的 `--timeout=0` ⇒ 钉红，还原逐字节一致。 |
| D127 | 控制台「已提交」视图按**事件流累积合并**（2026-10-21；`scripts/e2e_console.py::Ledger.committed_snapshot`；契约 §10「执行」） | ① **病灶**：单次提交只写页面草稿里本次执行/勾选的若干条用例，而 `cases_payload` 的 `committed` 取 `last_submit`（最后一条 submit 事件）⇒ 后一次只提交 1 条时，之前提交过的用例从 committed 视图整体消失；提交会清空浏览器草稿，于是控制台把已执行/已评审的用例重新显示为「未跑」（现场：账本最后一条只含 013，010/012 的历史提交被抹掉）。② **定案**：新增 `Ledger.committed_snapshot(source)`，按 append-only 事件顺序合并所有 submit 的 `cases`（后提交覆盖同名用例），`ts/actor` 取最后一条；`cases_payload` 与 `_submit` 改用该视图；`last_submit` 保留「最近事件」语义供时间戳/诊断使用。③ **被否**：提交时把全量累积快照写进每条事件（事件膨胀、重复存储，与「草稿=差量」语义冲突）；提交后保留草稿（重复计数/重复提交风险）；UI 侧按事件回放（把协议语义塞进展示层，其他消费者仍会踩同一个坑）。④ **钉与变异**：`test_committed_snapshot_merges_partial_submits`（部分提交合并 / 同名覆盖 / source 隔离 / legacy list 形态跳过）；变异 **M128**：把 `committed_snapshot` 退回 `last_submit` ⇒ 钉红，还原逐字节一致。 |
| D128 | 控制台人工评审绑定**提交与脚本指纹**，引入陈旧度（stale）判定与 UI 拦截（2026-10-21；`scripts/e2e_console.py`、`templates/e2e/console/app.js`；契约 §10.1） | ① **病灶**：控制台账本此前仅记录 `reviewed.pass` 与执行快照，**无任何代码提交（HEAD SHA）或测试脚本指纹**。人审完某条用例后，若代码或生成脚本发生改动，账本仍显示「已评审」，前端仍渲染勾选态，造成「曾经有人审过 = 当前版本已验收」的假象（审查逃逸）。② **定案**：① 提交事件与逐用例快照追加 `prov: {head_sha, scripts_hash, git_dirty, actor_type}`；`scripts_hash` 白名单覆盖 `product/e2e/scripts/` 源码及 `atlas-prepare.mjs`，严格排除运行时产物（`test-results/`、trace、png 等）；② `committed_snapshot` 按当前工作区指纹自动计算 `review_state` 四态闭集（`fresh` / `stale` / `legacy` / `unreviewed`）；若 HEAD 或脚本变动，标为 `stale`；③ 前端 UI：`isReviewed` 将 `stale` 剔除出「已评审」；用例行渲染 `STALE 需重审` 徽标、禁用通过复选框，横幅提示变动原因；顶栏统计增加 `需重审` 项；重新执行该用例自动清空旧评审态；④ 历史旧账本缺失指纹标记为 `legacy`，维持兼容但不冒充 fresh。③ **被否**：每次执行（done事件）均重新跑 git subprocess（导致运行期开销与单元测试 mock 冲突）；把 stale 做成阻断性硬门禁（E2E 控制台是辅助工作台，评审阻断由收口门统一把控）。④ **钉与变异**：`tests/test_e2e_console.py` +4（`test_scripts_hash_excludes_runtime_artifacts_and_whitelists_scripts` / `test_case_review_state_lifecycle` / `test_submit_attaches_provenance_and_committed_computes_stale` / `test_console_app_js_handles_stale_and_legacy_and_provenance`）；变异 **M129**（摘掉 stale 判定退回恒 fresh ⇒ 钉红），还原逐字节一致。全量测试通过。 |
| D129 | 独立审查报告契约扩展为 **`schema_version: 2`**，引入缺陷指纹去重、存量代码标记、处置留痕与轮次上限（2026-10-21；`shared/independent-review.md` §3/§4；`_support/review_policy.py`、`scripts/validate_review_report.py`、`scripts/cli_review_convert.py`、`scripts/gen_e2e_scripts.py`） | ① **病灶**：① 原契约状态映射硬死（有任一 Critical 即 FAIL），**无法区分改动引入的新缺陷与存量旧代码问题**；Agent 评审实测 59% 为既有存量代码，导致微小改动因存量问题被无限阻断；② 缺乏 finding 去重指纹，导致相同问题跨轮重复刷分；③ 缺乏轮次上限，实测出现连夜 50+ 轮死循环；④ 缺乏显式处置闭环（disposition），误报（false positive）无法由人或架构签字排除。② **定案**：① 设立单源内核 `_support/review_policy.py`；② `review.json` 引入 `schema_version: 2`；`checks[]` 扩充 `fingerprint`（排除行号的稳定哈希）、`pre_existing`（bool）、`disposition`（open/fixed/false_positive/intentional/ignored）、`verification`；③ 状态映射：阻断性 Critical = `Critical ∧ pre_existing!=true ∧ disposition未关闭`；`pre_existing=true` 的 Critical 降级为 WARN 下限（记录存量，不静默放行）；带签字与取证的 `false_positive` 降级为 WARN；重复 fingerprint ⇒ 校验器 FAIL；④ 轮次收敛：round >= 4 必须提供 `--escalate-to` 与 `--escalate-reason` 升级复议，否则拒绝放行；⑤ 首轮后支持 `--delta-only` 差量复审；⑥ 缺省 `schema_version: 1` 维持既有全阻断逻辑，存量历史报告 100% 兼容。③ **被否**：把 disposition 做成无需签字的口头开关（开严重安全后门）；由模型自审关闭 Critical（违背独立审查原则，必须人/架构签字）。④ **钉与变异**：`tests/test_review_report.py` +4、`tests/test_cli_review_convert.py` +3（含 `test_fingerprint_stable_across_line_numbers`：行号漂移后指纹必须不变、内容不同指纹必须不同——评审抓到 CLI 恒产 `path:12-15` 而旧正则剥不掉 ⇒ 去重门永不命中）、`tests/test_gen_e2e_scripts.py` +1；变异 **M130**（摘掉 pre_existing 豁免退回原写死 FAIL ⇒ 钉红）、**M130b**（摘 `validate_review_report` 的 fingerprint 去重段 ⇒ 重复指纹钉红）、**M130c**（`clean_target_file` 行号正则退回 `:\d+$`，剥不掉 CLI 恒产的 `path:12-15` ⇒ 指纹稳定性钉红），四段协议（基线绿→注入红→逐字节还原→复绿）全部通过、还原 sha256 逐字节一致。全量测试通过。 |
| D130 | E2E 环引入 **前端适配版 C01-C14 覆盖维度矩阵** 与缺口对账（2026-10-21；`rings/e2e/reference.md` §5.1/§5.2/§5.5/§8.2；`_support/case_block.py`、`validators/validate_e2e_index.py`、`templates/prd/domain.md`、`templates/e2e/case-shard.md`） | ① **病灶**：原「AC 反向覆盖门」仅能回答「每条 AC 是否至少被一条用例指向」，**无法回答每条 AC 的异常流、边界值、权限、会话恢复、幂等、状态转换等高危场景是否覆盖**；导致 Agent 生成大量表面正向用例，真正易崩场景系统性遗漏。② **定案**：① 前端适配裁剪版 C01-C14 场景维度闭集（C01正常流、C02异常流、C03边界值、C04权限、C05并发、C06重试、C07审计、C08会话恢复、C09一致性、C10依赖容错、C11幂等、C12输入校验、C13状态转换、C14安全）；② 用例分片块体增加可选数组字段 `覆盖维度:`，单源解析器 `_support/case_block.py` 纳入键空间；③ 域级 PRD 验收标准表增加可选第 4 列 `适用覆盖维度`（如 `C01, C02`），前三列保持不变；④ 校验器 `validators/validate_e2e_index.py` 增加「AC × 覆盖维度」对账项：已声明但未全量覆盖 ⇒ WARN；未知维度词 ⇒ WARN；未声明第 4 列的项目 ⇒ N/A 兜底，绝不产生破坏存量的永久红门；⑤ 控制台 snapshot case 对象透传 `dimensions` 字段。③ **被否**：在 PRD 新建第 4 张手工对账表（严重违反 single-source 契约，且会与 AC 唯一性定义门发生行号碰撞）；对所有 AC 强制 14 维度全覆盖（引发无脑生成几十条形式用例的膨胀灾难）。④ **钉与变异**：`tests/test_validators.py` 增加 `test_e2e_index_coverage_dimensions_pass_and_warn`（N/A / WARN / PASS 三态验证）；变异 **M131**（摘掉 dimensions 聚合回落全 PASS ⇒ 钉红），还原逐字节一致。全量测试通过。 |
| D131 | 收口契约引入 **变更风险定档、Always-Human 路径、修复验证 7 检查点与事故追问闭环**（2026-10-21；`shared/closeout.md` §2 步骤 3/4/11；`duty-review/README.md` §2；`templates/reviews/README.md`） | ① **病灶**：① 收口阶段缺乏系统性风险定档，高危底层改动（如权限、路由、CI、包依赖）容易被 Agent 自述误导而跳过严格人工亲测；② 缺陷修复任务（bug fix）常直接修改业务代码并自报已修复，缺乏「先失败后转绿」的 Red First 证明与边界/回归核对，导致同类问题反复逃逸；③ 线上/联调事故复盘停留在修代码，未追问「哪一道门本该接住」，事故没有转化为常态化回归用例或变异钉。② **定案**：① `shared/closeout.md` 补齐步骤 3「变更风险定档与人工审批」：三档风险矩阵，明确 `auth / permission / routing / CI / package deps / shared contracts` 为 Always-Human 永远人工路径，严禁 Agent 代勾放行；② 补齐步骤 4「缺陷修复验证 7 检查点」（复现明确、Red First 先失败测试、最小 diff、边界值、状态机完整、回归范围界定、闭环证据留存）；③ 步骤 11 与 `duty-review/README.md` 引入事故追问机制：每个确认逃逸缺陷必须在 `bugs.md` 标注原因，并在关闭前补齐 E2E 回归用例或 M 系列变异钉；④ 提供 `templates/reviews/README.md` 代码审查指引轻量模板（≤10 行，聚焦失败特征与证据链）。③ **被否**：用文件名/正则做脆弱的机器强制路径阻断脚本（极易被重命名或参数绕过，且易对合法改动造成假阻断）；由 Agent 自动签署审批（违背人类作为最终交付负责人的第一原则）。④ **钉与变异**：`test_canonical_consistency.py` 计数与跨文件一致性全量跑绿。 |
| D132 | 新增 **E2E hash 查询参数契约**（`hash参数:` + `e2e.query_preset.hash_keys`）（2026-10-22；`rings/e2e/reference.md` §5.5/§5.7/§8.2；`shared/stack-profile.md` §2；`_support/case_block.py` / `_support/url_merge.py` / `scripts/gen_e2e_scripts.py` / `validators/validate_e2e_index.py`） | ① **病灶**：HashRouter 页面的 `useSearchParams` 只读 `#` 之后的查询段；D109 `参数:` 只覆盖 `#` 之前的常规查询，`会话:` 是 sessionStorage，导致快照页这类「`#` 后查询前提」用例无合法写法，只能手补生成物（重跑即丢）。② **定案**：`hash参数:` 只声明键，值内联在 `goto` 的 hash 查询串；白名单 `query_preset.hash_keys`；守卫导航把同一段 hash 查询追加到 hash 段（`append_hash_query`），base query 仍在 `#` 前；零步基线不施加；路径门两侧 `strip_queries` 后比对；同键不得跨 `参数:`/`会话:`/`hash参数:` 双写。③ **被否**：把 `#` 后查询硬塞进 `参数:`（会丢 hash 段 / 与 base query 合并语义冲突）；项目侧手补生成物（不可重生成，属已否的 D98 类补丁）。④ **钉**：生成器 6 条 + 校验器 7 条（含 `test_hash_param_carried_to_guard_and_goto`、`test_zero_step_baseline_carries_no_hash_param`、`test_hash_query_merge_helpers` 与正向/未白名单/白名单外/死声明/值形态/未声明 hash 键/双载体）；`tests/test_validators.py` 计数 138 已登记 `shared/gates.md`。 |
| D133 | `value` 断言/探针改读**可见文本**，排除触发器内的视觉隐藏 a11y 镜像（2026-10-23；`scripts/gen_e2e_scripts.py` 发射点；契约 §5.5 `value` 行） | ① **病灶**：`value` 对非原生控件用 `innerText` 读触发器文本。Ant Design Select 在用户交互后向触发器内注入 `aria-live="polite"` 的无障碍播报 span（`width:0;height:0;opacity:0`），其文本与选中项相同；`innerText` 不排除视觉隐藏节点 ⇒ 选中文案被读两遍（现场：`模式一…\n模式一…`），同一标签的 `value` 断言在交互后必红，而交互前同断言正常（基线 green / 动作后 red 的假红）。契约本体写的是「触发器**可见**文本」，实现与契约不符。② **定案**：新增发射期助手 `atlasVisibleText(loc)`：采值前遍历触发器子树，用 `checkVisibility({opacityProperty:true,visibilityProperty:true})`（缺 API 时退 `getComputedStyle`）判定，把不可见节点的 `style` 暂存后置 `display:none !important`，读 `innerText` 后**按逆序逐字节恢复 style**（`try/finally` 覆盖异常路径），保留 `innerText` 的排版归一半径；`atlasValueOf`（探针，含三态语义）与 `atlasExpectValue`（正式断言，改用 `expect.poll` 保留轮询）统一走该助手；原生 `input/select/textarea` 的 `toHaveValue` 路径不变。③ **被否**：按 `aria-live` / `aria-hidden` 选择器硬排除（只治 Ant Design 一处，其他组件库的视觉隐藏节点仍会污染；`aria-hidden` 还可能承载可见文本）；读 `textContent`（会把 `display:none` 的隐藏下拉项也算进来，扩大假绿面）；对读数做去重（同一文案合法重复出现时无法区分，属语义猜测）。④ **钉与变异**：`tests/test_gen_e2e_scripts.py::test_value_reads_visible_text_excluding_a11y_mirror` —— 从生成物抽出助手源码，在 Node 里以假 DOM **真求值**：可见项 + `opacity:0` 的同文案播报项 ⇒ 只返回一次；采值后隐藏节点 `style` 恢复为 `null`；同时钉发射面含 `atlasVisibleText`、不再出现 `toHaveText(v, { useInnerText: true })`。 |
| D134 | 新增 E2E **`type` 逐字输入动词**（2026-10-23；契约 §5.5；`scripts/gen_e2e_scripts.py` / `validators/validate_e2e_index.py`） | ① **病灶**：Playwright `fill` 一次性写 DOM、只触发 `input`，不触发带掩码 / 受控输入组件的内部解析（现场：Ant Design RangePicker 日期输入，文本可见但保存 payload 无 `startTime/endTime`）；逐条 `press` 每次先 focus、只发单键，无法形成连续输入链（实测同样不提交）⇒ 项目侧只能留人工或用 `_support` 钩子代输入（步骤不可见、绕过 DSL）。② **定案**：`type <tid> <text>` → `locator.pressSequentially(text)`，逐字触发 `keydown/keypress/input`，**不先清空**原值（替换语义用 `fill`）；值必填，空值 ⇒ 生成器报错中止；动作词表 13 → 14，校验器词表同步，样例守恒表 +1。③ **被否**：用 N 条 `press` 拼输入（不可读且实测不提交）；`_support` 钩子代输入（步骤不可见、绕过 case DSL）；移除产品侧掩码（UX 变更、超出 E2E 能力面）。④ **钉**：`test_type_verb_emits_press_sequentially_without_clearing`（发射形态 + 空值中止 + `[N]` 定位）与 `test_e2e_index_type_is_action_not_assertion`（step 侧放行 / expected 侧拒收）；变异 **M134**（摘生成器 `type` 分支 ⇒ 钉红）。 |
| D135 | testid 提取器容忍 **`setAttribute` 尾逗号**（2026-10-23；`validators/validate_testids.py`；F22 扩展） | ① **病灶**：Prettier `trailingComma: all` 会把多行 `el.setAttribute("data-testid", "x")` 写成尾逗号形态（`"x",\n)`），旧正则要求 `"x"` 后紧邻 `)`，导致已实现 testid 被判缺失、双向集合 FAIL（现场：邮件面板 RangePicker 日期输入的多行 setAttribute）。② **定案**：`SETATTR_TESTID` / `SETATTR_TESTID_TPL` 在值后允许可选 `,`；与静态属性同档，不改变 counts / 页面归属。③ **被否**：项目侧改成单行调用（lint-staged 的 Prettier 仍会加回尾逗号）；把 testid 挂到 RangePicker 容器（`fill` / `value` 指不到内层 input）。④ **钉**：`test_f22_imperative_testid_extraction_and_counts` 增加多行 + 尾逗号样本（Red First：修前 `notes-avatar` 缺失；修后抽取成功）；变异 **M135**（去掉 `,?` ⇒ 钉红）。 |




---

## 13. 待实现事项

> **状态单一真相源（硬）**：本节**不复述各项的推进状态** —— 复述必漂，实例：2026-09-28 两轮独立审计都在本节抓到**陈述与实况相反**。
> **进度与下一步**随每轮实际产出就近登记；门的取证等级 = `shared/gates.md`。
> 本节只留**确知仍开、且不属批 6** 的项（机器判据：本节不得出现落地状态词，见 `tests/test_canonical_consistency.py` 判据 ④）。

1. **真栈收口**（E1 单段）：E2E 真跑门**已于 2026-10-04 逐页真跑并咬出真红**（`shared/gates.md` 2.2「E2E 真跑」行，`3508 §166`/`§187`/`§190`——2026-09-28「暂不真跑」裁定（`3508 §111`）已被执行反推）；**协议定形首跑已完成（2026-10-17，百炼/v3 platform-frontend：1 app × 1 页最小切片全绿 11/11，留档采纳仓 `product/e2e/reviews/2026-10-17/`，咬合证据登记 gates 2.2 行）**；确知仍开 = ① **E0 产物残留重生成**（绑真跑准备日一次清，`shared/single-source.md` §3）。

---

## 14. 未决项（实现前定）

- ~~`stack-profile.yaml` 的最终字段集（当前为草稿）~~【已定稿 **D99**（2026-10-17）：冻结现行实现实收面为 v1，后续字段变更一律起独立决策行】。
- ~~是否启用 git pre-commit 作为校验兜底~~【已结 **D100**（2026-10-17）：不启用，留待 CI 一起落】。
- 地址唯一来源 = `e2e.app_base_url`（E1 单段）；`prototype.base_url` / `prototype.serve_command` 随原型环退役。
- "本次需求影响哪些页面"的识别：由 `apply` 按 **D61** 从需求文本 + 结构基线路由表 + 索引页面表**语义推导**，产出结构化影响面清单；低置信 / 歧义 / 映射不到时**一次性 ≤3 问**向用户确认（不猜、不用 regex 判语义）。
- 多 app 仓库（monorepo）下 `product/` 是单份（产品维度）还是按 app 分片，待第一个 monorepo 场景出现时定。
