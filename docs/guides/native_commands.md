# 原生操作系统命令：注册、暴露与管理

本功能根据 2026-11-23 的新需求扩展原始规范：MVS 除了 MCP 工具，也能调用管理员明确
注册的 Linux、Windows、macOS 原生命令。入口为 **`/os/<分组>/tools/<工具名>`**。
模型不获得交互式终端，也不能自行指定程序路径、启动环境或动态执行源码。

## 1. 快速运行

仓库提供两项真实只读命令：hostname（主机名）和 identity（系统身份）。先检查配置中的
路径是否对应当前主机，再运行：

```bash
uv run mvs --config configs/servers.native.example.yaml repl
```

在 MVS 提示符中输入：

```text
ls /os
ls /os/host/tools
help /os/host/tools/hostname
run /os/host/tools/hostname
/os/host/tools/identity
cd /os/host/tools
./hostname
```

一次性执行可用：

```bash
uv run mvs --config configs/servers.native.example.yaml --json exec -- 'run /os/host/tools/hostname'
```

配置自动选择 `linux`、`win32` 或 `darwin` 实现。平台键对应 Python 的 `sys.platform`，
不根据模型请求切换系统。Windows 上不会运行 Linux 命令；未配置本平台实现的工具不会
出现在目录中。程序不存在时返回 `COMMAND_UNAVAILABLE`，不会从 PATH 猜测其他程序。

## 2. MCP 与原生命令可以共存

在同一 YAML 的 `servers` 列表中加入普通 MCP 服务和 `transport: native` 分组即可。
为保持已有授权接口，原生命令组也使用全局唯一的 `id`；同一个 id 不能同时注册为 MCP 和
原生命令组。MCP 工具仍在 `/mcp`，原生命令只在 `/os`，不会创建绕过权限的路径别名。

原生分组的 `allowed_tools` 默认空，必须显式授权。`enabled: false` 可以禁用整个分组，
单条命令也有 `enabled`。`approval_tools` 仍只返回需要审批，不会自动完成审批执行。
API 继续使用主体/租户的服务器授权；部署时把组 ID 加入 `MVS_ALLOWED_SERVERS` 并重启。

## 3. 参数化命令示例

下面把 Linux 的 `ls` 注册为逻辑工具 `list_directory`。管理员指定程序、工作目录、固定
选项和允许的路径根目录；模型只提供 `path` 字符串。

```yaml
servers:
  - id: files
    transport: native
    enabled: true
    allowed_tools: [list_directory]
    max_concurrency: 2
    call_timeout_seconds: 15
    native_commands:
      - name: list_directory
        description: 列出允许目录内的文件，不修改文件
        enabled: true
        timeout_seconds: 5
        max_output_bytes: 262144
        input_schema:
          type: object
          properties:
            path:
              type: string
              maxLength: 1024
          required: [path]
          additionalProperties: false
        path_roots:
          path: [/srv/data]
        implementations:
          linux:
            executable: /bin/ls
            cwd: /srv/data
            argv: ["-la", "--", { param: path }]
            encoding: utf-8
```

调用：

```text
run /os/files/tools/list_directory --path .
run /os/files/tools/list_directory --params-json '{"path":"reports"}'
```

`{param: path}` 是 YAML 参数绑定对象，不能写成字符串 `"{path}"` 并期待模板替换。
每个绑定生成**一个 argv 元素**，空格、引号、分号、反引号和 `$()` 不会被 Shell 解释。
数组和对象参数以 JSON 编码传入一个参数，不会被展开为任意选项列表。

当前动态 argv 参数必须全部声明为 required；每个 Schema 属性都必须有绑定，不静默丢弃。
布尔、数值转换继续由 SchemaAdapter 完成。字符串若以 `-` 开头默认拒绝，避免用户值变成
目标程序选项；确实需要该值时，管理员可配置 `allow_option_values: [参数名]`，同时审查
目标工具是否支持固定 `--` 参数终止符。负数数值参数不受这个字符串规则影响。

路径约束是可选但明确的：带 `path_roots` 的字符串会相对于固定 `cwd` 解析成绝对路径，
通过 `..` 或符号链接指向根目录之外会被拒绝。根目录必须是当前平台的绝对路径；多个系统
路径不同的路径工具建议分别配置分组。工作目录是进程启动目录，**不是文件系统沙箱**。
目标程序仍以 MVS 账户权限运行，路径检查也不能消除文件系统被并发替换的竞态。

## 4. 平台与脚本

直接程序必须使用绝对路径，Windows 入口必须是 `.exe`，不能隐式启动 `.bat`/`.cmd`。
`dir`、`Get-Service` 等属于命令解释器内部功能时，先写成管理员固定脚本，再注册脚本。
已知 Shell 禁止模型绑定任意 `-c`/`-Command` 源码；PowerShell 只接受固定 `-File` 模式。
固定 Bash 脚本模式为 `/bin/bash` 加绝对脚本路径，再附加类型化参数，不允许模型选择脚本。

Windows 示例：仓库附带 `examples/native/system_info.ps1`，读取系统版本、主机名和进程数。
将脚本安装到管理员控制的目录后注册：

