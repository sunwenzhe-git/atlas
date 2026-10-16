# 提案：`atlas_check` 包自检门的前置降级 —— 缺 `.atlas/tests` 记 SKIP（未走到这一步）而非恒红 FAIL

> 提案编号：RFC-20261016-02
> 提案作者：@Agent 起草（会话内）
> 关联状态：**v2 —— 已吸收独立评审 1 条 blocking + 2 条 major + 4 条 minor，全部采纳，无驳回**
> 影响范围：脚本工具 (scripts/atlas_check.py) | 门册 (shared/gates.md) | 决策/变更登记 (DESIGN.md) | 测试 (tests/test_atlas_check.py)
> 关联 issue：`#17`（**残余部分**；装配面根因已由 RFC-20261016-01 D86/F47 修掉）｜ 批内 F 号：**F53**；决策号：**D91**（D82–D90 已被批 9818502 与此前各批占用）

---

## 1. 现象与取证 (The Problem & Evidence)

### 1.1 与 D86 的关系：根因已修，门的形态没有跟上

D86（F47，已在 9818502 落地）修的是**装配面根因**：`package.json.files` 补 `tests` ⇒ npm 分发开始携带 `tests/`，install.sh 的 `cp -R` 从空操作变成真拷 ⇒ **未来**发行版装配出的项目副本 `.atlas/tests` 存在，门有对象可跑。

但 `check_factory` 本身（`scripts/atlas_check.py` L173–178）至今**无前置判据**，无条件 `pytest .atlas/tests`。两类场景仍然撞到 issue #17 的病灶：

| 场景 | `.atlas/tests` | 现今行为 | 应有行为 |
|---|---|---|---|
| ① 存量装配：beta.17 及以前发行版（npm 通道）装配的项目 | 不存在 | `FAIL`（pytest 退出码 4，`file or directory not found`），整体门判 FAIL | `SKIP` + 出声指路（采用者自己修不了的红训练成噪声——issue #17 的本体关切） |
| ② 源包开发态（atlas 仓根，无 `.atlas/`） | 不存在 | 同上 | 同上 |
| ②a 装配损坏：`.atlas/tests` 被文件占用（评审 M-1 实测：pytest 对 file 形态收集 0 条 exit 0 ⇒ 现行判 `ok`，一个现存的**假绿边界**；本批前置判据顺带关闭它） | 在场但非目录 | `ok`（更糟） | `SKIP`（判据一道覆盖，文案不作假陈述） |
| ③ D86 后的合法装配态 | 存在（目录） | 真跑，真红仍红 | **不变**（本提案不动） |

* **与既有纪律的落差**：本文件里三态语义已有两处同族先例——`check_validators` 的 `_GATE_PRECONDITIONS`（前置未声明 ⇒ `SKIP`+原因，「不是通过，且必须带原因」）与 `check_generated` 的 `GEN_NOT_READY`（`SKIP`「前置未声明（未就绪，非失败）」）。出声道具在手边，只是没用在出厂测试门上。现场实测（issue #17 帖 + 本地复跑）更是「全量恒红、`--fast` 恒绿」——同一扇门两条路给两个相反结论，正属它自己点名的「门看起来在跑 / 红灯训练成噪声」族。

### 1.2 客观证据 (Minimal Evidence)

```text
# 存量装配（现场项目，issue #17 原帖）
$ python3 .atlas/scripts/atlas_check.py --root .
  FAIL 对齐测试(.atlas/tests)  ERROR: file or directory not found: .atlas/tests   # exit 4 → 整体 FAIL
$ python3 .atlas/scripts/atlas_check.py --root . --fast
  OK                       # 同一次运行
$ ls .atlas/                # 装配集：_support adapters apply extensions patches rings runs scripts shared templates validators（无 tests）

# 判据位置
scripts/atlas_check.py  L174: code, out = run([py, "-m", "pytest", ".atlas/tests", …])   # 无存在性判据
同文件先例               L49–74:  _GATE_PRECONDITIONS（三态前置，SKIP 带原因）
install.sh              L149/154: 拷贝列表含 tests（能拷时会拷）；npm 旧发行版无 tests/ 目录 ⇒ 拷贝空操作
scripts/pkg_digest.py   L42:     ASSEMBLY_COVER_DIRS 含 tests（门 2.3 摘要同样算它）
```

