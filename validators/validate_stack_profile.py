#!/usr/bin/env python3
"""atlas 校验器 —— stack-profile 合法性与适配器可解析。

按 `shared/stack-profile.md` §2/§3.3 校验 `<项目根>/product/stack-profile.yaml`：
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


def strip_inline_comment(line: str) -> str:
    """去掉行内 YAML 注释：`#` 前有空白（或行首）且在引号外时截断。

    手写解析器（纯标准库）需要自己处理 YAML 合法的行内注释，
    否则 `routes: null  # 说明` 会被当成值 `null  # 说明`。
    """
    out, quote = [], None
    for i, ch in enumerate(line):
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
            out.append(ch)
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def yaml_scalar(raw: str):
    """把 YAML 标量转成 Python 值：空 / null 家族 → None，带引号则去引号。

    手写解析器需要自己识别 YAML 的 null 字面量，否则 `routes: null`
    会被当成字符串 `"null"` 而误判为「非 null 但解析不到」。
    """
    v = raw.strip()
    if len(v) >= 2 and v[0] in "'\"" and v[-1] == v[0]:
        return v[1:-1]
    if v in ("", "null", "Null", "NULL", "~", "none", "None"):
        return None
    return v


def parse_profile(text: str) -> dict:
    data: dict = {"product": None, "origin": None, "apps": [], "adapters": {},
                  "prototype": {}, "e2e": {}, "graph": None}
    section = None
    cur = None
    for raw in text.splitlines():
        line = strip_inline_comment(raw.rstrip())
        s = line.strip()
        if not s:
            continue
        if not line[:1].isspace():
            # 非缩进行 = 顶层：`key:` 开一个段；`key: value` 是标量并**结束**当前段。
            # 「结束当前段」是必须的：否则段头之后的顶层标量（`origin:`、`prototype: null`）
            # 会被当成上一段的子键吞掉（旧实现只在 section is None 时读标量）。
            if s.endswith(":"):
                section = s[:-1].strip()
                if section == "graph":
                    data["graph"] = {}
                cur = None
                continue
            if ":" in line:
                k, v = line.split(":", 1)
                data[k.strip()] = yaml_scalar(v)
                section = None
                cur = None
            continue
        if section == "apps":
            m = re.match(r"^\s*-\s*name:\s*(.+?)\s*$", line)
            if m:
                cur = {"name": yaml_scalar(m.group(1))}
                data["apps"].append(cur)
                continue
            m = re.match(r"^\s+(path|kind|role|stack):\s*(.*?)\s*$", line)
            if m and cur is not None:
                cur[m.group(1)] = yaml_scalar(m.group(2))
        elif section in ("adapters", "prototype", "e2e") or (section == "graph" and isinstance(data["graph"], dict)):
            m = re.match(r"^\s+([\w.-]+):\s*(.*?)\s*$", line)
            if m:
                if section == "graph":
                    data["graph"][m.group(1)] = yaml_scalar(m.group(2))
                    continue
                indent = len(line) - len(line.lstrip())
                key, v = m.group(1), yaml_scalar(m.group(2))
                # e2e 子段（2026-10-07 对齐 gen_e2e_scripts.parse_profile 的子块机制）：
                # `app_login:` / `seed:` 等缩进2且值为空的键开子块，更深缩进键归子 dict——
                # 旧实现全扁平化，`seed.mode` 会被误读成 e2e 顶层键（与子段键空间冲突）。
                if section == "e2e" and key in ("app_login", "seed") and indent == 2 and v is None:
                    data[section].setdefault(key, {})
                    cur = key
                    continue
                if cur is not None and indent > 2:
                    data[section][cur][key] = v
                    continue
                cur = None
                data[section][key] = v
    return data


def resolvable(root: Path, name: str) -> bool:
    cands = [root / ".atlas" / "adapters" / name, root / ".atlas" / "adapters" / f"{name}.py", root / name]
    for c in cands:
        if c.is_file():
            if c.suffix == ".py" or os.access(c, os.X_OK):
                return True
    return False


def validate(root: Path) -> Result:
    res = Result()
    p = root / "product" / "stack-profile.yaml"
    if not p.is_file():
        res.add("stack-profile 存在", "FAIL", str(p))
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

    res.add("prototype 段（已退役 E1）", "N/A",
            "atlas 不再消费；存量项目可保留（历史）或删除（shared/stack-profile.md §2）")
    present = bool(prof.get("e2e"))
    res.add("e2e 段存在", "PASS" if present else "WARN", "")
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
