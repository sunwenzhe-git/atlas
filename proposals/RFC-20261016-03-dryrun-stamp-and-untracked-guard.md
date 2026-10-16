# 提案：装配器两件 tool-semantic 修复 —— 干跑不落版本戳 + 脏树守卫分「已跟踪/未跟踪」两语义

> 提案编号：RFC-20261016-03
> 提案作者：@Agent 起草（会话内）
> 关联状态：**v2 —— 已吸收独立评审（tech-proposal-reviewer，verdict = 修后采纳）1 条 major + 6 条 minor/suggestion，处置见 §6**
> 影响范围：装配器 (install.sh) | 出厂测试 (tests/test_install_selfcheck.py) | 门册 (shared/gates.md「装配版本」「tests/test_install_selfcheck.py」两行) | 决策/变更登记 (DESIGN.md)
> 关联 issue：`#21`（干跑落戳 ⇒ 版本门报「一致」而内容陈旧）、`#22`（`.atlas/` 未跟踪 ⇒ `--update` 守卫恒拒 ⇒ `--force` 被逼成常规）｜批内 F 号：**F54**「干跑不落戳」、**F55**「守卫两语义拆分」；决策号：**D92、D93**（D91 已被批 d7d8699 占用）

---

## 1. 现象与取证 (The Problem & Evidence)

两案同源：都是 `install.sh` 装配器的**断言语义被形态短路**——§15 类别 1（判据可被措辞满足）/ 类别 3（守卫恒真失效）。流水线自感知上报时间 2026-10-16 14:50，现场证据在采用者项目实测。

### 1.1 Issue #21 → F54：`--dry-run` 会写装配版本戳，「干跑不干」破例

**病灶**：两个路由合取后造假。

```text
install.sh L 111:  脏树守卫挂 [ "$DRY_RUN" -eq 0 ]        ⇒ 干跑跳过守卫（预览语义，合理）
install.sh L 447:  版本戳落盘 = 裸 python3 heredoc（run() 外、无 DRY_RUN 判据）
                                                  ⇒ 干跑也真写 <target>/.atlas/VERSION
```

干跑 `-update` 把戳更新为**源包**当前摘要（payload 一文件未拷），随后一次被脏树守卫拒绝（exit 1）的真 `--update` 让副本「戳新 / 内容旧」；`atlas_check` 的「装配版本」门是**自写自读闭环**（只比 戳 ⇔ 源包摘要，不验副本内容）⇒ 读到新戳报 **ok「源包与装配态一致」**——「重装前先对账」的门被一次干跑洗成假绿。实测（issue 帖）：`--update --dry-run` 输出含 `[ok] .atlas/VERSION 装配版本戳`且文件 mtime 更新；后续真 `--update` 被守卫拒（payload 未拷，grep 常量为 0）；同录 `atlas_check --fast` 报「装配版本」**一致**。

**根因面**：版本戳载入位置不是问题的全部（它已在脚本最后，真跑且经 `set -e` 中途退出时不会落新戳）——问题是**这唯一一处写盘没有走干跑闸门**（全脚本其余写盘都经 `run()` / `DRY_RUN` 判据）。**未上报的同族面（评审 A-2 补）**：干跑**首装**时 `stamp_file` 内含 `parent.mkdir` ⇒ 旧路径全新 target 干跑也会真残留 `<target>/.atlas/`，卡住随后的真首装——同一道闸门顺带关闭。

### 1.2 Issue #22 → F55：脏树守卫把「整目录未跟踪」当成「已跟踪文件被改动」

**病灶**：守卫逐行收集 porcelain 输出，判据只看**路径**不看**状态列**：

```bash
install.sh L114–119:
  … done < <(git status --porcelain | cut -c4-)     # 掐掉 XY 状态列
  case "$raw" in .atlas/*|.atlas|…AGENTS.md) DIRTY_TOUCH="…" ;;
```

`.atlas/` 整目录未跟踪时 porcelain 折叠成一行 `?? .atlas/`；cut 后得 `.atlas/`，case 模式 `.atlas/*`（`*` 可配空）命中 ⇒ **未跟踪在场被判成「脏」**。在 `.atlas/` 有意不入版本控制的副本侧，守卫恒拒 ⇒ `--force` 成为 --update 常规前缀 ⇒ 守卫真正要护的东西（副本侧未提交的线束改动）反而在噪声里失去保护。实测（issue 帖）：porcelain 输出 `?? .atlas/`；无 `--force` 的 `--update` 报「装配触点存在未提交改动（.atlas/ AGENTS.md）」exit 1，而副本与源包实差仅 3 文件 + `__pycache__`，**并无本地独有改动需要保护**。

**守卫的两个真语义被一个桶吞了**（F34 落仓原意：护「已跟踪文件上的未提交改动」不被 rm -rf 卷走；而对「整目录未跟踪」，git 根本无基线可护——它只能说明「装配产物没入库」，那是 flag 旗，「包产物默认刷新」的正常形态）。

---

## 2. 决策与权衡 (The Decision & Trade-offs)

