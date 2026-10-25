# home 页面用例

## E2E-HOME-001 点击后标题就绪

```atlas-case
id: E2E-HOME-001
intent: 点击主按钮后标题文案变为「验收靶场」(改态前为「加载中…」)
pages:
  - home
precondition:
  - 已打开首页
step:
  - goto /
  - click home-cta-btn
expected:
  - text home-title 验收靶场
  - visible home-title
testid:
  - home-title
  - home-cta-btn
```

## E2E-HOME-002 点击后面板展开

```atlas-case
id: E2E-HOME-002
intent: 点击主按钮后面板展开(改态前隐藏)
pages:
  - home
precondition:
  - 已打开首页
step:
  - goto /
  - click home-cta-btn
expected:
  - visible home-panel
testid:
  - home-cta-btn
  - home-panel
```
