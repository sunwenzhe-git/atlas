# 交接 · 2026-11-01（新窗口开场用）

> **性质**：`research/` 工作留痕，非 canonical、不进装配、不作执行契约。
> **给谁**：下一个会话（无任何上文记忆）。本文自足：照 §1 核对现场 → 按 §3 的顺序做 → §5 是需用户拍板的事。
> **一句话现状**：消融真实批次 02 已完成并入库；`RFC-20261101-03` 的**修复已落分支但还没合并**，合并前差一道「全量复跑 + 与 main 对齐 + 第三轮只读复核」。

## 1. 现场核对（先跑这几条，别信本文的哈希）

```bash
cd /Users/sunwenzhe/Desktop/atlas
git log --oneline -3                      # 期望 HEAD 已含本文件那条 docs(handoff)；main 未 push
git status --porcelain                    # 期望空
git worktree list                         # 期望含 /private/tmp/atlas-rfc-20261101-03-20261101-192510
cd /private/tmp/atlas-rfc-20261101-03-20261101-192510
git log --oneline -3                      # 期望 d24ae6e ← b69ff4f ← f3fd984(=main HEAD，已 rebase)
git status --porcelain                    # 期望空
git merge-base main HEAD                  # 期望 = main HEAD（⇒ 合并是纯 ff）
git rev-list --count main..origin/main 2>/dev/null; git rev-list --count origin/main..main
```

已知（写于 2026-11-01 晚）：main 比 `origin/main` 领先（写这几行时为 12 个提交，**未 push**，用户未授权），确切数以 `git rev-list --count origin/main..main` 为准；分支 = `d24ae6e`（已 rebase 到 main，**未合并**），工作树干净。

## 2. 这一轮做了什么（都已提交，无需重做）

**A. 消融真实批次 02**（main `4e94496` + `f3fd984`，文档 `research/2026-11-01-ablation-real-batch-02.md`）

- 三个真实快照 × 3 轮 = 9 次编排运行，**0 FAIL**；`validate_testids` 占已计时门总和 **61–66%**（9/9 轮稳定）。
- 方法学结论（已写进设计文档）：**绝对 ms 跨环境不可比**（同一快照同一份文件：编排内中位 2826ms vs 单跑 4173ms，单跑首轮 8839ms 冷缓存），成本读数只能用同轮占比 + 配对差值。
- P5-A（D141 提取器复用）从 E2 升 **E1**：取源包 `d0c9a03` / `0830a72` 两份只差 10 行的校验器，两个真实快照「预热 + 8 轮交错 + 轮内顺序轮换」⇒ **-10.7% / -12.4%，16 对逐轮全部同向**，输出逐字相同、项目零漂移。
- 影子 `validate_e2e_index` 累计 **12 次运行 0 独立信号**（不删门，铁律）。
- 两处自我更正：① 三个快照的安装副本都已含 P5-A（旧记忆「需重装才生效」作废）；② `审查报告形态` WARN 属项目侧报告资产，7 行 WARN 里只有 `装配版本` 是 Atlas 自己的重装欠账。

**B. RFC-20261101-03 的修复轮**（分支 `e96fa3a`，账本在 `proposals/RFC-20261101-03-signer-must-be-string.md` §4.2）

| 编号 | 级别 | 病灶 | 修 | 新钉 |
|---|---|---|---|---|
| B1 | Critical | `load_resolves` 顶层缺省签字人 `str()` 洗白：`{"by":123}` → `"123"` 继承进每一条 ⇒ 台账 `PASS resolved 1`（端到端复现过） | `scripts/cli_review_convert.py:108-118` 顶层 `by` 若非 None 必须过 `signed_str` | **M51**（`tests/test_cli_review_convert.py`，四侧 123/数组/空白/true + 无半截产物） |
| B2 | Major | `round_declares` 一条坏形状 ⇒ 整批没收同轮合法声明 = 假失忆 | `_support/review_policy.py:230` 新增逐条判据 `resolves_entry_errors`；`scripts/review_closure.py:137-165` 逐条取舍 | **M98**（`tests/test_review_closure.py`） |
| B3 | Major | `is_blocking_critical` 收紧无独立钉：退回宽松版 **131 条全绿**（CLI 侧被 M48 形状判据遮蔽） | 内核级直接断言 | **M100**（`tests/test_review_report.py`） |
| B4 | Minor | `verification.evidence`、`escalation.approved_by` 仍 `str()`（同对象一侧严一侧松） | `_support/review_policy.py:305` / `:329` 走 `signed_str` | **M99** / **M101** |
| B5 | Minor | 测试名/文档串声称「数字签名」而体内用 `by:"lead"` | 改名 `test_resolves_entry_with_string_signer_closes`（正例对照）；`review_closure.py:218` 的重复 `str()` 走 `has_signed_disposition` | — |
| B6–8 | Minor | 锚点 `count_floor:45` 错（实 `:61`，启发式判绿）、门册 `M42–M48` / `M1–M17` 范围与归属错、契约三条字段口径未补 | `docs/map/review.md`、`shared/gates.md`（含新增盲区一行：形态门不查 `review.json.resolves` 条目形状）、`shared/independent-review.md` | — |

