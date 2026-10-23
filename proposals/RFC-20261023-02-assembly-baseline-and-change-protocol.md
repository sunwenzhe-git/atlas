# 装配基线与变更记录：吸收外部流程规范的三个机制（基线与差异指名、变更最小字段集、显式「无」）

> 提案编号：`RFC-20261023-02`
> 提案作者：（当前会话）
> 关联状态：已定案 (Accepted)（v2 评审「修后采纳」；2026-10-23 实施完成，落 `DESIGN.md` D145/D146/D147；评审记录 `RFC-20261023-02.review.md`）
> 影响范围：核心契约 (shared) | 环契约 (rings) | 校验器 (validators) | 脚本工具 (scripts) | 版本装配 (install.sh)
> 外部输入：2026-10-22 一份外部研发流程规范（13 个节点文档）。本提案只吸收其中三个**机制**，按 Atlas 自身口径重写；不引入任何外部流程名词、角色与平台依赖（`shared/global-rules.md` §15 零业务上下文）。

---

## 1. 现象与取证 (The Problem & Evidence)

### 1.1 触发形态（抽象）

**② 装配基线：漂移只能判「变没变」，判不了「变在哪」**
* **规则 / 环节**：`scripts/pkg_digest.py` 装配版本戳（F30/F37）+ `scripts/atlas_check.py` `check_version()` 装配版本门（`shared/gates.md` §2.2，门行在 :71）。
* **触发时机**：源包前进/落后于装配态时跑 `atlas_check`。
* **具体行为**：摘要只覆盖装配集聚合值。门行文案自证明细缺口——`atlas_check.py:475-480` 的漂移 WARN 块（措施句在 **478-479**）：「差异明细跑 `backflow.py` 三态对账」。外部流程规范的对应机制（部署基线）要求**逐项内容摘要 + 「未解释差异不得判定一致」**：基线的用途不止「发现变了」，而是「解释每一处差异后才允许判定一致」。Atlas 现状 = 发现了，但解释入口在另一个工具、且没有「已解释」的留痕协议。

**③ 变更记录：只记「改了什么」，不记「影响与结论」**
* **规则 / 环节**：域级 PRD §七 变更记录（`templates/prd/domain.md:143-147`：`| 版本 | 日期 | 变更说明 |`）；全局 PRD §十一 修订记录（`rings/prd/reference.md:84`、`:145`）。
* **触发时机**：AC / 范围 / 版本的任何变更落 PRD 时。
* **具体行为**：字段只有版本/日期/说明。外部流程规范的变更记录最小字段集还要求：**变更内容及原因（可区分修改前后） / 影响简述（含待确认项） / 处理结论与确认 / 需补做的事项及关联（无则显式注明无）**。Atlas 缺「影响」与「结论/后续」两列，导致变更后哪些验证结论可以沿用、哪些必须重验，无处承载——而这条原则其实已散落三处、互不知晓：
  * `apply/reference.md` §3.2：无需求卡修订「逐环**只改受影响集合**」；
  * `rings/e2e/reference.md:204` 域收口三值判定 ②：「修后**只复走受影响项**」；
  * `DESIGN.md:597`（D128）：控制台评审绑定提交/脚本指纹，变化 ⇒ `stale` 须重审。
  三处同义，但都不是通则，也没有在变更记录上落点。

**④ 显式「无」：四套写法并存，空白与「评估过为无」不可区分**
* **规则 / 环节**：模板指令「无则写『无』」（仅依赖域一处：`templates/prd/domain.md:23`；In/Out of Scope 处是纯 `[必填]`，无此指令——取证更正）；`不适用（理由：<一句>）`（`rings/prd/reference.md:84`、`:296`）；`未覆盖（沿用实然）`（`:88`、`:101`、`:295`）；控制台 `manual_state: missing` ⇒ 显式「未创建」行（D81 / **M73**，`DESIGN.md:550`；e2e 侧披露在 `rings/e2e/reference.md:649` 节区内）。
* **具体行为**：`validators/validate_prd.py:25` 的 `FORBIDDEN`（TODO/待补充/TBD/待定/视情况而定/后续补充/`[FIELD:]`）**不抓空表/空节**，也不抓 `[必填：…]` 占位符残留；「这张假设表没有内容」与「忘了填」在产物里同形。外部规范对此的原话是「可以填写 `无`，但需要有**显示的结论**」——Atlas 已有单点先例（D81），缺一条通则。

