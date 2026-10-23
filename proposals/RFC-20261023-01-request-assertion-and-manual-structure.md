# RFC-20261023-01 · E2E 请求断言动词与结构化人工走查

> 提案编号：RFC-20261023-01
> 提案作者：@sunwenzhe（agent 起草）
> 关联状态：**已拍板（2026-10-23，维护者确认；按评审意见修订，跳过 round 2）**；决策编号 **D142 / D143**
> 影响范围：核心契约 (shared) | 环契约 (rings) | 校验器 (validators) | 脚本工具 (scripts) | 控制台模板 (templates)

> **修订（2026-10-23，覆盖 §2.1 相应段落）**：本稿按 [REVIEW-2026-10-23](./REVIEW-2026-10-23-request-assertion-and-manual/README.md) 的 F1–F6 收敛，落地以本节为准：
> - 编号改为 **D142 / D143**（D140/D141 已被占用），变异 **M145–M148**。
> - `request`：**动作锚定新请求**——`after:N` 在第 N 步前记请求序号，无锚锚最后一步；只断言该时点后**新出现的第一条**匹配请求，无新请求 ⇒ FAIL；路径三态 `(缺席)` / `null` / `""`，中间缺失/过滤 0 或多命中/越界/请求体解析失败 = 解析错误；含该断言的用例默认 `trace: off`（`ATLAS_REQUEST_TRACE=1` opt-in），失败消息不打印载荷；`validate_testids` 与零步基线均豁免 api 后缀。
> - 人工块：`## <ID> <标题>` 提供 id/title，`atlas-manual` 块用**扁平行式** `操作 | 观察 | 命令(可空)`；解析单源 `_support/manual_block.py`；账本仍用例级，不扩 schema。
> - 评审报告：`proposals/REVIEW-2026-10-23-request-assertion-and-manual/`（2 Critical / 4 Major，均已按上条收敛）。

> **来源**：2026-10-23 会话。一个前端项目在验收「保存请求 payload 不应包含某字段」时，用例 DSL 无任何请求观测/断言动词，只能退回 DevTools 人工查看；同时 `manual.md` 是单行 prose，控制台除了渲染这段文字什么也做不了。临时用 `page.on('request')` 监听请求即可稳定完成该断言——证明这是 **DSL 表达力缺口**，不是用例只能人工。
> **零业务上下文**：本稿按 `.atlas/shared/global-rules.md` §15 抽象，不含产品名、业务名词、真实数据或业务代码。

---

## 1. 现象与取证 (The Problem & Evidence)

### 1.1 触发形态（抽象）

**形态 A：请求 payload 断言无动词**

- **规则 / 环节**：`rings/e2e/reference.md` §5.5 断言动词表 + `scripts/gen_e2e_scripts.py::ASSERT_VERBS`（`text / contains / count / visible / hidden / enabled / disabled / checked / value / attr / delta …`）。
- **触发时机**：用例需要验证「某个提交请求的 JSON 载荷中，某字段存在/缺席/等于某值」。
- **具体行为**：动词表只覆盖 DOM 可见态；请求载荷检查只能写成 `precondition` 散文，或由人打开 DevTools 手工看。用例资产无法表达，控制台也就无法执行。

**形态 B：人工走查项是单行 prose**

- **规则 / 环节**：`product/e2e/manual.md` 一行 `- <ID> | <页面> | <标题> | <操作说明>`（`scripts/e2e_console.py::read_manual`）。
- **触发时机**：打开控制台的人工走查卡片。
- **具体行为**：`read_manual` 把第 4 段之后整体拼成 `note`；控制台只能把这段文字原样显示。步骤、命令、观察点、证据要求没有字段承载，UI 无法分步渲染、无法复制命令、无法逐项核对。

**形态 C：把「前端错误渲染」误当成「后端失败语义」**

- **规则 / 环节**：`rings/e2e/reference.md` §5.8 网络边界打桩适用判据。
- **触发时机**：想用页面 mock 覆盖「上游服务调用失败」类用例。
- **具体行为**：mock 只能验证前端拿到失败结果后的渲染；服务端失败映射（异常 → 错误码/错误文案）仍无机器覆盖。本条不是 DSL 缺口，而是覆盖层次归属问题（见 §2.2 被否 E）。

### 1.2 客观证据（仓库实锚）

