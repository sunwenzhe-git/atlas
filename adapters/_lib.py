#!/usr/bin/env python3
"""适配器共用工具。**不是适配器本体**，不会被 `stack-profile.adapters` 解析。

提供：确定性文件遍历（剪依赖/构建目录）、`stack-profile.yaml` 的 apps 解析、
统一报错与 JSON 落盘。框架识别仍留在各适配器内部。
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _support.layout import load_layout  # noqa: E402

IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", "site-packages", "dist", "build",
    ".next", ".turbo", ".mypy_cache", ".pytest_cache", ".pyxle-build",
    "coverage", ".coverage", ".venv", "venv", ".scratch", "target",
    ".gradle", ".idea", ".atlas", ".atlas-run", ".trellis", ".adapter-out",
}


def die(adapter: str, msg: str) -> None:
    print(f"ERROR[{adapter}]: {msg}", file=sys.stderr)
    sys.exit(1)


def iter_files(root: Path, suffixes: tuple[str, ...], app_path: str | None = None):
    """遍历 root（或某 app）下指定后缀的文件，剪掉依赖/构建/VCS 目录，顺序确定。"""
    base = root / app_path if app_path else root
    if not base.exists():
        return
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in IGNORE_DIRS and not d.startswith(".venv") and not d.endswith(".venv")
        )
        for name in sorted(filenames):
            if name.endswith(suffixes):
                yield Path(dirpath) / name


def read_source(f: Path, rel: str, adapter: str) -> str | None:
    """读单个源文件；读不出（I/O 错误 / 非 UTF-8）⇒ WARN 后跳过，不中断整次扫描。

    与 `_scaffold.py` 同口径：单文件失败只影响该文件，整次扫描照常收口。
    """
    try:
        return f.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"WARN[{adapter}]: 跳过无法读取的文件 {rel}（非 UTF-8 或 I/O 错误）: {exc}",
              file=sys.stderr)
        return None


def load_apps(root: Path, adapter: str = "adapters") -> list[dict]:
    """读资产根/stack-profile.yaml 的 apps（name / path / role）。"""
    p = load_layout(root).stack_profile
    if not p.is_file():
        return []
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"WARN[{adapter}]: 无法读取 {p.name}（非 UTF-8 或 I/O 错误）⇒ 按无 apps[] 处理: "
              f"{exc}", file=sys.stderr)
        return []
    apps: list[dict] = []
    cur: dict | None = None
    in_apps = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("apps:"):
            in_apps = True
            continue
        if in_apps and line[:1] not in (" ", "\t"):
            in_apps = False
            cur = None
            continue
        if not in_apps:
            continue
        m = re.match(r"^\s*-\s*name:\s*(.+?)\s*$", line)
        if m:
            cur = {"name": m.group(1).strip().strip("'\"")}
            apps.append(cur)
            continue
        m = re.match(r"^\s+(path|role):\s*(.+?)\s*$", line)
        if m and cur is not None:
            cur[m.group(1)] = m.group(2).strip().strip("'\"")
    return apps


def resolve_app(root: Path, apps: list[dict], name: str | None, adapter: str) -> str | None:
    """--app 名 → apps[].path；返回单 app 遍历根，None 表示未显式指定 app。

    未显式指定时的默认扫描面由 `scan_scope` 决定（apps[] 收窄 / 无 apps[] 兜底），
    不再等于「整项目递归」。
    """
    if not name:
        return None
    hit = next((a for a in apps if a.get("name") == name), None)
    if hit is None:
        die(adapter, f"--app {name} 不在 stack-profile.apps 中")
    return hit.get("path") or hit.get("name")


@dataclass(frozen=True)
class ScanScope:
    """默认扫描面（issue #64）：apps[] 注册项 + 根目录文件；未登记顶层目录排除并计数。"""

    mode: str                      # explicit-app | apps | fallback
    roots: tuple[str, ...]         # 项目相对扫描根；"." = 整个项目根
    excluded: tuple[str, ...]      # 默认排除的顶层目录（项目相对）
    include_root_files: bool       # 是否扫根目录直接文件（顶层目录之外的文件）

    def includes(self, rel: str) -> bool:
        if "/" not in rel:
            return self.include_root_files or "." in self.roots
        for r in self.roots:
            if r == "." or rel == r or rel.startswith(r + "/"):
                return True
        return False

    def payload(self) -> dict:
        return {
            "mode": self.mode,
            "roots": list(self.roots),
            "excluded": list(self.excluded),
            "excluded_count": len(self.excluded),
        }

    def describe(self) -> str:
        if self.mode == "explicit-app":
            return f"--app 作用域 {self.roots[0]}（显式指定，行为不变）"
        names = "、".join(self.excluded) if self.excluded else "无"
        if self.mode == "apps":
            head = f"apps[] 注册 {len(self.roots)} 个（{'、'.join(self.roots)}）"
        else:
            head = (f"未声明可用 apps[] ⇒ 兜底扫描含源码的顶层目录"
                    f"（{'、'.join(self.roots) or '无'}）+ 根目录文件")
        return f"{head}；排除未登记顶层目录 {len(self.excluded)} 个（{names}）"


