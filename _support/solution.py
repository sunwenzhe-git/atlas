#!/usr/bin/env python3
"""atlas solution —— 多仓方案层（federated + pinned workspace）。

Phase 1 提供只读整合：清单 / 锁解析、成员 git 状态、ignore / gitlink / 非 git 守卫、
跨仓契约指纹、`status` / `check` / `lock` / `init` / `adopt`。

本次增量（Unreleased）把锁升级为可复现基线：
- 清单可记录 `members[].url`；URL 做 scheme 白名单并拒绝内嵌凭据；
- 锁记录成员 `url / branch / head(commit)`，作为 `check --strict` 的判据；
- `check --strict` 把锁缺失 / 锁未跟踪 / 版本或契约漂移 / dirty / 缺 URL 升为 FAIL；
- `diff` 只读对账：成员相对锁的提交 / diffstat 与工作区改动。

CI 按锁还原由流水线自行 clone + checkout 承担（见 `shared/solution.md` §5.1），本模块不提供自动还原命令。

**不做**：unified 资产搬迁、成员代码提交（solution_commit）、impact / closeout 多根对账。
这些属于 Phase 2/3；遇到 `mode: unified` 必须显式拒绝，不得静默降级。

契约正文见 `shared/solution.md`。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit, urlunsplit

MANIFEST_NAME = "atlas.solution.yaml"
LOCK_NAME = "atlas.solution.lock.json"
CONFIG_NAME = "atlas.config.yaml"
SCHEMA_VERSION = 1
# B 批起 v2 清单的首锁升 2（带 definition / acceptance_cutover）；v1 清单的锁仍是 1。
LOCK_SCHEMA_VERSION = 2
MODES = ("federated", "unified")
ASSET_OWNERS = ("member", "solution")


class SolutionError(ValueError):
    """输入 / 清单错误（CLI exit 2）。"""


def _load_sibling(name: str, key: str):
    if key in sys.modules:
        return sys.modules[key]
    path = Path(__file__).with_name(f"{name}.py")
    spec = importlib.util.spec_from_file_location(key, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


_SP = _load_sibling("stack_profile", "_atlas_solution_stack_profile")
strip_inline_comment = _SP.strip_inline_comment
yaml_scalar = _SP.yaml_scalar

# 用例 ID 文法单源（`rings/e2e/reference.md` §5.3）。
# 取用者必须登记进 `_support/case_id.py::CONSUMERS`（`tests/test_tools.py` 普查钉）。
case_id = _load_sibling("case_id", "_atlas_solution_case_id")


# ---------------------------------------------------------------- manifest

def manifest_path(root: Path) -> Path:
    return Path(root) / MANIFEST_NAME


# ------------------------------------------------------- reader_version（§5.2.1）

# 工具包根：开发树里 `_support/` 在包根下；安装副本里是 `<target>/.atlas/`。
# **只用来定位工具自身的版本来源，绝不读被检查仓 `<root>/package.json`**（v11/重要 3）。
_TOOL_PACKAGE_ROOT = Path(__file__).resolve().parents[1]

_SEMVER_RE = re.compile(
    r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")


def parse_semver(raw: str) -> tuple[int, int, int, str] | None:
    """(major, minor, patch, prerelease)；不可解析 ⇒ None（含装配摘要形态）。"""
    m = _SEMVER_RE.match((raw or "").strip())
    if m is None:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4) or ""


def semver_lt(raw: str, bound: tuple[int, int, int]) -> bool:
    """`raw < bound`（同版本时预发布视为更小）；`raw` 不可解析 ⇒ False。"""
    parsed = parse_semver(raw)
    if parsed is None:
        return False
    base, pre = parsed[:3], parsed[3]
    if base != bound:
        return base < bound
    return bool(pre)


def resolve_reader_version(root: Path) -> tuple[str, list[dict]]:
    """三级回落取**工具自身**版本（RFC §5.2.1 / §5.3），返回 `(version, downgrades)`。

    ① `<root>/.atlas/VERSION`：装配副本 semver；旧副本是摘要形态 ⇒ 降级继续；
    ② `<root>/.atlas/package.json`：安装副本随包写入的 `version`；
    ③ `<工具包根>/package.json`：开发树 / 源码包。
    **不读被检查仓 `<root>/package.json`**。三级全缺 ⇒ `version == ""`（unknown）。
    中间级存在但不可解析 ⇒ 记一条 `downgrades[]` 且继续回落，不提前判 unknown。
    """
    root = Path(root)
    atlas = root / ".atlas"
    candidates: list[tuple[str, Path, str]] = [
        ("VERSION", atlas / "VERSION", "text"),
        ("package.json", atlas / "package.json", "json"),
        ("工具包 package.json", _TOOL_PACKAGE_ROOT / "package.json", "json"),
    ]
    downgrades: list[dict] = []
    seen: set[Path] = set()
    for label, path, kind in candidates:
        if path in seen:
            continue
        seen.add(path)
        if not path.is_file():
            continue
        try:
            if kind == "text":
                raw = path.read_text(encoding="utf-8").strip()
            else:
                raw = str(json.loads(path.read_text(encoding="utf-8"))["version"])
        except (OSError, ValueError, KeyError, TypeError):
            downgrades.append({
                "code": "reader_version", "scope": "reader_version",
                "path": str(path),
                "detail": f"{label} 不可解析，已回落下一级",
            })
            continue
        if parse_semver(raw) is None:
            downgrades.append({
                "code": "reader_version", "scope": "reader_version",
                "path": str(path),
                "detail": f"{label} 不是 semver（{raw or '空'}），已回落下一级",
            })
            continue
        return raw.strip(), downgrades
    return "", downgrades


def reader_version(root: Path) -> str:
    """`resolve_reader_version` 的薄封装：`""` 表示 `reader_version_unknown`。"""
    return resolve_reader_version(root)[0]


def reader_version_unknown_hint(root: Path) -> str:
    """固定提示（RFC §5.3）：三个候选路径 + 修复方式。"""
    atlas = Path(root) / ".atlas"
    return (
        "reader_version_unknown: 缺少 .atlas/VERSION、.atlas/package.json 与 "
        "工具包 package.json 的 version\n"
        f"  候选：{atlas / 'VERSION'} / {atlas / 'package.json'} / "
        f"{_TOOL_PACKAGE_ROOT / 'package.json'}")


def lock_path(root: Path) -> Path:
    return Path(root) / LOCK_NAME


_NAME_BAD = re.compile(r"[\x00-\x1f:#\"'\\\\]")
_PATH_BAD = re.compile(r"[\x00-\x1f#\"'\\\\]")


def _validate_name(raw: str, field: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise SolutionError(f"{field} 不能为空")
    if raw != raw.strip() or _NAME_BAD.search(raw):
        raise SolutionError(f"{field} 含非法字符（控制字符 / : / # / 引号 / 反斜杠）: {raw!r}")
    return raw


def _safe_rel(raw: str, field: str) -> str:
    if not raw or not isinstance(raw, str):
        raise SolutionError(f"{field} 不能为空")
    if _PATH_BAD.search(raw):
        raise SolutionError(f"{field} 含非法字符（控制字符 / # / 引号 / 反斜杠）: {raw!r}")
    p = PurePosixPath(raw.strip())
    if p.is_absolute() or ".." in p.parts or not p.parts:
        raise SolutionError(f"{field} 必须是 solution 内相对路径（拒绝绝对路径与 ..）: {raw!r}")
    if p.parts[0] in (".atlas", ".trellis", ".git"):
        raise SolutionError(f"{field} 不能指向 Atlas/Trellis 内部目录: {raw!r}")
    return p.as_posix()


def _scalar(raw: str):
    v = yaml_scalar(raw)
    return v


_URL_SCHEMES = ("http", "https", "ssh", "git", "file")
_CREDENTIAL_QUERY = re.compile(
    r"(?:^|[?&])(?:access_token|private_token|token|auth|key|sig|signature|"
    r"x-amz-signature|x-amz-credential|x-amz-security-token)=", re.I)
_SCP_LIKE = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9._-]+:[^/].*$")


def _redact_url(raw: str) -> str:
    """错误信息里的脱敏展示：只遮蔽 userinfo 与 token 查询参数。"""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return "<redacted>"
    netloc = parts.netloc
    if "@" in netloc:
        user = netloc.rsplit("@", 1)[0]
        masked = "***" if ":" not in user else f"{user.split(':', 1)[0]}:***"
        netloc = f"{masked}@{netloc.rsplit('@', 1)[1]}"
    query = re.sub(
        r"(?i)((?:access_token|private_token|token|auth|key|sig|signature|"
        r"x-amz-signature|x-amz-credential|x-amz-security-token)=)[^&]*",
        r"\1***", parts.query)
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


def _validate_url(raw, field: str) -> str | None:
    """成员仓远端地址：scheme 白名单 + 拒绝内嵌凭据 / 参数注入。

    允许 http/https/ssh/git/file、SCP 形式 `user@host:path`、本地绝对或 ./ 路径；
    拒绝 `ext::`（git 可执行命令）、前导 `-`、控制字符 / 空白。
    http(s) 的 userinfo 与常见 token 查询参数一律拒绝，避免凭据落进清单与锁。
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s.startswith("-") or re.search(r"[\x00-\x1f\s]", s):
        raise SolutionError(f"{field} 含非法字符（控制字符 / 空白 / 前导 -）: {raw!r}")
    parts = urlsplit(s)
    scheme = parts.scheme.lower()
    if scheme:
        if scheme not in _URL_SCHEMES:
            raise SolutionError(
                f"{field} 的 scheme 不在白名单（{'/'.join(_URL_SCHEMES)}）: {raw!r}")
        if scheme in ("http", "https", "file") and (parts.username or parts.password):
            raise SolutionError(
                f"{field} 含内嵌凭据（userinfo），禁止写入清单/锁；"
                f"请改用 SSH 或凭据管理器: {_redact_url(s)!r}")
        if parts.password:
            raise SolutionError(
                f"{field} 含密码，禁止写入清单/锁；请改用 SSH 或凭据管理器: "
                f"{_redact_url(s)!r}")
        if _CREDENTIAL_QUERY.search(parts.query):
            raise SolutionError(
                f"{field} 查询参数含 token/签名，禁止写入清单/锁: {_redact_url(s)!r}")
        return s
    if _SCP_LIKE.match(s):
        # SCP 形式只允许 user@host:path；出现 user:pass@ 视为密码。
        userinfo = s.split("@", 1)[0]
        if ":" in userinfo:
            raise SolutionError(
                f"{field} 含内嵌密码，禁止写入清单/锁: {_redact_url(s)!r}")
        return s
    if s.startswith("/") or s.startswith("./") or s.startswith("../"):
        return s
    raise SolutionError(
        f"{field} 不是受支持的仓库地址（需要 scheme 白名单、SCP 形式或本地路径）: {raw!r}")


