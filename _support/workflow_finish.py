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

import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from _support import review_scope_core as scope_core
from _support.layout import LayoutError, load_layout
from _support.workflow_plan import ARCHIVE_DIR, load_tasks, atomic_write_json, UNIT_RE


class FinishError(ValueError):
    """收口校验异常。"""


REVIEW_DIR_PREFIX_RE = r"^\d{4}-\d{2}-\d{2}-impl-review-"
ARCHIVE_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")  # `archive/<YYYY-MM>/<ID>/`

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
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            cwd=str(root), capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if pr.returncode != 0:
        return None
    return [line.strip() for line in pr.stdout.splitlines() if line.strip()]


def _scope_matches(root: Path, data: dict) -> tuple[bool, str]:
    """检查报告落盘后暂存区内容未被替换（v4 内容封口）。

    三分类诊断（2026-11-21，自进化 campaign T3 三撞实测）：extra（暂存面多出实审集
    之外的路径——典型 = 审查产物误入暂存）/ missing（实审文件未暂存）/ changed
    （实审文件内容已变）。extra 全落审查产物目录 ⇒ 指引 unstage（该场景重跑
    verify 无效）；changed ⇒ 指引重新审查。整体摘要一致即放行（快速路径）。
    """
    scope = data.get("review_scope")
    if not isinstance(scope, dict) or not scope.get("sha256"):
        return True, ""  # 旧报告兼容：无内容锚，无法比对
    staged = staged_files(root)
    if staged is None:
        return False, "无法读取暂存区，不能确认审查内容未被替换（请在 git 仓库内重跑 verify）"
    try:
        manifest = scope_core.build_manifest(root, staged)
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
            m = scope_core.build_manifest(root, [p])
        except Exception:  # noqa: BLE001
            changed.append(p)
            continue
        entry = (m.get("files") or [{}])[0]
        if entry.get("sha256") != recorded.get(p):
            changed.append(p)
    extra_review = [q for q in extra if q.startswith(review_prefixes)]
    extra_other = [q for q in extra if not q.startswith(review_prefixes)]
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
    if not parts:
        parts.append("暂存面与实审集内容均一致但整体摘要不一致（罕见）；请重跑 verify")
    return False, "；".join(parts)


def check_task_review_passed(root: Path, unit: str) -> tuple[bool, str]:
    """检查指定任务是否已产出合规的 review.json 且未被拦截。"""
    root = root.resolve()
    # 查找匹配的 review 报告目录
    reviews_dir = root / "product" / "reviews"
    if not reviews_dir.is_dir():
        return False, "未找到 product/reviews 目录（尚未执行独立审查）"

    candidates = sorted(
        p for p in reviews_dir.iterdir()
        if p.is_dir() and re.fullmatch(
            REVIEW_DIR_PREFIX_RE + re.escape(unit) + "$", p.name)
    )
    if not candidates:
        return False, f"未找到任务 {unit} 的审查报告（须先执行 atlas review --unit {unit} --staged）"

    latest_dir = candidates[-1]
    review_file = latest_dir / "review.json"
    if not review_file.is_file():
        return False, f"报告目录 {latest_dir.name} 缺少 review.json"

    try:
        data = json.loads(review_file.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"读取 {review_file} 失败：{exc}"

    # 检查 review.json 是否合规且无阻塞项。字段口径以 cli_review_convert 的实际产出为准：
    # `status ∈ {PASS, WARN, FAIL}` + `ok` —— PASS 已由 `review_policy.calculate_status` 保证
    # 「无阻断 Critical、无 Major、无 M≠N 等下限」，此处不重复实现严重度判定（判据单源）。
    status = str(data.get("status") or "").strip().upper()
    if status != "PASS":
        return False, f"审查报告状态未通过（status: {data.get('status')}；收口需 PASS，WARN/FAIL 均阻断）"
    if data.get("ok") is False:
        return False, "审查报告 ok=false（存在未解决的阻断问题）"

    matched, why = _scope_matches(root, data)
    if not matched:
        return False, why

    return True, str(latest_dir)


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
        from refresh_structure import clean_exempt_prefixes, sha_matches_prefix  # noqa: E402
    except Exception:  # noqa: BLE001 —— ImportError 与旧装配同名模块损坏同吃
        return None
    return clean_exempt_prefixes, sha_matches_prefix


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
    其余一律 FAIL 或 PASS（响亮原则）。判据盲区（gates.md §2.1 同步声明）：
    暂存面内容一致性（review 封口门辖区）、键级漂移登记语义（未终审漂移经
    F26 baseline 冻结在有已提交改动时间接阻断，终审通道 `--advance-baseline`）、
    适配器产物与源码实时一致、内容级漂移、`baseline.branch` 方向。
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
    clean_exempt_prefixes, sha_matches_prefix = helpers
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
            "（facts 由 agent 维持、无适配器时追加 --advance-baseline 显式背书）")}
    dirty = _worktree_dirty_paths(root, prefixes)
    if dirty is None:
        return {"status": "FAIL", "reason": "git 探测失败（工作树状态不可读）——结构事实新鲜度不可证"}
    if dirty:
        shown = " ".join(dirty[:3]) + ("…" if len(dirty) > 3 else "")
        return {"status": "FAIL", "reason": (
            f"产品侧存在未暂存/未跟踪改动（{shown}）：先暂存并入审查"
            "（暂存面由审查封口门背书）或清理后重试")}
    return {"status": "PASS", "reason": f"baseline ≡ HEAD（{cur[:12]}）且无非豁免未暂存/未跟踪改动"}


