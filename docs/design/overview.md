---
title: 全流程设计总览
description: Atlas 覆盖「立项 → 需求 → 应然资产 → 实现 → 验收 → 收口」的全流程工作流设计总览：三大基础设施、两层正交模型、三环 + apply 闭环，以及贯穿全程的门与机器校验。
---

# 全流程设计总览

> Atlas 是覆盖 **「立项 → 需求 → 应然资产 → 实现 → 验收 → 收口」** 的全流程 AI 编程工作流。它全部活在业务 Git 仓库内、跨项目分发、机器可校验。
>
> 本页是设计的**总纲**：讲清工作流怎么开始、稳态循环长什么样、门位在哪、各环如何分工。三环与 `apply` 的细节见文末导航。

---

## 一、三大基础设施鼎立

Atlas 不重造执行与测试引擎，而是站在三件成熟基础设施之上，把它们编织成一条可对账的流水线：

1. **Trellis（执行基础设施）**：承担需求级任务生命周期——分阶段 Plan / Execute、Spec 路径原生注入与上下文管理。Atlas 严格遵守 Trellis 的约束（不新增状态、不改 hook 解析逻辑），只通过**锚点补丁**在 Plan 阶段插入一步。
2. **Playwright（验收基础设施）**：承担真实靶场的交互验证与端到端回归。现已**单轨定型为 Node-Playwright**（`@playwright/test`），python-playwright 整体退役。
3. **CGC（CodeGraphContext，MIT）代码拓扑基础设施**：承担全仓 AST 代码知识图谱构建与**有限的双消费面**（routes 文件枚举通道 + advisory 影响面基准）；事实抽取与域聚类**均不走图谱**（域 = 多信号投票，`rings/structure/reference.md` §2.1）——边界定形见 `DESIGN.md` D77/D78；用前现刷新鲜度防线与 impact 影响面对账照常承担。

> 三者在仓库里的落点：执行契约 `.trellis/`、验收产物 `product/e2e/`、图谱隔离层 `.atlas/adapters/_graph.py`。

---

## 二、两层正交：项目级平面与需求级平面

Atlas 的核心结构是**两层正交**（也常被称作**双线束模型**：Agent Harness 与 Project Harness）——两层的职责互不嵌套：

| 平面 | 回答什么 | 内容物 | 归属 |
|---|---|---|---|
| **项目级平面** | 这个产品**是什么**、**长什么样**、**怎么算做对了** | 结构事实 / 项目级 PRD / E2E 用例与索引 | Atlas |
| **需求级平面** | **这一次**改什么、怎么改、改完怎么验收 | 需求卡（Trellis task）、业务代码实现 | Trellis |

- **项目级**跨需求持久存在，是机器硬门禁的宿主，只定应然、不写业务实现；
- **需求级**随任务归档、上下文重置，只对当前这次修改负责；
- 两层之间由 **`apply` 单向衔接**：需求先落进项目级应然，再进实现（前置而非后补）。

> 想深入理解这套 Harness 概念，见 [双线束模型：Agent Harness 与 Project Harness](/concepts/architecture)。

---

## 三、四个起点：应然资产怎么开起来

入口取决于项目现状，但**都要先跑一次 `atlas init`**（等价于 `install.sh` 装配）。装配的内容在所有项目里完全一致：

- **atlas 包本体 → 项目的 `.atlas/`**：全套契约（每个环的 `reference.md`）、模板、校验脚本、适配器（含图谱隔离层 `_graph.py` 与 `impact_report.py`）、`_support/` 内核整包复制。这是日后所有规则与机器校验的**唯一正本**，skill 与文档都指回这里，不存第二份。装配完成生成 `.atlas/VERSION` 装配版本戳（内容摘要比对）。
- **skill 瘦桩 → 平台 skill 目录**：装一组轻量入口文件（`atlas-structure` / `atlas-prd` / `atlas-e2e` / `atlas-apply` / `atlas-design-review`）。**「桩」**是平台只有看到 SKILL.md 才能触发能力；**「瘦」**是文件本身不装规则，第一步就指回 `.atlas/` 正本，避免两处漂移。
- **Plan 步骤锚点补丁 → `.trellis/workflow.md`**：在 Phase 1 末尾插入 `#### 1.6 项目级资产更新`，让每条需求在进实现前必须先跑 `atlas apply`。补丁对准 Trellis 模板里的稳定标记插入，用带指纹的开始/结束标记包住，幂等可重放。
- **两处接线**：`.trellis/config.yaml` 加 `after_finish` hook（任务收口后自动刷新结构事实，刷新前强制用前现刷）；项目 `AGENTS.md` 加一段指针，agent 一进场就知道 atlas 在哪、入口是什么。

