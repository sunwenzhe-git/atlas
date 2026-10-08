# atlas — 项目级工作流设计

> 状态：设计定稿 + 决策记录（**历史与依据**）。**操作契约的唯一权威** = `.atlas/shared/` + `.atlas/rings/*/reference.md` + `.atlas/apply/reference.md` + `.atlas/skills/*/SKILL.md`；本文与它们冲突时以操作契约为准，设计依据见知识库（vault `atlas/`）。
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
│   │   ├── global/                  #   directory-map / routes / design-tokens
│   │   └── {current,legacy}/<domain>/{apis,data-models}.md
│   └── tasks/<NN-slug>/             # 需求级：prd.md = 需求卡；task id = 需求 ID
├── .atlas/                          # atlas 包（install.sh 装配；包产物）
│   ├── shared/                      #   共享契约（三环共同遵守）
│   ├── rings/                       #   各环执行契约 reference.md
│   ├── apply/                       #   跨环增量契约
│   ├── scripts/                     #   refresh_structure.py（事实区刷新；after_finish hook）
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

**7 类内容（5 入 `.trellis/spec/structure/`：B–F，D 条件；A / H 落项目根 `README.md`）**：

| # | 类别 | 性质 |
|---|---|---|
| A（可选） | 技术栈 + 启动方式（端口、依赖、启动/停止、已知坑）；落点 = **项目根 `README.md`** | 约定 |
| B | 目录与模块地图（每模块一句话职责） | 事实 + 语义 |
| C | 路由与页面清单（路径、用途、关键交互、实现状态） | 事实 |
| D（条件） | 接口清单（方法、路径、请求/响应要点、来源模块）；有机器可读描述时只记真相源入口 | 事实 |
| E | 数据模型清单（表/字段/关系/枚举） | 事实 |
| F | 设计 token 清单 | 事实 + 语义 |
| H（条件） | 测试现状与运行方式；落点 = **项目根 `README.md`**（README 已有则不动） | 事实 |

> G（testid / selector 约定）归 **E2E 环**；I（编码规范）不由 atlas 收口——两者均移出 structure（决策 D35）。

**域模型（本环负责提议）**：本环按路由/页面簇、模块簇、表/模型命名簇、接口路径前缀**聚类出候选域**，写入 `.trellis/spec/structure/_meta.json.domains`（含域 → globs；人读视图在 `tour.md` 域速查表）；PRD 诊断阶段读它并**定稿回写**。**域 id 是全链路键**（PRD / E2E / 注入 spec）。

**两层结构**：全局层 `global/`（`directory-map` / `routes` / `design-tokens`）+ 域级层 `{current,legacy}/<domain>/`（`apis` / `data-models`）。仅 `tour.md`（L1，`paths ['**']`）与 `domains/<d>.md`（L2，域 globs）带 `paths:` 被注入；其余事实文档无 `paths`、按需 Read。A（技术栈）与 H（测试）落项目根 `README.md`。

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
├── scripts/                         # refresh_structure.py（结构事实区刷新；after_finish hook）+ gen_e2e_scripts.py + gen_testid_stub.py + make_review_inputs.py + atlas_check.py + e2e_console.py + mutation_proof.py
├── patches/workflow-plan-apply/     # 锚点补丁：往 workflow.md 插 1.6 + 面包屑 enforcement
│   ├── spec.json                    #   补丁载荷
│   ├── apply-patches.py             #   锚点式幂等应用器（复用现有模式）
│   └── *.insert.md                  #   插入片段
├── patches/project-wiring/          # AGENTS.md 指针段 + after_finish hook（幂等）
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
  tokens: <adapter 名 | null>
  tests: <adapter 名 | null>
