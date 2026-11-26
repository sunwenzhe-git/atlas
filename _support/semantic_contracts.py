"""RFC-20261125-01 §6 read-only semantic contract reconciliation.

Expected contracts are never inferred from code or legacy documents. Observed
facts are projections of the existing routes/api/models/tests adapters and the
existing testid extractor; this module only reconciles and anchors them.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager, nullcontext
from pathlib import Path

from _support.governance_io import GovernancePathError, atomic_write_bytes, atomic_write_json, load_json, safe_path
from _support.governance_schema import canonical_bytes, canonical_digest, load_schema, validate
from _support.layout import load_layout

MODULE = "semantic"
MODES = ("shadow", "enforce", "off")
STORE_NAMES = ("expected", "observed", "graph")
UNSUPPORTED_ADAPTER_KINDS = {"ac", "error_code", "config", "cli", "state"}


class SemanticError(ValueError):
    """A semantic input, adapter projection, or contract store is unsafe."""


class SemanticIntegrityError(SemanticError):
    """A published semantic generation or pointer is damaged."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _mode(value: str | None, root: str | Path | None = None) -> str:
    selected = value or os.environ.get("ATLAS_SEMANTIC_MODE")
    if not selected:
        path = Path(root or Path.cwd()).absolute() / ".atlas/config.yaml"
        if path.is_file() and not path.is_symlink():
            config_text = path.read_text(encoding="utf-8")
            match = re.search(r"^\s*semantic_mode\s*:\s*['\"]?(shadow|enforce|off)['\"]?\b",
                              config_text, re.M)
            if re.search(r"^\s*semantic_mode\s*:", config_text, re.M) and not match:
                raise SemanticError("semantic_mode 配置非法")
            selected = match.group(1) if match else None
    selected = selected or "shadow"
    if selected not in MODES:
        raise SemanticError("mode 必须为 shadow/enforce/off")
    return selected


def semantic_mode(root: str | Path) -> str:
    return _mode(None, root)


def _finding(message: str, cause: str = "contract_unverified", **extra) -> dict:
    return {"cause": cause, "message": message, **extra}


def _result(verdict: str, rc: int, findings: list[dict], cause: str | None = None,
            mode: str = "shadow", **extra) -> dict:
    if mode == "off":
        verdict, rc, cause = "UNVERIFIED", 2, None
    elif mode == "shadow":
        rc = 0
    return {"schema_version": 1, "module": MODULE, "mode": mode,
            "verdict": verdict, "cause": cause, "rc": rc, "findings": findings, **extra}


def semantic_error_result(exc: Exception, mode: str | None = None, root: str | Path | None = None) -> dict:
    try:
        selected = _mode(mode, root)
    except SemanticError:
        selected = "enforce"
    cause = None if selected == "off" else "contract_unverified"
    return _result("UNVERIFIED", 2, [_finding(f"{type(exc).__name__}: {exc}")],
                   cause, selected, path="contracts")


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SemanticError(f"git 不可用：{exc}") from exc
    if result.returncode != 0:
        raise SemanticError(result.stderr.strip() or f"git {' '.join(args)} 失败")
    return result.stdout.strip()


