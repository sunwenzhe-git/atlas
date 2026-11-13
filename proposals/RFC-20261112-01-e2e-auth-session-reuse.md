# RFC-20261112-01：E2E 登录态复用与一次性登录入口

- 提案编号：RFC-20261112-01
- 日期：2026-11-12
- 版本：v2
- 状态：**提案中（仅方案；未实现、未改运行时、未跑用例、未开浏览器）**
- 评审结论：**有条件接受；A（执行期回写）不进 v1**。v1 只落地 C（显式 `atlas e2e login`）+ D（执行前预检）+ 导航层 URL query 保真；A 作为独立后续项，默认关闭。
- 影响范围：`rings/e2e/reference.md` §7.1 · `shared/stack-profile.md` §2 · `scripts/e2e_console.py` · `scripts/gen_e2e_scripts.py` · `templates/e2e/scripts/`（生成物）· `bin/atlas.js` · `tests/`
- 关联：
  - `DESIGN.md` D103（人工会话非机器门、不可 CI 复现）
  - `rings/e2e/reference.md` §7.1（凭据只来自运行期环境变量；人工会话取出）
  - `shared/stack-profile.md` §2 `e2e.app_login`（`real` / `fabricated` / `none`）

---

## 0. 一句话

v1 把登录态做成**有来源、有判定信号、可预检的运行期前提**：执行前用 state 形态分治 + 必填 probe 判断会话是否可用，不可用就明确失败并给出唯一的一次性登录入口 `atlas e2e login`；执行期的 `storageState` 回写（A）后置为独立项，默认关闭。

---

## 1. 现状与失败模式

### 1.1 机制

- 主控制台与成员控制台执行用例时，Playwright 为每个测试创建**临时 browser context**；用例结束即销毁，登录态不会从普通浏览器或上一次执行中继承。
- 登录态文件固定为 `<e2e.scripts_dir>/.atlas-auth/state.json`（生成器常量，`scripts/gen_e2e_scripts.py:2415`）。
- `app_login.mode: fabricated` 的 setup 只在文件**缺失或损坏**时写入假令牌；文件存在且 `JSON.parse` 成功就直接 `return`（`scripts/gen_e2e_scripts.py:2620-2627`）。
- `app_login.mode: real` 的 setup 也只在文件缺失、损坏或 `ATLAS_FORCE_LOGIN=1` 时重新登录；否则直接复用文件（`scripts/gen_e2e_scripts.py:2677-2685`）。
- 一旦 `state.json` 存在，后续执行不检查：令牌 / cookie 是否过期、会话是否被服务端注销、state 是否属于当前 `app_base_url` 的租户 / 应用上下文。
- 用户手工 `playwright codegen --save-storage=...` 导出的文件只是「某一刻的浏览器快照」，工具没有元数据、没有过期判定，也没有标准入口；过期后只能再导一次。

### 1.2 两个 4195 现场案例（用户已核实，本文不复核）

| 案例 | 触发 | 表现 | 现有工具为何无法自愈 |
|---|---|---|---|
| 令牌过期 | 人工会话约 8 小时 / 会话级 cookie 到期 | `state.json` 仍存在且可解析，setup 打印「保留已有登录态文件，跳过覆写」；执行带着过期令牌请求接口，用例红 | 没有过期检查；`fabricated` 的幂等守卫只判「文件可解析」，不判「会话可用」；`real` 也没有过期检查 |
| URL 缺 `organId` | 导航 URL 未带 `app_base_url` 的完整 query | 应用侧 `Amp-Organ-Id` 回落成 `1`，列表 / 详情落到错误租户，出现空数据或错误数据 | 登录态文件只记录 origin（scheme + host + port），不约束导航 URL 的 query；执行链没有「同源导航必须携带声明 query」的断言 |

两个案例是同一类问题的两面：**会话文件被当成了布尔值（存在 / 不存在），而不是带有效期与上下文的运行期前提。**

### 1.3 state 的三种形态