---

## 2. 决策与权衡 (The Decision & Trade-offs)

### 2.1 核心定案 (D91 —— 前置降级，三态语义并入出厂测试门)

1. `check_factory` 在跑 pytest **之前**先判前置：`<root>/.atlas/tests` 不是目录（**覆盖「不存在」与「在场但是文件」两态**——评审 M-1：只说「未找到」对文件形态是假陈述）⇒ `rows.add` **`SKIP`**，文案必须同时给出「判据面」与「出路」两层信息（连实测路径，同「结构漂移 SKIP 带实际路径」先例）：

   > `前置未声明（未就绪，非失败）：<path>/.atlas/tests 不存在或不是目录 —— 装配集不含包出厂测试目录（旧发行版装配态 / 源包开发态 / 装配损坏）。包自检在源包跑（pytest tests）；项目侧跑齐 = 重装取新发行版装配（install.sh / atlas upgrade，需解释器可跑 pytest）`

   其余门行为零变化：`rows.failed` 不含 `SKIP` ⇒ 全量模式回到**整体可用**，且跳过原因在门总览逐行可见（不静默、不当成 ok）。
2. `.atlas/tests` **存在**（目录）⇒ 一切行为逐字节不变：真跑 pytest，真红仍 `FAIL`（防「把真失败一并降级成 SKIP」——本提案的降级只吃「断言对象不在场」这一种情形；反面钉 A-2 守这条）。
3. **登记面**：门册 §2.2「对齐测试(.atlas/tests)」行——前置判据进「查什么」列、两条盲区显式化进「不查什么」列（评审 M-2：pytest 解释器可用性——无 pytest ⇒ `FAIL` 指名，环境缺失自修；评审 m-4：在场但零用例 ⇒ `no tests ran` 仍 `FAIL`，装配损坏值得查）+ 新钉与计数登记（`tests/test_atlas_check.py` 22 → **24 条**，机器审计口径 pytest 实收）；`DESIGN.md` 登记 **D91** + **D86 ② 行尾追加 D91 收窄注记**（评审 B-1，阻塞件——见 §2.2-A 与 §6）。

### 2.2 考虑过的备选方案及否定理由 (Considered Alternatives)

* **A（装配时报一句「包自检需在源包跑」，issue 原文提议 ① 后半）**：D86 之后装配**已经**带 tests，常态装配输出里每次打这句话 = 把一句只在异常态有用的信息变成常态噪声。*否定成立*；它的语义被 SKIP 文案吸收——指引出现在采用者**真正需要它**的那一次跑上。
* **B（缺目录时记 `ok` 并说明）**：违反三态语义铁律「SKIP 不是通过，且必须带原因」——把「未走到」伪装成「走过且绿」，比 FAIL 更坏。*否定成立*。
* **C（WARN 而非 SKIP）**：WARN 在本档门册里是「跑了、判据不咬」；目录不存在根本没跑，性质是「未走到这一步」，WARN 会污染真 WARN（漂移 / 源前进）的语义。*否定成立*（同 `EmptyAssembly` 行的「本仓 SKIP = 合法降级」——此处恰是合法降级）。
* **D（把该门挪进 `--fast`）**：门语义变化更大（丢掉每次全量跑真实出厂自检的能力）。*否定成立*。
* **B-1（评审 blocking：D86 ② 的在案否决未收窄）**：`DESIGN.md` D86 ② 原文明文否决「`atlas_check` 遇缺就 SKIP」——彼时否决成立的条件是**根因未修**（采用者出路不可达，SKIP 确属洗白）；根因（9818502）落地后该条件的失效面 = 「`.atlas/tests` 不在场」的残余态。*处置 = 采纳收窄而非推翻*：D91 落 `DESIGN.md` 新行，D86 行尾追加收窄注记，并把不可回退的根因纪律单独立句（**装配三表同步永远不得改靠 SKIP 吸收**）——两条记录从此各管一段，不再互斥。

