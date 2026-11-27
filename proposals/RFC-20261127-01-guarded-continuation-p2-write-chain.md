# 提案标题：Guarded Continuation P2 业务写链（`atlas workflow finish` 纳入治理链）

> 提案编号：RFC-20261127-01（v2.1，Round 2 双评均通过并已闭合 R2-M1/R2-N1）  
> 提案作者：@sunwenzhe-git  
> 关联状态：已定案并实施中 (Accepted) —— Round 2 并行双评通过（见 `proposals/REVIEW-20261127-01-gc-p2-dual-review.md`）  
> 影响范围：共享内核 (`_support`) | 脚本工具 (`scripts`) | 宿主扩展 (`extensions`) | 装配与门册 (`install.py`, `shared/gates`, `docs/map`) | 测试防线 (`tests`) | 自养宿主 (`atlas-playground`)

---

## 1. 现象与取证 (The Problem & Evidence)

### 1.1 触发形态（抽象）
* **规则 / 环节**：GDR（Guarded Continuation）从 P1 纯只读链向 P2 业务写链（`atlas workflow finish`）演进（依据：`handoff/2026-11-26-atlas-guarded-continuation-plan-v15.md` §0 M3、§8 P2 六条硬前置、§10 D2/D3；P1 正结果已由 `handoff/2026-11-26-gdr-p1-four-arm-report.md` 交付且用户已拍板 D2=要治理面）。
* **触发时机**：当工作单元完成 `verify` 并通过人工审查后，需要在 Pi 宿主治理窗口内经人类批准执行 `atlas workflow finish`（含隐写、状态提交、`git commit` 与归档），同时保证失败不自动重放、并发写者互斥、崩溃可诊断、全链可两阶段审计。
* **具体缺口**：
  1. **隐写与最终提交耦合在 `finish_task`**：`_support/workflow_finish.py:735` 在门禁判定前直接调 `extract_deferred_findings` 写 `deferred.md`，`:800` 在 `topology_required` 时调 `refresh_topology` 写 `.adapter-out/`，`:928` 在 `enforce` 下调 `build_receipt` 写 `.atlas/runs/workflow-receipt*` 与 `workflow-review-origin.json`，`scripts/atlas_workflow.py:678,688` 在缺失回推或失败时自动运行 `atlas_change --auto-stage` 并写 `attempts.jsonl`——缺乏独立、零写盘的纯预检入口。
  2. **缺少跨进程共享的长生命周期锁**：既有 `scripts/write_claim.py` 为一次性 CLI `O_EXCL` 模拟锁，进程崩溃即遗留孤儿锁，且 `workflow_finish.py`、`atlas_workflow.py` 与 `extensions/pi.ts` 之间无内核级互斥锁。
  3. **Pi 批准票未绑定 `run_id` 与不可逆二次确认**：P1 `GcTicket`（`extensions/pi.ts:34-41`）仅绑定 `unit/planSha256/sessionId/nonce/expiryMs`，`runId` 在 `atlas_continue` 执行期才生成，且只有单次 `ctx.ui.confirm`，对开户态仅检查 `isAtlasProject`（未按 v16 M3 对写链强制 `onboarding === "done"`）。
  4. **写链阶段感知、WAL 保护与防绕过缺口**：P1 `scripts/atlas_continue.py:85,129,208,258` 写死活跃目录 `in_progress`、全树零变化与 `plan` 活跃区；P1 `extensions/pi.ts:135,481,711,1051,1132` 将 `AUDIT_FAILED` 放入 `GC_TERMINAL_STATES` 且 `revoke-continuation` 无条件覆写 marker，会直接洗白非终态锁；TS 写盘缺 `O_NOFOLLOW` 与 `dir_fsync` 且未检验 `UNIT_RE`。
  5. **净化启动器缺 `PYTHONDONTWRITEBYTECODE=1` 且 git 包装器模板仅含 P1 两条**：`/tmp/atlas-p1-frozen/launcher.sh` 未导出 `PYTHONDONTWRITEBYTECODE=1` 导致 `workflow_finish.py` 派生校验器子进程可能生成 `.pyc` 污染工作树；只读包装器未覆齐 `workflow_finish` 及其传递依赖的实测 git 调用，也未隔离只读与写链 git 权限面。
  6. **自养宿主 `atlas-playground` 为半开户态**：当前缺少 `.atlas/spec/structure/_meta.json`（仅 `product/prd/prd.md` 在场），且因 `site/` 存在属非绿地项目，需补齐合规结构环开户方能通过 M3「写链必须全开户」硬前提。

