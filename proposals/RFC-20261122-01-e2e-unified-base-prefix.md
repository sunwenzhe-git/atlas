# 提案标题：E2E 靶场接入「统一前缀」——壳前缀与路由形态由 `app_base_url` 单源承载

> 提案编号：RFC-20261122-01
> 提案作者：@sunwenzhe-git
> 关联状态：已定案 (Accepted)——2026-11-22 tech-proposal-reviewer 独立评审**修后通过**（B1/B2/B3 已修入本文，M1-M4 并入 §2.4 落刀顺序）；**同日已落刀**（全量 1957 过 6 skip，playground 真跑门未入本轮），勾选面见 §3
> 影响范围：环契约 (rings/e2e) | 脚本工具 (scripts) | 共享内核 (_support) | 校验器 (validators) | 控制台 (scripts/e2e_console.py)

---

## 1. 现象与取证 (The Problem & Evidence)

### 1.1 触发形态（抽象）

* **规则 / 环节**：E2E 导航地址发射面（生成器 step `goto` / 守卫 / 零步基线 / 具名靶场；控制台手工项「打开」）与契约 §3.2 页面表 `路由` 列语义。
* **触发时机**：靶场应用为 **HashRouter + 部署在子路径壳前缀下 + 宿主注入 query** 三合一形态时（`e2e.app_base_url = http://h/shell/?tenant=T`），用例侧写业务段路由并生成脚本。
* **具体行为**：当前生成器对导航目标只做 query 合并（`url_merge.merge_base_query`，D104/D109 口径），**不合并 base 的路径段、不做 hash 形态重组**：

```text
页面表 路由列 = /app            （业务段，契约 §5.5 守卫注释口径「路由列只承载业务段」）
分片 step    = goto /app        （业务段）
base         = http://h/shell/?tenant=T

发射结果（现状）：
  await atlasGoto(page, '/app?tenant=T')
  ⇒ Playwright baseURL 解析：new URL('/app?tenant=T', 'http://h/shell/?tenant=T')
  ⇒ http://h/app?tenant=T          ← 壳前缀 /shell 丢失，落到路由匹配不上的地址（404 / 空壳页）
```

要让生成物可用，唯一的现存出路是**把全形态地址逐字手写进每一条用例**：

```text
step:  - goto /shell/?tenant=T#/app
```

⇒ 壳前缀 + hash 形态在**每条用例的每个 goto、每条守卫、每条基线 URL 里重复**；靶场换部署路径或换 tenant 前缀时 = 全量用例重写。这正是「统一前缀」要摘掉的重复。

**取证更正（2026-11-22 评审 B1，已实跑复核）**：守卫的 hash-only 写法 `守卫: #/app` **在解析层就写不出来**——标量键值过全域单源 `strip_inline_comment`（`_support/stack_profile.py`），`#` 前有空白即注释起点，实测解析结果为**空串**，静默回落页面路由（生成器 `_guard_target … or url` 兜底）。本提案**不收** hash-only 输入形态，也不动 `strip_inline_comment`（全域单源，改动波及面远超本 RFC）；守卫与 goto 同口径写业务段，或缺省回落页面 URL（统一后页面 URL 本身带壳与 hash，守卫语义反而首次成立）。

### 1.2 客观证据与日志 (Minimal Evidence)

实跑仓（HashRouter 前端靶场，真实项目）取证，已抽象：

```text
# stack-profile.yaml（唯一真相源）
app_base_url: http://localhost:3000/<shell>/?switchAgent=<T>

# 分片（业务段形态——用户已按「统一前缀」预期把分片简化干净）
守卫: #/app                        ← 实测解析为空串（评审 B1：# 前有空白 = 注释起点），
step:                               静默回落页面路由；本提案不收 hash-only 形态
  - goto /app

# 现有生成物（由早期手写全形态分片生成，仍可跑）
await atlasGoto(page, '/<shell>/?switchAgent=<T>#/app');
//   - goto /<shell>/?switchAgent=<T>#/app          ← step 注释逐字回显手写全形态

# 对照：用当前主线生成器对当前分片重生成（语义推演，merge_base_query 单源已核）
await atlasGoto(page, '/app?switchAgent=<T>');       ← 壳前缀丢失
```