```text
scripts/gen_e2e_scripts.py:97
ASSERT_VERBS = ("text", "contains", "count", "countOptions", "visible", "hidden",
                "enabled", "disabled", "checked", "unchecked", "value", "attr", "delta")
# 无 request / requestBody / network 一类动词

scripts/e2e_console.py:227-245（read_manual）
每行 `- <ID> | <页面> | <标题> | <操作说明>`；parts[3:] 以 " | " 拼成 note
# 无步骤/命令/观察点字段

templates/e2e/console/app.js:71-77
S.manual.map((m) => ({ id, page, title, type: 'manual', status: 'manual' … }))
# 卡片数据只有 note，没有结构
```

**最小复现（临时脚本，不落库）**：Playwright 在测试上下文监听 `page.on('request')`，解码表单 `params`，取 `Data.reqDTO...` 路径并断言字段缺席——10 行脚本即可稳定通过；同一断言在现有 DSL 里没有任何写法。

### 1.3 结论

- 请求载荷断言、提交后副作用检查这类「网络面断言」是真实需求，当前 DSL 缺表达面。
- 人工走查卡片的信息量受资产 schema 限制；控制台「简陋」是如实渲染的结果，不是 UI 单独能修的。
- 两类问题可以独立落地：A 补动词（机器覆盖），B 补结构（人工体验）。

---

## 2. 决策与权衡 (The Decision & Trade-offs)

### 2.1 核心定案

#### 批 1（建议 D140）：新增 `request` 断言动词

**语法**

```atlas-case
expected:
  - request app.updateApp Data.reqDTO.config.nodes[type=MailRead].config.nodeParam.mailStatus (空)
  - request app.updateApp Data.reqDTO.config.nodes[type=MailRead].config.nodeParam.keywordEnabled true
  - after:6 request app.updateApp Data.reqDTO.config.nodes[type=MailRead].config.nodeParam.count 20
```

- 三段式：`request <api> <json-path> <expected>`。
- `<api>`：`Api` 查询参数的**唯一后缀**，如 `app.updateApp` 匹配 `zeldaEasy.platform-console.app.updateApp`；命中多个不同 API ⇒ **响亮失败**并列出候选（与 `select` 的歧义拒绝同族）。
- `<json-path>`：点号键 + 可选 `[N]` / `[key=value]` 过滤；纯遍历、无 eval。例：`a.b[0].c`、`nodes[type=MailRead].config`。
- `<expected>`：
  - `(空)` = 路径不存在或值为 `null`；
  - `""` = 空字符串；
  - 其余按 JSON 字面量解析（数字/布尔/对象/数组），非法 JSON 则按字符串全等。
- 缺省取**最近一次**匹配请求；`after:<N>` 合法（等第 N 步后轮询出现）；**不得**与 `initial:` / `unchanged:` 叠写（没有「初始态请求」语义）。

**捕获与解码**

- 生成器在用例首屏 `goto` **之前**发射 `await atlasWatchRequests(page);`：
  - 监听 `page.on('request')`，按 `api` 查询参数归档最近一次请求；
  - 请求体解码顺序：表单 `params` → `JSON.parse`；`application/json` → `JSON.parse`；否则原文；
  - 只保存在测试内内存，不落盘、不打印请求体。
- `atlasExpectRequest(page, api, path, expected)`：
  - `expect.poll` 等匹配请求出现（超时 `ATLAS_WAIT_TIMEOUT_MS`），再解析路径；
  - 失败消息只打印 `api + path + expected`，不打印完整载荷（防敏感数据进日志/报告）；排障开关 `ATLAS_DEBUG_REQUESTS=1` 才输出载荷摘要。
- 与 `mock:` 正交：mock 请求同样会触发 `request` 事件；但本动词断言的是「请求形状」，不是「响应结果」。

**零步基线与门禁**

- `request` 断言**不参与零步基线**（它由动作派生，初始态没有请求；与 `delta` 同处理）。
- 校验器：`request` 必须有至少一条 `step`；`<api>` 不得为空；`<json-path>` 语法校验；`after:N` 的 N 仍按 step 计数。
- 生成器：无 `request` 断言的页面生成物**逐字节不变**（零变化承诺）。

**证据披露**

- 每条 `request` 断言通过时，测试注记追加 `atlas-request: <api> <path>`（不含值）；控制台用例卡可显示 `REQUEST` 证据行（与 `MOCKED` 同级但不改变通过判定）。

