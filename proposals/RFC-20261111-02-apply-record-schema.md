# RFC-20261111-02：apply 记录 schema（#52 / #54 / #55）

- 日期：2026-11-11
- 状态：**只定 schema，不实现**（本文件不含任何代码改动）
- 基线：`e534145`（v0.2.0-beta.33）
- 覆盖 issue：#52（需求卡空壳放行）、#54（验收资产缺失判空骨架、用例第二落点）、#55（apply 记录与上游版本无绑定）
- 前置结论：**写入方不存在时，本 RFC 不设任何门**。理由见 §2。
- 非目标：不改 `apply/reference.md`（本轮）、不改 `atlas-apply.md` 的固定七小节、不改 Trellis 任务卡模板、不实现 `atlas apply seal`、不实现校验器。

## 0. 摘要

1. **载体**：新增 `.trellis/tasks/<ID>/atlas-apply.seal.json`（机器侧封条），`atlas-apply.md` 保持人手写散文与固定七小节不变。封条不是第八小节。
2. **信任原则**：任何「版本 / 种类 / 写入方」标记都**不授予信任，只切换义务集**。每条义务都由校验器用**当前文件字节**复算；声明写得再漂亮，复算不过就 FAIL。
3. **旧记录识别**：无封条 = `absent`（迁移期 WARN + 计数，cutover 后 FAIL）；`kind=legacy` = 显式登记，带 owner + due，到期 FAIL；不自动续期。
4. **缺字段判定**：不跳过、不降级成「未知格式放行」；未知 `schema_version` 一律 FAIL（提示升级 Atlas），宁可红也不静默。
5. **前置**：seal 的唯一合法写入方是 `atlas apply seal`（本轮不实现）。在它存在之前，本设计无法落地，也不应该落地。

## 1. 三个 issue 的现状（为什么需要 schema）

| issue | 现状 | 机器侧缺什么 |
|---|---|---|
| #52 | `apply` 收尾由 skill 手写 `atlas-apply.md`；校验器只看 PRD，不读任务卡 | 没有「本条需求挂哪些 AC」的机器可读声明，也没有「卡自 apply 后是否被改过」的绑定 |
| #54 | `validate_e2e_index` 在方案层无索引无分片时判 N/A；用例可落进任务目录 | 没有「本次验收资产是 ready / not_ready / n/a」的显式声明，空骨架与真就绪同形 |
| #55 | `atlas-apply.md` 无上游 PRD 的版本 / 摘要 | 没有「记录基于哪一版上游」的绑定，上游改版后记录陈旧但 `check` 无感 |

共同点：三者都不是「少一条判据」，而是**记录本身没有字段可判**。先定字段，再谈判据。

另：全仓 `apply_version` **零命中**（代码 / 模板 / 脚本 / 文档），说明「新格式」目前没有任何写入方与消费方。任何「只对新记录生效」的写法都会让漏写的新记录永久落进豁免——与要治的「静默 applied」同构，故本 RFC 不采用。

## 2. 信任边界：机器凭什么相信一条记录是新格式

**结论：在没有机器写入方的前提下，机器不能相信。**

`apply_version` / `schema_version` / `written_by` / `written_at` 都是记录自己的声明，手写即可伪造。因此本 RFC 的判据**不以「标记存在」为信任来源**，只承认两类事实：

1. **可复算的字节**：`sha256(当前文件)`。校验器自己算，记录只提供「应该等于什么」。
2. **可复算的派生量**：AC 是否在 PRD 定义行里、用例 ID 是否在索引里、路径是否在任务目录外——都由校验器从当前文件重算。

由此得到三条硬规则：

- **标记只切换义务集**。写 `kind=apply` 就必须交出任务卡 / PRD / 索引 / 用例的摘要，少一项就 FAIL；写 `kind=legacy` 就必须交出 owner + due，到期就 FAIL。声明什么并不能换来豁免，只能换来「要证明什么」。
- **未知 ≠ 放行**。`schema_version` 不认识、封条存在但不可解析、`e2e` 段的 `status`（草案提案字段，待 RFC 批准）不在枚举里——全部 FAIL，附「升级 Atlas」指引。绝不允许「新格式看不懂 ⇒ 跳过」。
- **缺席 ≠ 豁免**。cutover 后无封条即 FAIL；不允许删除封条退回 WARN（见 §6.3 的迁移期旁路说明）。

