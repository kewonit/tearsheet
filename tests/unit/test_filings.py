"""Filing layer tests on made-up filings."""

import asyncio
import json
import os
from datetime import date

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from tearsheet.core.cache import Cache
from tearsheet.core.errors import ErrorCode, TearsheetError
from tearsheet.sources.filings.files import list_filings, resolve_filing
from tearsheet.sources.filings.pdf import page_texts, search_pdf
from tearsheet.sources.filings.xbrl import read_xbrl
from tearsheet.sources.tijori.client import Response
from tearsheet.sources.tijori.financials import FinancialRow, FinancialStatement
from tearsheet.tools import filings as filing_tools
from tests.unit.filing_fixtures import pdf, xbrl

QUARTER = date(2026, 9, 30)


@pytest.fixture
def folder(tmp_path, monkeypatch):
    path = tmp_path / "filings"
    path.mkdir()
    monkeypatch.setenv("TEARSHEET_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TEARSHEET_FILINGS_DIR", str(path))
    return path


def add(folder, name, content):
    target = folder / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content if isinstance(content, bytes) else content.encode())
    return target


def test_only_filings_inside_the_folder_are_listed(folder, tmp_path):
    add(folder, "a.xml", xbrl())
    add(folder, "ACMEFINE/report.pdf", pdf(["x"]))
    add(folder, "notes.txt", "x")
    outside = tmp_path / "secret.pdf"
    outside.write_bytes(pdf(["secret"]))
    os.symlink(outside, folder / "link.pdf")
    names = sorted(p.name for p in list_filings(folder))
    assert names == ["a.xml", "report.pdf"]


@pytest.mark.parametrize(
    "name", ["../secret.pdf", "/etc/passwd", "", "link.pdf", "notes.txt", "missing.pdf"]
)
def test_reading_outside_the_folder_or_odd_files_is_refused(folder, tmp_path, name):
    (tmp_path / "secret.pdf").write_bytes(pdf(["secret"]))
    os.symlink(tmp_path / "secret.pdf", folder / "link.pdf")
    add(folder, "notes.txt", "x")
    with pytest.raises(TearsheetError) as caught:
        resolve_filing(folder, name)
    assert caught.value.code in (ErrorCode.INVALID_INPUT, ErrorCode.NOT_FOUND)


def test_xbrl_metadata(folder):
    filing = read_xbrl(add(folder, "a.xml", xbrl()))
    assert (filing.symbol, filing.scrip_code, filing.basis) == (
        "ACMEFINE",
        "500001",
        "consolidated",
    )
    assert filing.period_end == QUARTER


def test_the_quarter_is_chosen_over_the_half_year_and_converted_to_crore(folder):
    filing = read_xbrl(add(folder, "a.xml", xbrl()))
    assert filing.amount_crore(("RevenueFromOperations",), QUARTER, quarter=True) == (
        123.45,
        "RevenueFromOperations",
    )


def test_dimensioned_breakdowns_are_never_taken_as_the_total(folder):
    filing = read_xbrl(add(folder, "a.xml", xbrl(revenue_rupees="")))
    assert filing.amount_crore(("RevenueFromOperations",), QUARTER, quarter=True) is None


def test_concepts_are_tried_in_order_and_bad_values_skipped(folder):
    filing = read_xbrl(add(folder, "a.xml", xbrl()))
    owners = ("ProfitOrLossAttributableToOwnersOfParent", "ProfitLossForPeriod")
    assert filing.amount_crore(owners, QUARTER, quarter=True)[0] == 14.0
    assert filing.amount_crore(("ProfitBeforeTax",), QUARTER, quarter=True) is None


def test_xml_entity_attacks_are_refused(folder):
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaaaaaaaa">'
        '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]><x>&b;</x>'
    )
    with pytest.raises(TearsheetError) as caught:
        read_xbrl(add(folder, "bomb.xml", bomb))
    assert caught.value.code is ErrorCode.INVALID_INPUT


def test_pdf_search_and_page_ranges(folder):
    path = add(folder, "ACMEFINE/report.pdf", pdf(["Cover page", "Revenue grew strongly", "End"]))
    assert search_pdf(path, "revenue", 5) == [(2, "Revenue grew strongly")]
    assert [n for n, _ in page_texts(path, 2, 99)] == [2, 3]


def test_a_damaged_pdf_is_a_clear_error(folder):
    with pytest.raises(TearsheetError):
        search_pdf(add(folder, "broken.pdf", b"%PDF-1.4 nonsense"), "x", 5)


def run_tool(tool, client=None, **arguments):
    server = MCPServer("test")
    cache = Cache(arguments.pop("cache_path"))
    try:
        filing_tools.register(server, client=client, cache=cache, read_only=None)
        try:
            return asyncio.run(server.call_tool(tool, arguments)).structured_content
        except ToolError as exc:
            return json.loads(str(exc).split(": ", 1)[1])
    finally:
        cache.close()


def test_search_finds_pdf_pages_and_xbrl_figures_for_one_company(folder, tmp_path):
    add(folder, "ACMEFINE/report.pdf", pdf(["Revenue rose", "Nothing"]))
    add(folder, "OTHERCO/report.pdf", pdf(["Revenue fell"]))
    add(folder, "q2.xml", xbrl())
    result = run_tool(
        "search_filings", query="revenue", company="acmefine", cache_path=tmp_path / "c"
    )
    hits = [(h["file"], h["kind"], h["page"]) for h in result["data"]["hits"]]
    assert ("ACMEFINE/report.pdf", "pdf", 1) in hits
    assert ("q2.xml", "xbrl", None) in hits
    assert not [h for h in hits if h[0].startswith("OTHERCO")]
    assert any("third-party" in w for w in result["warnings"])


