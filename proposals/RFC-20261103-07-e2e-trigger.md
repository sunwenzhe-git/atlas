# E2E 触发段：实现完成 → 用例执行 → 人 review

> 提案编号：RFC-20261103-07
> 提案作者：@sunwenzhe
> 关联状态：草案 (Draft)，已过一轮独立设计评审（2026-11-03）
> 影响范围：门册/契约（rings/e2e、apply、gates）· 脚本工具 (scripts) · 工作流补丁 (patches/workflow-e2e-trigger) · 测试 (tests)

---

## 1. 现象与取证

### 1.1 触发形态（抽象）

- **规则 / 环节**：`scripts/atlas_check.py` 的 `check_e2e`（E2E 真跑门）＋ Trellis 挂接（`apply/reference.md` §7）＋ 项目侧 `.trellis/config.yaml` 的 hooks。
- **触发时机**：一条需求实现完成、静态检查通过之后。
- **具体行为**：
  1. **没有主动调用/提醒**：E2E 执行器已存在（`atlas_check --page` 与 `scripts/atlas_verify.py` 的 pre→run→backfill→report），但 Phase 2 结束时没有任何步骤或面包屑提示去调用它们；收尾扫描（`shared/closeout.md`）只在「收口」时读，晚于实现完成。
  2. **未就绪状态同形**：`check_e2e` 的早退分支全部输出同一 `SKIP`，人读输出无法区分「本项目不接 E2E（设计结论）」「靶场未声明（缺决策）」「脚本未生成（缺工作）」「靶场不可达（环境）」「登录形态未声明（缺决策）」。

### 1.2 客观证据

```text
$ grep -n "hooks" -A 4 .trellis/config.yaml
hooks:
  after_archive:
    - "python3 .atlas/scripts/refresh_structure.py --root . --chain"

$ grep -n "atlas_check\|e2e\|E2E" .trellis/workflow.md | sed -n '1,5p'
525:- 动作：推导影响面 → 按 `prd` → `e2e` 增量更新 → ...
（Finish 3.4/3.5 无 E2E 条目；Phase 2.2 无 E2E 触发步骤）
```

`scripts/atlas_check.py::check_e2e` 的早退（节选，分支顺序决定实际命中）：

```python
if not scripts.is_dir():      → "无脚本目录（门控态）"
if page and not target:       → "无 {page}.spec.ts（...）"
if not mbase or 空值:          → "e2e.app_base_url 为空（...）"
if not _ok:                   → "ENV_ISSUE：e2e.app_base_url 不可达（...）"
```

**后果**：执行器齐备但无触发点；而 `SKIP` 的多义性让人读输出无法归因。

---

## 2. 决策与权衡

### 2.1 核心定案（按独立评审修订）

**D1｜`skip_reason` 只进 JSON，不改人读 detail、不改判定**

`atlas_check --json` 的 E2E 行新增机读字段 `skip_reason`，取值闭集（按 profile + cases/scripts 资产归类，不按早退顺序推断）：

| skip_reason | 判据 | 归属 |
|---|---|---|
| `gate_off` | 无 `e2e.cases_dir` 且无 `e2e.scripts_dir` | 设计结论 |
| `not_declared` | `e2e.app_base_url` 为空 | 缺决策 |
| `app_login_undeclared` | `app_base_url` 已声明、`app_login` 段缺失（§7.1 升档态） | 缺决策 |
| `not_generated` | 已有分片/用例、页面脚本不存在 | 缺工作 |
| `env_not_ready` | `app_base_url` 不可达 | 环境 |

- 人读 `detail` 文本**保持不变**（既有消费者与测试按原文断言）；
- 状态仍为 `SKIP`，退出码语义不变。

**D2｜触发器只做「就绪归因 + 委托既有执行器」，不新增执行路径**

新增 `scripts/e2e_trigger.py`：

- 读 profile / 分片 / 脚本目录，输出 D1 的归因结论；
- 未就绪 ⇒ 打印待办与置位字段，`exit 0`（不阻塞）；
- 已就绪 ⇒ **只输出**下一步命令（`python3 .atlas/scripts/atlas_verify.py --root .`，或 `atlas_check --page <页>`），`--run` 时才代为调用**既有执行器**；**不调用** `gen_e2e_scripts.py --apply`（生成前必须有 §12 独立审查报告，触发器不得绕过；最多做 dry-run 差量报告）；
- 不启动控制台，只打印 `e2e_console.py` 命令（review 由人执行）。

**D3｜挂载点 = Phase 2 最后一轮之前，分两段（版本化 workflow 补丁）**

时序（用户 2026-11-03 拍板）：

```
Phase 2.1 实现
   ↓
【A】E2E 黑盒执行（Phase 2 末尾、最后一轮质量检查之前）
   ↓
Phase 2.2 最后一轮质量检查（lint / build / type-check）
   ↓
Phase 3.4 提交
   ↓
【B】人工 review：启动控制台逐条执行 + 勾选（Phase 3.5 收尾提醒）
```

