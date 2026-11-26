"""RFC-20261125-01 P1: read-only legacy inventory and code-first migration.

Code facts are obtained only by invoking the existing routes/api/models/tests
adapters. Markdown is parsed for candidate intent, never promoted to expected
product contracts. Conflicts become STALE observations; unknown input and
missing real test execution become UNVERIFIED.
"""
from __future__ import annotations

import ast
import hashlib
import os
import platform
import re
import shlex
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from _support.governance_io import GenerationStore, GovernancePathError, load_json, safe_path
from _support.governance_schema import canonical_digest, validate

PKG_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = (
    "source-manifest.json", "facts.json", "contracts.json", "stale.json",
    "parse-errors.json", "test-evidence.json",
)
_SOURCE = {"type": "object", "additionalProperties": False,
           "required": ["path", "sha256", "tool", "role", "parse_status"],
           "properties": {"path": {"type": "string", "minLength": 1},
                          "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                          "tool": {"type": "string", "minLength": 1},
                          "role": {"enum": ["code", "test", "legacy"]},
                          "parse_status": {"enum": ["parsed", "unverified", "error"]}}}
_ANCHOR = {"type": "object", "additionalProperties": False,
           "required": ["path", "sha256"],
           "properties": {"path": {"type": "string", "minLength": 1},
                          "line": {"type": "integer", "minimum": 1},
                          "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}}}
_FACT = {"type": "object", "additionalProperties": False,
         "required": ["id", "adapter", "adapter_version", "kind", "value", "source"],
         "properties": {"id": {"type": "string", "minLength": 1},
                        "adapter": {"enum": ["routes", "api", "models", "tests"]},
                        "adapter_version": {"type": "string", "minLength": 1},
                        "kind": {"type": "string", "minLength": 1},
                        "value": {"type": "object"}, "source": _ANCHOR}}
_CONTRACT = {"type": "object", "additionalProperties": False,
             "required": ["id", "kind", "candidate", "observed", "status", "source"],
             "properties": {"id": {"type": "string", "minLength": 1},
                            "kind": {"enum": ["route", "field", "enum", "testid", "config", "cli"]},
                            "candidate": {"type": "object"}, "observed": {"type": "object"},
                            "status": {"enum": ["MATCH", "STALE", "UNVERIFIED"]},
                            "source": _ANCHOR}}
_FINDING = {"type": "object", "additionalProperties": False,
            "required": ["kind", "message"],
            "properties": {"kind": {"type": "string", "minLength": 1},
                           "message": {"type": "string", "minLength": 1},
                           "path": {"type": "string"}, "line": {"type": "integer", "minimum": 1}}}
ARTIFACT_SCHEMAS = {
    "source-manifest.json": {"$id": "atlas:migration-source-manifest:v1", "type": "object",
        "additionalProperties": False, "required": ["schema_version", "sources"],
        "properties": {"schema_version": {"const": 1}, "sources": {"type": "array", "items": _SOURCE}}},
    "facts.json": {"$id": "atlas:migration-facts:v1", "type": "object",
        "additionalProperties": False, "required": ["schema_version", "facts"],
        "properties": {"schema_version": {"const": 1}, "facts": {"type": "array", "items": _FACT}}},
    "contracts.json": {"$id": "atlas:migration-contracts:v1", "type": "object",
        "additionalProperties": False, "required": ["schema_version", "items"],
        "properties": {"schema_version": {"const": 1}, "items": {"type": "array", "items": _CONTRACT}}},
    "stale.json": {"$id": "atlas:migration-stale:v1", "type": "object",
        "additionalProperties": False, "required": ["schema_version", "items"],
        "properties": {"schema_version": {"const": 1}, "items": {"type": "array", "items": _CONTRACT}}},
    "parse-errors.json": {"$id": "atlas:migration-parse-errors:v1", "type": "object",
        "additionalProperties": False, "required": ["schema_version", "items"],
        "properties": {"schema_version": {"const": 1}, "items": {"type": "array", "items": _FINDING}}},
    "test-evidence.json": {"$id": "atlas:migration-test-evidence:v1", "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "ran", "verified", "command", "nodes", "commit", "tree_hash", "environment_digest", "environment", "exit_code"],
        "properties": {"schema_version": {"const": 1}, "ran": {"type": "boolean"},
                       "verified": {"type": "boolean"}, "command": {"type": "string"},
                       "nodes": {"type": "array", "items": {"type": "string"}},
                       "commit": {"type": ["string", "null"]},
                       "tree_hash": {"type": ["string", "null"], "pattern": "^[0-9a-f]{40}$"},
                       "environment_digest": {"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"},
                       "environment": {"type": "object", "additionalProperties": {"type": "string"}},
                       "exit_code": {"type": ["integer", "null"]},
                       "output": {"type": "string"},
                       "output_sha256": {"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"},
                       "reason": {"type": ["string", "null"]}},
        "allOf": [{"if": {"properties": {"verified": {"const": True}}, "required": ["verified"]},
                   "then": {"required": ["output", "output_sha256"],
                            "properties": {"ran": {"const": True}, "exit_code": {"const": 0},
                                           "command": {"minLength": 1}, "nodes": {"minItems": 1}}}}]},
}

_IGNORE = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
           ".adapter-out", ".atlas", ".pytest_cache", "target", ".next"}
_CODE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go"}
_ROUTE_RE = re.compile(r"\b(GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD|ANY)\s+(/[A-Za-z0-9_./:{}?=&%+-]*)")
_FIELD_RE = re.compile(r"(?:^|[\s`|])([A-Za-z_]\w*)\s*[:：]\s*(string|integer|number|boolean|datetime|date|array|object)\b", re.I)
_TABLE_FIELD_RE = re.compile(r"^\s*\|\s*`?([A-Za-z_]\w*)`?\s*\|\s*`?(string|integer|number|boolean|datetime|date|array|object)`?\s*\|", re.I)
_ENUM_RE = re.compile(r"\b(?:enum|枚举)\s+([A-Za-z_]\w*)\s*[=:{]\s*([A-Za-z0-9_\"'\s,|.-]+)", re.I)
_TESTID_RE = re.compile(r"\btestid\s*[:=]\s*`?([A-Za-z0-9_.:-]+)`?", re.I)
_CONFIG_RE = re.compile(r"\b(?:config|配置键)\s*[:=]\s*`?([A-Z][A-Z0-9_]{2,})`?", re.I)
_CLI_RE = re.compile(r"\b(?:CLI|命令)\s*[:=]\s*`?(--[a-z][a-z0-9-]*)`?", re.I)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tool(rel: str) -> str:
    parts = Path(rel).parts
    if parts and parts[0] == "openspec":
        return "openspec"
    if parts and parts[0] == ".trellis":
        return "trellis"
    return "legacy-docs"


def _is_test(rel: str) -> bool:
    name = Path(rel).name
    return bool(re.search(r"(?:^test_.*\.py$|_test\.py$|\.(?:test|spec)\.[jt]sx?$|Test\.java$|_test\.go$)", name)
                or any(p in ("tests", "test", "__tests__") for p in Path(rel).parts))


def _walk(root: Path):
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in _IGNORE and not d.startswith(".venv"))
        for name in sorted(dirs):
            linked = Path(directory) / name
            if linked.is_symlink():
                raise GovernancePathError(f"拒绝符号链接目录：{linked.relative_to(root).as_posix()}")
        for name in sorted(files):
            path = Path(directory) / name
            rel = path.relative_to(root).as_posix()
            # Generated migration outputs are not source inputs.
            if rel.startswith(".adapter-out/"):
                continue
            yield rel, path


