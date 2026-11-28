# L1 · 语义透镜子系统

> 子系统 #4 / 上级地图:[index.md](index.md) / 锚定版本:见 index.md 锚定版本行
> 一句话:**轻量语义透镜(Scope-Aware FRAS)辅助层 + 两个上层消费者(影响面候选面 / 收口对账)**。外部 AST 图谱已退役(D202),`_graph.py` 收敛为「读两级 cognition.fras 语义行、反向一跳反查」的极简辅助层。

## 它不是什么

- 不再是外部图谱的 ACL:cgc/FalkorDB 引擎与容器依赖已清除(D202 supersedes D77/D78);PATH 上恰好装着 cgc 时 `callers` 走旧查询(兼容 shim),不装即零外部依赖。
- 不是适配器本体:`_graph.py` 不被 `stack-profile.adapters` 解析;`graph` 段已退役——声明即 WARN 提示移除(`validators/validate_stack_profile.py:220`),存量合法不阻断。
- 不做影响面语义判断:反查给的是 R 边单跳候选(advisory 基准),不替代 agent 语义判断;透镜行本身由 AOCI 管线/人工增量维护,atlas 只读不产。

## 文件清单

| 文件 | 行数 | 角色 |
|---|---|---|
| `adapters/_graph.py` | 341 | 透镜辅助层:FRAS 行解析 / 反向一跳 / cgc 兼容 shim / 遗留声明解析 |
| `scripts/impact_report.py` | 222 | 消费者①:aoci_candidates 候选面 + not_ready 三态 |
| `scripts/impact_reconcile.py` | 149 | 消费者②:预测集 ⇔ 实际 diff 双向对账 |

配套契约:`shared/stack-profile.md` §2(`graph` 段退役横幅 + 两级透镜落点)与 §3.6(接触面现行为文档);impact 对账门行见 `shared/gates.md`。落点纪律不变:中间产物落项目根 `.adapter-out/`(运行态,接线第 5 触点自动追加 gitignore)。

## 核心机制

### 1. 两级透镜行(输入,atlas 只读)

`.atlas/spec/structure/global/cognition.fras`(跨切面共享基础设施:axios/auth/hooks/router 等)与 `.atlas/spec/structure/current/<域>/cognition.fras`(业务域内),另兼容仓根 `aoci.code.txt`。紧凑行格式 `路径[TAG]: F:… | R:code:x.py,… | A:… | S:…`,`read_cognition_fras`(`adapters/_graph.py:277`)解析;只 R 边参与反查。生产在 atlas 环外(AOCI 管线/人工增量维护);单源分工:apis/models 维持实体事实,FRAS 专管穿透拓扑(R)与防改崩硬约束(S)。

### 2. 反向 1-hop 反查(唯一的图查询)

`reverse_1hop_callers`(`adapters/_graph.py:270`):扫全部透镜行,收集 R 边指向目标文件集的源文件,排序去重返回。单跳、path 级、无深度展开——「一跳就停」是刻意保守:多跳传递面归 agent 语义判断,机器只给证据不替人拍板。

### 3. 影响面候选面(消费者①)

`main()`(`scripts/impact_report.py:174`)主流程:收种子/触达集 → 反查一跳 → **aoci_candidates 独立字段**(`scripts/impact_report.py:187`),单层 L1,不进 predicted 对账集(gates.md:57 口径)。无透镜 ⇒ exit 3 `not_ready`(`scripts/impact_report.py:190`),影响面基准退化为需求卡声明集;`backend: scope_aware_fras`(`scripts/impact_report.py:197`)如实标记新口径。

### 4. 收口对账(消费者②,不变)

`impact_reconcile.py`:预测集 ⇔ 实际 diff 双向差集,漏报/多报/基准漂移 ⇒ WARN 逐文件指名,不得静默对账;台账 `impact-reconcile.json` 无条件落盘,miss 升 FAIL 观察窗(D79④)。

### 5. cgc 兼容 shim(过渡件)

`callers`(`adapters/_graph.py:249`)双轨:PATH 有 cgc 走旧 CALLS 查询,否则 FRAS 反查。`GRAPH_BACKENDS`(`adapters/_graph.py:29`)词表常量保留防外部加载断裂;`freshness_key`(`adapters/_graph.py:29`)仅 shim 路径消费。退役的是依赖,不是兼容。

## 对外接口(谁咬它)

| 消费方 | 触点 |
|---|---|
| apply 影响面推导 | 先读 impact 报告再做语义判断;无透镜 = not_ready 如实记录 |
| validate_stack_profile | `graph` 段判声明形态 + 声明即退役 WARN |
| atlas_check | 不调透镜;只读 `.adapter-out/` 同址产物 |
| 收口流程 | reconcile 对账门(`shared/gates.md:57`) |

## 显式盲区

- 透镜行的 R 边语义机器不判:漏写 ⇒ 反查漏报,靠 reconcile WARN 兜底;S 约束暂无机器消费面(执行层立项时按消费面反推)。
- cgc shim 双轨口径不同(CALLS 边 vs R 边),两轨结果不可混对账;同仓两轨并存时以 FRAS 为主口径。
- `shared/stack-profile.md` §3.6 正文仍以 shim 现行为主叙事(横幅已标退役),主口径以 §2 退役横幅与本章为准。
- 透镜行覆盖度无门:维护多少反查多少,不维护就 not_ready——诚实缺省,不是缺陷。

## 演化锚(为什么长这样)

| 决策/事实 | 内容 |
|---|---|
| 图谱批 0(2026-10-05) | 薄后端厚自有 / 用前现刷 / 只走 CLI / 确定性四大共识(shim 时代遗产) |
| D78(2026-10-15) | 前端 JSX 调用边为零的实测与分通道口径——后成 D202 退役的直接证据 |
| D202(2026-11-19) | cgc/FalkorDB 退役;两级 FRAS 透镜 + aoci_candidates 立项(supersedes D77/D78) |

## 讲述时的三个抓手

1. **退役 ≠ 删子系统**:换的是「图的来源」——从外部 AST 引擎换成仓内语义行;消费者与对账门原样保留。
2. **诚实三态**:没有透镜行就 not_ready,预测集退化声明集——「不预填、不装有」的又一实例。
3. **一跳就停**:反查只给候选,多跳语义归 agent——机器给证据、人做判断的分工样板。
