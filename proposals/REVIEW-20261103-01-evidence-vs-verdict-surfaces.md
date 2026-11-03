# REVIEW-20261103-01：证据面 ⇄ 判分面（RFC-20261103-02）

- **被审对象**：`proposals/RFC-20261103-02-evidence-vs-verdict-surfaces.md` + 本批四文件未提交改动（`shared/global-rules.md` §17、`rings/e2e/reference.md` §7.1「运行目录二分」表、`shared/single-source.md` §1 登记行、`proposals/BACKLOG-execution-layer.md` §5 bullet）
- **评审方式**：独立只读子 agent（活仓零写入；变异实验在 `/tmp` 副本进行；2026-11-03）。README §3 口径执行：所有结论附评审者本人重跑的原始命令与输出，不引作者 §4.5。
- **总判定**：**accept with changes**（四件契约文本可收口；RFC 引用一处断链必修；另发现一个相邻潜伏缺陷，不阻塞本批但须当日单开登记）

## 结论速览

四文件 diff 逐行核对为纯契约文本、零行为变化；§17 与 e2e 表的清单分工成立；`grep -rn "results.json" rings/ shared/` 恰 1 命中且经变异实验证明断言有牙齿；生成器落点行号、判分读取方行号逐位吻合；§4.5(b) 实测落契约路径族；未新增任何机器门；升格条件可判定。**不能原样收口的原因有二**：① RFC §1.2 把 `.last-run.json` 的归类依据指向「`shared/gates.md` 的 D128 条」——该处不存在此内容（Major-1，一行修复）；② 评审实验发现 `results.json`（本表判分面成员）**并未**被指纹免疫闭集排除，每次真跑后污染 `scripts_hash`（Major-2，先于本批存在，须单开登记另案）。

## Critical（无）

## Major

1. **断链引用：RFC 的 `.last-run.json` 归类依据指向不存在的位置**
   `proposals/RFC-20261103-02-evidence-vs-verdict-surfaces.md:36` 写「归类依据：`shared/gates.md` 的 D128 条把它与 `test-results/`、`trace`、`png` 并列为『运行时产物、不入 `scripts_hash` 指纹』」。实测：
   - `grep -n "last-run\|test-results\|scripts_hash" shared/gates.md` → **零命中**；`shared/gates.md` 里 D128 只在第 71 行被交叉引用（「D127–D128/D174」），无 D128 决策行；
   - 该 D128 条实际在 **`DESIGN.md:597`**，原文枚举为「（`test-results/`、trace、png **等**）」——**未点名 `.last-run.json`**；
   - 真正把 `.last-run.json` 钉进指纹免疫闭集的是机器面：`scripts/e2e_console.py:148` 与 `:183` 的后缀闭集 `(".trace", ".png", ".webm", ".last-run.json")`，及钉 `tests/test_e2e_console.py:874`（写入 `.last-run.json` 后断言 `h2 == h1`）。
   引用措辞（指纹免疫口径）方向是对的，但指针落在不存在的内容上，读者按 RFC 复算会断链。
   **处置**：`:36` 改引 `DESIGN.md:597`（D128）+ `scripts/e2e_console.py:148/183`（指纹免疫闭集，注明该清单是**指纹免疫清单**、非证据/判分归类表）+ `tests/test_e2e_console.py:853`（钉名 `test_scripts_hash_excludes_runtime_artifacts_and_whitelists_scripts`）。仅改 RFC 文本，四件契约不动。

