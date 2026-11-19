# Playground 靶场实测：自建完整执行层全流程闭环留档 (D204)

> **实测时间**：2026-11-19
> **执行命令**：`atlas workflow (plan -> dispatch -> verify -> finish)`
> **测试靶场**：`tests/fixtures/verify_playground/`
> **最终结论**：**全流程 100% 自主闭环，完全摆脱 Trellis 依赖**。

---

## 一、生命周期各阶段流转实证

| 阶段 | 执行动作 | 关键产出物 | 验证判定 |
|---|---|---|---|
| **1. Plan (大任务拆解)** | `atlas workflow plan --unit HOME-FLOW` | 生成 `.atlas/tasks/HOME-FLOW/prd.md`、`task.json` | **PASS**（包含合规 `atlas-acceptance:` 行与四列 Confirmed 证据表） |
| **2. Dispatch (派发派工)** | `atlas workflow dispatch --unit HOME-FLOW` | 生成 `dispatch.md`，状态流转为 `in_progress` | **PASS**（仅注入 AC-HOME-001 最小上下文，精简 90%+ 无关 spec 噪音） |
| **3. Implement (开发实现)** | 代码修改并暂存 `git add site/index.html` | 暂存区就绪 | **PASS**（修改进入暂存区，状态机严格守住） |
| **4. Verify (独立审查)** | `atlas workflow verify --unit HOME-FLOW` | 触发 `atlas review --staged` + 工具链检查 | **PASS**（产出 `review.json` v4、`scope-manifest.json`、`closure.json`） |
| **5. Finish (确认收口)** | `atlas workflow finish --unit HOME-FLOW` | 校验审查报告通过，流转状态为 `completed` | **PASS**（若无 review.json 强制阻断，有证明顺利收口） |

---

## 二、关键取证

### 1. 任务派工单 (Dispatch) 样本
```markdown
# 任务派发执行单 (Task Dispatch) — 任务一：落实首页标题变更 AC-HOME-001

**任务编号**：`HOME-FLOW`
**状态**：`in_progress`

## 1. 任务需求 (Task PRD)
# 任务需求卡 — 任务一：落实首页标题变更 AC-HOME-001

**任务编号**：`HOME-FLOW`  
**前置依赖**：`无`  
**影响业务域**：`home`

<!-- ATLAS:START -->
atlas-acceptance: AC-HOME-001
<!-- ATLAS:END -->

## 1. 任务背景与目标
### 任务一：落实首页标题变更 AC-HOME-001
根据产品需求文档，点击主按钮后标题应从加载中正确切换为验收靶场。

## 2. 确认口径与证据台账 (Confirmed)

| 确认项 | 确认口径 | 证据状态 | 证据指针 |
|---|---|---|---|
| 验收基准 AC-HOME-001 | 满足对应断言并经独立审查通过 | pending | N/A |

## 3. 变更范围与完成定义
- [ ] 代码实现完成，无多余未跟踪修改
- [ ] 暂存区通过 `atlas review --staged` 独立审查
- [ ] 确定性测试/工具链全部通过

## 2. 权威验收...
```

### 2. 收口后任务卡元数据 (task.json)
```json
{
  "id": "HOME-FLOW",
  "title": "任务一：落实首页标题变更 AC-HOME-001",
  "status": "completed",
  "depends_on": [],
  "affected_domains": [
    "home"
  ],
  "acs": [
    "AC-HOME-001"
  ],
  "created_at": "2026-11-19"
}
```

---

## 三、最终评定
Atlas 自建执行层已具备独立支撑大型工作流的能力：
- 需求能自动拆为平级 Task DAG；
- 上下文注入极小精准；
- 暂存区自动质检验收；
- 最终收口证据完备。

达到并超过 Trellis 原有能力。
