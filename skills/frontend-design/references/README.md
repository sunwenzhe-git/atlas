# references/ 细则层

`SKILL.md` 是规范文件：所有规则、禁令和预检闸门都在那里。这个目录存放那些规则**指向的细则**：具体数值、错误/正确代码对照，以及每条规则的外部出处。

## 什么时候读这里的文件

**准备为那条规则写代码时再读**，不要提前读。索引见 `SKILL.md` 的「阅读地图」，以及下面的分层表。

## 目录分层

| 文件 | 内容 |
|---|---|
| `access-*.md` | 可访问性机制：焦点、键盘、语义、ARIA、alt 文字、目标尺寸、标题层级 |
| `color-*.md` | 对比度、不得只靠颜色、暗色模式、语义 token |
| `cwv-*.md` | Core Web Vitals：LCP、CLS、INP、响应式图片、延迟加载、关键 CSS |
| `form-*.md` | 校验时机、错误文案、label 位置、输入类型、自动填充 |
| `layout-*.md` | 层级、留白、F 型阅读、栅格、单一 CTA、邻近性 |
| `resp-*.md` | 移动优先、流体字号、容器查询、触摸目标、视口 meta |
| `typo-*.md` | 字体加载、行高、行宽、应用层系统字栈 |
| `anim-*.md` | GPU 属性、降低动效、时长与缓动、will-change |
| `design-system-map.md` | 设计系统选型（SKILL.md Section 2 的完整版）|
| `design-directives.md` | 字体、配色、材质、交互状态、图片策略、内容密度、引言（Section 4 的完整版）|
| `knob-definitions.md` | 三个旋钮的三档技术定义：栅格、缓动、间距、移动端塌陷（原 SKILL.md Section 1.D）|
| `tuning-verbs.md` | 调优动词表：bolder / quieter / distill / harden / typeset / colorize → 旋钮增量与典型动作（SKILL.md 1.E 的设计档案为基准）|
| `motion-skeletons.md` | 滚动动效骨架与禁止的动画写法（Section 5）|
| `dark-mode-protocol.md` | 暗色模式协议（Section 8）|
| `pattern-vocabulary.md` | 构图范式词汇表（Section 10）|
| `redesign-protocol.md` | 改版协议（Section 11）|
| `block-library.md` | 区块库契约（Section 12）|
| `ai-tells.md` | 完整带注解的 AI 味禁令清单（Section 9）|
| `design-systems.md` | 各设计系统的安装命令与官方文档链接 |

## 优先级

**`SKILL.md` 里写明的，以 `SKILL.md` 为准。** 以下 6 个文件带有 `Scope note (merged skill, ...)` 结尾注记，记录了两份源 skill 打架时的裁决：**display 行高**、**字体适用范围**、**动效时长与缓动**、**目标尺寸 vs 密度**、**栅格 vs 非对称**。全部裁决的汇总表在 `SKILL.md` 的 6.K。

## 语言现状

| | 文件数 | 字节 |
|---|---|---|
| 中文（说明文字） | 11 | 68,608 |
| 英文原文（保留） | 43 | 84,116 |

中文的 11 个：本文件、`ai-tells.md`、`design-directives.md`、`motion-skeletons.md`、`design-system-map.md`、`pattern-vocabulary.md`、`redesign-protocol.md`、`block-library.md`、`dark-mode-protocol.md`、`knob-definitions.md`、`tuning-verbs.md`。

保留英文的：`design-systems.md`（几乎全是 npm 命令与官方文档 URL），以及 42 个 `access-*` / `color-*` / `cwv-*` / `form-*` / `layout-*` / `resp-*` / `typo-*` / `anim-*` 规则文件。后者是以代码为主的标准细则（WCAG、web.dev 条目），**不参与手工调参**，保留原文即可。

## 语言约定

说明文字为中文；代码、类名、API 名、CSS 属性、规则 ID、文件名、URL 一律保留原文，不得翻译。
