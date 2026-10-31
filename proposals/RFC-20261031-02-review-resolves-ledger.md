# 跨轮 finding 闭环台账（resolves，WARN 观察面）

> 提案编号：RFC-20261031-02  
> 提案作者：@sunwenzhe-git  
> 关联状态：已定案 (Accepted)（D5 已实现、待合并）  
> 影响范围：脚本工具 (scripts) | 契约 (shared/independent-review.md) | 门册观测面 (shared/gates.md)  
> 关联取证：2026-10-31 真实 r1/r2 报告（12 条 prior Major 无交代）+ 16 条夹具

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

- [x] `scripts/review_closure.py`（新增，WARN observer）
- [x] `tests/test_review_closure.py`（16 条；M1/M2/M3）
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

* **结果（2026-10-31）**：D5 测试 **16 passed**；全量 **978 passed, 5 skipped**；安装自检 **PASS**；map **8 passed**；`git diff --check` 干净。
* **真实报告**：r1/r2 → `WARN prior 12 unaccounted 12`；r2-v3 单轮目录 → `SKIP`。
* **M1/M2/M3 四段协议**：M1 摘掉 unaccounted 收集 ⇒ `test_unaccounted_warns` 红；M2 把缺取证的 resolves 当已关闭 ⇒ `test_resolves_without_evidence_warns` 红；M3 把 Critical 的 intentional/ignored 当关闭 ⇒ `test_critical_intentional_resolve_warns` 红；均 sha256 还原复绿，日志在 `/tmp/atlas-d5-evidence/`。

### 4.5 留出验证

* 新增观测面，无既有判据可回归；不触发 D156 判据级留出。
* 外部留出：真实 r1/r2 报告（12 条 prior Major）与单轮 r2-v3 目录（SKIP）均不是测试夹具，作为真实语料验证；夹具只证链路。
* 反面包：pre_existing、carried、Major intentional、无指纹回退、坏形状各有用例。

## 5. 开放问题

1. `resolves` 由谁写：当前 triage/人写进 `review.json`；是否给 converter 加 `--resolves` 输入，另案。
2. `intentional/ignored` 对 Major 的关闭语义是否足够；当前允许，Critical 不允许。
3. 升档条件：真实仓连续多轮 WARN 被忽略、且修复闭环有数据后，再议是否进 `atlas_check`；本批不设。
4. 多报告目录/多需求并集不做；跨目录闭环若需要，另案。
