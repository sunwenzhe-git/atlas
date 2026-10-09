# atlas 共享契约 — 收口清单

> **为什么有这份文件**：多轮定形都写过「收口清单加一步」（验证预算的触发物、门自检、台账对账、vault 同步…），但**这份清单本身长期不存在**（canonical 全仓 grep = 0 命中，`3509 §B112`）⇒ 那些「人防」全部悬空。
>
> 本文件 = 人侧的**唯一收口步骤表**；机器侧的**唯一总账** = `shared/gates.md`。两步都要在**同一轮内**做完，不得留到「下次顺手」。

## 1. 触发表（哪些事件要跑哪几步）

| 事件 | 必跑步骤 |
|---|---|
| 改契约 / 模板 / 校验器 / 脚本 / skill 瘦桩 | 1 → 2 → 5 → 6 → 7 |
| 落一条定形（设计结论） | 4 → 1 |
| 解决一条台账条目 | 3 → 4 |
| 环退役 / 真相源迁移 / 产物改名 | 8（生命周期三件套） |
| 域实现完成 + 该域 E2E 全 green | **9**（域收口验收走查） |
| 域实现完成（E2E 真跑前即可） | **10**（实例 ⑤ 实现代码独立审查） |
| 独立审查报告落盘（①②④⑤ 任一实例） | 1（含 `validate_review_report --dir <报告目录>`，2026-10-06 起） |
| 影响面报告已产出（`.trellis/tasks/<ID>/impact.json` 存在）的收口 | 1（含 `impact_reconcile --task <ID> --diff-base <ref>` 对账门：predicted vs 实际 diff 双向差集 ⇒ WARN，B191-1，2026-10-07 起） |
| 任一工作单元收尾 | 1（至少） |

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

### 步骤 3 — 台账对账

- 对**每条 open 条目**：拿它的关键词在 canonical 里 grep ⇒ 命中即逐条判「契约是否已写死」⇒ 是则**当场挪卷**（未决卷 → 归档卷，附解决方式一行 + 取证）。
- **机器缩围**：`python3 .atlas/validators/validate_ledger.py --root .` —— 「疑似已落地」名单（条目引用的**包内路径**已存在，**全卷两种条目形态**同扫）+ 撞号检测 + 条目 schema（类型/优先级）判缺 + 按优先级计数的待裁决汇总；**缩围不等于结论**，逐条回读后再挪卷。
- **取证不到的不得移走**（「计划」「转记」不算落地）。
- 范围 = **全卷**（A / B / C / D 节），不只 B 组（`3509 §B102` 的教训）。
- **新条目落卷前**：取号跑 `python3 .atlas/scripts/issue_ledger_ids.py --root .`（`--check <候选>` 直查占用；轮次前缀形态 `B<纪要轮次>-<序号>`），条目行内带全 `类型：`（四闭集）与 `优先级：P0|P1|P2` 标签（`shared/knowledge.md` §9 八字段 schema；缺 ⇒ `validate_ledger` WARN）。
- **每批 ≤ 10 条**（人工预算上限，`3509 §100`）：分组后超出顺延下批；一次确认门过一组（不逐条问）。
- 新增台账卷必须声明卷角色（`> 卷角色：未决` / `> 卷角色：已决归档`），否则它不进台账统计（`shared/knowledge.md` §9）。

### 步骤 4 — vault 同步（Obsidian）

改契约或落定形后，**当轮**检查这五处（缺一处就是 `3509 §B103` 的新实例）：

1. **对应环的设计 note**（`3502` 结构 / `3503` PRD / `3505` E2E / `3506` 分发）；
2. **`3507` 决策记录**（定形/拍板要有一节，含背景 / 被否 / 连带）；
3. **`3508` 顶部的「当前进度 / 待办」节**（进度的**唯一落点**）；
4. **工作区 `AGENTS.md` 的映射行**（若涉及）；
5. **`3501` 总览 note 的流程节与门表**（§3 流程 / §2.1 循环图 / §6 生命周期 / §7 门表 ⇔ canonical `closeout.md` / `apply` / 环契约口径一致）。**实测漏更实例**：B124 拍板批更新了环 note 与台账卷，唯漏总览（2026-09-29 用户在 Obsidian 发现旧文 ⇒ 本条入清单）。

- 手工补同步**连败过三轮**（`3509 §101`/`§104`）。机器对账已覆盖 **vault 本体 ⇔ 投影索引**（`gates.md` 2.1，步骤 6 必跑）；本步守的 **canonical ⇔ vault 语义时效**仍无机器判据（`§B103` 残余）⇒ 五处当轮必查。
- 未决变化另写 `3509`（未决卷）/ 归档卷。
- **轮次卷滚动（2026-09-29，`§B122` 定）**：`3508` 的全文轮次 **≥ 30 轮或 ≥ 60k 字符**（任一命中）⇒ 当轮拆卷：最旧轮次全文逐字 append 新「历史卷 N」、当前卷为挪走轮次各补一行 gist、只留最近 5 轮全文；并同步工作区 `AGENTS.md §2.1` 映射行与 `3508` 卷首自述（**两处必须同口径**）。拆完跑步骤 6（刷新 + 对账）。**机器判据**（2026-10-04 补，`3509 §B188-1`）：`validators/validate_ledger.py` 的「纪要卷滚动阈值」——当前卷全文轮次 ≥ 30 轮或全文轮次区 ≥ 60k 字符 ⇒ **WARN** 指名（历史卷不计）；此前本条零判据，实测已超阈（58 轮 / 70.1k）而未触发拆卷。

### 步骤 5 — 回灌登记

- **源包不是 git 仓库** ⇒ 改源包前先备份；副本 → 源包方向按 `ATLAS-UPSTREAM.md` 登记一行（变更 / 原因取证 / 落地物 / 状态），**回灌完成前不算结束**（`3509 §95` 的传播义务）。
- 源包 → 副本方向（本轮批 5 即此向）同样登记，并跑步骤 2 的一致性核对。

### 步骤 6 — 知识库刷新与投影对账

- 改完 vault **必须**刷索引并对账（否则自己就是 `3509 §B81` 的实例）：

  ```
  bun atlas/scripts/kb_index_refresh.mjs      # 独立进程离线重建（秒级）
  bun atlas/scripts/kb_projection_check.mjs   # 投影 ⇔ 本体逐篇对账,必须 0 issues(退出码 0)
  ```

- **不要**经 MCP 跑 `knowledge-maintain` 的 `rebuild` / `embed` / `full`：它们在同一同步请求里跟一次 embedding 补嵌，本机 embedding 走默认本地模型且模型缓存为空 ⇒ 每次尝试从 HuggingFace CDN 下载，网络不可达时长挂 ⇒ MCP 客户端先超时（`3508 §135`）。`embeddings:{enabled:false}` 已于 2026-09-29 落 `~/.config/open-zk-kb/config.yaml`；**运行中的旧 MCP 进程不重读配置**（进程级缓存），重启 MCP 服务后才生效。
- bun / open-zk-kb 包 / 索引缺失 ⇒ 两脚本退 `SKIP`（退出码 3，**不是通过**）——此时降级为人工核对（`knowledge-search(tags:["atlas"])` 份数 vs `ls <vault>/atlas/*.md`）。

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

## Guidance

**收口时按触发表逐步跑，不得跳步**：机器面（`gates.md`）回答「门还在不在、咬不咬」，人面（本文件）回答「还有哪些事没人做」。**任何一步的结论都要落进台账或 vault** —— 只在对话里说过的结论，下一个会话看不到。
