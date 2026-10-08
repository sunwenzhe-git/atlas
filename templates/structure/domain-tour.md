---
paths:
  - '**'
---

<!-- atlas:facts:begin -->
# [必填：产品名] · 代码导航（codebase tour）

> 结构基线蒸馏的**入口索引**——告诉 agent **去哪读**，不复制结构事实正文。基线 `[必填：commit]`。

## 项目概况

- 应用：[必填：逐个 app 名（role）]
- 候选域：[必填：N]

## 全局事实（跨域）

| 事实 | 出处 |
|---|---|
| 目录与模块地图 | `.trellis/spec/structure/global/directory-map.md` |
| 全站路由总表 | `.trellis/spec/structure/global/routes.md` |

## 域速查表

| 域 | 中文名 | 涉及 app | 状态 |
|---|---|---|---|
| `[必填：domain-slug]` | [必填] | [必填] | 候选 |

> 碰某域代码时，对应 `.trellis/spec/structure/domains/<domain>.md` 会自动注入，含该域结构文档链接。
<!-- atlas:facts:end -->

## 维护约定

- **事实区**：标记内由 `refresh_structure.py`（`after_finish` hook）刷新。
- **语义区**：标记外内容由 AI / `trellis-update-spec` 维护。
