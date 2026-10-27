#!/usr/bin/env python3
"""Atlas 一键推送与发版自动化工具（Atlas Release & Publish Automation）。

封装并固化《推送与发版机械规范》（release-publish-conventions）：
1. 代理检查：默认检测并应用 7897 本地代理，保证 GitHub 联通；
2. 真实版本推导：以 npm registry dist-tags + git tag 为唯一真相源，杜绝跳号事故；
3. 测试门禁：发版前严格执行全量 pytest 校验；
4. 多处版本落点同步：package.json, README.md(双连字符), docs config, CHANGELOG(两份)；
5. Git 提交、打 Tag、推送、GitHub Release 补建与 NPM 发布（--tag beta + latest dist-tag）；
6. 轮询并验证 npm registry 异步生效状态。

用法：
  python3 scripts/release.py --status      # 只读诊断当前本地与远端/npm 状态
  python3 scripts/release.py --check       # 运行测试并验证版本计算（不写盘、不发布）
  python3 scripts/release.py               # 交互式执行完整发布流程
  python3 scripts/release.py --auto        # 全自动执行发布
  python3 scripts/release.py --version 0.2.0-beta.2  # 指定目标版本号发布
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PKG_NAME = "atlas-project-harness"
DEFAULT_PROXY_PORT = 7897
PROXY_URL = f"http://127.0.0.1:{DEFAULT_PROXY_PORT}"
DEFAULT_REPO_SLUG = "sunwenzhe-git/atlas"
ROOT_DIR = Path(__file__).resolve().parent.parent


def is_proxy_alive(port: int = DEFAULT_PROXY_PORT) -> bool:
    """探测指定端口是否有本地代理服务在监听。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def get_proxy_env() -> dict[str, str]:
    """返回配置好网络代理的环境变量字典。"""
    env = os.environ.copy()
    if is_proxy_alive(DEFAULT_PROXY_PORT):
        env["http_proxy"] = PROXY_URL
        env["https_proxy"] = PROXY_URL
        env["ALL_PROXY"] = PROXY_URL
    return env


def run_cmd(
    cmd: list[str] | str,
    cwd: Path = ROOT_DIR,
    use_proxy: bool = False,
    check: bool = True,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    """运行命令行指令。"""
    env = get_proxy_env() if use_proxy else os.environ.copy()
    shell = isinstance(cmd, str)
    res = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        shell=shell,
        text=True,
        capture_output=capture_output,
    )
    if check and res.returncode != 0:
        cmd_str = cmd if isinstance(cmd, str) else " ".join(cmd)
        err_msg = res.stderr.strip() if res.stderr else res.stdout.strip()
        raise RuntimeError(f"命令执行失败 (code {res.returncode}):\n$ {cmd_str}\n{err_msg}")
    return res


def get_git_state() -> dict[str, any]:
    """获取 Git 分支、工作区及提交状态。"""
    # 尝试同步 fetch
    try:
        run_cmd("git fetch origin", use_proxy=True, check=False)
    except Exception:
        pass

    branch_res = run_cmd("git branch --show-current", check=False).stdout.strip()
    status_sb = run_cmd("git status -sb", check=False).stdout.strip()
    status_s = run_cmd("git status -s", check=False).stdout.strip()
    unpushed_commits = run_cmd(
        "git log origin/main..HEAD --oneline", check=False
    ).stdout.strip().splitlines()
    unpushed = [c for c in unpushed_commits if c.strip()]

    recent_tags = run_cmd(
        "git tag -l --sort=-v:refname", check=False
    ).stdout.strip().splitlines()
    latest_git_tag = recent_tags[0].strip() if recent_tags else ""

    return {
        "branch": branch_res or "main",
        "status_sb": status_sb,
        "dirty": bool(status_s),
        "unpushed": unpushed,
        "latest_git_tag": latest_git_tag,
    }


def get_npm_dist_tags() -> dict[str, str]:
    """从 npm 获取当前发布的 dist-tags。"""
    res = run_cmd(
        f"npm view {PKG_NAME} dist-tags --json", check=False, use_proxy=False
    )
    if res.returncode == 0 and res.stdout.strip():
        try:
            data = json.loads(res.stdout)
            if isinstance(data, list) and data:
                return data[0]
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return {}