### 1.2 客观证据与日志 (Minimal Evidence)
```text
_support/workflow_finish.py:735          extract_deferred_findings(root, task, t_dir) 在门判定前写 deferred.md
_support/workflow_finish.py:800,928      _refresh_staged_topology / build_receipt 写 .adapter-out / .atlas/runs
_support/workflow_finish.py:970,973      atomic_write_json(task.json) + archive_task()，未调用 dir fsync，无共享写锁
scripts/atlas_workflow.py:678,688        _finish_change_backflow / record_attempt 隐式写回推产物与 attempts.jsonl
extensions/pi.ts:34-41,135,481,890,911   GcTicket 无 runId；AUDIT_FAILED 在终态集；revoke 无条件覆写；readOnlyHint=true
scripts/atlas_continue.py:47,85,146,208  _tree_entries 未排除锁；_task_state_ok 写死 in_progress；verify/audit 强制全树零变化
/tmp/atlas-p1-frozen/launcher.sh:11-15   env -i 未导出 PYTHONDONTWRITEBYTECODE=1
atlas-playground/.atlas/spec/structure/  缺失 _meta.json（半开户态；site/ 存在属非绿地）
```

---

## 2. 决策与权衡 (The Decision & Trade-offs)

### 2.1 核心定案 (The Decision)

#### 决策 1：宿主开户前提选型（二选一明确拍板）
* **定案**：采用**方案 A —— 为 `atlas-playground` 补齐符合非绿地校验规则的结构环语义开户**，并在其隔离 `/tmp` 克隆副本上执行 P2 真宿主 D 臂 RPC 烟测。
* **开户合规细节**：
  * 读取 `atlas-playground` 实际代码（`site/`、`scripts/`、`product/stack-profile.yaml`、`product/prd/home-prd.md`），补齐 `.atlas/spec/structure/{_meta.json, tour.md, global/directory-map.md, global/routes.md, domains/home.md}`。
  * 因 `atlas-playground/site/` 存在，`validators/validate_structure.py:285` 判定 `greenfield = False`：`_meta.json` 必须满足 `categories.A ∈ {covered, skipped}`、`categories.H ∈ {covered, added}`（**禁 `skipped`**），若声明 `truth_carriers` 须指向存在且非空的文件（如根 `README.md` 或 `TASKS.md`），且全仓运行 `python3 validators/validate_structure.py --root <playground>` 必须 `PASS`（0 FAIL）。
  * `atlas-playground` 内 `adapters` 全为 `null`，按 `scripts/refresh_structure.py:742-748`，空转态刷新不会自动推进 `baseline.commit`；提交结构开户产物后，在 `/tmp/gc-p2-smoke/project` 克隆副本内运行 `python3 .atlas/scripts/refresh_structure.py --root . --chain --advance-baseline` 使克隆副本内 `baseline.commit == HEAD`（`.atlas/` 属于 `clean_exempt_prefixes` 豁免前缀，不脏工作树）。
  * 保持 `atlas-playground` 的 `baseline-post-t5` tag 不动，且所有 `atlas eval host` 用例注册表（如 `eval-cases.json`）显式锁定 `"host_ref": "baseline-post-t5"`，避免 `atlas_eval.py:503` 默认回退 `HEAD` 改变旧基线行为。
* **否决备选（方案 B：直接在存量业务仓执行写链烟测）**：按 GDR 方案 §1.4 A4 与 `shared/global-rules.md` §15，真实业务仓存在在途删除且禁止承受 PoC 写链对任务卡/git 的不可逆变更。
* **M3 硬门实现**：`extensions/pi.ts` 对含任一 P2 写动作的计划在 `/atlas approve-continuation` 与 `atlas_continue` execute（claim 前）**强制校验 `status.onboarding === "done"`**，且 `preflight_finish` 中禁止 `check_structure_freshness` 以 `SKIP` 混过（必须 `PASS`）。P1 纯只读链（`progress`/`status`）保持 M3 收窄口径（`isAtlasProject`）不变。

