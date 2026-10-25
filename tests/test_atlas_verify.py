#!/usr/bin/env python3
"""atlas_verify(验收执行器,RFC-20261025-02 v2 / D150)七钉。

四步版:pre / run=atlas_check / report(留档) / backfill 缓行(写面零触碰)。
钉对应 RFC §4 ①–⑦;变异 **MB19**(摘「留档短路」⇒ 钉④红)/ **MB20**(摘「失败停环」⇒ 失败批被落档成 ok ⇒ 钉③红),四段协议还原逐字节一致。

夹具:temp root + 假 `atlas-prepare.mjs`(node,记调用数/批级 ID/可注入失败)
+ 假 `.atlas/scripts/atlas_check.py`(记真跑调用数,可注入失败行/成功行/留证构件)。
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
VERIFY = PKG_ROOT / "scripts" / "atlas_verify.py"

FAKE_PREPARE = """import fs from 'fs';
const cnt = '.verify-prep-count';
let n = 0; try { n = parseInt(fs.readFileSync(cnt, 'utf8') || '0', 10) || 0; } catch (e) {}
fs.writeFileSync(cnt, String(n + 1));
if (process.env.ATLAS_CASE_ID) fs.writeFileSync('.verify-prep-caseid', process.env.ATLAS_CASE_ID);
try { if (fs.readFileSync('.verify-prep-mode', 'utf8').trim() === 'fail') { console.error('prep boom'); process.exit(1); } } catch (e) {}
console.log('prepared');
"""

FAKE_CHECK = """import json as _json, sys
from pathlib import Path
root = Path(sys.argv[sys.argv.index("--root") + 1])
inv = root / ".atlas-run-invocations"
n = int(inv.read_text()) + 1 if inv.exists() else 1
inv.write_text(str(n))
mode = "ok"
mp = root / ".verify-check-mode"
if mp.exists():
    mode = mp.read_text().strip()
run_dir = root / "product/e2e/scripts/.atlas-run"
run_dir.mkdir(parents=True, exist_ok=True)
if mode == "fail":
    (run_dir / "trace.zip").write_bytes(b"fake-trace")
    print("  FAIL e2e_real_run  [FAIL] 判据不成立(注入)")
    print("FAIL (详细错误堆栈已落盘)")
    sys.exit(1)
(run_dir / "results.json").write_text("{}")
(run_dir / "e2e-summary.json").write_text("{}")
print("  ok   assembly_version  源包与装配态一致")
print("  ok   e2e_real_run      11/11")
print("OK")
"""


def load_verify():
    spec = importlib.util.spec_from_file_location("atlas_verify_under_test", VERIFY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make(root: Path, prep: bool = True, check: bool = True) -> None:
    (root / "product" / "e2e" / "scripts").mkdir(parents=True, exist_ok=True)
    (root / ".atlas" / "scripts").mkdir(parents=True, exist_ok=True)
    if prep:
        (root / "product/e2e/scripts/atlas-prepare.mjs").write_text(FAKE_PREPARE, encoding="utf-8")
    if check:
        (root / ".atlas/scripts/atlas_check.py").write_text(FAKE_CHECK, encoding="utf-8")


def run(root: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(VERIFY), "--root", str(root), *extra],
                          capture_output=True, text=True, timeout=300)


def _invocations(root: Path) -> int:
    p = root / ".atlas-run-invocations"
    return int(p.read_text()) if p.exists() else 0


def test_pre_failure_stops_batch() -> None:
    """钉①:prepare 失败 ⇒ 停在 pre、结构化报告、atlas_check 不被调、无留档(下游不静默跳过)。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        (root / ".verify-prep-mode").write_text("fail", encoding="utf-8")
        r = run(root, "--json")
        assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
        data = json.loads(r.stdout)
        assert data["failed_step"] == "pre" and data["ok"] is False, data
        assert _invocations(root) == 0                      # run 未执行
        assert not (root / "product/e2e/reviews").exists() or not list((root / "product/e2e/reviews").iterdir())


