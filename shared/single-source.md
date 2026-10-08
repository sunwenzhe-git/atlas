# atlas 共享契约 — 单一真相源登记

> 每类信息的**唯一权威落点**。各环只能引用，不得在别处复制正文。

## 1. 登记表

| 信息 | 唯一真相源 | 派生视图 / 引用者 |
|---|---|---|
| 需求卡 | Trellis 任务的 `prd.md`（`.trellis/tasks/<NN-slug>/prd.md`） | 不另建 inbox 或需求文档 |
| 结构事实（全局层 + 域级层） | `.trellis/spec/structure/`（Trellis 路径注入层） | PRD / E2E 环按需 Read |
| 域清单（候选 / 已定稿） | `.trellis/spec/structure/_meta.json`（机器）+ `tour.md` 域速查（人读）；structure 提议 → PRD 定稿回写 | PRD / E2E |
| **域间依赖**（实现前置依赖） | **域级 PRD frontmatter `depends_on`**（语义 = 实现前置依赖，**只含**全局 `product/prd/prd.md` §五 mermaid 的**实线**；虚线 = 增强链路 / 数据回流，不入本字段） | 全局 §五 mermaid 域间关系图（实线边集）+ 域级正文「依赖域 / 上游 / 下游」——两者均为**派生视图**；`validate_prd.py` 参数 4「域间依赖」按实线边集对账（悬空引用 / 实线成环 / 不一致 ⇒ FAIL） |
| 技术栈 + 快速启动（A 类，可选） | 项目根 `README.md` 的「技术栈 / 启动」两节 | 不入 spec；`_meta.json.categories` 记状态 |
| 测试现状与运行方式（H 类，条件） | 项目根 `README.md` 的「测试 / 运行」节 | 不入 spec；无则由确认门补 |
| 接口技术契约（D 类的机器可读部分） | 项目自带的机器可读接口描述（OpenAPI / Swagger / …） | `.trellis/spec/structure/*/<domain>/apis.md` 只记真相源入口，不复制端点 |
| testid / selector 约定 | `rings/e2e/reference.md` §4（E2E 环契约；**不在 structure 环**） | 实现期薄桩 `.trellis/spec/conventions/testid.md`（派生视图，由 `scripts/gen_testid_stub.py` 生成）；**实际落点见下一行**；E2E 分片引用它 |
| 项目 PRD | `product/prd/prd.md`（全局）+ `product/prd/<domain>-prd.md`（域级） | `product/prd/README.md` 追溯总表 |
| testid **实然**集合（现状） | 前端源码的 `data-testid` | `validate_testids.py` 按 `stack-profile.yaml` 的 `apps[].kind ∈ {frontend, fullstack}` 路径扫描（E1 统一，不再按 `origin` 分流）；与**应然**（下一行）的按页差集 = 待实现面 / 漂移面 |
| E2E 用例 | `product/e2e/e2e-index.md`（唯一入口）+ `product/e2e/cases/<page>.md`（分片） | 脚本由分片生成 |
| 页面标识（slug）与「页 ↔ 真实路由」映射 | `product/e2e/e2e-index.md` 页面表（e2e 环，E1 迁入） | slug = 分片文件名；页面表是 E2E 生成器 URL 的唯一来源（`rings/e2e/reference.md` §3.1） |
| testid **应然**集合 | `product/e2e/cases/*.md` 分片的 `testid:`（e2e 环，E1 迁入） | 用例分片隐式决定元素清单与初始态；**实然** = 前端源码 `data-testid` 扫描，执行即对账 |
| **独立审查的骨架条款** | `.atlas/shared/independent-review.md`（共享契约） | 三类实例（PRD / E2E 用例 / 设计决策）**按名引用**；各实例**只**声明自己的**维度 / fan-out 单位与阈值 / 回退环取值 / 权威输入** |
| **独立审查报告**（设计期语义门） | `product/<环>/reviews/<日期>-<范围>/`：`README.md`（人读三段式）+ `review.json`（机读 `{ok,status,checks[]}`）+ `inputs/MANIFEST.json`（指针化输入清单） | 门禁读 `review.json` 的 `status`；**审查意见不进被审对象正文**（记录类 / 交付面分离） |
| **人工缺口清单 / 修订批次**（无需求卡的应然资产修订） | `product/reviews/<日期>-<主题>/`：`README.md`（缺口清单 + 决策表 + 验收标准）+ `plans/`（分域修订方案） | 与上一行**不同角色**：上行是机器 / 独立审查产出，本行是人机协同收集的修订批次（`3507 P2`） |
| **独立审查校准账本** | `product/reviews/calibration.jsonl`（**append-only**，跨实例共用） | 三条指标：一致率 / 漏报率 / 分歧率；形态与回退规则见 `shared/independent-review.md` §7 |