- 新增补丁目录 `patches/workflow-e2e-trigger/`，三个插入点：
  1. **A 段**：Phase 2 末尾、最后一轮质量检查**之前**插入步骤——`python3 .atlas/scripts/e2e_trigger.py --root . --run`；未就绪只归因、`exit 0` 不阻塞。锚点 = 模板英文 `**Final pass (before Phase 3.4 commit)**` 之前（miss 时 `install.sh` 只 WARN，故补丁带锚点存在断言，并备 `#### 2.3` 形式的插入点片段）；
  2. **B 段**：Phase 3.5 收尾提醒处补一行控制台命令（`python3 .atlas/scripts/e2e_console.py --root .`），**不自动启动**；
  3. `[workflow-state:in_progress]` 与 inline 两个面包屑块各加一行 enforcement（执行期每轮提醒 A 段）。
- **只在最后一次 2.2 之前触发 A**（2.2 是 `[required · repeatable]`，每轮迭代都真跑 = 重活；B 段控制台 review 本身还会再执行一次）。
- 补丁沿用 `patches/workflow-plan-apply/` 的指纹标记形态；`install.sh` 已自动遍历 `patches/*/`，无需新增装配配置（仅需确认片段被纳入）。

### 2.2 考虑过的备选方案及否定理由

- **备选 A：`after_archive` 自动跑** —— 否定：归档晚于验收，且发生在提交之后，错过「实现完成即可迭代」的窗口。
- **备选 B：`atlas_check` 默认常驻真跑** —— 否定：真跑依赖靶场与会话，常驻失败退化成「狼来了」。
- **备选 C：`after_finish` hook** —— 否定：`after_finish` 只清任务指针、触发于提交之后（`task.py finish`），同样晚于实现完成；项目级 hook 需逐项目注册。
- **备选 D：由触发器直接 `gen --apply` + 运行器直跑** —— 否定（评审 Critical）：绕 §12 审查门；直跑会漏 reset/探针/browser/cwd，绿不被门与控制台承认。

### 2.3 刺痛代价与兼容性

- **兼容性**：`skip_reason` 为 JSON 新增字段，人读输出与判定不变；未安装新补丁的项目行为零变化。
- **成本**：触发器为只读归因，毫秒级；真跑成本仍由既有执行器承担。
- **边界**：不解决「有门但无形态」的人工会话问题（§7.1 D103），归因输出 `app_login_undeclared` 并给出人工会话步骤。

---

## 3. 改动面清单

- [ ] **契约/文档**：`rings/e2e/reference.md` §8.1（`skip_reason` 词表与归因；避开 `gates.md` 2.2 行的 1600 字符上限）· `rings/e2e/reference.md` §10（触发段一节）· `apply/reference.md` §7（一行）
- [ ] **代码逻辑**：`scripts/atlas_check.py`（`--json` 增加 `skip_reason`）· `scripts/e2e_trigger.py`（新，只读归因 + 委托）
- [ ] **工作流补丁**：`patches/workflow-e2e-trigger/`（`spec.json` + A 段「最后一轮质量检查前」步骤片段 + B 段「3.5 收尾」控制台命令片段 + 两个 breadcrumb 片段 + 锚点断言）
- [ ] **测试防线**：`tests/test_atlas_check_e2e_skip.py`（五态归因，含 `app_login_undeclared`；detail 原文不变）· `tests/test_e2e_trigger.py`（归因分支、未就绪 exit 0、`--run` 只调用既有执行器、绝不调用 `gen --apply`）· `tests/test_install_*`（新补丁幂等与锚点 miss 行为）
- [ ] **留出验证**：不适用（新增归因字段与触发器，不改既有判据）；触发面核对 = `git diff --name-only` 对照 DR4 路径族（实施时粘贴输出）
- [ ] **版本装配**：`install.sh`（确认 `patches/*` 自动遍历覆盖新目录）· `package.json`（版本号按发布流程）

---

## 4. 验证与测试结果

- **新增测试**：`tests/test_atlas_check_e2e_skip.py`（8 条：五态归因、枚举闭集、`Row.add` 机读字段不污染人读字段）· `tests/test_e2e_trigger.py`（4 条：提示词完备、委托优先 `atlas_verify`、`--page` 走 `atlas_check`、委托段不含生成器）。
- **测试结果**：`python3 -m pytest tests/ -q` ⇒ **1139 passed, 5 skipped**（全量）。
- **自检结论**：`python3 scripts/atlas_check.py --root . --fast` ⇒ `OK`（源包态多数检查 SKIP，属预期）。
- **补丁幂等**：合成 `workflow.md` 上首遍 `applied=4`，第二遍 `skipped=4`（正文指纹一致）。
- **计数守恒**：新增 2 个测试文件后同步更新了写死计数（`shared/gates.md` 51 个测试文件、`docs/map/*` 的行数与数字快照），`test_canonical_consistency` / `test_map_anchors` 复绿。
- **留出验证**：不适用（新增归因字段与触发器，不改既有判据）；触发面核对 = 本次改动路径为 `scripts/`、`patches/`、`rings/e2e/`、`apply/`、`tests/`，不含 DR4 段级锚路径族（实施时以 `git diff --name-only` 复核）。
