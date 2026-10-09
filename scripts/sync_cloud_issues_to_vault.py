#!/usr/bin/env python3
"""atlas 云端流水线设计报告同步器 —— 架构师专用维护端工具。

从 GitHub Issues 中心池拉取带 `pipeline-rfc` 标签的未决设计报告，
自动转为 Obsidian vault 标准活页卡片，并自动挂载至 3509 未决问题台账。
纯标准库，零外部依赖。

用法：
    python3 sync_cloud_issues_to_vault.py [--vault ~/.local/share/open-zk-kb] [--repo sunwenzhe-git/atlas]
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

DEFAULT_REPO = "sunwenzhe-git/atlas"
DEFAULT_VAULT = Path.home() / ".local" / "share" / "open-zk-kb"


def get_token() -> str | None:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token.strip()
    try:
        proc = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n",
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                if line.startswith("password="):
                    t = line.split("=", 1)[1].strip()
                    if t.startswith(("ghp_", "gho_", "github_pat_")):
                        return t
    except Exception:
        pass
    return None


def fetch_open_issues(repo: str, token: str | None) -> list[dict]:
    url = f"https://api.github.com/repos/{repo}/issues?state=open&labels=pipeline-rfc&per_page=50"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Atlas-Sync-Vault/1.0",
    }
    if token:
        headers["Authorization"] = f"token {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def generate_note_id(index: int = 1) -> str:
    now_str = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{now_str}{index:02d}"


def sync_issue_to_note(issue: dict, atlas_dir: Path, seq: int) -> Path | None:
    issue_num = issue["number"]
    title = issue["title"]
    body = issue.get("body", "")
    author = issue.get("user", {}).get("login", "unknown")
    html_url = issue["html_url"]
    date_str = datetime.datetime.now().strftime("%Y-%m-%d")

    slug = re.sub(r"[^\w\-]+", "-", title.lower()).strip("-")[:35] or f"issue-{issue_num}"
    
    # 检查是否已同步过该 issue（防止重复建卡片）
    for existing in atlas_dir.glob("*.md"):
        try:
            content = existing.read_text(encoding="utf-8")
            if f"issue_url: {html_url}" in content or f"Issue #{issue_num}" in content:
                return None  # 已存在，跳过
        except Exception:
            continue

    note_id = generate_note_id(seq)
    filename = f"{note_id}-rfc-{slug}.md"
    target_path = atlas_dir / filename

    card_content = f"""---
id: {note_id}
title: "{title}"
kind: proposal
status: open
lifecycle: living
type: atomic
tags:
  - atlas
  - pipeline-rfc
  - cloud-report
created: {date_str}
updated: {date_str}
issue_number: {issue_num}
issue_url: {html_url}
reporter: {author}
---

# `[!!layers]` RFC #{issue_num}: {title}

> 来自云端 Agent 自感知上报：[{author} @ Issue #{issue_num}]({html_url})

{body}
"""
    target_path.write_text(card_content, encoding="utf-8")
    return target_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub 目标仓库")
    parser.add_argument("--vault", type=Path, default=DEFAULT_VAULT, help="Obsidian Vault 根路径")
    args = parser.parse_args()

    atlas_dir = args.vault / "atlas"
    if not atlas_dir.exists():
        print(f"⚠️ Obsidian atlas 设计目录不存在: {atlas_dir}，跳过同步。", file=sys.stderr)
        return 0

    token = get_token()
    print(f"📡 正在从 GitHub ({args.repo}) 获取未决流水线设计报告...")
    try:
        issues = fetch_open_issues(args.repo, token)
    except Exception as e:
        print(f"❌ 获取云端 Issues 失败: {e}", file=sys.stderr)
        return 1

    print(f"🔍 发现 {len(issues)} 条待处理流水线设计报告。")
    synced_count = 0
    for i, issue in enumerate(issues, start=1):
        created_file = sync_issue_to_note(issue, atlas_dir, i)
        if created_file:
            print(f"  + 新建活页卡片: {created_file.name} (Issue #{issue['number']})")
            synced_count += 1

    print(f"🎉 同步完成！共新增 {synced_count} 条卡片至 Obsidian Vault ({atlas_dir})。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
