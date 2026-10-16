# 提案：路由适配器的识别完整性与挂载前缀合成；事实区渲染的往返一致

> 提案编号：RFC-20261016-01
> 提案作者：@Agent 起草（会话内）
> 关联状态：草案 v2 (Draft) —— v2 已吸收独立评审 7 条 finding（全文见 §6）
> 影响范围：适配器 (adapters) | 脚本工具 (scripts) | 契约正文 (shared/stack-profile.md) | 环契约 (rings/structure) | 门册 (shared/gates.md) | 决策/变更登记 (DESIGN.md / CHANGELOG.md) | 测试 (tests)
> 关联 issue：`#15`（[tool-semantic] routes 适配器候选文件闸）、`#16`（[tool-semantic] 事实区渲染层多行单元格）、`#17`（[rule-friction] `atlas_check` 包自检门落在不会被落下的目录上；本批附带）｜ 批内 F 号：**F46**（#15）/ **F47**（#16）/ **F48**（#17）；决策号顺延至 **D83–D86**（D82 已被并存批「用例 ID 文法」占用）

---

## 1. 现象与取证 (The Problem & Evidence)

### 1.1 触发形态（抽象）

**案 A（`#15`，识别不完整 + 静默）**

* **规则 / 环节**：`adapters/routes.py` 的 `collect_js_routes`（候选文件闸：`if "rout" not in f.name.lower() and f.parent.name != "router": continue`）。
* **触发时机**：对「一张站点级路由表 + 每个功能模块各自一张入口表」形态的项目跑 `routes` 适配器。
* **具体行为**：① 模块入口表的**文件名不含 `rout`** ⇒ 整文件被**静默排除**（不出声、不计数、不进 `source_files`）。实测该接入项目：**声明路由表的文件 11 个（数组形态 8 + JSX `<Route>` 形态 3），实际扫描 1 个 ⇒ `items` 19 条**。② JSX `<Route path=…>` 形态**根本没有解析器**（只认 `routes: [...]` 数组）。③ 于是 `structure ↔ 代码` 的对账门对**全部 32 条缺失路由恒等绿灯**。
* **与既有纪律的落差**：同一函数对「`path` 非字面量」的条目**有** WARN（`有 N 条常量路径…已跳过——取证范围少报这些条目`）。出声道具已在手边，只是没用在候选闸上——这是「静默少报」，不是「已知的范围收窄」。

**案 B（`#16`，写入即损坏）**

* **规则 / 环节**：`scripts/refresh_structure.py` 的 `render_table` / `parse_rows` 往返；接线前置判据（`rings/structure/reference.md` §6.2「产出非空且逐条自洽」）。
* **触发时机**：接线一个 `items` 字段携带**多行取值**的适配器（本栈是「对象 / 函数类型字面量作为类型文本」）。
* **具体行为**：`render_table` 只转义裸竖线，假定单元格单行。多行取值写进单元格后该行在文件里断成多行：`parse_rows` 把首行读成列数不符（`old_rows_by_key` 要求 `len(r)==len(header)` ⇒ 丢弃）、其余行不以竖线开头（跳过）⇒ ① 该行**从机器可读事实表消失**；② 每轮刷新都把同一批行判为「新增」⇒ **结构漂移标记常驻、baseline 棘轮永不释放**（一个永不收敛的假告警）。

**案 C（`#17`，附带）**

* **规则 / 环节**：`scripts/atlas_check.py` 的无条件 `pytest .atlas/tests`；对照 `install.sh:149,154`（拷贝列表含 `tests`）、`scripts/pkg_digest.py` 的 `ASSEMBLY_COVER_DIRS`（含 `tests`）、`package.json` 的 `files`（**不含 `tests`**）。
* **触发时机**：任何经 npm 全局包装配的项目跑 `atlas_check`（全量模式）。
* **具体行为**：三张「装配面」表**不同步** ⇒ npm 分发不含 `tests/` ⇒ install.sh 的拷贝是空操作 ⇒ `.atlas/tests` 恒不存在 ⇒ 该门恒 `FAIL`（`file or directory not found`，退出码 4），而 **`--fast` 一跑就 OK** ⇒ 接入项目的第一次门自检就显示一道自己修不了的红。

### 1.2 客观证据与日志 (Minimal Evidence)

