# 证据生命周期与评审收敛：EL-15 硬判据、前提复核、Major 可达性

> 提案编号：RFC-20261104-01
> 提案作者：Atlas 方案会话（待维护者指派独立评审）
> 关联状态：草案（Draft；第七轮，已按终校 B3 + 2 条应修修订，待复核；本轮只写方案，不改实现）
> 影响范围：执行契约（`rings/e2e/reference.md`）· 布局契约（`shared/layout.md`）· 审查契约（`shared/independent-review.md`）· 脚本（`scripts/gen_e2e_scripts.py`、`scripts/atlas_verify.py`、`scripts/e2e_console.py`、`scripts/review_closure.py`、`_support/layout.py`、新增 `_support/evidence_archive.py`）· 校验器内核（`_support/review_policy.py`）· 模板（`templates/reviews/README.md`）
> 关联：承接 `RFC-20261018-01`（失败留证）与 `RFC-20261103-02`（证据面 ⇄ 判分面）；S3 仅登记，不设计实现
> 修订依据：维护者拍板 P1–P13；独立评审阻断与应修 14 条（回执见 §10）；复核 B1–B4 + 8 条应修；终校 B3 + 2 条应修；P11/P12/P13 定案见 §9

---

## 0. 结论

本方案分三条落地：S1 证据生命周期、S2 前提复核、S4 Major 可达性；S3 只登记不采纳。

**S1 的目的不是审计留档，而是把运行观测回灌到项目的应然资产（spec / 判据 / PRD 期望）**：失败批的 trace/截图只有跨过下一次起跑仍然可读，改进与诊断消费者才能据此收紧契约、补判据、改 PRD 期望。归档只是这条回灌链的输入；缺陷调查材料是附带用途，不是主目的。因此 manifest 只记「有哪些证据、校验和、批次与阶段」。

最关键的取舍：**S1 的归档动作归 Atlas 的执行脚本，证据目录落根级 `.atlas-evidence/`，但归档永不参与判分——不新增 `atlas_check` 门，归档失败只 WARN**。理由：`shared/global-rules.md:142-146` §17 已把证据面 ⇄ 判分面定为纪律面并明确「无机器门」；把「上一批证据是否存在」升成门会让门依赖历史运行状态，并把「用户移动/删除证据」误判成代码缺陷。S2 同理只 WARN、永不阻断；S4 只改模板与 §10.4/§10.5，零代码。

**S1 的口径是「按纪律先行、门槛未触发」，不是推翻 `duty-review/bugs.md:41` 的裁决**：该行升格条件（「首个有缺陷指控价值的构件在复跑起跑后被清空」）至今未触发，`rings/e2e/reference.md:519` / `scripts/atlas_verify.py:31-32` 只是既有契约与已知观察，不作为升格新证据。

**P11/P12/P13 三条定案（§9）**：① 根 `.gitignore` 缺失时由生成器创建并只追加 `.atlas-evidence/` 等运行产物忽略行——这是对 `patches/project-wiring/apply-wiring.py:342` 已落地裁决的**显式放开**，必须在 `DESIGN.md` 记 D183，且不代写用户其他规则；② `globalTeardown` 作为**补充**落进生成器发射的 config（只 copy + 写 manifest，不判定、不改 verdict），机制本体仍是 `atlas_verify` / `e2e_console`；③ `_kill` 改软杀（SIGTERM → 默认 5s grace → SIGKILL），不改超时判定结果，只让 Playwright 有机会 flush trace。

---

## 1. 现象与取证

### 1.1 S1：EL-15 的「留证」已有契约，但跨轮归档没有实现

**契约现状：**

- `rings/e2e/reference.md:519` 已写「留存窗口 = 到下一次 `playwright test` 起跑；跨轮取证须在起跑前归档」。
- `rings/e2e/reference.md:520-527` 已把 `.atlas-run/` 分为证据面（`trace.zip`、`test-failed-*.png`、可选 `*.webm`）与判分面（`results.json`、`.last-run.json`）。
- `shared/global-rules.md:142-146` 已定：证据面/判分面必须可区分且有清单；改进/诊断/执行消费者只读证据面；本条是纪律面，无机器门。

**实现现状：**

- 生成器把 `outputDir` 固定为 `.atlas-run`（`scripts/gen_e2e_scripts.py:2338`、`:2374`），注释直写「留存窗口 = 到下一次起跑（Playwright 启动清空 outputDir）」（`:2349-2350`、`:2385-2386`）。
- `scripts/atlas_verify.py:31-32` 把这条观察写成已知边界（重跑清空上一失败批留证，跨轮取证先手动归档）。
- `scripts/atlas_verify.py:419-423` 的 `_fail` 只把 `_evidence_paths()` 列进报告，没有复制/归档；`:124` 的 `_evidence_paths()` 只枚举 `trace.zip` 与 `test-failed-*`。
- `scripts/e2e_console.py` 只运行 Playwright，不在用例结束后归档；`.atlas-run` 的清空来自 Playwright 自身，不是 Atlas 的清理函数。
- #31 修复后，`scripts/e2e_console.py:132-133` 只排除 `.atlas-run/` 整棵树；`:157` 的 `scripts_hash` 仍按脚本目录白名单扩展名收集。**证据 manifest（`.json`）若落在 `product/e2e/scripts/` 下会进入 `scripts_hash`**，因此证据目录必须在 scripts 根之外。

**门槛与「不做的具体后果」：**

- `duty-review/bugs.md:41` 的升格条件至今未触发（原文：首个**有缺陷指控价值**的构件在复跑起跑后被清空 ⇒ 立跨轮归档案；2026-10-25 的 28 构件为环境红、无缺陷指控价值，不触发）。
- 因此本项**按纪律先行**（§17 + EL-15 契约已声明），门槛维持「未触发」，**不得声称已推翻该裁决**。若将来触发，取证要求：① 留下首个有指控价值的构件身份（用例名 + 文件名 + 归属缺陷案）；② 复现 ≥2 次且给出固定节拍；③ 复跑起跑前后各留一次 `ls -l .atlas-run` 原始输出；④ 按 DR1 带 D108 勘误节归档。
- 不做的后果（主）：失败观测无法回灌——trace/截图在下一次起跑瞬间消失，`atlas_verify` 报告里的 `evidence_paths` 只剩失效路径，改进/诊断消费者失去可复算输入，spec / 判据 / PRD 期望的收紧只能靠记忆或重跑。**附带后果**：缺陷调查只能临时落 `/tmp`（不可复算，`rings/e2e/reference.md:519` 想避免的正是这个）。

### 1.2 S2：跨轮 carried 没有「前提复核」，循环在第 2–3 轮才被看见

- `scripts/review_closure.py:278` 已建 `events: fp → [(轮次, 证据类型, 原条目)]`，`:289` 对每一轮的每个 check 追加事件；但 `:292-297` 的 `prior_fps` 去重**只保留首次出现**，`prior` 的 `prior_round` 是最早轮次，不是「连续了几轮」。
- 现行 `carried`（`:378-397`）只回答「上一轮 open、本轮还在」，没有连续轮数；`shared/independent-review.md:80` 只在 `round >= 4` 升级；`duty-review/README.md:5` 把「同阶段问题反复出现」列为第一类病；`:28` 的 DR4 按源文件聚合，不按 finding 指纹。
- 后果：同一指纹第 2 轮仍 open 时，没有任何义务要求作者写下「这条修复共同假设了什么」；第 3 轮按同一前提再修，直到第 4 轮才升级。空窗恰好是第 2–3 轮。

### 1.3 S4：Major 只有 `file:line` 证据，没有「可触发路径」义务

- `shared/independent-review.md:223` 只硬性要求 `Critical` 附证据链；给不出证据链的至多判 `Major`，即 `Major` 可以只有位置与推理。
- `shared/independent-review.md:219-221` 的三问是架构判断，不含「哪个输入/状态/调用路径能让它真的发生」。
- `templates/reviews/README.md:8` 只要求 `file:line` 与可操作建议。
- 后果：审查者可以写「理论上可能」的 Major，作者无法复现，只能辩论或降级；`duty-review/README.md:28` 的「把红灯训练成噪声」正是此形态。

### 1.4 S3：Launch / Doctor / Cleanup 只登记，不采纳

- 当前只有 `baseURL` 单源（`rings/e2e/reference.md:508`），环境不就绪只归 `env_not_ready`（`rings/e2e/reference.md:713`），浏览器就绪由 D124（`DESIGN.md:593`）覆盖；没有进程、端口、登录态的结构化诊断。
- 不采纳理由：Atlas 假设靶场已在外部运行，起停动作归执行层（`RFC-20261103-10` 的边界）；当前没有真实项目反复卡在启动的取证。
- 登记触发条件（满足任一才另开 RFC）：
  1. 30 天内同一仓 ≥2 次 `env_not_ready`，且根因不是浏览器（D124 覆盖面），而是进程/端口/登录态；
  2. 同一仓 ≥3 个批次需要人工先起服务才能跑 `atlas_verify`；
  3. 执行层已能提供跨平台稳定的 `launch / doctor / cleanup` 命令并愿意承担动作。
- 触发后只讨论「Atlas 出字段/判据、执行层出动作」，不在本 RFC 预设计实现。

---

## 2. 决策与取舍

### 2.1 S1 决策

