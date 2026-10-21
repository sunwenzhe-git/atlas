# 变更与更新日志 (Changelog)

本文档记录了 **Atlas** 每个版本的重要特性变更、架构治理与问题修复。遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 规范。

---

## [v0.1.0-beta.36] - 2026-10-21

### 🔧 `select` 选项候选集排除内部子节点防假歧义 (D122 补漏)

- **`select` 选项候选集排除内部子节点（D122 补漏）**：`scripts/gen_e2e_scripts.py` 的 `atlasSelect` 候选集追加 `:not([class*="select-item-option-content"]):not([class*="select-item-option-state"])`，排除选项内部子节点，避免无 `title` 属性的 Ant Design 自定义选项内部子元素重复命中相同类名，消除多重命中导致的假歧义（`ambiguous`）报错。

---

## [v0.1.0-beta.35] - 2026-10-21

### 🔧 控制台持窗模式关闭 Playwright 自身 test timeout (D126 / issue #39)

- **控制台持窗模式 `--timeout=0`（D126）**：`scripts/e2e_console.py` 在 `self.keep_open`（持窗模式）下向 Playwright CLI 传递 `--timeout=0`，消除留窗时由于 Playwright 原生 30s test timeout 在 fixture teardown 中超时导致浏览器被强制关闭的问题；控制台的 wall-clock `--timeout` 是唯一超时真相源，自动关窗模式保持原生 30s 兜底防孤儿进程。
- **契约与验证**：契约 `rings/e2e/reference.md` §10.1 与 `DESIGN.md` D126 同步；钉 = `tests/test_e2e_console.py::test_runner_disables_playwright_test_timeout_only_in_hold_mode`，变异 **M127**。

---

## [v0.1.0-beta.34] - 2026-10-20

### 🔧 控制台前置准备钩子环境与前端诊断补齐 (D125)

- **NODE_PATH 同步注入（D125）**：`scripts/e2e_console.py` 调用项目 `product/e2e/scripts/atlas-prepare.mjs` 前置钩子时，若探测到 `nm_dir`，同步注入 `NODE_PATH`，确保前置准备脚本运行环境与真跑子进程依赖解析严格对齐，消除在未自建 `node_modules` 目录下运行时模块解析 `ERR_MODULE_NOT_FOUND` 的缺陷；
- **前端 UI 诊断分流（D125）**：`templates/e2e/console/app.js` 前端 UI 正式消费 `d.prep_failed`：状态 pill 显示为「前置失败」（warn 级），错误摘录与通告显式提示「前置数据准备 atlas-prepare 失败，与用例脚本本身无关」，消除误导使用人员改动用例脚本的假象。
- **契约与验证**：契约 `rings/e2e/reference.md` §10「执行」与 `DESIGN.md` D125 同步；钉 = `tests/test_e2e_console.py` prepare 四元组扩为五元组 + `test_console_app_js_handles_prep_failed_distinctly`，变异 **M126**。

---

## [v0.1.0-beta.33] - 2026-10-20

### 🔧 prepare 用例上下文 / select 候选集 / ESM upload 路径 / 就绪门浏览器判据（D121–D124 / #37 / #38）

- **数据准备钩子传入用例上下文（D121）**：`scripts/e2e_console.py` 调用项目 `atlas-prepare.mjs` 时在子进程环境变量中注入 `ATLAS_CASE_ID`（当前用例 ID），用例级前置不再被迫全局化；
- **`select` 选项候选集扩充（D122）**：`atlasSelect` 候选集追加 `[class*="select-item-option"]`，解决 Antd Select 可见项无 `role=option` 导致的定位超时假红；
- **ESM 项目 upload fixture 路径修复（D123）**：`type: "module"` 项目的 `upload` 发射 `import.meta.url` 路径解析，消除 `__dirname` 未定义异常；
- **E2E 就绪门补浏览器判据（D124 / #38）**：增加 `_support/pw_runner.py::probe_browser` 探测 Chromium 浏览器在场；`atlas_check` 真跑门缺浏览器时明确 FAIL 并指名安装命令 `npx playwright install chromium`，`e2e_console` 起跑前诚实拒绝。

---

## [v0.1.0-beta.32] - 2026-10-19

### 🎯 同名多实例元素序位下标支持（#31，D120）

- **步骤动词与断言动词多实例序位 `[N]` 支持（#31）**：`scripts/gen_e2e_scripts.py` 全面支持目标 testid 带 `[N]` 下标语法（0 起始，如 `click list-btn[1]`、`fill input[2] val`、`visible item[1]`），发射为 Playwright 原生 `.nth(N)` 定位器；省略下标时保持缺省 `.first()` 语义（100% 向后兼容）；
- **生成物 helper 同步适配**：`atlasSelect`、`atlasExpectValue`、`atlasDownload`、`tsLoc`、`tsVis`、`tsVisible` 等生成物 helper 同步适配 `nth` 参数；
- **校验门无缝对接**：`validators/validate_testids.py` 的 `case_testid_usage` 自动剥离 `[N]` 下标，双向集合门与应然落点门无缝对接基准 testid。

---

## [v0.1.0-beta.31] - 2026-10-19

### 🩹 自感知缺陷与工件健壮性一揽子修复（#25 / #27 / #28 / #29 / #30 / #34 / #35，D119）+ 等待超时上限口径统一（D118）

- **等待超时上限口径统一（D118）**：页面就绪锚点（含 `waitFor`/`download`/`select` 就绪轮询）等待上限与断言侧统一抬升为 20s（`ATLAS_WAIT_TIMEOUT_MS` 缺省 20,000ms），支持环境变量覆盖；消除慢页面首屏就绪超时被误报的假红。
- **登录预置深度取值与 JSON 支持（#35）**：`atlas-auth.setup.ts` 令牌键取值改用点号路径解构，彻底解决嵌套响应体（如 `data.token`）取到 `undefined` 击崩浏览器 context 的缺陷；`app_login` 支持可选声明 `body_format: form | json`；登录异常与非法响应统一拦截并保护存量 `state.json`。
- **测试目录与文件过滤（#27/#33）**：`validate_testids.py` 扫描过滤 `__tests__`、`test`、`tests`、`fixtures` 等目录及 `*.test.*`、`*.spec.*` 文件，明确测试代码不是页面声明处，消除全站重复假红。
- **应然先行落点门分档（#34）**：未实现页面的未落地落点降级为 `WARN`（先行设计待落地），正向前置设计不再被误判为 `FAIL（虚假陈述）`；翻档为已实现后严格保持 FAIL 严判。
- **域级 PRD 核心资产门（#29）**：`validate_prd.py` 增加对域级 PRD 核心资产（二、四、五章及结构类 AC 清单）的机器存在性严判，杜绝空壳域 PRD 假绿通道。
- **结构环事实载体解绑根 README（#25）**：`_meta.json` 引入 `truth_carriers`，支持语义别名与自解释注释，解绑根 README，适配 Agent-first 存量项目。
- **存量零 testid 三步推进链（#28）**：契约明确责任方与推进链，利用现成索引中的 `blocked` 状态与 Playwright 原生 `test.skip(reason)` 隔离待埋点状态与业务真失败。
- **独立审查 executed 标记与控制台守卫（#30）**：`review.json` 引入 `executed: boolean`；`e2e_console.py` 的 `snapshot()` 在读索引前增加存在性守卫，抛 `SnapshotError` 防线程崩溃。

---

## [v0.1.0-beta.30] - 2026-10-19

### 🧷 执行串行落门（D115）+ `attr` 空值形态（D116）+ `select` 就绪门按命中态轮询（D117）

- **执行串行落门（D115）**：契约 §7.1 新正文条「用例执行必须串行（并发 = 1）」（跨域并行仅在声明独立靶场时允许）；`atlas_check` 增常驻门「执行串行」——config 缺 `workers: 1` 或 `fullyParallel: false` ⇒ FAIL（逐判据隔离：只破任一都红）；生成器注释出处 `§8` → `§7.1`。变异 MD115a/MD115b 均红。
- **`attr` 空值形态（D116）**：新增 `""` / `(空)` 写法 = 断言「该属性**缺席或为空串**」，补「否定属性」表达面；缺席属性 `getAttribute` 返 `null` 非 `""` ⇒ `toHaveAttribute(name, "")` 是半通状态，发射改 `?? '').toBe('')` 走 `expect.poll`（与探针同形单源）；非空期望逐字节不变。变异 MD116 红。
- **`select` 就绪门按命中态轮询采样（D117）**：原全局候选集 `attached` 就绪门会被页面常驻 `[role=menuitem]`（顶部导航）秒满足 ⇒ 采样落进下拉零盒窗口，现场 `--repeat-each=3` 稳定 2 红。改为 `expect.poll` 轮询三值 `status`：0 命中 = 未就绪轮询至上限、>1 命中 = 歧义立即拒绝、唯一才点（D112 语义不变）；不引入固定等待；被否锚 `aria-owns`（只部分组件族成立）。变异 MB16 红；钉按三值形态重构 D112 原钉。
- **取证**：全量 **519 passed / 4 skipped**；`DESIGN.md` 三决策行；契约 `rings/e2e` §7.1 + §5.5 同步。

---

## [v0.1.0-beta.29] - 2026-10-19

### 🧲 守卫单段化修正：删去「纯在场声明」运行期段，退回单段页面就绪锚点 (D114 v2 修正 / issue #26)

- **背景（现场回灌，首版发布后当天即证伪）**：beta.28 第 ② 段 `guard_only` 与静态双向集合门相抵——「声明但不操作 / 不断言」是该门唯一合法补全形态，对这类 id 在 `goto` 时刻再要求运行期在场 = 两条合法用例在守卫处死锁（`Expected 1 / Received 0`）。
- **修正**：守卫 = **单段页面就绪锚点**（全量声明清单、`expect.poll`、超时点名整份清单）；被 step 触达的由原生自动等待承接、被 expected 触达的由断言轮询承接；**「仅声明」的 id 只参与静态校验，不承担运行期在场义务**。
- **取证**：原拆段钉替换为 `test_guard_is_anchor_only_and_never_backfills_presence`；变异 **MD114** 三枚钉红、还原逐字节一致；全量 **516 passed / 4 skipped**。登记：`rings/e2e`、`DESIGN.md` D114 行修订。

---

## [v0.1.0-beta.28] - 2026-10-19

### 🧲 元素齐全守卫拆两段：「页面就绪锚点 + 纯在场声明」，动作产物元素改由自动等待承接 (D114 / issue #26)

- **病灶**：守卫面 = 用例 `testid:` 全量清单（#R2）后，动作产物元素（初始态必然 0）在未执行任何 step 前即死锁 ⇒ 契约只能指向实现侧 `hidden` 占位槽，衍生三条隐式约定；次生 `count` 断言被迫写「真实数 + 1」、残留被折叠成「页面未加载」。
- **定案**：守卫拆两段——① `atlasAwaitAnyDeclared` **页面就绪锚点**（任一声明 id 在场即页面已渲染，`expect.poll` 轮询、超时点名整份清单）；② `guard_only` = `testid:` −（step 目标 ∪ expected 目标）仍逐个 `toHaveCount(1)` 严判；已触达的 id 由各自的原生自动等待承接。守卫面不会退化为空表 ⇒ **不再需要 hidden 占位槽，count 断言回到纯业务数**。
- **兼容**：存量占位槽不强制回退，对存量生成物增量可用。
- **取证**：钉 86 条（`test_guard_splits_anchor_from_presence_only_ids`；#R2 三枚旧钉按新形态重构）；变异 **MD114** 三枚钉红、还原逐字节一致；全量 **516 passed / 4 skipped**。登记：`rings/e2e` §7.1、`DESIGN.md` D114。

---

## [v0.1.0-beta.27] - 2026-10-19

### 🔧 testid 双向集合门的「动态名」诊断：文案与应然集合口径对齐 + 判据由词形改结构 (D113, M96/M97)

**背景**：`validators/validate_testids.py` 的「分页双向集合相等」门在 FAIL 时附带的诊断宣称「动态列表项如 `*-item` 切勿列入用例 `testid:` 块，**仅在 step/expected 中引用即可**」——但该豁免自 2026-09-25（§B40/§B64）起已不存在：`shard_testids` 的用例侧集合 = `testid:` 声明 ∪ `step`/`expected` 派生，**两侧都进同一门**，照建议操作仍判「缺失」。且触发判据为词形启发式（缺失名含 `item` 子串）：同类 `` `<prefix>-<运行期序号>` `` 不触发（漏提示），而名字恰含该子串的真漏实现反被附上错指引（错提示）。

**定案**：只修诊断、**判定强度零变化**。① 文案改指契约 §4 已给的正规形态（容器 + 计数 / 稳定样例行 / 类型级静态名）；② 判据由词形改为**结构**——取源里模板 testid 的**结构模式**（`${…}` → `.+?`、字面段 `re.escape`；只保留字面总长 ≥ 3 的模板，避免退化成 `^.+?$` 匹配一切）；③ 收集走 `collect_testids_expanded` 的**可选出参**（不动返回元数：该 5 元组已被 4 处调用方按位解包）。

**被否**：用「静态前缀」当判据（模板以 `${slug}` 开头时前缀为空，而这恰是最常见形态 ⇒ 判据恒不触发）；真开「按序号寻址」的豁免通道（削弱静态门——模板整段删除后不再报红；且当前无具体需求，缺口已上报上游 issue #24）。

**钉与变异**：`tests/test_validators.py` +2；变异 **M96**（整段回退旧诊断 ⇒ 钉子红）/ **M97**（只退判据为词形子串 ⇒ 钉子红），四段协议通过、还原逐字节一致。

---

## [v0.1.0-beta.26] - 2026-10-19

### 🎯 `select` 动词的选项定位：由「可访问名全等」改为三级降级 + 命中不唯一即拒绝 (D112, MB14/MB15)

**背景**：`atlasSelect` 在非原生分支发射 `getByRole('option', { name: label, exact: true })`——即「可访问名**全等**」。而组件常把描述文案塞进选项内（ant Select 的标准用法）⇒ 选项的可访问名 = **标签 + 描述**（现场实测 `文本对话基于LLM的对话型交互，适合进行复杂的多轮对话`）⇒ 全等恒不命中，用例卡在 **30s 定位超时**（不是断言失败，现场看不出真因）。

**定案**：
- **三级降级定位**：① `title` 属性全等 → ② 可见文本前缀 → ③ 名称包含。
- **候选只取几何可见元素**（`getBoundingClientRect()` 非零），hidden 选项不参与匹配。
- **命中数 ≠ 1 ⇒ 拒绝**并抛出「列出可见选项」的错误——**宁可响亮失败，也不 `.first()` 静默选错项**（某标签是另一标签前缀时，单档包含匹配会选错 = 假绿通道）。
- **原生 `<select>` 分支不变**（`selectOption({ label })`）；语义仍是「在该控件上选中 label 的那一项」，DOM 机制不进契约。

**钉与变异**：`tests/test_gen_e2e_scripts.py` +1（五条判据）；变异 **MB14**（摘掉唯一性拒绝）/ **MB15**（把 `exact: true` 写回发射），两枚四段协议通过、还原逐字节一致。

**装配**：咬合点 = 下一次 `install.sh --update`。

## [v0.1.0-beta.25] - 2026-10-18

### 🧩 E2E 执行面两案：用例前数据准备钩子（D110）+ refresh 落盘节拍参数化（D111）

