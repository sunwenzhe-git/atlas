# RFC-20261122-07: 执行层回收面硬化 + 测试纪律两件（BMad v6 / bmad-loop 机制综合吸收）

> 提案编号：RFC-20261122-07  
> 提案作者：Atlas 自动化管家  
> 关联状态：已定案 (Accepted) · **v2.1 落刀回填**（2026-11-22 首轮评审「修后再审」→ 复核轮「修后通过」→ 维护者拍板六项全按 AI 建议执行并同批落刀 P1+P2+P3；决策登记 `DESIGN.md` D209；全程记录见 `REVIEW-20261122-07`）  
> 影响范围：脚本工具 (scripts) | 共享内核 (_support) | 契约/文档 (shared) | 门登记 (gates.md) | proposals 纪律文本  
> 来源标的：`bmad-code-org/bmad-loop`（**MIT**，LICENSE 文件实证）+ `docs.bmad-method.org`（BMad Method v6，MIT）  
> 关联评估：2026-11-22 两轮外部评估（BMad v6 文档站 + bmad-loop 仓库深读），评估结论「机制抽取对象，不引依赖」为本 RFC 前提  
> 先例体裁：`RFC-20261119-03`（五开源机制综合吸收）——本 RFC 是同体裁的后续批，吸收件更少、面更收窄

---

## 0. 范围与来源定性（先读这个）

**来源定性**：bmad-loop 是「无 LLM 控制环」的确定性实现段编排器（纯 Python 挑票→派工→验证→评审→提交，完成判定只认 hook 事件/进程死亡），与 Atlas 执行层自立定案（`DESIGN.md` D203/D204：「编排/注入/持久化/检查皆可接管，写码由宿主 agent 执行」）哲学同源。Atlas 执行层骨架已落刀（`scripts/atlas_workflow.py` plan/dispatch/verify/finish/run），**本 RFC 不重立项执行层，只吸收其回收面已验证的机制去补已落刀面的缺口**。

**只吸收什么**：

| 标的 | 可吸收机制 | 明确不吸收（详见 §4） |
|---|---|---|
| bmad-loop | ①失败「扣/不扣预算」双轨分类学 + 有界尝试；②暂停原因封闭词表 + 退出码封闭分配；③deferred-work 台账登记形态（不含 sweep 分诊轮） | hook 完成判定（Atlas 确定性 CLI 入口同构）、8 态工单词表（撞 D204 三态锁定）、park git ref（Atlas 不自动重置）、worktree 隔离、mux 传输层、TUI、sweep LLM 分诊轮 |
| BMad v6 文档 | ④负断言消融规则（bmad-loop AGENTS.md 同款，BMad 文档站评审轮已确认其测试纪律）；⑤机制文档判据行 Tested-by 锚（`FEATURES.md` 契约：每条 property 锚测试文件） | 角色化 Agent、三层工单树、quick/thorough 评审分档（Atlas `atlas_review.py:248` round≥2 复审**派工单指令收窄**已覆盖本质）、PRD INV/OKR（`requirements/` 同锚刚落刀，冷却另案） |

**一句话结论**：吸收的是「失败分类的机器可读性」与「纪律的测试锚定」，不是编排器本体、不是新 validators、不是新状态机。

### 0.1 修订摘要（v1 → v2，逐条对应首轮评审）

| 首轮意见 | v2 处置 |
|---|---|
| [Blocker] `:332/:392` 整位 1→2 是对共享 die 位的错误处方（FinishError 承载 finish 门红，翻转既有测试钉） | §3.1.2 重写为**按 cause 分流**：`:332` 的 FinishError 先过词表——`freshness_fail`/`e2e_red`/`review_not_passed`/`scope_stale` 保持 1，environment/顺序类与 `:392` 归档 OSError 走 2；退出码表补「同位点不同 cause 不同码」注 |
| [Major] §1.3 pre_existing 穷举失实（漏 `_support/review_policy.py` 降级判据单源） | §1.3 改写：代码面 = `review_policy.py`（D129 降级判据单源）+ `cli_review_convert`/`review_closure`（合同消费）；**负断言「无聚合落账」经复核成立**，保留 |
| [Major] gates.md 登记行缺失（预算拒绝是机器拒绝，先例 = 新鲜度门 gates.md:59） | §3.1.1 显式声明按 `shared/gates.md` §2.1 机器门格式登记（判据/盲区/触发物/M 钉）；§6 第一期改动面补 `shared/gates.md`；N3 措辞澄清为仅约束 §3.2 纪律件 |
| [Major] cause 词表漏 `review.json` 存在但 status≠PASS 与 v4 内容封口红两条真实路径 | 词表补 `review_not_passed`（扣）、`scope_stale`（扣）、`budget_exceeded`（不扣·留痕）；补 fallback 规则（词表外一律 charged=true + `cause=unclassified`）+ 词表测试钉穷举值域 |
| [Major] Tested-by 消费器落 tests/ 零可达（受益者=采纳仓文档，tests/ 不进装配面） | §3.2.2 重写：消费器并入 `_support/workflow_verify.py` 的 `mechanism_doc_findings` WARN 族（复用 `discover_mechanism_docs`，随装配分发 ⇒ 采纳仓可达）；`test_map_anchors.py` 不动；`single-source.md:57` 登记行同步扩 |
| [Major] 证伪命令不具判别力（全局求和分不出单元/连续；glob 漏 archive；停止事件不可复算） | 预算拒绝追加 `{cause:"budget_exceeded", charged:false}` 留痕行（停止事件机器可查）；attempts 行 schema 增 `unit` 字段；§5.2 命令重写为 per-unit 聚合 + glob 补 `archive/*/*/attempts.jsonl`；`expected_if_false` 与判据逐字对应 |
| [Minor] §1.1「无记账」略过头（`scan_review_rounds` 已有当日轮次记账 + round-4 升级闸） | §1.1 补现状与真缺口收窄（跨日不设防 + verify/finish 层无预算无 cause）；§5.2 显式否决「数 findings 轮次当预算」备选并解释 2 与 round-4 两个上限的关系 |
| [Minor]「round≥2 自动收窄」措辞过强（实为派工单指令行） | §0/§4 改「派工单指令收窄」 |
| [Minor] §4.5 对 D156 触发 (b) 转述走样 | §4.5 改回 `gates.md` §2.5 原口径（契约判据且 diff 落 DR4 段级锚路径族 + `closeout_derive.py` 原始输出义务） |
| [Minor] 预算绕行面未声明（直跑 `atlas review --staged` 可绕开） | §3.1.1 声明：直跑 review 不在预算防线内，属人工责任面；不下沉预算到 review 入口（避免单写者违约） |
| [Minor] attempts.jsonl 半行/坏行 fail-soft 未定义 | §5.3 补：读侧跳过不可解析行并 WARN 出声；§5.2 命令同口径 |
| [Minor] 计数锚遗漏（自检声明实况 71 非 70；共享内核 27→28；refresh_count_anchors 在 tests/） | §6 改动面补 `docs/map/index.md`；§5.3 数字更正；验收命令路径更正为 `tests/refresh_count_anchors.py` |
| [Minor] `.atlas/config.yaml` 是新文件非「增键」（全仓无读写者；D205 ① 意向） | §5.3/§6 更正：第一期**新建**该文件 + 读取器 + fail-soft 缺省（无文件/无键 ⇒ 默认 2 不报错）；D205 引用改 ①；golden 相应扩 |
| [Minor] single-source 登记行落点混乱（§57 是 bullet 非 §1 表） | §6 第二期改为落 §1 表三列格式两行（attempts/deferred 各一行） |
| [Nit] deferred 状态值 `open` 偏离 D154 闭集 | §3.1.3 改为**复用 D154 闭集**：`开放｜已修·待复验｜已出库`；status 聚合计数「开放」 |
| [Nit] 130 来源、dispatch/plan 排除、契约注释面 | §3.1.2 加 130 来源注（信号死亡天然产生，不写 signal handler）；§3.1.1 加 dispatch/plan/archive 显式排除句；§6 加 `atlas_workflow.py:17/:311` 契约注释更新；「run 只读」改「run 不额外写」 |
| [Minor] 误扣率复核载体缺失 | §5.2 补：人工复核结论随 D206 代际账本记一行留痕，不加新面 |