```text
# 案 A：11 个声明文件只扫到 1 个（该 root 内）
$ python3 adapters/routes.py --root <root> --out /tmp/routes.json
[routes] WARN: <site-table-file> 有 1 条常量路径（path 非字面量）已跳过
[routes] 19 条路由 / 1 个源文件（backend=regex） -> /tmp/routes.json

# 案 B：连跑第二、三次 --chain，每轮都报同一批键级「新增」
$ python3 scripts/refresh_structure.py --root <root> --chain
  ⚠ 结构漂移（未登记键级变更…）： models +['<table> <field>', …] -[]
  baseline: 存在未终审键级漂移 ⇒ 冻结待终审
#   接线批次实测：82/1859 条 type 含换行（折叠成单行后长度中位数 86、p90 198、最大 608）

# 案 C
$ python3 scripts/atlas_check.py --root <root>            # 全量
  FAIL 对齐测试(.atlas/tests)  ERROR: file or directory not found: .atlas/tests   # 退出码 4
$ python3 scripts/atlas_check.py --root <root> --fast     # 同一项目
  OK
$ ls <root>/.atlas/     # 无 tests/
_support adapters apply extensions patches rings runs scripts shared templates validators
```

### 1.3 缺陷与能力的边界（评审 F 组纠正后的口径）

评审指出（采纳）：**案 A 的「模块相对路径」本身不是原契约未履行的缺陷**——C 类契约只规定「全站总表 + 行键口径」，从未规定适配器承担跨文件挂载推断；**合成属新增能力**。故本提案拆成两条彼此独立、可单独回退的决策：

| 决策 | 性质 | 本批 |
|---|---|---|
| **D83** 识别完整性（两形态都解析）+ 出声（声明数 / 扫描数 / 丢弃数） | **缺陷修复**（§1.1 案 A ①②） | 必做 |
| **D84** 挂载前缀合成（含歧义口径与降级） | **新增能力**（§2.1 #15 条 2） | 本批落地，可单独回退 |
| **D85** 渲染层「写出 ⇒ 读回」不变式 + 往返自校 | **缺陷修复**（§1.1 案 B） | 必做 |
| **D86**（附带）装配面三表同步（`package.json.files` ⇔ `install.sh` ⇔ `ASSEMBLY_COVER_DIRS`） | **缺陷修复**（§1.1 案 C） | 一行 + 一条守恒钉；可单独回退 |

**为何 D84 值得做**（而不是停在 D83）：只做 D83 的话，模块级表会以**模块相对路径**（`/create`、`/:tab`）进入一张以 `(应用, 页面/路由)` 为行键的**全站**表 ⇒ 跨模块同名路径被 `dedup_by_row_key` 折叠成一行 ⇒ **不是少报，而是多报假事实**——比缺口更糟。所以 D83 必须有 D84 兜住，否则它连「放宽闸」这一步都不能做。

---

## 2. 决策与权衡 (The Decision & Trade-offs)

### 2.1 核心定案 (The Decision)

#### D85（#16，`scripts/refresh_structure.py`）

1. **写侧单行化**：拼单元格前把 `\r\n|\r|\n` → `<br>`，随后转义裸 `|`。不变式（**逐单元格**，评审 F4 收窄为可判定口径）：

   ```
   parse_rows(render_table(header, rows))[1:]  ==  [[single_line(c).strip() for c in row] for row in rows]
   ```

   即「盘面读回值」必须等于「单行化后的取值」，表头行除外。
2. **键归一化等价**（评审 F3）：`_norm` 把 `<br>` 与换行视作**等价**（`<br>` → 空格后再折叠空白），使「适配器原值（含真换行）」与「盘面读回值（含 `<br>`）」归一化后相等 ⇒ 键稳定性成为**无条件成立**的事实，键列含换行时也不再造幻影漂移。
3. **渲染即自校**（评审 F4）：`render_table` **内部**对渲染出的字符串做上述逐单元格比对（**与是否写盘解耦**，dry-run 同样出品）；不一致 ⇒ stderr WARN（指名 `where`、首个不符的行/列、期望值与实得值），并把该表计入 `results` 的 changed 面。取 WARN 不取硬错：本脚本是 `after_finish` hook，契约规定「hook 失败只告警、不阻塞任务」（§8）。**真正会咬的门是单测**（§3.1 的 M-R1/M-R2）。
   * 取 `<br>` 而非空格：保留原取值的**行结构**。空格会把 `{ a: string <换行> b: string }` 拼成 `{ a: string b: string }`，两个成员之间失去分隔语义（实测该形态就出现在类型字面量里）。

