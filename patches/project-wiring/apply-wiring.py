#!/usr/bin/env python3
"""atlas 项目接线（project wiring）——把入口指针与收口 hook 幂等写进目标项目。

用法：
    python3 apply-wiring.py --target <项目根> [--apply] [--json]

做两件事（各自独立幂等）：

  1. `<项目根>/AGENTS.md`：在 Trellis 区块 `<!-- TRELLIS:END -->` **之后**追加
     `<!-- ATLAS:START -->…<!-- ATLAS:END -->` 段。该段位于 Trellis 区块**之外**，
     因此不被 `trellis update` 覆盖。已存在则整段按源更新（不新建重复段）。
     文件不存在时创建。

  2. `<项目根>/.trellis/config.yaml`：登记 `after_finish` hook 跑
     `refresh_structure.py`（结构事实刷新，决策 D38）；已有 `hooks:` 块则并入，
     否则在文件末尾新增。

设计要点：
  * 只做**外科式插入 / 替换**，不整体覆盖任何文件；标记外内容原样保留。
  * 缺省 dry-run（安全默认）；真正写入需显式 `--apply`。
  * `.yaml` 目标写入前做轻量结构护栏（不依赖第三方库）：`hooks:` 顶层键唯一、
    hook 命令行存在；不满足则报 error 且不写该文件。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent
POINTER_SNIPPET = PKG_ROOT / "agent-pointer.md"

ATLAS_START = "<!-- ATLAS:START -->"
ATLAS_END = "<!-- ATLAS:END -->"
TRELLIS_END = "<!-- TRELLIS:END -->"
AGENTS_REL = "AGENTS.md"

HOOK_CMD = "python3 .atlas/scripts/refresh_structure.py --root . --apply"
CONFIG_REL = ".trellis/config.yaml"

RE_HOOKS = re.compile(r"^hooks:\s*(#.*)?$")
RE_AFTER_FINISH = re.compile(r"^  after_finish:\s*(#.*)?$")
RE_TOP_LEVEL = re.compile(r"^\S")


def render_pointer() -> str:
    body = POINTER_SNIPPET.read_text(encoding="utf-8").rstrip("\n")
    return f"{ATLAS_START}\n{body}\n{ATLAS_END}\n"


# --------------------------------------------------------------------- AGENTS.md

def wire_agents(target: Path) -> dict:
    path = target / AGENTS_REL
    block = render_pointer()

    if not path.exists():
        return {
            "file": AGENTS_REL, "status": "applied", "detail": "created",
            "_write": (path, block),
        }

    text = path.read_text(encoding="utf-8")
    has_start = ATLAS_START in text
    has_end = ATLAS_END in text

    if has_start != has_end:
        return {"file": AGENTS_REL, "status": "error",
                "detail": f"标记不成对（{ATLAS_START if has_start else ATLAS_END} 单侧存在），不修改"}

    if has_start:
        i = text.index(ATLAS_START)
        j = text.index(ATLAS_END) + len(ATLAS_END)
        if text[j:j + 1] == "\n":
            j += 1
        new_text = text[:i] + block + text[j:]
        detail = "updated (block replaced)"
    elif TRELLIS_END in text:
        idx = text.index(TRELLIS_END) + len(TRELLIS_END)
        if text[idx:idx + 1] == "\n":
            idx += 1
        new_text = text[:idx] + block + text[idx:]
        detail = "applied (after TRELLIS:END)"
    else:
        new_text = text
        if not new_text.endswith("\n"):
            new_text += "\n"
        new_text += "\n" + block
        detail = "applied (appended at EOF)"

    if new_text == text:
        return {"file": AGENTS_REL, "status": "skipped", "detail": "already current"}
    return {"file": AGENTS_REL, "status": "applied", "detail": detail, "_write": (path, new_text)}


# ----------------------------------------------------------------- .trellis/config.yaml

def wire_config(target: Path) -> dict:
    path = target / CONFIG_REL
    if not path.exists():
        return {"file": CONFIG_REL, "status": "skipped",
                "detail": "config.yaml 不存在（Trellis 未初始化？）"}

    text = path.read_text(encoding="utf-8")
    if HOOK_CMD in text:
        return {"file": CONFIG_REL, "status": "skipped", "detail": "after_finish hook 已登记"}

    lines = text.splitlines(keepends=True)

    hooks_i = next((i for i, ln in enumerate(lines) if RE_HOOKS.match(ln)), None)

    if hooks_i is not None:
        after_finish_i = None
        for j in range(hooks_i + 1, len(lines)):
            if RE_TOP_LEVEL.match(lines[j]):
                break  # 离开 hooks 子块
            if RE_AFTER_FINISH.match(lines[j]):
                after_finish_i = j
                break
        if after_finish_i is not None:
            lines.insert(after_finish_i + 1, f'    - "{HOOK_CMD}"\n')
            detail = "applied (hook added to existing after_finish)"
        else:
            lines.insert(hooks_i + 1, f'  after_finish:\n    - "{HOOK_CMD}"\n')
            detail = "applied (after_finish added to existing hooks)"
    else:
        if text and not text.endswith("\n"):
            lines.append("\n")
        lines.append("\n# atlas structure refresh（D38）：每个任务 Finish 后刷新结构事实指针层\n")
        lines.append("hooks:\n")
        lines.append("  after_finish:\n")
        lines.append(f'    - "{HOOK_CMD}"\n')
        detail = "applied (new hooks block at EOF)"

    new_text = "".join(lines)

    # 轻量 YAML 结构护栏（不依赖 PyYAML）
    top_hooks = [ln for ln in new_text.splitlines() if RE_HOOKS.match(ln)]
    if len(top_hooks) != 1:
        return {"file": CONFIG_REL, "status": "error",
                "detail": f"YAML 护栏：顶层 hooks: 出现 {len(top_hooks)} 次（期望 1），不修改"}
    if HOOK_CMD not in new_text:
        return {"file": CONFIG_REL, "status": "error",
                "detail": "YAML 护栏：hook 命令未写入，不修改"}

    if new_text == text:
        return {"file": CONFIG_REL, "status": "skipped", "detail": "already current"}
    return {"file": CONFIG_REL, "status": "applied", "detail": detail, "_write": (path, new_text)}


# ----------------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=str(Path.cwd()), help="项目根目录（缺省 = 当前目录）")
    ap.add_argument("--apply", action="store_true", help="真正写入；缺省为 dry-run（安全默认）")
    ap.add_argument("--dry-run", action="store_true", help="显式 dry-run（与缺省等价）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    write = bool(args.apply) and not bool(args.dry_run)
    target = Path(args.target).resolve()

    results = [wire_agents(target), wire_config(target)]
    errors = sum(1 for r in results if r["status"] == "error")

    if write:
        for r in results:
            if r["status"] == "applied" and "_write" in r:
                p, t = r["_write"]
                p.write_text(t, encoding="utf-8")

    for r in results:
        r.pop("_write", None)

    applied = sum(1 for r in results if r["status"] == "applied")
    skipped = sum(1 for r in results if r["status"] == "skipped")

    if args.json:
        print(json.dumps({"target": str(target), "dry_run": not write,
                          "applied": applied, "skipped": skipped, "errors": errors,
                          "results": results}, ensure_ascii=False, indent=2))
    else:
        print(f"▶ 目标项目 : {target}")
        print(f"▶ 模式     : {'apply' if write else 'dry-run'}")
        for r in results:
            icon = {"applied": "✓", "skipped": "=", "error": "✗"}.get(r["status"], "?")
            print(f"  {icon} {r['file']} — {r['detail']}")
        print(f"合计：applied={applied} skipped={skipped} errors={errors}")
        if not write:
            print("（dry-run：未写入任何文件；如需写入请加 --apply）")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
