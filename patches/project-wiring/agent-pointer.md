# atlas — 全流程工作流

本项目已接入 **atlas**（全流程 vibecoding 工作流：「需求 → 应然资产 → 实现 → 验收 → 收口」；需求级执行由 Trellis 承担）。**开工前先读**：

- **契约（canonical）**：`.atlas/shared/`（`global-rules` / `single-source` / `layout` / `stack-profile`）+ `.atlas/rings/*/reference.md` + `.atlas/apply/reference.md`
- **技术栈画像**：`product/stack-profile.yaml`（`apps` / `role` / `adapters`）
- **视觉设计档案**：`product/design.md`（frontend-design skill 写；`detect:` 豁免与 `.impeccable/config.json` 的 `detector.ignoreRules` 由 `validate_design_exemptions` 双向对账）
- **结构事实**：`.trellis/spec/structure/`（Trellis 原生按 `paths:` 注入）；`spec/conventions/testid.md` 同理

**怎么用**：

- **先分清「装配」与「开户」（第一步就问这个）**：`atlas init` 只装配线束。**若 `product/prd/` 与 `.trellis/spec/structure/` 仍为空 ⇒ 本产品尚未开户** —— 用户说「接入 Atlas 工作流 / 把项目接进来」时走 `atlas-apply adopt`（存量：只登记既有基线 + 开户最小集，不重写老 PRD、不猜老用例），**不得**因为 `.atlas/` / `product/` 已存在就回「已接入」或反问是不是接过了。开户按产物存在与否**断点续跑**，不重来。
- skills：`atlas-structure` / `atlas-prd` / `atlas-e2e` / `atlas-apply`
- 需求级流程走 `.trellis/workflow.md` 的 `#### 1.6 项目级资产更新`（= `atlas apply <需求ID>`），**实现在其后**
- 收口 = 相关 E2E 全 `green` + **用户验收走查确认**（`blocked` ⇒ 域标待验收、不判收口）+ 结构事实刷新（`.trellis/config.yaml` 的 `after_finish` hook）
- **撞到「规则本身不合业务」不许静默绕过**：注释规则 / 放宽判定 / `--no-verify` / 假装完成都算绕过——按契约 §15 提炼**设计问题**（缺陷本体 · 抽象触发形态 · 建议方向；**不带产品名 / 业务名词 / 真实数据**）后用 `atlas report` 上报，并告知用户 + 给当前阶段最优临时推进方案（`.atlas/shared/global-rules.md` §15）。用户说「这不合理」是同一类。

> 本段由 `atlas/install.sh` 幂等维护（区块可重放）。请勿手改；改契约请改 atlas 源包后重跑 `install.sh`。