### 0.2 复核轮处置（v2 → v2.1，判定「修后通过」）

| 复核轮意见 | v2.1 处置 |
|---|---|
| [Major] `:332` 分流漏 `no_review_report` 码位；「钉 290 不翻转」声明不成立（:290 钉的恰是 no_review_report 路径） | §3.1.2 补全映射：`no_review_report`→2、fallback `unclassified`→1 写死；钉声明改为「:356 不翻转、:290 随语义更新 rc==2」 |
| [Major] deferred 提取绑 finish 成功路径 ⇒ open pre_existing Critical/Major（阻断收口者）永远到不了台账，§1.3 动机与承载力错位 | §3.1.3 提取移到 finish 门判定**之前**（无论成败先落账，幂等兜底），打印区分「登记 N 条（其中阻断中 M 条）」 |
| [Minor] 判据乙 t 计数器混入 uncharged verify 行（staged_empty 反复重跑可造假退役信号） | §5.2 t 改 charged-only，判据文句同步 |
| [Minor] §5.2 命令括注「坏行跳过」与工件不符（列表推导无守卫） | 命令改逐行 try/except，声明与工件一致 |
| [Nit] §3.2.2「verify 分册」指代有误（test_atlas_verify 是 D150 另一子系统） | 径指 `tests/test_atlas_workflow.py` |
| [Nit] deferred 幂等对无 fingerprint finding 无回退键 | 补 `path+check名+detail 摘要哈希` 回退去重键 |
| [Nit] `budget_exceeded` 留痕行 `cmd` 取值未规定 | 写死 `'verify'` |
| （防呆备忘）复核请求中提及的「N6」为评审指令笔误，RFC 红线始终为 R1/R2/N1-N4 | 无改动 |

---

## 1. 现象与取证 (The Problem & Evidence)

### 1.1 workflow verify/finish 层无跨日尝试预算，宿主 agent 可无限撞门烧 token

`atlas workflow run` 的闭环（`scripts/atlas_workflow.py:471` cmd_run：plan→dispatch→verify→finish）在 verify 失败时终止并提示「修复后可重试 verify」。现状盘点（经评审复核收窄）：

- 审查层**已有**当日轮次记账与升级闸：`_support/workflow_finish.py:46-73` `scan_review_rounds` 每单元每次审查留 `findings/<unit>.r<N>.json`；`shared/independent-review.md` 轮次上限与升级复议——round ≥ 4 必须 escalation 否则拒绝放行；
- **真缺口**：①轮次记账按日分目录（`findings/<day>/`），**跨日不设防**——昨日 3 轮今日 3 轮，审查层视角永远是第 1 天；②轮次文件无 cause/charged 信息，分不清「实现没改好」与「环境坏了」；③verify/finish 层无任何 attempts/retry/budget 概念（评审负断言：七个 workflow 模块 grep 零命中，成立）。

后果：宿主 agent 陷入「改一点→verify→失败→再改」循环时，workflow 侧无从拦阻（每次 verify 都是一次全量审查，token 大头）。这是执行层自立拍板时 B 类痛点（「review 暂存区改动全靠手动说」）在编排面的残余。对照 D203 审修循环上限 2 轮（`DESIGN.md` D203 ③）——那是**审查器内部单次调用**的修审循环；workflow 层的重试无对应物。

### 1.2 失败原因是散文，退出码语义混用

- `scripts/atlas_workflow.py:279`：`die("暂存区为空：…", code=2)`——**前置不满足（可恢复暂停）**与用法错误共用 2；
- `scripts/atlas_workflow.py:380`：`die(f"任务 {args.unit} 尚未 completed，不能归档", code=1)`——状态顺序错误计入「判定失败」；
- `scripts/atlas_workflow.py:331-332`：`except FinishError as exc: return die(str(exc), code=1)`——**该位是共享 die 位**：finish 的门红（review 未过 / E2E red / 新鲜度门红，`_support/workflow_finish.py:184,447,451,457` 均以 FinishError 冒泡，既有测试钉 `tests/test_atlas_workflow.py:290,356` 断言 `rc==1`）与底层异常共用 1；
- `scripts/atlas_workflow.py:392`：归档 OSError 走 `die(str(exc), code=1)`——底层异常与门红共用 1。

消费者（宿主 agent、脚本）只能靠解析中文散文区分「该改代码」还是「该改流程顺序」还是「环境坏了」。对照物（bmad-loop）：暂停原因封闭词表（`parked:` / `no work produced:` / `usage limit:` / `hook channel silent:` 等七类，每类带固定清除动作）+ 退出码封闭分配（OK=0/FAILURE=1/USAGE=2/INTERRUPTED=130，余量不分配）。