#### 批 2（建议 D141）：结构化人工走查

**目标**：保留现有单行格式（100% 兼容），新增可选的结构化块；控制台按步渲染并支持复制命令。

**推荐格式**（放在 `manual.md`，与旧行共存）：

```markdown
## MANUAL-XXX 标题

```atlas-manual
id: MANUAL-XXX
page: some-page
title: 标题
precondition:
  - 已登录且有可用数据
steps:
  - action: 打开节点面板
    expect: 面板出现
  - action: 修改某字段并保存
    command: |
      const params = JSON.parse(decodeURIComponent(payload));
      // 可选：可直接复制到 DevTools Console 的片段
    expect: 保存请求载荷中字段 X 缺席
evidence:
  - 请求载荷截图
```
```

- 解析：`scripts/e2e_console.py` 先读旧行，再读 `atlas-manual` 块；同 ID 重复 ⇒ FAIL。
- 控制台：卡片显示结构化步骤；每步「操作 / 观察」分列，`command` 提供复制按钮；「打开」仍按页面路由打开。
- 账本：**仍保持用例级通过**（不新增逐步骤账本），步骤勾选只作本地面板进度，避免账本 schema 扩张。
- 校验器：新增 `validate_e2e_index` 的 manual 解析检查（ID 唯一、page 存在、steps 非空、action/expect 非空）；旧行格式照旧。
- 迁移：存量 manual.md 不动；新写或重写的条目用新块；不强制批量迁移。

#### 批 3（可选，暂不定案）：`验证脚本:` 挂载

人工项可选声明一个项目脚本路径，控制台执行并展示输出，明确标注「辅助证据，不替代人工通过」。需要权限/网络边界设计，留待批 3 单独评审；本 RFC 不纳入。

### 2.2 考虑过的备选方案及否定理由

- **备选 A：允许用例里写任意 JS/Python 脚本**
  - *否定理由*：生成物不可审计、安全边界消失、零依赖契约被打破；等于把 E2E 变成脚本仓库。
- **备选 B：引入完整 JSONPath 库**
  - *否定理由*：Atlas 生成物零第三方依赖；完整 JSONPath 的语义面（通配、递归、过滤表达式）远超需求，且难以做确定性校验。采用最小路径子集即可覆盖。
- **备选 C：用 `mock:` 伪造失败响应来断言错误渲染**
  - *否定理由*：只能证明前端渲染，不能证明后端失败映射；对「服务端记得上一步」的流程 §5.8 明确出界。该层应由后端集成测试承载。
- **备选 D：只美化控制台，不改资产 schema**
  - *否定理由*：UI 无法从一段 prose 中推断步骤/命令；美化只能改善排版，不能增加信息量。
- **备选 E：把人工步骤写进 `precondition` 或 `intent`**
  - *否定理由*：这些字段是语义说明，不受执行器消费；继续把可执行信息塞进散文，等于维持现状。
- **备选 F：请求断言做全局共享缓存**
  - *否定理由*：跨用例污染、并发不安全；必须按测试上下文隔离，生命周期与用例一致。

### 2.3 刺痛代价与兼容性影响

- **零变化承诺**：未使用 `request` 动词的项目，生成物逐字节不变；校验器只是放宽词表，不改变既有判定。
- **隐私**：请求体可能含凭据/个人信息；默认不落盘、不打印，失败消息只给路径和期望值；`ATLAS_DEBUG_REQUESTS` 为显式排障口。
- **性能**：每条用例多一个 request 监听器与一次 Map 写入，开销可忽略；只保留每个 API 的最近一次请求。
- **语义边界**：`request` 只观测**请求**，不观测响应/SSE/WebSocket；响应断言仍归后端测试或后续独立提案。
- **人工结构**：旧 manual 行不迁移也能正常工作；新块解析失败必须 FAIL（不静默忽略），避免结构化信息写歪后无人发现。

---

## 3. 改动面清单 (Affected Surface)

### 批 1（D140）

