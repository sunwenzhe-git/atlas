# 提案标题：跨仓宿主沙箱对照跑分（`atlas eval host`）与自进化巡检裁决对齐

> 提案编号：RFC-20261126-03（v2，针对 Round 1 对抗评审全量修订）  
> 提案作者：@sunwenzhe-git  
> 关联状态：已定案并实施 (Accepted & Implemented)——独立对抗评审两轮通过（`proposals/REVIEW-20261126-01-cross-repo-sandbox-eval.md`）  
> 影响范围：脚本工具 (scripts) | CLI 路由 (bin) | 巡检裁决 (duty-review) | 提案规范 (proposals) | 测试防线 (tests) | 门册与导览 (shared/gates, docs/map) | 自养宿主 (`atlas-playground`)

---

## 1. 现象与取证 (The Problem & Evidence)

### 1.1 触发形态（抽象）
* **规则 / 环节**：自进化闭环中的跨仓沙箱验证（`scripts/atlas_eval.py`、`bin/atlas.js`）、每日巡检信号面（`scripts/duty_signals.sh`、`duty-review/README.md`）与分层提案规范（`proposals/README.md`）。
* **触发时机**：当自动化巡检、外部情报扫描或模型代际演进产生针对 `skills/`、提示文案或核心校验/工作流脚本的候选改动时。
* **具体行为**：
  1. `scripts/atlas_eval.py` 现有 `run` 子命令只支持同一仓库内两个 commit 的 `git worktree` 对照（`--root` 单仓模型），无法将 `atlas` 源仓的 `base` 与 `candidate`（含工作树 `WORKTREE`）分别装配到外部自养宿主（如 `atlas-playground`）的两个隔离 worktree 中运行对照，`ledger` 也不采集运行态 `check-events.jsonl` 增量变化；且 `bin/atlas.js:601` 在采纳仓默认优先运行宿主旧 `.atlas/scripts/atlas_eval.py`，无法路由新子命令；
  2. `scripts/run_playground_benchmark.py` 与 `scripts/run_playground_full_workflow.py` 仅针对内置夹具 `tests/fixtures/verify_playground` + mock CLI 运行，未驱动真实自养宿主 `atlas-playground`（后者 `HEAD=2492b43` 当前暂存了 WIP 夹具 `HOME-DARK-MODE`，缺干净可重放基线 tag 与 `eval-cases.json`）；
  3. `scripts/duty_signals.sh` 仅读取 git 提交、`bugs.md` 族与 GitHub issues，未消费已落盘的 `.atlas/runs/check-events.jsonl`（高频撞门摩擦与 0 触发高耗时门线索）；同时源仓自身 `.atlas/runs/check-events.jsonl`（87 行全 `SKIP`）若不加区分会遮蔽宿主真实信号；
  4. `duty-review/README.md` 与 `proposals/README.md` 尚未固化「提示/Skill 快车道 vs 契约/门禁慢车道」的分层验收口径，也未记录外部 Trending 扫描从严上限（≤5 条）与元复盘规则。

### 1.2 客观证据与日志 (Minimal Evidence)
```text
scripts/atlas_eval.py:211-230       cmd_run 仅在单个 root 上执行 make_worktrees(root, base_sha, cand_sha, workroot)
bin/atlas.js:598-610                case 'eval' 优先执行 <cwd>/.atlas/scripts/atlas_eval.py 并注入 --root <cwd>
scripts/run_playground_benchmark.py:24   写死 FIXTURE = PKG_ROOT / "tests" / "fixtures" / "verify_playground"
scripts/duty_signals.sh:17-65       无 check-events 段；detached worktree 下 ../atlas-playground 不可达
atlas/.atlas/runs/check-events.jsonl    87 行源仓全 SKIP 噪声；playground/.atlas/runs/check-events.jsonl 含 WIP dirty 与 N/A 行
atlas-playground HEAD=2492b43       暂存 HOME-DARK-MODE WIP 夹具，atlas_check --fast 退出码 1（3 FAIL）；92e254f/f0303fa 无 tag
```

---

## 2. 决策与权衡 (The Decision & Trade-offs)

