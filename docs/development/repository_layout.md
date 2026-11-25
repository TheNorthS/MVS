# 项目目录与版本约定

## 目录职责

| 路径                        | 职责                                   | 是否纳入版本控制           |
| --------------------------- | -------------------------------------- | -------------------------- |
| `src/mvs/`                  | Python核心、后端适配、API与控制面      | 是；排除构建生成的`web/`   |
| `web/src/`、`web/public/`   | 前端源码与静态资源源文件               | 是                         |
| `tests/`                    | 单元、集成、安全、端到端测试及协议夹具 | 是                         |
| `configs/`                  | 可公开的示例配置                       | 是；本地凭据配置除外       |
| `deploy/`                   | systemd及生产依赖Compose示例           | 是                         |
| `examples/`                 | 可运行的API、Agent和工具示例           | 是                         |
| `scripts/`                  | 稳定的安装、构建、验收与版本校验入口   | 是                         |
| `docs/`                     | 中文文档、目录索引与展示图片           | 是                         |
| `artifacts/benchmarks/`     | GPT原始记录及本地微基准数据            | 是；临时结果`storage/`除外 |
| `artifacts/tests/`          | 保留的JUnit和覆盖率数据                | 是                         |
| `artifacts/security/`       | 依赖审计与许可证报告                   | 是                         |
| `dist/release/0.0.1/`       | 本次发布的PyPI包、安装ZIP及校验表      | 否                         |
| `dist/`其他目录             | 历史构建与离线包，不自动加入发布       | 否                         |
| `.tools/`                   | 本地工具、调试脚本与临时验收环境       | 否                         |
| `.venv/`、`.mvs/`、缓存目录 | 本地依赖与运行数据                     | 否                         |

`src/mvs/web/`由Vite生成，打包时包含在wheel中；日常修改应在`web/src/`进行。
TypeScript构建缓存`*.tsbuildinfo`不提交。用户数据、凭据、工作虚拟环境不作为目录整理的删除对象。

## 版本锁定

当前维护版本为 **0.0.1**，不因新增功能或生成安装包自动递增。
`pyproject.toml`的`project.version`是版本维护依据，以下文件需同步：

- `uv.lock`中本项目的package版本。
- `web/package.json`的项目版本。
- `web/package-lock.json`的顶层和根package版本。
- README、安装教程与当前分发文件名。

运行`uv run python scripts/project_metadata.py`检查一致性。构建脚本先检查这些版本，再选择
`mcp_virtual_shell-0.0.1-py3-none-any.whl`这一明确产物，不按目录中旧wheel的修改时间猜测。
CI也执行版本一致性检查。

版本统一仅调整项目自身标签，不降级业务功能、MCP SDK或第三方依赖，不改写数据库配置revision。
历史测试、模型原始记录和审计文件保留当时版本，不能用批量替换伪造为0.0.1的重新验收。
更新/回滚测试可能使用0.0.2作为虚构目标版本，这不构成发布计划。

## 构建与分发

```bash
uv sync --locked --all-extras
uv run python scripts/project_metadata.py
uv run python scripts/build_release.py
```

当前发布产物在`dist/release/0.0.1/`，PyPI包和安装ZIP分别存放；源码直接从Git仓库推送，
不生成GitHub源码ZIP。历史wheel/ZIP保留在`dist/`和`dist/archive/`。已解压的旧离线包
可能被现有uv工具环境引用为Python路径，保留原位置并标记为历史目录，不能随意移动或删除。
完整离线包按OS/架构单独生成，安装后仍需保留其中Python目录。

目录变化同时更新Markdown相对链接、截图输出位置、脚本输出路径和测试夹具。
新增教程放入`guides/`，接口说明放入`reference/`，测试原始输出放入`artifacts/tests/`。

PyPI源码包使用明确文件范围，不包含研究产物、运行数据、凭据或缓存；GitHub仓库保留研究
结果和完整中文文档。具体步骤见[发布指南](publishing.md)。
