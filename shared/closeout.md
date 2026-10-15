# atlas 共享契约 — 收口清单

> **为什么有这份文件**：多轮定形都写过「收口清单加一步」（验证预算的触发物、门自检、独立审查…），但**这份清单本身长期不存在**（canonical 全仓 grep = 0 命中，`3509 §B112`）⇒ 那些「人防」全部悬空。
>
> 本文件 = 人侧的**唯一收口步骤表**；机器侧的**唯一总账** = `shared/gates.md`。两步都要在**同一轮内**做完，不得留到「下次顺手」。

## 1. 触发表（哪些事件要跑哪几步）

| 事件 | 必跑步骤 |
|---|---|
| 改契约 / 模板 / 校验器 / 脚本 / skill 瘦桩 | 1 → 2 → 5 → 7 |
| 环退役 / 真相源迁移 / 产物改名 | 8（生命周期三件套） |
| 改 `DESIGN.md` §12 决策（尤其含「被否：」的行）/ 撤回或收窄某项能力宣称 | **1（含宣称 sweep）**：以该裁决的否决词**全仓 grep** 逐命中判「宣称 or 历史锚」，否决词同批登记进 `tests/test_canonical_consistency.py` 判据⑦黑名单（词表=治标面，随裁决生长；语义自洽终归人——首跑咬合 2026-10-15 四处，`DESIGN.md` D79 ③） |
| 域实现完成 + 该域 E2E 全 green | **9**（域收口验收走查） |
| 域实现完成（E2E 真跑前即可） | **10**（实例 ⑤ 实现代码独立审查） |
| 独立审查报告落盘（①②④⑤ 任一实例） | 1（含 `validate_review_report --dir <报告目录>`，2026-10-06 起） |
| 影响面报告已产出（`.trellis/tasks/<ID>/impact.json` 存在）的收口 | 1（含 `impact_reconcile --task <ID> --diff-base <ref>` 对账门：predicted vs 实际 diff 双向差集 ⇒ WARN，B191-1，2026-10-07 起） |
| 域 / 里程碑收口且出现 ≥2 次同类纠偏（或用户点名复盘） | **11**（harness 复盘，按需） |
| ADR 演进链出现 `adr_cycle_detected` WARN（validate_adr stdout 自带 F36 修复指令） | 1（含 ADR 终审：`superseded_by` 指向**移出环外**的有效编号或撤销现行非终态取代行；validate_adr 复跑复绿——WARN 是终审信号不是失败，`shared/gates.md` §2.1） |

| 任一工作单元收尾 | 1（至少） |
| 结构环产出 / 刷新**域级文件** | 1（含**域清单确认门对账**：`rings/structure/reference.md` §6 步 4——报告里点名的「未确认」候选域，要么已过用户过目，要么显式登记待确认；域 id 是全链路键，未过目的粒度在 PRD 定稿时会整批重排） |

## 2. 步骤

### 步骤 1 — 门自检

```bash
python3 .atlas/scripts/atlas_check.py            # 一门一行；--fast 只跑校验器 + 生成物
```

- **逐行读**，不只看退出码。
- `SKIP` 是**一等结论**（未走到这一步 / 前置未声明），**不是通过**，必须带原因；`FAIL` 必须当场查因或登记台账。
- 判据来源：`shared/gates.md` §2 —— 一行一门，查什么 / **不查什么**都在表里。

### 步骤 2 — 装配面核对（改了包内件时）

```bash
python3 atlas/tests/test_install_selfcheck.py          # 装配面 ⇔ 包面 ⇔ 契约面（源包态）
rm -rf /tmp/probe && mkdir -p /tmp/probe && bash atlas/install.sh --target /tmp/probe --force   # 空目录探针：期望 exit 0
```

- 副本侧：`ATLAS_ALLOW_OVERWRITE=1 bash atlas/install.sh --target <项目根>` ⇒ 再逐目录 `diff -rq`，**期望逐字一致**。
- **为什么必须跑空目录探针**：`install.sh` 有些分支只在「目标已有旧桩」时才走到（实例：退役 skill 清理分支，`3509 §112` 的 `set -u` 事故只在副本重装时暴露）。

### 步骤 5 — 回灌登记

- **源包不是 git 仓库** ⇒ 改源包前先备份；副本 → 源包方向按 `ATLAS-UPSTREAM.md` 登记一行（变更 / 原因取证 / 落地物 / 状态），**回灌完成前不算结束**（`3509 §95` 的传播义务）。
- 源包 → 副本方向（本轮批 5 即此向）同样登记，并跑步骤 2 的一致性核对。

### 步骤 7 — 提交

- 提交前跑收尾检查（本工作区 = `bash .no-negative-echo/check.sh`，期望 `PASS`）。
- **派生件归位**：生成物（`product/e2e/scripts/`、`testid.md` 薄桩）与它的源（用例分片）在各自收口时一起归位；生成器幂等重跑兜底。
- 提交信息写**交付面**（做了什么、判据、取证），不写会话里的被否方案。

### 步骤 8 — 生命周期三件套（环退役 / 迁移 / 改名时）

**已落地为契约**（`shared/global-rules.md` §11 生命周期四态 + 退役三件套；`shared/single-source.md` §3 迁移史）⇒ 按契约执行（`§B115` 已闭环，2026-09-28）：

