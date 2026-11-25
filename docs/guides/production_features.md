# 0.0.1 生产能力扩展与验收边界

本轮针对“全部实现”补充功能。此文区分已有代码、本地测试和仍需要真实外部环境的验收。
详细状态见[完成跟踪](../development/completion_tracker.md)。

## 凭证、OAuth与授权

状态中的secrets改用Fernet认证加密，旧数据库首次打开时事务迁移。
主密钥默认在私有vault.key文件；可用MVS_VAULT_KEY环境变量，或设置
`MVS_VAULT_BACKEND=keyring`使用系统钥匙串。文件密钥和数据库同机可读时不构成对主机
管理员的保密。备份加密与存储加密使用独立密码/密钥。

后台“治理与运维→OAuth”支持授权码+PKCE、一次性state、按租户/用户保存令牌、续期和撤销。
MCP的`auth_ref: oauth:提供方名`在请求前取得对应用户令牌。用户通过
`POST /api/oauth/{provider}/start`取得授权地址，回调为`/api/oauth/callback`。
支持公开客户端PKCE，也支持client_secret_ref引用环境中的客户端密钥。真实身份提供方必须注册
client_id和回调，测试夹具不能替代真实授权验收。

自定义角色用`PUT /api/admin/roles/{role}`保存，用户支持roles、rules、secret_refs、rate_limit。
规则与服务授权和白名单相交；同用户角色允许项取并集。规则示例：

```json
{
    "demo": {
        "tools": ["add"],
        "arguments": {
            "add": {
                "type": "object",
                "properties": { "a": { "maximum": 10 } },
                "required": ["a"]
            }
        },
        "resources": [],
        "prompts": []
    }
}
```

secret_refs将服务器期望的凭证变量名映射到托管凭证名，优先于共享环境引用。

## 审批、配置与并发

approval_tools命中的调用创建10分钟有效审批，响应error.approval_id。后台查看参数并批准
或拒绝后，申请者重交原命令并携带approval_id。参数、主体、租户、工具版本必须一致，
批准在派发前只消费一次；超时失败不返还，避免重复副作用。

每次配置更新保存加密历史，后台可回滚服务/模型配置，保留当前身份令牌避免复活已撤销身份。
运行时普通请求并行，切换等待在途请求；未变化服务复用客户端，会话移交而非全部失效。
用户删除、禁用或身份变化后不能继续用旧身份访问。MVS_CONTROL_POSTGRES_DSN可启用共享
控制状态、审批、OAuth与审计，所有节点必须使用同一MVS_VAULT_KEY；执行前检查共享版本。
已在真实Redis/PostgreSQL上验证两个独立HTTP进程的20个并发请求、共享会话/结果、重启后的
cwd保留、撤权和令牌轮换。修复了等待切换锁后仍应用旧配置快照的竞态；不代表长期容量验收。

## 安装、升级、服务与模板

`mvs service install/uninstall`注册当前用户服务：Linux systemd用户服务、macOS launchd、
Windows登录任务。需目标平台服务管理器可用；本轮不修改用户真实开机设置。
图形安装入口scripts/installer_gui.py需要带Tk的Python和uv，不是签名MSI。

`mvs update check/install --url https://.../latest.json`校验HTTPS清单和wheel SHA256，
安装在CLI退出后执行以避免Windows锁文件；`mvs update status`查状态，`mvs update rollback`
使用已保留的前一wheel。首次安装包未进更新历史时不能回滚到它。MVS_RELEASE_BASE_URL配合
构建脚本生成清单。缺少发布地址时不能自动发现版本，目前不提供无人值守更新调度。

