# MCP Virtual Shell（MVS）

**面向AI Agent的统一工具入口与管理平台。** 当前版本为 **0.0.1**，支持Python 3.12及以上。

模型通过`virtual_shell(command)`按需发现和调用工具：`ls`查看目录，`help`读取参数，
`run`执行获授权的调用。MCP服务位于`/mcp`，管理员注册的操作系统命令位于`/os`。
调用共用Schema校验、权限、审批、并发、超时、审计和结果引用。

## 安装

从PyPI安装包含中文可视化后台的工具：

```bash
uv tool install --python 3.12 'mcp-virtual-shell[console]==0.0.1'
mvs init
mvs token show
mvs serve --open
```

后台默认地址为`http://127.0.0.1:8080`，使用本机初始化生成的管理员令牌登录。
发布wheel已包含React/shadcn/ui页面，最终用户不需要Node.js。
如果包尚未公开发布，请从项目提供的安装包选择本地wheel安装。

使用已有Python虚拟环境时也可运行：

```bash
python -m pip install 'mcp-virtual-shell[console]==0.0.1'
```

## 功能

- 通过官方MCP SDK v2接入stdio或Streamable HTTP服务。
- 注册Linux、Windows、macOS固定程序和脚本，限制参数、目录、输出与执行资源。
- 中文后台管理服务、工具白名单、用户、角色、凭证、模型、审批与配置历史。
- 结果按主体和租户隔离，支持有界预览、结果引用、分页和纯数据管道。
- 可选Redis会话/限流、PostgreSQL共享控制面与结果、S3对象内容。
- Prometheus指标、OpenTelemetry追踪、加密备份及恢复。

在后台工作台运行内置演示，无需模型API密钥：

```text
ls /mcp/demo/tools
help /mcp/demo/tools/add
run /mcp/demo/tools/add --a 12 --b 30
```

## 可选依赖

| 依赖组       | 用途                                  |
| ------------ | ------------------------------------- |
| `console`    | 管理后台、HTTP服务和模型客户端        |
| `api`        | 嵌入式FastAPI工具执行接口与可观测性   |
| `benchmark`  | 真实模型工具入口实验客户端            |
| `production` | Redis、PostgreSQL、S3和系统钥匙串适配 |

需要共享存储时安装`mcp-virtual-shell[console,production]==0.0.1`。
外部服务、模型密钥和Docker运行时需按部署场景另行配置。

MVS只执行管理员授权的工具，不接受任意操作系统Shell源码。版本0.0.1仍有跨平台服务安装、
真实第三方OAuth、长期压力和故障恢复等待验收项目，详见仓库文档。

## 文档与源码

- [项目首页与功能说明](https://github.com/TheNorthS/MVS)
- [安装与管理教程](https://github.com/TheNorthS/MVS/blob/main/docs/guides/user_installation.md)
- [Linux部署与模型接入](https://github.com/TheNorthS/MVS/blob/main/docs/guides/linux_deployment.md)
- [完整文档](https://github.com/TheNorthS/MVS/blob/main/docs/README.md)
- [问题反馈](https://github.com/TheNorthS/MVS/issues)

项目使用[MIT许可证](https://github.com/TheNorthS/MVS/blob/main/LICENSE)。
