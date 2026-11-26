"""Deterministic expansion of the frozen RFC-20261125-01 held-out specification."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from _support.governance_schema import canonical_digest

SCHEMAS = Path(__file__).resolve().parent.parent / "shared" / "schemas"


def expand_heldout(spec: dict | None = None) -> dict[str, list[dict]]:
    spec = spec or json.loads((SCHEMAS / "heldout-spec.json").read_text(encoding="utf-8"))
    result: dict[str, list[dict]] = {key: [] for key in (
        "semantic", "docs", "incident", "topology", "receipt", "classification")}
    domains = spec["domains"]
    for index, domain in enumerate(domains["semantic"]):
        field = f"{domain}Reference"
        for mutation, verdict in (("same", "PASS"), ("type", "FAIL"), ("required", "FAIL")):
            expected = {"kind": "field", "name": field, "type": "string", "required": index % 2 == 0}
            observed = dict(expected)
            if mutation == "type":
                observed["type"] = "integer"
            elif mutation == "required":
                observed["required"] = not expected["required"]
            result["semantic"].append({"id": f"H-SEM-{index:02d}-{mutation}", "input": {"expected": expected, "observed": observed}, "expected": verdict})
        values = [f"{domain}_draft", f"{domain}_final"]
        for mutation, verdict in (("same", "PASS"), ("extra", "FAIL")):
            observed = list(values) + ([f"{domain}_archived"] if mutation == "extra" else [])
            result["semantic"].append({"id": f"H-ENUM-{index:02d}-{mutation}", "input": {"expected": {"kind": "enum", "name": f"{domain}State", "values": values}, "observed": {"kind": "enum", "name": f"{domain}State", "values": observed}}, "expected": verdict})
        for mutation, verdict in (("same", "PASS"), ("rename", "FAIL")):
            result["semantic"].append({"id": f"H-TID-{index:02d}-{mutation}", "input": {"expected": {"kind": "testid", "value": f"{domain}-row"}, "observed": {"kind": "testid", "value": f"{domain}-row" if mutation == "same" else f"{domain}-item"}}, "expected": verdict})
    for index, topic in enumerate(domains["docs"]):
        for mutation, verdict in (("same", "PASS"), ("updated", "PASS"), ("source", "FAIL"), ("attestation", "WARN")):
            changed = mutation in ("updated", "source", "attestation")
            evidence = None if mutation == "source" else f"review-{topic}-{index:02d}-{mutation}"
            digest = lambda text: hashlib.sha256(text.encode()).hexdigest()
            result["docs"].append({"id": f"H-DOC-{index:02d}-{mutation}", "input": {"document": f"{topic}.md", "document_digest": digest(f"doc-{index}-{mutation}"), "source_digest": digest(f"source-{index}-new"), "recorded_source_digest": digest(f"source-{index}-new" if mutation in ("same", "updated") else f"source-{index}-old"), "recorded_document_digest": digest(f"doc-{index}-{mutation}"), "evidence": evidence, "attestation": mutation == "attestation", "source_changed": changed}, "expected": verdict})
    for index, kind in enumerate(domains["incident"]):
        for case, verdict in (("verified", "PASS"), ("unverified", "FAIL"), ("overdue", "FAIL"), ("rollback", "PASS")):
            verified = case in ("verified", "rollback")
            result["incident"].append({"id": f"H-INC-{index:02d}-{case}", "input": {"status": "contained" if case == "rollback" else "closed", "root_cause_evidence": [f"cause-{index}-{case}"] if verified else [], "verification_evidence": [f"verify-{index}-{case}"] if verified else [], "verified_by": f"owner-{index}" if verified else None, "verified_at": "2026-11-25T00:00:00Z" if verified else None, "actions_valid": case != "overdue", "timeline_closed": case != "rollback", "rollback_reason": "containment failed" if case == "rollback" else None}, "expected": verdict})
    for fmt in domains["topology"]:
        for index, service in enumerate(domains["semantic"]):
            source = f"{fmt}-{service}.yaml"
            for mutation, verdict in (("same", "PASS"), ("changed", "STALE"), ("dangling", "FAIL")):
                if fmt == "compose":
                    text = f"services:\n  {service}:\n    image: demo/{service}:1\n    ports:\n      - \"8080:8080\"\n"
                    if mutation == "changed":
                        text = text.replace("8080", "9090")
                    if mutation == "dangling":
                        text += "    depends_on:\n      - missing\n"
                elif fmt == "helm":
                    text = f"apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: {service}\nspec:\n  template:\n    spec:\n      containers:\n        - name: {service}\n          image: demo/{service}:1\n          ports:\n            - containerPort: 8080\n"
                    if mutation == "changed":
                        text = text.replace("8080", "9090")
                    if mutation == "dangling":
                        text += "          volumeMounts:\n            - name: missing\n              mountPath: /data\n      volumes:\n        - name: other\n          emptyDir: {}\n"
                else:
                    text = f"_format_version: \"3.0\"\nservices:\n  - name: {service}\n    url: http://{service}:8080\nroutes:\n  - name: {service}-route\n    paths:\n      - /{service}\n"
                    if mutation == "changed":
                        text = text.replace("8080", "9090")
                    if mutation == "dangling":
                        text += f"  - name: {service}-missing\n    service:\n      name: missing\n"
                source_digest = hashlib.sha256(text.encode()).hexdigest()
                result["topology"].append({"id": f"H-TOP-{fmt}-{index:02d}-{mutation}", "input": {"format": fmt, "source": source, "source_text": text, "source_digest": source_digest, "recorded_digest": source_digest if mutation == "same" else hashlib.sha256(b"old").hexdigest(), "fields_static": True, "edges_valid": mutation != "dangling"}, "expected": verdict})
            if fmt == "compose":
                dynamic_text = f"services:\n  {service}:\n    image: ${{IMAGE}}\n    ports:\n      - \"${{PORT}}:8080\"\n"
                dynamic_fields = ["image", "ports"]
            elif fmt == "helm":
                dynamic_text = f"image: ${{IMAGE}}\nname: {service}\n"
                dynamic_fields = ["image"]
            else:
                dynamic_text = f"services:\n  - name: {service}\n    url: http://${{UPSTREAM}}:8080\n"
                dynamic_fields = ["url"]
            dynamic_digest = hashlib.sha256(dynamic_text.encode()).hexdigest()
            result["topology"].append({"id": f"H-TOP-{fmt}-{index:02d}-dynamic", "input": {"format": fmt, "source": source, "source_text": dynamic_text, "source_digest": dynamic_digest, "recorded_digest": dynamic_digest, "fields_static": False, "dynamic_fields": dynamic_fields, "edges_valid": True}, "expected": "UNVERIFIED"})
    for index in range(spec["receipt_positive"]):
        result["receipt"].append({"id": f"H-RCP-P-{index}", "input": {"base_reachable": True, "patch_applies": True, "tree_matches": True, "direct_review": False, "forced": False, "fresh_checkout": True, "base": f"{index:040x}", "patch_sha256": f"{index + 1:064x}", "tree_hash": f"{index + 2:040x}", "binary_patch": index % 2 == 0}, "expected": "PASS"})
    for index, mutation in enumerate(("direct_review", "forced", "tree_mismatch", "old_receipt")):
        sample = {"base_reachable": True, "patch_applies": True, "tree_matches": True, "direct_review": False, "forced": False, "fresh_checkout": True}
        if mutation == "tree_mismatch":
            sample["tree_matches"] = False
        elif mutation == "old_receipt":
            sample["fresh_checkout"] = False
        else:
            sample[mutation] = True
        result["receipt"].append({"id": f"H-RCP-N-{index}", "input": sample, "expected": "FAIL"})
    texts = {
        "initial": ["从零搭建{}模块并建立初始需求", "新项目需要实现{}能力", "请为{}创建第一版功能"],
        "change": ["修改现有{}的工作方式", "在已有{}上增加新规则", "调整{}当前实现的行为"],
        "bug": ["修复{}不符合预期的问题", "{}现在出现回归需要纠正", "现有{}故障请排查并修复"],
    }
    for label, templates in texts.items():
        for index in range(spec["classification_samples_per_class"]):
            domain = domains["semantic"][index % len(domains["semantic"])]
            text = templates[index % len(templates)].format(domain) + f" 场景{index:02d}"
            result["classification"].append({"id": f"H-CLS-{label}-{index:02d}", "input": {"text": text}, "expected": label})
        for index in range(10):
            result["classification"].append({"id": f"H-CLS-{label}-abstain-{index:02d}", "input": {"text": f"请看一下{domains['semantic'][index]}，好像不太对"}, "expected": "abstain"})
    for samples in result.values():
        for sample in samples:
            sample["fingerprint"] = canonical_digest({"split": "held-out", **sample})
    return result