def _inventory(root: Path) -> tuple[dict, list[dict], dict[str, str]]:
    rows: list[dict] = []
    errors: list[dict] = []
    texts: dict[str, str] = {}
    for rel, path in _walk(root):
        safe_path(root, rel)  # rejects links before any adapter can follow them
        suffix = path.suffix.lower()
        tool = _tool(rel)
        code = suffix in _CODE_SUFFIXES
        legacy = (rel in {"README.md", "DESIGN.md", "RUNBOOK.md"}
                  or rel.startswith("docs/") or "prd" in path.name.lower())
        recognized = code or (tool in {"openspec", "trellis"} and suffix == ".md") or (tool == "legacy-docs" and legacy and suffix == ".md")
        unknown = tool in {"openspec", "trellis"} and not recognized
        if not recognized and not unknown:
            continue
        role = "test" if code and _is_test(rel) else "code" if code else "legacy"
        try:
            raw = path.read_bytes()
            status = "parsed"
            try:
                text = raw.decode("utf-8") if (code or recognized) else ""
            except UnicodeDecodeError as exc:
                text = ""
                status = "error"
                errors.append({"kind": "parse_error", "message": str(exc), "path": rel})
        except OSError as exc:
            raw = b""
            text = ""
            status = "error"
            errors.append({"kind": "parse_error", "message": str(exc), "path": rel})
        if unknown:
            status = "unverified"
            errors.append({"kind": "unknown_format", "message": "未支持的旧工具格式", "path": rel})
        rows.append({"path": rel, "sha256": _sha(raw), "tool": "code" if code else tool,
                     "role": role, "parse_status": status})
        texts[rel] = text
    rows.sort(key=lambda row: row["path"])
    errors.sort(key=lambda row: (row["path"], row["kind"], row["message"]))
    return {"schema_version": 1, "sources": rows}, errors, texts