### 2.3 必须警惕的刺痛代价与兼容性影响 (Trade-offs)

* **谁会「变绿」**：存量装配的全量模式从「恒红」变「绿 + 一条 SKIP」。这是**诚实的降级不是粉饰**：该红的那扇门（真跑测试）从未真的跑过，之前只是把 pytest 的 404 记成红；同时「装配版本」门仍对旧装配报 WARN（源已前进）——交叉信号指向重装，出路链完整。
* **不会把③变绿**：`FAIL` 分支逐字节不动；触发物（必红测试）在反面钉 A-2 里钉住。
* **`--fast` 不受影响**：快跑本就不调用 `check_factory`；本提案只改全量路径上「跑」之前的那一步。
* **装配戳**：本批改动全在装配集白名单目录内 ⇒ 装配戳失配 ⇒ 「装配版本」门 WARN，**由副本重装对账复绿**（传播义务，不是新问题）。
* **不改的东西**：不改门行名不改退出码语义；`pytest` 命令形态与超时（900s）原样；`SKIP` 文案不进 `failures`。

---

## 3. 改动面清单 (Affected Surface)

- [x] **代码逻辑 · D91**：`scripts/atlas_check.py`（`check_factory` 前置判据 + SKIP 文案；目录在场 ⇒ 行为逐字节不变）
- [x] **门册**：`shared/gates.md` §2.2 对齐测试行（前置进查什么、盲区进不查什么、M76 + F53 登记 + 计数 22→24）
- [x] **决策登记**：`DESIGN.md`（D91 新行；D86 ② 行尾 D91 收窄注记）
- [x] **测试防线**：`tests/test_atlas_check.py`（钉 A-1 三形态 + 出路动作词齐组；反面钉 A-2）

### 3.1 测试钉子（逐字节取证的注入形态）

| 钉 | 注入 | 期望 | 落点 |
|---|---|---|---|
| A-1 | 缺 `.atlas/tests` 三形态（无 `.atlas/` / 有 `.atlas/` 无 `tests/` / 路径被文件占用），全量模式 | 对齐测试行 `SKIP`（文案带实测路径 + 判据面与出路两层：`pytest tests` / `install.sh` / `atlas upgrade` 动作词齐组）、整体退出码 **0**、不在 `failures` | `tests/test_atlas_check.py::test_f53_factory_gate_skips_when_tests_dir_absent` |
| A-2（反面） | `.atlas/tests` 在场（目录） + 注入一条必红测试 | 对齐测试行 **`FAIL`**（1 failed）、整体退出码 1、进 `failures` | `tests/test_atlas_check.py::test_f53_factory_gate_still_fails_on_red_tests` |
| M76 | 前置判据置死（`if False and …` ≙ 摘掉分支） | A-1 **红**（回到 exit 4 恒红）；A-2 不受影响（真红仍真红） | 手工注入：红 → 逐字节还原（sha 前 16 位 `2494e04f525be144` 一致）→ 全绿 |

---

## 4. 验证与测试结果 (Verification)

```bash
python3 -m pytest tests/test_atlas_check.py -q          # 24 passed（22 → 24）
python3 -m pytest tests/test_canonical_consistency.py -q # 登记面审计（计数 / 引用 / 门调度）
python3 -m pytest tests -q                              # 出厂级全量
python3 scripts/atlas_check.py --fast                   # 源包态自证
```

**修复前基线**：`433 passed, 4 skipped`（RFC-20261016-01 收口数）；本批落地后全量结果见 §5。

---

## 5. 执行记录

