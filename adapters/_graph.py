#!/usr/bin/env python3
"""atlas 图谱后端隔离层 —— 已退役外部 AST 图谱，收敛为轻量语义透镜（Scope-Aware FRAS）辅助层。

设计定案（RFC-20261119-01 / D202，2026-11-19）：
* **外部 AST 图谱（cgc / FalkorDB）正式退役**：实测证明前端 JSX 组件无边、现代 Java 后端
  （Spring DI / MyBatis / 线程池异步 / HTTP）四重截断，沉重外部图数据库已彻底移除。
* **单源与两级轻量透镜**：支持读取项目内的全局（`.trellis/spec/structure/global/cognition.fras`）
  与业务域（`.trellis/spec/structure/current/<domain>/cognition.fras`）轻量语义行，
  提供反向 1-hop 单跳引用查询，赋能执行层与影响面推导。
* **落点保持**：项目根 `.adapter-out/` 仍是单一位点标记，保持与结构环产物一致。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _support.layout import load_layout  # noqa: E402

ADAPTER = "graph"

# 历史 backend 词表（已退役；保留常量防外部加载断裂）
GRAPH_BACKENDS = ("cgc",)

# 单一位点标记（tests/test_refresh_facts.py:47 依赖）
INDEX_MARKER = ".adapter-out/_graph_index.json"

VERSION_TIMEOUT = 5
INDEX_TIMEOUT = 120
QUERY_TIMEOUT = 30


def die(msg: str) -> None:
    print(f"ERROR[{ADAPTER}]: {msg}", file=sys.stderr)
    sys.exit(1)


def warn(msg: str) -> None:
    print(f"WARN[{ADAPTER}]: {msg}", file=sys.stderr)


# ---------------------------------------------------------------- stack-profile.yaml graph 段解析

def _strip_inline_comment(line: str) -> str:
    in_single = in_double = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            return line[:i].rstrip()
    return line


def _yaml_scalar(raw: str):
    s = raw.strip()
    if not s or s == "null" or s == "~":
        return None
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def load_graph_config(root: Path) -> dict | None:
    """读 stack-profile 的 `graph` 段；未声明 / 空段 / 显式 null ⇒ None。"""
    p = load_layout(root).stack_profile
    if not p.is_file():
        return None
    found: dict | None = None
    in_graph = False
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = _strip_inline_comment(raw.rstrip())
        s = line.strip()
        if not s:
            continue
        if not line[:1].isspace():
            in_graph = s == "graph:"
            if s.startswith("graph:") and not in_graph:
                scalar = _yaml_scalar(s[len("graph:"):])
                if scalar is not None:
                    die(f"graph 段形态非法（应为映射或 null）: {s.strip()}")
            continue
        if in_graph:
            m = re.match(r"^\s+([\w.-]+):\s*(.*?)\s*$", line)
            if m:
                if found is None:
                    found = {}
                found[m.group(1)] = _yaml_scalar(m.group(2))
    if not found:
        return None
    backend = found.get("backend")
    if backend not in GRAPH_BACKENDS:
        die(f"graph.backend 非法: {backend!r}（允许={list(GRAPH_BACKENDS)}；见 shared/stack-profile.md §2）")
    return found


# ---------------------------------------------------------------- 兼容探测与退役状态

def _backend_env() -> dict:
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    return env


def detect(root: Path | None = None, cfg: dict | None = None) -> dict | None:
    """探测 cgc 可执行与版本；若已退役且未安装则返回 None。"""
    exe = shutil.which("cgc")
    if exe is None:
        return None
    try:
        p = subprocess.run(["cgc", "--version"], capture_output=True, text=True,
                           timeout=VERSION_TIMEOUT, env=_backend_env())
    except (subprocess.TimeoutExpired, OSError) as e:
        warn(f"cgc --version 探测失败（{e}）")
        return None
    m = re.search(r"(\d+\.\d+\.\d+\S*)", (p.stdout or "") + "\n" + (p.stderr or ""))
    if not m:
        warn("cgc --version 未输出可识别的版本串")
        return None
    version = m.group(1)
    if cfg and cfg.get("pinned"):
        pinned = str(cfg["pinned"]).strip()
        if pinned and version != pinned:
            warn(f"版本失配：cgc 实装版本（{version}）与 stack-profile 声明的 pinned 版本（{pinned}）失配")
    return {"backend": "cgc", "version": version, "executable": exe}


def _is_git_worktree(root: Path) -> bool:
    try:
        p = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                           cwd=str(root), capture_output=True, text=True)
        return p.returncode == 0 and p.stdout.strip() == "true"
    except OSError:
        return False


def _git(root: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True)
    if p.returncode != 0:
        die(f"git {' '.join(args)} 失败: {(p.stderr or '').strip()}")
    return p.stdout


def freshness_key(root: Path) -> str:
    if not _is_git_worktree(root):
        warn("非 git 工作树：无法计算代码态指纹 ⇒ 每次消费都全量重建索引")
        return ""
    try:
        head = _git(root, "rev-parse", "HEAD").strip()
    except Exception:
        head = ""
    dirty = "\n".join(ln for ln in _git(root, "status", "--porcelain").splitlines() if ln.strip())
    raw = f"{head}\n{dirty}".encode("utf-8")
    import hashlib
    return hashlib.sha256(raw).hexdigest()


def ensure_index(root: Path, cfg: dict | None = None, version: str | None = None) -> dict:
    """用前现刷：若 cgc 在 PATH 且有 fake/真实环境，执行索引并更新 marker。"""
    root = Path(root)
    marker_path = root / INDEX_MARKER
    key = freshness_key(root)
    if marker_path.is_file():
        try:
            m = json.loads(marker_path.read_text(encoding="utf-8"))
            if m.get("backend") == "cgc" and m.get("freshness_key") == key and key:
                return {"status": "fresh", "backend": "cgc", "version": version or m.get("version", "")}
        except Exception:
            pass

    marker_path.parent.mkdir(parents=True, exist_ok=True)
    exe = shutil.which("cgc")
    if exe:
        p = subprocess.run(["cgc", "index"], cwd=str(root), capture_output=True, text=True,
                           timeout=INDEX_TIMEOUT, env=_backend_env())
        if p.returncode != 0:
            die(f"cgc index 失败（code={p.returncode}）: {(p.stderr or p.stdout).strip()}")

    payload = {
        "backend": "cgc",
        "backend_version": version or "0.0.0",
        "freshness_key": key,
    }
    marker_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"status": "indexed", "backend": "cgc", "version": payload["backend_version"]}


def _cypher_str(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


def _root_prefix(root: Path) -> str:
    return str(Path(root).resolve())


def _rel(root: Path, path: str) -> str | None:
    p = Path(path)
    if not p.is_absolute():
        return Path(path).as_posix()
    try:
        return p.resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return None


def query(root: Path, cypher_statement: str, cfg: dict | None = None) -> list[dict]:
    p = subprocess.run(["cgc", "query", cypher_statement], cwd=str(root),
                       capture_output=True, text=True, timeout=QUERY_TIMEOUT, env=_backend_env())
    if p.returncode != 0:
        die(f"cgc query 失败（code={p.returncode}）: {(p.stderr or p.stdout).strip()}")
    stdout = p.stdout or ""
    lines = stdout.splitlines()
    start_idx = -1
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("[") or s.startswith("{"):
            start_idx = i
            break
    if start_idx == -1:
        die(f"cgc query 输出没有 JSON: {stdout.strip()[:200]}")
    json_text = "\n".join(lines[start_idx:])
    try:
        data = json.loads(json_text)
    except Exception as e:
        die(f"cgc query JSON 解析失败（{e}）: {json_text.strip()[:200]}")
    if isinstance(data, dict) and data.get("error"):
        die(f"后端查询错误: {data['error']}")
    if isinstance(data, list):
        return data
    return [data]


def callers(root: Path, symbol: str, cfg: dict | None = None) -> list[dict]:
    """直接调用方（一跳）：若有 cgc 走查询，无 cgc 走轻量 FRAS。"""
    if shutil.which("cgc"):
        rows = query(root,
                     f"MATCH (c)-[:CALLS]->(t {{name: '{_cypher_str(symbol)}'}}) "
                     f"WHERE c.path STARTS WITH '{_root_prefix(root)}' "
                     "RETURN DISTINCT c.name AS name, c.path AS path", cfg)
        out, seen = [], set()
        for r in rows:
            if not isinstance(r, dict) or not r.get("name"):
                continue
            rel = _rel(root, r.get("path") or "")
            if rel is None:
                continue
            k = (r["name"], rel)
            if k in seen:
                continue
            seen.add(k)
            out.append({"name": r["name"], "path": rel})
        out.sort(key=lambda c: (c["path"], c["name"]))
        return out
    hop1 = reverse_1hop_callers(root, [symbol])
    return [{"name": p, "path": p} for p in hop1]


# ---------------------------------------------------------------- 轻量语义透镜 (FRAS) 辅助解析

def read_cognition_fras(path: Path) -> list[dict]:
    """解析单个 cognition.fras 或 aoci.code.txt 文件中的 FRAS 紧凑条目。"""
    entries = []
    p = Path(path)
    if not p.is_file():
        return entries
    content = p.read_text(encoding="utf-8", errors="replace")
    line_re = re.compile(r"^(\S+)\[([A-Z0-9\-]+)\]:\s*F:(.*?)(?:\s*\|\s*R:(.*?))?(?:\s*\|\s*A:(.*?))?(?:\s*\|\s*S:(.*?))?$")
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = line_re.match(line)
        if not m:
            continue
        rel_path, tag, f_desc, r_deps, a_exp, s_const = m.groups()
        deps = []
        if r_deps:
            for item in r_deps.split(","):
                item = item.strip()
                if item.startswith("code:"):
                    deps.append(item[5:])
                elif item and item != "-":
                    deps.append(item)
        entries.append({
            "path": rel_path,
            "tag": tag,
            "f": (f_desc or "").strip(),
            "r": deps,
            "a": (a_exp or "").strip(),
            "s": (s_const or "").strip(),
        })
    return entries


def reverse_1hop_callers(root: Path, target_paths: list[str]) -> list[str]:
    """反向 1-hop 单跳查询：寻找哪些文件的 R 边指向了 target_paths。"""
    root = Path(root)
    normalized_targets = {p.replace("\\", "/").lstrip("./") for p in target_paths if p}
    callers = set()

    candidate_files = []
    structure_root = root / ".trellis" / "spec" / "structure"
    if structure_root.is_dir():
        for fras_file in structure_root.glob("**/cognition.fras"):
            candidate_files.append(fras_file)
    aoci_txt = root / "aoci.code.txt"
    if aoci_txt.is_file():
        candidate_files.append(aoci_txt)

    for cfile in candidate_files:
        for entry in read_cognition_fras(cfile):
            src_path = entry["path"].replace("\\", "/").lstrip("./")
            deps = {d.replace("\\", "/").lstrip("./") for d in entry["r"]}
            if deps.intersection(normalized_targets):
                callers.add(src_path)

    return sorted(callers)


def symbols_in_files(root: Path, touched: list[str], cfg: dict | None = None) -> list[dict]:
    return [{"name": p.replace("\\", "/"), "path": p.replace("\\", "/")} for p in touched]


def file_paths(root: Path, prefix: str = "", cfg: dict | None = None) -> list[str]:
    return []