**本设计能证明什么、不能证明什么**（写进契约，不靠注释）：

| 能证明 | 不能证明 |
|---|---|
| 记录声明与**当前字节**一致（陈旧 / 脱节可判） | `apply` 真的跑过（可伪造一份摘要正确的封条） |
| 记录覆盖了任务卡、PRD、索引、用例这些**具体工件** | agent 真的读过 PRD、真的按影响面落笔 |
| 缺口被**显式登记**（reason / owner / due），而不是沉默 | 登记的理由是否成立（语义，归人审） |

所以本门的诚实定位是**治陈旧与脱节，不治造假**。造假仍靠 `atlas-apply.md` 的散文留痕与人审（`validate_walkthrough` 已承担其中一问）。若要把「造假」也关进机器面，唯一路径是让工具**自己产生资产改动**再据此签发封条——那是执行器课题，不在本 RFC。

## 3. 载体：为什么是独立封条文件，而不是改 `atlas-apply.md`

- `atlas-apply.md` 是**人写散文**，当前契约规定固定七小节（[`apply/reference.md:264-270`](../apply/reference.md#L264-L270)），并由 [`docs/map/apply.md:61`](../docs/map/apply.md#L61) 对外承诺。往里塞机器字段要么变成第八小节（破坏承诺），要么靠正则从散文里抠（脆，且重蹈 `_ac_defs` 式解析脆弱）。
- 封条是 JSON：可严格校验、可复算摘要、坏形态能响亮报错。
- 两者关系：`atlas-apply.md` 仍是对人、对复核者的主记录；封条是**紧邻的机器附录**，只服务校验器。封条缺失不影响人读记录的存在性。

落点：`.trellis/tasks/<ID>/atlas-apply.seal.json`（任务目录内，随 git 提交；不进 `.atlas-runs/` 之类的运行态目录，因为它是可复核的声明而非临时产物）。

## 4. 字段集

```json
{
  "schema_version": 1,
  "kind": "apply",
  "task": {
    "id": "12-add-login",
    "card": { "path": ".trellis/tasks/12-add-login/prd.md", "sha256": "<64 hex>" }
  },
  "acs": {
    "source": "product/prd/auth-prd.md",
    "definition_sha256": "<64 hex>",
    "referenced": ["AC-AUTH-001", "AC-AUTH-003"]
  },
  "e2e": {
    "status": "ready",
    "index_sha256": "<64 hex>",
    "case_ids": ["AUTH-LOGIN-001"]
  },
  "upstream": [
    { "role": "prd-global",  "path": "product/prd/prd.md", "sha256": "<64 hex>", "version": null },
    { "role": "prd-domain",  "path": "product/prd/auth-prd.md", "sha256": "<64 hex>", "version": "v3" },
    { "role": "e2e-index",   "path": "product/e2e/e2e-index.md", "sha256": "<64 hex>", "version": null }
  ],
  "written_by": "atlas apply seal",
  "command_version": "0.3.0",
  "written_at": "2026-11-11T10:20:31+08:00"
}
```

### 4.1 字段表

| 字段 | 类型 | 必需 | 含义 | 消费方怎么判 |
|---|---|---|---|---|
| `schema_version` | int | 是 | 当前唯一合法值 `1` | 缺失 / 非整数 / 未知 ⇒ **FAIL**（「未知版本，请升级 Atlas」，不跳过） |
| `kind` | enum | 是 | `apply` / `backfill` / `legacy` | 越界 / 缺失 ⇒ FAIL；各值的义务见 §5 |
| `task.id` | str | `kind≠legacy` | 必须等于任务目录名 | 不等 ⇒ FAIL |
| `task.card.path` | str | `kind≠legacy` | 相对项目根 | 不在本任务目录内 / 含 `..` ⇒ FAIL |
| `task.card.sha256` | str(64 hex) | `kind≠legacy` | 任务卡字节摘要 | 与当前字节不符 ⇒ FAIL「记录陈旧：任务卡已变更」 |
| `acs.source` | str | `kind≠legacy` | 方案 PRD 路径 | 文件不存在 ⇒ FAIL |
| `acs.definition_sha256` | str | `kind≠legacy` | PRD 字节摘要 | 不符 ⇒ FAIL |
| `acs.referenced` | str[] | `kind≠legacy` | 本需求挂的 AC | 为空且无 `acs.exempt` ⇒ FAIL；任一项不在 PRD 定义行 ⇒ FAIL |
| `acs.exempt` | obj | 否 | `{reason, owner, due}`，显式声明本条不挂 AC | 与 `referenced` 同时非空 ⇒ FAIL（二义）；三字段缺一 ⇒ FAIL；`due` 过期 ⇒ FAIL |
| `e2e` 段的 `status`（草案提案字段，待 RFC 批准） | enum | `kind≠legacy` | `ready` / `not_ready` / `n/a` | 缺失 / 越界 ⇒ FAIL |
| `e2e.index_sha256` | str | `status=ready` | 索引字节摘要 | 缺失 / 不符 ⇒ FAIL |
| `e2e` 段的 `case_ids`（草案提案字段，待 RFC 批准） | str[] | `status=ready` | 本需求新增 / 改动的用例 ID | 为空 ⇒ FAIL；任一 ID 不在索引 ⇒ FAIL |
| `e2e` 段的 `gap`（草案提案字段，待 RFC 批准） | obj | `status≠ready` | `{reason, owner, due}` | 缺任一 ⇒ FAIL；`due` 过期 ⇒ FAIL |
| `upstream` | obj[] | `kind≠legacy`，≥1 | 上游绑定 | 空数组 ⇒ FAIL |
| `upstream[].role` | enum | 是 | `prd-global` / `prd-domain` / `e2e-index` / `stack-profile` / `structure-facts` | 越界 ⇒ FAIL |
| `upstream[].path` | str | 是 | 相对项目根 | 不存在 ⇒ FAIL「上游已删除」 |
| `upstream[].sha256` | str | 是 | 字节摘要 | 不符 ⇒ FAIL「上游已改版，apply 记录陈旧」 |
| `upstream[].version` | str \| null | 否 | 人读版本号 | **不参与判定**（可伪造，不得当值域门） |
| `legacy_owner` | str | `kind=legacy` | 谁认领这条旧记录 | 缺失 ⇒ FAIL |
| `legacy_due` | date | `kind=legacy` | 必须迁出的截止日 | 缺失 / 过期 ⇒ FAIL；不接受空值或「长期」 |
| `written_by` | str | 是 | 写入方标识 | **不参与信任判定**；不在已知写入方集合 ⇒ WARN（提示可能手改），不据此 FAIL |
| `command_version` | str | 是 | 签发时的 Atlas 版本 | 仅排障；缺失 ⇒ WARN |
| `written_at` | ISO8601 | 是 | 签发时间 | 仅排障；缺失 / 非法 ⇒ WARN |

摘要算法统一 `sha256`，小写 hex，对**原始字节**计算（不做换行归一、不 trim）。

## 5. 谁写、谁读、谁批准

| 角色 | 动作 | 约束 |
|---|---|---|
| `atlas apply seal`（新命令，本轮不实现） | 唯一合法签发方；apply 收尾调用 | 摘要由工具**自己从文件算**，不接受命令行传入；自身前置不过（卡空壳、AC 悬空、`ready` 但索引 / 用例缺失、上游路径不存在）⇒ **拒绝签发**并 exit 1 |
| `atlas apply seal --backfill` | 迁移期一次性补登 | 签发 `kind=backfill` + `owner` + `due`；语义 = 「按当前资产绑定，但未经本次 apply」；到期 FAIL |
| `atlas apply adopt-legacy` | 人工登记无法绑定上游的旧任务 | 只写 `kind=legacy` + owner + due；已存在封条时拒绝，除非显式 `--renew` 并附评审编号（续期次数要在报告里可见） |
| `validate_apply_record`（新校验器，本轮不实现） | 只读判定 | 不写任何文件；不自动修复；不自动续期 |
| `validate_walkthrough` | 保持现状 | 仍只读 `atlas-apply.md` 的三问小节，不读封条 |

**重要**：`written_by` 可被手写伪造，所以「看起来是工具写的」不构成任何信任。工具写入的价值不在字段，而在于**它会因为自身前置不过而拒绝签发**——这是把约束放在写入侧，而不是放在记录里自称。

## 6. 旧记录识别与 cutover

### 6.1 三态

| 观测 | 判定 |
|---|---|
| 有封条，可解析，`kind=apply` / `backfill`，字段齐且复算一致 | `current` / `backfilled`，PASS |
| 有封条，`kind=legacy`，owner + due 未过期 | PASS（带「legacy 至 <due>」提示） |
| 有封条但不可解析 / 版本未知 / 字段缺失 / 复算不符 | **FAIL**（存在即必须有效） |
| 无封条，但有 `atlas-apply.md` | `absent`：迁移期 WARN + 计数；cutover 后 **FAIL** |
| 无封条，也无 `atlas-apply.md` | 不属本门（无 apply 记录），沿用既有语义 |
| 任务已归档（`status=completed`） | 不扫（与 `validate_walkthrough` 同时空域） |

### 6.2 cutover

- 硬编码版本 `0.3.0`；若 `0.3.0` 未发布，最迟 `2026-12-31`，二者先到为准。
- cutover 后 `absent` ⇒ FAIL，不再有迁移期 WARN。
- cutover 版本与日期写进 `shared/gates.md` 该门行与 `changelog`，不只靠 release note。

### 6.3 迁移期的已知旁路（如实写）

迁移期内 `absent` 只 WARN，因此「删掉封条」可以把 FAIL 降回 WARN。本设计**不假装能防住**：封条是可复核声明，不是外部账本；没有第二份账就判不出「曾经有过封条」。可用缓解：封条随 git 提交，删除会留在 `git log` 里，属评审可见；cutover 后旁路自动消失（缺席也是 FAIL）。若要求迁移期也堵死，需要外部账本（另一套 schema），本 RFC 不做。

## 7. 缺字段 / 坏形态矩阵（唯一判定表）

| # | 坏输入 | 判定 | 依据 |
|---|---|---|---|
| 1 | 封条不存在，cutover 前 | WARN + 计数 | §6.1 `absent` |
| 2 | 封条不存在，cutover 后 | FAIL | 缺席不是豁免 |
| 3 | JSON 不可解析 | FAIL | 存在即必须有效 |
| 4 | `schema_version` 缺失 / 未知 / 大于当前 | FAIL（提示升级 Atlas） | 未知不放行 |
| 5 | `kind` 缺失 / 越界 | FAIL | 义务集无法确定 |
| 6 | `kind=apply` 但缺 `task` / `acs` / `e2e` / `upstream` 任一 | FAIL | 义务集未履行 |
| 7 | `acs.referenced=[]` 且无 `acs.exempt` | FAIL | 空壳不得静默通过（#52） |
| 8 | `acs.referenced` 与 `acs.exempt` 同时存在 | FAIL | 二义 |
| 9 | `referenced` 中某 AC 不在 PRD 定义行 | FAIL | 与 #50 同源，但此处查的是记录声明 |
| 10 | `e2e.status=ready` 但缺 `index_sha256` / `case_ids` | FAIL | 不得用 N/A 空骨架冒充就绪（#54） |
| 11 | `e2e.status=ready` 但索引 / 用例摘要不符或 ID 不在索引 | FAIL | 就绪必须可复算 |
| 12 | `e2e.status∈{not_ready,n/a}` 且 `gap` 缺 reason / owner / due | FAIL | 缺口必须显式 |
| 13 | `e2e` 段 `gap` 的 `due`（草案提案字段） / `acs.exempt.due` / `legacy_due` 过期 | FAIL | 临时态不得永久 |
| 14 | `kind=legacy` 且带 `task` / `acs` / `e2e` / `upstream` 块 | FAIL | 二义 |
| 15 | `kind∈{apply,backfill}` 且带 `legacy_owner` / `legacy_due` | FAIL | 二义 |
| 16 | `upstream[].path` 不存在 | FAIL（上游已删除） | #55 |
| 17 | `upstream[].sha256` 不符 | FAIL（上游已改版） | #55 |
| 18 | `written_by` 未知 | WARN | 可能是手改；不作为 FAIL 依据（可伪造） |
| 19 | `command_version` / `written_at` 缺失 | WARN | 仅排障 |

## 8. 三个 issue 的字段落点

### 8.1 #52 需求卡空壳

- **机器能做的**：`task.card.sha256` 绑定卡字节；`acs.referenced` 必须非空，或显式 `acs.exempt{reason,owner,due}`。
- 效果：空壳卡不会「因为校验器只读 PRD」而静默放行——它要么给出 AC 指针，要么留下一份带 owner 与截止日的豁免。
- **显式盲区**：卡里写了字但内容是废话，机器判不了（语义归人审）。
- 为什么不是「检测 TBD 字样」：字样检测是形态游戏，换个词就绕过；显式豁免把「没有 AC」变成一条可审计声明，比黑名单更硬。

### 8.2 #55 上游版本绑定

- **机器能做的**：`upstream[]` 强制 ≥1 条（至少 `prd-domain` 或 `prd-global`），每条给 `sha256`；校验器复算。
- `version` 字段只作人读，**不进判据**——上游 PRD 的 `version` 是否递增本身没有机器可验证的语义。
- 「绑定」的含义要写清：绑定的是**字节**，不是「版本号更大」。上游改一个错别字也会让封条陈旧——这是有意的保守：宁可要求重新签发，也不让记录悄悄过期。

### 8.3 #54 验收资产缺失 / 用例第二落点

- **机器能做的（记录侧）**：`e2e` 段的 `status`（草案提案字段，待 RFC 批准）三态必填；`ready` 必须交索引摘要与用例 ID；其余两态必须交 `{reason,owner,due}`。
- **机器能做的（不受封条影响，独立判据）**：用例文件若落在 `.trellis/tasks/<ID>/` 下（按用例 ID 文法匹配），判 **FAIL「用例第二落点」**。这条不依赖封条，属既有资产布局判据的补强，落 `validate_e2e_index` 或新校验器需拍板（见 §12）。
- 父仓 `atlas solution check --strict` **不读成员 `.trellis/tasks/`**（Phase 1 只读聚合的边界），所以 #54 的这条门只能在**成员仓**的项目级 `atlas check` 里生效。

## 9. 可见性（如实写）

- **本门唯一真实入口**：项目级 `atlas check` / `python3 .atlas/scripts/atlas_check.py`（[`scripts/atlas_check.py:53-64`](../scripts/atlas_check.py#L53-L64) 的 `VALIDATORS`）。
- **采纳仓是否可见**：取决于该仓 CI 是否跑 `atlas check`；`RUNBOOK.md` 写了这个命令，但没有强制。**不跑 = 没有门。**
- **`atlas solution check --strict` 看不到本门**：它判的是方案清单 / 锁 / 成员状态，不读成员任务目录。
- **Atlas 本仓 CI 看不到本门**：`.github/workflows/tests.yml` 只跑两个 pytest 文件；最多加一条 CLI 级回归，不能声称「本仓 CI 已在跑这道门」。
- 结论：本 RFC 若实现，必须同时给出「采纳仓怎么跑」的最小样例，否则又是一道纸门。

## 10. 落点改动面（实现时同批）

| 文件 | 改动 |
|---|---|
| `apply/reference.md` §8（`:258-277`） | 追加一段：封条是机器附录、非第八小节、由 `atlas apply seal` 签发；**行数从 331 起变化** |
| `docs/map/apply.md:16`、`:97` | 「`apply/reference.md`(331 行)」→ 实测新行数（两处） |
| `docs/map/apply.md:61` | 「固定七小节」**保持不变**（封条不是小节） |
| `shared/layout.md:59` | 任务目录说明补 `atlas-apply.seal.json` |
| `shared/gates.md` | 新增一行门登记（对账平面 = 记录 ⇔ 当前字节；盲区 = 造假 / 语义；预算 = apply 收口后首次 `atlas check`；取证等级按实测填）；测试计数按实测回填 |
| `scripts/atlas_check.py` | `VALIDATORS` 增加 `validate_apply_record`；三态前置：无 `.trellis/tasks` ⇒ SKIP + 原因 |
| `validators/validate_apply_record.py` | 新校验器（只读） |
| `skills/atlas-apply/SKILL.md` | 收尾显式调用 `atlas apply seal` |
| `patches/workflow-plan-apply/1.6-plan-apply.insert.md` | §1.6 步骤补「签发封条」；片段正文变更 ⇒ 块指纹变化，采纳仓重跑 install 时整块替换（预期） |
| `bin/atlas.js` `case 'apply'`（`:434-450`） | help 列出 `apply seal` / `seal --backfill` / `adopt-legacy` |
| `docs/guide/changelog.md` | **当前无 `[Unreleased]` 段，需先建**，再写条目 |
| `docs/map/cli.md` / `docs/map/gates.md` | 命令与门行同步；跑 `node docs/map/atlas-map.check.js` 复验锚与计数 |
| `tests/test_apply_record.py`（新） | §11 全部样本 |
| `tests/test_gate_registry.py` | 门登记表形态钉（6 格 / 无空格格 / 行数上限） |
| `tests/test_cli_commands.py` | `apply seal` help 可见 + 一条 CLI 级回归 |

## 11. 反面包（坏记录样本 → 期望判定）

每条都写明**为什么被目标判据接住**，而不是被别的检查先拦下。

| 编号 | 坏输入 | 期望 | 为什么是它接住 |
|---|---|---|---|
| S1 | `kind=apply`，摘要齐全，随后 PRD 被编辑 | FAIL 陈旧 | 其余字段合法；唯一不变量是 `definition_sha256` 复算不符 |
| S2 | `kind=apply`，`acs.referenced=[]`，无 exempt | FAIL | 卡与 PRD 都可解析，不触发任何解析错误；命中「空壳」义务 |
| S3 | `kind=apply`，`referenced` 含 PRD 中不存在的 AC | FAIL | 与 #50 不同：此处不判清单，只判记录声明与 PRD 定义行集合 |
| S4 | `kind=apply`，`e2e.status=ready`，索引文件缺失 | FAIL | 不落入 `validate_e2e_index` 的 N/A 分支——本门先要求 `ready` 有摘要 |
| S5 | 用例文件写在 `.trellis/tasks/<ID>/` 下 | FAIL 第二落点 | 独立判据，不依赖封条；封条齐全也会红 |
| S6 | `kind=legacy`，`legacy_due` 已过 | FAIL | 不是 SKIP；到期即失效，不接受「长期」 |
| S7 | `kind=legacy` 同时带 `upstream` 块 | FAIL 二义 | 义务集冲突，先判形态再谈内容 |
| S8 | `schema_version=2` | FAIL（提示升级） | 不被当成未知格式跳过——这正是评审要堵的「新记录落入 SKIP」 |
| S9 | cutover 后，先前有效的封条被删除 | FAIL | 缺席 = FAIL，与 S8 同族：未知与缺席都不放行 |
| S10 | `upstream` 里的 PRD 被删除 | FAIL 上游已删除 | 路径存在性先于摘要；消息必须区分「删除」与「改版」 |
| S11 | `e2e.status=n/a`，`gap` 缺 owner | FAIL | 缺口三字段是义务，不因 `n/a` 免除 |
| S12 | 手写封条（`written_by` 写 `atlas apply seal`）但字段齐全且摘要正确 | **PASS**（仅 WARN 若 `written_by` 未知） | 如实承认：字段正确就无法分辨来源；本门不治造假（§2） |

回归钉（防误伤）：

- R1：现有 `atlas-apply.md` 固定七小节不被改写；`validate_walkthrough` 行为不变。
- R2：任务 `status=completed` 不扫；无 `atlas-apply.md` 且无封条的任务不产行。
- R3：`atlas check --fast` 只多一行，既有行的级别不变。
- R4：封条缺失在 cutover 前的 WARN 必须带数量与样例路径，不得只报一句「有缺失」。

## 12. 存量影响与迁移路径

- **迁移期（cutover 前）**：所有活跃任务 `absent` ⇒ 每个任务一条 WARN。噪声量与活跃任务数成正比，必须给汇总计数（一条门行 + N 条样例），不能刷屏。
- **迁移路径 A（推荐）**：实现 `atlas apply seal --backfill`，对活跃任务签发 `kind=backfill` + owner + due。它绑定当前字节，从此开始的改版可判陈旧。
- **迁移路径 B**：无法确定上游 PRD（方案 PRD 尚未写 / 路径不匹配）的任务，`adopt-legacy` 登记 `kind=legacy` + owner + due，到期前补 PRD 再转正。
- **不做**：自动为存量任务生成 `kind=apply` 封条——那会把「没跑过 apply」写成「跑过」，比没有封条更坏。
- **cutover 后**：`absent` 与过期 `legacy` / `backfill` 都 FAIL；迁移只能靠补 PRD + 重新签发。

## 13. D156

#52 / #54 / #55 本轮**不实现**，因此不进入三态记账（不写「闭族」「未闭族」「单案修复（无留出集）」）。`bugs.md` 三条保持 `开放`，正文不动。等实现并取到留出证据后，再按三态口径记账。

## 14. 本 RFC 不做什么

- 不实现 `atlas apply seal` / `adopt-legacy` / `validate_apply_record`。
- 不改 `apply/reference.md`（所以 331 行锚、`docs/map/apply.md` 两处引用本轮均不动）。
- 不改 `atlas-apply.md` 固定七小节，不改 Trellis 任务卡模板。
- 不引入 `apply_version` 之类的版本标记作为信任来源。
- 不把 `upstream[].version` 当判据；不自动续期 `legacy_due`。
- 不声称本门能防「伪造封条」。

## 15. 仍需拍板

1. **载体**：独立 `atlas-apply.seal.json`（不改七小节）——是否确认？
2. **`kind` 三值**（`apply` / `backfill` / `legacy`）与各自义务集——是否接受？特别是 `backfill` 是否保留，还是只留 `legacy`？
3. **cutover 硬指标**：版本 `0.3.0`、最迟 `2026-12-31`、二者先到为准——照此写死？
4. **摘要范围**：任务卡 + 方案 PRD + 索引 + 用例 + `upstream[]`。`structure-facts` / `stack-profile` 是否纳入？纳入会显著提高陈旧率（结构事实随实现变动）。
5. **门的位置**：放项目级 `atlas check`（`VALIDATORS`），并承认「采纳仓不跑就没有门」；还是同时要求在成员 CI 模板里加一条？后者要改装配产物，属另一批。
6. **#54 第二落点判据**：并入 `validate_e2e_index`，还是由新校验器 `validate_apply_record` 一并判？前者更贴对账平面，后者少一道门行。
7. **前置顺序**：先实现写入方（`seal` / `--backfill` / `adopt-legacy`）+ 只输出 inventory 的 WARN，再开 cutover FAIL——还是要求写入方与门同批上线？
8. **#52 空壳口径**：接受「显式豁免（reason/owner/due）」而非语义/关键字检测——是否确认？
9. **迁移期旁路**：接受「删封条可退回 WARN，靠 git 历史与评审可见」这一如实披露，还是要求另立外部账本（超出本 RFC 范围）？
