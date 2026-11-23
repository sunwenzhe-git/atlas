# RFC-20261123-01 机制文档触及申报判决面（WARN→FAIL 升格零件）

状态：**评审修后通过（2026-11-23，意见全采纳，v2 待落刀）**；首轮评审 tech-proposal-reviewer，2 Blocker + 4 Major + 5 Minor 全采纳（轮记见 §9）
日期：2026-11-23
前置：`RFC-20261122-04`（机制文档机器面 WARN 提示族）＋ playground 装配态实测（2026-11-23）

## 0 一句话

给机制文档「触及」面加**申报制判决**：改动命中某篇 `mechanism-paths:`、该篇未跟改、任务又没有该篇的 `not-involved` 申报 ⇒ `atlas workflow verify` **FAIL**（rc 1 + 扣预算）；篇的 `mechanism-paths:` 含非法 glob 形态（裸 `**` / 单星 / `?` / 非两档）⇒ 同位 FAIL。触及提示 WARN 全量退役由判决面取代；死 paths / 死测试锚 / `pending` 豁免 / 提示族 CAP 维持现状。

## 1 证据（为什么现在升格）

`RFC-20261122-04` 评审定的升格条件 = 上线误报率数据 + 实际漏单，另案。本 RFC 兑现该「另案」，**兑现方式如实登记：设计变更兑现，非数据兑现**——playground 实测 0/3 是合成夹具样本不构成误报率数据；真正的兑现是申报阀 redesign 把「误报代价」从「可能被拦」降为「一行申报」，误拦态结构性消失（首轮评审 Major-4③ 指正采纳）。

- **playground 装配态实测（2026-11-23，装配 `db63465f`）**：检出 2/2（触及点名篇名+文件精确、死 paths 出声且静态）、误报 0/3（良性暂存、同目录近邻、`.bak` 后缀全静默）、单星拒收不污染合法集、`pending` 豁免对照实证、CAP/词表语义全过。门咬合在装配态宿主成立。
- **实测同时咬出升格阻断点**：触及提示**不查篇自身是否在暂存集**（文档跟改了照样 WARN，B1 实证）⇒ 它是「去看一眼」提示不是「不同步」判决；直接 WARN→FAIL 翻转 = 每次覆盖面改动必拦、文档跟改也拦，误拦 100% by design。
- **结论**：缺的不是升格决心，是判决零件——**申报制豁免阀**。加了它，FAIL 的每次拦截都可归因（真没跟改，或拒绝履行申报义务），不存在「文档跟改了还被拦」的冤枉态。

## 2 判决语义（核心判据）

### 2.1 判决表

对每篇非 `pending` 机制篇（发现面维持 RFC-04 frontmatter 全仓扫描），设：

- `S` = 暂存文件集（`git diff --cached --name-only --no-renames`；**判决面剔除 `.atlas/` 前缀路径**——卡产物自身（含申报文件）入暂存不得触发触及，与 `_MECH_PRUNE_DIRS` 同口径，首轮 Blocker-1①）
- `H` = `S` ∩ 篇 globs 命中集
- `D` = 篇文件 ∈ `S`（该篇本次已被跟改暂存）
- `A` = 申报面含该篇 `not-involved` 行（理由非空）

| 场景 | H 非空 | D | A | 判定 |
|---|---|---|---|---|
| 已跟改 | ✓ | ✓ | 任意 | **PASS（静默）**——篇在暂存即视为已核对跟改；残留申报行成死行（见 2.3），不影响判定 |
| 未跟改未申报 | ✓ | ✗ | ✗ | **FAIL**：点名篇 + 命中文件预览 + 可复制申报行模板 + 精确落点路径 |
| 未跟改已申报 | ✓ | ✗ | ✓ | PASS（信任申报） |
| 无触及 | ✗ | 任意 | 任意 | 静默（现状不变；单独改篇 H✗D✓ 亦静默） |

- **申报是整卡有效非轮次有效**（首轮评审登记的已知残余）：第 1 轮申报 `not-involved` 后，同卡后续轮深改同机制仍静默 PASS。卡短命（收口归档）使残余窗口有限，显式接受；真需要轮次有效性时另案。
- 「信任申报」残余：理由真伪机器不可判，本门管义务履行不管理由真伪，显式接受。

### 2.2 申报面（`mech-declares.md`）文法（首轮 Blocker-2，写死不留白）

落点 `<tasks_root>/<unit>/mech-declares.md`（`record_attempt` 同款 `parents=True` 自动建目录；unit 经 run 子卡解析后的**最终 unit**为准）。合法行恰三类：

1. 空行；
2. `#` 开头注释行（整行）；
3. 申报行：`- <篇相对路径>: not-involved: <理由>`，理由须非全空白。

