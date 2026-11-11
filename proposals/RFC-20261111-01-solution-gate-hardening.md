# RFC-20261111-01：solution check 悬空 AC 门禁（#50）

- 日期：2026-11-11
- 状态：草案 v2（按 2026-11-11 独立评审意见重写；评审通过前不动代码）
- 基线：`e534145`（v0.2.0-beta.33）
- 本轮范围：**只做 #50**。
- 范围外：#52 / #54 / #55 的 apply 记录 schema 另立 `RFC-20261111-02`，只定字段与信任边界，不实现；#51 / #53 仅保留立项判断，不实现。
- 非目标：不改版本号；不改 `apply/reference.md`；不改 Trellis 任务卡模板；不为 #51 / #52 / #53 / #54 / #55 改任何实现。

## 0. 摘要

#50 本轮按「**直接 FAIL**」落地，不再造「默认 WARN + `--strict` FAIL」的子级别。`atlas solution check` 在本条上默认即 FAIL、exit 1；`--strict` 不改变该条级别，只继续管它原有的锁/漂移/dirty 清单。

同时新增两类配套：

1. `--fix-acs`：只做**行级保字节**的清单修复；`_ac_defs` 为空（PRD 缺失 / 路径不匹配 / 零定义）时**拒绝修复并 FAIL**，绝不把全部 AC 判悬空。退出码分工：清单不合法由 schema 拦成 **exit 2**，修复器守卫拒绝与「重跑仍红」是 **exit 1**，只有写回且重跑全绿才 0；唯一 AC 悬空时**拒绝清空**。
2. `--allow-dangling-acs`：只对「PRD 存在且定义非空、但引用悬空」这一类给一版宽限；写死移除版本 `0.3.0`，并在 `QUEUE.md` 落 owner + 期限观察行。**不覆盖** PRD 缺失 / 路径不匹配 / 零定义。

可见性如实写：真实门在**采纳仓 CI** 的 `atlas solution check --strict`；本仓 CI 只跑 `tests/test_cli_commands.py` + `tests/test_project_wiring.py`，#50 目前不进 `atlas_check`。本轮只在 `tests/test_cli_commands.py` 加一条 CLI 级回归，让 Atlas 仓 CI 能看到这行为，但不把该测试冒充成采纳仓的门。

## 1. 现状判据与缺口

### 1.1 代码路径

