---
name: atlas-ablate
description: "全量消融诊断：触发即在项目外隔离副本中，对当前门册的全部机制（VALIDATORS 全量 + atlas_check 内联门行）逐一摘除、观测门禁与耗时、再逐字节还原。只有一种模式：全量；不存在单机制模式。非流水线硬门禁，不做自动修复、不改真相源、不重录基线，也不宣称净收益。Use when 用户说消融诊断/ablation/全量消融/这个规则有没有用/门禁耗时是否值得。"
---

# atlas-ablate — 全量消融诊断

一次触发 = 一次全量消融。全量范围由项目当前的门册自动枚举，不由用户或 Agent 手挑。

## 0. 唯一模式与边界

- **唯一模式：全量**。不提供单机制、抽样、按目录挑选等第二种入口；用户说「摘掉某机制试试」时，仍按全量执行，再由矩阵定位该机制那一行。
- **非门禁**：不接入 `atlas check`、不参与 CI、不自动触发。
- **只读目标树**：全部摘除/还原只发生在项目外的隔离副本；目标工作树不被修改。
- **不用 git 写操作**：编排器不使用 `git apply` / `git checkout` / `git reset`，因此不要求目标仓可写 git，也不产生 git 写操作。
- **不改真相源**：不执行 `--record` / `--write` / `--force`，不手工改基线，不清理 active 事务。
- **不宣称净收益**：只出观测矩阵，不给「删/留」结论，不自动建议删除。
- **与 `atlas eval` 分工**：`atlas eval` 做 base/candidate commit 对照；本 skill 做隔离副本内的门机制摘除观测。

### 0.1 全局 Skill 的底座定位（先做这一步）

本 Skill 可全局安装（`~/.agents/skills/atlas-ablate/`），但底座必须在**当前项目**里找到：

1. 当前目录有 `.atlas/scripts/ablate_all.py` ⇒ 装配态：下文命令用 `.atlas/scripts/...`；
2. 否则当前目录有 `scripts/ablate_all.py` ⇒ Atlas 源包根：下文命令把 `.atlas/` 换成 `scripts/`；
3. 两者都没有 ⇒ **停止**，提示「当前目录不是 Atlas 项目根，找不到 ablate_all.py；请 cd 到项目根或先装配 Atlas」。不要猜路径、不要退化成单机制、不要手工拼补丁。

## 1. 全量的定义

全量 = 当前 `atlas_check.py` 运行面的**全部可摘门机制**：

1. `VALIDATORS` 元组中的每个校验器（每器一个机制）；
2. `atlas_check.py` 中所有调用 `rows.add` 的内联门函数（调度器 `check_validators` 除外）。

范围以编排器生成的 `catalog.json` 为准，不写死数字。源包当前为 13 个校验器 + 10 个内联门函数，共 23 个机制；项目升级后自动跟随。

**不在同一测量面**：装配期 hook / skill / wiring、`atlas eval` 对照、真跑 E2E 的业务用例本身。它们是装配或业务面，不是 `atlas_check` 门行；不要把「未覆盖」误写成「无价值」。

## 2. 触发后的第一步：只读盘点

```bash
python3 .atlas/scripts/ablate_all.py --root . --catalog-only \
  --out /tmp/atlas-ablate-catalog
```

- 输出机制总数与 `catalog.json`；
- 检查 `counts.validators` 与 `counts.inline` 是否与当前门册口径一致；
- `--catalog-only` 不复制、不摘除、不跑门，只读。

若目录为空、`VALIDATORS` 不可解析、或目标文件缺失 ⇒ 停止并报告根因；不要用单机制替代全量。

## 3. 执行全量（唯一入口）

```bash
python3 .atlas/scripts/ablate_all.py --root .
```

可选参数只影响证据与超时，不改变全量语义：

- `--out <dir>`：证据目录（必须在项目外；缺省 `~/.atlas-ablation/full/<root>/<时间>`）；
- `--rounds N`：基线轮数（默认 3；`N=1` 时不做耗时归因）；
- `--timeout S`：每次 fast 检查超时（默认 300 秒）；
- `--slow-timeout S`：非 fast 完整门册单次超时（默认 1800 秒）；
- `--keep-workdir`：保留隔离副本用于排障（不是第二种诊断模式）。

