# RFC-20261022-01 · 路由形判据下沉：把「脚本开车」从关口扩到流程面

> 提案编号：RFC-20261022-01
> 提案作者：@sunwenzhe（agent 起草）
> 关联状态：**已拍板（2026-10-22）**——批 1–3 落地中；M4′ / M5 顺延
> 影响范围：核心契约 (shared) | 环契约 (rings) | 校验器 (validators) | 脚本工具 (scripts)

> **来源**：2026-10-22 会话——Atlas × Trellis × ai-test-pipeline（外部技能仓）三方控制架构对比的结论：Atlas 已两次证明「会让脚本开车」（`scripts/release.py` 以 npm dist-tags + git tag 唯一真相源判号 + `--check` 干跑；`_support/pw_runner.py::probe_browser` 真跑探针三态，D124），欠的是**覆盖率**——把「判据可写成 0/1（路由形）却仍由契约正文要求模型照办」的条目系统下沉为机器判据。
> **评审轮记**：`proposals/REVIEW-2026-10-22-route-shaped-criteria.md`（两路并行评审：技术方案评审裁决「修后采纳」；事实核查 9 锚点 7 属实 2 部分属实；本稿已按全部 P0/P1 修订）。
> **拍板**：2026-10-22 维护者——只落批 1–3（M1/M2/M3）；M4′/M5 顺延；每批独立提交，不发版、不推远端。

---

## 1. 现象与取证 (The Problem & Evidence)

### 1.1 触发形态（抽象）

一类「判据是路由形（0/1 可判）、执行者却是模型自觉」的条目，分散在三份契约里。共性：**门册里要么不设机器判据、要么根本无门，病发全靠人眼**。已付事故成本的五处：

| # | 条目 | 现状 | 事故实证 |
|---|---|---|---|
| 1 | 走查单确认门的「锁」 | `shared/gates.md` §2.5 该行自记 `[语义]` + **不设机器判据**（gates.md:93）；但「走查节首有无 `> 已确认：<日期>` 行」是路由形 | 走查断链事故本体 = `RFC-20261015-01`；两道同名走查门靠人交叉指认 |
| 2 | 收口触发表（`shared/closeout.md` §1，含主表 + 补表） | 触发表是一张路由表（事件 → 必跑步骤），执行靠模型收口时「记得查表」 | closeout.md:3 开篇自证：**这份清单本身长期不存在**（canonical 全仓 grep = 0 命中，`3509 §B112`） |
| 3 | one-writer-per-file 写面仲裁 | `apply/reference.md` §5.1（:196）纯纪律；`validate_e2e_index` 只能**事后**抓不一致 | 契约原文自记「冲突时停下报告，不得抢占（实测第三次才守住，`3508 §55 一`）」，前两次静默互踩、代价返工 |
| 4 | backfill 生命周期与攒批 | `apply/reference.md` §5.2 四步生命周期（登记→裁决→执行→回流验证）+ 每批 ≤10 条，全在正文 | 无机器判：超批、跳裁决直接执行均无门可挡 |
| 5 | 需求级运行过程无账 | `atlas-apply.md` **每次覆写**（apply/reference.md:254），历史归 git；断点续跑只有 `adopt`（:29）/ `all`（:230）有（按产物存在），`apply <需求ID>` 失败即断 | 「只在对话里说过的结论，下一个会话看不到」（closeout.md:145 Guidance 自记）。**本条本期不修**（见 §2.1 M4 裁决），登记为已知态 |

### 1.2 客观证据（仓库实锚）

```text
shared/gates.md:93（§2.5 走查单确认门行）:
  「[语义] … 不设机器判据（人侧门；首跑咬实 G2 旁路面 = 2026-09-29 全局审查）」

shared/closeout.md:3:
  「这份清单本身长期不存在（canonical 全仓 grep = 0 命中，3509 §B112）⇒ 那些「人防」全部悬空」

apply/reference.md:196（§5.1）:
  「冲突时停下报告，不得抢占（实测第三次才守住，3508 §55 一）」

skills/atlas-release/SKILL.md:46-53（防跳号痛点）:
  并行会话预写 CHANGELOG 导致「CHANGELOG 标题 ≠ 实发」——release.py 判号收归脚本的直接动因
```