| 形态 | 典型内容 | 过期信号 | 备注 |
|---|---|---|---|
| `real` | `origins[].localStorage`，无 cookie；令牌可能是 JWT，也可能是不可解析的 opaque token | JWT `exp`；`state.meta.json` 的 `expires_at`；`written_at` + `max_session_age` | localStorage-only，cookie 判不了 |
| `fabricated` | localStorage 里是字面量假令牌，无 `exp` | 无过期语义；按字面量匹配识别 | 只允许 `app_login.mode: fabricated` |
| `imported` | cookie 会话：`token`、`Amp-Organ-Id` 等，`expires` 可能是会话级（-1），无 JWT `exp` | `state.meta.json` 的 `written_at` + `max_session_age`（默认 8h）或 `expires_at`；cookie 自身 `expires`（若 >0） | 人工登录 / codegen 产物，C 的默认来源 |

### 1.4 底线：假令牌也不能让用例变绿

1. `app_login.mode: real` 时，不得用 `fabricated` 的假令牌替代真实会话；缺失 / 过期 / 无法判定 ⇒ 明确失败或要求重建，不静默降级。
2. `app_login.mode: fabricated` 只允许在**文件缺失**时写入假令牌；文件存在但会话已失效时，不得用「重新写假令牌」掩盖失效。
3. 任何回写都必须来自**已通过 probe** 的 context；probe 失败时只允许保留旧文件并报错，不允许写一个「看起来可解析、实际不可用」的文件。
4. `fabricated` 来源不得被写成 `real` / `imported`；来源、时间与指纹必须可审计。
5. probe 不得可选：`real` / `imported` 下缺失 probe 即 fail closed，禁止用「只查过期」放行。

---

## 2. v1 范围与设计约束

### 2.1 v1 范围

- **C**：`atlas e2e login` 作为唯一的一次性人工登录 / 会话重建入口，产物 `source: imported`。
- **D**：执行前预检——state 形态分治的过期判定 + 必填 probe + 来源 / 指纹一致性；不可用即拒绝执行。
- **导航层 URL query 保真**：由生成物在每次同源导航时校验 query，缺失即失败。
- **凭据落盘卫生**：`.atlas-auth/` 忽略规则、`0600`、原子写、日志脱敏。
- **不做 A**：执行期回写不进 v1，默认关闭，作为独立后续项。

### 2.2 设计约束

- **单一事实源**：目标地址只来自 `e2e.app_base_url`（含 query）；state 只承载会话，不承载租户 / 应用上下文。
- **人类只在必要时介入**：首次登录、服务端强制过期、权限变更时需要人；工具负责判定与复用，不假装能替代登录。
- **显式失败优先于静默降级**：过期 / 缺失 / 无法判定 / 上下文不匹配都必须产生可操作的错误。
- **不改变判定语义**：登录态只影响前提，不改变用例断言、零步基线与终态集合。
- **不引入固定 sleep**：等待登录 / probe 用条件轮询与超时。
- **D103 调和**：C 仍是人工会话，不把登录变成机器门，也不承诺 CI 可复现；probe 只把「会话是否可用」变成机器可判定的前置条件。

---

## 3. 方案 C：`atlas e2e login`

### 3.1 机制

- 新增 `scripts/atlas_e2e_login.py`，由 `bin/atlas.js` 增加 `e2e login` 路由转发。
- 读取 `product/stack-profile.yaml`：
  - `e2e.app_base_url`：完整 URL（含 `organId` 等 query）；
  - `e2e.scripts_dir`：state 落点；
  - `e2e.app_login.probe`：必填（`real` / `imported`）。
- 打开有头 Chromium，导航到**完整** `app_base_url`；用户完成登录后，用同一 context 执行 probe。
- probe 通过才写：
  - `.atlas-auth/state.json`：`context.storageState()`；
  - `.atlas-auth/state.meta.json`：`source: imported`、`written_at`、`expires_at`（可推导时）、`base_url_fingerprint`、`probe: {ok, at, status}`、`state_sha256`。
  - 两个文件均原子写、`0600`。
- 输出下一步执行命令；不执行任何用例。

### 3.2 改动面

- `bin/atlas.js`：新增 `e2e login` 路由。
- `scripts/atlas_e2e_login.py`：有头浏览器、probe、原子写盘、错误文案。
- `scripts/e2e_console.py`：预检失败文案指向该命令。
- `rings/e2e/reference.md` §7.1：把标准人工会话入口写成 `atlas e2e login`；`playwright codegen --save-storage` 保留为应急路径。
- `tests/`：命令路由、配置读取、probe 失败不写盘、URL query 保真、`0600`。

