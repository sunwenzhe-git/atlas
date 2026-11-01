#!/usr/bin/env python3
"""`scripts/review_closure.py` 回归测试（D5 / RFC-20261031-02）。

夹具 = 报告目录：最新 `review.json` + `findings/<unit>.r<round>.json`。
覆盖：<2 轮 SKIP / carried / unaccounted WARN / resolves 取证 / 缺取证 /
pre_existing / Major intentional / Critical intentional / unknown resolves /
重复与坏形状 / 无指纹回退 / 单元文件错位 / 缺根报告 / prior Critical 降级 /
孤儿单元文件 / **中间轮关闭跨轮持久**（resolves@rN、re-reported-closed@rN、
更晚又 open 作废、轮次倒挂不作数、缺取证不作数、Critical intentional 不作数、
冗余声明进 warnings）/ **--emit-skeleton 义务骨架**。

变异证明（编号属本文件）：M1 摘掉 unaccounted 收集 ⇒ `test_unaccounted_warns` 红；
M2 把缺取证的 resolves 当已关闭 ⇒ `test_resolves_without_evidence_warns` 红；
M3 把 Critical 的 intentional/ignored 当关闭 ⇒ `test_critical_intentional_resolve_warns` 红；
M4 关闭判定改回按新一轮级别 ⇒ `test_prior_critical_downgraded_is_not_closed` 红；
M5 孤儿文件重新静默跳过 ⇒ `test_orphan_unit_file_warns` 红；
M6 只认最新轮证据（摘掉中间轮）⇒ `test_intermediate_resolves_persists_to_later_rounds` 等三条红；
M7 去掉「最后一次证据」判据（轮次单调与 open 重置失效）⇒ 重置与倒挂两条红；
M8 骨架不写文件 ⇒ `test_emit_skeleton_lists_unaccounted` 红；
M9 级别退回「义务侧覆盖本轮级别」⇒ `test_escalated_obligation_still_requires_signature` 红
   （`Major` 在中间轮升为 `Critical` + 无签字 `intentional` 不得算已关；正例对照
   `test_escalation_widening_keeps_legitimate_closure` 保证不刷红正常收口）；
M10 中间轮坏形状退回 exit 2 ⇒ `test_intermediate_declare_bad_shape_warns_not_blocks` 等三条红
   （`(unit, round)` 文件不得覆盖 ⇒ 钉死历史就永久跑不动）；
M11 级别加宽只读 `relevant()` 放行的条目 ⇒ 两条 `pre_existing_escalation_*` 红
   （升级那一轮标 `pre_existing` 就跳过加宽 ⇒ 声明侧与重报侧都能免签关掉；第二轮评审的残留方向）；
M12 `worst_level` 不做 `isinstance` 防护 ⇒ `test_broken_level_does_not_crash_the_ledger` 红
   （历史 `level` 为 list/dict 时抛裸 traceback、退出码 1，违背「只有 0 与 2」）；
M13 最新轮同指纹 open+closed 混排按 `any(closed)` 放行 ⇒ `test_open_and_closed_twin_in_latest_round_carries` 红
   （与中间轮口径不一致，且形态门的去重排除了 fixed 条目、不会替它出声）。
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
                 unit: str = "U", declares: dict[int, list[dict]] | None = None) -> Path:
    d = root / "report"
    (d / "findings").mkdir(parents=True, exist_ok=True)
    latest = max(rounds)
    for rnd, checks in rounds.items():
        data = {"unit": unit, "round": rnd, "checks": checks, "other": []}
        if declares and rnd in declares:
            data["resolves"] = declares[rnd]
        (d / "findings" / f"{unit}.r{rnd}.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8")
    data = {"unit": unit, "round": latest, "checks": rounds[latest], "other": []}
    if resolves is not None:
        data["resolves"] = resolves
    (d / "review.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return d


def run(d: Path, extra: list[str] | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCRIPT), "--dir", str(d)] + (extra or [])
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


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


def test_prior_critical_downgraded_is_not_closed() -> None:
    """M4：关闭与否按**上一轮级别**判 ⇒ prior Critical 降级成 Major 挂 intentional（无签字）不算关闭。"""
    with tempfile.TemporaryDirectory() as td:
        # 变体一：降级 + intentional（无 disposition_by / evidence）
        d = write_report(Path(td), {
            1: [finding("A")],
            2: [finding("A", level="Major", disposition="intentional")],
        })
        p = run(d)
        assert p.returncode == 0 and "WARN" in p.stdout, p.stdout
        c = closure(d)
        assert c["status"] == "WARN" and c["resolved"] == []
        assert len(c["carried"]) == 1 and len(c["level_downgraded"]) == 1
        assert "降级" in "".join(c["warnings"])

        # 变体二：仅降级、仍 open ⇒ 仍按未关闭跟踪并 WARN
        d2 = write_report(Path(td) / "r2", {
            1: [finding("A")],
            2: [finding("A", level="Major")],
        })
        p2 = run(d2)
        assert p2.returncode == 0 and "WARN" in p2.stdout, p2.stdout
        c2 = closure(d2)
        assert c2["status"] == "WARN" and len(c2["carried"]) == 1
        assert c2["level_downgraded"][0]["latest_level"] == "Major"


def test_prior_critical_rereported_as_critical_passes() -> None:
    """正例对照：级别未变且仍 open ⇒ carried、PASS（不得把正常重报刷红）。"""
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {1: [finding("A")], 2: [finding("A")]})
        p = run(d)
        assert p.returncode == 0 and "PASS" in p.stdout, p.stdout
        assert closure(d)["level_downgraded"] == []


def test_orphan_unit_file_warns() -> None:
    """M5：`findings/` 里的非本 unit 文件不得静默跳过 ⇒ 闭环义务凭空清零要可见。"""
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {2: [finding("B")]})
        (d / "findings" / "OTHER-REQ.r1.json").write_text(
            json.dumps({"unit": "OTHER-REQ", "round": 1, "checks": [finding("A")]},
                       ensure_ascii=False), encoding="utf-8")
        p = run(d)
        assert p.returncode == 0 and "WARN" in p.stdout, p.stdout
        c = closure(d)
        assert c["status"] == "WARN" and len(c["warnings"]) == 1
        assert "OTHER-REQ.r1.json" in c["warnings"][0]


# ── 2026-11-01 RFC-20261101-02 D5-a：跨轮关闭持久化 ────────────────────────────────
def fixed_decl(fp: str, **kw) -> dict:
    entry = {"fingerprint": fp, "status": "fixed", "by": "lead", "evidence": "test green"}
    entry.update(kw)
    return entry


def test_intermediate_resolves_persists_to_later_rounds() -> None:
    """M6：中间轮正式关闭的项，后续轮不得再要求交代（关闭是历史事实，不靠每轮重贴）。"""
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {1: [finding("A", level="Major")], 2: [], 3: [finding("B")]},
                         declares={2: [fixed_decl("A")]})
        p = run(d)
        assert p.returncode == 0 and "PASS" in p.stdout, p.stdout
        c = closure(d)
        assert c["status"] == "PASS" and c["unaccounted"] == []
        assert len(c["resolved"]) == 1
        assert c["resolved"][0]["via"] == "resolves@r2"
        assert c["resolved"][0]["declared_in_round"] == 2


def test_intermediate_rereported_closure_persists() -> None:
    """中间轮同指纹重报并带签字取证关闭 ⇒ 同样算历史事实（via=re-reported-closed@rN）。"""
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {
            1: [finding("A", level="Major")],
            2: [finding("A", level="Major", disposition="fixed", disposition_by="lead",
                        disposition_evidence="green")],
            3: [finding("B")],
        })
        p = run(d)
        assert p.returncode == 0 and "PASS" in p.stdout, p.stdout
        c = closure(d)
        assert c["resolved"][0]["via"] == "re-reported-closed@r2"


def test_reopen_after_intermediate_close_is_unaccounted() -> None:
    """M7：关过之后更晚一轮又 open ⇒ 早先关闭不作数（重置回未交代）。"""
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {
            1: [finding("A", level="Major")], 2: [],
            3: [finding("A", level="Major")], 4: [finding("B")],
        }, declares={2: [fixed_decl("A")]})
        p = run(d)
        assert p.returncode == 0 and "WARN" in p.stdout, p.stdout
        c = closure(d)
        assert [u["fingerprint"] for u in c["unaccounted"]] == ["A"]


def test_declare_earlier_than_obligation_does_not_count() -> None:
    """M7：轮次单调 —— r1 的声明关不掉 r2 才出现的义务。"""
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {1: [], 2: [finding("A", level="Major")], 3: [finding("B")]},
                         declares={1: [fixed_decl("A")]})
        p = run(d)
        assert p.returncode == 0 and "WARN" in p.stdout, p.stdout
        assert [u["fingerprint"] for u in closure(d)["unaccounted"]] == ["A"]


def test_intermediate_close_without_evidence_does_not_count() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {1: [finding("A", level="Major")], 2: [], 3: [finding("B")]},
                         declares={2: [{"fingerprint": "A", "status": "fixed"}]})
        p = run(d)
        assert p.returncode == 0 and "WARN" in p.stdout, p.stdout
        assert [u["fingerprint"] for u in closure(d)["unaccounted"]] == ["A"]


def test_intermediate_critical_intentional_does_not_count() -> None:
    """Critical 不因中间轮的 intentional/ignored 而关闭（与最新轮同一判据）。"""
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {1: [finding("A")], 2: [], 3: [finding("B")]},
                         declares={2: [{"fingerprint": "A", "status": "intentional"}]})
        p = run(d)
        assert p.returncode == 0 and "WARN" in p.stdout, p.stdout
        assert [u["fingerprint"] for u in closure(d)["unaccounted"]] == ["A"]


def test_stale_intermediate_declare_warns_but_not_loudly() -> None:
    """匹配不到义务的历史声明进 warnings（可见），但不额外抬状态。"""
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {1: [finding("A", level="Major")], 2: [], 3: [finding("B")]},
                         declares={2: [fixed_decl("A"), fixed_decl("GHOST")]})
        p = run(d)
        assert p.returncode == 0 and "PASS" in p.stdout, p.stdout
        c = closure(d)
        assert c["status"] == "PASS" and len(c["warnings"]) == 1
        assert "GHOST" in c["warnings"][0]


def test_intermediate_declare_bad_shape_warns_not_blocks() -> None:
    """S1：中间轮坏形状不 exit 2 —— `(unit, round)` 文件不得覆盖，钉死历史就永久跑不动。"""
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {1: [finding("A", level="Major")], 2: [], 3: [finding("B")]},
                         declares={2: [{"fingerprint": "A", "status": "done"}]})
        p = run(d)
        assert p.returncode == 0, p.stdout + p.stderr
        c = closure(d)
        assert c["status"] == "WARN" and any("形状错" in w for w in c["warnings"])
        assert [x["fingerprint"] for x in c["unaccounted"]] == ["A"]


def test_emit_skeleton_lists_unaccounted() -> None:
    """M8：义务骨架 —— 指纹/轮次/定位预填，status/by/evidence 待填。"""
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {1: [finding("A", level="Major")], 2: [finding("B")]})
        out = Path(td) / "skeleton.json"
        p = run(d, ["--emit-skeleton", str(out)])
        assert p.returncode == 0 and "骨架" in p.stdout, p.stdout
        sk = json.loads(out.read_text(encoding="utf-8"))
        assert sk["by"] == "" and len(sk["resolves"]) == 1
        entry = sk["resolves"][0]
        assert entry["fingerprint"] == "A" and entry["status"] == ""
        assert entry["prior_round"] == 1 and entry["target"]
        assert entry["by"] == "" and entry["evidence"] == ""


def test_escalated_obligation_still_requires_signature() -> None:
    """M9：义务级别取所有出现里最严的一档 —— Major 升级为 Critical 后不得无签字关闭。

    方向与 M4 相反：M4 挡「Critical 降级成 Major + intentional」，本条挡
    「同指纹在中间轮被升成 Critical，再挂 intentional（无 by / 无取证）」。
    """
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {
            1: [finding("F1", level="Major")],
            2: [finding("F1", level="Critical", pre_existing=True, disposition="intentional")],
            3: [finding("F2")],
        })
        p = run(d)
        assert p.returncode == 0 and "WARN" in p.stdout, p.stdout
        c = closure(d)
        assert [x["fingerprint"] for x in c["unaccounted"]] == ["F1"]
        assert c["resolved"] == []


def test_escalation_widening_keeps_legitimate_closure() -> None:
    """正例对照：升级后的 Critical 只要带签字取证，仍然算关闭（不得把正常收口刷红）。"""
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {
            1: [finding("F1", level="Major")],
            2: [finding("F1", level="Critical", disposition="fixed",
                        disposition_by="lead", disposition_evidence="green")],
            3: [finding("F2")],
        })
        p = run(d)
        assert p.returncode == 0 and "PASS" in p.stdout, p.stdout
        assert closure(d)["resolved"][0]["via"] == "re-reported-closed@r2"


def test_pre_existing_escalation_still_widens_level() -> None:
    """M11：升级那一轮顺手标 `pre_existing` 也必须把义务级别加宽。

    加宽此前挂在 `relevant()` 之后 ⇒ `pre_existing=True` 直接跳过，义务仍按陈旧 Major 判，
    最新轮一条无签字无取证的 `intentional` 声明就能把它算成已关（评审打出的残留方向）。
    """
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {
            1: [finding("F1", level="Major")],
            2: [finding("F1", level="Critical", pre_existing=True)],
            3: [finding("F2", level="Major")],
        }, resolves=[{"fingerprint": "F1", "status": "intentional"}])
        p = run(d)
        assert p.returncode == 0 and "WARN" in p.stdout, p.stdout
        c = closure(d)
        assert [x["fingerprint"] for x in c["unaccounted"]] == ["F1"]
        assert "F1" in c["invalid_resolves"] and c["resolved"] == []


def test_pre_existing_escalation_blocks_rereported_laundering() -> None:
    """同方向的另一条路径：最新轮把升级后的条目降成 Major + `intentional` 重报。"""
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {
            1: [finding("F1", level="Major")],
            2: [finding("F1", level="Critical", pre_existing=True)],
            3: [finding("F1", level="Major", disposition="intentional")],
        })
        p = run(d)
        assert p.returncode == 0 and "WARN" in p.stdout, p.stdout
        c = closure(d)
        assert c["resolved"] == [] and [x["fingerprint"] for x in c["carried"]] == ["F1"]


def test_broken_level_does_not_crash_the_ledger() -> None:
    """M12：历史里 `level` 是 list / dict（不可哈希）不得抛裸 traceback。

    本族脚本退出码只有 0 与 2；损坏条目按「不认识的一侧不参与加严」处理，
    仍要给出义务判定，而不是把工具打死（与 S1 同族：历史不得钉死工具）。
    """
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {
            1: [finding("F1", level="Major")],
            2: [finding("F1", level=["Critical"])],           # 形态损坏的升级尝试
            3: [finding("F2", level="Major")],
        }, resolves=[{"fingerprint": "F1", "status": "fixed", "by": "lead", "evidence": "e"}])
        p = run(d)
        assert p.returncode == 0, p.stdout + p.stderr
        c = closure(d)
        assert c["status"] == "PASS" and c["resolved"][0]["via"] == "resolves"


def test_open_and_closed_twin_in_latest_round_carries() -> None:
    """M13：同一指纹在最新轮同时出现 open 与已关闭条目 ⇒ 按未关闭跟踪并出声。

    否则 `any(closed)` 会把它算成 resolved，而同样形态在中间轮是被拒的（口径不一致）。
    """
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {
            1: [finding("F1", level="Major")],
            2: [finding("F1", level="Major"),
                finding("F1", level="Major", disposition="fixed",
                        disposition_by="lead", disposition_evidence="e")],
        })
        p = run(d)
        assert p.returncode == 0 and "WARN" in p.stdout, p.stdout
        c = closure(d)
        assert c["resolved"] == [] and [x["fingerprint"] for x in c["carried"]] == ["F1"]
        assert any("形态矛盾" in w for w in c["warnings"])


def test_non_ascii_round_suffix_becomes_orphan_not_crash() -> None:
    """M14：轮次后缀只认纯 ASCII 数字。

    `isdigit()` 对上标 `²` 为真但 `int()` 抛 ValueError ⇒ 裸 traceback、退出码 1（本器只允许 0/2）；
    对全角 `２` 为真且 `int()` 成功 ⇒ 会被静默当成 round 2 甚至充当关闭证据。
    两者都必须落到「孤儿文件」这条响亮路径上。
    """
    for suffix, label in (("²", "上标"), ("２", "全角")):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "report"
            (d / "findings").mkdir(parents=True)
            (d / "findings" / "U.r1.json").write_text(json.dumps(
                {"unit": "U", "round": 1, "other": [],
                 "checks": [finding("A", level="Major")]}, ensure_ascii=False), encoding="utf-8")
            (d / "findings" / f"U.r{suffix}.json").write_text(
                json.dumps({"unit": "U", "round": 2, "other": [], "checks": []}), encoding="utf-8")
            (d / "review.json").write_text(json.dumps(
                {"unit": "U", "round": 3, "other": [], "checks": []}, ensure_ascii=False),
                encoding="utf-8")
            p = run(d)
            assert p.returncode == 0, f"{label}: rc={p.returncode} {p.stdout}{p.stderr}"
            c = closure(d)
            assert c["status"] == "WARN", f"{label}: {c}"
            assert f"U.r{suffix}.json" in "".join(c["warnings"]), (label, c["warnings"])
            assert [x["fingerprint"] for x in c["unaccounted"]] == ["A"], (label, c)


def test_unwritable_report_dir_exits_2_not_traceback() -> None:
    """R-2：`closure.json` 写不出去 ⇒ 响亮 exit 2，不抛裸 PermissionError（退出码只有 0 与 2）。"""
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {1: [finding("A", level="Major")], 2: [finding("B")]})
        (d / "closure.json").mkdir()          # 与属主无关的确定性写失败
        p = run(d)
        assert p.returncode == 2, p.stdout + p.stderr
        assert "closure.json" in p.stderr, p.stderr


def test_declared_round_mismatch_is_audible() -> None:
    """R-3：`resolves[].round` 不是死字段 —— 与义务所在轮不一致时出声（判定仍按文件轮次）。"""
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {1: [finding("A", level="Major")], 2: [finding("B")]},
                         resolves=[{"fingerprint": "A", "status": "fixed", "by": "lead",
                                    "evidence": "green", "round": 7}])
        p = run(d)
        assert p.returncode == 0, p.stdout + p.stderr
        c = closure(d)
        assert c["status"] == "PASS" and len(c["resolved"]) == 1   # 关闭仍成立
        assert any("round=7" in w and "不一致" in w for w in c["warnings"]), c["warnings"]


def test_numeric_signature_does_not_close() -> None:
    """M17：`disposition_by: 123` + `disposition_evidence: ["x"]` 不是签字。

    这两处此前经 `str()` 判「非空」即算带取证关闭 —— 承重件（谁签的、凭什么关）不能给数字/数组面子。
    """
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {
            1: [finding("A", level="Critical")],
            2: [finding("A", level="Critical", disposition="false_positive",
                        disposition_by=123, disposition_evidence=["外层网关已校验"])],
        })
        p = run(d)
        assert p.returncode == 0, p.stdout + p.stderr
        c = closure(d)
        # 数字签名不算关闭 ⇒ 回到 carried（仍可见，按设计不抬 WARN）；resolved 必须为空
        assert c["resolved"] == [] and [x["fingerprint"] for x in c["carried"]] == ["A"]


def test_resolves_entry_still_needs_string_signer() -> None:
    """同方向在声明侧：`resolves[].by` 是数字 ⇒ 该条不算关闭（形状层已拒，见转换器用例）。"""
    with tempfile.TemporaryDirectory() as td:
        d = write_report(Path(td), {1: [finding("A", level="Critical")], 2: [finding("B")]},
                         resolves=[{"fingerprint": "A", "status": "false_positive",
                                    "by": "lead", "evidence": "e"}])
        p = run(d)
        assert p.returncode == 0 and "PASS" in p.stdout, p.stdout
        assert closure(d)["resolved"][0]["status"] == "false_positive"
