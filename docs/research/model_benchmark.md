# 真实模型工具入口对照实验

2026-11-25使用`deepseek-v4-pro / low`完成相同240组测试：236组成功，4组MVS任务达到8轮
上限，总用量2,827,348 Token，接口异常为0。任务目录、系统提示、seed、并发和轮次/输出限制
与GPT实验一致，服务端分词和接口兼容细节存在差异。
[DeepSeek报告](../../artifacts/benchmarks/deepseek-240-20261125-194449-v0.0.1/report.md)记录了
这些差异和全部能力错误；参数合法率不会因后续修正而改成100%。

当前0.0.1的GPT评测按240个有效任务执行统计，HTTP 502和网络超时作为接口异常排除，恢复后的
有效执行统一纳入样本。工具选择、参数和答案错误仍属于任务失败。最终240/240成功，
有效执行总用量1,681,974 Token，详见[GPT实验报告](../../artifacts/benchmarks/gpt-240-20261125-185218-v0.0.1/report.md)。
原始调用记录保留用于核对，不另设首次/重试能力报告。

本实验把“模型决定下一步”纳入循环。原 examples/benchmark.py 保留为本地路由微基准，
两者结果不能混用。新入口为 `mvs-benchmark`，实现位于 src/mvs/benchmarks/。

## 三种入口与公平性

| 入口                         | 初始模型工具                     | 发现方式         | 执行方式                       |
| ---------------------------- | -------------------------------- | ---------------- | ------------------------------ |
| 原生多工具（`native_tools`） | 全部 20/50/100/200 个函数 Schema | 初始上下文已给出 | 模型选择函数并生成 JSON        |
| JSON 网关（`json_gateway`）  | 一个 mcp_gateway                 | action=list/help | action=call + tool + arguments |
| MVS 虚拟命令（`mvs_shell`）  | 一个 virtual_shell               | ls/help          | run 或显式路径与 CLI 参数      |

三种入口均使用真实进程内官方 MCP 客户端和服务器。业务执行共用 ShellService 的
Schema 校验、权限策略、执行器、结果存储和返回预览，JSON 和原生入口只把已校验参数适配到这个后端。
不拿“缺少权限与存储的裸 SDK”和“完整 MVS”作功能不等价的主要对照。
原生入口得到完整定义，JSON 列表得到名字/描述，Shell ls 得到名字且 help 才得 Schema，
这些差别正是所比较的工具发现界面。它们会影响输入量和轮次，不应隐藏。

工具集包含 20 种不同业务：库存、价格、订单、物流、账单、汇率、天气、人员、仓库搜索、
客户、API 用量、订阅、税费、路线、积分、容量、健康、预约、文档、工单。参数覆盖整数、
小数、布尔、字符串、数组和嵌套对象。50/100/200 工具通过添加名称相近的历史快照工具扩展。
每个任务要求当前数据，错误选择历史快照会产生不同的答案。

这些都是合成只读业务数据，不会调用外部企业系统，也不会产生真实订单/付款。任务不把
期望工具名或 verification_code 作为隐藏答案注入模型；描述性名字可能容易匹配，因此
这不等于复杂真实业务的选工具难度。该实验也不检验大结果检索/上下文压缩收益。

## 固定条件

- 4 个规模 × 3 种入口 × 20 个任务 = 240 组；每组全新会话。
- 同一个请求模型、推理强度、系统要求和最大输出 Token。
- 每组最多 8 次模型响应，每轮最多执行 8 个工具请求，不自动重试。
- seed=42 固定目录排列和实验顺序；并发默认 4，用于控制运行时长。
- 输出上限默认 2048 Token，累计 Token 软预算默认 5,000,000。
- 软预算在新一组开始前检查；已经在途的最多 4 组可能越过预算。
- 第三次模型接口错误会停止新组，保留所有已完成或失败记录，不静默换模型。
- 不禁用服务端缓存，记录 usage.input_tokens_details.cached_tokens；缓存 Token
  仍包括在 input_tokens 中，不重复相加，也不从总 Token 扣除。

## 运行

```powershell
uv sync --all-extras
$env:OPENAI_BASE_URL = 'https://api.openai.com/v1'
$env:OPENAI_API_KEY = '<在本机设置，不写入仓库>'
uv run mvs-benchmark --model <可用GPT模型ID> --output artifacts/benchmarks/gpt-240-new
```

如果使用本机已有的自定义 OpenAI Responses 提供商配置，可以显式选择它：

```powershell
uv run mvs-benchmark --model gpt-6-astra --codex-config "$env:USERPROFILE/.codex/config.toml" --output artifacts/benchmarks/gpt-240-new --tasks 20 --concurrency 4
```

程序只读取所选接口提供商的 `base_url` 和凭证字段，不会复制配置文件、密钥或原始接口
错误到实验产物。模型请求仅含合成任务、工具定义和执行结果。首次运行前可用
`--sizes 20 200 --tasks 1 --output artifacts/benchmarks/gpt-smoke` 做 6 组冒烟测试。
本次接口的 gpt-5.4-mini 虽在模型列表中，但请求被拒绝；gpt-6-astra 实际请求成功。
正式组固定使用 gpt-6-astra，不把两者结果混合。代理返回的模型标识不等于独立验证后端身份。

