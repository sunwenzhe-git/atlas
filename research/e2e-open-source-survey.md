# E2E 环设计 — 开源方案调研

> **性质**：`atlas/research/` 属**非 canonical 调研存档**，不进 `install.sh` 装配清单（装配只取 `shared rings apply scripts templates adapters validators patches tests`），不作为执行契约。
> **用途**：为 `rings/e2e/reference.md` 与 `skills/atlas-e2e/SKILL.md` 的设计取舍提供依据。结论同步 Obsidian `2026091715433508-atlas-discussion-log`。
> **调研日期**：2026-09-20。**本文件允许出现具体框架名**（`global-rules.md` §1 的禁名录只约束 canonical 包内容）。

## 0. 调研对象与来源

| # | 方案 | 来源 | 形态 |
|---|---|---|---|
| 1 | Autospec | https://github.com/zachblume/autospec | CLI（TypeScript，Vercel AI SDK） |
| 2 | Cairn | https://github.com/plune-ai/cairn | CLI（Node/TS + Playwright），npm `@plune-ai/cairn`（页面 403，仅取仓库说明） |
| 3 | Ouroboros Tester | https://www.npmjs.com/package/ouroboros-tester | npm 包（Agent 流水线） |
| 4 | Full Test Orchestrator | https://github.com/greeun/full-test-orchestrator | Claude Code skill |
| 5 | QAai | https://github.com/profullstack/qaai | SaaS 平台（Next.js + Runner + Supabase） |
| 6 | DLV 阶段 05 Formal（本项目旧基线） | `.agents/skills/dlv-test-formal/SKILL.md` | 重型阶段机 |

## 1. 逐方案拆解

### 1.1 Autospec

| 维度 | 内容 |
|---|---|
| 流程 | Plan（爬取 URL ≤3 页 + 无障碍快照 → 模型生成 spec）→ Execute（每条 spec 独立浏览器上下文并行；语义动作 click by role / fill by label；**每步重读无障碍快照**）→ Report（pass/fail 摘要；**只把通过的** spec 写成 Playwright `.spec.js`） |
| 锚点策略 | 现代 locator：`getByRole` / `getByLabel` / `getByText`（语义优先，不用 CSS） |
| 用例真相源 | 无项目级真相源；产物是"跑通的测试代码" |
| 人工门 | 无 |
| 可取 | ① 语义 locator 稳定性；② **green-first 固化**——只有跑通过的用例才落成代码 |
| 不取 | ① 无 testid/无锚点契约；② 无项目级 living 文档；③ 爬取式**验现状**，与 atlas「应然先行」相反 |

### 1.2 Cairn（与本环最接近）

| 维度 | 内容 |
|---|---|
| 流程 | observe（ARIA + 截图 + 可交互元素）→ **ground**（逐条验证 locator、探 tab/view、探安全状态转移，"测真实存在而非幻觉"）→ design（**ISO/IEC/IEEE 29119-4 用例设计**：等价类 EP / 边界值 BVA / 决策表 / 状态转移 / 错误推测）→ generate & validate（POM 风格 `@playwright/test` + **self-repair keep-best**：修复不得让套件变差）→ judge & learn（确定性 scorer + LLM judge + Pilot 总评，Langfuse 追踪） |
| 用例形态 | **两种**：`ATC`（可自动化 → 生成代码）与 `MTC`（人工：提交、安全/XSS、视觉/UX、不可逆操作） |
| 模式解耦 | `design`（只出 Markdown 用例 + 录下的 selector，**不产码**）/ `automate`（从**已批准** ATC 生成码，跳过 MTC）/ `explore`（全流水线一次跑完） |
| 锚点策略 | 录下并**验证真实 locator**（ground 阶段），与我们的「testid 双向校验」同构，但它是「验证存在」，我们是「集合相等」 |
| 人工门 | 有：ATC 需批准后才 `automate` |
| 可取 | ① **design/automate 解耦 + 人工批准门**（= 我们的「从分片生成脚本」+ 前置更新）；② **ATC/MTC 二分**（可对齐我们的 `type` 与 `blocked/skipped`）；③ **locator ground-truth 校验**（启发了「testid 必须可解析」而非仅集合相等）；④ 29119-4 用例设计法可作 `type` 值域参考 |
| 不取 | ① URL 探索（我们原型才是真相源）；② POM/测试脚手架生成与 self-repair（平台味，超出 E2E 环）；③ Langfuse/Pilot |