对照契约的两可态：`rings/e2e/reference.md` §3.2 允许路由列「可含 hash 段（壳前缀与 `#` 都属路径形态）」，而生成器守卫注释（§5.5）又称「页面表 `路由` 列只承载业务段」——同一列两种口径并存，正是本提案要收窄成单一口径的点。

---

## 2. 决策与权衡 (The Decision & Trade-offs)

### 2.1 核心定案 (The Decision)

* **方案总结**：新增 stack-profile 闭集键 **`e2e.route_style`**（词表：`hash`；缺省 = 不声明，全链逐字节零变化）。声明 `hash` 时，全部导航发射面统一经内核单源函数 `url_merge.merge_base_prefix(target, base, style)` 重组——**壳前缀（base 路径段）+ 宿主 query + hash 形态由 `app_base_url` 一处声明，用例侧全量只写业务路由**。判别式钉死为确定性算法（评审 B2）：

```text
style = hash 时的逐条算法（按序判定，无歧义态）：
  ① target 不以 / 开头（外部绝对 URL 等）        → 原样（merge_base_query 对其本就零变化）
  ② target 含 #（存量全形态 / 异壳具名靶场）      → 路径与 hash 段逐字节原样，仅 query union：
       /shell#/app/x        → /shell?tenant=T#/app/x
       /app?t=1#/h          → /app?tenant=T&t=1#/h     ← 含 # = 全形态，不重组（评审 B2 改例）
  ③ target 无 # 且以 / 开头（业务段，唯一合法书写形态）→ 重组：
       /app                 → /shell/?tenant=T#/app
       /app?t=1             → /shell/?tenant=T&t=1#/app   （query 留 query 侧，D109 并集：base 前置、同键 target 胜）
  ④ hash-only 形态（#/app）不收：解析层写不出来（B1），守卫与 goto 同口径写业务段

幂等：f(f(x)) = f(x)——业务段重组结果含 # ⇒ 二次进入②原样返回；query union 同键去重。
零变化钉（评审 M3）：style=None 时 **字面委托** `return merge_base_query(target, base)`，
禁止平行实现——两函数漂移即破未声明项目的逐字节零变化承诺。
异壳边界：具名靶场（e2e.targets）地址若与 base 不同壳，须写全形态（走②）；「同壳业务段」
只认与 base 路径一致的壳，异壳前缀不支持重组（文档明示，不猜）。

* **发射面收口清单**（全部现有调用点，一次接上单源函数）：
  1. `gen_e2e_scripts.py` step `goto`（第二发射面）
  2. `gen_e2e_scripts.py` 守卫导航（第一发射面）
  3. `gen_e2e_scripts.py` 零步基线页面 URL / 具名靶场 URL（第三发射面 ×2）
  4. `e2e_console.py` 手工项「打开」`manual_open_url`（第四发射面）
* **控制台面的落法**：控制台**不新增 UI**。执行面走生成物自动继承；手工打开面经同一单源函数统一；「靶场」源信息行照常展示 `app_base_url`（前缀声明处可见）。运行期改址不在本提案范围（host 覆盖已有 `ATLAS_BASE_URL` 通道；query/前缀按 D104 既定口径 = 改 profile + 重生成）。
* **为何这是正解**：① 重复的根因是「接入前提」被摊进了「业务语义」的书写面——把壳前缀与 hash 形态归位到它所属的靶场声明（`app_base_url`），重复自然消失，与 D104 把宿主 query 收进 base 同一条分界线；② 契约两可态收窄为单一口径（声明 hash ⇒ 业务段；全形态保留为存量兼容形态）；③ 五个发射面本就全部漏斗过 `url_merge.merge_base_query`，单源函数一次收口，无第二处实现。

### 2.2 最强反方与证伪条件 (Strongest Counterargument & Falsification)

* **最强反方论证**：「统一前缀把真实导航地址从用例可见面藏进 profile——分片评审者看 `goto /app` 不再知道真实地址长什么样，『分片即真相源』弱化，证据面缩水；hash 重组是生成期的隐式变换，出问题时人看分片对不出地址」。这一条同时否决了「运行时覆盖输入框」（控制台 UI 改址）备选——它把同一变换搬到更晚、更不可留证的运行期。
* **回应**：D104 已把宿主 query 藏进 base 并把语义烘成生成期常量（"生成期变换把语义烘成常量"，原文口径），壳前缀与 query **同性质**——都是靶场接入前提，不是业务语义；且生成物 step 注释**回显统一后的全形态地址**（现有回显机制不变），评审在生成物面依然逐字可见。
* **证伪条件**：`discriminating_check{command, expected_if_false}`——在 hash 靶场项目上：`python3 scripts/gen_e2e_scripts.py --apply` 重生成后，对生成物中全部导航地址（**两种发射形态都取**，评审 M3：base 无 query 的项目走 `page.goto(`，只 grep `atlasGoto(` 判据面不全）与手写全形态基线做逐字节 diff；**任一条地址不一致（query union 键序除外）** ⇒ 方案错。命令：`diff <(grep -oE "atlasGoto\(page, '[^']*'\)|page\.goto\('[^']*'\)" 生成物) <(cat 手写全形态清单)`，期望为空 diff。

### 2.3 必须警惕的刺痛代价与兼容性影响 (Trade-offs)

* **零变化承诺**（本提案的硬边界）：未声明 `route_style` ⇒ 全部发射面逐字节不变（playground 等无壳项目、`route_style` 缺省项目全量免检）；路由已含 `#` 的全形态存量项目不声明也零变化。声明 `hash` 的项目首次需重生成——「生成物最新」门会红，属预期内的咬合提示。
* **兼容性**：`_support/url_merge.py` 与 `stack_profile.py` 是装配件——采纳仓需 `atlas upgrade / install.sh --update` 才咬合（安装副本文案齐套面照 D206 批口径全 WARN 跑出声）。
* **执行耗时**：无新增运行期开销（纯生成期字符串变换）。
* **范围边界（评审 M2）**：「单源承载」只统一**导航面**（goto / 守卫 / 基线 / 靶场 / 手工打开）。登录 probe 与 `api`/`request`/`mock` 等 **API 请求面不在范围**——`_support/auth_state.py` 的 probe URL 组装今天就不带 base 路径段，壳前缀靶场的 probe 打点属另一个缺口，本 RFC 只声明边界、不顺手修，防「app_base_url 单源承载一切」的误读。
* **长期维护成本**：新增面 = `url_merge` 一个纯函数 + profile 一个闭集键 + 词表校验一处。生命周期到「hash 路由形态成为历史」为止；`path` 形态（非 hash 应用部署在子路径下）等真实消费者出现再进词表，不预留（评审同意 YAGNI；词表错误文案给「path 形态未支持」留指向，防用户拿 hash 硬套 path-router 项目）。

### 2.4 落刀顺序（实施计划；含评审 M1/M3/B3 联动）

1. **内核单源**：`_support/url_merge.py` 新增 `merge_base_prefix(target, base, style)`——§2.1 判别式逐条实现；`style=None` **字面委托** `merge_base_query`（M3 钉）；query union 复用现有 `union_query`；幂等（对输出再变换 = 原样）+ **双跳合并**用例（页面级 `url` 再过守卫面的实际调用链，不只纯函数级 f(f(x))）。
2. **键归一化**：`_support/stack_profile.py` 新增 `normalize_route_style(raw)`（闭集词表 `{hash}`，缺省 `None`；坏值 fail-loud，错误文案带「path 形态未支持」指向）——与 `normalize_mock_prefixes` 同款单源，校验器与生成器共用。
3. **生成器**：`scripts/gen_e2e_scripts.py` 读取 `e2e.route_style`；四个导航发射面（step `goto` / 守卫 / 零步基线页面 URL / 具名靶场 URL）由 `merge_base_query` 切至 `merge_base_prefix`；词表外值中止（fail-loud，与 `靶场:` 闭集同款）。**守卫面顺序重排（评审 M1）**：先 `merge_base_prefix` 重组（业务段目标因此获得 hash 段），**再** `append_query` / `append_hash_query` 注入 `参数:` / `hash参数:`（两 append 本就按「对已合并 url 幂等」设计），最后 `merge_base_query` 幂等收口——否则 style=hash + 业务段守卫在 `hash参数:` 处即 ValueError 中止。
4. **控制台**：`scripts/e2e_console.py` `manual_open_url` 同步切换（origin + 前缀重组 + query 合并一次成型）。
5. **校验器（评审 B3，选①归一比对）**：`validators/validate_e2e_index.py` `_route_hit` 在 style=hash 下对 goto/守卫目标与页面表路由**两侧各过 `merge_base_prefix` 归一后再比对**（单源复用；校验器已装配 stack_profile 解析器）——存量全形态 goto 与业务段页面表因此可共存过渡；另对「style=hash 且页面表路由含 `#`」发迁移 WARN（不阻断）。理由记档：选②（一步收窄、不做混合共存）更省，但会把存量项目的迁移窗口卡死成全量 FAIL，违背「无关的改动不连坐」仓规。
6. **测试钉子**：`url_merge` 三形态 × 幂等 × 双跳 × 委托等价单测；生成器 hash 项目 goto/守卫/基线/靶场四面对齐手写全形态断言（**靶场含同壳与异壳两态**，评审 M4）；未声明键逐字节零变化断言；控制台 `manual_open_url`；坏词表中止；validator 混合形态命中 + 页面表迁移 WARN。
7. **文案面**：`rings/e2e/reference.md` §3.2 / §5.5 口径改写（§5.5 把 D104 ②「ATLAS_BASE_URL 只覆盖 host、不覆盖 query」延伸为「不覆盖 query 与路径前缀」）；`shared/stack-profile.md` §2 e2e 键表加 `route_style` 行；`templates/stack-profile.yaml` 注释；CHANGELOG 两份 `[Unreleased]`。

---

## 3. 改动面清单 (Affected Surface)

- [x] **契约/文档**：`rings/e2e/reference.md` §3.2（路由列口径收窄注记）、§5.5（`route_style` 口径 + D104 ② 延伸 + 与 D109 缝合）；`shared/stack-profile.md` §2 e2e 键表（评审 Minor）
- [x] **代码逻辑**：`_support/url_merge.py`（新单源函数 `merge_base_prefix`）、`scripts/gen_e2e_scripts.py`（四处发射面 + 守卫面注入顺序重排 + `route_style` 读取与闭集中止）、`scripts/e2e_console.py`（`manual_open_url`）、`_support/stack_profile.py`（键归一化 + 闭集校验，坏值 fail-loud 中止）
- [x] **校验器**：`validators/validate_e2e_index.py` `_route_hit` style=hash 归一比对（评审 B3①）+ 页面表全形态迁移 WARN
- [x] **明确不动的面**：`_support/case_block.py` / `strip_inline_comment`（全域单源，B1：不动）；`_support/auth_state.py` probe 面（M2：只声明边界）
- [x] **测试防线**：`tests/`（url_merge 三形态×幂等×双跳×委托等价单测；生成器对 hash 项目 goto/守卫/基线/靶场四面对齐断言〔含同壳/异壳靶场〕；未声明零变化逐字节断言；坏词表中止；控制台 manual_open_url；validator 混合形态）
- [x] **留出验证（§4.5）**：非触发写「不适用 + 触发面核对（a/b）」
- [x] **版本装配**：`templates/stack-profile.yaml` 注释；安装副本咬合面（upgrade/update 文案齐套）
- [x] **CHANGELOG**：两份 `[Unreleased]` 手补