- **用例执行前自动执行项目数据准备脚本（D110，`scripts/e2e_console.py`）**：项目自带 `product/e2e/scripts/atlas-prepare.mjs` ⇒ 每条用例先跑它（cwd = 项目根，180s 上限、不计入用例超时窗）；失败 / 超时 ⇒ **拒绝执行该用例**并按 `done` 事件完整形状（`prep_failed: true` + tail）如实上报。把「清零 → 静置 → 复跑」净场协议从人工纪律落成执行器机制，杜绝有状态靶场残留实体造成的 count 类断言系统性偏移。
- **refresh 落盘节拍参数化（D111，`scripts/gen_e2e_scripts.py`）**：`refresh` 发射**先等后刷**两行——`ATLAS_REFRESH_SETTLE`（默认 0）注入的 `waitForTimeout` 先于 `page.reload()`，节流型自动保存项目运行时给落库等待窗。默认 0 ⇒ 行为不变；毫秒数属项目侧运行时前提（对齐 `ATLAS_SLOWMO` 注入先例），非 §5.5「固定 sleep」禁令所指。
- **登记**：`DESIGN.md` D110/D111；契约正文 §7.1 / §5.5；钉 2 条 + 变异 M94/M95（四段协议）；全量 **512 passed / 4 skipped**。

---

## [v0.1.0-beta.24] - 2026-10-18

### 🧭 逐用例宿主注入 URL 参数通道：`goto` 查询门重靶 + 项目级白名单 (D109, MB12/MB13)

**背景**：`会话:`（D89）只解决 **sessionStorage** 那一个消费面；而某类应用的被测参数**只从载入地址的常规查询串读**（`window.location.search`）⇒ 契约内**无合法写法**（`goto` 带 `?` 是硬 FAIL、`auth` 只管登录态、`seed:` 绑数据实体）。D104 ① 已记下这条「三条各自成立 ⇒ 无合法写法」，当日改选 B′（base query 全局转发），把「`会话:` 扩 URL 参数档」列入被否清单。采用方现场（2026-10-18）：两条用例被迫写成同一前提（都走 sessionStorage）⇒ **重复**，查询串那一面**零覆盖**。

**重靶取证（本次的依据）**：原门（§5.7，2026-09-23；事故 `3509 §B20` = `E2E-LOGIN-003` 断言 `?state=forbidden` 演示横幅自身的文案）的**靶子随 E1 原型环退役而消失**——`?state=` 只出现在 `DESIGN.md:460` 的**已作废**决策行（D8 两段式 / D56 原型交互分级）；E1 后无任何决策行重新论证该门；`bugs.md` 与 `CHANGELOG.md` 零起该门事故；今日它的身份是「无合法写法」的**阻碍** = 制造成本。该门今日真正剩下的是**另一族**纪律「前置数据态只能用真实界面动作达到」，而这族边界在重靶前后都由**项目级白名单**守，与「`goto` 带不带 `?`」无关。

**定案**：
- **门重靶**：`goto 不带查询参数` → **`goto 查询键须已声明`**（键须 ① ∈ `e2e.query_preset.keys` ∧ ② ∈ 本用例 `参数:`）。**原靶仍在 FAIL 面内**：未声明键照样红。
- **新字段 `参数:`**（用例块，可选）：**只声明键**；值内联在 `step` 的 `goto` 查询串里（单一来源）。**守卫导航取该用例首个带参 `goto` 的查询串**——否则守卫读的是无前提的 DOM。
- **并集档转正**：`_support/url_merge.merge_base_query` 的「目标自带 `?` ⇒ 原样返回」暗位（原注释写着「§5.7 下不可达，为未来扩展留位」）改为 base 与目标 query **求并集**（base 在前、**同键 ⇒ 用例胜**）；既有生成物无一带 query 的 `goto` ⇒ **零回归**。
- **三道新门 + 生成期同源中止**：`参数 声明有效`（纯键 / 去重 / 白名单 / 防死声明）、`参数 值形态`（URL 安全集——生成物是 `page.goto('<url>')` 的**单引号拼接面**）、`会话`·`参数` 同键不叠写。
- **被否**：值只写 `参数:` 行而 `goto` 保持无 query（其「保住 §5.7 事故防护」的立论取证后作废，取舍只剩成本与表达力，B 胜）。
- **边界（如实登记）**：允许带白名单查询串后，「数据态直达」那族纪律的**机器面只剩白名单本身**——与 `会话:` 同族、是本设计的本来形态，登记以防后人以为还有别的网在兜。

**钉与变异**：`tests/test_validators.py` 116 → **123**；`tests/test_gen_e2e_scripts.py` +6；变异 **MB12**（并集档退回「原样返回」⇒ 单元钉 + 守卫承载钉齐红）/ **MB13**（守卫不追加用例参数 ⇒ 守卫面钉红），两枚四段协议通过、注入 diff 存档。

**装配**：咬合点 = 下一次 `install.sh --update`（契约与生成器同批生效）；派生件无 query 的既有用例**逐字节零变化**。

## [v0.1.0-beta.23] - 2026-10-18

### 🎞️ E2E 真跑失败自动留证：trace / screenshot 只在失败落盘 (RFC-20261018-01, D108)

- **两轨同构补两键**：生成物 `playwright.config.ts`（python 轨 / node 轨）的 `use:` 各补 `trace: 'retain-on-failure'` + `screenshot: 'only-on-failure'`——失败现场自动落 trace（DOM 快照 + 网络 + 操作日志，逐帧回放）与截图到 `test-results/`，**全绿轮零新增构件**；无覆盖口（防「成功轮也留证」开后门）。
- **不溯及已装配副本**：咬合点 = 下一次 `install.sh --update` / 首装重装配；重装配前「契约已声明留证而现场无 trace」属如实态、非缺陷，巡检不得误报。
- **留证含业务内容**，只落采纳仓本地、不进 atlas 上报通道（§15 出站面不破）；不解决 D103「人工会话取出 ⇒ CI 不可复现」盲区（真身是登录态）。
- **被否**：`video` 缓行（trace 自带回放器）；全量常录 `on`；失败自动重试 N 次（防复读机裁决已落 `duty-review/QUEUE.md` 归档区）；托管云沙盒会话。
- **接线与取证**：契约条 = `rings/e2e/reference.md` §7.1；门行 = `shared/gates.md` 2.2；决策行 = `DESIGN.md` D108；钉 3 条（双轨同构 / 值形态封闭 / 无覆盖口）+ 变异 **MB10/MB11** 四段协议双绿；全量 **497 passed / 4 skipped**。评审轮记（两轮）= `proposals/RFC-20261018-01`；观察室 +3（键盘三态原语 / 目录化扩展 / 上报机检增强）。

### 🔧 E2E 真跑：node 轨运行器判据换本体（D101；issue #24）

- **判据本体更换**：从「可执行文件存在」改为「从 `e2e.scripts_dir` 出发 `@playwright/test` 可解析」（对齐 `shared/gates.md` 2.2 行早写明的「按依赖可导入性，不按路径存在」）。背景 = 百炼/v2前端现场：ESM 项目（`"type": "module"`）下 Node 的 ESM 解析器**不读 `NODE_PATH`**，全局兜底找得到 binary、解析不到模块 ⇒ 错误落到运行期并被门计成「跑失败 / 无结果」。
- **单源内核 `_support/pw_runner.py`**：二进制解析 / 探针 / 修复收敛到一处，消除 `atlas_check.py` 与 `e2e_console.py` 的两份拷贝（含两份 `_is_node_playwright`）。
- **全局兜底改为可生效的修复**：补**幂等软链** + 复检，并输出「用了全局什么」；门侧降 `WARN`、不可修复 ⇒ `FAIL` 点名；项目自装缺模块不修只报；链接位被占拒绝覆盖。
- **取证**：`pytest tests -q` ⇒ **476 passed / 4 skipped**（基线 472）；`test_atlas_check.py` 24 → **25**、`test_e2e_console.py` 9 → **12**；变异 M88/M89/M90 三枚咬合、还原逐字节一致；`install.sh` 自检 44 → **46**（含顺手补的 `_support/case_id.py`）。

### 📋 复发自动可见（DR4 口径 B）+「可执行性判据本体」写成流程门（D102；承接 issue #24）

**背景**：D101 那条属「**判据可被形态满足**」族（`#1/#4/#6/#7` 首批 beta.17 已修一轮，`#20` / `#24` 两轮复见）。而 DR4「同类 ≥3 次 ⇒ 需立机器门**或契约条款**」此前**全凭人工裁量**——族规模没人算、复发靠撞见。维护者 2026-10-17 拍板选项 **B**：两件都做。

- **口径 B（族规模）**：实现 = **单源模块** `duty-review/families.py`（原稿是 shell 内联 python —— 无钉、形状一漂即**静默归零**，而静默归零恰好让本机制要治的「复发靠撞见」原样回来），`scripts/duty_signals.sh` 只读调它。聚类单元 = `duty-review/bugs.md` 的段 + 段首「同根归纳」行，计数 = 段内 `#NN` 去重（上界近似），**升室判据 = 同根归纳在案 ∧ 案数 ≥3 ∧ 段内最近日期在近 30 天**；只满足前两项 ⇒ 记「族已静默」不升室（防同一族清算完还天天喊 = 红灯训练成噪声）。与既有**口径 A**（fix 类提交触达路径 30 天 ≥3，判**复发速率**）互补。实跑 = **3 族升室候选**（E2E 14 案 / 安装与装配 3 案 / 自感知 8 案）+ **1 族自动静默**（structure）。新增 `tests/test_duty_bug_families.py`（4 条：解析面 = 文件面 / 真实库数得出族规模 / 判定真值表 + 活跃窗边界 / 空输入不炸），变异 **M91**（计数正则退回行首 ⇒ 静默归零 ⇒ 钉红）；全量 **480 passed / 4 skipped**、测试文件 32 → **33**（gates 计数行同步）。
- **契约条款（语义项，明示不设机器判据）**：`shared/gates.md` 2.5 新增「**可执行性判据本体**」流程门——判据必须问「**能不能真的用**」，不得以「东西在不在 / 文字写没写」代替；这类前置判据须具备 ① 一次性功能性探针（真跑一次：import / `--list` / dry-run）② **反面包**（东西在、但用不了 ⇒ 必须红）③ 失败原因不得被吞。附同族先例六条与人工追问清单三条。
- **为什么不做通解**：判「判据 ≠ 性质」要读意图 ⇒ 语义，机器判不了；硬立通用门 = 用可被形态满足的门治可被形态满足的病（同族递归）。该族复发**都发生在老门老代码上**（纪律只覆盖「新增/修改门」那一刻）——机器门治不了「没人回头看」，故本决策只做「让复发被看见 + 给写门一把尺子」。
- **登记面**：`DESIGN.md` D102 / `shared/gates.md` 2.5 / `duty-review/README.md` §2+§4 / `scripts/duty_signals.sh` / `duty-review/bugs.md`（自感知段补「同根归纳」锚行——此前该族无锚，只能靠 E2E 段虚高计数间接看见）。

### 🪲 「E2E 真跑」门：标量取值剥行内注释（issue #25；D94 ③ 残余的现场实证）

**现场**：百炼/v2前端全量门（重装配到 D101 后首跑）—— `e2e.reset 失败（exit 127）：/bin/sh: null: command not found`。`stack-profile.yaml` 写的是 `reset: null   # 真跑前靶场重置 shell 命令串`（**合法 YAML**：`#` 前有空白 ⇒ 行内注释），门把注释整段当值去执行 ⇒ **假红，且在跑到用例之前**（真跑还没开始，「谁红、为什么红」两件事一起被错认）。

**修法**：`scripts/atlas_check.py` 的 `check_e2e` 四处标量取值（`cases_dir` / `app_base_url` / `reset` / `node_modules`）统一过内核 `strip_inline_comment`（与 D94 **同一函数对象**；本文件首次引入该内核依赖）。此前四处各用正则直取 ⇒ 正是 D94 ③ 明写「其余文本期门仍在本次收敛面之外，登记为残余」的那一类。

**钉与取证**：`tests/test_atlas_check.py` 25 → **27 条**（双侧：注释不得污染取值 ⇒ `reset: null # 说明` 不执行；真写的发令必须照发 ⇒ `reset: echo …` 落文件 —— 防「把门修哑」）；变异 **M92**（四处取值退回 `m.group(1)` ⇒ 红，还原逐字节一致）；`pytest tests -q` ⇒ **482 passed / 4 skipped**。

**残留（仍开，非本批）**：全源包其余剥注释站点未收（`validators/validate_e2e_index.py` 10 处手写 `split("#",1)[0].strip()` 等）⇒ D94 ③ 的待办**部分**清偿、未字面全真；**新增观察**：`reset` 取值清洗用 `.strip("\"'")`（两端同时剥，非「剥成对引号」）⇒ 结尾带引号的合法发令会被吃一个字符（无现场证据，未改，登记备查）。

### 📋 `e2e.app_login` 不开第四形态：不可自动预置的靶场走「人工会话取出」**描述路径**（D103；issue #26）

**现场**（百炼/v2前端真跑准备日）：靶场**有访问门**但三态**都装不下** —— 图形验证码（`login_captcha`）+ 服务端 **cookie 会话**（`COOKIE_JSESSIONID`）+ 登录**响应体无令牌**（`data` 是 URL 串）；而 `validate_stack_profile` 只喊「请声明」⇒ **死胡同**（真跑门已能跑到用例，三条红全在未登录态）。

**定案（维护者拍板原话）**：「我想让 ai 主动给人生成这种类似的命令，然后登录完就完全没问题了」+「不用非要机器门吧，描述不是也可以」⇒ **不加字段、不加门**，落**描述 + 出路文案**：

- `rings/e2e/reference.md` §7.1 增「**人工会话取出（描述路径，非机器门）**」节：AI 主动给人 `playwright codegen --save-storage=<e2e.scripts_dir>/.atlas-auth/state.json "<e2e.app_base_url>"`，人登录一次；**四条纪律** = 关窗才落盘 / 会话短命令要**立即**跑 / `<scripts_dir>/.gitignore` 已含 `.atlas-auth/` 且生成器 setup 有**幂等守卫**（无凭据 + 已有合法 state ⇒ 保留，不覆盖人的会话）/ 它是**运行期凭据不是应然资产**。
- `shared/stack-profile.md` §2：`app_login` 行注明「**三态之外不设第四态**」。
- `validate_stack_profile` 的 WARN：由「请声明」改为**给出路**（含命令原型）；钉 `test_stack_profile_login_unstated_warn_gives_a_way_out`（`tests/test_validators.py` 112 → **113 条**）+ 变异 **M93**（把出路换成一句空话 ⇒ 红；还原逐字节一致）。
- **对 D80 ② 的注记（显式登记，不静默）**：D80 的「段缺失不再是合法降级 ⇒ 升档 = `not_ready: app_login`」与本行**相抵于一类项目**（有门但无形态可声明）——该升档落地时**须先把这一类排除**，否则会把「如实未声明」罚成 `not_ready`（`shared/gates.md` 2.2 行已登记该相抵点）。

**被否**：补第四形态 `manual`/`session_import`（契约增量四处同改 + 把**不可复现**固化成标准姿势）；把这类靶场塞进 `real`（一个形态说两件事）；用 `mode: none` 充数（与事实相反）。

**能力边界（不得 oversell）**：该路径**不可复现**（每轮要人登录 ⇒ CI 上不可用）、会话短命 ⇒ 是**兜底**而非 `app_login` 的替代形态；**无机器判据**，如实登记为纪律与盲区面。

**取证**：`pytest tests -q` ⇒ **483 passed / 4 skipped**。

### 🪲 变异证明**证据形态**补强：报告必须含注入 diff（独立评审驱动；M88/M90 复验）

**来源**：`proposals/REVIEW-2026-10-17-source-batch.md`（独立评审，干净上下文）判「同批 M88/M90 的变异证据**不足以支撑自述机制**，全批缺注入 diff ⇒ 独立复现性不足」。本条只动**证据面**，不动任何判定逻辑。