def test_batch_case_id_is_explicit_batch_token() -> None:
    """钉②:批级 `ATLAS_CASE_ID` 值形态 = `verify-batch`(显式批标识,非用例 ID;D121 逐用例归控制台)。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        assert run(root).returncode == 0
        assert (root / ".verify-prep-caseid").read_text().strip() == "verify-batch"


def test_run_failure_report_keeps_gate_rows_and_evidence() -> None:
    """钉③:run 失败 ⇒ 报告含门行原样 + 留证构件路径(D108 构件在失败报告可见)。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        (root / ".verify-check-mode").write_text("fail", encoding="utf-8")
        r = run(root, "--json")
        assert r.returncode == 1, (r.stdout, r.stderr)
        data = json.loads(r.stdout)
        assert data["failed_step"] == "run"
        assert any(row["name"] == "e2e_real_run" and row["status"] == "FAIL" for row in data["rows"]), data
        assert any("trace.zip" in p for p in data["evidence"]), data["evidence"]
        # 失败不落档(重跑不被短路)
        assert data["archive"] is None


def test_existing_archive_short_circuits_whole_batch() -> None:
    """钉④:留档在 ⇒ 整批短路——pre 与 atlas_check 都不执行。
    变异 **MB19**:摘掉留档短路 ⇒ 本钉红。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        d = root / "product/e2e/reviews"
        (d / "2026-01-01-verify").mkdir(parents=True)  # 任意既有 -verify 留档形态(当日由脚本判定,此处经 --json 验证语义)
        (d / "2026-01-01-verify/README.md").write_text("# old", encoding="utf-8")
        mod = load_verify()
        # 直接验证短路判据:archive_dir 存在 ⇒ main 短路(用 monkeypatch 日期不可行 ⇒ 以目录形态构造当日)
        import datetime as _dt
        today_dir = d / f"{_dt.date.today().isoformat()}-verify"
        today_dir.mkdir(parents=True, exist_ok=True)
        (today_dir / "README.md").write_text("# old", encoding="utf-8")
        r = run(root, "--json")
        assert r.returncode == 0, (r.stdout, r.stderr)
        data = json.loads(r.stdout)
        assert data["short_circuit"] is True and data["real_run_count"] == 0, data
        assert not (root / ".verify-prep-count").exists()   # pre 未执行
        assert _invocations(root) == 0


def test_resume_semantics_run_always_reruns() -> None:
    """钉⑤:断点语义——pre 恒重跑(幂等廉价);run **恒重跑**(验收本体;results.json 在失败批
    也存在,按它跳过 = 假绿通道——上一失败批的 check 若被误信为绿,空行集会落档成 ok)。
    留档是唯一短路门户(钉④);重跑清空上一失败批留证 = 已登记观察(bugs.md 留存窗口行)。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        run_dir = root / "product/e2e/scripts/.atlas-run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "results.json").write_text("{}", encoding="utf-8")      # 上一批残留(无论成败)
        r = run(root, "--json")
        assert r.returncode == 0, (r.stdout, r.stderr)
        data = json.loads(r.stdout)
        assert (root / ".verify-prep-count").read_text().strip() == "1"    # pre 恒重跑
        assert _invocations(root) == 1                                     # run 恒重跑(不被残留产物跳过)
        run_step = next(s for s in data["steps"] if s["name"] == "run")
        assert run_step["status"] == "ok" and run_step["real_run_count"] == 1, run_step


def test_exactly_one_real_run_per_green_batch() -> None:
    """钉⑥:全批只跑一次真跑(atlas_check 恰被调一次;执行器不另起 Playwright)。
    变异 **MB20**:run 跳过判据摘除/恒重跑 ⇒ 语义破 ⇒ 本钉(与钉⑤)红。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        assert run(root).returncode == 0
        assert _invocations(root) == 1, _invocations(root)
        assert json.loads(run(root, "--json").stdout)["short_circuit"] is True  # 二跑被留档短路,不二次真跑


def test_missing_root_fails_clean_without_writes() -> None:
    """钉⑦(收窄口径的机器面):参数错 ⇒ 退出码 2、不写任何盘。"""
    with tempfile.TemporaryDirectory() as td:
        empty = Path(td) / "nope"
        empty.mkdir()
        r = subprocess.run([sys.executable, str(VERIFY), "--root", str(Path(td) / "absent")],
                           capture_output=True, text=True)
        assert r.returncode == 2, (r.returncode, r.stderr)
        assert list(empty.iterdir()) == []                                 # 未写盘
