# patches/workflow-skill-routing

把跨项目的 **skill 路由**挂进目标项目 `.trellis/workflow.md`（2026-10-04 由 `workflow-ui-skills` 改名扩义为通用技能路由包）。机制与 `workflow-plan-apply` 同构：锚点式**版本化**补丁，幂等可重放。

| 路由 | 挂点 | 触发条件 |
|---|---|---|
| `frontend-design`（做 UI 与合规走查） | `[workflow-state:in_progress]` 面包屑 + 2.2 末平台无关注 | 任务涉前端 UI（页面 / 组件 / 样式 / 交互 / 文案呈现）；自备合规基线与预检闸门 |
| 落笔纪律（零反刍与读者中立） | 两条 in_progress 面包屑 | 产物定稿（提交 / 文档 / 报告 / 交接）；遵循 `.atlas/shared/global-rules.md` §14 |
| `atlas-grill` → `atlas-design-review`（设计决策串行两道） | 两条 planning 面包屑 | 重大设计决策（多方案、要用户拍板）定稿前 |
| 前端复用优先（同面板能力差集 + 五列记录） | 两条 planning 与两条 in_progress 面包屑 + 2.2 末注 | 新增/重构前端模块或新增前端源码文件；直接指向 `.atlas/shared/frontend-reuse.md`，普通修复不强制 |

## 为什么挂 workflow.md，而不是靠 skill 自动触发

skill 的自动触发 = 「请求文本 ↔ description」的概率匹配，绑在**请求时点**上；流程中段的技能需求（Execute 深处写 UI、落笔定稿、设计定稿前追问）发生在文件操作里，没有任何事件会重新评估一遍技能列表（本仓库实证：`25071f5` / `15d3d6f` 两次用到都是用户点名才跑；B124 走查形态三轮被否 = 设计决策不追问的代价）。workflow.md 祈使步骤 + `[workflow-state:*]` 面包屑（每轮注入）是本仓库实测最硬的软机制。

D177 的前端复用同理：V3 现场的同类选择器已经在同一面板里，问题不是「规则没写」，而是创建时没有事件把「同面板 sibling 能力差集」推到眼前。面包屑每轮注入 + 2.2 末注承载细节，比再加一个靠 description 匹配的 skill 更可靠。

## 内容

| 文件 | 作用 |
|---|---|
| `spec.json` | 补丁载荷：11 条锚点补丁（UP-161 三条 UI 路由 + UP-162 四条落笔/grilling + D177 四条前端复用） |
| `apply-patches.py` | 锚点式版本化应用器（与 workflow-plan-apply 同一实现的自包含拷贝） |
| `breadcrumb-in-progress.insert.md` / `_inline` | UI 技能路由 enforcement 行（子代理口径 / inline 口径） |
| `ui-skill-note.insert.md` | 2.2 末平台无关注——UI 路由 + 前端复用执行注载体 |
| `no-negative-echo-in-progress.insert.md` / `_inline` | 落笔纪律 enforcement 行 |
| `grilling-planning.insert.md` / `_inline` | 设计决策串行两道第一道的推手行 |
| `reuse-planning.insert.md` / `_inline` | Plan 阶段前端复用路由（五列记录 + 新模块目录一次性确认） |
| `reuse-in-progress.insert.md` / `_inline` | 实现阶段前端复用路由（无记录不得落笔） |

## 用法

```bash
# 干跑（看将插入什么，不写文件）
python3 apply-patches.py --target <项目根>

# 应用（幂等：已打过则 skipped）
python3 apply-patches.py --target <项目根> --apply
```

## id 纪律

补丁 `id` 一经落地**不得改名**：workflow.md 里的版本化块按 id 寻址，id 变更会让已落块失去指纹追踪、重放变成重复插入。内容修改 = 改片段文件 + 重放（指纹不同 ⇒ 整块替换）。

存量若存在 2026-09-27 之前的旧式 `ui-skill-note` 块（无结束标记），`insert_after` 会拒绝自动迁移；按应用器提示人工补结束标记后再重放。

## 安装接线状态

- **本项目**：已应用（2026-10-04，applied=7）；2026-10-31 扩至 11 条（D177）。口径分两种：全新项目 applied=11；存量已应用 7 条的项目 = 4 applied + 1 replaced（`ui-skill-note` 扩段）+ 6 skipped。本次 V3 原件只读，副本实跑即 4+1+6，重放 11 skipped。
- **新项目自动安装**：`install.sh` 第 5 步已泛化为遍历 `patches/*/spec.json`（含 `apply-patches.py` 的包才跑），本包随装配自动生效。
- **重跑 install.sh 的已知影响**：装配会整包刷新 `.atlas/`；workflow.md 里已落的版本化块**不会**被移除（补丁无卸载逻辑），片段更新后重放会按指纹整块替换。

## 前置条件

`frontend-design` 随 atlas 分发（`skills/frontend-design`），由 `install.sh` 安装到平台的 skill 目录；其它路由 skill（`web-design-guidelines` / `no-negative-echo` / `grilling` / `atlas-design-review`）视宿主与项目安装而定。目标机器缺某个 skill 时对应路由指令无法执行，但 workflow 文本本身无害（不会报错）。

D177 的前端复用路由**不依赖专属 skill**：面包屑直接指向 `.atlas/shared/frontend-reuse.md`。不新建 `skills/atlas-reuse`，因为 `tests/test_install_selfcheck.py` 的环退役对称判据会把非环 skill 判红。

## 确认门

应用本补丁会改 `.trellis/workflow.md`，属 `shared/global-rules.md` §7 确认门动作；本次由用户显式要求挂接（2026-10-04「帮我加吧」UI 路由 + 「整吧」通用路由扩条；2026-10-31「你就做就行」D177 前端复用）触发。

## 回归测试

`tests/test_frontend_reuse_patch.py` 用完整 workflow fixture 覆盖本包全部 11 条补丁：干跑不写、首跑 applied、二跑 skipped、锚点缺失报错且不写、跨包 id 唯一、契约字段与单源登记、无框架名泄漏。另保留 `workflow-plan-apply` 的 `tests/test_apply_patches.py` 不动。
