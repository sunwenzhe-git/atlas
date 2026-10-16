# 提案：靶场登录预置 —— 从「可选段 + 合法降级」改为「显式形态 + 未就绪」

> 提案编号：RFC-20261015-02
> 提案作者：@sunwenzhe-git（Agent 起草）
> 关联状态：草案 v2 (Draft) —— v2 已吸收评审意见（见文末「修订记录」）
> 影响范围：核心契约 (shared) | 环契约 (rings) | 校验器 (validators) | 脚本工具 (scripts) | 环输入 (apply) | 出厂模板 (templates)
> 关联 issue：`#11`（[design-conflict] 「登录预置」是硬要求但其取证配置 `app_login` 是可选段且无人产出）

---

## 1. 现象与取证 (The Problem & Evidence)

### 1.1 触发形态（抽象）

- **规则 / 环节**：`rings/e2e/reference.md` §7.1（第 420 行）「预置登录态（硬）」+ 同段「段缺失 = 合法降级」；`shared/stack-profile.md:91` `e2e.app_login` 段契约；`scripts/gen_e2e_scripts.py:1024` 缺段时 WARN + 跳过；`validators/validate_stack_profile.py:182–187`、`:234–235`。
- **触发时机**：真跑验收的整段过程 —— 生成器不预置会话，运行期靠人工在受控浏览器里登录，脚本复用该会话。
- **具体行为**：契约把登录态定为**硬**（「真实应用有访问门 ⇒ 运行必须预置真实会话」），但承载它的取证配置是**可选段**、缺失即「合法降级」，且**没有任何环 / 步骤负责产出它**。三重叠加的结果：每次真跑都要一次人工登录，而登录态短命（现场实测约 10 分钟）⇒ 长走查必然中途断掉；断掉的表现是「页面回落到登录页」而不是明确报错。

### 1.2 客观证据与日志 (Minimal Evidence)

```text
# 契约内部自相矛盾：硬要求 + 可选输入
$ sed -n '420p' rings/e2e/reference.md
预置登录态（硬）… 段缺失 = 合法降级（跳过登录预置 + 生成与运行期明确警告），段存在但字段不齐 ⇒ 生成报错
$ sed -n '91p' shared/stack-profile.md
e2e | app_login（子段：mode/endpoint/username_field/password_field/token_key/storage_key） | … 段缺失 = 合法降级

# 生成器在缺段时只警告，照常出脚本
$ sed -n '1024,1026p' scripts/gen_e2e_scripts.py
print("WARN: stack-profile 未声明 e2e.app_login —— 将跳过登录态预置"

# 产出方：三个环都不问
$ grep -rn 'app_login' rings/prd/reference.md apply/reference.md shared/closeout.md
（无输出）

# 机器门视角：全绿
$ python3 validators/validate_stack_profile.py --root .   → PASS（退出码 0）
# 该校验器只查 app_login 段**存在时**的 mode 枚举（:182-187），段缺失不产行；
# 且全文件 grep 不到 app_base_url ⇒ 它不校验 e2e 段的地址声明与否（:234-235 只有「e2e 段存在」WARN）

# 运行期取证（采用者项目现场）
[检测到] initAllI18n failed …Login.Expired
[时间线] pass1 12:00 登录成功 → pass3 12:09 仍有效 → pass4 12:10 / pass5 12:11 全部回落到登录页
[误读风险] 会话过期后 document.body.innerText 返回空串（bodyLen=0），而 page.content().length = 321376
         ⇒ 用 bodyLen 判存活会把「未登录」误读成「页面没渲染 / 被测代码坏了」
```

---

## 2. 决策与权衡 (The Decision & Trade-offs)

### 2.1 核心定案 (The Decision)

**(a) 把二态做成显式声明，落在已有的 `app_login` 段里（不新增顶层字段）。**

`e2e.app_login.mode` 增补一个取值 `none`：

| `mode` | 语义 | 生成行为 |
|---|---|---|
| `real`（缺省） | 靶场有访问门，走真实登录换取令牌 | 现有语义不变 |
| `fabricated` | 纯前端桩项目，直写固定假令牌 | 现有语义不变 |
| **`none`（新增）** | **靶场无访问门，不需要预置** | 不预置、**不打警告**（这是声明过的形态，不是降级） |