def parse_semver(ver: str) -> tuple[int, int, int, str, int]:
    """解析如 0.2.0-beta.1 形式的版本号。"""
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([a-zA-Z]+)\.(\d+))?$", ver.strip())
    if not m:
        return (0, 0, 0, "", 0)
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    prerelease = m.group(4) or ""
    pre_num = int(m.group(5)) if m.group(5) is not None else 0
    return (major, minor, patch, prerelease, pre_num)


def compute_next_beta_version(explicit_version: str | None = None) -> str:
    """严格以 npm 和 git tag 为基准计算顺延的下一个 beta 版本号。"""
    if explicit_version:
        clean = explicit_version.lstrip("v")
        if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[a-zA-Z]+\.\d+)?", clean):
            raise SystemExit(f"非法版本号：{explicit_version}（期望 vX.Y.Z 或 vX.Y.Z-beta.N）")
        return clean

    dist_tags = get_npm_dist_tags()
    npm_ver = dist_tags.get("latest") or dist_tags.get("beta") or ""

    # 2026-10-25 加固(beta.9 空号教训:三源瞬时不一致 ⇒ 顺延跳号,npm 不可补):
    # 真相源升级 = registry versions **全集**语义最大,再对 next 做防撞兜底。
    registry_versions: list[str] = []
    try:
        res = run_cmd(
            f"npm view {PKG_NAME} versions --json", check=False, use_proxy=False
        )
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout)
            if isinstance(data, list):
                registry_versions = [v for v in data if isinstance(v, str)]
    except Exception:
        pass

    pkg_json_path = ROOT_DIR / "package.json"
    pkg_ver = ""
    if pkg_json_path.exists():
        try:
            pkg_data = json.loads(pkg_json_path.read_text(encoding="utf-8"))
            pkg_ver = pkg_data.get("version", "")
        except Exception:
            pass

    git_state = get_git_state()
    git_tag_ver = git_state["latest_git_tag"].lstrip("v")

    # 取三者的最大版本作为当前真实版本
    versions = [v for v in [npm_ver, pkg_ver, git_tag_ver] if v]
    if not versions:
        return "0.1.0-beta.1"

    parsed_versions = [(parse_semver(v), v) for v in versions]
    parsed_versions.sort(key=lambda x: x[0])
    highest_ver_str = parsed_versions[-1][1]

    major, minor, patch, pre, pre_num = parse_semver(highest_ver_str)
    if pre:
        next_pre_num = pre_num + 1
        candidate = f"{major}.{minor}.{patch}-{pre}.{next_pre_num}"
    else:
        # 如果当前是非 prerelease，默认进入下一个 minor beta
        candidate = f"{major}.{minor + 1}.0-beta.1"

    # 防撞兜底:候选若已在 registry versions 全集里 ⇒ 顺延直至空位(跳号不可逆,撞号即 E409)
    existing = set(registry_versions)
    guard = 0
    while candidate in existing and guard < 100:
        major_, minor_, patch_, pre_, num_ = parse_semver(candidate)
        if pre_:
            candidate = f"{major_}.{minor_}.{patch_}-{pre_}.{num_ + 1}"
        else:
            candidate = f"{major_}.{minor_ + 1}.0-beta.1"
        guard += 1
    return candidate