### 3.3 代价与风险

- 仍需要人登录一次；这是物理前提，不是自动化缺口。
- 登录页可能跨域 / 有验证码；脚本只负责打开页面、检测 probe、保存，不替用户完成认证。
- 新增一个命令与脚本；比自动弹窗（方案 B）状态机小，比只失败（方案 D）多一条正向路径。

### 3.4 假令牌底线

- C 只允许在 `app_login.mode: real` 下使用；`fabricated` / `none` 调用即失败。
- 只写 probe 通过的会话；probe 失败退出非 0，原文件字节不变。
- 不写假令牌；不把 `imported` 标成 `real`。

---

## 4. 方案 D：执行前预检

### 4.1 过期判定按 state 形态分治

| 形态 | 可用信号 | 判定 | 无法判定时 |
|---|---|---|---|
| `real` | JWT `exp`；`state.meta.expires_at`；`written_at` + `max_session_age` | 任一信号显示已过期 ⇒ 不可用；至少一个信号可判定且未过期 ⇒ 继续 probe | **不可用**（fail closed），要求 `atlas e2e login` |
| `fabricated` | localStorage 值等于约定假令牌字面量；无 `exp` | 仅 `app_login.mode: fabricated` 可用；不是真实会话 | 值不匹配 ⇒ 不可用；不得当作真实会话 |
| `imported` | `state.meta.written_at` + `max_session_age`（默认 8h）；`state.meta.expires_at`；cookie `expires`（若 >0） | 任一信号过期 ⇒ 不可用；至少一个信号可判定且未过期 ⇒ 继续 probe | **不可用**（fail closed），要求 `atlas e2e login` |

补充规则：

- `real` 的令牌不是 JWT、meta 也没有 `expires_at` / `written_at` ⇒ **无法判定 ⇒ 不可用**，不允许「直接跑跑看」。
- `imported` 的 `token` / `Amp-Organ-Id` 是会话 cookie（`expires: -1`）且 meta 缺失 `written_at` ⇒ **无法判定 ⇒ 不可用**。
- `real` / `imported` 的过期判定通过后，**仍必须 probe**；过期判定不是放行条件。
- `fabricated` 不做 probe；它只允许在 `fabricated` 模式下存在，且不得被当成 `real` / `imported`。

### 4.2 probe 契约（必填，不得可选）

`e2e.app_login.probe` 是对象，`real` / `imported` 下必填；缺失即配置 FAIL、执行拒绝。

| 字段 | 必填 | 默认 | 语义 |
|---|---|---|---|
| `path` | 是 | — | 相对 `app_base_url` 的认证探针路径 |
| `method` | 否 | `GET` | `GET` / `POST` |
| `expect_status` | 否 | `200` | 期望状态码；非该值即失败 |
| `expect_content_type` | 否 | `application/json` | 必须匹配；**HTML 200 登录页在此失败** |
| `expect_json` | 否 | — | JSON Pointer → 期望值，如 `/data/organId: "123"`；缺失或不等即失败 |
| `timeout_ms` | 否 | `3000` | 超时即失败；上限 `10000` |

判定标准：

- 必须能拒绝「HTML 200 登录页」：`content-type` 非 JSON、响应体以 `<` 开头、重定向到登录路径、或 `expect_json` 不匹配，任一命中即失败。
- 必须在**与执行相同的会话、origin、完整 `app_base_url` query** 下运行；租户头 / query 派生逻辑与真实页面一致，避免 probe 通过但实际执行落到错误租户。
- 超时、网络错误、4xx/5xx、空响应、无法解析 JSON ⇒ fail closed。
- probe 不写 state；只返回 ok / fail 与脱敏原因。
- `none` 下 `probe` 必须禁写；`fabricated` 下同样禁写（假令牌不可能通过认证探针）。

### 4.3 来源与指纹一致性

- 执行前读取 `state.meta.json`：
  - `source` 必须属于当前 `app_login.mode` 允许的集合（见 §6 映射表）；
  - `base_url_fingerprint` 必须等于本次执行的有效 URL 指纹；
  - `state_sha256` 必须与 `state.json` 内容哈希一致。