def _run_adapter(root: Path, name: str, out: Path) -> tuple[dict, str]:
    command = [sys.executable, str(PKG_ROOT / "adapters" / f"{name}.py"),
               "--root", str(root), "--out", str(out)]
    result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"adapter {name} 失败 rc={result.returncode}: {result.stdout}{result.stderr}")
    return load_json(out), result.stdout + result.stderr


def _adapter_facts(root: Path, sources: dict) -> tuple[dict, list[dict], dict]:
    facts: list[dict] = []
    errors: list[dict] = []
    by_path = {row["path"]: row for row in sources["sources"]}
    with tempfile.TemporaryDirectory(prefix="atlas-migration-adapters-") as temporary:
        for adapter in ("routes", "api", "models", "tests"):
            try:
                payload, diagnostics = _run_adapter(root, adapter, Path(temporary) / f"{adapter}.json")
            except (OSError, subprocess.TimeoutExpired, RuntimeError, ValueError) as exc:
                errors.append({"kind": "adapter_error", "message": str(exc), "path": f"adapters/{adapter}.py"})
                continue
            if payload.get("spec_entry"):
                errors.append({"kind": "adapter_pointer", "message": "API adapter 只有描述指针，静态字段不可得",
                               "path": payload["spec_entry"]})
            coverage = payload.get("route_coverage") or {}
            if coverage.get("skipped"):
                errors.append({"kind": "route_unverified", "message": "部分路由静态不可解析",
                               "path": "adapters/routes.py"})
            for index, item in enumerate(payload.get("items") or []):
                anchor = item.get("source_file") or item.get("source_module") or item.get("location")
                if anchor:
                    anchor = str(anchor).split(":", 1)[0]
                if anchor not in by_path:
                    anchor = None
                source = {"path": anchor or f"adapters/{adapter}.py",
                          "sha256": by_path.get(anchor, {}).get("sha256", _sha((PKG_ROOT / "adapters" / f"{adapter}.py").read_bytes()))}
                line = item.get("line") or (1 if adapter == "tests" else None)
                if not line and item.get("source_file") and re.search(r":\d+$", item["source_file"]):
                    line = int(item["source_file"].rsplit(":", 1)[1])
                if line:
                    source["line"] = line
                else:
                    errors.append({"kind": "fact_line_unverified", "message": "adapter 未提供可回溯 file:line",
                                   "path": source["path"]})
                kind = {"routes": "page", "api": "endpoint", "models": "field", "tests": "test"}[adapter]
                facts.append({"id": f"{adapter}:{index:06d}", "adapter": adapter,
                              "adapter_version": str(payload.get("adapter_version", "unknown")),
                              "kind": kind, "value": item, "source": source})
            if adapter == "models":
                field_sources = {(fact["value"].get("table"), fact["value"].get("field")): fact["source"]
                                 for fact in facts if fact["adapter"] == "models" and fact["kind"] == "field"}
                for index, item in enumerate(payload.get("enums") or []):
                    source = dict(field_sources.get((item.get("table"), item.get("field")),
                                                    {"path": "adapters/models.py",
                                                     "sha256": _sha((PKG_ROOT / "adapters/models.py").read_bytes())}))
                    facts.append({"id": f"models-enum:{index:06d}", "adapter": "models",
                                  "adapter_version": str(payload.get("adapter_version", "unknown")),
                                  "kind": "enum", "value": item, "source": source})
    facts.sort(key=lambda fact: fact["id"])
    tests = sorted((fact["value"].get("location") for fact in facts if fact["adapter"] == "tests" and fact["value"].get("location")), key=str)
    return {"schema_version": 1, "facts": facts}, errors, {"tests": tests, "payloads": []}


