# 评审范围内容封口 + apply 基线（实例⑤ v4）

> 提案编号：RFC-20261103-01
> 提案作者：Atlas 维护批（用户 2026-11-03 拍板「可以」）
> 关联状态：已合并 (Merged)（2026-11-03，`c80182c`，随 beta.27 发版）
> 影响范围：脚本工具（scripts/）· 共享内核（_support/）· 契约（shared/）· 测试（tests/）
> 关联：`RFC-20261031-01`（实例⑤ coverage / delta）、`RFC-20261031-02`/`RFC-20261101-02`（跨轮闭环）、`RFC-20261101-03`（签字取证严格化）；`shared/independent-review.md` §3/§11、`shared/closeout.md` 步骤 10、`shared/gates.md` 2.1「实现代码 ⇔ 应然资产」行。
> 外部参照：`didi/helixharness` 的 `archive-preflight --review-choice` / `accept-review-drift`（只借「内容快照 + 受控确认」语义，不引入其流程状态机）。

---

## 1. 现象与取证

### 1.1 触发形态（抽象）

* **规则 / 环节**：实例⑤实现代码独立审查的落盘门 `scripts/validate_review_report.py`，报告契约 `review.json` v3。
* **触发时机**：报告落盘后，开发者又改了被审文件（未提交或已暂存），再拿同一份 `review.json` 去收口。
* **具体行为**：`review.json` 只有 `head_sha`（commit 锚）与 `reviewed_files`（路径列表），**没有文件内容摘要**；校验器只验形态、状态映射、N/M，不读被审文件内容。commit 不变时，改一字节仍 `PASS`。

### 1.2 客观证据（最小复现，2026-11-03 实跑）

```bash
# 1) 造一份 v3 PASS 报告，reviewed_files=["src_a.ts"]
# 2) 校验：PASS
# 3) 把 src_a.ts 内容从 "a = 1" 改成 "a = 2"（不动 commit、不动 review.json）
# 4) 再校验：
$ python3 scripts/validate_review_report.py --dir "$TMP/report"
  [PASS] 状态映射复算（§3 写死 + §6 下限）
  [PASS] 应审/实审对账（§6 第 8 条）
PASS
```

**同类历史证据**：`scripts/make_review_inputs.py` 模块 docstring 记录过基线副本漂移——「某轮快照只有 24 条用例、当前 35 条，拿它当审查期基线做 diff 会得出错误结论」。本提案把「内容哈希」从审查**输入侧**（已有 `MANIFEST.json`）补到审查**结论侧**（`review.json`）。

### 1.3 为什么现在必须补

- 2026-10-31 已有真实仓副本 r1/r2 跑通（`shared/gates.md` 2.1 行），入口与转换器都活了；r2 修复后 r1 报告仍会被复验，没有内容锚就无法区分「原样提交」与「又改了」。
- `reviewed_files` 只证明「CLI 说审了这些路径」，不证明「现在这些路径还是当时那份内容」。N/M 对账防的是少审，不防内容漂移。

---

## 2. 决策与权衡

### 2.1 核心定案

1. **scope 只覆盖 CLI 实审集**，不覆盖全工作区。
   - 集合 = delta 的 `reviewed_files`（coverage.completed / 显式 `--reviewed-files`）；非 delta 用 `--reviewed-files` 或 `coverage.completed`。
   - 全工作区会把并行 WIP 的无关改动卷进来，任何无关编辑都让门恒假红 —— 门一旦日常可遇就会被绕过。
2. **新增 `_support/review_scope_core.py`**（纯标准库）：给定路径列表生成内容清单 `{path, status, sha256, size}` + 根 `scope_sha256`；提供 `verify` 复算与 `baseline` 脏工作区基线。
3. **`review.json` 升 schema v4**，新增：
   ```json
   "review_scope": {
     "manifest": "scope-manifest.json",
     "sha256": "<64 hex>",
     "files": [{"path": "src/a.ts", "status": "M", "sha256": "<64 hex>", "size": 123}]
   }
   ```
   v3 及以下**不要求**该字段；v4 报告缺它 ⇒ FAIL。v4 只由「带 `--scope-manifest` 的新落盘报告」产生，**不回扫存量**。
