#!/usr/bin/env python3
"""M245: RFC-20261125-01 P1 migration gate.

First paragraph declaration: M245 removes the automatic legacy-candidate vs
observed-code STALE branch; tests/test_legacy_migration.py must turn red. The
four-stage mutation_proof evidence is stored under .atlas/runs/mutation-proof/.

This validator never edits legacy documents. It checks pointer/generation
integrity, versioned artifact schemas, current source hashes, conflict reports
and real test evidence. PASS/STALE/UNVERIFIED are preserved in JSON; malformed
artifacts are FAIL. STALE/FAIL rc=1 and UNVERIFIED rc=2.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _support.governance_io import GenerationStore, GovernancePathError, load_json, safe_path
from _support.governance_schema import canonical_digest, validate
from _support.legacy_migration import ARTIFACTS, ARTIFACT_SCHEMAS, _commit, _ensure_git_metadata, _environment_digest, _head_paths, _index_hash, _indexed_paths, _inventory, _python_test_nodes, _tree_hash

_MANIFEST_SCHEMA = {
    "$id": "atlas:migration-manifest:v1", "type": "object", "additionalProperties": False,
    "required": ["schema_version", "module", "mode", "generation", "business_digest", "path",
                 "previous_generation", "previous_pointer", "files"],
    "properties": {
        "schema_version": {"const": 1}, "module": {"const": "migration"},
        "mode": {"enum": ["shadow", "enforce", "off"]},
        "generation": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "business_digest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "path": {"type": "string", "pattern": "^generations/[0-9a-f]{64}$"},
        "previous_generation": {"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"},
        "previous_pointer": {"type": ["object", "null"]},
        "files": {"type": "object", "additionalProperties": False,
                  "required": list(ARTIFACTS),
                  "properties": {name: {"type": "string", "pattern": "^[0-9a-f]{64}$"} for name in ARTIFACTS}},
    },
}


def _result(verdict: str, rc: int, findings: list[dict], cause: str | None = None,
            mode: str = "enforce") -> dict:
    return {"schema_version": 1, "module": "migration", "mode": mode,
            "verdict": verdict, "cause": cause, "rc": rc, "findings": findings}


def _finding(message: str, path: str | None = None, kind: str = "migration") -> dict:
    cause = {"source_stale": "contract_stale", "legacy_stale": "contract_stale",
             "test_unverified": "migration_unverified", "unverified_intent": "migration_unverified",
             "unknown_format": "migration_unverified", "parse_error": "migration_unverified",
             "adapter_error": "migration_unverified", "adapter_parse_warning": "migration_unverified",
             "adapter_pointer": "migration_unverified", "route_unverified": "migration_unverified",
             "fact_line_unverified": "migration_unverified"}.get(kind, "migration_integrity")
    return {"cause": cause, "message": message, **({"path": path} if path else {})}


def check_migration(root: str | Path) -> dict:
    """Read and validate the current migration generation without changing it."""
    root = Path(root).absolute()
    try:
        safe_path(root, ".")
        store = GenerationStore(root)
        if not store.pointer_path.exists():
            return _result("UNVERIFIED", 2, [_finding("无 migration manifest；尚未执行迁移", str(store.pointer_path))], "migration_unverified")
        manifest = store.read_pointer()
    except (OSError, ValueError, GovernancePathError) as exc:
        return _result("UNVERIFIED", 2, [_finding(f"manifest 不可读取：{exc}")], "migration_unverified")
    mode = manifest.get("mode", "enforce")

    def result(verdict: str, rc: int, findings: list[dict], cause: str | None = None) -> dict:
        if mode == "off":
            return _result("UNVERIFIED", 2, findings, None, mode)
        if verdict == "FAIL" and cause is None:
            cause = "migration_integrity"
        return _result(verdict, 0 if mode == "shadow" else rc, findings, cause, mode)

    try:
        git_repo = _ensure_git_metadata(root)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return result("UNVERIFIED", 2, [_finding(f"git 元数据不可判定：{exc}")], "migration_unverified")

    errors = validate(manifest, _MANIFEST_SCHEMA)
    if errors:
        return result("FAIL", 1, [_finding("manifest schema: " + "; ".join(errors), "manifest.json", "schema")])
    if manifest["generation"] != manifest["business_digest"]:
        return result("FAIL", 1, [_finding("generation 与 business_digest 不一致", "manifest.json", "pointer")])
    if manifest["path"] != f"generations/{manifest['generation']}":
        return result("FAIL", 1, [_finding("指针路径与代际摘要不一致", "manifest.json", "pointer")])
    previous_pointer = manifest["previous_pointer"]
    if manifest["previous_generation"] is None:
        if previous_pointer is not None:
            return result("FAIL", 1, [_finding("无上一代却携带 previous_pointer", "manifest.json", "pointer")])
    elif not isinstance(previous_pointer, dict) or previous_pointer.get("generation") != manifest["previous_generation"]:
        return result("FAIL", 1, [_finding("previous_pointer 与 previous_generation 不一致", "manifest.json", "pointer")])
    generation = root / ".adapter-out/migration" / manifest["path"]
    artifacts: dict[str, dict] = {}
    actual_hashes: dict[str, str] = {}
    try:
        safe_path(root, f".adapter-out/migration/{manifest['path']}")
        if not generation.is_dir() or generation.is_symlink():
            return result("FAIL", 1, [_finding("代际目录不存在或为符号链接", manifest["path"], "generation")])
        entries = list(generation.iterdir())
        if {entry.name for entry in entries} != set(ARTIFACTS) \
                or any(not entry.is_file() or entry.is_symlink() for entry in entries):
            return result("FAIL", 1, [_finding("代际目录文件清单不完整或含额外条目", manifest["path"], "generation")])
        for name in ARTIFACTS:
            path = generation / name
            safe_path(root, f".adapter-out/migration/{manifest['path']}/{name}")
            if not path.is_file() or path.is_symlink():
                return result("FAIL", 1, [_finding("代际产物缺失或为符号链接", f"{manifest['path']}/{name}", "generation")])
            raw = path.read_bytes()
            actual_hashes[name] = hashlib.sha256(raw).hexdigest()
            value = load_json(path)
            schema_errors = validate(value, ARTIFACT_SCHEMAS[name])
            if schema_errors:
                return result("FAIL", 1, [_finding(f"{name} schema: " + "; ".join(schema_errors), name, "schema")])
            artifacts[name] = value
    except OSError as exc:
        return result("UNVERIFIED", 2, [_finding(f"代际 I/O 不可判定：{exc}", manifest["path"], "test_unverified")], "migration_unverified")
    except (ValueError, GovernancePathError) as exc:
        return result("FAIL", 1, [_finding(f"代际不可读取：{exc}", manifest["path"], "generation")])
    stale = artifacts["stale.json"]["items"]
    contracts = artifacts["contracts.json"]["items"]
    stale_findings = [_finding(f"旧文档 {item['kind']} 候选与代码事实冲突",
                               item["source"]["path"], "legacy_stale") for item in stale]
    evidence = artifacts["test-evidence.json"]
    if not evidence["verified"]:
        return result("UNVERIFIED", 2, [_finding(evidence.get("reason") or "测试未真跑或未通过", "test-evidence.json", "test_unverified")] + stale_findings, "migration_unverified")
    if evidence.get("commit") != _commit(root) or evidence.get("tree_hash") != _tree_hash(root) \
            or evidence.get("environment_digest") != _environment_digest():
        return result("UNVERIFIED", 2, [_finding("测试证据 commit/tree/环境与当前不一致", "test-evidence.json", "test_unverified")] + stale_findings, "migration_unverified")
    recorded_sources = artifacts["source-manifest.json"]["sources"]
    test_files = [item["path"] for item in recorded_sources if item["role"] == "test" and item["path"].endswith(".py")]
    if not set(_python_test_nodes(root, test_files)) <= set(evidence["nodes"]):
        return result("UNVERIFIED", 2, [_finding("测试证据未覆盖当前发现的全部 Python 测试节点", "test-evidence.json", "test_unverified")] + stale_findings, "migration_unverified")
    if evidence["verified"] and (not evidence["ran"] or evidence["exit_code"] != 0
                                  or not evidence["command"] or not evidence["nodes"]):
        return result("FAIL", 1, [_finding("测试证据自相矛盾", "test-evidence.json", "schema")])
    for name in ARTIFACTS:
        if actual_hashes[name] != manifest["files"][name]:
            return result("FAIL", 1, [_finding("代际产物哈希与指针不一致", f"{manifest['path']}/{name}", "pointer")])
    if canonical_digest(artifacts) != manifest["business_digest"]:
        return result("FAIL", 1, [_finding("business_digest 与六份产物不符", "manifest.json", "pointer")])

    if stale != [item for item in contracts if item["status"] == "STALE"]:
        return result("FAIL", 1, [_finding("stale.json 与 contracts.json 的 STALE 集合不一致", "stale.json", "schema")])
    if any(item["status"] == "UNVERIFIED" for item in contracts):
        return result("UNVERIFIED", 2, [_finding("存在无法对账的旧文档候选意图", "contracts.json", "unverified_intent")] + stale_findings, "migration_unverified")
    if artifacts["parse-errors.json"]["items"]:
        return result("UNVERIFIED", 2, [
            _finding(f"{item['kind']}: {item['message']}", item.get("path"), item["kind"])
            for item in artifacts["parse-errors.json"]["items"]] + stale_findings, "migration_unverified")

    recorded = artifacts["source-manifest.json"]["sources"]
    by_path = {item["path"]: item for item in recorded}
    if len(by_path) != len(recorded):
        return result("FAIL", 1, [_finding("source manifest 路径重复", "source-manifest.json", "schema")])
    findings: list[dict] = []
    for rel in sorted(_indexed_paths(root) - set(by_path)):
        findings.append(_finding("staged index 含未登记的源文件", rel, "source_stale"))
    for rel in sorted(_head_paths(root) - _indexed_paths(root)):
        findings.append(_finding("HEAD 源文件已被暂存删除", rel, "source_stale"))
    current_hashes: dict[str, str] = {}
    for item in recorded:
        try:
            if git_repo and _index_hash(root, item["path"]) != item["sha256"]:
                findings.append(_finding("源文件与 staged index 不一致", item["path"], "source_stale"))
            path = safe_path(root, item["path"])
            if path.is_symlink():
                findings.append(_finding("源文件为符号链接", item["path"], "source_unsafe"))
            elif not path.is_file():
                findings.append(_finding("源文件缺失", item["path"], "source_stale"))
            else:
                raw = path.read_bytes()
                current_hashes[item["path"]] = hashlib.sha256(raw).hexdigest()
                if current_hashes[item["path"]] != item["sha256"]:
                    findings.append(_finding("源文件哈希已变化", item["path"], "source_stale"))
        except (OSError, ValueError, GovernancePathError) as exc:
            findings.append(_finding(f"源路径不安全：{exc}", item["path"], "source_unsafe"))
    for fact in artifacts["facts.json"]["facts"]:
        source = fact["source"]
        rel = source["path"]
        if rel.startswith("adapters/") and rel not in by_path:
            adapter_path = Path(__file__).resolve().parents[1] / rel
            if not adapter_path.is_file() or hashlib.sha256(adapter_path.read_bytes()).hexdigest() != source["sha256"]:
                return result("FAIL", 1, [_finding("事实的 adapter 来源哈希不一致", rel, "fact_source")])
            continue
        row = by_path.get(rel)
        if row is None or row["sha256"] != source["sha256"]:
            return result("FAIL", 1, [_finding("事实来源未登记或哈希不一致", rel, "fact_source")])
        if "line" in source:
            try:
                lines = safe_path(root, rel).read_text(encoding="utf-8").splitlines()
                if source["line"] > len(lines):
                    return result("FAIL", 1, [_finding("事实来源行号越界", rel, "fact_source")])
                if fact["adapter"] == "models" and fact["value"].get("field") not in lines[source["line"] - 1]:
                    return result("FAIL", 1, [_finding("模型事实行号未锚定字段名", rel, "fact_source")])
            except (OSError, UnicodeDecodeError, ValueError):
                return result("FAIL", 1, [_finding("事实来源不可读取", rel, "fact_source")])
    for item in contracts:
        source = item["source"]
        row = by_path.get(source["path"])
        if row is None or row["sha256"] != source["sha256"]:
            return result("FAIL", 1, [_finding("候选意图来源未登记或哈希不一致", source["path"], "contract_source")])
    try:
        current, current_errors, _ = _inventory(root)
        if current_errors:
            return result("UNVERIFIED", 2, [
                _finding(f"{item['kind']}: {item['message']}", item.get("path"), item["kind"])
                for item in current_errors], "migration_unverified")
        current_paths = {item["path"] for item in current["sources"]}
        for path in sorted(current_paths - set(by_path)):
            findings.append(_finding("发现未登记的新源文件", path, "source_stale"))
        for path in sorted(set(by_path) - current_paths):
            findings.append(_finding("已登记源文件已消失", path, "source_stale"))
    except (OSError, ValueError, GovernancePathError) as exc:
        return result("UNVERIFIED", 2, [_finding(f"当前源清单无法重算：{exc}")], "migration_unverified")
    unsafe = [item for item in findings if item["cause"] == "migration_integrity"]
    if unsafe:
        return result("FAIL", 1, unsafe)
    if findings:
        return result("STALE", 1, findings, "contract_stale")
    if stale:
        return result("STALE", 1, [
            _finding(f"旧文档 {item['kind']} 候选与代码事实冲突", item["source"]["path"], "legacy_stale")
            for item in stale], "contract_stale")
    return result("PASS", 0, [])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        result = check_migration(args.root)
    except Exception as exc:  # fail closed: validator must never crash into a false PASS
        result = _result("UNVERIFIED", 2, [_finding(f"校验器异常：{type(exc).__name__}: {exc}")], "migration_unverified")
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        print(f"[{result['verdict']}] migration rc={result['rc']} cause={result['cause']}")
        for item in result["findings"]:
            location = item.get("path") or "migration"
            print(f"[{result['verdict']}] {location}: {item['message']}")
        if result["verdict"] == "PASS" and not result["findings"]:
            print("[PASS] migration manifest/schema/source/generation/test evidence 全部一致")
    return result["rc"]


if __name__ == "__main__":
    sys.exit(main())