1. **声明**：删除 / 失义 两档，逐项写明（无冻结档——退役即删，历史归 git）；
2. **迁移与失义清单**：状态标签、输入链、门、校验器、模板、装配项、**以及该环承载的规则**（实例：`data-atlas-panel` 的宿主环消失后要求仍在 ⇒ 已归位到 E2E 环 §4.1；UI 文案纪律 ⇒ 归位到 PRD 环 §6）；
3. **传播义务**：回灌 + 副本重装 + vault 同步完成前，退役不算结束（防复活属退役本体）。

### 步骤 9 — 域收口验收走查（2026-09-29 补，`3507 AQ` = B124 结论）

- **何时**：该域 E2E 在真实应用全 green 之后、宣布域收口之前（触发表「域实现完成 + 该域 E2E 全 green」行）。
- **动作**：用户按域级 PRD 功能清单逐条在真实应用上过一遍；符合性对照物与逐项三值判定、blocked（待验收）语义见 `rings/e2e/reference.md` §5.4 末。
- **留痕（硬）**：结论落 `product/e2e/reviews/<日期>-acceptance-<域>/README.md`；②③ 未清零 ⇒ 域不收口。

### 步骤 10 — 实现代码独立审查（实例 ⑤，2026-09-29 接入）

- **何时**：域实现落码后、域收口前（不依赖真栈，E2E 真跑前即可跑）。
- **前置**：`product/stack-profile.yaml` 的 `impl_review.llm` 非空（未配 ⇒ 本步 `SKIP` + 原因，**不是通过**；契约依据 `shared/independent-review.md` §10）。
- **动作四步**：
  1. 组 background（Markdown 文件：需求卡摘要 + 受影响域 AC + 相关用例断言 + 审查焦点三问（`shared/independent-review.md` §10.4，只引路径不复制正文）；**不喂整仓**）；
  2. `<cli> review --preview --from main --to <分支>`，记下 **Will review N**（`.md` 等不支持扩展名会被 CLI 排除 ⇒ N 用 preview 数，**不得**用 git diff 全量计数）；
  3. `<cli> review --audience agent --format json --output <报告目录>/cli.json --background-file <bg> --from main --to <分支>`（CLI 名取 `impl_review.cli`）；
  4. `python3 .atlas/scripts/cli_review_convert.py --input <报告目录>/cli.json --out <报告目录> --unit <需求ID> --round <N> --expected-files <preview 的 Will review 数>`；
  5. `python3 .atlas/scripts/validate_review_report.py --dir <报告目录>`（报告形态 + 应审/实审对账门，2026-10-06 起；FAIL ⇒ 修复产出侧后重出，不得带病收口）。
- **报告落点**：`product/reviews/<日期>-impl-review-<范围>/`（`cli.json` 留档为输入侧证据）。
- **门禁**：有 `Critical` ⇒ 域不收口，修复回流 Trellis Execute、改完重跑（round +1）；`M < N` ⇒ 查静默跳过；finding 判明「AC / 断言本身错」⇒ 回退环改判 `prd` / `e2e` 入 backfill 队列。

### 步骤 11 — harness 复盘（按需，2026-10-12 补，`3507 BT`，ATLAS-UPSTREAM #201）

- **何时（任一）**：
  1. 域开发中出现 ≥2 次同类人类纠偏（如反复提醒某种代码习惯、工作流边界）；
  2. 用户显式点名复盘（如「复盘一下刚才这轮为什么别扭」）；
  3. 大版本或里程碑集中收口。
  - **反向约束**：日常顺利收口**不得盲目触发**（`global-rules.md §12` 成本预算纪律，无信号不空跑）。
- **输入物（就地取材）**：
  - 会话原文或近几轮讨论纪要（`3508` 最新轮次，跨会话可调 `trellis mem`）；
  - 本批变更清单（`ATLAS-UPSTREAM.md`）与待决议题（`3509` 未决卷）；
  - 本地环境若已装配通用 `retro` skill，可直接复用其分析类目。
- **三视角审视**：
  1. **人侧纠偏聚类**：同一类纠偏出现 ≥2 次 ⇒ 指令/提示词存在结构性表达缺口，评估补入契约或规范；
  2. **机器门盲区**：出错若本可通过静态检查/测试拦截 ⇒ 优先建机器门，次选写口头规则（契约 `gates.md`）；
  3. **冗余与摩擦**：排查是否存在白烧 token、无产出价值的 no-op 步骤或过度复杂的汇报仪式。
- **结论三通道分流（严禁凭空造新文件）**：
  - **契约 / 门 / 补丁缺陷** ⇒ 登记 `ATLAS-UPSTREAM.md`，走用户确认门（`global-rules.md §7`）；
  - **未决待观察事项** ⇒ 写入 `3509` 未决卷标准条目（带背景与验证判据）；
  - **开发流程/宿主适配摩擦** ⇒ 沉淀为 `.trellis/workflow.md` 补丁（`patches/`）或通过 `atlas report`（`§15`）上报开源池。
- **硬边界**：
  - 不做业务代码实现期规范复盘（`BP` 边界，业务代码规范归项目自身 linter/typecheck 机器门）；
  - 所有结论必须附带具体文件、会话或提交的**证据链**（`BQ` 同源）。

## Guidance

**收口时按触发表逐步跑，不得跳步**：机器面（`gates.md`）回答「门还在不在、咬不咬」，人面（本文件）回答「还有哪些事没人做」。**任何一步的结论都要落进台账或 vault** —— 只在对话里说过的结论，下一个会话看不到。
