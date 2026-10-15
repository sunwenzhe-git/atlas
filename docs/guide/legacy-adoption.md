# 存量项目接入指南（adopt）

> 面向：已经跑了很久、代码与业务规则都在、文档不全的既有项目。
> 本文只回答一件事：**Atlas 接入存量项目时，要求你做什么、不要求你做什么**。所有结论以 `.atlas/` 契约与校验器源码为准。

设计原则一句话：**只登记基线，不逆向考古**。接入不要求补历史 testid、不要求重写历史文档；存量页面不会把门禁刷红；历史债务由后续需求按域逐页「顺路」还。

---

## 1. 接入步骤与 Checklist

### 接入步骤 Checklist

| 序号 | 步骤 | 命令 / 动作 | 核心交付物 / 目的 |
|---|---|---|---|
| 1 | 装配与画像 | `atlas init` + 与 Agent 核对 `product/stack-profile.yaml`（草稿不用手改） | 确认 `origin: adopt` 与技术栈画像 |
| 2 | 一次性开户与结构初始化 | `/atlas-apply adopt` | 逆向抽取结构事实（`_meta.json`、`current/`）与 PRD 开户最小集 |
| 3 | 生成实现期薄桩 | `python3 .atlas/scripts/gen_testid_stub.py --root .` | 产出 `.trellis/spec/conventions/testid.md` = 老页面 testid 实然盘点（非硬门前置：缺失会被 `validate_testids` 自动补齐） |
| 4 | 首日静态体检复核 | `atlas check --fast` | 验证门禁全绿或仅有合法 WARN |
| 5 | 需求增量流转 | `/atlas-apply <需求ID>` | 日常流转，按域增量生长 |

---

### 第 1 步：装配与画像（`atlas init` + `stack-profile.yaml`）

```bash
npm install -g atlas-project-harness
cd your-project
atlas init
```

> ⚠️ **这一步只完成「装配」，不等于已接入**。`atlas init` 落下的是线束与骨架：`.atlas/`、`product/`（含画像草稿与空的 `e2e/cases/`）、AGENTS.md 指针、Trellis 接线。**开户是第 2 步**——开户产物是 `product/prd/` 与 `.trellis/spec/structure/` 的**内容**（现在都还是空的）。把这两个目录当成「开户进度条」：为空 ⇒ 还没开户，说「接入」时 Agent 应当直接进 `atlas-apply adopt`，**而不是**因为 `.atlas/` 已存在就判「已接入」。

画像草稿不用你手改 —— 第 2 步开户时 Agent 会带着你逐项核对下面三处关键声明（也可以自己先看草稿）：

* **`origin: adopt`** —— 声明存量形态：PRD 走「增量起步」，开户只开最小集；
* **`apps[]`** —— 真正落地的实现标 `role: landing`；被重构替换中的旧代码（作为事实来源）标 `role: legacy`；
* **`adapters`** —— 技术栈命中现有适配器（routes / api / models / tests）就声明；未命中留 `null`，由 agent 阅读代码撰写结构事实。

> 出厂草稿含占位符，未替换前 `atlas check` 必有门禁 `FAIL`——这是 fail-closed 的设计行为，不是安装坏了。

### 第 2 步：一次性开户与结构初始化（`atlas-apply adopt`，只跑这一次）

对 Agent 说一句大白话——「帮我把这个项目接入 Atlas 工作流」（或 `/atlas-apply adopt`）。开户只做两件事：

1. **structure 环全量**：逆向抽取结构事实（路由 / 接口 / 数据模型 / 测试现状），按路由簇、模块簇、表/模型命名簇聚类出候选域，写入 `_meta.json.domains`。**域 id 是全链路键**——PRD、E2E、注入给实现任务的结构事实，全部按域对齐；
2. **PRD 开「开户最小集」**：
   * 全局 `prd.md`：只落三件——`范围形态：变更`、`覆盖度`、`基线`；
   * 每个域一份 `<domain>-prd.md`：止于「概述 + 功能清单 + 业务规则 + AC」；状态机、字段校验、六类文案、异常处理等细化件，留到该域真的有需求时再补。

