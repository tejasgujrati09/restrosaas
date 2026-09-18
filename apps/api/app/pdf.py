"""HTML -> PDF for printable sheets. All interpolated text is escaped."""

from __future__ import annotations

import asyncio
from html import escape

from app.core.money import format_inr

_CSS = """
@page { size: A4; margin: 14mm; }
body { font-family: sans-serif; color: #111; }
h1 { font-size: 20pt; margin: 0 0 4mm; }
h2 { font-size: 14pt; margin: 6mm 0 2mm; border-bottom: 1px solid #999; }
.zone { page-break-after: always; }
.zone:last-child { page-break-after: auto; }
.grid { display: flex; flex-wrap: wrap; gap: 6mm; }
.card { width: 56mm; border: 1px solid #333; padding: 3mm; text-align: center; }
.card svg { width: 44mm; height: 44mm; }
.label { font-size: 16pt; font-weight: bold; }
.hint { font-size: 8pt; color: #444; }
.item { display: flex; justify-content: space-between; padding: 1mm 0; }
.desc { font-size: 8pt; color: #555; }
.foot { margin-top: 8mm; font-size: 8pt; color: #444; }
"""


def _wrap(title: str, body: str) -> str:
    return (
        f"<html><head><meta charset='utf-8'><style>{_CSS}</style></head><body>{body}</body></html>"
    )


def qr_sheet_html(brand: str, zones: dict[str, list[tuple[str, str]]]) -> str:
    """`zones` maps zone name to (table label, inline QR svg). One page per zone."""
    sections = []
    for zone, tables in zones.items():
        cards = "".join(
            f"<div class='card'>{svg}<div class='label'>{escape(label)}</div>"
            f"<div class='hint'>Scan to order</div></div>"
            for label, svg in tables
        )
        sections.append(
            f"<section class='zone'><h1>{escape(brand)} &middot; {escape(zone)}</h1>"
            f"<div class='grid'>{cards}</div></section>"
        )
    return _wrap("QR sheet", "".join(sections))


def menu_html(
    brand: str,
    prices_include_tax: bool,
    categories: list[tuple[str, list[tuple[str, str | None, int, bool]]]],
) -> str:
    """`categories`: (name, [(item name, description, price paise, veg)])."""
    parts = [f"<h1>{escape(brand)}</h1>"]
    for name, items in categories:
        parts.append(f"<h2>{escape(name)}</h2>")
        for item_name, description, price_paise, veg in items:
            mark = "&#9679; " if veg else "&#9650; "
            desc = f"<div class='desc'>{escape(description)}</div>" if description else ""
            parts.append(
                f"<div class='item'><div>{mark}{escape(item_name)}{desc}</div>"
                f"<div>{escape(format_inr(price_paise))}</div></div>"
            )
    note = "Prices include taxes." if prices_include_tax else "Taxes extra, as applicable."
    parts.append(f"<div class='foot'>{note}</div>")
    return _wrap("Menu", "".join(parts))


async def render_pdf(html: str) -> bytes:
    def _render() -> bytes:
        from weasyprint import HTML  # heavy import; only PDF requests pay for it

        return HTML(string=html).write_pdf() or b""

    return await asyncio.to_thread(_render)
