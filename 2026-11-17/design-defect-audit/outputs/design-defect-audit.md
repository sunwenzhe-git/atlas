# Atlas 设计缺陷审计

- 审计对象：`main` @ `dd80869`（v0.3.0-beta.2，2026-11-15）
- 审计日期：2026-11-17
- 性质：**只读设计审计**。未改代码、未提交、未推送、未安装依赖、未动 `docs/map` 与计数锚。
- 范围说明：本报告只回答「atlas 自身有哪些设计缺陷」。不评估作为输入的那 10 段提示词本身的质量，也不给出多版方案（第 1、2 段在此不适用）。

---

## 0. 一页结论

这里说的「六套账本」= `shared/gates.md`（门册与计数）、`DESIGN.md` §12（决策）、`CHANGELOG.md`、`docs/guide/changelog.md`、`docs/map/`（8 文件 + HTML 交互图）、`duty-review/`（bugs / QUEUE / README）。

这个仓库最贵的环节不是写代码，而是**让这六套账本互相承认**。近 30 天 fix 类提交触达最多的 **9 个文件全是账本或契约正文**（`shared/gates.md` 49 次、`docs/map/atlas-map.html` 35 次、`DESIGN.md` 34 次、`CHANGELOG.md` 33 次、`docs/guide/changelog.md` 30 次、`docs/map/index.md` 22 次、`rings/e2e/reference.md` 19 次、`QUEUE.md` 17 次、`bugs.md` 16 次），第一个代码文件排第 10（`tests/test_validators.py` 15 次）。两次 beta 发布各自紧跟一次「发版门清障」提交，内容全是计数与基线。

最该动的 5 件事，按影响面排序：

| # | 该动什么 | 现在在付什么成本 | 最小动作 |
|---|---|---|---|
| 1 | **把「派生账本」改成生成物**：`gates.md`/`DESIGN.md`/双 changelog/`docs/map` 里的手抄数字与状态 | 46 次计数/基线类提交；发版门失败主要是账不平而非代码错 | 先只做一件事：把「测试文件数 / 校验器数 / 自检声明数 / 最大单件」四类数字收进一个机器生成的快照段，正文改成引用 |
| 2 | **给账本漂移一条 ≤60s 的提交前快车道** | 漂移只能在发版日的 535s 全量门里被发现，随后补一个「清障」提交并重跑 | 新增一个只跑 canonical 一致性 + map 锚 + 快照对账的 `--preflight` 目标，挂到批次收口而非发版 |
| 3 | **修正内核分层**：`_support` 不得依赖 `validators` | 依赖环靠惰性加载绕开；同一套 git/semver 有 2–6 份实现，修一份漏一份 | 把 E2E 索引解析从 validator 抽到 `_support`；`semver`/`_git` 收敛为单源 |
| 4 | **拆 `_support/solution.py`（3,997 行）** | 10 个分节混在一个文件，14 天改动 4,449 行；并行会话必冲突 | 按现有 `# ---` 分节切成 4–6 个模块，不改行为 |
| 5 | **给决策/观察台账一个「现行视图」** | 211 条决策行 + 约 20 条作废声明；新人要读完整史才知道现在算数的是什么 | 生成一张「现行决策表」（未作废行 + 一句结论），历史表保留 |

一条贯穿性判断：这五件事的共性是 **把「已经算得出来的东西」又手写了一遍**。不是纪律不严，恰恰是纪律太严、但落点选在了人手上。

---

## 1. 数据面核实（第 9 段：PR 太慢？）

**如实说明：本仓没有可分析的 PR 数据。** 证据：

