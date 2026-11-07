"""Run the analyst tasks against Tearsheet with a real agent and score them.

Usage:
    uv run python evals/run.py --split tuning
    uv run python evals/run.py --tasks t-id-01,t-fin-01
    uv run python evals/run.py --validate

Each task is one headless Claude Code session with only Tearsheet connected,
so running tasks costs money. Results go to .local/evals, which is gitignored.

Scoring follows a simple rule: check the exact first tool before trusting
anything fuzzier. Change one tool description at a time, write it by hand,
and re-run on more than one model.
"""

import argparse
import json
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS = Path(__file__).with_name("tasks.toml")
PREFIX = "mcp__tearsheet__"
ADVICE = (
    "you should buy",
    "you should sell",
    "i recommend buying",
    "i recommend selling",
    "i would buy",
    "i would sell",
    "good time to buy",
    "strong buy",
    "go ahead and buy",
)
CHECK_FIELDS = {"first_tool", "tools_include", "contains", "contains_any", "max_tool_calls"}


def load_tasks() -> list[dict]:
    return tomllib.loads(TASKS.read_text())["task"]


def validate(tasks: list[dict], tool_names: set[str]) -> list[str]:
    problems = []
    ids = [t["id"] for t in tasks]
    if len(ids) != len(set(ids)):
        problems.append("task ids are not unique")
    for task in tasks:
        unknown = set(task) - CHECK_FIELDS - {"id", "split", "prompt"}
        if unknown:
            problems.append(f"{task['id']}: unknown fields {sorted(unknown)}")
        if task.get("split") not in ("tuning", "held_out"):
            problems.append(f"{task['id']}: split must be tuning or held_out")
        named = [task.get("first_tool")] + list(task.get("tools_include", []))
        for name in filter(None, named):
            if name not in tool_names:
                problems.append(f"{task['id']}: no tool called {name}")
    return problems


def parse_stream(lines: list[str]) -> dict:
    calls, errors, answer, usage, cost = [], 0, "", {}, None
    names_by_id = {}
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind = event.get("type")
        content = (event.get("message") or {}).get("content")
        if kind == "assistant" and isinstance(content, list):
            for block in content:
                if block.get("type") == "tool_use" and block.get("name", "").startswith(PREFIX):
                    calls.append(block["name"].removeprefix(PREFIX))
                    names_by_id[block.get("id")] = block["name"]
        elif kind == "user" and isinstance(content, list):
            for block in content:
                if block.get("type") == "tool_result" and block.get("tool_use_id") in names_by_id:
                    errors += bool(block.get("is_error"))
        elif kind == "result":
            answer = str(event.get("result") or "")
            usage = event.get("usage") or {}
            cost = event.get("total_cost_usd")
    tokens = sum(
        usage.get(key) or 0
        for key in (
            "input_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
            "output_tokens",
        )
    )
    return {
        "calls": calls,
        "tool_errors": errors,
        "answer": answer,
        "tokens": tokens,
        "cost_usd": cost,
    }


def score(task: dict, run: dict) -> list[str]:
    failures = []
    answer = run["answer"].lower()
    calls = run["calls"]
    if task.get("first_tool") and (not calls or calls[0] != task["first_tool"]):
        failures.append(f"first tool was {calls[0] if calls else 'none'}, not {task['first_tool']}")
    for tool in task.get("tools_include", []):
        if tool not in calls:
            failures.append(f"never called {tool}")
    for text in task.get("contains", []):
        if text.lower() not in answer:
            failures.append(f"answer lacks {text!r}")
    options = task.get("contains_any")
    if options and not any(o.lower() in answer for o in options):
        failures.append("answer lacks all of the expected phrases")
    if len(calls) > task.get("max_tool_calls", 10):
        failures.append(f"{len(calls)} tool calls, over the budget of {task['max_tool_calls']}")
    for phrase in ADVICE:
        if phrase in answer:
            failures.append(f"gave advice: {phrase!r}")
    if not run["answer"]:
        failures.append("no answer")
    return failures


def run_task(task: dict, config: Path, model: str | None) -> dict:
    command = [
        "claude", "-p", task["prompt"],
        "--mcp-config", str(config), "--strict-mcp-config",
        "--allowedTools", "mcp__tearsheet",
        "--max-turns", "15", "--output-format", "stream-json", "--verbose",
    ]  # fmt: skip
    if model:
        command += ["--model", model]
    started = time.monotonic()
    process = subprocess.run(
        command, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=600
    )
    run = parse_stream(process.stdout.splitlines())
    run["seconds"] = round(time.monotonic() - started, 1)
    run["failures"] = score(task, run)
    return run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--split", choices=["tuning", "held_out", "all"], default="tuning")
    parser.add_argument("--tasks", help="comma-separated task ids, overriding --split")
    parser.add_argument("--model")
    parser.add_argument("--validate", action="store_true", help="check the task file and exit")
    args = parser.parse_args()

    tasks = load_tasks()
    sys.path.insert(0, str(ROOT / "src"))
    import asyncio

    from tearsheet.server import build_server  # noqa: E402

    names = {tool.name for tool in asyncio.run(build_server().list_tools())}
    problems = validate(tasks, names)
    if problems or args.validate:
        print("\n".join(problems) or f"{len(tasks)} tasks are valid.")
        return 1 if problems else 0

    if args.tasks:
        wanted = set(args.tasks.split(","))
        tasks = [t for t in tasks if t["id"] in wanted]
    elif args.split != "all":
        tasks = [t for t in tasks if t["split"] == args.split]

    out_dir = ROOT / ".local" / "evals"
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        server = {"command": "uv", "args": ["--directory", str(ROOT), "run", "tearsheet"]}
        json.dump({"mcpServers": {"tearsheet": server}}, handle)
        config = Path(handle.name)

    results = []
    try:
        for task in tasks:
            run = run_task(task, config, args.model)
            results.append({"id": task["id"], "split": task["split"], **run})
            status = "pass" if not run["failures"] else "FAIL: " + "; ".join(run["failures"])
            print(f"{task['id']:10} {len(run['calls'])} calls  {run['tokens']:>7} tokens  {status}")
    finally:
        config.unlink(missing_ok=True)

    passed = sum(not r["failures"] for r in results)
    report = out_dir / f"run-{time.strftime('%Y%m%d-%H%M%S')}.json"
    report.write_text(json.dumps(results, indent=2))
    if results:
        print(
            f"\n{passed}/{len(results)} passed | "
            f"{sum(len(r['calls']) for r in results) / len(results):.1f} tool calls and "
            f"{sum(r['tokens'] for r in results) / len(results):,.0f} tokens per task | "
            f"{sum(r['tool_errors'] for r in results)} tool errors | "
            f"${sum(r['cost_usd'] or 0 for r in results):.2f}\nDetails: {report}"
        )
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
