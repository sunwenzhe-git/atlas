# RFC-20261111-03：验收资产契约（#51 / #52 / #53 / #54 / #55 / #59）

- 日期：2026-11-11
- 状态：**v45（终局冻结修订；行数 `2518`；基线提交 `411c971`；2026-11-12）**
- 冻结约定：**自 v39 起，只有 C 批（封条写侧、续签链、`seal reanchor`、E2E 封条、记录绑定）与 B 批的实现反馈可改本文件**；规则层新增争议一律进 C 批；**B-0 期间不再改本文档**。
- 基线：`411c971`（A 批已提交；`9cdb1a1` 为 A 批前基线，`package.json` = `0.2.0-beta.33`）
- 覆盖：GitHub `sunwenzhe-git/atlas` 六个同域 issue
- 关系：取代 `RFC-20261111-02` 作为六条的域级设计；`RFC-20261111-01` 的 #50 结论继续有效

> v23 修第二十二轮 **1 阻断**（`exemption_start_signed_at_not_canonical` 的码义在码表 / T-28 / §8 三处互斥：码表把「等值不等」算进本码，T-28(c) 把纯等值不等归 `exemption_start_conflict`）与 5 重要（`exemption_start_history` 的 append-only 只有末项等式、无外部锚，且「origin 堵住延后 due」不成立——真实出口是上界 `first_seen_at + 90d` 而 reanchor 时封条载荷不可读；存量回填被「任何命令不改写」抵消；缺 `origin ≤ started_at`；C 批文件表漏 `seal reanchor` 写入口；S-55 前置引错夹具）与 6 次要。**B-0 面上一轮已判可真闭合、v22 可作 B-0 开工基线；本稿只收口 `exemption_start_*` 规则面，不宣称整份通过。** 本稿仍不碰实现（`_support/`、`scripts/`、`install.py`、`tests/` 一律不动，**唯一例外见 §6 B-0 文件表**）。
>
> **v24 一句话**：**码辖区正交**——`signed_at_not_canonical` 覆盖所有封条 blob（含 `L[0]`），`exemption_start_signed_at_not_canonical` 只管锁里的 `exemption_started_at` 字面值，**形态先于等值、形态失败跳过等值**；**存量锚改成「首个同时含该字段的版本」**（否则两个 `*_rewritten` 是死码），并补 T-30⑤；⑦ 拆成**标量 / 数组 A / 数组 B / 数组 C** 四条判据；**新增 `exemption_due_out_of_range`**（读侧 `due` 越界，续签可修）；S-55 前置改为「S-18 构造 + S-26 后置」，① 降到 2 条历史删首项。
>
> **v25 一句话**：**夹具可构造性收口**——S-55 ① 改为「1 条位移历史整体删除 ⇒ 由 ⑤（`origin == started_at`）红」，前缀单调另立 **T-33 纯函数单测**（三份合成锁文本、不走 git）；**`due` 全在日期层比较**（下界取 `exemption_start_origin` 的 UTC 日期、上界先 `min(first_seen_origin + 90d, acceptance_cutover)` 再截到日期，`acceptance_cutover` 不随缺 `first_seen_origin` 跳过；**该 `min` 口径已被 v26 取代：先截日期再加 90 天**）；`first_seen_origin > L[0].signed_at` 也报 rewritten；T-30③ 删「重排」、补 ⑥；形态失败**跳过整个 conflict 组**。
>
> **v26 一句话**：**`due` 端点与 V-20 对齐**——T-32③ 拆成 ③a（默认支 `2027-03-31`）/ ③b（延展支 `2027-06-29`，挂 `--anchor-review`）/ ③c（`+90d` 支）三条 PASS，`2027-06-30` 只作超限 FAIL；**单一日期归一化**「先截 UTC 日期再加 90 天，全程 `date`」；**纯函数 `check_history_prefix(versions) -> Ok | Err(code, detail)`** 落 §1.1.3，T-33 移入 **B-0**；报告项 `detail` 升为**可选对象**（`downgrades[]` 的人类可读字段改名 `note`）；S-55① 更正为「已重指后删空 ⇒ ⑤ 与单调同红」。（③a 的具体构造已被 v27 取代：改为早于默认的 `cutover = 2027-01-31`，避免 `first_seen_origin` 撞 `signed_at`。）
>
> **v27 一句话**：**端点构造可运行**——③a 改用**早于默认的 `cutover`**（`2027-01-31`，收紧合法、无需 review）并把 `first_seen_origin` 压到 `2026-11-05`，绕开未来 `signed_at`；③b 明写**未来值构造**（首签 `signed_at = first_seen_at = 2027-04-15T00:00:00Z`，不事后 amend）；`check_history_prefix` 补**四种输入边界**（空列 / 单版本 / 缺键 / `seal_anchors` 为 `null` 或非 dict ⇒ `[]`，均不抛异常）并进 B-0 文件表；S-52⑤ 写侧不 trim、S-51 的 `_root_by_index_ok` 分层与 `lexical=True` 零 FS 移入 B-0 夹具；`detail.kind` 记号全文统一。（③a 的 `signed_at` 仍写「运行时 `now`」，已被 v28/I-4 钉死。）
>
> **v28 一句话**：**前缀单调改「紧邻前一版本」**——`某前版本` 是 fail-open（`[] → [x] → []` 假绿），`:721` / `:726` / T-28④ / 码表 / §8 统一收紧；`versions` 补**按 commit SHA 去重**（merge 多父）与**末尾追加工作树当前锁**；无锁历史发 INFO **`lock_history_empty`**（新增 `info[]`，不计 FAIL）；T-32③a/③b 补**清单与锁两侧同写 + 可执行步骤**；③a / ③c 的 `signed_at` **钉死 `2026-11-05T00:00:00Z`**，不再用运行时 `now`。（v29/B-1 已删 `versions` 的「同 SHA 替换」第三条。）
>
> **v29 一句话**：**`versions` 构造收敛成两点**——删掉与②互斥且 fail-open 的 ③「同一 SHA 用工作树内容替换」，只留「SHA 去重（构造层清理、不产生判据）」+「工作树字节与 HEAD 不同则末尾追加，**HEAD 无该文件则不追加**」；`lock_history_empty` 与 `lock_missing` 写死互斥；T-32③a/③b 改为**四步序列**（`migrate` → 首签载荷一次写死 → `lock --update` → 锁独立提交），删掉所有 `--amend`；报告 `schema_version` 升 **2** 并补齐 v1→v2 增量键与 `info[]` 排序。
>
> **v30 一句话**：**删除提交不得伪造空版本**——`versions` 构造补第三点「历史层某版本没有该路径 ⇒ `git cat-file -t <c>:path` 失败即跳过、不记 `[]`」，工作树层补「HEAD 有但工作树被 `rm` ⇒ 不追加」，删锁→改根→重建锁只由 `assets_root_history_rewritten` 报；**`lock_missing` 拆出 `lock_tracked_but_deleted`**（已跟踪的锁被删 ⇒ FAIL/exit 1/`errors[]` 单码短路）；T-32③a/③b 改从 **v1 清单首次 `migrate --to 2 --cutover <v>`** 构造（避开 `migrate` 只补缺导致 ③a 静默退化成 ③c），并写死「须在无封条仓上首签」。**（该 ③a/③b 构造被 v31/B-2 撤销：0.4.0 不注册 `migrate`、在已迁移仓上「v1 首迁移」也不成立；见 §0.30。）**
>
> **v31 一句话**：**退回方案①并把隐含前提写成规则**——T-32③a/③b 基座回到「**已迁移仓**」，第①步 `migrate --cutover` 走 **0.3.x**（唯一注册 `migrate` 的版本）、②–④ 走 0.4.0、全程不碰 `migrate --to`，`--cutover` 的**覆盖语义**写进 §5.2（只覆盖清单字段、不脏定义源 ⇒ 步骤间无需提交）；**B-0 夹具拆两段**——「删锁 → 改根 → 重建 ⇒ `assets_root_history_rewritten`」搬到 C 批 S-48① 且基座必须是 **v2 锁 + 旧根**（B-0 的 v1 锁不贡献根，那里只会 PASS）；`lock_missing` 的**因果写正**（从未跟踪 ⇒ 无历史 ⇒ ⓪-1/⓪-2 空跑通过）；哨兵钉在**第 0 步之后、⓪-0 之前**并补浅仓 / 空仓 / 非 Git 三态；**manifest v2 ⇒ 锁 `schema_version: 2`** 立为写侧规则；`lock_tracked_but_deleted` 限定「仅 HEAD 无锁」并进 `not_run[]` 六段口径。（**v32/B-1 撤销本段的两处写法**：`migrate --cutover` 在已迁移仓上只补缺、与基座不同即 rc=2，造不出端点；「0.3.x / 0.4.0 双二进制」也没有获取两版本的机制。改用 `init --cutover`（单一二进制内的写法，不等于版本无关），见 §0.31。）

> **v32 一句话**：**认两条拍错、把夹具从「造不出的 CLI」退回「今天能跑的纯函数」**——① `--cutover` **不是覆盖语义**：`migrate` 只补缺、清单已有该字段而 `--cutover` 不同 ⇒ 报错（`_support/solution.py:1846-1850`、docstring `:1810`），v31 的覆盖规则删除且**不得为此放宽迁移器**；② 锁的 schema 由清单决定，`LOCK_SCHEMA_VERSION = 2`、`schema_version = 2 if data["version"] == 2 else 1`（`_support/solution.py:37/39`、`:1290-1291`），**v2 清单跑 `lock --update` 出 v2 锁**，B-0 期锁不是 v1。T-32③a/③b 的基座改用**单一二进制里的 `init --cutover <v>`**（③a `2027-01-31`、③b `2027-04-15`；**这不是「版本无关」——不启用第二份二进制，但 `reader_version` 仍决定清单版本，见 v33**），删掉「0.3.x / 0.4.0 双二进制」标签与「步骤间无需提交」；`versions` 构造提成 B-0 纯函数 `build_lock_versions`（CLI 层由 `lock_tracked_but_deleted` 另测）；`detail.kind` 统一成 `cause`；码表补 `⓪` 层三个码的 exit；C 批三条尚不存在的写入口一律标「**C 批实现时补**」。

> **v33 一句话**：**B-0 不动、只把 C 批的构造链改成形式可执行五步**（**v34 更正：「今天真能跑」不成立**——`init --cutover` 在 0.2.x 工具包下第①步即 exit 2，见 §0.33/阻断 1）——T-32③a/③b 前置改「**全新空仓 + 已提交的 PRD**」（`init` 见 `atlas.solution.yaml` 即 `SolutionError`，「已迁移仓」删除），步骤表在签封条与 `lock --update` 之间插入「**提交 PRD 与清单**」（否则定义源脏检查硬拒），并写死「**`init` 首锁的 `acceptance_cutover` 是 `null`，提交后再 `lock --update` 才写入端点值**」；`init --cutover` 在 reader < 0.4.0 下**必须 exit 2 拒绝、不得静默丢弃**（「不启用第二份二进制」≠「版本无关」）；`build_lock_versions.fetch` 与 ⓪-1 共用 `path_at(commit)` 单源探针；`shared/gates.md` 登记两个纯函数测试文件名；码表写明 `manifest_schema_unsupported` 无 JSON 报告；补「删后原样重建 ⇒ `Ok`」规则正文与纯函数夹具；§6 C 闭合度改逐端点一行。**B-0 侧 exit 统一 / V-10 / 两个纯函数 / 七项回退本轮未动。**
>
> **v34 一句话**：**把「形式可执行」与「产品可达」分开写、把 C 批写侧缺口补回 B-0**——① 端点两态：**产品路径**要等 B 批发版后（reader ≥ 0.4.0）才能 `init --cutover`；**测试路径**可预置 `.atlas/VERSION=0.4.0` 起步，但必须标明「夹具前置、不是产品可达路径」，删掉「今天真能跑」；② `acceptance_cutover_review` 的三处写侧（parser 白名单 / `_manifest_text` review 参数 / `lock_payload` 同名键）**纳入 B-0 文件表**，各配夹具（V-23），缺一行 ③b 与 V-20③ 即必红；③ `path_at` 补三洞判序（先 `cat-file -e <commit>`，再 `-t <commit>:<path>`；`tree` / symlink **不得静默当不存在**；浅仓只由对象缺失报 `chain_unverifiable`），并把「两处各写一套即未实现」改成可执行测试（V-24 + `shared/gates.md`）；④ 五步的 ③ 改 `git add -A`（含 `.gitignore`、成员仓初始提交），写明「干净」口径与复验命令；⑤ ④ 的 `seal_anchors` 标注 **C 批**，PASS 不构成 `due` 已评测；⑥ 如实写「删掉第②步，④ 与 `check` 输出不变」的语义空洞。

> **v35 一句话**：**把 review 的三态收敛成两态、把端点断言从「PASS」改成「exit 0 + `errors[]` 空 + 命中切点行」**——① **显式 `--anchor-review` 就落盘，不设 `ignored` 第三态**（早于 / 等于默认同样落盘；与已落地写侧和「显式给了必须落盘或报错」一致，不影响 `acceptance_cutover_unreviewed` 只对晚于默认触发）；② review 形态写死：**写侧坏值 exit 2、读侧坏值 FAIL `acceptance_cutover_review_malformed` / exit 1**（不拿 exit 2 让整份报告消失），补 V-23d；③ V-23 补 **e（已有 review 不同拒覆盖）/ f（v1 下 `--anchor-review` 拒绝）**，§5.2 第 8 条补 v1 同拒；④ **T-32 三条端点不再断言 `overall == PASS`**——实测 `overall = WARN`，改为 exit 0 + `errors[]` 空 + 命中『验收切点：清单与锁一致』；⑤ T-31 落点改 `scripts/atlas_solution.py`，标注「规则已定、实现待 B/O 批补齐」；⑥ 收口两处自引入陈旧句（`lock_payload` 字段、§8 的 `cat-file` 三态）与两处口径（exit 2 两类含 `manifest_*`、`lock_history_unparsable` 的 `non_blob` 外延）。

> **v36 一句话**：**写死两码互斥与端点断言的实际文本**——① `acceptance_cutover_unreviewed`（空 + 晚于默认）与 `acceptance_cutover_review_malformed`（非空坏形态）**先空后形态、同一字段只出一个码**；并标明 `unreviewed` 谓词当前不存在（`_check_acceptance_cutover` 只有 `missing` / `mismatch`），V-20⑥ 现在是假绿，两码必须同批实现；② T-32 断言改 **`checks[]` 的 `check == "验收切点"`**（纯文本模式两个子串 `"验收切点:"` / `"（清单与锁一致）"`，半角冒号），`--json` 不靠 stdout 文本；③ 更正 `migrate` 注册事实：argparse **无条件注册**，0.4.0 的拒绝来自 `load_manifest` 读侧版本门；④ 补早切点 review「仅存档但参与 `review_reused` 去重」、`non_blob` 只报当前侧（两侧各报是两条夹具）、`check --json` 的 v2 形状尚未落地（断言只用 `checks[]`）、T-31 已实现的事实。

> **v37 一句话**：**给 §6 B-0 补一道「完成判据」验收门**——① 五项全绿才算完成（两码同批 + V-20⑥/V-23d；三个纯函数与三个测试文件并登记 `shared/gates.md`；⓪ 层三码；报告 schema v2 出口；既有 B-0 夹具），任一项缺失不得宣告完成；② `internal_error` 作用域写死**仅限 `check` 命令**（其余命令未知异常仍 `[ERROR]` + return 1，无 JSON）；③ 报告 schema v2 补**落地判据**（`schema_version: 2` + 五数组 + 排序键）并定为 **B-0 交付**；④ B-0 文件表逐行标「已落地 / 待实现」，指向实测行号。

> **v38 一句话**：**把完成判据的封闭域补严、把 schema v2 的「五」定义统一**——① 判据第 5 项改为「**文件表所有『待实现』行归零**」（含 `install.py`、P-4 五处、`validate_e2e_index.py` 未落地子项），`install.py` 按实测改为**已落地**（`install.py:222-253`），不再当欠账；② **五数组 = `errors` / `warnings` / `info` / `skipped` / `downgrades`**，排序 `(code, path)`、`downgrades` 按 `(code, scope, path)`，**`not_run[]` 是固定枚举字符串、不参与排序**；③ 去掉「未单列状态一律待实现」的兜底，逐项标状态：`validate_e2e_index.py` 的 `archive` 扫描已落地、其余子项待实现；P-4 的 WARN 项改为 `:2229-2230` 已落地（旧 `:1153` 已过期）。

> **v41 一句话**：**按 v40 冻结约定开 C 批口径修订，补六处规则层空白 + 两处实况校正**——① crosswalk 解析器独立成 `_support/ac_crosswalk.py`（解析 / findings 两类公开入口，D 批交付，C 不 import）；② **卡门只判 `⊆ requirements[].acs`，crosswalk 像整体归 D**；③ 封条 `prd-domain` / `ac-crosswalk` 在 C 批**只按文件存在性做字节绑定、缺席不拒签**；④ 锁内 `requirements_digest` / `waiver_baseline_digest` 补「首次 = 键不存在」、同一序列化器 + golden vector、已写入不得静默改写；⑤ §五-b 契约 AC 最小 schema（六列、`AC-CONTRACT-\d{3}`、`关联AC` 回指 §五）；⑥ 任务卡 Confirmed 证据状态（`verified/assumed/unverified` + 指针，C 批成员侧执行）；并校正 `templates/prd/domain.md` 已是 `prd_schema: 2`、#51 孤儿 AC 明确「只对显式映射对账」。

> **v42 一句话**：**按独立评审收口 v41 的 4 阻断 / 8 重要 / 7 次要**——① 摘要首次判据改为「键不存在**或 `null`**」并写死 `manifest_digest_removed` / `manifest_rollback`（换锁、回滚、升级三路径分开判）；② `crosswalk_findings` 补 `MemberPrdReader` 入参、枚举 `CrosswalkParseError.code`、重复键归 findings；③ `AC-CONTRACT-*` **纳入 `requirements[].acs` 值域**（方案 (a)，E-04 可达）；④ C 批成员 PRD 路径用 `members[].path` + `prd/*-prd.md` glob 全绑，D 批补 `seal_upstream_unbound` 追溯窗；⑤ `waiver_baseline_drift` 移入 C；⑥ Confirmed 降级须 `REVIEW-ID`；⑦ K-17…K-19 改用 K-20…K-22，区间扩到 C-10 / K-22 / E-12；⑧ 文件表、§1.5 编号、历史锚点与 §9 孤儿项一并校正。

## 0. 返工对照

### 0.1 第三轮已拍板决策（不再是开放问题）

| # | 决策 | 落点 |
|---|---|---|
| 1 | legacy 白名单**允许新任务进入**，但必须走 review 门（受控豁免） | §3.1 |
| 2 | **封条归父仓拥有**；成员侧只保留任务卡投影校验；放弃「记录紧邻任务」 | §1.3/§1.4/§3.3 |
| 3 | 新增整数 `prd_version` 与 `prd_schema`，不复用 `version: 0.1.0`；模板改动并入 B 批 | §1.1/§5.2/§6 |
| 4 | 零证据用例按「**至少一个** token 属于结构类」判定 | §1.6 |
| 5 | `.atlas/VERSION` = semver；`.atlas/DIGEST` = 装配摘要；CLI 从 `VERSION` 读 `reader_version` | §5.2 |
| 6 | `2027-06-30` 必须有执行点：到期 WARN→FAIL | §1.5 |
| 7 | 新封条存 `previous_cases[]`（id → 旧 sha） | §3.4/§4.2 |

### 0.2 阻断返工对照

| 编号 | 第三轮结论 | v4 改法 | 详见 | 反面包 |
|---|---|---|---|---|
| R1 | `prd_version` 不存在且批次倒挂 | 模板新增 `prd_version`/`prd_schema` 并入 B 批；B 批夹具用真模板 | §1.1/§6 | D-08/D-25 |
| R2 | 同域副本抬版本仍可洗白 | **删除机器防副本承诺**；#59 降级为「变更可见 + 人工评审 PRD diff」，写进关闭条件与残余风险 | §2.6/§4.1/§8 | D-26/D-31 |
| R3 | `frozen_at` 不可复算；联邦 allowlist 粒度 | `allowlist_frozen_at` 入锁；allowlist 集中父仓一份；新任务进入步骤与 REVIEW-ID 信任边界写死 | §3.1 | S-09…S-12 |
| R4 | 成员封条读不到父仓资产 | 封条落父仓；`upstream[]` 全在父仓可解析；成员只校验卡投影；工作区缺席默认 FAIL（`--lenient` SKIP），卡未跟踪或有封条缺卡 FAIL | §1.3/§3.3 | U-08/E-06 |
| R5 | `changed_case_ids` 无旧哈希 | 新增 `previous_cases[]`；validator 用 Git 旧封条复算；case+link 同改的 reasons 判定 | §3.4/§4.2 | T-12/T-13 |
| R6 | glob 读者至少 9 个 | **约束 `definition.path` 必须在 `<assets_root>/prd/` 下且以 `-prd.md` 结尾**；4 个 glob 免改，5 个硬编码读者入 B 批 | §1.1 | D-13…D-18 |
| R7 | E-02 没有执行点 | 父仓 `check_solution` 执行被引用域证据列；成员 `atlas check` 明确 N/A；未被引用域到期（2027-06-30 止 WARN、07-01 起 FAIL）由成员 `validate_prd` 与父仓双执行 | §1.5/§2.3 | E-06/E-07 |
| R8 | 版本注入源不存在 | `VERSION`/`DIGEST` 拆分与 `install.py:352-364`、`:804` 迁移；0.4.0 对 v1 硬拒，消除 V-02 矛盾 | §5.2/§5.3 | V-02/V-05 |
| R9 | `first_seen_at` 只是工具自律 | 新增 `renewal_seq` + `previous_seal_sha256` + `previous_seal_commit`，validator 从 Git 复算链 | §3.2 | T-14 |

### 0.3 重要项对照

| 编号 | 落点 | 交付物 |
|---|---|---|
| I1 | §1.1 | canonical form + golden vector（含预期 sha256） |
| I2 | §1.1 | 摘要绑 `git cat-file` blob 字节；worktree 只判脏 |
| I3 | §2.6 | `commit` 不可复算：默认 FAIL，仅 `--allow-unverifiable-chain` WARN；写进关闭条件与残余风险 |
| I4 | §2.1 | `waiver_baseline_digest` 首锁后不可变 |
| I5 | §1.3 | `atlas-acceptance:` 跳过 fenced block 与 HTML 注释 |
| I6 | §1.3 | `solution task acceptance --backfill`（二选一，选 CLI） |
| I7 | §2.4 | `e2e` 段内 `status` 子字段的取数路径：父仓唯一写读，成员 N/A |
| I8 | §5.2 | `reader_version` 在 `load_manifest` 内部注入（读 `.atlas/VERSION`，开发树回落 `package.json`）；批次 A 不读 v2 清单、不碰 `definition.path` |
| I9 | §1.6 | 零证据：至少一个结构类 token |
| I10 | §1.5 | 2027-06-30 执行点 |
| I11 | §1.1 | `prd_date` ← 模板 `date`；`prd_schema` 一并映射 |
| I12 | §4.2 | reason→字段对应表 + 多类同改判定 |

### 0.4 第四轮返工对照

> **历史表**：本表记录第四轮当时的口径，**以正文为准**；其中「成员 AC 必须是 crosswalk 像」「卡门判 crosswalk 像」已被 v41/v42 改为「卡门只判 `⊆ requirements[].acs`，crosswalk 像归 D」。


| 编号 | 第四轮结论 | v5 改法 | 详见 | 反面包 |
|---|---|---|---|---|
| P1 | v2 新键被解析器静默丢弃 | B-0 让 `parse_manifest_text` 支持 `definition` 一层嵌套映射，标量白名单加 `acceptance_cutover` / `min_atlas`；未知子键 FAIL 不静默；新增 v2 round-trip 夹具 | §1.1.3、§6 | D-32/D-33 |
| P2 | 续签链可被「删掉重建」重置 | v5：恰好一个 A、零个 D；`first_signed_commit` 等于该 A。**v6 被 P-2 取代**：删 `first_signed_commit`，改绑 `renewal_seq == N` 与 `previous_seal_commit == L[-2]` | §3.2 | S-13/S-17 |
| P3 | 浅克隆下链无三态 | 拆 `chain_unverifiable`（对象本地缺失：v6 默认 FAIL，仅 `--allow-unverifiable-chain` WARN）/ `renewal_chain_broken`（对象在但 sha 不符）/ `seal_missing_at_commit`（该 commit 无封条）；CI 写死 `fetch-depth: 0`；I3 与 R9 同口径 | §3.2、§5.2 | S-14…S-16 |
| P4 | 卡投影在 CI 里不存在 | 成员仓必须跟踪 `.trellis/tasks/*/prd.md` 与 `solution.md`（C 批前置 + `git -C` 判据）；封条存在时 `card_absent` 一律 FAIL；只给本地开发 `--allow-card-absent` | §1.3.6、§3.3、§6 | K-13/K-14 |
| P5 | 0.4.0 硬拒无迁移路径 | 0.3.x 提供 `atlas solution migrate --to 2`；`install.py --update` 在「仓内 v1 + 来包 ≥0.4.0」时**拒绝刷新并打印命令**，不自动改写清单 | §5.2、§6 | V-06…V-08 |

| 重要 | 落点 | 改法 |
|---|---|---|
| 1 R2 无命令承载 | §2.6 | `lock --update` 打印 old→new（path/version/date/sha8）；`check` 每次输出一行 `定义源: …`；「lock 与 PRD 同一个 PR」进关闭条件 |
| 2 I10 缓冲覆盖新域 | §1.5 | 按 `prd_schema` 分层：`2` 立即要求两列；`1` 才有 2027-06-30 缓冲，且缓冲期发 WARN 不发 N/A |
| 3 I8 注入点选错层 | §5.2 | `load_manifest` 内部读 `<root>/.atlas/VERSION`，开发树回落 `package.json`；`reader_version` 不做 CLI 参数 |
| 4 卡 AC 判据用了「或」 | §1.3.2 | 改为「必须 ⊆ 该 `(id, member)` 的 `requirements[].acs`」；成员 AC 必须是 crosswalk 像 |
| 5 `none` 是无约束豁免 | §1.3.2 | 仅当该需求 `acs` 为空才可用；否则必须走需求级豁免行（review + due） |
| 6 R7 与 P4 同源 | §1.5、§3.3 | 「含封条的仓必须严格态」写成判据；默认即严格（v7 修正：`--lenient` 只在有封条时拒绝，锁不再拒绝，§0.6 Q-6） |
| 7 I3 与 R9 严重度矛盾 | §1.1.6、§3.2 | v6 统一为「默认 FAIL；仅 `--allow-unverifiable-chain` WARN」；对象在但字节不符统一 FAIL |

| 次要 | 改法 |
|---|---|
| 日期差一天 | 统一为「`2027-06-30`（含）前 WARN；`2027-07-01` 起 FAIL」 |
| 版本未升的提示 | `lock --update` 拒绝时输出 `请把 front matter prd_version 提到 <当前+1>` |
| prerelease 比较 | §5.2 定义 semver 比较（含 `-beta.N`）；不可解析 ⇒ `reader_version_unknown` |
| `legacy_frozen_at` 改名 | 改 `allowlist_frozen_at`，语义降为「防改字段」 |
| canonical 非 null | `cross_repo_e2e` 非 null 时按对象键升序 + 字段集合固定，给出规则 |

### 0.5 第五轮返工对照

**已拍板（不再作为开放问题）**

| # | 决策 | 落点 |
|---|---|---|
| 1 | 父仓主干**禁止 rebase/squash**；`seal reanchor --review` 仅在旧 A 对象本地不可达时允许重锚并 `seq+1`（v7 修正：工具不做检测，只写残余风险 + 服务端防线，§0.6 Q-3；**v8/I5 再收窄**：rebase / filter-branch 可检测，只有「squash + 重置封条」不可检测） | §3.2 |
| 2 | `--lenient` 在有封条或锁时**直接拒绝执行**；只允许「尚无封条」的开发早期（v7 修正：只按封条拒绝，锁不再拒绝，§0.6 Q-6） | §3.3 |
| 3 | `card_untracked` 按 `signed_at` 分层：切点前 WARN、重签后 FAIL；B-0 `migrate --check-members` 逐成员打印 `git add -f` 命令（v7 修正：删除宽限，改 C 批硬前置，§0.6 Q-4） | §1.3、§3.3、§5.2 |
| 4 | `--allow-dangling-acs` 退役点 = **0.4.0**（谓词 `semver_lt(version, "0.4.0")`），加「0.3.x 注册、0.4.0 不注册」夹具 | §2.6 |
| 5 | 新域 `prd_schema: 1` 仅当该 PRD 的 A 提交早于 0.4.0 发布点；否则要求 2 | §1.5 |
| 6 | `migrate` **不自动 lock**：migrate 写文件 → 人提交 → `lock --update` → 提交锁 | §5.2 |

**阻断**

| 编号 | 第五轮结论 | v6 改法 | 详见 | 反面包 |
|---|---|---|---|---|
| P-1 | migrate 写出本版拒绝加载的清单 | 版本门 `{1,2}` 提前到 B-0；**锁 schema 由清单决定**：清单 `version: 2` ⇒ `lock --update` 写 `schema_version: 2`（`LOCK_SCHEMA_VERSION = 2`；v32/B-2 更正旧稿的「B-0 期锁为 1」），旧 v1 锁仍可读 | §1.1.3、§5.2 | V-10 |
| P-2 | 只封删+重建，未封原地改写 | 改为 `renewal_seq == len(L)`、`previous_seal_commit == L[-2]`、`seq==1` 时 blob 等于 `L[0]`；删除 `first_signed_commit`；补 squash/merge/add-add/shallow 边界 | §3.2 | S-17…S-20 |
| P-3 | `card_untracked` 无迁移工具无宽限 | `migrate --check-members` + `signed_at` 分层（v7 已删分层） | §3.3、§5.2、§6 | K-17（v5 已删，v7 正式移除） |
| P-4 | `--allow-dangling-acs` 在 0.3.x 不存在 | 谓词改到 0.4.0（`scripts/atlas_solution.py:123-125`），说明 v5 文本与代码的错位 | §2.6 | V-11 |
| P-5 | B-0 窗口：定义源写了没人读 | B-0 只接受 `definition.path == <assets_root>/prd/solution-prd.md`；`definition` 进标量白名单（`definition: null` 不落 `unknown`）；B 再放开任意 `-prd.md` | §1.1.3 | D-35 |

**重要项**

| # | 落点 | 改法 |
|---|---|---|
| 1 矩阵自相矛盾 | §3.3 | 改为「默认（=严格）/ `--lenient`」两列逐行重推；U-08 同步 |
| 2 链 WARN 在默认态不存在 | §3.2 | 窄开关 `--allow-unverifiable-chain`，只管链与 commit，不复用 `--lenient` |
| 3 lenient 的 CI 禁令落到工具 | §3.3 | 有封条/锁 ⇒ 拒绝执行（exit 2），不靠「夹具红」 |
| 4 历史重写死锁 | §3.2 | `seal reanchor --review`；普通 rebase ⇒ `seal_history_reset`，需 reanchor |
| 5 I10 缓冲被复制旧 PRD 继承 | §1.5 | 按 PRD 文件 A 提交判 `prd_schema: 1` |
| 6 migrate 与工作树干净冲突 | §5.2 | 两步；脏检查只作用于 `lock --update` |
| 7 `--to 2` 覆盖人工值 | §5.2 | 只补缺、不改已有；多份 `*-prd.md` 且无 `--definition-path` ⇒ 拒绝并列出候选 |
| 8 卡门与 `ac_missing` 双重红 | §1.3 | 卡门只判「PRD 已定义 AC」的 crosswalk 像；未定义 AC 归 `ac_missing` |
| 9 两处锚点失准 | §1.6 | `validate_e2e_index.py:845` 是整格查语料；`templates/e2e/e2e-index.md:9` 是列头 |

**次要**

B-0 锁 1 → B 升 2 写一句；承认模板 `prd_schema: 1`（B）到 2（D）之间有窗口；D-14 的 init `--definition-path` 不存在 ⇒ 改夹具到 `migrate --definition-path`；`migrate` 幂等 = 缺字段补齐、已有不动；`.atlas/VERSION` 的 prerelease 比较补规则。

**状态**：本稿只完成第五轮返工，不宣称通过；等第六轮评审。

### 0.6 第六轮返工对照（v7）

> **历史表**：口径以正文为准；标「已被取代」的条目不要照旧实现。

**产品决策（本轮按推荐项落笔，文中标注「待拍板」）**

| # | 决策 | 落笔 |
|---|---|---|
| 1 | squash/rebase：只写残余风险 + 采纳仓契约要求（服务端禁 force-push / 线性历史），工具不做检测（**v8/I5 收窄**：仅 squash + 重置封条不可检测，rebase / filter-branch 可检测；**已被 v9 取代**：`D=0` 可 reanchor、`D>0` 判 `seal_history_reset`，见 §3.2「边界」） | §3.2/§8 |
| 2 | `--lenient` 保留，拒绝条件改为「有封条才拒」，不再因锁拒绝 | §3.3 |
| 3 | `card_untracked` 改为 C 批硬前置，删除 `signed_at` 分层与 K-17 | §1.3/§3.3/§6/§7 |
| 4 | 归档任务封条不动，校验时到 `tasks/archive/<month>/` 找卡 | §3.3/§5.2 |
| 5 | reanchor 只允许 fresh clone 执行，**且必须是完整克隆**（v12/重要 7：partial clone 的可达性同样不可判）；不提供破坏性命令 | §3.2 |

**阻断**

| 编号 | 第六轮结论 | v7 改法 | 详见 | 反面包 | 闭合判定 |
|---|---|---|---|---|---|
| Q-1 | 普通 `--no-ff` merge 打断链；`rev-list` 缺 `HEAD` | 过滤判据改为「`git show --format= --name-status <c> -- S` 为空即剔除」，不看父 blob；命令补 `HEAD`；`MM` 冲突 merge「取一侧字节 + 单独一次续签提交」 | §3.2 | S-21/S-22 | 真闭合 |
| Q-2 | reanchor 公式差一，逃生口自证失败 | `base_n` = 不含 reanchor 提交的 `N`，公式 `seq == base_seq + N - base_n - 1`；夹具：reanchor 后立刻 `check` PASS | §3.2 | S-18 | 真闭合 |
| Q-3 | squash 是完整绕过，不是「规则 4 必然失败」 | 删除可判结论；squash/rebase/filter-branch 统一写残余风险 + 服务端防线；补「旧 A 仍在对象库 ⇒ reanchor 不可用，只能 fresh clone」 | §3.2/§8 | —（不造假红夹具） | 名义闭合（工具不可检测，只能如实写）；**v8/I5 已收窄：不可检测的只有「squash + 重置封条」，rebase / filter-branch 归可检测** |
| Q-4 | `signed_at < 0.4.0` 宽限永不成立 | 删除宽限与 K-17；C 批硬前置；`signed_at` 正式定义为工具写入、签发时生成、续签时由工具重写（不可手填），只作 `gap.due` 下界 | §3.2/§3.3/§7 | — | 真闭合 |
| Q-5 | B-0 `migrate` 探测写出自己拒绝的清单 | 落盘前按 B-0 白名单校验目标路径；非默认名 ⇒ 拒绝并打印「B 批后支持任意 `-prd.md`」，不写文件 | §5.2 | V-12 | 真闭合 |
| Q-6 | 「有锁即拒」使 `--lenient` 在 fresh clone 不可用 | 拒绝条件只留「有封条」；只有锁、无封条时 `--lenient` 可用 | §3.3 | U-09 | 真闭合 |

**重要**

| # | 落点 | 改法 |
|---|---|---|
| 1 P-4 五处落点未改 | §2.6/§6/§10 | B-0 文件表加入 `shared/solution.md:73/:84`、`docs/guide/changelog.md:14`、`_support/solution.py:2229-2230`（v40 更正）、`duty-review/QUEUE.md:44`、`duty-review/bugs.md:62`、`tests/test_atlas_solution.py:972-978`；`duty-review/` 只新增 `[Unreleased]` 条、不改旧条，§10 写例外 |
| 2 归档导致 `card_absent` 误红 | §3.3/§5.2 | 卡解析依次找 `.trellis/tasks/<ID>/` → `.trellis/tasks/archive/<month>/<ID>/`；`card_absent` 只判非归档；`migrate --check-members` 覆盖 archive |
| 3 shallow 假绿 | §3.2 | 先 `git rev-parse --is-shallow-repository`；为真一律 `chain_unverifiable`，不进 A/D 分支 |
| 4 窄开关无可见性 | §3.2 | 降级固定打印 `[WARN] chain_unverifiable 已降级（--allow-unverifiable-chain）`，写入机读 `downgrades[]`；CI 禁用 |
| 5 `acceptance_cutover` B-0 冻不住 | §5.1 | 改为 B 批起写入锁 |
| 6 `signed_at` 未定义 | §3.2 | 正式定义：工具写入、签发时生成、续签时由工具重写（不可手填）；只作 `gap.due` 的下界，不参与链复算 |
| 7 #54 判据过窄 | §2.4 | 任务目录 `cases.md` 只要有用例行就报，不看 ID 前缀；0.3.x WARN / 0.4.0 FAIL；覆盖成员任务目录；新增 M-06 |
| 8 `e2e` 段内 `status` 子字段措辞 | §2.4 | 改为「草案提案字段，待 RFC 批准」，不写成已声明字段 |

**次要**

- `L` 为空时先判空，再走 `L[-2]` 规则。
- S-19 按「提交数」断言，不按字母数（merge 的 `AA` 只是一个提交）。
- `definition: null` 经 `_scalar` → `yaml_scalar` 归一为 `None`（`_support/solution.py:102-104`），白名单加入后不会读出字符串 `"null"`。

**状态**：第六轮 6 阻断、8 重要、3 次要均已落进正文；闭合判定见上表（Q-1/Q-2/Q-4/Q-5/Q-6 真闭合；Q-3 名义闭合——工具不可检测，只能如实写残余风险）。v7 不宣称通过，等第七轮评审。

### 0.7 第七轮返工对照（v8）

**阻断**

| 编号 | 第七轮结论 | v8 改法 | 详见 | 反面包 | 闭合判定 |
|---|---|---|---|---|---|
| B1 | reanchor 豁免被写成永久豁免，规则 2/5/8 从此不再检查；可构造「reanchor 一次后篡改 `previous_seal_commit`」假绿 | 豁免收窄到**reanchor 提交本身**（`renewal_seq == reanchor.base_seq`）；reanchor 提交写 `previous_seal_commit = from_a`；此后每次续签按普通规则 5/8 校验，`previous_seal_commit` 必须指回 reanchor 提交；第 8 步跳过条件收窄为「`previous_seal_commit == reanchor.from_a` **且** 当前是 reanchor 提交」 | §3.2 链规则 0/2/4、validator 第 4/5/8 步、reanchor 行为 | S-23、T-14 | **已被 v9 推翻**：本行只堵了「再篡改 previous」，未堵「伪造 reanchor 本身」；v9 载荷等价 + 外部锚、v10 边界记录认证才是现行判据（见 §0.8/§0.9） |
| B2 | `init` 写 v2、`migrate` 不补 v2、0.4.0 硬拒拼成死路；:904 与 :907 两条幂等定义相反 | **`init` 一律写 v1**，v2 只由 `migrate --to 2` 产生；`migrate` 对已是 v2 的清单**仍补齐缺失字段**（幂等 = 已有字段不动、缺失字段补上），删掉「重跑也不自愈」；V-12 落盘前白名单校验保留 | §5.2 第 5/6/8 条、§6 B-0 夹具 | V-13/V-14/V-15 | **已被 v9/v10 取代**：`init` 不再一律写 v1，按 `reader_version` 分支（0.4.0 写 v2 + `definition`，见 I-3/V-13/V-16）；本行只保留「v2 只由 `migrate --to 2` 产生」这半句的历史语境，不要照旧实现 |
| B3 | `e2e` 段内 `status` 子字段的反引号点号写法清不掉预存红：`test_canonical_consistency.py` 扫到 RFC 里的反引号点号引用，判「未在 §2 声明」 | 三处改为**正文描述**（`e2e` 段内的 `status` 子字段），不出现反引号包裹的「段名 + 点 + 字段名」形态；全 RFC 扫描确认无第二处同类字段 | §0.3 I7、§0.6 重要 8、§2.4 决策 5 | 实测 `test_contract_field_references_are_declared` 绿 | 真闭合（附命令与结果） |

**重要**

| # | 落点 | 改法 |
|---|---|---|
| I1 | §3.2 | 签署侧改为 `previous_seal_commit = 提交前 L[-1]`（等价于提交后的 `L[-2]`），写清「封条字节先于提交落盘」的视角；S-22 断言该等式 |
| I2 | §3.2 | `renewal_seq += 1` 改为「`renewal_seq = 提交后的 N`（顺序续签表现为 +1；merge/并行补签可跳级，只需单调且等于 `N`）」；补冲突 merge 实测反例 |
| I3 | §5.2/§3.3 | `migrate --check-members` 打印**解析后的实际路径**：active 与 archive 两种命令模板，夹具断言各出一条 |
| I4 | §3.2 | 新增「机读报告 schema」：顶层键固定集合、`downgrades[]` 项 `{code, flag, scope, detail}`、`scope ∈ {chain, definition_source, card_absent}`、`solution check --json` 为唯一产出点、数组按 `(code, path)` 排序（**已被 v9 取代**：项含 `path` 且三数组统一 `(code, path)`，见 §3.2「机读报告 schema」） |
| I5 | §3.2/§8 | 收窄为「只有 squash 成单提交**且**把封条改回 `seq=1 / previous_*=null` 不可检测」；rebase / filter-branch 归入「可检测（`renewal_chain_broken`），需 reanchor 才能继续」；S-18 同步（**已被 v9 取代**：`D>0`（删+重建）判 `seal_history_reset`，reanchor 不适用，见 §3.2「边界」） |
| I6 | §5.3 | B-0 无 `.atlas/VERSION` ⇒ 一律回落 `package.json`；两者都缺 ⇒ WARN + 固定提示（0.3.x），0.4.0 起才 FAIL（**已被 v9 取代**：三级回落、一律 WARN，见 §5.2 第 1 条与 §5.3） |

**次要**

- §0.5 P-3 表「反面包 = K-17」改为「K-17（v5 已删，v7 正式移除）」，不再是悬空编号。
- §8 残余风险补一行：`signed_at` 是工具自述，只能做 `gap.due` 下界，不能证明未重置。
- §3.2 字段定义补「`renewal_seq` 计的是封条路径提交数，不是续签动作数（续签次数 = `N - 1`）」。
- `L` 空先判空、S-19 按提交数、`definition: null` 归一三条第六轮已闭合，本轮未动；`docs/guide/changelog.md:14` 口径未动。

**状态**：v8 不宣称通过；B1/B2/B3 与 I1–I6 见上表判定（B3 附实测），等第八轮评审。

### 0.8 第八轮返工对照（v9）

> **本表已被 v11/v12 取代**：B1 行里的「anchor 必须与 `L[-2]` 同步（要先 `lock --update` 刷新）」是 v9 口径——预检时 `L[-2]` 是再上一枚封条，照它实现会把 PRE 重新挡红（v11/阻断 1 已改成按 HEAD 封条判）；`seal_anchor` 单对象也已被 v12 的按路径键映射 `seal_anchors` 取代。**不要照旧实现。**

**阻断**

| 编号 | 第八轮结论 | v9 改法 | 详见 | 反面包 | 闭合判定 |
|---|---|---|---|---|---|
| B1 | 伪造 reanchor 可重开豁免：任意续签把 `reanchor` 改成 `{base_seq: 当前 seq, base_n: N-1, from_a: 随机 sha}`，规则 4 恒成立、第 0/5/8/9/10 步全部命中例外 ⇒ PASS，且可换掉 `e2e.cases[]` / `gap` / `owner` | **两层都做**：① **载荷等价**——封条带 `reanchor` 时，除 `renewal_seq` / `previous_seal_commit` / `reanchor` / `signed_at` 外，其余字段必须与 `L[-2]` 的封条逐字节相等（机器判据，不再靠签署纪律）；② **外部锚**——锁新增 `seal_anchor = {first_commit, renewal_seq, n}`，`lock --update` 写入，`seal reanchor` 要求 `from_a == first_commit`、`base_seq == renewal_seq + 1`、`base_n == n`，且 anchor 必须与 `L[-2]` 同步（要先 `lock --update` 刷新），reanchor 后再 `lock --update` 提交 | §3.2 链规则 0/2/4、第 4/5/8/9/10 步、reanchor 段、§1.1.3 锁字段 | S-24/S-25（S-23 保留） | **真闭合（S-24/S-25）**；残余两类见 §8：锚与封条同提交篡改、旧原点确不可达时用锁内 `first_commit` 手写载荷不变的 reanchor（本地不可区分，靠 review/同 PR 评审） |
| B2 | 0.4.0 的 `init` 写 v1，与「0.4.0 只收 v2」互相否定：新仓建完下一次 `check` 即 `manifest_schema_unsupported`，而 `migrate` 只在 0.3.x 提供 | `init` 按 `reader_version` 分支：`< 0.4.0` 写 v1；`>= 0.4.0` 写 v2 **并写 `definition`**（路径来自 `_prd_skeletons` 已写出的 `product/prd/solution-prd.md`，`_support/solution.py:963-999`）。V-13 改写为 0.4.0 `init` 写 v2 + `definition`；新增 V-16（0.4.0 新仓 `init → check` PASS）；**V-13 从 B-0 夹具移到 B 批** | §5.2 第 8 条、§6 B/B-0 夹具表、§7 | V-13/V-16 | 真闭合 |

**重要**

| # | 落点 | 改法 |
|---|---|---|
| 1 | §3.2 报告 schema | `downgrades[]` 项补 `path`（可 `null`），三个数组统一按 `(code, path)` 排序；`definition_source` 场景给定义源路径，`chain` 给封条路径，`card_absent` 给卡路径 |
| 2 | §5.2 第 5/6 条、§8 | 明确 0.4.0 **不注册** `migrate`：v2 缺 `definition` 的自愈**只在 0.3.x 可达**，§8 残余风险写「需要 0.3.x 二进制」，V-15 补版本前提 |
| 3 | §5.3 | `reader_version` 加第三级回落：`.atlas/VERSION` → `package.json` → 代码内构建期常量 `__version__`；只有三者都缺才 `reader_version_unknown`，且一律 WARN |
| 4 | §3.2/§8 | filter-branch 分流：内容重写但封条路径保留（`D=0`）⇒ 可 reanchor；删+重建（`D>0`）⇒ 先判 `seal_history_reset`，reanchor 修不了，只能按新首签重建并走评审 |

**次要**

- §8 的 filter-branch 行收窄为「并重置成 `seq=1 / previous_*=null` 的单提交形态」——只改字节但保留 `seq`/`previous` 仍由第 5 步 SHA 不符抓得住。
- V-15 补 reader 版本前提（见重要 2）。
- K-17 标注、`signed_at` 残余风险、`renewal_seq` 命名三条第七轮已闭合，本轮未动。

**步序与合法路径自查（v9）**

1. **固定顺序 4 → 4b → 0 → 5/8/9/10**：第 4 步先判公式、第 4b 步再认证边界记录，第 0 步才用**提交身份**（`HEAD == R0`，`R0` = `L` 中第一枚 `renewal_seq == reanchor.base_seq` 的提交）决定是否走豁免；第 5 步的载荷等价、第 8 步的跳过条件、第 10 步的外部锚都依赖这几个结论。反过来先判 0 会把「只是字段里带着 reanchor 的普通续签」误认成 reanchor 提交；只用值等式会把 post-lock 提交误认成 reanchor 提交（v10/B-1）。
2. **锚校验只在 reanchor 提交处执行**：reanchor 之后 `lock --update` 会把 `first_commit` 推进到新纪元，若后续每次续签都拿旧 `reanchor.from_a` 与推进后的 `first_commit` 比，合法续签会全被判 `reanchor_anchor_mismatch`。因此规则 0 / 第 10 步显式限定「当前提交是 reanchor 提交」，普通续签只判规则 2/5/8。
3. **合法路径不被误红（fresh clone 首次 reanchor）**：`lock --update` 默认保留 `first_commit`（§1.1.3 第 2 条），重写后刷新只改 `renewal_seq` / `n`，`from_a` 仍是旧 A 且本地不可达 ⇒ 通过 4a；若每次从 `L[0]` 重算，`first_commit` 会变成重写后的可达首签，合法 reanchor 反被 `reanchor_not_allowed` 拒绝。
4. **仍然合法但会被判红/被拒的已知边界（v10 改为两类，不再说「唯一」）**：① **第二个纪元之后的就地重写**——后置 lock 已把 `first_commit` 推到可达的 `R0`，新 reanchor 的 `from_a` 只能取 `R0` ⇒ `reanchor_not_allowed`，**当前字段集无解**（§8 死结）；② **本机 squash 后旧原点仍在对象库**——`from_a` 可达 ⇒ `reanchor_not_allowed`，可到 fresh clone 绕开（有解）。两者都与真正的伪造同码，靠 `git cat-file -e <first_commit>` 区分。

**状态**：v9 不宣称通过；本轮暴露的 C 批两条阻断（B-1/B-2）与 I-1…I-6 已在 §0.9 返工，仍未宣称通过，等第十轮评审。B-0 验收夹具表现状见 §6 + §7（第八轮移出 V-13、补入 V-16）。

### 0.9 第九轮返工对照（v10）

**结论**：B-0 判定「能开」但补两条夹具断言；C 批两条阻断都是「规则自己要求做的事，一做就红」；B 批一处绑定缺口。v10 只改 RFC。

> **本表已被 v11/v12 部分取代**：`R0` 从「`L` 中第一枚」改为「唯一一枚（全量扫描，多枚即 `reanchor_record_mismatch`）」；`seal_anchor` 单对象改为按路径键的 `seal_anchors` 映射（v12/阻断 1），并增 `anchor_review` 与 4b 的 review 外部锚（§0.10 次-1、重要 1/2）。表内「第一枚」「单槽锚」只记录 v10 口径，不要照旧实现。

**阻断**

| 编号 | 第九轮结论 | v10 改法 | 详见 | 反面包 | 闭合判定 |
|---|---|---|---|---|---|
| B-1 | 后置 `lock --update` 独立提交后，`HEAD` 不在 `L`，值等式仍把 R2 判成 reanchor 提交 ⇒ `from_a` 与已推进的 `first_commit` 不符 + `seal_anchor_stale` 双红 | 「当前是 reanchor 提交」改为**提交身份**：`HEAD == R0`，`R0` = `L` 中第一枚 `renewal_seq == reanchor.base_seq` 的提交；post-lock / 不改封条的 merge 不在 `L` ⇒ 自动跳过第 10 步。后置 `lock --update` **必须独立提交、禁止 amend 到 R**（amend 后无字段可对）。补 S-26 | §3.2 规则 0/4a、第 10 步；§1.1.3 写锚规则；§3.2 reanchor 后置 | S-26 | 真闭合（R2 可构造 PASS；amend 形态明确无解） |
| B-2 | `reanchor` 字段可整段删掉：合法 reanchor 后 `seq == N` 恒成立，删字段仍 PASS；非边界续签把 `from_a` 换随机 sha 也 PASS | ① 锁内 `seal_anchor.first_commit != L[0]` ⇒ 封条**必须带 `reanchor`**，否则 `reanchor_record_missing`；② 封条带 `reanchor` 时在 `L` 中定位 `R0`，其 `reanchor` 对象必须与当前逐字节相同，否则 `reanchor_record_mismatch`（含 `R0` 不存在/多枚） | §3.2 规则 0/1、第 4b 步；§3.2 认证段 | S-27/S-28 | 真闭合（删除与改 `from_a` 两条路径都有机器判据） |

**重要**

| 编号 | 改法 | 详见 |
|---|---|---|
| I-1 | 删除「唯一」；§8 明写死结错误码 `reanchor_not_allowed` 与自查 `git cat-file -e <first_commit>`；说明第二个纪元之后的局部重写无解，未来需拆 `first_commit`（不可变）+ `epoch_origin`（推进），**不能简单停止推进** | §3.2 运维死结、§8 |
| I-2 | `N >= 2` 且 `base_n >= 1`，否则 `reanchor_invalid`；第 5/8/10 步所有 `L[-2]` 取用前统一 `len(L) >= 2` 守卫（squash 成单提交时不再 `IndexError`） | §3.2 规则 4、第 2/5/10 步 |
| I-3 | V-16 采纳走法 ②：0.4.0 `init` 写 v2 + `definition`，但 `definition.commit = null`（`blob` 有、`commit` 尚无）；0.4.0 放行到首次 `lock --update`，报 `definition_commit_pending` WARN，不触发 `definition_commit_unverifiable`；首次 `lock --update` 必须补齐 `commit` | §5.2 第 8 条、§6 B、§7 V-13/V-16 |
| I-4 | `__version__` 三级回落在代码里不存在：B 批文件表加 `_support/_version.py`（构建期写死，`install.py` 发布流程注入）；V-05 补三级来源各一条夹具；在此之前标**名义闭合** | §5.2 第 4/8 条、§5.3、§6 B、§7 V-05 |
| I-5 | §2.6 新增规则 5「锁（含 `seal_anchor`）与封条的变更必须同一个 PR」；§8 改引规则 5；`seal_anchor` 增可选 `anchor_review`（当前纪元的 reanchor REVIEW-ID），让锚变更在 diff 里自带评审号 | §2.6、§1.1.3、§8 |
| I-6 | 第 10 步固定顺序：形状 → `from_a` 可达（`reanchor_not_allowed`）→ `reanchor_anchor_missing` → `seal_anchor_stale` →（stale 成立即抑制）`reanchor_anchor_mismatch`；stale 是可恢复操作错误，mismatch 才是疑似篡改 | §3.2 规则 4a、第 10 步、§1.1.3 |

**次要**

1. §0.6/§0.7 旧口径加「已被 v9 取代」标注（I4/I5/I6/决策 1）。
2. reanchor 边界上的 `previous_seal_sha256` 置 `null`，并纳入载荷等价排除集（四字段 → 五字段，第五个必须为 `null`）。
3. V-15/§5.2 的提示主体改为「0.4.0 `check` 报 `definition_unbound`，message 里提示用 0.3.x 跑 `migrate`」。
4. 0.2.x 读 v2 硬拒不是 B-0 夹具（B-0 版本门 `{1,2}`、`reader_version` 注入在 B），移到 B 批夹具表。
5. S-18 写清构造要求：先在原仓产生真实 A 并 `lock --update` 记 `first_commit=A`，重写后 fresh clone 确认 `git cat-file -e A` 失败，再 reanchor；不得用从未存在过的 40-hex 冒充。

**B-0 补夹具**

- V-14 首步直接断言 0.3.x `init` 产物 `schema_version == 1`。
- V-07 加强：`migrate --to 2` 后锁文件字节不变；PRD 工作树脏时 `lock --update` 非零退出。

**状态**：v10 不宣称通过，已由 v11 返工（第十轮新增 2 阻断 + 6 重要见 §0.10）。

### 0.10 第十轮返工对照（v11）

| 编号 | 第十轮结论 | v11 改法 | 落点 |
|---|---|---|---|
| B-3 | `seal reanchor` 预检要求「锚与 `L[-2]` 同步」，而预检时 HEAD 是 reanchor 前的续签、`L[-2]` 是再上一枚 ⇒ 每次恢复都被 `seal_anchor_stale` 挡住 | 预检校验对象改为 **HEAD 的封条**（`anchor.renewal_seq == HEAD.renewal_seq`、`anchor.n == N`）；4a/第 10 步仍在 `HEAD == R0` 时用 `L[-2]`，两处比较对象不同 | §3.2 `seal reanchor` 段、4a/第 10 步注 |
| B-4 | 浅/partial clone 里 `cat-file -e` 一律失败 ⇒ 预检放行伪造的第二纪元；签出后加合法后置 lock，`HEAD != R0` ⇒ 第 10 步跳过 ⇒ PASS | `seal reanchor` / `lock --update` 预检加 `--is-shallow-repository` / `--is-partial-clone`，为真即拒；夹具 S-29；**不**改成「任意 HEAD 都查 `from_a`」 | §3.2 reanchor 段、§8、S-29 |
| I-7 | 多纪元回滚 `reanchor` 仍 PASS：4b 按 `seq == base_seq` 定位到第一纪元 `R0`、逐字节相同；`HEAD != R0` 时 `anchor_review` 无人比对 | 4b 增加**只比 `review`** 的外部锚校验：`anchor_review != null` 且当前封条带 `reanchor` ⇒ `current.reanchor.review == anchor_review`，否则 `reanchor_record_mismatch`；夹具 S-30 | §3.2 第 4b 步、§8、S-30 |
| I-8 | 换封条路径后锚仍指旧路径的 `first_commit` ⇒ 规则 1 误判 `reanchor_record_missing`（实测 PATH 期望 PASS） | `seal_anchor` 增 `path`；规则 1 / 4a / 4b / 第 10 步都要求 `anchor.path == 当前封条路径`；`lock --update` 换路径时重置锚；夹具 S-31；§3.2 路径段改成「不得删除旧路径」 | §1.1.3、§3.2、S-31 |
| I-9 | `reader_version` 第二级写成 `<root>/package.json`，采纳仓业务仓的 `1.2.0` 会被当成工具版本 | 第二级固定为**工具自身**的 `package.json`（`Path(atlas_package_root)/package.json` 或 `.atlas/package.json`） | §5.2 第 1 条、§5.3 |
| I-10 | 中间级不可解析就记 `reader_version_unknown`，与「三者都缺才 unknown」矛盾 | 中间级只记 `downgrades[]` 并继续回落；`reader_version_unknown` 只在三级全缺时作为最终状态；V-05/V-09 改写 | §5.2 第 1 条、§5.3、V-05、V-09 |
| I-11 | §0.7 的 B1/B2 旧口径未标「已被取代」，与 v10 相反 | B1 标「已被 v9 推翻」；B2 标「已被 v9/v10 取代」 | §0.7 |
| I-12 | §2.6 规则 5 字面会打回每一次普通续签（普通续签改封条、不改锁） | 规则 5 收窄为「`seal_anchor` 的变更必须与封条中 `reanchor` 的变更同 PR」；普通续签不受限 | §2.6 规则 5 |
| 次-1 | `R0` 用「第一枚」是实现陷阱；`L` 不保证 `seq` 单调 | 改为「唯一一枚 + 全量扫描，>1 即 `reanchor_record_mismatch`」；明说不要求单调，不补「严格递增」前置 | §3.2 符号表、规则 0、4b |
| 次-2 | 「首次 `lock --update` 后仍为 null ⇒ FAIL」缺状态标记 | 标记依次取 `acceptance_cutover != null` → 上一条锁 `definition.commit` 非 null → 都不可判则 WARN | §5.2 第 8 条、状态表、§8 |
| 次-3 | §1.1.6 三态漏 `commit == null` | 明写「null 是 `init` 后暂时态，见 `definition_commit_pending`，不落三态」 | §1.1.6 |
| 次-4 | 规则 1 的守卫可被「同提交删锚 + 删字段」绕过；§8 只写「篡改」没写「删除」 | §8 残余①扩为「同时篡改**或删除**」；规则 1 注明该形态是残余① | §3.2 规则 1、§8 |
| 次-5 | 符号混用：`R0`/`R0'`/`L`/`N`/`n`/`seq`/纪元/`first_commit` 时点 | 新增 §3.2 符号表；统一 `N = len(L)`、`n` 是锁快照；`R0'`、纪元、`first_commit` 时点定义补齐 | §3.2 符号表、§1.1.3 第 7 条 |
| 次-6 | `HEAD ∈ L` 且同改锁+封条是合法的，未写明 | 在第 10 步执行条件补「一次普通续签把 `seq` 升到 `base_seq+1` ⇒ 跳过；不升则规则 4 红」 | §3.2 第 10 步 |
| 次-7 | 路径段同句「不可移动」与「确需换路径」 | 与 I-8 一并改为「不得删除旧路径；确需换路径时按新首签」 | §3.2 路径段 |

**v11 自查**：四个指定场景按文本推演——A/M（普通链）仍 PASS；K·K2（删 `reanchor`）仍 `reanchor_record_missing`；J（改 `from_a`）仍 `reanchor_record_mismatch`；`N=1` / `base_n=0` 的 reanchor 仍 `reanchor_invalid` 且不取 `L[-2]`。新增的 `path` / `review` / 浅克隆判据都不在合法普通续签路径上（post-lock 与 merge 不触发 4b 的两个新分支；换路径由 `lock --update` 重置锚）。**仍不宣称通过，等第十一轮。**

### 0.11 第十一轮返工对照（v12）

**结论**：v11 的两条阻断（预检对象、浅克隆）成立并保留；但 v11 的 I-8 修法（单槽锚 + `path` 守卫）引入更宽的旁路——多封条共存时锚只记得最近刷新的一枚，旧路径的规则 1/4a/4b 全部被路径守卫跳过。v12 把锚改成**按路径键的映射**，并把 partial clone 探测改成可降级形式。

| 编号 | 第十一轮结论 | v12 改法 | 落点 |
|---|---|---|---|
| N-1（阻断） | `seal_anchor` 单槽：多封条时 `lock --update` 用最近一枚重置 `path/first_commit/anchor_review`，旧路径因 `anchor.path == 当前封条路径` 守卫被整段跳过；实测旧路径 `N=4, seq=4` 删 `reanchor` PASS；第二枚封条刷新后第一枚照过 | `seal_anchor` → **`seal_anchors: {"<封条路径>": {first_commit, renewal_seq, n, anchor_review, retired}}`**；`lock --update` 只写当前路径键（`--seal` 显式，多枚不猜），**绝不重置其他键**；换路径新增键、旧键 `retired` 保留并继续约束旧路径；validator 断言「HEAD 封条路径集合 == 映射键集合」，缺键 `seal_anchor_path_unmapped`、多键 `seal_anchor_path_orphaned`；规则 1/4a/4b/第 10 步/预检全部按当前路径查表，并对每个键循环；S-31 期望改为「新路径 PASS、旧路径删 `reanchor` 必红」（S-31b），新增 S-32/S-33/S-34 | §1.1.3、§2.6 规则 5、§3.2 符号表与规则 0/1/4a/4b/第 10 步、`seal reanchor` 预检、§7、§8 |
| N-2（阻断） | `git rev-parse --is-partial-clone` 在 git 2.50.1 / Apple Git-155 不存在：normal / `--filter=blob:none` / `--depth 1` 三仓实测都 exit 0 并原样回显，「非零即拒」「输出为 true 即拒」都永不生效 | 保留 `--is-shallow-repository`；partial 改用 `git config --get-regexp '^remote\..*\.promisor$'` / `git config --get extensions.partialClone` / `ls objects/pack/*.promisor`；S-29 拆 S-29（`--depth 1`）与 S-29b（`--filter=blob:none`）；明确 partial 只是纵深防御、严重度低于 shallow | `seal reanchor` 预检、§8、§7 S-29/S-29b |
| N-3（重要） | :893「同路径删+重建永久红」与 :952「换路径重建」自相矛盾，后者会把重置事实从机读面抹掉 | 同路径删+重建仍永久红（`D>0` ⇒ `seal_history_reset`）；换路径重建新增 `moved_from.path` 必须仍在 HEAD 存在、其续签链可复算、`moved_from.sha256` 与旧路径 HEAD 封条字节一致，否则 `seal_path_history_lost` FAIL | §3.2 触发段、路径段、§7 |
| N-4（重要） | 次-2「上一条锁」用 `HEAD^`，merge 下只取第一父，来自第二父的锁值判不出来 | 改 `git log -1 --format=%H --skip=1 -- atlas.solution.lock.json`；实现不便时对**所有父**取锁文件较新版本再比 | §5.2 第 8 条、§3.2 status 表、§8 |
| N-5（重要） | `downgrades[]` 的 `code`/`scope` 枚举没有 `reader_version`，但 §5.3/V-05 要求记一条 | 枚举补 `code: reader_version`、`scope: reader_version`、`path` = 被跳过的来源文件；V-05 与 schema 对齐 | §3.2 downgrades schema、§5.3、V-05 |
| N-6（重要） | §0.8 的 B1 行仍写「anchor 必须与 `L[-2]` 同步（要先 `lock --update` 刷新）」，无取代标注 | §0.8 整表加「已被 v11/v12 取代」注记，点明 PRE 挡红与单槽锚两处 | §0.8 |
| N-7（重要） | §0.6 决策 5 漏「必须是完整克隆」 | 补「且必须是完整克隆（partial 的可达性同样不可判）」 | §0.6 决策 5 |
| 次-8 | 符号表无作用域：`first_commit` 一名三义、`n` 无路径键、`R0` 未限定路径、纪元两义 | 符号表加「默认作用域 = 当前封条路径」；`n[path]`/`first_commit[path]`/`R0[path]` 显式带键；`first_commit` 三名逐条列明；纪元按路径定义 | §3.2 符号表、§1.1.3 第 8 条 |
| 次-9 | :945/:1391「残余风险只剩两类」被 N-1 证伪 | 改三类：①锚与封条同提交同改（只删锚/只删字段已被固定码拦）；②旧原点不可达时手写载荷不变的 reanchor；③无可枚举封条路径的空集退化。并说明「多封条互踩锚」已不在残余 | §3.2 `seal reanchor` 段、§8 |
| 次-10 | 反面包缺「旧路径仍受约束」与「多封条互不搬锚」 | S-31 改期望、新增 S-31b/S-32/S-33/S-34、T-20/T-21 | §7 |
| reader_version | 三级来源与实现不一致（RFC 第三级 `_support/_version.py` vs 实现第三级工具包根 `package.json`） | 三级固定为 `.atlas/VERSION` → `.atlas/package.json` → `<工具包根>/package.json`，取消 `_support/_version.py`；§5.3/V-05/§6 B 文件表同步 | §5.2 第 1 条、§5.3、V-05、§6 B |

**v12 自查**：N-1/N-2 在文本上闭合（见 §3.2 与 §7）；四个指定场景（A/M、K·K2、J、`N=1/base_n=0`）判序未变；新增的两条键集合断言只在「缺键/多键」时触发，普通续签、post-lock、merge、换路径（S-31）都不触发。**不宣称通过。**

### 0.12 第十二轮返工对照（v13）

**结论**：N-2 真闭合；N-1 只闭了一半——v12 把「锚」从单槽改成按路径键的映射，但**键集本身仍从 HEAD 枚举**（`seal_anchors` 的键 == HEAD 封条路径）。于是「删旧文件 + 删旧键」这一步让旧路径同时从文件面和键面消失，集合仍相等、循环里没有旧路径，`D>0` / `seal_history_reset` / `seal_path_history_lost` / `seal_absent` 全部不触发。v13 改的是**宇宙来源**，不是再加一条错误码。

| 编号 | 第十二轮结论 | v13 改法 | 落点 |
|---|---|---|---|
| R12-1（阻断） | 键集 = HEAD 封条路径 ⇒ 删键 + 删文件就退出校验宇宙；合法改名可洗掉整条旧链 | 键集改为**历史新增封条路径的并集**（`git log --diff-filter=A --no-renames --format= --name-only HEAD -- ':(glob)**/reviews/apply/**/*.seal.json'`；不带 `<assets_root>` 前缀，因为它可改名；实测 `--no-renames` 必需：去掉它 rename 检测会让新路径以 `R` 出现、`A` 消失；**已被 v14/B-1 取代**：命令补 `-m --full-history`、改固定 `<assets_root>` 前缀 + 两段谓词；**再被 v15/D-1 取代**：根进锁的 `assets_root_history`，见 §0.14）；键 **append-only**，只允许改 `state`；`state ∈ {active, retired, frozen}` **每个状态都有判据**；`moved_from` 是换路径唯一凭证；同路径封条**一旦出现即不可删除**，删任务只能整条冻结；结论「不存在『删文件但不迁出』的合法形态」 | §1.1.3 第 2/5/6/10 条、§3.2 符号表与规则 1、§7 S-36、§8 残余③ |
| R12-2（重要） | 首次刷新标记（`acceptance_cutover` / 上一条锁 / WARN）都是一步记忆，`init → lock --update → 改回 null` 可回退 | 主判据改为**锁文件完整历史扫描**：`git log --format=%H HEAD -- atlas.solution.lock.json` 逐个 `git show <c>:<lock>`，最近一次 `definition.commit != null` 而当前为 null ⇒ FAIL；若按「HEAD 之前」比较，**主判据是「各父中较新版本」**，`--skip=1` **只在 HEAD 自己触碰锁时**与之等价（实测两者在 merge 下返回不同提交；**已被 v14/B-2 取代**：主判据改 `git log -m --full-history --format=%H HEAD -- atlas.solution.lock.json`，这两句等价声明已整段删除） | §5.2 第 8 条、§8 |
| R12-3（重要） | S-31b / S-33 缺前置，缺前置时分别 PASS | S-31b 行首写死「旧路径本来就有合法 `reanchor` 且跑过后置 `lock --update`」；S-33 写死「旧路径 ≥2 个纪元且 `anchor_review != null`」，并注明直接从 S-30 的仓接续构造 | §7 S-31b/S-33 |
| R12-4（重要） | `retired` 无任何规则分支，会被理解成「可跳过」 | 给真实判据：`retired` 必须有 `moved_to`、目标封条的 `moved_from` 必须指回并 sha 匹配；`retired` 路径**禁止**新续签 / 新 `reanchor` / 改 `e2e.cases[]` / `owner`，违反 `seal_path_retired_write`；其迁出前链仍按规则 0–7 复算 | §1.1.3 第 5 条、§3.2 判序、T-23 |
| R12-5（重要） | 命名混用：纪元、`first_commit`、`R0'` | `first_commit` → `epoch_origin[path]`（已全局改，§0 历史表保留原文）；`R0'` → `R0_second[path]`；「纪元」拆成**纪元起点**（链的分段起点）与**锚记账时点**（后置 lock 写 `epoch_origin` 的时刻）两个词 | §3.2 符号表、§1.1.3 |
| R12-6（重要） | `seal_anchor_path_orphaned` 与 `seal_path_history_lost` 可能同时命中，优先级未定 | 固定判定优先级：**① 路径级（unmapped / orphaned）→ ② 状态合法性（state 与 HEAD/历史一致、frozen 被改、retired 被写）→ ③ 链级与 `moved_from`**；同一提交多码只报第一个 | §1.1.3 第 2 条、§3.2 链规则表头 |
| 次-11 | S-32 未写多封条必须带 `--seal <path>` | S-32 行首写明；新增 S-37「多封条不给 `--seal` ⇒ exit 2 并列出候选」 | §7 S-32/S-37 |
| B 批前置 | `reader_version_unknown` 时 `init` 行为未定 | 三级全缺 ⇒ `init` **fail-closed（exit 2）**，不得默认写 v1（无法判断自己是 0.3.x 还是 0.4.0）；`check` 仍是 WARN | §5.2 第 8 条、§5.3、§6 B、V-18 |

**v13 自查**：① 键集宇宙可由 `git log --diff-filter=A --no-renames` 一次性稳定复算（实测：rename 前后两路径都出现为 `A`；去掉 `--no-renames` 新路径消失）；② 三个状态各有独立判据（active ⇒ 规则 0–10 + 文件在 HEAD；retired ⇒ `moved_to` + 目标 `moved_from` + 迁出前 0–7；frozen ⇒ 文件在 HEAD + `frozen_at` 后无提交 + blob 相等）；③ `D>0` 永远有归属（active ⇒ `seal_history_reset`；retired ⇒ 必须有且仅有一次被 `moved_from` 覆盖的删除；frozen ⇒ `seal_frozen_modified`）；④ R12-6 优先级写在 §1.1.3 第 2 条，S-36 的首报码据此确定。**仍不宣称通过。**

### 0.13 第十三轮返工对照（v14）

**结论**：R12-1 的**方向**对（键集取历史并集），但**命令写错了**——`U` 少了 `-m --full-history`，在 `git merge -s ours` 这种正常命令下当场退化成空集，S-36 的假绿原样复现；锁的「完整历史扫描」同样少了 `--full-history`，merge 保留 null 锁时看不到侧支的非 null，FAIL 被降级成 WARN。其余 6 条重要都是「规则写了判据、CLI 上没有可执行的出口或约束」，v14 逐条补出口与可判谓词。

| 编号 | 第十三轮结论 | v14 改法 | 落点 |
|---|---|---|---|
| B-1（阻断） | `U` 缺 `--full-history` 与 `-m`：`-s ours` 后 `U` 为空、键一起删就全不触发；merge 内新增封条看不见 ⇒ 新封条的键永远建不了 | 命令写死 `git log -m --full-history --diff-filter=A --no-renames --format= --name-only HEAD -- ':(glob)<assets_root>/reviews/apply/*/*.seal.json'`；**分别**写明 `U` 为什么要 `-m`（`git log` 默认不输出 merge diff）、`L` 为什么不要 `-m`（`L` 用 `git show`，加 `-m` 会把一个 merge 拆成多份、`N` 偏大）；夹具 S-39/S-40 | §1.1.3 第 2 条、§3.2 符号表、§7 |
| B-2（阻断） | 锁历史扫描缺 `--full-history`：merge 保留 null 锁时只看得见 null 那条，`definition_commit_unverifiable` 被 `definition_commit_pending` 蒙混 | 主判据改 `git log -m --full-history --format=%H HEAD -- atlas.solution.lock.json`（同一 merge 按 `%H` 去重）；写明 `--full-history` 才是防剪枝的那一个、`-m` 在只取 `%H` 时无增量但统一口径；删 `--skip=1` 与「各父中较新版本」两句等价声明；夹具 V-19 | §5.2 第 8 条、§8 |
| I-1（重要） | `frozen` 只有判据没有写入出口，`lock --update` 也不写 `state: frozen`，「任务下线只能冻结」在 CLI 上不可执行 | 定义 `seal freeze --seal <path> --at <sha>`：只写 `state: frozen` 与 `frozen_at`，不碰封条字节，`frozen_at` 取该路径最后一次封条变更提交；`lock --update` 遇已 `frozen`/`retired` 的键**原样保留** `state`；S-38 改成「可由 `seal freeze` 接续构造」 | §1.1.3 第 3/11 条、§7 S-38 |
| I-2（重要） | `moved_from` 只认证旧封条，不约束新封条载荷：`git mv` + 换掉全部 `e2e.cases[]` + `reasons=[]` + 不写 `previous_cases` 全绿 | 换路径首签要跟 `L_pre[-1]` 比载荷，豁免集 `{renewal_seq, previous_seal_commit, previous_seal_sha256, moved_from, signed_at, reanchor?}`；不等就必须写 `reasons` + `previous_cases[]`，否则 `seal_move_payload_mismatch` FAIL；夹具 S-42/T-26 | §1.1.3 第 6 条、§3.2 规则 3、§7 |
| I-3（重要） | `U` 先于 shallow 判定，`--allow-unverifiable-chain` 下被截断的 `U` 无告警 | shallow / partial 移到判序第 0 步（**先于** `U`）；明写「仓形态不可信时路径级断言不得因 `U` 偏小而放行，`seal_anchor_path_unmapped` 不参与窄开关降级」 | §3.2 判序 |
| I-4（重要） | `U` 是超集，`docs/examples/reviews/apply/demo.seal.json` 也进 `U`，锁不建键就永久红，而 `lock --update` 又不许给非封条建键 | 给可判谓词 `^<assets_root>/reviews/apply/[^/]+/[^/]+\.seal\.json$`（`apply/` 之后恰好两段），并补「docs 样例不入 `U`」夹具 S-41 | §1.1.3 第 2 条、§7 |
| I-5（重要） | 新增封条必然产生一个永久红提交，且 `epoch_origin = L[0]` 自指 | 写死「封条提交与建键提交必须成对，中间态 `seal_anchor_path_unmapped` 是**预期红**，CI 只判 PR 头」；`epoch_origin` 由**后置**建键提交写；禁止在一个提交内同时加封条与建键 | §1.1.3 第 2/10 条、§7 |
| I-6（重要） | 「`assets_root` 可改名」与 `definition.path` 字面量、`-prd.md` 读者、卡投影路径冲突 | **放弃可改名前提，固定前缀**：改名后上述三处全部失效，契约其余部分没有任何迁移动作；正文删除「可改名」表述，`U` 直接用固定前缀（**已被 v15/D-1 取代**：根改成锁里 append-only 的 `assets_root_history`，改根走 `lock --update --assets-root`，见 §0.14） | §1.1.3 第 2 条 |
| N-1（次要） | `L_pre` 没有取值命令 | 写死 `idx = max{i \| L[i] 的 name-status 含 D}`、`L_pre = L[0:idx]`、无 `D` 时 `L_pre = L`；判命令 `git show --format= --name-status --no-renames <c> -- <S>` | §3.2 符号表、§1.1.3 第 5 条 |
| N-3（次要） | force-push 改写锁历史 | 写进 §8 残余，与 squash 并列：抹掉该提交后主判据也看不见，只剩 `acceptance_cutover != null` 能兜 | §8 |
| N-4（次要） | S-37 需多封条仓、T-23/T-24 需合法 `retired`/`frozen` 仓、S-38 依赖 freeze 命令，否则会被实现成恒真 | 三条都写「可由 S-31 / `seal freeze` 接续构造」 | §7 |

**v14 自查**：① 两条命令都带 `-m --full-history`，且**分别**写了「为什么」（§1.1.3 第 2 条给 `U`，§5.2 第 8 条给锁；并写明 `L` 不要 `-m`）；② `U` 与键集在同一坐标系（都是仓内字面路径、含 `<assets_root>` 前缀），`键 ∖ U == ∅` 才有意义；③ `seal freeze` 是 `frozen` 的唯一写入口，`lock --update` 不再碰 `state`；④ 新增封条 → 建键两个提交的顺序写死，中间态是**预期红**而不是「待修」。**仍不宣称通过。**

### 0.14 第十四轮返工对照（v15）

**结论**：R12-1 的「键集取历史并集」这次栽在**根的来源**上——`U` 的根仍读 `atlas.config.yaml` 现值，而那是**被检查方提交的文件**；改根就换掉了整个宇宙。v14 把 v13 那句「`U` 不因删键/删文件/改 `assets_root` 而缩小」砍成前两项，性质随之丢失，不是措辞问题。v15 把根也纳入锁的 append-only 历史，`U` 对所有历史根取并集，并在判序最前面用 `assets_root_changed` 卡住。

| 编号 | 第十四轮结论 | v15 改法 | 落点 |
|---|---|---|---|
| D-1（阻断） | `U` 的根来自可改的 `atlas.config.yaml`：`git rm` 封条 + `git mv product product2` + 改 config + 锁清空 ⇒ `U=0`，封条提交仍可达却全不触发；反方向合法改根 ⇒ 旧键 `seal_anchor_path_orphaned` 永久红、无恢复命令 | ① 锁新增 `layout_assets_root` 与 `assets_root_history[]`（append-only，首元素为首锁时的根）；② `check` 在判序第 0 步**之前**断言「config 现值 ∈ 历史」，否则新码 `assets_root_changed` FAIL，且**不参与 `--allow-unverifiable-chain` 降级**；③ `U` 对**所有历史根各算一次再并集**，命令仍是 `git log -m --full-history --diff-filter=A --no-renames`；④ 改根只能 `lock --update --assets-root <new>`：append 历史（不删旧值）、要求同提交把清单/资产树一起移动、要求 `anchor_review` 记录（与 reanchor 同一评审面）；「改根 + 删旧键」必红。夹具 S-43/S-44 | §1.1.3 第 12 条、§3.2 前置断言与符号表、§1.1.3 解析器第 3 条（`锁版本`）、§7 |
| I-1（重要） | 首签 rebase 必红且无自助出口；不写「禁止 rebase」（PR 上无法用机器门守） | `lock --update` 允许**受控重指** `epoch_origin`，四条同时满足：`state == active`、`anchor_review == null`、`renewal_seq == 1`、旧值不在当前 HEAD 历史（`git merge-base --is-ancestor` 为否或 `cat-file -e` 失败）；重指必须 append `epoch_origin_history[]`（旧值不删、一次最多一条）；任一不满足仍报 `reanchor_record_missing`，不放宽。夹具 S-45/S-46 | §1.1.3 第 3 条 |
| I-2（重要） | 两段谓词没有写入侧约束：`apply/auth/sub/T-2.seal.json`、`apply/T-3.seal.json` 都不进 `U`，建键时报 `orphaned` | 清单加载期拒绝含 `/` 的 `members[].name`（`<member>` 限 `[^/]+`）；`lock --update --seal` 对不匹配谓词的路径报专用码 `seal_path_unsupported`，不复用 `orphaned`。夹具 T-27 | §1.1.3 第 2 条/⑤、§7 |
| I-3（重要） | 规则 11 说「第 3 条原样保留」，但规则 3 只写了 `epoch_origin`/`anchor_review` 与 `state` | 规则 3 补「该状态专属字段（`moved_to` / `frozen_at` 等）原样保留，只刷新 `renewal_seq` / `n`」；夹具 S-47（v16 拆为 S-47a / S-47b） | §1.1.3 第 3 条 |
| I-4（重要） | `seal_move_payload_mismatch` 未进判序 | 归入优先级 ③，且 `seal_path_history_lost` **先于**它（凭证不成立时载荷比较无意义） | §1.1.3 判定优先级 |
| N-2（次要） | `signed_at` 在换路径豁免集里，`git mv` 就能把豁免到期日往后推 | 新 `signed_at` **不得晚于**旧版，晚于 ⇒ `seal_move_payload_mismatch`；夹具 T-28（**已经第十五轮改判：该方向写反，见 §0.15 N-2**） | §1.1.3 第 6 条 |
| N-1（次要） | `seal freeze --at` 另立了 `git log -1` 算法 | 改为「`--at` 必须等于按符号表算出的 `L[-1]`」，删除第二套算法 | §1.1.3 第 11 条 |
| N-3（次要） | 中间态红的本地口径未写 | 写明两提交之间看到 `seal_anchor_path_unmapped` 属预期；采纳仓若有 pre-push 逐提交跑 `check`，应跳过该中间提交 | §1.1.3 第 2 条 ③（`新建键`）、§8 |

**v15 自查**：① `U` 的根不再来自任何单一现值，`assets_root_history` 首元素即首锁根、append-only、删不掉；② `assets_root_changed` 排在一切路径级判据之前且不参与降级，改根缩宇宙这条路径在文本上断开；③ 合法改根有唯一出口且旧键不会 orphaned；④ 首签 rebase 有可执行的恢复路径，且 `epoch_origin_history[]` 让「改锚」本身留痕。**仍不宣称通过。**

### 0.15 第十五轮返工对照（v16）

**结论**：v15 把根搬进了锁，但**锁本身也是被检查方提交的文件**——「`config ∈ history`」与「`layout == history[-1]`」两条都只读当前锁，单提交整段重写 `assets_root_history: ["product2"]` 就全绿；「删锁 → 改根 → 重建锁」同理。v16 把根集改成**锁文件全部历史版本的并集**，当前锁必须**包含**历史并集，于是重写数组、删锁重建都删不掉旧根；另外把换路径的豁免起点从封条 `signed_at` 移进锁键（`exemption_started_at`），修掉「合法换路径必红」。

| 编号 | 第十五轮结论 | v16 改法 | 落点 |
|---|---|---|---|
| D-1（阻断） | `assets_root_history` 与 `layout_assets_root` 同属被检查方：删封条 + `git mv` + 改 config + 锁改成 `["product2"]` + `seal_anchors: {}` ⇒ ⓪ 过、`U=∅`、全绿；删锁重建同绕 | ① `U` 的根集 = **锁文件全部历史版本**的 `assets_root_history` 并集（v1 锁回落 `layout_assets_root`，再回落该提交的 `layout.assets_root`）；② 新码 **`assets_root_history_rewritten`** 排在 ⓪：当前数组必须**包含**历史并集，`layout != history[-1]`、当前缺字段而历史有，都同码；③ 新增 **S-48** | §1.1.3 资产根 bullet 与 `U` 命令、§3.2 前置断言、§7 |
| N-2（阻断，改判） | `signed_at` 单向写反：换路径首签签在现在，`now > old` 恒成立 ⇒ 合法换路径全红，与 S-31 冲突；旧封条每续签一次 `signed_at` 就后移，拿它当豁免起点是移动靶 | 方案 A：豁免起点移出封条——锁键新增 `exemption_started_at`（建键写死，`lock --update` / `seal freeze` 都不改），`gap.due` 的**下界**从它算（**v22/I-6 起改由不可变的 `exemption_start_origin` 承担；v23/I-3 起 due 是区间，上界取 `first_seen_origin + 90d`，见 §0.21/§0.22**）；`signed_at` 退回纯审计并**移出换路径豁免集**（换路径不是重签，逐字节沿用旧值）；T-28 改为「`exemption_started_at` 被刷新/后移 ⇒ FAIL」 | §1.1.3 第 2/6 条、§3.1、§7 |
| I-1（重要） | `:976`「仅 `lock_missing` 时跳过」与 `:494`「v1 升 2 之前不判」两条自相矛盾；删锁重建没点名 | 统一为：v1 锁或缺两字段 ⇒ **跳过 ⓪ 并 WARN `assets_root_history_absent`**；但 **v1 锁且 `seal_anchors` 非空 ⇒ `lock_v1_with_seals` FAIL**；删锁重建由「当前缺字段而历史有 ⇒ `assets_root_history_rewritten`」覆盖并点名 | §1.1.3 锁版本、§3.2 前置断言、§8 |
| I-2（重要） | 规则 12 ③ 覆写 `anchor_review` 破坏 4a/4b：做过 reanchor 的路径合法改一次根就假红 | `assets_root_history[]` 元素改为对象 `{root, review, commit}`，评审号进历史元素；`anchor_review` 仍只由 reanchor 写；S-44 加「另有已 reanchor 的路径，改根后仍 PASS」 | §1.1.3 第 12 条、§7 |
| I-3（重要） | `epoch_origin_history` 不在 schema、无初值 | 键值集合补该字段；规则 2 建键写 `[epoch_origin]`；规则 3 存量键缺失时按 `[当前 epoch_origin]` 初始化再 append；§8 的「长度 = 1 + 重指次数」升级为断言，违反 ⇒ `epoch_origin_history_rewritten` | §1.1.3 第 2/3 条、§8 |
| I-4（重要） | 受控重指四条不可判 | ② 改为「锁历史里该键从未出现过非 null 的 `anchor_review`」；③ `renewal_seq` 读 **HEAD 封条**不读锁快照；④ `merge-base --is-ancestor` 退出码 **1 = 不可达、128 = 对象缺失/不合法**都可重指，其他非零不得当「否」；上限 **1 次**（`len(epoch_origin_history) <= 2`）（**v17/B-2 已删除该上限**，见 §0.16） | §1.1.3 第 3 条 |
| I-5（重要） | `seal_path_unsupported` 判序与存量成员名未定 | ① 顺序改为 `seal_path_unsupported` → `seal_anchor_path_unmapped` → `seal_anchor_path_orphaned`，键不匹配任何根谓词**只报 unsupported**；存量清单含 `/` 的成员名 ⇒ v1 `migration_required` WARN + `migrate` 给改名建议（不自动改），v2 新写入 FAIL，已存在的三段键**永久 `seal_path_unsupported`**、不回落成 orphaned | §1.1.3 第 2 条/⑤、判定优先级 |
| I-6（重要） | 两个根字段没有 schema 约束 | `assets_root_history` 非空、元素互不相同、`layout == history[-1]`，违反 ⇒ `assets_root_history_rewritten`；根字符集**曾**限 `[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*`（**v19/阻断 1 已废**：该窄字符集与 `_support/layout.py` 双源，合法装入的根会永久红；现由 `layout.validate_value` 单源判定，见 §1.1.3 ② 与 §0.18） | §1.1.3 资产根 bullet |
| 次要 1 | §0.14 两处节号漂移 | D-1 行的「§5.2」改为「§1.1.3 解析器第 3 条（`锁版本`）」；N-3 行的「§8」改为「§1.1.3 第 2 条 ③」 | §0.14 |
| 次要 2 | S-47 一个夹具覆盖不了两种状态 | 拆成 **S-47a**（`frozen`：手改 `frozen_at` ⇒ `seal_frozen_modified`；不动 ⇒ PASS）与 **S-47b**（`retired`：`lock --update` 后 `moved_to`/`state` 原样） | §7 |
| 次要 3 | S-45 缺前置 | 补「`epoch_origin_history` 初值来自规则 2（建键即 `[epoch_origin]`），否则『从一条变两条』不可判」 | §7 |

**v16 自查**：① 根集不再来自任何**单一锁版本**：`U` 的根取锁全历史并集，当前锁只能「包含」不能「改写」，重写数组与删锁重建都在 ⓪ 断开，且**即便 ⓪ 被绕过，`U` 仍含旧根**（两道独立防线）；② 换路径豁免起点落在锁键且建键即冻结，封条 `signed_at` 不再承担期限语义，S-31 与 S-42 不再互相矛盾；③ 改根不再碰任何键的 `anchor_review`，4a/4b 与多纪元外部锚（S-30）不受影响；④ `epoch_origin_history` 有初值、有上限、有篡改断言，受控重指四条都给了可执行判法。**仍不宣称通过。**

### 0.16 第十六轮返工对照（v17）

**结论**：v16 把根集搬到了「锁文件历史」，但**解析层是 fail-open**——参考实现用 `jq` 逐版本解析，`jq` 失败被管道吞掉，坏版本静默消失，于是「提交 A 写坏数组 → 提交 B 改根删封条删键」重新全绿；同类还有 `[]` 的 truthiness、`{root: null}` 被 `-r` 打成字面量 `null`、v1 缺 config 静默丢根，以及 **`jq` 不是本仓依赖**（采纳仓 Windows 无 `jq`）。另一条阻断是重指上限：`len <= 2` 与 `N == 1` 的 reanchor 判 `reanchor_invalid` 叠加，单封条路径 rebase 两次后无解。v17 把历史解析改成**同一严格解析器 + 失败即 `lock_history_unparsable`**，并删掉次数上限。

| 编号 | 第十六轮结论 | v17 改法 | 落点 |
|---|---|---|---|
| B-1（阻断） | `UH` 解析 fail-open：`jq` 失败被吞、`[]` truthy、`{root:null}` 造假根、v1 缺 config 丢根；`jq` 不是本仓依赖 | ① 历史版本一律走 `_support/solution.py` 的同一严格解析器，任一版本解析失败/类型不对/空数组/元素缺 `.root`/`root` 非法 ⇒ **`lock_history_unparsable` FAIL**，不得跳过；② 删除全部 `jq`，改 Python 遍历；③ 写锁必须严格 JSON，任何命令不得重排/归一化/重写既有 `assets_root_history`（B 批的 `lock_payload` 同守）；④ 新增 **S-49** | §1.1.3 第 2 条与资产根 bullet、§3.2 ⓪、§5.2、§7 |
| B-2（阻断） | 重指上限造成死结：`len <= 2` + 「第二次起必须 reanchor」+ 「`N == 1` 的 reanchor 判 `reanchor_invalid`」⇒ rebase 两次永久红 | **删掉次数上限**，只保留四条开放条件（`state == active` / 锁历史无 `anchor_review` / HEAD 封条 `renewal_seq == 1` / 旧锚不可达）；`epoch_origin_history` 只作审计留痕，长度断言保留为**篡改检测**、不再当门 | §1.1.3 第 3 条、§8 |
| I-1（重要） | `exemption_started_at` 仍可后移：首写可写晚；换路径不从旧键继承（新键取旧封条 `signed_at`，续签后已后移） | ① 带 `moved_from` 的新键**必须继承旧键**的 `exemption_started_at`，旧键不存在 ⇒ **`exemption_start_conflict` FAIL**，不得回落封条时间；② 外部上界 `exemption_started_at <= git show -s --format=%cI <L[0]>`（首签提交时间）；③ T-28 补两个前置 | §1.1.3 第 2/4 条、§7 |
| I-2（重要） | v1 回落制造假红：无封条时改过 config 根，B 首锁只写新根 ⇒ `assets_root_history_rewritten` 假红且无合法修法 | v1 版本的 config 根**只在该版本 `seal_anchors` 非空时**才进 `UH`；`lock_v1_with_seals` 从「仅当前锁」扩到「锁全历史」 | §1.1.3 第 2 条、§3.2 ⓪、§5.2 |
| I-3（重要） | `epoch_origin_history_rewritten` 只在 §8，没进判序，且只约束写侧 | 进**判序 ②**，断言「末元素 == 当前 `epoch_origin`」，元素重复/不足/超出都归该码；写侧不再有次数上限 | §1.1.3 判定优先级 ②、§8 |
| I-4（重要） | 锁解析失败与 `lock_missing` 没区分 | 新增 **`lock_unparsable`**（FAIL，⓪-0），并写明「`lock_missing` 跳过只对**文件不存在**成立」 | §3.2 ⓪、§5.2 |
| I-5（重要） | `retired` 且旧文件已删时 `lock --update --seal <旧路径>` 未定义 | 规则 3 补：`retired` 键 `n = len(L_pre)`、`frozen` 键取冻结前缀长度；HEAD 无封条时 `renewal_seq` **保留原值**，不得写 `0`/`null`；S-47b 写明「旧文件保留（接 S-31）」前置 | §1.1.3 第 3 条、§7 |
| I-6（重要） | 规则 4 没告诉写侧复制 `signed_at` | 规则 4 加「新封条 `signed_at` = `L_pre[-1].signed_at`，逐字节」（与规则 6 同源） | §1.1.3 第 4 条 |
| 次要 1 | S-47a 里「`renewal_seq`/`n` 会刷新」与 `frozen` 语义矛盾 | 改为「取值不变」（封条不可变，冻结前缀长度即 `n`） | §7 |
| 次要 2 | 交叉引用写行号，每轮漂 | §0.14 / §0.15 / §0.16 一律改「节号 + 小标题」，不写行号 | §0.14/§0.15 |
| 次要 3 | `migration_required` 无定义 | 补：WARN、exit 0、不计入 FAIL 数，并在 §5.2 码表登记 | §1.1.3 第 2 条 ⑤、§5.2 |
| 次要 4 | `assets_root_history[].commit` 语义未定 | 写明「仅审计、不参与任何断言」；首元素固定 `null`；后续元素 = **执行该次 `lock --update` 时的 HEAD**（即携带新根的锁提交的父提交） | §1.1.3 资产根 bullet |
| 次要 5 | `layout.assets_root` 缺键/config 缺失无口径 | 缺键 ⇒ 按 `_support/layout.py` 默认值 `product`；config 文件缺失 ⇒ `assets_root_changed` FAIL | §1.1.3 资产根 bullet、§5.2 |
| 收编 1 | 实现侧已补 `acceptance_cutover_mismatch`，RFC 原无此码 | 正式收编：已首次刷新后清单与锁任一侧有值且不等 ⇒ FAIL；`commit != null` 之后**两侧均缺失也算 FAIL**（同码，`detail` 分 `one_side_missing` / `both_empty`）；`acceptance_cutover == null` 只在 `commit == null` 时豁免；写侧不得写回 `null`。**（v18/阻断 3 再改：该 `commit` 一律指 `definition.commit`；两侧缺失改判 `acceptance_cutover_missing`，`mismatch` 只判「两侧有值且不等」；`acceptance_cutover` 在 v2 清单必填）** | §5.1、§7 |
| 收编 2 | `prd_schema_too_low` 判据未写死，新仓从生成当天起报 WARN 到 2027-06-30 | 按 PRD 首次提交时间（`git log --diff-filter=A --format=%aI -- <prd>`，取最早、统一 UTC）与 0.4.0 发布点比较；晚于发布点却写 `1` ⇒ FAIL；0.4.0 起模板与 `init` 直接写 `2`，`1` 只作「首次提交早于 0.4.0 **且未被 crosswalk 引用**」的存量缓冲 | §1.5 第 2 条、§6 B、§7 D-37 |
| 收编 3 | §1.5 三处执行点混在一张清单里，父仓那半边以「已实现」姿态留在 B | 分两半：成员侧 `validators/validate_prd.py` 的同一谓词 ⇒ **B 批**（不依赖 crosswalk，可立即做）；父仓按 crosswalk 扫被引用成员 PRD、缺 crosswalk 报 `evidence_columns_unbound` ⇒ **D 批**（依赖 crosswalk 落地），§1.5 明写依赖，B 清单不得再把它算作已交付 | §1.5 第 2 条执行点分层、§6 B/D |
| 收编 4 | Assumptions 节名只认英文，`## 六、假设与默认值` 被当未声明跳过 | 改为按**表头**定位：表头必须含 `假设内容` 或 `采用的默认值`（节名任意）；两种表头都命中 | §1.5 第 1 条 |
| 收编 5 | 证据列表头匹配口径未写死 | `strip()` 后**逐字比对**（fail-closed，无包含匹配口子）；错误文案提示「疑似别名」，但**只进文案、不放行** | §1.5 第 1 条 |

**v17 自查**：① 历史解析不再有 shell 管道，任一版本坏 ⇒ 停在 `lock_history_unparsable`，`UH` 不可能因解析失败而缩小；② 重指无次数上限，四条条件同时保证「从未重锚 + 只有首签」，rebase 多少次都能自助恢复，且没有载荷可洗；③ `exemption_started_at` 两头都钉住——换路径必须继承旧键、首写不得晚于 `L[0]` 提交时间，`git mv` 不再能把豁免起点往后挪；④ `lock_unparsable`、`lock_history_unparsable`、`assets_root_history_rewritten`、`assets_root_changed` 四个根层码各有独立触发面，不再互相冒充。**仍不宣称通过。**

### 0.17 第十七轮返工对照（v18）

**结论**：B-2 真闭合（上限删对了），但 **B-1 与 I-1 只是名义闭合**——v17 的参考实现仍在 `{e.root for e in ...}` 里直取字段，`[]` 静默成空集、`{root: null}` 把 `None` 塞进根集、`[{}]` 抛 `AttributeError`；`load_lock_strict` 只被引用、没有定义（现网 `1.0 in (1,2)` / `True in (1,2)` 都为真）；`acceptance_cutover` 的「已刷新」标记挂在一个不存在的 `acceptance_cutover.commit` 上。v18 把这三处按拍板意见写死，不留可解释空间。

| 编号 | 第十七轮结论 | v18 改法 | 落点 |
|---|---|---|---|
| 阻断 1 | 参考实现用集合推导直取 `.root`：`[]` 空集、`{root:null}` 塞 `None`、`[{}]` 抛 `AttributeError` | 逐元素**显式校验**（`isinstance(list)` 且非空、逐元素 `isinstance(dict)`、`d.get("root")` 是非空 `str` 且匹配字符集**——v19/阻断 1 已把「匹配字符集」换成 `layout.validate_value`，见 §0.18**），任一不满足 `raise LockHistoryUnparsable(commit=c, reason=...)`；**禁止集合推导**；S-49 断言写成「抛该异常」 | §1.1.3 第 2 条 ①（参考实现）、§7 S-49 |
| 阻断 2 | `load_lock_strict` 无定义；跨版本必需字段集未定 | 写死三句：严格解析器 = JSON 对象 + `type(schema_version) is int and not isinstance(..., bool)` 且 ∈ `{1,2}`；历史版本只校验「存在则类型与结构正确」，另加 `members` / `contracts` 为 list-of-dict 两条版本无关硬要求；当前 schema 必需集**只对当前锁**由 ⓪-3 判，历史永不要求 `definition` / `seal_anchors` / 两个根字段 | §1.1.3 第 2 条 ②、§3.2 ⓪-1 |
| 阻断 3 | `acceptance_cutover` 标记落在不存在的 `acceptance_cutover.commit`；「两侧均缺失」判据不成立 | v2 清单**必填**，`init` 与 `migrate --to 2` 都写；v1 缺省只 WARN `migration_required`；标记统一为 **`definition.commit != null`**；首次刷新后任一侧缺失或两侧皆空 ⇒ **`acceptance_cutover_missing`** FAIL，两侧有值不等 ⇒ `acceptance_cutover_mismatch` FAIL；`commit == null` 期间两侧皆空合法；删掉「空清单允许缺省 cutover」的旧口径 | §5.1、§8 |
| 重要 1 | T-28 用 `%cI L[0]` 当主判据，但 committer date 可被改写 | 主判据改为 **`exemption_started_at` 与 `L[0]` 封条 `signed_at` 逐字节相等**（封条字节被链规则钉住、可复算）；`%cI L[0]` 降为 WARN/INFO，§8 明说不可证 | §1.1.3 第 2/3/4 条、§3.2 第 10 条、§7 T-28、§8 |
| 重要 2 | `prd_schema_too_low` 没有常量和武装条件 | 常量名写死 `PRD_SCHEMA_2_FROM`；`reader_version >= 0.4.0 && PRD_SCHEMA_2_FROM is None` ⇒ 新码 **`prd_schema_gate_unarmed`** WARN；发版门要求 tag 日期与常量一致，不一致 ⇒ FAIL | §1.5 第 2 条、§5.2 码表、§7 D-37/D-38 |
| 重要 3 | ⓪ 抢码：⓪-0 失败后仍去算 `UH`；解析层承担了当前锁的 schema 判定 | ⓪-0 失败**显式短路**（不算 `UH`、不判 ⓪-1…⓪-4）；解析层只管 JSON / 类型 / 空数组 / 元素 `.root`，当前锁的「根重复 / 字符集 / `layout != last`」**只由 ⓪-3 判**；写明 `[]` 归解析层（当前锁 ⇒ ⓪-0，历史 ⇒ ⓪-1）；S-43/S-48 的首报断言按新顺序改（**该行的「字符集只由 ⓪-3 判」已被 v22/B-1 取代**：词法下沉到 `load_lock_strict`，⓪-3 不再判字符集，见 §0.21） | §3.2 ⓪、§7 S-43/S-48 |
| 重要 4 | 读取层把「不存在」与「存在但 `show` 失败」混为一谈 | `git show` 前先 `git cat-file -e <c>:atlas.solution.lock.json`：存在却失败 ⇒ `lock_history_unparsable`；不存在才 `continue`。shallow/partial 判定**移回 ⓪ 之前**（作为第 0 步先执行） | §1.1.3 第 2 条 ①、§3.2 判序 |
| 重要 5 | `evidence_columns_*` 标了「0.4.0 起」，但 0.4.0 并没有这个门 | 改为「**crosswalk 落地版本起**」；成员侧期限判据仍按 PRD 首次提交与 0.4.0 比较，两者不再混写 | §1.5 第 2 条、§6 D |
| 次要 1 | v1 回落分支已是死代码 | 写成「**v1 版本一律不贡献根**」；删 `config_root_at` 与「v1 回落缺 config ⇒ `assets_root_changed`」整句 | §1.1.3 第 2 条 ①③ |
| 次要 2 | `1 + 重指次数` 没有计数口径 | 重指次数 = **锁历史逐版本比较 `epoch_origin` 发生变化的次数**，不得用数组自身长度反推 | §1.1.3 第 3 条、§8 |
| 次要 3 | 规则 4 的继承只写「旧键」 | 改为「**沿 `moved_from` 递归到链首，与链首键的值相等**」；中途缺键先报 ① `seal_anchor_path_unmapped`；「旧键不存在 ⇒ `exemption_start_conflict`」降为 `detail` | §1.1.3 第 4 条、§7 T-28 |
| 次要 4 | `lock_missing` 时历史有坏版本落哪个码没写 | 明确：`lock_missing` **只跳过 ⓪-0 与两条根断言**，⓪-1 仍执行 ⇒ 坏版本落 `lock_history_unparsable` | §3.2 ⓪ |
| 次要 5 | D-37 的 `%aI` 被当成证明 | 注明「author date 可被 `--date` 伪造，只作判据、不作证明」 | §1.5 第 2 条、§7 D-37 |

**v18 自查**：① 参考实现对每个元素做 `isinstance` 与类型/字符集断言，`[]` / `{root:null}` / `[{}]` / 坏 JSON 全部 `raise`，没有集合推导；② `load_lock_strict` 有可执行定义，历史版本不要求当前字段，`1.0` 与 `True` 被显式排除；③ `acceptance_cutover` 的「已刷新」只有一个标记（`definition.commit != null`），缺失与不等分属两码，pending 态只剩「两侧皆空」一种合法形态。**仍不宣称通过。**

### 0.18 第十八轮返工对照（v19）

> 第十八轮结论：v18 的三条阻断**真闭合**；新增 3 阻断 + 5 重要 + 5 次要。本轮按下面拍板写。

| 编号 | 第十八轮结论 | v19 改法 | 落点 | 反面包 |
|---|---|---|---|---|
| 阻断 1 | 根字符集双源：RFC 自造 `ROOT_RE`，`layout.py` 不禁中文/空格 | 检查器**直接调** `_support/layout.py` 的 `validate_value(root, "assets_root", s)`；RFC 不定义第二套字符集；`ROOT_RE` 只作「新增根」的写侧建议，**不作判据**；存量根按 `layout.py` 既有合法性 grandfathering | §1.1.3 ②④⑫、§3.2 ⓪-3、§8 | S-51（正）、S-52（负） |
| 阻断 2 | `migrate --to 2` / `init` 的 cutover 值无来源、无门槛 | 无 `--cutover` ⇒ 默认 `2027-03-31` 并 stdout 打印；`--cutover` 晚于默认 ⇒ 必须 `--anchor-review <REVIEW-ID>` 且 ≤ 默认 + 90 天；首次写入晚于默认且无 review 记录 ⇒ `acceptance_cutover_unreviewed` FAIL；B-0 `migrate` 增参并进文件表 | §1.1.3 清单字段、§5.1、§5.2、§6 B-0 | V-20、D-40 |
| 阻断 3 | 第 0 步可被 `--allow-unverifiable-chain` 降级 | 第 0 步 hard FAIL，**移出降级清单**；窄开关只降「对象本地缺失」；放宽的唯一形态是「整段跳过 ⓪ 与第 1 步、路径级/根级全 SKIP」；`cat-file -e` 换 `cat-file -t`，区分对象缺失（`chain_unverifiable`）与路径不存在（`continue`） | §3.2 第 0 步、⓪-1、第 9 步、§8 | S-14、V-21 |
| 重要 1 | ⓪ 失败后仍可能进第 1 步、`UH` 未定义 | 「⓪ 任一项 FAIL ⇒ `check` 立即 exit 1 结束，`errors[]` 只含该码，不进第 1 步」 | §3.2 前置、§5.2 | S-50 |
| 重要 2 | 异常逃逸到顶层，`--json` 可能不是合法 JSON | `check` 顶层 `try/except (LockParseError, LockHistoryUnparsable)` ⇒ `{code, message, path}`、exit 1；S-49 断言改成 `errors[].code` + 合法 JSON + exit 1 | §3.2、§7 | S-49 |
| 重要 3 | 发版门只有文字，没有可执行项 | 落成 `tests/test_release_gate.py`（或 `scripts/release_check.py`）：`PRD_SCHEMA_2_FROM` 非 None 且等于发布 tag 的 UTC 日期；武装条件含 prerelease（`>= 0.4.0-0`） | §1.5、§6 B、§7 | D-40 |
| 重要 4 | D-37 依赖常量置值，不能进 B 验收 | D-37 标「发布后夹具」，从 B 验收清单摘出；D-38 保留并注明「正式版 + 未武装常量」是不该存在的配置 | §6 B、§7 | D-37 / D-38 |
| 重要 5 | `lock_missing` 下 `git log` 失败被混进 `lock_history_unparsable` | `git log` 非零按「无历史」处理，但同遍报 `chain_unverifiable` FAIL；`lock_history_unparsable` 只留给「对象在、字节坏」 | §3.2 ⓪-1、§8 | V-21 |
| 次要 1 | `members`/`contracts` 两种口径 | 当前锁必须两者齐备（⓪-0 判）；历史版本「存在则校验」——写死一条，不留两种 | §1.1.3 ②、§3.2 ⓪-0 | S-50 |
| 次要 2 | v1 不贡献根的理由依附 ⓪-2 | 换成结构原因：`lock_payload` 只在清单 v2 时写两个根字段，v1 锁里根本不存在该字段 | §1.1.3 ③、§8 | — |
| 次要 3 | `UH` 未说可达性 | 明说「只信 HEAD 可达历史」，orphan / 已删分支上的锁版本不进 `UH` | §1.1.3、§3.2 符号表、§8 | S-53 |
| 次要 4 | T-28 的「逐字节相等」没有归一化口径 | `signed_at` 写死 `YYYY-MM-DDTHH:MM:SSZ`（UTC、`Z` 后缀、无小数秒）；比较按该形态逐字节 | §1.1.3、§3.2、§7 T-28、§8 | T-28 |
| 次要 5 | D-39 的「清单有、锁缺」可能被误读为常规写侧形态 | 注明是人工篡改形态，不是常规写侧路径 | §7 D-39 | D-39 |

**v19 自查**：① 全文不再有第二套根字符集**判据**——`ROOT_RE` 只以「写侧建议」身份出现（对照表、§1.1.3 ⑫、参考实现注释），任何 FAIL / PASS 都不由它得出，`layout.validate_value` 是唯一判据；② cutover 的默认值、打印、review 门槛、90 天上限、`acceptance_cutover_unreviewed` 五件事都落在 §5.1，B-0 文件表含 `--cutover` / `--anchor-review`；③ 第 0 步与 `chain_unverifiable` 的降级关系只有一种写法（hard FAIL、按 `cause` 只降 `object_missing`），`cat-file -t` 的两段判据写进 ⓪-1。**仍不宣称通过。**

### 0.19 第十九轮返工对照（v20）

> 第十九轮结论：三条阻断的规则侧都真闭合，但两条在**实现落点**上还有硬伤。本轮只按下面拍板写，不再留可解释空间。

| 编号 | 第十九轮结论 | v20 改法 | 落点 | 反面包 |
|---|---|---|---|---|
| 阻断 1 | `historical_roots()` 调带 FS 的 `validate_value`，其 `candidate.resolve()` + `relative_to()` 依赖**今天的工作树**；历史根今天变成仓外 symlink / 普通文件即永久 `lock_history_unparsable`，append-only + 禁归一化没有出口 | `layout.validate_value` 拆两层：`lexical=True` 只做 strip / 绝对路径 / `..` / 保留首段 / 字符规则，**零 FS**；默认版保留 FS 检查，供 `install.py` 写入与 ⓪-3 的**当前根**；`historical_roots()` 与 S-52 历史分支**只用 lexical**；根字符串**首尾空白一律判红**（解析层即拒、写侧同样拒），理由写明「校验用 strip 后串、入集合用原串」会使 glob 匹配不到。**v21 修**：v20 的「⓪-3 每个根严格版」与 append-only 冲突，改为**末元素严格、其余 lexical**（§0.20/B-1） | §1.1.3 ②④、参考实现、⓪-1、⓪-3、S-51/S-52 | S-51（+3 变体）、S-52；**v21 正文落点：L580（§1.1.3 ②）、L1261（⓪-3）、L655（`_root_by_index_ok`）、L1842（S-51）** |
| 阻断 2 | `<c>` 来自 `git log`，对象必然在本地 ⇒ ⓪-1 的 `object_missing` 是死分支；可达的是文件里写的 SHA | `--allow-unverifiable-chain` 的 `object_missing` **只对 `definition.commit` 生效**（降 WARN + `downgrades[]`、`scope=definition_source`）；`epoch_origin` / `previous_seal_commit` / `anchor_review` 对象缺失**一律 FAIL、不受开关影响**，理由写死「那是封条链的锚，缺失等于链不可证，不接受自述降级」；第 0 步 / ⓪-0 / ⓪-1 同样不降。**v21 修**：删 ⓪-1 残留的「这支受窄开关降级」，补**作用点白名单**（§0.20/B-2） | §3.2 第 0 步、前置段、第 9 步、报告 schema | V-21（两变体）；**v21 正文落点：L1254（第 0 步白名单）、L1872（V-21）** |
| 重要 1 | V-20 自相矛盾：`2027-06-30` 同时被要求 PASS 和 exit 2 | PASS 分支日期改 `2027-05-15`（> 默认、≤ 上限），`2027-06-30` **只作超限反例**；边界写死「**等于上限算通过**」；90 天用 `date(2027,3,31) + timedelta(days=90)` 算式表达，**不写死 `2027-06-29`** | §5.1、V-20 | V-20 |
| 重要 2 | review 是自述，未写明 | `acceptance_cutover_review` 与 `assets_root_history[].review` 都**只判 `REVIEW-\d{8}-\d{2}` 形态、不做台账查询**；同一 ID 用于两次不同决策（改根 + 改 cutover）⇒ 新码 **`review_reused`** FAIL | §1.1.3 ⑫、§5.1、§8 | **S-54（新）** |
| 重要 3 | ⓪ 短路后 `--json` 可能不完整 | `errors` 只含该码，但 `warnings` / `skipped` **照常输出**，未执行的段进顶层 `not_run[]`；stdout 不得为空、不得只有一条而无结构 | §3.2 ⓪-0、报告 schema | S-49/S-50 |
| 重要 4 | `signed_at_not_canonical` 未进码表、无夹具、写侧口径缺失 | 进码表（**FAIL、exit 1**）、补夹具、进 §8；写侧生成函数**单源** `strftime("%Y-%m-%dT%H:%M:%SZ")`、**禁 `isoformat()`**；加「写侧只产 `...Z`」夹具；**不设 grandfathering**——C 尚未上线、HEAD 里不存在已入库封条，规则生效即 fail-closed，理由写进正文。**v21 修**：续签口径改「重写」（§0.20/I-3），`exemption_start` 的细分原因另起码（次要 3） | §3.2 规则 0/§5.2 登记/§8、T-28/**T-29（新）** | T-28 / T-29；**v21 正文落点：L1597（§5.2 第 13 条）、L1904（§8）、L1778（T-29）** |
| 重要 5 | D-40 的 skip 语义未写 | 无 tag 或常量未武装 ⇒ `pytest.skip(reason=...)`；仅 `GITHUB_REF_TYPE=tag` 且 tag 匹配 `v0.4.0*` 时执行断言 | §6 B、D-40 | D-40 |
| 次要 1 | S-53 未说 merge | 注明「**merge 带入的祖先仍算 HEAD 可达**」 | §7 S-53、§8 | S-53 |
| 次要 2 | 历史版本缺 `members`/`contracts` 的口径 | 视为**旧工具产物放行**，不报 `lock_unparsable`（当前锁仍必填） | §1.1.3 ②、⓪-1 | S-50 / S-49 |

**v20 自查**：① `historical_roots()` 与 S-52 历史分支只走 `validate_value(..., lexical=True)`，参考实现里 `_root_lexical_ok` / `_root_fs_ok` 分列，⓪-3 的当前根才走严格版，S-51 用「历史目录已删」「历史根换成仓外 symlink」两个变体证明不因今天的工作树判红；② `object_missing` 的降级只出现在 `definition.commit` 一处，封条链的 `epoch_origin` / `previous_seal_commit` / `anchor_review` 一律 FAIL，V-21 用两个变体分别钉住；③ V-20 的 PASS 与反例不再共用日期，90 天是算式；④ `signed_at_not_canonical` 有码、有夹具、有写侧单源、无 grandfathering 理由。**仍不宣称通过。**

### 0.20 第二十轮返工对照（v21）

> 第二十轮结论：V-20 六分支真闭合、`not_run[]` 真闭合（枚举小缺口），但 **v20 不能作为 B-0 基线**。本轮不新增设计，只修实现落点与批次归属。

| 编号 | 第二十轮结论（复算要点） | v21 改法与正文落点 |
|---|---|---|
| B-1 | ⓪-3「当前锁 `assets_root_history` **每个根**过严格版」与 append-only 冲突；数组历史根永在，而严格版对仓外 symlink / 普通文件必拒 ⇒ S-51② 在 v20 文字下必红（`/tmp` 实测：lexical ACCEPT、strict REJECT） | ⓪-3 改「**`layout_assets_root`（数组末元素）走严格版，其余元素一律 `lexical=True`**」；规范句与参考实现同步；**按索引取末元素**，不按值匹配（同值重复无法用值区分）。落点：§1.1.3 ②、§3.2 ⓪-3、§1.1.3 参考实现 `_root_by_index_ok` |
| B-2 | ⓪-1 残留「`git cat-file -t <c>` 失败 ⇒ `chain_unverifiable`（这支才受窄开关降级）」与另外四处相反；降级仍按 `cause` 不按作用点，实现者照写会把封条链锚一起降 | 删该尾巴，改为「**⓪ 层任何 `object_missing` 都不受窄开关影响，一律 FAIL**」；降级判据补**作用点白名单**：仅「校验点 = `definition.commit` **且** `scope == definition_source`」两项同时成立才降，白名单显式列出、白名单外即使 `cause == object_missing` 也 FAIL。落点：§3.2 第 0 步 / 前置段 / 第 9 步、V-21② |
| B-3 | `git show 411c971:_support/layout.py \| grep lexical` 无匹配；模块只是未提交工作树改动；B-0 文件表与 §10 都不含它 ⇒ 干净基线 `TypeError`，而顶层只捕三个异常 ⇒ traceback 逃逸 | `_support/layout.py` **进 B-0 文件表**，条目写「`_validate_rel_path(..., lexical=False)` 新增参数 + `validate_value` 透传 + **首尾空白在 `strip()` 之前拒**」；§10「不碰实现」加例外条款；顶层异常转换扩成「已知异常按码、**未知异常 → `internal_error` + exit 2**，不吐 traceback」。落点：§6 B-0 文件表、§10、§3.2 报告 schema |
| I-1 | `layout.py:293` 的 `raw = value.strip()` 两层都静默归一化 ⇒「写侧双拒」只兑现解析层 | `_validate_rel_path` 在 `raw = value.strip()` **之前**先比 `value != value.strip()` 直接拒（不动 `ROOT_RE`）；写侧 `install.py --assets-root` / `lock --update --assets-root` 语义为「**拒，不 trim**」。落点：§1.1.3 ②、§6 B-0 文件表、S-52 |
| I-2 | 当前根空白在参考实现落 `lock_unparsable`，但 S-52⑤ / §8 期望 `assets_root_history_rewritten` | **以参考实现为准**：当前锁任何根不合法（含空白）⇒ `lock_unparsable`（⓪-0）；历史版本 ⇒ `lock_history_unparsable`；补「⓪-0 吸收当前锁全部结构性与词法性错误」。落点：§3.2 ⓪-0、§8、S-52⑤ |
| I-3 | §5.2 说「续签逐字节复制旧值」、§8 说「续签才由工具重写」，自相矛盾 | 续签**重写**（新封条自己的签署时刻，写侧单源 `strftime`）；**换路径**才沿用旧值。T-29 的规范性对**当前锁全量 `L`** 判（`L[0]`、HEAD 封条、中间续签全查）（**该句已被 v22/I-2 取代**：`L` 是提交序列、不在锁里，校验点改为链上每枚封条 blob 的 `signed_at`，见 §0.21）。落点：§5.2 第 13 条、§8、T-29 |
| I-4 | `--cutover` / `--anchor-review` 是 B-0 交付，但 V-20 只在 C 批夹具段；S-54 依赖 C 批 `lock --update --assets-root` | V-20 **移进 B-0 夹具清单**；S-54 拆两半——**B-0** 只验 `review_reused` 形态判定（用清单字段构造），**C** 验「换根后 review 复用」；批次归属表逐个夹具标批次。落点：§6 B-0 夹具、§7 S-54 |
| I-5 | §0.19 行 472/473/477 写「已改」，正文没到位 | 三行已重写并指到 §0.20；正文落点行号在 v21 定稿后统一标注（§1.1.3 ②、§3.2 ⓪-3、§5.2 第 13 条、§8） |

**v21 自查**：① ⓪-3 的唯一判据是「按索引取末元素严格、其余 lexical」，S-51 的「目录已删」「仓外 symlink」「普通文件」三变体都只走 lexical；② 降级的白名单是两项合取，V-21② 的断言引用的正是这条正文；③ `_support/layout.py` 在 B-0 文件表有独立条目、§10 有例外、顶层有 `internal_error`；④ 空白在 `strip()` 之前拒，写侧语义「拒，不 trim」，S-52 覆盖写侧；⑤ 当前锁空白归 `lock_unparsable`、历史归 `lock_history_unparsable`，S-52⑤ 与 §8 已对齐；⑥ 续签重写 / 换路径沿用；⑦ V-20 在 B-0、S-54 拆两半；⑧ `not_run[]` 补 `root_v1_check`、四个数组都有排序键。**仍不宣称通过。**

### 0.21 第二十一轮返工对照（v22）

> 第二十一轮结论：v20 那三个阻断全部真闭合，但 v21 修 I-2 时新造了一个阻断（B-1）。本轮只修规则面与实现落点，不新增产品决策（I-6 除外，它是设计修正）。

| 编号 | 第二十一轮结论（复算要点） | v22 改法与正文落点 |
|---|---|---|
| B-1（阻断） | 同一输入（当前锁元素 `../product`）在四处被分给两个码：§1.1.3 ④ 说「解析层不判字符集，全交 ⓪-3」；⓪-0 说「吸收当前锁全部词法错误」；⓪-3 说「只判字符集」；参考实现 `load_lock_strict` 只判 `str` / 非空 / 空白，**没调 `validate_value(..., lexical=True)`** ⇒ S-52④ 与 §6 C 断言 `lock_unparsable`，按参考实现跑落 `assets_root_history_rewritten` | **词法进 `load_lock_strict`**：当前锁（`current=True`）对每个 `assets_root_history` 元素调 `validate_value(..., lexical=True)`，失败 ⇒ `LockParseError`（⓪-0 `lock_unparsable`）；历史版本（`current=False`）同一函数、只对「可读为字符串」的元素跑 lexical，失败 ⇒ `LockHistoryUnparsable`（⓪-1）。删掉 §1.1.3 ④ 的「不判字符集」与 ⓪-3 的「只判字符集」；⓪-3 从此只判 `layout == last` / 按索引分层 / `UH` 包含 / 重复。参考实现同步，`_root_by_index_ok` 写明「入参已过词法层」。落点：§1.1.3 ④、§1.1.3 参考实现、§3.2 ⓪-0 / ⓪-3 |
| I-1 | S-51 只写「历史根已删 / 仓外 symlink / 普通文件 ⇒ 仍 PASS」，但按索引分层只有 `hist[:-1]` 走词法，symlink 与普通文件在严格版下都被拒 ⇒ 缺构造条件 | S-51 补构造约束：「被破坏的根必须位于 `hist[:-1]`，数组末元素为更新后的当前根」，三个变体各自写明该根是第几个元素。落点：§7 S-51 |
| I-2 | T-29 的「当前锁全量 `L`」是范畴错误：`L` 是封条提交序列、不在锁里；中间续签要改必须重写历史，`previous_seal_commit` / `blob@L[0]` 会先红 | 校验点改为「链上每枚封条 blob 的 `signed_at`（读侧从 `previous_seal_commit` 逐级取 blob）」；夹具只钉两态——N=1 时 amend 唯一封条（覆盖 `L[0]`）、N>1 时 amend HEAD；中间续签明确标「不可构造（改它必先破坏 `previous_seal_commit`）」。读侧进 §6 C 验收清单。落点：§7 T-29、§6 C |
| I-3 | `exemption_start_signed_at_not_canonical` 四处缺一（码表 / §8 / §7 有，§5.2 的 `code` 取值集只写「两枚」、§6 C 只写 `exemption_start_conflict`），且 T-28 的 `detail` 仍留 `not_canonical_or_mismatch` | `code` 取值集按实际枚数逐个列名（不写计数句）；§6 C 补新码；T-28 删 `detail` 的 `not_canonical_or_mismatch`，一个输入只出一个码。落点：§5.2 第 13 条、§6 C、§7 T-28 |
| I-4 | `except Exception` 会把 `--lenient` 拒绝、cutover 超限、半写失败一并转成 `internal_error` + JSON，与「`--lenient` 的 exit 2 首行不是 JSON」打架 | 处理顺序写死：`SolutionError` 在最外层**先于**通用 `except` 捕获并原样上抛；用法错误在最外层 try 之外；只有三类自有异常 + `SolutionError` 之外的真异常才走 `internal_error`。`internal_error` 进 §5.2 码表。落点：§3.2 报告 schema、§5.2 第 13 条 |
| I-5 | V-20⑥ 要求 `check` 报 `acceptance_cutover_unreviewed`，但 B-0 文件表的 `_support/solution.py` 条目没写 cutover 谓词 | `validate_manifest` 条目加「含 `acceptance_cutover` 取值校验与 review 谓词」，让 B-0 有落点、不必等 B 批。落点：§6 B-0 文件表 |
| I-6（改设计） | reanchor / squash 后 `L[0]` 重写 ⇒ `exemption_started_at`（指向旧 `L[0].signed_at`）永久红且无出口；`moved_from` 只覆盖换路径 | 拆两个键：**`exemption_start_origin`**（建键写死、任何路径都不改写，`gap.due` 的**下界**取它；v23/I-3 起 due 是区间、上界取 `first_seen_origin + 90d`）；**`exemption_started_at`**（主判据「逐字节等于当前 `L[0].signed_at`」保留，允许 `seal reanchor` 同步重指，重指必须 append `exemption_start_history[]` 元素 `{from, to, commit}`；断裂 ⇒ `exemption_start_history_broken` FAIL）。落点：§1.1.3 键表与参考样例、§5.1、§5.2 第 13 条、§7 T-28 与 S-55、§8 |
| 次要 1 | 降级白名单的「校验点」不是字段，外部审计无法靠码反推 | 把「校验点 == `definition.commit`」映射成 `code` 值 `definition_commit_unverifiable`（与 `scope: definition_source` 合取），写进 §3.2 报告 schema 的 `downgrades[]` 定义 |
| 次要 2 | `scope` 枚举是 `{definition_source, card_absent, reader_version}` 三值（`chain` 已删） | 正文已按三值写；验收口径不写「只剩一个值」。§3.2 报告 schema 明写「**三值**」 |
| 次要 3 | `internal_error` 路径的 `not_run[]` 没口径 | 补「已跑到第几步、`not_run` 填剩余段」。落点：§3.2 报告 schema |
| 次要 4 | `_root_by_index_ok` 对空数组 `hist[-1]` 会 `IndexError` | 加 `if not hist: return False`（已落参考实现） |
| 次要 5 | `internal_error` 未进 §5.2 码表 | 与 I-4 同源，一并登记。落点：§5.2 第 13 条 |

**v22 自查**：① 当前锁词法失败只有一条路（`load_lock_strict(current=True)` ⇒ `lock_unparsable`），⓪-3 不再判字符集；历史版本词法失败只有一条路（`current=False` ⇒ `lock_history_unparsable`）；② S-51 三个变体都写明「被破坏的根是第几个元素，末元素是当前根」；③ T-29 的校验点是封条 blob 的 `signed_at`，`L` 只作为「按序取 blob 的路径」；④ `exemption_start_signed_at_not_canonical` 在码表 / §6 C / §7 / §8 四处同名，T-28 单码；⑤ `SolutionError` 在 `except Exception` 之前；⑥ `exemption_start_history_broken` 有码、有夹具、有 §8 残余口径。**仍不宣称通过。**

### 0.22 第二十二轮返工对照（v23）

> 第二十二轮结论：**B-0 面四项真闭合，v22 可作 B-0 开工基线**；整份 RFC 还剩 1 阻断 + 5 重要 + 6 次要，全部集中在 `exemption_start_*` 这组规则。本轮只做规则收口，不新增产品决策。

| 编号 | 第二十二轮结论（复算要点） | v23 改法与正文落点 |
|---|---|---|
| B-1（阻断） | `exemption_start_signed_at_not_canonical` 码义互斥：`§1.1.3` 旧定义把「`exemption_started_at` 与 `L[0].signed_at` 不等」算进本码，T-28(c) 把纯等值不等归 `exemption_start_conflict`，T-28③ 手改成规范但不等的值 ⇒ 两条断言必有一侧红 | **码义单点**：本码**只罚形态**（`exemption_started_at` 或 `L[0].signed_at` 本身不规范，含后者非法）；等值不等**一律** `exemption_start_conflict`。码表、§3.2 判序 ②、T-28 优先级 (a)(c)、§8 四处同口径。落点：§5.2 第 13 条、§3.2 ②、§7 T-28、§8 |
| I-1 | `exemption_start_history` 的 append-only 无外部锚，唯一外部锚是末项 `to == started_at == L[0].signed_at`，单次提交整段重写可自洽；「origin 堵住延后 due」不成立——due 只有下界 `> origin`，真正延后出口是上界 `min(first_seen_at + 90d, cutover)`，而 reanchor 时 `L[-2]` 不可读、`first_seen_at` 只靠写侧原样保留 | ① `exemption_start_origin` 期望值 = **锁历史中该键最早出现版本**的值，不等 ⇒ 新码 `exemption_start_origin_rewritten`；② `exemption_start_history[]` 改判**版本前缀单调**，断裂 ⇒ `exemption_start_history_broken`；③ 新增锁键 **`first_seen_origin`**（建键写死、不可改写），`due` 上界改 `min(first_seen_origin + 90d, cutover)`，同样以锁历史最早版本为锚 ⇒ 新码 `first_seen_origin_rewritten`；`first_seen_at` 降为审计；④ 存量回填见 I-2。**四处统一口径写在 §1.1.3「资产根」⑦**。落点：§1.1.3 ⑦ 与四个键条目、§5.1 第 3 条、§5.2 第 13 条、§6 C、§7 T-30、§8 |
| I-2 | 存量回填被「任何命令都不改写」抵消：§1.1.3 有回填出口，但规则 3 / reanchor / §8 / S-55 都写「不动」「不得改写」 | 四处统一为「**已有值不改写；缺失时一次性回填（§1.1.3 第 3 条）**」。§6 C 加回填夹具 T-30④（老锁缺三个字段 ⇒ `lock --update` 后补齐且值等于原 `started_at`）。落点：§1.1.3 `exemption_start_origin` / `history` / `first_seen_origin`、规则 3 / 4、§3.2 reanchor、S-55、§8、T-30④ |
| I-3 | 全文没有 `origin ≤ started_at`；`origin > started_at` 不产生任何码；「due 只从 origin 算」措辞夸大（真实只有下界） | 加 `exemption_start_origin ≤ exemption_started_at`（违反 ⇒ `exemption_start_history_broken`，T-28⑦ / 码表 (d)）；§1.1.3、§5.1、§8 的措辞统一为「**下界取 origin、上界取 `first_seen_origin + 90d`**」。落点：§1.1.3 `exemption_started_at` / `history[]`、§5.1 第 3 条、§8 |
| I-4 | C 批文件表只把 `seal freeze` / `lock --update --assets-root` 写成入口，漏了 `seal reanchor --review --from-a`——它才是 `exemption_start_history[]` 的唯一写入口 | §6 C 文件表补 `seal reanchor --review <REVIEW-ID> --from-a <sha>`，并写明封条签发 / 续签由 `atlas_apply_seal.py` 承担。落点：§6 C |
| I-5 | S-55 前置引 S-31（换路径）——S-31 不产生「旧 A 不可达」，按 S-31 接续会被 `reanchor_not_allowed` 拒，三个子变体造不出来 | S-55 改引 **S-26**（reanchor → 后置 `lock --update` 独立提交），这是真实 reanchor 前置；子变体 ① 同时是「版本前缀单调」的删项变体。落点：§7 S-55 |
| 次要 1 | ⓪-3 自称「只判四项」，同段还判数组非空 / 首尾空白 / 对 `hist[:-1]` 再跑 lexical——后两者解析层已判，永不可能触发 | 收口成「解析层已判，这里只做防御性复核」；四项定义性判据逐条写明，防御性复核不列为触发条件。落点：§3.2 ⓪-0 / ⓪-3 |
| 次要 2 | `internal_error` 四处只齐两处（码表、`code` 取值集），§6 / §7 无夹具、§8 无条目 | 新增 T-31 夹具（未知异常 ⇒ exit 2 + 合法 JSON + `not_run[]` 完整；`SolutionError` 走业务码；用法错误 stdout 非 JSON）；§6 C 与 §8 各补一条。落点：§6 C、§7 T-31、§8 |
| 次要 3 | exit 2 双语义（纯文本 vs JSON）在 schema 里没写「消费方按首字符区分」 | §3.2 报告 schema 补一段：首字符 `{` ⇒ 按 JSON 解析；否则按人类可读文本；不得只看 exit code。落点：§3.2 |
| 次要 4 | `history[].commit` 语义（「执行命令时的 HEAD」与「即 R0 的父提交」等价但易误读） | §1.1.3 字段说明直接写死「**`R0` 的父提交**」；§3.2 reanchor 同步该措辞。落点：§1.1.3、§3.2 |
| 次要 5 | T-28④ / 码表里「`from` 不等于重指前的值」不可判（没有旧值记录，只能靠链自洽） | 删该分句，只保留链自洽与外部锚（origin / first_seen_origin）。落点：§5.2 第 13 条、§7 T-28 |
| 次要 6 | S-52⑤ 的「写侧不 trim」只在 C 批，实测当前 `layout.py` 对 `" product"` / `"product "` 两层都 ACCEPT（`raw = value.strip()` 在前） | 该断言标成 **B-0 交付即验**（§6 B-0 文件表已列 `_support/layout.py`），不是既有行为。落点：§7 S-52⑤ |

**v23 自查**：① `exemption_start_signed_at_not_canonical` 只罚形态，`exemption_start_conflict` 只罚等值，T-28(a)(c) 与码表同口径；② `exemption_start_origin` / `first_seen_origin` 都以锁历史最早版本为锚，各有 FAIL 码、夹具（T-30①②）、码表行、`code` 取值集、§8 条目；③ `exemption_start_history[]` 有版本前缀单调 + T-30③ / S-55 三变体；④ 回填口径在 §1.1.3 / 规则 3、4 / `seal reanchor` / S-55 / §8 五处一致（已有值不改写、缺失回填），并有 T-30④；⑤ `origin ≤ started_at` 进码表 (d)、T-28⑦、§1.1.3、§3.2 ②；⑥ `seal reanchor` 进 §6 C 文件表；⑦ S-55 改引 S-26；⑧ `internal_error` 四处齐备（码表 / `code` 取值集 / T-31 + §6 C / §8）；⑨ exit 2 按首字符区分；⑩ `history[].commit` = `R0` 的父提交；⑪ 删「`from` 不等于重指前的值」；⑫ S-52⑤ 标 B-0 交付即验。**仍不宣称通过。**

### 0.23 第二十三轮返工对照（v24）

> 第二十三轮结论：**B-0 仍可开工（B-0 面未受影响），C 批不能开工**。本轮只收口 `exemption_start_*` 的码辖区、存量锚、⑦ 判据形态、S-55 前置与 `due` 读侧码，不新增产品决策。

| 编号 | 第二十三轮结论（复算要点） | v24 改法与正文落点 |
|---|---|---|
| B-1（阻断） | `:1676` 写「本码专指 `exemption_started_at` **或 `L[0].signed_at`**」，T-28(a) 同；但 T-29②(i)（`N == 1` amend 唯一封条即覆盖 `L[0]`）期望 `signed_at_not_canonical` ⇒ 同一输入两个码辖区重叠 | **职责正交（修法 a）**：① `signed_at_not_canonical` = **封条 blob 的通用形态检查**，覆盖链上所有 blob **含 `L[0]`**；② `exemption_start_signed_at_not_canonical` **只管锁里的 `exemption_started_at` 字面值**，不管任何封条；③ §5.2 删「`L[0].signed_at` 归本码」、T-28(a) 同步只写 `exemption_started_at`，T-29②(i) 维持 `signed_at_not_canonical`；④ **补优先级**：形态判据先于等值判据，`exemption_started_at` **或** `L[0].signed_at` 任一形态失败 ⇒ **跳过等值比较、不报 `exemption_start_conflict`**（避免连锁双码）。落点：§5.2 第 13 条、§3.2 判序 ②、§7 T-28 / T-29、§8 |
| B-2（阻断） | 锚被四处写成「**首个含该键的版本**」（`:1679`、`:1680`、`:1994`、⑦ `:636`），但存量键那一版不含新字段 ⇒ 永远落「缺字段回填」⇒ 回填后锚不前进 ⇒ `exemption_start_origin_rewritten` / `first_seen_origin_rewritten` **永不 FAIL**（死码）；T-30①② 跑新建键，发现不了 | **锚改成「首个同时含该字段的版本」**（存量键即回填提交）；补 **T-30⑤**——`lock --update` 回填后再单次提交把 `first_seen_origin` 改成今天 ⇒ 必 FAIL，`exemption_start_origin` 同构变体一并补；**如实写残余风险**：存量键锚落在回填提交上，回填值取自当时不可证的 `first_seen_at`，所以「回填那一刻就写晚」检测不到；`exemption_start_origin` 的回填值受 T-28① 钉在 `L[0].signed_at` 上，比 `first_seen_origin` 硬一档。落点：§1.1.3「资产根」⑦ 与三个键条目、§5.2 两行、§6 C、§7 T-30、§8 |
| I-1（重要） | ⑦「四处同一写法」名不副实：开头写「凡是只许 append / 不改写的锁内值，期望值一律取最早版本」，但 ① `assets_root_history` 判「包含历史**并集** `UH` + `layout == hist[-1]`」，② `epoch_origin_history` 判「末元素 == 当前值 + 长度 == 1+重指次数」（换掉中间元素仍通过） | ⑦ **拆成四类写法**——标量（取首个同时含该字段的版本的值）、数组 A（`UH` 并集 + `layout == hist[-1]`）、数组 B（末元素 == 当前值 + 长度 == 1+重指次数）、数组 C（版本前缀单调 + 相邻至多一项）；并明确**「append-only 只是叙述，判据以上述四条为准」**。**正文判据不动**（`--full-history` 与并集都保留）。落点：§1.1.3「资产根」⑦、§8 |
| I-2（重要） | S-55 前置仍差一层：S-26 只给「后置 lock 独立提交」，不做 reanchor 构造（真正的构造在 S-18）；① 的「3 条历史删第 2 条」不可构造——`:257` 已写「第二个纪元之后的局部重写无解」，3 条需 3 次 `seal reanchor` | S-55 前置改成「**S-18 的构造 + S-26 的后置 lock**」；① 降到「**2 条历史删第 1 条**」。落点：§7 S-55 |
| I-3（重要） | `due` 越界在读侧没有码（`:1156` 已把 `due` 收成闭区间两端都含，写侧拒签有 T-03 / S-08，读侧无码）；回填 `origin = 当前 exemption_started_at` 还能主动造出越界（`started_at` 被 reanchor 重指过 ⇒ `origin > due`），正文只判 `origin > started_at` | 新增 **`exemption_due_out_of_range`（FAIL）**——`due` 不在闭区间内、或 `origin > due`，**读侧一律报**；出口写明：续签一枚新封条把 `due` 改回区间内即恢复 PASS（不是无出口的永久红）。进 §5.2、`code` 取值集、§6 C（T-32 一个变体：手改已签封条 `due` 到区间外）、§8。落点：§3.2 判序 ②、§5.1 第 3 条、§5.2、§6 C、§7 T-32、§8 |
| 次要 1 | `history[].commit` 仍不可校（`:640` 写死「`R0` 的父提交」，但没有「由 `to` 反查哪枚是 `R0`」的映射） | 明写「**仅审计、不校验**（由 `to` 无法反查 `R0`）」。落点：§1.1.3 `exemption_start_history[]` |
| 次要 2 | 「唯一写入口」与回填擦边（`:638` / `:641`）：`lock --update` 在缺失时会写 `[]` | 统一成「**唯一追加入口**」（`seal reanchor`）；回填写 `[]` 不算追加。落点：§1.1.3 `exemption_start_history[]` |
| 次要 3 | T-30④ 前置未写：老锁若是 v1 + 封条会先撞 ⓪-2 `lock_v1_with_seals` | 写明夹具**必须用 v2 形态**。落点：§6 C、§7 T-30④ |
| 次要 4 | `check` 在回填前遇到 `due` 上界缺 `first_seen_origin` 的行为（跳过还是红）没写 | 补口径：**下界照判、上界跳过**，报告 `warnings[]` 记 `migration_required`（提示跑 `lock --update`），回填后恢复上界判定，**不把旧锁判红**。落点：§5.1 第 3 条、§8 |

**v24 自查**：① `signed_at_not_canonical` 覆盖所有封条 blob（含 `L[0]`），`exemption_start_signed_at_not_canonical` 只管锁内 `exemption_started_at` 字面值，两者无交集；② **形态先于等值、形态失败跳过等值**已写进 §3.2 判序 ②、§7 T-28、§7 T-29、§5.2 码表、§8 五处；③ 标量锚一律「首个同时含该字段的版本」，`exemption_start_origin_rewritten` / `first_seen_origin_rewritten` 有 T-30⑤ 证明非死码，残余风险如实写；④ ⑦ 四类判据（标量 / 数组 A / 数组 B / 数组 C）与「append-only 只是叙述」写进 §1.1.3 与 §8 两处，正文判据未动；⑤ S-55 前置 = S-18 + S-26，① 降为「2 条删首项」；⑥ `exemption_due_out_of_range` **四处齐备**（§5.2 码表 / §3.2 `code` 取值集 / §6 C + §7 T-32 / §8）；⑦ `history[].commit` 仅审计；⑧ 「唯一**追加**入口」；⑨ T-30④ 必须 v2 形态；⑩ 缺 `first_seen_origin` 时上界跳过 + `migration_required` WARN。**仍不宣称通过，B-0 面本轮未动。**

### 0.24 第二十四轮返工对照（v25）

> 第二十四轮结论：**零阻断**，B-1 / B-2 / ⑦ 四类真闭合；剩 4 重要 + 7 次要。本轮只收口**夹具可构造性**、`due` 的**日期层**口径与 `first_seen_origin` 的**初值防护**，不新增产品决策，也不动 B-0 面。

| 编号 | 第二十四轮结论（复算要点） | v25 改法与正文落点 |
|---|---|---|
| I-1（重要） | S-55 前置与①相抵：S-18 只产生 1 次 `seal reanchor` ⇒ `exemption_start_history` 1 条；S-26 之后 `epoch_origin = R` 可达，第二次 reanchor 的 `--from-a` 必被 `reanchor_not_allowed` 拒，「2 条删首项」造不出来；删到 `[]` 又是任何数组的前缀，前缀单调不红（**该理由已被 v26/S-7 更正：`[]` 不是 `[x]` 的前缀扩展，单调也会红**），测到的是 ⑤ 而不是 ① | **拆两件事**：① 端到端夹具 S-55① 改为「**1 条位移历史整体删除** ⇒ 数组变空、`started_at` 已重指 ⇒ **由 ⑤（`origin == started_at`）红**」，并改掉「S-55 测前缀单调」的宣称；② **前缀单调另立 T-33 纯函数单测**——三份**合成锁文本**（v1 空 / v2 一项 / v3 两项）直接喂判据，断言「非前缀 ⇒ 红」，注明「**不走 git、不是端到端夹具**」。落点：§7 S-55、§7 T-33、§6 C |
| I-2（重要） | `due` / `acceptance_cutover` 是 `YYYY-MM-DD`，而 `exemption_start_origin` / `first_seen_origin + 90d` 是 `YYYY-MM-DDTHH:MM:SSZ`；「日期落在时间戳区间」比较口径未定义，T-32③ 两端点 PASS 写不出来，T-32① 的 `due = origin - 1d` 会先落格式校验 | §5.1 第 3 条**写死归一化**：`due` 一律 `YYYY-MM-DD`；下界取 `exemption_start_origin` 的 **UTC 日期部分**；上界先 `min(first_seen_origin + 90d, acceptance_cutover)` 再**截到 UTC 日期**；**比较全在日期层**。T-32③ 两端点写具体日期串（`due = 2027-03-31` 与 `due = 2027-06-30`；**该落点已被 v26/B-1 取代**——`2027-06-30` 超出 V-20 硬顶 `2027-06-29`，只作 FAIL 反例，端点改为 ③a/③b/③c，见 §0.25 与 §7 T-32）；T-32① 用 **`--amend` 改 HEAD 落盘**（同 T-29），避免 `renewal_seq != N` 抢码。落点：§5.1 第 3 条、§5.2、§7 T-32、§8 |
| I-3（重要） | T-30③ 的「重排」不可构造：1 条时是恒等变换，≥2 条与 I-1 同因不可构造 | 删「重排」子变体，只留「**删一项**」「**改一项**」；夹具里写明「**≥2 条历史不可端到端构造，前缀单调由 T-33 纯函数单测覆盖**」。落点：§7 T-30③、§6 C |
| I-4（重要） | 新建键的 `first_seen_origin` 只防改写、不防初值：读侧没有 `first_seen_origin == 首签封条 first_seen_at` 的断言，也没有上界；首签时把封条 `first_seen_at` 手改成未来值、锁键照抄，锚只证明「之后没再改」，`due` 上界被拉到 cutover | 给 `first_seen_origin_rewritten` **扩一条触发条件**——`first_seen_origin > L[0].signed_at`（**时间戳层**比较）也报本码，`detail.kind ∈ {rewritten, after_signed_at}` 区分成因；补 **T-30⑥** 夹具（首签封条 `first_seen_at` 写未来值 ⇒ 报本码）。`exemption_start_origin` 已有 T-28① 钉在 `L[0].signed_at`，不加。落点：§1.1.3 `first_seen_origin`、§3.2 判序 ②、§5.2 码表、§7 T-30⑥、§8 |
| 次要 1 | 「跳过等值」与「不报 conflict 全组」措辞不一（conflict 还含 `moved_from_chain_mismatch` / `chain_head_missing`） | 统一成「形态失败 ⇒ **跳过整个 conflict 组**」。落点：§3.2 判序 ②、§5.2、§7 T-28、§8 |
| 次要 2 | §3.2 第 10 步没跟着判序 ② 改，仍自排「等值→conflict，再 history」，且没列形态码、两个 rewritten、`due` | 改成「**顺序完全引用判序 ②，本节不再自排**」，并把三个形态 / 结构码、两个 rewritten、`due` 逐一列出。落点：§3.2 第 10 步 |
| 次要 3 | T-29(ii) 写「amend HEAD（最新续签提交）」，但 S-26 之后 HEAD 是后置 lock 提交、不一定封条 | 改成「**amend 最新续签提交**（不是字面 `HEAD`）」。落点：§7 T-29(ii)、§6 C |
| 次要 4 | 锚取空未定义：当前锁未提交（工作树有字段、历史无该字段）时「首个同时含该字段的版本」不存在 | 补口径：**跳过**（视为缺字段）；`seal_anchors` 为 `null` 或非 dict 时取锚按「无该键」容错，**不许抛异常落到 `internal_error`**。落点：§1.1.3「资产根」⑦、§8 |
| 次要 5 | `migration_required` 已成第三义（存量成员名 / v1 缺 cutover / 缺 `first_seen_origin`） | 强制 **`detail.kind` 归类**（`legacy_member_name` / `missing_acceptance_cutover` / `missing_first_seen_origin`），码表注明「同名不同 kind，消费方须按 kind 分」。落点：§5.2 |
| 次要 6 | 「缺 `first_seen_origin` 时上界整段跳过」把 `acceptance_cutover` 也跳过了 | 写明「**`acceptance_cutover` 上界不随 `first_seen_origin` 缺失而跳过**」（`due > cutover` 仍 FAIL）。落点：§5.1 第 3 条、§8 |
| 次要 7 | T-32① 的构造手段未写死 | 写死「用 **`--amend` 改 HEAD**」，理由同 T-29（新提交会让 `N` 加一，触发 `renewal_seq != N`）。落点：§7 T-32①、§6 C |

**v25 自查**：① S-55① 改为「1 条整体删除 ⇒ ⑤ 红」，不再宣称测前缀单调；② **T-33 纯函数单测**新增（三份合成锁文本，不走 git），T-30③ 只留删一项 / 改一项并注明 ≥2 条不可端到端构造；③ **`due` 全在日期层比较**已写进 §5.1 第 3 条、§5.2 码表、§7 T-32、§8 四处；④ `first_seen_origin > L[0].signed_at` 已进 §1.1.3、§3.2 判序 ②、§5.2 码表、§7 T-30⑥、§8 五处；⑤ `acceptance_cutover` 上界不随缺 `first_seen_origin` 跳过；⑥ 「跳过整个 conflict 组」四处同口径；⑦ `migration_required` 按 `detail.kind` 分类；⑧ 锚取空跳过且不抛异常。**仍不宣称通过；B-0 面本轮未动。**

### 0.25 第二十五轮返工对照（v26）

> 第二十五轮结论：**1 阻断 + 3 重要**（含上一轮 S-7 拍错的一条，本轮按评审更正）。本轮只收口 `due` 端点与 `min` 类型、纯函数契约、`detail` 承载位与三处夹具口径，不新增产品决策，也不动 B-0 面之外的实现。

| 编号 | 第二十五轮结论（复算要点） | v26 改法与正文落点 |
|---|---|---|
| B-1（阻断） | T-32③ 要求 `due = 2027-06-30`（上界端点）**必须 PASS**；但 V-20 已把 `acceptance_cutover` 延展硬顶在「默认 + 90 天」= `2027-06-29`（`2027-03-31` + 90d），`2027-06-30` 只作超限反例。`min(first_seen_origin + 90d, cutover)` 两支都到不了 06-30：默认支 `2027-03-31`、延展支 ≤ `2027-06-29` | T-32③ **拆三条端点用例、各钉一个 `min` 分支**：③a 默认支（`due = 2027-03-31`，令 `first_seen_origin + 90d > 2027-03-31`，取 `cutover` 支）PASS；③b 延展支（`acceptance_cutover = 2027-06-29` 且挂 `--anchor-review`，`due = 2027-06-29`，令 `first_seen_origin + 90d > 2027-06-29`，取 `cutover` 支）PASS；③c `+90d` 支（令 `first_seen_origin + 90d < cutover`，`due` 等于该日期）PASS；超限 `2027-06-30` 只留一条 **FAIL** 反例。每条写明钉的是 `min` 的哪一支。落点：§7 T-32、§6 C、§0.24 该行（S-12） |
| I-1（重要） | T-33 没有可独立调用的纯函数契约：全文没有函数名、模块、签名、返回类型；判据其余落点全绑在 `git log` 版本序列上，实现者拿不到「只吃文本、不碰仓库」的入口 | 在 §1.1.3 ⑦ 数组 C 给出签名 **`check_history_prefix(versions: list[list[Entry]]) -> Ok \| Err(code, detail)`**，定义 `Entry = {from, to, commit}` 三字段与 `versions` 的构造口径（按 `git log -m --full-history --reverse` 顺序解析出的数组序列；键不存在时为空列表），明确「`check` 只负责把版本序列喂给该函数，判据本体**零 git 依赖**」。T-33 断言挂在该签名上。落点：§1.1.3 ⑦、§7 T-33、**§6 B-0 夹具与 B-0 文件表**（v27/I-2/I-1 补：`_support/solution.py` 交付清单含 `check_history_prefix`，输入边界写死在 §1.1.3） |
| I-2（重要） | `min()` 操作数类型不一致：`first_seen_origin + 90d` 是时间戳、`acceptance_cutover` 是日期；datetime 比会 `TypeError`（落 `internal_error`），字符串比则因长度差异产生实现分歧 | 写死**单源归一化**：先把 `first_seen_origin` 截到 **UTC 日期**得 `d`（`date`），再 `min(d + timedelta(days=90), acceptance_cutover)`，**全程 `date` 类型**；明确「**先截日期再加 90 天**」，禁止先本地化、禁止时间戳直接与日期比。落点：§5.1 第 3 条、§5.2 码表、§7 T-32、§8 四处 |
| I-3（重要） | `detail.kind` 在报告 schema 里没有承载位置：`errors[]` / `warnings[]` 项固定 `{code, message, path}`，无 `detail`；`downgrades[]` 的 `detail` 是字符串，于是 T-30⑥ 的「区分成因」不可观测 | 统一 `detail` 为**对象**：`errors[]` / `warnings[]` 项加**可选** `detail`（对象），并逐个给出需要它的码的形状（`first_seen_origin_rewritten.detail = {kind: rewritten\|after_signed_at\|not_canonical}`、`exemption_start_conflict.detail = {kind: ...}`、`migration_required.detail = {kind: ...}` 至少三处）；`downgrades[]` 的人类可读字符串字段**改名 `note`**，`detail` 让给对象。**这些是新字段、尚未发布，改名无兼容成本**。落点：§3.2 报告 schema（`detail` 对象总定义）、§5.2 码表（`first_seen_origin_rewritten` / `exemption_start_conflict` / `migration_required` 三码逐条）、§7 T-28(c) 与 T-30⑥ |
| 次要 1（S-6） | §5.1 同句既写「`due > acceptance_cutover` 仍 FAIL」又写「回填后恢复完整上界，不得把旧锁判红」，自相矛盾；真实出口是续签新封条（T-32④），`lock --update` 只回填 `first_seen_origin`、不改 `due` | 删掉「不得把旧锁判红」，改成「回填只恢复 `+90d` 支；`due > cutover` 须续签修正，本码即续签出口」；并如实写「当前库内无已签封条，故升级即红的集合为空」。落点：§5.1 第 3 条、§8 |
| 次要 2（S-7） | S-55① 的理由写反（上一轮拍错）：`[]` **不是** `[x]` 的前缀扩展 ⇒ 单调**会**红；T-33① 也明写「v2 删项 ⇒ 断言失败」 | 改写为「**已重指（`origin != started_at`）后把唯一一项删掉** ⇒ **⑤ 与单调同时红**，按判序只报 `exemption_start_history_broken`」；夹具写明「该仓已 reanchor 过」，否则未重指时删空不会红。落点：§7 S-55① |
| 次要 3（S-9） | `first_seen_origin` 形态无读侧校验：`first_seen_at` 载荷无规范形态条款，`load_lock_strict` 也不解析 `seal_anchors`；`+00:00` 与 `...Z` 字符串比较会误判 | `first_seen_origin_rewritten.detail.kind` 增第三值 **`not_canonical`**；§1.1.3 写明「非 `...Z` 形态即报本码」。落点：§1.1.3 `first_seen_origin`、§5.2 码表、§3.2 schema、§8 |
| 次要 4（S-10） | T-33 批次归属错：挂在 §6 C 并依赖 B，但纯函数单测零依赖 | T-33 **移入 B-0**（B-0 唯一能验证前缀单调的夹具），§6 C 与 §6 B-0 两处清单同步挪动、不在两处都留。落点：§6 B-0 夹具、§6 C |
| 次要 5（S-11） | T-30⑥ 未写构造写法：首签无前一版封条（规则 7 不适用）、`first_seen_at` 不在 `requirements_digest` 覆盖内；但事后 amend 已签封条会改 `L[0]` SHA、使 `epoch_origin` 失配 | 写明「**建键时一次写成，不事后 amend 载荷**」。落点：§7 T-30⑥ |
| 次要 6（S-12） | §0.24 对照表里 T-32 那行落点与正文不符（指向含 `2027-06-30` 旧文本） | 随 B-1 一并改。落点：§0.24 I-2 行 |

**v26 自查**：① T-32 的 ③ 拆成 **三条 PASS 端点**（③a 默认 `cutover` 支 / ③b 延展 `cutover` 支 / ③c `+90d` 支），`2027-06-30` 降为**只作 FAIL**；连同 ① 越界、② `origin > due` 两条 FAIL，共 **3 条 PASS 端点 + 3 类 FAIL**，另 ④ 为续签出口验证；② `min` 单源归一化**六处**同口径（§1.1.3 / §3.2 / §5.1 / §5.2 / §7 T-32 / §8；「先截 UTC 日期再加 90 天」）**（v27/次要 3 补 §3.2 的引用句）**；③ `check_history_prefix` 签名与 `Entry` 形状落 §1.1.3 ⑦，T-33 挂签名并**移入 B-0**；④ `detail` 为可选对象、三种码形状明确、`downgrades[].note` 改名并注明无兼容成本；⑤ S-55① 更正为「已重指后删空 ⇒ ⑤ 与单调同红」；⑥ `first_seen_origin` 非 `...Z` ⇒ `not_canonical`；⑦ 删「不得把旧锁判红」并写明续签出口与「当前集合为空」；⑧ T-30⑥ 写明建键一次写成、不事后 amend。**仍不宣称通过；B-0 面除 T-33 挪入外未动。**（**③a 的构造已被 v27/B-1 取代**：改用早于默认的 `cutover = 2027-01-31`，见 §0.26。）

### 0.26 第二十六轮返工对照（v27）

> 第二十六轮结论：**1 阻断 + 3 重要（均为一句/一段级补丁）+ 5 次要**。本轮只修「端点构造在真实时钟下不可运行」与「纯函数输入边界 / B-0 交付清单缺口」，不新增产品决策。

| 编号 | 第二十六轮结论（复算要点） | v27 改法与正文落点 |
|---|---|---|
| B-1（阻断） | ③a/③b 的 `first_seen_origin` 与 `signed_at` 互斥：`:707` 要求 `first_seen_origin ≤ L[0].signed_at`，而 `signed_at = now()`（2026-11-11）；③a 需 `d ≥ 2027-01-01`、③b 需 `d ≥ 2027-04-01`，正常签发会先撞 `after_signed_at` | **③a 改为早于默认的 `cutover` 构造**：`acceptance_cutover = 2027-01-31`（§5.1 明写「允许收紧、无不得早于今日的下界」、无需 review），`first_seen_origin = 2026-11-05T00:00:00Z`（≤ 运行时 `signed_at`；`d + 90d = 2027-02-03 > cutover`）⇒ `due = 2027-01-31`。**未采用评审建议的 `2026-12-01`**：它仍晚于运行日 `signed_at`（2026-11-11），会先撞 `after_signed_at`；`2026-11-05` 同时满足「≤ `signed_at`」与「`d + 90d > cutover`」。**③b 明写未来值构造**：首签把 `signed_at` 与 `first_seen_at` 同写 `2027-04-15T00:00:00Z`（无规则禁止未来 `signed_at`，`%cI` 只 WARN/INFO；`first_seen_origin` 照抄 ⇒ 等于 `L[0].signed_at`，不触发 `after_signed_at`），不事后 amend。③c 不动（默认 `cutover` + 运行时 `now`；**v28/I-4 已把 ③c 也钉死为 `2026-11-05T00:00:00Z`**）。落点：§7 T-32、§6 C、§5.1 门槛句 |
| I-1（重要） | `check_history_prefix` 的输入边界未定义：空列 / 单版本 / 首版缺键 / `seal_anchors` 为 `null` 或非 dict 的返回值缺失；`load_lock_strict(current=False)` 不解析 `seal_anchors`，直接下标会抛异常 | §1.1.3 ⑦ 数组 C 写死四种边界：空列、单版本 ⇒ `Ok`；缺键 ⇒ 记 `[]`；`seal_anchors` 为 `null` / 非 dict 或 `exemption_start_history` 为 `null` / 非 list ⇒ 记 `[]`、**不得抛异常**（不落 `internal_error`）；`[]` 是零项前缀、任何 `[x...]` 都以它为前缀扩展。落点：§1.1.3 ⑦ |
| I-2（重要） | `check_history_prefix` 没进 `_support/solution.py` 的 B-0 交付清单，T-33 的建面归属悬空 | B-0 文件表 `_support/solution.py` 条补 `check_history_prefix`，写明它承担 `versions` 构造（含四种边界容错）与判据本体、零 git 依赖。落点：§6 B-0 文件表 |
| I-3（重要） | B-0 夹具缺 S-52⑤ 与 `layout.py` 相关项：S-52 仍只在 C 且带「写侧半条随 B-0 交付即验」，S-51 的 B-0 可验部分不在清单 | B-0 夹具补「**S-52⑤ 写侧不 trim**」（`" product"` / `"product "` 均拒）与「**S-51 的 B-0 可验部分**」（`_root_by_index_ok` 分层、`hist == []` 返回 `False` 不抛 `IndexError`、`lexical=True` 零 FS）；C 清单仅保留依赖 `lock --update --assets-root` / `seal reanchor` 的 CLI 面，不重复列同一条。落点：§6 B-0 夹具、§6 C |
| 次要 1 | `detail` 形状记号不一致（`detail = {kind}` vs `detail ∈ {…}`） | 全文统一为 `detail.kind ∈`（§5.2 `exemption_start_conflict`、§7 T-28(c)、§5.1 `acceptance_cutover_unreviewed` 同步）。落点：§5.2、§5.1、§7 |
| 次要 2 | 文首 v25 横幅仍写「先 `min` 再截日期」 | 加「已被 v26 取代」标注；v26 横幅里的 ③a 也加「已被 v27 取代」。落点：文首横幅 |
| 次要 3 | 「六处字面一致」实际只有五处（§3.2 只有码序无归一化句） | §3.2 判序 ② 的 `exemption_due_out_of_range` 后补「归一化口径见 §5.1 第 3 条」，六处名副其实。落点：§3.2 判序 ② |
| 次要 4 | §5.2 的 `migration_required` 只有注、没有表行 | 补表行：**WARN、`exit 0`、`warnings[]`、`detail.kind` 必填三值**。落点：§5.2 码表 |
| 次要 5 | §0.25 I-1 行落点没写 §6 B-0 | 补齐（§1.1.3 ⑦、§7 T-33、§6 B-0 夹具与文件表）。落点：§0.25 I-1 行 |

**v27 自查**：① ③a / ③b / ③c 三条均给具体构造值，且都写明 `first_seen_origin ≤ L[0].signed_at` 这一前置；② 四种 `versions` 边界的返回值写死、均不抛异常；③ `check_history_prefix` 同时出现在 §1.1.3 ⑦、§6 B-0 文件表、§6 B-0 夹具、§7 T-33；④ S-52⑤ / S-51 的 B-0 部分与 C 部分不重复；⑤ `detail.kind` 全文记号统一；⑥ `migration_required` 有表行；⑦ 文首三条横幅（v25 / v26 / v27）口径一致、旧写法均标注被取代。**仍不宣称通过。**

### 0.27 第二十七轮返工对照（v28）

> 第二十七轮结论：**2 阻断 + 4 重要 + 1 次要**，全部是口径收紧与常量钉死，无新产品决策。

| 编号 | 第二十七轮结论 | v28 改法与落点 |
|---|---|---|
| B-1（阻断） | `check_history_prefix` 的「**某**前版本」是 fail-open：`v1=[] → v2=[x] → v3=[]` 时 `v3` 是 `v1` 的前缀扩展 ⇒ 假绿，与 S-55① / T-33① 互斥；且 `git log -m` 对 merge 多父会重复输出同一提交，「紧邻前一版本」可能等于自身 | **统一改为「紧邻前一版本」**（`versions[i-1]` 是 `versions[i]` 的前缀，`versions[i][:len(prev)] == prev`）：§1.1.3 ⑦ 的 `Ok` 定义、`:726`、T-28④、§5.2 `exemption_start_history_broken`、§8 数组 C 五处同步；`[] → [x]` 合法、`[x] → []` 判红，`[]` 零项前缀语义**单向**；`versions` **按 commit SHA 去重**（merge 重复提交视作同一版），去重后按 `--reverse` 时间正序 |
| B-2（阻断） | T-32③a/③b 只写清单侧 `acceptance_cutover`，没写锁侧；B 批首次 `lock --update` 后处于已刷新态，只改清单 ⇒ `acceptance_cutover_mismatch` 先红、锁侧缺失 ⇒ `acceptance_cutover_missing` 先红，`exemption_due_out_of_range` 的 PASS 不可执行 | ③a / ③b 各补「**清单与锁两侧同写**该值」+ **可执行步骤**：`migrate --cutover <v>` → `lock --update` 落锁 → 签 / `--amend` 封条把 `due` 定到 `<v>`；同一次提交里锁值必须已是该值。落点：§7 T-32、§6 C |
| I-1（重要） | `versions` 不含工作树当前锁，本地删项未提交时前缀单调看不到，形成「本地绿、PR 红」 | `versions` 末尾**追加工作树当前锁**（与 HEAD 版字节不同时）；同一 SHA 已在序列中则**替换为工作树内容、不新增一版**（**v29/B-1 已删后半句**：工作树文件没有 SHA，该条与②互斥且 fail-open）。落点：§1.1.3 ⑦、§8 数组 C |
| I-2（重要） | `versions == []` 的可达性未标注；锁未跟踪时 `git log` 返空、`lock_missing` 不成立 ⇒ 前缀单调静默跳过 | §1.1.3 ⑦ 写明「`versions == [] ⇒ Ok` **仅在无锁历史时可达**」；§3.2 报告 schema 新增可选 **`info[]`**；§5.2 新增 INFO 码 **`lock_history_empty`**（不进 `errors[]` / `warnings[]`、不改 exit code）；§6 B-0 夹具与 §8 各一条（**四处齐备**） |
| I-3（重要） | B-0 夹具的 T-33 条目没带四边界 | T-33 夹具行补四边界断言（空列 / 单版本 / 缺键 / `seal_anchors` 为 `null` 或非 dict）+ merge 去重一条 + 无锁历史一条。落点：§6 B-0 夹具 |
| I-4（重要） | ③a 用运行时 `now` 当 `signed_at` 是定时炸弹：2027-02-01 之后 `origin` 日期 > `due` 自动翻红 | ③a 的 `signed_at` 改为**钉死 `2026-11-05T00:00:00Z`**（与 `first_seen_at` / `first_seen_origin` 同值，`origin == signed_at` 不触发 `after_signed_at`），区间 `[2026-11-05, 2027-01-31]` 永久成立；**③c 也一并钉死同值**（否则 2027 年起 `d + 90d` 翻到 `cutover` 支、`+90d` 分支失去覆盖）。落点：§7 T-32、§6 C |
| 次要 1 | `:922` 仍写「`detail` 取 …」 | 改 `detail.kind ∈ {…}`。落点：§3.2 锁版本段 |

**v28 自查**：① 全文已无「某前版本」（`grep` 只剩历史对照表引用）；② `versions` 的三点构造口径（SHA 去重 / 工作树追加 / 同 SHA 替换）只在 §1.1.3 ⑦ 定义一次，§8 与 §5.2 只引用（**v29/B-1 已把③「同 SHA 替换」整条删除，改为两点**）；③ `lock_history_empty` 在 §1.1.3、§3.2（`info[]`）、§5.2、§6 B-0 夹具、§8 五处可见；④ ③a / ③c 的 `signed_at` 均为 `2026-11-05T00:00:00Z`，无「运行时 `now`」残留（③b 用未来常量）；⑤ T-32 ③a/③b 均带「清单与锁两侧同写」与步骤序列。**仍不宣称通过。**

### 0.28 第二十八轮返工对照（v29）

| 编号 | 第二十八轮结论 | v29 改法与落点 |
|---|---|---|
| B-1（阻断，上轮拍错） | `versions` 构造的 ②「追加」与 ③「替换」互斥，③ 是 fail-open：单版删空 `[[x]] + []` 折叠成 `[[]]` ⇒ `Ok`；回滚 `[[a],[a,b]] + [a]` 先绿后红。根因是把「commit SHA」与「内容同一」混为一谈——工作树文件没有 SHA；且 `-m` 的重复项内容相同，「不去重会恒真」的理由被夸大 | **删掉 ③，只保留 ②**（工作树与 HEAD 字节不同 ⇒ 末尾追加）；**SHA 去重①只作用于 `git log` 序列**，并明确写成「构造层清理、不产生判据」；§0.27 I-1 行与 §8 一并收紧。落点：§1.1.3 ⑦、§8 数组 C |
| B-2（阻断） | 「无锁历史 + 工作树有锁」时 ② 的条件悬空：读作「HEAD 缺失即不同」⇒ `[[]]` 单版本、INFO 永不发；且 `lock_missing` 与 `lock_history_empty` 的边界未写 | ② 写死「**仅当 HEAD 存在该路径版本时才比较并追加；HEAD 无该文件 ⇒ 不追加**」；边界①补「**锁文件不存在 ⇒ `lock_missing`，不发 `lock_history_empty`**」；§3.2 ⓪-1 与 §5.2 码表补两码互斥。落点：§1.1.3 ⑦、§3.2、§5.2、§6 B-0 夹具 |
| B-3（阻断） | T-32③a/③b 的步骤用 `--amend`：与「不事后 amend」自相矛盾；amend 首签改 `L[0]` SHA ⇒ `epoch_origin` / `exemption_start_origin` 失配；`lock --update` 写在签封条之前不建键 ⇒ 键永不出现 | 步骤改为**四步**：`migrate --cutover <v>` → **首签载荷一次写死**（`signed_at` / `first_seen_at` / `due` 手写常量、不经 `now`、不 amend）→ `lock --update`（同次写 cutover + 建键）→ 锁独立提交；删掉步骤里所有 `--amend`，只留「`N > 1` 允许 amend 最新续签提交、不得动 `L[0]`」。取值为 ③a `2026-11-05` / `due = 2027-01-31`、③b `2027-04-15` / `due = 2027-06-29`。落点：§7 T-32、§6 C |
| I-1（重要） | T-33④ / B-0 夹具④ 不可证伪：签名里没有 SHA，喂 `[[x],[x]]` 去重与不去重都 `Ok`，且重复项本不改变判定 | **删掉 ④**（去重断言），并把「`-m` 多父重复按 `%H` 去重」明确写成**构造层清理动作、不产生判据**；要测只测 `check` 的版本序列构造，不进纯函数夹具。落点：§6 B-0 夹具、§7 T-33 |
| 次要 1 | `info[]` 未进确定性排序（仍写「四个数组」） | 改「**五个数组**」，前四个按 `(code, path)`，`info[]` 同用 `(code, path)`。落点：§3.2 确定性段 |
| 次要 2 | 新增顶层键但 `schema_version` 仍是 `1` | 报告 `schema_version` 升 **`2`**；同段列出 v1 → v2 增量键（`info[]`、可选 `detail` 对象、`skipped[]` / `not_run[]` 存在性、`downgrades[].note`）+ 「消费方必须忽略未知顶层键」兜底。落点：§3.2 顶层键与新增的「报告 schema 版本」段 |

**v29 自查**：① §1.1.3 ⑦ 只剩两点构造（SHA 去重 / 工作树追加），全文无「替换为工作树内容」的规范句（§0.27 历史行已标注作废）；② ② 的 HEAD 缺失分支已写死，`lock_history_empty` 与 `lock_missing` 在 §1.1.3、§3.2、§5.2、§6 四处互斥；③ T-32 ③a/③b 与 §6 C 都是四步序列、无 `--amend`（只剩 `N > 1` 那一句限制）；④ 纯函数夹具无去重断言，去重只剩构造层一句；⑤ `schema_version = 2` 与增量键清单都在 §3.2。**仍不宣称通过。**

### 0.29 第二十九轮返工对照（v30）

| 编号 | 第二十九轮结论 | v30 改法与落点（节号 + 行号） |
|---|---|---|
| B-1（阻断） | `versions` 构造对「某个版本没有该路径的文件」**无定义**。评审在 /tmp 干净仓复现：c1 写锁 → c2 改锁 → c3 `git rm` 锁后，`git log -m --full-history --reverse --format=%H HEAD -- atlas.solution.lock.json` 仍返回**三个** SHA（删除提交在列），`git cat-file -t <删除提交>:path` ⇒ `fatal: path ... does not exist`；若把删除提交记成 `[]`，`[…,[x],[]]` 会被判 `exemption_start_history_broken`——**错误码语义错位**（数组没被改写，是整份锁被删） | **(a) 历史层**：⑦ 构造②写死「某版本没有该路径 ⇒ `git cat-file -t <c>:atlas.solution.lock.json` 失败即 `continue`、**不记 `[]`**」，并显式引用 ⓪-1 的同一惯例、说明 ⑦ 为何沿用（其余判据读工作树 `current=True`，前缀单调必须同步，否则「本地删一项未提交」本地绿、PR 红）。**(b) 工作树层**：构造③补「**HEAD 有该路径、工作树文件被 `rm` ⇒ 不追加**」（不存在「拿什么比」的对象），整体由 `lock_missing`（从未跟踪）/ `lock_tracked_but_deleted`（已跟踪被删）承载、**不发 `lock_history_empty`**；边界①同步两码互斥，边界③补「**缺键 ≠ 该提交没有该路径**」。另写死「删除提交不得伪造成空版本」「删锁 → 改根 → 重建锁只由 ⓪-3 的 `assets_root_history_rewritten` 报、不被 `exemption_start_history_broken` 抢报」。落点：**§1.1.3 ⑦ 数组 C 与边界①③（`L767`）**、§3.2 ⓪-1（`L1460`）、§6 B-0 夹具（`L1871`）、§7 T-33（`L2005`）、§8 数组 C（`L2139`） |
| I-1（重要） | T-32③a 步骤① `migrate --cutover 2027-01-31` 在不生效：`migrate` 是「只补缺、不改已有」，C 批基座清单已有 `acceptance_cutover = 2027-03-31` ⇒ 显式值不覆盖 ⇒ ③ 步两侧同写 `2027-03-31` ⇒ `2026-11-05 + 90d = 2027-02-03 < 2027-03-31` ⇒ `due = 2027-02-03`，**③a 静默退化成 ③c**（断言仍 PASS，`cutover` 支失去覆盖） | 采评审**方案②**：③a/③b 改从 **v1 清单的独立夹具仓首次迁移**构造——`migrate --to 2 --cutover 2027-01-31`（与 V-20 同路径；此时 `acceptance_cutover` **尚不存在**，无「只补缺」覆盖问题），并写死**不得复用 B 批已写 `2027-03-31` 的基座**，否则静默退化；③b 同改为 `migrate --to 2 --cutover 2027-06-29 --anchor-review <REVIEW-ID>`。其余三步（首签载荷一次写死 → `lock --update` → 锁独立提交）在 v1→v2 首迁移路径上仍成立：`migrate` 只写清单、`lock --update` 才建键并写锁侧同值。端点值仍常量写死、**不引入运行时 `now`**（③a `2026-11-05T00:00:00Z` / `due = 2027-01-31`、③b `2027-04-15T00:00:00Z` / `due = 2027-06-29`），无新型时间炸弹。落点：**§7 T-32（`L2004`）**、§6 C 夹具行（`L1884`） |
| S-1（次要） | ③a 第②步「首签载荷一次写死」隐含「仓内尚无任何封条」；若 C 批夹具共用带封条的基座仓，第②步不可执行 | ③a/③b 前置写死「**本端点须在无封条仓上首签**」——与 I-1 的「v1 清单独立夹具仓」同一构造：首签前 HEAD 无 `*.seal.json`、`seal_anchors` 为 `null`，故「一次写死」可执行。落点：**§7 T-32（`L2004`）**、§6 C 夹具行（`L1884`） |
| S-2（次要） | `lock_missing` 同码承载「从未有锁（B-0 正常）」与「已跟踪的锁被删（篡改信号）」 | **加码**（不改 message 糊在一起）：新增 **`lock_tracked_but_deleted`**——锁文件不在工作树，但 `git cat-file -e HEAD:path` 成功 / `git ls-files --error-unmatch` 成功 / `git log -m --full-history --format=%H HEAD -- path` 非空，三者任一 ⇒ **FAIL、`exit 1`、`errors[]` 只含该码、短路**，`message` 写「已跟踪的锁被删除（篡改信号）」；三者全空才是 `lock_missing`（收窄为「从未有锁」，B-0 正常态，行为不变）。同步：⓪-0 之前的前哨判码、⓪-1 的互斥与「仍执行」语义、口径段标题、链规则、§5.1 锁版本段、§5.2 码表（新行 + `lock_history_empty` 行互斥）、§6 B-0 夹具、S-50、§8 残余/数组 C。报告归属：**`errors[]`、severity 1、`exit 1`**（不是 `warnings[]` / `info[]`）。落点：**§5.2 码表（`L1817`，`lock_history_empty` 行 `L1818`）**、§5.1 锁版本段（`L968`）、§3.2 ⓪-0 前哨（`L1459`）、⓪-1（`L1460`）、口径段（`L1465`）、链规则（`L1503`）、§1.1.3 ⑦（`L767`）、§6 B-0 夹具（`L1871`）、§7 S-50（`L2068`）、§8 残余（`L2126`）与数组 C（`L2139`） |

**v30 自查**：① §1.1.3 ⑦ 的 `versions` 构造是**三点**，历史层「路径缺失即 `continue`、不记 `[]`」与工作树层「HEAD 有但被 `rm` ⇒ 不追加」都已写死，且与 ⓪-1 的 `git cat-file -t` 惯例**同一实现**；② 删除提交不再产生版本，`[…,[x],[]]` 的误报路径消失，S-48 的「删锁 → 改根 → 重建锁」只由 `assets_root_history_rewritten` 报；③ T-32③a/③b 与 §6 C 都从 **v1 清单首次 `migrate --to 2 --cutover <v>`** 构造并写明「不复用 B 批基座」「无封条仓首签」，端点仍常量写死；④ `lock_tracked_but_deleted` 在 §5.1 / §5.2 / ⓪-0 / ⓪-1 / 口径段 / 链规则 / §1.1.3 ⑦ / §6 / S-50 / §8 十处齐备，`errors[]` 归属写死；⑤ 评审点名**不要动**的部分（S-55①/T-33② 覆盖、HEAD 无该文件三处一致、四步序列主体与 `N>1` amend 隔离、`schema_version = 2` / 五个数组 / `info[]` 排序 / 增量键 / 兜底句、`check_history_prefix` 四边界、T-32 三条区间算术）本轮未改。**仍不宣称通过。**（**v31/B-2 撤销本表 I-1 的「方案②」**：③a/③b 已退回方案①——已迁移仓 + 显式 `--cutover` 覆盖，见 §0.30。）

### 0.30 第三十轮返工对照（v31）

| 编号 | 第三十轮结论 | v31 改法与落点（节号 + 行号） |
|---|---|---|
| B-1（阻断） | L1871 的 B-0 夹具期望码在 v1 基座上不可达：**v31 当时的判断是「B-0 锁是 `schema_version: 1`、不含两个根」（§1.1.3 ① / §5.1 / V-10）——该判断已被 v32/B-2 更正为「清单 v2 ⇒ 锁 `schema_version: 2`」，本节保留为历史陈述**；评审实测有效版本 `(1,[])(1,[])(2,['product2'])`、`UH = {'product2'} ⊆ 当前 hist` ⇒ ⓪-3 / ⓪-4 全绿、`check` PASS、无任何码 | 夹具**拆两段**：B-0 只留「c1 → c2 → c3 删除提交被跳过、`versions` 恰两版、不报 `exemption_start_history_broken`」；「删锁 → 改根 → 重建锁 ⇒ 只报 `assets_root_history_rewritten`」**搬到 §6 C 的 S-48①**，并写死**基座必须是 v2 锁且历史版本带旧根**（`schema_version: 2`、`assets_root_history` 含旧根）——否则 `UH` 只剩重建后的根，⓪-3 无判据。落点：**§6 B-0 夹具（L1889）**、**§6 C S-48（L1902）** |
| B-2（阻断） | T-32③a/③b 四步在 C 批不可执行：0.4.0 不注册 `migrate`（步骤① argparse 未知命令、exit 2）；`migrate` 写清单与 PRD front matter ⇒ 工作树必脏，而 `lock --update` 要求定义源干净；四步在 ① 与 ③ 之间没有提交。v30 的「方案②」（v1 清单首次迁移）不成立 | **退回方案①**：基座改回「**已迁移仓**」（清单 v2、`acceptance_cutover = 2027-03-31` 已提交）+ **无封条**；**二进制版本写死**——① 走 **0.3.x**（唯一注册 `migrate` 的版本）、②–④ 走 **0.4.0**、全程不碰 `migrate --to`；① `migrate --cutover 2027-01-31` 是**覆盖语义**、只改清单、不动 PRD front matter ⇒ 定义源仍干净、**步骤间无需提交**，③ `lock --update` 可过；**立规则**：§5.2 的「只补缺、不改已有」加限定「**显式 `--cutover` 覆盖、不受其约束**」。S-1 前置改成「已迁移 + 无封条」。落点：**§5.2 迁移命令（L1783、L1784）**、**§7 T-32（L2022）**、§6 C 夹具行（L1902） |
| I-1（重要） | L1465 自相矛盾（`lock_missing` 定义为「HEAD / index 均无、`git log` 返空」，却又写「⓪-1 与 ⓪-2 仍执行（历史仍在 `git log` 里）」）；L1460「本项仍执行——历史里有坏版本照样 `lock_history_unparsable`」在拆分后不可达 | 删掉两处「历史仍在」措辞，改成拆分后的因果：**从未跟踪 ⇒ 三探针全空 ⇒ 没有锁历史 ⇒ ⓪-1 无版本可解析、⓪-2 无 v1 版本可判，两项按判序执行但恒通过**；「仍执行」只表示判序位置，不暗示历史里可能有坏版本。落点：**§3.2 ⓪-1（L1478）**、**§3.2 `lock_missing` 口径（L1483）** |
| I-2（重要） | 哨兵与第 0 步的先后未写死 + 浅仓 fail-open：`--depth 1` 且删除提交在浅边界外时 `is-shallow=true`、三探针全空 ⇒ 落 `lock_missing`、跳过根断言 | 写死「**在第 0 步之后、⓪-0 之前**」；补**浅仓复核**：调用路径跳过第 0 步（`lock --update` 预检、单测直接调判定函数）时先 `git rev-parse --is-shallow-repository`，为 `true` ⇒ `chain_unverifiable` hard FAIL（`detail.kind = "shallow"`），只有非浅仓才允许 `lock_missing`。落点：**§3.2 ⓪-0 哨兵** |
| I-3（重要） | 「清单 v2 ⇒ 锁写 `schema_version: 2`」不是规则，只是 L968 / L1758 的批次事实；T-32③a 在 v1 锁 + 无封条仓上建键会立刻撞 ⓪-2 `lock_v1_with_seals` | §5.1 立**写侧规则**：`manifest.schema_version == 2` ⇒ 本次 `lock --update` 写出的锁 `schema_version` **必须为 2**，并与 `layout_assets_root` / `assets_root_history[]` 同一次写入；**不得产出 v1 锁**（否则建键即撞 ⓪-2），B-0 的 `migrate` 不写锁故不受影响。落点：**§5.1 锁版本（L986）**、T-32③a 第③步（L2022） |
| S-1（次要） | 「删掉整份锁 ⇒ `lock_tracked_but_deleted`」会被读成「任何删除提交都报」；「删 → 重建」形态下 HEAD 有锁，哨兵前置不成立 | 两处加限定「**仅当 HEAD 无锁**」；写明「**删 → 重建**不报本码，由 ⓪-3 的 `assets_root_history_rewritten` 承载（只对 v2 旧根历史可达）」。落点：**§3.2 链规则（L1521）**、**§5.2 码表（L1835）** |
| S-2（次要） | 哨兵短路未进报告形状枚举（只写 ⓪-0 / ⓪-1）；`not_run[]` 未按六段口径规定 | 报告完整性枚举补哨兵；写死「**哨兵短路 ⇒ `not_run[]` 六段全进**、`errors[]` 只含该码」；码表行同步「`not_run[]` 六段全进」。落点：**§3.2 报告完整性（L1597）**、**§5.2 码表（L1835）** |
| S-3（次要） | V-20 缺「收紧无需 review」的正向夹具，而 ③a/③b 的第①步全靠这条规则（§5.1 有规则、B-0 无夹具） | V-20 补**第七支**：`--cutover 2027-01-31`（早于包级默认）⇒ PASS、不要求 `--anchor-review`、清单写 `2027-01-31`。落点：**§6 V-20（L1889）** |
| S-4（次要） | 空仓（`git init` 无提交，三探针 128/1/128）与非 git 目录（三探针全 128、第 0 步 `rev-parse` 也 128）两态未定义，L1455 只有 `true` 分支 | 写死：**非 Git 目录** ⇒ 用法 / 环境错误，`exit 2` + stdout 首行人类可读，**不得**当「非浅仓」继续；**空仓** ⇒ `--is-shallow-repository` 为 `false` 放行，三探针全空 ⇒ `lock_missing`，且空仓里 `git log` 的 128 按「无历史」处理、**不判 `chain_unverifiable`**。落点：**§3.2 第 0 步（L1473）** |

**v31 自查**：① 全文已无「从 v1 清单首次迁移」的执行指令（仅 §0.29 作为 v30 历史记录保留，并标注撤销）；② T-32③a/③b 的二进制版本、覆盖语义、无封条前置三处齐备；③ B-0 夹具不再声称覆盖 `assets_root_history_rewritten`，该形态只在 v2 旧根基座上存在（§6 C S-48①）；④ `lock_missing` / `lock_tracked_but_deleted` / `lock_history_empty` 三码互斥与「HEAD 无锁」限定在 ⓪-0、⓪-1、口径段、链规则、码表、§1.1.3 ⑦、§6、S-50、§8 一致；⑤ 哨兵次序、浅仓、空仓、非 Git 四态写死，`not_run[]` 六段口径进报告枚举；⑥ 评审点名**不要动**的部分（S-55① / T-33② 覆盖、「HEAD 无该文件 ⇒ 不追加」四处、四步序列末段 `N>1` amend 隔离、`schema_version = 2` / 五个数组 / `info[]` 排序 / 增量四类 / 兜底句、`check_history_prefix` 四边界、T-32 三条区间算术、「删后原样重建 ⇒ Ok 无告警」）本轮未改。**仍不宣称通过。**

### 0.31 第三十一轮返工对照

| 编号 | 第三十一轮结论 | v32 改法 | 落点（节号 / 行号） |
|---|---|---|---|
| B-1（阻断） | T-32③a 步骤①在 0.3.x 上 rc=2：`migrate` 只补缺、`--cutover` 与基座不同即报错，端点造不出来；「覆盖语义」方向本身拍错 | ③a/③b 步骤①改**单一二进制内的 `init --cutover <v>`**（**不是「版本无关」：`reader_version` 仍决定清单版本**；③a `2027-01-31`、③b `2027-04-15`，端点常量写死、不用运行时 `now`）；**删掉「0.3.x / 0.4.0 双二进制」标签**，版本门改写成「由哪一版的读侧门接受」；删掉 v31 的「显式 `--cutover` 是覆盖语义」，恢复「只补缺、不覆盖已有字段」并写明**不得为此放宽迁移器** | §7 T-32（L2051）、§6 C 夹具（L1925）、§5.2 第 5/6 条（L1796–1803）、V-14/V-15（L2140–2141） |
| B-2（阻断） | V-10 的「锁仍 `schema_version: 1`」与已落地写侧冲突（`LOCK_SCHEMA_VERSION = 2`；`schema_version = 2 if data["version"] == 2 else 1`；实测 v2 清单 `lock --update` 出 v2 锁） | 三处叙述改成「`migrate --to 2` 后 `lock --update` ⇒ 锁 `schema_version: 2`」，写侧规则（清单 v2 ⇒ 锁 v2）**从 B-0 起生效**；删除 L986 的批次例外句 | §1.1.3 锁版本（L1005）、§5.2 第 4/6 条（L1795）、§6 B-0 依赖（L1913）、V-10（L2136） |
| I-1（重要） | ③a 的清单改动从未提交，只证明 ③ 不被拒，不证明提交态自洽（新克隆 / CI 报 `acceptance_cutover_mismatch`） | 改走 `init --cutover` 后基座自带该值、清单与锁同源；步骤表补「清单与锁同一次提交（或先提交清单再签锁）」，保证端点 PASS 在**干净工作树**上成立 | §7 T-32（L2051） |
| I-2（重要） | B-1 拆分后 B-0 侧只剩构造层断言，CLI 层被 `lock_tracked_but_deleted` 短路 | `versions` 构造提成 **B-0 独立纯函数 `build_lock_versions`**（与 `check_history_prefix` 同级、进 B-0 文件表）；夹具喂「三个 SHA 的假对象、其中一个无文件」断言序列恰两版、不产生空版本；CLI 层另由哨兵夹具覆盖 | §1.1.3 ⑦（L804）、§6 B-0 文件表 / 夹具（L1906 / L1912）、§8 数组 C（L2186） |
| I-3（重要） | `detail.kind = "shallow"` 不在闭集白名单，且同码字段名冲突（同码另用 `cause`） | 统一用 **`cause`**；把 `chain_unverifiable.cause ∈ {shallow, partial, history_unreadable}` 写进报告 schema 的 `detail` 闭集白名单 | §3.2 ⓪-0（L1496）、报告 schema（L1602） |
| I-4（重要） | `chain_unverifiable` 的 exit code 未定义，⓪ 层出现两个值（1 与 2） | 码表补 `lock_unparsable` / `lock_history_unparsable` / `chain_unverifiable` 三行并写明 exit；**⓪ 层统一 exit 1**；exit 2 只留用法错误与 `internal_error` | §5.2 第 13 条（L1842–1845）、§1.1.3 锁版本码表句（L1005） |
| S-1（次要） | 「跳过第 0 步」不是 `rev-parse` 的返回值，而是调用路径事实；单测里不存在「第 0 步」 | 改成「浅仓判断留在 `check` 入口；判定函数接收显式参数 `history_available: bool`」，`false` ⇒ `chain_unverifiable(cause="shallow")` | §3.2 ⓪-0（L1496） |
| S-2（次要） | L1782「`migrate` 只写清单与 PRD front matter」与 ③a「不动 PRD front matter」矛盾 | ③a 改走 `init` 后该步整段删除；`migrate` 侧补「front matter 只补缺」限定，删掉「步骤间无需提交」 | §5.2 第 6 条（L1800）、§7 T-32 |
| S-3（次要） | ⓪-1 开头那句未加限定的「`git log` 本身非零 ⇒ `chain_unverifiable`」与后文重复且越界 | 删掉无限定版本，只留「**非 `lock_missing` 路径**里 `git log` 本身失败 ⇒ `chain_unverifiable`」 | §3.2 ⓪-1（L1497） |
| 结构 | C 批真正依赖的写入口（`seal freeze` / `seal reanchor` / `lock --update --assets-root`）**全仓不存在**，过去多轮在「看起来今天能跑」的 CLI 夹具上来回返工 | 这些端点统一标「**C 批实现时补**」，并写清 ① 依赖哪个尚不存在的命令、② 规则层已闭合到什么程度、③ 实现时用什么断言；能量化部分（`build_lock_versions`、`check_history_prefix`、`due` 日期算术）一律提纯函数夹具，**今天就跑** | §6 C 批（L1928）、§5.1 改根 / 冻结（L974） |

**v32 自查**：① 全文已无「显式 `--cutover` 覆盖已有字段」的规则，也没有「0.3.x / 0.4.0 双二进制」的执行指令（§0.30 作为历史记录保留并标注撤销）；② 锁 schema 的叙述只剩一种：清单 v2 ⇒ 锁 v2，从 B-0 起生效；③ T-32③a/③b 的基座由 `init --cutover` 一次写成，清单与锁同源、步骤表含提交；④ `versions` 构造有独立纯函数入口，B-0 可当天跑；⑤ `chain_unverifiable` 一律用 `cause`，exit 固定 1；⑥ C 批三条写入口全部标注「实现时补」。评审点名**不要动**的七项本轮未改。**仍不宣称通过。**

### 0.32 第三十二轮返工对照

| 编号 | 第三十二轮结论（实测） | v33 改法 | 落点（节号 / 行号） |
|---|---|---|---|
| B-1①（阻断） | ③ 之前 PRD 未提交 ⇒ `git status --porcelain → ?? product/`、`lock --update → [FAIL] 定义源工作树不干净（?? product/prd/solution-prd.md）`；`init` 只写 PRD 骨架、不提交 | ③a/③b 在「首签载荷」与 `lock --update` 之间插入**第③步「提交 PRD 与清单」**（`git add product/ atlas.solution.yaml && git commit`），写进步骤表并删掉「步骤间无需提交」 | §7 T-32 ③a/③b（L2077）、§6 C T-32 摘录（L1948） |
| B-1②（阻断） | `init` 首锁 `acceptance_cutover = null`（`lock_payload` 只在 `definition.commit` 非空时写值；实测 `init-lock schema 2, cutover None, commit None`），提交 PRD 后再 `lock --update` 才变 `2027-01-31, commit <sha>` | 写死**锁侧两态**：「PRD 未提交 ⇒ 硬拒、不产锁；PRD 已提交 ⇒ 写端点值；首锁 `null` 只作构造起点、不作 PASS 依据」，`due` 用第二次 lock 的值 | §7 T-32 ③a（L2077）、§6 C 摘录（L1948） |
| B-1③（阻断） | 前置「基座是已迁移仓」与 `init` 互斥（`init` 见 `atlas.solution.yaml` 即 `SolutionError`） | 前置改成「**全新空仓 + 已提交的 `product/prd/solution-prd.md`**」，「已迁移仓」整句删除；签名 / `--member` 步骤保留 | §7 T-32 ③a/③b（L2077） |
| B-1④（阻断） | `init --cutover` 在 `.atlas/VERSION=0.3.0` 下 **rc=0 静默丢弃**（清单 `version: 1`、锁 `schema_version: 1`、无 `acceptance_cutover` 键、无 WARN）；原因 `manifest_version = 1 if semver_lt(reader,(0,4,0)) else 2` | 写死「只在 reader ≥ 0.4.0 写 v2；**< 0.4.0 下显式 `--cutover` 必须 exit 2（用法错误）、不写任何文件**」，并新增夹具 V-22；`§5.2` 第 8 条同步 | §5.2 第 8 条（L1841）、§7 V-22（L2174）、§7 T-32 ③a（L2077） |
| 措辞（附带） | 「单二进制、无版本标签」读起来像版本无关 | 统一改成「**不启用第二份二进制，但 `reader_version` 仍决定清单版本**」；v32 历史句补同义括号 | 头部 v32 一句话（L27）、§7 T-32 ③a/③b（L2077）、§5.2 第 8 条（L1841）、V-22（L2174） |
| 重要 1 | `build_lock_versions(commits, fetch, worktree, head_has_path)` 的 `fetch` 与 ⓪-1 根集循环（内联 `git cat-file -t`）是两个「路径不存在」判定，口径会漂移 | §1.1.3 ⑦ 写死**共用 `path_at(commit)` 探针**：`git cat-file -t <c>:<path>` 返回非 `commit`/`blob` ⇒ `None`；`None` 两处都解释为「该提交无该路径 ⇒ 跳过」；**非零 rc 不得在任一处解释成 `chain_unverifiable`**（只有 `<commit>` 对象本身缺失才是） | §1.1.3 ⑦（L824） |
| 重要 1 附带 | `build_lock_versions` 与 `check_history_prefix` **都没进 `shared/gates.md`**（全仓命中 0；该表「不在本表 = 不存在」） | B-0 文件表补一行：登记 `tests/test_solution_versions.py`（或实际文件名）与 `tests/test_solution_history_prefix.py`，各附一条「喂坏输入必红」的假绿证明（`len(versions)==2` / `[a]→[a,b]→[a]` 必须 `Err`）；要求可执行、给出文件名 | §6 B-0 文件表（L1934） |
| 次要 1 | `manifest_schema_unsupported` 保留 exit 2 正确，但该路径**不产 JSON**（`except SolutionError` → stderr → `return 2`），`not_run[]` / `info[]` 出不来 | 码表该行写明「本码下 `--json` **无 JSON 报告、只有 stderr 文本**」，并说明与 §3.2「短路也要有报告」不矛盾（后者只约束**有报告对象**的出口） | §5.2 码表（L1866） |
| 次要 2 | §0.30 表（L678）仍写「B-0 锁是 `schema_version: 1`」，与 v32 的「清单 v2 ⇒ 锁 2」并排会误导 | 改历史陈述口径：「v31 当时的判断，已被 v32/B-2 更正」 | §0.30 B-1 行（L680） |
| 次要 3 | 「删后原样重建 ⇒ `Ok`」只有可推出、无正文无夹具 | §3.2 链规则 1 补规则正文（删除提交被跳过、重建字节相同 ⇒ 前缀扩展成立；HEAD 有锁 ⇒ 哨兵不触发；根历史不变 ⇒ ⓪-3 不红）；B-0 补纯函数夹具 `c1` 有锁 → `c2` 删除 → `c3` 原样重建 | §3.2 链规则 1（L1560）、§6 B-0 夹具（L1935） |
| 次要 4 | §6 C「规则层闭合到什么程度」只有一段汇总（L1930），读不出 S-38 与 S-48 的闭合度差异 | 改成**逐端点一行**：`seal freeze` 读侧闭合 / 写侧待命令；`seal reanchor` 三件事写死、闭合度最高；`lock --update --assets-root` 写侧规则闭合、CLI 待命令；并点明 S-48 比 S-18 多依赖一条命令 | §6 C 第 2 条（L1953） |

**v33 自查**：① T-32③a/③b 的五步顺序为 `init --cutover` → 首签载荷 → 提交 PRD 与清单 → `lock --update` → 锁提交，每步都写明期望（首锁 `null`、第二次 lock 才写端点值）；② 全文「已迁移仓」不再作为 ③a/③b 前置；③ `init --cutover` 的 reader 门在 §5.2 / V-22 / T-32 三处一致（< 0.4.0 必须 exit 2）；④ `path_at` 单源只写在 §1.1.3 ⑦ 一处、两处实现同源；⑤ `shared/gates.md` 登记行给出文件名与假绿证明；⑥ 码表补 `manifest_schema_unsupported` 的无报告说明；⑦「删后原样重建」有规则正文与纯函数夹具；⑧ §6 C 闭合度逐端点可读。评审点名**不要动**的 B-0 侧（exit 统一、V-10 新期望、`build_lock_versions` 函数形态与夹具、哨兵 / 互斥夹具、S-48① 搬 C 理由）及七项回退本轮未改。**仍不宣称通过。**

### 0.33 第三十三轮返工对照

| 编号 | 第三十三轮结论（实测） | v34 改法 | 落点（节号 / 行号） |
|---|---|---|---|
| 阻断 1 | 前置「全新空仓 + 已提交 PRD」⇒ 仓内无 `.atlas/` ⇒ `resolve_reader_version` 回落到工具包 `package.json` = `0.2.0-beta.33` ⇒ `manifest_version = 1` ⇒ `init --cutover` 抛 `SolutionError` ⇒ **exit 2，第①步即死**；与 V-22 的「拒绝」形成闭环，但与「今天真能跑」互斥 | 删除「今天真能跑」，改**两态诚实描述**：**产品路径** = B 批发版后 / `.atlas/VERSION` 已是 `0.4.0`；**测试路径** = 夹具预置 `.atlas/VERSION=0.4.0` 起步，并标明「夹具前置、不是产品可达路径」。§6 C 逐端点同步 | L29、§7 T-32（L2098）、§5.2 第 8 条（L1861）、§6 C（L1974） |
| 阻断 2 | **评审时** `acceptance_cutover_review` **写侧全缺**：parser 标量白名单（`_support/solution.py:327-329`）、`_manifest_text` 无 review 参数（`:1468-1472`）、`lock_payload` 无 review 键（`:1288-1314`）；手写键 ⇒ `manifest_field_unknown` exit 2；`migrate --anchor-review` 静默丢弃（rc=0、无键、无 WARN）。**v34 落笔时工作树已出现该实现**（parser `:328`、`_manifest_text` `:1480` 与写行 `:1496-1498`、`lock_payload` `:1314-1315`、`migrate` `:1888-1896`），B-0 夹具仍须锁住防回退 | 三处写侧**纳入 B-0 文件表**（不是 C 批），各配夹具 V-23a/b/c；写明「③b 与 V-20③ 依赖这三行，缺一行即必红」 | §6 B-0 文件表（L1955）、§7 V-23（L2196） |
| 重要 1 | ③ 只 `git add product/ atlas.solution.yaml`，跑完仍有 `?? .atlas/`、`?? atlas.config.yaml`、`?? web/`，与「干净工作树复验」冲突 | ③ 改为「成员仓先初始提交 → 夹具 `.gitignore` 忽略 `.atlas/` → `git add -A` 一并提交」，写明 `.atlas/` **不入库**、`atlas.config.yaml` 与 `web` **入库**；干净口径 = `git status --porcelain` 为空，复验命令 `test -z "$(git status --porcelain)"`；⑤ 锁提交后同一命令复验 | §7 T-32 ③/⑤（L2098） |
| 重要 2 | ④ 写「建 `seal_anchors` 键」今天不存在：无 `seal` 子命令、`lock --update` 不读封条、`lock_payload` 无 `seal_anchors`；锁写出后无该键、`check` 仍 PASS ⇒ `first_seen_origin` 无落点、`due` 无输入，绿是「读侧未实现」的假绿 | ④ 明确标 **C 批**（依赖 `seal freeze` 写入口）；写死「在该入口落地前，`check` 的 PASS **不构成 `due` 已评测**」；§6 C 同步 | §7 T-32 ④（L2098）、§6 C（L1974） |
| 重要 3 | `path_at` 三洞：symlink（`blob` ⇒ 视为存在，历史侧解析失败红、工作树跟随链接可能绿）；tree（⇒ `None` 静默跳过，吞掉「锁路径是目录」）；浅仓（同一非零 rc 一处判 `None`、一处判 `chain_unverifiable`） | 写死判序：先 `git cat-file -e <commit>`（不可读 ⇒ `chain_unverifiable`），再 `-t <commit>:<path>` 判路径形态；`blob` 时用 `ls-tree` mode 识别 symlink（`120000`）；`tree` / gitlink / symlink ⇒ `non_blob`，**不得静默当不存在**（历史侧 `lock_history_unparsable`、工作树侧 `lock_unparsable`）；**symlink 两侧一律不跟随、同一口径**；`fetch` 的 `None` 只表示 `absent` | §1.1.3 ⑦（L844） |
| 重要 4 | 「两处各写一套即视为未实现」不可证伪：`shared/gates.md` 无该行、`tests/` 无夹具、B-0 文件表无对应行（元规则「不在本表 = 不存在」） | 给可执行检查 `tests/test_path_at_single_source.py`（monkeypatch `_run_git` 计数或静态引用断言，两处都调用同一个 `path_at`），并写进 B-0 文件表与 `shared/gates.md`；补 V-24（symlink / tree / 浅仓三洞） | §6 B-0 文件表（L1954）、§7 V-24（L2197） |
| 重要 5 | `migrate --anchor-review` 显式给了 review 仍 rc=0 静默丢弃 | 正文单列：显式 review **必须落盘或 exit 2**，不许 rc=0 静默；并入 V-23b | §7 V-23（L2196）、§5.2 第 8 条（L1861） |
| 次要 1 | L1951「`lock_payload` 只写 `members` / `contracts`」陈旧 | 改成与代码一致的字段列表：`schema_version` / `solution` / `mode` / `locked_at` / `members` / `contracts`（+ `definition`、`acceptance_cutover`、根字段），注明**无** `seal_anchors` / `acceptance_cutover_review` | §6 C（L1972） |
| 次要 2 | 五步硬编码 `product/`，与 `init --assets-root` 取值失配 | ③ 的 add 改成整仓 `git add -A`，并注明 `product/` 只是 `--assets-root` 的默认值；非默认根同样被 `-A` 覆盖 | §7 T-32 ③（L2098） |
| 次要 3 | `init --anchor-review` 在 cutover 早于默认时无提示（晚于默认才必填，早于默认给了也无用） | **v34 曾写「不写该键 + 打印 `ignored`」；该写法已被 v35/口径裁定撤销**：显式给了就落盘，不设 `ignored` 第三态（见 §0.34） | §7 V-20⑦、§5.2 第 8 条（L1861） |
| 次要 4 | 「任何 exit 2 出口均不产 JSON」只在 `manifest_*` 一处解释 | 写成**通则**（覆盖用法错误、`manifest_schema_unsupported`、`reader_version_unknown` 等构造前出口；`internal_error` 为唯一例外），码表行改为引用通则、不逐条解释 | §5.2 第 13 条（L1883）、码表 `manifest_schema_unsupported`（L1886） |

**v34 自查**：① 全文不再把「今天真能跑」当结论（该短语只作为被否定的引语出现）；T-32③a/③b 明写「产品路径 / 测试路径」两态，测试路径的 `.atlas/VERSION=0.4.0` 只作夹具前置；② `acceptance_cutover_review` 三处写侧在 B-0 文件表可逐行核对，V-23a/b/c 覆盖 round-trip、`migrate --anchor-review` 落盘、锁同值；③ `path_at` 的浅仓 / symlink / tree 三态各有断言，`None` 只表示 `absent`；④ 单源有可执行测试并进 `shared/gates.md`；⑤ ③ 的提交集合与干净口径可复验；⑥ ④ 的 `seal_anchors` 已标 C 批、PASS 不等于 `due` 已评测；⑦ exit 2 通则一处写清。评审点名**不要动**的 B-0 侧（exit 统一、V-10 新期望、`build_lock_versions` 形态与夹具、哨兵 / 互斥夹具、S-48① 搬 C 理由）与「删后原样重建 ⇒ `Ok`」等已闭合项本轮未改。**仍不宣称通过。**

### 0.34 第三十四轮返工对照

| 编号 | 第三十四轮结论（实测） | v35 改法 | 落点（节号 / 行号） |
|---|---|---|---|
| 口径裁定 | 三处互斥：L1798「不晚于默认不写（或写 `null`）」、L1861「不写但打印 `ignored`」、L2193⑦「PASS、不写 + ignored」；代码实际**落盘**（`init --cutover 2027-01-31 --anchor-review REVIEW-…` ⇒ rc=0，清单与首锁都有该键、stdout 无 `ignored`） | 定为「**显式给了就落盘，不设 `ignored` 第三态**」；删掉「或写 `null`」「ignored」两处；理由写进正文一句（与已落地写侧一致、与「显式给了必须落盘或报错」一致、不影响 `acceptance_cutover_unreviewed` 只对晚于默认触发） | §1.1.3（L1816）、§5.2 第 8 条、§7 V-20⑦、§0.33 次要 3 行（L744） |
| 重要 1 | review 形态校验无落点、无出口、无错误码；`init --anchor-review 坏值` 今天 rc=0 | **写侧**（`init` / `migrate`）坏值 ⇒ 用法错误、exit 2、不写文件；**读侧**坏值 ⇒ 新增 FAIL 码 `acceptance_cutover_review_malformed`、进 `errors[]`、exit 1（不用 exit 2）；码表加行，补 V-23d | §5.2 第 8 条、§5.2 码表、§6 B-0 文件表（L1974）、§7 V-23 |
| 重要 2 | V-23 缺两条已实现分支：① `migrate` 已有 review 且新值不同 ⇒ 拒覆盖；② v1 路径显式 `--anchor-review` ⇒ 抛错拒绝 | V-23 补 **e**（已有 review 不同 ⇒ exit 2、不覆盖，与 `--cutover` 同口径）与 **f**（`reader_version < 0.4.0` 下显式 `--anchor-review` ⇒ exit 2、不写文件）；§5.2 第 8 条补「v1 下 `--anchor-review` 同样拒绝」 | §5.2 第 8 条、§7 V-23e/f（L2215） |
| 重要 3 | T-32 的「⇒ PASS」错：五步跑完 `check` rc=0 但 **`overall = WARN`**（E2E 未初始化 / 模板骨架 / 成员无资产） | 三条端点改为「**exit 0 + `errors[]` 为空 + stdout 命中『验收切点：清单与锁一致』**」，并明写「本端点不断言 `overall == PASS`」；④ 恢复同样按此形态 | §7 T-32（L2117） |
| 重要 4 | T-31 落点错：`scripts/atlas_check.py` 只是聚合巡检器；真正入口 `scripts/atlas_solution.py` 当前是 `[ERROR] …` → `return 1`、不出 JSON | 落点改 `scripts/atlas_solution.py` / `_support/solution.py`；行为仍按原文（exit 2 + 合法 JSON + `not_run[]` 六项），并标注「**规则已定、实现待 B/O 批补齐**」，不写成今天已生效（**v36/次要 4 更正：该实现现已落地，见 §0.35**） | §7 T-31（L2116） |
| 重要 5 | L1972「`lock_payload` … 没有 `seal_anchors` / `acceptance_cutover_review`」与刚落地代码及 L1955 矛盾；L2236「`cat-file -t` 失败即 `continue`」与 §1.1.3 ⑦ 三态相反 | L1972 改为「没有 `seal_anchors`（C 批才建）；`acceptance_cutover_review` 在 review 非空时写」；L2236 改为引用 ⑦ 的三态判序（`-e` 判对象可读 ⇒ `chain_unverifiable`；`-t` 判形态；`absent` / `non_blob` 分列） | §6 C（L1991）、§8（L2255） |
| 次要 1 | L1905「exit 2 只有两种…码表里不得再出现第二个 `2`」与码表 `manifest_schema_unsupported` 的 `2` 字面冲突 | 改口径：exit 2 两类 = **用法错误（含 `manifest_*` 等构造前出口）** 与 `internal_error`；`manifest_schema_unsupported` 归入用法错误，不是第三类 | §5.2 第 13 条（L1924） |
| 次要 2 | 码表 `lock_history_unparsable` 只写「对象在、字节坏」，`non_blob` 算外延扩大 | 该行补「`non_blob`（tree / symlink / gitlink）属本码外延，不是『没有该路径』、不得当 `absent` 跳过」 | §5.2 码表 |
| 次要 3 | §8 残余风险的「`cat-file -t` 失败即跳过」与 ⑦ 三态不一致 | 与重要 5 同处修改：引用 ⑦ 三态，不留旧写法 | §8（L2255） |

**v35 自查**：① 全文不再有「ignored」第三态与「不写 / 或写 `null`」分支，三处口径一致为「显式给了就落盘」；② review 坏值的写侧 / 读侧出口分开（exit 2 vs `errors[]`/exit 1），码表与 V-23d 对齐；③ V-23 覆盖 a–f 六条，含 `migrate` 拒覆盖与 v1 拒绝；④ T-32 三条端点与 ④ 恢复都不断言 `overall == PASS`；⑤ T-31 落点改准并标「实现待补」；⑥ `lock_payload` 字段与 §8 三态两处陈旧句已改；⑦ exit 2 两类口径与 `non_blob` 外延已写清。评审点名**不要动**的 review 三写侧、`path_at` 三态映射、五步形式与干净口径、`manifest_*` 无 JSON、十二项回退本轮未改。**仍不宣称通过。**

### 0.35 第三十五轮返工对照

| 编号 | 第三十五轮结论（实测） | v36 改法 | 落点（节号 / 行号） |
|---|---|---|---|
| 重要 1 | `unreviewed` 与 `malformed` 的判序 / 互斥没写；且 `acceptance_cutover_unreviewed` **代码里不存在**（`_check_acceptance_cutover` 只有 `missing` / `mismatch`），V-20⑥ 是假绿 | 写死「**先空后形态**：空 ⇒ `unreviewed`（仅晚于默认）；非空坏形态 ⇒ `malformed`；两码互斥、同一字段只出一个码」；码表补 `unreviewed` 行并在两行互标互斥；标明该谓词必须与 `malformed` **同批实现**，否则 V-20⑥ 永远绿 | §1.1.3（L1833）、码表（L1927）、V-20⑥（L2230） |
| 重要 2 | T-32 引文与实际输出不符：实测 `[PASS] 验收切点: acceptance_cutover=2027-01-31（清单与锁一致）`——**半角冒号**且中间夹 `acceptance_cutover=<v>` | 断言改为 `checks[]` 中 `check == "验收切点"` 的项；纯文本模式只断言两个子串 `"验收切点:"` 与 `"（清单与锁一致）"`；注明 `--json` 没有该行 stdout，不得写「stdout 命中」 | §7 T-32（L2135） |
| 重要 3 | L1843「`migrate` 在 0.4.0 不注册」与代码不符：`p_migrate` **无条件注册**（`scripts/atlas_solution.py:183`）；0.4.0 的失败来自 `load_manifest` 版本门（`manifest_schema_unsupported`、rc=2） | 改成「注册无条件、拒绝来自读侧版本门」，不再写 argparse 未知命令 | §5.2 第 6 条（L1873） |
| 次要 1 | 早切点写入的 review 语义未写：是否仅存档、是否参与 `review_reused` 去重 | 定死：早于 / 等于默认写入的 review **仅存档**（不进 `unreviewed` 门槛，只对晚于默认触发），但**仍参与 `review_reused` 去重**（聚合口径不区分早晚） | §1.1.3（L1834） |
| 次要 2 | `non_blob` 两侧报码先后未写：⓪-0 在 ⓪-1 前且一红即短路，V-24 读起来像同一次运行两侧都报 | 补「**当前侧优先**：同一运行只报 `lock_unparsable`；两侧各报是**两条独立夹具**」 | §7 V-24（L2234） |
| 次要 3 | `check --json` 目前没有 schema v2 形状（顶层只有 `checks / e2e / errors / mode / overall / solution`） | §5.2 报告 schema 补**实现状态**：「规则层 v2 已定、出口尚未落地」；落地前 T-32 只断言 `checks[]`，不依赖 `schema_version` / `warnings[]` / `info[]` / `not_run[]` | §5.2 报告 schema（L1674） |
| 次要 4 | T-31 事实过期：`_internal_error_report` / `_emit_internal_error` 已实现（`scripts/atlas_solution.py:240-274`，check 包装 `:369-370`） | 改掉「当前 `[ERROR]` → return 1、不出 JSON」，改为「**已实现**：exit 2 + `schema_version: 2` + `errors=[internal_error]` + `not_run` 六项，夹具见对应测试」 | §7 T-31（L2134） |

**v36 自查**：① 两码判序、互斥、实现状态三处齐备（§1.1.3 + 码表两行 + V-20⑥ 标注）；② T-32 三条端点与 ④ 恢复统一用 `checks[]` / 两个子串，不再引用全角连续串；③ `migrate` 注册事实改准；④ 早 review 的「仅存档 + 参与 `review_reused`」已写死；⑤ V-24 补当前侧优先；⑥ 报告 schema 标「出口待补」且 T-32 避开未落地键；⑦ T-31 标为已实现。评审点名**不要动**的 review 三写侧、`malformed` 的 severity/exit/降级、`path_at` 三态、五步形式与干净口径、`manifest_*` 无 JSON、exit 2 两类、十二项回退本轮未改。**仍不宣称通过。**

### 0.36 第三十六轮返工对照

| 编号 | 第三十六轮结论（实测） | v37 改法 | 落点（节号 / 行号） |
|---|---|---|---|
| 阻断 | §6 B-0 只有待实现项，没有「全绿才算完成」的判据（全文 grep「完成判据 / 不得宣告 / 落地判据」0 命中），B-0 可以带着 `acceptance_cutover_unreviewed` 的假绿通过验收 | 新增 **B-0 完成判据（唯一验收门）**：五项全绿才算完成——① 两码同批 + V-20⑥/V-23d；② 三个纯函数 + 三个测试文件并登记 `shared/gates.md` 三行；③ ⓪ 层 `lock_unparsable` / `lock_history_unparsable` / `LockParseError`；④ 报告 schema v2 出口；⑤ 既有 B-0 夹具；并写死「任一项缺失，B-0 不得宣告完成」 | §6 B-0（L2008） |
| 重要 1 | `internal_error`（exit 2 + JSON）只有 `check` 走（`scripts/atlas_solution.py:240-263`、包装 `:369-370`）；其余命令未知异常仍 `[ERROR]` → **return 1**、无 JSON（`:577-579`），与「任何 exit 2 出口」通则读起来互斥 | 写死作用域：**仅限 `check` 命令**；其余命令不产报告对象、没有 `not_run[]` 可承载，仍 `[ERROR]` + return 1 | §5.2 第 13 条（L1956）、§7 T-31（L2156） |
| 重要 2 | L1674 只有约束（T-32 只用 `checks[]`、不得写成已生效），没有落地判据与交付批次 | 补**落地判据**：`check --json` 顶层 `schema_version: 2` + **五数组**（`errors` / `warnings` / `info` / `skipped` / `downgrades`；`not_run` 单列）+ 排序键 `(code, path)`（**v38 更正**：v37 把 `not_run` 误算进「五键」，且漏了 `errors`）；**交付批次 = B-0**；保留「落地前任何夹具不得引用这些键」 | §5.2 报告 schema（L1688） |
| 重要 3 | B-0 文件表没有逐行实现状态，已落地与待实现混在一起 | 逐行标「**已落地 / 待实现 / 部分已落地**」：review 三写侧、`malformed`、T-31、`_validate_rel_path(lexical=)`、`migrate --cutover/--anchor-review` 已落地；`unreviewed`、三个纯函数、⓪ 层三码、schema v2 出口、三个测试文件与 `shared/gates.md` 三行待实现 | §6 B-0 文件表（L1999） |

**v37 自查**：① B-0 完成判据五项齐备且含「任一项缺失不得宣告完成」与逐项证据要求；② `internal_error` 作用域与「exit 2 两类」不再互斥；③ schema v2 的落地判据、交付批次（B-0）与「落地前不得引用」三句齐备；④ B-0 文件表每行都有状态标签，已落地项带实测行号。评审确认已真闭合的其余各项（T-31 事实、`migrate` 无条件注册、两码互斥、先空后形态、早切点 review 仅存档、T-32 断言文本、`malformed` 实现与严重度）本轮未改。**仍不宣称通过。**

### 0.37 第三十七轮返工对照

| 编号 | 第三十七轮结论（实测） | v38 改法 | 落点（节号 / 行号） |
|---|---|---|---|
| 阻断 1 | 完成判据的封闭域与文件表不一致：文件表把 `install.py`、P-4 五处、`validate_e2e_index.py` 兜底成「待实现」，但判据一项都没提 ⇒ B-0 可以带着这些欠账「五项全绿」；且 `install.py` **已落地**（`:222-253`）被误标为欠账 | 选**方案①**：判据第 5 项改为「**文件表所有『待实现』行归零**（含 `install.py`、P-4 五处、`validate_e2e_index.py` 未落地子项），逐行给证据」；`install.py` 改**已落地**（`install.py:222-253`，`:24` / `:363` 注释与调用点一致），不计欠账 | §6 B-0 完成判据（L2025）、文件表（L2011） |
| 阻断 2 | schema v2 判据不可满足：所谓「五键」是 `warnings/info/skipped/not_run/downgrades`，**漏了 `errors`**；且要求 `not_run[]` 按 `(code, path)` 排序，但它是固定枚举字符串、没有 `code`/`path` | 一行写死：**五数组 = `errors` / `warnings` / `info` / `skipped` / `downgrades`**，排序 `(code, path)`、`downgrades` 按 `(code, scope, path)`；**`not_run[]` 固定枚举字符串、不参与排序**；全文「五键 / 五数组」统一到此定义（含 §0.36 历史行与 v37 一句话） | §5.2 报告 schema（L1700） |
| 重要 | 兜底句继续误标：`validate_e2e_index.py` 的 `archive/<month>/` 扫描已在（docstring `:163`、扫描 `:781`），至少部分落地；P-4 的 `_support/solution.py:1153` 行号过期（正确为 `:2229-2230`） | 去掉「未单列状态一律待实现」的兜底，逐项标状态；`validate_e2e_index.py` 标「部分已落地（archive 扫描已落地，其余待实现）」；P-4 的 WARN 项改 `:2229-2230` 已落地，其余四项逐项标「待实现」 | §6 B-0 文件表（L2011） |

**v38 自查**：① 判据第 5 项现在覆盖文件表全部「待实现」行，`install.py` 不再被误记为欠账；② 「五数组」全文只有一个定义（`errors/warnings/info/skipped/downgrades`），`not_run[]` 明确不排序；③ 文件表每行状态逐项给出，不再有整行兜底；④ `archive` 扫描与 WARN 行号两处按实测更正。评审确认本轮不要动的 `internal_error` 作用域、review 三写侧 / `malformed` 标注、`_validate_rel_path(lexical=)`、`migrate --cutover/--anchor-review`、T-31、T-32 断言文本、三区间算术与十二项回退均未改。**仍不宣称通过。**

### 0.38 第三十八轮返工对照

| 编号 | 第三十八轮结论 | v39 改法 | 落点（节号 / 行号） |
|---|---|---|---|
| 1 | L2025 括号举例与表不一致：既写「含 `install.py`」又写「`install.py` 已落地、不计欠账」；「P-4 五处」实为 6 条待实现；漏了 `shared/gates.md` 与两个代码行 | 删「含 `install.py`」，保留「已落地、不计欠账」；括号改为逐条列全：`shared/gates.md`（三个测试文件 + 三行登记）、P-4 六条、`_support/solution.py` 7 项、`scripts/atlas_solution.py` 的 schema v2 出口 | §6 B-0 完成判据第 5 项（L2037） |
| 2 | L2012 仍留 `_support/solution.py:1153`，与 L2016 的 `:2229-2230` 重复且过期 | 删 `:1153`，改为「运行期 WARN 文案见 P-4 行的 `:2229-2230`」，全文只保留一处行号引用 | §6 B-0 文件表（L2024） |
| 3 | L2017 三项状态误标待实现，实际已在 `:782-823` 落地 | 翻正为**已落地**，附证据 `:782-823`（`archive` 扫描 `:163`/`:781`、任意用例行 `task_dir_case_duplicate`、成员任务目录、分级文案 `:816`），并注明未发现未实现子项 | §6 B-0 文件表（L2029） |
| 冻结 | 需给出冻结基线与冻结约定 | 头部写 **v39 冻结基线**、行数、基线提交 `411c971`；加冻结约定：只有 C 批与 B 批实现反馈可改，规则层争议进 C 批，B-0 期间不再改 | 头部（L4–L5） |

**v39 自查**：① 判据第 5 项的括号与文件表逐项对应（`shared/gates.md`、P-4 六条、`solution.py` 7 项、`scripts/atlas_solution.py` schema v2），`install.py` 只作「已落地、不计欠账」出现；② 全文不再有 `:1153`，WARN 行号只保留 `:2229-2230`；③ `validate_e2e_index.py` 四项均已落地并有 `:782-823` 证据；④ 头部含冻结基线、行数、基线提交与冻结约定。评审点名不要动的五项判据结构、五数组定义、`internal_error` 作用域、review 三写侧 / `malformed` 标注、`_validate_rel_path(lexical=)`、`migrate` 标注、T-31、T-32 断言文本、三区间算术与十二项回退均未改。

### 0.39 第三十九轮收尾修订

| 编号 | 第三十九轮结论 | v40 改法 | 落点（节号 / 行号） |
|---|---|---|---|
| 1 | L187 的「B-0 文件表加入…」落点清单仍写 `_support/solution.py:1153`，读起来像现行指令 | 改为 `_support/solution.py:2229-2230`（注明原 `:1153` 已过期），与 §6 P-4 行一致；此后 `1153` 只留在历史摘要与缺陷记录里，不再有权威落点引用 | §0.5 落点清单（L187） |
| 2 | L2038「分级文案 `:816`」不精确：`:821` 才是 `second_level = "FAIL" if _version_at_least(...) else "WARN"` 的判定行，`:816` 是 `reader_version_unknown` 提示 | 改为「分级判定 `:821`」并注明 `:816` 的含义；证据区间仍为 `:782-823` | §6 B-0 文件表（L2038） |

**v40 自查**：① §0.5 落点清单已无权威性 `:1153` 引用；② §6 B-0 文件表的分级判定行号改为 `:821`、`reader_version_unknown` 提示保留 `:816` 说明；③ 其余内容（含 v39 冻结约定与全部判据）未动，版本号 / 行数按实测更新，冻结基线不变（`411c971`）。

### 0.40 C 批口径修订（v41）

| # | 缺口 | v41 改法 | 落点（节号 / 行号） |
|---|---|---|---|
| 1 | crosswalk 解析器归属未定，易被塞进 2600+ 行的 `_support/solution.py` | 独立模块 `_support/ac_crosswalk.py`；公开面 `parse_crosswalk`（纯函数）与 `crosswalk_findings`（产 C-01…C-08），路径 helper `resolve_crosswalk_path` 供封条 role 用；调用方 = `check_solution` / `validate_ac_alignment`（D）与封条 upstream（仅路径）；**D 批交付，C 不 import** | §2.1、§6 D（L2128） |
| 2 | §1.3.2「成员 AC 也必须是 crosswalk 像」与 §1.3「只对源 PRD 已定义 AC 判」自相矛盾，C 夹具只列了集合判据 | 裁定 **C 批卡门只判 `⊆ requirements[].acs`**，crosswalk 像 / 孤儿 AC 整体归 D；改正两处口径并在 §6 C 夹具写明边界 | §1.3.2、§1.3 判据、§6 C（L2114） |
| 3 | 封条 `prd-domain` / `ac-crosswalk` 何时开始绑未定，且「有成员 AC / 有映射时是」会让 C 依赖未落地的解析器 | **C 批只按文件存在性做字节绑定、不做语义校验；文件不存在 ⇒ role 缺席、不拒签**；与「有映射时是」的关系写清（那两句归 D） | §2.5 |
| 4 | 锁内 `requirements_digest` / `waiver_baseline_digest` 没写首次判定、不可变与 canonical 口径 | 首次判据 = **锁里尚无该键**（**已被 v42 取代**：改为「键不存在或 `null`」+ 三路径 + `manifest_digest_removed` / `manifest_rollback`）；同一序列化器 + golden vector（`waiver` 向量 `f1da37a3…`）；已写入后只复算比对、**不得静默改写**；`waiver_baseline_drift` 判据仍归 D（**v42 移入 C**） | §1.1 8-b（L1207） |
| 5 | §五-b 字段契约 AC 无表头 / 列 / 编号 / 异常码 / 与 §五 的关系，E-04 无可执行形态 | 最小 schema：表头含 `契约AC`；六列 `契约AC / 字段 / 类型 / 必填 / 异常码 / 关联AC`；编号 `AC-CONTRACT-\d{3}`；`关联AC` 回指 §五 方案 AC；E-04 ⇒ `contract_ac_undefined`，缺表 ⇒ `contract_ac_table_missing`，悬空 ⇒ `contract_ac_orphan` | §1.5 第 7 条（L1381）、码表（L2033） |
| 6 | 任务卡 Confirmed 口径没有证据状态（#53 原文要求），只设计了 PRD Assumptions | 卡内 `Confirmed` / `确认口径` 表：`确认项 / 口径 / 证据状态 / 证据指针`；枚举 `verified/assumed/unverified`；C 批成员 `validate_task_card` 执行，父仓 N/A；新增 `confirmed_columns_missing` / `confirmed_evidence_missing` / `confirmed_unverified` | §1.5 第 8 条（L1387）、K-20…K-22 |
| 7 | §1.5 说「B 批写 1、D 批升 2」，与实况 `prd_schema: 2` 不符 | 改为实况：模板已 `prd_schema: 2` 且证据两列已落地（B 批）；D 批不再升版本 | §1.5 第 5 条、§1.1 第 7 条 |
| 8 | #51 双向对账只在 crosswalk 显式行内判，未列进的成员 AC 无判据 | 明确 **C-03 只对显式映射对账**；孤儿成员 AC 不判（理由：需解析成员 PRD，依赖 D 模块）；D 批可选 `crosswalk_orphan_member_ac` WARN，是否升 FAIL 留 §9 | §2.1、C-10 |

**v41 自查**：① `_support/ac_crosswalk.py` 的归属、公开面、调用方、批次四件齐备；② 卡门两处口径一致，§6 C 夹具写明「crosswalk 像 / 孤儿不判」；③ 两个 upstream role 的 C 批语义与「有映射时是」的关系写清，C 不依赖解析器；④ 两个 digest 的首次判据、序列化器、golden vector、不可改写四件齐备；⑤ §五-b 六列 / 编号 / `关联AC` / 三个新码（含 `contract_ac_table_missing`）落齐；⑥ Confirmed 的字段、枚举、判据、执行点四处齐备，并配 K-20…K-22；⑦ 模板实况与 §1.5 一致；⑧ 孤儿 AC 的「不判」写明了理由与 D 批可选项。**不宣称评审通过。**

### 0.41 v41 独立评审返工对照（v42）

| # | 评审项 | 处置 | 改法 | 落点 |
|---|---|---|---|---|
| 阻断 1 | 首次判据与锁 schema 矛盾（`null` 恒存在） | 接受 | 判据改为「键不存在**或值为 `null`**」；`waiver_baseline_digest` 首锁写 `null`、不省略；**`requirements_digest` 只改「首次」判据，首锁写实际值、不写 `null`** | §1.1 8-b |
| 阻断 2 | 「键不存在即首次」可被删键绕过 | 接受 | 三路径分开：升级走首次、换锁（历史有非 null）⇒ `manifest_digest_removed`、回滚（`prd_version` 递减 / digest 回旧值）⇒ `manifest_rollback`；读侧键缺失行为写死 | §1.1 8-b、§5.2 码表 |
| 阻断 3 | `crosswalk_findings` 签名产不出 C-01…C-08 | 接受 | 补 `reader: MemberPrdReader`（`paths` / `exists` / `front_matter` / `ac_ids`）；`CrosswalkParseError.code` 闭集五项；**重复键归 findings（C-05）**，parse 不抛；文件缺失由调用方判 `crosswalk_unresolvable` | §2.1 |
| 阻断 4 | 契约 AC 引用面与卡门右集互斥，E-04 不可达 | 接受（方案 a） | `AC-CONTRACT-*` **纳入 `requirements[].acs` 合法值域**；列出三处允许引用面，禁止进成员 AC 位置；`shared/solution.md:48` 随 D 同步 | §1.5 第 7 条 |
| 重要 1 | C 批仍有成员 PRD 路径依赖 | 接受 | `prd-domain` 用 `members[].path` + `prd/*-prd.md` **glob 全绑**（只列路径）；`resolve_crosswalk_path` 不产成员列表 | §2.5 |
| 重要 2 | 「缺席不拒签」致 D 批追溯翻红 | 接受 | `upstream[]` 只落已绑定 role；D 批推导期望 role，缺项 ⇒ `seal_upstream_unbound` WARN，至 **D 批首版 + 90d** FAIL；出口 = 续签补绑（v43 已修正 `min` 反向） | §2.5、码表 |
| 重要 3 | `waiver_baseline_drift` 留 D，C 读侧无码 | 接受 | **移入 C**（纯摘要比对、不依赖 crosswalk），C 读侧差异直接 FAIL | §1.1 8-b、码表 |
| 重要 4 | Confirmed 可重贴标签降级 | 接受 | 降级 / `assumed↔unverified` 互转须 `REVIEW-ID`，否则 `confirmed_downgrade_unreviewed` FAIL；定义 `assumed`=有默认值来源、`unverified`=无来源 | §1.5 第 8 条 |
| 重要 5 | K-17 是退役编号被复用 | 接受 | 新三条改用 **K-20…K-22**；码表 `confirmed_evidence_missing` 的引用由 `K-17` 改为 **K-21** | §7、§5.2 码表 |
| 重要 6 | 反包区间未扩、C-09/C-10 假绿 | 接受 | 区间改 `C-01…C-11` / `K-01…K-22` / `E-01…E-12`；C-09 改成「映射到错误方案 AC」；C-10 改成「默认配置断言**不产生**该码」 | §1.3/§1.5/§2.1 判据、§7 |
| 重要 7 | §6 D 文件行与正文相反、缺契约 AC 夹具 | 接受 | 文件行删「由 1 升 2」；D 夹具补契约 AC 正例 + 五类反例（缺表头 / 未定义 / 悬空 / 重复 / 编号错） | §6 D |
| 重要 8 | §1.3 成员侧枚举未同步 Confirmed | 接受 | 枚举加 Confirmed 证据状态；「不判证据列」限定为「不判 **PRD** 的证据列」 | §1.3 |
| 次要 1 | 历史行号大面积漂移 | 接受 | 把评审点名的 5 处改节锚（`§5.2 第 8 条`、`§5.2 码表`、`§7 V-20⑦`、`§7 V-23`、`§8 数组 C`）+ v40 自查两处；**正文仍有历史行号（历史记录，不作权威锚）**；双前缀 `§7 §7` 已删 | §0.35 / §0.39 / §0.40 |
| 次要 2 | §1.5 条目编号乱序（5,7,8,6） | 接受 | 把「6. 严格态」移回第 5 条之后，顺序 1…8 | §1.5 |
| 次要 3 | 「两个新码」实为三个；缺 `contract_ac_table_missing` | 接受（已落） | v41 一句话、§1.5 第 7 条、§0.40 均已含 `contract_ac_table_missing`；v41 自查改「三个新码」 | §1.5 第 7 条、v41 一句话、§0.40 |
| 次要 4 | 「C 批」被用来指 crosswalk 反包族 | 接受 | 改为「**crosswalk 检查族（D 批）**」 | §2.1 孤儿段、C-10 |
| 次要 5 | `shared/solution.md:44` 错位 | 接受 | 改 `:48`（`requirements[].acs` 规则所在行） | §2.1 |
| 次要 6 | `confirmed_parent_only` 未进 N/A 表 | 接受 | 新增 **E-12**：父仓判 Confirmed 证据状态 ⇒ N/A `confirmed_parent_only` | §7 E-12 |
| 次要 7 | §0.4 旧口径无历史声明 | 接受 | §0.4 标题下加「历史表，以正文为准」声明，点名两处已被 v41/v42 取代 | §0.4 |
| 横切 | 孤儿成员 AC 决定挂在 §9 但 §9 没有 | 接受 | §9 新增第 2 条开放问题：`crosswalk_orphan_member_ac` 是否升 FAIL，三选项，未定前默认 (a) 可选 WARN | §9 |

**v42 自查**：① 摘要两键的「缺失 / `null` / 历史」三态与三路径（升级 / 换锁 / 回滚）逐条有码；② findings 签名含 `MemberPrdReader`，四类失败形态各只有一个归属；③ 契约 AC 的引用面与卡门右集一致（`requirements[].acs` 已含它），E-04 可达；④ C 路径推导不依赖解析器，D 追溯窗有码与截止；⑤ `waiver_baseline_drift` 在 C；⑥ Confirmed 降级有门；⑦ 区间 / 编号 / 文件行 / §9 全部对齐。**不宣称评审通过。**

### 0.42 v42 复核返工对照（v43）

| # | 评审项 | 处置 | 改法 | 落点 |
|---|---|---|---|---|
| 阻断 1 | `manifest_rollback` 误伤合法回退、无出口 | 接受 | 删「digest 回到历史旧值」一支；只留 `prd_version` 递减；内容回滚不判 | §1.1 8-b |
| 阻断 2 | `min(cutover, D+90d)` 反向、D 上线无源 | 接受 | 改 `D 批首版 + 90d`，钉常量 `SEAL_UPSTREAM_BIND_FROM`；正文与码表统一；`frozen` 豁免 | §2.5、码表 |
| 阻断 3 | 契约 AC 无隔离、禁令无码 | 接受 | 排除 C-01/C-04/`ac_missing`/方案 AC 校验；`方案AC` 列仅 `AC-SOLUTION-*`；新增 `contract_ac_in_member_slot`；L1471 改「方案 AC + 契约 AC」；补 D 夹具 | §1.5 第 7 条、§2.1、码表、§6 D |
| 阻断 4 | `crosswalk_unresolvable` 未进码表、C-11 悬空 | 接受 | 码表补两码；C-11 定义 `member_domain_mismatch`；写清抑制关系 | §5.2 码表、§7 C-11 |
| 重要 1 | waiver 首锁 `null` 与「首次算值」互斥 | 接受 | 唯一写入点 = 首次观察到非空集合的 `lock --update`；`null`/`[]` 语义分开 | §1.1 8-b |
| 重要 2 | 三摘要码无判序、批次不一、无 `field` | 接受 | `manifest_rollback` 优先并抑制另两码；`detail.field`；批次写明 B-0 / C | §1.1 8-b、码表 |
| 重要 3 | `waiver_baseline_drift` 只移码未移夹具 | 接受 | 夹具移 C；C 文件表加 `ac-crosswalk-waivers.md`；缺失 ⇒ `[]` | §6 C |
| 重要 4 | 5 新码零反包、E-12 越界 | 接受 | 补 D-41…D-45；E 区间 `E-01…E-12`；E-12 移到 E-11 后 | §7 |
| 重要 5 | 降级判据需要历史但成员侧不读 | 接受 | 改可实现形态：当前 `unverified`/`assumed` 行必须带 `confirmed_review:` | §1.5 第 8 条 |
| 重要 6 | Reader 产不出 C-06/C-07；`member_unknown` 非纯函数 | 接受 | findings 增 `waivers` 入参；parse 闭集改 `member_field_empty`，`member_unknown` 归 findings | §2.1 |
| 重要 7 | §0.41 三处 overclaim / 一处低报 | 接受 | K-17→K-21、§1.3→K-22、删 `§7 §7`、v41 一句话恢复原文、§0.40 标「已被 v42 取代」、次要 3 改「接受（已落）」 | §0.40 / §0.41 |
| 次要 1 | §9 编号 1,2,2,3 | 接受 | 顺延为 1/2/3/4 | §9 |
| 次要 2 | E-12 插在 E-06 与 E-07 之间 | 接受 | 移到 E-11 之后 | §7 |
| 次要 3 | `manifest_digest_removed` 缺 `field` | 接受 | `detail.field` + `detail.prd_version` | §1.1 8-b、码表 |
| 次要 4 | 「`requirements_digest` 同治」歧义 | 接受 | 写明：只改「首次」判据，首锁写实际值、**不写 `null`** | §0.41 |
| 次要 5 | `frozen` 缺豁免 / 出口 | 接受 | `state=frozen` 豁免 `seal_upstream_unbound`；出口 = 解冻补绑或续签 | §2.5、码表 |

**v43 自查**：① 回滚码只按版本递减，无永久红；② 追溯窗口正向（D+90d）、有常量与 frozen 例外；③ 契约 AC 的排除清单、禁令码、`方案AC` 值域三件齐；④ 两个新码进码表、C-11 有码且抑制关系写清；⑤ waiver 基线唯一写入点、`null`/`[]` 区分；⑥ 三码判序与 `detail`；⑦ 夹具迁移与五条新反包；⑧ §0.41 的 overclaim 逐条回收。**不宣称评审通过。**

### 0.43 冻结前 8 条清单（v44）

| # | 清单项 | 处置 | 改法 | 落点 |
|---|---|---|---|---|
| 1 | `frozen` 豁免无真出口 | 接受，选 **(c)** | frozen 封条缺绑定 ⇒ **永久 WARN**（不阻断、不可 `--strict` 升级），每次进 `warnings[]` 并打印 `seal_upstream_unbound(frozen=N)`；不新增 `unfreeze`；补常量发版门（== D 首 tag UTC 日期）与 D-48 | §2.5、§6 C 文件表、码表、D-48 |
| 2 | C 区间两处未同步 | 接受 | §1.2 与 §2.1 的 `C-01…C-10` 均改 `C-01…C-11` | §1.2、§2.1 |
| 3 | 抑制清单漏 C-09、与 D-45 矛盾 | 接受 | 统一为 **抑制 C-01…C-11**；`crosswalk_unresolvable` = 缺失/不可读，坏行另归 `crosswalk_parse_error`；C-01 注释同步 | 码表、D-45、C-01 |
| 4 | K 引用指错 | 接受 | `confirmed_evidence_missing` 的引用改回 **K-20** | 码表 |
| 5 | `contract_ac_in_member_slot` 零反包 | 接受 | D 夹具补两例（`成员AC = AC-CONTRACT-001`；成员 PRD AC 表出现契约 AC）；新增 D-46 | §6 D、D-46 |
| 6 | Confirmed 收窄 | 接受 | `verified` 无指针 ⇒ FAIL；`assumed` 只要默认值来源指针；**只有 `unverified`** 要 `confirmed_review:`（`REVIEW-\d{8}-\d{2}`），带 review 时不再报 `confirmed_unverified`（互斥） | §1.5 第 8 条 |
| 7 | C 夹具 waivers 断言反了 | 接受 | 拆两态：基线 `null` + 缺文件 ⇒ 不判；基线非 null + 缺文件 ⇒ `waiver_baseline_drift` FAIL | §6 C |
| 8 | `CrosswalkParseError.code` 无报告出口 | 接受 | 新增 `crosswalk_parse_error`（1 / `errors[]`、不可降级、D 批），`detail.kind` 取五值；配 D-47 | 码表、§2.1、D-47 |

**v44 自查**：① frozen 不再永久红也无入口，改为可见的永久 WARN，且有常量发版门；② 两处 C 区间与 C-11 一致；③ 抑制清单与 D-45 统一、两码互斥；④ K-20 指向正确；⑤ 禁令码有 D-46 与夹具两例；⑥ Confirmed 不再逼 `assumed` 上评审、无双报、有格式；⑦ waivers 两态拆开；⑧ 解析失败有独立码与 `detail.kind`。仅清这 8 条，其余未动。**不宣称评审通过。**

## 1. 域模型（v45）

### 1.1 定义源：显式、受约束、可复算、需求摘要

**改了什么**

1. 清单 v2：

   ```yaml
   version: 2
   acceptance_cutover: 2027-03-31
   acceptance_cutover_review: null   # v19/阻断 2：仅当 cutover 晚于包级默认 2027-03-31 时写 REVIEW-ID
   min_atlas: "0.4.0"
   definition:
     domain: solution
     path: product/prd/solution-prd.md
   ```

2. 锁增加（本节字段集合；`acceptance_cutover` 随清单 v2 在 **B-0** 的 `lock --update` 里写入——清单 v2 ⇒ 锁 `schema_version: 2`，两者同源；旧 v1 锁仍只有 `members` / `contracts`，§5.1）：

   ```json
   {
     "definition": {
       "path": "product/prd/solution-prd.md",
       "domain": "solution",
       "domain_code": "SOLUTION",
       "prd_version": 3,
       "prd_schema": 2,
       "prd_date": "2026-11-11",
       "sha256": "<sha256 of CRLF-normalized blob bytes>",
       "blob": "<git blob object id>",
       "commit": "<commit containing blob>"
     },
     "requirements_digest": "45ef0f9a94ee9f118f5254caf69fdb4b14667483b8f7023cfb90ffe3386afdd1",
     "acceptance_cutover": "2027-03-31",
     "acceptance_cutover_review": null,
     "legacy_allowlist_sha256": null,
     "allowlist_frozen_at": null,
     "waiver_baseline_digest": null,
     "layout_assets_root": "product",
     "assets_root_history": [
       { "root": "product", "review": null, "commit": null }
     ],
     "seal_anchors": {
       "product/reviews/apply/auth/T-0001.seal.json": {
         "epoch_origin": "<该路径当前纪元起点的提交 sha>",
         "epoch_origin_history": ["<该路径当前纪元起点的提交 sha>"],
         "renewal_seq": 2,
         "n": 2,
         "anchor_review": null,
         "state": "active",
         "exemption_start_origin": "2026-11-11T08:00:00Z",
         "exemption_started_at": "2026-11-11T08:00:00Z",
         "exemption_start_history": [],
         "first_seen_origin": "<该路径首签封条载荷的 first_seen_at>"
       },
       "product/reviews/apply/auth/T-0000.seal.json": {
         "epoch_origin": "<旧路径纪元起点的提交 sha>",
         "epoch_origin_history": ["<旧路径纪元起点的提交 sha>"],
         "renewal_seq": 4,
         "n": 4,
         "anchor_review": null,
         "state": "retired",
         "moved_to": "product/reviews/apply/auth/T-0001.seal.json",
         "exemption_start_origin": "2026-10-01T08:00:00Z",
         "exemption_started_at": "2026-10-01T08:00:00Z",
         "exemption_start_history": [],
         "first_seen_origin": "<该路径首签封条载荷的 first_seen_at>"
       },
       "product/reviews/apply/billing/T-0007.seal.json": {
         "epoch_origin": "<该路径纪元起点的提交 sha>",
         "epoch_origin_history": ["<该路径纪元起点的提交 sha>"],
         "renewal_seq": 3,
         "n": 3,
         "anchor_review": null,
         "state": "frozen",
         "frozen_at": "<冻结提交 sha>",
         "exemption_start_origin": "2026-09-20T08:00:00Z",
         "exemption_started_at": "2026-09-20T08:00:00Z",
         "exemption_start_history": [],
         "first_seen_origin": "<该路径首签封条载荷的 first_seen_at>"
       }
     }
   }
   ```

   - **资产根（v15/D-1；v16/D-1 重写；v17/B-1 改严格解析）**：锁落两个字段——`layout_assets_root`（**当前**根，字符串）与 `assets_root_history[]`（**append-only** 的历史，元素是对象 `{root, review, commit}`；首元素 = 首次 `lock --update` 时的根，`review`/`commit` 为 `null`）。理由：`atlas.config.yaml` 与 `atlas.solution.lock.json` **都是被检查方提交的文件**；v15 把根搬进锁，但 ⓪ 只读**当前**锁，于是「删封条 + `git mv product product2` + 改 config + 锁整段重写成 `assets_root_history: [{root: "product2",...}]` + `seal_anchors: {}`」在 ⓪ 全绿、`U=∅`、键 `∅`，封条提交仍可达；「删锁 → 改根 → 重建锁」同绕。v16 的判据锚到**锁文件的历史版本**，但参考实现用 `jq` 逐版本解析，解析失败被管道吞掉（v17/B-1 阻断）——v17 起历史版本一律走**同一严格解析器**。规则：
     ① **根集（`U` 的根 `UH`）** = **锁文件全部历史版本**的根并集，逐个版本用 §1.1.3 第 2 条 ① 的 `historical_roots()`——与读当前锁**同一个严格解析器**，不另写 shell / `jq`。规则：`schema_version == 2` 且该版本有 `assets_root_history` ⇒ 逐元素取 `.root`（元素级合法性由解析层负责，见 ④）；`schema_version == 2` 但该版本没有该字段 ⇒ 这个版本不贡献根（历史版本不要求当前字段，见 §1.1.3 第 2 条 ②；当前锁缺字段由 ② 判）；**`schema_version == 1` 的版本一律不贡献根**（v19/次要 2：结构原因——写侧 `lock_payload` 只在清单 v2 时写 `layout_assets_root` / `assets_root_history` 两个字段，v1 锁里**根本不存在**该字段，不是「有而不取」；因此也**不回落 config 根**，v17 的 `config_root_at` 回落分支删除）。**可达性写死（v19/次要 3）**：`UH` 只信 **HEAD 可达**的锁历史（`git log ... HEAD -- <lock>` 的祖先集）；orphan 分支、已删分支、reflog 里的锁版本**不进** `UH`——它们无法被 `--full-history` 枚举，也不属于当前仓的可证历史。**任一版本解析失败或结构不合法 ⇒ `lock_history_unparsable` FAIL，不得跳过**（v17/B-1；v18 阻断 1/2）。命令与读取层见第 2 条。
     ② **`assets_root_history_rewritten`（v16；v18/重要 3 收口为「当前锁 schema + 包含关系」唯一判点；v19/阻断 1 换单一字符集源；v21/B-1 改按索引分层）**：只对**当前锁**判——当前 `assets_root_history` 非空、元素 `.root` 互不相同、`layout_assets_root == assets_root_history[-1].root`、`hist[-1]` 走默认严格版 FS、并且**包含**①的历史并集 `UH`（可以多出「本版本刚 append 的根」，但不得少任何一个历史根）；当前锁缺这两个字段而**历史任一版本有** ⇒ 同码（覆盖「删锁 → 改根 → 重建锁」）。**不参与 `--allow-unverifiable-chain` 降级。** 次序上它排在 `lock_unparsable` / `lock_history_unparsable` 之后：**结构与词法合法性已在解析层判完**（v22/B-1），这里只判「元素重复 / `layout != last` / `hist[-1]` 严格版 FS / 包含 `UH`」；`hist[:-1]` 的 lexical、数组非空、首尾空白属解析层已判，**这里只做防御性复核、不作为本码的触发条件**（v23/次要 1）。**字符集单源（v19/阻断 1）**：RFC **不再定义**第二套根字符集判据；`validate_value` 就是唯一判据。`ROOT_RE`（若保留）**只作「新增根」的写侧建议**（CLI 提示、文档示例），**任何 FAIL / PASS 都不得由它得出**。理由：`_support/layout.py` 的校验**不禁中文与空格**，而 `install.py --assets-root` 走的正是它；`assets_root_history` 又是 append-only、写侧禁归一化——若 RFC 另立一套更窄的字符集，合法装进去的根会**永久红且无出口**（不能删元素、不能改元素、不能改名）。存量根按 `layout.py` 的**两层判据**（v20/阻断 1；v21/B-1 改「按索引」）：`validate_value(..., lexical=True)` **只做词法校验**（非空、绝对路径、空段 / `.` / `..`、保留首段 `.atlas` / `.trellis`、引号 / `#` / 换行），**零 FS 访问**；默认的严格版额外判「已存在但不是目录」「symlink 逃逸」。**当前锁的数组按索引分层**：`assets_root_history[:-1]`（所有历史元素）**一律 `lexical=True`**；**只有末元素**（必须 `== layout_assets_root`，**按索引 `hist[-1]` 取，不按值匹配**——同值重复时无法用值区分）走**严格版**。理由：数组 append-only，历史根永远留在当前数组里；若「每个根都严格」，历史根今天被删、被换成仓外 symlink 或被换成普通文件，就会把整个数组永久判红且无出口（S-51 三个变体）。**历史版本（`historical_roots()` 读到的每个版本）内的所有根一律 lexical**，不因今天的工作树反判历史。**首尾空白一律判红，解析层与写侧都拒（v21/I-1）**：`_validate_rel_path` 必须在 `raw = value.strip()` **之前**先判 `value != value.strip()`（否则两层都被静默 trim，写侧根本没拒）；写侧 `install.py --assets-root` / `lock --update --assets-root` 的语义是「**拒，不 trim**」，与第 2 条 ④「写侧不得归一化」一致。理由：若校验用 strip 后的串、入集合用原串，glob 一个路径都匹配不到。
     ③ **`assets_root_changed`（v15）**：`atlas.config.yaml` 的 `layout.assets_root` 现值必须 `∈` 当前 `assets_root_history` 的 `.root` 集合，否则该码 FAIL。次序在 ② 之后：先证明锁没被改写，再证明 config 与当前锁一致。**缺键口径（v17/次要 5）**：config 里没有 `layout.assets_root` 键 ⇒ 按 `_support/layout.py` 的默认值 `product` 取（与实现同源，不另定默认）；**config 文件本身缺失 ⇒ `assets_root_changed` FAIL**（不是「跳过」）。
     ④ **解析层的边界（v18/阻断 1、重要 3；v19/阻断 1 换字符集源；v22/B-1 词法归位）**：解析层（`load_lock_strict`）判五类——① 不是合法 JSON 对象；② `type(schema_version) is int and not isinstance(schema_version, bool)` 为假，或值 ∉ `{1,2}`；③ 字段类型不对（`assets_root_history` 存在但不是数组、`layout_assets_root` 存在但不是字符串、`members` / `contracts` 存在但不是 list-of-dict）；④ `assets_root_history` 存在时**元素级**不合法（数组为空、元素不是对象、`.root` 缺失或不是非空字符串、或 `.root` 首尾带空白）；⑤ **词法**——每个 `.root` 调 `layout.validate_value(..., lexical=True)`（**零 FS**）。**词法就在这里判，不在 ⓪-3 重复**（v22/B-1：同一输入只能落一个码）；字符集判据只有 `layout.validate_value` 一个源（v19/阻断 1）。**⓪-3 只判**：`layout_assets_root == assets_root_history[-1].root`、`hist[-1]` 的默认严格版 FS、`.root` 集合 ⊇ `UH`、元素 `.root` 互不重复；**`hist[:-1]` 的 lexical 与数组非空已在解析层判定，这里只作防御性复核**（v23/次要 1）。**历史版本**违反任一 ⇒ `lock_history_unparsable`（⓪-1）；**当前锁**违反任一 ⇒ `lock_unparsable`（⓪-0）。**`[]` 归属写死**：当前锁 ⇒ `lock_unparsable`；历史版本 ⇒ `lock_history_unparsable`；⓪-3 永远不会看到空数组。**`members` / `contracts` 的一条口径（v19/次要 1；v20/次要 2）**：**当前锁必须两者齐备**（`load_lock_strict(..., current=True)`，缺失即 `lock_unparsable`）；**历史版本「存在则校验」，缺失视为旧工具产物放行**（`current=False`，不报 `lock_unparsable`）。**历史版本永不要求** `definition` / `seal_anchors` / 两个根字段存在（见 §1.1.3 第 2 条 ②）。
     ⑤ **唯一写入出口**：`lock --update --assets-root <new> --anchor-review <REVIEW-ID>`（第 12 条）；append 新的 `{root, review, commit}`、不删旧元素、不重排；评审号只进**历史元素**，**绝不写进任何键的 `anchor_review`**（v16/I-2：`anchor_review` 的定义是「创建当前纪元的那次 reanchor 的 REVIEW-ID」，覆写会让 4a/4b 对做过 reanchor 的路径假红，S-30 的多纪元外部锚也会被破坏）。**`commit` 的语义写死（v17/次要 4）**：**仅审计、不参与任何断言**；首元素固定 `null`（首次建键时该提交的 SHA 尚不可知），后续元素 = **执行该条 `--assets-root` 命令时的 HEAD**（即携带新根的锁提交的父提交；不是新根首次出现的提交，也不做可达性校验）。
     ⑥ **改根 + 删旧键 ⇒ 必红**：旧根仍在历史并集里 ⇒ `U` 仍含旧路径 ⇒ 键缺 ⇒ `seal_anchor_path_unmapped`（S-43）。**即便 ② 被绕过，`U` 也不缩**——根集取自历史版本而不是当前锁，这是与 ② 独立的一道防线。
     ⑦ **锁内自述值的锚（v23/I-1；v24/I-1、B-2 收口，统一口径）**：凡是「建键写死、之后只许 append / 不改写」的锁内值，其期望值**一律取锁文件历史**，不靠当前锁自证。取法统一为：`git log -m --full-history --reverse --format=%H HEAD -- atlas.solution.lock.json` 逐版本取出，用 §1.1.3 的 `load_lock_strict(..., current=False)` 解析。**按值形态分四类，判据各一条，不得互相套用**——**append-only 只是叙述，判据以下列四条为准**：
        - **标量**（`exemption_start_origin` / `first_seen_origin`）：锚 = **首个同时含有该字段的版本**里该字段的值；当前值 ≠ 锚 ⇒ 对应 `exemption_start_origin_rewritten` / `first_seen_origin_rewritten` FAIL。**存量键**的首个「含该键」版本没有该字段（v22/v23 写的锁）⇒ 锚顺延到**首个同时含该字段的版本**（即回填提交）；回填之前一律按「缺字段」处理、不判 rewritten。**取锚为空（v25/次要 4）**：当前锁尚未提交（工作树有字段、历史无该字段）⇒ **跳过** rewritten 判定（视为缺字段）；`seal_anchors` 为 `null` 或非 dict 时取锚按「无该键」容错，**不得抛异常**（不许落到 `internal_error`）。
        - **数组 A（`assets_root_history`）**：`UH` 并集 + `layout == hist[-1]` ⇒ `assets_root_history_rewritten`（判据不变）。
        - **数组 B（`epoch_origin_history`）**：末元素 == 当前 `epoch_origin` + 长度 == `1 + 重指次数`（次数由锁历史逐版本比较）⇒ `epoch_origin_history_rewritten`（判据不变）。
        - **数组 C（`exemption_start_history`）**：版本前缀单调（后版本是**紧邻前一版本**的前缀扩展、相邻版本至多新增一项；v28/B-1）⇒ `exemption_start_history_broken`。**判据本体抽成纯函数（v26/I-1）**：`check_history_prefix(versions: list[list[Entry]]) -> Ok | Err(code, detail)`，其中 `Entry = {from: str, to: str, commit: str}`（`commit` **仅审计、不参与判定**，见下条）；`versions` = 按 `git log -m --full-history --reverse --format=%H HEAD -- atlas.solution.lock.json` 顺序逐版本解析出的 `exemption_start_history[]` 序列（**每个元素是 `list[Entry]`，该版本缺该键时为空列表 `[]`**）。**`versions` 的构造口径（v30/B-1；v32/I-2 抽成独立纯函数 `build_lock_versions(commits, fetch, worktree, head_has_path)`）**：① **`git log` 序列按 commit SHA 去重**（**构造层清理动作、不产生判据**）——`-m --full-history` 对 merge 提交会因多父而重复输出同一提交，同一 `%H` 只保留一条，去重后保持 `--reverse` 的时间正序、重复提交视作同一版；**理由只是整洁**：重复项内容相同，只会多出一对恒真比较，不会跳过任何真实的相邻对，故「不去重会恒真」是夸大（v29/I-1）；② **历史层：某版本没有该路径 ⇒ 跳过、不得记 `[]`**——逐版本取值一律经 `path_at(c)`：**`absent` ⇒ 该提交没有该路径、`continue`**（沿用 ⓪-1 的同一惯例，v30/B-1(a)；**对象不可读 / `non_blob` 不在此跳过**，按本条约 `path_at` 三态处理；`git log -m --full-history --reverse` **会返回删除提交**——实测 `git rm` 后删除提交仍在列，`git cat-file -t <删除提交>:atlas.solution.lock.json` 直接 `fatal: path ... does not exist`，故逐版本解析必须显式跳过）；③ **工作树层：仅当 HEAD 存在该路径版本时才比较并追加**——工作树锁字节与 HEAD 版不同 ⇒ 把工作树内容作为最后一版追加；字节相同 ⇒ 不新增；**HEAD 无该文件（锁未跟踪 / 尚未提交）⇒ 不追加**，`versions` 保持 `[]`；**HEAD 有该路径但工作树文件被 `rm` ⇒ 同样不追加**（不存在「拿什么比」的对象），整体由 `lock_missing`（从未跟踪）或 `lock_tracked_but_deleted`（已跟踪被删）承载，**不发 `lock_history_empty`**（v30/B-1(b)）。**没有「同一 SHA 用工作树内容替换」这一条**（v29/B-1：工作树文件没有 SHA，该条与③互斥且 fail-open——单版删空时历史 `[[x]]` + 工作树 `[]` 会被折叠成 `[[]]` 单版本而判 `Ok`；回滚 `[[a],[a,b]]` + 工作树 `[a]` 会先绿后红；已删除）。**删除提交不得伪造成空版本（v30/B-1）**：若把删除提交记成 `[]`，序列 `[…, [x], []]` 会被判 `exemption_start_history_broken`——**错误码完全错位**（数组没有被改写，是整份锁被删）；跳过删除提交后，「删锁 → 改根 → 重建锁」这条形态只由 ⓪-3 的 `assets_root_history_rewritten` 报，不会被 `exemption_start_history_broken` 抢报。理由是 `check` 其余判据读工作树（`current=True`），前缀单调必须同步，否则「本地删一项未提交」会本地绿、PR 红。`Ok` = 每个后版本 `versions[i]` 都是**紧邻前一版本** `versions[i-1]` 的前缀扩展（`versions[i-1]` 是 `versions[i]` 的前缀，且相邻至多新增一项）——**不是「某前版本」**（v28/B-1：按「某前版本」实现会 fail-open，`[] → [x] → []` 的整段回滚会被首版 `[]` 接住，`[a] → [a,b] → [a]` 也会假绿）；`Err` = `("exemption_start_history_broken", {kind: ..., index: ...})`。**输入边界（v27/I-1，四种写死、均不得抛异常）**：① `versions == []` ⇒ `Ok`（无「后版本」可违；**仅当无任何锁历史时可达**——锁未跟踪 / 尚未提交时 `git log` 返空，此时另发 **INFO 级 `lock_history_empty`**（不进 `errors[]`、不改 exit code，见 §5.2）；**锁文件本身不存在 ⇒ 走 `lock_missing`（从未跟踪）/ `lock_tracked_but_deleted`（已跟踪被删），均不发本 INFO**（v29/B-2；v30/S-2：两码互斥，见 §3.2 ⓪-0/⓪-1））；② 只有一版 ⇒ `Ok`（无比较对）；③ 某版本缺 `exemption_start_history` 键（含首版）⇒ 该版本记 `[]`，按正常前缀扩展处理（**「缺键」≠「该提交没有该路径」**：后者由构造②**跳过**、根本不产生版本，v30/B-1）；④ 该版本的 `seal_anchors` 为 `null` / 非 dict（或 `exemption_start_history` 为 `null` / 非 list）⇒ 同样记 `[]`、**不得抛 `TypeError` / `AttributeError` 落 `internal_error`**——`load_lock_strict(current=False)` 不解析 `seal_anchors`，构造 `versions` 的代码必须自己做类型判定（§8 的「取锚容错」只覆盖取锚，不覆盖本构造）。**`[]` 是零项前缀，但语义单向（v28/B-1）**：首版缺键记的 `[]` 可作后版本的前缀（`[] → [x]` 合法），**反向不成立**——`[x] → []` 中 `[]` 不是 `[x]` 的前缀扩展，判 `Err`；任何非空 `[x...]` 都以 `[]` 为其前缀扩展，该性质只用于「首版 → 首次 append」。**`check` 只负责构造 `versions` 并喂给该函数，判据本体零 git 依赖**——T-33 的断言直接挂在该签名上。**`path_at(commit)` 是唯一探针（v33/重要 1；v34/重要 3 补三洞）**：`build_lock_versions` 的 `fetch` 与 ⓪-1 / `UH` 根集循环里的「路径是否存在」判定（§3.2 符号表 `UH` 行的内联探针）**必须调用同一个 `path_at(commit)`**，判序固定为：① `git cat-file -e <commit>` —— **非零 ⇒ 提交对象本地不可读 ⇒ `chain_unverifiable`（`cause = history_unreadable`）**，这一步与路径判定**不得共用一个 rc**；② `git cat-file -t <commit>:atlas.solution.lock.json` —— 非零且 stderr 为 `fatal: path ... does not exist` ⇒ `absent`（**唯一允许被 `fetch` 映射成 `None` 的状态**）；③ 输出 `blob` 时再取 `git ls-tree -z <commit> -- atlas.solution.lock.json` 的 mode：`120000` ⇒ **symlink**，`100644` / `100755` ⇒ 正常 blob；输出 `tree` / `commit`（gitlink）或 mode 为 `120000` ⇒ `non_blob(type)`。**三态语义**：`absent` ⇒ 两处都「跳过、不产生版本」；`non_blob` ⇒ **不得静默当不存在**——历史侧 `lock_history_unparsable`、当前工作树侧 `lock_unparsable`（均 exit 1）；`blob` ⇒ 返回字节。**symlink 两侧一律不跟随**：历史侧不把链接目标文本当锁读，工作树侧用 `lstat` + `readlink` 判定而**不得 `open`**（打开会跟随），两侧同一口径（都按 `non_blob` 拒绝），不许历史侧红而工作树侧绿；`tree` 同理（锁路径是目录属损坏，不是「无此路径」）。**`fetch` 的 `None` 只表示 `absent`，不表示 `non_blob`**；浅仓 / partial clone 的对象缺失只由第①步报 `chain_unverifiable`，不得因 `<commit>:<path>` 的 rc 落该码。
        四类都不依赖 `%cI` / 提交时间，只依赖锁文件字节；历史版本不可解析 ⇒ `lock_history_unparsable` 先短路（⓪-1）。**残余风险（v24/B-2）**：存量键的锚落在**回填提交**上，而 `first_seen_origin` 的回填值取自当时不可证的 `first_seen_at`，所以「回填那一刻就写晚」检测不到——能检测的只有「回填之后是否被改写」；`exemption_start_origin` 的回填值受 T-28① 钉在 `L[0].signed_at` 上，比 `first_seen_origin` 硬一档。
   - **`seal_anchors`（v9/B1；v10 增 `anchor_review`；v11 单槽；v12 按路径键；v13/R12-1 改成「历史路径并集 + append-only 状态机」；v16/I-3 增 `epoch_origin_history`、v16/N-2 增 `exemption_started_at`；v22/I-6 拆 `exemption_start_origin` + `exemption_start_history[]`）**：C 批起由 `lock --update` 写入；尚无封条时整键为 `null`（或空映射）。**键 = 封条在仓内的字面路径**（`<assets_root>/reviews/apply/<member>/<task-id>.seal.json`，**含 `<assets_root>` 前缀**——与 `git log --name-only` 的输出同一坐标系，否则「键 ∖ `U` == ∅」永远不成立；v14/I-4）。值是 `{epoch_origin, epoch_origin_history[], renewal_seq, n, anchor_review, state, exemption_start_origin, exemption_started_at, exemption_start_history[], first_seen_origin, moved_to?, frozen_at?}`：`epoch_origin` 是该路径当前**纪元起点**承认的提交（初始为首签 A；reanchor 后要等后置 `lock --update` 才变成该路径的 `R0`，reanchor 提交当刻仍是旧 A）；`epoch_origin_history[]` 是该路径 `epoch_origin` 的 append-only 历史（**建键即 `[epoch_origin]`**，受控重指只 append，v16/I-3）；`renewal_seq` / `n` 是写入时刻该路径 HEAD 封条的 `renewal_seq` 与该路径 `L` 的 `N`；`anchor_review` 是创建当前纪元的 reanchor 的 REVIEW-ID（初始为 `null`，**只由 `seal reanchor` 写**）；`state ∈ {active, retired, frozen}` 是**唯一**状态字段，三个状态都有判据（见第 5 条）。
     - **`exemption_start_origin`（v22/I-6；v23/I-1/I-2 补外部锚与回填出口）**：该键的**不可变豁免起点**（UTC ISO-8601，形态 `YYYY-MM-DDTHH:MM:SSZ`）。建键时写入首签封条 `signed_at` 的值。**已有值不改写**（`lock --update` / `seal freeze` / `seal reanchor` / 改根 / 换路径（`moved_from`）都不得改写**已有的**值）；**缺失时一次性回填**——老锁缺该键 ⇒ `lock --update` 写入当前 `exemption_started_at` 的值（二者建键同值，不得重取封条时间）。**外部锚（v23/I-1；v24/B-2 改取法）**：期望值 = **锁文件全部历史版本**中「**首个同时含有该字段的版本**」里的 `exemption_start_origin`（存量键的首个含键版本没有该字段 ⇒ 锚顺延到回填提交）；取法见 §1.1.3「资产根」⑦ 标量类。当前值与锚不等 ⇒ **`exemption_start_origin_rewritten` FAIL**。`gap.due` 的**下界**取它（§5.1 第 3 条、§2.4 决策 3）；**上界另由 `trunc_utc_date(first_seen_origin) + 90d` 与 `acceptance_cutover` 共同约束**（v23/I-3：不再写「due 只从它算」——due 是区间，不是单点）。带 `moved_from` 的新键**必须沿 `moved_from` 递归到链首、与链首键的 `exemption_start_origin` 相等**（v18/次要 3），不得重取封条时间。
     - **`exemption_started_at`（v22/I-6，主判据 = 当前 `L[0].signed_at`，允许 reanchor 同步重指）**：值必须**逐字节等于该路径 `L[0]` 首签封条的 `signed_at`**（v18/重要 1：封条字节被链规则钉住、可复算；`%cI L[0]` 只作 WARN/INFO，理由见 §8）。普通续签只 append、`L[0]` 不变，等式自然成立；**`seal reanchor` / squash 后 `L[0]` 被重写成新 `R0`** 时，允许且必须在本命令内把该字段同步重指到新 `L[0].signed_at`，**并且同时向 `exemption_start_history[]` append 一条审计项**（见下）。**不改 `exemption_start_origin`**。**先后关系（v23/I-3）**：必须满足 `exemption_start_origin ≤ exemption_started_at`；违反 ⇒ `exemption_start_history_broken`（空数组时由等值判据强制二者相等，非空时由本式约束）。
     - **`exemption_start_history[]`（v22/I-6，append-only；v23/I-1 加版本前缀单调）**：元素 `{from, to, commit}`——`from` = 链条上一环的值（首项时等于 `exemption_start_origin`，其余等于前一项的 `to`）、`to` = 本次重指后的 `exemption_started_at`、`commit` = **`R0` 的父提交**（v23/次要 4 写死：即执行 `seal reanchor` 时的 HEAD；**仅审计、不校验**——v24/次要 1：由 `to` 无法反查哪枚封条是 `R0`，本字段不参与任何断言，语义同 `assets_root_history[].commit`）。约束：① 数组 append-only（不得删项、不得改项、不得重排）；② 首项 `from` 等于 `exemption_start_origin`；③ 第 i 项的 `from` 等于第 i-1 项的 `to`（链条自洽）；④ **末项 `to` 逐字节等于当前 `exemption_started_at`**（而后者必须等于当前 `L[0].signed_at`）；⑤ 无重指时数组为空；⑥ `exemption_start_origin ≤ exemption_started_at`。任一不满足 ⇒ **`exemption_start_history_broken` FAIL**。**版本前缀单调（v23/I-1，外部锚；v28/B-1 改「紧邻前一版本」）**：把锁文件的每个历史版本按 `git log -m --full-history --reverse HEAD -- atlas.solution.lock.json` 排序（**按 commit SHA 去重**，末尾按 §1.1.3 ⑦ 追加工作树版——**仅当 HEAD 存在该文件时**，未跟踪 / 未提交则不追加；v29/B-2）后，任一后版本该键的 `exemption_start_history[]` 必须是**紧邻前一版本**的**前缀扩展**，且相邻版本**最多新增一项**——**不得放宽为「某前版本」**；删项、改项、重排、跨版本不连续 ⇒ 同码。这样 append-only 不再只靠末项等式自证（单次提交整段重写会同时被版本前缀单调与 origin 锚打掉）。**回填（v23/I-2）**：缺 `exemption_start_history` ⇒ `lock --update` 一次性初始化为 `[]`；**已有值一律不改写**；`seal reanchor` 是**唯一追加入口**（v24/次要 2：回填写 `[]` 不算「追加」），且必须与 `exemption_started_at` 同一次写入（只改一个 ⇒ 同码）。
     - **`first_seen_origin`（v23/I-1，新增；不可变）**：建键时写死为**当下该路径 HEAD 封条载荷的 `first_seen_at`**（UTC，规范形态同 §5.2）。**已有值不改写**；缺失时 `lock --update` 一次性回填为当前封条载荷的 `first_seen_at`（回填不改 `due` 上界：值相同）。**外部锚**同 origin：期望值 = 锁历史中**首个同时含该字段的版本**里的 `first_seen_origin`（存量键锚顺延到回填提交）；不等 ⇒ **`first_seen_origin_rewritten` FAIL**；**v25/I-4 扩一条触发条件**：`first_seen_origin > L[0].signed_at`（**时间戳层**比较）也报本码，`detail.kind ∈ {rewritten, after_signed_at, not_canonical}` 区分成因（首签时把封条 `first_seen_at` 手改成未来值、锁键照抄，锚只能证明「之后没再改」，`due` 上界会被拉到 `acceptance_cutover`；`exemption_start_origin` 已有 T-28① 钉在 `L[0].signed_at`，不加）；**形态（v26/S-9）**：`first_seen_origin` 非 `YYYY-MM-DDTHH:MM:SSZ`（`+00:00` / 小数秒 / 非 UTC）⇒ **也报本码**（`detail.kind = not_canonical`）——`first_seen_at` 载荷无规范形态条款、`load_lock_strict` 也不解析 `seal_anchors`，**不得**直接把它与 `L[0].signed_at` 做字符串比较。`gap.due` 的**上界** = `min(trunc_utc_date(first_seen_origin) + 90d, acceptance_cutover)`（`d = trunc_utc_date(first_seen_origin)` 为 `date`，先截日期再加 90 天，§5.1 第 3 条；v26/I-2）。`first_seen_at` 留在封条载荷里**只作审计**，不再承担 `due` 上界判据——封条载荷在 reanchor 时会被整段跳过（`L[-2]` 不可读），靠写侧「原样保留」不可证（v23/I-1）。
   - **键的宇宙（R12-1；v14/B-1 修命令、v14/I-4 收紧谓词、v15/D-1 换根来源、v16/D-1 改成「锁文件全历史根并集」、v17/B-1 改严格解析）**：键集**不是**「HEAD 上有哪些封条」，而是**历史上新增过的封条路径的并集** `U`。`U` 的根**取锁文件全部历史版本**的根并集 `UH`（v16/D-1：当前锁与 config 都不可信，只有 git 里的锁历史不可整段替换）：

     **① 根集 `UH` 必须用同一个严格解析器（v17/B-1）**：锁文件每个历史版本都经 `_support/solution.py` 的锁加载路径解析（与 `check` / `lock --update` 读当前锁**同一个函数**），**不许**另写一套 shell / `jq`——`jq` 不是本仓依赖（工具链是 stdlib Python + git，Windows 采纳仓没有 `jq`），管道里的失败还会被吞掉。参考实现（Python，stdlib + `subprocess`）：

     ```python
     # _support/solution.py：严格锁解析器（v18/阻断 2；v19/次要 1 加 current 分支；v22/B-1 词法下沉）
     # 与历史根集（v18/阻断 1；v19/阻断 1 换 layout 单源；v20/阻断 1 历史根只做词法校验）
     import json, subprocess
     from pathlib import Path
     from _support.layout import LayoutError, validate_value

     LOCK_PATH = "atlas.solution.lock.json"
     # ROOT_RE 仅作「新增根」的写侧提示（CLI 文案 / 文档示例），**不参与任何判据**（v19/阻断 1）

     class LockParseError(Exception): ...
     class LockHistoryUnparsable(Exception): ...   # 落码 lock_history_unparsable，⓪-1
     class ChainUnverifiable(Exception): ...       # 落码 chain_unverifiable（对象本地缺失 / git 层失败）

     def load_lock_strict(repo, text: str, *, current: bool) -> dict:
         """当前锁与历史锁共用的唯一解析器（v22/B-1：**词法层也在这一处**）。
         current=True：members/contracts 必须齐备（v19/次要 1）；任一元素 `.root` 过
           `validate_value(..., lexical=True)`，失败 ⇒ `LockParseError`（落 ⓪-0 `lock_unparsable`）。
         current=False：只校验「存在则类型正确」，不要求当前字段（v18/阻断 2）；元素 `.root`
           非字符串 / 空 / 首尾空白 ⇒ 同样抛；可读为字符串的再跑 `lexical=True`，失败 ⇒
           `LockHistoryUnparsable`（落 ⓪-1）。
         这样「当前锁词法错误归 ⓪-0、历史版本归 ⓪-1」只有一处实现，⓪-3 不再重复判字符集。
         """
         Err = LockParseError if current else LockHistoryUnparsable
         doc = json.loads(text)                       # 坏 JSON ⇒ JSONDecodeError（调用方按 current 归类）
         if not isinstance(doc, dict):
             raise Err("lock is not a JSON object")
         sv = doc.get("schema_version")
         # bool 是 int 的子类，且 1.0 == 1：必须先排除浮点与布尔（v18/阻断 2）
         if type(sv) is not int or isinstance(sv, bool) or sv not in (1, 2):
             raise Err(f"schema_version={sv!r}")
         for k in ("members", "contracts"):
             if current and k not in doc:
                 raise LockParseError(f"{k} missing in current lock")
             if k in doc and not (isinstance(doc[k], list)
                                  and all(isinstance(x, dict) for x in doc[k])):
                 raise Err(f"{k} is not list-of-dict")
         if "assets_root_history" in doc:
             h = doc["assets_root_history"]
             if not isinstance(h, list) or not h:     # [] ⇒ 解析失败，不是「无历史」
                 raise Err("assets_root_history is not a non-empty list")
             for i, el in enumerate(h):
                 if not isinstance(el, dict):
                     raise Err(f"assets_root_history[{i}] is not an object")
                 root = el.get("root")
                 if not isinstance(root, str) or not root or root != root.strip():
                     raise Err(f"assets_root_history[{i}].root={root!r}")
                 # v22/B-1：词法校验就在解析层，⓪-3 不再重复（当前 ⇒ LockParseError；历史 ⇒ LockHistoryUnparsable）
                 try:
                     validate_value(Path(repo), "assets_root", root, lexical=True)
                 except LayoutError:
                     raise Err(f"assets_root_history[{i}].root={root!r} rejected by lexical")
         if "layout_assets_root" in doc and not isinstance(doc["layout_assets_root"], str):
             raise Err("layout_assets_root is not a string")
         return doc

     def _root_lexical_ok(repo, root: str) -> bool:
         """历史根只做词法校验：零 FS 访问（v20/阻断 1）。
         历史根今天可能已删除、或被换成指向仓外的 symlink；append-only + 禁归一化
         没有出口，所以不得用「今天的工作树」判历史。"""
         try:
             validate_value(Path(repo), "assets_root", root, lexical=True)
         except LayoutError:
             return False
         return True

     def _root_fs_ok(repo, root: str) -> bool:
         """当前根用严格版（多判「存在但不是目录」「symlink 逃逸」），供 ⓪-3 使用；
         install.py --assets-root 走的也是这一版（写侧语义「拒，不 trim」）。"""
         try:
             validate_value(Path(repo), "assets_root", root)
         except LayoutError:
             return False
         return True

     def _root_by_index_ok(repo, hist: list) -> bool:
         """⓪-3 的根判据（v21/B-1；v22/B-1 明确输入语义、空数组防御）。
         **入参已过 `load_lock_strict` 的词法层**（每个元素都是合法词法根），本函数只做分层：
         hist[:-1] 再跑一次 lexical（防御，零 FS）；hist[-1] 走 strict（含 FS）。
         按值匹配会在「同一根重复出现」时无法区分末元素与历史元素。"""
         if not hist:
             return False
         for el in hist[:-1]:
             if not _root_lexical_ok(repo, el["root"]):
                 return False
         return _root_fs_ok(repo, hist[-1]["root"])

     def historical_roots(repo) -> set[str]:
         proc = subprocess.run(
             ["git", "log", "-m", "--full-history", "--format=%H", "HEAD", "--", LOCK_PATH],
             cwd=repo, capture_output=True, text=True,
         )
         if proc.returncode != 0:
             # git 层失败 ⇒ 不是「没有坏版本」（v19/重要 5）
             raise ChainUnverifiable("git log failed")
         roots: set[str] = set()
         for c in proc.stdout.split():                # 只信 HEAD 可达历史（v19/次要 3）
             # ① 提交对象本身缺失（浅/partial 剪掉）⇒ chain_unverifiable（v19/阻断 3）
             if subprocess.run(["git", "cat-file", "-t", c],
                               cwd=repo, capture_output=True).returncode != 0:
                 raise ChainUnverifiable(f"commit object missing: {c}")
             # ② 该提交没有锁路径 ⇒ 才 continue（不存在 ≠ 读不出）
             if subprocess.run(["git", "cat-file", "-t", f"{c}:{LOCK_PATH}"],
                               cwd=repo, capture_output=True).returncode != 0:
                 continue
             raw = subprocess.run(["git", "show", f"{c}:{LOCK_PATH}"],
                                  cwd=repo, capture_output=True, text=True)
             if raw.returncode != 0:                  # 路径在却读不出 ⇒ 不许当「无锁」
                 raise LockHistoryUnparsable(commit=c, reason="git show failed")
             try:
                 lock = load_lock_strict(repo, raw.stdout, current=False)
             except (json.JSONDecodeError, LockHistoryUnparsable) as e:
                 raise LockHistoryUnparsable(commit=c, reason=e)   # 不许跳过
             if lock["schema_version"] != 2:
                 continue                             # v1 锁里根本没有根字段（v19/次要 2）
             hist = lock.get("assets_root_history")
             if hist is None:
                 continue                             # 历史版本不要求当前字段
             # 逐元素显式复核；禁止 {e.root for e in hist}（v18/阻断 1）
             for i, el in enumerate(hist):
                 if not isinstance(el, dict):
                     raise LockHistoryUnparsable(commit=c, reason=f"element {i} not object")
                 root = el.get("root")
                 if not isinstance(root, str) or not root or root != root.strip():
                     raise LockHistoryUnparsable(commit=c, reason=f"root={root!r}")
                 if not _root_lexical_ok(repo, root):  # 防御性复核（load_lock_strict 已判过）；只词法，零 FS（v20/阻断 1）
                     raise LockHistoryUnparsable(commit=c, reason=f"root rejected: {root!r}")
                 roots.add(root)
         return roots
     ```

     **② `load_lock_strict` 的定义与失败语义（v18/阻断 2；v19/次要 1 收口成员字段）**：严格解析器 = 「`json.loads` 得到 JSON **对象** + `type(schema_version) is int and not isinstance(schema_version, bool)` 且值 ∈ `{1,2}`」——现网 `1.0 in (1, 2)` 与 `True in (1, 2)` 都为真，必须显式排除浮点与布尔。**历史版本只校验「存在则类型与结构正确」，不要求当前字段**；另加两条与版本无关的硬要求：`members` / `contracts` **存在时**必须是 list-of-dict。**当前锁则必须两者齐备**（`current=True`，缺失 ⇒ `lock_unparsable`）——这是唯一口径，不留「当前可缺、历史不可缺」的第二种写法（v19/次要 1）。当前 schema 的必需集（`definition` / `seal_anchors` / 两个根字段）**只对当前锁**由 ⓪-3 判，**历史版本永不要求**。任一历史版本 ① 不是合法 JSON 对象、② `schema_version` 类型或取值不对、③ `assets_root_history` 存在但不是非空数组、④ 元素不是对象或 `.root` 不是非空字符串 / 首尾带空白、⑤ `root` 被 `layout.validate_value(..., lexical=True)` 拒绝 ⇒ **`lock_history_unparsable` FAIL**，直接停，**不得跳过、不得当成「该版本无根」**。**历史版本缺 `members` / `contracts` ⇒ 视为旧工具产物放行**，不报 `lock_unparsable`（v20/次要 2）；当前锁缺 ⇒ 照旧 `lock_unparsable`。**历史根只做词法校验（v20/阻断 1）**：`lexical=True` 零 FS 访问——今天的工作树状态（目录已删 / 被换成仓外 symlink）不得反过来判历史。**读取层（v18/重要 4；v19/阻断 3 换 `-t`）**：先 `git cat-file -t <c>`——失败 ⇒ **`chain_unverifiable`**（对象本地缺失，这才是窄开关唯一可降级的那一支）；再 `git cat-file -t <c>:atlas.solution.lock.json`——失败 ⇒ **该提交没有该路径，`continue`**；两段都通过却 `git show` 失败 ⇒ **`lock_history_unparsable`**。**`git log` 本身非零 ⇒ `chain_unverifiable`**，不是 `lock_history_unparsable`（v19/重要 5）：前者是「历史读不到」，后者是「历史读到了但字节坏」，两者不能共码。v16 的洞（`jq` 整条失败被管道吞掉、`[]` truthy 不回落、`{root: null}` 被 `-r` 打成字面量 `null`、`[{}]` 抛 `AttributeError`）在「同一解析器 + 逐元素显式校验 + **禁止集合推导**」下同时消失。

     **③ v1 版本一律不贡献根（v18/次要 1；v19/次要 2 换结构理由）**：解析层判过 `schema_version` 之后，v1 版本直接 `continue`——不回落 `layout_assets_root`，也不回落该提交的 config 根（`config_root_at` 删除）。**理由改为结构性**：写侧 `lock_payload` **只在清单 `schema_version == 2` 时**写 `layout_assets_root` / `assets_root_history` 两个字段，v1 锁里**根本不存在**该字段——不是「有字段但不取」，所以「v1 + 非空 `seal_anchors` 会被 ⓪-2 判红」不再是这条规则的依据（它仍成立，但只是旁证）。`lock_v1_with_seals` 仍从「仅当前锁」扩到「锁全历史」（§3.2 ⓪-2）。

     **④ 写侧不得归一化（v17/B-1）**：`lock --update` 写出的锁必须是**严格 JSON**（无注释、无尾逗号、UTF-8、`\n` 结尾），且**任何命令都不得重排键序、重排数组、去重、归一化或重写既有 `assets_root_history` 元素**（B 批的 `lock_payload` 生成器同守）——否则 C 读到的「历史」是 B 写坏过的版本，`lock_history_unparsable` 与 S-49 会在真实仓里误报。

     **⑤ `commit` 字段语义（v17/次要 4）**：`assets_root_history[].commit` **仅审计、不参与任何断言**；首元素固定 `null`；后续元素 = **执行该次 `lock --update --assets-root` 时的 HEAD**（即携带新根的锁提交的父提交）。不写成「本次提交」——锁提交自身 SHA 在写入时不可知（自指），与规则 2 的 `L[0]` 同理。

     ```bash
     # U：对根集 UH 里每个 R 各跑一次，再并集去重（根集见上面的 Python）
     for R in <UH>; do
       git log -m --full-history --diff-filter=A --no-renames --format= --name-only HEAD \
         -- ":(glob)$R/reviews/apply/*/*.seal.json"
     done | sed '/^$/d' | sort -u
     ```

     **两道防线**：⓪-3 的 `assets_root_history_rewritten`（当前锁必须包含 `UH`）是错误码；**`UH` 只取历史版本**是兜底——即使 ⓪ 被绕过（比如实现者只比当前锁），`U` 也不会因当前锁被重写而缩小。`--full-history` 必须带：`atlas.solution.lock.json` 在 merge 里被保留成某一侧时，默认历史简化会把另一侧的版本剪掉，`UH` 就会漏掉那个根——与 `U` / `definition.commit` 同一口径（§5.2 第 8 条）。

     按行去重后排序（`-m` 会让同一个 merge 出多行，必须去重）。六个约束缺一不可：
     ① **`--full-history`（v14/B-1）**：`git merge -s ours` 是正常命令，合并后 HEAD 树与第一父完全相同，默认历史简化把侧支上「新增封条」的提交当 TREESAME 剪掉。实测（`/tmp/v14b`：base 无封条、side 新增、`main` 上 `git merge -s ours side`）：HEAD 树内 seal 数 0、v13 原命令（无 `-m`、无 `--full-history`）输出**空**、加上 `--full-history` 才看见 side 那条；而 `git merge-base --is-ancestor side HEAD` 仍返回 yes（历史确实在，只是被剪）。`U` 一旦为空而锁里的键也被一起删掉，路径级 / 状态机 / 链级三段全部不触发 ⇒ S-36 的假绿原样复现。**`U` 与 `L` 的 `--full-history` 口径必须一致**，不许一边带一边不带。
     ② **`-m`（v14/B-1）**：`U` 用 `git log --name-only`，而 `git log` 对 merge **默认不输出任何 diff**。merge 提交里新增封条（冲突解决时加了两侧都没有的路径）只有在 `-m` 下才以 `A` 出现。实测（`/tmp/v14c`：merge 提交里新增 `billing/T-9.seal.json`）：`--full-history` 单独用输出**空**，`-m` 才有（且对每个父各出一行 ⇒ 去重）；不加 `-m` 该路径永远进不了 `U`，`lock --update --seal <该路径>` 判 `seal_anchor_path_orphaned`，新封条的键**永远建不了**（反向假红）。
     ③ **`L` 不要 `-m`（别照抄）**：`L` 不是用 `git log --name-only` 算的，而是 `git rev-list --full-history` 出候选、再用 `git show --format= --name-status <c>` 逐提交过滤；`git show` 对 merge 默认给 combined diff，「两侧都没有的新增」本来就能看见；给 `git show` 加 `-m` 会把一次 merge 拆成多份 diff，同一个 merge 在 `L` 里被计多次、`N` 直接偏大（`renewal_seq == N` 会集体误红）。**`U` 要 `-m` 是因为它走 `git log`，`L` 不要 `-m` 是因为它走 `git show`——不是「一条该有一条不该有」。**
     ④ **`--no-renames`**：实测去掉它，rename 检测会把新路径显示成 `R100`、`A` 消失，只有旧路径留下（`/tmp/sealuniv`：`git mv T-1 → T-2` 后不带 `--no-renames` 只输出 `T-1`，带上则 `T-1`/`T-2` 都出现）。
     ⑤ **每个历史根各配一个两段谓词（v14/I-4；v15/D-1/I-2 改根来源与写入侧；v16/I-5 补判序与存量）**：对根集（①）里的每个 `R`，成员谓词是**能从路径稳定算出的两段式** `^<R>/reviews/apply/[^/]+/[^/]+\.seal\.json$`——`apply/` 之后恰好 `<member>/<task-id>.seal.json` 两段，多一段或少一段都不算封条。**写入侧**（v15/I-2、v16/I-5）：① 清单加载期拒绝含 `/` 的 `members[].name`（`<member>` 就是 `[^/]+`；现有 `_validate_name` 允许 `/`，所以要按清单版本分层：**v1 清单**含 `/` ⇒ `migration_required` WARN + `migrate` 打印改名建议（不自动改），**v2 新写入** ⇒ FAIL）；② `lock --update --seal <path>` 对**不匹配任何历史根谓词**的路径报专用码 `seal_path_unsupported`，**不复用** `seal_anchor_path_orphaned`（后者是「路径合法但从来没出现过」）；③ 已经存在的三段键（`apply/auth/sub/T-2.seal.json`）**永久 `seal_path_unsupported`**，不得回落成 orphaned——否则实现者会以为「建个键就能修好」。`docs/examples/reviews/apply/demo.seal.json` 这类文档样例因此**不进 `U`**（不在任何历史根下、段数也不对），不会逼着人对它建键（S-41）。
     ⑥ **`HEAD` 必须写**（与 §3.2 的 `L` 同口径，漏了会把 pathspec 当 revision）。

     **这是仓级集合 `U`，`check` 与 `lock --update` 各算一次、结果必须一致**；**键 append-only，永不删除，只允许改 `state`**；键是**仓内字面历史路径**（含 `<assets_root>` 前缀，与 `git log --name-only` 同一坐标系，否则「键 ∖ `U` == ∅」永远不成立）。这样「删旧文件 + 删旧键」不再让旧链从校验宇宙里消失：`U` 里有某路径而键缺 ⇒ `seal_anchor_path_unmapped`；键在而路径从未在 `U` 里出现过 ⇒ `seal_anchor_path_orphaned`。**`U` 的根取锁文件全历史并集（①），既不读 `atlas.config.yaml` 现值、也不只读当前锁的 `assets_root_history`**（v16/D-1）；当前锁没包含历史并集 ⇒ `assets_root_history_rewritten`，config 现值不在当前历史里 ⇒ `assets_root_changed`（两条都排 ⓪，见 §3.2）。
   - **判定优先级（R12-6；v15/D-1 前置 ⓪；v15/I-4 补载荷码；v16/I-5 改路径级次序；v17/I-3/I-4 进 ⓪ 与 ②）**：⓪ 锁与根（`lock_unparsable` → `lock_history_unparsable` → `lock_v1_with_seals` → `assets_root_history_rewritten` → `assets_root_changed`）→ ① 路径级（`seal_path_unsupported` → `seal_anchor_path_unmapped` → `seal_anchor_path_orphaned`，**必须这个次序**：键不匹配任何根谓词时只报 `seal_path_unsupported`，不再去看它在不在 `U` 里；先在 `U` 里判缺键，再判多出来的键）→ ② 状态合法性（state 与 HEAD 文件是否一致、frozen 是否被改、retired 是否被写、**`exemption_start_signed_at_not_canonical`**（**只管锁里的 `exemption_started_at` 字面值、只罚形态**；**先于一切等值判据**）→ **`signed_at_not_canonical`**（封条 blob 通用形态，**含 `L[0].signed_at`**；与上一条同属「形态层」，**任一形态失败即跳过整个 conflict 组**（`exemption_start_conflict` 及其 `detail` 分支 `moved_from_chain_mismatch` / `chain_head_missing` 一并跳过，v24/B-1；v25/次要 1）→ **`exemption_start_history_broken`**（审计链断裂、版本前缀单调破坏、`exemption_start_origin > exemption_started_at`）→ **`exemption_start_conflict`**（`exemption_started_at` 被手改 / 换路径未沿 `moved_from` 递归继承链首值 / 与 `L[0]` 封条 `signed_at` 不逐字节相等；等值不等只归本码，v23/B-1）→ **`exemption_start_origin_rewritten`** / **`first_seen_origin_rewritten`**（与锁历史锚不等，**或 `first_seen_origin > L[0].signed_at`（时间戳层，`detail.kind = after_signed_at`）**，v23/I-1；v25/I-4；**同一输入只出这一串码中的一个**）→ **`exemption_due_out_of_range`**（`due` 越出闭区间或 `origin > due`，读侧，v24/I-3；**`due` 归一化口径「先截 UTC 日期再加 90 天、全程 `date`」见 §5.1 第 3 条**，v27/次要 3）、**`epoch_origin_history_rewritten`**）→ ③ 链级与 `moved_from`（`seal_path_history_lost` → `seal_move_payload_mismatch` → `reanchor_*`，**`seal_path_history_lost` 必须排在 `seal_move_payload_mismatch` 之前**：凭证本身不成立时，载荷比较没有意义）。**同一提交同时命中多码时按此顺序报第一个**，不得随机；`U` 与键集的差集判完之前，不进入任何链规则。`orphaned` 只表示「键没有历史新增支撑」，`seal_path_history_lost` 只表示「历史路径的迁出/删除缺 `moved_from` 或对不上」，两者不会互相替代。**典型双命中**：保留旧键 + 只新增新键 + 写 `moved_from` 时，先判路径级（通过），再判状态（旧键 `retired` 需目标 `moved_from` 指回），最后才判链级；若旧键被标成 `active`，报 `seal_anchor_path_state_mismatch`，不再报 `seal_path_history_lost`。
     - **`lock --update` 的写锚规则（v9/B1；v10 推进条件；v11 `epoch_origin` 语义；v12 按路径写；v13 状态机与 append-only；v32/结构项：`seal freeze` / `seal reanchor` / `lock --update --assets-root` 三条写入口全仓不存在，本组规则标「**C 批实现时补**」，依赖命令 / 规则闭合度 / 实现断言见 §6 C 批）**：
       1. **作用域**：只写**当前封条路径**对应的那一个键，其他键**原样保留、绝不重置**。当前封条路径由 `--seal <path>` 显式给出；未给且仓内只有一枚封条时取它；**多于一枚且未给 `--seal` ⇒ exit 2 并列出候选**（不猜，S-37）。
       2. **新建键**：仅当该路径在 HEAD 有封条且键不存在（首次 `lock --update`）；`state = active`，`epoch_origin = L[0]`（无 `reanchor`）或该路径唯一那枚 `R0`（`L` 中唯一满足 `renewal_seq == reanchor.base_seq` 的提交）；`renewal_seq` / `n` 取该路径 HEAD 封条；`anchor_review = R0.reanchor.review` 或 `null`；**`epoch_origin_history = [epoch_origin]`（v16/I-3：建键即写下初值，否则规则 3 的「从一条变两条」不可判）**；**`exemption_start_origin` 与 `exemption_started_at` 同值写入**：二者都 = 该路径 `L[0]` 首签封条的 `signed_at`，逐字节相等（v18/重要 1；v22/I-6 起 origin 的已有值不改写、started_at 可由 reanchor 重指）；**`exemption_start_history = []`**（建键即空数组）；**`first_seen_origin = 该路径 HEAD 封条载荷的 first_seen_at`**（v23/I-1：建键写死，due 上界只从它算）；v18/重要 1：封条字节被链规则钉住、可复算；`git show -s --format=%cI <L[0]>` 只作 WARN/INFO——committer date 可被 amend / rebase / `GIT_COMMITTER_DATE` 改写，不可证）；带 `moved_from` 的新键不适用本式，必须递归继承链首键的值（规则 4）**。**封条提交与建键提交必须成对（v14/I-5）**：`epoch_origin = L[0]` 里的 `L[0]` 是**提交 SHA**，在「加封条的那个提交」里不可知（提交前算不出自己的 SHA，写进去就是自指）。因此：① **禁止在同一个提交里既新增封条又建键**；② 顺序固定为「先提交封条」→「在该提交上跑 `lock --update`」→「独立提交锁」；③ 中间态（HEAD 有封条、锁里还没键）**必然**报 `seal_anchor_path_unmapped`，这是**预期红**，不是缺陷——CI 只判 PR 头（或显式判「封条提交 + 建键提交」这一对），不得为了消红把两步并成一个提交；④ 建键提交里 `L[0]` 已确定，`epoch_origin` 才可写。**本地口径（v15/N-3）**：在两个提交之间看到 `seal_anchor_path_unmapped` 属预期；采纳仓若有 pre-push 逐提交跑 `check`，应**跳过该中间提交**（或只在 PR 头跑），不得因此要求把两步合并。
       3. **已存在键**：保留 `epoch_origin` 与 `anchor_review`，只刷新 `renewal_seq` / `n`；不得从 `L[0]` 重算（重写后 `L[0]` 会变成可达新 SHA，合法 fresh clone reanchor 会被 `reanchor_not_allowed` 误杀）。**`n` 按 state 取（v17/I-5）**：`active` ⇒ `len(L)`；`retired` ⇒ `len(L_pre)`（§1.1.3 第 5 条给的取值，**不是** `len(L)`——`retired` 的 `L` 末尾有删除提交，算进去会让 `n` 每次删除后都变）；`frozen` ⇒ `frozen_at` 前缀的长度。**HEAD 无封条时（`retired` 且旧文件已删 / `frozen` 且 `frozen_at` 前有删）`renewal_seq` 保留锁内原值，不得写 `0` / `null`**（v17/I-5：这两个值会让链规则 1 的 `renewal_seq == len(L)` 误红，也会被误读成「从未签发」）。**该状态专属字段原样保留（v15/I-3）**：`state`、`moved_to`、`frozen_at` 等一律不改——`lock --update` 不是状态迁移命令，遇到已 `frozen` 的键不得写回 `active`、也不得清掉 `frozen_at`；遇到 `retired` 不得改写、也不得清掉 `moved_to`（S-47a / S-47b）。**`exemption_started_at` 对 `lock --update` 只读不写（v16/N-2；v22/I-6）**：已存在键一律沿用原值，缺该字段（v15 及更早的锁）⇒ 一次性写入该路径 `L[0]` 那枚首签封条的 `signed_at`（**逐字节**，可从 git 复算；`%cI` 只作 WARN/INFO，见 §8；**归一化口径（v19/次要 4；v21/次要 3 拆码）：统一 `YYYY-MM-DDTHH:MM:SSZ`，UTC、`Z` 后缀、无小数秒；`+00:00` 或带小数秒 ⇒ `exemption_start_signed_at_not_canonical` FAIL（独立码，不与封条 `signed_at_not_canonical` 混用），不做语义换算**）。**`lock --update` 此后不再改它；唯一允许改它的是 `seal reanchor`（同步重指 + 同一写入里 append `exemption_start_history`）**。**`exemption_start_origin` / `exemption_start_history` / `first_seen_origin` 的补写（v23/I-1/I-2）**：缺 `exemption_start_origin` 的存量键 ⇒ 一次性写入当前 `exemption_started_at` 的值（二者在建键时同值，不能重取封条时间）；缺 `exemption_start_history` ⇒ 初始化为 `[]`；缺 `first_seen_origin` ⇒ 一次性写入当前封条载荷的 `first_seen_at`；**已有值一律不改写**（origin / first_seen_origin 只回填、不改写；history 只由 `seal reanchor` append）。**`epoch_origin_history` 的补写（v16/I-3）**：缺该字段的存量键 ⇒ 先按 `[当前 epoch_origin]` 初始化，再按下面的重指规则决定是否 append；已有该字段 ⇒ 只 append、不删、不重排、不排序。
          **首签分支 rebase 的受控重指（v15/I-1；v16/I-4 给可判法）**：`lock --update` 允许重指 `epoch_origin`，但**必须同时满足**四条：① `state == active`；② **锁历史里该键从未出现过非 `null` 的 `anchor_review`**（不是读当前锁的快照——扫 `git log -m --full-history HEAD -- atlas.solution.lock.json` 的每个版本，任一版本该键的 `anchor_review` 非空即不满足；v16/I-4）；③ **HEAD 封条**的 `renewal_seq == 1`（读 HEAD 文件，不读锁里的 `renewal_seq` 快照；v16/I-4）；④ 旧 `epoch_origin` **不在当前 HEAD 历史里**。④ 的退出码必须分清：`git merge-base --is-ancestor <old> HEAD` 返回 **0 = 可达（不可重指）**、**1 = 不可达（可重指）**、**128 = 对象缺失或不合法（可重指，rebase 后旧对象常已被 gc）**；**其它非零一律按错误退出，不得当成「否」**。重指必须 append `epoch_origin_history[]`：旧值永不删除，一次 `lock --update` 最多 append 一条，数组末元素即当前 `epoch_origin`。**不设次数上限（v17/B-2）**：四条条件已经保证「从未重锚 + 只有首签」，重复 rebase 只是换 SHA、没有载荷可洗；再加 `len <= 2` 会把「单封条路径 rebase 两次」变成死结（重指被拒、`N == 1` 的 reanchor 判 `reanchor_invalid`、键不能删、封条不能重置）。`epoch_origin_history` 只作**审计留痕**，长度断言（`len == 1 + 重指次数`、末元素 == 当前 `epoch_origin`、无重复）保留为**篡改检测**（判序 ②，码 `epoch_origin_history_rewritten`），**不再当门**。**重指次数的计数口径（v18/次要 2）**：= 锁文件历史**逐版本比较** `epoch_origin` 发生变化的次数（相邻两版该键的 `epoch_origin` 不同即 +1），**不得用数组自身长度反推**。**任一条件不满足仍按规则 1 报 `reanchor_record_missing`**，不得因为「看起来像 rebase」就放宽。这样首签 rebase 有可执行的自助出口，而不是「禁止 rebase」这种 PR 上无法用机器门守的规矩。
       4. **路径移动（R12-1/R12-4；S-31/S-35/S-36；v17/I-1/I-6 补继承与 `signed_at` 复制）**：新路径**新增**键（`state = active`，`epoch_origin = 新路径 L[0]`、`anchor_review = null`）；旧键改为 `state: retired` 并写 `moved_to: <新路径>`。**新键的 `exemption_started_at` 必须沿 `moved_from` 递归到链首、与链首键的值相等**，**`exemption_start_origin` 与 `exemption_start_history` 也一并从链首键逐字节复制**，**`first_seen_origin` 同此**（v23/I-1：due 上界也必须随换路径继承，不得重取当前封条载荷的 `first_seen_at`——否则换路径就成了「重置 90 天窗口」的出口）（v22/I-6：不得重取封条时间、不得把 history 重置为空数组——那样会让「换路径」变成清洗审计链的出口）（v18/次要 3：中途缺键先按 ① 报 `seal_anchor_path_unmapped`，不另判 `exemption_start_conflict`；「链首键不存在」只作 `exemption_start_conflict` 的 `detail`，不得回落到封条时间——旧封条每续签一次 `signed_at` 就后移，回落等于把豁免起点往后挪）；**新封条的 `signed_at` 必须逐字节等于 `L_pre[-1].signed_at`**（同一 canonical 形态：`YYYY-MM-DDTHH:MM:SSZ`、UTC、`Z`、无小数秒；v19/次要 4）（换路径不是重签，规则 6 的豁免集里已没有 `signed_at`；写侧由 `seal sign --move-from <旧路径>` 复制，不许取 `now()`）。**旧文件可以删除**，但该删除提交必须被新封条的 `moved_from` 覆盖（`moved_from.path == 旧路径` 且 `moved_from.sha256 == 旧路径在迁出前最后一枚封条的字节`），且 `moved_from.path` 必须 ∈ `U`。**没有 `moved_from` 的删除 ⇒ `seal_path_history_lost` FAIL**；旧路径 `L` 里的 `D` **照常计入**，由第 5 条给归属（不是不计算）。`retired` 之后：禁止该路径任何新续签、新 reanchor、以及改 `e2e.cases[]` / `owner`，违反 ⇒ `seal_path_retired_write` FAIL（不是「跳过」）。新路径的首签与建键**同样必须分成两个提交**（第 2 条 v14/I-5 的成对要求对首次签发和换路径签发一视同仁）。
       5. **状态机（唯一状态字段，三个状态都有判据，R12-1/R12-4）**：
          - `active`：**HEAD 必须存在该路径封条**，且无 `moved_to` / `frozen_at`；按规则 0–10 全链校验，`D>0` ⇒ `seal_history_reset`（不变）。文件在而 state 非 `active`、或 state 为 `active` 而 HEAD 无文件，都报 `seal_anchor_path_state_mismatch`。
          - `retired`：该路径已被 `moved_to` 指向的新路径取代；**HEAD 可以有旧文件（S-31）也可以没有（S-36 的合法形态）**。判据三条，缺一即 `seal_path_history_lost`：① `moved_to` 必填且指向一个存在的键；② 该目标路径的 HEAD 封条必须有 `moved_from.path == 本路径` 且 `moved_from.sha256 == sha256(本路径迁出前最后一枚封条字节, CRLF→LF)`；③ **迁出前那段链仍要复算**：令 `L_pre` = 本路径 `L` 中删除提交**之前**的提交序列——取值写死（v14/N-1）：`idx = max{i | L[i] 的 name-status 含 D}`（判命令 `git show --format= --name-status --no-renames <c> -- <S>`，逐 `c ∈ L` 求），`L_pre = L[0:idx]`；若 `L` 里没有任何 `D`，则 `L_pre = L`。`L_pre` 必须满足规则 0–7（`A`/`D` 按 `L_pre` 计），且 `moved_from.sha256` 必须等于 `L_pre[-1]` 那枚封条的字节。删除提交本身**不计入 `L_pre`**，但它必须**有且仅有一个**且被 `moved_from` 覆盖；`L` 里出现第二个 `D` ⇒ `seal_path_history_lost`（旧路径被删了两次 = 删+重建，不允许借 `retired` 洗白）。`retired` 之后禁止该路径任何新续签、新 `reanchor`、以及改 `e2e.cases[]` / `owner` ⇒ `seal_path_retired_write`。
          - `frozen`：**任务删除的唯一合法形态**——封条文件**必须仍在 HEAD**，`frozen_at` 必填；validator 要求 `git log <frozen_at>..HEAD -- <path>` 为空且 HEAD 封条字节 == `frozen_at` 提交的字节；违反（含**删除文件**，删除也是修改）⇒ `seal_frozen_modified` FAIL。冻结**不能掩盖此前的删除**：`L` 中 `frozen_at` 及更早的提交序列仍按规则 0–7 复算，`D>0` ⇒ `seal_history_reset`。报告固定打一行 `seal_frozen: <path>`（INFO，不是错误）。
          - **不存在「删文件但不迁出」的合法形态**：同路径封条一旦出现即不可删除；删任务只能整条冻结（`state: frozen`），文件保留。这样 `D>0` 永远有归属（R12-1 第 3 点）：`active` ⇒ `seal_history_reset`；`retired` ⇒ 必须有且仅有一次被 `moved_from` 覆盖的删除；`frozen` ⇒ `seal_frozen_modified` 或（冻结前的）`seal_history_reset`。**机器面无法区分「换路径后旧文件被删」与「任务本身被合法删除」**——所以后者被写死成 `frozen`（文件不删），不留灰区。
       6. **`moved_from` 是换路径的唯一凭证**：同 task-id 换路径必须带 `moved_from`；`moved_from.path` 必须在 `U` 里、其链可复算到迁出点、`moved_from.sha256` 与旧封条字节一致（CRLF→LF canonical）。**没有 `moved_from` 的新路径只能是全新 task-id**（旧任务按第 5 条冻结，不得删除）；旧文件被删但新封条没写 `moved_from` ⇒ **按 R12-6 优先级必有一红**：键被删 ⇒ `seal_anchor_path_unmapped`；键留 `active` ⇒ `seal_anchor_path_state_mismatch`；键标 `retired` 但无覆盖 ⇒ `seal_path_history_lost`（S-36 三种形态各验一次）。
          **`moved_from` 同时必须约束新封条的载荷（v14/I-2）**：新路径必然首签（`renewal_seq = 1`、`seq = 1`、`previous_* = null`），规则 3 的「blob == blob@L[0]」在这种路径上是**自己比自己**（`L[0]` 就是这枚新封条），所以「`moved_from.sha256` 只比旧路径 `L_pre[-1]` 的字节」挡不住「`git mv` + 顺手换掉全部 `e2e.cases[]` + `reasons=[]` + 不写 `previous_cases`」。因此换路径首签也要做**载荷等价**：把新封条与 `L_pre[-1]` 那枚旧封条逐字段比，豁免集固定为 `{renewal_seq, previous_seal_commit, previous_seal_sha256, moved_from, reanchor?}`（`reanchor` 只在换路径同时重锚时出现，仍按规则 2 的边界语义处理）；**其余字段必须逐字节相等**。不等时**不是无条件放行**：必须同时写非空 `reasons[]` 与完整的 `previous_cases[]`（id → 旧 sha，覆盖所有被改动的用例），否则 `seal_move_payload_mismatch` FAIL。这样「改名时业务数据一字不动」是默认路径，改动必须留痕且可复算（S-42/T-26）。**`signed_at` 不再承担期限语义（v16/N-2 改判）**：v15 的「新 `signed_at` 不得晚于旧值」写反了——换路径的首签签在现在，`now > old` 恒成立，每次合法换路径都会红，与 S-31 直接冲突；旧封条每续签一次 `signed_at` 就后移，拿它当豁免起点也是移动靶。v16 起：① `signed_at` **退回纯审计字段并移出上述豁免集**（换路径不是重签，新封条必须**逐字节沿用** `L_pre[-1]` 的 `signed_at`；续签才重写它）；② `gap.due` 的**下界**一律从锁键 **`exemption_start_origin`** 算（建键写死、**已有值任何命令都不改写、缺失时一次性回填**；v22/I-6 拆键——`exemption_started_at` 可被 `seal reanchor` 同步重指，**不得**拿它算 due；`due` 的上界取 `min(trunc_utc_date(first_seen_origin) + 90d, acceptance_cutover)`（先截 UTC 日期再加 90 天，全程 `date`；v23/I-1/I-3；v26/I-2），与封条字段无关；③ 反面包改为 T-28：**`exemption_started_at` 被手改刷新 / 后移、或与该路径 `L[0]` 首签封条的 `signed_at` 不逐字节相等**（v18/重要 1：主判据换成封条等值——封条字节被链规则钉住、可复算；`%cI L[0]` 只作 WARN/INFO）⇒ `exemption_start_conflict` FAIL（判序 ②）；**审计链断裂（删中间项 / 改 `from` / 换路径未继承 `exemption_start_history` / 重指未 append）另报 `exemption_start_history_broken`**（v22/I-6）；**另补两个前置**：换路径未沿 `moved_from` 递归继承链首值、首写晚于 `L[0]` 提交时间（`%cI` 只作 WARN/INFO，不单独判红）。
       7. **推进条件（v10/B-1）**：该键封条带 `reanchor`、该路径唯一 `R0` 存在、且 `R0.reanchor.from_a == epoch_origin` ⇒ `epoch_origin = R0`、`anchor_review = R0.reanchor.review`（**幂等**，任意 HEAD 可跑，含 post-lock 与 merge）。`from_a != epoch_origin`（第二次重写后尚未产生新 reanchor）⇒ 保持原值。**不要**按「HEAD 的 `renewal_seq == base_seq`」推进：post-lock/merge 会继承边界封条，会把起点指到不在 `L` 的提交。
       8. **禁止 amend 到 reanchor 提交**：amend 后 HEAD 仍在 `L` 且 `seq == base_seq`，但 `epoch_origin` 已是 amend 前的 R，`from_a` 不符，当前字段集无解（B-1）。后置 `lock --update` 必须独立提交。
       9. **连续重写的边界（v10/I-1；v13 拆词）**：后置 `lock --update` 把 `epoch_origin` 推到 `R0` 后，`R0` 在当前历史里可达；再就地重写该路径后续局部历史时，新 `reanchor.from_a` 必须等于 `epoch_origin = R0`，而 `R0` 可达 ⇒ `reanchor_not_allowed`，**当前字段集无解**（§8 死结）。若上次 reanchor 后**未跑**后置 lock，`epoch_origin` 仍是不可达旧 A，第二次重写后 `from_a` 仍可用旧 A，锚推进到 `R0_second`（第二次 reanchor 的提交）；可走通但依赖跳过第 8 条的后置 lock，**不推荐**。
       10. **时点语义与宇宙断言**：`epoch_origin` 在 reanchor 提交当刻仍是旧 A（4a 依赖）；只有后置 `lock --update` 的独立提交才推进（这就是「锚记账时点」）。每次 `check` / `lock --update` 都要：① 按第 2 条算出 `U` 并断言「键集 ⊇ `U`」（append-only，缺键 ⇒ `seal_anchor_path_unmapped`）；② 断言「键 ∖ `U` == ∅」（凭空多出的键 ⇒ `seal_anchor_path_orphaned`）；③ 断言每个键的 `state` 与 HEAD/历史一致：HEAD 有文件且 state 非 `active`/`frozen` 非法；HEAD 无文件且 state 为 `active` ⇒ `seal_anchor_path_state_mismatch`，state 为 `frozen` ⇒ `seal_frozen_modified`，state 为 `retired` ⇒ 走第 5 条三条判据。**同一遍状态检查的锁内一致性判据，顺序完全引用判序 ②，本节不再自排（v25/次要 2）**：依次判**三个形态 / 结构码**（`exemption_start_signed_at_not_canonical` → `signed_at_not_canonical` → `exemption_start_history_broken`）→ `exemption_start_conflict`（`detail` 三分支）→ 两个 rewritten（`exemption_start_origin_rewritten` / `first_seen_origin_rewritten`，含 `first_seen_origin > L[0].signed_at`，`detail.kind = after_signed_at`）→ `exemption_due_out_of_range` → `epoch_origin_history_rewritten`；本轮具体展开 ④ `exemption_started_at` —— 被 `lock --update` 刷新/后移、带 `moved_from` 的新键未沿 `moved_from` 递归继承链首值、或与 `L[0]` 封条 `signed_at` 不逐字节相等（`%cI L[0]` 只作 WARN/INFO，不单独判红） ⇒ `exemption_start_conflict`；**`exemption_start_history[]`** —— 删中间项、改 `from`、第 i 项 `from` ≠ 第 i-1 项 `to`、首项 `from` ≠ `exemption_start_origin`、末项 `to` ≠ 当前 `exemption_started_at`、`started_at` 被重指而数组未 append、**或版本前缀单调被破坏（后版本不是前版本的前缀扩展 / 单版本新增超过一项 / 相邻版本不连续）** ⇒ **`exemption_start_history_broken`**（v22/I-6；v23/I-1）；`exemption_start_origin` 与空数组时的 `started_at` 不等、**或 `exemption_start_origin > exemption_started_at`（v23/I-3）** ⇒ 同码；⑤ `epoch_origin_history` —— 末元素 ≠ 当前 `epoch_origin`、元素重复、或长度不等于 `1 + 重指次数` ⇒ `epoch_origin_history_rewritten`（只作篡改检测，**不设次数上限**）。不得把缺键当 `null`，也不得把 `lock_missing` 当「无锚」。**新增封条的中间态是预期红（v14/I-5）**：封条已提交、建键提交还没到，此时 `U` 有该路径而键缺 ⇒ `seal_anchor_path_unmapped`；这是两个提交之间的正常状态，`check` 在 PR 头上才要求全绿。
       11. **`seal freeze`：`frozen` 的唯一写入口（v14/I-1）**：`atlas solution seal freeze --seal <path> --at <sha>`。
          - **只写锁**：把该路径键的 `state` 置 `frozen`、`frozen_at` 置 `<sha>`，**不碰封条字节**（封条一个字节都不改，因此不产生续签，`renewal_seq` / `N` 都不变）；`epoch_origin` / `renewal_seq` / `n` / `anchor_review` 原样保留；**`exemption_start_origin` / `exemption_started_at` / `exemption_start_history` / `first_seen_origin` 的已有值也全部原样保留（不改写）；缺失字段不在这里补**——一次性回填只发生在 `lock --update`（§1.1.3 第 3 条；v22/I-6、v23/I-2：`seal freeze` 不是重锚、不改 `L[0]`，既不需要也不允许重指）。
          - **`--at` 的语义**：`frozen_at` = 该路径**最后一次封条变更提交**的 SHA，即**按 §3.2 符号表算出的 `L[-1]`**（`L` 由 `rev-list --full-history` + 逐提交 `git show` 构成；v15/N-1：**不得另立 `git log -1` 的第二套算法**）。允许显式给 `--at`，但必须等于 `L[-1]`，否则拒绝——不许把冻结时间写成任意提交。冻结不改封条，所以产出后 `git log <frozen_at>..HEAD -- <path>` 立即为空。
          - **前置**：该路径键存在（缺键 ⇒ `seal_anchor_path_unmapped`，不予新建）、`state == active`（已 `frozen` ⇒ 幂等成功，退出码 0；已 `retired` ⇒ `seal_path_retired_write` 拒绝）、仓形态完整（shallow / partial 拒绝，与 `seal reanchor` 同口径）。
          - **写后独立提交**：`seal freeze` 只改锁，不改封条；提交后 `check` 打 `seal_frozen: <path>` INFO。之后 `lock --update` 遇该键**原样保留** `state: frozen` 与 `frozen_at`（第 3 条）。
          - **反面包**：S-38 从此命令接续构造，不再靠手改锁。
       12. **改根：`lock --update --assets-root <new>`（v15/D-1 唯一合法出口；v16/I-2 改历史元素形态；v19/阻断 1 换字符集源；v20/阻断 1 空白与严格版）**：① `new` 必须**通过 `_support/layout.py` 的 `validate_value(new, "assets_root", s)`（默认严格版，含 FS 检查）**（`LayoutError` ⇒ 拒绝，`exit 2`）、**首尾无空白**（`new != new.strip()` ⇒ 拒绝）、且不等于当前 `layout_assets_root`（相等即幂等、不 append）。**RFC 不另立字符集**；`ROOT_RE`（若保留）只作 CLI 提示/示例的**写侧建议**，不作判据。② **同一提交**里 `atlas.config.yaml` 的 `layout.assets_root` 已改成 `new`，且资产树已整体移动（`git mv <old> <new>`）——config / 资产树 / 本命令产出的锁必须同提交；③ 必须带 `--anchor-review <REVIEW-ID>`（与 `seal reanchor` 同一评审面），该评审号**只写进新 append 的历史元素** `{root: new, review: <REVIEW-ID>, commit: <执行本命令时的 HEAD>}`，**绝不覆写任何键的 `anchor_review`**——`anchor_review` 的定义是「创建当前纪元的那次 reanchor」，改根不是重锚；覆写会让 4a/4b（`anchor_review == current.reanchor.review`）对做过 reanchor 的路径**假红**，S-30 的多纪元外部锚也会被破坏（v16/I-2）。**评审号是自述（v20/重要 2）**：`review` 只校验 `REVIEW-\d{8}-\d{2}` 形态，**不做台账查询、不验真伪**；同一 REVIEW-ID 若同时用于「改根」与「改 cutover」（即同时出现在 `assets_root_history[].review` 与 `acceptance_cutover_review`）⇒ 新码 **`review_reused` FAIL**；④ append `assets_root_history`（旧值永不删除、不重排、不排序），并把 `layout_assets_root` 置 `new`；⑤ **禁止同时删旧键**：旧根仍在历史并集里 ⇒ `U` 仍含旧路径，删键 ⇒ `seal_anchor_path_unmapped`（S-43）。合法改根后旧键**照常参与校验**（`state` / `epoch_origin` / `anchor_review` 都不变），因此不会 `orphaned`（S-44；S-44 的仓里另有一条**已 reanchor** 的路径，改根后必须仍 PASS）。

3. **解析器与版本门（P1/P-1/P-5）**：

   - 现状：`parse_manifest_text`（`_support/solution.py:177-252`）只支持「顶层标量 + `members/contracts/requirements` 三个列表节」。`definition:` 这类以 `:` 结尾的顶层键走 `:196-202` 分支，不在白名单 ⇒ 进 `data["unknown"]` 并置 `section="__unknown__"`；随后缩进的 `domain/path` 被 `:223-224` 的 `continue` 跳过。结果 `definition` 读出 `None`，**不报错**。`acceptance_cutover` / `min_atlas` 走 `:218-219`，同样只进 `unknown`，永远取不到。`definition: null` 也因键不在白名单而落 `unknown`，B 的 D-11 会误红。
   - B-0 批必须改：`definition` 作为**一层嵌套映射**解析（只认 `domain` / `path` 两个子键），**键本身也进标量白名单**（允许 `definition: null`）；标量白名单加 `acceptance_cutover` / `acceptance_cutover_review` / `min_atlas`（v19/阻断 2：`acceptance_cutover_review` 只在「cutover 晚于包级默认」时写，见 §5.1）。`definition: null` 经 `_scalar` → `yaml_scalar` 归一为 `None`（`_support/solution.py:102-104`），白名单加入后不会读成字符串 `"null"`。
   - **B-0 的边界（P-5/Q-5）**：B-0 只接受 `definition.path == <assets_root>/prd/solution-prd.md`（默认名）；B 批才放开任意满足 §1.1.4 的 `-prd.md`。这样 B-0 期写的 v2 清单不会被 5 个硬编码读者读错。**`migrate` 落盘前必须按同一白名单校验目标路径**：自动探测到非默认名 ⇒ 拒绝且不写文件（否则写出的是本版 `load_manifest` 自己拒绝加载的清单，§5.2 V-12）。
   - **版本门提前（P-1）**：B-0 的 `validate_manifest` 已接受 `{1,2}`（`_support/solution.py:267-268` 的 `!= SCHEMA_VERSION` 改为区间判断），否则 `migrate --to 2` 之后同一次运行里的 `lock --update` 会在 `load_manifest` 直接 `SolutionError`。
   - **锁版本（P-1；v15/D-1 补两字段；v16/D-1/I-1 定 v1 口径；v17/B-1/I-2/I-4 加解析层与历史口径）**：锁 schema 由清单决定——清单 `version: 2` ⇒ B-0 的 `lock --update` **直接写 `schema_version: 2`**（`LOCK_SCHEMA_VERSION = 2`、`schema_version = 2 if data["version"] == 2 else 1`）；只有 v1 清单才写 `1`。**v2 锁必须含 `layout_assets_root` 与 `assets_root_history[]`**：写入 2 时 `layout_assets_root` 取当时的 `layout.assets_root`、`assets_root_history = [{root: 该值, review: null, commit: null}]`（append-only，之后只许 append、只许加对象、不许改 `.root`）。**v1 锁的统一口径（v16/I-1；替换 v15 的「升 2 之前不判」；v17/I-2 扩到历史）**：v1 锁或缺这两个字段 ⇒ **跳过 ⓪-3/⓪-4 两条根断言**（无历史可判）并打 **`assets_root_history_absent` WARN**；**v1 版本一律不贡献根**（v18/次要 1）；**但锁文件任一版本（含当前）v1 且 `seal_anchors` 非空 ⇒ `lock_v1_with_seals` FAIL**（本工具不会产出「v1 锁 + 封条键」这一形态，出现即人为构造；这条堵住「退回 v1 锁以跳过根断言」）。**删锁重建**（`git rm` 锁 → 改根 → 重建 v1/v2 锁）由 `assets_root_history_rewritten` 覆盖：旧锁版本仍在 `git log` 里，当前锁缺字段而历史版本有 ⇒ FAIL（§0.15 D-1）。**解析层（v17/B-1/I-4）**：当前锁解析失败 ⇒ `lock_unparsable`；任一历史版本解析失败或结构不合法 ⇒ `lock_history_unparsable`；两者都是 FAIL，**`lock_missing` 只对文件不存在成立**（v30/S-2：文件不存在但 Git 记录曾有该路径 ⇒ `lock_tracked_but_deleted`，见 §3.2 ⓪-0）。**写侧版本规则（v31/I-3）**：`manifest.schema_version == 2` ⇒ 本次 `lock --update` 写出的锁 `schema_version` **必须为 `2`**，并与 `layout_assets_root` / `assets_root_history[]` **同一次写入**（与 §1.1.3 ① 的「清单 v2 ⇒ 写两个根字段」并列）；**不得在 v2 清单上产出 v1 锁**——若同一次更新还建了 `seal_anchors` 键，落盘即撞 ⓪-2 `lock_v1_with_seals`（T-32③a 的「无封条仓首次建键」会永久不可 PASS）。本规则**从 B-0 起生效**（v32/B-2）：`LOCK_SCHEMA_VERSION = 2`（`_support/solution.py:37/39`）、`schema_version = 2 if data["version"] == 2 else 1`（`:1290-1291`），因此 B-0 在 v2 清单上跑 `lock --update` 就已经产出 v2 锁，不存在「B-0 期锁仍为 v1」这一形态。**写侧（v17/B-1）**：`lock --update` 必须输出严格 JSON，且不得重排/归一化/重写既有 `assets_root_history`。升 2 当刻必须补齐——否则 v2 锁的第一天就能靠改 config 缩小 `U`。旧 `schema_version: 1` 锁在所有后续版本都可读（只读、不可再作为「无变更」依据）。**B-0 期不判 `definition_unbound`**（B 批才判）；「v2 清单 + v1 锁」不是本工具会产出的形态（锁 schema 由清单决定，⓪-2 已把该形态归为人为构造），故不另立豁免。**码表补登（v17/次要 3；v18 增补）**：`migration_required` = WARN、exit 0、**不计入 FAIL 数**（v1 存量清单迁移提示，不阻断 `check`）；`lock_unparsable` = FAIL、**exit 1**（⓪-0，**失败即短路**；v32/I-4：⓪ 层统一 1，exit 2 只留给用法错误与 `internal_error`）；`lock_history_unparsable` = FAIL、**exit 1**（⓪-1，不参与 `--allow-unverifiable-chain` 降级）；`exemption_start_conflict` = FAIL（判序 ②，`detail.kind ∈ {not_equal_signed_at, moved_from_chain_mismatch, chain_head_missing}`，v28/次要 1 统一记号）；`acceptance_cutover_missing` = FAIL（§5.1，已刷新后任一侧缺失或两侧皆空）；`acceptance_cutover_mismatch` = FAIL（两侧有值且不等）；`acceptance_cutover_unreviewed` = FAIL（v19/阻断 2，cutover 晚于包级默认且无 review 记录，或 > 默认 + 90 天；`detail.kind ∈ {review_missing, beyond_default_plus_90d}`）；`prd_schema_gate_unarmed` = **WARN**、exit 0、不计入 FAIL 数（`reader_version >= 0.4.0-0 && PRD_SCHEMA_2_FROM is None`）。
   - 未知顶层键仍进 `unknown`；但 `definition` 的未知子键 ⇒ `definition_field_unknown` FAIL（不静默）。
   - 反面包 D-32/D-33/D-35：v2 round-trip 后 `definition.domain` / `definition.path` / `acceptance_cutover` / `min_atlas` 全部可取，`definition: null` 不落 `unknown`，且 `unknown == []`。

4. **`definition.path` 的硬约束（R6）**：

   - 必须位于 `<assets_root>/prd/` 之下；
   - 必须以 `-prd.md` 结尾；
   - 拒绝绝对路径、`..`、symlink 逃逸。
   - 违反 ⇒ 加载期 `definition_path_unsupported` FAIL（不是 WARN）。

   该约束让 4 个 `glob("*-prd.md")` 读者**无需改代码**即可看到自定义文件名。v3 把 `validators/validate_e2e_index.py` 的 glob 误计为硬编码（`9cdb1a1` 的 `:773`，A 批后为 `:830`）；它是 glob，v4 已更正。

5. **读者清单（9 个，R6）**：

   | # | 位置 | 类型 | v6 处理 |
   |---|---|---|---|
   | 1 | `_support/solution_task.py:147-148` `_ac_prd` | 硬编码 | B 批读 `definition.path` |
   | 2 | `_support/solution_task.py:239-242` `_pointer` | 硬编码 | B 批读 `definition.path` |
   | 3 | `_support/solution.py:999` `_prd_skeletons` | 硬编码 | B 批按 `definition.path` 生成 |
   | 4 | `_support/solution.py:1265-1270` `check_solution` 骨架检查 | 硬编码 | B 批读 `definition.path` |
   | 5 | `_support/solution_e2e.py:350` `_ac_coverage` | 硬编码 | B 批读 `definition.path` |
   | 6 | `validators/validate_e2e_index.py:830` | glob `*-prd.md` | 后缀约束保证命中，免改 |
   | 7 | `validators/validate_prd.py:346` | glob `*-prd.md` | 后缀约束保证命中，免改 |
   | 8 | `validators/validate_ac_alignment.py:93` | glob `*-prd.md` | 后缀约束保证命中，免改 |
   | 9 | `validators/validate_ac_alignment.py:126` | glob `*-prd.md` | 后缀约束保证命中，免改 |

   - 5 个硬编码读者全部进 B 批；4 个 glob 读者进 B 批夹具（自定义文件名必须被它们看到），不改代码。
   - B 批上线到 D 批之间不存在窗口：`definition.path` 约束在**加载期**生效，v2 清单只有 B 批之后才可能被写入；v1 默认 `solution-prd.md` 天然满足约束。A 批不解析清单（§6）。

6. **摘要绑 blob，不绑工作树（I2）**：

   - `sha256` = sha256(**CRLF→LF 归一后**的 `git cat-file blob <commit>:<path>` 字节)；`blob` = 同一对象的 Git object id（按原字节）。
   - reader 复算：先 `git cat-file -t <commit>:<path>` 必须为 `blob`，再按同一 CRLF→LF 口径算 sha256；`blob` 与原字节一致；任一不符 ⇒ `definition_source_mismatch` FAIL。
   - 归一化口径与 E2E 块摘要一致（§3.4），避免 Windows 与 Unix 两套标准（I2）。
   - worktree 只用于判脏：`lock --update` 时 `git status --porcelain <path>` 非空 ⇒ 拒绝签发；`check` 时非空 ⇒ `definition_worktree_dirty` WARN（摘要仍从 blob 复算，不因换行折算失真）。Windows `autocrlf` 不会让摘要漂移。
   - `commit` 不可复算按**三态**，与 §3.2 同口径（P3/R9/重要 2）：对象本地不存在 ⇒ `definition_commit_unverifiable`（**默认严格态 FAIL**；仅窄开关 `--allow-unverifiable-chain` 降 WARN）；对象存在但 `commit:path` 不是锁里的 blob ⇒ FAIL；对象存在且命中 ⇒ PASS。**`commit == null` 不在这三态里**（v11/次要 3）：它是 `init` 刚写完的暂时态，见 `definition_commit_pending`（§5.2 第 8 条），不得落进「对象不存在」分支。浅克隆必须 `fetch-depth: 0`（§5.2）。该开关不复用 `--lenient`。

7. **front matter → 锁字段映射（I11）**：

   | 锁字段 | 来源 | 规则 |
   |---|---|---|
   | `prd_version` | front matter `prd_version` | 整数，≥1；缺失按 1（首锁回填）；新模板默认 1 |
   | `prd_date` | front matter `date` | `YYYY-MM-DD`，与模板 `date` 一一映射；缺失 ⇒ `prd_date_missing` FAIL |
   | `prd_schema` | front matter `prd_schema` | 整数；使用新列 / 契约表要求 2；缺失按 1 |
   | `version` | front matter `version`（`0.1.0`） | 文档 semver，**不参与身份、不映射**（决策 3） |

   `templates/prd/domain.md` 已含 `prd_version` 与 **`prd_schema: 2`**（v41 实况校正：证据两列已随 B 批落地），字段改动随 B 批（R1）；**D 批不再升 `prd_schema`**。

8. **`requirements_digest` canonical form（I1）**：

   - 输入：`requirements[]` 中每项只取 `id / member / acs / case_ids / cross_repo_e2e` 五个键。
   - 规范化：
     1. 所有字符串做 Unicode NFC；
     2. `acs`、`case_ids` 去重后按码位升序；
     3. 缺失列表 = `[]`；`cross_repo_e2e` 缺失 = `null`；非 null 只允许字符串 `none`（其他值在清单校验已 FAIL），做 NFC 后原样写入；
     4. 对象按键名升序；整体按 `(id, member)` 升序；
     5. 序列化固定 `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)`，UTF-8，无尾随换行；
     6. 取 sha256 小写十六进制。
   - **golden vector**：
     - 输入：`REQ-001 / backend / [AC-SOLUTION-001, AC-AUTH-012] / [E2E-AUTH-001] / null`
     - canonical 字节：`[{"acs":["AC-AUTH-012","AC-SOLUTION-001"],"case_ids":["E2E-AUTH-001"],"cross_repo_e2e":null,"id":"REQ-001","member":"backend"}]`
     - 期望：`45ef0f9a94ee9f118f5254caf69fdb4b14667483b8f7023cfb90ffe3386afdd1`
   - 实现若与此向量不一致 ⇒ 夹具红，不允许「换个序列化器」蒙混。

8-b. **锁内摘要字段的首次判定与不可变（B-0 写/读；`waiver_baseline_drift` 归 C；v43 补判序）**：

   - **`requirements_digest`**：**首次判据 = 键不存在或值为 `null`**（`lock.get("requirements_digest") is None`）；首锁 / 首次 `lock --update` 时按第 8 条的 canonical 序列化写入。已写入后每次只**复算比对**，不静默改写；不等 ⇒ `manifest_drift`（第 9 条）。**同一序列化器 + 同一 golden vector**：第 8 条的向量即本字段的向量，不允许另写一套。
   - **`waiver_baseline_digest`**：**首次判据 = 键不存在或值为 `null`**；首锁写 `null`（示例即 `null`，不省略该键），**`null → 值` 的唯一合法写入点 = 首次观察到非空可豁免集合的那次 `lock --update`**（v43/重要 1：不提前用空集占位，否则 D 批首次建豁免表就被判 drift；`null` = 尚未建立基线，`[]` = 已建立且为空集）；写入值 = 当时集合按同一序列化器（JSON 字符串数组、NFC、码位升序、`json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)`、sha256 小写十六进制）算出的摘要。**golden vector**：输入 `["REQ-001","REQ-002"]` → 期望 `f1da37a34aac137ff962018a1d6295ca20057c682576bad646e06ac950dde527`。
   - **不可变与三路径（v42/阻断 2）**——语义：键已存在且重算值变化 ⇒ **不得静默改写**。
     - **老锁升级**（v1→v2，锁历史**从未**含非 null 值）⇒ 走首次分支：写 `requirements_digest` 当前值；`waiver_baseline_digest` 写当前基线或 `null`。
     - **换锁**（当前锁缺该键 / 值为 `null`，但**锁历史任一版本含非 null 值**）⇒ **`manifest_digest_removed` FAIL**——删键不能重定基线。
     - **回滚**（**仅**当前 `definition.prd_version` < 锁历史最大 `prd_version`）⇒ **`manifest_rollback` FAIL**。**内容回滚不另判**（v43/阻断 1：digest 命中历史旧值可能合规改回旧版，再改回又命中另一个旧值 ⇒ 永久红无出口）；读侧不再用 digest 判回滚。
     - **C 批读侧**：`waiver_baseline_digest` 与当前可豁免集合重算值不等 ⇒ **`waiver_baseline_drift` FAIL**（v42/重要 3：本码**移入 C**，纯摘要比对、不依赖 crosswalk）；`requirements_digest` 不等 ⇒ `manifest_drift`。
     - **判序与互斥（v43/重要 2）**：`manifest_rollback` **优先**；命中后抑制 `manifest_digest_removed` 与 `waiver_baseline_drift`，同一运行只报一个。三码的 `detail.field ∈ {requirements_digest, waiver_baseline_digest}`；`manifest_rollback` 另带 `detail.prd_version = {current, max}`。批次：`manifest_*` 归 **B-0**（锁读侧），`waiver_baseline_drift` 归 **C**。

9. **单调身份（可见性，不是防伪）**：

   - 锁存在且同一路径的 blob 变化 ⇒ `prd_version` 必须严格递增，且 `lock --update` 必须带 `--review <REVIEW-ID>`；同版本换字节 ⇒ 拒绝，并输出 `请把 front matter prd_version 提到 <当前+1>`。
   - `prd_version` 递减或 `prd_date` 倒退 ⇒ 拒绝。
   - `definition.path` 变化必须额外带 `--allow-definition-path-change --review <REVIEW-ID>`；无评审 ⇒ 拒绝。
   - **评审对象是 PRD diff**：机器只校验 REVIEW-ID 的存在与三处一致，不校验内容；同路径内容替换也只能靠人审看出来（R2）。
   - `prd_schema` 必须等于工具支持的上限；高于自身支持 ⇒ `prd_schema_unsupported` FAIL。
   - **机器只证明「变了」**：以上规则不阻止「同域副本 + 抬版本 + 改路径 + 假 REVIEW」通过；是否合法由评审看 PRD diff 判（R2，§2.6）。

10. **`definition: null` 的边界**：只有 `requirements` 全为空时才允许；v2 清单任一需求有 `acs` ⇒ `lock --update` 拒绝写 null，`check` 报 `definition_unbound` FAIL。v1 清单在 0.3.x 只 WARN（迁移窗），0.4.0 加载期硬拒。

**为什么原方案不成立**

- v2 只用 `sha256` 绑定「签发后未变」，且把可变的工作树字节当摘要源；Windows 换行与未提交编辑都会让它失真（I2）。
- v3 用 `version: 0.1.0` 这个文档 semver 当身份：它不是整数、无法单调比较，模板也没有字段，B 批产不出可复算的锁（R1）。
- v3 把「严格递增」说成防副本，是超额承诺：同 domain、同 code、同 AC 编号的副本抬版本后仍可闭合（R2）。
- v3 只把 glob 读者算了 1 个，实际 4 个；不约束路径就得在 B→D 之间留一个「门绿但聚合 0/N」的窗口（R6）。
- v4 漏了**解析器**：`definition` / `acceptance_cutover` / `min_atlas` 在 `parse_manifest_text` 里进 `unknown` 或被跳过，所有仓会 `definition_unbound`，而夹具仍可能绿（P1）。

**新判据**

- 路径约束、blob 摘要、版本单调、schema 版本、digest 复算、v2 round-trip 六条全部 FAIL 级。
- `commit` 不可复算：默认严格态 FAIL，仅 `--allow-unverifiable-chain` 降 WARN（与 §3.2 的 `chain_unverifiable` 同口径，I3/R9/重要 2）。
- 摘要一致但 AC 不在定义源 ⇒ `ac_missing`（`--allow-dangling-acs` 在 `< 0.4.0` 注册，0.4.0 起不注册；见 §2.6 的谓词修正）。
- 摘要不同 + AC 缺失 ⇒ 先报 `manifest_drift`，不落 `ac_missing`。

**反面包**：D-01…D-35。

### 1.2 AC 引用与双命名空间

**改了什么**

- 方案 AC 唯一键：`(definition.path, AC ID)`。
- 成员 AC 唯一键：`(member, 成员 PRD 路径, AC ID)`。
- crosswalk 六列（I1 补 `成员域`）：

  ```markdown
  | 方案AC | 成员 | 成员PRD | 成员域 | 成员AC | 依据 |
  |---|---|---|---|---|---|
  | AC-SOLUTION-001 | backend | product/prd/auth-prd.md | auth | AC-AUTH-012 | 契约 C1 |
  ```

- `成员PRD` 必须在成员仓内、`<member>/<path>` 可读；`成员域` 必须与 `成员AC` 前缀一致，并与该 PRD front matter 的 `domain` 一致；不一致 ⇒ FAIL。
- 一个成员可以有多份 `*-prd.md`；`成员PRD` 是消歧键，缺列即 FAIL。
- 基数：1:N 合法；同一成员内 N:1 合法；同一成员 AC 回指两个方案 AC 只判 `(方案AC, 成员)` 是否有需求行。

**为什么原方案不成立**：v2 的 crosswalk 只有 `(方案AC, 成员, 成员AC)`，成员多域时无法定位定义行。

**判据**：C-01…C-11。

### 1.3 成员 AC 落点与卡投影（B1/B2/R4/I5/I6）

**改了什么**

1. **成员 AC 权威落点 = 成员 PRD 定义行**；任务卡、`solution.md`、记录只能引用。
2. **卡断言只认专用行**，不认裸 AC token：

   ```text
   atlas-acceptance: AC-SOLUTION-001, AC-SOLUTION-002
   atlas-acceptance: none（reason=内部重构；owner=@alice；due=2026-12-31）
   ```

   - 只有「行首（允许缩进）`atlas-acceptance:`」才算。
   - **跳过 fenced code block（``` / ~~~）与 HTML 注释块（I5）**：围栏内或注释内的行不计。
   - `task create` 生成的 `title = [AC-...] req` 与 `description = 跨仓任务 ...`（`_support/solution_task.py:377-378`）不匹配该前缀，空壳卡不会天生通过。
   - **AC 集合判据（重要 4/8）**：行内 AC 集合必须 **⊆ 该 `(id, member)` 的 `requirements[].acs`**。**卡门只判这一条**（v41 裁定）：C 批不看「crosswalk 像」、不做孤儿扫描；crosswalk 解析器尚未落地（§2.1），C 不 import `_support/ac_crosswalk.py`。「crosswalk 像存在」与「源 PRD 未定义的 AC 归 `ac_missing`」都是 **D 批 `validate_ac_alignment` / `check_solution` 的判据**，C 批卡门不重复红（否则 `--allow-dangling-acs` 降一次、卡门又红一次）；用方案 AC 冒充成员 AC 的区分同样归 D 批。
   - **`none` 的边界（重要 5）**：仅当该 `(id, member)` 的 `requirements[].acs` 为空时才可用；需求有 AC 却写 `none` ⇒ FAIL，必须走需求级豁免行（§2.1 的 `ac-crosswalk-waivers.md`，带 owner/due/review）。
   - **`card_untracked` 是 C 批硬前置（Q-4/决策 3）**：不做 `signed_at` 分层，不设宽限。迁移工具是 B-0 的 `migrate --check-members`（只读，逐成员打印 `git add -f` 命令）；前置未完成 ⇒ C 批不上线（§6）。到达 C 批后，成员仓未跟踪卡一律 FAIL，与封条何时签发无关。
3. **封条绑定声明式投影，不绑整卡字节**：

   ```json
   "card": {
     "path": ".trellis/tasks/<ID>/prd.md",
     "projection": {
       "acceptance_acs": ["AC-SOLUTION-001", "AC-SOLUTION-002"],
       "exemption": null,
       "sha256": "<canonical projection json>"
     }
   }
   ```

   - 投影只含 `atlas-acceptance:` 行的解析结果；Notes、进度、正文修改不改变投影。
   - 验收行变化 ⇒ 投影 sha 变化，重签 `reason=card-acceptance-change`。
   - 投影 canonical 化与 §1.1 的 `requirements_digest` 同一序列化器。
4. **封条归父仓（决策 2）**：

   - 封条落父仓 `<assets_root>/reviews/apply/<member>/<task-id>.seal.json`；单仓模式 `<member>` 写 `-`。
   - 父仓 `git ls-files --error-unmatch <seal>` 必须命中。
   - 成员仓不再有 `<assets_root>/reviews/apply/`，删除 v3 的成员封条设计。
5. **成员侧只做卡投影校验**：

   - `validate_task_card`（成员 `atlas check`）读 `.trellis/tasks/<ID>/prd.md`，解析 `atlas-acceptance:`，与父仓写入的 `solution.md` 指针 `acs:` 集合比较；只判语法、`none` 三字段、AC 集合 ⊆ `requirements[].acs`、**任务卡 Confirmed 证据状态（§1.5 第 8 条，v42/重要 8）**。
   - 成员侧**不读**父仓 PRD、crosswalk、封条；**不判 PRD 的证据列**（Confirmed 的证据状态要判，见上）、不判 e2e 选择器。
   - 成员仓单独跑 `atlas check`：卡投影项照判；父仓项记 N/A（显式原因，见 §2.4）。
6. **父仓定位成员卡（P4/重要 2）**：`members[].path` + 既有 `find_task`（`task.json` 的 `meta.solution/requirement/member`）。

   - **卡路径双解析（重要 2）**：先找 `.trellis/tasks/<ID>/prd.md`；未命中再找 `.trellis/tasks/archive/<month>/<ID>/prd.md`（Trellis 归档，§3.3 实测）。两处都找不到才算 `card_absent`；归档中命中的卡**不判新鲜度**（`status=archived`），但投影仍参与校验。封条 `card.path` 不随归档改写（§2.4 决策 6）。
   - **迁移前置（C 批硬前置）**：成员仓必须跟踪 `.trellis/tasks/*/prd.md` 与 `solution.md`；判据 `git -C <member> ls-files --error-unmatch <path>` 必须命中。不跟踪 ⇒ `card_untracked` FAIL（不是 SKIP），因为 CI 按锁 clone 后 `.trellis` 根本不在工作区。**无宽限**：不看封条 `signed_at`，C 批上线即 FAIL（Q-4）。
   - 封条存在时 `card_absent` **一律 FAIL**（签发时父仓已承诺投影，卡丢了就是资产缺失）；只有本地开发可用 `--allow-card-absent` 显式降为 WARN，CI 禁止该开关。
   - `member_workspace_absent` **默认 FAIL**；`--lenient`（仅无封条，**锁不再拒绝**，Q-6）才 SKIP；`card_untracked` / `card_absent`（有封条）/ `seal_absent` 默认都是 FAIL。`--strict` 默认开启；`--lenient` 仅当仓内存在封条时拒绝执行（§3.3）。
   - 封条 `card.projection` 是父仓快照；成员缺席且无封条时不得判 PASS。
7. **存量卡迁移（I6）**：新增 `atlas solution task acceptance --backfill`。

   - 从 `solution.md` 指针的 `acs:` 生成 `atlas-acceptance:` 行；
   - 已存在该行 ⇒ 拒绝（幂等，不覆盖）；
   - 只追加一行，不动卡正文；执行后由人提交，diff 可见。
8. **时点**：封条仍在 apply 时签发；投影对工作文档稳定，不引入第二个封条生命周期。

**为什么原方案不成立**

- v2 的「卡片任意位置出现 ≥1 个 AC token」被生成内容直接满足（B1）。
- v3 的整卡 sha 把 Notes/进度算进绑定，正常工作必然 stale（B2）。
- v3 把封条放成员 `<assets_root>/reviews/apply/`，成员读不到父仓 `prd-global`/`ac-crosswalk`/`e2e-index`，上游绑定无法复算（R4）。
- 不跳过围栏块，` ```atlas-acceptance: ... ``` ` 会被计数（I5）。

**判据**

- 活跃任务无 `atlas-acceptance:` 行 ⇒ FAIL（0.4.0；0.3.0 WARN）。
- 行内 AC 集合 ⊄ 该 `(id, member)` 的 `requirements[].acs` ⇒ FAIL。**「crosswalk 像」不在本判据内**（整体归 D 批，见 §1.3.2 与 §2.1）：C 批只有这一条集合判据。
- 需求有 AC 却写 `none` ⇒ FAIL（`none` 只对空 AC 需求合法）。
- `none` 缺 `reason/owner/due`，或 due 过期 ⇒ FAIL。
- 投影 sha 变化但 reason 不是 `card-acceptance-change` ⇒ FAIL。
- 围栏块 / HTML 注释内的行被计数 ⇒ 夹具红。
- 成员仓未跟踪卡（C 批起）⇒ `card_untracked` FAIL，无 `signed_at` 宽限；有封条但卡在 active 与 archive 都缺失 ⇒ `card_absent` FAIL。

**反面包**：K-01…K-22。

### 1.4 记录权威：md 是人证，seal 是绑定证（B8/决策 2）

**改了什么**

- 封条 `kind ∈ {binding, backfill, legacy}`；删除 `kind=apply`。
- `binding` 的语义 = 「签发时刻，资产字节被绑定」，**不声称 apply 跑过**。
- 不做 provenance：Atlas 不拥有执行器；`run_id` 可由人手写，提交前也无法要求「md 与封条同一 commit」。再加一个可伪造的 provenance 就是第三种假证据。
- `atlas-apply.md` 仍是执行证据；`validate_walkthrough` 按既有七小节判完整性，机器不据散文判绿。
- **封条归父仓**：父仓是唯一写者/读者；成员仓只提交任务卡与 `solution.md`。
- **「记录紧邻任务」偏好被放弃（决策 2）**：封条按父仓资产归属组织（`<member>/<task-id>`），不按成员任务目录组织；成员仓不持有封条。
- 覆写：apply 先写 md，再签 `binding`；旧封条不留副本，Git 是历史；封条存 `previous_seal_sha256` 与 §3.2 的续签链。
- **所有 `kind` 共用三个顶层字段**：`renewal_seq`、`previous_seal_sha256`、`previous_seal_commit`（外加可选 `reanchor`）；首签 `seq=1`、`previous_* = null`，续签按 §3.2 复算。`first_signed_commit` 删除（P-2）；reanchor 由 `reanchor` 对象承载（§3.2）。
- 七小节不变；机器可读表只在第 4 小节内部，封条是独立文件，不是第八小节。

**判据**

- `kind=binding|backfill` 的封条存在、md 缺失 ⇒ `validate_walkthrough` 按既有规则 FAIL；`kind=legacy` 不要求 md。
- md 改错别字 ⇒ 机器 PASS（有意不绑散文）。
- 任何文档/帮助里再出现「seal 证明 apply 已跑」⇒ 文本判据失败（U-03）。

### 1.5 证据状态（B12/R7/I10）

**改了什么**

1. Assumptions 表追加 `证据状态`（`verified/assumed/unverified`）与 `证据指针`（`系统@版本#定位`）。
   - **节名与表头（v17 补，收编实现侧现状）**：Assumptions 节**不以标题文案定位**，而以表头定位——表头必须含 `假设内容` **或** `采用的默认值`（`strip()` 后逐字比对）。因此 `## 六、假设`、`## 六、默认值`、`## 六、假设与默认值`、`## Assumptions` 都能命中；v17 前把 `## 六、假设与默认值` 当成「未声明」跳过，是识别层缺口，不是文档错。
   - **证据列表头的比对方式（v17 补）**：表头单元格 `strip()` 后**逐字相等**才认（fail-closed：不做包含匹配、不做大小写折叠、不做全角/半角归一、不认括号补充说明）。`证据 状态`、`Evidence State`、`证据状态（必填）` 都不通过；**错误文案必须提示「疑似别名」**——列出与标准表头最接近的一项（编辑距离 ≤ 2 或仅空白/大小写差异），但**不得因文案而放行**，也不得把「疑似别名」降级成 WARN。
2. **强制范围与执行点（按 `prd_schema` 分层，重要 2/5）**：
   - `prd_schema: 2`（新 PRD，含新列/契约表）：**立即**要求两列；缺列 ⇒ FAIL，不享受缓冲。
   - **`prd_schema: 1` 的判定（决策 5；v17 写死判据）**：按该 PRD 文件的**首次提交时间**与 0.4.0 发布点比较——`git log --diff-filter=A --format=%aI -- <prd>` 取最早一条（`--format=%aI` 是 author date，与发布点同为带时区的时间戳，比较前统一成 UTC；同一文件有多个 A（删除后重建）取最早）。**首次提交晚于 0.4.0 发布点却写 `prd_schema: 1` ⇒ `prd_schema_too_low` FAIL**（含把旧 PRD 复制到新域：副本的 A 是新提交，不是旧文件的 A）。**0.4.0 起模板与 `init` 直接写 `2`（V-13/V-16）**，`1` 只作**存量缓冲**，且缓冲只给「首次提交早于 0.4.0 **且未被 crosswalk 引用**」的域——否则每个新仓从生成当天到 2027-06-30 每次 `check` 都会报一条 `evidence_deadline_approaching` WARN，把真实告警淹掉。**判据常量与武装（v18/重要 2；v19/重要 3 补可执行项）**：0.4.0 发布点写死为模块常量 **`PRD_SCHEMA_2_FROM`**；**武装条件含 prerelease**——`reader_version >= 0.4.0-0`（含 `0.4.0-beta.N`；不能写 `>= 0.4.0`，否则整个 beta 期不武装，判据悄悄缺席）且 `PRD_SCHEMA_2_FROM is None` ⇒ **`prd_schema_gate_unarmed` WARN**（exit 0、不计入 FAIL，明示「判据未武装」，**不得静默放行**）。**发版门落成可执行项**（v19/重要 3）：新增 `tests/test_release_gate.py`（或 `scripts/release_check.py`，两者择一，必须进 CI 门禁），判「`PRD_SCHEMA_2_FROM` 非 `None` 且等于**发布 tag 的 UTC 日期**（`YYYY-MM-DD`）」；不一致 ⇒ FAIL（tag 与常量不得漂移）。常量置值后的真实发版必须让该测通过，**不是文档承诺**。**`%aI` 的证明力（v18/次要 5）**：author date 可被 `--date` 伪造，**只作判据、不作证明**。
   - **执行点分两半、分属两个批次（v17/重要）**：
     - **成员侧 `validators/validate_prd.py`（B 批）**：判「本 PRD 自己声明的 `prd_schema` 与首次提交时间是否匹配」、「`prd_schema: 2` 是否两列齐全」、「`prd_schema: 1` 是否在 2027-06-30 前 / 07-01 起 FAIL」。这半边**不依赖 crosswalk**（成员不知道自己是否被引用），可以立刻做，归 **B 批**。
     - **父仓侧（D 批，crosswalk 所在批次）**：按 crosswalk 的 `成员PRD` 扫被引用成员 PRD、缺列 ⇒ `evidence_columns_missing`、缺 crosswalk ⇒ `evidence_columns_unbound`。这半边**依赖 crosswalk 落地**，归 **D 批**；**B 批清单里不得出现「父仓证据列已实现」**（否则 D 的依赖被掩盖，B 交付的只是一半）。
   - **crosswalk 落地版本起**（v18/重要 5：不是 0.4.0——0.4.0 没有 crosswalk 这个门），凡被 `requirements[].acs` 引用到的成员 PRD（crosswalk 的 `成员PRD`），必须有这两列；缺列 ⇒ 父仓 `check_solution` FAIL `evidence_columns_missing`。父仓读取路径 = `members[].path` + crosswalk 的 `成员PRD`（缺 crosswalk ⇒ 该项 `evidence_columns_unbound` FAIL）。
   - `prd_schema: 1` 的存量域 PRD（未被引用）：`2027-06-30`（含）前 **WARN** `evidence_deadline_approaching`（不是 N/A）；`2027-07-01` 起 FAIL。执行点 = 成员 `validate_prd` + 父仓扫描（决策 6，不接受纯文档承诺）。
   - 父仓对未被引用成员 PRD 的扫描：`members[].path` + 成员自己的 `<assets_root>/prd/*-prd.md`；成员缺席 ⇒ **默认 FAIL**（`--lenient` 仅无封条时可 SKIP；有封条时已被拒绝，Q-6）。
3. **成员侧口径**：成员 `atlas check` 不知道自己是否被父仓引用，因此：
   - 引用强制（crosswalk 落地版本）⇒ N/A，原因 `evidence_columns_parent_only`；
   - 硬期限（`2027-06-30` 含前 WARN、`2027-07-01` 起 FAIL）⇒ 照判，因为期限对所有 `prd_schema: 1` 存量域生效。
4. `verified` 无指针 ⇒ FAIL；`unverified` ⇒ WARN。
5. 字段契约仍是独立 §五-b 表，不是证据状态。`prd_schema: 2` 是使用新列的开关。**实况校正（v41）**：`templates/prd/domain.md` **已是 `prd_schema: 2`**，证据两列（`证据状态` / `证据指针`）已在该模板中（B 批已落地）；D 批只补 §五-b 契约表与父仓半边，**不再把 `prd_schema` 由 1 升 2**；旧稿「B 写 1、D 升 2」作废。
6. **严格态是判据（决策 2/决策 3）**：`solution check` 默认严格态；`--lenient` **仅在仓内存在封条时**拒绝执行（exit 2），只有锁、没有封条时（例如 fresh clone 拿到父仓跟踪的锁但成员工作区为空）允许执行。工具行为替代「CI 命令行扫描」这一不可移植的办法。
7. **§五-b 字段契约 AC 的最小 schema（v41，E-04 的可执行形态）**：
   - **表头**：表头行必须含 `契约AC`；找不到该表 ⇒ `contract_ac_table_missing` FAIL（`prd_schema: 2` 且该域被引用时）。
   - **列**（固定六列，顺序即下表）：`| 契约AC | 字段 | 类型 | 必填 | 异常码 | 关联AC |`。`必填` 取 `是/否`；`异常码` 逗号分隔、形如 `ERR-[A-Z0-9_]+`，无则写 `-`。
   - **AC 编号形态**：`AC-CONTRACT-<3 位数字>`（`^AC-CONTRACT-\d{3}$`），独立命名空间，不得复用 `AC-SOLUTION-*` 或成员 AC 编号。
   - **与 §五 AC 表的关系**：`关联AC` 必须回指同 PRD §五 AC 表里已存在的方案 AC（`AC-SOLUTION-*`）；§五-b 不另立验收项，只把字段级契约挂到验收项上。
   - **引用面（v42/阻断 4，选方案 (a)）**：`AC-CONTRACT-*` **纳入 `requirements[].acs` 的合法值域**（与 `AC-SOLUTION-*` 并列），因此卡门右集不变、卡内写契约 AC 不撞 K-15。允许出现在：① 被引用域的 `requirements[].acs`；② 任务卡 `atlas-acceptance:`；③ 封条 `card.projection.acceptance_acs`。**不得**出现在成员 AC 位置（`成员AC` / 成员 PRD 的 AC 表）⇒ `contract_ac_in_member_slot` FAIL。**排除清单（v43/阻断 3）**：`AC-CONTRACT-*` **不进** C-01（不要求 crosswalk 行）、C-04、`ac_missing`、方案 AC 定义校验；只由 §五-b 自身与 `contract_ac_*` 判。**crosswalk 的 `方案AC` 列值域只允许 `AC-SOLUTION-*`**，写 `AC-CONTRACT-*` ⇒ `crosswalk` 解析期 `ac_format`（D 批）。`shared/solution.md:48` 的值域说明随 D 批同步。
   - **E-04 判据**：上述三处引用 `AC-CONTRACT-*`，而 §五-b 表无该行 ⇒ `contract_ac_undefined` FAIL；§五-b 的 `关联AC` 不在 §五 ⇒ `contract_ac_orphan` FAIL。**执行点**：父仓 `check_solution`（D 批，与 `_support/ac_crosswalk.py` 同批；C 批不实现）。
8. **任务卡 Confirmed 口径的证据状态（v41，#53 原文要求）**：
   - **位置**：任务卡（`.trellis/tasks/<ID>/prd.md`，含 archive）里 `Confirmed` / `确认口径` 小节下的表；表头必须含 `确认项` 与 `证据状态`。
   - **字段与枚举**：`确认项 | 口径 | 证据状态 | 证据指针`；`证据状态 ∈ {verified, assumed, unverified}`；`证据指针` 形如 `系统@版本#定位`。
   - **判据（v44/重要 6 收窄）**：`verified` 无指针 ⇒ `confirmed_evidence_missing` FAIL；`assumed` 只要求 `证据指针` 指向默认值来源（缺失 ⇒ 同 `confirmed_evidence_missing`），**不要求** `confirmed_review:`；`unverified` 天然无证据，只由降级保护判（见下）；缺表或缺列 ⇒ `prd_schema: 2` 下 `confirmed_columns_missing` FAIL（`prd_schema: 1` 存量只 WARN 至 2027-06-30）。
   - **降级保护（v42/重要 4；v43/重要 5；v44/重要 6 收窄）**：成员 check **不读 Git 历史**。**只有 `unverified` 行必须带 `confirmed_review:`**（格式 `REVIEW-\d{8}-\d{2}`，与 §3.2 的 REVIEW-ID 同构），缺失 ⇒ `confirmed_downgrade_unreviewed` FAIL；**带 `confirmed_review:` 时不再报 `confirmed_unverified`**（互斥，避免双报）；`assumed` / `verified` 不要求。`assumed` = 有默认值来源；`unverified` = 无来源——机器差异是「是否必须带指针」，**不是**可以无理由重贴标签。
   - **执行点**：成员 `validate_task_card`（C 批，卡在成员仓库）；父仓只验封条 `card.projection`、不读正文，故父仓 N/A `confirmed_parent_only`。**不进封条**，与 Assumptions 的证据状态互不替代。

**为什么原方案不成立**：v2 两行都写「可选」；v3 的 E-02 没有执行点，父仓不跑，成员也不跑；v4 的 N/A 把未来新域也一起豁免了。v5 把执行点分到父仓（引用）与成员（期限），并按 `prd_schema` 分层。

**判据**：E-01…E-12。

### 1.6 多值接口：完整消费点（B10/I9）

**改了什么**

- `关联AC` 单元格支持单值或 `、` / `,` 分隔列表；第一个 token 为主 AC；不扩列、不拆行。
- **逐点改**（A 批 `d7c03e9` 已落地；行号按 `411c971`；「A 批前行为」留作回归判据）：

  | # | 消费点（`411c971`） | A 批前行为 | 改法 | 夹具 |
  |---|---|---|---|---|
  | 1 | `validate_e2e_index.py:828-830` | 整格 `AC_RE.match` | split 后逐 token 校验 | 多值全合法 PASS |
  | 2 | `:840-845` | 整格查 `defs` | 每个 token 都要在 `defs` | 第二 token 未定义 ⇒ FAIL |
  | 3 | `:845` | 整格查语料 | 每个 token 都要在语料 | 同上（非父仓） |
  | 4 | `:904` | `covered_ac = {g["关联AC"]}` | split 后取并集 | 两个 AC 都进覆盖 |
  | 5 | `:957` | `acid = g["关联AC"]` | 对每个 token 循环 | 维度分到两个 AC |
  | 6 | `:958` | 按整格写 `covered_ac_dims` | 按 token 写 | 同上 |
  | 7 | `:965` | `covered_ac_set` 整格 | split 并集 | 第二 AC 不再被漏 |
  | 8 | `:966-969` | `ac_pages` 整格键 | 按 token 建键 | 页面映射正确 |
  | 9 | `:1022` | 零证据用例整格查 `struct_acs` | 至少一个 token ∈ `struct_acs` | 行为 AC + 结构 AC ⇒ PASS；全行为 ⇒ FAIL |
  | 10 | `_support/solution_e2e.py:361-362` | `{整格} & defs` | split 并集 | `attached` 计数正确 |
  | 11 | `scripts/e2e_console.py:748` | `"ac": acs[0]` | 主 AC + 全量列表展示 | 页面不显示原始逗号串 |

- **关键回归**：v2 漏改时，`:965` 会把 `AC-1、AC-2` 当整体，两个 AC 都进不了 `covered_ac_set`，`:976-979` 的 `continue` 会**跳过而不是判红**。夹具 M-03 钉这个：第二 AC 是唯一未覆盖的 AC，必须 FAIL。
- `scripts/e2e_console.py` 的展示只影响人读，不参与门；但必须避免把原始逗号串当单值显示。
- 文档同步：`shared/solution.md:56`、`rings/e2e/reference.md:180`、`:612`、`templates/e2e/e2e-index.md:9`；`proposals/HANDOFF-20261109-01-solution-e2e-usage.md:245` 标注为历史 handoff，不改正文，避免第二真相源。

**为什么原方案不成立**：v2 只改 `_ac_coverage` 一处；`:976-979` 的跳过路径会让缺覆盖变成「没看见」。

**判据**：M-01…M-05。

## 2. 逐条闭环

### 2.1 #51 联邦模式成员 AC 与方案 AC 无映射对账

**现状证据**

- `requirements[].acs` 绑**方案 AC 与契约 AC**（`AC-SOLUTION-*` ∪ `AC-CONTRACT-*`，v43/阻断 3）：`shared/solution.md:48`（随 D 同步）；已知键无 `member_acs`：`_support/solution.py:239-240`。
- `check_solution` 只做定义 / 任务 / 指针：`_support/solution.py:1136-1160`。
- `atlas-apply.md` 七小节没有 AC 段：`apply/reference.md:264-270`。

**决策**：crosswalk 六列（§1.2），键 `(方案AC, 成员, 成员PRD, 成员AC)`。

**解析器归属（v41）**：

- **独立模块 `_support/ac_crosswalk.py`**，不塞进 `_support/solution.py`（后者已 2600+ 行）。
- **公开面两类入口**：
  1. 解析入口 `parse_crosswalk(text) -> CrosswalkTable`：**纯函数**，零 Git / 零文件系统；坏行 ⇒ `CrosswalkParseError(code, line)`。
  2. findings 入口 `crosswalk_findings(table, manifest, reader: MemberPrdReader) -> list[Finding]`：`reader` 提供 `paths(member) -> list[Path]`、`exists(path)`、`front_matter(path) -> {domain, prd_schema}`、`ac_ids(path) -> set[str]`，另有 `waivers: list[WaiverRow]`（来自 `ac-crosswalk-waivers.md`；文件缺失 ⇒ `[]`）——C-06/C-07 由它供数（v43/重要 6）。产 C-01…C-11 所需的 `(code, row)`，**不打印、不 exit**。
     - **四类失败形态归属（v42/阻断 3）**：① crosswalk 文件缺失 ⇒ 调用方（`check_solution`）在 parse 前判 `crosswalk_unresolvable`（C-01）；② 表头 / 列数 / AC 形态 / 路径形态 / 成员名错 ⇒ `parse_crosswalk` 抛 `CrosswalkParseError`，`code` 闭集 = `header_missing | column_count | ac_format | prd_path | member_field_empty`（**纯词法**；`member_unknown` 需 manifest，移出 parse，归 findings C-11）；③ **唯一键重复归 findings（C-05）**，parse 不抛（同一行为只一个归属）；④ 成员 PRD 缺失 / 多 PRD 无法定位 / 成员 AC 不存在 / `domain` 不符 ⇒ findings 用 `reader` 判（C-02 / C-03 / C-11）。
  - 路径 helper `resolve_crosswalk_path(root) -> Path` 供封条 upstream 的 `ac-crosswalk` role 用；**只解析路径，不解析内容**。
- **调用方**：父仓 `check_solution`（D 批，parse + findings）；`validate_ac_alignment`（D 批，findings）；封条 upstream 解析只调 `resolve_crosswalk_path`（C 批，见 §2.5）。**C 批不 import 本模块**。
- **批次**：D 批交付；文件表加 `_support/ac_crosswalk.py` 与 `tests/test_ac_crosswalk.py`。

**孤儿成员 AC（v41 裁定，C-03 边界）**：C-03 只判「crosswalk 显式行列出的成员 AC 是否存在于成员 PRD」，**未列进 crosswalk 的成员 AC 不判**。理由：成员 PRD 的 AC 集合是成员仓自有资产，父仓无法区分「应映射却漏了」与「成员内部 AC」；要判必须解析成员 PRD，依赖本模块（D 批）。因此 #51 的「双向对账」在 **crosswalk 检查族（D 批）**降级为**单向（仅显式映射对）**；D 批提供可选 `crosswalk_orphan_member_ac` **WARN**（默认不 FAIL），是否升为 FAIL 留在 §9。

**迁移（I11/I4）**：不整方案一刀切。

- `0.4.0` 起按需求判：某需求的方案 AC 无映射且无豁免 ⇒ 该需求 FAIL，不牵连其他需求。
- 豁免资产 `<assets_root>/prd/ac-crosswalk-waivers.md`：`| 需求 | owner | due | review |`；`due ≤ acceptance_cutover`，到期 FAIL。
- `waiver_baseline_digest` = 首次 v2 锁时**可豁免的需求 ID 集合**的 canonical 摘要（同一序列化器，JSON 字符串数组）；写入锁后**不可变**。
  - 后加需求无法豁免；已有需求可续期 owner/due（不改集合）。
  - 摘要变化 ⇒ `waiver_baseline_drift` FAIL。
- 新需求在 `0.4.0` 后必须直接有映射。

**判据**：C-01…C-11；任一成员滞后只红对应需求。

### 2.2 #52 需求卡空壳可通过资产更新并进入实现

按 §1.3：专用 `atlas-acceptance:` 行 + 投影绑定 + 父仓封条。两条根因（生成内容带 token、整卡摘要必输）分别由 B1/B2 处理；围栏块漏计由 I5 处理。

**判据**：K-01…K-22。

### 2.3 #53 确认口径缺证据状态且 AC 无法承载字段契约

按 §1.5：证据状态挂 Assumptions；**任务卡 Confirmed 口径的证据状态按 §1.5 第 8 条（C 批成员侧）**；字段契约走 §五-b 独立表（最小 schema 见 §1.5 第 7 条）；`prd_schema: 2` 开关；0.4.0 父仓强制被引用域，2027-06-30 含前 WARN、2027-07-01 起成员侧强制全部存量域（R7/I10）。

**判据**：E-01…E-12。

### 2.4 #54 验收资产缺失与用例先行失效

**现状证据（按 HEAD 重述）**

- 父仓无索引无分片：声明 `case_ids` ⇒ FAIL，否则 WARN（`validate_e2e_index.py:553-564`）；N/A 只剩非父仓（`:563`）。
- 仍成立：没有校验器扫 `.trellis/tasks/**/cases.md`。
- `not_ready` 是三个机制，不合并：
  1. 生成器 `NOT_READY`（退出码 3 + 机读键，`CHANGELOG.md:508`）；
  2. `_ac_coverage` 的 `state=not_ready` 不参与 verdict（契约声明 `_support/solution_e2e.py:344-346`，状态在 `:367` 计算）；
  3. `impact_report.py` 的 not_ready。

**决策**

1. **第二落点判据（重要 7，放宽到 issue 原意）**：`.trellis/tasks/**/cases.md`（含 `archive/<month>/` 与成员任务目录）只要出现**任一条用例行**即报 `task_dir_case_duplicate`，**不看 ID 前缀**是否 `E2E-*`：`BE-SYNC-*` / `HC-RECORD-*` / `TW-PUSH-*` 等跨网用例同属「用例先行」的第二落点。「用例行」的可判形态：表格行首列为大写前缀 ID（`[A-Z][A-Z0-9]*(-[A-Z0-9]+)+`），或行内出现 `atlas-case` 围栏标题。
   - **版本分级**：`0.3.x` ⇒ WARN；`0.4.0` 起 ⇒ FAIL。
   - **覆盖范围**：A 批现有实现只覆盖「合法 `E2E-*` 用例不得以任务目录为第二落点」（`validators/validate_e2e_index.py:104-113` 的 `_task_case_ids` 只取合法用例 ID，`:693-715` 只比索引主表），跨网 150+ 条 `BE-SYNC-*` / `HC-RECORD-*` / `TW-PUSH-*` 仍 0 命中；B-0 起放宽为任意用例行，并在扫描时把成员 `members[].path` 与 `tasks/archive/**` 一并纳入。
2. 封条 `e2e.status ∈ {ready, not_ready, n/a}`；`not_ready` / `n/a` 必须有 `gap {reason, owner, due}`；`ready` 必须有 `case_ids` 且每条在索引。
3. `gap.due` 必须是真实日期（**`YYYY-MM-DD`**，无时间部分），且落在闭区间 **[`exemption_start_origin`, `min(trunc_utc_date(first_seen_origin) + 90d, acceptance_cutover)`]** 内：**比较全在日期层（v25/I-2）**——`due` 一律 `YYYY-MM-DD`；**下界**取 `exemption_start_origin` 的 **UTC 日期部分**（该键的不可变豁免起点，已有值不改写、缺失时一次性回填；v22/I-6：不用 `exemption_started_at` 算下界——后者可被 `seal reanchor` 重指）；**上界**：先把 `first_seen_origin` 截到 **UTC 日期**得 `d`（`date` 类型），再 `min(d + timedelta(days=90), acceptance_cutover)`——**先截日期再加 90 天**，全程 `date`，禁止先本地化、禁止时间戳与日期直接比（v23/I-1：`first_seen_origin` 是锁内不可变键，取建键时封条载荷的 `first_seen_at`；v26/I-2：单源归一化）。两端都含。`1970-01-01`、越界、缺字段 ⇒ 拒绝签发。到期 FAIL（B6）。**读侧（v24/I-3；v25/I-2 日期层）**：已签封条的 `due` 不在上述闭区间内（**日期层比较**）、或 `exemption_start_origin > due` ⇒ **`exemption_due_out_of_range` FAIL**（写侧拒签之外，读侧另有本码；只写侧拒签不够）；**出口** = 续签一枚新封条把 `due` 写回区间内，恢复 PASS。**回填前缺 `first_seen_origin`（v24/次要 4；v25/次要 6）**：下界照判（`origin` 在即可），**只跳过 `first_seen_origin + 90d` 这一支上界**（无法算），**`acceptance_cutover` 上界不随之跳过**（`due > acceptance_cutover` 仍 FAIL `exemption_due_out_of_range`）；报告 `warnings[]` 记一条 `migration_required`（`detail.kind = "missing_first_seen_origin"`，提示跑 `lock --update`）；**回填只恢复 `+90d` 这一支**；`due > cutover` 须续签修正——**本码即续签出口**（T-32④；v26/S-6：删掉旧稿「回填后恢复完整上界、不得把旧锁判红」的自相矛盾说法）。**当前库内无已签封条，故升级即红的集合为空**。
4. **双真相闭合（B4 同族）**：清单 `requirements[].case_ids` 与封条 `e2e.cases[].id` 集合相等；封条存 `selector_sha256`；选择器变更 ⇒ `requirements_digest` 漂移 + 封条 stale。
5. **取数路径（I7）**：`e2e` 段内的 `status` 子字段（**草案提案字段，待 RFC 批准**；`shared/stack-profile.md §2` 尚未声明该列，本 RFC 批准后随封条 schema 一并补声明，不写成已声明字段）只由父仓写、父仓读；成员 `atlas check` 对该项 N/A，成员不读父仓 `case_ids`。父仓签名时从清单取选择器、从索引取用例行；成员侧不参与。
6. **孤儿封条（I9/重要 2）**：封条 `task.path` 在 `.trellis/tasks/<ID>/` 与 `.trellis/tasks/archive/<month>/<ID>/` 都不存在，且 `status != archived` ⇒ `orphan_seal` FAIL；归档后封条不动，校验时到 archive 目录找卡，不算孤儿。只能 `atlas apply archive --task` 或 `atlas apply seal --drop --task`（带 reason）。不自动 GC。

**判据**：T-01…T-14。

### 2.5 #55 资产更新记录与上游版本无绑定

**决策**：封条 `upstream[]` 固定 role → path 解析（I4），**全部在父仓可解析**（决策 2）：

| role | path 解析 | 必需 |
|---|---|---|
| `manifest` | `atlas.solution.yaml` | 是 |
| `prd-global` | `definition.path` | 是 |
| `prd-domain` | crosswalk 的 `成员PRD`（经 `members[].path` 定位） | **C 批：对应成员 PRD 文件存在 ⇒ 是；不存在 ⇒ 缺席、不拒签**；「有成员 AC 时是」的语义判断归 D |
| `ac-crosswalk` | `<assets_root>/prd/ac-crosswalk.md` | **C 批：文件存在 ⇒ 是；不存在 ⇒ 缺席、不拒签**；「有映射时是」归 D |
| `e2e-index` | `<assets_root>/e2e/e2e-index.md` | 有 `case_ids` 时是 |
| `e2e-case` | 每个被引用的 `cases/<file>.md` | 有 `case_ids` 时是 |
| `stack-profile` | `<assets_root>/stack-profile.yaml` | 存在即绑定 |

- `structure-facts` 不作为 upstream role：它在 `.trellis/spec/structure/`，未跟踪 `.trellis` 的仓无法被 Git 绑定。
- role → path 由同一个 helper 解析，供 `seal` 与 `validate_apply_record` 共用；不允许封条里写任意路径。
- `version` 可写不判；绑定字节。不绑 `atlas-apply.md`。
- **C 批边界（v41）**：`prd-domain` 与 `ac-crosswalk` 只做**文件存在性 + 字节绑定**，不做语义校验（不解析 crosswalk、不比对成员 AC）；文件不存在 ⇒ 该 role **缺席**，**不拒签**。
- **C 批成员 PRD 路径推导（v42/重要 1）**：`prd-domain` 用 `members[].path` + `<assets_root>/prd/*-prd.md` **glob 全绑**（只列路径、不读内容），**不需要 crosswalk 表**；`resolve_crosswalk_path` 只给 `ac-crosswalk` 文件路径，不产成员 PRD 列表。这是路径推导，不是解析，倒挂确实解除。
- **D 批首次 check 的追溯处理（v42/重要 2）**：`upstream[]` **只含已绑定 role**，缺席不落盘（不写 `absent` 项）。D 批上线后按清单推导期望 role（`prd-domain` / `ac-crosswalk`）与封条 `upstream[]` 比对：缺项 ⇒ `seal_upstream_unbound` **WARN**；至 **D 批首版 + 90d**（模块常量 `SEAL_UPSTREAM_BIND_FROM`，随 D 批写入 `_support/solution.py`，仿 `PRD_SCHEMA_2_FROM`；**不用 `acceptance_cutover`**，否则默认 `2027-03-31` 早于 D 上线时窗口已过期、上线当天全 FAIL）仍缺 ⇒ **FAIL**。**`state = frozen` 的封条只降级为永久 WARN**（v44/阻断 1，选方案 (c)）：不阻断、不随 `--strict` 升级；理由：frozen 不可改写，全文无 `unfreeze` 命令，续签重写字节会被 `seal_frozen_modified` 判红 ⇒ 不能要求补绑。**可见性**：每次 `check` 必进 `warnings[]`，摘要行打印 `seal_upstream_unbound(frozen=N)`，并按 §3.2 计入 `warnings[]` 排序；解冻入口不在本 RFC 新增（留给 C 批之后的实现反馈）。
- **常量发版门（v44/阻断 1）**：`SEAL_UPSTREAM_BIND_FROM` 必须等于 **D 批首个 tag 的 UTC 日期**（`git for-each-ref --format='%(creatordate:short)' refs/tags/<first-D-tag>`），由与 D-40 同构的夹具断言；写晚 ⇒ 窗口永不到期，判 FAIL。与上表「有成员 AC 时是 / 有映射时是」的关系：那两句是 **D 批**的语义判据；C 批退化为存在性，故 C 不依赖 `_support/ac_crosswalk.py`，倒挂解除。
- 成员 PRD 缺席：**签发时（C 批）** `prd-domain` 计为缺席、**不拒签**，封条照签；**D 批起**（crosswalk 落地后）若该成员有映射行而 PRD 缺席 ⇒ 拒绝签发。**校验时**成员工作区缺席 ⇒ `upstream_unresolvable` 默认 FAIL（与 §3.3 的 `member_workspace_absent` 同口径），不静默跳过、不当 PASS。

**判据**：U-01…U-08。

### 2.6 #59 定义源无法区分「路径错」与「另一份合法 PRD」

**#59 的保证（R2）**

机器能证明的只有三件事：

1. 定义源路径是显式的，且被约束在 `<assets_root>/prd/*-prd.md`；
2. 锁签发后，定义源字节变化会在每次 check 被复算出来（blob 摘要）；
3. 锁后补 AC 会让 `requirements_digest` 漂移。

**命令承载（重要 1）**：

- `lock --update` 必须打印 old→new：`definition.path`、`prd_version`、`prd_date`、`sha256[:8]`；路径或版本变化时多打印一行 `[REVIEW] <REVIEW-ID>`。
- `check` 每次输出一行：`定义源: <path> @v<prd_version> <prd_date> <sha8>`；该项是输出契约，不是调试日志。
- 关闭条件新增：**锁变更与 PRD diff 必须在同一个 PR**。只改锁不改 PRD、或只改 PRD 不改锁 ⇒ 评审必须打回。

**评审规则（v10/I-5 显式编号，§8 的残余风险按编号引用）**

1. 定义源变更（`definition.path` / `prd_version` / `prd_date` / `sha256`）必须在 diff 可见，`lock --update` 必须带 REVIEW-ID 并打印 old→new。
2. 评审对象是 PRD diff，不是 REVIEW-ID 字符串；REVIEW-ID 只校验格式与三处一致（§3.1）。
3. 路径变更（换文件）必须在 PR 描述里单独标记，不得混在内容更新里。
4. **锁与 PRD diff 必须在同一个 PR**（只改锁不改 PRD、或只改 PRD 不改锁 ⇒ 打回）。
5. **`seal_anchors` 的变更必须与封条中 `reanchor` 的变更同 PR**（v10/I-5；v11/重要 6 收窄；v12 按路径键）：只改某个路径的锚不改该路径封条的 `reanchor`、或新增/删除/改写 `reanchor` 而不动对应键，都视为不可评审的拆分变更，评审必须打回。**普通续签不受此限**：只改 `renewal_seq` / `previous_seal_*` / `signed_at` / 业务字段的 PR 本来就不动锁（`lock --update` 只在版本升级、迁移或显式刷新时跑），按 v10 字面会误打回每一次续签。`seal_anchors` 的每次推进在 diff 里自带 `anchor_review`；`anchor_review` 与 `reanchor.review` 不一致、或键集合与封条路径集合不等（`seal_anchor_path_unmapped` / `seal_anchor_path_orphaned`）同样打回。

机器**不能**证明「这份 PRD 就是正确的那份」：同 domain、同 `domain_code`、同 AC 编号、抬 `prd_version`、改路径并带 REVIEW-ID 的副本，可以让机器面全绿。**#59 的关闭条件因此不是「副本无法洗白」，而是**：

- 任一定义源变更（含同路径内容替换）在 Git diff 可见，且 `lock --update` 必须带评审、必须打印 old→new；
- 评审对象是 PRD diff，不是 REVIEW-ID 字符串；路径变更额外标记；
- 机器侧只负责「变更可见 + 不可静默替换」，合法性与内容正确性由人负责；
- `commit` 不可复算时登记为关闭条件中的残余风险，不作为「已闭合」证据（I3/R9 同口径）。

**状态扩展**

| 观测 | 状态 | 级别 |
|---|---|---|
| v2 清单无 `definition`（v1 清单在 0.4.0 加载期已硬拒） | `definition_unbound` | FAIL |
| 路径缺失 / 逃逸 / 不满足后缀约束 | `definition_source_missing` / `definition_path_unsupported` | FAIL |
| sha / 版本 / schema / domain_code 不符 | `definition_source_mismatch` | FAIL（不看宽限） |
| `commit == null`（仅 `init` 刚写完、首次 `lock --update` 之前） | `definition_commit_pending` | WARN（v10/I-3；**已过首次刷新的唯一标记见 §5.2 第 8 条**：锁文件**完整历史**里任一版本 `definition.commit != null` ⇒ 此时 `null` 判 `definition_commit_unverifiable` FAIL，v13/R12-2 全历史扫描；v18/阻断 3 删除 `acceptance_cutover != null` 这条并列标记——`init` 就写该字段，它不证明刷新） |
| `commit` 对象本地缺失 | `definition_commit_unverifiable` | 默认 FAIL；仅 `--allow-unverifiable-chain` WARN |
| `commit` 对象在但不是锁里的 blob | `definition_source_mismatch` | FAIL |
| `requirements_digest` 不符 | `manifest_drift` | FAIL（不看宽限） |
| 绑定一致但零定义 | `ac_source_unavailable` | FAIL |
| 绑定一致、摘要一致、`ac ∉ defs` | `ac_missing` | FAIL；`--allow-dangling-acs` 仅 `< 0.4.0` 注册，0.4.0 起不注册 |

**`--allow-dangling-acs` 的退役点（决策 4/P-4/重要 1）**：v5 文本写「0.4.0 删除」，但 `scripts/atlas_solution.py:123-125` 的 `_allow_dangling_acs_enabled` 谓词是 `semver_lt(version, "0.3.0")`——`0.3.0-beta.x` 才注册，`0.3.0` 正式版已移除，两边差了一个小版本，所以 0.3.x 实际并不存在这个开关。B-0 把谓词改为 `semver_lt(version, "0.4.0")`：`0.2.x` / `0.3.x` 注册，`0.4.0` 起不注册。

**只改谓词不够：6 处落点必须同批翻（重要 1/第六轮；v39 更正计数）**。以下位置仍写「0.3.0 移除 / 0.3.0 起不注册」，与谓词改动后的事实相反，B-0 必须一并改：

| # | 落点 | 现状措辞 | 改为 |
|---|---|---|---|
| 1 | `shared/solution.md:73` | 0.3.0 移除 | 0.4.0 移除 |
| 2 | `shared/solution.md:84` | 0.3.0 起不注册 | 0.4.0 起不注册 |
| 3 | `docs/guide/changelog.md:14` | 0.3.0 移除 | 在 `[Unreleased]` 下新增「`--allow-dangling-acs` 退役点改为 0.4.0」，不改历史条目 |
| 4 | `_support/solution.py:2229-2230`（运行期 WARN；v39 更正行号） | 提示「0.3.0 移除」 | 提示「0.4.0 移除」；这是运行期输出，不是帮助文本 |
| 5 | `tests/test_atlas_solution.py:972-978` | 断言 `_allow_dangling_acs_enabled("0.3.0") is False` | 翻为 `("0.3.0") is True` + `("0.4.0") is False`（V-11） |
| 6 | `duty-review/QUEUE.md:44`、`duty-review/bugs.md:62` | 0.3.0 移除 | **只新增 `[Unreleased]` 更正条**，不改旧条目（§10 例外） |

帮助文本同步改为「将于 0.4.0 移除」。夹具 V-11 钉「`0.3.0` 注册、`0.4.0` 不注册」。

**残余风险（I3/R9）**

- `commit` 对象本地缺失 ⇒ 默认严格态 FAIL，仅 `--allow-unverifiable-chain` 降 WARN；仍由 blob 摘要兜底，但「锁到底对应哪个提交」不可证明。CI 必须 `fetch-depth: 0`（§5.2）。
- 旧 `.atlas` + 新封条 ⇒ 看不见 = 无门（§8）。
- 同域副本洗白 ⇒ 只能靠人审 PRD diff（R2）。

**判据**：D-01…D-35。

## 3. 遗留阻断

### 3.1 legacy：集中白名单 + 受控新任务（B5/R3/决策 1）

**为什么原方案不成立**：v2 要求 `git cat-file -e <sha>:<task.path>/atlas-apply.md`；`/Users/sunwenzhe/Desktop/跨网传输` 的 `git ls-files .trellis = 0`，未跟踪路径不可能出现在任何历史 commit。v3 的「只允许首次 v2 锁时已存在」又会让 cutover 后新建、尚未 apply 的任务没有合法出口。v3 的 `frozen_at` 只写在白名单里、不在锁里，无法复算「有没有后移」（R3）。

**新决策**

- 资产（**联邦模式集中父仓一份**，成员不各持一份）：`<assets_root>/reviews/apply/legacy-allowlist.md`

  ```markdown
  > frozen_at: 2027-01-31

  | task_id | member | task_path | apply_sha256 | owner | due | review |
  |---|---|---|---|---|---|---|
  | 20261010-login | backend | .trellis/tasks/20261010-login | null | @alice | 2027-03-31 | REVIEW-20270110-01 |
  ```

- `apply_sha256` 允许 `null`：legacy 的适用前提正是「没有可绑定的 apply 记录」；唯一键是 `(task_id, member, task_path)`。若填了 sha，则必须与该路径的 `atlas-apply.md` 字节一致。

- `frozen_at ≤ acceptance_cutover`；`due ≤ acceptance_cutover`。
- 封条 `kind=legacy` 必须匹配 `(task_id, member, task_path)`；有 sha 时 `apply_sha256` 也必须一致。
- **允许新任务进入（决策 1）**，步骤固定：
  1. 父仓 `atlas apply seal --legacy --task <member>/<task-id> --review <REVIEW-ID> --owner <owner> --due <date>`；
  2. 工具向白名单追加一行，重算 `legacy_allowlist_sha256`；
  3. 必须 `lock --update --review <REVIEW-ID>`；锁写 `legacy_allowlist_sha256` 与 `allowlist_frozen_at`；
  4. 没有 REVIEW-ID 或锁未更新 ⇒ 拒绝签发。
- **`frozen_at` 可复算（R3）**：锁存 `allowlist_frozen_at`；之后白名单的 `frozen_at` 不得晚于锁值（后移 ⇒ FAIL）。首次写锁时 `allowlist_frozen_at = 白名单 frozen_at`。允许新任务进入后，该字段不再承担「冻结集合」，只承担「防改字段」：白名单的 `task_id` 行可增，`frozen_at` 行不可后移。
- **REVIEW-ID 信任边界**：只校验格式 `REVIEW-\d{8}-\d{2}` 与「锁 / 白名单 / 封条三处一致」；不校验真伪。门的目的是防误操作与让变更可见，不防有意伪造；有意伪造属于评审责任（U-03 同族）。
- 封条 `legacy` 字段：`{allowlist_sha256, frozen_at, owner, due, review}`；不再有 `since_commit`。

**判据**：S-01…S-12。

### 3.2 backfill：首次签发日与续签链可复算（B6/R9/P-2/决策 1；v13：键宇宙 + 三态状态机）

**为什么原方案不成立**：v3 的 `first_seen_at` 只是工具自己写的字段，没有链、没有旧封条哈希，validator 无法证明它没被重置；v4/v5 的「恰好一个 A、零个 D」只封住**删掉重建**，封不住**原地改写**——把 `renewal_seq` 改回 1、`previous_*` 置 null、`first_seen_at` 改成今天，一次 M 提交即可全部通过路径事件判据。因此必须把 `renewal_seq` 与**真实提交数**绑定，而不是与文件自述绑定。

**封条字段**

- 封条顶层：`renewal_seq`、`previous_seal_sha256`、`previous_seal_commit`、`signed_at`（所有 `kind` 共用），外加可选 `reanchor`；`backfill = {first_seen_at, due, owner}`。
- **`signed_at` 正式定义（Q-4/重要 6；v16/N-2 改口径）**：UTC ISO-8601 秒级时间戳，**由工具在签发时写入**；人不得手填，续签时必须由工具重新生成，沿用旧值 ⇒ `signed_at_invalid` FAIL。v16 起它**只是审计字段**：① **不参与 `gap.due` 的任何计算**（下界由锁键 `exemption_start_origin` 承担——v22/I-6 起是 origin，不是可重指的 `exemption_started_at`；见 §3.2 第 2/3 条）；② 不参与链复算、不参与任何宽限分层；③ 换路径不是重签，新封条必须**逐字节沿用**旧封条的 `signed_at`（v16/N-2）。v6 的 `signed_at < 0.4.0 发布点 ⇒ WARN` 整段删除：封条由 C 批引入，任何真实封条的 `signed_at` 都晚于 C 批上线，该分支永远不可达；`signed_at` 本身也无法复算，拿它做期限等于给一个自述值开门。
- **删除 `first_signed_commit`（P-2）**：它可由路径历史复算，写进封条只会制造第二个真相源。决策 1 的「重写 `first_signed_commit`」在 v7 落成「reanchor 记 `base_seq` / `base_n` / `from_a`」。
- `due ≤ min(trunc_utc_date(first_seen_origin) + 90d, acceptance_cutover)`（**v23/I-1**：上界改取锁内不可变键 `first_seen_origin`，不再取封条载荷里可被写侧自述的 `first_seen_at`；`first_seen_at` 只作审计；**v26/I-2**：先截 UTC 日期再加 90 天，全程 `date`，禁止先本地化）。
- `renewal_seq` 从 1 开始；首签 `previous_seal_sha256` / `previous_seal_commit` = `null`。
- **任何封条字节变化都算续签**：必须把 `renewal_seq` 写成**提交后的 `N`**（顺序续签时表现为 +1；merge / 并行补签可以跳级，只需单调且等于 `N`——I2），并按 canonical JSON（键升序、UTF-8、LF）写出；否则 `renewal_seq != N`。这条把「格式化提交」也纳入链，避免「改了内容但不加 seq」的灰区。
  - **口径（次要 3）**：`renewal_seq` 计的是**封条路径提交数**（`N`），不是续签动作数；真实续签次数 = `N - 1`。合并进来的提交、跳级补签都会让「seq 增量 > 动作数」，这是有意的——链绑定的是提交历史，不是工具调用日志。
  - 反例（实测）：冲突 merge 取一侧后 `L = [A, M1, M2]`，独立续签提交后 `N = 4`，续签必须写 `seq = 4`（从 2 跳级）；写成 3 会 `renewal_chain_broken`。

**封条路径历史（Q-1/Q-2/重要 3）**

设 `S = <seal_path>`：

```text
C0 = git rev-list --full-history --no-renames --reverse HEAD -- <S>
L  = [c for c in C0 if `git show --no-renames --format= --name-status <c> -- <S>` 非空]
N  = len(L)
A  = L 中状态字母含 A 的「提交数」
D  = L 中状态字母含 D 的「提交数」
```

- **命令必须带 `HEAD`**：`git rev-list --full-history --no-renames --reverse HEAD -- <S>`。漏 `HEAD` 实测 `exit 129`（把 `<S>` 当成 revision）。
- **`git show` 同加 `--no-renames`**：否则重命名检测会把该提交显示成 `R100`，既不含 `A` 也不含 `D`，事件计数会漏。
- **merge 过滤不看父 blob，只看该提交对 `S` 的 `name-status` 是否为空**：为空 ⇒ 从 `L` 剔除（该 merge 对封条 TREESAME，取任一父即可）。实测：主干未改封条、PR 分支把封条改到 `seq=2`，两父 blob 不同，但 `git show --format= --name-status <merge> -- <S>` 为空；`rev-list --full-history` 仍把 merge 放进 `C0`。按父 blob 判会把 merge 留在 `L` ⇒ `N=3` 而封条 `seq=2` ⇒ 误报 `renewal_chain_broken`。这正是最常见的 `--no-ff` 合并方式。
- **事件按提交数计，不按字母数**：`AA` / `MM` 是同一个提交的一次事件（S-19 的 add/add 断言按提交数，不按字母数）。
- **冲突解决型 merge 禁止手写新字节**：能进入 `L` 的 merge，其封条字节必然与**所有**父都不同（等于某父就会被上一条剔除）。判据：`git show --format= --name-status <merge> -- <S>` 非空，且 `git diff --quiet <p> <merge> -- <S>` 对每个父都失败 ⇒ `seal_merge_conflict` FAIL。可判的正确做法：
  1. 解决冲突时 `git checkout --ours|--theirs -- <S>`（**逐字节取一侧**），merge 随即从 `L` 消失；
  2. 另起**一次独立续签提交**，由工具写 `renewal_seq = 提交后的 N`、`previous_seal_commit = 提交前 L[-1]`（等价于提交后的 `L[-2]`）。**视角必须写清（I1）**：封条字节在提交**之前**写进文件，此时 `L` 相对 `HEAD` 算，还不包含这个续签提交，所以可取到的「上一枚封条」是提交前的 `L[-1]`，不是提交前的 `L[-2]`；按字面取提交前 `L[-2]` 会拿到上上枚，提交后 validator 的 `L[-2]` 与实际不符 ⇒ `renewal_chain_broken`。
  - 两侧分支各自续签会让 `seq` 同时为 2；取一侧后 `L` 仍含两个 `M`，`seq` 与 `N` 仍不等，必须靠第 2 步补齐。这是操作要求，工具不自动修复，也不允许在 merge 提交里直接写封条内容。

判序（顺序不可交换）：

**第 0 步先于 ⓪：仓库形态（重要 3；v14/I-3；v18/重要 4 移回 ⓪ 之前；v19/阻断 3 改为不可降级）**：`git rev-parse --is-shallow-repository` 为 `true` ⇒ 直接 `chain_unverifiable` **hard FAIL**，**不进 A/D 分支、不进 ⓪、不进第 1 步**。只按 `A == 0` 判会漏掉「删+重建整段落在浅边界之外」：此时只看到重建的那个 A，`A=1 / D=0 / seq=1 / blob@L[0]` 全过 ⇒ 假绿 PASS。partial clone 同样在此步按 promisor 探测判 `chain_unverifiable` hard FAIL。**必须先于 ⓪ 与第 1 步**：浅/partial 的 `git log` 只能看到被截断的历史，先算 `U` 会让 `U` 偏小；若再叠加窄开关，路径级断言就会跟着被降级——所以 **`seal_anchor_path_unmapped` 不参与 `--allow-unverifiable-chain` 降级**：仓形态不可信时，路径级断言不得因 `U` 偏小而放行，一律按 `chain_unverifiable` 处理（默认 FAIL）。**本步不在 `--allow-unverifiable-chain` 的降级清单里（v19/阻断 3；v20/阻断 2）**：该开关**只降「`definition.commit` 的对象缺失」**（第 9 步），不降仓形态、不降封条链锚——`lock --update` 与 `seal reanchor` 本来就拒绝浅仓，检查器没有理由在不可信历史上继续算 `UH`。理由：降级后 `UH` 偏小，`U` 也跟着偏小，`seal_anchor_path_orphaned` / `seal_anchor_path_unmapped` 都会被静默放行，等于把「改根缩小宇宙」从后门放回来。**降级判据是「作用点 + scope」白名单，不是 `cause`（v21/B-2）**：白名单**只有一条**——「校验点 == `definition.commit` **且** `scope == definition_source`」；两项同时成立才降 WARN，白名单之外**即使 `cause == object_missing` 也 FAIL**（`epoch_origin` / `previous_seal_commit` / `anchor_review` 都不在白名单里）。本步 `cause ∈ {shallow, partial}`，不在白名单；`git log` 失败的 `cause == history_unreadable` 也不在（v19/重要 5：历史读不到 ≠ 对象缺失）。**若将来要放宽，唯一形态是**「整段跳过 ⓪ 与第 1 步，路径级/根级断言全部 SKIP」——**不许降级后继续算**；本稿不实现该形态，只写死边界。**两态写死（v31/S-4）**：① **非 Git 目录**（`git rev-parse --is-shallow-repository` 本身返 128 / `--show-toplevel` 失败）⇒ 属**用法 / 环境错误**：`check` 不产出报告，`exit 2` 且 stdout 首行是**人类可读文本**（与 §3.2「用法错误」同口径），**不得**把它读成「非浅仓」继续跑；② **空仓**（`git init` 后有 `.git`、无任何提交）：`--is-shallow-repository` 返 `false` ⇒ 本步放行、继续到 ⓪；三探针（`git cat-file -e HEAD:path` = 128、`git ls-files --error-unmatch` = 1、`git log -- path` = 128）全空 ⇒ `lock_missing`（B-0 尚未产锁的正常态）；**空仓里 `git log` 的 128 按「无历史」处理，不得判 `chain_unverifiable`**——本步只对 `--is-shallow-repository` / promisor 判仓形态。

**前置断言（v15/D-1；v16/D-1 加锁历史判据；v17/B-1/I-4 加解析层；v18/重要 3 收紧短路；v19/重要 1 明确终止；v20/阻断 2 收窄降级作用域）**：五条，顺序不可交换，全部**不参与 `--allow-unverifiable-chain` 降级**（降级只覆盖 `definition.commit` 的对象缺失；根与封条链不可信时 `U` 本身不可信，任何降级都会把「改根缩小宇宙」放行）。**⓪ 任一项 FAIL ⇒ `check` 立即 `exit 1` 结束**，`errors[]` **只含该码**，不进第 1 步——第 1 步不许拿到未定义的 `UH`（v19/重要 1）。

- **⓪-0 `lock_unparsable`（v17/I-4；v18/阻断 2；v19/次要 1；v20/阻断 1；v21/I-2）**：当前锁存在但**解析层**失败——不是合法 JSON 对象、`type(schema_version) is int and not isinstance(schema_version, bool)` 为假或值 ∉ `{1,2}`、`members` / `contracts` **缺失**（当前锁必须齐备，v19/次要 1）或存在但不是 list-of-dict、`assets_root_history` 存在但不是非空数组、元素不是对象或 `.root` 不是非空字符串 / **首尾带空白**（v20/阻断 1）、`layout_assets_root` 存在但不是字符串、或任一 `.root` 被 `validate_value(..., lexical=True)` 拒绝（v22/B-1）⇒ FAIL。**本码吸收当前锁的全部结构性与词法性错误（v21/I-2；v22/B-1 把词法下沉到 `load_lock_strict(current=True)`）**：`load_lock_strict` 对每个 `.root` 调 `validate_value(..., lexical=True)`，失败即 `LockParseError` ⇒ 这里落 `lock_unparsable`；**不留给 ⓪-3 再判**。**⓪-3 只判**「`layout_assets_root == hist[-1].root` / `hist[-1]` 的严格版 FS / 元素重复 / `.root` 集合 ⊇ `UH`」四项；**`hist[:-1]` 的 lexical、`assets_root_history` 非空、元素首尾无空白都已在解析层（⓪-0）判定，⓪-3 里只做防御性复核、永不可能单独触发**（v23/次要 1）。**`lock_missing` 的「跳过」只对文件不存在成立**，不得把「读不出来」归成「没有锁」。**⓪-0 之前先判 `lock_tracked_but_deleted`（v30/S-2；v31/I-2 钉次序与浅仓）**：**本哨兵位于第 0 步之后、⓪-0 之前**（不得前移到第 0 步之前——浅 / partial 仓必须先被第 0 步硬拒）；锁文件不在工作树，但 Git 记录里曾有或仍有该路径——`git cat-file -e HEAD:atlas.solution.lock.json` 成功（HEAD 有、工作树被 `rm`）**或** `git ls-files --error-unmatch -- atlas.solution.lock.json` 成功（index 仍有）**或** `git log -m --full-history --format=%H HEAD -- atlas.solution.lock.json` 非空（已提交删除）⇒ **FAIL、exit 1、`errors[]` 只含该码、短路**，`message` 写明「已跟踪的锁被删除（篡改信号）」；**三者全空才是 `lock_missing`**（从未有锁，B-0 尚未产锁的正常态）——两码同码承载会让「正常无锁」与「删锁」不可区分，故拆开（`lock_missing` 行为不变：只跳过 ⓪-0 与 ⓪-3/⓪-4）。**`--depth 1` 的 fail-open（v31/I-2；v32/S-1 + I-3 改写）**：浅仓判断留在 `check` 入口（第 0 步执行一次 `git rev-parse --is-shallow-repository`），判定函数**不接受「第 0 步」这个概念**，只接收显式参数 `history_available: bool`；单测直接调用时传 `history_available=False` 即等价。语义：浅边界外的删除提交会让三探针**全空**、看起来像「从未有锁」；此时**不得静默落 `lock_missing`**——`history_available == False` ⇒ `chain_unverifiable` hard FAIL（**`detail.cause = "shallow"`**，v32/I-3 统一字段名），只有 `history_available == True` 才允许 `lock_missing`。**一红即短路（v18/重要 3；v19/重要 1；v20/重要 3；v21/次要 1）**：不再读锁历史、不计算 `UH`、不判 ⓪-1…⓪-4，`check` **立即 `exit 1` 结束**——`lock_unparsable` 是唯一首报，`errors[]` 只有这一条；**但 `--json` 结构必须完整**：`errors` 之外照常输出 `warnings` / `skipped`，未执行的判序段写进 `not_run[]`（固定名：`root_history_check` / `root_v1_check` / `root_changed_check` / `path_level` / `state_level` / `chain_level`），stdout 不得为空。
- **⓪-1 `lock_history_unparsable`（v17/B-1；v18/阻断 1/2；v19/阻断 1/3、重要 5）**：锁文件的每个历史版本都必须能被**同一个 `load_lock_strict(..., current=False)`** 解析；**只校验「存在则类型与结构正确」**，不要求当前字段（`definition` / `seal_anchors` / 两个根字段在历史版本里可以缺）。失败面：坏 JSON / `schema_version` 类型或取值不对（含 `1.0`、`True`）/ `members` 或 `contracts` 存在但不是 list-of-dict（**缺失 ⇒ 视为旧工具产物放行**，v20/次要 2）/ `assets_root_history` 为空数组 / 元素不是对象 / `.root` 不是非空字符串或首尾带空白 / `root` 被 `layout.validate_value(..., lexical=True)` 拒绝（**历史根零 FS**，v20/阻断 1）。任一版本失败 ⇒ FAIL（`check` 立即 `exit 1`，同 ⓪ 的终止口径）。**解析失败不是「无历史」**：不得跳过该版本继续算 `UH`。**读取层三段（v19/阻断 3；v21/B-2 删降级尾巴）**：① `git cat-file -t <c>` 失败 ⇒ **`chain_unverifiable`**（对象本地缺失；**⓪ 层任何 `object_missing` 都不受窄开关影响，一律 FAIL**——`<c>` 来自 `git log`，这支本不可达，保留只为读取层防御）；② `git cat-file -t <c>:atlas.solution.lock.json` 失败 ⇒ **该提交没有该路径，`continue`**；③ 两段都通过却 `git show` 失败 ⇒ **`lock_history_unparsable`**。本码只留给「对象在、字节坏」。**`lock_missing` 时本项空跑通过（v31/I-1 更正因果）**：`lock_missing` 的定义（见下条口径）是 HEAD / index 均无该路径、`git log -- path` 返空 ⇒ **必然没有任何锁历史**，本项无版本可解析、恒通过；v30 的「历史里有坏版本照样 `lock_history_unparsable`」在拆分后不可达，已删。**非 `lock_missing` 路径里 `git log` 本身失败** ⇒ `chain_unverifiable`（不是本码，v19/重要 5）。**与 `lock_history_empty` 互斥（v29/B-2）**：本项只在锁文件**存在**时可能产生 FAIL；**文件不存在 ⇒ `lock_missing`（从未跟踪，无历史 ⇒ 本项空跑通过）/ `lock_tracked_but_deleted`（已跟踪被删，已在 ⓪-0 之前短路），均不发 INFO `lock_history_empty`**；INFO 只在「文件存在 + `git log` 返空 + `versions == []`」时发，两者不得同时出现。**历史层跳过（v30/B-1(a)）**：本项的读取层②「`git cat-file -t <c>:path` 失败 ⇒ 该提交没有该路径，`continue`」**同样适用于 ⑦ 构造 `versions`**，两处必须同一实现。
- **⓪-2 `lock_v1_with_seals`（v16/I-1；v17/I-2 扩到历史）**：锁文件**任一版本**（含当前）`schema_version == 1` 且 `seal_anchors` 非空/非 `null` ⇒ FAIL（本工具不产出该形态）。v1 版本一律不贡献根（§1.1.3 第 2 条 ③）。
- **⓪-3 `assets_root_history_rewritten`（v16/D-1；v18/重要 3 独占 schema 判定；v19/阻断 1 换字符集源；v20/阻断 1 分两层；v21/B-1 改按索引）**：先按 §1.1.3 第 2 条 ① 算出 `UH`（严格解析、v1 不贡献根、**历史版本内所有根只做词法校验**）；再要求**当前锁**满足四项**定义性判据**——`layout_assets_root == assets_root_history[-1].root`、`hist[-1]` 的严格版 `validate_value(...)`（多判「存在但不是目录」「symlink 逃逸」；`LayoutError` ⇒ 非法）、元素 `.root` 互不相同、`.root` 集合 ⊇ `UH`；任一不满足 ⇒ FAIL。**`assets_root_history` 非空、元素首尾无空白、`hist[:-1]` 的 lexical 复核属于解析层（⓪-0 / ⓪-1）已判，本段只做防御性复核、不作为本码的触发条件**（v23/次要 1）。**必须按索引取末元素（`hist[-1]`），不得「按值匹配末元素」**——同一个根重复出现时值无法区分索引（`_root_by_index_ok`）。**理由（v21/B-1）**：数组 append-only，历史根永远留在当前数组里；若「每个根都严格」，历史根今天被删 / 换成仓外 symlink / 换成普通文件，就永久红且无出口（S-51 三变体）。**字符集判据单源（v19/阻断 1）**：就是 `validate_value`，不另写 `ROOT_RE`；`ROOT_RE` 只作新增根的写侧建议。**词法不在这里判（v22/B-1）**：每个 `.root` 的 `lexical=True` 已在 ⓪-0（当前） / ⓪-1（历史）的 `load_lock_strict` 内完成；本码的四项定义性判据见本条开头（`layout == hist[-1]`、`hist[-1]` 严格版 FS、元素重复、`.root` 集合 ⊇ `UH`），v23/次要 1 只把「数组非空 / 首尾空白 / `hist[:-1]` 的 lexical」明确降为防御性复核。**当前锁缺这两个字段而历史任一版本有** ⇒ 同码（覆盖「删锁 → 改根 → 重建锁」）。**v1 锁或当前缺字段且历史也没有** ⇒ 跳过 ⓪-3、打 `assets_root_history_absent` WARN（无历史可判）。**结构、词法错误已在 ⓪-0 短路（v21/I-2；v22/B-1）**，本码的定义性判据只有 ⓪-0 条目列出的四项；`hist[:-1]` 的 lexical、数组非空、空白只做防御性复核（v23/次要 1）。
- **⓪-4 `assets_root_changed`（v15）**：`atlas.config.yaml` 的 `layout.assets_root` 现值必须 `∈` **当前** `assets_root_history` 的 `.root` 集合，否则 FAIL。次序在 ⓪-3 之后：先证明锁没被改写，再证明 config 与锁一致。**缺键 ⇒ 按 `_support/layout.py` 默认值 `product`；config 文件缺失 ⇒ 直接 FAIL**（v17/次要 5）。

**`lock_missing` / `lock_tracked_but_deleted` 的口径（v18/次要 4；v30/S-2 拆分）**：`lock_missing` = 锁文件不存在**且从未跟踪**（HEAD / index 均无该路径、`git log -- path` 返空），只跳过 ⓪-0 与 ⓪-3/⓪-4 两条根断言。**「仍执行」不等于「历史里可能有坏版本」（v31/I-1）**：三探针全空 ⇒ 没有任何锁历史 ⇒ ⓪-1 无版本可解析、⓪-2 无 v1 版本可判，两项按判序执行但恒通过；v30 的「历史仍在 `git log` 里」与 `lock_missing` 的定义自相矛盾，已删。若文件不存在但 Git 记录里曾有该路径（HEAD / index 有，或 `git log -- path` 非空）⇒ **`lock_tracked_but_deleted` FAIL**（⓪-0 之前短路，见上条），不得归入「无锁」跳过。**`[]` 归属**：当前锁 ⇒ ⓪-0 `lock_unparsable`；历史版本 ⇒ ⓪-1 `lock_history_unparsable`；⓪-3 永远不会看到空数组。**`U` 的根取锁文件全历史并集 `UH`，既不取 config 现值、也不只取当前锁的数组**（§1.1.3 第 2 条）；因此即便 ⓪-3 被实现者写漏，`U` 也不会因当前锁被重写而缩小——两道独立防线。
1. **键宇宙与状态分派（v13/R12-1；v15/D-1 根取历史；v16/D-1 取锁全历史并集；v16/I-5 改路径级次序）**：形态可信后才按 §1.1.3 第 2 条算出仓级 `U`（**对锁文件全历史根并集 `UH` 里的每个根各算一次再并集**），并判路径级，次序固定为 `seal_path_unsupported`（键不匹配任何根谓词）→ `seal_anchor_path_unmapped`（`U` 有而键缺）→ `seal_anchor_path_orphaned`（键 ∖ `U` 非空）。再按每个键的 `state` 分派：`active` 用 `L` 跑下面的 2–6 与规则 0–10；`retired` 用 `L_pre`（剔除删除提交后的序列）跑 2–6 与规则 0–7；`frozen` 用 `L` 截到 `frozen_at` 的前缀跑 2–6 与规则 0–7。二者之后分别跑 §1.1.3 第 5 条的迁出判据 / 冻结判据。**`state` 与 HEAD 不符时先报 `seal_anchor_path_state_mismatch`，不再往下算链**（R12-6 优先级 ②）。
2. `L`（或 `L_pre`）为空 ⇒ `chain_unverifiable`（**先判空，再走 `L[-2]`，不得索引空列表**）。
3. `A == 0` ⇒ `chain_unverifiable`（首签对象本地缺失）。
4. `D > 0` ⇒ `seal_history_reset`（删掉再重建）。**只对 `state == active` 的键生效**；`retired` 的删除不计入 `L_pre`，改为「删除提交有且仅有一次且被 `moved_from` 覆盖」判据（§1.1.3 第 5 条）；`frozen` 的删除按 `seal_frozen_modified` 判。`D` 本身**不会因为 state 而消失**，只是归属不同。
5. `A >= 2 && D == 0` ⇒ `seal_history_ambiguous`（add/add，要求重签）。
6. `A == 1 && D == 0` 才进入下面规则；`L[0]`（或 `L_pre[0]`）必须是那个 A。

**符号表（v11/次要 5；v12/次要 8 限定作用域；v13/R12-5 拆词）**

> **作用域**：本节所有符号默认指**当前封条路径** `S`。多枚封条时 validator 对 `seal_anchors` 的**每个键**各跑一套 `L/N/A/D/R0`，不存在跨路径共用的 `N`；凡带 `[path]` 的写法显式限定该键。`epoch_origin[path]` 仍是「一个字段、三种来源」（初始纪元旧 A / reanchor 后的 `R0` / 换路径后的新 `L[0]`），但**它是「纪元起点」的记账，不是链的物理分段**——链的物理分段由 `L` 与 `L_pre` 决定。
>
> **v13 拆词（R12-5）**：**纪元起点** = 某路径链上一次 reanchor 之后的第一枚封条所在提交（初始为 `A`，reanchor 后为 `R0`），是**链的属性**；**锚记账时点** = 后置 `lock --update` 把 `epoch_origin[path]` 写成该纪元起点的那个独立提交，是**锁的属性**。两者在 reanchor 提交当刻不重合（`epoch_origin` 仍是旧 A），这正是 4a 依赖的时点差。

| 符号 | 定义 | 易混点 |
|---|---|---|
| `UH` | **根集**：锁文件**HEAD 可达**历史版本的根并集——`git log -m --full-history --format=%H HEAD -- atlas.solution.lock.json` 取每个版本（orphan / 已删分支 / reflog 里的版本**不进**，v19/次要 3），逐个用**同一严格解析器** `load_lock_strict(..., current=False)`（v17/B-1；v18/阻断 1/2）解析：先 `git cat-file -t <c>`（失败 ⇒ `chain_unverifiable`）、再 `git cat-file -t <c>:<lock>`（失败 ⇒ `continue`）；`schema_version == 2` 且有 `assets_root_history` ⇒ **逐元素显式校验**（`isinstance(dict)`、`.root` 非空 `str`、`layout.validate_value`）后取 `.root`；`schema_version == 2` 但无该字段 ⇒ 该版本不贡献根；**`schema_version == 1` 一律不贡献根**（v18/次要 1；v19/次要 2 改结构理由：v1 锁里没有该字段）；最后去重 | 与 `assets_root_history` 不同：后者是**当前锁**里的数组，可被整段重写；`UH` 从 git 历史取，删数组元素、删锁重建都删不掉旧根。**解析失败不得跳过**——v16 的 `jq` 参考实现正是 fail-open 的入口；`[]` / `{root:null}` / `[{}]` 全部抛 `LockHistoryUnparsable`，禁止集合推导。**例外**：`git log` 非零 ⇒ `chain_unverifiable`（不是 `lock_history_unparsable`），见 ⓪-1 |
| `U` | 仓级**键宇宙**：对每个 `R ∈ UH` 各跑一次 `git log -m --full-history --diff-filter=A --no-renames --format= --name-only HEAD -- ":(glob)$R/reviews/apply/*/*.seal.json"`，**取并集**后按行去重（`-m` 会让同一 merge 出多行）；每个根配两段谓词 `^<R>/reviews/apply/[^/]+/[^/]+\.seal\.json$`（v14/B-1/I-4；v15/D-1 改根来源；v16/D-1 改取 `UH`） | 与 `L` 不同：`U` 是「历史上出现过封条的所有路径」，`L` 是「某一条路径的事件序列」。**`U` 的根取 `UH`（锁文件全历史），既不取 `atlas.config.yaml` 现值、也不只取当前锁数组**，因此不因删键/删文件/改根/重写锁而缩小；`-m` 管 merge diff 可见性，`--full-history` 管防剪枝，两个都要；**`L` 不要 `-m`**（`L` 走 `git show`，`-m` 会把一个 merge 拆成多份、`N` 偏大） |
| `S` | 当前封条仓内路径（= `seal_anchors` 的某个键） | 换路径后是新 `S`，旧路径另有自己的 `L` 与锚键 |
| `C0` | `git rev-list --full-history --no-renames --reverse HEAD -- S` | 含没改封条的提交与 merge |
| `L` | `C0` 中 `git show --format= --name-status <c> -- S` 非空的提交，按时间正序 | 不保证 `seq` 单调；merge/并行补签可跳级；**含 D 提交** |
| `L_pre` | `L` 中删除提交**之前**的子序列：`idx = max{i \| L[i] 的 name-status 含 D}`、`L_pre = L[0:idx]`；`L` 里没有 `D` 时 `L_pre = L`（v14/N-1） | 逐提交判 `git show --format= --name-status --no-renames <c> -- <S>`；`retired`/`frozen` 用它复算迁出/冻结前的链；`D` 不计入 `L_pre` |
| `N` | `len(L)`（当前路径），**当前时刻**的路径事件数 | 与锁字段 `n` 不同生命周期：`n` 是 `lock --update` 时刻的 `N` 快照 |
| `n[path]` | `seal_anchors[path].n`，写入时**该路径**的 `N` 快照 | 无路径键的 `n` 一律指当前路径 |
| `seq` | 封条字段 `renewal_seq` 的简写 | 只在封条内部；公式里的 `N` 永远用当前路径的当前值 |
| `A` / `D` | 该路径 `L` 中封条文件的 add 提交数 / delete 提交数（按提交计，不按字母计） | `A>=2` 歧义；`D>0` 的归属见 §1.1.3 第 5 条（active ⇒ `seal_history_reset`，retired ⇒ 必须被 `moved_from` 覆盖，frozen ⇒ `seal_frozen_modified`） |
| `R0` | 该路径 `L` 中**唯一一枚**满足 `renewal_seq == reanchor.base_seq` 的提交 | 多枚或零枚 ⇒ `reanchor_record_mismatch`；**不要求 `seq` 沿 `L` 严格递增**（补签会跳级），所以必须全量扫描，不能「找到第一枚就停」 |
| `R` | 实际写下 `reanchor` 的那个提交（`HEAD == R0` 时的 HEAD） | amend 后 `R` 与 `R0` 会分叉，故禁止 amend |
| `R0_second[path]` | 该路径第二次 reanchor 写下的提交（第二个**纪元起点**） | 只在上一次 reanchor 后未跑后置 lock 时出现（§1.1.3 第 7 条）；v13 前写作 `R0'` |
| `state[path]` | `seal_anchors[path].state ∈ {active, retired, frozen}` | **唯一**状态字段；不是「提示标记」——每个取值都有 §1.1.3 第 5 条的判据，决定该键走全链还是走迁出/冻结判据 |
| `moved_to[path]` | `seal_anchors[path].moved_to`：`retired` 键指向的新路径 | 必须指向存在的键，且目标封条 `moved_from.path` 指回本路径 |
| `frozen_at[path]` | `seal_anchors[path].frozen_at`：`frozen` 键的冻结提交 | 必填；`git log <frozen_at>..HEAD -- <path>` 必须为空 |
| `epoch_origin[path]` | `seal_anchors[path].epoch_origin`：该路径当前**纪元起点**的记账 | 初始为 A；reanchor 后要等**锚记账时点**（后置 lock）才变 `R0`；换路径新增键时为该路径 `L[0]`。跨路径比较无意义 |

链规则（v12/阻断 1；v13/R12-1 改键宇宙与状态分派：先按 §1.1.3 第 2 条算 `U` 并判路径级，再按每个键的 `state` 分派——`active` 跑完整 0–10，`retired` 跑 `L_pre` 的 0–7 + 迁出判据，`frozen` 跑冻结判据 + `L_pre` 的 0–7；任一键失败即整体 FAIL，不存在「只校验最近刷新过的那一枚」，也不存在「删了键就不校验」）：


0. **先定「reanchor 提交」与「边界记录」**：`reanchor` 豁免只作用于**写入 `reanchor` 的那一个提交**。判据是**提交身份**，不是值等式：令 `R0` = 该路径 `L` 中**唯一一枚**满足 `seal.renewal_seq == reanchor.base_seq` 的提交（**全量扫描** `L`；`L` 不要求 `seq` 单调，不能取「第一枚」就停，v11/次要 1），「当前是 reanchor 提交」⇔ `HEAD == R0`。`HEAD ∈ L` 是必要条件；后置 `lock --update` 的独立提交、不改封条的 merge 都不在 `L`，`HEAD != R0`，必须跳过锚校验（若用 `renewal_seq == base_seq` 的值等式，post-lock 提交会被误判成 reanchor 提交，`from_a` 与已推进的 `epoch_origin` 不符 + `seal_anchor_stale` 双红，第九轮 B-1）。若 `L` 中**不存在** `seq == base_seq` 的提交、存在**多枚**、或 `R0` 的 `reanchor` 对象与当前**不是逐字节相同** ⇒ `reanchor_record_mismatch` FAIL（B-2：删除或改写边界记录都算）。但「是 reanchor 提交」不自动等于「合法」——还必须同时满足**载荷等价**（规则 2）与**锁内锚一致**（规则 4a）。此后所有续签即使仍带着 `reanchor` 字段，也一律按普通续签判规则 2 / 5 / 8，并额外做一次边界记录认证（第 4b 步）；**不得再比对 `from_a` / `base_seq` / `base_n` 与 `seal_anchors[S]`**（锚在 reanchor 后已推进，再比会把每一次合法续签都判成 `reanchor_anchor_mismatch`），但 4b 的 **`review` 外部锚**照常比对（v11/重要 1）。
1. 封条**无 `reanchor`** 时：`renewal_seq == N`。若 `seal_anchors` 里**存在键 `S`**、且 `epoch_origin[S] != L[0]`，当前封条**必须带 `reanchor`**，否则 `reanchor_record_missing` FAIL（B-2：合法 reanchor 后 `seq == N` 恒成立，删字段能抹掉「这段历史被重写过、有人 review 过」的记账）。首次签发（`seal_anchors` 为 `null`、无键 `S`、或 `epoch_origin == L[0]`）不受影响。一旦写过 `reanchor`，后续续签**必须原样保留该字段**并改用规则 4 的公式。**绕过已收窄（v11/次要 4；v12/阻断 1；v13/R12-1 修第 5 点）**：同提交删掉键 `S` ⇒ 路径级先判 `seal_anchor_path_unmapped`（`U` 有该路径而映射缺键）。**「连封条一起删」不再是「触发 `D>0` / `seal_history_reset`」**——v12 写这句是把残余当成已解决：键与文件同删时旧路径根本不在循环里，`D` 不会被计算。v13 的正确结论是：该路径**仍因 `U` 而有键**，于是按 §1.1.3 第 5 条分派——① 键仍写 `active` 而 HEAD 无文件 ⇒ `seal_anchor_path_state_mismatch`；② 标 `retired` 但旧删除没有被新封条的 `moved_from` 覆盖、或 `moved_to` 目标不存在 ⇒ `seal_path_history_lost`；③ 标 `frozen` 而文件没了 ⇒ `seal_frozen_modified`。**三种出口都必须红，且都不依赖「文件还在」**。同理：`D>0` 只在 `state == active` 的路径上判 `seal_history_reset`；`retired` 的删除必须且只能有一次并被覆盖；`frozen` 段内的任何提交（含删除）都是 `seal_frozen_modified`。**删掉整份锁文件且 HEAD 无锁**（`git rm` 已提交，或工作树 `rm` 而 HEAD 该路径本来不存在）⇒ `lock_tracked_but_deleted` FAIL（v30/S-2；从未跟踪时才是 `lock_missing`），**不得**回落到「无锚」态。**「删 → 重建」不报本码（v31/S-1）**：重建后 HEAD 有锁，哨兵前置「锁文件不在工作树」不成立，该形态由 ⓪-3 `assets_root_history_rewritten` 承载（只对 **v2 旧根历史**可达，见 S-48①）——因此本码**不能被读成「任何删除提交都报」**。剩下只能靠「锁与封条必须同 PR」评审兜底，属 §8 残余①。**「删后原样重建 ⇒ `Ok`」的规则正文（v33/次要 3）**：删除提交被 `build_lock_versions` 跳过（不产生空版本），重建锁的那次提交产出与删除前**逐字节相同**的一版 ⇒ `versions` 的最后两版相等，后版本仍是紧邻前一版本的前缀扩展 ⇒ `check_history_prefix` 返回 `Ok`；重建后 **HEAD 有锁** ⇒ `lock_tracked_but_deleted` 的前置（锁文件不在工作树）不成立、不触发；根历史不变 ⇒ ⓪-3 的 `UH` 与当前 `hist` 相等、`assets_root_history_rewritten` 不报。**只有重建内容变了**（改根 / 删键 / 改数组）才由 ⓪-3 或对应的数组类码报；纯函数夹具见 §6 B-0（`c1` 有锁 → `c2` 删除 → `c3` 原样重建）。
2. `renewal_seq > 1` 时：**普通续签**要求 `previous_seal_commit == L[-2]`（**紧邻**上一提交，不是任意祖先）。唯一例外是**边界封条**（`renewal_seq == reanchor.base_seq`；含其后的 post-lock 提交与不改封条的 merge，因为它们继承同一枚封条、没有重写），其 `previous_seal_commit` 必须等于 `reanchor.from_a`（本地不可达的旧 A），且**载荷等价（v9/B1；v10 五字段）**：除 `renewal_seq` / `previous_seal_commit` / `previous_seal_sha256` / `reanchor` / `signed_at` 五个字段外，当前封条其余字段（`kind`、`e2e`、`links`、`gap`、`owner`、`first_seen_at`、`previous_cases`…）必须与 `L[-2]` 的封条逐字节相等。其中 `previous_seal_sha256` 在边界上**必须为 `null`**（v10/次要 2：边界不表示前驱，`from_a` 不可达、其封条 sha 取不到；置 `null` 而不是沿用旧值，避免字段名被误读成 `sha(L[-2])`）。这一条把「reanchor 提交不得改任何业务字段」从签署纪律变成机器判据——否则伪造 reanchor 可以顺手换掉 `e2e.cases[]` / `gap` / `owner`。
3. `renewal_seq == 1` 时：当前封条 blob 必须等于 `blob@L[0]`，且 `previous_* = null`。**换路径首签（带 `moved_from`）是唯一例外（v14/I-2；v16/N-2 改豁免集）**：此时 `L[0]` 就是这枚新封条自己，`blob == blob@L[0]` 恒真、等于没判；必须改判**对旧路径的载荷等价**——拿新封条与旧路径的 `L_pre[-1]` 逐字段比，豁免集 `{renewal_seq, previous_seal_commit, previous_seal_sha256, moved_from, reanchor?}`（**`signed_at` 已移出**：换路径不是重签，必须逐字节沿用旧值），其余字段逐字节相等；不等而未同时给出非空 `reasons[]` + 完整 `previous_cases[]`（id → 旧 sha，覆盖所有改动用例）⇒ `seal_move_payload_mismatch` FAIL（T-26/S-42）。否则 `git mv` + 顺手换掉全部 `e2e.cases[]` 会全绿。
4. 封条**有 `reanchor`** 时（含 reanchor 提交之后的每次续签）：`renewal_seq == reanchor.base_seq + (N - reanchor.base_n) - 1`。
   - **前置（v10/I-2）**：`N >= 2` 且 `base_n >= 1`，否则 `reanchor_invalid` FAIL（squash 成单提交后写 `{base_seq: 2, base_n: 0}` 会让 `L[-2]` 越界；下方所有 `L[-2]` 取用前统一加 `len(L) >= 2` 守卫）。
   - **身份不是值等式（v10/B-1）**：reanchor 提交时 `N = base_n + 1`，代入得 `renewal_seq == base_seq`；之后每续签一次 `N` 与 `seq` 同步 +1。这只说明「只有一枚封条把 `seq` 写成 `base_seq`」，**不能说明 HEAD 就是写下这枚封条的那个提交**：post-lock 提交与不改封条的 merge 继承同一枚封条，`seq` 仍是 `base_seq`，但 HEAD 不在 `L`。因此「当前是 reanchor 提交」一律用 `HEAD == R0`（规则 0），不用 `renewal_seq == base_seq`。
   - **4a 外部锚（v9/B1；v10 修身份与顺序；v12 按路径键查表）**：**只在 `HEAD == R0` 时执行**。判定顺序固定为：形状 → `from_a` 本地可达（⇒ `reanchor_not_allowed`）→ `seal_anchors` 为 `null` 或无键 `S`（⇒ `reanchor_anchor_missing`）→ `seal_anchors[S].renewal_seq != L[-2] 封条的 renewal_seq` 或 `seal_anchors[S].n != N - 1`（⇒ `seal_anchor_stale`，**成立即抑制后续 mismatch**，v10/I-6）→ `from_a != epoch_origin[S]` 或 `base_seq != seal_anchors[S].renewal_seq + 1` 或 `base_n != seal_anchors[S].n`（⇒ `reanchor_anchor_mismatch`）。stale 是可恢复的操作错误（忘了先 `lock --update`），mismatch 才是疑似篡改，不能先报篡改码。无键时一律 `reanchor_anchor_missing` FAIL。**没有这个锚，第一次 reanchor 用一个随机不存在的 sha 与合法 reanchor 在本地不可区分**（两者都只满足「对象不存在」）。注意本步的 `L[-2]` 只在 `HEAD == R0` 语义下成立；`seal reanchor`/`lock --update` 的**预检**比较对象是 HEAD 封条（§3.2 运维段），两处不同。
   - **写锚与后置（v10/B-1）**：reanchor 前先在 HEAD 上 `lock --update`（刷新 `renewal_seq` / `n`；`epoch_origin` 默认保留，见 §1.1.3）。reanchor 提交合并后必须**在该提交上**再 `lock --update` 并**独立提交**，把 `epoch_origin` 推进到 `R0`、`anchor_review` 写成 `R0.reanchor.review`。**禁止 amend 到 R**：amend 后 HEAD 仍在 `L` 且仍满足 `seq == base_seq`，但 `epoch_origin` 已变成 amend 前的 R，`from_a` 与它不符、锚也 stale，当前字段集下无解（没有字段能表示「边界是 R'，而 reanchor 是对 R 签的」）。
   - **B1 修正（v8）**：v7 把「有 reanchor」写成永久豁免，规则 2 的 `previous_seal_commit == L[-2]` 与规则 8 的 `seal_missing_at_commit` 在 reanchor 之后**永不执行**；可构造通过路径：合法 reanchor 一次后，某提交把 `seq += 1` 并把 `previous_seal_commit` 指向更早但仍带封条、sha 对得上的提交（规则 4 因 `N` 与 `seq` 同步 +1 成立、规则 5 被跳过、规则 7 只比 `first_seen_at` 且保留原值、规则 8 被跳过、规则 10 sha 对得上）⇒ 假绿。v8 把豁免收窄到边界封条，见夹具 S-23。
   - **B1 再修正（v9）**：v8 只堵了「reanchor 之后再篡改 previous」，没堵「伪造一次 reanchor 本身」——任意续签写 `{base_seq: 当前 seq, base_n: N-1, from_a: 随机 sha}` 即可重开纪元并丢掉 `L[-2]` 链接。v9 用载荷等价 + 外部锚两层同时堵，夹具 S-24（改载荷）与 S-25（载荷不变但 `from_a` 随机）。
   - **B2 修正（v10）**：v9 仍留下两条「删/改记账」路径——① 合法 reanchor 后 `seq == N` 恒成立，下一次续签把 `reanchor` 整段删掉仍 PASS（看起来像从未重写过的普通链）；② 非边界续签把 `from_a` 换成随机 sha，第 10 步因 `HEAD != R0` 跳过、算术恒等式照样成立 ⇒ PASS。v10 用规则 1 的 `reanchor_record_missing` 与第 4b 步的 `reanchor_record_mismatch` 堵，夹具 S-27/S-28。
   - **`base_n` 的定义（Q-2）**：签发 reanchor 时刻**不含 reanchor 提交本身**的 `N`。签发后 `N' = base_n + 1`，代入得 `renewal_seq == base_seq`；之后每次续签 `N` 与 `seq` 同步 +1，恒等式保持。两种写法都会差一：沿用 v6 的 `seq == base_seq + N - base_n` 且 `base_n` 不含本提交 ⇒ 签发后得 `seq == seq + 1`，恒假；把 `base_n` 定义成「含本提交的 N」而仍用新公式 ⇒ 得 `seq == base_seq - 1`，也恒假。
   - 夹具 S-18 必须断言：reanchor 提交后**立刻**跑 `solution check` 为 PASS（此时该路径的锚仍是签发前 `lock --update` 写入的旧纪元值，`epoch_origin` = 旧 A、`renewal_seq` / `n` 与 `L[-2]` 同步；reanchor 提交本身的 `base_seq = 旧 seq + 1`、`base_n = n` 正好满足 4a）。**构造要求（v10）**：必须先在原仓产生真实 A 并 `lock --update` 记 `epoch_origin = A`，重写后在 fresh clone 确认 `git cat-file -e A` 失败，再 `seal reanchor --from-a A`；不得用一串从未存在过的 40-hex 冒充（那只能测到 `reanchor_not_allowed` 的反面）。断言之后再跑一次 `lock --update` 并**独立提交**，锚推进到该 reanchor 提交（S-26）；**不得把「立刻 PASS」误读成「不需要后置 lock」**。

**原地改写为什么会被抓住**：

- 把 `renewal_seq` 改回 1 ⇒ 与 `N`（>1）不等，链规则 1 失败；
- 保留 seq 但 `previous_*` 置 null ⇒ 链规则 2：**普通续签**要求 `previous_seal_commit == L[-2]`，唯一例外是边界封条（其值必须是 `reanchor.from_a`）；因此这条断言只在「从未 reanchor」或「当前封条是边界封条」时分别成立，reanchor 之后把 `previous_*` 置 null 同样 `renewal_chain_broken`（v8 收窄，B1）；
- 只改 `first_seen_at` ⇒ 旧封条（`L[-2]`）的 `first_seen_at` 必须等于当前值，不等即 `renewal_chain_broken`。

三条路留下的是 `M` 提交，靠链规则 1/2 与 `first_seen_at` 一致性抓；若删文件再重建，则额外触发 `D` 计数。**校验以 HEAD 的封条为准**：工作树封条脏（`git status --porcelain <seal>` 非空）⇒ `seal_worktree_dirty` FAIL，不参与链复算。

**边界（如实写，不造假绿）**

- **唯一不可检测的形态：squash 成单提交「且」把封条改回 `seq=1 / previous_*=null`（Q-3/I5 收窄）**。实测：此时 `A=1`、`D=0`、`N=1`、当前 blob == `blob@L[0]`，规则全过——链规则 3 拿当前 blob 与重写后的 `L[0]` 比，等于自己比自己。工具**无法**区分「合法压平」与「掩盖历史」；本 RFC 不宣称能检测，也不提供假红夹具。
- **rebase / filter-branch 是可检测的，只是不能直接继续（I5 收窄；v10/B-2 改错误码）**：只重写 SHA、封条字节不变（`D=0`）时，`previous_seal_commit` 仍指旧提交 SHA，而重写后的 `L[-2]` 是新 SHA。判序上第 4b 步先跑：锁里有锚（`epoch_origin` = 旧 A，`!= L[0]`）而封条无 `reanchor` ⇒ `reanchor_record_missing`；只有锁里还没有锚时，才落到第 5 步的 `renewal_chain_broken`。这正是 `seal reanchor` 的入口：必须显式承认重写并重锚才能恢复。**例外（v10/I-1）**：这只对第一个纪元成立；若只重写第二个纪元之后的局部历史，`epoch_origin`（= 该路径当前**纪元起点** `R0`）仍可达，`reanchor_not_allowed` 会拒绝，当前字段集无解（§8 死结）。
- **删+重建型 filter-branch 不能 reanchor（v9/重要 4）**：若重写把封条文件删掉再加回来（`D > 0`），A/D 判序在链规则之前就报 `seal_history_reset`；reanchor 只对「内容重写但封条路径保留」有效，修不了 `D>0`。这种仓只能以新首签重建封条（`renewal_seq=1`）并走评审，历史链从新首签重新开始——这是有意的：删+重建本身就是重置信号，不该被 reanchor 洗掉。
- **服务端防线（对上两种形态都适用）**：采纳仓契约要求主干**禁 force-push、开分支保护**（线性历史或 merge-only 二选一，按团队定），并保留审计副本；本工具只做路径历史复算 + reanchor 显式记账。
- **运维死结（必须写进操作路径）**：本机 squash 后旧 A 仍在对象库，`git cat-file -e <old_A>` 成功 ⇒ `reanchor_not_allowed`，即 reanchor 反而不能在「做过 squash 的机器」上跑。唯一可用路径是在**没拉过旧历史的 fresh clone** 上执行（旧对象确实不存在），再 push 回来。事故现场若只有本机仓库，reanchor 不可用，这是已知限制。**错误码就是 `reanchor_not_allowed`**（与真正的伪造同码）；操作者自查：先 `git cat-file -e <seal_anchors[S].epoch_origin>`，**可达即属本死结**，不是篡改。**修法（v10/I-1，未来项）**：把「**纪元起点**」与「**不可达旧原点**」拆成两个字段——例如 `epoch_origin` 永不变（记链头）、`anchor_at` 记录锚记账后的可信起点（每次 reanchor 用它做 `from_a`）；**不能简单让 `epoch_origin` 永不推进**，那会把「用锁里的旧原点手写 reanchor」的伪造路径原样放回来。
- **普通 `--no-ff` merge（PR 分支改封条、主干未改）**：merge 的 `name-status` 为空 ⇒ 剔除，`N` 只数首签 + PR 分支那次续签，与 `seq=2` 一致（S-21）。
- **并行续签（两个 PR 各自 +1）**：即使无冲突、merge 取一侧，两个 `M` 都留在 `L` ⇒ `N=3` 而封条 `seq=2` ⇒ `renewal_chain_broken`。操作要求：**封条续签串行化**，同一时刻只允许一个在途续签；后合并的分支要 rebase 后重新续签（`seq` 写成新的 `N`），或在主干统一续签。
- **冲突解决型 merge**：`MM` 且字节不等于任何父 ⇒ `seal_merge_conflict` FAIL；取一侧 + 独立续签提交 ⇒ PASS（S-22）。
- **add/add 在 merge 中解决**：两个独立 A、`D=0` ⇒ `seal_history_ambiguous`（要求重签），**不是** `seal_history_reset`；重签后仍必须满足链规则 1–3。
- **shallow**：`--is-shallow-repository` 为真即 `chain_unverifiable`，不得当首签（S-20）。

**validator 复算链（默认严格态）**

1. 先判 shallow（`git rev-parse --is-shallow-repository`）；为真 ⇒ `chain_unverifiable`，停在原地。
2. 再算 `L/N/A/D`；`L` 为空或 `A == 0` ⇒ `chain_unverifiable`。`len(L) < 2` 时，凡需要 `L[-2]` 的步骤（5/8/10）跳过；若封条带 `reanchor`，另判 `reanchor_invalid`（v10/I-2，squash 成单提交的伪造不再 `IndexError`）。
3. **冲突 merge 前置判定**：`L` 中任一 merge 的封条字节与所有父都不同（`git show` 非空且 `git diff --quiet` 对每个父都失败）⇒ `seal_merge_conflict` FAIL，先于下面所有链规则报出。
4. 封条有 `reanchor` 时先判前置：`N >= 2 && reanchor.base_n >= 1`，否则 `reanchor_invalid`（v10/I-2）。然后 `renewal_seq == N`（封条无 `reanchor`）或 `reanchor.base_seq + (N - reanchor.base_n) - 1`（封条有 `reanchor`，含其后所有续签）；否则 `renewal_chain_broken`。**本步必须先于第 4b 步、链规则 0 与第 5/8 步**（固定顺序 **4 → 4b → 0 → 5/8/9/10**）。注意本步的等式**不保证「当前是 reanchor 提交」**：它只保证 `seq == base_seq` 的封条只有一枚，post-lock/merge 提交会继承同一枚封条；身份由 `HEAD == R0`（规则 0）判。`reanchor` 本身未被伪造，由第 5 步载荷等价、第 4b 步边界记录认证、第 10 步外部锚负责。
4b. **边界记录认证（v10/B-2；v11 增唯一性与 review 外部锚；v12 按路径键）**：封条**无** `reanchor` 时，若存在键 `S` 且 `epoch_origin[S] != L[0]` ⇒ `reanchor_record_missing` FAIL（删字段抹掉重写记账；同提交删键会被键集合断言先判 `seal_anchor_path_unmapped`）。封条**有** `reanchor` 时，**全量扫描** `L` 定位满足 `seq == base_seq` 的提交：**0 枚或多枚**、或唯一那枚 `R0.reanchor` 与当前 `reanchor` 不逐字节相同 ⇒ `reanchor_record_mismatch` FAIL（v11/次要 1：`L` 不保证 `seq` 单调；多枚本身就是异常）。另做**只比 `review`、不比 `from_a`/`base_seq`/`base_n`** 的外部锚校验：存在键 `S`、`seal_anchors[S].anchor_review != null` 时，要求 `current.reanchor.review == anchor_review`，否则 `reanchor_record_mismatch`（v11/重要 1：堵「多纪元回滚」——封条被回滚成第一纪元的合法记录时，`R0` 逐字节相同、第 10 步又因 `HEAD != R0` 跳过，只有 review 锚对不上；post-lock 与普通续签原样保留 review，不会误报）。这一步必须在第 5 步之前跑（S-28），且**对每个键的路径各跑一遍**（S-33：换路径后旧路径仍受约束）。
5. `renewal_seq > 1` 且 `len(L) >= 2` ⇒ `previous_seal_commit == L[-2]`，且 `sha256(该提交的封条字节, CRLF→LF) == previous_seal_sha256`。**唯一例外是边界封条**（`renewal_seq == reanchor.base_seq`；post-lock 提交与不改封条的 merge 继承同一枚封条，也适用本例外，v10/B-1），此时：① `previous_seal_commit == reanchor.from_a`（旧 A，本地不可达）；② **载荷等价**——除 `renewal_seq` / `previous_seal_commit` / `previous_seal_sha256` / `reanchor` / `signed_at` 外，其余字段必须与 `L[-2]` 的封条逐字节相等，且 `previous_seal_sha256` 必须为 `null`（v10/次要 2）。①不满足 ⇒ `renewal_chain_broken`；②不满足 ⇒ `reanchor_payload_mismatch` FAIL（v9/B1，S-24）。
6. `renewal_seq == 1` ⇒ 当前 blob == `blob@L[0]`，`previous_*` 为 null。**带 `moved_from` 的换路径首签例外**：`L[0]` 就是自己，改判与旧路径 `L_pre[-1]` 的载荷等价（豁免集同链规则 3），不等且无 `reasons[]` / `previous_cases[]` ⇒ `seal_move_payload_mismatch`（v14/I-2）。
7. 旧封条可读时，`first_seen_at` 必须与当前一致；否则 `renewal_chain_broken`。（**不再要求 `seq` 比旧值恰好大 1**：并行续签合并后的补签会一次跨多级，`seq == N` 与 `previous_seal_commit == L[-2]` 已足够保证单调。）
8. `previous_seal_commit` 指向的提交存在但该路径下无封条 ⇒ `seal_missing_at_commit` FAIL。**跳过条件只剩一条**：`renewal_seq == reanchor.base_seq` **且** `previous_seal_commit == reanchor.from_a`（当前封条是边界封条，其前驱是不可达旧 A；post-lock 提交与不改封条的 merge 继承同一枚封条，同样跳过，v10/B-1）。reanchor 之后的续签，`previous_seal_commit` 必须指回上一枚封条且该提交有封条，**不再跳过**（B1）。
9. 对象本地不存在 ⇒ `chain_unverifiable`：**默认严格态 FAIL**；仅窄开关 `--allow-unverifiable-chain` 降 WARN。**作用域收窄（v20/阻断 2）**：该开关的 `object_missing` **只对 `definition.commit` 生效**（上游 PRD 提交被 force-push 属合法场景），降级时记 `downgrades[]`、`scope: definition_source`。**封条链的锚一律不降**：`epoch_origin` / `previous_seal_commit` / `anchor_review` 指向的对象缺失 ⇒ **FAIL，开关无效**——那是封条链的锚，缺失等于链不可证，不接受自述降级。`<c>` 来自 `git log`、对象必然在本地，所以「锁历史里的 `<c>` 对象缺失」本就是死分支；真正可达的是**文件里写的 SHA**（上面三类），它们一律不享受降级。**第 0 步的仓形态（shallow / partial）也不在降级清单**（v19/阻断 3）；⓪-0 / ⓪-1 的 `lock_unparsable` / `lock_history_unparsable` 同样不降。（**例外**：`from_a` 本就必须不可达，不计入本步，由第 4b 步边界记录认证与第 10 步外部锚兜底——伪造者写随机 sha 会在第 4b/10 步被 `reanchor_record_mismatch` / `reanchor_anchor_mismatch` 抓住。）降级时必须打固定一行 `[WARN] definition_commit_unverifiable 已降级（--allow-unverifiable-chain）`，并按下方报告 schema 写入 `downgrades[]`（`scope: definition_source`）；CI 禁用该开关，与 `--allow-card-absent` 同规则（重要 4）。该开关只管「定义源 commit」一项，不复用 `--lenient`。
10. **`reanchor` 字段与外部锚（v9/B1；v10 修身份/顺序/字段）**：
    - 形状：`{base_seq, base_n, from_a, review}`；`review` 必须是 `REVIEW-\d{8}-\d{2}`。
    - 自洽（与旧封条比较的部分**只在 `HEAD == R0` 时执行**）：`from_a` 必须本地不可达（`git cat-file -e <from_a>` 失败），否则 `reanchor_not_allowed`。**「本身不可达」只在完整仓里有意义**：浅克隆 / partial clone（promisor）里 `cat-file -e` 对任何剪掉的提交都失败，不能据此放行（v11/阻断 2）。validator 在判序第 0 步已整体拒绝浅克隆（v14/I-3 前移到 `U` 之前）；`seal reanchor` 与 `lock --update` 的预检也必须自行判一次（§3.2 运维段 + S-29）。`HEAD == R0` 时，`base_seq - 1` 必须等于 `L[-2]` 封条的 `renewal_seq`，并用旧封条交叉核对 `base_n`（此时 `N - 1 == base_n`）。post-lock 提交与不改封条的 merge 继承边界封条，但 `HEAD != R0`，不重做这两条；普通续签也不重做（`L[-2]` 已变成上一枚续签封条，再比必然不等），只由第 4 步算术恒等式约束。
    - **判定顺序（v10/I-6；v11 加路径；v12 改查表；v13 加状态门）**：**前提 `state[S] == active`**（`retired` / `frozen` 的键不进入 4a，按 §1.1.3 第 5 条各自判据，禁止再拿它的 `renewal_seq`/`n` 做锚比较）；`from_a` 可达 ⇒ `reanchor_not_allowed`；`seal_anchors` 为 `null` 或无键 `S` ⇒ `reanchor_anchor_missing`；`seal_anchors[S].renewal_seq != L[-2] 封条的 renewal_seq` 或 `seal_anchors[S].n != N - 1` ⇒ `seal_anchor_stale`（**成立即停，抑制 mismatch**；`L[-2]` 只在 `HEAD == R0` 时才是 reanchor 的前驱，与预检「按 HEAD」不矛盾——两处的比较对象不同）；`from_a != epoch_origin[S]` 或 `base_seq != seal_anchors[S].renewal_seq + 1` 或 `base_n != seal_anchors[S].n` ⇒ `reanchor_anchor_mismatch`（S-25）；`seal_anchors[S].anchor_review` 非 null 时必须等于 `reanchor.review`，否则 `reanchor_anchor_mismatch`。
    - **执行条件**：以上锚校验**只在 `HEAD == R0` 时执行**（提交身份，不是 `renewal_seq == base_seq`）。post-lock 的独立提交、不改封条的 merge 不在 `L` ⇒ `HEAD != R0` ⇒ 整段跳过（B-1：否则 post-lock 提交会因 `from_a` 与已推进的 `epoch_origin` 不符而红）。**`HEAD ∈ L` 且同时改锁与封条也是合法的**（v11/次要 6）：只要封条改动把 `seq` 升到 `base_seq + 1`（一次普通续签），`HEAD != R0`，本步跳过、规则 4 的公式成立；若封条改了却不升 `seq`，规则 4 直接 `renewal_chain_broken`。写锚规则（§1.1.3 第 4 条）的「任意 HEAD 可跑」已覆盖这一形态。
    - 后置：reanchor 提交合并后必须在该提交上再 `lock --update` 并**独立提交**，把该路径的键推进为 `{epoch_origin: R0, renewal_seq: base_seq, n: N, anchor_review: reanchor.review, state: active}`；**禁止 amend 到 R**（B-1）。
    - `previous_seal_sha256`：边界封条上**必须为 `null`**，纳入载荷等价排除集（v10/次要 2）；reanchor 之后的普通续签恢复「`sha256(L[-2] 封条) == previous_seal_sha256`」。

**机读报告 schema（I4；`solution check --json` 是唯一产出点）**

现状：`scripts/atlas_solution.py:247` 只把内部结构原样 `json.dumps(data)`，没有稳定键名；§3.2 第 9 步与 §3.3 反复要求写 `downgrades[]`，不定义就无法断言「降级可见」。

- **顶层键（固定集合，不得多键）**：`schema_version`（整数 **`2`**；v29/次要 2）、`ok`（bool）、`reader_version`（string）、`definition_source`（对象：`domain` / `path` / `prd_version` / `sha256` / `commit`；无定义源时 `null`）、`errors[]`、`warnings[]`、**`info[]`（v28/I-2 新增，缺省 `[]`，结构性提示，不计 FAIL、不影响 exit code）**、`skipped[]`、`downgrades[]`、`not_run[]`（v20/重要 3：短路时也必须存在，未执行的段写名字进去，例如 `["path_level", "state_level", "chain_level"]`）。
- **实现状态（v36/次要 3）**：以上 v2 形状是**规则层**；当前 `check --json` 出口**尚未落地**——顶层只有 `checks / e2e / errors / mode / overall / solution`，没有 `schema_version` / `warnings[]` / `info[]` / `not_run[]`。落地前：① T-32 的端点断言**只用 `checks[]`**（`check == "验收切点"`），不依赖上述键；② 任何报告级断言都按「规则层 v2 已定、出口待补」表述，不得写成今天已生效。
- **落地判据与交付批次（v37/重要 2）**：**判据** = `check --json` 顶层出现 `schema_version: 2`，且 **五数组** = `errors[]` / `warnings[]` / `info[]` / `skipped[]` / `downgrades[]` 齐全（`not_run[]` **单列、不在这五个里**），排序键为 `(code, path)`；`downgrades[]` 按 `(code, scope, path)`；`not_run[]` 是固定枚举字符串（`root_history_check` / `root_v1_check` / `root_changed_check` / `path_level` / `state_level` / `chain_level`），**不参与排序**；**交付批次 = B-0**（v37 定，不再推迟到 B 批）。**落地前任何夹具不得引用这些键**（T-32 只用 `checks[]`）。
- **报告 schema 版本（v29/次要 2）**：本版 `schema_version = 2`。v1 → v2 的**增量键**只有四类：① 新增顶层 **`info[]`**（v28/I-2）；② `errors[]` / `warnings[]` 项可带**可选对象** `detail`（v26/I-3）；③ **`skipped[]` / `not_run[]` 的存在性要求**（v20/重要 3：短路时也不得缺键，未执行段按固定枚举写入）；④ `downgrades[]` 项的人类可读字段由 `detail` 改名 **`note`**（v26/I-3）。**兜底**：消费方**必须忽略未知顶层键与未知数组项字段**，不得因多键 / 多项报错（前向兼容）；只有 `schema_version` 高于自身支持上限时才允许拒绝解析。
- **`errors[]` / `warnings[]` 项**：`{code, message, path, detail?}`；`code` 用本文档的小写错误码（如 `renewal_chain_broken`、`seal_missing_at_commit`、`manifest_drift`、`review_reused`、`signed_at_not_canonical`、`exemption_start_signed_at_not_canonical`、`exemption_start_conflict`、`exemption_start_history_broken`、`exemption_start_origin_rewritten`、`first_seen_origin_rewritten`、`exemption_due_out_of_range`、`internal_error`；**全量登记见 §5.2 第 13 条码表**），`path` 是仓内相对路径或 `null`。
- **`info[]` 项（v28/I-2）**：`{code, message, path}`，与 `errors[]` 同形但**只承载结构性提示**；本版唯一登记项是 **`lock_history_empty`**（`ok` 可为 `true`、exit code 不变）。消费方不得把 `info[]` 计入 FAIL 面。`errors[]` / `warnings[]` 项可带 `detail`（**对象，不是字符串**；缺省即不出现，消费方不得假设恒存在）。本版需要它的码与形状固定如下：`first_seen_origin_rewritten.detail = {kind: "rewritten" | "after_signed_at" | "not_canonical"}`；`exemption_start_conflict.detail = {kind: "not_equal_signed_at" | "moved_from_chain_mismatch" | "chain_head_missing"}`（与 §7 T-28(c) 同集合，不得只写 `"conflict"`）；`migration_required.detail = {kind: "legacy_member_name" | "missing_acceptance_cutover" | "missing_first_seen_origin"}`；**`chain_unverifiable.detail = {cause: "shallow" | "partial" | "history_unreadable"}`（v32/I-3：字段名固定为 `cause`、不是 `kind`；三值分别对应第 0 步的两种仓形态与 ⓪-1 的读取层失败，与 §3.2 第 0 步 / ⓪-1 同集合）**。其余码可省略 `detail`。**同一码只允许一个 `detail` 字段名**：上列前三个用 `kind`，`chain_unverifiable` 用 `cause`；不得出现「同码两套字段名」（这是 v32/I-3 修掉的冲突）。
- **`downgrades[]` 项**：`{code, flag, scope, path, note}`（v9/重要 1：补 `path`，否则下面的排序键不存在；v26/I-3：原 `detail` 改名 `note`）：
  - `code`：被降级的错误码。本版合法取值逐个列名为 **`definition_commit_unverifiable`**、**`card_absent`**、**`reader_version`**（v12/重要 5：§5.3 的中间级不可解析要记一条，schema 必须能承载；**`chain_unverifiable` 已移出**——`<c>` 来自 `git log` 所以那支不可达，封条链锚又不可降，保留它只会让「链缺失被降级」有字面依据）。**白名单的「校验点」不是独立字段（v22/次要 1）**：唯一被允许的校验点「校验点 == `definition.commit`」**映射成 `code` 值**——`code == definition_commit_unverifiable` **且** `scope == definition_source` 同时成立，才表示「被降的是定义源 commit」；外部审计靠这两个值反推校验点，不得另立 `check_point` 键（报告顶层是固定集合，不得多键）；
  - `flag`：触发降级的开关/条件字面量（`--allow-unverifiable-chain` / `--allow-card-absent`；`reader_version` 无开关，写 `null`）；
  - `scope ∈ {definition_source, card_absent, reader_version}`（**三值，v22/次要 2**）：`definition_commit_unverifiable → definition_source`、`card_absent → card_absent`、`reader_version → reader_version`；**`chain` 不再是合法取值**（v20/阻断 2：封条链的对象缺失不可降级，§3.2 第 9 步）；三个取值是本版全部合法枚举，验收口径只说「三值」，**不得写成「只剩一个值」**；
  - `path`：`definition_source` 给定义源路径（`definition.commit` 缺失时就是 `<assets_root>/prd/*-prd.md`）、`card_absent` 给任务卡路径、`reader_version` 给被跳过的版本来源文件路径（如 `.atlas/VERSION`）；不适用的场景为 `null`；
  - `note`：一行人类可读说明，必须与 stdout 的固定 WARN 行同义（v26/I-3：原字段名 `detail` 改为 `note`，**把 `detail` 让给对象**；`downgrades[]` 是未发布的新结构，改名无兼容成本，**不保留 `detail` 别名**）。
- **唯一产出点**：`solution check --json`。`atlas check`（成员侧）、`solution task acceptance`、E2E 生成器都不产出该报告。
- **exit 2 的双语义（v23/次要 3，消费方按首字符区分）**：exit 2 有两种成因——(a) **用法错误**（参数互斥、`--lenient` 在「有封条」时被拒、`--cutover` 晚于默认且缺 `--anchor-review` 或超上限）：**stdout 首行是人类可读文本，不是 JSON**；(b) **`internal_error`**：`--json` 时仍输出一份合法 JSON（`ok: false`、`errors[]` 含 `code: internal_error`）。消费方**必须按 stdout 首字符区分**：首字符为 `{` ⇒ 按 JSON 解析（可能是 exit 1 或 exit 2 的报告）；否则按人类可读文本处理。不得只看 exit code 决定是否 parse JSON，也不得在首字符不是 `{` 时尝试 `json.loads`。
- **异常处理顺序（v19/重要 2；v20/重要 3 补完整性；v21/B-3 补未知异常；v22/I-4 分层，写死）**：`check` 的最外层按下面固定顺序，**不许把前两层并进 `internal_error`**：
  1. **用法错误在最外层 `try` 之外**：参数互斥、`--lenient` 在「有封条」时被拒、`--cutover` 晚于默认且缺 `--anchor-review` / 超上限等，一律在进入检查逻辑**之前**判定，`exit 2`，**首行是人类可读文本、不是 JSON**（与「`--lenient` 的 exit 2 首行不是 JSON」一致）。这一层不得被下面的 `except Exception` 看见。
  2. `SolutionError` **先于通用 `except` 捕获并原样上抛**：`except SolutionError: raise` 必须排在 `except Exception` **之前**（`scripts/atlas_solution.py:443-445` 已把它统一 `return 2`，message 是既有的人类可读文案）。**不得**转成 `internal_error`、不得包成 JSON、不得改文案；迁移期 `atlas solution migrate` 的半写失败也走这一层。
  3. `except (LockParseError, LockHistoryUnparsable, ChainUnverifiable)`：按 `{code, message, path}` 写进 `errors[]`（`LockParseError` 落 `lock_unparsable`、`LockHistoryUnparsable` 落 `lock_history_unparsable`、`ChainUnverifiable` 落 `chain_unverifiable`），`exit 1`，**`--json` 仍输出一份合法 JSON**（`ok: false`）。
  4. `except Exception`（**只兜以上之外的真正未知异常**）：转成 `errors[]` 的 `{code: "internal_error", message: <异常类型 + 首行>, path: null}`，**`exit 2`**，同样输出合法 JSON，**不得让 traceback 逃逸到 stdout**。理由可复算：干净基线上 `validate_value(..., lexical=True)` 会抛 `TypeError`（参数还不存在），若只捕三类，S-51 会以 traceback 而不是错误码失败。`raise` 只是单元测试里的内部细节，**不得逃逸到 CLI 顶层**。S-49 的断言因此写在 CLI 面上：`check --json` 的 `errors[].code == lock_history_unparsable`、stdout 是合法 JSON、`exit 1`。`internal_error` 的码表登记见 §5.2 第 13 条。
- **⓪ 短路后的完整性（v20/重要 3；v21/次要 1 补枚举；v22/次要 3 补 `internal_error`；v31/S-2 补哨兵）**：⓪-0 / ⓪-1 **以及第 0 步之后、⓪-0 之前的哨兵 `lock_tracked_but_deleted`（v31/S-2）** 一红即 `exit 1`，但**报告结构不得退化成「只有一条错误」**——`errors[]` 只含该码，`warnings[]` / `skipped[]` **照常输出**（该次运行已产生的那些；没产生的就是空数组，不是缺键），未执行的段按固定名写进 `not_run[]`（`["root_history_check", "root_v1_check", "root_changed_check", "path_level", "state_level", "chain_level"]` 的子集；**⓪-2 的 `lock_v1_with_seals` 有独立名字 `root_v1_check`**，不得并进 `root_history_check`）。**哨兵短路 ⇒ 六段全进 `not_run[]`（v31/S-2）**：`lock_tracked_but_deleted` 位于 ⓪-0 之前，一红则六个段名一个都没执行，`not_run[]` 必须是**完整六项**（不是子集），`errors[]` 只含该码。**`internal_error` 路径同样要填 `not_run[]`（v22/次要 3）**：检查器必须维护「已跑到第几步」的游标（⓪-0 → ⓪-1 → ⓪-2 → ⓪-3 → ⓪-4 → 路径级 → 状态级 → 链级），异常发生时按该游标把**其后的所有段**写进 `not_run[]`；异常若是从某段内部抛出，**该段本身也算未完成**，一并写进去（例：在 `root_history_check` 内抛 ⇒ `not_run` 从 `root_history_check` 起算）。不得把全部段都填进去冒充「一段没跑」，也不得留空数组。stdout **不得为空**、不得只有一行纯文本而无结构；`--json` 与人类可读输出都必须能看出「后面没跑」。
- **确定性（v21/次要 2；v29/次要 1 补 `info[]`）**：**五个数组**（`errors` / `warnings` / `info` / `skipped` / `downgrades`）都要有明确排序——前四个按 **`(code, path)`** 字典序（`path` 为 `null` 排最前），其中 `info[]` 同用 `(code, path)`；`downgrades[]` 按 `(code, path, scope)`（`path` / `scope` 为 `null` 排最前），保证同一工作树两次运行字节一致（便于 diff 与 CI 快照）。`not_run[]` 按上述固定枚举顺序输出，不排序。

**`seal reanchor --review`（决策 1/决策 5/重要 4）**

- 触发：父仓历史被 rebase / squash / filter-branch 改写，旧 A 提交对象本地不可达。**只对 `D == 0`（封条路径保留、仅内容/SHA 被重写）有效**；同路径删+重建（`D > 0`）先判 `seal_history_reset`，reanchor 不适用，且这条**永久红、不可恢复**（`L` 里那条 `D` 永远在）——这与「换路径重建」（旧路径**可删**但删除必须被 `moved_from` 覆盖 + 新路径首签，见下方「其余不变量」）是两件事，后者才允许，且必须把重置事实记在 `moved_from` 上（v12/重要 3；v13/R12-1 调整：旧文件**不必保留**，但旧键必须 `retired` 且删除被覆盖）。
- 前置（v9/B1；v10/I-6 定序；**v11/阻断 1 修同步对象；v12 按路径键查表**）：先 `lock --update`。它按 §1.1.3 的写锚规则**只刷新当前路径那个键**的 `renewal_seq` / `n`（**`epoch_origin` 默认保留**，不得重算成重写后的可达 `L[0]`；其他路径的键一个字都不动）。**签发前的校验对象是 HEAD 的封条**：要求 `seal_anchors[S].renewal_seq == HEAD 封条的 renewal_seq` 且 `seal_anchors[S].n == N`；**不要拿当前 `L[-2]` 判**——预检时 HEAD 还是 reanchor 前的普通续签，`L[-2]` 是再上一枚封条（`seq = N-1`），按它判会把每次恢复都挡成 `seal_anchor_stale`（实测 PRE：锚 `seq=2`、`L[-2].seq=1`）。这个值在 reanchor 提交（`HEAD == R0`）上才恰好等于 `L[-2]` 的 seq/n，所以 4a 与第 10 步仍用 `L[-2]`，两者不矛盾。判定顺序固定：`seal_anchors` 为 `null` 或无键 `S` ⇒ `reanchor_anchor_missing`；**键存在但 `state != active` ⇒ `seal_path_retired_write` / `seal_frozen_modified`（R12-4：`retired` 路径禁止新 `reanchor`，不得当「跳过」）**；锚与 HEAD 不同步 ⇒ `seal_anchor_stale`（**成立即拒，不再报 mismatch**）；两者都不是才允许签发。**`seal reanchor` 与 `lock --update` 的 preflight 都不要求「当前链 PASS」**：重写后的仓在第 4b 步本来就报 `reanchor_record_missing`，那正是 reanchor 要修的状态；若这两个命令先跑全链校验，恢复入口会被自己的规则挡住（第九轮「规则自己要求做的事，一做就红」的同类风险）。
- 行为：`renewal_seq = 旧值 + 1`（有 reanchor 时该仓后续一律按规则 4 的公式判）；写 `reanchor = {base_seq: 新 seq, base_n: 签发时不含本提交的 N, from_a: <旧 A>, review}`；**`previous_seal_commit = from_a`**（旧 A，本地不可达；这是第 8 步唯一的跳过条件）；**`previous_seal_sha256 = null`**（v10/次要 2：边界不表示前驱，旧 A 的封条字节取不到；不要沿用旧值，否则字段名会被读成 `sha(L[-2])`）；`first_seen_at` 原样保留。除 `renewal_seq` / `previous_seal_commit` / `previous_seal_sha256` / `reanchor` / `signed_at` **五类字段**外**不得改任何其他字段**（第 5 步载荷等价会逐字节比对 `L[-2]`）。后续续签必须保留 `reanchor` 字段，并把 `previous_seal_commit` 指向 reanchor 提交本身（B1）；删掉该字段会由第 4b 步判 `reanchor_record_missing`（B-2）。
- 锚约束：`--from-a` 必须等于 `epoch_origin[S]`；`base_seq` 必须等于 `seal_anchors[S].renewal_seq + 1`；`base_n` 必须等于 `seal_anchors[S].n`。三者任一不符 ⇒ `reanchor_anchor_mismatch`（S-25）。签发时由 CLI 校验；validator **只在 `HEAD == R0` 时复核**（提交身份，见 §3.2 规则 0）。post-lock 独立提交与不改封条的 merge 不在 `L`，不复核（B-1）。
- **豁免起点重指（v22/I-6；v23/I-2/I-3 改口径）**：reanchor 后 `L[0]` 被重写成新 `R0`，锁键里指向旧 `L[0].signed_at` 的 `exemption_started_at` 会永久红；因此本命令必须**在同一次写入**里把该路径键的 `exemption_started_at` 改成**新 `L[0].signed_at`**，并向 `exemption_start_history[]` **append** `{from: <重指前的旧值>, to: <新值>, commit: <执行 reanchor 时的 HEAD，即 R0 的父提交>}`。**`exemption_start_origin` 的已有值一律不改写**（缺失时按 §1.1.3 第 3 条一次性回填；改写已有值会被锁历史锚判 `exemption_start_origin_rewritten`）；`first_seen_origin` 同此，**已有值不改写**。两个字段必须同时写：只改 `started_at` 不 append、或只 append 不改值 ⇒ **`exemption_start_history_broken` FAIL**（S-55）。`lock --update` **不得**代替这一步（它对 `exemption_started_at` 只读、对 `origin` / `history` 的已有值不动，只做缺失回填，见 §1.1.3 第 3 条）。
- 后置（v10/B-1）：reanchor 提交合并后**必须在该提交上再 `lock --update`，并作为独立提交提交**，按 §1.1.3 的推进条件把 `epoch_origin` 置为 `R0`（新纪元）、`anchor_review` 写成 `R0.reanchor.review`；**`exemption_start_origin` / `exemption_started_at` / `exemption_start_history` / `first_seen_origin` 的已有值都不由这一步改写**（前三者已由上一段的重指写完；缺失值按 §1.1.3 第 3 条一次性回填）。**禁止 amend 到 R**：amend 后 HEAD 仍在 `L`、仍满足 `seq == base_seq`，但 `epoch_origin` 已指向 amend 前的 R，`from_a` 无字段可对，当前字段集下无解。若拖到下一次续签之后才跑，锚只刷新 `renewal_seq` / `n`、`epoch_origin` 仍是旧原点（操作约束，§8）。
- **只允许在完整仓的 fresh clone 执行（决策 5；v11/阻断 2；v12/阻断 2 修探测方式）**：预检先 `git rev-parse --is-shallow-repository`，为真即**非零退出拒绝**（message 提示 `git fetch --unshallow` 或重新完整 clone）。**partial clone 的探测不能用 `git rev-parse --is-partial-clone`**：该选项在 git 2.50.1 / Apple Git-155 上不存在，三个仓（normal / `--filter=blob:none` / `--depth 1`）实测都是 **exit 0 并把参数原样回显**，所以「退出码非零 ⇒ 拒绝」和「输出 == `true` ⇒ 拒绝」两种写法都永不生效、也不会报错（v12/阻断 2 实测）。改用下面任一（命中即拒绝，打印命中的配置键）：`git config --get-regexp '^remote\..*\.promisor$'`（有输出）、`git config --get extensions.partialClone`（有输出）、或 `ls "$(git rev-parse --git-path objects/pack)"/*.promisor`（有文件）。**partial 只是防御纵深**：它缺 blob 会让第 5/9 步自然红（`chain_unverifiable` / `seal_missing_at_commit`），严重度低于 shallow（shallow 会让 A/D 计数整体失真、直接假绿），不要把两者写成同级。做完形态检查再做 `git cat-file -e <from_a>`：成功 ⇒ `reanchor_not_allowed`。理由：浅克隆里 `cat-file -e` 对任何被剪掉的提交都失败，会把「本地没有」误判成「真的不可达」；签出第二纪元后再追加一个合法后置 lock，`HEAD != R0`，第 10 步整段跳过 ⇒ 最终 PASS（S-29 的构造）。**不要**改成「任意 HEAD 都查 `cat-file -e from_a`」——服务器保留旧对象时会把合法 reanchor 误判。工具不提供 `--force` 之类的破坏性绕过命令。
- `from_a` 由操作者用 `--from-a <sha>` 显式给出（旧首签 sha，从旧历史 / 审计记录取）。**v9 起它不再是纯自述**：必须等于锁内该路径键的 `epoch_origin`，因此「是不是旧 A」变成「是不是锁里记的那枚 A」；残余风险收窄为**三类**（v12/次要 9）：① 锚与封条在**同一提交**里同时被改写（键集合断言与 `epoch_origin != L[0]` 已堵住「只删锚」「只删字段」；剩下的是两侧一起改，锁与封条应走同一 PR 评审）；② 在旧原点**确实不可达**的仓里，攻击者从锁里读出 `epoch_origin`、手写一次载荷不变的 reanchor——这与合法 reanchor 在本地不可区分，只能靠 `review` + 同 PR 评审（§8）；③ **只有锁、没有封条路径可枚举的仓**：两种形态——(a) **封条尚未跟踪**（`git ls-files` 为空、`U` 为空集）；(b) **曾经跟踪、后来被删到空**（`U` 非空但 HEAD 上没有任何 `*.seal.json`，且键也被删光）。后者是 v12 最危险的形态：v12 的键集取 HEAD，`U` 不参与，于是「空集 == 空集」照样成立；v13 用 `U` 判 `seal_anchor_path_unmapped`（历史路径缺键）先挡住，但只要实施者把 `U` 也算成「HEAD 现存路径」，两种形态又会合成一个假绿。判据：`U` 必须从 `git log --diff-filter=A` 算，**不得**从 `git ls-files` / 工作树枚举算；`U` 非空而键集为空 ⇒ `seal_anchor_path_unmapped` FAIL，不是「无锚」。锚层之外仍靠 §3.3 的跟踪要求与 `card_untracked` 先挡。**「回滚到旧纪元」已不在此列**：4b 的 `review` 外部锚会抓住（v11/重要 1）；**「多封条互踩锚」也已不在此列**：v12 的按路径键映射让每条路径各自受约束（S-32）。
- 普通 rebase 后未 reanchor ⇒ 红，但**错误码要按判序看**（v10/B-2）：第 4b 步先跑，锁里 `epoch_origin` 仍是旧 A、封条无 `reanchor` ⇒ `reanchor_record_missing`；若锁里还没有该路径的锚键（`seal_anchors` 为 `null` 或无键 `S`），才落到第 5 步的 `renewal_chain_broken`（封条字节未变、D=0，`previous_seal_commit` 指向的旧 SHA 与重写后的 `L[-2]` 不等）。两者出口相同：`lock --update` → `seal reanchor`。若重写同时把封条重置成 `seq=1 / previous_*=null`，则落入上一条不可检测形态。
- 有 reanchor 时旧封条可能不可读 ⇒ 封条载荷里的 `first_seen_at` 只能由写侧「原样保留」自述。**v23/I-1 起 `gap.due` 的上界改由锁键 `first_seen_origin` 承担**（外部锚 = 锁历史中该键最早出现版本，不等 ⇒ `first_seen_origin_rewritten`），`first_seen_at` 降为审计字段，这条残余风险随之关闭；**剩余残余风险**只有「锁与封条在同一个提交里同时改写」——锁键由同 PR 评审兜（§8），工具无法在本地区分。
- 主干禁止 rebase/squash 是**仓契约要求**，不是本工具的检测项（§8）。

**其余不变量**

- **换路径重建（v13/R12-1 重写）**：成员改名等确需换路径时，**旧文件可以删除**，但必须同时满足四条——① 旧键**保留**并改 `state: retired` + `moved_to: <新路径>`（append-only，**不得删键**）；② 新路径按首签签发（`renewal_seq=1`）并记 `moved_from: {path, sha256}`；③ `moved_from.path` ∈ `U`，且 `moved_from.sha256 == sha256(旧路径迁出前最后一枚封条字节, CRLF→LF)`；④ 旧路径 `L_pre`（删除提交之前的事件序列）仍满足规则 0–7，删除提交有且仅有一次。任一条不满足 ⇒ `seal_path_history_lost` FAIL。**`moved_from.path` 不再要求「HEAD 上仍存在」**——那正是 v12 的缝：旧文件删掉后既不在 HEAD、旧键又被删，旧路径整段退出校验。现在旧路径的约束来自 `U` + `retired` 判据，与 HEAD 上还有没有文件无关。**否则「换路径重建」会把重置事实从机读面抹掉**——这条与「同路径删+重建永久红（`seal_history_reset`）」一起，才是重要 3 要求的自洽口径。两条路径各自按 `L/N` 判，不跨路径累计；旧键**不再参与** 4a/4b/第 10 步的锚比较（`state != active`），而是走 §1.1.3 第 5 条的三条迁出判据（S-33 复算的就是 `L_pre`）。归档不改封条路径，因此不触发 `D`；任务删除只能 `frozen`（文件保留），不存在「删文件不迁出」的合法出口。
- `chain_unverifiable` 与 §1.1 的 `definition_commit_unverifiable` 同口径；CI 必须 `fetch-depth: 0`（`actions/checkout@v4` 默认 1，`.github/workflows/tests.yml:17` 就是），否则整仓红。
- 重新 backfill 只允许改 `due`（仍受上限），保留 `first_seen_at`、`renewal_seq` 递进。
- 到期 FAIL；不转 legacy；唯一出口是真正跑 apply 后签 `kind=binding` 并删除 backfill 封条。
- owner 只从 CLI `--owner` 必填；不读 `.trellis/.developer` 或 git author。
- 若父仓未跟踪封条，链不可复算 ⇒ 先按 §3.3 的跟踪要求修复；不把「无链」当通过。

**判据**：S-06…S-08、S-13…S-53（含 S-45b、S-47a/b）、**S-55**、T-14…T-29、D-37/D-38/**D-40**、V-19/**V-20/V-21**。

### 3.3 `.trellis/` 封条可跟踪性与归属（R4/决策 2）

**实测**：跨网传输 `.trellis` 未跟踪（`git ls-files = 0`，`# .trellis/` 是注释）；sandbox 跟踪 66 个文件；Trellis 归档把任务移到 `tasks/archive/<month>/` 并置 `completed`（`atlas-sandbox-legacy/.trellis/scripts/common/task_store.py:1288` 起）。

**决策**

- 封条落**父仓** `<assets_root>/reviews/apply/<member>/<task-id>.seal.json`，不放成员 `.trellis/`。
- 跟踪校验在父仓：`git -C <parent> ls-files --error-unmatch <seal>`；未跟踪 = `absent`（0.3.0 WARN → 0.4.0 FAIL）。
- 成员目录在父仓 untracked（`shared/solution.md:23`）不影响封条：父仓读成员文件系统；CI 按锁 clone 成员。
- **成员仓跟踪前置（P4/Q-4，C 批硬前置）**：成员仓必须跟踪 `.trellis/tasks/*/prd.md`（含归档前路径）与 `.trellis/tasks/*/solution.md`；`git -C <member> ls-files --error-unmatch <path>` 不命中 ⇒ `card_untracked`。迁移工具是 B-0 的 `migrate --check-members`（只读，逐成员按**解析后的实际路径**打印 `git -C <member> add -f <prd> <solution>`：active 卡为 `.trellis/tasks/<ID>/…`，归档卡为 `.trellis/tasks/archive/<month>/<ID>/…`，见 §5.2 I3）；这是 C 批的前置，不是建议。**没有宽限**：`signed_at` 分层已删除（封条由 C 批引入，任何真实封条都晚于 0.4.0，分层不可达；§3.2）。
- **严格态是判据（重要 1/3/6/Q-6）**：`solution check` **默认即严格态**，不存在「默认 SKIP、`--strict` 才 FAIL」的中间态（`--strict` 保留为显式别名，默认已开启）。`--lenient` 只是开发早期的显式退出：仓内存在任一封条（`<assets_root>/reviews/apply/**/*.seal.json`）⇒ **直接拒绝执行**（exit 2，首行 `[FAIL] --lenient 仅限无封条`）；**只有锁不再拒绝**。原因：`init_solution` 在成员齐全时立即写锁（`_support/solution.py:1048-1049`），`adopt` 无条件写锁（`:1075`），锁是父仓跟踪文件，fresh clone 必然有锁但没有成员工作区；若锁也拒绝，新人 clone 下来连 `solution check` 都跑不了。
- 成员仓**没有封条**；成员侧只保留 `validate_task_card`。
- 归档后封条不动；`status=archived` 才停止新鲜度检查。卡解析先 `.trellis/tasks/<ID>/`、再 `.trellis/tasks/archive/<month>/<ID>/`（§1.3.6）。
- **缺席矩阵（R4/P4/Q-4/Q-6）**：

  | 观测 | 默认（=严格） | `--lenient`（仅无封条） | 备注 |
  |---|---|---|---|
  | `member_workspace_absent` | FAIL | SKIP | fresh clone 只有锁、无封条时 `--lenient` 可用（U-09）；CI 必须按锁 clone |
  | `card_untracked`（成员仓未跟踪卡） | FAIL（C 批起，无宽限） | SKIP | 迁移用 `migrate --check-members` |
  | `card_absent`（有封条但 active 与 archive 都缺卡） | FAIL | —（有封条 ⇒ `--lenient` 已拒绝执行） | 签发时已承诺投影；本地开发用 `--allow-card-absent` 降 WARN（CI 禁止） |
  | `seal_absent` | 0.3.0 WARN / 0.4.0 FAIL | WARN | 无封条就没有绑定证 |
  | `chain_unverifiable` | FAIL | —（有封条 ⇒ `--lenient` 已拒绝执行） | 窄开关 `--allow-unverifiable-chain` 才降 WARN，不复用 `--lenient` |

  - 默认列就是严格列；`--lenient` 只在「仓内没有封条」时可执行，有封条即 exit 2。
  - `card_absent` / `chain_unverifiable` 都需要封条才可能出现；有封条时 `--lenient` 已被拒绝，因此不存在「`--lenient` 下把它们当 SKIP」的路径。两者各自由 `--allow-card-absent` / `--allow-unverifiable-chain` 单独降级，且降级都要打固定 WARN 行并写 `downgrades[]`。

**判据**：U-08、U-09、K-13、K-14；`--lenient` 在有封条时 exit 2（夹具红），仅有锁时可用（夹具绿）；CI 命令行出现 `--lenient` / `--allow-card-absent` / `--allow-unverifiable-chain` 仍作为辅助夹具。

### 3.4 E2E 重签生命周期：块级绑定 + 旧哈希（B9/R5/决策 7）

**为什么原方案不成立**：v3 的 `changed_case_ids` 只有声明、没有旧哈希，validator 无法证明「这些 case 真的变过」；`previous_cases[]` 就是给复算用的旧值（R5）。

**块边界文法**

- 用例块 = `## <E2E-ID>` 标题起，到下一个 `##` 标题或 EOF（`HEAD`，`validate_e2e_index.py:178`）。
- 签名投影只取该块内**第一个** ` ```atlas-case ` 围栏体（`BLOCK`，`:179`；提取点 `BLOCK.search`，`:409`）。
- 摘要 = sha256(围栏体，CRLF→LF，去尾部换行)；标题、散文、Notes、索引状态列都不进摘要。
- 索引 `关联AC` 不在分片里；改 `关联AC` ⇒ `reason=link-change`。
- 分片围栏体改 ⇒ `reason=case-change`；索引状态回写 ⇒ 不 stale（§4.2）。

**封条字段（R5/决策 7）**

```json
"reasons": ["case-change"],
"e2e": {
  "status": "ready",
  "selector_sha256": "<manifest case_ids set>",
  "cases": [{"id": "E2E-AUTH-001", "sha256": "<body sha>"}],
  "links": [{"case_id": "E2E-AUTH-001", "acs": ["AC-AUTH-012"]}],
  "changed_case_ids": ["E2E-AUTH-001"],
  "previous_cases": [{"id": "E2E-AUTH-001", "sha256": "<previous body sha>"}],
  "gap": null
}
```

- `previous_cases[]` 只收录本次 `changed_case_ids` 对应条目；首签为空数组；旧封条在 Git 中必须可读。旧封条对象本地缺失 ⇒ `chain_unverifiable`（默认 FAIL；仅 `--allow-unverifiable-chain` 降 WARN），**不得当首签**（P3/重要 2）。
- validator 复算：
  1. 从 `previous_seal_commit` 读旧封条的 `e2e.cases[]`；
  2. `previous_cases[]` 必须与旧 `cases[]` 在 `changed_case_ids` 上的子集逐项相等；
  3. 当前分片 body sha 必须等于新 `cases[].sha256`；
  4. `changed_case_ids` = `{id | 新 sha ≠ previous_cases sha}`，声明必须与复算一致。
- `ready` 要求：每条 `case_id` 在索引主表、分片块摘要匹配、选择器集合相等。
- **与 reanchor 的衔接（B1 副作用，v8 补，v9 升为机器判据）**：reanchor 提交除 `renewal_seq` / `previous_seal_commit`（= `reanchor.from_a`）/ `previous_seal_sha256`（置 `null`）/ `reanchor` / `signed_at` 五字段外**不得修改任何字段**，尤其 `e2e.cases[]` / `links[]`；因此 `changed_case_ids` 与 `previous_cases[]` 必须与 `L[-2]` **逐字节相等**（通常为空，但**不要求一定为空**——它们是被冻结的业务载荷，不是清零），上面第 1–4 步不执行——`previous_seal_commit` 指向旧 A（该纪元首签那枚封条），不是被重写前的上一枚封条，不能当旧值读。reanchor 之后的普通续签恢复「从 `previous_seal_commit` 读旧封条」。**这条不再只是纪律**：§3.2 第 5 步的载荷等价会逐字节比对 `L[-2]`，改任何业务字段即 `reanchor_payload_mismatch`（S-24）。

**判据**：T-06…T-14。

## 4. 两条风险

### 4.1 #59：sha 只证明不变，不证明路径对（B3/B4/R2）

**反例**

- 同 domain / 同 domain_code / 同 AC 编号的副本：抬 `prd_version`、改路径、带 REVIEW-ID ⇒ 机器面全绿；机器无法区分「合法重写」与「替换」。
- 数量阈值：2 条 AC 错 1 条 = 50%；100 条错 90 条 = 90%。任何比例都不成立，所以不做比例阈值。

**可见性条件（不是防伪）**

1. 路径显式且受后缀约束；
2. `prd_version` 单调、`prd_date` 可读；
3. `commit + blob` 绑定，摘要从 blob 复算；
4. `requirements_digest` 每次 check 复算；
5. 任何 `definition` blob 变化（含同路径替换）必须 review PRD diff；路径变更额外标记；
6. `lock --update` 打印 old→new，`check` 每次输出 `定义源: …`（§2.6）；锁与 PRD 必须同一 PR。

机器证明「变了」；人证明「变得对」。这是 #59 的关闭条件，也是残余风险（§8）。

### 4.2 E2E：回写与重签成本（B9/R5/I12）

- 状态回写只进索引（`rings/e2e/reference.md:170`、`:509`、`:713`），不进分片围栏体；绑块不绑全文后，正常跑测试不会 stale。
- 谁重签：资产变更者（分片 / 链接 / 上游），不是跑测试的人。
- 防无脑重签：`reasons` 集合 + 实际变化复算 + `previous_cases[]` + `prev_sha256`。

**reason → 字段对应表（I12）**

| reason | 可验证的变化 | 证据字段 |
|---|---|---|
| `case-change` | 分片 `atlas-case` 围栏体 sha 变化 | `e2e.cases[]` + `e2e.previous_cases[]` |
| `link-change` | 索引 `关联AC` 集合变化 | `e2e.links[]` + 旧封条的 `links[]` |
| `upstream-change` | `upstream[]` 任一绑定字节变化 | `upstream[].sha256` |
| `card-acceptance-change` | 卡投影 sha 变化 | `card.projection.sha256` |
| `legacy-allowlist-change` | 白名单 sha 变化 | `legacy_allowlist_sha256` |

- 一次重签同时改 case 与 link：`reasons` 必须**同时**含 `case-change` 与 `link-change`；缺任一 ⇒ FAIL。
- 首签 `reasons=[]`；重签必须非空，且与实际变化集合相等。
- `reasons` 是集合：多写一个没有对应变化的 reason ⇒ FAIL（防止「全量重签」洗掉证据）。

## 5. 兼容与迁移

### 5.1 `acceptance_cutover`（B7）

- 载体：清单 v2 顶层 `acceptance_cutover: YYYY-MM-DD`，**v2 清单必填**（v18/阻断 3）。v1 清单缺省**不 FAIL**，只给 `migration_required` WARN（迁移提示）。
- 写入方：`init` 与 `migrate --to 2` **都写**（v18/阻断 3；v6 只写 `init` 不够，迁移仓会缺字段）。
- **默认值与打印（v19/阻断 2）**：无 `--cutover` ⇒ 写**包级默认 `2027-03-31`**，并在 stdout **显式打印一行** `acceptance_cutover=2027-03-31（可用 --cutover 覆盖）`。`init` 与 `migrate --to 2` 同规则，不允许「静默取默认」——人必须看到实际写入了什么。
- **`--cutover` 的门槛（v19/阻断 2；v20/重要 1 改算式与边界）**：`--cutover <YYYY-MM-DD>` 允许，但**值晚于包级默认时必须同时给 `--anchor-review <REVIEW-ID>`**（复用本节「放宽必须 review」的同一机制），且**不得晚于默认值 + 90 天**。上限由算式表达，**不写死日期字面量**：`cutover_max = date(2027, 3, 31) + timedelta(days=90)`（= `2027-06-29`）；**边界写死「等于上限算通过」**（`cutover <= cutover_max`）。违反任一 ⇒ 拒绝写文件、`exit 2`，文案打印默认值与上限。**不晚于默认**（收紧）不需要 review。**允许早于包级默认（收紧）**：本节只设**上界**（默认 + 90 天）与「晚于默认须 review」门槛，**没有「不得早于今日」或「不得早于默认」的下界**——`--cutover 2027-01-31` 合法、无需 review（v27/B-1 ③a 依赖此条）。
- **review 记录（v19/阻断 2；v20/重要 2 写明自述）**：cutover 晚于包级默认时，清单同时写 `acceptance_cutover_review: REVIEW-...`（`\|REVIEW-\d{8}-\d{2}\|`）；**显式给了 `--anchor-review` 就落盘（含早于 / 等于默认），不设 `ignored` 第三态**；没给则不写该字段（v35/口径裁定：与已落地写侧一致、与「显式给了必须落盘或报错」一致，且不影响 `acceptance_cutover_unreviewed`——它只对晚于默认触发）。B 首次 `lock --update` 把 `acceptance_cutover` 与 `acceptance_cutover_review` 一并写进锁。**判据**：首次写入的值晚于包级默认、而清单 / 首次锁里的 `acceptance_cutover_review` 为空 ⇒ **`acceptance_cutover_unreviewed` FAIL**（`detail.kind = "review_missing"`）；值晚于上限 ⇒ 同码、`detail.kind = "beyond_default_plus_90d"`（写侧本应已拒绝，此处兜手改）。这是在 `missing` / `mismatch` 之外的第三条，**只管「门槛」，不管「两侧一致性」**。**判序（v36/重要 1）**：**先空后形态**——review 为空 ⇒ 判 `acceptance_cutover_unreviewed`（仅 `cutover` 晚于默认时）；review 非空且形态不符 ⇒ 判 `acceptance_cutover_review_malformed`；**两码互斥，同一字段只出一个码**。**实现状态（v36/重要 1）**：`acceptance_cutover_unreviewed` 目前在代码中不存在（`_check_acceptance_cutover` 只有 `missing` / `mismatch`），所以 V-20⑥ 现在会**假绿**；该谓词必须与 `malformed` **同批实现**，否则 V-20⑥ 永远绿。
- **review 是自述（v20/重要 2）**：`acceptance_cutover_review` 与 `assets_root_history[].review` 都**只校验 `REVIEW-\d{8}-\d{2}` 形态**，工具**不做台账查询**、不验证该评审是否真实存在、不比对评审内容——它们是「人承认过」的记账，不是证明。能做的只有形态门与**不重复**：**同一个 `REVIEW-ID` 同时用于两次不同决策（至少一次改根、一次改 cutover）⇒ `review_reused` FAIL**；同一决策链内的重复引用（例如同一根的历史元素复用同一 ID，或 cutover 的首次写入与后续 `lock --update` 继承同一 ID）不算复用。判定取锁历史全量（`assets_root_history[].review` ∪ `acceptance_cutover_review`），按 `(review_id → 决策类别集合)` 聚合，集合大小 > 1 即红。**早于 / 等于默认写入的 review（v36/次要 1）**：**仅存档**——不进 `acceptance_cutover_unreviewed` 门槛（该码只在晚于默认触发），但**仍参与 `review_reused` 去重**（聚合口径不区分早晚）。
- **冻结点：B 批首次 `lock --update`**。B-0 不改 `lock_payload`（`_support/solution.py` 只写 `members` / `contracts`），所以 B-0 阶段该字段只在清单；**B 批首次 `lock --update` 必须把值（与 review）写进锁**，不是「此后才判」的软窗口。
- 放宽（改晚）必须 `lock --update --review <REVIEW-ID>`；改早（收紧）允许。**改晚仍受「≤ 包级默认 + 90 天」约束**：超过即 `exit 2`，不允许用 review 换无限延期。
- **唯一标记（v18/阻断 3）**：「已首次刷新」= **锁文件历史里任一版本 `definition.commit != null`**。不再引用 `acceptance_cutover.commit`（该字段不存在）。只看当前锁会被「改回 null」蒙混，所以必须扫全历史（与 §5.2 第 8 条同一取法）。
- **判据（三码，语义互斥）**：
  - **未刷新**（历史所有版本 `definition.commit == null`）：两侧皆空 ⇒ 合法 pending；单侧有值 ⇒ 放行（B-0 期间锁尚未写该字段）；两侧都有值且不等 ⇒ `acceptance_cutover_mismatch` FAIL。
  - **已刷新**：**任一侧缺失或两侧皆空 ⇒ `acceptance_cutover_missing` FAIL**（v18/阻断 3：`both_empty` 也是缺失，不再只由 `mismatch` 覆盖）；两侧有值且不等 ⇒ `acceptance_cutover_mismatch` FAIL；两侧有值且相等 ⇒ PASS。
  - **门槛**（任何阶段）：值晚于包级默认且 review 记录为空，或值 > 默认 + 90 天 ⇒ `acceptance_cutover_unreviewed` FAIL（v19/阻断 2）。
  - 写入侧：B 首次 `lock --update` 同时写值、review 与该次提交；此后任何 `lock --update` 都**不得把值写回 `null`**。
- **缺失口径（v18/阻断 3 收口）**：v2 清单无论 `requirements[].acs` 是否为空，都必须有 `acceptance_cutover`（必填）；旧句「空清单允许缺省」**删除**，不再保留第二口径。v1 清单缺省走上面的 `migration_required` WARN。
- 包版本日期 `2027-03-31` 只是**默认值**（`--cutover` 与 review 门槛的上限都相对它算），不是每仓 deadline；每仓以清单字段为准。

### 5.2 版本注入与 fail-closed（I8/R8/决策 5）

**现状**

- `SCHEMA_VERSION` 一个常量同时管清单（`_support/solution.py:267-268`）、锁（`:739`）、init（`:1022`）。
- `validate_manifest` 不接收包版本，没有「0.3.0 收 {1,2}、0.4.0 收 {2}」的注入点。
- `.atlas/VERSION` 现在存的是**装配摘要**（`install.py:804` 调 `stamp_file`），不是 semver；`install.py:352-364` 把它当摘要读。
- PRD 新列与封条对旧工具不可见。
- v3 声称「0.3.0 收 {1,2}、0.4.0 收 {2}」，但没有版本注入点，规则无法执行；`VERSION` 存的又是摘要，CLI 拿不到 `reader_version`（R8）。
- v4 把注入点放 CLI：`load_manifest` 有 15+ 调用方（含 `scripts/e2e_console.py:171-189`），漏网调用拿不到 `reader_version`；且没有 `migrate` 命令，0.4.0 硬拒后没有合法升级路径（重要 3/P5）。

**决策**

1. **拆分文件（决策 5）**：
   - `.atlas/VERSION` = semver（来自 `package.json`）；
   - `.atlas/DIGEST` = 装配摘要（`stamp_file` 的新落点）；
   - **注入点在 `load_manifest`（重要 3）**：`load_manifest` 内部解析 `<root>/.atlas/VERSION`；缺省时回落**工具自身**的两个来源——安装副本 `<root>/.atlas/package.json`、开发树/源码包的 `<工具包根>/package.json`（`Path(atlas_package_root)/package.json`），**绝不读被检查仓的 `<root>/package.json`**（v11/重要 3：采纳仓里 `<root>` 是业务仓，`1.2.0` 会被当成 `>=0.4.0`，把大量 v1 清单误判 FAIL）。三级顺序固定为：**① `.atlas/VERSION` → ② `.atlas/package.json` → ③ `<工具包根>/package.json`**（v12：与 `validators/validate_e2e_index.py:104-125` 的实现口径一致，**取消原第三级 `_support/_version.py`**——那是我方虚构的落点，现有代码第三级就是工具包根 `package.json`，不能两套并存）；三级全缺才 `reader_version_unknown`，且**一律 WARN**（不 FAIL，因为无法判版本）。`reader_version` **不做 CLI 参数**——`load_manifest` 有 15+ 调用方（含 `scripts/e2e_console.py:171-189`），CLI 注入会漏。
   - **三级各自的失败形态**：某级文件存在但不可解析（非 semver / JSON 坏 / 是装配摘要）⇒ 记一条 `downgrades[]`（`code: reader_version`、`scope: reader_version`、`path` = 该文件）并**继续回落下一级**（v11/重要 4）；只有三级都取不到才落 `reader_version_unknown`。安装副本的 `.atlas/VERSION` 在旧包上可能是摘要形态（`install.py:804` 的 `stamp_file`）——按本规则降级，不直接判 unknown。
   - semver 比较规则（次要）：数字段逐位比较；`0.2.0-beta.33` 的 prerelease 按 `alpha < beta < rc < 正式版`、同段比数字。
2. `install.py` 迁移：
   - `:804` 的 `stamp_file(..., VERSION)` 改为 `DIGEST`，同时写 `VERSION`（semver）；
   - `:352-364` 的 `copy_stamp` 从 `DIGEST` 读；旧副本只有摘要形态的 `VERSION` ⇒ 记一条 `downgrades[]` 并继续回落（不直接记 `reader_version_unknown`，v11/重要 4）；
   - 不迁移旧文件内容，`--update` 一次写新两文件。
3. 拆分常量：`MANIFEST_SCHEMA_MIN/MAX`、`LOCK_SCHEMA_VERSION`、`SEAL_SCHEMA_VERSION`、`PRD_SCHEMA_VERSION`。
4. `validate_manifest(data, root, phase1, reader_version)`：`reader_version` 由 `load_manifest` 传入；`0.2.x` 只接受 `{1}`，`0.3.x` 接受 `{1,2}`（B-0 的版本门提前，P-1），`0.4.0+` 只接受 `{2}`。**B-0 阶段的版本门是无条件 `{1,2}`（v11 约束）**：B-0 的 `validate_manifest` 不接收 `reader_version`（注入点属于 B 批），只做 `schema_version ∈ {1,2}` 的区间判断；上面的分版本收窄从 B 批接入注入后才生效。B-0 不得提前接入注入，否则「读被检查仓 `<root>/package.json`」的歧义（v11/重要 3）会反过来污染 B-0 的版本门，把采纳仓的 v1 清单判成 `manifest_schema_unsupported`。锁版本由清单决定：`manifest.schema_version == 2` ⇒ 本次 `lock --update` 写 `schema_version: 2`（`_support/solution.py:1290-1291`），**从 B-0 起生效**，不以「B 批首次升 2」为起点（v32/B-2 更正旧稿）；旧 v1 锁仍可读（只读）。
5. **消除 V-02 矛盾（R8）**：
   - 0.4.0 读 v1 清单 ⇒ **硬拒** `manifest_schema_unsupported`（exit 2）。**exit 2 的理由（v32/I-4）**：它在 `load_manifest` 里、报告对象构造之前抛出，没有 `errors[]` 可承载，按「环境 / 用法错误」处理；这与 ⓪ 层解析失败（有报告、exit 1）是两回事，不是两套并存；
   - 0.4.0 读 v2 但无 `definition` ⇒ FAIL `definition_unbound`（自愈路径：在 `reader_version < 0.4.0` 的装配上跑 `migrate --to 2` 补齐 `definition`，见第 6 条与 §8 残余风险；`migrate` 在 argparse 里**无条件注册**（`scripts/atlas_solution.py:183`），0.4.0 下的拒绝来自 `load_manifest` 的**读侧版本门**（实测 `[FAIL] manifest_schema_unsupported: 读者 0.4.0…`、rc=2），**不是** argparse 未知命令，v36/重要 3 更正）；
   - 迁移只在 `reader_version < 0.4.0` 的版本门**注册**（0.4.0 的注册门为 `{2}`，不再挂 `migrate`）；「用哪个二进制跑」不是判据，判据是**注册谓词**与**读侧门接受集**。
6. **迁移命令（P5/决策 6/重要 6/7）**：`migrate --to 2` 在 `reader_version < 0.4.0` 的版本门里注册（不按「用哪份二进制」区分）。
   - **两步，不自动 lock（决策 6/重要 6）**：`migrate` 只写清单里**缺失**的字段与 PRD front matter 里**缺失**的字段，写完退出，**不调用 `lock --update`**；人提交后再单独跑 `lock --update` 并提交锁。原因：`lock --update` 要求定义源工作树干净（§1.1.6 的 `git status --porcelain <path>` 非空即拒绝），migrate 刚写完文件时必然脏；自动 lock 会自相矛盾。该脏检查**只作用于 `lock --update`**，不作用于 `migrate`。
   - **只补缺、不改已有（重要 7）**：清单缺 `definition` / `acceptance_cutover` / `min_atlas` 才写；PRD front matter 缺 `prd_version` / `prd_schema` 才写；已有字段（含人手写的 `prd_version`、`definition.path`）一律不动。幂等 = 第二次执行 diff 为空（缺字段补齐、已有字段不动）。**（v32/B-1 撤销 v31 的「显式 `--cutover` 是覆盖语义」）显式 `--cutover` 同样受「只补缺」约束**：清单**已有** `acceptance_cutover` 且与 `--cutover` 不同 ⇒ **报错、不写任何文件**（`_support/solution.py:1846-1850`；docstring `:1810` 写死「只补缺，不覆盖已有字段」）；只有缺该字段时才写入。**不得为夹具放宽这条迁移器不变量。** PRD front matter 的 `prd_version` / `prd_schema` 也**只补缺**（基座已有则不动）。要构造非默认端点请走 `init --cutover`（T-32③a/③b），不要对已迁移仓重跑 `migrate --cutover`。
   - **`--cutover` / `--anchor-review`（v19/阻断 2）**：`migrate --to 2` 新增两个参数。无 `--cutover` ⇒ 写包级默认 `2027-03-31`，并 stdout 打印 `acceptance_cutover=2027-03-31（可用 --cutover 覆盖）`；`--cutover` 晚于默认 ⇒ 必须同时给 `--anchor-review <REVIEW-ID>`，并把 `acceptance_cutover_review` 写进清单；晚于默认 + 90 天（`2027-06-29`）或晚于默认而无 review ⇒ **拒绝写文件、exit 2**（§5.1）。`init` 复用同一实现与同一门槛，不写两套。**可执行边界（v32/B-1）**：① **收紧方向（早于包级默认，如 `2027-01-31`）无需 `--anchor-review`**（§5.1 只对「晚于默认」要求 review），放宽方向仍按上面的门槛；② **`migrate` 的注册门是 `reader_version < 0.4.0`**（0.4.0 不注册，V-15）——判据是**注册谓词**，不是「换一份二进制」；③ **基座已有 `acceptance_cutover` 时 `migrate --cutover` 只报错、不覆盖**（见上一条），所以端点构造一律用 `init --cutover`，不依赖 `migrate`。
   - **定义源消歧（重要 7/Q-5）**：`--definition-path` 显式给路径；未给时，`<assets_root>/prd/` 下恰好一份 `*-prd.md` ⇒ 用它；多于一份 ⇒ **拒绝并列出候选**，不猜。
   - **B-0 窗口（P-5/Q-5）**：B-0 的 `--definition-path` 只接受 `<assets_root>/prd/solution-prd.md`；其他路径 ⇒ `definition_path_unsupported`。B 批才放开任意 `*-prd.md`。
   - **落盘前按本版白名单校验，不自拒（Q-5）**：B-0 的自动探测会选中 `product/prd/auth-prd.md` 这类非默认名；若照写，同一版本的 `load_manifest` 下一次就会 `definition_path_unsupported`。因此 B-0 的 `migrate` 在写文件**之前**先校验目标路径：不在白名单 ⇒ **拒绝，不写任何文件**，打印 `[FAIL] B-0 只支持 <assets_root>/prd/solution-prd.md；任意 *-prd.md 由 B 批支持`。夹具 V-12。
   - **对已是 v2 的清单也补齐缺失字段（B2）**：幂等的定义是「**已有字段一律不动，缺失字段补上**」，不是「已是 v2 就只校验不改写」。因此 v2 缺 `definition` / `acceptance_cutover` / `min_atlas` 可由 `migrate --to 2` 自愈（v7 的「重跑也不自愈」已删）。**该自愈只由 `reader_version < 0.4.0` 的注册门接受**：0.4.0 不注册 `migrate`（版本门 `{2}` + 读 v1 硬拒），V-15 断言的是**注册谓词** `semver_lt(reader_version, "0.4.0")` 的取值，不是启动第二份二进制；B-0 的白名单拒绝发生在写盘前，是防「先写出再让读者撞错」，不构成死路。
   - **`migrate --check-members`（P-3/Q-4/重要 2/I3）**：只读检查，逐成员打印**解析后的实际路径**命令，而不是固定模板路径：
     - active 卡：`git -C <member> add -f .trellis/tasks/<ID>/prd.md .trellis/tasks/<ID>/solution.md`；
     - 归档卡：`git -C <member> add -f .trellis/tasks/archive/<month>/<ID>/prd.md .trellis/tasks/archive/<month>/<ID>/solution.md`（`<month>` 与 `<ID>` 取自实际目录）。
     
     v7 对所有卡都打印 active 路径，归档卡照抄会 `pathspec did not match` 且 `card_untracked` 依旧红。扫描范围包含 active 与 `.trellis/tasks/archive/<month>/<ID>/`（归档任务同样要让父仓在 clone 后可读，否则 `card_absent` 误红）；不改文件、不提交，供 C 批前置跟踪迁移。夹具断言 active 与 archive 各出一条命令。
   - **不静默自动改写**：清单是契约，必须人执行、diff 可见。
   - **升级顺序**：在 `reader_version < 0.4.0` 的装配上执行 `migrate --to 2` → 人提交清单与 PRD → `lock --update`（**清单已是 v2 ⇒ 锁写 `schema_version: 2`**，v32/B-2）→ 提交锁 → 再 `install.sh --update` 到 0.4.0。
   - **门的前提**：migrate 能在 B-0 跑，是因为 B-0 的 `validate_manifest` 已接受 `{1,2}`（P-1）；若门仍严格 `== 1`，`migrate --to 2` 后同一次运行里的 `lock` 会 `SolutionError`。
7. **`install.py --update` 拦截（P5）**：仓内有 v1 `atlas.solution.yaml` 且来包 ≥ `0.4.0` ⇒ **拒绝刷新 `.atlas`** 并打印 `atlas solution migrate --to 2`；否则 0.4.0 会在加载期 exit 2（`scripts/atlas_solution.py:443-445` 对 `SolutionError` 统一 `return 2`），而 `.atlas` 已被覆盖、迁移命令也跑不起来。
8. **`init` 按 `reader_version` 分支写（B2/v9；v10/I-3 补 `definition.commit = null`）**：
   - **`reader_version_unknown` ⇒ `init` fail-closed（v13/第十二轮 B 批前置）**：三级来源全缺时**无法判断自己是 0.3.x 还是 0.4.0**——写 v1 在 0.4.0 上会立刻自拒（版本门 `{2}`），写 v2 在 0.3.x 上可能不被接受。因此 `init` 遇 `reader_version_unknown` 必须 **exit 2 且不写任何文件**，message 打印三个候选路径与修复方式（重建 `.atlas` / 重装）；**不得默认写 v1**。注意与 `check` 的不对称：`check` 的 `reader_version_unknown` 仍是 WARN（只读、不写盘），`init` 是写盘且不可回退，故 fail-closed。夹具 V-18。
   - `reader_version < 0.4.0`（含 B-0）：写 `schema_version: 1`。
   - `reader_version >= 0.4.0-0`（含 beta）：写 `schema_version: 2`，**并写 `definition`**——路径取自 `init_solution` 经 `_prd_skeletons` 已写出的 `product/prd/solution-prd.md`（`_support/solution.py:963-999`），`definition.domain` 与 `domain` 同源。v8 的「一律写 v1」在 0.4.0 上会立刻自拒（版本门 `{2}` + 读 v1 硬拒），而 `migrate` 不在 0.4.0 注册，新仓无从就地补——这是 v9 修正的阻断。
   - **`--cutover` 与 reader 版本门（v33/阻断 4）**：`init --cutover` **只在 `reader_version >= 0.4.0` 写 v2 清单**（多一个 `acceptance_cutover` 字段）；`reader_version < 0.4.0` 下显式给 `--cutover` ⇒ **必须报错拒绝、exit 2（用法错误）、不写任何文件，不得静默丢弃**——v1 清单没有 `acceptance_cutover` 字段，静默丢弃会让「超上限会拒、写进去却沉默」两种行为并存（实现 `_support/solution.py:1660-1669` 已是该语义；`scripts/atlas_solution.py:519-521` 对 `SolutionError` 统一 `return 2`）。**「不启用第二份二进制」不等于「版本无关」**：全仓单 `package.json`、没有第二份二进制可跑，但 `reader_version` 仍决定清单版本（`manifest_version = 1 if semver_lt(reader, (0,4,0)) else 2`，`_support/solution.py:1647`）。夹具 **V-22**。**两态（v34/阻断 1）**：**产品路径**要等 B 批发版后（`.atlas/VERSION` ≥ 0.4.0）才能用 `init --cutover`；**测试路径**可预置 `.atlas/VERSION=0.4.0` 起步，但那是**夹具前置、不是产品可达路径**，不得据此宣称端点今天能在真实仓上跑。**早于默认的 `--anchor-review`（v35/口径裁定）**：`cutover ≤ 2027-03-31` 时 review 不是必填，但**显式给了就落盘**（清单与锁同写 `acceptance_cutover_review`，不设 `ignored` 第三态；与已落地写侧 `_support/solution.py:1717-1718` 一致）。**`migrate --anchor-review` 同理（v34/重要 5）**：显式给了 review **必须落盘**，不落盘即 exit 2。**v1 路径（`reader_version < 0.4.0`）下显式 `--anchor-review` 同样拒绝**（与 `--cutover` 同形：exit 2、不写任何文件；`_support/solution.py:1704-1708`），不得静默丢弃。**review 形态（v35/重要 1）**：写侧 `init` / `migrate`（含 `migrate --anchor-review`）收到形态不符的值 ⇒ **用法错误、exit 2、不写任何文件**；读侧清单已有坏值 ⇒ **FAIL `acceptance_cutover_review_malformed`、进 `errors[]`、exit 1**（不走 exit 2，否则一份坏值会让整份报告消失）。
   - **`definition.commit = null`（v10/I-3）**：`init_solution` 先写 PRD（`_support/solution.py:1037`）再 `write_lock`（`:1048-1049`），此刻 PRD 是 untracked——有 blob、没有 commit。锁里的 `definition.sha256` 与 `blob` 可由 `git hash-object` 当场算出，`commit` 只能写 `null`。这是唯一允许 `commit == null` 的形态。
   - **0.4.0 的放行与 WARN**：`check` 遇 `definition.commit == null` **不报** `definition_commit_unverifiable`（那是「对象本地缺失」的错误码），改报 `definition_commit_pending` WARN 并放行；首次 `lock --update` 必须补齐真实 commit，之后 `commit` 不得再为 `null`（再出现 ⇒ `definition_commit_unverifiable` FAIL）。**「是否已经首次 `lock --update`」必须有**不可回退**的状态标记（v11/次要 2；v12/重要 4 修取法；v13/R12-2 改主判据）**：仅看当前锁分不清「`init` 刚写的 null」与「后来被改回 null」。v12 的 ①②③ 都是一步记忆（只看 `acceptance_cutover` / 只看上一条锁 / 都不要就 WARN），`init → 首次 lock --update → 把 c1 改回 null → c2 仍 null` 这套操作在 CI 只看 PR 头时能蒙混。v13 改成**在锁文件的完整历史里找最近一次非 null**（v14/B-2：改判「**任一个**非 null 即算已刷新」，并用 `-m --full-history` 全扫）：
   - **主判据（不可回退；v14/B-2 修命令）**：`git log -m --full-history --format=%H HEAD -- atlas.solution.lock.json`（同一 merge 在 `-m` 下会出现多次，按 `%H` 去重），从新到旧逐个 `git show <c>:atlas.solution.lock.json`，**只要存在一个 `definition.commit != null` 的提交**而当前锁 `commit == null` ⇒ `definition_commit_unverifiable` **FAIL**。
     - **两条旗标各自管什么（v14/B-2，别把因果搞反）**：`--full-history` 是**防剪枝**的那一个。实测（`/tmp/v14e`：main 锁 `null`、side 写非 null、main 上 `git merge -s ours side` 保留 `null`）：`git log --format=%H HEAD -- atlas.solution.lock.json` 只输出 `null` 那条，side 的非 null 提交整个消失 ⇒ 落 `definition_commit_pending` WARN，`definition_commit_unverifiable` 的 FAIL 被蒙混；加 `--full-history` 才列出 side 那条。`-m` 让 merge 提交对每个父各出一份 diff，与 `U` 同一口径；但这条命令只取 `%H`、不取 diff，`-m` 对「列出哪些提交」**没有增量**（实测 with/without `-m` 输出相同）——**修好剪枝的是 `--full-history` 而不是 `-m`**，两个都写是为了与 `U` 保持同一字面口径，不许只留一个、也不许拿 `-m` 当防剪枝。
   - **不得用 `HEAD^`，也不得用 `--skip=1`（v14/B-2 删除旧等价声明）**：`HEAD^` 只取第一父，锁值若来自第二父就判不出来；`--skip=1` 返回的是「锁历史里的第一条之后」，与「HEAD 之前的最新状态」在 merge 下实测返回**不同提交**（R12-2）。v13 还写过「`--skip=1` 只在 HEAD 触碰锁时与各父中较新版本等价」——这句**没有判据价值，只会让实现者抄近路，v14 整段删除**；本条不再给任何局部取法，只认上面那一条全历史扫描。
   - ① **`acceptance_cutover != null` 不再是标记（v18/阻断 3 删除）**：`init` 与 `migrate --to 2` 都写该字段，它的存在不证明「已首次刷新」，把「cutover 有值 + 当前 `commit == null`」直接判 FAIL 会误伤刚 `init` 完的仓。唯一标记仍是上面「锁全历史任一版本 `definition.commit != null`」。
   - ② 全历史扫描**不可判**（如 `init` 后尚无任何提交、锁从未被触碰，或那个非 null 提交已被 force-push 抹掉）⇒ 才按 `definition_commit_pending` WARN；force-push 这一支的残余见 §8。
   - `init` 仍不接受 `--definition-path`（D-14 的夹具已改到 `migrate --definition-path`）；0.4.0 的路径由骨架固定，不需要人给。
   - 夹具：V-13（0.4.0 `init` 写 v2 + `definition`，B 批）、V-16（0.4.0 新仓 `init → check` PASS + `definition_commit_pending` WARN，B 批）、V-18（`reader_version_unknown` ⇒ `init` exit 2 不写盘，`check` 仍 WARN，v13/B 批前置）、V-19（main `null` + side 非 null + `merge -s ours` 保留 `null` ⇒ 必须 `definition_commit_unverifiable` FAIL，v14/B-2）。B-0 的验收不再包含 V-13（它背书的是 B 的行为）。
9. 封条 `schema_version` 独立；未知 ⇒ `schema_unknown` FAIL。
10. PRD front matter 增 `prd_version`（整数）与 `prd_schema`（整数，新列/契约表要求 2）；`validate_prd` 拒绝高于自身支持的版本。
11. **CI 必须 `fetch-depth: 0`（P3）**：

    ```yaml
    - uses: actions/checkout@v4
      with:
        fetch-depth: 0
    ```

    `actions/checkout@v4` 默认 1（`.github/workflows/tests.yml:17`），浅克隆下封条链与定义源 `commit` 都取不到。
12. **fail-closed 的边界**：清单 v2 是总开关，旧工具读到 v2 会硬拒。但旧工具 + v1 清单 + 新封条/新 PRD 列仍会「看不见 ⇒ 无门」。缓解：`min_atlas`、`install.sh --update` 比对、CI 显式比对；三者任一缺失仍是无门，文档如实写（§8）。
13. **错误码表（§5.2 码表；v22 起按实际枚数逐个列名，不写计数句）**：下表每个码都写清「写入哪个数组 / 退出码 / 是否可降级」。**外部审计只靠 `code` 反推判据**，不得靠 `detail` 文本（尤其不得把主码当 `detail` 值，见 `signed_at_not_canonical` 条）。
    | `code` | 含义与判据 | 落点 | exit / 数组 | 可降级 |
    |---|---|---|---|---|
    | `manifest_schema_unsupported` | `load_manifest` 的版本门拒绝（0.4.0 读 v1 / 0.2.x 读 v2）；**在报告对象构造之前抛出**，按 §5.2 第 13 条「exit 2 无 JSON 通则」处理（无 JSON、只有 stderr） | §5.2 第 4/5 条、V-02/V-08/V-17 | **2** / 无报告（stderr 文本） | 否 |
    | `lock_unparsable` | **⓪-0**：当前锁在解析层失败——非 JSON 对象 / `schema_version` 类型或取值不对 / `members`、`contracts` 缺失或非 list-of-dict / 任一 `.root` 结构性或词法性错误；**失败即短路**，`errors[]` 只有该码 | §3.2 ⓪-0 | **1** / `errors[]` | 否 |
    | `lock_history_unparsable` | **⓪-1**：锁的任一历史版本解析失败（对象在、字节坏）；**失败即短路**、不参与降级。**`non_blob` 属本码外延**（路径存在但类型是 tree / symlink / gitlink）：它不是「没有该路径」，不得当 `absent` 跳过（v35/次要 2） | §3.2 ⓪-1、§1.1.3 ⑦ | **1** / `errors[]` | 否 |
    | `chain_unverifiable` | **第 0 步 / ⓪-1**：`detail.cause ∈ {shallow, partial}`（仓形态不可信）或 `history_unreadable`（`git log` 不可读）；⓪ 层一律 hard FAIL，**字段名是 `cause` 不是 `kind`**（v32/I-3） | §3.2 第 0 步 / ⓪-1 | **1** / `errors[]` | 否（⓪ 层不降级；`definition.commit` 的对象缺失另有 `definition_commit_unverifiable` + `downgrades[]`） |
    | `signed_at_not_canonical` | 封条的 `signed_at` 不是 `YYYY-MM-DDTHH:MM:SSZ`（UTC、`Z` 后缀、无小数秒）；`+00:00`、`.123Z`、缺 `Z`、非 UTC 一律命中 | §3.2、T-28/T-29 | 1 / `errors[]` | 否 |
    | `review_reused` | 同一个 `REVIEW-ID` 被用于两个不同决策（改根 + 改 cutover）；同决策链内复用不算 | §5.1「review 是自述」 | 1 / `errors[]` | 否 |
    | `acceptance_cutover_unreviewed` | **门槛码**：`acceptance_cutover` 晚于包级默认而 review 为空 ⇒ FAIL（`detail.kind = "review_missing"`）；值 > 默认 + 90 天 ⇒ 同码（`beyond_default_plus_90d`）。**与 `acceptance_cutover_review_malformed` 互斥**：判序**先空后形态**——空值归本码（且仅晚于默认时），非空坏形态归 `malformed`，同一字段只出一个码（v36/重要 1）。**实现状态**：该谓词当前未落地（`_check_acceptance_cutover` 只有 `missing` / `mismatch`），必须与 `malformed` 同批实现，否则 V-20⑥ 永远绿 | §1.1.3、§5.1、V-20⑥ | **1** / `errors[]` | 否 |
    | `acceptance_cutover_review_malformed` | **读侧**：清单里的 `acceptance_cutover_review` 非空但形态不是 `REVIEW-\d{8}-\d{2}`（v35/重要 1）。**不走 exit 2**——否则一份坏值会让整份报告消失、用户看不到别的错误；进 `errors[]`、exit 1。**写侧**（`init` / `migrate` 收到 `--anchor-review`）形态不符属**用法错误**：exit 2、不写任何文件；**与 `acceptance_cutover_unreviewed` 互斥**：空值归上一行、非空坏形态归本码（先空后形态，v36/重要 1） | §1.1.3 清单字段、§5.2 第 8 条、V-23d | **1** / `errors[]`（读侧）；写侧 exit 2 无报告 | 否 |
    | `exemption_start_signed_at_not_canonical` | **只罚形态**，且**只管锁里的 `exemption_started_at` 字面值**本身不是规范形态 `YYYY-MM-DDTHH:MM:SSZ`；`path` 指锁文件（不是封条）。**任何封条 blob（含 `L[0].signed_at`）的形态一律归 `signed_at_not_canonical`**（v24/B-1 职责正交：通用封条形态 vs 锁内字面值形态）。等值不等一律归 `exemption_start_conflict`；**形态判据先于等值判据，任一形态失败即跳过整个 conflict 组**（`exemption_start_conflict` 及其 `detail` 分支 `moved_from_chain_mismatch` / `chain_head_missing` 一并跳过，v24/B-1；v25/次要 1）。**一个输入只出一个码**，不得把 `signed_at_not_canonical` 当 `detail` 值 | T-28(a)、T-29 | 1 / `errors[]` | 否 |
    | `exemption_start_conflict` | `exemption_started_at` 与当前 `L[0].signed_at` **不逐字节相等**（含被 `lock --update` 刷新 / 后移、重锚后未同步、首写写晚）；或带 `moved_from` 的新键未沿 `moved_from` 递归到链首、或与链首键的值不等（中途缺键先报 `seal_anchor_path_unmapped`）。`detail.kind ∈ {not_equal_signed_at, moved_from_chain_mismatch, chain_head_missing}`，**不得**把主码塞进 `detail`（v22/I-3；v27/次要 1 统一为 `detail.kind`）。**与 `exemption_start_signed_at_not_canonical` 的分工（v23/B-1）**：本码只管**等值**，形态不归本码 | T-28(b)(c) | 1 / `errors[]` | 否 |
    | `exemption_start_history_broken` | `exemption_start_history[]` 断裂，按下列任一：(a) **版本前缀单调**被破坏——某后版本数组不是**紧邻前一版本**的**前缀扩展**（v28/B-1：不得放宽为「某前版本」，否则 `[] → [x] → []` 会假绿）、单版本新增超过一项、删项 / 改项 / 重排、相邻版本不连续（v23/I-1 第 2 条）；(b) 第 i 项 `from` ≠ 第 i-1 项 `to`、首项 `from` ≠ `exemption_start_origin`、末项 `to` ≠ 当前 `exemption_started_at`；(c) `exemption_started_at` 被重指而数组未 append；(d) `exemption_start_origin > exemption_started_at`（v23/I-3） | §1.1.3 键表、T-28 变体、S-55 | 1 / `errors[]` | 否 |
    | `exemption_start_origin_rewritten` | `exemption_start_origin` 的当前值与**锁历史锚**不等——取法见 §1.1.3「资产根」⑦（`git log -m --full-history --reverse HEAD -- atlas.solution.lock.json`，**首个同时含该字段的版本**即锚；存量键顺延到回填提交）。存量缺字段不算 rewritten（走一次性回填）。v23/I-1；v24/B-2 | §1.1.3「资产根」⑦、T-30 | 1 / `errors[]` | 否 |
    | `first_seen_origin_rewritten` | `first_seen_origin` 的当前值与**锁历史锚**不等——取法与 `exemption_start_origin_rewritten` 同一口径（§1.1.3「资产根」⑦ 标量类；**首个同时含该字段的版本**，存量键顺延到回填提交）。存量缺字段不算 rewritten（走一次性回填）。**v25/I-4 扩一条触发条件**：`first_seen_origin > L[0].signed_at`（**时间戳层**比较）也报本码，`detail.kind ∈ {rewritten, after_signed_at, not_canonical}` 区分成因（`not_canonical` = 非 `YYYY-MM-DDTHH:MM:SSZ` 形态，v26/S-9：`first_seen_at` 载荷无规范形态条款、`load_lock_strict` 不解析 `seal_anchors`，不得直接与 `L[0].signed_at` 做字符串比较）。v23/I-1；v24/B-2；v26/S-9 | §1.1.3「资产根」⑦、T-30（含 ⑥） | 1 / `errors[]` | 否 |
    | `exemption_due_out_of_range` | `gap.due` **不在闭区间** `[exemption_start_origin, min(trunc_utc_date(first_seen_origin) + 90d, acceptance_cutover)]` 内，或 `exemption_start_origin > due`（存量回填 `origin = 当前 exemption_started_at` 而 `started_at` 被 reanchor 重指过时会造出此态）。**比较全在日期层（v25/I-2；v26/I-2 单源）**：`due` 一律 `YYYY-MM-DD`；下界取 `origin` 的 UTC 日期部分；上界先把 `first_seen_origin` 截到 UTC 日期得 `d`，再 `min(d + 90d, acceptance_cutover)`（**先截日期再加 90 天**，全程 `date`）；两端都含。**读侧一律报本码**（写侧另有 T-03 / S-08 拒签）；`path` 指封条。**出口**：续签一枚新封条把 `due` 改回区间内即恢复 PASS，不是无出口的永久红。v24/I-3；v25/I-2 | §5.1 第 3 条、T-32 | 1 / `errors[]` | 否 |
    | `migration_required` | 存量可迁移缺口，**WARN、`exit 0`、不计入 `errors[]`**（历史表 `:415` 只留了语义，这里是表项落点）：`detail.kind` **必填**、三值 `legacy_member_name` / `missing_acceptance_cutover` / `missing_first_seen_origin`；消费方按 `kind` 分支，不得只按 `code` 聚合 | §1.1.3 第 2 条⑤、§5.1、§8 | 0 / `warnings[]` | 否（WARN 本身不可降级） |
    | `lock_tracked_but_deleted` | **v30/S-2**：锁文件不在工作树，但 Git 记录里曾有 / 仍有该路径——`git cat-file -e HEAD:atlas.solution.lock.json` 成功（HEAD 有、工作树被 `rm`）、`git ls-files --error-unmatch -- atlas.solution.lock.json` 成功（index 仍有）、或 `git log -m --full-history --format=%H HEAD -- atlas.solution.lock.json` 非空（已提交删除）。与 `lock_missing`（三者全空、从未有锁，B-0 尚未产锁的正常态，只跳过 ⓪-0 与两条根断言）**互斥**；本码 **FAIL、`exit 1`、`errors[]` 只含该码、短路**，`message` 写明「已跟踪的锁被删除（篡改信号）」；`path` = `atlas.solution.lock.json`；**不发 INFO `lock_history_empty`**。**限定（v31/S-1）**：只在**工作树无锁且 HEAD 无该路径**（已提交删除 / 工作树 `rm`）时触发；「删 → 重建」重建后 HEAD 有锁 ⇒ 前置不成立、本码不触发，由 ⓪-3 `assets_root_history_rewritten` 报。**短路报告（v31/S-2）**：`not_run[]` **六段全进**、`errors[]` 只含本码、`warnings[]` / `skipped[]` 照常输出 | §3.2 ⓪-0/⓪-1、报告 schema `not_run[]`、§5.2 | 1 / `errors[]` | 否 |
    | `lock_history_empty` | **INFO 级（v28/I-2；v29/B-2 补互斥；v30/S-2 拆 `lock_tracked_but_deleted`）**：`git log -m --full-history HEAD -- atlas.solution.lock.json` 返空（锁**未跟踪** / 尚未提交），`check_history_prefix` 收到 `versions == []` 并返回 `Ok`；**只作可见性提示，不进 `errors[]` / `warnings[]`、不改 exit code、不计 FAIL**；`path` = `atlas.solution.lock.json`。**触发前提是锁文件存在**：文件不存在 ⇒ `lock_missing`（从未跟踪，只跳过 ⓪-0 与两条根断言）/ `lock_tracked_but_deleted`（已跟踪被删，短路），**均不发本码**；也**不覆盖**「文件存在但不可解析」（`lock_unparsable`）与「历史版本不可解析」（`lock_history_unparsable`） | §1.1.3 ⑦ 数组 C、§3.2 报告 schema `info[]`、§6 B-0 夹具、§8 | 0 / `info[]` | 否（INFO 不是错误） |
    | `internal_error` | 三类自有异常（`LockParseError` / `LockHistoryUnparsable` / `ChainUnverifiable`）与 `SolutionError` **之外**的未知异常；`message` = 异常类型 + 首行、`path: null`。**不得吞 `SolutionError`、不得吞用法错误**（v22/I-4，处理顺序见 §3.2 报告 schema）；`not_run[]` 按已跑游标填剩余段（v22/次要 3） | §3.2 报告 schema | 2 / `errors[]` | 否 |
    | `contract_ac_table_missing` | **D 批**：`prd_schema: 2` 且该域被引用，但 PRD 里找不到含 `契约AC` 表头的 §五-b 表（v41） | §1.5 第 7 条 | 1 / `errors[]` | 否 |
    | `contract_ac_undefined` | **D 批（E-04）**：任务卡 / 封条投影 / `requirements[].acs` 引用 `AC-CONTRACT-*`，但 §五-b 表无该行（v41） | §1.5 第 7 条、E-04 | 1 / `errors[]` | 否 |
    | `contract_ac_orphan` | **D 批**：§五-b 行的 `关联AC` 不在同 PRD §五 AC 表（v41） | §1.5 第 7 条 | 1 / `errors[]` | 否 |
    | `contract_ac_in_member_slot` | **D 批（v43/阻断 3）**：`AC-CONTRACT-*` 出现在 `成员AC` / 成员 PRD 的 AC 表（契约 AC 不得占成员 AC 位置） | §1.5 第 7 条 | 1 / `errors[]` | 否 |
    | `crosswalk_unresolvable` | **D 批（v43/阻断 4）**：`<assets_root>/prd/ac-crosswalk.md` 缺失 / 不可读；**抑制 C-01…C-11**（含 C-09；只报本码），不可降级 | §2.1 | 1 / `errors[]` | 否 |
    | `crosswalk_parse_error` | **D 批（v44/重要 8；v45 补抑制）**：crosswalk 能读但坏行；`detail.kind ∈ {header_missing, column_count, ac_format, prd_path, member_field_empty}`；**抑制 `C-01…C-11`（含 C-09；只报本码）**；不可降级；与 `crosswalk_unresolvable`（缺失/不可读）互斥 | §2.1 | 1 / `errors[]` | 否 |
    | `member_domain_mismatch` | **D 批（v43/阻断 4 / C-11）**：成员 PRD front matter `domain` 与 crosswalk `成员` 不符 | §2.1、C-11 | 1 / `errors[]` | 否 |
    | `confirmed_columns_missing` | **C 批**：任务卡 `Confirmed` / `确认口径` 小节缺表或缺 `确认项` / `证据状态` 列；`prd_schema: 2` 立即 FAIL，`1` 存量 WARN 至 2027-06-30（v41） | §1.5 第 8 条 | 1 / `errors[]` | 否 |
    | `confirmed_evidence_missing` | **C 批**：`证据状态 = verified` 但 `证据指针` 为空；或 `assumed` 无默认值来源指针（v41） | §1.5 第 8 条、K-20 | 1 / `errors[]` | 否 |
    | `confirmed_unverified` | **C 批**：`证据状态 = unverified`，**WARN**（exit 0、`warnings[]`），不阻断；**该行已带 `confirmed_review:` 时不报**（与 `confirmed_downgrade_unreviewed` 互斥，v44） | §1.5 第 8 条、K-21 | 0 / `warnings[]` | 否 |
    | `manifest_digest_removed` | **B-0（v42；v43 补 `detail`）**：锁历史曾含非 null 摘要键，当前锁缺该键或为 `null`（删键绕过）；`detail.field ∈ {requirements_digest, waiver_baseline_digest}`；**被 `manifest_rollback` 抑制** | §1.1 8-b | 1 / `errors[]` | 否 |
    | `manifest_rollback` | **B-0（v42；v43 收窄）**：**仅**当前 `definition.prd_version` < 锁历史最大 `prd_version`（内容回滚不判）；`detail.prd_version = {current, max}`；**优先并抑制** `manifest_digest_removed` / `waiver_baseline_drift` | §1.1 8-b | 1 / `errors[]` | 否 |
    | `waiver_baseline_drift` | **C 批（v42/重要 3）**：`waiver_baseline_digest` 与当前可豁免集合重算值不等（纯摘要比对、不依赖 crosswalk；基线 `null` 时不判）；`detail.field = waiver_baseline_digest` | §1.1 8-b | 1 / `errors[]` | 否 |
    | `seal_upstream_unbound` | **D 批（v42/重要 2）**：按清单推导的 `prd-domain` / `ac-crosswalk` role 未出现在封条 `upstream[]`；**D 批首版 + 90d**（常量 `SEAL_UPSTREAM_BIND_FROM`）前 WARN、到期 FAIL；`state=frozen` **永久 WARN**（不阻断、不可 `--strict` 升级） | §2.5 | 非 frozen：期内 0 / `warnings[]`、到期 1 / `errors[]`；frozen：恒 0 / `warnings[]`（不阻断、不可 `--strict` 升级） | 否 |
    | `confirmed_downgrade_unreviewed` | **C 批（v42/重要 4；v44 收窄）**：**仅 `unverified` 行**缺 `confirmed_review:`（`REVIEW-\d{8}-\d{2}`）⇒ FAIL；`assumed` 不要求（只要求默认值来源指针） | §1.5 第 8 条 | 1 / `errors[]` | 否 |
    - **`signed_at_not_canonical` 的写侧单源与校验范围（v21/I-3；v22/I-2 改范围）**：写侧封条装配只允许 `datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`，**禁止 `isoformat()`**；续签**重写** `signed_at`（新封条自己的签署时刻），**只有换路径（`moved_from`）沿用旧值时逐字节复制**。**校验范围改为「链上每枚封条 blob」**：读侧沿 `previous_seal_commit` 从 HEAD 逐级取 blob（含 `L[0]` 那枚），对每枚封条的 `signed_at` 逐字节判形态——**不是「当前锁 `L` 的全量封条」**（`L` 是封条**提交**序列，不是锁里的字段；中间续签若要改必须重写历史，`previous_seal_commit` / `blob@L[0]` 会先红，见 §7 T-29）。**不设 grandfathering**：C 批尚未上线、HEAD 里不存在任何已入库的 `*.seal.json`，规则生效即 fail-closed。
    - **`review_reused`**：同一个 `REVIEW-ID` 被用于两个不同决策（改根 + 改 cutover），判定见 §5.1「review 是自述」。
    - 以上码全部补进报告 `errors[]` / `warnings[]` 的 `code` 取值集（§3.2 机读 schema），并与已有码同规则：`path` 指向封条或清单文件，`message` 一行可读。
    - **exit 的唯一分层（v32/I-4）**：⓪ 层（`lock_unparsable` / `lock_history_unparsable` / `lock_tracked_but_deleted` / `chain_unverifiable`）**一律 exit 1**；`definition_source` 层与 ①②③ 的 FAIL 也是 `1`；**exit 2 只有两类**——**用法错误（含 `manifest_*` 等构造前出口；不进报告、首行人类可读）**与 `internal_error`（`--json` 时仍输出合法 JSON）。**`internal_error` 的作用域（v37/重要 1）**：**exit 2 + 合法 JSON + `not_run` 六段**仅限 `check` 命令**（`scripts/atlas_solution.py:240-263`，包装 `:369-370`）；**其余命令的未知异常仍走 CLI 兜底 `[ERROR]` → `return 1`、不产 JSON**（`:577-579`）——因为其它命令不产报告对象、没有 `not_run[]` 可承载，这不是「第二条 exit 2」。实现对应 `return 1 if overall == "FAIL" else 0`（`scripts/atlas_solution.py:354`）。码表里 `2` 字面只出现在这两类下（`manifest_schema_unsupported` 归入用法错误，**不是第三类**，v35/次要 1）；若将来确需某码为 2，必须在此处写明理由并同步 `errors[]` 口径，不得留两套。**exit 2 无 JSON 的通则（v34/次要 4）**：**凡在报告对象构造之前退出的 exit 2 出口，一律不产 JSON**——用法错误、`manifest_schema_unsupported`、`reader_version_unknown` 的 `init` 等，只有 stderr 文本（消费方按 stdout 首字符区分）；**唯一例外是报告对象已构造后的 `internal_error`**（`--json` 时仍输出合法 JSON，T-31 已钉死）。§3.2「短路也要有报告」只约束**有报告对象**的出口，与本通则不矛盾。**用法错误的当前实例**：`init --cutover` 在 `reader_version < 0.4.0` 下 ⇒ 无错误码、exit 2、stderr、不写任何文件（V-22）。
    - **`migration_required` 同名不同 `kind`（v25/次要 5）**：本码至少三处使用——① 存量成员名含 `/`（§1.1.3 第 2 条⑤）；② v1 清单缺 `acceptance_cutover`（§5.1）；③ 缺 `first_seen_origin` 导致 `due` 上界只跳过 `first_seen_origin + 90d` 一支（§5.1 第 3 条）。**`detail.kind` 必填**（`legacy_member_name` / `missing_acceptance_cutover` / `missing_first_seen_origin`），消费方须按 `kind` 分支，不得只按 `code` 聚合。

### 5.3 三个版本号不一致时以谁为准

| 载体 | 管什么 | 不一致 |
|---|---|---|
| 清单 `version` | 清单 schema | 旧工具读 v2 ⇒ 硬拒（响亮）；0.4.0 读 v1 ⇒ 硬拒 |
| 封条 `schema_version` | 封条 schema | 新工具不认识 ⇒ FAIL；旧工具不读 ⇒ 无门 |
| `.atlas/VERSION` | 工具/装配副本 semver（`reader_version`） | 缺失或非 semver ⇒ 依次回落 `.atlas/package.json` → `<工具包根>/package.json`；只有三者都缺 ⇒ `reader_version_unknown`：`check` **WARN**（I6/v9；v12 对齐实现），`init` **exit 2 不写盘**（v13/B 批前置，见 §5.2 第 8 条） |
| `.atlas/DIGEST` | 装配副本摘要 | 不参与门；只用于 `install --update` 覆盖提示 |

**三处版本号的关系（I6/v9）**：`.atlas/VERSION` 是 B 批才拆出来的（§5.2 第 1/2 条、§6 的 B 批文件表）；B-0 阶段它**尚不存在**，而 #54 的检查 B-0 就上线，所以不能把「无 `VERSION`」直接判红。回落链固定为三级：

1. `.atlas/VERSION`（装配副本，权威）；
2. **安装副本**的 `.atlas/package.json` 的 `version`（B 批 `install.py` 随包写入）；
3. **工具包根**的 `package.json` 的 `version`（`Path(atlas_package_root)/package.json`；源码树/开发树）——**不是**被检查仓的 `<root>/package.json`（v11/重要 3）。

> v12：以上三级与 `validators/validate_e2e_index.py:104-125` 的现有实现完全一致；**原第三级 `_support/_version.py` 取消**（那是 RFC 虚构的落点，现有代码第三级就是工具包根 `package.json`；两套并存会让 V-05 与夹具各测一个「第三级」）。

**中间级不可解析只记一条 `downgrades[]` 并继续回落**（v11/重要 4），最终版本仍可能由下一级确定；只有**三级都拿不到**才作为最终状态记 `reader_version_unknown`。此时 reader **无从知道自己是不是 0.4.0**，因此 `check` 一律 **WARN**（不是 0.4.0 FAIL——那是自指：要判 0.4.0 失败，必须先从某个来源知道自己是 0.4.0，而来源已全部缺失）。固定提示：`[WARN] reader_version_unknown：缺少 .atlas/VERSION、.atlas/package.json 与工具包 package.json 的 version`。**`init` 是例外，必须 fail-closed（v13/第十二轮 B 批前置）**：它要写清单、且写下去不可回退，无法判断 0.3.x / 0.4.0 时不得默认写 v1 ⇒ **exit 2，不写任何文件**（§5.2 第 8 条、V-18）。

### 5.4 七小节承诺

- `atlas-apply.md` 七小节不变（`apply/reference.md:264-270`；`docs/map/apply.md:61`）。
- 机器可读表只在第 4 小节内部；封条独立文件；不改对外承诺。

## 6. 实施分批（串行）

> 只改 `_support/solution*.py`、`scripts/`、`validators/`、`shared/solution.md`、模板与测试；本 RFC 不实现。A 批已单独开工，批次表按现状同步（I8）。
>
> **第六轮结论：B-0 / B / C / D 全部暂不开。** 下表只是返工后的实施顺序，不是开工许可；下一轮评审前不改实现。

### 批次 A：只读判据 + 多值消费点（已开工）

- 文件：`validators/validate_e2e_index.py`（§1.6 的 9 个点 + 第二落点）、`_support/solution_e2e.py`（只改 `:361-362` 的 split，不动 `:350` 的路径）、`scripts/e2e_console.py`（`:748`）、`shared/solution.md`、`rings/e2e/reference.md`、`templates/e2e/e2e-index.md`、`tests/test_e2e_index_gates.py`、`tests/test_solution_e2e_validators.py`。
- **A 批不做**：不读 v2 清单、不碰 `definition.path`、不改 `_ac_prd` / `_pointer` / `_prd_skeletons` / `check_solution` 骨架检查。
- 夹具：多值第二 token 未定义（M-02）、`:976-979` 跳过回归（M-03）、单值存量逐字节（M-01）、任务目录 `cases.md`（M-06 的 `E2E-*` 子集）。
- 依赖：无。

### 批次 B-0：解析器 + 版本门 + 迁移出口 + 开关退役点（0.3.x 发布点，P-1/P-3/P-4/P-5/Q-5）

- 文件：
  - **状态口径（v38/重要）**：每行逐项标「**已落地 / 待实现 / 部分已落地**」，**不允许整行兜底**；未逐项核过的子项按「待实现」计。判定以测试或实测行号为准，不以「看起来像」为准。
  - **状态：部分已落地**——`_support/solution.py`（`parse_manifest_text` 一层嵌套映射 + 标量白名单；**已落地**：review 三写侧（`:328` / `:1480` + `:1496-1498` / `:1314-1315`）与 `acceptance_cutover_review_malformed`（`:433`、`:436-450`、`:2300-2307`）；**待实现**：`acceptance_cutover_unreviewed`、`build_lock_versions`、`check_history_prefix`、`path_at`、`lock_unparsable` / `lock_history_unparsable` / `LockParseError`；`validate_manifest` 版本门 `{1,2}`，**并含 `acceptance_cutover` 取值校验与 review 谓词（v22/I-5）**——`acceptance_cutover` 必须是 `YYYY-MM-DD` 真实日期、`≤ 默认 + 90 天`；晚于默认而 `acceptance_cutover_review` 为空 ⇒ `acceptance_cutover_unreviewed` FAIL，非空则形态必须是 `REVIEW-\d{8}-\d{2}`——形态不符时**读侧**报 `acceptance_cutover_review_malformed` FAIL / exit 1（进 `errors[]`），**写侧** `--anchor-review` 形态不符属用法错误 / exit 2（见 §5.2 第 8 条与 V-23d，v35/重要 1）；这是 V-20⑥ 的 B-0 落点，不必等 B 批（运行期 WARN 文案见 P-4 行的 `:2229-2230`））；**并新增两个同级纯函数（v32/I-2）**：① `build_lock_versions(commits, fetch, worktree, head_has_path) -> list[list[Entry]]`——`versions` 构造本体（历史层 `fetch(c) is None` ⇒ **跳过、不记 `[]`**；工作树层仅当 `head_has_path` 且字节与 HEAD 不同才追加；`-m` 多父 `%H` 去重是构造层清理、不产生判据），并承担 §1.1.3 ⑦ 数组 C 的输入边界（缺键 ⇒ `[]`、`seal_anchors` 为 `null` / 非 dict ⇒ `[]`，**均不抛异常**）；零 git 依赖，夹具喂假 SHA 与假 `fetch`；② `check_history_prefix(versions) -> Ok | Err(code, detail)`——只判「紧邻前一版本」的前缀单调，不碰 git、不做构造。T-33 的建面归属即这两条；
  - **状态：已落地**——**`_support/layout.py`（v21/B-3，新增进表；`_validate_rel_path(lexical=)` 见 `_support/layout.py:291-335`）**：`_validate_rel_path(..., lexical=False)` 新增参数（`lexical=True` 时**零 FS 访问**，只做 strip / 绝对路径 / 空段 / `.` / `..` / 保留首段 / 字符规则；默认 `False` 保留 `candidate.resolve()` + `relative_to()` 的 FS 检查）、`validate_value` 透传该参数、**首尾空白在 `raw = value.strip()` 之前先判 `value != value.strip()` 直接拒**（v21/I-1：现在 `layout.py:293` 的 `strip()` 会把两层都静默归一化，写侧因此没拒）。**这是 B-0 的交付物，不是「顺手改」**：干净基线 `411c971` 上 `validate_value(..., lexical=True)` 会抛 `TypeError`，S-51 与 ⓪-3 依赖它；
  - **状态：部分已落地**——`scripts/atlas_solution.py`（`migrate --to 2 --definition-path --check-members` 含落盘前白名单校验；**已落地**：`migrate --cutover/--anchor-review`、T-31 的 `_internal_error_report` / `_emit_internal_error`（`:240-263`，包装 `:369-370`）；**待实现**：报告 schema v2 出口（判据见 §5.2 报告 schema）**新增 `--cutover <date>` / `--anchor-review <REVIEW-ID>`（v19/阻断 2）：默认 `2027-03-31` 并 stdout 打印，晚于默认必须带 review 且 ≤ 默认 + 90 天**；`_allow_dangling_acs_enabled` 谓词改 `< 0.4.0`）；
  - **状态：已落地**——`install.py`（v1 + 来包 ≥0.4.0 拒绝刷新并打印命令；`install.py:222-253`，`:24` / `:363` 的注释与调用点一致）；
  - **P-4 五处落点（重要 1；逐项状态）**：`shared/solution.md:73` / `:84`、`docs/guide/changelog.md:14`、`tests/test_atlas_solution.py:972-978` —— **待实现**；`_support/solution.py:2229-2230`（运行期 WARN「`--allow-dangling-acs` 将于 0.4.0 移除」）—— **已落地**（**v38/v39 更正**：行号以本行为准）；`duty-review/QUEUE.md:44` 与 `duty-review/bugs.md:62` —— **待实现**（只新增 `[Unreleased]` 更正条，不改旧条，§10 例外）；
  - **状态：已落地**——`validators/validate_e2e_index.py`（#54 放宽：任意用例行 + 成员任务目录 + archive 扫描，0.3.x WARN / 0.4.0 FAIL）：`archive/<month>/` 扫描（docstring `:163`、扫描 `:781`）、**任意用例行放宽**（只要有 用例行 即报 `task_dir_case_duplicate`，不看 ID 前缀）、**成员任务目录**、**0.3.x WARN / 0.4.0 FAIL**（分级判定 `:821`；`:816` 是 `reader_version_unknown` 提示，v40 更正）均**已落地**，证据 `:782-823`（v39/重要 3 翻正；未发现未实现子项）。
  - **状态：待实现**——**`shared/gates.md`（v33/重要 1 附带，新增进表；三个测试文件未建、三行登记未写）**：两个纯函数夹具必须登记进该表（表元规则是「不在本表 = 不存在」，全仓当前命中 0）——`tests/test_solution_versions.py` 对应 `build_lock_versions`、`tests/test_solution_history_prefix.py` 对应 `check_history_prefix`，文件名固定为这两个（实现若合并到一个文件，必须在表里写实际文件名并注明两函数同文件）。每行各附一条**「喂坏输入必红」的假绿证明**：① `test_solution_versions.py`——喂 `c1`/`c2` 有锁、`c3` 已删除，断言 `len(versions) == 2`；若实现把无文件版本记成 `[]`（或把删除提交记成空版本），长度变 3 ⇒ 断言红；② `test_solution_history_prefix.py`——喂 `[a] → [a,b] → [a]`，断言 `Err("exemption_start_history_broken")`；若按「某前版本」实现（`[a]` 是 `[a]` 的前缀）⇒ 返回 `Ok` ⇒ 断言红。两行都要求可执行、给出文件名，不接受「需登记」这类占位。**另加 `tests/test_path_at_single_source.py`（v34/重要 4）**：用 monkeypatch 给 `_run_git` 计数或做静态引用断言，证明 `build_lock_versions.fetch` 与 ⓪-1 根集循环调用的是同一个 `path_at`；并配 **V-24** 的 symlink / tree / 浅仓三洞断言（对应重要 3）。
  - **状态：已落地**——**`acceptance_cutover_review` 的三处写侧（v34/阻断 2，属 B-0，不是 C 批）**：① `parse_manifest_text` 标量白名单必须含该键（`_support/solution.py:328`；工作树已出现，**夹具仍须覆盖以防回退**）；② `_manifest_text` 增 `acceptance_cutover_review` 参数，非空时写同名行（`:1480`、写行 `:1496-1498`）；③ `lock_payload` 在 review 非空时写同名键（`:1314-1315`）。三处各配夹具 **V-23a…V-23f**（v35 补 d/e/f：写侧坏值 exit 2 / 读侧坏值 `acceptance_cutover_review_malformed` / 已有 review 不同拒覆盖 / v1 下 `--anchor-review` 拒绝）：**V-23a** 清单 round-trip（该键可取、空值不写行）、**V-23b** `migrate --to 2 --anchor-review <ID>` 落盘（清单含该键、`check` 不再 `manifest_field_unknown`、显式 review 不落盘即 exit 2；实现见 `:1888-1896`）、**V-23c** `lock --update` 后锁含 `acceptance_cutover_review` 且与清单同值（review 为空时不写键）。**③b 与 V-20③ 依赖这三行，缺一行即必红。**
- **完成判据（v37/阻断；B-0 唯一验收门）**：以下各项**全绿**才算 B-0 完成，任一项缺失**不得宣告完成**，也不得以「其余已绿」代替：
  1. `acceptance_cutover_unreviewed` 与 `acceptance_cutover_review_malformed` **同批实现**，且 V-20⑥ / V-23d 绿（先空后形态、两码互斥）；
  2. `build_lock_versions` / `check_history_prefix` / `path_at` 三个纯函数存在，且 `tests/test_solution_versions.py` / `tests/test_solution_history_prefix.py` / `tests/test_path_at_single_source.py` **已建并登记进 `shared/gates.md`**（三行，各带假绿证明）；
  3. ⓪ 层 `lock_unparsable` / `lock_history_unparsable` / `LockParseError` 存在，且 `non_blob` 的映射符合 §1.1.3 ⑦；
  4. 报告 schema v2 出口落地（判据见 §5.2 报告 schema：`schema_version: 2` + 五数组 + 排序键）；
  5. **文件表所有「待实现」行归零**，逐行给出证据——包括：`shared/gates.md`（三个测试文件 + 三行登记）；P-4 六条待实现（`shared/solution.md:73` / `:84`、`docs/guide/changelog.md:14`、`tests/test_atlas_solution.py:972-978`、`duty-review/QUEUE.md:44`、`duty-review/bugs.md:62`）；`_support/solution.py` 的 7 项（`acceptance_cutover_unreviewed`、`build_lock_versions`、`check_history_prefix`、`path_at`、`lock_unparsable` / `lock_history_unparsable` / `LockParseError`）；`scripts/atlas_solution.py` 的 schema v2 出口。`install.py` 已落地（`install.py:222-253`），**不计欠账**。同时既有 B-0 夹具（V-07 / V-10 / V-14 / V-15 / V-20 / V-23 / V-24 / T-33 / S-51 / S-52⑤）全绿。
  **上述任一项缺失，B-0 不得宣告完成**；通过验收时必须逐项给出证据（命令 / 测试名 / 输出行）。
- 夹具：v2 清单 round-trip——`definition.domain` / `definition.path` / `acceptance_cutover` / `min_atlas` 全部可取，`definition: null` 不落 `unknown`（`_scalar` → `yaml_scalar` 已把 `"null"` 归一成 `None`，`_support/solution.py:102-104`），`unknown == []`；`definition` 未知子键 ⇒ `definition_field_unknown` FAIL；`migrate --to 2` 只补缺、二次执行 diff 为空；**`migrate --to 2` 后 `atlas.solution.lock.json` 字节不变（不自动 lock），PRD 工作树脏时 `lock --update` 非零退出（V-07 加强，v10/B-0 补）**；**全链路的可验形态（V-14，v32/B-1 改为读侧门断言、不启动第二份二进制）**：`init` 在同一次装配里先写 v1、再 `migrate --to 2`，然后直接调 `validate_manifest(data, root, phase1, reader_version)` 喂两个读者版本——`0.3.x` 门接受 `{1,2}`、`0.4.0` 门只接受 `{2}`；断言迁移前的 v1 在 `0.4.0` 门下被拒 `manifest_schema_unsupported`、迁移后的 v2 在 `0.4.0` 门下 PASS。**「用哪个二进制跑」不是可执行前提**（全仓单 `package.json`，没有获取两个版本的机制），判据是读侧门接受集；**v2 缺 `definition` 可由 `migrate --to 2` 自愈（V-15；可用性由注册谓词 `semver_lt(reader_version, "0.4.0")` 判定，v32/B-1 改断言谓词而非「换二进制」）**；多份 `*-prd.md` 无 `--definition-path` ⇒ 拒绝并列出候选；B-0 自动探测到非默认名（`product/prd/auth-prd.md`）⇒ **拒绝且不写文件**（V-12）；`migrate --check-members` 逐成员按实际路径打印 `git add -f` 命令，**active 与 archive 各一条**（I3）；B-0 的 `migrate` + `lock --update` 不 `SolutionError`，**清单 v2 ⇒ 锁写 `schema_version: 2`**（v32/B-2，与 V-10 同一断言）；`0.3.0` 注册 `--allow-dangling-acs`、`0.4.0` 不注册（V-11）；v1 + 0.4.0 来包 ⇒ `install --update` 拒绝；仅有锁的 fresh clone 跑 `--lenient` 可用（U-09）；#54 任意用例行命中（M-06）；**V-20（v21/I-4：从 C 批移入 B-0，含六分支；v31/S-3 补第七支）：`migrate --to 2` 无 `--cutover` ⇒ 清单写 `2027-03-31` 且 stdout 含 `acceptance_cutover=2027-03-31（可用 --cutover 覆盖）`；`--cutover 2027-05-15`（晚于默认、在上限内）无 `--anchor-review` ⇒ exit 2；同值带 review ⇒ 写 `acceptance_cutover_review` 且 PASS；`--cutover 2027-06-30`（唯一超限反例）带 review 也 exit 2；`--cutover 2027-06-29`（等于 `date(2027,3,31) + timedelta(days=90)`）带 review ⇒ PASS（等于上限算通过）；首次写入晚于默认而 review 为空 ⇒ `acceptance_cutover_unreviewed` FAIL（`detail.kind = "review_missing"`）；**⑦（v31/S-3）`--cutover 2027-01-31`（早于包级默认、属收紧）⇒ PASS、不要求 `--anchor-review`，清单写 `2027-01-31`**（T-32③a/③b 第①步全靠「收紧无需 review」这条规则，B-0 必须有夹具）；显式给了 `--anchor-review` ⇒ **照写该键（显式给了就落盘，不设 `ignored` 第三态）**（v35/口径裁定）**；**S-54-B0（v21/I-4 拆半）：只用清单 / 首次锁字段构造「同一 `REVIEW-ID` 出现于 `assets_root_history[].review` 与 `acceptance_cutover_review` 两个决策类别」⇒ `review_reused` FAIL；不依赖 C 批的 `lock --update --assets-root`，也不要求仓里真有改根动作**。（**V-13/V-16 已移出 B-0**：它们背书的是 0.4.0 `init` 写 v2，属 B 批行为。**T-33（v25/I-1；v26/S-10 从 C 批移入 B-0；v26/I-1 挂 §1.1.3 ⑦ 的 `check_history_prefix` 签名；v28/I-3 补四边界；v29/I-1 删去重断言）：`exemption_start_history[]` 前缀单调的纯函数单测——合成 `versions` 直接喂 `check_history_prefix(versions)`：① 合法递增（`[] → [x] → [x,y]`）⇒ `Ok`；② **紧邻前一版本**不是后版本前缀（`[a] → []` 整段删空、`[a] → [a,b] → [a]` 回滚、改项、单版新增两项）⇒ `Err("exemption_start_history_broken", ...)`；③ **四边界**：`versions == []` ⇒ `Ok`、单版本 ⇒ `Ok`、缺键 ⇒ 记 `[]`、`seal_anchors` 为 `null` / 非 dict ⇒ 记 `[]` 且**不抛异常**；④ **无锁历史**：`versions == []` ⇒ `Ok`（`lock_history_empty` 的 CLI 面另由「锁未跟踪」用例断言，不在本纯函数夹具内）。零 git / 零依赖、不走 CLI，是 B-0 唯一能验证前缀单调的夹具**。**去重不进本夹具（v29/I-1）**：函数签名里没有 SHA，喂 `[[x],[x]]` 时去重与不去重都返回 `Ok`、断言无法区分，且重复项本身不改变判定；`-m` 多父重复的 `%H` 去重是**构造层清理动作、不产生判据**，若要覆盖就测 `check` 的版本序列构造，不进纯函数夹具；**另补 B-0 可验项（v27/I-3）**：① **S-52⑤ 写侧不 trim**——`install.py --assets-root " product"` / `"product "` 均**拒绝**（非零退出），不得 `strip` 后静默接受（当前 `layout.py:293` 的 `raw = value.strip()` 会 ACCEPT；B-0 交付改为先判 `value != value.strip()`）；② **S-51 的 B-0 可验部分**——`_root_by_index_ok` 的**分层**（历史根只做词法校验，`lexical=True` **零 FS 访问**）：`hist == []` ⇒ 返回 `False`、不抛 `IndexError`（v20/次要 4）；`_validate_rel_path(..., lexical=True)` 对**已删除 / 指向仓外的 symlink / 普通文件**的历史根都不因当前工作树判红（三变体的 CLI 面留 C 批）；③ **锁未跟踪 / 未提交**：`git log` 返空、工作树有锁、**HEAD 无该路径 ⇒ 不追加工作树版（`versions == []`）** ⇒ 发 INFO `lock_history_empty`（`info[]`）、`errors[]` 为空、exit 0，不得静默无输出（v28/I-2；v29/B-2）；**对照：锁文件从未跟踪（`git log` / `git cat-file -e HEAD:path` / `git ls-files --error-unmatch` 三者全空）且工作树无锁 ⇒ `lock_missing`（只跳过 ⓪-0 与两条根断言）、不发 `lock_history_empty`；已跟踪后被删（三条件任一成立）⇒ `lock_tracked_but_deleted` FAIL、exit 1、`errors[]` 单码短路，不得落 `lock_missing` 的跳过分支（v30/S-2）**。**另补 `versions` 构造的纯函数夹具（v30/B-1；v32/I-2 提成 B-0 独立函数）**：`build_lock_versions(commits, fetch, worktree, head_has_path)` 与 `check_history_prefix` 同级、进 B-0 文件表，零 git 依赖（`fetch` 返回 `None` 表示该提交无该路径，对应 `git cat-file -t` 失败）。夹具喂「三个 SHA 的假对象，其中 c3 无文件」⇒ 断言 `versions` **恰两版**、**不产生 `[]` 空版本**；再喂「HEAD 无该路径 + 工作树有锁」⇒ `versions == []`（不追加工作树版）。**再补「删后原样重建 ⇒ `Ok`」（v33/次要 3）**：喂 `c1` 有锁、`c2` 删除、`c3` 内容与 `c1` **逐字节相同** ⇒ `versions` **恰两版**（删除提交被跳过）、`check_history_prefix(versions) == Ok`；若实现把删除提交记成 `[]`、或把 `c3` 记成空版本，长度/返回值即断言红。该夹具只覆盖纯函数层；`HEAD 有锁 ⇒ 哨兵不触发`、`根历史不变 ⇒ ⓪-3 不红` 由 §3.2 链规则 1 的规则正文与既有哨兵/根夹具共同约住（CLI 面在本条不重复构造）。CLI 层（c1 写锁 → c2 改锁 → c3 `git rm atlas.solution.lock.json` 并提交）不再由本夹具断言：该 HEAD 上 `check` 被哨兵 `lock_tracked_but_deleted`（exit 1，单码短路）在 ⓪-0 截住，`versions` 根本走不到——这正是把构造提成纯函数的原因。**（v31/B-1 搬家；v32/I-2 改说明）「删锁 → 改根 → 重建锁 ⇒ 只报 `assets_root_history_rewritten`」不在 B-0**——B-0 的 c1/c2 锁已是 v2（写侧规则），但 c3 删锁并提交后 **HEAD 无该文件** ⇒ `check` 先撞哨兵 `lock_tracked_but_deleted` 在 ⓪-0 短路，根断言（⓪-3/⓪-4）与 `assets_root_history_rewritten` 都走不到；该形态移到 **§6 C 的 S-48①**，基座必须是 **v2 锁、HEAD 仍有锁、历史版本带旧根**（v31/B-1）；B-0 只保留纯函数层断言（`versions` 恰两版、不产生空版本）与哨兵夹具；对照「HEAD 有该路径、工作树文件被 `rm`（未提交）」⇒ `versions` 不追加工作树版、整体由 `lock_tracked_but_deleted` 承载（**不发 `lock_history_empty`**）。
- 依赖：A。**B-0 不升 0.4.0 的硬拒规则**，只提供写 v2、版本门 `{1,2}` 与迁移的能力；**清单 v2 ⇒ 锁 `schema_version: 2`（从 B-0 起生效，v32/B-2）**，旧 v1 锁仍可读。

### 批次 B：清单 v2 + 定义源身份 + 需求摘要 + PRD 模板字段（0.4.0，依赖 B-0）

- 文件：`_support/solution.py`（`load_manifest` 注入 `reader_version`、`validate_manifest` 版本门、`lock_payload`、`check_solution`、`_prd_skeletons`、`:1265-1270`、**`init_solution`：`reader_version_unknown` 时 exit 2 且不写盘**）、`_support/solution_task.py`（`:147-148`、`:242`）、`_support/solution_e2e.py`（`:350`）、`templates/prd/domain.md`（`prd_version` / `prd_schema`）、`templates/atlas.solution.yaml`、`scripts/atlas_solution.py`、`install.py`（`VERSION`/`DIGEST` 拆分 + 随包写 `.atlas/package.json`）、**`validators/validate_prd.py`（仅**成员侧**谓词：`prd_schema` 与首次提交时间匹配、`prd_schema: 2` 两列齐全、`prd_schema: 1` 的期限；不依赖 crosswalk，v17 归 B）**、`shared/solution.md`、`tests/test_atlas_solution.py`、`tests/test_solution_task.py`、`tests/test_prd_schema.py`、`tests/test_version_fallback.py`（新，V-05）。**不再新增 `_support/_version.py`**（v12：第三级固定为工具包根 `package.json`，与 `validate_e2e_index.py:104-125` 一致）。**父仓按 crosswalk 扫被引用 PRD 的那半边不在 B**（归 D，见 §1.5 第 2 条执行点分层）。
- 夹具：v1 无 `definition`；v2 缺 `acceptance_cutover`；同 domain/code/version 副本；版本未升（提示「提到 N」）；路径变更无评审；锁后补 AC（digest 漂移）；`definition: null` + 有 AC；5 个硬编码读者全部走自定义路径；4 个 glob 读者看到自定义名；golden vector；Windows 换行（worktree 脏但 blob 摘要一致）；`lock --update` old→new 输出；`check` 的 `定义源:` 行；**用真模板**（`templates/prd/domain.md`）跑；**0.4.0 `init` 写 v2 且带 `definition`，其中 `definition.commit == null`（V-13，v9 从 B-0 移入；v10/I-3 补）**；**0.4.0 新仓 `init → check` PASS 且只报 `definition_commit_pending` WARN（V-16，v9 新增；v10/I-3 补）**；**`reader_version` 三级来源各一条（`.atlas/VERSION` / `.atlas/package.json` / `<工具包根>/package.json`，V-05，v10/I-4；v12 去掉 `_support/_version.py`，与实现对齐）**；**0.2.x 读 v2 清单 ⇒ 硬拒 `manifest_schema_unsupported`（V-17，v10：从 B-0 缺口移入；`reader_version` 注入在 B，B-0 构造不出来）**；**`reader_version_unknown` 时 `init` ⇒ exit 2 且不写任何文件，对照 `check` 仍 WARN/exit 0（V-18，v13/第十二轮 B 批前置）**；**merge 保留 `null` 锁（main null + side 非 null + `merge -s ours`）⇒ `definition_commit_unverifiable` FAIL（V-19，v14/B-2）**；**v2 锁必须落 `layout_assets_root` 与 `assets_root_history[]`，首锁元素是对象 `{root: <当前根>, review: null, commit: null}`（v15/D-1；v16/D-1 改元素形态）**；**`prd_schema_too_low`（D-37，**发布后夹具**：v19/重要 4 从 B 验收清单摘出，它依赖 `PRD_SCHEMA_2_FROM` 已置值；常量仍为 `None` 时只验 `prd_schema_gate_unarmed` WARN）**；**`reader_version >= 0.4.0-0`（含 beta）且 `PRD_SCHEMA_2_FROM is None` ⇒ `prd_schema_gate_unarmed` WARN / exit 0 / 不计 FAIL（D-38，v18/重要 2；v19/重要 4 注明：这测的是「正式版带未武装常量」这种**不该存在的配置**，能绿只说明 WARN 生效，不说明判据可用）**；**发版门（D-40，v19/重要 3；v20/重要 5 补 skip 语义）：`tests/test_release_gate.py` 断言 `PRD_SCHEMA_2_FROM` 非 None 且等于发布 tag 的 UTC 日期，不一致 ⇒ FAIL。skip 语义写死：无 `GITHUB_REF_TYPE` / 非 `tag`，或 `PRD_SCHEMA_2_FROM is None` ⇒ `pytest.skip(reason=...)`（说明「未在发布 tag 上运行」或「常量未武装」）；仅 `GITHUB_REF_TYPE=tag` **且** `GITHUB_REF_NAME` 匹配 `v0.4.0*` 时执行断言**；**Assumptions 节按表头定位（`假设内容` / `采用的默认值`），`## 六、假设与默认值` 必须命中而非跳过；证据列表头 `strip()` 后逐字比对、`疑似别名` 只进文案不放行（v17）**。
- 依赖：A、B-0；模板字段改动随 B，不排 D（R1）。

### 批次 C：记录绑定 + 卡投影 + E2E 封条 + 续签链（#52/#54/#55）

- **前置迁移（P4/Q-4，C 批硬前置）**：成员仓跟踪 `.trellis/tasks/*/prd.md` 与 `.trellis/tasks/*/solution.md`（含 archive 目录的既有卡），用 B-0 的 `migrate --check-members` 逐成员产出 `git add -f` 命令；CI 加 `fetch-depth: 0`（§5.2.11）。前置未完成 ⇒ C 批不上线；没有 `signed_at` 宽限。
- 文件：`validators/validate_apply_record.py`（新）、`validators/validate_task_card.py`（新；v41 加 Confirmed 证据列判据）、`scripts/atlas_check.py`、`scripts/atlas_apply_seal.py`（新；**封条签发与续签的唯一写入口**，产出 `signed_at` 与 `renewal_seq` / `previous_*`；**v44：不新增 `seal unfreeze`**——frozen 封条缺 upstream 绑定只降级为永久 WARN，见 §2.5）、`scripts/atlas_solution.py`（preflight / `task acceptance --backfill` / **`seal freeze --seal <path> --at <sha>`（v14/I-1：`frozen` 的唯一写入口，只写锁的 `state`/`frozen_at`，不碰封条字节）** / **`seal reanchor --review <REVIEW-ID> --from-a <sha>`（v23/I-4 补进本表：`exemption_start_history[]` 的**唯一**写入口——它重写 `L[0]`、同步重指 `exemption_started_at`、并向 `exemption_start_history` append 一项 `{from, to, commit: R 的父提交}`；不写则 `exemption_start_history_broken`）** / **`lock --update --assets-root <new> --anchor-review <ID>`（v15/D-1：改根唯一出口，append `assets_root_history`）** / 默认 strict / `--lenient` 只看封条）、`apply/reference.md`、`shared/layout.md`、`docs/map/apply.md`、`tests/test_apply_record.py`、`tests/test_task_card.py`；**C 批新增只读依赖 `ac-crosswalk-waivers.md`**（`waiver_baseline_digest` 重算集合；文件缺失 ⇒ 集合 `[]`，不是 crosswalk 解析器依赖）。
- 夹具：title/description 带 AC 的空壳卡（B1）；围栏块藏 `atlas-acceptance:`（I5）；Notes 修改不 stale；验收行改 + 无误 reason；`card-acceptance-change`；AC 不在该需求 `acs` 内；**卡门边界（v41）：只判 `⊆ requirements[].acs`，crosswalk 像 / 孤儿成员 AC 归 D，C 批夹具不因此变红**；**Confirmed 表：`verified` 无指针 / `unverified` / 缺列（K-20…K-22）**；**`waiver_baseline_digest` 漂移 ⇒ `waiver_baseline_drift` FAIL（v43/重要 3：从 D 移到 C）；waivers 缺失分两态（v44/重要 7）：基线 `null` + 文件缺失 ⇒ 不判；基线非 null + 文件缺失 ⇒ 集合 `[]` ≠ 基线 ⇒ `waiver_baseline_drift` FAIL（删文件检测）**；有 AC 写 `none`；成员仓未跟踪卡 ⇒ `card_untracked` FAIL（K-13，无宽限）；有封条但卡在 active 与 archive 都缺失（K-14）；归档卡在 `tasks/archive/<month>/` 命中 ⇒ 不误红、不判新鲜度；分片块改 / 索引状态回写 / `关联AC` 改（link-change）；case+link 同改；`previous_cases` 错；`gap.due=1970-01-01`；`case_ids` 双真相不等；孤儿封条（active + archive 都无）；legacy 白名单（新任务有/无 review）；backfill 续签链；原地改写（`seq` 回 1 + `previous_*` null，S-17）；删封条重建（`seal_history_reset`）；普通 `--no-ff` merge 不打断链（S-21）；冲突解决 merge 手写新字节 ⇒ `seal_merge_conflict`，取一侧 + 独立续签提交且 `previous_seal_commit = 提交前 L[-1]` ⇒ PASS（S-22/I1）；add/add 冲突按**提交数**判 `seal_history_ambiguous`（S-19）；reanchor 后**立刻** `check` PASS（S-18）；**reanchor → 再续签 → 篡改 `previous_seal_commit` ⇒ `renewal_chain_broken`（S-23/B1）**；**伪造 reanchor 且改载荷 ⇒ `reanchor_payload_mismatch`（S-24/B1-v9）**；**伪造 reanchor、载荷不变、`from_a` 随机 ⇒ `reanchor_anchor_mismatch`（S-25/B1-v9）**；**reanchor → 后置 `lock --update` 独立提交 → `check` PASS（S-26/v10/B-1）**；**合法 reanchor → 下一次续签删掉 `reanchor` ⇒ `reanchor_record_missing`（S-27/v10/B-2）**；**非边界续签把 `from_a` 换成随机 sha ⇒ `reanchor_record_mismatch`（S-28/v10/B-2）**；**浅克隆执行 `seal reanchor` ⇒ 非零退出（S-29/v11/阻断 2）；`--filter=blob:none` 的 partial clone 同理（S-29b/v12/阻断 2）**；**多纪元回滚 `reanchor` ⇒ `reanchor_record_mismatch`（review 外部锚，S-30/v11/重要 1）**；**换封条路径：新路径 PASS、旧路径删 `reanchor` 必须红（S-31/S-31b/v12/阻断 1）**；**两枚封条各自 `lock --update` 互不搬锚，两路径各自续签都 PASS（S-32）**；**换路径后旧路径做多纪元回滚仍红（S-33）**；**`seal_anchors` 缺键 / 多键 ⇒ `seal_anchor_path_unmapped` / `seal_anchor_path_orphaned`（S-34、T-20/T-21）**；**换路径但 `moved_from` 指向已删/链不 PASS/sha 不符的旧路径 ⇒ `seal_path_history_lost`（S-35、T-22）**；**改名时删旧键 + 删旧文件 + 不写 `moved_from` ⇒ 必红（S-36，首报 `seal_anchor_path_unmapped`；v13/R12-1）**；**多封条不给 `--seal` ⇒ exit 2 并列候选（S-37）**；**合法 `frozen` PASS + 冻结后改写/删除 ⇒ `seal_frozen_modified`（S-38、T-24）**；**`retired` 路径被写 ⇒ `seal_path_retired_write`（T-23）**；**state 与 HEAD 不符 ⇒ `seal_anchor_path_state_mismatch`（T-25）**；`seal_anchors[S]` 缺失/过期 ⇒ `reanchor_anchor_missing` / `seal_anchor_stale`（**先判 stale，成立即抑制 mismatch**）；`N == 1` 的 reanchor（`base_n: 0`）⇒ `reanchor_invalid`，不 `IndexError`（v10/I-2）；删+重建型 filter-branch（`D>0`）⇒ `seal_history_reset`，reanchor 不适用（重要 4）；shallow 先判 `--is-shallow-repository`（S-20）；**`merge -s ours` 后删键删文件必红（S-39/v14/B-1）、merge 内新增封条能建键（S-40/v14/B-1）、`docs/examples/` 样例不入 `U`（S-41/v14/I-4）、换路径 + 改载荷 + 无 `reasons`/`previous_cases` ⇒ `seal_move_payload_mismatch`（S-42/T-26/v14/I-2）**；**改根 + 删旧键必红（S-43）、合法改根走 `--assets-root` 后旧键不 orphaned 且已 reanchor 的路径仍 PASS（S-44）、首签 rebase 受控重指后 `epoch_origin_history` 两条（S-45，前置：建键即 `[epoch_origin]`）、`renewal_seq == 2` 的 rebase 必红（S-46）、`frozen` 键手改 `frozen_at` ⇒ `seal_frozen_modified` / 不动 ⇒ PASS（S-47a）、`retired` 键 `lock --update` 后 `moved_to`/`state` 原样（S-47b）、单提交整段重写 `assets_root_history` + 删封条删键 + 挪树改 config ⇒ `assets_root_history_rewritten`（S-48；**基座前置（v31/B-1；v32/B-2 更正）：必须是 `schema_version: 2`、历史版本带旧根、且重建后 **HEAD 仍有锁**——B-0 的 c3 形态 HEAD 无锁，会先撞哨兵 `lock_tracked_but_deleted` 短路、根断言走不到（§6 B-0 已改纯函数），故该形态只归本条**）、三段/一段路径 ⇒ `seal_path_unsupported`（T-27）、`exemption_started_at` 与 `L[0]` 封条 `signed_at` 不逐字节相等 / 换路径未沿 `moved_from` 递归继承链首值 ⇒ `exemption_start_conflict` FAIL（T-28；`%cI` 越界只 WARN/INFO）；非规范形态（**锁内 `exemption_started_at` 字面值**）⇒ `exemption_start_signed_at_not_canonical` FAIL（**`L[0]` 等任何封条 blob 的形态归 T-29 的 `signed_at_not_canonical`**，v24/B-1）；`exemption_start_history[]` 断裂（删中间项 / 改 `from` / 末项 `to` 与 `L[0]` 不等 / 只改 `exemption_started_at` 不 append）⇒ `exemption_start_history_broken` FAIL（**S-55 三变体**，v22/I-6）、**提交 A 把 `assets_root_history` 写坏（坏 JSON / `[]` / `{root: null}` / `[{}]` / 元素缺 `.root`）→ 提交 B 改根 + 删封条 + 删键 + 锁写干净 ⇒ **CLI 面**断言 `check --json` 的 `errors[].code == lock_history_unparsable`、stdout 是合法 JSON、`exit 1`（`historical_roots()` 抛 `LockHistoryUnparsable` 只作单元测试细节，v19/重要 2；S-49 五变体，v18/阻断 1）**、**锁文件非 JSON / 顶层不是对象 / `schema_version: 1.0` 或 `true` / `members: {}` / **`members` 或 `contracts` 缺失（当前锁必填，v19/次要 1）** / `assets_root_history: []` ⇒ `lock_unparsable` FAIL 且 ⓪-0 即短路（`errors[]` 只有该码、不进第 1 步，v19/重要 1），不得落 `lock_missing` 的「跳过」（S-50，v18/阻断 2）**、**S-51（正）：资产根 `产品 根`（中文 + 空格）经 `install.py --assets-root` 合法装入 ⇒ `check` PASS、`assets_root_history_rewritten` 不报（根字符集单源，v19/阻断 1）；对照 `ROOT_RE` 只是写侧建议，不得据此判红**、**S-52（负）：历史锁根 `../product` / `/product` / `.atlas/product` ⇒ `lock_history_unparsable`；当前锁同形态 ⇒ `lock_unparsable`（v21/I-2：⓪-0 吸收当前锁全部结构性与词法性错误）；首尾空白在解析层拒、写侧拒空白（**写侧「不 trim」与 `_root_by_index_ok` 分层 / `lexical=True` 零 FS 已在 B-0 清单验，此处不重复**，v27/I-3；v23/次要 6：当前 `layout.py` 因 `raw = value.strip()` 在先仍会 ACCEPT）**、**S-53：orphan 分支或已删分支上的锁版本含旧根 ⇒ 不进 `UH`、不参与 ⓪-3（只信 HEAD 可达历史，v19/次要 3）**、**V-20 → 已移入 B-0 夹具（v21/I-4，此处不再重复）**、**V-21（v20/阻断 2 两变体）：① 清单 `definition.commit` 指向本地不存在对象 ⇒ WARN + `downgrades[]`（`scope: definition_source`、`flag: --allow-unverifiable-chain`）、`exit 0`；不带开关 ⇒ `definition_commit_unverifiable` FAIL；② 封条 `epoch_origin` 指向本地不存在对象 ⇒ 带开关也 FAIL（`previous_seal_commit` / `anchor_review` 同）；读取层：历史提交对象本地缺失 ⇒ `chain_unverifiable`（**`<c>` 来自 `git log`，⓪-1 不可达**）；该提交没有锁路径 ⇒ `continue`、不报码；对象与路径都在但 `git show` 失败 ⇒ `lock_history_unparsable`；`git log` 非零 ⇒ `chain_unverifiable`（不是 `lock_history_unparsable`）（v19/阻断 3、重要 5）**、**S-51 三变体（v20/阻断 1；v21/B-1 补普通文件、I-2 改报码；v22/I-1 补构造条件）：`assets_root_history` 至少两个元素，被破坏的根必须位于 `hist[:-1]`（三个变体分别破坏第 0 个元素），**末元素必须是更新后的当前根且真实存在、是目录**；① 该历史根对应目录已删除 ⇒ 仍 PASS；② 该历史根被换成指向仓外的 symlink ⇒ 仍 PASS；③ 该历史根被换成**普通文件** ⇒ 仍 PASS**（历史根只做词法校验，不因今天的工作树判红）、**S-53 注（v20/次要 1）：merge 带入的祖先仍算 HEAD 可达**、**S-54-C（v20/重要 2；v21/I-4 拆半）：同一个 `REVIEW-ID` 先用于 `lock --update --assets-root` 改根、再用于 `--cutover` ⇒ `review_reused` FAIL；同决策链内复用不算。B-0 只验形态判定（S-54-B0），本夹具验「换根动作后」的复用**、**T-29（v20/重要 4；v22/I-2 补读侧）：写侧只产 `...Z`——封条签发 / 续签后 `signed_at` 匹配 `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$`；**读侧校验点是链上每枚封条 blob 的 `signed_at`**（从 HEAD 沿 `previous_seal_commit` 逐级取，含 `L[0]`），两态夹具：`N == 1` amend 唯一封条（覆盖 `L[0]`）、`N > 1` **amend 最新续签提交**（v25/次要 3：不是字面 `HEAD`）；中间续签**不可构造**（改它必先破 `previous_seal_commit` ⇒ `renewal_chain_broken`），不设该变体；出现 `+00:00` 或小数秒 ⇒ `signed_at_not_canonical` FAIL**、**T-30（v23/I-1/I-2；v24/B-2 补⑤；v25/I-3/I-4 补⑥、删「重排」，六变体）：① 单提交把 `exemption_start_origin` 改成任意别的规范时间（其余不动）⇒ `exemption_start_origin_rewritten` FAIL；② 单提交把 `first_seen_origin` 重置成「今天」⇒ `first_seen_origin_rewritten` FAIL；③ 单提交把 `exemption_start_history[]` **删一项 / 改一项** ⇒ `exemption_start_history_broken` FAIL（版本前缀单调；**「重排」已删**，≥2 条不可端到端构造，前缀单调由 T-33 纯函数单测覆盖）；④ 回填夹具：**老锁必须是 `schema_version: 2` + 封条**（v1 会先撞 ⓪-2），缺 `exemption_start_origin` / `exemption_start_history` / `first_seen_origin`，`lock --update` 后补 `origin = 原 started_at`、`history = []`、`first_seen_origin = 当前 first_seen_at`，其余逐字节不变、`check` PASS，有值时一字不改；⑤ ④之后再单提交改 `first_seen_origin` ⇒ `first_seen_origin_rewritten` FAIL，同构改 `exemption_start_origin` 同理（存量锚非死码）；⑥ 首签封条 `first_seen_at` 写未来值、锁键照抄 ⇒ `first_seen_origin > L[0].signed_at` ⇒ `first_seen_origin_rewritten` FAIL（`detail.kind = after_signed_at`，初值防护；**构造：建键时一次写成、不事后 amend 载荷**，v26/S-11：首签无前一版封条、`first_seen_at` 不在 digest 覆盖内，无需重签；事后 amend 会改 `L[0]` SHA、使 `epoch_origin` 失配）**、**T-32（v24/I-3；v25/I-2；v26/B-1 端点对齐 V-20）：① `--amend` 改已签封条 `due` 到闭区间外（含 `2027-06-30` 超限）⇒ `exemption_due_out_of_range` FAIL（不得新开提交，否则 `renewal_seq != N` 抢码）；② `origin > due` ⇒ 同码；③ 三条端点 PASS、各钉 `min` 一支，且均满足 `first_seen_origin ≤ L[0].signed_at`——③a 早于默认的 `cutover` 支：`acceptance_cutover = 2027-01-31`（早于默认 `2027-03-31`，§5.1 允许收紧、无需 `--anchor-review`；**五步序列见 §7 T-32，v33/B-1 补 PRD 提交步与首锁 `null`**）：**前置 = 全新空仓 + 已提交的 `product/prd/solution-prd.md` + 无封条**（PRD 由 `init` 生成骨架、第③步提交；「已迁移仓」删除），`init --name demo --member <m>=<path> --cutover 2027-01-31`（清单一次写 v2；**首锁的 `acceptance_cutover` 为 `null`**——`lock_payload` 只在 `definition.commit` 非空时写值） → 首签载荷一次写死 `signed_at = first_seen_at = first_seen_origin = 2026-11-05T00:00:00Z`、`due = 2027-01-31`（不经 `now`、**不 amend**） → **提交 PRD、清单与配置**（`git add -A`，含 `.gitignore` 与成员仓初始提交；PRD 未跟踪会让 `lock --update` 撞「定义源工作树不干净」硬拒；v34/重要 1） → `lock --update`（本次**才**写入 `2027-01-31`，`due` 用它；v2 清单 ⇒ 写 v2 锁；**`seal_anchors` 属 C 批、今天不建键，PASS 不构成 `due` 已评测**，v34/重要 2） → **锁提交**（HEAD 清单与锁同源，干净工作树上复验 PASS）、`signed_at` **钉死、不得用运行时 `now`**（否则 2027-02-01 后 `origin` 日期 > `due` 自动翻红；与 `first_seen_origin` 同值保证 `origin == signed_at`）、`d + 90d = 2027-02-03 > cutover` ⇒ `due = 2027-01-31`；③b 延展支：`acceptance_cutover = 2027-04-15` 挂 `--anchor-review`（**清单与锁两侧同写 `2027-04-15`**；步骤同 ③a 的五步（含「提交 PRD 与清单」；**不启用第二份二进制，但 reader 版本仍决定清单版本**）——① `init --cutover 2027-04-15 --anchor-review <REVIEW-ID>`、两处 review 值一致），**首签时 `signed_at` 与 `first_seen_at` 同写 `2027-04-15T00:00:00Z`**（未来值构造；无规则禁止未来 `signed_at`，`%cI` 只 WARN/INFO；不事后 amend，否则改 `L[0]` SHA 撞 `epoch_origin`），`d + 90d = 2027-07-14 > cutover` ⇒ `due = 2027-04-15`；③c `+90d` 支：默认 `cutover = 2027-03-31`，`first_seen_at` / `first_seen_origin` / `signed_at` **同写 `2026-11-05T00:00:00Z`**（**同样不用运行时 `now`**，否则 2027 年起该支翻到 `cutover` 支、`+90d` 分支失去覆盖），`d + 90d = 2027-02-03 < 2027-03-31` ⇒ `due = 2027-02-03`，永久成立；④ 续签把 `due` 改回区间内 ⇒ 恢复 PASS；**比较全在日期层**（先截 UTC 日期得 `d` 再加 90 天，全程 `date`，`cutover` 不随缺 `first_seen_origin` 跳过）**、**T-31（v23/次要 2）：干净基线注入非 `SolutionError` 的未知异常 ⇒ `check --json` 为 exit 2、合法 JSON、`errors[]` 恰一条 `internal_error`、`not_run[]` 从异常处填满、无裸 traceback；注入 `SolutionError` ⇒ 走业务码；用法错误 ⇒ exit 2 且 stdout 首行非 JSON（消费方按首字符区分）**、**S-55 前置 = S-18 的构造 + S-26 的后置 lock（v23/I-5；v24/I-2 补全；v25/I-1 改①；v26/S-7 更正理由：**已重指后删空 ⇒ ⑤ 与单调同红、按判序只报 `exemption_start_history_broken`**；前缀单调移 T-33）**（以上 v15/v16/v17/v18/v19/v20/v21/v22/v23/v24/v25/v26）**。
- 依赖：B。

- **C 批写入口：全仓不存在，本稿一律标「C 批实现时补」（v32/结构项）**：`seal freeze --seal <path> --at <sha>`、`seal reanchor --review <ID> --from-a <sha>`、`lock --update --assets-root <new> --anchor-review <ID>` 三条命令**今天都不存在**（`scripts/atlas_solution.py` 没有对应子命令；`_support/solution.py` 的 `lock_payload` 只写 `schema_version` / `solution` / `mode` / `locked_at` / `members` / `contracts`（+ `definition`、`acceptance_cutover` 与根字段），**没有** `seal_anchors`（C 批才建）；`acceptance_cutover_review` 在 review 非空时写（`_support/solution.py:1314-1315`，v35/重要 5 更正））。因此本批**不再写「看起来今天就能跑」的 CLI 夹具**，统一按三要素表述：
  1. **依赖哪个尚不存在的命令**：S-18 / S-26 / S-31 / S-43 / S-44 / S-48 / S-55 依赖 `seal reanchor` 与 `lock --update --assets-root`；S-38 / S-47a 依赖 `seal freeze`；S-37 依赖 `lock --update` 的多封条选择逻辑。这些编号**在三条命令落地前不算可执行夹具**。
  2. **规则层逐端点闭合度（v33/次要 4；v34/阻断 1、重要 2 补两态与假绿）**：**两态口径**——三条端点的**产品可达前置是 B 批发版后**（或 `.atlas/VERSION` 已是 `0.4.0`）；夹具可预置 `.atlas/VERSION=0.4.0` 起步，但那是**夹具前置、不是产品可达路径**，不得据此宣称「今天可在真实仓上跑」。**`lock --update` 今天不写 `seal_anchors`**（`lock_payload` 无该键、无 `seal` 子命令）⇒ 本批夹具里的 `check` PASS **不构成 `due` 已评测**。
     - `seal freeze --seal <path> --at <sha>`：**读侧闭合、写侧待命令**——`seal_frozen_modified`（S-38/T-24）的「只写 `state` / `frozen_at`、不碰封条字节」已写死在 §5.1 / §1.1.3；S-38 今天只能构造「手改锁的 `frozen_at` ⇒ 必红」，**写侧后置断言（冻结后改写/删除封条 ⇒ 红）等命令落地**。
     - `seal reanchor --review <ID> --from-a <sha>`：**三件事全写死、闭合度最高**——重写 `L[0]`、同步重指 `exemption_started_at`、向 `exemption_start_history` append 一项（§5.1）；读侧 `reanchor_anchor_mismatch` / `reanchor_payload_mismatch` / `reanchor_record_missing` / `reanchor_record_mismatch` / `reanchor_anchor_missing` / `reanchor_invalid` / `seal_anchor_stale` 与 `exemption_start_history_broken` 的判据都已闭合（S-18/S-24…S-28/S-30/S-55）；**S-48 比 S-18 高一级**——除了 reanchor 还要「同提交改根 + 删封条删键 + 挪树改 config」，因此同时依赖下面那条命令。
     - `lock --update --assets-root <new> --anchor-review <ID>`：**写侧规则闭合、读侧闭合、CLI 待命令**——`assets_root_history` 只增不改、旧键不 orphaned、`REVIEW-ID` 不是 `review_reused` 的复用源（§5.1/§5.2）；读侧 ⓪-3 的 `UH` 口径、`assets_root_history_rewritten`、`seal_anchor_path_orphaned` 都已闭合；S-48① 的**基座前置**（v2 锁 + 历史版本带旧根 + 重建后 HEAD 仍有锁）也已写死，差的是命令本身。
  3. **实现时用什么断言**：三条写入口落地后补上述 CLI 夹具，并同时补三条写侧单测——`seal reanchor` 后 `exemption_start_history` 恰 append 一项且 `exemption_started_at == 新 L[0].signed_at`；`lock --update --assets-root` 后旧键不 orphaned、`assets_root_history` 只增不改；`seal freeze` 只写 `state` / `frozen_at`、封条字节不变。
  能量化部分（`build_lock_versions`、`check_history_prefix`、`due` 的日期算术、`lexical` 根校验）已提成**纯函数夹具并在 B-0 交付、今天就跑**，不等这三条命令。

### 批次 D：#51 crosswalk + #53 证据/契约 AC + 期限执行点

- 文件：**`_support/ac_crosswalk.py`（新，v41：`parse_crosswalk` / `crosswalk_findings` / `resolve_crosswalk_path`，见 §2.1）**、`tests/test_ac_crosswalk.py`（新）、`_support/solution.py`（`check_solution` 读 crosswalk、waiver、证据列；**父仓按 crosswalk 扫被引用成员 PRD、缺列报 `evidence_columns_unbound` 的那半边只在这里，v17 明确归 D**）、`_support/solution_task.py`（`task_status`）、`templates/prd/domain.md`（**仅** §五-b 契约表；`prd_schema: 2` 与证据两列已随 B 落地，**D 不再升版本**；`prd_version` 已随 B）、`templates/prd/ac-crosswalk.md`（新）、`validators/validate_prd.py`（只留**成员侧**证据列期限判据的接线；成员侧 `prd_schema` 谓词已在 B 落地）、`validators/validate_ac_alignment.py`、`shared/solution.md`、`tests/test_prd_contract_ac.py`、`tests/test_solution_task.py`。
- 夹具：成员多 PRD 定位（I1）；`(方案AC,成员)` 无需求行；重复三元组；需求级豁免；后加需求不可豁免；（`waiver_baseline_digest` 漂移已移 C，v43/重要 3）`verified` 无指针；被引用域缺列（父仓 FAIL `evidence_columns_unbound`）；**`成员AC = AC-CONTRACT-001` ⇒ `contract_ac_in_member_slot` FAIL；成员 PRD AC 表出现契约 AC ⇒ 同码（D-46）**；**父仓按 crosswalk 扫被引用 PRD、crosswalk 缺失 ⇒ `evidence_columns_unbound`（v17：这半边依赖 crosswalk 落地，不能出现在 B 的清单里）**；`prd_schema: 2` 新 PRD 缺列（立即 FAIL）；`prd_schema: 1` 存量未引用域缺列（2027-06-30 含前 WARN；07-01 起成员 `validate_prd` FAIL）；成员单独 `atlas check` 证据列 N/A；**§五-b 契约 AC（v42/重要 7）**：正例（六列齐全、`AC-CONTRACT-001` 被 `requirements[].acs` 引用、`关联AC` 有效）；反例（缺 `契约AC` 表头 ⇒ `contract_ac_table_missing`；引用未定义 ⇒ `contract_ac_undefined`；`关联AC` 悬空 ⇒ `contract_ac_orphan`；重复 `契约AC`；编号 `AC-CONTRACT-1` 形态错 ⇒ parse `ac_format`）。
- 依赖：B；D 必须在 B 后。**批次内依赖（v17/§1.5 第 2 条）**：`evidence_columns_unbound` 的父仓半边**只能**在 crosswalk 落地后实现；B 批只交付成员侧 `validators/validate_prd.py` 的同一谓词，不得以「父仓证据列已实现」的姿态记入 B 的验收。

串行：**A → B-0 → B → C → D**。任何两会话不得同时写 `_support/solution.py` 或 `shared/solution.md`。

## 7. 反面包（按编号，所有输入必须红/按注记）

| 编号 | 坏输入 | 期望 |
|---|---|---|
| K-01 | 空壳卡只有 `[AC-...]` 标题 + description | FAIL（专用行缺失） |
| K-02 | 卡正文散文出现合法 AC token | FAIL（不认裸 token） |
| K-03 | `atlas-acceptance:` 行引用未定义 AC | FAIL |
| K-04 | `none` 缺 owner / due / reason | FAIL |
| K-05 | `none` 的 due 已过 | FAIL |
| K-06 | 改 Notes 后封条 | PASS（投影不变） |
| K-07 | 改验收行、reason 未写 `card-acceptance-change` | FAIL |
| K-08 | 改验收行、reason 正确 | PASS（重签） |
| K-09 | 生成内容含 `atlas-acceptance:` 字样 | 不适用（生成器不写该前缀） |
| K-10 | `atlas-acceptance:` 在 ``` 围栏块内 | 不计（FAIL 专用行缺失） |
| K-11 | `--backfill` 覆盖已有验收行 | 拒绝 |
| K-12 | `atlas-acceptance:` 在 HTML 注释内 | 不计（FAIL 专用行缺失） |
| K-13 | 成员仓 `.trellis/tasks/*/prd.md` 未跟踪（C 批起，任意封条） | `card_untracked` FAIL（无 `signed_at` 宽限） |
| K-14 | 有封条但成员卡在 active 与 archive 都缺失 | `card_absent` FAIL（本地 `--allow-card-absent` 才 WARN） |
| K-14a | 有封条、卡已归档到 `.trellis/tasks/archive/<month>/<ID>/` | PASS（不算 `card_absent`，不判新鲜度） |
| K-15 | 卡挂别的需求的 AC（⊄ 本 `(id,member)` 的 `acs`） | FAIL |
| K-16 | 需求有 AC 却写 `none` | FAIL（须走需求级豁免） |
| K-20 | 任务卡 Confirmed 表 `verified` 无证据指针 / `assumed` 无默认值来源 | `confirmed_evidence_missing` FAIL（C，v41；v42 改号） |
| K-21 | 任务卡 Confirmed 表 `unverified` | `confirmed_unverified` WARN（exit 0；C，v41；v42 改号） |
| K-22 | `prd_schema: 2` 但 Confirmed 小节缺表 / 缺 `确认项` 或 `证据状态` 列 | `confirmed_columns_missing` FAIL（C，v41；v42 改号） |
| D-01 | v2 清单无 `definition` | FAIL unbound（v1 见 V-02 硬拒） |
| D-02 | v2 缺 `acceptance_cutover`（无论是否有 AC） | FAIL `acceptance_cutover_missing`（v18/阻断 3：v2 必填）；对照 v1 缺 ⇒ 只 `migration_required` WARN |
| D-03 | 同 domain/code/version 副本替换 | `lock --update` 拒绝（版本未升） |
| D-04 | 副本升版本但路径变更无评审 | 拒绝 |
| D-05 | 版本递减 / 日期倒退 | 拒绝 |
| D-06 | PRD 删除 / 逃逸 | FAIL missing |
| D-07 | blob sha 不符 | FAIL mismatch |
| D-08 | front matter `prd_version` 与锁不符 | FAIL mismatch |
| D-09 | 锁后补 AC | FAIL `manifest_drift`（不落 `ac_missing`） |
| D-10 | 真删 AC、摘要未变 | FAIL `ac_missing`（可宽限） |
| D-11 | `definition: null` 且需求有 AC | FAIL unbound |
| D-12 | commit 对象本地缺失 | 默认 FAIL `definition_commit_unverifiable`；仅 `--allow-unverifiable-chain` WARN（I3/R9） |
| D-13 | 5 个硬编码读者任一漏改 | 夹具红 |
| D-14 | `migrate --definition-path` 指定自定义名，清单仍写默认名 | 红 |
| D-15 | 自定义路径下 `_pointer` 仍写默认名 | 红 |
| D-16 | 自定义路径下 `_ac_coverage` 仍读默认名 | 红（0/N 聚合） |
| D-17 | 4 个 glob 读者看不到自定义名 | 红（路径约束被绕过） |
| D-18 | 路径含 `..` / 绝对路径 / 不在 `<assets_root>/prd/` | 加载拒绝 |
| D-19 | 定义源变更带假 REVIEW | 形式通过；评审责任，机器不判（如实） |
| D-20 | `_ac_prd` 硬编码 | 夹具红 |
| D-21 | `_prd_skeletons` 硬编码 | 夹具红 |
| D-22 | `check_solution` 骨架检查硬编码 | 夹具红 |
| D-23 | `definition.path` 不以 `-prd.md` 结尾 | `definition_path_unsupported` FAIL |
| D-24 | Windows `autocrlf`：worktree 字节 ≠ blob，但 blob 摘要一致 | `check` 内容 PASS + dirty WARN；`lock --update` 拒绝 |
| D-25 | `requirements_digest` 与 golden vector 不一致 | 夹具红 |
| D-26 | 同域副本 + 抬版本 + 改路径 + REVIEW | 机器 PASS；记录为已知残余风险（R2） |
| D-27 | v2 清单在 A 批代码上被读取 | 不发生（A 批不解析清单，I8） |
| D-28 | PRD 缺 `date` | `prd_date_missing` FAIL |
| D-29 | `prd_schema` 高于工具支持 | `prd_schema_unsupported` FAIL |
| D-30 | blob 变、版本升、无 REVIEW | `lock --update` 拒绝 |
| D-31 | 同路径替换 + 抬版本 + REVIEW | 机器 PASS；人审 PRD diff 负责（R2） |
| D-32 | v2 清单 round-trip：`definition` 落进 `unknown` | 夹具红（P1） |
| D-33 | `acceptance_cutover` / `min_atlas` 取不到 | 夹具红（P1） |
| D-34 | `definition` 未知子键 | `definition_field_unknown` FAIL（不静默） |
| D-35 | `definition: null`（无需求） | 不落 `unknown`，`unknown == []`（P-5） |
| D-36 | 0.4.0 `init` 后首次 `check`：`definition.commit == null`（PRD 刚写出、未提交） | `definition_commit_pending` **WARN**（放行；不得报 `definition_commit_unverifiable`）；首次 `lock --update` 后仍为 `null` ⇒ 后者 FAIL（v10/I-3） |
| D-37 | `prd_schema: 1`，但该 PRD 的**首次提交**晚于 0.4.0 发布点（`git log --diff-filter=A --format=%aI -- <prd>` 取最早一条，统一 UTC 比较）；对照：0.4.0 `init` / 模板生成的新 PRD 直接写 `2` | `prd_schema_too_low` **FAIL**（v17/收编 2；v18/重要 2 补常量与武装；**v19/重要 4：本夹具标为「发布后夹具」，从 B 批验收清单摘出**——它依赖常量已置值，常量仍 `None` 时只验 `prd_schema_gate_unarmed`）。判据常量写死 **`PRD_SCHEMA_2_FROM`**（= 0.4.0 发布点日期）；`reader_version >= 0.4.0-0`（含 prerelease）且 `PRD_SCHEMA_2_FROM is None` ⇒ `prd_schema_gate_unarmed` WARN，不得静默按「未武装」放行；发版门由 **D-40** 的可执行测试判。缓冲只给「首次提交早于 0.4.0 **且未被 crosswalk 引用**」的域。**`%aI` 的证明力（v18/次要 5）**：author date 可被 `--date` 伪造，**只作判据、不作证明** |
| D-38 | `reader_version >= 0.4.0-0`（含 beta）但 `PRD_SCHEMA_2_FROM` 未设置（`None`）；对照：发布 tag 日期与常量日期不一致 | `prd_schema_gate_unarmed` **WARN**（exit 0，不计入 FAIL，提示「判据未武装」）；后者在**发版门** FAIL（判据不得与 tag 漂移）。**v19/重要 4 注**：本夹具测的是「正式版带未武装常量」这种**不该存在的配置**——它能绿只说明 WARN 生效，不说明 `prd_schema_too_low` 判据可用；真正可用必须等 D-37 的常量置值 |
| D-39 | **已首次刷新**（锁历史任一版本 `definition.commit != null`）后：① 清单有 cutover、锁缺；② 两侧皆空；③ 两侧有值不等。对照：`definition.commit == null` 期间两侧皆空 / 单侧有值 | ①② ⇒ `acceptance_cutover_missing` **FAIL**；③ ⇒ `acceptance_cutover_mismatch` **FAIL**；对照 ⇒ pending PASS（单侧有值放行，B-0 期锁尚未写该字段）。写入侧不得把值写回 `null`。**v19/次要 5**：① 是**人工篡改形态**（`init` / `migrate --to 2` 必写清单、B 首次 `lock --update` 必写锁），不是常规写侧路径；夹具里要注明是手工删锁字段 |
| D-40 | **发版门（v19/重要 3）**：发布 tag 的 UTC 日期 vs `PRD_SCHEMA_2_FROM`；对照：prerelease 版（`0.4.0-beta.1`）且常量已置值 | `tests/test_release_gate.py`（或 `scripts/release_check.py`）断言「常量非 `None` 且 `==` tag 的 UTC 日期」⇒ PASS；不等 / 常量仍 `None` ⇒ **FAIL**。武装条件用 `reader_version >= 0.4.0-0`，beta 期也必须武装，不允许整段 beta 静默 |
| D-41 | 锁历史含 non-null `requirements_digest`，当前锁改成缺键 / `null` | `manifest_digest_removed` FAIL，`detail.field = requirements_digest`（v43） |
| D-42 | 锁 `prd_version` 从 5 回退到 3（其余不动） | `manifest_rollback` FAIL，`detail.prd_version = {3, 5}`；若同时缺键，**只报本码**（抑制 `manifest_digest_removed`，v43） |
| D-43 | D 批 `SEAL_UPSTREAM_BIND_FROM` 起 90 天后，C 期封条缺 `prd-domain` / `ac-crosswalk` | `seal_upstream_unbound` FAIL；`state=frozen` 豁免；窗口内只 WARN（v43） |
| D-44 | Confirmed 行 `unverified` 无 `confirmed_review:` / 有则 PASS | `confirmed_downgrade_unreviewed` FAIL / PASS（v43：当前行判，不读历史） |
| D-45 | crosswalk 文件缺失 / 不可读 | `crosswalk_unresolvable` FAIL，**抑制 C-01…C-11（含 C-09）**（v44） |
| D-46 | `成员AC = AC-CONTRACT-001`；成员 PRD AC 表出现契约 AC | `contract_ac_in_member_slot` FAIL（v44/重要 5） |
| D-47 | crosswalk 能读但坏行（表头 / 列数 / AC 形态 / 路径 / 成员字段空 五类） | `crosswalk_parse_error` FAIL，`detail.kind` 取五值之一；**抑制 `C-01…C-11`（含 C-09；只报本码）**；**不是** `crosswalk_unresolvable`（v45） |
| D-48 | **常量发版门（v44/阻断 1）**：`SEAL_UPSTREAM_BIND_FROM` ≠ D 批首个 tag 的 UTC 日期 | FAIL（与 D-40 同构；写晚 ⇒ 追溯窗口永不到期） |
| C-01 | 方案 AC 无 crosswalk 行 | 该需求 FAIL。**排除**：`AC-CONTRACT-*` 不要求 crosswalk 行（§1.5 第 7 条）；crosswalk 文件缺失 / 不可读 ⇒ 整表抑制，只报 `crosswalk_unresolvable`；**能读但坏行 ⇒ 整表抑制，只报 `crosswalk_parse_error`** |
| C-02 | 成员 PRD 路径缺失 / 多 PRD 无法定位 | FAIL |
| C-03 | 成员 AC 不在指定成员 PRD | FAIL |
| C-04 | `(方案AC,成员)` 无需求行 | FAIL |
| C-05 | 重复 `(方案AC,成员,成员PRD,成员AC)` | FAIL |
| C-06 | 后加需求进豁免表 | FAIL（baseline 不含） |
| C-07 | 豁免 due 超 cutover | 拒绝 |
| C-08 | 一个成员 AC 映射两个方案 AC | PASS（两行合法） |
| C-09 | 显式行存在、成员 AC 也在成员 PRD，但该行把成员 AC 映射到**错误的方案 AC**（与 PRD 的 `关联AC` 不一致） | FAIL（映射错位；v42/重要 6 改成真正不同的反例） |
| C-10 | D 批默认配置下跑孤儿成员 AC（未列进 crosswalk） | **断言不产生** `crosswalk_orphan_member_ac`（默认 WARN 关闭/不报）；只有显式开启可选开关才 WARN（v42/重要 6，避免恒真假绿） |
| C-11 | 成员 PRD front matter `domain` 与 crosswalk `成员` 列不符 | FAIL `member_domain_mismatch`（§1.3 已写「不一致 ⇒ FAIL」；v43/阻断 4 补码） |
| E-01 | `verified` 无指针 | FAIL |
| E-02 | 被需求引用的域缺证据列（0.4.0，父仓） | FAIL |
| E-03 | `prd_schema: 1` 存量未引用域缺列 | 2027-06-30 含前 WARN；07-01 起 FAIL |
| E-04 | 契约 AC 未定义却被引用 | FAIL |
| E-05 | 旧四列且未被引用（2027-07-01 起） | FAIL |
| E-06 | 成员单独 `atlas check` 判证据列引用 | N/A `evidence_columns_parent_only` |
| E-07 | 2027-07-01 后未引用域仍四列 | FAIL（成员 `validate_prd` 执行） |
| E-08 | `prd_schema: 2` 新 PRD 缺两列 | 立即 FAIL（无缓冲） |
| E-09 | 缓冲期内把缺列判成 N/A | 夹具红（必须 WARN） |
| E-10 | 引用 `AC-CONTRACT-*` 但 §五-b 表无该行 / 无 `契约AC` 表头 | `contract_ac_undefined` / `contract_ac_table_missing` FAIL（D） |
| E-11 | §五-b 行的 `关联AC` 不在 §五 AC 表 | `contract_ac_orphan` FAIL（D） |
| E-12 | 父仓单独判任务卡 Confirmed 证据状态 | N/A `confirmed_parent_only`（父仓不读卡正文；v42/次要 6） |
| T-01 | 任务目录 `cases.md` 出现任一条用例行（`E2E-*` / `BE-SYNC-*` / `HC-RECORD-*` / `TW-PUSH-*`，含成员任务目录与 archive） | 0.3.x WARN；0.4.0 起 FAIL `task_dir_case_duplicate` |
| T-02 | `not_ready` 无 gap | FAIL |
| T-03 | `gap.due=1970-01-01` / 过去 | 拒绝签发 |
| T-04 | `ready` 的 case_ids 为空 | FAIL |
| T-05 | `case_ids` 与封条集合不等 | FAIL |
| T-06 | 分片围栏体改 | FAIL stale |
| T-07 | 索引状态回写 | PASS |
| T-08 | 索引 `关联AC` 改、shard 不变、reason 缺失 | FAIL |
| T-09 | 索引 `关联AC` 改、reason=link-change | PASS |
| T-10 | 孤儿封条（任务已删未 archive） | FAIL |
| T-11 | archived 封条 | 不判新鲜度 |
| T-12 | case + link 同改，reasons 只写一个 | FAIL |
| T-13 | `previous_cases[]` 与旧封条不符 | FAIL |
| T-14 | `renewal_seq != N`（无 `reanchor`）/ 不等于 reanchor 公式（有 `reanchor`）/ 普通续签的 `previous_seal_commit != L[-2]` / `previous_seal_sha256` 不符；**边界封条（`seq == base_seq`）的 `previous_seal_sha256` 不为 `null`** | FAIL；reanchor 提交自身按 `previous_seal_commit == reanchor.from_a` 判，后续续签无豁免（S-23；v10/次要 2 补 null 断言） |
| T-15 | reanchor 提交的载荷与 `L[-2]` 不等（除 `renewal_seq`/`previous_seal_commit`/`previous_seal_sha256`/`reanchor`/`signed_at` **五字段**，且 `previous_seal_sha256` 必须为 `null`） | `reanchor_payload_mismatch` FAIL（S-24；v10 五字段） |
| T-16 | reanchor 的 `from_a`/`base_seq`/`base_n` 与该路径键 `seal_anchors[S]` 不符；`seal_anchors` 为 null、无键 `S`、或与 `L[-2]` 封条不同步（**仅在 `HEAD == R0` 时判**，且 **stale 成立即抑制 mismatch**） | `reanchor_anchor_mismatch` / `reanchor_anchor_missing` / `seal_anchor_stale` FAIL（S-25；v10/B-1、I-6；v12 按路径键） |
| T-17 | 封条带 `reanchor`，但 `L` 中不存在 `seq == base_seq` 的提交 / 存在多枚 / `R0.reanchor` 与当前不逐字节相同（**含非边界续签改 `from_a`**）；或 `seal_anchors[S].anchor_review != null` 且当前 `reanchor.review != anchor_review`（多纪元回滚） | `reanchor_record_mismatch` FAIL（S-28/S-30，第 4b 步，v10/B-2；v11/重要 1；v12 按路径键） |
| T-18 | 该路径键的 `epoch_origin[S] != L[0]`，但当前封条**没有** `reanchor`（删字段抹掉重写记账） | `reanchor_record_missing` FAIL（S-27，规则 1 + 第 4b 步，v10/B-2；v12 按路径键） |
| T-19 | `reanchor` 的 `N < 2` 或 `base_n < 1`（squash 成单提交后伪造） | `reanchor_invalid` FAIL，不得 `IndexError`（v10/I-2） |
| T-20 | **`U`（历史新增封条路径并集）**里有某条路径，但 `seal_anchors` 缺该键（含删键逃规则 1、含封条已被删到 HEAD 为空） | `seal_anchor_path_unmapped` FAIL（v12/阻断 1；v13/R12-1 把宇宙从 HEAD 改为 `U`；S-31b/S-36） |
| T-21 | `seal_anchors` 有某个键，但该路径**从未在 `U` 里出现过**（凭空键）；**不**因为「HEAD 上没有该文件」而判本码——那是状态问题（T-25） | `seal_anchor_path_orphaned` FAIL（v12/阻断 1；v13/R12-1 收紧：orphaned 只表示「无历史新增支撑」，不再等同于「HEAD 无文件」） |
| T-22 | 换路径的新封条记了 `moved_from`，但 `moved_from.path` ∉ `U` / 旧路径 `L_pre` 不可复算 PASS / `moved_from.sha256` 与旧路径迁出前最后一枚封条字节不符 | `seal_path_history_lost` FAIL（v12/重要 3；v13/R12-1 取消「旧路径 HEAD 必须仍有文件」这一前置——旧文件可删，判据改为 `U` + `L_pre` + sha） |
| T-23 | `state == retired` 的路径被写：新 `reanchor`、新续签、改 `e2e.cases[]` / `owner`（含 `seal reanchor` / `lock --update` 的入口） | `seal_path_retired_write` FAIL（v13/R12-4：`retired` 不是「可跳过」标记，每状态都有判据）。**前置**：需合法 `retired` 仓，**可由 S-31 接续构造**；没有前置时「retired 路径被写」无从发生，夹具会被实现成恒真（v14/N-4） |
| T-24 | `state == frozen` 的路径在 `frozen_at` 之后被改**或被删**；`frozen_at` 缺失；`frozen_at` 不是 HEAD 祖先 | `seal_frozen_modified` FAIL（v13/R12-1：删除也是修改；冻结不能掩盖此前的删除，`L_pre` 里的 `D>0` 仍判 `seal_history_reset`）。**前置**：需合法 `frozen` 仓，**可由 S-31 接续构造并跑 `seal freeze`**（v14/N-4） |
| T-25 | `state` 与 HEAD/历史不一致：`active` 但 HEAD 无文件；HEAD 有文件但 `state == retired` 且无合法 `moved_to`；`frozen` 但 `frozen_at` 与 HEAD 字节不等 | `seal_anchor_path_state_mismatch` FAIL（v13/R12-1 状态机判据；路径级之后、链级之前判，R12-6 优先级 ②） |
| T-26 | 换路径首签（`renewal_seq = 1`、`previous_* = null`、带 `moved_from`）与旧路径 `L_pre[-1]` 的载荷不等（豁免集 `{renewal_seq, previous_seal_commit, previous_seal_sha256, moved_from, reanchor?}` 之外），且未写 `reasons[]` / `previous_cases[]` | `seal_move_payload_mismatch` FAIL（v14/I-2；新路径 `L[0]` 就是自己，规则 3 的 blob 比较挡不住；S-42；v16/N-2 把 `signed_at` 移出豁免集） |
| T-27 | 封条路径不满足任何历史根的两段谓词：`apply/auth/sub/T-2.seal.json`（三段）、`apply/T-3.seal.json`（一段）；或清单里 `members[].name` 含 `/` | `lock --update --seal <该路径>` 报 `seal_path_unsupported`，**不复用** `seal_anchor_path_orphaned`，且该键**永久** unsupported、不得回落成 orphaned。成员名分层（v16/I-5）：**v1 清单**含 `/` ⇒ `migration_required` WARN + `migrate` 打印改名建议（不自动改，现有 `_validate_name` 允许 `/`）；**v2 新写入** ⇒ 加载期 FAIL（`members[].name` 限 `[^/]+`） |
| T-28 | 锁键 `exemption_started_at` / `exemption_start_origin` / `exemption_start_history[]` 的**等值判据（v18/重要 1；v19/次要 4 归一化；v22/I-6 双键与审计链）**：① `exemption_started_at` 不等于该路径 **当前** `L[0]` 首签封条的 `signed_at`（逐字节；被 `lock --update` 刷新/后移、重锚后未同步、或首写写晚）；② 带 `moved_from` 的新键未沿 `moved_from` 递归到链首、或与链首键的 `exemption_started_at` 不等（中途缺键先报 `seal_anchor_path_unmapped`）；③ 无 `moved_from` 的新键把起点写成「建键当天」或任何非 `L[0].signed_at` 的值；④ `exemption_start_history[]` 非空时：末项 `to` ≠ 当前 `exemption_started_at`、第 i 项 `from` ≠ 第 i-1 项 `to`、首项 `from` ≠ `exemption_start_origin`、数组不是 append-only（删项/改项/重排）、或**版本前缀单调被破坏**（某后版本不是**紧邻前一版本**的前缀扩展、单版本新增超过一项、相邻版本不连续；v23/I-1；v28/B-1 改「紧邻前一版本」、不得放宽为「某前版本」）；⑤ `exemption_start_history` 为空时 `exemption_start_origin` ≠ `exemption_started_at`（建键二者同值，任一侧被改写即露）；⑥ 发生了 `seal reanchor`（`L[0]` 被重写）却未 append 审计项；⑦ `exemption_start_origin > exemption_started_at`（v23/I-3） | **主判据是封条字节等值**（判序 ②）：`exemption_started_at == L[0].signed_at`（逐字节）；封条被 §3.2 链规则钉住（`seq == N`、`previous_*`、`blob@L[0]`），可复算；`git show -s --format=%cI <L[0]>` 只作 **WARN/INFO**（committer date 可被 amend / rebase / `GIT_COMMITTER_DATE` 改写），越界不单独判红。**历史数组判据**：`exemption_start_history` 非空 ⇒ 末项 `to` 必须等于 `exemption_started_at` 且等于 `L[0].signed_at`，链条自洽（首项 `from` == `exemption_start_origin`，第 i 项 `from` == 第 i-1 项 `to`），数组 append-only；空 ⇒ `exemption_start_origin == exemption_started_at`。**归一化口径（v19/次要 4，写死一种）**：`signed_at` / `exemption_started_at` / `history[].from|to` 统一序列化为 **`YYYY-MM-DDTHH:MM:SSZ`**——UTC、`Z` 后缀、**无小数秒**；比较一律按这个形态逐字节。**一个输入只出一个码（v22/I-3，按下面优先级取第一条命中；v24/B-1 形态先于等值）**：(a) **只判锁内字面值形态**——`exemption_started_at` 出现 `+00:00` 时区写法或带小数秒（`.123Z`、无 `Z`）⇒ **`exemption_start_signed_at_not_canonical` FAIL**；**`L[0].signed_at` 等任何封条 blob 的形态不归本夹具**，一律由 T-29 的 `signed_at_not_canonical` 判。(b) 涉及审计链与先后关系的（④⑤⑥⑦）⇒ **`exemption_start_history_broken` FAIL**；(c) ①–③ 中的纯等值 / 链首缺失 ⇒ **`exemption_start_conflict` FAIL**，`detail.kind ∈ {not_equal_signed_at, moved_from_chain_mismatch, chain_head_missing}`——**`detail.kind` 不得出现 `not_canonical_or_mismatch` 这类把主码塞进 detail 的取值**（v22/I-3 删除；v27/次要 1 统一为 `detail.kind`）。**形态失败即跳过整个 conflict 组（v24/B-1；v25/次要 1）**：`exemption_started_at` 或 `L[0].signed_at` 任一形态不合法 ⇒ **不报** `exemption_start_conflict` **及其 `detail.kind` 分支（`moved_from_chain_mismatch` / `chain_head_missing`）**，只报对应的形态码（前者本码、后者 `signed_at_not_canonical`），避免连锁双码。**不再是** v15 的「新封条 `signed_at` 晚于旧值 ⇒ `seal_move_payload_mismatch`」，也**不再是** v17 的「`≤ %cI L[0]` 当外部上界」；`exemption_started_at` 仍**不以锁历史首版为主判据**——锁历史最早版本是 `exemption_start_origin` / `first_seen_origin` 的锚（v23/I-1），本字段只认封条字节等值 |
| T-29 | **`signed_at` 规范形态（v20/重要 4；v21/I-3 补范围与续签口径；v22/I-2 改校验点为封条 blob）**：① 写侧**签发**与**续签**后分别读回 `signed_at`（续签必须**重写**为自己的签署时刻，不得复制旧值；换路径 `moved_from` 才沿用旧值）；② 手工把**链上某一枚封条 blob** 的 `signed_at` 改成 `2027-03-31T00:00:00+00:00`（或 `...T00:00:00.123Z`、`...T00:00:00`）后跑 `check`。**校验点 = 链上每枚封条 blob 的 `signed_at`**（读侧从 HEAD 封条的 `previous_seal_commit` 逐级取 blob，含 `L[0]` 那枚）——**不是「当前锁 `L` 的全量封条」**：`L` 是封条**提交**序列、不在锁里，锁里没有可被改的 `signed_at`。**只钉两态（可构造）**：(i) `N == 1` ⇒ **amend 唯一一枚封条提交**（`git commit --amend` 改该文件），即覆盖 `L[0]`；(ii) `N > 1` ⇒ **amend 最新续签提交**（v25/次要 3：**不是字面 `HEAD`**——S-26 后置 `lock --update` 之后 HEAD 是锁提交、不一定封条），只改该提交那枚 blob，前链不动。**中间续签明确标注「不可构造」**：要改第 k 枚（`0 < k < N-1`）必须重写其后的每一次提交，`previous_seal_commit` 链与 `blob@L[0]` 等式会先红（落 `renewal_chain_broken`），因此**不设该变体**，也不要写「覆盖中间封条」的夹具 | ① ⇒ **PASS**，值匹配 `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$`（写侧单源 `strftime("%Y-%m-%dT%H:%M:%SZ")`，**不得** `isoformat()`）；② 的 (i)(ii) 两态 ⇒ **FAIL `signed_at_not_canonical`**（exit 1、进 `errors[]`），**不做语义等价换算**。判据对**读侧逐级取出的每枚 blob** 逐一执行——(i) 证明 `L[0]` 那枚在范围内，(ii) 证明 HEAD 那枚在范围内，两者合起来覆盖「不只查 `L[0]`」。**`L[0]` 的形态归属（v24/B-1）**：`L[0].signed_at` 不合法 ⇒ **`signed_at_not_canonical`**（通用封条形态码），**不得**落 `exemption_start_signed_at_not_canonical`；后者只管锁里的 `exemption_started_at` 字面值。**形态先于等值**：`L[0]` 或 `exemption_started_at` 任一形态失败 ⇒ T-28 的等值比较跳过、不报 `exemption_start_conflict`（避免连锁双码）。**无 grandfathering**：C 批未上线、HEAD 无已入库封条，规则生效即 fail-closed |
| T-30 | **锁内自述值的外部锚（v23/I-1/I-2；v24/B-2 补⑤；v25/I-3/I-4 补⑥、删「重排」）**，六变体：① 单次提交把某键的 `exemption_start_origin` 改成任意别的规范时间（其余不动）⇒ **FAIL `exemption_start_origin_rewritten`**；② 单次提交把 `first_seen_origin` 重置成「今天」（其余不动）⇒ **FAIL `first_seen_origin_rewritten`**；③ 单次提交把 `exemption_start_history[]` **删一项 / 改一项**，使后版本不是前版本的前缀扩展 ⇒ **FAIL `exemption_start_history_broken`**（版本前缀单调）。**「重排」子变体已删（v25/I-3）**：1 条时重排是恒等变换、≥2 条与 I-1 同因不可端到端构造；前缀单调改由 **T-33 纯函数单测**覆盖；④ **回填夹具（I-2）**：老锁（**必须是 `schema_version: 2` + 封条形态**；v24/次要 3：v1 清单配封条会先撞 ⓪-2 `lock_v1_with_seals`，造不出本变体）缺 `exemption_start_origin` / `exemption_start_history` / `first_seen_origin`，跑 `lock --update` ⇒ **补 `origin = 原 started_at` 的值、history = `[]`、first_seen_origin = 当前封条 `first_seen_at`**，其余字段逐字节不变，`check` PASS；**已有值不被改写**（有值时 `lock --update` 后逐字节相同）；⑤ **存量锚非死码（v24/B-2）**：跑完④的回填后再**单次提交**把 `first_seen_origin` 改成「今天」⇒ **FAIL `first_seen_origin_rewritten`**；同构变体：回填后单次提交改 `exemption_start_origin` ⇒ **FAIL `exemption_start_origin_rewritten`**（锚顺延到回填提交，之后被改即露）；⑥ **初值防护（v25/I-4；v26/S-11 写明构造）**：首签时把封条载荷的 `first_seen_at` 写成**未来值**、锁键 `first_seen_origin` 照抄 ⇒ `first_seen_origin > L[0].signed_at` ⇒ **FAIL `first_seen_origin_rewritten`**（`detail.kind = "after_signed_at"`）。**构造写法**：建键时一次写成、**不事后 amend 载荷**——首签没有前一版封条（规则 7 不适用）、`first_seen_at` 也不在 `requirements_digest` 覆盖内，因此**不需要重签**；若事后 amend 已签封条，会改 `L[0]` SHA、使 `epoch_origin` 失配（③ 链级码），虽按判序 ② 先于 ③ 仍报 ②，但覆盖集已变脏、夹具不再单测本码。锚取法统一走 §1.1.3「资产根」⑦（`git log -m --full-history --reverse HEAD -- atlas.solution.lock.json`，标量类取「首个同时含该字段的版本」），存量缺字段不判 rewritten | ①②③⑤⑥ 各 FAIL（对应 `errors[]`、exit 1）；变体④ PASS 且字段值断言齐全；⑤ 专治「存量键两码永不 FAIL」；⑥ 专治「初值写晚」；对应 §8 的锚口径条目 |
| T-31 | **`internal_error` 兜底（v23/次要 2）**：在干净基线上给某条判据注入一个**非 `SolutionError`、非三类解析异常**的未知异常（例：猴子补丁让 `validate_value` 抛 `TypeError`），跑 `solution check --json` ⇒ **exit 2**，stdout 是**合法 JSON**（`ok: false`、`errors[]` 恰一条 `{code: "internal_error", path: null}`、`not_run[]` 从抛异常处填满剩余段），**不得**出现裸 traceback。对照：注入一个 `SolutionError` ⇒ 走它自己的业务码（不是 `internal_error`）；用法错误（如 `--lenient` 遇到封条）⇒ exit 2 且 stdout 首行是**人类可读文本**、不是 JSON（消费方按首字符区分，§3.2）。**实现状态（v36/次要 4 更正；v35 的「待补齐」已过期）**：`scripts/atlas_check.py` 只是聚合巡检器，真正的 `check` 入口是 `scripts/atlas_solution.py`；`_internal_error_report` / `_emit_internal_error` **已实现**（`:240-274`，`check` 包装 `:369-370`）——未知异常 ⇒ exit 2 + 合法 JSON（`schema_version: 2`）+ `errors=[internal_error]` + `not_run` 六项，与本节六段名逐字一致；夹具见对应测试。落点 `scripts/atlas_solution.py` / `_support/solution.py` 的顶层 try，**不得**在解析层或单条规则内部捕获 `Exception` | exit 2；合法 JSON 或纯文本按上面区分；`internal_error` 恰一条；不吞 `SolutionError`；无裸 traceback |
| T-32 | **`due` 读侧越界（v24/I-3；v25/I-2 日期层；v26/B-1 端点对齐 V-20）**：① 用 **`git commit --amend` 改 HEAD 落盘**（同 T-29；**不得新开提交**——新提交会让 `N` 加一、触发 `renewal_seq != N` 抢码），把一枚已签封条的 `due` 改到闭区间外（例：`due = 2027-03-31` 早于 `origin` 的 UTC 日期，或 `due = first_seen_origin + 91d`，或 `due > acceptance_cutover`）⇒ **FAIL `exemption_due_out_of_range`**；② 存量回填造出的 `exemption_start_origin > due`（`origin` 取自已重指的 `started_at`）⇒ 同码；③ **三条端点（必须通过；判据见下），各钉死 `min(trunc_utc_date(first_seen_origin) + 90d, acceptance_cutover)` 的一支**——`d = trunc_utc_date(first_seen_origin)`，且三条都必须满足 `first_seen_origin ≤ L[0].signed_at`（否则先撞 `first_seen_origin_rewritten`，`detail.kind = after_signed_at`，判序 ② 里它先于 `due`）：**③a 早于默认的 `cutover`（`cutover` 支）**：`acceptance_cutover = 2027-01-31`（**早于包级默认 `2027-03-31`，§5.1 明确允许收紧、无「不得早于今日」下界，故无需 `--anchor-review`**），**清单与锁两侧同写该值**（`atlas.solution.yaml` 与 `atlas.solution.lock.json` 的 `acceptance_cutover` 必须相等——B-0 起 `lock --update` 已把该字段写进锁（清单 v2 ⇒ 锁 v2），只改清单会先撞 `acceptance_cutover_mismatch`、锁侧缺失会先撞 `acceptance_cutover_missing`，两者都抢在 `exemption_due_out_of_range` 之前）；**形式可执行五步（v29/B-3；v30/I-1；v32/B-1 改 `init --cutover`；v33/B-1 补 PRD 提交步、首锁 `null` 与 reader 门；v34/阻断 1 改两态、删「今天真能跑」）**：**前置**：**全新空仓 + 已提交的 `product/prd/solution-prd.md`**——HEAD 无 `atlas.solution.yaml`（`init` 见到该文件即 `SolutionError`，「已迁移仓」这个前置删除）+ 无封条（`seal_anchors` 为 `null`、HEAD 无 `*.seal.json`）；PRD 若由 `init` 生成骨架，**必须在第③步先提交**，`lock --update` 只认「已提交的 PRD」。**两态（v34/阻断 1）**：**产品路径**要等 B 批发版后（`.atlas/VERSION` ≥ 0.4.0）才能执行 `init --cutover`；**测试路径**可预置 `.atlas/VERSION=0.4.0` 起步（仓内原本无 `.atlas/`，不预置则回落到工具包 `0.2.0-beta.33`、第①步即 exit 2），但这是**夹具前置、不是产品可达路径**，不得据此宣称端点今天能在真实仓上跑。**不启用第二份二进制，但 reader 版本仍决定清单版本**：`init --cutover` 只在 reader ≥ 0.4.0 写 v2；reader < 0.4.0 下显式 `--cutover` **必须报错拒绝（exit 2，用法错误），不得静默丢弃**（实测 `.atlas/VERSION=0.3.0` 下原本 rc=0、清单 `version: 1`、无 `acceptance_cutover` 键）。① `atlas solution init --name demo --member <m>=<path> --cutover 2027-01-31`——清单写 `version: 2` + `acceptance_cutover: 2027-01-31`；`init` 同时写 **PRD 骨架（未跟踪）** 与**首锁**，首锁的 `acceptance_cutover` 是 **`null`**（`lock_payload` 只在 `definition.commit` 非空时才写该值）；早于默认属收紧 ⇒ 无需 `--anchor-review`（V-20⑦），也无 `--to 2`（没有 v1 基座）；② **首签载荷一次写死**——`signed_at = first_seen_at = first_seen_origin = 2026-11-05T00:00:00Z`、`due = 2027-01-31`，全部手写常量（**不经 `now`、不 amend**）；③ **提交 PRD、清单与配置（v33/B-1①；v34/重要 1 补全 add 集合）**：先在夹具仓写 `.gitignore`（内容 `.atlas/`）并给成员仓一次初始提交（`git -C <member> commit --allow-empty -m m0`），再 `git add -A && git commit`——覆盖 `product/`（或 `--assets-root` 的取值，`product` 只是默认）、`atlas.solution.yaml`、`atlas.config.yaml`、成员仓 gitlink 与 `.gitignore`。`.atlas/` **不入库**（装配产物）；**干净口径 = `git status --porcelain` 为空**（`.atlas/` 已被忽略），复验命令 `test -z "$(git status --porcelain)"`。**只 `git add product/ atlas.solution.yaml` 不够**——实测仍剩 `?? .atlas/`、`?? atlas.config.yaml`、`?? web/`；`lock --update` 的定义源脏检查只认 `definition.path`，PRD 未跟踪即 `[FAIL] 定义源工作树不干净（?? product/prd/solution-prd.md）`，**这一步不能省**，「步骤间无需提交」不成立；④ `lock --update`（**C 批写入口**）——此时 `definition.commit` 非空 ⇒ 写 **v2 锁**、写入 `acceptance_cutover = 2027-01-31`；**`seal_anchors` 键的写入属 C 批**（依赖 `seal freeze` 写入口）——在该入口落地前锁里**没有**该键，`check` 的 PASS **不构成 `due` 已评测**：**`due` 用的是本次写入的值**（首锁是 `null`，这是第二次 lock）；⑤ **锁提交（v32/I-1）**：`git add atlas.solution.lock.json && git commit`，让 HEAD 清单与 HEAD 锁同源；否则新克隆 / CI 报 `acceptance_cutover_mismatch`；**锁提交后 `test -z "$(git status --porcelain)"` 复验一次**（干净口径同上）。**锁侧两态写死**：PRD 未提交 ⇒ `lock --update` 硬拒、不产锁；PRD 已提交 ⇒ 写 `2027-01-31`；`init` 首锁的 `null` 只作构造起点，不作为端点通过依据。**语义现状（v34，必须如实写）**：封条载荷不含 `definition.commit`，②→④ 不产生 `definition_commit_mismatch`；但**把第②步整段删掉，第④步与 `check` 的输出完全不变**——今天没有任何代码读取首签封条的 `signed_at` / `first_seen_at` / `due`（`seal freeze` 未落地、锁无 `seal_anchors`）。所以这五步是**形式可执行**、**语义尚未接通**：`due` 的评测要等 C 批写入口落地，不能拿本夹具的 PASS 当 `due` 已验证。**`signed_at` 必须钉死、不得用运行时 `now`**（否则 2027-02-01 之后 `origin` 日期 > `due = 2027-01-31` 会自动翻红；与 `first_seen_origin` 同值也保证 `origin == signed_at`、不触发 `after_signed_at`），`d + 90d = 2027-02-03 > 2027-01-31` ⇒ `due = 2027-01-31`（= `cutover`）⇒ **exit 0 + `errors[]` 为空 + 命中 `checks[]` 中 `check == "验收切点"` 的项**（**`--json` 断言 `checks[]`，不断言 stdout 文本**——`--json` 模式没有那行；纯文本模式的两个子串是 `"验收切点:"` 与 `"（清单与锁一致）"`，实测为**半角冒号**且中间夹 `acceptance_cutover=<v>`。**本端点不断言 `overall == PASS`**：实测 `overall = WARN`，来自 E2E 未初始化 / 模板骨架 / 成员无资产，与 `due` 无关），区间 `[2026-11-05, 2027-01-31]` 永久成立；**③b 延展支（`cutover` 支，未来值构造）**：`acceptance_cutover = 2027-04-15`（**晚于包级默认 `2027-03-31`**，须同时挂 `--anchor-review <REVIEW-ID>`；未超硬顶 `2027-06-29`，等于硬顶的 PASS 由 V-20⑤ 单独覆盖），**清单与锁两侧同写 `2027-04-15`**（步骤同 ③a 五步、**同样从全新空仓起步**；不启用第二份二进制，但 reader 版本决定清单版本——① `init --cutover 2027-04-15 --anchor-review <REVIEW-ID>` → ② 首签载荷一次写死 `signed_at = first_seen_at = first_seen_origin = 2027-04-15T00:00:00Z`、`cutover = due = 2027-04-15` → ③ **提交 PRD、清单与配置（`git add -A`，同 ③a）** → ④ `lock --update`（首锁 `null`，本次才写入 `2027-04-15`；同样不建 `seal_anchors`，见 ③a 语义现状）→ ⑤ 锁提交，两处 review 值一致）；该支绕不开未来时间戳（需 `d ≥ 2027-04-01`），故**首签时把封条 `signed_at` 与 `first_seen_at` 同写成 `2027-04-15T00:00:00Z`**（形态合法；**无规则禁止未来 `signed_at`**，`%cI` 越界只作 WARN/INFO），`first_seen_origin` 建键时照抄 `first_seen_at`（`= L[0].signed_at`，不触发 `after_signed_at`），**不事后 amend 载荷**（事后 amend 会改 `L[0]` SHA、撞 `epoch_origin`）；`d + 90d = 2027-07-14 > 2027-04-15` ⇒ `due = 2027-04-15`（= `cutover`）⇒ **exit 0 + `errors[]` 为空 + 命中 `checks[]` 中 `check == "验收切点"` 的项**（**`--json` 断言 `checks[]`，不断言 stdout 文本**——`--json` 模式没有那行；纯文本模式的两个子串是 `"验收切点:"` 与 `"（清单与锁一致）"`，实测为**半角冒号**且中间夹 `acceptance_cutover=<v>`。**本端点不断言 `overall == PASS`**：实测 `overall = WARN`，来自 E2E 未初始化 / 模板骨架 / 成员无资产，与 `due` 无关）；**③c `+90d` 支**：`acceptance_cutover` 取默认 `2027-03-31`，`first_seen_at`、`first_seen_origin`、`signed_at` 同写 `2026-11-05T00:00:00Z`（**同样不用运行时 `now`**，否则 2027 年起该支会翻到 `cutover` 支、`+90d` 分支失去覆盖），`d + 90d = 2027-02-03 < 2027-03-31` ⇒ `due = 2027-02-03`（= 时间戳那一支）⇒ **exit 0 + `errors[]` 为空 + 命中 `checks[]` 中 `check == "验收切点"` 的项**（**`--json` 断言 `checks[]`，不断言 stdout 文本**——`--json` 模式没有那行；纯文本模式的两个子串是 `"验收切点:"` 与 `"（清单与锁一致）"`，实测为**半角冒号**且中间夹 `acceptance_cutover=<v>`。**本端点不断言 `overall == PASS`**：实测 `overall = WARN`，来自 E2E 未初始化 / 模板骨架 / 成员无资产，与 `due` 无关），该构造永久成立。**三条端点（③a/③b/③c）的步骤里删掉所有 `--amend`（v29/B-3；① 的 amend 是有意的篡改构造，不在此列）**：① 首签 `--amend` 会改 `L[0]` SHA，而 `epoch_origin` 与不可变的 `exemption_start_origin` 都指旧 `L[0].signed_at` ⇒ 必在 ③ 段红或触发 `exemption_start_history_broken`；② `lock --update` 若写在签封条之前，此时无封条不建 `seal_anchors` 键，签完又没有第二次 `lock --update` ⇒ 键永不出现，C 批期望 PASS 的仓必须有键。**唯一允许的 amend 是 `N > 1` 时 amend 最新续签提交、且不得动 `L[0]`**（同 T-29）。**超限 `2027-06-30` 只留一条 FAIL 反例、不再兼作端点**（`2027-06-30 > cutover_max = 2027-06-29`，V-20 已把它排除在合法区间外，故不可能 PASS）；④ **出口验证**：对①的仓续签一枚新封条、把 `due` 写回区间内 ⇒ `check` 恢复 exit 0 + `errors[]` 为空（`overall` 可为 WARN；证明可修复、不是永久红） | ①② 与「超限 `2027-06-30`」⇒ **FAIL `exemption_due_out_of_range`**（`path` 指封条、exit 1）；③a/③b/③c 三条都满足 **exit 0 + `errors[]` 为空 + `checks[]` 命中 `check == "验收切点"`**（纯文本模式看 `"验收切点:"` 与 `"（清单与锁一致）"` 两个子串；**不比较 `overall`**）；④ 由 FAIL 转为同一形态（exit 0、errors 空）。**比较全在日期层**：`due` 一律 `YYYY-MM-DD`；下界取 `exemption_start_origin` 的 UTC 日期；上界**先截日期再加 90 天**——`d = trunc_utc_date(first_seen_origin)`（`date`），`upper = min(d + timedelta(days=90), acceptance_cutover)`，全程 `date`，禁止时间戳与日期直接比、禁止本地化后再加。**缺 `first_seen_origin` 时**只跳过 `d + 90d` 一支，`acceptance_cutover` 上界照判（§5.1 第 3 条）；本夹具须在回填后跑 |
| T-33 | **`exemption_start_history[]` 前缀单调的纯函数单测（v25/I-1；v26/I-1/S-10 挂签名、移入 B-0）**：断言直接挂在 §1.1.3「资产根」⑦ 数组 C 的签名上——`check_history_prefix(versions: list[list[Entry]]) -> Ok | Err(code, detail)`，`Entry = {from, to, commit}`、`versions` = 按 `git log -m --full-history --reverse` 顺序逐版本解析出的 `exemption_start_history[]` 序列（**没有该路径的提交按 §1.1.3 ⑦ 构造②跳过、不产生版本**，v30/B-1；构造由 `build_lock_versions` 负责）。给三份**合成 `versions`**（v1 空数组 / v2 一项 / v3 两项），**直接喂函数**，不经 git、不经 CLI、不读仓库。变体：① v3 不是 v2 的前缀扩展（或 v2 删项、v2 改项）⇒ 断言 `Err("exemption_start_history_broken", …)`；② 合法的 v1→v2→v3 递增 ⇒ 断言 `Ok` | ① ⇒ `Err(code = "exemption_start_history_broken")`（纯函数级返回，不产生 CLI 报告）；② ⇒ `Ok`。**归属 B-0**（v26/S-10：零依赖，不归 C、不依赖 B）——§6 B-0 清单唯一落点，§6 C 已移除。**注明：不走 git、不是端到端夹具**——前缀单调只依赖锁版本内容，不需要真实 `seal reanchor` 链，故不依赖 S-18 / S-26；与 S-55① 分工：S-55① 测 ⑤，本夹具测前缀单调。**`check` 侧只负责构造 `versions` 并喂入，判据本体零 git 依赖**；实现不得让函数读文件或跑 `git`，否则本夹具失去意义。**另验 §1.1.3 ⑦ 的四种输入边界（v27/I-1）**：`versions == []` ⇒ `Ok`、单版本 ⇒ `Ok`、缺键 ⇒ `[]`、`seal_anchors` 为 `null` / 非 dict ⇒ `[]` 且不抛异常；**去重不进本夹具（v29/I-1）**——函数签名里没有 SHA，喂 `[[x],[x]]` 时去重与不去重都返回 `Ok`、断言无法区分；`-m` 多父的 `%H` 去重是构造层清理动作、不产生判据，要测就测 `build_lock_versions`（B-0 同级纯函数，v32/I-2） |
| U-01 | 上游 PRD 改一字节 | FAIL stale |
| U-02 | 上游删除 | FAIL「已删除」 |
| U-03 | 文档宣称 seal 证明 apply 跑过 | 文本判据失败 |
| U-04 | `upstream` role 越界 | FAIL |
| U-05 | 上游 role 路径不在规定解析 | FAIL |
| U-06 | 只改版本号、字节不变 | PASS |
| U-07 | `atlas-apply.md` 改错别字 | PASS（有意不绑） |
| U-08 | 成员工作区缺席 / 卡未跟踪 | 缺席默认 FAIL、`--lenient`（仅无封条）SKIP；未跟踪默认 FAIL（C 批起无宽限） |
| U-09 | fresh clone：有锁、无成员工作区、无封条 | `--lenient` 允许执行（`member_workspace_absent` SKIP），不因「有锁」exit 2（Q-6） |
| S-01 | legacy 无白名单条目 | FAIL |
| S-02 | 白名单 `frozen_at` 晚于 cutover | FAIL |
| S-03 | 冻结后改白名单无评审 | 拒绝 |
| S-04 | legacy due 晚于 cutover | FAIL |
| S-05 | 未跟踪 `.trellis` 的仓声明 legacy | 可用（走白名单） |
| S-06 | backfill 缺 `first_seen_at` | 拒绝 |
| S-07 | 重新 backfill 重置 `first_seen_at` | 拒绝 |
| S-08 | backfill due 超 90 天 / cutover | 拒绝 |
| S-09 | 新任务进 legacy 带 REVIEW + 锁更新 | PASS（决策 1） |
| S-10 | 新任务进 legacy 无 REVIEW | 拒绝 |
| S-11 | 白名单 `frozen_at` 晚于锁 `allowlist_frozen_at` | FAIL |
| S-12 | 联邦成员各持一份 allowlist | 拒绝（集中父仓一份） |
| S-13 | 删封条后重建 `seq=1 / first_seen_at=今天` | `seal_history_reset` FAIL（`L[1:]` 有 D） |
| S-14 | 浅克隆（`fetch-depth: 1`）下校验链 | **hard FAIL `chain_unverifiable`，不可降级**（v19/阻断 3：第 0 步不在 `--allow-unverifiable-chain` 的降级清单里——降级后 `UH` 偏小、路径级断言跟着放行）。**对照**：只有「对象本地缺失」那一支（S-15 偏远的 `previous_seal_commit` 对象被剪）才允许该开关降 WARN |
| S-15 | `previous_seal_commit` 对象在但 sha 不符 | `renewal_chain_broken` FAIL |
| S-16 | `previous_seal_commit` 下无封条 | `seal_missing_at_commit` FAIL |
| S-17 | 原地改写：`seq` 回 1、`previous_*` 置 null、`first_seen_at` 改今天，单次 M 提交 | `renewal_seq != N` / `renewal_chain_broken` FAIL |
| S-18 | rebase 后未 reanchor | 先判第 4b 步 ⇒ `reanchor_record_missing`（锁有锚、封条无 `reanchor`）；锁无锚时才是 `renewal_chain_broken`（字节未变、D=0，`previous_seal_commit` 指旧 SHA）；带 `--review --from-a` 且旧 A 不可达 ⇒ reanchor 后**立刻** `check` PASS（`seq == base_seq + (N - base_n) - 1`，Q-2）。**构造要求（v10/次要 5）**：先在原仓产生真实 A 并 `lock --update` 记 `epoch_origin = A`；重写后在 **fresh clone** 里确认 `git cat-file -e A` **失败**，再 reanchor。不得用一串从未存在过的 40-hex 冒充（那只测到 `reanchor_not_allowed` 的反面）。随后必须按 S-26 做后置 lock，**不得把「立刻 PASS」误读成「不需要后置 lock」** |
| S-19 | add/add 冲突在 merge 中解决（两个分支各一个 A、零 D） | `seal_history_ambiguous`（要求重签），不是 reset；按**提交数**断言，`AA` 只算一个提交（Q-1 次要） |
| S-20 | shallow 仓库（`git rev-parse --is-shallow-repository` 为真） | 先判仓库形态 ⇒ **`chain_unverifiable` hard FAIL（v19/阻断 3：不在降级清单）**，**不进 A/D 分支、不进 ⓪、不进第 1 步**（防「删+重建落在浅边界外」假绿）。**`--allow-unverifiable-chain` 不改变本行结果**；将来放宽的唯一形态是「整段跳过 ⓪ 与第 1 步、路径级/根级全 SKIP」，不许降级后继续算——本稿不实现 |
| S-21 | 主干未改封条、PR 分支把封条改到 `seq=2`，`merge --no-ff` | PASS；merge 的 `git show --format= --name-status` 为空 ⇒ 从 `L` 剔除，`N=2`（Q-1） |
| S-22 | 冲突解决 merge 手写新封条字节（`MM`，不等于任何父） | `seal_merge_conflict` FAIL；改为取一侧字节 + 独立续签提交（`seq = 提交后的 N`，`previous_seal_commit = 提交前 L[-1]`，**断言该值等于提交后的 `L[-2]`**）⇒ PASS（Q-1/I1） |
| S-23 | reanchor 一次后**再**做一次续签，并把该续签的 `previous_seal_commit` 指向更早、仍带封条且 sha 对得上的提交（`seq = 提交后的 N`） | `renewal_chain_broken` FAIL（豁免只作用于 reanchor 提交本身，规则 5/8 对后续续签照常执行，B1） |
| S-24 | 伪造 reanchor：任意续签写 `{base_seq: 当前 seq, base_n: N-1, from_a: 随机 sha}`，并顺手改 `e2e.cases[]` / `gap` / `owner` | `reanchor_payload_mismatch` FAIL（**五字段**之外必须与 `L[-2]` 逐字节相等，且边界 `previous_seal_sha256` 必须为 `null`，v9/B1；v10 补第五字段） |
| S-25 | 伪造 reanchor：载荷不变、`from_a` 仍是随机 sha、`base_seq/base_n` 按当前值拼 | `reanchor_anchor_mismatch` FAIL（`from_a != seal_anchors[S].epoch_origin`，v9/B1）；`seal_anchors` 为 null 或无键 `S` ⇒ `reanchor_anchor_missing`；锚与 `L[-2]` 不同步 ⇒ `seal_anchor_stale`（**成立即抑制 mismatch**） |
| S-26 | 合法 reanchor 提交 `R` 上 `check` PASS；在 `R` 上跑 `lock --update`（`epoch_origin = R`），**独立提交**只改锁的 `R2`；对 `R2` 求值 | **PASS**：`R2 ∉ L` ⇒ `HEAD != R0` ⇒ 第 10 步整段跳过；`seq == base_seq` 仍成立，第 4 步通过（v10/B-1，修 v9 的 `reanchor_anchor_mismatch` / `seal_anchor_stale` 死路） |
| S-27 | 合法 reanchor 后，下一次续签把 `reanchor` 整段删掉、其余照常（`seq = 新 N`） | `reanchor_record_missing` FAIL（锁内 `epoch_origin != L[0]` 要求封条必须带 `reanchor`，v10/B-2；v9 此处 PASS） |
| S-28 | 非边界续签把 `reanchor.from_a` 换成随机 sha（其余字段不变，`seq = 新 N`） | `reanchor_record_mismatch` FAIL（第 4b 步：`L` 中 `seq == base_seq` 的那枚提交的 `reanchor` 与当前不逐字节相同；v9 因 `HEAD != R0` 跳过第 10 步而 PASS） |
| S-29 | 浅克隆：`git clone --depth 1` 后执行 `seal reanchor --review --from-a <被剪掉的 R1>` | **非零退出**（预检 `--is-shallow-repository` 为真即拒，v11/阻断 2）；若放行，签出第二纪元 + 合法后置 lock 后 `HEAD != R0`、第 10 步跳过 ⇒ 实测 PASS，故必须在入口拦 |
| S-29b | partial clone：`git clone --filter=blob:none` 后执行 `seal reanchor` | **非零退出**（v12/阻断 2：探测用 `git config --get-regexp '^remote\..*\.promisor$'` / `extensions.partialClone` / `objects/pack/*.promisor`，任一命中即拒；**不得**用 `git rev-parse --is-partial-clone`——该选项不存在，实测 exit 0 原样回显）。严重度低于 S-29：partial 缺 blob 本会让第 5/9 步自然红，这里是纵深防御 |
| S-30 | 多纪元回滚：第二纪元 reanchor（`base_seq=5, base_n=4`）后，一次普通续签把 `reanchor` 回滚成**第一纪元**那条合法记录，`renewal_seq` 调到 `6`（满足公式） | `reanchor_record_mismatch` FAIL（4b 的全量扫描按 `seq == base_seq` 定位到第一纪元 `R0`、逐字节相同，但 `review` 外部锚对不上 `seal_anchors[S].anchor_review`，v11/重要 1；v10 此处 PASS） |
| S-31 | 换封条路径（**旧文件保留**形态）：旧路径保留封条、新路径首签（`renewal_seq=1`，记 `moved_from: {path, sha256}`），`lock --update` **新增**新路径键（`epoch_origin = 新 L[0]`、`state: active`）、旧键标 `state: retired` + `moved_to` 保留 | **PASS**（新路径按新键判；旧路径按 `retired` 判据：`L_pre = L` 无删除、规则 0–7 PASS；v12/阻断 1；v13/R12-4 明确 `retired` 判据）。旧文件**删除**的形态由 S-36 覆盖 |
| S-31b | **前置（R12-3 写死）**：接 S-31，且旧路径本来就有**合法 `reanchor`**（旧路径 `epoch_origin != L_old[0]`、`anchor_review != null`）并在换路径前跑过后置 `lock --update`；在此前提上，**旧路径**删掉 `reanchor` 字段（其余照常续签） | **FAIL `reanchor_record_missing`**（v12/阻断 1：旧键仍约束旧路径）。**缺前置时该夹具不可判**：旧路径从未 reanchor 过时，删一个不存在的字段是 no-op，规则 1 的「必须带 `reanchor`」前提（`epoch_origin != L[0]`）不成立，必然 PASS——这不是漏判，是夹具构造错误。可由 S-30 的仓接续构造 |
| S-32 | **前置**：两枚封条（`member-a/T-1`、`member-b/T-2`），两路径各自 `lock --update` 时**必须带 `--seal <path>`**（多封条不给 ⇒ S-37 的 exit 2）；互不搬锚；两路径各自续签 | **均 PASS**，且两次 `lock --update` 后锁里两个键的 `epoch_origin` / `n` 各自只变自己那份（v12/阻断 1；单槽锚会互相覆盖；v13 补 `--seal` 前置） |
| S-33 | **前置（R12-3 写死）**：接 S-31/S-31b，且旧路径有 **≥2 个纪元**（至少两次合法 `reanchor`、`anchor_review != null`，可从 S-30 的仓接续构造）；在此前提上对**旧路径**做多纪元回滚（回滚成第一纪元合法 `reanchor`） | **FAIL `reanchor_record_mismatch`**（旧路径的 `anchor_review` 仍生效）。**缺前置时该夹具不可判**：只有一个纪元时 4b 的 `review` 外部锚没有第二个值可比，回滚段与当前段相同，必然 PASS |
| S-34 | `seal_anchors` 缺键 / 多键：删掉某条**历史出现过**的封条路径的键；或保留一个**从未在 `U` 里出现**的路径键 | `seal_anchor_path_unmapped` / `seal_anchor_path_orphaned` FAIL（T-20/T-21；v13：判据是 `U`，不是 HEAD 文件） |
| S-35 | 换路径重建：新路径记 `moved_from`，但 `moved_from.path` ∉ `U` / 旧路径 `L_pre` 不 PASS / `moved_from.sha256` 与迁出前最后一枚封条字节不符 | `seal_path_history_lost` FAIL（T-22，v12/重要 3；v13 取消「旧路径 HEAD 必须仍有文件」） |
| S-36 | **R12-1 的核心反面包**：合法成员改名——删旧封条文件 + 删旧键 + 只新增新路径键（`state: active`、`moved_from` **不写**）、task-id 保持不变；`git commit` 一次完成（键与文件同删，`D` 在旧路径 `L` 里但旧键已不在） | **必红**。首报码按 R12-6 优先级：`U` 有旧路径而键缺 ⇒ **`seal_anchor_path_unmapped`**（路径级）；若把旧键补回但留 `active` ⇒ `seal_anchor_path_state_mismatch`；若标 `retired` 却没有 `moved_from` 覆盖 ⇒ `seal_path_history_lost`。**三种任一都不得 PASS**。v12 在此场景全绿：键集 == HEAD 封条路径，旧路径同时从文件面与键面消失，集合仍相等、循环无旧路径、`D>0` 不计算、task-id 不变所以 `seal_absent` 也不触发 |
| S-37 | 多封条仓执行 `lock --update` / `seal reanchor` **不给 `--seal <path>`** | **exit 2**，并**列出全部候选路径**（排序稳定）；不得默认选一枚（v13/次要 11）。给了 `--seal` 但不在 `U` ∪ 键集 ⇒ `seal_anchor_path_orphaned`，不是「按名字新建」。**前置（v14/N-4）**：需多封条仓，**可由 S-31 接续构造**（换路径后新旧两枚并存）或 S-32；单封条仓里「不给 `--seal`」恒 PASS，不构成反面包 |
| S-38 | 合法 `frozen`（删任务、文件保留）：**由 `seal freeze --seal <path> --at <L[-1]>` 写锁**（只改 `state: frozen` 与 `frozen_at`，封条字节不动）、独立提交后 `check` PASS 并打 `seal_frozen: <path>` INFO；随后在该路径上**改一字节**或**删除文件**再 `check` | 前者 **PASS**（`git log <frozen_at>..HEAD -- <path>` 为空、blob 相等）；后者 **FAIL `seal_frozen_modified`**（T-24；删除与改写同码）。两者都不出现 `seal_history_reset`（冻结前的 `L_pre` 无 `D`）。**前置（v14/N-4/I-1）**：可由 S-31 接续构造（把 `active` 键冻结），**不再靠手改锁**造 `frozen` |
| S-39 | **B-1 正向**：封条只在侧支新增，main 上 `git merge -s ours side`（HEAD 树内 seal 数 0），随后在同一提交里把锁里的键也删掉 | **必红**：`U` 必须仍包含侧支那条（靠 `--full-history`），键缺 ⇒ `seal_anchor_path_unmapped`。v13 原命令（无 `-m --full-history`）在此形态输出空，键集也空 ⇒ 路径级/状态机/链级全不触发、S-36 的假绿原样复现（v14/B-1） |
| S-40 | **B-1 反向**：merge 提交里新增一枚封条（冲突解决时加两侧都没有的 `billing/T-9.seal.json`），随后 `lock --update --seal <该路径>` | **能建键**（PASS）：`U` 必须包含该路径——只有 `-m` 才看得见 merge 的新增；缺 `-m` 时 `U` 不含它 ⇒ `seal_anchor_path_orphaned`，新封条的键永远建不了（v14/B-1） |
| S-41 | `docs/examples/reviews/apply/demo.seal.json` 存在，但既不在 `<assets_root>/` 下、也不满足两段谓词；锁里不给它建键 | **PASS**（该样例不进 `U`，不得报 `seal_anchor_path_unmapped`）。v13 的 `**/reviews/apply/**` 会把它算进 `U` ⇒ 永久红，而 `lock --update` 无权给非封条建键（v14/I-4） |
| S-42 | 接 S-31：`git mv` 换路径后，新封条顺手换掉全部 `e2e.cases[]`、`reasons: []`、不写 `previous_cases`，只保留 `moved_from` | **FAIL `seal_move_payload_mismatch`**（T-26：豁免集之外必须与 `L_pre[-1]` 逐字节相等；补齐全量 `reasons[]` + `previous_cases[]` 后才 PASS）。新路径首签的 `L[0]` 就是自己，规则 3 的 blob 比较挡不住（v14/I-2） |
| S-43 | **改根 + 删旧键（v15/D-1；v16/D-1 改判据）**：`product/reviews/apply/auth/T-1.seal.json` + 锁里 `active` 键 ⇒ `U=1`；下一提交 `git rm` 封条 + `git mv product product2` + `config: assets_root: product2` + 锁里 `seal_anchors: null`，**且把 `assets_root_history` 一并改成 `[{root: "product2", review: "RV-0007", commit: <前序 sha>}]`、`layout_assets_root: "product2"`**（v15 只改 config 与删键，v16 必须把「顺手重写数组」也钉死） | **FAIL `assets_root_history_rewritten`**：锁文件历史里存在 `product` 根，当前数组不含它 ⇒ **⓪-3 首报**（v18/重要 3 收口；⓪-0 只判解析层、不会在这里红）；**不参与 `--allow-unverifiable-chain` 降级**。把数组补回去（`[{product,null,null},{product2,RV-0007,...}]`）仍红 `seal_anchor_path_unmapped`（`UH` 含旧根 ⇒ `U` 含旧路径 ⇒ 键被删）。v14 在该形态下 `U=0`、全绿（实测 `0f181f6`）——这是 v15 阻断 |
| S-44 | **合法改根（v15/D-1；v16/I-2 加 reanchor 前置）**：`lock --update --assets-root product2 --anchor-review RV-0007`，同提交改 `config` 与 `git mv product product2`，锁里 `assets_root_history: [{root:"product",review:null,commit:null},{root:"product2",review:"RV-0007",commit:<执行时的 HEAD>}]`、旧键全保留。**前置（v16/I-2）**：该仓另有一条**已 reanchor** 的路径（`anchor_review == "RV-0001"`、`epoch_origin != L[0]`，可由 S-30 接续构造） | **PASS**：`layout_assets_root == "product2"`、历史两条且旧元素未删未改；`U` 对 `UH` 两条根取并集，旧键**不**报 `seal_anchor_path_orphaned`；**已 reanchor 的路径 `anchor_review` 仍是 `RV-0001`**（改根不得覆写它，4a/4b 照常通过）。缺 `--anchor-review`、评审号写进键的 `anchor_review`、或资产树未同提交移动 ⇒ 拒绝 |
| S-45 | **首签 rebase 的受控重指（v15/I-1；v16/I-3/I-4 补前置与可判法；v17/B-2 删上限）**：某路径 `renewal_seq == 1`（读 **HEAD 封条**）、锁历史里该键从未有非 null `anchor_review`、`state == active`；在分支上 rebase 使旧 `epoch_origin` 不可达（`merge-base --is-ancestor` 返回 **1**，或旧对象已 gc 返回 **128**），然后对 HEAD 跑 `lock --update --seal <path>`。**前置（v15/次要 3）**：建键时 `epoch_origin_history` 已按规则 2 写成 `[epoch_origin]`，否则「从一条变两条」不可判 | **PASS**：`epoch_origin` 重指到新 `L[0]`、`epoch_origin_history` 变**两条**（旧值保留、只 append）；再跑一次 `lock --update` 不重复 append（仍两条）。**不设次数上限（v17/B-2）**：`len == 3` 不再被拒 `reanchor_not_allowed`，第二/第三次重指只要四条开放条件仍成立就照常 PASS；长度断言只作篡改检测（`epoch_origin_history_rewritten`），不当门。四条中任一被破坏（续签过 / 曾重锚 / 非 active / 旧锚仍可达）仍报 `reanchor_record_missing`；**把 128 以外的非零退出当「否」⇒ 夹具断言必须红**（错误用法） |
| S-45b | **连续两次 rebase 的单封条路径（v17/B-2 正面）**：接 S-45，同一条路径在第一次受控重指后再 rebase 一次（HEAD 封条仍 `renewal_seq == 1`、锁历史仍无非 null `anchor_review`），再跑 `lock --update --seal <path>` | **PASS**：`epoch_origin_history` 三条、末元素 == 当前 `epoch_origin`；不出现 `reanchor_not_allowed`、不需要也不能走 `seal reanchor --review`（`N == 1` 的 reanchor 本就判 `reanchor_invalid`）。v16 在该形态下永久红（重指被上限拒、reanchor 被 `reanchor_invalid` 拒、键不能删、封条不能重置）——这是 v16 阻断的反面 |
| S-46 | **`renewal_seq == 2` 的分支 rebase（v15/I-1）**：同上但 HEAD 封条的 `renewal_seq == 2`，旧 `epoch_origin` 因 rebase 不可达 | **必红 `reanchor_record_missing`**：受控重指只对首签开放，续签后的 rebase 必须走 `seal reanchor --review`。**v16/I-4 补反例**：锁里快照 `renewal_seq == 1` 但 HEAD 封条已是 `2`（锁未刷新）⇒ 仍必红——判据读 HEAD 封条，不读锁内快照 |
| S-47a | **`frozen` 键的字段保留（v15/I-3；v16/次要 2 拆分；v17/次要 1 改口径）**：由 S-38 接续，对已 `frozen` 的键跑 `lock --update --seal <该路径>`（`state` / `frozen_at` / `renewal_seq` / `n` **取值全部不变**——封条不可变，`lock --update` 不刷新冻结键的任何字段），再 `check`；对照分支手改锁里的 `frozen_at` | 前者 **PASS**：`state` 仍 `frozen`、`frozen_at` 原样、`renewal_seq` / `n` 与跑命令前逐字节相同，不报 `seal_frozen_modified` / `seal_anchor_path_state_mismatch`；后者 **FAIL `seal_frozen_modified`** |
| S-47b | **`retired` 键的字段保留（v16/次要 2；v17/I-5 补无封条分支）**：由 S-31 接续，对 `retired` 键跑 `lock --update --seal <旧路径>`。**前置**：旧文件保留（接 S-31）；另设对照变体——旧文件已删（接 S-36 的合法形态），HEAD 无封条 | **PASS**：`state` 仍 `retired`、`moved_to` 原样（不得被清空或改写）；`n` 取 `len(L_pre)`、`renewal_seq` 保留原值（**不得写 `0` / `null`**），`check` 不报 `seal_anchor_path_state_mismatch` / `seal_path_history_lost`。**为什么不能与 S-47a 合并**：`moved_to` 与 `frozen` 互斥（`frozen` 键没有 `moved_to`），一个夹具覆盖不了两种字段保留 |
| S-48 | **整段重写锁（v16/D-1，本轮阻断的反面）**：接 S-43 的形态，但**不写 `--assets-root`**——单提交里 `git rm` 封条 + `git mv product product2` + `config: assets_root: product2` + 锁整段改成 `layout_assets_root: "product2"`、`assets_root_history: [{root:"product2",review:"RV-0007",commit:null}]`（旧根元素**删掉**）、`seal_anchors: {}`，封条提交仍可达 | **FAIL `assets_root_history_rewritten`**（**⓪-3 首报**，v18/重要 3；⓪-0 只判解析层、不判 schema）；**对照变体（必须同样红）**：① `git rm atlas.solution.lock.json` → 改根 → 用 v2 重建锁（当前是「缺根历史」而历史有 ⇒ 同码）；② 重建成 **v1 锁** + 非空 `seal_anchors` ⇒ `lock_v1_with_seals`（⓪-2）；③ 重建成 v1 锁 + 空 `seal_anchors` ⇒ ⓪-3/⓪-4 跳过但 `U`（取 `UH`）仍含旧根 ⇒ `seal_anchor_path_unmapped`。**三种都不得全绿**——v15 在①③下 `U=∅`、键 ∅、全绿 |
| S-49 | **`UH` 的解析层 fail-open（v17/B-1 反面；v18/阻断 1 收紧断言；v19/阻断 1 换 layout 单源、重要 2 断言移到 CLI 面）**：提交 A 把锁里的 `assets_root_history` 写成**坏形态**（五变体，v19/阻断 1 换第五项：① `assets_root_history: []`；② `{}` 或坏 JSON；③ `[{root: "product"}, {}]`（元素缺 `.root`）；④ `[{root: null, review: null, commit: null}]`；⑤ 元素 `.root` 被 `layout.validate_value` 拒绝——`../product` / `/product` / `.atlas/product`。**`"product"` 不再算坏形态**：它是合法根，归 S-51 正向）→ 提交 B `git rm` 封条 + `git mv product product2` + 改 `config` + 锁写成干净 v2（`assets_root_history: [{root: "product2", ...}]`、`seal_anchors: {}`） | **断言写在 CLI 面（v19/重要 2）：`check --json` 的 `errors[].code == lock_history_unparsable`、stdout 是合法 JSON、`exit 1`**——`historical_roots()` 抛 `LockHistoryUnparsable` 只作**单元测试细节**，不得逃逸成 traceback；顶层 `try/except` 负责转成报告条目。判据逐条：①`isinstance(doc, dict)`；② `type(schema_version) is not int or isinstance(..., bool) or sv not in (1,2)`；③ 元素 `isinstance(dict)`；④ `d.get("root")` 是非空 `str` 且通过 `_support/layout.py` 的 `validate_value`（**不用 `ROOT_RE`**；`layout.py` 不禁中文/空格） —— `[]` 在「非空数组」这一条就被拒（不许 truthy 跳过）、`{root:null}` 在「非空 `str`」被拒（不许把 `None` 塞进根集、也不许 `-r` 造字面量 `null`）、`[{}]` 在「元素是对象但缺 `.root`」被拒（不许 `AttributeError` 逃逸）。**禁止 `{e.root for e in hist}` 这类集合推导**；解析器与当前锁同一个 `load_lock_strict`；**禁用 `jq` / shell 管道**。读取层（v19/阻断 3）：先 `git cat-file -t <c>`（对象缺失 ⇒ `chain_unverifiable`），再 `git cat-file -t <c>:<lock>`（路径不存在 ⇒ `continue`）；两段都在却 `git show` 失败 ⇒ 抛该异常。**当前锁**出现 `[]` ⇒ 走 S-50 的 `lock_unparsable`（⓪-0），不是本夹具 |
| S-50 | **当前锁不可解析（v17/I-4；v18/阻断 2；v19/次要 1、重要 1）**：把 `atlas.solution.lock.json` 写成非 JSON（截断的半个对象）、顶层是数组、`schema_version: 1.0`、`schema_version: true`、`members: {}`（不是 list-of-dict）、**`members` 缺失**、**`contracts` 缺失**（当前锁必须齐备）、`assets_root_history: []`、`seal_anchors` 是字符串 | **FAIL `lock_unparsable`**（⓪-0，先于 `lock_history_unparsable` 与 ⓪-3）；**⓪-0 一红即短路**：不再读锁历史、不算 `UH`，**`check` 立即 `exit 1`、`errors[]` 只有该码、不进第 1 步**（v19/重要 1）。**不得**落 `lock_missing` 的「跳过、当无锁」分支——`lock_missing` 只对**文件不存在**成立。同一仓换成「从未跟踪锁且工作树也没有」⇒ 才是 `lock_missing`（只跳过 ⓪-0 与 ⓪-3/⓪-4，⓪-1 仍执行）；**已跟踪后被 `git rm` / `rm` 删掉 ⇒ `lock_tracked_but_deleted` FAIL、`exit 1`、`errors[]` 单码短路**（v30/S-2） |
| S-51 | **根字符集单源·正向（v19/阻断 1；v20 补变体；v21/B-1 补普通文件、按索引；v22/I-1 补构造条件）**：`install.py --assets-root "产品 根"` 装入（中文 + 空格），跑 `lock --update` 与 `check`；对照：资产根 `product_v2`（ASCII）。**构造约束（v22/I-1，缺一则夹具不成立）**：`assets_root_history` 至少有**两个元素**——被破坏的根必须位于 **`hist[:-1]`**（索引 `0..n-2`），**数组末元素 `hist[-1]` 必须是更新后的当前根 `product_v2`（或 `产品 根`）且工作树里真实存在、是目录**。只有 `hist[:-1]` 走 `lexical=True`；若把被破坏的根放在末元素，它走严格版（`candidate.resolve()` + `relative_to()`），symlink 与普通文件会被拒——那是预期行为，不是本夹具。三个变体各自写明被破坏的根是第几个元素：① **`hist[0]`**（最老的历史根）对应目录**已删除**（`assets_root_history` 仍含它，工作树无此目录）⇒ `check` 仍 **PASS**；② **`hist[0]`** 被换成**指向仓外的 symlink**（`ln -s /tmp/outside <hist[0].root>`）⇒ 仍 **PASS**；③ **`hist[0]`** 被换成**普通文件**（`printf x > <hist[0].root>`）⇒ 仍 **PASS**。三个变体的当前根 `hist[-1]` 都必须未被破坏 | **PASS**：`layout.validate_value` 接受中文与空格；三变体证明**历史根只做词法校验、零 FS 访问**——历史根今天变成不存在、被换成仓外 symlink 或被换成普通文件，都**不因今天的工作树判红**（`_root_lexical_ok`）。`assets_root_history_rewritten` / `assets_root_changed` 均不报。**判据按索引**：`hist[:-1]` 全 lexical、只有 `hist[-1]` strict（`_root_by_index_ok`）；若实现仍对「每个根」调严格版（含 `resolve()` + `relative_to()`），变体①②③立刻红并永久无出口。`ROOT_RE` 只作写侧建议 |
| S-52 | **根字符集单源·负向（v19/阻断 1；v20 区分词法/FS；v21/I-1 补写侧、I-2 改报码）**：① 历史锁元素 `.root = "../product"`；② `"/product"`（绝对路径）；③ `".atlas/product"`（首段保留段）；④ 当前锁元素同三种形态；⑤ 任一根字符串**首尾带空白**（`" product"` / `"product "`），并分别经**解析层**与**写侧**（`install.py --assets-root` / `lock --update --assets-root`）两条路径 | ①②③ ⇒ **`lock_history_unparsable` FAIL**（⓪-1，`validate_value(..., lexical=True)` 拒绝，**零 FS**）；④ ⇒ **`lock_unparsable` FAIL**（**v21/I-2 改码；v22/B-1 落实现**：`load_lock_strict(current=True)` 对每个元素调 `validate_value(..., lexical=True)`，失败即抛 `LockParseError`；当前锁的全部结构性与词法性错误在 ⓪-0 吸收，**⓪-3 从此不判字符集**，只判 `layout == last` / 按索引分层 / `UH` 包含 / 重复）；⑤ 历史根 ⇒ `lock_history_unparsable`、**当前根 ⇒ `lock_unparsable`**；**写侧 ⇒ 拒绝写盘、非零退出、不 trim**（v21/I-1：`_validate_rel_path` 在 `raw = value.strip()` **之前**判 `value != value.strip()`；只测解析层不算覆盖）。**v23/次要 6 标为 B-0 交付即验**：实测当前 `layout.py` 对 `" product"` / `"product "` 两层都 ACCEPT（`raw = value.strip()` 在前），写侧拒空白尚未实现，因此本半条的断言**随 B-0 的 `_support/layout.py` 改动一起交付**（§6 B-0 文件表已列），不是既有行为。理由：若校验用 `strip()` 后的串、入集合用原串，`glob` 会匹配不到任何路径。**不是** `ROOT_RE` 判的——把 `ROOT_RE` 删掉后仍必须红 |
| S-53 | **`UH` 只信 HEAD 可达（v19/次要 3；v20/次要 1 补 merge）**：在 orphan 分支（或已删分支）上提交一版锁，写入旧根 `legacy_root`；HEAD 分支的锁里没有该根、封条也没有该路径 | **不进 `UH`**：`assets_root_history_rewritten` 不因缺 `legacy_root` 报红，`seal_anchor_path_*` 也不因该根造出路径。**对照**：把同一提交 cherry-pick 到 HEAD 可达位置 ⇒ 立刻进 `UH`，缺根即 `assets_root_history_rewritten` FAIL。**merge 注**：由 merge **带入的祖先**（第二父及其祖先）仍是 `HEAD` 的祖先，**算 HEAD 可达**，进 `UH`；只有 orphan / 已删分支 / 仅 reflog 可及的提交才排除 |
| S-54 | **`review_reused`（v20/重要 2；v21/I-4 拆两半）**：**S-54-B0（B-0）** 只用清单 / 首次锁字段构造「同一 `REVIEW-ID` 出现在 `assets_root_history[].review` 与 `acceptance_cutover_review` 两个决策类别」；**S-54-C（C）** 走真实 `lock --update --assets-root <new> --anchor-review RV-20261118-03`（改根），再用同一 ID 作 `--cutover` 的 `--anchor-review` | 两半都 ⇒ **FAIL `review_reused`**（`path` 指锁文件、`message` 说明「同一评审号用于两个决策」）。**对照**：同一决策类别内复用（同一根的历史元素复用同一 ID / cutover 首次写入与后续 `lock --update` 继承同一 ID）⇒ **PASS**，不误红。工具**不做台账查询**，只按 `(review_id → 决策类别集合)` 判重。B-0 的形态判定不依赖改根动作，C 的变体验「换根后」的复用 |
| S-55 | **`exemption_start_history[]` 断裂（v22/I-6，新增；v23/I-5 改前置；v24/I-2 再修；v25/I-1 改①）**：**前置 = S-18 的构造 + S-26 的后置提交**——**S-18** 是唯一真正执行 `seal reanchor` 的夹具（`R` 上 reanchor 合法、`L[0]` 重写成新 `R0`）；**S-26** 只提供「后置 `lock --update` 放进独立提交 `R2`」这一层，本身不构造 reanchor。`reanchor_not_allowed` 的前提是 `git cat-file -e <from_a>` 失败，换路径（S-31）不产生该前提，接 S-31 会被拒、构造不出本夹具。在「S-18 + S-26」的仓上继续：`exemption_started_at` 同步重指、`exemption_start_history` append 一条 `{from: <旧 L[0].signed_at>, to: <新 L[0].signed_at>, commit: <R 的父提交>}`，然后手工破坏审计链。**三个子变体，各自独立夹具**：① **已重指后整体删除唯一位移项**——S-18/S-26 只产生 **1 次** `seal reanchor`，`exemption_start_history` 只有 **1 条**；把这一条整段删掉 ⇒ 数组变空，而 `exemption_started_at` 已被重指到新 `L[0]`（即 `exemption_start_origin != exemption_started_at`）⇒ **⑤ 与版本前缀单调同时红**（`[]` **不是** `[x]` 的前缀扩展，单调判据同样不通过；v26/S-7 更正 v25 的「`[]` 是任何数组的前缀、单调不会红」——**写反了**），按判序只报一条 **`exemption_start_history_broken`**。**夹具必须写明「该仓已 reanchor 过」**（`origin != started_at`）：未重指时删空，⑤ 的 `origin == started_at` 仍成立，**不会红**。**不得**再写「2 条删首项」或「3 条删第 2 条」（v25/I-1）：S-26 之后 `epoch_origin = R` 可达，第二次 `seal reanchor` 的 `--from-a` 必被 `reanchor_not_allowed` 拒，2 条造不出来；前缀单调的**纯函数级**断言另由 **T-33**（B-0）覆盖；② **改 `from`**——把末项 `from` 改成任意别的日期（不等于前一项 `to`，或首项时不等于 `exemption_start_origin`）；③ **`to` 与 `L[0]` 不等**——末项 `to` 保留旧值而 `exemption_started_at` 已重指（或反之）。**对照（必须 PASS）**：未发生 reanchor、`exemption_start_history: []` ⇒ PASS；走一次 `seal freeze` 或 `lock --update` 后再 `check`，已有 origin 与 history 都不变 ⇒ PASS。**反面对照**：只改 `exemption_start_origin` 而 history 不动 ⇒ 首项 `from` 与 origin 不等，**同码 `exemption_start_history_broken`**；若 origin 被改成另一个值且版本前缀被破坏，另见 T-30① 的 `exemption_start_origin_rewritten` | ①②③ 都 ⇒ **FAIL `exemption_start_history_broken`**（`path` 指锁文件、`message` 指出断在哪一项、`exit 1`）。**不得**落 `exemption_start_conflict` 或 `exemption_start_signed_at_not_canonical`——一次输入只出一个码（v22/I-3 同口径）。**写侧对照**：`seal reanchor` 只改 `exemption_started_at` 而不 append 审计项 ⇒ 同码；同时改 origin ⇒ 同码（origin 任何路径都不改写）。`seal freeze` / `lock --update` / 改根对**已有** origin 与 history 都**不改写**；**缺失时**按 §1.1.3 第 3 条口径一次性回填（origin 取原 `started_at`、history 取 `[]`、`first_seen_origin` 取当前封条 `first_seen_at`），回填后 `check` PASS |
| M-01 | 单值存量索引 | 逐字节 PASS |
| M-02 | 多值第二 token 未定义 | FAIL（不得在 `:976-979` 跳过） |
| M-03 | 第二 AC 是唯一未覆盖 AC | FAIL，不能 `continue` |
| M-04 | 零证据用例挂行为 AC + 结构 AC | PASS（至少一个结构类） |
| M-05 | 多值 AC 只在索引改、分片不变 | link-change 重签后可 PASS |
| M-06 | 成员/父仓任务目录 `cases.md` 有 `BE-SYNC-*` / `HC-RECORD-*` / `TW-PUSH-*` 行（非 `E2E-*`） | 0.3.x WARN；0.4.0 起 FAIL（#54 判据放宽，T-01） |
| V-01 | 0.3.0 读 v2 清单 | 接受（迁移期） |
| V-02 | 0.4.0 读 v1 清单 | 硬拒 `manifest_schema_unsupported` |
| V-03 | 封条 schema 未知 | FAIL |
| V-04 | 旧 `.atlas` + 新封条 | 无门（如实，不在反面包宣称已红） |
| V-05 | `.atlas/VERSION` 仍是旧摘要形态 | 该级记为 `downgrades[]`（`code/scope: reader_version`）并**继续回落**（不在此刻记 `reader_version_unknown`）；安装副本 `.atlas/package.json` 或工具包根 `package.json` 拿到 semver 即为最终版本（v11/重要 4；v12 对齐实现）。**三级来源各一条夹具，只有「三级全缺」那条断言 `reader_version_unknown` WARN**（不 FAIL；硬拒只留给清单 schema）。第三级就是现有实现（工具包根 `package.json`），**无需新增落点** |
| V-06 | 仓内 v1 清单 + `install --update` 到 0.4.0 | 拒绝刷新，打印 `atlas solution migrate --to 2` |
| V-07 | 在 `reader_version < 0.4.0` 的装配上执行 `migrate --to 2` | 写 v2（只补缺、不自动 lock）；人提交后 `lock --update`；重复执行 diff 为空。**v10 加强：迁移后 `atlas.solution.lock.json` 字节不变；PRD 工作树脏时 `lock --update` 非零退出** |
| V-08 | 未 migrate 直接升 0.4.0 | exit 2（`manifest_schema_unsupported`），且 `.atlas` 未被覆盖 |
| V-09 | `0.2.0-beta.33` vs `0.2.0` | prerelease < 正式版；某一级不可解析 ⇒ 记 `downgrades[]` 并回落下一级，**只有三级全取不到**才 `reader_version_unknown` WARN（v11/重要 4） |
| V-10 | B-0 `migrate --to 2` 后同一次运行 `lock --update` | 不 `SolutionError`；**锁 `schema_version: 2`**（`LOCK_SCHEMA_VERSION = 2`；实测 v2 清单跑 `lock --update` 出 v2 锁）；旧 v1 锁仍可读（v32/B-2 更正旧稿的「仍为 1」） |
| V-11 | `0.3.0` / `0.4.0` 注册 `--allow-dangling-acs` | `0.3.0` 注册、`0.4.0` 不注册（argparse 拒绝） |
| V-12 | B-0 `migrate` 自动探测到 `product/prd/auth-prd.md`（非默认名） | **拒绝且不写任何文件**，打印「B 批后支持任意 `-prd.md`」；不得写出本版 `load_manifest` 拒绝加载的清单（Q-5） |
| V-13 | `init` 在 0.4.0 上建新仓（B 批） | 写出 `schema_version: 2` **且带 `definition`**（路径 = `product/prd/solution-prd.md`，**`definition.commit == null`**，`sha256`/`blob` 由 `git hash-object` 当场算出）；写 v1 会立刻 `manifest_schema_unsupported`（v9/B2；v10/I-3） |
| V-14 | 读侧门接受集：同一装配里 `init`（v1）→ `migrate --to 2`，再用 `load_manifest` 的 `reader_version` 注入分别喂 `"0.3.x"` 与 `"0.4.0"` | **PASS**：`"0.3.x"` 门接受 `{1,2}`、`"0.4.0"` 门只接受 `{2}`——迁移前 v1 在 `"0.4.0"` 门下被拒 `manifest_schema_unsupported`，迁移后 v2 在 `"0.4.0"` 门下 PASS（v32/B-1：不启动第二份二进制；全仓单 `package.json`，无获取两版本的机制）；首步仍断言 `init` 产物 `schema_version == 1` |
| V-15 | 已是 v2 但缺 `definition` 的清单（**可用性由注册谓词 `semver_lt(reader_version, "0.4.0")` 判定**，不是「换 0.3.x 二进制」，v32/B-1） | `migrate --to 2` **补齐缺失字段后 `check` PASS**（幂等 = 已有字段不动、缺失字段补上）；0.4.0 只能打印「请在 `< 0.4.0` 的装配上跑 migrate」并 FAIL `definition_unbound`（B2/重要 2）。**v10/次要 3：提示主体是 0.4.0 的 `check`（`definition_unbound` 的 message 里带上该命令）；`migrate` 本身在 0.4.0 未注册，不可能由它打印** |
| V-16 | 0.4.0 新仓 `init → check`（B 批） | **PASS**：`init` 写 v2 + `definition`，`check` 不再 `definition_unbound` / `manifest_schema_unsupported`；**只报 `definition_commit_pending` WARN，不报 `definition_commit_unverifiable`**（v10/I-3） |
| V-17 | 0.2.x 读 v2 清单（B 批；`reader_version` 注入在 B，B-0 构造不出来） | 硬拒 `manifest_schema_unsupported`（版本门 `0.2.x` 只接受 `{1}`，§5.2 第 4 条） |
| V-18 | 三级版本来源全缺（删 `.atlas/VERSION`、`.atlas/package.json`，并从隔离目录跑工具使工具包根也不可解析）后执行 `init` | **exit 2，且不写任何文件**（清单、锁、PRD 骨架都不落盘）；message 列出三个候选路径。**不得默认写 v1**（v13/第十二轮 B 批前置）。对照：同一环境跑 `check` 只报 `reader_version_unknown` WARN、exit 0 |
| V-19 | **merge 保留 null 锁（v14/B-2）**：main 锁 `definition.commit: null`，side 分支写非 null，main 上 `git merge -s ours side`（结果保留 null），HEAD 的 `check` | **FAIL `definition_commit_unverifiable`**：主判据 `git log -m --full-history --format=%H HEAD -- atlas.solution.lock.json` 必须列出 side 那条非 null 提交。缺 `--full-history` 时只有 null 那条 ⇒ 误落 `definition_commit_pending` WARN、FAIL 被蒙混 |
| V-20 | **`migrate --to 2` / `init` 的 cutover 取值（v19/阻断 2；v20/重要 1；v21/I-4 批次归 B-0）**：① 无 `--cutover`；② `--cutover 2027-05-15`（晚于默认、在上限内）无 `--anchor-review`；③ 同上带 `--anchor-review RV-20261118-03`；④ `--cutover 2027-06-30`（**唯一超限反例**：`> date(2027,3,31) + timedelta(days=90)`）带 review；⑤ 边界 `--cutover 2027-06-29`（**等于** `cutover_max`）带 review；⑥ 首次写入晚于默认但清单 / 首次锁的 `acceptance_cutover_review` 为空；⑦ 早于默认的 `--cutover 2027-01-31` 且显式带 `--anchor-review` | ① 写 `2027-03-31` 且 stdout 含 `acceptance_cutover=2027-03-31（可用 --cutover 指定）`；② **exit 2、不写文件**；③ 清单写 `2027-05-15` + `acceptance_cutover_review`，`check` **PASS**；④ **exit 2**（超限，review 也救不了）；⑤ **PASS**（**等于上限算通过**）；⑥ `acceptance_cutover_unreviewed` **FAIL**（`detail.kind = "review_missing"`；**该谓词当前未实现**，在它与 `malformed` 同批落地前本支为**假绿**，见 §0.35/重要 1）；⑦ 早于默认的 `--cutover 2027-01-31` 且显式带 review ⇒ **PASS**、清单写 `2027-01-31` **且 `acceptance_cutover_review` 照写**——**显式给了就落盘，不设 `ignored` 第三态**（v35/口径裁定）；未给 review 时该键不写。**PASS 分支不再使用 `2027-06-30`**——它只作超限反例，避免同一日期同时要求 PASS 与 exit 2。**B-0 文件表必须含 `--cutover` / `--anchor-review` 两个参数**，否则本夹具无法构造。**reader 门对照（v33/阻断 4）**：本夹具的前提是 **0.4.0 读者**；同一个显式 `--cutover` 在 `reader_version < 0.4.0` 下不是本夹具形态——必须 exit 2、不写任何文件（V-22） |
| V-21 | **`object_missing` 的作用域（v19/阻断 3；v20/阻断 2 重写；v21/B-2 对齐白名单）**：① 清单 `definition.commit` 指向本地不存在的对象；② 封条 `epoch_origin` 指向本地不存在的对象，且命令带 `--allow-unverifiable-chain`；③ 历史提交对象本地缺失（浅边界外）；④ 该提交没有锁路径；⑤ 对象与路径都在但 `git show` 失败（坏对象）；⑥ `git log` 本身非零 | ① ⇒ **WARN + `downgrades[]`**（`code: definition_commit_unverifiable`、`scope: definition_source`、`flag: --allow-unverifiable-chain`），`exit 0`；**不带开关** ⇒ `definition_commit_unverifiable` FAIL。② ⇒ **FAIL**，带开关也不降——**判据就是 §3.2 第 0 步的作用点白名单**（仅「校验点 = `definition.commit` 且 `scope == definition_source`」，`epoch_origin` 不在白名单，白名单外即使 `cause == object_missing` 也 FAIL）；`previous_seal_commit` / `anchor_review` 同类。③ ⇒ `chain_unverifiable`（**`<c>` 来自 `git log`，⓪-1 不可达，仅读取层防御；⓪ 层任何 `object_missing` 都不受开关影响**）；④ ⇒ `continue`、不报码；⑤ ⇒ `lock_history_unparsable`；⑥ ⇒ `chain_unverifiable`（**不是** `lock_history_unparsable`）。**对照**：`lock_missing` + ⑥ ⇒ 仍 `chain_unverifiable`（⓪-1 照跑） |
| V-22 | **`init --cutover` 的 reader 门（v33/阻断 4）**：`reader_version < 0.4.0`（`.atlas/VERSION=0.3.0`）下执行 `init --cutover 2027-01-31` | **exit 2（用法错误）、不写任何文件**（清单 / 锁 / PRD 骨架都不落盘），message 写明「`--cutover` 需要 0.4.0 清单（v2），当前读者只能写 v1，`acceptance_cutover` 无处落盘（拒绝静默忽略）」；**不得 rc=0 静默丢弃**（旧行为：清单 `version: 1`、锁 `schema_version: 1`、无 `acceptance_cutover` 键、无 WARN）。对照：同一 reader 不带 `--cutover` ⇒ 正常写 v1 清单；`reader_version >= 0.4.0` 带 `--cutover` ⇒ 写 v2 清单并把该值落盘。**注意**：这只是「不启用第二份二进制」，不是「版本无关」——`reader_version` 仍决定清单版本（§5.2 第 8 条） |
| V-23 | **`acceptance_cutover_review` 三处写侧（v34/阻断 2，B-0）**：a) 清单 round-trip——v2 清单含 `acceptance_cutover_review: RV-1` ⇒ 解析可取、`check` 无 `manifest_field_unknown`；值为空 ⇒ **不写行**；b) `migrate --to 2 --anchor-review RV-1` ⇒ 清单落盘该键且 `check` PASS；**不落盘（静默丢弃）⇒ 测试红**；`migrate` 显式 review 未落盘应 exit 2；c) `lock --update` 后用 v2 清单 ⇒ 锁含 `acceptance_cutover_review` 且与清单同值；review 为空 ⇒ 锁**不写**该键。三处任一缺失 ⇒ ③b 与 V-20③ 必红 | §6 B-0 文件表、§5.2 第 8 条 | **PASS**（三处齐备）；缺一处即 **FAIL（夹具红）** d) **写侧坏值（v35/重要 1）**：`init --anchor-review BAD` / `migrate --anchor-review BAD` ⇒ **exit 2、不写任何文件**；读侧坏值（手改清单成 `BAD`）⇒ `check` **FAIL `acceptance_cutover_review_malformed`、exit 1、`errors[]` 含该码**，其余错误仍可见（不是 exit 2）。e) **已有 review 不同（v35/重要 2）**：`migrate --to 2 --anchor-review RV-2` 而清单已有 `RV-1` ⇒ **exit 2、不覆盖**（与 `--cutover` 同口径）。f) **v1 路径（v35/重要 2）**：`reader_version < 0.4.0` 时 `init --anchor-review RV-1` ⇒ **exit 2、不写任何文件**（v1 清单无该字段，拒绝静默丢弃）。 |
| V-24 | **`path_at` 三洞（v34/重要 3/4）**：symlink——历史版本把锁路径做成指向仓外的 symlink、当前工作树同名 symlink ⇒ **两侧都按 `non_blob` 拒绝**（历史侧 `lock_history_unparsable`、工作树侧 `lock_unparsable`，exit 1），且工作树侧**不得跟随链接读成绿**；tree——锁路径是目录 ⇒ 历史侧 `lock_history_unparsable`、当前工作树 `lock_unparsable`，**不得静默当「无此路径」跳过**；浅仓 / partial clone——`git cat-file -e <commit>` 失败 ⇒ `chain_unverifiable`（`cause = history_unreadable`），**不得因 `<commit>:<path>` 的 rc 落该码**。另由 `tests/test_path_at_single_source.py` 断言 `build_lock_versions.fetch` 与 ⓪-1 根集循环调用同一个 `path_at`（monkeypatch 计数或静态引用）。**报码先后（v36/次要 2）**：同一运行里 ⓪-0（当前锁）在 ⓪-1（历史）之前且一红即短路 ⇒ `non_blob` 只报**当前侧** `lock_unparsable`；「两侧都报」是**两条独立夹具**（历史侧版本另放一块基座跑），不是同一次运行 | §1.1.3 ⑦、§6 B-0 文件表、`shared/gates.md` | **PASS**（三态各正确）；任一洞静默 / 两侧不一致即 **FAIL** |

### 刻意不做

- 不判卡 / 假设 / 需求的语义质量；不判 `REVIEW-ID` 真伪。
- 不绑 `atlas-apply.md` 字节；不在工作树保留旧封条副本（Git 历史是唯一记录）；不自动 GC。
- 不把非父仓的无索引 N/A 改 FAIL。
- 不合并三个 `not_ready` 机制；不改生成器退出码 3。
- 不自动续期 legacy/backfill/gap；不自动补 PRD；不自动生成 crosswalk；不自动改写清单（`migrate` 必须人跑）。
- 不在浅克隆下把「链取不到」当通过；不宣称「同域副本无法洗白」（R2）。

## 8. 可见性（如实写）

- 成员入口 `atlas check`（`scripts/atlas_check.py:53-64`）：卡投影、证据列期限；父仓引用项 N/A。
- 父仓入口 `atlas solution check --strict`：`#51/#59`、定义源、需求摘要、封条、crosswalk、被引用域证据列。
- Atlas 本仓 CI 只跑 `tests/test_cli_commands.py` + `tests/test_project_wiring.py`（`.github/workflows/tests.yml:33`），本 RFC 的门不在默认路径。
- Atlas 本仓没有 `.trellis`，`#52` 只能靠合成夹具。
- **旧 `.atlas` + 新封条 = 看不见 = 无门**；缓解见 §5.2，不宣称已全局接线。
- 采纳仓不跑 `atlas check` / `solution check --strict`，这些门等于不存在；`--strict` 默认开只约束「跑了的人」。
- **成员 `.trellis` 不跟踪 = 卡投影在 CI 永远看不到**；C 批硬前置要求跟踪（无 `signed_at` 宽限），未完成的仓不进入严格态。
- **浅克隆 = 链取不到，且不可降级（v19/阻断 3）**；先判 `git rev-parse --is-shallow-repository`，为真一律 `chain_unverifiable` **hard FAIL**——**第 0 步不在 `--allow-unverifiable-chain` 的降级清单里**（该开关只降「对象本地缺失」那一支，见 §3.2 第 9 步）。理由：降级后 `UH` 偏小、路径级/根级断言跟着放行，等于把「改根缩小宇宙」从后门放回来；`lock --update` 与 `seal reanchor` 本来就拒浅仓。**将来若要放宽，唯一形态是「整段跳过 ⓪ 与第 1 步、路径级/根级全 SKIP」**，不许降级后继续算——本稿不实现。CI 必须 `fetch-depth: 0`。
- **squash 是唯一不可检测的形态（Q-3/I5 收窄，名义闭合）**：只有「squash 成单提交 **并且** 把封条改回 `seq=1 / previous_*=null`」时路径事件与 blob 规则全过，工具**不能检测**。本 RFC 不提供假红夹具；防线只能是服务端（禁 force-push、主干保护、线性历史），属采纳仓契约要求，不属本工具能力。另：本机 squash 后旧 A 仍在对象库 ⇒ reanchor 反被 `reanchor_not_allowed` 拒绝，只能在 fresh clone 执行——且必须是**完整克隆**，浅克隆被预检拒绝（v11/阻断 2，S-29）。
- **rebase / filter-branch 是可检测的（I5 收窄；v10/B-2 改错误码）**：只重写 SHA、封条字节不变（`D=0`）时，锁有锚 ⇒ 第 4b 步报 `reanchor_record_missing`；锁无锚 ⇒ 第 5 步报 `renewal_chain_broken`（`previous_seal_commit` 仍指旧 SHA 而 `L[-2]` 是新 SHA）。两者都必须走 `seal reanchor --review` 才能继续；只有 filter-branch **并重置成 `seq=1 / previous_*=null` 的单提交形态**时才退化为上一条的不可检测形态。`D>0`（删+重建）另判 `seal_history_reset`，reanchor 修不了（§3.2 重要 4）。
- **v2 缺 `definition` 的自愈由 `reader_version < 0.4.0` 的注册门接受（重要 2；次要 3 改主体；v32/B-1 改判据）**：`migrate` 在 argparse 里**无条件注册**，但 0.4.0 读本仓 v2 清单会被**读侧版本门**拒绝（`manifest_schema_unsupported`），所以 `definition_unbound` 的修复只能在 `reader_version < 0.4.0` 的装配上完成（v36/重要 3 更正）；V-15 断言的是注册谓词，不要求第二份二进制（全仓单 `package.json`）。**提示主体是 0.4.0 的 `check`**：它报 `definition_unbound`，并在 message 里提示「在 `< 0.4.0` 的装配上跑 `atlas solution migrate --to 2`」；`migrate` 在 0.4.0 会被版本门拒绝，不可能跑通并打印该提示。0.4.0 新仓不受影响（`init` 直接写 v2 + `definition`，V-13/V-16）。
- **`init` 刚写完的 `definition.commit` 只能为 `null`（v10/I-3）**：`init_solution` 写 PRD 时它还是 untracked，拿不到包含它的 commit。此形态只报 `definition_commit_pending` WARN；首次 `lock --update` 补齐后，`commit` 再为 `null` 即 `definition_commit_unverifiable` FAIL（「已过首次刷新」的**唯一**标记见 §5.2 第 8 条：锁文件**完整历史**里存在 `definition.commit != null` 的提交——主判据 `git log -m --full-history --format=%H HEAD -- atlas.solution.lock.json`；v18/阻断 3 删除 `acceptance_cutover != null` 这条并列标记——`init` 与 `migrate --to 2` 就写该字段，它不证明刷新）。这不是「链取不到」，不能混用两个错误码。
- **`--lenient` 的 CI 禁令**：只有锁不再拒绝（fresh clone 可用，Q-6）；有封条即 exit 2。CI 命令行扫描 `--lenient` 仍保留为辅助夹具。
- **残余风险（R2/I3/R9/Q-3/I5/B1/B-2；v11 收窄；v12/次要 9 改三类）**：同域副本 + 抬版本 + 改路径 + 假 REVIEW 可在机器面通过；`commit` / 封条链对象本地缺失在默认态 FAIL、窄开关下 WARN（**v20/阻断 2 收窄**：只有 `definition.commit` 可降、`scope: definition_source`；`epoch_origin` / `previous_seal_commit` / `anchor_review` 缺失**一律 FAIL，开关无效**）；squash（且把封条重置为 `seq=1 / previous_*=null`）无法检测，rebase / filter-branch 可检测但需 reanchor；reanchor 的 `from_a` 由锁内该路径键 `seal_anchors[S].epoch_origin` 钉住，随机 sha 与顺手改业务字段都会被拒（S-24/S-25）。**B-2 的结论收窄为**：删 `reanchor` 字段（S-27）、改 `from_a`（S-28）已堵；**回滚到旧纪元**由 4b 的 `review` 外部锚堵（S-30，v11/重要 1）。**本地不可区分的残余只剩三类（v12；v13/R12-1 补第③类的第二形态）**：① 锚与封条在**同一提交**里被同时改写（只删锚 ⇒ `seal_anchor_path_unmapped`，只删字段 ⇒ `reanchor_record_missing`，删整份锁 ⇒ `lock_tracked_but_deleted`（从未跟踪时才 `lock_missing`）；剩下的是两侧一起改，只能靠锁与封条同 PR 评审）；② 旧原点确实不可达时，用锁里的 `epoch_origin` 手写一次载荷不变的 reanchor（语义上只是提前声明一个本该发生的纪元切换，不改业务数据）；③ **仓里没有任何可枚举的封条路径**，两种形态：（a）**封条尚未跟踪**（`U` 为空集）；（b）**曾经跟踪、后来删到空**（`U` 非空、HEAD 上没有 `*.seal.json`）。v12 只写了 (a)；在 (b) 下「键集 == HEAD 封条路径」两边都是空集，`D>0` 与 `seal_history_reset` 都不计算——这正是 S-36 的形态。v13 的挡法是 `U` 必须从 `git log -m --full-history --diff-filter=A --no-renames` 算（v14/B-1 补 `-m` 与 `--full-history`；**v15/D-1 再补：对 `assets_root_history` 每个根各算一次再并集，根不读 config 现值**）：`U` 非空而键集为空 ⇒ `seal_anchor_path_unmapped`，与「从未跟踪」区分开；**若实施者把 `U` 也实现成「HEAD 现存路径」，(a)(b) 会重新合成一个假绿**。**v16/D-1 补第③类的第三形态**：(c) **改根 + 整段重写锁**——单提交把 `assets_root_history` 改成只剩新根、`seal_anchors: {}`、`config` 改根，v15 在该形态下 ⓪ 过、`U=∅`、全绿；v16 的挡法是把 `U` 的根集改成**锁文件全历史并集**（`UH`）+ `assets_root_history_rewritten`（v18/重要 3 起固定排在 ⓪-3），两者相互独立（见 S-48）。锚层之外仍靠 §3.3 的跟踪要求与 `card_untracked` 先挡。**「多封条互踩锚」不在残余里**：v12 的按路径键映射让每条路径各自受约束（S-32），单槽锚时代的「旧路径规则 1/4a/4b 被整段跳过」已消除（S-31b）。前两类都要求**锁（含 `seal_anchors`）与封条走同一个 PR 评审（§2.6 规则 5）**，不靠机器承诺。
- **force-push 抹掉锁历史（v14/N-3，与上一条 squash 并列）**：锁历史主判据（`git log -m --full-history --format=%H HEAD -- atlas.solution.lock.json`）只能看见**当前可达**的提交；一旦写过 `definition.commit != null` 的那个提交被 force-push 抹掉，主判据也看不见它，当前 `commit == null` 的锁就只剩 `definition_commit_pending` WARN 被放行。`acceptance_cutover` **兜不了**：它在 `init` / `migrate --to 2` 就写入，与是否刷新无关（v18/阻断 3 删除这条兜底）；**机器面无法区分「从未刷新」与「刷新后被抹掉」**。防线同 squash：服务端禁 force-push / 主干保护，属采纳仓契约要求，不属本工具能力，因此**不给假红夹具**。
- **`assets_root_history` 的建立窗口与不可整段替换性（v15/D-1；v16/D-1 重写；v17/B-1 补解析层）**：`schema_version: 1` 的锁没有 `layout_assets_root` / `assets_root_history`，`check` 在升 2 之前**无从判根**；这段窗口里「改 config + 删键」在机器面不可见。因此 **B 批首次 `lock --update` 必须与 v2 清单同批落地、不得延后**，升 2 当刻补齐两字段。**窗口关闭后的判据不是「当前锁自洽」，而是「当前锁 ⊇ 锁历史」**：`UH`（锁文件全历史版本的根并集）是唯一不可被单提交替换的基准；当前 `assets_root_history` 必须**包含** `UH`，`layout_assets_root` 必须等于 `assets_root_history[-1].root`，元素 `.root` 互异，**按索引分层只做 FS 严格版**（`hist[-1]` 走默认严格版；`hist[:-1]` 的 lexical 已在解析层 ⓪-0 对每个元素完成，这里只作防御性复核，v23/次要 1；**唯一字符集源**，v19/阻断 1；v21/B-1；RFC 不另立 `ROOT_RE` 判据）——任一不满足 ⇒ `assets_root_history_rewritten`（⓪-3；v18/重要 3 把 schema 判定全部收口到这里）。**`UH` 只信 HEAD 可达历史（v19/次要 3；v20/次要 1 补 merge）**：orphan / 已删分支 / reflog 里的锁版本不进并集；**merge 带入的祖先（第二父及其祖先）仍是 HEAD 的祖先，算 HEAD 可达**，进并集。**两层根校验（v20/阻断 1；v21/B-1 改按索引，写死）**：`layout.validate_value` 拆 `lexical=True` / 默认严格两版——**lexical 只做 strip / 绝对路径 / `..` / 保留首段 / 字符规则，零 FS 访问**，供 `historical_roots()` 与 ⓪-1 判历史根；**默认严格版保留 FS 检查（`candidate.resolve()` + `relative_to()`），只用于 `install.py` 写入与 ⓪-3 的末元素**。**⓪-3 只对末尾元素做严格版 FS**：解析层（⓪-0，`current=True`）已对**每个** `.root` 跑 `validate_value(..., lexical=True)`，所以 `assets_root_history[:-1]` 的 lexical 属**已判**、这里只作防御性复核；⓪-3 的定义性 FS 检查只剩 `hist[-1]`（= `layout_assets_root`）走默认严格版——数组 append-only，历史根永远留在当前数组里（v23/次要 1）。历史根**今天**变成指向仓外的 symlink、被删成普通文件、或被换成普通文件，都不影响词法判定——`append-only` + 禁归一化因此有出口（S-51 三变体）。**根字符串首尾带空白一律判红**（历史 ⇒ `lock_history_unparsable`；**当前 ⇒ `lock_unparsable`（v21/I-2：⓪-0 吸收当前锁全部结构性与词法性错误）**；写侧 `--assets-root` 同样拒绝、不 trim），理由：若校验用 `strip()` 后的串、入集合用原串，后续 `glob` 会匹配不到任何路径。**v1 锁的统一口径（v18/次要 1；v19/次要 2 换结构理由）**：**v1 版本一律不贡献根**——写侧 `lock_payload` 只在清单 v2 时写 `layout_assets_root` / `assets_root_history`，v1 锁里**根本没有该字段**（不是「有而不取」，也不回落 config 根）；根字段缺失 ⇒ 跳过 ⓪-3/⓪-4 两条根断言并 WARN `assets_root_history_absent`；但 **v1 锁 + 非空 `seal_anchors` ⇒ `lock_v1_with_seals` FAIL**（本工具不产出该形态，出现即人为构造，堵住「退回 v1 跳过根断言」）。**解析层（v17/B-1；v18/阻断 1/2；v20/阻断 1、次要 2）**：`UH` 必须用与读当前锁**同一个 `load_lock_strict`** 逐版本解析，**禁止 `jq` / shell 管道**（非本仓依赖、失败会被吞）；历史版本只校验「存在则类型与结构正确」，**不要求 `definition` / `seal_anchors` / 两个根字段**；**历史版本缺 `members` / `contracts` 视为旧工具产物放行**，不报 `lock_unparsable`（当前锁仍两者必填，v19/次要 1）；任一版本坏 JSON、`schema_version` 非严格 int（含 `1.0` / `True`）、`assets_root_history` 为空数组、元素不是对象、`.root` 不是非空字符串或被 `validate_value(..., lexical=True)` 拒绝 ⇒ `lock_history_unparsable` FAIL；读取层（v19/阻断 3）：先 `git cat-file -t <c>`（对象缺失 ⇒ `chain_unverifiable`），再 `git cat-file -t <c>:<lock>`（**该提交没有该路径 ⇒ `continue`**），两段都在却 `git show` 失败 ⇒ 同码；`git log` 本身非零 ⇒ `chain_unverifiable`（v19/重要 5），**不是** `lock_history_unparsable`。**「解析失败」不是「无历史」**：v16 的参考实现正是在这里 fail-open，提交 A 写坏字段、提交 B 写干净即可全绿（S-49）。删锁重建由「当前缺字段而历史有 ⇒ `assets_root_history_rewritten`」覆盖（S-48）。`assets_root_history[].commit` 仅审计、不参与任何断言。残余只剩服务端：**force-push 把旧锁版本从历史里抹掉后，`UH` 也看不见旧根**——与下一条同源，防线是禁 force-push，不给假红夹具。
- **浅克隆里的可达性不可判（v11/阻断 2；v12/阻断 2 修探测）**：`git cat-file -e` 对浅/partial clone 剪掉的提交一律失败，会被误读成「旧原点真的不可达」。validator 在判序第 0 步整体拒绝浅克隆（v14/I-3 前移）；`seal reanchor`/`lock --update` 预检也必须自行判并拒绝（S-29/S-29b）。浅克隆用 `--is-shallow-repository`；**partial 不能用 `git rev-parse --is-partial-clone`**（git 2.50.1 / Apple Git-155 无此选项，实测 exit 0 原样回显，两种写法都永不生效），改用 `git config --get-regexp '^remote\..*\.promisor$'` / `git config --get extensions.partialClone` / `objects/pack/*.promisor`。partial 只是纵深防御（缺 blob 会让第 5/9 步自然红），严重度低于 shallow。**不要**改成「任意 HEAD 都查 `cat-file -e from_a`」：服务器保留旧对象时会把合法 reanchor 误判为伪造。
- **reanchor 的写锚边界（v9/B1 自查；v10/B-1 修；v12 按路径键）**：`lock --update` 不得每次从 `L[0]` 重算 `epoch_origin[S]`，否则重写后它会指向可达的新首签，fresh clone 首次 reanchor 必被 `reanchor_not_allowed` 误杀；也**不得重置其他路径的键**（§1.1.3 写锚规则第 1/2 条）。锚推进的条件是 `R0.reanchor.from_a == epoch_origin[S]`（幂等），**与 HEAD 是否是 `R0` 无关**，所以 post-lock 独立提交、不改封条的 merge 上跑也安全；后置 `lock --update` 必须独立提交，禁止 amend 到 `R`（§1.1.3 第 6 条）。路径移动新增键、旧键 `state: retired` 保留（同处第 4 条），`epoch_origin` 的**锚记账时点**语义、键宇宙 `U` 与三条宇宙断言见同处第 10 条（v11/重要 2、次要 5；v12/阻断 1；v13/R12-1 改宇宙来源）。**v15/I-1 的受控重指同样只 append、不回写**：`epoch_origin_history` 的**长度 = 1 + 重指次数**在 v16/I-3 里升级为**断言**（不足、超出、末元素 ≠ 当前 `epoch_origin`、元素重复 ⇒ `epoch_origin_history_rewritten`，按篡改锁处理），但 v17/B-2 把它明确降为**篡改检测、不再当门**——**不设次数上限**（`len <= 2` 已删），否则「单封条路径 rebase 两次」会变成死结（重指被拒、`N == 1` 的 reanchor 判 `reanchor_invalid`、键不能删、封条不能重置，唯一出路是改写历史或手改锁）。四条开放条件不变：`state == active` + 锁历史里该键从未有非 null `anchor_review` + **HEAD 封条** `renewal_seq == 1` + 旧值不可达（`merge-base --is-ancestor` 为 1 或 128）；重复 rebase 只换 SHA、没有载荷可洗（S-45/S-45b）。**重指次数的计数口径（v18/次要 2）**：= 锁文件历史**逐版本比较** `epoch_origin` 发生变化的次数（相邻两版该键的 `epoch_origin` 不同即 +1），**不得用 `epoch_origin_history` 数组长度反推**。
- **第二个纪元之后的局部重写是已知死结（v10/I-1）**：一旦后置 lock 把 `epoch_origin` 推到 `R0`，再就地重写第二个纪元之后的局部历史时，reanchor 的 `from_a` 只能取 `R0`，而 `R0` 可达 ⇒ `reanchor_not_allowed`。它与真正的伪造**同码**；操作者先 `git cat-file -e <seal_anchors[S].epoch_origin>`，**可达即属本死结**。当前字段集无解；真消死结需要把「**纪元起点**」与「**不可达旧原点**」拆成两个字段（例如 `epoch_origin` 永不变 + `anchor_at` 记录锚记账后的可信起点），且**不能简单让 `epoch_origin` 永不推进**（那会把「用锁里的旧原点手写 reanchor」的伪造路径放回来）。
- **`signed_at` 是工具自述（次要 2；v16/N-2 退回纯审计；v17/I-1 换字段）**：v16 起它**不再给 `gap.due` 做判据**（下界自 v22 起由锁键 **`exemption_start_origin`** 承担：建键时写入首签封条 `signed_at`，**已有值任何命令都不改写；缺失时按 §1.1.3 第 3 条一次性回填**——`lock --update` / `seal freeze` / `seal reanchor` / 改根 / 换路径（`moved_from`）都只回填缺失、不改已有值；`gap.due` 的**下界**取它、**上界**取 `min(trunc_utc_date(first_seen_origin) + 90d, acceptance_cutover)`（v23/I-1/I-3；v26/I-2：先截日期再加 90 天），也不参与链复算与宽限分层；换路径不是重签，新封条逐字节沿用旧 `signed_at`，续签才由工具重写。它**不能证明封条未被重置**；链能证明的只是「提交历史里存在过这些封条字节」，时间维度依赖 `exemption_started_at` + `first_seen_origin` + reanchor 记账。**外部锚的强度（v23/I-1；v24/B-2）**：锚取锁文件中**首个同时含该字段的版本**（存量键即回填提交），首版虽由作者写入，但一旦入库便**不可回溯改写**（force-push 被服务端契约禁止，§8），因此它强于「当前锁自证」；仍不能证明时间本身真实，只能证明该值自上锁以来未被改写。**`exemption_started_at` 的判据（v18/重要 1；v22/I-6 拆键）**：**拆成三个键**——`exemption_start_origin`（已有值不可改写、缺失时一次性回填，见上；`gap.due` **下界**取它）、`first_seen_origin`（建键写死、已有值不可改写、缺失时一次性回填；`gap.due` **上界**取它，v23/I-1）与 `exemption_started_at`（主判据 = 当前 `L[0].signed_at`）。后者允许 `seal reanchor` 同步重指（否则 reanchor 重写 `L[0]` 后老键永久红、无出口），但**必须同时** append 一条审计项到 `exemption_start_history[]`：元素 `{from, to, commit}`，`from` = 重指前的值、`to` = 重指后的值；数组 append-only，首项 `from` == `exemption_start_origin`、第 i 项 `from` == 第 i-1 项 `to`、末项 `to` == 当前 `exemption_started_at` == 当前 `L[0].signed_at`；`history` 为空时 `exemption_start_origin == exemption_started_at`（建键二者同值）。任一断裂 ⇒ **`exemption_start_history_broken` FAIL**（T-28(b)、S-55）。① **主判据 = 等值**——值必须与该路径 `L[0]` 首签封条的 `signed_at` **逐字节相等**；封条字节被 §3.2 的链规则钉住（`seq == N`、`previous_*`、`blob@L[0]`），可复算，比 committer date 强。② **继承**——带 `moved_from` 的新键必须**沿 `moved_from` 递归到链首、与链首键的值相等**（中途缺键先报 `seal_anchor_path_unmapped`；「链首键不存在」只作 `exemption_start_conflict` 的 `detail`）。`git show -s --format=%cI <L[0]>` 只作 **WARN/INFO**：committer date 可被 `git amend` / `rebase` / `GIT_COMMITTER_DATE` 改写，**不可证**；越界只能提示，不能单独判红。**v23/I-1 的口径（v24/B-2 修取法）**：锚取锁历史中**首个同时含该字段的版本**（存量键即回填提交），不再用「当前锁自证」——首版由作者写入但入库后不可回溯改写，故能判「上锁后是否被改」；`exemption_start_origin` 与 `first_seen_origin` 各有 rewritten 码。**归一化口径（v19/次要 4，写死一种）**：`signed_at` 统一序列化为 **`YYYY-MM-DDTHH:MM:SSZ`**——UTC、`Z` 后缀、**无小数秒**；等值比较一律按该形态逐字节，`+00:00` 写法或带小数秒（`.123Z`）⇒ **形态码**：`exemption_started_at` 自身 ⇒ **`exemption_start_signed_at_not_canonical`**；任何封条 blob（含 `L[0].signed_at`）⇒ **`signed_at_not_canonical`**（v24/B-1 职责正交）；**形态失败即跳过整个 conflict 组**（`exemption_start_conflict` 及其 `detail` 分支，v25/次要 1），不报 `exemption_start_conflict`。**写侧单源（v20/重要 4；v21/I-3 改续签口径）**：封条签发 / 续签只允许 `datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`，**禁止 `isoformat()`**（默认产出 `+00:00`，带微秒时产出小数秒）；**续签重写自己的签署时刻**，**只有换路径（`moved_from`）沿用旧值时才逐字节复制**，不重新格式化。**不设 grandfathering**：C 批尚未上线，HEAD 里不存在任何已入库的 `*.seal.json`，没有需要放行的存量——规则生效即 fail-closed；理由写在这里，避免后续以「存量」为由开口。**残余**：`force-push` 改写锁历史后等值与继承都不可判（封条链与首个版本一起被抹掉），与上一条同一残余面；本 RFC 不宣称时间可证，只宣称「改动会在链上留下可复算的痕迹」。
- **`object_missing` 只降 `definition.commit`（v20/阻断 2；v21/B-2 白名单）**：`<c>` 来自 `git log`，对象必然在本地，⓪-1 的 `object_missing` 是**死分支**（保留读取层防御，不产生 WF）；可达的「文件里写的 SHA」有四处——`definition.commit`、封条 `epoch_origin`、`previous_seal_commit`、`anchor_review`。`--allow-unverifiable-chain` 的**作用点白名单只有一条**：「校验点 == `definition.commit` **且** `scope == definition_source`」，两项同时成立才降（WARN + `downgrades[]`）；**白名单之外即使 `cause == object_missing` 也 FAIL**——`epoch_origin` / `previous_seal_commit` / `anchor_review` 是封条链的锚，缺失等于链不可证，不接受自述降级。第 0 步仓形态、⓪-0、⓪-1 同样不降。
- **`review_reused` 的可见性（v21/次要 5）**：`acceptance_cutover_review` 与 `assets_root_history[].review` 都只是**自述**——工具只判 `REVIEW-\d{8}-\d{2}` 形态、**不做台账查询**、不验证评审真实存在；能查的只有「不重复」：同一 `REVIEW-ID` 出现在两个决策类别（改根 + 改 cutover）⇒ `review_reused` FAIL。**残余**：一个真实存在但内容不相关的评审号仍可被贴到任一次决策上，机器面无法区分；防线是锁与清单同 PR 评审（§2.6 规则 5），不给假绿也不给假红。
- **「锁内自述值的锚 = 锁历史」这套口径的适用范围（v23/I-1；v24/I-1、B-2 收口）**：四类值都在 §1.1.3「资产根」⑦ 一处定义，**按值形态分四类、判据各一条，不再各写一套**——**append-only 只是叙述，判据以下列四条为准**：
  - **标量**（`exemption_start_origin` / `first_seen_origin`）：取 `git log -m --full-history --reverse --format=%H HEAD -- atlas.solution.lock.json` 逐版本解析（同一个 `load_lock_strict`，`current=False`），锚 = **首个同时含该字段的版本**里的值；当前值 ≠ 锚 ⇒ `exemption_start_origin_rewritten` / `first_seen_origin_rewritten` FAIL。**取锚为空（v25/次要 4）**：当前锁尚未提交（工作树有字段、历史无该字段）⇒ **跳过**（视为缺字段）；`seal_anchors` 为 `null` 或非 dict 时按「无该键」容错，**不得抛异常落 `internal_error`**。**`first_seen_origin > L[0].signed_at`（时间戳层）也报 `first_seen_origin_rewritten`，`detail.kind ∈ {rewritten, after_signed_at, not_canonical}`（v25/I-4；v26/S-9 补 `not_canonical`——`first_seen_origin` 不是 `...Z` 形态即报本码，见 §1.1.3）。**
  - **数组 A**（`assets_root_history`）：`UH` 并集 + `layout == hist[-1]` ⇒ `assets_root_history_rewritten`。
  - **数组 B**（`epoch_origin_history`）：末元素 == 当前 `epoch_origin` + 长度 == `1 + 重指次数` ⇒ `epoch_origin_history_rewritten`。
  - **数组 C**（`exemption_start_history`）：版本前缀单调（后版本是**紧邻前一版本**的前缀扩展、相邻至多新增一项；v28/B-1：不得写成「某前版本」，`[] → [x] → []` 会假绿）⇒ `exemption_start_history_broken`。**`versions` 构造三点（v29/B-1、B-2；v30/B-1 补第三点；v32/I-2 提成独立纯函数 `build_lock_versions`，与 `check_history_prefix` 同级）**：① 按 commit SHA 去重（merge 多父会重复输出，构造层清理、不产生判据）；② **历史层：某版本没有该路径 ⇒ 跳过、不得记 `[]`**——逐版本经 `path_at(c)`（§1.1.3 ⑦ 三态判序）：先 `git cat-file -e <commit>` 判对象可读（不可读 ⇒ `chain_unverifiable`），再 `-t <commit>:<path>` 判形态——`absent` ⇒ `continue`；`non_blob` ⇒ `lock_history_unparsable`，**不得静默跳过**（`git rm` 之后删除提交仍在 `git log`，若记 `[]` 会让 `[…,[x],[]]` 误报 `exemption_start_history_broken`，而实际是整份锁被删）；③ 末尾追加工作树当前锁（**仅当 HEAD 存在该路径且字节不同**；HEAD 无该文件、或 **HEAD 有但工作树文件被 `rm`** ⇒ 均不追加）；无任何锁历史时 `versions == []` 返回 `Ok` 并另发 INFO `lock_history_empty`（不进 `errors[]`、exit code 不变）；**锁文件从未跟踪 ⇒ `lock_missing`、已跟踪后被删 ⇒ `lock_tracked_but_deleted`，均不发该 INFO**。
  **存量缺字段不算 rewritten**，走 §1.1.3 第 3 条一次性回填。**残余（v24/B-2，两条）**：① 存量键的锚落在**回填提交**上（首个含键版本没有该字段），`first_seen_origin` 的回填值取自当时不可证的 `first_seen_at`，所以「回填那一刻就写晚」检测不到，只能检测「回填之后被改写」；② force-push 把最早版本从历史抹掉后，锚也看不见——防线都是服务端禁 force-push，不给假红夹具。`exemption_start_origin` 的回填值受 T-28① 钉在 `L[0].signed_at` 上，比 `first_seen_origin` 硬一档。
- **`exemption_due_out_of_range` 的可见性与出口（v24/I-3；v25/I-2 日期层；v26/I-2 单源归一化）**：`gap.due` 一律 `YYYY-MM-DD`，必须落在闭区间 `[exemption_start_origin, min(d + 90d, acceptance_cutover)]` 内（`d = trunc_utc_date(first_seen_origin)`），且 `origin ≤ due`；**比较全在日期层**——下界取 `exemption_start_origin` 的 **UTC 日期部分**；上界**先截日期再加 90 天**：`d = trunc_utc_date(first_seen_origin)`（`date`），再 `min(d + timedelta(days=90), acceptance_cutover)`，全程 `date`，禁止时间戳与日期直接比、禁止本地化后再加——**「先截日期再加 90 天」是单源写法**（纯 UTC 下与「先加 90 天再截日期」结果相同，但只允许这一种）。两端都含。**读侧**超出即 FAIL（写侧拒签之外，读侧另有此码——`:1156` 的闭区间两端都含，越界不能只在写侧拦）。**出口**：续签一枚新封条把 `due` 改回区间内，`check` 恢复 PASS（T-32④ 验证），不是永久红。**回填前缺 `first_seen_origin`**：只跳过 `d + 90d` 这一支，**`acceptance_cutover` 上界不随之跳过**（`due > cutover` 仍 FAIL），`warnings[]` 记 `migration_required`（`detail.kind = "missing_first_seen_origin"`，提示跑 `lock --update`）。**回填只恢复 `+90d` 这一支；`due > cutover` 须续签修正——本码即续签出口（T-32④）**；当前库内无已签封条，故「升级即红」的集合为空。
- **`internal_error` 的可见性（v23/次要 2）**：`internal_error` 是**兜底未知异常**的唯一出口（`except Exception`，只接在 `SolutionError` / 三类解析异常之后），**不是**任何业务判据的常规取值。`exit 2`、`--json` 时输出合法 JSON（`ok: false`、`errors[]` 含 `{code: "internal_error", message: <异常类型 + 首行>, path: null}`），并按 §3.2「⓪ 短路后的完整性」填 `not_run[]`（游标及其后所有段）。**验收口径**：§5.2 码表登记（第 13 条）、`code` 取值集（§3.2 schema）、§6 夹具（`validate_value(..., lexical=True)` 在干净基线上抛 `TypeError` ⇒ 走该层而非 traceback；另造一个非 `SolutionError` 的未知异常）、§8 本条**四处齐备**。**它不代表「检查通过」**：消费方拿到 exit 2 + `internal_error` 时必须当失败处理（首字符 `{` ⇒ 按 JSON 解析）。

## 9. 待拍板（开放问题）

**以下 5 条第六轮产品决策按推荐项写进正文，标记「待拍板」；评审若否决，正文对应段落需回滚：**

| # | 决策 | 本轮落笔（推荐项） |
|---|---|---|
| 1 | squash / rebase | squash（且把封条重置为 `seq=1 / previous_*=null`）只写残余风险 + 采纳仓契约要求（服务端禁 force-push / 线性历史），工具不宣称检测；**rebase / filter-branch 按 `D` 分流（v10/次要 1 补齐）**：`D=0`（路径保留、只重写 SHA）⇒ 可检测（锁有锚时第 4b 步报 `reanchor_record_missing`，锁无锚时第 5 步报 `renewal_chain_broken`），需 reanchor 才能继续；`D>0`（删+重建）⇒ 判 `seal_history_reset`，只能新首签重建 + 评审，reanchor 不适用（v9/重要 4） |
| 2 | `--lenient` | 保留；拒绝条件改为「有封条才拒」，锁不再拒绝 |
| 3 | `card_untracked` | C 批硬前置；删除 `signed_at` 分层与 K-17 |
| 4 | 归档任务 | 封条不动；校验时到 `tasks/archive/<month>/` 找卡 |
| 5 | reanchor | 只允许 fresh clone 执行；不提供破坏性绕过命令 |

原有开放问题：

1. `关联AC` 同列多值（`、`/`,`）是否够；是否需要单独的链接表。
2. **`crosswalk_orphan_member_ac` 是否升 FAIL（v42/横切）**：D 批默认只 WARN（默认配置下不报，见 C-10）；#51 的「双向对账」另一半（成员 AC → 方案）仍无人判。选项：(a) 保持可选 WARN；(b) D 批首版即 FAIL，给 90 天迁移；(c) 只对「成员 PRD 已被 `prd-domain` 绑定的仓」FAIL。**待拍板**，未定前默认 (a)。
3. `atlas apply archive` 的归档条件：是否要求「所有 AC 有 E2E 状态或显式 n/a」。
4. `min_atlas` 的强制点：只靠 `install.sh --update`，还是必须 CI 比对。

## 10. 本 RFC 不做什么

- 不写实现、不改 `_support/`、`scripts/`、`validators/`、模板与契约正文。**例外（v21/B-3）：`_support/layout.py` 是 B-0 的交付物**——`_validate_rel_path(..., lexical=False)` 新增参数 + `validate_value` 透传 + 首尾空白在 `strip()` 之前拒，条目见 §6 B-0 文件表；干净基线 `411c971` 上该参数不存在，`validate_value(..., lexical=True)` 会抛 `TypeError`，不补这条 B-0 无法开工。除此之外不得借「布局校验」为由改其他文件。
- 不提交、不 push、不发版；版本保持 `0.2.0-beta.33`。
- 不修改 `RFC-20261111-01` / `RFC-20261111-02` 正文。
- **`duty-review/` 例外（重要 1）**：为闭合 P-4 的 `--allow-dangling-acs` 措辞，允许在 `duty-review/QUEUE.md` 与 `duty-review/bugs.md` **仅新增 `[Unreleased]` 更正条**，不改旧条目、不改冻结基线正文；不改写历史记录、不删旧条。
- 不宣称已通过评审；评审由独立会话执行。