### 2.1 核心定案 (The Decision)
* **方案总结**：
  1. **扩展 `scripts/atlas_eval.py` 新增 `host` 子命令（兼容 `run` / `gate`）+ 修复 `bin/atlas.js` 路由**：
     - **CLI 与路径优先级**：
       - `bin/atlas.js` `case 'eval'`：当首参为 `host` 时**强制走 `PKG_ROOT/scripts/atlas_eval.py`**（避免命中宿主旧 `.atlas/scripts/atlas_eval.py`）；`run` / `gate` 保持既有本地优先回退逻辑。
       - `--harness-root` 默认取 `PKG_ROOT`（即 `Path(__file__).resolve().parents[1]`，要求存在 `install.py`，**绝不继承 `--root`**）；`--host-root` 默认取 `--root`（当通过 `atlas eval host` 在宿主仓内执行时自动指向 `cwd`）；相对路径 `--cases`、`--out`、`--worktree-root` 按 `Path.cwd()` 解析；默认 `--out` = `<host_root>/.atlas/runs/eval-host`；`ledger["root"]` 写入 `str(host_root)` 使 `atlas eval gate --ledger ... --out <rel>` 锚定一致。
     - **兼容边界与反空跑（anti-noop）**：
       - `--harness-base` 必须为 `--harness-root` 下的有效 git ref，`--harness-cand` 为 git ref 或字面 `WORKTREE`（直指 `--harness-root` 只读工作树）；两臂均要求存在 `install.py`（不支持 `479d958` 之前无 `install.py` 的历史 commit，缺失即 exit 2 响亮报错，推荐使用 D205 之后 `>= v0.4.0` 基线）。
       - 当两臂均为 git ref 且 `base_sha == cand_sha` 时拒绝（exit 2）；当 `--harness-cand WORKTREE` 时，使用 `scripts/pkg_digest.py` 的 `digest()` 结合 `install.py` sha256 比较两臂装配集摘要（覆盖 `shared/`、`rings/`、`apply/`、`scripts/`、`templates/`、`adapters/`、`validators/`、`patches/`、`_support/`、`skills/`、`extensions/` 与 `install.py`），若逐字节一致且未传 `--allow-noop` 则拒绝（exit 2），杜绝「只改了非装配文件或干净工作树却跑出假对比」。
     - **双仓隔离装配（含 skills 与 wiring）**：
       - 统一使用最外层 `try...finally` 管理两仓 worktree 生命周期（不让内层 helper 抛 `SystemExit` 跳过外层清理；清理顺序先 host 后 harness 并对两仓执行 `worktree prune`）。
       - `--host-ref` 未显式传入时，若 `cases` 注册表声明了 `"host_ref"` 则取之，否则默认 `HEAD`。
       - 在两份临时 `<host_wt>` 中执行 `python3 <harness_dir>/install.py --target <host_wt> --update --force`（**默认不传 `--no-skill` / `--no-wiring`**，因为 `install.py:430-438,613-755` 的 skill 瘦桩与 `AGENTS.md` 接线全部写入 `<target>` 目录、不触碰用户 `~/`，由此保证快车道改 `skills/` 与 `agent-pointer.md` 真正在沙箱生效；保留可选 `--no-skill` / `--no-wiring` 开关供特定调用方显式跳过）。非 `WORKTREE` 的 `harness` worktree 在 case 期间保持存活（保证 `atlas_check` 的 `装配版本` 门可解析源路径），`finally` 一并销毁。任一臂 `install.py` 返回非 0 ⇒ 立即清理并 exit 2。
     - **增量 `check-events.jsonl` 采集与 Tier A/B 分层**：
       - 在 **`install.py` 完成之后、跑 case 之前**记录 `<host_wt>/.atlas/runs/check-events.jsonl` 的已有行数 `before_lines`（不存在为 `0`），在 **跑完 case 之后、`measure_gate` 之前**读取新增行 `lines[before_lines:]`（避免 `gate_command` 自身写事件污染 case 统计；逐行 JSON 容错解析、过滤 `ablation_id != null`、记录 `parse_errors`、runs 数与新增 FAIL/WARN/ok 行分布）。
       - 产出兼容 `atlas eval gate` 的 `ledger.json`（含 `harness_root`、`host_root`、`host_ref`、`check_events_delta`）与人类可读 `summary.md`。
       - 明确口径边界：`atlas eval gate` 是 **Tier A（确定性检查与工作流烟测）**的硬回归门；**Tier B（headless Agent 端到端重放）**作为独立运行集/advisory 对照（配合 `runbook §4` rubric 与 `--retries`），不直接进确定性 CI `pass→fail` 阻断门。
  2. **扩展 `scripts/duty_signals.sh` 新增只读「运行态轨迹摘要」段**：
     - **路径探测（防源仓自影 + 支持 detached worktree）**：优先读取 `ATLAS_PLAYGROUND_ROOT`；否则通过 `git rev-parse --git-common-dir` 反推主仓父目录下的兄弟 `atlas-playground/.atlas/runs/check-events.jsonl`（在 detached worktree 下仍可用）；仅当当前仓**不是 Atlas 源仓**（缺少 `install.py` 或 `rings/`）时，才回退读取当前仓自身的 `.atlas/runs/check-events.jsonl`。
     - **严格信号清洗（纯标准库 Python，只读零写盘）**：
       - 逐行容错解析，跳过 `ablation_id != null` 的消融实验行；
       - 区分 `clean`（`git_dirty == false`）与 `dirty`（`git_dirty == true`）运行：高频摩擦热点（FAIL/WARN Top 5）优先按 clean 运行汇总并单独标注 WIP dirty 噪声；
       - 减法线索（0 触发高耗时 Top 5）**严格剔除 `SKIP` / `N/A` / `ABSENT` 及 `duration_ms is None`**，只对 `ok_count > 0 ∧ fail_count == 0 ∧ warn_count == 0` 的实跑门统计耗时分布。
  3. **裁决面文档与映射对齐（`duty-review/README.md`、`proposals/README.md`、`shared/gates.md`、`DESIGN.md`、`docs/map/`）**：
     - `duty-review/README.md` §3/§4 登记运行态轨迹只读输入段（明示只作观测输入、不自动计入 DR4）、`QUEUE.md` 改进条目的快/慢车道标签、Trending 扫描上限收严至 ≤5 条 + 防复读机锚 + 上期吸收元复盘；
     - `proposals/README.md` 登记**全仓库路径无盲区**的分层验收规范（明示仅规范 Atlas 自身 PR/RFC 准入，不改 `shared/gates.md:56`「`atlas eval` 不挂业务收口」口径）：
       - **快车道（行为引导与提示面）**：仅触及 `skills/`、`patches/project-wiring/agent-pointer.md`、`docs/`、`duty-review/`、`proposals/` ⇒ **不免除既有单测**（`test_install_selfcheck` / `test_canonical_consistency` 包括 `SKILL_BUDGET_CHARS < 20000` 照常强制），且触及 `skills/` 或 `agent-pointer.md` 时须附 `atlas eval host` Tier A 跨仓回归（并建议附 Tier B 收益对照）；
       - **慢车道（门禁、契约与运行时核心）**：触及 `validators/`、`shared/`、`rings/`、`apply/`、`scripts/`、`_support/`、`adapters/`、`templates/`、`patches/`（非 `agent-pointer.md`）、`install.py`、`bin/` ⇒ 强制单测 + M 系列变异钉 + D156 留出验证（触发时）+ 维护者拍板，涉及运行时/校验/装配面时附 `atlas eval host` Tier A 绿灯；
       - **纯测试/夹具面**：仅触及 `tests/` ⇒ 对应单测与全量 `pytest tests/`；
     - 同步更新 `shared/gates.md` **§2.1**（`:56` `atlas_eval.py` 行）登记新变异钉与 `〔数:用例数.test_atlas_eval.py=...〕`，同步更新 `docs/map/`（`ledger_snapshot.py --write` + `docs/map/atlas-map.html` 文件数）与 `DESIGN.md` 新 D 行。
  4. **基准化自养宿主 `/Users/sunwenzhe/Desktop/atlas-playground`**：
     - 保留 `HEAD=2492b43` 的 `HOME-DARK-MODE` 实验现场不动；在干净节点 `f0303fa` 打 tag `baseline-pre-tasks`、在 T5 收口后干净节点 `92e254f` 打 tag `baseline-post-t5`；
     - 在 `atlas-playground` 落地 `eval-cases.json`（显式声明 `"host_ref": "baseline-post-t5"`，包含基于稳定宿主的 Tier A 确定性门与 workflow 烟测 case）。

