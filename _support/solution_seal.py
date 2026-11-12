#!/usr/bin/env python3
"""验收资产封条（seal）单源：路径解析、upstream 绑定、续签链、状态机、写侧。

RFC-20261111-03 §1.1.3 / §1.4 / §1.5 / §2.5 / §3.2 / §3.4 的 C 批落点。
本模块只依赖 stdlib + git，不 import `_support/solution.py`（避免环），
由 `solution.py::_load_sibling` 或校验器按文件路径加载。

术语：
- `S`：封条仓内路径 `<assets_root>/reviews/apply/<member>/<task-id>.seal.json`；
- `L`：该路径封条事件提交序列（`git show --name-status` 非空）；
- `N = len(L)`；`A` / `D`：add / delete 提交数。
"""
from __future__ import annotations

import copy
import fnmatch
import hashlib
import json
import re
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------- 常量

SEAL_RE = re.compile(
    r"^(?P<root>.+?)/reviews/apply/(?P<member>[^/]+)/(?P<task>[^/]+)\.seal\.json$")
SIGNED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REVIEW_ID_RE = re.compile(r"^REVIEW-\d{8}-\d{2}$")

SEAL_STATES = ("active", "retired", "frozen")
SEAL_KINDS = ("binding", "backfill", "legacy")
ROLES = ("manifest", "prd-global", "prd-domain", "ac-crosswalk",
         "e2e-index", "e2e-case", "stack-profile")

# 载荷等价豁免集（§3.2 链规则 2 / 5）
BOUNDARY_EXEMPT = frozenset({
    "renewal_seq", "previous_seal_commit", "previous_seal_sha256",
    "reanchor", "signed_at"})
# 换路径首签豁免集（§3.2 链规则 3 / T-26）。`reasons` 是注释不是业务载荷：
# 纯改名写一条 `--reason` 不得因此判「载荷不等」。
MOVE_EXEMPT = frozenset({
    "renewal_seq", "previous_seal_commit", "previous_seal_sha256",
    "moved_from", "reanchor", "reasons"})


class SealError(ValueError):
    """输入 / 写侧用法错误（CLI exit 2）。"""


# ---------------------------------------------------------------- git

def _git(root: Path, *args: str, binary: bool = False):
    proc = subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=not binary)
    if binary:
        return proc.returncode, proc.stdout, proc.stderr.decode("utf-8", "replace")
    return proc.returncode, proc.stdout, proc.stderr


def _rev_parse(root: Path, rev: str) -> str | None:
    rc, out, _ = _git(root, "rev-parse", "--verify", rev)
    return out.strip() if rc == 0 and out.strip() else None


def _has_object(root: Path, sha: str) -> bool:
    """`git cat-file -e <sha>` 语义：对象在本地对象库中是否可用。"""
    rc, _, _ = _git(root, "cat-file", "-e", sha)
    return rc == 0


def _ancestor_rc(root: Path, commit: str) -> int:
    """`git merge-base --is-ancestor <commit> HEAD` 原始退出码。

    RFC §1.1.3：0 = 仍可达（拒绝）；1 = 不可达（允许）；128 = 对象缺失（允许）；
    其它非零 = 错误（写侧拒绝，读侧报 `chain_unverifiable`）。
    """
    rc, _, _ = _git(root, "merge-base", "--is-ancestor", str(commit), "HEAD")
    return rc


def repo_shape(root: Path) -> tuple[str | None, str]:
    """返回 `(cause, detail)`；`cause is None` 表示仓形态可信。

    cause ∈ {shallow, partial}；非 git / 空仓按可信处理（由调用方判）。
    """
    rc, out, _ = _git(root, "rev-parse", "--is-shallow-repository")
    if rc == 0 and out.strip() == "true":
        return "shallow", "仓库是浅克隆（--is-shallow-repository=true），历史不可证"
    rc, out, _ = _git(root, "config", "--get-regexp",
                      r"^remote\..*\.promisor$")
    rc2, out2, _ = _git(root, "config", "--get", "extensions.partialClone")
    has_promisor = (rc == 0 and out.strip()) or (rc2 == 0 and out2.strip())
    if not has_promisor:
        pack = Path(root) / ".git" / "objects" / "pack"
        has_promisor = pack.is_dir() and any(pack.glob("*.promisor"))
    if has_promisor:
        return "partial", "仓库是 partial clone（promisor），历史对象不可证"
    return None, ""


def _parents(root: Path, commit: str) -> list[str]:
    rc, out, _ = _git(root, "rev-list", "--parents", "-n", "1", commit)
    if rc != 0 or not out.strip():
        return []
    return out.split()[1:]


def seal_history(root: Path, path: str) -> dict:
    """复算 `C0 / L / L_pre / N / A / D`（§3.2 封条路径历史）。"""
    rc, out, err = _git(root, "rev-list", "--full-history", "--no-renames",
                        "--reverse", "HEAD", "--", path)
    if rc != 0:
        return {"error": "history_unreadable", "detail": err.strip(),
                "commits": [], "statuses": {}}
    commits = [line for line in out.splitlines() if line.strip()]
    statuses: dict[str, str] = {}
    kept: list[str] = []
    for commit in commits:
        rc2, out2, _ = _git(root, "show", "--no-renames", "--format=",
                            "--name-status", commit, "--", path)
        text = out2.strip()
        if rc2 != 0 or not text:
            continue
        letters = "".join(line.split("\t", 1)[0].strip()
                          for line in text.splitlines() if line.strip())
        statuses[commit] = letters
        kept.append(commit)
    a_count = sum(1 for c in kept if "A" in statuses[c])
    d_count = sum(1 for c in kept if "D" in statuses[c])
    delete_idx = [i for i, c in enumerate(kept) if "D" in statuses[c]]
    pre = kept[: max(delete_idx)] if delete_idx else list(kept)
    return {"error": None, "commits": kept, "statuses": statuses,
            "N": len(kept), "A": a_count, "D": d_count, "L_pre": pre}


def merge_conflicts(root: Path, path: str, commits: list[str]) -> list[str]:
    """`L` 中封条字节与所有父都不同的 merge（§3.2 冲突解决型 merge）。"""
    bad: list[str] = []
    for commit in commits:
        parents = _parents(root, commit)
        if len(parents) < 2:
            continue
        differs = True
        for parent in parents:
            rc, _, _ = _git(root, "diff", "--quiet", parent, commit, "--", path)
            if rc == 0:
                differs = False
                break
        if differs:
            bad.append(commit)
    return bad


def blob_at(root: Path, commit: str, path: str) -> bytes | None:
    """`<commit>:<path>` 的 blob 字节；不存在 / 非 blob ⇒ `None`。"""
    rc, out, _ = _git(root, "cat-file", "-t", f"{commit}:{path}")
    if rc != 0 or out.strip() != "blob":
        return None
    rc, data, _ = _git(root, "show", f"{commit}:{path}", binary=True)
    return data if rc == 0 else None


def head_blob(root: Path, path: str) -> bytes | None:
    return blob_at(root, "HEAD", path)


def worktree_dirty(root: Path, path: str) -> str:
    rc, out, _ = _git(root, "status", "--porcelain", "--", path)
    return out.strip() if rc == 0 else ""


