#!/usr/bin/env python3
"""atlas_verify(验收执行器,RFC-20261025-02 v2 / D150;backfill 步 = 附录 B v2 / D151)十钉。

钉对应 RFC §4 ①–⑦ + 附录 B v2 ⑧–⑩;变异 **MB19**(摘「留档短路」⇒ 钉④红)/ **MB20**(摘「失败停环」⇒ 失败批被落档成 ok ⇒ 钉③红)/ **MB22**(回填退回内联改写、不走 `e2e_console.writeback` 同函数 ⇒ 钉⑧红)/ **MB23**(摘写后复检 ⇒ 撞窗不被检测 ⇒ 钉⑩红),四段协议含注入 diff、还原逐字节一致。

夹具:temp root + 假 `atlas-prepare.mjs`(node,记调用数/批级 ID/可注入失败)
+ 假 `.atlas/scripts/atlas_check.py`(记真跑调用数,可注入失败行/成功行/留证构件;
绿批输出 Playwright JSON 形态 results.json:①expected / ②skipped——供 backfill 解析)
+ 可选 `e2e-index.md` / `events.jsonl` 夹具(钉⑧⑨⑩)。"""
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
# 绿批:Playwright JSON 报告形态(suites[].specs[].tests[].status)——backfill 逐用例解析源
(run_dir / "results.json").write_text(_json.dumps({
    "stats": {"expected": 1, "unexpected": 0, "skipped": 1},
    "suites": [{"specs": [{"title": "E2E-A-001 点击后标题就绪", "tests": [{"status": "expected"}]}]},
               {"specs": [{"title": "E2E-A-002 点击后面板展开", "tests": [{"status": "skipped"}]}]}],
}, ensure_ascii=False))
(run_dir / "e2e-summary.json").write_text("{}")
print("  ok   assembly_version  源包与装配态一致")
print("  ok   e2e_real_run      11/11")
print("OK")
"""

# backfill 夹具:两条可回填行的索引(①red 待翻绿、②blocked 由 skipped 草稿豁免、③不在 results 故不动)
FAKE_INDEX = """# E2E 总索引

| 用例ID | 页面 | 中文标题 | 类型 | 关联AC | 需求 | 状态 | 状态原因 | 分片 |
|---|---|---|---|---|---|---|---|---|
| E2E-A-001 | home | 点击后标题就绪 | smoke | AC-A-001 | | red | | [cases/home.md](cases/home.md) |
| E2E-A-002 | home | 点击后面板展开 | smoke | AC-A-001 | | blocked | ENV_ISSUE：断网 | [cases/home.md](cases/home.md) |
| E2E-A-003 | home | 本批未执行 | smoke | AC-A-002 | | green | | [cases/home.md](cases/home.md) |