#### 决策 2：从 `_support/workflow_finish.py` 抽出纯预检，切分四类显式动作面
在 `_support/workflow_finish.py` 抽取零写盘纯函数 `plan_deferred_findings(root, task, t_dir)` 与 `preflight_finish(root, task, *, force=False, require_full_onboarding=False)`：
* **纯预检零写盘保证**：
  * `preflight_finish` **绝不写盘**：不写 `deferred.md`、不写 `attempts.jsonl`、不调 `atlas_change --auto-stage`、不写 `workflow-receipt`、不写 `.adapter-out/`。
  * 对 `topology_required`（原 `_refresh_staged_topology` 调 `refresh_topology` 会写 `.adapter-out/topology/`）：`preflight_finish` 使用只读 `collect_topology(..., source_root=staged_tmp)` + `validate_topology` + `scope_topology_result` 在内存中完成拓扑预检（零写盘），并将 `_refresh_staged_topology` 持久化动作显式移至 `atlas_workflow_finish_deferred`（或当不需要持久化时在 `deferred` 步落盘并纳入 `authorized_write_set`）。
  * 既有 `finish_task()` 复用同一纯函数，保持既有 `atlas workflow finish` CLI 退出码与门禁语义逐字节兼容。
* **P2 封闭动作枚举（加入 `_support/guarded_continuation.py::ALLOWED_TOOLS`，禁 `force`）**：
  * 契约校验：`args` 严格仅允许 `{"unit": unit}`（P2 禁止任何 `force` 参数或字段）。
  1. `atlas_workflow_finish_preflight`（`readOnlyHint: true`，只读启动器 `ATLAS_GC_LAUNCHER`）：运行纯 `preflight_finish(..., require_full_onboarding=True)`，输出 `{unit, review_dir, staged_files, head_before, deferred_plan, expected_archive_rel, receipt_mode, topology_required}`。失败不进入 `UNKNOWN`（零写面），收口为 `CLOSED_FAILED`。
  2. `atlas_workflow_finish_deferred`（`destructiveHint: false`，写链启动器 `ATLAS_GC_WRITE_LAUNCHER`）：显式承载隐写面——按 `deferred_plan` 原子写入 `<t_dir>/deferred.md`（无新条目则记无操作回执）；若 `topology_required`，执行 `_refresh_staged_topology`；若 `receipt_mode == "enforce"`，执行 `build_receipt` + `verify_receipt`。
  3. `atlas_workflow_finish_commit`（`destructiveHint: true`，写链启动器 `ATLAS_GC_WRITE_LAUNCHER`）：最终状态与 git 提交：
     * **原子写入 `task.json`**：设置 `status = "completed"` 及 `e2e_precondition` / `structure_freshness` / `governance_precondition`，计算并落盘 `expected_task_sha256`；
     * **条件 `git commit`**：若 `staged_files` 非空，在**未设置 `GIT_INDEX_FILE`** 下取真实暂存区 `expected_tree = git write-tree`，执行 `git commit -m "chore(workflow): finish <unit>"`（仅提交已冻结暂存区，不执行 `git add`）；若 `staged_files` 为空，跳过 `git commit`（记 `git_commit: "skipped_empty_staged"`）；
     * **提交后期望指纹与非授权树复核**：
       - `task.json` 字节 SHA256 == `expected_task_sha256`；
       - 若执行了 `git commit`：`git rev-parse --verify HEAD^` == `head_before`、`git rev-parse --verify HEAD^{tree}` == `expected_tree`、`staged_files == []`；若跳过 `git commit`：`git rev-parse HEAD` == `head_before` ∧ `staged_files == []`；
       - 同时核验工作树除本动作授权目标外无未预期变更（防项目 `pre-commit` hook 静默篡改工作树）。任一项不符立即转 `UNKNOWN`。
  4. `atlas_workflow_finish_archive`（`destructiveHint: true`，写链启动器 `ATLAS_GC_WRITE_LAUNCHER`）：
     * 写 `INTENT` 记录源目录全部文件清单与 SHA256（`pre_archive_files`）、`expected_archive_dir = .atlas/tasks/archive/<YYYY-MM>/<unit>`、`expected_task_sha256`、`expected_plan_sha256`；
     * 调用带 `dir_fsync` 加固的 `archive_task` 迁入 `expected_archive_dir`，依次 `dir_fsync` 源父目录 `.atlas/tasks/`、月目录与 `archive/` 根目录；
     * **归档后复核**：源目录 `<t_dir>` 已不存在、目标目录存在、`task.json` 哈希 == `expected_task_sha256`、`continuation.json` 哈希 == `expected_plan_sha256`、其余原目录文件逐一守恒。任一项不符立即转 `UNKNOWN`。