def _without_fences(text: str) -> str:
    return re.sub(r"```[^\n]*\n[\s\S]*?```[^\n]*",
                  lambda match: "\n" * match.group(0).count("\n"), text)


def _candidates(rel: str, text: str, digest: str) -> list[dict]:
    clean = _without_fences(text)
    found: list[dict] = []
    for number, line in enumerate(clean.splitlines(), 1):
        def add(kind, candidate):
            found.append({"id": f"{rel}:{number}:{kind}:{len(found)}", "kind": kind,
                          "candidate": candidate, "observed": {}, "status": "UNVERIFIED",
                          "source": {"path": rel, "line": number, "sha256": digest}})
        for match in _ROUTE_RE.finditer(line):
            add("route", {"method": match.group(1).upper(), "path": match.group(2).rstrip(".,;")})
        for regex in (_FIELD_RE, _TABLE_FIELD_RE):
            for match in regex.finditer(line):
                add("field", {"name": match.group(1), "type": match.group(2).lower()})
        for match in _ENUM_RE.finditer(line):
            values = re.findall(r"[A-Za-z0-9_-]+", match.group(2))
            if values:
                add("enum", {"name": match.group(1), "values": sorted(set(values))})
        for match in _TESTID_RE.finditer(line):
            add("testid", {"value": match.group(1)})
        for match in _CONFIG_RE.finditer(line):
            add("config", {"key": match.group(1)})
        for match in _CLI_RE.finditer(line):
            add("cli", {"flag": match.group(1)})
    return found


def _route_path(value: str) -> str:
    path = value.split("#", 1)[0].split("?", 1)[0]
    path = re.sub(r"\{([A-Za-z_]\w*)\}", r":\1", path)
    if path != "/":
        path = path.rstrip("/")
    return path or "/"


def _type(value: str | None) -> str:
    text = (value or "").strip().lower()
    return {"str": "string", "int": "integer", "bool": "boolean", "float": "number",
            "datetime": "datetime", "date": "date"}.get(text, text)


def _reconcile(candidates: list[dict], facts: dict) -> tuple[list[dict], list[dict]]:
    observed_routes = [f["value"] for f in facts["facts"] if f["adapter"] == "api" and f["kind"] == "endpoint"]
    observed_fields = [f["value"] for f in facts["facts"] if f["adapter"] == "models" and f["kind"] == "field"]
    observed_enums = [f["value"] for f in facts["facts"] if f["kind"] == "enum"]
    pages = [f["value"] for f in facts["facts"] if f["adapter"] == "routes"]
    for contract in candidates:
        candidate = contract["candidate"]
        kind = contract["kind"]
        matches: list[dict] = []
        comparable = False
        if kind == "route":
            comparable = bool(observed_routes)
            matches = [item for item in observed_routes if item.get("method") == candidate["method"]
                       and _route_path(str(item.get("path", ""))) == _route_path(candidate["path"])]
            if not matches:
                matches = [item for item in pages
                           if _route_path(str(item.get("path", ""))) == _route_path(candidate["path"])]
                if matches:
                    contract["status"] = "UNVERIFIED"
                    contract["observed"] = {"reason": "page_route_has_no_http_method", "observed_matches": matches}
                    continue
        elif kind == "field":
            comparable = bool(observed_fields)
            matches = [item for item in observed_fields if item.get("field") == candidate["name"]]
        elif kind == "enum":
            comparable = bool(observed_enums)
            matches = [item for item in observed_enums if item.get("field") == candidate["name"]
                       or item.get("name") == candidate["name"]]
        elif kind == "testid":
            # No existing testid adapter is invoked by this migration contract.
            comparable = False
        else:
            comparable = False
        if not comparable:
            contract["status"] = "UNVERIFIED"
            continue
        if not matches:
            contract["status"] = "STALE"
            contract["observed"] = {"reason": "candidate_not_observed"}
            continue
        if kind == "field":
            observed_types = {_type(item.get("type")) for item in matches}
            if len(observed_types) > 1:
                contract["status"] = "UNVERIFIED"
                contract["observed"] = {"reason": "ambiguous_field_type", "observed_matches": matches}
                continue
            ok = observed_types == {candidate["type"]}
        elif kind == "enum":
            ok = any(sorted(str(v.get("value")) for v in item.get("values", [])) == candidate["values"] for item in matches)
        else:
            ok = True
        contract["status"] = "MATCH" if ok else "STALE"
        contract["observed"] = matches[0] if ok else {"reason": "value_mismatch", "observed_matches": matches}
    stale = [dict(item) for item in candidates if item["status"] == "STALE"]
    return candidates, stale