def parse_manifest_text(text: str) -> dict:
    """解析 `atlas.solution.yaml` 的受限 YAML 子集。

    支持：顶层标量；`definition:` 一层嵌套（`domain` / `path`，`definition: null`
    归一为 None）；`members:` / `contracts:` / `requirements:` 的 `- key: value`
    列表（`requirements` 逐行解析 `id / acs / member / task_slug / assignee / scope /
    case_ids / cross_repo_e2e`）。不支持嵌套列表 / 多行标量。未知顶层键与未知
    `definition` 子键均报错，不静默丢弃。
    """
    data: dict = {"members": [], "contracts": [], "requirements": [],
                  "requirements_present": False, "unknown": [],
                  "definition": None, "acceptance_cutover": None, "min_atlas": None}
    section = None
    cur: dict | None = None
    for raw in text.splitlines():
        line = strip_inline_comment(raw.rstrip())
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        s = line.strip()
        if indent == 0 and not s.startswith("- "):
            if s.endswith(":"):
                section = s[:-1].strip()
                cur = None
                if section == "definition":
                    data["definition"] = {}
                elif section == "requirements":
                    data["requirements_present"] = True
                elif section not in ("members", "contracts", "requirements"):
                    raise SolutionError(
                        f"manifest_field_unknown: 清单未知顶层键: {section}")
                continue
            if ":" not in s:
                raise SolutionError(f"无法解析清单行: {raw!r}")
            key, val = s.split(":", 1)
            key, val = key.strip(), _scalar(val)
            if key in ("version", "solution", "mode", "acceptance_cutover", "min_atlas"):
                data[key] = val
            elif key == "definition":
                if val is not None:
                    raise SolutionError(
                        "definition 必须是映射（definition:<换行>  domain/path）或 null")
                data["definition"] = None
            elif key == "members":
                if val not in (None, "[]"):
                    raise SolutionError("members 必须是列表（空值写 members: []）")
                data["members"] = []
            elif key == "contracts":
                if val not in (None, "[]"):
                    raise SolutionError("contracts 必须是列表（空值写 contracts: []）")
                data["contracts"] = []
            elif key == "requirements":
                data["requirements_present"] = True
                if val not in (None, "[]"):
                    raise SolutionError("requirements 必须是列表（空值写 requirements: []）")
            else:
                raise SolutionError(f"manifest_field_unknown: 清单未知顶层键: {key}")
            section = None
            cur = None
            continue
        if section == "definition":
            if ":" not in s:
                raise SolutionError(f"无法解析 definition 行: {raw!r}")
            key, val = s.split(":", 1)
            key = key.strip()
            if key not in ("domain", "path"):
                raise SolutionError(
                    f"definition_field_unknown: definition 未知子键: {key}")
            data["definition"][key] = _scalar(val)
            continue
        if section in ("members", "contracts", "requirements"):
            if s.startswith("- "):
                cur = {}
                data[section].append(cur)
                s = s[2:].strip()
                if not s:
                    continue
            if cur is None or ":" not in s:
                raise SolutionError(f"无法解析 {section} 列表行: {raw!r}")
            key, val = s.split(":", 1)
            key = key.strip()
            known = {
                "members": ("name", "path", "url", "assets", "kind", "stack_profile"),
                "contracts": ("id", "producer", "producer_path", "consumer", "consumer_path"),
                "requirements": ("id", "acs", "member", "task_slug", "assignee", "scope",
                                 "case_ids", "cross_repo_e2e"),
            }[section]
            if key not in known:
                cur.setdefault("unknown", []).append(key)
                continue
            cur[key] = _scalar(val)
            continue
        # requirements：Phase 1 只登记存在性，不解析。
        if section == "requirements":
            data["requirements_present"] = True
            continue
        raise SolutionError(f"无法解析清单行: {raw!r}")
    return data


def load_manifest(root: Path) -> dict:
    path = manifest_path(root)
    if not path.is_file():
        raise SolutionError(f"未找到 {MANIFEST_NAME}: {path}")
    try:
        data = parse_manifest_text(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SolutionError(f"清单不可读: {exc}") from exc
    return validate_manifest(data, Path(root))


def _manifest_version(raw) -> int:
    """B-0：0.3.x 同时接受 v1 / v2；0.4.0 只接受 v2 的分支属后续批次。"""
    value = str(raw or "").strip()
    if value not in ("1", "2"):
        raise SolutionError(
            f"manifest_schema_unsupported: 清单 version 必须为 1 或 2（当前: {value or '缺失'}）")
    return int(value)


def _manifest_definition(raw, root: Path) -> dict | None:
    """`definition` 归一：null ⇒ None；否则只收 domain / path，path 限 B-0 白名单。"""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise SolutionError("definition 必须是映射或 null")
    domain = str(raw.get("domain") or "").strip()
    path = str(raw.get("path") or "").strip()
    if not domain or not path:
        raise SolutionError("definition.domain / definition.path 都不能为空")
    expected = f"{_assets_root(Path(root))}/prd/solution-prd.md"
    if path != expected:
        raise SolutionError(
            f"definition_path_unsupported: B-0 只接受 {expected}（当前: {path}）；"
            "B 批后支持任意 `-prd.md`")
    return {"domain": domain, "path": path}


def validate_manifest(data: dict, root: Path, phase1: bool = True) -> dict:
    version = _manifest_version(data.get("version"))
    name = _validate_name(data.get("solution"), "solution 名称")
    mode = str(data.get("mode", "")).strip()
    if mode not in MODES:
        raise SolutionError(f"mode 必须是 {'/'.join(MODES)}")
    if phase1 and mode == "unified":
        raise SolutionError("unified 模式尚未交付（Phase 2）；Phase 1 只支持 federated")

    members: list[dict] = []
    seen_names: set[str] = set()
    seen_paths: set[str] = set()
    for item in data.get("members") or []:
        if not isinstance(item, dict):
            raise SolutionError("members 项必须是映射")
        mname = _validate_name(item.get("name"), "members[].name")
        mpath = _safe_rel(str(item.get("path") or ""), "members[].path")
        assets = str(item.get("assets") or "").strip()
        if mname in seen_names:
            raise SolutionError(f"members 名称重复: {mname}")
        if mpath in seen_paths:
            raise SolutionError(f"members 路径重复: {mpath}")
        if assets not in ASSET_OWNERS:
            raise SolutionError(f"members[].assets 必须是 {'/'.join(ASSET_OWNERS)}")
        if phase1 and assets != "member":
            raise SolutionError("Phase 1 只支持 members[].assets: member")
        seen_names.add(mname)
        seen_paths.add(mpath)
        members.append({
            "name": mname,
            "path": mpath,
            "url": _validate_url(item.get("url"), f"members[{mname}].url"),
            "assets": assets,
            "kind": str(item.get("kind") or "fullstack").strip() or "fullstack",
            "stack_profile": str(item.get("stack_profile") or "").strip(),
            "unknown": list(item.get("unknown") or []),
        })
    if not members:
        raise SolutionError("members 至少需要一个成员仓（Phase 1 不接受空方案）")

    contracts: list[dict] = []
    seen_ids: set[str] = set()
    for item in data.get("contracts") or []:
        if not isinstance(item, dict):
            raise SolutionError("contracts 项必须是映射")
        cid = _validate_name(item.get("id"), "contracts[].id")
        if cid in seen_ids:
            raise SolutionError(f"contracts[].id 重复: {cid!r}")
        producer = str(item.get("producer") or "").strip()
        consumer = str(item.get("consumer") or "").strip()
        if producer not in seen_names or consumer not in seen_names:
            raise SolutionError(f"contract {cid} 的 producer/consumer 必须是 members 名称")
        contracts.append({
            "id": cid,
            "producer": producer,
            "producer_path": _safe_rel(str(item.get("producer_path") or ""),
                                       f"contract {cid}.producer_path"),
            "consumer": consumer,
            "consumer_path": _safe_rel(str(item.get("consumer_path") or ""),
                                       f"contract {cid}.consumer_path"),
        })
        seen_ids.add(cid)

    requirements: list[dict] = []
    seen_req_keys: set[tuple[str, str]] = set()
    for item in data.get("requirements") or []:
        if not isinstance(item, dict):
            raise SolutionError("requirements 项必须是映射")
        rid = _validate_name(item.get("id"), "requirements[].id")
        member = str(item.get("member") or "").strip()
        if member not in seen_names:
            raise SolutionError(f"requirement {rid} 的 member 必须是 members 名称")
        acs_raw = item.get("acs")
        if isinstance(acs_raw, list):
            acs = [str(a).strip() for a in acs_raw if str(a).strip()]
        else:
            acs = [a.strip() for a in re.split(r"[、,，]", str(acs_raw or "")) if a.strip()]
        if not acs:
            raise SolutionError(f"requirement {rid} 缺少 acs")
        for ac in acs:
            if not re.fullmatch(r"AC-[A-Z0-9]+-\d{3}", ac):
                raise SolutionError(f"requirement {rid} 的 AC ID 非法: {ac!r}")
        slug = str(item.get("task_slug") or "").strip()
        if not _valid_task_slug(slug):
            raise SolutionError(f"requirement {rid} 的 task_slug 非法: {slug!r}")
        scope = str(item.get("scope") or "").strip()
        if not scope:
            raise SolutionError(f"requirement {rid} 缺少 scope")
        assignee = str(item.get("assignee") or "").strip()
        if assignee:
            _validate_name(assignee, "requirements[].assignee")
        # 选择器（一期）：`case_ids` 是**需求级**属标量，逗号/顿号分隔；`cross_repo_e2e`
        # 唯一合法值 `none`。文法 / 去重在这里；「多成员必须 case_ids / 单成员二选一」
        # 是跨行语义，归 `solution check`（不在此抛 SolutionError，避免清单加载提前打断）。
        case_ids_present = "case_ids" in item
        raw_case_ids = item.get("case_ids")
        if isinstance(raw_case_ids, list):
            case_ids = [str(c).strip() for c in raw_case_ids if str(c).strip()]
        else:
            case_ids = [c.strip() for c in re.split(r"[、,，]", str(raw_case_ids or ""))
                        if c.strip()]
        seen_case_ids: set[str] = set()
        for cid in case_ids:
            if not re.fullmatch(case_id.GRAMMAR, cid):
                raise SolutionError(f"requirement {rid} 的 case_id 文法非法: {cid!r}")
            if cid in seen_case_ids:
                raise SolutionError(f"requirement {rid} 的 case_ids 重复: {cid!r}")
            seen_case_ids.add(cid)
        cross_present = "cross_repo_e2e" in item
        cross_repo_e2e = str(item.get("cross_repo_e2e") or "").strip() or None
        if cross_repo_e2e is not None and cross_repo_e2e != "none":
            raise SolutionError(
                f"requirement {rid} 的 cross_repo_e2e 只能是 none: {cross_repo_e2e!r}")
        key = (rid, member)
        if key in seen_req_keys:
            raise SolutionError(f"requirements 重复（id+member）: {rid} / {member}")
        seen_req_keys.add(key)
        requirements.append({
            "id": rid,
            "acs": acs,
            "member": member,
            "task_slug": slug,
            "assignee": assignee or None,
            "scope": scope,
            "case_ids": case_ids,
            "case_ids_present": case_ids_present,
            "cross_repo_e2e": cross_repo_e2e,
            "cross_repo_e2e_present": cross_present,
            "unknown": list(item.get("unknown") or []),
        })

    # 选择器互斥（清单内语义）：同一 `requirement.id` 最多一行携带 `case_ids`、
    # 最多一行携带 `cross_repo_e2e`，且两者不得同时出现。
    by_req: dict[str, list[dict]] = {}
    for req in requirements:
        by_req.setdefault(req["id"], []).append(req)
    for rid, rows in by_req.items():
        case_rows = [r for r in rows if r["case_ids_present"]]
        none_rows = [r for r in rows if r["cross_repo_e2e_present"]]
        if len(case_rows) > 1:
            raise SolutionError(f"requirement {rid} 有多行携带 case_ids（选择器歧义）")
        if len(none_rows) > 1:
            raise SolutionError(f"requirement {rid} 有多行携带 cross_repo_e2e")
        if case_rows and none_rows:
            raise SolutionError(f"requirement {rid} 同时出现 case_ids 与 cross_repo_e2e")

    return {
        "version": version,
        "definition": _manifest_definition(data.get("definition"), root),
        "acceptance_cutover": (str(data.get("acceptance_cutover")).strip()
                               if data.get("acceptance_cutover") else None),
        "min_atlas": (str(data.get("min_atlas")).strip()
                      if data.get("min_atlas") else None),
        "solution": name.strip(),
        "mode": mode,
        "members": members,
        "contracts": contracts,
        "requirements": requirements,
        "requirements_present": bool(requirements) or bool(data.get("requirements_present")),
        "unknown": list(data.get("unknown") or []),
    }


# ---------------------------------------------------------------- git

def _git(cwd: Path, *args: str, timeout: int = 15) -> tuple[int, str, str]:
    try:
        p = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                           text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)
    return p.returncode, p.stdout, p.stderr