#### 决策 3：所有写者共享长生命周期内核锁（`fcntl.flock`，禁一次性 `O_EXCL` 模拟锁）
* **锁文件打开与释放规范（防 `O_TRUNC` 与 inode 分叉）**：
  * 锁路径固定为 `.atlas/runs/continuations/locks/write.lock`（父目录经 `safe_mkdir_nofollow` 建立）。
  * 所有获取方必须以 **`os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW`** 打开（**严禁 `O_TRUNC`**），再调 `fcntl.flock(fd, LOCK_EX | LOCK_NB)`。
  * **仅在 `flock` 成功后**才执行 `os.lseek(fd, 0, os.SEEK_SET)` + `os.ftruncate(fd, 0)` + 写入 `{pid, holder, unit, run_id, token_sha256, acquired_at}` + `os.fsync(fd)` + `fsync_dir(lock_path.parent)`；未拿到锁绝不改写文件内容。
  * 释放时仅 `flock(fd, LOCK_UN)` + `os.close(fd)`，**严禁 `unlink` 锁文件**（避免 POSIX 多 inode 失效）。
* **长生命周期持有与抢占时序**：
  * `atlas_continue` execute 在 **claim 票据和写 `CLAIMED_NO_RUN` 之前**先抢占 `WriteLock`：通过 `node:child_process.spawn` 启动管道绑定子进程 `python3 -I -B .atlas/scripts/atlas_continue.py lock-hold --root <cwd> --unit <unit> --run-dir <runId>`（按 `join(cwd, ".atlas", "scripts", "atlas_continue.py")` 解析，`stdio: ['pipe','pipe','pipe']`），直到收到首行 `LOCKED\n`（`lock-hold` 写 `LOCKED` 后立即 `flush()`）才进入 `claim` 与 `CLAIMED_NO_RUN`；抢锁失败（如外部 CLI 正在写）则保留票据不变、零落盘拒绝！若在收到 `LOCKED\n` 后、移交 `gcPendingAudit` 前发生异常或 `claim` 复检失败，须在 `finally` 中立即关闭 `lock-hold` stdin 释放锁，杜绝残留背景锁进程。
  * 若 Pi 宿主异常崩溃（`SIGKILL`/OOM），stdin 管道 EOF 导致 `lock-hold` 立即退出，**OS 内核自动回收进程并释放 `flock`**。
* **秘密租约通道与重入防自死锁**：
  * `lock-hold` 仅通过 stdout pipe 返回一次性内存 `lock_token` 给 Pi 扩展，`write.lock` 文件只存 `token_sha256`（不明文落盘）。
  * 写链子工具通过异步 `gcLauncherAsync(..., { input: stdinPayload })` 将 `lock_token` 经 **`stdin` pipe** 传给 `atlas_continue.py` 写命令（**严禁经 CLI argv 或环境变量明文传递**），Python 侧校验 `sha256(token) == lock.token_sha256`、`run_id` 匹配且 `os.kill(holder_pid, 0)` 存活。
  * `_support/workflow_finish.py` 的 `finish_task` 与 `archive_task`（接受 `_lock_held: bool = False` 防 `finish_task -> archive_task` 自死锁）及 `scripts/atlas_workflow.py` 写入口（`plan`/`dispatch`/`verify`/`finish`/`archive`/`run`）全部强制获取同一 `WriteLock`；Pi 持有锁期间，任何外部 CLI 写命令立即 `BlockingIOError` 退出（exit 2）。

#### 决策 4：Pi 一次性批准票绑定 `run_id`、二次确认与不可逆显式授权点
* **票据与预检**：
  * `GcTicket` 扩展字段：`runId: string`、`isWrite: boolean`、`irreversibleAck: boolean`。
  * `/atlas approve-continuation <unit>` 先同步校验 `UNIT_RE`（`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`）；对含写动作的计划强制检查 `status.onboarding === "done"`、`ATLAS_GC_LAUNCHER` 与 `ATLAS_GC_WRITE_LAUNCHER` 存在且可执行、无非终态标记（含 `UNKNOWN`/`ISOLATED`/`AUDIT_FAILED`）。
  * 预先生成 `runId = "gc-" + Date.now() + "-" + randomBytes(4).toString("hex")`，**使用 `/tmp` 临时 `gcLog`（并在 `finally` 清理，保证拒签时仓库零字节落盘）** 运行只读 `preflight` 预览受影响写面。
* **两段 UI 确认（不可逆显式授权点）**：
  1. **第一段 `ctx.ui.confirm`**：确认 `unit`、`run_id`、`plan_sha256`、动作清单与 5 分钟一次消费治理窗口；
  2. **第二段 `ctx.ui.confirm`**：显式列出全部不可逆步骤（`deferred` / `task.json completed` / `git commit` / `archive`）及「写启动后非零或不确定即转 `UNKNOWN` 禁止自动重放」，任一段拒签零落盘退出。