def _git_bytes(root: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(["git", *args], cwd=root, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SemanticError(f"git 不可用：{exc}") from exc
    if result.returncode != 0:
        raise SemanticError(result.stderr.decode("utf-8", "replace").strip() or f"git {' '.join(args)} 失败")
    return result.stdout


def _revision(root: Path, commit: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{7,40}", commit):
        raise SemanticError(f"非法 revision：{commit}")
    full = _git(root, "rev-parse", "--verify", f"{commit}^{{commit}}")
    tree = _git(root, "rev-parse", f"{full}^{{tree}}")
    return {"commit": full, "digest": canonical_digest({"commit": full, "tree": tree})}


def _run_adapter(root: Path, name: str, out: Path) -> dict:
    command = [sys.executable, str(Path(__file__).resolve().parents[1] / "adapters" / f"{name}.py"),
               "--root", str(root), "--out", str(out)]
    try:
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SemanticError(f"adapter {name} 执行失败：{exc}") from exc
    if result.returncode != 0:
        raise SemanticError(f"adapter {name} 失败 rc={result.returncode}: {result.stdout}{result.stderr}")
    return load_json(out)


def _blob_bytes(root: Path, revision: str, rel: str) -> bytes | None:
    try:
        spec = f":{rel}" if revision == ":0" else f"{revision}:{rel}"
        result = subprocess.run(["git", "show", spec], cwd=root,
                                capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def _blob_digest(root: Path, revision: str, rel: str) -> str | None:
    data = _blob_bytes(root, revision, rel)
    return _sha(data) if data is not None else None


def _source(source_root: Path, git_root: Path, rel: str, line: int | None,
            hashes: dict[str, str], revision: str = ":0") -> dict:
    if not rel:
        raise SemanticError("adapter 事实缺少 source file")
    line = line or 1
    path = safe_path(source_root, rel)
    if not path.is_file() or path.is_symlink():
        raise SemanticError(f"事实来源不是普通文件：{rel}")
    raw = path.read_bytes()
    digest = _sha(raw)
    if digest != _blob_digest(git_root, revision, rel):
        raise SemanticError(f"事实来源与 {revision} blob 不一致：{rel}")
    if rel in hashes and hashes[rel] != digest:
        raise SemanticError(f"事实来源哈希不一致：{rel}")
    hashes[rel] = digest
    if line > len(raw.splitlines()):
        raise SemanticError(f"事实来源行号越界：{rel}:{line}")
    return {"path": rel, "line": line, "sha256": digest}


def _anchor(item: dict, fallback_line: int | None = None) -> tuple[str | None, int | None]:
    rel = item.get("source_file") or item.get("source_module") or item.get("location")
    line = item.get("line") or fallback_line
    if rel and re.search(r":\d+$", str(rel)):
        rel, suffix = str(rel).rsplit(":", 1)
        line = line or int(suffix)
    return (str(rel) if rel else None), line


def _field_type(value: object) -> str:
    text = str(value or "").strip()
    enum = re.match(r"Enum\(\s*['\"]([^'\"]+)", text, re.I)
    if enum:
        return enum.group(1)
    simple = {"str": "string", "string": "string", "int": "integer", "integer": "integer",
              "bool": "boolean", "boolean": "boolean", "float": "number", "number": "number",
              "datetime": "datetime", "date": "date", "json": "object", "object": "object",
              "array": "array"}
    return simple.get(text.lower(), text)


def _required(item: dict) -> bool | None:
    constraints = str(item.get("constraints") or "")
    if "非空" in constraints or "主键" in constraints:
        return True
    if "可空" in constraints:
        return False
    return None


def _fact(fact_id: str, kind: str, value: dict, version: str, source: dict) -> dict:
    return {"id": fact_id, "kind": kind, "value": value,
            "adapter_version": version, "source": source}


def _testid_facts(source_root: Path, git_root: Path, hashes: dict[str, str], errors: list[str],
                  extractor, version: str | None, revision: str = ":0") -> tuple[list[dict], str | None]:
    if extractor is None or not version:
        errors.append("testid extractor 未注入，testid 事实不可判定")
        return [], None
    vt = extractor
    try:
        globs = vt.app_globs(source_root)
        per_page, _counts, files, _expanded, _dups = vt.collect_testids_expanded(source_root, globs)
        layout = load_layout(source_root)
        states = vt.index_page_states(source_root, layout) or {}
        shard_pages = sorted(p.stem for p in layout.e2e_cases_dir.glob("*.md")) if layout.e2e_cases_dir.is_dir() else []
        all_values = {value for values in per_page.values() for value in values}
        pages = sorted(set(states) | set(shard_pages) | {v.split("-", 1)[0] for v in all_values})
    except (OSError, ValueError, RuntimeError) as exc:
        errors.append(f"testid extractor 不可用：{exc}")
        return [], version
    facts: list[dict] = []
    for rel in files:
        try:
            path = safe_path(source_root, rel)
            original = path.read_text(encoding="utf-8")
            clean = vt.strip_comments(original)
            declarations, _occurrences, expanded = vt.file_testid_decls(clean, pages)
            templates = (vt.TEMPLATE_TESTID_ATTR.findall(clean) + vt.DATASET_TESTID_TPL.findall(clean)
                         + vt.SETATTR_TESTID_TPL.findall(clean))
            if templates and not expanded:
                errors.append(f"动态 testid 不可枚举：{rel}")
            for value in sorted(declarations | expanded):
                line = next((number for number, text in enumerate(original.splitlines(), 1)
                             if value in text), None)
                if line is None:
                    line = next((number for number, text in enumerate(original.splitlines(), 1)
                                 if "data-testid" in text or ".dataset" in text or "setAttribute" in text), None)
                source = _source(source_root, git_root, rel, line, hashes, revision)
                facts.append(_fact(f"testid:{rel}:{line}:{value}", "testid", {"value": value}, version, source))
        except (OSError, UnicodeError, ValueError, GovernancePathError) as exc:
            errors.append(f"testid 来源不可投影：{rel}: {exc}")
    return facts, version


def _project_adapters(root: Path, base: dict, head: dict, testid_extractor=None,
                      testid_version: str | None = None) -> dict:
    facts: list[dict] = []
    sources: list[dict] = []
    errors: list[str] = []
    hashes: dict[str, str] = {}
    versions: list[str] = []
    try:
        committed_paths = _git_bytes(root, "diff", "--name-only", "-z",
                                     base["commit"], head["commit"]).decode("utf-8", "surrogateescape")
        staged_paths = _git_bytes(root, "diff", "--cached", "--name-only", "-z").decode("utf-8", "surrogateescape")
        changed_paths = {item for item in (committed_paths + staged_paths).split("\0") if item}
        changed_paths = {path for path in changed_paths if not path.startswith("contracts/")
                         and path != ".atlas/runs/workflow-review-origin.json"
                         and not path.startswith(".atlas/runs/workflow-receipt/")}
    except SemanticError:
        raise SemanticError("semantic diff 不可判定，拒绝生成 observed")
    revision = head["commit"] if head["commit"] != base["commit"] else ":0"
    with tempfile.TemporaryDirectory(prefix="atlas-semantic-index-") as snapshot, \
            tempfile.TemporaryDirectory(prefix="atlas-semantic-tree-index-") as index_dir:
        source_root = Path(snapshot)
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(index_dir) / "index")) if revision != ":0" else None
        try:
            if revision != ":0":
                read_tree = subprocess.run(["git", "read-tree", revision], cwd=root, env=env,
                                           capture_output=True, text=True, timeout=60)
                if read_tree.returncode != 0:
                    raise SemanticError("head tree 不可读取：" + read_tree.stderr.strip())
            checked_out = subprocess.run(["git", "checkout-index", "--all", f"--prefix={source_root}/"],
                                         cwd=root, env=env, capture_output=True, text=True, timeout=120)
        except SemanticError as exc:
            raise SemanticError(f"语义源树不可物化：{exc}") from exc
        if checked_out.returncode != 0:
            raise SemanticError("语义源树不可物化：" + checked_out.stderr.strip())
        with tempfile.TemporaryDirectory(prefix="atlas-semantic-adapters-") as temporary:
            for adapter in ("routes", "api", "models", "tests"):
                try:
                    payload = _run_adapter(source_root, adapter, Path(temporary) / f"{adapter}.json")
                    version = str(payload.get("adapter_version") or "unknown")
                    versions.append(f"{adapter}@{version}")
                    if payload.get("spec_entry"):
                        errors.append(f"api adapter 只有描述指针，字段不可静态判定：{payload['spec_entry']}")
                    coverage = payload.get("route_coverage") or {}
                    for skipped in coverage.get("skipped") or []:
                        errors.append(f"动态路由不可判定：{skipped.get('file')}: {skipped.get('reason')}")
                    for index, item in enumerate(payload.get("items") or []):
                        rel, line = _anchor(item, 1 if adapter == "tests" else None)
                        if adapter == "routes":
                            kind, value = "route", {"path": item.get("path"), "method": None}
                        elif adapter == "api":
                            kind, value = "route", {"path": item.get("path"), "method": item.get("method")}
                        elif adapter == "models":
                            kind = "field"
                            value = {"name": item.get("field"), "type": _field_type(item.get("type")),
                                     "required": _required(item), "table": item.get("table")}
                        else:
                            kind, value = "tests", {"location": item.get("location")}
                        source = _source(source_root, root, rel, line, hashes, revision)
                        facts.append(_fact(f"{adapter}:{index:06d}", kind, value, version, source))
                    if adapter == "models":
                        field_facts = {(fact["value"].get("table"), fact["value"].get("name")): fact
                                       for fact in facts if fact["kind"] == "field"}
                        field_meta = {key: fact["value"] for key, fact in field_facts.items()}
                        field_sources = {key: fact["source"] for key, fact in field_facts.items()}
                        for index, item in enumerate(payload.get("enums") or []):
                            rel, line = _anchor(item)
                            key = (item.get("table"), item.get("field"))
                            meta = field_meta.get(key) or {}
                            source = field_sources.get(key)
                            if source is None:
                                if not rel:
                                    errors.append(f"枚举缺少来源锚：{item.get('field')}")
                                    continue
                                source = _source(source_root, root, rel, line, hashes, revision)
                            values = [row.get("value") for row in item.get("values") or []]
                            enum_type = _field_type(meta.get("type"))
                            if values and values[0] == enum_type and enum_type not in ("枚举", ""):
                                values = values[1:]
                            name = enum_type if enum_type not in ("枚举", "") else item.get("field")
                            value = {"name": name, "field": item.get("field"), "table": item.get("table"),
                                     "values": values}
                            facts.append(_fact(f"models-enum:{index:06d}", "enum", value, version, source))
                except (OSError, ValueError, RuntimeError, GovernancePathError) as exc:
                    errors.append(f"adapter {adapter} 不可用：{exc}")
        testids, testid_version = _testid_facts(source_root, root, hashes, errors,
                                                testid_extractor, testid_version, revision)
        facts.extend(testids)
    if testid_version:
        versions.append(testid_version)
    facts.sort(key=lambda item: item["id"])
    sources = sorted({(item["path"], item["line"], item["sha256"]): item for item in
                      (fact["source"] for fact in facts)}.values(), key=lambda item: (item["path"], item["line"]))
    return {"schema_version": 1, "base": base, "head": head,
            "adapter_version": "|".join(sorted(set(versions))), "facts": facts,
            "changed_paths": sorted(changed_paths),
            "sources": sources, "coverage": {"parsed": len(facts),
            "unverified_fields": sorted({item for item in errors if "动态" in item}),
            "parse_errors": sorted(set(errors))}}


def _route(value: object) -> tuple[str | None, str]:
    if isinstance(value, dict):
        method, path = value.get("method"), value.get("path")
    else:
        text = str(value or "").strip()
        method, _, path = text.partition(" ")
        if not path:
            method, path = None, text
    method = str(method).upper() if method else None
    path = str(path or "").split("#", 1)[0].split("?", 1)[0]
    path = re.sub(r"\{([A-Za-z_]\w*)\}", r":\1", path)
    if path != "/":
        path = path.rstrip("/")
    return method, path or "/"


def _same_identity(kind: str, contract: dict, fact: dict) -> bool:
    value = fact.get("value") or {}
    if kind == "field":
        return contract.get("name") == value.get("name") and (
            not contract.get("table") or contract.get("table") == value.get("table"))
    if kind == "enum":
        return contract.get("name") in (value.get("name"), value.get("field"))
    if kind == "route":
        return _route(contract.get("value"))[1] == _route(value)[1]
    if kind in ("testid", "ac"):
        return contract.get("value") == value.get("value")
    if kind in UNSUPPORTED_ADAPTER_KINDS:
        return canonical_digest(contract.get("value")) == canonical_digest(value.get("value"))
    if kind == "tests":
        wanted = str(contract.get("value") or "").split("::", 1)[0]
        if "::" in str(contract.get("value") or ""):
            return False
        return wanted in (value.get("location"), value.get("value"))
    return False


def reconcile_contract(contract: dict, observed: dict | None) -> dict | None:
    """Return one deterministic finding for a contract/fact pair, or None."""
    kind = contract.get("kind")
    if observed is None:
        return {"verdict": "UNVERIFIED", "cause": "contract_unverified",
                "message": f"条款 {kind} 契约缺少观测证据"}
    if observed.get("kind") == kind and "value" in observed:
        observed = observed["value"]
    if kind in ("testid", "ac", "tests"):
        value = observed if isinstance(observed, dict) else {"value": observed}
    else:
        value = observed.get("value", observed)
    if kind == "field":
        expected = {"name": contract.get("name"), "type": _field_type(contract.get("type")),
                    "required": contract.get("required")}
        actual = {"name": value.get("name"), "type": _field_type(value.get("type")),
                  "required": value.get("required")}
        if actual["required"] is None:
            return {"verdict": "UNVERIFIED", "cause": "contract_unverified",
                    "message": f"字段 {expected['name']} 必填性不可静态判定"}
        if (expected["name"] != actual["name"] or expected["type"] != actual["type"]
                or expected["required"] != actual["required"]):
            return {"verdict": "FAIL", "cause": "contract_stale",
                    "message": f"字段漂移：期望 {expected}，观测 {actual}"}
    elif kind == "enum":
        expected_values = sorted(set(contract.get("values") or []))
        actual_values = sorted(set(value.get("values") or []))
        if contract.get("name") not in (value.get("name"), value.get("field")) or expected_values != actual_values:
            return {"verdict": "FAIL", "cause": "contract_stale",
                    "message": f"枚举漂移：期望 {contract.get('name')}={expected_values}，观测 {value.get('name')}={actual_values}"}
    elif kind == "route":
        expected_method, expected_path = _route(contract.get("value"))
        actual_method, actual_path = _route(value)
        if expected_path != actual_path or (expected_method and actual_method and expected_method != actual_method):
            return {"verdict": "FAIL", "cause": "contract_stale",
                    "message": f"路由漂移：期望 {expected_method} {expected_path}，观测 {actual_method} {actual_path}"}
        if expected_method and not actual_method:
            return {"verdict": "UNVERIFIED", "cause": "contract_unverified",
                    "message": f"路由 {expected_path} 的 HTTP 方法不可静态判定"}
    elif kind in UNSUPPORTED_ADAPTER_KINDS:
        if canonical_digest(contract.get("value")) != canonical_digest(value.get("value")):
            return {"verdict": "FAIL", "cause": "contract_stale",
                    "message": f"{kind} 漂移：期望 {contract.get('value')}，观测 {value.get('value')}"}
    elif kind in ("testid", "ac"):
        if contract.get("value") != value.get("value"):
            return {"verdict": "FAIL", "cause": "contract_stale",
                    "message": f"{kind} 漂移：期望 {contract.get('value')}，观测 {value.get('value')}"}
    elif kind == "tests":
        wanted = str(contract.get("value") or "").split("::", 1)[0]
        if wanted not in (value.get("location"), value.get("value")):
            return {"verdict": "FAIL", "cause": "contract_stale",
                    "message": f"测试锚漂移：期望 {wanted}，观测 {value.get('location')}"}
    else:
        return {"verdict": "UNVERIFIED", "cause": "contract_unverified",
                "message": f"不支持的契约 kind：{kind}"}
    return None


def _select_fact(contract: dict, candidates: list[dict], allow_fallback: bool = True) -> dict | None:
    exact = [fact for fact in candidates if _same_identity(contract["kind"], contract, fact)]
    if exact:
        if contract["kind"] == "route":
            method = _route(contract.get("value"))[0]
            same_method = [fact for fact in exact if _route(fact["value"])[0] == method]
            return sorted(same_method or exact, key=lambda item: item["id"])[0]
        return sorted(exact, key=lambda item: item["id"])[0]
    if allow_fallback and contract["kind"] in ("field", "enum", "route") and len(candidates) == 1:
        return candidates[0]
    return None


def _reconcile_stores(expected: dict, observed: dict, prior_edges: list[dict] | None = None) -> tuple[list[dict], list[dict]]:
    findings: list[dict] = []
    edges: list[dict] = []
    used: set[str] = set()
    prior_counts: dict[str, int] = {}
    for edge in prior_edges or []:
        prior_counts[edge["from"]] = prior_counts.get(edge["from"], 0) + 1
    for clause in expected["clauses"]:
        # A newly added clause/contract has no previous edge to rename. Missing
        # evidence is UNVERIFIED; only an established single candidate can prove
        # a deterministic field/enum/route rename.
        allow_fallback = prior_edges is None or len(clause["contracts"]) <= prior_counts.get(clause["clause_id"], 0)
        for contract in clause["contracts"]:
            candidates = [fact for fact in observed["facts"] if fact["kind"] == contract["kind"]]
            fact = _select_fact(contract, candidates, allow_fallback)
            finding = reconcile_contract(contract, fact)
            if finding and fact is None and finding.get("verdict") == "UNVERIFIED" \
                    and contract["kind"] not in UNSUPPORTED_ADAPTER_KINDS \
                    and not (contract["kind"] == "tests" and "::" in str(contract.get("value", ""))) \
                    and not observed["coverage"]["parse_errors"]:
                finding = {"verdict": "FAIL", "cause": "contract_stale",
                           "message": f"条款 {contract['kind']} 契约无代码/AC/测试证据"}
            if finding:
                findings.append({**finding, "evidence_ref": clause["clause_id"]})
            if fact is None:
                continue
            used.add(fact["id"])
            core = {"from": clause["clause_id"], "to": fact["id"], "kind": "clause_contract_observed",
                    "base": {"commit": observed["base"]["commit"]},
                    "head": {"commit": observed["head"]["commit"]}, "source": fact["source"],
                    "contract": contract}
            edges.append({"id": canonical_digest(core), "base": core["base"], "head": core["head"],
                          "from": clause["clause_id"], "to": fact["id"], "kind": core["kind"],
                          "source": fact["source"], "sha256": canonical_digest(fact["value"]),
                          "adapter_version": fact["adapter_version"]})
    changed_paths = set(observed.get("changed_paths", []))
    for fact in observed["facts"]:
            if fact["id"] not in used and fact["source"]["path"] in changed_paths:
                findings.append({"cause": "contract_stale", "verdict": "FAIL",
                                 "message": f"代码事实未挂条款或请求：{fact['id']}",
                                 "path": fact["source"]["path"], "line": fact["source"]["line"],
                                 "evidence_ref": fact["id"]})
    return findings, edges


def _contracts_dir(root: Path) -> Path:
    return safe_path(root, "contracts")


def _read_store(root: Path, name: str) -> dict:
    directory = _contracts_dir(root)
    path = directory / f"{name}.json"
    manifest_path = directory / "manifest.json"
    manifest = None
    if manifest_path.exists() or manifest_path.is_symlink():
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise SemanticIntegrityError("semantic manifest 缺失或不是普通文件")
        manifest = load_json(manifest_path)
        _verify_published_generation(directory, manifest)
        expected_path = directory / "expected.json"
        if not expected_path.is_file() or expected_path.is_symlink() \
                or _sha(expected_path.read_bytes()) != manifest["files"]["expected.json"]:
            raise SemanticIntegrityError("contracts/expected.json 与当前代际不一致")
    if name != "expected" and manifest is None:
        raise SemanticIntegrityError("semantic manifest 缺失，拒绝回退固定投影")
    if name != "expected" and manifest is not None:
        path = safe_path(directory, f"{manifest['path']}/{name}.json")
    if not path.is_file() or path.is_symlink():
        raise SemanticError(f"缺 semantic {name} 库：contracts/{name}.json")
    return load_json(path)


def _verify_published_generation(directory: Path, manifest: dict) -> None:
    if not isinstance(manifest, dict):
        raise SemanticIntegrityError("semantic manifest 必须为对象")
    generation = manifest.get("generation")
    files = manifest.get("files")
    if not isinstance(generation, str) or not re.fullmatch(r"[0-9a-f]{64}", generation) \
            or manifest.get("business_digest") != generation \
            or manifest.get("path") != f"generations/{generation}" \
            or not isinstance(files, dict) or set(files) != {f"{name}.json" for name in STORE_NAMES}:
        raise SemanticIntegrityError("semantic manifest generation/files 非法")
    target = safe_path(directory, manifest["path"])
    if not target.is_dir() or target.is_symlink():
        raise SemanticIntegrityError("semantic 旧代目录缺失或不是普通目录")
    entries = list(target.iterdir())
    if {entry.name for entry in entries} != set(files) \
            or any(not entry.is_file() or entry.is_symlink() for entry in entries):
        raise SemanticIntegrityError("semantic 旧代目录文件清单不完整")
    stores = {}
    for name, expected in files.items():
        raw = (target / name).read_bytes()
        if _sha(raw) != expected:
            raise SemanticIntegrityError(f"semantic 旧代 hash 不符：{name}")
        stores[name.removesuffix(".json")] = json.loads(raw.decode("utf-8"))
    if canonical_digest(stores) != generation:
        raise SemanticIntegrityError("semantic 旧代 canonical digest 不符")


@contextmanager
def _publication_lock(root: Path):
    directory = _contracts_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = safe_path(root, "contracts/.semantic-publish.lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _expected_snapshot(root: Path) -> tuple[bytes, dict]:
    expected_path = _contracts_dir(root) / "expected.json"
    if not expected_path.is_file() or expected_path.is_symlink():
        raise SemanticError("缺 semantic expected 库：contracts/expected.json")
    expected_raw = expected_path.read_bytes()

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise SemanticIntegrityError(f"expected.json 重复键：{key}")
            value[key] = item
        return value

    return expected_raw, json.loads(expected_raw.decode("utf-8"), object_pairs_hook=unique)


def _publish_stores(root: Path, observed: dict, graph: dict) -> None:
    with _publication_lock(root):
        expected_raw, expected = _expected_snapshot(root)
        _publish_stores_locked(root, expected_raw, expected, observed, graph)


def _publish_stores_locked(root: Path, expected_raw: bytes, expected: dict,
                           observed: dict, graph: dict) -> None:
    directory = _contracts_dir(root)
    manifest_path = directory / "manifest.json"
    prior_manifest = None
    if manifest_path.exists() or manifest_path.is_symlink():
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise SemanticIntegrityError("semantic manifest 缺失或不是普通文件")
        prior_manifest = load_json(manifest_path)
        _verify_published_generation(directory, prior_manifest)
    expected_path = directory / "expected.json"
    if expected_path.read_bytes() != expected_raw:
        raise SemanticError("expected 在投影后已变化，拒绝发布混合代际")
    stores = {"expected": expected, "observed": observed, "graph": graph}
    payload = {f"{name}.json": canonical_bytes(value) + b"\n" for name, value in stores.items()}
    payload["expected.json"] = expected_raw
    digest = canonical_digest(stores)
    generations = safe_path(directory, "generations")
    generations.mkdir(parents=True, exist_ok=True)
    final = safe_path(directory, f"generations/{digest}")
    if final.exists():
        entries = list(final.iterdir())
        if not final.is_dir() or final.is_symlink() or {entry.name for entry in entries} != set(payload) \
                or any(not entry.is_file() or entry.is_symlink() for entry in entries):
            raise SemanticError("semantic 代际目录损坏，拒绝覆盖 last-known-good")
        for name, data in payload.items():
            if (final / name).read_bytes() != data:
                raise SemanticError("semantic 代际内容损坏，拒绝覆盖 last-known-good")
    else:
        temporary = Path(tempfile.mkdtemp(prefix=f".{digest}.", dir=str(generations)))
        try:
            for name, data in payload.items():
                atomic_write_bytes(temporary / name, data)
            os.rename(temporary, final)
        finally:
            if temporary.exists():
                for child in temporary.iterdir():
                    child.unlink()
                temporary.rmdir()
    atomic_write_bytes(directory / "observed.json", payload["observed.json"])
    atomic_write_bytes(directory / "graph.json", payload["graph.json"])
    if prior_manifest and prior_manifest.get("generation") == digest:
        previous_generation = prior_manifest.get("previous_generation")
        previous_pointer = prior_manifest.get("previous_pointer")
    else:
        previous_generation = prior_manifest.get("generation") if prior_manifest else None
        previous_pointer = prior_manifest
    atomic_write_json(directory / "manifest.json", {
        "schema_version": 1, "generation": digest, "business_digest": digest,
        "path": f"generations/{digest}",
        "previous_generation": previous_generation, "previous_pointer": previous_pointer,
        "files": {name: _sha(data) for name, data in sorted(payload.items())},
        "expected": {"path": "expected.json", "digest": canonical_digest(expected)},
        "observed": {"path": "observed.json", "digest": canonical_digest(observed)},
        "graph": {"path": "graph.json", "digest": canonical_digest(graph)},
    })


def rollback_contracts(root: str | Path, mode: str | None = None) -> dict:
    root = Path(root).absolute()
    selected = _mode(mode, root)
    if selected == "off":
        return _result("UNVERIFIED", 2, [_finding("semantic 模块 off，不能回滚")], None, selected)
    directory = _contracts_dir(root)
    pointer_path = directory / "manifest.json"
    if not pointer_path.is_file() or pointer_path.is_symlink():
        raise SemanticIntegrityError("semantic manifest 缺失或不是普通文件")
    current = load_json(pointer_path)
    if not isinstance(current, dict):
        return _result("FAIL", 1, [{"cause": "contract_stale",
                                    "message": "semantic pointer 必须为对象"}],
                       "contract_stale", selected)
    previous = current.get("previous_pointer")
    if not isinstance(previous, dict) or previous.get("generation") != current.get("previous_generation"):
        raise SemanticIntegrityError("没有可回滚的 semantic 上一代")
    _verify_published_generation(directory, previous)
    target = safe_path(directory, previous["path"])
    current_expected = (directory / "expected.json").read_bytes()
    previous_expected = (target / "expected.json").read_bytes()
    if current_expected != previous_expected:
        return _result("FAIL", 1, [{"cause": "contract_stale",
                                    "message": "当前 expected 与上一代不同，拒绝回滚覆盖用户契约"}],
                       "contract_stale", selected)
    snapshots = {name: (directory / f"{name}.json").read_bytes() if (directory / f"{name}.json").is_file() else None
                 for name in STORE_NAMES}
    try:
        for name in STORE_NAMES:
            atomic_write_bytes(directory / f"{name}.json", (target / f"{name}.json").read_bytes())
        atomic_write_json(pointer_path, previous)
    except Exception:
        for name, raw in snapshots.items():
            path = directory / f"{name}.json"
            if raw is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write_bytes(path, raw)
        raise
    return _result("WARN", 0, [{"cause": "observation", "message": "semantic manifest 已回切上一代"}],
                   None, selected, generation=previous["generation"])


def semantic_digests(root: str | Path) -> dict[str, str]:
    root = Path(root).absolute()
    return {name: canonical_digest(_read_store(root, name)) for name in STORE_NAMES}


def refresh_contracts(root: str | Path, *, base: str | None = None, head: str | None = None,
                      mode: str | None = None, write: bool = True,
                      testid_extractor=None, testid_version: str | None = None) -> dict:
    """Project current adapter facts and atomically publish observed/graph only."""
    root = Path(root).absolute()
    selected = _mode(mode, root)
    if selected == "off":
        return _result("UNVERIFIED", 2, [_finding("semantic 模块 off，in-scope 不可判定")], None, selected)
    expected_path = _contracts_dir(root) / "expected.json"
    if not expected_path.is_file() or expected_path.is_symlink():
        raise SemanticError("缺 semantic expected 库：contracts/expected.json")
    with _publication_lock(root) if write else nullcontext():
        expected_raw, expected = _expected_snapshot(root)
        errors = validate(expected, load_schema("semantic-expected"))
        if errors:
            raise SemanticError("expected schema: " + "; ".join(errors))
        base_revision = _revision(root, base or _git(root, "rev-parse", "HEAD"))
        head_revision = _revision(root, head or base_revision["commit"])
        prior_edges = None
        try:
            prior = _read_store(root, "graph")
            if isinstance(prior, dict) and not validate(prior, load_schema("semantic-graph")):
                prior_edges = prior["edges"]
        except (OSError, ValueError, GovernancePathError):
            pass
        observed = _project_adapters(root, base_revision, head_revision, testid_extractor, testid_version)
        projection_errors = validate(observed, load_schema("semantic-observed"))
        if projection_errors:
            raise SemanticError("observed schema: " + "; ".join(projection_errors))
        findings, edges = _reconcile_stores(expected, observed, prior_edges)
        graph = {"schema_version": 1, "expected_digest": canonical_digest(expected),
                 "observed_digest": canonical_digest(observed), "edges": edges}
        graph_errors = validate(graph, load_schema("semantic-graph"))
        if graph_errors:
            raise SemanticError("graph schema: " + "; ".join(graph_errors))
        if write:
            _publish_stores_locked(root, expected_raw, expected, observed, graph)
        return _evaluate(root, expected, observed, graph, findings, selected)


def _validate_sources(root: Path, store: dict) -> list[dict]:
    findings: list[dict] = []
    revision = store["head"]["commit"] if store["head"]["commit"] != store["base"]["commit"] else ":0"
    for fact in store["facts"]:
        source = fact["source"]
        try:
            safe_path(root, source["path"])
            raw = _blob_bytes(root, revision, source["path"])
            if raw is None:
                raise SemanticError("来源不在语义源树")
            if _sha(raw) != source["sha256"] or source["line"] > len(raw.splitlines()):
                raise SemanticError("来源 staged hash/line 已变化")
        except (OSError, ValueError, GovernancePathError) as exc:
            findings.append({"cause": "contract_stale", "verdict": "FAIL",
                             "message": f"事实来源不可复核：{source['path']}: {exc}",
                             "path": source["path"], "line": source["line"]})
    return findings


def _evaluate(root: Path, expected: dict, observed: dict, graph: dict,
              findings: list[dict], mode: str) -> dict:
    coverage_findings = [_finding(item) for item in observed["coverage"]["parse_errors"]]
    coverage_findings.extend(_finding(f"动态字段不可判定：{item}")
                             for item in observed["coverage"]["unverified_fields"])
    all_findings = findings + coverage_findings + _validate_sources(root, observed)
    for item in all_findings:
        item.setdefault("verdict", "UNVERIFIED" if item["cause"] == "contract_unverified" else "FAIL")
    digests = {"expected": canonical_digest(expected), "observed": canonical_digest(observed),
               "graph": canonical_digest(graph)}
    if any(item["verdict"] == "FAIL" for item in all_findings):
        verdict, rc, cause = "FAIL", 1, "contract_stale"
    elif any(item["verdict"] == "UNVERIFIED" for item in all_findings) or coverage_findings:
        verdict, rc, cause = "UNVERIFIED", 2, "contract_unverified"
    else:
        verdict, rc, cause = "PASS", 0, None
    common_findings = [{key: value for key, value in item.items() if key != "verdict"} for item in all_findings]
    return _result(verdict, rc, common_findings, cause, mode,
                   metrics={"digests": digests}, generation=digests["graph"], path="contracts/graph.json")


def check_contracts(root: str | Path, *, mode: str | None = None,
                    testid_extractor=None, testid_version: str | None = None) -> dict:
    """Read-only validation of the three stores, graph anchors and reconciliation."""
    root = Path(root).absolute()
    selected = _mode(mode, root)
    if selected == "off":
        return _result("UNVERIFIED", 2, [_finding("semantic 模块 off，in-scope 不可判定")], None, selected)
    try:
        stores = {name: _read_store(root, name) for name in STORE_NAMES}
    except SemanticIntegrityError as exc:
        return _result("FAIL", 1, [_finding(str(exc), "contract_stale")], "contract_stale", selected,
                       path="contracts")
    except (OSError, ValueError, GovernancePathError) as exc:
        return _result("UNVERIFIED", 2, [_finding(str(exc))], "contract_unverified", selected,
                       path="contracts")
    schema_findings: list[dict] = []
    for name, value in stores.items():
        errors = validate(value, load_schema(f"semantic-{name}"))
        schema_findings.extend(_finding(f"{name} schema: {error}", "contract_stale",
                                        path=f"contracts/{name}.json") for error in errors)
    if schema_findings:
        return _result("FAIL", 1, schema_findings, "contract_stale", selected, path="contracts")
    expected, observed, graph = (stores[name] for name in STORE_NAMES)
    integrity: list[dict] = []
    if graph["expected_digest"] != canonical_digest(expected):
        integrity.append(_finding("graph expected_digest 与 expected 库不符", "contract_stale"))
    if graph["observed_digest"] != canonical_digest(observed):
        integrity.append(_finding("graph observed_digest 与 observed 库不符", "contract_stale"))
    try:
        if observed["base"] != _revision(root, observed["base"]["commit"]):
            integrity.append(_finding("observed base revision digest 不可重算", "contract_stale"))
        if observed["head"] != _revision(root, observed["head"]["commit"]):
            integrity.append(_finding("observed head revision digest 不可重算", "contract_stale"))
    except SemanticError as exc:
        return _result("UNVERIFIED", 2, [_finding(str(exc))], "contract_unverified", selected,
                       path="contracts/observed.json")
    findings, expected_edges = _reconcile_stores(expected, observed, graph["edges"])
    if canonical_digest(graph["edges"]) != canonical_digest(expected_edges):
        integrity.append(_finding("graph 边与 expected↔observed 对账结果不符", "contract_stale"))
    fact_ids = {fact["id"] for fact in observed["facts"]}
    clause_ids = {clause["clause_id"] for clause in expected["clauses"]}
    if len(fact_ids) != len(observed["facts"]):
        integrity.append(_finding("observed fact id 重复", "contract_stale"))
    if len(clause_ids) != len(expected["clauses"]):
        integrity.append(_finding("expected clause_id 重复", "contract_stale"))
    versions = set(observed["adapter_version"].split("|"))
    if any(not any(part == fact["adapter_version"] or part.endswith("@" + fact["adapter_version"])
                   for part in versions) for fact in observed["facts"]):
        integrity.append(_finding("observed adapter_version 未覆盖全部事实", "contract_stale"))
    for edge in graph["edges"]:
        if edge["from"] not in clause_ids or edge["to"] not in fact_ids:
            integrity.append(_finding("graph 边端点不存在", "contract_stale"))
    try:
        projected = _project_adapters(root, observed["base"], observed["head"],
                                      testid_extractor, testid_version)
        if canonical_digest(projected) != canonical_digest(observed):
            integrity.append(_finding("observed 库与当前 staged index 重投影结果不符", "contract_stale",
                                      path="contracts/observed.json"))
    except SemanticError as exc:
        return _result("UNVERIFIED", 2, [_finding(f"staged index 重投影不可判定：{exc}")],
                       "contract_unverified", selected, path="contracts/observed.json")
    expected_sources = sorted({(fact["source"]["path"], fact["source"]["line"], fact["source"]["sha256"])
                               for fact in observed["facts"]})
    recorded_sources = sorted({(source["path"], source["line"], source["sha256"])
                               for source in observed["sources"]})
    if expected_sources != recorded_sources:
        integrity.append(_finding("observed sources 与事实来源集合不符", "contract_stale"))
    return _evaluate(root, expected, observed, graph, findings + integrity, selected)
