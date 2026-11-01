# RFC-20261101-01：代码/设计孤岛约束登记（非门草案）

> 提案编号：RFC-20261101-01
> 提案作者：@sunwenzhe-git
> 关联状态：已定案 (Accepted)（2026-11-01 canonical 已落地；提交记录见 git log）
> 影响范围：契约 (shared) | 文档 (docs/map) | 测试锚（只读引用，不新增）
> 关联取证：2026-11-01 AOCI-CODE v0.1.0-rc23 在 Atlas 克隆副本的 7 文件样本（2,732 行 / 32 条 S / 7 条落盘条目）
> 实施批次：无代码批次；本 RFC 只回答「是否建表、收哪些行」

---

## 0. 摘要

一次外部文件级认知索引验证显示：Atlas 的 32 条非显性约束里，约 1/3 只存在于代码注释、测试或 `DESIGN.md` 的决策行里，没有进入用户文档或共享契约正文；但这些约束恰恰是「改错会静默出事」的部分。AOCI-CODE 的 S 字段把它们压成一行、并与文件同址，这个形态值得借；它的 R 关系写错仍能通过治理预览，说明**机器绿不等于语义对**，必须补锚。

初版列了 12 条；独立只读评审 + 主审抽查发现其中 4 条（C-05、C-06、C-07、C-12）已在门册 §2.1 登记（`shared/gates.md:56`、`:68`、`:73`），去重后保留 8 条。本版按评审结论修订，不再把这 4 条重复登记。

本 RFC 的定案：

- **不建新门**：不新增校验器、不进 `atlas_check`、不改任何判据。
- **不新建 shared 文件**：在 `shared/gates.md` §4「缺口清单」下新增「约束登记（非门）」子节，避免另立第三个真相源。
- **先收 8 条**：只收去重后仍只在代码/设计/测试里的约束；每条必须能回指文件行、现有测试或变异钉。
- **owner 写在约束名内**：保持门册六列对齐，不新增第七列。
- **升格另案**：某条约束若反复造成回归或缺测试锚，再按门册规则单独立门、补 M 系变异，不在本 RFC 批量上判据。

评审阶段只读；落地记录见 §7。canonical 已改 `shared/gates.md` §4.1 与 `docs/map/` 的行数快照，提交记录见 git log。

---

## 1. 现象与取证

### 1.1 触发形态（抽象）

* **环节**：agent 修改核心脚本 / 适配器 / 校验器时，只读 `docs/map/`、PRD 或门册，读不到该文件 docstring / 注释 / 设计决策里的关键约束。
* **触发时机**：重构、修 bug、加分支、复制实现、调整执行目录、改异常捕获顺序。
* **具体行为**：约束没有单一检索点；改错后现有测试可能仍绿，或只在真实仓/真跑时以「假红」「静默跳过」「幽灵数据」形态出现。

### 1.2 客观证据

**E1：7 文件样本**

- 工具：AOCI-CODE `v0.1.0-rc23`（darwin/arm64），sha256 `1481afcf…` 与发布页 `SHA256SUMS` 一致；许可证 FSL-1.1-MIT。
- 样本：`_support/siblings.py`、`_support/review_policy.py`、`adapters/_graph.py`、`validators/validate_ac_alignment.py`、`scripts/closeout_derive.py`、`shared/global-rules.md`、`scripts/atlas_check.py`；共 2,732 行。
- 7 条 FRAS 落盘；32 条 S 约束；作者逐条核对后 **0 条事实错误**，1 条选择不全（AC 条目漏了「无主 AC / 无豁免 skip 直接 FAIL」这个主判据）。
- 约 1/3 只在代码注释、测试或 `DESIGN.md` 决策行里，未进入用户文档或共享契约正文。代表：
  - `adapters/_graph.py:197-204`：非 git 工作树返回空键 + WARN；`ensure_index` 空键永不判 fresh，每次全量重建。
  - `validators/validate_ac_alignment.py:492-500`：仅当门禁非 FAIL 且无解析错误才写 AC 基线快照，避免把坏快照冻成新基线。
  - `scripts/atlas_check.py:134-150`：`reset` 取值先剥行内注释、再只剥成对引号；调用点与测试必须走同一函数。
  - `scripts/atlas_check.py:819-836`：`_write_check_event` 写失败必须静默吞掉，观测面坏了不能把门禁判红。
