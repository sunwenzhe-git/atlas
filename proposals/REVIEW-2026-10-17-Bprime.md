# REVIEW-2026-10-17-B′ · 增补独立评审（方案 B′）

- 评审者：独立评审员（干净上下文；仅以 §9.1 的实跑证据 + 代码实读为据，未采信作者自述作为结论）
- 对象：`proposals/RFC-20261017-01-e2e-route-hash-form.md` §9（B′）
- 基线：`proposals/REVIEW-2026-10-17-source-batch.md`（已定事项）
- 方法：**只读**；**本会话无 shell / write / git**，故**未跑**干跑、`pytest`、`git`——全部结论落到 `file:line` 实读，未落到可复跑命令（见 §我不同意但你… 末条）
- 输出语言：中文

---

## § 方案取舍

**结论：同意 B′ 的层次（合并发生在「生成物导航层」），但落点清单不完整，「一处发射」是低报，且有一条被 B′ 前提直接打坏的第五消费者未列。** 建议：**B′ 采纳，落刀按下述清单补齐**；并建议把合并实现为**生成期纯函数变换**而非运行期 TS 助手。

### 为什么「生成物导航层」是正确层次

三案都碰过，逐条对：

| 案 | 层次 | 判 |
|---|---|---|
| A（`#/…` 直接写进用例块） | 用例文本值形态 | **已被 §9.1 实测推翻**（`_support/stack_profile.py:45` `ch == "#" and (i == 0 or line[i-1] in " \t")` ⇒ `goto #/…` 值被吞成 `'goto'`）。同意作者撤回。 |
| B（`会话:` 扩 URL 参数档） | 运行时行为 | 触 D99 冻结字段集 + reload 打断 SPA，成本最高。同意不作主张。 |
| **B′（生成物把 base query 带进每一跳）** | 生成物导航层 | **正确**：地址的唯一真相源本就是 `e2e.app_base_url`（`rings/e2e/reference.md:437`、`:458`），宿主注入的 tenant 本就住在那里；生成物是它的消费者，负责把它转发到它自己的每一跳 `goto`。不改共享注释语义（A 的死因）、不加字段（B 的死因）、用例侧仍 `?`-free（§5.7 不破）。 |

### 第三案（更小），我倾向它取代 §9.2 的「发射导航助手」

**生成期纯函数变换**，而非运行期 helper：

- 在**生成期**用 `_merge_base_query(target, base)`（Python 侧，`urlparse(base).query` 取 query，按 `#` 切分目标，把 query 插在 path 与 hash 之间）处理**三处**导航目标串，直接发射已合并的绝对路径。
- **无需**新增运行期 TS 助手、无需每站 `if/else` 包一层 → 零变化面只落在「base 含 query」一个分支，且生成物**确定性可快照**（`生成物最新` 门 `shared/gates.md:64` 天然看守）。
- 附带解开一个 B′ §9.2「运行期助手」方案的隐患：config 用 `ATLAS_BASE_URL ?? '{base}'`（`gen_e2e_scripts.py:1540`/`:1566`）。运行期 helper 要正确跟随覆盖，得从 `test.info().project.use.baseURL` 反取 base（modal）——生成期变换把这问题化为「烘进常量」，语义直白。

**更激进但更脆的第三案（仅登记，不推荐）**：生成期把目标整段转成 hash 相对形态 `page.goto('#/…')`，把 query 完全交还 Playwright 的 `baseURL` 解析（RFC §1 表首行证明 base 的 path+query 全保）。免去手写 query 合并，**但**仅当 base 的 path 与目标 `#` 前那段一致时成立（`base=http://host/` + target `/console/#/…` ⇒ `/console` 丢失）⇒ 脆，不作主张。

**我不主张改判 B / A。** B′ 层次成立；A 的病是物理不可写，不是设计不好。

---

## § 落点清单（确切 `file:line`）

作者 §9.2 写「**一处发射 + 契约一句**」。实读后，**发射面是三处，不是一处**：

