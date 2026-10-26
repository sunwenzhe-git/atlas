#!/usr/bin/env python3
"""atlas 共享内核 —— 项目级资产根布局解析（RFC-20261026-01）。

守一件事：项目级资产根（默认 `product/`）与 ADR 根（默认 `<assets_root>/adr`）
由项目根 `atlas.config.yaml` 单一声明；所有消费者经本模块解析，禁止各自写死。

- 文件缺失 ⇒ 默认布局（存量项目零变化）。
- 文件存在 ⇒ 严格校验：`version: 1`、只允许 `layout.assets_root` / `layout.adr`、
  重复键 / 未知键 / 非字符串 / 路径逃逸 / symlink 逃逸 ⇒ `LayoutError`（响亮，不回落）。
- 路径统一项目根相对 POSIX；对外返回绝对 `Path`。
- 纯标准库；YAML 子集复用 `_support/stack_profile.py` 的 `strip_inline_comment` /
  `yaml_scalar`，不新造第二套方言。

CLI：
  python3 _support/layout.py --root <项目根> --print <assets_root|adr|prd|...>
  python3 _support/layout.py --root <项目根> --print-abs <key>
  python3 _support/layout.py --root <项目根> --validate
  python3 _support/layout.py --root <项目根> --validate-value <assets_root|adr> <值>
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path

CONFIG_NAME = "atlas.config.yaml"
DEFAULT_ASSETS_ROOT = Path("product")
_ALLOWED_TOP = frozenset({"version", "layout"})
_ALLOWED_LAYOUT = frozenset({"assets_root", "adr"})
_FORBIDDEN_FIRST_PARTS = frozenset({".atlas", ".trellis"})


class LayoutError(ValueError):
    """布局配置非法（缺失字段 / 未知键 / 路径逃逸 / 文件与目录形态不符）。"""


def _load_stack_profile():
    """按文件路径加载兄弟模块，兼容源包态、装配态与 load_module 独立加载。"""
    key = "_atlas_layout_stack_profile"
    if key in sys.modules:
        return sys.modules[key]
    path = Path(__file__).with_name("stack_profile.py")
    spec = importlib.util.spec_from_file_location(key, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


_SP = _load_stack_profile()
strip_inline_comment = _SP.strip_inline_comment
yaml_scalar = _SP.yaml_scalar
parse_profile = _SP.parse_profile


@dataclass(frozen=True)
class Layout:
    root: Path
    assets_root: Path
    adr_dir: Path

    def _rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    @property
    def stack_profile(self) -> Path:
        return self.assets_root / "stack-profile.yaml"

    @property
    def design(self) -> Path:
        return self.assets_root / "design.md"

    @property
    def prd_dir(self) -> Path:
        return self.assets_root / "prd"

    @property
    def prd_readme(self) -> Path:
        return self.prd_dir / "README.md"

    @property
    def prd_global(self) -> Path:
        return self.prd_dir / "prd.md"

    @property
    def e2e_dir(self) -> Path:
        return self.assets_root / "e2e"

    @property
    def e2e_index(self) -> Path:
        return self.e2e_dir / "e2e-index.md"

    @property
    def e2e_manual(self) -> Path:
        return self.e2e_dir / "manual.md"

    @property
    def e2e_cases_dir(self) -> Path:
        return self.e2e_dir / "cases"

    @property
    def e2e_scripts_dir(self) -> Path:
        return self.e2e_dir / "scripts"

    @property
    def e2e_fixtures_dir(self) -> Path:
        return self.e2e_dir / "fixtures"

    @property
    def e2e_reviews_dir(self) -> Path:
        return self.e2e_dir / "reviews"

    @property
    def e2e_run_dir(self) -> Path:
        return self.e2e_scripts_dir / ".atlas-run"

    @property
    def e2e_auth_dir(self) -> Path:
        return self.e2e_scripts_dir / ".atlas-auth"

    @property
    def console_dir(self) -> Path:
        return self.e2e_reviews_dir / "console"

    @property
    def console_ledger(self) -> Path:
        return self.console_dir / "events.jsonl"

    @property
    def reviews_dir(self) -> Path:
        return self.assets_root / "reviews"

    @property
    def reports_dir(self) -> Path:
        return self.assets_root / "atlas-reports"

    def path_for(self, key: str) -> Path:
        mapping = {
            "assets_root": self.assets_root,
            "adr": self.adr_dir,
            "prd": self.prd_dir,
            "e2e": self.e2e_dir,
            "design": self.design,
            "stack_profile": self.stack_profile,
            "reviews": self.reviews_dir,
            "reports": self.reports_dir,
            "e2e_index": self.e2e_index,
            "e2e_manual": self.e2e_manual,
            "e2e_cases": self.e2e_cases_dir,
            "e2e_scripts": self.e2e_scripts_dir,
            "e2e_fixtures": self.e2e_fixtures_dir,
            "e2e_reviews": self.e2e_reviews_dir,
            "console_ledger": self.console_ledger,
        }
        if key not in mapping:
            allowed = ", ".join(sorted(mapping))
            raise LayoutError(f"未知输出键 {key!r}（允许：{allowed}）")
        return mapping[key]

    def print_value(self, key: str) -> str:
        return self._rel(self.path_for(key))

    def warnings(self) -> list[dict[str, str]]:
        """配置与现场不一致的提示（首版 WARN，不阻断）。"""
        out: list[dict[str, str]] = []
        default_root = self.root / DEFAULT_ASSETS_ROOT
        if self.assets_root != default_root and (default_root / "stack-profile.yaml").is_file():
            out.append({
                "code": "double_root",
                "detail": (
                    f"默认 {DEFAULT_ASSETS_ROOT.as_posix()}/stack-profile.yaml 与配置根 "
                    f"{self._rel(self.assets_root)} 同时存在资产；确认是否双根，"
                    "改根需手工迁移，不自动搬移"),
            })
        default_adr = self.assets_root / "adr"
        if self.adr_dir != default_adr and default_adr.is_dir():
            out.append({
                "code": "adr_double_root",
                "detail": (
                    f"{self._rel(default_adr)}/ 与配置 ADR 根 {self._rel(self.adr_dir)} "
                    "同时存在；确认是否 ADR 双根"),
            })
        if (self.assets_root != default_root and not self.assets_root.is_dir()
                and default_root.is_dir()):
            out.append({
                "code": "configured_root_missing",
                "detail": (
                    f"配置资产根 {self._rel(self.assets_root)} 不存在，但默认 "
                    f"{DEFAULT_ASSETS_ROOT.as_posix()}/ 有资产；疑似配置错误"),
            })
        if (self.assets_root != default_root and self.e2e_dir.is_dir()
                and self.stack_profile.is_file()):
            try:
                prof = parse_profile(self.stack_profile.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                return out
            e2e = prof.get("e2e") or {}
            keys = ("cases_dir", "index", "scripts_dir")
            values = [e2e.get(k) for k in keys]
            if all(isinstance(v, str) and (v == "product" or v.startswith("product/"))
                   for v in values):
                out.append({
                    "code": "profile_path_drift",
                    "detail": (
                        f"{self._rel(self.stack_profile)} 的 e2e 三路径仍指向 product/，"
                        f"但配置资产根为 {self._rel(self.assets_root)}；疑似模板未渲染 / 路径漂移"),
                })
        return out


def _parse_config(text: str) -> dict:
    top: dict[str, object] = {}
    layout: dict[str, str] = {}
    seen_top: set[str] = set()
    seen_layout: set[str] = set()
    section: str | None = None
    saw_layout = False
    saw_version = False

    for raw in text.splitlines():
        line = strip_inline_comment(raw.rstrip())
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        if "\t" in line[:indent]:
            raise LayoutError(f"缩进不得使用 Tab：{raw!r}")
        s = line.strip()
        if indent == 0:
            section = None
            key, sep, value = s.partition(":")
            if not sep:
                raise LayoutError(f"无法解析行（缺冒号）：{raw!r}")
            key = key.strip()
            if key in seen_top:
                raise LayoutError(f"重复顶层键：{key}")
            seen_top.add(key)
            if key not in _ALLOWED_TOP:
                raise LayoutError(f"未知顶层键：{key}（只允许 version / layout）")
            if key == "version":
                if value.strip():
                    version = yaml_scalar(value)
                    if str(version) != "1":
                        raise LayoutError(f"version 只支持 1，收到 {version!r}")
                    top["version"] = 1
                    saw_version = True
                else:
                    raise LayoutError("version 必须是标量 1")
                continue
            if value.strip():
                raise LayoutError("layout 必须是块（`layout:` 后换行）")
            section = "layout"
            saw_layout = True
            continue

        if section != "layout":
            raise LayoutError(f"缩进行不在 layout 段下：{raw!r}")
        key, sep, value = s.partition(":")
        if not sep:
            raise LayoutError(f"无法解析行（缺冒号）：{raw!r}")
        key = key.strip()
        if key in seen_layout:
            raise LayoutError(f"重复 layout 键：{key}")
        seen_layout.add(key)
        if key not in _ALLOWED_LAYOUT:
            raise LayoutError(f"未知 layout 键：{key}（只允许 assets_root / adr）")
        val = yaml_scalar(value)
        if not isinstance(val, str) or not val.strip():
            raise LayoutError(f"layout.{key} 必须是非空字符串")
        layout[key] = val.strip()

    if not saw_version:
        raise LayoutError("缺少 version: 1")
    if not saw_layout:
        raise LayoutError("缺少 layout: 段")
    if "assets_root" not in layout:
        raise LayoutError("缺少 layout.assets_root")
    return {"version": top.get("version"), "layout": layout}


def _validate_rel_path(root: Path, key: str, value: str) -> Path:
    raw = value.strip()
    if not raw:
        raise LayoutError(f"layout.{key} 不能为空")
    if "\\" in raw:
        raise LayoutError(f"layout.{key} 使用 POSIX '/' 分隔符，收到 {raw!r}")
    if any(ch in raw for ch in ('"', "'", "#", "\n", "\r")):
        raise LayoutError(f"layout.{key} 不得包含引号 / '#' / 换行：{raw!r}")
    if re.match(r"^[A-Za-z]:", raw) or raw.startswith("/"):
        raise LayoutError(f"layout.{key} 必须是项目相对路径，不能是绝对路径：{raw!r}")
    parts = raw.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise LayoutError(f"layout.{key} 不得包含空段、'.' 或 '..'：{raw!r}")
    if parts[0].casefold() in _FORBIDDEN_FIRST_PARTS:
        raise LayoutError(f"layout.{key} 不得落在 {parts[0]}/：{raw!r}")

    root_resolved = root.resolve()
    candidate = (root_resolved / Path(*parts)).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise LayoutError(f"layout.{key} 解析后逃出项目根：{raw!r} -> {candidate}") from exc
    if candidate.exists() and not candidate.is_dir():
        raise LayoutError(f"layout.{key} 已存在但不是目录：{raw!r}")
    return root / Path(*parts)


def validate_value(root: Path, key: str, value: str) -> Path:
    if key not in _ALLOWED_LAYOUT:
        raise LayoutError(f"未知 layout 键：{key!r}（只允许 assets_root / adr）")
    return _validate_rel_path(Path(root).absolute(), key, value)


def write_config(root: Path, assets_root: str, adr: str | None = None,
                 overwrite: bool = False) -> Path:
    """原子写 `atlas.config.yaml`；已存在且未显式 overwrite ⇒ LayoutError。"""
    root = Path(root).absolute()
    config = root / CONFIG_NAME
    if config.exists() and not overwrite:
        raise LayoutError(f"布局配置已存在，拒绝覆盖：{config}")
    _validate_rel_path(root, "assets_root", assets_root)
    if adr is not None:
        _validate_rel_path(root, "adr", adr)
    lines = ["version: 1", "layout:", f"  assets_root: {assets_root.strip()}"]
    if adr is not None:
        lines.append(f"  adr: {adr.strip()}")
    tmp = config.parent / (config.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(config)
    return config


def load_layout(root: Path, config_path: Path | None = None) -> Layout:
    root = Path(root).absolute()
    config = Path(config_path) if config_path is not None else root / CONFIG_NAME
    if not config.is_file():
        if config_path is not None:
            raise LayoutError(f"指定的布局配置不存在：{config}")
        assets_root = root / DEFAULT_ASSETS_ROOT
        return Layout(root=root, assets_root=assets_root, adr_dir=assets_root / "adr")
    try:
        text = config.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise LayoutError(f"无法读取布局配置 {config}：{exc}") from exc
    data = _parse_config(text)
    assets_root = _validate_rel_path(root, "assets_root", data["layout"]["assets_root"])
    adr_raw = data["layout"].get("adr")
    if adr_raw is not None:
        adr_dir = _validate_rel_path(root, "adr", adr_raw)
    else:
        adr_dir = assets_root / "adr"
        if adr_dir.exists() and not adr_dir.is_dir():
            raise LayoutError(
                f"layout.adr 默认路径已存在但不是目录：{adr_dir.relative_to(root).as_posix()}")
    return Layout(root=root, assets_root=assets_root, adr_dir=adr_dir)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="atlas 项目级资产根布局解析")
    parser.add_argument("--root", type=Path, default=Path("."), help="项目根目录")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--print", dest="print_key", metavar="KEY",
                       help="输出项目相对路径（assets_root / adr / prd / e2e / ...）")
    group.add_argument("--print-abs", dest="print_abs_key", metavar="KEY",
                       help="输出绝对路径")
    group.add_argument("--validate", action="store_true", help="校验配置；非法 exit 2")
    group.add_argument("--validate-value", nargs=2, metavar=("KEY", "VALUE"),
                       help="校验单个 layout 值（init 提示用）")
    group.add_argument("--write", action="store_true",
                       help="写 atlas.config.yaml（需 --assets-root，可选 --adr）")
    parser.add_argument("--assets-root", dest="write_assets_root", metavar="DIR",
                        help="--write 的资产根（项目相对）")
    parser.add_argument("--adr", dest="write_adr", metavar="DIR",
                        help="--write 的可选 ADR 根（项目相对）")
    args = parser.parse_args(argv)

    try:
        if args.write:
            if not args.write_assets_root:
                raise LayoutError("--write 需要 --assets-root")
            write_config(args.root, args.write_assets_root, args.write_adr)
            print("ok")
            return 0
        if args.validate_value:
            key, value = args.validate_value
            validate_value(args.root, key, value)
            print("ok")
            return 0
        layout = load_layout(args.root)
        if args.validate:
            for warning in layout.warnings():
                print(f"WARN [layout] {warning['code']}: {warning['detail']}", file=sys.stderr)
            print("ok")
            return 0
        key = args.print_key or args.print_abs_key
        if args.print_abs_key:
            print(layout.path_for(key))
        else:
            print(layout.print_value(key))
        return 0
    except LayoutError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(_main())