### 2.1 D92（F54）：版本戳落盘必须挂干跑闸门——「干跑不产生装配态变更」

1. 戳写入（L447–462 整块）外层挂 `DRY_RUN` 判据：`--dry-run` ⇒ 只出声 `  [dry-run] 装配版本戳（不落盘：干跑不产生装配态变更）`，不进 python。**不采**「把戳写包进 `run()`」的写法：run 只对子命令生效，对裸 heredoc 管段无效，包进去反而留一个「看起来受控实际直写」的假闸门。
2. 真跑路径行为**逐字节不变**：落戳仍最后一步、失败仍硬错（F37 口径）、文案不动。
3. `atlas_check`「装配版本」门零改动——修后守住「假绿来自干跑写坏戳」的来路，不去做「验副本内容」的第二重判据（issue 建议③的否决理由见 §2.3）。

### 2.2 D93（F55）：脏树守卫按 porcelain 状态列分语义——已跟踪改动**拒**，未跟踪在场**WARN 放行**

1. 守卫循环改读**整行**：XY 状态列（`${raw:0:2}`）+ 路径（`cut -c4-`）；触点 case 模式不变（`.atlas/*|.atlas|.trellis/workflow.md|.trellis/config.yaml|AGENTS.md`）。状态 `??`（未跟踪——含整目录折叠 `?? .atlas/`）⇒ 进 `UNTRACKED_TOUCH`；其余状态 ⇒ 进 `DIRTY_TOUCH`（现行为）。
2. `DIRTY_TOUCH` 非空 ⇒ 行为增量逐字节不变：`--force` 才放行，其余 exit 1（守卫主语义，护已跟踪的未提交改动）。
3. `UNTRACKED_TOUCH` 非空且 `DIRTY_TOUCH` 为空 ⇒ **WARN 放行**（不拒、不要求 `--force`）：出声一行，点名触点 + 「git 侧无基线可护，副本侧未回灌改动覆盖自负——按 ATLAS-UPSTREAM.md 先回灌再刷新更稳（回灌助手 scripts/backflow.py）」；旗位保持 exceptional（issue #22 的落点关切：「--force 被逼成常规」）。
4. 两桶皆非空 ⇒ 仍走拒路径（`--force` 才过），未跟踪项并进通知文案——**拒绝优先于放行**，不允许「一个可拒点被另一个可放行点遮住」。

### 2.3 考虑过的备选及否定理由

- **【#21-③】给「装配版本」门加副本内容抽检（对 `.atlas/` 重算摘要比对戳）——本批不采**：摘要算法口径为**源包布局**而立（`ASSEMBLY_COVER_DIRS` + `SKIP_DIRS`），对副本侧直算需先立案「副本清单 = 包拷贝集 − 副本本地改动 − VERSION 自环 − `__pycache__`」的可比口径；口径未立就上判据，任何副本本地正当改动（ 含在进行中的回灌批）都制造 WARN 风暴 ⇒ 门又一次被训练成噪声。留待独立 RFC（判据面成立时要连 D79 升档规则一起验）。
- **【#22-① 反向】未跟踪也拦、只降一格到「必答确认」**：等价于把 `--force` 改名换姓成为常规输入——issue 本体关切不除，否。
- **【#22 甄别强口径（评审 B-1 首选）】副本版本戳 == 当前源包摘要 ⇒ WARN 放行；不等/缺 ⇒ 回落拒路径**：截住「未跟踪 + 有副本独有改动」的静默丢失，零新配置面。**本批次要不采、采其下限**：npm 升级链路（`atlas upgrade` ⇒ 项目 `atlas update`）里**最常见形态恰是「未跟踪且已过期」**（副本由旧发行版装配、`.atlas/` 不入库、源包已前进）⇒ 戳不相等 ⇒ 每次合法升级都被逼 `--force`——病灶复现（issue #22 的落点关切本身）。已采下限 = WARN 文案**双摘要可见化**（副本戳 ⇔ 源包摘要同录），丢失风险可见 + 出路先行（ATLAS-UPSTREAM.md / `backflow.py`）；「试用期无本地改动」的常态（issue 现场证据）不再被拦。
- **【#22-②】项目级开关声明「装配目录不入库，守卫闭嘴」**：多一个需要同步登记/退役的配置面，而 porcelain 状态列本身已携带全部所需信息——用上游真相源，不造第二份声明，否。
- **【#22 评审 A-4 非问题备案】quotepath 非 ASCII / rename 行 / porcelain v1/v2**：触点全 ASCII，前缀模式对 rename 行保守命中——不升 porcelain v2。
- **【#21 干跑跳过脏树守卫】（现状）保持不动**：预览语义要求展示「改动计划」而非「当下合法性」；守卫在干跑里没有可保护对象（不写盘）。

### 2.4 钉子（tests/test_install_selfcheck.py，子进程集成同 F34 风格）

