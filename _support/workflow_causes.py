#!/usr/bin/env python3
"""workflow 失败原因封闭词表 + 尝试预算 + 退出码分配（RFC-20261122-07，单源模块）。

三件事：
1. **cause 封闭词表（双轨）**——`charged`（扣预算）=「需实现侧动作（改码 / 改文档 /
   履行申报义务）才能过」的失败；`uncharged`（不扣）= 前置态 / 流程顺序 / 环境 / 留痕。
   词表外一律 `unclassified` 保守扣（宁可误拦不可误放，评审 E 轮 fallback 规则）。
2. **退出码封闭分配**——0=OK / 1=判定失败·门红 / 2=用法或前置不满足 / 3=预算超限暂停 /
   130=中断（SIGINT 信号死亡天然产生，无 die() 路径发出；SIGTERM=143 落不分配区）。
   4–129 与 131+ 不分配。**同一位点（如 finish 的 FinishError）不同 cause 不同码**：
   门红 1、前置/顺序/环境 2、预算 3。
3. **attempts.jsonl 记账**——单写者 = `workflow verify` / `finish` 失败路径与预算拒绝
   路径；`plan`/`dispatch`/`archive` 失败不入记账、不占预算、无 paused_reason
   （RFC-20261122-07 §3.1.1 显式排除）。读侧 fail-soft：跳过不可解析行并返回坏行数。

红线（RFC-20261122-07 N1/N2）：预算与原因全部落 D204 三态状态机**之外**（不新增第四态）；
预算超限的语义 = 停下要求人工（退出码 3 + `budget_exceeded` 留痕行），不是放行/跳过。
配置面 = `.atlas/config.yaml` 的 `workflow.max_verify_attempts`（install 建模板，
--update 保留；无文件/无键/坏值/非正值 ⇒ 缺省 2，fail-soft）。
纯标准库。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ─────────────────────────────── 退出码封闭分配 ───────────────────────────────

EXIT_OK = 0
EXIT_GATE_FAIL = 1          # 判定失败（门红/扣预算失败）
EXIT_USAGE = 2              # 用法错误 / 前置不满足 / 环境异常 / 流程顺序
EXIT_BUDGET = 3             # verify 尝试预算超限暂停（要求人工）
EXIT_INTERRUPTED = 130      # SIGINT 信号死亡天然产生；无 die() 路径发出本码
# 4–129 与 131+ 不分配（SIGTERM=143 天然落在不分配区）。

# ─────────────────────────────── cause 封闭词表（双轨） ───────────────────────

# cause -> charged。True = 扣预算（实现侧需改代码才能过）；False = 不扣（前置/顺序/环境/留痕）。
CAUSES: dict[str, bool] = {
    # 扣预算：门红 / 检查未过
    "blocking_critical": True,       # verify：审查报告（含 --check-cmd 并轨段）未过（rc==1）
    "verify_command_failed": True,   # --check-cmd 确定性检查非 0（D203 ③ 同轨；并轨后并入报告）
    "review_not_passed": True,       # finish：报告存在但 status ≠ PASS（WARN/FAIL 均阻断）
    "scope_stale": True,             # finish：v4 内容封口红（实审内容已变 / 产物误入暂存面）
    "freshness_fail": True,          # finish：结构事实新鲜度门红（RFC-20261122-05）
    "e2e_red": True,                 # finish：E2E 关联用例 red（agent-pointer 口径）
    "mechanism_undeclared": True,    # verify：机制篇触及未跟改未申报（RFC-20261123-01）
    "mechanism_paths_invalid": True,  # verify：机制篇 mechanism-paths 词表非法（RFC-20261123-01）
    "migration_integrity": True,
    "contract_stale": True,
    "incident_evidence_missing": True,
    "incident_not_resolved": True,
    "docs_stale": True,
    "docs_owner_missing": True,
    "topology_stale": True,
    "receipt_stale": True,
    "bug_backflow_stale": True,       # finish：缺陷实现 diff 或回推产物已变化
    "bug_backflow_invalid": True,     # finish：缺陷台账/schema/决策/审查锚非法
    # 不扣预算：前置态 / 顺序 / 环境 / 留痕
    "migration_unverified": False,
    "contract_unverified": False,
    "incident_unverified": False,
    "docs_unverified": False,
    "topology_unverified": False,
    "receipt_unverified": False,
    "calibration_unverified": False,
    "staged_empty": False,           # verify：实现未暂存（前置态）
    "bug_backflow_missing": False,    # finish：缺陷未执行 atlas bug / 缺台账
    "bug_backflow_pending": False,    # finish：回推待完成或待签字
    "bug_backflow_unstaged": False,   # finish：record/回推文档未暂存
    "bug_backflow_worktree_diverged": False,  # finish：index 与工作树分叉
    "bug_backflow_unsupported_object_type": False,  # bug/finish：symlink/gitlink/type-change
    "bug_backflow_mode_not_finish_ready": False,    # finish：range 记录改 staged 重跑
    "no_task_card": False,           # 对账本外 / 非法 / 越界任务收口或派发
    "state_transition": False,       # 流程顺序错（未 completed 先归档、归档目标已存在等）
    "no_review_report": False,       # 审查报告缺失 / 会话待审 PENDING（流程顺序）
    "environment": False,            # 底层异常（git 不可用 / OSError / 报告损坏不可读）
    "budget_exceeded": False,        # 预算超限拒绝事件本身（不计数、只留痕；cmd 写死 'verify'）
}
FALLBACK_CAUSE = "unclassified"      # 词表外一律保守扣（fallback）
CHARGED_DEFAULT = True

# 闭环性自检（模块加载即断言；防词表手滑写出第三态值）
assert all(isinstance(v, bool) for v in CAUSES.values()), "cause 词表必须双轨布尔"


def is_charged(cause: str) -> bool:
    """cause 是否扣预算；词表外保守扣（unclassified 语义）。"""
    return CAUSES.get(cause, CHARGED_DEFAULT)


def exit_code_for(cause: str) -> int:
    """cause → 退出码：budget_exceeded ⇒ 3；扣预算（含 fallback）⇒ 1；不扣 ⇒ 2。"""
    if cause == "budget_exceeded":
        return EXIT_BUDGET
    return EXIT_GATE_FAIL if is_charged(cause) else EXIT_USAGE


# ─────────────────────────────── attempts.jsonl 记账 ──────────────────────────

def attempts_path(tasks_root: Path, unit: str) -> Path:
    """任务卡 attempts 台账落点（随卡归档，历史保留）。"""
    return Path(tasks_root) / unit / "attempts.jsonl"


def record_attempt(tasks_root: Path, unit: str, *, cmd: str, cause: str) -> dict:
    """追加一行 `{ts, unit, cmd, cause, charged}`（单写者 = verify/finish 失败与预算拒绝路径）。

    词表外 cause 归 fallback（保守扣）。写失败只 WARN 不反噬主流程（观测面纪律）。
    返回写入的行（供调用方复用）。"""
    cause = cause if cause in CAUSES else FALLBACK_CAUSE
    row = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "unit": unit,
        "cmd": cmd,
        "cause": cause,
        "charged": is_charged(cause),
    }
    path = attempts_path(tasks_root, unit)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"WARN（attempts 记账失败）: {exc}", file=sys.stderr)
    return row


def load_attempts(tasks_root: Path, unit: str) -> tuple[list[dict], int]:
    """fail-soft 读 attempts 台账：跳过不可解析行（半行 JSON 等），返回 `(行列表, 坏行数)`。

    缺文件 ⇒ `([], 0)`（旧卡零回填，RFC-20261122-07 §5.3）。"""
    path = attempts_path(tasks_root, unit)
    if not path.is_file():
        return [], 0
    rows: list[dict] = []
    bad = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(data, dict):
            rows.append(data)
        else:
            bad += 1
    return rows, bad


def charged_count(tasks_root: Path, unit: str) -> int:
    """扣预算失败计数（预算判据口径：只认 `charged is True` 的行）。"""
    rows, _bad = load_attempts(tasks_root, unit)
    return sum(1 for r in rows if r.get("charged") is True)


# ─────────────────────────────── workflow 参数配置 ────────────────────────────

DEFAULT_MAX_VERIFY_ATTEMPTS = 2   # 对齐 D203 审修循环上限 2 的既有口径（RFC-20261122-07 §8-1）

_MAX_ATTEMPTS_RE = re.compile(r"^\s*max_verify_attempts\s*[:=]\s*(\d+)\s*$", re.MULTILINE)


def max_verify_attempts(root: Path) -> int:
    """`.atlas/config.yaml` 的 `workflow.max_verify_attempts`；fail-soft 缺省 2。

    只认缩进层下的该键（install 模板注释注明「未知键被忽略」）；无文件 / 无键 /
    坏值 / 非正值（0 或负——写 0 等于关掉预算变放行，违反 N2）一律回缺省。"""
    path = Path(root) / ".atlas" / "config.yaml"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return DEFAULT_MAX_VERIFY_ATTEMPTS
    m = _MAX_ATTEMPTS_RE.search(text)
    if not m:
        return DEFAULT_MAX_VERIFY_ATTEMPTS
    try:
        value = int(m.group(1))
    except ValueError:  # pragma: no cover —— 正则已保证数字，防御性保留
        return DEFAULT_MAX_VERIFY_ATTEMPTS
    return value if value >= 1 else DEFAULT_MAX_VERIFY_ATTEMPTS
