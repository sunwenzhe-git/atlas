# 消融事务工具 + 「消融残留」WARN 门（P3 首切片）

> 提案编号：RFC-20261101-04
> 状态：**已确认；P3-a 已合并、P3-b 已实现（待合并）**
> 关联：`research/2026-10-23-ablation-differential.md` §5.1–§5.8（F1–F7 / 四条不变式 / 事务协议 / 三道锁 / 不要做的四件事）、§7 P3；`DESIGN.md` D137、D156、拟 D182
> 影响面：新 `scripts/ablation.py`；改 `scripts/atlas_check.py`；新 `tests/test_ablation.py`；改 `tests/test_atlas_check.py`；`shared/gates.md`、`DESIGN.md`、两处 changelog、`docs/map/*`、`install.sh`（仅自检行）

---

## 0. 评审结论与本版修订（2026-11-01）

只读评审给出 **3 个 Blocker + 若干 Major**；主审抽查确认属实。v2 的修订：

| 评审项 | v1 问题 | v2 修订 |
|---|---|---|
| **B1** | apply 成功后 manifest/active 写失败仍清理 ID 目录 ⇒ before 被删、项目留消融态、无 active | **apply 前**写 `pending` active + 项目 marker；apply 后任何失败**不得删 before**；只有 apply 前的失败才清理；仅在所有路径可安全判定时回滚，否则保留现场并提示 `restore` |
| **B2** | restore 未校验 before 备份就写回；smoke 后不复算哈希 | 写回前逐路径校验 `before` == `manifest.before`；坏备份 ⇒ 零写入、保留 active；写回后复算；smoke 后**再复算**，smoke 写盘 ⇒ `restore_failed` |
| **B3** | mode / symlink / absent / 目录 / 重复路径等价面未定义 | MVP 只接受**现有普通文件的修改/删除**；拒绝 symlink、目录、新增、mode-only、rename/copy/binary；等价面 = `type + sha256 + mode`（文件）/ `absent`（删除后）；`lstat` + `resolve()` containment |
| Major：并发/原子 | 全局 map 无锁；同 root 并发丢 entry；ID 跨项目冲突 | **per-root 状态目录** `<state-root>/roots/<root_hash>/`；`fcntl.flock` 锁；`schema_version/status/owner/root_id`；原子写（temp + fsync + `os.replace`） |
| Major：路径/ID | root/state-root/路径未 realpath | 全部 `resolve(strict=True)` + `commonpath`；ID 白名单 `[A-Za-z0-9._-]+` 且禁止 `..`/`/`；state-root 必须在项目外且 0700 |
| Major：restore 原子性 | 一条冲突时可能已写另一条 | **全路径 preflight**：任一冲突/备份坏 ⇒ 零写入 |
| Major：gate 噪声 | active 未超时也 WARN | healthy active ⇒ **ok + detail**；超时/分叉/manifest/hash/备份异常 ⇒ WARN；无 active + 无 marker ⇒ N/A；永不 FAIL |
| Major：smoke | `true` 可冒充独立验证；`restore_verified` 过度宣称 | smoke 用 argv（无 shell）；begin 先跑 baseline；trivial/缺失 ⇒ `completed_hash_only`（`hash_verified=true, smoke_verified=false`）；smoke 后复算 |
| Major：git/dirty | `git_available=false` 仍放行；dirty 不分面 | root 必须是 git 顶层；git 不可用直接拒绝；**触碰集合内的 tracked dirty 一律拒绝**；`--allow-dirty` 只放行触碰集合外的 dirty 并登记 |
| Major：patch | 解析/原子性不足 | 只允许修改/删除现有普通文件；用 `git apply --numstat -z` 取路径；apply 前后 `git status --porcelain -z` 断言实际变化 ⊆ 触达集合 |
| Major：host/F5 | host_mode 只记录、无消费者 | 记录 `host_mode + host_evidence`，并在 `status`/`plan` 出 `host_warning`（source 不得落 `.atlas/`；adopter 应落 `.atlas/`）；不做自动 F5 门 |
| Major：run/F6 | run 无 timeout/cap；子命令可写项目 | **run 移出 MVP（P3-b）**；begin 打印 `ATLAS_ABLATION_ID`，操作者手工带环境跑；工具证据只落项目外 |
| Major：D156 | §4.5 是承诺不是证据 | 实现批重跑原始命令并粘贴；按 `单案修复（无留出集）` **仅当评审确认**；附 QUEUE 观察行 + 残留风险；不称闭族 |
| 范围 | 全局 map / run / install 互锁过重 | per-root 目录；run/install 互锁/`status --json` 范围见 §7；MVP 只做 begin/restore/status + 内置门 |