### 2.2 最强反方与证伪条件 (Strongest Counterargument & Falsification)
* **最强反方论证**：
  1. **沙箱真跑与宿主脏树冲突**：`atlas-playground` 把 `.atlas/` 跟踪进了 git，且 `install.py --update` 会同时覆盖 `.atlas/`、`skills/` 与 `AGENTS.md`，产生大量已跟踪脏文件——这会不会导致 `atlas_check` 或 `atlas workflow` case 在沙箱内与真实未跟踪 `.atlas/` 仓行为失真？**驳回/边界**：`atlas_check.py --fast`（`check_version` / `check_write_claims`）不因 `.atlas/` git 跟踪差异而假 FAIL，反倒能顺手测出 `install.py --update` 在已跟踪 `.atlas/` 仓的触点守卫；唯独在 `host` 模式下跑涉及 `workflow finish` 干净工作树门禁的 case 时，case 本身必须在临时卡或干净基线上测并显式感知该前提。
  2. **轨迹噪音与信噪比**：`atlas-playground` 的 `.atlas/runs/check-events.jsonl` 包含开发 WIP 期的 FAIL（14 行中 9 行 `git_dirty: true`）与 `N/A` 耗时行，放进 `duty_signals.sh` 是否只会制造噪音？**驳回/对策**：通过在读取侧强制剔除 `ablation_id != null`、`SKIP`/`N/A`/`ABSENT`、`duration_ms is None`，并将 `git_dirty: true` WIP 运行与 `git_dirty: false` 干净运行分栏输出，既保留真实故障线索又防止 `N/A` 和消融实验污染日常判断。
  3. **Tier B 非确定性与 `eval gate` 冲突**：若把 LLM 端到端重放直接连进 `atlas eval gate`，模型随机抖动会导致 CI 假失败。**对策**：严格把 `gate` 锁在 Tier A 确定性回归，Tier B 只作增量收益观察与人工/rubric 对照。