- **证据根 = 根级 `.atlas-evidence/`**，与 `.atlas-run/`（`product/e2e/scripts/` 内）物理分离，且不进入 `scripts_hash`。
- **登记为 `shared/layout.md` §1 第五落点**：现表头是「四个落点」（`shared/layout.md:10`），表体四行（`:14-17`）⇒ 改为「五个落点」并加一行 `.atlas-evidence/`（归属 = 运行证据，`install.sh` 不覆盖、不清空）。
- **忽略行写入者（P11 = A，已定）**：写者 = `scripts/gen_e2e_scripts.py:2575-2577` 的现有 `.gitignore` 写盘函数（`:2573-2574` 是 auth setup，不是写盘），扩展为「根 `.gitignore` 缺失则创建；存在则只追加缺失的 `.atlas-evidence/` 一行」。**这是对已落地裁决的放开**（`patches/project-wiring/apply-wiring.py:342` 现定「根 `.gitignore` 不存在 ⇒ 不替用户从零创建」）；安全理由：缺失时创建是「幂等追加」的特例，**已有内容一字不改、只追加缺失行**，且范围只限 `.atlas-evidence/` 这类运行产物忽略行，不代写用户其他规则。放开须在 `DESIGN.md` 记 D183（见 §7.2）。
- **冲突路径与输出**（逐条写死，全部只作用于 `.atlas-evidence/` 行，绝不改其他内容）。**先定可判定闭集**：去掉注释与首尾空白后，整行 ∈ {`.atlas-evidence`, `.atlas-evidence/`, `/.atlas-evidence`, `/.atlas-evidence/`} 才算「已含」；以 `!` 开头且去掉 `!` 后 ∈ 同一集合才算「冲突」。**不做 glob 推理**——`*`、更宽通配、反选通配一律不推断，闭集之外的行视为与本行无关：
  1. 文件缺失 ⇒ 创建并写一行，输出 `gitignore_created`（PASS，不 WARN）；
  2. 闭集内已含 ⇒ 跳过，输出 `N/A`，不改文件；
  3. 存在但缺该行 ⇒ 追加一行，输出 `gitignore_appended`；若文件末尾无换行，先补一个换行再追加，**原有字节与行序一字不改**；
  4. 文件只读/无权限 ⇒ 不写，输出 **WARN** `gitignore_readonly`（归档照常，见 §4.6 的持续 dirty 量化）；
  5. 文件存在但**已被 git 跟踪** ⇒ 正常追加（该文件本就该被跟踪），输出 `gitignore_tracked_appended`（**不 WARN**），并提示该修改随 S1 同提交；
  6. 闭集内冲突（显式反选该目录） ⇒ 不与用户意图对抗，跳过，输出 **WARN** `gitignore_rule_conflict`；不改用户规则、不改用其他路径绕过。
- **为什么必须写忽略**：根级目录无忽略 ⇒ 未跟踪 ⇒ `repo_git_dirty()` 为 True（`scripts/e2e_console.py:124-126`）⇒ `repo_provenance` 的 `git_dirty` 为 True（`:397-405`）⇒ 提交时挂 dirty 警告（`:473`）。这条链是根级落点的必付成本，忽略行是唯一解。
- **防御性登记**：`.atlas-evidence` 加入 `_RUNTIME_PATH_PARTS`（`scripts/e2e_console.py:132`），使它在任何被扫目录里都不进指纹（即使未来有人把它挪进 scripts 根）。
- **三个归档点**：① 起跑前归档（`rings/e2e/reference.md:519` 的契约动作，**只由包装器做**）——把现有 `.atlas-run/` 证据面复制到 `.atlas-evidence/<run-id>-pre/`，再让 Playwright 清空；② 失败后归档——`atlas_verify._fail`（`:419-423`）与控制台用例失败/超时后复制到 `<run-id>-fail/`；③ **P12 补充**：生成器发射的 `globalTeardown` 在跑后 copy + 写 manifest（`phase="post-run"`），只覆盖「直跑 `atlas_check` / 直跑 playwright」这条没有包装器的入口；它不判定、不改 verdict，也不替代 ①。
- **去重规则（批内）**：控制台**每批只做一次 pre-run 归档**（批首、第一个用例起跑前），**fail 归档只在失败用例后各做一次**；同一归档根内相同 `sha256` 的文件不重复复制，manifest 复用已有条目。不允许「逐用例 pre-run + fail」双写。
- **去重规则（跨批，回应评审 8）**：`<id>-pre/` 与 `<id+1>-pre/` 是不同的根，上一轮失败 trace 会被再归档一次。解法：`.atlas-evidence/index.json` 记 `sha256 → 首个归档相对路径`；归档前先查索引，命中即跳过复制、只在 manifest 记 `deduped_from`；索引与 manifest 同事务（tmp+replace）更新；索引损坏时按各 `manifest.json` 重建。**实现代价**：+1 索引文件、并发写需文件锁（`fcntl`）或失败即重建、+2 条测试（跨批不重复 / 索引损坏可重建）。不选「按 mtime 过滤」，因为 mtime 不可靠（复制/检出都会改）。
- **只归档证据面**：`trace.zip`、`test-failed-*.png`、可选 `*.webm`；`results.json` / `.last-run.json` 永不复制。
- **归档失败 = WARN，不改判**：归档是观测回灌的输入动作，不是门；磁盘/权限失败不得把真实失败改写成 PASS，也不得把真实 PASS 改写成 FAIL。
- **不自动删证据**（P1a）：`.atlas-evidence/` 不参与任何清理；保留期与清理若需要，走独立显式操作（另开 RFC），不在本 RFC。
- **命名区分（防混淆）**：`atlas_verify` 已有 `archive_dir`（`:133`）、`write_archive`（`:340`）、报告键 `archive`（`:405`），语义是**批留档**（成功批快照，`:374-377` 已存在则拒跑）。本方案的「证据归档」一律写全称 `evidence archive` / `evidence_archive`，契约里明写「留档 ≠ 证据归档」。
- **已知边界（P2 + P6，按 B2 选 (i) 改写）**：直跑 `atlas_check`（`scripts/atlas_check.py:817` 直接 `pw_bin test -c playwright.config.ts`）**pre-run 不归档 ⇒ N/A**；但 config 里的 `globalTeardown` 使 **post-run 归档必然发生**。因此残余风险只剩「teardown 未执行」的情形（SIGKILL、进程未正常退出、或显式跳过），不再是「直跑全无归档」。不选专用跳过变量，也不并存两种写法；归档仍不挂进门。
- **不做事后对账（P10）**：不提供 `--verify-archive`。理由：写入侧在写 manifest 时已自校验（sha256 + 原子写）；事后对账的收益低于新增 CLI + 测试 + 文档 + 评审面的成本。记为「不做，只留钩子」，列入 §2.6 本轮范围外。

### 2.2 S2 决策

- **连续判定（B1 修正）**：`prev` = `events[fp]`（`scripts/review_closure.py:278`/`:289`）中**满足 `round < latest_round` 且 `kind == "check"` 的最大轮号**；判 `latest_round - prev == 1`。**不得引用 `prior` 的 `prior_round`**（`:292-297` 的 `prior_fps` 是跨轮单集合，r2 再命中即 `continue`、`prior_round` 停在 r1 ⇒ `{1,2,3}` 会被算成 `3-1=2` 而漏掉第 2–3 轮空窗）。`events` 直接持有每一轮的 `check` 事件，是唯一可用的轮号来源。
- **同轮重复只在本轮内去重**：同一轮同一指纹出现多次 ⇒ 该轮只算一次，不影响 `prev`；跨轮命中**不得**把 streak 归 N/A。
- 最新轮 `checks[]` 必须带：`premise`（一句话共同前提）、`discriminating_check`（`{command, expected_if_false, observation?}`，`command` 可重跑，`expected_if_false` 写「若前提为假应看到什么不同」）。
- 缺失/空值/形状错 ⇒ `premise_required[]` + `warnings`，`status` 升 WARN；**退出码仍为 0，不进 `atlas_check`，永不阻断**（P3）。
- 字段是 `checks[]` 可选字段，不新增 schema 版本；`_support/review_policy.py` 的 `validate_v2_finding`（`:279`）只校验「出现时的形状」，不要求所有 finding 都带。
- `premise` 放在 `resolves` 里不算数（carried 是仍未关闭项，`resolves` 只描述已关闭项）。
- **重复指纹只在本轮内去重**：同轮同指纹重复 ⇒ 本轮计一次，沿用既有重复 WARN；`prior_fps` 的跨轮命中不参与 streak 判定（删掉原「命中即 N/A」）。

### 2.3 S4 决策

- `Major` 必须有「可触发路径」：输入/状态/调用路径 + 已检查的上游守卫；给不出路径的候选**直接丢弃，不降级**。
- **probe/观察路径合法但必须可复跑**（P4）：允许设计/性能类 Major 用 probe，但必须写「命令 + 预期差异」（`command` + `expected_diff`），不是「观察一下」。
- **丢弃候选留痕**（P7）：报告末尾一行「候选 + 一句不可达原因」，不进分级、不阻断。
- `Critical` 证据链口径不变（`shared/independent-review.md:223`）；`Minor` 不受约束。
- 只改 `shared/independent-review.md:223`、`:231` 与 `templates/reviews/README.md:8`；**零代码、无新门**。

### 2.4 形状面统一立场（回应「S2 有形状机判、S4 拒绝形状面」）

归因修正：S4 本轮不入形状面，**不是**因为「语义不可机判」——S4 的 probe（`command + expected_diff`）与 S2 的 `discriminating_check` 同构，机器同样能判「有没有写、形状对不对」。真实原因是**本轮 S4 零代码、没有结构化字段载体**：产出只是报告末尾一行非结构化文字，没有可校验的对象。因此：

- S2 本轮新增了结构化载体（`checks[]` 可选字段，由 `validate_v2_finding` 校验形状），所以形状面存在。
- S4 本轮不新增载体，所以没有可锁对象；若未来 S4 引入 `probe` / `discarded[]` 结构化字段，应与 S2 一样做形状校验，而不是继续停留在纪律。
- 统一原则只保留一句：**机器只锁「该写的东西写了没」，不锁「写得对不对」**；它不能用来论证「S4 天生该零代码」。

### 2.5 被否决的备选实现