def sync_version_files(new_version: str, dry_run: bool = False) -> list[str]:
    """同步全部多处版本号落点。"""
    modified = []
    today_str = datetime.date.today().isoformat()

    # 1. package.json
    pkg_path = ROOT_DIR / "package.json"
    pkg_text = pkg_path.read_text(encoding="utf-8")
    new_pkg_text = re.sub(
        r'("version"\s*:\s*")[^"]+(")',
        rf'\g<1>{new_version}\g<2>',
        pkg_text,
        count=1,
    )
    if new_pkg_text != pkg_text:
        modified.append("package.json")
        if not dry_run:
            pkg_path.write_text(new_pkg_text, encoding="utf-8")

    # 2. README.md (注意：双连字符 0.1.0--beta.N)
    readme_path = ROOT_DIR / "README.md"
    readme_text = readme_path.read_text(encoding="utf-8")
    # 把 version 串里的单连字符转换成 shields.io 规范的双连字符
    badge_ver = new_version.replace("-", "--")
    new_readme_text = re.sub(
        r'(https://img\.shields\.io/badge/version-)[^-\s]+(?:--[a-zA-Z0-9.]+)?(-blue\.svg)',
        rf"\g<1>{badge_ver}\g<2>",
        readme_text,
    )
    if new_readme_text != readme_text:
        modified.append("README.md")
        if not dry_run:
            readme_path.write_text(new_readme_text, encoding="utf-8")

    # 3. docs/.vitepress/config.mts
    vite_path = ROOT_DIR / "docs" / ".vitepress" / "config.mts"
    vite_text = vite_path.read_text(encoding="utf-8")
    new_vite_text = re.sub(
        r"(\{ text:\s*'v)[^']+(',\s*link:\s*'https://github\.com/[^']+/releases'\s*\})",
        rf"\g<1>{new_version}\g<2>",
        vite_text,
    )
    if new_vite_text != vite_text:
        modified.append("docs/.vitepress/config.mts")
        if not dry_run:
            vite_path.write_text(new_vite_text, encoding="utf-8")

    # 5. docs/map/index.md 锚定版本 + atlas-map.html 版本串（2026-10-25 补，beta.8 漏刷教训：
    #    map 锚门「始终最新」会咬发版——版本同步面必须含 docs/map 两个落点）
    map_idx = ROOT_DIR / "docs" / "map" / "index.md"
    if map_idx.is_file():
        t = map_idx.read_text(encoding="utf-8")
        nt = re.sub(r"(v\d+\.\d+\.\d+-beta\.\d+)", f"v{new_version}", t, count=0) if False else re.sub(
            r"v\d+\.\d+\.\d+-beta\.\d+", f"v{new_version}", t)
        if nt != t:
            modified.append("docs/map/index.md")
            if not dry_run:
                map_idx.write_text(nt, encoding="utf-8")
    map_html = ROOT_DIR / "docs" / "map" / "atlas-map.html"
    if map_html.is_file():
        t = map_html.read_text(encoding="utf-8")
        nt = re.sub(r"v\d+\.\d+\.\d+-beta\.\d+", f"v{new_version}", t)
        if nt != t:
            modified.append("docs/map/atlas-map.html")
            if not dry_run:
                map_html.write_text(nt, encoding="utf-8")

    # 4. CHANGELOG.md (收拢 [Unreleased] 为 [vX.Y.Z])
    changelog_path = ROOT_DIR / "CHANGELOG.md"
    changelog_text = changelog_path.read_text(encoding="utf-8")
    if "## [Unreleased]" in changelog_text:
        new_cl_text = changelog_text.replace(
            "## [Unreleased]",
            f"## [v{new_version}] - {today_str}",
            1,
        )
        modified.append("CHANGELOG.md")
        if not dry_run:
            changelog_path.write_text(new_cl_text, encoding="utf-8")

    # 5. docs/guide/changelog.md (同步收拢 [Unreleased] 为 [vX.Y.Z])
    guide_cl_path = ROOT_DIR / "docs" / "guide" / "changelog.md"
    if guide_cl_path.exists():
        guide_cl_text = guide_cl_path.read_text(encoding="utf-8")
        if "## [Unreleased]" in guide_cl_text:
            new_gcl_text = guide_cl_text.replace(
                "## [Unreleased]",
                f"## [v{new_version}] - {today_str}",
                1,
            )
            modified.append("docs/guide/changelog.md")
            if not dry_run:
                guide_cl_path.write_text(new_gcl_text, encoding="utf-8")

    return modified


def run_test_suite() -> None:
    """执行发版前严苛门禁测试。"""
    print("⏳ 正在运行规范一致性测试 (test_canonical_consistency.py)...")
    res_canon = run_cmd("pytest tests/test_canonical_consistency.py -q", check=False)
    if res_canon.returncode != 0:
        raise RuntimeError(f"规范一致性测试失败：\n{res_canon.stdout}\n{res_canon.stderr}")
    print("  ✅ 规范一致性测试通过")

    print("⏳ 正在运行全量回归测试套件 (pytest tests/)...")
    res_full = run_cmd("pytest tests/ -q", check=False)
    if res_full.returncode != 0:
        lines = (res_full.stdout or "").strip().splitlines()
        tail = "\n".join(lines[-15:])
        raise RuntimeError(f"全量测试未全部通过：\n{tail}\n{res_full.stderr}")
    print("  ✅ 全量测试套件通过")


