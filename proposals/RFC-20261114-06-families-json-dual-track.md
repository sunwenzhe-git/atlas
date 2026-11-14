# 提案：`families.py --json` 双轨批（人读轨不动，尾部机器段供脚本取数）

> 提案编号：RFC-20261114-06
> 提案作者：AI（维护者拍板批次）
> 关联状态：已定案（Accepted；独立评审「改造后采纳」）
> 影响范围：脚本工具（`duty-review/families.py`、`scripts/duty_signals.sh`）+ 测试防线 + canonical 登记面

---

## 1. 现象与取证

* **触发形态**：`scripts/duty_signals.sh:30` 调 `duty-review/families.py`，该脚本**只有一轨人读文本**
  （`main()` 只 `print(render(...))`），巡检自动化要与别的信号面做机器对账时只能正则刮中文列。
* **客观证据**：`python3 duty-review/families.py | wc -c` = **1142** 字节 / **6** 行（2026-11-14 实测）；
  `main()`（改前 `families.py:188-201`）无 argparse、无任何结构化出口。
* **基线实况**（2026-11-14）：`package.json` = `0.2.0-beta.36`；`tests/` **79** 个文件；
  `pytest --collect-only` 实收 **1755** 条；`tests/test_duty_bug_families.py` **19** 条；
  `git log origin/main..main` = 1 笔（`65690c3`）。

## 2. 决策与权衡

### 2.1 核心定案

1. `main()` 加 `--json` 旗标，**用扫描剥离**（`args=[a for a in argv if a!="--json"]`），不上 argparse
   ——避免未知旗标 exit 2 与 `-h` 行为面扩张；`--json <path>` 与 `<path> --json` 都通。
2. `--json` 时输出 **compact 单行 JSON**（`ensure_ascii=False`、无 indent）：
   `{"ledger": <路径>, "cutoff": <date.today().isoformat()>, "families": [...], "warns": [...]}`；
   每族 `{family, count, exact, last_date, active, verdict, warns[]}`。
3. **显式挑字段序列化**：`families()` 的 rows 内含 `ids` / `exact_ids` 两个 `set`，直接 `json.dumps` 必炸。
4. **去掉 render_text**：人读文本由 `duty_signals.sh` 的第一次调用提供，payload 里再放是纯重复。
5. **台账文件缺** ⇒ `families=[]`、`warns=[]`、`cutoff=null`（不 null 崩、不编造）。
6. **无旗标调用输出逐字节不变**。
7. `scripts/duty_signals.sh` 两次调用：`:30` 原行一字不动；其下加 marker 行 + `--json` 调用；
   文件头自述改「人读为主，尾部机器段供脚本取数」。

### 2.2 备选方案及否定理由

* **argparse**：未知旗标 exit 2 / `-h` 行为面扩张，与「旧旗标当路径静默出空报告 rc=0」脚枪同族；否。
* **render_text 入 payload**：与第一次调用重复，体积翻倍；否。
* **JSON 直接 `json.dumps(rows)`**：`set` 不可序列化，必炸；否。
* **永久冻结真实台账输出**：四周内必翻「族已静默」，是脆弱钉；否（只做批内一次性 diff 证据）。
* **把 JSON 写文件**：违巡检「全程只读」铁则；否。

### 2.3 代价与兼容性

* 巡检输出体积 +≤1KB（现网 families 段 1142 字节 / 6 行；该脚本有 30.4KB 输出体积前科，需实测卡口）。
* 无旗标人读轨零变化（批内 diff 为空）；无新增依赖（纯标准库）。

## 3. 改动面清单

- [x] **代码**：`duty-review/families.py`（`--json` 分支 + 显式字段序列化）
- [x] **脚本**：`scripts/duty_signals.sh`（marker + 第二次调用；文件头自述）
- [x] **测试防线**：`tests/test_duty_bug_families.py` +3（19 → 22）；变异 MB24–MB26
- [x] **canonical 登记面（七处）**：`shared/gates.md` 条数；测试文件头计数行；`duty-review/README.md:30`、`:32`、`:65`（§4）；`DESIGN.md` §12 D200；`CHANGELOG.md` 新批段
- [x] **介质不动**：`duty-review/bugs.md` / `QUEUE.md` 不动（承 D154 拒 JSON/SQLite 搬介质）

## 4. 验证与测试结果

* 钉 1：派生日期夹具 + 同源逐字段对照（`main(["--json", 夹具])` ⇔ 进程内 `families(夹具, today=today)`）；
* 钉 2：warns 双轨等值（JSON warns 数 == render WARN 行数）；
* 钉 3：no-flag 输出 = `render()` 单源直通 + 首行措辞逐字（不做真实台账永久冻结）；
* 变异 MB24（摘 `--json` 分支）/ MB25（JSON 丢 warns）/ MB26（动 no-flag 输出）四段协议；
* 验收：① 改前/改后 no-flag 真实台账输出 diff 为空；② 本批相关全绿 + 唯一既有红单列；③ 每钉专属红因；④ payload ≤1KB 增量。

### 4.5 留出验证（D156 触发面核对）

* **触发面核对**：(a) 不触发——无 `bugs.md` 引子族锚、无 ≥3 条独立审查重复 finding；
  (b) 不触发——本批不改门 / 校验器 / 契约判据，只给既有单源模块加机器出口与测试钉。
  命令：`git diff --name-only` = `duty-review/families.py`、`scripts/duty_signals.sh`、`tests/test_duty_bug_families.py`、日志与登记面；不落 DR4 段级锚路径族。
* **三态结论**：`不适用（未触发）`。
