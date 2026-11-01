# 跨轮 finding 闭环台账（resolves，WARN 观察面）

> 提案编号：RFC-20261031-02  
> 提案作者：@sunwenzhe-git  
> 关联状态：已合并 (Merged)（`8ae589d` + 评审修订 `43dca7f`，ff 入 main）  
> 影响范围：脚本工具 (scripts) | 契约 (shared/independent-review.md) | 门册观测面 (shared/gates.md)  
> 关联取证：2026-10-31 真实 r1/r2 报告（12 条 prior Major 无交代）+ 19 条夹具

---

## 1. 现象与取证

### 1.1 触发形态

* **环节**：实例⑤报告目录的 `findings/<unit>.r<round>.json` 多轮单元文件；报告形态门只看最新 `review.json`。
* **行为**：上一轮未关闭的 Critical/Major 如果在新一轮既没有被同指纹重报，也没有显式处置，会被静默丢掉；契约又要求「同一问题跨轮不得重复贴」，不能用强制重报来补。
* **实测**：真实 r1/r2 报告（`2026-10-31`）r1 12 条 Major（3 high + 9 medium）在 r2 既未重报、也无 `resolves`；最新轮只有 1 条 Major（修复引入的新问题）。此前没有任何机器面能发现这 12 条旧问题「不再可见」。

### 1.2 证据

```text
review_closure @ <真实 r1/r2 报告>   WARN
rounds 2  prior 12  carried 0  resolved 0  unaccounted 12
# r2-v3 单独目录（只有 r2 一轮）→ SKIP（<2 轮，合法降级）
```

## 2. 决策与权衡

### 2.1 核心定案

**D5：独立 `scripts/review_closure.py` WARN 观察面；不建 FAIL 门、不进 `atlas_check`。**

* 触发：报告目录有 ≥2 轮 `findings/<unit>.r<round>.json`；`python3 .atlas/scripts/review_closure.py --dir <报告目录>`。
* 对象：上一轮 `Critical|Major` 且 `pre_existing != true` 且未带签字+取证关闭的 finding。
* 最新轮处理：
  * 同 fingerprint 仍在且 open ⇒ `carried`（仍可见，不告警）；
  * 同 fingerprint 已带签字+取证关闭（`fixed`/`false_positive`）⇒ `resolved`（via re-reported）；
  * 不在最新轮，但 `review.json.resolves` 声明关闭 ⇒ `resolved`（via resolves）；
  * 两者都没有 ⇒ `unaccounted` WARN。
* `resolves` 形状：`[{fingerprint, status, by?, evidence?, round?}]`；`status ∈ {fixed,false_positive,intentional,ignored}`；`fixed`/`false_positive` 必须带 `by`+`evidence`；**Critical 只接受 fixed/false_positive**（intentional/ignored 不算关闭）；Major 可 intentional/ignored。unknown fingerprint ⇒ WARN；重复/坏形状 ⇒ exit 2。
* **级别从严（修订 R1）**：是否算关闭按**上一轮的级别**判，不按新一轮声明的级别——否则「先把 Critical 降成 Major，再挂 intentional」即可免签。prior Critical 在新一轮不再是 Critical 时，除 `carried` 外另记 `level_downgraded` WARN。
* **孤儿文件（修订 R2）**：`findings/` 里不属于本 `unit` 的单元文件不得静默跳过 ⇒ WARN。跨轮改 `--unit` 名会让闭环义务凭空清零并退化成 `SKIP`，正是本器要治的形态。
* 输出：报告目录 `closure.json` + 一行摘要；退出码 0（PASS/WARN/SKIP），2（输入错误）；<2 轮 SKIP。
* 非门：不进入 `atlas_check`；`shared/closeout.md` 步骤 10 在报告形态门之后手动跑；能力成熟后再议升档。

### 2.2 被否方案

