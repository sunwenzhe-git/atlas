#!/usr/bin/env python3
"""atlas apply —— Trellis Plan 挂载补丁的锚点式**版本化**应用器。

用法：
    python3 apply-patches.py --target <项目根> [--spec <spec.json>] [--apply] [--json]

设计要点
  * 只做**外科式插入 / 整块替换**，不整体覆盖 `<项目根>/.trellis/workflow.md`——
    因此与其它对 workflow.md 的改动互不覆盖。
  * **版本化块**（2026-09-27，`3509 §B93`）：
        <!-- atlas:apply:<id>@<sha256前8位> -->
        <片段正文>
        <!-- /atlas:apply:<id> -->
    判据于是不再是「标记在不在」，而是「**块里的正文是否仍等于当前片段**」：
      - 指纹相同 ⇒ `skipped`
      - 指纹不同（片段更新过）⇒ **整块替换**为当前片段（`replaced`）
      - 旧式块（只有 `<!-- atlas:apply:<id> -->`、无指纹无结束标记）⇒ `upgraded`（仅补格式）
        或 `replaced`（正文与当前片段不符）
  * **旧式块的安全迁移**：`insert_before*` 的块紧邻锚点 ⇒ 边界 = 重算的锚点位置（精确）；
    `insert_after*` 且正文不符 ⇒ **拒绝并报 error**（不做「删到下一个小节」这种会误伤内容的猜测）。
  * 锚点缺失 / 歧义 / 替换未改变字节 → 报 error 且**不修改该文件**。
  * 缺省 dry-run（安全默认）；真正写入需显式 `--apply`。
  * 模式：
      - insert_before / insert_after              —— 锚点为**单行唯一子串**
      - insert_before_regex / insert_after_regex  —— 锚点为**唯一正则**（re.MULTILINE）
    插入内容来自补丁的 `snippet`（相对本目录的文件）。
  * 护栏：`.json` 目标写入前必须能 `json.loads`；`.py` 目标必须能 `compile`。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent
DEFAULT_SPEC = PKG_ROOT / "spec.json"

LINE_MODES = ("insert_before", "insert_after")
REGEX_MODES = ("insert_before_regex", "insert_after_regex")


def marker_re(pid: str) -> re.Pattern[str]:
    """带可选正文指纹的块标记。"""
    return re.compile(rf"<!--\s*atlas:apply:{re.escape(pid)}(?:@(?P<fp>[0-9a-f]{{8}}))?\s*-->")


def end_marker(pid: str) -> str:
    return f"<!-- /atlas:apply:{pid} -->"


def fingerprint(snippet: str) -> str:
    return hashlib.sha256(snippet.rstrip("\n").encode("utf-8")).hexdigest()[:8]


def build_block(pid: str, snippet: str) -> str:
    """标记（带指纹）+ 片段正文 + 结束标记。结束标记由本应用器统一追加，
    片段文件保持纯正文。"""
    return (
        f"<!-- atlas:apply:{pid}@{fingerprint(snippet)} -->\n"
        + snippet.rstrip("\n")
        + "\n"
        + end_marker(pid)
        + "\n"
    )


def locate(text: str, mode: str, patch: dict) -> tuple[int | None, str | None]:
    """返回插入位置；锚点缺失或歧义时返回 (None, 原因)。"""
    if mode in LINE_MODES:
        needle = patch["anchor"]
        lines = text.splitlines(keepends=True)
        hits = [i for i, ln in enumerate(lines) if needle in ln]
        if not hits:
            return None, "anchor not found"
        if len(hits) > 1:
            return None, f"anchor ambiguous ({len(hits)} matches)"
        i = hits[0]
        if mode == "insert_before":
            pos = sum(len(ln) for ln in lines[:i])
        else:
            pos = sum(len(ln) for ln in lines[: i + 1])
        return pos, None

    pattern = patch["pattern"]
    matches = list(re.compile(pattern, re.MULTILINE).finditer(text))
    if not matches:
        return None, "pattern not found"
    if len(matches) > 1:
        return None, f"pattern ambiguous ({len(matches)} matches)"
    m = matches[0]
    return (m.start() if mode == "insert_before_regex" else m.end()), None


def block_end(
    text: str, m: re.Match[str], pid: str, patch: dict, snippet: str
) -> tuple[int | None, str | None]:
    """给定已存在的块标记，返回 (块结束位置, 说明)。

    「块」= 从标记起到本补丁正文结束（含结束标记与紧随的一个换行）。
    """
    e = text.find(end_marker(pid), m.end())
    if e >= 0:
        j = e + len(end_marker(pid))
        return (j + 1 if text[j : j + 1] == "\n" else j), "end-marker"

    body = snippet.rstrip("\n")
    off = m.end()
    if text[off : off + 1] == "\n":
        off += 1
    if text.startswith(body, off):
        j = off + len(body)
        return (j + 1 if text[j : j + 1] == "\n" else j), "snippet"

    if patch["mode"].startswith("insert_before"):
        pos, err = locate(text, patch["mode"], patch)
        if err or pos is None:
            return None, f"legacy block: {err}"
        return pos, "anchor"

    return None, "legacy block without end marker on insert_after（需人工处理）"


def guard(path: Path, new_text: str) -> str | None:
    if path.suffix == ".json":
        try:
            json.loads(new_text)
        except json.JSONDecodeError as exc:
            return f"JSON 护栏拦截：{exc}"
    if path.suffix == ".py":
        try:
            compile(new_text, str(path), "exec")
        except SyntaxError as exc:
            return f"语法护栏拦截：{exc}"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=str(Path.cwd()), help="项目根目录（缺省 = 当前目录）")
    ap.add_argument("--spec", default=str(DEFAULT_SPEC))
    ap.add_argument("--apply", action="store_true", help="真正写入；缺省为 dry-run（安全默认）")
    ap.add_argument("--dry-run", action="store_true", help="显式 dry-run（与缺省等价）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    write = bool(args.apply) and not bool(args.dry_run)
    target = Path(args.target).resolve()
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    prefix = spec.get("target_prefix", "")

    results: list[dict] = []
    errors = 0

    for patch in spec["patches"]:
        pid = patch["id"]
        mode = patch["mode"]
        rel = prefix + patch["file"]
        path = target / rel
        entry = {"id": pid, "issue": patch.get("issue", ""), "file": rel}

        if not path.exists():
            entry.update(status="error", detail="target file not found")
            errors += 1
            results.append(entry)
            continue

        if mode not in LINE_MODES and mode not in REGEX_MODES:
            entry.update(status="error", detail=f"unknown mode {mode}")
            errors += 1
            results.append(entry)
            continue

        snippet_path = PKG_ROOT / patch["snippet"]
        if not snippet_path.is_file():
            entry.update(status="error", detail=f"snippet not found: {patch['snippet']}")
            errors += 1
            results.append(entry)
            continue
        snippet = snippet_path.read_text(encoding="utf-8")
        fp = fingerprint(snippet)
        block = build_block(pid, snippet)

        text = path.read_text(encoding="utf-8")
        m = marker_re(pid).search(text)

        if m:
            old_fp = m.group("fp")
            end, how = block_end(text, m, pid, patch, snippet)
            if end is None:
                entry.update(status="error", detail=how or "block end not found")
                errors += 1
                results.append(entry)
                continue
            if old_fp == fp and how == "end-marker":
                entry.update(status="skipped", detail="already applied（正文版本一致）")
                results.append(entry)
                continue
            if old_fp == fp:
                status, detail = "upgraded", "正文一致，仅补指纹与结束标记"
            elif old_fp:
                status, detail = "replaced", f"正文版本 {old_fp} → {fp}"
            else:
                status = "upgraded" if how in ("snippet", "end-marker") else "replaced"
                detail = "旧式块：补指纹与结束标记" if how in ("snippet", "end-marker") else "旧式块：正文不符，整块替换"
            new_text = text[: m.start()] + block + text[end:]
            if new_text == text:
                entry.update(status="error", detail="replacement produced no change（替换未改变字节）")
                errors += 1
                results.append(entry)
                continue
        else:
            pos, err = locate(text, mode, patch)
            if err:
                entry.update(status="error", detail=err)
                errors += 1
                results.append(entry)
                continue
            new_text = text[:pos] + block + text[pos:]
            if len(new_text) <= len(text):
                entry.update(status="error", detail="insertion produced no growth（锚点定位异常）")
                errors += 1
                results.append(entry)
                continue
            status, detail = "applied", f"+{len(new_text) - len(text)} 字节"

        bad = guard(path, new_text)
        if bad:
            entry.update(status="error", detail=bad)
            errors += 1
            results.append(entry)
            continue

        entry.update(status=status, detail=detail)
        if write:
            path.write_text(new_text, encoding="utf-8")
        results.append(entry)

    counts = {k: sum(1 for r in results if r["status"] == k)
              for k in ("applied", "replaced", "upgraded", "skipped")}

    if args.json:
        print(json.dumps({"target": str(target), "dry_run": not write, **counts,
                          "errors": errors, "results": results}, ensure_ascii=False, indent=2))
    else:
        icons = {"applied": "✓", "replaced": "↻", "upgraded": "↑", "skipped": "=", "error": "✗"}
        print(f"▶ 目标项目 : {target}")
        print(f"▶ 模式     : {'apply' if write else 'dry-run'}")
        for r in results:
            print(f"  {icons.get(r['status'], '?')} [{r['issue']}] {r['id']} — {r['detail']}")
        print("合计：applied={applied} replaced={replaced} upgraded={upgraded} "
              "skipped={skipped} errors={errors}".format(**counts, errors=errors))
        if not write:
            print("（dry-run：未写入任何文件；如需写入请加 --apply）")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
