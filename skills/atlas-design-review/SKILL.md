---
name: atlas-design-review
description: "方案评审员（独立审查的第 3 类实例）：把「独立审查」用到**设计决策**上——对 grilling 一轮问答产出的推荐（或任一待定设计主张）做一次**独立复核**：审查者先不看推荐、独立给结论，再与推荐比对；一致 ⇒ 低风险侧可自动通过，不一致 ⇒ 一律人工；高风险（`global-rules.md §7` 四条）**一律人工**，评审员只压缩阅读量、不替代确认。骨架正文在 `.atlas/shared/independent-review.md`（本 skill 只是入口瘦桩）。Use when 用户要求 方案评审/评审员/独立复核推荐/设计决策评审/grilling 后复核/design review/对一组设计方案做交叉验证。不生成前沿问题（那是 grilling 的职责）、不替用户签确认门、不审 PRD / E2E 用例（那两处各有自己的实例）。"
---

# atlas design review

「方案评审员」的入口瘦桩。**骨架正文不在本文件**——按名引用 `.atlas/shared/independent-review.md` §8（实例 ④）。

## 先读

1. `.atlas/shared/independent-review.md` —— 骨架条款（§2）、输出契约（§3）、门禁（§4）、执行器（§5）、成本约束（§6）、校准环（§7），以及**实例 ④ 的专属条款**（§8：分级线 / 与 grilling 的串行关系 / 替代方案 / 留痕落点）。
2. `.atlas/shared/global-rules.md` §7 —— 高风险四条（本实例**一律人工**的那批）。

## 什么时候用它

- **串行两道**里的第二道：`grilling`（产设计树 + 前沿问题 + 每条推荐）→ 用户答 frontier 轮 → **本评审**复核该轮**全部**推荐 → 一致：继续下一轮 / 不一致：人工。
- 任一「已有一组主张、需要交叉验证」的场合。

## 边界

- **不生成前沿问题** —— 那是 `grilling` 的职责；让它生成问题 = 又变成无界探索（`independent-review.md` §6 第 6 条同源）。
- **不替代用户确认门** —— 评审员可以替人「读」，不能替人「签」；`global-rules.md §7` 四条**一律人工**。
- **不落笔改动被审对象** —— 只审不改。
- **不使用同源上下文** —— 审查者必须 fresh context，且档位不得低于生成者（`independent-review.md` §5）。

## 怎么做（祈使句）

1. 读骨架与 `§8`，确认本次属**低风险**还是 **§7 高风险**（决定「一致可否自动通过」）。
2. 产**输入清单**：`python3 .atlas/scripts/make_review_inputs.py --out product/reviews/<日期>-design-review-<主题>/inputs`（指针化，不拷副本）。
3. **先独立得出**该轮每条主张的结论（不看推荐），再比对；**不一致一律人工**。
4. 按 `§3` 出**双份**留痕（`README.md` + `review.json`）；每条 finding 带结论与理由；替代方案**必须带代价说明**，且**不得自行采纳**。
5. 低风险侧按 `§7` 的校准环记 `product/reviews/calibration.jsonl`；**§7 高风险不记**。
