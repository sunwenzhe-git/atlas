#!/usr/bin/env python3
"""`scripts/impact_report.py`（影响面基准）的「喂坏输入必红」判据（2026-10-05 图谱批 1）。

为什么要它：批 2 的 impact 对账门以本报告的 predicted 集为预测侧——报告分层错 /
不可复现 / 三态失守，对账门就全是噪音。四侧（经 fake `cgc`，不依赖真后端）：
  1. 分层 BFS 正确（L1 直接 / L2 间接 / 深度封顶 + 同名排除 + 文件集映射）；
  2. 确定性：同代码态双跑 impact.json 字节一致（无时间戳）；
  3. 三态：未声明 graph 段 / cgc 缺失 ⇒ exit 3 + `not_ready`（显式可见跳过）；
  4. 用法错：零输入 ⇒ exit 1（响亮，不得产出空基准装样子）。

变异：摘掉分层去重的 excluded 集 ⇒ 第 1 侧红（种子同名回环重复入层）；
往 payload 里加 generated_at ⇒ 第 2 侧红。
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PKG_ROOT / "scripts" / "impact_report.py"

PROFILE = """product: 夹具
graph:
  backend: cgc
"""

# 调用图（name 级）：
#   send_email ← recover_password(login.py), create_user(users.py)
#   recover_password ← login_page(login.tsx)
#   create_user ← admin_seed(admin.py), send_email（自引用环，必须被同名排除拦住）
CALLERS = {
    "send_email": [
        {"name": "recover_password", "path": "backend/app/api/routes/login.py"},
        {"name": "create_user", "path": "backend/app/api/routes/users.py"},
    ],
    "recover_password": [{"name": "login_page", "path": "frontend/src/login.tsx"}],
    "create_user": [
        {"name": "admin_seed", "path": "backend/app/seed.py"},
        {"name": "send_email", "path": "backend/app/api/routes/login.py"},
    ],
}

FAKE_CGC = r'''#!/usr/bin/env python3
import json, os, re, sys
args = sys.argv[1:]
if args[:1] == ["--version"]:
    print("CodeGraphContext 0.9.9")
    sys.exit(0)
if args[:1] == ["index"]:
    sys.exit(0)
if args[:1] == ["query"]:
    q = args[1]
    table = json.loads(os.environ["FAKE_CGC_CALLERS"])
    m = re.search(r"t \{name: '([^']+)'\}", q)
    rows = table.get(m.group(1), []) if m else []
    print("Services initialized.")
    print(json.dumps(rows, ensure_ascii=False))
    sys.exit(0)
sys.exit(2)
'''


def mk(root: Path) -> None:
    (root / "product").mkdir(parents=True, exist_ok=True)
    (root / "product" / "stack-profile.yaml").write_text(PROFILE, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], check=True)
    (root / "backend" / "app").mkdir(parents=True, exist_ok=True)
    (root / "backend" / "app" / "utils.py").write_text("def send_email():\n    pass\n",
                                                       encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "init"], check=True)


def fake_cgc(tmp_path: Path) -> str:
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    exe = bin_dir / "cgc"
    exe.write_text(FAKE_CGC, encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    os.environ["FAKE_CGC_CALLERS"] = json.dumps(CALLERS)
    return str(bin_dir)


def run(root: Path, bin_dir: str, *extra: str, no_cgc: bool = False
        ) -> tuple[subprocess.CompletedProcess, Path | None]:
    out_dir = root / ".report-out"
    if no_cgc:
        empty = root / "emptybin"  # 真·无 cgc 的 PATH（不能传空串——会继承真 PATH 摸到真后端）
        empty.mkdir(exist_ok=True)
        path_env = str(empty)
    else:
        path_env = bin_dir + os.pathsep + os.environ.get("PATH", "")
    p = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), "--out", str(out_dir), *extra],
        capture_output=True, text=True, timeout=120, env=dict(os.environ, PATH=path_env))
    j = out_dir / "impact.json"
    return p, (j if j.exists() else None)


def test_layering_files_and_determinism(tmp_path) -> None:
    """分层正确 + 种子同名回环被排除 + 双跑字节一致（确定性 = 批 2 对账门的前提）。"""
    bin_dir = fake_cgc(tmp_path)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root)
        p, j = run(root, bin_dir, "--symbols", "send_email")
        assert p.returncode == 0, p.stderr
        payload = json.loads(j.read_text(encoding="utf-8"))
        names = [[s["name"] for s in l["symbols"]] for l in payload["layers"]]
        assert names[0] == ["create_user", "recover_password"], names  # L1 按 (path,name) 序
        assert names[1] == ["admin_seed", "login_page"], names          # L2；send_email 环被拦
        assert len(names) == 2, names                                   # L3 空 → 提前收束
        assert payload["layers"][0]["files"] == [
            "backend/app/api/routes/login.py", "backend/app/api/routes/users.py"]
        assert payload["head"] and payload["backend"].startswith("cgc@")
        assert "generated_at" not in json.dumps(payload)  # 无时间戳：可复现

        # 双跑字节一致
        p2, j2 = run(root, bin_dir, "--symbols", "send_email")
        assert p2.returncode == 0, p2.stderr
        assert j.read_bytes() == j2.read_bytes()


def test_not_ready_when_graph_section_absent(tmp_path) -> None:
    bin_dir = fake_cgc(tmp_path)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "product").mkdir(parents=True)
        (root / "product" / "stack-profile.yaml").write_text("product: 夹具\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        p, j = run(root, bin_dir, "--symbols", "x")
        assert p.returncode == 3, (p.stdout, p.stderr)
        assert json.loads(p.stdout)["status"] == "not_ready"
        assert j is None  # 未就绪不得产出半成品


def test_not_ready_when_backend_missing(tmp_path) -> None:
    bin_dir = fake_cgc(tmp_path)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root)
        p, j = run(root, bin_dir, "--symbols", "x", no_cgc=True)
        assert p.returncode == 3, (p.stdout, p.stderr)
        assert json.loads(p.stdout)["status"] == "not_ready"
        assert j is None


def test_usage_error_when_no_inputs(tmp_path) -> None:
    bin_dir = fake_cgc(tmp_path)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root)
        p, j = run(root, bin_dir)
        assert p.returncode == 1, (p.stdout, p.stderr)
        assert j is None
