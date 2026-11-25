"""atlas-ablate 全量执行面：目录枚举、行摘除、逐字节还原与矩阵。"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
ABLATE_ALL = PKG_ROOT / "scripts" / "ablate_all.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


FAKE_CHECK = '''\
import argparse
import json
import sys
from pathlib import Path

VALIDATORS = ("validate_demo",)


def check_validators(root, rows):
    validator = Path(root) / "validators" / "validate_demo.py"
    if validator.is_file():
        rows.add("validate_demo", "ok", "演示校验器", duration_ms=10)
    else:
        rows.add("validate_demo", "SKIP", "校验器不存在")


def check_other(root, rows):
    rows.add("旁路门", "ok", "内联门", duration_ms=5)


def check_slow(root, rows):
    rows.add("慢门", "SKIP", "靶场未起")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows = []

    class RowSink:
        def add(self, name, status, detail="", duration_ms=None):
            rows.append({"name": name, "status": status, "detail": detail,
                         "duration_ms": duration_ms})

    check_validators(args.root, RowSink())
    check_other(args.root, RowSink())
    if not args.fast:
        check_slow(args.root, RowSink())
    print(json.dumps({"ok": not any(r["status"] == "FAIL" for r in rows),
                      "rows": rows}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def _fixture(root: Path) -> None:
    (root / "scripts").mkdir(parents=True)
    (root / "validators").mkdir()
    (root / "scripts" / "atlas_check.py").write_text(FAKE_CHECK, encoding="utf-8")
    (root / "validators" / "validate_demo.py").write_text(
        "print('demo')\n", encoding="utf-8")


def test_catalog_enumerates_full_surface_and_excludes_dispatcher():
    mod = _load(ABLATE_ALL, "ablate_all_catalog")
    catalog = mod.build_catalog(PKG_ROOT)
    ids = {entry["id"] for entry in catalog["entries"]}
    assert "validate_adopt_facts" in ids
    assert "check_generated" in ids
    assert "check_validators" not in ids
    assert catalog["counts"]["validators"] == 14
    assert catalog["counts"]["inline"] == 10
    assert catalog["counts"]["total"] == 24


def test_strip_rows_only_touches_target_function():
    mod = _load(ABLATE_ALL, "ablate_all_strip")
    source = '''\
def check_a(rows):
    if True:
        rows.add("A", "ok", "x")

def check_b(rows):
    rows.add("B", "ok", "y")
'''
    text, removed = mod._strip_rows(source, "check_b")
    assert removed == 1
    assert 'rows.add("A"' in text
    assert 'rows.add("B"' not in text
    compile(text, "<stripped>", "exec")


def test_full_run_restores_bytes_and_reports_matrix():
    mod = _load(ABLATE_ALL, "ablate_all_run")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "project"
        out = Path(tmp) / "evidence"
        root.mkdir()
        _fixture(root)
        before_check = _sha(root / "scripts" / "atlas_check.py")
        before_validator = _sha(root / "validators" / "validate_demo.py")

        result = mod.run_full(root, out, rounds=2, timeout=30,
                              slow_timeout=30, keep_workdir=False)
        entries = {entry["id"]: entry for entry in result["entries"]}

        assert entries["validate_demo"]["surface"] == "fast"
        assert entries["validate_demo"]["after_status"]["validate_demo"] == "SKIP"
        assert entries["check_other"]["surface"] == "fast"
        assert entries["check_other"]["after_status"]["旁路门"] == "ABSENT"
        assert entries["check_slow"]["verdict"].startswith("不可归因")
        assert all(entry.get("restore_ok", True) for entry in result["entries"])

        assert _sha(root / "scripts" / "atlas_check.py") == before_check
        assert _sha(root / "validators" / "validate_demo.py") == before_validator
        matrix = json.loads((out / "matrix.json").read_text(encoding="utf-8"))
        assert matrix["counts"]["total"] == 3
        assert matrix["counts"]["ablated"] == 2
        assert matrix["counts"]["restore_failed"] == 0


def test_cli_has_no_single_mechanism_mode():
    proc = subprocess.run([sys.executable, str(ABLATE_ALL), "--help"],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0
    for forbidden in ("--only", "--mechanism", "--single"):
        assert forbidden not in proc.stdout