> **为什么这是既有习语而非发明**：本仓的 `e2e.mock.mode: off`（在打桩通道里声明「不打桩」）、`e2e.review.mode: off`（在审查段里声明「免审」）就是这个家族的两例 ——「在 X 段里用一个 mode 值声明 X 通道不需要」已是既定写法。`app_login.mode: none` 是第三例，读者有先例可依。

配套把两处语义钉死：

- **`mode: none` ⇒ 段内取证字段一律不得残留**（含 `storage_key`）⇒ **FAIL**。注意与 `fabricated` 的差别：`fabricated` 是**收窄**（保留 `storage_key`），`none` 是**全弃**。
- **空段（`app_login:` 后无内容）= 未声明**（按 (b) 走未就绪），**不是**「已声明但字段不齐」；非空但缺字段才 FAIL。

**(b) 「段缺失」不再等于「合法降级」，改为「未声明 ⇒ 未就绪」。**

- `app_login` 段未声明 ⇒ 生成器 **`not_ready`（退出码 3）**，不产脚本；`atlas_check` 判 **SKIP + 具名原因**（同 `app_base_url` 为 null 的既有先例，`gen_e2e_scripts.py:1003`）。
- 这一条**不是 FAIL，也不阻断开发**：`未就绪 ≠ 失败`（`rings/e2e/reference.md:398`）。
- **机读键必须指定**（镜像既有惯例）：`--json` 的 `{"ok": false, "not_ready": "app_login", …}`，message 带显式 token 前缀（镜像两态辨析用的 `ENV_ISSUE：<地址>；<原因>`），供下游与测试钉住 —— 现先例的 `not_ready: "app_base_url"` 已有测试钉（`tests/test_gen_e2e_scripts.py:458`）。
- **`not_ready` 通道本来就混装异质原因**（`:398` 明列「未就绪含两态：① 地址未声明 ② 地址已声明但靶场不可达」），所以本条的第三态与它同族，靠 message token 辨析，不另开通道。

**(c) 分阶段升档 —— 升档条件改为「时间锚」，并承认现场已计一次咬合。**

- **第一阶段（本 RFC）**：语义改造 + `validate_stack_profile` 增一条 **WARN 指名**：`e2e.app_base_url` 已声明（= 项目准备真跑）而 `app_login` 段未声明 ⇒ WARN。
  - **WARN 文案必须中性**（不能对无门项目断言错误事实）：「登录形态未声明：有门项目将退化为人工登录且会话短命；无门项目请声明 `mode: none`」。
- **第二阶段（升档）**：把「未声明」推给生成器的 `not_ready`（即 (b) 生效）。
  - **升档条件 = 下一次真跑准备日无条件升档**（时间锚，不设「观察窗」作为门槛）。
  - **本次现场（pass1→pass5 的会话失效 + 人工登录）计为第 1 次咬合**，登记落 `shared/gates.md` 的「E2E 真跑」行（台账在仓内、可复审 —— 遵 `DESIGN.md` D79 ④「判据值全落 gates 行、不赖仓外数字」）。
- **为什么不一上来就 `not_ready`**：`app_base_url` 已声明 + `app_login` 缺失的既有项目，现状**能跑**（无门项目不预置本来就对）⇒ 立刻收紧会把一批正常项目挡在门外。第一阶段先把「这是未知态」讲清楚，第二阶段再收紧 —— `none` 的迁移动作只有一行。
- **诚实的代价账**：第一阶段对运行期的行为与「只加 WARN」相同（照常出无预置脚本）⇒ issue 的病灶在阶段一**只变得可见、未被治**。它依赖阶段二必然到来，而阶段二现在是**时间锚**（不再是不可执行的观察窗）。

**(d) 给 `app_login` 一个产出环节（与 #10 同构的缺口）。**

契约写清了「是什么」，从没写「谁在哪一步产出它」。定案：

