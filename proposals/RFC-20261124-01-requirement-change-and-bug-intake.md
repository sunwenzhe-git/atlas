# 需求落点扩展为初始需求、需求变更与缺陷的统一增量层

> 提案编号：RFC-20261124-01
> 提案作者：@sunwenzhe-git
> 关联状态：活文档与 diff 回推实现完成，最终双评审通过
> 影响范围：核心契约 (shared) | 环契约 (rings) | 脚本工具 (_support / scripts) | 测试

---

## 1. 现象与取证 (The Problem & Evidence)

初始需求已有 `product/requirements/<slug>/` 落点，但需求变更与 bug 没有共同的类型、基线关联和关闭语义。直接为 bug 新建台账会形成第二生命周期；把 bug 报告塞进 `items.md` 又会复制证据正文或伪造需求原文。

只读双评审确认了五个必须闭合的面：

1. 无任务卡的重复、非缺陷、不修项没有合法关闭路径；`finish` 只认任务卡（`scripts/atlas_workflow.py:415-417`）。
2. 缺陷报告与 `items.md` 的逐字需求原文语义冲突（`rings/prd/reference.md` §12.1）。
3. 需求落点归档后，任务卡保存的逻辑路径失效；verify 直接拼路径（`_support/workflow_verify.py:255-266`）。
4. finish 的 JSON 输出没有回写待办，文本模式又对所有类型无条件要求沉淀产品事实（`scripts/atlas_workflow.py:436-454`）。
5. 跨落点领取只比对条目 ID，不比对来源路径，可被同 ID 冒领（`_support/workflow_verify.py:230-249`）。

## 2. 决策与权衡 (The Decision & Trade-offs)

### 2.1 核心定案

D1–D7 记录 2026-11-24 初始决策；D8/D9 是 2026-11-25 维护者确认的最终模型。二者冲突时以 D8/D9 为准：功能根类型始终保持初始需求，请求类型住 `changes/` / `bugs/`，缺陷证据不住 `work/`，已收口或已归档功能不接受新请求。

- **D1 统一落点**：初始需求、需求变更、缺陷共用 `<assets_root>/requirements/<slug>/`，不新增 `product/bugs/`。
- **D2 类型与基线**：`requirement.md` 增加 `**类型**：初始需求/需求变更/缺陷`；缺省为初始需求。需求变更与缺陷必须用 `**关联需求**：<slug>#R-NN` 指向既有需求落点，基线状态须为已确认/已拆/已收口。
- **D3 缺陷证据分层**：`work/缺陷报告.md` 保存现象、期望、实际、复现与环境证据；`items.md` 只引用既有需求落点中的权威行为条款。无既有行为依据时不自动伪装成缺陷；独立新能力走初始需求，变更/缺陷必须补唯一行为基线。
- **D4 稳定关联与路径**：slug 不复用，活跃/归档重名（含损坏归档）按复用告警；解析先找活跃目录，再唯一匹配 `archive/<YYYY-MM>/<slug>`，并守住配置资产根、项目根、symlink 与围栏边界。任务卡 `requirement_root` 保存规范化逻辑路径，旧归档实体路径与逻辑 slug 归一，领取来源路径必须与之一致；`plan --requirement` 可传逻辑 slug 并回落唯一归档实体；路径型落点引用解析失败必须报错，不得退成直填（普通文本文件直填保留）；已归档任务 ID 禁止重建；卡正文指针只指 `work/` 来源材料。
- **D5 无卡分诊关闭**：重复、非缺陷、不修项写 `**结论**：重复/非缺陷/不修` 与非空 `**证据**` 后直接置「已收口」并归档，不造任务卡、不跑覆盖矩阵与 bug-fix 七检查点。
- **D6 类型感知收口**：关联卡全部位于合法 `archive/<YYYY-MM>/<任务ID>`、目录名等于 ID、无重复任务 ID 且 completed 后才提示推进落点状态；初始需求/变更回写产品事实，缺陷仅在事实缺失或错误时回写，verify 提示同分流。JSON 同步返回 `requirement_closeout`；非法类型、落点解析失败或 IO 错误只返回 pending/unknown。verify 先校验全局任务账本，损坏卡、非法 UTF-8 或无落点重复 ID 均拒绝收口提示，finish 对跨落点冒领同样拒绝推进；归档命名空间内同 ID 一律保留（含缺 task.json 的目录），`requirements/archive` 根拒 symlink 改道。
- **D7 索引非权威**：`_index.md` 只是派生导航视图，权威仍是 `requirement.md` 与 `task.json`，不作为判据输入。
- **D8 自然语言 intake**：单仓 `plan/run` 文本入口先分类、唯一关联父功能并落请求，再拆卡；新卡 `intake_version: 2`，dispatch/verify/finish 对功能根、请求、条款与状态 fail-closed；旧卡/v1 独立 slug 不回溯，跨仓 solution 任务链显式旁路，普通文本文件直填兼容。
- **D9 功能活文档与回推**：一个功能点只维护根 `requirement.md`；首版快照入 `changes/CHG-000-initial`，后续变更/缺陷分目录存请求与证据。`atlas bug/change` 按 base 以来 diff 回推活文档/PRD/E2E/spec并跑现有校验，finish 用代码指纹+文档哈希强制新鲜度，语义冲突必须人工 decision。