- 任一不匹配 ⇒ 拒绝执行，不尝试「修一下再跑」。
- **租户依据（最终口径）**：`e2e.app_base_url` 声明了 `organId` 时，**URL 参数是唯一依据**（实测请求头按 URL 判定，旧 cookie 不影响实际租户）；state 里的 `Amp-Organ-Id` 与声明值不一致只输出告警、不阻断执行。URL 未声明 `organId` 时，才退回 state 的 `Amp-Organ-Id` 作为生效租户并纳入指纹。

### 4.4 改动面

- `scripts/e2e_console.py`：预检、错误文案、退出码；不改执行 / 判定逻辑。
- `scripts/gen_e2e_scripts.py`：state 形态识别、meta 读写（生成期 / 执行期共用工具）。
- `shared/stack-profile.md` §2：`probe` 字段与必填矩阵。
- `strings` / 文档：错误文案给出完整 `atlas e2e login` 命令。
- `tests/`：三种形态 × 过期 / 未过期 / 无法判定；probe 各类失败；来源 / 指纹 / 哈希不匹配。

---

## 5. 导航层 URL query 保真

- 生成物提供 `atlasGoto(page, url)`（及首屏导航封装）：对**同源**导航解析 `new URL(url)`，要求其 query 键集合 ⊇ `e2e.app_base_url` 的 query 键集合。
- 缺失任一键 ⇒ 在导航前抛错，错误信息包含缺失键、期望 URL、实际 URL；用例红，不进入页面。
- 跨域导航（SSO / 外部登录）不校验；回到应用同源后的下一次导航重新校验。
- 校验发生在**生成物的导航层**，不在控制台读取配置时自检；控制台自检只能证明配置里写了 query，抓不到用例里写死的缺 query URL。
- `ATLAS_BASE_URL` 只覆盖 host；query、`organId` 等租户上下文仍以 `e2e.app_base_url` 为准，不得被环境变量冲掉。
- 该能力属于 v1，与 A 无关。

---

## 6. `source` ↔ `app_login.mode` 映射与 A 的后置契约

### 6.1 映射表

| `app_login.mode` | C 是否允许 | C 写入的 `source` | A 回写门允许的 `source` | probe |
|---|---|---|---|---|
| `real` | 是 | `imported` | `real`、`imported`（统一视为「真实会话类」） | 必填 |
| `fabricated` | 否 | — | `fabricated` | 禁写 |
| `none` | 否 | — | 不允许任何 state | 禁写 |

A 的回写门**不比较 `source` 字面量与 `mode` 相等**，而是比较归一化后的 `session_class`：

```text
session_class(real)       = real
session_class(imported)   = real
session_class(fabricated) = fabricated
```

- `mode: real` ⇒ 允许 `session_class == real`（即 `real` 或 `imported`）。
- `mode: fabricated` ⇒ 只允许 `session_class == fabricated`。
- `mode: none` ⇒ 不允许回写。

这样 C 产出的 `imported` 在 `real` 下与 A 的回写门一致，不会出现「永远不相等」的矛盾。

### 6.2 A（后置，默认关闭）

A 不进 v1。恢复时必须按以下契约实现：

- 只在 `globalTeardown` 用**一次性独立 context** 跑一次；不逐测试回写、不并发回写。
- 前置条件全部满足才写：
  - probe ok；
  - `origin + 租户指纹` 与执行开始时一致；
  - 未检测到登出 / 权限变更（probe 401/403、登录页跳转、租户变化任一命中即放弃回写）。
- `state.json` 与 `state.meta.json` 一起原子写；meta 含 `state_sha256`，读取时校验内容哈希；不一致即 fail closed。
- 默认关闭，配置项为显式开关（如 `e2e.auth.persist_state: false`）；关闭时与 v1 行为一致。
- 回写不得把 `fabricated` 写成 `real` / `imported`；来源按 §6.1 映射判定。
- 回写失败不删除旧文件，只记录脱敏错误；不把回写失败记成用例失败或通过。

---

## 7. 指纹定义

`base_url_fingerprint` 必须是**完整有效 URL 的指纹**，至少包含：

- scheme；
- host（应用 `ATLAS_BASE_URL` 覆盖后的最终 host）；
- port（最终 port）；
- path；
- **完整 query（含 `organId`、`appId`、`appCode` 等）**，按键排序后参与哈希。

计算口径：

