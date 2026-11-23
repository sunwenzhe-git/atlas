# atlas 共享契约 — 单一真相源登记

> 每类信息的**唯一权威落点**。各环只能引用，不得在别处复制正文。
>
> 路径约定：下表 `product/` 均为**默认资产根**示例；实际按项目根 `atlas.config.yaml` 的 `layout.assets_root` / `layout.adr` 解析（见 `shared/layout.md` §1.1）。

## 1. 登记表

| 信息 | 唯一真相源 | 派生视图 / 引用者 |
|---|---|---|
| **需求落点（需求 PRD / 条目 / 原文转换稿）** | `<assets_root>/requirements/<需求slug>/`：`requirement.md`（确认稿 = **需求 PRD**，首部状态行 `**状态**：候选/已确认/已拆/已收口`）+ `items.md`（**落点条目表**，条目正文唯一住址）+ `work/需求PDF-全文.md`（原文转换稿）+ 收口后移 `requirements/archive/<YYYY-MM>/`；登记 = `requirements/_index.md`。**2026-11-22 登记（`RFC-20261122-03`）**，改判 2026-09「不另建 inbox 或需求文档」立场：需求层是需求类信息的**唯一真相源**（增量），与产品事实（存量）分层，非第二正文源 | 执行层 `plan --requirement`（落点模式）/ `verify` 跨卡覆盖性对账 / 域级产品事实沉淀回写（`rings/prd/reference.md` §12） |
| 需求卡（任务 PRD） | 执行层任务的 `prd.md`（`.atlas/tasks/<NN-slug>/prd.md`） | **承接引用**需求落点条目（落点模式卡不复制条目正文与需求正文，`task.json.requirement_root` 指向落点）；**直填模式保留**（无落点的单卡小需求，旧行为逐字节不变） |
| **需求原文（外部原件的仓内转换稿）** | 需求落点目录 `work/需求PDF-全文.md`（带 `<!-- page N -->` 页码锚、空白页保留裸锚；正文逐字不改写；**不在仓内的需求视为不存在，不得进入实现**，2026-11-21 登记）。**2026-11-22 自卡目录迁移至此（`RFC-20261122-03`，走 §3 迁移仪式 + 存量豁免）** | `items.md` / 卡领取引用表 / `coverage-matrix.md` / 实现引用与冲突裁决 |
| 结构事实（全局层 + 域级层） | `.atlas/spec/structure/`（结构环事实层（`paths:` 索引）） | 各环按需 Read；`atlas workflow dispatch --paths` 按索引只注入命中规范 |
| 域清单（候选 / 已定稿） | `.atlas/spec/structure/_meta.json`（机器）+ `tour.md` 域速查（人读）；structure 提议 → PRD 定稿回写 | PRD / E2E |
| **域间依赖**（实现前置依赖） | **域级 PRD frontmatter `depends_on`**（语义 = 实现前置依赖，**只含**全局 `product/prd/prd.md` §五 mermaid 的**实线**；虚线 = 增强链路 / 数据回流，不入本字段） | 全局 §五 mermaid 域间关系图（实线边集）+ 域级正文「依赖域 / 上游 / 下游」——两者均为**派生视图**；`validate_prd.py` 参数 4「域间依赖」按实线边集对账（悬空引用 / 实线成环 / 不一致 ⇒ FAIL） |
| 技术栈 + 快速启动（A 类，可选） | 项目根 `README.md` 的「技术栈 / 启动」两节 | 不入 spec；`_meta.json.categories` 记状态 |
| 测试现状与运行方式（H 类，条件） | 项目根 `README.md` 的「测试 / 运行」节 | 不入 spec；无则由确认门补 |
| 接口技术契约（D 类的机器可读部分） | 项目自带的机器可读接口描述（OpenAPI / Swagger / …） | `.atlas/spec/structure/*/<domain>/apis.md` 只记真相源入口，不复制端点 |
| testid / selector 约定 | `rings/e2e/reference.md` §4（E2E 环契约；**不在 structure 环**） | 实现期薄桩 `.atlas/spec/conventions/testid.md`（派生视图，由 `scripts/gen_testid_stub.py` 生成）；**实际落点见下一行**；E2E 分片引用它 |
| **产品事实**（全局 + 域级；原称「项目 PRD」，2026-11-22 正名 `RFC-20261122-03`） | `product/prd/prd.md`（全局产品事实）+ `product/prd/<domain>-prd.md`（域级产品事实）——目录 / 文件名中的 `prd` 为历史遗留落点名，语义 = 产品事实（应然登记）；「PRD」一词现唯一指需求类文档 | `product/prd/README.md` 追溯总表；需求收口时按域沉淀回此（FN/R/AC/文案规范表 + 变更记录） |
| **机制叙事文档**（「这个机制怎么转」的单主题指南，一篇一机制；与 ADR 分界 =「怎么转」归此、「为什么这么定」归 ADR） | 仓库自定落点（惯例 `docs/architecture/<机制>.md`）；发现面 = frontmatter `mechanism-paths:` key 全仓扫描（**永不入 `.atlas/spec/`**——会撞注入截断并打破结构环「仅三类文件带 paths:」规范句，`RFC-20261122-04`） | `atlas workflow verify` **申报判决门**（触及未跟改未申报 ⇒ FAIL rc1+扣预算 `mechanism_undeclared`；`mechanism-paths` 词表两档非法 ⇒ FAIL `mechanism_paths_invalid`；判决前置审查带；申报面 = 卡目录 `mech-declares.md`，`RFC-20261123-01`）+ 审查后 WARN 提示族残部（疑似死 paths / 词表点名 / 死测试锚 / 申报死行；`pending` 覆盖豁免；`RFC-20261122-04/07`）；写法纪律（骨架不内联 / 两档 glob）落采纳仓手写区 |
| workflow 尝试记账（失败分类学，`RFC-20261122-07`） | `.atlas/tasks/<id>/attempts.jsonl`（append-only，行内带 `unit`；cause 封闭词表 + 退出码分配 + 预算缺省值单源 = `_support/workflow_causes.py`；写入面 = verify/finish 失败路径与预算拒绝路径，单写者） | `atlas workflow status` 聚合 charged/uncharged/坏行（含归档卡；`--json` 逐卡 `attempts`） |
| workflow 存量缺陷登记（deferred，`RFC-20261122-07`） | `.atlas/tasks/<id>/deferred.md`（D154 状态闭集 `开放｜已修·待复验｜已出库`；fingerprint 幂等，无 fingerprint 回退键 = target+check+detail 摘要哈希；写入面 = `workflow_finish.extract_deferred_findings`，**finish 门判定之前**——阻断中的存量病案也要落账） | `atlas workflow status` 聚合「开放」计数；收口/阻断时出声「登记 N 条（其中阻断中 M 条）」 |
| testid **实然**集合（现状） | 前端源码的 `data-testid` | `validate_testids.py` 按 `stack-profile.yaml` 的 `apps[].kind ∈ {frontend, fullstack}` 路径扫描（E1 统一，不再按 `origin` 分流）；与**应然**（下一行）的按页差集 = 待实现面 / 漂移面 |
| E2E 用例 | `product/e2e/e2e-index.md`（唯一入口）+ `product/e2e/cases/<page>.md`（分片） | 脚本由分片生成 |
| 页面标识（slug）与「页 ↔ 真实路由」映射 | `product/e2e/e2e-index.md` 页面表（e2e 环，E1 迁入） | slug = 分片文件名；页面表是 E2E 生成器 URL 的唯一来源（`rings/e2e/reference.md` §3.1） |
| testid **应然**集合 | `product/e2e/cases/*.md` 分片的 `testid:`（e2e 环，E1 迁入） | 用例分片隐式决定元素清单与初始态；**实然** = 前端源码 `data-testid` 扫描，执行即对账 |
| **前端复用决策记录** | 任务卡 Plan / dispatch.md（执行层；`.atlas/tasks/<NN-slug>/`） | `.atlas/shared/frontend-reuse.md` 只定义流程与记录字段；PRD / E2E / apply 不复制正文；Atlas 不持有索引或数据 |
| **独立审查的骨架条款** | `.atlas/shared/independent-review.md`（共享契约） | 三类实例（PRD / E2E 用例 / 设计决策）**按名引用**；各实例**只**声明自己的**维度 / fan-out 单位与阈值 / 回退环取值 / 权威输入** |
| **独立审查报告**（设计期语义门） | `product/<环>/reviews/<日期>-<范围>/`：`README.md`（人读三段式）+ `review.json`（机读 `{ok,status,checks[]}`）+ `inputs/MANIFEST.json`（指针化输入清单） | 门禁读 `review.json` 的 `status`；**审查意见不进被审对象正文**（记录类 / 交付面分离） |
| **人工缺口清单 / 修订批次**（无需求卡的应然资产修订） | `product/reviews/<日期>-<主题>/`：`README.md`（缺口清单 + 决策表 + 验收标准）+ `plans/`（分域修订方案） | 与上一行**不同角色**：上行是机器 / 独立审查产出，本行是人机协同收集的修订批次（`3507 P2`） |
| **项目级长效架构决策 (ADR)** | `product/adr/`（唯一权威，按 `NNNN-<slug>.md` 编号） | 域级 PRD 引用架构决策编号；单需求内微观取舍归域级 PRD；修订批次细节归 `product/reviews/` |
| **独立审查校准账本** | `product/reviews/calibration.jsonl`（**append-only**，跨实例共用） | 三条指标：一致率 / 漏报率 / 分歧率；形态与回退规则见 `shared/independent-review.md` §7 |
| **运行目录（`.atlas-run/`）文件归属清单** | `rings/e2e/reference.md` §7.1「运行目录二分」表 | `shared/global-rules.md` §17 只写通则、不复制清单；改进 / 诊断 / 执行类消费者按表定读取面 |

