# REVIEW-20261122-08: RFC-20261122-08 行级锚定测量面草案双评审记录

> 评审对象：`proposals/RFC-20261122-08-line-anchoring-warn-measurement.md`
> 评审形态：全档双评审（RFC-20261114-07 惯例）——评审 A = tech-proposal-reviewer 设计评审（29 万 token，17 工具核验）；评审 B = general-purpose 独立核验（证据链逐条对表 + 算法实测，199 万 token，55 工具核验）。两评独立并行、互不通气。
> 评审基线：HEAD `ac061ac`（评审中发现 RFC-07 批 e59b501+ac061ac 已提交收口）

---

## 评审 A：设计评审（总裁决 = 修后再审）

**Major ×6**：
- M-1 「零文件交叉（git status 实证）」虚假陈述——RFC-07 批动过 gates.md/docs-map 计数面，且已提交收口
- M-2 L1 复算 diff 基准只写 staged，from/to 与 delta 两种运行模式未定义 ⇒ 非 staged 轮假 mismatch 污染升档分子
- M-3 三态口径漏「报了行号+复算无果」态（hallucinated 摘录与真实漂移混计，毁区分度）
- M-4 「统计面永不 die」与转换器 14 处 die 文化的冲突未给实现约束（stats 写失败会破坏退出码契约）
- M-5 摘除判据「no_field 恒 0」在 CLI 执行器下结构性不可触发；「OCR 产物天然无 existing_code」系无证据断言（其 code_comment 工具层强制该字段）
- M-6 证伪命令按字面不可复跑（session 模式 exit 2 不跑转换器，判别命令应直跑转换器）

**Minor ×6**：m-1 分章 rider 无独立验收/回滚注记；m-2 「现成管道/无新增进程」两处不准（管道在 atlas_review.py:483-486 非 atlas_workflow；转换器自跑 git diff 即新增进程）；m-3 匹配确定性未指定（首处命中策略缺失 ⇒ 钉4 与 mismatch 率不可复现）；m-4 摘除窗 2 窗应对齐先例 3 窗（gates.md:57）+ 窗单位未定义；m-5 接线落点应在 main()（convert() 纯函数体无 I/O）；m-6 existing_code 指令行应放「## 产物」段非探索预算段。

**通过项 ×8**：§1.3 诚实条款落实到位；行号锚全部准确（逐一核实）；stack-profile 不涉产物 schema 判断正确；WARN 不置红依据真实（workflow_causes.py 已落地、blocking_critical 语义错位成立）；两级锚设计正确且必要（pre_existing 硬编码 :164）；gates.md :57 impact_reconcile 为 WARN-only 登记行直接先例；line_anchor.py 组织合规（siblings.load_module 惯例）；unanchored 分档与 :153 降级形态连续。

## 评审 B：独立核验（总裁决 = 有偏差清单，无致命证伪）

**file:line 逐条对表**：全部证实（含 OCR README.md:78 原文实抓、resolver.go 机制逐点吻合）；仅 :286-288 为弱证据（只证字段存在性）与 OCR resolver.go 行号段细节级存疑。

**算法可行性**：hunk 头解析仓内先例证实（`changelog_guard.py:9-11,45` HUNK_RE）；「现成管道/无新增进程」轻度失实（需新增一次 git diff 子进程）；-U0/U3 未显式讨论；滑窗耗时实测 **3.8ms**（万行×10 条），「毫秒级」证实。

**计数棘轮链（核心偏差）**：v1 预警「四处」**一误三漏**——apply.md 咬合不成立（撤）；漏三处必然咬红：`docs/map/index.md`〔共享内核=28→29〕、`shared/gates.md` 191 行 ×2（docs/map/gates.md:18 + atlas-map.html:564）、`atlas-map.html:496`〔转换器 458 行〕。tests 87→88 三面证实（index.md:108 / gates.md:129 / atlas-map.html:308）。

**零文件交叉**：字面证伪、收窄解释成立——代码面零交叉为真（e59b501 diff-stat 实证）；契约面 gates.md + docs/map 两件 + golden 基线同文件（草案自带「登记行提交串行」已隐含承认，属表述不一致非事实错误）。

**golden 面**：咬面比草案宽——212 文件全量内容哈希，五个改动件全在表内 + 新 _support 文件成新条目；「排 RFC-07 golden 之后」约束有据（worktree 对已提交树录纪律）且前置已满足。

**统计落盘**：无消费者冲突证实（review_closure 孤儿扫描只 glob findings/、validate_review_report 只读指名文件、evidence_archive 包容性归档；同形态先例 impact_reconcile.py:137）。

## v2 处置（18 条全采纳、0 驳回、1 部分 → 实为 17+1）

R1-M1+R2-4（§0.1 改写）、R1-M2（基准三模式推导 + unresolvable 档）、R1-M3（三态→四态）、R1-M4（三条实现约束写死）、R1-M5（executor 保留 + 判据分轨 + OCR 断言撤回改「未核实」）、R1-M6（证伪命令直跑转换器）、R2-2（棘轮清单重写：一撤三补 + 算法边界补 -U0/元行/binary + 进程措辞修）、R2-5（golden 宽口径）、R1-m1（rider 独立注记 §3.1）、R1-m2（管道措辞修）、R1-m3（首处命中写死）、R1-m4（窗单位定义 + 摘除 3 窗）、R1-m5（接线落点 main() 链尾）、R1-m6（指令行归产物段）、R2-1（:286-288 引用降级）、R2-3（棘轮现值附实测）、R2-6（落盘安全旁证）。明细见 RFC §0.2 修订摘要表。

## 复核

v2 发回评审 A 复核（其总裁决「修后再审」的闭环义务）。复核结论：**见文末追记**。

---

## 复核追记（2026-11-22）

v2 发回评审 A 复核（续用其原上下文）：**修后通过**——18 条意见全部有实质处置且 6 Major 方向性修补全部成立；v2 新引入的事实锚（棘轮现值/先例行号）抽验全部核实。附**落刀前必补五条单句级处方**（R-1~R-5，已全部落进 v2 正文）：R-1 证伪命令补 `--diff-base/--diff-head` 与夹具 grounding；R-3 diff 命令分模式（staged 用 `git diff --cached`，`INDEX` 非合法 ref）；R-2 anchored 谓词 = 区间相交（含子集）；R-4 `--no-renames` 下纯 rename 有 hunk，删该特例 + 补「path 不在 diff ⇒ 跳 L1 直入 L2」；R-5 executor 记录原值、判据窗只认 `session-subagent`。复核声明「五条全部照处方落进 §2.1/§2.2 后即可落刀，无需回审」。**RFC-20261122-08 转入落刀状态。**
