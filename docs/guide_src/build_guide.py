"""
Builds docs/odigos_parousiasis.pdf — the run & presentation guide (Greek).

    python docs/guide_src/build_guide.py

Renders docs/guide_src/guide.html with headless Chromium (Playwright) into an
A4 PDF with page numbers. Screenshots are read from docs/guide_src/img/.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

HERE = Path(__file__).resolve().parent
HTML = HERE / "guide.html"
OUT = HERE.parent / "odigos_parousiasis.pdf"


async def main() -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(HTML.resolve().as_uri(), wait_until="networkidle")
        await page.wait_for_timeout(500)
        await page.pdf(
            path=str(OUT),
            format="A4",
            print_background=True,
            margin={"top": "22mm", "bottom": "20mm", "left": "17mm", "right": "17mm"},
            display_header_footer=True,
            header_template=(
                '<div style="font-size:8px;color:#8a8880;width:100%;padding:0 17mm;'
                'font-family:Liberation Sans,Arial,sans-serif;display:flex;'
                'justify-content:space-between">'
                '<span>Ευφυής Πράκτορας Αναπλήρωσης Αποθεμάτων — Οδηγός Εκτέλεσης &amp; Παρουσίασης</span>'
                '<span>Γεώργιος Δράκος · Athens MBA</span></div>'
            ),
            footer_template=(
                '<div style="font-size:8px;color:#8a8880;width:100%;padding:0 17mm;'
                'font-family:Liberation Sans,Arial,sans-serif;text-align:center">'
                'Σελίδα <span class="pageNumber"></span> / <span class="totalPages"></span></div>'
            ),
        )
        await browser.close()
    print(f"PDF written: {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    asyncio.run(main())