装完后**唯一要人做的**：填 `product/stack-profile.yaml`——它是 Atlas 认识这个项目的唯一入口档案，核心只读它，契约与模板里都不写死任何具体框架名。

| 项目形态 | 起点 | 启动顺序 |
|---|---|---|
| **全新（绿地）** | `apply all`（幂等、断点续跑） | stack-profile + 约定类结构 → PRD 骨架 → 空索引 + 页面表 → 开始接需求（事实类随代码由适配器补齐） |
| **重构 / 存量** | `apply adopt` 开户 | legacy 结构事实（适配器 AST/正则逆向抽取 + 多信号投票候选域；图谱为可选文件枚举增强，`DESIGN.md` D77）→ PRD 开到「开户最小集」→ **不预设 E2E**，由后续需求按三问门长出 → 开始接需求 |
| **纯存量自描述** | `apply adopt` 开户 | 结构事实 + PRD（当前功能条目，开户最小集）→ 同样不预设 E2E → 开始接需求 |
| **已接入项目的日常** | 无独立入口 | 就是下面这条稳态循环 |

---

## 四、稳态循环：一条需求的一生

每提一条需求走一遍；上面四种起点开好户后，最终都汇合到这条循环：

```text
Trellis 开需求卡（.trellis/tasks/<需求ID>/prd.md；ID = task 目录名，不另建 inbox）
   ↓
① atlas apply <需求ID>   ←— Trellis Plan 的 1.6 步自动带上
   ↓   三问门分流：有一条「是」⇒ 拉起对应环；全否 ⇒ 走纯加法旁路，直接到 ②
   ↓   影响面识别（agent 语义判断 + 图谱 BFS 拓扑推导；生成 impact.json 作为预测基准）
   ↓   按需增量：PRD 章节 → E2E 用例分片与索引（新用例先标 red）
   ↓   机器校验全跑（validate_prd / validate_testids / validate_e2e_index）
   ↓   报告 → .trellis/tasks/<需求ID>/atlas-apply.md
   ↓   任一环失败 / 影响面定不下来 ⇒ 停在 planning，不得进入实现
   ↓
② Trellis 实现（业务代码归执行器，Atlas 不碰业务实现）
   ↓
③ 收口：实例 ⑤ 实现代码审查 → E2E red → green → 验收走查门
   → 运行态报错现场留底与结构化证据链快照
   → 收口 impact 预测对账（对账 impact.json vs 实际 git diff）
   → 回写 current/ 结构事实（用前现刷图谱）
   → Harness 自省复盘记录
   → Trellis finish 归档
   ↓
（反向发现上游资产有缺口 ⇒ 已裁决条目攒批，backfill ≤10 条/批灌回，下游重跑重审）
```

**几种旁路**（都是合法路径，不是绕过）：

- **纯加法**：有需求但三问全否 ⇒ 不拉任何环，报告写明「本需求判定：纯加法 / 不启用三环」+ 依据，直接进实现。
- **只改应然资产**：没有需求、评审期修订 PRD / 用例 ⇒ 不建需求卡、不建任务，按 `prd → e2e` 跑受影响集合，清单落 `product/reviews/<日期>-<主题>/`。
- **存量开户**：见上一节，只登记基线、不全量重述。

---

## 五、三环一览

| 环 | 一句话职责 | 驱动方式 | 基础设施依托 |
|---|---|---|---|
| **structure 逆向环** | 读代码产出**实然**结构事实（路由 / 接口 / 模型），落 `.trellis/spec/structure/`；提议候选域 | 适配器抽取（双通道）+ 用前现刷 | **CGC 图谱** + AST 适配器 |
| **prd 产品环** | **应然**业务叙事与验收基准（全局 + 域级）；定稿域边界；AC 用 GWT 三列形态 | Agent 撰写 + 走查单确认门 | Trellis Spec 原语 |
| **e2e 验收环** | 页面分片用例先行；唯一总索引；testid 锚点先行；真实靶场回归 | 生成器派生脚本 + 控制台走查 | **Node-Playwright**（单轨） |