- 这是 7 文件样本，不外推全仓；全量 303 条未跑。

**E2：R 关系的语义缺口**

`scripts/atlas_check.py` 的条目初稿把 6 个 R 写成 `.atlas/validators/...`、`.atlas/scripts/...` 安装态路径；源仓没有 `.atlas/`，`update-entry --preview` 仍放行。改为 `validators/...`、`scripts/...`、`_support/...` 后才落盘。这不是格式问题，是语义校验缺口。

**E3：漂移与维护**

改 `_support/siblings.py` 后 `verify` 报 `stale: ['_support/siblings.py']`；`aoci_maintain` 自动签发 `change=update` 候选并带新 `source_sha256`；还原后 sha256 逐字节一致，`stale` 清零。

**E4：验证边界**

只验证 7 个文件、未跑全量 303 条；未验证 Overview 分块、Attestation、跨 Agent 复用、数据库认知、70 万行规模。样本用于判断「S 值不值得借」，不用于宣称 AOCI 已生产可用。

### 1.3 评审去重结果

独立只读评审与主审抽查确认：

- **C-05**（收口并入未跟踪文件）已在 `shared/gates.md:56` 的 `closeout_derive.py` 行登记；现有测试的正控已隐式覆盖该分支（`tests/test_closeout_derive.py:78-88` 的基线提交后，`_touch` 创建的文件均为未跟踪），只是没有专用钉。
- **C-06**（收口 WARN 范围）同样在 `shared/gates.md:56`，并已有 M141/M142。
- **C-07**（生成物三态）已在 `shared/gates.md:68` 的 `生成物最新` 行登记。
- **C-12**（装配版本坏戳 / EmptyAssembly）已在 `shared/gates.md:73` 的 `装配版本` 行登记，含 M59/M59b。
- **C-11** 的测试锚应为 `tests/test_atlas_check.py:1111`（写失败不判红）与 `:1130`（序列化失败不抛），初版只写了后者。
- **C-01** 的 M59 与装配版本 M59 重号；已把 graph 侧改为 **M161**，装配版本 M59 保留。

去重后保留 8 条：C-01、C-02、C-03、C-04、C-08、C-09、C-10、C-11。

---

## 2. 决策与权衡

### 2.1 核心定案

**D1：在 `shared/gates.md` §4「缺口清单」新增「约束登记（非门）」子节，不新增门、不新建 shared 文件。**

- 放 §4 而不是 §2：§2 是机器门登记表；非门表放进去容易被读成门，产生「影子门」。
- 不新建独立 shared 文件：本轮没有足够收益支撑新的装配/计数/单源登记面；且 Draft 阶段引用尚不存在的 shared 文件会撞 `tests/test_canonical_consistency.py` 的「shared 互引可达」判据（本提案初版已实测 1 failed）。
- 表沿用门册六列；`owner` 写在约束名内；最后一列从「假绿测试（等级）」改为「锚 / 取证（非门；未取证写待补）」。
- 明确声明：本节不参与判定、不计入门总数、不进入 `atlas_check`；权威仍在代码/DESIGN；升格另案。

**D2：先收 8 条，不做全量 307。**

- 只收去重后仍只在代码/设计/测试里的约束。
- 已有门册登记的 4 条不重复收；若评审认为检索价值高，可在 §4 表中加一行「见 §2.1」指针，不复制正文。
- 每条要有可用锚；没有测试锚的标「待补」，不写「出厂级」。

**D3：升格另案。**

某条约束满足以下任一条件，才单独立门并补 M 系变异，不在本 RFC 批量转门：

- 真实仓连续出现同类回归；
- 现有测试锚无法咬住坏输入；
- 约束可机器判定且误报率可接受。

### 2.2 考虑过的备选方案及否定理由

* **备选 A：新建独立 shared 文件。**
  * *否定理由*：本轮收益不足；会新增装配自检、`docs/map/` 计数、`shared/single-source.md` 登记、canonical 互引等同步面；Draft 阶段引用尚不存在的文件还会直接撞 `test_shared_references_resolve`（实测红）。
* **备选 B：放进 `shared/gates.md` §2.7。**
  * *否定理由*：§2 是门登记表，非门表放进去有影子门风险；§4 更贴近「观测/缺口」语义。
