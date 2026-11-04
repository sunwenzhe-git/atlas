# 评审记录：#31 运行产物指纹假漂移修复

> 评审编号：REVIEW-20261103-04
> 评审对象：`proposals/RFC-20261103-09-e2e-scripts-hash-run-artifacts.md`（对应 `duty-review/bugs.md` #31）
> 评审结论：**Approve（通过）—— 0 条阻塞项，1 条边界提醒**
> 评审方式：实施后**只读复核 + 命令重放**（评审与实施同一会话；非第三方独立评审，独立性弱于外部评审，故附原始输出）

---

## 1. 事实核查

| 核查项 | 结论 | 证据 |
|---|---|---|
| 基线 | main / `54ad6e7`，工作树干净 | `git log --oneline -3`、`git status --short` |
| 症状与实证 | `.atlas-run/results.json` 写入前后 `h1 ≠ h2`；`.last-run.json` 原本免疫 | `duty-review/bugs.md` #31 原文；`REVIEW-20261103-01` Major-2 |
| 两处清单漂移根因 | `scripts_hash` 与 `script_file_map` 各持一份排除清单 | 修复前 `aaa9dcb:scripts/e2e_console.py:146/148/181/183` |
| 单源化 | `_RUNTIME_PATH_PARTS` / `_RUNTIME_SUFFIXES` 被两函数共用 | [`e2e_console.py:132`](file:///Users/sunwenzhe/Desktop/atlas/scripts/e2e_console.py#L132)、`:153`、`:188` |
| 边界 | `.atlas-run/` 树排除；`scripts/` 根其它白名单扩展名仍计入 | `rings/e2e/reference.md` §10.1「#31 修复边界」；RFC §2.1 |
| D128 | 目标句已覆盖；仅补记边界，**未新增 D 行** | `DESIGN.md` D128 ① 行 |
| D174 | `fp = {script, block, rest, shared, app}` 表述仍成立 | `DESIGN.md` D174；`results.json` 不参与三者 |
| 钉 | 3 条断言（写入不变 / 内容再变不变 / 源脚本变仍变） | [`tests/test_e2e_console.py:853`](file:///Users/sunwenzhe/Desktop/atlas/tests/test_e2e_console.py#L853) |
| 变异 | M175（摘 `.atlas-run` ⇒ 红），四段协议 | `.atlas/runs/mutation-proof/M175.txt` |
| 计数链 | 65 自检 / 52 测试文件 / 10 校验器不变 | 未新增脚本/测试文件；`install.sh` / `gates.md` 计数行未改 |
| 状态词 | #31 → `已修·待复验`，未提前宣称出库 | `duty-review/bugs.md` #31 |
| 触发面 | (b) 命中 ⇒ 单案修复（无留出集） | RFC §4.5；观察行见 QUEUE |

## 2. 发现

1. **（边界提醒，不阻塞）** 修复只覆盖 `.atlas-run/` 目录族与已知后缀；`.atlas-run/` 之外、以白名单扩展名落盘的运行产物仍会计入指纹。RFC §5 已显式列为遗留，gates/契约侧不得引用为「判分载体均已指纹免疫」。
2. **（已核实）** `shared/gates.md` E2E 行处于 1,600 字符形态上限，本批未在该行追加文字；指纹边界落在 `rings/e2e/reference.md` §10.1（该行原本即由 gates 行指针指向），未破坏 `test_gate_registry`。

## 3. 重放命令与真实输出

```text
$ python3 -m pytest tests/test_e2e_console.py -q
（见 §4 全量与专项）

$ PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/ -q -p no:cacheprovider
1144 passed, 5 skipped in 1705.24s (0:28:25)

$ python3 scripts/atlas_check.py --fast
（源包态 10 个校验器全部 SKIP 校验器不存在；仅 write-claim / ablation 行真跑）
exit 0（不构成门证据）

$ python3 -m pytest tests/test_map_anchors.py tests/test_gate_registry.py -q
11 passed in 1.31s（本批同时重跑 `tests/test_e2e_console.py`；三项合计 39 passed）
```

## 4. 结论

* **Approve**：修复完成 #31 的落地面与钉面；三态 `单案修复（无留出集）`，不宣称闭族。
* 真实仓复验未完成 ⇒ bugs.md 状态保持 `已修·待复验`；观察行 owner / 期限已挂。
