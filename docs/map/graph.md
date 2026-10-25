# L1 · 代码图谱子系统

> 子系统 #4 / 上级地图:[index.md](index.md) / 锚定版本:v0.2.0-beta.6(2026-10-24)
> 一句话:**全仓唯一接触外部代码图谱工具的隔离层(ACL)+ 两个上层消费者(影响面报告 / 收口对账)**。聪明逻辑归 atlas 自有脚本,图谱后端只当「哑索引 + 查询接口」。

## 它不是什么

- 不是适配器本体:`_graph.py` 不被 `stack-profile.adapters` 解析(`adapters/_graph.py:37` 自述),它是图谱后端(cgc)的全线唯一接触面。
- 不是必选项:项目不声明 `graph` 段 ⇒ 整个子系统静默不启用(报告器 exit 3 `not_ready`,apply 显式跳过不阻断)。
- 不做影响面语义判断:它给的是 **name 级静态调用面(偏宽、保守,无边 ≠ 无人用)**,是 apply 影响面推导的「结构证据约束」输入,不替代 agent 语义判断(`apply/reference.md:124`)。

## 文件清单

| 文件 | 行数 | 角色 |
|---|---|---|
| `adapters/_graph.py` | 392 | ACL 本体:profile 声明解析 / 后端探测 / 新鲜度与索引 / 四个查询接口 |
| `scripts/impact_report.py` | 224 | 消费者①:按需求出影响面预测报告(BFS 分层) |
| `scripts/impact_reconcile.py` | 149 | 消费者②:收口时预测集 ⇔ 实际 diff 双向对账 |

配套契约:`shared/stack-profile.md` §2(`graph` 段 schema)与 §3.6(影响面报告契约);`shared/gates.md` 2.1 的 `impact_reconcile` 行。落点纪律:全部中间产物落项目根 `.adapter-out/`(运行态,`.gitignore` 应含该行——project-wiring 补丁第 5 触点自动追加)。

## 核心机制

### 1. 声明:stack-profile 的 graph 段

`product/stack-profile.yaml` 可选段,`load_graph_config`(`adapters/_graph.py:104`)解析:

```yaml
graph:
  backend: cgc       # 词表 GRAPH_BACKENDS = ("cgc",),见 _graph.py:53
  pinned: "0.6.13"   # 可选;与实装失配 ⇒ 显式 WARN 不阻断(_graph.py:159)
```

段缺失 / `graph: null` / 空段 ⇒ 返回 None(不用图谱)。注意 `_yaml_scalar` 的 null 家族已收窄为 YAML 口径(`null`/`~`/空)——裸 `none` 是合法字符串(D80 时代的教训:profile 新 mode 值曾被吞成 null)。

### 2. 后端探测与降级纪律

`detect()`(`adapters/_graph.py:143`):找 `cgc` 可执行 + 解析版本号;不可用 ⇒ 返回 None,由**调用方**决定响亮降级——适配器显式 WARN + 回退正则、报告器显式 `not_ready`。本层绝不静默(`_graph.py:27-29`)。子命令超时三档:VERSION 15s / QUERY 120s / INDEX 900s(`_graph.py:57-59`)——「宁可响亮超时,不可无限等待」。

### 3. 用前现刷(freshness)——本子系统最核心的设计

`freshness_key()`(`adapters/_graph.py:181`)算**代码态指纹 = sha1(HEAD + 脏文件集)**,排掉 `.adapter-out` 自身(否则「写标记 ⇒ 键变 ⇒ 再索引」自激振荡)。`ensure_index()`(`adapters/_graph.py:226`)消费前先比对:

- 键一致 ⇒ 微秒级直接返回(fresh);
- 不一致 ⇒ `cgc index --force` **全量重建**,成功后写标记 `.adapter-out/_graph_index.json`;
- 非 git 工作树 ⇒ 空键 + WARN,每次全量重建(绝不拿无法验证的索引装新鲜)。

**为何不用 `cgc update` 增量**(B191-2 实测收口):update 语义 = 只加不减,删除的符号会残留成幽灵调用方 ⇒ `callers` 对已删代码静默答错 ⇒ 影响面虚高。切换条件写死在 `ensure_index` 的 docstring(`_graph.py:238-240`):后端升级后复测「新增追平 + 删除追平」两例全过才准改 update。

