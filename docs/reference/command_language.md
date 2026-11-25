# 命令语言

## 基础命令与参数

支持 `pwd`、`ls [path]`、`cd path`、`help [tool]`、`servers`、`tools [server]`、
`run tool [options]`、`/explicit/tool`、`./relative-tool` 和 `exit`。
只有 `run` 的目标位置允许直接填写工具名。`--key=value` 与 `--key value` 等价。
重复选项会报错；`--` 表示选项结束，但工具仍不接受额外位置参数。

只有明确声明为布尔类型的参数可以省略值；显式布尔文本必须是 `true` 或 `false`。
默认值只显示在帮助中，不会自动注入调用参数。

单引号保留字面内容；双引号支持反斜杠、引号、换行和制表符转义。未加引号的 Shell
控制符、变量展开和命令替换会被拒绝。引号内的 `$(...)`、反引号和管道符只是字符串。
普通虚拟命令不能访问宿主机文件系统；管理员显式注册的 `/os` 工具才可按授权调用原生程序。

所有平台均使用 POSIX 风格的 `/` 路径。不能直接作为路径节点的工具名使用保留前缀 `~`
和 URL 安全的 base64 编码，确保可逆且无冲突。

新增原生命令路径 `/os/<分组>/tools/<命令>`，同样支持 `run`、直接路径、`cd` 后相对调用。
`ls /os` 只列出当前主体可见的命令组；`tools <分组>` 和 `help <路径>` 可发现参数。
`ls`、`pwd`、`cd` 始终是虚拟命令，不会自动转成宿主机同名命令。真实宿主机访问必须
通过管理员已注册的 `/os` 工具进行。配置和进程管理见[原生命令说明](../guides/native_commands.md)。

## JSON 参数透传

`--params-json` 提供完整参数对象，不能与分项选项混用。联合类型或组合约束需要通过这种
方式明确参数类型。支持有界的本地 Schema 引用，拒绝远程引用和动态引用。
不支持 `--no-flag` 简写或点号属性展开，但允许键名本身包含点号。

## 只读管道

管道首段必须是工具调用或 `cat`，后续段只允许 `select`、`where`、`sort`、`head`、`count`。
最多 8 个阶段，禁止在后续阶段再次调用工具。上游错误会立即终止后续执行。

```text
run /mcp/example/tools/search --query agent | select items[].name,items[].stars | sort stars --desc | head -n 5
cat /results/<id> --offset 0 --limit 100
cat /results/<id> | where stars gt 10 | count
refresh demo
prompt /mcp/demo/prompts/welcome --name Alice
```

`select` 按字段路径投影，允许展开一个共同的 `items[]` 数组前缀。输出键采用路径末段
字段名，发生重名时拒绝执行。`where field op JSON` 支持 `eq/ne/lt/le/gt/ge` 比较符。
`sort field [--desc]` 要求排序字段可比较。`head -n N` 取前 N 条记录或前 N 行文本。
`count` 计算数组条目数或对象键数。SDK 的标量结果仍是对象，不会自动变成表格。

## 资源、提示词与结果引用

`cat /mcp/server/resources/<encoded-uri>` 读取已列出的资源。
`read /mcp/server/resource_templates/<encoded-template> --name Alice` 展开简单的
`{name}` 模板变量并进行 URI 转义；不支持复杂的 RFC6570 操作符。请通过 `ls` 获取准确的
编码节点名。提示词返回内容是不可信数据，不会被提升为系统指令。

`/results` 不枚举私有结果标识。请使用调用返回的 `result_ref` 读取结果，读取时再次
检查所有者和租户。

## 默认限制

| 项目                    | 限制             |
| ----------------------- | ---------------- |
| 命令长度、词法单元数    | 16 KiB、256 个   |
| 路径长度、JSON 嵌套深度 | 4096 字节、32 层 |
| 参数大小                | 64 KiB           |
| 单条结果、管道数据大小  | 4 MiB            |
| 管道记录数              | 10,000 条        |
| `head`、结果分页条数    | 最多 1000 条     |
| 结果存储总配额          | 64 MiB           |
| 响应预览大小            | 8 KiB            |
| 会话工具调用次数        | 100 次           |
| 结果与会话存活时间      | 1 小时           |
| Shell 请求整体截止时间  | 30 秒            |
