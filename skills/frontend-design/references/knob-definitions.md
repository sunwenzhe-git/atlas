# 旋钮定义：三档技术参考

_原 SKILL.md Section 1.D（更早为 Section 7）移入于此。设定旋钮值不需要读本文件；要写对应的 CSS / Tailwind 时再读。两条全局禁令不随档位变化：滚动监听禁令见 SKILL.md Section 5，命中区地板见 SKILL.md 6.D。_

## DESIGN_VARIANCE（1-10）

* **1-3（可预期）**：对称 CSS Grid（12 栏、等 fr）、等距 padding、居中。
* **4-7（错位）**：`margin-top: -2rem` 叠压、混搭图片宽高比（4:3 紧挨 16:9）、左对齐标题压在居中数据上。
* **8-10（非对称）**：瀑布流、分数单位栅格（`grid-template-columns: 2fr 1fr 1fr`）、大面积留白区（`padding-left: 20vw`）。
* **移动端覆盖**：4-10 档的非对称版面在 `md:` 以上成立，**在 < 768px 必须塌成严格单列**（`w-full`、`px-4`、`py-8`）。

## MOTION_INTENSITY（1-10）

* **1-3（静态）**：不做自动动画，只有 CSS `:hover` 与 `:active` 状态。
* **4-7（流畅 CSS）**：`transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1)`，`animation-delay` 做入场级联，聚焦 `transform` 与 `opacity`。
* **8-10（高阶编排）**：复杂滚动触发、视差、滚动驱动动画（CSS `animation-timeline` 或 GSAP ScrollTrigger），用 Motion hooks。**绝不使用 `window.addEventListener('scroll')`**，这是硬禁令，见 SKILL.md Section 5。

## VISUAL_DENSITY（1-10）

* **1-3（画廊）**：大量留白，巨大 section 间距（`py-32` 至 `py-48`）。贵、干净。
* **4-7（日常应用）**：常规 Web 间距（`py-16` 至 `py-24`）。
* **8-10（驾驶舱）**：紧 padding。不要卡片盒，用 1px 分隔线切数据。强制：所有数字用 `font-mono`。
* **密度从不决定命中区大小。** `VISUAL_DENSITY` 管的是一个视口里塞多少信息。交互目标在任何密度下都遵守 6.D 的地板（最小 24x24，期望 44x44，间距 8px）。