- **工具**（`scripts/mutation_proof.py`）：报告新增 **`## 注入 diff`** 段（`injected_diff()`，`difflib` unified diff ±3 行）——没有它，「反向破坏的是不是自述那一处」无法独立复现，证据止于作者自述。四段协议不变。
- **M88 复验（红因错位已修）**：原报告红因实为**夹具假 `Proc` 缺 `stderr`** ⇒ `atlas_check.run()`（`:122`）崩，**从未触到 status 断言** ⇒ 钉子会响但机制未被证明。六处假 `Proc` 补 `stderr=""` 后重跑：红因已对齐为「status 仍 `FAIL`、但 detail 退化成『无结果』」= **判据被绕过导致真原因丢失**本身。
- **M90 复验**：断言补具名消息（原为空 `AssertionError:`），报告现含注入描述 + diff ⇒ 与 M89 共用用例但**注入面不同**，可辨。
- **M88–M93 六枚全部带 diff 重跑**：`/tmp/atlas-mutation-2026-10-17/`（每份含原/后 sha256 + 基线 + **注入 diff** + 注入后 + 还原后）。
- **钉**：`tests/test_tools.py::test_mutation_proof_happy_path` 补三条断言（报告含 `## 注入 diff` / `-ok` / `+bad`）⇒ 工具能力不会静默丢。
- **登记面**：`shared/gates.md` 2.5「变异证明」行（查什么 + 假绿测试列）与 2.2「E2E 真跑」行（复验注记）。
- **取证**：`pytest tests -q` ⇒ **483 passed / 4 skipped**。

### 🔧 E2E：宿主注入型 base query 由生成物转发（D104；issue #27；两轮独立评审后落刀）

**病灶**：某类应用把宿主注入的前提（tenant）**只从 `window.location.search` 读**（无 sessionStorage 回落）⇒ `会话:` 通道（D89，sessionStorage）**送不到**；`goto` 又不得带 `?`（§5.7）；而 base 一旦带 query，**绝对路径会丢 query**（`new URL('/console/#/x', '…?switchAgent=7202')` ⇒ query 消失）。三条各自成立 ⇒ 无合法写法 ⇒ 真跑导航落到「请选择业务空间」，白屏假红。

**两轮评审**：`proposals/REVIEW-2026-10-17-source-batch.md`（2 MUST / 5 SHOULD）+ `proposals/REVIEW-2026-10-17-Bprime.md`（10 MUST / 2 SHOULD / 3 OBSERVE）。

- **第一案 A 被落刀实测推翻**：让路由列允许 `#/…` 相对形态（`new URL('#/x', base)` 能保住 base 的 path+query），但 `.atlas-case` 里 `goto #/…` 的 `#` 前有空格 ⇒ 按 D94 行内注释语义被截断成 `'goto'`（`守卫:` 标量同样）⇒ **物理不可写**；救它要改 D94 刚收敛的共享注释语义（`proposals/RFC-20261017-01` §9.1）。
- **定案 B′（评审建议的生成期纯函数变换，不是运行期助手）**：路由列保持**路径形态**（`/console/#/app/agent/detail`，`#` 紧邻 `/` ⇒ 不被注释吞）⇒ 上一轮评审的四处消费者**无需改**；改由**生成期**把 base 的 query 并进**三处**导航发射面（step `goto` / 元素齐全守卫 / 零步基线 `data.url`），单源 = 新增 `_support/url_merge.py`；控制台手工「打开」（**第五消费者**）的 `base + path` 拼接同步修正为 `origin + 合并路径`。
- **口径三条**：base 无 query ⇒ 生成物**逐字节零变化**；`ATLAS_BASE_URL` **只覆盖 host、不覆盖 base 的 query**；**边界明示**——base query 成为前提后，「它缺席时」的行为无法用同一份用例表达（`会话:`/`auth: none` 不同消费面，不构成逃逸口），要 opt-out 须另起决策行（触 D99）。
- **落刀现场补一处（D104 ⑦，D94 ③ 残余清偿）**：step 的 `goto` 曾丢 hash 段 —— `parse_line` 用 `line.partition("#")`（任何 `#` 都截断，D94 ② 的列表项例外），路径形态 `/console/#/…` 被砍成 `/console/`；改走内核 `strip_inline_comment` 后值保真、尾随说明照剥（改判 D94 ② 该例外，旧行号 + 新证据已登记）。余两处 `partition("#")` 无现场证据、未动。
- **钉与变异**：值保真（含列表项）/ 三处齐并 / 无 query 零变化 / 控制台绝对地址；变异 **MB1/MB2/MB3/MB4** 四枚咬合、还原逐字节一致（报告在 `/tmp/atlas-mutation-2026-10-17/`，含注入 diff）。
- **取证**：`pytest tests -q` ⇒ **487 passed / 4 skipped**；`install.sh` 自检 46 → **47 条**（+`_support/url_merge.py`）。
- **登记面**：`DESIGN.md` D104 / `rings/e2e/reference.md` §3.2 + §5.5 / `shared/stack-profile.md` §2 / `shared/gates.md`（`生成物最新` 零变化钉 + 2.2 真跑行）/ `duty-review/bugs.md` #27。

### ⏱️ E2E 断言超时下限：生成的运行器配置必须声明 `expect.timeout`（D105；issue #28）

**现场**（#27 落地后）：三处导航 URL 全对、元素**真在**（探针实测 `disabled=true` + 合规 `aria-label`），真跑仍 `3 failed 1 passed`。根因 = 生成的 `playwright.config.ts` **没有 `expect` 段** ⇒ 继承 Playwright **默认 5s**，而该应用首屏实测 **14,184 ms**（dev bundle 13.8MB）⇒「元素还没渲染」被误判成「元素不存在」= **假红**。

- **定案**：生成器在两处 config 分支发射 `expect: { timeout: Number(process.env.ATLAS_EXPECT_TIMEOUT ?? 20_000) }`。
- **它不是「固定等待」**：`expect` 是轮询式 auto-wait，本改只抬**上限**（不引入 sleep，不破 §5.5 禁令）。
- **被否**：只给守卫加 timeout（其余断言仍 5s）；调 test 超时（兜底不解决断言级假红）；固定 sleep（契约明禁）。
- **代价（如实）**：真失败从 5s 变 20s 才红；慢环境可用 `ATLAS_EXPECT_TIMEOUT` 调低。
- **钉与变异**：`test_runner_config_declares_expect_timeout_floor` + 变异 **MB5**（摘发射 ⇒ 红，还原逐字节一致）。
- **取证**：`pytest tests -q` ⇒ **488 passed / 4 skipped**。

### 🧭 E2E 执行入口的 cwd 口径统一：真跑门改以 `<scripts_dir>` 为 cwd（D106；issue #29）

**现场**：#27 / #28 落地后真跑仍 `3 failed 1 passed`，而**同一份产物** `cd scripts` 直跑 **8.2s 全绿**。差异 = **cwd**：生成物里的相对路径（`storageState: ".atlas-auth/state.json"`、`outputDir: ".atlas-run"`、mock fixture）**全是 cwd 相对**的，`atlas_check` 却用 `cwd=项目根` + `-c <相对路径>` 跑 ⇒ storageState 被解析到 `<root>/.atlas-auth/`（**并在那儿写下空 state**，实测 `{"cookies":[],"origins":[]}`）⇒ 读不到人工会话 ⇒ 未登录态跑用例 ⇒ 断言等满 20s **假红**。控制台本来就是 `cd scripts` 再跑。

- **定案**：真跑门改 `cwd=<scripts_dir>` + `-c playwright.config.ts`（与执行器同一口径）；契约侧新增「**执行 cwd（硬）**」条。
- **被否**：把生成物相对路径改成绝对路径（派生件带机器绝对路径 ⇒ 不可移植、破「生成物 = 确定性派生物」）；只修 setup 的 state 路径（其余相对路径仍漂）。
- **教训（写进 D106 ④）**：**「同一产物在两个入口下跑出不同结论」先查 cwd / 环境**，否则会把执行器差异误判成用例或实现缺陷（本轮先误判为超时不足——由 D105 兜住超时面——再查出真因）。
- **钉与变异**：`test_check_e2e_runs_with_scripts_dir_as_cwd`（截 `run()` 的 (cmd, cwd)）+ 变异 **MB6**（退回 root ⇒ 红，还原逐字节一致）。
- **取证**：`pytest tests -q` ⇒ **489 passed / 4 skipped**。

### 🧪 零步基线的每个探针必须「缺席即判不成立」（D107；issue #30）

**现场**：`atlas_check --page app-agent-detail` ⇒ 两条真用例全绿，唯零步基线 `Test timeout of 30000ms exceeded`。带参页面的页级路由本就不渲染详情（`D104` 允许的形态），而 `attr` 探针发射 `getByTestId(t).first().getAttribute(n)` —— **没有 `count()` 守卫**，Playwright 对**未挂载**元素的 `getAttribute` 会等到默认超时 ⇒ 4 探针 × 2 趟撑爆 test 预算。契约 §5.5 早已明写「基线探不到元素按 `null = 不成立` 处理」⇒ **等挂载 = 违约**。

- **定案**：`attr` 探针加 `count() > 0 &&` 前置（缺席 ⇒ `false` = 不成立）；并升为**生成器通用不变式**：任何探针表达式都必须带缺席守卫（`count()) > 0` / `tsVis(` / `tsVisible(` / `atlasValueOf(`）。
- **被否**：加大 test 超时（把等挂载合法化）；带参页面跳过基线（§5.5 已选择回 `null`）；只在项目侧声明 `守卫:`（那是资产选择题，不修 atlas 违约面）。
- **钉与变异**：`test_zero_step_probes_never_wait_for_attachment`（对**全部**探针做通用守卫检查）+ 变异 **MB7**。
- **出库**：探针行为属**运行面** ⇒ 待下一轮真跑复验后出库。
- **取证**：`pytest tests -q` ⇒ **490 passed / 4 skipped**。

### 🧹 D94 ③ 残余清偿：剥注释口径**全域单源**（`D94 ⑥`；MB8/MB9）

D94 当初把「其余文本期门」登记为残余（改口径会变动其它门的既有判定）。本批一次清偿：

| 面 | 原状 | 改法 |
|---|---|---|
| `validators/validate_e2e_index.py` 的 `_code()` | `line.split("#", 1)[0].strip()` = **第二份口径**（任何 `#` 都截断） | 走内核 `strip_inline_comment` |
| 同文件 **9 处**内联 `split("#", 1)[0]` | 同上 | 全改 `_code(...)` |
| `scripts/gen_e2e_scripts.py` **3 处**内联 `split("#", 1)[0]` | 同上（本批结构钉抓出来的，原清单没数到） | 全改 `strip_inline_comment(...)` |
| `_parse_mock_line` 的 `partition("#")` | 同上 | 走内核 |
| `initial:` 理由检测的 `partition("#")` | 撞上断言值里的 `#`（如 `/console/#/x`）⇒ 把**路径尾巴当理由** = **假「有理由」**（假 PASS） | 走内核，理由 = **真注释**之后的内容 |
| `e2e.reset` 取值清洗 `.strip("\"\'")` | 从**两端**剥集合内任意字符 ⇒ 结尾带引号的合法发令被吃掉一个字符（静默改义） | 只剥**成对**引号（`_reset_command`） |

- **钉**：**结构钉**（行解析器的**代码行**里不得出现 `split("#"` —— 它当场抓出 3 处漏网）+ `initial:` 假理由**双侧**（无真理由 ⇒ WARN / 有真理由 ⇒ PASS）+ `_code` 保真 + `_reset_command` 行为（**穿门实际调用的那个函数**，不钉 helper 本体）。
- **变异**：**MB8**（`_code` 退回 split ⇒ 结构钉 + 假理由钉红）· **MB9**（`_reset_command` 退回两端同剥 ⇒ 红因正是「结尾引号被吃」）。
- **残留**：**无** —— D94 ③「剥注释全局一个函数对象」从「收敛面内成立」变为**字面全真**。
- **取证**：`pytest tests -q` ⇒ **494 passed / 4 skipped**（`test_validators` 114→116、`test_atlas_check` 28→29）。

## [v0.1.0-beta.22] - 2026-10-17

### ⚙️ E2E 生成链第三动能 `dispatch` + 台账收口三件（D98/D99/D100；v3 定形首跑全绿）

- **合成事件直发动词（D98）**：`rings/e2e/reference.md` §5.5 新增 `dispatch <tid>`——React `dispatchEvent('click')` 创造第三动能，适配「常态遮罩 + 入场动画」表面（force 在动画窗口被吞、native 因可点性检查永不过而挂死）；适用边界与 `native` 同家族、值域封闭（无第三位，出现 ⇒ 校验器 FAIL + 生成器报错中止）；变异 M87 + 两枚钉 + `test_validators.py` 112 条。
- **`stack-profile` 字段集定稿（D99）**：冻结现行实现实收面为 v1（`_support/stack_profile.py` ⇔ `shared/stack-profile.md` §3），后续字段变更一律起独立决策行，§14「草稿」语境退役。
- **pre-commit 兜底不启用（D100）**：校验靠显式跑（`pytest tests/` 全量 + `atlas_check` 前闸），启用留待 CI 一起落（D72 ④ 前置形态收口）。
- **协议定形首跑全绿（§13① 收口）**：v3 platform-frontend 切片 1 app × 1 页 **11/11**（净场协议 + D98 分片直发 + 产品同日修内容保存管道），留档采纳仓 `product/e2e/reviews/2026-10-17/`；gates 2.2「E2E 真跑」行补第 2 次咬合证据（逐格纪律只升本行）。

---


## [v0.1.0-beta.21] - 2026-10-16

### 🪲 E2E 生成链四处缺陷闭环：标量注释污染 · 元素守卫空转 · 守卫门不剥注释 · `force` 与被测属性相抵（Issue #R1–#R4 / D94–D97）

- **标量注释污染单源收敛（R1/D94）**：`_support/case_block.py` 的标量键分支改经内核 `_support/stack_profile.strip_inline_comment`，消除标量值尾部 `#` 注释直达生成脚本 URL 字面量的问题；列表项保持原样（其 `#` 为自然语言说明）。
- **守卫门自带剥注释（R3/D94）**：`validators/validate_e2e_index.py` 的 `守卫:` 路径门先经单源 `strip_inline_comment` 再做路由比对，消除门与生成器的消费歧义。
- **元素齐全守卫回归契约正文（R2/D95，⚠ 行为恢复）**：`scripts/gen_e2e_scripts.py` 的元素守卫 id 面回归 `case.get("testid")` 契约应然清单；未声明 `hidden` 占位槽的动态元素守卫开始真红（正确反馈），静态侧由常驻槽位门双重防腐。
- **Playwright `force` 动作步级开关（R4/D96）**：`rings/e2e/reference.md` §5.5 确立 `click`/`hover` 默认 `{ force: true }` 的契约授权与适用边界；新增 `native` 步级开关（如 `- click btn native`）用于禁用 force，保护可交互性被测属性的真实判定；校验器与生成器双向强检值域。
- **基线与守卫剥注释同源（S1/D97）**：零步基线探针与用例元素守卫 id 逐项剥离行内注释，彻底消除带说明 testid 导致的 `toHaveCount(1)` 假红。

---

## [v0.1.0-beta.20] - 2026-10-16

### 🔧 装配器语义两案：干跑不落版本戳 + 脏树守卫分「已跟踪/未跟踪」两语义 (Issue #21/#22: F54/F55, D92/D93)