### 1.3 动机一句话

不是引入新范式，是把 Atlas 自己已验证的手法从「关口两点」扩到「流程面」；下沉后**正文只留语义**，模型自觉的需求面减半。

---

## 2. 决策与权衡 (The Decision & Trade-offs)

### 2.1 核心定案 (The Decision)

**筛选判据（一条）**：某条目同时满足 ① 判据可写成 0/1（路由形）；② 当前执行者是模型自觉或事后兜底 ⇒ 纳入下沉。**语义形条目一律不动**（三问门判定、影响面语义推导、设计评审对话——模型主场）。**附带两条硬约束**：
1. （评审 P0-2 引入）机器面必须有**天然发射位**（校验器 / 命令 / 生命周期钩子 / 已有写盘点），不允许「模型收口时顺手记一笔」形态的账——那是给自觉病换个池子。
2. （维护者 2026-10-22 质询引入，消融锚）**能力轴筛选**：纳入前先答「这件补偿的是模型四项能力（上下文窗口 / 速度 / 并发 / 输出长度）之一，还是实现模型无关性质？」——补偿能力的不进仓（模型一换就是纯负担，同 ai-test-pipeline `stallMs` 45 处硬编码教训）；实现性质的须在门册行登记「**摘除后坏法**」作为未来消融测试（`trellis ablate` 同思路）的锚。

**五件的消融定性**（摘掉后系统坏掉的方式，决定了它们随模型能力提升的去留）：

| 件 | 摘除后的坏法 | 性质 | 随模型增强 |
|---|---|---|---|
| M1 走查锁 | 「用户已确认」这一声明无人裁决——自证不可信 | 对账平面（声明 ⇔ 凭据） | **不可替代**；叙述越可信，对账越值钱 |
| M2 派生器 | ①漏查触发表（能力面，会随能力稀释）；②覆盖完整性无法验证（枚举面，不随能力消失——declaredTotal 原理） | 混合体 | **枚举面保留、提醒面递减**；定位从「防漏」滑向「枚举标准件」 |
| M3 原子锁 | 并发写互踩 | 并发正确性（物理问题） | **不可替代**（最纯；模型互相看不见对方） |
| M4′ 事件行 | 机器行为无机器记录 | 仪器（机器记机器） | 不可替代（但也最弱，可选） |
| M5 队列状态机 | 「人还没裁决就执行了」；超人工预算 | 守**人的**决定权与预算（≤10 = `3509 §100` 人工上限） | **不可替代且随能力增强更重要**——模型越强，越有能力和倾向「顺手做了」 |

**统一形态（四条铁规矩）**：
1. 宿主无关：纯 stdlib Python 子进程件，零沙箱依赖、零新第三方依赖；新校验器必须提供 `--root` 接口（`atlas_check.py:187` 以 `python <校验器>.py --root .` 调用）；
2. 走自己的元门：每件先在 `shared/gates.md` 注册（§2.1 每器一行 / 编排行），配坏输入必红测试 + M 系列变异钉 + 还原逐字节一致；
3. **计数与登记链同步（评审修订：判据⑥不是自动的，是「不改就红」的强制对账）**：凡动 `VALIDATORS` / 新增测试文件 / 新增自检 check，必须手动同步：`gates.md` §2.2「当前 9」计数串、§2.1 每器一行门行、§2.6「33 个测试文件」与逐文件「N 条」计数、§2.3「install.sh 自检 N 条 check 声明」、`DESIGN.md`「9 个校验器」计数与花括号清单（DESIGN.md:430）——全部被 `test_canonical_consistency.py` 各判据钉住；
4. **决策与否决词纪律**：每件落地随批落 `DESIGN.md` §12 决策行（自 D133 顺延）；含「被否：」的行触发 closeout.md:10-12 宣称 sweep + `test_canonical_consistency.py` 判据⑦黑名单登记；
5. **独立可退役 + 真收口留痕**：每件独立一批、独立发版；**每批验收必须含一次真收口用新件跑全程并留痕**（防「机制在、接线断」）。

