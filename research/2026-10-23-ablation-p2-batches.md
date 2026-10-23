# P2 批次数据 + 影子试点 — 夹具验证

> **性质**：`research/` 非 canonical 证据存档；不进装配、不作为执行契约。
> **日期**：2026-10-23。**范围**：P2 事件行的 3 轮夹具批次 + `validate_e2e_index` 的 3 轮影子试点。
> **重要限制**：这是**夹具批次**，不是真实项目批次；耗时与状态只证明数据链路通了，不能外推为真实项目的成本或误拦率。
> **真实批次 01**（采用方项目快照）已另行采集：见 [research/2026-10-23-ablation-real-batch-01.md](2026-10-23-ablation-real-batch-01.md)。

## 1. 事件行批次（3 轮）

**夹具**：`/tmp/atlas-batch-fixture`，一个最小项目根：`product/stack-profile.yaml` + 一个 E2E 分片 + 一个前端源码文件；`.atlas/validators` 与 `.atlas/scripts` 软链到源包。夹具**故意**包含不一致用例（`home-missing`），所以 3 轮均 `ok=false`；这是夹具设计，不是 P2 的结论。

**命令**（每轮）：

```bash
python3 scripts/atlas_check.py --root /tmp/atlas-batch-fixture --fast --json
```

**事件行结果**（3 轮，逐门耗时 ms）：

| 门 | 状态（3 轮） | 耗时（3 轮） | 中位数 |
|---|---|---|---|
| `validate_e2e_index` | FAIL / FAIL / FAIL | 52 / 44 / 40 | 44 |
| `validate_prd` | FAIL / FAIL / FAIL | 49 / 40 / 35 | 40 |
| `validate_testids` | FAIL / FAIL / FAIL | 47 / 46 / 37 | 46 |
| `validate_stack_profile` | WARN / WARN / WARN | 37 / 38 / 35 | 37 |
| `生成物最新` | SKIP / SKIP / SKIP | 46 / 41 / 42 | 42 |
| 其余 9 行 | SKIP（前置未声明） | `None` | — |

- 事件行 3 条，追加而非覆盖；`ok` 均为 `false`，与退出码 1 一致。
- 有执行段的行带 `duration_ms`；纯 `SKIP` 行为 `None`——这正是「跑了没跑」可区分的最小形态。
- `validate_prd` 在夹具里 FAIL 是因为夹具故意没有 `product/prd/prd.md`，不是 P2 行为变化；真实项目应按自身前置判断。
- 夹具太小，耗时在 35–52ms 量级，**不代表真实项目**；它的价值是证明事件行能被消费，而不是给出成本数字。

## 2. 影子试点（3 轮）

**工具**：`research/shadow_pilot.py`（research 工具，不进装配）。默认只读，账本写项目外；只存门名 / 状态 / 计数 / 耗时 / 输出哈希 / 校验器哈希，不存校验器原文。

**命令**（每轮）：

```bash
python3 research/shadow_pilot.py \
  --root /tmp/atlas-shadow-fixture \
  --gate validate_e2e_index \
  --out /tmp/shadow-ledger.jsonl \
  --label fixture-run-N
```

**结果**：

| 轮次 | would-be 状态 | FAIL 行 | WARN 行 | SKIP 行 | 耗时 |
|---|---|---|---|---|---|
| fixture-run-1 | FAIL | 4 | 1 | 6 | 39ms |
| fixture-run-2 | FAIL | 4 | 1 | 6 | 36ms |
| fixture-run-3 | FAIL | 4 | 1 | 6 | 43ms |

- 3 轮 `output_sha256` 相同（`770bb5079555862d…`），`validator_sha256` 也相同（`0e1fe755b600…`），说明夹具输入与校验器版本稳定、影子结论可复现。
- 影子工具退出码在 FAIL 时为 1（便于脚本判断），但**不阻断任何工作流**；它不在 `atlas_check` 内，也不改校验器。
- 账本 3 行；逐行检查无夹具文案（`首页`）泄漏，只有计数与哈希。
- 运行前后对夹具做了文件哈希清单比对：**逐字节未变**（`validate_e2e_index` 只读）。
- 这次是「受控 would-be block」：夹具本来就有坏用例，影子工具只是把它记录成「如果强制执行会 FAIL」。它不证明真实任务的 would-be block 率。

## 3. 真实批次怎么跑

等下一次真实项目批次结束，跑下面两条命令（**先正常跑，再影子跑**）：

```bash
# 1) 正常门禁：事件行落在项目的 .atlas/runs/check-events.jsonl
python3 <项目根>/.atlas/scripts/atlas_check.py --root <项目根> --fast --json

# 2) 影子：只记录、不阻断；账本默认写 ~/.atlas-shadow/validate_e2e_index.jsonl
python3 <atlas源包>/research/shadow_pilot.py \
  --root <项目根> \
  --gate validate_e2e_index \
  --label <批次ID>
```

**每批次看四个数：**

1. `would_be_status`：影子门本来会不会 FAIL；
2. `fail_lines` / `warn_lines`：如果是 FAIL，红在几条判据上；
3. `duration_ms`：影子门的耗时（C1 的第一个真实样本）；
4. 与正常 `check-events.jsonl` 的交叉：同一批次里其他门是否也红了（判断影子门是否**冗余**）。

**决策规则（先写死，避免事后解释）：**

- 连续 2–3 个真实批次，影子门 `would_be_status = PASS` 且正常门禁无同类 FAIL ⇒ 该门在本项目**当前负载下没有可观测拦截**，进入「观察/候选降档」讨论，但**不直接删**（失败模式可能是低频灾难，参考首跑报告 §4.4 的保险规则）。
- 影子门 FAIL 且正常门禁也 FAIL ⇒ 它是**冗余信号**；查重叠门，讨论合并或降档。
- 影子门 FAIL 但正常门禁 PASS / 未跑 ⇒ 它是**独立信号**；这是最值得保留的证据，记录到台账并考虑升级为正式门。
- 任何情况下都不在真实项目里物理摘门；本阶段只做影子。

## 4. 限制

- **夹具不是真实项目**：3 轮耗时 35–52ms，不能拿去算 C1/C6 的真实成本；真实项目的门耗时要等下一批。
- **没有 token / 人工时长**：影子工具不采集宿主 token；C3/C4 仍为空。
- **A2/A4/A5 仍不可判**：影子只回答「门会不会红」，不回答「门有没有被触发」；后者要靠 `check-events.jsonl` 的 `status=SKIP` 与真实批次日志。
- **单门试点**：本轮只验证 `validate_e2e_index`；其他门（尤其有写副作用的 `validate_testids` / `validate_ac_alignment`）不在本轮影子范围。
- **夹具的状态不代表质量**：`validate_prd` / `validate_testids` 的 FAIL 是夹具故意不完整造成的，不能当真实缺陷。

## 5. 下一步

- 收集 **2–3 个真实批次**的 `check-events.jsonl` + 影子账本；
- 用首跑报告的 T2 口径做一次「影子门 vs 重叠门」对照；
- 再决定是否把影子门升级为正式门、或进入判据级消融。
