#!/usr/bin/env python3
"""atlas 项目接线的回归测试。

守护「install.sh 把 AGENTS.md 指针 + after_finish hook 幂等写进目标项目」：
  * AGENTS.md：插在 `<!-- TRELLIS:END -->` 之后；重跑幂等；缺文件创建；区块更新；标记不成对报错且不改。
  * config.yaml：无 hooks 时新增；有 hooks 时并入；有 after_finish 时追加；重跑幂等。
  * dry-run 不写。

两种运行方式：
    python3 atlas/tests/test_project_wiring.py      # 脚本式
    pytest atlas/tests/test_project_wiring.py        # pytest 式
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
PKG = PKG_ROOT / "patches" / "project-wiring"
REPO = PKG_ROOT.parent
APPLIER = PKG / "apply-wiring.py"
SNIPPET = PKG / "agent-pointer.md"
REAL_CONFIG = REPO / "codebases" / ".trellis" / "config.yaml"

HOOK_CMD = "python3 .atlas/scripts/refresh_structure.py --root . --apply"
A_START = "<!-- ATLAS:START -->"
A_END = "<!-- ATLAS:END -->"
T_END = "<!-- TRELLIS:END -->"

AGENTS_FIXTURE = f"""<!-- TRELLIS:START -->
# Trellis Instructions

Managed by Trellis. Edits outside this block are preserved.

{T_END}
"""

CONFIG_NO_HOOKS = """# Trellis Configuration

session_commit_message: "chore: record journal"
max_journal_lines: 2000
"""

CONFIG_WITH_HOOKS = """# Trellis Configuration

hooks:
  after_create:
    - "echo created"

# Misc
max_journal_lines: 2000
"""

CONFIG_WITH_AFTER_FINISH = """hooks:
  after_finish:
    - "echo old"
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
    assert "#### 1.6 项目级资产更新" in body
    assert "stack-profile.yaml" in body


def test_agents_insert_after_trellis_and_idempotent() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        f = write(tmp, "AGENTS.md", AGENTS_FIXTURE)

        r1 = run(tmp, "--apply")
        assert r1.returncode == 0, r1.stdout + r1.stderr
        text = f.read_text(encoding="utf-8")
        assert A_START in text and A_END in text
        # 指针在 TRELLIS:END 之后
        assert text.index(T_END) < text.index(A_START)
        # Trellis 区块原样保留
        assert "Managed by Trellis. Edits outside this block are preserved." in text
        assert "#### 1.6 项目级资产更新" in text

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
        text = f.read_text(encoding="utf-8")
        assert A_START in text and A_END in text


def test_agents_updates_existing_block() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        stale = f"{T_END}\n\n{A_START}\nOLD STALE CONTENT\n{A_END}\n"
        f = write(tmp, "AGENTS.md", stale)
        r = run(tmp, "--apply")
        assert r.returncode == 0, r.stdout
        text = f.read_text(encoding="utf-8")
        assert "OLD STALE CONTENT" not in text
        assert text.count(A_START) == 1 and text.count(A_END) == 1


def test_agents_unbalanced_markers_error_without_writing() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        f = write(tmp, "AGENTS.md", f"hello\n{A_START}\nno end\n")
        before = f.read_text(encoding="utf-8")
        r = run(tmp, "--apply")
        assert r.returncode == 1, r.stdout
        assert "errors=1" in r.stdout, r.stdout
        assert f.read_text(encoding="utf-8") == before


def top_hooks_count(text: str) -> int:
    return sum(1 for ln in text.splitlines() if ln.strip() == "hooks:")


def test_config_new_hooks_block() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        f = write(tmp, ".trellis/config.yaml", CONFIG_NO_HOOKS)
        r = run(tmp, "--apply")
        assert r.returncode == 0, r.stdout
        text = f.read_text(encoding="utf-8")
        assert HOOK_CMD in text
        assert top_hooks_count(text) == 1
        assert "session_commit_message" in text  # 原内容保留


def test_config_insert_into_existing_hooks() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        f = write(tmp, ".trellis/config.yaml", CONFIG_WITH_HOOKS)
        r = run(tmp, "--apply")
        assert r.returncode == 0, r.stdout
        text = f.read_text(encoding="utf-8")
        assert HOOK_CMD in text
        assert "after_create:" in text
        assert top_hooks_count(text) == 1


def test_config_insert_after_existing_after_finish() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        f = write(tmp, ".trellis/config.yaml", CONFIG_WITH_AFTER_FINISH)
        r = run(tmp, "--apply")
        assert r.returncode == 0, r.stdout
        text = f.read_text(encoding="utf-8")
        assert HOOK_CMD in text
        assert '"echo old"' in text
        assert top_hooks_count(text) == 1


def test_config_idempotent() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        f = write(tmp, ".trellis/config.yaml", CONFIG_NO_HOOKS)
        run(tmp, "--apply")
        before = f.read_text(encoding="utf-8")
        r2 = run(tmp, "--apply")
        assert r2.returncode == 0, r2.stdout
        assert f.read_text(encoding="utf-8") == before
        assert "applied=0" in r2.stdout and "errors=0" in r2.stdout, r2.stdout


def test_dry_run_does_not_write() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        a = write(tmp, "AGENTS.md", AGENTS_FIXTURE)
        c = write(tmp, ".trellis/config.yaml", CONFIG_NO_HOOKS)
        a_before, c_before = a.read_text(encoding="utf-8"), c.read_text(encoding="utf-8")
        r = run(tmp)  # 缺省 dry-run
        assert r.returncode == 0, r.stdout
        assert "applied=2" in r.stdout, r.stdout
        assert a.read_text(encoding="utf-8") == a_before
        assert c.read_text(encoding="utf-8") == c_before


def test_real_config_already_wired() -> None:
    """真实 codebases 配置已含 hook → 应 skipped（守护重复登记）。"""
    if not REAL_CONFIG.is_file():
        print("skip: codebases/.trellis/config.yaml 不存在")
        return
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        f = write(tmp, ".trellis/config.yaml", REAL_CONFIG.read_text(encoding="utf-8"))
        before = f.read_text(encoding="utf-8")
        r = run(tmp, "--apply")
        assert r.returncode == 0, r.stdout
        assert f.read_text(encoding="utf-8") == before
        assert "skipped=1" in r.stdout, r.stdout


def main() -> int:
    tests = [
        test_snippet_exists,
        test_agents_insert_after_trellis_and_idempotent,
        test_agents_missing_file_creates,
        test_agents_updates_existing_block,
        test_agents_unbalanced_markers_error_without_writing,
        test_config_new_hooks_block,
        test_config_insert_into_existing_hooks,
        test_config_insert_after_existing_after_finish,
        test_config_idempotent,
        test_dry_run_does_not_write,
        test_real_config_already_wired,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  ✗ {t.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ✗ {t.__name__}: {type(exc).__name__}: {exc}")
    print(f"{'FAIL' if failed else 'PASS'} ({len(tests) - failed}/{len(tests)})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