**关键承诺：开户不预设 E2E**——不猜老业务的验收用例、不要求补 testid、不产生历史页面的对账债务。老项目的 UI 与流程已经在代码里，从代码反推产品意图再全量重写 PRD 与用例，既不可能也没价值。

### 第 3 步：生成实现期薄桩（`gen_testid_stub.py`，开户交尾）

在结构初始化之后、首日体检之前，显式执行一次薄桩生成：

```bash
python3 .atlas/scripts/gen_testid_stub.py --root .
```

> **为什么建议显式跑一次**：薄桩是**开户交割物之一** —— 生成器扫描既有前端源码，产出**老页面 testid 的实然盘点表**（契约 §4.1）。
> **注意它不是首日的硬门前置**：薄桩缺失时 `validate_testids.py` 会**就地自动补齐并记 `PASS`**（F32 机器兜底，2026-10-15 起；`FAIL` 只留给生成失败的真错）。所以显式跑一次是为了让这份交割物**当场可见、可核对**，而不是躲在某道门的副作用里。

随后即可执行首日体检，确认基础门禁全绿：

```bash
atlas check --fast     # 秒级静态体检：全部门禁 + 生成物新鲜度
```

### 第 4 步：从第一条需求起，按域增量生长（`atlas-apply <需求ID>`）

开户后日常完全回到 Trellis 任务卡流转；Atlas 在 workflow Phase 1.6 自动调度 `apply <需求ID>`：

* 过**三问门**（这条需求是否改既有能力？是否需要人确认应然 UI？是否需要可重复的端到端验收？）——决定这条需求拉起哪些环；
* 推导影响面 → **只变更受影响域**的 PRD 章节与受影响页的用例分片，不做全库无差别校验；
* 三问全否（纯加法 / 内部重构 / 用户不可见的后端改动）：写一行「本需求判定：纯加法 / 不启用三环」+ 依据，直接进实现。这是合法旁路，不是绕过工作流。

---

## 2. 为什么存量项目不会「门禁天天红灯」

这是接入前最普遍的担心，逐条对着校验器源码回答：

**机制一：开户不预设 E2E**（见上）——没有历史用例，就没有「开户即红灯」。

**机制二：门禁检查的是「本条需求触及的资产」**，而不是全库全量扫描（三问门分流）。

**机制三：页状态三档 + SKIP（`validate_testids.py`）**。testid 双向对账（分片应然 ⇔ 前端源码实然）是**分页**对账：只有「既有该页分片、前端又有该页 testid」的页才真正进入比较，强度由索引页面表（`e2e-index.md`）的 `实现状态` 列决定：

| 页面状态 | 判定强度 |
|---|---|
| `已实现` | 该页两集合**双向严格相等**，多一个少一个都 `FAIL` |
| `实现中` / `未开始` | 同形缺口降 `WARN`，附逐页清单 |
| 前端无该页任何 testid | 该页整体 `SKIP`，不算失败；实现落地之日才是对账之时 |

* 前端扫描到 0 个 testid（存量项目常见）⇒ 全部页按未实现 `SKIP` + 一条 `WARN`；
* 前端有页但无对应用例分片 ⇒ `WARN`（列出待补用例清单），不是红；
* 缺状态列 ⇒ 按「`已实现`」严判（fail-closed——不允许漏列静默放宽）；状态词表外的取值 ⇒ `FAIL`。

**推论**：存量页面的默认水位是 `SKIP` / `WARN`。红只应出现在两个时刻——① 显式把某页标成「已实现」但事实上没对齐；② 需求触达的页面上新老集合发生漂移。两者都是真实信号。

**机制四：存量 testid 命名保持现状（`validate_testids.py`）**。契约 §4 承诺「既有实现保持现有 `data-testid`」。存量代码里哪怕存在非常规命名（如 `login_btn`、`loginButton` 等历史驼峰或下划线命名），校验器只记为 `WARN` 并附清单，**不判 FAIL**（不因接入动作强迫重构老代码）。用例分片引用已存在于源码中的既有存量命名同样放行；只有作者在用例分片中新声明了源码中不存在的违规名字时，才会触发 FAIL 严判。

