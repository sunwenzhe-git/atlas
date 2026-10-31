---
title: 跨项目分发设计
description: Atlas 是独立工作流包（Git 仓库）+ 安装器，装进任意项目；核心不认任何框架，框架知识全部下沉到 stack-profile、适配器与图谱隔离层。
---

# 跨项目分发设计

> 用户的硬要求：**「我所有的项目都要用这一套工作流」**。因此 Atlas 核心、模板、校验脚本**不得包含任何具体框架名**——框架知识全部下沉到 `stack-profile`、适配器与图谱隔离层。
>
> 契约正文位于 `.atlas/shared/`，本页是设计依据。

---

## 一、包结构（独立 Git 仓库）

```text
atlas/
├── DESIGN.md                设计定稿（SSOT）
├── README.md
├── install.sh               装配到目标项目（整包装配，可重装、可升级，落 VERSION 戳）
├── _support/                单源内核支持库（模块加载 / profile 解析 / 用例块解析）
├── shared/                  三环与 apply 共享契约（唯一副本）
├── skills/                  平台装配单元（瘦桩，指回 .atlas/）
├── rings/                   各环执行契约：structure / prd / e2e（reference.md）
├── apply/                   跨环增量契约：reference.md（apply + adopt + all）
├── patches/                 装配期锚点补丁（见 §五）
├── templates/               stack-profile + prd / 结构 / 用例 / 控制台 / ADR 模板
├── adapters/                各栈事实抽取器与图谱隔离层
├── validators/              机器校验脚本
└── tests/                   回归测试（随件增长）
```

**共享契约 `shared/`（唯一副本）**：

| 文件 | 编码的规则 |
|---|---|
| `global-rules.md` | 无框架名 / 单一真相源 / 幂等 / 占位符 / 取证 / 确认门 / 生命周期 |
| `stack-profile.md` | profile 字段契约（含 `graph` 段）+ 适配器契约（名字 → 脚本解析） |
| `single-source.md` | 真相源登记（含迁移史） |
| `layout.md` | `product/` 布局与 role 语义 |
| `gates.md` | **门唯一总账**（对账平面 / 显式盲区 / 验证预算 / 假绿测试取证等级） |
| `closeout.md` | 人侧收口步骤 |
| `independent-review.md` | 独立审查骨架（多实例共用） |

> 开发地（源包）现已迁入项目内 `atlas/` 目录；`install.sh` 把它装配进各项目 `.atlas/`，skill 与文档都指回 `.atlas/` 正本。

---

## 二、`stack-profile.yaml`（每项目一份）

核心只读它来认识项目。关键字段：

- `product`：产品名（项目级资产的归属维度）。
- `apps[]`：`name` / `path` / `kind`（frontend | backend | fullstack | mobile）/ **`role`**（`landing` → `structure/current/`；`legacy` → `structure/legacy/`）/ `stack`（自由文本，仅展示）。
- `graph`：代码图谱后端隔离配置（`backend: cgc pinned "0.6.13"`），**仅 `adapters/_graph.py` 允许直接调用**。
- `adapters`：`routes` / `api` / `models` / `tests`，`null` = 未提供，该类别降级为 Agent 撰写；声明 `graph` 时 `routes` 自动走图谱通道。
- `e2e`：`runner: node-playwright`（现役单轨，python-playwright 已退役）；`cases_dir` / `index` / `scripts_dir`；`app_base_url`（未就绪 = 生成器报 `not_ready`）；`app_login` 子段；`seed` 子段（含 `mode: enforce | declare` 声明 / 发射解耦开关）。
- `impl_review`：实现代码独立审查配置。

**生成需用户确认**（会影响后续所有环）。

---

## 三、适配器与图谱隔离层

- 只做「代码 → 结构化事实」，**输出 JSON、不写文档**；只读、幂等、失败不产半成品。
- **按事实类别命名**（`routes` / `models` / `api` / `tests`），**框架识别收在适配器内部**；`--root` 传项目根、`--app` 传 app 名；域级类别按 app 各调一次，全局类别整项目一次。
- **CGC 隔离层 `adapters/_graph.py`**：全线**唯一接触图谱工具的模块**。对外提供探测、用前现刷（`ensure_index` 比对 HEAD 与脏文件指纹，维持 `--force` 全量索引）、路径转换与 Cypher 确定性查询。
- **契约正文唯一落在 `shared/stack-profile.md`**（含「名字 → 脚本」的解析顺序）。
- 无对应适配器的技术栈 → 该类别由 Agent 撰写，结构基线标注 `maintained_by: agent`。

---

## 四、安装器（装配到目标项目）

**两种等价入口**：CLI `atlas init`（首次装配）/ `atlas update`（安全刷新），或直接跑 `install.sh`。

