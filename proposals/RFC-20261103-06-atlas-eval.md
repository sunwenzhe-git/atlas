# atlas eval：消融净贡献的最小可重复跑分器

> 提案编号：RFC-20261103-06
> 状态：已实现（Implemented，待独立评审/合并；评审子代理因用量窗口未派出，改为按评审清单主会话自查——修正两处见 §4.5）
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
   - `atlas eval run --cases <registry.json> --base <sha> --candidate <sha> --out <dir> [--timeout 300] [--keep-worktrees] [--json]`
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
       {"id": "C-08", "kind": "bug", "anchor": "DESIGN.md#D101",
        "command": "python3 -m pytest tests/test_atlas_check.py::test_e2e -q"}
     ]
   }
   ```
   - 只收两类：`mutation` / `bug`（`kind` 只作人读分类，不参与判据——统一锚机制见下）。**不收** `bugs.md` 条目（已修即出库，指针会悬空）、**不收**真跑 E2E 快照（真机噪声，另案）。
   - 锚对账（统一机制，candidate worktree 内）：`path::node` ⇒ `pytest --collect-only -q`；`path#fragment` ⇒ 文件含片段。缺失 ⇒ 该 case `anchor_missing=true` 且**不参与 pass/fail 分类**（无效 case 不得计入 pass2pass）；`gate` 判 FAIL（不静默 SKIP）。
4. **ledger = JSON + 一行摘要**：
   ```json
   {"schema_version": 1, "base": "<sha>", "candidate": "<sha>",
    "cases": [{"id","kind","anchor_ok","base_status","candidate_status","base_ms","candidate_ms","error"}],
    "summary": {"pass2pass": N, "pass2fail": N, "fail2pass": N, "fail2fail": N, "anchor_missing": N},
    "gate_green": {"base": N|null, "candidate": N|null}}
   ```
5. **回归判据只有两条**：
   - 任一 case `pass→fail` ⇒ `gate` FAIL；
   - `gate_green.candidate < gate_green.base` ⇒ FAIL（若两侧都有整数；缺 `gate_command` / 解析不到 ⇒ `null` + WARN，不 FAIL）。
   - `fail2fail` 只记 WARN（基线本来就红，不是本批回归）；`fail2pass` 允许（改进）。
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

- [ ] **代码**：新增 `scripts/atlas_eval.py`；`bin/atlas.js` 新增 `case 'eval'` 转发 + help。
- [ ] **契约/文档**：`shared/gates.md` 2.5 新增「eval 回归门」行；`CHANGELOG.md`；`docs/map/cli.md` 命令面与行数。
- [ ] **测试**：新增 `tests/test_atlas_eval.py`（fixture：两 commit、pass2pass / pass2fail / fail2fail、anchor missing、gate_green 下降、worktree 清理、dry-run/keep）。
- [ ] **样本注册表**：`research/eval-cases.example.json`（只作格式示例，不宣称覆盖全集）。

---

## 4. 验证与测试结果

**实现批实跑（2026-11-03）**：

```bash
$ python3 -m pytest tests/test_atlas_eval.py -q
10 passed in 7.14s
```

端到端手测（临时 git 仓：base=flag.txt+gate.py 3 行 ok；candidate=删 flag.txt+gate.py 2 行 ok）：

| case | base → candidate | anchor | 判定 |
|---|---|---|---|
| C1 pytest 节点 | pass → pass | ok | pass2pass |
| C2 flag.txt 存在性 | pass → fail | ok | pass2fail |
| C3 恒红命令 | fail → fail | ok | fail2fail（只 WARN） |
| C4 `docs/nope.md#X` | pass → pass | **MISSING** | 锚缺失，不参与分类 |

`gate` 一次命中三类失败：`pass→fail：C2` / `锚缺失：C4` / `gate_green 下降：3 → 2`，exit 1；f2f 只 WARN。

**变异证明（四段协议）**：

| 变异 | 注入点 | 结果 | 还原 sha256 |
|---|---|---|---|
| M171 | `cmd_gate` 摘掉 pass→fail 检测 | `test_gate_regression_alone_fails` 红 | `e79348f48fca…` |
| M172 | `cmd_gate` 摘掉锚缺失 FAIL | `test_gate_anchor_missing_alone_fails` 红 | `e79348f48fca…` |

### 4.5 留出验证

- **触发面**：新增独立评测 CLI，未改 `atlas_check` / 既有校验器判据，未挂收口 ⇒ D156 路径：不适用。
- **评审说明**：tech-proposal-reviewer 因用量窗口未派出；改按评审清单主会话自查，两处修正已落实现——① 门登记 2.5 → **2.1**（元规则「不在本表=不存在」适用一切自动门）；② gate_green 解析不到 ok/PASS 行 ⇒ **null + WARN 跳过**（源包态 `atlas_check` 大量 SKIP，不得把「未装配」判成回归）。独立评审可在用量窗口恢复后补跑，结论并入本节。
- **已知残留**：case 命令依赖 worktree 内环境（缺 pytest ⇒ error；两侧同缺 = f2f 只 WARN）；`gate_command` 在源包态无意义（null 跳过），适合装配后的采纳仓。

- fixture 仓库：3 个 commit（base / candidate-regression / candidate-clean），case 命令 = `python3 -c ...`（无外部依赖）。
- `run`：产出 ledger、pass2pass / pass2fail / fail2fail 分类正确、`anchor_missing` 抓得到、worktree 默认清理、`--keep-worktrees` 保留。
- `gate`：pass2fail ⇒ exit 1；全 pass2pass ⇒ 0；`gate_green` 下降 ⇒ 1；`gate_green` null ⇒ 0 + WARN；`fail2fail` ⇒ 0 + WARN。
- 变异：M171 摘 pass2fail 检测 ⇒ gate 用例红；M172 摘 anchor 对账 ⇒ anchor 用例红。

### 4.5 留出验证

- **触发面**：新增独立 CLI 门，不修改 `atlas_check` / 既有校验器判据；D156 路径待评审确认是否适用。若评审认定触发，按「单案修复（无留出集）」登记 QUEUE 观察行，不宣称闭族。

---

## 5. 验收判据

1. `atlas eval run` fixture 全链 exit 0，ledger JSON 字段齐全，case 状态分类正确。
2. `atlas eval gate` 对 pass2fail / gate_green 下降 ⇒ exit 1；全绿 ⇒ 0；`fail2fail` 只 WARN。
3. anchor 缺失 ⇒ 该 case `anchor_missing=true` 且 gate FAIL，不静默 SKIP；**该 case 不参与 pass/fail 分类**（无效 case 不得计入 pass2pass）。
4. worktree 默认清理；`--keep-worktrees` 保留；失败不吞错误。
5. 全量测试绿；`atlas eval` 不出现在 `atlas_check` 自动门列表里（独立门，避免自指）。