* **备选 C：写进 `docs/map/` 章节。**
  * *否定理由*：地图是 creator-facing，每章 ≤120 行预算；按文件铺开会爆预算，且消费对象是「改这个文件的 agent」，不是「讲 Atlas 的人」。
* **备选 D：12 条直接建门。**
  * *否定理由*：多数是语义/结构约束，批量上判据会触发 §12「先量再动手」；且部分已有测试锚，重复建门会造双判据。
* **备选 E：继续只留在代码 docstring / 注释。**
  * *否定理由*：agent 只读地图/门册时读不到；本次样本已经证明约 1/3 约束处在这个状态。

### 2.3 必须警惕的代价与兼容性影响

- **维护成本**：`gates.md` §4 多一张表；每行必须绑定锚，锚失效要随发版/门册同步更新。
- **不是门**：不能把「有行」当成「已自动判定」；它只改善检索，不改变任何行为。
- **兼容性**：零运行时成本、零退出码变化；不要求存量项目重跑 `atlas init`、不新增装配文件。
- **行数快照**：`shared/gates.md` 行数变化会触发 `docs/map/gates.md:18` 的「153 行」快照；按 M155（版本串/行数声明漂移）同步，不是 M151–M154。若只加 §4 子节，行数按实算更新。
- **语义风险**：表里的约束仍是人写的；必须由独立评审确认「确实非显性、确实改错会出事」，不接受模型自证。

---

## 3. 改动面清单（若采纳）

- **契约/文档**：`shared/gates.md` §4 新增「约束登记（非门）」子节 + 8 行表；不新增门行、不改 §2 判据；同文件 §2.1 AC 行测试计数 62 → 63。
- **地图同步**：`docs/map/gates.md:18` 的 `shared/gates.md` 行数快照按实算更新；若 `docs/map/index.md` / `atlas-map.html` 的 shared 份数不受影响（未新增 shared 文件），不更新。
- **代码逻辑**：无。
- **测试防线**：`tests/test_validate_ac_alignment.py` +1 条 C-03 钉（FAIL / parse_errors / PASS 对照）；无新测试文件；登记 M162a/M162b。
- **版本装配**：无新增文件、无 `install.sh` 自检项、无版本号变化；仅 `gates.md` 行数快照同步。
- [ ] **若未来改走独立 shared 文件**：另案补 `install.sh:550-556` 自检、`docs/map/index.md` 的「8 份」、`atlas-map.html` 的「契约 ×8」、`docs/design/distribution.md` 的 shared 表、`shared/single-source.md` 登记；本 RFC 不做。

本 RFC 已按 §7 落地；本提案文件随同批提交。

---

## 4. 约束登记草案（核心交付物）

> 本节不是门：不参与判定、不计入门总数、不进入 `atlas_check`；权威仍在代码/DESIGN；升格另案。**门/校验器/脚本不得读取本表作为 SKIP/FAIL/通过依据；本表也不得被 `atlas_check` 汇总。** 任何把本表行升格为门的改动，必须迁到 §2 并补假绿测试 + M 系变异，不得在本节原地加判据。
> 六列沿用 `shared/gates.md` §2 的语义；`owner` 写在约束名内，保持六列。`[不变式]` = 语义/结构约束，非自动门。最后一列不标「出厂级」——有测试只写测试与变异；没有就写「待补」，不冒充假绿证明。

