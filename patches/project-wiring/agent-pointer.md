# atlas — 全流程工作流

本项目已接入 **atlas**（需求 → 应然资产 → 实现 → 验收 → 收口）。工作知识主要在 `.atlas/`（技术栈画像在 `product/`）：

- `.atlas/shared/` — 契约（`global-rules` / `single-source` / `layout` / `stack-profile`）
- `product/stack-profile.yaml` — 技术栈画像（`apps` / `role` / `adapters`；资产根按 `atlas.config.yaml` 解析）
- `.atlas/rings/*/reference.md` — 各环产出契约
- `.atlas/spec/` — 按包/层划分的规范（`paths:` 索引；写某层代码前先读命中的部分）
- `.atlas/tasks/` — 需求级任务账本（PRD / 派工单 / 审查报告）

平台暴露 atlas 命令时优先用命令，不要手工模拟步骤：

- **装配 ≠ 开户**：`atlas init` 只装线束；`product/prd/` 与 `.atlas/spec/structure/` 为空即未开户，走 `atlas-apply adopt` 断点续跑，不得回「已接入」。

- 开工：`atlas workflow plan --unit <ID> [--paths <glob...>]` → `atlas workflow dispatch [--paths <file...>]`
- 提交前：`atlas workflow verify --unit <ID>`（未通过不得提交或收口）
- 收口：`atlas workflow finish --unit <ID>`（另需 E2E 全绿 + 用户验收走查）
- **平台口径（Windows）**：契约里的 `python3` 用 `python` 替代（需 Python 3.10+）。

撞到「规则本身不合业务」不许静默绕过：按 `.atlas/shared/global-rules.md` §15 提炼设计问题后 `atlas report` 上报。

> 本段由 `atlas/install.py` 幂等维护（区块可重放）。请勿手改；改契约请改 atlas 源包后重跑 `atlas init`。