- **干跑不落版本戳（D92/F54）**：`install.sh` 的版本戳落盘原是全脚本唯一裸写 ⇒ `--update --dry-run` 会真写 `.atlas/VERSION` 而不装配任何内容，配合一次被守卫拒住的真跑，副本落入「戳新 / 内容旧」且装配版本门（自写自读闭环）报假 ok；干跑首装还会残留 `<target>/.atlas/` 卡住真首装。修后戳写入挂干跑闸门，真跑路径逐字节不变。
- **脏树守卫两语义拆分（D93/F55）**：旧守卫只看 porcelain 路径列，`.atlas/` 整目录未跟踪（`?? .atlas/`，包产物不入库的合法形态）被撞判成脏 ⇒ `--update` 恒拒、`--force` 被逼成常规。修后按状态列分桶：已跟踪未提交改动 ⇒ 拒（F34 语义不变）；未跟踪 ⇒ WARN 放行 + 双摘要可见化（副本戳 ⇔ 源包摘要同录出声）+ 回灌出路先行。
- **动作执行可交互性强化**：`scripts/gen_e2e_scripts.py` 的 Playwright 点击与悬停动作默认追加 `{ force: true }`，避免真实 UI 中由于悬浮遮罩、动画或父容器事件拦截导致的动作执行超时。
- **登记**：`gates.md` 两行 + `DESIGN.md` D92/D93 + `proposals/RFC-20261016-03`（v2，独立评审「修后采纳」，处置表见 §6）；钉 2 条进 `tests/test_install_selfcheck.py`（7 → 9 条），变异 M77/M78 实证红后还原逐字节一致。

---

## [v0.1.0-beta.19] - 2026-10-16

### 🔧 生成器抗脆弱增强：动态元素守卫解死锁 + Playwright Strict Mode 兼容 + 登录态幂等保护 (`scripts/gen_e2e_scripts.py`)

- **前置守卫解死锁**：前置在场守卫仅断言 `step[0]` 的操作目标，动态生成的 testid 不再被前置判定死锁；若 `step[0]` 为 `goto`/`refresh` 等无 testid 操作，守卫安全为空。
- **Strict Mode 鲁棒性兼容**：单体动作与单体状态断言（`click`/`fill`/`visible`/`text` 等）统一发射 `.first()` / `.filter({ hasText: ... }).first()`，彻底消除界面中多实例同名元素导致的 Playwright strict mode violation 异常；`count` 断言保持原样。
- **登录态持久化保护**：生成器的 `auth setup` 脚本在 `stateFile`（如 `state.json`）已存在且非空时跳过覆写，保护开发者录制或现场生成的真实会话不被重跑覆盖。

---

### 🔧 包自检门前置降级 —— 缺 `.atlas/tests` 记 `SKIP`，不再恒红 (Issue #17: F53, D91)

**背景（残余面）**：issue #17 的装配面根因（`package.json.files` 漏 `tests` ⇒ 经 npm 装配的项目恒无 `.atlas/tests`）已在本日 beta.18 批（D86/F47）修掉，但 `scripts/atlas_check.py` 的包自检门（`check_factory`）本身**无前置判据**：存量装配（beta.17 及以前发行版的 npm 装配态）与源包开发态（仓根无 `.atlas/`）下 `pytest .atlas/tests` 收集失败（退出码 4）⇒ 全量模式恒红 `FAIL`，而 `--fast` 一跑就 OK——同一扇门两条路给两个相反结论（「红灯训练成噪声」族）。另有一个评审实出的现存假绿：`.atlas/tests` 被**文件**占用（装配损坏）时 pytest 收集 0 条退出码 0 ⇒ 被判 `ok`。

- **前置判据**：`.atlas/tests` **不是目录**（不存在 / 被文件占用）⇒ **`SKIP`**（不进 `failures`、不压垮整体判定），文案两层 = 判据面（实测路径 + 旧发行版装配态 / 源包开发态 / 装配损坏三形态点名）+ 出路（源包 `pytest tests`；项目侧重装走齐 `install.sh` / `atlas upgrade`）。同文件三态先例：`_GATE_PRECONDITIONS` / `GEN_NOT_READY`。
- **目录在场 ⇒ 行为逐字节不变**：真跑 pytest，真红仍 `FAIL`——降级只吃「断言对象不在场」这一种，防把真失败一并洗绿。
- **评审（tech-proposal-reviewer，1 blocking + 5 major/minor 修后采纳）**：blocking 件 = `DESIGN.md` D86 曾在根因未修时明文否决「遇缺就 SKIP」——按**收窄**处置而非推翻：D91 单列 + D86 行尾收窄注记，并把「装配面根因（装配三表同步）永远不得改靠 SKIP 吸收」单独立句；其余 = file 形态一道覆盖（上假绿关闭）、pytest 可用性盲区进门册「不查什么」、出路动作词齐组进钉、变异号登记、在场零用例（`no tests ran`）取舍显式化。
- **钉**：A-1（三形态 SKIP + 出路词齐组：`pytest tests` / `install.sh` / `atlas upgrade`）+ A-2（反面钉：目录在场注入必红 ⇒ 仍 `FAIL`）；变异 **M76**（前置分支置死 ⇒ A-1 红；还原逐字节一致，sha `2494e04f525be144`）。
- **登记补遗**：发版口径收拢为单版本——本条目一次性收录当日五个批次（F49–F53）的全部内容；另将 F49–F52 批已被占用而未落册的 **D87–D90 四行决策补记进 `DESIGN.md`**（内容自各批提交正文还原）。

**取证**：`tests/test_atlas_check.py` 22 → 24 条全绿；`pytest tests -q` ⇒ **455 passed / 4 skipped**（落地前基线 453 passed / 4 skipped，+2 钉无红）；`scripts/atlas_check.py --fast` 源包态自证 OK；`tests/test_canonical_consistency.py` 9 绿（计数 24 条为 pytest 实收口径）。登记面：`proposals/RFC-20261016-02-factory-gate-precondition.md`（v2 含评审处置 §6）、`shared/gates.md` 2.2 对齐测试行、`DESIGN.md` D91 + D86 收窄注记。

---

### 🔧 `守卫:` 路径 —— 元素齐全守卫在带参页面上不再导航到匹配不上的地址 (Issue #23: F52, D90)

**背景（两条条文合取后不可用）**：契约 §3.1 明定「带参路由取**业务段**」（`/projects` 而非 `/projects/:id`）⇒ 索引页面表 `路由` 列**按设计**不承载路径参数；而生成器 `page_urls()` 把该列当**唯一 URL 来源**，用于用例体开头的**元素齐全守卫**导航。带参页面的守卫因此落到路由匹配不上的地址：页面不渲染 ⇒ 守卫在 `goto` 后即红，用例自身的带参 `goto` 来不及生效。同一列还被 §8.2 的「`goto` 路径 ∈ 页面表」门当**前缀锚**用 ⇒ **一个字段被两种相反语义的用途消费**。

- **契约 §5.5 新增可选标量键 `守卫:`**：值 = 一条具体路径，生成器的**守卫导航**改用它；**缺省回落页面表 `路由` 列** ⇒ **对无参页面逐字节零变化**（零变化承诺同 §5.8）。
- **值仍不得私藏于分片**：`守卫:` 必须命中页面表 `路由` 列（口径同 §8.2：精确，或**非根路由**的子路径前缀命中）⇒ 新门行 **「守卫 路径 ∈ 页面表」**；判定逻辑抽成 `_route_hit()` 与 `goto` 路径门**共用**（同一套口径，避免两处各写一遍）。
- **零步基线仍用页面表 `路由`**：本字段是用例级的（同页不同用例可指不同实例），基线是页级产物；基线在带参页面上探不到元素时按「null = 不成立」处理 ⇒ 不产生假阳性。
- **一处实现坑（已记入内核注释）**：`守卫` 是**标量键**，**不得**登记进 `_support/case_block.py` 的 `_BLOCK_KEYS` —— 该元组内每个键都初始化为 list，入了就变成数组（实测踩到：`case.get("守卫").strip()` 报 `'list' object has no attribute 'strip'`）。

**取证**：新增钉子 4 条 —— 校验器 2（正向 1：`/home/42` 前缀命中 `/home` ⇒ PASS；坏输入 1：页面表外路径 ⇒ FAIL）、生成器 2（**带 `守卫:` ⇒ 守卫导航用该具体路径**；**零变化承诺**：同一用例带/不带 `守卫:` 各生成一次，两份产物**只差那一行**且该行含 `page.goto(`）。源包全量 **453 passed / 0 failed / 4 skipped**。`shared/gates.md` 计数登记 106 → 108（该门本轮第四次咬合）。

---

### 🔧 会话前提：`会话:` 通道 —— 宿主注入型会话态成为可声明、可隔离、可机检的前提 (Issue #13: F51, D89)

**背景（现场实证）**：有类需求的**被测属性本身就是**「会话被宿主以某个注入参数载入 ⇒ 界面呈相应形态」（身份 / 租户 / 管控 / 灰度类标记）。契约原无通道：`goto` 带 `?` 即 FAIL（§5.7/§8.2）、`auth` 只管登录态、`seed:` 绑数据实体 ⇒ 这类用例只能写成散文 `precondition`，而断言在初始态即成立 ⇒ 撞 §5.6 R9 恒真禁制，两条豁免通道又都不适用。

- **契约 §5.5 新增可选字段 `会话:`**（`- <键>=<值>`）：**前提构造，等同 `step`**；生成器编译为**首屏导航前**注册的 `addInitScript`，写入 **`sessionStorage`**。
  - 为何是 `sessionStorage`（用户裁定 Q1-A）：`storageState` 只覆盖 localStorage，而它跳标签页 / 跳用例持续 ⇒ 会污染后续用例（含「不传参 ⇒ 保持可用」类**对照用例**）。代码注释里写明了这条理由，防后人「优化」成 localStorage。
  - **与 R9 的关系（关键）**：**零步基线不施加 `会话:`**（基线是独立生成的页级测试体）⇒ 依赖该前提的断言在基线（默认会话）下不成立，R9 自动满足，不必也不得去借 `initial:`。
- **取值优先级（用户裁定 Q2-C）**：用例声明的值兜底，运行期环境变量 `ATLAS_SESSION_<键规范化>` **优先覆盖**；两者皆空 ⇒ **运行期报错中止**（不静默跑成默认态 = 假绿）。敏感值只经环境进入。
- **键白名单 = `stack-profile.yaml` 的 `e2e.session_preset.keys`**（`shared/stack-profile.md` §2 新行）：白名单外 / 整段未声明 ⇒ **文本期 FAIL + 生成器中止**（双保险）。白名单是**项目级声明**，正是 §5.7 禁令的边界落点：会话 / 身份 / 权限 / 灰度类注入键是**前提**（与 `app_login` 预置会话同类），**数据实体状态仍只能用真实界面动作达到**——不得把「某个数据对象已存在」走私成会话键。
- **落点**：`rings/e2e/reference.md` §5.1/§5.5 + `shared/stack-profile.md` §2 + `_support/case_block.py`（`_BLOCK_KEYS` 增 `会话`）+ `_support/stack_profile.py`（`_E2E_SUBBLOCK_KEYS` 增 `session_preset`，并补**块列表**解析：`<键>:` + `- 项`，惰化物化 ⇒ 对既有 profile 零行为变化）+ `scripts/gen_e2e_scripts.py`（`atlasSessionPreset` helper + 发射先于 `page.goto` + 白名单中止）+ `validators/validate_stack_profile.py`（段/键形态两行）+ `validators/validate_e2e_index.py`（门行「会话 取值合法」）。

**取证**：新增钉子 8 条 —— 校验器 4（正向 1 / 坏输入 3）、生成器 4（发射先于首航 / 未声明白名单 ⇒ exit 2 / 键在白名单外 ⇒ exit 2 / **零步基线测试体里不得出现 `atlasSessionPreset`**）。源包 **449 passed / 0 failed / 4 skipped**。`shared/gates.md` 计数登记 102 → 106（该门本轮第三次咬合）。契约字段登记门亦咬合一次：生成器先引用了 `e2e.session_preset` 而 §2 未声明 ⇒ 红，按门要求补契约后才复绿。

---

### 🔧 应然落点：应然 testid 的承载元素成为声明式、可机检的资产 (Issue #20: F50, D88)

> 本批动 `rings/e2e/reference.md` §5.1/§5.5、`_support/case_block.py`、`validators/validate_testids.py`。

**背景（现场实证）**：应然 testid 清单取自 AC 文字，而双向集合门只比「值集合相等」⇒ 一个**永不渲染的死字面量**就能把门凑绿而用例仍红。真实案例：某需求三条应然 id 里有两条所描述的控件在该产品里**根本不存在**（该类型控件在对应面板只渲染一句提示文案），分片却按 AC 文字为它们立了 id；门只会把「前端没这个字面量」报成缺口，**无法指出「这个控件压根没有」**。

- **契约 §5.5 新增可选字段 `落点:`**：行形态 `- <tid> <相对项目根的路径>`，声明应然 id 的承载元素；写明分档与理由：**声明了但不对**（文件不存在 / 文件内解析不到该 id）= 假陈述 ⇒ FAIL；**未登记** = 纪律缺口（存量清零过渡）⇒ WARN。
- **契约 §5.1 字段表**同步登记该键。
- **`_support/case_block.py`**：`_BLOCK_KEYS` 增 `落点`（单源解析器是它的唯一入口）。
- **`validators/validate_testids.py`**：
  - 新增 `file_testid_decls(clean_text, pages)` —— 把「单文件可解析的 testid 声明」抽成**单源**函数（静态字面量 / 同文件静态常量 + 单层引用 / 可枚举模板 / 命令式注入），`collect_testids_expanded` 与新的落点门**共用**（否则「抽取器看到了、落点门看不到」会成为新的半通状态）；
  - 新增 `shard_landings(cases, pages)`：按 **tid_owner** 归页（与 `shard_testids` 同规——否则跨页共享元素在市场分片登记、却要按 app 页查）；
  - 新增门行 **「应然落点」**。
- **顺带修一处同族缺陷**：`case_testid_usage` 原为**手写行扫描**（只认 `step`/`expected`/`testid` 三个小节键）⇒ 新增一个数组键就会把它的条目误吸进 testid 集合（本轮实测：`testid 命名规范` 报 `home-title web/src/home.html` 为违规名）。已改为走单源 `parse_block`。

**取证**：`tests/test_validators.py` +4（正向 1；坏输入 3：指向不存在文件 ⇒ FAIL / 文件内解析不到该 id ⇒ FAIL / 未登记落点 ⇒ WARN）；另修两处受影响的既有夹具（模板展开用例补落点、adopt 单向子集用例的文件名与落点对齐）。源包 **441 passed / 0 failed / 4 skipped**。`shared/gates.md` 计数登记 98 → 102（该门本轮再次咬合）。采用方端到端变异证明：把一条落点改指不存在的文件 ⇒ 「应然落点」FAIL 并指名；恢复 ⇒ PASS。

---

### 🔧 testid 契约：共享元素「一零件一名」+ 同文件静态常量解析 (Issue #19: F49, D87)

> 本批只动 `rings/e2e/reference.md` §4 与 `validators/validate_testids.py`。**双向集合门的强度未放宽**；新增的只是一条**静态可枚举**的声明形态。

**背景**：采用方现场撞到的形态 —— 同一共享组件在多页 / 多语境渲染同一语义元素，而应然 testid 按页命名；契约原先只承认「恰一处静态字面」（`data-testid={变量}` 对抽取不可见），使「一个零件一个名」这条路在抽取器侧**没有合法声明形态**。已按采用方裁定（跨页也只取一个名）落策略。

