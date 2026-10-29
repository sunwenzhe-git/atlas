#!/usr/bin/env python3
"""Vitest/Jest AC 提取器（框架知识的合法落点）。

轻量词法扫描：识别 `it/test/describe` 调用、标题字符串、紧邻 JSDoc 与
`.skip/.todo/.fails` 等修饰；不引入 TS/JS parser，保持零第三方依赖。

标记约定（与 `docs/guide/backend-test.md` 对齐）：
  * AC：测试标题里的 `[AC-...]`；
  * dims：紧邻 JSDoc 的 `@atlas-dims C01,C11`；
  * waiver：标题或 JSDoc 里的 `waiver:` / `@atlas-waiver`。
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

from . import ExtractResult

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from _support.siblings import load_module  # noqa: E402

_ac_coverage = load_module("ac_coverage")

AC_ID_RE = re.compile(r"\b(AC-[A-Z0-9]+-\d+)\b")
TITLE_AC_RE = re.compile(r"\[(AC-[A-Z0-9]+-\d+)\]")
CALL_RE = re.compile(
    r"\b(it|test|describe|xit|xdescribe|fit|fdescribe)\b"
    r"(\s*\.\s*(skip|todo|only|fails|concurrent|skipIf|each))?\s*\("
)
DESCRIBE_NAMES = {"describe", "xdescribe", "fdescribe"}
TEST_NAMES = {"it", "test", "xit", "fit"}
JS_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
SKIP_DIRS = {
    "node_modules", ".git", "dist", "build", ".next", ".nuxt", ".output",
    "coverage", "__pycache__", ".venv", "venv", "vendor", ".cache", "out",
    "target", ".atlas", ".atlas-run", ".scratch", ".trellis", ".turbo",
}
E2E_PREFIXES = ("product/e2e/", ".atlas-run/", ".atlas/")


# ------------------------------------------------------------------ 轻量词法

def _skip_ws_comments(text: str, pos: int) -> int:
    while pos < len(text):
        ch = text[pos]
        if ch.isspace():
            pos += 1
        elif text.startswith("//", pos):
            nl = text.find("\n", pos)
            pos = len(text) if nl < 0 else nl + 1
        elif text.startswith("/*", pos):
            end = text.find("*/", pos + 2)
            pos = len(text) if end < 0 else end + 2
        else:
            break
    return pos


def _parse_string(text: str, pos: int) -> tuple[str, int, bool] | None:
    """解析字符串/模板字面量；模板含 ${} ⇒ dynamic=True。"""
    if pos >= len(text) or text[pos] not in "'\"`":
        return None
    quote = text[pos]
    i = pos + 1
    out: list[str] = []
    dynamic = False
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            if i + 1 >= len(text):
                return None
            out.append(text[i:i + 2])
            i += 2
        elif ch == quote:
            return ("".join(out), i + 1, dynamic)
        elif quote == "`" and text.startswith("${", i):
            dynamic = True
            depth = 1
            j = i + 2
            while j < len(text) and depth:
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                j += 1
            if depth:
                return None
            out.append("${...}")
            i = j
        else:
            out.append(ch)
            i += 1
    return None


def _match_paren(text: str, open_pos: int) -> int | None:
    depth = 0
    i = open_pos
    quote = ""
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if text.startswith("//", i):
            nl = text.find("\n", i)
            i = len(text) if nl < 0 else nl + 1
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = len(text) if end < 0 else end + 2
            continue
        if ch in "'\"`":
            quote = ch
            i += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _noncode_ranges(text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    i, n = 0, len(text)
    while i < n:
        if text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            ranges.append((i, j))
            i = j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            ranges.append((i, j))
            i = j
        elif text[i] in "'\"`":
            parsed = _parse_string(text, i)
            if parsed is None:
                i += 1
                continue
            ranges.append((i, parsed[1]))
            i = parsed[1]
        else:
            i += 1
    return ranges


def _is_code(ranges: list[tuple[int, int]], pos: int) -> bool:
    return not any(start <= pos < end for start, end in ranges)


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _jsdoc_before(text: str, pos: int) -> str:
    start = text.rfind("/**", 0, pos)
    if start < 0:
        return ""
    end = text.find("*/", start + 3)
    if end < 0 or end + 2 > pos:
        return ""
    if text[end + 2:pos].strip():
        return ""
    return text[start:end + 2]


def _jsdoc_tags(block: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "acs": set(), "dims": set(), "dims_bad": [], "dims_shape_ok": True,
        "dims_present": False, "waiver": "",
    }
    if not block:
        return out
    m = re.search(r"@atlas-ac\b([^\n*]*)", block)
    if m:
        out["acs"].update(AC_ID_RE.findall(m.group(1)))
    m = re.search(r"@atlas-dims\b([^\n*]*)", block)
    if m:
        out["dims_present"] = True
        dims, bad, ok = _ac_coverage.parse_dims_list(m.group(1).strip())
        out["dims"], out["dims_bad"], out["dims_shape_ok"] = dims, bad, ok
    m = re.search(r"@atlas-waiver\b([^\n*]*)", block)
    if m:
        out["waiver"] = m.group(1).strip()
    return out


def _calls(text: str) -> list[dict[str, Any]]:
    ranges = _noncode_ranges(text)
    out: list[dict[str, Any]] = []
    for m in CALL_RE.finditer(text):
        if not _is_code(ranges, m.start()):
            continue
        name = m.group(1)
        if name not in TEST_NAMES | DESCRIBE_NAMES:
            continue
        open_pos = m.end() - 1
        close = _match_paren(text, open_pos)
        if close is None:
            continue
        arg_pos = _skip_ws_comments(text, open_pos + 1)
        parsed = _parse_string(text, arg_pos)
        out.append({
            "name": name,
            "modifier": m.group(3) or "",
            "start": m.start(),
            "end": close,
            "title": parsed[0] if parsed else None,
            "dynamic": parsed[2] if parsed else False,
            "jsdoc": _jsdoc_before(text, m.start()),
            "line": _line_of(text, m.start()),
        })
    return out


def _iter_test_files(test_dir: Path, root: Path) -> list[Path]:
    if not test_dir.is_dir():
        return []
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(test_dir):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if p.suffix not in JS_SUFFIXES:
                continue
            if ".test." not in name and ".spec." not in name and "__tests__" not in p.parts:
                continue
            try:
                rel = p.relative_to(root).as_posix()
            except ValueError:
                rel = p.as_posix()
            if rel.startswith(E2E_PREFIXES):
                continue
            files.append(p)
    return files


class Extractor:
    def __init__(self, name: str = "vitest") -> None:
        self.name = name

    def extract(self, root: Path, test_dir: Path, cfg: dict[str, Any] | None = None) -> ExtractResult:
        files = _iter_test_files(test_dir, root)
        if not files:
            return ExtractResult(
                input_state="absent",
                scan_face=[f"扫描面无 JS/TS 测试文件：{test_dir}"],
            )
        tests: list[dict[str, Any]] = []
        parse_errors: list[str] = []
        scan_face: list[str] = []
        for p in files:
            try:
                text = p.read_text(encoding="utf-8")
            except Exception as exc:
                parse_errors.append(f"{p.relative_to(root)}: {exc}")
                continue
            rel = str(p.relative_to(root))
            calls = _calls(text)
            describes = [c for c in calls if c["name"] in DESCRIBE_NAMES]
            for c in calls:
                if c["name"] in DESCRIBE_NAMES:
                    continue
                if c["title"] is None:
                    scan_face.append(
                        f"{rel}:{c['line']} 动态/非字符串标题（test.each / skipIf / 变量），未静态提取"
                    )
                    continue
                parents = [d for d in describes if d["start"] < c["start"] < d["end"]]
                parents.sort(key=lambda d: d["start"])
                parent_titles = [d["title"] or "<dynamic>" for d in parents]
                parent_skip = any(
                    d["name"] == "xdescribe" or d["modifier"] in ("skip", "todo")
                    for d in parents
                )
                parent_scope = False
                for d in parents:
                    dt = _jsdoc_tags(d["jsdoc"])
                    if TITLE_AC_RE.search(d["title"] or "") or dt["acs"] or dt["dims_present"]:
                        parent_scope = True
                tags = _jsdoc_tags(c["jsdoc"])
                title_acs = set(TITLE_AC_RE.findall(c["title"]))
                marker_acs = title_acs | tags["acs"]
                skipped = parent_skip or c["name"] == "xit" or c["modifier"] in ("skip", "todo")
                weak = skipped or c["modifier"] in ("fails", "skipIf") or c["dynamic"]
                waiver = tags["waiver"] if skipped else ""
                if skipped and not waiver and "waiver:" in c["title"].lower():
                    waiver = c["title"]
                if c["modifier"] == "each":
                    scan_face.append(f"{rel}:{c['line']} test.each 表格未静态展开")
                if c["name"] == "fit" or c["modifier"] == "only":
                    scan_face.append(f"{rel}:{c['line']} 聚焦用例（fit/only）")
                if c["dynamic"]:
                    scan_face.append(f"{rel}:{c['line']} 动态标题，按静态可读部分计入")
                if parent_scope:
                    scan_face.append(f"{rel}:{c['line']} describe 级 AC/dims 不支持继承")
                tests.append({
                    "name": " > ".join(parent_titles + [c["title"]]),
                    "file": rel,
                    "line": c["line"],
                    "acs": marker_acs,
                    "marker_acs": marker_acs,
                    "doc_acs": set(),
                    "dims": tags["dims"],
                    "dims_bad": tags["dims_bad"],
                    "dims_shape_ok": tags["dims_shape_ok"],
                    "dims_present": tags["dims_present"],
                    "skipped": skipped,
                    "waiver": waiver,
                    "weak": weak,
                    "marker_scope_unsupported": parent_scope,
                })
        return ExtractResult(
            tests=tests,
            parse_errors=parse_errors,
            scan_face=scan_face,
            input_state="present",
        )
