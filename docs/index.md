---
layout: home

hero:
  name: "Atlas"
  text: "工业级 Spec-Driven 全流程工作流"
  tagline: "“没有应然资产约束的 AI 编码，写得越快，烂尾越彻底。” 让 Vibe Coding 拥有工业级确定性。"
  image:
    src: /images/e2e-console.png
    alt: Atlas E2E 控制台
  actions:
    - theme: brand
      text: 🚀 30 秒快速上手
      link: /guide/quick-start
    - theme: alt
      text: ⚡ 查看独门重器
      link: /innovations/e2e-console

features:
  - icon: 🎯
    title: 应然资产先行 (Spec-Driven)
    details: 坚决杜绝“盲写代码、事后补文档”。需求提出后先由 apply 编译进 PRD 与 E2E 资产，先定规则再动手。
  - icon: 🖥️
    title: E2E 用例评审控制台
    details: 纯标准库本地服务，带 500ms 慢动作弹窗回放。执行绿灯才解锁人工 Review，单写者原子提交账本。
  - icon: 🕸️
    title: 代码图谱 (Code Graph) 逆向
    details: 基于 FalkorDB / cgc 全仓拓扑，跨文件 callers/callees 深度感知，精准推导需求影响面与架构漂移。
  - icon: 🔨
    title: 变异证明 (Mutation Proving)
    details: 拒绝形同虚设的假门禁。M1~M43 变异钉子测试实证：每一条机器规则都必须证明自己在脏数据下会咬人。
  - icon: 🛡️
    title: 实例 ⑤ 只读防偷工减料审查
    details: 独立进程 diff 审查，严苛执行“应审 N / 实审 M”对账，彻底遏制大模型跳过文件、少审漏审的暗箱操作。
  - icon: 🧠
    title: 可选外脑：Obsidian 决策中枢
    details: 代码库只写正向终态（What），Obsidian 活页沉淀决策心路（Why）。优雅降级设计，未配置自动跳过。
---

<div class="vp-doc" style="max-width: 960px; margin: 40px auto; padding: 0 24px;">

## 💡 为什么开发者选择 Atlas？

在纯粹依赖 Agent 自由发挥的 AI 辅助编程（Vibe Coding）中，开发者普遍会遇到难以逾越的工程陷阱：

| 自由放养的传统 Vibe Coding | 🛡️ Atlas 工业级应然资产治理 |
|---|---|
| **上下文失忆**：会话一压缩，模型遗忘历史决策，反复推翻架构 | **三卷合一外脑**：决策依据与未决台账持久化，新会话一秒入场 |
| **“伪完成”幻觉**：仅凭前端组件和 Toast 自证成功，数据根本没落盘 | **有头慢动作控制台**：慢速真实弹窗回放，刷新复断言，眼见为实 |
| **单源事实坍塌**：接口契约、代码实现与测试用例散落各处，修 A 坏 B | **双向机器对账门**：testid 实然 ⇔ 应然集合严格相等，多写漏写一票否决 |
| **形式主义自审**：同一个 Agent 自写自审，永远是一团和气的“毫无问题” | **独立审查架构**：跨进程隔离、只审不改、N/M 评审文件数强对账 |

---

## ⚡ 极速开始：只需两行

```bash
# 1. 全局安装 CLI
npm install -g atlas-workflow

# 2. 进入项目目录一键装配
cd your-project && atlas init
```

> **日常开发全自动**：在 Trellis 中提需求，工作流自动编译应然资产；写完代码自动逆向刷新事实，零心智负担！

</div>
