# atlas — 全流程工作流

本项目已接入 **atlas**（全流程 vibecoding 工作流：「需求 → 应然资产 → 实现 → 验收 → 收口」；需求级执行由 Trellis 承担）。**开工前先读**：

- **契约（canonical）**：`.atlas/shared/`（`global-rules` / `single-source` / `layout` / `stack-profile` / `knowledge`）+ `.atlas/rings/*/reference.md` + `.atlas/apply/reference.md`
- **技术栈画像**：`product/stack-profile.yaml`（`apps` / `role` / `adapters`；`knowledge.vault` 非空表示启用 Obsidian 同步）
- **视觉设计档案**：`product/design.md`（frontend-design skill 写；`detect:` 豁免与 `.impeccable/config.json` 的 `detector.ignoreRules` 由 `validate_design_exemptions` 双向对账）
- **结构事实**：`.trellis/spec/structure/`（Trellis 原生按 `paths:` 注入）；`spec/conventions/testid.md` 同理
- **知识库（可选）**：`knowledge.vault` 非空时，动手前先检索 vault 内 `atlas/` 的总览 note 与未决问题 note

**怎么用**：

- skills：`atlas-structure` / `atlas-prd` / `atlas-e2e` / `atlas-apply`
- 需求级流程走 `.trellis/workflow.md` 的 `#### 1.6 项目级资产更新`（= `atlas apply <需求ID>`），**实现在其后**
- 收口 = 相关 E2E 全 `green` + **用户验收走查确认**（`blocked` ⇒ 域标待验收、不判收口）+ 结构事实刷新（`.trellis/config.yaml` 的 `after_finish` hook）

> 本段由 `atlas/install.sh` 幂等维护（区块可重放）。请勿手改；改契约请改 atlas 源包后重跑 `install.sh`。
