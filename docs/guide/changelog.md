# 变更与更新日志 (Changelog)

本文档记录了 **Atlas** 每个版本的重要特性变更、架构治理与问题修复。遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 规范。

---

## [v0.1.0-beta.14] - 2026-10-15

### 🚀 AI 原生自愈与免阻断架构升级 (AI-Native Resilience & Zero Friction)

* **【生成器自愈化】审查门免阻断自愈 (`scripts/gen_e2e_scripts.py`, `_support/stack_profile.py`, `validators/validate_stack_profile.py`)**：
  - 彻底终结 `review.json` 缺失直接抛 `exit 2` 阻断写盘、逼迫 AI 人工造假报告桩的历史包袱；
  - 规范化扩充 `e2e.review` 字段白名单与模式枚举：支持 `mode: gate`（严格审查门）、`mode: auto-baseline`（自愈基线模式）与 `mode: off`（免审）；
  - 当项目处于存量接管形态（`origin: adopt`）或声明了 `review: null` / `auto-baseline` 时，若未发现历史审查报告，在全量校验通过后自动自愈生成最小可证伪基线审查报告（`*-adopt-baseline` 或 `*-auto-baseline`），放行脚本写盘。
* **【提取器增强】JS 动态 testid 提取与文件级 counts 重构 (`validators/validate_testids.py`)**：
  - 全面支持原生 JS 命令式赋值语法：捕获 `el.dataset.testid = "..."`、`el.dataset['testid'] = "..."` 与 `el.setAttribute("data-testid", "...")`（含单/双引号、JSX 花括号与可枚举模板字符串）；
  - 引入源码注释预清洗（`strip_comments`），自动剥离 HTML 注释与 JS/TS 行/块注释，避免废弃 id 产生幻影报错；
  - 重构 `counts` 全站唯一规则为「声明文件数」，同一文件内的 HTML 与 JS 共存、条件分支或动态列表赋值计数为 1（天然豁免），跨文件冲突严格报警，业务代码无需在 HTML 补 `<template>` 假桩。
* **【存量脚手架自适应】Python pytest.ini 无损兜底 (`patches/project-wiring/apply-wiring.py`, `adapters/tests.py`)**：
  - 项目装配接线（`apply-wiring.py`）智能识别 Python 特征，同时 `adapters/tests.py` 输出 `python3 -m pytest` 标准命令；
  - 根目录无 pytest 配置时自动生成默认 `pytest.ini` 并配置 `pythonpath = .` 与 AC 标记；已有配置无损追加，彻底免除 Python 模块导入找不到路径的环境摩擦。
* **【Mock 零步探针容忍】打桩用例自动免除零步恒真探针 (`scripts/gen_e2e_scripts.py`)**：
  - 识别用例分片中的 `mock:` 段，整体免除注入零步基线探针（`probes`），彻底根除外部接口打桩导致的页面初始容器被误判为“恒真（假阳性）”；
  - 用例本身的 Playwright 测试体 100% 完整保留严格断言，AI 与开发者无需再机械式手写 `initial:` 豁免前缀。

---

## [v0.1.0-beta.13] - 2026-10-14

### 🚀 核心协议全栈化与沙箱前沿加固 (Core Protocols & Usability)

* **`e2e.mock` 协议支持 `mode: auto` 混合穿透与白名单扩充 (`scripts/gen_e2e_scripts.py`, `validators/validate_stack_profile.py`, `validators/validate_e2e_mocks.py`)**：
  - 正式支持 `e2e.mock.mode: auto`，在全栈/混合测试场景下，未命中桩表的路由自动调用 `await route.continue();` 穿透访问真实后端，彻底解决纯前端 fail-loud 误掐真实 API 的问题；
  - `stack-profile` 的 `e2e.mock` 白名单正式扩充收录 `fixtures_dir` 并支持动态目录路径解析；
  - 增强网络 Mock 外部 URL（`https://*`）通配匹配与 `api_prefix` 智能兜底。
* **全局 Node Playwright 健壮探测与 Python CLI 防御 (`scripts/atlas_check.py`, `scripts/e2e_console.py`, F19)**：
  - 支持纯 Python/存量项目（`node_modules: null`）通过全局 Node 模块（`npm i -g @playwright/test`）直接运行 E2E 真跑；
  - 引入 `_is_node_playwright()` 文件内容特征检测，精准过滤 PATH 中同名的 Python Playwright CLI；
  - 增加对标准 Unix `<prefix>/bin` 与现代 `npm prefix -g` 的候选路径推导。
