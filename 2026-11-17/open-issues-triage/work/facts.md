# 取证原始记录（open-issues-triage）

- 采集时间：2026-11-17
- 采集方式：只读静态命令（未跑测试、未启浏览器、未 git 写操作）
- HEAD：`96fcd8b`

## 1. 最近七笔（beta.2 之后）

```
96fcd8b docs(audit): 留档 2026-11-17 设计缺陷审计与账本单一源设计案
0eac771 feat(canonical): 变异钉登记完整性检查（单向集合比对）
0357bea feat(map): 「编排门行」登记为派生键并由占位渲染
1a17306 fix(map): html 文件条目的「N 个测试文件」纳入现有计数值域
7fb581a docs(ledger): 门册校验器数转占位 + D201 裁决记录（收口）
99acadc docs(map): 收掉章节版本串与门册两处手抄漂移（步 4）
b0c230d refactor(gates): 计数改派生占位，删五条句式白名单正则（步 3）
23d771e refactor(map): 数字快照改派生占位，check_snapshot 改重渲染门（步 2）
9d0d52d feat(ledger): 新增派生数字生成器（账本单一源 · 步 1）
```

`git log --stat dd80869..HEAD` 各笔文件数：9d0d52d 5 / 23d771e 4 / b0c230d 4 / 99acadc 11 / 7fb581a 2 / 1a17306 1 / 0357bea 3 / 0eac771 4 / 96fcd8b 4。**无 CHANGELOG.md / docs/guide/changelog.md 改动**。

## 2. 计数面

| 采集 | 结果 |
|---|---|
| `ls tests/test_*.py \| wc -l` | 81 |
| CI 实际 pytest 目标 | `tests/test_cli_commands.py tests/test_project_wiring.py`（tests.yml:33/89/92） |
| `ls .git/hooks \| grep -v sample` | 空 |
| `.pre-commit-config.yaml` / husky / lefthook | 均不存在 |
| 计数/锚/基线类提交（全史） | 39（`grep -cE '清障\|计数\|基线\|回正\|锚'`） |
| beta.2 之后命中同类词 | 2（均为本批账本改动，非清障） |
| `grep -o "〔数:[^〕]*〕"` | `shared/gates.md` 38 / `docs/map/*.md` 14 / `DESIGN.md` 1 |
| 仍为字面计数的点 | `shared/gates.md:80`「当前 12」，且 `test_canonical_consistency.py:607` 读它 |
| `grep -rn preflight scripts/ shared/` | 仅 `_support/auth_state.py:479`、`scripts/e2e_console.py:1519`（E2E 登录态预检），无批次门 |

## 3. 分层与重复

```
_support/solution_e2e.py:67,168,287,318,431,467   load_module("validate_e2e_index")
validators/validate_e2e_index.py:736,815          load_module("solution").load_manifest
_support/solution.py:3307,3334,3654               _load_sibling("solution_task"/"solution_e2e")
_support/siblings.py:23                            load_module
_support/solution.py:70                            _load_sibling
scripts/atlas_solution.py:25                       _load_solution（不写 sys.modules）
```

`def _git(`（生产侧 7 处）：`_support/solution.py:718`、`_support/solution_seal.py:54`、`adapters/_graph.py:172`、`scripts/ablation.py:187`、`scripts/atlas_eval.py:62`、`scripts/refresh_structure.py:609`、`validators/validate_task_card.py:38`；另 `scripts/e2e_console.py:121/129/142/164` 四个窄封装。

`semver_lt` 两份：
- `_support/solution.py:126-134`：不可解析 ⇒ `False`
- `scripts/atlas_solution.py:219-226`：不可解析 ⇒ 退回 `a.strip() < b.strip()`

单源守卫：`tests/test_shared_kernel.py:227-243`，`allowed` 11 项，只扫 `scripts/ validators/ _support/` 的模块级 `^def <name>\(`。

## 4. 单体

```
3997 _support/solution.py
1822 _support/solution_seal.py
 606 _support/solution_e2e.py
 435 _support/solution_task.py
```

分节（`grep -n "^# ---"`）：102 / 108 / 716 / 976 / 1023 / 1737 / 2311 / 2401 / 3046 / 3799。

`git log --since='2026-11-03' --numstat -- _support/solution.py` ⇒ 4223 增 / 226 删 = **4449**。

## 5. 决策台账

| 采集 | 结果 |
|---|---|
| §12 内 `^\| *D[0-9]` 行数（:458 起，至 :681 前） | 199 |
| 唯一 ID 数 | 199（无重复） |
| 删除线行 | 2（`:534` D71、`:540` D75） |
| 行内退役注记 | 3（D42 tokens 段、D71、D75） |
| 前言作废声明 | `DESIGN.md:460`（一段话列 D8 / D45 / D46-47 / D48 / D49-53 部分 / D54-59 / D67 / D68 部分） |
| §12 的机器判据 | 无（canonical 只判 §13 状态词与校验器清单） |
| 「现行决策」生成器 | 无（`ledger_snapshot.py:14-15` 明示决策理由不派生） |

## 6. changelog guard

```
tests/changelog_guard.py           存在
scripts/changelog_guard.py         不存在
install.py:568-569                 pkg_dirs = shared/ rings/ apply/ scripts/ templates/ adapters/ validators/ patches/ _support/ extensions
package.json.files                 无 tests
scripts/pkg_digest.py:55-56        ASSEMBLY_COVER_DIRS 11 项，无 tests
shared/closeout.md:34              仍 shadow，明写「未接本清单」
tests/test_sync_automation.py:26-28 已把 tests/ 与 scripts/ 加入 sys.path ⇒ 迁移后 import 不需改
```

## 7. prototype

```
scripts/e2e_console.py:1446-1448   last_submit：e.get("source", "prototype")
scripts/e2e_console.py:1465        committed_snapshot：e.get("source", "prototype")
_support/solution_e2e.py:448       e.get("source", "prototype") == "app"
validators/validate_e2e_index.py:226  STATES 含 prototype-pass
_support/stack_profile.py:22,116   prototype 段仍解析
validators/validate_stack_profile.py:435  prototype 段判 N/A
shared/global-rules.md:94          prototype-pass = E0 历史终态
```

## 8. 跨网复验相关锚点

| 语义 | 位置 |
|---|---|
| 锁文件名 | `_support/solution.py:37` `LOCK_NAME = "atlas.solution.lock.json"`；清单 `:36` |
| 封条状态闭集 | `_support/solution_seal.py:32` `SEAL_STATES = ("active","retired","frozen")` |
| freeze 写侧 | `_support/solution.py:3825-3849` |
| frozen 读侧判据 | `_support/solution_seal.py:697-727`（`seal_frozen_modified`） |
| `--lenient` 拒绝 | `scripts/atlas_solution.py:485-488` |
| check exit 语义 | `scripts/atlas_solution.py:503`（`overall == FAIL` ⇒ 1） |
| atlas_check 校验器来源 | `scripts/atlas_check.py:239`（`<root>/.atlas/validators/`） |
| `--fast` 跳过项 | `scripts/atlas_check.py:1011-1019`（跳过 `check_factory` / `check_e2e`） |

## 9. 本次未执行的检查（按任务约束）

- 未跑 `pytest`（含建议的 preflight 三文件组合，因此无耗时数据）
- 未跑 `atlas_check` / `atlas solution check`
- 未执行任何 git 写操作；`git status` 仅见 `?? 2026-11-17/prompt-library-eval/`（本次未触碰）