## 3. 迁移史（真相源搬家 = 一等事件，`3509 §95`）

> **迁的不只是文件，是「谁说了算」**。每次迁移必须：① 在本表登记一行；② 跑**迁移仪式** = **完备性对账**（**新源 ⊇ 旧源迁移基线集**：旧源迁移时已有的每一项，新源必须都有对应）；③ 旧源**删除**（无冻结档，`3507 AT`；历史归 git）。

| 项 | 从 | 到 | 日期 / 依据 |
|---|---|---|---|
| 结构事实 | `product/structure/` | `.trellis/spec/structure/`（Trellis 路径注入层） | D37（方案 C） |
| testid **应然** | 原型（`product/prototype/*.html` 的 `data-testid`） | 用例分片 `product/e2e/cases/*.md` 的 `testid:` | E1，`3508 §92` |
| 「页 ↔ 真实路由」映射 | `product/prototype/README.md` 页索引 | `product/e2e/e2e-index.md` **页面表** | E1，`3508 §92` |
| 页面 slug 规则 | 原型环契约 §4 | E2E 环契约 §3.1 | E1，`3508 §92` |
| 未决台账 | 单卷（`3509` 一卷到底） | **双卷**：未决卷 + 已决归档卷（各带**卷角色**声明） | 2026-09-25 拆卷；2026-09-28 卷角色机器化（`shared/knowledge.md` §9） |
| 门的「假绿测试」与「取证等级」 | 散在纪要卷 / 各门自己的测试 | `shared/gates.md` 的登记表列 | 批 6 首批，`3507 AB` |
| 收口步骤（人侧） | 散在纪要卷的「收口清单加一步」 | `shared/closeout.md` | 批 6 首批，`3507 AB` |
| 设计 token（F 类，实然） | `.trellis/spec/structure/global/design-tokens.md` | 前端样式表本身（源即真相，无副本） | F 类退役直接删除，2026-09-30（用户拍板，`3508 §156`） |

- **旧源不得同时被消费**：迁移完成后，旧源若仍被 atlas 读 ⇒ 判为漂移（与 §2 的「同一信息两处正文」同罪）。
- **待迁项（未完成）**：**E0 产物面残留**（`product/e2e/scripts/` 的 `_ATLAS_TARGET_IS_PROTOTYPE`/`_MOCK_NS`、已删功能的 testid、索引存量行仍 `prototype-pass`）—— 绑定**真跑准备日**重生成一次清（`3509 §B115`）。**已完成**：`product/prototype/` 于 2026-09-30 删除（`3507 AT`）。

## 4. 约束

- 同一信息若在两处出现正文，判为**漂移**：保留真相源那份，另一处改成引用。
- 结构事实的**唯一落点是 `.trellis/spec/structure/`**——不再有 `product/structure/`。Trellis 任务通过路径注入原生消费它；PRD / E2E 按需 Read。
- 编码规范（原 I 类）与 testid 约定（原 G 类）**不在 structure 环**：testid 约定正文归 **E2E 环契约** `.atlas/rings/e2e/reference.md` §4；编码规范不由 atlas 收口。
- 编号体系（功能 / 规则 / AC / 用例）全产品唯一、不复用；格式见各环契约。
- **独立审查的骨架条款唯一在 `shared/independent-review.md`**（2026-09-26 补）：四类实例不得把骨架（只审不改 / 独立结论 / 分级 / 留痕双份 / 硬口径 / 门禁 / 成本约束）复制进自己的环契约，只能**按名引用**并声明自己的维度与取值。发现两处骨架正文即判为漂移。
- **`data-testid` 的应然归用例分片，实然归前端源码**（2026-09-26 立，2026-09-28 按 E1 改写）——真相源分层：**应然** = `product/e2e/cases/*.md` 分片的 `testid:` 清单（实现按它命名、不得自造，`rings/e2e/reference.md` §4.1）；**实然** = 前端源码 `data-testid` 扫描。旧项目接入时前端通常**没有** `testid`，按分片应然写用例得到的是「待实现面」差集——**不得**把旧代码的 CSS 选择器 / DOM 结构拓成应然。
