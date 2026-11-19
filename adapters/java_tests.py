"""JUnit 5 + AssertJ 静态解析 → AC 草稿（RFC-20261119-03 Phase 3b）。

**只读文本解析，不执行测试、不依赖 JDK/Maven/Gradle。** 框架知识的合法落点是
`adapters/`；本文件由 `scripts/adopt_static.py` 直接调用，不注册进
`scripts/refresh_structure.py` 的 `tests` 类别（该类别契约没有 AC/断言位）。

反假绿纪律：
  - AC 草稿不是门禁；`confirmed` 恒为 `false`，必须由人确认后才能进入 PRD；
  - 断言含 Mock / 无可静态判定的期望值时，`confidence` 降为 `medium|low`；
  - 不执行 JUnit、不启动 Spring 上下文、不跑 `mvn test`。

CLI：
    python3 adapters/java_tests.py --root <项目根> --out <ac-draft.json> [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from _jpa import _ann_value, _has, _match_brace, _strip_comments
    from java_web import java_sources
except ImportError:  # pragma: no cover - 包形态兜底
    from adapters._jpa import _ann_value, _has, _match_brace, _strip_comments  # type: ignore
    from adapters.java_web import java_sources  # type: ignore

VERSION = "1.0.0"
TEST_ANN = ("Test", "ParameterizedTest")
METHOD_RE = re.compile(
    r"(?P<anns>(?:@[A-Za-z_]\w*(?:\s*\([^()]*\))?\s*)*)"
    r"(?P<mods>(?:public|protected|private|static|final|\s)*)"
    r"(?P<ret>[A-Za-z_][\w.<>\[\], ?]*)\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*\((?P<params>(?:[^()]|\([^()]*\))*)\)\s*"
    r"(?:throws\s+[^{]+)?\{"
)
MOCK_RE = re.compile(r"\b(?:mock|mockito|when|verify|spy|stub)\b", re.I)
LITERAL_EXPECT_RE = re.compile(
    r"(?:assertEquals\s*\(\s*)(\"[^\"]*\"|'[^']*'|\d+(?:\.\d+)?|true|false|null)"
)
ASSERTJ_EXPECT_RE = re.compile(
    r"assertThat\s*\([^;]*?\)\s*\.\s*(?:isEqualTo|isSameAs|contains|hasSize)\s*\(\s*"
    r"(\"[^\"]*\"|'[^']*'|\d+(?:\.\d+)?|true|false|null)"
)


def _depths(text: str) -> list[int]:
    out = [0] * len(text)
    depth = 0
    quote = ""
    i = 0
    while i < len(text):
        ch = text[i]
        out[i] = depth
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in "'\"":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    return out


def _assertions(body: str) -> list[str]:
    """抽取断言原文（保留人可读形态；不做语义解释）。"""
    out: list[str] = []
    buf: list[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        if "assert" in line:
            if buf:
                out.append(" ".join(buf))
            buf = [line]
        elif buf and (line.startswith(".") or line.startswith(")")):
            buf.append(line)
        elif buf:
            out.append(" ".join(buf))
            buf = []
        if buf and line.endswith(";"):
            out.append(" ".join(buf))
            buf = []
    if buf:
        out.append(" ".join(buf))
    return [re.sub(r"\s+", " ", a).strip() for a in out if a.strip()][:12]


def _confidence(assertions: list[str], body: str) -> str:
    if not assertions or MOCK_RE.search(body):
        return "low"
    if any(LITERAL_EXPECT_RE.search(a) or ASSERTJ_EXPECT_RE.search(a)
           for a in assertions):
        return "high"
    return "medium"


def parse_project(root: Path) -> dict[str, Any]:
    root = root.resolve()
    drafts: list[dict[str, Any]] = []
    warnings: list[str] = []
    source_files: list[str] = []
    seq = 0
    for f in java_sources(root, tests=True):
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            warnings.append(f"跳过不可读文件 {f}: {exc}")
            continue
        rel = f.relative_to(root).as_posix()
        clean = _strip_comments(text)
        depth = _depths(clean)
        for m in METHOD_RE.finditer(clean):
            # 测试方法在类体内 ⇒ 顶层类方法的深度为 1；嵌套类（深度 ≥2）不抽。
            if depth[m.start()] != 1:
                continue
            anns = m.group("anns")
            if not any(_has(anns, a) for a in TEST_ANN):
                continue
            open_pos = clean.find("{", m.end() - 1)
            close = _match_brace(clean, open_pos) if open_pos >= 0 else None
            if close is None:
                warnings.append(f"{rel}:{m.group('name')} 方法体括号不闭合")
                continue
            body = clean[open_pos + 1:close]
            assertions = _assertions(body)
            seq += 1
            display = _ann_value(anns, "DisplayName") or m.group("name")
            source_files.append(rel)
            drafts.append({
                "id": f"AC-DRAFT-{seq:03d}",
                "source": {
                    "file": rel,
                    "line": clean.count("\n", 0, m.start()) + 1,
                    "test": m.group("name"),
                },
                "display_name": display,
                "assertions": assertions,
                "confidence": _confidence(assertions, body),
                "mock_dependent": bool(MOCK_RE.search(body)),
                "confirmed": False,
                "status": "待人工确认",
            })
    return {
        "adapter": "java_tests",
        "adapter_version": VERSION,
        "ac_drafts": drafts,
        "source_files": sorted(set(source_files)),
        "parse_warnings": warnings,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="JUnit 5 + AssertJ 静态解析（只读）")
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    data = parse_project(Path(args.root))
    dst = Path(args.out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps({"ok": True, "ac_drafts": len(data["ac_drafts"]),
                          "warnings": len(data["parse_warnings"])}, ensure_ascii=False))
    else:
        print(f"[java_tests] {len(data['ac_drafts'])} 条 AC 草稿 / "
              f"{len(data['parse_warnings'])} 条警告 -> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