| 约束（非门，owner） | 对账平面 | 查什么（不变式） | **不查什么**（显式盲区） | 触发 / 预算 | 锚 / 取证（非门） |
|---|---|---|---|---|---|
| C-01 图谱非 git 新鲜度（owner: `adapters/_graph.py`） | `adapters/_graph.py` 新鲜度键 ⇔ git 工作树 | `[不变式]` 非 git 工作树时 `freshness_key()` 返回空串 + stderr WARN；`ensure_index()` 只认非空 key，空 key 永不判 fresh，每次全量重建 | 不判断图索引内容是否最新（重建由 `--force` 承担）；不替代 `cgc` 版本 pin | 每次图谱消费者查询前 | `adapters/_graph.py:197-204`、`:255-256`；`tests/test_graph_backend.py:140-145`；变异 M161（graph 侧） |
| C-02 查询输出解析（owner: `adapters/_graph.py`） | `adapters/_graph.py` 后端 CLI 输出 ⇔ 上层 JSON 消费 | `[不变式]` `query()` 从首个 `[` 或 `{` 起 raw_decode（跳过启动横幅）；后端 `{"error":...}` 必须 `die`；找不到 JSON 也 `die`，不得返回空列表 | 不校验 Cypher 语义；不保证后端结果业务正确 | 每次 `query()`；超时 120s | `adapters/_graph.py:304-331`；`tests/test_graph_backend.py:155-180`；变异说明见 :13（未编号，待补） |
| C-03 AC 基线快照写回（owner: `validators/validate_ac_alignment.py`） | `validators/validate_ac_alignment.py` 本轮覆盖快照 ⇔ `.atlas/runs/backend-ac-alignment.json` | `[不变式]` 仅当 `result.status != "FAIL"` 且 `not parse_errors` 才写快照；否则不写，避免把坏快照冻成新基线 | 不判断快照内容是否业务正确；不负责修复坏测试 | 每次 AC 门运行末尾 | `validators/validate_ac_alignment.py:492-500`；`tests/test_validate_ac_alignment.py::test_baseline_not_written_on_fail_or_parse_error`（FAIL / parse_errors / PASS 对照）；N/A 不写见 `:1047`；变异 M162a（总写 ⇒ FAIL 分支红）/ M162b（摘 `not parse_errors` ⇒ parse_errors 分支红）；两次还原逐字节一致 |
| C-04 AC 归一化记录不变量（owner: `validators/validate_ac_alignment.py`） | `adapters/ac/` 提取记录 ⇔ validator 契约 | `[不变式]` 必填字段齐；`acs == marker_acs ∪ doc_acs`；两者 ⊆ `acs`；`line>0`；`file` 项目根相对且无 `..`；`(file,line)` 唯一；违反 ⇒ 测试提取契约 FAIL | 不判断测试断言是否语义有效；不判断提取器是否真的跑对框架 | 每次 AC 门消费 extractor 记录 | `validators/validate_ac_alignment.py:238-291`；`tests/test_validate_ac_alignment.py:1144-1169`；D163（`DESIGN.md:639`）；变异待补 |
| C-08 reset 取值清洗（owner: `scripts/atlas_check.py`） | `scripts/atlas_check.py` `e2e.reset` 原值 ⇔ 实际执行命令 | `[不变式]` `_reset_command()` 先 `strip_inline_comment` 再只剥成对包裹引号；调用点与测试必须走同一函数；禁止 `.strip("\"'")` 从两端剥任意引号（会吃掉结尾合法引号） | 不验证命令能否执行（真跑门负责）；不解析 shell 语法 | `check_e2e()` 读取 `reset:` 时 | `scripts/atlas_check.py:134-150`、`:661-663`；`tests/test_atlas_check.py:488-500`；变异 MB9（有） |
| C-09 标量值抽取正则（owner: `scripts/atlas_check.py`） | `scripts/atlas_check.py` stack-profile 标量 ⇔ 门读取值 | `[不变式]` 同行空白只用 `[^\S\n]`，不得用 `\s`；`\s` 会跨行把下一个键名当值（空 `app_base_url` 被误读为已声明） | 不解析完整 YAML；不验证 profile 字段合法性（validate_stack_profile 负责） | `check_e2e()` 读取 `cases_dir` / `app_base_url` / `reset` / `node_modules` | `scripts/atlas_check.py:630-632`、`:644`、`:661`、`:676`；`tests/test_atlas_check.py:266-284`；变异待补 |
| C-10 E2E 执行 cwd（owner: `scripts/atlas_check.py`） | `scripts/atlas_check.py` 生成物相对路径 ⇔ 真跑执行目录 | `[不变式]` 真跑 cwd 必须是生成物所在 `scripts_dir`，不是项目根；`storageState`、`outputDir`、mock fixture 等相对路径以该目录为基准 | 不验证用例语义；不保证登录态有效（真跑结果为准） | `check_e2e()` 真跑分支 | `scripts/atlas_check.py:712-718`；`tests/test_atlas_check.py:507-544`；D106（`DESIGN.md:575`）；变异 MB6（有） |
| C-11 观测面写失败（owner: `scripts/atlas_check.py`） | `scripts/atlas_check.py` `check-events.jsonl` ⇔ 门禁结论 | `[不变式]` `_write_check_event()` 写失败必须静默吞掉；观测面坏了不能反过来把检查判红 | 不保证事件完整；不参与判定 | 每次 `main()` 结束 | `scripts/atlas_check.py:819-836`；`tests/test_atlas_check.py:1111`（写失败不判红）、`:1130`（序列化失败不抛）；变异待补 |

