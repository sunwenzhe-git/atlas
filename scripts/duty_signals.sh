#!/usr/bin/env bash
# Atlas 每日巡检 · 只读信号收集器（协议见 duty-review/README.md §4）
# 用法: bash scripts/duty_signals.sh "<上次巡检日期，如 2026-10-16；也接受 git since 表达式>"
# 铁则: 全程只读、不落任何文件；输出给人读，正文判断交巡检器。
set -uo pipefail
SINCE="${1:-yesterday}"
# 裸日期补 00:00：git 会把无时间成分的日期锚定到当前时刻（2026-10-16 实测 --since="2026-10-16" 返回空），产生假「无新增信号」
case "$SINCE" in
  *" "*|*:*|*[a-zA-Z]*) ;;   # 已含时间或自然语言（如 "yesterday"、"7 days ago"），原样
  *) SINCE="$SINCE 00:00" ;;
esac
cd "$(git rev-parse --show-toplevel)" || exit 1

echo "== NOW =="
date '+%F %T'

echo; echo "== 脏文件 (git status --porcelain) =="
git status --porcelain

echo; echo "== 新提交 (since: $SINCE) =="
git log --since="$SINCE" --oneline

echo; echo "== 台账被动过没 (DESIGN.md / shared/gates.md / CHANGELOG.md, since: $SINCE) =="
git log --since="$SINCE" --oneline -- DESIGN.md shared/gates.md CHANGELOG.md

echo; echo "== 30 天 fix 类提交触达文件 (DR4 聚类输入；按 fix/修/红/回归 过滤——建议③ 2026-10-17) =="
git log --since='30 days ago' --name-only --grep='fix\|修\|红\|回归' -i --pretty='format:@%h %s'

echo; echo "== bugs.md 同根段聚类 (DR4 口径 B：族规模 × 活跃窗；活跃且 >=3 案 ⇒ 升室候选) =="
python3 "$(git rev-parse --show-toplevel)/duty-review/families.py"

REPO=$(git remote get-url origin 2>/dev/null | sed -E 's#.*github\.com[:/]##; s#\.git$##')
echo; echo "== GitHub issues (${REPO:-仓库不明, 跳过}; open 全列 + closed 近 14 天有动静 + closed 全索引) =="
if [ -n "$REPO" ]; then
  python3 - "$REPO" <<'PY'
import json, sys, urllib.request
from datetime import datetime, timedelta, timezone
repo = sys.argv[1]
try:
    url = f"https://api.github.com/repos/{repo}/issues?state=all&per_page=100&sort=updated&direction=desc"
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.load(r)
except Exception as e:
    print(f"(GitHub API 不可达: {e})")
    sys.exit(0)
items = [i for i in data if "pull_request" not in i]
opened = [i for i in items if i["state"] == "open"]
closed = [i for i in items if i["state"] != "open"]
if not opened:
    print("(0 open)")
for i in opened:
    print(f"#{i['number']} {i['title']} (comments={i['comments']}, updated={i.get('updated_at','')[:10]})")
cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%d")
recent = [i for i in closed if i.get("updated_at", "") >= cutoff]
print(f"-- closed 近 14 天有动静 {len(recent)}/{len(closed)} 条 --")
for i in recent:
    print(f"#{i['number']} [closed·更新 {i.get('updated_at','')[:10]}] {i['title']} (comments={i['comments']})")
print("-- closed 全索引（存量对照库：每轮新信号逐条比对用） --")
for i in sorted(closed, key=lambda x: x["number"]):
    print(f"#{i['number']} {i['title']}")
PY
fi
