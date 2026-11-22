#!/usr/bin/env python3
"""Atlas Workflow Context —— 按改动路径选取最小结构上下文。

Trellis 的 spec 注入模型：任务涉及哪些文件，就只注入这些文件命中的规范。
Atlas 的同构实现：

- 规范 = `.atlas/spec/**/*.md` 里**带 `paths:` frontmatter** 的文件
  （结构环 `tour.md` / `domains/<domain>.md`、约定薄桩 `conventions/*.md`）；
- 命中 = 任务改动路径对任一 glob 成立；`**` 跨目录、`*` 不跨目录；
- 最小化 = 显式改动路径存在时**不注入** `**` 兜底规范；结构规范优先，
  约定规范至多补 1 份；最多 3 份；
- 域回退 = 无改动路径时，用任务卡的 `affected_domains` 匹配 `domains/<domain>.md`；
- 完全无信号时，只注入 `**` 兜底规范（如 `tour.md`）供导航。

纯标准库实现。
"""
from __future__ import annotations

import posixpath
import re
from functools import lru_cache
from pathlib import Path

SPEC_DIRS = (".atlas/spec/structure", ".atlas/spec/conventions")
MAX_SPECS = 3
MAX_LINES_PER_SPEC = 80
MAX_CHARS_PER_SPEC = 4000
MAX_FILE_BYTES = 1_000_000

_FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.S)
_PATH_ITEM_RE = re.compile(r"^\s*-\s*(.+?)\s*$")
_PATHS_KEY_RE = re.compile(r"^paths\s*:(.*)$")
_WILDCARDS = ("**", "**/*", "*")


class ContextError(ValueError):
    """结构上下文选取异常。"""


# ---------------------------------------------------------------- frontmatter

def _strip_comment(raw: str) -> str:
    """去掉引号外的行内注释（`- apps/web/** # 前端`）。"""
    out: list[str] = []
    quote = ""
    for ch in raw:
        if quote:
            if ch == quote:
                quote = ""
            out.append(ch)
        elif ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out).strip()


def _unquote(raw: str) -> str:
    s = raw.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def _split_flow_items(raw: str) -> list[str]:
    """解析 `["a", 'b']` 的内部；引号内的逗号不切。"""
    items: list[str] = []
    buf: list[str] = []
    quote = ""
    for ch in raw:
        if quote:
            if ch == quote:
                quote = ""
            buf.append(ch)
        elif ch in ("'", '"'):
            quote = ch
            buf.append(ch)
        elif ch == ",":
            items.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if "".join(buf).strip():
        items.append("".join(buf))
    return [_unquote(_strip_comment(i)) for i in items]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _split_frontmatter(text: str) -> tuple[dict, str]:
    text = text.lstrip("\ufeff")
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    paths: list[str] = []
    lines = m.group(1).splitlines()
    in_paths = False
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        key = _PATHS_KEY_RE.match(stripped)
        if key:
            rest = key.group(1).strip()
            if rest.startswith("["):
                buf = rest
                while "]" not in buf and i + 1 < len(lines):
                    i += 1
                    buf += " " + lines[i].strip()
                inner = buf[1:buf.index("]")] if "]" in buf else buf[1:]
                paths.extend(_split_flow_items(inner))
                in_paths = False
            elif rest:
                paths.append(_unquote(_strip_comment(rest)))
                in_paths = False
            else:
                in_paths = True
            i += 1
            continue
        if in_paths:
            item = _PATH_ITEM_RE.match(line)
            if item:
                paths.append(_unquote(_strip_comment(item.group(1))))
            elif stripped:
                in_paths = False
        i += 1
    paths = _dedupe(paths)
    return ({"paths": paths} if paths else {}), text[m.end():]


def load_specs(root: Path) -> list[dict]:
    """读取全部带 `paths:` 的规范文件（相对路径 + globs + 去 frontmatter 正文）。"""
    root = root.resolve()
    specs: list[dict] = []
    for rel_dir in SPEC_DIRS:
        base = root / rel_dir
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.md")):
            try:
                if p.stat().st_size > MAX_FILE_BYTES:
                    continue
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            meta, body = _split_frontmatter(text)
            if not meta.get("paths"):
                continue
            specs.append({
                "rel": p.relative_to(root).as_posix(),
                "name": p.stem,
                "paths": meta["paths"],
                "body": body.strip(),
            })
    return specs


