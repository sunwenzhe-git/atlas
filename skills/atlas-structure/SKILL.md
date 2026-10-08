---
name: atlas-structure
description: "项目结构基线（逆向）：读代码产出结构事实，落 .trellis/spec/structure/（Trellis 路径注入层）——目录与模块地图、路由与页面清单、接口清单、数据模型清单、设计 token；并从代码提议候选域。Use when 用户要求 项目结构/项目整体结构/逆向/项目基线/目录与模块地图/路由清单/接口清单/数据模型清单/设计 token/候选域。不产出 PRD、E2E 用例或需求（那是其它 atlas 环）。"
---

# atlas structure

结构基线（逆向）环。读代码产出**结构事实**，落 **`.trellis/spec/structure/`**（Trellis 的路径注入层）——既是项目级事实，又能被 Trellis 任务原生注入消费。

## 先读

1. 共享契约（`.atlas/shared/`）：`global-rules.md`、`stack-profile.md`、`single-source.md`、`layout.md`。
2. 本环契约：`.atlas/rings/structure/reference.md`。

## 路径

本项目 atlas 包在 `<项目根>/.atlas/`；`<项目根>` = 当前工作目录（含 `.trellis/` 与 `product/` 的那层）。结构事实落 `<项目根>/.trellis/spec/structure/`。

## 边界

只产出结构事实，**不得**顺手写 PRD、用例或需求。越界即失败。

- 与 PRD 环：本环先跑、提议**候选域**；PRD 定稿域。两者不自动互相触发。
- **只有 `tour.md` 与 `domains/<domain>.md` 带 `paths:`**（指针，被注入）；其余事实文档无 `paths`、按需 Read。事实区用 `atlas:facts` 标记、脚本刷新；语义区留给 AI。