- **契约 §4 新增「共享元素取名策略：一零件一名」**：共享元素只取**一个** testid，页面段 = **归属页**（`tid_owner`），不随渲染页变化 ⇒「同一 testid 在多个页面渲染」**合法**（唯一性判据 = **声明处计数**，不是渲染点计数）。契约就此**不采用**「按当前页 slug 派生前缀」的模板机制作为共享元素的默认形态（`${slug}` 模板仍合法，但只用于共享外壳确实按页派生前缀的场合）。
- **契约 §4 新增「抽取器接受的声明形态」清单**：静态字面量 / **同文件静态字符串常量 + 单层引用** / 可枚举模板字面量 / 命令式注入（`dataset` / `setAttribute`）。**非静态初始化式、跨文件导入、未在本文件声明的标识符一律不解析 ⇒ 报缺失**（宁缺不猜）。
- **`validators/validate_testids.py`**：新增 `CONST_DECL` + `IDENT_TESTID_ATTR`，把 `const X = 'a-b-c'` … `data-testid={X}` 解析为与字面量**同档**的声明 —— 计入**声明处计数**（跨文件重名照报）、参与双向集合**两侧**判罚（孤儿照判）；同一常量在同文件被引用 ≥2 次计入「同文件重复声明」。
- **契约 §4「常驻槽位口径」补一句**：占位槽的可交互态应取**与用例断言期望相反**的态（断言 `disabled` 的入口用未禁用占位、断言 `enabled` 的用已禁用占位）——守卫照命中，而真实元素缺席时断言**照样红**，不得以占位元素充当断言证据（假绿通道，`shared/independent-review.md` §2 第 3 条）。

**取证**：`tests/test_validators.py` **+4**（正向 1：常量引用 ⇒ PASS；坏输入 3：非静态初始化式 ⇒ 缺失 FAIL / 跨文件导入 ⇒ 缺失 FAIL / 同常量引两次 ⇒ 同文件重复 WARN 并指名）。源包全量 `pytest tests/ -q` → **437 passed / 0 failed / 4 skipped**。`shared/gates.md` 的 `tests/test_validators.py` 计数登记 **94 → 98**（该门本轮**咬合一次**——按「红检查是证据」改登记而非放宽判据）。

---

## [v0.1.0-beta.18] - 2026-10-16


### 🔧 路由适配器识别完整性与挂载前缀合成 · 事实区渲染往返不变式 (Issue #15/#16/#17: F46/F47/F48, D83–D86)

> 本批钉号用 `M-R*` 前缀（与在飞批的 M 号段解耦，避开并发占用）。

* **【routes 适配器：两形态识别 + 挂载前缀合成】（`adapters/routes.py`, `shared/stack-profile.md` §3.2, `rings/structure/reference.md` §4 C + §6.2, `shared/gates.md` 2.1 + §3, `tests/test_adapter_routes.py`；`proposals/RFC-20261016-01`，issue #15；F46 / D83+D84）**：
  - **候选判据从「文件名」改成「内容」**（数组形态 + JSX `<Route>` 形态，含**同文件嵌套深度栈**）⇒ 模块入口表（`index.*`）不再被静默排除；接入项目实测 **19 → 52 条 / 1 → 10 个源文件**。
  - **挂载前缀合成**（新增能力）：站点表条目「路径 → 懒加载 / 导入的模块文件」即挂载关系；模块级表的**模块相对**路径必须合成成全站路径后再入表——否则多模块同名路径撞上渲染行键 `(应用, 页面/路由)` 被 `dedup_by_row_key` 折叠成**假事实**（比缺口更糟）。
  - **歧义口径写死**（评审 F2）：入边 ≥2 / 成环 / 基名不可求值 ⇒ **未解析 + 计数，条目一律不产出**（宁缺不产假路径）；站点级 vs 模块级用**本地证据**（本文件是否挂载了自己的 router）判，**不看 basename**——否则「别名解析失效」会被字面量 basename 兜住（缺陷不可观测），而「无入边 + 无 basename」的模块表会静默退化成站点级、把相对路径泄成全站路径。
  - **覆盖率出声**：输出 JSON 增 `route_coverage`（契约正文已登记）+ stderr 逐文件列未解析原因；**明确不收**页内 tab 驱动的伪路由（不是路由声明，继续由 agent 语义撰写）。
  - 钉（均逐字节还原复绿）：**M-R3** 候选闸还原成文件名 / **M-R4** 合成退化为模块相对路径 / **M-R5** 未解析仍产出相对路径 / **M-R6** 别名解析退回尾段字面相等 / **M-R7** 子路由按「无 basename」误判站点级。
* **【事实区渲染：「写出 ⇒ 读回」不变式 + 渲染即自校】（`scripts/refresh_structure.py`, `rings/structure/reference.md` §6.2, `tests/test_refresh_facts.py`；`proposals/RFC-20261016-01`，issue #16；F47 / D85）**：
  - 单元格换行 → `<br>`（**保行结构**，不用空格把成员粘起来）+ 裸 `|` 转义 ⇒ 逐单元格往返一致；此前多行取值把一行撑成多行，`parse_rows` 丢首行、跳续行 ⇒ **事实丢行 + 每轮判「新增」**（漂移标记常驻、baseline 棘轮**永不释放**）。真实数据实测：1987 条 / 88 条含换行 ⇒ 修后第二遍 **0 漂移、字节幂等、1939 行全部读回**。
  - `_norm` 把 `<br>` 与换行视作**等价**（键稳定从此无条件成立）；**渲染即自校**对渲染出的字符串逐单元格比对、与是否写盘解耦（dry-run 同样出品），不一致 ⇒ stderr `WARN[render_table]`。
  - 钉：**M-R1** 摘掉单行化 / **M-R2** 换行→空格（防「用空格糊过去也算修好」）/ **M-R9** `_norm` 不折叠 `<br>` / **M-R10** 摘掉自校调用（自校必须**活着能咬**）。
* **【装配面三表同步：`package.json.files` 补 `tests`】（`package.json`, `tests/test_tools.py`；`proposals/RFC-20261016-01`，issue #17；F48 / D86）**：F30 只钉了 `install.sh` ⇔ `pkg_digest` 两张表，**第三张漏了 `tests`** ⇒ npm 分发不含 `tests/` ⇒ 经 npm 全局包装配的项目**恒无** `.atlas/tests` ⇒ `atlas_check` 全量模式的包自检门恒红（采用者自己修不了，而 `--fast` 一跑就 OK）。补 `files` 条目 + 守恒钉第三条腿；钉：**M-R8** 从 `files` 摘掉 `tests` ⇒ `test_f47_npm_files_cover_assembly_list` 红。

### 🚪 走查断链与登录预置两案落地 (Issue #10/#11: RFC-20261015-01/02, 评审修后采纳)

* **【走查与 E2E 控制台：术语交叉指认 + `manual.md` 产出方 + 存在性披露】（`rings/e2e/reference.md` §6.2/§5.4 末/§10 执行纪律/§10.1, `rings/prd/reference.md` §4·八, `shared/gates.md` 2.5, `docs/design/e2e-ring.md`, `scripts/e2e_console.py`, `templates/e2e/console/app.js`, `tests/test_e2e_console.py`；`proposals/RFC-20261015-01`，issue #10；D81）**：
  - 「走查」一词被两道不同阶段的门共用（跨 `3507 AQ` / `3508 §170` 两份决策记录复用同一 B124 标签）⇒ 读成「硬软自相矛盾」。定案 = **仓库既有的两名各自保留 + 撞车点交叉指认**：`走查单确认门`（硬，= e2e §6.2 前置门）、`验收走查门`（不阻塞后续域）；`rings/e2e/reference.md:383` / `:569` / prd §八 标题下三处互指。**不发明第三名、不全局改名**（波及 7 源文件 + 开户模板节标题，可逆性最差）。明示翻转触发器：确认门连续挡住两批以上需求的 e2e 落笔（gates 台账可查）⇒ 重议改软。
  - **`manual.md` 定位收窄 = 「控制台盖不住的手工项」**（B124 原话），不是走查单载体——收口走查的符合性对照物明文指向**已确认的 §八 节**（`rings/e2e/reference.md:176`）；issue 的「双写无主」判为**伪冲突**，不建回填协议、不做回指弱关联。
  - **产出方**：e2e 环在页面表就绪后盘点落项（§10 新增执行纪律 5）；**验收走查现场**新识别的手工项**授权人侧当场直写**（评审补的盲区——现场发现时 e2e 环已收工，无授权落点会让缺陷在运行时复发）；控制台写盘点不变（账本 + 索引）。
  - **存在性披露**：§5.4 收口走查留痕 README 增**「手工项：N 项 / 已评估：0 / 待评估」**评估行（不发明 §11 新报告行——「评估过没有」是 per-域跨时间状态，不是「每次变更」状态）；控制台 `manual_state: missing` ⇒ meta 行显式「未创建」——「文件缺失 = 空清单不阻塞」保留，但**「没有」与「忘了」不得同形**（**M73**：摘通道 ⇒ `test_manual_absence_is_disclosed_not_silent` 红）。不采纳 issue 的「开户落空 manual.md」：零占位符（`global-rules.md` §5）+ 空文件不区分「评估过为 0」与「忘了」。
  - **顺序死锁不改门即消解**：§八 的入口来自功能六件套，不依赖 e2e 环的索引页面表；「manual.md 页面列须按压页面表路由」的前置依赖只在把 `manual.md` 当走查载体时才被造出来——不造该依赖（§6.2 补边界句：门只约束「本环不落笔用例」）。
* **【靶场登录预置：`app_login.mode` 增 `none` + 「段缺失 = 合法降级」撤销（分两阶段升档）】（`shared/stack-profile.md` §2, `rings/e2e/reference.md` §5.8/§7.1, `apply/reference.md` adopt 行/三问门, `templates/stack-profile.yaml`, `scripts/gen_e2e_scripts.py`, `validators/validate_stack_profile.py`, `_support/stack_profile.py`, `tests/` 五文件, `shared/gates.md` 2.2/2.1；`proposals/RFC-20261015-02`，issue #11；D80）**：
  - **`mode: none` = 靶场无访问门的显式声明**（家族先例 `e2e.mock.mode: off` / `e2e.review.mode: off`——「在 X 段里用 mode 值声明 X 通道不需要」）：不生成登录预置设施（`atlas-auth.setup.ts` 不出、配置无 setup 项目 / storageState）、不打警告；段内五取证字段残留 ⇒ 校验器 FAIL + 生成器报错（与 `fabricated` 的「收窄」相反 = **「全弃」**）；**空段 = 未声明**（**M71**：none 分支仍生成设施 ⇒ `test_setup_mode_none_generates_no_login_facilities` 红）。
  - **语义改判**：段缺失 = **未声明**（不再是「合法降级」——硬要求（§7.1 登录态（硬））的输入不得靠「缺失即静默放行」吸收）。**分两阶段**：第一阶段 `validate_stack_profile` **WARN 指名**（`app_base_url` 已声明 ⇒ 项目准备真跑；**文案中性**——本器判不了靶场有没有门，不得断言「每次都需人工登录」；未声明 base_url 不提前吹，**M70**）；**第二阶段 = 下一次真跑准备日（时间锚，无条件）** 推给生成器 `not_ready`（退出码 3 + 机读键 `not_ready: "app_login"`，与 `app_base_url` 同通道，SKIP 原因两态扩三态）。**第 1 次咬合（升档依据）= 2026-10-15 现场**（pass1→pass5 会话失效 + 人工登录复用），登记 `gates.md` 2.2「E2E 真跑」行。**连带面明示**：升档日 `生成物最新` 门一并 SKIP 为有意回退；enforcement 点（生成器）与 gate 点（真跑门）解耦是有意设计——迁移窗口内盘上旧脚本不误杀。
  - **产出方补齐（与 #10 同一病理）**：adopt 开户问数「**靶场接入取证**」（`app_base_url` + 登录形态三选一必须显式——`real` 四值 / `mode: none` / `fabricated` + `storage_key`；凭据只提醒来源，**询问不落盘**）；三问第 3 问判「是」而未声明 ⇒ 兜底追问（UX 加速器，判据正文仍是机器门）。
  - **`yaml_scalar` null 家族收窄为 YAML 口径**（只认 `null` / `~` / 空；裸 `none` = 合法字符串）：旧口径把裸 `none` 吞成 null ⇒ 缺省判据把它读成 `real`，三态判据静默失效（**M72**；全量回归无受影响夹具）。
  - **词表守恒补缺**：`APP_LOGIN_MODES` 是唯一无「⊆ 模板 ⊆ 契约正文」守恒钉的 MODES 族（`SEED_MODES` / `ORIGINS` / `RUNNERS` 都有）⇒ 本批补上（`test_validators.py` 89→**91** 条 / `test_gen_e2e_scripts.py` 53→**55** 条）。变异 **M69**（none 字段互斥卸恒真 ⇒ 残留夹具变绿）。
  - **升档迁移动作（存量项目）**：`app_base_url` 已声明 + `app_login` 缺失的项目，在升档日前**加一行** `app_login: {mode: none}`（无门）或补齐 `real` 四值（有门）；`real/fabricated` 已声明的项目零影响。
* 两方案评审 = tech-proposal-reviewer 子代理「**修后采纳**」（v2 各按其修正点落地：修 3 处事实错误 / 重写自相矛盾的升档条件 / 指定机读键 / 换出更省的留痕落点；完整修订记录见两份 RFC 文末）；设计记录 = `DESIGN.md` D80 / D81；全量 **418 passed / 4 skipped**（bun 执行级 skip 为既有），canonical 一致性全绿。

### 🧩 用例 ID 文法单源与 `PAGE` 段推导写全 (Issue #14: F45, D82)

* **【`PAGE` 段推导写全 + 文法单源 + 无裸正则普查钉】（`rings/e2e/reference.md` §5.3, `_support/case_id.py`, `validators/validate_e2e_index.py`, `scripts/e2e_console.py`, `templates/e2e/e2e-index.md`, `templates/e2e/case-shard.md`, `tests/test_validators.py`, `tests/test_e2e_console.py`, `tests/test_tools.py`, `shared/gates.md`；issue #14；D82）**：
  - **契约写全推导**：§5.3 原只写「`PAGE` = 页面 slug 的**大写**」，多段 slug 无解 ⇒ 补「**只做大小写变换、不做分段变换**」——连字符原样保留、不设收敛、不设 `slug → PAGE` 映射表；单段 / 多段各给一例，并写出机器可读形态。`slug.upper()` 即 `PAGE`，故 `PAGE` 段与 slug 双向可推，「全站唯一由 `PAGE` 段保证」自然成立。
  - **文法单源**：同一文法体原在索引校验器与控制台两处各存一份、各自只支持单段（前者 `ID 格式` 门对多段 slug 恒红，后者从生成产物反查用例 ID 时静默取不到）⇒ 经 `_support/case_id.py` 收敛为唯一实现（同语言逐字节双拷贝的单源先例 = `_support/case_block.py`）。**锚点仍各留**：整格判定（`^…$`）与「从生成产物取 ID 前缀」不是同一判定，不合并。载体已就位（`_support` 已在装配白名单、`load_module` 已泛化查找、两消费方已 `import`）⇒ 新增 1 文件 + 2 处取用，**不动**装配与加载机制。
  - **无裸正则污染门**（`tests/test_tools.py`，**M75** 咬合）：① 文法持有者集合恰为 `{_support/case_id.py}` —— 判据按**常量内容**（含 `E2E-` 且含三位尾号锚）而非固定子串，故字符类等价改写（`[A-Z\d]`）、相邻字符串拼接、更松的 `\w+` 形态一并被咬；② 实际取用者 ⇔ `CONSUMERS` 登记面，两个方向都红。**已知残留已登记**：把文法拆到多个常量再拼装、或经 `re.escape` 构造的写法仍绕过（属刻意构造，与「按源码文本找正则」路线的边界一致）。
  - **反向两态留档**（`global-rules.md` §6）：**M74** 把单源文法改回单段 ⇒ 文法钉子红、逐字节还原后复绿；**M75** 在普查面内注入自写裸正则 ⇒ 普查钉红、删除后复绿。两态均断言「注入前基线 GREEN / 注入前字节确实改变且锚点恰好命中 1 次 / 还原后 sha 相同」。
  - **不新增报响门**：控制台取不到 node id 时下游已返回 409（不是假绿通道）；立门会在「生成前的合法中途态」假红（`未就绪 ≠ 失败` 同族）且触 §12 先量。本批只对齐文法。
  - **模板占位符**给形态引导（`PAGE` = 页 slug 的大写原文），脚手架不再留白。
  - **实测**：源包 `pytest tests/ -q` = `423 passed, 4 skipped`（本批净增 5 条）；本项目 `validate_e2e_index.py` 的 `ID 格式` 门由 FAIL 转 PASS，6 条存量 ID 一条未改（零迁移）；其余门逐项同态。
  - 被否：纯同步钉（不共享实现 —— 把登记面内的漂移留给守卫，而跨语言对才用同步钉）；收敛为单段（各读数实测碰撞或丢双射，且需新增映射表）；顺手统一 `AC_RE`（PRD 环明文禁止多段 `CODE`，单段是有意收紧）。