| 备选 | 否决理由 |
|---|---|
| 把 `outputDir` 改成永久 `.atlas-evidence` | Playwright 起跑仍会清空 `outputDir`，等于把证据目录交给清空逻辑；证据面/运行面不再分离 |
| **以 `globalTeardown` 为机制本体（唯一归档点）** | 已知事实更正：`playwright.config.ts` 的**唯一写者是生成器**（`scripts/gen_e2e_scripts.py:2405`），归属稳定，不存在「用户手改冲掉归档逻辑」的固有问题。仍不作本体：① 它只能做「跑后」，做不了 `rings/e2e/reference.md:519` 的**起跑前**归档；② 被 SIGKILL 时 teardown 不执行（P13 软杀失败后的兜底路径，`scripts/e2e_console.py:1028-1037`）；③ 它仍需同一套白名单/manifest 代码；④ 直跑归档没有 run-id/verdict 语义。**P12 已定：作为补充**，覆盖「直跑 `atlas_check` / 直跑 playwright」，本体仍是 `atlas_verify` / `e2e_console`。 |
| **`_kill` 保持硬杀、接受 partial** | **P13 已定 A：改软杀**。硬杀会让 Playwright 来不及 flush trace，最需要证据的超时形态反而最缺证；软杀（SIGTERM → grace → SIGKILL）成本是每次超时最多多 5s，收益是完整 trace。判定结果不受影响。 |
| 新建 `validators/validate_evidence_archive.py` 做成门 | 门会依赖历史运行状态；用户移动/删除证据会被判红；与 `shared/global-rules.md:146` 的「纪律面，无机器门」冲突 |
| 控制台逐用例 pre-run + fail 双写 | 同一批产出两份 trace、两张 manifest，评审已点名；改为批首一次 pre-run + 失败各一次 fail + sha256 去重 |
| 把 `premise` 放进 `resolves` | carried 项没有 resolves 条目，会静默漏检；且与「关闭证据」语义混淆 |
| 新建 `validators/validate_premise.py` 硬门 | 跨轮 carried 只有 `review_closure` 知道；单文件 validator 看不到历史，只能做文本形状门，属于假门 |
| 给 `review.json` 加**必填** `reachability` 字段 | 本轮 S4 无结构化载体（§2.4）；必填会奖励「写一句路径」的存在性假绿。若未来引入，应做成**可选字段 + 形状校验**，不做必填语义门 |
| 采纳 S3 的 `launch/doctor/cleanup` 字段 | 与 `baseURL` 单源和「执行层拥有动作」边界冲突；当前无真实触发取证 |

### 2.6 本轮范围外

- **`--verify-archive` 事后对账**：不做，只留钩子（理由见 §2.1 末条）。
- **证据保留期与自动清理**：不做（P1a）；`.atlas-evidence/` 只增不减，清理另开 RFC。
- **S3 的 Launch / Doctor / Cleanup**：只登记触发条件（§1.4），不设计、不接线。

---

## 3. 判据精确化

### 3.1 S1 真假条件表

输入 = 一次执行前/后的 `.atlas-run`、证据目录状态、归档调用结果。

| # | 输入 | 判定 | 输出 | 合法反例/边界 |
|---|---|---|---|---|
| S1-1 | 起跑前 `.atlas-run` 有证据面文件，归档成功 | 证据 + manifest 均落 `.atlas-evidence`，源文件未删 | PASS | 正常归档 |
| S1-2 | 起跑前 `.atlas-run` 不存在或为空 | 无证据可归档 | N/A | 首跑/全绿轮，不算违规 |
| S1-3 | 失败后 `.atlas-run` 有 PNG（`screenshot: only-on-failure`），归档成功 | **归档轴**：该批证据可跨批次访问 | PASS（归档） | 与 trace 有无解耦；控制台失败、超时同样适用 |
| S1-4 | 某用例 `trace_enabled=False`（逐用例策略，见下） | **trace 轴**：该案 trace 子项 N/A；**PNG 仍按 `screenshot: only-on-failure` 归档**，归档动作照常 | trace N/A + 归档 PASS | `trace: off` 不等于「无证据」；不得因此不建 manifest |
| S1-5 | 某用例 `trace_enabled` **未知**，且运行失败无 `trace.zip` | 批次策略未知 ⇒ **WARN**（附 `results.json` 失败用例数），**不得 N/A** | **WARN** | 与 S1-4 不同：这是「该有却没有/无法判断」，评审点名的假绿来源 |
| S1-6 | 证据目录不可写/磁盘满 | 归档失败，源文件保留 | WARN | 运行结论不变；不得改成 FAIL |
| S1-7 | 源文件读取失败/复制后 sha256 不一致 | 只保留校验成功的文件，manifest 列缺失项 | WARN | 不得静默算 PASS |
| S1-8 | `.atlas-evidence/<run-id>` 已存在 | 独占创建失败 ⇒ `-2` 后缀，绝不覆盖 | PASS | 同秒/同 source 碰撞 |
| S1-9 | 两次运行并发、同名同秒 | 一方成功，另一方 `-2`；两份 manifest 均完整 | PASS | 独占 mkdir 保证不写半份 |
| S1-10 | manifest 写到一半崩溃 | 采用 tmp + `os.replace` 原子写；读者只见完整 manifest，残留 `.tmp` 不计 | N/A | 半成品不可见 |
| S1-11 | 超大 trace（配额/IO 错） | 复制失败 ⇒ WARN，manifest 记 `partial` | WARN | 不因单文件失败丢整批 |
| S1-12 | 证据目录是符号链接且指向根外 | 解析后不在项目根内 ⇒ 拒绝写入 | WARN | 与 `shared/layout.md:31` 的「解析后仍须落在项目根内」同源 |
| S1-13 | 跨设备复制 | 用流式 `copyfile`，PASS | PASS | 不得用 `rename`/硬链 |
| S1-14 | 用户把证据移走/删掉 | 归档器无法恢复；下次归档 N/A | N/A | 不判红，不做自动恢复 |
| S1-15 | 直接 `atlas_check` 真跑（`scripts/atlas_check.py:817` 直接 `pw_bin test -c playwright.config.ts`） | **pre-run 轴**：无包装器 ⇒ 不归档（N/A）；**post-run 轴**：config 里的 `globalTeardown` 照常归档 | pre-run N/A / post-run PASS | 选 (i)：teardown 覆盖直跑；不再有「直跑全不归档」 |
| S1-16 | 证据面里混入 `results.json`/`.last-run.json` | 判分面文件不复制 | PASS（只复制白名单） | 不得把判分面当证据 |
| S1-17 | 有人伪造 manifest `verdict=pass` | 门/回填不读取归档 | 原 FAIL 保持 | 证据不得反向充当通过证据 |
| S1-18a | manifest 被篡改（改 sha256 / 删文件），未做显式复核 | 无消费者 ⇒ 判分不变 | N/A | 事后对账已明确不做（§2.6） |
| S1-18b | 显式复核（人工/一次性脚本，不在门内） | 重算 sha256 与 manifest 不符 ⇒ 报告差异 | WARN | 复核不是产品 CLI，也不是门 |
| S1-19 | 存量 `.atlas-run`（升级前遗留） | 起跑前先归档，再清空 | PASS | 兼容存量关键路径 |
| S1-20a | 运行超时，`_kill` 发 SIGTERM 后在 grace 窗口内退出（P13） | **trace 完整** ⇒ 走正常证据归档（`phase="fail"`），manifest 完整、无 `partial`；**trace 缺席** ⇒ 落 S1-20b 的 WARN | 归档 PASS（trace 在）/ WARN（trace 缺）；运行判定仍 FAIL | `_kill` 只对 node 进程发 SIGTERM（`scripts/e2e_console.py:1028-1036`），**未覆盖 worker/browser**；Playwright 在 SIGTERM 下是否 flush **未真跑验证**，钉用「收到 SIGTERM 先写 trace」的模拟进程，只证明归档链 |
| S1-20b | 运行超时，SIGTERM 后 grace 内仍未退出 ⇒ SIGKILL | 该次 trace 不完整，teardown 亦不执行 ⇒ 记 WARN 并标 `partial` | **WARN + partial** | 只有软杀也失败才落本行；这是 S1-20a 的兜底，不是常态 |

**两轴独立（B4）：** 「归档是否发生」与「trace 是否应存在」是两条轴，**不互相抹掉**：

- 归档轴只看白名单文件是否复制成功（PNG 在就 PASS），trace 缺失**不**把归档判成 WARN，也**不**把 PASS 抹掉。
- trace 轴只看该用例的 `trace_enabled`：已知 False ⇒ N/A；未知 ⇒ **WARN**（永不 N/A）；已知 True 且失败无 trace ⇒ WARN。
- **判别源是逐用例，不是批次 bool**：生成期产出逐用例 trace 策略清单（每案 `request_assertion: bool`），运行期再叠加 `ATLAS_REQUEST_TRACE`（request-only 用例才开 trace）得到每案 `trace_enabled`。一个批次 bool 表达不了「这批里只有某些是 request-only」。

**最容易假绿：** 只检查 `.atlas-evidence` 存在，不校验 manifest 与 sha256；只检查目录非空，不看是否混入 `results.json`；批次策略未知时静默算 N/A。
**最容易假红：** 归档权限失败判 FAIL；用户移动证据判代码缺陷；`trace: off` 的 N/A 判缺证；`globalTeardown` 缺席判实现失败。

### 3.2 S2 真假条件表

输入 = 逐轮 `events`（`scripts/review_closure.py:278`）、最新 `review.json`、finding 的 `premise` / `discriminating_check`。

| # | 输入 | 判定 | 输出 | 合法反例/边界 |
|---|---|---|---|---|
| S2-1 | 最新 open + 上一轮（轮差=1）同指纹 open，字段齐全 | 前提已写且有判别检查 | PASS | 正常 |
| S2-2 | 同上，缺 `premise` 或 `discriminating_check` | 触发前提复核 | WARN | 退出码 0，永不阻断（P3） |
| S2-3 | `premise` 空串/非字符串 | 视为缺失；形状错另由 report validator 红 | WARN / exit 2（形状） | 形状面与语义面分开 |
| S2-4 | 只有最新 1 轮 open | 不构成连续 | N/A | 首轮不要求 |
| S2-5 | r1 open、r3 open（缺 r2） | `prev` = r1（`events` 中 `<3` 的最大 check 轮）⇒ `3-1=2 ≠ 1` ⇒ 轮号不严格相邻 | N/A | 缺轮不算连续；沿用既有 round 告警 |
| S2-6 | 上一轮已 `resolves` 关闭，最新又 open | 不是连续 carried | N/A | 重新开启不是「同前提失败」 |
| S2-7 | 上一轮 `pre_existing` / `Minor` | 不参与 streak | N/A | 已存在项/低级别不算 |
| S2-8 | 同指纹级别从 Critical 降 Major，仍 open | 仍触发；级别不影响连续计数 | WARN（字段缺时） | 级别变化不是关闭 |
| S2-9 | `premise` 写在 `resolves` 而非 `checks` | 视为缺失 | WARN | 位置约束，防漏检 |
| S2-10 | 非 carried finding 带 `premise` | 忽略，不罚 | N/A | 允许提前写 |
| S2-11 | 同轮同指纹重复（`prior_fps` 命中，`:292-294`） | 只在**本轮内**去重：该轮计一次，沿用既有重复 WARN；同轮 Major+Critical 重复时**保留最严档（Critical）**，不让升降级语义被吞；**不把 streak 归 N/A** | 本轮一次 + 既有 WARN；等级取最严 | 跨轮命中不污染 streak（B1） |
| S2-12 | `{1,2,3}`：r2 写了 `premise`/`discriminating_check`，r3 没写 | `prev` 取 r2 ⇒ 轮差 1 ⇒ 触发；最新轮 r3 缺字段 | WARN | 旧公式用 `prior_round`(r1) 会得 `3-1=2` ⇒ N/A，必须在此红 |
| S2-13 | `{1,2,3,4}`：四轮同指纹均 open、每轮都不带字段 | `prev` 逐轮推进（4→3→2→1），最新轮 r4 仍触发 | WARN | 连续多轮不因跨轮 `prior_fps` 命中而中断 |