### 1.3 审查发现的存量缺陷（pre_existing）无聚合落账通道

`shared/independent-review.md:77`：`pre_existing=true` 的 Critical「不阻断本次收口……**记录于存量台账**，不静默放行」。代码面现状（经评审复核更正）：`_support/review_policy.py:120,127,286-288`（D129 状态内核，pre_existing 降级判据**单源**：不阻断、状态下限抬为 WARN）+ `scripts/cli_review_convert.py` / `scripts/review_closure.py`（合同消费面）。**负断言成立：全仓没有任何组件把存量 finding 聚合落账**——实际去向 = 逐轮孤立的 `reviews/<date>/<unit>/review.json`，收口归档后即埋没。Atlas 既有台账 `duty-review/bugs.md` 是 Atlas 自身仓的 E2E 缺陷族账（巡检域，状态闭集 `开放｜已修·待复验｜已出库`），不接采纳仓 workflow 的审查产物。**「存量问题被发现了，然后呢」——答案目前是不存在。**

### 1.4 负断言消融规则未成文

bmad-loop AGENTS.md「Ablation rule」：*「对任何断言『X 被拒/缺席』的测试，删掉守卫代码确认测试 FAIL 后才可信——负断言对值缺席的所有原因都放行。」* Atlas 仓的测试纪律正本（`proposals/README.md` §2 强测试约束）有 M 钉子与 D156 留出验证制度，但**没有这条书写者自检规则**。它与 atlas-ablate 的认识论同源（D206：没见过红的门不是门），是同一原则在**单条断言尺度**的形态。历史踩坑佐证：`tests/test_no_framework_names.py` 不扫 `scripts/` 的盲区（`RFC-20261119-03` §3.3.4 被迫补专项断言）、i3 同秒竞态「单跑必绿≠无竞态」。

### 1.5 机制文档判据行无测试锚

机制叙事文档契约（`shared/single-source.md:22,57,58`，`RFC-20261122-04` 落刀）已做到：`mechanism-paths:` 锚「该机制叙述哪片代码」+ 死 glob WARN（发现面 `discover_mechanism_docs` 住 `_support/workflow_verify.py:424`，**随装配分发**，采纳仓可达）。但判据行本身（「verify 会 WARN 出声」「finish 会阻断」这类**行为陈述**）不带「哪条测试证明它」的锚——行为陈述与测试防线之间的对应关系只存在于评审记忆里。对照物：bmad-loop `docs/FEATURES.md` 契约——「每条 property 必须是当前代码成立的短可测陈述 + **Tested by 具体测试文件**」。Atlas 同族先例：`docs/map` 锚存活性门（`tests/test_map_anchors.py`，M151-M155）证明「文档行锚测试」的机器可查形态成立，但该测试章程是 docs/map 专属且 tests/ 不进装配面（`RFC-20261114-01`）——**消费器必须住在装配面内才够得到采纳仓文档**。

---

## 2. 刚性红线（继承 + 新增）

| # | 红线 | 落地判据 |
|---|---|---|
| R1（继承 `RFC-20261119-03`） | 门禁/工具输出禁止可自动覆盖基线的改写指令 | 本 RFC 所有新输出（attempts 记账、`paused_reason`、deferred 登记）全是只读观测与状态记录；无任何 `--write`/`--record`/`--force` 类提示 |
| R2（继承） | 严禁动态侵入 | attempts/deferred 全部消费已有机器产物（`review.json`、exit code、E2E 索引），不新增目标仓执行 |
| N1（新增） | **不得改 D204 任务三态状态机** | `todo/in_progress/completed` 锁定不动；预算与原因全部落**状态机外**的元数据面（`.atlas/tasks/<id>/attempts.jsonl`、`deferred.md`、结构化 die），不新增第四态，不把「预算超限」写成状态 |
| N2 | **预算超限的语义是「停下要求人工」，不是放行/跳过** | 超限 ⇒ 拒绝继续该单元 + 专用退出码 3 + 留痕行 + 人读指引；不存在「标失败继续」「自动降级 WARN」形态——否则预算机制本身就是新假绿面 |
| N3 | **纪律件零新 validators** | §3.2 两件落纪律文本与**既有 WARN 提示族扩展**（§3.2.2 复用 `mechanism_doc_findings` 族，不新增 `validators/`、不进 `atlas_check` VALIDATORS）；§3.1.1 预算门属 workflow 侧机器拒绝行为，按 `shared/gates.md` §2.1 机器门格式登记（先例：结构事实新鲜度门，gates.md:59），与 N3 不冲突；若维护者认定预算不构成门须显式记录排除理由 |
| N4 | MIT 来源引用规范 | 机制级转写（词表、形态、判据），不逐字搬运实现；来源仓库与许可在各节注明（MIT 与 Apache-2.0 单向兼容，无 Trellis 式干净室义务，但 Atlas 惯例保持实现自有） |

---

## 3. 方案

### 3.1 支柱一：workflow 回收面三件（喂 D204 `atlas workflow`）

#### 3.1.1 失败双轨分类学 + 有界尝试

**词表（封闭，双轨）**——新增单源模块 `_support/workflow_causes.py`：

| cause | 轨 | 语义 | 判定来源 |
|---|---|---|---|
| `blocking_critical` | 扣 | 审查报告存在未关闭阻断项（实现侧需改代码） | verify 调 review 返回 FAIL（`review.json` status=FAIL） |
| `verify_command_failed` | 扣 | `--check-cmd` 确定性检查非 0（D203 ③ 同轨） | check 退出码 |
| `review_not_passed` | 扣 | finish 发现报告存在但 status ≠ PASS（收口需 PASS，WARN/FAIL 均阻断，`workflow_finish.py:184`） | finish 读报告 |
| `scope_stale` | 扣 | v4 内容封口红（实审文件内容已变/审查产物误入暂存面，`workflow_finish.py:93-150` `_scope_matches`） | finish 封口门 |
| `freshness_fail` | 扣 | finish 结构事实新鲜度门红（`RFC-20261122-05`） | finish 门判定 |
| `e2e_red` | 扣 | finish 的 E2E 结论 `red`（`patches/project-wiring/agent-pointer.md:17` 口径） | E2E 索引状态列 |
| `staged_empty` | 不扣 | 前置态：实现未暂存 | 现有判定（`atlas_workflow.py:279`） |
| `no_task_card` | 不扣 | 对账本外任务收口/派发 | `atlas_workflow.py:323` |
| `state_transition` | 不扣 | 流程顺序错（未 completed 先归档等） | `atlas_workflow.py:380` |
| `no_review_report` | 不扣 | 先收口后审查的顺序错 | `workflow_finish.py:167` |
| `environment` | 不扣 | 底层异常（git 不可用等 OSError/exception 路径） | `atlas_workflow.py:332,392` 异常分支 |
| `budget_exceeded` | 不扣·**留痕** | 预算超限拒绝事件本身（不计数、只留痕，供证伪条件复算） | 预算检查拒绝路径 |
| （fallback）`unclassified` | 扣 | 词表外路径一律 `charged=true` + `cause=unclassified`（保守默认：判不清按真失败计，宁可误拦不可误放） | die 结构化变体兜底分支 |