* **证伪条件（可执行的双端判别探针）**：
  1. **实跑闭环 + 回归捕获**：`discriminating_check_1` `{command: "python3 scripts/atlas_eval.py host --cases /Users/sunwenzhe/Desktop/atlas-playground/eval-cases.json --harness-base HEAD --harness-cand WORKTREE --host-root /Users/sunwenzhe/Desktop/atlas-playground --out /tmp/eval-host-probe && python3 scripts/atlas_eval.py gate --ledger /tmp/eval-host-probe/ledger.json", expected_if_false: "exit != 0，或 gate_green 出现假 FAIL，或 gate 无法解析 ledger"}`；
  2. **防假绿（skill/pointer 真实触达宿主 + 注入退化必红）**：测试套件中验证当候选修改 `skills/*/SKILL.md` 与 `patches/project-wiring/agent-pointer.md` 时，宿主 `cand` worktree 内的 `.agents/skills/*/SKILL.md` 与 `AGENTS.md` **必须发生实质变更**（抓出 `--no-skill --no-wiring` 类静默屏蔽），且向候选注入退化变更时 `atlas eval gate` 必须返回 **exit 1**。

### 2.3 必须警惕的刺痛代价与兼容性影响 (Trade-offs)
* **双仓清理责任**：`host` 最多在 `harness_root` 和 `host_root` 共建 4 个 worktree，必须由最外层 `try...finally` 保证零残留。
* **向后兼容**：`atlas eval run` / `gate` 命令行参数、退出码与旧 `ledger.json` schema 完全不变；`duty_signals.sh` 无轨迹文件时静默跳过、exit 0。
* **宿主无关红线**：离线采集只读取既有 `.atlas/runs/check-events.jsonl`，不向任何采纳仓增加运行时 LLM 遥测。

---

## 3. 改动面清单 (Affected Surface)

- [x] **代码逻辑**：`scripts/atlas_eval.py`、`scripts/duty_signals.sh`、`bin/atlas.js`
- [x] **契约/文档**：`duty-review/README.md`、`proposals/README.md`、`shared/gates.md`（§2.1 `atlas_eval.py` 行）、`DESIGN.md`（§12 `D216` 行）、`docs/map/index.md`、`docs/map/gates.md`、`docs/map/cli.md`、`docs/map/atlas-map.html`
- [x] **测试防线**：`tests/test_atlas_eval.py`（18 → 23 条，`M257`/`M258`）、`tests/test_duty_signals.py`（3 条，`M259`）
- [x] **留出验证（§4.5）**：已贴原始 `git diff --name-only` 与 `closeout_derive.py` 输出完成 (a)/(b) 触发面核对
- [x] **自养宿主（仓外基准化）**：`/Users/sunwenzhe/Desktop/atlas-playground` tag `baseline-pre-tasks` (`f0303fa`) / `baseline-post-t5` (`92e254f`) + `eval-cases.json`

