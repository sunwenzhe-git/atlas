---
name: atlas-prd
description: "项目级产品需求文档（PRD）：产出全局 prd.md + 每个产品功能域一份域级 PRD，含功能架构、范围与处置、Rule Set 与可追溯 AC。Use when 用户要求 项目级 PRD/产品需求文档/全局 PRD/域级 PRD/功能架构/需求范围与处置/业务规则/验收标准 AC/PRD 审查。不产出 E2E 用例、代码或结构事实（结构事实是 atlas-structure）。"
---

# atlas prd

项目级 PRD 环。产出**应然**文档（只写产品应该是什么样，不写实现进度、不挂状态）。

## 先读

1. 共享契约（`.atlas/shared/`）：`global-rules.md`、`stack-profile.md`、`single-source.md`、`layout.md`。
2. 本环契约：`.atlas/rings/prd/reference.md`。

## 路径

本项目 atlas 包在 `<项目根>/.atlas/`；`<项目根>` = 当前工作目录（含 `.trellis/` 与 `product/` 的那层）。

## 边界

不产出 E2E 用例、代码或结构事实。越界即失败。

- **域级 PRD 有两种形态**（契约 §4）：`origin: adopt` 的**首轮开户**用**开户最小集**（一 域概述 / 二 功能清单 / 四 业务规则 / 五 验收标准 四节；三 功能详细说明、六 Assumptions & Defaults **整节不出现**，留到该域首次由 `apply <需求ID>` 增量时补齐）；其余场景用完整形态。两种形态受同一套机器门约束。
