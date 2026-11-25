import json
from types import SimpleNamespace

import pytest

from mvs.benchmarks.report import aggregate, paired_comparisons
from mvs.benchmarks.runner import episode, usage_record
from mvs.benchmarks.workload import tasks, tool_result, tools_for


def test_workload_has_real_selection_and_no_oracle_leak():
    cases = tasks()
    assert len(cases) == len({task.tool for task in cases}) == 20
    for size in [20, 50, 100, 200]:
        definitions = tools_for(size)
        assert len(definitions) == len({item["name"] for item in definitions}) == size
        for task in cases:
            assert tool_result(task.tool, task.arguments)["verification_code"] not in task.prompt
    assert (
        usage_record({"usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}})[
            "total_tokens"
        ]
        == 12
    )
    assert usage_record({}) is None


@pytest.mark.parametrize("mode", ["native_tools", "json_gateway", "mvs_shell"])
async def test_agent_loop_uses_real_mcp_and_counts_usage(mode, tmp_path):
    task = tasks()[0]

    class Provider:
        config = SimpleNamespace(model="test-model")
        n = 0

        async def complete(self, instructions, history, tools):
            self.n += 1
            if self.n == 1:
                if mode == "native_tools":
                    name, args = task.tool, task.arguments
                elif mode == "json_gateway":
                    name, args = (
                        "mcp_gateway",
                        {"action": "call", "tool": task.tool, "arguments": task.arguments},
                    )
                else:
                    name, args = (
                        "virtual_shell",
                        {"command": "run /mcp/bench/tools/stock --sku SKU-482 --warehouse north"},
                    )
                output = [
                    {
                        "type": "function_call",
                        "call_id": "call_1",
                        "name": name,
                        "arguments": json.dumps(args),
                    }
                ]
            else:
                assert history[-1]["type"] == "function_call_output"
                assert json.loads(history[-1]["output"])["status"] == "success"
                output = [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": tool_result(task.tool, task.arguments)["verification_code"],
                            }
                        ],
                    }
                ]
            return {
                "id": f"response_{self.n}",
                "model": "test-model",
                "status": "completed",
                "output": output,
                "usage": {
                    "input_tokens": 100 * self.n,
                    "output_tokens": 20,
                    "total_tokens": 100 * self.n + 20,
                },
            }

    record = await episode(Provider(), 20, mode, task, tmp_path, 42, 4)
    assert record["success"] is True
    assert record["mcp_call_count"] == 1
    assert record["usage"]["total_tokens"] == 340
    assert record["context_growth_tokens"] == 100
    assert record["tool_selection_attempts"][0]["arguments_valid"]
    summary = aggregate([record])[0]
    assert summary["total_tokens"] == 340
    assert summary["task_success_rate"] == 1


async def test_hallucinated_answer_without_tool_is_not_success(tmp_path):
    task = tasks()[0]

    class Provider:
        config = SimpleNamespace(model="test-model")

        async def complete(self, *args):
            return {
                "model": "test-model",
                "status": "completed",
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": tool_result(task.tool, task.arguments)["verification_code"],
                            }
                        ],
                    }
                ],
            }

    record = await episode(Provider(), 20, "native_tools", task, tmp_path, 42, 4)
    assert not record["success"]
    assert record["mcp_call_count"] == 0
    assert aggregate([record])[0]["tool_selection_accuracy"] is None


def test_pairing_never_hides_incomplete_or_mismatched_tasks():
    rows = []
    for mode, tokens in [("native_tools", 100), ("mvs_shell", 60)]:
        for task in ["task_a", "task_b"]:
            rows.append(
                {
                    "size": 20,
                    "mode": mode,
                    "task_id": task,
                    "success": True,
                    "usage_complete": True,
                    "usage": {"total_tokens": tokens},
                    "interaction_rounds": 2,
                }
            )
    rows[0]["success"] = False
    result = paired_comparisons(rows)[0]
    assert result["paired_tasks"] == 1
    assert result["excluded_tasks"] == ["task_a"]
    assert result["token_reduction_fraction"] == pytest.approx(0.4)