# ---------------------------------------------------------------- path / glob

def _norm_glob(raw: str) -> str:
    """glob 只做斜杠归一与 `./` 清理；**不做** normpath（会吃掉尾 `/`）。"""
    g = str(raw).strip().replace("\\", "/")
    while g.startswith("./"):
        g = g[2:]
    if g.endswith("/"):
        g += "**"
    return g


def _is_wildcard(glob: str) -> bool:
    return _norm_glob(glob) in _WILDCARDS


@lru_cache(maxsize=512)
def _glob_regex(glob: str) -> re.Pattern[str]:
    """`**` 跨目录、`*` 不跨目录；`a/**` 允许零段；`[!x]` 取反。"""
    g = _norm_glob(glob)
    out: list[str] = []
    i, n = 0, len(g)
    while i < n:
        ch = g[i]
        if ch == "*":
            if i + 1 < n and g[i + 1] == "*":
                if i + 2 < n and g[i + 2] == "/":
                    out.append("(?:.*/)?")
                    i += 3
                elif out and out[-1] == "/":
                    out.pop()
                    out.append("(?:/.*)?")
                    i += 2
                else:
                    out.append(".*")
                    i += 2
            else:
                out.append("[^/]*")
                i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        elif ch == "[":
            j = i + 1
            if j < n and g[j] in ("!", "^"):
                j += 1
            if j < n and g[j] == "]":
                j += 1
            while j < n and g[j] != "]":
                j += 1
            if j >= n:
                out.append(r"\[")
                i += 1
            else:
                content = g[i + 1:j]
                if content.startswith("!"):
                    content = "^" + content[1:]
                out.append("[" + content.replace("\\", r"\\") + "]")
                i = j + 1
        else:
            out.append(re.escape(ch))
            i += 1
    return re.compile("".join(out))


def _scope_path(root: Path, raw: str) -> str:
    """改动路径归一：相对项目根；绝对路径尝试相对化；逃出根 ⇒ 空（不可命中）。"""
    s = str(raw).strip().replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    if not s:
        return ""
    if re.match(r"^[A-Za-z]:/", s) or s.startswith("/"):
        try:
            return Path(s).resolve().relative_to(root.resolve()).as_posix()
        except (ValueError, OSError):
            return ""
    s = posixpath.normpath(s)
    if s in (".", "..") or s.startswith("../"):
        return ""
    return s


def hit_path(path: str, glob: str) -> bool:
    if not path:
        return False
    if _is_wildcard(glob):
        return True
    if _glob_regex(glob).fullmatch(path):
        return True
    # 目录型 scope（无通配符）按前缀命中；目录型 glob 同理由 `a/**` 覆盖
    g = _norm_glob(glob)
    if not any(ch in g for ch in "*?["):
        return path == g.rstrip("/") or path.startswith(g.rstrip("/") + "/")
    return False


def _specificity(spec: dict, scopes: list[str] | None = None) -> int:
    """命中的最长非兜底 glob 越具体，越优先。

    限定只计**实际命中**的 glob：一份通用指南列了很多目录时，不得凭一条更长的
    无关 glob 挤掉真正对口的领域约定。
    """
    concrete = [len(_norm_glob(g)) for g in spec["paths"]
                if not _is_wildcard(g)
                and (scopes is None or any(hit_path(p, g) for p in scopes))]
    return max(concrete, default=0)


def _is_wildcard_only(spec: dict) -> bool:
    return all(_is_wildcard(g) for g in spec["paths"])


def _is_conventions(spec: dict) -> bool:
    return spec["rel"].split("/")[2:3] == ["conventions"]


def _domainhit_path(spec: dict, domains: list[str]) -> bool:
    if not domains:
        return False
    stem = spec["name"].lower()
    for raw in domains:
        d = str(raw).strip().lower()
        if not d:
            continue
        if stem == d or stem.startswith(d + "-") or stem.startswith(d + "_"):
            return True
    return False


