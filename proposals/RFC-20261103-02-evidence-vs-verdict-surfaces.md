# 证据面 ⇄ 判分面：运行目录的读取边界

> 提案编号：RFC-20261103-02
> 提案作者：Atlas 维护批（用户 2026-11-03 拍板「按你推荐的来」）
> 关联状态：已定案（Accepted，实现已落；`REVIEW-20261103-01` 修后通过，必修项已落）
> 影响范围：核心契约（`shared/`）· 环契约（`rings/e2e/`）
> 关联：`proposals/BACKLOG-execution-layer.md` §5（执行层定界）；`RFC-20261018-01` / `DESIGN.md` D108（失败留证）、`RFC-20261025-02` / `DESIGN.md` D151（backfill 写面）
> 外部参照：`google-research/harness2`（Apache-2.0，arXiv 2610.14224）的「判分对改进者不可见」三重隔离，只借「证据载体与判分载体必须可区分」这一条语义，不引入其递归框架。
> 评审轨迹：设计稿一轮（仓外）砍掉了原稿的「归属对账 WARN 门」；RFC 文本二轮（仓外）修正了 `.last-run.json` 的归类错误与 §4.5 的预判结论。两轮均未落 `REVIEW-*` 文件。

---

## 1. 现象与取证

### 1.1 触发形态（抽象）

- **规则 / 环节**：E2E 环执行产物的落点（`.atlas-run/`）。
- **触发时机**：一个面向「改进 / 诊断 / 执行」的消费者（未来自建执行层、缺陷归因、自动收紧契约）为了定位失败去读运行目录。
- **具体行为**：该目录同时承载**证据载体**（失败现场的回放与截图）与**判分载体**（运行器 JSON 报告、上次运行状态文件）。消费者按「读整个目录」的直觉行事，即等于读到判分结论。

### 1.2 客观证据

**写入方**（同一条配置把两类载体写进同一目录）：

```text
scripts/gen_e2e_scripts.py:2336   ['json', { outputFile: '.atlas-run/results.json' }]
scripts/gen_e2e_scripts.py:2338   outputDir: '.atlas-run'
scripts/gen_e2e_scripts.py:2372   ['json', { outputFile: '.atlas-run/results.json' }]
scripts/gen_e2e_scripts.py:2374   outputDir: '.atlas-run'
```

**证据载体**（D108 契约条 + 真跑日实态）：`<用例目录>/trace.zip` + `test-failed-*.png` 成对；`video` 缓行未启用，若启用则为 `*.webm`。

**判分载体**：
- `results.json` —— 运行器 JSON 报告，含每个用例的 `status` / `expected`；
- `.last-run.json` —— 运行器自己的「上次运行」状态文件。**归类依据**：它是运行器自带的「上次运行」状态文件（内容即运行状态），随运行生成；D128 的指纹免疫口径（`DESIGN.md:597`）与机器面 `scripts/e2e_console.py:148` / `:183` 的后缀闭集（`.trace` / `.png` / `.webm` / `.last-run.json`，钉 = `tests/test_e2e_console.py:853`）把它归为运行时产物——该闭集是**指纹免疫清单**，不是证据 / 判分归类表。

**判分读取方**：`scripts/atlas_check.py:748`（E2E 真跑门取结果）、`scripts/atlas_verify.py:161`（backfill 解析）。

**外部同类事故（机制参照，非 Atlas 证据）**：`harness2` 把同一形态记为一次真实事故——交付物树与判分输出同目录，改进者读到判分通过率与失败检查项名（`harness2/core/context.py:351-361`）。它此后以三道独立校验隔离：措辞层拒收判分词汇（`core/spec.py:119-127`）、运行视图永不携带分数（`core/spec.py:177-187`）、经验写入前两处校验无判分裁决（`core/library.py:106-123`）。

### 1.3 诚实边界

Atlas 当前**没有任何**改进器读取 `.atlas-run/`。本条**不是存量缺陷，是预防性边界**——立条的成本今天很低；一旦自动消费者先落地、边界后补，改动面会扩大到生成物落点本身（见 §2.2 备选 B）。

---

## 2. 决策与权衡

### 2.1 核心定案

1. **通则**：`shared/global-rules.md` 新增 §17「证据面 ⇄ 判分面（硬）」——交付面的证据载体与判分载体必须**可区分且有清单**；面向改进 / 诊断 / 执行的消费者**只读证据面**，判分面只由门与回填读取。无清单的目录不得作为改进输入。
2. **实例**：`rings/e2e/reference.md` §7.1（生成器契约）内「失败留证」条（`rings/e2e/reference.md:519`）之后补一张二分表：

   | 面 | 文件形态 |
   |---|---|
   | 证据面 | `<用例目录>/trace.zip`、`test-failed-*.png`、（启用时）`*.webm` |
   | 判分面 | `results.json`（运行器 JSON 报告，含 `status` / `expected`）、`.last-run.json`（上次运行状态） |

3. **单一真相源**：`shared/single-source.md` §1 登记「`.atlas-run/` 文件归属清单」= `rings/e2e/reference.md` §7.1。
4. **纪律面如实登记**：本条**没有机器判据**，按既有口径（2026-10-15 v2 抽取）登记为纪律与盲区面，不假装是门。表格保持固定两列，使未来加白名单时不必改契约。
5. **不把 `results.json` 写进 `global-rules.md` 正文**：§17 只写通则；具体文件名只出现在 e2e 环契约的表里（**契约面** `shared/` + `rings/` 内唯一；避免跨环复制清单）。