**主审抽查（2026-11-01）**：确认 RFC v1 的 apply 后清理、restore 无备份校验、等价面缺失属实；实现后实况计数已核：`tests/` **45** 个测试文件、`tests/test_atlas_check.py` **60** 条、`tests/test_ablation.py` **23** 条、`install.sh` **63** 条 `check`、编排门 **9 类**、M 系至 **M164**（见 §4）。

## 1. 现象与证据

设计文档 §5.3 已有事务协议，但只有手工流程：P5-A 在 `/tmp` 副本里手工拷/删/还原，靠人记 sha256。F1–F3 没有机器载体：

- **F1 忘了装回**：门静默失效；
- **F2 装回但字节不对**：行为微妙改变；
- **F3 期间他人改同一文件**：手工还原覆盖在途工作。

P3 不是「自动消融」，而是把**事务边界**工具化，并让未关闭的消融在下一轮 `atlas_check` 可见（出生 WARN，不 FAIL）。

## 2. 定案（v2 MVP）

### 2.1 范围

**做**：`ablation begin` / `restore` / `status`；`atlas_check` 内置门「消融残留」；项目外状态根；项目内 `.atlas/ABLATION` 提示；三方还原 + 冲突拒绝；独立 smoke；坏输入测试 + M163/M164。

**P3-b 已实现（2026-11-02）**：`run` 子命令（argv 无 shell / timeout / 输出 cap / 环境注入）；`install.sh --update` 的 active 互锁；`host_warning` 进「消融残留」WARN；`--state` 状态面快照/还原。

**不做（永不）**：自动还原；仓内备份；生产级 `ATLAS_ABLATE` 开关；整线束 on/off；自动冲突合并；LLM 分类；`status --json`（保留最小文本输出）。

### 2.2 状态布局（per-root，项目外唯一真相）

```text
<state-root>/roots/<root_hash>/
  active.json            # 单 entry：schema_version/status/owner/root/root_id/id/scope/started/timebox_min
  .lock                  # fcntl.flock
  <ID>/
    plan.json
    before/              # 仅触达路径的逐字节副本
    manifest.before.json
    manifest.after.json
    result.json
    conflict.json        # 仅冲突
```

- `state-root` 默认 `~/.atlas-ablation/`；`--state-root` / `ATLAS_ABLATION_HOME` 覆盖（测试必须用）。
- `root_hash = sha256(realpath(root))[:16]`；`root_id = {st_dev, st_ino}` 防同路径重建。
- `active.json` 是唯一真相；项目内 `.atlas/ABLATION` 只写 `{id, scope, started, timebox_min}`，不是真相。
- 所有 JSON 写入：同目录临时文件 + `fsync` + `os.replace`；状态目录 `0700`；ID 白名单且只在本 root 内唯一。

### 2.3 数据模型（等价面）

- 触达路径只能是**现有普通文件**；`begin` 拒绝：symlink、目录、FIFO/设备、纯新增、mode-only、rename/copy/binary、绝对路径/`..`/symlink 父目录/`.git/`/`.atlas/ABLATION`/state-root 自身。
- 每个路径的 `type` ∈ `file|absent`；`file` 记 `{sha256, size, mode}`；删除后的 `absent` 与空文件分开。
- 重复路径归一化去重；路径来自 `git apply --numstat -z`（目标侧），不手写解析 `a/`/`b/`。
- apply 前后跑 `git status --porcelain -z`，断言实际变化 ⊆ 触达集合；多出路径 ⇒ 中止（不猜测）。