**机制清单（评审后从五件收敛为「三件核心 + 一件可选轻件 + 一件顺延」）**：

**M1 走查锁机器面**（批 1）—— 新增 `validators/validate_walkthrough.py`
- **时空域（评审 P1-2）**：只扫 `.trellis/tasks/*/` 中 `task.json.status ∈ {planning, in_progress}` 的任务（已归档不扫——「重派生删行」的合法失效与老记录不挂永久红账）。
- 判据：在域内任务的 `atlas-apply.md` 三问门判定第 2 问 =「是」⇒ 受影响域级 PRD 走查节须有 `> 已确认：<日期>` 行；缺失/形态非法 ⇒ **FAIL** 指名域与文件。
- **四态出口（评审 P1-1）**：识别到三问小节但第 2 问**不可解析** ⇒ **WARN** 指名 + 要求人工核对（不可解析 ≠ 未走到，防「写歪措辞静默旁路」）；无 apply 记录 / 第 2 问 = 否 / 无需求卡修订形态（§3.2）⇒ **SKIP** 带原因（存量 adopt 不误伤）。
- 门册 §2.5 行改写为「部分机器化」：机器面 = 确认行存在性与形态；语义残留 = 走查内容对不对（归人）；**「不查什么」明写两条**：① 三问判定本身的语义越轨（把该答「是」的答成否）不设防——锁的是「写下的『是』与确认行的对账」，不是「是」的判定；② §3.2 第四形态（无需求卡修订）的走查面不在本门（由 closeout 宣称 sweep 承担）。
- 调度者 = `atlas_check`（纳入 `VALIDATORS`；判据⑥计数同步见铁规矩 3）。

**M2 收口派生器**（批 2）—— 新增 `scripts/closeout_derive.py`
- `closeout_derive --diff-base <ref>`：取 `git diff --name-only`，对 `closeout.md` §1 **两张表**（主表 + 补表；注意「≥2 次同类纠偏」与「用户点名复盘」是**同一行**）逐行匹配（**表是唯一真相源，派生器只解析不复制**），输出本轮必跑步骤清单到 **stdout**（不落派生文件面）：机器步骤标「自动」、人侧步骤标「人工 + 判据指针」；触发值含「1→2→5→7」箭头链语法。
- **告警宇宙收敛（评审 P0-1 极性修正）**：「未匹配面 WARN」只对 **atlas 自有对账面**（`shared/` `rings/` `validators/` `scripts/` `templates/` `patches/` `_support/` `tests/` `DESIGN.md`）生效——这些路径有 diff 却没命中触发行才是真异常；业务代码在派生范围外，**只计条数一行带过，不出声**（防狼来了把真信号训练成噪声）。
- 自带自检：① 触发表引用的步骤号必须存在于 §2（空号 ⇒ FAIL 指名，对齐「死指针」纪律）；② 输出首行固定「本清单不含语义触发行，正文自查」。
- **自我审计诚实登记（评审 P1-3）**：`closeout.md` 步骤 1 正文加「收口第一步 = closeout_derive（旧装配态无此命令 ⇒ 查表照旧）」；门册行「不查什么」明写「**没人逼模型跑派生器**——触发物仍是纪律，本器只把『查表』的成本降到零」。
- 收口流程本身不变：步骤照 `closeout.md` 执行，派生器只回答「本轮必跑哪几步」。

