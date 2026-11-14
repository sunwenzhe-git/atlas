# 提案标题：同步税卸载脚本——changelog 前置守卫 + 计数锚自动改齐（「消重不减防」）

> 提案编号：RFC-20261114-04  
> 提案作者：@agent_learning  
> 关联状态：草案 (Draft)  
> 影响范围：脚本工具 (scripts)（新增两脚本；零新门零新字段）

---

## 1. 现象与取证 (The Problem & Evidence)

### 1.1 触发形态（抽象）

* **规则 / 环节**：两条仍然纯手动的同步税——
  1. **changelog 前置补写**：feature commit 涉及装配面时须手补 `CHANGELOG.md` 与 `docs/guide/changelog.md` 两份 `[Unreleased]` 段（发版规范在案：「feature commit 漏写 changelog 时须手补两份」）；release.py 只在发版时**收拢** `[Unreleased]`（L277-302 实读），**不检测 feature commit 是否漏写**——漏写只会在发版日被发现，届时手工追忆。
  2. **计数锚人工改齐**：改动装配面（新增测试文件 / 改 install.py 等行数敏感文件）后，docs/map 数字快照（index.md + atlas-map.html 两措辞）+ gates.md 门册计数 + apply.md 行数锚须人工逐处改齐并跑三面。既有 `test_map_anchors.py` 是**保活门**（锚过期 ⇒ 红），只判不改——改的动作全人工。
* **触发时机**：每个 feature commit（税 1）/ 每次动装配面行数或文件数（税 2）。

### 1.2 客观证据与日志 (Minimal Evidence)

- 税 1 风险实证：CHANGELOG 标题 ≠ 实发跳号事故（beta.17→19，在案）；RFC-20261114-01 落刀批同样未写 changelog 段，靠 #63 批恰好起头 `[Unreleased]` 才未成漏——**同一会话两个 feature commit，一个漏写无人发现，守卫缺失是结构性的**。
- 税 2 实证（本批亲历）：RFC-20261114-01 落刀后 `test_map_anchors` / `test_canonical_consistency` 咬红 **7 处锚**（出厂测试文件数两措辞 + html ×76 + index.md 快照 + cli.md 两行数 + gates.md 一行数 + canonical 计数），人工逐处改齐 + 复跑 ≈ **9 分钟**；且曾因批量脚本笔误截断 `docs/map/index.md`（'w' 模式二次打开）——人工批量改数字既慢又易错。
- 「消重不减防」原则（2026-11-13 用户方向）：重量从人身上卸到脚本，检查本身保留（保活门不动）。

---

## 2. 决策与权衡 (The Decision & Trade-offs)

### 2.1 核心定案 (The Decision)

