# 实验与验收产物

最新：[DeepSeek V4 Pro 240组报告](benchmarks/deepseek-240-20261125-194449-v0.0.1/report.md)，
236/240成功、2,827,348 Token，4组MVS任务达到8轮上限，无接口异常。
[GPT对照报告](benchmarks/gpt-240-20261125-185218-v0.0.1/report.md)为240/240成功、1,681,974 Token。
每个模型只保留一份正式报告，使用相同任务与口径；原始调用数据用于追溯。

| 目录                                                               | 内容                                         |
| ------------------------------------------------------------------ | -------------------------------------------- |
| [最新GPT实验](benchmarks/gpt-240-20261125-185218-v0.0.1/report.md) | 当前0.0.1的240组有效任务、原始记录与统一报告 |
| [benchmarks/gpt-smoke](benchmarks/gpt-smoke/summary.json)          | 正式实验前的冒烟记录                         |
| [benchmarks/router](benchmarks/router/results.json)                | 不包含模型推理的本地路由微基准               |
| [tests](tests/)                                                    | Docker专项、全量JUnit与最近保存的覆盖率JSON  |
| [security](security/)                                              | Python/npm依赖审计和许可证清单               |

当前GPT评测统一使用最新实验目录；测试与安全报告保留各自验收日期和统计口径。
文档使用的控制台截图已归入[docs/assets/console](../docs/assets/console/)。
新的模型实测使用新输出目录；不要删除失败记录来改写历史成功率。