- **adopt 开户最小集**新增一项「**靶场接入取证**」：与 `app_base_url` 同批向用户索取 **登录形态三选一**（有门 ⇒ 四值；无门 ⇒ `mode: none`；纯前端桩 ⇒ `fabricated` + `storage_key`）。落点：`apply/reference.md` 的 adopt 行 + `rings/e2e/reference.md` §6/§7.1。
- **兜底**：`apply <需求ID>` 首次判定「本次需要 E2E」时，若 `app_login` 仍未声明 ⇒ 追问一次（不阻断 prd 环）。
- **澄清与 D78 的张力**：本 RFC 用 D78「指令通道会漂」否决了「只加体检提醒」，而 (d) 的兜底追问本身是会话通道 —— 可辩护，因为**判据的正文是机器门（(b) 的 `not_ready`）**，追问只是 UX 加速器。此点写进契约，避免读成自相矛盾。

**(e) 责任面分层（文档面）。** 「凭据只来自运行期环境变量（`ATLAS_APP_USER` / `ATLAS_APP_PASSWORD`）」与「取证值登记在 `e2e.app_login`」**跨两份文档分散**（`shared/stack-profile.md:91` 的段契约行 ↔ `rings/e2e/reference.md:420` 的硬要求行；后者那一 bullet 内虽同时提到两者，但读者从 profile 契约侧进入时看不到运行期那一半）。定案：在 §7.1 用**一段**把两半绑在一起写，并明确 —— **谁设置凭据**（运行者 / CI，运行期）、**谁询问取证值**（adopt 开户 + e2e 环兜底，设计期）。

**(f) 明确不在本次范围。** 会话**过期**的运行期检测（`bodyLen=0` 被误读成「页面没渲染」）—— 那是探针与断言纪律（§5.4 / §5.5 一族）的另一个题。本 RFC 只解决「预置该不该有、有没有人负责产出」，不解决「预置在跑的过程中失效了怎么被看见」，单独立项。

### 2.2 考虑过的备选方案及否定理由 (Considered Alternatives)

- **备选 A：只加 WARN，不改「合法降级」语义**。
  - *否定理由*：这正是把硬要求消化成静默的机制本身 —— WARN 之后**照常生成不带预置的脚本**，运行期以「页面回落登录页」的形态失败，而该形态极易被误读。与 F37（摘要恒空 ⇒ 只会通过的门）同族。WARN 在本提案里保留给**第一阶段**，但形态声明必须存在。
- **备选 B：新增顶层字段 `e2e.auth: gate | none`**（与**用例级** `auth: none` 同词）。
  - *否定理由*：① **作用域混乱**——用例级 `auth`（`:172`：`preset | none`，说的是「这条用例要剥掉预置的干净 context」）与项目级「靶场有没有门」共用一个词 + 共用一个 `none` 值；两者真跑语义上并不矛盾（无门项目里用例 `auth: none` 只是冗余），但阅读混淆风险真实存在（本仓刚处理过 RFC-01 的同名病）；② 它把「有没有门」与「有没有取证值」拆成两个字段 ⇒ 两个真相源（`auth: gate` 但 `app_login` 空、`auth: none` 但 `app_login` 有值都是可能的非法组合，需要额外交叉判据）。落进 `app_login.mode` 则一处声明、一处判据。
- **备选 C：要求所有项目都写 `app_login` 段**。
  - *否定理由*：**真正独立的理由**只有两条 —— ① 无门项目段内容为空 ⇒ 占位符（`shared/global-rules.md:35`），且「空段 = 已声明无门」与「空段 = 忘了填」仍是同一个形态，正是本 RFC 要消除的同形；② 段存在性被用作「有没有门」的编码，等于把判据塞回「靠缺失推断」。**注意**：本提案第二阶段的效果（无门项目也必须写 `app_login: {mode: none}`）与「必填段 + `none` 豁免」在**结果上等价**，差别只在落点选择 —— 上面两条是选 `mode` 而非选必填档的理由，不是「必填档做不到」。
- **备选 D：把「未声明」直接判 `FAIL`（而不是 `not_ready` / SKIP）**。
  - *否定理由*：`未就绪 ≠ 失败`（`3509 §B110`）—— 永久红的门会被当成背景噪声；`app_base_url` 已确立「未就绪走 not_ready + SKIP」先例，本条应与它同族而非更重。