2. **相邻潜伏缺陷（本评审新发现；先于本批存在，非 RFC-02 引入）：`results.json` 污染 `scripts_hash`**
   `scripts/e2e_console.py` 的 `scripts_hash`（`:139-165`）与 `script_file_map`（`:169-190`）同源扫描 `s_dir.rglob("*")`：目录排除族只有 `test-results / playwright-report / .atlas-auth / node_modules`（`:147`，**不含 `.atlas-run`**），后缀排除闭集为 `(".trace", ".png", ".webm", ".last-run.json")`（`:148`）；`results.json` 以 `.json` 结尾命中白名单 `:150` ⇒ **计入指纹**。而真跑后 `product/e2e/scripts/.atlas-run/results.json` 恒存在（`scripts/atlas_check.py:748` 即从该处读取；json reporter `outputFile` 相对 cwd=scripts，D106 口径）。副本实验（`/tmp/exp/fp_experiment.py`，对 `/tmp` 副本加载 `e2e_console`，仿 D128 钉流程）：

   ```text
   h1 (source only)                   = 1b8281eb5fec0bc0
   h2 (after .atlas-run/results.json) = dfdfb3de8d87b866
   results.json pollutes fingerprint: True
   .last-run.json immune             : True
   ```

   影响：跑完任一用例 ⇒ 指纹变 ⇒ 控制台其它已审条目被判 `stale` 需重审（假漂移），正面违反 D128 立条目标「确保执行产物不导致指纹假漂移」（`DESIGN.md:597` ②）；同时说明本 RFC 表中「判分载体」二成员里只有 `.last-run.json` 对指纹不可见，`results.json` 不是——RFC §1.2 的叙事前提只半成立。D128 钉测试未覆盖 `results.json`（`tests/test_e2e_console.py:870-874` 只钉 trace/png/`.last-run.json`）。
   **处置**：不阻塞本批（bug 属 `scripts/` 族，修复 = 闭集补 `.atlas-run/` 目录排除或显式排除 `results.json` + 补钉 + 变异，须走自己的 RFC）。本 RFC 收口同日：在 `duty-review/bugs.md` E2E 段登记观察（带本实验复算命令），并在 `proposals/BACKLOG-execution-layer.md` §5 该 bullet 上补一句「指纹面未免疫（见 REVIEW-20261103-01 Major-2）」。

## Minor

1. **BACKLOG bullet 的升格条件只写了一半**
   `proposals/BACKLOG-execution-layer.md:57`：「升格条件 = 第一个自动改进 / 诊断消费者出现。」——漏了第二触发（「出现第三类载体」）。其余三处（RFC §2.3、`shared/global-rules.md:146`、`rings/e2e/reference.md:527`）均双条件齐全。第三类载体先于消费者出现时，「迁出/保留/双轨」评估可能被漏触发。
   **处置**：该行补「或出现清单外第三类载体」八字。
2. **RFC §2.1.5 断言与自家 BACKLOG bullet 字面冲突**
   `proposals/RFC-20261103-02-...md:62`：「具体文件名只出现在 e2e 环契约的表里」——但本批登记的 `proposals/BACKLOG-execution-layer.md:57` 同样点名 `results.json` / `.last-run.json`。backlog 是登记非清单正文、不构成 single-source §4 的「两处正文」漂移，但字面与断言不符。
   **处置**：RFC 该句收窄为「契约面（`shared/` + `rings/`）内只出现在 e2e 环契约的表里」，或 BACKLOG bullet 去文件名改指「§7.1 二分表判分面」。
3. **并行窗口 hunk 归属**：`git diff HEAD -- shared/global-rules.md` 含两个 hunk，其中 §13「门登记表同口径（`RFC-20261103-03`）」属并行会话，非本批。RFC-02 提交时必须按 hunk 归属拆分，不得把 RFC-03 行带进本批 commit（其余三文件 diff 各只有本批一个 hunk，干净）。
4. **历史引用行号漂移**：`REVIEW-20261030-01` 引的 `scripts/closeout_derive.py:71/74`，现「校验器」族在 `:71`、「契约」族在 `:84`（族内容未变）。历史文件按 git 历史理解，不追溯改。另 RFC §3 的 checkbox 尚为 `- [ ]`，收口时补勾。

## 复核记录（评审者本人重跑，2026-11-03）

**① 通则与清单分工**

```
$ grep -n "^#\{2,3\} " rings/e2e/reference.md | grep "7\."
489:### 7.1 生成器契约（`scripts/gen_e2e_scripts.py`，D68）
# 二分表在 :520-527，确在 §7.1 内；single-source 登记行指向正确
$ grep -n "trace\|webm\|last-run\|results" shared/global-rules.md
（无输出，退出码 1）⇒ §17 未复制任何文件名，清单唯一在 e2e 表
```

变异验证（/tmp 副本，向 §17 故意插一行判分清单后复跑 grep）：

```
$ printf '\n  | 判分面（副本变异：故意复制清单） | `results.json`（变异行） |\n' >> shared/global-rules.md
$ grep -rn "results.json" rings/ shared/
rings/e2e/reference.md:525:…
shared/global-rules.md:148:…（变异行）
⇒ 断言有牙齿：两处正文会立刻显形为 2 命中
```