**存在任何其余非空行 ⇒ FAIL「申报文件不可解析」**（fail-closed，点名行号与原文）。路径匹配沿用暂存集同款归一化（strip 前导 `./`、`\`→`/`，逐字比对，不做大小写折叠）。申报行指向零发现篇 ⇒ 不判 FAIL，审查通过后 WARN「申报死行」（镜像 RFC-04 M2，作用域限卡生命周期）。

- **零新 CLI 参数**：verify 已持 `tasks_root`+`unit`，自动读申报文件；`run` 透传天然生效；申报文件随卡归档（镜像 attempts.jsonl 落点语义），审计留痕。
- **`updated` 词不需要**：篇是否跟改由机械事实（∈ 暂存）表达，词表收窄到单字 `not-involved`。
- **FAIL 文案承担教学义务**：每条未申报 violation 打印**可复制申报行**（含该篇精确相对路径）与解析后落点 `<tasks_root>/<unit>/mech-declares.md`（首轮 Blocker-2 杀手简化 + Major-2：治 run 子卡解析后「申报放错目录」与「手打路径口径分歧」）。

### 2.3 词表机器化：两档收紧（首轮 Blocker-1② + Major-3）

`mechanism-paths:` 条目合法形态恰两档（契约 §60「两档 glob」正文由此获得机器判据，**逆紧登记**：中段 `**`（`a/**/b`）此前引擎可解析、机器判自本 RFC 起拒收）：

1. 字面路径：不含 `*` 亦不含 `?`；
2. 目录子树：`<字面路径>/**`（`**` 恰在末尾且前缀字面；裸 `**`、`**/x`、`a/*/b`、含 `?` 均非法）。

非法条目维持现有 bad-globs 隔离（不污染合法集）+ 审查后 WARN 点名；**且判决位升格 FAIL**（`mechanism_paths_invalid`）：否则「写精确 glob 的篇被门管、写歪 glob 的篇永久免检」激励倒挂（首轮 Major-3）。`pending` 篇豁免的是 paths 覆盖判定，**不豁免词表非法**（词表非法是词形缺陷非覆盖判定，与既有「pending 篇 bad globs 照样点名」同语义）。

### 2.4 判决位次与退出码（首轮 D5/D2 采纳）

- **位次 = 前置判定带**（`staged_empty` → 预算门 → **申报+词表判决** → 审查启动）：忘申报/写歪 glob 就不烧一轮 fresh-context 审查 token（T3 口径 ~356k+/轮）。前置红因也是该轮唯一红因（该轮审查未启动），不破坏「一轮一个主红因」叙事。
- **fail ⇒ rc 1** + `record_attempt(cause=...)`。混合违规（既有未申报又有坏 glob）⇒ cause 取 `mechanism_paths_invalid`（修 glob 先于申报，词形是根因）。
- **`--dry-run` 不判决不记账不出红**（与 staged_empty/预算门同带）；**`--json`** 下判决 FAIL 输出 `{"unit","status":"gate_fail","cause","violations":[{doc,kind,hits}...]}`，人读 FAIL 行照旧 stderr。
- **绕行面不变**：直跑 `atlas review --staged` 不经过判决面，属既有绕行面（人工责任，与预算门同一口径）。

## 3 维持不变（明确不动）

- 死 paths / 死测试锚 两条 WARN 原样（提示族残部，仍在审查通过后出声——红轮不可见 = 现状不变，不顺手改语义）。
- 单星/非法 glob 的**审查后 WARN** 原样保留（判决位 FAIL 不吸收审查后 WARN——前者拦流程、后者是提示族残部；同轮前置 FAIL 后审查不跑故二者不同轮出现，无重复出声）。
- `pending` 冷启动豁免对 paths 覆盖判定原样（触及/死 paths 均不判；词表非法照点名/照 FAIL）。
- 提示族 `CAP=5` 点名上限 + 汇总行原样；**判决 FAIL 面不设 CAP**（篇量级 ~15 全列，每条带出路文案，首轮 Minor-1）。
- 写法纪律（single-source §60 五条）不新增条目；④「改机制链必看篇」措辞随批微调（核对指令 → 申报义务）。

## 4 咬合面清单（落刀必动）

| 面 | 动作 |
|---|---|
| `_support/workflow_verify.py` | 词表收紧（两档谓词替换单星正则）；新增申报判决函数（复用 discover/`_mech_hit`/`_tracked_files` 现款；`.atlas/` 过滤；文法解析 fail-closed；模板文案）；删触及提示 WARN 分支；`mechanism_doc_findings` 支持传入已发现篇集（防 discovery 双跑）；新增申报死行 WARN |
| `scripts/atlas_workflow.py` | `cmd_verify` 前置带接线判决 + FAIL 输出（stderr + json）；argparse **零新增** |
| `_support/workflow_causes.py` | 词表新增 `"mechanism_undeclared": True` / `"mechanism_paths_invalid": True`；**模块 docstring 定义同步改**：「实现侧需改代码才能过」→「需实现侧动作（改码 / 改文档 / 履行申报义务）才能过」（首轮 Major-1：不修定义则模块加载即语义自相矛盾） |
| `shared/single-source.md` | §1 L22 机器面列 + §59 登记行（升格兑现记——**如实写设计变更兑现非数据兑现** + 实验引用）+ §60 纪律④ 措辞 |
| `shared/gates.md` | 门册新行（机制文档触及申报门，owner = cmd_verify 判决函数）+ 变异证明双钉（摘判决调用 ⇒ 红；摘 `.atlas/` 过滤 ⇒ Blocker-1 场景红） |
| `tests/test_atlas_workflow.py` | 判决族测试（§2.1 表全格 + 文法全形 + 词表逆紧形态 + `.atlas` 过滤 + run 子卡落点 + dry-run + `--json` 形态 + cause/charged/退出码断言 + 申报死行 WARN） |
| `proposals/RFC-20261103-04-installer-golden/*.json` | 装配覆盖面变更 ⇒ worktree 对已提交树重录 |
| `docs/map/cli.md` | **L19 行文本语义重写**（触及提示 → 申报门；锚点门只验锚与计数不验语义，文本不改则语义漂移静默存活——首轮 Major-4①）+ 行号锚随代码移（`--fix`）+ 数字快照实收对账 |
| `RFC-20261122-04` §6 交付文本 | 采纳仓手写区补「升格注记」一段（upgrade 推不到手写区，须显式交付升级文本——首轮 Major-4②） |
| `CHANGELOG.md` | `[Unreleased]` 条目 |

版本串不动（不发版，随下次发版窗口）。

## 5 变异证明（门册纪律，双钉）

1. 摘掉判决函数调用 ⇒ 判决族测试红；
2. 摘掉 `.atlas/` 过滤 ⇒ Blocker-1 场景测试红（申报文件入暂存触发触及）。
报告含注入 diff（`scripts/mutation_proof.py` 口径）。

## 6 不做（边界）

- 不动 `product/` vs `docs/` 边界、不做采纳仓篇目搬家（v3/playground 侧另批事件）。
- 不造申报文件 validator（2.2 文法是判决自身的解析契约，十几行，非 validator 面）；不做「代码 mtime vs 篇 mtime」机械比对判据（申报制已给豁免阀；机械比对会盲拦散文合法不跟改的场景，恰是本门要避免的冤枉态）。
- 不新增 CLI 参数、不动卡 schema、不动 install 模板结构（申报文件是运行态约定，契约文本落 single-source §1/§4）。
- 不做「WARN+FAIL 双轨并存」（触及一族两语义必漂，见 D3）；`--resolves` 通道不并轨（轮次作用域 findings 处置 vs 卡作用域常设申报，生命周期不同——首轮评审立场采纳）。

## 7 拍板点（首轮评审后状态）

- **D1** 申报落点 = 卡目录 `mech-declares.md` ✅（评审认可：正确薄度）
- **D2** cause 双成员 `mechanism_undeclared` / `mechanism_paths_invalid` 均 `charged=True` + **词表 docstring 定义同步改** ✅（首轮 Major-1 荐案采纳；拒绝 uncharged+rc2 备选——门感弱化）
- **D3** 触及提示 WARN 全量退役由判决面取代 ✅
- **D4** `updated` 隐式——篇 ∈ 暂存即 PASS，不设第二词 ✅
- **D5** 判决位次 = 前置判定带 ✅（评审立场：前置红因也是唯一红因，省 ~356k/轮）
- **D6**（首轮新增）坏 glob 判决位升格 FAIL（cause `mechanism_paths_invalid`）✅（Major-3 荐案采纳）

## 8 评审焦点（预派七问 → 评审立场回执）

1. **申报裸奔**：fail-closed 方向对但判据曾缺失 ⇒ §2.2 文法写死 + FAIL 文案可复制申报行（杀手简化）。
2. **信任申报残余**：显式接受 + 补登记「整卡有效非轮次有效」（§2.1）。
3. **ad-hoc unit mkdir**：自洽（`parents=True` 与 `record_attempt` 同款）。
4. **前置位次**：评审支持前置（该轮审查未启动，无双红因叙事问题）。
5. **charged**：保 charged=True + rc1 + 定义修 + 模板文案（Major-1 荐案）；预算数学（缺省 2：忘申报 1 + 真红 1 = 触墙要人工）登记为已知行为非缺陷。
6. **多篇对账**：只 FAIL 未申报篇、可行动 ✅；FAIL 无 CAP 全列（Minor-1）。
7. **形态分裂**：可接受（生命周期不同，FAIL 文案承担教学义务）。

## 9 首轮评审轮记（2026-11-23，tech-proposal-reviewer）

总判**修后通过**：2 Blocker（裸 `**` × `.atlas` 暂存面 = 永久卡死/永久豁免；判决文法未定义）+ 4 Major（charged 语义与词表定义冲突；run 子卡申报落点漂移；坏 glob 篇逃逸判决激励倒挂；docs/map cli.md L19 语义行 / RFC-04 §6 升级注记 / §59 升格兑现措辞三处文档语义漏项）+ 5 Minor（FAIL 无 CAP / discovery 双跑 / dry-run 与 --json 契约 / 申报死行 / 判决表死行格说明）。全部采纳，落点见 §2/§3/§4/§7 对应标注；评审「落地可行性与可逆性」结论：判决是纯前置读判无状态迁移，可逆（回滚 = 删判决块恢复 WARN 分支）。
