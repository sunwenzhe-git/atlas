---
title: 逆向（结构）环设计
description: 第一环：读代码产出实然结构事实，落 .trellis/spec/structure/，既是项目级事实又能被 Trellis 原生注入；CGC 代码图谱深度赋能——AST 双通道抽取、调用拓扑候选域聚类、用前现刷、影响面对账。
---

# 逆向（结构）环设计

> **第一环。**读代码产出**结构事实**，直接落 `.trellis/spec/structure/`——同一份既是项目级事实（PRD / E2E 按需读取），又能被 Trellis 任务**原生注入**消费。
>
> 口号：**只做足够支撑下游（PRD / E2E）的上下文**，绝不重做一套文档工厂。契约正文位于 `.atlas/rings/structure/reference.md`，本页是设计依据。

---

## 一、边界

**本环只产结构事实**；PRD、测试用例、需求都不在本环产出，越界即失败。

**与 PRD 环解耦但有序**：本环先跑、**提议候选域**；PRD 读本环产物并**定稿域**。两者**不自动互相触发**。

---

## 二、结构事实：全局层 + 域级层

| # | 类别 | 层 | 落点 |
|---|---|---|---|
| A（可选） | 技术栈 + 启动方式 | — | 项目根 `README.md`（不入 spec） |
| B | 目录与模块地图（含域 → 模块映射） | 全局 | `global/directory-map.md` |
| C | 路由与页面清单（全站总表，带「域」列） | 全局 | `global/routes.md` |
| D（条件） | 接口清单；有机器可读描述时只记真相源入口 | 域级 | `{role}/<domain>/apis.md` |
| E | 数据模型清单 | 域级 | `{role}/<domain>/data-models.md` |
| H（条件） | 测试现状与运行方式 | — | 项目根 `README.md`（不入 spec） |

**约定 / 事实二分**是本环的地基：

- **约定 / 决策类**（A 的选型、B 的语义部分）：人 / Agent 撰写；
- **事实类**（B / C / D / E 里可枚举的部分）：**适配器脚本从代码抽取**，可重复运行、不漂；
- **绿地友好**：没代码就没有事实——事实随代码由适配器补齐，不是「没建完」。

---

## 三、代码图谱（CGC）对逆向环的深度优化

Atlas 把 **CGC（CodeGraphContext，MIT）** 集成为与 Trellis、Playwright 并列的**第三基础设施**，用来攻克「纯正则抽取的盲区」与「静态逆向事实易漂移」两个顽疾。

### 3.1 事实抽取：从正则盲盒 → AST 图谱双通道

- **痛点**：传统适配器靠 `os.walk` + 正则遍历源码。在现代工程（文件式路由、AST 别名导入、动态路由）里经常**抽 0 条**，逆向只好靠 Agent 肉眼通读，浪费大量上下文 Token。
- **薄隔离层**：`.atlas/adapters/_graph.py` 是全线**唯一接触图谱后端**的防腐层——**薄后端、厚自有**，只走 CLI，不 import 内部模块、不直连内部数据库。
- **双通道**：适配器支持 `--backend graph|regex`（默认 `auto`：profile 声明 `graph.backend` 时走图谱，否则走正则）。
- **确定性铁律**：Cypher 查询在代码侧兜底 `ORDER BY` 排序；子进程注入 `COLUMNS=20000`，规避终端默认列宽把 JSON 长文本硬折断的问题；保证同一代码态重跑输出**字节级一致**。
- **响亮降级**：探测不到后端时显式降级为 regex（stderr WARN + JSON 落 `backend_fallback` 字段）；显式 `--backend graph` 而不可用则**硬报错**，绝不静默装绿。

### 3.2 候选域提议：从人工猜测 → 调用拓扑聚类

- **痛点**：逆向第一步要从散乱代码里「提议候选域」供 PRD 定稿。旧版靠目录名启发式猜测，面对扁平目录或跨目录调用时主观且易误判。
- **拓扑聚类**：基于 CGC 导出的调用关系拓扑（`call_edges` / `callers` / `callees`），运行 Leiden 社区检测（固定随机种子 `seed=42` 保障确定性），从真实调用拓扑的高内聚簇自动识别功能模块——**机器计算内聚边界，Agent 裁定领域语义与命名**。

### 3.3 事实新鲜度：用前现刷（Zero-Daemon）

- **痛点**：逆向文档生成后极易随代码演进腐化；若起常驻后台 watcher，watcher 又容易静默挂掉或漏事件。
- **用前现刷**：适配器与刷新脚本调用前强制执行 `_graph.ensure_index()`——比对当前 `git HEAD` 与脏文件指纹，无变化秒过、有变化现刷，用「构造」杜绝过期状态，而不是靠常驻守护进程。
- **全量索引决断**：受控实验证实 `cgc update` 的增量语义**只加不减**（删除已提交文件后仍残留废弃符号），会使调用链与符号表对已删代码静默答错。因此 Atlas 坚决维持 `index --force` **全量重建**（约 17 秒），以绝对确定性保障逆向基准不失真。