### 2.2 考虑过的备选方案及否定理由

- **备选 A：在 `atlas_check` 加「归属对账」WARN 门**（扫目录，未登记文件即点名）
  *否定理由*：目录里的构件随运行器版本演进（今天 `.trace` / `.png` / `.webm` / `.last-run.json`，明天可能多 `error-context` 一类），门出生即常态 WARN。`shared/gates.md` 元规则第 3 条（响亮原则）反对把常态 WARN 当判据——它会训练读者忽略这一行。
- **备选 B：物理把 `results.json` 搬出证据目录**
  *否定理由*：撞 D108 的留存窗口（运行器起动即清空 `outputDir`）与 D151 的回填通道（`atlas_verify.py:161`）；且执行层定界（`BACKLOG-execution-layer.md` §5）未做，现在搬会产生两套落点。改为记入该 backlog §5 的待定界项。
- **备选 C：先建读取器白名单代码**
  *否定理由*：当前没有证据读取器，白名单无消费者，属空转（`shared/global-rules.md` §12「先量再动手」）。

### 2.3 生效后的升格条件

以下任一发生，本条从纪律面升为机器门，并评估 `results.json` 物理迁出：

1. 出现**第一个**「改进 / 诊断 / 执行」消费者读取 `.atlas-run/`；
2. 该目录出现**第三类**载体（今天的证据族 + 判分族之外的形态）。

升格动作 = 白名单校验 + backlog §5 的「迁出 / 保留 / 双轨」三选一。

### 2.4 代价与兼容性

- 不改变任何生成物、不改任何退出码、不改任何既有判据 ⇒ **采纳仓零行为变化**。
- 成本：契约正文约 15 行 + 一处登记。
- 已知盲区：条款靠纪律执行，无机器面；若长期没有自动消费者，它就是一份低成本的前置文档。

---

## 3. 改动面清单

- [x] **契约**：`shared/global-rules.md` 新增 §17
- [x] **环契约**：`rings/e2e/reference.md` §7.1「失败留证」条后补二分表
- [x] **单一真相源**：`shared/single-source.md` §1 登记行
- [x] **待办登记**：`proposals/BACKLOG-execution-layer.md` §5 记「`results.json` 物理落点待定界」一条
- [ ] **代码逻辑**：无
- [ ] **测试防线**：不适用（无判据输出变化；核对见 §4.5，实现轮补原始输出）
- [ ] **版本装配**：无（`shared/` 随 `cp -R` 整目录装配）

---

## 4. 验证与测试结果

```bash
python3 -m pytest tests/ -q
python3 scripts/atlas_check.py --fast
grep -rn "results.json" rings/ shared/    # 应只有 §7.1 那一处正文
```

* 测试结果（2026-11-03 实测）：`pytest tests/` = **1,116 passed / 3 failed**——3 个失败（`test_no_framework_names` / `test_atlas_verify_playground` ×2）经单独复跑全部转绿，红因 = 并行会话同窗在改同一批文件（`atlas_eval` 登记行等），非本批判据；本批新增 `tests/test_gate_registry.py` 3 条全绿（该文件属 RFC-03）。
* 自检结论：`atlas_check --fast` = **OK**（SKIP 均为合法降级态）。
* 独立评审（`REVIEW-20261103-01`）在 /tmp 冻结副本复跑：**1,119 passed / 5 skipped / 0 failed** —— 上句 3 个失败确认为并行窗口瞬时红。
* grep 断言：`results.json` 在 `rings/` + `shared/` 仅 §7.1 一处正文（1 处命中，符合预期）。

### 4.5 留出验证（系统性修复必填）

- **触发面核对 (a)：族锚**
  实测命令与输出（2026-11-03 当日树）：

  ```text
  $ grep -n "证据面\|判分面" duty-review/bugs.md
  （无输出，退出码 1）
  ```

  ⇒ 无 `bugs.md` 同根归纳锚，本条不是缺陷修复。
- **触发面核对 (b)：路径族**
  本条尚未实现，无 diff 可判。实现轮必须粘贴两条原始输出（命令 + 输出，可复算）：

  ```bash
  git diff --name-only <base>..HEAD
  python3 scripts/closeout_derive.py --diff-base <base>
  ```

  预期路径 = `shared/global-rules.md`、`shared/single-source.md`、`rings/e2e/reference.md`、`proposals/BACKLOG-execution-layer.md`；是否落在门 / 校验器路径族，以派生器输出为准，**实现前不预填结论**。
- **留出集**：不适用——本条不产生任何判据输出翻转（verdict / 案数 / 日期 / 精确病案数均不变）。
- **三态结论**：待实现轮按 §4.5 实测结果落定；当前不得宣称闭族。

---

## 5. 被否方案与残留风险

- 被否：归属对账 WARN 门、物理搬家、白名单代码（见 §2.2）。
- 残留风险：条款存在但无人执行。补偿 = §2.3 的升格条件 + `single-source.md` 登记（有可见落点，不靠记忆）。
- 不解决：D103 登录态盲区、D108 留存窗口——两者与本条正交，引用 §2.2 备选 B 只为说明物理搬家的代价。
