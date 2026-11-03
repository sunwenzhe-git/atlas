# atlas eval：消融对照跑分器

> 提案编号：RFC-20261103-06
> 状态：已合并 (Merged)（2026-11-03，`f17bc82` + 评审修复 `0fae0be`，随 beta.27 发版；独立评审「修后落地」B1/B2/M1–M5 与 m2/m7 均已落）
> 影响范围：脚本工具（scripts/）· CLI（bin/）· 契约（shared/gates.md 登记）· 测试（tests/）
> 关联：`RFC-20261101-04`（消融事务工具）、`research/2026-10-25-net-contribution-ledger.md`（30 案三档证据）、`research/2026-11-01-ablation-real-batch-02.md`（真实批次）、`shared/gates.md` 2.5（流程门）。
> 外部参照：HelixHarness 的 base/candidate + 同一 Case 集 + regression gate 闭环；**只借闭环形状，不借其 UI / mock 演示**。

---

## 1. 现象与取证

### 1.1 已有能力与缺口

- **已有**：`scripts/ablation.py`（begin/restore/run/status，项目外状态根、三方还原、smoke 复算）；`scripts/mutation_proof.py`（四段协议：基线绿 → 注入红 → 逐字节还原 → 复绿）；`research/2026-10-25-net-contribution-ledger.md`（30 案、三档证据 A/B/C、每条四锚）；`research/2026-11-01-ablation-real-batch-02.md`（三个真实快照 + P5-A 前后配对）。
- **缺口**：没有「同一组 case、base/candidate 两个 commit、一条命令跑完并出机读 ledger」的跑分器；没有「pass→fail / 门全绿数下降」的回归门；每批消融仍靠人记命令、手工拼表。
- **不是缺口**：消融事务本身（`ablation.py` 已覆盖）；变异证明本身（`mutation_proof.py` 已覆盖）；净收益叙事（现有台账明确拒绝「反事实 / 净收益」判据，本 RFC 不碰）。

### 1.2 客观证据

- `research/2026-10-25-net-contribution-ledger.md` 开头写明「非 canonical、不进装配、不作为门」「单项目单周不可外推」；`research/2026-11-01-ablation-real-batch-02.md` 用「三个真实快照 + 3 轮同快照重复」手工跑。
- `scripts/ablation.py` 的能力边界是「物理摘除 / 还原事务」，不是「两个 commit 的对照跑分」；`run` 子命令只跑一个命令，不产出 case 级 ledger。
- `scripts/mutation_proof.py` 是单门四段协议，不是多 case 批量回归。

---

## 2. 决策与权衡

### 2.1 核心定案（最小闭环）

1. **新增 `scripts/atlas_eval.py` + `atlas eval`**，两个子命令：
   - `atlas eval run --cases <registry.json> --base <sha> --candidate <sha> --out <dir> [--timeout 300] [--retries 1] [--worktree-root <dir>] [--keep-worktrees]`
   - `atlas eval gate --ledger <file> [--out <file>]`（gate_green 判据在同一 ledger 内部：candidate < base ⇒ FAIL；无需基线 ledger）
2. **隔离 = git worktree**：`git worktree add --detach <tmp>/base <base>` / `<tmp>/candidate <candidate>`；case 命令在各自 worktree 的**项目根**执行；`shlex.split` + `shell=False`（与 `ablation.py run` 同口径）；每 case 独立 timeout。
3. **case 注册表 = 指针索引，不是第二真相源**：
   ```json
   {
     "schema_version": 1,
     "gate_command": "python3 .atlas/scripts/atlas_check.py --fast",
     "cases": [
       {"id": "M165", "kind": "mutation", "anchor": "tests/test_review_report.py::test_v4_stale_scope_fails",
        "command": "python3 -m pytest tests/test_review_report.py::test_v4_stale_scope_fails -q"},
       {"id": "C-08", "kind": "bug", "anchor": "DESIGN.md#| D105 |",
        "command": "python3 -m pytest tests/test_atlas_check.py::test_e2e -q"}
     ]
   }
   ```
   - case `kind` 为**可选自由文本**（不校验闭集、不参与判据——评审 m1：不参与判据就不设拒入门）。**不收** `bugs.md` 条目（已修即出库，指针会悬空）、**不收**真跑 E2E 快照（真机噪声，另案）。
   - 锚对账（base / candidate 两侧各判一次，统一机制）：`path::node` ⇒ 收集器收集（注册表可选 `anchor_collector`，缺省 `sys.executable -m pytest`；**只按退出码判**——节点名含 error/timeout 子串不再误杀，评审 B1）；`path#fragment` ⇒ 文件含片段（登记口径：表格锚建议带行分隔符如 `#| D101 |`，防交叉引用误判存在——评审 m2，机制不校验）。candidate 侧缺失 ⇒ `anchor_missing=true` 且**不参与 pass/fail 分类**；`gate` 判 FAIL。
   - `anchor_ok_base=false`（candidate 新增）：base 侧跳过执行记 `skipped`；candidate 红 ⇒ `new_red` ⇒ **gate FAIL**（评审 M2：新增即红不是「基线本来就红」，不得落 f2f-WARN）；candidate 绿 ⇒ `new_ok` 记录不判。
   - `--retries N`（默认 1）：pass→fail 的 case 在 candidate 侧复跑确认，复跑绿 ⇒ 不定罪（节拍类口径承自 `duty-review/bugs.md` 同根归纳②）；ledger 记 `retries_used`。
