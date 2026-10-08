---
name: frontend-design
description: 前端设计 skill，两层合一。第一层是「品味总监」，服务营销类页面（landing page / 官网 / 作品集 / 关于页 / 定价页 / 改版）：判读 brief、推断设计语言、设定三个旋钮（variance / motion / density）、禁用 AI 味套路、执行版面与文案硬规则。第二层是「合规基线」，同时覆盖 Web 产品界面（dashboard / 后台 / 数据密集视图 / 多步表单）：可访问性机制、焦点与键盘、目标尺寸、表单校验体验、Core Web Vitals、暗色模式。交付前由预检闸门强制校验。不适用于原生桌面与移动 App。
license: MIT
---

# 前端设计：品味总监 + 合规基线

> 两个职责合在一处。一个是**总监**：读懂 brief，拒绝产出模板化的营销页。一个是**基线**：拒绝产出不可访问、慢、用不了的界面。
> 下面每条规则都是**情境化**的，不会自动触发。先读 brief，再只取用得上那部分。

---

## 阅读地图（按需打开，不要预加载）

`SKILL.md` 只保留**生成前后必须一直在场**的内容：范围路由、brief 判读、旋钮、约定、会让交付失败的硬规则、合规基线、预检闸门。所有解释、代码骨架、枚举清单都放在 `references/` 里，由触发条件决定何时读。

| 读这个文件 | 什么时候读 |
|---|---|
| `references/design-system-map.md` | 选设计系统或官方包时；或 brief 是一种审美而非一套系统时 |
| `references/design-directives.md` | 写字体、配色校准、材质、交互状态、图片策略、内容密度、引言时。**4.7 与 4.11 因为会直接导致交付失败，在下面保留了一份摘要**，Section 4 的其余细节都在这个文件里 |
| `references/motion-skeletons.md` | 实现滚动动效时。含 GSAP sticky-stack / horizontal-pan / scroll-reveal 的可用骨架 |
| `references/knob-definitions.md` | 要写三档旋钮对应的具体 CSS / Tailwind（栅格轨道、缓动曲线、间距档位）时。原 Section 1.D |
| `references/tuning-verbs.md` | brief 是对既有页面的调优（bolder / quieter / distill / harden / typeset / colorize）而不是新建时 |
| `references/ai-tells.md` | **产出任何版面之前**。完整带注解的禁令清单，含 9.F 摘要背后的全部条目 |
| `references/pattern-vocabulary.md` | 需要命名或调用某个构图范式时（hero 范式、bento、动态字体等）|
| `references/redesign-protocol.md` | brief 是对既有网站的改版 |
| `references/block-library.md` | 要沉淀可复用区块，而不是写一次性 section |
| `references/dark-mode-protocol.md` | 实现暗色模式时。含 token 策略与双模式测试 |
| `references/design-systems.md` | 阅读地图里任一系统的安装命令与官方文档链接 |
| `references/<前缀>-*.md` | Section 6 里点名的那条合规规则。前缀为 `access-` / `color-` / `cwv-` / `form-` / `layout-` / `resp-` / `typo-` / `anim-`。全量索引见 `references/README.md` |

**章节号沿用原锚点，因此不是连续的。** Section 2、8、10、11、12 已移入 `references/`，编号作为稳定标识保留，这样被移动文件内部的所有交叉引用仍然可解析。原 Section 7（旋钮定义）并入了 Section 1，其技术细节在 `references/knob-definitions.md`。Section 5 只把实现细节移入 `references/`，摘要与两条硬禁令保留在本文件。

**翻译约定：** 说明文字为中文；代码、类名、API 名、CSS 属性、规则 ID、文件名、阈值一律保留原文，不得翻译。改动规则时请连代码示例一起核对。

**canonical 规则：** 同一规则存在多份副本时，`references/` 文件为唯一权威；`SKILL.md` 的内联副本只写摘要，不得出现 references 里没有的数值或分档。改数值先改 references，再同步摘要。

**语言现状：** `SKILL.md` 与本目录下 11 个文件为中文（`README.md`、`ai-tells.md`、`design-directives.md`、`motion-skeletons.md`、`design-system-map.md`、`pattern-vocabulary.md`、`redesign-protocol.md`、`block-library.md`、`dark-mode-protocol.md`、`knob-definitions.md`、`tuning-verbs.md`）。`design-systems.md`（几乎全是 npm 命令与官方文档 URL）与 42 个 `access-` / `color-` / `cwv-` / `form-` / `layout-` / `resp-` / `typo-` / `anim-` 规则文件保留英文原文：那是以代码为主的标准细则（WCAG、web.dev），不参与手工调参，保留原文便于随时对照上游。

---

## 范围路由（第一步执行）

先判定表面类型，再只套用对应的层。判定结果要和 design read 写在同一行。

| 表面 | 识别信号 | 适用内容 |
|---|---|---|
| **营销** | landing page、官网、作品集、关于页、发布页、定价页，以及上述页面的改版 | 全部适用：Section 0 到 9、11、14 |
| **应用**（浏览器内的 Web 产品界面）| dashboard、admin panel、settings、表格密集视图、多步表单 / 向导、代码编辑器、实时协作界面 | **视觉设计交给**整套官方设计系统（Section 2.A 按品类指明用哪个），依据 Section 13。本 skill 在这里只贡献 **Section 3** 的约定 + **Section 6** 的合规基线。Section 4.7 的 hero 硬规则、4.8 的图片策略、4.9 的营销内容密度**不适用**，它们属于营销表面 |
| **混合** | 产品界面外面套着营销壳、文档站、既有落地页又有应用的工具 | 营销路由套营销层，应用路由套应用层。在 design read 里声明哪个是哪个 |

