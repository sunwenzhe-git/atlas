#!/usr/bin/env python3
"""RFC-20261125-01 §15 read-only calibration ledger validator.

A ledger that is missing, malformed, below any per-class gate, short of held-out
samples or inconsistent with its frozen fingerprints is UNVERIFIED/rc2. Its
reported decision is forced to shadow; this validator can never promote a failed
calibration to enforce.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _support.classification_contract import (  # noqa: E402
    CLASS_LABELS,
    FROZEN_CORPUS_FINGERPRINT,
    FROZEN_SPEC_SHA256,
    GATES,
    MIN_HELDOUT_PER_CLASS,
    load_frozen_heldout,
    load_prediction_file,
    build_classification_corpora,
    calibration_generation,
    evaluate_classification,
    select_thresholds,
)
from _support.governance_io import load_json, safe_path  # noqa: E402

CALIBRATION_REL = ".atlas/runs/governance-calibration.json"


def _result(errors: list[str], *, decision: str = "shadow", eligible: bool = False,
            mode: str = "enforce") -> dict:
    if mode == "off":
        errors, eligible = [], False
    return {
        "schema_version": 1, "module": "classification", "mode": mode, "path": CALIBRATION_REL,
        "verdict": "UNVERIFIED" if mode == "off" or errors else "PASS",
        "rc": 2 if mode == "off" or errors and mode == "enforce" else 0,
        "cause": "calibration_unverified" if errors else None,
        "decision": decision, "eligible_for_enforce": eligible,
        "findings": [{"cause": "calibration_unverified", "message": error} for error in errors],
    }


def _integer(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _same_number(actual, expected) -> bool:
    return isinstance(actual, (int, float)) and not isinstance(actual, bool) \
        and math.isfinite(actual) and math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)


def canonical_metrics(value: dict) -> dict:
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))


def validate_calibration(root: str | Path, ledger_path: str = CALIBRATION_REL) -> dict:
    """Validate frozen provenance, sample counts, formulas and §15 gates."""
    root = Path(root).absolute()
    generation_dir = None
    try:
        path = safe_path(root, ledger_path)
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError("calibration ledger 缺失或不是普通文件")
        ledger = load_json(path)
        if not isinstance(ledger, dict):
            raise ValueError("calibration ledger 必须为对象")
        generation = ledger.get("generation")
        if generation is not None:
            if not isinstance(generation, str) or not re.fullmatch(r"[0-9a-f]{64}", generation):
                return _result(["calibration generation 非法"])
            if ledger.get("path") != f".atlas/runs/governance-calibration/generations/{generation}":
                return _result(["calibration generation path 与标识不符"])
            directory = safe_path(root, ledger["path"])
            generation_dir = directory
            files = ledger.get("files")
            if not isinstance(files, dict) or set(files) != {
                    "ledger.json", "calibration-predictions.json", "heldout-predictions.json"}:
                return _result(["calibration generation files 清单非法"])
            if not directory.is_dir() or directory.is_symlink():
                return _result(["calibration generation 目录缺失"])
            entries = list(directory.iterdir())
            if {entry.name for entry in entries} != set(files) \
                    or any(not entry.is_file() or entry.is_symlink() for entry in entries):
                return _result(["calibration generation 目录不完整"])
            for name, expected in files.items():
                if hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected:
                    return _result([f"calibration generation hash 不符：{name}"])
            snapshot = load_json(directory / "ledger.json")
            if calibration_generation(snapshot, (directory / "calibration-predictions.json").read_bytes(),
                                      (directory / "heldout-predictions.json").read_bytes()) != generation:
                return _result(["calibration generation 与内容重算不符"])
            core = {key: value for key, value in ledger.items()
                    if key not in {"generation", "path", "files", "previous_generation", "previous_pointer"}}
            if snapshot != core:
                return _result(["calibration pointer 与 generation ledger 不一致"])
            ledger = snapshot
    except (OSError, ValueError, UnicodeError) as exc:
        return _result([str(exc)])
    errors = []
    if ledger.get("schema_version") != 1 or ledger.get("module") != "classification":
        errors.append("schema_version/module 非法")
    owner = ledger.get("owner")
    if not isinstance(owner, str) or not owner.strip():
        errors.append("owner 缺失")
    requested = ledger.get("decision")
    if requested not in ("shadow", "enforce"):
        errors.append("decision 非法")
    heldout = ledger.get("heldout")
    if not isinstance(heldout, dict):
        errors.append("heldout provenance 缺失")
        heldout = {}
    if heldout.get("spec_sha256") != FROZEN_SPEC_SHA256:
        errors.append("heldout spec sha256 与冻结值不符")
    if heldout.get("corpus_fingerprint") != FROZEN_CORPUS_FINGERPRINT:
        errors.append("heldout corpus fingerprint 与冻结值不符")
    if heldout.get("tuning_allowed") is not False or heldout.get("evaluation_only") is not True:
        errors.append("held-out 必须 evaluation_only 且 tuning_allowed=false")
    thresholds = ledger.get("thresholds")
    if not isinstance(thresholds, dict) or set(thresholds) != {"top1_score", "margin"} \
            or any(isinstance(value, bool) or not isinstance(value, (int, float))
                   or not math.isfinite(value) or not 0 <= value <= 1 for value in thresholds.values()):
        errors.append("thresholds 非法")
    elif thresholds["top1_score"] < 0.90 or thresholds["margin"] < 0.15:
        errors.append("thresholds 低于初始 top1>=0.90/margin>=0.15 下限")
    selection = ledger.get("threshold_selection")
    if not isinstance(selection, dict) or selection.get("split") != "calibration" \
            or selection.get("feasible") is not True:
        errors.append("thresholds 不是从可达 calibration 集选择")
    metrics = ledger.get("metrics")
    calibration_metrics = metrics.get("calibration") if isinstance(metrics, dict) else None
    heldout_metrics = metrics.get("heldout") if isinstance(metrics, dict) else None
    if not isinstance(calibration_metrics, dict) or calibration_metrics.get("passed") is not True:
        errors.append("calibration metrics 未达门槛")
    if not isinstance(heldout_metrics, dict) or heldout_metrics.get("passed") is not True:
        errors.append("held-out metrics 未达门槛")
    if isinstance(selection, dict) and isinstance(calibration_metrics, dict) \
            and selection.get("scorer_version") != calibration_metrics.get("scorer_version"):
        errors.append("calibration scorer_version 不一致")
    if not isinstance(selection, dict) or not isinstance(selection.get("heldout_prediction_fingerprint"), str) \
            or not re.fullmatch(r"[0-9a-f]{64}", selection["heldout_prediction_fingerprint"]):
        errors.append("heldout prediction fingerprint 缺失或非法")
    if isinstance(heldout_metrics, dict) and isinstance(thresholds, dict) \
            and heldout_metrics.get("thresholds") != thresholds:
        errors.append("held-out metrics thresholds 与账本不符")

    samples = ledger.get("samples")
    heldout_samples = samples.get("heldout") if isinstance(samples, dict) else None
    if not isinstance(heldout_samples, dict):
        errors.append("heldout samples 缺失")
        heldout_samples = {}
    per_class = heldout_metrics.get("per_class") if isinstance(heldout_metrics, dict) else None
    if not isinstance(per_class, dict) or set(per_class) != set(CLASS_LABELS):
        errors.append("heldout per_class metrics 缺失或含未知键")
        per_class = {}
    frozen = None
    try:
        frozen = load_frozen_heldout()
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
    for label in CLASS_LABELS:
        count = heldout_samples.get(label)
        item = per_class.get(label)
        if not _integer(count) or count < MIN_HELDOUT_PER_CLASS:
            errors.append(f"{label} held-out samples 少于 {MIN_HELDOUT_PER_CLASS}")
        if not isinstance(item, dict):
            errors.append(f"{label} per_class metrics 缺失")
            continue
        required_counts = ("true_positive", "false_positive", "false_negative", "abstained", "samples")
        if any(not _integer(item.get(key)) for key in required_counts):
            errors.append(f"{label} metric counts 非法")
            continue
        tp, fp, fn = item["true_positive"], item["false_positive"], item["false_negative"]
        total, abstained = item["samples"], item["abstained"]
        if total != count or tp + fn != total or abstained > total:
            errors.append(f"{label} metric counts 不自洽")
            continue
        expected = {
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "abstention": abstained / total if total else None,
        }
        for key, value in expected.items():
            if value is None or not _same_number(item.get(key), value):
                errors.append(f"{label} {key} 公式不符")
            elif key in ("precision", "recall") and value < GATES[key]:
                errors.append(f"{label} {key} 未达门槛")
            elif key == "abstention" and value > GATES[key]:
                errors.append(f"{label} abstention 未达门槛")
    if isinstance(heldout_metrics, dict):
        total = heldout_metrics.get("total")
        labeled_items = [item for item in per_class.values() if isinstance(item, dict)
                         and all(_integer(item.get(key)) for key in
                                 ("true_positive", "false_positive", "false_negative", "abstained", "samples"))]
        labeled_total = sum(item["samples"] for item in labeled_items)
        abstained = sum(item["abstained"] for item in labeled_items)
        expected_overall = abstained / labeled_total if isinstance(total, int) and labeled_total > 0 else None
        if expected_overall is None or not _same_number(heldout_metrics.get("overall_abstention"), expected_overall):
            errors.append("held-out overall abstention 公式不符")
        elif expected_overall > GATES["abstention"]:
            errors.append("held-out overall abstention 未达门槛")
        if heldout_metrics.get("passed") is not (not heldout_metrics.get("reasons")):
            errors.append("held-out passed 与 reasons 不自洽")
    if frozen is not None and isinstance(heldout_metrics, dict):
        if heldout_metrics.get("total") != len(frozen["samples"]):
            errors.append("held-out total 与冻结语料不符")
        if any(heldout_samples.get(label) != frozen["samples_per_class"][label] for label in CLASS_LABELS):
            errors.append("held-out per-class samples 与冻结语料不符")
    if isinstance(selection, dict):
        try:
            corpora = build_classification_corpora()
            calibration_path = generation_dir / "calibration-predictions.json" if generation_dir else \
                safe_path(root, selection.get("calibration_predictions_path", ""))
            heldout_path = generation_dir / "heldout-predictions.json" if generation_dir else \
                safe_path(root, selection.get("heldout_predictions_path", ""))
            for path, key in ((calibration_path, "calibration_predictions_sha256"),
                              (heldout_path, "heldout_predictions_sha256")):
                if hashlib.sha256(path.read_bytes()).hexdigest() != selection.get(key):
                    errors.append(f"{path.name} sha256 与账本不符")
            calibration_predictions, calibration_source = load_prediction_file(calibration_path, "calibration")
            heldout_predictions, heldout_source = load_prediction_file(heldout_path, "held-out")
            if calibration_source["fingerprint"] != selection.get("calibration_fingerprint"):
                errors.append("calibration prediction fingerprint 不符")
            if heldout_source["fingerprint"] != selection.get("heldout_prediction_fingerprint"):
                errors.append("heldout prediction fingerprint 不符")
            if isinstance(thresholds, dict):
                recalculated = select_thresholds(corpora["calibration"], calibration_predictions)
                if recalculated["thresholds"] != thresholds:
                    errors.append("thresholds 不是 calibration 重放结果")
                if recalculated.get("feasible") is not True or recalculated.get("passed") is not True:
                    errors.append("calibration 重放未达门槛")
                if canonical_metrics(recalculated) != canonical_metrics(calibration_metrics):
                    errors.append("calibration metrics 与预测 artifact 重放不符")
                if calibration_source.get("scorer_version") != selection.get("scorer_version") \
                        or heldout_source.get("scorer_version") != selection.get("scorer_version"):
                    errors.append("prediction artifact scorer_version 与账本不符")
                replayed_heldout = evaluate_classification(corpora["held-out"], heldout_predictions, thresholds=thresholds)
                if canonical_metrics(replayed_heldout) != canonical_metrics(heldout_metrics):
                    errors.append("heldout metrics 与预测 artifact 重放不符")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"校准预测 artifact 不可重放：{exc}")
    eligible = not errors
    decision = requested if eligible and requested in ("shadow", "enforce") else "shadow"
    if errors and requested == "enforce":
        errors.append("未达标账本不得升 enforce；已强制 shadow")
    return _result(errors, decision=decision, eligible=eligible)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--ledger", default=CALIBRATION_REL)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--mode", choices=("shadow", "enforce", "off"), default="enforce")
    args = parser.parse_args(argv)
    try:
        result = validate_calibration(args.root, args.ledger)
        result = _result([item["message"] for item in result["findings"]],
                         decision=result["decision"], eligible=result["eligible_for_enforce"], mode=args.mode)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        result = _result([f"calibration validator 异常：{exc}"], mode=args.mode)
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        print(f"[{result['verdict']}] calibration rc={result['rc']} decision={result['decision']}")
        for finding in result["findings"]:
            print(f"[{result['verdict']}] {finding['message']}")
    return result["rc"]


if __name__ == "__main__":
    sys.exit(main())
