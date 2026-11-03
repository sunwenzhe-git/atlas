#!/usr/bin/env python3
"""atlas 项目接线的回归测试。

守护「install.sh 把 AGENTS.md 指针 + after_archive hook 幂等写进目标项目」：
  * AGENTS.md：插在 `<!-- TRELLIS:END -->` 之后；重跑幂等；缺文件创建；区块更新；标记不成对报错且不改。
  * config.yaml：无 hooks 时新增；有 hooks 时并入；旧 after_finish 迁移到 after_archive；重跑幂等。
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
REPO = PKG_ROOT.parent
APPLIER = PKG / "apply-wiring.py"
SNIPPET = PKG / "agent-pointer.md"
REAL_CONFIG = REPO / "codebases" / ".trellis" / "config.yaml"

HOOK_CORE = ".atlas/scripts/refresh_structure.py --root ."
# 2026-11-03（RFC-20261103-04 §6 决策 3）：钩子改为平台无关启动器形态。
HOOK_CMD = f"node .atlas/scripts/run_python.js {HOOK_CORE} --chain"
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

CONFIG_LEGACY_PYTHON = f"""hooks:
  after_archive:
    - "python3 {HOOK_CORE} --chain"
"""

CONFIG_APPLY_TAIL = """hooks:
  after_archive:
    - "python3 .atlas/scripts/refresh_structure.py --root . --apply"
"""

CONFIG_CUSTOM_TAIL = """hooks:
  after_archive:
    - "python3 .atlas/scripts/refresh_structure.py --root . --custom"
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
    # §15 自感知上报的出口必须在指针段里 —— 它是该契约在真实项目里**唯一的常在交付面**
    # （只写在 `.atlas/shared/global-rules.md` 里时，流程中段等不到提醒）。
    assert "atlas report" in body and "§15" in body, "指针段缺 §15 上报出口"


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
        assert "after_archive:" in text
        assert top_hooks_count(text) == 1


def test_config_migrates_legacy_after_finish() -> None:
    """D159：旧 after_finish 里的 refresh hook 迁移到 after_archive；自定义 hook 原样保留。"""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        f = write(tmp, ".trellis/config.yaml", CONFIG_WITH_AFTER_FINISH)
        r = run(tmp, "--apply")
        assert r.returncode == 0, r.stdout
        text = f.read_text(encoding="utf-8")
        assert HOOK_CMD in text
        assert '"echo old"' in text
        assert "after_archive:" in text
        assert top_hooks_count(text) == 1
        # 旧的 after_finish 子块仍在（自定义 echo old），但不得再含 refresh 命令
        finish_i = text.index("after_finish:")
        archive_i = text.index("after_archive:")
        cmd_i = text.index("refresh_structure.py")
        assert finish_i < archive_i and cmd_i > archive_i, text


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


def test_config_upgrades_legacy_hook_without_duplicate() -> None:
    """旧解释器形态（python3/python）⇒ 就地升级为平台无关启动器，且不得双注册。

    钩子写在 git 跟踪的 config.yaml 里：旧形态在另一端 OS 必坏（python3 在 Windows
    只命中商店 stub；python 在 POSIX 常缺席）。update 时就地升级，重跑幂等。
    """
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        f = write(tmp, ".trellis/config.yaml", CONFIG_LEGACY_PYTHON)
        r = run(tmp, "--apply")
        assert r.returncode == 0, r.stdout
        text = f.read_text(encoding="utf-8")
        assert HOOK_CMD in text
        assert f'"python3 {HOOK_CORE}' not in text
        assert text.count("refresh_structure.py") == 1, "升级时不得双注册"
        # 归一后重跑必须字节不变
        before = f.read_text(encoding="utf-8")
        r2 = run(tmp, "--apply")
        assert r2.returncode == 0, r2.stdout
        assert f.read_text(encoding="utf-8") == before
        assert "applied=0" in r2.stdout and "errors=0" in r2.stdout, r2.stdout


def test_config_apply_tail_normalized_to_chain() -> None:
    """after_archive 里旧 `--apply` 尾参要迁成 `--chain`，不能与既有条目并存。"""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        f = write(tmp, ".trellis/config.yaml", CONFIG_APPLY_TAIL)
        r = run(tmp, "--apply")
        assert r.returncode == 0, r.stdout
        text = f.read_text(encoding="utf-8")
        assert HOOK_CMD in text
        assert "--apply" not in text, text
        assert text.count("refresh_structure.py") == 1
        assert top_hooks_count(text) == 1