---

## [v0.1.0-beta.17] - 2026-10-15


### 🧹 门册五件遗留态收口 (Leftover-State Batch: D79)

* **【真跑记录裁决与升档规则落档】（`shared/gates.md` 上限声明/2.2/2.4, `DESIGN.md` §13 项, `rings/e2e/reference.md` §16, `shared/single-source.md` §3；D79 ①）**：
  - 以 gates 2.2 行的仓内记录（逐页真跑 + 咬出真红，`3508 §166`/`§187`/`§190`）为事实，纠正三处 2026-09-28 批的「真栈未跑/未发生」残留措辞（完成门 = 域收口事件、与真跑门独立）；「暂不真跑」裁定标注为已被执行反推，双台账会话号（`3509 §111`/`3508 §111`）并列引用。
  - 取证上限改**逐格**：`真跑级` 只给字面咬过的行、须附咬合证据；未覆盖行保持出厂级、不预填；**首跑协议 = 1 app × 1 页最小切片**，留档 `product/e2e/reviews/<日期>/`；完成门与真跑门是独立升档通道；E0 产物残留重生成绑真跑准备日。
* **【AC 反向覆盖：升 FAIL 规则落档 + 死指针修正】（`validators/validate_e2e_index.py`, `shared/gates.md` 2.1/§3；D79 ②）**：
  - 触发 = 零挂靠清零 + 清零态实测全绿一次 ⇒ WARN 分支改 FAIL（不设 profile 开关——灰度即「看起来在跑」面）；升档日 source/copy 分叉按回灌批收口。校验器 WARN detail 里指向外仓 `product/issues.md` P9 的死指针改为 gates 行锚（台账不在本仓）。
* **【D77 否决面词汇钉（canonical 判据⑦，治标）+ closeout 宣称 sweep】（`tests/test_canonical_consistency.py`, `shared/gates.md` 2.6, `shared/closeout.md`, `docs/design/overview.md`, `docs/design/prd-ring.md`；D79 ③）**：
  - 黑名单词（判据⑦词表，五个；词表本体见 `tests/test_canonical_consistency.py` 的 `VETO_WORDS`）出现在 git 跟踪源 md 的活语境 ⇒ 红；豁免锚 = 行内 `D77/D78`（局部自持，**不得**并入 `RETIRE_MARKS`——共享会把豁免串门到 ①③⑤）；扫面收窄到 `docs/**.md`（除 `.vitepress`）+ `shared/**.md` + 顶层 `README.md`（rglob 不认 .gitignore，dist 编译产物会漂判据）；`rings`、`apply`、`patches` 三目录不扫 = 显式盲区。
  - **判据落地首跑即咬 4 处漏网活体**（`overview.md:20/:57/:143`、`prd-ring.md:124` 的 Leiden/拓扑聚类宣称——D78 ④ 收窄批的漏网，教训 = sweep 按词 grep、不按已知清单改文件），同批全部收窄为多信号投票 + D77 锚。
  - closeout 新触发行：改 §12 被否裁决 ⇒ 全仓 grep 否决词 + 同批登记进黑名单（钉=治标本面，语义自洽终归人）。变异 M67：摘掉黑名单一个词 ⇒ 喂坏输入用例红（还原逐字节一致）。
* **【impact 对账观察窗（不加代码）】（`shared/gates.md` 2.1, `scripts/impact_reconcile.py` docstring；D79 ④）**：
  - 台账 = `impact_reconcile` **已无条件落盘**的 `impact-reconcile.json`（每单一份）；升 FAIL 触发 = 裁决日起**连续 3 单**漏报（miss）为 0 且无**同文件**重复漏报（对账本来就只判文件级）；升档后分档 = **miss ⇒ FAIL、over 保持 WARN**（多报是预测偏宽的良性量，收口不得被它钉死）；判据值全落 gates 行、不赖仓外 `3509 §B191-1` 台账数字。
* **【装配版本门 WARN 文案升级】（`scripts/atlas_check.py`, `scripts/pkg_digest.py`, `shared/gates.md` 2.2, `tests/test_atlas_check.py`；D79 ⑤）**：
  - WARN detail 给齐**两支路生效路径**（npm 全局源包态 `atlas upgrade` → `atlas update`；本地源仓态重跑 `install.sh`）+ `backflow.py` 三态明细通道（版本门不做第二套文件级 diff——防腐）；同批回写三处旧文案字样 + 测试断言钉（**M68**：从 detail 摘掉动作词 ⇒ 红，还原逐字节一致）。

### 📐 图谱收益实测收窄与接线/gitignore 自动化 (Graph Value Recalibration & Wiring)

* **【图谱「提议」按栈门控 + 收益宣称按实测收窄】（`shared/stack-profile.md` §2/§3.6, `rings/structure/reference.md` §6/§7, `templates/stack-profile.yaml`, `scripts/impact_report.py`, `DESIGN.md` D78, `docs/innovations/code-graph.md`, `docs/design/structure-ring.md`, `docs/concepts/rings.md`, `docs/guide/token-engineering.md`, `README.md`；issue #2 复审）**：
  - cgc 0.6.13 实测（前端形态夹具独立复测）：**JSX 组件引用不产生任何调用边**（`CALLS` 与启发式调用边均不覆盖 `element: <Comp />` 形态），且 atlas 消费层只认 `CALLS` 边（`_graph.callers` 写死边型）⇒ 图谱对纯 UI 栈两条消费面近乎零收益——`routes` 图谱枚举通道与 regex **产出恒等**，`impact` 对组件叶面系统性失真；逻辑调用链照常有效。
  - **提议按栈门控**：仅当 `apps[]` 存在 `kind ∈ {backend, fullstack}` 的 app 时才探测并提议声明 `graph` 段；纯 `frontend` / `mobile` 不提议（不探测、不提、不推销）。撤回排定的「体检报告图谱探测提醒」——对目标栈无收益的能力不需要发现通道。
  - 收益口径分两层写死：**消费层**（atlas 只读 `CALLS` 边）是不随 cgc 版本漂移的不变式；**后端层**（0.6.13 边型普查）随版本可能变化，由 `pinned` 探测 WARN 感知。
  - 文档同步收窄：`docs/design/structure-ring.md` 的「调用拓扑候选域聚类 / Leiden」宣称（与 D77 ① 直接冲突，03 收窄漏网）、`docs/concepts/rings.md`、`docs/guide/token-engineering.md`（advisory ≠ 阻断）、`docs/innovations/code-graph.md` 与 `README.md` 的开场措辞；`impact_report` 常驻「无调用方命中」提示句补 JSX 渲染引用。
* **【接线第 5 触点：`.gitignore` 自动追加 `.adapter-out/`】（`patches/project-wiring/apply-wiring.py`, `shared/stack-profile.md` §3.1/§3.6, `shared/gates.md` 2.3；issue #8 的后续）**：
  - issue #8 把 atlas 全部中间产物统一到项目根 `.adapter-out/` 之后，**所有**接线项目的 `git status` 都会出现未跟踪噪声（不只图谱用户）。接线在目标项目**已有** `.gitignore` 时幂等追加一行；`.adapter-out` 子串已存在 ⇒ 跳过；`!.adapter-out` 负模式 ⇒ 跳过不与用户规则打架；**无 `.gitignore` ⇒ 不首创**（报告给一行建议）。**本触点无退役对称**：单向追加、永不回收——`.gitignore` 不是 wiring 建的文件（与 `pytest.ini`「逐字节相等才清」不同，明写承认）。门面 2.3 行四触点 → 五触点，计数随 `tests/test_apply_wiring.py`（20 条）/ `tests/test_project_wiring.py`（12 条）刷新。
* **【跨产物声明一致门：D 类接线态 ⇔ 形态 / 缺口登记】（`validators/validate_structure.py`, `rings/structure/reference.md` §7，`shared/gates.md` 2.1）**：
  - 契约 §3.5 把「D 类有机器可读描述 ⇒ 指针形态 ⇒ `adapters.api` 置 null」写死，但接线态与形态声明**分属两个产物**（profile ⇔ `_meta.json`），此前无任何机器判据——混写（如 profile 还声明着 `api` 而 `_meta.categories.D` 记的是指针）没有门咬。现 `validate_structure` 判：`adapters.api` 已接线但 `categories.D` **锚定声明**为指针 / 未取证形态、或 `adapter_gaps` 登记 `api` ⇒ `WARN` 指名（锚定声明口径 = F38 同族：
    token 首位 + 显式分隔符，散文提及不算声明）；profile 缺失 / `adapters.api` 未声明 ⇒ 不产行。同日实测咬合：标签前缀正则会把「未取证」本身当 `<标签>:` 前缀吃掉 ⇒ 判据顺序定为「声明位直取优先、标签兜底」（更新至 `_d_form_token` 注释与 F43 钉子）。变异证明：M64，`tests/test_structure_validator.py`（24 条）。
* **【`apis.md` 指针形态判据锚定化（F44，issue #6 同族兄弟残留）】（`validators/validate_structure.py`）**：
  - 旧判据是无锚定全文子串 `"真相源" in t`：清单型 `apis.md` 的语义段只要写一句「本域接口真相源由网关维护」，整表就被误判「清单与指针混写」FAIL——与 issue #6 的 `categories.A/H` 措辞判形态同一族疾病，落在兄弟判据上。现改**锚定声明**：行首（或表格单元格首）出现 `真相源` token、其后接显式分隔符或就此结束才算指针形态；散文提及一律不算，真按指针落笔时豁免照常成立。`表格列` 门里对指针文件的豁免同步换用同一判据。变异证明：M66，判据退回全文子串 ⇒ `test_f44_list_form_prose_mention_of_zhenxiangyuan_not_flagged` 红（还原逐字节一致）。



* **【`.adapter-out/` 单一位点 = 项目根】（`scripts/refresh_structure.py`, `scripts/atlas_check.py`, `adapters/_graph.py`, `shared/stack-profile.md` §3.1/§3.6, `DESIGN.md` D41/D77, `rings/structure/reference.md` §6.1；issue #8）**：
  - 设计档案 `docs/design/structure-ring.md` 的目录树**从一开始**就把 `.adapter-out/` 画在**项目根**（「适配器提取中间件、图谱新鲜度标记」同处），而实现漂成了两处：图谱层在项目根、结构环产物在 `.trellis/spec/structure/` 下 ⇒ 同名两处。现场因此出现「`git status` 里有 `.adapter-out/`，而「结构漂移」门说『无 .adapter-out 产物目录』」的自相矛盾——排查者会先怀疑门坏，而不是去比对基准。
  - 三消费者（`refresh_structure` 写入 / 漂移门读取 / `_graph` 标记）统一到项目根；漂移门的 SKIP 文案**带上实际路径**，同类「SKIP 与现场不一致」一眼能看出问的是哪条路径。新增 `test_f41_adapter_out_single_location` 把三者钉在一起（此前是两处硬编码字面量，无任何测试关联）。
  - **顺带修掉一个移动暴露的真缺陷**：`CLEAN_EXEMPT_PREFIXES`（F26 基线自进前置④「产品侧干净」）此前靠 `.trellis/` **顺带**豁免 `.adapter-out/`；移到项目根后若不显式豁免，atlas 自己写的中间目录会被读成「产品侧有未提交改动」⇒ **基线自进永久冻结**（比原缺陷更难察觉：门不报错，只是再也不前进）。已把 `.adapter-out/` 加入豁免前缀。
  - 代价：项目应在 `.gitignore` 加一行 `.adapter-out/`（对所有项目都成立，不再只是图谱用户）。
* **【接线缺口可见化：`_meta.json.adapter_gaps`】（`validators/validate_structure.py`, `rings/structure/reference.md` §6.1/§7/§9, `templates/structure/_meta.json`；issue #3 ④）**：
  - 接线前置未满足时（适配器 0 命中 / 产出不自洽），契约要求「不接线 + 登记缺口」。不登记的话两种性质完全不同的处境在产物里**同形**（都是 `maintained_by: agent`）：(a) 设计结论「源即真相，不接」；(b) **工具覆盖不足**（逐件判定表判「接」，但本栈 0 命中）。采用者会把 (b) 读成 (a)，而该类别的 `structure ↔ 代码` 对账平面**永久缺口、且无人知道它不是预期的**——`§B118` 论证了「把缺口伪装成配门比诚实缺口更糟」，本条补其反面：**把工具覆盖不足伪装成审慎的设计结论，同样是伪装**。
  - 此前契约把落点写成「写进台账（`§B118`）」，而 `3509` 台账**不在本仓** ⇒ 缺口被记录在采用者读不到的地方。现改为落 `_meta.json.adapter_gaps`（类别 → 为什么没接）：`validate_structure` 对非空值出 `WARN` 逐条指名（**不置红**——未接本身不是缺陷，但必须可见），形态非法 ⇒ `FAIL`；`atlas_check` 体检报告直接可见。

### 🐛 自感知上报四项缺陷清偿 (Self-Reported Defects: Four Fixes)

* **【装配版本门：摘要恒空致门恒 ok】（`scripts/pkg_digest.py`, `scripts/atlas_check.py`, `install.sh`；F37，issue #1）**：
  - 过滤口径由**绝对** parts 改**根相对** parts：npm 全局安装的源包位于 `<prefix>/lib/node_modules/<pkg>`，绝对 parts 必然命中 `SKIP_DIRS` 里的 `node_modules` ⇒ 每个文件都被滤掉 ⇒ `files == []` ⇒ 摘要恒为 `sha256('')[:16]`；而落戳与重算**两侧同错** ⇒ 恒等 ⇒ 「装配版本」门在任何内容漂移下都不报红（实测 `digest(绝对全局路径) == e3b0c44298fc1c14`）。
  - 「装配集为空」由静默空摘要改为**响亮报错**（`EmptyAssembly`）：`atlas_check` 侧 WARN（不得滑成 SKIP——本仓 SKIP 语义是「合法降级」），`install.sh` 侧落戳失败改**硬错**（「装配 0 文件」不得被记成一次合法装配）并附一行手工诊断命令。
  - 历史坏戳 `e3b0c44298fc1c14` 单列一条**根因级** WARN（重跑 install.sh），不混进「源包已前进/落后」那条对账文案。
