# REVIEW-20261122-07: RFC-20261122-07 首轮评审（tech-proposal-reviewer）

> 评审对象：`proposals/RFC-20261122-07-executor-recovery-and-test-discipline-absorption.md`（v1）  
> 评审轮：第 1 轮 · 单评（用户指令）· 2026-11-22  
> 总判定：**修后再审**（1 Blocker + 6 Major + 6 Minor + 4 Nit）  
> 意见处置：全部见 RFC v2 §0.1 修订摘要表；复核轮回本文件追加

---

## 意见全文（第 1 轮）

### A. 证据准确性

**[Blocker] §3.1.2「:332/:392 底层异常 1→2」是对共享 die 位的错误处方，照写即推翻本 RFC 自己的退出码表**
- 证据：`scripts/atlas_workflow.py:331-332`（`except FinishError as exc: return die(str(exc), code=1)`）；`_support/workflow_finish.py:184`（「收口需 PASS，WARN/FAIL 均阻断」）、`:447/:451/:457`（review 未过 / E2E red / 新鲜度门红全部以 `FinishError` 冒泡）；`tests/test_atlas_workflow.py:290`（finish 门红钉 `rc==1`）、`:356`。RFC §1.2 自己写明「:332 底层异常**与门红共用** 1」，§3.1.2 却把该位整体改判 2 并标注「（底层异常）」——字面实施后，finish 的 review-WARN/FAIL、scope 封口红、e2e_red、freshness_fail 全部变成「2=用法或前置不满足」，直接违反同节「1=判定失败·门红」的封闭分配，且翻转两条既有测试。
- 修法：把「两处修正」改写为**按 cause 分流**的指令：`:332` 承载的 FinishError 先过 §3.1.1 词表判定——`freshness_fail`/`e2e_red`/review 未过/scope 封口红保持 1，仅 environment / 顺序类（no_review_report、no_task_card）与 `:392` 归档 OSError 类走 2。退出码表须补一行「同一位点、不同 cause、不同码」的显式说明。

**[Major] §1.3「触碰 pre_existing 的只有 cli_review_convert 与 review_closure」列举失实**
- 证据：`_support/review_policy.py:120/:127/:286-288`——D129 状态内核本身实现 pre_existing 降级（「pre_existing=True ⇒ 不阻断，状态下限抬为 WARN」），是「合同面降级」的真正判据单源；grep 全仓还命中 `shared/gates.md`、`docs/gates/iron-gates.md`。
- 为什么是问题：核心负断言（无聚合落账通道）经复核**成立**（review_policy 只降级不落账），但「只有 A 与 B」的穷举在本仓「先回代码证实再报缺口」纪律下属引用失实，且漏掉的恰是承担降级语义的内核。
- 修法：改为「代码面 = `_support/review_policy.py`（降级判据单源）+ `cli_review_convert`/`review_closure`（合同消费）；无任何组件把存量 finding 聚合落账」。

**[Minor] §1.1「重试次数没有任何记账」略过头，且未处置更瘦替代**
- 证据：`_support/workflow_finish.py:46-73`（`scan_review_rounds`——每单元每次审查留 `findings/<unit>.r<N>.json`，跨日可数）；`shared/independent-review.md`「轮次上限与升级复议：round >= 4 必须 escalation 否则拒绝放行」。审查层已有**当日**轮次记账与 round-4 升级闸；真缺口是跨日不设防 + verify/finish 层无预算。§5.2 备选里应显式否决「直接数 findings 轮次文件当预算」（理由现成：按日重置、混入直跑 `atlas review`、无 cause/charged 信息），顺带解释新预算默认 2 与既有 round-4 两个环上限为何不同值。

**[Minor] §0/§4「`atlas_review.py:248` round≥2 复审**自动**收窄」措辞过强**
- 证据：行号与原文准确，但该行在 `write_review_request` 的派工单模板内——是给 fresh-context 子代理的**指令行**，非机器强制的范围收窄（代码无第二处收窄实现）。结论（不吸收 quick/thorough）仍可维持，但「自动」应改为「派工单指令收窄」。

其余取证逐条核实为真：`atlas_workflow.py:279/323/332/380/392/471` 行号与语义全部准确；`workflow_finish.py:167` no_review_report 路径属实；`independent-review.md:77` 逐字命中；attempts/retry/budget 在七个 workflow 模块中零命中（负断言成立）；`agent-pointer.md` 全文无按退出码分支的消费行、`bin/atlas.js:406-414` 纯透传（兼容性取证成立）；`single-source.md:22/57/58`、`DESIGN.md:671-676`（D204 ②三态、D206 目标函数）引用准确。

