# RFC-20261017-01 · E2E 页面表 `路由` 列允许 **hash 相对形态**（`#/…`）

- 状态：**待独立评审**（评审通过后落刀；未落刀）
- 关联：issue **#27**（`duty-review/bugs.md` E2E 段）；同族任务 `10-16-e2e-param-route-and-panel-steps`
- 输出语言：中文
- 作者：本会话（agent_learning）；评审者须**干净上下文**（`rings/e2e/reference.md` §12.6）

## 1. 现场与病灶

应用（百炼/v2前端）真实可导航地址形态：

```
壳前缀 /console/ + hash 路由 + 宿主 tenant 必须在 query
http://localhost:2000/console/?switchAgent=7202#/app/agent/detail/2110669642083168258
```

三条消费点各自成立，**合起来无合法写法**：

| # | 事实 | 取证 |
|---|---|---|
| ① | 应用**只读 URL query** 取 tenant（`g_config.switchAgent` = `searchParams.get('switchAgent')`；`agent-select` 同）——**无 sessionStorage 回落** | `src/common/config/g_config.ts:8`、`src/entry/main/layout/header/agent-select/index.tsx:25` |
| ② | 缺 tenant ⇒ 页面停在「**请选择业务空间**」，应用详情**不渲染** | 2026-10-17 探针：无 tenant 等 25s timeout；带 `?switchAgent=7202` 立刻找到附件入口 |
| ③ | `会话:` 通道写的是 **sessionStorage**（`addInitScript`）⇒ **送不到** ① 这个消费点 | `_support`/生成器 §5.5「会话:」实现；`DESIGN.md` D89 |
| ④ | `goto` 被门禁**不得带查询参数**（§5.7 防「参数直达数据态」） | `rings/e2e/reference.md` §8.2 `goto` 路径门 / §5.7 |
| ⑤ | 生成物 `page.goto('/console/#/…')` 是**绝对路径** ⇒ `new URL()` **丢弃 base 的 query** | 本机实测（见下） |

实测（`node -e "new URL(t, base)"`，base = `http://localhost:2000/console/?switchAgent=7202`）：

| target | 结果 |
|---|---|
| `#/app/agent/detail/1` | `http://localhost:2000/console/?switchAgent=7202#/app/agent/detail/1` ← **base 的 path 与 query 都保住** |
| `/console/#/app/agent/detail/1` | `http://localhost:2000/console/#/app/agent/detail/1` ← query 丢 |
| `/app/agent/detail/1` | `http://localhost:2000/app/agent/detail/1` ← 壳前缀丢（dev server 回 `Cannot GET /app/agent/detail`） |

⇒ 只要导航目标写成 **hash 相对形态**（`#/…`），tenant 由 `e2e.app_base_url` 承载即可全程带上，**`goto` 仍不带 query**（不破 §5.7 的禁令）。

## 2. 方案 A（本 RFC 主张）：`路由` 列允许 hash 相对形态

**改什么**（四处代码 + 两处契约；**不动 `会话:` 通道、不新增字段**）：

| # | 文件:行 | 现状 | 改为 |
|---|---|---|---|
| 1 | `validators/validate_e2e_index.py:434` | 页面表 `路由` 校验收 `路由非/开头或重复=…` | 允许 `#/` 开头（与 `/` 并列），其余仍拒 |
| 2 | `validators/validate_e2e_index.py:314-315`、`:660-663`（`_route_hit`） | 「非根路由的子路径前缀命中；根路由 `/` 仅精确」 | 同口径**照搬**到 hash 形态（`#/` 视为该形态的根：仅精确；`#/x` 前缀命中 `#/x/y`） |
| 3 | `scripts/gen_e2e_scripts.py:1287`（`miss_route` 判定） | 只认 `/` 开头 | 同 #1 |
| 4 | `rings/e2e/reference.md:78`（§3.2 表注） | 「`路由` 以 `/` 开头且全表唯一」 | 「`路由` 为**路径形态**（`/…`）或 **hash 相对形态**（`#/…`）——后者用于 hash 路由应用：base 的 query 由 `e2e.app_base_url` 承载，`#/…` 相对形态可保住它（见 §5.5 注）；全表唯一」 |
| 5 | `rings/e2e/reference.md` §5.5 附近 | — | 增一条注：**为何是相对形态**（绝对路径会丢 base 的 path+query）+ 与「`goto` 不带查询参数」不冲突的说明（参数在 base，不在 step） |
| 6 | v2 项目资产（**非源包**）：`product/e2e/e2e-index.md` 页面表路由、`product/e2e/cases/*.md` 的 `守卫:`/`goto`、`product/stack-profile.yaml` 的 `app_base_url`（已带 tenant） | 现状 `/app/agent/detail` / `#/…` 等 | 路由 = `#/app/agent/detail` 等；`守卫:`/`goto` = `#/app/agent/detail/<真 id>` |