- [`_support/solution_task.py`](../_support/solution_task.py#L147-L156) `_ac_defs()` 只读 `<assets_root>/prd/solution-prd.md`，只认表格行 `| AC-XXX-NNN |`；文件不存在直接返回空集。
- [`_support/solution_task.py`](../_support/solution_task.py#L337) `ac_missing = [ac for ac in req["acs"] if ac not in defs]`；[`L351-L352`](../_support/solution_task.py#L351-L352) 把它拼成普通 warning 字符串。
- [`_support/solution.py`](../_support/solution.py#L1135-L1141) 对所有 `check_requirements` 的 warning 统一 `add("跨仓任务", "WARN", warning)`，没有按 `strict` 取 `level`。
- [`scripts/atlas_solution.py`](../scripts/atlas_solution.py#L214-L218) 只有 `overall == FAIL` 才 exit 1；因此当前悬空 AC 在默认与 `--strict` 下都 exit 0。
- [`shared/solution.md`](../shared/solution.md#L81) 的 `--strict` 清单不含 AC 定义行；[`shared/gates.md`](../shared/gates.md#L63) 该行写的是「AC 定义行 / 指针 ⇒ WARN」。

### 1.2 关键缺口：`_ac_defs` 空集语义

`_ac_defs()` 在以下情况都返回空集：

1. `solution-prd.md` 不存在；
2. `atlas.config.yaml` 的 `layout.assets_root` 指向的路径与实际 PRD 不匹配；
3. PRD 存在但零 AC 定义（刚 init 的模板骨架）；
4. PRD 的 AC 定义不是表格行（例如 bullet list）。

当前代码会把情况 1–4 全部解释为「所有 `requirements[].acs` 都悬空」。如果直接按 #50 改成 FAIL，会得到「整仓红 + 报错信息全错」；如果按「只对新记录生效」做 marker，又没有写入方，属于自证。

**必须如实写清的能力边界：运行时只有一个 guard，即「`defs` 为空」。** 解析器拿到的就是空集，无法分辨是文件缺失、路径错、零定义还是写法不符；因此 B/C/D 三类在机器眼里**不可区分**，只能共用一个 `AC 定义源不可用` 出口，消息里给出解析路径供人排查，但**路径本身不是区分成因的证据**。

另一个必须写下的推论：`assets_root` 配错、但错路径下恰有一份**非空** PRD 时，`defs` 非空，本条 guard 不会触发，需求会落进 A 类（悬空引用），并且**可以被 `--allow-dangling-acs` 宽限**。这是设计接受的不完美，不假装能识别。

### 1.3 可见性

- **采纳仓 CI 真实入口**：`atlas solution check --strict`（[`shared/solution.md`](../shared/solution.md#L81)、[`docs/guide/changelog.md`](../docs/guide/changelog.md#L54-L57)）。这是 #50 真正的门。
- **本仓 CI**：[`.github/workflows/tests.yml`](../.github/workflows/tests.yml#L33) 只跑 `tests/test_cli_commands.py tests/test_project_wiring.py -q`。
- **`atlas check`**：不跑 `solution check`，`scripts/atlas_check.py` 的 `VALIDATORS` 也不含 `solution_task`；#50 在 `atlas check` 里完全不可见。
- **结论**：#50 的门在采纳仓 CI；本仓 CI 只能加 CLI 级回归，不能声称「本仓 CI 已经在跑这道门」。
- **必须写进契约的一句**：采纳仓不跑 `atlas solution check --strict` 就等于没有这道门。样例逐字位于 [`shared/solution.md:133`](../shared/solution.md#L133)（§5.1 是锁还原，不是这行），这里只是把它显式写成「门要有人跑」：

```yaml
# 采纳仓 CI（示例；样例逐字位于 shared/solution.md:133，锁还原见同文件 §5.1）
- run: atlas solution check --strict
```

  本 RFC **不声称**该样例已接线到任何仓：Atlas 本仓没有采纳仓 CI，采纳仓是否加这条由各仓 owner 决定；没加就没有门，这是运行事实，不是文档措辞问题。

## 2. 改成什么

### 2.1 判据级别

**直接 FAIL**，不是 WARN 子级别。

- `atlas solution check`（无 `--strict`）：该条 FAIL，`overall=FAIL`，exit 1。
- `atlas solution check --strict`：同样 FAIL，exit 1；`--strict` 不再影响该条。
- `--allow-dangling-acs`：仅把「PRD 存在且定义非空、引用悬空」这一类降为 WARN，exit 0；输出必须带「宽限至 0.3.0」。
- `--allow-dangling-acs` **不覆盖** PRD 缺失 / 路径不匹配 / 零定义；这些仍 FAIL。

### 2.2 判据文字与触发条件

判据必须落在 **`_support/solution_task.py` 的共用 helper**（例如 `ac_source_status()`），由 `task_status()`（因而 `atlas solution task status`）与 `check_solution()` 同时调用，**不能只放 `check_solution`**：否则 `check` 报「定义源不可用」而 `task status` 仍报 N 条悬空，两个入口两套语义。

helper 返回结构化三态：`source_unavailable` / `dangling`（带 ac 与 requirement）/ `ok`。两个调用方按各自出口渲染（`check` 出 FAIL 行，`task status` 出同样的 FAIL 语义，`warnings` 数组仍保持字符串形状见 R5）。

按下列互斥分支处理：

| 条件 | 级别 | 文字 |
|---|---|---|
| `defs` 非空，存在 `ac ∉ defs` | **FAIL**（`--allow-dangling-acs` 时 WARN） | `跨仓任务 AC 定义行缺失：requirement=<req.id> ac=<AC-ID>；PRD=<path>` |
| `defs` 为空，且任一 requirement 的 `acs` 非空 | **FAIL**（宽限不适用） | `AC 定义源不可用：<path> 缺失、零定义或路径不匹配；拒绝按悬空处理，请先修 PRD 或 assets_root` |
| `defs` 非空，所有 `acs` 均可解析 | PASS | — |
| `defs` 为空，且所有 requirement 的 `acs` 都为空 | 不触发 #50 | 沿用现有「solution 资产缺失 / 模板骨架」WARN |

要点：

- 空集不再进入 `ac_missing` 循环；先判「定义源可用性」，再判悬空。
- `defs` 的「非空」只代表至少有一行匹配 `| AC-XXX-NNN |`；不代表定义全集正确，但足以避免全量误报。
- 第三条的「不触发 #50」保证刚 init、无 requirements 的骨架不会因 #50 变红。
- 所有消息都带 PRD 的**解析路径**（`root / assets_root / prd / solution-prd.md`），给人工排查用；**不得**把「消息里有路径」写成「能区分 B/C/D 成因」——运行时它们共用一个空集出口（§1.2）。
- `defs` 非空但实际是**另一个目录**的 PRD（`assets_root` 配错且错路径下有非空 PRD）时，本条判为 A 类悬空，**可被宽限**；这是已知盲区，不在本轮修。
- **两通道统一按 AC 粒度（写死，二选一取此）**：helper 的 `dangling` 是**逐 AC 的 finding 列表**；`task_status` 的 `warnings` 也**逐 AC 渲染一条**（数量可能比今天多，但仍是字符串数组，R5 形状不变；这是行为变化，需在 changelog 写明）。不接受「按 requirement 一条、内含 AC 列表」的旧粒度——那会让去重键与 FAIL 对不上。
- **渲染层必须去重**：同一条 finding 现在既会以 FAIL 进入新通道，又会被既有 `warnings` 循环记成 WARN（[`_support/solution.py:1135-1141`](../_support/solution.py#L1135-L1141)）。`check_solution` 在把 helper 结果渲染成 FAIL 后，必须按 `(code, requirement, ac)` 把该条从 WARN 通道剔除，**同一条 #50 finding 只出现一次**。helper 只产结构化结果，去重是渲染层职责。

### 2.3 `--fix-acs`：行级保字节，不做解析后重生成

**硬守卫（任一命中即拒绝修复并 exit 1）：**

- `defs` 为空且任一 `requirements[].acs` 非空；
- `solution-prd.md` 不存在或不在 `assets_root/prd/` 下；
- 清单能加载，但原始文本里无法唯一定位目标 `acs:` 行（同 `- id:` 出现多次、目标行不存在、`acs:` 行与解析结果对不上）；
- 移除悬空 token 会让某条 requirement 的 `acs` 变空（§2.3 末尾的硬守卫）。

清单**加载不了**的形态（flow list / 块列表 / 引号包裹 / 跨行 / AC 文法不符）不在这里判——它们先被 schema 拦成 `SolutionError`（exit 2），修复器不重复拦（见下方退出码口径）。

**写回方式：**

- 读原始文本（`newline=""` 保留换行风格），逐行定位目标 `- id:` 下的 `acs:` 行；
- 只移除悬空 token 及其相邻一个分隔符，保留行尾注释、缩进、其它键顺序、空行、文件末尾换行；
- 写出前做原子 temp + replace；写出后重新读取并逐字节比较：除目标 `acs:` 行外，其它行必须完全一致；否则回滚并报错；
- 不使用 `_manifest_text()`（[`_support/solution.py`](../_support/solution.py#L859-L900) 是解析后重生成，会丢注释、重排键、把 `acs` 归一成逗号串）；
- 不支持的形式只打印人工修改指引，不尝试猜测。

**分隔符口径（明确列出，不留给实现猜）：**

- 支持 `,`（半角逗号）与 `,` 后带空白的形态；`、`（顿号）与 `，`（全角逗号）按**同一 token 分隔语义**处理，二者与半角逗号一样可安全切分。
- 行尾 `#` 注释先剥离再切分，写回时注释原样保留。
- 其它形态（引号包裹、`[A, B]` flow list、块列表、跨行）**在清单加载阶段就按 AC 文法被 schema 拦下**，抛 `SolutionError`、CLI 返 **exit 2**，修复器根本轮不到执行。修复器**不重复**拦这一层；它只拦「清单能加载，但目标行无法唯一定位 / 写回不安全」的形态，并 exit 1。

**退出码口径（两类，不要混用）：**

| 退出码 | 含义 | 触发点 |
|---|---|---|
| `2` | 清单本身不合法（`SolutionError`） | AC 文法 / 结构 / 非单行 `acs:` 等 schema 层拦截 |
| `1` | 清单合法，但修复被拒绝，或修复后重跑仍红 | 修复器守卫（无法唯一定位）、写回后 gate 仍 FAIL |
| `0` | 写回成功且重跑 gate 全绿 | 仅此一种 |

**命令形态：**

- `atlas solution check --fix-acs`：dry-run，只打印将被移除的 `requirement/ac/line`。
- `atlas solution check --fix-acs --apply`：执行行级写回；**写回后重跑一次同一 gate，以重跑结果定退出码**——仍有悬空 / 定义源不可用 ⇒ exit 1 并打印剩余项，不允许「写成功就 exit 0」。
- **硬守卫：拒绝删除最后一个 token。** 判空口径写死：对目标 `acs:` 行先 `strip_inline_comment`，再按 `,` / `、` / `，` 切分并 trim，得到 **token 集**；若「token 集 − removal 集」为空 ⇒ 不写文件、exit 1，输出 `requirement=<id> 唯一 AC 已悬空；拒绝清空。请补 PRD 定义行，或手工删除整条 requirement（工具不代删）`。**不按原始行是否有字符判空**（那会把 `AC-X, # 注释` 之类误判为非空）。
- **一次算完再写**：`removal` 集合先对整个清单算完，再对每条目标行做**一次**写回；不做「逐 token 逐个写」。这样字节比对只有一次，也不会出现半写状态。
- 因此**不存在「删空」路径**：工具既不自动删 requirement，也不会产出空 `acs` 行。
- `--fix-acs` 本身不是门禁；它不能把「定义源不可用」修绿，也不能替代重跑后的判定。

### 2.4 `--allow-dangling-acs` 宽限

- 只对 `defs` 非空、引用悬空这一类生效；输出必须包含：
  `宽限开关已启用：--allow-dangling-acs 将于 0.3.0 移除；owner=@sunwenzhe；期限=2026-12-31`
- 移除版本写死 `0.3.0`；若 0.3.0 未发布，最迟 `2026-12-31` 移除，二者先到为准。
- `duty-review/QUEUE.md` 观察室增加一行：
  `- 观察 #50 宽限移除：owner=@sunwenzhe，期限=2026-12-31，目标版本=0.3.0；到期未移除则按 D156 升级。`
- 宽限是**临时降级**，不是永久豁免；不得在 release note 之外只靠口头记忆。
- **可执行钉（不只靠 QUEUE 文案）**：flag 是否注册由纯函数 `_allow_dangling_acs_enabled(version)` 决定（`< 0.3.0` ⇒ True），测试必须同时含四条断言，缺第 2 条 M6 今天就没有可判红点：
  1. **基线**：当前 `package.json` 版本 `0.2.0-beta.33` < `0.3.0` ⇒ `--allow-dangling-acs` **必须存在**于 `--help` 与 argparse 选项集合（防「提前删了」）；
  2. **合成版本**：直接把 `"0.3.0"` 喂给 `_allow_dangling_acs_enabled` ⇒ 必须 False，且按该版本渲染的 help 不含该 flag（**今天就能判红**，不依赖发版）；
  3. **真实版本**：`package.json` ≥ `0.3.0` ⇒ help 与 argparse 都不得出现该 flag（发版当天自动生效）；
  4. **预发布**：合成版本 `"0.3.0-beta.1"` ⇒ `_allow_dangling_acs_enabled` 必须 True（semver 下 `< 0.3.0`）。
- **两条实现约束（否则上面四条断言做不出来）：**
  1. **parser builder 必须接受版本注入**：形如 `build_parser(version)`，测试直接把合成版本传进去渲染 help / 选项集合；不允许靠 monkeypatch `sys.argv`、改全局变量或写临时 `package.json` 来伪造版本。
  2. **版本比较必须走 semver**：`0.3.0-beta.1` 必须判为 `< 0.3.0`。禁止字符串比较——`"0.3.0-beta.1" >= "0.3.0"` 在字典序下为 True，会让预发布版提前关掉宽限。
- 变异钉 **M6**：把 `_allow_dangling_acs_enabled` 改成恒 True ⇒ 第 2 条今天即刻红；还原后绿。
- 变异钉 **M6b**：把 semver 比较换成字符串比较 ⇒ 合成版本 `"0.3.0-beta.1"` 必须为 True 的断言红。

### 2.5 契约文字

- `shared/solution.md` §3 `--strict` 清单追加：
  「`requirements[].acs` 引用了方案 PRD 中不存在的 AC 定义行 ⇒ **FAIL**（默认与 `--strict` 同级别；`--allow-dangling-acs` 仅对“PRD 定义非空”的悬空引用给一版宽限。PRD 缺失 / 路径不匹配 / 零定义共用一个空集 guard ⇒ **FAIL**，不适用宽限）」
- **同批必须改** [`shared/solution.md:81`](../shared/solution.md#L81) 末尾那句「不改变默认人工检查的 WARN 语义」——它在本条落地后会自相矛盾。改为：
  「除 AC 定义行（默认即 **FAIL**）外，其余默认仍为 WARN。」并在同节补一句「采纳仓不跑 `solution check --strict` 就等于没有这道门（最小 CI 样例见 [`shared/solution.md:133`](../shared/solution.md#L133)）」。
- `shared/gates.md` 第 63 行改为：
  「AC 定义行 ⇒ **FAIL**（默认与 `--strict` 同级别；`--allow-dangling-acs` 仅宽限“定义源可用”的悬空引用；定义源不可用 ⇒ FAIL 且拒绝 `--fix-acs`）；指针 ⇒ WARN」
- `scripts/atlas_solution.py` 的 `--help` 增加 `--fix-acs [--apply]` 与 `--allow-dangling-acs`，并标注移除版本/期限。

## 3. 反面包

### 3.1 新增能力反面包

以下用例全部基于一个**最小合法夹具**：单成员、`atlas.solution.yaml` 可解析、锁/URL/dirty 等既有检查均通过，确保坏输入只会被 #50 的目标判据接住，而不是先被别的检查拦下。

| 编号 | 坏输入 | 目标判据 | 为什么是它接住 |
|---|---|---|---|
| A | PRD 有 `AC-DEMO-001`，清单引用 `AC-DEMO-999` | `AC 定义行缺失` FAIL，exit 1 | 清单/锁/URL 均合法；`defs` 非空，唯一失败点是 `ac ∉ defs` |
| B | `requirements[].acs` 非空，但 `solution-prd.md` 不存在 | `AC 定义源不可用` FAIL，exit 1 | 既有检查只 WARN 资产缺失，不会先 FAIL；新 guard 必须先于 `ac_missing` 命中，且消息不得写成「全部 AC 悬空」 |
| C | `requirements[].acs` 非空，`layout.assets_root` 指向错误目录 | `AC 定义源不可用` FAIL | 与 B 同一 guard；测试只断言「消息带解析路径、且不写成 N 条悬空」，**不**把路径当成区分成因的证据（B/C/D 运行时不可区分） |
| D | PRD 存在但零 AC 定义（模板骨架），且 requirements 有 acs | `AC 定义源不可用` FAIL | 与 B/C 同一 guard；避免把零定义误报成 N 条悬空 |
| E1 | `--fix-acs` 遇清单能加载、但原始文本无法唯一定位目标 `acs:` 行：**同一条 requirement 行内 `acs:` 键重复**，或**不同 member 的同 id 行** | 拒绝修复，**exit 1**，文件字节不变 | 修复器守卫接住：这两形态都能过 `load_manifest`（不会被「requirements 重复（id+member）」拦），故不是 `SolutionError`；证明「不猜、不半写」 |
| F | `--fix-acs --apply` 需删除悬空 token，行尾有注释、其它键有自定义顺序 | 只改目标 `acs:` 行，其它字节不变 | 行级补丁 + 写后逐字节比对；`_manifest_text` 路径不得出现 |
| G | `--allow-dangling-acs` + **A、B、C、D 四份夹具** | A ⇒ WARN + exit 0（输出含 0.3.0/期限）；**B/C/D ⇒ 仍 FAIL + exit 1** | 宽限只接 A 类。B/C/D 必须显式存在于 G 中并断言仍红，否则「宽限误放行 B/C/D」不会被任何用例咬住 |
| H | `acs: AC-DEMO-001、AC-DEMO-999`（顿号），只 999 悬空 | 只删 999，001 保留，其余字节不变 | 分隔符口径显式含 `、` / `，`；不是靠正则碰巧切对 |
| I | 某 requirement 的**唯一** AC 悬空，且该行带行尾注释（`acs: AC-DEMO-999  # 说明`） | **拒绝修复，exit 1**，文件字节不变，消息含「拒绝清空」与手工处置指引 | 修复器硬守卫先于写回；判空按「`strip_inline_comment` + `,`/`、`/`，` 切分后的 token 集」而非原始行字符；不产生空 `acs`，避免重跑在 `load_manifest` 抛 `SolutionError`（exit 2） |
| J | `--fix-acs --apply` 写成功，但清单别处仍有悬空 | **exit 1**（以重跑结果为准） | 退出码来自重跑 gate，不是来自「文件写成功」；这是「写成功≠门变绿」的唯一咬点 |
| K | 同一坏输入分别跑 `atlas solution check` 与 `atlas solution task status` | 两者都给「定义源不可用」语义 | 判据在共用 helper；只有一处实现，不存在两套出口 |

### 3.2 既有行为回归钉（不是新增能力）

- **R1**：`_ac_defs()` 已支持 `| \`AC-DEMO-001\` |`、单元格前后空白；含反引号/空白的合法 PRD 必须 PASS。这是回归钉，不算 #50 新增能力。
- **R2**：合法清单（所有 AC 均在 PRD 定义行）默认与 `--strict` 都 PASS，exit 0。
- **R3**：缺任务 / `solution.md` 缺失 / context 指针缺失仍为 WARN，不因 #50 被升级成 FAIL。
- **R4**：无 requirements 的骨架（`requirements: []`）不触发 #50；既有资产缺失 WARN 保持原级别。
- **R5**：`atlas solution task status` 的 JSON `warnings` 仍是字符串数组；#50 的内部结构化不得破坏该形状。
- **R6（去重钉）**：断言**同一条 #50 finding 只出现一次**，不得同时以 FAIL 与 WARN 两种形态出现。不要求整份报告只有一行——B/D 会带资产缺失 / 模板骨架 WARN，C 会带错路径下多个资产缺失 WARN，这些是既有输出，正确实现下也应存在。夹具必须含**同一 requirement 下两个悬空 AC**，以咬住 AC 粒度（按 requirement 聚合会漏）。
- **R7（既有 schema 行为，不是新增能力）**：flow list / 多行 `acs:` 今天就会被清单 schema 拦成 `SolutionError`、CLI 返 **exit 2**；钉它只为防回退，不把它算成 `--fix-acs` 的新守卫。

### 3.3 变异钉

- M1：把 `AC 定义行缺失` 改回 WARN ⇒ A 红。
- M2：把「定义源不可用」guard 删掉 ⇒ B/C/D 红（会退化成「全部 AC 悬空」或误绿）。
- M3：`--fix-acs` 改用 `_manifest_text()` 重生成 ⇒ F 的「其它字节不变」红。
- M4：`--allow-dangling-acs` 同时放行 B/C/D ⇒ **G 中 B/C/D 的 FAIL 断言**红（G 必须真的构造 B/C/D，只构造 A 的话 M4 是假钉）。
- M5：`--fix-acs` 在**清单能加载、但目标行无法唯一定位**（同 requirement 行内 `acs:` 重复 / 跨 member 同 id）时仍部分写回 ⇒ **E1** 的字节不变断言红。（E2 已归 R7 回归钉，M5 不指向它。）
- M6：把 `_allow_dangling_acs_enabled` 改成恒 True ⇒ §2.4 第 2 条（合成版本 `0.3.0`）**今天**即红；不依赖真实版本 ≥0.3.0。
- M6b：把 semver 比较换成字符串比较 ⇒ §2.4 第 4 条（`0.3.0-beta.1` 必须 True）红；parser builder 若改成读全局版本，第 2/4 条无法注入，一并红。
- M7：`--fix-acs --apply` 改回「写成功即 exit 0」⇒ **J** 红（I 是守卫拒绝写回，不承担这条）。
- M8：分隔符只认半角逗号 ⇒ H 红（顿号/全角形态切不开）。
- M9：把 guard 只留在 `check_solution`、`task_status` 走旧 `ac_missing` ⇒ K 红。
- M10：去掉渲染层去重，**或**把通道退回按 requirement 聚合（旧 `ac_missing` 一条内含 AC 列表）⇒ R6 红（多 AC 夹具下同一 finding 以 FAIL + WARN 两份出现）。

每条变异按四段协议：注入、跑红、还原、逐字节比对复绿。

## 4. 存量影响

### 4.1 A 类：有悬空 AC 的存量仓

- 直接 FAIL，升级当天 `atlas solution check` 与 `--strict` 都红、exit 1。
- 迁移路径：
  1. `atlas solution check --fix-acs` 看清单（不写文件）；
  2. 确认 AC 确实已从 PRD 删除后，`--fix-acs --apply`；
  3. 若某条 requirement 的**唯一** AC 悬空，工具会拒绝清空（§2.3 硬守卫）——此时要么补 PRD 定义行，要么由人手工删除整条 requirement，工具不代删；
  4. 重跑 `atlas solution check`。
- 宽限：`--allow-dangling-acs` 一版，写死 0.3.0 移除 + QUEUE 观察行。宽限只接 A 类。

### 4.2 B 类：solution PRD 尚未写 / 路径不匹配 / 零定义，但清单已有 `acs`

- 这是评审要求补的一类：直接 FAIL，且**不受 `--allow-dangling-acs` 宽限**。
- 为什么必须单列：空 `defs` 会把全部 AC 判悬空；如果只做悬空 FAIL，这类仓会得到「N 条全悬空」的错误报告，且 `--fix-acs` 可能清空全部引用。必须先用「定义源不可用」拦下。
- 机器**不区分** PRD 缺失 / 路径不匹配 / 零定义（§1.2），三者只给同一个 `AC 定义源不可用` 出口；下面分开写的是**人工排查路径**，不是三个判据。
- 迁移路径（全部手工）：
  - PRD 缺失：按 `templates/prd/domain.md` 手工创建 `<assets_root>/prd/solution-prd.md`，并补齐 `AC-SOLUTION-NNN` 定义行。**不提供 `--ensure-prd`**：`_prd_skeletons`（[`_support/solution.py:963`](../_support/solution.py#L963)）已在 `init` 时按模板幂等产出零 AC 骨架，再补一份骨架不会让门变绿；更坏的是 `assets_root` 配错时它会照错路径写文件，把「路径不匹配」伪装成「PRD 已补」。
  - 路径不匹配：先核 `atlas.config.yaml` 的 `layout.assets_root`，修配置或把 PRD 移到解析路径；不要先补 PRD，否则错路径下写出文件会掩盖配置错误。
  - 零定义：把 AC 写成表格行 `| AC-XXX-NNN | 场景 | 回指规则 |`；`_ac_defs()` 不识别 bullet list，这是既有行为，不是本轮新增限制。
- PRD 内容仍由人写；本轮不提供任何自动补 PRD 的命令。
- **已知盲区**：`assets_root` 指向另一个含**非空** PRD 的目录时，`defs` 非空 ⇒ 落入 A 类，还能被 `--allow-dangling-acs` 宽限。机器无法识别这是配置错误，只能靠人看到大量悬空后去核路径。

### 4.3 C 类：骨架 / 无 requirements 的存量仓

- `requirements: []` 或所有 `acs` 为空：不触发 #50；现有「资产缺失 / 模板骨架」WARN 不变。
- 刚 `init` 的骨架默认没有 requirements，因此不会因 #50 整仓红。
- 若 `init` 时显式传了带 `acs` 的 requirements 但 PRD 还是骨架，则落入 B 类，直接红；迁移 = 补 PRD 或先清空 requirements 的 acs（后者需人工确认需求是否真的没有 AC）。

### 4.4 D 类：PRD 有 AC 但写法不是表格

- `_ac_defs()` 只认表格行，bullet list 会被判「零定义」⇒ B 类 FAIL。
- 迁移：改成表格行；这是既有解析口径，不是 #50 新增。若采纳仓大量使用 bullet list，属于另一个 schema 问题，应另立 RFC，不在本轮放宽 `_ac_defs`。

### 4.5 留出验证（D156）

D156 状态：**证据未取**。本轮**不记**「闭族 / 未闭族 / 单案修复（无留出集）」——未闭族的原义是「留出做了但失败」，本轮没有做留出，不能占用该态。

**本轮不在 `duty-review/bugs.md` #50 写 D156 指针行。** 指针行的合法形态是 `- 留出验证：RFC-… / REVIEW-…`（无状态、无日期、无编号），而现在没有 REVIEW 编号，写出来只是半条账。等留出做完、评审给出 REVIEW 编号后，再补这一行。

留出验证至少补齐：

1. **pre-fix 红证**：一个真实采纳仓（非本仓合成夹具）在升级前跑 `atlas solution check`，保存完整输出与 exit code，证明悬空 AC 当前为 WARN/exit 0；
2. **post-fix 绿证**：同一仓升级后跑同一命令，证明 FAIL/exit 1；再跑 `--fix-acs --apply` 后 PASS；
3. **独立留出**：第二个未参与本方案设计的采纳仓快照，或由评审人确认「确无第二仓」；
4. **定义源不可用样本**：至少一个 PRD 缺失/路径不匹配的真实仓，证明 B 类 FAIL 且 `--fix-acs` 拒绝；
5. **宽限样本**：A 类 + `--allow-dangling-acs` 的 WARN/exit 0 与宽限文案。

反面包与本节的关系：

- 新增能力反面包见 §3.1（A–K；E 只留 E1，E2 归 R7），既有行为回归钉见 §3.2（R1–R7），变异钉见 §3.3（M1–M10、M6b）。
- 这些全是**舱内合成夹具**，不是留出证据，不能拿来充本节 1–5。留出必须来自未参与设计的真实仓。

留出验证要专门盯的残留风险：

1. **B/C/D 运行时不可区分**：留出若只造「PRD 缺失」一种样本，只能证明它变红，不能证明路径不匹配 / 零定义也被正确出口覆盖（三者本来就共用同一个空集 guard）。
2. **带连字符的 AC CODE 不被识别**：`_ac_defs` 的域名段是 `[A-Z0-9]+`，`AC-FOO-BAR-001` 这类写法不会被当成定义行 ⇒ 整份 PRD 记为「零定义」⇒ 落 B 类 FAIL。既有解析口径，不在本轮放宽；留出时要确认采纳仓是否存在这种写法。
3. **`--ensure-prd` 已删除**：PRD 缺失只能手工补。若采纳仓预期「命令自动补骨架」，会得到「补了仍不绿」的预期外结果（骨架零 AC）。
4. **`assets_root` 配错且错路径下有非空 PRD**：落 A 类，还能被宽限（§4.2 已知盲区）。

谁能补：

- 采纳仓 owner（用户）提供只读快照与命令输出；
- 实现者只读运行、不改采纳仓；
- 独立评审人确认留出是否独立、是否足以改 D156 状态。

补齐后在本节追加证据编号与 `REVIEW-…` 编号，再在 `bugs.md` #50 补 `- 留出验证：RFC-20261111-01 / REVIEW-…` 指针行；本轮不写、不预设。

## 5. 契约 / 模板 / 落点改动面

| 文件 | 改动 | 说明 |
|---|---|---|
| `shared/solution.md:81` | strict 清单追加 AC 定义行 FAIL + 定义源不可用 FAIL；**同句**把「不改变默认人工检查的 WARN 语义」改为「除 AC 定义行外，其余默认仍 WARN」；同节补「不跑 `--strict` 就等于没有门」+ 最小 CI 样例 | 不改会自相矛盾 |
| `shared/gates.md:63` | 门行判据改为 FAIL；测试条数按实测回填 | 不新增门行 |
| `scripts/atlas_solution.py` | 新增 `--fix-acs [--apply]`、`--allow-dangling-acs`；`--apply` 写后重跑 gate 定退出码；help/usage | 无 `--ensure-prd` |
| `_support/solution_task.py` | 新增共用 helper `ac_source_status()`（`source_unavailable` / `dangling` / `ok`，`dangling` 逐 AC）；`_ac_defs` 空集语义显式化；`task_status` 与 `check_requirements` 都走 helper；warnings 改**逐 AC 一条** | 两个入口同源；`warnings` 仍是字符串数组，条数变化需写进 changelog |
| `_support/solution.py` | `check_solution` 调 helper 渲染 FAIL，不再自己判空集 | 不调用 `_manifest_text` 修复 |
| `tests/test_atlas_solution.py` | A–K（E 只留 E1）、R1–R7、M1–M10 + M6b（含 §2.4 四条版本断言） | 单元/集成 |
| `tests/test_cli_commands.py` | 一条 CLI 级回归：悬空 AC ⇒ exit 1；`--fix-acs` help 可见 | **本仓 CI 唯一可见点**，但不是采纳仓的门 |
| `bin/atlas.js` | help 文案列出 `--fix-acs` / `--allow-dangling-acs` | 命令路由不变，仅帮助；无 `--ensure-prd` |
| `docs/guide/changelog.md` | 先建 `[Unreleased]` 段，再写 #50 条目 | 当前无该段 |
| `shared/gates.md` 行 63 的测试计数 | 按 `tests/test_atlas_solution.py` 实测条数回填 | 不预设数字 |
| `docs/map/gates.md` / `docs/map/cli.md` | #50 不新增门行/命令名；若实现批改了计数或 help 锚，跑 `node docs/map/atlas-map.check.js` | 不制造新锚 |
| `docs/map/apply.md:61` | **不动**；#50 不改 `apply/reference.md`，所以不触发「固定七小节」 | #52/#54/#55 若未来落地，必须在 schema RFC 里同批改 |
| `docs/map/apply.md:16`、`:97` 的 `apply/reference.md(331 行)` | **不动**；`apply/reference.md` 本轮零改动，行数仍为 331 | 任何改 `apply/reference.md` 的批次必须同批改这两处 |
| `duty-review/bugs.md` | #50 `状态 已修·待复验` + 日期；**不写 D156 指针行**；不新增尾缀键 | 见 §6 |
| `tests/test_duty_bug_families.py` | `TODAY` 与 `FROZEN_BASELINE` 日期同步；案数/exact 不变 | 见 §6 |
| `duty-review/QUEUE.md` | 宽限移除观察行 | owner/期限见 §2.4 |

## 6. 冻结基线

### 6.1 `duty-review/bugs.md`

仓内状态闭集是 `开放｜已修·待复验｜已出库`。本批**只能记 `已修·待复验`**：§4.5 只有「证据未取」，没有 pre-fix 红证、没有留出集、也没有 REVIEW，不满足 `已出库`。

- 只改 #50：
  - `状态 开放` → `状态 已修·待复验`；
  - `日期` → `2026-11-11`；
  - `证` 写实现提交 + `tests/test_atlas_solution.py` / `tests/test_cli_commands.py` 用例名。
- **本批不写 D156 指针行**。合法指针形态是 `- 留出验证：RFC-… / REVIEW-…`（无状态、无日期、无编号）；现在没有 `REVIEW-…`，写了就是半条账。等评审给出 REVIEW 编号后再补。
- 不新增 `#NN`；案数上界仍 15。
- D156 / 留出验证只写在 RFC §4.5，**不要新增尾缀字段键**；`duty-review/families.py` 的 `FIELD_KEYS` 是封闭集 `日期/状态/族/证`，新增键会触发「不认识尾缀」WARN。
- 指针行不带日期、不带 `#NN`，避免抬 `last_date` / 改 `count`。
- `已出库` 只在「留出验证补齐 + 评审给出 REVIEW + 复验通过」之后由发版批改为 `已出库`；本 RFC 不预支这一步。

### 6.2 `tests/test_duty_bug_families.py`

当前：

- `TODAY = datetime.date(2026, 11, 8)`
- `FROZEN_BASELINE["自感知上报（§15 缺陷族）"] = (15, "2026-11-08", "升室候选")`
- `exact["自感知上报（§15 缺陷族）"] == 7`
- `exact["E2E（契约用例 / 生成器 / 校验器）"] == 1`

本批预期：

- `TODAY = datetime.date(2026, 11, 11)`；
- `FROZEN_BASELINE["自感知上报（§15 缺陷族）"] = (15, "2026-11-11", "升室候选")`；
- 两处 `exact` 不变（#50 仍带字段，不新增条目）；
- 注释追加：`2026-11-11：#50 改为已修·待复验（仍带字段；案数不变，日期 11-08→11-11；D156 证据未取，不写指针行）`。

若实现中发现必须新增 `#NN`，先停：那会改 `count` 与 `exact`，需同批复核 `duty-review/README.md` §2 钉数与 `shared/gates.md`。

### 6.3 同批

- `bugs.md` 状态、基线日期、`QUEUE.md` 宽限观察行、`changelog.md` `[Unreleased]` 必须同一笔提交。
- 精确 `git add` 指定文件；禁止 `git add -A`、`--amend`、`--no-verify`。

## 7. 实施顺序与分批提交

### 批次 1：共用 guard 与两个入口同源

- 改：`_support/solution_task.py`（新增 `ac_source_status()`，`task_status` / `check_requirements` 都走它）、`_support/solution.py`（`check_solution` 只渲染 helper 结果）、`scripts/atlas_solution.py`（仅 check 路径）、`tests/test_atlas_solution.py`、`tests/test_cli_commands.py`。
- 预期红：A、B、C、D、K、R6；R1–R5、R7 绿。变异钉 **M1 / M2 / M9 / M10** 必须在本批各自可注入并咬红对应用例（M1→A，M2→B/C/D，M9→K，M10→R6），否则批 1 的假绿测试不合格。
- 门：`python3 -m pytest tests/test_atlas_solution.py -q`；`python3 -m pytest tests/test_cli_commands.py -q`。
- 不碰 `--fix-acs` / `--allow-dangling-acs`。

### 批次 2：`--fix-acs` 行级修复

- 改：`scripts/atlas_solution.py`、`_support/solution.py`（行级补丁，不碰 `_manifest_text`）、`tests/test_atlas_solution.py`。
- 预期红：E1、F、H、I、J、M3、M5、M7、M8；A–D/K/R6 已由批次 1 转绿；**R7（schema 拦截 flow list / 多行 ⇒ exit 2）本批预期绿——它是既有行为回归钉，不是本批新实现**。
- 门：`python3 -m pytest tests/test_atlas_solution.py -q`。

### 批次 3：宽限、契约、落点与台账

- 改：`shared/solution.md`（strict 清单 + **:81 同句改写** + 最小 CI 样例）、`shared/gates.md`、`bin/atlas.js` help、`docs/guide/changelog.md`（先建 `[Unreleased]`）、`duty-review/QUEUE.md`、`duty-review/bugs.md`（`已修·待复验`，不写 D156 指针行）、`tests/test_duty_bug_families.py`、`tests/test_atlas_solution.py`（§2.4 版本门）。
- 预期红：G、M4、M6、M6b；基线未同步前 `test_current_real_file_baseline_frozen` 红，同步后绿。
- 门：`python3 -m pytest tests/test_atlas_solution.py tests/test_duty_bug_families.py -q`；`node docs/map/atlas-map.check.js`（若实现批改了 map 锚/计数）。
- 不 push、不发版；版本保持 `0.2.0-beta.33`。

每批一笔提交，精确 `git add`；不跑全量；`tests/test_atlas_verify_playground.py` 与本轮无关，不跑。

## 8. #51 / #53 立项判断（保留，不动实现）

### 8.1 #51 联邦模式成员 AC 与方案 AC 无映射对账

**为什么现在不做：**

- `templates/atlas.solution.yaml` 的 `requirements[].acs` 只绑定方案 PRD 的 AC；成员任务卡没有机器可读的「成员 AC ↔ 方案 AC」字段。
- `RFC-20261108-02` 已明确「不做跨仓 AC crosswalk，另案」；Phase 1 的契约边界就是不做。
- 要做 crosswalk，需要方案 AC 解析、成员任务卡 AC 提取、双向映射字段、覆盖/冲突判据、存量迁移，是一套 schema，不是一条判据。

**重开条件（满足任一）：**

1. 出现至少一个真实联邦方案，需要按方案 AC 计算跨成员覆盖率；
2. 成员任务卡的「关联 AC」稳定到可机器解析，且至少两个仓在用；
3. 用户明确接受在 `atlas.solution.yaml` 增加 `member_acs` 映射并承担存量迁移。

**涉及契约面：** `templates/atlas.solution.yaml` requirements schema；`shared/solution.md` §2/§3；`_support/solution.py` manifest 闭包；`_support/solution_task.py` 的 `_ac_defs` / `check_requirements`；`validators/validate_ac_alignment.py`；`apply/reference.md` §8。

**本轮结论：** 不实现，issue 保持 open。

### 8.2 #53 确认口径缺少证据状态且 AC 无法承载字段契约

**为什么现在不做：**

- 任务卡 Confirmed 口径归 Trellis 模板，Atlas 不拥有；在 Atlas 侧加证据状态只能写进 `templates/prd/domain.md` 的 Assumptions 表，而该表当前四列没有证据等级消费方。
- AC 表当前三列（AC ID / 场景 / 回指规则），要承载字段契约需新增列或新增 AC 种类，会让所有存量 PRD 迁移。
- 没有机器消费方：`validate_prd.py` / `validate_ac_alignment.py` 目前不读证据状态，也没有字段级契约判据；先加字段只会制造「写了但没人查」的假资产。

**重开条件（满足任一）：**

1. 出现真实需求，其字段级预期无法用现有 AC / Assumptions 表达；
2. 用户接受新增「证据状态」列或「字段契约」AC 种类，并承担 `templates/prd/domain.md` + 存量 PRD 迁移；
3. Trellis 任务卡模板提供兼容字段，Atlas 只需读取，不需改模板。

**涉及契约面：** `templates/prd/domain.md:107` AC 表、`:136-141` Assumptions 表；`rings/prd/reference.md:147,192`；`shared/single-source.md`；`apply/reference.md` §4/§8；`validators/validate_prd.py` / `validators/validate_ac_alignment.py`；Trellis 任务卡模板（外部）。

**本轮结论：** 不实现，issue 保持 open。

## 9. 仍需用户拍板

1. **直接 FAIL**：确认 #50 默认即 FAIL、exit 1，不再保留 WARN 默认？这是本轮方案的前提。
2. **B 类是否同批 FAIL**：PRD 缺失 / 路径不匹配 / 零定义 + requirements 有 acs ⇒ `AC 定义源不可用` FAIL，且不受宽限。是否接受？
3. **宽限硬指标**：移除版本 `0.3.0`、最迟 `2026-12-31`、owner `@sunwenzhe`、QUEUE 观察行；是否照此写死？
4. **`--fix-acs` 支持面**：分隔符支持半角逗号 `,`、顿号 `、`、全角逗号 `，`；引号 / flow list / 块列表 / 跨行由清单 schema 拦（exit 2），修复器不重复拦。是否接受该分隔符集？
5. **`--fix-acs` 退出码与守卫**：schema 拦截（flow list / 多行）⇒ exit 2；修复器无法唯一定位 ⇒ exit 1；写回后重跑 gate，仍有悬空 ⇒ exit 1；唯一 AC 悬空 ⇒ 拒绝清空、exit 1。是否确认？
6. **Atlas CI 可见性**：只在 `tests/test_cli_commands.py` 加 CLI 级回归（本仓 CI 可见），不把 `atlas solution check` 接进 `atlas_check`；同时契约明写「采纳仓不跑 `--strict` 就等于没有门」；是否接受？
7. **台账状态**：实现批把 `bugs.md` #50 改为 `已修·待复验`，**不写 D156 指针行**，`已出库` 留给后续发版批；是否确认？
8. **#52/#54/#55 schema RFC**：结论是「先有机器写入方 `atlas apply seal` 才谈实现」，本轮不实现、不作为实现依据；是否接受该前置？
9. **#51/#53**：保持 open、只保留立项判断；是否确认？

## 10. 不做什么

- 不写实现、不改任何代码/契约/模板。
- 不提交、不 push、不发版；版本号保持 `0.2.0-beta.33`。
- 不实现 #52 / #54 / #55；它们改由 `RFC-20261111-02` 只定 schema，不实现。
- 不实现 #51 / #53；不把候选设计写成既定事实。
- 不把「只对新记录生效」的 marker 当成信任边界；没有写入方的 marker 一律不写进 #50。
- 不为绿而放宽既有判据；不把 `--allow-dangling-acs` 写成永久豁免。