### 1.3 Ouroboros Tester

| 维度 | 内容 |
|---|---|
| 口号 | **spec-first, not code-first**；`proven interactions, not assumed ones`；`agents explore, humans review` |
| 流程 | explore（探索 live app）→ verify（**独立 re-crawl**、重放交互 recipe、验 API 契约、跑 CRUD 流；错则修、对则标 verified）→ architect（POM / fixture / helper 架构）→ write tests（POM + API helper 造数 + 断言） |
| 产物 | `src/docs/`（`spec.md`+`impl.md`、`STATE.md`、`DOMAIN-TREE.md`）、`src/pages/`、`src/fixtures/`、`src/helpers/`、`src/tests/` |
| 质量门 | **每阶段有校验脚本、未过不得移交**：`validate-spec.mjs`（spec 完整性/章节/场景格式）、`validate-architecture.mjs`（POM/fixture/helper 完整性） |
| 锚点策略 | user-facing locators 优先：`getByRole` / `getByLabel` / `getByText`，CSS 次之 |
| 可取 | ① **每阶段机器校验门**（与我们的 `validators/` 一一对应）；② **spec 是代码上游**（与"索引是唯一入口"同义）；③ DOMAIN-TREE / STATE 这类**项目级结构文档**（与 `.trellis/spec/structure/` 同构） |
| 不取 | ① live 探索；② 生成整套测试脚手架与 POM（我们只从分片生成 spec 脚本） |

### 1.4 Full Test Orchestrator（深入；含同类 skill 的结构范本）

来源：`greeun/full-test-orchestrator`（已浅克隆核对：`SKILL.md` 892 行 + `references/{test-domains,quality-criteria,doc-templates,report-format,parallel-strategy}.md` + `assets/templates/{scenario,testcase}-template.md`）。

**它是 `atlas-e2e` 的直接结构模板**：`SKILL.md`（工作流 + 门禁） + `references/`（分主题正文） + `assets/templates/`（产物模板）——与 atlas 计划中的 `skills/atlas-e2e/SKILL.md` + `rings/e2e/reference.md` + `templates/e2e/` 同构。