* **存量沙箱 `origin: adopt` testid 单向子集校验 (`validators/validate_testids.py`, F20)**：
  - 在存量接管模式下，用例未引用的存量历史 testid 降级为 WARN/INFO 记录，彻底解除对未改动老元素的强制绑架；
  - 对新需求用例中声明的 testid 依然维持严格双向闭环。
* **架构决策记录（ADR）演进链拓扑成环拦截 (`validators/validate_adr.py`)**：
  - 校验器内置 DFS 染色法有向无环图（DAG）检测，精准捕获 `0001 -> 0002 -> 0001` 等循环废弃回环（`adr_cycle_detected: WARN`），守卫架构演进终态健康。

---

## [v0.1.0-beta.12] - 2026-10-14

### 🐛 缺陷修复与沙箱实测回灌 (Bug Fixes & Usability)

* **`seed × models` 对账门字段解析缺陷修复 (`validators/validate_e2e_index.py`, F14)**：重构数据模型解析存储为 `dict[str, set[str]]`，支持单表多行多字段累加收集与精确成员判定，根治以往首行 `setdefault` 遗漏后续字段及子串模糊匹配引发的校验误杀。
* **`install.sh` 刷新时保留 `.atlas/runs/` 运行态数据 (`install.sh`, F18)**：装配刷新逻辑由整包物理删除改为白名单子目录清理（`shared rings apply scripts templates adapters validators patches tests _support`），避免冲掉包含后端 AC 覆盖率基线及控制台快照的非 git 跟踪运行态数据。
* **结构环 `categories` A/H 键值解析前缀容错 (`validators/validate_structure.py`, F17)**：引入关键字前缀扫描提取器 `_cat_token`，优先匹配 `covered`、`skipped`、`added` 合法状态词，兼容形如 `"H": "H: skipped"` 的书写习惯。
* **适配器空产物避免意外清空既有结构事实 (`scripts/refresh_structure.py`, F16)**：在 `render_routes` 中增加空产物守卫，当 routes 适配器在非支持技术栈上输出 `{"items": []}` 且目标 `routes.md` 已存在有效手工事实行时，自动保留既有内容并输出告警，防止静默清空事实表。
* **存量接入指南补充实现期薄桩步骤 (`docs/guide/legacy-adoption.md`, F15)**：在存量接入步骤 Checklist 与命令指引中显式补充 `python3 .atlas/scripts/gen_testid_stub.py --root .` 生成实现期薄桩（`.trellis/spec/conventions/testid.md`），闭环开户标准，避免首日 `validate_testids.py` 硬门禁报红。
* **官网架构设计文档标题归一 (`docs/design/`)**：结构环设计文档标题统一归一为《结构（逆向）环设计与实体边界治理》，规范文档体系表达。

---

## [v0.1.0-beta.11] - 2026-10-14

### 🚀 架构解耦与官网升级 (Architecture & Documentation)

* **彻底解耦 open-zk-kb（知识库与台账子系统退役）**：移除开发期自举的 `kb_*` 脚本与 `validate_ledger.py`（核心门禁校验器精简为 9 个）；域级 AC 编号唯一性强校验契约完整归位至 `validators/validate_prd.py`；全量清理契约、装配脚本 `install.sh` 与门禁清单中对旧台账的冗余依赖。
* **官网全新上线「设计方案」栏目 (`docs/design/`)**：新增 5 篇高质量深度架构设计解析（《架构总览与分层设计》《结构环与实体边界治理》《PRD 环与业务规则闭环》《E2E 环与确定性断言工程》《工程分发与线束装配体系》），全面解密 Atlas 核心实现机理。
* **工程叙事严谨化与概念术语对齐**：全面摒弃情绪化修辞，回归务实的第一人称工程手记风格；对齐「双线束模型」（项目级工程线束 vs 需求级业务线束）与「两道全局护栏」概念体系；完善内置 7 大技能清单与 Pi Agent 扩展硬化指南（rtk 退出码保真性告警与 warm-cache 真实计费口径）。