def test_config_custom_refresh_tail_skipped() -> None:
    """自定义尾参的 refresh hook 不猜、不覆盖、不重复登记。"""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        f = write(tmp, ".trellis/config.yaml", CONFIG_CUSTOM_TAIL)
        before = f.read_text(encoding="utf-8")
        r = run(tmp, "--apply")
        assert r.returncode == 0, r.stdout
        assert f.read_text(encoding="utf-8") == before
        assert "自定义 refresh hook" in r.stdout, r.stdout


def test_hook_command_is_platform_neutral() -> None:
    """同一串钩子命令跨 OS 成立：由 Node 启动器运行时解析 Python 3.10+。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location("apply_wiring_mod", APPLIER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    core = ".atlas/scripts/refresh_structure.py --root ."
    assert mod.HOOK_CMD == f"node .atlas/scripts/run_python.js {core} --chain"
    assert "python3" not in mod.HOOK_CMD and "python " not in mod.HOOK_CMD
    for legacy in (f'    - "python3 {core} --chain"',
                   f'    - "python {core} --chain"',
                   f'    - "py -3 {core} --chain"',
                   f'    - "python.exe {core} --chain"'):
        assert mod._normalize_hook_line(legacy) == \
            f'    - "node .atlas/scripts/run_python.js {core} --chain"'
    # 已是启动器 ⇒ 幂等；绝对路径解释器 ⇒ 不猜
    assert mod._normalize_hook_line(mod.HOOK_CMD) == mod.HOOK_CMD
    assert mod._normalize_hook_line(f'    - "C:/Python312/python.exe {core} --chain"') is None


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


def test_gitignore_fifth_touchpoint_appends_idempotently() -> None:
    """第 5 触点（2026-10-15，issue #8）：已有 `.gitignore` ⇒ 追加一行 `.adapter-out/`，
    重跑幂等字节不变；端到端（真跑 `--apply`）防函数级测试漏掉接线排序/汇总回归。"""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        gi = write(tmp, ".gitignore", "node_modules/\n")
        r1 = run(tmp, "--apply")
        assert r1.returncode == 0, r1.stdout + r1.stderr
        assert gi.read_text(encoding="utf-8") == "node_modules/\n.adapter-out/\n"
        r2 = run(tmp, "--apply")
        assert r2.returncode == 0, r2.stdout
        assert gi.read_text(encoding="utf-8") == "node_modules/\n.adapter-out/\n"


def test_real_config_wiring_is_idempotent() -> None:
    """真实 codebases 配置：无论旧形态还是启动器形态，升级一次后重跑字节不变。"""
    if not REAL_CONFIG.is_file():
        print("skip: codebases/.trellis/config.yaml 不存在")
        return
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        f = write(tmp, ".trellis/config.yaml", REAL_CONFIG.read_text(encoding="utf-8"))
        r1 = run(tmp, "--apply")
        assert r1.returncode == 0, r1.stdout
        text = f.read_text(encoding="utf-8")
        assert text.count("refresh_structure.py") == 1, text
        before = f.read_text(encoding="utf-8")
        r2 = run(tmp, "--apply")
        assert r2.returncode == 0, r2.stdout
        assert f.read_text(encoding="utf-8") == before
        assert "applied=0" in r2.stdout and "errors=0" in r2.stdout, r2.stdout


def main() -> int:
    tests = [
        test_snippet_exists,
        test_agents_insert_after_trellis_and_idempotent,
        test_agents_missing_file_creates,
        test_agents_updates_existing_block,
        test_agents_unbalanced_markers_error_without_writing,
        test_config_new_hooks_block,
        test_config_insert_into_existing_hooks,
        test_config_migrates_legacy_after_finish,
        test_config_idempotent,
        test_config_upgrades_legacy_hook_without_duplicate,
        test_config_apply_tail_normalized_to_chain,
        test_config_custom_refresh_tail_skipped,
        test_hook_command_is_platform_neutral,
        test_dry_run_does_not_write,
        test_gitignore_fifth_touchpoint_appends_idempotently,
        test_real_config_wiring_is_idempotent,
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