| 维度 | 内容（带取证） |
|---|---|
| 定位 | Claude Code skill：十域测试套件生成（unit / api / integration / e2e / security / a11y / performance / load-stress / smoke / chaos），并行 agent |
| 核心原则 | **Tests Are the Spec**（`SKILL.md:10-14`）：人类 QA 按**需求**验，不按现状验；测试失败时先问「实现错还是测试错」，**默认实现错**。→ 即我们的「应然先行」 |
| 规格来源优先级 | `SKILL.md:98-117` A-1：显式规格 > 类型契约 > 路由定义 > 既有测试 > 代码意图 > 框架约定；**「预期值来自 spec，不来自先跑一遍实现」**（`SKILL.md:393`） |
| 流程 | A 规格+代码分析（串行）→ **A+ 误报审计** → **A-5 域覆盖门（10 域判定 → 用户确认）** → B 文档生成（3 agent 并行）→ C 代码生成 → D 执行 → E 失败分诊 → F 修复 → G 复验（≤5 轮，`SKILL.md:71-94`）→ H 报告 |
| 产物流 | `tests/doc/scenarios/<domain>-scenarios.md`（`SC-{DOMAIN}-NNN`）+ `tests/doc/testcases/<domain>-testcases.md`（`TC-{DOMAIN}-NNN`，字段：Scenario/Preconditions/Input/Steps/Expected Output/**Actual Output**/Status/Priority）；**1 场景 → 2-5 用例**（happy + 边界）（`doc-templates.md:62-68`） |
| **有意义测试门** | **3-Question Gate**（`SKILL.md:18-22`）：① 没有它什么 bug 会漏到生产？② 这层是这条验证的 owner 吗？③ 失败触发什么动作？答不上就别写。**7 条禁写模式**（`SKILL.md:24-34`）：常量校验 / 存在性检查 / 实现复制 / 占位断言 / 纯委托 / 静态数据 / 重复中间件 |
| **误报审计** | `SKILL.md:36-59` + `quality-criteria.md:24-42`：6 条 grep 模式抓「通过但没验」——`expect(true)`、`[SKIP]`、`!== undefined`、`expect([...]).toContain`、`.catch(()=>null)`、空测试体；分级 CRITICAL/HIGH/MEDIUM；**「误报比没测试更危险」** |
| **反偏见纪律** | `SKILL.md:61-67`：① 绝不改测试去迁就 bug；② 绝不无根因删失败测试；③ 绝不用 `skip/xtest/.todo` 绕过失败；④ **绝不弱化断言**去求绿；⑤ 改测试必须写理由（spec 变了 / 假设错了 / 非确定） |
| **失败分诊 6 类** | `SKILL.md:427-463`：`IMPL_BUG` / `TEST_ERROR` / `SPEC_AMBIGUOUS` / `ENV_ISSUE` / `FLAKY` / `NOT_IMPLEMENTED`，每类有明确动作 |
| **Layer Ownership** | `SKILL.md:613-637`：每个验证项**恰好归一个层**（unit/api/integration/e2e/security/a11y/perf），禁止跨层重复；E2E 文件必须用浏览器 `page`，仅用 `request` 的不算 E2E |
| **去重 3-Gate** | `SKILL.md:156-233`：判重必须过 Same Target / Same Intent / Same Layer 三关、附 grep 与正文引用；**文件名/describe/目录相似都不算证据**；≥10 条判重时用户抽样 ≥30% 复核 |
| 质量门 | 10 条（`quality-criteria.md`）：0 误报、覆盖、独立、确定（0 flaky）、边界值、失败可读、速度（e2e < 30s）、OWASP、WCAG 2.1 AA、性能 |
| E2E 域必测 | `test-domains.md:52-122`：全生命周期旅程（非会员/会员/管理员各一条连续流）、移动端**独立 spec**、i18n 实内容校验、**禁止 `[SKIP]` 优雅跳过**（要 `toBeVisible` 或 `fixme`+`test.fail`） |
| 不取 | ① 十域齐做（超 E2E 环范围）；② 生成→执行→修复→复验闭环（我们 v1 只管资产与脚本，执行由两段式承载）；③ 覆盖率百分比门（需 instrument，与我们「集合相等」的锚点门不同类） |

### 1.5 QAai

| 维度 | 内容 |
|---|---|
| 定位 | AI 驱动的 QA 平台：从 **PR diff 与 spec** 规划、生成、执行 Playwright E2E，人工在环审批 |
| 架构 | Next.js Web（看板/产物查看）+ Runner Service（planning/generation/execution workers + 作业队列）+ Supabase（Postgres/Auth/RLS/Storage） |
| 能力 | 多 LLM、flake 统计检测 + 热力图、route/API 覆盖矩阵、GitHub 集成（webhook/check/PR）、CI/CD |
| 可取（作为**后续可选**项） | ① flake 统计；② route/API 覆盖矩阵；③ CI check 门禁；④ 人工审批 |
| 不取 | 三件套基础设施（DB/Auth/Storage/队列）——与 atlas「仓库内文件契约、零基础设施」定位冲突 |

### 1.6 DLV 阶段 05 Formal（旧基线）

| 维度 | 内容 |
|---|---|
| 流程 | P01 freeze（标杆池 `frozen-benchmark.json` + `source-scan-ledger.json`）→ P02 common（`assertion_cover_list_all`）→ P02.5 规则引擎（required/长度/数值/枚举）→ P03a scaffold 骨架 → P03b LLM 填充（8 条步骤质量门）→ P03c merge+render（review/atomic 双粒度）→ P04 coverage（映射 + 缺口）→ P05 review → P06 stage05 补充 |
| COV 字段 | `business_object` / `trigger_scene` / `terminal_or_error_surface` / `observation_layer`（单一主观测层）/ `assertion_layer`（可多选，须含观测层） |
| 可取 | ① **AC → 用例可追溯**（我们 `prd_ref` 已对齐）；② **单一事实源**思想；③ **覆盖率缺口报告** |
| 不取 | 冻结标杆池 + 多阶段中间产物（正是 atlas 要取代的「文档工厂」） |

### 1.7 Autonoma（`autonoma-ai/autonoma`）——最深，且是"教训库"

来源：已浅克隆核对（3139 文件，pnpm + Turborepo 单体；BSUL-1.1）。核心可读：`apps/cli/src/agents/05-test-generator/{test-spec,rubrics,validation,step-guidance,duplicate-judge}.ts`、`packages/diffs/src/agents/diffs/plan-authoring-guide.ts`、`apps/api/docs/suite-health.md`。

