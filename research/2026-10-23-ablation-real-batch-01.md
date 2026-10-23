# 真实批次 01 — 采用方项目快照

> **性质**：`research/` 非 canonical 证据存档；不进装配、不作为执行契约。
> **日期**：2026-10-23。**对象**：由维护者提供的真实采用方项目根（已装配 Atlas；本文不落产品名、绝对路径、业务 case ID）。
> **范围**：一次真实快照的 `atlas_check --fast` **3 轮同快照重复** + `validate_e2e_index` 影子 3 连跑；未跑真跑 E2E，未改项目源码 / 生成物 / 契约。
> **受控补样**：真实批次 01 缺的「影子 FAIL / 正式不失败」「影子 PASS / 正式 FAIL」「两者 FAIL」三形态，已在隔离副本用受控注入补齐（E2 级），见 [research/2026-10-23-ablation-controlled-batches.md](2026-10-23-ablation-controlled-batches.md)。

## 1. 执行与还原

- **装配态**：`.atlas/VERSION` 指向 npm 全局源包；项目 `.atlas/validators` 为 9 个校验器，源包编排器当前含 10 个（多出 `validate_walkthrough`，项目侧无此文件 ⇒ `SKIP`）。
- **运行命令**：用源包 `scripts/atlas_check.py --root <项目根> --fast --json`（带 P2 事件行），未使用项目内旧编排器。
- **快照/还原**：运行前快照 `.atlas/runs/`、`product/e2e/` 与 `.trellis/spec/conventions/testid.md`；运行后把 `check-events.jsonl` 复制到临时证据目录，**删除项目内新事件行**，并从快照还原 `backend-ac-alignment.json`。
- **结果**：项目 `git status` 运行前后一致；`product/e2e` 与 testid 薄桩的哈希清单**逐文件未变**；`.atlas/runs/` 只剩运行前那一个基线文件，sha256 与快照一致。

## 2. 真实门禁结果（3 轮同快照重复）

`atlas_check --fast`：3 轮退出码均为 0；每轮 16 行，0 FAIL / 5 WARN / 3 SKIP / 8 ok。

| 状态（3 轮） | 门 | 耗时（3 轮 ms） | 中位数 |
|---|---|---|---|
| ok | `validate_stack_profile` | 33 / 33 / 32 | 33 |
| WARN | `validate_structure` | 63 / 56 / 55 | 56 |
| WARN | `validate_e2e_index` | 56 / 54 / 51 | 54 |
| WARN | `validate_testids` | 1014 / 845 / 816 | **845** |
| ok | `validate_e2e_mocks` | 34 / 35 / 42 | 35 |
| ok | `validate_ac_alignment` | 38 / 37 / 37 | 37 |
| ok | `validate_prd` | 49 / 50 / 50 | 50 |
| ok | `validate_design_exemptions` | 29 / 29 / 29 | 29 |
| SKIP | `validate_adr` | `None` | — |
| SKIP | `validate_walkthrough` | `None` | — |
| WARN | `生成物最新` | 47 / 46 / 47 | 47 |
| WARN | `审查报告形态` | 0 / 0 / 0 | 0 |
| ok | `执行串行` | 0 / 0 / 0 | 0 |
| SKIP | `结构漂移` | `None` | — |
| ok | `装配版本` | 65 / 18 / 17 | 18 |
| ok | `写面残留` | `None` | — |

**读数：**

- 已计时门总和：1428 / 1203 / 1176ms（中位 **1203ms**）；首轮偏慢是冷缓存（`装配版本` 65ms → 18/17ms）。
- `validate_testids` 单门：1014 / 845 / 816ms，中位 **845ms**，占已计时门总和 **69.4–71.0%**（中位约 70%）。它是当前唯一的大头；其余门都在 0–56ms 量级。
- 本快照 3 轮都没有 FAIL；WARN 集中在 structure / e2e-index / testids / 生成物 / 审查报告五个面，状态 3 轮一致。
- `validate_walkthrough` 的 SKIP 是「源包编排器 vs 项目装配态」差异，不是项目缺陷；`写面残留` 是源包新增行，项目侧无对应资产。
- `审查报告形态` / `执行串行` 的 0ms 是真实极快路径，不是没跑；`duration_ms` 为 0 与 `None` 在事件行里语义不同。
- 每轮运行前后 `product/e2e` 与 testid 薄桩的哈希清单**逐文件未变**；每轮后 `.atlas/runs/` 都还原到运行前状态。