4. **ledger = JSON + 一行摘要**：
   ```json
   {"schema_version": 1, "base": "<sha>", "candidate": "<sha>",
    "cases": [{"id","kind","anchor_ok","base_status","candidate_status","base_ms","candidate_ms","error"}],
    "summary": {"pass2pass": N, "pass2fail": N, "fail2pass": N, "fail2fail": N, "anchor_missing": N},
    "gate_green": {"base": N|null, "candidate": N|null}}
   ```
5. **回归判据（评审后四条）**：
   - 任一 case `pass→fail` ⇒ FAIL（`--retries` 复跑确认，防节拍类抖动定罪）；
   - `anchor_missing` ⇒ FAIL；`new_red`（candidate 新增即红）⇒ FAIL；
   - `gate_green.candidate < gate_green.base` ⇒ FAIL（同一 ledger 内对照；解析不到 ok/PASS ⇒ `null` + WARN，不 FAIL）。
   - `fail2fail` 只 WARN（基线本来就红）；`fail2pass` / `new_ok` 记录不判。
6. **不宣称净收益 / 反事实**：ledger 只记录「同一 case 在两个 commit 的可复算状态」；「净贡献」叙事仍归 research 台账，不入 gate。
7. **不建 UI、不进 `atlas_check`**：`atlas eval gate` 是独立 CLI/CI 门；`shared/gates.md` 2.5 登记为流程门（非自动门），真实采用前不升级。

### 2.2 备选方案与否定理由

- **A：从 `bugs.md` 自动派生 case**
  - 否定理由：`bugs.md` 修好即出库，自动派生会把「已删除的案」当 case；且字段是自然语言，派生规则必脆。注册表只存稳定锚（D 行 / 测试节点），人写一次。
- **B：把 `gate_green` 当硬判据、缺 gate_command 直接 FAIL**
  - 否定理由：Atlas 源包态 `atlas_check` 多数校验器 SKIP（无 `.atlas/` 装配），会把「环境未装配」误判成回归；缺省只 WARN，显式传 `gate_command` 才判。
- **C：把「净贡献不降」写进 gate**
  - 否定理由：现有台账明确「反事实叙述只作口径不作判据」；写成 gate 会重蹈不可复算的账。
- **D：用 `ablation.py` 做 base/candidate**
  - 否定理由：`ablation.py` 是「物理摘除 + 还原」事务，不管理两个 commit；混用会把事务状态和跑分状态搅在一起。
- **E：跑真跑 E2E 快照作 case**
  - 否定理由：真机/后端/登录态噪声大，且当前无稳定靶场；另案，不入首版。

### 2.3 代价与兼容性

- worktree 创建 / 清理有成本；默认清理，`--keep-worktrees` 留现场调试。
- case 命令依赖各 worktree 的环境（Python/pytest/node）；缺依赖 ⇒ case `error`，不是 PASS。
- 注册表与 ledger 落项目外 / `.atlas/runs/`（gitignored），不新增 canonical 产物。
- 单项目、单环境、有限 case 集 ⇒ **不宣称可外推**；ledger 头部继承「单项目单周」腿注字段（`note`）。

---

## 3. 改动面清单

- [x] **代码**：新增 `scripts/atlas_eval.py`；`bin/atlas.js` 新增 `case 'eval'` 转发 + help。
- [x] **契约/文档**：`shared/gates.md` 2.1 新增「eval 回归门」行（独立 CLI，不进 atlas_check）；`CHANGELOG.md`；`docs/map/cli.md` 命令面与行数。
- [x] **测试**：新增 `tests/test_atlas_eval.py` 18 条。
- [x] **样本注册表**：`research/eval-cases.example.json`（只作格式示例，不宣称覆盖全集）。

---

## 4. 验证与测试结果

**实现批实跑（2026-11-03；评审修后批同步回填）**：

```bash
$ python3 -m pytest tests/test_atlas_eval.py -q
18 passed in 14.89s

$ python3 -m pytest tests/ -q        # 工作树落定态（含 gate-registry 批在途修复）
1127 passed, 5 skipped in 452.74s
```

端到端手测（临时 git 仓：base=flag.txt+gate.py 3 行 ok；candidate=删 flag.txt+gate.py 2 行 ok+新增红/绿测试）：

