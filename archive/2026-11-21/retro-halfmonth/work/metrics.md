# 数据底稿（只读取证，2026-11-21）

所有数字均由下列命令在 `/Users/sunwenzhe/Desktop/atlas` 上现跑得出，未改仓库。

## 1. 提交面

```bash
git log --since=2026-11-06 --oneline | wc -l          # 193
git log --since=2026-11-06 --pretty=format:'%s' | grep -c '^fix'   # 37
```

| 类型 | 条数 |
|---|---|
| feat | 47 |
| docs | 64 |
| fix | 37 |
| chore | 21 |
| test | 14 |
| refactor | 9 |
| ci | 2 |

按日分布（提交数）：11-06 3 / 11-07 9 / 11-08 22 / 11-09 6 / 11-10 6 / 11-11 28 /
11-12 22 / 11-13 9 / 11-14 25 / 11-15 3 / 11-17 35 / 11-18 2 / 11-19 8 / 11-20 16。

## 2. 发版面

```bash
git for-each-ref --sort=creatordate --format='%(creatordate:short) %(refname:short)' refs/tags | awk '$1>="2026-11-06"'
```

17 个 tag / 15 天（11-13 两次、11-17 两次、11-19 三次、11-20 四次）。

发版提交与其上一条提交的时间差（脚本见对话记录）：

| 发版 | 上一条提交 | 间隔 | 上一条类型 |
|---|---|---|---|
| v0.4.0-beta.4 | docs(map) 行数锚复位 | 1 min | 账本 |
| v0.4.0-beta.3 | docs(changelog) workflow 记录 | 9 min | 账本 |
| v0.4.0-beta.2 | fix(workflow) 状态机 | 10 min | 代码 |
| v0.4.0-beta.1 | refactor(workflow) 167 文件 | 72 min | 代码 |
| v0.3.0-beta.6 | docs(changelog) D202 补记 | 10 min | 账本 |
| v0.3.0-beta.5 | docs(changelog) guide 补记 | 19 min | 账本 |
| v0.3.0-beta.4 | docs(map) 用例计数 | 0 min | 账本 |
| v0.3.0-beta.3 | fix(kernel) semver 门 | 10 min | 代码 |
| v0.3.0-beta.2 | fix(validators) AC 文法 | 34 min | 代码 |
| v0.3.0-beta.1 | test 计数/基线回正 | 9 min | 账本 |
| v0.2.0-beta.36 | fix(test) probe_browser 钉 | 11 min | 测试 |
| v0.2.0-beta.35 | fix(tests) 新鲜度标签 | 0 min | 测试 |
| v0.2.0-beta.34 | fix(gates) 门册手尾 | 611 min | 账本 |
| v0.2.0-beta.33 | docs(changelog) | 0 min | 账本 |
| v0.2.0-beta.32 | docs(map) 计数 61 | 188 min | 账本 |
| v0.2.0-beta.31 | test 锁脏检查 | 43 min | 测试 |
| v0.2.0-beta.30 | docs(rfc) 回填 | 28 min | 文档 |

12/17（71%）的 tag 在 0–34 分钟内紧跟一条「清障」提交；其中账本类 8 条、测试/钉类 3 条、真代码 3 条。

## 3. 账本漂移：D201 落地前后

切点 = `2026-11-17 15:45`（`9d0d52d` 派生生成器落地）。

```bash
git log --until='2026-11-17 15:45' --since=2026-11-06 --pretty=format:'%s' \
  | grep -cE '计数|锚|基线|刷新|回正|回长|清障|golden|版本串|行数'   # 25
git log --since='2026-11-17 15:45' --pretty=format:'%s' \
  | grep -cE '计数|锚|基线|刷新|回正|回长|清障|golden|版本串|行数'   # 6
```

| 区间 | 提交总数 | 账本类 | 占比 |
|---|---|---|---|
| 11-06 → 11-17 15:45 | 134 | 25 | 18.7% |
| 11-17 15:45 → 11-21 | 60 | 6 | 10.0% |

后 6 条里有 3 条本身是 D201 的实施步骤（`23d771e`/`b0c230d`/`99acadc`），
残余漂移修复 = 3 条 / 4 天：`1a17306`（计数值域）、`2191290`（用例计数）、`ace8d4e`（行数锚）。

`2026-11-17/ledger-design` 自定的验收判据是「账本文件退出 fix 提交 Top10」。
实测（11-17 15:45 之后，11 条 fix 提交的文件触达计数）：

| 文件 | 次数 |
|---|---|
| `scripts/atlas_workflow.py` | 4 |
| `docs/map/cli.md` | 4 |
| `CHANGELOG.md` | 4 |
| `_support/workflow_plan.py` | 4 |
| `shared/gates.md` | 3 |
| `docs/guide/changelog.md` | 3 |

账本文件仍占 Top10 的 3 席 → **验收判据未达成**。

## 4. fix 提交触达文件（全区间）

```bash
git log --since=2026-11-06 --grep='^fix' --name-only --pretty=format: | grep -v '^$' | sort | uniq -c | sort -rn
```

`shared/gates.md` 12、`_support/solution.py` 8、`tests/test_atlas_solution.py` 7、
`tests/test_apply_record.py` 7、`CHANGELOG.md` 7、`docs/guide/changelog.md` 6、
`docs/map/cli.md` 5、`_support/solution_seal.py` 5。

## 5. 现存不一致（未修）

```bash
sed -n '54,70p' scripts/atlas_check.py     # VALIDATORS 共 13 项
grep -n '12 器\|12 个 validate\|12 校验器' docs/map/*.md
```

- `docs/map/gates.md:17` `| validators/(12 器) |`
- `docs/map/gates.md:34` `| 12 个 validate_* |`
- `docs/map/gates.md:47` `## 12 个校验器(判据本体)`
- `docs/map/index.md:45` `12 校验器 + 编排器 + ...`

同文件 `docs/map/gates.md:4` 与 `docs/map/index.md:106` 用的是派生占位
`〔数:校验器文件=13〕` / `〔数:校验器=13〕`。两套口径并存，散文侧无门。