* **方案总结**：新增两个独立脚本（进 `scripts/` = 进装配集；**零新门**——挂点全部落在既有**人侧收口清单触发表**，不进 atlas_check 机器门序列）：
  1. **`scripts/changelog_guard.py`**：对指定 commit 范围（缺省 `HEAD~1..HEAD`，另留 `--range <A..B>` 供事后审计）取 `git diff --name-only`，命中**检测集单常量**即要求两份 changelog 同步——
     * **检测集定死一处**：`DETECT = pkg_digest.ASSEMBLY_COVER_DIRS ∪ pkg_digest.ASSEMBLY_COVER_FILES ∪ {install.py, install.sh, package.json, bin}`，并**排除 changelog 自身**（`CHANGELOG.md` / `docs/guide/changelog.md`；仓内 changelog 面只有这两份，`docs/map/atlas-map.html` 无 changelog 段）。不引 `backflow.BACKFLOW_DIRS`——两表不等（`BACKFLOW_DIRS` 无 `skills`、无 `LICENSE`，`scripts/backflow.py:39`），混用会漏检。
     * **判据写死**：`CHANGELOG.md` 与 `docs/guide/changelog.md` **两份**的 `[Unreleased]` 段内**新增行 ≥ 1**（用 `git diff --range -- <changelog>` 数段内 `+` 行）；**段在但段内零新增 ⇒ 红**（#63 批「起头了但没写内容」的掩蔽形态，反面钉）。任一份不合格即 exit 1。
     * **只提示不改写**——补写内容语义归人，输出补写模板（段式：「### 📦 <环>：<一句话>（<RFC/issue 号>）」）。
  2. **`scripts/refresh_count_anchors.py`**：按**工作树采集**（与保活门 `test_map_anchors` 同平面，缺省值即工作树），`--from HEAD` 留提交后对账口子。对锚格式**白名单正则**逐处改写数字（只动数字不动措辞；白名单外锚一律跳过并打印「未识别锚 N 处」）——**宁漏改不误改**，漏改由既有保活门兜底红。
     * **脏树告警**：对行数敏感文件（`install.py` / `install.sh` / `scripts/atlas_check.py` / 被点名的 `scripts/*.py`），若工作树 ≠ HEAD ⇒ 响亮告警「数字按工作树现值写，须与锚同批提交，否则干净树咬红（a0bdd53）」并继续（不阻断）。
     * **白名单枚举格式而非枚举文件**：路径从锚自身提取、行数现场点数；`docs/map/index.md` 数字快照行复用 `tests/test_map_anchors.py::_derive_snapshot` 的**同名映射**（8 个实收键：校验器 / 出厂测试文件 / skills / 环 / 共享契约 / 共享内核 / install.sh 自检声明 / 最大单件），不另抄一份键表。`最大单件` 命中易主时**打印提示（旧件 → 新件）但不自动改文件名**。
     * **写后自检**：写完在进程内复跑 `collect_docs` / `check_snapshot` / `check_freshness`，**余漂非零 ⇒ exit 1**（不把「写完了但不绿」留给人工发现）。
     * **明确不覆盖**：删除「装配面文件总数」项（无消费锚）；`docs/map/index.md` 的「install.py 自检声明 66 条」行**无人判**（映射只产 `install.sh 自检声明`），`编排门行` 为语义行——两行在输出里显式标「范围外」，不假装覆盖。**canonical 计数**（`tests/test_canonical_consistency.py` 里写死的 shared/gates.md 条数等）也是 refresh 范围外的残余税，须人工改齐。
     * **副本态/非 git 语义**：`CHANGELOG.md` / `docs/map/` 缺席或本仓非 git ⇒ **响亮 SKIP**（exit 0 + 「本器源包态专用」短句），文案风格对齐 `scripts/closeout_derive.py:180-182`。
  * 挂点（都是既有表，加行不加门）：`shared/closeout.md:13` 触发表行「改契约 / 模板 / 校验器 / 脚本 / skill 瘦桩」**补写两脚本名**（只加名，不动步骤列 `1 → 2 → 5 → 7`）。**不再挂 `scripts/release.py`**（发版时才提示 = 时机已过，不值动发版脚本）。
* **为何这是正解**：两条税都是**机械可推导**的（装配面 diff ⇒ changelog 该有段；实收 ⇒ 锚数字），人工只做语义部分（changelog 写什么 / review diff）。检查面零新增（保活门、canonical、closeout 全保留），动的只是「谁改数字」。
* **有意的不对称（写明）**：纯测试批（只动 `tests/`）**不触发** changelog 守卫（`tests/` 不在检测集）——这是有意的（纯测试批无需 changelog 段）；但 `tests/` 文件数变动**仍需** `出厂测试文件` 锚随改，走 refresh 而非守卫。

### 2.2 考虑过的备选方案及否定理由 (Considered Alternatives)

* **备选 A**：做成 pre-commit / CI 机器门（强制拦截）
  * *否定理由*：新机器门违反零新门纪律；changelog 漏写有合法形态（纯文档批不涉装配面），强制门必带白名单豁免 = 门复杂化。收口清单 + 可跑脚本已把「忘补」成本降到「收口时跑一下」。
* **备选 B**：refresh 脚本直接改 docs/map 全文锚（含措辞重排）
  * *否定理由*：措辞归人、数字归机器——「只动数字」的正则白名单宁窄勿宽；措辞改动若由脚本做，一次误替换就是本批亲历的 index.md 截断事故复刻。
* **备选 C**：把计数锚从「实收对账」改为「不写数字」（根治）
  * *否定理由*：锚数字的保活价值正是「N 行⇔wc / ×N⇔实收」的刻意棘轮（docs/map 保活门首跑咬出真漂移的机制在案）；去数字 = 拆防。

### 2.3 必须警惕的刺痛代价与兼容性影响 (Trade-offs)

