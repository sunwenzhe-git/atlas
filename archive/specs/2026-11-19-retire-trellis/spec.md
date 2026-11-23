# Spec：从 Atlas 仓库彻底移除 Trellis

- 状态：已批准并执行完毕（2026-11-19）
- 日期：2026-11-19
- 关联：RFC-20261119-02（Atlas 自建执行层）、RFC-20261103-04（装配单源）
- 目标仓库：`/Users/sunwenzhe/Desktop/atlas`

## 1. 目标与边界

**目标**：Atlas 的执行层已由 `atlas workflow`（`scripts/atlas_workflow.py` +
`_support/workflow_{plan,dispatch,finish}.py`）承载，Trellis 不再是任何运行时、装配、
契约、模板、用户文档的前置依赖。本次把 Trellis 从**当前实现与当前文档**中移除。

**保留（用户已拍板）**：

- 历史记录一律不改：`proposals/`、`research/`、`handoff/`、`CHANGELOG.md`、
  `docs/guide/changelog.md`、`2026-11-17/`、`2026-11-18/`、`.zcode/`、`duty-review/`。
- `docs/guide/comparison.md`：Trellis 作为**对比对象**保留。
- `docs/guide/legacy-adoption.md`：Trellis 作为**迁移来源**保留。
- `proposals/RFC-20261103-04-installer-golden/`：历史 golden 快照在本任务内不改；v0.4.0-beta.1 发版批次按新装配行为统一重录（见 §8）；
  `install.py` docstring 不再声称它是当前验收口令。

**非目标**：不改业务语义；不新增门禁；不做 git commit/push。

## 2. 路径映射（单一约定）

| 旧落点 | 新落点 |
|---|---|
| `.trellis/tasks/<ID>/` | `.atlas/tasks/<ID>/` |
| `.trellis/spec/structure/` | `.atlas/spec/structure/` |
| `.trellis/spec/conventions/` | `.atlas/spec/conventions/` |
| `.trellis/config.yaml`（`spec_injection.max_total_chars`） | `.atlas/config.yaml`（可选，缺省 9500 / 9400） |
| `.trellis/scripts/task.py`（任务卡创建） | `_support/workflow_plan.write_task_card()` 原生写入 |
| `.trellis/.developer` / `TRELLIS_DEVELOPER` | `.atlas/.developer` / `ATLAS_DEVELOPER` |
| `.trellis/workflow.md` 补丁挂载 | 删除；执行顺序由 `atlas workflow` 承载 |