def _ensure_git_metadata(root: Path) -> bool:
    result = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=root,
                            capture_output=True, text=True, timeout=10)
    if result.returncode == 0:
        return result.stdout.strip() == "true"
    if (root / ".git").exists() or any((parent / ".git").exists() for parent in root.parents):
        raise ValueError("git 元数据不可读")
    return False


def _commit(root: Path) -> str | None:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                                text=True, timeout=10)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _indexed_paths(root: Path) -> set[str]:
    if _commit(root) is None:
        return set()
    result = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, timeout=30)
    if result.returncode != 0:
        raise ValueError("git ls-files 不可读")
    paths = {item.decode("utf-8", "replace") for item in result.stdout.split(b"\0") if item}
    return {rel for rel in paths if _inventory_path(rel)}


def _inventory_path(rel: str) -> bool:
    path = Path(rel)
    suffix = path.suffix.lower()
    if rel in {"openspec", ".trellis"} or rel.startswith(("openspec/", ".trellis/")) \
            or suffix in _CODE_SUFFIXES:
        return True
    legacy = (rel in {"README.md", "DESIGN.md", "RUNBOOK.md"}
              or rel.startswith("docs/") or "prd" in path.name.lower())
    return legacy and suffix == ".md"


def _head_paths(root: Path) -> set[str]:
    commit = _commit(root)
    if commit is None:
        return set()
    result = subprocess.run(["git", "ls-tree", "-r", "-z", "--name-only", commit], cwd=root,
                            capture_output=True, timeout=30)
    if result.returncode != 0:
        raise ValueError("git ls-tree 不可读")
    paths = {item.decode("utf-8", "surrogateescape") for item in result.stdout.split(b"\0") if item}
    return {rel for rel in paths if _inventory_path(rel)}