## 3. 影子试点（`validate_e2e_index`，3 连跑）

| 轮次 | would-be 状态 | FAIL 行 | WARN 行 | N/A 行 | 耗时 |
|---|---|---|---|---|---|
| real-snapshot-1 | WARN | 0 | 1 | 2 | 62ms |
| real-snapshot-2 | WARN | 0 | 1 | 2 | 52ms |
| real-snapshot-3 | WARN | 0 | 1 | 2 | 54ms |

- 3 轮输出哈希相同，校验器哈希相同；项目文件在影子运行前后未变（该门只读）。
- 影子门 **WARN** 与正式 `validate_e2e_index` 行的 **WARN** 一致：本快照里它**没有独立拦截信号**，不会阻断任何东西。
- 唯一 WARN 是「持久化写复断言」判据；另有 2 条 N/A（覆盖维度 / seed × models）。这是判据面的提示，不是业务缺陷；本文不复述具体 case ID。
- 影子耗时（52–62ms）与正式行（中位 54ms）同量级，说明影子没有引入明显的额外成本。

## 4. 这轮真实数据说明什么

**能说明：**

1. P2 事件行在真实装配项目里可用：16 行、逐门耗时、状态、退出码一致；运行后项目可还原到原状。
2. 成本高度集中：`validate_testids` 中位 845ms，吃掉已计时门总和的约 70%；判据级消融已补（E2，隔离副本）：提取器复用可省约 110ms/14% 且输出逐字不变，删判据几乎不省时间——详见 [research/2026-10-23-ablation-testids-criterion.md](2026-10-23-ablation-testids-criterion.md)。
3. 影子门在当前快照里没有独立价值信号：它与正式门同 WARN，0 FAIL；不能据此说它无用，只能说明**这个快照没有需要它单独拦的东西**。
4. 项目当前是「零 FAIL、多 WARN」态；WARN 的处置成本（人读 5 行）比 FAIL 更值得下一步量化。

**不能说明：**

- 不能算真实误拦率 / 阻塞率：只有 1 个快照，0 FAIL；分母太小。
- 不能算 token / 人时：本轮没有采集。
- 不能外推 `validate_testids` 的中位 845ms 到其他项目（首轮 1060ms 为冷缓存）：它随前端源码与用例规模变化。
- 不能证明 `validate_e2e_index` 无用：它在本快照没有 FAIL，但 WARN 仍可能对应真实风险；需要更多快照，尤其是它 FAIL 的快照。

## 5. 下一批怎么采

同一项目，等下一个任务状态（最好包含一次真实 FAIL 或一次门禁 WARN 处置），重复：

```bash
# 正常门禁（事件行落在项目 .atlas/runs/check-events.jsonl；跑完记得把证据复制出来并还原运行态）
python3 <atlas源包>/scripts/atlas_check.py --root <项目根> --fast --json

# 影子（账本默认写 ~/.atlas-shadow/validate_e2e_index.jsonl，不写项目）
python3 <atlas源包>/research/shadow_pilot.py \
  --root <项目根> --gate validate_e2e_index --label <批次ID>
```

**每批看三件事：**

1. `validate_testids` 耗时是否仍占大头；若是，下一轮做**只读副本**上的判据级消融（不是影子）。
2. 影子门是否出现 `FAIL` 而正式门禁 `PASS` / 未跑——那才是它的独立价值信号。
3. 正式门禁的 WARN 有几条被人实际处置（改代码 / 改资产 / 明确接受），这是 C5 误拦/噪声的真实分母。

## 6. 限制

- 单一快照；不是 2–3 个独立批次。3 连跑只证明稳定性，不证明跨任务分布。
- 项目父仓有在途改动（`git_dirty=true`）；本轮没有把父仓改动混入 Atlas 仓，也没有把项目路径 / 业务 case ID 写入本文。
- 运行态还原是「运行目录快照 + 定向删除新增事件行 + 还原基线文件」；不是完整的消融事务工具，未覆盖冲突拒绝（本轮没有冲突）。
- 事件行证据（含项目绝对路径）只留在会话临时目录，未入库；本文只保留抽象后的数值。