**这里的「应用」指 Web 产品界面，不是原生 App。** 指的是用 HTML、CSS、React、Tailwind 写的、跑在浏览器里、用 Core Web Vitals 衡量的 dashboard / 后台 / 向导。原生桌面与原生移动 App **完全不在本 skill 范围**，请直接用 Apple HIG 或 Material 及平台自身规范。完整清单见 Section 13。

这套路由存在的意义是拦住两类错误：

* 把营销硬规则（hero 必须占满首屏、eyebrow 配额、bento 单元格数、同一意图只能有一个 CTA）套到 dashboard 上。对那个表面而言，这是错的尺子。
* 营销页 hero 根本占不满首屏、或键盘根本走不通，却把 Section 6 每一条都打了勾。**Section 6 是地板，不能替代 Section 4。**

---
## 0. BRIEF 判读（动手之前先读懂场面）

在碰代码或调旋钮之前，**先推断用户到底想要什么**。多数 LLM 设计产出之所以差，是因为模型直接跳到一个默认审美，而不是先读懂场面。

### 0.A 先读这些信号
1. **页面类型**：landing（SaaS / 消费级 / 代理机构 / 活动）、作品集（开发者 / 设计师 / 创意工作室）、改版（保真还是推翻重做）、编辑型 / 博客。
2. **用户用的审美词**：「极简」「安静」「Linear 风」「Awwwards」「野兽派」「高端消费」「Apple 感」「俏皮」「严肃 B2B」「编辑感」「代理机构感」「玻璃感」「暗黑科技」。
3. **参考信号**：用户给的 URL、贴的截图、点名的产品、对标的品牌。
4. **受众**：B2B 采购评审 vs 有设计意识的消费者 vs 扫一眼作品集的招聘方。**受众决定审美，不是你的品味决定。**
5. **已有的品牌资产**：logo、色、字体、摄影。做改版时这些是起始材料，不是可选项（见 Section 11）。
6. **隐性约束**：可访问性优先的受众、公共部门、受监管行业、信任优先的电商、儿童产品。**这类约束优先级高于审美偏好。**

### 0.B 生成之前先输出一行 Design Read

动手写代码之前，先用一行说明：**「判读为：<页面类型>，面向 <受众>，<审美>语言，倾向 <设计系统或审美家族>。」**

示例：

- 「判读为：面向技术买家的 B2B SaaS 落地页，Linear 式极简语言，倾向 Tailwind utilities + Geist + 克制动效。」
- 「判读为：面向招聘方的个人设计师作品集，编辑 / 动态字体语言，倾向原生 CSS + 滚动驱动动画 + 自定义字体。」
- 「判读为：公共部门服务网站的改版，信任优先语言，倾向 GOV.UK Frontend 或 USWDS。」

**产出文案语言：默认中文。** brief 明确面向海外受众或要求其他语言时跟随 brief，并把语言写进 design read；未声明时一律按中文产出，4.7 的中文换算阈值随之生效。

### 0.C brief 模糊时，只问一个问题，不要猜

**只问一个**澄清问题，绝不要一次抛一堆。且只在 design read 真的会分叉时才问。例：「这个要更偏 Linear 那种干净，还是更偏 Awwwards 那种实验性？」

如果从上下文能自信推断，**就不要问**，直接声明 design read 然后往下做。

### 0.D 反默认纪律

不要默认以下东西：AI 紫渐变、深色网格上的居中 hero、三个等分 feature 卡片、到处糊玻璃拟态、满屏无限循环微动效、Inter + slate-900。**这些都是 LLM 的默认脸。** 依 design read 主动绕开它们。

---

## 1. 三个旋钮（核心配置）

design read 之后，设定三个旋钮。下文所有版面、动效、密度决定都由这三个值把关。

* **`DESIGN_VARIANCE: 8`** · 1 = 完全对称，10 = 艺术性混乱
* **`MOTION_INTENSITY: 6`** · 1 = 静态，10 = 电影感 / 物理感
* **`VISUAL_DENSITY: 4`** · 1 = 画廊 / 疏朗，10 = 驾驶舱 / 信息密集

**基线：`8 / 6 / 4`。** 除 design read 覆盖，否则用这组。**不要叫用户去改这个文件**，覆盖在对话里完成。

### 1.A 旋钮推断（design read → 旋钮值）
| 信号 | VARIANCE | MOTION | DENSITY |
|---|---|---|---|
| 「极简 / 干净 / 安静 / 编辑感 / Linear 风」 | 5-6 | 3-4 | 2-3 |
| 「高端消费 / Apple 感 / 奢华 / 品牌」 | 7-8 | 5-7 | 3-4 |
| 「俏皮 / 张扬 / Dribbble / Awwwards / 实验 / 代理机构」 | 9-10 | 8-10 | 3-4 |
| 「落地页 / 作品集 / 营销站（默认）」 | 7-9 | 6-8 | 3-5 |
| 「信任优先 / 公共部门 / 受监管 / 可访问性关键」 | 3-4 | 2-3 | 4-5 |
| 「改版 - 保真」 | 随现状 | +1 | 随现状 |
| 「改版 - 推翻重做」 | 视为新站，从基线 8/6/4 起步 | 同左 | 随现状 |

除上表标注「随现状」的格子外，推翻重做一律不参考现状的数值。

### 1.C 旋钮如何驱动产出
把这些值（或用户覆盖后的值）当成全局变量。本文档中所有交叉引用都指这些确切的变量名，**不要自造别名**如 `LAYOUT_VARIANCE` 或 `ANIM_LEVEL`。

