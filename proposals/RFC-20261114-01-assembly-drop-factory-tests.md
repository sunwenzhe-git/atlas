# 提案标题：装配集摘除出厂测试目录（tests/）——采纳仓装配瘦身，出厂测试回归源包验收面

> 提案编号：RFC-20261114-01  
> 提案作者：@agent_learning  
> 关联状态：草案 (Draft)  
> 影响范围：脚本工具 (scripts)（装配单源 install.py / 回灌清单 backflow.py）

---

## 1. 现象与取证 (The Problem & Evidence)

### 1.1 触发形态（抽象）

* **规则 / 环节**：`install.py` 第 1 步「整包装配到 `<目标>/.atlas/`」的 `pkg_dirs` 白名单（L566-567）包含 `tests`；采纳仓 `atlas_check` 的「对齐测试」行对 `.atlas/tests` **在场即跑**（`pytest .atlas/tests`，`FACTORY_TIMEOUT_S = 1800`）。
* **触发时机**：任何采纳仓装配后第一次跑默认门（`atlas_check` 非 `--fast`）。
* **具体行为**：采纳方第一天就吃到两份不该由它付的重量——
  1. **体量**：`tests/` 是装配面最大单目录——tracked 口径 88 个跟踪文件 / 1.7M（`git ls-files tests/ | wc -l`；`du` 8.2M 中 6.4M 为未跟踪 `__pycache__`），约占 tracked 装配面 41%（其余 shared/scripts/validators/_support/adapters 等合计 ~4.8M du 口径）；
  2. **红噪声**：出厂测试是**源包验收面**，其中相当部分断言的是源仓状态（源包文档锚 / 装配行为子进程 / skill 对称性），放进采纳仓跑必然出现「与采纳方无关的红」。

### 1.2 客观证据与日志 (Minimal Evidence)

干净骨架装配场实测（`install.py --target <临时场> --no-patch --no-wiring --no-skill`，git init 干净基线）：

```text
# 出厂测试在采纳仓的默认门里跑（atlas_check 默认模式，含 pytest .atlas/tests）
7 failed, 1682 passed, 61 skipped in 562.47s (0:09:22)

# 7 个失败构成（采纳方无从分辨哪些与自己有关）：
FAILED test_atlas_solution.py::test_b0_v06_install_update_refuses_v1_with_040_package
FAILED test_atlas_solution.py::test_b0_install_update_main_refuses_before_overwriting
FAILED test_atlas_solution.py::test_b0_install_assembles_package_json_for_reader_version
FAILED test_backfill_contract.py::test_backfill_mode_is_documented
FAILED test_backfill_contract.py::test_backfill_stub_mentions_mode
FAILED test_install_selfcheck.py::test_skill_stubs_reference_existing_contracts   # --no-skill 场
FAILED test_install_selfcheck.py::test_ring_and_skill_are_symmetric               # --no-skill 场
```

**契约先例已声明这是合法态**（`scripts/atlas_check.py` 对齐测试行 SKIP 三态文案，D91/F53，2026-10-16 issue #17）：

```text
SKIP 对齐测试(.atlas/tests)   前置未声明（未就绪，非失败）：... 不存在或不是目录 ——
装配集不含包出厂测试目录（旧发行版装配态 / 源包开发态 / 装配损坏）。
包自检在源包跑（pytest tests）；项目侧跑齐 = 重装取新发行版装配
```

**装配漂移已有专门防线**：装配版本行（`.atlas/VERSION` 指纹对账）+ `MANIFEST.json` 逐文件对账；出厂测试防的是源包工具行为，不是装配漂移。

**该形态从未被显式拍板**：`git log -S'tests' -- install.sh` 显示 tests 自 v1.0.0 首发即在装配循环（b1aefd6），D91 的 SKIP 三态是给「旧发行版 npm 不发布 tests/」的既有事实做兼容，不是「装/不装」的决策记录。

