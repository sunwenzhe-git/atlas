# REVIEW-20261026-06 · Batch A 后端维度门实现评审

> **对象**：当前工作区 Batch A / D153 实现（基线 `d762ea4`）
> **评审者**：pre-commit-reviewer（只读）
> **时点**：2026-10-26（初评「修后通过」→ 2026-10-26 修复复核）

## 总判定：修后通过 → 修复复核通过

初评：主骨架已忠实落地（E2E 只做 `_parse_dims` 纯抽取、D130 判据未动、无 Batch B、无 `apply-wiring`/索引解析改动；后端列、AST `dims`、active/weak、通道 N/A、`atlas_check`/`atlas_verify` 的 N/A 可见性均已实现），但有 6 条必修：模板占位制造假声明、E2E 零变化缺 golden/行为钉、M156 证据哈希失配、跨 PRD 重复/混合未知 token 静默、扫描面未点名、契约把扫描面为空写成 N/A。修复复核后全部落，见文末。

## 逐问判定

1. **范围忠实：通过（初评有保留，已修）。** `validate_e2e_index.py` 的 diff 只有 `ac_coverage` 导入与调用替换；`declared_ac_dims`/`bad_case_dims`/`total_declared` 逻辑未动；`validate_structure.split_row`、`atlas_verify` 窄解析、`apply-wiring`、`MAIN_COLUMNS`/`tables`/`gather_shards` 未碰；`grep def _parse_dims` 已无定义；D130 回归与全量套件绿。初评指出 `DIM_CLAIM_RE` 是第二份 token 正则、`iter_md_tables` 未入单源守卫；复核已把两者收进 `_support/ac_coverage.py` 并纳入 `test_shared_kernel` 的唯一性白名单。
2. **后端列解析：通过（初评有保留，已修）。** 表头定位、3/4/5/6 列、第 4 列后端表头 WARN、备注列 WARN、标准 4 列 E2E N/A、空/`N/A`/`—`/`-`、自由文本 WARN、非 3 位 AC WARN 均实测通过。初评的跨 PRD 同 AC 同维度静默、`C01,C99` 混合未知 token 静默已修：重复声明无条件 WARN（同维度也报）；`unknown_dim_tokens` 出声未知 token；备注列 `AC-C01-001` 不再被误判（`(?<!AC-)`）。
3. **AST 与证据强度：通过（初评有保留，已修）。** 精确 token、marker AC vs docstring AC、多 AC/空/非字面量/未知/孤儿、`skip`/`xfail`/`skipif`/`parametrize(marks=...)`/`pytest.param`/类级与模块级 `pytestmark`、`skipif(False)`、类方法 `(file,line)` 去重、`*_test.py`/语法错误扫描面均已实现；新增 6 列、`dims=[]`、`parametrize`/`pytest.param`、`enforce` 维度缺口等测试。初评指出类/模块 `pytestmark=skip` 只进 weak 不进 skipped；这是既有 `无效跳过拦截` 的边界（本批不改既有四判据），已在 `shared/gates.md` 的“不查什么”保留语义，未假称已被该门接住。扫描面/解析失败 detail 已点名文件（前 3 个）。
4. **通道与 N/A：通过（初评有保留，已修）。** `apps` 缺失、无 backend/fullstack、多后端、`backend_test` 缺失、非 pytest、`test_dir` 缺失/缺省的分界与 RFC 一致；早退 N/A、`Result.status` 全 N/A、`atlas_check` 子项 N/A 只进 detail、整门 N/A 才行级 N/A、`atlas_verify._parse_rows` 接受 N/A 均已实现并有测试；正常 E2E PASS 含 `[N/A ] manual` 不会被误标。初评的契约写反已修：扫描面为空/无 `test_*.py` ⇒ WARN；`backend_test` 段缺失改为「后端维度子项 N/A，既有 AC 对账仍按缺省 test_dir 扫描」；`atlas_check`/`iron-gates`/`docs/map` 状态清单加入 N/A；新增 `--json` 整门 N/A 测试。
5. **单源：通过（初评有保留，已修）。** E2E 与后端门确实使用同一 `ac_coverage.parse_dims_cell` 对象；`allowed` 覆盖三个解析函数及 `iter_md_tables`/`split_md_row`/`has_dim_claim`/`unknown_dim_tokens`；`validate_structure.split_row`、`atlas_verify` 窄解析、`parse_block` 别名未被误碰。初评要求的 golden 与 monkeypatch 行为钉已落：`tests/fixtures/e2e_coverage_dims_golden.json`（7 组语料）+ `test_ac_coverage_golden_file` + `test_e2e_dimension_check_uses_shared_parser`（monkeypatch 共享函数，E2E 输出必须变化）；M156f 改为「本地点调用」行为红，非同名 wrapper。
6. **测试与变异：通过（初评近否决，已修）。** 计数真实：`test_validate_ac_alignment.py` 39（7 既有 + 32 新增）、`test_atlas_check.py` 45、`test_atlas_verify.py` 11、`test_shared_kernel.py` 12、`test_validators.py` 147；全量 **743 passed / 4 skipped**；测试直接调用门，非 mock 门。M156a–f 已在最终代码上重跑，原/后 sha256 与当前 `validate_ac_alignment.py`（`e32463…`）、`validate_e2e_index.py`（`4c6cb2…`）一致；M156d 是行为红（WARN 断言），M156f 是行为钉红（baseline PASS vs 注入 WARN），不是语法/用法错误；原始输出 `.atlas/runs/mutation-proof/`。
7. **文档/计数：通过（初评有保留，已修）。** `install.sh` 720 行/56 条 `check`、`atlas_check.py` 932 行、`_support` 10 件、`shared/gates.md` 39/45/56、`docs/map` 9→10/719→720/55→56/924→932、`atlas-map.html` 内核 ×10/56 条一致；`README`/`docs/gates/iron-gates.md`/`templates/e2e/case-shard.md`/legacy-adoption（`rings/templates/` 已随 E1 退役，本行仅历史指称）的「第 4 列 E2E、后端列第 5 列、`mode` 只管挂载」一致。初评的模板占位已改为空；新增真实模板测试；`docs/gates/iron-gates.md:101` 与 `templates/e2e/case-shard.md:26` 已改「E2E 闭集/通道」；`docs/map/gates.md` 的 `check_validators :203`、`check_factory :244`、`_gate_preconditions :68` 已修正。
8. **强宣称验伪：通过（初评有保留，已修）。** 标准 4 列 E2E 零影响（N/A，不 WARN）；备注列 `AC-C01-001` 不再误报；「E2E 行为不变」由 diff + D130 测试 + golden/行为钉支持；「N/A 不是通过」对子项/行状态成立，`backend_test` 缺失时明确为「后端维度子项 N/A、既有 AC 对账仍扫」；「M156a–f 全咬」证据哈希与当前文件一致；「743 passed / 4 skipped」与 `install.sh` 空目录探针 exit 0 为真。
9. **安全与副作用：通过。** `ast.literal_eval` 仅用于字面量，无 eval/exec/命令注入；解析器只读；`validate_ac_alignment` 的 baseline 写入仍是既有行为（FAIL 不写；早退 N/A 不写）；`install.sh` 自检新增 `_support/ac_coverage.py`，实测空目录 exit 0 且文件落盘；`.atlas/runs/mutation-proof` 未被跟踪/打包。
10. **未跟踪记录：通过（初评有保留，已修）。** `proposals/README.md` 的 BACKLOG 指针正确；`BACKLOG` §8 已改为「D153 契约层已落地，执行层 EL-01/EL-02 仍待」；`REVIEW-20261026-05` 的「5 条必修全部落」现为事实（golden/行为钉与模板占位已补）；`DESIGN.md` 模板声明与实现一致。

