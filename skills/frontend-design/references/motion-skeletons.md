# 动效：可用骨架与禁止写法

_原 SKILL.md Section 5 的实现细节移入于此；摘要与两条硬禁令仍保留在 SKILL.md。_

**这些是工具，不是默认。** 只在 design read 需要时使用，**没有一条会自动触发**。

* **Liquid Glass / 玻璃拟态**：适合高端消费、Apple 邻近、奢华品牌或媒体叠层调性。不适合 dashboard、公共部门或「无聊的 B2B」。用它时不要停在 `backdrop-blur`：加 1px 内描边（`border-white/10`）和轻微内阴影（`shadow-[inset_0_1px_0_rgba(255,255,255,0.1)]`）来做出实体边缘折射。为 `prefers-reduced-transparency` 提供实心填充降级。
* **磁性微物理**：`MOTION_INTENSITY > 5` **且** brief 读起来是高端 / 俏皮 / 代理机构时使用。**只能**用 Motion 的 `useMotionValue` / `useTransform` 在 React 渲染周期之外实现。**不要用 `useState`**，见 Section 3.B。
* **持续微交互**（Pulse、Typewriter、Float、Shimmer、Carousel）：`MOTION_INTENSITY > 5` **且**该 section 真的能从动效获益时使用（状态指示、实时流、AI 感）。**不是每张卡片都需要无限循环。** section 是信息性的就让它静止。用弹簧物理（`type: "spring", stiffness: 100, damping: 20`），不要线性缓动。
* **「声称有动效，就得真有动效」。** `MOTION_INTENSITY > 4` 时，页面必须真的在动：至少要有 hero 的入场过渡、关键 section 的滚动揭示、CTA 的悬停物理。声称 `MOTION_INTENSITY: 7` 却是静态页面，就是坏掉的。反过来，如果当前范围内做不出能用的动效，**把旋钮降到 3，交付一个干净的静态页面**。绝不要做一半坏掉的动效（被截断的 ScrollTrigger、跳变的入场、缺失的清理）。
* **动效必须有理由（强制）。** 加任何动画之前先问：「这个动画传达了什么？」成立的答案：**层级**（把注意力引到对的地方）、**叙事**（按与叙事匹配的顺序揭示内容）、**反馈**（回应用户操作）、**状态迁移**（表示某物发生了变化）。不成立的答案：「看着酷」。**因为 GSAP 可用就到处用 GSAP 是业余做法。** 每个 ScrollTrigger、每个跑马灯、每个钉住的 section 都需要一个理由。一句话说不清理由，就删掉这个动画。
* **跑马灯一页最多一个（强制）。** 横向滚动文字跑马灯（「logo 无尽滚动」「宣言横向滚动」「动态词条」）每页最多出现**一次**。同一页出现两个及以上，读起来就是偷懒的填充。挑出真正需要跑马灯的那一个 section，其余换别的版面。
* **GSAP sticky-stack 范式（用到滚动堆叠时）。** 「随滚动堆叠的卡片」必须是**真的** sticky-stack，不是顺序揭示列表。规范代码见下面 5.A。**常见失败**：触发点在滚动中途才响应，而不是在视口顶部就把卡片钉住。**修法**：用 `start: "top top"`，不要用 `start: "top center"` 或 `"top 80%"`。
* **GSAP horizontal-pan 范式（用到横向滚动劫持时）。** 规范骨架见下面 5.B。**常见失败**：动画在 section 被钉住之前就开始，于是用户只看到半张幻灯片。**同样的修法**：`start: "top top"`，钉住外层 wrapper，scrub 内层 track。

### 5.A Sticky-Stack 规范骨架

```tsx
"use client";
import { useRef, useEffect } from "react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useReducedMotion } from "motion/react";

gsap.registerPlugin(ScrollTrigger);

export function StickyStack({ cards }: { cards: React.ReactNode[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();

  useEffect(() => {
    if (reduce || !ref.current) return;
    const ctx = gsap.context(() => {
      const cardEls = gsap.utils.toArray<HTMLElement>(".stack-card");
      cardEls.forEach((card, i) => {
        if (i === cardEls.length - 1) return;
        ScrollTrigger.create({
          trigger: card,
          start: "top top",                              // 在视口顶部钉住
          endTrigger: cardEls[cardEls.length - 1],
          end: "top top",
          pin: true,
          pinSpacing: false,
        });
        gsap.to(card, {
          scale: 0.92,
          opacity: 0.55,
          ease: "none",
          scrollTrigger: {
            trigger: cardEls[i + 1],
            start: "top bottom",
            end: "top top",
            scrub: true,
          },
        });
      });
    }, ref);
    return () => ctx.revert();
  }, [reduce]);

  return (
    <div ref={ref} className="relative">
      {cards.map((card, i) => (
        <div
          key={i}
          className="stack-card sticky top-0 min-h-[100dvh] flex items-center justify-center"
        >
          {card}
        </div>
      ))}
    </div>
  );
}
```