**消融实测（隔离装配场，`scripts/ablation.py` begin/restore 事务，补丁 = tests 全目录删除 diff 81373 行 / 88 tracked 文件（另 1 条为装配场误提交的缓存残留）/ 零 binary）**：

```text
# J1：摘除后 atlas_check --fast 与基线逐行 diff —— 仅一行差异，且为消融事务自身元状态
21c21
<   N/A  消融残留                       无 active 消融（未做实验）
---
>   ok   消融残留                       消融进行中（ablate-tests-20261113，剩余 59 分钟）
# 其余全部校验器 / 装配版本 / 写面残留等实质门行零差异

# J2：摘除后默认模式的对齐测试行 —— 精确落入 D91 三态 SKIP 文案（一字不差）
SKIP 对齐测试(.atlas/tests)   前置未声明（未就绪，非失败）：... 装配集不含包出厂测试目录 ...

# J3：restore 逐字节还原
ablation restore ablate-tests-20261113: completed_hash_only hash_verified=True
# 还原后 atlas_check --fast 与基线逐行零差异（diff 空）
```

---

## 2. 决策与权衡 (The Decision & Trade-offs)

### 2.1 核心定案 (The Decision)

* **方案总结**：装配集摘除 `tests`——**四张清单表同批**（`install.py` `pkg_dirs` / `scripts/pkg_digest.py` `ASSEMBLY_COVER_DIRS` / `package.json` npm `files` / `scripts/backflow.py` `BACKFLOW_DIRS`）去掉 `tests`，装配/更新流程**显式清理存量 `.atlas/tests` 残留**（MANIFEST 基线闸防误删）；出厂测试回归源包验收面（`pytest tests/` 只在源仓跑）。`atlas_check` 仅一处 SKIP 文案出路修订（见 §2.3 M2），门机制零改动（D91 三态已天然兼容摘除态）。
* **为何这是正解**：采纳仓的四件事（写/改用例、跑门、AC 表、bugs.md）经消融实测证明**零依赖** `.atlas/tests`（J1 逐行零差异）；装配漂移防线（装配版本行 + MANIFEST）不受影响（J1 中该行亦零差异）；出厂测试本来就是源包验收语义（D91 文案自证）。单版本约束下这是唯一的纯减法。

### 2.2 考虑过的备选方案及否定理由 (Considered Alternatives)

* **备选方案 A**：分档装配（薄档 = 最小核 / 厚档 = 全量，按需选择）
  * *否定理由*：已拍板否决（2026-11-13）——「太麻烦，心智负担也重，肯定就只有一个版本」；两档引入「你装的是哪一版」的追问成本与测试矩阵翻倍。
* **备选方案 B**：装配 tests 的子集（区分「工具单测」与「对齐测试」两类）
  * *否定理由*：tests/ 89 文件无此分类边界（工具单测 / 装配行为测试 / 文档锚测试混装），引入分类机制 = 新机械 + 新维护面；且对齐子集仍会把「源包状态断言」的偶发红带进采纳仓。
* **备选方案 C**：维持现状（装配即全量），把 7 failed 当已知噪声教给采纳方
  * *否定理由*：红被训练成噪声正是 D91 注释里明文警示的反面教材（「两相反结论并存，红被训练成噪声」）；且 9m22s 的默认门耗时全部由采纳方支付，换不来采纳方收益。

### 2.3 必须警惕的刺痛代价与兼容性影响 (Trade-offs)