**发射面（`scripts/gen_e2e_scripts.py`）**

| # | 位置 | 现状 | 必须做 |
|---|---|---|---|
| E1 | `:448` | `actions.append(f"await page.goto('{value}');")` —— step 的 `goto` 动词 | 合并 base query 后再发射 |
| E2 | `:621` | `f"  await page.goto('{guard_url}');\n"` —— 元素齐全守卫导航（`guard_url` 定于 `:407`，缺省 = 页面表 `路由`） | 同上 |
| E3 | `:844` + `:1446` | 零步基线 `data = json.dumps({"url": url, …})`（`:844`）→ 运行期 `atlasZeroStepBaseline` 内 `await page.goto(data.url);`（`:1446`） | 同上（否则基线从「带 tenant 但探不到」退化为「连壳都无 tenant」） |
| E4 | `:401` | `def ts_case(case, url)` —— E1/E2 的宿主函数 | 需把 base query 传进来 ⇒ **签名变更**（或走模块级常量），比「一处发射」大 |
| E5 | `:1085` / `:1329` | `base = e2e.get("app_base_url")`；`url = urls[page]` | 取 query 的落点（`urlparse`），供 E1–E3 |

**契约面（`rings/e2e/reference.md` / `shared/stack-profile.md`）**

| # | 位置 | 改什么 |
|---|---|---|
| C1 | `rings/e2e/reference.md:78`（§3.2 表注：「`路由` 以 `/` 开头且全表唯一」） | 说明 `路由` 为**路径形态**、可含 `#`（`#` 紧邻 `/`），宿主 query 由 `e2e.app_base_url` 承载 |
| C2 | `rings/e2e/reference.md:277-288`（§5.5 `会话:`/`守卫:` 块） | 增一条注：`e2e.app_base_url` 的 query = **宿主注入型前提**，生成物负责带到每一跳；与 §5.7 不冲突（参数在 base，不在 step） |
| C3 | `shared/stack-profile.md:90`（`app_base_url` 字段） | 字段语义补一句：可含 query（= 宿主注入前提），生成物转发 |
| C4 | `shared/gates.md:64`（`生成物最新`） | 零变化承诺的看守点，无需改判据；落刀时确认未动 |

**validator 面**：**无需改**（这正是 B′ 相对 A 的核心优势——见下「四处消费者不需要改」验证）。

**被 B′ 前提打坏、RFC 未列的第五消费者**：

| # | 位置 | 问题 |
|---|---|---|
| E6 | `scripts/e2e_console.py:741` | `url = (…get("base_url") or "").rstrip("/") + route` —— 手工项「打开」用**字符串拼接**。base 一旦带 query（B′ 的前提），此式产出畸形 URL：`http://localhost:2000/console/?switchAgent=7202` + `/console/#/…` = `…?switchAgent=7202/console/#/…`。 |

**验证回答：作者说「四处消费者不需要改」——成立。**

逐条机器核（path-form 路由下）：

1. `validators/validate_e2e_index.py:411` 行过滤 `re.match(r"^\|\s*[a-z0-9][a-z0-9-]*\s*\|\s*/", ln)` —— 路由 `/console/#/app/agent/detail` 以 `/` 开头 ⇒ **命中** ⇒ `page_rows` 非空、`goto` 门不空转。✅ 不需要改（与上一轮 MUST-1 相反，因形态换了）。
2. `validate_e2e_index.py:319` `_route_hit` 的 `r != "/" and p.startswith(r + "/")` —— `goto /console/#/app/agent/detail/1` 前缀命中 `/console/#/app/agent/detail`。✅
3. `scripts/gen_e2e_scripts.py:222` `re.match(r"^\|\s*([a-z0-9][a-z0-9-]*)\s*\|\s*(/\S*)\s*\|", ln)` —— `/console/#/…` 以 `/` 开头、`#` 是 `\S` ⇒ 命中，不进 `miss_route`（`:1285`）。✅
4. `scripts/e2e_console.py:141` `cells[1].startswith("/")` —— ✅。