## 3. 迁移纪律（真相源搬家 = 一等事件）

> **迁的不只是文件，是「谁说了算」**。每次迁移必须：① 在本文件 §1 登记表更新权威落点；② 跑**迁移仪式** = **完备性对账**（**新源 ⊇ 旧源迁移基线集**：旧源迁移时已有的每一项，新源必须都有对应）；③ 旧源**删除**（无冻结档，`3507 AT`；历史归 git，历史迁移条目归台账 `3509 §95`）。

- **旧源不得同时被消费**：迁移完成后，旧源若仍被 atlas 读 ⇒ 判为漂移（与 §2 的「同一信息两处正文」同罪）。
- **存量豁免条款（`RFC-20261122-03`，2026-11-22）**：#71 需求原文真相源（卡目录 `work/需求PDF-全文.md`）迁往需求落点的迁移按**需求增量切换**——迁移基线集 = 改判日后开工的需求；**存量卡级源随卡 archive 归档自然清退，清退完成前该卡条目以卡内源为权威**（verify 判据双词表显式识别旧格式卡并按旧判据处理），并存期为有边界的例外而非漂移。
- **待迁项（未完成）**：**E0 产物面残留**（`product/e2e/scripts/` 的 `_ATLAS_TARGET_IS_PROTOTYPE`/`_MOCK_NS`、已删功能的 testid、索引存量行仍 `prototype-pass`）—— 绑定**真跑准备日**（= 协议定形首跑准备日，升档规则见 `shared/gates.md` 上限声明与 `DESIGN.md` D79 ①）重生成一次清（`3509 §B115`）。**已完成**：`product/prototype/` 于 2026-09-30 删除（`3507 AT`）。