### 2.4 begin（顺序与失败语义）

1. 校验 ID/root/state-root/patch；`root` 必须是 git 顶层（`rev-parse --show-toplevel` == `realpath(root)`）；git 不可用 ⇒ 拒。
2. `git apply --numstat -z` 取路径；校验类型/containment/重复；拒绝不支持形态。
3. 取 `<root_hash>/.lock`（非阻塞）；若已有 active ⇒ 拒。
4. `git status --porcelain`：触碰集合内的 tracked dirty 一律拒；`--allow-dirty` 只放行**触碰集合外**的 dirty 并登记；触碰集合内的 untracked 允许并快照（`lstat` 单独检查，不依赖 git status 显示 ignored）。
5. 写 `plan.json`；写 `active.json` `status=pending` + 项目 marker（原子）；**任何后续失败都保留 before 快照**。
6. 快照 `before/` + `manifest.before.json`；逐文件校验备份哈希；fsync。
7. `git apply --check` → `git apply`。
8. 重算 `manifest.after.json`；断言至少一个路径字节改变、变化集合 ⊆ 触达集合；更新 active `status=active` + after manifest（原子）。
9. 若第 6 步后失败：保留 before/active/marker；只有当所有路径 current==before 或 current==after 且备份校验通过时才做安全回滚；否则保留现场并打印 `ablation restore --id`。只有第 5 步前的失败才清理 ID 目录。

### 2.5 restore（全路径 preflight）

1. 取锁；读 active；校验 schema/root/root_id；active 不存在 ⇒ exit 2。
2. 逐路径校验 `before` 备份 == `manifest.before`（type/hash/mode）；任一不符 ⇒ 零写入、`restore_failed`、保留 active。
3. 逐路径判定：`current == before`（type+hash+mode）⇒ 跳过；`current == after` ⇒ 待写回；其他 ⇒ 冲突。
4. **先完成全部判定**；任一冲突 ⇒ 写 `conflict.json`（哈希 + 统一 diff）、零写入、`aborted`、保留 active、exit 2。
5. 写回 before（内容 + mode；`absent` ⇒ 删除）；重算全部路径 == before；不符 ⇒ `restore_failed`。
6. 运行 smoke（argv，无 shell，cwd=root，注入 `ATLAS_ABLATION_ID`）：
   - begin 时先跑 baseline smoke，必须 rc=0，否则拒绝 begin；
   - smoke argv 不得包含触达路径、scope 字符串或被消融的门名（机判启发式）；`true`/`:`/`exit 0` ⇒ `trivial`；
   - 无 smoke / trivial ⇒ `hash_verified=true, smoke_verified=false`，结果 `completed_hash_only`；
   - smoke rc≠0 ⇒ `restore_failed`；smoke 后**再复算**全部路径，若变化 ⇒ `restore_failed`（`smoke_mutated`）。
7. 全部通过 ⇒ `result.json` `{status: completed|completed_hash_only, hash_verified, smoke_verified, timings}`；删除 active 条目 + 项目 marker；**保留 `<ID>/` 证据目录**。

### 2.6 门「消融残留」（`atlas_check` 内置行，出生 WARN）

读 `ATLAS_ABLATION_HOME`/`~/.atlas-ablation/`，按 `root_hash` 精确查找（`realpath` + `root_id`）：