### 3.4 逆向事实向下游贯通：影响面推导 + 对账门

- **影响面推导**：基于图谱衍生 `.atlas/scripts/impact_report.py`（沿调用拓扑 BFS 分层反查 L1 / L2 / L3），为后续变更产出 `impact.json` 影响面预测。
- **变异对账闭环**：在 apply / 收口阶段，由 `impact_reconcile.py` 执行双向对账门（预测影响面 vs 实际 `git diff`），漏改或基准漂移显式报警，完成「逆向基准 ↔ 代码实现 ↔ 变更收口」的闭环。

> 图优化的更多工程设计见 [代码图谱 (Code Graph) 逆向](/innovations/code-graph)。

---

## 四、legacy / current 分层

- `current/`：`role: landing` 的 app 的事实（落地实现）；
- `legacy/`：`role: legacy` 的 app（事实来源，重构 / 存量项目才有——没有 legacy app 时整个目录缺席）；
- 域级按 `<domain>/` 分目录，每域两份（apis / data-models）；同域多 app 共用，按 app 加小节。

---

## 五、落点与注入

| 内容 | 落点 |
|---|---|
| B / C（全局事实） | `global/`（pull-only，无 `paths`，由 `tour.md` 链接） |
| D / E（域级事实） | `{current,legacy}/<domain>/`（pull-only，由 `domains/<d>.md` 链接） |
| 注入指针 | `tour.md`（L1，`paths ['**']`）+ `domains/<domain>.md`（L2，域 globs） |
| 域清单 | `_meta.json.domains`（机器）+ `tour.md` 域速查表（人读）；PRD 定稿后回写 |
| A / H | 项目根 `README.md`（受控例外） |

```text
<项目根>/
├── README.md                       # A（技术栈/启动，可选）+ H（测试/运行，条件）
├── .trellis/spec/structure/
│   ├── _meta.json                  # 机器：product / baseline / apps[] / domains[] / categories
│   ├── tour.md                     # L1：paths ['**']
│   ├── domains/<domain>.md         # L2：paths = 域 globs
│   ├── global/                     # directory-map / routes
│   └── {current,legacy}/<domain>/  # apis / data-models
├── .adapter-out/                   # 适配器提取中间件、图谱新鲜度标记（.gitignore，不入库）
├── .atlas/                         # atlas 包（含 adapters/_graph.py、scripts/impact_report.py）
└── product/                        # prd / e2e
```

**为什么落 `.trellis/spec/structure/`**：这是 Trellis 的 Spec 路径注入层——`tour.md` 与 `domains/<d>.md` 带 `paths:`，Trellis 任务会**原生注入**对应片段；其余文件按需 Read。

---

## 六、适配器与接线

- 适配器**只产 JSON、不写文档**；契约正文唯一落 `.atlas/shared/stack-profile.md`。适配器按事实类别命名（`routes` / `api` / `models` / `tests`），**框架识别收在适配器内部**——核心代码不认识任何具体框架。
- **接线判据**——满足其一才接：① **聚合价值**（事实散落多处、源难以直接读）；② **第三方对账方**（存在需要与该事实对账的另一工件）。两者皆无 ⇒ 源即真相，不接（抽取即拷贝，拷贝即漂移面）。
- **现况（三接）**：`routes` / `api` / `models` 已接线——适配器输出 = 确定性集合，`structure ↔ 代码` 对账从「缺口」转为「配门」（重跑适配器 → 刷新 → 差集 = 待更新面）；`tests` 不接（源即真相）。
- **事实区自动渲染**：`refresh_structure.py --apply` 读 `.adapter-out/*.json` 自动重写事实区表——行键级单元格合并（适配器填可枚举列、既有行语义列保留、消失行移除），无 `.adapter-out/` 时跳过。

---

## 七、维护：事实区与语义区两条通道

| 通道 | 谁跑 | 何时 | 覆盖 |
|---|---|---|---|
| **语义** | `trellis update-spec`（AI）/ 人工 | Trellis Finish 原生步骤 | 经验 / 规范 / 坑（`atlas:facts` 标记**外**） |
| **事实** | `refresh_structure.py`（读适配器 → 填 `atlas:facts` 区 → 推进基线） | `after_finish` hook 或手动 | 表 / 字段 / 路由 / 接口（标记**内**） |

事实刷新是**纯脚本**，正好适合 hook 单行登记，不改 `workflow.md` 结构，升级冲突最小。语义区留给 AI，事实区由脚本保鲜。
