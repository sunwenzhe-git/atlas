#!/usr/bin/env bash
# Atlas 每日巡检 · 只读信号收集器（协议见 duty-review/README.md §4）
# 用法: bash scripts/duty_signals.sh "<上次巡检日期，如 2026-10-16；也接受 git since 表达式>"
# 铁则: 全程只读、不落任何文件；输出人读为主，尾部机器段供脚本取数；正文判断交巡检器。
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

echo; echo "== bugs.md 族 JSON (机器段,供脚本取数) =="
python3 "$(git rev-parse --show-toplevel)/duty-review/families.py" --json

echo; echo "== 运行态轨迹摘要 (check-events.jsonl; 只读观测面) =="
COMMON_DIR=$(git rev-parse --git-common-dir 2>/dev/null || echo ".git")
MAIN_ROOT=$(cd "$COMMON_DIR/.." 2>/dev/null && pwd || pwd)
EVENTS_FILE=""
EVENTS_SOURCE=""
if [ -n "${ATLAS_PLAYGROUND_ROOT:-}" ]; then
  EVENTS_FILE="$ATLAS_PLAYGROUND_ROOT/.atlas/runs/check-events.jsonl"
  EVENTS_SOURCE="ATLAS_PLAYGROUND_ROOT"
else
  SIBLING_EVENTS="$(dirname "$MAIN_ROOT")/atlas-playground/.atlas/runs/check-events.jsonl"
  if [ -f "$SIBLING_EVENTS" ]; then
    EVENTS_FILE="$SIBLING_EVENTS"
    EVENTS_SOURCE="sibling:atlas-playground"
  elif [ ! -f "$MAIN_ROOT/install.py" ] || [ ! -d "$MAIN_ROOT/rings" ]; then
    # 仅非 Atlas 源仓才回退当前仓，防源仓全 SKIP 自影（M259）
    EVENTS_FILE="$MAIN_ROOT/.atlas/runs/check-events.jsonl"
    EVENTS_SOURCE="repo-local"
  fi
fi

if [ -n "$EVENTS_FILE" ] && [ -f "$EVENTS_FILE" ]; then
  python3 - "$EVENTS_FILE" "$EVENTS_SOURCE" <<'PY'
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

path = Path(sys.argv[1])
source_label = sys.argv[2]
clean_runs = 0
dirty_runs = 0
ablation_skipped = 0
parse_errors = 0
friction = defaultdict(lambda: {"fail": 0, "warn": 0})
# M259: 仅统计非消融、非 SKIP/N/A/ABSENT 且 duration_ms 非空的实跑行
ablate_stats = defaultdict(lambda: {"ok": 0, "fail": 0, "warn": 0, "durations": []})

with path.open("r", encoding="utf-8", errors="replace") as fh:
    for raw in fh:
        line = raw.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            parse_errors += 1
            continue
        if not isinstance(ev, dict) or not isinstance(ev.get("rows"), list):
            parse_errors += 1
            continue
        if ev.get("ablation_id") is not None:
            ablation_skipped += 1
            continue
        is_clean = (ev.get("git_dirty") is False)
        if is_clean:
            clean_runs += 1
        else:
            dirty_runs += 1
        for row in ev["rows"]:
            if not isinstance(row, dict):
                continue
            name = row.get("name")
            status = row.get("status")
            dur = row.get("duration_ms")
            if not isinstance(name, str) or not isinstance(status, str):
                continue
            if is_clean and status in ("FAIL", "WARN"):
                friction[name]["fail" if status == "FAIL" else "warn"] += 1
            if status in ("SKIP", "N/A", "ABSENT"):
                continue
            if status == "FAIL":
                ablate_stats[name]["fail"] += 1
            elif status == "WARN":
                ablate_stats[name]["warn"] += 1
            elif status in ("ok", "PASS"):
                ablate_stats[name]["ok"] += 1
            if isinstance(dur, (int, float)) and not isinstance(dur, bool):
                ablate_stats[name]["durations"].append(float(dur))

print(
    f"来源={source_label} ({path}) · clean={clean_runs} · wip_dirty={dirty_runs} "
    f"· ablation_filtered={ablation_skipped} · parse_errors={parse_errors}"
)
hot = sorted(
    ((k, v["fail"], v["warn"]) for k, v in friction.items()),
    key=lambda x: (-(x[1] * 3 + x[2]), x[0]),
)[:5]
if hot:
    print("-- clean 运行摩擦热点 Top 5 (FAIL/WARN) --")
    for name, f_n, w_n in hot:
        print(f"  {name}: FAIL={f_n} WARN={w_n}")
else:
    print("-- clean 运行摩擦热点: (无 FAIL/WARN) --")

zero_trig = []
for name, st in ablate_stats.items():
    if st["ok"] > 0 and st["fail"] == 0 and st["warn"] == 0 and st["durations"]:
        med = statistics.median(st["durations"])
        tot = sum(st["durations"])
        zero_trig.append((name, st["ok"], med, tot))
zero_trig.sort(key=lambda x: (-x[2], -x[3], x[0]))
if zero_trig[:5]:
    print("-- 0 触发(仅实跑 ok)高耗时 Top 5 (atlas-ablate 观察线索) --")
    for name, ok_n, med, tot in zero_trig[:5]:
        print(f"  {name}: ok={ok_n} median={med:.0f}ms total={tot:.0f}ms")
else:
    print("-- 0 触发高耗时线索: (无符合条件门) --")
PY
else
  echo "(无 check-events.jsonl，跳过)"
fi

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
