# 账本设计案 · 中间取证（work）

- 对象：`/Users/sunwenzhe/Desktop/atlas`，`main` @ `dd80869`（v0.3.0-beta.2）
- 日期：2026-11-17
- 性质：**只读**。未改代码、未提交、未动 `docs/map` 与计数锚、未启动服务。
- 本文只放原始数字与命令；判断在 `../outputs/ledger-design.md`。

## 1. 规模实测

| 量 | 值 | 命令 |
|---|---|---|
| 测试文件 | 80 | `ls tests/test_*.py \| wc -l` |
| 用例实收 | 1807 | `python3 -m pytest tests/ --collect-only -q \| tail -2` |
| 校验器 | 12 | `ls validators/validate_*.py \| wc -l` |
| 共享契约 | 9 | `ls shared/*.md \| wc -l` |
| 共享内核 | 19 | `ls _support/*.py \| wc -l` |
| 门册行数 | 186（splitlines） | `wc -l shared/gates.md` = 185（末行无换行） |
| 门册数字+量词 | 91 处 | 正则 `\d+\s*(个\|条\|行\|份\|件\|类\|器)` |
| 门册超长行 | 20 行 > 1200 字符，最长 4176（E2E 真跑行） | Python 统计 |
| DESIGN 决策行 | 198 | `grep -cE '^\| *\*{0,2}D[0-9]+' DESIGN.md` |
| DESIGN 作废/退役/删除线行 | 17 | `grep -cE '作废\|已退役\|~~' DESIGN.md` |
| 两份 changelog 差异 | 163 行 | `diff CHANGELOG.md docs/guide/changelog.md \| wc -l` |

> 任务书里的「78 个测试文件」与实况 80 不符；本文一律用实测 80。

## 2. 账本触及频率（近 7 天，含 gates/DESIGN/双 changelog/docs/map/duty-review）

```
2026-11-11 10
2026-11-12 13
2026-11-13  7
2026-11-14 12
2026-11-15  3
2026-11-16  0
2026-11-17  0
```
命令：`git log --since="<day> 00:00" --until="<day> 23:59" --oneline -- <账本路径集> | wc -l`
活跃日 ≈ 9 次/天。历史口径（审计 `design-defect-audit/work/metrics.md`）：计数/锚/基线类提交 46 次；`docs/map` 提交 112 次（占 475 的 23.6%）；3 天 3 次发版门清障（`bf0e297` / `65eee1d` / `efb83c1`）。

## 3. 反向证据：门全绿但账本自相矛盾（本次新测）

在 HEAD 上直接跑只读检查：

```
$ python3 tests/test_map_anchors.py
docs/map 锚门：全绿        # exit 0
```

同时实测到三处漂移：

| # | 漂移 | 实测 | 为什么门没抓到 |
|---|---|---|---|
| 1 | 7 个章节文件版本串停在 `v0.2.0-beta.7`，index 已是 `v0.3.0-beta.2` | `docs/map/{graph,review,gates,e2egen,apply,adapters,cli}.md:3` | `check_freshness` 只比对 `index.md` 的「锚定版本」与 html 的 `v…` 串，**不扫其余 md** |
| 2 | `docs/map/gates.md:4` 写「77 个出厂测试文件」，实况 80 | 同一句里还有「12 个校验器」正确 | 计数门只认 `shared/gates.md` 的四种固定句式；map 章节的散文数字不在值域 |
| 3 | `docs/map/gates.md:66` 写「编号已至 M162」、`:90` 写「已至 M164」，而同文件外实际最大编号是 `M176b` | 同一文件两行互相矛盾 | M 编号上限没有任何门 |

这三条是「锁手抄数字」这一取向的直接反例：不是漏了一条正则，而是**同一条事实在多个正文里有多个副本，门只锁了其中一处**。

## 4. 现有「算」的能力覆盖矩阵

| 派生面 | 谁在算 | 覆盖 | 明确不覆盖 |
|---|---|---|---|
| `docs/map` md 的 `path`(N 行) 与表格行 | `tests/refresh_count_anchors.py:128-141` | ✅ 可写 | — |
| `docs/map/index.md` 数字快照（8 键：校验器 / 出厂测试文件 / skills / 环 / 共享契约 / 共享内核 / install.sh 自检声明 / 最大单件） | `:143-178` + `_derive_snapshot` `test_map_anchors.py:244-270` | ✅ 可写 | 「编排门行」9 类无机器判据（`:282` 显式跳过） |
| `docs/map/atlas-map.html` 的 `N 行` / `×N` / `N 文件` | `:181-201` | ✅ 可写 | 版本串只报告不写（`:13-16`） |
| `docs/map` 的 `path:line` 锚 | `tests/test_map_anchors.py --fix` | ✅ 可写 | § 锚、语义正确性 |
| `shared/gates.md` 的计数 | 无人写 | ❌ | `refresh_count_anchors.py:210-217` 打印「范围外 N 处」后跳过 |
| canonical 的四类计数（测试文件 / 自检 / 校验器 / 逐文件条数） | `tests/test_canonical_consistency.py:221-295` 只**判**不写 | ❌ 无写入器 | 白名单外写法一律不判（`:420-433` 自认） |
| 两份 changelog 的 `[Unreleased]` | `tests/changelog_guard.py` 只判；`scripts/release.py:277-301` 发版时才 collapse | ⚠️ 只在发版 | 内容一致性、哪份权威 |
| 版本串 | `scripts/release.py:257-273` 写 index + html 两处 | ⚠️ 两处 | 其余 7 个 map md |
| DESIGN §12 现行集 | 无 | ❌ | 作废状态散在三种形态里，机器读不出 |
| duty-review 基线/案数 | `duty-review/families.py` 解析 + `tests/test_duty_bug_families.py` 22 钉 | ⚠️ 判形状 | 散文日期（明写盲区） |

## 5. 接线面核实

- `tests/changelog_guard.py` 除自身外只被 `tests/test_sync_automation.py` 引用；**不在 `atlas_check`、不在 `closeout.md` 步骤 1、不在 CI**（`.github/workflows/tests.yml` 只跑 `test_cli_commands.py` + `test_project_wiring.py`）。
- `tests/refresh_count_anchors.py` 同样只有测试与文档引用，无常驻接线。
- 两份 changelog 在 HEAD 上**都没有 `[Unreleased]` 段**（首段即 `## [v0.3.0-beta.2]`），而 guard 判据要求该段存在 ⇒ 任何触装配面的批次都会被 would-flag；这正是 `shared/closeout.md:34` 记的「26/30 会被 would-flag」。
- 权威声明：全仓 grep「权威」在 changelog 内零命中，没有任何一处写「哪份是权威」。

## 6. 门册与 map 章节的自我描述漂移

- `shared/gates.md` 2.6 写「80 个测试文件」，`docs/map/gates.md:4` 写「77 个」——同一事实两份副本，只有前者被 canonical 锁住。
- `docs/map/gates.md:18` 写「shared/gates.md(186 行)」——此行被 `check_freshness` 锁（正确）。
- 说明：**同一份文档内，行数被锁、散文计数与编号上限不被锁**。这就是「按句式白名单锁数字」的边界。
