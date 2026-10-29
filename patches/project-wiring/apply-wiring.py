#!/usr/bin/env python3
"""atlas 项目接线（project wiring）——把入口指针、收口 hook、宿主扩展幂等写进目标项目。

用法：
    python3 apply-wiring.py --target <项目根> [--apply] [--json]

做五件事（各自独立幂等）：

  1. `<项目根>/AGENTS.md`：在 Trellis 区块 `<!-- TRELLIS:END -->` **之后**追加
     `<!-- ATLAS:START -->…<!-- ATLAS:END -->` 段。该段位于 Trellis 区块**之外**，
     因此不被 `trellis update` 覆盖。已存在则整段按源更新（不新建重复段）。
     文件不存在时创建。

  2. `<项目根>/.trellis/config.yaml`：登记 `after_archive` hook 跑
     `refresh_structure.py`（结构事实刷新，决策 D159：归档才是任务收口；旧形态
     `after_finish` 会被迁移）；已有 `hooks:` 块则并入，否则在文件末尾新增。
     同一步把 `session_auto_commit` 默认写为 `false`（D160：提交由人 review，
     不让归档自动 commit；用户显式设置的键尊重不动）。

  3. `<项目根>/<测试配置>`（仅 extractor 声明的栈）：由 `adapters/ac/` 的 extractor
     提供项目级配置 hook；无 hook 的栈跳过，不写任何配置。

  4. `<项目根>/.pi/`（仅 pi 宿主）：把官方扩展落到 `.pi/extensions/atlas/index.ts`，
     并在 `.pi/settings.json` 的 `extensions[]` 里幂等登记一行（2026-10-15 补）。

  5. `<项目根>/.gitignore`（仅已存在时）：幂等追加一行 `.adapter-out/`（2026-10-15 补）。
     issue #8 后 atlas 全部中间产物统一落项目根该目录（适配器输出 / 漂移标记 /
     图谱新鲜度标记），不忽略则 `git status` 常驻未跟踪噪声——**对所有接线项目成立**，
     不只图谱用户。判据：文件**不存在 ⇒ 不首创**（跳过并在报告里给一行建议）；
     内容已含 `.adapter-out` 字样 ⇒ 幂等跳过；出现 `!.adapter-out` 负模式 ⇒ 跳过，
     不与用户既有规则打架。**本触点无退役对称**：`.gitignore` 不是本项目创建的文件，
     追加后永不回收（与 extractor 配置的「逐字节相等才清」不同——追加是单向动作，
     由报告行当刻告知用户）。

设计要点：
  * 只做**外科式插入 / 替换**，不整体覆盖任何文件；标记外内容原样保留。
  * 缺省 dry-run（安全默认）；真正写入需显式 `--apply`。
  * `.yaml` 目标写入前做轻量结构护栏（不依赖第三方库）：`hooks:` 顶层键唯一、
    hook 命令行存在；不满足则报 error 且不写该文件。`.pi/settings.json` 同律：
    结构判读不了就跳过（只报要手加的那一行），不猜结构。
  * **不认识的目标形态 = 跳过 + 说明**，绝不自动创建宿主目录（非 pi 项目不建 `.pi/`）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _support.layout import LayoutError, load_layout  # noqa: E402
from adapters.ac import wire_project  # noqa: E402

PKG_ROOT = Path(__file__).resolve().parent
POINTER_SNIPPET = PKG_ROOT / "agent-pointer.md"

ATLAS_START = "<!-- ATLAS:START -->"
ATLAS_END = "<!-- ATLAS:END -->"
TRELLIS_END = "<!-- TRELLIS:END -->"
AGENTS_REL = "AGENTS.md"

HOOK_CMD = "python3 .atlas/scripts/refresh_structure.py --root . --chain"
# C1（R7，2026-10-15）：存量钩子的**前缀**（幂等判据必须冗余于一字符）——
# 子串等于旧命令会漏识别 `--apply` 旧形态 ⇒ 双 hook 常驻、refresh 跑两遍。
HOOK_PREFIX = "python3 .atlas/scripts/refresh_structure.py --root ."
CONFIG_REL = ".trellis/config.yaml"
EVENT_ARCHIVE = "after_archive"
EVENT_ORDER = ["after_finish", "after_start", "after_create", "after_archive"]

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

RE_AUTO_COMMIT = re.compile(r"^session_auto_commit:\s*(.*)$")
RE_AUTO_COMMIT_COMMENTED = re.compile(r"^#\s*session_auto_commit:.*$")


def _wire_auto_commit(lines: list[str]) -> str:
    """默认关闭 Trellis 的自动提交（D160）。

    自动提交会把 journal / task 归档直接 commit 进用户仓库，绕过人工 review；
    atlas 的接线口径是「提交由人决定」，故新项目默认写 `session_auto_commit: false`。
    用户显式写了该键 ⇒ 尊重（true/false 都不改），只在报告里说明。
    """
    for ln in lines:
        m = RE_AUTO_COMMIT.match(ln)
        if not m:
            continue
        value = m.group(1).split("#")[0].strip().lower()
        return "respected (already false)" if value in ("false", "no", "0", "off") else "respected (user override)"
    for i, ln in enumerate(lines):
        if RE_AUTO_COMMIT_COMMENTED.match(ln):
            lines[i] = "# atlas 接线：默认关闭自动提交，提交由人 review 后手工执行（D160）\nsession_auto_commit: false\n"
            return "applied (enabled-off at template comment)"
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    lines.append("\n# atlas 接线：默认关闭自动提交，提交由人 review 后手工执行（D160）\nsession_auto_commit: false\n")
    return "applied (enabled-off appended)"


def _hooks_range(lines: list[str]) -> tuple[int, int] | None:
    """返回 hooks: 子块的行区间 [start, end)（end 为第一个顶层行）。"""
    hi = next((i for i, ln in enumerate(lines) if RE_HOOKS.match(ln)), None)
    if hi is None:
        return None
    end = len(lines)
    for j in range(hi + 1, len(lines)):
        if RE_TOP_LEVEL.match(lines[j]):
            end = j
            break
    return (hi + 1, end)


def _event_lines(lines: list[str], rng: tuple[int, int], event: str) -> tuple[int, list[int]] | None:
    """返回某事件子块的 (键行下标, 命令行下标列表)；不存在返回 None。"""
    start, end = rng
    key_re = re.compile(rf"^  {re.escape(event)}:\s*(#.*)?$")
    for i in range(start, end):
        if not key_re.match(lines[i]):
            continue
        cmd_idx = []
        j = i + 1
        while j < end:
            ln = lines[j]
            if ln.strip() and not ln.startswith("    "):
                break
            if ln.lstrip().startswith("- "):
                cmd_idx.append(j)
            j += 1
        return (i, cmd_idx)
    return None


def wire_config(target: Path) -> dict:
    """接线 `.trellis/config.yaml` 的两件事（各自幂等）：

    1. refresh hook 登记到 `after_archive`（D159）。归档（`task.py archive`，收尾命令
       `/trellis-finish-work` 走的也是它）才是任务收口；`after_finish` 只清活动任务指针，
       用它会在真收口时漏刷新。存量 `after_finish` 里的同一条命令会被**迁移**。
    2. `session_auto_commit` 默认写 `false`（D160）：自动提交会把 journal / 任务归档直接
       commit 进用户仓库，绕过人工 review；用户显式写了该键则尊重不动。
    """
    path = target / CONFIG_REL
    if not path.exists():
        return {"file": CONFIG_REL, "status": "skipped",
                "detail": "config.yaml 不存在（Trellis 未初始化？）"}

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    rng = _hooks_range(lines)

    hook_ready = False
    if rng is not None:
        archive = _event_lines(lines, rng, EVENT_ARCHIVE)
        hook_ready = archive is not None and any(HOOK_CMD in lines[i] for i in archive[1])

    detail = "after_archive hook already registered"
    if not hook_ready:
        # 找到别处（旧形态 after_finish / 其它事件）的同一条命令，准备迁移
        legacy: list[tuple[str, int]] = []
        if rng is not None:
            for event in EVENT_ORDER:
                found = _event_lines(lines, rng, event)
                if found is None:
                    continue
                for i in found[1]:
                    if HOOK_PREFIX in lines[i]:
                        tail = lines[i].split(HOOK_PREFIX, 1)[1].strip().strip('"').strip("'").strip()
                        if tail not in ("--apply", "--chain"):
                            return {"file": CONFIG_REL, "status": "skipped",
                                    "detail": "存在自定义 refresh hook（尾参非 --apply/--chain），未改"}
                        legacy.append((event, i))

        # 迁移：删除旧命令行；旧事件子块被删空时连键行一起去掉
        for event, i in sorted(legacy, key=lambda x: -x[1]):
            del lines[i]
            found = _event_lines(lines, _hooks_range(lines) or (0, 0), event)
            if found is not None and not found[1]:
                del lines[found[0]]

        rng = _hooks_range(lines)
        if rng is None:
            if text and not text.endswith("\n"):
                lines.append("\n")
            lines.append("\n# atlas structure refresh（D159）：任务归档后刷新结构事实指针层\n")
            lines.append("hooks:\n")
            lines.append("  after_archive:\n")
            lines.append(f'    - "{HOOK_CMD}"\n')
            detail = "applied (new hooks block at EOF)"
        else:
            archive = _event_lines(lines, rng, EVENT_ARCHIVE)
            if archive is None:
                lines.insert(rng[1], f'  after_archive:\n    - "{HOOK_CMD}"\n')
                detail = "applied (after_archive added to existing hooks)"
            else:
                lines.insert(archive[0] + 1, f'    - "{HOOK_CMD}"\n')
                detail = "applied (hook added to existing after_archive)"
            if legacy:
                detail = detail.replace("applied", "applied (migrated from after_finish)")

    commit_state = _wire_auto_commit(lines)
    if commit_state.startswith("applied"):
        detail = f"{detail}; session_auto_commit off"

    new_text = "".join(lines)

    # 轻量 YAML 结构护栏（不依赖 PyYAML）
    top_hooks = [ln for ln in new_text.splitlines() if RE_HOOKS.match(ln)]
    if len(top_hooks) != 1:
        return {"file": CONFIG_REL, "status": "error",
                "detail": f"YAML 护栏：顶层 hooks: 出现 {len(top_hooks)} 次（期望 1），不修改"}
    if HOOK_CMD not in new_text:
        return {"file": CONFIG_REL, "status": "error",
                "detail": "YAML 护栏：hook 命令未写入，不修改"}
    active_commit_keys = [ln for ln in new_text.splitlines() if RE_AUTO_COMMIT.match(ln)]
    if len(active_commit_keys) > 1:
        return {"file": CONFIG_REL, "status": "error",
                "detail": f"YAML 护栏：session_auto_commit 出现 {len(active_commit_keys)} 次（期望 ≤1），不修改"}

    if new_text == text:
        return {"file": CONFIG_REL, "status": "skipped", "detail": "already current"}
    return {"file": CONFIG_REL, "status": "applied", "detail": detail, "_write": (path, new_text)}


# ----------------------------------------------------------------- .gitignore 兜底（2026-10-15 补，第 5 个触点）

GITIGNORE_REL = ".gitignore"
ADAPTER_OUT_LINE = ".adapter-out/"


def wire_gitignore(target: Path) -> dict:
    """`.gitignore` 追加 `.adapter-out/`（issue #8 后所有接线项目都需要，不只图谱用户）。

    三条判据（缺失即跳过并显式说明，不猜）：
      * 文件**不存在 ⇒ 不首创**——根 `.gitignore` 是用户自有文件，本脚手不替用户从零创建，
        只在报告里给出建议行；
      * 内容已含 `.adapter-out` **子串** ⇒ 已忽略，幂等跳过（子串判据兼容
        `.adapter-out`、`.adapter-out/*` 等一切等价写法）；
      * 出现 `!.adapter-out` 负模式 ⇒ 意见相反，跳过不与用户打架。
    """
    path = target / GITIGNORE_REL
    if not path.is_file():
        return {"file": GITIGNORE_REL, "status": "skipped",
                "detail": f"无 {GITIGNORE_REL} ⇒ 不首创（建议手动加一行 {ADAPTER_OUT_LINE}）"}
    text = path.read_text(encoding="utf-8")
    if "!" + ADAPTER_OUT_LINE.rstrip("/") in text:
        return {"file": GITIGNORE_REL, "status": "skipped",
                "detail": "存在 !.adapter-out 负模式 ⇒ 不与用户既有规则打架"}
    if ADAPTER_OUT_LINE.rstrip("/") in text:
        return {"file": GITIGNORE_REL, "status": "skipped", "detail": "已忽略 .adapter-out"}
    new_text = (text if text.endswith("\n") else text + "\n") + ADAPTER_OUT_LINE + "\n"
    return {"file": GITIGNORE_REL, "status": "applied",
            "detail": "appended .adapter-out/ (atlas 中间产物单一位点，issue #8)",
            "_write": (path, new_text)}


# ----------------------------------------------------------------- pi 宿主扩展（2026-10-15 补，第 4 个触点）

PI_REL = ".pi"
PI_SETTINGS_REL = ".pi/settings.json"
PI_EXT_ENTRY = "./extensions/atlas/index.ts"
PI_EXT_DEST_REL = ".pi/extensions/atlas/index.ts"
# 扩展源：`__file__` 的爷爷目录就是包根（源包态 = 仓库根；副本态 = `.atlas/`）
PI_EXT_SRC_REL = "extensions/pi.ts"

RE_EXT_ARRAY = re.compile(r'"extensions"\s*:\s*\[')


def _pi_ext_source() -> Path:
    return Path(__file__).resolve().parents[2] / PI_EXT_SRC_REL


def wire_pi_extension(target: Path) -> list[dict]:
    """pi 宿主：把官方扩展落到 `.pi/extensions/atlas/index.ts`，并在 `.pi/settings.json`
    的 `extensions` 数组里**幂等登记**一行（2026-10-15 补 —— 此前该扩展只在 npm 包里有，
    装配从不落地它，于是 `/atlas` 命令与「未开户」提示在真实项目里全都不存在）。

    三条纪律：
      * **非 pi 宿主不动**：没有 `.pi/` ⇒ 跳过（不替用户创建宿主目录）。
      * **外科式插入**：`settings.json` 只往数组里插一行，不整体重写（本脚本的既有设计要点）；
        数组形态无法可靠判读（缺 `extensions` 键 / 空数组）⇒ **跳过并给出要手加的那一行**，
        不猜结构、不覆盖。
      * **可逆**：注销 = 删掉那一行 + 删 `.pi/extensions/atlas/`。
    """
    pi_dir = target / PI_REL
    if not pi_dir.is_dir():
        return [{"file": PI_EXT_DEST_REL, "status": "skipped", "detail": "非 pi 宿主（无 .pi/），跳过"}]

    out: list[dict] = []

    # ① 扩展本体
    src = _pi_ext_source()
    dest = target / PI_EXT_DEST_REL
    if not src.is_file():
        out.append({"file": PI_EXT_DEST_REL, "status": "error",
                    "detail": f"找不到扩展源 {src}（包面缺 extensions/pi.ts）"})
    else:
        new_text = src.read_text(encoding="utf-8")
        if dest.is_file() and dest.read_text(encoding="utf-8") == new_text:
            out.append({"file": PI_EXT_DEST_REL, "status": "skipped", "detail": "already current"})
        else:
            existed = dest.is_file()
            out.append({"file": PI_EXT_DEST_REL, "status": "applied",
                        "detail": "refreshed from package" if existed else "installed from package",
                        "_write": (dest, new_text)})

    # ② settings.json 登记
    cfg = target / PI_SETTINGS_REL
    if not cfg.is_file():
        out.append({"file": PI_SETTINGS_REL, "status": "skipped",
                    "detail": f"settings.json 不存在 ⇒ 未登记（扩展已就位，手加一行 {PI_EXT_ENTRY}）"})
        return out
    text = cfg.read_text(encoding="utf-8")
    if PI_EXT_ENTRY in text:
        out.append({"file": PI_SETTINGS_REL, "status": "skipped",
                    "detail": "extensions 已含 atlas 扩展"})
        return out
    m = RE_EXT_ARRAY.search(text)
    if not m:
        out.append({"file": PI_SETTINGS_REL, "status": "skipped",
                    "detail": f"无 extensions 数组 ⇒ 不猜结构（手加 \"extensions\": [\"{PI_EXT_ENTRY}\"]）"})
        return out
    # 数组非空 ⇒ 抄第一个元素的行首缩进插一行；空数组 ⇒ 用 2 空格兜底
    tail = text[m.end():]
    nM = re.match(r"(\r?\n[ \t]*)", tail)
    if nM and tail[nM.end():nM.end() + 1] not in ("]", ""):
        indent, sep = nM.group(1), nM.group(1)
        insert = f"{sep}\"{PI_EXT_ENTRY}\","
        new_text = text[:m.end()] + insert + tail
    elif tail.lstrip().startswith("]"):
        line_start = text.rfind("\n", 0, m.start())
        base = text[line_start + 1: m.start()] if line_start >= 0 else ""
        new_text = (text[:m.end()] + "\n" + base + "  " + f"\"{PI_EXT_ENTRY}\"" + "\n" + base + "]"
                    + tail.lstrip()[1:])
    else:
        out.append({"file": PI_SETTINGS_REL, "status": "skipped",
                    "detail": f"extensions 数组形态无法判读 ⇒ 未登记（手加一行 {PI_EXT_ENTRY}）"})
        return out
    try:
        json.loads(new_text)
    except json.JSONDecodeError as exc:
        out.append({"file": PI_SETTINGS_REL, "status": "error",
                    "detail": f"插入后 JSON 非法，放弃写入：{exc}"})
        return out
    out.append({"file": PI_SETTINGS_REL, "status": "applied",
                "detail": "registered atlas extension in extensions[]", "_write": (cfg, new_text)})
    return out


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
    try:
        load_layout(target)
    except LayoutError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2

    results = [wire_agents(target), wire_config(target), wire_project(target),
               wire_gitignore(target)]
    results += wire_pi_extension(target)
    errors = sum(1 for r in results if r["status"] == "error")

    if write:
        for r in results:
            if r["status"] == "applied" and "_write" in r:
                p, t = r["_write"]
                p.parent.mkdir(parents=True, exist_ok=True)  # `.pi/extensions/atlas/` 这类新目录
                p.write_text(t, encoding="utf-8")
            elif r["status"] == "removed" and "_remove" in r:
                r["_remove"].unlink(missing_ok=True)

    for r in results:
        r.pop("_write", None)
        r.pop("_remove", None)

    applied = sum(1 for r in results if r["status"] == "applied")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    removed = sum(1 for r in results if r["status"] == "removed")

    if args.json:
        print(json.dumps({"target": str(target), "dry_run": not write,
                          "applied": applied, "skipped": skipped, "removed": removed,
                          "errors": errors,
                          "results": results}, ensure_ascii=False, indent=2))
    else:
        print(f"▶ 目标项目 : {target}")
        print(f"▶ 模式     : {'apply' if write else 'dry-run'}")
        for r in results:
            icon = {"applied": "✓", "skipped": "=", "error": "✗", "removed": "−"}.get(r["status"], "?")
            print(f"  {icon} {r['file']} — {r['detail']}")
        print(f"合计：applied={applied} skipped={skipped} removed={removed} errors={errors}")
        if not write:
            print("（dry-run：未写入任何文件；如需写入请加 --apply）")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