- [ ] **契约/文档**：`rings/e2e/reference.md` §5.5（新增 `request` 行、正反例）、§7.1（请求观测与隐私）、§8.2（动词合法性/步骤锚/零步基线豁免）；`DESIGN.md` D140；`CHANGELOG.md`。
- [ ] **代码逻辑**：`scripts/gen_e2e_scripts.py`（`ASSERT_VERBS`、`ts_case` 发射 watcher、`ts_assert_expr` 支持基线豁免、helper 源码块）；`validators/validate_e2e_index.py`（`ASSERT_VERBS`、路径语法、必须有 step、`initial/unchanged` 叠写拒绝）。
- [ ] **测试防线**：
  - `tests/test_gen_e2e_scripts.py`：生成物含 `atlasWatchRequests` 且位于首个 `goto` 前；`atlasExpectRequest` 发射形态；无 `request` 用例逐字节不变（零变化钉）。
  - `tests/test_validators.py`：正向（合法 api/path/expected + step）、坏输入（无 step / 空 api / 非法 path / 与 `initial:` 叠写）各 FAIL；动词表两侧同步。
  - Node 真求值：mini path 解析器覆盖缺失键、null、空串、数组索引、`[key=value]` 过滤、歧义 API。
  - 变异：**M140a** 摘 watcher 发射 ⇒ 生成物钉红；**M140b** 缺失键返回 `""` 而非 absent ⇒ 校验钉红；**M140c** 校验器接受无 step 的 request ⇒ 坏输入钉红。
- [ ] **版本装配**：`shared/gates.md` 中 `tests/test_gen_e2e_scripts.py` / `tests/test_validators.py` 计数同步；`test_canonical_consistency.py` 计数/词表一致性。

### 批 2（D141）

- [ ] **代码逻辑**：`scripts/e2e_console.py::read_manual`（兼容旧行 + `atlas-manual` 块）；`templates/e2e/console/app.js`（步骤列表、复制命令、进度勾选）；`validators/validate_e2e_index.py` 或新增 `validate_manual.py`（块解析/字段校验/ID 唯一）。
- [ ] **测试防线**：`tests/test_e2e_console.py`（旧行兼容、块解析、坏块 FAIL）、`tests/test_validators.py`（ID 重复、缺 steps、未知 page）；变异 **M141** 摘掉块解析 ⇒ 新格式未被消费即红。
- [ ] **文档**：`product/e2e/README.md` 模板、`rings/e2e/reference.md` 人工项章节；`DESIGN.md` D141。

---

## 4. 验证与测试结果 (Verification)

实施后必须：

```bash
pytest tests/test_gen_e2e_scripts.py tests/test_validators.py tests/test_e2e_console.py
pytest tests/
python3 scripts/atlas_check.py --fast
```

- 既有项目生成物零变化（不含 `request` 断言的 spec 逐字节比对）。
- 用一条真实的「保存请求字段缺席」用例做端到端验证：用例从「人工 DevTools」迁移到 `request` 断言；在真实应用上跑绿，并保留失败时的可读报错。
- 变异四段协议：基线绿 → 注入红 → 逐字节还原 → 复绿。

---

## 5. 开放问题（拍板前需确认）

1. **API 匹配**：`app.updateApp` 后缀是否足够？是否要求完整 `zeldaEasy.<ns>.<svc>.<method>`？建议后缀 + 歧义拒绝。
2. **路径语法**：是否支持通配/递归？建议 v1 只支持点号键、`[N]`、`[key=value]`；通配留待真实需求。
3. **最近一次 vs 第 N 次**：重试/自动保存会多次发同一 API；建议默认最近一次，后续按需加 `request[1]` 形态（与 `[N]` 序位一致）。
4. **敏感值**：期望值本身可能是敏感串（token）；失败消息是否需要对 expected 做掩码？建议默认只打印路径与「不匹配」，值长度/类型可打印。
5. **人工结构**：步骤勾选是否需要进账本？建议 v1 只做面板进度，账本保持用例级。
6. **请求 vs 响应**：本批只做请求；响应断言/SSE 是否另起 RFC？建议另起，避免动词语义膨胀。

---

## 6. 落地顺序与回滚

1. 批 1（D140）：契约 + 生成器 + 校验器 + 单测 + 变异钉；发布 beta；重装；把一个真实的人工 payload 检查改成 `request` 断言并跑绿。
2. 批 2（D141）：控制台/解析器/模板 + 单测；旧 manual 行不动；用一条新格式条目验证渲染与复制。
3. 任一批可独立回滚：批 1 不影响旧生成物；批 2 不影响旧 manual 行。

> **不解决的范围**：上游服务故障注入、响应体断言、SSE/WebSocket 流断言、跨用例共享请求缓存。这些留给后端集成测试或独立 RFC。
