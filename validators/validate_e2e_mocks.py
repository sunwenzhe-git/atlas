#!/usr/bin/env python3
"""atlas 校验器 —— 网络边界打桩门（`mock:` 行 / fixtures，契约 `rings/e2e/reference.md` §5.8/§8.3）。

2026-10-12 随 §5.8 落地（对抗评审修订案，用户拍板）。判据分层（§6.0）：本门只收**文本期
可判**的形态项；「后端记得上一步」类**出界判据是语义项**，不进本门（人 / 独立审查承担）。

门清单（§8.3）：
  * **mode 开关**：分片出现 `mock:` 行而 `e2e.mock.mode` 未声明 / 非 `on` ⇒ FAIL——
    防全后端项目静默屏蔽真 API 回归（镜像 `e2e.seed.mode` 的 declare|enforce 先例，B197-1）。
  * **api_prefix 前置**：`mode: on` 而 `api_prefix` 缺失 / 不以 `/` 开头 ⇒ FAIL。
  * **行语法 + 路径锚定**：解析复用生成器 `parse_mock_line`（同一份文法，不另写第二份）；
    方法枚举 / `->` / seq / status / delay / 锚定前缀越界 ⇒ FAIL 并逐行指名。
  * **fixture 引用闭环**：引用存在（缺 = FAIL）+ 孤儿（盘上未被引用 = FAIL，防僵尸数据；
    与 validate_testids 的双向集合同构）+ 伴生 schema 无 fixture ⇒ FAIL。
  * **fixture schema 收紧**：同名伴生 `<fixture>.schema.json` 存在时 fixture ⊨ schema
    （子集：type/properties/required/enum/items）且声明 properties 的对象层必须
    `additionalProperties: false`（多余字段即 FAIL——防「后端删字段桩不知道」的静默假绿灯）。
    无伴生 schema ⇒ 不阻断（纯前端无契约源的入场形态）。
  * **mock 先于 step**：`mock:` 行出现在首条 `step` 之后 ⇒ FAIL（注册先于 goto 的时序前提）。
  * **零步基线空转**：`mode: on` 且某页分片含 `mock:` 行 ⇒ 该页 WARN（基线不挂桩、
    无后端环境下探针全 null = 恒真守卫失效的知悉项，契约 §5.8）。

- 框架无关：本文件不得出现任何具体框架名。纯标准库。
- 判定：`PASS`/`WARN` → 退出码 0；`FAIL` → 1。前置（E2E 资产未建）记 N/A。

用法：
    python3 validate_e2e_mocks.py --root <项目根> [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# 随包内核引导（`_support/`，2026-10-12 单源批）：模块加载收敛为单源实现。
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))
from _support.siblings import load_module  # noqa: E402


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


def load_generator():
    """复用生成器的 mock 文法（同一份解析，不写第二份——single-source §1）。"""
    return load_module("gen_e2e_scripts")


# ---------------------------------------------------------------- schema 收紧（子集校验）

def _type_ok(value, ty: str) -> bool:
    if ty == "object":
        return isinstance(value, dict)
    if ty == "array":
        return isinstance(value, list)
    if ty == "string":
        return isinstance(value, str)
    if ty == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if ty == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if ty == "boolean":
        return isinstance(value, bool)
    if ty == "null":
        return value is None
    return False


def schema_errors(value, schema: dict, where: str) -> list[str]:
    """fixture ⊨ schema（子集校验）。**收紧门**：声明 `properties` 的对象层必须
    `additionalProperties: false`——不收紧的 schema 自己先 FAIL（防形同虚设的 schema 门）。"""
    errs: list[str] = []
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_type_ok(value, ty) for ty in types):
            errs.append(f"{where}: 类型应为 {t}，得 {type(value).__name__}")
            return errs
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{where}: {value!r} 不在枚举 {schema['enum']} 内")
    if isinstance(value, dict):
        props = schema.get("properties")
        if props is not None:
            if schema.get("additionalProperties") is not False:
                errs.append(f"{where}: schema 声明 properties 却未 additionalProperties: false（收紧门）")
            for rk in schema.get("required", []):
                if rk not in value:
                    errs.append(f"{where}: 缺必填字段 {rk!r}")
            for k, v in value.items():
                if k in props:
                    errs.extend(schema_errors(v, props[k], f"{where}.{k}"))
                elif schema.get("additionalProperties") is False:
                    errs.append(f"{where}: 多余字段 {k!r}（additionalProperties: false）")
    if isinstance(value, list) and "items" in schema:
        for i, v in enumerate(value):
            errs.extend(schema_errors(v, schema["items"], f"{where}[{i}]"))
    return errs


# ---------------------------------------------------------------- mock 先于 step（原始块序扫描）

def mock_after_step_violations(text: str, case_block_re, list_keys: set[str]) -> list[str]:
    """按原始行序扫每个 atlas-case 块：`mock:` 行出现在 `step` 键开启之后 ⇒ 违例。

    `parse_block` 按键归集、丢失跨键行序 ⇒ 本门必须自己做一遍**行序**扫描
    （生成物把派发表注册钉在 goto 之前，但分片书写顺序失控 = 文件面可读性 + 时序前提双失）。
    """
    bad: list[str] = []
    for block in case_block_re.findall(text):
        cid, key, step_seen = "", None, False
        for raw in block.splitlines():
            s = raw.strip()
            if not s:
                continue
            if s.startswith("- ") and key:
                item = s[2:].strip()
                if key == "mock" and step_seen:
                    bad.append(f"{cid or '(未知用例)'}: mock 行在 step 之后 —— {item}")
                continue
            if ":" in s:
                k, v = s.split(":", 1)
                k, v = k.strip(), v.strip()
                if k == "id":
                    cid = v
                if k in list_keys:
                    key = k
                    if k == "step":
                        step_seen = True
                    if k == "mock" and v and step_seen:  # 行内标量形态 `mock: GET …`
                        bad.append(f"{cid or '(未知用例)'}: mock 行在 step 之后 —— {v}")
                else:
                    key = None
    return bad


# ---------------------------------------------------------------- 主校验

def validate(root: Path) -> Result:
    res = Result()
    e2e_dir = root / "product" / "e2e"
    cases_dir = e2e_dir / "cases"
    index = e2e_dir / "e2e-index.md"
    if not index.is_file() or not cases_dir.is_dir():
        res.add("mock 门前置", "N/A", "E2E 用例资产未建（缺 product/e2e/e2e-index.md 或 cases/）")
        return res

    gen = load_generator()
    prof_path = root / "product" / "stack-profile.yaml"
    e2e_cfg: dict = {}
    if prof_path.is_file():
        e2e_cfg = gen.parse_profile(prof_path.read_text(encoding="utf-8")).get("e2e") or {}

    mock_cfg = e2e_cfg.get("mock")
    if mock_cfg is None:
        mock_cfg = {}
    if mock_cfg and not isinstance(mock_cfg, dict):
        res.add("e2e.mock 段形态", "FAIL", f"值={mock_cfg!r}（应为映射；契约 §5.8 / shared/stack-profile.md §2）")
        return res
    mode = mock_cfg.get("mode") or "off"
    raw_prefix = mock_cfg.get("api_prefix")
    prefix = raw_prefix if raw_prefix is not None else ("/" if mode in ("on", "auto") else None)

    shards = gen.gather_cases(cases_dir)
    mock_pages = sorted(p for p, items in shards.items() if any(c.get("mock") for c in items))
    mock_case_ids = [c["id"] for items in shards.values() for c in items if c.get("mock")]

    # —— mode 开关门（防全后端项目误用）
    if mode not in ("off", "on", "auto"):
        res.add("e2e.mock.mode 枚举", "FAIL", f"值={mode!r} 允许=['off', 'on', 'auto']（缺省 off；契约 §5.8）")
    elif mock_case_ids and mode not in ("on", "auto"):
        res.add("mode 开关（防误用）", "FAIL",
                f"分片出现 mock: 行但 e2e.mock.mode not in ('on', 'auto')：{mock_case_ids[:8]}"
                f"{'…' if len(mock_case_ids) > 8 else ''}（共 {len(mock_case_ids)} 条；"
                "真实后端健在时写桩 = 静默屏蔽真 API 回归——纯前端桩或混合穿透项目显式声明 mode: on/auto 放行）")
    else:
        res.add("mode 开关（防误用）", "PASS",
                f"mode={mode} 放行" if mode in ("on", "auto") else "无 mock: 行（未启用打桩 = 合态）")

    # —— api_prefix 前置
    if mode in ("on", "auto"):
        ok = bool(prefix) and str(prefix).startswith("/") and " " not in str(prefix)
        msg = (f"值={prefix!r}（未配置默认兜底为 /；以 / 开头且无空白）" if raw_prefix is None
               else f"值={prefix!r}（mode: {mode} 时以 / 开头且无空白）")
        res.add("api_prefix 前置", "PASS" if ok else "FAIL", msg)

    # —— 行语法 + 锚定（复用生成器 parse_mock_line；mode off 时 prefix 未知 ⇒ 只查文法）
    anchor = str(prefix) if (mode in ("on", "auto") and prefix) else None
    grammar_bad: list[str] = []
    refs: list[str] = []
    for _page, items in shards.items():
        for c in items:
            for line in c.get("mock") or []:
                try:
                    e = gen.parse_mock_line(line, anchor)
                except ValueError as exc:
                    grammar_bad.append(f"{c['id']}: {exc}")
                    continue
                refs.extend([item["ref"] for item in e["seq"]] if e["seq"] else [e["ref"]])
    res.add("行语法 + 路径锚定", "PASS" if not grammar_bad else "FAIL",
            "；".join(grammar_bad[:6]) + (f"（共 {len(grammar_bad)} 条）" if len(grammar_bad) > 6 else ""))

    # —— fixture 引用闭环（存在 / 孤儿）
    custom_fdir = mock_cfg.get("fixtures_dir")
    if custom_fdir:
        fixtures_root = Path(custom_fdir)
        if not fixtures_root.is_absolute():
            fixtures_root = root / custom_fdir
    else:
        fixtures_root = cases_dir.parent / "fixtures"

    def _resolve_fixture(ref: str) -> Path:
        if ref.startswith("fixtures/"):
            rel = ref[len("fixtures/"):]
            p_custom = fixtures_root / rel
            if p_custom.is_file():
                return p_custom
            p_default = cases_dir.parent / ref
            if p_default.is_file():
                return p_default
            return p_custom
        return fixtures_root / ref

    missing = sorted({r for r in refs if not _resolve_fixture(r).is_file()})
    res.add("fixture 引用存在", "PASS" if not missing else "FAIL",
            f"缺={missing[:8]}（引用相对 product/e2e/，须以 fixtures/ 开头）")
    if fixtures_root.is_dir():
        on_disk = sorted("fixtures/" + p.relative_to(fixtures_root).as_posix()
                         for p in fixtures_root.glob("**/*.json"))
    else:
        on_disk = []
    fixtures_on_disk = [p for p in on_disk if not p.endswith(".schema.json")]
    orphans = [p for p in fixtures_on_disk if p not in set(refs)]
    res.add("fixture 孤儿", "PASS" if not orphans else "FAIL",
            f"未被引用={orphans[:8]}（僵尸数据；与 validate_testids 双向集合同构）")
    orphan_schemas = [p for p in on_disk
                      if p.endswith(".schema.json")
                      and p[: -len(".schema.json")] + ".json" not in set(fixtures_on_disk)]
    res.add("伴生 schema 有主", "PASS" if not orphan_schemas else "FAIL",
            f"无同位 fixture={orphan_schemas[:8]}")

    # —— fixture schema 收紧（可选伴生；存在即校验）
    schema_bad: list[str] = []
    for rel in fixtures_on_disk:
        sub = rel[len("fixtures/"):] if rel.startswith("fixtures/") else rel
        schema_path = fixtures_root / (sub[: -len(".json")] + ".schema.json")
        fixture_path = _resolve_fixture(rel)
        if not schema_path.is_file():
            continue
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 — 报出原因即可
            schema_bad.append(f"{rel}: 解析失败 {exc}")
            continue
        if not isinstance(schema, dict):
            schema_bad.append(f"{rel}: schema 须为对象")
            continue
        errs = schema_errors(fixture, schema, rel)
        if errs:
            schema_bad.extend(errs[:3])
    res.add("fixture schema 收紧", "PASS" if not schema_bad else "FAIL",
            "；".join(schema_bad[:6]) + (f"（共 {len(schema_bad)} 条）" if len(schema_bad) > 6 else "")
            or "无伴生 schema（不阻断；补 <fixture>.schema.json 即收紧）")

    # —— mock 先于 step（原始行序）
    ordering_bad: list[str] = []
    for md in sorted(cases_dir.glob("*.md")):
        ordering_bad.extend(mock_after_step_violations(
            md.read_text(encoding="utf-8"), gen.CASE_BLOCK,
            {"pages", "precondition", "seed", "mock", "step", "expected", "testid"}))
    res.add("mock 先于 step", "PASS" if not ordering_bad else "FAIL",
            "；".join(ordering_bad[:6]))

    # —— 零步基线空转 / mock 探针豁免（契约 §5.8 知悉项与 R6 豁免）
    if mode == "on" and mock_pages:
        res.add("零步基线空转", "WARN",
                f"页={mock_pages}：基线不挂桩，无后端环境下探针全 null = 恒真守卫失效"
                "（契约 §5.8 知悉项；恢复守卫强度须另立 mock-default 批）")
    elif mock_pages:
        res.add("零步基线空转", "PASS",
                f"页={mock_pages}：mock 用例断言不参与零步基线（初态由桩环境定义，契约 §5.8 R6 探针豁免）")
    else:
        res.add("零步基线空转", "PASS", "无 mock 页或未启用打桩")

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
        print(f"validate_e2e_mocks @ {root}")
        for c in res.checks:
            line = f"  [{c['level']:<4}] {c['check']}"
            if c["detail"] and c["level"] != "PASS":
                line += f" —— {c['detail']}"
            print(line)
        print(res.status)
    return 1 if res.status == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
