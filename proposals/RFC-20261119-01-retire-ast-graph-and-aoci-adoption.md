# RFC-20261119-01：正式退役 cgc 外部 AST 图谱，确立全局与域级轻量语义透镜（Scope-Aware FRAS）以赋能执行层

> 提案编号：RFC-20261119-01  
> 提案作者：@antigravity  
> 关联状态：已终审通过 (Approved after Final Review)  
> 评审记录：2026-11-19 经专职 `tech-proposal-reviewer` 智能体（GLM-5.3-Flash）三轮对抗性审查与全仓实证核验，裁决为【修后通过】，P0（D200 编号）与 P1 机械清单全部吸收闭环。  
> 影响范围：核心契约 (shared) | 结构环与执行层 (rings/structure & execution) | 适配器 (adapters) | 脚本工具 (scripts) | 校验器与门册 (validators & gates) | 装配面 (assembly)

---

## 1. 现象、取证与战略定位 (The Problem & Evidence)

### 1.1 战略定界：赋能 Atlas 自建执行层的代码导航
根据 2026-10-25 拍板决议（`atlas-own-executor-plan.md`，D150 链条）：**Atlas 绝非仅是终点线上的质检员，而必须走向「需求输入 -> 架构理解 -> 自主生成与修改 -> 确定性门禁与真跑验收」的完整研发生态闭环**。

在执行层自主改动代码时，Agent 面临的核心瓶颈是：
1. **全局噪音大**：在大型仓内，缺乏物理收敛会导致 Agent 大海捞针；
2. **框架黑盒多**：现代企业级框架（Spring DI、MyBatis-Plus 泛型 BaseMapper、异步线程池、React JSX 渲染、qiankun 微前端）阻断了传统静态调用分析；
3. **隐性地雷密**：大量不可从静态语法推断的业务硬约束（如异步时序、React 闭包锁死、鉴权校验先后顺序、长整型精度丢失）无法被静态解析捕获。一旦 Agent 踩雷，代码必然在真跑验收门上一遍遍撞红。

### 1.2 为什么必须彻底退役 cgc/FalkorDB 外部 AST 图谱？
实测证实，基于编译器 AST 的外部代码图谱在现代工程中已全面失效（取证详见 `/Users/sunwenzhe/Desktop/aoci-eval/notes/REPORT.md`）：
- **前端栈 JSX 零边（D78 实证）**：组件以标签形式引入，AST 不生成函数调用边 `[:CALLS]`，图谱枚举与轻量正则**完全恒等**，组件叶子影响面**系统性失真**；
- **Java 现代后端四重断链（2026-11-19 实测）**：
  1. *Spring DI 断链*：Controller 调接口抽象方法，AST 无法到达实现类 `ServiceImpl`；
  2. *MyBatis-Plus 断链*：调泛型 `selectPage` 仅关联到 MyBatis 库内部，完全丢失数据表和 Entity 映射；
  3. *线程池断链*：`executor.submit(...)` 发生时，AST 调用链直接截断，下游异步业务成为孤岛；
  4. *HTTP 客户端断链*：`restTemplate.exchange()` 丢失目标服务与配置。
- **运维与装配沉重**：依赖 Docker、FalkorDB、CGC 外部库，增加采纳仓准入门槛，运行时经常报 `not_ready`。

### 1.3 语义图谱实测的启示与 AOCI 全仓大底座的致命代价
AOCI-CODE（v0.2.0-rc2）实测表明，模型撰写的 FRAS 语义边能够完美穿透上述四重断链（后端切面产出 49 条高质量边，前端产出 329 条边）。但其**全仓平铺建索模式代价极高**：
- 1,272 目标的 Java 仓全量建索需 **37~41 轮多轮交互批次**；
- Agent 进场常驻底噪 **14 万 tokens**；
- 其 `cognition system impact` 命令官方锁死为**仅支持 `database://` 表对象**，不提供代码级 impact 算子；
- 机器门只验结构不验语义真假。

---

## 2. 决策与架构设计 (The Decision & Architecture)

### 2.1 核心定案与分层分工

1. **彻底退役外部 AST 图数据库（cgc / FalkorDB）**：
   - 清理 `adapters/_graph.py`（恰 397 行死代码）与 FalkorDB 容器连接逻辑；
   - 废弃 `stack-profile` 的 `graph` 节点及 `routes.py` 的 `--backend graph` 选项；若存量项目声明了 `graph`，由 `validate_stack_profile.py` 报 **WARN 指名「graph 段已退役请移除」**（绝不静默改道）。
2. **确立「两级轻量语义透镜（Scope-Aware FRAS）」体系**：
   - **绝不全仓平铺建立庞大索引**，改用需求驱动的局部激活；
   - **资产下沉与去中心化存储**：
     - **业务域内资产**：存放在 `.trellis/spec/structure/current/<domain>/cognition.fras`；
     - **跨切面共享基础设施（彻底解决孤儿问题）**：`src/components/**`、`src/utils/**`（axios、auth、hooks）、`src/router.jsx` 等跨切面资产，存放在 `.trellis/spec/structure/global/cognition.fras`（与 `routes.md` 同级）；
3. **单源事实不重叠原则（解决两份账本打架）**：
   - 接口契约与数据模型事实继续由 `apis.md` 与 `data-models.md` 承载，FRAS 中**严禁重复声明**已有的 API/模型字段；
   - `cognition.fras` 只准入两类增量信息：
     - **R（穿透调用拓扑）**：格式 `R:code:相对路径`，记录穿透框架的真实依赖；
     - **S（防改崩硬约束）**：严格执行 AOCI S 字段准入铁律（非静态推断 + 防踩雷事实，硬配额 C9-8≤600, C7-4≤200, C3-1≤50），严禁正确的废话。