def test_an_empty_folder_says_how_to_add_filings(folder, tmp_path):
    result = run_tool("search_filings", query="revenue", cache_path=tmp_path / "c")
    assert "Download them by hand" in result["warnings"][0]


def test_read_filing_returns_pages_or_figures(folder, tmp_path):
    add(folder, "ACMEFINE/report.pdf", pdf(["One", "Two", "Three"]))
    add(folder, "q2.xml", xbrl())
    pages = run_tool(
        "read_filing", file="ACMEFINE/report.pdf", pages="2-3", cache_path=tmp_path / "c"
    )
    assert [p["text"] for p in pages["data"]["pages"]] == ["Two", "Three"]
    facts = run_tool("read_filing", file="q2.xml", cache_path=tmp_path / "c")["data"]["facts"]
    assert ["RevenueFromOperations", "1"] not in facts
    assert ["Symbol", "ACMEFINE"] in facts


@pytest.mark.parametrize("pages", ["0", "3-1", "a"])
def test_bad_page_ranges_are_explained(folder, tmp_path, pages):
    add(folder, "r.pdf", pdf(["x"]))
    result = run_tool("read_filing", file="r.pdf", pages=pages, cache_path=tmp_path / "c")
    assert result["code"] == "INVALID_INPUT"


def test_read_filing_refuses_paths_outside_the_folder(folder, tmp_path):
    result = run_tool("read_filing", file="../home/session.json", cache_path=tmp_path / "c")
    assert result["code"] in ("INVALID_INPUT", "NOT_FOUND")


def quarterly(revenue, profit, basis="consolidated"):
    rows = [
        FinancialRow(name="Net Sales", unit="crore", values=[100.0, revenue]),
        FinancialRow(name="Net Profit", unit="crore", values=[10.0, profit]),
    ]
    return FinancialStatement(
        statement="quarterly", basis=basis, periods=["Jun 2026", "Sep 2026"], rows=rows
    )


def test_verification_matches_within_rounding(folder):
    add(folder, "q2.xml", xbrl())
    verification = filing_tools.verify_quarterly(quarterly(123.47, 14.0), "ACMEFINE", "500001")
    assert verification.status == "matched"
    assert "revenue Sep 2026" in verification.detail


def test_verification_reports_a_mismatch_with_both_figures(folder):
    add(folder, "q2.xml", xbrl())
    verification = filing_tools.verify_quarterly(quarterly(130.0, 14.0), "ACMEFINE", "500001")
    assert verification.status == "mismatch"
    assert "Tijori 130.0, filing 123.45" in verification.detail


def test_verification_needs_the_same_basis_and_company(folder):
    add(folder, "q2.xml", xbrl(basis="Standalone"))
    assert (
        filing_tools.verify_quarterly(quarterly(123.45, 14.0), "ACMEFINE", "500001").status
        == "unchecked"
    )
    add(folder, "q2b.xml", xbrl())
    assert (
        filing_tools.verify_quarterly(quarterly(123.45, 14.0), "OTHER", "999").status == "unchecked"
    )


class FinancialsClient:
    def __init__(self, html):
        self.html = html

    async def get(self, path):
        if "advanced_search" in path:
            rows = [{"name": "Acme", "slug": "acme", "scripcode": 500001, "nse symbol": "ACMEFINE"}]
            body = {
                "data": rows if "is_sme=False" in path else [],
                "financial_q": "Market Capitalization > 0",
            }
            return Response(200, json.dumps(body))
        return Response(200, self.html)


def financials_page(revenue):
    rows = [
        {"name": "Net Sales", "value": [100.0, revenue], "sub_section": []},
        {"name": "Net Profit", "value": [10.0, 14.0], "sub_section": []},
    ]
    tables = {
        "qt_c": {"report_dates": ["Jun 2026", "Sep 2026"], "skip_report_dates": [], "data": rows}
    }
    return f'<script id="fin_tables_data" type="application/json">{json.dumps(tables)}</script>'


def test_reconcile_figure_end_to_end(folder, tmp_path):
    add(folder, "q2.xml", xbrl())
    result = run_tool(
        "reconcile_figure",
        client=FinancialsClient(financials_page(123.4)),
        company="ACMEFINE",
        metric="revenue",
        period="Sep 2026",
        cache_path=tmp_path / "c",
    )
    assert result["verification"]["status"] == "matched"
    assert (result["data"]["tijori_crore"], result["data"]["filing_crore"]) == (123.4, 123.45)
    assert result["data"]["filing"] == "q2.xml"


def test_reconcile_without_a_filing_is_unchecked_and_says_why(folder, tmp_path):
    result = run_tool(
        "reconcile_figure",
        client=FinancialsClient(financials_page(123.4)),
        company="ACMEFINE",
        metric="revenue",
        period="Sep 2026",
        cache_path=tmp_path / "c",
    )
    assert result["verification"]["status"] == "unchecked"
    assert "No matching XBRL filing" in result["verification"]["detail"]


def test_reconcile_rejects_a_period_that_is_not_a_quarter_label(folder, tmp_path):
    add(folder, "q2.xml", xbrl())
    result = run_tool(
        "reconcile_figure",
        client=FinancialsClient(financials_page(123.4)),
        company="ACMEFINE",
        metric="revenue",
        period="Q2 FY27",
        cache_path=tmp_path / "c",
    )
    assert result["verification"]["status"] == "unchecked"


def test_an_absolute_path_is_refused_even_inside_the_folder(folder):
    inside = add(folder, "a.pdf", pdf(["x"]))
    with pytest.raises(TearsheetError) as caught:
        resolve_filing(folder, str(inside))
    assert caught.value.code is ErrorCode.INVALID_INPUT