- **备选 E：用「用例侧信号」精确收紧（`app_login` 未声明 **且** 索引里存在需要预置会话的用例 ⇒ 第一阶段即 `not_ready`；纯无门项目继续 WARN）**。
  - *否定理由*：判据多一层且依赖用例声明完备（无门项目若懒得标 `auth: none` 会误伤，因为缺省是 preset）；收益是把「被挡住的集合」收敛到真会被运行期伤害的项目。**列为备选**：若评审认为分阶段的代价账不可接受，这是两边都不伤的第三条路。
- **备选 F：在体检报告里加一条提醒了事**。
  - *否定理由*：`DESIGN.md` D78 刚承认过「用指令 / 提示通道解决配置缺口会漂 —— `rings/structure` §6 步 1 的提议条款在实际接入里从未生效过」。同一教训不重复踩。

### 2.3 必须警惕的刺痛代价与兼容性影响 (Trade-offs)

- **存量项目兼容**：`app_login` 已声明的项目**零影响**（`mode` 缺省 `real`）。`app_base_url` 已声明而 `app_login` 缺失的项目：第一阶段只多一条 WARN；第二阶段变 `not_ready`（见下条连带面）。迁移动作 = **加一行** `app_login: {mode: none}`（无门）或补齐四值（有门）。**必须在 CHANGELOG 显式写出这条迁移动作。**
- **第二阶段会连带翻转「生成物最新」门（诚实列账）**：`atlas_check` 的 `check_generated`（`scripts/atlas_check.py:187–202`）依赖生成器返回码 ⇒ 生成器 `not_ready` 会让**整行**从「看守生成物新鲜度」变 **SKIP**。影响中等（脚本仍会被直接发现 stale），但必须写明这是**有意的回退**，而不是「被挡住的只有真跑」。
- **enforcement 点与 gate 点是解耦的**（有意）：真跑门（`check_e2e`）自己读 profile 判 `app_base_url`，**不走生成器** ⇒ 迁移窗口内，盘上已有的无预置旧脚本**仍会照跑**（不会被误杀），本条的可见性载体是「生成物最新 SKIP + 具名 WARN」。这一点要在契约里写明，避免读成「真跑被挡住」。
- **迁移面必须一次列全**：现存「段缺失 = 合法降级」的表述散在 **5 处**，不是 1 处 ——
  `shared/stack-profile.md:91`、`rings/e2e/reference.md:420`（§7.1）、`rings/e2e/reference.md:327`（§5.8 咬合行）、`scripts/gen_e2e_scripts.py:1020–1021`（报错文案）、`templates/stack-profile.yaml:58/60`（注释），外加 `tests/test_gen_e2e_scripts.py:1084/1091` 的钉子测试（本就要被 M 钉退回重写）。**做成一份「词表 / 措辞同步表」逐处对账**，用 `tests/test_canonical_consistency.py` 的契约字段引用可达钉兜底。
- **词表同源面是四处，不是三处**：契约 §2（文本） / 校验器 `APP_LOGIN_MODES`（`validators/validate_stack_profile.py:57`） / 生成器 `APP_LOGIN_MODES`（`scripts/gen_e2e_scripts.py:78`） / **出厂模板注释**（`templates/stack-profile.yaml:60`）。**并且 `APP_LOGIN_MODES` 恰是唯一没有「⊆ 模板 ⊆ 契约正文」守恒测试的词表**（`SEED_MODES` / `ORIGINS` / `RUNNERS` 都有，见 `tests/test_validators.py:1348/1445/1911`）⇒ 本 RFC 顺手补上这条守恒钉，否则加 `none` 时漏同步不会被任何测试抓住。
- **生成物字节比对面要确认**：`mode: none` 落地后 stderr 不再打 WARN —— 若 `atlas_check` 的生成物门比对含 stderr 或返回文本，会漂。落地时确认比对对象**仅产物字节**。
- **不涉及**：重跑 `atlas init`（无装配集变化）、刷新结构事实。

---

## 3. 改动面清单 (Affected Surface)

- [ ] **契约/文档**：
  - `shared/stack-profile.md` §2 `:91`（`mode` 词表加 `none`、段描述由「取证值」改「登录形态与取证值」、删「段缺失 = 合法降级」句）
  - `rings/e2e/reference.md` §7.1 `:420`（硬要求 + 形态声明 + 责任面一段 + 未就绪口径 + 机读键/token）、§5.8 `:327`
  - `apply/reference.md`（adopt 开户最小集加「靶场接入取证」；`apply <需求ID>` 兜底追问）
  - `templates/stack-profile.yaml` `:58/60`（注释加 `mode: none` 示例，删旧措辞）
  - `shared/gates.md`（「E2E 真跑」行登记升档条件与咬合台账）