源码仓库为[TheNorthS/MVS](https://github.com/TheNorthS/MVS)，MIT许可，版本固定0.0.1。
release工作流默认只构建，可显式选择GitHub草稿、TestPyPI或PyPI；包索引需先配置可信发布者。
步骤见[发布指南](../development/publishing.md)，构建成功不代表已上传PyPI。
MCP模板为固定版本Git/Fetch，后台可安装/重装隔离环境并注册，不是任意第三方包市场。

scripts/full_offline_bundle.py按当前平台打包独立Python、uv和依赖wheel，用户离线运行
install.cmd/install.sh。构建需要联网；不同平台分别构建。build_offline.py仅包含依赖wheel，
不含Python，请勿混用。

## 备份、存储与恢复

```bash
mvs backup create /safe/backup.mvsb
mvs backup restore /safe/backup.mvsb --home /new/empty/instance
mvs repair
```

备份用Scrypt+Fernet加密，SQLite使用快照API，恢复拒绝非空目录、非法路径、哈希不符和错误
密码。运行中的实例拒绝离线维护。repair清理本地孤立对象，报告丢失/损坏对象；不自动删除
仍被引用的数据。已有schema_migrations记录；任意历史版本降级尚无保证。
MVS_BACKUP_DIR、MVS_BACKUP_PASSWORD、MVS_BACKUP_INTERVAL_SECONDS启用定时加密备份，
备份目录必须在实例目录外。当前自动备份覆盖本地实例，外部数据库需使用其原生备份设施。

production可选依赖提供Redis会话/锁/限流、PostgreSQL事务配额与结果元数据、S3对象内容：

```bash
uv sync --extra console --extra production
export MVS_REDIS_URL=redis://localhost:16379/0
export MVS_POSTGRES_DSN=postgresql://mvs:密码@localhost:15432/mvs
export MVS_S3_BUCKET=mvs-results
export MVS_S3_ENDPOINT=https://s3.example.com
```

AWS凭证使用boto3标准配置。共享控制面另设置MVS_CONTROL_POSTGRES_DSN与MVS_VAULT_KEY。
Redis同步方法可能阻塞事件循环。已验证真实S3附件、哈希损坏检测、TTL删除和孤立/丢失对象
核对，以及PostgreSQL的10连接原子配额竞争。MVS_S3_BUCKET启用时mvs repair可核对并清理
超过1小时的孤立对象。长期高负载、断网恢复和长请求锁租期仍需专项验证。
Docker引擎现已恢复，可按[Docker验收教程](docker_acceptance.md)创建独立临时服务复跑测试。

## 资源与网络边界

原生命令新增memory_limit_mb、cpu_time_seconds。Windows Job聚合限制，POSIX启动器设置
RLIMIT_AS/RLIMIT_CPU。`MVS_ISOLATED_VALIDATION=1`把参数Schema、结果Schema及管道交给
独立固定操作进程，限制5秒、256MiB、CPU3秒；注册表Schema格式检查也可隔离。
细粒度权限规则采用受限Schema子集，拒绝正则和递归引用，支持enum/const/长度/数值范围等。
这避免了授权复核路径中同步执行不受控正则，但也不宣称支持任意复杂权限Schema。

sandbox_image使用管理员预先拉取的Docker镜像，默认禁网络、只读根/挂载、非root、
drop capabilities、禁止提权、256MiB、一个CPU核和64个PID上限。工作目录映射到容器
/workspace，参数路径按授权根转换。已在Windows Docker Desktop的Linux引擎中实测资源
配置、中文/空格路径、超时、重复取消、输出超限和清理。容器创建与启动分开管理，取消会
等待创建结果再回收，清理不被重复取消中断；容器日志关闭以防无限输出占满日志。
创建/清理控制操作分别有30秒上限，回收失败明确返回COMMAND_CLEANUP_FAILED。
远程daemon的挂载路径必须在daemon所在机器存在；这仍不是Linux/macOS宿主完整安装验收。

HTTP MCP在TCP连接点解析检查IP并使用数字IP连接，保留Host/TLS SNI；真实HTTP测试和
防重绑定单测通过。其他模型/OAuth出站仍依赖可信管理员配置，并未套用MCP主机白名单。

## 多模型与持续验证

model.protocol支持responses/chat_completions/anthropic，fallbacks最多3个。模型请求在
429/502/503/504或网络失败后可切换，工具不重放；mvs-agent支持--protocol。
新协议已有HTTP夹具测试，但没有重复跑真实付费模型实验。

CI新增依赖漏洞扫描、许可证清单和真实Redis/PostgreSQL服务测试；macOS/目标服务器仍需
验收环境。功能尚未完整验收的部分不会因为新增文件存在就标记为完成。