### 1.D 旋钮定义（技术参考）

三档旋钮对应的具体写法——栅格轨道、缓动曲线、间距档位、移动端塌陷点——在 **`references/knob-definitions.md`**。设定旋钮值不需要读它，写对应样式时再读。其中一条对任何档位生效：**4-10 档的非对称版面在 < 768px 必须塌成严格单列**。

### 1.E 项目设计档案（跨会话持久）

判读与旋钮设定完成后，**设计档案**固定落 `product/design.md`（相对项目根，目录不存在则创建），无论项目是否走 atlas 工作流——atlas 项目这正是产物归属里项目级应然（产品长什么样）的位置，非 atlas 项目统一同一落点。不叫 `DESIGN.md`：那个名字在 atlas 体系是源包操作契约。

* 设计档案已存在 → **先读它并沿用**。除非本次 brief 明确要求改方向或用户口头覆盖，不重新判读、不默默改值；用户在对话里覆盖了旋钮，同步更新设计档案。
* 设计档案不存在 → 把本次判读结果写入设计档案（一次性 demo / 临时页除外）。只记事实不记过程，五行即可：

```markdown
# 设计档案
- 判读：<0.B 的那一行>
- 旋钮：DESIGN_VARIANCE <n> / MOTION_INTENSITY <n> / VISUAL_DENSITY <n>（<偏离基线的理由，无则写「基线」>）
- 设计系统 / 审美家族：<名称>
- 强调色与主题：<色值>；<单主题锁 / 双模式>
- 已有豁免：<prose 类豁免每条一行理由；detect 类写作 `detect:<rule-id> — <理由>` 并同步 `.impeccable/config.json`；无则写「无」>
```

后续会话、改版、调优动词（`references/tuning-verbs.md`）都以它为准。

**detect 类豁免必须双侧落盘**：档案里写 `detect:<rule-id> — <理由>`，同一 rule id 同步进项目根 `.impeccable/config.json` 的 `detector.ignoreRules`（没有该文件则创建）——只记档案 = 报警没真关，只关报警 = 没台账。atlas 项目由 `validate_design_exemptions` 机器对账，漂移即 FAIL；非 atlas 项目同形态，便于日后携带。

### 1.F Section 计划（≥ 5 个 section 的营销页先做这个再写代码）

旋钮设定后、写任何代码之前，先输出 section 计划表：每行一个 section——名称、内容一句话、**版面家族**（词汇见 `references/pattern-vocabulary.md`）、有无 eyebrow。

4.7 的机械规则必须**在计划期就满足**：8 个 section 至少 4 种版面家族、eyebrow ≤ `ceil(sectionCount / 3)`、无 3 个以上连续图文分栏、hero 占满首屏。计划不达标就改表，不要先写代码再到闸门前返工。闸门只验证一件事：代码是否按计划执行。

---

## 3. 默认架构与约定

除 design read 选了真实设计系统（见 `references/design-system-map.md`），以下为默认。

### 3.A 技术栈
* **框架**：React 或 Next.js，默认 Server Components（RSC）。
  * **RSC 安全**：全局状态只能在 Client Component 里用。Next.js 下把 provider 包进 `"use client"` 组件。
  * **交互隔离**：任何用 Motion、滚动监听、指针物理的组件**必须**是带 `'use client'` 的独立叶子节点。Server Component 只渲染静态版面。
* **样式**：**Tailwind v4**（默认）。仅当既有项目要求时用 v3。
  * v4 下不要在 `postcss.config.js` 里用 `tailwindcss` 插件，改用 `@tailwindcss/postcss` 或 Vite 插件。
* **动画**：**Motion**（原 Framer Motion）。从 `motion/react` 导入（`import { motion } from "motion/react"`）。`framer-motion` 包仍可用作兼容别名，新代码优先 `motion/react`。
* **字体**：一律用 `next/font`（Next.js）或自托管 `@font-face` + `font-display: swap`。**生产环境绝不通过 `<link>` 引 Google Fonts。**

### 3.B 状态
* 孤立 UI 用局部 `useState` / `useReducer`。
* 全局状态**仅**用于避免深层 prop 透传：Zustand、Jotai 或 React context。
* **绝不**用 `useState` 跟踪由用户输入驱动的连续值（鼠标位置、滚动进度、指针物理、磁性悬停）。用 Motion 的 `useMotionValue` / `useTransform` / `useScroll`。`useState` 每次变化都会重渲染整棵 React 树，移动端直接崩。

### 3.C 图标
* **允许的库（优先级顺序）**：`@phosphor-icons/react`、`hugeicons-react`、`@radix-ui/react-icons`、`@tabler/icons-react`。
* **不推荐**：`lucide-react`。仅当用户明确要求或项目已依赖时可用。
* **shadcn/ui 例外**：shadcn/ui 组件内部自带的 lucide 图标随组件保留，不必替换；自行新增的图标仍遵守本节。
* **绝不手写 SVG 图标。** 缺字形就再装一个库或用基本图元拼，不要从零画路径。
* **一个项目一个图标家族**，不要在同一组件树里混 Phosphor 和 Lucide。
* **全局统一 `strokeWidth`**（如 `1.5` 或 `2.0`）。

### 3.D Emoji 政策
默认在代码、标记和可见文案中不鼓励使用。符号一律换成图标库字形。**覆盖条件**：仅当用户明确要求俏皮 / 聊天感 / 社交原生调性时，且即便如此也要克制、有意图。