* **【tests 适配器：对 `.test.ts` 给出 Python 运行命令】（`adapters/tests.py`, `shared/stack-profile.md` §3.2；F40，issue #4）**：
  - 运行命令改由测试文件**后缀族**推定（`.py` ⇒ Python 族；`.ts/.js/.tsx/.jsx` ⇒ Node 族，playwright > vitest > jest > `npm test`），配置只在同族内细化命令——不再「项目根有 pytest 配置 ⇒ 全仓测试都按 pytest 跑」。
  - 后缀族与配置族**冲突**时不产矛盾条目：item 仍出、`run_command` 置空（**无主张**）+ stderr WARN，**退出码恒 0**（非零会被 `refresh_structure --chain` 当成适配器失败而中止整条链）。
  - **配置探测扫整项目**，不随 `--app` 收窄——配置是项目级的、落在项目根；旧实现逐 app 调用时拿不到根级配置，命令被静默降级成空。
  - 接线前置由「产出非空」扩为「产出非空**且逐条自洽**」：`§B118` 只覆盖了「产出为空」那一类假绿灯，没覆盖「产出非空但内容错」。
* **【structure 类别覆盖：散文可满足 A/H 枚举判据】（`validators/validate_structure.py`, `templates/structure/_meta.json`, `rings/structure/reference.md` §7；F38，issue #6）**：
  - `_cat_token` 由关键词**全文子串匹配**改**锚定声明位置**：可选 `<标签>:` 前缀（保住 F17 的 `A: covered` 容错），token 之后须接显式分隔符或串尾，取证文本接在其后。旧实现把**描述未完成**的措辞判成**已完成**（`待核准：…核准后补写为 added` 通过），而 H 恰是 `adopt` 下唯一不得 `skipped` 的类别。
  - 同步 `templates/structure/_meta.json` 的占位写法（原 `[covered|skipped：<取证>]` 会教出非法形态）与 §7 的写法规定。
* **【prd 域间依赖门：判据存在却无对应规格】（`validators/validate_prd.py`, `rings/prd/reference.md` §4/§7；F39，issue #7）**：
  - 节点 id 正则 `\w+` → 含连字符（带连字符的域 slug 此前**不可用作节点 id**）；`domain_name` 由 `\S+` 改**整行**读取并剥引号（含空格的中文名此前**读不出来** ⇒ 与「标签须与 `domain_name` 逐字相同」组合成**无合法写法**）；裸 slug 节点也认。
  - 边抽取不再整段 `findall`：支持**链式** `a --> b --> c` 与**边标签** `a -->|前置| b`（旧实现**静默丢边**），`%%` 注释剥除，`-.->` 仍不入边集。
  - FAIL 文案分两类根因：「标签未解析」与「边集真不一致」。
  - 契约补齐「§五 mermaid 写法约定」（节点 / 标签 / 箭头 / 方向 / 粒度 / 注释 + 可照抄示例）——判据的写法要求不再只活在源码里。

*(以下为上一轮未发布内容)*

### 🔌 前端栈适配器覆盖与图谱消费面如实化 (Frontend Adapter Coverage & Honest Graph Surface)

* **【适配器认主流前端栈】（`adapters/routes.py`, `adapters/api.py`, `adapters/models.py`, `adapters/_lib.py`）**：
  - 真实存量项目实测：**routes / api / models 三类产出全为 0** ⇒ 按 §6.2 只能退回「agent 手写」（慢，且带解析瑕疵）。本轮把三类的 TS 形态补齐：
    - `routes`：收**声明式路由表**（含 `rout` 的数组绑定，如 `routesList` / `otherRouters`），不再要求父目录叫 `router`、不再只认 `.ts`；反引号路径与 `element: <X />` 一并收；注释行（`//`、`/* */`）不再被当成活路由。
    - `models`：收**契约层声明文件**（`types/` `api/` `dto/` …）里 `export` 的 `interface` / `type … = {`；`?` ⇒ 可空、`readonly` ⇒ 只读、字面量联合 ⇒ 枚举、`extends` ⇒ 父字段并入；非 `export` 局部类型、无字段体的类型别名、组件 Props（UI 管道）与 `*.d.ts` 一律不收。
    - `api`：收 **TS 的 RPC / action 调用**（首参为点分方法名的 `request(…)` / `*Fetch<…>(…)`），`path` 记方法名本身、不合成 URL。
  - 新增共用工具 `_lib.strip_js_comments`（引号感知：`'https://x'` 里的 `//` 不是注释）。
  - **修复**：`api` 的「有机器可读描述」分支此前**不可达**——描述文件搭源码后缀遍历永远找不到 `.json` ⇒ 自带 `openapi.json` 的项目会得到空事实表；改为按文件名单独探测（整项目范围）。
  - 测试：新增 `tests/test_adapter_api.py`，扩写 `tests/test_adapter_routes.py` / `tests/test_adapter_models.py`，登记变异证明 **M52 / M53 / M54**。
* **【图谱消费面如实化】（`README.md`, `docs/innovations/code-graph.md`, `shared/stack-profile.md`）**：
  - 原文称图谱供给结构抽取「跨文件端点到模型映射 / 级联依赖自动归域」（如实化判据：`DESIGN.md` D77），与实装不符——`_graph.py` 的消费面只有 `routes` 的**文件枚举通道**与 `apply` 的**影响面基准**两处，域聚类与解析层都不走图谱。图示与正文按实情改写，并写明「它不做什么」。
  - **画像确认门内新增探测与提议**：`graph` 段在模板里是注释态，不提议就永不生效（实测用户装好后端而全程无人提过）；同时要求提议口径如实，别把能力说大。
* **【结构环：域清单确认门】（`rings/structure/reference.md`, `skills/atlas-structure/SKILL.md`）**：
  - 在「提议候选域」与「铺域级文件」之间加一道用户过目门；未经确认就产出的，报告里必须点名「未确认」。域 id 是全链路键，PRD 定稿合并/拆分会让在未确认粒度上先铺的产出整批重排。
* **【F 类退役残留清除】（`DESIGN.md`, `skills/atlas-structure/SKILL.md`, `docs/ecosystem/skills.md`）**：
  - 设计 token（F 类）2026-09-30 已整体退役，但设计档案与 skill 瘦桩仍把它列为现行产出 ⇒ 按「退役即删」清掉残留陈述。
* **【装配集同步】（`scripts/pkg_digest.py`, `shared/gates.md`）**：`extensions/` 已纳入装配拷贝集而摘要白名单未覆盖（F30 门红）⇒ 补齐；门总账计数按实况更新。

### 🧭 图谱与抽取口径收口（设计评审驱动，2026-10-15 第二轮）

* **【图谱落点与工作树纪律】（`adapters/_graph.py`, `shared/stack-profile.md` §3.6, `DESIGN.md` D77）**：
  - **标记落点定形 = 项目根 `.adapter-out/`（本层自己的运行时目录）**：本轮一度把它挪进结构环的 `--out` 产物目录，**已回退**——§3.1 那条路径是给适配器产物定的，而本层不是适配器、消费者还跨 structure/apply 两个环，挂进单环目录会让只跑 apply 的项目凭空长出 `spec/structure/`。真正缺的是**约定本身没写下来** ⇒ 现在写进 §3.6，并明确「启用图谱的项目应 gitignore `.adapter-out/`」；
  - 新增两条**硬约束**：**后端自己的索引库不得落进项目工作树**（否则新鲜度键自激成永不稳定的全量重建）；**图谱通道的文件清单必须过与 regex 通道同一份 `IGNORE_DIRS` 剪枝**（`cgc index` 无 exclude 旗标，依赖目录进池即产假事实，`routes._prune`）；
  - 非 git 工作树 ⇒ 显式 WARN + 每次全量重建（此前直接硬崩，违背「声明了而环境不满足 ⇒ 响亮降级」）；`ensure_index` 记明**单进程假设**；
  - 图谱能力在设计档案里**此前零记录**（同期实现层增强 D70/D73/D76 都有 D 号）⇒ 补 **D77**，把消费面、落点、枚举纪律、启用方式一次定形。
* **【api 口径：RPC 形态与 D42 窄化】（`adapters/api.py`, `shared/stack-profile.md` §3.2/§3.5, `DESIGN.md` D42）**：
  - RPC / action 形态的 `method` 由 `POST` 改记 **`RPC`**——调用点看不出传输动词，写 `POST` 是不可取证的猜测（`path` 仍记方法名本身，不合成 URL）；
  - **D42 窄化声明**：其「不收前端 client 调用」以「存在后端 / 描述侧真相源」为前提；纯前端无描述态下前端调用点即 D 类唯一机械可抽源（此前本轮实现整体踩在这条未退役的反向决策上）；
  - 转指针形态（探测到机器可读描述 ⇒ 丢弃源码抽到的端点）**必须出声**：stderr 报出丢弃条数，不再静默清空。
* **【行键粒度：适配器不去重，渲染期折叠】（`scripts/refresh_structure.py`, `shared/stack-profile.md` §3.2, `DESIGN.md` D69）**：
  - 新增 `dedup_by_row_key`：同一事实文件内的重复行键折叠为首行（行键级合并以「行键唯一」为前提）；
  - 适配器**保持不去重**——实测真项目 25 个重复（方法,路径）键**全部跨域**，是「同一端点被两个域各调一次」的合法事实，全局去重会抹掉另一个域唯一的那条。
* **【models 枚举补面与措辞更正】（`adapters/models.py`）**：
  - 新增**同文件「别名 / 枚举名 → 取值」旁表**：`export type S = 'a' | 'b'` 与 `export enum S {…}` 自身不成行（`table · field` 是行键，接不住独立枚举），但引用它们的字段现在能拿回取值（真项目实测补回 45 处、枚举 67 → 112）；
  - 更正失实措辞：跨文件类型引用是**直接丢弃**（渲染期只做 `source_file` → 行的域归属、不解析类型引用，且 `关系` 是适配器列），不是「留给渲染期」；
  - 「先量」统计：stderr 报出顶层枚举/别名声明数与补回处数（`global-rules.md` §12）。
* **【静默跳过一律出声】（`adapters/routes.py`, `shared/closeout.md`）**：
  - routes 的**常量路径**条目（`path: SOME_CONST` 静态不可求值）跳过时 stderr 报数——静默会让 §9 报告的「取证范围」少报；契约同步写明 `auth` 只记可静态取证的**认证**门、且渲染表当前无该列；
  - `closeout.md` 触发表新增一行：结构环产出/刷新域级文件时须对账**域清单确认门**（未过目的候选域要么过目、要么登记待确认）。
  - 新增/更新判据：M55（图谱枚举剪枝）/ M56（渲染期行键折叠）/ M57（RPC 方法值）/ M58（非 git 降级）。

### 🔎 D 类形态改判：先问人，再问代码（2026-10-15 第三轮）

* **【判定主体纠正】（`shared/stack-profile.md` §3.5, `rings/structure/reference.md` §4 D / §6 步 1 / §9, `templates/structure/_meta.json`）**：
  - 原口径「项目**是否自带**机器可读接口描述**由适配器探测**」把「仓内探测不到」等同于「无描述」——而描述**常常不在本仓库**（网关 / 独立文档站 / 运行时端点）。实测有接入项目的 `categories.D` 记着「后端经网关暴露 RPC action；网关文档地址不随仓库分发」：仓内探测不到，但描述确实存在；照旧口径会被误判为「无」⇒ 去枚举调用点，产出一张本不该存在的清单。
  - 改判：D 类形态**先问用户**（与 A 类「先问是否纳入」、图谱「探测后提议」同一批确认门问题）；答「有」（地址可在仓外）⇒ **指针形态** + `adapters.api` 置 `null`（**不接源码枚举适配器**，否则清单与指针混写）；答「无」⇒ 才落源码枚举；**未答 ⇒ 不得当「无」**，记 `categories.D` 并在 §9 点名「未取证」。
  - 顺带更正：§3.5 原文举例「用一个读取该描述的适配器（**如 `openapi`**）」，而包内并无出厂 `openapi` 适配器（`adapters/` 只有 routes / api / models / tests）⇒ 如实写明「包内暂无出厂实现；仓内文件形态项目可自带，**仓外地址形态无需适配器**、指针由 agent 记」。

---



## [v0.1.0-beta.16] - 2026-10-15

### 🚀 结构环链路闭环与 R8 完结收口 (Structure Ring Chain Close-Out & R8 Closure)

* **【链路闭环与诚实基线】（`scripts/refresh_structure.py`, `validators/validate_structure.py`, `templates/`）**：
  - 适配器链路全闭环（F25），打通结构环元数据消费与验证；
  - 诚实基线推进（F26）与单遍渲染优化（F27），规避渲染冗余与基线偏离；
  - 引入 Tour 消费者挂载（F29）与装配集合指纹比对（F30，`pkg_digest.py`）；
  - 严格规范 TODO 标记校验（F31）与桩代码自动补齐生成（F32）。
* **【安装与治理安全加固】（`install.sh`, `scripts/atlas_check.py`, `validators/validate_adr.py`）**：
  - 安装器工作区脏树拦截守卫（F34），避免污染开发中未提交的工作区；并在纯拷贝态下优雅跳过无 `install.sh` 的自检用例；
  - 规范级相对引用锚点支持（F34b）与指针形态覆盖豁免机制（F33）；
  - ADR 循环依赖修复指引与收口记录矩阵（F36），提升架构决策记录的自愈排查效率。

---

## [v0.1.0-beta.15] - 2026-10-15

### 🔧 规范与门禁一致性加固 (Canonical Consistency & Reconcile Closure)

* **【门禁用例实收口径对齐】（`shared/gates.md`, `tests/test_canonical_consistency.py`, `README.md`）**：
  - `gates.md` 逐文件用例计数登记改按 pytest 实收口径（AST 顶层 `test_*`），消除因字符串字面量 fixture 内嵌被测写法导致的幽灵计数偏差（全仓真实用例数对齐 AST 实收口径）；
  - 新增 M10 钉子门禁，确保登记口径真实可证伪；
  - README tests 徽章去写死数字，从根因上杜绝版本发布时的徽章数值漂移。
* **【R6 闭环一致性实施】（`scripts/gen_e2e_scripts.py`, `validators/validate_testids.py`, `patches/project-wiring/apply-wiring.py`）**：
  - 严格执行三把钥匙契约（`review: null` / 未声明走缺省严格门）；
  - `validate_testids.py` 收窄同文件重复告警，仅针对静态属性同形态重复报警，豁免模板壳静态与 JS 命令式赋值混用；
  - `apply-wiring.py` 接线载体优先级遵循 `pyproject.toml` > `setup.cfg` > `pytest.ini`，不再注入已退役的 `pythonpath` 补丁。

---

## [v0.1.0-beta.14] - 2026-10-15

### 🚀 AI 原生自愈与免阻断架构升级 (AI-Native Resilience & Zero Friction)

* **【生成器自愈化】审查门免阻断自愈 (`scripts/gen_e2e_scripts.py`, `_support/stack_profile.py`, `validators/validate_stack_profile.py`)**：
  - 彻底终结 `review.json` 缺失直接抛 `exit 2` 阻断写盘、逼迫 AI 人工造假报告桩的历史包袱；
  - 规范化扩充 `e2e.review` 字段白名单与模式枚举：支持 `mode: gate`（严格审查门）、`mode: auto-baseline`（自愈基线模式）与 `mode: off`（免审）；
  - 当项目处于存量接管形态（`origin: adopt`）或**显式声明** `mode: auto-baseline` 时，若未发现历史审查报告，在全量校验通过后自动自愈生成最小可证伪基线审查报告（`*-adopt-baseline` 或 `*-auto-baseline`），放行脚本写盘；
  - **三把钥匙语义（R6 对账定稿）**：`review: null` / 未声明 = 执行器取会话默认（契约原语义）⇒ 走缺省严格门，**不再隐式免审**；`mode: off` = 免审 ⇒ 直接放行且不落基线（不制造「形式审过」假象）。