#### D83 + D84（#15，`adapters/routes.py`）

**D83 —— 识别完整性 + 出声**

1. 候选判据从「文件名」改为**内容**：文件文本含路由签名即候选（数组形态命中 `_route_array_starts`；或含 `<Route` / `<Routes` 标签）。廉价预筛 `"rout" not in text.lower()` 保留，但**只用于省去解析，不承担正确性**。
2. JSX 形态新增解析器，**带嵌套深度栈**：`<Route path="a">…<Route path="b"/></Route>` ⇒ 子路径 `a/b`（同文件内前缀直接合成，评审 `missing_alternatives` 提的内核已吸收）。`path` 非字面量（常量 / 复杂表达式）⇒ 跳过并计数，与数组形态既有纪律一致。
3. **出声**：stderr 逐行报「声明表的文件数 / 站点级 / 已挂载 / 未挂载（逐文件原因）」；同一组计数写进输出 JSON 新键 `coverage`（字段语义登记进 `shared/stack-profile.md` §3.2 —— 评审 F5）。

**D84 —— 挂载前缀合成（判定顺序，每步失败 ⇒ 该文件条目全部丢弃 + 计数，绝不产出模块相对路径）**

1. **符号表**（同文件内）：`const X = lazy(() => import('…'))` / `import X from '…'` / `X = lazy(…)` ⇒ `X → specifier`。条目里的 `component` 字段若已是 specifier 形态（`.` / 别名开头）则直接用。
2. **specifier → 文件**（`resolve_spec`；评审 F1 把口径改成可判定的）：
   * 相对（`.` 开头）：按该文件目录做路径运算，在 `p` / `p.<已知后缀>` / `p/index.<已知后缀>` 里取**唯一存在**者；
   * 别名（其他）：丢掉第一个 `/` 之前的段得 `tail`；候选 = 枚举集里**路径含 `/{tail}/`**（或等于 `tail` + 后缀）的项；**再用「该文件也声明表」过滤**；过滤后仍不唯一 ⇒ **未解析**（原因「别名命中不唯一」）。
3. **挂载边**：站点级表的条目 `(路径, 解析出的目标文件)`，且目标必须**本身也声明表**且 ≠ 自身 ⇒ 记一条边 `前缀 → 目标文件`。
4. **前缀取值**（评审 F2 补的歧义口径）：目标文件入边**恰好 1 条** ⇒ 用该前缀；**≥ 2 条 ⇒ 未解析 + 计数**（把候选前缀全部列进报告）；**成环 ⇒ 未解析 + 计数**。
5. **站点级 / 模块级判定**（只用**本地证据**，不依赖别的文件）：
   * 有入边 ⇒ 模块级，前缀 = 入边前缀；
   * 无入边 且**无 `basename` 属性** ⇒ **站点级**（路径原样，不做合成）；
   * 无入边 且 `basename` 为**字面量** ⇒ 模块级，前缀 = 该字面量；
   * 无入边 且 `basename` **非字面量** ⇒ **未解析 + 计数**（原因「基名不可求值」）。
6. **合成**：`前缀 + 本地路径`，规范化（折叠重复斜杠；前缀 `"/"` 视作空；保留 `:param`）。
7. **交叉自证**：模块文件同时写了字面量 `basename` ⇒ 与合成前缀比对：一致 ⇒ 双源确认；不一致 ⇒ WARN（两个值都写进文案）并**采用入边前缀**（公开路径由挂载方定义）。

#### D86（#17，附带）

`package.json` 的 `files` 补 `tests`（三表同步），并给现有的同步钉补上第三张表的判据（`package.json.files ⊇ ASSEMBLY_COVER_DIRS`）。

### 2.2 考虑过的备选方案及否定理由 (Considered Alternatives)