def _git_lines(cwd: Path, *args: str, timeout: int = 15) -> list[str] | None:
    rc, out, _ = _git(cwd, *args, timeout=timeout)
    return out.splitlines() if rc == 0 else None


def _git_bytes(cwd: Path, *args: str, timeout: int = 15) -> bytes | None:
    """取原始字节（blob 摘要不能被文本解码改写换行）。"""
    try:
        p = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                           timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


def _is_git(path: Path) -> bool:
    """成员必须是**自己的仓根**；仅位于 solution 根工作树内不算。"""
    if not path.is_dir():
        return False
    rc, out, _ = _git(path, "rev-parse", "--show-toplevel")
    if rc != 0 or not out.strip():
        return False
    try:
        return Path(out.strip()).resolve() == path.resolve()
    except OSError:
        return False


def _head(path: Path) -> str | None:
    rc, out, _ = _git(path, "rev-parse", "HEAD")
    return out.strip() if rc == 0 and out.strip() else None


def _member_url(path: Path) -> str | None:
    if not _is_git(path):
        return None
    rc, out, _ = _git(path, "remote", "get-url", "origin")
    return out.strip() if rc == 0 and out.strip() else None


def _branch(path: Path) -> str | None:
    rc, out, _ = _git(path, "rev-parse", "--abbrev-ref", "HEAD")
    return out.strip() if rc == 0 and out.strip() else None


def _status_lines(path: Path) -> list[str] | None:
    rc, out, _ = _git(path, "status", "--porcelain", "--untracked-files=all")
    if rc != 0:
        return None
    return [ln for ln in out.splitlines() if ln.strip()]


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _atlas_baseline(member: Path) -> str | None:
    meta = _read_json(member / ".trellis" / "spec" / "structure" / "_meta.json")
    if not isinstance(meta, dict):
        return None
    baseline = meta.get("baseline")
    if isinstance(baseline, dict):
        return baseline.get("commit") or None
    return baseline if isinstance(baseline, str) else None


def _has_atlas_assets(member: Path) -> bool:
    return any((member / p).exists() for p in (
        "atlas.config.yaml",
        "product/stack-profile.yaml",
        ".trellis/spec/structure/_meta.json",
    ))


def _ignore_patterns(path: Path) -> list[str]:
    if not path.is_file():
        return []
    out: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = strip_inline_comment(raw).strip()
        if line:
            out.append(line)
    return out


def _glob_regex(pattern: str) -> re.Pattern[str]:
    out: list[str] = ["^"]
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    out.append("$")
    return re.compile("".join(out))


def _pattern_matches(pattern: str, rel: str) -> bool:
    p = pattern.strip()
    if not p:
        return False
    if p.startswith("/"):
        p = p[1:]
    dir_pattern = p.endswith("/")
    if dir_pattern:
        p += "**"
    if p == "**":
        return True
    regex = _glob_regex(p)
    if dir_pattern and rel == p[:-3].rstrip("/"):
        return True
    if "/" not in p:
        return any(regex.match(seg) for seg in rel.split("/"))
    return regex.match(rel) is not None


def _ignore_sources(root: Path, rel: str) -> list[tuple[str, Path]]:
    """成员路径上所有可能生效的 ignore 文件：根级 + 逐级祖先目录。

    `.gitignore` / `.ignore` / `.rgignore` 在子目录同样生效；只查根级会漏掉
    `apps/.ignore` 这类嵌套规则。返回 (相对该 ignore 文件的目录, 文件路径)。
    """
    sources: list[tuple[str, Path]] = []
    for name in (".gitignore", ".ignore", ".rgignore"):
        path = root / name
        if path.is_file():
            sources.append(("", path))
    base = PurePosixPath()
    for part in PurePosixPath(rel).parts[:-1]:
        base = base / part
        for name in (".gitignore", ".ignore", ".rgignore"):
            path = root / base / name
            if path.is_file():
                sources.append((base.as_posix(), path))
    exclude = root / ".git" / "info" / "exclude"
    if exclude.is_file():
        sources.append(("", exclude))
    return sources


def _ignored_by_file(root: Path, rel: str) -> list[str]:
    reasons: list[str] = []
    rel_path = PurePosixPath(rel)
    for base, path in _ignore_sources(root, rel):
        sub = rel if not base else rel_path.relative_to(base).as_posix()
        ignored = False
        for pattern in _ignore_patterns(path):
            neg = pattern.startswith("!")
            body = pattern[1:].strip() if neg else pattern
            if _pattern_matches(body, sub):
                ignored = not neg
        if ignored:
            reasons.append(str(path.relative_to(root)))
    return reasons


def _member_ignored(root: Path, rel: str) -> list[str]:
    reasons = _ignored_by_file(root, rel)
    rc, _, _ = _git(root, "check-ignore", "-q", "--", rel)
    if rc == 0 and not reasons:
        reasons.append(".gitignore（git check-ignore）")
    return reasons


def _tracked_member_paths(root: Path, rel: str) -> list[str]:
    rc, out, _ = _git(root, "ls-files", "-s", "--", rel)
    if rc != 0:
        return []
    return [ln for ln in out.splitlines() if ln.strip()]


def _assert_members_untracked(root: Path, entries: list[dict]) -> None:
    """init/adopt 写清单前硬拒绝：成员路径已被父仓跟踪（含 submodule gitlink）。

    只 WARN 会让“父仓 diff 看不到成员内容”的假象被带进新方案；
    这里要求先解除跟踪，工作区文件保留。
    """
    for m in entries:
        tracked = _tracked_member_paths(root, m["path"])
        if not tracked:
            continue
        gitlinks = [ln for ln in tracked if ln.split(maxsplit=1)[0] == "160000"]
        if gitlinks:
            raise SolutionError(
                f"成员 {m['name']} 路径 {m['path']} 已被 solution 仓登记为 submodule/gitlink"
                f"（mode 160000，{len(gitlinks)} 条）。请先执行 `git rm --cached {m['path']}` "
                f"并删除 .gitmodules 中对应条目（保留工作区文件），再重试；"
                "不要把 submodule 与 solution 混用。")
        raise SolutionError(
            f"成员 {m['name']} 路径 {m['path']} 已被 solution 仓跟踪（{len(tracked)} 条）。"
            f"请先执行 `git rm -r --cached {m['path']}`（保留工作区），"
            "确认 .gitignore/.ignore/.rgignore 不命中该路径，再重试。")


def member_state(root: Path, member: dict) -> dict:
    path = (root / member["path"]).resolve()
    state = {
        "name": member["name"],
        "path": member["path"],
        "url": member.get("url") or None,
        "exists": path.is_dir(),
        "git": _is_git(path),
        "branch": None,
        "head": None,
        "dirty": None,
        "atlas_baseline": None,
        "atlas_assets": False,
        "ignored": [],
        "tracked": [],
        "unknown": list(member.get("unknown") or []),
        "escaped": False,
    }
    if not state["exists"]:
        return state
    try:
        path.relative_to(root.resolve())
    except ValueError:
        state["escaped"] = True
    state["atlas_assets"] = _has_atlas_assets(path)
    state["ignored"] = _member_ignored(root, member["path"])
    state["tracked"] = _tracked_member_paths(root, member["path"])
    if state["git"]:
        state["branch"] = _branch(path)
        state["head"] = _head(path)
        state["dirty"] = _status_lines(path)
        state["atlas_baseline"] = _atlas_baseline(path)
        if not state["url"]:
            try:
                # origin 可能内嵌凭据：非法地址不进入状态，避免 status --json 泄露。
                state["url"] = _validate_url(_member_url(path), f"member {member['name']}.url")
            except SolutionError:
                state["url"] = None
    return state


# ---------------------------------------------------------------- contracts / lock

def _sha256_file(path: Path) -> str:
    try:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return "missing"


def _safe_member_file(root: Path, member_rel: str, file_rel: str) -> Path | None:
    """契约文件必须落在 solution 根内；symlink 指向根外时返回 None，不读外部文件。"""
    root_r = root.resolve()
    member_dir = (root / member_rel).resolve()
    try:
        member_dir.relative_to(root_r)
    except ValueError:
        return None
    target = (member_dir / file_rel).resolve()
    try:
        target.relative_to(root_r)
    except ValueError:
        return None
    return target