* **塞进 `validate_review_report.py` FAIL**：跨轮语义 + 存量报告会形成永久红门；先 WARN 观察。
* **强制同 fingerprint 重报**：与「同一问题跨轮不得重复贴」直接冲突；carried 不是关闭。
* **自动按启发式关闭**：`fixed` 的语义真实性不可机判；必须带签字 + 取证。
* **converter 自动写 resolves**：当前由 triage/人声明；后续可加 `--resolves` 输入，不在本批。

### 2.3 边界

* `resolves` 的 `fixed` 语义是否真实、证据是否够——仍归独立审查/人。
* 只处理报告目录内最新轮与 prior unit 文件；跨报告目录、跨需求不并集。
* `pre_existing` 不计入闭环义务；`reused`/`waived` 不在本批扩展。
* 不自动修 finding；不替代 `validate_review_report` 或域收口。

## 3. 改动面

- [x] `scripts/review_closure.py`（新增，WARN observer；288 行）
- [x] `tests/test_review_closure.py`（19 条；M1–M5）
- [x] `shared/independent-review.md` §11（新增跨轮闭环契约）
- [x] `shared/closeout.md` 步骤 10（报告形态门后跑 closure）
- [x] `shared/gates.md` §4（候选观测面，非门）
- [x] `docs/concepts/review.md`、`docs/gates/iron-gates.md` §8、`docs/map/review.md`、`docs/map/atlas-map.html`、`README.md`
- [x] `DESIGN.md` D179；`CHANGELOG.md` / `docs/guide/changelog.md`

## 4. 验证

```bash
pytest tests/test_review_closure.py
pytest tests/
python3 tests/test_install_selfcheck.py
```

* **结果（2026-10-31 首版）**：D5 测试 **16 passed**；全量 **978 passed, 5 skipped**；安装自检 **PASS**；map **8 passed**；`git diff --check` 干净。
* **结果（2026-11-01 修订 R1/R2 后）**：D5 测试 **19 passed**；全量 **981 passed, 5 skipped**；`review_closure.py` 288 行。
* **真实报告**：r1/r2 → `WARN prior 12 unaccounted 12`；r2-v3 单轮目录 → `SKIP`。
* **M1/M2/M3 四段协议**：M1 摘掉 unaccounted 收集 ⇒ `test_unaccounted_warns` 红；M2 把缺取证的 resolves 当已关闭 ⇒ `test_resolves_without_evidence_warns` 红；M3 把 Critical 的 intentional/ignored 当关闭 ⇒ `test_critical_intentional_resolve_warns` 红；均 sha256 还原复绿，日志在 `/tmp/atlas-d5-evidence/`。
* **M4/M5 四段协议（修订后补）**：基线 `19 passed` → 注入 M4（`state_of(c, item.get("level"))` 退回 `state_of(c)`）⇒ `test_prior_critical_downgraded_is_not_closed` 红、18 绿 → 注入 M5（删 `orphans.append(path.name)`）⇒ `test_orphan_unit_file_warns` 红、18 绿 → sha256 `ba4ef58…46cb2c` 逐字节还原 → `19 passed` 复绿。

### 4.5 留出验证

* 新增观测面，无既有判据可回归；不触发 D156 判据级留出。
* 外部留出：真实 r1/r2 报告（12 条 prior Major）与单轮 r2-v3 目录（SKIP）均不是测试夹具，作为真实语料验证；夹具只证链路。
* 反面包：pre_existing、carried、Major intentional、无指纹回退、坏形状各有用例。

### 4.6 只读评审发现的两条静默绕过（2026-11-01 修订）

首版实现有两处可把 D5 的结论「悄悄变绿」，均由只读评审提出、主审在真实代码上复现后修复。

**R1 —— 关闭判定只看新一轮级别 ⇒ 降级即免签。**

`state_of()` 的 Critical 保护读的是**最新轮** `level`，于是 r1 的 open `Critical` 只要在 r2 用同一指纹
把 `level` 写成 `Major` + `disposition=intentional`（无 `disposition_by`/`disposition_evidence`），
就被判 `resolved`、整体 `PASS`：