### 2.2 最强反方与证伪条件

**最强反方**：三类对象共用需求状态机，可能把“尚未确认的 bug”误当需求，或让无卡关闭成为绕过验收的后门。

**回应**：候选态承接未确认对象；用户明确要求实现时，自然语言 intake 将该条请求确认为已确认后再拆卡。已确认 bug 必须有既有行为基线；无卡关闭只允许重复、非缺陷、不修三类结论，不产生实现完成声明。

**证伪条件**：若同一 `requirement_root` 的卡可以用另一落点的同 ID 满足覆盖，或落点归档后 verify 误报缺件，则单源与关联设计失效。

### 2.3 代价与兼容性

- 旧需求无类型字段，按初始需求处理，存量零迁移；旧任务卡无 `intake_version` 时保持原流程；普通文本文件直填保留。
- 新增解析与归档回落均为本地文件操作；自然语言 intake 与新一代任务卡前置门是硬门，按既有退出码 2 / `intake_missing` 登记，不新增 CLI 顶层命令。
- `_index.md` 不新增机器对账，避免把导航视图升级成第二真相源。

## 3. 改动面清单 (Affected Surface)

- [x] **契约/文档**：`shared/single-source.md`、`shared/layout.md`、`rings/prd/reference.md`、`shared/closeout.md`。
- [x] **代码逻辑**：`_support/workflow_plan.py`、`_support/workflow_intake.py`、`_support/workflow_dispatch.py`、`_support/workflow_verify.py`、`_support/workflow_finish.py`、`scripts/atlas_workflow.py`。
- [x] **测试防线**：`tests/test_atlas_workflow.py` 覆盖类型、关联、归档、跨根冒领、重跑指针、类型收口与多卡等待；`tests/test_workflow_intake.py` 覆盖自动分类、父需求歧义、幂等、dry-run、stdin 与 dispatch/verify/finish 前置门。
- [x] **门册/地图/决策**：`shared/gates.md`、`docs/map/*`、`DESIGN.md` D211、`CHANGELOG.md`。
- [x] **留出验证（§4.5）**：按 D156 触发面核对后填写。

## 4. 验证与测试结果 (Verification)

- Red First（首轮）：新增回归首跑 **11 failed / 2 passed**，失败覆盖类型、关联、跨根冒领、归档解析、重跑指针与 finish JSON。
- Red First（落地后复审补边）：新增边界首跑 **10 failed / 2 passed**，失败覆盖完成≠归档、非法类型收口、跨根/symlink、围栏假条目、候选基线、slug 复用与路径规范化。
- `tests/test_atlas_workflow.py`：**159 passed**（pytest 用例；AST 测试函数数见门册派生占位）。
- 自然语言 intake：`tests/test_workflow_intake.py` **57 个测试函数 / 65 个 pytest 用例**；最新基线定向回归结果见 §7。
- 变异证明：**M207–M246 全通过**，均满足注入非零、逐字节还原一致、复绿；M246 最终证据在 `/tmp/atlas-issue75-m246-final-zsmklr72/evidence/`。
- canonical / map / sync 自动化：**31 passed**（最终刷新后）。
- 全量测试：最终 **2163 passed / 6 skipped**（552.88s）。
- 安装自检与装配副本烟测：通过；真实 `validate_living_requirement` / `validate_prd` / `validate_e2e_index` / `validate_testids` 全绿，覆盖 v2 重跑、多卡稳定、同名小节、坏 UTF-8 与幂等回推。
- `git diff --check`：通过。