### 4.1 去重说明（不重复登记）

| 初版条目 | 已有落点 | 处置 |
|---|---|---|
| C-05 收口未跟踪文件并入 | `shared/gates.md:56` `closeout_derive.py` 行 | 不再登记；现有正控隐式覆盖，无专用钉 |
| C-06 收口 WARN 范围 | `shared/gates.md:56` 同行；M141/M142 | 不再登记 |
| C-07 生成物第三态 | `shared/gates.md:68` `生成物最新` 行 | 不再登记 |
| C-12 装配版本坏戳 | `shared/gates.md:73` `装配版本` 行；M59/M59b | 不再登记 |

### 4.2 锚缺口（评审重点）

- **C-03（已补）**：`test_baseline_not_written_on_fail_or_parse_error` 覆盖 FAIL / parse_errors / PASS 对照；变异 M162a（总写 ⇒ FAIL 分支红）/ M162b（摘 `not parse_errors` ⇒ parse_errors 分支红）；两次还原逐字节一致。非门，不标「出厂级」。
- **C-02 / C-09**：有测试，变异未编号或未补；本表不标「出厂级」。
- **C-04 / C-11**：有测试，无 M 系变异；本表不标「出厂级」。
- **C-05 / C-06 / C-07 / C-12**：已通过门册登记与变异钉覆盖，不在本表重复。

### 4.3 收录规则

1. 只收「从代码结构看不出来、改错会出事」的约束；通用建议、命名偏好、纯实现细节不收。
2. 每条必须有唯一 owner；跨文件约束归触发文件，不按「受影响文件」铺开。
3. 已在 `shared/` 正文或门册 2.1 有单一权威落点、且没有检索缺口的，不重复收。
4. 没有锚的条目可以登记，但必须写「待补」+ owner；不得标取证等级。
5. 不把门册已有判据改写成「约束」重复登记；门册继续做自动判定，本表只做检索与评审导航。

---

## 5. 验证与评审

### 5.1 已做

- 7 文件样本、32 条 S、逐条回指代码/设计/测试；作者核对 0 条事实错误；样本范围不外推全仓。
- 每条草案的 file:line 已在主仓核对（`git status` 仅 pre-existing `duty-review/QUEUE.md`；本提案为新增未跟踪文件）。
- 现有测试锚已用 `grep` 核对；缺口在 §4.2 明示。
- 2026-11-01 实跑：13 条既有锚 + 1 条新增 C-03 钉 = 14 passed；`tests/test_validate_ac_alignment.py` 63 passed；canonical/map 17 passed。
- C-03 反事实 M162a/M162b：在副本改为总是写 ⇒ FAIL 分支红；摘掉 `not parse_errors` ⇒ parse_errors 分支红；两次还原 sha256 均一致、复绿。
- 漂移/维护实测：改文件 → `stale` → maintain 签发 update 候选 → 还原后 sha 一致。

### 5.2 未做

- 全量 303 条建立；Overview 分块 / Attestation / 跨 Agent 复用；DB cognition；真实大仓规模。
- 8 条约束的独立评审（本轮只做作者侧核查 + 一次只读评审的 blocker/major 抽查）；新增 1 条 C-03 测试与 M162a/M162b 反事实；不做系统性留出验证。

### 5.3 评审问题（已确认）

确认结果（2026-11-01）：采纳并落地；§4 放置、8 条收录、owner 写名内、4 条不重复登记均按本版执行；C-03 已补直接测试锚。

1. 放 `shared/gates.md` §4（本版选择）是否比 §2.7 更稳？是否同意不新建 shared 文件？
2. 去重后 8 条是否全收？C-03 已补直接钉，是否保留在表内？
3. `owner` 写在约束名内是否够，还是必须加第七列？
4. C-05 / C-06 / C-07 / C-12 已在门册，是否同意不重复登记？
5. 是否把「R/A 路径必须存在」作为未来任何认知索引的硬锚（本次 R 错误的直接教训）？

### 5.4 留出验证（模板 §4.5）

