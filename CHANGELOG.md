# 更新日志 (CHANGELOG)

本项目遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/) 语义化版本规范与 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 变更记录规范。

---

## [v0.1.0-beta.7] - 2026-10-10

### 🚀 新增功能 (Features)

* **CLI 自身升级 (`atlas upgrade`)**：支持一键检查并通过 npm 更新全局 CLI 至最新版本，支持 `--tag beta` 体验预发布通道以及 `--dry-run` 预览升级命令。
* **项目线束增量刷新 (`atlas update`)**：在目标项目目录下运行，可平滑增量更新 `.atlas/` 治理契约与各平台 skills 瘦桩，具备幂等安全性，不覆盖已有业务代码与技术栈画像。
* **共享内核库 (`_support/`)**：
  * `siblings.py`：标准化的包内模块加载器，提供纯净的独立导入与执行隔离。
  * `case_block.py`：增强型 E2E 用例块解析与结构化提取能力。
  * `stack_profile.py`：健壮的技术栈画像（`stack-profile.yaml`）解析与元数据提取器。
* **回灌工具 (`scripts/backflow.py`)**：提供项目级资产变更向上游主仓库回灌对齐的自动化支持。

### 🛡️ 架构治理 (Architectural Improvements)

* **纯项目级解耦（对标 Trellis 范式）**：
  * 彻底移除全局 Pi 扩展（`atlasharness.ts`）与全局 skills 声明，解决因全局包安装导致所有会话提示词被污染的痛点。
  * Skills 改为按需装配：仅在项目执行 `atlas init` 或 `atlas update` 时，在目标项目的本地目录（`.agents/skills/`、`.claude/skills/` 等）下发轻量瘦桩，离开项目即恢复纯净环境。
* **包构建优化**：将 `_support/` 共享内核与 `CHANGELOG.md` 显式纳入 npm 分发白名单，确保离线与全局安装均能完备解析。

### 🧪 测试与质量 (Tests & Quality)

* 新增全套命令级回归测试套件：`test_cli_commands.py`、`test_backflow.py`、`test_shared_kernel.py`、`test_nested_repo_gitlink_guard.py`。
* 项目全套回归测试增至 335 项用例，保持 100% 稳定通过（332 passed, 3 skipped）。
