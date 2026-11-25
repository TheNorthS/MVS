# Docker 真实集成验收教程

此教程验证本项目实际连接 Redis、PostgreSQL、S3 兼容存储，并运行受约束的 Linux 容器命令。
测试使用真实服务和真实 MCP 演示服务，不调用付费模型。双节点测试启动两个独立的 MVS
HTTP 服务进程；它们共享数据库和 Redis，但使用不同的本地实例目录。

## 1. 准备环境

在项目根目录执行。开发机器需要 Python 3.12 或以上、uv，以及可用的 Docker Linux 引擎。
Windows 可使用 Docker Desktop 的 WSL2 后端。先确认 `docker version` 同时显示 Client
和 Server；只有客户端版本不能证明引擎已经连接。

```bash
docker version
docker info
uv sync --locked --all-extras
docker pull redis:7-alpine
docker pull postgres:16-alpine
docker pull minio/minio:RELEASE.2024-12-18T13-15-44Z
docker pull python:3.12-slim
```

镜像需预先下载。原生命令沙箱只使用已经存在的镜像，调用过程中不会自动下载镜像。
部署时建议将管理员批准的镜像固定到 digest；修改镜像、程序和挂载配置都应经过审查。

## 2. 一条命令启动并验收

```bash
uv run python scripts/test_docker.py
```

脚本会创建随机命名的三个临时容器，端口随机分配且只绑定 `127.0.0.1`，生成临时密码，
等待依赖就绪后运行测试。退出时根据本次随机名称和标签清理容器及其临时匿名卷。
不会清空用户已有的 Redis 数据库、PostgreSQL 数据库或 S3 桶。

PostgreSQL 测试每项使用独立 schema，S3 测试创建独立桶并在结束后清理。
测试自己的沙箱容器使用 `mvs.backend=native` 标签，生产后端按自己生成的精确名称回收。
脚本清理失败会返回错误并列出未清理的名称，不会把清理失败报告成成功。

如果已在本机保存了兼容镜像，可指定镜像名称；以下是本次验收机器的实际命令：

```powershell
$env:PYTHONIOENCODING = 'utf-8'
.venv/Scripts/python.exe scripts/test_docker.py --minio-image rag-e-minio:2024-12-18
```

可只跑一组测试，也可改变 JUnit 报告路径：

```bash
uv run python scripts/test_docker.py --report .tools/docker-acceptance.xml tests/integration/test_cluster_process.py
```

要让全量回归同时使用真实依赖并采集覆盖率，运行：

```bash
uv run python scripts/test_docker.py --coverage tests
```

默认报告为 `.tools/docker-acceptance.xml`，终端显示真实通过数、失败数和清理结果。
可用 `docker ps -a --filter label=mvs.backend=native` 查看沙箱状态，但不要批量删除其他
正在使用 MVS 的用户的容器。测试失败时先按名称检查相应容器和引擎状态。

## 3. 验证了什么

| 测试文件                   | 实际执行内容                                                                                                                             |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `test_external_storage.py` | Redis 会话共享、身份隔离和限流；PostgreSQL 结果分页、10 个连接并发争用配额；S3 附件、完整性、过期清理、孤立对象和丢失对象核对            |
| `test_control_postgres.py` | 共享配置版本、加密凭证读取、过期版本写入冲突                                                                                             |
| `test_cluster_runtime.py`  | 双运行时并发调用、共享结果、撤权、令牌轮换，以及等待切换期间再次更新配置的竞态                                                           |
| `test_cluster_process.py`  | 两个独立 HTTP 进程交替提交 20 个并发请求；节点退出后读取其结果；节点重启后保持会话/cwd；跨进程撤权和令牌轮换                             |
| `test_docker_sandbox.py`   | 非 root、只读根目录和挂载、禁网络、无 capabilities、禁止提权、CPU/内存/PID 限额、中文与空格路径映射、超时/取消/重复取消/输出超限后的清理 |

S3 孤立对象年龄的测试仅将时间判断前移两小时；对象写入、读取、列举、哈希校验与删除
均发生在真实 MinIO 中。双进程并发测试属于功能验收，不能当作长期压力或跨物理机容灾测试。

## 4. 生产实例配置与测试配置的区别

脚本内部使用 `MVS_TEST_*` 变量注入一次性的测试端点。生产运行时使用下列变量：

| 变量                                          | 用途                                       |
| --------------------------------------------- | ------------------------------------------ |
| `MVS_REDIS_URL`                               | 所有节点共享的会话、会话锁和请求限流       |
| `MVS_POSTGRES_DSN`                            | 结果元数据、权限归属与配额事务             |
| `MVS_CONTROL_POSTGRES_DSN`                    | 控制台配置、身份、审批、OAuth 和事件       |
| `MVS_VAULT_KEY`                               | 所有节点一致的 Fernet 密钥，需独立安全保存 |
| `MVS_S3_BUCKET`                               | 已创建、专供该 MVS 部署使用的对象桶        |
| `MVS_S3_ENDPOINT`                             | S3 兼容服务端点；AWS S3 可使用默认端点     |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | S3 凭证，也可使用 boto3 支持的其他凭证方式 |

每个节点使用独立 `--home` 目录。各节点的服务配置中若含原生命令的宿主路径，应在每个
节点保持相同可用路径；挂载中的目录和文件须允许容器的 UID/GID 65534 读取。
Docker bind mount 的源路径由 Docker daemon 所在机器解释。
若连接远程 daemon，不能假设客户端本地文件会自动同步过去。

详细部署、备份和权限边界见[生产能力说明](production_features.md)与
[Linux 安装及模型接入教程](linux_deployment.md)。生产环境须自行配置 TLS、持久化卷、
备份和网络访问控制；本教程的临时容器配置仅用于可重复验收。

## 5. 尚不能从这些测试推出的结论

测试通过不等于已完成 Linux/macOS 的服务安装验收，不代表真实第三方 OAuth 授权通过，
也不能证明生产数据规模下的延迟、吞吐或容灾能力。Redis 同步接口的阻塞、长时间请求下
锁租期、多节点进程异常退出、数据库断网恢复、真实云 S3 的权限与网络仍需进一步验收。
最新结果和失败修复记录见[验收报告](../reports/validation_report.md)。
