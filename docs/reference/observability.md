# 监控、指标和追踪

API 默认在自己的 CollectorRegistry 中收集指标，多身份共用一个收集器；多个应用
实例互不污染。核心模块依赖无第三方包的 Telemetry 接口，默认无操作，因此纯命令行
运行不强制安装 Prometheus/OTel。应用也可向 ShellService 注入 PrometheusTelemetry。

| 指标                                  | 类型   | 标签                 | 统计口径                                       |
| ------------------------------------- | ------ | -------------------- | ---------------------------------------------- |
| mvs_shell_requests_total              | 计数器 | status, command      | 每次 ShellService.execute 完成或取消计一次     |
| mvs_shell_duration_seconds            | 直方图 | command              | 虚拟命令请求完整耗时，包含会话锁等待           |
| mvs_tool_calls_total                  | 计数器 | server, tool, status | 已进入 tools/call 的尝试，包含超时、取消和失败 |
| mvs_tool_duration_seconds             | 直方图 | server, tool         | 已发出调用的总耗时，包含信号量排队、结果规范化 |
| mvs_native_command_calls_total        | 计数器 | server, tool, status | 原生命令后端执行尝试，不混入 MCP 调用          |
| mvs_native_command_duration_seconds   | 直方图 | server, tool         | 原生命令后端耗时，包含排队与清理               |
| mvs_registry_refresh_total            | 计数器 | server, status       | 每次工具列表刷新结果，包含启动、手动、TTL 刷新 |
| mvs_registry_refresh_duration_seconds | 直方图 | server               | 发现刷新耗时，包含刷新锁等待                   |
| mvs_result_bytes_total                | 计数器 | server               | 成功持久化的 UTF-8 结果封装与附件文件字节累计  |
| mvs_policy_denials_total              | 计数器 | server, reason       | 显式访问被拒绝，不计普通目录过滤               |

工具状态 `status` 分别使用 `success/error/timeout/cancelled` 表示成功、错误、超时和取消。
工具业务 `is_error`、协议异常和输出校验失败都归为 `error`；未发起 MCP 调用的语法、
参数或授权失败不增加工具调用数。虚拟命令状态使用 `success/error/approval_required/cancelled`，
分别表示成功、错误、需要审批和取消。结果字节指标是累计写入量，不是当前占用量；
过期删除不使计数器减少，重复读取也不增加，管道新结果以 `server=unknown` 统计。
资源/提示词访问不伪装为 tools/call 指标，但其结果写入和 Shell 请求仍统计。
原生命令使用独立计数器，包含后端参数检查和启动失败；状态同样区分成功、错误、超时和取消。

命令标签 `command` 使用固定枚举，未解析命令统一为 `unknown`；服务器标签 `server`
仅允许管理员配置项，其余统一为 `unknown`；拒绝原因 `reason` 为固定枚举：
server_not_granted、tool_not_allowed、
approval_required、authorization_changed、catalog_not_allowed、result_not_owned、admin_required、other。
工具标签 `tool` 来自已注册元数据，不直接取任意用户输入。指标不使用主体、租户、会话、
请求、查询内容、结果标识或原始错误消息作标签。服务器的工具目录本身应可信并保持稳定。

拒绝不可见路径仍公开返回 NOT_FOUND，不因指标改变 API 错误语义。访问不存在/过期结果
与真正跨所有者或租户访问分别处理，只有后者增加 `result_not_owned`；管理员指标不泄露
被访问的结果 ID。权限判定在等待执行队列后再次发生，撤权拒绝计 authorization_changed。

## 获取指标

启动 examples/api_server.py，使用管理员 Bearer Token 请求 GET /metrics。未认证为
401；普通用户为 403。返回 Prometheus 文本指标格式。

```yaml
scrape_configs:
  - job_name: mvs
    scrape_interval: 15s
    metrics_path: /metrics
    static_configs:
      - targets: ["127.0.0.1:8080"]
    authorization:
      type: Bearer
      credentials_file: /run/secrets/mvs_metrics_token
```

示例 PromQL：

```promql
sum by (command, status) (rate(mvs_shell_requests_total[5m]))
histogram_quantile(0.95, sum by (le, server, tool) (rate(mvs_tool_duration_seconds_bucket[5m])))
sum by (server, tool) (rate(mvs_tool_calls_total{status="error"}[5m]))
sum by (server) (increase(mvs_registry_refresh_total{status="error"}[15m]))
sum by (server) (rate(mvs_result_bytes_total[5m]))
sum by (server, reason) (increase(mvs_policy_denials_total[15m]))
```

## OpenTelemetry 追踪

API 的 `mvs.api.execute` 追踪片段包含 `mvs.request_id`、`mvs.status`。下层
`mvs.shell.execute → mvs.tool.invoke` 嵌套在同一条追踪中；注册表使用
`mvs.registry.refresh`。工具调用还会进入 SDK 自带的协议追踪片段。
示例应用安装 ConsoleSpanExporter，集成方可替换为 OTLP 导出器。不记录原始参数、
工具返回值或凭证。当前收集器运行在进程内；多个工作进程需分别采集后在 Prometheus 聚合，
没有启用 prometheus_client 的多进程模式。

测试覆盖真实 stdio、正常结果、超时/取消、发现失败、跨用户结果拒绝、目录过滤不计拒绝、
标签内容限制、多个收集器隔离，以及 API→虚拟命令→工具的追踪关联。
