#!/usr/bin/env python3
"""同步脚本化工具的行为钉（`RFC-20261114-04` 阶段 1：`refresh_count_anchors`）。

钉的四类（与 RFC §3 对齐）：
  * 跨工具绿：合成行数变化 → `--write` → `test_map_anchors` 三函数全绿；
  * 只动数字：改后文档与改前逐字节差异只在数字段；
  * 幂等：连跑两次 `--write`，第二次零 diff；
  * 边界：脏树告警但按工作树写 / 非源仓与非 git 响亮 SKIP / 余漂非零 exit 1 /
    范围外（`shared/gates.md` 计数）不写只报 / `path:line` 不碰。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import refresh_count_anchors as rca  # noqa: E402
from test_map_anchors import check_freshness, check_snapshot, collect_docs  # noqa: E402

INDEX_MD = """# 地图

> **锚定版本**：v1.2.3

## 数字快照

| 量 | 值 | 出处 |
|---|---|---|
| 校验器 | 9(`atlas_check.VALIDATORS`) | `scripts/atlas_check.py` |
| 编排门行 | 9 类(validators / 对齐测试) | `scripts/atlas_check.py` |
| 出厂测试文件 | 9 | `tests/` |
| skills | 9 | `skills/` |
| 环 | 9 | `rings/` |
| 共享契约 | 9 | `shared/` |
| 共享内核 | 9 | `_support/` |
| 最大单件 | `scripts/big.py` 9 行 | — |

`big`(`scripts/big.py:1`) 与 `scripts/big.py`(9 行)
"""

HTML = """<div>
  {id:'g-test', title:'出厂测试 ×9',
   tip:{sum:'tests/ 9 文件,含钉子。',files:[['tests/','出厂测试套件目录:9 个测试文件']]}},
  {id:'shared', sub:'shared/ 契约 ×9'},
  {id:'kernel', sub:'_support/ 内核 ×9'},
  files:[['scripts/big.py','big 5 行:说明']],