### 3.E 响应式与版面机制
* 统一断点（`sm 640`、`md 768`、`lg 1024`、`xl 1280`、`2xl 1536`）。
* 版面容器用 `max-w-[1400px] mx-auto` 或 `max-w-7xl`。
* **视口稳定性**：全高 hero **绝不**用 `h-screen`，一律 `min-h-[100dvh]`，避免移动端 iOS Safari 地址栏导致的跳动。
* **栅格优先于 flex 数学**：**绝不**用复杂的 flexbox 百分比计算（`w-[calc(33%-1rem)]`），一律用 CSS Grid（`grid grid-cols-1 md:grid-cols-3 gap-6`）。

### 3.F 依赖校验（强制）
导入任何第三方库之前，先查 `package.json`。包不存在就先输出安装命令。**绝不**假设某个库存在。

---

## 4. 硬规则（有一条不满足即为交付缺陷）

Section 4 的其余部分（字体池与衬线纪律 4.1、配色校准与调色板禁令 4.2、版面多样化 4.3、材质与圆角锁 4.4、交互状态与对比度检查 4.5、表单结构 4.6、图片策略 4.8、内容密度 4.9、引言 4.10）都在在 **`references/design-directives.md`**。写字体、配色、卡片、状态、图片或长列表之前先读它。下面这些必须在**不读文件的情况下**就位。

### 4.7 版面纪律（硬规则）

* **词数阈值针对英文。** 中文按 1 词 ≈ 2 字换算：副文案 ≤ 40 字，主 CTA ≤ 6 字，副段落 ≤ 50 字。行数限制与 eyebrow 计数和语言无关。
* **hero 必须占满首屏。** 桌面端标题最多 2 行，副文案最多 **20 个词** 且最多 3-4 行，CTA 不滚动就能看到。文案太长就砍文案或降字号，**绝不让 hero 溢出**。
* **hero 字号与图片尺寸一起规划。** 默认 `text-4xl md:text-5xl lg:text-6xl`；仅当标题 3-5 个词时才用 `text-6xl md:text-7xl`。**hero 标题到第 4 行，永远是字号错误，不是文案长度错误。**
* **hero 顶部留白上限**：桌面端最多 `pt-24`（约 6rem）。超过这个值视觉上就是版面 bug，不是留白。
* **hero 文本栈纪律，最多 4 个文本元素**：（1）eyebrow 或品牌条 或都不要；（2）标题；（3）副文案；（4）CTA（1 主 + 最多 1 次）。**hero 内禁止**：CTA 下方的小标语、信任微条、价格提示、feature 列表、social proof 头像行。这些一律下移到紧邻的 section。
* **「Used by / Trusted by」logo 墙放在 hero 下方，绝不放进 hero**，且**只放 logo**，不要在 logo 下方印行业或品类标签。
* **导航在桌面端必须一行排完**，`lg` 以下压缩标签或收进汉堡。**高度上限 80px，默认 64-72px。**
* **bento 栅格要有节奏，不能一边倒重复。** 交替全宽行、非对称瓦片、纵向断点。
* **bento 单元格数**：有几个内容就几个格子。中间或末尾出现空格即规划错误，**重排栅格，绝不贴空白瓦片**。
* **section 版面家族不得重复**：同一版面家族一页最多出现**一次**。8 个 section 至少要用 4 种不同家族。
* **zigzag 交替上限**：图文左右交替最多连续 2 个 section，第 3 个连续图文分栏即为预检失败。
* **eyebrow 克制，每 3 个 section 最多 1 个**（hero 算 1 个）。预检时机械计数：统计所有 section 标题上方的 `uppercase tracking` 小标签数量，若大于 `ceil(sectionCount / 3)` 即失败。**不要每个 section 标题上都有 eyebrow。**
* **分栏标题禁令**：「左边大标题 + 右边小解释段」不得用作 section 标题。真的需要就上下堆叠。
* **bento 背景多样性**：任何多格栅格里至少 2-3 个格子要有真实视觉变化（图片、品牌渐变、图案、色块）。全是白底文字卡片读起来就是无聊的 AI 默认。
* **移动端塌陷必须逐 section 显式声明** `< 768px` 的降级方案，写在同一个组件里。不要「Tailwind 会处理」。

### 4.11 页面主题锁

**整页只有一个主题，section 不得反转。** 深色 section 中间夹一个浅色 section 即为破损。同族内的背景色差可以（`bg-zinc-950` 紧挨 `bg-zinc-900`），但深色页中间翻成 `bg-amber-50` 不行。用带主题的设计系统（Radix Themes、shadcn/ui `<Theme>`）时，在页面根节点**只设一次**主题，不要让各 section 各自覆盖。

**配色 / 圆角 / CTA / 交互状态的一致性锁（4.2、4.4、4.5）**：一个强调色、一套圆角体系、CTA 一行放下且一个意图一个标签、表单控件对背景满足 WCAG AA、loading / 空 / 错误状态齐全——这些锁的完整定义以 `references/design-directives.md` 为 canonical，不在此重复数值；预检闸门的「各锁成立」一项负责逐条勾验。

---

## 5. 动效（实现细节在 references）

可用的滚动动效骨架，含 sticky-stack、horizontal-pan、scroll-reveal stagger，都在 **`references/motion-skeletons.md`**。写滚动编排之前先读它。以下两条必须不读文件就位：