def seal_sha256(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def projection_sha(projection: dict) -> str:
    return hashlib.sha256(canonical(projection)).hexdigest()


def parse_seal(data: bytes) -> dict:
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise SealError(f"封条不是合法 JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise SealError("封条顶层不是 JSON 对象")
    return doc


def is_seal_path(path: str) -> bool:
    return bool(SEAL_RE.match(path))


# ---------------------------------------------------------------- 角色解析

def _member_prd_paths(root: Path, data: dict, assets_root: str) -> list[str]:
    out: list[str] = []
    for member in data.get("members") or []:
        base = Path(root) / str(member["path"])
        if not base.is_dir():
            continue
        for path in sorted((base / assets_root / "prd").glob("*-prd.md")):
            out.append(str(path.relative_to(root)))
    return out


def resolve_upstreams(root: Path, data: dict, assets_root: str) -> dict:
    """解析 C 批可绑定的 role → 仓内路径。

    只返回**文件存在**的 role（`prd-domain` / `ac-crosswalk` 不存在 ⇒ 缺席，
    不拒签，§2.5 C 批边界）。
    """
    root = Path(root)
    resolved: dict[str, list[str]] = {}
    manifest = Path(root) / "atlas.solution.yaml"
    if manifest.is_file():
        resolved["manifest"] = ["atlas.solution.yaml"]
    definition = (data.get("definition") or {}).get("path")
    if definition and (root / definition).is_file():
        resolved["prd-global"] = [str(definition)]
    prd_domain = _member_prd_paths(root, data, assets_root)
    if prd_domain:
        resolved["prd-domain"] = prd_domain
    crosswalk = Path(assets_root) / "prd" / "ac-crosswalk.md"
    if (root / crosswalk).is_file():
        resolved["ac-crosswalk"] = [str(crosswalk)]
    has_cases = any(req.get("case_ids") for req in data.get("requirements") or [])
    index = Path(assets_root) / "e2e" / "e2e-index.md"
    if has_cases and (root / index).is_file():
        resolved["e2e-index"] = [str(index)]
        cases: list[str] = []
        for req in data.get("requirements") or []:
            for case_id in req.get("case_ids") or []:
                candidate = Path(assets_root) / "e2e" / "cases" / f"{case_id}.md"
                if (root / candidate).is_file():
                    cases.append(str(candidate))
        if cases:
            resolved["e2e-case"] = sorted(set(cases))
    profile = Path(assets_root) / "stack-profile.yaml"
    if (root / profile).is_file():
        resolved["stack-profile"] = [str(profile)]
    return resolved


def _sha_for(root: Path, path: str) -> str | None:
    target = Path(root) / path
    try:
        return hashlib.sha256(
            target.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    except OSError:
        return None


def _role_shapes(root: Path, data: dict, assets_root: str) -> dict[str, list[str]]:
    """role 的**规定路径形态**（文件不存在时也用于区分 `deleted` 与 `unresolved`）。"""
    definition = (data.get("definition") or {}).get("path") or ""
    return {
        "manifest": ["atlas.solution.yaml"],
        "prd-global": [definition or f"{assets_root}/prd/*-prd.md"],
        "prd-domain": [f"*/{assets_root}/prd/*-prd.md"],
        "ac-crosswalk": [f"{assets_root}/prd/ac-crosswalk.md"],
        "e2e-index": [f"{assets_root}/e2e/e2e-index.md"],
        "e2e-case": [f"{assets_root}/e2e/cases/*.md"],
        "stack-profile": [f"{assets_root}/stack-profile.yaml"],
    }


def _matches_role_shape(role: str, path: str, shapes: dict[str, list[str]]) -> bool:
    return any(fnmatch.fnmatch(path, pattern)
               for pattern in shapes.get(role, []))


def upstream_findings(root: Path, data: dict, seal: dict, seal_path: str,
                      assets_root: str, *, bind_from: str | None,
                      today: date | None = None) -> list[dict]:
    """`upstream[]` 绑定校验 + `seal_upstream_unbound`（§2.5）。"""
    from datetime import timezone
    today = today or datetime.now(timezone.utc).date()
    findings: list[dict] = []
    resolved = resolve_upstreams(root, data, assets_root)
    shapes = _role_shapes(root, data, assets_root)
    state = (seal.get("__state") or "active")
    entries = seal.get("upstream")
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        findings.append(_f("upstream_invalid", "error",
                           "upstream 不是数组", seal_path))
        entries = []
    by_role: dict[str, list[dict]] = {}
    for item in entries:
        if not isinstance(item, dict):
            findings.append(_f("upstream_invalid", "error",
                               "upstream 项不是对象", seal_path))
            continue
        role = item.get("role")
        path = item.get("path")
        if role not in ROLES:
            findings.append(_f("upstream_role_unknown", "error",
                               f"upstream role 越界: {role!r}", seal_path))
            continue
        allowed = resolved.get(role)
        if allowed is None:
            if _matches_role_shape(role, path, shapes) \
                    and not (Path(root) / str(path)).exists():
                findings.append(_f("upstream_missing", "error",
                                   f"上游已删除: {role} {path}", seal_path))
            else:
                findings.append(_f("upstream_path_unresolved", "error",
                                   f"role {role} 在父仓不可解析（文件不存在）",
                                   seal_path))
            continue
        if path not in allowed:
            findings.append(_f("upstream_path_unresolved", "error",
                               f"role {role} 的 path 不在规定解析内: {path!r}",
                               seal_path))
            continue
        by_role.setdefault(role, []).append(item)
    for role, items in by_role.items():
        for item in items:
            path = item["path"]
            actual = _sha_for(root, path)
            if actual is None:
                findings.append(_f("upstream_missing", "error",
                                   f"上游已删除: {role} {path}", seal_path))
            elif item.get("sha256") != actual:
                findings.append(_f("upstream_stale", "error",
                                   f"上游字节已变（{role} {path}）", seal_path))
    missing = [role for role in resolved if role not in by_role]
    if missing:
        text = ("封条 upstream 缺绑定 role: " + "、".join(missing)
                + (f"（state=frozen 永久 WARN）" if state == "frozen" else ""))
        if state == "frozen":
            findings.append(_f("seal_upstream_unbound", "warning", text, seal_path))
        elif bind_from is None:
            findings.append(_f("seal_upstream_unbound", "warning", text, seal_path))
        else:
            try:
                deadline = (datetime.strptime(bind_from, "%Y-%m-%d").date()
                            + timedelta(days=90))
            except ValueError:
                deadline = None
            severity = "error" if deadline and today > deadline else "warning"
            findings.append(_f("seal_upstream_unbound", severity, text, seal_path))
    return findings


def _f(code: str, severity: str, message: str, path: str | None,
       detail: dict | None = None) -> dict:
    item = {"code": code, "severity": severity, "message": message, "path": path}
    if detail is not None:
        item["detail"] = detail
    return item


# ---------------------------------------------------------------- 路径宇宙

def seal_universe(root: Path, roots: list[str]) -> tuple[set[str], set[str]]:
    """`U`（历史新增封条路径并集）与 unsupported（键不匹配任何根谓词）。

    返回 `(U, supported_roots)`。
    """
    universe: set[str] = set()
    for asset_root in roots:
        pattern = f":(glob){asset_root}/reviews/apply/*/*.seal.json"
        rc, out, _ = _git(root, "log", "-m", "--full-history",
                          "--diff-filter=A", "--no-renames",
                          "--format=", "--name-only", "HEAD", "--", pattern)
        if rc != 0:
            continue
        for line in out.splitlines():
            rel = line.strip()
            m = SEAL_RE.match(rel)
            if m and m.group("root") == asset_root:
                universe.add(rel)
    return universe, set(roots)


def key_matches_root(key: str, roots: list[str]) -> bool:
    m = SEAL_RE.match(key)
    return bool(m and m.group("root") in roots)


# ---------------------------------------------------------------- 链

def _payload_of(doc: dict, exempt: frozenset) -> bytes:
    return canonical({k: v for k, v in doc.items()
                      if k not in exempt and not k.startswith("__")})


def analyze_chain(root: Path, path: str, seal: dict, anchor: dict | None,
                  state: str) -> list[dict]:
    """单路径链校验（active / retired / frozen 共用，按状态分派）。

    `seal` 为 HEAD（frozen 为 frozen_at）封条文档；`anchor` 为
    `seal_anchors[path]`（可能为 None）。
    """
    out: list[dict] = []
    hist = seal_history(root, path)
    if hist["error"]:
        return [_f("chain_unverifiable", "error",
                   f"链历史不可读（{hist.get('detail') or 'git log 失败'}）", path,
                   {"cause": "history_unreadable"})]
    commits: list[str] = hist["commits"]
    statuses: dict[str, str] = hist["statuses"]
    L = hist["L_pre"] if state in ("retired", "frozen") else commits
    if not L:
        return [_f("chain_unverifiable", "error",
                   "该路径没有可读的封条提交（L 为空）", path,
                   {"cause": "history_unreadable"})]
    if 0 == hist["A"]:
        return [_f("chain_unverifiable", "error",
                   "首签对象本地缺失（A == 0）", path,
                   {"cause": "history_unreadable"})]
    for commit in merge_conflicts(root, path, L):
        out.append(_f("seal_merge_conflict", "error",
                      f"冲突解决型 merge 手写新字节: {commit[:12]}", path))
    if out:
        return out
    if state == "active":
        if hist["D"] > 0:
            return [_f("seal_history_reset", "error",
                       "封条路径出现删除提交（D>0），删+重建视为重置", path)]
        if hist["A"] >= 2:
            return [_f("seal_history_ambiguous", "error",
                       "封条路径有多个 add（A>=2），要求重签", path)]
        if "A" not in statuses.get(L[0], ""):
            out.append(_f("chain_unverifiable", "error",
                          "L[0] 不是首签提交（add）", path,
                          {"cause": "history_unreadable"}))
            return out
    elif state == "retired":
        if hist["D"] > 1:
            out.append(_f("seal_path_history_lost", "error",
                          "retired 路径出现多次删除，无法用 moved_from 覆盖", path))
    N = len(L)
    seq = seal.get("renewal_seq")
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
        out.append(_f("renewal_chain_broken", "error",
                      f"renewal_seq 非法: {seq!r}", path))
        return out
    reanchor = seal.get("reanchor")
    if reanchor is not None:
        if not isinstance(reanchor, dict):
            out.append(_f("reanchor_invalid", "error",
                          "reanchor 不是对象", path))
            return out
        base_n = reanchor.get("base_n")
        base_seq = reanchor.get("base_seq")
        if not isinstance(base_n, int) or isinstance(base_n, bool) or base_n < 1 \
                or N < 2:
            out.append(_f("reanchor_invalid", "error",
                          f"reanchor.base_n={base_n!r} / N={N} 不满足 N>=2 且 "
                          "base_n>=1", path))
            return out
        if not isinstance(base_seq, int) or isinstance(base_seq, bool):
            out.append(_f("reanchor_invalid", "error",
                          f"reanchor.base_seq={base_seq!r} 非法", path))
            return out
        expect = base_seq + (N - base_n) - 1
        if seq != expect:
            out.append(_f("renewal_chain_broken", "error",
                          f"renewal_seq={seq} != reanchor 公式 {expect}"
                          f"（base_seq={base_seq}, base_n={base_n}, N={N}）", path))
            return out
    elif seq != N:
        out.append(_f("renewal_chain_broken", "error",
                      f"renewal_seq={seq} != N={N}", path))
        return out
    # 4b：边界记录认证（v49/项 2：`reanchor_record_missing` 只对 `active` / `frozen`
    # 判；`retired` 键的 `epoch_origin` 已固化，不因旧路径树被重写而报）。
    if reanchor is None:
        if state in ("active", "frozen") and anchor \
                and anchor.get("epoch_origin") not in (None, L[0]):
            out.append(_f("reanchor_record_missing", "error",
                          f"锁内 epoch_origin={anchor.get('epoch_origin')} != "
                          f"L[0]={L[0]}，但封条没有 reanchor", path))
            return out
    else:
        matches = []
        for commit in L:
            raw = blob_at(root, commit, path)
            if raw is None:
                continue
            try:
                doc = parse_seal(raw)
            except SealError:
                continue
            if doc.get("renewal_seq") == reanchor.get("base_seq"):
                matches.append((commit, doc))
        if len(matches) != 1:
            out.append(_f("reanchor_record_mismatch", "error",
                          f"L 中 renewal_seq == base_seq 的提交有 {len(matches)} 枚"
                          "（要求恰好 1 枚）", path))
            return out
        record_commit, record_doc = matches[0]
        if canonical(record_doc.get("reanchor")) != canonical(reanchor):
            out.append(_f("reanchor_record_mismatch", "error",
                          "边界记录与当前 reanchor 不逐字节相同", path))
            return out
        if anchor and anchor.get("anchor_review") not in (None, ""):
            if (reanchor.get("review") or "") != anchor.get("anchor_review"):
                out.append(_f("reanchor_record_mismatch", "error",
                              "reanchor.review 与锁内 anchor_review 不符"
                              "（多纪元回滚）", path))
                return out
        # 4a：只在 HEAD == R0（当前提交就是写下 reanchor 的那枚）时执行
        head = _rev_parse(root, "HEAD")
        if head == record_commit:
            out.extend(_anchor_checks(root, path, seal, anchor, L, N, reanchor))
    # 5 / 6 / 7 / 8
    prev_commit = seal.get("previous_seal_commit")
    prev_sha = seal.get("previous_seal_sha256")
    boundary = (reanchor is not None
                and seq == reanchor.get("base_seq"))
    if seq > 1 and N >= 2:
        if boundary:
            if prev_commit != reanchor.get("from_a"):
                out.append(_f("renewal_chain_broken", "error",
                              "边界封条 previous_seal_commit != reanchor.from_a",
                              path))
            if prev_sha is not None:
                out.append(_f("renewal_chain_broken", "error",
                              "边界封条 previous_seal_sha256 必须为 null", path))
            old = blob_at(root, L[-2], path)
            if old is not None:
                try:
                    old_doc = parse_seal(old)
                except SealError:
                    old_doc = None
                if old_doc is not None and \
                        _payload_of(old_doc, BOUNDARY_EXEMPT) != \
                        _payload_of(seal, BOUNDARY_EXEMPT):
                    out.append(_f("reanchor_payload_mismatch", "error",
                                  "reanchor 提交改动了业务载荷（应与 L[-2] 逐字节相等）",
                                  path))
        else:
            if prev_commit != L[-2]:
                out.append(_f("renewal_chain_broken", "error",
                              f"previous_seal_commit={prev_commit} != L[-2]={L[-2]}",
                              path))
            old = blob_at(root, L[-2], path)
            if old is not None and prev_sha != seal_sha256(old):
                out.append(_f("renewal_chain_broken", "error",
                              "previous_seal_sha256 与 L[-2] 封条字节不符", path))
            if old is not None:
                try:
                    old_doc = parse_seal(old)
                except SealError:
                    old_doc = None
                if old_doc is not None and \
                        seal.get("first_seen_at") != old_doc.get("first_seen_at"):
                    out.append(_f("renewal_chain_broken", "error",
                                  "first_seen_at 与上一枚封条不一致", path))
    elif seq == 1:
        if prev_commit is not None or prev_sha is not None:
            out.append(_f("renewal_chain_broken", "error",
                          "首签的 previous_* 必须为 null", path))
        moved_from = seal.get("moved_from")
        if isinstance(moved_from, dict) and moved_from.get("path"):
            out.extend(_move_payload(root, path, seal, moved_from))
        else:
            first = blob_at(root, L[0], path)
            if first is not None and canonical(seal) != canonical(parse_seal(first)):
                out.append(_f("renewal_chain_broken", "error",
                              "首签 blob 与 L[0] 不相等", path))
    # 8：previous_seal_commit 指向的提交必须有封条
    skip8 = boundary and prev_commit == reanchor.get("from_a")
    if not skip8 and prev_commit and N >= 2:
        if blob_at(root, prev_commit, path) is None:
            if _rev_parse(root, prev_commit) is not None:
                out.append(_f("seal_missing_at_commit", "error",
                              f"previous_seal_commit={prev_commit[:12]} 下无封条",
                              path))
            else:
                out.append(_f("chain_unverifiable", "error",
                              f"previous_seal_commit={prev_commit[:12]} 对象本地缺失",
                              path, {"cause": "object_missing"}))
    # signed_at 形态（T-29）
    if not SIGNED_AT_RE.match(str(seal.get("signed_at") or "")):
        out.append(_f("signed_at_not_canonical", "error",
                      f"signed_at 非规范形态: {seal.get('signed_at')!r}", path))
    return out


def _anchor_checks(root: Path, path: str, seal: dict, anchor: dict | None,
                   L: list[str], N: int, reanchor: dict) -> list[dict]:
    out: list[dict] = []
    from_a = reanchor.get("from_a")
    if not isinstance(from_a, str) or not re.fullmatch(r"[0-9a-f]{40}", from_a):
        out.append(_f("reanchor_anchor_mismatch", "error",
                      f"reanchor.from_a 形态非法: {from_a!r}", path))
        return out
    if _has_object(root, from_a):
        out.append(_f("reanchor_not_allowed", "error",
                      f"from_a={from_a[:12]} 仍可达；reanchor 只允许不可达旧 A",
                      path))
        return out
    if not anchor:
        out.append(_f("reanchor_anchor_missing", "error",
                      "seal_anchors 为 null 或没有该路径键", path))
        return out
    prev_doc = None
    if len(L) >= 2:
        raw = blob_at(root, L[-2], path)
        if raw is not None:
            try:
                prev_doc = parse_seal(raw)
            except SealError:
                prev_doc = None
    if prev_doc is None or anchor.get("renewal_seq") != prev_doc.get("renewal_seq") \
            or anchor.get("n") != N - 1:
        out.append(_f("seal_anchor_stale", "error",
                      "锁锚与 L[-2] 封条不同步；先 lock --update 再 reanchor", path))
        return out
    if (anchor.get("epoch_origin") != from_a
            or reanchor.get("base_seq") != (anchor.get("renewal_seq") or 0) + 1
            or reanchor.get("base_n") != anchor.get("n")):
        out.append(_f("reanchor_anchor_mismatch", "error",
                      "reanchor 的 from_a / base_seq / base_n 与锁锚不符", path))
        return out
    if anchor.get("anchor_review") not in (None, ""):
        if (reanchor.get("review") or "") != anchor.get("anchor_review"):
            out.append(_f("reanchor_anchor_mismatch", "error",
                          "reanchor.review 与 anchor_review 不符", path))
    return out


def _move_payload(root: Path, path: str, seal: dict, moved_from: dict) -> list[dict]:
    old_path = moved_from.get("path")
    if not isinstance(old_path, str) or not is_seal_path(old_path):
        return [_f("seal_path_history_lost", "error",
                   f"moved_from.path 非法: {old_path!r}", path)]
    old_hist = seal_history(root, old_path)
    if old_hist["error"] or not old_hist["L_pre"]:
        return [_f("seal_path_history_lost", "error",
                   f"旧路径 {old_path} 链不可复算", path)]
    old_raw = blob_at(root, old_hist["L_pre"][-1], old_path)
    if old_raw is None:
        return [_f("seal_path_history_lost", "error",
                   f"旧路径最后封条不可读: {old_path}", path)]
    if moved_from.get("sha256") != seal_sha256(old_raw):
        return [_f("seal_path_history_lost", "error",
                   "moved_from.sha256 与旧路径最后封条字节不符", path)]
    try:
        old_doc = parse_seal(old_raw)
    except SealError:
        old_doc = None
    if old_doc is None:
        return [_f("seal_path_history_lost", "error",
                   f"旧路径封条不可解析: {old_path}", path)]
    if _payload_of(old_doc, MOVE_EXEMPT) != _payload_of(seal, MOVE_EXEMPT):
        reasons = seal.get("reasons")
        prev_cases = seal.get("e2e", {}).get("previous_cases") \
            if isinstance(seal.get("e2e"), dict) else None
        if not (isinstance(reasons, list) and reasons
                and isinstance(prev_cases, list) and prev_cases):
            return [_f("seal_move_payload_mismatch", "error",
                       "换路径首签的业务载荷与旧封条不等：需非空 reasons[] 说明改动，"
                       "并给出覆盖所有改动用例的 previous_cases[]（reasons[] 本身不计载荷）",
                       path)]
    return []


# ---------------------------------------------------------------- 状态机

def analyze_state(root: Path, path: str, anchor: dict, assets_root: str,
                  data: dict, *, bind_from: str | None = None) -> list[dict]:
    out: list[dict] = []
    state = anchor.get("state")
    if state not in SEAL_STATES:
        return [_f("seal_anchor_path_state_mismatch", "error",
                   f"state 非法: {state!r}", path)]
    if worktree_dirty(root, path):
        return [_f("seal_worktree_dirty", "error",
                   "封条工作树不干净；链复算以 HEAD 为准", path)]
    head_raw = head_blob(root, path)
    if state == "active":
        if head_raw is None:
            return [_f("seal_anchor_path_state_mismatch", "error",
                       "state=active 但 HEAD 无该封条文件", path)]
        try:
            seal = parse_seal(head_raw)
        except SealError as exc:
            return [_f("seal_unparsable", "error", str(exc), path)]
        out.extend(_schema_findings(root, data, seal, path, assets_root,
                                    bind_from, state))
        out.extend(analyze_chain(root, path, seal, anchor, "active"))
        return out
    if state == "frozen":
        frozen_at = anchor.get("frozen_at")
        head = _rev_parse(root, "HEAD")
        if not frozen_at or _rev_parse(root, frozen_at) is None:
            return [_f("seal_frozen_modified", "error",
                       f"frozen_at 缺失或不是有效提交: {frozen_at!r}", path)]
        # I1：删除→重建→冻结 仍属重置，不能借冻结绕过 seal_history_reset。
        hist = seal_history(root, path)
        if not hist["error"] and hist["D"] > 0:
            return [_f("seal_history_reset", "error",
                       "frozen 路径历史上出现删除提交（D>0），视为重置", path)]
        rc, _, _ = _git(root, "merge-base", "--is-ancestor", frozen_at, "HEAD")
        if rc != 0:
            return [_f("seal_frozen_modified", "error",
                       f"frozen_at={frozen_at[:12]} 不是 HEAD 祖先", path)]
        rc, out_log, _ = _git(root, "log", "--format=%H",
                              f"{frozen_at}..HEAD", "--", path)
        if rc == 0 and out_log.strip():
            return [_f("seal_frozen_modified", "error",
                       "冻结后封条路径仍有提交（改写或删除）", path)]
        frozen_raw = blob_at(root, frozen_at, path)
        if frozen_raw is None:
            return [_f("seal_frozen_modified", "error",
                       "冻结提交下封条不存在", path)]
        try:
            seal = parse_seal(frozen_raw)
        except SealError as exc:
            return [_f("seal_unparsable", "error", str(exc), path)]
        out.extend(_schema_findings(root, data, seal, path, assets_root,
                                    bind_from, "frozen"))
        out.extend(analyze_chain(root, path, seal, anchor, "frozen"))
        return out
    # retired
    moved_to = anchor.get("moved_to")
    if not moved_to:
        return [_f("seal_path_history_lost", "error",
                   "state=retired 但缺 moved_to", path)]
    target_anchor = (data.get("__seal_anchors") or {}).get(moved_to)
    if not isinstance(target_anchor, dict):
        return [_f("seal_path_history_lost", "error",
                   f"moved_to={moved_to} 不是锁内键", path)]
    # v49/项 2：`retired` 只判「`moved_to` 指向的新键存在且 state == active」。
    if target_anchor.get("state") != "active":
        return [_f("seal_path_history_lost", "error",
                   f"moved_to={moved_to} 的目标键 state="
                   f"{target_anchor.get('state')!r}，应为 active", path)]
    target_raw = head_blob(root, moved_to)
    if target_raw is None:
        return [_f("seal_path_history_lost", "error",
                   f"moved_to={moved_to} 的封条不存在", path)]
    try:
        target = parse_seal(target_raw)
    except SealError as exc:
        return [_f("seal_path_history_lost", "error", str(exc), path)]
    moved_from = target.get("moved_from")
    if not isinstance(moved_from, dict) or moved_from.get("path") != path:
        return [_f("seal_path_history_lost", "error",
                   "新路径封条的 moved_from.path 未指回本路径", path)]
    hist = seal_history(root, path)
    if hist["error"] or not hist["L_pre"]:
        return [_f("seal_path_history_lost", "error",
                   "retired 路径 L_pre 不可复算", path)]
    last_raw = blob_at(root, hist["L_pre"][-1], path)
    if last_raw is not None and head_raw is not None \
            and canonical(parse_seal(head_raw)) != canonical(parse_seal(last_raw)):
        out.append(_f("seal_path_retired_write", "error",
                      "retired 路径在迁出后被继续写入", path))
    if last_raw is not None:
        try:
            doc = parse_seal(last_raw)
        except SealError:
            doc = None
        head_doc_retired = None
        if head_raw is not None:
            try:
                head_doc_retired = parse_seal(head_raw)
            except SealError:
                head_doc_retired = None
        # v49/项 1：本键已写 `moved_to`（retired），封条（迁出前最后一枚或 HEAD
        # 保留的旧文件）再带 `reanchor` ⇒ 互斥。
        if any(isinstance(item, dict) and isinstance(item.get("reanchor"), dict)
               for item in (head_doc_retired, doc)):
            out.append(_f("seal_move_reanchor_conflict", "error",
                          "retired 封条（旧键 moved_to）同时带 reanchor", path,
                          {"kind": "moved_to_reanchor"}))
            return out
        if doc is not None:
            out.extend(analyze_chain(root, path, doc, anchor, "retired"))
    return out


def validate_seal_record(root: Path, data: dict, seal_path: str,
                         anchor: dict | None, assets_root: str, *,
                         bind_from: str | None) -> list[dict]:
    """`validate_apply_record` 的单封条入口（schema + upstream + 链）。"""
    findings: list[dict] = []
    raw = head_blob(root, seal_path)
    dirty = worktree_dirty(root, seal_path)
    if dirty:
        findings.append(_f("seal_worktree_dirty", "error",
                           "封条工作树不干净；链复算以 HEAD 为准", seal_path))
        return findings
    if raw is None:
        findings.append(_f("seal_absent", "error",
                           "HEAD 无该封条文件", seal_path))
        return findings
    try:
        seal = parse_seal(raw)
    except SealError as exc:
        return findings + [_f("seal_unparsable", "error", str(exc), seal_path)]
    if anchor is not None:
        findings.extend(analyze_state(root, seal_path, anchor,
                                      assets_root, data, bind_from=bind_from))
    else:
        findings.extend(_schema_findings(root, data, seal, seal_path,
                                         assets_root, bind_from))
    return findings


def _schema_findings(root: Path, data: dict, seal: dict, seal_path: str,
                     assets_root: str, bind_from: str | None,
                     state: str = "active") -> list[dict]:
    out: list[dict] = []
    kind = seal.get("kind")
    if kind not in SEAL_KINDS:
        out.append(_f("seal_kind_invalid", "error",
                      f"kind 非法: {kind!r}", seal_path))
    if not isinstance(seal.get("e2e"), dict):
        out.append(_f("seal_e2e_missing", "error", "缺 e2e 段", seal_path))
    else:
        e2e = seal["e2e"]
        status = e2e.get("status")
        if status not in ("ready", "not_ready", "n/a"):
            out.append(_f("seal_e2e_status_invalid", "error",
                          f"e2e.status 非法: {status!r}", seal_path))
        gap = e2e.get("gap")
        if status in ("not_ready", "n/a"):
            if not isinstance(gap, dict) or not all(
                    gap.get(k) for k in ("reason", "owner", "due")):
                out.append(_f("seal_gap_missing", "error",
                              "not_ready / n/a 必须带 gap{reason,owner,due}",
                              seal_path))
            elif not DATE_RE.match(str(gap.get("due"))):
                out.append(_f("seal_gap_due_invalid", "error",
                              f"gap.due 非 YYYY-MM-DD: {gap.get('due')!r}",
                              seal_path))
        if status == "ready" and not (e2e.get("cases") or []):
            out.append(_f("seal_e2e_cases_empty", "error",
                          "e2e.status=ready 但 cases[] 为空", seal_path))
    if "backfill" in seal and not isinstance(seal.get("backfill"), dict):
        out.append(_f("seal_backfill_invalid", "error",
                      "backfill 不是对象", seal_path))
    # v49/项 1（§2.5、RFC L1616）：`moved_to` 写在**旧/retired** 封条上，`reanchor`
    # 写在同一封条即互斥。`moved_from` 在**新**封条上，与自己的 `reanchor` 允许
    # 并存，故这里只认 `moved_to`，绝不看 `moved_from`。
    if "moved_to" in seal and isinstance(seal.get("reanchor"), dict):
        out.append(_f("seal_move_reanchor_conflict", "error",
                      "同一封条同时带 moved_to 与 reanchor", seal_path,
                      {"kind": "moved_to_reanchor"}))
    probe = dict(seal)
    probe["__state"] = state
    out.extend(upstream_findings(root, data, probe, seal_path, assets_root,
                                 bind_from=bind_from))
    out.extend(_apply_record_findings(root, data, seal, seal_path))
    out.extend(_e2e_findings(root, data, seal, seal_path, assets_root))
    out.extend(_due_findings(seal, seal_path, data))
    return out


def _resolve_card_file(member_dir: Path, card_path: str) -> Path | None:
    """卡路径双解析（§1.3.6 / 重要 2）：先 active，未命中再 `archive/*/<ID>/<tail>`。

    封条 `card.path` 不随归档改写（§2.4 决策 6），卡归档后仍须能定位；
    归档命中不判新鲜度（只在调用方读字节 / 判跟踪）。
    """
    direct = member_dir / card_path
    if direct.is_file():
        return direct
    parts = Path(card_path).parts
    if len(parts) >= 4 and parts[0] == ".trellis" and parts[1] == "tasks":
        task_id, tail = parts[2], Path(*parts[3:]).as_posix()
        hits = sorted(member_dir.glob(
            f".trellis/tasks/archive/*/{task_id}/{tail}"))
        if hits:
            return hits[-1]
    return None


def _apply_record_findings(root: Path, data: dict, seal: dict,
                           seal_path: str) -> list[dict]:
    """§1.4：`kind=binding|backfill` 要求成员侧任务卡与 `atlas-apply.md` 存在。

    三态：成员子树未 checkout ⇒ **不可验证**（WARN，不是「卡确实缺」）；
    成员树在、封条指向的卡缺失 ⇒ `card_absent` FAIL；卡在、同目录
    `atlas-apply.md` 缺 ⇒ `apply_record_missing` FAIL。`legacy` 不走本判据（§3.1）。
    """
    if seal.get("kind") not in ("binding", "backfill"):
        return []
    match = SEAL_RE.match(seal_path)
    group = match.group("member") if match else ""
    member = next((m for m in data.get("members") or []
                   if m.get("name") == group
                   or Path(str(m.get("path"))).name == group), None)
    card = seal.get("card") if isinstance(seal.get("card"), dict) else {}
    card_path = card.get("path")
    if member is None or not card_path:
        return [_f("apply_record_missing", "warn",
                   "无法定位成员 / 封条未写 card.path；本项不可验证", seal_path,
                   {"kind": "unverifiable"})]
    member_dir = Path(root) / str(member["path"])
    if not member_dir.is_dir():
        return [_f("apply_record_missing", "warn",
                   f"成员子树未 checkout（{member['path']}/）；本项不可验证",
                   seal_path, {"kind": "member_not_checked_out"})]
    try:
        empty = not any(member_dir.iterdir())
    except OSError:
        empty = True
    rc, out, _ = _git(root, "ls-files", "-s", "--", str(member["path"]))
    is_gitlink = rc == 0 and out.strip().startswith("160000")
    rc2, top, _ = _git(member_dir, "rev-parse", "--show-toplevel")
    own_repo = (rc2 == 0 and bool(top.strip())
                and Path(top.strip()).resolve() == member_dir.resolve())
    if empty or (is_gitlink and not own_repo):
        # submodule / gitlink 未 init 时留下的是空目录：同样不可验证，不是「卡确实缺」。
        return [_f("apply_record_missing", "warn",
                   f"成员子树未 checkout（{member['path']}/ 为空或仅 gitlink）；本项不可验证",
                   seal_path, {"kind": "member_not_checked_out"})]
    card_file = _resolve_card_file(member_dir, str(card_path))
    if card_file is None:
        return [_f("card_absent", "error",
                   f"封条指向的任务卡在 active 与 archive 都不存在: {card_path}",
                   seal_path, {"kind": "card_absent", "card": str(card_path)})]
    rel_card = card_file.relative_to(member_dir).as_posix()
    # 卡必须被**成员仓**跟踪（C 批前置）；成员是嵌套仓时 `git -C` 落到成员仓，
    # 成员树直接内嵌父仓时落到父仓——两处都要求 `ls-files` 能命中这条路径。
    rc, _, _ = _git(member_dir, "ls-files", "--error-unmatch", "--", rel_card)
    if rc != 0:
        return [_f("card_untracked", "error",
                   f"任务卡未被 git 跟踪: {rel_card}", seal_path,
                   {"kind": "card_untracked", "card": rel_card})]
    apply_md = card_file.parent / "atlas-apply.md"
    if not apply_md.is_file():
        return [_f("apply_record_missing", "error",
                   f"kind={seal.get('kind')} 的封条缺 atlas-apply.md: "
                   f"{apply_md.relative_to(root)}", seal_path)]
    return []


def _case_map(items) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items or []:
        if isinstance(item, dict) and item.get("id"):
            out[str(item["id"])] = str(item.get("sha256") or "")
    return out


def _old_path_last_doc(root: Path, path: str) -> dict | None:
    """旧路径 `L_pre[-1]` 的封条文档（换路径首签的旧值来源）。"""
    hist = seal_history(root, path)
    if hist["error"] or not hist["L_pre"]:
        return None
    raw = blob_at(root, hist["L_pre"][-1], path)
    if raw is None:
        return None
    try:
        return parse_seal(raw)
    except SealError:
        return None


def _e2e_findings(root: Path, data: dict, seal: dict, seal_path: str,
                  assets_root: str) -> list[dict]:
    """§3.4 四步复算：旧 cases 子集 / 当前 body sha / changed ids / ready。"""
    e2e = seal.get("e2e") if isinstance(seal.get("e2e"), dict) else {}
    cases = e2e.get("cases") if isinstance(e2e.get("cases"), list) else []
    current: dict[str, str] = {}
    for item in cases:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        cid = str(item["id"])
        current[cid] = str(item.get("sha256") or "")
        actual = _case_sha(root, assets_root, cid)
        if item.get("sha256") != actual:
            yield _f("seal_e2e_case_sha_mismatch", "error",
                     f"用例 {cid} 的 body sha 与封条不符", seal_path)
    seq = seal.get("renewal_seq")
    moved = seal.get("moved_from")
    is_move = isinstance(moved, dict) and isinstance(moved.get("path"), str)
    old_cases: dict[str, str] = {}
    payload_equivalent = False
    if is_move:
        # 换路径首签：旧值来自**旧路径** `L_pre[-1]`，不是本路径的 previous
        old_doc = _old_path_last_doc(root, str(moved["path"]))
        if old_doc is None:
            yield _f("seal_path_history_lost", "error",
                     f"旧路径封条不可读: {moved['path']}", seal_path)
            return
        old_e2e = old_doc.get("e2e") if isinstance(old_doc.get("e2e"), dict) else {}
        old_cases = _case_map(old_e2e.get("cases"))
        payload_equivalent = (_payload_of(old_doc, MOVE_EXEMPT)
                              == _payload_of(seal, MOVE_EXEMPT))
    else:
        prev_doc = None
        prev_commit = seal.get("previous_seal_commit")
        if seq and seq > 1 and prev_commit:
            raw = blob_at(root, str(prev_commit), seal_path)
            if raw is None:
                # 边界封条 previous 指向不可达旧 A：回落到 L[-2]（重写后的上一枚）
                hist = seal_history(root, seal_path)
                if not hist["error"] and len(hist["commits"]) >= 2:
                    raw = blob_at(root, hist["commits"][-2], seal_path)
            if raw is not None:
                try:
                    prev_doc = parse_seal(raw)
                except SealError:
                    prev_doc = None
        if isinstance(prev_doc, dict):
            old_e2e = prev_doc.get("e2e") if isinstance(prev_doc.get("e2e"), dict) else {}
            old_cases = _case_map(old_e2e.get("cases"))
    declared_changed = list(e2e.get("changed_case_ids") or [])
    declared_prev = _case_map(e2e.get("previous_cases"))
    if is_move and payload_equivalent:
        # 换路径 = 载荷逐字节复制（`_move_payload` 是唯一判定来源）：e2e 业务字段
        # 是被搬过来的旧载荷，不按用例变化重算，否则合法搬路径必红。
        pass
    elif is_move:
        computed_changed = sorted(cid for cid, sha in current.items()
                                  if old_cases.get(cid) != sha)
        if sorted(declared_changed) != computed_changed:
            yield _f("seal_e2e_changed_case_ids_mismatch", "error",
                     f"changed_case_ids 声明 {sorted(declared_changed)} != 复算 "
                     f"{computed_changed}", seal_path)
        expected_prev = {cid: old_cases[cid] for cid in computed_changed
                         if cid in old_cases}
        if declared_prev != expected_prev:
            yield _f("seal_e2e_previous_cases_mismatch", "error",
                     f"previous_cases={declared_prev} != 旧 cases 子集 "
                     f"{expected_prev}", seal_path)
    else:
        computed_changed = sorted(cid for cid, sha in current.items()
                                  if old_cases.get(cid) != sha) \
            if seq and seq > 1 else []
        if seq == 1 and e2e.get("previous_cases"):
            yield _f("seal_e2e_previous_cases_mismatch", "error",
                     "首签 previous_cases 必须为空", seal_path)
        if sorted(declared_changed) != computed_changed:
            yield _f("seal_e2e_changed_case_ids_mismatch", "error",
                     f"changed_case_ids 声明 {sorted(declared_changed)} != 复算 "
                     f"{computed_changed}", seal_path)
        expected_prev = {cid: old_cases[cid] for cid in computed_changed
                         if cid in old_cases}
        if declared_prev != expected_prev:
            yield _f("seal_e2e_previous_cases_mismatch", "error",
                     f"previous_cases={declared_prev} != 旧 cases 子集 {expected_prev}",
                     seal_path)
    if e2e.get("status") == "ready":
        wanted = sorted({cid for req in data.get("requirements") or []
                         for cid in req.get("case_ids") or []})
        if e2e.get("selector_sha256") != selector_sha256(wanted):
            yield _f("seal_e2e_selector_mismatch", "error",
                     "selector_sha256 与 manifest case_ids 集合不符", seal_path)
        index = Path(root) / assets_root / "e2e" / "e2e-index.md"
        index_text = index.read_text(encoding="utf-8") if index.is_file() else ""
        for cid in current:
            if not _case_file_exists(root, assets_root, cid):
                yield _f("seal_e2e_case_missing", "error",
                         f"用例分片不存在: {cid}", seal_path)
            elif not re.search(rf"^##\s+{re.escape(cid)}\s*$", index_text, re.M):
                yield _f("seal_e2e_case_missing", "error",
                         f"索引主表缺用例块: {cid}", seal_path)


def _case_file_exists(root: Path, assets_root: str, case_id: str) -> bool:
    return (Path(root) / assets_root / "e2e" / "cases" / f"{case_id}.md").is_file()


def analyze(root: Path, data: dict, lock: dict | None, roots: list[str], *,
            bind_from: str | None) -> list[dict]:
    """仓级封条判据：仓形态 → ⓪-2 → 路径宇宙 → 每键状态/链。

    `roots` 是锁历史根并集 `UH`（由 `solution.py` 的同一严格解析器算出）。
    ⓪-3 / ⓪-4 在 `solution.py::check_solution` 里判，本函数只消费 `roots`。
    """
    findings: list[dict] = []
    if lock is None:
        # 锁缺失但 HEAD 有封条：不得返回 N/A（B1）；逐枚报键缺失。
        if head_seals(root, roots or []):
            return [_f("seal_anchor_path_unmapped", "error",
                       "锁缺失，但 HEAD 存在封条；先 lock --update", path)
                    for path in head_seals(root, roots or [])]
        return findings
    anchors = lock.get("seal_anchors")
    by_path: dict[str, dict] = {}
    if isinstance(anchors, dict):
        by_path = {str(k): v for k, v in anchors.items() if isinstance(v, dict)}
    elif anchors not in (None, {}):
        findings.append(_f("seal_anchors_invalid", "error",
                           "seal_anchors 既不是 null 也不是对象", "atlas.solution.lock.json"))
        return findings
    # 无锚且无封条文件 ⇒ 本子系统未接入，不重复报 chain_unverifiable
    if not by_path and not head_seals(root, roots or []):
        return findings
    cause, detail = repo_shape(root)
    if cause:
        return [_f("chain_unverifiable", "error", f"chain_unverifiable: {detail}",
                   None, {"cause": cause})]
    if lock.get("schema_version") == 1 and by_path:
        findings.append(_f("lock_v1_with_seals", "error",
                           "schema_version=1 的锁不得有 seal_anchors", "atlas.solution.lock.json"))
    universe, _ = seal_universe(root, roots) if roots else (set(), set())
    unsupported = [key for key in by_path if roots and
                   not key_matches_root(key, roots)]
    for key in sorted(unsupported):
        findings.append(_f("seal_path_unsupported", "error",
                           f"键不匹配任何历史根的两段谓词: {key}", key))
    valid_keys = {key for key in by_path if key not in unsupported}
    for key in sorted(universe - valid_keys):
        findings.append(_f("seal_anchor_path_unmapped", "error",
                           f"历史新增封条路径缺锁内键: {key}", key))
    for key in sorted(valid_keys - universe):
        findings.append(_f("seal_anchor_path_orphaned", "error",
                           f"锁内键从未在 U 中出现: {key}", key))
    enriched = dict(data)
    enriched["__seal_anchors"] = by_path
    for key in sorted(valid_keys & universe):
        findings.extend(analyze_state(root, key, by_path[key],
                                      lock.get("layout_assets_root")
                                      or _root_of(key), enriched,
                                      bind_from=bind_from))
    # 锚字段（T-28 / T-30 / T-32）
    for key, anchor in sorted(by_path.items()):
        if key in unsupported:
            continue
        head_raw = head_blob(root, key)
        if head_raw is None:
            continue
        try:
            head_doc = parse_seal(head_raw)
        except SealError:
            continue
        findings.extend(check_anchor_fields(root, key, anchor, head_doc,
                                            data, lock))
    return findings


def _root_of(key: str) -> str:
    m = SEAL_RE.match(key)
    return m.group("root") if m else "product"


def check_anchor_fields(root: Path, path: str, anchor: dict, head_doc: dict,
                        data: dict, lock: dict) -> list[dict]:
    """锁内自述值与封条字节的等值 / 形态 / 区间判据（T-28、T-30⑥、T-32）。"""
    out: list[dict] = []
    hist = seal_history(root, path)
    L = hist["commits"] if not hist.get("error") else []
    started = anchor.get("exemption_started_at")
    origin = anchor.get("exemption_start_origin")
    first_seen = anchor.get("first_seen_origin")
    if not SIGNED_AT_RE.match(str(started or "")):
        out.append(_f("exemption_start_signed_at_not_canonical", "error",
                      f"exemption_started_at 非规范形态: {started!r}", path))
        return out
    first_doc = None
    if L:
        raw = blob_at(root, L[0], path)
        if raw is not None:
            try:
                first_doc = parse_seal(raw)
            except SealError:
                first_doc = None
    chain = anchor.get("exemption_start_history")
    if chain is None:
        chain = []
    if not isinstance(chain, list):
        out.append(_f("exemption_start_history_broken", "error",
                      "exemption_start_history 不是数组", path))
        return out
    # v49/项 2：`retired` 键的 `epoch_origin` 已固化（不随历史重写重指），读侧不再
    # 判锚可达性 / 起点等值——本块（`chain_unverifiable` / `exemption_start_origin_
    # rewritten` / `exemption_start_conflict`）只对 `active` / `frozen` 生效。
    if anchor.get("state") != "retired" and first_doc is not None \
            and "reanchor" not in head_doc and "moved_from" not in head_doc:
        signed = first_doc.get("signed_at")
        if not SIGNED_AT_RE.match(str(signed or "")):
            out.append(_f("signed_at_not_canonical", "error",
                          f"L[0].signed_at 非规范形态: {signed!r}", path))
            return out
        # T-30①：`exemption_start_origin` **不可变**，外部锚 = 锁历史首个含该字段的
        # 版本里的值（v23/I-1；v24/B-2 取法）。重指后 `L[0]` 会变，不能拿它当锚，
        # 否则「重指 + 重签」永久红且二次 `lock --update` 不自愈。
        entry = _anchor_entry_in_history(root, path, "exemption_start_origin")
        epoch_history = anchor.get("epoch_origin_history")
        epoch_history = epoch_history if isinstance(epoch_history, list) else []
        # v49/项 3（RFC L1198）：两态不得合并。
        # ① 首次信任（TOFU）：`epoch_origin_history` 长度 1、其值 == `L[0]`、
        #    `anchor_review == null`、封条不带 `reanchor` ⇒ 首次建立时不存在被改写的
        #    历史，锚自指是事实，不报 `chain_unverifiable`（否则任何首签永久红）。
        first_trust = (len(epoch_history) == 1
                       and epoch_history[0] == L[0]
                       and anchor.get("anchor_review") in (None, "")
                       and not isinstance(head_doc.get("reanchor"), dict))
        # ② 重指痕迹：epoch 历史多于一项 / 有过 anchor_review / 封条带 reanchor /
        #    当前 epoch_origin 已不是 L[0]（重写后旧纪元仍留在锁里）。
        repointed = (len(epoch_history) > 1
                     or anchor.get("anchor_review") not in (None, "")
                     or isinstance(head_doc.get("reanchor"), dict)
                     or str(anchor.get("epoch_origin")) != L[0])
        self_ref = entry is not None and entry[0] == L[0]
        truncated = bool(chain) and len(epoch_history) <= 1
        # ① 不判红；② 有痕迹而锚仍自指（或取不到锚 / epoch 历史被压平）⇒ fail-closed。
        if not first_trust and ((entry is None and repointed) or truncated
                                or (self_ref and repointed)):
            out.append(_f("chain_unverifiable", "error",
                          "重指后无法取得独立外部锚（锚自指或 epoch 历史被压平）",
                          path, {"cause": "anchor_not_independent"}))
            return out
        if entry is not None and not self_ref:
            anchor_origin = entry[1]
            if origin != anchor_origin:
                out.append(_f("exemption_start_origin_rewritten", "error",
                              "exemption_start_origin 与锁历史锚不等"
                              "（历史豁免起点被改写）", path,
                              {"kind": "rewritten"}))
                return out
        if started != signed:
            out.append(_f("exemption_start_conflict", "error",
                          "exemption_started_at 与 L[0].signed_at 不逐字节相等",
                          path, {"kind": "not_equal_signed_at"}))
    if first_seen is not None:
        if not SIGNED_AT_RE.match(str(first_seen)):
            out.append(_f("first_seen_origin_rewritten", "error",
                          f"first_seen_origin 非规范形态: {first_seen!r}",
                          path, {"kind": "not_canonical"}))
        elif first_doc is not None and \
                str(first_seen) > str(first_doc.get("signed_at") or ""):
            out.append(_f("first_seen_origin_rewritten", "error",
                          "first_seen_origin 晚于 L[0].signed_at", path,
                          {"kind": "after_signed_at"}))
    if chain:
        prev_to = origin
        for index, entry in enumerate(chain):
            if not isinstance(entry, dict):
                out.append(_f("exemption_start_history_broken", "error",
                              f"history[{index}] 不是对象", path))
                return out
            if entry.get("from") != prev_to:
                out.append(_f("exemption_start_history_broken", "error",
                              f"history[{index}].from 与前项 to 不连续", path))
                return out
            prev_to = entry.get("to")
        if prev_to != started:
            out.append(_f("exemption_start_history_broken", "error",
                          "history 末项 to 与 exemption_started_at 不等", path))
    else:
        if origin != started:
            out.append(_f("exemption_start_history_broken", "error",
                          "无重指时 exemption_start_origin 必须等于 "
                          "exemption_started_at", path))
    if SIGNED_AT_RE.match(str(origin or "")) and SIGNED_AT_RE.match(str(started or "")) \
            and str(origin) > str(started):
        out.append(_f("exemption_start_history_broken", "error",
                      "exemption_start_origin > exemption_started_at", path))
    # due 读侧：把锁锚注入后复用同一区间判据
    e2e = head_doc.get("e2e") if isinstance(head_doc.get("e2e"), dict) else {}
    gap = e2e.get("gap") if isinstance(e2e.get("gap"), dict) else {}
    if gap.get("due"):
        probe = dict(head_doc)
        probe["__origin"] = origin or ""
        probe["__first_seen_origin"] = first_seen or ""
        out.extend(_due_findings(probe, path, data))
    return out


def compute_anchor(root: Path, path: str, prior: dict | None,
                   head_doc: dict | None, head_commit: str | None,
                   *, all_prior: dict | None = None) -> dict:
    """`lock --update` 写单个键的值（§1.1.3 第 3 条 / ⑦，受控重指）。

    已有值一律保留（只刷新 `renewal_seq` / `n`；`retired` / `frozen` 全保留）。
    新键：`epoch_origin = L[0]`、`exemption_start_* = L[0].signed_at`、
    `first_seen_origin = 封条 first_seen_at`。

    `all_prior` 是**同一次 `--update` 的锁内全量键**（不传才回落磁盘锁）：
    换路径继承必须读本次快照，不能读到上一次写盘的旧锁。
    """
    hist = seal_history(root, path)
    if hist["error"] or not hist["commits"]:
        raise SealError(f"{path}: 封条路径历史不可读，拒绝建键")
    L = hist["commits"]
    seq = (head_doc or {}).get("renewal_seq")
    prior = prior if isinstance(prior, dict) else None
    others = all_prior if isinstance(all_prior, dict) else _lock_anchors(root)
    state = (prior or {}).get("state") or "active"
    if state in ("retired", "frozen") and prior is not None:
        anchor = dict(prior)
        if state == "retired":
            anchor["n"] = len(hist["L_pre"])
        return anchor
    if prior is None:
        first_raw = blob_at(root, L[0], path)
        first_doc = parse_seal(first_raw) if first_raw else {}
        signed = first_doc.get("signed_at")
        anchor = {
            "epoch_origin": L[0],
            "epoch_origin_history": [L[0]],
            "renewal_seq": seq if isinstance(seq, int) else 0,
            "n": len(L),
            "anchor_review": None,
            "state": "active",
            "exemption_start_origin": signed,
            "exemption_started_at": signed,
            "exemption_start_history": [],
            "first_seen_origin": first_doc.get("first_seen_at"),
        }
        moved = (head_doc or {}).get("moved_from")
        if isinstance(moved, dict) and moved.get("path"):
            old_anchor = others.get(str(moved["path"]))
            if not isinstance(old_anchor, dict):
                raise SealError(
                    "seal_path_history_lost: moved_from 链首键缺失 "
                    f"{moved['path']}")
            for key in ("exemption_start_origin", "exemption_started_at",
                        "exemption_start_history", "first_seen_origin"):
                if key in old_anchor:
                    anchor[key] = copy.deepcopy(old_anchor[key])
        return anchor
    anchor = dict(prior)
    anchor["renewal_seq"] = seq if isinstance(seq, int) else prior.get("renewal_seq")
    anchor["n"] = len(L)
    anchor.setdefault("epoch_origin_history", [anchor.get("epoch_origin")])
    reanchor = (head_doc or {}).get("reanchor")
    if isinstance(reanchor, dict):
        # §3.2 规则 10：epoch_origin 推进到**写 reanchor 的那个提交 R0**，不是 L[0]。
        record = _reanchor_commit(root, path, L)
        if record and anchor.get("epoch_origin") != record:
            anchor["epoch_origin"] = record
            history = list(anchor["epoch_origin_history"])
            if record not in history:
                history.append(record)
            anchor["epoch_origin_history"] = history
        if not anchor.get("anchor_review"):
            anchor["anchor_review"] = reanchor.get("review")
    # 受控重指（S-45）：首签 + active + 锁历史从未 reanchor + 旧锚不在 HEAD 历史。
    # §1.1.3 第 3 条：不设次数上限（I8），由「从未 reanchor」保证不可绕过。
    origin_commit = str(anchor.get("epoch_origin") or "")
    ancestor_rc = _ancestor_rc(root, origin_commit) if origin_commit else 1
    if ancestor_rc not in (0, 1, 128):
        raise SealError(
            f"{path}: merge-base --is-ancestor {origin_commit[:12]} HEAD 失败"
            f"（rc={ancestor_rc}）")
    if (reanchor is None and seq == 1 and anchor.get("state") == "active"
            and not _anchor_value_in_history(root, path, "anchor_review")
            and anchor.get("epoch_origin") != L[0]
            and ancestor_rc in (1, 128)):
        new_started = (head_doc or {}).get("signed_at")
        old_started = anchor.get("exemption_started_at")
        history = list(anchor.get("exemption_start_history") or [])
        # 写侧不得用**未核验**的 old_started 编审计链：只有「无既有链且起点就是
        # 不可变 origin」时，才把这次同步记成一条可复核的 from→to。
        if (not history and old_started
                and old_started == anchor.get("exemption_start_origin")
                and isinstance(new_started, str)
                and new_started != old_started):
            history.append({"from": old_started, "to": new_started,
                            "commit": head_commit or _rev_parse(root, "HEAD")})
        anchor["exemption_started_at"] = new_started or old_started
        anchor["exemption_start_history"] = history
        anchor["epoch_origin"] = L[0]
        anchor["epoch_origin_history"].append(L[0])
    if anchor.get("exemption_start_origin") is None:
        anchor["exemption_start_origin"] = anchor.get("exemption_started_at")
    if anchor.get("exemption_started_at") is None:
        anchor["exemption_started_at"] = anchor.get("exemption_start_origin")
    if anchor.get("exemption_start_history") is None:
        anchor["exemption_start_history"] = []
    if anchor.get("first_seen_origin") is None:
        anchor["first_seen_origin"] = (head_doc or {}).get("first_seen_at")
    # B5：换路径新键必须继承链首键的豁免起点，不得重置 90 天窗口。
    # 已有历史（本路径做过 reanchor）时不再回灌旧键，否则会把重指结果冲掉。
    moved = (head_doc or {}).get("moved_from")
    if (isinstance(moved, dict) and moved.get("path")
            and not anchor.get("exemption_start_history")):
        old_anchor = others.get(str(moved["path"]))
        if not isinstance(old_anchor, dict):
            raise SealError(
                f"seal_path_history_lost: moved_from 链首键缺失 {moved['path']}")
        for key in ("exemption_start_origin", "exemption_started_at",
                    "exemption_start_history", "first_seen_origin"):
            if key in old_anchor:
                anchor[key] = copy.deepcopy(old_anchor[key])
    return anchor


def _reanchor_commit(root: Path, path: str, commits: list[str]) -> str | None:
    """L 中承载 `reanchor` 对象的提交（R0）；多条取最新。"""
    for commit in reversed(commits):
        raw = blob_at(root, commit, path)
        if raw is None:
            continue
        try:
            doc = parse_seal(raw)
        except SealError:
            continue
        if isinstance(doc.get("reanchor"), dict):
            return commit
    return None


def _lock_anchors(root: Path) -> dict:
    path = Path(root) / "atlas.solution.lock.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    anchors = doc.get("seal_anchors")
    return {str(k): v for k, v in anchors.items()
            if isinstance(v, dict)} if isinstance(anchors, dict) else {}


def _lock_anchor_versions(root: Path, path: str) -> list[tuple[str, dict]]:
    """锁文件全历史里该封条路径的锚（`(提交, 锚)` 正序；不可解析 / 无键的版本跳过）。"""
    rc, out, _ = _git(root, "log", "-m", "--full-history", "--reverse",
                      "--format=%H", "HEAD", "--", "atlas.solution.lock.json")
    if rc != 0:
        return []
    versions: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for commit in out.split():
        if commit in seen:
            continue
        seen.add(commit)
        raw = blob_at(root, commit, "atlas.solution.lock.json")
        if raw is None:
            continue
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            continue
        anchors = doc.get("seal_anchors") if isinstance(doc, dict) else None
        anchor = anchors.get(path) if isinstance(anchors, dict) else None
        if isinstance(anchor, dict):
            versions.append((commit, anchor))
    return versions


def _anchor_entry_in_history(root: Path, path: str,
                             field: str) -> tuple[str, object] | None:
    """外部锚：锁历史中**首个同时含该字段**的 `(提交, 值)`（无 ⇒ `None`）。"""
    for commit, anchor in _lock_anchor_versions(root, path):
        if field in anchor:
            return commit, anchor[field]
    return None


def _anchor_value_in_history(root: Path, path: str, field: str):
    entry = _anchor_entry_in_history(root, path, field)
    return entry[1] if entry else None


def select_seal(root: Path, anchors: dict | None, requested: str | None,
                candidates: list[str] | None = None) -> str:
    """多封条选择（S-37）：不给 `--seal` 且有多个候选 ⇒ exit 2 候选列表。"""
    paths = sorted(set(candidates or []))
    if requested:
        return requested
    if len(paths) == 1:
        return paths[0]
    if not paths:
        raise SealError("仓内没有封条；先签发一枚封条")
    raise SealError("存在多枚封条，必须用 --seal <path> 指定；候选：\n  "
                    + "\n  ".join(paths))


def head_seals(root: Path, roots: list[str]) -> list[str]:
    found: set[str] = set()
    for asset_root in roots:
        base = Path(root) / asset_root / "reviews" / "apply"
        if not base.is_dir():
            continue
        for path in base.rglob("*.seal.json"):
            rel = str(path.relative_to(root))
            if is_seal_path(rel):
                found.add(rel)
    return sorted(found)


def build_seal_payload(root: Path, data: dict, seal_path: str, *,
                       assets_root: str, kind: str = "binding",
                       card_path: str | None = None,
                       acceptance_acs: list[str] | None = None,
                       e2e_status: str = "n/a",
                       case_ids: list[str] | None = None,
                       gap: dict | None = None,
                       owner: str | None = None,
                       first_seen_at: str | None = None,
                       moved_from: dict | None = None,
                       reasons: list[str] | None = None,
                       previous_cases: list[dict] | None = None,
                       now: datetime | None = None) -> dict:
    """构造封条载荷（写侧唯一入口；`signed_at` 由工具生成）。"""
    now = now or datetime.now(timezone.utc)
    signed_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    head_raw = head_blob(root, seal_path)
    hist = seal_history(root, seal_path)
    explicit_move = moved_from is not None
    old_doc: dict | None = None
    if head_raw is not None:
        old_doc = parse_seal(head_raw)
        seq = int(old_doc.get("renewal_seq") or 1) + 1
        prev_commit = hist["commits"][-1] if hist["commits"] else None
        prev_sha = seal_sha256(head_raw)
        base_first = old_doc.get("first_seen_at") or (old_doc.get("backfill") or {}).get("first_seen_at")
        base_card = old_doc.get("card")
        base_e2e = old_doc.get("e2e") if isinstance(old_doc.get("e2e"), dict) else {}
    else:
        seq = 1
        prev_commit = None
        prev_sha = None
        base_first = None
        base_card = None
        base_e2e = {}
    if moved_from is not None:
        # 换路径不是重签：seq=1、previous_* = null、signed_at 沿用旧值
        seq, prev_commit, prev_sha = 1, None, None
        old_raw = None
        old_path = moved_from.get("path")
        if old_path:
            old_hist = seal_history(root, old_path)
            if not old_hist["error"] and old_hist["L_pre"]:
                old_raw = blob_at(root, old_hist["L_pre"][-1], old_path)
        if old_raw is None:
            raise SealError(f"换路径：旧路径封条不可读: {old_path}")
        old_doc = parse_seal(old_raw)
        signed_at = old_doc.get("signed_at", signed_at)
        base_first = old_doc.get("first_seen_at") or base_first
        base_card = old_doc.get("card")
        base_e2e = old_doc.get("e2e") if isinstance(old_doc.get("e2e"), dict) else {}
        moved_from = dict(moved_from)
        moved_from["sha256"] = moved_from.get("sha256") or seal_sha256(old_raw)
    elif old_doc is not None and isinstance(old_doc.get("moved_from"), dict):
        # B4：已迁出的封条在后续续签里必须继续携带 moved_from
        moved_from = dict(old_doc["moved_from"])
    if explicit_move and old_doc is not None:
        # 换路径首签：除豁免字段外必须与旧路径最后封条逐字节相同。
        payload = {k: copy.deepcopy(v) for k, v in old_doc.items()
                   if not k.startswith("__")}
        payload["renewal_seq"] = 1
        payload["previous_seal_commit"] = None
        payload["previous_seal_sha256"] = None
        payload["signed_at"] = signed_at
        payload["moved_from"] = moved_from
        if reasons:
            payload["reasons"] = list(reasons)
            # 换路径 + **真的**换了用例：e2e / upstream 必须按当前树复算，不能整段
            # 沿用旧载荷；纯改名（用例没变）保持复制，避免把注释写进业务载荷。
            current_cases = [{"id": cid, "sha256": _case_sha(root, assets_root, cid)}
                             for cid in sorted(set(case_ids or []))]
            e2e = _e2e_payload(data, current_cases, e2e_status, gap,
                               base_e2e, old_doc, None, first=False)
            if e2e.get("changed_case_ids"):
                payload["e2e"] = e2e
                payload["upstream"] = _upstream_entries(root, data, assets_root)
        return payload
    projection = {
        "acceptance_acs": sorted(set(acceptance_acs or [])),
        "exemption": None,
    }
    projection["sha256"] = projection_sha(projection)
    card = {"path": card_path or (base_card or {}).get("path"),
            "projection": projection}
    cases = [{"id": cid, "sha256": _case_sha(root, assets_root, cid)}
             for cid in sorted(set(case_ids or []))]
    e2e = _e2e_payload(data, cases, e2e_status, gap, base_e2e, old_doc,
                       previous_cases, first=(seq == 1))
    payload = {
        "kind": kind,
        "renewal_seq": seq,
        "previous_seal_sha256": prev_sha,
        "previous_seal_commit": prev_commit,
        "signed_at": signed_at,
        "first_seen_at": first_seen_at or base_first or signed_at,
        "e2e": e2e,
        "card": card,
        "upstream": _upstream_entries(root, data, assets_root),
    }
    if isinstance(e2e.get("gap"), dict):
        payload["backfill"] = {"first_seen_at": payload["first_seen_at"],
                               "due": e2e["gap"].get("due"),
                               "owner": e2e["gap"].get("owner") or owner}
    if moved_from is not None:
        payload["moved_from"] = moved_from
    # B4：reanchor 对象必须被后续续签原样继承，否则 epoch_origin 守卫失效。
    # 换路径后的续签同样要保留（`moved_from` 与 `reanchor` 可同时存在）。
    if old_doc is not None and isinstance(old_doc.get("reanchor"), dict):
        payload["reanchor"] = old_doc["reanchor"]
    if reasons:
        payload["reasons"] = list(reasons)
    return payload


def selector_sha256(case_ids: list[str]) -> str:
    return seal_sha256(canonical(sorted(set(case_ids))))


def _case_links(data: dict, case_ids: list[str]) -> list[dict]:
    wanted = set(case_ids)
    links: dict[str, list[str]] = {}
    for req in data.get("requirements") or []:
        acs = sorted(set(req.get("acs") or []))
        for cid in req.get("case_ids") or []:
            if cid in wanted:
                links[cid] = acs
    return [{"case_id": cid, "acs": links[cid]} for cid in sorted(links)]


def _e2e_payload(data: dict, cases: list[dict], status: str,
                 gap: dict | None, base_e2e: dict, old_doc: dict | None,
                 previous_cases: list[dict] | None, *,
                 first: bool = False) -> dict:
    """§3.4：cases / links / changed_case_ids / previous_cases 的写侧复算。"""
    old_cases = {}
    if isinstance(base_e2e.get("cases"), list):
        old_cases = {str(item.get("id")): item.get("sha256")
                     for item in base_e2e["cases"] if isinstance(item, dict)}
    current = {item["id"]: item["sha256"] for item in cases}
    changed = ([] if first else sorted(
        cid for cid, sha in current.items() if old_cases.get(cid) != sha))
    previous = ([{"id": cid, "sha256": old_cases[cid]}
                 for cid in changed if cid in old_cases]
                if previous_cases is None else list(previous_cases))
    # 读侧（`_e2e_findings`）按 manifest 全集复算 selector；写侧必须同口径，
    # 否则「合法只绑子集」的封条会被判 `seal_e2e_selector_mismatch`。
    wanted = sorted({cid for req in data.get("requirements") or []
                     for cid in req.get("case_ids") or []})
    return {
        "status": status,
        "selector_sha256": selector_sha256(wanted),
        "cases": cases,
        "links": _case_links(data, list(current)),
        "changed_case_ids": changed,
        "previous_cases": previous,
        "gap": gap,
    }


def _upstream_entries(root: Path, data: dict, assets_root: str) -> list[dict]:
    resolved = resolve_upstreams(root, data, assets_root)
    rows: list[dict] = []
    for role in ROLES:
        for path in resolved.get(role, []):
            sha = _sha_for(root, path)
            if sha is None:
                continue
            rows.append({"role": role, "path": path, "sha256": sha})
    return rows


def _case_sha(root: Path, assets_root: str, case_id: str) -> str:
    path = Path(root) / assets_root / "e2e" / "cases" / f"{case_id}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    m = re.search(r"```atlas-case\n(.*?)```", text, re.S)
    body = m.group(1) if m else ""
    return seal_sha256(body.rstrip("\n").encode("utf-8"))


def reanchor_payload(head_doc: dict, *, from_a: str, review: str,
                     now: datetime | None = None) -> dict:
    """`seal reanchor` 的新封条载荷（只改五个字段 + reanchor）。"""
    if not REVIEW_ID_RE.match(review):
        raise SealError(f"--review 形态非法: {review!r}（REVIEW-YYYYMMDD-NN）")
    seq = head_doc.get("renewal_seq")
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
        raise SealError("HEAD 封条 renewal_seq 非法，无法 reanchor")
    now = now or datetime.now(timezone.utc)
    payload = {k: v for k, v in head_doc.items() if not k.startswith("__")}
    payload["renewal_seq"] = seq + 1
    payload["previous_seal_commit"] = from_a
    payload["previous_seal_sha256"] = None
    payload["signed_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    payload["reanchor"] = {
        "base_seq": seq + 1,
        "base_n": None,          # 由调用方用 N 填
        "from_a": from_a,
        "review": review,
    }
    return payload


def _due_findings(seal: dict, seal_path: str, data: dict) -> list[dict]:
    """`gap.due` 读侧闭区间（§2.4 决策 3 / T-32）。"""
    e2e = seal.get("e2e") if isinstance(seal.get("e2e"), dict) else {}
    gap = e2e.get("gap") if isinstance(e2e.get("gap"), dict) else {}
    due_raw = gap.get("due")
    if not due_raw:
        return []
    if not DATE_RE.match(str(due_raw)):
        return [_f("exemption_due_out_of_range", "error",
                   f"gap.due 非日期形态: {due_raw!r}", seal_path)]
    try:
        due = date.fromisoformat(str(due_raw))
    except ValueError:
        return [_f("exemption_due_out_of_range", "error",
                   f"gap.due 非真实日期: {due_raw!r}", seal_path)]
    origin = (seal.get("__origin") or "").strip()
    first_seen = (seal.get("__first_seen_origin")
                  or seal.get("first_seen_at") or "")
    upper: date | None = None
    if DATE_RE.match(str(data.get("acceptance_cutover") or "")):
        upper = date.fromisoformat(str(data["acceptance_cutover"]))
    if SIGNED_AT_RE.match(first_seen):
        d = date.fromisoformat(first_seen[:10])
        plus = d + timedelta(days=90)
        upper = plus if upper is None else min(upper, plus)
    lower: date | None = None
    if SIGNED_AT_RE.match(origin):
        lower = date.fromisoformat(origin[:10])
    elif DATE_RE.match(origin):
        lower = date.fromisoformat(origin)
    if lower and due < lower:
        return [_f("exemption_due_out_of_range", "error",
                   f"gap.due={due} 早于 exemption_start_origin={lower}",
                   seal_path)]
    if upper and due > upper:
        return [_f("exemption_due_out_of_range", "error",
                   f"gap.due={due} 晚于上界 {upper}", seal_path)]
    return []