def contract_states(root: Path, data: dict) -> list[dict]:
    by_name = {m["name"]: m for m in data["members"]}
    out: list[dict] = []
    for c in data.get("contracts") or []:
        producer = _safe_member_file(root, by_name[c["producer"]]["path"], c["producer_path"])
        consumer = _safe_member_file(root, by_name[c["consumer"]]["path"], c["consumer_path"])
        out.append({
            "id": c["id"],
            "producer": c["producer"],
            "producer_path": c["producer_path"],
            "producer_sha256": _sha256_file(producer) if producer else "missing",
            "consumer": c["consumer"],
            "consumer_path": c["consumer_path"],
            "consumer_sha256": _sha256_file(consumer) if consumer else "missing",
        })
    return out


# ------------------------------------------------------- definition（§1.1 / §5.2）

def _prd_front_matter(path: Path) -> dict[str, str]:
    """读 PRD 的 YAML front matter（只取标量；不引入 YAML 依赖）。"""
    if not path.is_file():
        return {}
    m = re.match(r"^---\s*\n(.*?)\n---", path.read_text(encoding="utf-8"), re.S)
    if not m:
        return {}
    out: dict[str, str] = {}
    for raw in m.group(1).splitlines():
        line = strip_inline_comment(raw.rstrip())
        if not line.strip() or ":" not in line:
            continue
        key, val = line.split(":", 1)
        out[key.strip()] = str(_scalar(val) if val.strip() else "").strip()
    return out


def _positive_int(raw: str, field: str) -> int:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise SolutionError(f"{field}_invalid: 必须是整数（当前: {raw!r}）")
    if value < 1:
        raise SolutionError(f"{field}_invalid: 必须 ≥ 1（当前: {value}）")
    return value


def _definition_lock_fields(root: Path, definition: dict) -> dict:
    """把 `definition` 落成锁字段（§1.1.2 / §1.1.6 / §1.1.7）。

    `sha256` 与 `blob` 绑 **Git blob 字节**（CRLF→LF 归一），不绑工作树；
    `commit` 是该 blob 所在的提交：PRD 尚未入库（`init` 刚写完）时为 `null`，
    这是唯一允许 `commit == null` 的形态（§5.2 第 8 条）。
    """
    rel = str(definition["path"])
    path = root / rel
    fm = _prd_front_matter(path)
    prd_date = fm.get("date") or ""
    if not prd_date:
        raise SolutionError(
            f"prd_date_missing: {rel} 的 front matter 缺 date（YYYY-MM-DD）")
    domain = str(definition.get("domain") or fm.get("domain") or "").strip()
    fields = {
        "path": rel,
        "domain": domain,
        "domain_code": (fm.get("domain_code") or domain).strip(),
        "prd_version": _positive_int(fm.get("prd_version") or 1, "prd_version"),
        "prd_schema": _positive_int(fm.get("prd_schema") or 1, "prd_schema"),
        "prd_date": prd_date,
    }
    blob: str | None = None
    commit: str | None = None
    data: bytes | None = None
    if _is_git(root):
        rc, out, _ = _git(root, "rev-parse", f"HEAD:{rel}")
        if rc == 0 and out.strip():
            blob = out.strip()
            data = _git_bytes(root, "cat-file", "blob", blob)
            rc2, out2, _ = _git(root, "log", "-1", "--format=%H", "HEAD", "--", rel)
            commit = out2.strip() if rc2 == 0 and out2.strip() else None
    if data is None:
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise SolutionError(f"definition_source_missing: 无法读取 {rel}: {exc}")
        if _is_git(root):
            rc, out, _ = _git(root, "hash-object", "--", rel)
            blob = out.strip() if rc == 0 and out.strip() else None
    fields["sha256"] = hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()
    fields["blob"] = blob
    fields["commit"] = commit
    return fields


def _lock_history_definition_commit(root: Path) -> str | None:
    """主判据：在锁文件的**完整历史**里找最近一次 `definition.commit != null`。

    必须 `-m --full-history`（RFC §5.2 第 8 条 / 第十三轮 B-2 实测定性）：
    不带 `--full-history` 时 `git log` 会做历史简化，merge 下看不见被合并分支里
    写过非 null 的锁提交（实测：merge 保留 null 锁，`git log` 只给 null 提交，
    `--full-history` 才给出分支的 deadbeef 提交），于是 `commit == null` 会误落
    `definition_commit_pending` WARN，把 `definition_commit_unverifiable` 的 FAIL
    蒙混过去。`-m` 让 merge 提交逐父展开，避免合并提交本身被跳过。

    残余（不得声称「不受历史改写影响」）：force-push / 改写历史抹掉那条提交后，
    主判据同样看不见；此时只剩锁里的 `acceptance_cutover != null` 作快速正向兜底，
    因此本函数不保证能识别所有「已刷新后改回 null」的形态（RFC §8）。
    """
    rc, out, _ = _git(root, "log", "-m", "--full-history", "--format=%H",
                      "HEAD", "--", LOCK_NAME)
    if rc != 0:
        return None
    seen: set[str] = set()
    for commit in out.split():
        if commit in seen:
            continue
        seen.add(commit)
        rc2, text, _ = _git(root, "show", f"{commit}:{LOCK_NAME}")
        if rc2 != 0:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        definition = payload.get("definition") if isinstance(payload, dict) else None
        if isinstance(definition, dict) and definition.get("commit"):
            return commit
    return None


def lock_payload(root: Path, data: dict) -> dict:
    members: list[dict] = []
    for m in data["members"]:
        s = member_state(root, m)
        if s["git"] and s.get("branch") == "HEAD":
            raise SolutionError(
                f"成员 {s['name']} 处于 detached HEAD（branch=HEAD）；"
                "请先切回分支再执行 lock --update，避免锁里写入不可复现的分支名")
        members.append({
            "name": s["name"],
            "path": s["path"],
            "url": m.get("url"),
            "branch": s["branch"],
            "head": s["head"],
            "atlas_baseline": s["atlas_baseline"],
        })
    definition = data.get("definition")
    definition_fields = _definition_lock_fields(root, definition) if definition else None
    payload = {
        "schema_version": (LOCK_SCHEMA_VERSION if data.get("version") == 2
                           else SCHEMA_VERSION),
        "solution": data["solution"],
        "mode": data["mode"],
        "locked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "members": members,
        "contracts": contract_states(root, data),
    }
    if data.get("version") == 2:
        payload["definition"] = definition_fields
        # `acceptance_cutover` 从**首次** `lock --update`（PRD 已入库）起才进锁。
        # `init` 的首锁 `definition.commit == null`，若同时写非 null cutover，
        # §5.2 的「快速正向」会把刚建好的仓直接判成 unverifiable FAIL（V-16 自拒）。
        payload["acceptance_cutover"] = (
            data.get("acceptance_cutover")
            if definition_fields and definition_fields.get("commit") else None)
    return payload


def _definition_dirty(root: Path, data: dict) -> str:
    """定义源工作树是否脏（RFC §1.1.6：`git status --porcelain <path>` 非空即脏）。

    只作用于 `lock --update`（`require_clean=True`），不作用于 `init` / `migrate`。
    非 git 仓 / 无 definition 时不可判，按干净处理（不新增阻塞）。
    """
    definition = data.get("definition") or {}
    rel = str(definition.get("path") or "")
    if not rel:
        return ""
    rc, out, _ = _git(root, "status", "--porcelain", "--", rel)
    if rc != 0:
        return ""
    return out.strip()


def write_lock(root: Path, data: dict, require_clean: bool = False) -> Path:
    if require_clean:
        dirty = _definition_dirty(root, data)
        if dirty:
            first = dirty.splitlines()[0]
            raise SolutionError(
                f"定义源工作树不干净（{first}）；先提交 {data['definition']['path']} "
                "再执行 atlas solution lock --update")
    payload = lock_payload(root, data)
    path = lock_path(root)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(path)
    return path


def read_lock(root: Path) -> dict | None:
    data = _read_json(lock_path(root))
    if not isinstance(data, dict) or not isinstance(data.get("schema_version"), int):
        return None
    for key in ("members", "contracts"):
        val = data.get(key, [])
        if not isinstance(val, list) or any(not isinstance(item, dict) for item in val):
            return None
    return data


def lock_tracking(root: Path) -> dict:
    """锁文件是否被父仓跟踪、且与父仓 HEAD 一致（CI 复现的前提）。"""
    if not _is_git(root):
        return {"tracked": False, "consistent": None}
    rc, _, _ = _git(root, "ls-files", "--error-unmatch", "--", LOCK_NAME)
    tracked = rc == 0
    consistent = None
    if tracked:
        rc2, _, _ = _git(root, "diff", "--quiet", "HEAD", "--", LOCK_NAME)
        consistent = rc2 == 0
    return {"tracked": tracked, "consistent": consistent}


# ---------------------------------------------------------------- init / adopt

