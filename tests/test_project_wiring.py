#!/usr/bin/env python3
"""atlas 项目接线的回归测试。

守护「install.sh 把 AGENTS.md 指针 / 测试配置 / .gitignore / pi 扩展幂等写进目标项目」：
  * AGENTS.md：追加到 EOF（不破坏用户既有内容）；重跑幂等；缺文件创建；区块更新；标记不成对报错且不改。
  * dry-run 不写。

两种运行方式：
    python3 tests/test_project_wiring.py      # 脚本式
    pytest tests/test_project_wiring.py        # pytest 式
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
PKG = PKG_ROOT / "patches" / "project-wiring"
APPLIER = PKG / "apply-wiring.py"
SNIPPET = PKG / "agent-pointer.md"

A_START = "<!-- ATLAS:START -->"
A_END = "<!-- ATLAS:END -->"

AGENTS_FIXTURE = """# 用户既有说明

不要覆盖我。
"""


def run(target: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(APPLIER), "--target", str(target), *extra],
        capture_output=True, text=True,
    )


def write(tmp: Path, rel: str, content: str) -> Path:
    p = tmp / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def test_snippet_exists() -> None:
    assert SNIPPET.is_file(), "缺少 agent-pointer.md"
    body = SNIPPET.read_text(encoding="utf-8")
    assert "atlas workflow plan" in body
    assert "stack-profile.yaml" in body
    # §15 自感知上报的出口必须在指针段里 —— 它是该契约在真实项目里**唯一的常在交付面**
    # （只写在 `.atlas/shared/global-rules.md` 里时，流程中段等不到提醒）。
    assert "atlas report" in body and "§15" in body, "指针段缺 §15 上报出口"


def test_agents_appends_at_eof_and_idempotent() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        f = write(tmp, "AGENTS.md", AGENTS_FIXTURE)

        r1 = run(tmp, "--apply")
        assert r1.returncode == 0, r1.stdout + r1.stderr
        text = f.read_text(encoding="utf-8")
        assert A_START in text and A_END in text
        # 用户内容原样保留，指针段在其后
        assert text.index("不要覆盖我") < text.index(A_START)
        assert "atlas workflow plan" in text

        before = f.read_text(encoding="utf-8")
        r2 = run(tmp, "--apply")
        assert r2.returncode == 0, r2.stdout
        assert f.read_text(encoding="utf-8") == before, "重跑应字节不变"


def test_agents_missing_file_creates() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        r = run(tmp, "--apply")
        assert r.returncode == 0, r.stdout
        f = tmp / "AGENTS.md"
        assert f.is_file()
        assert A_START in f.read_text(encoding="utf-8")


def test_agents_updates_existing_block() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        stale = f"{A_START}\n旧内容\n{A_END}\n"
        f = write(tmp, "AGENTS.md", "# 头\n\n" + stale)
        r = run(tmp, "--apply")
        assert r.returncode == 0, r.stdout
        text = f.read_text(encoding="utf-8")
        assert text.count(A_START) == 1
        assert "旧内容" not in text
        assert "atlas workflow plan" in text


def test_agents_unbalanced_markers_error_without_writing() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        f = write(tmp, "AGENTS.md", f"# 头\n{A_START}\n半截\n")
        before = f.read_bytes()
        r = run(tmp, "--apply")
        assert r.returncode == 1
        assert "标记不成对" in r.stdout + r.stderr
        assert f.read_bytes() == before


def test_dry_run_does_not_write() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        r = run(tmp)
        assert r.returncode == 0, r.stdout
        assert "applied=1" in r.stdout
        assert not (tmp / "AGENTS.md").exists(), "dry-run 不得写盘"


def test_gitignore_fourth_touchpoint_appends_idempotently() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        f = write(tmp, ".gitignore", "node_modules/\n")
        r = run(tmp, "--apply")
        assert r.returncode == 0, r.stdout
        text = f.read_text(encoding="utf-8")
        assert text.count(".adapter-out/") == 1
        assert text.count(".atlas/*") == 1
        assert "!.atlas/tasks/" in text and "!.atlas/spec/" in text
        run(tmp, "--apply")
        assert f.read_text(encoding="utf-8") == text


def test_gitignore_absent_is_not_created() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        r = run(tmp, "--apply")
        assert r.returncode == 0, r.stdout
        assert not (tmp / ".gitignore").exists()
        assert "不首创" in r.stdout


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
