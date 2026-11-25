# 需求落点扩展为初始需求、需求变更与缺陷的统一增量层

> 提案编号：RFC-20261124-01
> 提案作者：@sunwenzhe-git
> 关联状态：草案（实现中，待独立复审）
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

- **D1 统一落点**：初始需求、需求变更、缺陷共用 `<assets_root>/requirements/<slug>/`，不新增 `product/bugs/`。
- **D2 类型与基线**：`requirement.md` 增加 `**类型**：初始需求/需求变更/缺陷`；缺省为初始需求。需求变更与缺陷必须用 `**关联需求**：<slug>#R-NN` 指向既有需求落点，基线状态须为已确认/已拆/已收口。
- **D3 缺陷证据分层**：`work/缺陷报告.md` 保存现象、期望、实际、复现与环境证据；`items.md` 只引用既有需求落点中的权威行为条款。无既有行为依据的对象先登记初始需求落点或归类为需求变更。
- **D4 稳定关联与路径**：slug 不复用，活跃/归档重名（含损坏归档）按复用告警；解析先找活跃目录，再唯一匹配 `archive/<YYYY-MM>/<slug>`，并守住配置资产根、项目根、symlink 与围栏边界。任务卡 `requirement_root` 保存规范化逻辑路径，旧归档实体路径与逻辑 slug 归一，领取来源路径必须与之一致；`plan --requirement` 可传逻辑 slug 并回落唯一归档实体；路径型落点引用解析失败必须报错，不得退成直填（普通文本文件与含斜杠普通需求文本直填保留）；任务 ID 必须为合法非空字符串；归档链拒 symlink；关联/缺陷报告 finding 未清零不得推进收口；已归档任务 ID 禁止重建；卡正文指针只指 `work/` 来源材料。
- **D5 无卡分诊关闭**：重复、非缺陷、不修项写 `**结论**：重复/非缺陷/不修` 与非空 `**证据**` 后直接置「已收口」并归档，不造任务卡、不跑覆盖矩阵与 bug-fix 七检查点。
- **D6 类型感知收口**：关联卡全部位于合法 `archive/<YYYY-MM>/<任务ID>`、目录名等于 ID、无重复任务 ID 且 completed 后才提示推进落点状态；初始需求/变更回写产品事实，缺陷仅在事实缺失或错误时回写，verify 提示同分流。JSON 同步返回 `requirement_closeout`；非法类型、落点解析失败或 IO 错误只返回 pending/unknown。verify 先校验全局任务账本，损坏卡、非法 UTF-8 或无落点重复 ID 均拒绝收口提示，finish 对跨落点冒领同样拒绝推进；归档命名空间内同 ID 一律保留（含缺 task.json 的目录），`requirements/archive` 根拒 symlink 改道。
- **D7 索引非权威**：`_index.md` 只是派生导航视图，权威仍是 `requirement.md` 与 `task.json`，不作为判据输入。

### 2.2 最强反方与证伪条件

**最强反方**：三类对象共用需求状态机，可能把“尚未确认的 bug”误当需求，或让无卡关闭成为绕过验收的后门。

**回应**：候选态承接未确认对象；已确认 bug 必须有既有行为基线；无卡关闭只允许重复、非缺陷、不修三类结论，不产生实现完成声明。

**证伪条件**：若同一 `requirement_root` 的卡可以用另一落点的同 ID 满足覆盖，或落点归档后 verify 误报缺件，则单源与关联设计失效。

### 2.3 代价与兼容性

- 旧需求无类型字段，按初始需求处理，存量零迁移。
- 新增解析与归档回落均为本地文件操作，保持 WARN 纪律面，不新增硬门或 CLI。
- `_index.md` 不新增机器对账，避免把导航视图升级成第二真相源。

## 3. 改动面清单 (Affected Surface)

- [x] **契约/文档**：`shared/single-source.md`、`shared/layout.md`、`rings/prd/reference.md`、`shared/closeout.md`。
- [x] **代码逻辑**：`_support/workflow_plan.py`、`_support/workflow_verify.py`、`_support/workflow_finish.py`、`scripts/atlas_workflow.py`。
- [x] **测试防线**：`tests/test_atlas_workflow.py` 新增类型、关联、归档、跨根冒领、重跑指针、类型收口与多卡等待回归。
- [x] **门册/地图/决策**：`shared/gates.md`、`docs/map/*`、`DESIGN.md` D211、`CHANGELOG.md`。
- [x] **留出验证（§4.5）**：按 D156 触发面核对后填写。

## 4. 验证与测试结果 (Verification)

- Red First（首轮）：新增回归首跑 **11 failed / 2 passed**，失败覆盖类型、关联、跨根冒领、归档解析、重跑指针与 finish JSON。
- Red First（落地后复审补边）：新增边界首跑 **10 failed / 2 passed**，失败覆盖完成≠归档、非法类型收口、跨根/symlink、围栏假条目、候选基线、slug 复用与路径规范化。
- `tests/test_atlas_workflow.py`：**159 passed**（pytest 用例；AST 测试函数数见门册派生占位）。
- 变异证明：**M207–M244 三十八钉全通过**，均满足注入非零、逐字节还原一致、复绿；原始输出在 `.atlas/runs/mutation-proof/rfc-20261124-01/`。
- canonical / map / sync 自动化：**55 passed**。
- 全量测试：**2066 passed / 6 skipped**。
- 安装自检：**10 passed**；空目录装配成功；`atlas_check --fast` = **OK**。
- `git diff --check`：通过。

### 4.5 留出验证

触发面核对：本轮来自同一冻结设计的两位独立评审，重复命中跨落点假绿、归档断链、无卡关闭与 finish 漂移；属于多条独立 finding 同根修复。`git diff --name-only` 命中 `_support/workflow_{plan,verify,finish}.py` 与 `shared/` / `rings/` 契约面；`closeout_derive --diff-base HEAD` 派生步骤 1/2/3/5/7。`_support/` 的三条未命中 WARN 是既有显式盲区（`tests/test_closeout_derive.py` 有对应钉），本轮不扩面。落地后并行双评又确认完成≠归档、slug 复用、跨根/symlink、围栏假条目、候选基线、非法类型收口六类边界；终审进一步确认嵌套围栏、文件级 symlink、非法任务归档路径、旧归档身份分裂与 IO 失败五类残留；末轮复审再确认真实读取吞错、归档目录名≠任务 ID、重复任务 ID 与缺陷 verify 文案四类问题；补充复审进一步确认归档逻辑入口、跨月重复 ID、非法类型 verify 与账本失败兜底四类残留；末次复审再确认路径型入口退化、无落点重复 ID、坏账本、非法归档 ID 保留与归档根 symlink 五类问题；最终补边覆盖普通文件直填、无账本归档 ID、verify symlink loop、非法 UTF-8 与跨落点冒领收口五项，均已补实现与反例。当前未构造满足三条独立性的留出集，结论登记为 **未闭族**，不宣称闭族；后续真实采纳仓出现同类案例时补独立留出验证。
