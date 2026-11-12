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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import NamedTuple
from urllib.parse import urlsplit, urlunsplit

MANIFEST_NAME = "atlas.solution.yaml"
LOCK_NAME = "atlas.solution.lock.json"
CONFIG_NAME = "atlas.config.yaml"
SCHEMA_VERSION = 1
# B 批起 v2 清单的首锁升 2（带 definition / acceptance_cutover）；v1 清单的锁仍是 1。
LOCK_SCHEMA_VERSION = 2
# PRD front matter 的结构档位（RFC §1.5 / §5.2 第 10 条）：2 起立即要求 Assumptions
# 证据两列；1 只享受截止日前的 WARN 缓冲。
PRD_SCHEMA_VERSION = 2
# `prd_schema: 1` 的证据列缓冲截止日：2027-06-30（含）前 WARN，2027-07-01 起 FAIL。
EVIDENCE_COLUMNS_DEADLINE = "2027-06-30"
# `prd_schema_too_low` 的锚点：0.4.0 的发布日期（含），填 YYYY-MM-DD。
# 0.4.0 未发布前为 None ⇒ 不判（发布前任何 PRD 的首次提交都早于发布点，本就该走缓冲）；
# **0.4.0 发布时必须填成实际日期**，否则该判据永远不触发。
PRD_SCHEMA_2_FROM: str | None = None
EVIDENCE_COLUMNS = ("证据状态", "证据指针")
# B 批的验收切点与 v2 最低工具版本：`init` 与 `migrate` 共用。
# CLI 覆盖走 `--cutover`（见 `resolve_cutover`），不要手改清单后再 lock：两边值不等
# 会被 `acceptance_cutover_mismatch` 判红。
ACCEPTANCE_CUTOVER_DEFAULT = "2027-03-31"
# `--cutover` 往后推的上限：默认值 + 90 天（按日期算，不写死日期；等于上限算通过）。
ACCEPTANCE_CUTOVER_MAX_DAYS = 90
MIN_ATLAS_FOR_V2 = "0.4.0"
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
# 资产根校验单源（v19/v20）：检查器不得再写第二套字符集。
_LAYOUT = _load_sibling("layout", "_atlas_solution_layout")


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
                  "definition": None, "acceptance_cutover": None,
                  "acceptance_cutover_review": None, "min_atlas": None}
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
            if key in ("version", "solution", "mode", "acceptance_cutover",
                       "acceptance_cutover_review", "min_atlas"):
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


def resolve_cutover(cutover: str | None = None,
                    anchor_review: str | None = None) -> str:
    """`--cutover` 的唯一实现（v19/v20）：`init` 与 `migrate --to 2` 共用。

    - 不给 ⇒ 包级默认 `ACCEPTANCE_CUTOVER_DEFAULT`；
    - 晚于默认 ⇒ 必须同时给 `--anchor-review`，且不得晚于「默认 + 90 天」
      （上限用 `default + timedelta(days=90)` 算，不写死日期；等于上限算通过）；
    - 早于默认 ⇒ 允许（收紧切点只会缩短豁免，不会延长）。
    """
    value = (cutover or "").strip() or ACCEPTANCE_CUTOVER_DEFAULT
    try:
        target = datetime.strptime(value, "%Y-%m-%d").date()
        base = datetime.strptime(ACCEPTANCE_CUTOVER_DEFAULT, "%Y-%m-%d").date()
    except ValueError as exc:
        raise SolutionError(f"acceptance_cutover 必须是 YYYY-MM-DD: {value!r}") from exc
    if target <= base:
        return value
    if not (anchor_review or "").strip():
        raise SolutionError(
            f"--cutover {value} 晚于默认 {ACCEPTANCE_CUTOVER_DEFAULT}；"
            "往后推切点必须同时给 --anchor-review <REVIEW-ID>")
    ceiling = base + timedelta(days=ACCEPTANCE_CUTOVER_MAX_DAYS)
    if target > ceiling:
        raise SolutionError(
            f"--cutover {value} 超过上限 {ceiling.isoformat()}"
            f"（默认 {ACCEPTANCE_CUTOVER_DEFAULT} + {ACCEPTANCE_CUTOVER_MAX_DAYS} 天）")
    return value


# 切点评审号的唯一形态（RFC §5.1 `acceptance_cutover_review` / §3.2 第 10 步 reanchor.review）。
REVIEW_ID_RE = re.compile(r"^REVIEW-\d{8}-\d{2}$")


def validate_anchor_review(value: str | None) -> str | None:
    """写侧（`init` / `migrate` 的 `--anchor-review`）：形态必须是 `REVIEW-\\d{8}-\\d{2}`。

    空值 ⇒ None；不符 ⇒ `SolutionError`（exit 2、调用方保证不落盘）。
    读侧的坏值是另一条路：`check` 报 `acceptance_cutover_review_malformed` FAIL（exit 1），
    不在这里抛——一份坏值不该让整份报告消失。
    """
    s = (value or "").strip()
    if not s:
        return None
    if not REVIEW_ID_RE.fullmatch(s):
        raise SolutionError(
            f"--anchor-review 必须是 REVIEW-YYYYMMDD-NN（正则 REVIEW-\\d{{8}}-\\d{{2}}）: "
            f"{value!r}")
    return s


def _cutover_note(value: str, cutover: str | None) -> str:
    """给 CLI 打印一行来源说明（默认值要显式提示可用 `--cutover` 覆盖）。"""
    if (cutover or "").strip():
        return f"acceptance_cutover={value}"
    return f"acceptance_cutover={value}（可用 --cutover 覆盖）"