4. **校验器只对本轮新产出报告复算**：`validate_review_report.py --scope-manifest <file>` 才复算；不带该参数时，v4 报告记 `WARN: scope 未复算（未提供 manifest）`，不 FAIL。存量 v2/v3 报告一律不因此变红。
5. **跨轮观察面归 `review_closure.py`**：读各轮 `review_scope.files`，若 prior 轮的文件内容已变且该路径不在最新轮实审集 ⇒ WARN（非门）；带 `review_scope_drift` 用户确认的按确认处理。
6. **受控降级 `--accept-scope-drift <sha256> --accept-by <name> --accept-reason <text> --user-confirmed`**：把用户显式确认写进新报告 `review_scope_drift`，标记 `reviewed=false`，不伪装成已复审；缺 `--user-confirmed` 或签字/理由为空 ⇒ exit 2。
7. **apply 基线并入同一工具**：`review_scope.py baseline --unit <ID>` 记录 apply 起始既有 dirty 集；`baseline-check` 对比当前 dirty，未变化自动排除，与本次改动的重叠才 WARN。**只告警不阻断**（Atlas 不拥有 Trellis 的 apply 边界）。

### 2.2 考虑过的备选方案及否定理由

* **备选 A：全工作区 scope（staged/unstaged/untracked 全收）**
  * 否定理由：并行 WIP 常态下恒假红；评审范围应与 CLI 实审集一致，而不是整个工作区。
* **备选 B：校验器每次自动复算，存量报告一律复算**
  * 否定理由：r2 修复后 r1 报告必然不再匹配，历史报告会被追溯判红；「报告落盘时」与「事后复验」是两件事。
* **备选 C：用 `git diff` 的 tree hash 代替内容哈希**
  * 否定理由：未提交/暂存内容不在 tree 里；`reviewed_files` 的当前工作区内容才是要验的对象。
* **备选 D：另建 `scope.json` 作为第二真相源**
  * 否定理由：`review_scope` 必须嵌在 `review.json`（门只读它），manifest 只是随报告归档的输入侧证据；closu​re 读报告字段，不读旁路文件。
* **备选 E：把 apply 基线独立成门**
  * 否定理由：Atlas 不拥有 Trellis 的 apply 边界，阻断会误伤；合并进同一工具，只出 WARN。

### 2.3 刺痛代价与兼容性

- v4 只对新报告生效；v2/v3 存量报告 100% 兼容（新增字段不参与旧版本映射）。
- 大文件（>10 MiB）与二进制：记录 `size` + `mtime_ns`，`hash_mode: "size_mtime"`，并在 `review_scope` 显式标注「不可逐字节复算」；不静默当作内容哈希。
- 符号链接：拒绝（避免逃逸项目根）；路径含 `..` 或绝对路径拒绝。
- 性能：只哈希实审集，不扫全仓；哈希按 1 MiB 分块流式读取。
- 运行态：`apply-baseline.json` 落 `.atlas/runs/<unit>/`（已 gitignore），不进 canonical 产物。

---

## 3. 改动面清单

- [x] **契约/文档**：`shared/independent-review.md` §3（v4 字段与复算窗口）、§11（跨轮 scope 观察）；`shared/closeout.md` 步骤 10（`--scope-manifest` 用法）；`shared/gates.md` 2.1 新增/扩展「评审范围内容封口」行；`docs/concepts/review.md` 同步。
- [x] **代码逻辑**：
  - 新增 `_support/review_scope_core.py`（哈希/清单/复算/基线）。
  - 新增 `scripts/review_scope.py`（manifest / verify / baseline 三子命令）。
  - 改 `_support/review_policy.py`（`validate_v4_report_fields`）。
  - 改 `scripts/cli_review_convert.py`（`--scope-manifest`、`--accept-scope-drift`、v4 写入）。
  - 改 `scripts/validate_review_report.py`（`--scope-manifest`、v4 形态、复算窗口）。
  - 改 `scripts/review_closure.py`（跨轮 scope 漂移 WARN / accepted）。