| 条件 | 状态 |
|---|---|
| state-root 不存在 / 无 active / 无项目 marker | `N/A`（未做实验） |
| 无 active 但有项目 marker | **WARN**（提示残留） |
| active.json 缺失/损坏/不可读/旧 schema | **WARN**（真相不可核） |
| active + marker 缺失/ID 不一致 | **WARN** |
| plan/manifest/`before` 缺失或备份哈希不符 | **WARN** |
| 触达路径 current ∉ {before, after} | **WARN**（第三人改动） |
| 超时未关闭 / `status=pending|restoring|completed` 但 active 在 | **WARN** |
| active + `status=active` + 未超时 + marker/manifest/hash 全一致 | **ok** + detail「消融进行中（剩余 X 分钟）」 |
| 任意坏输入 | **不 FAIL、不崩溃**；显式 WARN |

- 只读：不自动 restore、不写 active/项目；只哈希 manifest 触达路径；单文件 >10MB 记 `too_large` WARN，不读入内存；跨项目用 per-root 目录天然隔离。
- 放置：`atlas_check` 内置行（与 `写面残留`/`结构漂移`/`装配版本` 同型），**不进 `VALIDATORS`**；schema/读取逻辑单源在 `scripts/ablation.py`（`atlas_check` import，不复制）。

### 2.7 status

文本输出：ID、host_mode、scope、开始时间、timebox 剩余/超时、marker 一致性、最近 result；`--root` 过滤；`--json` 后置（MVP 不做）。`host_warning`（source 触达 `.atlas/`、adopter 触达 `.atlas/` 之外）在 status/plan 可见。

## 3. 安全映射（F1–F7）

| 风险 | v2 防护 | 残留 |
|---|---|---|
| F1 | pending active + marker + gate WARN | install `--update` 互锁已实现；`--force` + `ATLAS_ALLOW_ABLATION_OVERWRITE=1` 才越过（显式放弃现场） |
| F2 | before/after sha256 + mode + 备份校验 + 写回复算 + smoke 后复算 | 极端文件系统损坏不可防 |
| F3 | 三方比对 + 全路径 preflight + conflict.json + 拒绝写入 | **同字节的第三人改动不可区分**（如消融删除、第三人也删除 ⇒ current==after）；这是显式盲区 |
| F4 | 真相在项目外；项目内 marker 只是提示 | 项目外 state-root 被人删 ⇒ WARN，不可恢复 |
| F5 | host_mode + host_evidence + status/plan 的 host_warning | **不自动判 F5**；操作者选隔离副本 |
| F6 | `run` 子命令注入 `ATLAS_ABLATION_ID/ROOT`，stdout/stderr/rc 落项目外 runs/ | 子命令仍可自行写项目；工具证据只捕获自身输出 |
| F7 | smoke argv + baseline + 独立性启发式 + smoke 后复算 | `true`/trivial 只能记 `hash_only`，不冒充 F7 |

## 4. 改动面与计数（实况已核）

- 新 `scripts/ablation.py`；新 `tests/test_ablation.py`；改 `scripts/atlas_check.py`、`tests/test_atlas_check.py`。
- `shared/gates.md`：
  - §2.2 新门行「消融残留」（出生 WARN；不查什么；测试文件与条数）；
  - `tests/test_atlas_check.py` 49 → **60 条**；`tests/test_ablation.py` **23 条**；
  - `install.sh` 自检 **62** → **63**（加 `check "消融事务工具" "$ATLAS_DEST/scripts/ablation.py"`）。
- `docs/map/index.md`：编排门 **8 类 → 9 类**；出厂测试文件 **44 → 45**；install 自检 **62 → 63**；`最大单件` 不变（新脚本预计 < 2614 行）。
- `docs/map/gates.md`：**44 文件 → 45**；**M162 → M164**；门全景加「消融残留」行。
- `docs/map/atlas-map.html`：`tests/ 44 文件 → 45`；相关计数同步。
- `DESIGN.md` **D182**；两处 changelog；`tests/test_canonical_consistency.py` / `tests/test_map_anchors.py` / `tests/test_install_selfcheck.py` 负责咬合。
- **不新增共享契约文件**（state schema 在 RFC + `scripts/ablation.py --help`；P3-b 若采用者也需要，再评估新增共享契约）。
- **不新增 `_support` 文件**（避免共享内核计数变化）。