* **`window.addEventListener('scroll', ...)` 是禁令。** 它每帧都跑，极易掉帧。改用 Motion 的 `useScroll()`、GSAP `ScrollTrigger`、`IntersectionObserver`，或 CSS 滚动驱动动画（`animation-timeline`）。同样禁止在 React state 里存 `window.scrollY`，以及用 `requestAnimationFrame` 循环碰 state。
* **动效必须有理由。** 加任何动画之前先回答「它传达了什么」。成立的答案：层级、叙事、反馈、状态迁移。不成立的答案：「看着酷」。一句话说不清就删掉。**marquee 一页最多一个。**

---
## 6. 合规基线（可访问性、性能、动效、暗色模式）

这是地板的**唯一规范副本**。Section 4 说的是设计意图，这一节说的是意图底下必须成立的东西。每条规则都点出它在 `references/` 里对应的文件，那里有具体数值、错误/正确代码对照和出处。**准备写那段代码时再打开那个文件。6.K 记录了「两份源 skill 打架的地方」的裁决结果，覆盖任何东西之前先读它。**

### 6.A 动画性能
* 只动 `transform` 和 `opacity`。**绝不**动 `top`、`left`、`width`、`height`。
* `will-change` 克制使用，只给真正会动的元素，**绝不**全局 `will-change: *`。
* 细则：`references/anim-gpu-properties.md`、`references/anim-will-change.md`

### 6.B 降低动效（强制）
* **任何 `MOTION_INTENSITY > 3` 的动效都必须尊重 `prefers-reduced-motion`。** 这条没有商量余地。
* Motion 下用 `useReducedMotion()` 降级为静态。CSS 下用 `@media (prefers-reduced-motion: no-preference)` 包裹，或在 `reduce` 覆盖块里关掉。
* 无限循环、视差、滚动劫持、磁性物理，在降低动效下**必须**塌成静态或瞬时。

### 6.C 动效时长与缓动

| 动作 | 时长 |
|---|---|
| 悬停 / 聚焦状态 | 100-150ms |
| 按钮反馈 | 100-200ms |
| 下拉 / 手风琴 / 展开 | 200-300ms |
| 弹层 / 对话框 | 200-400ms |
| 页面转场 | 300-500ms |
| 滚动驱动编排 | **由滚动距离决定，无 ms 上限** |

* 微交互遵守上表，**表内任何一项不超过 500ms**。滚动驱动的工作（GSAP ScrollTrigger、CSS `animation-timeline`、pin 住的 section、横向平移）由滚动距离驱动，**不受上表约束，但绝不受 6.B 豁免**。
* **缓动**：主曲线 `cubic-bezier(0.16, 1, 0.3, 1)`（expo-out）。弹层可用 `cubic-bezier(0.32, 0.72, 0, 1)`。Material 的 `cubic-bezier(0.4, 0, 0.2, 1)` 仅当 brief 建立在自带 motion token 的设计系统上时使用。**一页一条主曲线。移动绝不使用 `linear`。**
* 细则：`references/anim-duration-easing.md`、`references/anim-reduced-motion.md`

### 6.D 可访问性机制（全部强制）

* **焦点可见**：每个可交互元素都要有，至少 2px，对相邻色至少 3:1。`outline: none` 且无替代方案即为预检失败。`references/access-focus-indicators.md`
* **语义 HTML 优先于 ARIA**：动作用 `<button>`，导航用 `<a href>`，结构用 `<nav>` / `<main>` / `<header>` / `<footer>`，一页一个 `<h1>`。`references/access-semantic-html.md`
* **标题层级不得跳级**（`h2` 之后接 `h4` 非法）。视觉字号归 CSS，元素层级归文档结构。`references/access-heading-hierarchy.md`
* **键盘**：每个可交互元素都能到达并操作，Tab 顺序与视觉顺序一致，无键盘陷阱，弹层打开时焦点移入、关闭时归还。`references/access-keyboard-navigation.md`
* **可访问名称**：纯图标控件必须有 `aria-label`，裸露的 `<button><svg/></button>` 不合格。装饰性图片用 `alt=""`。有意义的 alt 文字控制在 **125 字符以内**。`references/access-aria-labels.md`、`references/access-alt-text.md`
* **绝不只靠颜色**：错误 / 成功 / 必填 / 选中状态，颜色必须搭配文字、图标或形状。`references/color-not-only-indicator.md`
* **目标尺寸**：最小 **24x24** CSS px（WCAG 2.2 AA），**期望 44x44**（AAA / iOS HIG，Material 要求 48x48），相邻目标间距至少 8px。正文内嵌链接豁免。**这条地板优先于 `VISUAL_DENSITY`**，密度管的是一个视口里放多少信息，从不管命中区多大。`references/access-target-size.md`、`references/resp-touch-targets.md`
* **视口 meta** 用 `initial-scale=1`。**绝不**用 `maximum-scale=1` 或 `user-scalable=no`，那会挡掉低视力用户依赖的缩放。`references/resp-viewport-meta.md`
* **对比度**：WCAG AA 起步，正文 4.5:1，大字（18px+ / 14px+ 粗体）与 UI 边界 3:1。hero 文案目标 AAA。宁可提高对比度，也不要为了「柔和」而降低。`references/color-contrast-ratio.md`

### 6.E 表单
* label 放在输入框**上方**，用 `for`/`id` 绑定（`references/form-labels-above.md`）。辅助文字写进标记。错误文字放**下方**。块间距 `gap-2`。**绝不用 placeholder 当 label。**
* 校验时机：blur 时校验**和**提交时校验。**空必填项在 blur 时不校验。用户正在输入时绝不报错。** `references/form-inline-validation.md`
* 错误文案要可操作、正面表述（「请输入工作邮箱」，而不是「此项不得为空」）。`references/form-error-messages.md`
* 用对的 `type` / `inputmode`，以及对的 `autocomplete` token，让浏览器和密码管理器能自动填充。`references/form-input-types.md`、`references/form-autocomplete.md`