* **脚本进装配集**：`scripts/` +2 文件 ⇒ 摘要面 / 装配面变化 ⇒ golden `--record` 重录 + `backflow` 清单守恒自动适配（BACKFLOW_DIRS 是目录级，无需改）+ docs/map 行数锚（scripts 目录合计行若有）随实况改齐——落刀时按计数棘轮链走全。
* **白名单维护**：锚格式演进（新增锚措辞）须同步白名单——脚本跳过未识别锚并打印清单，漏改可见（不是静默）。
* **脏树告警的摩擦**：工作树与 HEAD 不一致时脚本仍会按工作树写数字并告警——正确用法是「改文件 + 跑 refresh → 锚与源同批提交」，错误用法（先提交源码再跑 refresh）会立即被告警与保活门同时咬住，不再有静默错写。
* **存量采纳仓**：`--update` 后副本获得两脚本（装配面随包）——采纳仓同样可跑 changelog_guard（对采纳仓自己的提交）；行为对旧装配态无影响（脚本不被任何门调用）。
* **执行耗时**：两脚本均为秒级（git show + 正则），无预算面影响。

---

## 3. 改动面清单 (Affected Surface)

- [ ] **代码逻辑**：新增 `scripts/changelog_guard.py`（DETECT 单常量 ⇒ 两份 changelog `[Unreleased]` 段内新增行 ≥ 1，只提示不改写）
- [ ] **代码逻辑**：新增 `scripts/refresh_count_anchors.py`（工作树采集 + 形式白名单 + 写后自检 + 脏树告警 + 副本态 SKIP）
- [ ] **契约/文档**：`shared/closeout.md:13` 触发表行补两脚本名（人侧步骤，非门；不动步骤列）
- [ ] **测试防线**：`tests/test_sync_automation.py`——
  * changelog_guard：装配面变更 + 缺段 ⇒ exit 1 / 段在场且段内有新增 ⇒ 0 / **段在场但段内零新增 ⇒ 1（掩蔽形态）** / 纯文档批 ⇒ 0（豁免形态）/ 两份 changelog 只写一份 ⇒ 1；
  * refresh_count_anchors：喂假锚场 ⇒ 数字改齐 / 白名单外锚 ⇒ 跳过并打印 / **跨工具绿**（夹具仓改行数敏感文件 → refresh → 断言 `test_map_anchors` 三函数绿）/ **脏树行为钉**（工作树 ≠ HEAD ⇒ 告警且按工作树写）/ **幂等零 diff**（显式构造 工作树 == HEAD 前提）/ 写后自检余漂 ⇒ exit 1 / 非 git 副本态 ⇒ 响亮 SKIP exit 0；
  * **守恒钉**：`DETECT ⊇ ASSEMBLY_COVER_DIRS`（防检测集日后被悄悄收窄）。
- [ ] **留出验证（§4.5）**：触发面核对见下
- [ ] **版本装配**：装配集 +2 文件 ⇒ golden `--record` 重录；docs/map 行数锚随实况改齐；`package.json` 版本随发版批 bump

---

## 4. 验证与测试结果 (Verification)

```bash
pytest tests/test_sync_automation.py tests/test_map_anchors.py tests/test_canonical_consistency.py
pytest tests/                              # 出厂全量（装配集 +2 后）
python3 scripts/atlas_check.py --fast
harness.py --check --installer install.py  # golden（重录后）全绿
# 行为级：本批自身落地时即吃狗粮——refresh_count_anchors 跑本批锚改齐，changelog_guard 对本批 commit 实跑
```

* **测试结果**：回填于落刀批
* **自检结论**：回填于落刀批

### 4.5 留出验证（系统性修复必填；`RFC-20261026-03`）

* **触发面核对**：(a) 非缺陷修复族（新增工具，无 bugs.md 同根引子；「锚截断事故」为过程性笔误，修复随本工具落地自然消解，不作引子）；(b) 改动面 = scripts/ + closeout.md 触发表行——落刀时粘贴 `git diff --name-only` + `scripts/closeout_derive.py` 对照原始输出（closeout_derive L72 明示 tests/ 归「脚本」族），据实记「锚 → 路径族」映射或「不适用 + 核对依据」。
* **留出集 / pre-fix 红 / post-fix 绿 / 反面包**：性质 = 新增工具非判据修复，预判「不适用」，评审确认；两脚本行为钉自带正反面（缺段红 / 在场绿；掩蔽红 / 跨工具绿；假锚改齐 / 幂等零 diff）。
