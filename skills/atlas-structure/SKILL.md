---
name: atlas-structure
description: "项目结构基线（逆向）与规范开户：读代码产出结构事实（目录与模块地图、路由与页面清单、接口清单、数据模型清单）与约定类规范，落 .atlas/spec/structure/ 与 .atlas/spec/conventions/，并从代码提议候选域。支持单轮增量逆向与「开户模式」全量补齐整个项目规范。Use when 用户要求 项目结构/项目整体结构/逆向/项目基线/目录与模块地图/路由清单/接口清单/数据模型清单/候选域/开户规范/项目规范生成/spec bootstrap/全量规范补齐/存量项目规范。不产出 PRD、E2E 用例或需求（那是其它 atlas 环）。"
---

# atlas structure

结构基线（逆向）环，同时承担**项目规范开户**。读代码产出**结构事实**，落 **`.atlas/spec/structure/`**；约定类规范落 **`.atlas/spec/conventions/`**。两者都带 `paths:` 索引，供 `atlas workflow dispatch --paths` 按改动路径**最小注入**。

## 先读

1. 共享契约（`.atlas/shared/`）：`global-rules.md`、`stack-profile.md`、`single-source.md`、`layout.md`。
   - 路径约定：下文 `product/` 均为**默认资产根**示例；实际按项目根 `atlas.config.yaml` 的 `layout.assets_root` 解析（`shared/layout.md` §1.1）。
2. 本环契约：`.atlas/rings/structure/reference.md`。

## 路径

本项目 atlas 包在 `<项目根>/.atlas/`；`<项目根>` = 当前工作目录（含 `.atlas/` 与 `product/` 的那层）。结构事实落 `<项目根>/.atlas/spec/structure/`；约定规范落 `<项目根>/.atlas/spec/conventions/`。

## 边界

只产出结构事实与**约定类规范**，**不得**顺手写 PRD、用例或需求。越界即失败。

- 与 PRD 环：本环先跑、提议**候选域**；PRD 定稿域。两者不自动互相触发。
- **域清单先请用户过目**：域 id 是全链路键，PRD 定稿时会合并 / 拆分 / 改名 ⇒ 动手铺域级文件**之前**先把候选域表交给用户（`reference.md` §6 步 4）；未过目就产出的，报告里须点名「未确认」。
- **只有 `tour.md`、`domains/<domain>.md`、`conventions/*.md` 带 `paths:`**（注入指针）；其余事实文档无 `paths`、按需 Read。事实区用 `atlas:facts` 标记、脚本刷新；语义区留给 AI。

## 开户模式（全量规范补齐）

存量项目接入、或 `.atlas/spec/` 为空 / 陈旧时，用一次全量开户把**整个项目的规范**建起来：

1. **盘点**：看 `.atlas/spec/` 现状，标记「可复用 / 陈旧 / 模板残留」；无 `.atlas/spec/` 先 `atlas init`（存量项目走 `atlas-apply adopt`）。
2. **分析真实代码库**：包清单、workspace、构建脚本、入口路由、测试风格、配置与环境；必要时用 GitNexus / ABCoder（`references/repository-analysis.md`）。结论必须回到源码核对。
3. **划边界**：按包或按层（前端 / 后端 / CLI / worker / 共享库 / 工具）拆；小项目一次跑完，不人为拆任务。
4. **产出**：
   - 结构导航：`structure/tour.md`（`paths: ['**']`）+ `structure/domains/<domain>.md`（域 globs）；
   - 事实正文：目录图 / 路由 / 接口 / 数据模型（**不带 `paths:`**）；
   - 约定规范：`conventions/<topic>.md`（如组件复用、错误处理、命名），带精确 globs；`testid.md` 由 E2E 环生成，本环不写。
5. **写对 `paths:`**：每条 glob 必须能被真实路径命中；禁止用 `**` 逃逸（唯一例外 `tour.md`）。只改前端就只该命中前端域与前端约定。
6. **验证**：
   ```bash
   python3 .atlas/scripts/refresh_structure.py --root . --chain
   python3 .atlas/scripts/atlas_check.py --fast
   grep -rn "TODO\|待填\|placeholder\|<%" .atlas/spec
   atlas workflow dispatch --unit <ID> --paths <真实文件>...
   ```
   最后一条确认 `dispatch.md` 只出现命中域，不出现无关域。

**红线**：不写占位符 / 通用框架建议；规则必须指到真实文件 / 测试 / 项目文档；不复制大段代码；不顺手写 PRD / E2E；不改业务源码（除非任务显式要求）。

## 参考路由

| 需要 | 读 |
|---|---|
| 仓库架构分析与工具用法 | [references/repository-analysis.md](references/repository-analysis.md) |
| 拆分与任务卡写法 | [references/spec-task-planning.md](references/spec-task-planning.md) |
| 规范写作标准与示例 | [references/spec-writing.md](references/spec-writing.md) |
| GitNexus / ABCoder 接入 | [references/mcp-setup.md](references/mcp-setup.md) |
