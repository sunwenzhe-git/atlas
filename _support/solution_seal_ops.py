"""封条写侧（§10，2026-11-17 从 `solution.py` 迁出）。

职责：多封条选择、`seal freeze` / `seal reanchor` 的锁写入，以及 status / check / diff
的文本渲染。对外入口：`select_seal_path` / `freeze_seal` / `reanchor_seal` /
`render_status` / `render_check` / `render_diff`。

依赖由 `solution.py` 在加载后注入（`SolutionError` / `_assets_root` / `_SEAL` /
`read_lock` / `lock_path` / `LOCK_NAME` / `_head`）；本模块**不得反向 import** `solution.py`，
否则形成环。
"""

from __future__ import annotations

import json
import re
from pathlib import Path


def select_seal_path(root: Path, requested: str | None = None) -> str:
    """多封条选择：`--seal` 显式；否则唯一 HEAD 封条；多枚 ⇒ exit 2 候选。"""
    lock = read_lock(root)
    anchors = (lock or {}).get("seal_anchors")
    by_path = {k: v for k, v in anchors.items()
               if isinstance(v, dict)} if isinstance(anchors, dict) else {}
    asset_root = (lock or {}).get("layout_assets_root") or _assets_root(root)
    heads = _SEAL.head_seals(root, [asset_root])
    try:
        return _SEAL.select_seal(root, by_path, requested, heads)
    except _SEAL.SealError as exc:
        raise SolutionError(str(exc)) from exc


def _write_lock_doc(root: Path, doc: dict) -> Path:
    path = lock_path(root)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(path)
    return path


def freeze_seal(root: Path, seal_path: str, at: str) -> dict:
    """`seal freeze`：只写锁的 `state` / `frozen_at`，不碰封条字节（S-38）。"""
    path = select_seal_path(root, seal_path)
    if not _SEAL.is_seal_path(path):
        raise SolutionError(f"--seal 不是合法封条路径: {path}")
    if _SEAL.head_blob(root, path) is None:
        raise SolutionError(f"HEAD 无封条文件: {path}")
    hist = _SEAL.seal_history(root, path)
    if hist["error"] or at not in hist["commits"]:
        raise SolutionError(f"--at={at} 不是 {path} 的封条提交")
    if at != hist["commits"][-1]:
        raise SolutionError(
            f"--at 必须是该路径最后一枚封条提交 L[-1]={hist['commits'][-1]}")
    lock = read_lock(root)
    if lock is None:
        raise SolutionError(f"缺少 {LOCK_NAME}；先 lock --update")
    anchors = lock.get("seal_anchors")
    if not isinstance(anchors, dict) or path not in anchors:
        raise SolutionError(f"锁内没有该路径键（先 lock --update）: {path}")
    anchor = dict(anchors[path])
    anchor["state"] = "frozen"
    anchor["frozen_at"] = at
    anchors[path] = anchor
    lock["seal_anchors"] = anchors
    _write_lock_doc(root, lock)
    return {"seal": path, "state": "frozen", "frozen_at": at}


def reanchor_seal(root: Path, seal_path: str, review: str, from_a: str) -> dict:
    """`seal reanchor`：重写纪元起点 + 同步 `exemption_started_at` + append 审计项。"""
    cause, detail = _SEAL.repo_shape(root)
    if cause:
        raise SolutionError(f"拒绝 reanchor：{detail}（{cause}）")
    path = select_seal_path(root, seal_path)
    if not _SEAL.is_seal_path(path):
        raise SolutionError(f"--seal 不是合法封条路径: {path}")
    raw = _SEAL.head_blob(root, path)
    if raw is None:
        raise SolutionError(f"HEAD 无封条文件: {path}")
    try:
        head_doc = _SEAL.parse_seal(raw)
    except _SEAL.SealError as exc:
        raise SolutionError(str(exc)) from exc
    if not re.fullmatch(r"[0-9a-f]{40}", str(from_a or "")):
        raise SolutionError(f"--from-a 必须是 40 位提交 SHA: {from_a!r}")
    if _SEAL._has_object(root, from_a):
        raise SolutionError(
            f"reanchor_not_allowed: from_a={from_a[:12]} 仍可达；"
            "唯一可用路径是在未拉过旧历史的 fresh clone 上执行")
    lock = read_lock(root)
    if lock is None:
        raise SolutionError(f"缺少 {LOCK_NAME}；先 lock --update")
    anchors = lock.get("seal_anchors")
    if not isinstance(anchors, dict) or path not in anchors:
        raise SolutionError(f"reanchor_anchor_missing: 锁内没有该路径键 {path}")
    anchor = dict(anchors[path])
    # v49/项 1：`moved_to` 与 `reanchor` 互斥——键已 `retired`（带 `moved_to`）或
    # 封条本身带 `moved_to` 时，写侧拒绝、exit 2、不写任何文件。
    if "moved_to" in anchor or "moved_to" in head_doc:
        raise SolutionError(
            "seal_move_reanchor_conflict: 该键 / 封条已带 moved_to（retired），"
            "不得再写 reanchor")
    hist = _SEAL.seal_history(root, path)
    N = hist["N"]
    if anchor.get("renewal_seq") != head_doc.get("renewal_seq") \
            or anchor.get("n") != N:
        raise SolutionError(
            "seal_anchor_stale: 锁锚与 HEAD 封条 / N 不同步；先 lock --update")
    if anchor.get("epoch_origin") != from_a:
        raise SolutionError(
            "reanchor_anchor_mismatch: from_a != seal_anchors[S].epoch_origin")
    try:
        payload = _SEAL.reanchor_payload(head_doc, from_a=from_a, review=review)
    except _SEAL.SealError as exc:
        raise SolutionError(str(exc)) from exc
    payload["reanchor"]["base_seq"] = int(anchor.get("renewal_seq") or 0) + 1
    payload["reanchor"]["base_n"] = int(anchor.get("n") or 0)
    # 先验后写：审计链必须可从当前 origin 接续
    chain = list(anchor.get("exemption_start_history") or [])
    origin = anchor.get("exemption_start_origin")
    old_started = anchor.get("exemption_started_at")
    if chain:
        if chain[-1].get("to") != old_started:
            raise SolutionError(
                "exemption_start_history_broken: 末项 to 与 exemption_started_at 不等")
        prev_to = chain[-1].get("to")
    else:
        if origin != old_started:
            raise SolutionError(
                "exemption_start_history_broken: 无重指时 origin 必须等于 started_at")
        prev_to = origin
    target = Path(root) / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    new_started = payload["signed_at"]
    chain.append({"from": prev_to, "to": new_started, "commit": _head(root)})
    anchor["exemption_started_at"] = new_started
    anchor["exemption_start_history"] = chain
    anchor["renewal_seq"] = payload["renewal_seq"]
    anchors[path] = anchor
    lock["seal_anchors"] = anchors
    _write_lock_doc(root, lock)
    return {"seal": path, "renewal_seq": payload["renewal_seq"],
            "reanchor": payload["reanchor"],
            "exemption_started_at": new_started,
            "next": "提交封条与本锁（reanchor 提交 R），再独立跑 lock --update 并提交 R2"}


