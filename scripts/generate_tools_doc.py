"""Write docs/TOOLS.md from the server's own tool and prompt definitions.

Run after changing a tool:  uv run python scripts/generate_tools_doc.py
A unit test fails if the committed file is out of date.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "docs" / "TOOLS.md"


def _type(schema: dict) -> str:
    if "enum" in schema:
        return "one of " + ", ".join(f"`{v}`" for v in schema["enum"])
    if "anyOf" in schema:
        parts = [_type(s) for s in schema["anyOf"] if s.get("type") != "null"]
        return " or ".join(parts) if parts else "null"
    kind = schema.get("type", "any")
    if kind == "array":
        item = _type(schema.get("items", {}))
        size = []
        if "minItems" in schema:
            size.append(f"at least {schema['minItems']}")
        if "maxItems" in schema:
            size.append(f"at most {schema['maxItems']}")
        return f"list of {item}" + (f" ({', '.join(size)})" if size else "")
    limits = []
    if "minimum" in schema:
        limits.append(f"≥ {schema['minimum']}")
    if "maximum" in schema:
        limits.append(f"≤ {schema['maximum']}")
    if "minLength" in schema:
        limits.append(f"{schema['minLength']}–{schema.get('maxLength', '')} chars")
    elif "maxLength" in schema:
        limits.append(f"≤ {schema['maxLength']} chars")
    return kind + (f" ({', '.join(limits)})" if limits else "")


def _resolve(schema: dict, defs: dict) -> dict:
    ref = schema.get("$ref")
    return defs[ref.rsplit("/", 1)[-1]] if ref else schema


def _description(text: str) -> str:
    paragraphs = [" ".join(p.split()) for p in (text or "").strip().split("\n\n")]
    return "\n\n".join(p for p in paragraphs if p)


def render(tools: list, prompts: list) -> str:
    lines = [
        "# Tools reference",
        "",
        "Generated from the server's tool definitions by `scripts/generate_tools_doc.py`.",
        "Every tool returns the response envelope described in"
        " [ARCHITECTURE.md](ARCHITECTURE.md#response-envelope); `data` holds the type named below.",
        "",
    ]
    for tool in tools:
        schema = tool.input_schema or {}
        defs = schema.get("$defs", {})
        required = set(schema.get("required", []))
        output = (tool.output_schema or {}).get("title", "")
        data_type = output.removeprefix("Envelope[").removesuffix("]") if output else "—"
        lines += [f"## `{tool.name}`", "", _description(tool.description), ""]
        properties = schema.get("properties", {})
        if properties:
            lines += ["| Parameter | Type | Required | Default |", "|---|---|---|---|"]
            for name, prop in properties.items():
                resolved = _resolve(prop, defs)
                default = prop.get("default", resolved.get("default"))
                shown = "—" if name in required else f"`{default!r}`".replace("'", '"')
                yes = "yes" if name in required else "no"
                lines.append(f"| `{name}` | {_type(resolved)} | {yes} | {shown} |")
            lines.append("")
        else:
            lines += ["No parameters.", ""]
        lines += [f"Returns `{data_type}`.", ""]
    lines += ["# Prompts", "", "| Prompt | Arguments | Purpose |", "|---|---|---|"]
    for prompt in prompts:
        arguments = ", ".join(f"`{a.name}`" for a in prompt.arguments or [])
        lines.append(f"| `{prompt.name}` | {arguments} | {prompt.description} |")
    return "\n".join(lines).rstrip() + "\n"


def build() -> str:
    with tempfile.TemporaryDirectory() as home:
        os.environ["TEARSHEET_HOME"] = home
        sys.path.insert(0, str(ROOT / "src"))
        from tearsheet.server import build_server

        server = build_server()
        tools = asyncio.run(server.list_tools())
        prompts = asyncio.run(server.list_prompts())
        return render(tools, prompts)


if __name__ == "__main__":
    OUTPUT.write_text(build())
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")