single-source 登记行（`shared/single-source.md:30`）真相源 = `rings/e2e/reference.md` §7.1「运行目录二分」表（实测表确实在 §7.1）、派生视图 = §17 只写通则——指向正确。

**② 表内容 ⇔ 代码事实**

```
$ grep -n "results.json\|outputDir\|last-run" scripts/gen_e2e_scripts.py | head
2336:            "    ['json', { outputFile: '.atlas-run/results.json' }],\n"
2338:            "  outputDir: '.atlas-run',\n"
2372:            "    ['json', { outputFile: '.atlas-run/results.json' }],\n"
2374:            "  outputDir: '.atlas-run',\n"
# 与 RFC §1.2 引的 2336/2338/2372/2374 逐位一致（两轨 reporter 全貌：['list'] + ['json']）

$ grep -n "last-run" scripts/e2e_console.py | head
148:        if rel.endswith((".trace", ".png", ".webm", ".last-run.json")):
183:        if rel.endswith((".trace", ".png", ".webm", ".last-run.json")):
# 后缀闭集确为指纹免疫清单（scripts_hash :148 / script_file_map :183），RFC 未将其误作归类表——口径成立；
# 但 RFC 替代引用（gates.md D128）断链，见 Major-1

$ sed -n '748p' scripts/atlas_check.py
    results_json = scripts / ".atlas-run" / "results.json"      # :748 精确
$ sed -n '161p' scripts/atlas_verify.py
    rf = run_dir / "results.json"                               # :161 精确；解析闭集 {expected, flaky, unexpected, skipped}（:177）
```

`.last-run.json` 归判分面的机器依据可查但位置与 RFC 所写不符：钉 = `tests/test_e2e_console.py:853`（`:874` 写入 `.last-run.json` 后 `assert h2 == h1`），决策原文 = `DESIGN.md:597`（D128）。

**③ grep 断言复跑（活仓）**

```
$ grep -rn "results.json" rings/ shared/
rings/e2e/reference.md:525:  | 判分面 | `results.json`（运行器 JSON 报告，含 `status` / `expected`）、`.last-run.json`（上次运行状态） |
exit=0，恰 1 处正文，符合预期
```

**④ 零行为变化核对**

```
$ git diff HEAD -- shared/global-rules.md rings/e2e/reference.md shared/single-source.md proposals/BACKLOG-execution-layer.md
# 四文件各 hunk 均为纯 markdown 契约文本；无代码/判据/退出码改动
# 注意：global-rules.md 的 diff 含第二个 hunk（:111「门登记表同口径（RFC-20261103-03）」），
# 属并行会话，非本批——提交时按 hunk 拆分（Minor-3）
```

**⑤ §4.5(b) 触发面核对（补原始输出）**

```
$ git diff --name-only HEAD -- shared/global-rules.md rings/e2e/reference.md shared/single-source.md proposals/BACKLOG-execution-layer.md
proposals/BACKLOG-execution-layer.md
rings/e2e/reference.md
shared/global-rules.md
shared/single-source.md
exit=0
$ python3 scripts/closeout_derive.py --diff-base HEAD
本清单不含语义触发行，正文自查
本轮改动 10 个文件（atlas 自有对账面 5 个；业务面 5 个，只计条数）
[自动] 步骤 1 —— 触发：任一工作单元收尾；改契约 / 模板 / 校验器 / 脚本 / skill 瘦桩；…
[自动] 步骤 2 —— 触发：改契约 / 模板 / 校验器 / 脚本 / skill 瘦桩（判据指针：closeout.md §2 步骤 2）
[人工] 步骤 3 —— 触发：改动触及核心业务链路 / 权限 / CI / 依赖 / 契约（判据指针：closeout.md §2 步骤 3）
[人工] 步骤 5 —— 触发：改契约 / 模板 / 校验器 / 脚本 / skill 瘦桩（判据指针：closeout.md §2 步骤 5）
[人工] 步骤 7 —— 触发：改契约 / 模板 / 校验器 / 脚本 / skill 瘦桩（判据指针：closeout.md §2 步骤 7）
exit=0
```