### 4.5 留出验证

触发面核对：本轮来自同一冻结设计的两位独立评审，重复命中跨落点假绿、归档断链、无卡关闭与 finish 漂移；属于多条独立 finding 同根修复。`git diff --name-only` 命中 `_support/workflow_{plan,verify,finish}.py` 与 `shared/` / `rings/` 契约面；`closeout_derive --diff-base HEAD` 派生步骤 1/2/3/5/7。`_support/` 的三条未命中 WARN 是既有显式盲区（`tests/test_closeout_derive.py` 有对应钉），本轮不扩面。落地后并行双评又确认完成≠归档、slug 复用、跨根/symlink、围栏假条目、候选基线、非法类型收口六类边界；终审进一步确认嵌套围栏、文件级 symlink、非法任务归档路径、旧归档身份分裂与 IO 失败五类残留；末轮复审再确认真实读取吞错、归档目录名≠任务 ID、重复任务 ID 与缺陷 verify 文案四类问题；补充复审进一步确认归档逻辑入口、跨月重复 ID、非法类型 verify 与账本失败兜底四类残留；末次复审再确认路径型入口退化、无落点重复 ID、坏账本、非法归档 ID 保留与归档根 symlink 五类问题，均已补实现与反例。当前未构造满足三条独立性的留出集，结论登记为 **未闭族**，不宣称闭族；后续真实采纳仓出现同类案例时补独立留出验证。

## 5. 自然语言 intake 首轮双评审与处置

同一冻结输入派两位互不可见 reviewer；严重度不一致取高，原始结论按下表合流。

| 级别 | 独立命中问题 | 处置 |
|---|---|---|
| Critical | 变更正文丢成「见父需求」；单父静默误挂；全归档时新功能被错误要求基线（A）；单父误挂（B） | 已修：变更 `items.md` 保存完整原文；只按明确父需求名/标题或 `--related` 关联；无未收口父需求时独立新能力落初始需求 |
| Major | 同一 unit 新原文被丢弃（A/B）；跨 unit 重复请求幂等失败（A/B） | 已修：内容摘要在父解析前复用；同 unit 不同原文默认 rc2，显式 `--replan` 才重建 |
| Major | 泛化「失败/异常」把新功能判缺陷并伪造复现（B） | 已修：收窄缺陷词；报告只写用户事实，缺失环境/操作序列明确「未提供」 |
| Major | solution 新卡绕过 intake（A/B） | 边界登记：跨仓成员卡为显式旁路，由父仓 solution 需求/AC 指针追溯；单仓 plan/run 仍是唯一自动入口 |
| Major | 索引复制状态/关联卡且不刷新（A） | 已修：索引只保留 slug/类型/关联需求，不复制状态或任务清单 |
| Major | 仓外落点 plan 成功但 dispatch 永阻（B） | 已修：plan 对仓外/非法落点直接 rc2；合法归档实体仍归一逻辑 slug |
| Minor | plan WARN 与 dispatch 硬门不一致（A） | 不改：保留并行基线既有 plan WARN 语义，硬门落在实现入口 dispatch/verify/finish |
| Minor | 状态行尾双空格被吞、文档基线语义漂移、路径被当正文（A） | 已修：保留 Markdown 行尾；同步契约；路径不存在/缺 `requirement.md` 直接 rc2 |
| 测试缺口 | 原测试只断言「见父需求」、只测初始需求幂等、未测单父误挂/同 unit 换文本 | 已补：完整多行正文、重复 bug、单父拒绝、全归档新功能、同 unit 拒绝、候选/缺证据/finish 阻断等反例 |

首轮修复后合并主仓并行窗口新增的路径/symlink/归档边界基线，避免覆盖或回退该窗口成果；最终回评审与全量结果在本节续记。

## 6. 最终回评审与处置

两位 reviewer 均核验冻结哈希；首轮 Critical 全部关闭。最终回评新增问题按严重度合流如下：

