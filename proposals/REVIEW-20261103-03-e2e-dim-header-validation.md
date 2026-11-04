# 评审记录：E2E 第 4 列按表头名校验

> 评审编号：REVIEW-20261103-03
> 评审对象：`proposals/RFC-20261103-08-e2e-dim-header-validation.md`
> 评审结论：**Approve（通过）—— 0 条阻塞项，2 条不阻塞修整建议**
> 评审方式：实施后**只读复核 + 命令重放**（评审与实施同一会话；非第三方独立评审，独立性弱于外部评审，故逐条附原始输出供维护者复核）

---

## 1. 事实核查（逐条绑定仓内编号）

| 核查项 | 结论 | 证据（仓内真实位置） |
|---|---|---|
| 基线 | main / `aaa9dcb`，工作树干净 | `git branch --show-current`、`git status --short`、`git log --oneline -5` |
| Batch A 不重做 | D153 已落地，解析单源在用 | `DESIGN.md` D153 行（2026-10-26，`ec9bf18`）；`validators/validate_e2e_index.py` 调用 `parse_dims_cell` |
| 缺口定位 | 旧实现为**第 4 格位置式正则**，表头不参与判据 | 改动前 `aaa9dcb:validators/validate_e2e_index.py:665`；RFC §1.2 复算命中 `[('AC-HOME-001', ' C01-C02 ')]` |
| 列定位路径 | 走 `_support/ac_coverage.iter_md_tables` + 表头名索引，**未迁** `tables()` | [`validate_e2e_index.py:358`](file:///Users/sunwenzhe/Desktop/atlas/validators/validate_e2e_index.py#L358)、`:370`、`:373`；`tables()` 仍只服务索引 / 页面表（`:225` / `:371` / `:529` 旧位） |
| 合法表头 | 逐字 `适用覆盖维度`，模块常量固定 | [`validate_e2e_index.py:94`](file:///Users/sunwenzhe/Desktop/atlas/validators/validate_e2e_index.py#L94) |
| 逐表独立 | 单表表头不符 ⇒ 跳过该表；合法表照常 | [`validate_e2e_index.py:370-377`](file:///Users/sunwenzhe/Desktop/atlas/validators/validate_e2e_index.py#L370-L377) |
| N/A 语义未改 | `atlas_check.py` 子项 N/A 语义（D153）原样 | `scripts/atlas_check.py` 未出现在 diff；`atlas_check --fast` = exit 0（源包态 10 校验器全 `SKIP 校验器不存在`，不构成门证据） |
| D130 / M131 保持绿 | 合法 4 列表头语料结论不变 | `tests/test_validators.py::test_e2e_index_coverage_dimensions_pass_and_warn` 通过；`DESIGN.md` D130 行未改动 |
| 新增钉 | 3 类断言 + golden 4 例 | [`tests/test_validators.py:1503`](file:///Users/sunwenzhe/Desktop/atlas/tests/test_validators.py#L1503)、`tests/fixtures/e2e_coverage_dims_golden.json` → `e2e_dim_header_cases` |
| 变异编号 | M174（仓内实际最大为 M173，未按过时 M131 续号） | `.atlas/runs/mutation-proof/M174.txt`；`README.md:381` / `docs/innovations/mutation-proving.md:22` 为过时文本，未作为依据 |
| 范围纪律 | 无 weak-only 代码；`prototype-pass` 不动 | diff 无 weak / prototype 相关改动；RFC §5 明示范围外 |
| 计数链 | 10 校验器 / 52 测试文件 / 65 自检不变 | 未新增校验器、未新增测试文件；`shared/gates.md` 计数行未改；`test_map_anchors` 8 passed |
| 契约同步 | §5.2 增加「表头名逐字」与逐表 N/A | [`rings/e2e/reference.md:336`](file:///Users/sunwenzhe/Desktop/atlas/rings/e2e/reference.md#L336) |
| 触发面 | (a) 否；(b) 保守命中 ⇒ 三态 = 单案修复（无留出集） | RFC §4.5 原始输出；观察行 = [`QUEUE.md:32`](file:///Users/sunwenzhe/Desktop/atlas/duty-review/QUEUE.md#L32)，owner / 期限已写 |

## 2. 发现

1. **（已核实）全量套件实跑已补齐**：RFC §4.1 已用最终全量输出替换占位（`1144 passed, 5 skipped`，见 §4 重放）。
2. **（不阻塞）`tests/test_atlas_verify_playground.py` 环境耗时**：该用例在本机单跑 >14 分钟（内部多次装配 + 跑装配副本测试），非本批改动引入；评审时以最终全量输出为准，若因环境超时需在结案说明单列，不得记为红。

## 3. 方案审查

* **路径选择合理**：`tables()` 是本文件私有且仅服务索引 / 页面表；D153 已把「表切分 + 单元格解析」收敛到 `_support/ac_coverage.py`，本批沿用同源并复用同一奇偶钉（`tests/test_shared_kernel.py` 15 passed），避免第二条 parser。RFC §2.2 备选 E 已记录否定理由。
* **行为边界清晰**：合法表头零变化；错表头从「按第 4 格吸收」变为「按未声明跳过」。未新增 WARN 文本，不制造新噪声。
* **未越界**：weak-only WARN、`prototype-pass`、#31 均未触碰；RFC §5 显式列出。

## 4. 重放命令与真实输出

```text
$ python3 -m pytest tests/test_validators.py -q
183 passed in 1.44s

$ python3 -m pytest tests/test_map_anchors.py -q
8 passed in 0.14s

$ python3 -m pytest tests/test_gate_registry.py tests/test_shared_kernel.py -q
15 passed in 0.12s

$ python3 scripts/atlas_check.py --fast
（源包态 10 个校验器全部 SKIP 校验器不存在；仅 write-claim / ablation 行真跑）
exit 0（不构成门证据）

$ PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/ -q -p no:cacheprovider
1144 passed, 5 skipped in 1715.33s (0:28:35)
```

## 5. 结论

* **Approve**：RFC 与实现一致，契约 / 测试 / 变异 / 计数 / QUEUE 均闭合；三态 `单案修复（无留出集）` 成立，不宣称闭族。
* 观察行已挂 owner + 补验期限；后续案（weak-only WARN）明确留待另批。
