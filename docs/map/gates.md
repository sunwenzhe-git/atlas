# L1 · 门禁与校验子系统

> 子系统 #8 / 上级地图:[index.md](index.md) / 锚定版本:v0.2.0-beta.7(2026-10-24)
> 一句话:**「每道机器门都要真的会咬」的执行体系**——10 个校验器 + 1 个编排器 + 1 本门册总账 + 变异证明协议 + 42 个出厂测试文件。判据分散在各校验器实现,编排器只聚合不改判。

## 设计三律(门册元规则,`shared/gates.md:3-9`)

1. **注册义务**:不在 `gates.md` 登记表 = 不存在。新增自动门先登记再上线。
2. **假绿测试义务**:每道门必须配「喂坏输入必红」的证明(M 系变异钉),补不齐登记为缺口,不得留空装作有。
3. **响亮原则**:坏输入必须显式失败或显式 SKIP + 原因。**静默继续 = 门失效**。

## 文件清单

| 文件 | 角色 |
|---|---|
| `scripts/atlas_check.py`(940 行) | 统一检查入口 / 编排器(**只聚合,不改判据**) |
| `validators/`(10 器) | 判据本体,每器一行输出 |
| `shared/gates.md`(149 行) | 门登记总账:六列(门 / 对账平面 / 查什么 / **不查什么** / 预算 / 假绿测试等级) |
| `scripts/mutation_proof.py`(155 行) | 变异证明工具:把缺陷放回去看门红不红,还原须逐字节一致 + 报告须含注入 diff |
| `tests/`(42 文件) | 出厂测试套件(`check-all.py --only atlas` 全绿为出厂条件) |

## 编排器 atlas_check 的结构

调用:`python3 .atlas/scripts/atlas_check.py [--root .] [--page <slug>] [--fast] [--json]`。一门一行 `ok|FAIL|WARN|SKIP|N/A <名称> <摘要>`;任一 FAIL ⇒ 退出码 1,WARN 不影响退出码(`scripts/atlas_check.py:1-22`)。

### 四态语义(`3509 §B110`)

`SKIP` = 未走到 / 前置未声明(**不是通过也不是失败**,必须带原因)≠ `WARN`(过期/提醒,不置红)≠ `FAIL`(硬阻断)≠ `ok`。生成物门三态:未就绪(SKIP)≠ 生成物过期(WARN)≠ 生成失败(FAIL)。

### 门行全景(`main()`,`scripts/atlas_check.py:850`)

| 门行 | 实现 | 一句话判据 |
|---|---|---|
| 10 个 validate_* | `check_validators` :203 | 逐器调用,一门一行;前置文件缺失 ⇒ SKIP(`_gate_preconditions` :68 定义 7 器的三态前置) |
| 对齐测试(.atlas/tests) | `check_factory` :244 | 装配副本跑 pytest;目录不存在 = 装配未含测试(F53 三形态 SKIP) |
| 生成物最新 | `check_generated` :275 | gen_e2e_scripts 干跑 diff;exit 3 = not_ready SKIP |
| 审查报告形态 | `check_review_report` :356 | 最新 E2E 审查报告复算(validate_review_report 单源) |
| 执行串行 | `check_serial_execution` :246 | 运行器配置必须 `workers: 1` + `fullyParallel: false`(D115) |
| 结构漂移 | `check_drift` :373 | 只读 `.adapter-out/_drift.json` 标记,不做二次判定 |
| 装配版本 | `check_version` :435 | `.atlas/VERSION` 摘要戳 + `.atlas/MANIFEST.json` 逐文件基线 ⇔ 当前源包重算(D145);历史坏戳单列根因级 WARN |
| 写面残留 | `check_write_claims` :559 | glob 未释放 claim ⇒ WARN 指名(提醒面,不是门禁) |
| E2E 真跑 | `check_e2e` :589 | 单段执行:TCP 探活 → e2e.reset → 运行器可解析性判据 → 浏览器就绪探针 → 真跑;结果 JSON 供控制台/失败留证 |

**辅助机制**:失败详情落 `.atlas/runs/last-check-error.log`(全绿轮自动清);每轮观测事件追加 `.atlas/runs/check-events.jsonl`(门名/状态/耗时,**观测面不参与判定**);成功真跑写 `.atlas/runs/e2e-summary.json`(带 git_head/dirty 溯源)。

## 10 个校验器(判据本体)