- [ ] **代码逻辑**：`scripts/gen_e2e_scripts.py`（`none` 分支；未声明 ⇒ `not_ready: "app_login"` + message token；`none` 残留字段 FAIL；空段 = 未声明）、`validators/validate_stack_profile.py`（`APP_LOGIN_MODES` 加 `none`；`none` 冲突 FAIL；第一阶段 WARN 指名 + 中性文案）
- [ ] **测试防线**：
  - `tests/test_gen_e2e_scripts.py`（`mode: none` 不预置且**不打 WARN**；未声明 ⇒ `not_ready == "app_login"`；`none` + 残留字段 ⇒ FAIL；空段 ⇒ 未就绪）+ M 钉（「未声明 ⇒ not_ready」退回「WARN + 照常生成」⇒ 用例红）
  - `tests/test_validators.py`（`app_base_url` 已声明 + `app_login` 缺失 ⇒ WARN 指名）+ **补 `APP_LOGIN_MODES` 的「⊆ 模板 ⊆ 契约正文」守恒钉**（照 `:1348/1445` 先例）
- [ ] **版本装配**：`package.json`（小版本递增）

---

## 4. 验证与测试结果 (Verification)

> 本节在草案期为「应跑清单」，落地时补齐实测输出。

```bash
pytest tests/test_gen_e2e_scripts.py tests/test_validators.py
pytest tests/
python3 scripts/atlas_check.py --fast
```

- **应补的负向验证**：`app_login` 未声明 ⇒ `atlas_check` 的真跑门 / 生成物门**分别**落 SKIP 且带具名原因（证明两行各自可见，而不是笼统「未就绪」）。
- **应补的兼容性验证**：造一个 `app_base_url` 已声明 + `app_login` 缺失的存量夹具，跑第一阶段版本 ⇒ 只出 WARN、生成物与旧版逐字节一致。
- * **测试结果**：待落地时填（当前草案未改代码）
- * **自检结论**：待落地时填

---

## 修订记录

**v2（本版）吸收评审意见**：
1. **升档条件重写**：原「WARN 被观察并被人工登录咬过一次」已被本次现场满足、且无台账落点 ⇒ 改为**时间锚**（下一次真跑准备日无条件升档），本次现场计为第 1 次咬合并落 `shared/gates.md`（评审 P1）。
2. **WARN 文案改中性**：原稿「每次运行都需人工登录」对无门项目是错误断言（评审 P1）。
3. **补机读键与 token**：新增 `not_ready: "app_login"` + message 显式 token，镜像 `ENV_ISSUE` 惯例与既有测试钉（评审 P1）。
4. **补连带面**：写明 `check_generated`（生成物最新门）会一并 SKIP、以及 enforcement 点（生成器）与 gate 点（真跑门）解耦是有意为之（评审 P1）。
5. **补迁移面清单**：残留「段缺失 = 合法降级」的 5 处坐标 + 2 处测试钉子逐处列出（评审 P1）。
6. **补词表同源第四处**：`templates/stack-profile.yaml`；并指出 `APP_LOGIN_MODES` 缺守恒钉 ⇒ 本 RFC 顺手补（评审 P2）。
7. **修正行号**：校验器判据 `:236` → `:234–235`（评审 P2）。
8. **补最强论据**：`app_login.mode: none` 的家族先例（`e2e.mock.mode: off` / `e2e.review.mode: off`）（评审 P2）。
9. **备选 C 去稻草人**：诚实写明它与本方案第二阶段在结果上等价，列出真正独立的落点理由（评审 P2）。
10. **补两条钉子语义**：`none` ⇒ 五字段全弃（含 `storage_key`）、空段 = 未声明（评审 P2）。
11. **新增备选 E**：用例侧信号收紧的第三条路（评审建议，未采纳但留档）。
12. **补 D78 张力澄清**：(d) 的兜底追问是 UX，判据正文仍是机器门（评审 P2）。
