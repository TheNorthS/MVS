# 最终用户安装与可视化管理（0.0.1）

> 当前版本固定为0.0.1，治理与生产配置见[生产能力说明](production_features.md)。
> wheel/ZIP统一使用0.0.1版本号。Windows完整离线包另含Python、uv与wheel依赖，运行根目录
> install.cmd，无需访问包索引；必须保留包内Python目录。0.0.1已发布到PyPI。

这一版本把管理功能集成进 Python 安装包。用户不需要下载源码、编辑 YAML 或安装 Node.js。
管理页面基于 React、Vite、Tailwind CSS 和 **shadcn/ui 官方组件**，随 wheel 一起安装。

## 1. 获得发布包

推荐直接从[PyPI](https://pypi.org/project/mcp-virtual-shell/0.0.1/)安装：

```bash
uv tool install --python 3.12 'mcp-virtual-shell[console]==0.0.1'
mvs init
mvs token show
mvs serve --open
```

已有虚拟环境时可运行`python -m pip install 'mcp-virtual-shell[console]==0.0.1'`。

项目维护者运行 `python scripts/build_release.py`，生成：

- `dist/release/0.0.1/pypi/mcp_virtual_shell-0.0.1-py3-none-any.whl`：Python包，包含控制台。
- `dist/release/0.0.1/pypi/mcp_virtual_shell-0.0.1.tar.gz`：含已构建页面的源码包。
- `dist/release/0.0.1/installers/mcp_virtual_shell-0.0.1-installer.zip`：wheel、安装脚本和教程。
- `dist/release/0.0.1/SHA256SUMS.json`：分发文件哈希。

0.0.1的wheel与源码包已公开上传PyPI；GitHub Release与安装ZIP可另行分发。
源码仓库为[TheNorthS/MVS](https://github.com/TheNorthS/MVS)，维护者按[发布指南](../development/publishing.md)上传包。
把 installer.zip 分发给其他用户即可；安装依赖时仍需要联网，**不是完全离线安装包**。

## 2. 一条命令安装并初始化

解压 installer.zip，进入解压目录。Linux/macOS：

```bash
sh scripts/install.sh
```

Windows PowerShell：

```powershell
.\scripts\install.ps1
```

Windows PowerShell 5.1 与 PowerShell 7 都可使用。安装脚本以带 BOM 的 UTF-8 保存；
若旧安装包出现中文乱码、`UnexpectedToken` 或“字符串缺少终止符”，请换用修复后的安装 ZIP。
这属于脚本编码问题，不需要调整系统执行策略或手动修改脚本中的引号。

如系统脚本策略阻止运行，应按组织策略允许受信任脚本；安装脚本不会修改系统执行策略。
脚本会在缺少 uv 时安装固定版本 uv 0.13.8，使用 uv 创建 Python 3.12 工具环境，安装
本地 wheel 的 console 依赖，然后运行 `mvs init`。脚本不注册系统服务，不要求 root，
也不删除或覆盖现有实例配置。重复安装用于更新程序，初始化本身是幂等的。

已经有 uv 时，也可以手动安装 wheel：

```bash
uv tool install --python 3.12 './mcp_virtual_shell-0.0.1-py3-none-any.whl[console]'
mvs init
```

如果 `mvs` 不在 PATH，运行 `uv tool update-shell` 后重新打开终端，或者使用安装脚本打印的
完整命令路径。用户需要网络下载 Python 和依赖；代理与镜像使用 uv 的标准配置。

## 3. 打开后台

```bash
mvs token show
mvs serve --open
```

第一条命令只在你的终端显示初始管理员令牌。第二条启动 API 和管理页面并尝试打开浏览器，
默认地址 `http://127.0.0.1:8080`。把令牌粘贴到登录框。令牌不放进 URL，也不存入浏览器
localStorage；刷新页面后需重新输入。不要把管理员令牌交给普通 Agent。

无桌面的 Linux 服务器使用 `mvs serve`，再通过 SSH 隧道访问：

```bash
ssh -N -L 8080:127.0.0.1:8080 user@server
```

浏览器访问本机8080。控制台只监听回环地址；公网访问需要你自己配置可信 HTTPS 反向代理。
本版本单进程运行，同一数据目录只能启动一个控制台实例。
反向代理使用自定义域名时，在服务进程环境设置 `MVS_ALLOWED_HOSTS=mvs.example.com`；
后端检查Host和浏览器Origin，不开启跨域管理写入。

## 4. 数据位置与实例选择

| 系统    | 默认目录                                              |
| ------- | ----------------------------------------------------- |
| Windows | `%LOCALAPPDATA%\MVS`                                  |
| Linux   | `$XDG_DATA_HOME/mvs`，未设置时为 `~/.local/share/mvs` |
| macOS   | `~/Library/Application Support/MVS`                   |

可以设置 `MVS_HOME`，或在 init/serve/doctor/token 命令上使用 `--home /your/path`。
如果使用自定义目录，每次命令必须选择同一个目录。

```bash
mvs init --home /srv/mvs-data
mvs token show --home /srv/mvs-data
mvs serve --home /srv/mvs-data --port 8080
mvs doctor --home /srv/mvs-data
```

已有 YAML 配置可在服务停止时合并导入；不会自动给普通用户新增授权：

```bash
mvs config import configs/servers.local.yaml
mvs config export my-servers-backup.yaml
```

导出只包含服务配置，不包含用户令牌或托管凭证；目标文件已存在时拒绝覆盖。

`control.sqlite3` 保存管理状态与最多2000条事件；`admin-token` 是本机初始令牌文件；
`results/` 保存工具结果。访问令牌在数据库中只保存SHA256摘要，创建/轮换时只回显一次。
托管的下游模型/MCP凭证使用Fernet加密，不通过读取接口回显。主密钥可使用私有文件、
MVS_VAULT_KEY或系统钥匙串；同时取得主密钥和数据库的人仍可解密。Unix目录权限0700，
Windows继承用户目录ACL。备份整个数据目录时按包含凭证的数据处理。

## 5. 第一次配置

初始化默认创建 demo 服务和管理员，立即可在工作台运行 `run /mcp/demo/tools/add --a 2 --b 3`。
需要空实例可用 `mvs init --empty`。在概览页点击「打开配置向导」：

1. **模型与凭证**：填写支持 Responses 的接口地址、模型ID和凭证变量名。
   在凭证区写入 `MVS_SECRET_MODEL_KEY`。远程模型接口要求HTTPS，本机接口可用HTTP。
2. **服务与工具**：添加本地 MCP、远程 MCP 或原生命令。保存后测试连接，查看发现的Schema，
   勾选需要开放的工具并保存。空白名单表示不允许调用，不是全部开放。
3. **用户与授权**：创建普通用户，指定租户和可访问服务组，保存后复制只显示一次的令牌。
4. **调用工作台**：手动测试虚拟命令；配置模型后也可提交自然语言任务让模型实际调用工具。

模型连接测试会发出一次简短请求，模型任务会进行最多8轮调用，可能计费。普通 pytest
不会调用付费模型。工作台以当前登录管理员身份执行；给其他人接入时用独立普通用户令牌。

## 6. 服务和原生命令管理

### 本地 MCP

填写唯一服务ID、启动程序和逐行参数，例如 python、`-m`、`mvs.infrastructure.mcp.demo_server`。
实际第三方 MCP 要事先安装到它自己的环境，再填写绝对可执行路径。控制台不会替用户安装
任意外部 MCP 软件包。保存可能启动所配置的服务器；连接测试只执行发现，不调用业务工具。

### 远程 MCP

填写 Streamable HTTP MCP URL，界面从URL生成主机白名单；可填写凭证引用，例如
`MVS_SECRET_REMOTE_TOKEN`。凭证在「模型与凭证」写入；OAuth在「治理与运维」配置，
服务使用`auth_ref: oauth:提供方名`引用用户凭证，真实身份提供方仍需完成客户端注册和验收。
私网例外与更多配置可在「高级 JSON」编辑，所有内容仍需通过后端校验。

### 原生命令

填写命令名、说明、当前平台程序绝对路径、工作目录、argv JSON数组和输入JSON Schema。
例如 hostname 无参数，输入Schema为 `{"type":"object","additionalProperties":false}`。
多命令、其他系统实现、path_roots和环境引用可用高级JSON。普通管理员表单不会开放自由Shell。
完整规则见项目的 `docs/guides/native_commands.md`。

服务卡片可启停、编辑、删除或测试连接。删除服务同时移除用户对该服务的授权。

## 7. 配置安全应用

每次更改携带配置版本号，后端校验通过才应用。并发管理员的过期版本返回409，需刷新再改。
校验失败不改原配置；切换会等待正在执行的API请求结束，再启用新运行实例。连接失败的
服务会显示「未就绪」，可以修正配置；语法有效并不代表下游服务一定在线。

当前版本在配置切换时保留有效会话和当前目录；普通请求并行执行，切换等待在途请求完成。
外部Agent收到会话404仍需重新创建会话；已有持久化结果仍受原owner/tenant保护。
多实例需配置共享Redis、PostgreSQL和一致的凭证密钥，见[生产能力说明](production_features.md)。
已验证两个独立HTTP进程共享会话和重启恢复，不能据此承诺高并发生产容量。
已开始的副作用不能靠撤权或热切换自动回滚。

用户令牌可以轮换、禁用或删除，旧令牌随后不能访问API。必须保留至少一个启用管理员。
轮换自己的管理员令牌时，请先复制弹窗的新令牌，再退出并重新登录；初始admin-token文件
不会被远程轮换自动覆盖，`mvs token show` 会提示旧引导令牌已失效。

丢失管理员令牌时，在拥有数据目录权限的主机上停止服务，运行 `mvs token reset`
（其他管理员ID使用 `--user ID`），再用 `mvs token show` 获取新令牌。
重置和离线导入会检查实例锁，服务运行中拒绝执行，避免配置与运行实例不一致。

## 8. 普通用户和模型客户端接入

后台沿用原有 `/api/v1/sessions` 与 `/api/v1/shell/execute` 接口。普通用户可以创建会话和
执行获准的工具，不能调用 `/api/admin/*`。客户端程序可通过 `mvs-agent` 运行：

```bash
export OPENAI_BASE_URL=https://api.openai.com/v1
export OPENAI_API_KEY='<你的模型凭证>'
export MVS_API_URL=http://127.0.0.1:8080
export MVS_AGENT_TOKEN='<后台创建的普通用户令牌>'
mvs-agent --model '<实际可用模型ID>' --task '发现工具并计算2加3'
```

上面是Linux/macOS写法；Windows使用 `$env:变量名='值'`。默认使用Responses函数调用；
通过`--protocol chat_completions`或`--protocol anthropic`选择对应兼容协议。
管理后台保存的模型配置用于后台测试与任务，不自动发送凭证到普通客户端。

## 9. 记录、结果与运维

调用记录显示状态、主体、耗时、错误类别和结果引用，不保存原始命令与参数。
结果详情仍检查owner/tenant，管理员也不能直接读取其他用户结果。
指标入口 `/metrics` 继续要求管理员身份。`mvs doctor` 检查配置数据库、程序版本和前端资源。

更新：停止服务后用新发布包重新执行安装脚本，再 `mvs serve`；初始化不会覆盖既有数据。
卸载程序可用 `uv tool uninstall mcp-virtual-shell`，数据目录不会自动删除。
长期运行可由systemd/Windows服务包装器/launchd启动绝对路径的 `mvs serve --home ...`；
本版安装器不自动注册系统服务。

## 10. 开发与发布

只有维护者构建时需要 Node。前端在 `web/`，shadcn官方组件源码与来源清单一并保存。

```bash
uv sync --all-extras
cd web
npm ci
npm run build
cd ..
python scripts/build_release.py
```

构建产物写入 `src/mvs/web/` 并打入wheel，后端和静态页面同源，不需要单独部署前端服务。
离线包、服务注册、OAuth、审批和共享控制面均已有实现；已完成和待完成的验收分别记录在
[完成跟踪](../development/completion_tracker.md)。版本保持0.0.1，历史开发阶段编号不代表公开发布版本。
