# [必填：页 slug] 页面用例

> 一页一分片。每条用例 = `## <ID> <中文标题>` + 紧随的 ` ```atlas-case ` 块（行式键值）。
> 断言落点页 = 本页；跨页流程在 `pages:` 记全链路，绝不复制。
> `seed:` 是**可选的机器可判数据前提**（语法 `upsert <实体> <字段>=<值>`）；通道由 `stack-profile.yaml` 的 `e2e.seed.hook` 声明（缺省 = 合法降级 + 明确警告）。

## E2E-[必填：PAGE]-001 [必填：中文标题]

```atlas-case
id: E2E-[必填：PAGE]-001
intent: [必填：可证伪的一句话声明——这条用例证明什么]
pages:
  - [必填：本页 slug]
precondition:
  - [必填：已进入…；本用例自 mock 数据，不依赖其它用例]
seed:
  - upsert [可选：<实体> <字段>=<值> …；幂等 upsert、每条用例独立播种；实体×字段要与 structure 的 data-models 事实对得上]
step:
  - [必填：点击「X」（<page>-x-btn）]
expected:
  - [必填：可观测、可判定的结果；渲染后可见文案]
testid:
  - [必填：<page>-x-btn]
```
