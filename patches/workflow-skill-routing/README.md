# patches/workflow-skill-routing

把跨项目的 **skill 路由**挂进目标项目 `.trellis/workflow.md`（2026-10-04 由 `workflow-ui-skills` 改名扩义为通用技能路由包）。机制与 `workflow-plan-apply` 同构：锚点式**版本化**补丁，幂等可重放。

| 路由 | 挂点 | 触发条件 |
|---|---|---|
| `frontend-design`（做 UI 与合规走查） | `[workflow-state:in_progress]` 面包屑 + 2.2 末平台无关注 | 任务涉前端 UI（页面 / 组件 / 样式 / 交互 / 文案呈现）；自备合规基线与预检闸门 |
| 落笔纪律（零反刍与读者中立） | 两条 in_progress 面包屑 | 产物定稿（提交 / 文档 / 报告 / 交接）；遵循 `.atlas/shared/global-rules.md` §14 |
| `atlas-grill` → `atlas-design-review`（设计决策串行两道） | 两条 planning 面包屑 | 重大设计决策（多方案、要用户拍板）定稿前 |

## 为什么挂 workflow.md，而不是靠 skill 自动触发

skill 的自动触发 = 「请求文本 ↔ description」的概率匹配，绑在**请求时点**上；流程中段的技能需求（Execute 深处写 UI、落笔定稿、设计定稿前追问）发生在文件操作里，没有任何事件会重新评估一遍技能列表（本仓库实证：`25071f5` / `15d3d6f` 两次用到都是用户点名才跑；B124 走查形态三轮被否 = 设计决策不追问的代价）。workflow.md 祈使步骤 + `[workflow-state:*]` 面包屑（每轮注入）是本仓库实测最硬的软机制。

## 内容

| 文件 | 作用 |
|---|---|
| `spec.json` | 补丁载荷：7 条锚点补丁（UP-161 三条 UI 路由 + UP-162 四条：落笔纪律 ×2 + grilling ×2） |
| `apply-patches.py` | 锚点式版本化应用器（与 workflow-plan-apply 同一实现的自包含拷贝） |
| `breadcrumb-in-progress.insert.md` / `_inline` | UI 技能路由 enforcement 行（子代理口径 / inline 口径） |
| `ui-skill-note.insert.md` | 2.2 末平台无关注——UI 路由细节载体 |
| `no-negative-echo-in-progress.insert.md` / `_inline` | 落笔纪律 enforcement 行 |
| `grilling-planning.insert.md` / `_inline` | 设计决策串行两道第一道的推手行 |

## 用法

```bash
# 干跑（看将插入什么，不写文件）
python3 apply-patches.py --target <项目根>

# 应用（幂等：已打过则 skipped）
python3 apply-patches.py --target <项目根> --apply
```

## id 纪律

补丁 `id` 一经落地**不得改名**：workflow.md 里的版本化块按 id 寻址，id 变更会让已落块失去指纹追踪、重放变成重复插入。内容修改 = 改片段文件 + 重放（指纹不同 ⇒ 整块替换）。

## 安装接线状态（回灌前）

- **本项目**：已应用（2026-10-04，applied=7）。
- **新项目自动安装**：源包 `install.sh` 第 5 步目前**硬编码**只应用 `patches/workflow-plan-apply`；本包要在装配时自动生效，须把该步泛化为遍历 `patches/*/spec.json`（存在 `apply-patches.py` 才跑）。已登记 `ATLAS-UPSTREAM.md` `#161` / `#162` 的上游目标，随回灌批落地。
- **回灌前重跑 install.sh 的已知影响**：装配会整包刷新 `.atlas/` ⇒ 本包目录会被冲掉；workflow.md 里已落的版本化块**不会**被移除（补丁无卸载逻辑），但片段更新后的重放对齐须待回灌后的 install.sh。

## 前置条件

路由的 skill（`frontend-design` / `web-design-guidelines` / `no-negative-echo` / `grilling` / `atlas-design-review`）里，前四者是**用户级** skill（`~/.agents/skills/`），不随 atlas 分发；`atlas-design-review` 是本项目 `.agents/skills/` 的 atlas 瘦桩。目标机器缺某个 skill 时对应路由指令无法执行，但 workflow 文本本身无害（不会报错）。

## 确认门

应用本补丁会改 `.trellis/workflow.md`，属 `shared/global-rules.md` §7 确认门动作；本次由用户显式要求挂接（2026-10-04「帮我加吧」UI 路由 + 「整吧」通用路由扩条）触发。

## 回归测试

项目副本不含测试面（`.atlas/tests/` 属装配刷新面）。回灌时在源包补三件：① `atlas/patches/workflow-skill-routing/` 整目录搬运；② `install.sh` 第 5 步泛化；③ 仿 `test_real_workflow_anchors_present` 先例给 `atlas/tests/test_apply_patches.py` 加本包锚点守卫。
