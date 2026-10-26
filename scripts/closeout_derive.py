#!/usr/bin/env python3
"""atlas 工具 —— 收口派生器（M2，`RFC-20261022-01` 批 2，2026-10-23）。

回答一个路由形问题：**本轮 diff 必跑 `shared/closeout.md` §1 的哪几步？**

  `shared/closeout.md` §1 的触发表（主表 + 补表）是**唯一真相源**：本器只**解析**
  事件行与步骤号，不复制一张表进来。`--diff-base <ref>` 取 `git diff --name-only`
  的改动文件，逐行匹配「事件 ⇒ 必跑步骤」，把本轮清单打到 **stdout**（不落派生文件面）。

输出语义：
  - 首行固定「本清单不含语义触发行，正文自查」——诊断类 / 域收口 / 复盘等触发行
    无路径形态，本器不猜；
  - 机器可执行步骤标 `[自动]`，人侧步骤标 `[人工]` 并给判据指针（`closeout.md` §2 步骤 N）；
  - 触发值支持「1 → 2 → 5 → 7」箭头链语法（含 `**1（含…）**` 一类加粗包裹）。

告警宇宙收敛（评审 P0-1）：**未命中任何触发行 ⇒ WARN** 只对 atlas 自有对账面
（`shared/` `rings/` `validators/` `scripts/` `templates/` `patches/` `_support/`
`tests/` `DESIGN.md`）生效；业务面文件在派生范围外，只计条数一行带过，不逐条出声
（全员 WARN = 狼来了，会把真信号训练成噪声）。

自带自检（硬）：
  ① 触发表引用的步骤号必须存在于 §2（`### 步骤 N —`；步骤 6 已退役 ⇒ 空号 ⇒ FAIL
     指名，对齐「死指针」纪律）；
  ② 表结构解析失败 / 步骤号解析失败 ⇒ **FAIL 响亮**（不得退化成空清单静默通过）。

边界自认：**没人逼模型跑派生器**——触发物仍是纪律（`closeout.md` 步骤 1 已写
「收口第一步 = closeout_derive」）；本器只把「查表」的成本降到零，不假装是门。

框架无关；纯标准库。CLI：
    python3 closeout_derive.py --diff-base <ref> [--root .] [--json]
退出码：0 = 清单已产出（WARN 不置红）；2 = 契约解析 / git ref / 空号失败。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _support.layout import LayoutError, load_layout  # noqa: E402

CONTRACT_CANDIDATES = (
    Path(".atlas") / "shared" / "closeout.md",
    Path("shared") / "closeout.md",
)

# atlas 自有对账面（评审 P0-1 的告警宇宙）；业务面只计条数
ATLAS_OWNED_PREFIXES = (
    "shared/", "rings/", "validators/", "scripts/", "templates/",
    "patches/", "_support/", "tests/",
)
ATLAS_OWNED_FILES = ("DESIGN.md",)

# 机器可执行步骤：§2 正文给的是命令 / 机械核对。其余按人侧步骤处理。
AUTOMATED_STEPS = frozenset({1, 2})

# 事件关键词 ⇒ 路径前缀。**只做「改哪类文件」的关联**；步骤号一律取自触发表。
# `任一工作单元` 是**无条件触发行**：它恒贡献步骤，但不算「某个文件命中了触发行」
# （否则每个文件都会被它「救下」，未命中告警永远不响）。
UNCONDITIONAL_TOKEN = "任一工作单元"
def event_path_tokens(root: Path) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """事件关键词 ⇒ 路径前缀；资产前缀随项目布局配置解析。"""
    lay = load_layout(root)
    return (
        ("DESIGN.md", ("DESIGN.md",)),
        ("模板", ("templates/",)),
        ("校验器", ("validators/",)),
        # `tests/` 归「脚本」族：回归钉随包走，改测试与改脚本属同一条触发行。
        # 若不并进来，`tests/` 在告警宇宙里却永无触发行 ⇒ 每次改测试都 WARN（假信号）。
        ("脚本", ("scripts/", "tests/")),
        ("skill", ("skills/",)),
        ("独立审查报告", (f"{lay.print_value('reviews')}/",
                          f"{lay.print_value('e2e_reviews')}/")),
        ("影响面报告", ("impact.json",)),
        ("ADR", (f"{lay.print_value('adr')}/",)),
        ("结构环", (".trellis/spec/structure/",)),
        ("CI", (".github/",)),
        ("依赖", ("package.json", "bun.lock", "pnpm-lock.yaml", "package-lock.json", "go.mod")),
        ("契约", ("shared/", "rings/", "apply/", "atlas.config.yaml")),
    )

TABLE_HEADER_CELLS = {"事件", "必跑步骤"}
STEP_HEADING_RE = re.compile(r"^###\s*步骤\s*(\d+)\s*[—\-–]", re.M)


class DeriveError(RuntimeError):
    """契约 / diff / 空号级别的硬失败（exit 2）。"""


def find_contract(root: Path) -> Path:
    for rel in CONTRACT_CANDIDATES:
        p = root / rel
        if p.is_file():
            return p
    tried = " / ".join(r.as_posix() for r in CONTRACT_CANDIDATES)
    raise DeriveError(f"找不到收口契约（试过 {tried}）")


def parse_steps(cell: str) -> list[int]:
    """从「1 → 2 → 5 → 7」/「**1（含…）**」一类单元取步骤号。

    只读每段**开头**的 1–2 位数字：避免把「2026-10-06」一类日期读成步骤号
    （这是本器最容易被写歪的地方——日期在括号里，不属于箭头段）。
    """
    out: list[int] = []
    for seg in re.split(r"→", cell):
        s = seg.strip().lstrip("*` ").strip()
        m = re.match(r"^(\d{1,2})(?![\d])", s)
        if m:
            out.append(int(m.group(1)))
    return out


def parse_table(contract_text: str) -> list[dict]:
    """解析 §1 的**两张表**（主表 + 补表）。返回 [{event, steps, raw}]。"""
    parts = re.split(r"^##\s*1\.\s*触发表.*$", contract_text, maxsplit=1, flags=re.M)
    if len(parts) < 2:
        raise DeriveError("closeout.md 未找到「## 1. 触发表」小节")
    body = re.split(r"^##\s*2\.", parts[1], maxsplit=1, flags=re.M)[0]

    rows: list[dict] = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|") or not line.endswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if cells[0] in TABLE_HEADER_CELLS or all(set(c) <= set("-: ") for c in cells):
            continue
        steps = parse_steps(cells[1])
        if not steps:
            raise DeriveError(f"触发行无法解析出步骤号：{cells[0][:60]!r}")
        rows.append({"event": cells[0], "steps": steps, "raw": line})
    if not rows:
        raise DeriveError("触发表解析出 0 行 —— 表结构可能已变，拒绝给出空清单")
    return rows


def parse_existing_steps(contract_text: str) -> dict[int, str]:
    """§2 实际存在的步骤号 → 标题（`### 步骤 N — <名>`）。"""
    parts = re.split(r"^##\s*2\.\s*步骤.*$", contract_text, maxsplit=1, flags=re.M)
    if len(parts) < 2:
        raise DeriveError("closeout.md 未找到「## 2. 步骤」小节")
    out: dict[int, str] = {}
    for m in STEP_HEADING_RE.finditer(parts[1]):
        out[int(m.group(1))] = m.group(0).lstrip("# ").strip()
    if not out:
        raise DeriveError("§2 未解析出任何「### 步骤 N —」标题")
    return out


def validate_step_references(rows: list[dict], existing: dict[int, str]) -> None:
    bad = []
    for row in rows:
        for n in row["steps"]:
            if n not in existing:
                bad.append(f"触发行「{row['event'][:40]}」引用步骤 {n}，但 §2 无「步骤 {n}」"
                           "（空号 = 死指针；步骤 6 已随台账子系统退役）")
    if bad:
        raise DeriveError("；".join(bad))


def git_changed_files(root: Path, diff_base: str) -> list[str]:
    """本轮改动面 = `git diff --name-only <base>` ∪ 未跟踪文件（`.gitignore` 除外）。

    未跟踪面是刻意并进来的：收口发生在提交**前**，新建文件此刻还不在 diff 里；
    漏掉它们 = 新增脚本 / 校验器不触发「改契约」行（机制在、接线断）。
    """
    p = subprocess.run(["git", "-C", str(root), "diff", "--name-only", diff_base],
                       capture_output=True, text=True)
    if p.returncode != 0:
        err = (p.stderr or p.stdout).strip()
        if "not a git repository" in err.lower():
            # 非 git 项目不是「坏 ref」，是形态不适用：短句拒绝，不刷整屏 git usage
            raise DeriveError("本仓不是 git 仓库（无法用 diff 派生）——按 closeout.md 查表照旧")
        last = [l for l in err.splitlines() if l.strip()][-1:] or [""]
        raise DeriveError(f"git diff --name-only {diff_base} 失败：{last[0]}")
    changed = [l.strip() for l in p.stdout.splitlines() if l.strip()]
    u = subprocess.run(["git", "-C", str(root), "ls-files", "--others", "--exclude-standard"],
                       capture_output=True, text=True)
    if u.returncode == 0:
        changed += [l.strip() for l in u.stdout.splitlines() if l.strip()]
    # 去重保序（同一文件可能同时出现在 diff 与未跟踪面，例如 `git add -N` 之后）
    return list(dict.fromkeys(changed))


def _event_matches_path(event: str, path: str, tokens) -> bool:
    for token, prefixes in tokens:
        if token not in event:
            continue
        for pref in prefixes:
            if pref.endswith("/"):
                if path.startswith(pref):
                    return True
            elif path == pref or Path(path).name == pref:
                return True
    return False


def derive(rows: list[dict], changed: list[str], tokens) -> tuple[dict[int, list[str]], list[str], int]:
    """→ (步骤号 → 触发行列表, 未命中的 atlas 自有面文件, 业务面文件数)。"""
    trigger_map: dict[int, list[str]] = {}
    owned_unmatched: list[str] = []
    business = 0

    def _add(row: dict) -> None:
        for n in row["steps"]:
            bucket = trigger_map.setdefault(n, [])
            if row["event"] not in bucket:
                bucket.append(row["event"])

    unconditional = [r for r in rows if UNCONDITIONAL_TOKEN in r["event"]]
    conditional = [r for r in rows if UNCONDITIONAL_TOKEN not in r["event"]]
    for row in unconditional:
        _add(row)
    for path in changed:
        hits = [row for row in conditional if _event_matches_path(row["event"], path, tokens)]
        owned = path.startswith(ATLAS_OWNED_PREFIXES) or path in ATLAS_OWNED_FILES
        if hits:
            for row in hits:
                _add(row)
        elif owned:
            owned_unmatched.append(path)
        else:
            business += 1
    return trigger_map, owned_unmatched, business


def render(trigger_map: dict[int, list[str]], owned_unmatched: list[str],
           business: int, changed: int) -> str:
    lines = ["本清单不含语义触发行，正文自查",
             f"本轮改动 {changed} 个文件（atlas 自有对账面 {changed - business} 个；"
             f"业务面 {business} 个，只计条数）"]
    if not trigger_map:
        lines.append("（本轮 diff 未命中任何路径形触发行）")
    for n in sorted(trigger_map):
        kind = "自动" if n in AUTOMATED_STEPS else "人工"
        events = "；".join(e[:48] for e in trigger_map[n])
        lines.append(f"[{kind}] 步骤 {n} —— 触发：{events}"
                     f"（判据指针：closeout.md §2 步骤 {n}）")
    for path in owned_unmatched:
        lines.append(f"[WARN] atlas 自有面文件未命中任何触发行：{path}"
                     "（触发表可能漏了一行，或这张表该扩了）")
    return "\n".join(lines)


def run(root: Path, diff_base: str) -> dict:
    contract = find_contract(root)
    text = contract.read_text(encoding="utf-8")
    rows = parse_table(text)
    existing = parse_existing_steps(text)
    validate_step_references(rows, existing)
    changed = git_changed_files(root, diff_base)
    try:
        tokens = event_path_tokens(root)
    except LayoutError as exc:
        raise DeriveError(str(exc)) from exc
    trigger_map, owned_unmatched, business = derive(rows, changed, tokens)
    return {
        "ok": True,
        "contract": str(contract),
        "diff_base": diff_base,
        "changed": len(changed),
        "business": business,
        "steps": {str(n): trigger_map[n] for n in sorted(trigger_map)},
        "warnings": owned_unmatched,
        "text": render(trigger_map, owned_unmatched, business, len(changed)),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="收口派生器（触发表唯一真相源）")
    ap.add_argument("--diff-base", required=True, help="git diff 的基准 ref")
    ap.add_argument("--root", default=".", help="项目根（默认 .）")
    ap.add_argument("--json", action="store_true", help="JSON 输出（stdout）")
    args = ap.parse_args(argv)
    try:
        res = run(Path(args.root), args.diff_base)
    except DeriveError as e:
        print(f"[FAIL] closeout_derive — {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(res["text"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