**记账与上限**：

- 承载：`.atlas/tasks/<id>/attempts.jsonl`（append-only，行 schema `{ts, unit, cmd, cause, charged}`——**行内自带 unit 字段**，归档后 `.atlas/tasks/archive/<YYYY-MM>/<id>/attempts.jsonl` 仍可按 unit 聚合；随任务卡归档保留历史）；
- **单写者**：只有 `workflow verify` / `workflow finish` 命令写（`cmd_verify` / `cmd_finish` 失败路径追加；预算拒绝路径追加 `budget_exceeded` 留痕行）；`workflow run` 调用 verify/finish 产生的写入属这两个命令的写入，run 本身**不额外写**；`status` 只读；
- **显式排除**：`plan` / `dispatch` / `archive` 的失败不记 attempts、不占预算、无 `paused_reason`（`atlas_workflow.py:185,188,190,194` 等派发顺序类 die 全属 uncharged 类，退出码归 2，与新表自洽）；
- 预算：`charged` 计数 ≥ `workflow.max_verify_attempts` ⇒ `verify`/`run` 拒绝继续该单元：退出码 3（见 3.1.2）+ 追加 `budget_exceeded` 留痕行（`cmd` 写死 `'verify'`）+ 人读指引「预算超限，人工判断后再试或调整上限」；
- **绕行面声明**：宿主 agent 直跑 `atlas review --staged` 可绕开预算（同量 token 燃烧）——**不在防线内，属人工责任面**（D203 触发面本就是纪律行形态）；不把预算检查下沉到 review 入口（会造成第二个写者，违反单写者纪律）；
- `uncharged` 永不计数（环境/顺序错不是实现的错，扣预算会逼 agent 硬闯）；
- **读侧 fail-soft**：跳过不可解析行（半行 JSON 等）并 WARN 出声一行，不让坏行炸掉整个读取；
- **不自动重试、不自动重置工作树**（Atlas 形态是宿主 agent 显式重跑；bmad-loop 的 park-git-ref 机制因 Atlas 从不自动 reset 而无需求，见 §4）。

**门登记义务**：本条「charged ≥ 上限 ⇒ 拒绝 + 退出码 3」是 workflow 侧机器拒绝行为，按 `shared/gates.md` §2.1 机器门格式登记一行（判据 / 显式盲区：uncharged 误分类不可机判，靠词表测试钉穷举 + 人工复核兜底 / 触发物 / 假绿测试 M 钉号）。先例：结构事实新鲜度门同位登记（gates.md:59）。§3.2.1 自我适用的 M 变异钉登记进同列。

#### 3.1.2 暂停原因封闭词表 + 退出码语义化（按 cause 分流）

- `die()` 增加结构化变体：`die(msg, code=…, cause=…)`；`verify` / `finish` / `status` 的 `--json` 输出新增 `paused_reason`（取 3.1.1 词表），人读文案不变（用户可见面零变化）；
- **退出码封闭分配**：0=OK / 1=判定失败·门红 / 2=用法或前置不满足 / 3=预算超限暂停 / 130=中断（SIGINT 信号死亡天然产生，**无 die() 路径发出 130**；SIGTERM=143 落「131+ 不分配」区；不写 signal handler）；4–129 与 131+ 不分配；
- **同位点、不同 cause、不同码**（首轮 Blocker 修正，替代 v1 的「整位改判」处方）：
  - `atlas_workflow.py:331-332` 的 `FinishError` 分支：先过词表判定——`review_not_passed` / `scope_stale` / `freshness_fail` / `e2e_red` / fallback `unclassified` ⇒ **1**（门红与保守兜底按判定失败计）；`no_review_report` / `no_task_card` / `state_transition` / `environment` ⇒ **2**（前置/顺序/环境，非门红）。既有测试钉处置：`test_atlas_workflow.py:356`（e2e_red）不翻转；`:290`（no_review_report）随语义更新为 rc==2（顺序错归 2，与 :380 同治；v2 曾声明「290 不翻转」，经复核证伪，以本句为准）；
  - `atlas_workflow.py:380`（未 completed 先归档）：1 → 2（顺序错非门红）；
  - `atlas_workflow.py:392`（归档 OSError）：1 → 2（异常非门红）；
- 兼容性取证（已核）：`patches/project-wiring/agent-pointer.md` 无按退出码分支的消费行，`bin/atlas.js:406-414` 纯透传，现有消费者全部只判 `rc != 0`；
- **契约注释面同步**：`atlas_workflow.py:17` 模块 docstring 退出码契约、`:311`「本命令的退出码契约 = 0/1/2」注释随 3/130 更新；
- 分配表写死在 `_support/workflow_causes.py` 并带测试钉子（防未来随手 `code=4`）。

#### 3.1.3 审查存量缺陷台账通道（deferred 登记，最小面）