| 校验器 | 对账平面 | 核心判据 |
|---|---|---|
| `validate_stack_profile` | 项目声明 ⇔ 共享契约 §2 | 字段契约 / origin 枚举 / graph 段 / app_login 三态 |
| `validate_structure` | structure 产物 ⇔ 环契约 | `_meta.json` 形态 / routes 语义列留空 WARN / D 类接线态 / adapter_gaps 可见化 |
| `validate_prd` | PRD 产物 ⇔ 环契约 | 功能→规则→AC 链路 / 域间依赖 mermaid 实线边对账 / 变更记录 5 列 |
| `validate_testids` | testid 应然(分片)⇔ 实然(源码) | 按页双向集合相等;模板字面量展开;应然落点分档 |
| `validate_e2e_index` | 索引 ⇔ 分片 ⇔ 契约 | 结构门 + 有意义门 + seed×models + AC 反向覆盖 |
| `validate_e2e_mocks` | 打桩声明 ⇔ mock 契约 | mock 段形态矩阵 |
| `validate_ac_alignment` | 后端测试 ⇔ PRD AC | 无主 AC / 无效跳过 / 双向覆盖 / 差量防退化 / 后端维度（D153） |
| `validate_design_exemptions` | 设计档案豁免 ⇔ 工具配置 | 双向集合相等(单侧漂移 = 半遮蔽) |
| `validate_adr` | ADR ⇔ MADR 契约 | 编号唯一 / 演进链闭环 / 章节完整 |
| `validate_walkthrough` | 走查门声明 ⇔ 凭据 | 三问第 2 问「是」⇒ 域级 PRD 须有 `> 已确认:日期` 行 |

**门册 2.1 行的「不查什么」列与判据列同等重要**——每道门的显式盲区都写在那里,讲述时这是「我们知道门守不到哪」的诚信面。

## 变异证明协议(治「假门禁」)

流程四段(治「门会不会咬」):**注入坏输入 ⇒ 门必红 ⇒ 还原逐字节一致 ⇒ 复绿**;报告须含注入 diff(2026-10-17 立:无它则「反向破坏的是不是自述那一处」不可独立复现——M88 夹具教训)。工具 `scripts/mutation_proof.py` 不承载判据,钉子全部登记在门册右列(编号已至 M150 上下)。

同族的「可执行性判据本体」纪律(D101/DR4):可执行/可用类前置判据必须 ① 真跑一次功能性探针 ② 有反面包(「东西在但用不了」必须红) ③ 失败原因不被吞。同族复发两轮才立此行(#1 恒绿门 / #24 路径存在当充要)。

## 三态前置表 `_gate_preconditions`(`scripts/atlas_check.py:68`)

7 个校验器声明了「前置文件缺失 ⇒ SKIP」:stack_profile(无 profile)/ structure(结构环未跑)/ design_exemptions(无设计档案)/ e2e_mocks(无用例资产)/ ac_alignment(无 PRD)/ adr(无 ADR 目录)。**SKIP 是合法降级不是放行**——文案必须带「未就绪,非失败」与出路。

## 显式盲区

- 判据语义对错(「是」判得对不对、断言异源与否)——归独立审查与人。
- `gates.md` 表格列数完整性曾是零门覆盖(批量改表漏 `|` 无门发现),后补入 `test_canonical_consistency`。
- 契约正文的**语义自洽**机器判不了(代码与契约陈述级分叉,只有人看得到——F32 实例)。

## 演化锚

| 事实 | 内容 |
|---|---|
| `3509 §B68` | 「6 条命令收成一条」——atlas_check 诞生动机 |
| `3509 §B110` | 四态语义定形(SKIP ≠ 通过 ≠ 失败) |
| `3509 §B114` | 取证等级五档(出厂级/待复核/真跑级/从未红过) |
| D79(2026-10-15) | 真跑级逐格纪律:无咬合证据不得预填 |
| D101/D124 | 运行器判据本体(可导入性)/ 浏览器就绪探针 |
| D145(2026-10-23) | MANIFEST 逐文件装配基线(配对校验先行) |
| M 系编号 | 已至 M150 上下,全部登记在门册右列 |

## 讲述时的三个抓手

1. **门会咬是证明出来的,不是宣称出来的**:每道门都有「喂坏输入必红」的变异钉子,而且证明本身也有纪律(注入 diff + 逐字节还原)。
2. **四态纪律**:永不当绿灯放行——前置没就绪就明说 SKIP 并带原因,真红假红严格分流(靶场不可达 ≠ 用例失败)。
3. **「不查什么」写进总账**:每道门自带显式盲区声明,诚信面与判据面同权重。