**最容易假绿：** 只看 `premise` 非空，不看 `discriminating_check.command`；作者写套话但从不重跑。
**最容易假红：** 把「未修但已 carried」当违规；把缺轮当连续；把 `resolves` 里的字段当已满足。

### 3.3 S4 判据（纪律，不是机器判据）

| # | 输入 | 判定 | 输出 | 合法反例/边界 |
|---|---|---|---|---|
| S4-1 | `Major` 有可触发路径 + 上游守卫核对 | 可保留 | PASS（纪律） | 路径可为输入/状态/调用路径 |
| S4-2 | `Major` 给不出可触发路径 | 丢弃，不降级；报告末尾一行记「候选 + 不可达原因」 | 不进分级、不阻断 | 不写「可能」「建议关注」 |
| S4-3 | `Critical` 有证据链 | 保留，口径不变 | PASS | S4 不削弱 |
| S4-4 | `Minor` 无路径 | 允许，不进阻断面 | N/A | 设计/性能类可留观察 |
| S4-5 | 设计/性能类 Major 用 probe | 必须写「命令 + 预期差异」且可复跑，否则丢弃 | PASS（纪律） | 观察不是命令（P4） |
| S4-6 | 审查者写「输入可触发」但无具体路径/命令 | 视为没有可触发路径 | 丢弃 | 抽样复放会抓 |

**假绿：** 只写「某输入可能触发」；probe 只写「观察一下」。
**假红：** 要求所有 Major 都有单测复现；设计类只能用 probe，不应被误杀。

---

## 4. 机制落点

### 4.1 S1

| 落点 | 改动 |
|---|---|
| `shared/layout.md:10-17` | §1 标题「四个落点」→「五个落点」，表体加 `<项目根>/.atlas-evidence/` 一行（归属 = 运行证据；`install.sh` 不覆盖、不清空） |
| `scripts/gen_e2e_scripts.py:2575-2577`（现有 `.gitignore` 写盘函数；2573-2574 是 auth setup） | **P11=A**：写者扩展为「根 `.gitignore` 缺失则创建、存在则只追加缺失行」；保留原内容与行序；`patches/project-wiring/apply-wiring.py:342` 的「不首创」在此**仅对 `.atlas-evidence/` 等运行产物忽略行放开**（D183 记录） |
| `scripts/gen_e2e_scripts.py:2405`（config 发射） | **P12**：发射两个东西——① config 里 `globalTeardown: './atlas-evidence-teardown.ts'`（**相对 config 目录解析**；config 位于 `<e2e>/scripts/`，见 `_support/layout.py:107-108`，故**不得写 `./scripts/…`**，否则会解析到 `<e2e>/scripts/scripts/` 而模块不存在、绿轮被 teardown 抛错翻红）；② **新文件 `<e2e>/scripts/atlas-evidence-teardown.ts`**，内部 `execFileSync(process.env.ATLAS_PYTHON ?? "python3", [<repo>/.atlas/_support/evidence_archive.py, "--phase", "post-run", ...])`，**吞掉所有异常**（不得让 teardown 抛错把 PASS 翻成 FAIL）。teardown **只 copy + 写 manifest，不判定、不改 verdict**。**受 P13 影响的部分**：被 SIGKILL（软杀失败后的兜底）时 teardown 不执行 ⇒ 该次无 post-run 归档，按 S1-20b 落 WARN + `partial`；起跑前归档仍只由包装器做，teardown 不替代它。**`scripts_hash` 影响**：`.ts` 与 `.atlas-trace-policy.json` 都在 `scripts/e2e_console.py:157` 白名单内 ⇒ **会进指纹，属一次性基线变化**，实现交付记录须附新 `scripts_hash`；两个文件同时列入 `docs/map` 文件清单。**共享内核仍是 11→12**（该文件不在 `_support/`，不构成第 13 件） |
| `scripts/gen_e2e_scripts.py`（策略清单） | **B4**：生成期按用例产出 **`<e2e>/scripts/.atlas-trace-policy.json`**（与 `playwright.config.ts` 同目录）：`{case_id: {"request_assertion": bool}}`；运行期再叠加 `ATLAS_REQUEST_TRACE` 得每案 `trace_enabled`。它是**生成物、进 `scripts_hash`**（一次性基线变化，交付记录附新值），并列入 `docs/map` 文件清单 |
| `_support/layout.py` | 新增 `e2e_evidence_dir` 属性（`root / ".atlas-evidence"`）；`path_for` 增键 |
| 新增 `_support/evidence_archive.py` | `archive_run_artifacts(root, *, source, phase, scripts_hash=None)`：白名单枚举、流式复制、sha256、tmp+replace 写 manifest、独占创建目录（`-2` 顺延）、符号链接越界拒绝、失败 WARN；**不删任何源文件/旧归档** |
| `scripts/atlas_verify.py` | 起跑前调用 `phase="pre-run"`；`_fail`（`:419-423`）调用 `phase="fail"`；**逐案 trace 判定读 `<e2e>/scripts/.atlas-trace-policy.json` + `ATLAS_REQUEST_TRACE`**（读不到 ⇒ 该案 WARN，不 N/A）；报告增 `evidence_archive` 字段（**不参与 ok 判定**，与既有 `archive`（`:405`）区分） |
| `scripts/e2e_console.py` | 批首一次 pre-run；失败/`_kill` 后 fail（正常退出时 post-run 由 teardown 补）；结果事件带 `evidence_archive`；归档 WARN 只显示；`:132` 的 `_RUNTIME_PATH_PARTS` 防御性加 `.atlas-evidence` |
| `scripts/e2e_console.py:1028-1037` | **P13=A**：`_kill` 改「SIGTERM → 等 `kill_grace_secs` → 仍不退才 SIGKILL」。配置：`kill_grace_secs` 默认 **5s**，允许 0–15s，超出即钳到边界（0 等于退回旧行为）。**不改超时判定结果**：超时判定在 `:985-988` 先发生（先 `_kill()` 再置 `timed_out=True`）；grace 只改变进程如何退出，**grace 后仍置 `timed_out`** ⇒ 该案照旧 FAIL。**对总时长的占用与上限**：每次超时最多 +`kill_grace_secs`（默认 +5s，最多 +15s）；单批最坏 = 超时用例数 × grace，不叠加到用例自身的 `timeout` 预算；grace 期间不重试、不二次判定。**覆盖边界**：SIGTERM 只发给 node 进程，worker/browser 不在控制内 |
| `rings/e2e/reference.md:519` | 把「跨轮取证须在起跑前归档」补成可执行条款：目录、白名单、manifest、去重、保留期（归 P1）；写明「留档（`atlas_verify.archive`）≠ 证据归档」 |
| `install.py` | 新 `_support/evidence_archive.py` 增一条自检（65→66） |
| `docs/map/*` | 与 S1 同提交同步（见 §6） |

**机器门 / 纪律切分：** 归档是执行动作 + 报告字段，**不新增 `atlas_check` 门**；运行时归档失败是 WARN，门不依赖历史证据（符合 `shared/global-rules.md:146`）。

### 4.2 S2

| 落点 | 改动 |
|---|---|
| `scripts/review_closure.py:274-297` | 由 `events[fp]` 取 `prev`（`< latest_round` 且 `kind=="check"` 的最大轮）判 `latest_round - prev == 1`；同轮内去重；**不再用 `prior` 的 `prior_round`**；`result` 增 `premise_required[]` 与 `warnings`；只改 WARN，不改退出码 |
| `_support/review_policy.py:279` | `validate_v2_finding` 增可选字段形状校验：`premise` 非空字符串；`discriminating_check` 为对象且 `command`/`expected_if_false` 非空；`observation` 可选非空 |
| `shared/independent-review.md` §11 | 增「连续 carried ≥2 轮 ⇒ 最新轮必须带 premise + discriminating_check；只 WARN，不阻断」 |
| `templates/reviews/README.md` | 不新增必填项；说明指向 `checks[]` 可选字段，避免模板变成第二真相源 |

**机器门 / 纪律切分：** `review_closure` 是 WARN observer（`shared/gates.md:149`），S2 不进门；`review_policy` 只做形状校验。

### 4.3 S4

| 落点 | 改动 |
|---|---|
| `shared/independent-review.md:223` | 在 `Critical` 证据链后增 `Major` 可触发路径义务：输入/状态/调用路径 + 已检查上游守卫；probe 须「命令 + 预期差异」；不可达即丢弃，不降级 |
| `shared/independent-review.md:231` | §10.5 模板描述增「证据要求 = file:line + 可触发路径（或可复跑 probe）+ 上游守卫」 |
| `templates/reviews/README.md:8` | 第 4 项改为「file:line + 可触发路径/可复跑 probe + 已检查上游守卫 + 可操作建议；无路径候选丢弃，并在报告末尾留一行候选 + 不可达原因」 |

**机器门 / 纪律切分：** 零代码、零门；依据 §2.4（本轮无结构化字段载体），不把「可触发」伪装成形状判据。

### 4.4 命名

- `atlas_verify` 的 `archive` / `archive_dir` / `write_archive`（`:133`/`:340`/`:405`）= **批留档**（成功批快照）。
- 本方案 = **证据归档**（失败批/跨轮证据），统一命名 `evidence_archive` / `.atlas-evidence` / `manifest.json`；契约与报告字段均用全称。

---

## 4.5 流程义务

### 4.5.1 RFC 号

- 今日 2026-11-04；`proposals/` 实查无其他 `RFC-20261104-*`；本文件即 **RFC-20261104-01**。
- 若写入前复核冲突：顺延 `RFC-20261104-02` 并在此记录实际号，不静默改号。

### 4.5.2 独立评审