- **写者与时机**：`_support/workflow_finish.py`（finish 已是 `review.json` 的读取点，维持单写者纪律）：提取 `checks[]` 中 `pre_existing=true` 且 disposition 未关闭的 findings，**在 finish 门判定之前执行**——无论收口成败先落账（open pre_existing Critical/Major 会以 WARN 下限阻断收口，若绑定成功路径则头条病案永远到不了台账；幂等去重兜底复跑重复）；追加到 `.atlas/tasks/<unit>/deferred.md`；打印行区分「登记 N 条（其中阻断中 M 条）」；
- **条目形态**（对齐 D154 bug 台账机器字段纪律，**状态复用 D154 闭集**）：`- DW-<n> 〔日期(必填)｜开放｜族(仅记录)｜证(fingerprint + review 轮次)〕<一句话> (file:line)`；状态值域 = `开放｜已修·待复验｜已出库`（与 `duty-review/bugs.md` 制式段同源，不自造闭集）；
- **幂等**：按 fingerprint 去重——同一 fingerprint 已登记则跳过（复审重报不重复登记）；fingerprint 在审查契约中为可选字段（v2 推荐），无 fingerprint 的 finding 回退去重键 = `path + check 名 + detail 摘要哈希`；
- **可见化**：`workflow status` 聚合显示各卡「开放」deferred 计数（含已归档卡，归档路径已知可读）；`workflow finish` 收口后打印「本单元登记存量缺陷 N 条 → deferred.md」；
- **不做**（有意收窄）：不做 bmad-loop sweep 的 LLM 分诊轮、不做自动修复、不做跨单元聚合台账（`.atlas/` 顶层不加新目录，不动 `layout.md` 契约）——登记与可见化是本 RFC 全部语义，分诊/消费另案（对齐 `duty-review` 巡检消费面节奏）。

### 3.2 支柱二：测试纪律两件

#### 3.2.1 负断言消融规则成文

- **落点**：`proposals/README.md` §2「强测试约束」追加一条（Atlas 仓自身测试纪律正本；不随装配分发——这是开发纪律不是采纳仓契约）；
- **文本（机制级转写）**：「任何断言『X 被拒/缺席/不出声』的测试，**必须先摘除守卫代码实跑确认变红**后才可信——负断言对『值缺席的所有原因』都放行；摘不红的负断言只证明『该输入路径没走到』，不证明『守卫在』」（出处：bmad-loop AGENTS.md Ablation rule；同认识论先例 = D206 消融口径）；
- 本 RFC 的预算/词表测试**自我适用**：`test_…attempts` 系负断言用例必须附「摘除记账调用 ⇒ 测试红」的变异证据，M 钉号登记进 `shared/gates.md` 假绿测试列（与预算门同批）。

#### 3.2.2 机制文档判据行 Tested-by 锚（可选但存活，棘轮起点；消费器住装配面）

- **形态**：机制叙事文档（`docs/architecture/<机制>.md`，frontmatter `mechanism-paths:`）的判据/行为行可带行尾锚 `〔测:tests/test_x.py::test_y〕`；
- **消费器（本轮 Major 修正）**：并入 `_support/workflow_verify.py` 的 `mechanism_doc_findings` **WARN 提示族**（该族即 `single-source.md:57` 登记的机制文档机器面，`discover_mechanism_docs` 已在该文件，**随装配分发 ⇒ 采纳仓可达**）：扫描各篇已写锚的行，锚指向的测试文件或用例 id 不存在 ⇒ WARN 出声（死锚检测，只在已写锚的行上生效）；`tests/test_map_anchors.py` 不动（其章程是 docs/map 专属，不扩）；
- **契约同步**：`shared/single-source.md:57` 登记行同步扩（提示族内容增「死锚 WARN」一项），`§1` 机制文档行不动；写法纪律（§58 四条）增补第五条：判据/行为行**建议**带 Tested-by 锚，不强制；
- **棘轮口径**：新增/修订的机制文档行建议带锚（随装配分发的写法纪律承载），存量不回溯（Atlas 自身仓目前 `docs/architecture/` 尚无实例，形态先立正本，采纳仓第一篇机制文档起受益）；
- **升格条件**（防过度设计）：若两代任务跑实证「无锚行导致行为陈述漂移未被发现」的真实案例 ≥2，再议「新增行必带」棘轮——先可选后强制，与 `single-source.md:57` 的 WARN 升格条件同节奏；
- **消费器测试**：落在 `tests/test_atlas_workflow.py`（`mechanism_doc_findings` 既有测试所在文件；`tests/test_atlas_verify.py` 属 D150 验收执行器另一子系统，不相干），不新增测试文件（防计数棘轮链四处咬红）。

---

## 4. 明确不吸收面（防重复立项对照表）

| 不吸收项 | 理由 |
|---|---|
| hook 完成判定（只认会话 hook 事件/进程死亡） | Atlas 的单元完成判定**已经是** trust-nothing 形态：完成 = `review.json` 机器产物 + 校验器复算（`workflow_finish.py`），从不存在「认模型文本」的路径；bmad-loop 需要它是因为它监视 tmux 会话，Atlas 不监视会话 |
| 8 态工单词表（draft/ready-for-dev/in-review/built/done/blocked/dropped…） | 撞 D204 三态锁定（`DESIGN.md` D204 ②）；暂停语义由 N1 的**状态机外元数据**（cause 词表 + attempts）承载，不加态 |
| park git ref（重置失败尝试前保全现场） | Atlas 从不自动重置工作树（verify 失败实现留在暂存区由人处置），「重置前保全」无触发场景 |
| worktree 隔离 / max_parallel | Atlas 单宿主会话顺序派工（D204 DAG 按依赖满足派发），无并行单元合回形态 |
| fresh-context 评审、终审确定性 | 已落地（D203/D204：宿主子代理 Fresh Context 硬约束、生成者≠审查者、merge-ready 确定性门），无增量 |
| mux/psmux 传输层、TUI 仪表盘 | 外部进程驱动 CLI 形态，Atlas 走宿主内确定性 CLI 入口；TUI 的「只经文件观察引擎」解耦原则已被 `workflow status` 只读面覆盖 |
| BMAD 数据模型（sprint-status.yaml / stories.yaml / tickets.py） | 深耦合 BMAD 项目结构；Atlas 任务账本 `.atlas/tasks` 已定案（D205），同一锚别动两次 |
| quick/thorough 评审分档 | Atlas `atlas_review.py:248` 已有分档本质：round≥2 复审**派工单指令**只审上轮 findings 涉及文件及其直接引用（fresh-context 子代理指令收窄，非机器强制——收窄结论仍成立：单元审查是收口唯一一道审查，无「循环内全量反复审」的浪费形态可省） |
| sweep LLM 分诊轮（deferred 定期分诊会话） | 无人值守形态不存在 + 防自动化假绿红线（`RFC-20261119-03` R1 同源）；分诊归巡检/人工节奏 |
| 角色化 Agent、三层工单树、问人式 checkpoint | 2026-11-22 BMad v6 评估轮已判不吸收（撞「方法默认生效零口令」定案与 RFC-20261122-03 正本） |
| PRD INV/OKR 二分、OQ 责任人字段 | `requirements/` 同锚刚落刀（RFC-20261122-03），冷却另案（见 §8-④） |

