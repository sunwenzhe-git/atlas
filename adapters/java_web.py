"""Spring Controller / DTO 静态解析（RFC-20261119-03 Phase 3a）。

**只读文本解析，不执行 Java、不依赖 JDK/Maven/Gradle。** 框架知识的合法落点是
`adapters/`；本文件由 `scripts/adopt_static.py` 直接调用，不注册进
`scripts/refresh_structure.py` 的 `ADAPTER_CATEGORIES`，避免污染 `api` 契约。

能力边界（明确不做，遇到时输出 `confidence=low` / `parse_warnings`，不猜）：
  - SpEL、`params` / `headers` 条件映射、接口继承映射、AOP 改写后的真实路径；
  - Lombok 生成字段、`record` 组件展开、嵌套 Controller 的内部方法；
  - 多行注解参数的复杂拼装、同名 DTO 的包级消歧（列候选并标 `ambiguous`）。

CLI：
    python3 adapters/java_web.py --root <项目根> --out <facts.json> [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:  # 源包内直接运行 / 被 adopt_static 以 adapters 入 sys.path 两种形态
    from _jpa import _ann_value, _has, _match_brace, _strip_comments, parse_classes
except ImportError:  # pragma: no cover - 包形态兜底
    from adapters._jpa import (  # type: ignore
        _ann_value, _has, _match_brace, _strip_comments, parse_classes,
    )

VERSION = "1.0.0"
MAIN_DIRS = ("src/main/java",)
TEST_DIRS = ("src/test/java",)

CONTROLLER_ANN = ("RestController", "Controller")
MAPPING_ANN = {
    "GetMapping": "GET",
    "PostMapping": "POST",
    "PutMapping": "PUT",
    "DeleteMapping": "DELETE",
    "PatchMapping": "PATCH",
}
CLASS_RE = re.compile(r"\bclass\s+([A-Za-z_]\w*)")
METHOD_RE = re.compile(
    r"(?P<anns>(?:@[A-Za-z_]\w*(?:\s*\([^()]*\))?\s*)*)"
    r"(?P<mods>(?:public|protected|private|static|final|synchronized|abstract|native|"
    r"default|\s)*)"
    r"(?P<ret>[A-Za-z_][\w.<>\[\], ?]*)\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*\((?P<params>(?:[^()]|\([^()]*\))*)\)\s*"
    r"(?:throws\s+[^{]+)?\{"
)


def java_sources(root: Path, tests: bool = False) -> list[Path]:
    """标准 Java 源码布局；没有标准目录时退回全仓（排除测试目录）。"""
    bases = TEST_DIRS if tests else MAIN_DIRS
    found: list[Path] = []
    for base in bases:
        d = root / base
        if d.is_dir():
            found.extend(sorted(d.rglob("*.java")))
    if found:
        return found
    if tests:
        return []
    for f in sorted(root.rglob("*.java")):
        rel = f.as_posix()
        if "/test/" in rel or "/tests/" in rel:
            continue
        found.append(f)
    return found


def _depths(text: str) -> list[int]:
    """每个字符前的花括号深度（忽略字符串/注释内的括号；注释已剥离）。"""
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


def _annotations_before(text: str, pos: int) -> str:
    """取 `class` 关键字之前的注解块；兼容 `@RestController public class C {` 同行。"""
    prefix = text[max(0, pos - 2000):pos]
    cut = max(prefix.rfind("}"), prefix.rfind(";"))
    tail = prefix[cut + 1:] if cut >= 0 else prefix
    anns = re.findall(r"@[A-Za-z_]\w*(?:\s*\([^)]*\))?", tail, re.S)
    return "\n".join(anns)


def _split_top(text: str, sep: str = ",") -> list[str]:
    parts: list[str] = []
    cur: list[str] = []
    depth = 0
    quote = ""
    for ch in text:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "'\"":
            quote = ch
            cur.append(ch)
        elif ch in "<([{":
            depth += 1
            cur.append(ch)
        elif ch in ">)]}":
            depth = max(0, depth - 1)
            cur.append(ch)
        elif ch == sep and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur).strip())
    return parts


def _param_info(param: str) -> tuple[str, str, list[str]]:
    anns = re.findall(r"@[A-Za-z_]\w*(?:\s*\([^)]*\))?", param, re.S)
    rest = re.sub(r"@[A-Za-z_]\w*(?:\s*\([^)]*\))?", " ", param, flags=re.S).strip()
    rest = re.sub(r"\bfinal\b", " ", rest).strip()
    m = re.match(r"(.+?)\s+([A-Za-z_]\w*)$", rest, re.S)
    if not m:
        return "", "", anns
    return m.group(1).strip(), m.group(2), anns


def _return_type(raw: str) -> str:
    ret = re.sub(r"\s+", " ", raw).strip()
    m = re.match(r"ResponseEntity\s*<\s*(.+)\s*>$", ret)
    return m.group(1).strip() if m else ret


def _dto_index(root: Path) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for f in java_sources(root):
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = f.relative_to(root).as_posix()
        for d in parse_classes(text, rel):
            index.setdefault(d["name"], []).append({
                "source": rel,
                "kind": d["kind"],
                "fields": [
                    {"name": row["field"], "type": row["type"],
                     "constraints": row.get("constraints")}
                    for row in d["fields"]
                ],
            })
    return index


def _dto_fields(type_name: str, index: dict[str, list[dict[str, Any]]]) -> tuple[list[dict], bool, list[str]]:
    simple = re.sub(r"<.*>", "", type_name).strip()
    candidates = index.get(simple, [])
    if not candidates:
        return [], False, []
    if len(candidates) > 1:
        return [], True, [c["source"] for c in candidates]
    return candidates[0]["fields"], False, []


def parse_project(root: Path) -> dict[str, Any]:
    root = root.resolve()
    endpoints: list[dict[str, Any]] = []
    warnings: list[str] = []
    source_files: list[str] = []
    dto = _dto_index(root)

    for f in java_sources(root):
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            warnings.append(f"跳过不可读文件 {f}: {exc}")
            continue
        rel = f.relative_to(root).as_posix()
        clean = _strip_comments(text)
        depth = _depths(clean)
        for cm in CLASS_RE.finditer(clean):
            ann = _annotations_before(clean, cm.start())
            if not any(_has(ann, a) for a in CONTROLLER_ANN):
                continue
            source_files.append(rel)
            base = _ann_value(ann, "RequestMapping")
            open_pos = clean.find("{", cm.end())
            if open_pos < 0:
                warnings.append(f"{rel}:{cm.group(1)} 未找到类体")
                continue
            close = _match_brace(clean, open_pos)
            if close is None:
                warnings.append(f"{rel}:{cm.group(1)} 类体括号不闭合")
                continue
            body = clean[open_pos + 1:close]
            body_depth = _depths(body)
            base_line = clean.count("\n", 0, open_pos) + 1
            class_endpoints = 0
            for mm in METHOD_RE.finditer(body):
                if body_depth[mm.start()] != 0:
                    continue
                method_ann = mm.group("anns")
                http, path = "", ""
                for name, verb in MAPPING_ANN.items():
                    if _has(method_ann, name):
                        http, path = verb, _ann_value(method_ann, name)
                        break
                if not http and _has(method_ann, "RequestMapping"):
                    path = _ann_value(method_ann, "RequestMapping")
                    vm = re.search(r"method\s*=\s*(?:RequestMethod\.)?([A-Za-z]+)",
                                   method_ann)
                    http = vm.group(1).upper() if vm else "ANY"
                if not http:
                    continue
                class_endpoints += 1
                full_path = "/".join(x.strip("/") for x in (base, path) if x.strip())
                full_path = "/" + full_path if full_path else "/"
                body_type, path_vars, query_vars = "", [], []
                others: list[dict[str, str]] = []
                for p in _split_top(mm.group("params")):
                    if not p:
                        continue
                    typ, name, anns = _param_info(p)
                    if _has("\n".join(anns), "RequestBody"):
                        body_type = re.sub(r"<.*>", "", typ).strip()
                    elif _has("\n".join(anns), "PathVariable"):
                        path_vars.append(name)
                    elif _has("\n".join(anns), "RequestParam"):
                        query_vars.append(name)
                    else:
                        others.append({"type": typ, "name": name})
                fields, ambiguous, candidates = _dto_fields(body_type, dto)
                endpoints.append({
                    "kind": "endpoint",
                    "source": {
                        "file": rel,
                        "line": base_line + body[:mm.start()].count("\n"),
                    },
                    "payload": {
                        "http": http,
                        "path": full_path,
                        "controller": cm.group(1),
                        "handler": mm.group("name"),
                        "request": {
                            "body": body_type or None,
                            "body_fields": fields,
                            "path": path_vars,
                            "query": query_vars,
                            "other": others,
                        },
                        "response": _return_type(mm.group("ret")),
                        "ambiguous": ambiguous,
                        "dto_candidates": candidates,
                    },
                })
            if class_endpoints == 0:
                warnings.append(f"{rel}:{cm.group(1)} 未抽到端点（可能为同行注解 / 多行注解 / 嵌套类形态）")
    return {
        "adapter": "java_web",
        "adapter_version": VERSION,
        "endpoints": endpoints,
        "source_files": sorted(set(source_files)),
        "parse_warnings": warnings,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Spring Controller 静态解析（只读）")
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    data = parse_project(Path(args.root))
    dst = Path(args.out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps({"ok": True, "endpoints": len(data["endpoints"]),
                          "warnings": len(data["parse_warnings"])}, ensure_ascii=False))
    else:
        print(f"[java_web] {len(data['endpoints'])} 个端点 / "
              f"{len(data['parse_warnings'])} 条警告 -> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