* **A（只放宽候选闸 —— 原 `#15` 里我提的 ①）**：会产生模块相对路径进入全站表、被 `dedup_by_row_key` 折叠成假行键。*否定成立*（评审同意）。**采纳为降级路径**：仅当 D84 第 4/5 步判「未解析」时才走丢弃。
* **B（让人在 `stack-profile.yaml` 声明「模块 → 挂载前缀」）**：挂载关系就在代码里，人工再写一遍 = 第二真相源与漂移面。*否定成立*。
* **C（只认字面量 basename，不做挂载映射）**：只覆盖「模块自己写死 basename」的那部分；用辅助函数推导 basename 的模块收口不了。*否定成立*；**采纳为 D84 第 5 步的一个分支**（不与 B 冲突：一个读代码，一个让人写）。
* **D（只修 `models` 适配器，折叠 `type` 里的换行）**：不变式是渲染层的，任何适配器 / 任何字段的多行取值都会撞；只修一个适配器等于把纪律变成「每个适配器各自遵守一条没写进契约的约定」。*否定成立*。
* **E（让 `parse_rows` 容错，读回多行行）**：读回需要在写侧没提供边界信息的前提下**猜行边界**。*否定成立*。存量已损坏文件在下一轮 `--apply` 整块重写而自愈，不需读侧补救。
* **F（连「页内 tab 驱动的伪路由」一起收）**：不是路由声明（没有路由级 path 字面量，只有 tab key + 编程式跳转），收它要猜基名与 tab 语义。**本轮明确不收**，该形态继续由 agent 语义撰写。
* **G（评审 `missing_alternatives`：JSX 同文件嵌套直接拼前缀，替代挂载映射）**：已取证——本项目的站点表是**数组**形态、3 条 JSX 表都在**模块级** ⇒ 该方案对本项目覆盖 **0 条**，不能替代 D84；但它的**技术内核已被 D83 条 2 的嵌套深度栈吸收**（同文件前缀与跨文件挂载共用同一套前缀机制）。*作为替代方案否定，作为实现细节采纳*。
* **H（评审 F7 提及的替代：本批只改装配面之外的东西以回避装配戳）**：不成立——两案的代码全在装配集白名单目录内，回避即等于不修。

### 2.3 必须警惕的刺痛代价与兼容性影响 (Trade-offs)

* **性能**：D83 的候选判据从「读文件名」变成「读文件内容」⇒ 每个 app 多一次源文件遍历。实测本项目 app（1040 个候选源文件）单次遍历在本机为**亚秒级**，与同目录 `api` / `models` 适配器既有读法一致；只在 `--chain` / 显式运行时发生。
* **产物形态变化（存量项目首跑会亮一次漂移）**：D83 生效后同一项目 `items` 从 19 → ~54 条（含新收的模块级与 JSX 表）⇒ **首跑出现大批键级「新增」**，一次合法的、必须登记的漂移；`_drift.json` 会亮一轮（这正是它该做的事，但要预期到，不能当回归）。
* **`<br>` 进入事实单元格**：单行化让部分单元格含 HTML 行标记，纯文本读者会看到字面 `<br>`；行键比较在 F3 改动后把 `<br>` 与换行视作等价 ⇒ **键稳定无条件成立**。不新增契约字段，也不改 `atlas:facts` 标记语义。
* **契约正文新增一格**：输出 JSON 增 `coverage` 键 ⇒ `shared/stack-profile.md` §3.2 必须登记（F5）。这是**契约正文**改动（`global-rules.md` §7 的包自身演进），随本批一并过确认门。
* **门册与登记面**（F6/F7）：新判据与新钉必须落 `shared/gates.md`（元规则 1「不在本表 = 不存在」+ 元规则 2「喂坏输入必红」），新增决策落 `DESIGN.md`（D83–D86）、变更落 `CHANGELOG.md`；本次改动必然使**装配戳**失配 ⇒ 「装配版本」门 WARN，**由「副本重装对账」重落 `.atlas/VERSION` 复绿**（不是新问题，是传播义务的一步）。
* **不改的东西**：不动行键 / 列头 / `atlas:facts` 标记 / 漂移机制 / 退出码语义；`routes` 与 `models` 的 **JSON 既有字段**一个不动（只新增 `coverage`）。
* **存量自愈**：案 B 无需迁移脚本（下一轮 `--apply` 整块重写事实区即自愈）；案 A 需项目侧重跑适配器并登记那一轮漂移；案 C 需重装才落到项目副本。

---

## 3. 改动面清单 (Affected Surface)

