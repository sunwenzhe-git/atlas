---
title: Optimize Largest Contentful Paint
impact: CRITICAL
impactDescription: LCP under 2.5s improves SEO rankings by 8-15%
tags: cwv, lcp, performance, loading, images
---

## Optimize Largest Contentful Paint

LCP measures how long the largest visible element takes to render. A slow LCP (over 2.5s) hurts SEO rankings and causes users to perceive the page as slow.

**Incorrect (blocking LCP element):**

```html
<head>
  <!-- Render-blocking CSS -->
  <link rel="stylesheet" href="all-styles.css">
  <!-- Blocking fonts -->
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Roboto">
</head>
<body>
  <!-- Hero image without optimization -->
  <img src="hero-4k.jpg" alt="Hero banner">
  <!-- LCP element loads after all CSS and fonts -->
</body>
```

**Correct (prioritized LCP element):**

```html
<head>
  <!-- Preload LCP image -->
  <link rel="preload" as="image" href="hero-optimized.webp" fetchpriority="high">
  <!-- Critical CSS inlined -->
  <style>/* Above-fold styles */</style>
  <!-- Non-critical CSS deferred -->
  <link rel="stylesheet" href="styles.css" media="print" onload="this.media='all'">
</head>
<body>
  <!-- Optimized hero with explicit dimensions -->
  <img
    src="hero-optimized.webp"
    alt="Hero banner"
    width="1200"
    height="600"
    fetchpriority="high"
    decoding="async"
  >
  <!-- LCP element loads first, renders within 2.5s -->
</body>
```

**LCP optimization strategies:**
- Preload LCP images with `fetchpriority="high"`
- Use WebP/AVIF formats (30-50% smaller than JPEG)
- Inline critical CSS, defer non-critical styles
- Set explicit width/height to prevent layout shifts

Reference: [web.dev LCP](https://web.dev/articles/lcp)

## 6.F Core Web Vitals 与交付（原 SKILL.md 逐字移入）

* **LCP < 2.5s**：hero 图用 `next/image priority` 或预加载，**绝不延迟加载**。`references/cwv-optimize-lcp.md`、`references/cwv-lazy-load-offscreen.md`
* **INP < 200ms**：重活移出主线程。`references/cwv-improve-inp.md`
* **CLS < 0.1**：图片显式给 `width`/`height` 或 `aspect-ratio`，字体度量对齐，不late 注入横幅。`references/cwv-minimize-cls.md`
* 交付：`srcset` + `sizes`，WebP/AVIF 优于 JPEG，内联关键 CSS。`references/cwv-responsive-images.md`、`references/cwv-critical-css.md`
* 字体：`next/font` 或自托管 `@font-face` 配 `font-display: swap`；预加载关键字重时**必须带 `crossorigin`**（同源也要）。`references/typo-font-display.md`、`references/typo-preload-fonts.md`
* 正文流体字号用 `clamp()`，下限 16px、上限 20px。`references/resp-fluid-typography.md`
* 行高与行宽见 6.K。细则：`references/typo-line-height.md`、`references/typo-readable-line-length.md`
* **交付前跑一次 Lighthouse。**
* **交付前跑机器检查：`npx impeccable detect src/`（或对本地预览 URL 跑，用渲染后布局查对比度、溢出、触控目标）。exit 2 的 findings 必须先处理或写明豁免理由；零安装、零 token，不依赖模型自查。**
