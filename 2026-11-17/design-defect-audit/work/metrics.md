# 原始度量与取证命令（中间材料）

审计对象：`main` @ `dd80869`（v0.3.0-beta.2，2026-11-15）
采集日期：2026-11-17
全程只读；未改代码、未提交、未安装依赖、未跑全量测试。

## 1. 仓库规模

| 量 | 值 | 命令 |
|---|---|---|
| tracked 文件 | 500 | `git ls-files \| wc -l` |
| 提交总数 | 475 | `git rev-list --count HEAD` |
| 标签总数 | 72 | `git tag \| wc -l` |
| 近 30 天标签 | 52 | `git for-each-ref --sort=-creatordate --format='%(creatordate:short)' refs/tags \| awk '$1>="2026-10-18"' \| wc -l` |
| 近 14 天提交 | 232 | `git log --since=2026-11-01 --oneline \| wc -l` |
| 生产 Python（除 tests） | 41,102 行 | `git ls-files '*.py' \| grep -v '^tests/' \| xargs wc -l` |
| 测试 Python | 40,728 行 / 82 文件 / 1807 用例 | `pytest tests/ --collect-only -q` |
| Markdown | 40,026 行 | `git ls-files '*.md' \| xargs wc -l` |

## 2. PR 数据面核实（第 9 段）

- `gh` 未安装；仓库无 PR refs；`git log --merges` 仅 3 条（均为远端同步合并，非评审合并）。
- `duty-review/QUEUE.md` 机器状态行明写「issue 通道停用（以批语落点为准）」。
- 结论：PR 数据不足以支撑「最慢的 PR」分析。改用等价证据（见报告 §1）。

## 3. 门禁耗时

| 量 | 值 | 出处 |
|---|---|---|
| 全量出厂测试（静默） | 535s / 76 文件 / 1750 项 | `scripts/atlas_check.py:68-73` 注释 |
| 单并行会话负载 | 681s | 同上 |
| 发版日（~3× 负载）推算 | ~1600s | 同上 |
| 门预算 | 1800s（原 900s） | `scripts/atlas_check.py:73` |
| 采集到的 check-events | 51 条，全部 `fast=true`，最后一条 2026-11-05 | `.atlas/runs/check-events.jsonl` |

## 4. 返工热点（近 30 天 fix 提交触达文件 Top 12）

```
49 shared/gates.md
35 docs/map/atlas-map.html
34 DESIGN.md
33 CHANGELOG.md
30 docs/guide/changelog.md
22 docs/map/index.md
19 rings/e2e/reference.md
17 duty-review/QUEUE.md
16 duty-review/bugs.md
15 tests/test_validators.py
13 tests/test_gen_e2e_scripts.py
13 scripts/gen_e2e_scripts.py
```

命令：
```
git log --since='2026-10-18' --grep='fix|修' -i --name-only --pretty=format: \
  | grep -v '^$' | sort | uniq -c | sort -rn | head -20
```

## 5. 账本与计数

- `docs/map` 相关提交 112 次（占 475 的 23.6%）：`git log --oneline -- docs/map | wc -l`
- `docs/map/*.md` 内 `path:line` 锚 79 处；`(N 行)` 计数锚 9 处
- `tests/refresh_count_anchors.py` 明示不写 `shared/gates.md` 与 canonical 计数（`:13-16`、`:210-217`）
- 计数/锚/基线类提交 46 次：`git log --pretty=format:'%s' | grep -cE '计数|锚|基线|刷新|回正|门清障|golden|回长'`
- `shared/closeout.md:34`：近 30 天按自然日划批，26/30 会被 changelog guard would-flag
- 两份 changelog 非镜像：`diff CHANGELOG.md docs/guide/changelog.md | wc -l` = 163 行差异

## 6. 发版门清障提交（3 天 3 次）

| commit | 日期 | 触达 |
|---|---|---|
| bf0e297 | 2026-11-14 | `shared/gates.md` 计数 1 行 + 2 个测试基线 |
| 65eee1d | 2026-11-13 | `shared/gates.md` 4 行 + duty 基线 |
| efb83c1 | 2026-11-15 | 主要是 `_support/*` + 账本（beta.2 门清障） |

## 7. 结构性事实

- 生产模块 `def` 重名：`_git` ×6（含 `_support/solution.py` 与 `_support/solution_seal.py` 各一份）、`semver_lt` ×2、`split_row` ×2、`read_origin` ×2、`tid_owner` ×2、`normalize_mock_prefixes` ×2。
- 模块加载器 3 套：`_support/siblings.py:23`、`_support/solution.py:70`、`scripts/atlas_solution.py:25`。
- 依赖环：`_support/solution.py:3334`（惰性）→ `_support/solution_e2e.py:67` → `validators/validate_e2e_index.py:736` → `_support/solution.py`。
- `_support/solution.py` 3,997 行 / 10 个分节；`solution_seal.py` 1,822 行。
- `DESIGN.md` §12 决策行 211 条；`:460` 为「E1 作废决策」前言，单段声明约 20 条作废。

命令：
```
python3 - <<'EOF'  # 重名 def 普查
import re,collections,pathlib
...
EOF
```