## 页面表(页 ↔ 路由 ↔ 实现状态)
"""

FAKE_LEDGER_EVENT = ('{"kind": "submit", "source": "app", "ts": "2026-10-26T10:00:00", "changed": 0, '
                     '"cases": {}, "prov": {"head_sha": "base000", "scripts_hash": "hash000", '
                     '"git_dirty": false, "actor_type": "human"}}')


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


# ---------------------------------------------------------------- 附录 B v2(D151)⑧⑨⑩

def make_index(root: Path) -> None:
    (root / "product" / "e2e").mkdir(parents=True, exist_ok=True)
    (root / "product/e2e/e2e-index.md").write_text(FAKE_INDEX, encoding="utf-8")


def make_ledger(root: Path) -> None:
    p = root / "product" / "e2e" / "reviews" / "console"
    p.mkdir(parents=True, exist_ok=True)
    (p / "events.jsonl").write_text(FAKE_LEDGER_EVENT + "\n", encoding="utf-8")


def _ledger_bytes(root: Path) -> bytes:
    return (root / "product/e2e/reviews/console/events.jsonl").read_bytes()


def _claim_residue(root: Path) -> list[str]:
    d = root / ".atlas" / "runs" / "write-claims"
    return sorted(p.name for p in d.glob("*.json")) if d.is_dir() else []


def test_backfill_reuses_console_writeback_identity() -> None:
    """钉⑧(B1 单一来源):回填走**装配态同目录**的 `e2e_console.writeback` 同一函数——
    模块解析 = scripts/ 兄弟文件;行为面 = 记录器证回填以 apply=True 调它(而非内联行改写)。
    变异 **MB22**:回填退回内联改写(绕开 console 函数)⇒ 本钉红。"""
    import sys as _sys
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        make_index(root)
        run_dir = root / "product/e2e/scripts/.atlas-run"      # seed 逐用例执行结果(单用例 expected)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "results.json").write_text(json.dumps(
            {"suites": [{"specs": [{"title": "E2E-A-001 点击后标题就绪", "tests": [{"status": "expected"}]}]}]},
            ensure_ascii=False), encoding="utf-8")
        console, claim_mod = load_verify()._import_console()
        assert Path(console.__file__).resolve() == (PKG_ROOT / "scripts" / "e2e_console.py").resolve()
        assert Path(claim_mod.__file__).resolve() == (PKG_ROOT / "scripts" / "write_claim.py").resolve()
        orig, calls = console.writeback, []
        console.writeback = lambda *a, **k: (calls.append(k.get("apply")), orig(*a, **k))[-1]
        try:
            assert load_verify().step_backfill(root).get("status") in {"ok", "SKIP"}
        finally:
            console.writeback = orig
        assert calls == [True], calls   # apply=True:落盘回填确实经由 console 同一函数


def test_backfill_never_touches_review_ledger() -> None:
    """钉⑨(B2 账本不进):全链绿批回填后 **events.jsonl 字节不变**;索引 ①red→green、
    blocked 行(skipped 草稿豁免)与不在 results 的行不动;留档含回填章(键集 = 改动集)
    + README 机器批声明行;claim 无残留。变异 **MB22** 同族连带：内联改写不产索引变化 ⇒ 本钉红。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        make_index(root)
        make_ledger(root)
        before = _ledger_bytes(root)
        r = run(root, "--json")
        assert r.returncode == 0, (r.stdout[-600:], r.stderr[-400:])
        assert _ledger_bytes(root) == before                      # 账本逐字节不变
        index = (root / "product/e2e/e2e-index.md").read_text(encoding="utf-8")
        row = next(l for l in index.splitlines() if l.startswith("| E2E-A-001"))
        assert "| green |" in row                                 # red → green
        b2 = next(l for l in index.splitlines() if l.startswith("| E2E-A-002"))
        assert "| blocked | ENV_ISSUE：断网 |" in b2              # skipped ⇒ 不入 draft,原样
        data = json.loads(r.stdout)
        bf = next(s for s in data["steps"] if s["name"] == "backfill")
        assert bf["status"] == "ok" and bf["backfill"]["cases"].keys() == {"E2E-A-001"}, bf
        readme = (root / data["archive"] / "README.md").read_text(encoding="utf-8")
        assert "执行器回填" in readme                              # 机器批声明(分辨面 = 留档)
        assert _claim_residue(root) == []                         # claim 已 release
        r2 = run(root, "--json")                                  # 留档短路批:backfill 不再跑
        assert json.loads(r2.stdout)["short_circuit"] is True


def test_backfill_concurrent_submit_reports_collision_and_fails() -> None:
    """钉⑩(B3 撞窗):回填窗口内账本被注入伪造人批 submit ⇒ 尾 submit 变化被抓到 ⇒
    exit 非 0 + 撞窗结构化报告(意图改动/写后现值) + **不落档**;claim 无残留。
    变异 **MB23**:摘写后复检 ⇒ 撞窗被吞 ⇒ 本钉红。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        make_index(root)
        make_ledger(root)
        mod = load_verify()
        console, _ = mod._import_console()
        orig = console.writeback

        def inject_then_writeback(*a, **k):
            # 竞写窗内:人批 submit 在「基线读取之后、写索引之前」顶掉尾 submit(时点家族)
            d = root / "product/e2e/reviews/console/events.jsonl"
            with d.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"kind": "submit", "source": "app", "ts": "2026-10-26T12:00:00",
                                     "changed": 2, "cases": {"E2E-A-003": {"ok": True}},
                                     "prov": {"head_sha": "human999", "scripts_hash": "hash999",
                                              "git_dirty": True, "actor_type": "human"}},
                                    ensure_ascii=False) + "\n")
            return orig(*a, **k)

        console.writeback = inject_then_writeback
        try:
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = mod.main(["--root", str(root), "--json"])
        finally:
            console.writeback = orig
        assert code == 1, buf.getvalue()
        data = json.loads(buf.getvalue())
        assert data["failed_step"] == "backfill" and data["archive"] is None, data
        assert "撞窗" in data["steps"][-1]["detail"] and "console 重提交" in data["steps"][-1]["detail"]
        rows_after = data["steps"][-1].get("backfill", {}).get("rows_after", [])
        assert any(m["id"] == "E2E-A-001" and m["intended"] == {"状态": "green"} for m in rows_after), rows_after
        assert _claim_residue(root) == []