- **需要**。三条都改契约/执行边界，走实例 ⑤（fresh context、只读、不修）。
- 重点：S1 是否真实现 `rings/e2e/reference.md:519` 的起跑前归档、`scripts_hash` 是否被污染、直跑 N/A 是否可接受；S2 的连续定义是否基于 `events`、WARN-only 效力；S4 零代码是否变成口号门；**P11 的 `.gitignore` 放开是否严格「只追加、不覆盖、只限运行产物行」**；**P12 的 teardown 是否真的只 copy + 写 manifest、不判定**；**P13 的软杀是否确实不改超时判定结果**。
- 评审产出 `proposals/REVIEW-20261104-01-<后缀>.md`（**号必须带后缀**，与已存在的 `proposals/REVIEW-20261104-01-d156-single-case-signoff.md` 区分；本轮不创建）；评审「改到能过」后才进实现。

### 4.5.3 D156 三态与依据

| 项 | 是否触发 D156 | 依据 (a)/(b) | **三态（二选一，已定）** | 形式要件 |
|---|---|---|---|---|
| S1 | **是，按 (b)** | 改 `rings/e2e/reference.md` 契约判据 + `scripts/atlas_verify.py` 执行路径；`git diff --name-only` 落 DR4 段级族 | **单案修复（无留出集）** | ① 评审确认（唯一判定记录 = `proposals/REVIEW-20261104-01-d156-single-case-signoff.md`，带后缀）② QUEUE 观察行：owner = `master`；期限 = 首个真实仓真跑后 2 周（不晚于下一个 beta 发版后 2 周，先到为准）③ 残留风险段（见下） |
| S2 | **是，按 (b)** | 改 `shared/independent-review.md` §11 契约判据 + `scripts/review_closure.py` / `_support/review_policy.py` | **单案修复（无留出集）** | ① 评审确认 ② QUEUE：owner = `master`；期限 = 首个真实仓出现连续 carried 后 2 周（不晚于下一个 beta 发版后 2 周，先到为准）③ 残留风险段 |
| S4 | **否** | 仅 §10.4/§10.5 + 模板，无机器判据 | N/A（未触发；按 §8.3 人工抽样验收） | 3 条历史 Major 抽样复放 |
| S3 | **否** | 未设计、未接线 | N/A | 触发后另开 RFC |

owner/期限的**句式**沿用 `duty-review/QUEUE.md:32-33` 的既有观察行；但 **owner 不是沿用**——原文是 `owner = 本批实施者`，P9 把它**改为** `master`（这是改一条既有写法，不是复制）。

**形式要件的落地义务（回应评审 10）：** 实现批**必须**落 QUEUE 观察行（owner=`master`，期限按上句）；未落则该条的 D156 形式要件未完成，S1/S2 不得宣称修复完成。

**S1 为何无可行留出集（回应评审 4）：** `shared/gates.md:107` ① 要求留出集能让 verdict / 案数 / 最近日期 / 精确病案数翻转；本件是**执行层归档动作**，归档**不参与判分**，无法制造上述任一翻转 ⇒ ① 对该件**结构性不可能**成立。② 在 `scripts/atlas_verify.py` 侧，既有钉都走同一条 `FAKE_CHECK` 路径（`tests/test_atlas_verify.py:46`），没有钉外的第三条 `atlas_verify` 判据路径可作留出（控制台的假 pw 与生成器的 `make()` 属另两个入口，不构成 `atlas_verify` 的第二条判据路径）。故无可行留出集，按单案修复，不声称闭族。

**S1 残留风险（须入 QUEUE 与本节）：** ① 直跑**只剩 teardown 未执行的情形**（SIGKILL、进程未正常退出、显式跳过）⇒ 该次无 post-run 归档、按 S1-20b 落 WARN + `partial`；pre-run 仍 N/A（B2 选 (i)）；② 归档 WARN 在无人看输出时静默；③ manifest 被篡改无消费者、不告警；不做事后对账（P10）；④ 无自动清理 ⇒ 磁盘单调增长；⑤ 符号链接/跨设备边界只覆盖到测试钉，真实仓未验；⑥ Playwright 在 SIGTERM 下是否 flush trace 未真跑验证。

**S2 残留风险：** ① WARN-only 可能被忽略（效力靠评审纪律）；② `premise` 可写成套话，判别性检查不真跑；③ 依赖逐轮 `findings/*.json` 完整性（缺轮即 N/A）；④ 不新增 schema 版本 ⇒ 旧报告不受影响，但字段语义无版本锚。

**S2 为何不再报「闭族」/ H3、H5 为何不能当留出集：** `tests/test_review_closure.py:66` 的 `write_report` 可写任意 `rounds: dict[int, list[dict]]`（`checks`/`resolves`/`review_scope` 全可造），H3（3 轮同指纹、仅末轮带字段）与 H5（r1/r3、缺 r2）都能由该助手直接产出 ⇒ 违反 `shared/gates.md:107` 留出独立性 ③「夹具不可由既有钉夹具只改…得到」（既有钉同样由 `write_report` 造）。仓内也无 3 轮真实评审语料（`git ls-files` 仅 `tests/fixtures/verify_playground/product/e2e/reviews/2026-01-01-fixture/` 单轮）。故按 **单案修复**，不声称闭族。

**S2 pre-fix 红证计划：** 在实现前的基线 `HEAD`（`d1674e3`）工作树只加测试、不加实现，跑 `python3 -m pytest -q tests/test_review_closure.py::test_two_round_carried_requires_premise`，预期 **红**（`result` 无 `premise_required` 键）。实现后同命令转绿；原始输出贴入 §8/实现批记录。

**S1 pre-fix 红证计划：** 同法跑 `python3 -m pytest -q tests/test_atlas_verify.py::test_failed_batch_archives_evidence`，预期 **红**（无 `.atlas-evidence` 目录）。实现后转绿。

**基线口径（回应评审 5）：** 当前 HEAD 是 `d1674e3`（`docs(proposals): sign off D156 single-case status (RFC-08/09)`）。`0299914`（`docs(proposals): delimit execution layer boundary (P1-3)`）**不是 HEAD，仅作历史起点**；红证与 D156 (b) 取证一律以 `d1674e3` 为基线，避免把 RFC-20261103-10 的改动混进本件 diff。

**原始命令输出（实现批回填，不在本轮伪造）：**

```bash
git diff --name-only d1674e3
python3 scripts/closeout_derive.py --diff-base d1674e3 --root .
```

### 4.5.4 新 D 行

- **需要，但只在实现阶段占号**：D 行现 180 条，末号 D182；下一号 **D183**（实现批必须在 `DESIGN.md` 记一行，号顺延，见 §7.2 落地义务）。本 RFC 不改 `DESIGN.md`。
- D183 建议：「E2E 证据归档到根级 `.atlas-evidence/`（起跑前 + 失败后 + teardown 补充），只归档证据面、不重判、不删；**放开 `patches/project-wiring/apply-wiring.py:342` 的「根 `.gitignore` 不存在即不首创」——仅限 `.atlas-evidence/` 等运行产物忽略行，缺文件则创建、已有内容不覆盖只追加缺失行，不代写用户其他规则**；`review_closure` 连续 carried 缺前提只 WARN；Major 需可触发路径/可复跑 probe，不可达即丢弃」。
- 若只批准部分项，D183 按批准项裁剪；不预设 D184。

### 4.5.5 变异号与四段协议

- **S2：M176**。变异 = 删除 `scripts/review_closure.py` 中 `carried_streak >= 2` 的 `premise_required` 分支；预期 `test_two_round_carried_requires_premise` 红。四段：基线绿 → 注入 → 指定测试红 → 逐字节还原（`sha256sum` 前后一致）→ 复绿。
- **S2：M176b**（**子号，不占新号**）。变异 = 把连续判定改回旧公式（用 `:292-297` 的 `prior_round`）；预期 `test_third_round_missing_premise_warns` 与 `test_four_round_streak_still_warns` **都红**，`test_two_round_carried_requires_premise` 仍绿（证明新钉专抓旧公式的漏检，不是重复钉）。四段同上。
- **S1：M177**。变异 = 删除 `_fail` 中的 `archive_run_artifacts(..., phase="fail")`；预期 `test_failed_batch_archives_evidence` 红。四段同上。
- **S1：M178**（回应「恒绿钉」）。注**刻意回归**：在 `atlas_verify` 读取 `.atlas-evidence/*/manifest.json` 的 `verdict` 并回填报告；预期 `test_forged_manifest_is_not_consumed_by_verify` 红。该钉是契约钉（防未来代码读归档反判），M178 证明它能红；不是「现有代码必红」的假变异。
- **S4：无变异**（零代码，无可注入判据；用 §8 抽样复放验收）。
- **S1/P12：M179**。变异 = 从发射的 config 里**摘掉 `globalTeardown: './atlas-evidence-teardown.ts'` 整段接线**（teardown `.ts` 文件保留）；预期 `test_emitted_config_carries_global_teardown` 红，`test_global_teardown_cli_archives_without_touching_verdict` 仍绿（CLI 单独可跑，证明「发射」与「行为」分开钉）。四段同上。
- **S1/P13：M180**。变异 = `_kill` 回退为直接 `proc.kill()`（SIGKILL，跳过 SIGTERM + grace）；预期 `test_archived_trace_is_independently_consumable[soft-kill]` 红（脚本未及 flush trace ⇒ 归档缺 `trace.zip` 或 zip 空），`[plain]` 档仍绿。**注意：M180 证明的是代码路径，不是 Playwright 的 SIGTERM flush 行为**，与 S1-20a 的断言强度匹配。四段同上。
- **S1/P13 兜底：M186**。变异 = 删掉 grace 到期后的 SIGKILL 升级（进程挂起不退出）；预期 `test_sigterm_ignored_escalates_to_sigkill` 红（测试超时/无 `partial`）。
- **P11 `.gitignore` 五条：M181–M185**。一一对钉：M181 去掉「缺失则创建」⇒ `test_gitignore_created_when_absent` 红；M182 改成整文件重写/覆盖 ⇒ `test_gitignore_append_preserves_existing_bytes` 红；M183 把只读当可写/吞异常不 WARN ⇒ `test_gitignore_readonly_warns` 红；M184 对已跟踪文件误判 WARN ⇒ `test_gitignore_tracked_file_appended_without_warn` 红；M185 忽略闭集反选、强行追加 ⇒ `test_gitignore_negation_rule_conflict_warns` 红。四段同上。
- **P12 吞异常：M187**。变异 = 去掉 teardown 的 `try/catch` 包裹；预期 `test_teardown_cli_never_exits_nonzero` 红（注入异常后 CLI 退出码非 0）。
- **编号自查**：M176 → M176b → … → M187；**M176b 是子号，不占新号**；仓内实际最大为 M175，落稿前实查全仓 `M181`–`M187` 均未占用，无撞号。用途分工：**M176 = S2 前提复核**；**M176b = S2 旧公式回退**；**M177 = S1 失败归档接线**；**M178 = S1 证据不得反向充当通过证据**；**M179 = P12 teardown 发射**；**M180 = P13 回退硬杀**；**M181–M185 = P11 `.gitignore` 五种路径**；**M186 = P13 删 grace 后升级**；**M187 = teardown CLI 吞异常**。
- 测试内既有局部变异编号（`M1..M11`）不动。