def verify_npm_live(version: str, max_wait_sec: int = 180) -> bool:
    """轮询 npm registry 确认新版本生效。"""
    print(f"⏳ 正在轮询 NPM Registry 确认 v{version} 生效...")
    start_time = time.time()
    while time.time() - start_time < max_wait_sec:
        cache_buster = int(time.time())
        url = f"https://registry.npmjs.org/{PKG_NAME}?t={cache_buster}"
        curl_res = run_cmd(
            f'curl -s "{url}"', check=False, use_proxy=False
        )
        if curl_res.returncode == 0 and curl_res.stdout:
            try:
                data = json.loads(curl_res.stdout)
                dist_tags = data.get("dist-tags", {})
                versions = data.get("versions", {})
                if dist_tags.get("latest") == version and version in versions:
                    return True
            except Exception:
                pass
        time.sleep(10)
    return False


def get_repo_slug() -> str:
    """从 origin 远端解析 owner/repo，失败时回落到本仓常量。"""
    res = run_cmd("git remote get-url origin", check=False)
    m = re.search(r"github\.com[:/]+([^/]+)/([^/]+?)(?:\.git)?$", res.stdout.strip()) if res.returncode == 0 else None
    return f"{m.group(1)}/{m.group(2)}" if m else DEFAULT_REPO_SLUG


def get_github_token() -> str:
    """三级取 token：环境变量 → gh CLI → git 凭据（HTTPS 推送用的 PAT）。"""
    for key in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PAT"):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    if shutil.which("gh"):
        res = run_cmd("gh auth token", check=False)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    try:
        res = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            text=True,
            capture_output=True,
            timeout=15,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                if line.startswith("password="):
                    return line[len("password="):].strip()
    except Exception:
        pass
    return ""


def github_api(
    method: str,
    path: str,
    token: str,
    payload: dict | None = None,
    timeout: int = 30,
) -> tuple[int, dict | list]:
    """调 GitHub REST API；返回 (HTTP 状态码, 响应体)；网络错误返回 (0, {...})。"""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"https://api.github.com{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "atlas-release")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    handlers = [urllib.request.ProxyHandler({"http": PROXY_URL, "https": PROXY_URL})] if is_proxy_alive(DEFAULT_PROXY_PORT) else []
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"message": raw[:300]}
    except Exception as e:
        return 0, {"message": str(e)}


def extract_changelog_section(text: str, version: str) -> str:
    """取出 CHANGELOG 中 `## [vX]` 段正文（到下一个 `## [` 为止）。"""
    m = re.search(
        rf"^## \[v{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)",
        text,
        re.M | re.S,
    )
    return m.group(1).strip() if m else ""


def changelog_section(version: str) -> str:
    p = ROOT_DIR / "CHANGELOG.md"
    if not p.is_file():
        return ""
    return extract_changelog_section(p.read_text(encoding="utf-8"), version)


def get_previous_tag(tag_name: str) -> str:
    """沿提交图取目标 tag 之前最近的 tag（自动 notes 的对比基线）。"""
    res = run_cmd(["git", "describe", "--tags", "--abbrev=0", f"{tag_name}^"], check=False)
    return res.stdout.strip() if res.returncode == 0 else ""


def get_github_latest_release() -> tuple[bool, str]:
    """返回 (查询是否可用, 最新非草稿 Release 的 tag)。

    不用 `/releases/latest`：它只认最新非 prerelease，存在稳定版时会对后续 beta 误报落后。
    """
    token = get_github_token()
    if not token:
        return False, ""
    code, data = github_api("GET", f"/repos/{get_repo_slug()}/releases?per_page=5", token, timeout=10)
    if code == 200:
        releases = [r for r in data if isinstance(r, dict) and not r.get("draft")] if isinstance(data, list) else []
        return True, (releases[0].get("tag_name", "") if releases else "")
    return False, ""


