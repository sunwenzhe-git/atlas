# 规范写作

Atlas 的 spec 是给未来 agent 的**本仓工作指引**，不是通用项目教科书。

## 从证据出发

每条重要规则至少有一个背书：

- 展示推荐模式的源码文件；
- 展示预期行为的测试；
- 定义约定的项目文档；
- 多个文件里重复出现的模式。

用短片段帮助理解即可，优先写「文件路径 + 符号 / 行为」。

## 文件结构

- 导航对齐项目：`.atlas/spec/structure/tour.md` 指向域级导航与事实文档。
- 一个主题开发者会独立查找 ⇒ 单独文件；重复同一条规则 ⇒ 合并。
- 不适用于本仓的模板段落直接删除。
- 模板没覆盖但本仓重要的模式，新增文件。

## `paths:` 规则（决定注入是否精准）

- 只有**导航**（`tour.md`、`domains/*.md`）与**约定**（`conventions/*.md`）带 `paths:`。
- 每条 glob 必须能被真实路径命中，例如 `apps/web/**`、`packages/ui/src/**/*.tsx`。
- **禁止**用 `**` 逃逸；唯一例外是 `tour.md` 的全局入口。
- 域规范只写本域 globs；不要把整库写进一个域。
- 新增约定前先确认：没有它，agent 会犯什么具体错误？写不出来就别加。

## 正文结构

好的规范段落包含：

- 什么时候适用；
- 本仓要照做的模式；
- 支撑它的源码 / 测试文件；
- 常见错误与反模式；
- 可复现的验证命令（若确实稳定）。

避免：

- 占位句、空标题；
- 通用框架建议；
- 只在一个宿主可用的工具说明；
- 大段复制代码；
- 基于一次偶然实现的「规则」。

## 示例

```markdown
## 命令处理

命令处理器要把参数解析、校验、副作用分开。本仓模式：

- 在命令边界解析参数；
- 先把原始输入转成类型化选项，再进核心逻辑；
- 文件写入留在命令/服务层，不要塞进模板助手。

参考：
- `packages/cli/src/commands/example.ts`
- `packages/cli/test/commands/example.test.ts`

避免把未校验的 `process.argv` / 配置对象直接传进共享 helper。
```

## 交付前自检

```bash
grep -rn "TODO\|待填\|placeholder\|<%" .atlas/spec
python3 .atlas/scripts/refresh_structure.py --root . --chain
python3 .atlas/scripts/atlas_check.py --fast
```

再确认：链接可达、导航与文件集一致、`paths:` 能命中真实文件。
