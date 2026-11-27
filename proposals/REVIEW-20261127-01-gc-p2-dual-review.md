# 并行对抗评审与四分法处置记录：`RFC-20261127-01`（Guarded Continuation P2 业务写链）

> 评审编号：REVIEW-20261127-01  
> 评审对象：`proposals/RFC-20261127-01-guarded-continuation-p2-write-chain.md`  
> 并行双评输入：同一冻结 v1 提案 + 逐字相同评审指令  
> 独立评审员：Reviewer A（`ea582f64-b062-4a2b-af9d-0446009f70e0`）｜ Reviewer B（`8fc44295-3067-4600-ba64-9d7f6dfdc5ff`）  
> Round 1 结论：双评一致判定**驳回重修**（A: 5 Critical + 5 Major + 2 Minor；B: 4 Critical + 4 Major + 1 Minor）  
> 四分法处置：全部自证面与判断面意见已合流吸收并修订为 `RFC-20261127-01` **v2**，无未决分歧需升级用户。

---

## 一、Round 1 双评合流与四分法处置表

| 编号 | 严重度（取高） | 重合度 | 定位与核心问题 | 四分法归类 | 处置动作（v2 落点） |
|---|---|---|---|---|---|
| F-01 | **Critical** | 双评命中（A-C2, B-1, B-3） | `cmd_verify` 写死全树零变化与 `in_progress`；`write.lock` 未从 `_tree_entries` 排除；`authorized_write_set` 漏原活跃目录迁出与 `workflow-review-origin.json`；缺归档文件守恒与跨午夜日期锚定 | 自证面直接修 | `_tree_entries` 排除 `write.lock`；`verify`/`audit` 按 `wal.jsonl` 已 `COMMITTED` 阶段派生写集与 `task.json` 合法态；按 `wal` 记录 `archived_task_dir` 校验迁出/逐文件 SHA256 守恒 |
| F-02 | **Critical** | 双评命中（A-C1, B-4） | `UNKNOWN` 非终态封锁在 `RECORDED`/`ISOLATED`/`AUDIT_FAILED`/`revoke-continuation` 路径可被覆写；`AUDIT_FAILED` 错放进 `GC_TERMINAL_STATES`；`AbortSignal` 未中断 `spawnSync` | 自证面直接修 | 移出 `AUDIT_FAILED`/`UNKNOWN` 出 `GC_TERMINAL_STATES`；严禁覆写 `UNKNOWN`；`revoke` 对 `UNKNOWN`/已建 `run_id` 拒签；写链改异步 `spawn` 接 `AbortSignal`；`recover` 强制走 `diagnose-unknown` |
| F-03 | **Critical** | 双评命中（A-C3, A-C4, B-2） | 净化启动器未导出 `PYTHONDONTWRITEBYTECODE=1`（子进程校验器产生 `.pyc`）；`preflight` 改调 `check_topology` 与暂存变更冲突；M1 git 白名单遗漏 `workflow_receipt`/`bug_backflow`/`docs_governance`/`semantic`/`legacy_migration` 实测调用 | 自证面直接修 | 两启动器强制导出 `PYTHONDONTWRITEBYTECODE=1`；`topology_required` 预检改只读内存 `collect_topology`，持久化移至 `deferred`；补齐全部实测 git 模板并区分只读 vs 写链+临时索引边界 |
| F-04 | **Critical** | 双评命中（A-C4, B-7） | Git 包装器缺前缀选项拦截（`-c*`/`-C*`/`--git-dir*`/`--work-tree*`）、`checkout-index --prefix` 目录写穿、写链 `commit -m` 未锁 `$# == 3` 及未清 `GIT_INDEX_FILE` | 自证面直接修 | 改用前缀拦截与精确 `$#` 校验；`<REF>/<SPEC>/<REL>/<MSG>` 禁 `-` 开头；`--prefix` 验临时目录规范路径；写 `commit` 前强制 `unset GIT_INDEX_FILE GIT_WORK_TREE GIT_DIR`；`prepare/preflight` 拒非空 `core.fsmonitor`/`hooksPath` |
| F-05 | **Critical** | 双评命中（A-C5, B-5） | `WriteLock` 未禁用 `O_TRUNC` 与 `unlink`（致并发毁锁与多 inode 失效）；`finish_task -> archive_task` 自死锁；`atlas_workflow.py` 其余写入口漏锁；`lock_token` 传参通道与 `gcLauncher` 冲突 | 自证面直接修 | 锁文件仅 `O_CREAT|O_RDWR|O_NOFOLLOW` 打开，获锁后才 `ftruncate` 写入、释放不 `unlink`；`finish_task`/`archive_task` 支持 `_lock_held`；`atlas_workflow.py` 全写命令接锁；`lock_token` 仅经 `stdin` pipe 传入 `gcLauncherAsync` |
| F-06 | **Major** | 双评命中（A-M1, B-5） | `approve` 预览日志写仓内破坏「拒签零落盘」；`claim` 先于 `lock-hold` 导致锁冲突死锁 | 自证面直接修 | `approve` 预览用 `/tmp` 临时 `gcLog` 并清理；`atlas_continue` 先抢 `lock-hold` 后 claim 票据 |
| F-07 | **Major** | 独立命中（A-M2） | `INTENT`/`COMMITTED` 写入方（子 vs 父）时序、WAL 尾行截断容错、`write-commit` 后非授权树未变校验缺失 | 自证面直接修 | 子工具 `execute` 写 `INTENT`，父工具在 `threeWayOk` 后调 `wal-commit`；任何 `writeStarted` 后异常或尾行截断均转 `UNKNOWN`；`write-commit` 复核非授权树未变 |
| F-08 | **Major** | 双评命中（A-M3, B-6） | TS 写盘缺 `O_NOFOLLOW`/`dir_fsync`、`UNIT_RE` 校验、`claim` 前双启动器校验及 `atlas_continue` `annotations` 失真 | 自证面直接修 | TS 侧补全 `UNIT_RE`、`O_NOFOLLOW`+`fsyncSync`、claim 前预检双启动器、校准 `annotations` 为 `readOnlyHint:false, destructiveHint:true` |
| F-09 | **Major** | 双评命中（A-M4, A-N2, B-8） | `atlas-playground` 非绿地 `categories.H` 校验、`--chain --advance-baseline`、隔离克隆 `HEAD` 自指与 `eval host` tag 锁定 | 自证面直接修 | 明确按 `validate_structure` 非绿地全绿开户、克隆副本跑 `--chain --advance-baseline`、钉死 `eval` 注册表 `host_ref: "baseline-post-t5"` |
| F-10 | **Major** | 独立命中（A-M5） | `shared/gates.md` 新门登记、`install.py` `c()` 评估与 D156 触发面核对义务 | 判断面回应留痕 | v2 §3/§4.5 明确增补 `shared/gates.md` 登记、`install.py` 边界评估与实施后 D156 (b) 实跑贴证要求 |
| F-11 | **Minor** | 双评综合（A-N1, B-9） | 空暂存区 `write-commit` 复核 `HEAD == head_before`、禁 `force`、`_support/`/`extensions/` 收口派生盲区与措辞清理 | 自证面直接修 | 均已写入 v2 §2.1 与 §2.2/§3 |

---

## 二、Round 2 复审安排

已将修订后的 `proposals/RFC-20261127-01-guarded-continuation-p2-write-chain.md`（v2）提交两位独立评审员进行 Round 2 核验，确认零遗留 Critical/Major 后再落刀实施。