| 级别 | 问题 | 处置 |
|---|---|---|
| Critical | 动态加载 `workflow_plan` 时包根不在 `sys.path`，solution task create 抛 `ModuleNotFoundError`（A） | 已修：layout 改为同目录动态加载回退并注册 dataclass 模块；新增 cwd 在包外的 subprocess 反例 |
| Major | 「回归测试/故障演练」同时含变更与缺陷词，被误判缺陷（B） | 已修：自动模式变更证据优先；显式 `--type bug` 才按缺陷 |
| Major | 短标题子串仍可静默误挂父需求（B） | 已修：只接受显式 `<slug>#R-NN`、`--related` 或长度足够的完整标题；新增「登录日志」反例 |
| Major | 显式传另一落点路径可绕过 `--replan`（B） | 已修：落点身份切换也要求 `--replan`；新增路径切换正反例 |
| Major | 旧卡重跑被盖 `intake_version: 1`，反而被新门锁死（B） | 已修：已有旧卡无标记时保持无标记；新卡仍写入标记；新增旧卡重跑 dispatch 正例 |
| Major | 已收口落点复用后 plan 成功但 dispatch 永阻（A） | 已修：已收口落点跳过摘要复用并生成新 slug；同 unit 默认要求新 unit，`--replan` 可显式重建 |
| Major | `--slug archive` 污染归档容器并抛 IndexError（A） | 已修：`archive`/`_index` 保留名在写入、解析、逻辑归一三处拒绝 |
| Minor | 缺陷 `items.md` 自指、实际结果被写成既成事实（A/B） | 已修：确认稿指向 `work/缺陷报告.md`；未提供证据明确写未提供 |
| Minor | 状态替换命中围栏示例、索引 symlink 跟随写出（B） | 已修：只替换首个首部状态字段；索引 symlink 在写入前拒绝 |
| Minor | 旧来源 `<落点>/items.md#R-01` 误报冒领（A） | 已修：归一前剥离 `/items.md` 或 `/requirement.md` 后缀并加反例 |
| Minor | 已归档 completed 卡重放被已收口状态拦停（A/B） | 已修：归档完成卡允许幂等重放 |
| Minor | 地图自检数量与 CLI 用法过期（A） | 已修：74 条自检；plan/run 用法补齐 stdin/type/related/slug/replan |

D5 无卡分诊关闭仍是**纪律面**：门册既有行明确不查其字段内容，本轮不新增语义门；`结论/证据` 的写法由 `rings/prd/reference.md` §12.4 承担。

## 7. 终审残留与关闭

| 级别 | 独立命中 | 关闭方式 |
|---|---|---|
| Major | 活跃/归档同 ID 被静默覆盖（A/B） | `load_tasks` 重复 ID 直接 `PlanError`；新增双卡同 ID 反例 |
| Major | `--replan` 换落点后领取表仍指旧落点（A） | 落点身份变化时重建领取表；保留新落点指针，清除旧来源 |
| Major | 已收口落点可作新任务入口（A/B） | 基础合法状态移除已收口；仅归档 completed 卡可幂等重放；显式落点入口 plan 直接拒绝 |
| Major | 文本写 R-99 但条目不存在时回退 R-01（B） | 显式条款 ID 不存在即 `PlanError`，不再静默降级 |
| Minor | 中文斜杠文本被当路径（A/B） | 路径识别只接受 ASCII 路径段；新增中文斜杠正例 |

上述修复后 `tests/test_workflow_intake.py` + workflow + solution 定向回归 **192 passed**；末次双核验又发现中文紧邻 `R-99` 无词边界，已改为 ASCII 数字边界并补无空格反例；M245 四段协议再次通过。最终双核验对其余四项均确认关闭。合并主仓最新并行基线后，定向回归 **230 passed**、工作流/CLI/装配/契约受影响回归 **307 passed**；该基线全量 **2056 passed / 6 skipped**，本次最终全量结果见 §4。

## 8. 并行基线合并回评审

