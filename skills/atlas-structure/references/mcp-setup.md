# GitNexus / ABCoder 接入（可选）

两者只是工具选择，不是 Atlas 的依赖。没有它们也能开户——直接读源码与测试即可。

## GitNexus

从仓库构建代码知识图谱，用来看模块边界、执行流、依赖关系与影响面。

```bash
npx gitnexus analyze      # 建索引（产物在 .gitnexus/）
npx gitnexus status       # 查看状态
npx -y gitnexus mcp       # MCP server 命令
```

常用工具：

| 工具 | 用途 |
|---|---|
| `gitnexus_query` | 按概念找执行流 / 功能区 |
| `gitnexus_context` | 看符号的调用者、被调用者、引用 |
| `gitnexus_impact` | 改符号前看影响面 |
| `gitnexus_detect_changes` | 收尾前核对改动符号与受影响流 |
| `gitnexus_cypher` | 直接图查询 |

## ABCoder

把代码解析成 UniAST，给出精确的包 / 文件 / 节点结构。

```bash
go install github.com/cloudwego/abcoder@latest
abcoder parse /absolute/path/to/package --lang typescript --name package-name --output ~/abcoder-asts
abcoder mcp ~/abcoder-asts
```

常用工具：

| 工具 | 用途 |
|---|---|
| `list_repos` | 列出已解析仓库 |
| `get_repo_structure` | 看包与文件 |
| `get_package_structure` | 看包内节点 |
| `get_file_structure` | 看函数 / 类 / 类型 / 签名 |
| `get_ast_node` | 取代码、依赖、引用、实现 |

## 纪律

- 图谱输出只用于**定位**；写进规范的规则必须回到源码 / 测试核对。
- 不要在规范里写「依赖某 MCP」；工具缺席时规范仍然成立。
- 索引会陈旧：大改代码后重跑 `analyze`，或直接在结论里标注「未复核」。