* **票据 Claim 与能力校验**：
  * `atlas_continue` execute 在 `claim` 前校验 `UNIT_RE`、`onboarding === "done"`（写链）及两套启动器就位，然后抢占 `lock-hold`，再原子 claim 票据并复核 `ticket.runId === marker.run_id && ticket.irreversibleAck === true`。
  * 调整 `atlas_continue` `annotations` 为 `{ readOnlyHint: false, destructiveHint: true, openWorldHint: false }`（4 个 P2 子工具均为 `exposure: "codemode"`，P1 两只读子工具保持 `readOnlyHint: true`），`tool_call` + 子工具 `execute` 双重能力校验阻断一切直调/跨扩展调用/改参。

#### 决策 5：逐动作 intent/WAL/回执、`UNKNOWN` 不可覆写封锁与崩溃恢复
* **写链 WAL 状态机（`.atlas/runs/continuations/<run_id>/wal.jsonl`，逐行 `fsync` + `dir_fsync`）**：
  1. 父工具在进入首个写动作前设置 `writeStarted = true`（若动作执行期间触发 `AbortSignal`，异步写启动器向子进程发 `SIGTERM`→宽限→`SIGKILL` 并等待退出）。
  2. 每个写子工具 `execute` 通过 `gcCapAuth` 校验后：**① 计算期望指纹 → ② 向 `wal.jsonl` 追加 `INTENT`（含 `action_index`、`action_id`、`tool`、`head_before`、`target_paths`、`expected_fingerprints`）并更新 `isolated/<unit>.json {state:"WRITING"}` → ③ 执行原子写与 `dir_fsync` → ④ 复核期望指纹 → ⑤ 写 `O_EXCL` `raw-receipts/` 并预提交 `gcRawCommits` 返回**（子工具自身**不写 `COMMITTED`**）。
  3. 父工具 `atlas_continue` 在 `ctx.executeTool` 返回并**通过 `threeWayOk`（raw 回执 == 私有台账 == outcome 重算）且 `!outcome.isError` 后**，才调用 `atlas_continue.py wal-commit` 向 `wal.jsonl` 追加 `COMMITTED`（`fsync` + `dir_fsync`）。
  4. **触发 `UNKNOWN` 条件**：只要 `writeStarted === true`，出现任一写子工具返回 `isError` / 非零退出 / 超时 / `AbortSignal` 中断 / `threeWayOk` 失败 / `wal.jsonl` 存在未闭合 `INTENT` 或尾部截断坏行，父工具立即调用 `wal-mark-unknown` 向 `wal.jsonl` 追加 `UNKNOWN` 并持久化 `isolated/<unit>.json {state:"UNKNOWN", run_id, action_index, action_id, reason}`，同步置入 `gcIsolatedUnits`、立即短路后续动作。
* **`UNKNOWN` 不可覆写与禁自动重放硬约束**：
  * **`GC_TERMINAL_STATES = Set(["SUCCEEDED", "CLOSED_FAILED", "REVOKED"])`**：显式将 `UNKNOWN`、`ISOLATED` 与 `AUDIT_FAILED` 排除在自动解锁终态之外（`session_start` 均重建封锁）。
  * **严禁覆写 `UNKNOWN`**：一旦进入 `UNKNOWN`，父工具虽仍落盘 `execution-receipt`（`terminal_reason: "UNKNOWN"`）与封印以便审计取证，但**禁止 `gcWriteMarker` 用 `RECORDED`/`ISOLATED`/`AUDIT_FAILED` 覆写 `UNKNOWN` 标记**；`gcRunAudit` 识别 `verdict === "UNKNOWN"` 或 `wal.jsonl` 含 `UNKNOWN` 时仅落盘诊断摘要，保持 `marker.state === "UNKNOWN"` 与封锁不解锁，并随即关闭 `lock-hold` stdin 管道释放全局 `write.lock`（不阻塞同仓其他健康单元，而当前单元仍由持久 `UNKNOWN` 标记与 `gcIsolatedUnits` 保持封锁）。
  * **`revoke-continuation` 保护**：若 `isolated/<unit>.json` 为 `UNKNOWN`、`ISOLATED`、`WRITING`、`RUNNING`、`RECORDED` 或已绑定 `run_id`，`revoke-continuation` 强制拒绝覆盖，指引走 `/atlas recover-continuation`。
  * **`recover-continuation` 崩溃恢复**：优先检测 `marker.state === "UNKNOWN"` 或 `wal.jsonl` 存在未闭合 `INTENT`/尾行截断/缺失 `execution-receipt.json`：只调用只读 `atlas_continue.py diagnose-unknown`（容错尾部半行，比对最后 `INTENT` 与磁盘/`HEAD` 现态，列明已落/未落目标），经人类 `ctx.ui.confirm` 后仅可写终态 `CLOSED_FAILED (resolved_from_unknown: true)` 解锁，**绝对禁止自动重放任何写动作或自动 `finish`**。

