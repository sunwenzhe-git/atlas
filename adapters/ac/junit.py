#!/usr/bin/env python3
"""JUnit 5 AC 提取器（框架知识的合法落点）。

轻量行级扫描：识别 `@Test/@ParameterizedTest/@RepeatedTest/@TestFactory` 方法、
`@DisplayName`、`@Disabled/@Ignore`、`@Tag("atlas-dims-Cxx")`；不引入 Java
parser/JVM 依赖。JUnit 的复杂动态形态（TestFactory / 参数化占位符）标 weak
并进扫描面，不假装覆盖。

标记约定（与 `docs/guide/backend-test.md` 对齐）：
  * AC：`@DisplayName("[AC-...] ...")`（或方法名里的 `[AC-...]`）；
  * dims：重复的 `@Tag("atlas-dims-C01")`（JUnit @Tag 不允许逗号）；
  * waiver：`@Disabled("waiver: ...")` / `@Ignore("waiver: ...")`。
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

TITLE_AC_RE = re.compile(r"\[(AC-[A-Z0-9]+-\d+)\]")
TEST_ANN_RE = re.compile(r"@(Test|ParameterizedTest|RepeatedTest|TestFactory)\b")
CLASS_RE = re.compile(r"\b(?:class|interface|record|enum)\s+([A-Za-z_]\w*)")
METHOD_RE = re.compile(r"([A-Za-z_]\w*)\s*\(")
JAVA_KEYWORDS = {
    "if", "for", "while", "switch", "catch", "new", "return", "throw",
    "synchronized", "try", "assert", "super", "this",
}
SKIP_DIRS = {
    "node_modules", ".git", "target", "build", "out", "dist", "coverage",
    "__pycache__", ".venv", "venv", ".atlas", ".atlas-run", ".scratch", ".trellis", ".gradle",
}


def _strip_comments(text: str) -> str:
    out: list[str] = []
    i, n = 0, len(text)
    quote = ""
    in_line = False
    in_block = False
    while i < n:
        if in_line:
            if text[i] == "\n":
                in_line = False
                out.append("\n")
            else:
                out.append(" ")
            i += 1
            continue
        if in_block:
            if text.startswith("*/", i):
                in_block = False
                out.append("  ")
                i += 2
            else:
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            continue
        if quote:
            out.append(text[i])
            if text[i] == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if text[i] == quote:
                quote = ""
            i += 1
            continue
        if text.startswith("//", i):
            in_line = True
            out.append("  ")
            i += 2
            continue
        if text.startswith("/*", i):
            in_block = True
            out.append("  ")
            i += 2
            continue
        if text[i] in "'\"":
            quote = text[i]
        out.append(text[i])
        i += 1
    return "".join(out)


def _unescape(s: str) -> str:
    return (s.replace("\\n", "\n").replace("\\t", "\t")
            .replace('\\"', '"').replace("\\\\", "\\"))


def _ann_value(annotations: str, name: str) -> str:
    m = re.search(
        r"@%s\s*\(\s*(?:value\s*=\s*)?\"((?:\\.|[^\"\\])*)\"" % re.escape(name),
        annotations,
    )
    return _unescape(m.group(1)) if m else ""


def _tag_values(annotations: str) -> list[str]:
    return [_unescape(m.group(1)) for m in re.finditer(
        r"@Tag\s*\(\s*\"((?:\\.|[^\"\\])*)\"\s*\)", annotations
    )]


def _iter_java_files(test_dir: Path, root: Path) -> list[Path]:
    if not test_dir.is_dir():
        return []
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(test_dir):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            if not name.endswith(".java"):
                continue
            p = Path(dirpath) / name
            try:
                rel = p.relative_to(root).as_posix()
            except ValueError:
                rel = p.as_posix()
            if "/src/main/" in f"/{rel}":
                continue
            files.append(p)
    return files


def _scan(text: str, rel: str) -> tuple[list[dict[str, Any]], list[str]]:
    clean = _strip_comments(text)
    tests: list[dict[str, Any]] = []
    scan_face: list[str] = []
    class_name = ""
    class_scope = False
    class_disabled = False
    class_waiver = ""
    pending: list[str] = []

    def flush_pending(line: str, lineno: int) -> None:
        nonlocal pending
        ann = "\n".join(pending)
        pending = []
        if not TEST_ANN_RE.search(ann):
            return
        m = METHOD_RE.search(line)
        if not m:
            return
        method = m.group(1)
        if method in JAVA_KEYWORDS:
            return
        display = _ann_value(ann, "DisplayName")
        title = display or method
        acs = set(TITLE_AC_RE.findall(display)) | set(TITLE_AC_RE.findall(method))
        tags = _tag_values(ann)
        dims: set[str] = set()
        bad: list[str] = []
        dims_present = False
        shape_ok = True
        for tag in tags:
            if not tag.startswith("atlas-dims-"):
                continue
            dims_present = True
            suffix = tag[len("atlas-dims-"):]
            parsed, bad_tokens, ok = _ac_coverage.parse_dims_list(suffix)
            dims.update(parsed)
            bad.extend(bad_tokens)
            shape_ok = shape_ok and ok
        disabled_reason = _ann_value(ann, "Disabled") or _ann_value(ann, "Ignore")
        skipped = class_disabled or bool(re.search(r"@(Disabled|Ignore)\b", ann))
        waiver = ""
        if skipped:
            candidate = disabled_reason or class_waiver
            waiver = candidate if "waiver:" in candidate.lower() else ""
        parameterized = bool(re.search(r"@ParameterizedTest\b", ann))
        test_factory = bool(re.search(r"@TestFactory\b", ann))
        dynamic_display = bool(display) and ("{" in display or "#" in display)
        weak = skipped or parameterized or test_factory or dynamic_display
        if class_scope:
            scan_face.append(f"{rel}:{lineno} class 级 AC/dims 不支持继承")
        if test_factory:
            scan_face.append(f"{rel}:{lineno} @TestFactory 动态用例未静态展开")
        if dynamic_display:
            scan_face.append(f"{rel}:{lineno} 参数化 DisplayName 占位符，按静态部分计入")
        tests.append({
            "name": f"{class_name}.{method}" if class_name else method,
            "file": rel,
            "line": lineno,
            "acs": acs,
            "marker_acs": acs,
            "doc_acs": set(),
            "dims": dims,
            "dims_bad": bad,
            "dims_shape_ok": shape_ok,
            "dims_present": dims_present,
            "skipped": skipped,
            "waiver": waiver,
            "weak": weak,
            "marker_scope_unsupported": class_scope,
        })

    for lineno, line in enumerate(clean.splitlines(), 1):
        s = line.strip()
        if not s:
            continue
        if s.startswith("@"):
            pending.append(s)
            continue
        cm = CLASS_RE.search(s)
        if cm:
            class_name = cm.group(1)
            ann = "\n".join(pending)
            pending = []
            tags = _tag_values(ann)
            display = _ann_value(ann, "DisplayName")
            class_scope = bool(TITLE_AC_RE.search(display)) or any(
                t.startswith("atlas-dims-") for t in tags
            )
            class_disabled = bool(re.search(r"@(Disabled|Ignore)\b", ann))
            reason = _ann_value(ann, "Disabled") or _ann_value(ann, "Ignore")
            class_waiver = reason if "waiver:" in reason.lower() else ""
            continue
        if "(" in s and pending:
            flush_pending(s, lineno)
            continue
        if pending and (";" in s or "=" in s or "}" in s):
            pending = []

    return tests, scan_face


class Extractor:
    def __init__(self, name: str = "junit5") -> None:
        self.name = name

    def extract(self, root: Path, test_dir: Path, cfg: dict[str, Any] | None = None) -> ExtractResult:
        files = _iter_java_files(test_dir, root)
        if not files:
            return ExtractResult(
                input_state="absent",
                scan_face=[f"扫描面无 Java 测试文件：{test_dir}"],
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
            found, face = _scan(text, rel)
            tests.extend(found)
            scan_face.extend(face)
        return ExtractResult(
            tests=tests,
            parse_errors=parse_errors,
            scan_face=scan_face,
            input_state="present",
        )