def create_github_release(tag_name: str, version: str) -> bool:
    """按已推送的 tag 补建 GitHub Release：beta ⇒ prerelease，正文取 CHANGELOG 段。

    幂等：同 tag 的 Release 已存在则跳过。失败只告警不抛错——调用点已推 tag 并即将发 npm，
    此处阻断只会留下「tag 已占号但未发布」的半态。
    """
    token = get_github_token()
    if not token:
        print("  ⚠️ 未取得 GitHub token（GITHUB_TOKEN / GH_TOKEN / git 凭据），跳过 Release 创建")
        return False
    slug = get_repo_slug()
    code, data = github_api("GET", f"/repos/{slug}/releases/tags/{tag_name}", token)
    if code == 200:
        print(f"  ℹ️ GitHub Release {tag_name} 已存在，跳过创建")
        return True
    if code != 404:
        print(f"  ⚠️ 查询 GitHub Release 失败 (HTTP {code})：{data.get('message', '')}")
        return False
    body = changelog_section(version)
    payload: dict[str, object] = {
        "tag_name": tag_name,
        "name": tag_name,
        "draft": False,
        "prerelease": bool(parse_semver(version)[3]),
        "generate_release_notes": not body,
    }
    if body:
        payload["body"] = body
    else:
        # 不传则以「上一个 Release」为基线——Release 缺席时基线会跨过多个 tag
        previous_tag = get_previous_tag(tag_name)
        if previous_tag:
            payload["previous_tag_name"] = previous_tag
    code, data = github_api("POST", f"/repos/{slug}/releases", token, payload)
    if code == 201:
        print(f"  ✅ GitHub Release 已创建：{data.get('html_url', tag_name)}")
        return True
    print(f"  ⚠️ GitHub Release 创建失败 (HTTP {code})：{data.get('message', '')}")
    return False


def cmd_status() -> None:
    """只读状态诊断。"""
    print("=" * 60)
    print("📋 Atlas 仓库发版状态诊断")
    print("=" * 60)

    git_state = get_git_state()
    proxy_ok = is_proxy_alive(DEFAULT_PROXY_PORT)
    dist_tags = get_npm_dist_tags()
    next_ver = compute_next_beta_version()

    pkg_ver = ""
    try:
        pkg_ver = json.loads((ROOT_DIR / "package.json").read_text(encoding="utf-8")).get("version", "")
    except Exception:
        pass

    print(f"🌐 本地 7897 代理状态 : {'🟢 监听中 (可用)' if proxy_ok else '🔴 未启动 (git push 可能超时)'}")
    print(f"🌿 当前 Git 分支      : {git_state['branch']}")
    print(f"📦 package.json 版本   : {pkg_ver}")
    print(f"🏷️  最新 Git Tag       : {git_state['latest_git_tag']}")
    print(f"🚀 NPM 当前发布版本   : latest={dist_tags.get('latest', 'none')}, beta={dist_tags.get('beta', 'none')}")
    rel_ok, rel_tag = get_github_latest_release()
    if not rel_ok:
        rel_line = "查询不可用（无 token / 网络受阻）"
    elif not rel_tag:
        rel_line = "无（下次发版自动创建）"
    elif rel_tag != git_state["latest_git_tag"]:
        rel_line = f"{rel_tag} ⚠️ 落后最新 tag（下次发版自动补建）"
    else:
        rel_line = rel_tag
    print(f"🐙 GitHub 最新 Release : {rel_line}")
    print(f"⏭️  推导下一个发版版本 : v{next_ver}")

    if git_state["dirty"]:
        print("\n⚠️ 工作区存在未提交的改动：")
        print(run_cmd("git status -s", check=False).stdout.strip())
    else:
        print("\n✨ 工作区干净，无未暂存改动")

    if git_state["unpushed"]:
        print(f"\n📌 本地领先远端 {len(git_state['unpushed'])} 个未推送提交：")
        for c in git_state["unpushed"]:
            print(f"  • {c}")
    else:
        print("📌 本地提交已全部同步至远端 (ahead 0)")
    print("=" * 60)


