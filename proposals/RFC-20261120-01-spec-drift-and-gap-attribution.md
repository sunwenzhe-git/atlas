# RFC-20261120-01：规格—代码偏差的分类吸收（Spec Kit `converge` / `assess` 情报落地）

> 提案编号：RFC-20261120-01
> 提案作者：Atlas 自动化管家
> 状态：已定案 (Accepted) · v2 —— 2026-11-20 按 v2 落地 A / B 两批；C 批已撤销（理由见 §3.3）
> 影响范围：核心契约 (apply / shared) | 校验器 (validators) | 模板 (templates) | 文档
> 情报来源：2026-11-20 阅读的 GitHub Spec Kit 综述（`converge` 2026-06、`assess` 2026-07、1.0 于 2026-10）

---

## 0. 评审处置摘要（v1 → v2）

v1 提出三批改动，其中 C 批「impact 键级对账门」被评审判为**需重大返工**：它读错了 `_drift.json` 的结构，且设计上存在必然恒绿路径。v2 采纳全部 Critical/Major，C 批撤销。

| v1 主张 | 评审结论（带证据） | v2 处置 |
|---|---|---|
| C 批读 `_drift.json` 的 `added` 键 | 顶层是 `{generated_at, drifts[]}`，元素是 `" ".join(k)` 字符串（[`refresh_structure.py:376`](../scripts/refresh_structure.py#L376)、[`:808`](../scripts/refresh_structure.py#L808)） | **撤销 C 批** |
| 键归一化为 `<app>:<path>` / `<app>:<METHOD> <path>` / `<app>:<name>` | 实际 key_cols 是「应用+页面/路由」/「方法+路径」（**无 app**）/「表/模型+字段」（**字段级，非模型级**）（[`refresh_structure.py:422`](../scripts/refresh_structure.py#L422)、[`:476`](../scripts/refresh_structure.py#L476)、[`:510`](../scripts/refresh_structure.py#L510)） | 同上 |
| `_drift.json` 可做任务级归因 | 它是**全局、瞬时** marker：只反映最近一次 `--apply`，无漂移刷新即 `unlink`（[`refresh_structure.py:801-813`](../scripts/refresh_structure.py#L801-L813)） | 同上 |
| `added` = 「规格没写、实现加了」 | `added` 的真实语义 = 「不在**既有事实表**」（[`refresh_structure.py:370-376`](../scripts/refresh_structure.py#L370-L376)）；不读 PRD/E2E | 类别名从 `unrequested` 撤回 |
| 缺 `predicted_keys` ⇒ SKIP | 沿用现有 `skip()` 会连文件级 miss/over 一起跳过，等于对已生效门静默降级（[`impact_reconcile.py:90-97`](../scripts/impact_reconcile.py#L90-L97)） | 撤销 |
| `predicted_keys` 靠 `written_at` 保证「实现前写入」 | `impact.json` 无该字段；自声明可伪造（与 `RFC-20261111-02` §2 同结论） | 撤销 |
| 门总账写在 `shared/gates.md` §2.2 | `impact_reconcile` 在 **§2.1**（[`gates.md:57`](../shared/gates.md#L57)）；§2.2 从 `:76` 开始 | 修正 |
| A 批只改校验器枚举 | ADR 模板同源声明了旧枚举（[`templates/adr/template.md:6`](../templates/adr/template.md#L6)） | 模板同批 |
| `revisit_when` 字段 | 无消费者、无触发检查，只多一个 WARN | **删除** |
| README 加 LinearB / 美团 / DORA 二手数字 | 无一手链接与样本口径；公开面放不可复核数字与「不造假绿」承诺相反 | **删除** |
| —— | `atlas_check` 已点名 added/removed 键（[`atlas_check.py:616-624`](../scripts/atlas_check.py#L616-L624)）：缺的是**处置**，不是检测 | 改为 §3.3 |

---

## 1. 结论先行

| 外部机制 | 处置 | 落点 |
|---|---|---|
| `assess` 的 `kill` 必须书面留档 | **吸收**（复用 ADR，不造台账） | §3.1 |
| `converge` 的 append-only / 不重写规格纪律 | **吸收为契约**（偏差三岔口） | §3.2 |
| `unrequested`（加戏）作为一等偏差 | **不新增门**：Atlas 已有三处机器面，缺的是收口处置 | §3.3 |
| `converge` 的 Agent 自评比对 | 不吸收 | 判据自然语言、不可证伪 |
| 九步 SDD + 项目宪法 | 不吸收 | Atlas 先有防线后有流程 |
| `.specify/feature.json` 会话态 | 不吸收 | `.atlas/tasks/` 账本更严 |
| `tasks.md` append 补齐任务 | 不吸收 | 与 workflow 派工单重复 |
| `pass^k` | 观察项 | §8 |
| 与 git 解耦的全仓体检 | 观察项 | §8 |

**一句话**：值得吸收的只有两件半——「不做要留证」「偏差要归因」，外加把已有漂移信号接到收口处置上；其余要么已有，要么不该做成门。

---

## 2. 现状取证（修正后）

| # | 事实 | 锚点 |
|---|---|---|
| 1 | 越界检测到**文件级**为止，`miss`/`over` 只比路径 | [`impact_reconcile.py:117-122`](../scripts/impact_reconcile.py#L117-L122) |
| 2 | 键级增删已被算出来，但只在「结构漂移」门里 **WARN 点名**（最多 3 处 × 每侧 2 键），不判该不该加 | [`atlas_check.py:616-624`](../scripts/atlas_check.py#L616-L624) |
| 3 | `_drift.json` 是全局瞬时 marker，不可做任务归因；`added` 语义 = 不在既有事实表 | [`refresh_structure.py:801-813`](../scripts/refresh_structure.py#L801-L813) |
| 4 | 回填分型只有三行，**没有归因维度**，默认动作 = 改上游 | [`apply/reference.md:208-214`](../apply/reference.md#L208-L214) |
| 5 | ADR 状态枚举无 `rejected`；模板与校验器双源声明同一枚举 | [`validate_adr.py:39`](../validators/validate_adr.py#L39)、[`templates/adr/template.md:6`](../templates/adr/template.md#L6) |
| 6 | 未登记的 status 只 WARN，不 FAIL | [`validate_adr.py:147-150`](../validators/validate_adr.py#L147-L150) |

> 对 #5 的诚实修正：现在**可以**写 `status: rejected` 的 ADR 文件，只是被判非法并 WARN。缺口是「没有正式状态」，不是「无处留证」。

---

## 3. 方案

### 3.1 A 批：`rejected` ADR —— 让「不做」成为合法状态

**判据**

1. `validators/validate_adr.py` 的 `VALID_STATUSES` 增加 `rejected`；
2. `templates/adr/template.md` 第 6 行枚举同批同步（双源一致性）；
3. `status: rejected` 的 ADR，`Decision` 章节必须非空（写「为什么不引入」，不是「不引入什么」）；
4. `rejected` **不参与** `superseded` 链（现状只对 `superseded` 建图，不改）；
5. 不新增 `revisit_when` 字段：重议条件写进 `Consequences` 散文即可，无消费者不加键。

**适用边界**：架构 / 机制级否决进 ADR；纯产品范围否决进 PRD §6.3「不做清单」（[`templates/prd/global.md:96`](../templates/prd/global.md#L96)，本 RFC 不动 PRD 结构）。

**成本**：2 个文件各 1 处；1 条正控 + 1 枚变异钉。

---

### 3.2 B 批：偏差三岔口（纪律面，不计入「已吸收」）

现状把「补写 / 修订 / 收口 / 配置」一股脑交给 `backfill`，默认动作是改上游。v2 把三岔口定义在**偏差发现入口**，不塞进 §5.2 的分型表（后两行「需裁决」「退役/迁移」本就不是回填条目）：

| 归因 | 触发 | 动作 | 通道 |
|---|---|---|---|
| `spec_gap` | 上游规格对、实现漏了 | 产实现任务，**不写回上游** | `atlas workflow` |
| `spec_amend` | 实现多做的东西有价值，应转正 | 写回 PRD / E2E 并留 `来源: backfill` | `apply backfill` |
| `out_of_scope` | 实现多做的东西无价值 | 产移除任务，**不写回上游** | `atlas workflow` |

**如实登记**：本项**无机器门**（回填队列不是机器可读文件）。按 [`global-rules.md:146-147`](../shared/global-rules.md#L146-L147) 的先例，纪律面不假装是门，也不计入「已吸收」。升格条件 = 回填队列落成机器可读文件，届时归因成为可校验枚举。

**落点**：`apply/reference.md` §5.2 之前新增「偏差处置」小节；`shared/closeout.md` 人侧清单追加一问（步骤 6 已退役，编号追加在现有末位，不打乱 1–5、7–11）。

---

### 3.3 C 批（撤销新门）：把已有信号接到收口处置

**为什么不做键级预测对账**：

1. **锚不存在**：`_drift.json` 全局瞬时，任务级归因需要新增「apply 前置生成结构键快照 + 入 git + 时序锚 + 封条绑定哈希」四件套，成本远超它能多抓到的信息量；
2. **必然恒绿**：`predicted_keys` 由同一个 Agent 在规划期写，全部写上即恒绿；加时序锚又要动封条 schema（未知版本 FAIL 的既有语义），风险不成比例；
3. **语义被高估**：`added` 只表示「不在既有事实表」，不等于「规格没写」。真正的规格对账 Atlas 已有更硬的链：AC ⇄ 用例 ⇄ testid 双向集合 + AC 对齐门。结构键这一层做细，收益是「多知道几个新路由」，代价是一整套新机制。

**v2 只做两件零/低代码的事**：

1. 「结构漂移」门的 WARN 文案追加处置指引（**纯自然语言，不含任何 `--apply` / `--write` 命令**，符合 R1）：`请按偏差三岔口在收口逐条处置`；
2. `shared/closeout.md` 人侧清单同一问覆盖三处信号：本次 `结构漂移` 点名的新增键 / `testid` 多写 / AC 对齐偏差，是否都在本需求范围内，逐条给出归因。

这样不新增判定面、不新增账本、不产生「门却没判别力」的伪吸收。

---

## 4. 与四条刚性红线的对照（`RFC-20261119-03` §1.4）

| 红线 | 本 RFC 的落地 |
|---|---|
| R1 门禁不得输出可自动覆盖基线的指令 | 只改 WARN 文案为自然语言处置指引，无 `--apply` / `--write` / `--record` |
| R2 存量采纳禁止动态侵入 | 不新增任何执行目标代码的步骤 |
| R3 禁止全局放水账本 | 不引入白名单 / 忽略表；三岔口只能是处置，不能登记豁免 |
| R4 存量采纳 Java 优先 | 不涉及适配器 |

---

## 5. 改动面清单

- [x] **校验器**：`validators/validate_adr.py`（`rejected` 枚举 + `Decision` 非空分支）
- [x] **模板**：`templates/adr/template.md`（第 6 行枚举同步，双源一致）
- [x] **契约**：`apply/reference.md` §5.3「偏差三岔口」；`shared/closeout.md`（触发表 + 步骤 12 + 编号口径 1–5、7–12）
- [x] **编排文案**：`scripts/atlas_check.py`（结构漂移 WARN 文案追加处置指引，不改判定）
- [x] **测试**：`tests/test_validate_adr.py`（+3：rejected 正例 / rejected 空理由 / 模板枚举双源一致）
- [x] **文档**：`README.md` §八 收口清单补「步骤 12」一条
- [x] **门总账**：`shared/gates.md` §2.1 `validate_adr` 行同步（枚举 + Decision 非空 + 钉说明）
- [x] **装配/计数锚**：`atlas_check --fast` 与相关测试已核，无计数锚漂移

---

## 6. 验证

```bash
pytest tests/test_validate_adr.py          # 14 passed
pytest tests/test_atlas_check.py tests/test_install_selfcheck.py      # 85 passed
pytest tests/test_closeout_derive.py tests/test_canonical_consistency.py  # 34 passed
pytest tests/test_backfill_contract.py tests/test_validators.py       # 207 passed
python3 scripts/closeout_derive.py --diff-base HEAD                   # 步骤号引用自检通过
python3 scripts/atlas_check.py --fast                                 # OK
```

| 钉 | 摘掉什么 | 预期红 |
|---|---|---|
| M-A1 | `rejected` 判据分支 | `test_validate_adr_rejected_empty_decision_warns` 红 |
| M-A1 正控 | — | 既有 `proposed/accepted` 用例仍绿 |
| M-A2 | 模板枚举同步 | `test_adr_template_status_enum_synced` 红（新增一致性钉：模板枚举 == `VALID_STATUSES`） |

**M-A1 实跑记录**：基线 14 passed → 注入 `DECISION_REQUIRED_STATUSES={"accepted"}` → `1 failed, 13 passed`（唯一红 = `test_validate_adr_rejected_empty_decision_warns`，其余绿）→ 逐字节还原 → 14 passed。

---

## 7. 最强反方与证伪条件

**最强反方：删掉 C 批之后，这份 RFC 只剩「加一个枚举 + 加一段流程文字」，对「验收瓶颈」零贡献。**
成立。文章的核心论点是「AI 把写代码成本压到零，验收成了瓶颈」，而本 RFC 明确不碰验收产能。它否决的备选是「做键级预测对账门」——那个看起来更硬，但会在三处必然恒绿。

**证伪条件（可执行）**：A/B 批合入后，若 3 个月内没有任何一条 `rejected` ADR 或 `out_of_scope` 归因被真实使用（统计命令：`git log --diff-filter=A -- '*/adr/*.md' | xargs -I{} git show --stat {} | grep -c 'status: rejected'`，以及 closeout 中归因字段的非空计数），则判本 RFC 为「纸面吸收」，两项都应回退，不得计入收益。

**次要反方：三岔口是加词不加约束。** 成立，已在 §3.2 如实登记，不计入「已吸收」。

---

## 8. 观察项（不立项，留触发条件）

| 观察项 | 不立项理由 | 触发条件 |
|---|---|---|
| E2E 连跑 k 次（`pass^k`） | 文章数据是 Agent 组合可靠性，与用例抖动不是同一问题 | `atlas_eval` ledger 出现同一 case 绿→红回摆 ≥ 3 次 |
| 与 git 解耦的全仓「离规格多远」体检 | 存量仓历史偏差噪声未评估，易产出无法处置的长清单 | ≥ 2 个采纳仓反馈「不知道离规格多远」并给出具体场景 |
| 任务级结构键快照 + `predicted_keys` | 见 §3.3 三条否决理由；不是永远不做，是当前成本/收益不成立 | 结构漂移门的 added 键在真实收口里出现「漏处置」≥ 3 次，且每次都导致返工 |

---

## 9. 未决项

1. `shared/closeout.md` 追加问题的编号：现有步骤为 1–5、7–11（步骤 6 已退役），追加为末位新步，**不得插号**。
2. 若未来重启任务级结构键快照（§8 第三行），必须先解决封条 schema 新增字段的版本语义（未知 `schema_version` 即 FAIL），该项不在本 RFC 范围。
