# 区块库契约

_原 SKILL.md Section 12 逐字移入。_

范式词汇表（Section 10）负责**命名**，区块库负责用真实的 props、真实的动效规格和真实代码把它们**实现出来**。

**状态**：schema 已定于此。区块将逐步补齐。**不按这个 schema 走，就不许自己造新区块。**

### 12.A 文件位置
```
blocks/
  hero/
    asymmetric-split.md
    editorial-manifesto.md
    kinetic-type.md
    ...
  feature/
    bento-grid.md
    sticky-scroll-stack.md
    zig-zag.md
    ...
  social-proof/
  pricing/
  cta/
  footer/
  navigation/
  portfolio/
  transition/
```
路径相对于本 skill 根目录（即 `SKILL.md` 所在目录）。

### 12.B 必备 frontmatter
```yaml
name: asymmetric-split-hero
category: hero
dial_compatibility:
  variance: [6, 10]
  motion: [3, 10]
  density: [2, 5]
when_to_use: "Landing pages with one strong asset and one strong message. Default hero for SaaS, agency, premium consumer."
not_for: "Editorial / manifesto launches where the message IS the design."
stack: ["react", "next", "tailwind", "motion"]
```
（`when_to_use` / `not_for` 用英文写，因为它们是给模型做路由匹配用的判断语。）

### 12.C 必备正文小节
1. **视觉草图**：简短 ASCII 图或版面描述。
2. **Props API**：组件的接口。
3. **代码草图**：最小可运行实现（默认 Server Component，动效部分做 Client 孤岛）。
4. **移动端降级**：`< 768px` 的显式塌陷规则。
5. **动效变体**：`MOTION_INTENSITY` 每一档（1-3、4-7、8-10）一个变体，并显式给出降低动效时的降级。
6. **暗色模式说明**：本区块专属的 token 策略。
7. **反模式**：这个区块常见做坏的方式。
8. **参考**：指向生产环境里的真实案例。

### 12.D 区块库纪律
* **一个文件一个区块。** 不许一个文件塞多个区块。
* **每个区块必须能独立工作**（丢进页面就能渲染）。
* **每个区块必须通过预检闸门**（Section 14）。
* 依赖 Section 2.A 某套设计系统的区块，放在 `blocks/<category>/<name>--<system>.md`（例如 `feature/bento-grid--material.md`）。
