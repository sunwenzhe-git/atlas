# 暗色模式协议

_原 SKILL.md Section 8 逐字移入。强制要求在 SKILL.md 6.G 里保留。_

**默认双模式。** 除非 brief 是模仿纸质印刷的编辑型内容，否则不要假设只做浅色。

### 8.A token 策略（选一种，然后一路用到底）
* **Tailwind `dark:` 变体**（工具类优先项目的默认做法）：每个颜色工具类都配上它的暗色变体（`bg-white dark:bg-zinc-950`、`text-gray-900 dark:text-gray-100`）。
* **CSS 变量**（用于 shadcn/ui、Radix Themes 或自带主题机制的组件库）：定义语义 token（`--surface`、`--surface-elevated`、`--text-primary`、`--accent`），在 `[data-theme="dark"]` 或 `@media (prefers-color-scheme: dark)` 下换值。

### 8.B 这里不规定具体颜色
颜色由 brief 和品牌决定。本 skill 只强制四件事：
* **对比度**：正文最低 WCAG AA，hero 文案目标 AAA。
* **层级对等**：浅色下成立的视觉层级，暗色下也必须成立。CTA 在浅色里跳得出来，暗色里也要跳得出来。
* **品牌还原**：主品牌色必须保持可辨识。不要把品牌色去饱和到暗色模式里。
* **不用纯 `#000000`、不用纯 `#ffffff`**：用近黑（`zinc-950`、近黑暖灰）与近白。纯值会杀掉层次。

### 8.C 默认模式
尊重 `prefers-color-scheme`，除非品牌坚持某一模式。如果任一模式会丢失关键品牌表达，再加一个手动切换。

### 8.D 交付前两种模式都要测
开发过程中就用两种模式打开页面。**只看过一种模式的页面不许交付。**
