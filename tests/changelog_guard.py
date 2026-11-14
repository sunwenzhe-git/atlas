#!/usr/bin/env python3
"""批次 changelog 前置守卫（`RFC-20261114-04` 阶段 2a：shadow 模式）。

判据（与 `shared/closeout.md` §1「批次收口 changelog 规则」逐字对齐）：
  批次 range 内若存在**触装配面的 `feat` / `fix` 提交**，则 `CHANGELOG.md` 与
  `docs/guide/changelog.md` 两份的 `[Unreleased]` 段内各有 ≥1 行新增
  （「段在但段内零新增」同样不合格）。

量法：`git diff -U0 <range> -- <changelog>` 的 `+` 行，按 post-image 行号落进
HEAD 版 `[Unreleased]` 段体（不含段标题、不含空行）才计数——与 RFC §2.1 的
「用 `git diff --range -- <changelog>` 数段内 `+` 行」同口径。

影子语义（本阶段只报告、不阻断）：发现问题打印 would-flag 明细并 exit 0；
`--enforce` 开关已留，但本阶段不接 closeout（接 = 后续阶段的事）。

范围：默认 `origin/main..HEAD`（未推送提交）；为空 ⇒ exit 2 并提示显式传
`--range <base>..HEAD`，**绝不静默退回 `HEAD~1..HEAD`**。

只提示，绝不自动改写 changelog。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for extra in (HERE, HERE.parent / "scripts"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from pkg_digest import ASSEMBLY_COVER_DIRS, ASSEMBLY_COVER_FILES  # noqa: E402

DEFAULT_ROOT = HERE.parent

# 单常量检测集：装配面覆盖面 ∪ 装配入口/清单面；不另造与装配面并行的清单。
DETECT_COVER_DIRS = tuple(ASSEMBLY_COVER_DIRS) + ("bin",)
DETECT_COVER_FILES = tuple(ASSEMBLY_COVER_FILES) + ("install.py", "install.sh", "package.json")
DETECT = frozenset(DETECT_COVER_DIRS) | frozenset(DETECT_COVER_FILES)

CHANGELOGS = ("CHANGELOG.md", "docs/guide/changelog.md")
FEATFIX_RE = re.compile(r"^(feat|fix)(\([^)]*\))?!?:")
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
UNRELEASED_RE = re.compile(r"^##\s*\[Unreleased\]", re.I)
H2_RE = re.compile(r"^##\s+")


class GuardError(Exception):
    pass


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def _resolve_range(root: Path, rng: str) -> tuple[str, str]:
    if ".." not in rng:
        raise GuardError(f"range 形态须为 <base>..<head>，收到 {rng!r}")
    left, right = rng.split("..", 1)
    shas = []
    for rev in (left, right):
        p = _git(root, "rev-parse", "--verify", rev + "^{commit}")
        if p.returncode != 0:
            raise GuardError(f"range 端点不可解析：{rev}（{(p.stderr or p.stdout).strip()}）")
        shas.append(p.stdout.strip())
    return shas[0], shas[1]


def _commit_count(root: Path, rng: str) -> int:
    p = _git(root, "rev-list", "--count", rng)
    if p.returncode != 0:
        raise GuardError(f"git rev-list {rng} 失败：{(p.stderr or p.stdout).strip()}")
    return int(p.stdout.strip() or 0)


def _triggering_commits(root: Path, rng: str) -> list[tuple[str, str]]:
    p = _git(root, "log", "--no-merges", "--format=%H%x1f%s%x1e", rng, "--")
    if p.returncode != 0:
        raise GuardError(f"git log {rng} 失败：{(p.stderr or p.stdout).strip()}")
    out: list[tuple[str, str]] = []
    for rec in p.stdout.split("\x1e"):
        rec = rec.strip()
        if not rec or "\x1f" not in rec:
            continue
        sha, subject = rec.split("\x1f", 1)
        if not FEATFIX_RE.match(subject):
            continue
        files = _changed_files(root, sha)
        if any(_is_detect(f) for f in files):
            out.append((sha, subject))
    return out


def _changed_files(root: Path, sha: str) -> list[str]:
    p = _git(root, "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", sha)
    if p.returncode != 0:
        raise GuardError(f"git diff-tree {sha} 失败：{(p.stderr or p.stdout).strip()}")
    return [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]


def _is_detect(path: str) -> bool:
    if path in CHANGELOGS:
        return False  # changelog 自身不算装配面触发
    if path in DETECT:
        return True
    return any(path.startswith(d + "/") for d in DETECT_COVER_DIRS)


def _section_bounds(text: str) -> tuple[int, int] | None:
    """HEAD 版 `[Unreleased]` 段体的 1-based 半开区间 [start, end)；无段 ⇒ None。"""
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if UNRELEASED_RE.match(ln):
            start = i + 2  # 段体首行 = 标题下一行
            break
    if start is None:
        return None
    end = len(lines) + 1
    for j in range(start - 1, len(lines)):
        if H2_RE.match(lines[j]):
            end = j + 1
            break
    return start, end


def _added_in_unreleased(root: Path, rng: str, path: str, head_sha: str) -> dict:
    """返回 {missing_file, missing_section, added}；added = 段体内新增非空行数。"""
    head = _git(root, "show", f"{head_sha}:{path}")
    if head.returncode != 0:
        return {"missing_file": True, "missing_section": False, "added": 0}
    bounds = _section_bounds(head.stdout)
    if bounds is None:
        return {"missing_file": False, "missing_section": True, "added": 0}
    p = _git(root, "diff", "-U0", rng, "--", path)
    if p.returncode != 0:
        raise GuardError(f"git diff {rng} -- {path} 失败：{(p.stderr or p.stdout).strip()}")
    added = 0
    cur = None
    for ln in p.stdout.splitlines():
        m = HUNK_RE.match(ln)
        if m:
            cur = int(m.group(1))
            continue
        if cur is None or ln.startswith("+++") or ln.startswith("---"):
            continue
        if ln.startswith("+"):
            if bounds[0] <= cur < bounds[1] and ln[1:].strip():
                added += 1
            cur += 1
        elif ln.startswith(" "):
            cur += 1
    return {"missing_file": False, "missing_section": False, "added": added}


def _describe(stat: dict) -> str:
    if stat["missing_file"]:
        return "文件缺失"
    if stat["missing_section"]:
        return "缺 [Unreleased] 段"
    return f"{stat['added']} 行新增"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="批次 changelog 前置守卫（RFC-20261114-04 阶段 2a，shadow 模式）")
    ap.add_argument("--range", dest="rng", default="origin/main..HEAD",
                    help="提交范围 <base>..<head>（缺省 origin/main..HEAD）")
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="仓库根")
    ap.add_argument("--enforce", action="store_true",
                    help="发现问题 exit 1（本阶段不接 closeout；缺省 shadow exit 0）")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()

    try:
        _base_sha, head_sha = _resolve_range(root, args.rng)
    except GuardError as exc:
        print(f"ERROR：{exc}")
        print("提示：显式传 --range <base>..HEAD（本器绝不静默退回 HEAD~1..HEAD）")
        return 2
    count = _commit_count(root, args.rng)
    if count == 0:
        print(f"ERROR：range {args.rng} 为空（无提交）——请显式传 --range <base>..HEAD；"
              "本器绝不静默退回 HEAD~1..HEAD")
        return 2

    triggers = _triggering_commits(root, args.rng)
    if not triggers:
        print(f"PASS：range {args.rng}（{count} 提交）无触装配面的 feat/fix 提交（纯 docs/test/chore 批豁免）")
        return 0

    stats = {path: _added_in_unreleased(root, args.rng, path, head_sha) for path in CHANGELOGS}
    bad = [path for path in CHANGELOGS if stats[path]["added"] < 1]
    trigger_brief = "、".join(f"{sha[:8]} {subject}" for sha, subject in triggers[:6])
    if len(triggers) > 6:
        trigger_brief += f" 等 {len(triggers)} 笔"
    if not bad:
        detail = " / ".join(f"{path} +{stats[path]['added']} 行" for path in CHANGELOGS)
        print(f"PASS：range {args.rng}（{count} 提交，触装配面 feat/fix {len(triggers)} 笔）"
              f"——两份 [Unreleased] 均有新增（{detail}）")
        return 0

    print(f"[would-flag] range {args.rng}（{count} 提交，触装配面 feat/fix {len(triggers)} 笔）")
    print(f"  触发提交：{trigger_brief}")
    for path in CHANGELOGS:
        print(f"  - {path}：{_describe(stats[path])}")
    if args.enforce:
        print("enforce：判据不合格 -> exit 1")
        return 1
    print("shadow：只报告不阻断（exit 0；--enforce 才 exit 1）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
