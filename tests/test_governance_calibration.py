"""RFC-20261125-01 P5 classification, metrics and calibration counterexamples.

M251 mutates the auto-accept threshold conjunction in
_support/classification_contract.py. The real four-stage evidence is stored at
.atlas/runs/mutation-proof/M251.txt.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from _support.classification_contract import (  # noqa: E402
    ClassificationError,
    DEFAULT_THRESHOLDS,
    build_classification_corpora,
    classify_record,
    evaluate_classification,
    load_frozen_heldout,
    select_thresholds,
    verify_heldout,
)
from _support.governance_metrics import compute_metrics, percentile  # noqa: E402
from scripts.atlas_calibrate import calibrate  # noqa: E402
from validators.validate_calibration import validate_calibration  # noqa: E402


def candidates(top1="initial", score=0.99, top2="change", score2=0.01):
    return [
        {"type": top1, "score": score, "evidence": ["fixture-top1"]},
        {"type": top2, "score": score2, "evidence": ["fixture-top2"]},
    ]


def write_json(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def prediction_rows(samples, *, good=True):
    rows = {}
    for sample in samples:
        expected = sample["expected"]
        if expected == "abstain":
            scores = [0.50, 0.40] if good else [0.99, 0.01]
        elif good:
            top2 = "change" if expected != "change" else "initial"
            rows[sample["id"]] = {
                "scorer_version": "fixture-scorer@1",
                "candidates": candidates(expected, 0.99, top2, 0.01),
            }
            continue
        scores = [0.99, 0.01] if not good else [0.50, 0.40]
        rows[sample["id"]] = {
            "scorer_version": "fixture-scorer@1",
            "candidates": candidates("initial", scores[0], "change", scores[1]),
        }
    return rows


def prediction_file(path: Path, split: str, samples, *, good=True) -> Path:
    rows = prediction_rows(samples, good=good)
    return write_json(path, {
        "split": split,
        "scorer_version": "fixture-scorer@1",
        "samples": [{"id": sample["id"], **rows[sample["id"]]} for sample in samples],
    })


@pytest.mark.parametrize("score,margin,accepted", [
    (0.90, 0.15, True),
    (0.90, 0.149999, False),
    (0.899999, 0.20, False),
    (1.00, 0.15, True),
])
def test_m251_threshold_boundaries_are_inclusive(score, margin, accepted):
    result = classify_record({"text": "fixture"}, lambda _: {
        "scorer_version": "fixture@1",
        "candidates": candidates(score=score, score2=round(score - margin, 6)),
    })
    assert (result["decision"] == "auto") is accepted
    assert result["verdict"] == ("PASS" if accepted else "UNVERIFIED")
    assert result["rc"] == (0 if accepted else 2)


def test_top1_top2_margin_and_evidence_are_sorted_and_traced():
    raw = [
        {"type": "bug", "score": 0.10, "evidence": ["third"]},
        {"type": "change", "score": 0.20, "evidence": ["second"]},
        {"type": "initial", "score": 0.90, "evidence": ["first"]},
    ]
    result = classify_record({"text": "private business body"}, lambda _: {
        "scorer_version": "scorer@abc", "candidates": raw,
    })
    assert result["top1"] == "initial" and result["top2"] == "change"
    assert result["score"] == 0.90 and result["top2_score"] == 0.20
    assert result["margin"] == pytest.approx(0.70)
    assert result["evidence"] == ["first"] and result["scorer_version"] == "scorer@abc"
    assert result["decision"] == "auto" and result["type"] == "initial"
    assert "private business body" not in json.dumps(result)


def test_auto_requires_non_empty_top1_evidence():
    result = classify_record({"text": "fixture"}, lambda _: {
        "scorer_version": "fixture@1", "candidates": [
            {"type": "initial", "score": 0.99, "evidence": []},
            {"type": "change", "score": 0.01, "evidence": ["e"]},
        ]})
    assert result["decision"] == "abstain" and result["rc"] == 2
    assert any(item["reason"] == "evidence_missing" for item in result["candidate_reasons"])


def test_explicit_type_has_priority_and_never_invokes_scorer():
    def forbidden(_):
        raise AssertionError("explicit --type must not invoke auto scorer")

    result = classify_record({"text": "fixture"}, forbidden,
                             explicit_type="bug", related=["REQ-75"])
    assert result["decision"] == "explicit" and result["type"] == "bug"
    assert result["explicit"] == {"type": "bug", "related": ["REQ-75"]}
    assert result["verdict"] == "PASS" and result["rc"] == 0
    assert "scorer_version" not in result


def test_abstain_returns_candidates_reasons_and_one_input_request():
    result = classify_record({"text": "ambiguous"}, lambda _: {
        "scorer_version": "fixture@1", "candidates": candidates(score=0.60, score2=0.50),
    })
    assert result["decision"] == "abstain" and result["type"] is None
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2
    assert result["required_input"] == ["--type", "--related"]
    assert result["candidate_reasons"] and len(result["candidates"]) == 2
    assert result["top1"] == "initial" and result["top2"] == "change"


@pytest.mark.parametrize("bad", [
    [{"type": "initial", "score": float("nan")}],
    [{"type": "initial", "score": 1.01}],
    [{"type": "initial", "score": 0.9}, {"type": "initial", "score": 0.1}],
    [{"type": "initial", "score": 0.9, "evidence": [""]},
     {"type": "bug", "score": 0.1, "evidence": ["e"]}],
    [{"type": "unknown", "score": 0.9}, {"type": "bug", "score": 0.1}],
])
def test_invalid_auto_scores_fail_closed(bad):
    with pytest.raises(ClassificationError):
        classify_record({}, lambda _: {"scorer_version": "fixture@1", "candidates": bad})


def test_classify_output_io_error_returns_json_rc2(tmp_path):
    record = write_json(tmp_path / "record.json", {"text": "fixture"})
    result = subprocess.run([sys.executable, str(PKG_ROOT / "scripts/atlas_classify.py"),
                             "--mode", "enforce", "classify", "--root", str(tmp_path),
                             "--input", str(record), "--type", "bug", "--output", str(tmp_path), "--json"],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 2, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "UNVERIFIED" and payload["rc"] == 2


def test_train_calibration_heldout_are_disjoint_and_heldout_is_frozen():
    corpora = build_classification_corpora()
    assert set(corpora) == {"train", "calibration", "held-out"}
    ids = {}
    texts = {}
    for split, samples in corpora.items():
        ids[split] = {sample["id"] for sample in samples}
        texts[split] = {sample["input"]["text"] for sample in samples}
        assert all(sample["fingerprint"] for sample in samples)
    assert not ids["train"] & ids["calibration"] and not ids["train"] & ids["held-out"]
    assert not ids["calibration"] & ids["held-out"]
    assert not texts["train"] & texts["calibration"] and not texts["train"] & texts["held-out"]
    frozen = load_frozen_heldout()
    assert frozen["spec_sha256"] == "77ac0da783c9eeb6948053cbc79f15600bfe4ac14c792843271ef57ad93d6dd5"
    assert frozen["corpus_fingerprint"] == "765622d17d7b477f86bec2b89078380fb35e2f2aaedebbe595d586c7e9c39f49"
    assert frozen["tuning_allowed"] is False
    assert frozen["samples_per_class"] == {"initial": 50, "change": 50, "bug": 50}


@pytest.mark.parametrize("field,value", [
    ("fingerprint", "0" * 64),
    ("expected", "bug"),
])
def test_heldout_content_or_fingerprint_change_is_rejected(field, value):
    samples = copy.deepcopy(build_classification_corpora()["held-out"])
    samples[0][field] = value
    with pytest.raises(ClassificationError, match="fingerprint|指纹"):
        verify_heldout(samples)


def test_single_candidate_abstains_and_confident_abstain_error_fails():
    single = classify_record({"text": "x"}, {"scorer_version": "v", "candidates": [
        {"type": "initial", "score": 0.99, "evidence": ["e"]}]})
    assert single["decision"] == "abstain" and single["rc"] == 2
    corpora = build_classification_corpora()
    predictions = prediction_rows(corpora["held-out"])
    for sample in corpora["held-out"]:
        if sample["expected"] == "abstain":
            predictions[sample["id"]] = {"scorer_version": "fixture-scorer@1", "candidates": [
                {"type": "initial", "score": 0.99, "evidence": ["wrong"]},
                {"type": "change", "score": 0.01, "evidence": []}]}
    metrics = evaluate_classification(corpora["held-out"], predictions)
    assert metrics["passed"] is False
    assert any("自信误判" in reason for reason in metrics["reasons"])
    assert metrics["overall_abstention"] == 0


def test_threshold_selection_uses_calibration_not_heldout():
    corpora = build_classification_corpora()
    calibration = prediction_rows(corpora["calibration"])
    selected = select_thresholds(corpora["calibration"], calibration)
    assert selected["feasible"] is True
    assert selected["thresholds"] == DEFAULT_THRESHOLDS
    poor_heldout = evaluate_classification(corpora["held-out"],
                                           prediction_rows(corpora["held-out"], good=False),
                                           selected["thresholds"])
    assert poor_heldout["passed"] is False
    assert select_thresholds(corpora["calibration"], calibration)["thresholds"] == selected["thresholds"]


def test_per_class_metrics_count_wrong_auto_class_as_recall_miss():
    samples = [
        {"id": "i1", "expected": "initial"}, {"id": "i2", "expected": "initial"},
        {"id": "c1", "expected": "change"}, {"id": "b1", "expected": "bug"},
    ]
    predictions = {
        "i1": {"scorer_version": "v1", "candidates": candidates("initial", 0.99, "bug", 0.01)},
        "i2": {"scorer_version": "v1", "candidates": candidates("change", 0.99, "bug", 0.01)},
        "c1": {"scorer_version": "v1", "candidates": candidates("initial", 0.60, "change", 0.50)},
        "b1": {"scorer_version": "v1", "candidates": candidates("bug", 0.99, "change", 0.01)},
    }
    result = evaluate_classification(samples, predictions, DEFAULT_THRESHOLDS)
    assert result["per_class"]["initial"]["true_positive"] == 1
    assert result["per_class"]["initial"]["false_positive"] == 0
    assert result["per_class"]["change"]["false_positive"] == 1
    assert result["per_class"]["initial"]["precision"] == 1.0
    assert result["per_class"]["initial"]["recall"] == 0.5
    assert result["per_class"]["change"]["false_negative"] == 1
    assert result["per_class"]["change"]["abstention"] == 1.0


def test_insufficient_heldout_samples_cannot_pass():
    samples = [{"id": "only", "expected": "initial"}]
    metrics = evaluate_classification(samples, prediction_rows(samples), DEFAULT_THRESHOLDS)
    assert metrics["passed"] is False
    assert metrics["reasons"] and any("50" in reason for reason in metrics["reasons"])
    assert metrics["samples_per_class"]["change"] == 0


def test_metrics_formulas_and_percentiles():
    payload = {
        "clauses": [{"status": status} for status in
                    ["FAIL", "FAIL", "STALE", "UNVERIFIED", "UNVERIFIED", "PASS", "PASS", "PASS", "PASS", "PASS"]],
        "finding_samples": [{"valid": False}, {"valid": False}, {"valid": True}, {"valid": True}],
        "completed_units": [{"receipt_valid": True}, {"receipt_valid": False},
                            {"receipt_valid": False}, {"receipt_valid": False}],
        "repair_durations_ms": [400, 100, 300, 200],
        "incidents": [{"status": status} for status in ["closed", "contained", "resolved", "detected"]],
        "docs": [{"status": status} for status in ["PASS", "STALE", "STALE", "PASS"]],
        "topology": {"total": 4, "covered": 3},
        "private_business_body": "do-not-copy-this-body",
    }
    result = compute_metrics("/missing", module_results=payload, check_events=[
        {"rows": [{"name": "gate", "status": "PASS", "duration_ms": 10}]},
        {"rows": [{"name": "gate", "status": "FAIL", "duration_ms": 30}]},
    ])
    metrics = result["metrics"]
    assert metrics["drift_rate"]["value"] == pytest.approx(0.30)
    assert metrics["unverified_coverage"]["value"] == pytest.approx(0.20)
    assert metrics["false_positive_rate"]["value"] == pytest.approx(0.50)
    assert metrics["bypass_rate"]["value"] == pytest.approx(0.75)
    assert metrics["detection_fix_duration_ms"]["p50"] == 200
    assert metrics["detection_fix_duration_ms"]["p95"] == 400
    assert metrics["incident_unclosed_rate"]["value"] == pytest.approx(0.75)
    assert metrics["docs_stale_rate"]["value"] == pytest.approx(0.50)
    assert metrics["topology_coverage"]["value"] == pytest.approx(0.75)
    assert result["sources"]["check_events"]["runs"] == 2
    assert "do-not-copy-this-body" not in json.dumps(result)
    assert percentile([1, 2, 3, 4], 50) == 2


@pytest.mark.parametrize("explicit", [None, "bug"])
def test_classify_off_never_returns_pass_or_invokes_scorer(explicit):
    def forbidden(_):
        raise AssertionError("off classification must not invoke scorer")

    result = classify_record({"text": "fixture"}, forbidden, explicit_type=explicit, mode="off")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2


def test_empty_metrics_are_explicit_na_not_zero(tmp_path):
    result = compute_metrics(tmp_path)
    for key in ("drift_rate", "unverified_coverage", "false_positive_rate", "bypass_rate",
                "detection_fix_duration_ms", "incident_unclosed_rate", "docs_stale_rate",
                "topology_coverage"):
        metric = result["metrics"][key]
        assert metric["status"] == "N/A", key
        assert metric.get("value", metric.get("p50")) is None, key
        assert metric["reason"], key
        assert metric["owner"] and metric["due"], key
    assert result["classification_calibration"]["owner"]
    assert result["classification_calibration"]["due"]
    for source in result["sources"].values():
        assert source["owner"] and source["due"]
    assert result["sources"]["check_events"]["present"] is False
    assert result["sources"]["calibration"]["present"] is False
    assert result["sources"]["module_results"]["present"] is False


def test_zero_denominator_is_na_and_malformed_events_are_unverified():
    payload = {"clauses": [], "finding_samples": [], "completed_units": [],
               "repair_durations_ms": [], "incidents": [], "docs": [],
               "topology": {"total": 0, "covered": 0}}
    result = compute_metrics("/missing", module_results=payload,
                             check_events=[{"rows": []}, "not-json-object"])
    assert result["metrics"]["drift_rate"]["status"] == "N/A"
    assert result["sources"]["check_events"]["status"] == "UNVERIFIED"
    assert result["sources"]["check_events"]["errors"] == 1


def test_calibration_writes_atomic_ledger_and_passes_only_on_heldout(tmp_path):
    corpora = build_classification_corpora()
    calibration = prediction_file(tmp_path / "calibration.json", "calibration", corpora["calibration"])
    heldout = prediction_file(tmp_path / "heldout.json", "held-out", corpora["held-out"])
    result = calibrate(tmp_path, calibration, heldout, owner="Atlas + domain owner", decision="enforce", mode="enforce")
    assert result["rc"] == 0 and result["verdict"] == "PASS", result
    assert result["decision"] == "enforce" and result["eligible"] is True
    path = tmp_path / ".atlas/runs/governance-calibration.json"
    ledger = json.loads(path.read_text(encoding="utf-8"))
    assert ledger["heldout"]["spec_sha256"] == "77ac0da783c9eeb6948053cbc79f15600bfe4ac14c792843271ef57ad93d6dd5"
    assert ledger["heldout"]["tuning_allowed"] is False
    assert ledger["samples"]["heldout"]["initial"] == 50
    assert ledger["thresholds"] == DEFAULT_THRESHOLDS
    assert ledger["owner"] == "Atlas + domain owner" and ledger["decision"] == "enforce"
    assert ledger["metrics"]["heldout"]["passed"] is True
    assert validate_calibration(tmp_path)["rc"] == 0
    assert not list(path.parent.glob(".governance-calibration.json.*.tmp"))


def test_calibration_below_gate_stays_shadow_and_validator_returns_rc2(tmp_path):
    corpora = build_classification_corpora()
    calibration = prediction_file(tmp_path / "calibration.json", "calibration", corpora["calibration"])
    heldout = prediction_file(tmp_path / "heldout.json", "held-out", corpora["held-out"], good=False)
    result = calibrate(tmp_path, calibration, heldout, owner="owner", decision="enforce")
    assert result["rc"] == 2 and result["verdict"] == "UNVERIFIED"
    assert result["eligible"] is False and result["decision"] == "shadow"
    checked = validate_calibration(tmp_path)
    assert checked["rc"] == 2 and checked["verdict"] == "UNVERIFIED"
    assert checked["decision"] == "shadow" and checked["cause"] == "calibration_unverified"


def test_calibration_pointer_failure_keeps_previous_generation_valid(tmp_path, monkeypatch):
    import scripts.atlas_calibrate as calibration
    corpora = build_classification_corpora()
    calibration_file = prediction_file(tmp_path / "calibration.json", "calibration", corpora["calibration"])
    heldout_file = prediction_file(tmp_path / "heldout.json", "held-out", corpora["held-out"])
    assert calibrate(tmp_path, calibration_file, heldout_file, owner="owner", mode="enforce")["rc"] == 0
    paths = [tmp_path / ".atlas/runs/governance-calibration.json",
             tmp_path / ".atlas/runs/governance-calibration-predictions.json",
             tmp_path / ".atlas/runs/governance-heldout-predictions.json"]
    before = [path.read_bytes() for path in paths]
    reordered = tmp_path / "reordered.json"
    reordered.write_text(json.dumps(json.loads(calibration_file.read_text()), ensure_ascii=False, separators=(",", ":")))
    original = calibration.atomic_write_json

    def fail_ledger(path, value):
        if Path(path).name == "governance-calibration.json":
            raise OSError("injected ledger failure")
        return original(path, value)

    monkeypatch.setattr(calibration, "atomic_write_json", fail_ledger)
    with pytest.raises(OSError, match="injected"):
        calibrate(tmp_path, reordered, heldout_file, owner="owner", mode="enforce")
    assert paths[0].read_bytes() == before[0]
    assert validate_calibration(tmp_path)["rc"] == 0


def test_non_object_calibration_pointer_is_unverified_not_crash(tmp_path):
    path = tmp_path / ".atlas/runs/governance-calibration.json"
    path.parent.mkdir(parents=True)
    path.write_text("[]")
    result = validate_calibration(tmp_path)
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2
    cli = subprocess.run([sys.executable, str(PKG_ROOT / "validators/validate_calibration.py"),
                          "--root", str(tmp_path), "--json"], capture_output=True, text=True)
    assert cli.returncode == 2 and json.loads(cli.stdout)["verdict"] == "UNVERIFIED"


def test_calibration_rollback_cli_non_object_pointer_is_unverified(tmp_path):
    path = tmp_path / ".atlas/runs/governance-calibration.json"
    path.parent.mkdir(parents=True)
    path.write_text("[]")
    result = subprocess.run([sys.executable, str(PKG_ROOT / "scripts/atlas_calibrate.py"),
                             "--root", str(tmp_path), "--mode", "enforce", "--rollback", "--json"],
                            capture_output=True, text=True)
    assert result.returncode == 2, result.stdout + result.stderr
    assert json.loads(result.stdout)["verdict"] == "UNVERIFIED"


def test_calibration_rollback_off_does_not_switch_pointer(tmp_path):
    from scripts.atlas_calibrate import rollback_calibration
    corpora = build_classification_corpora()
    calibration = prediction_file(tmp_path / "calibration.json", "calibration", corpora["calibration"])
    heldout = prediction_file(tmp_path / "heldout.json", "held-out", corpora["held-out"])
    calibrate(tmp_path, calibration, heldout, owner="owner", mode="enforce")
    calibrate(tmp_path, calibration, heldout, owner="owner", decision="enforce", mode="enforce")
    pointer = tmp_path / ".atlas/runs/governance-calibration.json"
    before = pointer.read_bytes()
    result = rollback_calibration(tmp_path, mode="off")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2 and result["mode"] == "off"
    assert pointer.read_bytes() == before


def test_calibration_rollback_switches_to_previous_generation(tmp_path):
    from scripts.atlas_calibrate import rollback_calibration
    corpora = build_classification_corpora()
    calibration = prediction_file(tmp_path / "calibration.json", "calibration", corpora["calibration"])
    heldout = prediction_file(tmp_path / "heldout.json", "held-out", corpora["held-out"])
    assert calibrate(tmp_path, calibration, heldout, owner="owner", decision="shadow", mode="enforce")["rc"] == 0
    first = json.loads((tmp_path / ".atlas/runs/governance-calibration.json").read_text())["generation"]
    assert calibrate(tmp_path, calibration, heldout, owner="owner", decision="enforce", mode="enforce")["rc"] == 0
    result = rollback_calibration(tmp_path)
    assert result["generation"] == first and result["decision"] == "shadow"
    checked = validate_calibration(tmp_path)
    assert checked["rc"] == 0 and checked["decision"] == "shadow"


def test_validator_rejects_tampered_counts_thresholds_and_owner(tmp_path):
    corpora = build_classification_corpora()
    calibration = prediction_file(tmp_path / "calibration.json", "calibration", corpora["calibration"])
    heldout = prediction_file(tmp_path / "heldout.json", "held-out", corpora["held-out"])
    assert calibrate(tmp_path, calibration, heldout, owner="owner", decision="enforce")["rc"] == 0
    path = tmp_path / ".atlas/runs/governance-calibration.json"
    original = json.loads(path.read_text(encoding="utf-8"))
    for mutate in (
        lambda value: value["samples"]["heldout"].update(initial=49),
        lambda value: value["thresholds"].update(top1_score=0.1),
        lambda value: value.update(owner=""),
        lambda value: value["heldout"].update(spec_sha256="0" * 64),
        lambda value: value["metrics"]["heldout"]["per_class"]["bug"].update(precision=0.94),
        lambda value: value["metrics"]["heldout"]["per_class"]["bug"].update(samples="50"),
        lambda value: value.update(generation="0" * 64),
    ):
        broken = copy.deepcopy(original)
        mutate(broken)
        write_json(path, broken)
        checked = validate_calibration(tmp_path)
        assert checked["rc"] == 2 and checked["verdict"] == "UNVERIFIED", checked
        assert checked["decision"] == "shadow"


def test_prediction_split_mismatch_and_heldout_label_forgery_are_rejected(tmp_path):
    corpora = build_classification_corpora()
    calibration = prediction_file(tmp_path / "calibration.json", "calibration", corpora["calibration"])
    heldout = prediction_file(tmp_path / "heldout.json", "held-out", corpora["held-out"])
    value = json.loads(heldout.read_text(encoding="utf-8"))
    value["split"] = "calibration"
    write_json(heldout, value)
    with pytest.raises(ClassificationError, match="split"):
        calibrate(tmp_path, calibration, heldout, owner="owner")
    value["split"] = "held-out"
    value["samples"][0]["expected"] = "bug"
    write_json(heldout, value)
    with pytest.raises(ClassificationError, match="expected|标签"):
        calibrate(tmp_path, calibration, heldout, owner="owner")


def test_classify_cli_explicit_and_auto_json(tmp_path):
    record = write_json(tmp_path / "record.json", {"text": "fixture"})
    script = PKG_ROOT / "scripts/atlas_classify.py"
    explicit = subprocess.run([sys.executable, str(script), "--mode", "enforce", "classify", "--root", str(tmp_path),
                               "--input", str(record), "--type", "bug", "--related", "REQ-75", "--json"],
                              capture_output=True, text=True, timeout=30)
    assert explicit.returncode == 0, explicit.stdout + explicit.stderr
    assert json.loads(explicit.stdout)["explicit"] == {"type": "bug", "related": ["REQ-75"]}
    persisted = json.loads((tmp_path / ".atlas/runs/workflow-classification.json").read_text())
    assert persisted["mode"] == "enforce" and persisted["type"] == "bug"
    auto_record = write_json(tmp_path / "auto.json", {
        "scorer_version": "fixture@1", "candidates": candidates(),
    })
    auto = subprocess.run([sys.executable, str(script), "classify", "--root", str(tmp_path),
                           "--input", str(auto_record), "--json"], capture_output=True, text=True, timeout=30)
    assert auto.returncode == 0, auto.stdout + auto.stderr
    assert json.loads(auto.stdout)["top1"] == "initial"
