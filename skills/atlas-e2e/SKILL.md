---
name: atlas-e2e
description: "项目级 E2E 验收用例环：从 PRD 的 AC（业务预期）与用例分片的 testid 应然清单产出「页面分片 + 总索引」用例资产，testid 应然（分片）⇔ 实然（前端源码）按页双向集合校验，再从分片生成 E2E 脚本、在真实应用单段执行（e2e.app_base_url）。Use when 用户要求 E2E 用例/E2E 索引/用例索引/验收用例/页面分片/用例分片/testid 规范/testid 校验/交互冒烟/从分片生成脚本/Playwright 脚本。不产出 PRD、结构事实、业务代码或影响面识别算法（分别是其它 atlas 环与 apply 的职责）。"
---

# atlas e2e

验收用例环。读 **PRD 的 AC**（业务预期）与**用例分片的 `testid:` 应然清单**（交互与锚点），产出「页面分片 + 总索引」的 E2E 用例资产，用 **testid 应然（分片）⇔ 实然（前端源码）**的按页双向集合校验对账，再从分片生成 E2E 脚本、在真实应用**单段**执行（`e2e.app_base_url`）。

## 先读

1. 共享契约（`.atlas/shared/`）：`global-rules.md`、`stack-profile.md`、`single-source.md`、`layout.md`。
2. 本环契约：`.atlas/rings/e2e/reference.md`。

## 路径

本项目 atlas 包在 `<项目根>/.atlas/`；`<项目根>` = 当前工作目录（含 `.trellis/` 与 `product/` 的那层）。用例资产落 `<项目根>/product/e2e/`；实现期 testid 薄桩落 `<项目根>/.trellis/spec/conventions/testid.md`。

## 边界

只产出 E2E 用例资产与 E2E 脚本，**不得**顺手写 PRD、结构事实、业务代码，也不实现影响面识别算法。越界即失败。

- **依据来源硬优先级**：业务预期只来自域级 PRD 的 AC；交互与 testid **应然**来自用例分片（E1）；`.trellis/spec/structure/` 只作参考基线，禁止反推预期。
- **testid 是唯一硬锚**：必要元素必须带 `data-testid`，脚本一律以 testid 定位；**应然（分片 `testid:` 清单）⇔ 实然（前端源码 `data-testid` 扫描）**按页双向集合校验（已实现页必须相等；未实现页 SKIP / WARN，`实现状态` 见索引页面表）。
- **页面 slug = 分片文件名**（E1：slug 规则正文在环契约 §3.1）：分片键只认页面；跨页记 `pages[]`，绝不复制；「页 ↔ 真实路由」的唯一真相源 = 索引**页面表**。
- **状态类字段只在索引**：执行结果回写 `e2e-index.md` 的 `状态` / `状态原因`。
- **结果断言硬规则**：禁止把瞬时反馈（toast / 成功提示 / 弹窗关闭）当验证；持久化写（create/edit/delete/save）必须**刷新后复断言**；断言须落在与被操作控件**不同的真相源**；编辑/切换类断言**前后两端**；文案用渲染后可见文案。
- **数据前提**：用例数据必须确定性、可重跑、用例间互不依赖；不引入外部造数服务，也不依赖已退役的原型 mock 层（E1 单段 = 真实应用）。
- **门控态**：全局 PRD 待决策非空 ⇒ 域级 PRD 未产出 ⇒ 只落「空索引 + 空分片」骨架，校验器记 N/A，不杜撰用例。
- **独立审查（环间门，`reference.md` §12）**：用例产出后、生成脚本前跑一次独立审查 —— 分片 fan-out（阈值 **20 条或 500 行**）+ **一个全局审查者**（去重 3-Gate / 索引↔分片一致性 / AC 覆盖重复）；两轮维度 **3 致命（D1 可证伪性 / D4 写类复断言 / D6 零断言步骤）+ 5 质量**，第二轮按**用例级**条件化；报告落 `product/e2e/reviews/<日期>-<范围>/`，与人工评审账本 `console/` **分离**；骨架按名引用 `.atlas/shared/independent-review.md`；**有 `Critical` ⇒ `gen_e2e_scripts.py --apply` 拒绝写盘**。
