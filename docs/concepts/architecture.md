# 双线束模型：Agent Harness 与 Project Harness

## 原创概念：为什么我们需要完整的 Project Harness？

在 AI 编程的实际落地中，必须清晰区分两套完全不同的线束（Harness）：

* **Agent Harness（工人马具）**：由外部 Coding Agent 平台（如 Claude Code, Cursor, OpenCode 等）提供，负责模型在单次会话中的 Prompt 组装、上下文截断与底层工具调用；
* **Project Harness（项目工程线束）**：直接驻留在业务 Git 仓库内部、守护软件全生命周期的工程规范。**Trellis 本身就是 Project Harness 的一部分**，专注于小需求的任务拆解与状态机流转；而 **Atlas 将这套 Project Harness 升格为覆盖软件全生命周期的完整治理体系**。

---

## 架构拓扑：项目全生命周期线束

```
┌─────────────────────────────────────────────────────────────┐
│                 Atlas：全生命周期的 Project Harness            │
│                                                             │
│   ┌─────────────────────────────────────────────────────┐   │
│   │   项目级平面（全局资产与秩序）                        │   │
│   │   结构基线 ──► 项目级 PRD (AC) ──► E2E 验收总索引与分片 │   │
│   └──────────────────────────┬──────────────────────────┘   │
│                              │  单向编排：atlas apply <ID>   │
│                              ▼                              │
│   ┌─────────────────────────────────────────────────────┐   │
│   │   需求级平面（小需求任务执行，由内置的 Trellis 承担）    │   │
│   │   需求卡 (Task) ──► 业务代码编写 ──► 任务归档        │   │
│   └─────────────────────────────────────────────────────┘   │
└──────────────────────────────┬──────────────────────────────┘
                               │ 通过路径薄桩与钩子注入给外部 Agent
                               ▼
┌─────────────────────────────────────────────────────────────┐
│   外部 Coding Agent（如 Claude Code / Cursor / Codex 等）    │
│   提供 Agent Harness（模型上下文、工具调用、单次会话）         │
└─────────────────────────────────────────────────────────────┘
```

### 1. 原创概念：为什么有了 Agent 记忆，依然需要 Project Harness？
* **Agent Harness 的记忆是“工人的经验手记（模糊且概率性）”**：  
  现代 Coding Agent 确实拥有记忆机制（如 auto-memory、向量检索或会话手记）。但这种记忆本质上是**自然语言的经验总结与概率召回** —— 它无法提供机器确定性。面对大型系统，模型依旧会遗忘边界、漏掉关联依赖、甚至产生假完成幻觉；
* **Project Harness 维护的是“工程蓝图与机器门禁（确定且可证伪）”**：  
  Atlas 原创提出的 Project Harness 不依赖模型的“记忆自觉”，而是将应然资产（PRD 验收准则、代码图谱事实、E2E 验收用例）直接固化在代码仓库内，并用双向集合对账门给出硬性的 0/1 判定。**工人的个人手记再丰富，也绝不能替代工地的建筑蓝图与机器监理！**
* **Trellis 专注小需求执行**：  
  Trellis 优雅地解决了“单条小需求的 Plan、Implement 与 Check”，它作为 Project Harness 的需求级执行件，现在已经是 Atlas 工作流的有机组成部分；
* **Atlas 补齐了全生命周期的全局闭环**：  
  在小需求执行之上，Atlas 铸造了项目级应然资产（PRD/E2E/结构）、全套机器硬门禁、以及有头慢放控制台，让整个代码库拥有了贯穿一生的工程确定性。无论你外部换用何种 Coding Agent，项目内部的 Project Harness 始终如一地稳如磐石。

---

## 1. 项目级：应然资产层 (Atlas 辖区)

