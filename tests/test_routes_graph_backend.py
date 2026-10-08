#!/usr/bin/env python3
"""`adapters/routes.py` 双通道文件枚举的「喂坏输入必红」判据（2026-10-05 图谱批 1）。

为什么要它：graph 通道与 regex 通道必须对同一代码态产出**逐字节同构**的 items
（同一派生逻辑、同一排序）——两通道漂移 = 事实源分叉，同族 `3509 §B92`（索引静默脱节）。
降级必须显式（stderr WARN + `backend_fallback` 字段），静默改道 = 门失效。

五侧（1–4 经 fake `cgc`；5 需真后端，`ATLAS_REAL_GRAPH=1` 门控）：
  1. 两通道 items 全等；
  2. auto 解析：profile 声明 graph ⇒ graph；
  3. 声明了 graph 但 cgc 缺失 ⇒ 响亮降级（exit 0 + WARN + backend_fallback）；
  4. 显式 --backend graph 而 cgc 缺失 ⇒ 硬错 exit 1（显式要求不得被静默改道）；
  5. 真后端：cgc index 夹具后 graph 通道与 regex 通道全等 + 双跑字节一致。
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
ADAPTER = PKG_ROOT / "adapters" / "routes.py"

PROFILE = """product: 夹具
apps:
  - name: frontend
    path: frontend
    kind: frontend
    role: landing
    stack: 夹具
graph:
  backend: cgc
"""

FILES = {
    "frontend/src/routes/__root.tsx": "// 根：不成路由\n",
    "frontend/src/routes/_layout.tsx": "// 路径无关布局\n",
    "frontend/src/routes/index.tsx": "// 首页\n",
    "frontend/src/routes/login.tsx": "// 登录\n",
    "frontend/src/routes/_layout/config.tsx": "// 配置\n",
    "frontend/src/routes/_layout/projects.$id.tsx": "// 项目详情\n",
    "frontend/src/routeTree.gen.ts": "// 生成物，必须跳过\n",
}

FAKE_CGC = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
if args[:1] == ["--version"]:
    print("CodeGraphContext 0.9.9")
    sys.exit(0)
if args[:1] == ["index"]:
    sys.exit(0)
if args[:1] == ["query"]:
    files = json.loads(os.environ["FAKE_CGC_FILES"])
    print("Services initialized.")
    print(json.dumps([{"path": p} for p in files], ensure_ascii=False))
    sys.exit(0)
sys.exit(2)
'''


def mk(root: Path, with_graph: bool = True) -> None:
    (root / "product").mkdir(parents=True, exist_ok=True)
    (root / "product" / "stack-profile.yaml").write_text(
        PROFILE if with_graph else PROFILE.replace("graph:\n  backend: cgc\n", ""),
        encoding="utf-8")
    for rel, body in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "init"], check=True)


def fake_cgc_into(tmp_path: Path) -> str:
    """装 fake cgc，返回它所在的 PATH 前缀（调用方拼进子进程 env，防止摸到真 cgc）。"""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    exe = bin_dir / "cgc"
    exe.write_text(FAKE_CGC, encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    os.environ["FAKE_CGC_FILES"] = json.dumps(sorted(FILES))
    return str(bin_dir)


def run(root: Path, *extra: str, env: dict | None = None) -> tuple[dict, subprocess.CompletedProcess]:
    out = root / "out.json"
    p = subprocess.run([sys.executable, str(ADAPTER), "--root", str(root),
                        "--out", str(out), *extra],
                       capture_output=True, text=True, timeout=180, env=env)
    data = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    return data, p


def test_graph_channel_matches_regex_channel(tmp_path) -> None:
    """通道全等：同一夹具，graph（fake 后端）与 regex 产出 items 逐项一致。"""
    bin_dir = fake_cgc_into(tmp_path)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root)
        env = dict(os.environ, PATH=bin_dir + os.pathsep + os.environ.get("PATH", ""))
        regex_out, p1 = run(root, "--backend", "regex", env=env)
        assert p1.returncode == 0, p1.stderr
        graph_out, p2 = run(root, "--backend", "graph", env=env)
        assert p2.returncode == 0, p2.stderr
        assert graph_out["backend"] == "graph"
        assert graph_out["items"] == regex_out["items"], (
            "两通道 items 漂移（事实源分叉）:\n"
            f"graph={json.dumps(graph_out['items'], ensure_ascii=False)}\n"
            f"regex={json.dumps(regex_out['items'], ensure_ascii=False)}")


def test_auto_resolves_graph_when_declared(tmp_path) -> None:
    bin_dir = fake_cgc_into(tmp_path)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root)
        env = dict(os.environ, PATH=bin_dir + os.pathsep + os.environ.get("PATH", ""))
        out, p = run(root, env=env)
        assert p.returncode == 0, p.stderr
        assert out["backend"] == "graph"


def test_missing_backend_falls_back_loudly(tmp_path) -> None:
    """声明了 graph 但 cgc 缺失 ⇒ 响亮降级：exit 0 + stderr WARN + backend_fallback 字段。"""
    with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as emptybin:
        root = Path(td)
        mk(root)
        env = dict(os.environ, PATH=emptybin)  # 无 cgc
        out, p = run(root, env=env)
        assert p.returncode == 0, p.stderr
        assert "WARN" in p.stderr and "降级" in p.stderr, p.stderr
        assert out["backend"] == "regex" and out.get("backend_fallback")
        assert out["items"]  # 降级不是空产出：regex 通道照常出事实


def test_explicit_graph_without_backend_fails(tmp_path) -> None:
    with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as emptybin:
        root = Path(td)
        mk(root)
        env = dict(os.environ, PATH=emptybin)
        out, p = run(root, "--backend", "graph", env=env)
        assert p.returncode == 1, (p.stdout, p.stderr)
        assert "显式" in p.stderr


def test_real_backend_crosscheck_and_determinism(tmp_path) -> None:
    """真后端门控（ATLAS_REAL_GRAPH=1）：cgc 索引夹具 → 两通道全等 + 双跑字节一致。"""
    if os.environ.get("ATLAS_REAL_GRAPH") != "1":
        pytest_skip = __import__("pytest")
        pytest_skip.skip("需要真后端：ATLAS_REAL_GRAPH=1（并要求 cgc 已安装）")
    if shutil.which("cgc") is None:
        __import__("pytest").skip("cgc 未安装")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root)  # mk() 已建 git 仓库并提交（代码态指纹需要 HEAD）
        regex_out, _ = run(root, "--backend", "regex")
        graph_out, p = run(root, "--backend", "graph")
        assert p.returncode == 0, p.stderr
        assert graph_out["items"] == regex_out["items"]
        # 双跑字节一致（确定性契约：对账门的存在前提）
        out_a = root / "a.json"
        out_b = root / "b.json"
        for o in (out_a, out_b):
            subprocess.run([sys.executable, str(ADAPTER), "--root", str(root),
                            "--out", str(o), "--backend", "graph"],
                           capture_output=True, text=True, timeout=300, check=True)
        assert out_a.read_bytes() == out_b.read_bytes()