---

## 4.6 关联决定登记（不在本 RFC 改稿，落点归各自 RFC）

维护者同时拍板了跨越本 RFC 的三条，供评审与实现批对齐；**本轮不改那些文件**：

| 决定 | 落点（由各自 RFC 改） |
|---|---|
| 错表头静默 N/A 接受，残留风险写进 `RFC-20261103-08` §4.5（①） | `proposals/RFC-20261103-08-e2e-dim-header-validation.md` §4.5 |
| E2E 表强制前三列顺序（`AC ID` / `场景` / `回指规则`），否则该表 N/A（②） | 同上（`rings/e2e/reference.md` 契约 + `validators/validate_e2e_index.py`） |
| 「职责迁出 ≠ 物理迁出，`.atlas-run/` 仍是运行目录」（④） | `proposals/RFC-20261103-10-execution-layer-delimitation.md` |
| 「出现自动消费者就重评」触发器（⑤） | 同上 |

维护者拍板在本 RFC 的落点：P1a → §2.1；P1b/P5 → §2.1 + §4.1；P2/P6 → §2.1 + S1-15；P3 → §2.2；P4 → §2.3 + S4-5；P7 → §2.3 + S4-2；P8 → §0 + §1.1 + §4.5.3。

**本轮接受但必须记录的残余（复核项）：**

| 项 | 记录 |
|---|---|
| `.gitignore` 只读/冲突的持续代价 | 该路径会让 `.atlas-evidence` **长期未被忽略**：从该次生成起，直到用户手工补行；期间 `repo_git_dirty()` 恒真（`scripts/e2e_console.py:124-126`）⇒ `git_dirty` 恒真（`:397-405`）⇒ **每一批运行、每一次提交都挂 dirty 警告**（`:473`），不是「提示一次就完」。WARN 文案须写明「需手工补行」 |
| 跨批 `index.json` 并发 | 是 **lost-update（丢去重），不是损坏**：并发写只会让两批各自漏记一条索引，manifest 仍完整可读。锁作用域定死为「`index.json` 读-改-写 + 单次 manifest tmp→replace」；不锁归档复制、不锁跨批远端 |
| `test_global_teardown_absent_in_legacy_projects` | 接近恒真（无 teardown 的旧输出本就不会报错），保留为**兼容性姿态**，**不计入有效反钉/判据数量**（§5.1 已标注） |
| M180 的证明强度 | 证明的是**代码路径**（回退硬杀会让 `[soft-kill]` 红），**不是 Playwright 在 SIGTERM 下的 flush 行为**；与 S1-20a「模拟进程」的断言强度一致，不得在验收里当成真实行为已验证 |
| Playwright 对 `globalTeardown` 抛错的处理 | **未真跑验证**：本稿只保证 teardown 自身吞异常、CLI 退出码 0（`test_teardown_cli_never_exits_nonzero`），**不断言** Playwright 会把绿轮记为成功。实现批须真跑一次确认；**未确认前不得宣称该路径安全**，也不得把「Playwright 退出码仍 0」写成已测事实 |
| 解释器依赖 | `_support/evidence_archive.py` **只用标准库**；`ATLAS_PYTHON`（缺省 `python3`）只需能跑标准库 + `zipfile`。目标项目无 `python3` 时 teardown 落 **WARN**、不翻红（与 CLI 吞异常同口径） |

---

## 5. 测试钉

> 不新增测试文件：全部钉进既有 `tests/test_atlas_verify.py`、`tests/test_e2e_console.py`、`tests/test_gen_e2e_scripts.py`、`tests/test_review_closure.py`、`tests/test_review_report.py`，因此 `shared/gates.md:113` 的 52 不变 53。

### 5.1 S1

| 钉 | 用例 | 夹具 | 预期 |
|---|---|---|---|
| 正钉 | `test_failed_batch_archives_evidence` | 既有 `FAKE_CHECK`（`tests/test_atlas_verify.py:46`）写 `.atlas-run/trace.zip` + `test-failed-1.png`，检查失败（沿用 `:141` 形态） | `.atlas-evidence/<id>/manifest.json` 存在；`files[]` 含两类证据；`atlas_verify` 仍 exit 1 |
| 反钉（改名，回应恒绿） | `test_forged_manifest_is_not_consumed_by_verify` | 预置伪造 manifest（`verdict=pass`），真实检查失败 | `atlas_verify` 仍 exit 1；**命名与注释明确它是契约钉**，杀伤由 M178 证明 |
| 功能探针（回应评审 3） | `test_archived_trace_is_independently_consumable[plain]`（参数化两档之一） | 归档后**删除整个 `.atlas-run`**；用 `zipfile.ZipFile` 打开归档里的 `trace.zip`，按 manifest 重算 `files[].sha256` | zip 可打开且含 trace 事件；重算 sha256 与 manifest 逐一相等；不依赖源目录存在 |
| 功能探针（P13，**复用同一条钉，不造第二条同型钉**） | 同用例 `[soft-kill]` 档 | 子进程收到 SIGTERM 后先写 `trace.zip` 再正常退出——这是**模拟**，不是 Playwright 真实行为；断言走同一个 `_assert_archive_consumable` 助手 | **trace 在 ⇒ 归档 PASS**；**trace 缺 ⇒ 落 S1-20b WARN**；运行判定仍 FAIL。**Playwright 在 SIGTERM 下是否 flush 未真跑验证**（`_kill` 只对 node 进程，`scripts/e2e_console.py:1028-1036`） |
| 边界钉（B4） | `test_sigterm_ignored_escalates_to_sigkill` | 子进程 `signal.signal(SIGTERM, SIG_IGN)` 后挂起 > grace | grace 到期后 SIGKILL；该次 WARN + `partial`；`timed_out` 仍 True；**M186 证明删掉 grace 后的 SIGKILL 会红** |
| 边界钉 | `test_archive_is_idempotent_and_never_overwrites` | 同 source/时间调用两次 | 第二次 `-2`；第一份文件与 sha256 不变 |
| 边界钉 | `test_pre_run_archives_legacy_atlas_run` | 预置升级前 `.atlas-run` 证据 | 起跑前归档成功；清空后 `.atlas-evidence` 仍在 |
| 边界钉（B4，拆两轴） | `test_trace_off_is_na_but_archive_still_passes` | ① 该案 `trace_enabled=False`、失败但有 png；② 该案 policy 未知且失败无 `trace.zip` | ① trace **N/A**，但 **归档 PASS**（png 在、manifest 建）；② trace **WARN**，**不得 N/A** |
| 边界钉 | `test_archive_failure_is_warn_not_fail` | **注入** `evidence_archive` 的复制函数抛 `PermissionError`（不依赖 FS 权限）；另加 `os.geteuid() == 0` 的 `skipif` 变体 | 归档 WARN；原失败批仍 FAIL；不改判 |
| 边界钉 | `test_archive_symlink_escape_refused` | `.atlas-evidence` 为指向根外的符号链接 | 拒绝写入，WARN，根外无文件 |
| 关系钉 | `test_evidence_archive_outside_scripts_hash` | 归档后计算 `scripts_hash` | 与归档前一致；`.atlas-evidence` 不进指纹（`_RUNTIME_PATH_PARTS` 已登记） |

**P12 teardown 钉（落 `tests/test_gen_e2e_scripts.py`，复用既有 `make()` 夹具，不新增文件）：**

| 钉 | 用例 | 夹具 | 预期 |
|---|---|---|---|
| 发射钉 | `test_emitted_config_carries_global_teardown` | 既有 `make(root)` 生成项目，读发射的 `playwright.config.ts` 与 `scripts/atlas-evidence-teardown.ts` | config 文本匹配 `'./atlas-evidence-teardown.ts'` 且**不得出现** `'./scripts/atlas-evidence-teardown.ts'`；teardown 文件含 `execFileSync` 调用 `evidence_archive.py --phase post-run`；原配置其余内容逐字节不变 |
| 仅归档钉（**subprocess 调 Python CLI**） | `test_global_teardown_cli_archives_without_touching_verdict` | `subprocess.run([sys.executable, evidence_archive.py, "--phase", "post-run", "--root", tmp])`，预置 `.atlas-run` 证据面 | 生成 `<id>-post-run/manifest.json`；`phase="post-run"`；**无 verdict 字段**；进程退出码 0 |
| 吞异常钉（应修 2a，**只测可观测的那半**） | `test_teardown_cli_never_exits_nonzero` | 直接调 Python CLI，注入 `PermissionError` | **CLI 退出码仍 0**；stderr 有记录；**不**断言 Playwright 退出码（未真跑） |
| 缺席钉（兼容姿态，**不计入有效反钉/判据数量**） | `test_global_teardown_absent_in_legacy_projects` | 未接入归档模块的旧生成器输出 | 不报错、不阻断（N/A）；接近恒真，只作旧项目兼容 |

**P11 `.gitignore` 钉（落 `tests/test_gen_e2e_scripts.py`，五条对应 §2.1 可判定闭集与 M181–M185）：**