* **定义**：“这个软件是什么、业务规则有哪些、怎么算做对”；
* **内容物**：
  * **结构基线**（`.trellis/spec/structure/`）：通过 AST 与代码图谱自动抽取的实然事实；
  * **项目级 PRD**（`product/prd/`）：业务叙事与验收标准（AC）单一真相源；
  * **E2E 验收总索引与页面分片**（`product/e2e/`）：真实靶场可证伪用例；
* **特性**：
  * **跨需求持久化**：不会随着某个任务完成而被归档隐藏；
  * **机器可校验**：受全量出厂测试（`python3 -m pytest .atlas/tests/`）与机器门禁守护；
  * **只定应然，不写业务实现**：Atlas 契约严格约束自己“不产出业务代码”。

---

## 2. 需求级：任务执行层 (Trellis 辖区)

* **定义**：“这一次迭代具体改什么、哪个 Agent 来改、怎么一步步改”；
* **执行体**：由必需的宿主任务系统 [Trellis](https://github.com/mindfold-ai/trellis) 承担（负责任务调度与需求级流程挂载；底层对接各类 Agent 交互平台）；
* **特性**：
  * 任务卡（`prd.md`、`implement.md`）随着开发结束而归档；
  * 会话上下文随着任务完结而重置；
  * 任务只对当前具体修改负责，没有项目全局视野。

---

## 3. `apply` 单向衔接：应然资产先行

在传统的任务执行流中，开发者常常“先写代码，写完随手写两句说明”；在 Atlas 中，这个流程被严格逆转：

1. **Phase 1.6 强约束**：需求卡被批准后、动手写代码之前，强制触发 `atlas apply <需求ID>`；
2. **三问门分流**：
   * 改动了既有系统能力？
   * 需要人类确认新的 UI 交互？
   * 该功能需要可重复自动化验收？
3. **编译应然资产**：
   * 若有任一为“是”，必须先在 `product/prd/` 中更新受影响域的 AC，并在 `product/e2e/cases/` 生成用例分片；
   * 只有应然资产编译就绪并通过全部前置门禁，Agent 才被允许进入代码编写阶段。

---

## 4. 附：Agent Harness 五子系统与 Atlas 资产的类比映射

外部课程把 Agent Harness 拆成五个子系统。下表只做**类比映射**，不是把两层当成同一层：Agent Harness 管单会话，Project Harness 管跨会话；前者由外部 Coding Agent 提供，后者由 Atlas 固化在仓库里。

| Agent Harness 子系统 | 课程落点 | Atlas 对应 | Atlas 的差异 |
|---|---|---|---|
| Instructions | AGENTS.md / CLAUDE.md | init 注入指针 + skills 瘦桩 + `shared/global-rules.md` | 入口是路由，规则随包版本化 |
| State | progress.md / feature_list.json | Trellis 任务 + 结构基线 + ADR + E2E 索引 | 门禁判定 + 人审落账，跨会话可对账（门禁只报告，不改写资产） |
| Verification | init.sh / 测试命令 | `atlas check` 两档 + 硬门 + 变异证明 | 双向对账，门禁自证会红 |
| Scope | WIP=1 / 完成定义 | 三问门 + AC + 覆盖维度 | 需求级裁剪；覆盖维度只提示缺口，不替代语义审查 |
| Session Lifecycle | session-handoff.md | apply / backfill / closeout + 人审账本 | 跨会话资产化 + 评审指纹 |

两者不是替代关系：课程解决「单次会话怎么让 agent 可靠地做完一件事」，Atlas 解决「跨会话、跨需求，项目怎么持续证明自己没漂移」。课程已经要求验证命令通过后才改状态，但 `feature_list.json` 仍是单文件、由 agent 维护；Atlas 用 PRD / AC / E2E 三份独立资产 + 双向门 + 人审账本，防「自己批自己作业」与「资产 ⇄ 实现漂移」。

> 外部参考（仅作类比，不构成依赖）：`walkinglabs/learn-harness-engineering` 课程；Anthropic《Harness design for long-running application development》；OpenAI《Harness engineering》；arXiv:2610.34577《Rethinking Verification in Agent Harnesses》。