`mock` 的 `context.route`：**不被波及**——`gen_e2e_scripts.py:694` / `rings/e2e/reference.md:363` 明写「pathname+method 命中、**query 天然免疫**」。✅

两个执行入口：`atlas_check`（`E2E 真跑` 门 `shared/gates.md:65`）与 `e2e_console` 的执行走 config `baseURL`（`e2e_console.py:461` 传 `ATLAS_BASE_URL=base_url`），query 随 base 一致 ⇒ **页脚本路径不受波及**；但 `e2e_console` 的**手工「打开」**（E6）受波及。

---

## § 风险与逃逸口

1. **零变化承诺如何保证（Q3）**：B′ 只在「`urlparse(base).query` 非空」时改写发射。生成物是确定性派生件（`gen_e2e_scripts.py:1328-1486` 纯字符串拼装），`shared/gates.md:64` 的 `生成物最新` 门（三态：SKIP / WARN 过期 / FAIL 生成失败）看守派生件。**必须**留一枚 golden 快照钉：base 无 query 的项目生成物对旧版**逐字节相等**（见 §钉与变异 P3）。
2. **调用面外溢（E4）**：合并要进 `ts_case()` 与 `ts_zero_step_baseline()`，这是**共享发射函数**，任何括号 / 缩进漂移会漏到所有项目 ⇒ 零变化钉必须覆盖整页字节，不是仅覆盖含 `goto` 的用例。
3. **ATLAS_BASE_URL 覆盖语义（新）**：`gen_e2e_scripts.py:1540`/`:1566` 用 `process.env.ATLAS_BASE_URL ?? '{base}'`。合并若烘进生成期常量，运行期覆盖会与常量不一致；若走运行期 helper，需从 `test.info().project.use.baseURL` 取 base。**B′ 必须钉死走哪一侧并写明覆盖语义**，否则「改 base 就跑别处」的行为漂移。
4. **逃逸口（Q4）——真缺口**：B′ 让 base query 出现在**每一跳** ⇒ 「验证宿主参数**缺席**行为」的用例**无法表达**。而 `会话:` 写的是 **sessionStorage**（`gen_e2e_scripts.py:614`/`:1423`、`reference.md:279`）、`auth: none` 覆盖的是 **storageState**（`gen_e2e_scripts.py:1083`、`reference.md:193`）——**两者都不在同一消费点**（应用读的是 `searchParams.get('switchAgent')`，RFC §1 ①）⇒ **`会话:` / `auth: none` 不构成逃逸口**。B′ 要么**显式声明**「base query 缺席态超出本项目范围」，要么设计**显式 opt-out**（新键 ⇒ 触 D99，须独立决策行）。作者 §9.2 只写「需显式覆盖（与 `会话:` 的同类边界）」——但 `会话:` 今天也没有 off-switch，类比不成立，**必须补齐决策**。
5. **「同名键以目标为准」是死条款**：§5.7 禁用例 `goto` 带 `?`（`validate_e2e_index.py` `goto 带查询参数` 门）、路由列/守卫也不含 query ⇒ 目标永无同名键 ⇒ 该合并分支**不可达、不可测**。建议删除或改述为「目标若含 query 则为未来扩展保留」，别把它写成已生效口径。

### 与既有裁决的关系（Q5）：**不相抵**

| 裁决 | 关系 |
|---|---|
| `goto 禁带查询参数`（`reference.md:506` / §5.7 `:338`；门在 `validate_e2e_index.py` `goto_param` 段） | **不破**：门打在**用例 step 文本**；生成物内含 `?` 不在其判据内。 |
| `会话:`（D89；`reference.md:277-283`） | 不动；B′ 与它同属「宿主注入型前提」，只是载体是 URL 而非 sessionStorage。**但见风险 4**：两者不可互相冒充逃逸口。 |
| `守卫:`（D90；`reference.md:284-288`） | 不受影响；`guard_url` 仍走页面表路由 / `守卫:`，只是发射前合并 query。 |
| D99（字段集冻结；`DESIGN.md:568`） | **不触**：B′ 不加字段（逃逸口若加则触）。 |
| D103（人工会话；`reference.md:461-463`） | 正交。 |

