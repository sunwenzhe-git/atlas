# 范式词汇表

_原 SKILL.md Section 10 逐字移入。这是词汇表，不是组件库。_

**这是词汇表，不是库。** 模型应该**知道**这些范式名，以便讨论它们、带着它们做设计、并在 design read 需要时调用它们。**具体实现与代码草图在区块库（Section 12），那里是逐步补齐的。**

**命名约定**：范式名保留英文（这是与设计业界共用的词汇，也是可检索的），括号里给中文注解。

### Hero 范式
* **Asymmetric Split Hero**（非对称分栏 Hero）：一侧文案、一侧资产，大量留白。
* **Editorial Manifesto Hero**（编辑宣言 Hero）：大字号、无资产，接近海报。
* **Video / Media Mask Hero**（视频遮罩 Hero）：文字镂空成遮罩，底下是视频。
* **Kinetic-Type Hero**（动态字体 Hero）：用动画字体本身当主要视觉。
* **Curtain-Reveal Hero**（幕布揭示 Hero）：hero 随滚动像幕布一样分开。
* **Scroll-Pinned Hero**（滚动钉住 Hero）：hero 钉在原地，内容从后面滚过。

### 导航与菜单
* **Mac OS Dock Magnification**（Dock 放大）：边缘导航，悬停时图标平滑放大。
* **Magnetic Button**（磁性按钮）：向光标方向吸附。
* **Gooey Menu**（黏稠菜单）：子项像黏稠液体一样分离出来。
* **Dynamic Island**（灵动岛）：形变的胶囊，承载状态 / 提醒。
* **Contextual Radial Menu**（场景化环形菜单）：在点击处展开的圆形菜单。
* **Floating Speed Dial**（浮动速拨）：FAB 弹开成弧形次级操作。
* **Mega Menu Reveal**（巨型菜单展开）：全屏下拉，内容 stagger 淡入。

### 版面与栅格
* **Bento Grid**（便当栅格）：非对称瓦片分组（Apple 控制中心那样）。
* **Masonry Layout**（瀑布流）：错落栅格，行高不固定。
* **Chroma Grid**（色度栅格）：描边 / 瓦片带轻微流动的渐变。
* **Split-Screen Scroll**（分屏滚动）：左右两半朝相反方向滑。
* **Sticky-Stack Sections**（粘性堆叠 section）：section 钉住并逐层堆叠。

### 卡片与容器
* **Parallax Tilt Card**（视差倾斜卡）：跟随鼠标坐标做 3D 倾斜。
* **Spotlight Border Card**（聚光描边卡）：光标位置点亮边框。
* **Glassmorphism Panel**（玻璃拟态面板）：磨砂玻璃，带内折射。
* **Holographic Foil Card**（全息烫箔卡）：悬停时虹彩流转。
* **Tinder Swipe Stack**（滑动卡堆）：实体卡堆，可以甩出去。
* **Morphing Modal**（形变弹层）：按钮展开成自己的对话框。

### 滚动动画
* **Sticky Scroll Stack**（粘性滚动堆叠）：卡片粘住并物理堆叠。
* **Horizontal Scroll Hijack**（横向滚动劫持）：纵向滚动转成横向平移。
* **Locomotive / Sequence Scroll**（序列滚动）：视频 / 3D 序列绑在滚动条上。
* **Zoom Parallax**（缩放视差）：中心背景图随滚动缩放。
* **Scroll Progress Path**（滚动进度路径）：SVG 线沿滚动逐步描绘。
* **Liquid Swipe Transition**（液体滑动转场）：页面转场像黏稠液体。

### 画廊与媒体
* **Dome Gallery**（穹顶画廊）：3D 全景画廊。
* **Coverflow Carousel**（Coverflow 轮播）：带斜角的 3D 轮播。
* **Drag-to-Pan Grid**（拖拽平移栅格）：无边界的可拖动画布。
* **Accordion Image Slider**（手风琴图滑）：窄条在悬停时展开。
* **Hover Image Trail**（悬停图像拖尾）：鼠标经过时弹出图像轨迹。
* **Glitch Effect Image**（故障效果图）：悬停时 RGB 通道错位。

### 字体与文本
* **Kinetic Marquee**（动态跑马灯）：无尽文字带，随滚动反向。
* **Text Mask Reveal**（文字遮罩揭示）：巨大文字作为透出视频的窗口。
* **Text Scramble Effect**（文字乱码效果）：加载 / 悬停时矩阵式解码。
* **Circular Text Path**（环形文字路径）：文字沿旋转圆圈弯曲。
* **Gradient Stroke Animation**（渐变描边动画）：描边文字带流动渐变。
* **Kinetic Typography Grid**（动态字体栅格）：字母躲开光标。

### 微交互与效果
* **Particle Explosion Button**（粒子爆裂按钮）：CTA 成功时炸成粒子。
* **Liquid Pull-to-Refresh**（液体下拉刷新）：刷新指示器像水滴分离。
* **Skeleton Shimmer**（骨架微光）：占位块上掠过移动的高光。
* **Directional Hover-Aware Button**（方向感知按钮）：填充从光标进入的那一侧进来。
* **Ripple Click Effect**（波纹点击效果）：从点击坐标扩散的波。
* **Animated SVG Line Drawing**（SVG 自绘线）：矢量线实时画出自己。
* **Mesh Gradient Background**（Mesh 渐变背景）：水母灯式的有机色块。
* **Lens Blur Depth**（镜头虚化景深）：模糊背景 UI 以聚焦前景操作。

### 动效库选择
* **Motion（`motion/react`）**：UI / Bento / 状态变化动效的默认选择。
* **GSAP + ScrollTrigger**：整页滚动叙事和滚动劫持。隔离在专门的叶子组件里，配 `useEffect` 清理。
* **Three.js / WebGL**：画布背景和 3D 场景。同样的隔离规则。
* **绝不在同一棵组件树里混用 GSAP / Three.js 与 Motion。** 它们会抢同一批帧。