- `gh` 未安装，仓库无 PR refs；`git log --merges` 只有 3 条，均为远端同步合并，不是评审合并。
- [QUEUE.md](file:///Users/sunwenzhe/Desktop/atlas/duty-review/QUEUE.md) 机器状态行明写「issue 通道停用（以批语落点为准）」。
- 实际模式是「本地会话 + 直接提交 main」：475 提交 / 72 标签，近 30 天 52 个标签。

因此改用等价证据，结论如下：

| 等价指标 | 实测 | 判定 |
|---|---|---|
| 全量出厂测试耗时 | 535s（静默）/ 681s（单并行会话）/ 发版日推算 ~1600s（仓内实测记录，非本次复跑） | **这是最慢的一环**，900s 预算曾两次撞顶（issue #63）——[atlas_check.py:68-73](file:///Users/sunwenzhe/Desktop/atlas/scripts/atlas_check.py#L68-L73) |
| 发版链路耗时 | 52 标签 / 30 天；每次发版前跑 canonical + 全量 pytest（[release.py:307-321](file:///Users/sunwenzhe/Desktop/atlas/scripts/release.py#L307-L321)） | 发版本身不慢，**慢在发版失败后的返工** |
| 发版门返工 | 3 天内 3 次「发版门清障」：`bf0e297`、`65eee1d`、`efb83c1` | 见 §3 F1 |
| 提交级验证 | CI 只跑 2 个测试文件（[tests.yml:30-33](file:///Users/sunwenzhe/Desktop/atlas/.github/workflows/tests.yml#L30-L33)），82 个测试文件里 80 个只在本地发版时跑 | 见 §3 F2 |

所以第 9 段的问题在本仓要改写为：**「最慢的不是某个 PR，而是从改动到被验证的这条路」**，且这条路上耗时最多的是账本对账，不是用例执行。

---

## 2. 审计方法

- **主力**：第 7 段（历史演变）、第 8 段（新人认知成本）、第 10 段（返工共性根因）。
- **结论层**：每条发现都要过第 3、4、6 段三问——「这是症状还是原因」「二阶影响是什么」「最强反对能不能推翻它」。三问写在每条发现内。
- **第 5 段**：只列真正能给出更优解的类比，见 §5。
- **第 1、2 段**：不适用。这是审计，不是修 bug，也不向用户反问。
- 判定四分类：**有意设计**（附当时理由）/ **历史遗留** / **可安全移除** / **不确定**（不猜）。

---

## 3. 发现清单（按影响面排序）

### F1. 六套账本 + 手抄派生数字，已成为返工主战场

**结论**：仓库把「可以算出来的事实」手写进了多处正文，并给每处配了一道人肉对账。结果是每次功能落地都要额外付一次「账平税」，且发版门失败的主要形态是账不平。

**证据**

| 事实 | 位置 |
|---|---|
| 近 30 天 fix 提交触达 Top9 全是账本/契约正文，第一个代码文件排第 10 | 见 `work/metrics.md` §4；原始命令已留档 |
| 两次 beta 发布各跟一次「清障」，内容只有计数/基线 | `bf0e297`（`shared/gates.md` 1 行 + 2 个测试基线）、`65eee1d`（`gates.md` 4 行 + duty 基线） |
| 计数/锚/基线类提交 46 次 | `git log --pretty=format:'%s' \| grep -cE '计数\|锚\|基线\|刷新\|回正\|门清障\|golden\|回长'` |
| `docs/map` 相关提交 112 次（占全部 475 的 23.6%） | `git log --oneline -- docs/map \| wc -l` |
| 刷新器只覆盖 `docs/map`，明示不碰 `gates.md` 与 canonical 计数 | [refresh_count_anchors.py:13-16](file:///Users/sunwenzhe/Desktop/atlas/tests/refresh_count_anchors.py#L13-L16)、[:210-217](file:///Users/sunwenzhe/Desktop/atlas/tests/refresh_count_anchors.py#L210-L217) |
| canonical 计数门自认是「固定句式白名单」，漏形态就静默放过 | [test_canonical_consistency.py:420-433](file:///Users/sunwenzhe/Desktop/atlas/tests/test_canonical_consistency.py#L420-L433) |
| 决策记录 211 行、`docs/map` 8 个文件、CHANGELOG 两份 | [DESIGN.md:458](file:///Users/sunwenzhe/Desktop/atlas/DESIGN.md#L458)；`docs/map/*.md` |

**判定**：**真缺陷（设计层，非风格）**。计数门本身是有意设计（`3509 §B105` 的教训是「写死计数无对账」，[test_canonical_consistency.py:222-226](file:///Users/sunwenzhe/Desktop/atlas/tests/test_canonical_consistency.py#L222-L226)）。缺陷不在「设门」，在于**派生数据被反规范化到 4–6 处正文**，每处都要人肉同步。

**三问**

- *症状还是原因？* 「计数写错」是症状。根因是派生数据没有唯一生成点；对账门只能证明「你抄的数字和现在一样」，证明不了「这条数字守住了什么」。
- *二阶影响？* ① 门失败形态被账本噪声淹没，真红与假红难分；② 白名单式判据会随写法演化静默漏检；③ 开发者为让门变绿而改数字，而不是改行为——这是「红灯训练成噪声」的另一种形态。
- *最强反对？* 「计数是防漂移的探针，删了就没人发现少了测试」。反对成立一半：**计数确实抓到过真问题**（2026-09-28 审计拒收就是靠计数不一致发现的）。但「抓到了」的价值来自**对账动作**，不来自**数字本身**。把数字换成机器生成的快照（内容摘要 + 文件清单），同样能抓，且不需要人手抄。

**最小动作**：新增一个 `snapshot.json`（测试文件数、校验器清单、自检声明数、最大单件、共享契约数），由脚本生成；`docs/map` 与 `gates.md` 的相应行改成「见 snapshot」。**先只迁四类数字**，不要把 211 条决策一起迁。

---

### F2. 只有「发版门」，没有「批次门」：D100 接受的风险已经兑现

**结论**：`D100` 当初明确接受「跳过验证直接提交」的窗口风险，前提是「CI 一起落」。半年后 CI 仍只跑 2 个测试文件，而账本漂移的发现点被推到了发版日。

**证据**

- `D100` 原文：「pre-commit 不上；启用留待 CI 一起落」「维护者明示接受该风险」——[DESIGN.md:569](file:///Users/sunwenzhe/Desktop/atlas/DESIGN.md#L569)。
- CI 实际只跑 `test_cli_commands.py` + `test_project_wiring.py`；注释自认「出厂全量门禁仍以本地为准」——[tests.yml:30-33](file:///Users/sunwenzhe/Desktop/atlas/.github/workflows/tests.yml#L30-L33)、[:88-92](file:///Users/sunwenzhe/Desktop/atlas/.github/workflows/tests.yml#L88-L92)。
- 唯一强制点是 `release.py` 的 canonical + 全量 pytest——[release.py:307-321](file:///Users/sunwenzhe/Desktop/atlas/scripts/release.py#L307-L321)。
- `.git/hooks` 只有 sample，无常驻钩子。
- 后果实证：`bf0e297`/`65eee1d`/`efb83c1` 三次清障都发生在发版动作里；issue #63 记录「即使时间无限门也过不去」（[bugs.md:53](file:///Users/sunwenzhe/Desktop/atlas/duty-review/bugs.md#L53)）。

**判定**：**有意设计，但前提已失效**。D100 判断的是 2026-10-17 的规模（当时约百次提交、单人节奏）；现在是 475 提交 / 30 天 52 标签。决策没有被重新评估，风险从「理论存在」变成「每周兑现」。

**三问**

- *症状还是原因？* 「发版日忙」是症状。原因是**验证频率低于改动频率**，且验证内容里混入了大量本可前置的账本检查。
- *二阶影响？* 每次发版多 1–2 个清障提交 → 历史里混入无意义提交 → 回溯「哪个改动引入了问题」更难 → 下一次更不敢动。
- *最强反对？* 「CI 跑全量要钱/要时间，单人项目不划算」。成立，所以动作不应是「把 535s 搬进 CI」。动作是**分级**：60s 的快车道只跑确定性强、无外部依赖的检查（canonical 一致性、map 锚、快照对账、schema 校验），全量仍留在发版。

**最小动作**：加一个 `--preflight` 入口（复用现有测试文件，不新写判据），在每批收口时跑，目标 p95 ≤ 60s。验收判据：连续 5 个批次在发版前零账本类红。

---

### F3. 内核分层倒置：`_support` 依赖 `validators`，环靠惰性加载绕开

**结论**：共享内核（`_support/`）反过来依赖校验器（`validators/`），形成 `solution → solution_e2e → validate_e2e_index → solution` 的环；环不是被设计消除的，而是被「运行时再 import」掩盖的。同时，单源纪律在本层有 3 套加载器、2 份 semver、6 份 `_git`。

**证据**

| 事实 | 位置 |
|---|---|
| 内核 import 校验器 | [_support/solution_e2e.py:67](file:///Users/sunwenzhe/Desktop/atlas/_support/solution_e2e.py#L67) `load_module("validate_e2e_index")` |
| 校验器 import 内核 | [validators/validate_e2e_index.py:736](file:///Users/sunwenzhe/Desktop/atlas/validators/validate_e2e_index.py#L736) `load_module("solution").load_manifest` |
| 内核回指内核（惰性） | [_support/solution.py:3334](file:///Users/sunwenzhe/Desktop/atlas/_support/solution.py#L3334)、[:3654](file:///Users/sunwenzhe/Desktop/atlas/_support/solution.py#L3654) |
| 为避环而写的注释 | [_support/solution_seal.py:5-6](file:///Users/sunwenzhe/Desktop/atlas/_support/solution_seal.py#L5-L6)、[_support/solution_task.py:9](file:///Users/sunwenzhe/Desktop/atlas/_support/solution_task.py#L9) |
| 加载器三套 | [siblings.py:23](file:///Users/sunwenzhe/Desktop/atlas/_support/siblings.py#L23)、[solution.py:70](file:///Users/sunwenzhe/Desktop/atlas/_support/solution.py#L70)、[atlas_solution.py:25](file:///Users/sunwenzhe/Desktop/atlas/scripts/atlas_solution.py#L25)（后者不进 `sys.modules` 缓存） |
| 单源守卫只盯 11 个函数名 | [test_shared_kernel.py:228-240](file:///Users/sunwenzhe/Desktop/atlas/tests/test_shared_kernel.py#L228-L240) |
| 守卫未覆盖的重名 | `_git` ×6（含内核两份）、`semver_lt` ×2、`split_row` ×2、`read_origin` ×2、`tid_owner` ×2、`normalize_mock_prefixes` ×2 |

**两份 semver 语义不同**（这是正确性风险，不只是重复）：

- 内核版：不可解析 ⇒ `False`——[_support/solution.py:126-134](file:///Users/sunwenzhe/Desktop/atlas/_support/solution.py#L126-L134)
- CLI 版：不可解析 ⇒ **退回字符串比较**——[scripts/atlas_solution.py:219-226](file:///Users/sunwenzhe/Desktop/atlas/scripts/atlas_solution.py#L219-L226)

同一个版本字符串在两处可能得到相反结论。当前只影响 `--allow-dangling-acs` 的注册窗口，但这是「两处各写一套 ⇒ 判据分叉」的教科书形态——正是该项目自己在 [test_shared_kernel.py:222-226](file:///Users/sunwenzhe/Desktop/atlas/tests/test_shared_kernel.py#L222-L226) 写下的根因（B197-1：双端同错 ⇒ 门恒绿）。

**判定**：**真缺陷**。分层倒置与加载器分叉都是增量堆叠的结果，不是有意设计；注释只解释了「为什么现在能跑」，没有解释「为什么这样是对的」。

**三问**

- *症状还是原因？* 「循环 import 报错」是症状；原因是 E2E 索引解析这段逻辑归属错了——它既被 validator 用，也被内核用，于是落在 validator 里，内核只能反向依赖。
- *二阶影响？* ① 任何 import 顺序变化都可能改变行为；② 单元测试只能通过 `load_module` 这种字符串寻址，重构无法被静态工具覆盖；③ 修一份实现漏另一份，且守卫不覆盖——这类问题会以「某个入口行为不同」的形式在真跑时才暴露。
- *最强反对？* 「惰性加载是 Python 里处理环的常规手段，重复的 `_git` 只有几行」。前半成立但本末倒置：常规手段是为了保住分层，这里是为了保住不分层。后半不成立——`_git` 的六份实现里，超时、二进制开关、错误码约定已经不同（`solution.py` 返回三元组、`solution_seal.py` 用 `-C` + 可选 binary）。

**最小动作**：把 `validate_e2e_index` 里被内核消费的解析函数（`parse_block` 之外的表格/维度解析）迁到 `_support/e2e_index_core.py`；`semver` 收敛为内核一份；`_git` 收敛为 `_support/gitcmd.py`。守卫从「函数名白名单」改成「按模块声明允许的导入边」，否则新增重复仍然逃逸。

---

### F4. `_support/solution.py`：3,997 行、10 个分节、14 天改动 4,449 行

**结论**：全仓最核心的内核文件是一个单体。它同时承担清单解析、git 探测、契约锁、定义源校验、初始化/迁移、历史链重建、crosswalk、AC 修复、封条写侧与渲染。

**证据**

- 分节即关注点：[solution.py](file:///Users/sunwenzhe/Desktop/atlas/_support/solution.py) 内 10 个 `# ---` 分节，从 `manifest`（:102）到「封条写侧」（:3799）。
- 体量：3,997 行 / 183 KB；配套 `solution_seal.py` 1,822 行。
- 改动强度：近两周该文件 diff 合计 4,449 行（`git log --numstat`，见 `work/metrics.md`）。
- 消费者 7 处：`solution_e2e`、`solution_task`、`atlas_apply_seal`、`validate_ac_alignment`、`validate_apply_record`、`validate_e2e_index`，以及测试。
- 单体直接导致 F3 的绕环写法（同一文件内惰性加载另外三个 solution_* 模块）。

**判定**：**历史遗留**。它不是一次设计出来的分层，而是 A/B/C/D 四批验收资产逐批追加的结果；CHANGELOG 也按批次记录。没有证据表明「必须放一个文件」是有意约束。

**三问**

- *症状还是原因？* 「文件太大」是症状；原因是**没有按变化频率分层**——清单格式与 git 探测几乎不变，锁/封条/追溯链每批都在改，两者却共享一个文件。
- *二阶影响？* ① 并行会话冲突（仓库自己的记忆与 D100 都提到「多会话并行开发」）；② review 面太大，评审只能抽样；③ 新人无法判断改一个字段会波及哪些判据。
- *最强反对？* 「拆了会产生 import ceremony，还可能出现循环」。这正是 F3 要一起解决的：先定分层（解析 / 探测 / 判据 / 写侧 / 渲染），再拆文件，循环自然消失。

**最小动作**：按现有分节切 5 个模块，**不改任何函数体**，只移动与转导出；用现有 1807 条测试保证行为不变。先切「git 探测」与「渲染」这两个低耦合段，风险最小。

---

### F5. 决策与观察台账：只追加、无现行视图

**结论**：`DESIGN.md` §12 是 append-only 决策表（211 行），作废信息以「前言 + 删除线 + 行内注记」三种形态散落；`QUEUE.md` 的观察项也用行内 `【已结】` 标注。历史保住了，**「现在算数的是什么」没有唯一出口**。

**证据**

- 作废前言单段声明约 20 条作废决策（D8、D45–D47、D49–D59、D67 等）——[DESIGN.md:460](file:///Users/sunwenzhe/Desktop/atlas/DESIGN.md#L460)。
- 行内删除线：`D14` 被划掉并指向 `D27`——[DESIGN.md:477](file:///Users/sunwenzhe/Desktop/atlas/DESIGN.md#L477)。
- 行内退役注记：`D42` 的 `tokens` 段「【已退役 2026-09-30】」——[DESIGN.md:505](file:///Users/sunwenzhe/Desktop/atlas/DESIGN.md#L505)。
- 观察台账同类形态：[QUEUE.md](file:///Users/sunwenzhe/Desktop/atlas/duty-review/QUEUE.md) 观察室内多条以「【已结…本行保留作记录】」结尾。
- 反例说明这不是纯风格问题：`D72` 把「CI 分级与回滚」登记为未决，`D100` 又把 pre-commit 留给 CI，两行相隔约 30 行，单独读任一行都会得出错误的现状判断。

**判定**：**有意设计（追溯需求）+ 缺视图（缺陷）**。append-only 是标准 ADR 实践，不该改；缺的是一张生成的「现行决策」表。

**三问**

- *症状还是原因？* 「新人读不懂」是症状；原因是**没有区分「史」与「法」**——同一张表既当档案又当规范。
- *二阶影响？* ① 新会话可能按已作废决策施工（仓库大量依赖「交接提示词」，这个风险是实的）；② 每次决策都要写一段「本行作废了哪几行」，反过来增加写作成本；③ 审查时要跨 200 行做一致性推理。
- *最强反对？* 「历史全留着最安全，删了就丢依据」。不反对保留，反对的是**只有一个视图**。生成一张现行表不影响历史。

**最小动作**：写一个生成器，输出「现行决策表」（未被作废的行 + 一句结论 + 指向原行号），把 `DESIGN.md:460` 的作废前言改成结构化标记（如行尾 `〔作废 by E1〕`），让生成器能识别。不删任何历史。

---

### F6. 双 changelog 手写两份 + guard 落错目录、不随包

**结论**：`CHANGELOG.md` 与 `docs/guide/changelog.md` 不是镜像，是**两份独立撰写**的同一事件记录（163 行差异）。守卫只检查「两边各加了至少一行」，不检查一致性；而且守卫放在 `tests/`，按 RFC 应放 `scripts/` 并随包分发。

**证据**

- 两份 3,223 行，差异 163 行：`diff CHANGELOG.md docs/guide/changelog.md | wc -l`。同一天同一批的条目措辞不同（例：v0.3.0-beta.2 的 E2E 段，一份写三行、另一份写五行并带日期）。
- 守卫判据只有「段内 `+` 行 ≥1」——[tests/changelog_guard.py:2-10](file:///Users/sunwenzhe/Desktop/atlas/tests/changelog_guard.py#L2-L10)、`CHANGELOGS` 常量在 :55。
- 实测 26/30 天会被 would-flag，且仍是 shadow（只报不阻）——[shared/closeout.md:34](file:///Users/sunwenzhe/Desktop/atlas/shared/closeout.md#L34)。
- RFC 写的落点是 `scripts/changelog_guard.py`，并承诺「存量采纳仓 `--update` 后副本获得两脚本」——[RFC-20261114-04:32](file:///Users/sunwenzhe/Desktop/atlas/proposals/RFC-20261114-04-sync-automation.md#L32)、[:60](file:///Users/sunwenzhe/Desktop/atlas/proposals/RFC-20261114-04-sync-automation.md#L60)。
- 实际不在装配面：`install.py` 的 `pkg_dirs` 不含 `tests`（[install.py:568-569](file:///Users/sunwenzhe/Desktop/atlas/install.py#L568-L569)），`package.json` 的 `files` 也不含 `tests`。

**判定**：**真缺陷（契约 ⇄ 实现漂移）**，且是「交付物承诺了但没发出去」这一类。影响面小于 F1–F4，但确定性最高、修起来最便宜。

**三问**

- *症状还是原因？* 「changelog 常缺」是症状；原因是**同一事实有两个人工写入口**，守卫只验「写过」，不验「写对」。
- *二阶影响？* ① 两份长期分叉，读者不知道哪份权威；② shadow 模式意味着它现在对返工零贡献，却已经付了实现与测试成本；③ 承诺给采纳仓的能力没交付，后续 `--enforce` 上线时采纳仓无处可跑。
- *最强反对？* 「两份面向不同读者（开发者 vs 文档站），措辞本来就该不同」。成立——所以修法不是合并成一份，而是**改成一份真相源 + 一处派生渲染**（如 `docs/guide/changelog.md` 由 `CHANGELOG.md` 生成或反之），或明确声明二者独立并以 `CHANGELOG.md` 为权威、另一份只做摘要。

**最小动作**：① 把 `tests/changelog_guard.py` 移到 `scripts/`（同步 `pkg_dirs` 与 `package.json`）；② 在 `shared/closeout.md` 写明哪份是权威；③ 再谈 `--enforce`。

---

### F7. `atlas_check` 无法检查 atlas 自身（自举缺口）

**结论**：9 行编排门里的大部分判据需要被检查仓有 `product/` 资产；源包本身没有，所以这些门在自家仓库恒为 SKIP。atlas 自己的验收实际是直接跑 pytest，编排器从未对本仓完整跑过。

**证据**

- 各门前置：[atlas_check.py:76-110](file:///Users/sunwenzhe/Desktop/atlas/scripts/atlas_check.py#L76-L110)，注释直接写「atlas 自身设计场景（工作区无资产根）⇒ 未走到这一步」。
- 本仓无 `product/`、无 `.trellis/`（`ls` 验证）。
- 观测面证据：`.atlas/runs/check-events.jsonl` 51 条事件**全部 `fast=true`**，最后一条停在 2026-11-05；无一次全量编排记录。
- `tests/test_atlas_check.py` 用假桩验证每一行的判定，但「9 行串起来跑在一个真实仓上」只由 `test_atlas_verify_playground` 覆盖，而 playground 曾因 `beta.35` 排除而「咬合迟到一批」（[bugs.md:53](file:///Users/sunwenzhe/Desktop/atlas/duty-review/bugs.md#L53)）。

**判定**：**有意设计（工具面向采纳仓）+ 真实覆盖盲区**。两者不矛盾：定位可以是这样，但「编排器自身没在真实仓上被持续演练」是缺陷。

**三问**

- *症状还是原因？* 「门在自家不跑」是症状；原因是没有一个**最小真实仓 fixture** 作为常驻演练面，只能靠 playground 偶发跑。
- *二阶影响？* issue #63 的三层根因（测试漏挂 skipif、预算不足、落点漂移）都是「编排器在真实装配态没跑过」的产物；修复又引入新配置（1800s/2400s），下一次改动仍可能撞。
- *最强反对？* 「这是工具，不是产品仓，用 pytest 验收够了」。部分成立；但 `atlas_check` 是交付给用户的主入口，它自己的回归不能只靠假桩。

**判定细化**：这是**中等影响**，且部分落在「不确定」——无法证明「9 行全量在真实采纳仓连续跑绿」的频率，因为仓内没有该数据。

**最小动作**：把 playground 的真跑收敛成一个**常驻最小 fixture**（1 个 app / 1 个页面 / 1 条用例），纳入快车道（若能在 60s 内）或每日巡检，而不是只在发版时跑。

---

### F8. 退役残留：`prototype` 语义仍在生产代码里承担默认值

**结论**：原型环（E1）已退役，但 `prototype` 仍作为**默认来源**参与事件归因，`prototype-pass` 仍是合法状态。

**证据**

- [scripts/e2e_console.py:1446-1448](file:///Users/sunwenzhe/Desktop/atlas/scripts/e2e_console.py#L1446-L1448)：旧事件无 `source` 字段 ⇒ **视为 `prototype`**。
- [_support/solution_e2e.py:448](file:///Users/sunwenzhe/Desktop/atlas/_support/solution_e2e.py#L448)：同样以 `prototype` 作默认来源。
- [validators/validate_e2e_index.py:226](file:///Users/sunwenzhe/Desktop/atlas/validators/validate_e2e_index.py#L226)：`STATES` 仍含 `prototype-pass`。
- [_support/stack_profile.py:22](file:///Users/sunwenzhe/Desktop/atlas/_support/stack_profile.py#L22)：仍解析 `prototype` 段。
- 代码文件中 `prototype` 出现 180 次（含测试，测试占多数；生产侧集中在上述四处）。

**判定**：**历史遗留，但当前是「有意兼容」**。保留理由明确：旧账本要能读（`e2e_console.py:21` 注释）。**可安全移除的部分**：把「缺省来源」从 `prototype` 改成 `unknown`，旧事件按显式白名单兼容；`prototype-pass` 状态可保留但标 `legacy`。**不确定**：是否还有真实采纳仓的旧账本依赖这个默认值——仓内无数据，建议保留一个版本周期。

**三问**

- *症状还是原因？* 「代码里还有 prototype」是症状；真正的问题是**退役没有定义「旧数据的读法」**，于是退役后仍用退役概念做默认值，语义反转。
- *二阶影响？* 新事件若漏写 `source`，会被静默归到已退役的来源，统计口径悄悄错。
- *最强反对？* 「默认值只是为了读旧数据，不影响新数据」。不成立：默认值恰恰作用在「字段缺失」的新数据上，缺失时无法区分新旧。

---

### F9. 摘除 `tests/` 后，采纳仓失去唯一的就地自检

**结论**：`RFC-20261114-01` 把 `tests/` 移出装配面，理由是采纳仓对齐门 9m22s + 7 条与采纳方无关的红。代价是「对齐测试」门在新装配态成为**常驻 SKIP**，采纳仓不再有任何验证工具自身的方式。

**证据**

- `CHANGELOG.md:60`：四表同批摘除，明写「出厂测试回归源包验收面」。
- [gates.md:81](file:///Users/sunwenzhe/Desktop/atlas/shared/gates.md#L81)：该行 SKIP「成为新发行版装配态的最常驻合法态」。
- [tests.yml:30-31](file:///Users/sunwenzhe/Desktop/atlas/.github/workflows/tests.yml#L30-L31)：CI 也不跑全量，等于全链路只有源包本地跑。

**判定**：**有意取舍，但缺少替代**。动机（删掉与采纳方无关的红）是对的；问题是删完之后没有补一个「工具自身冒烟」的轻量替代。

**三问**

- *症状还是原因？* 「门恒红」是症状；原因是那批测试**混装了两种东西**：工具行为测试（与采纳方无关）和装配态测试（必须适配）。正确动作是拆，不是整目录摘。
- *二阶影响？* 采纳仓里工具坏了没人知道；错误只能由用户在使用中撞到，再回到源包修——反馈链变长。
- *最强反对？* 「采纳仓本来就只该跑自己的项目资产，不该跑工具的自测」。成立一半：全量不该跑，但**装配完整性冒烟**（版本戳、MANIFEST 与文件一致、CLI 能起、`--fast` 能出报告）应该保留，且它本来就存在（66 条 `c()` 自检），只是没被组织成一个可跑入口。

**最小动作**：把 install.py 的 66 条 `c()` 自检暴露为 `atlas doctor`（只读、<5s），写进采纳仓的收口清单；不恢复 `tests/` 装配。

---

## 4. 明确排除：这些看起来像缺陷，但不是

审计要区分「真缺陷」与「我不喜欢的风格」。以下候选经核查后**不报**：

| 候选 | 为什么不是缺陷 |
|---|---|
| `PRD_SCHEMA_2_FROM = None` 像「永不触发的门」 | 已有补偿：读者 ≥0.4.0 且未填 ⇒ `prd_schema_gate_unarmed` WARN（[solution.py:3457-3463](file:///Users/sunwenzhe/Desktop/atlas/_support/solution.py#L3457-L3463)），并有发版门测试（`tests/test_release_gate.py`）。这是**有意设计的延迟武装**，且已防死锁。 |
| 生产代码大量 `except Exception: pass` | 抽样 27 处，均为观测面/最佳努力（如事件写入失败不翻红、npm 探测失败回落）。注释逐处写明理由，符合「观测面坏了不能反过来判红」的既定口径。 |
| CI 不跑全量 | `D100` 明示接受 + 全量 535s。问题在「没有快车道」，不在「CI 不跑全量」（已并入 F2）。 |
| `proposals/` 104 份不进包 | `package.json files` 不含 `proposals`，分发面无影响；属研发过程资产。 |
| 计数门存在本身 | 它是**有意设计**且抓到过真问题；缺陷在实现方式（F1）。 |
| `docs/map` 私有（不进站点） | 有意设计，`srcExclude` 已落。 |
| 5,613 行的 `test_validators.py` | 单文件大但按校验器分节、无跨文件状态；属测试组织风格，未观察到返工成本。 |

---

## 5. 跨领域类比（只在能给出更优解时用）

1. **编译器 / 数据库的正常化**（用于 F1）：编译器不会把符号表抄进注释再让测试比对注释；派生数据必须由唯一源头计算。Atlas 现在相当于「符号表手抄三份 + 三份互校」。更优解不是加强互校，而是**只留一份，其余渲染**。
2. **航空检查单**（用于 F2）：检查单的价值在于「在起飞前按固定顺序执行」，不是「落地后回顾」。当前把账本检查放在发版（落地）而不是批次收口（起飞前），等于检查单在降落后才填。
3. **操作系统内核 / 驱动分层**（用于 F3）：内核不 import 驱动。这里 `_support` import `validators` 就是内核 import 驱动；靠「运行时再加载」维持可运行，等于用动态链接绕开分层，问题会以「某个加载顺序下行为不同」的形式回来。

第 5 段其他类比（如协议规范、财务审计）没有给出比上述三条更具体的动作，故不展开。

---

## 6. 建议的执行顺序（不含代码改动）

1. **F1 的四类数字**（1 个生成器 + 4 处引用）——收益最大、风险最低、不触碰判据。
2. **F2 的 `--preflight`**（复用现有测试，只加入口）——让 F1 的收益不被发版噪声吃掉。
3. **F6 的 guard 移位 + 权威声明**（纯搬迁 + 一行文档）——顺手清掉一个已承诺未交付项。
4. **F3 的分层修正**（先抽 `e2e_index_core`，再收 `semver` / `_git`）。
5. **F4 的拆分**（按分节切，行为不变）——建议在 F3 之后做，否则会带着环拆。
6. **F5 的现行视图**（生成器，不删史）。
7. F7 / F8 / F9 作为观察项，先补数据再决定是否动。

验收判据（可在不动代码的前提下先观测）：连续 5 个批次无「计数/基线/锚」类 fix 提交；发版前 preflight 零红；`git log --numstat` 中账本文件不再进入 fix 提交 Top10。

---

## 附录：证据复现

所有命令与原始数字见 [work/metrics.md](file:///Users/sunwenzhe/Desktop/atlas/2026-11-17/design-defect-audit/work/metrics.md)。关键命令：

```bash
# 返工热点
git log --since='2026-10-18' --grep='fix|修' -i --name-only --pretty=format: \
  | grep -v '^$' | sort | uniq -c | sort -rn | head -20

# 计数/锚/基线类提交数
git log --pretty=format:'%s' | grep -cE '计数|锚|基线|刷新|回正|门清障|golden|回长'

# docs/map 提交占比
git log --oneline -- docs/map | wc -l

# 两份 changelog 差异
diff CHANGELOG.md docs/guide/changelog.md | wc -l

# 用例规模（只收集，不执行）
python3 -m pytest tests/ --collect-only -q | tail -1
```

只读声明：以上均为无副作用命令；未执行测试套件，未启动浏览器，未修改任何被审文件。
