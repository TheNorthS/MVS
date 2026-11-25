# 验收报告（2026-11-14）

## 2026-11-26：真实GitHub CI与跨平台修复

源码已推送`TheNorthS/MVS`的main，版本保持0.0.1。首次远程检查发现并修复：
Windows专用类型在POSIX类型检查中未隔离、测试Python路径resolve绕过虚拟环境、Windows输出
默认非UTF-8、后台未停止导致uv缓存锁阻塞、MinIO公共镜像不可获取，以及macOS不支持RLIMIT_AS。

MinIO测试镜像改从固定上游提交构建，保留AGPL许可，且不包含在MVS的PyPI包中。
macOS使用独立进程组RSS监测并保留CPU/超时约束，采样上限不等同内核硬限制；已增加实际内存
超限回归。Windows原生命令显式传递系统目录、架构与模块发现变量，仍不继承任意应用凭据。
固定PowerShell测试允许25秒冷启动，实际超时清理另有专用回归。

远程Windows/Linux/macOS的Python3.12/3.13测试分别取得通过；最新Windows两项均166通过、
13跳过。浏览器、依赖安全、S3/Redis/PostgreSQL集成、纯构建发布工作流均已取得成功记录。
本地新MinIO镜像的12项专项全部通过（99.43秒），临时容器全部清理。
最终提交的排队/完成状态应以[Actions](https://github.com/TheNorthS/MVS/actions)为准。
可核对[跨平台任务](https://github.com/TheNorthS/MVS/actions/runs/45659736390)、
[外部集成](https://github.com/TheNorthS/MVS/actions/runs/45657379342)及
[发布构建](https://github.com/TheNorthS/MVS/actions/runs/45657584199)。

PyPI上传尚未执行；发布构建选用build-only，未创建GitHub Release或上传包索引。

## 2026-11-26：GitHub与PyPI发布准备（0.0.1）

按维护者确认采用MIT许可，仓库为`https://github.com/TheNorthS/MVS`，项目和前后端锁文件
保持0.0.1。补充PyPI专用中文说明、元数据、许可证与第三方NOTICE，发布产物位于
`dist/release/0.0.1/`。源码直接从当前Git仓库推送，不生成GitHub源码ZIP。

本轮完整pytest：**165项通过、13项跳过，121.94秒**；跳过为12项需注入外部依赖的测试和
1项Windows符号链接权限。此次没有重新运行Docker专项或收费模型实验；历史成绩保持原记录。
新增发布范围/凭据拒绝检查及相关发布测试通过，Ruff和mypy（66个源码文件）通过。
TypeScript/Vite构建与Twine strict检查通过，wheel/sdist包含MIT元数据、许可文件和全部页面资源。

在仓库外的独立工作目录创建全新虚拟环境，从wheel离线安装console依赖，确认版本0.0.1，
HTTP后台页面返回200，真实demo MCP计算12+30返回42。sdist重建wheel的全部76个文件内容
与发布wheel一致，未调用Node。无预构建页面的干净源码允许editable安装，正式构建则明确拒绝。

Git待提交内容扫描未检出所检查模式的凭据或运行数据；这不是完整安全审计。分发校验排除
`.tools`、实例数据库、研究缓存和旧安装包。远程CI与PyPI发布状态需查看实际工作流，不冒充本地验收。

> 2026-11-25起项目版本统一固定为0.0.1。下文0.1/0.2/0.3标签及测试数字保留当时记录，
> 不表示目录整理后重新执行了相应验收。原始产物已归入`artifacts/tests/`与`artifacts/benchmarks/`。

## 2026-11-25：DeepSeek V4 Pro同任务240组评测

通过用户指定的DeepSeek官方端点和`deepseek-v4-pro`，使用Responses协议、low推理、seed=42、
并发4、每组8轮及2048输出Token，与GPT实验条件清单相比仅请求模型和创建时间不同。
工具与任务目录逐字节一致，运行期间源码哈希不变。DeepSeek忽略禁用并行工具调用参数，已明确记录。

正式240组完成，236组成功、4组达到轮次上限，无接口异常。原生多工具与JSON网关均80/80；
MVS为76/80，工具选择准确率98.08%、参数合法率和正确率75.96%、平均5.58轮。
失败源于工具发现/命令使用的额外往返：3组第8轮才正确调用工具，未留出最终回答轮次；1组未成功调用。
这些是能力与入口交互失败，不按网络故障排除，也未重跑覆盖。

共919轮带用量模型响应、239次真实MCP调用、264次目标调用尝试。正式总Token为2,827,348，
其中输入2,769,130、输出58,218；缓存输入2,280,064和推理输出12,126已分别包含在输入/输出中。
独立6组冒烟全部成功，额外82,108 Token单列，不计入正式240组。

已核对记录唯一性、每格20任务、逐轮usage加总、预期工具/参数/答案、统计重算和源码哈希。
控制台输出换行曾使进度摘要漏读失败，最终以保存的JSON逐条核对为准，未将中途误报写入最终成绩。
本次未修改生产代码，也未重跑pytest；只记录真实模型验收。详情见
[DeepSeek实验报告](../../artifacts/benchmarks/deepseek-240-20261125-194449-v0.0.1/report.md)。

## 2026-11-25：0.0.1真实GPT 240组评测

有效样本为4个规模×3种入口×20个任务，共240组，全部成功。工具选择准确率、参数合法率和
参数正确率均为100%；有效执行共802轮模型响应、240次实际MCP调用，总Token为1,681,974。
HTTP 502和网络超时作为接口异常排除，任务恢复后统一计入有效样本，不分首次和重试评分。

已核对每格20任务、唯一ID、逐轮usage、实际调用、参数与答案、来源及源码哈希。
本次不计入pytest通过数。详细指标仅维护在[唯一GPT实验报告](../../artifacts/benchmarks/gpt-240-20261125-185218-v0.0.1/report.md)。

## 2026-11-25：0.0.1版本统一与目录整理

Python包、前端元数据与uv/npm锁文件统一为0.0.1；当前安装文档同步版本。文档按用途分类，
实验、截图和报告迁移后更新调用方路径，123处本地文档链接检查通过。历史JSON/XML不改写。

相关安装/发布/部署/架构检查17项通过；最终修改后的模型基准/发布/架构检查16项通过，
这两组存在重叠，不累计为独立通过数。Ruff、mypy（66文件）、TypeScript/Vite构建通过。
本轮未重新运行全部外部服务测试，前次170项全量数据保留在下文。

构建验证发现前端生成目录被Git忽略后wheel漏带页面，已显式声明Hatch构建产物；
离线安装发现运行时字节码缓存可在启动时改写，已排除缓存并让安装入口使用`-B`。
最终wheel含后台资源、版本为0.0.1；安装ZIP包含新目录的教程并保留PowerShell BOM。
Windows完整离线ZIP从新目录解压、空缓存安装39个依赖成功，doctor确认初始化和后台资源正常。
当前离线清单为2812个文件，早期3486文件清单仍作为历史记录保留；ZIP CRC和三个分发文件哈希通过。

## 2026-11-25：Docker恢复后的真实集成验收

Docker Desktop已恢复连接，Engine 29.6.1、Linux/amd64、WSL2后端。本次使用独立临时容器
运行Redis 7、PostgreSQL 16、MinIO，以及python:3.12-slim命令沙箱。没有修改原有业务容器。

专项验收：**12项通过，99.99秒，零失败、零跳过、零警告**。报告保存在
[Docker专项JUnit记录](../../artifacts/tests/docker-acceptance-2026-11-25.xml)。
两个独立MVS进程通过真实HTTP提交20个并发请求，验证共享会话/结果、节点重启后cwd保留、
跨节点撤权和令牌轮换。另验证10个PostgreSQL连接竞争配额、真实S3附件与隔离、内容哈希、
过期清理、孤立/丢失对象修复，以及Docker只读/禁网络/非root/cgroup限额和路径映射。
S3孤立对象测试仅模拟年龄，读写删除均访问真实服务。

真实测试发现并修复了以下问题，初次失败没有计为通过：

- 无限输出时先删容器会阻塞清理，并掩盖RESULT_TOO_LARGE；现在先终止CLI并排空管道，
  关闭沙箱日志，随后回收容器，清理失败有明确错误。
- 取消恰逢Docker创建时可能留下Created容器；改为创建/启动分开管理，等待创建结果再清理，
  重复取消也不能中断清理任务。复跑后没有遗留本次沙箱。
- 多实例等待切换锁后可能应用等待前的旧配置；现在取得锁后重新读取共享配置版本。

接入真实依赖的最终全量：**170项通过、1项跳过，173.16秒，零失败、零警告**，行/分支
联合覆盖率**80.13%**（语句83.05%，分支71.07%）。唯一跳过项是本机Windows符号链接权限。
完整记录见[全量JUnit记录](../../artifacts/tests/docker-full-regression-2026-11-25.xml)及`coverage.json`。
覆盖率包含本次pytest进程执行的外部存储/沙箱路径，不计独立HTTP/MCP子进程的额外执行。
普通未注入外部端点的回归另为158项通过、13项跳过（112.26秒），不与最终通过数相加。
Ruff通过，mypy检查66个源码文件通过，TypeScript/Vite生产构建通过。
测试脚本与CI已覆盖这12项专项，复跑方法见[Docker验收教程](../guides/docker_acceptance.md)。

本地0.3.0 wheel、installer.zip与Windows完整离线包已同步修复；离线包3486个清单文件
哈希核验通过，ZIP CRC核验通过，SHA256SUMS.json已更新。没有上传公共仓库或包索引。
刷新后的完整离线包在新的工具目录和空缓存中安装成功（Python 3.12.13、39个依赖，
UV_OFFLINE/NO_INDEX），doctor确认initialized=true、ui_bundled=true；未修改正常实例。

此次验收属于本机Docker和同机双进程功能验证，未模拟跨物理机网络故障、长期高负载、
数据库主备切换或真实云S3。真实OAuth及Linux/macOS系统服务验收仍未完成。
Git/PyPI公开发布按用户要求暂不进行。

## 2026-11-25：0.3.0扩展（未全部完成生产验收）

新增治理页、加密凭证/迁移、OAuth、细粒度规则、审批、并发运行门控、配置回滚和会话保留；
新增多模型适配、DNS连接绑定、资源约束/隔离工作进程、Redis/PostgreSQL/S3适配、备份恢复、
服务注册、更新/回滚、MCP固定模板、离线包和发布/安全扫描CI。

Docker恢复前全量：**158项通过、4项跳过，89.15秒，行/分支联合覆盖率78%**。跳过为Windows
符号链接权限，以及Redis结果/会话、PostgreSQL结果、共享控制面三个真实外部服务测试。
Ruff通过，mypy检查66个源码文件通过。覆盖率低于80%项目目标，不宣称已全部验收。
旧协议测试曾在一次全量中连接失败；单独重跑和后续全量通过，未删除测试。

真实执行证据：

- 官方Fetch MCP固定模板实际隔离安装成功。
- 真实HTTP MCP回归与已校验IP直接连接单测通过。
- Windows隔离工作进程终止恶意正则，原生进程/Job回归通过。
- 真实demo MCP审批流程验证批准一次、参数改变拒绝、消费后拒绝重放、会话cwd保留。
- 20个并发会话请求与细粒度角色参数校验通过。
- 加密备份恢复、错误密码拒绝、数据库凭证不含明文、配置历史、限流共享测试通过。
- Chat/Anthropic适配与OAuth PKCE/续期/撤销使用HTTP夹具通过，未冒充真实第三方验收。
- Windows完整离线包携带Python/uv/39个依赖，在新工具目录和空缓存、UV_OFFLINE/NO_INDEX下
  安装并初始化成功。图形安装入口已加入包，尚未进行GUI操作验收。
- 浏览器原有2条流程通过，治理页定位错误修正后单项重跑通过；一次浏览器启动退出失败
  属于本机运行异常，后续单项已成功。未把失败隐藏成首次全绿。
- Python pip-audit与npm官方注册表audit均报告无已知漏洞；许可证拒绝检查通过，
  mcp-virtual-shell项目许可证仍为UNKNOWN，需维护者明确选择许可证。

当时的外部阻碍（Docker问题现已解除，见上文）：Docker Desktop启动后引擎仍返回500；没有可用Redis/PostgreSQL/S3真实实例，
没有发布Git远端/PyPI账户，没有Linux/macOS服务注册与真实OAuth授权环境。已向用户请求
这些信息。准确状态见[完成跟踪](../development/completion_tracker.md)，不能将新增代码称为全部生产完成。

## Windows PowerShell 5.1 安装脚本修复

用户报告解压后的install.ps1发生UnexpectedToken、字符串缺少终止符和缺少右花括号。
使用Windows PowerShell 5.1.26100.9818复现3个解析错误：无BOM的UTF-8中文被按ANSI误读。
源码改为UTF-8 BOM，打包辅助模块统一转换.ps1编码，已同步修复现有解压副本与发布ZIP、
更新SHA256SUMS；wheel内容哈希未变化。4项编码/打包/5.1解析回归测试全部通过，Ruff通过。

在真实PowerShell 5.1中运行修复后的解压安装脚本，使用独立的UV_TOOL_DIR、UV_TOOL_BIN_DIR
和MVS_HOME完成安装与初始化；doctor返回initialized=true、ui_bundled=true，退出码0。
测试复用了本机已有uv和离线依赖缓存，没有重新测试uv下载分支，没有修改用户正常实例配置。
之前在PowerShell 7中的语法检查不足以覆盖5.1默认编码差异，本次增加真实5.1解析回归。

## 2026-11-23 增量验收：0.2.0安装包与shadcn/ui控制台

新增管理状态/运行时/API/实例锁、init/serve/doctor/token/config命令、mvs-agent入口、
React/Vite/shadcn官方组件控制台、安装脚本与wheel/ZIP构建脚本。
后台覆盖服务/原生命令、发现与授权、用户令牌、模型凭证、命令和模型工作台、记录及结果查询。

实际验证：

- Python全量 **139项通过、1项跳过，耗时82.77秒**。跳过仍为Windows符号链接权限。
- Ruff通过，mypy检查47个源码文件通过；本轮没有重新采集覆盖率。
- TypeScript与Vite生产构建成功，页面资源已打入wheel。
- Playwright使用真实Chrome与真实后台：**2项通过，耗时26.8秒**。验证登录、服务新增与
  发现、真实MCP调用、用户授权、原生命令表单、真实主机名调用、管理员自身令牌轮换，
  检查桌面/移动截图与无页面脚本错误。
- 管理API测试覆盖401/403、跨租户结果拒绝、撤权/轮换持久化、版本冲突、最后管理员保护、
  配置无效不发布、凭证不回显、Host/Origin限制、模型执行循环和实例锁。
- 使用实际Windows安装脚本把发布wheel装入全新的隔离uv工具目录，安装产生mvs/mvs-agent/
  mvs-benchmark。离开源码目录运行doctor确认ui_bundled=true，启动安装后的后台并实际调用
  demo MCP，得到`{"result":11}`。未依赖仓库开发环境或Node运行页面。
- Linux/macOS安装脚本通过Ubuntu/WSL `bash -n`；PowerShell脚本语法检查通过。

分发物位于dist，包含wheel、installer.zip与SHA256SUMS.json；尚未上传公共包索引。
用户安装仍需联网下载Python/依赖，不是完全离线安装。未实测Linux/macOS完整安装器。
本轮模型API调用用受控测试接口验证，没有重新触发付费模型实验。

## 2026-11-23 增量验收：原生操作系统命令

新增 `domain/native.py`、`infrastructure/native/`、`configs/servers.native.example.yaml`、
固定 PowerShell 示例和[中文使用文档](../guides/native_commands.md)。`/os` 原生命令与 `/mcp` 工具
共用 Schema、Policy、Registry/VFS、并发、审计、结果存储和 API，新增原生命令专用指标。
用户新需求明确扩展原始范围，规范首页已经注明该变更。

实际执行：

```text
uv run ruff check .
uv run mypy src/mvs examples/gpt_agent.py examples/deploy_api.py
uv run pytest --cov=src/mvs --cov-branch --cov-report=term-missing --cov-report=json:artifacts/tests/coverage.json -q
uv run mvs --config configs/servers.native.example.yaml --json exec -- 'run /os/host/tools/hostname'
uv run mvs --config configs/servers.native.example.yaml --json exec -- '/os/host/tools/identity'
```

Windows 全量 **134项通过、1项跳过，耗时54.84秒，总体覆盖率87%**。跳过项为创建符号链接
需要系统权限，测试没有删除或假装通过。新增更严格的禁止任意 Shell 执行架构检查另外2项通过。
Ruff 全部通过；mypy检查43个源码/示例文件通过。真实hostname.exe/whoami.exe和固定PowerShell
脚本运行成功，非零退出码、stdout/stderr、结果引用、错误管道短路、超时/取消清理均验证。

Ubuntu/WSL（Python 3.14.4）独立运行原生命令后端6项检查：真实hostname、id、字面参数与
环境隔离、符号链接越界、输出超限、超时后的后代清理，全部通过。这不是Linux全套MCP回归。
macOS沿用POSIX实现且已加入CI矩阵，但本地没有macOS运行环境，不能宣称该平台已实测通过。

测试发现并修复：Windows Job创建参数兼容问题、未排空管道导致输出超限清理阻塞，以及
TimeoutError被OSError误捕获导致错误分类不正确。已知Shell只接受管理员固定脚本，不允许
动态`-c`/`-Command`；通用解释器动态参数只允许放在固定脚本路径之后。
进程组/Job清理不等于CPU、文件系统或网络沙箱，仍以MVS账户权限运行。

> 文档中文统一日期：2026-11-15。以下测试与实验数字均保留原实测结果，不代表重新执行。

环境：Windows、Python 3.12.6、uv 0.13.8、mcp 2.3.0、pytest 9.2.0。
仓库最初只有实施规范，没有旧 MVP 源码。

## 分阶段交付文件

下列模块路径相对于 `src/mvs/`，另行注明的仓库路径除外。

- 阶段 0：`pyproject.toml`、`uv.lock`、`.github/workflows/ci.yml`、SDK 演示和真实 SDK 测试。
- 阶段 1：`parser/{ast,lexer,parser}.py` 和 `tests/unit/test_parser.py`。
- 阶段 2：`core/{registry,vfs}.py`、`infrastructure/mcp/{client_manager,sdk_v2_adapter}.py`、
  `infrastructure/storage/session_store.py`，以及注册表、分页和路径测试。
- 阶段 3：`core/schema_adapter.py`、`security/{policy,audit}.py` 和参数/权限测试。
- 阶段 4：`services/shell_service.py`、`cli.py`、`infrastructure/mcp/executor.py`、
  `core/result_normalizer.py`，以及演示、执行器和安全测试。
- 阶段 5：`infrastructure/storage/result_store.py`、`pipeline/`、`core/catalog.py`、
  `tests/e2e/test_p1_stdio.py` 和 `examples/agent_adapter.py`。
- 阶段 6：`api/app.py`、`infrastructure/mcp/http_security.py`、`examples/api_server.py`、
  `examples/benchmark.py`，以及 API、HTTP、旧协议、故障恢复测试和文档。

## 首轮逐阶段实测

| 阶段或检查点      | 实际结果                                      | 验证内容                                            |
| ----------------- | --------------------------------------------- | --------------------------------------------------- |
| 阶段 0            | 3 项通过                                      | 真实 v2 stdio 发现与调用、2026-07-28 协议、架构边界 |
| 阶段 1            | 38 项通过                                     | 混合语法、位置记录、引号数据、注入拒绝              |
| 阶段 2            | 46 项通过，另有 1 项分页测试通过              | 真实注册表生命周期、快照、虚拟路径和会话隔离        |
| 阶段 3            | 72 项通过                                     | Schema 转换与校验、JSON/引用安全、默认拒绝策略      |
| 阶段 4            | 77 项通过，语句覆盖率 87%                     | 完整演示、CLI、执行器限制与错误、审计               |
| 阶段 5            | 87 项通过                                     | 持久化结果、管道、真实资源/模板/提示词              |
| 阶段 6 中间检查点 | 93 项通过，另有 2 项旧协议测试通过            | 认证 API、HTTP、追踪与指标、v1↔v2                   |
| 首轮完整回归      | **100 项通过，耗时 28.11 秒，零跳过、零失败** | 恢复、排队撤权、大结果、CLI、随机输入               |

实际运行命令如下。本机使用项目内 uv 可执行文件和项目缓存目录。

```text
uv sync --all-extras
uv run ruff check .
uv run mypy
uv run pytest -q -p no:cacheprovider
uv run pytest --cov=src/mvs --cov-branch --cov-report=term-missing --cov-report=json:artifacts/tests/coverage.json -q -p no:cacheprovider
uv run mvs --json exec -- 'run /mcp/demo/tools/add --a 10 --b 20'
uv run python examples/benchmark.py
```

首轮 Ruff 全部通过，mypy 在 28 个源码文件中未发现问题。
开启分支统计后的总体覆盖率为 **86%**；词法器/解析器为 100%，VFS 为 97%，
SchemaAdapter 为 92%。这些是 coverage.py 联合行与分支统计的百分比。
覆盖率采集不包含独立演示服务器子进程自身。实际 CLI 返回成功，标准输出为 `30`，
数据为 `{"result":30}`。`coverage.json` 保存后续最近一次采集的数据。

最初 stdio 测试遇到 Windows 沙箱 `WinError 5`，获准在沙箱外运行后通过。
早期解析器测试发现 `--` 终止符的错误分类问题，已修复。检查安装的 SDK 源码时发现
显式刷新需要 `cache_mode="refresh"`，已修复。Ruff 和 mypy 的问题都在阶段检查前修正，
没有删除失败测试来获得通过结果。

在首轮检查点，阶段 6 尚不满足完整生产与研究验收：真实模型 Token/选工具基准、OAuth
生命周期、分布式存储与限流、硬性 CPU 隔离和 DNS 到套接字绑定均未完成。
模型基准和监控随后按下文补充。通知使用 TTL 兜底；持续集成已配置 Windows/Linux 和
Python 3.12/3.13，但这里没有实际运行远程 CI 或 macOS 验证。

## 2026-11-14 增量验收：GPT 实验与监控

新增 `domain/telemetry.py`、`infrastructure/observability.py`、`benchmarks/` 和
`infrastructure/mcp/benchmark_server.py`。注册表、执行器、结果存储、ShellService
及 API 接入统一观察接口，新增 `mvs-benchmark` 入口和 `benchmark` 可选依赖。

实际执行 `uv sync`、`ruff check`、`mypy`、`pytest --cov=src/mvs --cov-branch`。
最终 **115 项通过，耗时 48.41 秒，零失败、零跳过**；总体行/分支联合覆盖率 **87%**，
Prometheus/OTel 适配器覆盖率 **100%**。mypy 在 36 个源码文件中未发现问题，Ruff 通过。

新增自动化测试不调用付费模型，验证真实 MCP 后端、用量统计、错误脱敏、断点恢复、
失败保留和答案判分。指标验证覆盖正常、业务失败、输出错误、超时、取消、发现失败、
审批、排队撤权、存储失败、跨用户读取、目录过滤不计拒绝、API 管理员拒绝和收集器隔离。
API、Shell 和工具追踪关联验证通过。

## 当前 GPT 实验结果（2026-11-25，0.0.1）

当前统一使用最新240组有效执行：全部任务成功，总用量1,681,974 Token，802轮模型响应、
240次真实MCP调用。工具选择准确率、参数合法率和参数正确率均为100%。接口502与网络超时
不进入能力评分，工具选择、参数和答案错误仍按任务失败处理。

MVS相对原生入口在20/50/100/200工具规模分别增加66.6%、减少8.0%、减少34.0%、减少47.5%，
各规模均为20个同任务配对。完整数字仅维护在[最新实验报告](../../artifacts/benchmarks/gpt-240-20261125-185218-v0.0.1/report.md)，
统计定义见[模型实验说明](../research/model_benchmark.md)。旧实验结果不再作为当前文档引用。
这些结论仅适用于本次合成单步任务与模型接口，不等于所有业务都具有100%成功率或Token收益。

## 2026-11-15 增量验收：Linux 教程与真实 MCP 接入

新增完整中文部署教程、`examples/deploy_api.py`、`examples/gpt_agent.py`、Linux Git MCP
配置和 `deploy/mvs.service`。API 工厂从环境加载服务器配置与授权，区分普通主体/管理员令牌；
GPT 客户端经真实 HTTP API 运行有界工具循环，并清理会话，对审批与不确定执行结果停止调用。

官方 `mcp-server-git==2026.11.11` 在隔离环境安装并联调，实际发现14个工具，白名单内的
`git_status` 和 `git_log` 读取临时真实 Git 仓库成功，未授权写工具不可见。
教程新增6项测试通过。首次全量回归出现一次旧版连接失败，检查发现 SDK 探测窗口为10秒，
与原总连接超时相同；默认连接超时调整为30秒，给启动和旧协议回退留出时间。
最终 **121项通过，耗时44.59秒，零失败、零跳过**。Ruff通过，mypy检查38个源码/示例文件通过。
本次未重新采集覆盖率，前文覆盖率仍属于相应历史运行。

Ubuntu/WSL 通过全部20段Bash示例的 `bash -n` 语法检查，文档本地链接检查通过。
WSL网络DNS解析失败，未完成其依赖安装和systemd部署；未登录用户目标服务器，也未在本轮
调用付费GPT。测试使用受控模型响应、真实MCP后端验证调用循环，不能宣称新增部署链已在
目标Linux上完成真实GPT验收。完整步骤见[Linux接入教程](../guides/linux_deployment.md)。