### 1.2 客观证据（仓库侧，可直接复现）

```text
# ② 聚合摘要 ⇒ 明细另跑（漂移 WARN 块 475-480，措施句 478-479）
$ sed -n '475,480p' scripts/atlas_check.py
    rows.add("装配版本", "WARN",
             f"源包已前进/落后于装配态（装配 {stamped} → 当前 {current}）——"
             "生效：npm 全局源包态 `atlas upgrade` 后在项目里跑 `atlas update`；"
             "本地源仓态重跑 `install.sh`；差异明细跑 `backflow.py` 三态对账"

# ③ 变更记录表头（域级模板）
$ sed -n '143,147p' templates/prd/domain.md
## 七、变更记录
| 版本 | 日期 | 变更说明 |

# ④ 占位符表不含空节/空表；四处「无」写法各说各话
$ sed -n '25p' validators/validate_prd.py
FORBIDDEN = ["TODO", "待补充", "TBD", "待定", "视情况而定", "后续补充", "[FIELD:]"]
```

---

## 2. 决策与权衡 (The Decision & Trade-offs)

### 2.1 核心定案 (The Decision)

**② 装配基线：聚合摘要保留，新增逐文件 manifest；「一致性判定」升级为解释制**

1. `pkg_digest` 新增 `manifest(root) -> dict`（`digest()` 复用**同一次遍历**产出的 `(rel, sha256)` 表，禁止二次读盘），结构最小化：`{digest, files: {rel_posix: sha256}}`——时间/源包路径已属 VERSION 三行，不重复（O1）。
2. `pkg_digest.stamp_file()` 写两个文件，**顺序定死：先 `.atlas/MANIFEST.json` 后 `.atlas/VERSION`**（VERSION 最后写 ⇒ VERSION 在场即 manifest 已齐；VERSION 在场而 manifest 缺/空 = 干净的「旧装配」语义，B1）。VERSION 三行契约**不变**。
3. `atlas_check.check_version()`（函数体 :419-481）manifest 分支：
   * **第一步配对校验**：`manifest["digest"] == stamped` 不成立 ⇒ 退聚合文案并指名「manifest 与 VERSION 不配套，重跑 install.sh」（B1）；
   * 配对成立 ⇒ 漂移 WARN **逐文件指名**（`changed/added/removed`，上限 10 + 计数 + 定位计数，O3）；
   * manifest 缺失（旧装配）⇒ 现有聚合文案 + 「重跑 install.sh 补 manifest」；**ok 分支**追加尾注「旧装配无 manifest（正式判据未齐）」——status 仍 ok，不新增红（S4）；
   * 两分支 detail 均须保住 M68 动作词三件套：`atlas upgrade` / `install.sh` / `backflow`（S6）。
4. 契约文字（`shared/gates.md` §2.2 本门行 + `pkg_digest` docstring）：**判定「装配态一致」的充分条件 = 摘要相等 ∧ manifest 覆盖装配集完整**；存在差异时，只有逐项给出解释（`backflow.py` 三态对账 / 收窄注记留痕）才可记「不一致（已解释）」，**未解释差异不得记一致**。运行时仍保持 WARN 语义（漂移是常态信号，非门禁失败——与 `check_drift` 同款）。
5. **不接线** `scripts/release.py`（发布前置检查为后续可选项，避免过度设计）。
6. **manifest 与装配集无自指**：manifest 落 target 侧 `.atlas/`，装配集白名单（`pkg_digest.py:42-44`）不含 `.atlas` ⇒ 不进摘要。

**③ 变更记录：域级 §七 表头升级为 5 列，外加一条「只重验受影响项」通则**

1. 新模板表头：`| 版本 | 日期 | 变更内容及原因 | 影响 | 结论与后续 |`。
   * **影响**：点名受影响的域 / AC / 用例；未触达验证面时写 `无（未触达验证面）`（与 ④ 同词表）。
   * **结论与后续**：接受 / 不接受 / 后续处理 + 需补做的事项及关联；无后续写 `无`。