**钉与变异**（按本仓纪律）：
- validator：`#/…` 路由 ⇒ `路由非/开头或重复` PASS；`goto #/x/y` 前缀命中 `#/x` ⇒ PASS；`goto #/x-越界` ⇒ FAIL；`#/` 根仅精确（`#/x` 不命中 `#/`）。
- generator：hash 形态路由不再进 `miss_route`；生成物 `page.goto('#/…')` 逐字节如分片所写。
- 变异 M94/M95（待定编号）：撤回 `#/` 容忍 ⇒ 对应钉红；`_route_hit` 去掉 hash 分支 ⇒ 前缀钉红。

## 3. 方案 B（**本 RFC 不主张**，列入被否）：给 `会话:` 通道扩一档「URL 参数」

`会话: switchAgent=7202` 声明后，生成器在 `goto` 前 `addInitScript` 重放 query、或 `goto` 后补写并 reload。

- **优**：语义上「宿主注入型前提」与 `会话:` 同族（D89 的本意），形态更靠近「前提」而非「路由」。
- **否的理由**：① 要新增字段（`session_preset.url_keys` 或 `channel` 映射）——`DESIGN.md` D99 已冻结字段集（新增须独立决策行）；② 生成器要多一条「重放/reload」路径（reload 会打断 SPA 状态与 `waitFor` 语义，`addInitScript` 改不了已发生的首屏导航）；③ 方案 A 的成本更低（只放宽一个值域 + 一处文档），且**不动运行时行为**；④ 方案 A 对「非 hash 路由」的应用同样成立（其路由本来就写 `/…`）。
- 若评审认为「**前提**」必须走 `会话:` 而非「路由形态」，本条应改判为 B——这正是请求评审的点之一。

## 4. 与既有裁决的关系

| 关联 | 关系 |
|---|---|
| `D90`（`守卫:` 标量键承载具体路径） | **同族**：都是「页面表 `路由` 是**模式**、不是可导航地址」的产物。D90 给了用例级出口；本 RFC 让**基线与守卫共用的那一列**也能表达 hash 形态真实路由 |
| `#23`（页面表路由被当具体 URL 用于守卫导航 ⇒ 带参页守卫必红） | 已由 D90 修（守卫承载具体路径）。本 RFC **不**与它冲突：D90 解决「带参」，本 RFC 解决「形态写不出来」 |
| `D89`（`会话:` 通道 = sessionStorage） | **不动**。方案 A 明确不做「URL 参数通道」，理由见 §3 |
| D99（字段集冻结） | 方案 A **不加字段** ⇒ 不触 D99 |
| D103（人工会话取出） | 与本 RFC 正交：那条解「登录态」，本条解「导航地址形态」 |

## 5. 残留与诚实边界（不得 oversell）

1. **零步基线仍可能红**：基线用页面表 `路由`（页级，`#/x` 无实例 id）⇒ 带参页面在基线上探不到元素 ⇒ 契约 §5.5 已规定「按 `null = 不成立` 处理，不产生假阳性」。本 RFC **不**声称把基线修绿；基线与「打开面板/选中节点」等步骤问题归同族任务 `10-16-e2e-param-route-and-panel-steps`。
2. **前缀命中的既有弱点原样保留**：`/x` 与 `#/x` 都可能被「合法前缀 + 真垃圾尾」命中（§5.5 已登记的独立待办），本 RFC 不收紧。
3. **本机实测的 URL 语义**（`new URL` 相对形态）是 Node/浏览器标准语义，非 atlas 自造；但仍**未在真跑链上端到端验证**（评审通过后落刀再验）。

## 6. 请求评审者判的点（逐条给结论 + 证据）

1. 方案 A vs B：「导航地址形态」到底应归**路由列的值域**，还是归**会话前提的通道**？给出理由与反例。
2. `#/` 形态的**前缀命中**口径是否应与 `/` 完全同构（含「根仅精确」）？有没有被我漏掉的第三方消费者（`manual.md` 手工项、控制台开浏览器、`impact` 推导、`apply` 影响面……）会因此坏掉？
3. 本轮同批已提交的四处改动（见 `REVIEW` 任务的输入清单）是否与方案 A 冲突。
4. 方案 A 的改动面是否**遗漏**（尤其：是否有别处硬编码「以 / 开头」的判据）。

## 7. 落刀清单（评审通过后执行，供核对）

源包：`validators/validate_e2e_index.py` / `scripts/gen_e2e_scripts.py` / `rings/e2e/reference.md` / `tests/test_validators.py` / `tests/test_gen_e2e_scripts.py` / `shared/gates.md`（计数与行）/ `DESIGN.md`（D104）/ `CHANGELOG.md` + `docs/guide/changelog.md` / `duty-review/bugs.md`（#27 状态）。
项目侧：`product/stack-profile.yaml`（已改）/ `product/e2e/e2e-index.md` / `product/e2e/cases/*.md` → 重生成 → 真跑验证。