### 6.F Core Web Vitals 与交付
* **LCP < 2.5s**：hero 图用 `next/image priority` 或预加载，**绝不延迟加载**。`references/cwv-optimize-lcp.md`、`references/cwv-lazy-load-offscreen.md`
* **INP < 200ms**：重活移出主线程。`references/cwv-improve-inp.md`
* **CLS < 0.1**：图片显式给 `width`/`height` 或 `aspect-ratio`，字体度量对齐，不late 注入横幅。`references/cwv-minimize-cls.md`
* 交付：`srcset` + `sizes`，WebP/AVIF 优于 JPEG，内联关键 CSS。`references/cwv-responsive-images.md`、`references/cwv-critical-css.md`
* 字体：`next/font` 或自托管 `@font-face` 配 `font-display: swap`；预加载关键字重时**必须带 `crossorigin`**（同源也要）。`references/typo-font-display.md`、`references/typo-preload-fonts.md`
* 正文流体字号用 `clamp()`，下限 16px、上限 20px。`references/resp-fluid-typography.md`
* 行高与行宽见 6.K。细则：`references/typo-line-height.md`、`references/typo-readable-line-length.md`
* **交付前跑一次 Lighthouse。**
* **交付前跑机器检查：`npx impeccable detect src/`（或对本地预览 URL 跑，用渲染后布局查对比度、溢出、触控目标）。exit 2 的 findings 必须先处理或写明豁免理由；零安装、零 token，不依赖模型自查。**

### 6.G 暗色模式
* **任何面向消费者的页面都强制**。一开始就同时设计两种模式，未经明确指示不得只做单模式。尊重 `prefers-color-scheme`，默认跟随系统，除非品牌坚持。
* **不用纯 `#000000`，不用纯 `#ffffff`**，只用近黑与近白。两种模式都要维持层级对等与品牌还原，并遵守 4.11 的整页主题锁。
* 完整协议：`references/dark-mode-protocol.md`。token：`references/color-semantic-palette.md`、`references/color-dark-mode.md`

### 6.H 响应式
* 移动优先，用 `min-width` 查询，断点见 3.E。`references/resp-mobile-first.md`
* 非对称版面（variance 4-10）在 768px 以下塌成严格单列，见 `references/knob-definitions.md`。
* **容器查询**用于「必须在任意容器宽度下成立」的组件，而不只看视口宽度。`references/resp-container-queries.md`
* `min-h-[100dvh]`，绝不用 `h-screen`。
* 版面层级、留白、阅读路径、邻近性等通用版面规则：`references/layout-*.md`（`layout-visual-hierarchy`、`layout-whitespace`、`layout-f-pattern`、`layout-grid-system`、`layout-single-cta`、`layout-proximity-grouping`）

### 6.I DOM 开销
* 颗粒 / 噪点滤镜只允许加在固定的 `pointer-events-none` 伪元素上，**绝不加在滚动容器上**，那会导致持续 GPU 重绘，移动端帧率直接崩。
* 注意包体积。Motion 不小，Three.js 很大。首屏之外的一律延迟加载。

### 6.J z-index
**绝不**乱撒 `z-50` / `z-10`。z-index 只用于系统性层级（sticky 导航、弹层、遮罩、颗粒），并把层级表写进项目常量文件。

### 6.K 两份源 skill 打架处的裁决（已定，不要逐项目再议）

* **Display 行高**。**绝不用裸 `leading-none`。** 单行 display 最低 `leading-[1.05]`。两行及以上，或斜体词里含 `y g j p q` 降部字母：`leading-[1.1]` 并留 `pb-1`。紧度靠 `tracking-tighter`，不靠零行高。
* **正文行高与行宽**。无冲突。canonical 分档只在 `references/typo-line-height.md`（40-60ch：1.5-1.6；60-80ch：1.6-1.8）。Section 4.1 的默认（`leading-relaxed` + `max-w-[65ch]`）落在 60-80ch 档内。
* **动效时长**。按类型切开：时基过渡遵守 6.C 且不超过 500ms；距离基的滚动编排不受表约束，但**绝不豁免 6.B**。移动用 `linear` 无论如何都禁止。
* **字体选择，按表面切而不是按元素切。** *营销表面*：品牌字覆盖导航和按钮，身份感就是目的，FOUT 靠 `font-display: swap` + 预加载关键字重解决。*应用表面*：品牌字与衬线字只留给标题和品牌时刻，导航、按钮、label、输入框、表格用系统字栈，因为控件上「即时渲染」优先于品牌字体。`references/typo-system-font-stack.md`
* **命中区 vs 密度**。地板赢。DENSITY 9 的驾驶舱照样是 44px 的导航和图标按钮、间距 8px。见 6.D。
* **行宽与栅格**。无冲突。正文 65ch，标题可以到 85ch。高 variance 下的非对称用栅格内的分数轨道表达（`grid-template-columns: 2fr 1fr 1fr`），**绝不用魔法宽度**，两边都禁任意百分比并要求 CSS Grid。
* **CTA 数量与暗色模式**。无冲突。一个主操作、一个意图一个标签；两种模式都支持、整页锁定一个主题。

---

## 9. AI 味（禁止模式）

这些是模型想「看起来像设计过」时会自动掉进去的签名。除 brief 明确要求，一律硬禁。**完整带注解的禁令清单（含 9.F 摘要背后的全部条目）在 `references/ai-tells.md`，产出任何版面之前先读它。**

