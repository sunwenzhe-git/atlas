#!/usr/bin/env python3
"""atlas_verify(验收执行器,RFC-20261025-02 v2 / D150;backfill 步 = 附录 B v2 / D151)十钉。

钉对应 RFC §4 ①–⑦ + 附录 B v2 ⑧–⑩;变异 **MB19**(摘「留档短路」⇒ 钉④红)/ **MB20**(摘「失败停环」⇒ 失败批被落档成 ok ⇒ 钉③红)/ **MB22**(回填退回内联改写、不走 `e2e_console.writeback` 同函数 ⇒ 钉⑧红)/ **MB23**(摘写后复检 ⇒ 撞窗不被检测 ⇒ 钉⑩红),四段协议含注入 diff、还原逐字节一致。

夹具:temp root + 假 `atlas-prepare.mjs`(node,记调用数/批级 ID/可注入失败)
+ 假 `.atlas/scripts/atlas_check.py`(记真跑调用数,可注入失败行/成功行/留证构件;
绿批输出 Playwright JSON 形态 results.json:①expected / ②skipped——供 backfill 解析)
+ 可选 `e2e-index.md` / `events.jsonl` 夹具(钉⑧⑨⑩)。"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
VERIFY = PKG_ROOT / "scripts" / "atlas_verify.py"


def _load_verify():
    spec = importlib.util.spec_from_file_location("atlas_verify", VERIFY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_parse_rows_accepts_na() -> None:
    """D153：atlas_check 的整门 N/A 行不得在执行器留档中消失。"""
    mod = _load_verify()
    rows = mod._parse_rows("N/A validate_adr 不适用\nok foo PASS\n")
    assert rows[0]["status"] == "N/A", rows
    assert rows[0]["name"] == "validate_adr"

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
    (run_dir / "test-failed-1.png").write_bytes(b"fake-png")
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


# ── RFC-20261104-01 S1：证据归档（失败留证 / trace 轴 / 归档器安全） ─────────

def _evidence_mod():
    spec = importlib.util.spec_from_file_location(
        "evidence_archive_under_test", PKG_ROOT / "_support" / "evidence_archive.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _manifests(root: Path) -> list[Path]:
    return sorted((root / ".atlas-evidence").glob("*/manifest.json"))


def test_failed_batch_archives_evidence() -> None:
    """S1 钉：失败批必须落 `.atlas-evidence/<id>-fail/`，含 trace + png，且判定不变（exit 1）。

    变异 M177（摘 `_fail` 归档调用）⇒ 本钉红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        (root / ".verify-check-mode").write_text("fail", encoding="utf-8")
        proc = run(root, "--json")
        assert proc.returncode == 1, proc.stdout + proc.stderr
        ms = _manifests(root)
        assert ms, "失败批未归档"
        d = json.loads(ms[0].read_text(encoding="utf-8"))
        names = {Path(f["path"]).name for f in d["files"]}
        assert {"trace.zip", "test-failed-1.png"} <= names, names
        assert d.get("verdict") == "fail", d


def test_forged_manifest_is_not_consumed_by_verify() -> None:
    """S1 钉：verify 判定不读归档 manifest——伪造 `verdict=pass` 不得让失败批变绿。

    变异 M178（把 manifest 判定读回报告）⇒ 本钉红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        (root / ".verify-check-mode").write_text("fail", encoding="utf-8")
        assert run(root).returncode == 1
        m = _manifests(root)[0]
        d = json.loads(m.read_text(encoding="utf-8"))
        d["verdict"] = "pass"
        m.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        assert run(root).returncode == 1


def test_pre_run_archives_legacy_atlas_run() -> None:
    """S1 钉（S1-19）：起跑前归档上一批遗留证据（Playwright 起跑即清空 `.atlas-run`）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make(root)
        legacy = root / "product/e2e/scripts/.atlas-run"
        legacy.mkdir(parents=True)
        (legacy / "trace.zip").write_bytes(b"legacy-trace")
        assert run(root).returncode == 0
        ms = _manifests(root)
        assert any("-pre/" + p.name == "-pre/manifest.json" or "-pre" in p.parent.name for p in ms), ms
        pre = [p for p in ms if "-pre" in p.parent.name]
        assert pre, [p.parent.name for p in ms]
        d = json.loads(pre[0].read_text(encoding="utf-8"))
        assert [Path(f["path"]).name for f in d["files"]] == ["trace.zip"]


def test_trace_off_is_na_but_archive_still_passes() -> None:
    """B4：`trace_enabled=False ⇒ N/A` 不得抹掉 PNG 归档的 PASS（两轴分开判）。"""
    ev = _evidence_mod()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        run_dir = root / "product/e2e/scripts/.atlas-run"
        run_dir.mkdir(parents=True)
        (run_dir / "test-failed-1.png").write_bytes(b"png")
        out = ev.archive_run_artifacts(
            root, source="t", phase="fail", run_dir=run_dir,
            trace_policy={"E2E-X": {"request_assertion": True}},
            failed_cases=["E2E-X"], request_trace=False)
        assert out["status"] == "PASS", out
        assert out["trace"]["status"] == "N/A", out["trace"]


def test_unknown_trace_policy_is_warn_never_na() -> None:
    """B4：策略未知 ⇒ WARN，不得 N/A（假绿来源）。"""
    ev = _evidence_mod()
    out = ev.trace_axis(None, ["E2E-X"], trace_present=False)
    assert out["status"] == "WARN", out


