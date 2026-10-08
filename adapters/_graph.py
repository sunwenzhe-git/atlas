#!/usr/bin/env python3
"""atlas 图谱后端隔离层 —— **全线唯一接触代码图谱工具的模块**。

设计共识（2026-10-05 批 0 spike 后定形）：

* **薄后端、厚自有**：图谱工具只当「哑索引 + 查询接口」；影响面分层、域聚类等
  聪明逻辑归 atlas 自有脚本。后端哪天要换，只改本文件。
* **用前现刷**：图谱没有独立更新节拍——每个消费者在查询前调 `ensure_index()`，
  先比对新鲜度键（git HEAD + 脏文件集），不一致才重建索引。新鲜度是消费行为
  自带属性，不依赖 hook 或守护进程；过期状态在消费时构造性不存在。
* **接触面只走 CLI**：接口最窄、最不容易随后端小版本变动；不走 Python import，
  不直连图数据库内部 schema。
* **确定性**：本层产出的所有查询都带 `ORDER BY`，同代码态重跑结果一致——这是
  上层可 diff、可对账的前提。

后端 = cgc（CodeGraphContext，MIT；PyPI 包 `codegraphcontext`，可执行名 `cgc`）。
未安装 / 不可达时 `detect()` 返回 None，由调用方决定响亮降级（适配器显式 WARN +
回退正则；报告器显式 not_ready），本层绝不静默。

声明：`product/stack-profile.yaml` 的可选 `graph` 段（契约见 `shared/stack-profile.md` §2）：

    graph:
      backend: cgc       # 枚举见 GRAPH_BACKENDS；缺省整个段 = 不用图谱
      pinned: "0.6.13"   # 可选；与实装版本失配 ⇒ 显式 WARN（不阻断）

本文件不是适配器本体，不会被 `stack-profile.adapters` 解析（同 `_lib.py`）。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ADAPTER = "graph"

# backend 词表（shared/stack-profile.md §2 同源；出厂测试守恒）
GRAPH_BACKENDS = ("cgc",)

# 各子命令超时（秒）。宁可响亮超时，不可无限等待——本机曾把「网络读阻塞」误判为
# 死锁（2026-10-05），超时是这类故障的第一道显式化防线。
VERSION_TIMEOUT = 15
QUERY_TIMEOUT = 120
INDEX_TIMEOUT = 900

INDEX_MARKER = ".adapter-out/_graph_index.json"


def die(msg: str) -> None:
    print(f"ERROR[{ADAPTER}]: {msg}", file=sys.stderr)
    sys.exit(1)


def warn(msg: str) -> None:
    print(f"[{ADAPTER}] WARN: {msg}", file=sys.stderr)


# ---------------------------------------------------------------- profile 声明

def _yaml_scalar(raw: str):
    v = raw.strip()
    if len(v) >= 2 and v[0] in "'\"" and v[-1] == v[0]:
        return v[1:-1]
    if v in ("", "null", "Null", "NULL", "~", "none", "None"):
        return None
    return v


def _strip_inline_comment(line: str) -> str:
    out, quote = [], None
    for i, ch in enumerate(line):
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
            out.append(ch)
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def load_graph_config(root: Path) -> dict | None:
    """读 stack-profile 的 `graph` 段；未声明 / 空段 / 显式 null ⇒ None（不用图谱）。

    graph 段不要求是文件末段：遇下一个顶层段即结束收集，已收集内容保留
    （2026-10-05 实测咬出：早版在段尾重置时把已收集的配置一并丢弃）。"""
    p = Path(root) / "product" / "stack-profile.yaml"
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
                # `graph: null` = 显式不用；其它标量形态也在此收口
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


# ---------------------------------------------------------------- 后端探测

def detect(root: Path | None = None, cfg: dict | None = None) -> dict | None:
    """探测 cgc 可执行与版本；不可用 ⇒ None。cfg.pinned 声明且失配 ⇒ 显式 WARN。"""
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
        warn(f"cgc --version 输出无法解析: {(p.stdout or p.stderr or '').strip()[:120]}")
        return None
    version = m.group(1)
    if cfg and cfg.get("pinned") and str(cfg["pinned"]) != version:
        warn(f"版本失配：profile pin={cfg['pinned']} 实装={version}"
             f"（图谱查询结果可能随版本漂移；建议 pipx/uv 对齐或更新 pin）")
    return {"version": version}


# ---------------------------------------------------------------- 新鲜度与索引

def _git(root: Path, *args: str, timeout: int = 30) -> str:
    p = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True,
                       timeout=timeout)
    if p.returncode != 0:
        die(f"git {' '.join(args)} 失败: {(p.stderr or '').strip()[:200]}")
    return p.stdout


def freshness_key(root: Path) -> str:
    """代码态指纹 = sha1(HEAD + 脏文件集)。脏工作区的未提交改动一并计入——
    索引反映的是磁盘工作树，不是 HEAD 提交。

    `.adapter-out/` 行排除：它是运行时产物目录（stack-profile.md §3.1 定性——
    中间产物、非真相源），且本层自己的新鲜度标记也写在里面；不排除的话
    「写标记 ⇒ 键变化 ⇒ 再索引」自激振荡，新鲜度机制自毁（2026-10-05 实测）。"""
    head = _git(root, "rev-parse", "HEAD").strip() if _has_commits(root) else ""
    dirty = "\n".join(ln for ln in _git(root, "status", "--porcelain").splitlines()
                      if ".adapter-out" not in ln)
    return hashlib.sha1((head + "\n" + dirty).encode("utf-8")).hexdigest()


def _has_commits(root: Path) -> bool:
    p = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=str(root),
                       capture_output=True, text=True)
    return p.returncode == 0


def _marker_path(root: Path) -> Path:
    return Path(root) / INDEX_MARKER


def _read_marker(root: Path) -> dict | None:
    p = _marker_path(root)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def ensure_index(root: Path, cfg: dict | None = None, version: str | None = None) -> dict:
    """用前现刷：新鲜度键一致 ⇒ 直接返回（微秒级）；不一致 ⇒ `cgc index --force`
    全量重建，成功后写新鲜度标记。失败响亮 die，绝不留半新索引装新鲜。

    **为何不用 `cgc update` 增量（B191-2 实测收口，2026-10-07；cgc 0.6.13 + falkordb 后端）**：
    update 的增量语义 = **只加不减** —— 新增符号可追平（提交 / 未提交工作树实测都能入图），
    但**删除不追平**：符号删除并提交后再 update，已删函数仍留在索引里（实测 `gamma` 残留；
    `cgc clean` 只清无关系孤儿节点，追不平有 File/Repository 壳挂着的符号）。残留符号会让
    `callers` / `symbols_in_files` 对已删除代码**静默答错**（幽灵调用方 ⇒ impact 影响面虚高），
    正是 `§B92`「过期索引静默答错」风险本体 ⇒ 判定**不可信，维持 `--force`**
    （确定性优于 ~17s 的全量成本）。

    **切换条件（回退 = 本路径）**：后端版本升级后，在受控仓库复测「新增追平 + 删除追平」
    两例（含未提交与已提交两种态）全部通过，且 `clean` 能追平 Repository/File 壳，
    方可改为 update 增量；任一不过即维持全量。"""
    root = Path(root)
    cfg = cfg or load_graph_config(root) or {}
    if version is None:
        det = detect(root, cfg)
        if det is None:
            die("cgc 不可用（未安装或探测失败）——图谱消费者不得在未探测时查询")
        version = det["version"]
    key = freshness_key(root)
    marker = _read_marker(root)
    if marker and marker.get("key") == key and marker.get("backend_version") == version:
        return {"status": "fresh", "version": version, "key": key}
    p = subprocess.run(["cgc", "index", str(root), "--force", "--no-progress"],
                       capture_output=True, text=True, timeout=INDEX_TIMEOUT,
                       env=_backend_env())
    if p.returncode != 0:
        die(f"cgc index 失败（exit {p.returncode}）: {(p.stderr or p.stdout or '').strip()[-400:]}")
    marker_path = _marker_path(root)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(json.dumps(
        {"key": key, "backend": "cgc", "backend_version": version}, ensure_ascii=False,
        sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "indexed", "version": version, "key": key}


# ---------------------------------------------------------------- 查询

def _cypher_str(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


def _backend_env() -> dict:
    """后端子进程环境。COLUMNS 调大：后端用 rich 渲染输出，默认宽度 ~80 会把
    JSON 长字符串**硬换行**成非法文本（2026-10-05 实测）；调大后单行不再折断。"""
    env = dict(os.environ)
    env["COLUMNS"] = "20000"
    return env


def _abs(root: Path, rel: str) -> str:
    return str((Path(root) / rel).resolve())


def _rel(root: Path, path: str) -> str | None:
    """后端节点路径（绝对）→ 项目根相对 posix；根外路径（全局库含多仓库）⇒ None。"""
    p = Path(path)
    if not p.is_absolute():
        return Path(path).as_posix()
    try:
        return p.resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return None


def _root_prefix(root: Path) -> str:
    return _cypher_str(str(Path(root).resolve()) + "/")


def query(root: Path, cypher: str, cfg: dict | None = None) -> list | dict:
    """执行只读 Cypher，返回解析后的 JSON（通常为行数组）。

    后端 CLI 输出含启动横幅，从首个行首 `[`/`{` 起做 JSON 解码；后端报错对象
    （`{"error": ...}`）响亮 die。调用方负责在 Cypher 里写 ORDER BY（确定性纪律）。
    """
    try:
        p = subprocess.run(["cgc", "query", cypher], cwd=str(root), capture_output=True,
                           text=True, timeout=QUERY_TIMEOUT, env=_backend_env())
    except subprocess.TimeoutExpired as e:
        die(f"cgc query 超时（>{QUERY_TIMEOUT}s）——先怀疑网络/后端卡死，而非数据规模: {cypher[:120]}")
    if p.returncode != 0:
        die(f"cgc query 失败（exit {p.returncode}）: {(p.stderr or p.stdout or '').strip()[-400:]}")
    out = p.stdout or ""
    idx, start = len(out), -1
    for ch in ("[", "{"):
        i = out.find(ch)
        if 0 <= i < idx:
            idx, start = i, i
    if start < 0:
        die(f"cgc query 输出中没有 JSON: {out.strip()[-200:]}")
    try:
        obj, _ = json.JSONDecoder().raw_decode(out[start:])
    except json.JSONDecodeError as e:
        die(f"cgc query 输出 JSON 解析失败（{e}）: {out[start:start + 200]}")
    if isinstance(obj, dict) and obj.get("error"):
        die(f"后端查询错误: {obj['error']}")
    return obj


def file_paths(root: Path, prefix: str | None = None, cfg: dict | None = None) -> list[str]:
    """索引内 File 节点路径（**项目根相对** posix），字典序。prefix 传 app path 时只取该 app。

    后端全局库可能同时索引多个仓库：查询按项目根绝对路径前缀过滤，根外节点丢弃。"""
    rows = query(root,
                 f"MATCH (f:File) WHERE f.path STARTS WITH '{_root_prefix(root)}' "
                 "RETURN f.path AS path ORDER BY path", cfg)
    out: set[str] = set()
    for r in rows:
        if not isinstance(r, dict) or not r.get("path"):
            continue
        rel = _rel(root, r["path"])
        if rel is None:
            continue
        if prefix and not (rel == prefix.rstrip("/") or rel.startswith(prefix.rstrip("/") + "/")):
            continue
        out.add(rel)
    return sorted(out)


def symbols_in_files(root: Path, paths: list[str], cfg: dict | None = None) -> list[dict]:
    """给定文件内定义的函数 / 方法节点：[{name, path（根相对）}]，按 (path, name) 序。"""
    if not paths:
        return []
    lst = "[" + ", ".join(f"'{_cypher_str(_abs(root, p))}'" for p in sorted(set(paths))) + "]"
    rows = query(root,
                 f"MATCH (n) WHERE (n:Function OR n:Method) AND n.path IN {lst} "
                 "RETURN DISTINCT n.name AS name, n.path AS path ORDER BY path, name", cfg)
    out: set[tuple[str, str]] = set()
    for r in rows:
        if not isinstance(r, dict) or not r.get("name"):
            continue
        rel = _rel(root, r.get("path") or "")
        if rel is None:
            continue
        out.add((r["name"], rel))
    return [{"name": n, "path": p} for n, p in sorted(out)]


def callers(root: Path, symbol: str, cfg: dict | None = None) -> list[dict]:
    """直接调用方（一跳）：[{name, path（根相对）}]，按 (path, name) 序。

    **name 级匹配**：同名多定义会并入（影响面偏宽、保守）——这是 tree-sitter 级
    图谱的已知口径，契约见 shared/stack-profile.md §3.6；收口对账时以实际 diff 为准。
    调用方按项目根过滤——全局库同时索引多个仓库时不得跨仓污染。
    """
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
    out.sort(key=lambda c: (c["path"], c["name"]))  # 确定性在代码侧兜底，不只信后端 ORDER BY
    return out
