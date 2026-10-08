---
name: atlas-apply
description: "项目级跨环编排环（atlas 唯一编排件）：把一条需求灌进项目级应然资产——读 Trellis 需求卡，推导影响面，按 prd → e2e 增量更新，跑机器校验并出报告；四模式：apply <需求ID>（需求式跨环增量）、apply adopt（既有项目一次性接入开户：只跑 structure 全量 + 全局 PRD 按最小必填集、域级 PRD 按「开户最小集」逐域开一份）、all（按序跑 structure/prd/e2e 三环全量）与 backfill（回流原语：已裁决的回填条目按上游目标分组、攒批灌入，含下游用例改挂与各环门照跑）；先过三问门（改动既有能力 / 要人确认 UI / 要可重复验收），三问全否 ⇒ 只走 structure + Trellis。Use when 用户要求 接入 Atlas 工作流/把项目接入 Atlas/存量项目接入/应用需求/需求增量/更新项目级资产/跨环更新/apply 需求/跑三环全量/all 模式/旧项目接入/接入开户/adopt 模式/回填/backfill/回流原语/把需求灌进 PRD 与 E2E/实现前更新应然资产。不产 PRD 正文、E2E 用例、结构事实或业务代码（分别是各环与 Trellis 实现阶段的职责）。"
---

# atlas apply

跨环编排环，atlas 里唯一的编排件。把一条需求灌进项目级应然资产：读 Trellis 需求卡 → 推导影响面 → 按 `prd → e2e` 增量更新（E1：原型环已移除）→ 跑机器校验 → 出报告；更新完成后 Trellis 才去实现。三种模式：`apply <需求ID>`（需求式增量）、`apply adopt`（既有项目一次性接入开户）与 `all`（按序跑三环全量）。

## 先读

1. 共享契约（`.atlas/shared/`）：`global-rules.md`、`stack-profile.md`、`single-source.md`、`layout.md`。
2. 本环契约：`.atlas/apply/reference.md`。
3. 涉及的具体环契约：`.atlas/rings/{prd,e2e,structure}/reference.md`（按参与的环读）。

## 路径

本项目 atlas 包在 `<项目根>/.atlas/`；`<项目根>` = 当前工作目录（含 `.trellis/` 与 `product/` 的那层）。需求 ID = Trellis task id；需求卡 = `.trellis/tasks/<需求ID>/prd.md`；执行记录落 `.trellis/tasks/<需求ID>/atlas-apply.md`。

## 边界

只做跨环增量编排，**不重实现**任何环内逻辑。越界即失败。

- **三问门（先判，再动手；判定 + 依据必须写进 `atlas-apply.md`）**：① 改动既有能力？② 要人确认应然 UI？③ 要可重复验收？（超出 lint/test/typecheck）任一为是才拉起对应环；**三问全否 ⇒ 只走 `structure` + Trellis** —— 这是**合法路径**，不是绕过工作流。判据见 `apply/reference.md` §3.1/§4.1。
- **无需求卡的应然资产修订（第 4 种形态，`apply/reference.md` §3.2）**：判据 = **有没有一条需求要接**；无 ⇒ **不建需求卡、不建任务**，直接按环跑 `prd → e2e`（只改受影响集合）。评审期「先收集问题再批量优化」：清单落 `product/reviews/<日期>-<主题>/`（`README.md` + `plans/`），**一条工作单元承载 N 条问题、不得用子任务树**，切到「优化」由用户显式宣布收齐；`review` 期间 `validate_testids` 双向集合**允许红**，收口前必须绿。
- **`adopt` 模式**：旧项目**第一次**接入——只跑 `structure` 全量，再把 `product/prd/` 开起来：全局 `prd.md` 按**最小必填集**（`范围形态：变更` + `覆盖度` + `基线`），**域级为域清单里每个域开一份「开户最小集」**（一 域概述 / 二 功能清单 / 四 业务规则 / 五 验收标准；三 功能详细说明与 六 Assumptions **整节不出现**，留到该域真有需求时补——契约 §4）；**不预设** E2E（原型环已移除），它由后续每条需求按三问门长出。
- **并发写面**：同一项目级文件**单写者**；并发前先声明写面，冲突时停下报告（`apply/reference.md` §5.1）。
- **参与环与顺序**：`apply <需求ID>` = `prd → e2e`（按三问门取舍）；`structure` 不参与（实然，实现后由 `after_finish` hook 刷），唯一例外 = 本次 PRD 定稿改了域清单 ⇒ 末尾追一次 structure re-key。`all` = `structure → prd → e2e` 逐一全量。
- **`backfill` 模式（回流原语，第 4 种，`apply/reference.md` §5.2）**：把**已裁决**的回填条目（补写 / 修订 / 收口 / 配置四型）按「上游目标 + 改动类型」**分组**、**攒批**（≤ 10 条/批）灌入上游；**独立声明写面**走 §5.1 仲裁；**闭环钩子硬** —— 下游重跑/重审 + 台账**随批挪卷** + **各环门照跑**（不得以「只是回填」跳过）。裁决型走队列本体、退役型走生命周期（`shared/global-rules.md` §11）。
- **判据「是否改变应然 UI」**（不是需求大小）：改 UI ⇒ 先把 PRD 文案 / 流程面落细，并把新元素的 testid **应然**写进用例分片（E1：原型环已移除，见 `rings/e2e/reference.md` §6.2）；不改 UI ⇒ 复用既有 testid，只补用例；纯后端不可见 ⇒ 本环不产用例。
- **影响面识别归本环**：agent 语义判断 + 结构证据（`routes.md`/`_meta.json.domains`/索引页面表），产结构化清单；低置信 / 歧义 / 映射不到 ⇒ 一次性 ≤3 问，**不猜**；**禁**用正则判语义。
- **实现前前置**：apply 在实现之前跑；不回写 E2E 执行状态（新用例置 `red`）。失败 / 门控 ⇒ 停在 planning 并结构化报告，**不得进入实现**。
- **确认门**：整页重建 / 删页 / 全量重生成 / 删既有产物 / 改 `stack-profile.yaml` 必须先获用户确认（`global-rules §7`）。
- **独立审查门（环间，硬）**：`e2e` 用例产出后、生成脚本前跑 **E2E 环独立审查**（`.atlas/rings/e2e/reference.md` §12；报告落 `product/e2e/reviews/<日期>-<范围>/`，**有 `Critical` 不得生成脚本**）。骨架按名引用 `.atlas/shared/independent-review.md`。
- **不新增 Trellis 状态**；不改需求卡 `prd.md`（除非用户要求）；不写业务代码。