#### 决策 6：TS/Python 双侧 `O_NOFOLLOW`/`dir_fsync`、写集审计、归档路径解析与 git 包装器闭包
* **双侧路径与落盘加固**：Python 侧 `fsync_dir(path)` + `safe_mkdir_nofollow` 覆盖 `write_exclusive`、`write_json_exclusive`、`atomic_write_json`、`wal.jsonl`、`archive_task`（源/月/归档根三目录 `dir_fsync`）及 `isolated` 标记；TS 侧 `gcWriteMarker`、`gcRunDir`、写 `raw-receipts`/`receipt-payload`/`host-record` 统一使用 `lstatSync` 非 symlink 检查（`O_NOFOLLOW`）及文件+父目录 `fsyncSync`。
* **`_tree_entries` 与 `cmd_verify`/`cmd_audit` 写集阶段感知**：
  * `_tree_entries(root, run, unit)` 精确排除 `.atlas/runs/continuations/locks/write.lock` 单文件。
  * **按 `wal.jsonl` 已 `COMMITTED` 阶段派生 `authorized_write_set` 与合法 `task.json` 状态表**：
    * 无 `COMMITTED` 写动作（仅只读/`preflight`）：允许变集 `∅`，`task.json` 在活跃区且 `status == "in_progress"`；
    * `write-deferred` 已 `COMMITTED`：允许集纳入 `<t_dir>/deferred.md`，且当配置启用时纳入 `.atlas/runs/workflow-receipt.json`、`.atlas/runs/workflow-receipt/**`、`.atlas/runs/workflow-review-origin.json`、`.adapter-out/topology*`、`.atlas/spec/structure/global/runtime-topology.md`；
    * `write-commit` 已 `COMMITTED`：允许集纳入 `<t_dir>/task.json`，且合法 `task.status == "completed"`；
    * `write-archive` 已 `COMMITTED`：允许集纳入活跃源目录 `.atlas/tasks/<unit>/**`（迁出删除）与 `wal.jsonl` 记录的 `archived_task_dir/**`（迁入创建，**严禁按 `date.today()` 推算防跨午夜漂移**），`cmd_verify`/`cmd_audit` 从 `archived_task_dir` 读取 `task.json` 与 `continuation.json`。
  * **归档文件守恒与证书路径**：当 `write-archive` 已 `COMMITTED`，`audit` 必须额外核验：① 原活跃区 `.atlas/tasks/<unit>/` 已不存在；② `wal` 记录的 `pre_archive_files` 中除 `task.json`/`deferred.md` 外每个文件在 `archived_task_dir` 存在且 SHA256 相等；③ `archived_task_dir/continuation.json` 哈希 == `plan_sha256`、`task.json` `status == "completed"`；④ `certificate.json` 落盘时记录 `archived_task_dir`、`plan_path_after_archive` 与 `certificate_path`。