| 钉 | 用例 | 夹具 | 预期 |
|---|---|---|---|
| 缺失创建 | `test_gitignore_created_when_absent` | 临时根无 `.gitignore` | 文件被创建且只含 `.atlas-evidence/` 行；输出 `gitignore_created`；不 WARN |
| 追加不改字节 | `test_gitignore_append_preserves_existing_bytes` | 预置含用户规则、末尾无换行的文件 | 先补换行再追加；**原有字节与行序逐字节不变**；输出 `gitignore_appended` |
| 只读 | `test_gitignore_readonly_warns` | `chmod 0444`（`skipif` 为 root） | 不写，WARN `gitignore_readonly`；文件内容不变；归档仍继续 |
| 已跟踪 | `test_gitignore_tracked_file_appended_without_warn` | `git init` + `git add .gitignore`，文件缺该行 | 正常追加，输出 `gitignore_tracked_appended`；**不 WARN** |
| 冲突 | `test_gitignore_negation_rule_conflict_warns` | 预置 `!.atlas-evidence/`（闭集内的显式反选） | 不写，WARN `gitignore_rule_conflict`；文件不变 |

**防假绿：** 除 manifest 字段外，必须有一条**功能探针**证明归档可独立消费（删源目录后仍能打开 `trace.zip`、重算 sha256 一致），不得用存在性代替「能不能真的用」（`shared/gates.md:106`）。

### 5.2 S2

| 钉 | 用例 | 夹具 | 预期 |
|---|---|---|---|
| 正钉 | `test_two_round_carried_requires_premise` | `write_report({1:[fp],2:[fp]})`，无字段 | `status=WARN`，`premise_required` 长度 1，exit 0 |
| 反钉 | `test_two_round_carried_with_premise_passes` | 同上，字段齐全 | `premise_required` 为空，无新 WARN |
| 边界钉 | `test_single_round_carried_no_premise` | 只有最新 1 轮 open | 不触发 |
| 边界钉 | `test_resolved_round_breaks_streak` | r1 open、r2 resolves、r3 open | 不触发 |
| 边界钉 | `test_round_gap_is_not_consecutive` | `write_report({1:[fp],3:[fp]})`（缺 r2） | 因 `3-1 != 1` 不触发；用例注释写明依据是轮差，不是 `events` 相邻性 |
| 边界钉 | `test_same_round_duplicate_deduped_in_round` | 同轮同指纹重复 | 本轮计一次；`premise_required` 按一次算；沿用既有重复 WARN；**不因跨轮 `prior_fps` 命中归 N/A** |
| 边界钉（最严档） | `test_same_round_duplicate_keeps_strictest_level` | 同轮同指纹先 Critical 后 Major（及反向） | 该轮等级取 **Critical**；不因去重降级；`premise_required` 仍按一次算 |
| 边界钉（B1） | `test_third_round_missing_premise_warns` | `write_report({1:[fp],2:[fp+字段],3:[fp]})` | `premise_required` 长度 1、`status=WARN`；**错公式（用 `prior_round`）会算成 3−1=2 ⇒ N/A ⇒ 此钉必红** |
| 边界钉（B1） | `test_four_round_streak_still_warns` | `write_report({1:[fp],2:[fp],3:[fp],4:[fp]})`，全缺字段 | 最新轮 r4 仍触发；streak 不因 r2/r3 的 `prior_fps` 命中而中断 |
| 边界钉 | `test_level_change_still_requires_premise` | r1 Critical open、r2 Major open，缺字段 | 仍触发 |
| 形状钉 | `test_premise_optional_fields_shape`（`test_review_report.py`） | 合法/非法 `premise`/`discriminating_check` | 合法通过；非法 exit 2 |

**防「红灯训练成噪声」（替换恒真断言）：** 断言三条——① 连续两轮缺字段 ⇒ `premise_required` **稳定出现**；② 同一夹具连跑两次，`premise_required` 与 `warnings` 的**条目序与内容逐字节稳定**（`json.dumps(..., ensure_ascii=False)` 直接比对）；③ 字段齐全轮 ⇒ **不产生新 WARN**。不写「任何情况下不 FAIL」——`status` 只可能是 PASS/WARN（`scripts/review_closure.py:433`），且 `atlas_check` 从不含它（`shared/gates.md:149`），该断言恒真、不可失败。若未来要把 WARN 升门，须另开 RFC + D156，不在本 RFC 偷升。

### 5.3 S4

- **不落测试文件**：本轮零代码、无结构化载体，硬造文本存在性测试只会假绿（§2.4）。
- 验收 = 人工抽样：从既有 `proposals/REVIEW-2026*.md` 取 3 条 `Major`，按新模板写「输入/状态/调用路径（或可复跑 probe：命令 + 预期差异）+ 已检查上游守卫」；任一条写不出 ⇒ S4 未达成。

---

## 6. 计数链与 docs/map

| 计数 | 当前 | 之后 | 同步点 |
|---|---|---|---|
| 校验器数 | 10（`shared/gates.md:68`） | 10 | 不新增 validator |
| 测试文件数 | 52（`shared/gates.md:113`） | 52 | 不新增测试文件；P12/P13 新钉全部复用既有文件（P12 → `tests/test_gen_e2e_scripts.py`，P13 → `tests/test_e2e_console.py` 的既有探针参数化），故测试文件数不变 |
| `install.py` 自检条数 | 65（`shared/gates.md:82`；`docs/map/index.md:112` 的「65 条」为**人工口径**） | **66** | 新增 `_support/evidence_archive.py` 一条自检；gates + canonical 机器比对；`docs/map/index.md:112`「65 条」→「66 条」**不在机器口径内，必须人工改** |
| 共享内核件数 | 11（`docs/map/atlas-map.html:172` 的 `内核 ×11`、`:529` 的 `(11 件)`；`docs/map/index.md:37`/`:111`） | **12** | **2 机器 + 2 人工**：机器 ① `tests/test_map_anchors.py:365-371` 的 `r"内核 ×(\d+)"` 读 `docs/map/atlas-map.html:172`；机器 ② `:279-288` 的 `check_snapshot` 判 `docs/map/index.md:111`；人工 ③ `docs/map/atlas-map.html:529` 的 `(11 件)`；人工 ④ `docs/map/index.md:37`（两者不被上述正则读取） |
| 最大单件行数 | 2614（`docs/map/index.md:113`、`docs/map/e2egen.md:16`、`docs/map/atlas-map.html:357`/`:499`） | **必漂，实现后实测回填** | **2 机器 + 2 人工**：机器 ① `tests/test_map_anchors.py:279-288`（`docs/map/index.md:113`）；机器 ② `:355-358`（`docs/map/e2egen.md:16`）与 HTML `:357`/`:499`（由 `:365-371` 的 HTML 规则读）；人工 ③/④ 新值只能实现后实测，回填到上述四处。P11/P12 必改 `scripts/gen_e2e_scripts.py` 行数 ⇒ 必须同批改，否则地图门红 |
| `scripts_hash` | 现行指纹（不含 `.atlas-evidence`） | **一次性基线变化** | P12 发射的 `scripts/atlas-evidence-teardown.ts` 与 `.atlas-trace-policy.json` 都在 `scripts/e2e_console.py:157` 白名单内 ⇒ 进指纹；交付记录须附新值；`docs/map` 文件清单两个都加 |
| D 行 | 180，末号 D182 | **181，末号 D183** | 实现阶段写 D183；本 RFC 不写 |
| e2e_console 行数 | 1396（`docs/map/e2egen.md:17`、`docs/map/atlas-map.html:371`、`:500`） | 增加（P13 改 `_kill`） | 三处同步；HTML 两处由 `:365-371` 机器读 |
| review_closure 行数 | 490（`docs/map/atlas-map.html:516`） | 增加 | `docs/map/review.md:15` 无行数，只有锚（`:77`/`:137`/`:191`/`:101`），插入点在 397 后 ⇒ 锚不漂 |
| gate 表行数 | — | — | **本 RFC 不断言数字**：表头/分隔行是否计入无唯一口径，改为只声明「不新增门行」 |

**docs/map 锚点：**

- `docs/map/e2egen.md:54` 的符号是 **`resolve_pw`**（`scripts/e2e_console.py:649`），不是 `run_pw`；同行的 `snapshot:568`、`repo_provenance:394`、`Ledger:682`、`Runner:811` 在 S1 插入（`Runner._run` 内）后不漂。
- `docs/map/review.md:15` 的 `state_of:77` / `round_declares:137` / `last_close:191` / `load_prior_rounds:101` 均在 378 之前，S2 插入后不漂。
- **计数一致性**：`tests/test_map_anchors.py:262-263` 按 `len(_support/*.py)` 实算期望值，`:365-371` 只从 `docs/map/atlas-map.html` 抓 `内核 ×N`；因此新增 `_support/evidence_archive.py` 时，**机器会咬红 `docs/map/atlas-map.html:172`**，而 `:529` 的 `(11 件)` 与 `docs/map/index.md:37`/`:111` 只能靠人同步（§6）。

---

## 7. 落地顺序、拆分与回滚

### 7.1 顺序

1. **S1 先落**：唯一在持续丢数据的问题；`docs/map` 同步**绑进 S1 同一个提交**（否则单独落 S1 时 `test_map_anchors` 会红）。
2. **S2 第二**：WARN-only，独立于 S1；落完先观察 2 轮评审，再议是否升门（本 RFC 不升）。
3. **S4 第三**：零代码，最后落。

### 7.2 提交拆分

- S1、S2、S4 各自一个独立提交，均可单独回滚；S1 内部分两小步（helper + 测试 / 接线 + 报告 + docs/map），同一提交。
- **D183 落地义务（P11 放开的记账）**：S1 实现批**必须**在 `DESIGN.md` 记一行 D183（号顺延，现末号 D182 ⇒ D183），正文写明「本次放开 `patches/project-wiring/apply-wiring.py:342` 的『根 `.gitignore` 不存在即不首创』，**仅限 `.atlas-evidence/` 等运行产物忽略行，不代写用户其他规则**」。未记 D183 则 S1 不得宣称完成——放开已落地裁决却不记账，等于让后续评审无从追溯。
- **P12 落地义务**：改 `scripts/gen_e2e_scripts.py:2405` 发射 `globalTeardown` 时，同一提交内更新 `rings/e2e/reference.md` 的归档点表述（起跑前 = 包装器、跑后补充 = teardown），不得只改代码不改契约文字。

### 7.3 回滚

| 项 | 回滚动作 | 数据影响 |
|---|---|---|
| S1 | 移除归档调用/helper/layout 属性/忽略行写入；保留已生成 `.atlas-evidence` 不删 | 旧 `.atlas-run` 证据仍在；新归档停止；**已生成 manifest 变成无消费者的孤儿，不自动清理**（按 P1a 显式操作处理） |
| S2 | 移除 `premise_required` 计算与字段校验；旧 `review.json` 可选字段被忽略 | 旧评审记录不改写；WARN 消失；无迁移 |
| S4 | 回退模板与 §10.4/§10.5 文字 | 无运行时影响 |