def _index_hash(root: Path, rel: str) -> str | None:
    try:
        result = subprocess.run(["git", "show", f":{rel}"], cwd=root, capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return _sha(result.stdout) if result.returncode == 0 else None


def _tree_hash(root: Path) -> str | None:
    try:
        result = subprocess.run(["git", "write-tree"], cwd=root, capture_output=True,
                                text=True, timeout=10)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _environment_digest() -> str:
    return hashlib.sha256((platform.python_version() + "\0" + platform.platform()).encode()).hexdigest()


def _stable_output(output: str) -> str:
    # Wall-clock timings are observation metadata, not business content.
    output = re.sub(r"\bin\s+\d+(?:\.\d+)?s\b", "in <duration>s", output)
    output = re.sub(r"\b\d+(?:\.\d+)?s\b", "<duration>s", output)
    return output.strip()


def _python_test_nodes(root: Path, locations: list[str]) -> list[str]:
    nodes: list[str] = []
    for rel in sorted(set(locations)):
        if not rel.endswith(".py"):
            continue
        try:
            tree = ast.parse(safe_path(root, rel).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError, SyntaxError):
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                nodes.append(f"{rel}::{node.name}")
            elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                for method in node.body:
                    if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and method.name.startswith("test_"):
                        nodes.append(f"{rel}::{node.name}::{method.name}")
    return sorted(nodes)


def _python_xfail_nodes(root: Path, locations: list[str]) -> set[str]:
    nodes: set[str] = set()
    for rel in sorted(set(locations)):
        if not rel.endswith(".py"):
            continue
        try:
            tree = ast.parse(safe_path(root, rel).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError, SyntaxError):
            continue

        def marked(statements):
            return any(isinstance(item, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == "pytestmark" for target in item.targets)
                       and "xfail" in ast.unparse(item.value) for item in statements)

        if marked(tree.body):
            nodes.update(_python_test_nodes(root, [rel]))
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                if any("xfail" in ast.unparse(item) for item in node.decorator_list):
                    nodes.add(f"{rel}::{node.name}")
            elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                for method in node.body:
                    if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                            or not method.name.startswith("test_"):
                        continue
                    if marked(node.body) or marked(method.body) \
                            or any("xfail" in ast.unparse(item) for item in method.decorator_list):
                        nodes.add(f"{rel}::{node.name}::{method.name}")
    return nodes


def _pytest_collected_nodes(root: Path, nodes: list[str]) -> list[str]:
    result = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", *nodes],
                            cwd=root, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise ValueError("pytest collect-only 失败：" + (result.stderr or result.stdout).strip())
    return [line.strip() for line in result.stdout.splitlines()
            if "::" in line and not line.lstrip().startswith(("=", "WARN", "ERROR"))]


def _test_evidence(root: Path, discovered: list[str], command: list[str] | None,
                   explicit_nodes: list[str] | None = None) -> dict:
    discovered_nodes = _python_test_nodes(root, discovered)
    xfail_nodes = _python_xfail_nodes(root, discovered)
    nodes = sorted(set(explicit_nodes or []) | set(discovered_nodes))
    if set(nodes) & xfail_nodes:
        evidence = {"schema_version": 1, "ran": False, "verified": False,
                    "command": "", "nodes": nodes, "commit": _commit(root),
                    "tree_hash": _tree_hash(root), "environment_digest": _environment_digest(),
                    "environment": {"python": platform.python_version(), "platform": platform.platform(),
                                    "cwd": ".", "executable": sys.executable},
                    "exit_code": None, "output": "", "output_sha256": None,
                    "reason": "xfail 标记节点不得作为 PASSED 证据"}
        return evidence
    executed = list(command) if isinstance(command, list) else []
    evidence = {"schema_version": 1, "ran": False, "verified": False,
                "command": shlex.join(executed) if executed else "", "nodes": nodes, "commit": _commit(root),
                "tree_hash": _tree_hash(root), "environment_digest": _environment_digest(),
                "environment": {"python": platform.python_version(), "platform": platform.platform(),
                                "cwd": ".", "executable": sys.executable},
                "exit_code": None, "output": "", "output_sha256": None, "reason": None}
    if not discovered:
        evidence["reason"] = "tests adapter 未发现测试文件"
        return evidence
    if not nodes:
        evidence["reason"] = "未记录可验证测试节点（非 Python 测试须显式 --test-node）"
        return evidence
    if not set(nodes) <= set(discovered_nodes):
        evidence["reason"] = "显式测试节点不属于现有 tests adapter 发现集"
        return evidence
    if _commit(root) is not None:
        unstaged = subprocess.run(["git", "diff", "--name-only"], cwd=root,
                                  capture_output=True, text=True, timeout=30)
        if unstaged.returncode == 0 and set(unstaged.stdout.splitlines()) & set(discovered):
            evidence["reason"] = "测试文件工作树与 staged index 不一致，拒绝测试证据"
            return evidence
    if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
        evidence["reason"] = "未提供有效的真实测试命令"
        return evidence
    is_pytest = bool(Path(executed[0]).name.startswith("pytest")
                     or (Path(executed[0]).name.startswith("python")
                         and executed[1:3] == ["-m", "pytest"]))
    if not is_pytest:
        evidence["reason"] = "当前只接受 pytest 逐节点 PASSED 证据；其他运行器须提供适配器"
        return evidence
    executed = [part for part in executed if not re.fullmatch(r"-[vq]+", part)]
    if "-m" in executed:
        executed.insert(executed.index("pytest") + 1, "-vv")
    else:
        executed.append("-vv")
    try:
        collected_nodes = _pytest_collected_nodes(root, nodes)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        evidence["reason"] = f"pytest 节点收集失败：{exc}"
        return evidence
    with tempfile.TemporaryDirectory(prefix="atlas-migration-junit-") as temporary:
        junit = Path(temporary) / "results.xml"
        evidence["command"] = shlex.join(executed + [f"--junitxml={junit}"]).replace(str(junit), "<junit>")
        try:
            result = subprocess.run(executed + [f"--junitxml={junit}"], cwd=root,
                                    capture_output=True, text=True, timeout=300)
            cases = ET.parse(junit).getroot().findall(".//testcase") if junit.is_file() else []
        except (OSError, subprocess.TimeoutExpired, ET.ParseError) as exc:
            evidence["reason"] = f"测试未能真实执行或 JUnit 不可解析：{exc}"
            return evidence
    output = _stable_output(result.stdout + result.stderr).replace(str(junit), "<junit>").replace(str(root), "<root>")
    plain_output = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", output)
    if re.search(r"(?m)^\S+::\S+\s+XPASS\b", plain_output) \
            or re.search(r"\b\d+\s+xpassed\b", plain_output, re.I):
        evidence.update({"ran": True, "exit_code": result.returncode, "output": output,
                         "output_sha256": _sha(output.encode("utf-8")), "verified": False,
                         "reason": "XPASS 不得作为 PASSED 证据"})
        return evidence
    covered = True
    for node in nodes:
        rel, *parts = node.split("::")
        expected_class = ".".join(list(Path(rel).with_suffix("").parts) + parts[:-1])
        expected_name = parts[-1]
        collected = [item for item in collected_nodes if item == node or item.startswith(node + "[")]
        if not collected:
            covered = False
            break
        for collected_node in collected:
            suffix = collected_node[len(node):]
            matched = any(case.get("classname") == expected_class
                          and case.get("name") == expected_name + suffix
                          and not any(case.find(tag) is not None for tag in ("failure", "error", "skipped"))
                          for case in cases)
            if not matched:
                covered = False
                break
        if not covered:
            break
    verified = result.returncode == 0 and covered
    evidence.update({"ran": True, "exit_code": result.returncode, "output": output,
                     "output_sha256": _sha(output.encode("utf-8")),
                     "verified": verified,
                     "reason": None if verified else "命令未逐节点证明 PASSED"})
    return evidence


def migrate(root: str | Path, test_command: list[str] | str | None = None,
            test_nodes: list[str] | None = None, mode: str = "enforce") -> dict:
    """Build and publish one deterministic generation without editing sources."""
    root = Path(root).absolute()
    if mode not in ("shadow", "enforce", "off"):
        raise ValueError("mode 必须为 shadow/enforce/off")
    if mode == "off":
        return {"schema_version": 1, "module": "migration", "mode": mode,
                "verdict": "UNVERIFIED", "cause": None, "rc": 2,
                "findings": [{"cause": "observation", "message": "migration off，不扫描、不执行测试、不发布代际"}]}
    safe_path(root, ".")
    try:
        git_repo = _ensure_git_metadata(root)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return {"schema_version": 1, "module": "migration", "mode": mode,
                "verdict": "UNVERIFIED", "cause": "migration_unverified", "rc": 2,
                "findings": [{"cause": "migration_unverified", "message": str(exc)}]}
    if isinstance(test_command, str):
        test_command = shlex.split(test_command)
    source_manifest, errors, texts = _inventory(root)
    if git_repo:
        for row in source_manifest["sources"]:
            if _index_hash(root, row["path"]) != row["sha256"]:
                errors.append({"kind": "source_stale", "path": row["path"],
                               "message": "源文件与 staged index 不一致，拒绝生成迁移证据"})
        recorded_paths = {row["path"] for row in source_manifest["sources"]}
        for rel in sorted(_indexed_paths(root) - recorded_paths):
            errors.append({"kind": "source_stale", "path": rel,
                           "message": "staged index 含未进入 inventory 的源文件"})
        for rel in sorted(_head_paths(root) - _indexed_paths(root)):
            errors.append({"kind": "source_stale", "path": rel,
                           "message": "HEAD 源文件已被暂存删除，拒绝静默丢失"})
    facts, adapter_errors, discovered = _adapter_facts(root, source_manifest)
    errors.extend(adapter_errors)
    candidates: list[dict] = []
    for row in source_manifest["sources"]:
        if row["tool"] in {"openspec", "trellis", "legacy-docs"} and row["parse_status"] == "parsed":
            candidates.extend(_candidates(row["path"], texts.get(row["path"], ""), row["sha256"]))
    candidates.sort(key=lambda item: (item["source"]["path"], item["source"]["line"], item["id"]))
    contracts, stale = _reconcile(candidates, facts)
    # Unsupported semantic dimensions are explicit, never silently MATCH.
    for item in contracts:
        if item["status"] == "UNVERIFIED":
            errors.append({"kind": "unverified_intent", "path": item["source"]["path"],
                           "line": item["source"]["line"],
                           "message": f"现有 adapter 无法对账 {item['kind']} 候选意图"})
    evidence = _test_evidence(root, discovered["tests"], test_command, test_nodes)
    if not evidence["verified"] and not any(e["kind"] == "test_unverified" for e in errors):
        errors.append({"kind": "test_unverified", "message": evidence["reason"] or "测试证据不足"})
    errors.sort(key=lambda item: (item.get("path", ""), item["kind"], item["message"]))
    artifacts = {
        "source-manifest.json": source_manifest,
        "facts.json": facts,
        "contracts.json": {"schema_version": 1, "items": contracts},
        "stale.json": {"schema_version": 1, "items": stale},
        "parse-errors.json": {"schema_version": 1, "items": errors},
        "test-evidence.json": evidence,
    }
    for name, schema in ARTIFACT_SCHEMAS.items():
        problems = validate(artifacts[name], schema)
        if problems:
            raise ValueError(f"迁移产物 schema 非法 {name}: {problems}")
    digest = canonical_digest(artifacts)
    if mode == "off":
        verdict, cause, rc = "UNVERIFIED", None, 2
    elif errors or not evidence["verified"]:
        verdict, cause, rc = "UNVERIFIED", "migration_unverified", 2
    elif stale:
        verdict, cause, rc = "STALE", "contract_stale", 1
    else:
        verdict, cause, rc = "PASS", None, 0
    if mode == "shadow":
        rc = 0
    store = GenerationStore(root)
    store.publish(digest, artifacts, mode)
    return {"schema_version": 1, "module": "migration", "mode": mode,
            "verdict": verdict, "cause": cause, "rc": rc,
            "generation": digest, "path": f".adapter-out/migration/generations/{digest}",
            "findings": [{"cause": "migration_unverified", "message": item["message"],
                          **({"path": item["path"]} if item.get("path") else {}),
                          **({"line": item["line"]} if item.get("line") else {})}
                         for item in errors]
                        + [{"cause": "contract_stale", "message": "旧文档候选与代码事实冲突",
                            "path": item["source"]["path"], "line": item["source"]["line"]}
                           for item in stale]}


def rollback(root: str | Path, mode: str = "shadow") -> dict:
    if mode not in ("shadow", "enforce", "off"):
        raise ValueError("rollback mode 必须为 shadow/enforce/off")
    if mode == "off":
        return {"schema_version": 1, "module": "migration", "mode": mode,
                "verdict": "UNVERIFIED", "cause": None, "rc": 2,
                "findings": [{"cause": "observation", "message": "migration off，不能回滚"}]}
    result = GenerationStore(root).rollback()
    mode = result.get("mode", "enforce")
    verdict, rc = ("UNVERIFIED", 2) if mode == "off" else ("WARN", 0)
    return {"schema_version": 1, "module": "migration", "mode": mode,
            "verdict": verdict, "cause": None, "rc": rc,
            "generation": result["generation"], "path": result["path"],
            "findings": [{"cause": "observation", "message": "manifest 指针已回切；需重跑 check 复核代际"}]}