* **【提取器增强】JS 动态 testid 提取与文件级 counts 重构 (`validators/validate_testids.py`)**：
  - 全面支持原生 JS 命令式赋值语法：捕获 `el.dataset.testid = "..."`、`el.dataset['testid'] = "..."` 与 `el.setAttribute("data-testid", "...")`（含单/双引号、JSX 花括号与可枚举模板字符串）；
  - 引入源码注释预清洗（`strip_comments`），自动剥离 HTML 注释与 JS/TS 行/块注释，避免废弃 id 产生幻影报错；
  - 重构 `counts` 全站唯一规则为「声明文件数」，同一文件内的 HTML 与 JS 共存、条件分支或动态列表赋值计数为 1（天然豁免），跨文件冲突严格报警，业务代码无需在 HTML 补 `<template>` 假桩；
  - **同文件重复 WARN 收窄（R6 对账定稿）**：仅对**静态属性同形态重复**报警；「模板壳静态声明 + JS 命令式赋值」混用为 vanilla JS 合法惯用法，豁免不报。
* **【存量脚手架自适应】Python pytest 配置兜底重构 (`patches/project-wiring/apply-wiring.py`, `adapters/tests.py`)**：
  - `adapters/tests.py` 输出标准 `python3 -m pytest` 命令形态，cwd 自动入 `sys.path`，从根因上消除模块导入找不到路径的环境摩擦；
  - **接线兜底退居诚实角色（R6 对账定稿）**：`apply-wiring.py` 不再注入 `pythonpath = .` 环境补丁（随 F23 退役），只承接 `ac` marker 注册；**载体优先级 = 已有 pyproject.toml / setup.cfg > 既有 pytest.ini（只补 marker）> 新建 pytest.ini**，杜绝「接线复活被清掉的补丁」。
* **【Mock 零步探针容忍】打桩用例自动免除零步恒真探针 (`scripts/gen_e2e_scripts.py`)**：
  - 识别用例分片中的 `mock:` 段，整体免除注入零步基线探针（`probes`），彻底根除外部接口打桩导致的页面初始容器被误判为“恒真（假阳性）”；
  - 未被任何 step 操作的容器在场断言（`visible`，声明块成员）由前置 `toHaveCount(1)` 守卫环覆盖而豁免（真跑实证定形）；
  - 用例本身的 Playwright 测试体 100% 完整保留严格断言与打桩审计，AI 与开发者无需再机械式手写 `initial:` 豁免前缀。

---

## [v0.1.0-beta.13] - 2026-10-14

### 🚀 核心协议全栈化与沙箱前沿加固 (Core Protocols & Usability)

* **`e2e.mock` 协议支持 `mode: auto` 混合穿透与白名单扩充 (`scripts/gen_e2e_scripts.py`, `validators/validate_stack_profile.py`, `validators/validate_e2e_mocks.py`)**：
  - 正式支持 `e2e.mock.mode: auto`，在全栈/混合测试场景下，未命中桩表的路由自动调用 `await route.continue();` 穿透访问真实后端，彻底解决纯前端 fail-loud 误掐真实 API 的问题；
  - `stack-profile` 的 `e2e.mock` 白名单正式扩充收录 `fixtures_dir` 并支持动态目录路径解析；
  - 增强网络 Mock 外部 URL（`https://*`）通配匹配与 `api_prefix` 智能兜底。
* **全局 Node Playwright 健壮探测与 Python CLI 防御 (`scripts/atlas_check.py`, `scripts/e2e_console.py`, F19)**：
  - 支持纯 Python/存量项目（`node_modules: null`）通过全局 Node 模块（`npm i -g @playwright/test`）直接运行 E2E 真跑；
  - 引入 `_is_node_playwright()` 文件内容特征检测，精准过滤 PATH 中同名的 Python Playwright CLI；
  - 增加对标准 Unix `<prefix>/bin` 与现代 `npm prefix -g` 的候选路径推导。
* **存量沙箱 `origin: adopt` testid 单向子集校验 (`validators/validate_testids.py`, F20)**：
  - 在存量接管模式下，用例未引用的存量历史 testid 降级为 WARN/INFO 记录，彻底解除对未改动老元素的强制绑架；
  - 对新需求用例中声明的 testid 依然维持严格双向闭环。
* **架构决策记录（ADR）演进链拓扑成环拦截 (`validators/validate_adr.py`)**：
  - 校验器内置 DFS 染色法有向无环图（DAG）检测，精准捕获 `0001 -> 0002 -> 0001` 等循环废弃回环（`adr_cycle_detected: WARN`），守卫架构演进终态健康。

---

## [v0.1.0-beta.12] - 2026-10-14

### 🐛 缺陷修复与沙箱实测回灌 (Bug Fixes & Usability)

* **`seed × models` 对账门字段解析缺陷修复 (`validators/validate_e2e_index.py`, F14)**：重构数据模型解析存储为 `dict[str, set[str]]`，支持单表多行多字段累加收集与精确成员判定，根治以往首行 `setdefault` 遗漏后续字段及子串模糊匹配引发的校验误杀。
* **`install.sh` 刷新时保留 `.atlas/runs/` 运行态数据 (`install.sh`, F18)**：装配刷新逻辑由整包物理删除改为白名单子目录清理（`shared rings apply scripts templates adapters validators patches tests _support`），避免冲掉包含后端 AC 覆盖率基线及控制台快照的非 git 跟踪运行态数据。
* **结构环 `categories` A/H 键值解析前缀容错 (`validators/validate_structure.py`, F17)**：引入关键字前缀扫描提取器 `_cat_token`，优先匹配 `covered`、`skipped`、`added` 合法状态词，兼容形如 `"H": "H: skipped"` 的书写习惯。
* **适配器空产物避免意外清空既有结构事实 (`scripts/refresh_structure.py`, F16)**：在 `render_routes` 中增加空产物守卫，当 routes 适配器在非支持技术栈上输出 `{"items": []}` 且目标 `routes.md` 已存在有效手工事实行时，自动保留既有内容并输出告警，防止静默清空事实表。
* **存量接入指南补充实现期薄桩步骤 (`docs/guide/legacy-adoption.md`, F15)**：在存量接入步骤 Checklist 与命令指引中显式补充 `python3 .atlas/scripts/gen_testid_stub.py --root .` 生成实现期薄桩（`.trellis/spec/conventions/testid.md`），闭环开户标准，避免首日 `validate_testids.py` 硬门禁报红。
* **官网架构设计文档标题归一 (`docs/design/`)**：结构环设计文档标题统一归一为《结构（逆向）环设计与实体边界治理》，规范文档体系表达。

---

## [v0.1.0-beta.11] - 2026-10-14

### 🚀 架构解耦与官网升级 (Architecture & Documentation)

* **彻底解耦 open-zk-kb（知识库与台账子系统退役）**：移除开发期自举的 `kb_*` 脚本与 `validate_ledger.py`（核心门禁校验器精简为 9 个）；域级 AC 编号唯一性强校验契约完整归位至 `validators/validate_prd.py`；全量清理契约、装配脚本 `install.sh` 与门禁清单中对旧台账的冗余依赖。
* **官网全新上线「设计方案」栏目 (`docs/design/`)**：新增 5 篇高质量深度架构设计解析（《架构总览与分层设计》《结构环与实体边界治理》《PRD 环与业务规则闭环》《E2E 环与确定性断言工程》《工程分发与线束装配体系》），全面解密 Atlas 核心实现机理。
* **工程叙事严谨化与概念术语对齐**：全面摒弃情绪化修辞，回归务实的第一人称工程手记风格；对齐「双线束模型」（项目级工程线束 vs 需求级业务线束）与「两道全局护栏」概念体系；完善内置 7 大技能清单与 Pi Agent 扩展硬化指南（rtk 退出码保真性告警与 warm-cache 真实计费口径）。

### 🐛 缺陷修复与沙箱实测加固 (Bug Fixes & Usability)

* **Playwright 慢动作回放改由环境变量注入 (`scripts/e2e_console.py`)**：修复 `e2e_console` 回放时拼接 `--slowmo=<N>` CLI 旗标导致 Playwright 1.64 `test` 子命令报 `unknown option`（exit 1）的缺陷。改由 `ATLAS_SLOWMO` 环境变量向 Playwright 配置文件的 `launchOptions.slowMo` 注入，保障无头/有头慢动作回放稳定性。
* **E2E 生成器清扫退役页孤儿 spec (`scripts/gen_e2e_scripts.py`)**：修复 `--apply` 模式未清扫已退役页面用例导致孤儿 spec 遗留并在后续被测试拾起报错的问题。dry-run 显式上报退役变更，`--apply` 精准只清理带 `AUTO-GENERATED` 标记的孤儿用例。
* **存量非规范 testid 兼容性放行 (`validators/validate_testids.py`)**：对遗留存量非标 testid 降级为 WARN 警告放行，仅在新增违规分片时硬阻断，降低既有存量工程（Adopt 模式）接入阻力。

---

## [v0.1.0-beta.10] - 2026-10-13

### 🐛 缺陷修复与体验增强 (Bug Fixes & Usability)

* **PRD 规则表列序精准指路 (`validators/validate_prd.py`)**：优化 §四 业务规则表解析体验。当用户声明了「所属功能」表头但未按契约排在第 3 列时，不再输出具有误导性的“未声明所属功能”，而是明确给出友好的指路报错：指出所属功能应在第 3 列（规则 ID ｜ 规则内容 ｜ 所属功能 ｜ …）及当前实际列位，大幅提升排查效率。
* **Playwright 运行通道环境变量覆盖 (`scripts/gen_e2e_scripts.py`)**：在生成的 `playwright.config.ts` 中增加 `channel: process.env.ATLAS_PLAYWRIGHT_CHANNEL` 覆盖机制。支持开发者在需要时直接通过环境变量（如 `ATLAS_PLAYWRIGHT_CHANNEL=chrome`）复用宿主机 Google Chrome 浏览器，免去非必要重新下载大体积 Chromium 二进制的等待。

---

## [v0.1.0-beta.9] - 2026-10-13

### 🐛 缺陷修复与门禁严苛化 (Bug Fixes & Hardening)

* **PRD 目录卫生门 (`validators/validate_prd.py`)**：新增「参数0 目录规范」校验门，严禁 `product/prd/` 目录下存在非法子目录（如 `domains/`）或非标准命名 Markdown。彻底杜绝因目录层级脱节导致 `domains` 计数为空、使“待决策登记非空却产出域级 PRD”被静默穿透发放虚假通行证的缺陷。
* **占位符检测排除合法元数据 (`validators/validate_prd.py`)**：在参数 2 零占位符扫描中，增加对 frontmatter 合法元数据行（如 `domain_code: TODO`、`domain: todo`）的排除，消除待办类合法领域命名的误判。
* **AC 代码对账口径收口平铺 (`validators/validate_ac_alignment.py`)**：将 `collect_prd_acs` 收敛为严格对齐平铺契约的发现范围（`prd.md` 与 `*-prd.md`），显式隔离并排除 `reviews/` 等非需求子目录，防止评审历史或废弃文档中残留的旧 AC 污染已声明白名单。
* **E2E node_modules 相对路径锚定 (`scripts/atlas_check.py`)**：修复 `check_e2e` 中提取的 `node_modules` 相对路径未与传入的 `root` 参数锚定导致跨 CWD 运行时误判的问题（`root / nm_rel`），并在可执行文件缺失时追加友好的安装指引提示（`npm i -D @playwright/test`）。

### 🧪 测试套件 (Tests)

* 补充目录规范变异测试 `test_prd_illegal_nested_directories_fails`，`shared/gates.md` 对应台账对齐至 76 条。
* 补充 AC 对账隔离评审文档测试 `test_ac_alignment_ignores_reviews_and_subdirectories`。
* 补充外部 CWD 路径锚定测试 `test_check_e2e_node_modules_anchored_to_root`。全量用例扩增至 348 条，保持 100% 通过。

---

## [v0.1.0-beta.8] - 2026-10-12

### 🐛 缺陷修复与鲁棒性增强 (Bug Fixes & Hardening)

* **全量体检生成物容错 (`scripts/atlas_check.py`)**：修复 `gen_e2e_scripts.py` 混杂前置警告日志导致 `json.loads` 解析失败误报 `WARN 生成器输出非 JSON` 的缺陷，增加正则提取 JSON 块容错。
* **事实刷新冷启动容错 (`scripts/refresh_structure.py`)**：修复新建工程在尚未首建结构环时被 Trellis `after_finish` 钩子调用抛出 `ERROR: 缺少 _meta.json` 导致退出码 1 的问题，改为友好 `SKIP` 并以 0 正常退出。
* **E2E 分片块缺字段报错指名 (`validators/validate_e2e_index.py`)**：细化用例分片缺少必填字段（如 `precondition`）时的报错信息，从模糊的 `缺字段=['E2E-xxx']` 优化为精确指名 `E2E-xxx(缺:precondition)`。
* **AC 代码级对账递归扫描 (`validators/validate_ac_alignment.py`)**：修复 `collect_prd_acs` 使用单层 `glob("*.md")` 漏扫 `product/prd/domains/` 域级 PRD 验收准则的问题，改为 `rglob("*.md")` 递归检索。
* **防退化棘轮防污染守卫 (`validators/validate_ac_alignment.py`)**：修复校验器无论是否 FAIL 均无条件落盘基线的缺陷，增加 `res.status != "FAIL"` 状态守卫，防止测试注入坏输入污染历史基线。
* **CLI 出厂测试副本态隔离 (`tests/test_cli_commands.py`)**：为 CLI 测试增加 `pytest.mark.skipif`，在目标项目 `.atlas/tests` 副本态（不分发 `bin/` 与 `install.sh`）下优雅跳过，保证项目端全量体检绿灯。

---

## [v0.1.0-beta.7] - 2026-10-10

### 🚀 新增功能 (Features)

* **CLI 自身升级 (`atlas upgrade`)**：支持一键检查并通过 npm 更新全局 CLI 至最新版本，支持 `--tag beta` 体验预发布通道以及 `--dry-run` 预览升级命令。
* **项目线束增量刷新 (`atlas update`)**：在目标项目目录下运行，可平滑增量更新 `.atlas/` 治理契约与各平台 skills 瘦桩，具备幂等安全性，不覆盖已有业务代码与技术栈画像。
* **共享内核库 (`_support/`)**：
  * `siblings.py`：标准化的包内模块加载器，提供纯净的独立导入与执行隔离。
  * `case_block.py`：增强型 E2E 用例块解析与结构化提取能力。
  * `stack_profile.py`：健壮的技术栈画像（`stack-profile.yaml`）解析与元数据提取器。
* **回灌工具 (`scripts/backflow.py`)**：提供项目级资产变更向上游主仓库回灌对齐的自动化支持。

### 🛡️ 架构治理 (Architectural Improvements)

* **纯项目级解耦（对标 Trellis 范式）**：
  * 彻底移除全局 Pi 扩展（`atlasharness.ts`）与全局 skills 声明，解决因全局包安装导致所有会话提示词被污染的痛点。
  * Skills 改为按需装配：仅在项目执行 `atlas init` 或 `atlas update` 时，在目标项目的本地目录（`.agents/skills/`、`.claude/skills/` 等）下发轻量瘦桩，离开项目即恢复纯净环境。
* **包构建优化**：将 `_support/` 共享内核与 `CHANGELOG.md` 显式纳入 npm 分发白名单，确保离线与全局安装均能完备解析。

### 🧪 测试与质量 (Tests & Quality)

* 新增全套命令级回归测试套件：`test_cli_commands.py`、`test_backflow.py`、`test_shared_kernel.py`、`test_nested_repo_gitlink_guard.py`。
* 项目全套回归测试增至 335 项用例，保持 100% 稳定通过（332 passed, 3 skipped）。
