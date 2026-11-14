#!/usr/bin/env python3
"""同步脚本化工具的行为钉（`RFC-20261114-04` 阶段 1 / 2a）。

阶段 1（`refresh_count_anchors`）四类钉：
  * 跨工具绿：合成行数变化 → `--write` → `test_map_anchors` 三函数全绿；
  * 只动数字：改后文档与改前逐字节差异只在数字段；
  * 幂等：连跑两次 `--write`，第二次零 diff；
  * 边界：脏树告警但按工作树写 / 非源仓与非 git 响亮 SKIP / 余漂非零 exit 1 /
    范围外（`shared/gates.md` 计数）不写只报 / `path:line` 不碰。

阶段 2a（`changelog_guard` shadow）钉：
  * 缺段 / 段在零新增 / 只补一份 ⇒ would-flag 且 exit 0；`--enforce` ⇒ exit 1；
  * 两份都有新增 ⇒ PASS；纯 docs / test 批 ⇒ PASS；
  * 空 range ⇒ exit 2（绝不退回 `HEAD~1..HEAD`）；缺省 range = `origin/main..HEAD`；
  * DETECT ⊇ ASSEMBLY_COVER_DIRS ∪ ASSEMBLY_COVER_FILES（守恒钉）；
  * 只提示不改写。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for extra in (HERE, HERE.parent / "scripts"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import changelog_guard as cg  # noqa: E402
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


# ---------------- 阶段 2a：changelog_guard（shadow） ----------------

# 历史回放（2026-11-14 实测；判据 = 批次 range 净 diff，不参与下列夹具）：
# 1) `c6ff399^..ac891d3`（11-12 批，14 笔触装配面 feat/fix）：根 CHANGELOG 缺
#    `[Unreleased]` 段、guide 段内 0 行 ⇒ **would-flag**。
# 2) `v0.2.0-beta.31..6b4e8c6`：**PASS**——`cad2d5d`（11-08 01:10）已在同批内给
#    guide 的 `[Unreleased]` 补了 11 行，`6b4e8c6` 补根文件；净 diff 两份都有账。
# 3) `v0.2.0-beta.30..2fd6911`：**PASS**——`2fd6911` 的 diff 本身同时给两份加了内容。
#    （回放到补写提交的父提交 `..6b4e8c6^` / `..2fd6911^` 才会 would-flag 单份；
#    这不是判据口径，不拿它当样本。）
# 4) `cad2d5d..6b4e8c6`（5 笔纯 docs/chore）：**PASS**（豁免形态）。
# 结论：单份形态只由下面的**合成夹具**覆盖，不拿真实历史当单份样本。

GUARD_CL = "## [Unreleased]\n\n## [v0.1.0] - 2026-01-01\n\n* old\n"
GUARD_NO_UNREL = "## [v0.1.0] - 2026-01-01\n\n* old\n"
GUARD_NEW = "## [Unreleased]\n\n### 📦 feat\n\n* added\n\n## [v0.1.0] - 2026-01-01\n\n* old\n"


def _mk_guard_repo(tmp: Path, base: str = GUARD_CL) -> Path:
    (tmp / "docs" / "guide").mkdir(parents=True)
    (tmp / "tests").mkdir()
    (tmp / "scripts").mkdir()
    (tmp / "scripts" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp / "tests" / "test_a.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    (tmp / "package.json").write_text('{"name": "p"}\n', encoding="utf-8")
    (tmp / "CHANGELOG.md").write_text(base, encoding="utf-8")
    (tmp / "docs" / "guide" / "changelog.md").write_text(base, encoding="utf-8")
    (tmp / "docs" / "note.md").write_text("# note\n", encoding="utf-8")
    _git(tmp, "init", "-q")
    _git(tmp, "add", "-A")
    _git(tmp, "commit", "-q", "-m", "chore: base")
    return tmp


def _guard_commit(repo: Path, msg: str, files: dict[str, str]) -> str:
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()


def test_guard_detect_covers_assembly_surface():
    import pkg_digest
    assert set(pkg_digest.ASSEMBLY_COVER_DIRS) <= cg.DETECT, "DETECT 收窄漏了装配目录"
    assert set(pkg_digest.ASSEMBLY_COVER_FILES) <= cg.DETECT, "DETECT 收窄漏了装配顶层件"
    assert {"install.py", "install.sh", "package.json", "bin"} <= cg.DETECT


def test_guard_flags_missing_changelog_in_shadow(tmp_path, capsys):
    repo = _mk_guard_repo(tmp_path / "repo")
    _guard_commit(repo, "feat(scripts): 改装配面", {"scripts/a.py": "x = 2\n"})
    assert cg.main(["--root", str(repo), "--range", "HEAD~1..HEAD"]) == 0
    out = capsys.readouterr().out
    assert "[would-flag]" in out and "feat/fix 1 笔" in out
    assert "CHANGELOG.md：0 行新增" in out
    assert "docs/guide/changelog.md：0 行新增" in out
    assert "shadow" in out


def test_guard_enforce_exits_1(tmp_path):
    repo = _mk_guard_repo(tmp_path / "repo")
    _guard_commit(repo, "fix(scripts): 改装配面", {"scripts/a.py": "x = 2\n"})
    assert cg.main(["--root", str(repo), "--range", "HEAD~1..HEAD", "--enforce"]) == 1


def test_guard_passes_when_both_have_added_lines(tmp_path, capsys):
    repo = _mk_guard_repo(tmp_path / "repo")
    _guard_commit(repo, "feat(scripts): 带 changelog",
                  {"scripts/a.py": "x = 2\n", "CHANGELOG.md": GUARD_NEW,
                   "docs/guide/changelog.md": GUARD_NEW})
    assert cg.main(["--root", str(repo), "--range", "HEAD~1..HEAD"]) == 0
    out = capsys.readouterr().out
    assert "PASS" in out and "[would-flag]" not in out


def test_guard_header_only_section_is_flagged(tmp_path, capsys):
    repo = _mk_guard_repo(tmp_path / "repo", base=GUARD_NO_UNREL)
    _guard_commit(repo, "feat(scripts): 只起段头",
                  {"scripts/a.py": "x = 2\n",
                   "CHANGELOG.md": "## [Unreleased]\n\n" + GUARD_NO_UNREL,
                   "docs/guide/changelog.md": "## [Unreleased]\n\n" + GUARD_NO_UNREL})
    assert cg.main(["--root", str(repo), "--range", "HEAD~1..HEAD"]) == 0
    out = capsys.readouterr().out
    assert "[would-flag]" in out
    assert "CHANGELOG.md：0 行新增" in out and "docs/guide/changelog.md：0 行新增" in out


def test_guard_passes_when_in_batch_catchup_fills_both(tmp_path, capsys):
    """样本 2/3 的合成版：feat 提交没写账，同批后续 docs 补写两份 ⇒ 净 diff PASS。"""
    repo = _mk_guard_repo(tmp_path / "repo")
    _guard_commit(repo, "feat(scripts): 只改代码", {"scripts/a.py": "x = 2\n"})
    _guard_commit(repo, "docs(changelog): 同批补两份",
                  {"CHANGELOG.md": GUARD_NEW, "docs/guide/changelog.md": GUARD_NEW})
    assert cg.main(["--root", str(repo), "--range", "HEAD~2..HEAD"]) == 0
    out = capsys.readouterr().out
    assert "PASS" in out and "[would-flag]" not in out


def test_guard_synthetic_single_file_is_flagged(tmp_path, capsys):
    """单份形态 = **合成夹具**（同批只有根 CHANGELOG 有新增、guide 零新增）。"""
    repo = _mk_guard_repo(tmp_path / "repo")
    _guard_commit(repo, "feat(scripts): 只补一份",
                  {"scripts/a.py": "x = 2\n", "CHANGELOG.md": GUARD_NEW})
    assert cg.main(["--root", str(repo), "--range", "HEAD~1..HEAD"]) == 0
    out = capsys.readouterr().out
    assert "CHANGELOG.md：2 行新增" in out
    assert "docs/guide/changelog.md：0 行新增" in out


def test_guard_passes_pure_docs_batch(tmp_path, capsys):
    repo = _mk_guard_repo(tmp_path / "repo")
    _guard_commit(repo, "docs: 纯文档", {"docs/note.md": "# changed\n"})
    assert cg.main(["--root", str(repo), "--range", "HEAD~1..HEAD"]) == 0
    out = capsys.readouterr().out
    assert "PASS" in out and "纯 docs/test/chore 批豁免" in out


def test_guard_passes_pure_test_batch(tmp_path, capsys):
    repo = _mk_guard_repo(tmp_path / "repo")
    _guard_commit(repo, "test: 纯测试", {"tests/test_a.py": "def test_a():\n    assert 1\n"})
    assert cg.main(["--root", str(repo), "--range", "HEAD~1..HEAD"]) == 0
    assert "PASS" in capsys.readouterr().out


def test_guard_empty_range_exits_2(tmp_path, capsys):
    repo = _mk_guard_repo(tmp_path / "repo")
    assert cg.main(["--root", str(repo), "--range", "HEAD..HEAD"]) == 2
    out = capsys.readouterr().out
    assert "为空" in out and "--range" in out


def test_guard_default_range_is_origin_main(tmp_path, capsys):
    repo = _mk_guard_repo(tmp_path / "repo")
    base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    _git(repo, "update-ref", "refs/remotes/origin/main", base)
    _guard_commit(repo, "feat(scripts): 未推送提交", {"scripts/a.py": "x = 2\n"})
    assert cg.main(["--root", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "origin/main..HEAD" in out and "[would-flag]" in out


def test_guard_never_rewrites_changelog(tmp_path):
    repo = _mk_guard_repo(tmp_path / "repo")
    _guard_commit(repo, "feat(scripts): 改装配面", {"scripts/a.py": "x = 2\n"})
    before = {rel: (repo / rel).read_bytes() for rel in cg.CHANGELOGS}
    cg.main(["--root", str(repo), "--range", "HEAD~1..HEAD"])
    after = {rel: (repo / rel).read_bytes() for rel in cg.CHANGELOGS}
    assert before == after, "守卫只提示，绝不自动改写 changelog"