* **四表同批（评审 M1，必修）**：装配面实为四张清单表——`install.py pkg_dirs` / `pkg_digest.ASSEMBLY_COVER_DIRS`（VERSION+MANIFEST 摘要口径，两端同 import）/ `package.json npm files`（分发面）/ `backflow.BACKFLOW_DIRS`。只摘装配面会留下：摘要口径含 tests（违反 pkg_digest 自述不变量）、npm 发行版带 1.7M 死重、「装配版本」WARN 逐文件指名被 tests/* 主导（恰与消噪初衷相反）。同步钉 `test_f30`（F30）现只钉 `pkg_dirs ⊆ cover` 单方向，本次补 `cover ⊆ pkg_dirs ∪ {skills}` 反向钉坐实「双向」注释；`test_f47` 双方向在摘除后均不红（当年 M-R8 前提「npm 缺 tests ⇒ 门恒红」消亡），`gates.md` 门表 M-R8 叙事加失效时点注记。
* **兼容性**：存量项目 `--update` 后 `.atlas/tests` 不会被白名单刷新循环删除（循环只删白名单目录）⇒ **必须**在装配流程加显式清理（孤儿 tests 若不删，将继续被默认门跑且永不刷新，比现状更糟）。**清理必须带 MANIFEST 基线闸（评审 M3，必修）**：现存文件全部命中 `.atlas/MANIFEST.json` 登记的出厂基线 hash ⇒ 纯出厂残留，删；存在基线外或 hash 不符文件 ⇒ 响亮列名拒绝（对齐测试门「目录在场即跑」的语义会邀请采纳方往 `.atlas/tests` 种自己的集成测试，rm 不可逆），`--force` 越过；清理动作走 `install.py run()` 保 dry-run 语义，fresh 场幂等 no-op。
* **SKIP 文案出路修订（评审 M2，必修）**：现行 D91 文案出路「项目侧跑齐 = 重装取新发行版装配（install.sh / atlas upgrade）」在摘除后成为死路——任何新发行版装配都不含 tests，照文案重装永远无法兑现，采纳方会陷入 重装→SKIP→再重装 循环。成因枚举补「新发行版装配态（出厂测试已回归源包）」，出路改述为「包自检在源包跑（pytest tests）；项目侧无跑齐义务；历史装配态经 atlas upgrade / install.sh 更新后本目录随之移除」。同批：`test_atlas_check.py` 出路 token 组钉（四 token 全保留，钉不破）、`gates.md` 门表行注记。§2.1 原表述「`atlas_check` 零改动」据此更正——门机制零改动，文案一句修订。
* **职责转移**：采纳仓失去「出厂测试在装配副本上直接跑」的对齐面。该职责由既有「装配版本」行（指纹）+ MANIFEST 逐文件对账承接；行为级漂移由真跑门承接。出厂测试防「源包工具回归」，与采纳仓无关。
* **golden 装配集**：装配集内容一变必须 `--record` 重录（harness 纪律），验收口令 `harness.py --check --installer install.py` 全绿。
* **脚本耗时**：采纳仓默认门从分钟级（含出厂测试 pytest）降为秒级（对齐测试行 SKIP）；源仓出厂测试耗时不变（`FACTORY_TIMEOUT_S = 1800`）。
* **顺带发现（已定案，非缺陷）**：消融实测中「装配版本」行在装配刚完成后即 WARN（装配指纹 `f2d3b6be…` → 当前 `e81f47a5…`，改 4 文件）——落刀后对提交树（bfc8563）fresh 装配复验，装配版本行 `ok`（`8e0e93b5…`，204 文件基线齐）⇒ 该 WARN 是并行会话 issue #63 批在装配后改动那 4 个文件的**真实漂移信号**，机制工作正常，无需另案。

---

## 3. 改动面清单 (Affected Surface)

- [ ] **代码逻辑**：`install.py`（pkg_dirs 去 `tests`（L566-567）；新增存量 `.atlas/tests` 显式清理 **带 MANIFEST 基线闸**；头部用法注释 L11 同步）
- [ ] **代码逻辑**：`scripts/pkg_digest.py`（`ASSEMBLY_COVER_DIRS` 去 `tests`（L52-53）；注释「装配集白名单与 install.sh 对齐」改指 install.py）
- [ ] **代码逻辑**：`package.json`（npm `files` 去 `tests`（L27））
- [ ] **代码逻辑**：`scripts/backflow.py`（`BACKFLOW_DIRS` 去 `tests`（L38-39）；L11/L37「与 install.sh 循环一致」改指 install.py——单源已迁）
- [ ] **代码逻辑**：`scripts/atlas_check.py`（对齐测试 SKIP 文案出路修订，L293-297；门机制零改动）
- [ ] **契约/文档**：`shared/gates.md`（门表 M-R8 叙事加失效时点注记；对齐测试门行注记摘除时点）
- [ ] **代码逻辑**：`install.sh`（头注 L10-11 装配目录列举同步；单源在 install.py，无独立循环）
- [ ] **测试防线**：`tests/test_tools.py` F30 补反向钉（`cover ⊆ pkg_dirs ∪ {skills}`，坐实「双向」注释）
- [ ] **测试防线**：新增 `tests/test_assembly_surface.py`——四表同批守恒钉（任一表加回 `tests` ⇒ 红，M 系列变异钉）+ 清理函数行为钉（出厂残留删 / 基线外拒绝 / fresh 幂等）
- [ ] **留出验证（§4.5）**：触发面核对命令原始输出落 §4.5
- [ ] **版本装配**：golden 装配集 `--record` 重录（`proposals/RFC-20261103-04-installer-golden/`）；`package.json` 版本随发版批 bump

---

## 4. 验证与测试结果 (Verification)

落刀后必须全绿：

```bash
pytest tests/                      # 出厂测试全量（源包）
python3 scripts/atlas_check.py --fast
harness.py --check --installer install.py   # golden 全绿（重录后）
# npm 分发面：npm pack 产物 tarball 不含 tests/（M1 分发面验收）
# 装配场复验：干净目录 install.py 装配 → .atlas 无 tests
#   → atlas_check 默认模式：对齐测试行 SKIP（新文案）、其余与摘除前 fast 逐行一致（含装配版本行）
#   → --update 存量场：MANIFEST 基线闸后 .atlas/tests 不存在；基线外文件场 ⇒ 响亮拒绝
#   → 默认模式 diff（评审 i1）：装配版本行 ok 态下摘除前后默认门全行 diff
```

* **消融实测记录**：见 §1.2（J1/J2/J3 全过，隔离场 `/tmp/atlas-ablation-field`，ablation 事务 begin→restore `hash_verified=True`）。
* **测试结果**：回填于落刀批（锚类失败已修：docs/map 七处数字/符号锚 + gates.md 计数；全量 pytest 最终态见批注提交记录）
* **自检结论**：装配场三场复验全过——① fresh 装配零 tests / MANIFEST 零 tests 条目 / 对齐测试行 SKIP 新文案（四 token 齐）；② 存量场 --update 残留 77 文件 → 0；③ 基线闸拒绝场 exit 2 逐字指名 `tests/my_integration_test.py（基线外）`、--force 越过 exit 0 + WARN。golden `--record` 已跑全绿（9 场景），产物未随本批（工作区含并行会话 #63 批未提交改动，待干净树重录——装配集一变就 --record 纪律由后续批承接）

### 4.5 留出验证（系统性修复必填；`RFC-20261026-03`）

* **触发面核对**：(a) 本案非缺陷修复族（装配面减法，无 bugs.md 同根引子族）；(b) 改动落在 `install.py` / `scripts/backflow.py`——对照 `scripts/closeout_derive.py` 路径族表核对是否触碰门判据段级锚路径族。**落刀时粘贴 `git diff --name-only` + closeout_derive 对照两条命令原始输出**，据实记「锚 → 路径族」映射或「不适用 + 核对依据」。
* **留出集 / pre-fix 红 / post-fix 绿 / 反面包**：落刀后按实跑回填；本性质为装配面变更而非判据修复，预判走「单案修复（无留出集）」或「不适用」，评审确认。
