---
title: 后端测试与 AC 提取
description: 后端/全栈 AC 对账的 extractor 配置与各测试框架的标记示例；契约正文见 shared/stack-profile.md §2。
---

# 后端测试与 AC 提取

> 本页只放**示例**；字段契约与状态语义以 `.atlas/shared/stack-profile.md` §2 与 `.atlas/shared/gates.md` 的 AC 行为准。示例里的框架名只用于说明，不代表 Atlas 核心依赖它们。

## 1. 配置

```yaml
backend_test:                     # 可选段；缺失 = 合法降级
  command: <test command>         # 收口核验命令
  test_dir: backend/tests         # 提取器扫描根（缺省 backend/tests）
  extractor: <adapter name>       # 提取器注册表名；缺省用注册表默认值
  mode: advisory                  # advisory（缺省）| enforce
  ac_marker: <adapter-specific>   # 可选；由 extractor 解释
```

- `extractor` 由 `adapters/ac/` 的注册表解析；当前内置 `pytest`。
- 未知/不可用的 extractor ⇒ AC 门报 `[UNVERIFIED]`（advisory `WARN` / enforce `FAIL`），不会伪装 PASS。
- `framework` 是 `extractor` 的兼容别名；两者同时声明且不一致 ⇒ profile 校验 FAIL。

## 2. pytest

```python
import pytest

@pytest.mark.ac("AC-PAYMENT-001", dims=["C01", "C11"])
def test_refund_rejected_when_balance_insufficient():
    ...

@pytest.mark.ac("AC-PAYMENT-002")
@pytest.mark.skip(reason="waiver: 依赖外部支付沙箱，季度回归覆盖")
def test_refund_timeout_retry():
    ...
```

- AC 挂在 `@pytest.mark.ac(...)`；`dims` 只作用于单 AC marker。
- 挂 AC 的 skip/xfail 必须带 `waiver:` 理由，否则 FAIL。
- 模块/类级 `pytestmark` 挂 AC 目前只报 WARN（不支持继承）。

## 3. Vitest / Jest（已内置，Batch C1）

```ts
/** @atlas-dims C01,C11 */
it('[AC-PAYMENT-001] 余额不足时拒绝退款', async () => {
  ...
});

it.skip('[AC-PAYMENT-002] 退款网关超时重试 waiver: 沙箱依赖，季度回归覆盖', async () => {
  ...
});
```

- AC 放测试标题的 `[AC-...]`（也可用紧邻 JSDoc `@atlas-ac AC-...`）；dims 放 `@atlas-dims`。
- `.skip` / `.todo` / `xit` / `xdescribe` / `describe.skip` ⇒ skipped + weak；`.fails` / `.skipIf` ⇒ weak；`.only` / `fit` ⇒ 扫描面 WARN。
- 挂 AC 的 skip 必须带 `waiver:`（标题或 `@atlas-waiver`），否则 FAIL。
- 文件面：`*.test.*` / `*.spec.*` / `__tests__/**`；排除 `node_modules`、构建产物与 `product/e2e/`（防 Playwright 用例串入后端通道）。
- 动态标题按静态可读部分计入并标 weak；`test.each` / `skipIf` 表格不静态展开，扫描面 WARN。

## 4. JUnit 5（已内置，Batch C2）

```java
@Test
@DisplayName("[AC-PAYMENT-001] 余额不足时拒绝退款")
@Tag("atlas-dims-C01")
@Tag("atlas-dims-C11")
void refundRejectedWhenBalanceInsufficient() { ... }

@Test
@DisplayName("[AC-PAYMENT-002] 退款网关超时重试")
@Disabled("waiver: 依赖外部支付沙箱，季度回归覆盖")
void refundTimeoutRetry() { ... }
```

- JUnit 5 的 `@Tag` 不允许逗号，dims 用多个 `atlas-dims-<维度>` tag（或项目自定义注解）。
- AC 建议放 `@DisplayName` 的 `[AC-...]`；`@Disabled` 的理由里写 `waiver:`。
- `@ParameterizedTest` / `@TestFactory` / 带占位符的 `@DisplayName` 标 weak 并进扫描面，不假装已覆盖。
- 多模块 Maven/Gradle：单 app + `test_dir: .` 时 extractor 递归盘点各模块 `src/test/java`。
- 多 backend app：同样用统一 `test_dir`（建议 `.`）做全局 AC 对账；app 级归属由 structure 事实/agent 表达，AC 门不按 app 拆分。

## 5. 外部 extractor（Batch C2，已支持）

内置 extractor 之外，项目可声明 `extractor_command`（argv 字符串，`shlex.split`、禁止 shell）：

```yaml
backend_test:
  extractor_command: java -jar tools/atlas-ac-extract.jar
  test_dir: src/test/java
  mode: advisory
```

Atlas 会追加 `--root <项目根> --test-dir <扫描根> --json`，命令向 stdout 输出：

```json
{
  "schema_version": 1,
  "input_state": "present",
  "tests": [
    {
      "name": "com.x.RefundTest.refundRejected",
      "file": "src/test/java/com/x/RefundTest.java",
      "line": 12,
      "acs": ["AC-PAYMENT-001"],
      "marker_acs": ["AC-PAYMENT-001"],
      "doc_acs": [],
      "dims": ["C01"],
      "dims_bad": [],
      "dims_shape_ok": true,
      "dims_present": true,
      "skipped": false,
      "waiver": "",
      "weak": false,
      "marker_scope_unsupported": false
    }
  ],
  "parse_errors": [],
  "scan_face": []
}
```

- 超时 120s、stdout 上限 10MB、`shell=False`；非 0 退出 / 超时 / 非法 JSON / schema 不合法 ⇒ `[EXTRACTOR]` FAIL。
- `extractor_command` 与 `extractor`/`framework` 互斥；JavaParser 只作为项目侧参考实现，不随 Atlas 分发 JVM 依赖。

### Go

结构清单由 `tests` 适配器负责（`*_test.go` + `go.mod` → `go test ./...`）；AC 对账未内置 Go extractor，请用上面的 `extractor_command` 提供归一化 JSON（标记语法由项目自定义）。

## 6. 状态速查

| 场景 | advisory | enforce |
|---|---|---|
| 无 backend/fullstack app | `N/A` | `N/A` |
| 无 PRD AC 且无测试输入 | `N/A` | `N/A` |
| apps 缺失 / 未注册 extractor | `[UNVERIFIED]` WARN | `[UNVERIFIED]` FAIL |
| 输出 schema 非法 / 命令失败 | `[EXTRACTOR]` FAIL | FAIL |
| 解析失败 | `[PARSE]` WARN | `[PARSE]` FAIL |
| 有 AC 但零挂载 | `[ZERO-COVERAGE]` WARN | FAIL |
| 扫描面非空 | `[SCAN]` WARN | `[SCAN]` WARN |
| 无主 AC / 无 waiver skip | FAIL | FAIL |

完整判据见 `.atlas/shared/gates.md` 的 AC 行。