2. `validators/validate_prd.py`：5 列表头 ⇒ PASS；**legacy 判据放宽**（S2）：「无『影响』列但含『变更说明』列」⇒ WARN「legacy 变更记录形态，下次变更时随迁」（不置红；4 列修订人变体等未知存量形态不首日红）；FAIL 只留「连变更记录都不可辨」形态。
3. **边界句（O2）**：5 列仅域级；全局 PRD §十一 修订记录暂不扩列（`rings/prd/reference.md:84`、`:145` 语义不动）。
4. 通则落 `shared/global-rules.md`（新增一条）：「**变更（含 AC / 范围 / 版本）后只重验受影响项；未受影响且仍有效的结论沿用，并留下沿用依据**」。显式指认三个既有机器落点：D128 `stale`（E2E 评审结论）、`backflow.py` 三态（装配面）、`apply` §3.2（应然资产只改受影响集合）。不新增机器门。

**④ 显式「无」：统一为「空白非法，必须有结论」的通则，首版 WARN**

1. 合法词表**不发明新词**：`无` / `无（理由可选）`，以及三枚既有语义词（`不适用（理由：…）`、`未覆盖（沿用实然）`、控制台「未创建」行）；通则只规定「可无内容不得留空白」。
2. 机器落点（只两处，遵守「落门先问语料」，`rings/prd/reference.md:392`）：
   * 域级 §六（Assumptions & Defaults）表存在且零数据行 ⇒ 须含显式 `无` 或整节 `不适用（理由：…）`，否则 **WARN 指名**（首版 WARN，翻转触发器见 §2.3）；
   * ③ 新增「影响」列单元格空白 ⇒ **FAIL**（层内自含，无存量负担）。
   * **实现边界（S3）**：两条判据必须落 `validate_prd.py` 的**独立 check 行**，不得并入现有 `shape_issues`/参数 4（那里聚合即 FAIL）；新判据同步登记 `shared/gates.md:43` validate_prd 门册行的判据清单（不入册 = 门册与实现分叉，本仓同类事故 #7）。
3. **词表单源（S1）**：`FORBIDDEN` 增补 `[必填`、`[条件必填`，且三处同族词表同步——`validate_prd.py:25`、`validators/validate_structure.py:36`、`shared/global-rules.md:35-38` §5 占位符禁令；新增**词表守恒钉**（两 FORBIDDEN 与 §5 逐词对账）。
4. 模板占位符指令统一为 `[必填；无则写 无（理由可选）]`；仅依赖域已有该措辞（`:23`），属对齐非新增。

### 2.2 考虑过的备选方案及否定理由 (Considered Alternatives)

* **备选 A（②）**：把 manifest 内容塞进 `.atlas/VERSION` 扩成多行/JSON。
  * *否定理由*：VERSION 是已落地的三行契约（摘要/时间/源包路径），`check_version` 按行解析、旧装配无 manifest 走 SKIP 的分支已成型；改格式会让旧副本全军 WARN，且 `stamp_file` 的干跑副作用守卫（`test_install_selfcheck.py:389-430`）需重走一遍。sidecar 增量最小。
* **备选 B（②）**：漂移直接升红门。
  * *否定理由*：漂移是常态信号非缺陷（`check_version` docstring 原话），置红会打断正常开发循环；「解释制」的适用范围是**收口/发布判定**，不是每次 `atlas_check`。
* **备选 C（③）**：保持 3 列表头，把影响/结论塞进「变更说明」单元格。
  * *否定理由*：语义子结构藏在自由文本里，等于没有判据；表格列是最小机械判据的天然载体（与 §五 AC 表列头判据同族，`:388` ⑦）。
* **备选 D（③）**：新增机器门「变更后必须列出受影响用例集，并与实际改动对账」。
  * *否定理由*：AC→用例的受影响集合依赖语义判断（现有 `impact_reconcile.py` 对的是代码 diff 与预测集，语言不同）；先立通则与字段，机器对账留给已有三落点，不新造空头门。
* **备选 E（④）**：全局扫描「所有可无节」做空节 FAIL。
  * *否定理由*：`:392` 已有教训——「落一道门之前先问语料能不能满足它」；存量域 PRD 无法批量保证，先两处 + WARN，避免长期不可满足的红门。