* **净化启动器与双 Git 包装器闭包（M1 规则 + `PYTHONDONTWRITEBYTECODE=1`）**：
  * 两套净化启动器在 `env -i` 中**强制导出 `PYTHONDONTWRITEBYTECODE=1`**（同时支持 `stdin` 输入传 `lock_token`）。
  * `/tmp/atlas-p1-frozen/` 保持不动；P2 测试与烟测冻结两套严格包装器（全部拦截前缀模式 `-c*`、`-C*`、`--exec-path*`、`--git-dir*`、`--work-tree*`、`--output*`、`--ext-diff*`、`--textconv*`、`--config-env*`、`;`、`|`，所有自由位置参数 `<REF>`/`<SPEC>`/`<REL>`/`<MSG>` 禁止以 `-` 开头）：
    1. **只读包装器 (`ATLAS_GC_LAUNCHER`)**：精确 `$#` + 逐位白名单覆盖 P1 与 `workflow_finish` 全部实测只读调用：`diff --cached --name-only --diff-filter=ACDMRT -z`、`diff --cached --name-only -z --no-renames`、`diff --cached --raw -z --no-renames --abbrev=(40|64)`、`diff --cached --quiet HEAD -- <REL>`、`diff --cached -U0 --no-renames -- <REL>`、`diff --name-only`、`diff --name-only -z <BASE> <TREE>`、`-c core.quotePath=false diff --name-only`、`-c core.quotePath=false ls-files --others --exclude-standard`、`ls-files -z`、`ls-files --error-unmatch -- <REL>`、`rev-parse HEAD`、`rev-parse --verify <REF>`、`rev-parse --is-inside-work-tree`、`rev-parse --show-object-format`、`rev-parse --git-dir`、`rev-parse <REV>^{tree}`、`show :<REL>` / `show <SPEC>`、`-C <ROOT> status --porcelain -z --untracked-files=all`、`-C <ROOT> show <SPEC>`（`-C <ROOT>` 须 `realpath == ATLAS_GC_ROOT`）、`cat-file -e <OBJ>`、`diff-tree --no-commit-id --name-only -r <REV>`、`ls-tree -r -z --name-only <REV>`、`checkout-index --all --prefix=<TMP>/`（`$# == 3` 且 `<TMP>` 经 `realpath` 解析位于 `/tmp`、`/private/tmp` 或 `$TMPDIR` 内无 symlink）。同时在 `prepare`/`preflight` 拒绝非空 `core.fsmonitor` 或外部 `core.hooksPath`。
    2. **写链包装器 (`ATLAS_GC_WRITE_LAUNCHER`，仅 P2 写工具使用)**：在只读闭包外追加 `write-tree`、`hash-object -w --stdin`（`$# == 3`，仅写链允许、只读包装器禁入）、`commit -m <MSG>`（强制 `$# == 3` 且在 `exec` 前 **`unset GIT_INDEX_FILE GIT_WORK_TREE GIT_DIR`**）、`rev-parse --verify HEAD^`、`rev-parse --verify HEAD^{tree}`；以及当 `GIT_INDEX_FILE` 解析位于临时目录内时放行 `workflow_receipt` 所需临时索引操作（`read-tree`、`update-index`、`diff --cached --binary`、`apply --cached --binary`）。
  * 按方案 §8 边界，本次不在仓内入包 `scripts/atlas_git_readonly`。

### 2.2 最强反方与证伪条件 (Strongest Counterargument & Falsification)
* **最强反方论证**：
  1. **直接 CLI 写入口绕锁或自死锁**：若仅 Pi 端上锁而 `atlas_workflow.py`/`finish_task`/`archive_task` 不共用 `WriteLock`，外部写者仍能撞穿窗口；若未处理嵌套，则 `finish_task` 调 `archive_task` 自死锁。**对策**：全写者入口统一 `WriteLock`（`O_CREAT|O_RDWR|O_NOFOLLOW`，不 `unlink`）+ `_lock_held` 重入标记。
  2. **`UNKNOWN` 状态经旧审计/撤销路径漏网**：若沿用 P1 `AUDIT_FAILED ∈ GC_TERMINAL_STATES` 或无条件 `revoke`，一次伪造/错误撤销即可让未对账的脏写链重新启用。**对策**：`UNKNOWN`/`ISOLATED`/`AUDIT_FAILED` 永不进自动解锁终态，严禁 `RECORDED`/`AUDIT_FAILED`/`revoke` 覆写 `UNKNOWN`，恢复只能走人类显式确认关闭且零自动重放。
  3. **临时索引与 `pre-commit` hook 污染提交树**：若 `write-commit` 未清理 `GIT_INDEX_FILE` 或未核对工作树，真实提交可能错用临时索引或混入 hook 改动。**对策**：写包装器执行 `commit` 前强制 `unset GIT_INDEX_FILE GIT_WORK_TREE GIT_DIR`，提交后同时校验 `HEAD^`、`HEAD^{tree}`、`task.json` 与非授权树哈希。
* **证伪条件（可执行判别检查）**：
  1. `discriminating_check_preflight`: `{command: "python3 -B -m pytest -p no:cacheprovider tests/test_guarded_continuation_p2.py -k preflight", expected_if_false: "preflight 失败路径写入了 deferred.md / attempts.jsonl / task.json / .adapter-out / .pyc"}`；
  2. `discriminating_check_lock`: `{command: "python3 -B -m pytest -p no:cacheprovider tests/test_guarded_continuation_p2.py -k shared_lock", expected_if_false: "持锁期间外部 finish/archive 未被拒绝、O_TRUNC 毁锁、或杀掉 lock-hold 后新写者仍阻塞"}`；
  3. `discriminating_check_unknown`: `{command: "python3 -B -m pytest -p no:cacheprovider tests/test_guarded_continuation_p2.py -k unknown_and_post_commit", expected_if_false: "提交后指纹不符未转 UNKNOWN、revoke/audit 洗白 UNKNOWN、或 recover 自动重放写动作"}`；
  4. `discriminating_check_archive_fsync`: `{command: "python3 -B -m pytest -p no:cacheprovider tests/test_guarded_continuation_p2.py -k 'archive_cert or dir_fsync'", expected_if_false: "归档后 verify/audit 失败、守恒校验漏抓篡改、或父目录未执行 os.fsync"}`。