def _norm_app_path(value: str | None) -> str:
    p = (value or "").strip().replace("\\", "/").strip("/")
    return p or "."


def _top_level_dirs(root: Path) -> list[str]:
    return sorted(
        p.name for p in root.iterdir()
        if p.is_dir() and p.name not in IGNORE_DIRS
        and not p.name.startswith(".venv") and not p.name.endswith(".venv")
    )


def _has_candidate_source(base: Path, suffixes: tuple[str, ...]) -> bool:
    for _dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in IGNORE_DIRS and not d.startswith(".venv") and not d.endswith(".venv")
        )
        if any(n.endswith(suffixes) for n in filenames):
            return True
    return False


def _dedupe_roots(roots: list[str]) -> list[str]:
    """去掉被祖先根覆盖的嵌套根（"apps" + "apps/web" ⇒ 只留 "apps"）。"""
    out: list[str] = []
    for p in roots:
        if p == ".":
            return ["."]
        if any(q != p and (p == q or p.startswith(q + "/")) for q in roots):
            continue
        out.append(p)
    return out


def scan_scope(root: Path, apps: list[dict], app_path: str | None,
               suffixes: tuple[str, ...], adapter: str) -> ScanScope:
    """按 apps[] 收窄默认扫描面；显式 --app 行为不变；无 apps[] 时走可解释兜底。"""
    if app_path:
        return ScanScope("explicit-app", (_norm_app_path(app_path),), (), False)

    top = _top_level_dirs(root)
    registered: list[str] = []
    for a in apps:
        p = _norm_app_path(a.get("path") or a.get("name"))
        if p not in registered:
            registered.append(p)
    missing = [p for p in registered if p != "." and not (root / p).is_dir()]
    existing = _dedupe_roots([p for p in registered if p == "." or (root / p).is_dir()])
    if missing:
        print(f"WARN[{adapter}]: apps[].path 不存在，已排除: {'、'.join(missing)}",
              file=sys.stderr)
    if existing:
        covered = {t for t in top if any(t == p or p.startswith(t + "/") for p in existing)}
        return ScanScope("apps", tuple(existing),
                         tuple(t for t in top if t not in covered), True)

    # 兜底：没有可用 apps[] ⇒ 只扫「含候选源码的顶层目录」+ 根目录文件，不整仓递归。
    roots = tuple(d for d in top if _has_candidate_source(root / d, suffixes))
    excluded = tuple(d for d in top if d not in roots)
    return ScanScope("fallback", roots, excluded, True)


def iter_scope_files(root: Path, suffixes: tuple[str, ...], scope: ScanScope):
    """按扫描面产出候选文件（确定性；根目录文件与根遍历不重复）。"""
    seen: set[Path] = set()
    if scope.include_root_files and "." not in scope.roots:
        for p in sorted(root.iterdir()):
            if p.is_file() and p.name.endswith(suffixes):
                seen.add(p)
                yield p
    for r in scope.roots:
        for f in iter_files(root, suffixes, None if r == "." else r):
            if f in seen:
                continue
            seen.add(f)
            yield f


def write_json(adapter: str, out: str, payload: dict) -> None:
    dst = Path(out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    n = len(payload.get("items", []))
    print(f"[{adapter}] {n} 项 / {len(payload.get('source_files', []))} 个源文件 -> {dst}")


def strip_js_comments(text: str) -> str:
    """去掉 JS/TS 的 `//` 与 `/* */` 注释，**保留换行**（行号据此稳定）。

    必须懂引号：`'https://x'` 里的 `//` 不是注释——朴素 `split("//")` 会把 URL 砍断。
    注释同样是**源码事实的敌人**：被注掉的条目/字段若仍被当活事实收走，产出的就是假事实
    （2026-10-15 实测：被 `//` 注掉的路由条目仍被收进清单）。
    """
    out: list[str] = []
    i, n = 0, len(text)
    quote = ""
    while i < n:
        ch = text[i]
        if quote:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in "'\"`":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            i = text.find("\n", i)
            if i < 0:
                break
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            out.extend(c for c in text[i:end] if c == "\n")
            i = end
            continue
        out.append(ch)
        i += 1
    return "".join(out)