### 4. 查询接口(4 个,全部确定性)

`adapters/_graph.py:299-392`:`query`(裸 Cypher,调用方负责 ORDER BY)、`file_paths`、`symbols_in_files`、`callers`(一跳直接调用方)。纪律:接触面只走 CLI 不走 Python import;`COLUMNS=20000` 防 rich 渲染硬换行 JSON(`_graph.py:274`);根外路径丢弃(cgc 全局库可能跨仓,不得污染);Python 侧再排一次序兜底(`_graph.py:391`)。

### 5. 消费者①:影响面报告 `impact_report.py`

`apply <需求ID>` 影响面推导前跑(契约 `apply/reference.md:122-131`):

```
python3 .atlas/scripts/impact_report.py --root . --task <需求ID> --symbols/--paths/--diff-base …
```

链路:种子符号收集(`collect_seed_symbols`,impact_report.py:71)→ 沿 CALLS 边 BFS 分层(`bfs_layers`,impact_report.py:102)→ 渲染 `.trellis/tasks/<ID>/impact.json|md`(`render`,impact_report.py:134)。用前现刷、确定性可复现;未声明 graph 段 ⇒ exit 3 `not_ready`(impact_report.py:42),apply 记录后跳过、不阻断。

### 6. 消费者②:收口对账 `impact_reconcile.py`

收口时对「预测集 vs 实际改动」双向差集(gates.md 2.1 行,B191-1):predicted = `touched_files ∪ inputs.paths ∪ ⋃ layers[].files`;漏报(miss)/多报(over)⇒ WARN 逐文件指名,基准漂移(head 或 diff-base 变了)⇒ WARN 点名两个基准——**不得静默对账**。台账 `impact-reconcile.json` 无条件落盘,是 miss 升 FAIL 触发(连续 3 单 miss=0 且无重复)的观察数据源。报告缺失 ⇒ exit 3 SKIP(显式,不是通过)。

## 对外接口(谁咬它)

| 消费方 | 触点 |
|---|---|
| apply 影响面推导 | 先读 impact 报告再做语义判断(`apply/reference.md:124`) |
| atlas_check | 不直接调图谱;只读 `.adapter-out/` 同址产物(漂移门 / F41 三消费者同址钉) |
| validate_stack_profile | 只判 `graph` 段**声明形态**(键白名单 + backend 枚举),不判 cgc 真装没装 |
| 适配器 | 显式 WARN + 回退正则(后端不可用时) |

## 显式盲区

- **JSX/前端引用边为零**(实测):图上 `[:CALLS]` 边对前端组件基本无收益 ⇒ routes 通道恒等、impact 通道组件叶失真。口径分两通道,**别写「前端零收益」**(曾实测两轮)。
- name 级匹配:同名多定义并入 ⇒ 影响面偏宽。收口以实际 diff 为准(reconcile 收口)。
- 单进程假设:`ensure_index` 无并发互锁,并行消费会各做一次全量重建(后写者胜,只白烧时间)。

## 演化锚(为什么长这样)

| 决策/事实 | 内容 |
|---|---|
| 图谱批 0(2026-10-05) | 薄后端厚自有 / 用前现刷 / 只走 CLI / 确定性四大设计共识定形 |
| B191-2(2026-10-07) | `cgc update` 增量不可信(只加不减),维持 `--force` 全量 |
| issue #8(2026-10-15) | 中间产物统一落项目根 `.adapter-out/`(此前同名两处,门与现场自相矛盾) |
| D78(2026-10-15) | 前端收益实测两轮确认分通道口径;三决议落地 |
| 后端 | cgc(CodeGraphContext,PyPI `codegraphcontext`),pin 0.6.13;前身 Axon 已替 |

## 讲述时的三个抓手

1. **换后端只改一个文件**:`_graph.py` 是全线唯一接触面——这就是 ACL 的价值演示。
2. **新鲜度是消费行为自带的属性**:不靠 hook 不靠守护进程,过期状态在消费时构造性不存在。
3. **预测要被对账**:影响面报告不是终点,收口时 reconcile 双向差集 + miss 升 FAIL 观察窗——「机器预测也要被机器审计」的实例。