**定位**：SaaS 平台——每 PR 一个 preview 环境 + Environment Factory 造隔离测试数据 + AI agent 驱动真实浏览器（截图 + 点位检测）跑自然语言用例 + 出 PR 评论（视频/截图/疑似代码行）。**执行层与我们无关**（vision agent、preview env、SDK 造数都要基础设施）。

**但它的"用例怎么写"是同类里最严的，且有代价背书**（注释里全是真实事故）：

| # | 规则（取证） | 一句话 |
|---|---|---|
| A1 | **禁止断言 toast**（`plan-authoring-guide.ts:78-80`） | toast 自动消失，断言时序不稳；**toast 不算验证** |
| A2 | **持久化写必须刷新后复断言**（`plan-authoring-guide.ts:109-114`、`rubrics.ts:132-145`） | create/edit/delete 在页内立刻断言可能命中的是**乐观更新**（"看着存了其实没存"）；唯一证明是 reload 后同一实体/值仍在。例外：校验被拒（无写）、纯导航/鉴权、会话内短暂状态 |
| A3 | **断言必须与被操作控件不同源**（`rubrics.ts:116-126`） | 点筛选后断言筛选 chip 可见＝没验；要断言列表真的变了 |
| A4 | **编辑/切换要断言前后两端**（`plan-authoring-guide.ts:125-128`） | 只断言"新值"可能本来就是这个值，用例什么都没做也通过 |
| A5 | **意图必须可证伪**（`test-spec.ts:167-170`、`rubrics.ts:64-68`） | `intent` ≥30 字符的具体行为声明；"页面显示正确"不合格；`**Intent**:` 段必填（`validation.ts:98-100`） |
| A6 | **文案必须是渲染后的可见文案**（`plan-authoring-guide.ts:82-92`） | 不得用 i18n key / 枚举值 / 组件名（`MoreVertical`）/ CSS 类当文案；要读 locale 文件解析真实文案 |
| A7 | **步骤动词闭集**（`validation.ts:13-18`） | `click/type/scroll/assert/hover/drag/refresh`；每步 `N. verb: 目标`，且 click/type/assert 必须写**屏幕位置**（`validation.ts:33-42`） |
| A8 | **禁占位与"或"**（`plan-authoring-guide.ts:138`、`rubrics.ts:59`） | 不得 `{{token}}`/`{var}`/`e.g.`/`Dynamic:`/"A 或 B"；含"或"的步骤不可证伪 |
| A9 | **Step 与 Verification 分离**（`plan-authoring-guide.ts:16-24`） | 动作步骤 vs 断言步骤分列；"打开又关闭"类不产生结果的用例不合格 |
| A10 | **测试数据接地与独立性**（`rubrics.ts:228-233`） | 断言里的每个具体值必须来自**提供的测试数据**，不得来自应用自带 seed/fixture，也不得依赖别的用例创建的数据；`<generated per run>` 不得字面断言 |
| A11 | **去重是语义判断、按页作用域、保守**（`duplicate-judge.ts`） | "转账"vs"挪钱"是同一条；不同页几乎必不同；误杀比重复更糟；judge 挂了就 fail-open 全放行 |
| A12 | **语义判断交给模型，regex 只做 token 级**（`test-spec.ts:29-35`） | 用 regex 判"句子意思"翻过车：**680 次重试、$11、零用例**；能判的只有 token/占位/结构 |
| A13 | **Suite health：新套件从"校准中"起步，不预置为绿**（`suite-health.md:10-18`） | `trust=(passed+client_bug)/全部 findings`；**确认的真 bug 提高健康度**；失败分诊含 `environment_failure/scenario_issue/engine_artifact/plan_mismatch/invalid_test` |
| A14 | **选择器一律禁止**（`plan-authoring-guide.ts:57`、`rubrics.ts:38`） | 明令禁 `data-testid`/`aria-label`/CSS/元素类型——因为**改不了客户代码** |

**它比我们强的地方**：用例"是否真的验到了东西"被拆成可复述的规则（A1–A4、A9），并有 review rubrics 与去重语义判断；`intent` 字段把"这条用例证明什么"变成必填。Suite health 把"新套件不可信"讲清楚。