</div>
"""

BIG_PY = "def big():\n    pass\n\ny = 1\ny = 2\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                   check=True, capture_output=True, text=True)


def _mk_repo(tmp: Path, *, html: str = HTML, commit: bool = True) -> Path:
    """最小源包夹具（8 个实收键 + 行数锚 + html 计数锚都在场）。"""
    (tmp / "docs" / "map").mkdir(parents=True)
    (tmp / "scripts").mkdir()
    (tmp / "tests").mkdir()
    (tmp / "skills" / "s1").mkdir(parents=True)
    (tmp / "rings" / "structure").mkdir(parents=True)
    (tmp / "shared").mkdir()
    (tmp / "_support").mkdir()
    (tmp / "scripts" / "atlas_check.py").write_text("VALIDATORS = ('a', 'b')\n", encoding="utf-8")
    (tmp / "scripts" / "big.py").write_text(BIG_PY, encoding="utf-8")
    (tmp / "tests" / "test_a.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    (tmp / "rings" / "structure" / "reference.md").write_text("# r\n", encoding="utf-8")
    (tmp / "shared" / "global-rules.md").write_text("# g\n", encoding="utf-8")
    (tmp / "_support" / "k.py").write_text("x = 1\n", encoding="utf-8")
    (tmp / "install.sh").write_text("check one\ncheck two\n", encoding="utf-8")
    (tmp / "package.json").write_text('{"version": "1.2.3"}\n', encoding="utf-8")
    (tmp / "docs" / "map" / "index.md").write_text(INDEX_MD, encoding="utf-8")
    (tmp / "docs" / "map" / "atlas-map.html").write_text(html, encoding="utf-8")
    if commit:
        _git(tmp, "init", "-q")
        _git(tmp, "add", "-A")
        _git(tmp, "commit", "-q", "-m", "init")
    return tmp


def _docs_text(repo: Path) -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8")
            for p in sorted((repo / "docs" / "map").iterdir()) if p.is_file()}


def _digits_masked(text: str) -> str:
    return re.sub(r"\d+", "#", text)


def test_write_refreshes_anchors_and_cross_tool_is_green(tmp_path, capsys):
    repo = _mk_repo(tmp_path / "repo")
    # 合成行数变化：被测源文件真实变长 3 行（不是改锚骗自己）
    with (repo / "scripts" / "big.py").open("a", encoding="utf-8") as f:
        f.write("y = 3\ny = 4\ny = 5\n")
    before = _docs_text(repo)

    assert rca.main(["--root", str(repo), "--write"]) == 0

    assert not collect_docs(repo), "写后锚存活必须全绿"
    assert not check_snapshot(repo), "写后 index.md 数字快照必须全绿"
    assert not check_freshness(repo), "写后行数与计数声明必须全绿"
    for name, old in before.items():
        assert _digits_masked(old) == _digits_masked(_docs_text(repo)[name]), \
            f"{name} 除数字外不得有别字节变化"


def test_path_line_anchor_is_not_touched(tmp_path):
    repo = _mk_repo(tmp_path / "repo")
    assert rca.main(["--root", str(repo), "--write"]) == 0
    idx = (repo / "docs" / "map" / "index.md").read_text(encoding="utf-8")
    assert "`scripts/big.py:1`" in idx, "path:line 行号锚归 fix_drifts，本器不得改写"
    assert "`scripts/big.py`(5 行)" in idx, "同一行的计数锚必须按实况写"


def test_second_write_is_idempotent(tmp_path, capsys):
    repo = _mk_repo(tmp_path / "repo")
    assert rca.main(["--root", str(repo), "--write"]) == 0
    first = _docs_text(repo)
    capsys.readouterr()
    assert rca.main(["--root", str(repo), "--write"]) == 0
    out = capsys.readouterr().out
    assert _docs_text(repo) == first, "第二次 --write 必须零 diff"
    assert "0 处待写" in out


def test_gates_counts_are_out_of_scope(tmp_path, capsys):
    repo = _mk_repo(tmp_path / "repo")
    gates = repo / "shared" / "gates.md"
    gates.write_text("| 门 | **9 个**测试文件；`tests/test_a.py` 3 条 | `当前 12）` |\n",
                     encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "gates")
    before = gates.read_text(encoding="utf-8")

    assert rca.main(["--root", str(repo), "--write"]) == 0
    out = capsys.readouterr().out
    assert "范围外" in out and "shared/gates.md" in out, "canonical 计数必须显式报范围外"
    assert gates.read_text(encoding="utf-8") == before, "范围外文件不得被写"


def test_dirty_tree_warns_but_writes_worktree_value(tmp_path, capsys):
    repo = _mk_repo(tmp_path / "repo")
    with (repo / "scripts" / "big.py").open("a", encoding="utf-8") as f:
        f.write("y = 9\n")
    assert rca.main(["--write", "--root", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "[WARN]" in out and "脏树" in out
    assert "`scripts/big.py`(6 行)" in (repo / "docs" / "map" / "index.md").read_text(encoding="utf-8"), \
        "脏树时按工作树现值写（6 行）"


def test_non_source_repo_skips(tmp_path, capsys):
    tmp = tmp_path / "plain"
    tmp.mkdir()
    assert rca.main(["--root", str(tmp)]) == 0
    assert "SKIP" in capsys.readouterr().out


def test_non_git_source_repo_skips(tmp_path, capsys):
    repo = _mk_repo(tmp_path / "repo", commit=False)
    assert rca.main(["--root", str(repo), "--write"]) == 0
    out = capsys.readouterr().out
    assert "SKIP" in out and "git" in out


def test_residual_drift_exits_1(tmp_path, capsys):
    # 版本串是发版动作（只报告不写）：残留 version_stale 必须让写后自检 exit 1
    repo = _mk_repo(tmp_path / "repo", html="<div>v9.9.9</div>\n")
    assert rca.main(["--root", str(repo), "--write"]) == 1
    out = capsys.readouterr().out
    assert "余漂" in out and "version_stale" in out


def test_regex_self_check_rejects_path_line_counts():
    rca.self_check_regexes()  # 不抛 = 行号锚与计数锚不相交