def render_status(data: dict) -> str:
    lines = [f"solution: {data['solution']} ({data['mode']})", "members:"]
    for s in data["members"]:
        head = (s.get("head") or "—")[:12]
        dirty_n = s.get("dirty_count")
        dirty = "clean" if dirty_n == 0 else (f"dirty:{dirty_n}" if dirty_n else "n/a")
        ignored = "ignored" if s.get("ignored") else "ok"
        if s.get("head_drift"):
            drift = "drift"
        elif s.get("locked_head"):
            drift = "locked"
        else:
            drift = "no-lock"
        lines.append(
            f"  {s['name']:<16} {s['path']:<20} git={str(s['git']).lower():<5} "
            f"branch={s.get('branch') or '—':<12} head={head:<12} {dirty:<8} "
            f"{drift:<7} atlas={'yes' if s['atlas_assets'] else 'no':<3} {ignored}")
    lines.append(f"lock: {'present' if data['lock']['present'] else 'missing'}"
                 + (f" ({data['lock']['locked_at']})" if data['lock'].get('locked_at') else ""))
    return "\n".join(lines)


def render_check(data: dict) -> str:
    lines = [f"solution check: {data['overall']}"]
    for r in data["checks"]:
        lines.append(f"  [{r['status']}] {r['check']}: {r['detail']}")
    return "\n".join(lines)


def render_diff(data: dict) -> str:
    lines = [f"solution diff: {data['solution']} ({data['mode']})"]
    for m in data["members"]:
        if not m["git"]:
            lines.append(f"  [{m['name']}] {m['path']}  ! 不是 git 仓")
            continue
        locked = (m.get("locked_head") or "—")[:12]
        lines.append(
            f"  [{m['name']}] {m['path']} branch={m.get('branch') or '—'} "
            f"head={(m.get('head') or '—')[:12]} locked={locked}")
        if not m.get("locked_head"):
            lines.append("    lock=—（未锁定，仅显示工作区）")
        elif m.get("lock_commit_present") is False:
            lines.append("    ! 锁中 commit 不在本地；请先 fetch 对应成员")
        elif m["commits"]:
            lines.append(f"    自锁以来提交 {len(m['commits'])} 条:")
            lines += [f"      {c}" for c in m["commits"]]
            if m["diffstat"]:
                lines.append("    自锁以来 diffstat:")
                lines += [f"      {c}" for c in m["diffstat"]]
        if m["staged"]:
            lines.append("    已暂存:")
            lines += [f"      {c}" for c in m["staged"]]
        if m["unstaged"]:
            lines.append("    未暂存:")
            lines += [f"      {c}" for c in m["unstaged"]]
        if m["worktree"]:
            lines.append(f"    工作区 {len(m['worktree'])} 项:")
            lines += [f"      {c}" for c in m["worktree"][:30]]
            if len(m["worktree"]) > 30:
                lines.append(f"      …（其余 {len(m['worktree']) - 30} 项省略）")
        if m.get("worktree_ok") is False:
            lines.append("    ! git status 失败，无法判断工作区")
        if not any((m["commits"], m["staged"], m["unstaged"], m["worktree"])):
            lines.append("    clean（相对锁无差异）")
    return "\n".join(lines)