def cmd_release(target_version: str | None = None, auto: bool = False, dry_run: bool = False) -> None:
    """执行发布流程。"""
    next_ver = compute_next_beta_version(target_version)
    tag_name = f"v{next_ver}"

    print(f"\n🚀 准备执行发布流程：目标版本 = {tag_name}")
    if dry_run:
        print("🔍 [DRY RUN 模式]：只做检查与模拟，不实际提交、打标签、推送与发布 NPM\n")

    # 1. 代理检查
    if not is_proxy_alive(DEFAULT_PROXY_PORT):
        print(f"⚠️ 警告：本地端口 {DEFAULT_PROXY_PORT} 未监听，Git 推送可能因网络受阻。")
        if not auto and not dry_run:
            ans = input("是否继续尝试推送？[y/N]: ").strip().lower()
            if ans != "y":
                print("已取消发布。")
                return

    # 2. 测试门禁
    run_test_suite()

    # 3. 版本同步
    print(f"\n📝 正在同步版本号到 {next_ver}...")
    mod_files = sync_version_files(next_ver, dry_run=dry_run)
    # 2026-10-25 加固(beta.8 教训:并行会话在途改动被 chore 卷入发布):版本落点同步后,
    # 工作树里若还有「版本落点之外」的未提交改动 ⇒ 拒绝发版(等维护者分流)。
    if not dry_run:
        dirty_out = run_cmd("git status --porcelain", use_proxy=False).stdout
        mod_set = {m.split(" → ")[-1].strip() for m in mod_files}
        strays = []
        for line in dirty_out.splitlines():
            path = line[3:].strip().strip('"')
            if path and path not in mod_set:
                strays.append(path)
        if strays:
            raise RuntimeError(
                "工作树存在版本落点之外的未提交改动(会被卷入发版 chore)——请先分流:\n  "
                + "\n  ".join(strays[:10])
                + ("\n  …" if len(strays) > 10 else ""))

    if mod_files:
        print(f"  已更新版本落点文件: {', '.join(mod_files)}")
    else:
        print("  所有版本落点已是目标版本。")

    if dry_run:
        print("\n✅ DRY RUN 检查全部通过！")
        return

    # 4. 提交发版 chore (若有改动)
    git_st = run_cmd("git status -s", check=False).stdout.strip()
    if git_st:
        print(f"\n📦 正在提交发版 commit: chore(release): {tag_name}")
        run_cmd("git add -A")
        run_cmd(f'git commit -m "chore(release): {tag_name}"')
    else:
        print("\n📦 无新增改动，复用现有提交发版。")

    # 5. 打 Tag
    print(f"🏷️  创建标签: {tag_name}")
    run_cmd(f"git tag -f {tag_name}")

    # 6. 推送到 GitHub
    print("📤 正在通过代理推送到 GitHub origin...")
    run_cmd("git push origin main", use_proxy=True)
    run_cmd(f"git push -f origin {tag_name}", use_proxy=True)
    print("  ✅ Git 提交与 Tag 推送成功！")

    # 7. GitHub Release（跟随 tag；失败只告警，不阻断 npm）
    print("\n🐙 正在创建 GitHub Release...")
    try:
        create_github_release(tag_name, next_ver)
    except Exception as e:
        print(f"  ⚠️ GitHub Release 创建异常（不阻断发版）：{e}")

    # 8. NPM 发布
    print(f"\n📦 正在发布 NPM 包 {PKG_NAME}@{next_ver} (--tag beta)...")
    run_cmd("npm publish --tag beta")
    print(f"🔖 更新 NPM dist-tag latest -> {next_ver}...")
    run_cmd(f"npm dist-tag add {PKG_NAME}@{next_ver} latest")

    # 9. 轮询验证
    ok = verify_npm_live(next_ver)
    if ok:
        print(f"\n🎉 恭喜！{PKG_NAME}@{next_ver} 已正式在 NPM 生效！")
    else:
        print(f"\n⚠️ 提示：NPM 后台处理仍在队列中，稍后运行 `npm view {PKG_NAME} dist-tags` 即可查看。")


def main() -> None:
    parser = argparse.ArgumentParser(description="Atlas 项目一键发版自动化工具")
    parser.add_argument("--status", action="store_true", help="只读诊断当前状态")
    parser.add_argument("--check", action="store_true", help="运行测试与校验，模拟发版")
    parser.add_argument("--dry-run", action="store_true", help="模拟发版，不执行写盘和发布")
    parser.add_argument("--auto", "-y", action="store_true", help="全自动执行，无需二次确认")
    parser.add_argument("--version", "-v", type=str, default=None, help="显式指定目标版本号")
    args = parser.parse_args()

    if args.status:
        cmd_status()
    elif args.check or args.dry_run:
        cmd_release(target_version=args.version, auto=True, dry_run=True)
    else:
        cmd_release(target_version=args.version, auto=args.auto, dry_run=False)


if __name__ == "__main__":
    main()