---

## 5. 决策与权衡

### 5.1 核心定案

1. **失败双轨制**：扣预算=「实现侧需改代码才能过」的失败；不扣=「前置/环境/顺序/留痕」。拦单元撞门打转，同时不惩罚环境抖动。代价：cause 判定必须保守（词表外与判不清一律 `unclassified` 扣，见 3.1.1 fallback）。
2. **状态机外元数据**：一切新语义落 `attempts.jsonl` / `deferred.md` / `paused_reason` / 退出码，D204 三态与任务卡契约（`validate_task_card`，D208）零改动。代价：状态面与元数据面分离，`status` 需要聚合展示。
3. **deferred 只登记不分诊**：填「存量缺陷发现后埋没」的真缺口，不引入无人值守分诊形态。代价：登记不等于被修——可见化是唯一出口，依赖人/巡检消费。
4. **纪律先于 validators**：负断言规则走文本；Tested-by 锚走既有 WARN 提示族扩展；预算门走 gates.md §2.1 登记但不进 `atlas_check` VALIDATORS。代价：无 atlas_check 级硬度，靠写作者自觉 + 评审拦截 + gates.md 登记；升格有明确条件（§3.2.2）。

### 5.2 最强反方与证伪条件

**最强反方论证**：attempts 预算会制造新型假绿——agent 被「预算超限」拦住后，有三条绕路：①调高 `max_verify_attempts`；②把 `blocking_critical` 谎报成 `environment`（uncharged 不计数）；③**绕开 workflow 直跑 `atlas review --staged`**（同量 token，预算看不见）。且 cause 判定若大量误扣（环境问题被计成扣预算失败），正常工作流会被误拦。该反方同时否决了备选「不加预算（现状）」——现状的打转烧 token 是已观测痛点，不作为选项。

**对三条绕路的处置**：①改配置 = 人工显式决策，本身留痕于 config，可接受（三类才问人的显式出口）；②谎报 cause = 词表由 workflow 代码内部判定（非 agent 填写），agent 无注入面；fallback `unclassified` 保守扣进一步压缩谎报收益；③直跑 review = **显式声明不在防线内、属人工责任面**（预算是 workflow 编排面的拦阻，不是全仓 token 警察；下沉 review 入口会破坏单写者纪律，不做）。

**证伪条件（可执行，`discriminating_check` 形态）**：

- **打转拦截有效性**（留痕依赖：预算拒绝路径追加 `budget_exceeded` 留痕行，§3.1.1）——两个真实任务跑窗口后：
  - 判据甲「停止事件发生」：存在单元 charged ≥ 上限且留痕行存在 ⇒ 机制在被触发，有效；
  - 判据乙「无打转则无价值」：观测窗口内**无任何** `budget_exceeded` 留痕行，**且**存在单元 charged 的 verify 行 ≥ 4（charged 打转发生但预算没拦住；混入 uncharged 会给 staged_empty 反复重跑留出假退役信号，故 charged-only）⇒ 判定预算形同虚设，退役该机制（复归 D206 减法判据）；
  - `discriminating_check: {command: "python3 - <<'PY'
import json, glob
from collections import Counter
rows = []
for f in glob.glob('.atlas/tasks/*/attempts.jsonl') + glob.glob('.atlas/tasks/archive/*/*/attempts.jsonl'):
    for l in open(f):
        try:
            rows.append(json.loads(l))
        except Exception:
            pass
c = Counter(r['unit'] for r in rows if r.get('charged'))
t = Counter(r['unit'] for r in rows if r.get('cmd') == 'verify' and r.get('charged'))
s = [r for r in rows if r.get('cause') == 'budget_exceeded']
print('stop_events:', len(s), 'max_charged:', max(c.values(), default=0), 'units_ge4_charged_verify:', sorted(u for u, n in t.items() if n >= 4))
PY", expected_if_false: "stop_events>0 ⇒ 预算拦过，有效；stop_events==0 且 units_ge4_charged_verify==[] ⇒ 从未打转，机制未经历考验，挂观察不退役；stop_events==0 且 units_ge4_charged_verify 非空 ⇒ 证伪，退役"}`（命令内 try/except 逐行跳过坏行，与读侧 fail-soft 同口径）
- **误扣率**：上线后两个真实任务跑窗口内对 `charged` 条目人工复核，结论**随 D206 代际账本记一行留痕**（不加新登记面）；`charged` 中被判定「实为环境/前置态」比例 > 30% ⇒ 词表失真，回退为只记账不出声（退化为观测面）。

**其他备选（有取舍价值者）**：

- 备选 A「cause 词表进 review.json 合同（改 `independent-review.md`）」——否：合同面改动触发 §4.5 全套留出验证与 `review_policy`/`cli_review_convert`/`review_closure` 连锁，收益只是人读更顺；词表收在 workflow 层，合同零改动。
- 备选 B「deferred 聚合进 `duty-review/bugs.md` 族账」——否：那是 Atlas 自身仓巡检域，采纳仓 workflow 产物跨仓写入破坏单仓自治；落任务卡目录随卡归档，聚合靠 status。
- 备选 C「直接数 `findings/<unit>.r<N>.json` 轮次文件当预算（不加 attempts 面）」——否：轮次目录按日分桶 ⇒ 跨日重置不设防（恰是待修缺口）；混入直跑 `atlas review` 的轮次（非 workflow 语境）；无 cause/charged 信息。attempts.jsonl 是跨日、带 cause、单写者的最小面。**与既有 round-4 升级闸的关系**：两个不同环的上限——round-4 管「单次调用内审查轮次升级」（当日、审查层），`max_verify_attempts=2` 管「单元级重试预算」（跨日、workflow 层），互不替代。

### 5.3 刺痛代价与兼容性影响