### 9.A 视觉与 CSS
不要霓虹 / 外发光。不要纯黑。不要过饱和强调色。大标题不要渐变文字。不要自定义鼠标指针。

### 9.B 字体
默认避开 `Inter`（见 4.1）。不要只靠巨大 H1 喊叫，用字重和颜色建立层级。衬线用于编辑 / 奢华 / 出版，**不用于产品界面**。

### 9.C 版面与间距
padding 与 margin 在数学上一致，不留位置尴尬的漂浮元素。**禁止三等分 feature 卡片。**

### 9.D 内容与数据
不要通用人名（「John Doe」「Sarah Chan」），不要通用头像，不要假精确数字（`99.99%`、`50%`），不要创业套壳品牌名（「Acme」「Nexus」「SmartFlow」），不要填充动词（「Elevate」「Seamless」「Unleash」「Next-Gen」）。

### 9.E 外部资源与组件
不要手写 SVG 图标，只用 Phosphor / HugeIcons / Radix / Tabler。不要 div 拼的假截图。不要挂掉的 Unsplash 链接。`shadcn/ui` 只能用改造过的状态，不能是默认样式。

### 9.F 生产测试里的高频 AI 味
一律禁止。完整枚举（hero 里的版本号、`Scroll` 滚动提示、装饰性状态圆点、middle-dot 滥用、「Quietly in use at」式措辞等几十条，每条带注解和替代方案）以 **`references/ai-tells.md`** 为 canonical——阅读地图已要求产出任何版面之前先读它，此处不再维护第二份枚举。

### 9.G 破折号禁令（最高频的 AI 味）

**英文输出里，em-dash `—` 完全禁止。** 没有「限量使用」的余地，没有「自然语言频率」的余地，没有「正文里可以」的余地。标题、eyebrow、pills、按钮文字、图注、导航项、正文、引言、署名、alt 文字，全部禁止。en-dash `–` 用作分隔符同样禁止。日期与数字区间用普通连字符（`2018-2026`、`€40-80k`）。

**中文输出里的破折号「——」** 是规范标点，但同样被 LLM 当成修辞拐杖滥用。规则：不得出现在标题、eyebrow、按钮、图注中；正文里只用于真实的解释或插入语，且整页不超过一处。不用它做停顿、强调或列举。

允许出现的横线字符只有：普通连字符 `-`（复合词、区间、标记里的分隔线）与数学负号。

**豁免（仅两条）**：① brief 明确要求破折号风格时，遵循 brief 并在 design read 里声明；② 改版 - 保真模式下，原样保留的存量品牌文案（slogan、既有正文）不算「产出文案」；新增文案仍受本条约束。

**产出中只要出现一个不该有的 `—` 或 `——`，预检即失败，必须重写。**

---

## 13. 边界与移交

范围路由（本文开头）负责把表面分流到营销层或应用层。这一节只裁决一件事：**哪些表面的视觉设计要移交出去，以及移交之后什么仍然留下。**

**视觉移交**（路由表里的「应用」表面）——视觉设计交给对应的官方系统，Section 3 的约定与 Section 6 的合规基线照常生效：

* dashboard / admin panel / 密集产品界面 → Section 2.A 里的 Fluent、Carbon、Atlassian 或 Polaris。
* 数据表格 → TanStack Table 或 AG Grid。
* 多步表单 / 向导 → 表单专用范式。6.E 的表单合规照常生效。
* 代码编辑器 → Monaco / CodeMirror 及其官方皮肤。
* 实时协作界面（在线状态、光标、OT 感知）→ 协作专用方案。

**完全出范围**——本 skill 什么都不贡献：

* 原生桌面与原生移动 App → 直接用 Apple HIG / Material 及平台自身规范。

遇到视觉移交的表面，**明确说出来**，指出用哪套系统，然后照常套用 Section 6。可访问性、焦点、键盘操作、目标尺寸、表单校验体验和性能指标，不因为设计系统接管了视觉就变成可选项。**设计语言交出去，地板留下。**

---

## 14. 预检闸门

输出代码之前，每一格都要过。**这不是可选项，也不是走过场。任何一格无法诚实打勾，页面就没做完。** 每格对应的细则在它引用的 section 或文件里。

**按范围路由取子集**：应用表面跳过【版面硬规则】整块，以及【品味】块中带 (4.8) / (4.9) 标记的项；混合表面把营销部分和应用部分分开各过一遍。其余块对一切表面生效。

**输入已声明**
- [ ] design read 已用一行写出（0.B），旋钮值由它推断且给出了理由，不是默默用了基线（Section 1）
- [ ] 已按范围路由判定表面类型；若是应用表面，视觉设计已交给官方设计系统，同时 Section 6 仍然生效
- [ ] 设计系统已从 Section 2 选定，一个项目一套，没有混用；若走的是一种审美而非系统，已诚实标注为审美（`references/design-system-map.md`）
- [ ] 若为改版，已识别模式并完成审计（`references/redesign-protocol.md`）
- [ ] 设计档案（`product/design.md`，1.E）已读取或已写入；已有档案时本次判读与之一致，或用户明确要求变更
- [ ] ≥ 5 section 的营销页已输出 section 计划（1.F），4.7 机械规则在计划上即满足