三环之上，`apply` 是**唯一的跨环编排件**：把一条需求精确、可重放、带门禁地编译并灌入项目级资产。此外还有 `product/adr/` 承载**架构决策记录**（编号化、由 Agent 自动撰写），把「为什么这么架构」沉淀为可追溯资产。

---

## 六、门与机器校验

全流程门位：`structure`（实然事实）→ `prd`（应然叙事）→ **走查单确认门** → `e2e`（用例先行）→ 实现 → **实例 ⑤ 实现代码审查 + 验收走查门** → **impact 对账门** → 收口。PRD 与实现之间**有门无环**（不加新环、不恢复原型）。

| 门 | 判据 |
|---|---|
| 三问门（需求级） | ① 是否改动既有能力 ② 是否需要人确认应然 UI / 流程 ③ 是否需要可重复验收——定「这一条需求拉起哪些环」；三问全否 ⇒ 只走 structure + Trellis |
| 环间审查门（硬） | E2E 用例产出后、生成脚本前跑独立审查；有 `Critical` ⇒ 生成器**拒绝写盘** |
| 走查单确认门（硬，人侧） | 改变应然 UI 的需求：域级 PRD 末节「用户旅程走查」获用户确认后才进 e2e 环 |
| 完成门（硬 + 显式例外） | 需求相关用例必须在真实应用上全 `green` 且实例 ⑤ 审查无 `Critical`；做不到的标 `blocked` + 原因与去向 |
| 验收走查门（硬，人侧） | E2E 全 green 后、域收口前：用户在评审控制台逐用例执行 + review；不符 ⇒ 登记差异不收口；**不阻塞后续域开发** |
| 装配版本门（硬，机器侧） | `.atlas/VERSION` 内容摘要比对源包；源包变动未重新装配 ⇒ 响亮 WARN |
| impact 对账门（硬/机器侧） | 收口实际 `git diff` 与 `impact.json` 预测触达集双向对账，差集逐文件指名 |
| 用户确认门 | 覆盖既有产物 / 改 `stack-profile` / 改 `.trellis/workflow.md` / 改通用模板与校验脚本 ⇒ 先取确认 |

**机器侧校验器（现行 9 个）**：`validate_structure` / `validate_stack_profile` / `validate_prd` / `validate_testids` / `validate_e2e_index` / `validate_design_exemptions` / `validate_e2e_mocks` / `validate_ac_alignment` / `validate_adr`，外加对账器 `impact_reconcile.py`、版本核验 `pkg_digest.py`、门总览 `atlas_check.py`。

门的**唯一总账**是 `.atlas/shared/gates.md`（含对账平面 / 显式盲区 / 验证预算 / 假绿测试取证等级）——**不在表 = 不存在**；人侧收口步骤 = `.atlas/shared/closeout.md`。运行 `atlas check` 会聚合执行全部登记校验器，逐门一行输出 `ok | FAIL | WARN | SKIP`，其中 **`SKIP` 是「未就绪」，不是通过**。

---

## 七、手动与自动的分工

人手按键的只有三处：**装包（`atlas init`）、开户（`adopt` / `all`）、backfill 攒批执行**。

日常循环里：`apply` 由 Trellis 锚点自动携带，校验器与 hook 全自动；只有**确认门**（覆盖产物 / 删页 / 改 `stack-profile.yaml`）必须停下来等人。

> 上手指引见 [30 秒快速上手](/guide/quick-start)，门禁机制细节见 [门禁系统](/gates/iron-gates)。

---

## 设计文档导航

- [结构（逆向）环设计](/design/structure-ring)：结构事实、适配器抽取、可选图谱文件枚举与影响面基准（`DESIGN.md` D77）、用前现刷、多信号投票候选域
- [产品（PRD）环设计](/design/prd-ring)：应然两级、AC 契约、走查单确认门
- [E2E 环设计](/design/e2e-ring)：用例分片、总索引、testid 规范与双向校验、状态机与完成门
- [跨项目分发设计](/design/distribution)：包结构、stack-profile、适配器、平台装配、install