计数现状（门已核）：`test_review_closure.py` **40**、`test_review_report.py` **45**、`test_cli_review_convert.py` **51**；行数 `review_policy.py` **371**、`review_closure.py` **423**、`cli_review_convert.py` **372**、`validate_review_report.py` **221**。

## 3. 剩下要做的事（按顺序，1→4 是同一件事）

1. **复跑全量**（可选的绝对保险；已完成的部分：修复轮 `e96fa3a` 上全量 **1019 passed / 5 skipped** 真跑绿，
   随后 rebase 到 main，`git diff e96fa3a d24ae6e` 在 `research/` **之外为空** ⇒ 代码/测试/契约面与被验证过的那棵树逐字节相同；
   rebase 后另跑过 map + canonical + 三个审查测试文件 = **153 passed**。要彻底稳妥就再跑一次：
   ```bash
   cd /private/tmp/atlas-rfc-20261101-03-20261101-192510 && python3 -m pytest tests/ -q
   ```
   失败就贴原文回来判，别自行放宽断言。
2. ~~与 main 对齐~~ **已完成**：分支已 rebase 到 `f3fd984`（main 只多了 `research/` 文档，无冲突）。合并因此是纯 `--ff-only`。
   纪律提醒留着：**不要用 `git stash` 复现**（本机规矩）；要动就先提交。
3. **第三轮只读复核**（流程：方案 → 只读评审 → 主审抽查 → 用户确认）。范围要小，只问三件事：
   B1 是否真的堵死（还有没有别的 `str()`/真值判签字的旁路）；B2 的逐条取舍有没有把「重复指纹」口径改松；
   M100 这种**内核级钉子**在门册里的表述会不会让后人误以为 CLI 侧已覆盖。派 `【示例】代码审查员`，明确 read-only、scratch 只进 `/tmp`。
   ⚠️ 上一轮的教训：评审会自己跑 `review_closure.py`，它会在被扫的报告目录里**生成 `closure.json`**（本轮就落在 `proposals/REVIEW-2026-10-23-.../closure.json`，已移出仓库到 `/tmp/rf03-review-artifacts/`）。让评审者**别写仓库**，或在复核后 `git status` 清一次。
4. **合并**（唯一还没做的动作；需用户点头，本地 ff，不 push）：
   ```bash
   cd /Users/sunwenzhe/Desktop/atlas && git merge --ff-only rfc-20261101-03-signer-strictness
   python3 -m pytest tests/ -q
   ```

## 4. 之后排队的事（不阻塞合并）

- **消融批次 03**：别再重复同形态 —— 12 次运行 0 FAIL、0 处置，分母已钉死在 0。要先**采到事件**：一次真的把门跑红的任务状态 + 一条被人实际处置的 WARN（留时间戳与动作），这才是 C5 误拦/噪声的分子分母。协议见批次 02 §8。真实项目跑批必须快照→跑→截断新增事件行→逐文件 sha 还原→复核 `git status` 与受保护树。
- **nanwang 遗留（BACKFILL 记在**克隆**里：`/tmp/atlas-impl-review-20261031-204905/nanwang/product/reviews/2026-10-31-impl-review-dashboard-topn/BACKFILL.md`；Atlas 仓内**没有** `product/reviews/`，别在错的地方找）**：r4 与 scan 补审未经独立复审（4 轮上限已升级登记）；r1 仍有 10 条 Minor 未处置；2 条 scan 项延后；克隆仓有 7 条**改动前就红**的基线测试。克隆在 `/tmp/atlas-impl-review-20261031-204905/nanwang`（`/tmp` 会被清，清了要重新克隆）。
- **弱点留出（`project-weakness-heldout-loop`）的两个盲区**之一：「触发靠自述可被逃」——目前只靠独立评审手工对照。
- **P3 消融事务工具**（设计文档 §7 的 P3）：物理摘除只在隔离副本，没做工具化。

## 5. 需要用户拍板 / 授权（agent 不要自作主张）

1. **push**：main 领先 origin 10 个提交。**未授权不得 push**；「提交推送」在该项目语义里 = 完整发版链（走 `atlas-release` skill），不是单纯 push。
2. **发版**：当前 npm 全局装的是 `0.2.0-beta.25`；分支里的收紧改动要发版后真实项目重装才拿到。
3. **真实项目重装**（`install.sh --update`）：三个采用方工作树都有未提交在途改动，动手前必须 dry-run + 用户点头。
4. **RFC-03 合并本身**：流程上要有用户「合并」二字。

## 6. 常驻纪律（本项目，别漏）