**品味**
- [ ] **新增文案全页零 `—` / `——`**（标题、eyebrow、pills、正文、引言、署名、图注、按钮、alt 文字；9.G 的两条豁免须已在 design read 里声明）（9.G）
- [ ] 无 Section 9 的 AI 味；产出版面之前已读过 `references/ai-tells.md` 的完整禁令清单
- [ ] 文案自查已完成：每个可见字符串都重读过，无语法破损、无 AI 幻觉句式、无无依据的假精确规格
- [ ] 使用了真实图片（优先生成工具，其次真实摄影，再其次标注清楚的占位位），没有 div 拼的假截图、没有手绘装饰 SVG、没有纯文字极简（4.8）
- [ ] 图标只来自允许的库，一个项目一个家族，`strokeWidth` 已统一
- [ ] 超过 5 项的长列表用了对的组件而不是默认 `<ul>` + `divide-y`；规格表与数据倾泻已重做（4.9）
- [ ] 凡抬升层级不表达真实等级的卡片都已去掉，改用间距或分隔线

**版面硬规则（4.7，仅营销表面）**
- [ ] hero 占满首屏：标题 ≤ 2 行、副文案 ≤ 20 词且 ≤ 4 行、CTA 不滚动可见、顶部留白 ≤ `pt-24`、文本元素 ≤ 4 个，hero 内无小标语 / 信任条 / 价格提示
- [ ] 「Used by / Trusted by」logo 墙位于 hero **下方**，用真实 SVG logo 或生成的标记，logo 下方不印品类标签
- [ ] 桌面端导航一行排完、高度 ≤ 80px；移动端塌陷逐 section 显式声明（`h-screen` 禁令在 6.H，对所有表面生效）
- [ ] bento 单元格数与内容一致、无空格，且至少 2-3 格有真实视觉变化
- [ ] eyebrow 数量 ≤ `ceil(sectionCount / 3)`（hero 计 1），是机械数出来的，不是凭眼估的
- [ ] 无 3 个以上连续图文分栏；8 个 section 至少 4 种版面家族；section 标题未使用分栏标题范式
- [ ] 各锁成立：整页一个主题（4.11）、一个强调色、一套圆角、一个意图一个 CTA 标签、CTA 不换行

**可访问性（6.D）**
- [ ] 每个可交互元素焦点可见（≥ 2px，≥ 3:1），无 `outline: none` 且无替代
- [ ] 语义 HTML 与标题层级正确：不跳级、一个 `h1`、动作用真 `<button>`、导航用真 `<a href>`、纯图标控件有可访问名称、装饰图片 `alt=""`、alt 文字短于 125 字符
- [ ] 键盘全程可操作：Tab 顺序合理、无陷阱、弹层关闭后焦点归还
- [ ] 错误 / 成功 / 必填 / 选中状态均不只靠颜色
- [ ] 目标尺寸在任意密度下达标：最小 24x24、期望 44x44、间距 ≥ 8px（优先于 `VISUAL_DENSITY`）
- [ ] 对比度达标：按钮、表单控件、placeholder、focus ring、辅助与错误文字对背景均为 WCAG AA；hero 文案力争 AAA
- [ ] 视口 meta 允许缩放，无 `maximum-scale=1`、无 `user-scalable=no`
- [ ] 表单：label 在上方、`for`/`id` 绑定、无 placeholder 当 label、blur 与提交双校验（不在输入中、不在空必填项上报错）、错误文案可操作、`type` / `inputmode` / `autocomplete` 正确

**性能（6.F）**
- [ ] 交付检查：`srcset` + `sizes`、WebP 或 AVIF、LCP 图未延迟加载、关键 CSS 已内联、关键字体已带 `crossorigin` 预加载
- [ ] Core Web Vitals 有望达标：LCP < 2.5s、INP < 200ms、CLS < 0.1，每张图与字体都预留了空间
- [ ] 宣布完成之前**已跑过 Lighthouse**
- [ ] 宣布完成之前**已跑过 `npx impeccable detect`**（源码目录或渲染 URL），exit 2 的 findings 已处理或有明确豁免

**动效（6.A-6.C）**
- [ ] 只动 `transform` 与 `opacity`；`will-change` 克制使用
- [ ] 每个动画都能用一句话说明理由（层级 / 叙事 / 反馈 / 状态迁移）；marquee 一页最多一次；声称有的动效真的做出来了
- [ ] 时长落在 6.C 表内（无一项超过 500ms）或确属滚动驱动；一页一条主缓动曲线；移动未用 `linear`
- [ ] 所有 `MOTION_INTENSITY > 3` 的动效都尊重降低动效设置，并降级为静态
- [ ] 无 `window.addEventListener('scroll')`、无在 state 里存 `window.scrollY`、无碰 state 的 `requestAnimationFrame` 循环；滚动相关用 `useScroll()` / ScrollTrigger / IntersectionObserver / CSS 滚动驱动；骨架照 `references/motion-skeletons.md` 执行
- [ ] 动效隔离在带 `'use client'` 的叶子组件里并做了 memo；`useEffect` 里的动画有严格清理

**状态与其他**
- [ ] 暗色 token 已定义并在两种模式下都测过；无纯 `#000000` / `#ffffff`
- [ ] 空状态、loading、错误状态齐全；有 `:active` 触感反馈
- [ ] 6.K 的裁决已遵守：无裸 `leading-none`、字体按表面切、无随意 z-index
- [ ] 内容密度合理：副段落默认 ≤ 25 词、引言 ≤ 3 行且署名干净、营销页无 20 行数据表
- [ ] 宣布完成之前**已目检渲染结果**：用浏览器对桌面（≥ 1280px）与移动（390px）两个 viewport 截图，逐项核对 hero 高度、版面塌陷、暗色模式、文字溢出；至少已对渲染 URL 跑过一次 `npx impeccable detect <预览 URL>`
