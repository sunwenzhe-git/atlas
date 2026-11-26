# 缺陷回推门面与 canonical 落点封印

> 提案编号：RFC-20261125-03
> 关联 issue：#75 / #76
> 状态：已实现，独立复审 findings 已关闭，待发版
> 影响范围：CLI / workflow / review scope / 校验器 / 契约 / 测试

## 1. 问题

D211 已统一缺陷落点，但缺陷修复仍缺反向编排：没有 `atlas bug`、机器台账与 finish 强制封印；历史 feature-root `bugs/` 规则也可能造成双落点。

## 2. 决策

1. 唯一缺陷落点保持 `<assets_root>/requirements/<slug>/`。
2. `requirement.md` 管类型/状态/关联需求，`work/缺陷报告.md` 管证据，根级 `record.json` 管回推审计元数据。
3. `atlas bug` 负责 bootstrap、影响面、签字回推与反查；可执行 hunk 默认待签字。
4. 固定顺序：实现暂存 → `atlas bug --from staged` → 暂存产物 → verify → finish。
5. finish 强制 staged 实现 OID 指纹、index/worktree 一致、产物暂存与 `review.json.bug_backflow` 独立锚；`--force` 不绕。
6. `.atlas/bugs/`、资产根缺陷 bugs 与 `requirements/<slug>/bugs/` 由 `validate_bug_ledger` 拒绝，历史文件不自动搬迁。

## 3. 机器契约

### 3.1 实现指纹

- staged 从 `git diff --cached --raw -z --no-renames` 取路径、old/new OID、mode 与对象类型。
- 只排除本次事务实际写入/生成的精确路径；无关暂存变化继续进入身份。
- OID 接受 40/64 hex；symlink、gitlink、type-change 前置拒绝。
- `source.sha256` 为排序后 canonical JSON 的 SHA256，patch 只作证据。

### 3.2 台账

- schema：`templates/bug/record.schema.json`。
- `backflow_status`：`pending | needs_decision | ready | applied | not_applicable`。
- `ready|applied` 必须无 open conflict、无 pending impact，且每个 impact 有 document 或已应用 decision 支撑。
- `history[]` append-only，seq 从 1 连续，首项 prev 为 null；verify 将 history 事件哈希写入独立审查锚。
- `not_applicable` 只允许无任务卡引用的独立分诊对象。

### 3.3 审查锚

verify 在 `review.json.bug_backflow` 写入：

- `record_sha256`
- `artifacts[{path,sha256}]`
- `history[{seq,event_sha256}]`
- `deleted_files[{path,old_oid}]`

finish 只比对该独立锚，不信任台账自哈希。staged review scope 统一读取 index blob。

## 4. 验收

1. `atlas bug --unit <slug> --from <range>` 可完成文档回推、校验与台账；staged 重跑后进入 finish 链。
2. 改接口字段未改 PRD、改 testid 未改 E2E 均非零退出并点名冲突。
3. 缺记录、pending、stale、未暂存、index/worktree 分叉、range 模式分别阻断 finish。
4. 同输入二次执行零写入、rc0。
5. `.atlas/bugs/`、资产根缺陷 bugs、`requirements/<slug>/Bugs/` 与旧 type/kind 台账均 FAIL。
6. 两个缺陷先后改同一文档，历史记录不假红。
7. 决策重放、错 bug/source、old 不唯一、部分预检失败均零写入。
8. 每个新门配 M 系变异证明。

## 5. 评审记录

方案经多轮独立双评审，冻结版为 `atlas-issues-75-76-plan-v5.md`（SHA256 `b914111c05e766bac78d2d0fb638916794781988cb6dbf7d3a31df9039c496a1`）与 `bug-record.schema.json`（SHA256 `4051a2532797c44676f897f6236e8e516d3f766eba52492a7d55be864d9210c9`）；两位 focused reviewer 均判「通过」，无剩余 Critical/Major/Minor。

并行 `fix/issue-75-atlas-bug` 的纯 diff/标识符提取、校验器编排与测试思路作为参考；feature-root 建卡与 `intake_version:2` 豁免不进入本实现。

## 6. 验证与评审

- 方案 v5 与 schema 经两位 focused reviewer 独立判「通过」。
- 实现首轮代码复审发现 1 Critical / 5 Major / 10 Minor，全部修复并补回归；focused closure review 另发现非 ASCII 路径解析缺口，已改为逐实现路径生成 diff 并补反例。
- 专项回归：114 passed / 12 subtests；新增 schema/runtime 守恒测试。
- 全量回归：2132 passed / 6 skipped / 12 subtests，唯一失败为派生计数漂移，重渲染后 canonical/map 复绿；发版脚本将再跑全量门禁。
- M252/M253 四段变异证明均通过：注入非零、逐字节还原、复绿。
- 空目录安装探针 exit 0；文档构建 exit 0；`git diff --check` 通过。

## 7. 2026-11-26 扩展：需求变更与自动触发（D213）

1. `atlas change` 成为需求变更/缺陷统一入口，`atlas bug` 保留缺陷兼容别名；命令名不是触发前提。
2. `workflow verify` 在独立评审前自动执行回推、运行校验器并暂存 exact 产物；`workflow finish` 对缺失/过期记录自动补跑，产物变化后强制 reverify。
3. 需求变更使用 `work/变更请求.md`，缺陷使用 `work/缺陷报告.md`；record schema、dedupe、validator 与双落点守卫对称覆盖两类。
4. 新审查锚为 `review.json.change_backflow`（`anchor_version=2`），覆盖 canonical 根、报告、record 与回推文档；旧 `bug_backflow` 只读兼容，双锚并存或新锚缺版本即失败。
5. 自动回推不伪造根因/阶段：原因取报告显式字段，阶段按显式参数、报告字段、保守 prod 解析；冲突仍需签字决策。
6. M255/M256 四段变异证明通过：摘 verify 自动触发、放宽 legacy 锚 canonical 产物守卫均实测转红，逐字节还原后复绿。

## 7. 留出验证

本批为 issues #75/#76 的系统性修复，触发 (b) 契约/校验器/门判据改动。已构造的回归覆盖双落点、决策绑定、语义 hunk、归档/重分析、报告篡改、索引分叉与历史幂等；尚未取得满足三条独立性的真实采纳仓留出集，结论登记为 **未闭族**。后续真实采纳仓出现同类案例时补独立留出验证，不把合成夹具冒充闭族。
