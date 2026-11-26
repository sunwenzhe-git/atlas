#!/usr/bin/env python3
"""atlas 项目接线的回归测试。

守护「install.sh 把 AGENTS.md 指针 / 测试配置 / .gitignore / pi 扩展幂等写进目标项目」：
  * AGENTS.md：置顶注入（RFC-20261126-02：BOM / front-matter 之后；宿主窗口截尾部，
    EOF 注入会被整段截掉——issue #77）；存量尾部块迁移到头部（内容逐字节不变仅位置）；
    重跑幂等；缺文件创建；区块更新；标记不成对或多对（≠1）报错且不改。
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


def test_agents_injects_at_head_and_idempotent() -> None:
    """RFC-20261126-02：置顶注入（块在用户内容之前，防宿主窗口截尾）；重跑幂等。"""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        f = write(tmp, "AGENTS.md", AGENTS_FIXTURE)

        r1 = run(tmp, "--apply")
        assert r1.returncode == 0, r1.stdout + r1.stderr
        text = f.read_text(encoding="utf-8")
        assert A_START in text and A_END in text
        # 块置顶：用户内容原样保留且在指针段之后
        assert text.index(A_START) < text.index("不要覆盖我")
        assert "atlas workflow plan" in text

        before = f.read_text(encoding="utf-8")
        r2 = run(tmp, "--apply")
        assert r2.returncode == 0, r2.stdout
        assert f.read_text(encoding="utf-8") == before, "重跑应字节不变"


def test_agents_relocates_legacy_eof_block_to_head() -> None:
    """RFC-20261126-02：存量 EOF 块迁移到头部（内容逐字节不变，仅位置）。"""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        f = write(tmp, "AGENTS.md", AGENTS_FIXTURE)
        run(tmp, "--apply")  # 先造一个置顶块
        good_block = f.read_text(encoding="utf-8")
        block = good_block[good_block.index(A_START):good_block.index(A_END) + len(A_END) + 1]
        # 手工摆成「旧世界」形态：用户内容 + 块在 EOF
        legacy = "# 用户既有说明\n\n不要覆盖我。\n\n" + block
        f.write_text(legacy, encoding="utf-8")

        r = run(tmp, "--apply")
        assert r.returncode == 0, r.stdout + r.stderr
        text = f.read_text(encoding="utf-8")
        assert text.index(A_START) < text.index("不要覆盖我"), "块应迁移到头部"
        assert text.count(A_START) == 1 and text.count(A_END) == 1
        assert "不要覆盖我" in text
        # 迁移后再跑幂等
        before = f.read_text(encoding="utf-8")
        run(tmp, "--apply")
        assert f.read_text(encoding="utf-8") == before


def test_agents_respects_yaml_front_matter_and_bom() -> None:
    """RFC-20261126-02 评审 M2/M3：front-matter 必须留在字节序列头，BOM 保持在物理头。"""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        fm = "---\ntitle: 宿主文档\n---\n\n# 正文\n"
        f = write(tmp, "AGENTS.md", fm)
        r = run(tmp, "--apply")
        assert r.returncode == 0, r.stdout + r.stderr
        text = f.read_text(encoding="utf-8")
        assert text.startswith("---\n"), "front-matter 必须仍是文件首行"
        assert text.index(A_START) > text.index("title: 宿主文档"), "块应在 front-matter 之后"
        assert text.index(A_START) < text.index("# 正文")

        # BOM：保持在物理文件头，块在 BOM 之后
        with tempfile.TemporaryDirectory() as td2:
            tmp2 = Path(td2)
            f2 = tmp2 / "AGENTS.md"
            f2.write_text("\ufeff# BOM 文档\n", encoding="utf-8")
            r2 = run(tmp2, "--apply")
            assert r2.returncode == 0, r2.stdout + r2.stderr
            raw = f2.read_bytes()
            assert raw.startswith(b"\xef\xbb\xbf"), "BOM 必须保持在物理文件头"
            text2 = f2.read_text(encoding="utf-8")
            assert text2.index(A_START) < text2.index("# BOM 文档")


def test_agents_crlf_end_line_swallowed() -> None:
    """RFC-20261126-02 评审 M3：CRLF 文件上 END 行尾的 \\r\\n 一并吞掉，不残留裸 \\r。"""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        f = write(tmp, "AGENTS.md", "# 头\r\n\r\n正文。\r\n")
        r = run(tmp, "--apply")
        assert r.returncode == 0, r.stdout + r.stderr
        text = f.read_text(encoding="utf-8")
        assert A_START in text
        # 迁移形态再跑一轮 CRLF 块替换：存量块行尾是 \r\n 时不残留
        good_block = text[text.index(A_START):]
        legacy = "# 头\r\n\r\n正文。\r\n" + good_block.replace("\n", "\r\n")
        f.write_text(legacy, encoding="utf-8")
        r2 = run(tmp, "--apply")
        assert r2.returncode == 0, r2.stdout + r2.stderr
        text2 = f.read_text(encoding="utf-8")
        assert text2.count(A_START) == 1
        assert A_END + "\r" not in text2, "END 后不得残留孤立 \\r"


def test_agents_multiple_marker_pairs_error_without_writing() -> None:
    """RFC-20261126-02 评审 m3：标记计数 ≠1 ⇒ 报错不修改（防粘贴复读复读标记）。"""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        f = write(tmp, "AGENTS.md", AGENTS_FIXTURE)
        run(tmp, "--apply")
        before = f.read_bytes()
        text = f.read_text(encoding="utf-8")
        # 用户正文里粘进一对复读标记（prd.md 模板同款标记，workflow_plan 复用）
        f.write_text(text + "\n模板片段：\n<!-- ATLAS:START -->\natlas-acceptance: none\n<!-- ATLAS:END -->\n",
                     encoding="utf-8")
        before = f.read_bytes()
        r = run(tmp, "--apply")
        assert r.returncode == 1
        assert "标记多对" in r.stdout + r.stderr
        assert f.read_bytes() == before


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