| 级别 | 合并回退 | 处置 |
|---|---|---|
| Critical | `archive_task` 丢失归档根/月目录 symlink 与越界守卫（B） | 恢复主仓最新 `archive_task`；保留 intake finish 前置 |
| Major | closeout/verify 的 all-closed 不再要求关联检查为空（B） | 恢复主仓最新 relation/claim/load 失败守卫 |
| Major | 任务 ID 真值判断导致列表 ID 崩栈、空白 ID 放行（B） | 恢复主仓最新字符串非空校验；重复 ID 仍拒绝 |
| Major | `--replan` 传普通文件时关闭 intake，正文与旧落点绑定丢失（A） | 仅无 prior 的普通文件走直填；有 prior 的文件重跑必须重新 intake 并保留绑定；新增反例 |
| 基线能力 | 逻辑 slug 归档回落、归档 ID 保留、普通文件直填、重复 ID 拒绝 | 定向与广泛回归均保留；主仓新增 M242–M244 测试一并恢复并通过 |
| Major | intake 卡缺领取表、来源非法或漏领时 closeout/verify 仍提示可收口（A/B） | 已修：closeout 与 verify 对 intake 卡校验领取表存在、来源可解析、条目覆盖完整；缺表/非法/漏领/幽灵引用均阻断收口提示，新增四类反例 |
| Major | 混用旧卡/新卡时 finish 只统计新卡领取；行内 ID 与来源 ID 不一致仍可收口；「来源说明」表头触发 StopIteration（A/B） | 已修：所有合法来源参与覆盖；行内/来源 ID 不一致入 findings；表头只认精确「来源」；新增混卡、幽灵、无来源列、互换 ID 反例 |
| Major | 纯旧卡幽灵/漏领被 has_intake 短路；旧直填表无「来源」列时合法 ID 不计入覆盖（A/B） | 已修：覆盖与幽灵检查对所有关联卡生效；旧直填表按「原文」表头回退取行首 ID；新增旧卡幽灵与旧/新混卡反例 |
| Major | 条目表按子串选头，正文含「来源」误命中；旧卡无表时 verify 静默推进（A） | 已修：共享 `claim_items_table` 只认精确 ID + 来源/原文表头；无表/无合法表头统一入 findings；新增正文含“来源”与旧卡缺表反例 |

末次双核验对旧直填兼容、混卡并集、幽灵/漏领、ID 不一致逐项确认； reviewer 最后的精确表头与缺表反例已补实现和测试。安装副本自动归类→落点→dispatch 烟测通过，M245 四段协议通过，该阶段全量 **2123 passed / 6 skipped**；最终结果见 §4。

## 9. 功能活文档与 diff 回推（2026-11-25 维护者确认）

维护者确认：每个大功能点只保留一份持续更新的需求文档，需求变更与缺陷必须分目录，首版需求作为不可变基线快照。最终结构：

```text
requirements/<feature>/
├── requirement.md
├── items.md
├── changes/
│   ├── CHG-000-initial/{requirement.md,request.md,diff.md}
│   └── CHG-YYYYMMDD-NNN/{request.md,diff.md}
└── bugs/
    └── BUG-YYYYMMDD-NNN.md
```

- 初始需求创建功能根、R-01 与首版快照；变更/缺陷只新增请求并更新功能根变更记录/条款索引。
- `atlas bug` 与 `atlas change` 共用 `scripts/atlas_bug.py`，以请求 `base_commit` 以来 diff 反查 spec paths 与 testid/API/错误码/字段标识符。
- 机械引用可自动更新；活条款只在 `diff.md` 有明确变更后且基线未变时更新；语义冲突必须 `--decision` + `--decision-by`。
- 请求内 JSON 回执记录代码指纹、文档哈希、影响面、冲突与校验结果；finish 缺回执/冲突/过期分别阻断。
- 旧 v1 独立 slug 与 `work/` 数据只读兼容，不自动迁移；普通文本文件直填保留。

### 9.1 本轮验证

- `tests/test_workflow_intake.py`：57 个测试函数 / 65 个 pytest 用例全部通过。
- `tests/test_workflow_backflow.py`：28 个测试函数 / 30 个 pytest 用例通过（testid/spec 回推、变更条款、业务冲突与显式 decision、缺回执、代码过期、dry-run、校验红、成功 finish、重复执行、混卡隔离、真实 validator、living 校验、docs 过滤、版本累计、坏文档/坏 UTF-8 回执、快路径损坏、外部坏 UTF-8、截断/空列、最近请求旧 ID/不存在 ID、悬空/被删请求变更记录）。
- 工作流/CLI/装配/契约最终受影响回归：**254 passed**；全量结果见 §4。
- 真实校验器与装配副本烟测：`validate_living_requirement` / `validate_prd` / `validate_e2e_index` / `validate_testids` 全绿；v2 省略需求/同原文重跑保持请求指针与 base，多卡重跑不新增卡，同名 Markdown 小节按 source_sha256 切点恢复，坏 UTF-8 输入与坏回执均干净 rc2。
- M246 四段协议通过：注入 rc1、还原 rc0、字节一致；最终全量 **2163 passed / 6 skipped**。