* **备选 F（④）**：为「无」发明统一带理由的单一写法。
  * *否定理由*：四写法各有语义边界（不适用 ≠ 未覆盖 ≠ 未创建 ≠ 无内容），合一会丢语义；通则只消除「空白」，不动语义分化。

### 2.3 必须警惕的刺痛代价与兼容性影响 (Trade-offs)

* **② 旧副本**：无 manifest ⇒ 现有聚合文案 + 补装提示，不新增红；`atlas update` 后自动获得 manifest（`stamp_file` 单点，install.sh 自动覆盖；`bin/atlas.js:91-160` 真跑必过落戳块）。**干跑不落**（沿用既有守卫，install.sh:513-531）。
* **② 半态协议（B1）**：写序「manifest → VERSION」使任何中断都落在「VERSION 旧 + manifest 新」或「两者皆旧」两种可判定态：`check_version` 以 VERSION 在场为唯一「已装配」信号，配对校验不成立即退聚合口径；**不存在「VERSION 新而 manifest 缺」的可信态**。
* **② 性能**：manifest 与 `digest()` 同一次遍历产出，无二次读盘；`.atlas/MANIFEST.json` 体积 ≈ 装配集文件数 × ~90B；`--fast`（`atlas_check.py:756` 无条件执行）新增一次 JSON 读。
* **③ 存量 7 域 PRD**：legacy 形态（3 列或含「变更说明」的变体）⇒ WARN 不红；**不为迁移单独跑一轮**（与「有效工作不重复」同精神），随下次真实变更迁移。
* **④ 存量域 PRD**：§六 空表 ⇒ 首版 WARN；**翻转触发器（显式）**：统计落 per-域收口留痕 README 追加一行「可无项空表：N / 误报：N」（与「手工项」行同格式，`rings/e2e/reference.md:204` 先例），由采用项目收口评审填写；连续两轮收口周期真实遗漏 ≥1 且误报 0 ⇒ 升 FAIL；误报 >0 ⇒ 维持 WARN 并细分判据（S5）。
* **④ 误伤面已核**：`validate_prd.py:364` 反引号剥除先于 FORBIDDEN ⇒ 正文提及安全；`[必填` 带括号不加裸「必填」，避开数据字典「必填」列（`templates/prd/domain.md:73`）；仓内 PRD 夹具无 `[必填` 字面，`test_validate_adr.py:128` 的 `[必填：方案结论]` 走 ADR 校验器无碰撞。
* **不破坏**：VERSION 三行契约、装配集白名单、`atlas_check --fast` 预算、`impact_reconcile.py` 语义面。

---

## 3. 改动面清单 (Affected Surface)

- [ ] **契约/文档**：
  - `shared/gates.md` §2.2「装配版本」门行（:71，② 明细指名 + 一致性判定条款）+ :43 validate_prd 门行判据清单（③④ 新判据登记）
  - `shared/global-rules.md` §5 占位符禁令词表增补（④ 单源）+ 新增「变更后只重验受影响项」通则（③）
  - `rings/prd/reference.md` §4·七（变更记录 5 列与 legacy 过渡）+ 可无项显式通则落点（④）
  - `rings/e2e/reference.md` §10.1 交叉指认（manual_state 先例 → 通则，不发明新名）
  - 模板：`templates/prd/domain.md` §七 表头 5 列、§六 占位指令、Out of Scope/依赖域措辞对齐（③④）
- [ ] **代码逻辑**：
  - `scripts/pkg_digest.py`：`manifest(root) -> dict`（复用 `digest()` 同一遍历，产出 `{digest, files}`）；`stamp_file()` 先写 MANIFEST 后写 VERSION
  - `scripts/atlas_check.py`：`check_version()` manifest 配对校验 → 逐文件指名（cap 10 + 定位计数）；ok/退聚合两分支保 M68 三词
  - `validators/validate_prd.py`：§七 表头三态（5 列 PASS / legacy WARN / 不可辨 FAIL）、§六 空表 WARN，均走**独立 check 行**；`FORBIDDEN` +`[必填`、`[条件必填`
  - `validators/validate_structure.py`：`FORBIDDEN`（:36）同步两词
  - `install.sh`：自检 +1 条（manifest 落下）；干跑闸（513-531）语义不变