- [x] **代码逻辑 · D85**：`scripts/refresh_structure.py`（`render_table` 单行化 + 渲染内自校；`_norm` 的 `<br>` 等价）
- [x] **代码逻辑 · D83/D84**：`adapters/routes.py`（内容判据；JSX 解析器带嵌套栈；符号表 / `resolve_spec` / 挂载边 / 前缀合成 / 未解析计数 / `coverage` 键）
- [x] **代码逻辑 · D86**：`package.json`（`files` 补 `tests`）
- [x] **契约正文**：`shared/stack-profile.md` §3.2（`coverage` 键语义；评审 F5）
- [x] **契约措辞**：`rings/structure/reference.md` §4 C（C 类路径口径 = 合成后的绝对路径）与 §6.2（接线前置补「渲染可读回」判据）
- [x] **门册**：`shared/gates.md`（2.1 `refresh_structure` 行：新判据 + 用例计数回填；2.2「装配版本」行的重装说明；评审 F6）
- [x] **决策/变更登记**：`DESIGN.md`（D83–D86）、`CHANGELOG.md`（版本段）；评审 F7
- [x] **测试防线**：`tests/test_refresh_facts.py`（D85）、`tests/test_adapter_routes.py`（D83/D84）、`tests/test_tools.py`（D86 的三表同步钉）
- [x] **传播**：重装本项目副本（`install.sh --update --no-skill --no-patch --no-wiring`）重落 `.atlas/VERSION`

### 3.1 测试钉子（逐字节取证的注入形态）

| 钉 | 注入 | 期望 | 落点 |
|---|---|---|---|
| M-R1 | 摘掉 `render_table` 的单行化 | 往返不变式用例 **红**（+ 自校 WARN 出现） | `tests/test_refresh_facts.py` |
| M-R2 | 把换行替换为**空格**后再还原 | 「保留行结构」断言 **红**（防「用空格糊过去也算修好」） | 同上 |
| M-R3 | 候选闸还原成「文件名含 `rout`」 | 模块入口表用例 **红**（条数不足 + 未挂载计数为 0） | `tests/test_adapter_routes.py` |
| M-R4 | 让前缀合成退化为「直接用模块相对路径」 | 跨模块同名路径的**折叠**断言 **红**（备选 A 的病灶） | 同上 |
| M-R5 | 让未解析文件照旧产出相对路径 | `未解析 ⇒ 丢弃 + 计数` 断言 **红** | 同上 |
| M-R6 | 别名解析退回「尾段唯一相等」（F1 的字面实现） | 别名形态夹具 **红**（合成失效 ⇒ 未挂载计数暴涨） | 同上 |
| M-R7 | `package.json.files` 摘掉 `tests` | 三表同步钉 **红** | `tests/test_tools.py` |

---

## 4. 验证与测试结果 (Verification)

```bash
python3 -m pytest tests/test_adapter_routes.py tests/test_refresh_facts.py tests/test_tools.py -q
python3 -m pytest tests -q                 # 出厂级全量（修复前基线：418 passed, 4 skipped / 23.78s）
python3 scripts/atlas_check.py --fast
```

* **修复前基线**：`418 passed, 4 skipped in 23.78s`（2026-10-16，含仓内另一在途批的改动）。
* **测试结果 / 自检结论**：见 §5。

---

## 5. 执行记录

**修复前基线**：`418 passed, 4 skipped in 23.78s`（2026-10-16，含仓内另一在途批的改动）。

**M 钉四段取证**（注入 → 断言**字节确实改变** → 红 → **逐字节还原** → 绿；每片均记 sha 一致）：

| 钉 | 注入点 | 结果 |
|---|---|---|
| M-R1 | `render_table` 的 `cell_text(x)` → `str(x)`（摘掉单行化） | 红 / 还原逐字节一致 / 复绿 |
| M-R2 | `CELL_BREAK = "<br>"` → `" "` | 红 / 还原 / 复绿（防「用空格糊过去也算修好」） |
| M-R3 | 内容预筛 → `posixpath.basename(rel)` 含 `rout` 或父目录 `router`（还原旧文件名闸） | 红 / 还原 / 复绿 |
| M-R4 | 去掉 `compose_prefix`（退化为模块相对路径） | 红 / 还原 / 复绿 |
| M-R5 | 跳过 `coverage["skipped_items"]` 分支（未解析仍产出） | 红 / 还原 / 复绿 |
| M-R6 | 表声明过滤 → `posixpath.basename(r) == tail`（评审 F1 的字面实现） | 红 / 还原 / 复绿 |
| M-R7 | 去掉 `_ROUTER_MOUNT_RE.search` 条件（子路由按「无 basename」误判站点级） | 红 / 还原 / 复绿 |
| M-R8 | `package.json.files` 摘掉 `tests` | **自然红**（修复前即该状态）⇒ 补 `files` 后复绿 |
| M-R9 | `_norm` 退回 `" ".join(str(s).split())`（不折叠 `<br>`） | 红 / 还原 / 复绿 |
| M-R10 | 去掉 `_selfcheck_round_trip` 调用（自校必须**活着能咬**） | 红 / 还原 / 复绿 |