**关键点**：`start: "top top"`、`pin: true`、除最后一张外每张卡都被钉住、缩放 / 透明度变换由**下一张**卡的滚动触发器驱动（所以上一张在下一张到来时缩小）。

### 5.B Horizontal-Pan 规范骨架

```tsx
"use client";
import { useRef, useEffect } from "react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useReducedMotion } from "motion/react";

gsap.registerPlugin(ScrollTrigger);

export function HorizontalPan({ children }: { children: React.ReactNode }) {
  const wrap = useRef<HTMLDivElement>(null);
  const track = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();

  useEffect(() => {
    if (reduce || !wrap.current || !track.current) return;
    const ctx = gsap.context(() => {
      const distance = track.current!.scrollWidth - window.innerWidth;
      gsap.to(track.current, {
        x: -distance,
        ease: "none",
        scrollTrigger: {
          trigger: wrap.current,
          start: "top top",                              // section 顶边碰到视口顶部时开始钉住
          end: () => `+=${distance}`,                    // 滚动距离 = track 宽度减视口宽度
          pin: true,
          scrub: 1,
          invalidateOnRefresh: true,
        },
      });
    }, wrap);
    return () => ctx.revert();
  }, [reduce]);

  return (
    <section ref={wrap} className="relative overflow-hidden">
      <div ref={track} className="flex h-[100dvh] items-center">
        {children}
      </div>
    </section>
  );
}
```

**关键点**：`start: "top top"`、`pin: true`、`end: "+=${distance}"`（滚动长度 = 需要横向走过的距离）、`scrub: 1`。外层 wrapper 被钉住，内层 track 随用户纵向滚动而横向滑动。

### 5.C Scroll-Reveal Stagger 规范骨架（更轻的替代）

只需要简单的「进入视口时出现」（不需要钉住）时，优先用 Motion 的 `whileInView` 而不是 GSAP。更轻，也不需要 ScrollTrigger：

```tsx
"use client";
import { motion, useReducedMotion } from "motion/react";

export function RevealStagger({ items }: { items: string[] }) {
  const reduce = useReducedMotion();
  return (
    <ul className="grid gap-6">
      {items.map((item, i) => (
        <motion.li
          key={item}
          initial={reduce ? false : { opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.3 }}
          transition={{
            duration: 0.6,
            delay: i * 0.06,
            ease: [0.16, 1, 0.3, 1],
          }}
        >
          {item}
        </motion.li>
      ))}
    </ul>
  );
}
```

**适用场景**：feature 列表、证言栅格、logo 墙，以及任何只需要「滚动进来」的东西。**把 GSAP 留给真正需要 pin / scrub 的工作。**

### 5.D 禁止的动画写法

* **`window.addEventListener("scroll", ...)` 是禁令。** 它每帧都跑，极易掉帧，无法批处理。改用 Motion 的 `useScroll()`、GSAP 的 `ScrollTrigger`、`IntersectionObserver`，或 CSS 滚动驱动动画（`animation-timeline: view()`）。
* **在 React state 里用 `window.scrollY` 自己算滚动进度。** 同样原因，每帧都重渲染。
* **碰 React state 的 `requestAnimationFrame` 循环。** 改用 motion value（`useMotionValue` + `useTransform`）。
* **布局过渡**：可见状态变化（列表重排、弹层展开、路由间共享元素）用 Motion 的 `layout` 和 `layoutId` props。**不要「为了保险」把静态内容包进 `layout`**，那会付出测量开销。
* **级联编排**：顺序重要的揭示时刻，用 `staggerChildren`（Motion）或 CSS 级联（`animation-delay: calc(var(--index) * 100ms)`）。用 `staggerChildren` 时，父级（`variants`）与子级**必须**在同一棵 Client Component 树里。
