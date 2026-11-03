#!/usr/bin/env python3
"""`scripts/atlas_review.py` 一键编排回归（RFC-20261103-05）。

夹具 = 临时项目：最小 stack-profile（`impl_review` 指向 fixture CLI）+ 最小 PRD/E2E 资产 +
fake CLI（preview 输出 `Will review 1`；review 写 coverage.completed = src/a.ts）。

覆盖：全链 v4 / dry-run 不写盘 / preview 与 review 失败透传 / `impl_review.llm` 缺 ⇒ SKIP /
`--cli` 覆盖 / delta flags / inputs 失败只 WARN / **真 CLI flag 形态锁**（对照
`shared/closeout.md` 步骤 10 的两条命令，契约改一处即红）。

变异证明（编号属本文件）：M169 去掉 `--scope-manifest` 传给 validator ⇒ 全链 FAIL；
M170 把 preview 的 `Will review` 解析删掉 ⇒ 全链 exit 2。
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PKG_ROOT / "scripts" / "atlas_review.py"
CLOSEOUT = PKG_ROOT / "shared" / "closeout.md"

FAKE_CLI = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path

args = sys.argv[1:]
if "--preview" in args:
    if os.environ.get("FAKE_FAIL_PREVIEW"):
        sys.exit(7)
    print("Will review 1")
    sys.exit(0)
if os.environ.get("FAKE_FAIL_REVIEW"):
    sys.exit(7)
out = Path(args[args.index("--output") + 1])
out.write_text(json.dumps({
    "status": "completed",
    "summary": {"files_reviewed": 1, "comments": 0},
    "comments": [], "warnings": [],
    "manifest": {"coverage": {"completed": [{"path": "src/a.ts"}], "failed": [],
                              "waived": [], "reused": [], "selected": [{"path": "src/a.ts"}]}},
}), encoding="utf-8")
'''


def make_project(root: Path, *, llm: str | None = "fake-model", cli: str | None = None,
                  assets: bool = True) -> Path:
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "a.ts").write_text("export const a = 1\n", encoding="utf-8")
    f = root / "fake_cli.py"
    f.write_text(FAKE_CLI, encoding="utf-8")
    f.chmod(0o755)
    cli_path = cli or str(f)
    (root / "product").mkdir(parents=True, exist_ok=True)
    (root / "product" / "stack-profile.yaml").write_text(
        "product: Demo\n"
        "origin: greenfield\n"
        "apps:\n  - name: web\n    path: src\n    kind: frontend\n    role: landing\n"
        "    stack: React\n"
        "adapters:\n  routes: null\n  api: null\n  models: null\n  tests: null\n"
        "e2e:\n  runner: node-playwright\n"
        f"impl_review:\n  cli: {cli_path}\n  llm: {llm if llm is not None else 'null'}\n",
        encoding="utf-8")
    if assets:
        (root / "product" / "prd").mkdir(parents=True, exist_ok=True)
        (root / "product" / "prd" / "prd.md").write_text("# PRD\n", encoding="utf-8")
        (root / "product" / "e2e" / "cases").mkdir(parents=True, exist_ok=True)
        (root / "product" / "e2e" / "e2e-index.md").write_text("# E2E\n", encoding="utf-8")
        (root / "product" / "e2e" / "cases" / "c1.md").write_text("# case\n", encoding="utf-8")
    return root


def run(root: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run([sys.executable, str(SCRIPT), "--root", str(root), *args],
                          capture_output=True, text=True, timeout=180, env=e)


def report_dir(root: Path) -> Path:
    dirs = sorted((root / "product" / "reviews").glob("*-impl-review-U"))
    assert dirs, "未生成报告目录"
    return dirs[-1]


BASE = ("--unit", "U", "--from", "main", "--to", "HEAD", "--expected-files", "1")


def test_full_chain_writes_v4_report(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    p = run(root, *BASE, "--scope", "demo")
    assert p.returncode == 0, p.stdout + p.stderr
    d = report_dir(root)
    review = json.loads((d / "review.json").read_text(encoding="utf-8"))
    assert review["schema_version"] == 4
    assert review["review_scope"]["files"][0]["path"] == "src/a.ts"
    for name in ("background.md", "cli.json", "scope-manifest.json", "review.json", "closure.json"):
        assert (d / name).is_file(), name
    assert "[PASS] 评审范围内容封口（v4）" in p.stdout
    assert "atlas review @" in p.stdout and "ok" in p.stdout


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    p = run(root, *BASE, "--dry-run")
    assert p.returncode == 0, p.stdout + p.stderr
    assert not (root / "product" / "reviews").exists()
    assert "$ " in p.stdout and "Will review 1" in p.stdout
    for marker in ("--preview", "--audience", "cli_review_convert.py",
                   "validate_review_report.py", "review_closure.py"):
        assert marker in p.stdout, marker


def test_preview_failure_passthrough(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    p = run(root, *BASE, env={"FAKE_FAIL_PREVIEW": "1"})
    assert p.returncode == 7
    assert not (root / "product" / "reviews").exists()


def test_review_failure_passthrough(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    p = run(root, *BASE, env={"FAKE_FAIL_REVIEW": "1"})
    assert p.returncode == 7


def test_llm_missing_skips(tmp_path: Path) -> None:
    root = make_project(tmp_path, llm=None)
    p = run(root, *BASE)
    assert p.returncode == 0 and "SKIP" in p.stdout
    assert not (root / "product" / "reviews").exists()


def test_cli_override_wins(tmp_path: Path) -> None:
    root = make_project(tmp_path, cli="/nonexistent/ocr")
    p = run(root, *BASE, "--cli", str(root / "fake_cli.py"))
    assert p.returncode == 0, p.stdout + p.stderr


def test_delta_flags_recorded(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    p = run(root, "--unit", "U", "--from", "main", "--to", "HEAD", "--expected-files", "1",
            "--delta-only", "--base-sha", "a" * 40, "--head-sha", "b" * 40, "--round", "2")
    assert p.returncode == 0, p.stdout + p.stderr
    review = json.loads((report_dir(root) / "review.json").read_text(encoding="utf-8"))
    assert review["delta_only"] is True and review["head_sha"] == "b" * 40


def test_inputs_failure_warns_not_blocks(tmp_path: Path) -> None:
    root = make_project(tmp_path, assets=False)
    p = run(root, *BASE)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "make_review_inputs 失败" in p.stderr


def test_background_is_pointerized(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    p = run(root, *BASE)
    assert p.returncode == 0, p.stdout + p.stderr
    text = (report_dir(root) / "background.md").read_text(encoding="utf-8")
    assert ".trellis/tasks/U/prd.md" in text
    assert "§10.4" in text and "MANIFEST.json" in text
    assert "Given" not in text  # 不复制 AC 正文


def _load_module():
    spec = importlib.util.spec_from_file_location("atlas_review_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_true_cli_flag_shape_lock() -> None:
    """契约 §步骤 10 的两条命令 flag 集合必须与编排器常量双向一致（改契约即红）。"""
    mod = _load_module()
    text = CLOSEOUT.read_text(encoding="utf-8")
    preview_line = next(ln for ln in text.splitlines() if "<cli> review --preview" in ln)
    review_line = next(ln for ln in text.splitlines() if "<cli> review --audience agent" in ln)
    flags = lambda line: set(re.findall(r"--[a-z-]+", line))
    assert flags(preview_line) == set(mod.PREVIEW_FLAGS), preview_line
    assert flags(review_line) == set(mod.REVIEW_FLAGS), review_line
    # 实际 argv 也必须覆盖常量（防「常量对、命令不对」）
    assert set(mod.preview_argv("x", "a", "b")) >= set(mod.PREVIEW_FLAGS)
    assert set(mod.review_argv("x", "a", "b", Path("o"), Path("g"))) >= set(mod.REVIEW_FLAGS)


def test_cli_missing_clean_error(tmp_path: Path) -> None:
    root = make_project(tmp_path, cli="/nonexistent/ocr")
    p = run(root, *BASE)
    assert p.returncode == 2 and "不存在" in p.stderr
    assert "Traceback" not in p.stderr


def test_parse_preview_n_accepts_colon() -> None:
    mod = _load_module()
    assert mod.parse_preview_n("Will review: 3") == 3
    assert mod.parse_preview_n("will review 4 files") == 4
    assert mod.parse_preview_n("no count") is None


def test_background_respects_overrides(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    p = run(root, *BASE, "--requirement", "custom/req.md",
            "--prd", "custom/prd", "--cases", "custom/cases")
    assert p.returncode == 0, p.stdout + p.stderr
    text = (report_dir(root) / "background.md").read_text(encoding="utf-8")
    assert "custom/req.md" in text and "custom/prd" in text and "custom/cases" in text