1. 落地顺序：`check_factory` 前置分支 → 钉 A-1/A-2 → `test_atlas_check.py` 24 绿 → M76 变异四段取证（置死分支 ⇒ `test_f53…skips…` 红 / 逐字节还原 sha 一致 / 24 绿）→ 门册 / `DESIGN.md` 登记。
2. 评审事项处置：B-1（收窄节 + D86 注记，§6 表）/ M-1（判据一道覆盖两形态，A-1 增加 file-form 夹具）/ M-2（门册「不查什么」+ 文案 pytest 提示）/ m-1（变异号登记 M76）/ m-2（出路动作词齐组断言）/ m-3（证据路径订正为 `scripts/pkg_digest.py`；计数同批回填 24）/ m-4（零用例取舍进门册「不查什么」，不改判据）——**7+1 条全部采纳**。
3. 场景手工核验：A-1 的形态①（空夹具根）与③（file 形态）即为「存量装配」与「装配损坏」的最小同构；②形态由 issue #17 现场（当刻实测恒红）覆盖。

**回归**（落地后实测）：`pytest tests -q` ⇒ **455 passed, 4 skipped**（落地前基线 **453 passed, 4 skipped**——含批 9818502 之后的 4 个后续 commit 所增用例；本批 +2 新钉，无红）；`scripts/atlas_check.py --fast` 自证 OK；`tests/test_canonical_consistency.py` 9 绿（登记面审计含计数 24 条实收口径与门调度齐查）。

---

## 6. 评审处置（独立审查 1 轮，verdict = 有阻塞问题；1 blocking + 2 major + 4 minor + 1 not-judged 复核段，除 not-judged 外全部采纳，无驳回）

| finding | 级别 | 处置 | 落到 v2 的哪一处 |
|---|---|---|---|
| B-1 D86 ② 在案否决与本案的陈述级冲突未收窄 | blocking | **采纳**（收窄成立条件而非推翻：否决只成立于「出路不可达」；D91 落新行 + D86 行尾收窄注记 + 「根因面不得改靠 SKIP 吸收」单独立句） | §2.2-B-1；`DESIGN.md` D86 ② / D91 ③ |
| M-1 文件形态被「未找到」误陈述（且现行对 file 形态判 `ok` = 假绿） | major | **采纳**（判据「不是目录」一道覆盖两态；文案改「不存在或不是目录」；A-1 增 file-form 夹具；顺带关闭现存假绿边界） | §1.1 表②a；§2.1 条 1；钉 A-1 |
| M-2 出路文案漏 pytest 可用性 | major→minor | **采纳**（SKIP 文案补「需解释器可跑 pytest」；门册「不查什么」列显式登记该盲区） | §2.1 条 1/3 |
| m-1 变异证明未按 M 号惯例登记 | minor | **采纳**（登记 **M76**，门册行回写） | §3.1；gates.md 2.2 |
| m-2 A-1 只断状态不断出路词 | minor | **采纳**（断言 detail 含路径 + `pytest tests` / `install.sh` / `atlas upgrade`，M68 同款纪律） | §3.1 钉 A-1 |
| m-3 计数机审句式 / 证据路径 / 解释器指代三处小误 | minor | **采纳**（计数登记同批回填 24 条 pytest 实收口径；证据路径订正 `scripts/pkg_digest.py`；动机代码注释维持以启动器视角表述） | §1.2；§3；gates.md 2.2 |
| m-4 在场但零用例（`no tests ran` exit 5）取舍未显式留痕 | minor | **采纳**（维持 FAIL 判据不变，取舍进 `gates.md` 2.2「不查什么」列） | §2.1 条 3 |
| （not-judged 复核段）SKIP 语义诚实性 / --fast 交互 / A-2 成本 / 更小实现 / 9818502 其余残余 | — | 评审侧已核实无问题；9818502 对 issue #15/#16/#17 原帖无其他未覆盖残余（仅 M-2 一条顺带计量面） | — |
