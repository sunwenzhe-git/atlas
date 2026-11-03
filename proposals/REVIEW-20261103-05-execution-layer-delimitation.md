# 评审记录：执行层 ⇄ Atlas 四块定界（P1-3）

> 评审编号：REVIEW-20261103-05
> 评审对象：`proposals/RFC-20261103-10-execution-layer-delimitation.md`（对应 P1-3 / `duty-review/QUEUE.md` 归档行）
> 评审结论：**Approve（通过）—— 0 条阻塞项，2 条提示**
> 评审方式：只读复核 + 命令重放（评审与实施同一会话；非第三方独立评审，独立性弱于外部评审，故附原始输出）

---

## 1. 事实核查

| 核查项 | 结论 | 证据 |
|---|---|---|
| 编号唯一性 | 当日 RFC 先用 09（#31）⇒ 本件取 **10**；REVIEW 先用 04（#31）⇒ 本件取 **05**，无撞号 | §3 命令 ① 原始输出 |
| 前置 #31 已修 | `5a36129`；`.atlas-run/` 入目录族、两份清单常量化同源 | `scripts/e2e_console.py:132-133`、`:153/:155`、`:188/:190`；`git show --stat 5a36129` |
| #31 真实修复边界 | `.atlas-run/` **整树**排除（`results.json` / `.last-run.json` / trace / 截图 / 嵌套件）；`scripts/` 根白名单扩展名**仍计入** | 同左 + `RFC-20261103-09` §2.1/§5；`rings/e2e/reference.md` §10.1 |
| 防一刀切钉 | 源脚本内容变 ⇒ 哈希变（断言③） | `tests/test_e2e_console.py::test_scripts_hash_excludes_runtime_artifacts_and_whitelists_scripts`；§3 命令 ③ |
| D128 表述 | 目标句「执行产物不得致指纹假漂移」仍成立；边界已补记 `.atlas-run/` | `DESIGN.md:597` D128 ① |
| D174 表述 | `prov.fp = {script, block, rest, shared, app}` 仍成立；`results.json` 不参与三者 | `DESIGN.md:650` D174 ②；RFC-10 §2.3 |
| 过度结论检查 | RFC-10 / BACKLOG 均只出现「**不得**引用『判分载体均已指纹免疫』」，无一处正面宣称 | §3 命令 ④ |
| 四块裁定完备 | ①双轨、②迁出、③迁出（调度面）、④保留——每块恰一个三选一，且各带理由与落点 | RFC-10 §2.1；`BACKLOG-execution-layer.md:54-57` |
| §7 只增不删 | 四块均为**追加**；④ 的修复前断言改为「指纹面状态（2026-11-03 更新）」的带日期状态行，历史事实保留，未删除任何能力条目 | `git diff proposals/BACKLOG-execution-layer.md` |
| 无新机器判据 | 本批全部改动均为 `.md`；无钉、无变异、无门 | §3 命令 ② |
| D156 触发面 | (a) 否（非系统性修复）；(b) 否——diff 只落 `proposals/`、`duty-review/`，对 `event_path_tokens` 的契约族（`shared/`、`rings/`、`apply/`、`atlas.config.yaml`）与脚本族（`scripts/`、`tests/`）零命中 | §3 命令 ② + `scripts/closeout_derive.py:67-86` |
| 环境事实引用 | `_support/layout.py:119-120` 定义 `.atlas-run/`；`rings/e2e/reference.md` §10.1 二分表在位 | §3 命令 ⑤ |

## 2. 发现

1. **（提示，不阻塞）** 第 ④ 块的「保留」判定以「无清单外第三类载体、无自动消费者」为前提；前提之一是**经验性的**（自动消费者尚未出现），无法由本批机器面证明。RFC §2.3 已把它列为遗留 3，升格条件原样保留——OK。
2. **（提示，不阻塞）** `BACKLOG-execution-layer.md` ④ 行原句「现仍计入 `scripts_hash`」在 `5a36129` 后已不真。本批以带日期的「指纹面状态（2026-11-03 更新）」段替换，保留修复前事实与落点；不构成 §7 的条目删除，但属于**状态行编辑**，记录在此供维护者复核。

其余：四块裁定与卷首边界判据（判据 / 账本 / 覆盖维度 / 门禁 ⇄ 动作 / 运行 / 证据 / 报告）一致；硬接口表的每一行只有一个权威侧与一个写者，失败归属可判定；`ATLAS_CASE_ID` / 环境键 / `results.json` 字段集「逐字节不变」的冻结表述与 D121、D150 一致。

## 3. 重放命令与真实输出

```text
① 编号
$ ls proposals | grep -E "20261103" | sort
... RFC-20261103-08 / RFC-20261103-09 / RFC-20261103-10
... REVIEW-20261103-01 … REVIEW-20261103-04
（写入前 09 / 04 为当日最大 ⇒ 本件取 10 / 05）

② 改动面（D156 (b) 路径交叉检查）
$ git diff --name-only
duty-review/QUEUE.md
proposals/BACKLOG-execution-layer.md
（另加两个未跟踪新文件：RFC-20261103-10 / REVIEW-20261103-05）
⇒ 对 event_path_tokens 的「契约」「脚本」族均零命中；未改门 / 校验器 / 契约判据

③ 钉与快检
$ PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_e2e_console.py tests/test_duty_bug_families.py -q -p no:cacheprovider
47 passed in 1.76s
$ python3 scripts/atlas_check.py --fast
OK

④ 过度结论检查
$ grep -rn "指纹免疫" proposals/BACKLOG-execution-layer.md proposals/RFC-20261103-10-execution-layer-delimitation.md rings/e2e/reference.md
BACKLOG:57 …「仍不得引用「判分载体均已指纹免疫」」…
RFC-10:37 …「本 RFC 任何一处都不得写成「判分载体均已指纹免疫」」…
reference.md:689 …（指纹行，列 `.atlas-run/`（含 `results.json` / `.last-run.json` / trace）…

⑤ 落点
$ grep -n "e2e_run_dir" _support/layout.py
119:    def e2e_run_dir(self) -> Path:
120-        return self.e2e_scripts_dir / ".atlas-run"
```

## 4. 结论

* **Approve**：四块裁定、硬接口、失败归属与遗留均成立；与 #31 的真实修复边界一致，无过度结论。
* 纯定界 ⇒ **无新钉、无变异、无门**；D156 未触发（原始核对见 §3 ②）。
* 遗留已显式登记（RFC-10 §5）；执行层自建须另立 RFC，本件不构成实现授权。