## 4.5 留出验证（D156）

- 本批改门/编排器/契约判据 ⇒ 触发 (b) 命中（计划路径：`scripts/`、`shared/gates.md`、`tests/`、`docs/map`、`DESIGN.md`）。
- **计划阶段原始输出**（2026-11-01；实现批必须重跑并替换）：
  - `git diff --name-only`：空（RFC 尚未跟踪）；
  - `python3 scripts/closeout_derive.py --diff-base HEAD`：`本清单不含语义触发行，正文自查；本轮改动 1 个文件（atlas 自有对账面 0 个；业务面 1 个，只计条数）；[自动] 步骤 1 —— 触发：任一工作单元收尾`。
  - 这是**预判**，不是留出证据；实现批必须附实际 diff/derive 原文、锚→路径族映射、误报。
- 三态：拟 `单案修复（无留出集）`——新增观测门，无既有弱点族可闭；**须评审确认「确无可行留出集」**，不得自称 `闭族`。
- QUEUE 观察行（拟）：
  `- **P3-a 消融残留门观察**（RFC-20261101-04）：owner = P3 实施者；补验期限 = 首个真实事务后 2 周（不晚于 2026-12-15）；升室 = 一次「active 在而门 N/A/静默」或「restore 后 active 未清且门未 WARN」；出室 = 连续 2 次真实事务门行为正确且无误报。`
- 残留风险：install 互锁缺失；F5 未自动化；smoke 可为 trivial；active.json 损坏不可恢复；同字节第三人改动不可区分；gate 在坏输入下可能噪声。

## 5. 测试与 M 钉（实现批）

### 5.1 `tests/test_ablation.py`（新）

- begin：修改/删除（现有普通文件）；快照/manifest/active/marker；host_mode/host_evidence；触碰集合内 tracked dirty 拒；触碰集合外 dirty + `--allow-dirty` 放行；untracked 触碰快照；patch 越界/绝对/`..`/symlink/目录/新增/mode-only/rename/copy/binary 拒；同 root 重复 begin 拒；state-root 在项目内/`0700` 拒；ID 非法拒；`git_available=false` 拒。
- 半截状态：apply 后 manifest/active 写失败 ⇒ before 保留、pending/active 可见、restore 可执行；apply 前失败 ⇒ 清理 ID。
- restore：current==after → before；current==before → no-op；第三人改动 → conflict.json + 零写入 + active 保留 + exit 2；两路径一冲突一可还原 ⇒ **两条都不写**；备份损坏 ⇒ 零写入 + 保留；写回失败 ⇒ 保留 active 可续跑；smoke baseline 非 0 拒 begin；smoke 失败 / smoke 写盘 ⇒ `restore_failed` + active 保留；smoke 通过 ⇒ completed；trivial/无 smoke ⇒ completed_hash_only；模式恢复；删除文件恢复；mode/symlink/absent 覆盖。
- status：无 active / active / 超时 / marker 分叉 / host_warning。
- 并发：两进程 begin，一胜一负；跨 root 同 ID 不共享目录。
- 所有测试用临时 git 仓 + 临时 state-root/HOME；不写真实 `~`。

### 5.2 `tests/test_atlas_check.py`（改）

- 无 active + 无 marker ⇒ N/A；
- 无 active + marker ⇒ WARN；
- healthy active（未超时、全一致）⇒ **ok + detail**；
- 超时 ⇒ WARN；marker 缺失/不一致 ⇒ WARN；plan/manifest/before 缺失或坏 ⇒ WARN；第三人改动 ⇒ WARN；active.json 损坏/旧 schema/state-root 不可读 ⇒ WARN；跨 root ⇒ N/A；`status=pending/restoring/completed` 但 active 在 ⇒ WARN；
- 任意坏输入**永不 FAIL、不崩溃**；gate 不写项目。

### 5.3 M 钉 + 额外安全钉（四段协议，注入只在 `/tmp` 副本）