**真实数据抽查（D85）**：真实项目的 `models` 产物 **1987 条（88 条 `type` 含换行）** 走 `render_models` 两遍 ⇒ 第二遍 **0 键级漂移**、字节幂等、`old_rows_by_key` 读回 **1939** 行（= 全量去重行键，**零丢失**；修前每轮在 9 张表上重复报同一批「新增」）。

**真实项目覆盖率抽查（D83+D84）**：`routes` 适配器在同一项目上 **19 条 / 1 个源文件 → 52 条 / 10 个源文件**；`route_coverage = {declared: 11, site_level: 1, mounted: 9, skipped: 1（0 条）}`。唯一未解析的是「通用路由外壳组件」文件（`basename={basename}` 且不存条目），逐文件出声点名。**明确不收**的两类各自可见：页内 tab 驱动的伪路由（不是路由声明）、常量路径条目（既有 WARN）。

**改动面**：§3 清单全部落地（另含 `shared/gates.md` 三行更新 + 门册计数回填 `test_refresh_facts.py` 17→20、`test_tools.py` 14→15，由 `test_registry_counts_match_reality` 钉住）。

**全量回归**：修复后 **`433 passed, 4 skipped in 24.03s`**（含仓内另一在途批的用例）。

**未覆盖 / 残余（明示）**：
1. `validate_structure` 对含 `<br>` 单元格的行为 —— 用装了 `<br>` 的真实事实表实跑该校验器取证（见下一条「副本重装对账」）。
2. 图谱通道与 regex 通道全等 —— 跑 `tests/test_routes_graph_backend.py`（本轮绿）。
3. 「数组写在调用里」（`createBrowserRouter([...])`，无 `routes` 绑定名）仍不在识别面内 —— 与 `_route_array_starts` 的既有判据同源，本轮不动；站点表以 `const routesList = [...]` 形态出现的项目不受影响。


---

## 6. 评审处置（独立审查 1 轮，verdict = 有阻塞问题；7 条 finding 全部采纳，无驳回）

| finding | 级别 | 处置 | 落到 v2 的哪一处 |
|---|---|---|---|
| F1 别名→文件解析欠定 | major | **采纳**（改成「目录前缀 + 也声明表过滤，仍不唯一才丢弃」） | §2.1 D84 条 2；钉 M-R6 |
| F2 多挂载前缀取值未定 | major | **采纳**（≥2 入边 ⇒ 未解析 + 计数，候选前缀入报告） | §2.1 D84 条 4 |
| F3 「键稳定」无条件误断言 | minor | **采纳**（`_norm` 把 `<br>` 与换行视作等价） | §2.1 D85 条 2 |
| F4 自校弱于声称的不变式 + 与 dry-run 耦合 | minor | **采纳**（改为对渲染字符串逐单元格比对，与写盘解耦） | §2.1 D85 条 1/3 |
| F5 新输出字段未登记契约正文 | major | **采纳**（补 `shared/stack-profile.md` §3.2） | §3 |
| F6 新判据/新钉未登记门册 | major | **采纳**（补 `shared/gates.md` + 计数回填） | §3 |
| F7 漏决策登记、变更记录、装配戳生效面 | major | **采纳**（补 `DESIGN.md` / `CHANGELOG.md` / 重装重落 VERSION） | §3 |
| （框架纠正）「模块相对路径」不是原契约未履行 | — | **采纳**（拆成 D83 缺陷修复 + D84 新增能力，可单独回退） | §1.3 / §2.1 |
| （missing_alternatives）JSX 同文件嵌套替代挂载映射 | — | **取证后作为替代方案否定、作为实现细节采纳**（本项目覆盖 0 条，但嵌套栈已并入 D83 条 2） | §2.2 G |

**未判事项**（评审 `not_judged`，由本批自行补齐）：① `<br>` 单元格对 `validators/validate_structure.py` 解析与列头判据的影响（**本批用装了 `<br>` 的事实表实跑该校验器取证**）；② 候选判据改内容判据后**图谱通道与 regex 通道全等**是否仍成立（**跑 `tests/test_routes_graph_backend.py`**）；③ 性能实测与 19→~54 口径（已在本 RFC §2.3 由父会话实测记录）。