**M3 写面 claim 机器面**（批 3）—— 新增 `scripts/write_claim.py`
- **原子 claim 文件（评审 P1-4）**：每 claim 一个文件 `.atlas/runs/write-claims/<hash>.json`，`open(O_CREAT|O_EXCL)` 天然原子——并发 take 同一文件时后者直接失败退出非零，**不搞单 JSON 读改写**（那会把锁本身变成被并发打穿的伪锁）；`release` = 删文件；残留检查 = glob 目录。
- `write_claim take --file <路径> --task <ID>` / `write_claim release --file <路径>`；冲突 ⇒ 退出非零 + 指名在办任务——§5.1「冲突停下报告、不得抢占」从纪律变成命令拒绝；`apply/reference.md` §5.1 加一行钩子 + 降级路径（旧装配无此命令 ⇒ 纪律照旧）。
- 落点先例更正（评审）：保留先例是 **F18**（install.sh 白名单子目录清理保留 `.atlas/runs/`，CHANGELOG.md:794），非 F41；`.atlas/runs/` 已有 3 个消费者（`backend-ac-alignment.json` / `e2e-summary.json` / `last-check-error.log`），claims 为并置第 4 件，文件名不撞、目录清扫为逐文件 unlink 不整目录清。
- 陈旧 claim（收口未释放）⇒ `atlas_check` 新行 `写面残留` **WARN** 指名；`validate_e2e_index` 事后兜底**保留不撤**。
- **边界自认**：`.atlas/` 不入库为合法形态（F55）⇒ claims **不进 git 历史**、没有「历史归 git」兜底——claims 是纯运行态，不做事实。
- **M4 裁决（评审 P0-2）：原「需求级 journal + 投影」砍掉**——校验器无状态、事件「谁落账」无天然发射位，靠模型 append = 给自觉病换池子；且与「M3 claims 保持运行态」自洽，不再有台账搬家。替代：**M4′（可选轻件，半天）**——`atlas_check` 每轮跑完向 `.atlas/runs/check-events.jsonl` 追加一行 repo 级摘要（已有写 `e2e-summary.json` 同款先例，发射位天然）；「atlas-apply.md 接管为投影视图」维持未决观察项，升档条件写在契约行。

**M5 backfill 队列状态机**（**顺延为可选批 5**，评审 P2：事故复现率最低、对 M2 依赖最弱，预算紧则不伤主线）—— 新增 `scripts/backflow_queue.py`
- **不新增登记入口（评审 P1-5）**：`filed` 条目必须引用一行**已存在**的 `ATLAS-UPSTREAM.md` 登记（id = 该行锚；`queue add` 校验引用存在，空号 FAIL——与 M2 自检①同款）；**只存引用不存内容**（状态分层判据②）。
- 状态闭集：`filed → adjudicated → batched → applied → verified`（+ `rejected`/`split`）；未 `adjudicated` ⇒ `batch`/`mark-applied` 拒绝；`batch` **>10 条 ⇒ 拒绝并指名顺延**（`3509 §100` 机器化）。
- **消费者先立**：`applied 未 verified` ⇒ `atlas_check` WARN 指名（无此消费面则砍 `verified` 态）。

**落地顺序**：批 1 M1 → 批 2 M2 → 批 3 M3 →（可选批 4 M4′ / 批 5 M5）。任一件停做不影响已落件。

### 2.2 考虑过的备选方案及否定理由

> ⚠ 本节四条均为被否项——落地时按 closeout.md:10-12 触发表执行**否决词全仓 sweep**，并把否决词登记进 `test_canonical_consistency.py` 判据⑦黑名单。

* **备选 A**：整体换 dispatcher 巨内核（ai-test-pipeline 同款全脚本驱动）
  * *否定理由*：「认知技能 + 契约正文」是 Atlas 的宿主可移植性护城河；ai-test-pipeline 被执行器沙箱约束逼出「stage 内联拷贝 + 对拍测试」的结构性重复，是实证反面。本 RFC 只下沉路由形判据，驱动权仍在模型。
* **备选 B**：`atlas-apply.md` 直接改成机器生成的投影视图
  * *否定理由*：层次弄反——apply 记录里的「判定 + 依据」是语义面，机器只能接账面；且需求级账本无天然发射位（评审 P0-2），先落 M4′ 观察窗。
* **备选 C**：只补文档纪律（「收口前记得查表」「写共享文件前记得声明」）
  * *否定理由*：即现状——已被三次事故证伪（§1.1 表 2/3 行）。纪律的成本是每次收口重新支付，机制的成本是一次。
* **备选 D**：把「是否改变应然 UI」（三问第 2 问）也机器化，让走查锁脱离 apply 记录自判
  * *否定理由*：三问判定是语义（`apply/reference.md` §4.1 明文「不进机器门」）；机器只读 apply **已写下**的判定记录，替模型判语义 = 重蹈 D53/E16 regex 判句意覆辙。