- [ ] **测试防线**（**强约束：含 M 系列变异钉子**）：
  - `tests/test_tools.py`：F30 装配集同步钉回归；新增 manifest 形态钉（manifest↔VERSION digest 不得分叉）；**词表守恒钉**（两 FORBIDDEN 与 `global-rules` §5 逐词对账，S1）
  - `tests/test_atlas_check.py`：配对成立逐文件指名 / 不配套退聚合 / 缺失退化 / ok 尾注；**M-new-1** 摘 manifest diff 分支退回聚合文案 ⇒ 钉红；**M-new-4** 摘配对校验（不配也逐文件指名）⇒ 钉红；M68 三词在两分支各自复断言（S6）；cap-10 分支小钉（O3，防上限改 0 也绿）
  - `tests/test_install_selfcheck.py`：F54 ①态干跑后 `MANIFEST.json` 逐字节不变；②态干跑后 `.atlas/` 不在场（现有断言）；**M-new-5** 摘干跑闸 ⇒ 干跑态 MANIFEST 被写 ⇒ 钉红（B2）
  - `tests/test_validate_prd.py`（或既有 prd 测试）：§七 三态、§六 空表 WARN / 显式 `无` PASS；**M-new-2** §六空表判据恒真 ⇒ 钉红；**M-new-3** legacy 不告警 ⇒ 钉红
  - 夹具同步：`[必填` 进 FORBIDDEN 后更新含占位符的坏输入夹具，保持「坏输入在门内、好输入在门外」
- [ ] **版本装配**：`install.sh`（自检 +1；无拷贝列表变化）

---

## 4. 验证与测试结果 (Verification)

（2026-10-23 实施完成；实测结果如下）

```bash
# 1. 相关单元测试
pytest tests/test_tools.py tests/test_atlas_check.py tests/test_install_selfcheck.py tests/test_validators.py

# 2. 出厂级全量（必须全绿）
pytest tests/

# 3. 快速自检
python3 scripts/atlas_check.py --fast
```

* **测试结果（2026-10-23）**：相关四件 **18 / 41 / 9 / 145 passed**（PRD 校验器用例在 `tests/test_validators.py`，原文误写的 `test_validate_prd.py` 不存在）；出厂全量 **642 passed, 4 skipped**；`test_canonical_consistency.py` **9 passed**；`atlas_check --fast` 源包态 exit 0（该态校验器行 `SKIP`：无 `.atlas/validators`，属既有口径）。
* **三态实测**（源包副本 `/tmp/rfc2-src` 装入 `/tmp/rfc2-probe`，`atlas_check --fast` 实跑）：
  1. **真装配** ⇒ `ok 装配版本 源包与装配态一致（8a1c54ce49e334d1，196 文件基线齐）`；
  2. **旧装配无 manifest**（删 `.atlas/MANIFEST.json`）⇒ `ok …；旧装配无 manifest——正式判据未齐，重跑 install.sh 补`（status 仍 ok，S4 成立）；
  3. **漂移**（源包副本 `shared/gates.md` 追加一行）⇒ `WARN …：改 1 / 增 0 / 删 0；改=shared/gates.md。` + M68 三词齐（`atlas upgrade` / `install.sh` / `backflow.py`）。
* **变异四段协议（5/5 全绿，报告含注入 diff，落 `/tmp/atlas-mutation/rfc2/`）**：
  * **M-new-1** 逐文件指名退回聚合（`old, new = {}, {}`）⇒ 漂移钉红；
  * **M-new-4** 摘 manifest↔VERSION 配对校验（`if False:`）⇒ 不配套钉红；
  * **M-new-2** §六空表判据恒真（`if False:`）⇒ 可无项钉红；
  * **M-new-3** 删 legacy 变更记录分支（`elif False:`）⇒ legacy WARN 钉红；
  * **M-new-5** 摘干跑闸（`DRY_RUN -eq 1` → `-eq 99`）⇒ F54 干跑钉红（VERSION/MANIFEST 双断言）。
  五例还原后 sha256 逐字节一致、复跑全绿。
