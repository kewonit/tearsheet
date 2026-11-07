"""The eval harness itself: task file validity and scoring, with no agent runs."""

import asyncio
import importlib.util
import json
from pathlib import Path

from tearsheet.server import build_server

RUN = Path(__file__).resolve().parents[2] / "evals" / "run.py"
spec = importlib.util.spec_from_file_location("evals_run", RUN)
evals = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evals)


def test_the_task_file_is_valid_and_sized(monkeypatch, tmp_path):
    monkeypatch.setenv("TEARSHEET_HOME", str(tmp_path))
    names = {tool.name for tool in asyncio.run(build_server().list_tools())}
    tasks = evals.load_tasks()
    assert evals.validate(tasks, names) == []
    assert len(tasks) >= 30
    assert sum(t["split"] == "held_out" for t in tasks) >= 10


def stream(*events):
    return [json.dumps(e) for e in events]


def test_only_tearsheet_tools_are_counted_and_errors_are_found():
    lines = stream(
        {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "a", "name": "ToolSearch"}]},
        },
        {
            "type": "assistant",
            "message": {
                "content": [{"type": "tool_use", "id": "b", "name": "mcp__tearsheet__find_company"}]
            },
        },
        {
            "type": "user",
            "message": {"content": [{"type": "tool_result", "tool_use_id": "b", "is_error": True}]},
        },
        {
            "type": "result",
            "result": "Done",
            "usage": {"input_tokens": 5, "output_tokens": 7},
            "total_cost_usd": 0.1,
        },
    )
    run = evals.parse_stream(lines)
    assert (run["calls"], run["tool_errors"], run["tokens"], run["answer"]) == (
        ["find_company"],
        1,
        12,
        "Done",
    )


def test_scoring_catches_the_wrong_tool_missing_text_and_advice():
    task = {"first_tool": "find_company", "contains": ["500333"], "max_tool_calls": 1}
    run = {
        "calls": ["get_financials", "find_company"],
        "answer": "You should buy it.",
        "tool_errors": 0,
    }
    failures = evals.score(task, run)
    assert len(failures) == 4


def test_a_good_run_passes():
    task = {"first_tool": "find_company", "contains": ["500333"], "contains_any": ["BSE"]}
    run = {"calls": ["find_company"], "answer": "Its BSE code is 500333.", "tool_errors": 0}
    assert evals.score(task, run) == []