### 2.3 必须警惕的刺痛代价与兼容性影响 (Trade-offs)
* **P1 默认休眠与向后兼容**：无 `ATLAS_GC_LAUNCHER` / `ATLAS_GC_WRITE_LAUNCHER` 时扩展保持 fail-closed 休眠；P1 只读计划继续只需要 `ATLAS_GC_LAUNCHER` 与 `isAtlasProject`，不破坏 P1 测试与既有 `atlas workflow` CLI 退出码（0/1/2/3/130）。
* **`AUDIT_FAILED` 封锁校准**：将 `AUDIT_FAILED` 移出自动解锁 `GC_TERMINAL_STATES` 对齐 `extensions/pi.ts:1158` 既定契约（「审计失败保持封锁，可 recover 重试审计」）。
* **平台边界与计数棘轮**：依赖 POSIX `flock` 与 `O_DIRECTORY`，Windows 明示不适用；新增 `tests/test_guarded_continuation_p2.py` 将使 `出厂测试文件` 从 103 增至 104，需同步 `ledger_snapshot.py --write`、`docs/map/atlas-map.html` 与 `tests/test_apply_wiring.py`。

---

## 3. 改动面清单 (Affected Surface)

- [ ] **共享内核 (`_support`)**：`_support/workflow_finish.py`、`_support/guarded_continuation.py`
- [ ] **脚本工具 (`scripts`)**：`scripts/atlas_continue.py`、`scripts/atlas_workflow.py`
- [ ] **宿主扩展 (`extensions`)**：`extensions/pi.ts`
- [ ] **测试防线 (`tests`)**：新增 `tests/test_guarded_continuation_p2.py`；更新 `tests/test_apply_wiring.py`
- [ ] **门册、装配核对与导览 (`shared/gates`, `install.py`, `docs/map`, `CHANGELOG`)**：`shared/gates.md`（登记 P2 新门禁行与 M 变异钉）、评估 `install.py` `c()` 自检声明（若需将 `atlas_continue.py`/`guarded_continuation.py` 纳入装配校验则同步重录 golden；否则说明边界）、`scripts/ledger_snapshot.py --write` + `docs/map/atlas-map.html` + `CHANGELOG.md` `[Unreleased]`
- [ ] **自养宿主 (`atlas-playground`)**：补齐 `.atlas/spec/structure/` 非绿地全开户产物（`validate_structure.py` 全绿），仓外 `/tmp` 克隆跑 `--chain --advance-baseline` + D 臂 RPC 真宿主烟测，报告落 `handoff/`

---

## 4. 验证与测试结果 (Verification)

*待复审通过并落刀实施后回填实跑结果：*
* `python3 -B -m pytest -p no:cacheprovider --basetemp /tmp/gc-p2-pytest tests/test_guarded_continuation.py tests/test_guarded_continuation_p2.py tests/test_apply_wiring.py tests/test_canonical_consistency.py tests/test_map_anchors.py`
* 全量 pytest（`test_atlas_verify_playground.py` 单独运行）与 `python3 scripts/atlas_check.py --fast`
* 真宿主 D 臂 RPC 模式烟测（`/tmp/gc-p2-smoke/`，落 `handoff/` 烟测报告）

### 4.5 留出验证（系统性修复触发面核对）
* **触发面核对**：
  * `(a)` Round 1 双评出现 4 组重合 Critical/Major（均已在本版 v2 闭合，非生产运行态同根回归），未引 `duty-review/bugs.md` 子族锚。
  * `(b)` 本批将修改 `_support/workflow_finish.py` 与 `extensions/pi.ts` 门禁相关逻辑；实施落盘后须重跑并粘贴 `git diff --name-only` 与 `python3 scripts/closeout_derive.py --diff-base <ref>` 原始输出，交叉对照 `duty-review/bugs.md` DR4 段级锚确认是否触发 D156 留出集（并在评审侧补充 `真实样本@commit` 与 `应判不中的反例`）。
