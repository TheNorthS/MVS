# 架构与接口契约

当前0.0.1包含`management/`控制面与内置`web/`静态资源。`mvs init`建立用户私有实例，
`mvs serve`同时提供shadcn/ui控制台、管理员API和既有工具执行API。控制状态独立存入SQLite，
热切换通过ManagedRuntime保护请求和配置代际；原`create_app`与YAML部署入口继续兼容。
后台中的模型任务使用`mvs.agent`通过同一执行API调用工具，不绕过Policy。

2026-11-23 起增加原生命令后端：MCP 使用 `/mcp`，管理员配置的操作系统命令使用 `/os`。
两者共用 Registry、VFS、SchemaAdapter、Policy、执行编排、审计和 ResultStorage。
`ToolDescriptor.backend` 来自可信服务配置而非服务器注解；原生命令的完整配置哈希参与版本。
`ClientManager` 兼容原有接口，根据 transport 创建 MCP 连接或 NativeConnection。
原生实现位于 `infrastructure/native/`，没有 MCP SDK 依赖。详细契约见[原生命令说明](../guides/native_commands.md)。

`ShellService.execute(command, SessionContext) -> ShellResponse` 是命令行和 HTTP API
共用的执行入口。解析器生成不可变的抽象语法树（AST），并保留选项顺序及其在原始命令中的
位置。注册表（Registry）是工具元数据的唯一来源；虚拟文件系统（VFS）接收经过权限过滤、
与原数据分离的快照。SchemaAdapter 负责参数转换和原始 JSON Schema 校验，权限策略要求
同时具备服务器访问授权和工具白名单。执行器获得并发信号量后，再次检查版本与权限。
MVS 不自动重试工具调用；超时返回 `TIMEOUT_UNCERTAIN`，表示服务端可能已经执行。

## SDK 隔离与连接管理

生产代码中，官方 MCP SDK 的导入集中在 `src/mvs/infrastructure/mcp/`。
客户端上下文由独立任务负责进入和退出，确保 AnyIO 取消作用域使用正确；关闭时按照
注册顺序的逆序释放连接。协议版本协商交给官方 Client，不自行实现握手。

工具发现最多读取 100 页、10,000 个工具和 4 MiB 元数据。显式刷新使用 SDK 的
`cache_mode="refresh"`。每个服务器的刷新锁保证刷新串行执行，新字典构建完成后原子发布。
发现失败只把对应服务器标记为离线。基于存活时间（TTL）的恢复可以重新建立连接，但不会
重放此前失败的工具调用。

## 工具、资源与身份边界

工具、资源、资源模板和提示词使用独立的目录、协议方法和授权白名单。工具快照与资源目录
分别原子发布，不构成跨目录事务。每个 API 身份拥有独立的客户端和注册表，只连接获准访问
的服务器。下游支持管理员配置的凭证引用，以及按用户保存的OAuth凭证；真实提供方仍需验收。

## 结果与会话存储

ResultStorage 是可注入的存储协议，已提供PostgreSQL与S3外部后端。默认 ResultStore 使用 SQLite
保存元数据，并用私有对象文件保存内容。元数据包括 UUID4 标识、租户、所有者、来源、
创建时间、过期时间、MIME 类型、字节数和内容哈希。

对象路径只由系统生成的标识构造，读取前通过 SQL 检查所有权。可信适配器可以调用
`get_asset` 读取经过授权的附件；模型响应只包含引用，不直接携带二进制内容的 base64。
同一主体、同一租户可以跨会话读取未过期结果；会话默认保存在内存，也可通过Redis跨实例共享。

## 响应、审计与监控

ShellResponse 包含请求标识、会话标识，以及 `status`、`exit_code`、`stdout`、`stderr`、
`data`、`result_ref`、`truncated`、`duration_ms` 和 `error`。标量工具结果保留官方 SDK 的
`{"result": value}` 结构，标准输出则显示标量值。API 和命令行都不能绕过权限策略。

审计不记录原始命令或参数值，只记录请求标识、大小、版本、耗时和错误类别。Shell 请求
具有 30 秒整体截止时间，API 还可提供 OpenTelemetry 追踪和需要认证的指标接口。

Telemetry 是无第三方依赖、可注入的领域观察接口。注册表、执行器、结果存储和
ShellService 发出完成事件，可选的 PrometheusTelemetry 适配器记录有界标签指标和嵌套
追踪片段。每个 API 应用拥有独立指标收集器，由该应用中的授权身份共用。安装追踪组件后，
审计中的 `trace_id` 会关联实际追踪。统计口径见[监控说明](observability.md)。

## 真实模型实验

真实模型基准由 Responses 接口适配器、固定只读任务集、三个面向模型的入口和有轮次上限
的对话循环组成。三个入口共用 ShellService 执行链和真实的进程内 MCP 服务器。
每组实验保存服务端用量、模型输出、实际工具调用以及预期答案核对结果，便于独立审查。
方法与限制见[模型实验说明](../research/model_benchmark.md)。