## 4. 约束

- 同一信息若在两处出现正文，判为**漂移**：保留真相源那份，另一处改成引用。
- 结构事实的**唯一落点是 `.atlas/spec/structure/`**——不再有 `product/structure/`。执行层 任务通过路径注入原生消费它；PRD / E2E 按需 Read。
- 编码规范（原 I 类）与 testid 约定（原 G 类）**不在 structure 环**：testid 约定正文归 **E2E 环契约** `.atlas/rings/e2e/reference.md` §4；编码规范不由 atlas 收口。Atlas 管实现期纪律与可追溯性；业务代码规范仍归项目 linter/typecheck。
- 编号体系（功能 / 规则 / AC / 用例）全产品唯一、不复用；格式见各环契约。
- **独立审查的骨架条款唯一在 `shared/independent-review.md`**（2026-09-26 补）：四类实例不得把骨架（只审不改 / 独立结论 / 分级 / 留痕双份 / 硬口径 / 门禁 / 成本约束）复制进自己的环契约，只能**按名引用**并声明自己的维度与取值。发现两处骨架正文即判为漂移。
- **`data-testid` 的应然归用例分片，实然归前端源码**（2026-09-26 立，2026-09-28 按 E1 改写）——真相源分层：**应然** = `product/e2e/cases/*.md` 分片的 `testid:` 清单（实现按它命名、不得自造，`rings/e2e/reference.md` §4.1）；**实然** = 前端源码 `data-testid` 扫描。旧项目接入时前端通常**没有** `testid`，按分片应然写用例得到的是「待实现面」差集——**不得**把旧代码的 CSS 选择器 / DOM 结构拓成应然。
- **项目级长效架构决策唯一在 `product/adr/`**（2026-10-13 登记）：跨需求的全局长效技术决策落 `product/adr/NNNN-<slug>.md`；单需求内的业务实现细节归域级 PRD；无需求卡的人工修订批次归 `product/reviews/<日期>-<主题>/`。任何技术决策一旦落盘即为生效契约，推翻时新建并标记 `superseded`，严禁在别处复制正文。
- **前端复用决策记录归 任务卡 Plan / dispatch.md**（2026-10-31 登记，D177）：能力 / 参考实现 / 决策 / 缺口 / 验证只在任务 Plan / Design 保留一份；`.atlas/shared/frontend-reuse.md` 是**执行期程序契约**（非门、非真相源），不持有记录、不生成组件索引、不参与门禁。
- **需求原文优先序与条目覆盖**（2026-11-21 登记，`#71/#72/#73`；2026-11-22 落点化改写，`RFC-20261122-03`）：权威源排序 = **需求原文（转换稿） > 需求 PRD（确认稿） > 任务 PRD > 设计文档 > 代码惯例**——确认稿是原文的协商派生承接，与原文冲突时**原文优先**；正式名与用户可见文案（标签 / placeholder / 按钮 / 提示语）必须**引用**来源章节，不许自拟、不许复制简写；文档间矛盾登记冲突并按 `global-rules.md` §15 上报，**不许就地二选一**。
  - **落点模式（`--requirement` 指向需求落点）**：条目正文唯一住址 = 落点 `items.md`（`ID | 页码 | 章节 | 原文（逐字）`，限定语保留，表行数 = 总数自检）；卡侧 `requirement-items.md` = **领取引用表**（`ID = 落点条目 ID`，`来源 = <落点路径>#<落点ID>`，**不复制正文**），卡 `prd.md` §1 正文指针化；条目↔卡 = **at-least-once 共担合法**，`verify` 跨卡按 ID 覆盖性对账（漏领 / 幽灵引用 / 状态机不一致 ⇒ WARN）。
  - **直填模式（`--requirement` 指向普通文本 / 无落点）**：旧路径保留——开工前置产物两件落任务卡目录（plan 自动生成骨架，重跑不覆盖已填）：`requirement-items.md`（条目表：`ID | 页码 | 章节 | 原文`，原文逐字、限定语保留，文末声明总数，表行数 = 总数自检）+ `coverage-matrix.md`（**需求条目覆盖矩阵**：行 = 条目 ID，列 = PRD / 设计文档 / 实现 / E2E，格值 = 覆盖（位置）/ 不涉及（理由）/ `UNRESOLVED`；与产品事实环 §8 追溯覆盖矩阵、`RFC-20261111-04` 派生覆盖矩阵三者互不替代）。矩阵留空格 / 含 `UNRESOLVED` ⇒ `atlas workflow verify` **WARN**（判据 = `_support/workflow_verify.py`，纪律面起步；升格 FAIL 条件 = 出现第一个 WARN 被放行后的实际漏单，另案）。
  - 两模式判据兼容：verify 表头词表 = 原文 / 来源 双词表，旧格式卡按直填判据处理（存量豁免见 §3）。