### B. 与已定案决策的冲突

N1 本身成立：attempts/deferred/paused_reason 全在 task.json 状态之外，D204 三态与 D208 `validate_task_card` 零触碰，`layout.md` 不动（无新顶层目录）。但有一条被忽略的登记义务：

**[Major] gates.md 登记行缺失——预算拒绝是新的机器拒绝行为，有直接先例**
- 证据：`shared/gates.md:59`——同为 finish/verify 侧前置的「结构事实新鲜度」（RFC-20261122-05）按 §2.1 机器门格式登记（含判据、显式盲区、触发物、假绿测试/M 钉号）；gates.md §4 还有「缺口清单（未登记）」段。本 RFC 的「charged≥上限 ⇒ 拒绝 + 退出码 3」是同级机器拒绝，且 §3.2.1 自我适用的 M 变异钉也需要登记位（M165-M168 等钉号全部住在 gates.md 假绿测试列）。§6 三期改动面清单完全没提 `shared/gates.md`。
- 修法：第一期改动面加一行「shared/gates.md §2.1 增预算门登记行（判据 / 盲区：uncharged 误分类不可机判 / 触发物 / M 钉）」；若维护者认定非门，须在 RFC 里写明排除理由，不能沉默。

**[Minor] §4.5 对 D156 触发 (b) 的转述走样**
- 证据：`shared/gates.md:121` 与 `shared/closeout.md:83`：触发 (b) = 改门/校验器/契约判据 **且** `git diff --name-only` 落 DR4 段级锚路径族（`closeout_derive.py` 输出手工对照）。RFC 写成「diff 不落任何 validators/」，这不是 (b) 的判据。§4.5 的自我评估结论（预期不触发）可能仍对，但程序上落刀批必须粘贴 `closeout_derive.py` 原始输出。改写为引用 gates.md §2.5 原口径即可。

### C. 边界盲区

**[Major] cause 封闭词表漏掉两个真实失败路径（都流经被改的 die 位）**
- 证据：`_support/workflow_finish.py:182-192`——finish 侧至少还有两类高频失败不在 9 词表内：① review.json 存在但 `status != PASS`（「收口需 PASS，WARN/FAIL 均阻断」）；② v4 内容封口红 `_scope_matches`（实审文件内容已变/审查产物误入暂存面，`:93-150`）。「封闭词表 + 判定不清默认扣」遇未列举路径时行为未定义（既无法写 paused_reason，扣不扣也无据）。
- 修法：词表补 `review_not_passed`（扣，finish 侧发现报告未过）与 `scope_stale`（扣，封口门红）；并写明 fallback：词表外一律 `charged=true` + `cause=unclassified`，词表测试钉穷举值域。

**[Minor] 预算绕行面未声明**：预算只在 `cmd_verify` 入口拦；宿主 agent 换 `atlas review --staged` 直跑即可绕开（同量 token 燃烧）。§5.2 反方论证了改配置与谎报 cause 两条绕路，漏了这条最直接的。修法：二选一——在 RFC 写明「直跑 review 不在防线内，属人工责任」，或把预算检查下沉到 `atlas_review --staged` 入口（多一处单写者违约，不建议）。

**[Minor] attempts.jsonl 半行/坏行 fail-soft 未定义**：§5.3 只覆盖「无文件按 0 计」。append-only 单写者在崩溃时可留半行 JSON；且 §5.2 的取证命令 `json.loads(l)` 遇坏行直接炸。修法：读侧跳过不可解析行（可 WARN 出声），§5.2 命令同口径。

**[Nit] 退出码 130 并非空头承诺，但应写清来源**：实测（Python 3.12，无信号处理）SIGINT 下进程死于信号、shell 观察到 130；SIGTERM=143 落在「131+ 不分配」区。修法：表下加注「130 由信号死亡天然产生，无 die() 路径发出；SIGTERM(143) 不入表」，防实施者去写 signal handler。

**[Nit] dispatch/plan 的 die 路径不入词表是对的，但缺一句显式排除**：`atlas_workflow.py:185/188/190/194`（已 completed 不能重复派发、依赖未满足等）全是 uncharged 类且默认 code=2，与新表自洽——补一句「dispatch/plan 失败不记 attempts、不占预算、无 paused_reason」即可封死这个问号。

### D. 过度设计检查