- **golden 装配基线**：`scripts/atlas_workflow.py`、`_support/workflow_*.py` 在装配面内（`RFC-20261119-03` §9.2 golden diff 实证）⇒ 落刀批必须重录 golden（worktree 对已提交树录，防烤入并行 WIP）；第一期新增 `.atlas/config.yaml` 装配模板与 `_support/workflow_causes.py` ⇒ golden 面相应扩；
- **`.atlas/config.yaml` 是新文件**：全仓现无任何代码读写 `.atlas/config.yaml`（现存根 `atlas.config.yaml` 是另一物，`_support/layout.py:29`；`shared/solution.md:166` 为退役期遗物）；D205 ① 只立「工作流参数住 .atlas/config.yaml」意向。第一期实际动作 = **新建**该文件（装配模板产出）+ `workflow_causes.py` 读取器 + fail-soft 缺省（**旧装配无此文件或无键 ⇒ 默认 2，不报错**）；
- **退出码消费者**：`bin/atlas.js:406-414` 纯透传、`agent-pointer.md` 无按码分支（已核）——`:380`/`:392` 两处 1→2 与 `:332` 按 cause 分流理论上安全，实施批仍 grep 全仓 workflow 调用点复核；
- **计数锚快照**：`docs/map/index.md` 〔数:自检声明=71〕、〔数:共享内核=27→28〕（新增 `workflow_causes.py`）、tests 计数与最大单件——落刀批跑 `ledger_snapshot.py` 与 `tests/refresh_count_anchors.py` 刷新并核 dry-run；
- **存量任务卡**：无 attempts.jsonl / deferred.md 的旧卡按 0 计（fail-soft 读），不迁移不回填；坏行跳过 WARN；
- **执行耗时**：attempts/deferred 均为 O(1) 追加与 O(n) 状态聚合，无可感知开销；
- **长期维护**：新增单源模块 `_support/workflow_causes.py`（词表+退出码+记账，约 120 行）与 deferred 读写（`workflow_finish.py` 内约 60 行）+ `workflow_verify.py` 死锚 WARN（约 30 行）；生命周期到「执行层退役或 D206 消融判负」为止，退出形态=机制摘除+golden 重录，无死尸表。

---

## 6. 改动面清单与分期

### 第一期：workflow 回收面（§3.1.1 + §3.1.2，同批落刀）

| 文件 | 动作 |
|---|---|
| `_support/workflow_causes.py` | **新增**：cause 封闭词表（13 值域含 fallback/budget_exceeded）、双轨、退出码分配表、attempts 读写（fail-soft 读）、`die` 结构化变体、config 读取（`.atlas/config.yaml` fail-soft 缺省 2） |
| `scripts/atlas_workflow.py` | `cmd_verify`/`cmd_finish` 失败路径接记账；预算拒绝路径（退出码 3 + `budget_exceeded` 留痕行）；`cmd_status` 聚合 attempts（含归档）+ paused_reason；`:380`/`:392` 退出码 1→2；`:332` FinishError 按 cause 分流；`:17` docstring 与 `:311` 注释更新 |
| `_support/workflow_finish.py` | finish 失败路径接记账（`review_not_passed`/`scope_stale`/`freshness_fail`/`e2e_red`） |
| `install.py` + 装配模板 | **新建** `.atlas/config.yaml` 模板（含 `workflow.max_verify_attempts: 2` 注释示例）；自检声明计数同步 |
| `shared/gates.md` | §2.1 增预算门登记行（判据 / 盲区：uncharged 误分类不可机判 / 触发物 / M 钉号） |
| `tests/test_atlas_workflow.py` | 扩展：词表封闭性穷举钉、双轨计数、预算超限拒绝（**负断言附摘除变异证据**，M 钉进 gates.md）、退出码分配表钉、`:332` 分流两侧（门红/fallback 保持 1；`no_review_report`/`environment` 走 2，含 `:290` 钉随语义更新）、旧卡与坏行 fail-soft、config 缺省回退 |
| `docs/map/index.md` | 计数锚刷新（自检声明 / 共享内核 / tests 计数 / 最大单件，经 `scripts/ledger_snapshot.py --write` 与 `tests/refresh_count_anchors.py`） |
| `proposals/RFC-20261103-04-installer-golden/` | golden 重录（worktree 隔离、对已提交树；diff 限本批条目） |
| `DESIGN.md` | 新 D 行（号位落刀时计）：双轨分类学 + 退出码封闭 + 三态锁定 N1 声明 + 绕行面声明 |

### 第二期：deferred 台账通道（§3.1.3）

| 文件 | 动作 |
|---|---|
| `_support/workflow_finish.py` | deferred 提取/追加（fingerprint 幂等，D154 状态闭集）+ 收口后出声 |
| `scripts/atlas_workflow.py` | `cmd_status` 聚合「开放」deferred（含归档卡） |
| `tests/test_atlas_workflow.py` | 扩展：登记幂等（同 fingerprint 不重记）、D154 字段与状态闭集形态钉、归档后仍可聚合 |
| `shared/single-source.md` | §1 表增两行（三列格式 `| 信息 | 唯一真相源 | 派生视图 |`，对齐 :22 既有行）：attempts 记账一行、deferred 登记一行 |

### 第三期：测试纪律两件（§3.2，与第二期可并批）

| 文件 | 动作 |
|---|---|
| `proposals/README.md` | §2 追加负断言消融规则 |
| `shared/single-source.md` | §57 登记行扩「死锚 WARN」；§58 写法纪律增补第五条（Tested-by 锚建议形态） |
| `_support/workflow_verify.py` | `mechanism_doc_findings` WARN 族扩死锚检测（复用 `discover_mechanism_docs`，随装配分发） |
| `tests/test_atlas_workflow.py` | 扩展：死锚 WARN 出声/合法锚不误伤/未写锚行零出声 |

**每期共同验收**（按序）：定向测试全绿 → `pytest tests/` 全量绿 → `python3 scripts/atlas_check.py --fast` 无 FAIL → `python3 scripts/ledger_snapshot.py`（dry-run）与 `python3 tests/refresh_count_anchors.py`（dry-run）无漂移 → golden `harness.py --check` 绿（重录后）→ 临时装配项目端到端（改实现→verify→故意再 verify 触发预算→人工放行路径；直跑 review 绕行面行为确认）。

### §4.5 留出验证触发面评估