---

## 4. 验证与测试结果 (Verification)

```bash
# 1. 靶向与相关测试套件
python3 -m pytest tests/test_atlas_eval.py tests/test_duty_signals.py tests/test_install_selfcheck.py tests/test_duty_bug_families.py -q
# -> 58 passed in 38.64s

# 2. JS 语法与 Atlas 快速自检
node --check bin/atlas.js
python3 scripts/atlas_check.py --fast
# -> OK (atlas_check_rc=0)

# 3. M257 / M258 / M259 隔离变异证明
# -> M257_rc=1 M258_rc=1 M259_rc=1

# 4. atlas-playground 实跑跨仓对照与门禁验证
python3 scripts/atlas_eval.py host \
  --cases /Users/sunwenzhe/Desktop/atlas-playground/eval-cases.json \
  --harness-base HEAD --harness-cand WORKTREE \
  --harness-root /Users/sunwenzhe/Desktop/atlas \
  --host-root /Users/sunwenzhe/Desktop/atlas-playground \
  --out /tmp/eval-host-probe
python3 scripts/atlas_eval.py gate --ledger /tmp/eval-host-probe/ledger.json
# -> pass2pass=4 gate_green 13->13 ; atlas eval gate PASS

# 5. 一致性与导览检查（本批相关项全绿；工作区存在先验并行在飞任务 guarded_continuation 的 2 项未决提示）
python3 -m pytest tests/test_canonical_consistency.py tests/test_map_anchors.py -q
# -> 32 passed, 2 failed (先验在飞项：guarded-continuation.md 未落盘 & 内核计数 42 vs 43)
```

### 4.5 留出验证

* **触发面核对**：
  * `(a)` 本 RFC §1 未引 `duty-review/bugs.md` 子族锚，独立对抗评审（`proposals/REVIEW-20261126-01-cross-repo-sandbox-eval.md`）无 ≥3 条重复 finding。
  * `(b)` 原始命令与输出（可复算）：

```text
$ git -C /Users/sunwenzhe/Desktop/atlas diff --name-only
DESIGN.md
archive/2026-11-24/share-ppt/outputs/... (4 files, unrelated pre-existing)
bin/atlas.js
docs/map/atlas-map.html
docs/map/cli.md
docs/map/gates.md
docs/map/index.md
duty-review/README.md
proposals/README.md
scripts/atlas_eval.py
scripts/duty_signals.sh
shared/gates.md
tests/test_atlas_eval.py

$ python3 /Users/sunwenzhe/Desktop/atlas/scripts/closeout_derive.py --root /Users/sunwenzhe/Desktop/atlas --diff-base HEAD
本清单不含语义触发行，正文自查
本轮改动 20 个文件（atlas 自有对账面 7 个；业务面 13 个，只计条数）
[自动] 步骤 1 —— 触发：任一工作单元收尾；改 `DESIGN.md` §12 决策（尤其含「被否：」的行）/ 撤回或收窄某项能力宣称；改契约 / 模板 / 校验器 / 脚本 / skill 瘦桩；改动触及核心业务链路 / 权限 / CI / 依赖 / 契约（判据指针：closeout.md §2 步骤 1）
[自动] 步骤 2 —— 触发：改契约 / 模板 / 校验器 / 脚本 / skill 瘦桩（判据指针：closeout.md §2 步骤 2）
[人工] 步骤 3 —— 触发：改动触及核心业务链路 / 权限 / CI / 依赖 / 契约（判据指针：closeout.md §2 步骤 3）
[人工] 步骤 5 —— 触发：改契约 / 模板 / 校验器 / 脚本 / skill 瘦桩（判据指针：closeout.md §2 步骤 5）
[人工] 步骤 7 —— 触发：改契约 / 模板 / 校验器 / 脚本 / skill 瘦桩（判据指针：closeout.md §2 步骤 7）
[WARN] atlas 自有面文件未命中任何触发行：_support/guarded_continuation.py（触发表可能漏了一行，或这张表该扩了）
```

* **结论**：不适用（本批为新增 `atlas eval host` 子命令、巡检只读轨迹面与提案车道规范对齐，未修改既有机器校验器判据，也未落入 `bugs.md` DR4 活跃族路径）。
