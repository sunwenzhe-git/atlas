#!/usr/bin/env python3
"""`scripts/review_closure.py` 回归测试（D5 / RFC-20261031-02）。

夹具 = 报告目录：最新 `review.json` + `findings/<unit>.r<round>.json`。
覆盖：<2 轮 SKIP / carried / unaccounted WARN / resolves 取证 / 缺取证 /
pre_existing / Major intentional / Critical intentional / unknown resolves /
重复与坏形状 / 无指纹回退 / 单元文件错位 / 缺根报告。

变异证明：M1 摘掉 unaccounted 收集 ⇒ `test_unaccounted_warns` 红；
M2 把缺取证的 resolves 当已关闭 ⇒ `test_resolves_without_evidence_warns` 红；
M3 把 Critical 的 intentional/ignored 当关闭 ⇒ `test_critical_intentional_resolve_warns` 红。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "review_closure.py"


def finding(fp: str, *, level: str = "Critical", target: str = "a.py:1",
            with_fingerprint: bool = True, **kw) -> dict:
    item = {"id": "D1", "level": level, "check": "bug", "target": target,
            "detail": "问题", "rollback": "implement"}
    if with_fingerprint:
        item["fingerprint"] = fp
    item.update(kw)
    return item


def write_report(root: Path, rounds: dict[int, list[dict]], resolves=None,
                 unit: str = "U") -> Path:
    d = root / "report"
    (d / "findings").mkdir(parents=True, exist_ok=True)
    latest = max(rounds)
    for rnd, checks in rounds.items():
        (d / "findings" / f"{unit}.r{rnd}.json").write_text(
            json.dumps({"unit": unit, "round": rnd, "checks": checks, "other": []},
                       ensure_ascii=False), encoding="utf-8")
    data = {"unit": unit, "round": latest, "checks": rounds[latest], "other": []}
    if resolves is not None:
        data["resolves"] = resolves
    (d / "review.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return d


def run(d: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), "--dir", str(d)],
                          capture_output=True, text=True, timeout=120)


def closure(d: Path) -> dict:
    return json.loads((d / "closure.json").read_text(encoding="utf-8"))


def test_less_than_two_rounds_skips() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {1: [finding("A")]})
        p = run(d)
        assert p.returncode == 0 and "SKIP" in p.stdout, p.stdout
        assert closure(d)["status"] == "SKIP"


def test_carried_same_fingerprint_passes() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {1: [finding("A")], 2: [finding("A")]})
        p = run(d)
        assert p.returncode == 0 and "PASS" in p.stdout, p.stdout
        c = closure(d)
        assert c["status"] == "PASS" and len(c["carried"]) == 1 and c["unaccounted"] == []


def test_unaccounted_warns() -> None:
    """M1：上一轮 open Critical 在新一轮既未重报也未 resolves ⇒ WARN。"""
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {1: [finding("A")], 2: [finding("B")]})
        p = run(d)
        assert p.returncode == 0 and "WARN" in p.stdout, p.stdout
        c = closure(d)
        assert c["status"] == "WARN"
        assert [x["fingerprint"] for x in c["unaccounted"]] == ["A"]


def test_resolves_with_evidence_passes() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {1: [finding("A")], 2: [finding("B")]},
                         resolves=[{"fingerprint": "A", "status": "fixed",
                                    "by": "lead", "evidence": "test green"}])
        p = run(d)
        assert p.returncode == 0 and "PASS" in p.stdout, p.stdout
        c = closure(d)
        assert c["status"] == "PASS" and len(c["resolved"]) == 1


def test_resolves_without_evidence_warns() -> None:
    """M2：fixed/false_positive 缺签字/取证不得算关闭。"""
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {1: [finding("A")], 2: [finding("B")]},
                         resolves=[{"fingerprint": "A", "status": "fixed"}])
        p = run(d)
        assert p.returncode == 0 and "WARN" in p.stdout, p.stdout
        c = closure(d)
        assert "A" in c["invalid_resolves"] and c["unaccounted"]


def test_pre_existing_skipped() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {1: [finding("A", pre_existing=True)], 2: [finding("B")]})
        p = run(d)
        assert p.returncode == 0 and "PASS" in p.stdout, p.stdout
        assert closure(d)["prior_relevant"] == 0


def test_major_intentional_resolves_passes() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {1: [finding("A", level="Major")], 2: [finding("B")]},
                         resolves=[{"fingerprint": "A", "status": "intentional"}])
        p = run(d)
        assert p.returncode == 0 and "PASS" in p.stdout, p.stdout
        assert len(closure(d)["resolved"]) == 1


def test_critical_intentional_resolve_warns() -> None:
    """M3：Critical 不能靠 intentional/ignored 关闭。"""
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {1: [finding("A")], 2: [finding("B")]},
                         resolves=[{"fingerprint": "A", "status": "intentional"}])
        p = run(d)
        assert p.returncode == 0 and "WARN" in p.stdout, p.stdout
        c = closure(d)
        assert "A" in c["invalid_resolves"] and c["unaccounted"]


def test_unknown_resolves_warns() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {1: [finding("A")], 2: [finding("B")]},
                         resolves=[{"fingerprint": "X", "status": "fixed",
                                    "by": "lead", "evidence": "green"}])
        p = run(d)
        assert p.returncode == 0 and "WARN" in p.stdout, p.stdout
        assert closure(d)["unknown_resolves"] == ["X"]


def test_duplicate_resolves_fails() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {1: [finding("A")], 2: [finding("B")]},
                         resolves=[{"fingerprint": "A", "status": "fixed", "by": "l",
                                    "evidence": "e"},
                                   {"fingerprint": "A", "status": "fixed", "by": "l",
                                    "evidence": "e"}])
        p = run(d)
        assert p.returncode == 2 and "重复" in p.stderr


def test_malformed_resolves_fails() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {1: [finding("A")], 2: [finding("B")]}, resolves="x")
        p = run(d)
        assert p.returncode == 2 and "resolves" in p.stderr

        d2 = write_report(Path(td) / "r2", {1: [finding("A")], 2: [finding("B")]},
                          resolves=[{"fingerprint": "A", "status": "done"}])
        p2 = run(d2)
        assert p2.returncode == 2 and "status" in p2.stderr


def test_latest_reported_closed_with_evidence_resolves() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {
            1: [finding("A")],
            2: [finding("A", disposition="fixed", disposition_by="lead",
                        disposition_evidence="test green")],
        })
        p = run(d)
        assert p.returncode == 0 and "PASS" in p.stdout, p.stdout
        c = closure(d)
        assert len(c["resolved"]) == 1 and c["resolved"][0]["via"] == "re-reported"


def test_finding_without_fingerprint_uses_hash() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {
            1: [finding("", with_fingerprint=False)],
            2: [finding("", with_fingerprint=False)],
        })
        p = run(d)
        assert p.returncode == 0 and "PASS" in p.stdout, p.stdout
        assert len(closure(d)["carried"]) == 1


def test_unit_file_mismatch_fails() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {1: [finding("A")], 2: [finding("B")]})
        unit_file = d / "findings" / "U.r2.json"
        data = json.loads(unit_file.read_text(encoding="utf-8"))
        data["round"] = 1
        unit_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        p = run(d)
        assert p.returncode == 2 and "round" in p.stderr


def test_no_prior_unit_skips() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {2: [finding("A")]})
        p = run(d)
        assert p.returncode == 0 and "SKIP" in p.stdout, p.stdout


def test_missing_root_fails() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "report"
        (d / "findings").mkdir(parents=True)
        (d / "findings" / "U.r1.json").write_text("{}", encoding="utf-8")
        p = run(d)
        assert p.returncode == 2 and "review.json" in p.stderr