- 以 `e2e.app_base_url` 为基准；`ATLAS_BASE_URL` 只覆盖 host（沿用 §7.1 口径），query / path / 租户参数不被覆盖。
- 先归一化（scheme/host 小写、默认端口省略、query 排序、保留重复键的顺序语义），再取 SHA-256。
- **生效租户**：URL 声明 `organId` ⇒ 以该参数为唯一租户依据（已随 query 进入指纹），state 的 `Amp-Organ-Id` 不一致只告警、不影响指纹判定；URL 未声明 `organId` ⇒ 以 state 的 `Amp-Organ-Id` 为生效租户，追加进指纹原文。
- 同一 host、不同 `organId` 必须得到不同指纹；禁止只用 origin 做指纹。
- 指纹只入 meta，不入日志正文；错误信息可输出指纹前 12 位用于排障。

---

## 8. 与既有纪律调和

### 8.1 D103

- D103 的结论保持不变：人工会话不是机器门，不承诺 CI 可复现；`real` 的自动登录仍只走 `ATLAS_APP_USER` / `ATLAS_APP_PASSWORD` + setup。
- C 是**本地人工会话的标准入口**，不是 CI 登录方案；probe 只判定「当前会话是否可用」，不把人工登录变成 CI 步骤。
- D 的失败路径必须明确说明「需要人工重建」，不得让 CI 以为可以自动恢复。

### 8.2 setup 幂等守卫

- `real` / `fabricated` setup 的「文件存在且可解析就跳过」保持不变，人工会话不会被 setup 冲掉。
- C 是显式写盘；A 只在 §6.2 的前置条件下由 teardown 写盘。两者都不改变 setup 的幂等语义。
- 预检失败时不删除、不覆盖 `state.json`；只拒绝执行并提示重建。

### 8.3 `app_login` 字段矩阵

| mode | 合法字段 | 禁写字段 |
|---|---|---|
| `none` | `mode` | 其余全部，含 `probe`、`endpoint`、`username_field`、`password_field`、`token_key`、`storage_key`、`body_format` |
| `fabricated` | `mode`、`storage_key` | `endpoint`、`username_field`、`password_field`、`token_key`、`body_format`、`probe` |
| `real` | `mode`、`endpoint`、`username_field`、`password_field`、`token_key`、`storage_key`、`body_format`、`probe`（必填） | — |

- 矩阵之外的字段一律 FAIL，包括 `storage_state`：state 路径固定为 `.atlas-auth/state.json`，不接受 profile 覆盖。
- 存量 profile 若声明 `storage_state`，落地时需清理；本提案不代改任何项目配置。
- `none` 下写 `probe` 必须 FAIL；`fabricated` 下写 `probe` 同样 FAIL。

---

## 9. 凭据落盘卫生

- `.atlas-auth/` 必须被项目 `.gitignore` 覆盖；安装器 / 校验器增加忽略规则检查，缺失即 WARN 或 FAIL（按既有门级别）。
- `state.json`、`state.meta.json` 权限必须是 `0600`；目录建议 `0700`。
- 写入使用同目录临时文件 + `os.replace` 原子替换；`umask 077`；失败不破坏旧文件。
- `state.meta.json` 只放：`source`、`written_at`、`expires_at`、`base_url_fingerprint`、`probe` 摘要、`state_sha256`；**不放令牌、cookie 值、密码**。
- 日志 / 错误 / 证据包不得输出 state 内容；只输出路径、来源、指纹前 12 位、probe 状态与脱敏原因。
- 安装器重放不得把 `.atlas-auth/` 带入制品；成员仓同步不复制该目录。

---

## 10. 改动面清单（v1）

- [ ] **契约/文档**：`rings/e2e/reference.md` §7.1（C 命令、D 预检、probe 契约、state 形态与指纹、导航层 query 保真）；`shared/stack-profile.md` §2（`probe`、字段矩阵、`storage_state` 非法）；`DESIGN.md` 决策记录。
- [ ] **CLI**：`bin/atlas.js` + `scripts/atlas_e2e_login.py`（`atlas e2e login`）。
- [ ] **控制台**：`scripts/e2e_console.py`（state 形态识别、过期判定、probe 调用、来源 / 指纹 / 哈希校验、失败文案；不改执行 / 判定逻辑）。
- [ ] **生成器**：`scripts/gen_e2e_scripts.py`（`atlasGoto` query 保真、state 工具函数、meta 读写；A 相关代码默认关闭且不生成）。
- [ ] **测试**：`tests/test_gen_e2e_scripts.py`（`atlasGoto` 缺失 query 失败、正常同源通过）、`tests/test_e2e_console.py`（三形态 × 过期 / 无法判定 / probe 失败 / 指纹不符）、`tests/test_validators.py`（字段矩阵、`none`/`fabricated` 禁 `probe`）、`tests/test_cli_commands.py`（`e2e login` 路由）。
- [ ] **兼容性**：存量无 meta 的 `state.json` 按形态推断；无法判定 ⇒ 首次执行被拒绝并提示 `atlas e2e login`；不要求重跑 `atlas init`，重装配 `.atlas` 即可。