## 10. 活文档回推双评审与处置

两位 reviewer 对同一冻结输入独立评审，均确认核心链路可运行，并复现以下问题；已按自证面全部修复：

| 级别 | 独立命中 | 处置 |
|---|---|---|
| Critical | 子串盲替换导致 `-new-new`、PRD 版本二跳（A/B） | 标识符改词边界匹配；同快照早退；元数据重跑不重复替换/升版 |
| Critical | 初始请求 items 比对错误，二次 plan 丢 v2/request_path（A） | initial 去重不比 items；重复原文在分类前复用 v2 请求 |
| Critical | decision 缺 decision-by 仍写业务文档（A） | 缺签名提前返回，零业务写入 |
| Major | 不同字段/无对应关系的新增值被误配为改名（A/B） | 要求同文件；字段名按值配对、字段值按键配对；status 不命中 statusCode |
| Major | diff_text 未过滤文档自身改动（A） | 与代码快照共用 managed 过滤 |
| Major | 第二请求改功能根导致第一回执过期（B） | 回执改为条款/变更行/items ID 行片段哈希，不哈希整篇活文档 |
| Major | 多行/管道原文撑破变更记录（A/B） | 单元格转义；结论按行首 ID 定位后替换末列 |
| Major | 缺活文档校验、测试全打桩（A） | 新增 living-document 校验项与真实 validator 回归 |
| Major | 已收口功能仍可追加请求（B） | 父基线只接受已确认/已拆 |
| Minor | 分类把强症状缺陷当变更、失败状态混淆、base 不入指纹、请求元数据可手改（A/B） | 强缺陷词优先；failed 单列；base 入摘要；finish 核对请求元数据 |

## 11. 回评审残留关闭

末次双核验确认前十项关闭，并补出四项残留：living 校验结果被 `results=[]` 覆盖、`docs/*.md` 仍进入代码标识符分析、功能版本不累计、字段名同值误配。已分别修复：保留 living 校验结果、代码快照排除 docs、版本从活文档实读递增、字段名不自动配对（字段值仍要求同键）；对应反例已补。全量结果见 §4。

末轮再补：活文档缺失/坏 UTF-8 时，回推仍写 fail 回执并返回 1，不再抛错返 2 无回执；字段名误配反例改为 change 档并使用同值，避免 bug 档强制冲突掩盖判据。

坏 UTF-8 终核补边：活文档在影响分析前做严格解码检查，缺失或任何坏字节都直接写 fail 回执并返 1；外部目标文档坏 UTF-8 记 conflict 不写入。新增部分坏字节与 change 缺 requirement.md 端到端反例。

快路径与外部编码终核：活文档严格检查前置于幂等早退；成功回执后文档损坏会覆盖为 fail 回执并返 1。git diff 与回执片段读取统一 errors=replace，外部坏 UTF-8 不再绕过回执，而是记 conflict 且不写入。

结构完整性终核：`items.md` 必须四列非空、ID 唯一，「最近请求」按变更记录顺序指向该条款最新请求；变更记录所有数据行必须对应磁盘现存请求且唯一六列非空。截断、空列、旧 ID、不存在 ID、孤儿行、请求文件删除均写 fail 回执并阻断 finish，`--force` 不绕；正常第二请求不误伤第一回执。

重跑与输入编码终核：v2 卡省略 `--requirement` 或同原文重跑时继承 intake/request/base 元数据，并从请求原文而非活文档重新拆卡，多卡数量与 ID 稳定；请求原文含同名 Markdown 小节时按 `source_sha256` 选择唯一切点。stdin、需求文件、请求记录坏 UTF-8 均干净 rc2，无 traceback；坏回执不会把任务推进为 completed 或归档。

最终双评审：两位独立 reviewer 对冻结哈希核验，上述残留逐项关闭；全量 **2163 passed / 6 skipped**，装配副本真实校验器烟测通过。