- [x] **测试防线**：
  - 新增 `tests/test_review_scope.py`（manifest / verify / baseline，含 M165/M168）。
  - 扩展 `tests/test_review_report.py`（v4 形态、stale/fresh、v3 兼容，含 M165）。
  - 扩展 `tests/test_cli_review_convert.py`（v4 写入、manifest 对账、drift 确认，含 M166）。
  - 扩展 `tests/test_review_closure.py`（跨轮漂移、覆盖后不告警、accepted，含 M167）。
- [x] **版本装配**：`install.sh` / `package.json.files` 已覆盖 `scripts/`、`_support/`、`tests/`，无需新增路径；`atlas_check` 的 `VALIDATORS` 不变（新门属于既有 `validate_review_report` 的扩展，不新增校验器）。
- [ ] **留出验证（§4.5）**：实现批回填。

---

## 4. 验证与测试结果

**实现批实跑（2026-11-03）**：

```bash
$ python3 -m pytest tests/test_review_scope.py tests/test_review_report.py \
      tests/test_cli_review_convert.py tests/test_review_closure.py -q
165 passed in 36.03s

$ python3 -m pytest tests/ -q
1089 passed, 5 skipped in 627.84s (0:10:27)  # 最终全量；随后新增 1 条 converter 用例，目标套件 165 条全绿

$ python3 scripts/atlas_check.py --fast
OK   # 源包态：多数校验器因未装配 .atlas/ 而 SKIP（如实 SKIP，不是通过）
```

**端到端手测**（临时 git 仓，manifest → converter v4 → validator）：
- 新鲜报告带 `--scope-manifest` ⇒ `[PASS] 评审范围内容封口（v4）`；
- 改一字节后再验 ⇒ `[FAIL] 实审文件内容已变化`，exit 1；
- `review_closure` 在内容变化且未纳入最新实审集时 ⇒ `scope_drift 1` WARN；
- `--accept-scope-drift … --user-confirmed` ⇒ `scope_drift_accepted 1`，不告警。

### 4.5 留出验证（系统性修复必填）

- **触发面核对**：本次改门/校验器判据（`validate_review_report`、`cli_review_convert`、`review_closure`、新增 `review_scope`），触发 D156。路径交叉检查原始输出：
  - `git diff --name-only`：`CHANGELOG.md` / `README.md` / `_support/review_policy.py` / `_support/review_scope_core.py` / `docs/concepts/review.md` / `docs/gates/iron-gates.md` / `docs/map/*` / `scripts/cli_review_convert.py` / `scripts/review_closure.py` / `scripts/review_scope.py` / `scripts/validate_review_report.py` / `shared/closeout.md` / `shared/gates.md` / `shared/independent-review.md` / `skills/atlas-apply/SKILL.md` / `tests/test_*.py`（共 20+ 文件）。
  - `python3 scripts/closeout_derive.py --diff-base HEAD`：本轮改动 25 文件（自有对账面 14）；派生步骤 **1 / 2 / 3 / 5 / 7**；`[WARN] atlas 自有面文件未命中任何触发行：_support/review_policy.py`、`_support/review_scope_core.py`。
  - **WARN 处置（显式盲区，不在本 RFC 扩族）**：`_support/` 不在任何触发表路径族，属**既有**缺口（`review_policy.py` 在本次改动前同样 WARN；`tests/test_closeout_derive.py::test_atlas_owned_unmatched_warns_each_path` 明确要求 unknown `_support/` 出声）。本 RFC 不顺手改触发表族（会动既有判据与测试），登记为残留风险；新文件继承同一 WARN。