```yaml
servers:
  - id: wininfo
    transport: native
    allowed_tools: [system_info]
    native_commands:
      - name: system_info
        description: 使用固定 PowerShell 脚本读取系统信息
        input_schema:
          type: object
          additionalProperties: false
        implementations:
          win32:
            executable: C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe
            cwd: C:\mvs
            argv: ["-NoProfile", "-NonInteractive", "-File", "C:\mvs\scripts\system_info.ps1"]
            encoding: utf-8
```

按组织策略部署或签名脚本，不自动降低系统执行策略。管理员脚本不能自行把传入值再次交给
`eval`、`Invoke-Expression` 或其他动态源码接口。通用解释器、Git 插件、环境变量和程序
自带的扩展能力都属于管理员需要审查的能力边界；固定 argv 不能证明任意程序无副作用。

macOS 使用 `darwin` 键，例如 `/usr/bin/id`、`/bin/hostname`。配置方式和 Linux 相同，
但不能假定两者系统工具支持相同选项，应分别编写 argv。

## 5. 执行、环境和结果

直接调用采用 `asyncio.create_subprocess_exec`，不会调用 `subprocess(shell=True)`。
stdin 固定关闭，不提供交互输入或伪终端。大部分宿主环境不会继承，只保留系统必需的
SystemRoot/WINDIR/TEMP/TMP 与语言设置。所需环境变量由每个平台实现的 `env_refs`
显式绑定，例如 `env_refs: {SERVICE_TOKEN: MVS_SERVICE_TOKEN}`。凭证不要放进 argv。

进程总并发受分组 `max_concurrency` 限制，排队后再次验证权限和工具 revision。
原生命令的完整绑定哈希参与 revision，包括程序、argv、Schema 与限制。配置变更需重启
服务，`refresh` 只重建已加载定义，不会从模型命令读取任意 YAML。

超时取命令 `timeout_seconds`、分组 `call_timeout_seconds`、Shell 剩余截止时间的约束。
stdout 和 stderr **合计**超过 `max_output_bytes` 时终止进程，返回 `RESULT_TOO_LARGE`。
最大可配置输出为 1 MiB，默认 256 KiB；该限制不是进程内存或 CPU 限额。
输出按配置 `encoding` 解码，Windows 示例的 cp936 应按实际系统代码页调整。

结果 `data` 包含：

```json
{
  "stdout": "...",
  "stderr": "",
  "exit_code": 0,
  "platform": "linux",
  "output_bytes": 123
}
```

标准输出和错误输出保存在 owner/tenant 绑定的结果引用中，反馈仍受预览上限约束。
输出按不可信数据处理。退出码非零时响应状态为 error，错误码为 `COMMAND_FAILED`，
保留真实退出码、输出和结果引用；管道立即停止后续转换。程序输出 JSON 时仍保存在
`data.stdout` 字符串中，不自动猜测输出格式。

超时返回 `TIMEOUT_UNCERTAIN`：终止进程不能撤销已发生的文件、网络或业务副作用。
程序不可用返回 `COMMAND_UNAVAILABLE`；清理管道未及时结束返回 `COMMAND_CLEANUP_FAILED`。
系统调用使用当前 MVS 服务账户，不自行提权或切换用户。

## 6. 进程生命周期与监控

- Windows：先挂起创建进程，加入带关闭即终止策略的 Job 对象，再恢复线程；取消、超时、
  输出超限和正常结束时关闭 Job，清理关联的后代，且不弹出控制台窗口。
- Linux/macOS：启动独立会话/进程组，结束时终止同组后代并排空管道。可信程序若主动
  `setsid` 脱离进程组，不在此清理保证内；这不是针对恶意程序的容器隔离。
- 服务关闭会取消仍在运行的原生命令。不会自动重试，也不会因错误码把另一个程序作为备选。

复用现有 Shell、结果存储、权限与刷新指标，并单独提供：

| 指标                                | 标签                 |
| ----------------------------------- | -------------------- |
| mvs_native_command_calls_total      | server, tool, status |
| mvs_native_command_duration_seconds | server, tool         |

原生命令不计入 MCP 的 `mvs_tool_calls_total`。原生指标统计进入原生后端的执行尝试，
其中可包含参数路径检查、启动失败；status 为 success/error/timeout/cancelled。
审计增加 `backend=native`，仍不记录 argv 原值或凭证。API/Agent 使用方式与 MCP 工具一致。

## 7. 范围与验证

该功能在运行 MVS 的本机执行。远程 Linux/Windows/macOS 主机需分别部署 MVS 或接入
对应远程 MCP；不会隐式添加 SSH、WinRM 或跨主机登录能力。

Windows 已实际验证原生程序、混合调用、Schema、权限、字面控制符、环境隔离、非零退出码、
输出上限、超时/取消、后代清理、API、管道和结果保存。Ubuntu/WSL 已验证真实 hostname/id、
参数与环境、输出超限和后代清理；macOS 使用 POSIX 实现并加入 CI，尚无本机 macOS 实测。

参考：[Python 异步子进程](https://docs.python.org/3/library/asyncio-subprocess.html)、
[Windows 进程创建标志](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags)、
[Windows Job 对象](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)。
