# Tasks：彻底移除 Trellis

依赖顺序执行；每完成一批先跑对应测试，不把红门带到下一批。

## T1 运行时路径与原生任务卡

- [x] `_support/layout.py`：保留首段只剩 `.atlas`
- [x] `_support/solution.py`：内部目录判据、`_meta.json`、任务根、packages 检查、`--no-trellis` 调用
- [x] `_support/solution_seal.py`：归档任务路径
- [x] `_support/solution_task.py`：原生写任务卡（`workflow_plan.write_task_card`），`ATLAS_DEVELOPER` / `.atlas/.developer`
- [x] `_support/workflow_dispatch.py`、`_support/review_scope_core.py`：表述
- [x] `scripts/atlas_workflow.py`：删 `.trellis/tasks` 回退
- [x] `scripts/refresh_structure.py`：路径 / `.atlas/config.yaml` / 豁免前缀 / 文案
- [x] `scripts/{atlas_check,atlas_review,impact_report,impact_reconcile,closeout_derive,gen_testid_stub,atlas_apply_seal,atlas_solution}.py`
- [x] `validators/{validate_task_card,validate_e2e_index,validate_walkthrough,validate_testids,validate_structure}.py`
- [x] `adapters/{_graph,_lib,models}.py`、`adapters/ac/{js,pytest,junit}.py`
- 验证：`pytest tests/test_atlas_workflow.py tests/test_solution_task.py tests/test_refresh_facts.py tests/test_task_card.py tests/test_validate_walkthrough.py tests/test_structure_validator.py tests/test_solution_e2e_validators.py -q`

## T2 装配层

- [x] `install.py`：删 `--no-trellis`/`--no-patch`、Trellis 前置、第 5 步、`apply_patch_pkg`；骨架与自检改 `.atlas`；步骤编号
- [x] `install.sh`：头部说明
- [x] `bin/atlas.js`、`bin/platform.js`：删 Trellis 探测与自动 init
- [x] 删除 `patches/workflow-{plan-apply,e2e-trigger,root-cause,skill-routing}/`
- [x] `patches/project-wiring/apply-wiring.py`：删 `wire_config` 与 hook 机制、`TRELLIS_END` 特判
- [x] `patches/project-wiring/{agent-pointer.md,README.md}`
- [x] 删除 `scripts/run_python.js` 与 `tests/test_run_python_launcher.py`
- [x] `package.json` keyword、`.github/workflows/tests.yml`
- 验证：`pytest tests/test_install_profile.py tests/test_install_selfcheck.py tests/test_project_wiring.py tests/test_apply_wiring.py tests/test_cli_commands.py -q`；`python3 install.py --target /tmp/atlas-tf --dry-run`

## T3 契约 / 模板 / skills / 扩展

- [x] `shared/{global-rules,single-source,layout,closeout,solution,stack-profile,gates,independent-review,frontend-reuse}.md`
- [x] `rings/{structure,prd,e2e}/reference.md`、`apply/reference.md`
- [x] `templates/*`
- [x] `skills/atlas-{apply,structure,prd,e2e}/SKILL.md`
- [x] `extensions/pi.ts`
- 验证：`pytest tests/test_map_anchors.py -q`（契约锚点）、人工通读 §7 四条签名

## T4 用户文档

- [x] `README.md`（执行层章节 + 去 Trellis 前置）
- [x] `docs/guide/quick-start.md`、`docs/guide/how-it-works.md`
- [x] `docs/concepts/{architecture,layout,rings}.md`
- [x] `docs/design/{overview,structure-ring,distribution,prd-ring,e2e-ring}.md`
- [x] `docs/ecosystem/skills.md`、`docs/innovations/assertions.md`、`docs/index.md`
- [x] `docs/map/{cli,index,apply,graph}.md`、`docs/map/atlas-map.html`（锚点/计数同步）
- [x] `RUNBOOK.md`、`DESIGN.md`
- 验证：`pytest tests/test_map_anchors.py tests/test_canonical_consistency.py -q`

## T5 计数与门禁

- [x] `shared/gates.md` 计数（自检声明、用例数、门册行）刷新
- [x] `docs/map/index.md` 数字快照刷新
- [x] 定向全套 + `python3 scripts/atlas_check.py --fast` + 账本快照

## T6 全仓审计

- [x] `grep -ri trellis` 只剩：`proposals/`、`research/`、`handoff/`、`CHANGELOG.md`、
      `docs/guide/changelog.md`、`2026-11-1x/`、`.zcode/`、`duty-review/`、
      `docs/guide/comparison.md`、`docs/guide/legacy-adoption.md`、`scripts/run_playground_*.py`、
      `proposals/RFC-20261103-04-installer-golden/`
- [x] 汇报残留分类与理由