def _write_if_missing(path: Path, text: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_config(root: Path, assets_root: str) -> None:
    path = root / CONFIG_NAME
    if path.exists():
        return
    path.write_text(f"version: 1\nlayout:\n  assets_root: {assets_root.strip()}\n",
                    encoding="utf-8")


def _install_atlas(root: Path, assets_root: str) -> None:
    version = root / ".atlas" / "VERSION"
    contract = root / ".atlas" / "shared" / "solution.md"
    if version.is_file() and contract.is_file():
        return
    pkg = Path(os.environ.get("ATLAS_PKG_ROOT") or Path(__file__).resolve().parents[1])
    install_py = pkg / "install.py"
    if not install_py.is_file():
        raise SolutionError(
            "solution 根尚未装配 .atlas，且找不到包内 install.py；"
            "请先运行 atlas init 或从源包运行 atlas solution init"
        )
    # solution 根不要求 Trellis（Phase 1 成员各自持有 Trellis）；--no-trellis 跳过
    # Trellis 初始化/骨架，--force 兜底装配器的其他前置。.atlas 目录存在但缺
    # VERSION/shared/solution.md = 上次装配中途失败：允许覆盖重装。
    env = os.environ.copy()
    if (root / ".atlas").exists():
        env["ATLAS_ALLOW_OVERWRITE"] = "1"
    p = subprocess.run(
        [sys.executable, str(install_py), "--target", str(root),
         "--assets-root", assets_root, "--no-skill", "--no-patch", "--no-wiring",
         "--no-trellis", "--force"],
        capture_output=True, text=True, env=env,
    )
    if p.returncode != 0:
        tail = (p.stderr or p.stdout or "").strip().splitlines()[-1:]
        raise SolutionError(f"装配 .atlas 失败: {tail[0] if tail else 'exit ' + str(p.returncode)}")
    if not (version.is_file() and contract.is_file()):
        raise SolutionError("装配 .atlas 不完整（缺 VERSION 或 shared/solution.md）；请重试")


def _member_entries(members: list[tuple], root: Path | None = None) -> list[dict]:
    out: list[dict] = []
    for item in members:
        name, path, kind = item[0], item[1], item[2]
        explicit_url = item[3] if len(item) > 3 else None
        rel = _safe_rel(path, f"member {name}.path")
        url = explicit_url
        if not url and root is not None:
            url = _member_url(Path(root) / rel)
        out.append({"name": name, "path": rel,
                    "url": _validate_url(url, f"member {name}.url"),
                    "assets": "member", "kind": kind or "fullstack"})
    return out


def _valid_task_slug(slug: str) -> bool:
    if not slug or "/" in slug or "\\" in slug or ".." in slug:
        return False
    if re.match(r"^\d{2}-\d{2}-", slug):
        return False
    return True


def _yaml_value(value: str) -> str:
    """清单值：含 `#` 时加引号，避免被行内注释截断。"""
    s = str(value)
    return f'"{s}"' if "#" in s else s


def _manifest_text(name: str, members: list[dict], contracts: list[dict] | None = None,
                   requirements: list[dict] | None = None,
                   definition: dict | None = None,
                   acceptance_cutover: str | None = None,
                   min_atlas: str | None = None) -> str:
    lines = [
        "# atlas solution（多仓方案层；Phase 1 = federated）",
        f"version: {2 if definition else 1}",
        f"solution: {name}",
        "mode: federated",
    ]
    if definition:
        lines += [
            "definition:",
            f"  domain: {_yaml_value(definition['domain'])}",
            f"  path: {definition['path']}",
        ]
    if acceptance_cutover:
        lines.append(f"acceptance_cutover: {acceptance_cutover}")
    if min_atlas:
        lines.append(f"min_atlas: {_yaml_value(min_atlas)}")
    lines.append("members:")
    for m in members:
        lines += [
            f"  - name: {m['name']}",
            f"    path: {m['path']}",
        ]
        if m.get("url"):
            lines.append(f"    url: {_yaml_value(m['url'])}")
        lines += [
            "    assets: member",
            f"    kind: {m.get('kind') or 'fullstack'}",
        ]
    if contracts:
        lines.append("contracts:")
        for c in contracts:
            lines += [
                f"  - id: {c['id']}",
                f"    producer: {c['producer']}",
                f"    producer_path: {c['producer_path']}",
                f"    consumer: {c['consumer']}",
                f"    consumer_path: {c['consumer_path']}",
            ]
    else:
        lines.append("contracts: []")
    if requirements:
        lines.append("requirements:")
        for r in requirements:
            acs = r["acs"] if isinstance(r["acs"], list) else [
                a.strip() for a in re.split(r"[、,，]", str(r["acs"])) if a.strip()]
            lines += [
                f"  - id: {r['id']}",
                f"    acs: {','.join(acs)}",
                f"    member: {r['member']}",
                f"    task_slug: {r['task_slug']}",
                f"    scope: {_yaml_value(r['scope'])}",
            ]
            if r.get("assignee"):
                lines.append(f"    assignee: {r['assignee']}")
            case_ids = r.get("case_ids") or []
            if isinstance(case_ids, str):
                case_ids = [a.strip() for a in re.split(r"[、,，]", case_ids) if a.strip()]
            if case_ids:
                lines.append(f"    case_ids: {','.join(case_ids)}")
            if r.get("cross_repo_e2e"):
                lines.append(f"    cross_repo_e2e: {r['cross_repo_e2e']}")
    return "\n".join(lines) + "\n"


_PROFILE_PLACEHOLDERS = ("<产品名>", "<app 标识>")


def _write_profile(root: Path, name: str, members: list[dict], assets_root: str) -> None:
    path = root / assets_root / "stack-profile.yaml"
    text = _solution_profile(name, members, assets_root)
    if path.exists():
        if any(p in path.read_text(encoding="utf-8", errors="replace")
               for p in _PROFILE_PLACEHOLDERS):
            path.write_text(text, encoding="utf-8")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _solution_profile(name: str, members: list[dict], assets_root: str) -> str:
    lines = [
        "# atlas solution stack-profile（Phase 1：跨仓 E2E 画像）",
        f"product: {name}",
        "origin: greenfield",
        "apps:",
    ]
    for m in members:
        lines += [
            f"  - name: {m['name']}",
            f"    path: {m['path']}",
            f"    kind: {m.get('kind') or 'fullstack'}",
            "    role: landing",
            "    stack: 由成员仓维护",
        ]
    lines += [
        "adapters:",
        "  routes: null",
        "  api: null",
        "  models: null",
        "  tests: null",
        "e2e:",
        "  runner: node-playwright",
        f"  cases_dir: {assets_root}/e2e/cases",
        f"  index: {assets_root}/e2e/e2e-index.md",
        f"  scripts_dir: {assets_root}/e2e/scripts",
        "  app_base_url: null",
        "  reset: null",
        "  node_modules: null",
    ]
    return "\n".join(lines) + "\n"


def _prd_skeletons(root: Path, name: str, assets_root: str) -> None:
    prd_dir = root / assets_root / "prd"
    prd_dir.mkdir(parents=True, exist_ok=True)
    (root / assets_root / "e2e" / "cases").mkdir(parents=True, exist_ok=True)
    (root / assets_root / "e2e" / "scripts").mkdir(parents=True, exist_ok=True)
    (root / assets_root / "reviews").mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    _write_if_missing(prd_dir / "prd.md", f"""---
doc: prd-global
product: "{name}"
version: 0.1.0
date: "{today}"
status: draft
---

# {name} — 产品需求文档（全局）

范围形态：首建

## 五、功能架构

| 域 slug | 中文名 | 一句话职责 | 域级文件 |
|---|---|---|---|
| solution | 跨仓需求 | 跨仓需求与验收 | `solution-prd.md` |
""")
    template = root / ".atlas" / "templates" / "prd" / "domain.md"
    if not template.is_file():
        template = Path(__file__).resolve().parents[1] / "templates" / "prd" / "domain.md"
    text = template.read_text(encoding="utf-8") if template.is_file() else ""
    text = text.replace('domain: "[必填：domain-slug，如 dubbing-config]"',
                        'domain: "solution"')
    text = text.replace('domain_name: "[必填：中文名]"',
                        f'domain_name: "{name} 跨仓需求"')
    text = text.replace('domain_code: "[必填：ID 前缀，如 DUBBING-CONFIG，用于 FN-/R-/AC- 编号]"',
                        'domain_code: "SOLUTION"')
    text = text.replace('date: "[必填：YYYY-MM-DD]"', f'date: "{today}"')
    _write_if_missing(prd_dir / "solution-prd.md", text)
    _write_if_missing(prd_dir / "README.md", """# PRD 追溯总表

| 域 | 域级文件 | 模块 | 页面 | 功能数 | 规则数 | AC 数 |
|---|---|---|---|---|---|---|
| solution | solution-prd.md | — | — | 0 | 0 | 0 |
""")


def init_solution(root: Path, name: str, members: list[tuple],
                  assets_root: str = "product", install: bool = True,
                  contracts: list[dict] | None = None,
                  requirements: list[dict] | None = None) -> Path:
    root = Path(root).resolve()
    if manifest_path(root).exists():
        raise SolutionError(f"{MANIFEST_NAME} 已存在：{manifest_path(root)}")
    # RFC §5.2 第 8 条 / V-18：三级来源全缺时无法判断自己是 0.3.x 还是 0.4.0，
    # init 要写清单且不可回退 ⇒ fail-closed（exit 2），**不得默认写 v1**。
    reader = reader_version(root)
    if not reader:
        raise SolutionError(
            reader_version_unknown_hint(root)
            + "\n  无法判断当前工具是 0.3.x 还是 0.4.0 ⇒ init 不写任何文件（fail-closed）。"
              "\n  修复：重建 .atlas（install.py --update）或重装 Atlas 后重试。")
    # 0.4.0 起新仓直接写 v2 + definition（v9 阻断：写 v1 会被版本门 {2} 立刻自拒，
    # 而 0.4.0 不注册 migrate，新仓无从就地补）。
    manifest_version = SCHEMA_VERSION if semver_lt(reader, (0, 4, 0)) else 2
    name = _validate_name(name, "solution 名称")
    entries = _member_entries(members, root)
    if not entries:
        raise SolutionError("Phase 1 至少需要一个成员仓（--member name=path）")
    # 写清单前硬拒绝：成员已被父仓跟踪（含 gitlink）时不进入 solution 模型。
    _assert_members_untracked(root, entries)
    # atlas.config.yaml 是资产根的单一来源；已存在时不得用 CLI 默认值覆盖。
    effective_assets = _assets_root(root) if (root / CONFIG_NAME).is_file() else assets_root
    definition = None
    cutover = None
    min_atlas = None
    if manifest_version == 2:
        # 路径由 init 固定（`_prd_skeletons` 会写出），不接受 --definition-path（D-14）。
        rel = f"{effective_assets}/prd/solution-prd.md"
        definition = {"domain": _prd_domain(root / rel) or "solution", "path": rel}
        cutover = "2027-03-31"
        min_atlas = "0.4.0"
    validate_manifest({
        "version": manifest_version,
        "definition": definition,
        "acceptance_cutover": cutover,
        "min_atlas": min_atlas,
        "solution": name,
        "mode": "federated",
        "members": entries,
        "contracts": contracts or [],
        "requirements": requirements or [],
        "requirements_present": bool(requirements),
        "unknown": [],
    }, root, phase1=True)
    if install:
        _install_atlas(root, effective_assets)
    _write_config(root, effective_assets)
    _write_profile(root, name, entries, effective_assets)
    _prd_skeletons(root, name, effective_assets)
    # 清单最后原子落盘：前面的 profile/PRD 中途失败时不留“已初始化”假象，
    # 重跑不会被 manifest 存在检查挡住。
    path = manifest_path(root)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(_manifest_text(name, entries, contracts, requirements,
                                  definition=definition,
                                  acceptance_cutover=cutover,
                                  min_atlas=min_atlas), encoding="utf-8")
    tmp.replace(path)
    # 成员齐全且不在 detached HEAD 时立即写入首版锁：
    # init 即钉住一组可复现版本；成员尚未 clone 时暂不写，避免 head=None 的“假锁”。
    data = load_manifest(root)
    states = [member_state(root, m) for m in data["members"]]
    if all(s["git"] and s.get("branch") not in (None, "HEAD") for s in states):
        write_lock(root, data)
    return path


def _single_prd_path(root: Path, assets_root: str) -> str:
    prd_dir = Path(root) / assets_root / "prd"
    cands = sorted(p.name for p in prd_dir.glob("*-prd.md")) if prd_dir.is_dir() else []
    if not cands:
        raise SolutionError(f"未找到域级 PRD（{assets_root}/prd/*-prd.md）；无法补 definition")
    if len(cands) > 1:
        raise SolutionError("发现多个域级 PRD，无法确定唯一源：" + "、".join(cands))
    return f"{assets_root}/prd/{cands[0]}"


def _prd_domain(path: Path) -> str:
    path = Path(path)
    if not path.is_file():
        return ""
    m = re.match(r"^---\s*\n(.*?)\n---", path.read_text(encoding="utf-8"), re.S)
    if not m:
        return ""
    hit = re.search(r"^domain:\s*(.+?)\s*$", m.group(1), re.M)
    return str(_scalar(hit.group(1)) or "").strip() if hit else ""


def _migrated_manifest_text(text: str, definition: dict | None,
                            scalars: dict[str, str]) -> str:
    """行级补缺：只在缺字段时插入，已有内容逐行保留（不改注释 / 顺序）。"""
    block: list[str] = []
    if definition:
        block += ["definition:",
                  f"  domain: {_yaml_value(definition['domain'])}",
                  f"  path: {definition['path']}"]
    block += [f"{k}: {v}" for k, v in scalars.items()]
    out: list[str] = []
    inserted_at_definition = False
    skip_children = False
    for ln in text.splitlines():
        top = bool(ln) and not ln.startswith((" ", "\t"))
        if skip_children and not top:
            continue
        skip_children = False
        if top and ln.strip().startswith("version:"):
            comment = ""
            if "#" in ln:
                comment = "  " + ln[ln.index("#"):].rstrip()
            out.append(f"version: 2{comment}")
            continue
        if definition and top and (
            ln.strip() == "definition:" or ln.strip().startswith("definition: null")
        ):
            out.extend(block)
            inserted_at_definition = True
            skip_children = True
            continue
        out.append(ln)
    if block and not inserted_at_definition:
        idx = next((i for i, ln in enumerate(out)
                    if ln.strip().startswith("mode:")
                    and not ln.startswith((" ", "\t"))), None)
        if idx is None:
            out.extend(block)
        else:
            out[idx + 1:idx + 1] = block
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def migrate_manifest(root: Path, to: int = 2,
                     definition_path: str | None = None) -> dict:
    """B-0：清单 v1→v2（只补缺，不覆盖已有字段，不自动 lock）。"""
    root = Path(root).resolve()
    if to != 2:
        raise SolutionError("B-0 只支持 --to 2")
    path = manifest_path(root)
    if not path.is_file():
        raise SolutionError(f"缺少 {MANIFEST_NAME}；先执行 atlas solution init/adopt")
    text = path.read_text(encoding="utf-8")
    data = parse_manifest_text(text)
    version = _manifest_version(data.get("version"))
    default_path = f"{_assets_root(root)}/prd/solution-prd.md"
    definition = data.get("definition") or None
    added: list[str] = []
    if definition is None:
        chosen = (definition_path or "").strip() or _single_prd_path(root, _assets_root(root))
        if chosen != default_path:
            raise SolutionError(
                f"B-0 只支持 {default_path}；B 批后支持任意 `-prd.md`（当前: {chosen}）；"
                "未写入任何文件")
        if not (root / chosen).is_file():
            raise SolutionError(
                f"--definition-path 指向的文件不存在: {chosen}；未写入任何文件")
        domain = _prd_domain(root / chosen) or str(data.get("solution") or "").strip()
        definition = {"domain": domain, "path": chosen}
        added.append("definition")
    else:
        if definition_path and definition_path.strip() != (definition.get("path") or ""):
            raise SolutionError("清单已有 definition.path；migrate 只补缺，不覆盖已有字段")
        _manifest_definition(definition, root)
    scalars: dict[str, str] = {}
    if not data.get("acceptance_cutover"):
        scalars["acceptance_cutover"] = "2027-03-31"
        added.append("acceptance_cutover")
    if not data.get("min_atlas"):
        scalars["min_atlas"] = "0.4.0"
        added.append("min_atlas")
    new_text = _migrated_manifest_text(
        text, definition if "definition" in added else None, scalars)
    changed = new_text != text
    if changed:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(new_text, encoding="utf-8")
        tmp.replace(path)
    return {"manifest": str(path), "from": version, "to": 2,
            "added": added, "changed": changed}


def card_tracking_commands(root: Path, data: dict) -> list[str]:
    """`migrate --check-members`：逐成员按实际路径打印卡片 git add -f 命令。"""
    root = Path(root).resolve()
    out: list[str] = []
    for m in data["members"]:
        base = root / m["path"]
        tasks = base / ".trellis" / "tasks"
        cards: list[Path] = []
        if tasks.is_dir():
            cards += sorted(p for p in tasks.iterdir() if p.is_dir() and p.name != "archive")
            archive = tasks / "archive"
            if archive.is_dir():
                cards += sorted(p for p in archive.glob("*/*") if p.is_dir())
        for card in cards:
            files = [card / n for n in ("prd.md", "solution.md") if (card / n).is_file()]
            if files:
                rels = " ".join(shlex.quote(p.relative_to(base).as_posix()) for p in files)
                out.append(f"git -C {shlex.quote(m['path'])} add -f {rels}")
    return out


def detect_members(root: Path) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for child in sorted(Path(root).iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if not _is_git(child):
            continue
        if _has_atlas_assets(child):
            out.append((child.name, child.name, "fullstack"))
    return out


def adopt_solution(root: Path, name: str, members: list[tuple[str, str, str]] | None = None,
                   assets_root: str = "product", install: bool = True) -> tuple[Path, list[dict]]:
    root = Path(root).resolve()
    entries = _member_entries(members or detect_members(root), root)
    if not entries:
        raise SolutionError("未检测到带 Atlas 资产的成员仓；请用 --member name=path 显式指定")
    path = init_solution(root, name, [(m["name"], m["path"], m.get("kind", "fullstack"))
                                      for m in entries],
                         assets_root=assets_root, install=install)
    data = load_manifest(root)
    write_lock(root, data)
    return path, data["members"]


# ---------------------------------------------------------------- status / check

def status(root: Path) -> dict:
    root = Path(root).resolve()
    data = load_manifest(root)
    states = [member_state(root, m) for m in data["members"]]
    lock = read_lock(root)
    for s in states:
        prev = _lock_member(lock, s["name"])
        s["locked_head"] = (prev or {}).get("head")
        s["head_drift"] = bool(prev and prev.get("head")
                               and prev.get("head") != s.get("head"))
        s["dirty_count"] = len(s["dirty"]) if isinstance(s.get("dirty"), list) else None
    return {
        "solution": data["solution"],
        "mode": data["mode"],
        "members": states,
        "lock": {
            "present": lock is not None,
            "locked_at": (lock or {}).get("locked_at"),
        },
        "contracts": contract_states(root, data),
    }


def _lock_member(lock: dict | None, name: str) -> dict | None:
    for m in (lock or {}).get("members") or []:
        if m.get("name") == name:
            return m
    return None


def _lock_contract(lock: dict | None, cid: str) -> dict | None:
    for c in (lock or {}).get("contracts") or []:
        if c.get("id") == cid:
            return c
    return None


def _check_definition_lock(root: Path, data: dict, lock: dict | None, add,
                           allow_unverifiable: bool = False) -> None:
    """定义源与 `definition.commit` 的不可回退判据（RFC §1.1.6 / §5.2 第 8 条）。

    `commit == null` 只在 `init` 首锁（PRD 未入库）合法 ⇒ `definition_commit_pending`
    WARN；一旦「已首次刷新」（锁的完整历史里出现过非 null，或锁里
    `acceptance_cutover != null` 快速正向），当前再为 null ⇒ `definition_commit_unverifiable`
    FAIL，不得落 WARN。
    """
    definition = data.get("definition")
    if not definition:
        return
    rel = definition["path"]
    add("定义源", "PASS", f"{rel}（domain={definition.get('domain')}）")
    if lock is None:
        return
    locked = lock.get("definition")
    if not isinstance(locked, dict):
        add("定义源锁", "WARN",
            "锁中没有 definition 字段；运行 atlas solution lock --update")
        return
    commit = locked.get("commit")
    if not commit:
        if lock.get("acceptance_cutover"):
            add("定义源 commit", "FAIL",
                "definition_commit_unverifiable: 锁内 acceptance_cutover 非 null，"
                "说明已首次刷新，但当前 definition.commit == null")
            return
        hist = _lock_history_definition_commit(root)
        if hist:
            add("定义源 commit", "FAIL",
                f"definition_commit_unverifiable: 当前 definition.commit == null，"
                f"但锁历史 {hist[:12]} 曾写入非 null（完整历史扫描 "
                "--full-history -m）")
        else:
            add("定义源 commit", "WARN",
                "definition_commit_pending: 首次 lock --update 前允许 commit == null；"
                "提交 PRD 后运行 atlas solution lock --update")
        return
    rc, _, _ = _git(root, "cat-file", "-e", f"{commit}^{{commit}}")
    if rc != 0:
        status = "WARN" if allow_unverifiable else "FAIL"
        add("定义源 commit", status,
            f"definition_commit_unverifiable: 本机缺少提交 {commit[:12]}"
            "（浅克隆？CI 需 fetch-depth: 0）")
        return
    rc, blob, _ = _git(root, "rev-parse", f"{commit}:{rel}")
    if rc != 0 or not blob.strip():
        add("定义源 commit", "FAIL",
            f"definition_source_mismatch: {commit[:12]}:{rel} 不存在")
        return
    blob = blob.strip()
    raw = _git_bytes(root, "cat-file", "blob", f"{commit}:{rel}")
    if raw is None:
        add("定义源 commit", "FAIL",
            f"definition_source_mismatch: 无法读取 {commit[:12]}:{rel}")
        return
    want_sha = str(locked.get("sha256") or "")
    sha = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
    if (locked.get("blob") and locked["blob"] != blob) or (want_sha and want_sha != sha):
        add("定义源 commit", "FAIL",
            f"definition_source_mismatch: {commit[:12]}:{rel} 的 blob/sha256 与锁不一致")
    else:
        add("定义源 commit", "PASS", f"{rel} @ {commit[:12]}")
    dirty = _definition_dirty(root, data)
    if dirty:
        add("定义源工作树", "WARN",
            f"definition_worktree_dirty: {rel} 有未提交改动；摘要仍按 blob 复算")


def check_solution(root: Path, strict: bool = False,
                   allow_dangling_acs: bool = False,
                   lenient: bool = False,
                   allow_unverifiable_chain: bool = False) -> dict:
    root = Path(root).resolve()
    data = load_manifest(root)
    results: list[dict] = []
    level = "FAIL" if strict else "WARN"
    add = lambda name, status, detail: results.append(
        {"check": name, "status": status, "detail": detail})

    add("清单 schema", "PASS", f"{data['solution']} / {data['mode']} / {len(data['members'])} 成员")
    if not _is_git(root):
        add("solution 根", level, "不是 git 仓；成员 untracked 没有基线，建议先 git init")
    rc, cfg_out, _ = _git(root, "config", "--get", "status.showUntrackedFiles")
    if rc == 0 and cfg_out.strip().lower() == "no":
        add("git 配置", level,
            "status.showUntrackedFiles=no 会盲掉 _graph / atlas_check / e2e_console")
    if data.get("unknown"):
        add("清单未知键", "WARN", "；".join(data["unknown"]))
    if data.get("requirements"):
        try:
            task_core = _load_sibling("solution_task", "_atlas_solution_task_check")
            seen: set[tuple[str, str, str, str]] = set()
            downgraded = False
            for f in task_core.task_findings(root, data):
                key = (f["code"], f["requirement"], f["member"], f["ac"])
                if key in seen:
                    continue
                seen.add(key)
                if allow_dangling_acs and f["code"] == "ac_missing":
                    downgraded = True
                    add("跨仓任务", "WARN", f["detail"] + "（宽限：--allow-dangling-acs）")
                    continue
                add("跨仓任务", f["level"], f["detail"])
            if downgraded:
                add("宽限", "WARN",
                    "宽限开关已启用：--allow-dangling-acs 将于 0.4.0 移除；"
                    "owner=@sunwenzhe；期限=2026-12-31")
        except Exception as exc:  # noqa: BLE001 - 对账不可用要显式出声
            add("跨仓任务", "WARN", f"对账不可用: {type(exc).__name__}: {exc}")
        for req in data.get("requirements") or []:
            if req.get("unknown"):
                add("跨仓任务", "WARN",
                    f"{req['id']} 未知键: {'、'.join(req['unknown'])}")

    # 父仓跨仓 E2E（RFC-20261108-02 一期）：索引存在性 / 选择器 / 引用 / 接线 / 需求列一致性。
    e2e_audit = None
    try:
        e2e_core = _load_sibling("solution_e2e", "_atlas_solution_e2e")
        e2e_audit = e2e_core.check(root, data)
        for item in e2e_audit["checks"]:
            add(item["check"], item["status"], item["detail"])
    except Exception as exc:  # noqa: BLE001 - 专门检查不可用必须出声
        add("父仓 E2E", "FAIL", f"检查不可用: {type(exc).__name__}: {exc}")

    lock = read_lock(root)
    contracts_now = contract_states(root, data)
    if lock is not None:
        tracking = lock_tracking(root)
        if not tracking["tracked"]:
            add("契约锁跟踪", level,
                f"{LOCK_NAME} 未被父仓 Git 跟踪；CI 无法从父仓 commit 还原锁定版本")
        elif tracking["consistent"] is False:
            add("契约锁跟踪", level,
                f"{LOCK_NAME} 与父仓 HEAD 不一致；请提交锁文件后再跑 CI")
    if lock is None:
        add("契约锁", level, f"缺少 {LOCK_NAME}；运行 atlas solution lock --update")
    else:
        for s in data["members"]:
            prev = _lock_member(lock, s["name"])
            cur = member_state(root, s)
            if prev is None:
                add(f"锁/{s['name']}", level, "锁中没有该成员")
                continue
            if not prev.get("head"):
                add(f"锁/{s['name']}", level, "锁中没有 commit，无法复现成员版本")
            if prev.get("head") != cur.get("head"):
                add(f"锁/{s['name']}", level,
                    f"HEAD 漂移：锁定 {str(prev.get('head'))[:12]} → 当前 {str(cur.get('head'))[:12]}")
            if prev.get("branch") != cur.get("branch"):
                add(f"锁/{s['name']}", level,
                    f"分支漂移：锁定 {prev.get('branch')!r} → 当前 {cur.get('branch')!r}")
            if prev.get("atlas_baseline") != cur.get("atlas_baseline"):
                add(f"锁/{s['name']}", level,
                    f"成员 Atlas baseline 漂移：锁定 {str(prev.get('atlas_baseline'))[:12]} → "
                    f"当前 {str(cur.get('atlas_baseline'))[:12]}")
            if prev.get("path") != s["path"]:
                add(f"锁/{s['name']}", level,
                    f"锁中 path={prev.get('path')!r} 与清单 {s['path']!r} 不一致")
            manifest_url = s.get("url") or ""
            lock_url = prev.get("url") or ""
            if not manifest_url and not lock_url:
                if strict:
                    add(f"锁/{s['name']}", "FAIL",
                        "清单与锁都没有 url；新机器 / CI 无法 bootstrap 成员")
            elif lock_url != manifest_url:
                add(f"锁/{s['name']}", level,
                    "锁中 url 与清单不一致；重新执行 lock --update 并提交")
        for c in contracts_now:
            prev = _lock_contract(lock, c["id"])
            if prev is None:
                add(f"锁/契约 {c['id']}", level, "锁中没有该契约")
                continue
            for side in ("producer_sha256", "consumer_sha256"):
                if prev.get(side) != c[side]:
                    add(f"锁/契约 {c['id']}", level, f"{side} 漂移（需人工确认跨仓影响）")
        member_names = {m["name"] for m in data["members"]}
        contract_ids = {c["id"] for c in contracts_now}
        for lm in lock.get("members") or []:
            if lm.get("name") not in member_names:
                add("锁", level, f"锁中成员已不在清单: {lm.get('name')}")
        for lc in lock.get("contracts") or []:
            if lc.get("id") not in contract_ids:
                add("锁", level, f"锁中契约已不在清单: {lc.get('id')}")
    _check_definition_lock(root, data, lock, add,
                           allow_unverifiable=allow_unverifiable_chain)
    for c in contracts_now:
        missing = [side for side in ("producer_sha256", "consumer_sha256")
                   if c[side] == "missing"]
        if missing:
            add(f"契约 {c['id']}", level,
                "文件缺失：" + "、".join(side.replace("_sha256", "") for side in missing))

    for m in data["members"]:
        s = member_state(root, m)
        prefix = f"成员 {s['name']}"
        if not s["exists"]:
            if lenient:
                add(prefix, "SKIP",
                    f"member_workspace_absent: 路径不存在 {s['path']}（--lenient 跳过）")
            else:
                add(prefix, level, f"member_workspace_absent: 路径不存在: {s['path']}")
            continue
        if s["escaped"]:
            add(prefix, level, "成员路径 resolve 后逃逸出 solution 根（symlink？）")
        if not s["git"]:
            add(prefix, level, "不是 git 仓")
        if not s["atlas_assets"]:
            add(prefix, "WARN", "未检测到 Atlas 资产（atlas.config.yaml / product/stack-profile.yaml / 结构 meta）")
        if s["ignored"]:
            add(prefix, level, "成员路径命中 ignore：" + "、".join(s["ignored"]))
        if s["tracked"]:
            add(prefix, level, f"成员路径已被 solution 仓跟踪（{len(s['tracked'])} 条，疑似 gitlink）")
        if strict and s["git"]:
            if s["dirty"] is None:
                add(prefix, "FAIL", "无法判断工作区是否 dirty（git status 失败）")
            elif s["dirty"]:
                add(prefix, "FAIL",
                    f"工作区有 {len(s['dirty'])} 处未提交改动；strict 要求成员干净")
        if s.get("unknown"):
            add(prefix, "WARN", "成员未知键：" + "、".join(s["unknown"]))

    for rel in (".atlas", f"{_assets_root(root)}/stack-profile.yaml",
                f"{_assets_root(root)}/prd/prd.md",
                f"{_assets_root(root)}/prd/solution-prd.md"):
        if not (root / rel).exists():
            add(f"solution 资产 {rel}", "WARN", "缺失")
    prd = root / _assets_root(root) / "prd" / "solution-prd.md"
    if prd.is_file() and "[必填" in prd.read_text(encoding="utf-8", errors="replace"):
        add("solution-prd.md", "WARN", "仍是模板骨架（含 [必填] 占位），需补齐完整域 PRD")
    profile = root / _assets_root(root) / "stack-profile.yaml"
    if profile.is_file():
        profile_text = profile.read_text(encoding="utf-8", errors="replace")
        if any(p in profile_text for p in _PROFILE_PLACEHOLDERS):
            add("stack-profile.yaml", "WARN",
                "仍是通用模板（含 <产品名>/<app 标识>），需换成 solution 画像")
    trellis_cfg = root / ".trellis" / "config.yaml"
    if trellis_cfg.is_file():
        trellis_text = trellis_cfg.read_text(encoding="utf-8", errors="replace")
        missing = [m["path"] for m in data["members"]
                   if f"path: {m['path']}" not in trellis_text
                   and f"path: ./{m['path']}" not in trellis_text]
        if missing:
            add("Trellis packages", "WARN",
                "未声明成员：" + "、".join(missing))
    else:
        add("Trellis packages", "SKIP",
            "solution 根无 .trellis/config.yaml（Phase 1 不生成；Phase 2）")

    if any(r["status"] == "FAIL" for r in results):
        overall = "FAIL"
    elif any(r["status"] == "WARN" for r in results):
        overall = "WARN"
    else:
        overall = "PASS"
    return {"solution": data["solution"], "mode": data["mode"],
            "overall": overall, "checks": results, "e2e": e2e_audit}


class FixRefused(ValueError):
    """`--fix-acs` 守卫拒绝 / 写回不安全（CLI exit 1，不是清单 schema 错误）。"""


_ACS_LINE = re.compile(r"^(?P<prefix>\s*acs:)(?P<value>.*)$")
_ACS_SEP = re.compile(r"([,、，])")


def _split_acs_core(core: str) -> tuple[list[str], list[str]]:
    parts = _ACS_SEP.split(core)
    tokens = parts[0::2]
    seps = parts[1::2] + [""]
    return tokens, seps


def _acs_token_set(core: str) -> set[str]:
    return {tok.strip() for tok in _split_acs_core(core)[0] if tok.strip()}


def _rebuild_acs_core(core: str, drop: set[str]) -> str:
    tokens, seps = _split_acs_core(core)
    kept = [i for i, tok in enumerate(tokens)
            if tok.strip() and tok.strip() not in drop]
    out: list[str] = []
    for n, i in enumerate(kept):
        out.append(tokens[i])
        if n < len(kept) - 1:
            out.append(seps[i])
    return "".join(out)


def _acs_blocks(lines: list[str]) -> list[dict]:
    """按 `requirements:` 段扫描 `  - id:` 块；只取定位所需信息，不做 YAML 解析。"""
    blocks: list[dict] = []
    in_req = False
    block: dict | None = None
    for idx, raw in enumerate(lines):
        noeol = raw.rstrip("\r\n")
        if re.match(r"^requirements:\s*$", noeol):
            in_req, block = True, None
            continue
        if not in_req:
            continue
        if re.match(r"^\S", noeol):
            in_req, block = False, None
            continue
        m = re.match(r"^  - id:\s*([^#\s]+)\s*$", noeol)
        if m:
            block = {"id": m.group(1), "acs": [], "member": None}
            blocks.append(block)
            continue
        if block is None:
            continue
        if noeol.startswith("    acs:") and _ACS_LINE.match(noeol):
            block["acs"].append(idx)
        mm = re.match(r"^    member:\s*(\S+)\s*$", noeol)
        if mm:
            block["member"] = mm.group(1)
    return blocks


def _locate_acs_line(block: dict, req: dict, lines: list[str]) -> tuple[int, str, str]:
    """返回 (行号, 去掉前导空白的 core, 前导空白)；无法唯一定位即拒绝。"""
    if len(block["acs"]) != 1:
        raise FixRefused(
            f"requirement={req['id']}：原始文本中 `acs:` 行出现 {len(block['acs'])} 次，"
            "无法唯一定位；不修复、不半写。请手工改成单行 `acs:`")
    idx = block["acs"][0]
    body = strip_inline_comment(lines[idx].rstrip("\r\n"))
    m = _ACS_LINE.match(body)
    if m is None:
        raise FixRefused(f"requirement={req['id']}：`acs:` 行无法解析（第 {idx + 1} 行）")
    core = m.group("value")
    lead = core[:len(core) - len(core.lstrip())]
    core = core[len(lead):]
    tokens = [t.strip() for t in _split_acs_core(core)[0] if t.strip()]
    if tokens != req["acs"]:
        raise FixRefused(
            f"requirement={req['id']}：`acs:` 行与清单解析结果对不上"
            f"（行内 {tokens} ≠ 清单 {req['acs']}）；不猜，请人工核对")
    return idx, core, lead


def fix_acs(root: Path, data: dict, apply: bool = False) -> dict:
    """行级保字节移除悬空 AC（#50）；不重生成清单，不碰其它行。

    守卫顺序：定义源不可用 ⇒ 目标行无法唯一定位 ⇒ 删空某条 requirement。
    定义源判据与 `check_solution` 同源（`solution_task.ac_source_status`）。
    """
    root = Path(root).resolve()
    task_core = _load_sibling("solution_task", "_atlas_solution_task_fix")
    assets_root = _assets_root(root)
    reqs = data.get("requirements") or []
    if not reqs:
        return {"apply": apply, "removals": []}
    source = task_core.ac_source_status(root, data, assets_root)
    if source["state"] == "source_unavailable":
        raise FixRefused(source["findings"][0]["detail"])
    defs = task_core._ac_defs(root, assets_root)

    path = manifest_path(root)
    lines = path.read_bytes().decode("utf-8").splitlines(keepends=True)
    blocks = _acs_blocks(lines)
    by_id: dict[str, list[dict]] = {}
    for req in reqs:
        by_id.setdefault(req["id"], []).append(req)

    edits: list[tuple[int, str]] = []
    removals: list[dict] = []
    for rid, rows in by_id.items():
        matched = [b for b in blocks if b["id"] == rid]
        if len(matched) != 1:
            raise FixRefused(
                f"requirement={rid}：清单原始文本中同 id 块出现 {len(matched)} 次，"
                "无法唯一定位 `acs:` 行；不修复、不半写")
        req, block = rows[0], matched[0]
        if block["member"] not in (None, req["member"]):
            raise FixRefused(
                f"requirement={rid}：`- id:` 块 member={block['member']!r} 与清单 "
                f"{req['member']!r} 不一致；不猜，请人工核对")
        idx, core, lead = _locate_acs_line(block, req, lines)
        drop = {ac for ac in req["acs"] if ac not in defs}
        if not drop:
            continue
        if not (_acs_token_set(core) - drop):
            raise FixRefused(
                f"requirement={rid} 唯一 AC 已悬空；拒绝清空。"
                "请补 PRD 定义行，或手工删除整条 requirement（工具不代删）")
        raw = lines[idx]
        eol = raw[len(raw.rstrip("\r\n")):]
        body = strip_inline_comment(raw.rstrip("\r\n"))
        comment = raw.rstrip("\r\n")[len(body):]
        prefix = _ACS_LINE.match(body).group("prefix")
        edits.append((idx, prefix + lead + _rebuild_acs_core(core, drop) + comment + eol))
        for ac in sorted(drop):
            removals.append({"requirement": rid, "member": req["member"],
                             "ac": ac, "line": idx + 1})

    result = {"apply": apply, "removals": removals}
    if not apply or not edits:
        return result

    new_lines = list(lines)
    for idx, new in edits:
        new_lines[idx] = new
    changed = {idx for idx, _ in edits}
    original = path.read_bytes()
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            fh.write("".join(new_lines))
        tmp.replace(path)
        written = path.read_bytes().decode("utf-8").splitlines(keepends=True)
        if len(written) != len(lines) or any(
                a != b for i, (a, b) in enumerate(zip(lines, written))
                if i not in changed):
            raise FixRefused("写回后逐字节比对失败，已回滚（非目标行发生变化）")
    except Exception:
        path.write_bytes(original)
        raise
    finally:
        tmp.unlink(missing_ok=True)
    return result


def diff_solution(root: Path) -> dict:
    """只读对账：每个成员相对锁的提交、diffstat 与工作区改动。"""
    root = Path(root).resolve()
    data = load_manifest(root)
    lock = read_lock(root)
    members: list[dict] = []
    for m in data["members"]:
        path = (root / m["path"]).resolve()
        prev = _lock_member(lock, m["name"]) or {}
        entry = {
            "name": m["name"],
            "path": m["path"],
            "git": _is_git(path),
            "branch": None,
            "head": None,
            "locked_head": prev.get("head"),
            "lock_commit_present": None,
            "commits": [],
            "diffstat": [],
            "staged": [],
            "unstaged": [],
            "worktree": [],
            "worktree_ok": None,
        }
        if entry["git"]:
            entry["branch"] = _branch(path)
            entry["head"] = _head(path)
            locked = prev.get("head")
            if locked:
                rc, _, _ = _git(path, "cat-file", "-e", f"{locked}^{{commit}}")
                entry["lock_commit_present"] = rc == 0
                if rc == 0 and locked != entry["head"]:
                    entry["commits"] = _git_lines(
                        path, "log", "--oneline", "--max-count=50",
                        f"{locked}..HEAD") or []
                    entry["diffstat"] = _git_lines(
                        path, "diff", "--stat", f"{locked}..HEAD") or []
            entry["staged"] = _git_lines(path, "diff", "--cached", "--stat") or []
            entry["unstaged"] = _git_lines(path, "diff", "--stat") or []
            worktree = _status_lines(path)
            entry["worktree_ok"] = worktree is not None
            entry["worktree"] = worktree or []
        members.append(entry)
    return {"solution": data["solution"], "mode": data["mode"], "members": members}


def has_apply_seal(root: Path) -> bool:
    """仓内是否存在封条（`<assets_root>/reviews/apply/**/*.seal.json`，RFC §3.3）。

    有封条 ⇒ 必须严格态；`--lenient` 只允许在尚无封条时使用（只有锁不拒绝，Q-6）。
    """
    root = Path(root)
    base = root / _assets_root(root) / "reviews" / "apply"
    if not base.is_dir():
        return False
    return any(base.rglob("*.seal.json"))


def _assets_root(root: Path) -> str:
    config = root / CONFIG_NAME
    if config.is_file():
        for line in config.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if s.startswith("assets_root:"):
                v = _scalar(s.split(":", 1)[1])
                if isinstance(v, str) and v:
                    return v
    return "product"


def render_status(data: dict) -> str:
    lines = [f"solution: {data['solution']} ({data['mode']})", "members:"]
    for s in data["members"]:
        head = (s.get("head") or "—")[:12]
        dirty_n = s.get("dirty_count")
        dirty = "clean" if dirty_n == 0 else (f"dirty:{dirty_n}" if dirty_n else "n/a")
        ignored = "ignored" if s.get("ignored") else "ok"
        if s.get("head_drift"):
            drift = "drift"
        elif s.get("locked_head"):
            drift = "locked"
        else:
            drift = "no-lock"
        lines.append(
            f"  {s['name']:<16} {s['path']:<20} git={str(s['git']).lower():<5} "
            f"branch={s.get('branch') or '—':<12} head={head:<12} {dirty:<8} "
            f"{drift:<7} atlas={'yes' if s['atlas_assets'] else 'no':<3} {ignored}")
    lines.append(f"lock: {'present' if data['lock']['present'] else 'missing'}"
                 + (f" ({data['lock']['locked_at']})" if data['lock'].get('locked_at') else ""))
    return "\n".join(lines)


def render_check(data: dict) -> str:
    lines = [f"solution check: {data['overall']}"]
    for r in data["checks"]:
        lines.append(f"  [{r['status']}] {r['check']}: {r['detail']}")
    return "\n".join(lines)


def render_diff(data: dict) -> str:
    lines = [f"solution diff: {data['solution']} ({data['mode']})"]
    for m in data["members"]:
        if not m["git"]:
            lines.append(f"  [{m['name']}] {m['path']}  ! 不是 git 仓")
            continue
        locked = (m.get("locked_head") or "—")[:12]
        lines.append(
            f"  [{m['name']}] {m['path']} branch={m.get('branch') or '—'} "
            f"head={(m.get('head') or '—')[:12]} locked={locked}")
        if not m.get("locked_head"):
            lines.append("    lock=—（未锁定，仅显示工作区）")
        elif m.get("lock_commit_present") is False:
            lines.append("    ! 锁中 commit 不在本地；请先 fetch 对应成员")
        elif m["commits"]:
            lines.append(f"    自锁以来提交 {len(m['commits'])} 条:")
            lines += [f"      {c}" for c in m["commits"]]
            if m["diffstat"]:
                lines.append("    自锁以来 diffstat:")
                lines += [f"      {c}" for c in m["diffstat"]]
        if m["staged"]:
            lines.append("    已暂存:")
            lines += [f"      {c}" for c in m["staged"]]
        if m["unstaged"]:
            lines.append("    未暂存:")
            lines += [f"      {c}" for c in m["unstaged"]]
        if m["worktree"]:
            lines.append(f"    工作区 {len(m['worktree'])} 项:")
            lines += [f"      {c}" for c in m["worktree"][:30]]
            if len(m["worktree"]) > 30:
                lines.append(f"      …（其余 {len(m['worktree']) - 30} 项省略）")
        if m.get("worktree_ok") is False:
            lines.append("    ! git status 失败，无法判断工作区")
        if not any((m["commits"], m["staged"], m["unstaged"], m["worktree"])):
            lines.append("    clean（相对锁无差异）")
    return "\n".join(lines)