def archive_month(t_dir: Path, tasks_root: Path) -> str | None:
    """任务目录若已在 `archive/<YYYY-MM>/<ID>/` 下，返回月份名；否则 None。

    月份层是判据侧的既有契约：`validators/validate_task_card.py` 按
    `archive/*/*/prd.md` 找卡，封条按 `archive/*/<ID>/<tail>` 定位。写入侧
    只用月度目录，避免归档卡静默掉出判据覆盖（issue #70）。
    """
    archive_root = (tasks_root / ARCHIVE_DIR).resolve()
    try:
        rel = t_dir.resolve().relative_to(archive_root)
    except ValueError:
        return None
    if len(rel.parts) == 2 and ARCHIVE_MONTH_RE.match(rel.parts[0]):
        return rel.parts[0]
    return None


def archive_task(root: Path, tasks_root: Path, t_dir: Path, t_id: str) -> dict:
    """把已收口任务移到 `.atlas/tasks/archive/<YYYY-MM>/<id>/`（幂等；issue #70）。

    月份取归档当天。历史扁平存档（`archive/<id>/`）或缺/错月份层的目录会在
    下次归档时迁入当月，从而重新进入判据与封条的扫描面。
    """
    if not UNIT_RE.match(t_id):
        raise FinishError(f"非法任务标识：{t_id!r}")
    root = root.resolve()
    if archive_month(t_dir, tasks_root) is not None:
        return {"status": "already", "path": str(t_dir.resolve().relative_to(root))}
    dest = tasks_root / ARCHIVE_DIR / date.today().strftime("%Y-%m") / t_id
    if dest.exists():
        raise FinishError(f"归档目标已存在：{dest}（源目录仍在 {t_dir}；请人工核对后处理）")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(t_dir), str(dest))
    except OSError as exc:
        raise FinishError(f"归档失败：{t_dir} → {dest}（{exc}）") from exc
    return {"status": "moved", "path": str(dest.relative_to(root))}


def finish_task(root: Path, task: dict, *, force: bool = False) -> dict:
    """完成单个任务的收口流转。"""
    root = root.resolve()
    t_id = task["id"]
    if not UNIT_RE.match(t_id):
        raise FinishError(f"非法任务标识：{t_id!r}")
    tasks_root = (root / ".atlas" / "tasks").resolve()
    t_dir = Path(task.get("_dir") or (tasks_root / t_id)).resolve()
    if t_dir != tasks_root and tasks_root not in t_dir.parents:
        raise FinishError(f"任务目录越界：{t_dir}（必须在 {tasks_root} 之内）")

    if not t_dir.is_dir():
        raise FinishError(f"任务目录不存在：{t_dir}")
    if archive_month(t_dir, tasks_root) is None:
        archive_dest = tasks_root / ARCHIVE_DIR / date.today().strftime("%Y-%m") / t_id
        if archive_dest.exists():
            raise FinishError(
                f"归档目标已存在：{archive_dest}（源目录仍在 {t_dir}；请人工核对后处理）")
    if not force:
        passed, reason = check_task_review_passed(root, t_id)
        if not passed:
            raise FinishError(f"任务 {t_id} 无法收口：{reason}")

    e2e = check_e2e_precondition(root, task)
    if e2e["status"] == "FAIL":
        raise FinishError(f"任务 {t_id} 无法收口：{e2e['reason']}")

    # 结构事实新鲜度前置（RFC-20261122-05）：没刷 spec 拒收。--force 不绕本门
    # （force 语义 = 跳过人工审查，非跳过事实锚，评审 M4）。
    structure = check_structure_freshness(root)
    if structure["status"] == "FAIL":
        raise FinishError(f"任务 {t_id} 无法收口：{structure['reason']}")

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
    atomic_write_json(task_json_file, meta)

    # 归档（issue #70）：completed 任务移出活跃区；幂等，失败显式报错
    archived = archive_task(root, tasks_root, t_dir, t_id)

    # 检查整体工作流是否全部收工（含归档任务）
    all_tasks = load_tasks(tasks_root, include_archived=True)
    total = len(all_tasks)
    completed_count = sum(1 for t in all_tasks if t.get("status") == "completed")

    return {
        "unit": t_id,
        "status": "completed",
        "total_tasks": total,
        "completed_tasks": completed_count,
        "all_done": (total > 0 and completed_count == total),
        "e2e_precondition": e2e,
        "structure_freshness": structure,
        "archived": archived,
    }