**机制五：后端差量棘轮（`validate_ac_alignment.py`）**——与上一次快照比对，挂载 AC 的测试数与覆盖的 AC 数**净增不得为负**；基线快照落 `.atlas/runs/backend-ac-alignment.json`。起步用缺省的 `advisory` 模式即可：覆盖缺口以报告形式呈现，不做全量补齐的强制要求；但已经挂上去的对账关系不许悄悄退回。

随时可用一条命令看全貌：

```bash
atlas check --fast     # 秒级静态体检：全部门禁 + 生成物新鲜度
```

---

## 3. 纯后端 / 全栈项目补充

* **前端 testid 门自动放行**：`stack-profile` 中没有任何 `kind: frontend | fullstack` 的 app 路径时，`validate_testids` 直接判定「门控态 `N/A`」通过——纯后端项目不会被浏览器侧门禁打扰；
* **E2E 环不参与**：契约明示「纯后端 / 接口、用户不可见」的需求不产出 E2E 用例；
* **后端 AC 对账门禁**：在 `product/stack-profile.yaml` 增加可选段 `backend_test` 启用（**段缺失 = 合法降级**）：

```yaml
backend_test:                     # 可选段；缺失 = 合法降级
  command: pytest backend/tests   # 测试执行命令
  test_dir: backend/tests         # AC 挂载点扫描根（缺省 backend/tests）
  framework: pytest               # v1 仅支持 pytest
  mode: advisory                  # advisory（缺省，报告不阻断）| enforce（缺口硬阻断）
  ac_marker: pytest_mark          # 挂载形态：@pytest.mark.ac("AC-xxx")
```

测试代码挂 AC：

```python
@pytest.mark.ac("AC-PAYMENT-001")
def test_refund_rejected_when_balance_insufficient():
    ...
```

四种判据随之生效：

* **无主 AC 拦截**：测试挂载的 AC 在 `product/prd/` 里不存在 ⇒ `FAIL`；
* **无效跳过拦截**：挂了 AC 的测试被 skip / xfail 且未写 `waiver:` 豁免理由 ⇒ `FAIL`；
* **覆盖对账**：报告已声明 AC 与已挂载 AC 的覆盖率（`enforce` 模式下零挂载 ⇒ `FAIL`）；
* **差量防退化**：与上次快照比，挂载数与覆盖数净增不得为负。

> 语言边界：v1 原生支持 Python / pytest（AST 提取）。其它语言的后端暂由账本、结构事实与独立审查门覆盖。

---

## 4. 存量页面从「未接管」到「已覆盖」：实操路径

当某条需求第一次触达一张老页面：

1. **盘点**：跑 `python3 .atlas/scripts/gen_testid_stub.py --root .` 生成实现期薄桩（`.trellis/spec/conventions/testid.md`）。它含**两块清单**——① 分片应然（用例声明的）② **前端实然（源码按页扫描）**。对存量项目，第二块就是现成的老页面 testid 盘点表；
2. **触达**：`apply` 增量把本次需求影响的可交互元素写进该页分片（应然清单）。契约口径是「**既有实现保持现有 `data-testid`**」——不为了对齐某种新命名去翻新旧代码，分片照既有实现写；
3. **复核后收紧**：把页面表状态从 `实现中` 改为 `已实现` 之前，先确认该页双向差集为空。状态一改，该页立即进最严双向判定——**这正是防「刷绿」的设计**：想收紧强度，先把债还完；
4. **不要批量改状态**：把没有对过账的页面成批标「已实现」= 立刻红。宁可留 `WARN`，它是待办清单，不是耻辱柱。

---

## 5. 依赖与边界（诚实清单）

| 项 | 现状 |
|---|---|
| 必需依赖 | Node 18+、Python 3.10+、**Trellis 全局包**（需求级任务状态机是 Atlas 的执行宿主；「先学 Trellis 再用 Atlas」的双重学习成本真实存在） |
| 浏览器级 E2E | Web 单轨（Node + Playwright）；CLI / 移动端 / 嵌入式不适用 |
| 后端验收 | 独立 AC 对账门禁（v1 = Python / pytest） |
| 结构事实 | 无适配器的技术栈由 agent 撰写，质量取决于代码可读性 |
| 成熟度 | `0.1.0-beta`：遇到边缘 case 大概率需要读源码或提 Issue |