结论：`shared/global-rules.md`、`shared/single-source.md`、`rings/e2e/reference.md` 落在「契约」路径族（`scripts/closeout_derive.py:84` = `("契约", ("shared/", "rings/", "apply/", "atlas.config.yaml"))`）⇒ 触发收口步骤 1/2/3/5/7，与派生器输出一致；`proposals/` 不在路径族。**落在 DR4 触发面（契约族）**，收口必跑，§4.5(b) 的预填结论（预期路径四条）实测吻合。步骤族里无校验器/脚本族 ⇒ 与「零代码改动」自洽。

**⑥ 响亮原则与升格条件**

```
$ grep -n "RFC-20261103-02" shared/gates.md
（无输出，退出码 1）⇒ gates.md 未新增本批门行；§17 自declare「纪律面，无机器门」
$ head -3 tests/test_gate_registry.py
"""门登记表形态门（`RFC-20261103-03`；三钉 + 唯一性）。… ⇒ 新增测试属 RFC-03，与本批无关
```

升格条件双触发（第一个自动消费者 / 第三类载体）均为存在性判断、对照二分表可机械判定 ⇒ **可判定成立**。RFC §2.2 引用的元规则锚点亦核实：响亮原则 = `shared/gates.md:7`（元规则第 3 条）、`先量再动手` = `shared/global-rules.md:98`（§12）、D108 = `DESIGN.md:577`。

**⑦ 外部参照抽查（GitHub raw，main 分支当日 HEAD）**

```
$ curl -s raw.githubusercontent.com/google-research/harness2/main/harness2/core/context.py | sed -n '351,361p'
_WITHHELD_NOTE = (
    "CONTENTS ARE WITHHELD ON THIS PATH, DELIBERATELY. … the extracted-deliverable tree lives inside the same trial directory as
    the grader's own output, so serving file bodies here once served the grader's pass rate and failed-check names along with them. …"
# 命中：正是「交付物树与判分输出同目录」事故原文（注：包路径实为 harness2/core/…，仓库根还有一层 harness2/）

$ sed -n '119,127p' /tmp/h2_spec.py     # core/spec.py
        for bad in ("benchmark", "evaluation", "grader", "rubric", "score"):
            … must describe the WORK, not its measurement …    # 命中：措辞层拒收判分词汇
$ sed -n '177,187p' /tmp/h2_spec.py
class RunView:
    """What the method knows about one finished rollout. Never carries a score."""   # 命中：运行视图永不携带分数
$ sed -n '106,123p' /tmp/h2_library.py  # core/library.py
        The tree is checked for grader verdicts before anything is written.
        …
        context.assert_tree_has_no_grader_verdicts(harness)
        context.assert_tree_has_no_grader_verdicts({"EXPERIENCE.md": …})               # 命中：写入前两处校验
```

四处外部行号**全部命中原文**。备注：RFC 引用路径写 `core/…`，实际仓库布局为 `harness2/core/…`，建议引用时补全前缀。

**⑧ 套件与自检（/tmp 冻结副本）**

```
$ python3 -m pytest tests/ -q        # 副本 = 拷贝时点工作树冻结快照
1119 passed, 5 skipped in 373.00s    # 0 failed
$ python3 scripts/atlas_check.py --fast   # 副本
OK
exit=0
```

RFC §4 声称 1116 passed / 3 failed（3 个失败归因并行窗口）——总数 1116+3=1119 与我副本的 1119 passed 一致，且冻结快照 **0 failed** ⇒ 「3 failed = 同窗瞬时红、单独复跑转绿」的归因成立。装配声明亦核实：`install.sh:342-349` 对 `shared` 等整目录 `cp -R`，RFC §3「版本装配：无」成立。

## 残留风险

1. 条款无机器面，靠纪律执行（RFC 自declare）：若长期无自动消费者，二分表只是前置文档；升格双条件是唯一唤醒机制，而 BACKLOG bullet 漏写条件 2（Minor-1）会削弱唤醒面。
2. Major-2 的指纹缺陷未修前，每次真跑后控制台已审条目假 `stale` 的体感会持续存在，且它会让「判分面对指纹不可见」这句话在 `results.json` 上不真——登记前请勿在别处引用「判分载体均已指纹免疫」的表述。
3. 并行窗口仍在活跃提交（评审期间观察到对活仓运行的第三方 pytest 进程）；本评审的 grep/diff 结果均以我执行时点的树为准，收口前建议对必查项 ③⑤ 复跑一次。
