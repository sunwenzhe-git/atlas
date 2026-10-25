# E2E 总索引

| 用例ID | 页面 | 中文标题 | 类型 | 关联AC | 需求 | 状态 | 状态原因 | 分片 |
|---|---|---|---|---|---|---|---|---|
| E2E-HOME-001 | home | 点击后标题就绪 | smoke | AC-HOME-001 | | green | | [cases/home.md#e2e-home-001](cases/home.md#e2e-home-001) |
| E2E-HOME-002 | home | 点击后面板展开 | smoke | AC-HOME-001 | | green | | [cases/home.md#e2e-home-002](cases/home.md#e2e-home-002) |

## 页面表（页 ↔ 路由 ↔ 实现状态）

| 页面 | 路由 | 域 | 实现状态 |
|---|---|---|---|
| home | / | home | 已实现 |

## 页面 ↔ 用例

| 页面 | 断言落点用例 | 链路经过用例 |
|---|---|---|
| home | E2E-HOME-001, E2E-HOME-002 |  |
