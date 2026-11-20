# 拆分与任务卡

默认单 agent 跑完整循环。需要留痕时，可以建执行层任务卡，但 skill 不依赖任何平台、CLI 或并行 worker。

## 拆分原则

按**真实所有权边界**拆：

- 一个包有独立约定 ⇒ 一个工作单元；
- 同一个包里前端 / 后端 / CLI / worker / 共享库规则不同 ⇒ 按层拆；
- 跨包但无单一归属的横切模式 ⇒ 一份横切规范。

不要为了「看起来完整」硬拆。小库一次跑完胜过五张任务卡。

## 任务卡写法

```bash
atlas workflow plan --unit SPEC-<scope> \
  --requirement <需求说明文件> \
  --paths <本次要覆盖的真实路径 glob...>
```

需求卡正文建议包含：

```markdown
# 为 <package-or-layer> 开户规范

## 目标
为 <scope> 写出项目专属的 .atlas/spec/ 规范。

## 范围
- 规范目录：
- 要读的源码目录：
- 要读的测试：
- 不在范围：

## 架构结论
（来自 repository-analysis 的具体发现）

## 要新建 / 更新的文件
- .atlas/spec/structure/tour.md
- .atlas/spec/structure/domains/<domain>.md
- .atlas/spec/conventions/<topic>.md

## 纪律
- 规范适配真实代码库，不保留不适用模板。
- 规则必须带真实文件路径 / 符号。
- 不改业务源码（除非任务明确要求）。
- paths: 必须能被真实路径命中，禁止 ** 逃逸。
```

## 验收

- 规范含真实例子与反模式；
- 无占位符；
- 导航与文件集一致；
- `python3 .atlas/scripts/atlas_check.py --fast` 全绿；
- 用真实路径跑一次 `atlas workflow dispatch --paths ...`，注入面正确。

## 可选并行

宿主支持子代理时，可让辅助读独立包或做校验；主 agent 负责整合与最终质量。辅助任务的边界要写清：只读研究 / 只写互不重叠的 spec 目录 / 只做校验。不要把宿主专有命令写进 skill。
