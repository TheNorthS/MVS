# 文档导航

当前项目版本固定为 **0.0.1**。产品介绍和快速开始见[项目首页](../README.md)。

准备提交源码或发布包时，使用[GitHub与PyPI发布指南](development/publishing.md)。
项目仓库为[TheNorthS/MVS](https://github.com/TheNorthS/MVS)，许可证为[MIT](../LICENSE)。

| 目录           | 内容                         | 主要入口                                                                                                                                                                                                        |
| -------------- | ---------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `guides/`      | 安装、接入与运维步骤         | [安装与管理](guides/user_installation.md)、[Linux部署](guides/linux_deployment.md)、[原生命令](guides/native_commands.md)、[生产能力](guides/production_features.md)、[Docker验收](guides/docker_acceptance.md) |
| `reference/`   | 架构、语言、API和安全契约    | [架构](reference/architecture.md)、[命令语言](reference/command_language.md)、[管理API](reference/management_api.md)、[安全边界](reference/security.md)、[可观测性](reference/observability.md)                 |
| `research/`    | 实验设计、复现与统计口径     | [真实模型实验](research/model_benchmark.md)、[本地微基准](research/benchmarks.md)                                                                                                                               |
| `development/` | 维护约定、实施决策与完成状态 | [目录与版本约定](development/repository_layout.md)、[实施决策](development/implementation_decisions.md)、[完成跟踪](development/completion_tracker.md)                                                          |
| `reports/`     | 人类可读的实测记录           | [验收报告](reports/validation_report.md)                                                                                                                                                                        |
| `assets/`      | README与文档使用的图片       | `assets/console/` 保存控制台截图                                                                                                                                                                                |

[原始实施规范](MCP_Virtual_Shell_Codex_Implementation_Spec.md)保留在原路径，便于继续按原始要求审查；[变更记录](CHANGELOG.md)保留在文档根目录。

原始JSON、JUnit与实验逐轮数据存放在[artifacts](../artifacts/README.md)，不与教程混放。
历史报告中的0.1.0、0.2.0、0.3.0是此前开发阶段使用的标签；它们不表示已有公共发布，也不改变当前版本0.0.1。
