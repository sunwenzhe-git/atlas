"""M251: RFC-20261125-01 §11 frozen classification output contract.

Removing either score/margin comparison from the auto-accept conjunction (or
changing ``and`` to ``or``) must turn the M251 threshold-boundary tests in
tests/test_governance_calibration.py red. The real four-stage mutation_proof is
.atlas/runs/mutation-proof/M251.txt.

This module does not classify natural language. Callers supply versioned scored
candidates; explicit --type always wins, while uncertain auto results abstain
once and request --type/--related. Train, calibration and the fingerprinted
held-out corpus are disjoint, and held-out is never used to select thresholds.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from _support.governance_corpus import SCHEMAS, expand_heldout
from _support.governance_schema import canonical_bytes, canonical_digest

CLASS_LABELS = ("initial", "change", "bug")
DEFAULT_THRESHOLDS = {"top1_score": 0.90, "margin": 0.15}
MIN_HELDOUT_PER_CLASS = 50
GATES = {"precision": 0.95, "recall": 0.85, "abstention": 0.20}
FROZEN_SPEC_SHA256 = "77ac0da783c9eeb6948053cbc79f15600bfe4ac14c792843271ef57ad93d6dd5"
FROZEN_CORPUS_FINGERPRINT = "765622d17d7b477f86bec2b89078380fb35e2f2aaedebbe595d586c7e9c39f49"


class ClassificationError(ValueError):
    """A classification contract, corpus or prediction is invalid."""


def calibration_generation(ledger: dict, calibration_raw: bytes, heldout_raw: bytes) -> str:
    return hashlib.sha256(canonical_bytes({
        "ledger": ledger,
        "calibration_predictions_sha256": hashlib.sha256(calibration_raw).hexdigest(),
        "heldout_predictions_sha256": hashlib.sha256(heldout_raw).hexdigest(),
    })).hexdigest()


def _fingerprinted(split: str, sample: dict) -> dict:
    value = {"split": split, **sample}
    return {**sample, "fingerprint": canonical_digest(value)}


def _derived_split(spec: dict, split: str, templates: dict[str, list[str]]) -> list[dict]:
    samples = []
    domains = spec["domains"]["semantic"]
    for label in CLASS_LABELS:
        for index in range(spec["classification_samples_per_class"] + 10):
            domain = domains[index % len(domains)]
            text = templates[label][index % len(templates[label])].format(domain) + f" {split}-{index:02d}"
            sample = {"id": f"{split}-{label}-{index:02d}", "input": {"text": text}, "expected": label}
            samples.append(_fingerprinted(split, sample))
        for index in range(10):
            domain = domains[index % len(domains)]
            sample = {"id": f"{split}-{label}-abstain-{index:02d}",
                      "input": {"text": f"请辅助查看{domain}，状态暂不明确 {split}-{index:02d}"},
                      "expected": "abstain"}
            samples.append(_fingerprinted(split, sample))
    return samples


def build_classification_corpora() -> dict[str, list[dict]]:
    """Return disjoint train/calibration fixtures and the immutable held-out set."""
    spec = json.loads((SCHEMAS / "heldout-spec.json").read_text(encoding="utf-8"))
    train = _derived_split(spec, "train", {
        "initial": ["初始化{}并交付首个版本", "为{}建立全新系统"],
        "change": ["演进{}既有功能", "变更{}当前约定"],
        "bug": ["排查{}异常并修复回归", "纠正{}的非预期行为"],
    })
    calibration = _derived_split(spec, "calibration", {
        "initial": ["规划{}的第一阶段", "筹备{}的新能力"],
        "change": ["更新{}已上线规则", "重构{}现有流程"],
        "bug": ["处理{}缺陷", "定位{}故障原因并修复"],
    })
    heldout = expand_heldout(spec)["classification"]
    verify_heldout(heldout)
    return {"train": train, "calibration": calibration, "held-out": heldout}


def verify_heldout(samples: list[dict]) -> str:
    """Reject any content, label, per-item fingerprint or aggregate drift."""
    if not isinstance(samples, list) or not samples:
        raise ClassificationError("held-out 样本必须是非空数组")
    ids = set()
    for sample in samples:
        if not isinstance(sample, dict) or sample.get("id") in ids:
            raise ClassificationError("held-out 样本 id 缺失或重复")
        ids.add(sample["id"])
        expected_fingerprint = sample.get("fingerprint")
        body = {key: value for key, value in sample.items() if key != "fingerprint"}
        if expected_fingerprint != canonical_digest({"split": "held-out", **body}):
            raise ClassificationError(f"held-out fingerprint 不匹配：{sample['id']}")
    fingerprint = canonical_digest(samples)
    if fingerprint != FROZEN_CORPUS_FINGERPRINT:
        raise ClassificationError("held-out 聚合指纹变化，禁止用于调参")
    return fingerprint


def load_frozen_heldout() -> dict:
    """Load held-out only when both the frozen spec bytes and corpus still match."""
    path = SCHEMAS / "heldout-spec.json"
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != FROZEN_SPEC_SHA256:
        raise ClassificationError("heldout-spec.json 字节指纹变化")
    spec = json.loads(raw.decode("utf-8"))
    if spec.get("split") != "held-out" or spec.get("tuning_allowed") is not False:
        raise ClassificationError("held-out split 必须冻结且 tuning_allowed=false")
    samples = expand_heldout(spec)["classification"]
    fingerprint = verify_heldout(samples)
    return {
        "spec_path": "shared/schemas/heldout-spec.json", "spec_sha256": digest,
        "corpus_fingerprint": fingerprint, "tuning_allowed": False,
        "samples_per_class": {label: sum(item["expected"] == label for item in samples)
                              for label in CLASS_LABELS},
        "samples": samples,
    }


def _thresholds(value: dict | None) -> dict:
    selected = dict(DEFAULT_THRESHOLDS if value is None else value)
    if set(selected) != set(DEFAULT_THRESHOLDS):
        raise ClassificationError("thresholds 必须且只能含 top1_score/margin")
    for key in selected:
        number = selected[key]
        if isinstance(number, bool) or not isinstance(number, (int, float)) \
                or not math.isfinite(number) or not 0 <= number <= 1:
            raise ClassificationError(f"threshold {key} 必须在 [0,1]")
    return selected


def _candidates(value) -> list[dict]:
    if not isinstance(value, list) or not value:
        raise ClassificationError("auto candidates 必须是非空数组")
    normalized = []
    seen = set()
    for candidate in value:
        if not isinstance(candidate, dict) or set(candidate) - {"type", "score", "evidence"}:
            raise ClassificationError("candidate 只允许 type/score/evidence")
        label = candidate.get("type")
        score = candidate.get("score")
        if label not in CLASS_LABELS or label in seen:
            raise ClassificationError("candidate type 非法或重复")
        if isinstance(score, bool) or not isinstance(score, (int, float)) \
                or not math.isfinite(score) or not 0 <= score <= 1:
            raise ClassificationError("candidate score 必须在 [0,1]")
        evidence = candidate.get("evidence", [])
        if not isinstance(evidence, list) or any(not isinstance(item, str) or not item.strip() for item in evidence):
            raise ClassificationError("candidate evidence 必须为字符串数组")
        seen.add(label)
        normalized.append({"type": label, "score": float(score), "evidence": list(evidence)})
    order = {label: index for index, label in enumerate(CLASS_LABELS)}
    return sorted(normalized, key=lambda item: (-item["score"], order[item["type"]]))


def _scorer_output(scorer, record: dict) -> tuple[list[dict], str]:
    try:
        output = scorer(record) if callable(scorer) else scorer
    except Exception as exc:
        raise ClassificationError(f"scorer 失败：{exc}") from exc
    if not isinstance(output, dict):
        raise ClassificationError("scorer 输出必须为对象")
    version = output.get("scorer_version")
    if not isinstance(version, str) or not version.strip():
        raise ClassificationError("scorer_version 不能为空")
    return _candidates(output.get("candidates")), version


def classify_record(record: dict, scorer=None, *, explicit_type: str | None = None,
                    related: list[str] | str | None = None,
                    thresholds: dict | None = None, mode: str = "shadow") -> dict:
    """Freeze one explicit/auto/abstain result without retaining business text."""
    if not isinstance(record, dict):
        raise ClassificationError("classification record 必须为对象")
    if mode not in ("shadow", "enforce", "off"):
        raise ClassificationError("mode 必须为 shadow/enforce/off")
    selected = _thresholds(thresholds)
    try:
        input_digest = canonical_digest(record)
    except (TypeError, ValueError) as exc:
        raise ClassificationError(f"record 不可 canonical 化：{exc}") from exc
    refs = [related] if isinstance(related, str) else related or []
    if not isinstance(refs, list) or any(not isinstance(item, str) or not item for item in refs):
        raise ClassificationError("related 必须为非空字符串数组")
    common = {"schema_version": 1, "module": "classification", "mode": mode, "input_digest": input_digest,
              "thresholds": selected, "related": list(refs)}
    if mode == "off":
        return {**common, "decision": "abstain", "type": None, "cause": None,
                "verdict": "UNVERIFIED", "rc": 2, "required_input": ["--type"]}
    if explicit_type is not None:
        if explicit_type not in CLASS_LABELS:
            raise ClassificationError("explicit --type 必须为 initial/change/bug")
        return {**common, "decision": "explicit", "type": explicit_type,
                "explicit": {"type": explicit_type, "related": list(refs)},
                "verdict": "PASS", "rc": 0, "required_input": []}
    ranked, version = _scorer_output(scorer, record)
    top1 = ranked[0]
    top2 = ranked[1] if len(ranked) > 1 else None
    top2_score = top2["score"] if top2 else 0.0
    margin = top1["score"] - top2_score
    accepted = len(ranked) >= 2 and bool(top1["evidence"]) \
        and top1["score"] >= selected["top1_score"] and margin >= selected["margin"]
    reasons = []
    if top1["score"] < selected["top1_score"]:
        reasons.append({"type": top1["type"], "reason": "top1_below_threshold"})
    if not top1["evidence"]:
        reasons.append({"type": top1["type"], "reason": "evidence_missing"})
    if len(ranked) < 2:
        reasons.append({"type": top1["type"], "reason": "top2_missing"})
    if margin < selected["margin"]:
        reasons.append({"type": top1["type"], "reason": "margin_below_threshold"})
    return {
        **common, "decision": "auto" if accepted else "abstain",
        "type": top1["type"] if accepted else None,
        "top1": top1["type"], "top2": top2["type"] if top2 else None,
        "score": top1["score"], "top2_score": top2_score, "margin": margin,
        "evidence": top1["evidence"], "scorer_version": version, "candidates": ranked,
        "candidate_reasons": reasons,
        "required_input": [] if accepted else ["--type", "--related"],
        "verdict": "PASS" if accepted else "UNVERIFIED", "rc": 0 if accepted else 2,
    }


def _meets(metrics: dict) -> bool:
    return all(metrics.get(key) is not None and metrics[key] >= GATES[key]
               for key in ("precision", "recall")) \
        and metrics.get("abstention") is not None and metrics["abstention"] <= GATES["abstention"]


def evaluate_classification(samples: list[dict], predictions: dict[str, dict], thresholds: dict | None = None, *,
                            min_samples: int = MIN_HELDOUT_PER_CLASS) -> dict:
    """Evaluate accepted predictions by class; expected labels come from corpus."""
    selected = _thresholds(thresholds)
    expected_ids = [sample["id"] for sample in samples]
    if len(expected_ids) != len(set(expected_ids)) or set(expected_ids) != set(predictions):
        raise ClassificationError("predictions 与语料 id 集合必须完全一致")
    counts = {label: {"true_positive": 0, "false_positive": 0, "false_negative": 0,
                      "abstained": 0, "samples": 0} for label in CLASS_LABELS}
    accepted = 0
    abstained_total = 0
    versions = set()
    reasons = []
    for sample in samples:
        expected = sample["expected"]
        prediction = predictions[sample["id"]]
        if not isinstance(prediction, dict):
            raise ClassificationError(f"prediction 必须为对象：{sample['id']}")
        result = classify_record({"id": sample["id"]}, prediction, thresholds=selected)
        versions.add(result["scorer_version"])
        predicted = result["type"]
        if expected == "abstain":
            if result["decision"] != "abstain":
                reasons.append(f"abstain 样本被自信误判：{sample['id']}")
            continue
        if expected not in CLASS_LABELS:
            continue
        counts[expected]["samples"] += 1
        if result["decision"] == "abstain":
            counts[expected]["abstained"] += 1
            counts[expected]["false_negative"] += 1
            abstained_total += 1
        else:
            accepted += 1
            if predicted == expected:
                counts[expected]["true_positive"] += 1
            else:
                counts[expected]["false_negative"] += 1
                counts[predicted]["false_positive"] += 1
    per_class = {}
    for label, count in counts.items():
        tp, fp, fn = count["true_positive"], count["false_positive"], count["false_negative"]
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        abstention = count["abstained"] / count["samples"] if count["samples"] else None
        per_class[label] = {**count, "precision": precision, "recall": recall,
                            "abstention": abstention}
        if count["samples"] < min_samples:
            reasons.append(f"{label} samples {count['samples']} < {min_samples}")
        if not _meets(per_class[label]):
            reasons.append(f"{label} precision/recall/abstention 未达门槛")
    labeled_total = sum(count["samples"] for count in counts.values())
    overall_abstention = abstained_total / labeled_total if labeled_total else None
    if overall_abstention is None or overall_abstention > GATES["abstention"]:
        reasons.append("overall abstention 未达门槛")
    if len(versions) > 1:
        raise ClassificationError("单次评测 scorer_version 必须一致")
    return {
        "thresholds": selected, "minimum_samples": min_samples,
        "samples_per_class": {label: counts[label]["samples"] for label in CLASS_LABELS},
        "per_class": per_class, "accepted": accepted, "total": len(samples),
        "overall_abstention": overall_abstention,
        "scorer_version": next(iter(versions)) if versions else None,
        "passed": not reasons, "reasons": reasons,
    }


def select_thresholds(samples: list[dict], predictions: dict[str, dict]) -> dict:
    """Select only on calibration; prefer coverage, then the frozen initial pair."""
    best = None
    best_key = None
    for top1_int in range(90, 101):
        for margin_int in range(15, 31):
            thresholds = {"top1_score": top1_int / 100, "margin": margin_int / 100}
            metrics = evaluate_classification(samples, predictions, thresholds=thresholds,
                                              min_samples=1)
            if not metrics["passed"]:
                continue
            key = (metrics["accepted"],
                   -abs(thresholds["top1_score"] - DEFAULT_THRESHOLDS["top1_score"])
                   - abs(thresholds["margin"] - DEFAULT_THRESHOLDS["margin"]),
                   thresholds["top1_score"], thresholds["margin"])
            if best_key is None or key > best_key:
                best_key, best = key, metrics
    if best is None:
        fallback = evaluate_classification(samples, predictions, thresholds=DEFAULT_THRESHOLDS,
                                           min_samples=1)
        return {**fallback, "feasible": False,
                "reasons": ["calibration 无可达门槛阈值"] + fallback["reasons"]}
    return {**best, "feasible": True}


def load_prediction_file(path: str | Path, split: str) -> tuple[dict[str, dict], dict]:
    """Load externally scored rows and bind expected labels to the canonical corpus."""
    if split not in ("train", "calibration", "held-out"):
        raise ClassificationError("prediction split 必须为 train/calibration/held-out")
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ClassificationError(f"prediction 文件不可读取：{exc}") from exc
    if not isinstance(value, dict) or value.get("split") != split:
        raise ClassificationError("prediction split 与请求不一致")
    version = value.get("scorer_version")
    if not isinstance(version, str) or not version.strip():
        raise ClassificationError("prediction scorer_version 不能为空")
    rows = value.get("samples")
    if not isinstance(rows, list):
        raise ClassificationError("prediction samples 必须为数组")
    corpora = build_classification_corpora()
    corpus = {sample["id"]: sample for sample in corpora[split]}
    if split == "held-out":
        frozen = load_frozen_heldout()
        if frozen["corpus_fingerprint"] != verify_heldout(corpora[split]):
            raise ClassificationError("held-out fingerprint 不冻结")
    predictions = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) - {"id", "candidates", "scorer_version", "expected"}:
            raise ClassificationError("prediction row 含未知字段")
        sample_id = row.get("id")
        if sample_id not in corpus or sample_id in predictions:
            raise ClassificationError(f"prediction id 未知或重复：{sample_id}")
        if "expected" in row and row["expected"] != corpus[sample_id]["expected"]:
            raise ClassificationError(f"prediction expected 标签与冻结语料不符：{sample_id}")
        row_version = row.get("scorer_version", version)
        if row_version != version:
            raise ClassificationError("prediction scorer_version 不一致")
        predictions[sample_id] = {"scorer_version": version, "candidates": row.get("candidates")}
    if set(predictions) != set(corpus):
        raise ClassificationError("prediction samples 必须覆盖 calibration/held-out 全量且不得增减")
    # Validate every candidate shape before any threshold selection starts.
    for sample_id, prediction in predictions.items():
        classify_record({"id": sample_id}, prediction)
    return predictions, {"split": split, "scorer_version": version,
                         "samples": len(predictions),
                         "fingerprint": canonical_digest([{"id": key, **predictions[key]}
                                                          for key in sorted(predictions)])}