- 前置检查：目标项目须有 `.trellis/`；若 profile 声明了 `graph.backend: cgc` 但本机未探测到，输出显式 `[WARN]` 提示安装、不阻断装配。
- **整包 → `<目标>/.atlas/`**：`shared/` / `rings/` / `apply/` / `templates/` / `adapters/` / `_support/` / `validators/` / `patches/` / `scripts/` / `tests/`。属包产物，默认刷新。
- **装配版本戳 `.atlas/VERSION`**：装配时基于源包内容 sha256 合成 16 位摘要，落目标项目 `.atlas/VERSION`（含摘要、时间戳、源包绝对路径）；由 `atlas check` 的「装配版本」门比对检验——源包变动后响亮 WARN 提示重新装配，杜绝静默滞后。
- **skill 瘦桩**：每个 `skills/atlas-*/` → 各平台 skill 目录（瘦桩 `SKILL.md` 指回 `.atlas/`）；并清理历史单入口 `atlas` skill。
- **建骨架**：`.trellis/spec/structure/{domains,global}` + `product/e2e/cases`（**不建** `product/prototype/`）；已有内容**永不覆盖**；`stack-profile.yaml` 已存在则保留。
- **应用 Plan 挂载补丁**：见 §五。
- **项目接线**（幂等、可重放）：① `AGENTS.md` 在 Trellis 区块**之后**写 `<!-- ATLAS:START/END -->` 指针段；② `.trellis/config.yaml` 幂等登记 `after_finish` hook（`refresh_structure.py`）。
- 末尾**自检**：各环契约 / apply 契约 / skill 瘦桩 / stack-profile / 目录骨架 / 补丁标记 / 接线指针 / hook。

---

## 五、锚点补丁（`patches/`）

装配期对 `.trellis/` 做**外科式插入**，用带指纹的开始 / 结束标记包住，幂等可重放：

| 补丁 | 作用 |
|---|---|
| `workflow-plan-apply/` | 往 `.trellis/workflow.md` 的 Phase 1 插入 `#### 1.6 项目级资产更新`（调 `atlas apply`）+ 面包屑 enforcement 行 |
| `workflow-root-cause/` | 首次红灯根因前置排查挂载，确保报错现场不丢失 |
| `workflow-skill-routing/` | 把 UI 合规、落笔纪律、设计决策追问、前端复用优先挂进 `.trellis/workflow.md` 面包屑；D177 起前端复用直接指向 `shared/frontend-reuse.md` |
| `project-wiring/` | `AGENTS.md` 指针段 + `after_finish` hook |

**为什么要写成 Plan 的 `[required · once]` 步骤**：Trellis 的「自动」分两层——hook 注入面包屑是**确定性**的，skill description 命中是**概率性**的；且建 task 前必须获得用户同意。所以只有写成强制步骤 + enforcement 行才可靠。

---

## 六、平台适配

至少覆盖 **Claude Code / opencode / Codex / Pi**：

| 平台 | skill 目录 | 备注 |
|---|---|---|
| Claude Code | `.claude/skills/` | |
| opencode | `.agents/skills/` | |
| Codex | `.codex/skills/` | 探测到 `.codex/` 目录时装；另有 `.codex/agents/` 放子代理 |
| Pi | `.agents/skills/` | 走 extension + prompts |

- skill frontmatter 只用 `name` + `description`（触发短语写进 description）。
- 命名避开 Trellis 保留名（`trellis-meta` / `trellis-spec-bootstrap` / `trellis-session-insight` / `trellis-channel`）。
- **skill 名 = `atlas-<环>`**：一个环一个 skill，各 description 只含本环触发词，**不设单入口 skill**。

---

## 七、需求级挂载（补丁）

`atlas-apply` skill 的 `apply` 模式必须挂进 **Trellis 的 Plan 阶段**，靠 `patches/workflow-plan-apply/` 往 `.trellis/workflow.md` 插入：

1. 一个 `#### 1.6 项目级资产更新` 步骤（调 `atlas-apply` 的 `apply`；`[required · once]`）；
2. 在 `[workflow-state:planning]` 面包屑块里加**一条 enforcement 行**，使其**每轮自动提醒**（Trellis 的 hook 每轮注入面包屑，是确定性的）；
3. Phase Index 的 Phase 1 步骤清单补一行 `1.6`（人读总览）。

理由同上：只有写成 `[required · once]` 步骤才可靠。回归测试双跑验证插入 / 幂等 / dry-run / 锚点缺失保护。

---

## 八、机器校验与命令面

**校验器（现行 10 个）**：`validate_structure` / `validate_stack_profile` / `validate_prd` / `validate_testids` / `validate_e2e_index` / `validate_design_exemptions` / `validate_e2e_mocks` / `validate_ac_alignment` / `validate_adr` / `validate_walkthrough`。

**脚本侧工具链**：`atlas_check`（门总览：校验器 / 出厂测试 / 生成物 / 真跑）、`refresh_structure`（事实区刷新）、`gen_e2e_scripts`（脚本派生）、`gen_testid_stub`（testid 薄桩）、`impact_report` / `impact_reconcile`（影响面预测与对账）、`pkg_digest`（装配版本摘要）、`backflow`（回灌助手）、`closeout_derive`（收口步骤派生）、`write_claim`（写面 claim 仲裁）、`mutation_proof`（变异证明）、`e2e_console`（评审控制台）。

**CLI 命令面**（`atlas <command>`）：

| 命令 | 作用 |
|---|---|
| `atlas init` | 一键初始化并装配到当前（或指定）项目 |
| `atlas update` | 安全刷新项目内的 `.atlas/` 工程线束与平台 Skills |
| `atlas upgrade` | 拉取 npm 最新全局包升级全局 CLI |
| `atlas check` | 运行项目级资产与门禁全套检查 |
| `atlas console` | 启动 E2E 用例评审控制台 |
| `atlas report` | 生成流水线报告 |

> 注意：`apply` 不是终端命令——它是由 AI Coding Agent 在会话中执行的**认知编排技能**，通过 `/atlas-apply <模式>` 或自然语言唤起。