---

## § 钉与变异（Q6）

| 钉 | 位置 | 断言 | 变异 | 注入 | 预期红 |
|---|---|---|---|---|---|
| **P1 值保真（文本期）** | `tests/test_validators.py` | 分片含 `goto /console/#/app/agent/detail/1` ⇒ `goto 不带查询参数` PASS **且** `goto 路径 ∈ 页面表` PASS；并直测 `strip_inline_comment("goto /console/#/app/agent/detail/1   # 说明")` 保留整段路径 | **M-B1** | 把 `_support/stack_profile.py:45` 判据改为「任何 `#` 都截断」 | P1 红（证明该形态可写性由注释语义守着） |
| **P2 合并真发生** | `tests/test_gen_e2e_scripts.py` | base 带 query ⇒ 生成物**逐字节**含 `await page.goto('/console/?switchAgent=7202#/app/agent/detail/1');`（step 站）+ 守卫站 + 基线 `data.url` 三处 | **M-B2** | 把 `_merge_base_query` 改成 identity | P2 三处齐红（证明三站都被覆盖，非只一处） |
| **P3 零变化** | 同上，golden 快照 | base 不带 query ⇒ 整页生成物对旧版**逐字节相等** | **M-B3** | 去掉「base 无 query 短路」（无条件发射合并/助手） | P3 红 |
| **P4 逃逸口（若采用 opt-out）** | 同上 | 声明 opt-out 的用例生成物**不含**合并 | **M-B4** | 摘掉 opt-out 判定 | P4 红 |

**最低集 = P2 + P3 + M-B2 + M-B3**（「合并真的发生」+「不带 query 零变化」）；P1/M-B1 证明 A 的死因被守住，建议同时上。

---

## § 我不同意（但你有权不理）

1. **不同意「一处发射」**：实为三处导航发射（`gen_e2e_scripts.py:448` / `:621` / `:844`→`:1446`）+ `ts_case()` 签名变更。漏任一处 ⇒ 该跳 tenant 缺席 ⇒ 白屏假红。
2. **不同意「四处消费者不需要改」覆盖全部**：那四处（validator `:411`/`:319`、gen `:222`、console `:141`）**确实不需要改**；但 `scripts/e2e_console.py:741`（手工「打开」拼接）是**第五消费者**，被 B′ 的前提（base 带 query）**直接打坏**，RFC §9.2 未列。
3. **不同意把 `会话:` / `auth: none` 当作「base query 缺席」的逃逸口**：二者所在存储面与本消费点不同，不构成逃逸口；须显式声明超范围或新增 opt-out。
4. **不同意「同名键以目标为准」写成生效口径**：§5.7 下不可达，是死条款。
5. **我未判什么（边界声明）**：
   - **本会话无 shell / write / git** ⇒ **未跑** `gen_e2e_scripts.py --root <tmp> --json` 干跑、**未跑** `pytest`、**未跑** `git`；所有结论为 `file:line` 代码实读，非执行取证。**RFC §9.2 的 URL 合并实测（`new URL` 语义）我未复算**——那是 Node 标准语义，属落刀后真跑验证面。
   - 未判 §1–§8 背景（除作为 B′ 前提的 §9.1 strip 证据外）。
   - 未读 v2 项目侧资产（`product/e2e/*`、`product/stack-profile.yaml`）——属项目数据，不在只读清单。
   - 未判上一轮 REVIEW 已定事项本身的对错（只作基线引用）。
   - 未判 `/Users/sunwenzhe/Desktop/百炼/v2前端`（仅按 RFC §1 引用其事实，未实读）。
