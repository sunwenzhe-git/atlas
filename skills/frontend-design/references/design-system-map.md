# 设计系统选型地图

_原 SKILL.md Section 2 逐字移入。_

拿到 design read（Section 0）和旋钮（Section 1）之后，选对地基。**有官方包的东西，不要自己发明 CSS。** **不要把一种审美潮流伪装成官方系统。**

### 2.A 什么时候该上真实的设计系统（用官方包）
| brief 读起来像… | 用 | 为什么 |
|---|---|---|
| 微软 / 企业级 SaaS / dashboard | `@fluentui/react-components` 或 `@fluentui/web-components` | 官方 Fluent UI，微软 token，可访问性已经做好了 |
| Google 味 UI、Material 风格产品 | `@material/web` + Material 3 token | 官方，可用 Material Theming 换肤 |
| IBM 式 B2B / 企业分析 | `@carbon/react` + `@carbon/styles` | 官方 Carbon，数据密度范式成熟 |
| Shopify 应用界面 | `polaris.js` web components / Polaris React | Shopify 后台强制要求 |
| Atlassian / Jira 式产品 | `@atlaskit/*` + `@atlaskit/tokens` | 官方 Atlassian DS |
| GitHub 式开发工具 / 社区页 | `@primer/css` 或 `@primer/react-brand` | 官方 Primer；营销页用 Brand 变体 |
| 英国公共部门服务 | `govuk-frontend` | 法规 / 合规层面就要求用它 |
| 美国公共部门 / 信任优先 | `uswds` | 同上 |
| 快速本地商户 / 代理机构 MVP | Bootstrap 5.3 | 无聊、快、能用 |
| 现代可访问的 React 地基 | `@radix-ui/themes` | 原语 + 打磨过的主题 |
| 组件归你所有的新式 SaaS | shadcn/ui（`npx shadcn@latest add ...`）| 代码在你手上，好改造；**绝不交付默认样式** |
| Tailwind 的现代 SaaS / AI 营销站 | Tailwind v4 工具类 + `dark:` 变体 | 独立开发者与小团队的默认解 |

**诚实规则**：如果 brief 读起来是上面某套系统，就装**官方包**用它。不要手搓它的 CSS。不要引了人家的 token 再覆盖掉 90%。

**一个项目一套系统。** 不要在同一棵组件树里混 Fluent React 和 Carbon。不要把 shadcn/ui 组件塞进 Material 3 的应用里。

**上表中每套系统的安装命令与官方文档链接**在 `design-systems.md`。安装之前先读那个文件，**不要凭记忆手搓某套系统的 CSS**。

### 2.B 当 brief 是一种审美，而不是一套系统
下面这些方向**没有单一官方包**。用原生 CSS + Tailwind + 一个维护中的组件库来搭。在代码注释里诚实说明：哪些是借鉴来的灵感，哪些是官方材料。

| 审美 | 诚实的实现方式 |
|---|---|
| 玻璃拟态 / 「磨砂玻璃」 | `backdrop-filter`、层叠描边、高光叠层。为 `prefers-reduced-transparency` 提供实心填充降级。 |
| Bento（Apple 式瓦片栅格）| 尺寸混搭的 CSS Grid。没有哪个库独占它。 |
| 野兽派 | 原生 CSS、等宽字体、生硬描边。无库。 |
| 编辑 / 杂志 | 衬线字、非对称栅格、大量留白。无库。 |
| 暗黑科技 / 黑客 | 等宽 + 强调霓虹、终端母题。无库。 |
| 极光 / mesh 渐变 | SVG 或层叠径向渐变。无库。 |
| 动态字体 | 原生 CSS 动画、滚动驱动动画、劫持场景用 GSAP。无库。 |
| **Apple Liquid Glass** | Apple 只为 Apple 平台记录过它。**不存在官方的 `liquid-glass.css`。** Web 上的实现都是用 `backdrop-filter` + 层叠描边 + 高光做的**近似**。必须明确标注这是近似。 |