```text
# 修复前：r1 Critical(FP-A) / r2 同指纹 Major+intentional
review_closure @ .../d5-verify-b1   PASS   rounds 2 prior 1 carried 0 resolved 1 unaccounted 0
```

修法：`state_of(check, obligation_level)` 用**上一轮的级别**判关闭（prior Critical 只接受带取证
的 `fixed`/`false_positive`）；另把「prior Critical 在新一轮不再是 Critical」单独记
`level_downgraded` + WARN——否则级别可以一轮一轮往下洗而无痕。修复后同一夹具：

```text
review_closure @ .../d5-verify-b1   WARN   rounds 2 prior 1 carried 1 resolved 0 unaccounted 0 warnings 1
  · prior Critical（round 1 `a.ts:10-12`）新一轮降级为 'Major' —— 仍按未关闭跟踪
```

**R2 —— `findings/` 里非本 unit 的文件被静默 `continue` ⇒ 闭环义务凭空清零。**

`load_prior_rounds()` 只认 `<unit>.r<N>.json`，其余文件名一律跳过；而 `--unit` 每轮自由传入。
r1 用 `REQ-1`、r2 写成 `REQ-1-delta` ⇒ 没有上一轮文件可读 ⇒ **`SKIP`，零告警**，磁盘上那条未关闭
`Critical` 无人认领：

```text
# 修复前：findings/REQ-1.r1.json 有 open Critical；review.json unit=REQ-1-delta round=2
review_closure @ .../d5-verify-b2   SKIP   rounds 1 prior 0 ... unaccounted 0
```

修法：不匹配本 unit 的文件收进 `orphans`，有孤儿即 WARN（`prior_rounds` 为空时不再退化成 SKIP），
摘要行打印 `warnings N` 与逐条明细。修复后同一夹具：

```text
review_closure @ .../d5-verify-b2   WARN   rounds 1 prior 0 ... warnings 1
  · findings/ 有 1 个非本 unit 的单元文件未纳入闭环（跨轮 unit 改名或一目录多 unit）：['REQ-1.r1.json']
```

**新增钉子（编号属本文件）**：M4 = 把关闭判定改回按新一轮级别 ⇒ `test_prior_critical_downgraded_is_not_closed` 红；
M5 = 孤儿文件重新静默跳过 ⇒ `test_orphan_unit_file_warns` 红。四段协议（基线绿 → 注入红 → sha256 逐字节还原 → 复绿）
日志在 `/tmp/atlas-d5-evidence/`；`test_prior_critical_rereported_as_critical_passes` 为正例对照，防止把正常重报刷红。

**评审提出但未在本批改的（记录理由）**：

* prior `level` 非闭集（小写/缺失）会放过义务 —— 形态门 `validate_review_report` 对 `level` 闭集已经 FAIL，属既有防线覆盖。
* `resolves` 在 <2 轮的 SKIP 路径不校验形状 —— 无义务项时校验只制造噪声；输入错误面维持「有声明才判」。
* `closure.json` 写盘无异常保护 —— 与 `cli_review_convert` 写 `review.json` 同一假设（报告目录可写），不做单独兜底。
* converter 加 `--resolves` 入口 —— 属 §5 第 1 条另案，不在本批。
* 跨轮 unit 一致性没有硬约束 —— 先按 WARN 观察；升档与 §5 第 3 条同轨。

## 5. 开放问题

1. `resolves` 由谁写：当前 triage/人写进 `review.json`；是否给 converter 加 `--resolves` 输入，另案。
2. `intentional/ignored` 对 Major 的关闭语义是否足够；当前允许，Critical 不允许。
3. 升档条件：真实仓连续多轮 WARN 被忽略、且修复闭环有数据后，再议是否进 `atlas_check`；本批不设。
4. 多报告目录/多需求并集不做；跨目录闭环若需要，另案。