### 7.4 存量数据兼容

- **存量 `.atlas-run/`**：S1 起跑前归档，升级后第一次运行也先把旧证据搬走再清空。
- **存量 `.atlas-evidence/`**：不存在；用户已手建时只新建子目录，绝不覆盖/删除。
- **存量评审记录**：S2 不回写历史；跨升级 carried 缺字段 ⇒ 下次 closure WARN，补齐即消失，不阻断。
- **直接 `atlas_check`**：**pre-run 不归档（N/A）**；**post-run 由 config 里的 `globalTeardown` 归档**（P2/P6 选 (i)，残余只剩 teardown 未执行的情形）。

---

## 8. 验收标准

### 8.1 S1

```bash
# 实现前（基线 HEAD d1674e3，只加测试）：预期红
python3 -m pytest -q tests/test_atlas_verify.py::test_failed_batch_archives_evidence

# 实现后：预期绿
python3 -m pytest -q tests/test_atlas_verify.py
python3 -m pytest -q tests/test_e2e_console.py
python3 -m pytest -q tests/test_e2e_console.py -k "independently_consumable"
python3 -m pytest -q tests/test_gen_e2e_scripts.py -k "global_teardown"
python3 -m pytest -q tests/test_gen_e2e_scripts.py -k "gitignore"
```

人工复核（用测试夹具产出的 archive 路径）：

```bash
python3 - <<'PY'
import json, pathlib
p = next(pathlib.Path('.atlas-evidence').glob('*fail*/manifest.json'))
d = json.loads(p.read_text())
assert d['verdict'] == 'fail'
assert any(f['name'] == 'trace.zip' and f['sha256'] for f in d['files'])
assert not any(f['name'] in {'results.json', '.last-run.json'} for f in d['files'])
print(p)
PY
```

预期：打印 manifest 路径；`files[]` 含 `trace.zip` + `test-failed-*.png` 且各有 sha256；不含判分面文件；`atlas_verify` 仍 exit 1。

### 8.2 S2

```bash
# 实现前：预期红（缺 premise_required 键）
python3 -m pytest -q tests/test_review_closure.py::test_two_round_carried_requires_premise

# 实现后：预期绿
python3 -m pytest -q tests/test_review_closure.py
python3 -m pytest -q tests/test_review_report.py
```

预期：`test_two_round_carried_requires_premise` 断言 `status=WARN`、`premise_required` 长度 1、退出码 0；缺轮用例 `premise_required` 为空；非法字段形状 exit 2。

### 8.3 S4

- 抽样 3 条历史 `Major`，每条都能写出「路径（或可复跑 probe：命令 + 预期差异）+ 上游守卫」；任一写不出即未达成。

### 8.4 计数、地图、总门

```bash
python3 tests/test_canonical_consistency.py
python3 tests/test_map_anchors.py --fix
python3 tests/test_map_anchors.py
python3 scripts/atlas_check.py --root . --fast
```

预期：canonical 通过（install 66、tests 52、validators 10、共享内核 12 一致）；map 0 stale；`atlas_check --fast` 无 `FAIL`（S2 的 WARN 不出现在门面）。M176–M187 四段协议的红/绿输出附实现批记录，不提交变异。

---

## 9. 拍板状态

**P1–P13 全部已定，无未决项。**

| # | 决定 | 落点 |
|---|---|---|
| P1a/P1b | 归档不自动清理；证据根 = 根级 `.atlas-evidence/` | §2.1、§4.1 |
| P2/P6 | 直跑 `atlas_check`：**pre-run 不归档（N/A），post-run 由 teardown 归档**；残余只剩 teardown 未执行 | §2.1、S1-15、§4.5.3 |
| P3 | S2 只 WARN、永不阻断 | §2.2 |
| P4 | S4 probe 须「命令 + 预期差异」 | §2.3、S4-2 |
| P5 | 归档失败只 WARN，不改判 | §2.1、§4.1 |
| P7 | 丢弃候选留痕一行 | §2.3、S4-5 |
| P8 | 目的 = 回灌应然资产（spec/判据/PRD 期望） | §0、§1.1、§4.5.3 |
| P9 | D156 单案修复的 QUEUE owner = `master` | §4.5.3 |
| P10 | 不做 `--verify-archive` | §2.1 末条、§2.6 |
| **P11 = A** | 生成器在根 `.gitignore` 缺失时创建并追加 `.atlas-evidence/`；**这是改一条已落地裁决**（`patches/project-wiring/apply-wiring.py:342`），故须记 D183；范围仅限运行产物忽略行 | §2.1（含 6 条冲突路径）、§4.1、§4.5.4、§7.2 |
| **P12 = 同批** | `globalTeardown` 作为**补充**落进生成器发射的 config，并发射 `scripts/atlas-evidence-teardown.ts`（subprocess 调 `evidence_archive.py --phase post-run`、吞异常）：只 copy + 写 manifest、不判定、不改 verdict；本体仍是 `atlas_verify`/`e2e_console` | §2.1 第三个归档点、§2.5 否决论证、§4.1、§6（`scripts_hash`/docs/map） |
| **P13 = A** | `_kill` 改软杀：SIGTERM → `kill_grace_secs`（默认 5s，0–15s）→ 仍不退才 SIGKILL；超时判定先发生、grace 后仍置 `timed_out` ⇒ FAIL；只对 node 进程发 SIGTERM | §2.5、§3.1 S1-20a/20b、§4.1 |

本轮范围外（不在本稿实现，也不留可选项）：`--verify-archive` 事后对账、证据保留期/自动清理、S3 的 Launch/Doctor/Cleanup（§2.6）。

---

## 10. 评审回执（14 条）

| 评审条 | 改在 | 怎么改 |
|---|---|---|
| 1 `duty-review/bugs.md:41` 冲突 | §1.1、§0、§4.5.3 | 写成「按纪律先行、门槛未触发」；列出将来触发所需 4 项取证；明确 `rings/e2e/reference.md:519`/`scripts/atlas_verify.py:31-32` 只是既有契约/已知观察，不作升格新证据 |
| 2 D156 三态自洽 | §4.5.3 | S1 二选一 → **单案修复（无留出集）**，补 owner/期限/5 条残留风险；S2 也改单案（说明 `write_report` 能造 H3/H5、仓内无 3 轮真实语料），补 pre-fix 红证命令 |
| 3 根级目录无写入者/dirty 链 | §2.1、§4.1、§6 | 加 `shared/layout.md` §1 第五落点；写明 `repo_git_dirty:124-126` → `:397-405` → `:473` 链；根 `.gitignore` 写者与首创权 **P11=A 已定**（缺失创建 + 只追缺失行，记 D183，冲突路径按闭集 6 条见 §2.1）；现有写盘函数在 `scripts/gen_e2e_scripts.py:2575-2577`（2573-2574 是 auth setup）；`scripts/gen_e2e_scripts.py:2575-2577` 现状是 create-only（本轮回执已按评审 12 更正） |
| 4 S2 streak 读 events | §2.2、§3.2 S2-5/S2-11、§5.2 | 连续改为：`prev` = `events[fp]` 中 `< latest_round` 且 `kind=="check"` 的最大轮，判 `latest_round - prev == 1`；**不再用 `:292-297` 的 `prior_round`**；同轮重复只在本轮内去重（不归 N/A）；补 `{1,2,3}`、`{1,2,3,4}` 钉 |
| 5 S1 真值表边界 + 拆 N/A | §3.1 | 新增 S1-5/9/10/11/12/13/18；**两轴独立**：归档轴与 trace 轴分开判；`trace: off` ⇒ trace N/A 但归档仍 PASS；批次策略未知 ⇒ WARN，永不 N/A |
| 6 恒绿伪造钉 | §5.1、§4.5.5 | 改名 `test_forged_manifest_is_not_consumed_by_verify` 并注明契约钉；加 **M178**（注入「读归档回填 verdict」）证明可红 |
| 7 防噪声断言恒真 | §5.2 | 去掉恒真的「绝不 FAIL」，换成可失败的确定性断言：同一夹具连跑两次，`premise_required` 与 `warnings` 条目序与内容逐字节稳定；另加「稳定出现」「齐全轮无新 WARN」 |
| 8 计数链 | §6 | 共享内核 11→12；**2 机器 + 2 人工**：机器 `docs/map/atlas-map.html:172`（`内核 ×N`）、`docs/map/index.md:111`（`check_snapshot`）；人工 `docs/map/atlas-map.html:529`（`(11 件)`）、`docs/map/index.md:37`；最大单件 2614 另列（`docs/map/e2egen.md:16`/`docs/map/index.md:113`/HTML `:357`/`:499`，P11/P12 改生成器行数后必漂）；`docs/map/index.md:112`「65 条」人工改 66；删除无口径的 gate 表行数；`docs/map/e2egen.md:54` 改为 `resolve_pw` |
| 9 控制台双份 | §2.1、§2.5 | 定「批首一次 pre-run + 每失败用例一次 fail + 同 sha256 去重」；把双写列入否决表 |
| 10 顺序/回滚孤儿 | §7.1、§7.3 | `docs/map` 绑进 S1 提交；回滚后 manifest 变孤儿、不自动清理 |
| 11 特权容器假绿 | §5.1 | 改为注入 `PermissionError` + `euid==0` `skipif` 变体 |
| 12 命名混淆 | §2.1、§4.4 | 明写「留档（`atlas_verify.archive`，`:133`/`:340`/`:405`）≠ 证据归档」 |
| 13 备选重论证 | §2.5 | 承认 `globalTeardown` 收益；删掉「与代码不符」那条断言，改为已知事实（`playwright.config.ts` 唯一写者是 `scripts/gen_e2e_scripts.py:2405`、归属稳定）；列出仍不作本体的 4 条具体权衡（含 `_kill` 的硬杀事实）；**P12 已定：同批作为补充**；`reachability` 必填字段的否决改由 §2.4「本轮无结构化载体」论证 |
| 14 S4/S2 口径统一 | §2.4 | 归因改为「S4 本轮无结构化字段载体，故无形状面」；承认 probe 与 `discriminating_check` 同构可机判；明确未来引入字段时应按 S2 做形状校验 |