* **备选 E（评审引入后否决）**：需求级 journal.jsonl 由模型在收口时 append 事件
  * *否定理由*：违反本 RFC 自己的筛选判据——「模型顺手记」= 自觉病的换池；且 apply 幂等增量模型下重跑即重推导，账本解决不了断点处半成品资产问题。降档为 M4′ repo 级事件行。

### 2.3 必须警惕的刺痛代价与兼容性影响

* **存量项目**：M1 对域外任务 / 无 apply 记录 / 第 2 问否 ⇒ SKIP 不 FAIL（不给存量造红门）；M2/M3 为新命令 + 运行态文件，无存量依赖。
* **降级路径的诚实表述（评审修订）**：契约与脚本同包同发（install.sh 整目录枚举同批装配），「有契约无命令」态现实中只在回灌断裂时出现；`bin/atlas.js` 对未知命令响亮退出 2（bin/atlas.js:312-316），非静默面。**不把安全性论证押在降级路径上**——各钩子行的主语义是「有命令则机器判」，降级只是兜底注记。
* **运行态不入 git**：`.atlas/` 不入库为合法形态（F55）⇒ claims / check-events 无「历史归 git」兜底；它们是运行态不是事实，不进 `closeout.md` 步骤 5 的回灌登记义务。
* **性能**：M2 每次收口一次 `git diff --name-only`；其余 O(1)；零新依赖。
* **两处新风险自认**：① M1 的时空域依赖 `task.json.status` 可读——Trellis 任务记录损坏（`workflow-state:task_error` 形态）⇒ 该任务 SKIP + 原因，响亮不假绿；② M2 触发表行匹配依赖 closeout.md 表结构稳定 ⇒ 派生器解析失败必须**FAIL 响亮**（不得退化为空清单静默通过）。

---

## 3. 改动面清单 (Affected Surface)

> 每件独立一批（独立提交 + 独立 beta）。**批内通用义务（评审补充）**：① DESIGN.md §12 决策行（D 号顺延）+ 否决词 sweep + 判据⑦黑名单登记；② 计数链手动同步（gates.md §2.2 当前 N / §2.1 每器一行 / §2.6 测试文件数与逐文件条数 / §2.3 自检 check 数 / DESIGN.md 校验器计数）；③ 装配：install.sh 自检 `check` 行 + `test_install_selfcheck` + `package.json.files` 核对（目录级拷贝通常自动覆盖，仍须核对）；④ **一次真收口用新件跑全程并留痕**。

**M1（批 1）**
- [ ] 契约：`shared/gates.md` §2.5 走查单确认门行改写（部分机器化 + 四态出口 + 两条盲区）+ §2.1 新增 validate_walkthrough 行；`apply/reference.md` §3.1 环间人工门加机器面指针
- [ ] 代码：`validators/validate_walkthrough.py`（`--root` 接口；纳入 `scripts/atlas_check.py` 的 `VALIDATORS`）
- [ ] 测试防线：`tests/test_validate_walkthrough.py`（正控：已确认放行；坏输入：判定为是但无确认行 ⇒ FAIL、确认行形态非法 ⇒ FAIL、三问小节在但第 2 问不可解析 ⇒ WARN、无 apply 记录 ⇒ SKIP、第 2 问否 ⇒ SKIP、已归档任务不扫、重派生删行 ⇒ FAIL）+ M 系列变异钉（摘存在性判据 ⇒ 红 / 摘 WARN 分支 ⇒ 红 / 摘时空域过滤 ⇒ 红）
- [ ] 计数链：gates.md §2.2「当前 9→10」+ DESIGN.md「9 个校验器」+ 花括号清单 + §2.6 文件计数

