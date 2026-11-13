#!/usr/bin/env python3
"""atlas 校验器 —— stack-profile 合法性与适配器可解析。

按 `shared/stack-profile.md` §2/§3.3 校验 `<项目根>/<资产根>/stack-profile.yaml`
（资产根默认 `product/`，由 `atlas.config.yaml` 解析）：
字段契约、`origin` 来源形态枚举、`apps[]` 枚举与路径、`adapters` 名字能否解析到脚本。

- **框架无关**：本文件不得出现任何具体框架名。
- 纯标准库。
- 判定：`null` = OK（合法降级）；非 `null` 解析不到 = FAIL；`apps[].path` 不存在 = WARN。
  有 FAIL → 退出码 1；否则 0。

用法：
    python3 validate_stack_profile.py --root <项目根> [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# 随包内核引导（`_support/`，2026-10-12 单源批）：profile 解析口径取 `_support/stack_profile.py`
# 单源实现（此前与 gen_e2e_scripts 各持一份，B197-1 曾实际漂移一次——登记行「对齐 gen 同款」）。
if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _support.siblings import load_module  # noqa: E402
from _support.layout import LayoutError, load_layout  # noqa: E402

_sp = load_module("stack_profile")
# 保名兼容（出厂测试引用 `vsp.parse_profile` / `vsp.strip_inline_comment` / `vsp.yaml_scalar`）
parse_profile = _sp.parse_profile
strip_inline_comment = _sp.strip_inline_comment
yaml_scalar = _sp.yaml_scalar

KINDS = ("frontend", "backend", "fullstack", "mobile")
ROLES = ("landing", "legacy")
# 来源形态（`shared/stack-profile.md` §2）。缺省按 greenfield 处理 —— 保持既有行为，
# 不因未声明而静默切换形态；模板与契约里的词表必须与本元组逐项一致（出厂测试守恒）。
ORIGINS = ("greenfield", "adopt")
DEFAULT_ORIGIN = "greenfield"
# 图谱后端词表（`shared/stack-profile.md` §2 `graph` 段同源；出厂测试守恒）。
# 可选能力：段缺失 = 不用图谱（合法）；声明了就必须合法（未知键 / 未知 backend = FAIL）。
GRAPH_BACKENDS = ("cgc",)
GRAPH_KEYS = ("backend", "pinned")

# 数据播种通道词表（`shared/stack-profile.md` §2 `e2e.seed` 段同源；出厂测试守恒）。
# mode：enforce（缺省 = 现行为，每用例运行期播种）/ declare（只对账不发射，B197-1，2026-10-07）。
SEED_KEYS = ("hook", "mode")
SEED_MODES = ("declare", "enforce")
# 会话预设段（`shared/stack-profile.md` §2 / `rings/e2e/reference.md` §5.5，2026-10-16，issue #13）
SESSION_PRESET_KEYS = ("keys",)
SESSION_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-]*$")
# 网络边界打桩通道词表（`shared/stack-profile.md` §2 `e2e.mock` 段同源，rings/e2e §5.8；
# 2026-10-12）。mode：off（缺省 = 现行为：mock: 行即 FAIL，防全后端项目误用）/ on（放行）/ auto（混合穿透）。
MOCK_KEYS = ("mode", "api_prefix", "fixtures_dir")
MOCK_MODES = ("off", "on", "auto")
# 登录形态与取证值（rings/e2e §5.8 / §7.1，2026-10-12；2026-10-16 增 none，RFC-20261015-02：
# 与 e2e.mock.mode off / e2e.review.mode off 同构——在 X 段里用 mode 值声明「靶场没有 X」）。
# mode：real（缺省 = 真实登录语义）/ fabricated（纯前端桩：setup 不发请求直写假令牌，必填收窄
# 为 storage_key）/ none（靶场无访问门——声明形态，非降级；段内取证字段一律不得残留）。
APP_LOGIN_KEYS = ("mode", "endpoint", "username_field", "password_field", "token_key", "storage_key", "body_format", "probe")
APP_LOGIN_FIELDS = ("endpoint", "username_field", "password_field", "token_key", "storage_key", "body_format")
APP_LOGIN_MODES = ("real", "fabricated", "none")
APP_LOGIN_BODY_FORMATS = ("form", "json")
# 字段矩阵（RFC-20261112-01 §8.3）：fabricated 只允许 mode + storage_key；none 全弃。
APP_LOGIN_FABRICATED_FORBIDDEN = ("endpoint", "username_field", "password_field", "token_key", "body_format", "probe")
# probe 契约（RFC §4.2 / rings/e2e/reference.md §7.1）：real 下必填；不可选。
PROBE_KEYS = ("path", "method", "expect_status", "expect_content_type", "expect_json", "timeout_ms")
PROBE_METHODS = ("GET", "POST")
PROBE_TIMEOUT_MAX_MS = 10000
# 运行器视口与配色（shared/stack-profile.md §2 / rings/e2e/reference.md §5.4，2026-11-11）：
# 可选段键；缺省 = 不写 playwright.config.ts 的 use，保持运行器原生默认。
VIEWPORT_RE = re.compile(r"^(\d+)\s*[xX]\s*(\d+)$")
COLOR_SCHEMES = ("light", "dark", "no-preference")

# 独立审查调度通道词表（shared/stack-profile.md §2，rings/e2e §12.6；v0.1.0-beta.14）
# mode: gate（缺省 = 严格独立审查门）/ auto-baseline（无报告时自动兜底生成基线，免阻断）/ off（免审）
REVIEW_KEYS = ("mode", "model")
REVIEW_MODES = ("gate", "auto-baseline", "off")

# 后端测试调度段白名单（shared/stack-profile.md §2；B209-1 / 3507 BT，2026-10-12）。
# 可选能力：段缺失 = 降级（由项目自行执行）；声明了就必须合法。
BACKEND_TEST_KEYS = ("command", "test_dir", "framework", "extractor",
                     "extractor_command", "mode", "ac_marker")
BACKEND_TEST_MODES = ("enforce", "advisory")


class Result:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(self, check: str, level: str, detail: str = "") -> None:
        self.checks.append({"check": check, "level": level, "detail": detail})

    @property
    def status(self) -> str:
        levels = {c["level"] for c in self.checks}
        if "FAIL" in levels:
            return "FAIL"
        return "WARN" if "WARN" in levels else "PASS"


# `strip_inline_comment` / `yaml_scalar` / `parse_profile` 的单源实现在
# `_support/stack_profile.py`（2026-10-12 单源批）；本文件顶部经 `_support.siblings`
# 加载并保名（出厂测试引用 `vsp.parse_profile` 等）。判定面（白名单 / 枚举）仍在本文件自持。


def resolvable(root: Path, name: str) -> bool:
    cands = [root / ".atlas" / "adapters" / name, root / ".atlas" / "adapters" / f"{name}.py", root / name]
    for c in cands:
        if c.is_file():
            if c.suffix == ".py" or os.access(c, os.X_OK):
                return True
    return False


def _as_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
        return int(value.strip())
    return None


def probe_errors(probe) -> list[str]:
    """probe 契约（RFC-20261112-01 §4.2）：real 必填；缺失 / 形态非法 ⇒ FAIL。"""
    if not isinstance(probe, dict):
        return ["probe 必须是映射（path / method / expect_status / expect_content_type / expect_json / timeout_ms）"]
    errors: list[str] = []
    unknown = [k for k in probe if k not in PROBE_KEYS]
    if unknown:
        errors.append(f"未知键={unknown} 允许={list(PROBE_KEYS)}")
    path = probe.get("path")
    if not isinstance(path, str) or not path.strip().startswith("/"):
        errors.append(f"path 必填且以 / 开头，得 {path!r}")
    method = str(probe.get("method") or "GET").upper()
    if method not in PROBE_METHODS:
        errors.append(f"method 非法={probe.get('method')!r} 允许={list(PROBE_METHODS)}")
    status = _as_int(probe.get("expect_status", 200))
    if status is None or not (100 <= status <= 599):
        errors.append(f"expect_status 应为 100..599 的整数，得 {probe.get('expect_status')!r}")
    ctype = probe.get("expect_content_type", "application/json")
    if not isinstance(ctype, str) or not ctype.strip():
        errors.append("expect_content_type 应为非空字符串")
    expect_json = probe.get("expect_json")
    if expect_json is not None:
        if not isinstance(expect_json, dict):
            errors.append("expect_json 应为 `JSON Pointer → 期望值` 映射")
        else:
            bad = [k for k in expect_json if not str(k).startswith("/")]
            if bad:
                errors.append(f"expect_json 的键应为 JSON Pointer（以 / 开头），非法={bad}")
    timeout_ms = _as_int(probe.get("timeout_ms", 3000))
    if timeout_ms is None or not (1 <= timeout_ms <= PROBE_TIMEOUT_MAX_MS):
        errors.append(f"timeout_ms 应为 1..{PROBE_TIMEOUT_MAX_MS} 的整数，得 {probe.get('timeout_ms')!r}")
    return errors


def validate(root: Path) -> Result:
    res = Result()
    try:
        lay = load_layout(root)
    except LayoutError as exc:
        res.add("项目布局配置", "FAIL", str(exc))
        return res
    p = lay.stack_profile
    if not p.is_file():
        res.add("stack-profile 存在", "FAIL", lay.print_value("stack_profile"))
        return res
    prof = parse_profile(p.read_text(encoding="utf-8"))

    res.add("product 非空", "PASS" if prof.get("product") else "FAIL", repr(prof.get("product")))

    origin = prof.get("origin")
    if origin is None:
        res.add("origin 枚举", "WARN",
                f"未声明，按默认 {DEFAULT_ORIGIN} 处理（保持既有行为）；允许={list(ORIGINS)}")
    else:
        res.add("origin 枚举", "PASS" if origin in ORIGINS else "FAIL",
                f"值={origin} 允许={list(ORIGINS)}")
    eff_origin = origin if origin in ORIGINS else DEFAULT_ORIGIN

    apps = prof.get("apps") or []
    missing = [a.get("name") for a in apps if not all(a.get(f) for f in ("name", "path", "kind", "role"))]
    bad_kind = [a.get("name") for a in apps if a.get("kind") not in KINDS]
    bad_role = [a.get("name") for a in apps if a.get("role") not in ROLES]
    res.add("apps[] 必填字段", "PASS" if apps and not missing else "FAIL",
            f"count={len(apps)} 缺字段={missing}")
    res.add("apps[].kind 枚举", "PASS" if not bad_kind else "FAIL", f"非法={bad_kind} 允许={KINDS}")
    res.add("apps[].role 枚举", "PASS" if not bad_role else "FAIL", f"非法={bad_role} 允许={ROLES}")

    absent = [a.get("path") for a in apps if a.get("path") and not (root / a["path"]).exists()]
    res.add("apps[].path 存在", "WARN" if absent else "PASS", f"不存在={absent}")

    adapters = prof.get("adapters") or {}
    null_keys, unresolved = [], []
    for key, val in adapters.items():
        if val is None:
            null_keys.append(key)
        elif not resolvable(root, val):
            unresolved.append(f"{key}={val}")
    res.add("adapters 非 null 可解析", "PASS" if not unresolved else "FAIL",
            f"未解析={unresolved}；null（合法降级）={null_keys}")

    graph = prof.get("graph")
    if isinstance(graph, dict) and graph:
        unknown = [k for k in graph if k not in GRAPH_KEYS]
        res.add("graph 段键白名单", "PASS" if not unknown else "FAIL",
                f"未知键={unknown} 允许={list(GRAPH_KEYS)}")
        res.add("graph.backend 枚举", "PASS" if graph.get("backend") in GRAPH_BACKENDS else "FAIL",
                f"值={graph.get('backend')} 允许={list(GRAPH_BACKENDS)}")
        pinned = graph.get("pinned")
        ok_pin = pinned is None or bool(re.fullmatch(r"\d+\.\d+\.\d+\S*", str(pinned)))
        res.add("graph.pinned 形态", "PASS" if ok_pin else "FAIL", f"值={pinned}（语义版本形态）")
    elif graph is not None and not isinstance(graph, dict):
        res.add("graph 段形态", "FAIL", f"值={graph!r}（应为映射或 null）")
    else:
        res.add("graph 段（可选能力）", "PASS",
                "未声明 = 不用图谱（合法）；声明契约见 shared/stack-profile.md §2")

    e2e_prof = prof.get("e2e") or {}
    if isinstance(e2e_prof, dict):
        runner = e2e_prof.get("runner")
        # B201-4 单轨化（3507 BO，2026-10-09）：python-playwright 已退役。
        # 唯一合法值 = node-playwright；缺省 = node-playwright（未声明 = 合法）；
        # 显式 python-playwright / 其它值 ⇒ FAIL（响亮拒绝，不静默改行为——同 B197-1 缺省判据）。
        res.add("e2e.runner 枚举（单轨）",
                "PASS" if (runner is None or runner == "node-playwright") else "FAIL",
                f"值={runner!r} 允许=['node-playwright']（缺省同值；python-playwright 已退役，B201-4/3507 BO）")
        # 视口与配色（2026-11-11）：可选；缺省保持运行器原生默认，声明了就必须合法。
        viewport = e2e_prof.get("viewport")
        if viewport is None:
            res.add("e2e.viewport 形态", "PASS", "未声明 = 不写 use.viewport（运行器默认）")
        else:
            m_vp = VIEWPORT_RE.fullmatch(str(viewport).strip())
            ok_vp = bool(m_vp) and int(m_vp.group(1)) > 0 and int(m_vp.group(2)) > 0
            res.add("e2e.viewport 形态",
                    "PASS" if ok_vp else "FAIL",
                    f"值={viewport!r}（应形如 1440x900，宽高为正整数；缺省不写该键）")
        color_scheme = e2e_prof.get("color_scheme")
        res.add("e2e.color_scheme 枚举",
                "PASS" if (color_scheme is None or color_scheme in COLOR_SCHEMES) else "FAIL",
                f"值={color_scheme!r} 允许={list(COLOR_SCHEMES)}（缺省不写该键）")
    seed = e2e_prof.get("seed") if isinstance(e2e_prof, dict) else None
    if isinstance(seed, dict) and seed:
        unknown = [k for k in seed if k not in SEED_KEYS]
        res.add("e2e.seed 键白名单", "PASS" if not unknown else "FAIL",
                f"未知键={unknown} 允许={list(SEED_KEYS)}")
        mode = seed.get("mode")
        res.add("e2e.seed.mode 枚举", "PASS" if mode is None or mode in SEED_MODES else "FAIL",
                f"值={mode!r} 允许={list(SEED_MODES)}（缺省 enforce = 每用例运行期播种；B197-1）")
    elif seed:
        # 非映射真值（字符串等）= 形态非法；空 dict（`seed:` / `seed: null` 同形）不算——
        # YAML 里两者都是 null = 显式不用 = 与未声明同判（合法降级）。
        res.add("e2e.seed 段形态", "FAIL", f"值={seed!r}（应为映射或 null）")
    else:
        res.add("e2e.seed（可选段）", "PASS",
                "未声明 = 合法降级（mode 缺省 enforce；hook 未声明 ⇒ 生成期 WARN + 运行期警告）")

    # 契约 `rings/e2e/reference.md` §5.5 / `shared/stack-profile.md` §2（2026-10-16，issue #13）：
    # **会话预设键白名单**。段缺失 / 空 = 该靶场不允许任何会话预设（用例出现 `会话:` 行 ⇒
    # 文本期 FAIL + 生成器中止双保险）。白名单是**项目级声明**，它把「哪些宿主注入键可预设」
    # 收在项目侧，防把「数据态」走私成会话参数（§5.7 的禁令不破）。
    session_preset = e2e_prof.get("session_preset") if isinstance(e2e_prof, dict) else None
    if isinstance(session_preset, dict) and session_preset:
        unknown_keys = [k for k in session_preset if k not in SESSION_PRESET_KEYS]
        res.add("e2e.session_preset 键白名单", "PASS" if not unknown_keys else "FAIL",
                f"未知键={unknown_keys} 允许={list(SESSION_PRESET_KEYS)}")
        keys = session_preset.get("keys")
        if not isinstance(keys, list) or not keys:
            res.add("e2e.session_preset.keys 形态", "FAIL",
                    f"值={keys!r}（应为非空列表；空 / 缺失 = 不允许任何会话预设，与整段不声明同义）")
        else:
            bad_keys = [str(k) for k in keys if not SESSION_KEY_RE.match(str(k))]
            res.add("e2e.session_preset.keys 形态", "PASS" if not bad_keys else "FAIL",
                    f"非法键={bad_keys}（须匹配 ^[A-Za-z][A-Za-z0-9_.\\-]*$）")
    elif session_preset:
        res.add("e2e.session_preset 段形态", "FAIL", f"值={session_preset!r}（应为映射或 null）")
    else:
        res.add("e2e.session_preset（可选段）", "PASS",
                "未声明 = 不允许任何会话预设（用例出现 `会话:` 行 ⇒ 校验器 FAIL + 生成器中止）")

    # 契约 rings/e2e/reference.md §5.4/§5.5（多靶场，beta.16）：具名靶场登记表
    # `e2e.targets`（可选；闭集）。名字进生成测试名（`__<名>` 后缀）⇒ `[a-z0-9-]+`；
    # 路由形态同页面表 `路由` 列（`/` 开头）。未声明 = 单靶场（现行为，逐字节不变）。
    targets = e2e_prof.get("targets") if isinstance(e2e_prof, dict) else None
    if isinstance(targets, dict) and targets:
        bad_targets: list[str] = []
        for t_name, t_route in targets.items():
            if not re.fullmatch(r"[a-z0-9-]+", str(t_name)):
                bad_targets.append(f"{t_name}:名字应为[a-z0-9-]+")
            if not str(t_route or "").strip().startswith("/"):
                bad_targets.append(f"{t_name}:路由应以/开头")
        res.add("e2e.targets 形态", "PASS" if not bad_targets else "FAIL",
                f"非法条目={bad_targets[:8]}（名字 [a-z0-9-]+；路由以 / 开头）" if bad_targets
                else f"{len(targets)} 个具名靶场已登记")
    elif targets is not None:
        res.add("e2e.targets 段形态", "FAIL", f"值={targets!r}（应为 `名: 路由` 映射或 null）")
    else:
        res.add("e2e.targets（可选段）", "PASS",
                "未声明 = 单靶场（用例出现 `靶场:` 行 ⇒ 校验器 FAIL + 生成器中止）")

    app_login = e2e_prof.get("app_login") if isinstance(e2e_prof, dict) else None
    if isinstance(app_login, dict) and app_login:
        unknown_keys = [k for k in app_login if k not in APP_LOGIN_KEYS]
        # 字段矩阵（RFC-20261112-01 §8.3）：矩阵外字段一律 FAIL，含 `storage_state`
        # （state 路径固定为 .atlas-auth/state.json，不接受 profile 覆盖）。
        res.add("e2e.app_login 字段矩阵", "PASS" if not unknown_keys else "FAIL",
                (f"矩阵外字段={unknown_keys} 允许={list(APP_LOGIN_KEYS)}"
                 if unknown_keys else f"字段均在矩阵内（{list(APP_LOGIN_KEYS)}）"))
        m = app_login.get("mode")
        res.add("e2e.app_login.mode 枚举", "PASS" if m is None or m in APP_LOGIN_MODES else "FAIL",
                f"值={m!r} 允许={list(APP_LOGIN_MODES)}（缺省 real；fabricated = 纯前端桩项目直写假令牌；"
                "none = 靶场无访问门的显式声明——rings/e2e §5.8/§7.1，RFC-20261015-02）")
        if m == "none":
            # none ⇒ 取证与形态字段一律不得残留（含 storage_key、body_format 与 probe）。
            # 与 fabricated 的「收窄」相反是「全弃」，两条判据同构成镜像（RFC-20261015-02）。
            leftover = [k for k in (APP_LOGIN_FIELDS + ("probe",))
                        if app_login.get(k) not in (None, "", {})]
            res.add("e2e.app_login.mode=none 字段互斥", "PASS" if not leftover else "FAIL",
                    (f"残留={leftover}（无门 ⇒ 全弃 —— fabricated 是收窄，none 是全弃）"
                     if leftover else "无取证值残留（none = 全弃，正确形态）"))
        elif m == "fabricated":
            forbidden = [k for k in APP_LOGIN_FABRICATED_FORBIDDEN
                         if app_login.get(k) not in (None, "", {})]
            res.add("e2e.app_login.mode=fabricated 字段互斥", "PASS" if not forbidden else "FAIL",
                    (f"禁写字段残留={forbidden}（fabricated 只允许 mode + storage_key；probe 不可能通过认证探针）"
                     if forbidden else "只含 mode + storage_key（正确形态）"))
            res.add("e2e.app_login.mode=fabricated 必填", "PASS"
                    if str(app_login.get("storage_key") or "").strip() else "FAIL",
                    f"storage_key={app_login.get('storage_key')!r}（必填）")
        else:
            probe = app_login.get("probe")
            if probe is None:
                res.add("e2e.app_login.probe 必填", "FAIL",
                        "mode=real 必须声明 probe（端点 / 方法 / 期望状态码与类型 / JSON 字段 / 超时）；"
                        "缺失 = 无法判定会话可用性，执行必须拒绝（RFC-20261112-01 §4.2）")
            else:
                errs = probe_errors(probe)
                res.add("e2e.app_login.probe 形态", "PASS" if not errs else "FAIL",
                        ("probe 合法（" + "；".join(errs) + "）" if not errs else "；".join(errs)))
        bf = app_login.get("body_format")
        res.add("e2e.app_login.body_format 枚举", "PASS" if bf is None or bf in APP_LOGIN_BODY_FORMATS else "FAIL",
                f"值={bf!r} 允许={list(APP_LOGIN_BODY_FORMATS)}（缺省 form；json = 发送 application/json 载荷）")

    # 凭据落盘卫生（RFC-20261112-01 §9）：`.atlas-auth/` 必须被忽略；state / meta 必须 0600。
    auth_dir = lay.e2e_auth_dir
    if auth_dir.is_dir():
        gi = lay.e2e_scripts_dir / ".gitignore"
        covered = False
        try:
            covered = gi.is_file() and any(
                ln.strip().rstrip("/") == ".atlas-auth"
                for ln in gi.read_text(encoding="utf-8").splitlines()
            )
        except OSError:
            covered = False
        res.add("e2e .atlas-auth 忽略规则", "PASS" if covered else "WARN",
                (f"{gi} 已覆盖 .atlas-auth/" if covered else
                 f"{gi} 未覆盖 .atlas-auth/（运行期凭据不得入库；生成器补 .gitignore 后重跑）"))
        bad_perms = []
        for name in ("state.json", "state.meta.json"):
            f = auth_dir / name
            try:
                if f.is_file() and (f.stat().st_mode & 0o077):
                    bad_perms.append(f"{name}={oct(f.stat().st_mode & 0o777)}")
            except OSError:
                continue
        res.add("e2e 登录态文件权限", "PASS" if not bad_perms else "WARN",
                ("state / meta 均为 0600" if not bad_perms else
                 f"权限过宽={bad_perms}（应 0600；请 chmod 600 或用 atlas e2e login 重写）"))
    else:
        res.add("e2e 登录态卫生（可选）", "N/A", "无 .atlas-auth/（未产生人工会话）")

    # RFC-20261015-02（issue #11）：登录形态未声明 ⇒ WARN 指名（第一阶段；第二阶段 = 下一次
    # 真跑准备日推生成器 `not_ready`，升档记录见 shared/gates.md「E2E 真跑」行）。
    # 文案必须中性——本器判不了靶场有没有访问门，不得断言「每次都需人工登录」。
    if isinstance(e2e_prof, dict):
        base_url = e2e_prof.get("app_base_url")
        if (base_url or "").strip() and not app_login:
            res.add("e2e 登录形态未声明", "WARN",
                    "e2e.app_base_url 已声明而 e2e.app_login 未声明：有门项目将退化为人工登录且会话"
                    "短命（长走查必断）；无门项目请显式声明 app_login: {mode: none}；"
                    "**有门但三态都装不下**（图形验证码 / cookie 会话 / 响应体无令牌）⇒ 保持未声明，"
                    "按 rings/e2e §7.1「人工会话取出」生成 "
                    "`playwright codegen --save-storage=<e2e.scripts_dir>/.atlas-auth/state.json \"<e2e.app_base_url>\"` "
                    "交人登录（AI 主动给命令；描述路径非形态声明，且明示不可复现）"
                    "——升档后未声明 ⇒ 生成器 not_ready（退出码 3），见 gates「E2E 真跑」行")

    mock = e2e_prof.get("mock") if isinstance(e2e_prof, dict) else None
    if isinstance(mock, dict) and mock:
        unknown = [k for k in mock if k not in MOCK_KEYS]
        res.add("e2e.mock 键白名单", "PASS" if not unknown else "FAIL",
                f"未知键={unknown} 允许={list(MOCK_KEYS)}")
        mode = mock.get("mode")
        res.add("e2e.mock.mode 枚举", "PASS" if mode is None or mode in MOCK_MODES else "FAIL",
                f"值={mode!r} 允许={list(MOCK_MODES)}（缺省 off = 分片出现 mock: 行即 FAIL，防全后端项目误用；"
                "rings/e2e §5.8）")
        if mode in ("on", "auto"):
            prefix = mock.get("api_prefix")
            prefix_errors = _sp.normalize_mock_prefixes(prefix, mode)[1]
            detail = (f"值={prefix!r}（mode: {mode} 时必填或兜底 /；标量或列表，每项以 / 开头且无空白）")
            if prefix_errors:
                detail += "；" + "；".join(prefix_errors)
            res.add("e2e.mock.api_prefix 前置", "PASS" if not prefix_errors else "FAIL", detail)
    elif mock:
        # 非映射真值（字符串等）= 形态非法；空 dict / null 与未声明同判（显式不用 = 合法降级）。
        res.add("e2e.mock 段形态", "FAIL", f"值={mock!r}（应为映射或 null）")
    else:
        res.add("e2e.mock（可选段）", "PASS",
                "未声明 = off（分片出现 mock: 行 ⇒ FAIL，防全后端项目误用；rings/e2e §5.8）")

    review = e2e_prof.get("review") if isinstance(e2e_prof, dict) else None
    if isinstance(review, dict) and review:
        unknown_rev = [k for k in review if k not in REVIEW_KEYS]
        res.add("e2e.review 键白名单", "PASS" if not unknown_rev else "FAIL",
                f"未知键={unknown_rev} 允许={list(REVIEW_KEYS)}")
        rev_mode = review.get("mode")
        res.add("e2e.review.mode 枚举", "PASS" if rev_mode is None or rev_mode in REVIEW_MODES else "FAIL",
                f"值={rev_mode!r} 允许={list(REVIEW_MODES)}（缺省 gate）")
    elif isinstance(review, str):
        res.add("e2e.review 模式枚举", "PASS" if review in REVIEW_MODES else "FAIL",
                f"值={review!r} 允许={list(REVIEW_MODES)}")
    elif review is not None and not isinstance(review, dict):
        res.add("e2e.review 段形态", "FAIL", f"值={review!r}（应为映射、模式标量或 null）")
    else:
        res.add("e2e.review（可选段）", "PASS",
                "未声明 = null（缺省走 gate 门禁；可配置 mode: auto-baseline 开启 AI-Native 免阻断自愈）")

    res.add("prototype 段（已退役 E1）", "N/A",
            "atlas 不再消费；存量项目可保留（历史）或删除（shared/stack-profile.md §2）")
    present = bool(prof.get("e2e"))
    res.add("e2e 段存在", "PASS" if present else "WARN", "")

    # 后端测试调度段（B209-1 / 3507 BT，2026-10-12）：可选能力，段缺失 = 合法降级。
    backend_test = prof.get("backend_test")
    if isinstance(backend_test, dict) and backend_test:
        unknown_bt = [k for k in backend_test if k not in BACKEND_TEST_KEYS]
        res.add("backend_test 键白名单", "PASS" if not unknown_bt else "FAIL",
                f"未知键={unknown_bt} 允许={list(BACKEND_TEST_KEYS)}")
        bt_mode = backend_test.get("mode")
        res.add("backend_test.mode 枚举",
                "PASS" if bt_mode is None or bt_mode in BACKEND_TEST_MODES else "FAIL",
                f"值={bt_mode!r} 允许={list(BACKEND_TEST_MODES)}（缺省 advisory）")
        bt_fw = backend_test.get("framework")
        bt_ex = backend_test.get("extractor")
        if bt_fw is not None and bt_ex is not None and bt_fw != bt_ex:
            res.add("backend_test.extractor 别名",
                    "FAIL", f"framework={bt_fw!r} 与 extractor={bt_ex!r} 冲突（别名必须一致）")
        else:
            bt_name = bt_ex if bt_ex is not None else bt_fw
            if bt_name is None:
                res.add("backend_test.extractor",
                        "PASS", "未声明 = 使用提取器注册表默认值（兼容存量）")
            elif not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", str(bt_name)):
                res.add("backend_test.extractor 形态",
                        "FAIL", f"值={bt_name!r}（应为 [a-z0-9][a-z0-9_-]*；支持性由 AC 门运行时判定）")
            else:
                res.add("backend_test.extractor",
                        "PASS", f"值={bt_name!r}（支持性由 AC 门运行时判定）")
        bt_cmd = backend_test.get("extractor_command")
        if bt_cmd is not None:
            if not isinstance(bt_cmd, str) or not bt_cmd.strip():
                res.add("backend_test.extractor_command 形态",
                        "FAIL", f"值={bt_cmd!r}（应为非空 argv 字符串）")
            elif bt_fw is not None or bt_ex is not None:
                res.add("backend_test.extractor_command 互斥",
                        "FAIL", "extractor_command 与 extractor/framework 不得同时声明")
            else:
                res.add("backend_test.extractor_command",
                        "PASS", "外部 extractor argv 已声明（运行时按 argv 执行，不走 shell）")
        bt_marker = backend_test.get("ac_marker")
        if bt_marker is not None and (not isinstance(bt_marker, str) or not bt_marker.strip()):
            res.add("backend_test.ac_marker 形态",
                    "FAIL", f"值={bt_marker!r}（应为非空字符串）")
    elif backend_test is not None and not isinstance(backend_test, dict):
        res.add("backend_test 段形态", "FAIL", f"值={backend_test!r}（应为映射或 null）")
    else:
        res.add("backend_test（可选段）", "PASS",
                "未声明 = 合法降级（由项目自行执行测试；契约见 shared/stack-profile.md §2）")

    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    res = validate(root)
    if args.json:
        print(json.dumps({"ok": res.status != "FAIL", "status": res.status,
                          "root": str(root), "checks": res.checks}, ensure_ascii=False, indent=2))
    else:
        print(f"validate_stack_profile @ {root}")
        for c in res.checks:
            line = f"  [{c['level']:<4}] {c['check']}"
            if c["detail"] and c["level"] != "PASS":
                line += f" —— {c['detail']}"
            print(line)
        print(res.status)
    return 1 if res.status == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
