# 变更与更新日志 (Changelog)

本文档记录了 **Atlas** 每个版本的重要特性变更、架构治理与问题修复。遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 规范。

---

## [v0.1.0-beta.8] - 2026-10-12

### 🐛 缺陷修复与鲁棒性增强 (Bug Fixes & Hardening)

* **全量体检生成物容错 (`scripts/atlas_check.py`)**：修复 `gen_e2e_scripts.py` 混杂前置警告日志导致 `json.loads` 解析失败误报 `WARN 生成器输出非 JSON` 的缺陷，增加正则提取 JSON 块容错。
* **事实刷新冷启动容错 (`scripts/refresh_structure.py`)**：修复新建工程在尚未首建结构环时被 Trellis `after_finish` 钩子调用抛出 `ERROR: 缺少 _meta.json` 导致退出码 1 的问题，改为友好 `SKIP` 并以 0 正常退出。
* **E2E 分片块缺字段报错指名 (`validators/validate_e2e_index.py`)**：细化用例分片缺少必填字段（如 `precondition`）时的报错信息，从模糊的 `缺字段=['E2E-xxx']` 优化为精确指名 `E2E-xxx(缺:precondition)`。
* **AC 代码级对账递归扫描 (`validators/validate_ac_alignment.py`)**：修复 `collect_prd_acs` 使用单层 `glob("*.md")` 漏扫 `product/prd/domains/` 域级 PRD 验收准则的问题，改为 `rglob("*.md")` 递归检索。
* **防退化棘轮防污染守卫 (`validators/validate_ac_alignment.py`)**：修复校验器无论是否 FAIL 均无条件落盘基线的缺陷，增加 `res.status != "FAIL"` 状态守卫，防止测试注入坏输入污染历史基线。
* **CLI 出厂测试副本态隔离 (`tests/test_cli_commands.py`)**：为 CLI 测试增加 `pytest.mark.skipif`，在目标项目 `.atlas/tests` 副本态（不分发 `bin/` 与 `install.sh`）下优雅跳过，保证项目端全量体检绿灯。

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