- **机制叙事文档触及申报判决门 + 提示族残部**（2026-11-22 登记 `RFC-20261122-04`；2026-11-23 升格 `RFC-20261123-01`）：**判决门**（verify 前置判定带，审查启动前）：暂存区 diff `--no-renames`（剔除 `.atlas/` 前缀——卡产物自身不触发触及）× 各篇 `mechanism-paths:` 交集 ∧ 篇未跟改（∉ 暂存）∧ 卡内无该篇 `not-involved: <理由>` 申报（`<tasks_root>/<unit>/mech-declares.md`，文法 fail-closed：合法行 = 空行 / `#` 注释 / `- <篇>: not-involved: <非空白理由>`，其余非空行 ⇒ FAIL 点名行号）⇒ FAIL rc1 + 扣预算 `mechanism_undeclared`；篇 globs 词表非法 ⇒ FAIL `mechanism_paths_invalid`（两档逆紧：字面路径 / `dir/**`，裸 `**`、中段 `**`、单星、`?` 自此拒收；`pending` 篇豁免覆盖判定不豁免词形）；FAIL 无点名上限，文案带可复制申报行 + 解析后精确落点（run 子卡场景）。**提示族残部**（审查通过后 WARN，红轮不可见 = 既有语义不变）：疑似死 paths（globs 对 `git ls-files` 零命中——治 paths 自身静默死）+ 词表非法点名 + 死测试锚（判据行 `〔测:…〕` 锚指向的 `tests/` 文件不存在 ⇒ WARN；形态非法（非 `tests/` 前缀/越界）点名；`pending` 篇仍判——锚存活与 paths 无关；**节点级存在性不机器判**（防 verify 挂测试收集器），`RFC-20261122-07`）+ 申报死行（申报指向零发现篇 ⇒ WARN）；`pending` 冷启动豁免（覆盖面）；提示族点名上限 5。**升格兑现如实记**：RFC-04 评审升格条件 =「留样张误报率数据 + 实际漏单」——本次以**设计变更兑现**（申报豁免阀使「文档跟改了还被拦」的冤枉态结构性消失；playground 装配态实测 2026-11-23 检出 2/2、误报 0/3 为合成夹具样本，不充当误报率数据），非数据兑现；触及提示 WARN（「查看该机制篇是否跟改」）同日退役——它是「去看一眼」不判「不同步」（篇 ∈ 暂存照样出声，playground B1 实证），直接翻转即 100% 误拦；门上线后 FAIL/申诉数据接棒留样张纪律。
- **机制叙事文档写法纪律（正本，随装配分发）**（2026-11-22 登记，`RFC-20261122-04`）：纪律是机制文档功能的**使用说明**而非采纳仓特有约定，正本住本装配面随 install/upgrade/update 分发（换仓自动有）；采纳仓手写区可重复为**可选可见性强化**（推不到、可漂，非正本）。四条：①**一篇一机制**——「这个机制怎么转」的跨文件叙事才写文档（惯例 `docs/architecture/<机制>.md`）；代码查得到的事实不手写（交结构事实源），「为什么这么定」进 ADR；②**骨架不内联**——端口 / 配置键 / 服务清单指事实源或配置真身，正文只写读代码拼不出的部分（机制重设计才过时，日常改码不漂）；③**两档 glob**——`mechanism-paths:` 字面路径优先，`dir/**` 仅当确实叙述整棵子树（理由旁注写在 globs 列表**末行**，`#` 注释插条目中间会中断解析），单星 `*` 拒收；未定 paths 的新篇写 `pending`；④**改机制链必看篇**——verify 触及现为申报判决门：跟改该篇一并暂存，或在卡目录 `mech-declares.md` 申报 `- <篇路径>: not-involved: <理由>`，否则 FAIL（判据见上一条与 §1 登记行）；⑤**判据行带测试锚（可选但存活，`RFC-20261122-07`）**——行为/判据陈述行建议行尾 `〔测:tests/<file>.py::<node>〕` 锚（死锚由 verify 提示族 WARN 出声；「新增行必带」的升格须两代任务跑实证 ≥2 例行为陈述漂移漏检后另案）。