`.atlas/` 的子目录刷新是白名单式（`install.py` 只清空白名单子目录 `shared/`、`rings/`、`apply/`、`scripts/`、
templates/adapters/validators/patches/_support/extensions`），`.atlas/tasks`、`.atlas/spec`、
`.atlas/config.yaml` 属项目态，不会被 `atlas update` 覆盖。

## 3. 运行时改动（精确到文件/函数）

### 3.1 `_support/`

| 文件 | 改动 |
|---|---|
| `layout.py` | `_FORBIDDEN_FIRST_PARTS = frozenset({".atlas"})`（L33）；docstring 同步 |
| `solution.py` | L233-234 内部目录判据与文案去掉 `.trellis`；L826/L839 `_meta.json` 路径；L1297 文案；L1805-1814 装配器调用去掉 `--no-trellis`；L2301 成员任务根；L3567-3578 "Trellis packages" → `.atlas/config.yaml` |
| `solution_seal.py` | L876-879 归档任务路径 `.atlas/tasks/archive/*/...` |
| `solution_task.py` | **重写任务卡创建**：删 `_task_py/_run/_probe`；`_tasks_root(member)=member/".atlas"/"tasks"`；`create` 用 `workflow_plan.write_task_card` 生成 `prd.md`+`task.json`（注入 `solution/requirement/member/assignee` meta）；`solution.md` 指针与 `implement.jsonl`/`check.jsonl` 原样；`_assignee` 读 `ATLAS_DEVELOPER` → `.atlas/.developer` → 主 worktree；`--resume/--update` 语义保持 |
| `workflow_dispatch.py` | L7 去掉 "比 Trellis 减少 80%+" 表述 |
| `review_scope_core.py` | L6 "不阻断 Trellis 的 apply 边界" → "不阻断执行层 apply 边界" |

### 3.2 `scripts/`

| 文件 | 改动 |
|---|---|
| `atlas_workflow.py` | `_read_tasks_root` 恒为 `.atlas/tasks`（删 `.trellis/tasks` 回退分支） |
| `refresh_structure.py` | 全部 `.trellis/spec/structure` → `.atlas/spec/structure`；`read_cfg_int` 读 `.atlas/config.yaml`；`clean_exempt_prefixes` = `{".atlas/", ".adapter-out/"}`；`trellis-update-spec` 文案 → "结构环语义区（AI）"；`add-context` 指引 → `atlas workflow dispatch` |
| `atlas_check.py` | `_meta.json` 路径、无 `.trellis` SKIP 文案 → `.atlas` |
| `atlas_review.py` | 缺省 `--requirement` → `.atlas/tasks/<unit>/prd.md`；help 去 "Trellis task id" |
| `impact_report.py` / `impact_reconcile.py` | 任务落点 `.atlas/tasks/<ID>/`；`cognition.fras` 根 `.atlas/spec/structure` |
| `closeout_derive.py` | 结构环前缀 `.atlas/spec/structure/` |
| `gen_testid_stub.py` | `STUB_REL = ".atlas/spec/conventions/testid.md"` |
| `atlas_apply_seal.py` | 用法示例路径 |
| `atlas_solution.py` | `task` 子命令 help 文案 |
| `run_python.js` | **删除**（唯一用途是 `.trellis/config.yaml` 钩子启动器） |

### 3.3 `validators/`

- `validate_task_card.py`：任务卡 glob → `.atlas/tasks/**/prd.md` 与 `.atlas/tasks/archive/*/*/prd.md`；
  `[N/A]` 判据 → 无 `.atlas/tasks`。
- `validate_e2e_index.py`：任务分片扫描根 → `.atlas/tasks`；structure 根 → `.atlas/spec/structure`。
- `validate_walkthrough.py`：`TASKS_RELPATH = .atlas/tasks`；文案。
- `validate_testids.py`：薄桩路径 → `.atlas/spec/conventions/testid.md`；忽略目录去 `.trellis`。
- `validate_structure.py`：spec 根与 `config.yaml` 路径 → `.atlas/...`。

### 3.4 `adapters/`

`_graph.py`（`structure_root`）、`_lib.py`、`models.py`、`ac/{js,pytest,junit}.py` 的
忽略目录集合去掉 `.trellis`；`_graph.py` 文档串路径改 `.atlas/spec/structure`。

## 4. 装配层改动

### 4.1 `install.py`

1. docstring：删 `--no-trellis`，步骤 5（workflow 补丁）删除，步骤 6 只保留 AGENTS.md /
   extractor 配置 / `.gitignore` / pi 扩展接线；golden 说明改为"历史快照"，v0.4.0-beta.1 由发版批次统一重录。
2. 删 `NO_TRELLIS` 全局与 `--no-trellis` / `--no-patch` 参数；`--profile` 宏：
   `audit = --no-wiring`、`adopt = --no-wiring`、`strict = 无附加旗标`。
3. 删 L407-424（Trellis 检测 / 自动 `trellis init` / 缺 `.trellis` 即 die）。
4. 触点脏树守卫只认 `.atlas/` 与 `AGENTS.md`。
5. 骨架：`.atlas/tasks`、`.atlas/spec/structure/{domains,global}`、`.atlas/spec/conventions`。
6. 删第 5 步与 `apply_patch_pkg()`；步骤编号 `[1/6]..[6/6]` → `[1/4]..[4/4]`。
7. 自检：删 "workflow 补丁应用器"、"Python 启动器"；"structure spec 根" → `.atlas/spec/structure`；
   删 `.trellis/workflow.md` 与 `.trellis/config.yaml` 自检。
8. `solution_update_guard` 等其余逻辑不动。

### 4.2 `install.sh` / `bin/`

- `install.sh`：头部说明同步（去 `--no-trellis/--no-patch` 与第 5 步）。
- `bin/atlas.js`：删 `detectTrellis` 引入与整段 Trellis 自动初始化；`init` help 去
  `--no-patch`/trellis 示例；`update` help 去 `--no-patch`；L566 文案去 `.trellis`。
- `bin/platform.js`：删 `trellisProbe()` / `detectTrellis()` 及导出与注释。

### 4.3 `patches/`

- 删除 `patches/workflow-plan-apply/`、`patches/workflow-e2e-trigger/`、
  `patches/workflow-root-cause/`、`patches/workflow-skill-routing/`（全部只改 `.trellis/workflow.md`）。
- 保留 `patches/project-wiring/`：
  - `apply-wiring.py`：删 `wire_config()` 及 `HOOK_*`/`CONFIG_REL`/`EVENT_*`/`_wire_auto_commit`/
    `_hooks_range`/`_event_lines`/`_refresh_tail`/`_normalize_hook_line`；删 `TRELLIS_END`
    特判（Atlas 段恒在文件末尾追加/原位替换）；`results` = `wire_agents + wire_project +
    wire_gitignore + wire_pi_extension`。
  - `agent-pointer.md` / `README.md`：同步口径。

### 4.4 其它

- `package.json`：删 keyword `"trellis"`。
- `.github/workflows/tests.yml`：删 Trellis probe 步骤与 `detectTrellis()` 断言；
  Windows 用例建的 `.trellis` 目录改 `.atlas`。
- `tests/test_run_python_launcher.py`：删除。
- `scripts/run_playground_*.py`：保留为**对照基准**产物（与 `comparison.md` 同属允许残留）；
  仅把"依赖 Trellis"的措辞改为"旧宿主执行层（Trellis）"。

## 5. 契约 / 模板 / skills / 扩展

| 文件 | 改动 |
|---|---|
| `shared/global-rules.md` | §7 第 3 条签名改为"改 `AGENTS.md` 指针段或装配接线"（保持"四条"计数不变）；§72 结构事实路径；§151 假设落 `.atlas/tasks/<ID>/` |
| `shared/single-source.md` | 需求卡 / 结构事实 / 域清单 / testid 薄桩 / 前端复用记录 → `.atlas/...` |
| `shared/layout.md` | 目录树与落点改 `.atlas/spec/*` + `.atlas/tasks`；保留首段 `{.atlas}` |
| `shared/closeout.md` | impact 路径；"atlas / Trellis 契约"→"atlas 契约"；`trellis mem`→会话上下文；补丁沉淀→`atlas report` |
| `shared/solution.md` | 成员任务 `.atlas/tasks`；"Trellis slug"→"任务 slug"；`.atlas/.developer`；`/trellis:start`→`atlas workflow dispatch` |
| `shared/stack-profile.md` / `gates.md` / `independent-review.md` / `frontend-reuse.md` | 路径与"Trellis 任务 Plan/Design"→"任务卡 Plan / dispatch.md" |
| `rings/structure/reference.md` | 全部落点、hook 段改为"显式 `refresh_structure.py --chain`（收口后 / CI）" |
| `rings/prd/reference.md` / `rings/e2e/reference.md` | `.atlas/spec/structure`、`.atlas/spec/conventions`、`.atlas/tasks`；触发段改为 `atlas workflow verify` 前 |
| `apply/reference.md` | 需求卡路径、§7 "与 Trellis 的挂接"→"与执行层（atlas workflow）的挂接"、§9 patches 整节改写/删除 |
| `templates/*` | 路径替换 |
| `skills/atlas-{apply,structure,prd,e2e}/SKILL.md` | 路径与"Trellis 需求卡"→"执行层任务卡" |
| `extensions/pi.ts` | `hasTrellis`→`hasStructure`（检测 `.atlas/spec/structure/_meta.json`）；状态/提示文案去 Trellis |

## 6. 用户文档

必改：`README.md`（宿主执行器段改为 `atlas workflow`，新增"执行层"章节）、
`RUNBOOK.md`、`DESIGN.md`、`docs/index.md`、`docs/guide/quick-start.md`、
`docs/guide/how-it-works.md`、`docs/concepts/{architecture,layout,rings}.md`、
`docs/design/{overview,structure-ring,distribution,prd-ring,e2e-ring}.md`、
`docs/ecosystem/skills.md`、`docs/innovations/assertions.md`、
`docs/map/{cli,index,apply,graph}.md` 与 `docs/map/atlas-map.html`。

`docs/map/cli.md` 的 `文件:行号` 锚点必须在代码改动后同步（`tests/test_map_anchors.py` 会红）；
`docs/map/gates.md` 的自检声明数 / 用例数等 `〔数:...〕` 计数按最终结果刷新（可跑
`python3 tests/refresh_count_anchors.py`）。

## 7. 验证

1. 定向套件（全绿）：
   `pytest tests/test_atlas_workflow.py tests/test_atlas_review.py tests/test_project_wiring.py
   tests/test_apply_wiring.py tests/test_install_profile.py tests/test_install_selfcheck.py
   tests/test_solution_task.py tests/test_atlas_solution.py tests/test_refresh_facts.py
   tests/test_task_card.py tests/test_validate_walkthrough.py tests/test_validators.py
   tests/test_structure_validator.py tests/test_solution_e2e_validators.py
   tests/test_cli_commands.py tests/test_layout.py tests/test_map_anchors.py
   tests/test_canonical_consistency.py -q`
2. `python3 scripts/atlas_check.py --fast` 全绿。
3. `python3 scripts/ledger_snapshot.py <既定参数>` 账本对齐。
4. 装配实测：`python3 install.py --target /tmp/atlas-trellis-free --dry-run` →
   真实装配 → `--update`；确认无 `.trellis` 产物、无 `trellis init` 提示。
5. 全仓审计：`grep -ri trellis` 仅命中第 1 节"保留"清单与 `comparison.md` /
   `legacy-adoption.md`、`run_playground_*.py`。

## 8. 风险与取舍

- **旧任务迁移**：已有项目里的 `.trellis/tasks` 不自动搬移；`atlas workflow status`
  不再回读 `.trellis/tasks`（彻底移除口径）。迁移在 `legacy-adoption.md` 给出手工命令。
- **structure 刷新的触发时机**：`after_archive` 钩子随 Trellis 一起消失，改为显式
  `refresh_structure.py --chain`（收口后 / CI），文档明确写出。
- **golden 快照**：`proposals/RFC-20261103-04-installer-golden/` 与旧版输出不再逐字节一致，
  本任务内保留为历史基线；v0.4.0-beta.1 发版批次已按无 Trellis 的新装配行为统一重录，
  harness 场景移除 `.trellis` 种子与已退役旗标，`--check` 8/8 通过；`install.py` 仍不引用它为验收口令。
- **solution 成员任务**：由调用 Trellis `task.py` 改为 Atlas 原生写卡，`find_task` /
  `solution.md` / `implement.jsonl|check.jsonl` 语义保持，`shared/solution.md` 同步。

## 9. 批准

批准后按 `tasks.md` 顺序执行；执行中若发现与本 spec 冲突的现状，先停下来说明并请求裁决。