---

## 11. 验证计划（提案阶段不执行）

### 11.1 单测

- `real`：JWT `exp` 过期 / 未过期 / 无 `exp` 且无 meta ⇒ 分别拒绝 / 进入 probe / 拒绝。
- `fabricated`：字面量假令牌在 `fabricated` 下可用；在 `real` 下拒绝；写 `probe` ⇒ 配置 FAIL。
- `imported`：`written_at` 超过 8h ⇒ 拒绝；meta 缺失 ⇒ 拒绝；probe 通过 / HTML 200 / 超时 ⇒ 通过 / 拒绝 / 拒绝。
- 指纹：同 host 不同 `organId` 指纹不同；`ATLAS_BASE_URL` 只改 host 时 query 指纹不变、host 指纹变。
- 导航层：同源导航缺 `organId` ⇒ 导航前失败；跨域 SSO 放行；回到同源后重新校验。
- 卫生：state / meta `0600`；`.atlas-auth/` 忽略规则缺失 ⇒ 门失败；日志不含令牌。

### 11.2 两条真实 dogfood（不是全量 E2E）

1. **过期拦截**：构造一个**可解析但已过期**的 state（JWT `exp` 已过，或 `imported` 的 `written_at` 超过 8h），执行单条受保护用例；预检必须拦截，用例**不得变绿**，错误信息给出 `atlas e2e login`。
2. **租户不串**：执行 `atlas e2e login` → 保存 state → 用完整 `app_base_url`（含 `organId`）跑单条租户相关用例；确认 probe 与用例都落在声明租户，`Amp-Organ-Id` 未回落成 `1`。该条同时验证 A 启用后的回写（登录 → 回写 → 租户指纹不变）。

不跑全量 E2E；不启动无人值守浏览器；dogfood 由人在本地执行并记录结果。

---

## 12. 不在本提案范围内

- **A 不进 v1**：执行期回写默认关闭，独立后续项；本提案只保留其契约，不在 v1 实现。
- 不自动完成 SSO / 图形验证码 / 服务端会话续期。
- 不新增 `app_login` 第四态；不改 `real` / `fabricated` / `none` 三态语义。
- 不改 `e2e_console.py` 的执行 / 判定逻辑、零步基线、`atlas-hold` 持窗行为。
- 不改成员仓的用例内容或断言；不把登录态写进日志、证据包或制品。
- 不做跨机器 / 跨环境会话同步；`state.json` 仍是单机文件。
- 不把 `playwright codegen` 从文档删除；它保留为应急路径。

---

## 13. 风险与开放问题

- **probe 端点缺失**：`real` / `imported` 项目必须声明 probe；没有 probe 就不能执行。这是有意的 fail closed，但会带来一次性接入成本。
- **会话 cookie 无过期**：`imported` 依赖 `written_at` + `max_session_age` 的启发式，最终仍由 probe 判定；meta 缺失即拒绝，不做「先跑跑看」。
- **probe 与页面上下文差异**：probe 必须复用同一 origin / query / 会话；若应用只在浏览器里设置 `Amp-Organ-Id`，probe 需要显式带上同一派生头，否则会误判。
- **A 的回写并发**：未来启用时仍受 `workers: 1` 约束；并行前必须加锁或只在主进程回写。
- **字段矩阵迁移**：`storage_state` 等矩阵外字段会让存量 profile FAIL；落地时需逐项目清理，本提案不代改。
- **敏感信息**：state / meta 必须 `0600`，错误信息只输出路径、来源、指纹前缀与 probe 状态；任何令牌、cookie 值、密码不得入日志。