def _manifest_version(raw, root: Path | None = None) -> int:
    """清单 schema 版本门（RFC §5.2 / §5.3）。

    判定依据是**读者版本**（工具自身，见 `reader_version`）：
    - 不可判（`""`）：不设门，`{1,2}` 都收——判不出自身版本时不得误拒；
    - `< 0.3.0`：只收 `1`（v2 清单是 0.3.0 才引入的，旧读者读不懂 `definition`）；
    - `0.3.x`（B-0 发布带）：`{1,2}`（迁移窗口）；
    - `>= 0.4.0`：只收 `2`，v1 给迁移口令而不是裸拒（0.4.0 不再注册 `migrate`）。
    """
    value = str(raw or "").strip()
    reader = reader_version(Path(root)) if root is not None else ""
    allowed = {"1", "2"}
    if reader and semver_lt(reader, (0, 3, 0)):
        allowed = {"1"}
    elif reader and not semver_lt(reader, (0, 4, 0)):
        allowed = {"2"}
    if value not in allowed:
        if value not in ("1", "2"):
            raise SolutionError(
                "manifest_schema_unsupported: 清单 version 必须为 1 或 2"
                f"（当前: {value or '缺失'}）")
        if reader and not semver_lt(reader, (0, 4, 0)):
            raise SolutionError(
                f"manifest_schema_unsupported: 读者 {reader}（≥0.4.0）只接受清单 v2"
                f"（当前 v{value}）；先用 0.3.x 跑 `atlas solution migrate --to 2` "
                "再 `lock --update`（0.4.0 不注册 migrate）")
        raise SolutionError(
            f"manifest_schema_unsupported: 读者 {reader}（<0.3.0）只接受清单 v1"
            f"（当前 v{value}）；请升级 Atlas 后再读 v2 清单")
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
    version = _manifest_version(data.get("version"), root)
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

    cutover = (str(data.get("acceptance_cutover")).strip()
               if data.get("acceptance_cutover") else None)
    # `acceptance_cutover_review`：切点评审号（与 `--anchor-review` 同取值口径）。
    # 只做「非空字符串 / 不留空白」形态校验；`REVIEW-\d{8}-\d{2}` 与台账查询归判据侧。
    cutover_review = (str(data.get("acceptance_cutover_review")).strip()
                      if data.get("acceptance_cutover_review") else None)
    if version == 2:
        # v18：v2 清单**必填** `acceptance_cutover`（`init` 与 `migrate --to 2` 都写）。
        if not cutover:
            raise SolutionError(
                "acceptance_cutover_missing: 清单 v2 必须声明 acceptance_cutover"
                "（YYYY-MM-DD）；用 0.3.x 跑 migrate --to 2 或手补后重跑 lock --update")
        try:
            datetime.strptime(cutover, "%Y-%m-%d")
        except ValueError as exc:
            raise SolutionError(
                f"acceptance_cutover 必须是 YYYY-MM-DD: {cutover!r}") from exc
    return {
        "version": version,
        "definition": _manifest_definition(data.get("definition"), root),
        "acceptance_cutover": cutover,
        "acceptance_cutover_review": cutover_review,
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

def _front_matter_of(text: str) -> dict[str, str]:
    """解析文本里的 YAML front matter（只取标量；不引入 YAML 依赖）。"""
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
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


def _prd_front_matter(path: Path) -> dict[str, str]:
    """读 PRD 的 YAML front matter（只取标量；不引入 YAML 依赖）。"""
    if not path.is_file():
        return {}
    return _front_matter_of(path.read_text(encoding="utf-8"))


def _positive_int(raw: str, field: str) -> int:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise SolutionError(f"{field}_invalid: 必须是整数（当前: {raw!r}）")
    if value < 1:
        raise SolutionError(f"{field}_invalid: 必须 ≥ 1（当前: {value}）")
    return value


def _assumption_table_header(text: str) -> list[str] | None:
    """取 Assumptions 节内第一张表的表头单元格；无节 / 无表 ⇒ None。

    节名收中文同义词（`假设` / `默认值`）：模板之外的实际写法常见 `## 六、假设与默认值`，
    只认 `Assumptions` 会把整节当成未声明而跳过证据列判据。
    """
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(r"^#{2,3}\s.*(Assumptions|假设|默认值)", line):
            start = i + 1
            break
    if start is None:
        return None
    for line in lines[start:]:
        if re.match(r"^#{1,3}\s", line):
            return None
        s = line.strip()
        if s.startswith("|") and s.endswith("|"):
            return [c.strip() for c in s.strip("|").split("|")]
    return None


def _first_commit_date(root: Path, rel: str) -> str | None:
    """文件首次被 add 的提交时间（`%aI`，ISO8601），取最早一条；未提交 ⇒ None。"""
    lines = _git_lines(root, "log", "--diff-filter=A", "--format=%aI", "--", rel)
    if not lines:
        return None
    return lines[-1].strip() or None


def prd_schema_too_low(root: Path, rel: str, text: str) -> str | None:
    """按**首次提交时间**判 `prd_schema: 1` 是否已过期（RFC §1.5 / E-03）。

    0.4.0 发布后才首次提交的 PRD 若仍写 `1`，是想靠存量缓冲绕过证据列（新 PRD 必须
    自带证据列）⇒ `prd_schema_too_low` FAIL。首次提交早于发布点的存量 PRD 继续走
    WARN 缓冲（`prd_schema_findings`）。

    锚点 `PRD_SCHEMA_2_FROM` 为 `None` 时**不判**：0.4.0 尚未发布，任何 PRD 的首提交
    都早于发布点，不判即正确（不是 fail-open）。发布时把常量填成实际日期。
    """
    if PRD_SCHEMA_2_FROM is None:
        return None
    fm = _front_matter_of(text)
    try:
        schema = _positive_int(fm.get("prd_schema") or 1, "prd_schema")
    except SolutionError:
        return None
    if schema != 1:
        return None
    first = _first_commit_date(root, rel)
    if first is None or first[:10] <= PRD_SCHEMA_2_FROM:
        return None
    return (f"prd_schema_too_low: {rel} 首次提交于 {first[:10]}（晚于 0.4.0 发布点 "
            f"{PRD_SCHEMA_2_FROM}）却声明 prd_schema: 1；0.4.0 起新建 PRD 必须写 2")


def prd_schema_findings(text: str, rel: str, today: date | None = None
                        ) -> list[tuple[str, str]]:
    """`prd_schema` 与 Assumptions 证据列的谓词（RFC §1.5 / E-03 / E-08）。

    - `prd_schema: 2`（及以上）：**立即**要求 `证据状态` / `证据指针` 两列，缺列 ⇒ FAIL，
      不享受缓冲；
    - `prd_schema: 1`（或未写，按 1）：缺列在 `2027-06-30`（含）前 WARN
      `evidence_deadline_approaching`，`2027-07-01` 起 FAIL；
    - 无 Assumptions 表（既有惯例写「无」或开户最小集整节缺席）：没有证据行可挂，
      不判缺列（C-05/E-05 的「旧四列」只针对存在表头的表）；
    - 高于工具支持档位 ⇒ FAIL `prd_schema_unsupported`。
    """
    fm = _front_matter_of(text)
    try:
        schema = _positive_int(fm.get("prd_schema") or 1, "prd_schema")
    except SolutionError as exc:
        return [("FAIL", f"{exc}（{rel}）")]
    if schema > PRD_SCHEMA_VERSION:
        return [("FAIL", f"prd_schema_unsupported: {rel} 的 prd_schema={schema} "
                         f"高于工具支持的 {PRD_SCHEMA_VERSION}")]
    header = _assumption_table_header(text)
    if header is None:
        return [("PASS", f"{rel} 未声明 Assumptions 表（无证据行，跳过证据列判据）")]
    missing = [c for c in EVIDENCE_COLUMNS if c not in header]
    if not missing:
        return [("PASS", f"{rel} 的 Assumptions 表含 {' / '.join(EVIDENCE_COLUMNS)}")]
    columns = " / ".join(missing)
    if schema >= 2:
        return [("FAIL", f"evidence_columns_missing: {rel} 的 prd_schema={schema} "
                         f"立即要求证据两列，缺 {columns}（无缓冲）")]
    day = date.today() if today is None else today
    deadline = date.fromisoformat(EVIDENCE_COLUMNS_DEADLINE)
    if day <= deadline:
        return [("WARN", f"evidence_deadline_approaching: {rel} 缺 {columns}；"
                         f"{EVIDENCE_COLUMNS_DEADLINE}（含）前只 WARN，次日 2027-07-01 起 FAIL")]
    return [("FAIL", f"evidence_columns_missing: {rel} 缺 {columns}；"
                     f"prd_schema: 1 的缓冲已于 {EVIDENCE_COLUMNS_DEADLINE} 到期")]


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


def validate_assets_root(root: Path, raw, lexical: bool = True) -> str:
    """资产根校验的**单源**：直接调 `_support/layout.py`，不另立字符集（v19/v20）。

    `layout.py` 只禁反斜杠、引号、`#`、换行、绝对路径、`..`、保留首段
    （`.atlas` / `.trellis`）与 symlink 逃逸；**不禁中文、不禁空格**——`install.py
    --assets-root 产品` 走的正是它。检查器若自己写正则，会出现「合法装进去、check
    永久红、append-only 数组又没有出口」。

    写侧默认 `lexical=True`（零 FS 访问）：历史根今天若已成仓外 symlink 或普通文件，
    用今天的工作树去判会永红；FS 逃逸检查只留给 `install.py` 写入与当前根的判据。
    """
    if not isinstance(raw, str) or not raw.strip():
        raise SolutionError("assets_root 不能为空")
    s = raw.strip()
    try:
        _LAYOUT.validate_value(Path(root), "assets_root", s, lexical=lexical)
    except _LAYOUT.LayoutError as exc:
        raise SolutionError(f"assets_root 非法（layout.py 单源口径）: {exc}") from exc
    return s


def _root_history_fields(root: Path, lock: dict | None, assets_root: str | None,
                         anchor_review: str | None) -> tuple[str, list[dict]]:
    """`layout_assets_root` + `assets_root_history` 的**写侧**（RFC §1.1.3 资产根）。

    **只允许「首次写入」或「尾部追加」**：既有元素原样保留——同一个 dict 对象、
    同一顺序、不补键、不排序、不归一化、不重写。

    理由是 C 批的根集 `U` 从锁文件的**全部历史版本**求并集：B 若在这里重排 / 归一化
    既有元素，C 读到的就是被 B 污染过的历史，而且这种污染是 fail-open 的（`U` 缩小后，
    路径级 / 状态机 / 链级三段一起不触发）。因此任何「需要修正既有元素」的形态都
    **不在这里修**，直接拒绝写入，留给判据侧（v17）报 `assets_root_history_rewritten`。

    改根（追加）必须显式给 `assets_root` + `anchor_review`：只改 `atlas.config.yaml`
    不会让本函数追加，避免「改 config ⇒ 锁被改写」这条 v15 攻击在写侧复现。
    历史元素 `{root, review, commit}` 的 `commit` 只作审计、不参与任何断言。
    """
    if lock is None:
        cur = validate_assets_root(root, assets_root if assets_root is not None
                                   else _assets_root(root))
        return cur, [{"root": cur, "review": None, "commit": None}]

    history = lock.get("assets_root_history")
    layout = lock.get("layout_assets_root")
    if history is None and layout is None:
        # B 批之前的 v2 锁（没有这两个字段）：按首写落，形态与 init 首锁一致。
        cur = validate_assets_root(root, assets_root if assets_root is not None
                                   else _assets_root(root))
        return cur, [{"root": cur, "review": None, "commit": None}]
    if (not isinstance(history, list) or not history
            or any(not isinstance(item, dict) for item in history)):
        raise SolutionError(
            f"{LOCK_NAME} 的 assets_root_history 不是非空对象数组；拒绝写入"
            "（写侧只追加、不修既有元素，交判据侧报 assets_root_history_rewritten）")
    last = history[-1].get("root")
    if not isinstance(last, str) or layout != last:
        raise SolutionError(
            f"{LOCK_NAME} 的 layout_assets_root 与 assets_root_history[-1] 不一致；"
            "拒绝写入（写侧不做归一化）")
    if assets_root is None or validate_assets_root(root, assets_root) == last:
        # 当前根未变 ⇒ 幂等：不 append、不碰既有元素，layout 原样返回。
        return layout, list(history)
    review = (anchor_review or "").strip()
    if not review:
        raise SolutionError(
            "改资产根必须同时给评审号：assets_root 变化时需 --anchor-review "
            "<REVIEW-ID>（RFC §1.1.3 资产根 ⑤）；只改 atlas.config.yaml 不会追加历史")
    new = validate_assets_root(root, assets_root)
    return new, list(history) + [
        {"root": new, "review": review, "commit": _head(root)}]


def _existing_lock_for_write(root: Path) -> dict | None:
    """写锁前读旧锁；存在但解析不出结构 ⇒ 拒绝覆盖（否则会丢历史根）。"""
    path = lock_path(root)
    if not path.is_file():
        return None
    lock = read_lock(root)
    if lock is None:
        raise SolutionError(
            f"{LOCK_NAME} 存在但无法解析；拒绝覆盖"
            "（会丢掉 assets_root_history 的全部历史版本）")
    return lock


def lock_payload(root: Path, data: dict, assets_root: str | None = None,
                 anchor_review: str | None = None) -> dict:
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
        # B 批起以**清单 v2** 决定锁 schema（=2），不再看 reader_version；init 的
        # reader_version 分支（<0.4.0 写 v1 清单）与之在 0.3.x/0.4.0 上等价：
        # 0.3.x 只会产出 v1，0.4.0 只会产出 v2，不存在「清单 v2 却写锁 1」的新路径。
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
        # 切点评审号：非空才写同名键（空不写 `null`，否则等于给「未评审」发键）。
        if data.get("acceptance_cutover_review"):
            payload["acceptance_cutover_review"] = data["acceptance_cutover_review"]
        # 根字段的写侧只做「首写」或「尾追加」（见 `_root_history_fields`）：
        # `assets_root_changed` / `assets_root_history_rewritten` 的判据侧随 v17 落地。
        layout_root, root_history = _root_history_fields(
            root, _existing_lock_for_write(root), assets_root, anchor_review)
        payload["layout_assets_root"] = layout_root
        payload["assets_root_history"] = root_history
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


def write_lock(root: Path, data: dict, require_clean: bool = False,
               assets_root: str | None = None,
               anchor_review: str | None = None) -> Path:
    if require_clean:
        dirty = _definition_dirty(root, data)
        if dirty:
            first = dirty.splitlines()[0]
            raise SolutionError(
                f"定义源工作树不干净（{first}）；先提交 {data['definition']['path']} "
                "再执行 atlas solution lock --update")
    payload = lock_payload(root, data, assets_root=assets_root,
                           anchor_review=anchor_review)
    path = lock_path(root)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(path)
    return path


def read_lock(root: Path) -> dict | None:
    """严格解析锁；**只做两件事，不设跨版本必需字段集**（v18 边界）：

    ① `schema_version` 必须是非 bool 的 `int` 且 ∈ {1,2}——`1.0 in (1,2)` 与
       `True in (1,2)` 都为真，所以先卡 `type(...) is int`；写 3 也不得被当成
       「更新的合法锁」而跳过全部判据；
    ② 字段**存在则**类型 / 结构正确（`members` / `contracts` 是 list-of-dict）。

    历史版本的锁没有 `definition.*`、根字段或 `seal_anchors` 是**合法**的：按当前
    必需集去解旧版本会让所有有历史的仓永久红。当前锁的必需集只由「当前锁」那条
    判据负责，不在这里做。
    """
    data = _read_json(lock_path(root))
    if not isinstance(data, dict):
        return None
    schema = data.get("schema_version")
    if type(schema) is not int or schema not in (SCHEMA_VERSION, LOCK_SCHEMA_VERSION):
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
                   acceptance_cutover_review: str | None = None,
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
    if acceptance_cutover_review:
        lines.append(
            f"acceptance_cutover_review: {_yaml_value(acceptance_cutover_review)}")
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
                  requirements: list[dict] | None = None,
                  cutover: str | None = None,
                  anchor_review: str | None = None) -> Path:
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
    min_atlas = None
    # v1 不写 acceptance_cutover（v18：缺省只给 migration_required WARN）；
    # v2 才走 `resolve_cutover`（默认值 / --anchor-review / 上限）。
    if manifest_version != 2:
        # 显式给了就必须有反馈：v1 清单没有 `acceptance_cutover` / `_review` 字段，
        # 静默丢弃会让「超上限会拒、写进去却沉默」两种行为并存。
        if (cutover or "").strip():
            raise SolutionError(
                f"`--cutover` 需要 0.4.0 清单（v2）；当前读者 {reader} 只能写 v1 清单，"
                "acceptance_cutover 无处落盘（拒绝静默忽略）。"
                "请升级到 0.4.0 后重试 init，或升级后用 "
                "`atlas solution migrate --to 2 --cutover <YYYY-MM-DD>` 补写。")
        if (anchor_review or "").strip():
            raise SolutionError(
                f"`--anchor-review` 需要 0.4.0 清单（v2）；当前读者 {reader} 只能写 v1 清单，"
                "acceptance_cutover_review 无处落盘（拒绝静默忽略）。"
                "请升级到 0.4.0 后重试 init。")
        cutover = None
        anchor_review = None
    else:
        # 路径由 init 固定（`_prd_skeletons` 会写出），不接受 --definition-path（D-14）。
        rel = f"{effective_assets}/prd/solution-prd.md"
        definition = {"domain": _prd_domain(root / rel) or "solution", "path": rel}
        # 写侧形态门先于任何落盘：坏 review 值与 v1 下 `--cutover` 同形（exit 2、零文件）。
        anchor_review = validate_anchor_review(anchor_review)
        cutover = resolve_cutover(cutover, anchor_review)
        min_atlas = MIN_ATLAS_FOR_V2
    # `--anchor-review` 给了就必须落盘（v2 才有该字段；v1 上面已经拒绝）。
    cutover_review = (anchor_review or "").strip() or None
    validate_manifest({
        "version": manifest_version,
        "definition": definition,
        "acceptance_cutover": cutover,
        "acceptance_cutover_review": cutover_review,
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
                                  acceptance_cutover_review=cutover_review,
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
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SolutionError(f"无法以 UTF-8 读取 {path}: {exc}") from exc
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
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


def _prd_front_matter_patch(path: Path, additions: dict[str, str]) -> tuple[str, list[str]]:
    """算出打了补丁的 PRD 全文（**不落盘**）：供 migrate 先校验、后统一写盘。

    失败（不可读 / 非 UTF-8 / 缺 front matter）一律 `SolutionError`，调用方据此保证
    磁盘零变化——以前的顺序是「先写清单、再读 PRD」，PRD 非 UTF-8 时清单已经被改。
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SolutionError(f"无法读取 {path}: {exc}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SolutionError(f"{path} 不是 UTF-8（{exc}）；未写入任何文件") from exc
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if m is None:
        raise SolutionError(f"{path} 缺 front matter（`---` 包裹的头部）；未写入任何文件")
    fm = _front_matter_of(text)
    todo = {k: v for k, v in additions.items() if not fm.get(k)}
    if not todo:
        return text, []
    block = "\n".join(f"{k}: {v}" for k, v in todo.items())
    return text[:m.end(1)] + "\n" + block + text[m.end(1):], list(todo)


def _patch_prd_front_matter(path: Path, additions: dict[str, str]) -> list[str]:
    """PRD front matter 只补缺（migrate 用）：已有键一律不动，无 front matter 不造。"""
    if not path.is_file() or not additions:
        return []
    new_text, todo = _prd_front_matter_patch(path, additions)
    if todo:
        path.write_text(new_text, encoding="utf-8")
    return todo


def migrate_manifest(root: Path, to: int = 2,
                     definition_path: str | None = None,
                     cutover: str | None = None,
                     anchor_review: str | None = None) -> dict:
    """B-0：清单 v1→v2（只补缺，不覆盖已有字段，不自动 lock）。

    `--cutover` 与 `init` 共用 `resolve_cutover`（默认 `ACCEPTANCE_CUTOVER_DEFAULT`，
    往后推需 `--anchor-review` 且不超过默认 + 90 天）。
    """
    root = Path(root).resolve()
    if to != 2:
        raise SolutionError("B-0 只支持 --to 2")
    # 写侧形态门先于任何落盘（坏值与 `init` 同形：exit 2、磁盘零变化）。
    anchor_review = validate_anchor_review(anchor_review)
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
    resolved_cutover = resolve_cutover(cutover, anchor_review)
    existing_cutover = str(data.get("acceptance_cutover") or "").strip()
    if existing_cutover and (cutover or "").strip() and existing_cutover != resolved_cutover:
        raise SolutionError(
            f"清单已有 acceptance_cutover={existing_cutover}，与 --cutover "
            f"{resolved_cutover} 不同；migrate 只补缺，不覆盖已有字段"
            "（要改切点请手改清单后重跑 lock --update）")
    if not existing_cutover:
        scalars["acceptance_cutover"] = resolved_cutover
        added.append("acceptance_cutover")
    # 切点评审号：显式给了就必须落盘（不许静默丢弃），已有不同值则拒绝覆盖。
    review = (anchor_review or "").strip() or None
    existing_review = str(data.get("acceptance_cutover_review") or "").strip()
    if existing_review and review and existing_review != review:
        raise SolutionError(
            f"清单已有 acceptance_cutover_review={existing_review}，与 --anchor-review "
            f"{review} 不同；migrate 只补缺，不覆盖已有字段"
            "（要改评审号请手改清单后重跑 lock --update）")
    if review and not existing_review:
        scalars["acceptance_cutover_review"] = review
        added.append("acceptance_cutover_review")
    if not data.get("min_atlas"):
        scalars["min_atlas"] = MIN_ATLAS_FOR_V2
        added.append("min_atlas")
    new_text = _migrated_manifest_text(
        text, definition if "definition" in added else None, scalars)
    changed = new_text != text
    # PRD front matter 同步补 prd_version / prd_schema（§5.2 第 6/10 条）：
    # 已有值一律不动；这是 migrate 的第二类「补缺」，与清单分开统计。
    # **先算两份新内容并校验（UTF-8 / front matter 形态），再一起落盘**：
    # 旧实现先 replace 清单再读 PRD，PRD 非 UTF-8 会 exit 2 而清单已被改。
    prd_text: str | None = None
    prd_added: list[str] = []
    if definition:
        prd_path = root / definition["path"]
        prd_text, prd_added = _prd_front_matter_patch(
            prd_path, {"prd_version": "1", "prd_schema": "1"})
    if changed:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(new_text, encoding="utf-8")
        tmp.replace(path)
    if prd_added and definition:
        (root / definition["path"]).write_text(prd_text, encoding="utf-8")
    return {"manifest": str(path), "from": version, "to": 2,
            "acceptance_cutover": resolved_cutover,
            "added": added + prd_added, "changed": changed or bool(prd_added)}


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


def _check_acceptance_cutover(data: dict, lock: dict | None, add) -> None:
    """清单 / 锁的 `acceptance_cutover` 一致性（RFC v18）。

    刷新标记统一为 `definition.commit != null`（不再引用 `acceptance_cutover.commit`）：
    - `commit == null`：`init` 首锁刻意不写 cutover，两侧皆空是合法 pending 态；
    - `commit != null` 后：任一侧缺失 / 两侧皆空 ⇒ `acceptance_cutover_missing` FAIL；
      两侧有值但不等 ⇒ `acceptance_cutover_mismatch` FAIL；
    - 清单 v1 缺省只给 `migration_required` WARN（v1 本就没有这个字段）。
    """
    manifest_value = data.get("acceptance_cutover")
    lock_value = (lock or {}).get("acceptance_cutover")
    if lock is None:
        if data.get("version") == 1 and not manifest_value:
            add("验收切点", "WARN",
                "migration_required: 清单 v1 未声明 acceptance_cutover；"
                "用 0.3.x 跑 migrate --to 2 时会补默认值")
        return
    locked_def = lock.get("definition")
    refreshed = isinstance(locked_def, dict) and bool(locked_def.get("commit"))
    if not refreshed:
        if data.get("version") == 1 and not manifest_value:
            add("验收切点", "WARN",
                "migration_required: 清单 v1 未声明 acceptance_cutover；"
                "用 0.3.x 跑 migrate --to 2 时会补默认值")
        elif not manifest_value and not lock_value:
            add("验收切点", "PASS",
                "pending：定义源首次刷新前（definition.commit == null），两侧皆空合法")
        return
    if manifest_value and lock_value:
        if manifest_value == lock_value:
            add("验收切点", "PASS",
                f"acceptance_cutover={manifest_value}（清单与锁一致）")
        else:
            add("验收切点", "FAIL",
                f"acceptance_cutover_mismatch: 清单 {manifest_value!r} 与锁 "
                f"{lock_value!r} 不一致；手改清单后需重跑 lock --update 并提交锁")
        return
    sides = []
    if not manifest_value:
        sides.append("清单")
    if not lock_value:
        sides.append("锁")
    if not manifest_value and not lock_value:
        detail = "清单与锁两侧均为空"
    else:
        detail = f"{'/'.join(sides)}侧缺失（清单 {manifest_value!r} / 锁 {lock_value!r}）"
    add("验收切点", "FAIL",
        f"acceptance_cutover_missing: 已首次刷新（definition.commit != null）但{detail}；"
        "补齐后重跑 lock --update 并提交锁")


# ---------------------------------------------------------------- B-0 ⓪ 层 + 纯函数
# RFC-20261111-03 §1.1.3 ⑦ / §3.2 ⓪-0、⓪-1 / §5.2 码表。这三个名字是 B-0 的完成判据
# （§6 第 3 条），也是「两处各写一套即视为未实现」的唯一探针。

LOCK_PATH = LOCK_NAME
ABSENT = "absent"
BLOB = "blob"
NON_BLOB = "non_blob"


class LockParseError(Exception):
    """当前锁解析失败 ⇒ ⓪-0 `lock_unparsable`（exit 1、短路）。"""


class LockHistoryUnparsable(Exception):
    """历史锁版本解析失败 ⇒ ⓪-1 `lock_history_unparsable`（exit 1、短路）。"""

    def __init__(self, commit: str, reason):
        self.commit = commit
        self.reason = reason
        super().__init__(f"{commit}: {reason}")


class ChainUnverifiable(Exception):
    """对象本地不可读 / git 层失败 ⇒ `chain_unverifiable`（exit 1）。"""


class PrefixError(NamedTuple):
    """`check_history_prefix` 的 `Err(code, detail)`。"""

    code: str
    detail: dict


def path_at(root: Path, commit: str, path: str = LOCK_PATH, *,
            current: bool = False) -> tuple[str, str | None]:
    """唯一路径探针（§1.1.3 ⑦ `path_at`）：三态 `absent` / `blob` / `non_blob`。

    判序固定：① `cat-file -e <commit>` 非零 ⇒ 提交对象本地不可读 ⇒ `ChainUnverifiable`
    （与路径判定**不共用 rc**）；② `cat-file -t <commit>:<path>` 非零且 stderr 含
    `does not exist` ⇒ `absent`（**唯一能被 `fetch` 映射成 `None` 的状态**）；
    ③ type 非 `blob` 或 `ls-tree` mode 为 `120000` ⇒ `non_blob`（tree / gitlink / symlink）。

    `non_blob` 一律抛：历史侧 `LockHistoryUnparsable`、当前侧 `LockParseError`——
    不得静默当「无此路径」跳过。`absent` 返回 `(ABSENT, None)`。
    """
    rc, _, _ = _git(root, "cat-file", "-e", commit)
    if rc != 0:
        raise ChainUnverifiable(f"commit object missing: {commit}")
    rc, out, err = _git(root, "cat-file", "-t", f"{commit}:{path}")
    if rc != 0:
        if "does not exist" in (err or ""):
            return ABSENT, None
        return _non_blob(commit, path, f"cat-file -t failed: {(err or '').strip()}",
                         current)
    kind = (out or "").strip()
    if kind != "blob":
        return _non_blob(commit, path, f"type={kind or '?'}", current)
    rc, tree, _ = _git(root, "ls-tree", "-z", commit, "--", path)
    mode = ""
    if rc == 0 and tree:
        mode = tree.split("\0", 1)[0].split(" ", 1)[0]
    if mode == "120000":
        return _non_blob(commit, path, "mode=120000 (symlink)", current)
    rc, text, err = _git(root, "show", f"{commit}:{path}")
    if rc != 0:
        return _non_blob(commit, path, f"show failed: {(err or '').strip()}", current)
    return BLOB, text


def _non_blob(commit: str, path: str, reason: str, current: bool):
    detail = f"non_blob {path} at {commit[:12]}: {reason}"
    if current:
        raise LockParseError(detail)
    raise LockHistoryUnparsable(commit, detail)


def _lock_history_commits(root: Path, path: str = LOCK_PATH) -> list[str]:
    """`git log -m --full-history --reverse` 的提交序列；`git log` 本身失败 ⇒ 链不可验。"""
    rc, out, err = _git(root, "log", "-m", "--full-history", "--reverse",
                        "--format=%H", "HEAD", "--", path)
    if rc != 0:
        raise ChainUnverifiable(f"git log failed: {(err or '').strip()}")
    seen: set[str] = set()
    commits: list[str] = []
    for c in out.split():
        if c not in seen:
            seen.add(c)
            commits.append(c)
    return commits


def _history_fetch(root: Path, path: str = LOCK_PATH):
    """`build_lock_versions` 的真实 `fetch`：只经 `path_at`（与 ⓪-1 同一探针）。"""

    def fetch(commit: str) -> str | None:
        state, text = path_at(root, commit, path)
        return text if state == BLOB else None

    return fetch


def iter_lock_history(root: Path, path: str = LOCK_PATH):
    """⓪-1 / `UH` 根集循环的唯一历史读取入口：逐提交走 `path_at`，`absent` 跳过。"""
    for commit in _lock_history_commits(root, path):
        state, text = path_at(root, commit, path)
        if state == ABSENT:
            continue
        yield commit, text


def _entries_of_lock_text(text: str) -> list[dict]:
    """取 `seal_anchors.exemption_start_history[]`，四边界容错（均不抛异常）。

    缺键 / `seal_anchors` 为 `null` 或非 dict / `exemption_start_history` 为 `null`
    或非 list ⇒ `[]`。
    """
    try:
        doc = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise LockHistoryUnparsable("<worktree>", f"invalid JSON: {exc}")
    if not isinstance(doc, dict):
        return []
    anchors = doc.get("seal_anchors")
    if not isinstance(anchors, dict):
        return []
    hist = anchors.get("exemption_start_history")
    if not isinstance(hist, list):
        return []
    return list(hist)


def build_lock_versions(commits: list[str], fetch, worktree: str | None,
                        head_has_path: bool) -> list[list[dict]]:
    """版本序列构造（§1.1.3 ⑦ 数组 C）：零 git 依赖，`fetch` 注入。

    - `fetch(commit)` 返回该提交的锁原文，`None` ⇒ 该提交**没有该路径**（删除提交 /
      浅边界外）⇒ 跳过、**不记 `[]`**；
    - 工作树层：仅当 `head_has_path` 且 HEAD 确有该路径、工作树原文存在且与 HEAD
      不同 ⇒ 追加最后一版；HEAD 无该路径或被 `rm` ⇒ 不追加（`versions` 保持 `[]`）；
    - `-m` 多父重复按 `%H` 去重是构造层清理，不产生判据。
    """
    versions: list[list[dict]] = []
    seen: set[str] = set()
    for commit in commits:
        if commit in seen:
            continue
        seen.add(commit)
        text = fetch(commit)
        if text is None:
            continue
        versions.append(_entries_of_lock_text(text))
    head_text = fetch(commits[-1]) if commits else None
    if (head_has_path and head_text is not None and worktree is not None
            and worktree != head_text):
        versions.append(_entries_of_lock_text(worktree))
    return versions


def check_history_prefix(versions: list[list[dict]]) -> PrefixError | None:
    """前缀单调判据（§1.1.3 ⑦，T-33）：`Ok` ⇒ `None`。

    只判**紧邻前一版本**：`versions[i-1]` 必须是 `versions[i]` 的前缀，且相邻至多
    新增一项（`[]` 是零项前缀、语义单向：`[] → [x]` 合法，`[x] → []` 判红）。
    """
    for index in range(1, len(versions)):
        prev, cur = versions[index - 1], versions[index]
        if cur[:len(prev)] != prev:
            return PrefixError("exemption_start_history_broken",
                               {"kind": "not_prefix", "index": index})
        if len(cur) - len(prev) > 1:
            return PrefixError("exemption_start_history_broken",
                               {"kind": "multiple_appended", "index": index})
    return None


def _lock_err(current: bool, message: str) -> Exception:
    return LockParseError(message) if current else \
        LockHistoryUnparsable("<history>", message)


def load_lock_strict(root: Path, text: str, *, current: bool) -> dict:
    """当前锁与历史锁共用的唯一解析器（§1.1.3，词法层也只有这一处）。

    `current=True`：`members` / `contracts` 必须齐备，元素 `.root` 过 lexical；
    失败 ⇒ `LockParseError`（⓪-0）。`current=False`：只校验「存在则类型正确」，
    失败 ⇒ `LockHistoryUnparsable`（⓪-1）。`assets_root_history` 出现时必须是
    非空 list-of-dict（`[]` 是解析失败，不是「无历史」）。
    """
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _lock_err(current, f"invalid JSON: {exc}")
    if not isinstance(doc, dict):
        raise _lock_err(current, "lock is not a JSON object")
    sv = doc.get("schema_version")
    if type(sv) is not int or isinstance(sv, bool) or sv not in (1, 2):
        raise _lock_err(current, f"schema_version={sv!r}")
    for key in ("members", "contracts"):
        if current and key not in doc:
            raise LockParseError(f"{key} missing in current lock")
        val = doc.get(key, [])
        if not isinstance(val, list) or any(not isinstance(x, dict) for x in val):
            raise _lock_err(current, f"{key} is not list-of-dict")
    if "assets_root_history" in doc:
        hist = doc["assets_root_history"]
        if not isinstance(hist, list) or not hist:
            raise _lock_err(current, "assets_root_history is not a non-empty list")
        for i, el in enumerate(hist):
            if not isinstance(el, dict):
                raise _lock_err(current, f"assets_root_history[{i}] is not an object")
            root_value = el.get("root")
            if (not isinstance(root_value, str) or not root_value
                    or root_value != root_value.strip()):
                raise _lock_err(
                    current, f"assets_root_history[{i}].root={root_value!r}")
            try:
                _LAYOUT.validate_value(Path(root), "assets_root", root_value,
                                       lexical=True)
            except Exception:  # noqa: BLE001 - LayoutError 不导出，统一按词法失败
                raise _lock_err(
                    current,
                    f"assets_root_history[{i}].root={root_value!r} rejected by lexical")
    if "layout_assets_root" in doc and not isinstance(doc["layout_assets_root"], str):
        raise _lock_err(current, "layout_assets_root is not a string")
    return doc


def _check_definition_lock(root: Path, data: dict, lock: dict | None, add,
                           allow_unverifiable: bool = False,
                           downgrades: list[dict] | None = None) -> None:
    """定义源与 `definition.commit` 的不可回退判据（RFC §1.1.6 / §5.2 第 8 条）。

    `commit == null` 只在 `init` 首锁（PRD 未入库）合法 ⇒ `definition_commit_pending`
    WARN；一旦「已首次刷新」（锁的完整历史里出现过非 null，或锁里
    `acceptance_cutover != null` 快速正向），当前再为 null ⇒ `definition_commit_unverifiable`
    FAIL，不得落 WARN。

    `definition_unbound`（RFC §5.2 第 5 条）：**锁 schema 2** 时 `definition` 缺失 /
    为 null ⇒ FAIL。前置只看锁版本，不再看清单版本——否则「把清单降成 v1 再把锁改
    成 3」就能整条跳过（清单版本门由 `_manifest_version` 独立把守）。
    """
    definition = data.get("definition")
    if not definition:
        if lock is not None and lock.get("schema_version") == LOCK_SCHEMA_VERSION:
            add("定义源", "FAIL",
                "definition_unbound: 锁 schema_version=2，但清单的 definition 缺失"
                "或为 null；用 0.3.x 跑 migrate --to 2 补齐 definition，再 lock --update")
        return
    rel = definition["path"]
    add("定义源", "PASS", f"{rel}（domain={definition.get('domain')}）")
    # 浅克隆 / partial clone：链与提交对象都不可证 ⇒ `chain_unverifiable` **hard FAIL**。
    # 这一支**不在** `--allow-unverifiable-chain` 的降级清单里（该开关只降「清单
    # `definition.commit` 指向的提交对象本地缺失」一支，见下方 `allow_unverifiable`）。
    # 封条链锚（`epoch_origin` / `previous_seal_commit` / `anchor_review`）缺对象同样
    # 一律 FAIL，不受该开关影响——缺了就是不可证，不接受自述降级。
    rc, shallow, _ = _git(root, "rev-parse", "--is-shallow-repository")
    if rc == 0 and shallow.strip().lower() == "true":
        add("定义源 commit", "FAIL",
            "chain_unverifiable: 仓库是 shallow/partial"
            "（git rev-parse --is-shallow-repository=true），完整历史不可证；"
            "CI 需 fetch-depth: 0")
        return
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
        # `--allow-unverifiable-chain` 的**唯一**降级范围：这一支（提交对象本地缺失）。
        # 不是「所有不可证都降级」——见上方 shallow 与封条链锚，那些一律 FAIL。
        status = "WARN" if allow_unverifiable else "FAIL"
        add("定义源 commit", status,
            f"definition_commit_unverifiable: 本机缺少提交 {commit[:12]}"
            "（浅克隆？CI 需 fetch-depth: 0）")
        if allow_unverifiable and downgrades is not None:
            downgrades.append({
                "code": "definition_commit_unverifiable",
                "flag": "--allow-unverifiable-chain",
                "scope": "definition_source",
                "path": rel,
                "note": f"definition_commit_unverifiable 已降级"
                        f"（--allow-unverifiable-chain）：本机缺少提交 {commit[:12]}",
            })
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


def _sort_report_arrays(errors: list[dict], warnings: list[dict], info: list[dict],
                        downgrades: list[dict]) -> None:
    """RFC §3.2 确定性排序：`(code, path)`；`downgrades[]` 用 `(code, scope, path)`。

    `null` 排最前（取空串）。`not_run[]` 不排序，按固定枚举顺序输出。
    """
    def _code_path(item: dict) -> tuple[str, str]:
        return (item.get("code") or "", item.get("path") or "")

    for arr in (errors, warnings, info):
        arr.sort(key=_code_path)
    downgrades.sort(key=lambda i: (i.get("code") or "", i.get("scope") or "",
                                   i.get("path") or ""))


# ⓪ 层短路时「后面一段都没跑」的固定六段枚举（`not_run[]` 不排序，按此顺序输出）。
NOT_RUN_SEGMENTS = ["root_history_check", "root_v1_check", "root_changed_check",
                    "path_level", "state_level", "chain_level"]


def _head_has_lock(root: Path, path: str = LOCK_PATH) -> bool:
    rc, out, _ = _git(root, "ls-tree", "-z", "HEAD", "--", path)
    return rc == 0 and bool(out.strip())


def _layer0_lock(root: Path):
    """§3.2 ⓪ 层：返回 `(lock, fatal, infos, chain_issue)`。

    - ⓪-0 **当前锁优先**：文件存在但不是普通文件（symlink / 目录）或 `load_lock_strict`
      失败 ⇒ `fatal = lock_unparsable`，**不再读历史**（短路）。
    - 文件不存在：HEAD 跟踪过或历史里有版本 ⇒ `lock_tracked_but_deleted`（INFO）；
      否则 `lock_missing`（INFO）。两种都只跳过 ⓪-0，⓪-1 仍执行。
    - ⓪-1：历史版本 `non_blob` / 字节坏 ⇒ `fatal = lock_history_unparsable`（短路）。
      `git log` 本身失败 ⇒ `chain_issue`（`chain_unverifiable` FAIL，历史按空处理）。
    - INFO 三码互斥：`lock_missing`（从未有过锁）/ `lock_tracked_but_deleted`（曾跟踪过、
      当前 HEAD 无锁）/ `lock_history_empty`（当前锁在，但没有任何已提交版本）。
    """
    path = lock_path(root)
    infos: list[dict] = []
    exists = path.exists() or path.is_symlink()
    hist_reader = _is_git(root)
    commits: list[str] = []
    chain_issue: dict | None = None
    if hist_reader:
        rc_head, _, _ = _git(root, "rev-parse", "--verify", "HEAD")
        if rc_head != 0:
            commits = []          # 空仓：没有 HEAD ⇒ 无历史，不是「历史不可读」
        else:
            try:
                commits = _lock_history_commits(root)
            except ChainUnverifiable as exc:
                chain_issue = {"code": "chain_unverifiable", "path": LOCK_NAME,
                               "message": f"chain_unverifiable: 锁历史不可读（{exc}）"
                                          "；按无历史处理，历史面判据不执行"}
    if not exists:
        if _head_has_lock(root) or commits:
            infos.append({"code": "lock_tracked_but_deleted", "path": LOCK_NAME,
                          "message": "lock_tracked_but_deleted: 锁曾被跟踪，但当前 "
                                     "HEAD 无锁文件；⓪-0 与两条根断言跳过"})
        else:
            infos.append({"code": "lock_missing", "path": LOCK_NAME,
                          "message": "lock_missing: 锁文件不存在（从未生成）；"
                                     "⓪-0 与两条根断言跳过"})
        lock = None
    else:
        if path.is_symlink() or path.is_dir():
            return None, {"code": "lock_unparsable", "path": LOCK_NAME,
                          "message": "lock_unparsable: 当前锁不是普通文件"
                                     "（symlink / 目录 / gitlink 形态）"}, infos, chain_issue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return None, {"code": "lock_unparsable", "path": LOCK_NAME,
                          "message": f"lock_unparsable: 当前锁不可读（{exc}）"}, infos, chain_issue
        try:
            lock = load_lock_strict(root, text, current=True)
        except LockParseError as exc:
            return None, {"code": "lock_unparsable", "path": LOCK_NAME,
                          "message": f"lock_unparsable: {exc}"}, infos, chain_issue
        if hist_reader and not commits:
            infos.append({"code": "lock_history_empty", "path": LOCK_NAME,
                          "message": "lock_history_empty: 当前锁没有任何已提交版本"
                                     "（未跟踪）；历史面判据跳过"})
    if hist_reader and commits:
        try:
            list(iter_lock_history(root))
        except ChainUnverifiable as exc:
            chain_issue = chain_issue or {
                "code": "chain_unverifiable", "path": LOCK_NAME,
                "message": f"chain_unverifiable: 锁历史不可读（{exc}）"}
        except LockHistoryUnparsable as exc:
            return lock, {"code": "lock_history_unparsable", "path": LOCK_NAME,
                          "message": f"lock_history_unparsable: {exc}"}, infos, chain_issue
    return lock, None, infos, chain_issue


def check_solution(root: Path, strict: bool = False,
                   allow_dangling_acs: bool = False,
                   lenient: bool = False,
                   allow_unverifiable_chain: bool = False) -> dict:
    root = Path(root).resolve()
    data = load_manifest(root)
    results: list[dict] = []
    # 带码的错误面（B-0 只登记形态类 FAIL；完整 v2 报告 schema 随 C 批）。
    errors: list[dict] = []
    warnings: list[dict] = []
    info: list[dict] = []
    downgrades: list[dict] = []
    level = "FAIL" if strict else "WARN"
    add = lambda name, status, detail: results.append(
        {"check": name, "status": status, "detail": detail})

    # §3.2 ⓪：当前锁优先，一红即短路（不读历史、后面五段全进 `not_run[]`）。
    lock, lock_fatal, lock_infos, chain_issue = _layer0_lock(root)
    info.extend(lock_infos)
    if chain_issue:
        add("锁历史", "FAIL", chain_issue["message"])
        errors.append({"code": chain_issue["code"], "message": chain_issue["message"],
                       "path": chain_issue["path"]})
    if lock_fatal:
        add("锁解析", "FAIL", lock_fatal["message"])
        errors.append({"code": lock_fatal["code"], "message": lock_fatal["message"],
                       "path": lock_fatal["path"]})
        _sort_report_arrays(errors, warnings, info, downgrades)
        return {"schema_version": 2, "solution": data["solution"],
                "mode": data["mode"], "overall": "FAIL", "checks": results,
                "errors": errors, "warnings": warnings, "info": info,
                "downgrades": downgrades, "not_run": list(NOT_RUN_SEGMENTS),
                "e2e": None}

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
                           allow_unverifiable=allow_unverifiable_chain,
                           downgrades=downgrades)
    _check_acceptance_cutover(data, lock, add)
    # 切点评审门槛（RFC v19/阻断 2，V-20⑥）：判序**先空后形态**，两码互斥。
    # 空值只对「晚于默认切点」报 `unreviewed`，绝不能落到 `malformed`；
    # 形态坏则只报 `malformed`，不再重复算「缺 review」。
    cutover = data.get("acceptance_cutover")
    review = data.get("acceptance_cutover_review")
    late = False
    if cutover:
        try:
            late = (datetime.strptime(str(cutover), "%Y-%m-%d").date()
                    > datetime.strptime(ACCEPTANCE_CUTOVER_DEFAULT, "%Y-%m-%d").date())
        except ValueError:
            late = False
    if late and not review:
        detail = (f"acceptance_cutover_unreviewed: 清单 cutover={cutover} 晚于包级默认 "
                  f"{ACCEPTANCE_CUTOVER_DEFAULT}，但没有 acceptance_cutover_review；"
                  "用 --anchor-review 重写清单或把切点改回默认")
        add("acceptance_cutover 评审号", "FAIL", detail)
        errors.append({"code": "acceptance_cutover_unreviewed",
                       "message": detail, "path": MANIFEST_NAME})
    elif review and not REVIEW_ID_RE.fullmatch(str(review)):
        detail = (f"acceptance_cutover_review_malformed: 清单 acceptance_cutover_review="
                  f"{review!r} 不符合 REVIEW-YYYYMMDD-NN（REVIEW-\\d{{8}}-\\d{{2}}）；"
                  "改清单后重跑 lock --update")
        add("acceptance_cutover 评审号", "FAIL", detail)
        errors.append({"code": "acceptance_cutover_review_malformed",
                       "message": detail, "path": MANIFEST_NAME})
    # 注入点武装检查：读者已 ≥0.4.0 但 `PRD_SCHEMA_2_FROM` 仍为 None ⇒ 该判据永不触发，
    # 必须可见（发版门另有一条「tag 日期与常量一致」）。
    reader = reader_version(root)
    if reader and not semver_lt(reader, (0, 4, 0)) and PRD_SCHEMA_2_FROM is None:
        add("PRD 证据列", "WARN",
            "prd_schema_gate_unarmed: 读者 ≥0.4.0 但 `PRD_SCHEMA_2_FROM` 未填，"
            "prd_schema_too_low 不会触发；发版时把常量填成 0.4.0 发布日期")
    # 定义源 PRD 的 prd_schema 档位与证据列（§1.5）：2 立即 FAIL，1 缓冲到 2027-06-30。
    if data.get("definition"):
        rel = data["definition"]["path"]
        prd_file = root / rel
        if prd_file.is_file():
            prd_text = prd_file.read_text(encoding="utf-8")
            too_low = prd_schema_too_low(root, rel, prd_text)
            if too_low:
                add("PRD 证据列", "FAIL", too_low)
            for status, detail in prd_schema_findings(prd_text, rel):
                add("PRD 证据列", status, detail)
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
    # RFC §3.2 报告 schema：固定顶层键；数组排序键 `(code, path)`（`null` 排最前），
    # `downgrades[]` 用 `(code, scope, path)`（冻结基线 §5.2，v40）。正常跑完 `not_run[]` 为空数组。
    _sort_report_arrays(errors, warnings, info, downgrades)
    return {"schema_version": 2, "solution": data["solution"], "mode": data["mode"],
            "overall": overall, "checks": results, "errors": errors,
            "warnings": warnings, "info": info, "downgrades": downgrades,
            "not_run": [], "e2e": e2e_audit}


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