def test_archive_failure_is_warn_not_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """S1 钉：归档器自身失败 ⇒ WARN / partial，**不改判定**（调用方仍 exit 1）。"""
    ev = _evidence_mod()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        run_dir = root / "product/e2e/scripts/.atlas-run"
        run_dir.mkdir(parents=True)
        (run_dir / "trace.zip").write_bytes(b"t")

        def boom(*_a, **_k):
            raise OSError("注入复制失败")

        monkeypatch.setattr(ev.shutil, "copyfile", boom)
        out = ev.archive_run_artifacts(root, source="t", phase="fail", run_dir=run_dir)
        assert out["status"] == "WARN", out
        assert out["partial"] is True


def test_archive_symlink_escape_refused() -> None:
    """S1 钉：`.atlas-evidence` 解析到根外 ⇒ 拒绝写入、落 WARN。"""
    ev = _evidence_mod()
    with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as outside:
        root = Path(td) / "repo"
        (root / "product/e2e/scripts/.atlas-run").mkdir(parents=True)
        (root / "product/e2e/scripts/.atlas-run/trace.zip").write_bytes(b"t")
        (root / ".atlas-evidence").symlink_to(Path(outside))
        out = ev.archive_run_artifacts(root, source="t", phase="fail")
        assert out["status"] == "WARN", out
        assert not list(Path(outside).glob("*")), "越界目录被写入"


@pytest.mark.parametrize("kill_mode", ["plain", "soft-kill"])
def test_archived_trace_is_independently_consumable(kill_mode: str) -> None:
    """S1 钉（S1-20a）：归档后删 `.atlas-run` 仍可打开 zip + sha256 自洽。

    两种夹具：plain / soft-kill（模拟 SIGTERM 后 flush）。变异 M180 / M186 会让
    对应路径拿不到完整归档 ⇒ 本钉红。
    """
    ev = _evidence_mod()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        run_dir = root / "product/e2e/scripts/.atlas-run"
        run_dir.mkdir(parents=True)
        real_zip = run_dir / "trace.zip"
        with zipfile.ZipFile(real_zip, "w") as zf:
            zf.writestr("trace/0.trace", f"mode={kill_mode}".encode())
        out = ev.archive_run_artifacts(root, source="t", phase="fail", run_dir=run_dir)
        trace_entry = next(f for f in out["files"] if Path(f["path"]).name == "trace.zip")
        import shutil as _sh
        _sh.rmtree(run_dir)
        archived = root / trace_entry["path"]
        assert archived.is_file(), archived
        with zipfile.ZipFile(archived) as zf:
            assert zf.namelist(), "trace.zip 不可独立打开"
        assert hashlib.sha256(archived.read_bytes()).hexdigest() == trace_entry["sha256"]


def test_archive_is_idempotent_and_never_overwrites() -> None:
    """S1 钉（S1-21）：两次归档 = 两份并存；第一份字节不变。"""
    ev = _evidence_mod()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        run_dir = root / "product/e2e/scripts/.atlas-run"
        run_dir.mkdir(parents=True)
        (run_dir / "trace.zip").write_bytes(b"t1")
        first = ev.archive_run_artifacts(root, source="t", phase="fail", run_dir=run_dir)
        first_manifest = (root / first["dir"] / "manifest.json").read_bytes()
        second = ev.archive_run_artifacts(root, source="t", phase="fail", run_dir=run_dir)
        assert first["dir"] != second["dir"]
        assert (root / first["dir"] / "manifest.json").read_bytes() == first_manifest


def test_global_teardown_absent_in_legacy_projects() -> None:
    """P12 钉（兼容性姿态）：旧生成器产物没有 teardown / 政策清单 ⇒ 不阻断、不报错。

    同时钉住 teardown 的语义：post-run manifest **无 `verdict` 字段**（只复制不判定）。
    这条接近恒真，只作兼容性姿态，不计入有效反钉数量。
    """
    ev_path = PKG_ROOT / "_support" / "evidence_archive.py"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        run_dir = root / "product/e2e/scripts/.atlas-run"
        run_dir.mkdir(parents=True)
        (run_dir / "trace.zip").write_bytes(b"legacy")
        proc = subprocess.run([sys.executable, str(ev_path), "--phase", "post-run",
                               "--root", str(root), "--run-dir", str(run_dir)],
                              capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        m = _manifests(root)[0]
        d = json.loads(m.read_text(encoding="utf-8"))
        assert "verdict" not in d, d


def test_archive_cli_never_exits_nonzero() -> None:
    """P12/S1 钉：teardown 载体（CLI）遇到异常也只 WARN、退出码 0。"""
    ev_path = PKG_ROOT / "_support" / "evidence_archive.py"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        run_dir = root / "product/e2e/scripts/.atlas-run"
        run_dir.mkdir(parents=True)
        (run_dir / "trace.zip").write_bytes(b"t")
        (root / ".atlas-evidence").write_text("not a dir", encoding="utf-8")
        proc = subprocess.run([sys.executable, str(ev_path), "--phase", "post-run",
                               "--root", str(root), "--run-dir", str(run_dir)],
                              capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "WARN" in proc.stderr, proc.stderr