**M2（批 2）**
- [ ] 契约：`shared/closeout.md` §1 加派生器注记（表仍为唯一真相源）+ 步骤 1 加「收口第一步 = closeout_derive」；`shared/gates.md` 注册 closeout_derive 行（盲区列含「没人逼模型跑派生器」）
- [ ] 代码：`scripts/closeout_derive.py`（两表解析 / 箭头链语法 / 告警宇宙收敛 / 空号 FAIL / 解析失败 FAIL）
- [ ] 测试防线：`tests/test_closeout_derive.py`（各路径形触发行命中 / atlas 自有面未命中 ⇒ WARN 逐条 / 业务面只计条数 / 空号引用 ⇒ FAIL / 表结构解析失败 ⇒ FAIL / 语义行不出现在清单）+ 变异钉（摘告警宇宙收敛 ⇒ 红 / 摘空号校验 ⇒ 红）
- [ ] 计数链：§2.6 文件计数与逐文件条数

**M3（批 3）**
- [ ] 契约：`apply/reference.md` §5.1 加 claim 钩子行 + 降级注记；`shared/gates.md` 注册 `写面残留` WARN 行
- [ ] 代码：`scripts/write_claim.py`（原子 O_EXCL claim 文件）；`scripts/atlas_check.py` 加 `写面残留` 行
- [ ] 测试防线：`tests/test_write_claim.py`（take/release 幂等 / 并发 take 同文件后者失败 / 冲突退出非零指名 / 陈旧残留 WARN / 逐文件清理不误删他件）+ 变异钉（摘 O_EXCL ⇒ 红 / 摘残留 glob ⇒ 红）
- [ ] 计数链：§2.3 自检 check 数 + §2.6

**M4′（可选批 4，半天）**
- [ ] 代码：`scripts/atlas_check.py` 末尾追加 `.atlas/runs/check-events.jsonl` 一行（repo 级摘要：时间戳 / 退出码 / FAIL 行名集）
- [ ] 测试防线：`tests/test_atlas_check.py` 追加钉（追加幂等单行 / 全绿也记）+ 变异钉
- [ ] 契约：`shared/gates.md` E2E 真跑行旁注或 §2.6 行注记（消费面 = 巡检取数，登记观察窗）

**M5（可选批 5，顺延）**
- [ ] 契约：`apply/reference.md` §5.2 加队列钩子；`shared/gates.md` 注册 backflow_queue 行（含「applied 未 verified ⇒ WARN」消费面）
- [ ] 代码：`scripts/backflow_queue.py`（引用存在性校验 / 状态闭集 / >10 拒绝 / 未裁决拒绝执行 / 只存引用）
- [ ] 测试防线：`tests/test_backflow_queue.py` + 变异钉
- [ ] 计数链：同通用义务

---

## 4. 验证与测试结果 (Verification)

> 每批提交前本地必须全绿；本节随各批落地回填实测数字。

```bash
pytest tests/test_<本批新件>.py        # 批内新测试
pytest tests/                          # 出厂全量（必须全绿）
python3 scripts/atlas_check.py --fast  # 快速自检
python3 tests/test_install_selfcheck.py         # 装配面自检（源包态）
rm -rf /tmp/probe && mkdir -p /tmp/probe && bash install.sh --target /tmp/probe --force  # 空目录探针
```

* **测试结果（批 1 / M1，2026-10-23）**：`tests/test_validate_walkthrough.py` **16 passed**；出厂全量 `586 passed, 4 skipped`；`atlas_check --fast` 源包态 exit 0（该态校验器行为 `SKIP`：无 `.atlas/validators`）；空目录探针 `bash install.sh --target /tmp/probe --force` exit 0，装配自检 51 条引用全部可达（含新 `check` 行）。**真收口留痕**：装到 `/tmp/probe` 后以 `planning` 任务夹具跑 `validate_walkthrough` —— 确认行在 ⇒ `PASS`；摘掉确认行 ⇒ `FAIL`（exit 1）指名 `demo-prd.md`；还原 ⇒ `PASS`；`atlas_check` 行显示 `ok validate_walkthrough`（接线成立）。变异 **M138/M139/M140** 四段协议全绿、报告含注入 diff（`/tmp/atlas-mutation/m1/`）。
* **自检结论（批 1）**：新增 `VALIDATORS` 第 10 项；`gates.md` §2.2「当前 10」/ §2.6「34 个测试文件」/ §2.3「50 条 check」/ `DESIGN.md`「10 个校验器」+ 花括号清单同步，`test_canonical_consistency.py` 9 passed。
