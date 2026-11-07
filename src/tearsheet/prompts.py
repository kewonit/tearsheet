"""Research workflows offered as MCP prompts.

Each prompt asks for facts with their units, periods and sources, and for
the gaps to be stated. None of them asks for a buy or sell view, because
Tearsheet doesn't give investment advice.
"""

from mcp.server.mcpserver import MCPServer

RULES = (
    "Rules: quote every figure with its unit and period. Say when a period is TTM or "
    "interim, when data is blank, and when figures are unchecked against filings. "
    "Report every warning the tools return. Don't recommend buying, selling or "
    "holding, and don't predict prices."
)


def earnings_review(company: str) -> str:
    return (
        f"Review the latest results for {company} using the Tearsheet tools.\n"
        "1. Call get_financials with statement quarterly for the last 5 quarters.\n"
        "2. Call get_financials with statement income for the last 3 years.\n"
        "3. Summarise how revenue, operating profit and net profit changed, quarter on "
        "quarter and year on year, using the figures as returned.\n"
        "4. Note one-off items such as unusual other income, and any quarter where a "
        "figure is blank and why.\n"
        f"{RULES}"
    )


def peer_comparison(company: str) -> str:
    return (
        f"Compare {company} with its closest listed peers using the Tearsheet tools.\n"
        "1. Call company_snapshot to see the company and get_business_mix to see what it sells.\n"
        "2. Choose up to four peers in the same business, using get_sector_view or "
        "screen_stocks if needed, and say why each was chosen.\n"
        "3. Call compare_companies with the company and its peers.\n"
        "4. Describe where the company sits on valuation, returns, leverage and growth, "
        "using the summary's minimum, median and maximum.\n"
        f"{RULES}"
    )


def thesis_check(company: str, thesis: str) -> str:
    return (
        f"Check this claim about {company} against the data: {thesis}\n"
        "1. Break the claim into statements that figures can confirm or contradict.\n"
        "2. For each one, call the Tearsheet tool that holds the evidence, such as "
        "get_financials, get_ownership, get_business_mix or get_operating_metrics.\n"
        "3. Mark each statement as supported, contradicted or not checkable with this "
        "data, and give the figures behind each verdict.\n"
        "4. List what you couldn't check.\n"
        f"{RULES}"
    )


def register(server: MCPServer) -> None:
    server.prompt(description="Review a company's latest quarterly and annual results.")(
        earnings_review
    )
    server.prompt(description="Compare a company with its closest listed peers.")(peer_comparison)
    server.prompt(description="Check a claim about a company against the data.")(thesis_check)
