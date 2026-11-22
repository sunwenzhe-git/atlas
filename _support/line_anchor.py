#!/usr/bin/env python3
"""行级锚定复算（RFC-20261122-08）—— 评审产物行号的确定性测量面，算法单源。

只读测量：复算不改写行号、不进指纹（`review_policy.compute_fingerprint` 的
clean_target_file 仍剥行号）、不参与判收；失败语义由调用方
`try/except (OSError, subprocess.SubprocessError)` 包住降级 WARN（RFC §2.1-件②
约束①，永不 die——与 cli_review_convert 的快速失败文化隔离）。

算法对照 alibaba/open-code-review `internal/diff/resolver.go`（Apache-2.0，tree
284ff013f0705ae6）移植：normalizeLine / splitAndNormalize / matchConsecutive /
extractSideLines(newSide) / resolveFromFileContent；仓内 hunk 头解析先例 =
`scripts/changelog_guard.py:45` HUNK_RE。

口径（RFC §2.1-件②，评审复核 R-2/R-3/R-4/R-5 处置已落）：
- 四态 + unresolvable：anchored（reported 与 resolved 区间相交，含子集）/
  mismatch（命中但无交集）/ unresolved（报了行号，L1+L2 均无果）/
  unanchored(legacy|no_field) / unresolvable（binary 文件或 diff 基准不可得，
  不计入漂移率分子分母）。
- 两级匹配：L1 = diff hunk 新侧（行号由 hunk 头计数器推算）→ L2 = 全工作树
  文件回退（pre_existing / path 不在 diff 的必经之路——path 不在 diff 输出
  ⇒ 跳 L1 直入 L2，不算 unresolvable）。
- diff 基准分模式（R-3）：staged ⇒ `git diff --cached`（INDEX 非合法 ref）；
  range/delta ⇒ `git diff <base>..<head>`；一律 -U0 --no-renames。
- 匹配确定性：归一化后**首处命中即 resolved**（文件头顺序扫描，无并列策略）。

纯标准库。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

# changelog_guard.py:45 同款 hunk 头形态（新侧起点/行数）
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

STATES = ("anchored", "mismatch", "unresolved",
          "unanchored_legacy", "unanchored_no_field", "unresolvable")


def normalize_line(s: str) -> str:
    """OCR resolver.go normalizeLine 同款：trim → 剥行首 +/- → trim。"""
    s = s.strip()
    s = s.removeprefix("+")
    s = s.removeprefix("-")
    return s.strip()


def split_normalize(code: str) -> list[str]:
    """OCR splitAndNormalize 同款：切行、归一化、跳空行。"""
    result = []
    for raw in str(code or "").split("\n"):
        n = normalize_line(raw)
        if n:
            result.append(n)
    return result


def match_consecutive(side_lines: list[tuple[int, str]],
                      targets: list[str]) -> tuple[int, int] | None:
    """OCR matchConsecutive 同款：滑窗找 targets 的连续首处命中。

    side_lines 元组 = (新/旧文件行号, 归一化内容)；返回 (start, end) 或 None。
    """
    if not targets or len(side_lines) < len(targets):
        return None
    for i in range(len(side_lines) - len(targets) + 1):
        if all(side_lines[i + j][1] == targets[j] for j in range(len(targets))):
            return (side_lines[i][0], side_lines[i + len(targets) - 1][0])
    return None


def parse_file_diffs(diff_text: str) -> dict[str, dict]:
    """把 unified diff 正文按文件切段。

    返回 {path: {"binary": bool, "side": [(new_line, content)]}}；side =
    新侧行（context + added，行号由 hunk 头计数器推算——OCR extractSideLines
    newSide=True 同款；-U0 下即纯 added 行）。元行（\\ No newline…）跳过。
    """
    files: dict[str, dict] = {}
    cur_path: str | None = None
    cur: dict | None = None
    new_line = 0
    for line in diff_text.split("\n"):
        if line.startswith("diff --git "):
            cur_path = None
            cur = None
            continue
        if line.startswith("Binary files ") or line.startswith("GIT binary patch"):
            if cur is not None:
                cur["binary"] = True
            continue
        if line.startswith("+++ b/"):
            cur_path = line[6:].strip()
            if cur_path.startswith("w/"):  # --default-directory 变体兜底
                cur_path = cur_path[2:]
            cur = {"binary": False, "side": []}
            files[cur_path] = cur
            continue
        m = HUNK_RE.match(line)
        if m and cur is not None:
            new_line = int(m.group(1))
            continue
        if cur is None or cur_path is None:
            continue
        if line.startswith("\\"):  # \ No newline at end of file
            continue
        if line.startswith("+"):
            cur["side"].append((new_line, normalize_line(line[1:])))
            new_line += 1
        elif line.startswith("-"):
            pass  # 删除行不占新侧行号
        else:
            if line.startswith(" ") and len(line) > 1:
                content = normalize_line(line[1:])
            else:
                content = normalize_line(line)
            cur["side"].append((new_line, content))
            new_line += 1
    return files


def resolve_in_diff(file_diff: dict, targets: list[str]) -> tuple[int, int] | None:
    """L1：在该文件 diff 新侧滑窗匹配（行号 = 新文件坐标系）。"""
    return match_consecutive(file_diff["side"], targets)


def resolve_from_file(root: Path, path: str,
                      targets: list[str]) -> tuple[int, int] | None:
    """L2：全文回退（pre_existing / path 不在 diff 的兜底）。

    OCR resolveFromFileContent 同款：归一化跳空行，命中行号取**原始行号**
    （1-indexed），空行不占位置。
    """
    try:
        content = (root / path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    lines: list[tuple[int, str]] = []
    for i, raw in enumerate(content.split("\n"), start=1):
        n = normalize_line(raw)
        if n:
            lines.append((i, n))
    return match_consecutive(lines, targets)


def _git_diff_text(root: Path, *, staged: bool, base: str | None,
                   head: str | None) -> str | None:
    """按模式取 diff 正文（R-3 分模式）；失败返回 None（调用方记 unresolvable）。"""
    if staged:
        argv = ["git", "diff", "--cached", "-U0", "--no-renames"]
    elif base and head:
        argv = ["git", "diff", f"{base}..{head}", "-U0", "--no-renames"]
    else:
        return None
    try:
        pr = subprocess.run(argv, cwd=str(root), capture_output=True, text=True,
                            timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if pr.returncode != 0:
        return None
    return pr.stdout


def classify_comment(comment: dict, file_diffs: dict[str, dict],
                     root: Path) -> tuple[str, list[int] | None,
                                          list[int] | None]:
    """单条 comment 归四态；返回 (state, reported, resolved)。

    前提：diff 基准可用（基准不可得 ⇒ 调用方整轮 unresolvable，不经此函数）。
    """
    path = str(comment.get("path") or "").replace("\\", "/").lstrip("/")
    try:
        start = int(comment.get("start_line") or 0)
        end = int(comment.get("end_line") or 0)
    except (TypeError, ValueError):
        start = end = 0
    reported = [start, end] if start or end else None
    if "existing_code" not in comment:
        return ("unanchored_no_field", reported, None)
    targets = split_normalize(comment.get("existing_code"))
    if not targets or reported is None:
        return ("unanchored_legacy", reported, None)

    fd = file_diffs.get(path)
    if fd is not None and fd["binary"]:
        return ("unresolvable", reported, None)
    resolved = resolve_in_diff(fd, targets) if fd is not None else None  # L1
    if resolved is None:  # path 不在 diff / L1 无果 ⇒ L2 全文回退
        resolved = resolve_from_file(root, path, targets)
    if resolved is None:
        return ("unresolved", reported, None)
    if reported[0] <= resolved[1] and resolved[0] <= reported[1]:
        return ("anchored", reported, list(resolved))  # 相交含子集（R-2）
    return ("mismatch", reported, list(resolved))


def compute_stats(root: Path, comments: list[dict], *, staged: bool = False,
                  base: str | None = None, head: str | None = None,
                  executor: str = "unknown",
                  diff_text: str | None = None) -> dict:
    """整轮统计；返回 anchoring-stats.json 的 dict（调用方落盘 + WARN）。

    diff_text 仅供测试注入；缺省按 staged/base/head 跑 git。基准不可得
    （无参数或 git 失败）⇒ 整轮 unresolvable（不兜 L2——grounding 缺失时
    统计必须显式失能，防假 anchored）。
    """
    diff_mode = "staged" if staged else ("range" if (base and head) else "none")
    if diff_text is None and diff_mode != "none":
        diff_text = _git_diff_text(root, staged=staged, base=base, head=head)
    grounding_ok = diff_text is not None
    file_diffs = parse_file_diffs(diff_text) if grounding_ok else {}

    counts = {s: 0 for s in STATES}
    detail: list[dict] = []
    for c in comments if isinstance(comments, list) else []:
        if not isinstance(c, dict):
            continue
        if not grounding_ok:
            state, reported, resolved = "unresolvable", None, None
        else:
            state, reported, resolved = classify_comment(c, file_diffs, root)
        counts[state] += 1
        detail.append({"path": str(c.get("path") or "?"),
                       "reported": reported, "resolved": resolved,
                       "state": state})
    return {"executor": executor or "unknown", "diff_mode": diff_mode,
            "grounding_ok": grounding_ok, "total": len(detail), **counts,
            "comments": detail}