| case | base → candidate | anchor(base/cand) | 判定 |
|---|---|---|---|
| C1 pytest 节点 | pass → pass | ok/ok | pass2pass |
| C2 flag.txt 存在性 | pass → fail | ok/ok | pass2fail |
| C3 恒红命令 | fail → fail | ok/ok | fail2fail（只 WARN） |
| C4 `docs/nope.md#X` | skipped → pass | missing/MISSING | 锚缺失，不参与分类 |
| error 命名节点 | pass → pass | ok/ok | **B1 正钉：不被子串误杀** |
| candidate 新增红测试 | skipped → fail | missing/ok | **new_red ⇒ gate FAIL** |
| candidate 新增绿测试 | skipped → pass | missing/ok | new_ok 只记录 |
| 节拍类（首跑红复跑绿） | pass → pass | ok/ok | `--retries 2` 不定罪，retries_used=1 |

`gate` 一次命中：`pass→fail：C2` / `锚缺失：C4` / `gate_green 下降：3 → 2`，exit 1；f2f 只 WARN。

**变异证明（四段协议）**：

| 变异 | 注入点 | 结果 | 还原 sha256 |
|---|---|---|---|
| M171 | `cmd_gate` 摘掉 pass→fail 检测 | `test_gate_regression_alone_fails` 红 | `e79348f48fca…` |
| M172 | `cmd_gate` 摘掉锚缺失 FAIL | `test_gate_anchor_missing_alone_fails` 红 | `e79348f48fca…` |
| M173 | `check_anchor` 退回子串判据（评审 B1） | `test_error_named_anchor_not_killed` 红 | `3d07a311e22a…` |

### 4.5 留出验证与独立评审记录（合并版；替代此前两段各自为政的 §4.5）

- **触发面核对**：新增独立评测 CLI，未改 `atlas_check` / 既有校验器判据，未挂收口；触发 (a) 无引子族锚、无 ≥3 条独立审查重复 finding，触发 (b) 是**新增门**而非改既有判据（D156 ③ 明拒「每 RFC 强制留出」）⇒ **不适用**，如实声明而非逃检。
- **独立评审记录（2026-11-03，tech-proposal-reviewer，只读）**：结论「修后落地」。B1（锚收集 `"error"` 子串误杀合法锚——已实测复现）/ B2（提交态 `test_gate_registry` 形态门先在红，验收自报不实）/ M1（p→f 无复跑防抖）/ M2（新增即红落 f2f-WARN）/ M3（worktree 三条泄漏路径）/ M4（锚收集器解释器错位）/ M5（文档-实现五处漂移）/ m1–m8。**处置**：B1、M1、M2、M3、M5 与 m4/m5/m6/m8 已在本批修掉并加钉（上表 M173；`--retries` / `new_red` / `--worktree-root` / `anchor_collector` 均为评审直接产出）；m1（kind 砍闭集）、m2（fragment 登记口径）、m3（砍 --baseline 幽灵 + 注册表指纹）、m7（并发覆盖帮助注记）同步落。**原未修项已清**：gates 行的 fragment 口径注记已随 gate-registry 批（`44e9fde`）落在 `shared/gates.md` 2.1 行。
- **B2 如实记录**：`f17bc82` 提交态 `shared/gates.md` 的 `E2E 真跑` 行超长（11,696 字符）+ 三行 7 格，`test_gate_registry` 形态门在该 commit 先在红——**先在红，非 eval 行引入**（parent `60511d0` 同样红；eval 行自身 6 格、1,296 字符合规）；在途 gate-registry 批已把这些行修到合规（归属他案）。本批修后以**工作树落定态**全量复跑留痕：1127 passed / 5 skipped；修前一轮全量曾因 eval 行计数 `10 ≠ 18` 红（已回填），playground 单轮 flake 一次（单测复跑与全量均绿）。验收「全量绿」以落定态为准。
- **已知残留**：case 命令依赖 worktree 内环境（缺 pytest ⇒ error；两侧同缺 = f2f 只 WARN）；`gate_command` 在源包态无意义（null 跳过），适合装配后的采纳仓；并发同 `--out` 会覆盖 ledger（帮助注记，单用户工具）。

---

## 5. 验收判据

1. `atlas eval run` fixture 全链 exit 0，ledger JSON 字段齐全，case 状态分类正确。
2. `atlas eval gate` 对 pass2fail / gate_green 下降 ⇒ exit 1；全绿 ⇒ 0；`fail2fail` 只 WARN。
3. anchor 缺失 ⇒ 该 case `anchor_missing=true` 且 gate FAIL，不静默 SKIP；**该 case 不参与 pass/fail 分类**（无效 case 不得计入 pass2pass）。
4. 节拍类防抖：首跑红复跑绿的 case（`--retries`）⇒ 不定罪；恒红 ⇒ 仍判回归。
5. candidate 新增即红 ⇒ gate FAIL（`new_red`）；candidate 新增且绿 ⇒ `new_ok` 只记录。
6. worktree 默认清理、部分失败回滚、run 前 prune、`--keep-worktrees` 保留；失败不吞错误。
7. 全量测试绿（落定态）；`atlas eval` 不出现在 `atlas_check` 自动门列表里（独立门，避免自指）。