- 证据必须**真跑**；对称断言必配**反向夹具**；变异证明走四段（基线绿 → 注入红 → sha256 逐字节还原 → 复绿），注入只在 `/tmp` 副本。
- M 号引用要带**所属测试文件**（本轮就修了一处 `M1–M17` 把 `M15/M16`（属 `test_validators.py`）算进台账的问题）。
- 改行为/文案要同步：契约（`shared/*.md`）、`shared/gates.md` 计数与行、`DESIGN.md` 决策行、两处 changelog、`docs/map/*`（锚点 + 行数）；`tests/test_canonical_consistency.py` 与 `tests/test_map_anchors.py` 会咬。
- 写计数句时「文件名 + NN 条」要紧邻，别在中间插别的文件名（白名单式正则会误配，本轮踩过）。
- 只 stage 自己的文件 + `git diff --cached --check`；`git status` 干净再收尾。临时/客户仓的原目录只读，实验一律在 `/tmp` 副本或 worktree。

## 7. 可直接粘给新窗口的开场指令（**含全部剩余项，按顺序执行**）

> 接手 Atlas（`/Users/sunwenzhe/Desktop/atlas`）。先读 `research/2026-11-01-handoff-next-window.md` 全文，然后按下面顺序把**所有**剩余项做完；每项做完简短汇报，撞到需要授权的地方停下来等我，不要自己猜。
>
> 0. **核对现场**：`git log --oneline -3`（main 应已包含本交接文档那条 `docs(handoff)` 提交）、`git status --porcelain` 为空、`git worktree list` 含 `/private/tmp/atlas-rfc-20261101-03-20261101-192510`；分支头应为 `d24ae6e`，`git merge-base main HEAD` 应等于 main HEAD（纯 ff 就绪）。
> 1. **第三轮只读复核**（派 `【示例】代码审查员`，明确 read-only、scratch 只进 `/tmp`）只看三点：B1 批级缺省签字人的旁路是否真尽（还有没有别处用 `str()`/真值判「有人签了」）、B2 中间轮逐条取舍有没有把「重复指纹」口径放软、M100 内核级钉子在 `shared/gates.md` 的表述会不会让后人误以为 CLI 侧已覆盖。复核前后各跑一次 `git status`：跑 `review_closure.py` 会在被扫的报告目录生成 `closure.json`，那是生成物，别提交。
> 2. **有 blocker 先修**（同 §2 的路径：改代码 → 配钉子 → 四段变异协议只在 `/tmp` 副本跑 → 契约/门册/锚点/两处 changelog 同步 → 全量 `pytest tests/ -q`）。没 blocker 就报告并**等我点头再** `git merge --ff-only rfc-20261101-03-signer-strictness`，合并后再跑一次全量。
> 3. **消融批次 03**（协议照 `research/2026-11-01-ablation-real-batch-02.md` §8，快照定位与还原步骤见同文 §1）：① **处置面** —— 挑采用方一条长期挂着的 WARN 实际处置一次（改资产或明确接受），留时间戳与动作，这是 C5 误拦/噪声率的第一个真实分子；② **拦截面** —— 只有某个任务状态真能把门跑红才采，**不造假红**、不做整线束 on/off。每轮跑批前后必须：备份 `.atlas/runs` → 跑 → 截断新增事件行 → 逐文件 sha256 还原 → 复核 `git status` 与受保护树零漂移。成本结论只用同轮占比与配对差值（预热 + 交错 + 轮内顺序轮换），别拿绝对 ms 跨批次讲涨跌。产出 `research/2026-11-XX-ablation-real-batch-03.md`，不落项目名 / 绝对路径 / 业务 case ID。
> 4. **真实项目重装**（只有要测「重装生效」或发版口径时才做）：三棵采用方工作树都有未提交在途改动，**先 dry-run 并等我点头**。批次 02 已确认 P5-A 在三个快照都生效，所以这条优先级低于 3。
> 5. **nanwang 遗留**：台账在**克隆**里 —— `/tmp/atlas-impl-review-20261031-204905/nanwang/product/reviews/2026-10-31-impl-review-dashboard-topn/BACKFILL.md`（Atlas 仓内没有 `product/reviews/`，别在错处找；`/tmp` 被清就重新克隆装配）。待办：r4 与 scan 补审未经独立复审（4 轮上限已升级登记）、r1 剩 10 条 Minor 未处置、2 条 scan 项延后、克隆仓 7 条**改动前就红**的基线测试。
> 6. **弱点留出盲区**（`project-weakness-heldout-loop`）：「触发靠自述可被逃」目前只靠独立评审手工对照 —— 先做机制盘点再决定要不要加判据，别一上来建硬门。
> 7. **P3 消融事务工具**（设计文档 §7 的 P3）：把「物理摘除只在隔离副本」这套手工流程工具化 + 「消融残留」门以 WARN 出生；需 RFC + 坏输入测试 + M 钉，走应然链（方案 → 只读评审 → 主审抽查 → 用户确认）。
>
> **需要我说「可以」才动的四件事**：合并、push、发版、真实项目重装。其余（读、跑只读门禁、在 `/tmp` 副本注入与还原、写 `research/` 留痕并本地 commit）可自主连续做完。全程纪律：证据必须真跑；对称断言配反向夹具；M 号引用带所属测试文件；改行为同步契约 / `shared/gates.md` 计数 / `DESIGN.md` / 两处 changelog / `docs/map` 锚点与行数（一致性门会咬）；不要用 `git stash` 复现；只 stage 自己的文件 + `git diff --cached --check`；采用方与客户原目录只读。
