"""Builders for made-up XBRL and PDF filings. No real filing data is used."""

NS = (
    'xmlns:xbrli="http://www.xbrl.org/2003/instance" '
    'xmlns:fin="http://example.com/made-up-taxonomy" '
    'xmlns:xbrldi="http://xbrl.org/2006/xbrldi"'
)


def context(cid, start=None, end="2026-09-30", segment=False):
    period = (
        f"<xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate>"
        if start
        else f"<xbrli:instant>{end}</xbrli:instant>"
    )
    seg = (
        '<xbrli:segment><xbrldi:explicitMember dimension="fin:Seg">fin:A</xbrldi:explicitMember>'
        "</xbrli:segment>"
        if segment
        else ""
    )
    return (
        f'<xbrli:context id="{cid}"><xbrli:entity>'
        f'<xbrli:identifier scheme="x">500001</xbrli:identifier>{seg}</xbrli:entity>'
        f"<xbrli:period>{period}</xbrli:period></xbrli:context>"
    )


def xbrl(
    symbol="ACMEFINE",
    code="500001",
    basis="Consolidated",
    revenue_rupees="1234500000",
    profit_rupees="150000000",
    owners_rupees="140000000",
):
    facts = [
        ("Symbol", "I", symbol),
        ("ScripCode", "I", code),
        ("NameOfTheCompany", "I", "Acme Fine-Chem Limited"),
        ("NatureOfReportStandaloneConsolidated", "I", basis),
        ("DateOfEndOfReportingPeriod", "I", "2026-09-30"),
        ("RevenueFromOperations", "Q", revenue_rupees),
        ("RevenueFromOperations", "H", "9999900000"),
        ("RevenueFromOperations", "S", "1"),
        ("ProfitLossForPeriod", "Q", profit_rupees),
        ("ProfitOrLossAttributableToOwnersOfParent", "Q", owners_rupees),
        ("ProfitBeforeTax", "Q", "not a number"),
    ]
    body = "".join(
        f'<fin:{name} contextRef="{ctx}" unitRef="INR" decimals="-5">{value}</fin:{name}>'
        for name, ctx, value in facts
    )
    contexts = (
        context("I")
        + context("Q", start="2026-07-01")
        + context("H", start="2026-04-01")
        + context("S", start="2026-07-01", segment=True)
    )
    return f'<?xml version="1.0"?><xbrli:xbrl {NS}>{contexts}{body}</xbrli:xbrl>'


def pdf(pages):
    """A minimal valid PDF with one line of text per page."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", ""]
    kids = []
    for text in pages:
        content_id = len(objects) + 2
        page_id = len(objects) + 1
        kids.append(f"{page_id} 0 R")
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {{font}} 0 R >> >> /Contents {content_id} 0 R >>"
        )
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    font_id = len(objects) + 1
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    objects = [o.replace("{font}", str(font_id)) for o in objects]
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out