### 🐛 缺陷修复与沙箱实测加固 (Bug Fixes & Usability)

* **Playwright 慢动作回放改由环境变量注入 (`scripts/e2e_console.py`)**：修复 `e2e_console` 回放时拼接 `--slowmo=<N>` CLI 旗标导致 Playwright 1.64 `test` 子命令报 `unknown option`（exit 1）的缺陷。改由 `ATLAS_SLOWMO` 环境变量向 Playwright 配置文件的 `launchOptions.slowMo` 注入，保障无头/有头慢动作回放稳定性。
* **E2E 生成器清扫退役页孤儿 spec (`scripts/gen_e2e_scripts.py`)**：修复 `--apply` 模式未清扫已退役页面用例导致孤儿 spec 遗留并在后续被测试拾起报错的问题。dry-run 显式上报退役变更，`--apply` 精准只清理带 `AUTO-GENERATED` 标记的孤儿用例。
* **存量非规范 testid 兼容性放行 (`validators/validate_testids.py`)**：对遗留存量非标 testid 降级为 WARN 警告放行，仅在新增违规分片时硬阻断，降低既有存量工程（Adopt 模式）接入阻力。

---

## [v0.1.0-beta.10] - 2026-10-13

### 🐛 缺陷修复与体验增强 (Bug Fixes & Usability)

* **PRD 规则表列序精准指路 (`validators/validate_prd.py`)**：优化 §四 业务规则表解析体验。当用户声明了「所属功能」表头但未按契约排在第 3 列时，不再输出具有误导性的“未声明所属功能”，而是明确给出友好的指路报错：指出所属功能应在第 3 列（规则 ID ｜ 规则内容 ｜ 所属功能 ｜ …）及当前实际列位，大幅提升排查效率。
* **Playwright 运行通道环境变量覆盖 (`scripts/gen_e2e_scripts.py`)**：在生成的 `playwright.config.ts` 中增加 `channel: process.env.ATLAS_PLAYWRIGHT_CHANNEL` 覆盖机制。支持开发者在需要时直接通过环境变量（如 `ATLAS_PLAYWRIGHT_CHANNEL=chrome`）复用宿主机 Google Chrome 浏览器，免去非必要重新下载大体积 Chromium 二进制的等待。

---

## [v0.1.0-beta.9] - 2026-10-13

### 🐛 缺陷修复与门禁严苛化 (Bug Fixes & Hardening)

* **PRD 目录卫生门 (`validators/validate_prd.py`)**：新增「参数0 目录规范」校验门，严禁 `product/prd/` 目录下存在非法子目录（如 `domains/`）或非标准命名 Markdown。彻底杜绝因目录层级脱节导致 `domains` 计数为空、使“待决策登记非空却产出域级 PRD”被静默穿透发放虚假通行证的缺陷。
* **占位符检测排除合法元数据 (`validators/validate_prd.py`)**：在参数 2 零占位符扫描中，增加对 frontmatter 合法元数据行（如 `domain_code: TODO`、`domain: todo`）的排除，消除待办类合法领域命名的误判。
* **AC 代码对账口径收口平铺 (`validators/validate_ac_alignment.py`)**：将 `collect_prd_acs` 收敛为严格对齐平铺契约的发现范围（`prd.md` 与 `*-prd.md`），显式隔离并排除 `reviews/` 等非需求子目录，防止评审历史或废弃文档中残留的旧 AC 污染已声明白名单。
* **E2E node_modules 相对路径锚定 (`scripts/atlas_check.py`)**：修复 `check_e2e` 中提取的 `node_modules` 相对路径未与传入的 `root` 参数锚定导致跨 CWD 运行时误判的问题（`root / nm_rel`），并在可执行文件缺失时追加友好的安装指引提示（`npm i -D @playwright/test`）。

### 🧪 测试套件 (Tests)

* 补充目录规范变异测试 `test_prd_illegal_nested_directories_fails`，`shared/gates.md` 对应台账对齐至 76 条。
* 补充 AC 对账隔离评审文档测试 `test_ac_alignment_ignores_reviews_and_subdirectories`。
* 补充外部 CWD 路径锚定测试 `test_check_e2e_node_modules_anchored_to_root`。全量用例扩增至 348 条，保持 100% 通过。

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