## 必修项（初评 6 条，全部已落）

1. 模板占位改空 + 真实模板测试（`test_backend_real_template_placeholder_na`）。
2. E2E 零变化 golden + monkeypatch 行为钉（`e2e_coverage_dims_golden.json` / `test_e2e_dimension_check_uses_shared_parser`）。
3. M156a–f 在最终代码上重跑，哈希一致；M156f 改为本地点调用的行为红。
4. 跨 PRD 同 AC 同维度 WARN；`C01,C99` 混合未知 token WARN；备注列 `AC-C01-001` 不误报。
5. 扫描面/解析失败 detail 点名文件（前 3 个）。
6. 契约纠偏：扫描面为空 ⇒ WARN；`backend_test` 缺失 ⇒ 后端维度子项 N/A；`atlas_check`/`iron-gates`/`docs/map` 状态清单加 N/A；`--json` N/A 测试。

## 建议项（初评，已采纳的部分）

- `iter_md_tables`/`split_md_row`/`has_dim_claim`/`unknown_dim_tokens` 纳入单源 allowed；`DIM_CLAIM_RE` 改为共享函数并排除 `AC-` 前缀。
- 补 6 列、`dims=[]`、`parametrize`/`pytest.param`、`enforce` 维度缺口、`--json` N/A 测试。
- 修正 `docs/map` 的 `check_validators`/`check_factory`/`_gate_preconditions` 旧行号锚。
- 更新 `BACKLOG` 与 `REVIEW-05` 的落地状态。
- 给 `validate_ac_alignment` 加共享函数对象钉（`vaa.parse_dims_cell is ac.parse_dims_cell`）。

## 结构级问题

- 初评指出的「单源靠同名 def」「skipped 与 weak 语义分裂」「模板未受门保护」已分别用 allowed/行为钉、契约边界说明、真实模板测试收口；`docs/map` 的“注释即符号”假活已手工修正锚点。无新增结构级 blocker。

## 附：修复复核证据

- `python3 -m pytest tests/ -q` ⇒ **743 passed / 4 skipped**（199.21s）。
- `tests/test_validate_ac_alignment.py` 39、`test_atlas_check.py` 45、`test_atlas_verify.py` 11、`test_shared_kernel.py` 12、`test_validators.py` 147。
- `install.sh --target /tmp/atlas-probe --force` ⇒ exit 0；`.atlas/_support/ac_coverage.py` 落盘；56 条 check。
- M156a–f：原/后 sha256 与当前文件一致（`e32463…` / `4c6cb2…`）；M156d 行为红（WARN 断言）；M156f 行为钉红（baseline PASS → 注入 WARN）。
- `tests/test_canonical_consistency.py` / `test_map_anchors.py` / `test_install_selfcheck.py` ⇒ 27 passed。
- 未修改仓库；所有探针在 `/tmp`，变异输出在 `.atlas/runs/mutation-proof/`（未跟踪）。