def select_specs(root: Path, paths: list[str] | None = None,
                 domains: list[str] | None = None) -> list[dict]:
    """按改动路径 / 受影响域选取最小规范集。

    规则（顺序即优先级）：
      1. 显式改动路径命中 → 只取命中项，**不**混入 `**` 兜底；
         结构规范优先，约定规范至多补 1 份；
      2. 无改动路径但给了域 → 取 `domains/<domain>.md`；
      3. 两者都无 → 只取 `**` 兜底（如 `tour.md`），最多 1 份。
    """
    specs = load_specs(root)
    doms = [d for d in (domains or []) if str(d).strip()]

    if paths is not None:
        scopes = [s for s in (_scope_path(root, p) for p in paths if str(p).strip()) if s]
        if not scopes:
            return []  # 显式范围为空 ⇒ 不回落兜底
        hits = [s for s in specs
                if not _is_wildcard_only(s)
                and any(hit_path(p, g) for p in scopes for g in s["paths"])]
        hits.sort(key=lambda s: (-_specificity(s, scopes), s["rel"]))
        structure = [s for s in hits if not _is_conventions(s)]
        conventions = [s for s in hits if _is_conventions(s)]
        if structure:
            picked = structure[:MAX_SPECS]
            if conventions and len(picked) < MAX_SPECS:
                picked.append(conventions[0])
            return picked
        return conventions[:MAX_SPECS]

    if doms:
        picked = [s for s in specs
                  if not _is_wildcard_only(s) and _domainhit_path(s, doms)]
        picked.sort(key=lambda s: (-_specificity(s), s["rel"]))
        if picked:
            return picked[:MAX_SPECS]

    wild = [s for s in specs if _is_wildcard_only(s)]
    wild.sort(key=lambda s: s["rel"])
    return wild[:1]


# ---------------------------------------------------------------- rendering

def _excerpt(body: str) -> str:
    lines = body.splitlines()
    out = lines[:MAX_LINES_PER_SPEC]
    text = "\n".join(out).strip()
    if len(text) > MAX_CHARS_PER_SPEC:
        text = text[:MAX_CHARS_PER_SPEC].rstrip() + "\n…（已截断，全文请按需 Read）"
    elif len(lines) > MAX_LINES_PER_SPEC:
        text += "\n…（已截断，全文请按需 Read）"
    return text


def _fence(body: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", body)), default=0)
    return "`" * max(3, longest + 1)


def render_specs(specs: list[dict], scope_paths: list[str] | None = None,
                 domains: list[str] | None = None) -> str:
    """渲染派工单的「最小结构上下文」段。"""
    scope = ", ".join(f"`{p}`" for p in (scope_paths or []))
    dom = ", ".join(f"`{d}`" for d in (domains or []))

    lines = ["## 4. 最小结构上下文（按改动路径自动注入）"]
    if scope or dom:
        lines.append(f"> 本次范围：{scope or ''}{(' · 域 ' + dom) if dom else ''}；"
                     "只注入命中规范，未命中的请按需 Read。")
    else:
        lines.append("> 未提供改动路径；仅注入导航兜底规范。要更精准请用 "
                     "`atlas workflow dispatch --paths <file...>`。")
    lines.append("")

    if not specs:
        lines.append("（未匹配到带 `paths:` 的规范；请确认 `.atlas/spec/structure/` 已开户）")
        lines.append("")
        return "\n".join(lines)

    emitted = 0
    for s in specs:
        body = _excerpt(s["body"])
        if not body:
            continue
        fence = _fence(body)
        globs = ", ".join(f"`{g}`" for g in s["paths"])
        lines.append(f"### 命中 {globs} → `{s['rel']}`")
        lines.append("")
        lines.append(f"{fence}md")
        lines.append(body)
        lines.append(fence)
        lines.append("")
        emitted += 1

    if not emitted:
        lines.append("（命中的规范暂无正文）")
        lines.append("")
    return "\n".join(lines)
