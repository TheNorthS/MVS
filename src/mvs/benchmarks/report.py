import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

MODE_LABELS = {
    "native_tools": "原生多工具",
    "json_gateway": "JSON 网关",
    "mvs_shell": "MVS 虚拟命令",
}


def aggregate(records: list[dict]) -> list[dict]:
    groups: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for record in records:
        groups[record["size"], record["mode"]].append(record)
    output = []
    for (size, mode), rows in sorted(groups.items()):
        attempts = [attempt for row in rows for attempt in row["tool_selection_attempts"]]
        usages = [row["usage"] for row in rows if row["usage"] is not None]
        times = sorted(row["latency_ms"] for row in rows)
        complete = all(row["usage_complete"] for row in rows)
        output.append(
            {
                "size": size,
                "mode": mode,
                "episodes": len(rows),
                "task_success_rate": sum(row["success"] for row in rows) / len(rows),
                "tool_selection_accuracy": sum(x["correct_tool"] for x in attempts) / len(attempts)
                if attempts
                else None,
                "argument_validity": sum(x["arguments_valid"] for x in attempts) / len(attempts)
                if attempts
                else None,
                "correct_argument_rate": sum(x["correct_arguments"] for x in attempts)
                / len(attempts)
                if attempts
                else None,
                "selection_attempt_count": len(attempts),
                "usage_complete": complete,
                "provider_failures": sum(
                    bool(row.get("failure")) and row["failure"]["code"].startswith("provider_")
                    for row in rows
                ),
                "measured_episodes": sum(row["usage_complete"] for row in rows),
                "total_tokens": sum(x["total_tokens"] for x in usages) if complete else None,
                "observed_tokens": sum(x["total_tokens"] for x in usages),
                "mean_tokens": statistics.mean(x["total_tokens"] for x in usages)
                if complete
                else None,
                "input_tokens": sum(x["input_tokens"] for x in usages),
                "output_tokens": sum(x["output_tokens"] for x in usages),
                "cached_input_tokens": sum(x["cached_input_tokens"] for x in usages),
                "mean_rounds": statistics.mean(row["interaction_rounds"] for row in rows),
                "mcp_calls": sum(row["mcp_call_count"] for row in rows),
                "median_latency_ms": statistics.median(times),
                "p95_latency_ms": times[max(0, math.ceil(len(times) * 0.95) - 1)],
                "mean_context_growth_tokens": statistics.mean(
                    row["context_growth_tokens"]
                    for row in rows
                    if row["context_growth_tokens"] is not None
                )
                if any(row["context_growth_tokens"] is not None for row in rows)
                else None,
            }
        )
    return output


def paired_comparisons(records: list[dict]) -> list[dict]:
    """Compare identical tasks only; do not silently compare unequal successful subsets."""
    index = {(row["size"], row["mode"], row["task_id"]): row for row in records}
    comparisons = []
    for size in sorted({row["size"] for row in records}):
        for baseline in ("native_tools", "json_gateway"):
            pairs = []
            excluded = []
            for task_id in sorted({row["task_id"] for row in records if row["size"] == size}):
                left = index.get((size, baseline, task_id))
                right = index.get((size, "mvs_shell", task_id))
                if not left or not right:
                    continue
                if not all(row["success"] and row["usage_complete"] for row in (left, right)):
                    excluded.append(task_id)
                    continue
                pairs.append(
                    {
                        "task_id": task_id,
                        "baseline_tokens": left["usage"]["total_tokens"],
                        "mvs_tokens": right["usage"]["total_tokens"],
                        "baseline_rounds": left["interaction_rounds"],
                        "mvs_rounds": right["interaction_rounds"],
                    }
                )
            baseline_total = sum(pair["baseline_tokens"] for pair in pairs)
            mvs_total = sum(pair["mvs_tokens"] for pair in pairs)
            comparisons.append(
                {
                    "size": size,
                    "baseline": baseline,
                    "paired_tasks": len(pairs),
                    "excluded_tasks": excluded,
                    "baseline_tokens": baseline_total,
                    "mvs_tokens": mvs_total,
                    "token_reduction_fraction": 1 - mvs_total / baseline_total
                    if baseline_total
                    else None,
                    "pairs": pairs,
                }
            )
    return comparisons


def write_report(root: Path, manifest: dict, records: list[dict], summary: list[dict]) -> None:
    planned = len(manifest["sizes"]) * len(manifest["modes"]) * manifest["tasks_per_cell"]
    result = {
        "manifest": manifest,
        "completed_episodes": len(records),
        "planned_episodes": planned,
        "complete": len(records) == planned,
        "summary": summary,
        "paired_comparisons": paired_comparisons(records),
    }
    (root / "summary.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    lines = [
        "# GPT 真实模型对照实验",
        "",
        f"请求模型：`{manifest['requested_model']}`；已完成 {len(records)}/{planned} 组。",
        "",
        "| 工具数 | 入口 | 样本 | 成功率 | 选工具准确率 | 参数合法率 | "
        "平均 Token | 平均轮次 | 中位耗时（毫秒） |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    def fmt(value: float | None, percent: bool = False) -> str:
        if value is None:
            return "未完整测得"
        return f"{value:.1%}" if percent else f"{value:.1f}"

    for row in summary:
        lines.append(
            f"| {row['size']} | {MODE_LABELS.get(row['mode'], row['mode'])} | {row['episodes']} | "
            f"{fmt(row['task_success_rate'], True)} | "
            f"{fmt(row['tool_selection_accuracy'], True)} | "
            f"{fmt(row['argument_validity'], True)} | {fmt(row['mean_tokens'])} | "
            f"{fmt(row['mean_rounds'])} | {fmt(row['median_latency_ms'])} |"
        )
    lines.extend(
        [
            "",
            "## 同任务配对比较",
            "",
            "只比较两边均成功且用量记录完整的同一任务；排除数明确列出，不能替代全样本成功率。",
            "",
            "| 工具数 | 对照入口 | 配对任务数 | 排除任务数 | MVS Token 减少比例 |",
            "|---|---|---|---|---|",
        ]
    )
    for comparison in result["paired_comparisons"]:
        lines.append(
            f"| {comparison['size']} | "
            f"{MODE_LABELS.get(comparison['baseline'], comparison['baseline'])} | "
            f"{comparison['paired_tasks']} | {len(comparison['excluded_tasks'])} | "
            f"{fmt(comparison['token_reduction_fraction'], True)} |"
        )
    lines.extend(
        [
            "",
            "模型接口采用 OpenAI Responses 协议，词元（Token）数来自响应的 `usage` 用量字段。",
            "这些数值不是字符数估算。",
            "包含重读历史与工具定义的输入 Token；缓存输入另列，不把缓存量当成免费或省略量。",
            "原始逐轮输出、工具结果、用量、实际 MCP 调用和答案判定保存在 `episodes/`。",
            "首次输入与后续输入 Token 序列表示上下文增长；总 Token 是各轮用量之和。",
            "基准使用合成只读业务任务与真实进程内 MCP；三种入口共用 ShellService 后端。",
            f"每个组合计划 {manifest['tasks_per_cell']} 个任务，且无重复采样，"
            "不能推广为所有业务或模型的收益。",
            "接口代理的返回模型名会记录，但本实验无法独立验证代理后端身份或真实账单。",
            "客户端没有自动重试模型或 MCP 调用；失败记录不会在恢复运行时被悄悄替换。",
        ]
    )
    (root / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