- **留出集**：**无独立留出集**。本次是新增内容封口判据，不是对既有判据的修补；可得的真实语料（2026-10-31 r1/r2 报告目录）不在仓内，无法构造独立于开发夹具的留出案例。
- **pre-fix 红**：§1.2 已给出现状实测——同一份 v3 PASS 报告，被审文件从 `a = 1` 改成 `a = 2` 后校验器仍 `PASS`（该门修前红不了，正是本提案的病）。
- **post-fix 绿**：`test_v4_stale_scope_fails` / `test_v4_fresh_scope_passes` / `test_scope_drift_unreviewed_warns` / `test_baseline_excludes_unchanged_and_flags_overlap` 全绿；全量 1089 passed（最终全量；新增 1 条用例已在目标套件 165 条内全绿）。
- **变异证明（四段协议）**：四枚注入均按预期红并逐字节还原（sha256 一致）：

  | 变异 | 注入点 | 结果 | 还原 sha256 |
  |---|---|---|---|
  | M165 | `validate_review_report.py` 摘掉 scope 复算 | `test_v4_stale_scope_fails` 红 | `18048f1b4b9e…` |
  | M166 | `cli_review_convert.py` 摘掉 manifest 文件集对账 | `test_v4_manifest_set_mismatch_refused` 红 | `ca836dcb6f34…` |
  | M167 | `review_closure.py` 摘掉漂移收集 | `test_scope_drift_unreviewed_warns` 红 | `cff4f1995f53…` |
  | M168 | `review_scope_core.py` 摘掉 baseline overlap | `test_baseline_excludes_unchanged_and_flags_overlap` 红 | `9d9ec48226c0…` |

- **三态结论**：**单案修复（无留出集）**。须评审确认「确无可行留出集」；`duty-review/QUEUE.md` 已挂观察行（owner = 本批实施者；补验期限 = 首个真实实例⑤多轮运行后 2 周）；残留风险 = ① `_support/` 触发表族缺口（继承既有 WARN）；② v4 尚未跑真实仓多轮语料，跨轮 `scope_drift` 的误报率未知；③ 大文件 `size_mtime` 不是逐字节封口（已在报告显式标注）。**不宣称闭族。**


---

## 5. 验收判据（机器可判）

1. `review_scope.py manifest` 生成确定性排序的清单；同内容两次生成 `scope_sha256` 相同。
2. `review_scope.py verify`：改一字节 ⇒ exit 1；只改 mtime ⇒ exit 0；删除文件 ⇒ exit 1。
3. `cli_review_convert.py --scope-manifest`：manifest 文件集 ≠ 实审集 ⇒ exit 2，且不留半截产物。
4. `validate_review_report.py --scope-manifest`：stale ⇒ FAIL；fresh ⇒ PASS；不带 manifest 的 v4 ⇒ WARN；v3 存量 ⇒ 不受影响。
5. `review_closure.py`：prior 内容变化且未纳入最新实审集 ⇒ WARN；纳入且哈希一致 ⇒ 不告警；`review_scope_drift` 签字齐全 ⇒ 记录为 accepted，不告警。
6. `review_scope.py baseline`：基线内未变化路径自动排除；与本次改动重叠 ⇒ WARN；基线文件缺失 ⇒ WARN（不是 PASS）。
7. 变异：M165 摘掉校验器复算 / M166 摘掉 converter 文件集对账 / M167 摘掉 closure 漂移检测 / M168 摘掉 baseline 重叠检测 ⇒ 对应用例红；四段协议还原逐字节一致。

---

## 6. 开放问题（实现时定）

1. `review_scope.files` 是否要包含 `status`（M/A/??/clean）？——初版包含，便于人读；不参与 `scope_sha256`（只哈希 path + content hash），避免 git 状态噪声让门抖动。
2. 大文件 `size_mtime` 模式下，`scope_sha256` 是否仍算「内容封口」？——显式标注 `hash_mode`，校验器对该模式只 WARN「不可逐字节复算」，不冒充强封口。
3. `baseline` 的 dirty 集合是否包含 ignored 文件？——不包含（`git status --porcelain` 默认不列 ignored；与净场协议一致）。
4. 是否把 `atlas review` 编排一起做？——本 RFC 不做；编排属 RFC-2，依赖本 RFC 的 `--scope-manifest`。