**它的前提我们不成立、因而必须分道的地方**：A14（禁选择器）源于改不了客户 app；atlas 的原型与实现**都是我们写的**，所以 testid 硬锚成立，且 A7 的"必须写屏幕位置"对我们**冗余**（testid 全站唯一，不存在重名歧义）。

**不取**：preview 环境、Environment Factory/SDK 造数、vision 执行、self-heal、平台化。

## 2. 横向对比

| 维度 | Autospec | Cairn | Ouroboros | Full-Test-Orch | QAai | DLV05 | **atlas E2E（现状设计）** |
|---|---|---|---|---|---|---|---|
| 出发源 | URL（现状） | URL（现状） | live app（现状） | 代码+规格 | PR diff+spec | PRD/需求 | **PRD + 原型（应然）** |
| 用例真相源 | 无 | Markdown ATC/MTC | `spec.md` | `tests/doc/*.md` | DB | `frozen-benchmark.json` | **`e2e-index.md` + 分片** |
| 组织粒度 | 页（爬取） | 探索路径 | 域/URL | 域（10 域） | PR | COV 原子 | **页面分片 + 总索引** |
| 锚点策略 | 语义 locator | 录+验 locator | 语义 locator | — | 生成选择器 | UI 触发锚点 | **`data-testid` 双向集合校验** |
| 人工门 | 无 | ATC 批准 | humans review | 误报审计+分诊 | 审批 | 多阶段门禁 | **状态机 + 完成门（硬门+例外）** |
| 机器校验 | 无 | scorers | 每阶段脚本 | 10 质量条 | 分析 API | 多校验器 | **`validate_{testids,e2e_index}.py`（待写）** |
| 基础设施 | 无 | 无 | 无 | 无 | **有（SaaS）** | 无 | **无（纯文件）** |
| 跨项目通用 | — | — | — | — | — | 部分 | **硬要求（禁框架名）** |

## 3. 对 atlas E2E 的结论

**主干保持 atlas 原生**：在「应然先行 + 项目级 living 资产 + 仓库内零基础设施 + 跨项目通用」四条约束下，六个方案**没有一个**同时满足——Autospec/Cairn/Ouroboros 从现状出发（抛弃应然），QAai 需基础设施，DLV05 正是被取代的重型工厂。

**建议采纳（低成本、直击痛点）**：