- 触发面核对 (a)：`bugs.md` 同根归纳无本 RFC 引子族（新增能力非缺陷修复）⇒ 不命中；
- 触发面核对 (b)：按 `shared/gates.md` §2.5 原口径——本 RFC 不改门/校验器/契约判据（`validate_task_card` 与 `review_policy` 零改动；预算门为新增 workflow 侧行为，gates.md 登记行不属「改判据」），`git diff --name-only` 预期不落 DR4 段级锚路径族；**落刀批必须粘贴 `git diff --name-only` 与 `scripts/closeout_derive.py` 路径族表对照的原始输出（不得只写「无命中」结论）**；
- 若评审复核认定第一期改动构成「契约判据面」（退出码语义被消费），则按 §4.5 补留出集——留出集候选：记账摘除后预算测试翻转（与 §3.2.1 变异证据同件，天然满足「判据输出翻转 + 变异增量杀伤」）。

---

## 7. 验证与测试结果

**三期已同批落刀（P2/P3 并批，2026-11-22）**，决策登记 `DESIGN.md` D209。评审轨迹：v1「修后再审」（1 Blocker + 6 Major）→ v2 全数处置 → 复核轮「修后通过」（残留 2 Major + 2 Minor 已于 v2.1 补全，判定「无须第三轮评审」）。

**已落地**：

- `_support/workflow_causes.py` 新增（词表 12 值域 + fallback / 双轨 / 退出码分配 0/1/2/3/130 / attempts 读写 fail-soft / config fail-soft 缺省 2）；
- `scripts/atlas_workflow.py`：verify 预算门（charged ≥ 上限 ⇒ rc3 + `budget_exceeded` 留痕行）+ rc≠0 记账（rc1 ⇒ `blocking_critical` 扣 / rc2 PENDING ⇒ `no_review_report` 不扣）+ `--json` 暂停面 `paused_reason`；finish 失败按 FinishError.cause 记账 + 分流退出码；status 人读 + `--json` 逐卡聚合 attempts（含坏行数）与 deferred 开放数；`:380`/`:392` 1→2；`:332` 按 cause 分流；docstring/`:311` 注释更新；
- `_support/workflow_finish.py`：FinishError 带 cause（审查门三分类 no_review_report/environment/review_not_passed/scope_stale；e2e_red / freshness_fail / state_transition / no_task_card / environment 各就位）；`extract_deferred_findings`（门判定之前、fingerprint 幂等 + 回退键、D154 闭集、阻断也落账并出声「登记 N 条（其中阻断中 M 条）」）；`deferred_open_count`；
- `_support/workflow_verify.py`：`_dead_anchor_findings` 并入 `mechanism_doc_findings` WARN 提示族（死锚 / 形态非法 / pending 篇仍判 / 无锚零出声；节点级不机器判）；
- `install.py`：`.atlas/config.yaml` create-if-missing 模板（--update 保留）+ c() 自检声明（71→72）；
- 契约面：`shared/gates.md` §2.1 预算门登记行 + §4.1 约束登记 C-13/C-14（M201/M202 非门钉的家）；`shared/single-source.md` §1 表两行（attempts/deferred）+ §57 死锚扩展 + §58 第五条；`proposals/README.md` §2 负断言消融规则。

**验证结果**：

| 检查 | 结果 |
|---|---|
| 定向 `pytest tests/test_atlas_workflow.py -q` | **85 passed**（新增 16 条 + 3 条语义钉更新：T-04/T-1 finish 无报告 1→2、T-31 归档 1→2；review_not_passed/e2e_red/freshness 门红钉 rc==1 全部保持） |
| 计数/契约套件（selfcheck / canonical / map_anchors / no_framework / ledger_snapshot） | **59 passed**（快照经 `ledger_snapshot.py --write` + `tests/refresh_count_anchors.py --write` 刷新：共享内核 27→28、自检声明 71→72、变异编号上限 M196→M202 等） |
| `python3 scripts/atlas_check.py --fast` | OK，无 FAIL |
| 变异钉五连（M197/M198/M199/M201/M202 摘守卫见红、逐钉复原复绿） | **5/5 红 → 复原 5/5 绿**（负断言消融规则自我适用，proposals/README §2 落地首日 dogfood） |
| 全量 `pytest tests/ -q` | 见 §6 验收序列终验行（feat 批提交后统一复跑 + golden 重录） |

**§4.5 触发面核对原始输出**（落刀批义务，摘录）：

- `git diff --name-only`（对照 HEAD）：`DESIGN.md`、`_support/workflow_finish.py`、`_support/workflow_verify.py`、`docs/map/*`（计数刷新）、`install.py`、`proposals/README.md`、`scripts/atlas_workflow.py`、`shared/gates.md`、`shared/single-source.md`、`tests/test_atlas_workflow.py`（另有未跟踪 `_support/workflow_causes.py` + 本 RFC/REVIEW）；
- `python3 scripts/closeout_derive.py --diff-base HEAD`：触发步骤 1/2（自动）+ 3/5/7（人工），`_support/workflow_*.py` 三件出「自有面未命中触发行」WARN（触发表缺口，非本批判据面）——**核对结论：(b) 不触发**（无 validators/ 无 atlas_check VALIDATORS 改动；diff 不落 DR4 段级锚路径族的校验器面；atlas_workflow/workflow_finish/workflow_verify 非 §4.5 (b) 判据面文件）。留出集不适用；负断言变异证据与 §3.2.1 变异同件（五钉四段已实测）。

---

## 8. 开放问题（待拍板）

1. **预算默认值**：`max_verify_attempts` 默认 2（对齐 D203 审修循环口径）还是 3？2 更紧（省 token），3 更宽容（复杂单元一次 verify FAIL 可能只是审查视角问题）。**建议 2**。
2. **deferred 通道的升级出口**：只做登记+可见化（本 RFC 口径）之外，是否给 `duty-review` 巡检开一条采纳仓 deferred 的只读采样口（跨仓只读，不写）？**建议挂观察**：先跑两代看「开放」deferred 积压量再定。
3. **Tested-by 锚棘轮强度**：可选但存活（本 RFC 口径）vs 新增行必带。**建议可选起步**，升格条件已写 §3.2.2。
4. **PRD 小件另案**：INV/OKR 二分、`[ASSUMPTION]` 逐条消化、OQ 责任人三件套——建议挂 `requirements/`（RFC-20261122-03）冷却期后的后续 RFC，本批不碰。
5. **双评审**：按 `RFC-20261114-07` 全档双评审惯例，本 RFC 是否追加第二独立评审？当前已过 tech-proposal-reviewer 第 1 轮（修后再审）+ v2 处置 + 复核轮；若维护者要求双评按同法补派第二人。