- **不适用**：本 RFC 不改门 / 校验器 / 契约判据；不产生判据输出翻转，不触发 (a) 引子族 / (b) 判据路径族。
- 若评审后决定把某条约束升格为门，另案 RFC 必须补：留出集 / pre-fix 红 / post-fix 绿 / 反面包 / 三态结论 + M 系变异。

---

## 6. 附录：AOCI 样本摘要

| 文件 | S 条数 | 其中仅在代码/设计/测试 | 备注 |
|---|---:|---:|---|
| `_support/siblings.py` | 2 | 0 | map/门册/测试已有对应 |
| `_support/review_policy.py` | 4 | 0 | `shared/independent-review` + D129 已有 |
| `adapters/_graph.py` | 7 | ~2 | 非 git 空键、JSON 起点/错误 die |
| `validators/validate_ac_alignment.py` | 2 | ~2 | 基线冻结、记录不变量 |
| `scripts/closeout_derive.py` | 3 | ~2 | 未跟踪并入、WARN 范围 |
| `shared/global-rules.md` | 4 | 0 | 文档自身硬约束 |
| `scripts/atlas_check.py` | 10 | ~6 | 10 条全属实；R 路径写错 |
| **合计** | **32** | **~12** | 0 事实错误；1 条选择不全 |

初版 12 条经评审去重后保留 8 条；上表的 ~12 是样本里「未进入用户文档/共享契约正文」的 S 条款数，不等于本表最终收录数。完整 7 条 FRAS 原文与 AOCI 运行日志保存在临时验证目录，不随仓；本提案只借形态，不复制其索引内容，也不把 AOCI 作为 Atlas 依赖。

---

## 7. 落地记录（2026-11-01）

**状态**：Accepted；canonical 已落地；提交记录见 git log。

**改动**

- `shared/gates.md` §4.1 新增「约束登记（非门）」8 条表；不计入门总数、不进入 `atlas_check`。
- `shared/gates.md` §2.1 AC 行测试计数 62 → 63（新增 C-03 钉）。
- `tests/test_validate_ac_alignment.py` 新增 `test_baseline_not_written_on_fail_or_parse_error`（FAIL / parse_errors / PASS 对照），登记 M162a/M162b。
- `tests/test_graph_backend.py`：graph 非 git 变异 M59 → M161，消除与装配版本 M59 的重号。
- `duty-review/bugs.md`：graph 非 git 变异引用 M59 → M161。
- `docs/map/gates.md:18` 行数快照 153 → 170（M155）；`docs/map` M 编号上限 M150 → M162。
- `docs/map/atlas-map.html` 两处 `shared/gates.md` 描述同步 170 行 + §4.1 说明；M 编号上限 M150 → M162。
- `CHANGELOG.md` / `docs/guide/changelog.md` Unreleased 增加本批记录。

**验证**

- `tests/test_validate_ac_alignment.py`：63 passed。
- `tests/test_canonical_consistency.py`：9 passed。
- `tests/test_map_anchors.py`：8 passed。
- 13 条既有锚 + 1 条新增 C-03 钉：14 passed。
- C-03 反事实 M162a/M162b：在副本改为总是写 ⇒ FAIL 分支红；摘掉 `not parse_errors` ⇒ parse_errors 分支红；两次还原 sha256 均一致、复绿。
- 初版 Draft 引用的不存在的 shared 文件曾使 `test_shared_references_resolve` 实红；改走 §4 后随 canonical 9 passed 复绿。

**C-03 反事实证据（手工，未写入 `.atlas/runs/mutation-proof/`）**

- 注入 A：`if res.status != "FAIL" and not parse_errors:` → `if True:`；`pytest tests/test_validate_ac_alignment.py::test_baseline_not_written_on_fail_or_parse_error` = 1 failed（FAIL 分支）；还原后 sha256 `1d2c366823b3797109431515f86731286fd7242146ae4b379dff75a092bc4075`、1 passed。
- 注入 B：同一行 → `if res.status != "FAIL":`；同一测试 = 1 failed（parse_errors 分支）；还原后同一 sha、1 passed。

**未做 / 残留**

- C-03 已补直接测试锚与 M162a/M162b 手工反事实；非门，表中不标「出厂级」。
- 不新增门 / 校验器 / `atlas_check` 行；不新增 shared 文件；不改 `install.sh` / 版本号。
- 全量 303 条 AOCI 索引未跑；本 RFC 未把 AOCI 作为依赖。
