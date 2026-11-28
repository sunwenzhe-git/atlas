#!/usr/bin/env python3
"""Atlas Workflow Finish —— 收口校验与账本流转引擎 (Phase Finish)。

职责：
1. 校验当前任务是否已通过独立审查（检查对应任务目录下或 reviews/ 下的 `review.json` 证明）；
2. 校验确定性测试/门禁是否全绿，无未解决的 Critical/Major findings；
3. 将任务状态原子流转至 `completed`；
4. 检查 DAG 中全部任务：若所有工作单元均已 completed，执行全局收口归档。

纯标准库实现。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path

from _support import review_scope_core as scope_core
from _support.bug_backflow import validate_backflow
from _support.docs_governance import DocsGovernanceError, check_docs_for_ids, docs_mode
from _support.guarded_continuation import WriteLock, WriteLockError, fsync_dir
from _support.incident import IncidentError, configured_mode as incident_mode, validate_task_incidents
from _support.layout import LayoutError, load_layout
from _support.runtime_topology import (
    TopologyError, collect_topology, refresh_topology, scope_topology_result,
    topology_mode, validate_topology,
)
from _support.semantic_contracts import SemanticError
from _support.workflow_receipt import (
    ReceiptError, _classification_result, _staged_scope_digest,
    build_receipt, receipt_mode, validate_workflow_origin, verify_receipt,
)
from _support.governance_schema import canonical_digest
from _support.workflow_plan import (
    ARCHIVE_DIR, REQUIREMENT_ITEMS_FILE, REQUIREMENT_TYPES, PlanError, is_archived_task_dir,
    load_tasks,
    atomic_write_json, normalize_requirement_ref, requirement_relation_findings,
    requirement_type, resolve_requirement_root, strip_fences, UNIT_RE,
)
from _support.workflow_causes import FALLBACK_CAUSE
from _support.workflow_verify import SOURCE_REF_RE, first_table


class FinishError(ValueError):
    """收口校验异常。

    `cause` 为 RFC-20261122-07 失败原因词表成员（缺省 `unclassified` = 保守扣预算，
    fallback 规则）；调用方按 `cause` 分流退出码（同一位点不同 cause 不同码）。"""

    def __init__(self, msg: str, cause: str | None = None):
        super().__init__(msg)
        self.cause = cause


REVIEW_DIR_PREFIX_RE = r"^\d{4}-\d{2}-\d{2}-impl-review-"

# 审查证据命名契约单源（RFC-20261122-02）：目录 `<date>-impl-review-<unit>/findings/<unit>.r<N>.json`。
# 取号（当日）与跨日扫描（进度探针）双方 import 同一构造，命名契约改名时全部消费点自动跟随。
_REVIEW_DIR_NAME_RE = re.compile(REVIEW_DIR_PREFIX_RE + r"(.+)$")
_FINDINGS_FILE_TMPL = "{unit}.r{round}.json"


def review_findings_dir(root: Path, day: str, unit: str) -> Path:
    """某日某任务的审查 findings 目录构造（`_next_review_round` 取号用）。"""
    return root / "product" / "reviews" / f"{day}-impl-review-{unit}" / "findings"


def scan_review_rounds(root: Path, unit: str, *,
                       day: str | None = None) -> list[tuple[str, int, Path]]:
    """跨日扫描某任务的审查轮次文件，按（目录日期, 轮号）升序。

    轮号按日重置（每日目录独立取号），跨日轮次不连续——消费方不得直接对轮号求和。
    `day` 限定单日（当日取号用）；缺省扫全部日期（进度探针用）。
    返回 `(date_str, round, findings_file_path)` 三元组列表。
    """
    base = root / "product" / "reviews"
    if not base.is_dir():
        return []
    rounds: list[tuple[str, int, Path]] = []
    for d in sorted(base.iterdir()):
        m = _REVIEW_DIR_NAME_RE.fullmatch(d.name)
        if not m or m.group(1) != unit or not d.is_dir():
            continue
        date_str = d.name[:10]
        if day is not None and date_str != day:
            continue
        fdir = d / "findings"
        if not fdir.is_dir():
            continue
        pat = re.compile(rf"{re.escape(unit)}\.r(\d+)\.json")
        for p in fdir.iterdir():
            fm = pat.fullmatch(p.name)
            if fm:
                rounds.append((date_str, int(fm.group(1)), p))
    return sorted(rounds, key=lambda t: (t[0], t[1]))


def staged_files(root: Path) -> list[str] | None:
    """暂存区文件清单；`None` = git 不可用/非 git 仓库（与「暂存为空」`[]` 区分）。

    RFC-20261122-02：提升为公共入口，workflow_progress 探针复用同一读面（吞错口径单源）。
    """
    try:
        pr = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACDMRT", "-z"],
            cwd=str(root), capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if pr.returncode != 0:
        return None
    return [item for item in pr.stdout.split("\0") if item]


def _scope_matches(root: Path, data: dict, *,
                   allowed_extra: set[str] | None = None) -> tuple[bool, str]:
    """检查报告落盘后暂存区内容未被替换（v4 内容封口）。

    三分类诊断（2026-11-21，自进化 campaign T3 三撞实测）：extra（暂存面多出实审集
    之外的路径——典型 = 审查产物误入暂存）/ missing（实审文件未暂存）/ changed
    （实审文件内容已变）。extra 全落审查产物目录 ⇒ 指引 unstage（该场景重跑
    verify 无效）；changed ⇒ 指引重新审查。整体摘要一致即放行（快速路径）。
    """
    scope = data.get("review_scope")
    if not isinstance(scope, dict) or not scope.get("sha256"):
        if allowed_extra:
            return False, "缺陷 finish 要求带 sha256 的 v4 review_scope"
        return True, ""  # 旧报告兼容：无内容锚，无法比对
    if allowed_extra and data.get("schema_version") != 4:
        return False, "缺陷 finish 要求 schema_version=4 审查报告"
    staged = staged_files(root)
    if staged is None:
        return False, "无法读取暂存区，不能确认审查内容未被替换（请在 git 仓库内重跑 verify）"
    try:
        # review_scope 的 sha256 是「审查时的暂存内容」锚：生成侧一直按 index
        # 哈希（见 workflow_receipt._staged_scope_digest）。旧报告可能省略
        # hash_source；缺省若回退 worktree，Windows 的 autocrlf 会让同一 staged
        # 内容在工作区呈现不同字节并误判为审查后变化。
        hash_source = scope.get("hash_source", "index")
        head_ref = "INDEX" if hash_source == "index" else scope.get("head")
        if hash_source == "index" and _staged_scope_digest(root, staged) == scope.get("sha256"):
            return True, ""
        manifest = scope_core.build_manifest(root, staged, head=head_ref,
                                             hash_source=hash_source)
    except Exception as exc:  # noqa: BLE001 —— 路径/状态异常一律视为不可封口
        return False, f"暂存区内容无法重算摘要：{exc}"
    if manifest.get("scope_sha256") == scope.get("sha256"):
        return True, ""
    files = scope.get("files") or []
    if not files:
        return False, ("审查后暂存区内容已变化（review_scope 摘要不一致；旧报告无逐文件锚，"
                       "无法自动分类）：实审文件内容已变 ⇒ 须重新审查（fresh review）后重跑 "
                       "verify；实审文件未变 ⇒ 通常是审查产物误入暂存面，unstage 后重跑 finish")
    recorded = {f.get("path"): f.get("sha256", "") for f in files
                if isinstance(f, dict) and f.get("path")}
    review_prefixes = ("product/reviews/", "product/e2e/reviews/")
    extra = sorted(set(staged) - set(recorded))
    missing = sorted(set(recorded) - set(staged))
    changed = []
    for p in sorted(set(recorded) & set(staged)):
        try:
            m = scope_core.build_manifest(root, [p], head=head_ref,
                                          hash_source=hash_source)
        except Exception:  # noqa: BLE001
            changed.append(p)
            continue
        entry = (m.get("files") or [{}])[0]
        if entry.get("sha256") != recorded.get(p):
            changed.append(p)
    extra_review = [q for q in extra if q.startswith(review_prefixes)]
    extra_bug = [q for q in extra if q in (allowed_extra or set())]
    extra_other = [q for q in extra if not q.startswith(review_prefixes) and q not in (allowed_extra or set())]
    parts = []
    if extra_review:
        parts.append("审查产物不得进暂存面：`git restore --staged "
                     + " ".join(extra_review)
                     + "` 后重跑 finish（实审文件未变时重跑 verify 无效）")
    if extra_other:
        parts.append("暂存面多出实审集之外的非审查产物路径：" + " ".join(extra_other)
                     + "（纳入实审需重新审查）")
    if missing:
        parts.append("实审文件未暂存：" + " ".join(missing) + "；暂存后重跑 verify")
    if changed:
        parts.append("实审文件内容已变（" + " ".join(changed)
                     + "）：须重新审查（fresh review）后重跑 verify")
    if not parts and extra_bug:
        return True, ""
    if not parts:
        parts.append("暂存面与实审集内容均一致但整体摘要不一致（罕见）；请重跑 verify")
    return False, "；".join(parts)


def check_task_review_passed(root: Path, unit: str, *,
                             bug_artifacts: set[str] | None = None) -> tuple[bool, str, str]:
    """检查指定任务是否已产出合规的 review.json 且未被拦截；返回 `(passed, reason, cause)`。

    `cause` 为 RFC-20261122-07 失败原因词表成员：报告缺失/未执行 ⇒ `no_review_report`
    （不扣，流程顺序）；报告损坏不可读 ⇒ `environment`（不扣，文件级异常）；status ≠ PASS
    或 ok=false ⇒ `review_not_passed`（扣）；内容封口红 ⇒ `scope_stale`（扣）。"""
    root = root.resolve()
    # 查找匹配的 review 报告目录
    reviews_dir = root / "product" / "reviews"
    if not reviews_dir.is_dir():
        return False, "未找到 product/reviews 目录（尚未执行独立审查）", "no_review_report"

    candidates = sorted(
        p for p in reviews_dir.iterdir()
        if p.is_dir() and re.fullmatch(
            REVIEW_DIR_PREFIX_RE + re.escape(unit) + "$", p.name)
    )
    if not candidates:
        return False, f"未找到任务 {unit} 的审查报告（须先执行 atlas review --unit {unit} --staged）", "no_review_report"

    latest_dir = candidates[-1]
    review_file = latest_dir / "review.json"
    if not review_file.is_file():
        return False, f"报告目录 {latest_dir.name} 缺少 review.json", "no_review_report"

    try:
        data = json.loads(review_file.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"读取 {review_file} 失败：{exc}", "environment"

    # 检查 review.json 是否合规且无阻塞项。字段口径以 cli_review_convert 的实际产出为准：
    # `status ∈ {PASS, WARN, FAIL}` + `ok` —— PASS 已由 `review_policy.calculate_status` 保证
    # 「无阻断 Critical、无 Major、无 M≠N 等下限」，此处不重复实现严重度判定（判据单源）。
    status = str(data.get("status") or "").strip().upper()
    if status != "PASS":
        return False, f"审查报告状态未通过（status: {data.get('status')}；收口需 PASS，WARN/FAIL 均阻断）", "review_not_passed"
    if data.get("ok") is False:
        return False, "审查报告 ok=false（存在未解决的阻断问题）", "review_not_passed"

    matched, why = _scope_matches(root, data, allowed_extra=bug_artifacts)
    if not matched:
        return False, why, "scope_stale"

    return True, str(latest_dir), ""


# ───────────────── 存量缺陷登记 deferred（RFC-20261122-07 §3.1.3）─────────────────

DEFERRED_FILE = "deferred.md"
DEFERRED_HEADER = (
    "# 存量缺陷登记（deferred；RFC-20261122-07 §3.1.3）\n\n"
    "来源 = 最新轮独立审查报告的 `pre_existing` 未关闭 findings；"
    "状态闭集复用 D154（开放｜已修·待复验｜已出库）。只登记不分诊（消费归巡检/人工节奏）。\n"
)
# D154 状态闭集（与 duty-review/bugs.md 制式段同源）：本登记面只产出「开放」，
# 推进到「已修·待复验 / 已出库」由人工编辑。
DEFERRED_STATUS_CLOSED = ("fixed", "false_positive", "intentional", "ignored")
_DEFERRED_OPEN_RE = re.compile(r"^-\s+DW-\d+\s*〔[^〕]*｜开放")
_DEFERRED_ID_RE = re.compile(r"DW-(\d+)")


def _deferred_key(check: dict) -> str:
    """幂等去重键：fingerprint 优先（审查契约中为可选字段，v2 推荐），缺省回退
    `target + check 名 + detail` 的 sha256 前 16 位（复核轮 Nit 修正）。"""
    fp = str(check.get("fingerprint") or "").strip()
    if fp:
        return f"fp={fp}"
    raw = "|".join(str(check.get(k) or "") for k in ("target", "check", "detail"))
    return f"k={hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def deferred_open_count(t_dir: Path) -> int:
    """deferred.md 中状态「开放」的条目数（`workflow status` 聚合口径；文件缺失 ⇒ 0）。"""
    p = Path(t_dir) / DEFERRED_FILE
    if not p.is_file():
        return 0
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    return sum(1 for ln in text.splitlines() if _DEFERRED_OPEN_RE.match(ln.strip()))


def plan_deferred_findings(root: Path, task: dict, t_dir: Path) -> dict:
    """只读计算最新轮审查报告中待登记的存量缺陷，不写磁盘。"""
    root = Path(root).resolve()
    reviews_dir = root / "product" / "reviews"
    unit = str(task.get("id") or "")
    deferred_path = Path(t_dir) / DEFERRED_FILE
    empty = {
        "registered": 0,
        "blocking": 0,
        "deferred_path": str(deferred_path),
        "content": None,
        "shown": "",
    }
    if not reviews_dir.is_dir() or not unit:
        return empty
    candidates = sorted(
        p for p in reviews_dir.iterdir()
        if p.is_dir() and re.fullmatch(
            REVIEW_DIR_PREFIX_RE + re.escape(unit) + "$", p.name)
    )
    if not candidates:
        return empty
    try:
        data = json.loads((candidates[-1] / "review.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    checks = data.get("checks") or []
    if not isinstance(checks, list):
        return empty
    round_no = str(data.get("round") or "").strip()
    if deferred_path.is_file():
        try:
            existing = deferred_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return empty
    else:
        existing = DEFERRED_HEADER
    next_no = 1 + max((int(m.group(1)) for m in _DEFERRED_ID_RE.finditer(existing)),
                      default=0)
    registered = 0
    blocking = 0
    lines: list[str] = []
    for c in checks:
        if not isinstance(c, dict) or c.get("pre_existing") is not True:
            continue
        disposition = str(c.get("disposition") or "open").strip().lower()
        if disposition in DEFERRED_STATUS_CLOSED:
            continue
        key = _deferred_key(c)
        if key in existing:
            continue
        level = str(c.get("level") or "unknown").strip() or "unknown"
        detail = " ".join(str(c.get("detail") or "").split()) or "（无描述）"
        target = str(c.get("target") or "").strip()
        round_tag = f" r{round_no}" if round_no else ""
        loc = f"（{target}）" if target else ""
        lines.append(
            f"- DW-{next_no} 〔{date.today().isoformat()}｜开放｜族:{level}｜证:{key}{round_tag}〕"
            f"{detail}{loc}")
        if level in ("Critical", "Major"):
            blocking += 1
        next_no += 1
        registered += 1
    if not registered:
        return empty
    try:
        shown = deferred_path.resolve().relative_to(root).as_posix()
    except ValueError:
        shown = str(deferred_path)
    return {
        "registered": registered,
        "blocking": blocking,
        "deferred_path": str(deferred_path),
        "content": existing.rstrip("\n") + "\n" + "\n".join(lines) + "\n",
        "shown": shown,
    }


def extract_deferred_findings(root: Path, task: dict, t_dir: Path) -> dict:
    """把最新轮审查报告的存量缺陷（`pre_existing` ∧ 未关闭）登记进任务卡 deferred.md。

    **在 finish 门判定之前调用**（RFC-20261122-07 复核轮 Major 修正）：open pre_existing
    Critical/Major 会以 WARN 下限阻断收口（收口需 PASS），若绑定成功路径则头条病案
    永远到不了台账——无论收口成败先落账，fingerprint 幂等兜底复跑重复。
    只登记不分诊（bmad-loop sweep 的 LLM 分诊轮明确不吸收，`RFC-20261119-03` R1 同源）。
    返回 `{registered, blocking}`（registered = 本次**新**登记条数）。"""
    root = Path(root).resolve()
    reviews_dir = root / "product" / "reviews"
    unit = str(task.get("id") or "")
    if not reviews_dir.is_dir() or not unit:
        return {"registered": 0, "blocking": 0}
    candidates = sorted(
        p for p in reviews_dir.iterdir()
        if p.is_dir() and re.fullmatch(
            REVIEW_DIR_PREFIX_RE + re.escape(unit) + "$", p.name)
    )
    if not candidates:
        return {"registered": 0, "blocking": 0}
    try:
        data = json.loads((candidates[-1] / "review.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"registered": 0, "blocking": 0}  # 报告损坏：登记面沉默（损坏由审查门点名）
    checks = data.get("checks") or []
    if not isinstance(checks, list):
        return {"registered": 0, "blocking": 0}
    round_no = str(data.get("round") or "").strip()
    deferred_path = Path(t_dir) / DEFERRED_FILE
    if deferred_path.is_file():
        try:
            existing = deferred_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return {"registered": 0, "blocking": 0}
    else:
        existing = DEFERRED_HEADER
    next_no = 1 + max((int(m.group(1)) for m in _DEFERRED_ID_RE.finditer(existing)),
                      default=0)
    registered = 0
    blocking = 0
    lines: list[str] = []
    for c in checks:
        if not isinstance(c, dict) or c.get("pre_existing") is not True:
            continue
        disposition = str(c.get("disposition") or "open").strip().lower()
        if disposition in DEFERRED_STATUS_CLOSED:
            continue
        key = _deferred_key(c)
        if key in existing:
            continue
        level = str(c.get("level") or "unknown").strip() or "unknown"
        detail = " ".join(str(c.get("detail") or "").split()) or "（无描述）"
        target = str(c.get("target") or "").strip()
        round_tag = f" r{round_no}" if round_no else ""
        loc = f"（{target}）" if target else ""
        lines.append(
            f"- DW-{next_no} 〔{date.today().isoformat()}｜开放｜族:{level}｜证:{key}{round_tag}〕"
            f"{detail}{loc}")
        if level in ("Critical", "Major"):
            blocking += 1
        next_no += 1
        registered += 1
    if not registered:
        return {"registered": 0, "blocking": 0}
    try:
        deferred_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=".deferred-", suffix=".tmp", dir=str(deferred_path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(existing.rstrip("\n") + "\n" + "\n".join(lines) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, deferred_path)
            fsync_dir(deferred_path.parent)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
    except OSError as exc:
        print(f"WARN（deferred 登记失败）: {exc}", file=sys.stderr)
        return {"registered": 0, "blocking": 0}
    try:
        shown = deferred_path.resolve().relative_to(root).as_posix()
    except ValueError:
        shown = str(deferred_path)
    print(f"  存量缺陷登记：{registered} 条（其中阻断中 {blocking} 条）→ {shown}")
    return {"registered": registered, "blocking": blocking}


def _acceptance_evidence(lay) -> dict:
    """用户验收走查留痕：`<e2e>/reviews/*-acceptance-*/README.md`（缺 ⇒ SKIP，人工责任）。"""
    reviews = lay.e2e_reviews_dir
    if not reviews.is_dir():
        return {"status": "SKIP", "reason": "无 E2E 验收走查留痕目录（人工责任）"}
    docs = sorted(p for p in reviews.glob("*-acceptance-*")
                  if p.is_dir() and (p / "README.md").is_file())
    if not docs:
        return {"status": "SKIP", "reason": "未见 *-acceptance-*/README.md（用户验收走查为人工责任）"}
    latest = docs[-1]
    return {"status": "PASS", "path": str(latest.relative_to(lay.root)),
            "reason": "找到验收走查留痕"}


E2E_MAIN_COLUMNS = ["用例ID", "页面", "中文标题", "类型", "关联AC", "需求", "状态", "状态原因", "分片"]


def _markdown_tables(text: str) -> list[tuple[list[str], list[list[str]]]]:
    """轻量读取 Markdown 表（列头 + 行），与 `validators/validate_e2e_index.tables` 同口径。

    不直接 import 校验器：`_support → validators` 反向依赖有棘轮上限
    （`tests/test_shared_kernel.py`），新增依赖须先拆旧的。
    """
    out: list[tuple[list[str], list[list[str]]]] = []
    block: list[list[str]] = []
    for line in text.splitlines():
        if line.strip().startswith("|"):
            block.append([c.strip() for c in line.strip().strip("|").split("|")])
        elif block:
            out.append((block[0], [r for r in block[1:]
                                   if not all(set(c) <= set("-: ") for c in r)]))
            block = []
    if block:
        out.append((block[0], [r for r in block[1:]
                               if not all(set(c) <= set("-: ") for c in r)]))
    return out


def check_e2e_precondition(root: Path, task: dict) -> dict:
    """收口前把 E2E 结论纳入校验输入（issue #69）。

    - 与本任务 AC 关联的用例存在 `red` ⇒ `FAIL`（阻断收口）；
    - 索引缺失 / 任务卡无 AC / 本任务 AC 未出现在索引 / 含 `skipped` ⇒ `SKIP`（显式记录原因，
      不静默当作通过）；
    - 其余（`green` / `blocked` 带原因）⇒ `PASS`。
    验收走查留痕单独记录，不改变 E2E 结论（缺留痕 = `SKIP`，人工责任）。
    """
    try:
        lay = load_layout(root)
    except LayoutError as exc:
        return {"status": "SKIP", "reason": f"布局不可解析：{exc}"}
    index = lay.e2e_index
    if not index.is_file():
        return {"status": "SKIP", "reason": f"未找到 E2E 索引（{index.relative_to(root)}）：按人工责任处理"}
    try:
        tabs = _markdown_tables(index.read_text(encoding="utf-8"))
    except OSError as exc:
        return {"status": "SKIP", "reason": f"E2E 索引不可读：{exc}"}
    if not tabs:
        return {"status": "SKIP", "reason": "E2E 索引无可解析表格"}
    matched = next(((h, r) for h, r in tabs if h == E2E_MAIN_COLUMNS), None)
    if matched is None:
        return {"status": "SKIP",
                "reason": f"E2E 主表列头不可识别（期望 {E2E_MAIN_COLUMNS}）"}
    header, rows = matched
    grid = [dict(zip(header, r + [""] * (len(header) - len(r)))) for r in rows]
    acs = [str(a) for a in (task.get("acs") or []) if str(a).strip()]
    if not acs:
        return {"status": "SKIP", "reason": "任务卡未声明 AC，无法定位 E2E 适用面", "acs": []}
    scoped = [g for g in grid if any(a in (g.get("关联AC") or "") for a in acs)]
    if not scoped:
        return {"status": "SKIP", "reason": f"本任务 AC 未出现在 E2E 索引：{acs}", "acs": acs}
    counts = dict(Counter((g.get("状态") or "") for g in scoped))
    cases = [g.get("用例ID") or "?" for g in scoped]
    red = [cid for cid, g in zip(cases, scoped) if (g.get("状态") or "") == "red"]
    skipped = [cid for cid, g in zip(cases, scoped) if (g.get("状态") or "") == "skipped"]
    out = {"acs": acs, "cases": cases, "counts": counts,
           "acceptance": _acceptance_evidence(lay)}
    if red:
        out.update(status="FAIL", reason=f"E2E 关联用例存在 red：{red}")
    elif skipped:
        out.update(status="SKIP", reason=f"E2E 关联用例含 skipped（不得当通过）：{skipped}")
    else:
        out.update(status="PASS", reason=f"E2E 关联用例无 red（{counts}）")
    return out


def _git_out(root: Path, *args: str) -> tuple[bool, str]:
    """本地 git 只读探测；(False, "") = 调用失败/非零退出（与 staged_files 同吞错口径）。"""
    try:
        pr = subprocess.run(["git", *args], cwd=str(root),
                            capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False, ""
    if pr.returncode != 0:
        return False, ""
    return True, pr.stdout.strip()


def _load_refresh_helpers() -> tuple | None:
    """惰性加载 `refresh_structure` 的新鲜度判据单源（RFC-20261122-05）。

    源仓布局（scripts/ 与 _support/ 同根）与采纳仓布局（.atlas/scripts/ 与
    .atlas/_support/ 同根）都按「父目录的 scripts/」解析；两处都没有 = 装配残缺
    ⇒ 返回 None。硬前置不走 atlas_check 的 WARN 降级模式——降级成放行恰好复制
    本门要治的「静默通过」病（评审 M2），由调用方 FAIL 响亮指名重装配。
    """
    here = Path(__file__).resolve().parent
    for cand in (here.parent / "scripts", here.parent):
        if (cand / "refresh_structure.py").is_file():
            if str(cand) not in sys.path:
                sys.path.insert(0, str(cand))
            break
    try:
        from refresh_structure import (  # noqa: E402
            clean_exempt_prefixes, declared_dirty_hit, load_local_dirty_paths,
            sha_matches_prefix)
    except Exception:  # noqa: BLE001 —— ImportError 与旧装配同名模块损坏同吃
        return None
    return clean_exempt_prefixes, sha_matches_prefix, load_local_dirty_paths, declared_dirty_hit


def _worktree_dirty_paths(root: Path,
                          prefixes: tuple[str, ...]) -> list[str] | None:
    """非豁免的**未暂存（工作树≠索引）∪ 未跟踪**路径（门脏面，RFC-20261122-05）。

    暂存面（索引侧）不入判据——收口契约下实现恰在暂存区，由 review 封口门
    （`_scope_matches`）背书（评审 C1）。git 探测失败 ⇒ None（硬门 fail-closed，
    不与「干净」混叠，评审 M1）。`core.quotePath=false` 保中文/特殊路径不被转义。
    """
    ok, diff = _git_out(root, "-c", "core.quotePath=false", "diff", "--name-only")
    if not ok:
        return None
    ok2, others = _git_out(root, "-c", "core.quotePath=false",
                           "ls-files", "--others", "--exclude-standard")
    if not ok2:
        return None
    paths = [ln.strip() for ln in (diff + "\n" + others).splitlines() if ln.strip()]
    return sorted(p for p in paths if not p.startswith(prefixes))


def check_structure_freshness(root: Path) -> dict:
    """结构事实新鲜度前置（RFC-20261122-05）：baseline ≡ HEAD ∧ 无未暂存脏路径。

    三态复刻 `check_e2e_precondition`。SKIP 仅两种：无 `_meta.json`（未开户，
    与 atlas_check `validate_structure` 前置同口径）/ 无 `.git`（非 git 仓）；
    其余一律 FAIL 或 PASS（响亮原则）。脏面三分诊（RFC-20261126-01）：半暂存
    （暂存∩脏）与未申报库外脏面 ⇒ FAIL（charged 同 `freshness_fail`）；
    `structure.local_dirty_paths` 申报面 ⇒ 豁免并在 PASS reason 逐条留痕（人审点，
    归档 task.json 入库可审）。判据盲区（gates.md §2.1 同步声明）：
    暂存面内容一致性（review 封口门辖区）、键级漂移登记语义（未终审漂移经
    F26 baseline 冻结在有已提交改动时间接阻断，终审通道 `--advance-baseline`，
    RFC-20261126-01 起扩越脏树）、适配器产物与源码实时一致、内容级漂移、
    `baseline.branch` 方向。
    """
    root = root.resolve()
    meta_path = root / ".atlas" / "spec" / "structure" / "_meta.json"
    if not meta_path.is_file():
        return {"status": "SKIP", "reason": "结构环未开户（无 .atlas/spec/structure/_meta.json）"}
    if not (root / ".git").exists():
        return {"status": "SKIP", "reason": "非 git 仓，结构事实新鲜度机器不可证"}
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"status": "FAIL", "reason": f"无法解析 {meta_path.relative_to(root)}：{exc}"}
    baseline = meta.get("baseline") if isinstance(meta, dict) else None
    old = str((baseline or {}).get("commit") or "").strip()
    if not old or old.startswith("[必填") or old == "—":
        return {"status": "FAIL", "reason": "结构事实 baseline 未登记（占位）——重跑 refresh_structure.py 重锚"}
    helpers = _load_refresh_helpers()
    if helpers is None:
        return {"status": "FAIL",
                "reason": "装配缺 scripts/refresh_structure.py（新鲜度判据单源）——重跑 install.sh --update 后重试"}
    clean_exempt_prefixes, sha_matches_prefix, load_local_dirty_paths, declared_dirty_hit = helpers
    ok, head = _git_out(root, "rev-parse", "HEAD")
    if not ok:
        return {"status": "FAIL", "reason": "git 探测失败（rev-parse HEAD 不可得）——结构事实新鲜度不可证"}
    try:
        prefixes = clean_exempt_prefixes(root)
    except LayoutError as exc:
        return {"status": "FAIL", "reason": f"布局配置不可读，豁免面无法判定：{exc}"}
    cur = head.splitlines()[0] if head else ""
    if not sha_matches_prefix(cur, old):
        return {"status": "FAIL", "reason": (
            f"结构事实 baseline（{old[:12]}）落后当前 HEAD（{cur[:12]}）——先重刷结构事实："
            "python3 .atlas/scripts/refresh_structure.py --root . --chain"
            "（树非干净——含暂存实现或未申报本地面——时追加 --advance-baseline 显式背书；"
            "facts 由 agent 维持、无适配器时同样以 --advance-baseline 背书）")}
    dirty = _worktree_dirty_paths(root, prefixes)
    if dirty is None:
        return {"status": "FAIL", "reason": "git 探测失败（工作树状态不可读）——结构事实新鲜度不可证"}
    # 脏面三分诊（RFC-20261126-01）：半暂存（暂存∩脏，审查锚失效风险）与未申报库外
    # 脏面 ⇒ FAIL（charged 不变）；已申报常驻本地面（structure.local_dirty_paths，
    # 判据单源 refresh_structure）⇒ 豁免，PASS reason 逐条留痕（评审 C1 人审点：
    # 归档 task.json 在 .atlas/tasks/ 白名单内入库可审）。
    staged = set(staged_files(root) or [])
    declared = load_local_dirty_paths(root)
    half = sorted(p for p in dirty if p in staged)
    declared_hits = sorted(p for p in dirty
                           if p not in staged and declared_dirty_hit(p, declared))
    undeclared = sorted(p for p in dirty
                        if p not in staged and not declared_dirty_hit(p, declared))
    if half:
        shown = " ".join(half[:3]) + ("…" if len(half) > 3 else "")
        return {"status": "FAIL", "reason": (
            f"产品侧存在半暂存改动（{shown}）：暂存与工作树内容分叉会让审查锚与提交"
            "内容不一致——先 git add 并入审查或 restore 还原后重试"
            "（structure.local_dirty_paths 申报不豁免半暂存面）")}
    if undeclared:
        shown = " ".join(undeclared[:3]) + ("…" if len(undeclared) > 3 else "")
        return {"status": "FAIL", "reason": (
            f"产品侧存在未申报的未暂存/未跟踪改动（{shown}）：先暂存并入审查"
            "（暂存面由审查封口门背书）或清理后重试；确属常驻不打算提交的本地面，"
            "在 .atlas/config.yaml 申报 structure.local_dirty_paths（目录条目以 / "
            "结尾按前缀匹配，其余精确匹配；申报消费留痕可审）")}
    note = ""
    if declared_hits:
        note = (f"；已申报本地脏面豁免 {len(declared_hits)} 条"
                f"（structure.local_dirty_paths）：{' '.join(declared_hits)}")
    return {"status": "PASS", "reason": f"baseline ≡ HEAD（{cur[:12]}）且无非豁免未暂存/未跟踪改动" + note}


def archive_month(t_dir: Path, tasks_root: Path, task_id: str | None = None) -> str | None:
    """任务目录若已在 `archive/<YYYY-MM>/<ID>/` 下，返回月份名；否则 None。"""
    if not is_archived_task_dir(tasks_root, t_dir):
        return None
    if task_id is not None and t_dir.name != task_id:
        return None
    return t_dir.parent.name


def archive_task(root: Path, tasks_root: Path, t_dir: Path, t_id: str,
                 *, _lock_held: bool = False) -> dict:
    """把已收口任务移到 `.atlas/tasks/archive/<YYYY-MM>/<id>/`（幂等；issue #70）。

    月份取归档当天。历史扁平存档（`archive/<id>/`）或缺/错月份层的目录会在
    下次归档时迁入当月，从而重新进入判据与封条的扫描面。
    """
    if not UNIT_RE.match(t_id):
        raise FinishError(f"非法任务标识：{t_id!r}", cause="no_task_card")
    root = root.resolve()
    if archive_month(t_dir, tasks_root, t_id) is not None:
        return {"status": "already", "path": str(t_dir.resolve().relative_to(root))}
    from contextlib import nullcontext
    try:
        lock_ctx = nullcontext() if _lock_held else WriteLock(root, holder="cli-archive", unit=t_id)
        with lock_ctx:
            archive_root = tasks_root / ARCHIVE_DIR
            month_dir = archive_root / date.today().strftime("%Y-%m")
            if archive_root.is_symlink() or month_dir.is_symlink():
                raise FinishError("归档链含 symlink，拒绝移出任务账本", cause="environment")
            try:
                month_resolved = month_dir.resolve()
                dest_resolved = (month_dir / t_id).resolve()
            except (OSError, RuntimeError) as exc:
                raise FinishError(f"归档目标不可解析：{exc}", cause="environment") from exc
            if (month_resolved.parent != archive_root.resolve()
                    or tasks_root not in dest_resolved.parents or root not in dest_resolved.parents):
                raise FinishError("归档目标越界，拒绝移动", cause="environment")
            dest = month_dir / t_id
            if dest.exists():
                raise FinishError(f"归档目标已存在：{dest}（源目录仍在 {t_dir}；请人工核对后处理）",
                                  cause="state_transition")
            src_parent = t_dir.parent
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(t_dir), str(dest))
                fsync_dir(dest)
                fsync_dir(dest.parent)
                fsync_dir(archive_root)
                if src_parent.exists():
                    fsync_dir(src_parent)
            except OSError as exc:
                raise FinishError(f"归档失败：{t_dir} → {dest}（{exc}）", cause="environment") from exc
            return {"status": "moved", "path": str(dest.relative_to(root))}
    except WriteLockError as exc:
        raise FinishError(f"写链互斥锁冲突：{exc}", cause="environment") from exc


def requirement_closeout(root: Path, req_root_rel: str) -> dict:
    """按需求类型生成收口待办；只有关联卡全部归档才推进落点状态。"""
    root = Path(root).resolve()
    req_root_rel = normalize_requirement_ref(root, req_root_rel)
    try:
        req_dir = resolve_requirement_root(root, req_root_rel)
        declared_type = requirement_type(req_dir) if req_dir is not None else None
    except (LayoutError, OSError):
        req_dir = None
        declared_type = None
    valid_type = declared_type in REQUIREMENT_TYPES
    kind = declared_type if valid_type else "未知"
    findings: list[str] = []
    try:
        relation_findings = (requirement_relation_findings(root, req_dir)
                             if req_dir is not None else ["需求落点无法解析"])
        findings.extend(relation_findings)
    except OSError as exc:
        relation_findings = [f"需求落点元数据不可读：{exc}"]
        findings.extend(relation_findings)
    load_error: str | None = None
    try:
        related = [
            t for t in load_tasks((root / ".atlas" / "tasks"), include_archived=True)
            if normalize_requirement_ref(root, t.get("requirement_root", ""))
            == req_root_rel
        ]
    except (PlanError, OSError) as exc:
        related = []
        load_error = str(exc)
        findings.append(f"任务账本不可读或存在重复 ID：{load_error}")
    claim_findings: list[str] = []
    for task in related:
        items_path = Path(task["_dir"]) / REQUIREMENT_ITEMS_FILE
        if not items_path.is_file():
            continue
        try:
            rows = first_table(
                strip_fences(items_path.read_text(encoding="utf-8", errors="replace")),
                ("来源",))
        except (OSError, UnicodeError) as exc:
            claim_findings.append(f"任务 {task.get('id')} 领取表不可读：{exc}")
            continue
        if not rows or not any("来源" in cell for cell in rows[0]):
            continue
        src_idx = next(i for i, cell in enumerate(rows[0]) if "来源" in cell)
        for row in rows[1:]:
            source = row[src_idx].strip() if len(row) > src_idx else ""
            match = SOURCE_REF_RE.match(source)
            if match and normalize_requirement_ref(root, match.group("path")) != req_root_rel:
                claim_findings.append(
                    f"任务 {task.get('id')} 领取来源 {match.group('path')!r} "
                    f"与 {req_root_rel!r} 不一致：拒绝跨落点冒领")
    findings.extend(claim_findings)
    all_closed = (bool(req_dir) and valid_type and not load_error and not relation_findings
                  and not claim_findings and bool(related) and all(
                      t.get("_archived") and t.get("status") == "completed" for t in related))
    if not all_closed:
        writeback = "pending"
    elif kind == "缺陷":
        writeback = "conditional"
    else:
        writeback = "required"
    if req_dir is None:
        findings.append("需求落点无法解析为唯一合法目录")
    elif not valid_type:
        findings.append(f"需求类型非法：{declared_type!r}")
    return {
        "requirement_root": req_root_rel,
        "type": kind,
        "all_cards_closed": all_closed,
        "product_fact_writeback": writeback,
        "requirement_status_target": "已收口" if all_closed else None,
        "findings": findings,
    }


def _refresh_staged_topology(root: Path, options: dict) -> dict:
    with tempfile.TemporaryDirectory(prefix="atlas-finish-topology-") as temporary:
        source_root = Path(temporary)
        checked_out = subprocess.run(["git", "checkout-index", "--all", f"--prefix={source_root}/"],
                                     cwd=root, capture_output=True, text=True, timeout=60)
        if checked_out.returncode != 0:
            raise TopologyError("staged index 不可物化：" + checked_out.stderr.strip())
        return refresh_topology(root, source_root=source_root, **options)


def _preflight_staged_topology(root: Path, options: dict) -> dict:
    """只读评估 staged index 的静态拓扑，不写 `.adapter-out/topology` 或代际目录。"""
    mode = str(options.get("mode") or "shadow")
    if mode not in ("shadow", "enforce", "off"):
        raise TopologyError("mode 必须为 shadow/enforce/off")
    if mode == "off":
        return {"schema_version": 1, "module": "topology", "mode": "off", "verdict": "UNVERIFIED",
                "cause": None, "rc": 2,
                "findings": [{"cause": "observation", "message": "Topology 已关闭；in-scope 不可判定"}],
                "metrics": {}}

    def _res(verdict: str, cause: str | None, findings: list[dict], *, metrics: dict | None = None) -> dict:
        rc = 0 if mode == "shadow" else 2 if verdict == "UNVERIFIED" else 1 if verdict in ("FAIL", "STALE") else 0
        return {"schema_version": 1, "module": "topology", "mode": mode, "verdict": verdict,
                "cause": cause, "rc": rc, "findings": findings, "metrics": metrics or {}}

    with tempfile.TemporaryDirectory(prefix="atlas-finish-topology-") as temporary:
        source_root = Path(temporary)
        checked_out = subprocess.run(["git", "checkout-index", "--all", f"--prefix={source_root}/"],
                                     cwd=root, capture_output=True, text=True, timeout=60)
        if checked_out.returncode != 0:
            raise TopologyError("staged index 不可物化：" + checked_out.stderr.strip())
        collect_kw = {k: v for k, v in options.items()
                      if k in ("project", "environment", "cluster", "release",
                               "scan_globs", "owner", "due", "adapter")}
        topology, _ = collect_topology(root, source_root=source_root, **collect_kw)
    if topology["coverage"]["parse_errors"]:
        findings = [{"cause": "topology_unverified", "path": item["path"], "message": item["message"]}
                    for item in topology["coverage"]["parse_errors"]]
        return _res("UNVERIFIED", "topology_unverified", findings,
                    metrics={"parsed": topology["coverage"]["parsed"]})
    if topology["coverage"]["parsed"] == 0 or not topology["items"]:
        return _res("UNVERIFIED", "topology_unverified",
                    [{"cause": "topology_unverified", "message": "未解析到任何静态拓扑节点"}])
    errors = validate_topology(topology)
    if errors:
        return _res("FAIL", "topology_stale",
                    [{"cause": "topology_stale", "message": "topology schema: " + "; ".join(errors)}])
    unverified = topology["coverage"]["unverified_fields"]
    return _res(
        "UNVERIFIED" if unverified else "PASS",
        "topology_unverified" if unverified else None,
        [] if not unverified else [{"cause": "topology_unverified", "message": "动态字段见 coverage.unverified_fields"}],
        metrics={"nodes": sum(bool(item.get("node")) for item in topology["items"]),
                 "edges": sum(bool(item.get("edge")) for item in topology["items"]),
                 "parsed": topology["coverage"]["parsed"]},
    )


def _validate_finish_gates(root: Path, task: dict, t_dir: Path, tasks_root: Path, *,
                           force: bool = False,
                           require_full_onboarding: bool = False,
                           mutate_topology: bool = True) -> dict:
    """共享 finish 门判定核心（预检只读模式与真实收口复用同一契约）。"""
    t_id = str(task.get("id") or "")
    if require_full_onboarding:
        if force:
            raise FinishError("P2 写链禁止 --force 绕过人工审查", cause="review_not_passed")
        if not (root / ".git").exists():
            raise FinishError("M3 写链要求 git 仓库，当前目录无 .git", cause="environment")
        try:
            prd_file = load_layout(root).prd_dir / "prd.md"
        except LayoutError as exc:
            raise FinishError(f"M3 写链布局配置不可读：{exc}", cause="environment") from exc
        meta_path = root / ".atlas" / "spec" / "structure" / "_meta.json"
        if not prd_file.is_file() or not meta_path.is_file():
            raise FinishError("M3 写链前置不满足：须完整装配且具备 PRD 与结构基线 _meta.json", cause="environment")
        if task.get("status") != "in_progress":
            raise FinishError(f"任务 {t_id} 状态须为 in_progress，当前 {task.get('status')!r}",
                              cause="state_transition")
        if archive_month(t_dir, tasks_root, t_id) is not None:
            raise FinishError(f"任务 {t_id} 已归档，不能重复收口", cause="state_transition")

    bug_check = validate_backflow(root, task)
    if bug_check["findings"]:
        raise FinishError(f"任务 {t_id} 无法收口：{'；'.join(bug_check['findings'])}",
                          cause=bug_check["cause"])
    bug_artifacts = set(bug_check.get("artifacts") or {})
    review_dir: str | None = None
    if bug_check["applicable"]:
        passed, reason, cause = check_task_review_passed(
            root, t_id, bug_artifacts=bug_artifacts)
        if not passed:
            raise FinishError(f"任务 {t_id} 无法收口：{reason}", cause=cause)
        review_dir = reason
        try:
            review_data = json.loads((Path(reason) / "review.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise FinishError(f"变更/缺陷审查锚不可读：{exc}", cause="environment")
        anchored = validate_backflow(root, task, review_data)
        if anchored["findings"]:
            raise FinishError(f"任务 {t_id} 无法收口：{'；'.join(anchored['findings'])}",
                              cause=anchored["cause"])
    elif not force:
        passed, reason, cause = check_task_review_passed(root, t_id)
        if not passed:
            raise FinishError(f"任务 {t_id} 无法收口：{reason}", cause=cause)
        review_dir = reason
    if force and receipt_mode(root) == "enforce":
        raise FinishError("receipt enforce 模式下 --force 不能生成完成凭据", cause="review_not_passed")

    e2e = check_e2e_precondition(root, task)
    if e2e["status"] == "FAIL":
        raise FinishError(f"任务 {t_id} 无法收口：{e2e['reason']}", cause="e2e_red")

    # 结构事实新鲜度前置（RFC-20261122-05）：没刷 spec 拒收。--force 不绕本门
    # （force 语义 = 跳过人工审查，非跳过事实锚，评审 M4）。
    structure = check_structure_freshness(root)
    if structure["status"] == "FAIL" or (require_full_onboarding and structure["status"] != "PASS"):
        raise FinishError(f"任务 {t_id} 无法收口：{structure['reason']}",
                          cause="freshness_fail")

    # P2 shadow 消费：仅 resolves_incidents/doc_ids 进入 scope；shadow 不阻断旧任务。
    try:
        incident_results = validate_task_incidents(
            root, task, force=force,
            mode="off" if incident_mode(root) == "off" else "enforce")
        docs_result = (check_docs_for_ids(root, task.get("doc_ids") or [],
                                          mode=docs_mode(root))
                       if task.get("doc_ids") else None)
        topology_options = {}
        topology_path = root / ".adapter-out/topology.json"
        if topology_path.is_file():
            try:
                topology_data = json.loads(topology_path.read_text(encoding="utf-8"))
                topology_options = topology_data.get("inputs") or {}
                if os.environ.get("ATLAS_TOPOLOGY_OWNER"):
                    topology_options["owner"] = os.environ["ATLAS_TOPOLOGY_OWNER"]
                if os.environ.get("ATLAS_TOPOLOGY_DUE"):
                    topology_options["due"] = os.environ["ATLAS_TOPOLOGY_DUE"]
                pointer_path = root / ".adapter-out/topology/manifest.json"
                if pointer_path.is_file():
                    topology_options.setdefault("adapter", json.loads(pointer_path.read_text()).get("adapter", "all"))
            except (OSError, ValueError):
                topology_options = {}
        topology_options["mode"] = topology_mode(root)
        topo_fn = _refresh_staged_topology if mutate_topology else _preflight_staged_topology
        topology_result = topo_fn(root, topology_options) if task.get("topology_required") else None
        if topology_result and topology_result.get("verdict") == "UNVERIFIED" \
                and topology_result.get("cause") == "topology_unverified":
            topology_data = json.loads((root / ".adapter-out/topology.json").read_text(encoding="utf-8"))
            ok_staged, staged_output = _git_out(root, "diff", "--cached", "--name-only",
                                                "--diff-filter=ACDMRT", "-z")
            if ok_staged:
                staged = [item for item in staged_output.split("\0") if item]
            else:
                staged = staged_files(root)
                if staged is None:
                    raise TopologyError("暂存面不可判定，不能降级动态拓扑 scope")
            topology_result = scope_topology_result(topology_result, topology_data, staged)
    except (IncidentError, DocsGovernanceError, TopologyError, OSError, ValueError) as exc:
        raise FinishError(f"治理引用无法校验：{exc}", cause="environment") from exc
    for governed in incident_results + ([docs_result] if docs_result else []) + ([topology_result] if topology_result else []):
        if governed.get("rc") != 0:
            cause = governed.get("cause")
            if not cause and governed.get("verdict") == "UNVERIFIED":
                cause = {"incident": "incident_unverified", "topology": "topology_unverified",
                         "docs": "docs_unverified", "semantic": "contract_unverified",
                         "classification": "calibration_unverified", "migration": "migration_unverified",
                         "receipt": "receipt_unverified"}.get(governed.get("module"), "environment")
            cause = cause or {
                "incident": "incident_not_resolved", "topology": "topology_stale",
                "docs": "docs_stale", "semantic": "contract_stale",
            }.get(governed.get("module"), "environment")
            raise FinishError(f"任务 {t_id} 无法收口：" + "; ".join(
                item.get("message", "") for item in governed.get("findings", [])), cause=cause)

    classification_result = None
    calibrated = None
    expected_digest = None
    if task.get("classification_required"):
        try:
            classification_result = _classification_result(root, None)
            expected_digest = task.get("classification_input_digest")
            if classification_result["input_digest"] != expected_digest:
                raise FinishError("任务分类结果 input_digest 与任务输入不符", cause="calibration_unverified")
        except (ReceiptError, OSError, ValueError) as exc:
            raise FinishError(f"任务 {t_id} 分类结果未通过：{exc}", cause="calibration_unverified") from exc
        calibration_validator = Path(__file__).resolve().parents[1] / "validators" / "validate_calibration.py"
        calibration_run = subprocess.run([sys.executable, str(calibration_validator), "--root", str(root), "--json"],
                                         capture_output=True, text=True, timeout=60)
        calibrated = json.loads(calibration_run.stdout)
        if calibrated["rc"] != 0:
            raise FinishError("分类校准未通过：" + "; ".join(f["message"] for f in calibrated["findings"]),
                              cause=calibrated.get("cause") or "calibration_unverified")
        if calibrated.get("decision") != "enforce":
            raise FinishError("classification_required 只接受 enforce 校准决策", cause="calibration_unverified")
        ledger = json.loads((root / ".atlas/runs/governance-calibration.json").read_text(encoding="utf-8"))
        if classification_result["decision"] == "auto":
            thresholds = ledger.get("thresholds") or {}
            if classification_result.get("scorer_version") != ledger.get("threshold_selection", {}).get("scorer_version") \
                    or classification_result.get("thresholds") != thresholds \
                    or classification_result["score"] < thresholds.get("top1_score", 1) \
                    or classification_result["margin"] < thresholds.get("margin", 1):
                raise FinishError("任务分类 scorer/threshold/分数与校准账本不符", cause="calibration_unverified")

    enforce_ctx: dict | None = None
    if receipt_mode(root) == "enforce":
        try:
            validate_workflow_origin(root, t_id,
                                     (Path(review_dir) / "review.json").relative_to(root).as_posix())
        except ReceiptError as exc:
            raise FinishError(f"任务 {t_id} 缺有效 workflow verify 来源：{exc}", cause="review_not_passed") from exc
        scope = ["workflow"]
        governed_results = [{"module": "workflow", "verdict": "PASS", "rc": 0,
                             "digest": canonical_digest({"review": review_dir})}]
        module_modes = {"workflow": "enforce"}
        if task.get("clause_ids"):
            scope.append("semantic")
            semantic_validator = Path(__file__).resolve().parents[1] / "validators" / "validate_contracts.py"
            semantic_run = subprocess.run([sys.executable, str(semantic_validator), "--root", str(root), "--json"],
                                          capture_output=True, text=True, timeout=180)
            semantic = json.loads(semantic_run.stdout)
            module_modes["semantic"] = semantic["mode"]
            if semantic["rc"] != 0:
                raise FinishError("Semantic 契约未通过：" + "; ".join(f["message"] for f in semantic["findings"]),
                                  cause=semantic.get("cause") or "contract_unverified")
            governed_results.append({key: semantic[key] for key in ("module", "verdict", "rc")} | {"digest": canonical_digest(semantic)})
        if task.get("doc_ids"):
            scope.append("docs")
            module_modes["docs"] = docs_mode(root)
        if task.get("resolves_incidents"):
            scope.append("incident")
            module_modes["incident"] = incident_mode(root)
        if task.get("topology_required"):
            scope.append("topology")
            module_modes["topology"] = topology_mode(root)
        if task.get("classification_required"):
            scope.append("classification")
            module_modes["classification"] = calibrated["decision"]
            governed_results.append({key: calibrated[key] for key in ("module", "verdict", "rc")} | {"digest": canonical_digest(calibrated)})
        if task.get("source_manifest"):
            scope.append("migration")
            migration_validator = Path(__file__).resolve().parents[1] / "validators" / "validate_migration.py"
            migration_run = subprocess.run([sys.executable, str(migration_validator), "--root", str(root), "--json"],
                                           capture_output=True, text=True, timeout=60)
            migrated = json.loads(migration_run.stdout)
            module_modes["migration"] = migrated["mode"]
            if migrated["rc"] != 0:
                raise FinishError("迁移证据未通过：" + "; ".join(f["message"] for f in migrated["findings"]),
                                  cause=migrated.get("cause") or "migration_unverified")
            governed_results.append({key: migrated[key] for key in ("module", "verdict", "rc")} | {"digest": canonical_digest(migrated)})
        if incident_results:
            incident_summary = {
                "module": "incident",
                "verdict": "PASS" if all(item["rc"] == 0 for item in incident_results) else "FAIL",
                "rc": 0 if all(item["rc"] == 0 for item in incident_results) else next(
                    item["rc"] for item in incident_results if item["rc"] != 0),
                "digest": canonical_digest(incident_results),
            }
            governed_results.append(incident_summary)
        governed_results += [{key: item[key] for key in ("module", "verdict", "rc")} | {"digest": canonical_digest(item)}
                             for item in ([docs_result] if docs_result else []) + ([topology_result] if topology_result else [])]
        if any(mode != "enforce" for mode in module_modes.values()):
            blocked_module = next(name for name, mode in module_modes.items() if mode != "enforce")
            cause = {"semantic": "contract_unverified", "incident": "incident_unverified",
                     "docs": "docs_unverified", "topology": "topology_unverified",
                     "classification": "calibration_unverified", "migration": "migration_unverified",
                     "receipt": "receipt_unverified"}.get(blocked_module, "environment")
            raise FinishError("receipt enforce 要求 in-scope 模块均为 enforce；当前 " + json.dumps(module_modes, sort_keys=True), cause=cause)
        ok_base, base = _git_out(root, "rev-parse", "HEAD")
        if not ok_base:
            raise FinishError("receipt base HEAD 不可得", cause="environment")
        enforce_ctx = {
            "scope": scope,
            "governed_results": governed_results,
            "module_modes": module_modes,
            "base": base.splitlines()[0] if base else "",
        }

    return {
        "bug_check": bug_check,
        "bug_artifacts": bug_artifacts,
        "review_dir": review_dir,
        "e2e": e2e,
        "structure": structure,
        "incident_results": incident_results,
        "docs_result": docs_result,
        "topology_result": topology_result,
        "classification_result": classification_result,
        "expected_digest": expected_digest,
        "enforce_ctx": enforce_ctx,
    }


def _resolve_task_scope(root: Path, task: dict) -> tuple[Path, str, Path, Path]:
    root = root.resolve()
    t_id = str(task.get("id") or "")
    if not UNIT_RE.match(t_id):
        raise FinishError(f"非法任务标识：{t_id!r}", cause="no_task_card")
    tasks_root = (root / ".atlas" / "tasks").resolve()
    t_dir = Path(task.get("_dir") or (tasks_root / t_id)).resolve()
    if t_dir != tasks_root and tasks_root not in t_dir.parents:
        raise FinishError(f"任务目录越界：{t_dir}（必须在 {tasks_root} 之内）",
                          cause="no_task_card")
    if not t_dir.is_dir():
        raise FinishError(f"任务目录不存在：{t_dir}", cause="no_task_card")
    if receipt_mode(root) == "off":
        raise FinishError("receipt off 模式下不能完成或归档任务", cause="receipt_unverified")
    if archive_month(t_dir, tasks_root, t_id) is None:
        archive_dest = tasks_root / ARCHIVE_DIR / date.today().strftime("%Y-%m") / t_id
        if archive_dest.exists():
            raise FinishError(
                f"归档目标已存在：{archive_dest}（源目录仍在 {t_dir}；请人工核对后处理）",
                cause="state_transition")
    return root, t_id, tasks_root, t_dir


def preflight_finish(root: Path, task: dict, *, force: bool = False,
                     require_full_onboarding: bool = False) -> dict:
    """纯只读预检：校验收口全部门禁与待写面，不写 attempts/deferred/receipt/.adapter-out。"""
    root, t_id, tasks_root, t_dir = _resolve_task_scope(root, task)
    deferred_plan = plan_deferred_findings(root, task, t_dir)
    gates = _validate_finish_gates(
        root, task, t_dir, tasks_root,
        force=force, require_full_onboarding=require_full_onboarding, mutate_topology=False,
    )
    ok_head, head_out = _git_out(root, "rev-parse", "HEAD")
    return {
        "ok": True,
        "unit": t_id,
        "task_dir": str(t_dir),
        "head_commit": head_out.splitlines()[0] if ok_head and head_out else None,
        "staged_files": staged_files(root) or [],
        "deferred_plan": deferred_plan,
        "bug_backflow": {
            "applicable": gates["bug_check"]["applicable"],
            "artifacts": sorted(gates["bug_artifacts"]),
            "review": gates["review_dir"],
        },
        "e2e_precondition": gates["e2e"],
        "structure_freshness": gates["structure"],
        "governance_precondition": {
            "incidents": gates["incident_results"],
            "docs": gates["docs_result"],
            "topology": gates["topology_result"],
            "receipt_mode": receipt_mode(root),
        },
        "enforce_ready": gates["enforce_ctx"] is not None,
        "archive_dest": str(tasks_root / ARCHIVE_DIR / date.today().strftime("%Y-%m") / t_id),
    }


def finish_task(root: Path, task: dict, *, force: bool = False,
                _lock_held: bool = False) -> dict:
    """完成单个任务的收口流转。"""
    root, t_id, tasks_root, t_dir = _resolve_task_scope(root, task)
    from contextlib import nullcontext
    try:
        lock_ctx = nullcontext() if _lock_held else WriteLock(root, holder="cli-finish", unit=t_id)
        with lock_ctx:
            # 存量缺陷登记（RFC-20261122-07 §3.1.3）：finish 门判定**之前**执行——无论收口
            # 成败先落账（open pre_existing Critical/Major 以 WARN 下限阻断收口，绑定成功
            # 路径则头条病案永远到不了台账；fingerprint 幂等兜底复跑重复）。
            deferred_info = extract_deferred_findings(root, task, t_dir)
            gates = _validate_finish_gates(
                root, task, t_dir, tasks_root,
                force=force, require_full_onboarding=False, mutate_topology=True,
            )
            bug_check = gates["bug_check"]
            bug_artifacts = gates["bug_artifacts"]
            review_dir = gates["review_dir"]
            e2e = gates["e2e"]
            structure = gates["structure"]
            incident_results = gates["incident_results"]
            docs_result = gates["docs_result"]
            topology_result = gates["topology_result"]
            classification_result = gates["classification_result"]
            expected_digest = gates["expected_digest"]
            enforce_ctx = gates["enforce_ctx"]

            receipt_result = None
            if enforce_ctx is not None:
                governed_results = enforce_ctx["governed_results"]
                scope = enforce_ctx["scope"]
                module_modes = enforce_ctx["module_modes"]
                base = enforce_ctx["base"]
                try:
                    build_receipt(
                        root=root, unit=t_id, task_id=t_id, base=base,
                        validators=governed_results, in_scope_modules=scope,
                        module_modes=module_modes,
                        review_path=(Path(review_dir).absolute().relative_to(root).as_posix() + "/review.json"),
                        requirement_id=task.get("requirement_root"), clause_ids=task.get("clause_ids") or [],
                        incident_ids=task.get("incident_ids") or [], resolves_incidents=task.get("resolves_incidents") or [],
                        doc_ids=task.get("doc_ids") or [], topology_refs=task.get("topology_refs") or [],
                        topology_required=bool(task.get("topology_required")), migration_required=bool(task.get("source_manifest")),
                        classification_required=bool(task.get("classification_required")),
                        classification_result=classification_result,
                        classification_input_digest=expected_digest,
                        review_origin="workflow", force=False,
                    )
                    receipt_result = verify_receipt(
                        root, mode="enforce", check_current_tree=True,
                        expected_unit=t_id, expected_task_id=t_id,
                        expected_validator_digests={item["module"]: item["digest"] for item in governed_results},
                    )
                    if receipt_result["rc"] != 0:
                        raise FinishError("；".join(item["message"] for item in receipt_result["findings"]),
                                          cause=receipt_result.get("cause") or "receipt_unverified")
                except FinishError:
                    raise
                except ReceiptError as exc:
                    raise FinishError(f"receipt 验证失败：{exc}", cause="receipt_stale") from exc
                except SemanticError as exc:
                    raise FinishError(f"receipt Semantic 验证失败：{exc}", cause="contract_unverified") from exc
                except (OSError, ValueError) as exc:
                    raise FinishError(f"receipt 验证失败：{exc}", cause="environment") from exc

            # 更新 task.json 状态为 completed（E2E 前置结论一并落盘，issue #69）
            task_json_file = t_dir / "task.json"
            if task_json_file.is_file():
                try:
                    meta = json.loads(task_json_file.read_text(encoding="utf-8"))
                except Exception:
                    meta = task
            else:
                meta = task

            meta["status"] = "completed"
            meta["e2e_precondition"] = e2e
            meta["structure_freshness"] = structure
            meta["governance_precondition"] = {"incidents": incident_results, "docs": docs_result,
                                               "topology": topology_result, "receipt": receipt_result}
            atomic_write_json(task_json_file, meta)
            fsync_dir(task_json_file.parent)

            # 归档（issue #70）：completed 任务移出活跃区；幂等，失败显式报错
            archived = archive_task(root, tasks_root, t_dir, t_id, _lock_held=True)

            # 检查整体工作流是否全部收工（含归档任务）；账本读取失败不得把已归档任务变成崩溃现场。
            task_load_error: str | None = None
            try:
                all_tasks = load_tasks(tasks_root, include_archived=True)
            except (PlanError, OSError) as exc:
                all_tasks = [{**task, "status": "completed", "_archived": True}]
                task_load_error = str(exc)
            total = len(all_tasks)
            completed_count = sum(1 for t in all_tasks if t.get("status") == "completed")

            return {
                "unit": t_id,
                "status": "completed",
                "total_tasks": total,
                "completed_tasks": completed_count,
                "all_done": (task_load_error is None and total > 0 and completed_count == total),
                "task_load_error": task_load_error,
                "requirement_closeout": (
                    requirement_closeout(root, task["requirement_root"])
                    if task.get("requirement_root") else None),
                "bug_backflow": {
                    "applicable": bug_check["applicable"],
                    "artifacts": sorted(bug_artifacts),
                    "review": review_dir,
                },
                "change_backflow": {
                    "applicable": bug_check["applicable"],
                    "artifacts": sorted(bug_artifacts),
                    "review": review_dir,
                },
                "e2e_precondition": e2e,
                "structure_freshness": structure,
                "governance_precondition": {"incidents": incident_results, "docs": docs_result,
                                            "topology": topology_result, "receipt": receipt_result},
                "deferred_registration": deferred_info,
                "archived": archived,
            }
    except WriteLockError as exc:
        raise FinishError(f"写链互斥锁冲突：{exc}", cause="environment") from exc