**[Major] §3.2.2 Tested-by 锚消费器落在 tests/，而它的受益者（采纳仓机制文档）永远跑不到它**
- 证据：`tests/test_map_anchors.py:8-10`（「docs/map 是 atlas 自仓资产，**不装配进 .atlas/**」；tests/ 自 RFC-20261114-01 起不进装配面）；`docs/` 下**不存在** architecture/ 目录（RFC 自认「Atlas 自身仓尚无实例」）；机制文档的发现面 `discover_mechanism_docs` 在 `_support/workflow_verify.py:424`——这个才随装配分发。结论：消费器放在 Atlas 仓测试里 ⇒ 要检查的文档（采纳仓 `docs/architecture/*.md`）所在的仓永远不执行它 ⇒ 「采纳仓落地受益」主张为空，当前形态是零可达消费者的死代码。
- 修法（二选一，皆更瘦）：① 把锚存活检查并入 `_support/workflow_verify.py` 的 `mechanism_doc_findings` WARN 族（随装配分发、只在已写锚的行上出声，与 :57 提示族同节奏）——tests/test_map_anchors.py 不动；② 砍掉本件，等第一篇机制文档真实出现再立。另：即便保留 tests 方案，也应新建消费函数复用 `discover_mechanism_docs`，而非扩 test_map_anchors 的 charter（其章程是 docs/map 专属）。

attempts 预算本身：真问题（verify 全量审查是 token 大头、跨日打转无人拦），机制薄（一个 JSONL + 一个计数），对齐 D206 目标函数的 token 轴，保留。deferred 最小面：登记+可见化收得恰当，不做 sweep 分诊正确。cause 9 类双轨：真正承重的是 charged 布尔位，具体 cause 串是观测面——按本仓「封闭值域」惯例可接受，不建议再砍。

### E. 证伪条件可执行性

**[Major] §5.2 discriminating_check 不具判别力，且与其声明的判据脱节**
- 证据：命令只全局求和 `sum(1 for r in rows if r['charged'])`，而判据是「**单元级** charged≥上限的**停止事件**」与「单单元连续 ≥4 次 verify」——全局和既分不出单元也分不出连续；glob `.atlas/tasks/*/attempts.jsonl` 漏掉 `archive/<YYYY-MM>/<id>/`（RFC 自己说 attempts 随卡归档保留）；「停止事件」（exit 3 拒绝）没有落任何机器可读记录——拒绝发生的那个 verify 按设计**不再写 attempts**（预算检查在跑审查之前），该事件从 attempts.jsonl 不可复算。
- 修法：① 预算拒绝时追加一条 `{cause:"budget_exceeded", charged:false}`（不计数、只留痕），停止事件即机器可查；② 命令改 per-unit 聚合：`Counter` 按 unit 键控 charged/total，再判 `any(charged[u]>=2)` 与 `any(total[u]>=4)`，glob 补 `archive/*/*/attempts.jsonl`；③ `expected_if_false` 现文语义缠绕，重写成与判据逐字对应的期望值。

**[Minor] 误扣率 30% 阈值无可落地的复核载体**：「人工复核」结论无登记字段，事后不可复算。修法：deferred 或 attempts 侧不加面，接受人工结论进 closeout 叙事即可，但 RFC 应写明复核结论的留痕位置（建议随代际账本记一行）。

### F. 改动面完整性

**[Minor] 计数锚/快照遗漏**：「install.py 自检 70 条」实况为 **71**（`docs/map/index.md:113`〔数:自检声明=71〕）；新增 `_support/workflow_causes.py` 会使〔数:共享内核=27〕→28、`tests/` 计数、最大单件等快照漂移——§6 改动面未列 `docs/map/index.md`。`refresh_count_anchors.py` 在 `tests/` 不在 `scripts/`，验收命令请带全路径。

**[Minor] `.atlas/config.yaml` 是新文件不是「增键」，且缺缺省回退语义**：全仓无任何代码读写 `.atlas/config.yaml`（现存的是根 `atlas.config.yaml`，`_support/layout.py:29`；`shared/solution.md:166` 那处是退役期多仓遗物）；D205 ① 只立了意向。第一期实际要**新建**该文件 + 读取器 + 「旧装配无此文件 ⇒ 默认 2 不报错」的 fail-soft。另 D205 的工作流参数位在 **①** 不在 ②，引用改正确。golden 面相应扩（新文件入装配树）。

**[Minor] 第二期 single-source.md 登记行落点描述混乱**：§57 是 §4 约束 bullet，登记行走 §1 表（`| 信息 | 唯一真相源 | 派生视图 |` 三列格式）。attempts/deferred 各一行落 §1 表，措辞对齐 §1 既有行。

**[Nit] deferred 条目「对齐 D154」但状态值 `open` 偏离 D154 闭集**：D154 状态闭集 = `开放｜已修·待复验｜已出库`（`duty-review/bugs.md` 制式段）。status 聚合要数 open，值域必须闭集——直接复用 D154 三值或声明自己的闭集并给钉。

**[Nit] 契约注释面未列**：`atlas_workflow.py:17` 模块 docstring 退出码契约与 `:311`「本命令的退出码契约 = 0/1/2」注释需随 3/130 更新；「run 只读」措辞与 run→cmd_verify/cmd_finish（写者）矛盾，改「run 不额外写」。

---

## 总判定（第 1 轮）：修后再审

架构方向（状态机外元数据、双轨分类、只登记不分诊、纪律先于门）与 D203/D204/D205/D206 全部咬合，取证密度在同体裁提案中属上乘，负断言大多经复核成立。但 Blocker 一条（:332 整位 1→2 的字面处方会把 finish 门红改判成用法错误，推翻本 RFC 自己的封闭退出码表并翻转既有测试钉），加上词表漏路径、gates.md 登记缺席、证伪命令无判别力、Tested-by 消费器零可达四条 Major 都落在核心交付面上，修正涉及设计细节重排而非措辞润色——按本仓「Major=修后通过的前提、成簇于核心面则复审」的口径，修完这批应回评审位复核后再落刀。

---

## 复核轮（第 2 轮，2026-11-22，同一评审位）

**v2 处置判定**：首轮 Blocker 真实消解（cause 分流成立、门红保 1、:356 钉保住）；6 Major 中五个干净消解（1.3 枚举 / gates.md 登记 / 词表补齐+fallback / Tested-by 可达性——装配白名单含 `_support/`（docs/map/index.md:58）实证 / 证伪命令主体）；Minor/Nit 批 13 条全部消解。

**新发现问题**：

- **[Major] `:332` 分流对 `no_review_report` 未分配码位，且「钉 290 不翻转」声明不可能自洽**——`tests/test_atlas_workflow.py:290` 钉的恰是 no_review_report 路径（FinishError → `:332` rc==1）；v2 保 1 清单只有四类门红，`no_review_report` 无归属；按语义应走 2 ⇒ :290 随语义更新（同 :380→test:439 的合法更新），v2 括注为假。fallback `unclassified` 退出码未显式。
- **[Major] deferred 提取绑 finish 成功路径 ⇒ 头条病案永远到不了台账**——`review_policy.py:127` pre_existing Critical ⇒ 状态下限 WARN → `workflow_finish.py:184` WARN/FAIL 均阻断收口 ⇒ 要收口必须 disposition 关闭，而提取过滤「未关闭」⇒ 成功路径只剩 open pre_existing Minor 可落账；§1.3 动机（「Critical 记录于存量台账，然后呢」）与通道承载力错位。（复核员注：首轮已识别未入报告，如实补登。）
- **[Minor] 判据乙 t 计数器混入 uncharged verify 行**——staged_empty 反复重跑（零 token）即可凑 ≥4 造假退役信号。
- **[Minor] §5.2 命令括注「坏行跳过」与工件不符**——列表推导 `json.loads(l)` 无守卫。
- **[Nit] ×4**：§3.2.2「verify 分册」指代有误（test_atlas_verify 是 D150 另一子系统）；deferred 幂等对无 fingerprint finding 无回退键；`budget_exceeded` 留痕行 `cmd` 未规定；复核请求中「N6」为评审指令笔误（RFC 红线始终 R1/R2/N1-N4，防呆备忘）。

**总判定：修后通过**——残留全部是规定补全级修法（两段文字、一条测试期望值、一处执行顺序），不动架构、不动分期、不动红线，且都落在 §6 既有验收序列覆盖面内。**修完可直接进实施批，无须第三轮评审。**

**v2.1 处置（同日完成，全部落 RFC §0.2 表）**：`:332` 映射补全（`no_review_report`→2、`unclassified`→1 写死、钉声明改「:356 不翻转/:290 随语义更新」）；deferred 提取移至 finish 门判定之前（打印「登记 N 条（其中阻断中 M 条）」）；判据乙改 charged-only；证伪命令改逐行 try/except（声明与工件一致）；4 Nit 全补（测试文件径指 / fingerprint 回退去重键 / `cmd` 写死 `'verify'` / N6 笔误备忘无改动）。
