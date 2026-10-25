# L1 · apply 跨环编排子系统

> 子系统 #6 / 上级地图:[index.md](index.md) / 锚定版本:v0.2.0-beta.6(2026-10-24)
> 一句话:**atlas 里唯一的编排件**——把「一条需求」灌进项目级应然资产;只做编排与顺序,环内逻辑一律引用各环契约,不复制正文。

## 它不是什么

- 不产 PRD 正文 / 用例 / 结构事实 / 业务代码——越界即失败(契约 §11)。
- 不重实现环内步骤:prd / e2e 的增量规程归 `rings/*/reference.md`。
- 不新增 Trellis 状态:只用 planning / in_progress / completed 三态(D64)。

## 文件清单

| 文件 | 角色 |
|---|---|
| `apply/reference.md`(326 行) | 执行契约本体(安装后位于 `.atlas/apply/reference.md`),四模式 / 三问门 / 影响面 / 增量边界全在这 |
| `skills/atlas-apply/` | agent 执行入口(skill 薄桩) |
| `patches/workflow-plan-apply/` | 把 apply 挂进 Trellis 工作流的锚点式补丁 |
| `scripts/write_claim.py`(204 行) | 并发写面仲裁的 claim 钩子(M3,RFC-20261022-01) |
| `tests/test_backfill_contract.py` | backfill 契约符合性钉(弱判据形态面) |

## 四种模式(契约 §1,`apply/reference.md:19`)

| 模式 | 语义 | 一句话记忆 |
|---|---|---|
| `apply <需求ID>` | 需求式跨环增量:`prd → e2e` 顺序,只动受影响集合 | 每条需求的常规路径 |
| `apply adopt` | 既有项目一次性**开户**:只跟 structure 全量 + 域级「开户最小集」PRD + testid 薄桩;**不做全量重述** | 「把基线登记下来,开到能接第一条需求」 |
| `all` | 按序全量:`structure → prd → e2e`(绿地 / 重建基线) | 三环各自全量流程的编排 |
| `backfill` | 回流原语:已裁决的回填条目分组攒批灌回上游(≤10 条/批) | 「回填是常态,不是异常」 |

**需求 ID = Trellis task id;需求卡 = task 的 `prd.md`**。另有第 4 种形态(应然资产自身修订、无需求卡)**不经 apply**——直接按 `prd → e2e` 逐环跑受影响集合,判据 = 「有没有一条需求要接?」(§3.2)。

## 核心机制

### 1. 三问门(§3.1,`apply/reference.md:67`)——这条需求要拉起哪些环

1. 是否**改动既有能力**?(判据 = §4.1 回退测试:整块撤掉新东西,既有的能否一一还原)
2. 是否需要人确认**应然 UI / 流程**?(是 ⇒ PRD 六件套落细 + 用户旅程走查,**确认前不得进 e2e 环**)
3. 是否需要**可重复的验收**?(超出 lint/test 能力 ⇒ E2E 环)

三问全否 ⇒ 合法的「纯加法 / 不启用三环」路径;判定与依据**必须写进报告**(门是语义判断,机器判不了;机器面只做「写下的『是』与确认行」的对账 = `validators/validate_walkthrough.py`)。

### 2. 影响面识别(§4,`apply/reference.md:109`)

agent 语义判断为主 + 结构证据约束;产出结构化清单(`affected_domains / affected_pages / page_change_kind / affected_acs / evidence`),每条证据可定位。声明了 `graph` 段的项目先跑 impact 报告(见 [graph.md](graph.md))。**禁止 regex 判语义**(D61:Autonoma 反例,680 次重试 / $11 / 零用例)。兜底:映射不到域 / 二义 / 性质判不准 ⇒ 一次性汇总问用户(≤3 问),不得自行拍板。

### 3. 增量边界与确认门(§5)

只对受影响集合落笔,**从不整文件覆盖**;整页重建 / 删页 / 全量重生成 / 改 stack-profile ⇒ 先复述待确认内容等用户回复(`global-rules.md` §7)。

### 4. 并发写面仲裁(§5.1)+ claim 钩子

共享表面(e2e-index 等)单写者纪律:动手前 `write_claim.py take --file <路径> --task <ID>`(原子文件 `.atlas/runs/write-claims/<hash>.json`,`O_CREAT|O_EXCL`),收口 `release`;残留由 atlas_check「写面残留」门 WARN 点名。claims 是运行态不进 git。

### 5. Trellis 挂接(§7,`apply/reference.md:238`)

挂载点 = `.trellis/workflow.md` Phase 1 的 `#### 1.6 项目级资产更新(atlas apply)` 步骤 + 面包屑 enforcement 行,由 `patches/workflow-plan-apply/` 锚点式版本化补丁落下(块指纹 = 片段正文 sha256 前 8 位;指纹同 ⇒ skipped,异 ⇒ 整块替换——可重放,不整体覆盖用户的 workflow.md)。失败 ⇒ 停在 planning 输出结构化报告,不得进实现。

### 6. 回写与报告(§8)

执行记录落 `.trellis/tasks/<需求ID>/atlas-apply.md`(幂等覆写),固定七小节:模式 / 三问判定 / 影响面清单 / 各环改动(含写面声明) / 校验结果 / 门控项 / 下一步。apply 在实现之前跑,**不回写** E2E 执行状态(新增用例置 red,green 的回写在真实执行与收口)。

## 单向衔接总图

```
需求卡(prd.md) ──apply──► 应然资产(PRD 增量 + E2E 分片,实现之前)
                                 │ 机器校验
                                 ▼
                    Trellis Execute 实现业务代码
                                 │ after_finish hook
                                 ▼
                    实然事实回写(structure 保鲜,D38)
```

## 显式盲区

- 三问门的**语义对错**机器不判(机器面只对账「已确认行」)。
- apply 自身不跑环内门禁的判据——判据归各校验器,apply 只组织顺序并如实报告。
- 门控态(PRD 待决策非空 ⇒ e2e 只落空骨架)是**如实态不是失败**。

## 演化锚

| 决策 | 内容(`apply/reference.md:310` 决策对应表) |
|---|---|
| D27/F10 | apply 独立 skill;「按需求增量」与「按阶段全量」两模式不合并 |
| D60 | `prd → e2e` 顺序;structure 不参与增量 + 域变更 re-key 唯一例外 |
| D61 | 影响面 = agent 语义 + 结构证据;≤3 问兜底;禁 regex 判语义 |
| D62/D63 | 增量边界与确认门 / all 的幂等与断点续跑 |
| D64/D65/D66 | Trellis 挂接(不加状态)/ 报告落点 / patches 锚点幂等 |
| `3509 §99` | backfill 第 4 模式(2026-09-28):分组 / 攒批 ≤10 / 独立写面 / 闭环钩子 |
| RFC-20261022-01 M3 | write_claim 钩子(2026-10-23);walkthrough 机器面 M1 同批 |

## 讲述时的三个抓手

1. **单向阀门**:需求必须先变成应然资产并过机器校验,实现才能开始——「更新完成后,Trellis 才去实现」。
2. **四模式覆盖全部入口**:新需求 / 旧项目开户 / 全量重建 / 回流补账,没有第五种入口(资产自修订显式不走 apply,防任务树滥用)。
3. **编排件不复制环逻辑**:apply 的 326 行全部是顺序、边界、报告——每个环的正文都在自己的契约里,这是「单一真相源」在编排层的体现。