编排器内部按顺序做：

1. 检查当前 root 无 active 消融事务；
2. 把 root 复制到项目外临时目录（排除 `.git` / `node_modules` / 缓存）；
3. 在副本上跑基线 `atlas_check.py --fast --json`，默认 3 轮；
4. 逐机制摘除 → 单轮观测 → 逐字节还原并复算 sha256；
5. 写出 `catalog.json` / `baseline-fast.json` / `runs/` / `matrix.json` / `summary.md`。

## 4. 基线闸（不满足即停）

- 基线必须 `rc` 为 0 或 1，且 `--json` 可解析；空载荷、非 JSON、`rc=124/127` ⇒ 测量无效，停止。
- 基线不得有 `FAIL`；有 FAIL ⇒ 无法归因，停止并报告 FAIL 行。`WARN` / `SKIP` / `N/A` 不阻塞。
- 基线各轮的行状态必须一致；轮间漂移 ⇒ 停止，先解决环境不稳定。
- 非 fast 面（factory / E2E 等）单独跑一次完整门册：
  - 基线为 `FAIL` / `SKIP` / `N/A` ⇒ 该机制记「不可归因」，**不当作 ok**；
  - 基线为 `ok` / `WARN` ⇒ 可摘除并单轮观测；
  - 完整门册超时或无效 ⇒ 该面全部记「未覆盖 + 原因」，不得静默跳过。

## 5. 摘除与还原（编排器执行，Agent 不手工改）

- **校验器**：在副本中删除 `validators/<name>.py`；`check_validators` 会把该行置为 `SKIP`（这是预期观测，不是门坏了）。
- **内联门函数**：只把该函数内的 `rows.add(...)` 语句替换为 `pass`；函数内其他副作用保持执行，其他函数字节不动。
- **还原**：写回原始字节、恢复文件权限、复算 sha256；不一致 ⇒ **立即停止整批**，保留证据目录，报告失败路径。
- 任一机制还原失败后，不得继续下一个机制，也不得用 `git checkout` / `reset --hard` 绕过。

## 6. 输出怎么看

`summary.md` / `matrix.json` 每行一个机制：

- `面`：`fast` / `slow` / `none`；
- `基线 → 摘除后`：目标行状态迁移；
- `其他行变化`：摘除后其它门行是否变化（非空即「溢出」，需人复核依赖关系）；
- `Δ行耗时`：仅 `fast` 面、且基线轮数 ≥2 时给出；
- `可归因`：只有 `|Δ|` 超出基线噪声带才为「是」；否则只能写「不可归因」；
- `判定`：`目标行恶化` / `目标行摘除/降级` / `无可观测差异` / `溢出：其他行变化` / `未覆盖：<原因>` / `不可归因：<原因>` / `测量无效：<原因>`。

报告只引用这些字段，不把 `SKIP` 写成 `ok`，不把「零破损」写成「机制无用」。

## 7. 测量有效性（否则输出「无效」）

- 每次观测的 `rc` 必须是 0 或 1，且 JSON 可解析；
- `rc=124/127`、空载荷、截断/损坏 JSON ⇒ 本次观测无效；
- 单次样本不下结论；fast 面基线默认 3 轮，耗时归因必须给出噪声带；
- 还原后 sha256 必须与摘除前逐字节一致；否则整批无效；
- 非 fast 面只有单次基线时，只能报状态迁移，不报耗时归因。

## 8. 禁止事项

- 不启动服务、不杀进程、不访问生产；
- 不执行 `--record` / `--write` / `--force` / `git apply` / `git checkout` / `git reset`；
- 不把 `remediation_hint` 当修复命令执行；
- 不在 active 未清除时开始全量；
- 不提供单机制 / 抽样入口；不因「太慢」「范围太大」擅自缩小全量范围；
- 不把「零破损」直接等同于「机制无用」——覆盖缺口与预防型门不在本测量面内。