运行器恢复：重复相同命令会跳过已有单组记录文件；实验条件清单不一致时报错。接口异常任务
在独立目录恢复执行，汇总按任务ID选择有效完整记录；修改代码或提示词需开始新实验。原始记录
继续保留，最终只维护一份报告。

## DeepSeek接口与复现

DeepSeek官方支持Responses格式和`reasoning.effort=low`，可复用当前运行器。通过进程环境设置
`OPENAI_BASE_URL=https://api.deepseek.com`与对应`OPENAI_API_KEY`，密钥不要写进源码或实验产物。
运行`mvs-benchmark --model deepseek-v4-pro`并明确提供新的`--output`目录即可；其他参数沿用上文。

DeepSeek会忽略`parallel_tool_calls=false`，模型可在同一轮请求多个工具；运行器仍逐个执行，
保留每轮最多8次请求的限制。输出的reasoning记录会随历史传回，usage包含推理输出和缓存输入。
该差异写入实验元数据，不能宣称两家模型的协议行为完全一致。
依据：[Responses兼容说明](https://api-docs.deepseek.com/guides/responses_api/)与
[推理模式](https://api-docs.deepseek.com/guides/thinking_mode/)。

## 指标定义

| 指标                                        | 定义                                                                                            |
| ------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| 任务成功率（`task_success_rate`）           | 最终答案精确等于预期校验码，且实际 MCP 调用了正确工具与正确参数的组数 / 有效任务组              |
| 工具选择准确率（`tool_selection_accuracy`） | 正确目标工具调用尝试数 / 全部目标调用尝试数；不计 ls/help/list 等发现                           |
| 参数合法率（`argument_validity`）           | 通过目标原始 Schema 校验的尝试数 / 全部目标调用尝试数                                           |
| 参数正确率（`correct_argument_rate`）       | 与任务期望参数精确一致的尝试数 / 全部尝试；合法不一定正确                                       |
| 总词元数（`total_tokens`）                  | 逐轮服务端 usage.total_tokens 累计，包含发现和重读历史；不是字符估算                            |
| 输入/输出/缓存词元数                        | 逐轮对应 usage 字段之和，缓存词元已包含在输入词元中                                             |
| 交互轮次（`interaction_rounds`）            | 模型响应次数，包含最后给出答案的一次                                                            |
| MCP 调用数                                  | 真实 tools/call 处理函数收到的次数，区别于模型侧调用 ls/help 次数                               |
| 上下文增长                                  | 每轮 input_tokens 序列，汇总为最后一轮减首轮；另存输入 JSON 字节数                              |
| 延迟                                        | 单组发现、模型、工具和结果持久化耗时；记录中位数，以及按排序位置取整计算的第 95 百分位数（P95） |

未知函数、无法解析的目标命令计无效尝试；纯发现失败不伪装为目标选择。没有任何实际
调用，即使模型碰巧说对校验码，也判任务失败。返回的 `usage` 用量数据缺失则标记测量不完整，不能
用 0 或字符数代替。模型接口超时的实际服务端计费可能未知，因此单独记录。

## 产物与审查

运行器产生下列文件；完成后的最新实验将配置归入`metadata/`、完整性与异常核对归入`audit/`，
有效记录统一保存在`episodes/`。新实验使用新目录，不写入已有报告目录。

- manifest.json：模型、SDK 版本、随机种子、并发、上限、任务摘要哈希、系统提示。
- workload.json：完整任务、全部工具定义及排列，可检查工具选择的难度。
- episodes/*.json：逐轮输出、工具结果、用量、上下文序列、实际 MCP 调用、失败原因。
- summary.json：每格统计结果；report.md：中文汇总表。
- storage/：实验临时结果文件（已 gitignore），不需要作为报告提交。

结果必须同时看成功率、Token 和轮次。在成功率下降时不能单独称省 Token。
报告增加同任务配对表：只保留两边均成功且用量记录完整的同一任务（`task_id`），并列出排除项。
成功率覆盖全部有效任务，能力错误仍保留为失败；接口故障不计入能力评分。最终Token、
轮次、延迟和上下文增长均使用相同有效样本集合，额外接口事件与运行成本只在审计记录中保留。
接口故障的服务端用量可能未知，评测Token不代表完整运行账单。
每格仅 20 个任务，没有重复采样和显著性检验；不能推广到其他模型、其他提示词、复杂多步
业务或真实生产网络。服务端缓存和 4 路并发也影响耗时，Token 不是实际账单金额。
本次实验报告见 [240 组结果](../../artifacts/benchmarks/gpt-240-20261125-185218-v0.0.1/report.md)。

接口依据：[官方函数调用文档](https://developers.openai.com/api/docs/guides/function-calling)
与 [Responses usage 契约](https://developers.openai.com/api/reference/resources/responses/methods/create)。
