# atlas — 全流程工作流

本项目已接入 **atlas**（需求 → 应然资产 → 实现 → 验收 → 收口）。工作知识主要在 `.atlas/`（技术栈画像在 `product/`）：

- `.atlas/shared/` — 契约（`global-rules` / `single-source` / `layout` / `stack-profile`）
- `product/stack-profile.yaml` — 技术栈画像（`apps` / `role` / `adapters`；资产根按 `atlas.config.yaml` 解析）
- `.atlas/rings/*/reference.md` — 各环产出契约
- `.atlas/spec/` — 按包/层划分的规范（`paths:` 索引；写某层代码前先读命中的部分）
- `.atlas/tasks/` — 需求级任务账本（PRD / 派工单 / 审查报告）

平台暴露 atlas 命令时优先用命令，不要手工模拟步骤：

- **装配 ≠ 开户**：`atlas init` 只装线束；`product/prd/` 与 `.atlas/spec/structure/` 为空即未开户，走 `atlas-apply adopt` 断点续跑，不得回「已接入」。

- 开工：用户说出新需求、大功能点下的后续改动或 bug 时，先运行 `atlas workflow plan --unit <ID> --requirement -`（用户原话经带引号 heredoc 传 stdin）；初始需求建立功能活文档与首版快照，变更/缺陷在 `changes/` 或 `bugs/` 新增请求。退出 0 后才运行 `atlas workflow dispatch [--paths <file...>]`。父需求或类型不唯一时补 `--related <feature>#R-NN` / `--type`，不要先改代码。
- 回推：变更/缺陷实现后运行 `atlas change --unit <请求ID|任务ID>` 或 `atlas bug --unit <请求ID|任务ID>`，按 diff 更新活文档/PRD/AC/E2E/spec 并校验；语义冲突必须带 `--decision` 与 `--decision-by`。
- 提交前：`atlas workflow verify --unit <ID>`（未通过不得提交或收口）
- 收口：`atlas workflow finish --unit <ID>`（读独立审查 PASS + 本任务 AC 关联的 E2E 结论：`red` 阻断，缺数据显式 `SKIP`；完成后任务移入 `.atlas/tasks/archive/<YYYY-MM>/`）
- **平台口径（Windows）**：契约里的 `python3` 用 `python` 替代（需 Python 3.10+）。

撞到「规则本身不合业务」不许静默绕过：按 `.atlas/shared/global-rules.md` §15 提炼设计问题后 `atlas report` 上报。

> 本段由 `atlas/install.py` 幂等维护（区块可重放）。请勿手改；改契约请改 atlas 源包后重跑 `atlas init`。