- **M163**（属 `tests/test_atlas_check.py`）：从 `atlas_check.main()` 摘掉 `check_ablation_residue` 调用 ⇒ healthy/超时/marker 等门用例红；**正例对照**：无 active 的干净项目 gate 行 N/A、无 FAIL。
- **M164**（属 `tests/test_ablation.py`）：把 restore 的三方比对退回「无条件写回 before」⇒ 冲突用例红；**正例对照**：正常 restore 仍绿。
- 额外安全钉：备份损坏 ⇒ restore 零写入；apply 后 active/manifest 写失败 ⇒ before 保留；smoke 写盘 ⇒ 复算失败。
- 四段：基线绿 → 注入红（记录红集）→ sha256 逐字节还原 → 复绿；日志 `/tmp/atlas-rfc04-evidence/`；注入前建临时 git 仓/临时 HOME，不触活仓。

## 6. 非目标 / 残留风险（v2）

- 自动还原、仓内备份、`ATLAS_ABLATE` 开关、整线束 on/off、自动冲突合并、LLM 分类：不做。
- `run` 子命令：P3-b 已实现（argv 无 shell、timeout、64KB 输出 cap、runs/ 证据）。
- `install.sh --update` 互锁：P3-b 已实现并实测（active 时 rc=2；`--force` + `ATLAS_ALLOW_ABLATION_OVERWRITE=1` 才放行）。
- host_mode：`host_warning` 已进「消融残留」门（WARN）；仍不做自动 F5 阻断。
- F3 同字节第三人改动不可区分（显式盲区）；smoke trivial 不冒充 F7；active.json 损坏只能 WARN，不能恢复。
- `status --json` 后置；若未来采用者也需要共享契约，再评估新增；`_support` 不新增文件。

## 7. 已确认决策（2026-11-02，均按推荐实现）

1. **MVP 范围**：按 §2.1（begin/restore/status + 内置门；run/install 互锁/host F5 门后置）是否同意？
2. **healthy active 的门状态**：推荐 **ok + detail**（WARN 只留超时/分叉/hash/备份/manifest 异常）；若坚持每轮 WARN，请明确「可见性优先」。
3. **smoke**：推荐「结构化 argv + begin baseline + smoke 后复算；无 smoke/trivial ⇒ `completed_hash_only`，不冒充 F7」；是否接受？
4. **D156 三态**：推荐 `单案修复（无留出集）` + QUEUE 观察行 + 残留风险，不称闭族；是否同意？

## 8. 实施顺序（确认后）

1. `scripts/ablation.py` + `tests/test_ablation.py`（工具：begin/restore/status；状态模型/锁/原子写/全路径 preflight）。
2. `atlas_check` 内置门 + `tests/test_atlas_check.py`（N/A/ok/WARN/永不 FAIL）。
3. M163/M164 + 额外安全钉四段协议（`/tmp` 副本）。
4. 同步 `shared/gates.md` 计数/行、`DESIGN.md` D182、两处 changelog、`docs/map/*`、`install.sh` 自检行。
5. 全量 `pytest tests/ -q` + 只读复核；用户确认后再合并（合并/push 仍需单独授权）。

## 9. P3-b 实施补记（2026-11-02）

- `run`：argv 无 shell、timeout、64KB 输出 cap、`ATLAS_ABLATION_ID/ROOT` 注入、`runs/` 证据。
- `install.sh --update`：active 时拒绝（`--force` + `ATLAS_ALLOW_ABLATION_OVERWRITE=1` 才越过）；真实 dry-run 实测 rc=2 / rc=0。
- host F5：`active.host_warning` ⇒ 门 WARN。
- `--state`：运行期产物快照/还原（不参与三方冲突；`restore` 记 `state_restored`）。
- 测试：`tests/test_ablation.py` **23**、`tests/test_atlas_check.py` **60**；M163/M164 四段协议 + run/state/host/install 用例。