- **A-1（F54，变异钉 M77）**：存量装配态干跑 ⇒ exit 0、`[dry-run] 装配版本戳` 出声、VERSION **逐字节不变**；全新 target 干跑 ⇒ exit 0 且 `<target>/.atlas` **不在场**（评审 A-2 的 mkdir 残留面，两态双证）。
- **A-2（F55；前半变异钉 M78 / 后半回归钉）**：git 仓只提交 `AGENTS.md` + `.trellis/workflow.md`，`.atlas/`（含 fixture 戳）**有意不 add**。前半：`--update` 无 `--force` ⇒ **exit 0**、输出含「未跟踪项」WARN 与「当前源包」双摘要文案、`.atlas/` 被真刷新（fixture 戳被 16 位摘要重写）⇒ 退回「只看路径列」即红（M78）。后半：已跟踪 `AGENTS.md` 改脏 ⇒ 无 `--force` 仍 exit 1（拒优先，不被未跟踪项遮蔽）；`--force` ⇒ exit 0 且 F34 文案「感知到装配触点未提交改动」逐字节保留 + 「另有未跟踪项」并录。fixture 契约（评审 D-4）：与 F34 同旗（`--no-skill --no-patch --no-wiring`）、预建 `.trellis/`、git 只提交指针文件、脏固件在 `--force` 后**还原**再复跑（守卫放行不改指针文件）。
- **变异**：**M77**（摘 F54 干跑闸 ⇒ A-1 红）/ **M78**（未跟踪桶改指脏桶 ⇒ A-2 前半红）；两枚注入前 `bash -n` 校验、还原逐字节一致（post-batch sha `ee5ac3d0b4db…`）。

---

## 3. 落点清单 (Implementation Footprint)

| 文件 | 改动 |
|---|---|
| `install.sh` | ① 戳写块挂 `DRY_RUN`；② 守卫循环整行读 + `UNTRACKED_TOUCH` 分桶与 WARN 放行 |
| `tests/test_install_selfcheck.py` | +2 集成钉（A-1 / A-2）+ 变异自证（暂退改动 ⇒ 新钉红） |
| `shared/gates.md` | 「装配版本」行补录：戳只在真装配落（F54），干跑不产戳 ⇒ 「戳新内容旧」来路关闭 |
| `DESIGN.md` | D92 / D93 四行补记 |
| `CHANGELOG.md` | 新版头 + 本批一节（Issue #21/#22: F54/F55, D92/D93） |
| `proposals/RFC-20261016-03-…md` | 本文件（评审处置后升 v2） |

---

## 6. 评审处置 (Review Disposition)

评审方：tech-proposal-reviewer 子代理；verdict = **修后采纳**（无 blocking）。

| 项 | 级别 | 要点 | 处置 |
|---|---|---|---|
| A-1 | 核验通过 | 干跑落戳是全脚本唯一 VERSION 写入，无旁路（逐行核 `pkg_digest.stamp_file`） | 备案 |
| A-2 | minor | 干跑**首装**经 `stamp_file` 的 mkdir 残留 `<target>/.atlas/`，卡随后的真首装——RFC 未点名 | **采纳**：§1.1 补取证 + A-1 钉加全新 target 态断言（两态双证） |
| A-3 | 核验通过 | 真跑 `set -e` 中途退出时戳保持旧值（方向安全） | 备案 |
| A-4 | 核验通过（备案） | quotepath / rename 行 / porcelain v1-v2 无影响 | §2.3 备案 |
| B-1 | **major** | 未跟踪 `.atlas/` 内确有副本独有改动 ⇒ WARN 放行 = 静默丢失 | **采纳下限**：WARN 双摘要可见化 + 回灌出路先行；强口径（戳相等才放行）否——npm 升级链路「未跟踪且过期」最优形态会被逼 `--force` 常规化，病灶复现（理由录 §2.3 / D93） |
| C-1 | 核验通过 | 拒优先 + `--force` 语义未漂移 | 备案 |
| C-2 | minor | F34 钉断言文案须稳定 | **采纳**：拒路径 force 文案逐字节保留，F34 钉回归绿（本轮实证） |
| C-3 | suggestion | 两路径措辞统一词典 | **采纳**：统一「未跟踪项」 |
| D-1/D-2 | 核验通过 | 钉子在旧代码可红；子进程可行性已被 F34 现实证明 | 备案 |
| D-3 | minor | 「A-2 两半在旧代码红」表述不实（后半本就绿 = 回归钉） | **采纳**：§2.4 改「前半变异钉 M78 / 后半回归钉」 |
| D-4 | minor | fixture 契约未写死 | **采纳**：四条契约录 §2.4 |
| D-5 | minor | 漏变异编号登记 | **采纳**：M77/M78 登记（先例 M76） |
| E-1 | 核验通过 | F54/F55/D92/D93 编号无占用 | 备案 |
| E-2 | minor | gates.md 计数同步 | **采纳**：`tests/test_install_selfcheck.py` 行补两钉；计数以 pytest 实收为准（7 → 9 条该文件内） |
| E-3 | suggestion | install.sh 头部用法注释补守卫语义 | **采纳**：模式段 +2 行 |
| E-4 | 核验通过 | AGENTS.md §3 / 指针段无连带改动需求 | 备案 |