| # | 来源 | 采纳点 | 落到哪里 |
|---|---|---|---|
| A1 | Cairn | design/automate 解耦 + 人工批准门 | 契约明确「索引/分片是上游、脚本是下游派生」，脚本只在用例已定后生成 |
| A2 | Ouroboros | 每阶段机器校验门 | `validate_testids.py` / `validate_e2e_index.py` |
| A3 | Full Test Orchestrator | **有意义测试门（3-Question Gate）+ 7 条禁写模式** | `validate_e2e_index.py` 的「用例可判定性」检查 + 契约 §用例质量门 |
| A4 | Full Test Orchestrator | **失败分诊 6 类** | `status_reason` 的建议值域（见 §4 Q4） |
| A5 | Cairn | 29119-4 用例设计法（EP/BVA/决策表/状态转移/错误推测） | `type` 值域与用例设计提示（见 §4 Q2） |
| A6 | Autospec/Ouroboros | 语义 locator 优先 | **与 testid 的关系待定**（见 §4 Q1） |
| A7 | Full Test Orchestrator | **误报审计 6 条 grep 模式** | `validate_e2e_index.py` 的 WARN 级扫描（占位预期 / 「仅跳转」/ 无断言步骤） |
| A8 | Full Test Orchestrator | **反偏见纪律 5 条** | 完成门契约：禁止为求绿弱化 `expected_zh` / 加 `skipped`；`blocked/skipped` 必须带原因与去向（与现有状态机一致，补上"禁止弱化"） |
| A9 | Full Test Orchestrator | **Layer Ownership（每验证项恰归一层）** | 我们的「断言落点页」+「一例一片 + 跨页 `pages[]`」正是同构；补充「`request`-only 不算 E2E」式边界（只有 UI 交互才归本环） |
| A10 | Full Test Orchestrator | **去重 3-Gate** | `validate_e2e_index.py` 的「无孤儿 / 无跨分片复制」判定的复核规程（避免误报重复） |
| A11 | Full Test Orchestrator | **规格来源优先级 + 预期来自 spec 不来自实现** | 契约写明用例预期以 PRD + 原型（应然）为准，禁止用真实应用现状反推预期 |
| A12 | Full Test Orchestrator | **skill 结构范本**（`SKILL.md` + `references/` + `assets/templates/`） | `skills/atlas-e2e/SKILL.md` + `templates/e2e/{index,shard}.md` 的骨架 |
| A13 | **Autonoma** | **禁止断言瞬时反馈**（A1） | 契约 §结果断言规则：toast/成功提示/弹窗关闭不得作唯一验证 |
| A14 | **Autonoma** | **持久化写刷新后复断言**（A2） | 契约 + 质量门：create/edit/delete/save 必须 reload 后复断言；三类例外要写明 |
| A15 | **Autonoma** | **断言须与被操作控件不同源**（A3）+ **编辑类前后两端**（A4） | 契约 §结果断言规则 + 质量门 WARN |
| A16 | **Autonoma** | **`intent` 可证伪声明**（A5） | 新增分片字段 `intent` + 质量门（非空/长度/模糊黑名单） |
| A17 | **Autonoma** | **文案须为渲染后可见文案**（A6） | 契约：`expected` 文案取自 AC 文案规范；不得用 i18n key/枚举/组件名 |
| A18 | **Autonoma** | **禁占位与"或"**（A8）+ **Step/Verification 分离**（A9） | 质量门 WARN/FAIL 扩项 |
| A19 | **Autonoma** | **测试数据接地与用例独立性**（A10） | 契约新增 §数据前提 + 列为 open issue（数据供给方式待定） |
| A20 | **Autonoma** | **去重语义化、按页、保守、fail-open**（A11）+ **regex 只判 token**（A12） | 坐实 Q13 选择：语义项留 agent 纪律、校验器只判 token/结构 |
| A21 | **Autonoma** | **新套件从"校准中"起步**（A13） | 完成门语义：`red` 是未证实态，只有真机通过才 `green` |

**明确不采纳**：URL/live 探索（Autospec/Cairn/Ouroboros 的起点）、平台化三件套与队列（QAai）、POM/整套测试脚手架生成与 self-repair（Cairn/Ouroboros）、冻结标杆池与多阶段中间产物（DLV05）。

## 4. 调研引出的新决策点（待 grill）

| # | 问题 | 影响 |
|---|---|---|
| Q1 | **锚点策略**：`data-testid` 唯一硬锚 vs testid + 语义 locator（role/label/text）双轨 | 决定契约是否允许脚本用语义 locator、以及双向校验只校 testid 还是两者都校 |
| Q2 | 是否把 **29119-4 用例设计法** 写进 `type` 值域/提示 | 影响用例字段与校验器词表 |
| Q3 | 是否把 **有意义测试门（3-Question Gate）+ 误报审计 grep 模式** 纳入 `validate_e2e_index.py` | 决定校验器是「结构校验」还是「语义校验」，以及判定用 FAIL 还是 WARN |
| Q4 | `status_reason` 是否收敛为 **FTO 六类值域**（`IMPL_BUG`/`TEST_ERROR`/`SPEC_AMBIGUOUS`/`ENV_ISSUE`/`FLAKY`/`NOT_IMPLEMENTED`），还是仍用自由文本 | 影响状态机契约、回写规则与校验器 |
| Q5 | 是否采纳 **反偏见纪律 5 条**（禁止弱化断言求绿）写进完成门 | 影响收口门与「硬门 + 显式例外」的措辞 |
| Q6 | 是否明确 **E2E 与 API/其他层的边界**（`request`-only 不算 E2E） | 影响本环范围与用例归类 |
| Q7 | 是否把 Autonoma 的 **结果断言规则（A1–A4、A9）** 写进契约与质量门 | **已采纳**（用户 2026-09-20 同意）：契约 §5.6 结果断言规则 R1–R6 + §8.2 质量门扩项；示例已改（去 toast） |
| Q8 | 是否新增分片字段 **`intent`**（可证伪声明） | **已采纳**：分片字段增 `intent`，质量门查缺失/模糊 |
| Q9 | **测试数据供给** | **已定**（用户："你自己 mock 不就行了"）：本环**自行 mock**，确定性、用例独立、不引外部造数（契约 §5.7），不立 open issue |