```

未声明适配器（`null`）的类别，退回 agent 撰写。

### 9.3 适配器

- 只负责"从代码抽取可枚举事实"，输出结构化的中间产物，不写文档。
- 按栈实现，如 `vue-router`、`fastapi`、`sqlalchemy`、`pyxle`、`electron` 等；命名不绑定具体项目。
- 没有对应适配器的技术栈：该类别由 agent 撰写，并在结构基线里标注为"人工维护"。

### 9.4 安装产物

`install.sh` 在目标项目里落地：

1. **整包 → `<目标>/.atlas/`**（`shared/`、`rings/`、`apply/`、`templates/`、`adapters/`、`validators/`、`patches/`、`tests/`）；属包产物，默认刷新。
2. 每个 `skills/atlas-*/` → 各平台 skill 目录（瘦桩 `SKILL.md`，指回 `.atlas/`）；并清理历史单入口 `atlas` skill。
3. `.trellis/workflow.md` 的 Plan 步骤补丁（锚点幂等；`--no-patch` 可跳过）。
4. `product/` 目录骨架 + `stack-profile.yaml` 模板（既有内容永不覆盖）。
5. **项目接线**（`patches/project-wiring/`，幂等；`--no-wiring` 可跳过）：`<目标>/AGENTS.md` 的 `<!-- ATLAS:START/END -->` 指针段（置于 Trellis 区块**外**，不被 `trellis update` 覆盖）+ `.trellis/config.yaml` 的 `after_finish` hook（`refresh_structure.py`）。补的是「新项目 agent 一开会话就知道本项目用 atlas、契约在哪、需求级怎么走」的入口（D73）。
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

**实现状态**：7 个校验器（`validate_{structure,stack_profile,prd,testids,e2e_index,ledger,design_exemptions}.py`）+ `scripts/atlas_check.py`（门总览：校验器 / 出厂测试 / 生成物 / 真跑，**一门一行 `ok|FAIL|WARN|SKIP`**）。

**门总账与收口清单（2026-09-28 落地，`3509 §B112`/`§B114`）**：所有门登记在 `shared/gates.md`（含**对账平面 / 显式盲区 / 验证预算 / 假绿测试取证等级**三列）—— **不在表 = 不存在**；人侧收口步骤表 = `shared/closeout.md`（此前被多处定形引用却长期不存在）。`SKIP` 是**一等结论**（未就绪），不是通过。

---

## 11. 接入起点（新项目）

**最小可用基线**（不必等全站建完）：

1. `stack-profile.yaml` + 约定类结构（A / G / I）；可选启用知识库同步（`knowledge` 段，见 D71 / `shared/knowledge.md`）。
2. PRD 骨架（定位 + 用户 + 已有功能条目）或（绿地时）仅产品定位。
3. E2E：空索引 + **页面表**（未实现页记 `未开始`）+ 校验脚本可用。

**启动顺序按项目现状自适应**：

| 项目形态 | 顺序 |
|---|---|
| 绿地（`origin: greenfield`，等价入口 `apply all`） | stack-profile + 约定 → PRD 骨架 → 空索引 + 页面表 → 开始接需求（事实类随代码由适配器补齐） |
| 重构 / 存量（`origin: adopt`，`apply adopt` 开户） | legacy structure 事实（适配器抽取）→ PRD 开到「开户最小集」（只登记基线，不全量重述）→ 不预设 E2E（由后续需求按三问门长出）→ 开始接需求 |
| 纯存量自描述（`origin: adopt`） | structure 事实 + PRD（当前功能条目，开户最小集）→ 不预设 E2E → 开始接需求 |

存量两行的 E2E 口径 = `apply/reference.md` §1 adopt 教义（开户不预设 E2E；E1 原型环已移除），2026-09-29 对齐（`B146-1`）。

**绿地为什么是友好的**：事实类内容由适配器从代码生成，**没代码就没有事实**，不是"没建完"；而 E2E 先行在绿地上价值更大——用例本身就是规格。

---

## 12. 决策记录

> **E1（2026-09-27，原型环移除）作废的决策**：D8（两段式执行模型）、D45（依据来源含原型）、D46/D47（页面 = 原型文件名 / testid 双向锚原型）、D48（`执行目标` 字段，另已于 2026-09-23 退役）、D49–D53 中依赖原型的部分、D54–D59（原型产物布局 / URL / 交互分级 / 生成流程 / 应然 token / 原型环范围）、D67（`validate_prototype.py` / `serve_prototype.py`）。**D68 部分有效**（生成器已落地，两段式部分作废）。**现行口径**见 `.atlas/shared/` + `rings/*/reference.md`；历史依据见知识库 `3508 §92`。下表保留原文，供追溯「当初为什么这么定」。

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
| D41 | 适配器消费规程与产物落点 | 适配器**不自动改写文档**：由 structure 环 agent 按 **global 类别整项目一次 / 域级类别按 app 各一次** 调用，JSON 落 `<项目根>/.trellis/spec/structure/.adapter-out/<category>[/<app>].json`（中间产物、非真相源），再读 JSON 渲染事实表 + 补语义列。「事实区自动渲染 + 表→域映射」为后续独立项 |
| D42 | 适配器口径补齐（第二批） | ① `api`：Swagger 描述（落盘或运行时 `spec_entry`）→ 指针，无描述才源码抽 `@action`/装饰器清单；**不收**出站调用与前端 client 调用；② `tokens`：只抽样式表自定义属性，`kind` 加第 6 值 `other`；③ `tests`：`type` 定 `unit\|integration\|e2e\|other`，`status` 留空由 agent 补 |
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
| D69 | 事实区自动渲染（C7） | `refresh_structure.py --apply` 读 `.adapter-out/*.json` 自动重写事实区表：**行键级单元格合并**（适配器填可枚举列、既有行**语义列保留**、新增行语义列留空→校验器 WARN、消失行移除）；归属 = 条目 `source_file` → app（最长 path 前缀）→ role（`landing`→`current/`）→ 域 globs（最长命中），**无命中落 `global/{apis,data-models}-shared.md`**；无 `.adapter-out/` 时跳过（agent 维持） |
| D70 | 适配器脚手架与指南 | 新增 `adapters/_scaffold.py`（可复制填空的适配器模板，强制 `source_file`）+ `adapters/README.md`（契约 §3 落成步骤）；把「无适配器 → `null` → agent 撰写」作为**一等降级**；`models` 条目补 `source_file`（支撑 D69 域归属）。**框架知识只允许出现在适配器内** |
| D71 | 知识库（Obsidian）维护契约（2026-09-20） | 新增 `shared/knowledge.md`：知识库保存**设计依据与讨论**（「为什么这么定」），与产物分层、不复制正文。**可选增强**——`stack-profile.knowledge.vault` 为 `null`/缺省 ⇒ 整体跳过、不阻断任何环。写入/检索**经 open-zk-kb MCP**（不手写 vault 文件）；vault 内**唯一 atlas 设计目录**（跨项目共用，不按项目分目录）。四环与 `apply` **收口必做**（`global-rules.md` §9）；只写持久设计与依据（决策/讨论/被否/纠正/未决），不写进度与产物正文；契约变更**仓库 canonical 与知识库两处同改**。`stack-profile` 增 `knowledge` 段（`tool/vault/dir/project`）；`install.sh` **不写用户 vault**（只落 profile 草稿 + 自检契约存在） |
| D76 | 设计档案契约登记 + 豁免机器对账门（2026-10-08，`3508 §200` / `ATLAS-UPSTREAM #182`） | `product/design.md`（视觉设计档案）登记为项目级应然文件：**写者 = frontend-design skill**（atlas 包外；atlas 不生产、不覆盖、只读两个触点）——① 走查单确认门前对照视觉方向一致性（`rings/prd/reference.md` §4·八）；② 档案「已有豁免」的 `detect:<rule-id>` 必须与 `.impeccable/config.json` 的 `detector.ignoreRules` **双向集合相等**，新校验器 `validate_design_exemptions.py`（无档案 ⇒ SKIP 三态；变异 M43）。缘起：档案生于 frontend-design skill 吸收 impeccable 精华（`3508 §199`），项目根落点撞 atlas 产物归属与 `DESIGN.md` 契约名 ⇒ 用户拍板固定落 `product/`。被否：按 `.atlas/` 存在与否嗅探两种落点（双落点 = 漂移面）；校验器内嵌 impeccable 规则表（第三方升级会误伤） |

| D72 | 职责边界 = 约束层（2026-09-22，对标 Harness） | atlas **只收口约束层**（应然资产 / 唯一事实源 / 三类入口），Harness 其余四层按阶段分工、不并入：① 对抗验证——atlas 只审自身产物（当前 `prd review`），实现代码审查归 Trellis；② 证据层——只留确定性校验器 + E2E 状态机，可视化报告与「测试覆盖状态跳转」检测延后（依赖 B4）；③ 状态写入——只记影响面与 `atlas-apply.md`，目标复述 / 长任务持久化归 Trellis；④ 边界对齐——atlas 侧 = 确认门 + 完成门 + apply 覆盖门，CI 分级与回滚延后（依赖 B4）。**G1 原型/E2E 审查、G2 可视化证据、G3 CI·回滚登记为未决（`3509 §C8–C10`），实跑后按证据 promote**。理由：Harness 是项目跑了两个月的事后归纳（非蓝图），atlas 尚未端到端跑通一条需求（`3509` 批 6 登记（该机制原属 §13 待实现事项；§13 现只放指针，逐项状态以 `3509` 为准）），在未运行的设计上预置机制是拿猜测赌契约。详见 §3.1 |
| D73 | 项目接线自动化（2026-09-22） | 新增 `patches/project-wiring/`（`apply-wiring.py` + `agent-pointer.md` + README），`install.sh` 作为第 6 步装配（幂等、`--no-wiring` 可跳过）：① `<目标>/AGENTS.md` 在 `<!-- TRELLIS:END -->` **之后**写 `<!-- ATLAS:START/END -->` 指针段——位于 Trellis 区块**外**故不被 `trellis update` 覆盖；② `.trellis/config.yaml` 幂等登记 `after_finish` hook。**修的是两处此前靠手工、且升级会被冲掉的接线**（install.sh 原本完全不碰 AGENTS.md）。回归测试 `tests/test_project_wiring.py`（11 用例）。属 `global-rules.md §7` 确认门动作，由显式安装触发 |
| D74 | 定位表述定稿：身份 ≠ 实现分工（2026-09-29，`3508 §129` 设计树 A–F） | **身份** = atlas 是覆盖「立项 → 需求 → 应然资产 → 实现 → 验收 → 收口」的**全流程 vibecoding 工作流**，项目级应然资产跨项目分发、机器可校验；**实现分工** = 「需求级执行」由执行器承担（**当前 = Trellis**，依附其官方可改面，不改状态机与 hook 解析），执行器可替换是未来可能而非现行契约。改面：`README.md` 开场 + §定位（删「分层正交」作身份表述——它降为产物分层的实施细节，归 `DESIGN.md` §3/§8）；`patches/project-wiring/agent-pointer.md` 标题与首行同步（重装配后注入各业务仓库 AGENTS.md）。被否：把「atlas = 项目级资产层」当身份（一次分工决策 D72 静默改写身份，实证 `3508 §129`）；「执行器 adapter」先行（无实跑取证） |
| D75 | 知识库双通道 + KB 投影对账门（2026-09-29，`3509 §B116`/`§B121` 拍板「按推荐走」） | **双通道**：短 note 经 MCP（store/get），**长 note 定点/批量修订直接编辑文件** + 收口跑 `kb_index_refresh.mjs` + `kb_projection_check.mjs` 对账（`shared/knowledge.md` §3 重写；原「不手写 vault 文件」与历轮实践矛盾，且 open-zk-kb 无文件监听 ⇒ 手改不重索引会静默漂）。**对账门**：`atlas/scripts/kb_projection_check.mjs` 用包内解析器逐篇逐字段比对投影（`.index/knowledge.db`）⇔ vault 本体，四类漂移指名，入 `gates.md` 2.1（测试 + 三类变异咬合）；`atlas_check` 对校验器 WARN 行从静默当 ok 改为显式 `WARN` 行。配套：`embeddings:{enabled:false}` 落 `~/.config/open-zk-kb/config.yaml`（本机不可达 HF CDN，local 兜底使 rebuild/embed 每次白试下载 = MCP 超时根因）。被否：坚持 MCP 单一通道（唯一可行通道就是直接编辑，实证 `§B116` 硬证据）；拆短 note 方案（丢历史、覆盖风险） |

---

## 13. 待实现事项

> **状态单一真相源（硬）**：本节**不复述各项的推进状态** —— 复述必漂，实例：2026-09-28 两轮独立审计都在本节抓到**陈述与实况相反**。
> **批 6（契约改造批）的逐项状态 = 知识库 `3509` 的「批 6 登记」节**；进度与下一步 = 知识库 `3508` 顶部的「当前进度 / 待办」节；门的取证等级 = `shared/gates.md`。
> 本节只留**确知仍开、且不属批 6** 的项（机器判据：本节不得出现落地状态词，见 `tests/test_canonical_consistency.py` 判据 ④）。

1. **首次真栈执行**（E1 单段）：`e2e.app_base_url` 就绪后重生成 `product/e2e/scripts/` 并跑全量用例（首跑分类协议见 `rings/e2e/reference.md` §5.4）。当前**未发生**（用户 2026-09-28 裁定暂不真跑，`3508 §111`）。

---

## 14. 未决项（实现前定）

- `stack-profile.yaml` 的最终字段集（当前为草稿）。
- 是否启用 git pre-commit 作为校验兜底。
- 地址唯一来源 = `e2e.app_base_url`（E1 单段）；`prototype.base_url` / `prototype.serve_command` 随原型环退役。
- "本次需求影响哪些页面"的识别：由 `apply` 按 **D61** 从需求文本 + 结构基线路由表 + 索引页面表**语义推导**，产出结构化影响面清单；低置信 / 歧义 / 映射不到时**一次性 ≤3 问**向用户确认（不猜、不用 regex 判语义）。
- 多 app 仓库（monorepo）下 `product/` 是单份（产品维度）还是按 app 分片，待第一个 monorepo 场景出现时定。