4. **诚实对待首改与 Drift 防御**：
   - **首改诚实化**：首次触及未建卡的冷门模块，诚实标明无 FRAS 增益，走源码直读 + 真跑门兜底；
   - **收口棘轮生长**：每次需求收口（对账门与真跑门全绿后），顺手为本次触及的文件补齐或更新 FRAS 条目；
   - **Drift 校验**：FRAS 条目记录对应文件的 blob sha，消费时失配直接出声抛 WARN，绝不盲目信任过期条目；
5. **影响面推导与对账门（impact_reconcile）的精准闭环**：
   - `impact_report.py` 移除 `ensure_index()` 探针，无 AOCI/FRAS 时返回诚实的 `status: "not_ready"`；此时预测集取**需求卡声明集（`touched_files`）**；
   - 若存在本域及全局 `cognition.fras`，仅做**反向 1-hop（单跳）R 边提取**补充进 `aoci_candidates` 独立字段供 Agent 参考，不污染传统 `layers[]`，gates.md:57 predicted 集不入账；
   - 对账门遵从 `shared/gates.md:57`，漏报（miss）保持 **WARN 级警告**，严格遵循 D79④ 观察窗升档规则，并在收口报告强制留痕，防范无脑填宽。

---

## 3. 全量改动面清单 (Affected Surface) —— 经全仓 grep 实核补齐

本案改动清单经终审审查机械全核，涵盖代码、校验器、装配面、门册与测试链：

### 3.1 核心代码、校验器与适配器清理
- [ ] `adapters/_graph.py`：移除对 `codegraphcontext` 和 FalkorDB 的直接连接（397 行全清），重写为读取 `cognition.fras` 单跳反查的极简辅助函数；
- [ ] `adapters/routes.py`：移除 `--backend graph` 选项及对 `_graph` 的 import；若传入 graph 报显式退役 WARN 并回退；
- [ ] `validators/validate_stack_profile.py`：`:44` 移除 GRAPH_KEYS 依赖，`:210-217` 增加对 `graph` 段的显式退役 WARN 指名提示；
- [ ] `scripts/impact_report.py`：移除 `_graph.ensure_index()` 探针，支持读取 `cognition.fras` 反向 1-hop 边进 `aoci_candidates`，无索引时诚实输出 `status: "not_ready"`；
- [ ] `rings/structure/reference.md`：`:183,208` 移除“探测图谱后端并提议”的指令；
- [ ] `_support/solution.py`：清理 `:3333` 引用 `_graph` 的文案；
- [ ] 文档宣称面收口：`README.md`、`RUNBOOK.md`、`docs/guide/quick-start.md`、`docs/innovations/code-graph.md`、`docs/concepts/rings.md`、`docs/design/overview.md` 同步清理 cgc/graph 说明。

### 3.2 契约与 ADR 链（ADR Supersession）
- [ ] `DESIGN.md`：新增决策条款 **D200（退役外部 AST 图谱，确立全局与域级按需语义透镜）**（避免 D185 撞号），挂接 supersedes 链（取代 D77/D78，行内保留原编号防词汇钉断裂）；
- [ ] `shared/stack-profile.md`：将 `graph` 节点标记为已退役（deprecated），采纳仓无需再配置；
- [ ] `apply/reference.md`：更新影响面报告输入源优先级与 `not_ready` 语义。

### 3.3 门册与装配面（Assembly Surface 四表同批）
- [ ] `shared/gates.md`：门册更新退役条款，包含清理 §4.1 C-01/C-02（owner: `adapters/_graph.py`），**按当前 58 行实收口径重算**；
- [ ] `install.py` 及相关脚本：清理 `c("图谱后端隔离层", .../_graph.py)` 声明，**四表同批更新**（`install.py` 的 pkg_dirs / package.json.files，`scripts/pkg_digest.py` 的 ASSEMBLY_COVER_DIRS，`backflow` 的 BACKFLOW_DIRS），保证 `test_assembly_surface.py` 四表钉一次过。

### 3.4 测试防线与测试文件计数棘轮链
- [ ] 清理/重构测试文件：
  - `tests/test_graph_backend.py`、`tests/test_routes_graph_backend.py`、`tests/test_stack_profile_graph.py`（重构为测试退役 WARN 出声与 FRAS 单跳读取）；
  - `tests/test_refresh_facts.py:47`（同步更新加载对象）；
  - `tests/test_shared_kernel.py:50-106`（同步派生字段白名单）；
  - `tests/test_map_anchors.py` 与 `docs/map/graph.md`（同步维护 L1 图谱地图锚点）；
- [ ] 若增删测试文件，严格联动修改**三处测试计数棘轮**（`docs/map/index.md:108`、`docs/map/atlas-map.html`、`shared/gates.md`，执行器为 `test_map_anchors.py`）；
- [ ] `tests/test_impact_report.py`：新增对 `cognition.fras` 存在与缺失双轨情况下的单元测试。

---

## 4. 实施阶段 (Implementation Phases)

1. **Phase 1（契约先行与文档收口）**：落盘 D200 条款，标记 stack-profile 废弃，更新全局文档；
2. **Phase 2（校验器与适配器收缩）**：精简 `_graph.py` 与 `validate_stack_profile.py`，打通 FRAS 单跳解析；
3. **Phase 3（装配与测试棘轮对账）**：四表同批更新，同步更新测试文件与锚点门，跑全套测试；
4. **Phase 4（沙箱切面验收）**：在 `/Users/sunwenzhe/Desktop/跨网传输/hc-unify-application` 验证全局+域级 FRAS 在改动需求下的单跳提取与对账门表现。
