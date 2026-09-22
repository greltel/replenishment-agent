"""
Generates Παράρτημα Δ — Τεχνικός Οδηγός Υλοποίησης.

A comprehensive PDF guide explaining:
  • Architecture & design decisions
  • All modules (data, agent, MRP, rules, copilot, dashboard)
  • Recent additions (Bootstrap CI, Rule Ablation, Forecast Dashboard)
  • How to read the code & extend it
  • Defense-ready talking points

Designed to be read by the thesis author to understand WHAT was built
and WHY each piece exists.
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT, TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle,
    KeepTogether, Image, ListFlowable, ListItem,
)


# ============================================================
# Font registration (DejaVu supports Greek)
# ============================================================
def register_fonts():
    """Register DejaVu fonts which support Greek characters."""
    try:
        pdfmetrics.registerFont(TTFont(
            "DejaVu", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        ))
        pdfmetrics.registerFont(TTFont(
            "DejaVu-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        ))
        pdfmetrics.registerFont(TTFont(
            "DejaVu-Italic", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"
        ))
        pdfmetrics.registerFont(TTFont(
            "DejaVu-Mono", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
        ))
        return "DejaVu", "DejaVu-Bold", "DejaVu-Italic", "DejaVu-Mono"
    except Exception:
        return "Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Courier"


# ============================================================
# Styles
# ============================================================
def make_styles():
    base, bold, italic, mono = register_fonts()
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "MyTitle", parent=styles["Title"],
        fontName=bold, fontSize=22, leading=28,
        spaceAfter=12, textColor=colors.HexColor("#1a365d"),
        alignment=TA_CENTER,
    )

    subtitle_style = ParagraphStyle(
        "MySubtitle", parent=styles["Normal"],
        fontName=italic, fontSize=12, leading=18,
        textColor=colors.HexColor("#4a5568"),
        alignment=TA_CENTER, spaceAfter=24,
    )

    h1 = ParagraphStyle(
        "H1", parent=styles["Heading1"],
        fontName=bold, fontSize=16, leading=22,
        textColor=colors.HexColor("#1a365d"),
        spaceBefore=18, spaceAfter=10,
    )

    h2 = ParagraphStyle(
        "H2", parent=styles["Heading2"],
        fontName=bold, fontSize=13, leading=18,
        textColor=colors.HexColor("#2c5282"),
        spaceBefore=12, spaceAfter=8,
    )

    h3 = ParagraphStyle(
        "H3", parent=styles["Heading3"],
        fontName=bold, fontSize=11, leading=16,
        textColor=colors.HexColor("#2d3748"),
        spaceBefore=8, spaceAfter=4,
    )

    body = ParagraphStyle(
        "Body", parent=styles["Normal"],
        fontName=base, fontSize=10, leading=14,
        alignment=TA_JUSTIFY, spaceAfter=6,
    )

    code = ParagraphStyle(
        "Code", parent=styles["Code"],
        fontName=mono, fontSize=8, leading=11,
        leftIndent=12, rightIndent=12,
        backColor=colors.HexColor("#f1f5f9"),
        borderColor=colors.HexColor("#cbd5e0"),
        borderWidth=0.5, borderPadding=6,
        spaceBefore=4, spaceAfter=6,
    )

    note = ParagraphStyle(
        "Note", parent=styles["Normal"],
        fontName=italic, fontSize=9, leading=12,
        textColor=colors.HexColor("#4a5568"),
        leftIndent=20, rightIndent=20,
        spaceBefore=4, spaceAfter=8,
    )

    callout = ParagraphStyle(
        "Callout", parent=styles["Normal"],
        fontName=base, fontSize=10, leading=14,
        leftIndent=10, rightIndent=10,
        backColor=colors.HexColor("#fef3c7"),
        borderColor=colors.HexColor("#f59e0b"),
        borderWidth=0.5, borderPadding=8,
        spaceBefore=6, spaceAfter=8,
    )

    return dict(
        title=title_style, subtitle=subtitle_style,
        h1=h1, h2=h2, h3=h3,
        body=body, code=code, note=note, callout=callout,
        base=base, bold=bold, italic=italic, mono=mono,
    )


# ============================================================
# Helper functions
# ============================================================
def P(text, style):
    """Paragraph shortcut."""
    return Paragraph(text, style)


def code_block(text, style):
    """Multi-line code block. Pre-escapes <, >, &."""
    text = (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))
    # Preserve line breaks
    text = text.replace("\n", "<br/>")
    # Preserve indentation
    text = text.replace("  ", "&nbsp;&nbsp;")
    return Paragraph(text, style)


def make_table(data, col_widths=None, header_color="#1a365d"):
    """Standard styled table."""
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_color)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "DejaVu-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTNAME", (0, 1), (-1, -1), "DejaVu"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    return t


# ============================================================
# Content builder
# ============================================================
def build_content(styles: dict) -> list:
    """Build the entire PDF content as a flowables list."""
    story = []

    # ─── COVER PAGE ───
    story.append(Spacer(1, 4*cm))
    story.append(P("ΠΑΡΑΡΤΗΜΑ Δ", styles["title"]))
    story.append(P("Τεχνικός Οδηγός Υλοποίησης", styles["title"]))
    story.append(Spacer(1, 0.5*cm))
    story.append(P(
        "Ευφυής Πράκτορας Αναπλήρωσης Αποθεμάτων<br/>"
        "με Διασύνδεση SAP",
        styles["subtitle"]
    ))
    story.append(Spacer(1, 3*cm))

    cover_table_data = [
        ["Φοιτητής:",      "George Drakos"],
        ["Επιβλέπων:",     "Σωτήρης Γκαγιαλής (ΕΜΠ Μηχανολόγων)"],
        ["Πρόγραμμα:",     "ΔΔΠΜΣ Athens MBA (ΟΠΑ + ΕΜΠ)"],
        ["GitHub:",        "github.com/greltel/replenishment-agent"],
        ["Έκδοση Project:", "v1.0 (μετά Bootstrap CI, Rule Ablation, Forecast)"],
        ["Tests:",         "183/183 passing"],
        ["LOC:",           "~7,500 Python + ABAP"],
    ]
    cover_table = Table(cover_table_data, colWidths=[5*cm, 9*cm])
    cover_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "DejaVu-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "DejaVu"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#2c5282")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(cover_table)
    story.append(PageBreak())

    # ─── INTRODUCTION ───
    story.append(P("Σκοπός Αυτού του Οδηγού", styles["h1"]))
    story.append(P(
        "Το παρόν παράρτημα συνοδεύει τη Διπλωματική Εργασία και τεκμηριώνει "
        "λεπτομερώς την τεχνική υλοποίηση του ευφυούς πράκτορα αναπλήρωσης "
        "αποθεμάτων. Ο στόχος είναι ο αναγνώστης — είτε επιβλέπων είτε "
        "μέλος της τριμελούς επιτροπής — να μπορεί να κατανοήσει: "
        "(α) τι ακριβώς υλοποιήθηκε, (β) γιατί επιλέχθηκε αυτή η αρχιτεκτονική, "
        "(γ) πώς να αναπαράγει τα αποτελέσματα.", styles["body"]
    ))
    story.append(Spacer(1, 6))
    story.append(P(
        "Το έγγραφο διαχωρίζεται σε εννέα ενότητες που ακολουθούν τη "
        "λογική ροή του project: από την αρχιτεκτονική, στα δεδομένα, "
        "στον αλγόριθμο, στα rules, στην αξιολόγηση, και τέλος στις προσθήκες "
        "που αναβαθμίζουν τη ΔΕ σε εξαιρετικού επιπέδου εργασία (Bootstrap "
        "Confidence Intervals, Rule Ablation Study, Demand Forecast Dashboard, "
        "AI Copilot).", styles["body"]
    ))

    story.append(P("Πίνακας Περιεχομένων", styles["h2"]))
    toc_data = [
        ["1.", "Αρχιτεκτονική Συστήματος"],
        ["2.", "Επίπεδο Δεδομένων (Data Layer)"],
        ["3.", "Πράκτορας BDI (Agent)"],
        ["4.", "MRP & Lot Sizing"],
        ["5.", "Επιχειρησιακοί Κανόνες (Rules)"],
        ["6.", "Αξιολόγηση (Backtest) με Πολλαπλά Σενάρια"],
        ["7.", "Νέα Προσθήκη: Bootstrap Confidence Intervals"],
        ["8.", "Νέα Προσθήκη: Rule Ablation Study"],
        ["9.", "Νέα Προσθήκη: Demand Forecast Dashboard"],
        ["10.", "AI Copilot (Ollama-based)"],
        ["11.", "Πώς να Τρέξετε τον Κώδικα — Βήμα προς Βήμα"],
        ["12.", "Defense-Ready Σημεία Συζήτησης"],
    ]
    toc_table = Table(toc_data, colWidths=[1.5*cm, 14*cm])
    toc_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "DejaVu"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#2c5282")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(toc_table)
    story.append(PageBreak())

    # ============================================================
    # SECTION 1 — ARCHITECTURE
    # ============================================================
    story.append(P("1. Αρχιτεκτονική Συστήματος", styles["h1"]))

    story.append(P(
        "Το σύστημα ακολουθεί <b>τρι-επίπεδη αρχιτεκτονική</b> (three-tier "
        "architecture), σχεδιασμένη για offline λειτουργία και απόλυτη "
        "ασφάλεια εταιρικών δεδομένων:", styles["body"]
    ))
    arch_table = [
        ["Επίπεδο", "Τεχνολογία", "Ρόλος"],
        ["Παρουσίαση",      "Streamlit Dashboard",       "Visualization 6 tabs"],
        ["Λογική",          "Python BDI Agent",          "Perception → Deliberation → Action"],
        ["Δεδομένων",       "SQLite + SQLAlchemy ORM",   "Persistence, ETL από SAP CSV"],
    ]
    story.append(make_table(arch_table, col_widths=[3*cm, 5*cm, 7*cm]))
    story.append(Spacer(1, 8))

    story.append(P("1.1 Ροή Δεδομένων", styles["h2"]))
    story.append(code_block(
        "[SAP ERP]                                  \n"
        "    │ ZMRP_AGENT_EXPORT.abap                \n"
        "    ▼                                       \n"
        "data/raw/*.csv  (MARA, MARC, MARD, EKKO,    \n"
        "                  EKPO, MB51)               \n"
        "    │ src/data_layer/anonymization.py       \n"
        "    ▼                                       \n"
        "data/anonymized/*.csv  (pseudonymized)      \n"
        "    │ scripts/run_etl.py                    \n"
        "    ▼                                       \n"
        "replenishment.db  (SQLite)                  \n"
        "    │ scripts/run_agent.py                  \n"
        "    ▼                                       \n"
        "Proposals (DB) → Dashboard / Copilot",
        styles["code"]
    ))

    story.append(P("1.2 Γιατί Αυτή η Αρχιτεκτονική;", styles["h2"]))
    arch_reasons = [
        "<b>Security &amp; Privacy:</b> Τα εταιρικά δεδομένα παραμένουν στο "
        "local SQLite. Καμία απευθείας σύνδεση με production SAP system, "
        "ώστε να μη δημιουργείται φόρτος ή κίνδυνος.",

        "<b>Reproducibility:</b> Όλη η ροή είναι deterministic. Με ίδια "
        "δεδομένα και ίδιο seed, ο πράκτορας παράγει πάντα τις ίδιες "
        "προτάσεις. Κρίσιμο για ακαδημαϊκή έρευνα.",

        "<b>Modularity:</b> Κάθε επίπεδο είναι ανεξάρτητο. Μπορώ να αλλάξω "
        "το data layer (π.χ., από SQLite σε PostgreSQL) χωρίς να αγγίξω "
        "τον agent.",

        "<b>Testability:</b> Το data layer είναι in-memory στα tests "
        "(<font face='DejaVu-Mono'>sqlite:///:memory:</font>), επιτρέποντας "
        "ταχύτατη εκτέλεση 183 unit tests σε ~17 δευτερόλεπτα.",
    ]
    for r in arch_reasons:
        story.append(P("• " + r, styles["body"]))

    story.append(P("1.3 Δομή Φακέλων", styles["h2"]))
    story.append(code_block(
        "replenishment-agent/\n"
        "├── src/                          # Κύριο πακέτο\n"
        "│   ├── config.py                 # Κεντρικές ρυθμίσεις\n"
        "│   ├── data_layer/               # SQLAlchemy models, ETL\n"
        "│   ├── agent/                    # BDI implementation\n"
        "│   ├── mrp/                      # MRP engine + lot sizing\n"
        "│   ├── rules/                    # Business rules\n"
        "│   ├── copilot/                  # AI Copilot (Ollama)\n"
        "│   └── utils/                    # KPIs, forecasting, bootstrap\n"
        "├── dashboard/                    # Streamlit (6 tabs)\n"
        "├── scripts/                      # CLI entry points\n"
        "├── tests/                        # 183 pytest tests\n"
        "├── abap/                         # SAP extractor program\n"
        "├── data/                         # raw / anonymized / samples\n"
        "└── docs/                         # Τεκμηρίωση",
        styles["code"]
    ))
    story.append(PageBreak())

    # ============================================================
    # SECTION 2 — DATA LAYER
    # ============================================================
    story.append(P("2. Επίπεδο Δεδομένων", styles["h1"]))

    story.append(P("2.1 Πηγαία Δεδομένα από SAP", styles["h2"]))
    story.append(P(
        "Το ABAP πρόγραμμα <font face='DejaVu-Mono'>ZMRP_AGENT_EXPORT</font> "
        "εξάγει 6 πίνακες από το SAP σε μορφή CSV:", styles["body"]
    ))
    sap_tables = [
        ["SAP Table", "Περιεχόμενο", "Χρήση στο Project"],
        ["MARA",  "General material master",     "material_id, type, UoM, weight"],
        ["MAKT",  "Material descriptions",       "Περιγραφή υλικού (multi-language)"],
        ["MARC",  "Material per plant",          "MRP type, lead time, safety stock"],
        ["MARD",  "Stock per storage location",  "Διαθέσιμο απόθεμα ανά location"],
        ["EKKO",  "PO header",                   "Vendor, currency, PO date"],
        ["EKPO",  "PO line items",               "Quantity, expected delivery date"],
        ["MB51 (MSEG+MKPF)", "Material movements", "Goods receipts &amp; issues"],
    ]
    story.append(make_table(sap_tables, col_widths=[3*cm, 5*cm, 7*cm]))
    story.append(Spacer(1, 8))

    story.append(P(
        "<b>Τεχνική σημείωση για το ABAP:</b> Το extractor κάνει LEFT OUTER "
        "JOIN ανάμεσα σε MARA και MAKT για να φέρει τις περιγραφές των υλικών, "
        "με προτεραιότητα στη γλώσσα που επιλέγει ο χρήστης (παράμετρος "
        "<font face='DejaVu-Mono'>p_lang</font>) και fallback στα Αγγλικά. "
        "Το MB51 χρησιμοποιεί το πεδίο SHKZG (S=Soll/Debit για receipts, "
        "H=Haben/Credit για issues) για να καθορίσει το πρόσημο της ποσότητας — "
        "λάθος που συναντάται συχνά σε ad-hoc ABAP scripts.", styles["body"]
    ))

    story.append(P("2.2 Anonymization (GDPR/Privacy)", styles["h2"]))
    story.append(P(
        "Το <font face='DejaVu-Mono'>src/data_layer/anonymization.py</font> "
        "μετατρέπει τα raw SAP exports σε ανωνυμοποιημένα CSV που μπορούν "
        "να χρησιμοποιηθούν για ακαδημαϊκούς σκοπούς:", styles["body"]
    ))
    anon_table = [
        ["Πεδίο", "Αρχικό", "Μετά"],
        ["Material number",  "000000000000020084",  "MAT9103C8C8 (MD5-based)"],
        ["Plant",            "GB19",                "PLT5A2F"],
        ["Supplier",         "0000100123",          "SUP7B2E2A91"],
        ["Description",      "PVC ring 2mm 1.5kg",  "Διατηρείται ως έχει"],
    ]
    story.append(make_table(anon_table, col_widths=[4*cm, 5*cm, 6*cm]))
    story.append(Spacer(1, 6))
    story.append(P(
        "<b>Deterministic pseudonymization:</b> Χρησιμοποιείται MD5 hash του "
        "πραγματικού κωδικού (8-char prefix). Έτσι κάθε φορά που τρέχει το "
        "anonymization, το ίδιο υλικό παίρνει το ίδιο pseudonym — διατηρώντας "
        "join consistency μεταξύ πινάκων.", styles["body"]
    ))

    story.append(P("2.3 SAP Parsers — Defensive Engineering", styles["h2"]))
    story.append(P(
        "Τα SAP exports έχουν ιδιαιτερότητες που σπάνε naive parsing:", styles["body"]
    ))
    parsers_list = [
        "<b>Trailing minus:</b> '3.000-' σημαίνει −3000 (όχι Python ValueError)",
        "<b>European format:</b> '1.234,56' σημαίνει 1234.56",
        "<b>YYYYMMDD dates:</b> '20260508' πρέπει να γίνει 2026-05-08",
        "<b>Empty cells:</b> Στο SAP εμφανίζονται ως spaces, όχι NULL",
    ]
    for p in parsers_list:
        story.append(P("• " + p, styles["body"]))

    story.append(P(
        "Όλα αυτά αντιμετωπίζονται στο "
        "<font face='DejaVu-Mono'>src/data_layer/sap_parsers.py</font>, "
        "που έχει 33 dedicated unit tests.", styles["body"]
    ))

    story.append(P("2.4 Smart Defaults για Ελλιπές Master Data", styles["h2"]))
    story.append(P(
        "Πολλά SAP περιβάλλοντα (ιδίως sandbox/demo) έχουν κενά κρίσιμα MRP "
        "πεδία (PLIFZ, EISBE, BSTMI). Το module "
        "<font face='DejaVu-Mono'>master_data_enrichment.py</font> "
        "υπολογίζει smart defaults από ιστορικά δεδομένα:", styles["body"]
    ))
    enrichment_table = [
        ["Πεδίο", "Πηγή 1 (αν υπάρχει)", "Πηγή 2 (derived)"],
        ["Lead time",       "MARC.PLIFZ", "PO history ή 14 days"],
        ["Safety stock",    "MARC.EISBE", "z × σ × √LT (Silver-Pyke-Peterson)"],
        ["Reorder point",   "MARC.MINBE", "avg_daily × LT + SS"],
        ["MOQ",             "MARC.BSTMI", "Median PO qty"],
        ["Lot sizing",      "MARC.DISLS", "Από CV: WW/POQ/EOQ/FOQ"],
        ["ABC class",       "—",          "Pareto στο cost × annual_demand"],
    ]
    story.append(make_table(enrichment_table, col_widths=[3.5*cm, 4.5*cm, 7*cm]))

    story.append(P("Παράδειγμα Safety Stock derivation:", styles["h3"]))
    story.append(code_block(
        "SS = z × σ_LT × √LT\n"
        "\n"
        "όπου:\n"
        "  z   = service-level z-score (0.98 → 2.054)\n"
        "  σ_LT = std-dev της ημερήσιας ζήτησης\n"
        "  LT  = lead time σε ημέρες\n"
        "\n"
        "Αναφορά: Silver, Pyke & Peterson (1998), ch. 7",
        styles["code"]
    ))
    story.append(PageBreak())

    # ============================================================
    # SECTION 3 — BDI AGENT
    # ============================================================
    story.append(P("3. Πράκτορας BDI", styles["h1"]))

    story.append(P(
        "Η αρχιτεκτονική BDI (Beliefs-Desires-Intentions) είναι το standard "
        "model για ευφυείς πράκτορες (Bratman 1987, Rao &amp; Georgeff 1995). "
        "Στο project μας υλοποιείται με 3 διακριτά components:", styles["body"]
    ))

    bdi_table = [
        ["Component", "Τι Είναι", "Module"],
        ["Beliefs",     "Τρέχουσα κατάσταση κόσμου (stock, POs, history)",
         "src/agent/base.py: AgentBeliefs"],
        ["Desires",     "Επιθυμητοί στόχοι (e.g., target service level)",
         "src/agent/base.py: AgentDesires"],
        ["Intentions",  "Δεσμευμένες αποφάσεις για δράση (proposals)",
         "src/agent/base.py: AgentIntention"],
    ]
    story.append(make_table(bdi_table, col_widths=[2.8*cm, 6*cm, 6.2*cm]))
    story.append(Spacer(1, 8))

    story.append(P("3.1 Κύκλος Εκτέλεσης (Run Cycle)", styles["h2"]))
    story.append(code_block(
        "def run_cycle(self):\n"
        "    # 1. PERCEPTION: αναγνώριση κόσμου\n"
        "    self.perceive()    # → self.beliefs\n"
        "\n"
        "    # 2. DELIBERATION: αποφάσεις\n"
        "    self.deliberate()  # → self.intentions\n"
        "\n"
        "    # 3. ACTION: persistence των αποφάσεων\n"
        "    self.act()         # → DB (proposals table)",
        styles["code"]
    ))

    story.append(P("3.2 Perception Module", styles["h2"]))
    story.append(P(
        "Το PerceptionModule φορτώνει από τη βάση δεδομένων όλα τα δεδομένα "
        "που χρειάζεται ο agent ώστε να αποφασίσει: τρέχοντα αποθέματα, "
        "ανοιχτές παραγγελίες, ιστορικά κινήσεων κατανάλωσης. Σημαντική "
        "λεπτομέρεια: χρησιμοποιεί το <font face='DejaVu-Mono'>as_of_date</font> "
        "ώστε να μπορεί να τρέξει σε ιστορικά παράθυρα (απαραίτητο για το "
        "backtest).", styles["body"]
    ))

    story.append(P("3.3 Deliberation Module", styles["h2"]))
    story.append(P(
        "Ο πυρήνας της λογικής. Για κάθε υλικό:", styles["body"]
    ))
    delib_steps = [
        "1. <b>Forecast demand</b> — εκτίμηση ζήτησης για τον horizon "
        "(default 60 ημέρες)",

        "2. <b>Run MRP</b> — υπολογισμός net requirements ανά περίοδο, "
        "λαμβάνοντας υπόψη stock, open POs, και safety stock",

        "3. <b>Apply lot sizing</b> — μετατροπή net requirements σε "
        "ποσότητα παραγγελίας (LFL/FOQ/EOQ/POQ/Wagner-Whitin)",

        "4. <b>Apply business rules</b> — εμπλουτισμός/τροποποίηση των "
        "προτάσεων με τους 7 κανόνες (βλ. Ενότητα 5)",

        "5. <b>Build Intentions</b> — δημιουργία τελικών proposals με "
        "ημερομηνία, ποσότητα, και rule audit trail",
    ]
    for s in delib_steps:
        story.append(P(s, styles["body"]))

    story.append(P("3.4 Action Module", styles["h2"]))
    story.append(P(
        "Persists τα intentions στον πίνακα <font face='DejaVu-Mono'>proposals</font> "
        "της βάσης. Κρίσιμη λεπτομέρεια: κάθε φορά που τρέχει ο agent, "
        "διαγράφει τα παλιά proposals και ξαναγράφει — αποφεύγοντας stale data "
        "και ομοίως διασφαλίζοντας ότι το dashboard βλέπει πάντα την τρέχουσα "
        "κατάσταση.", styles["body"]
    ))
    story.append(PageBreak())

    # ============================================================
    # SECTION 4 — MRP & Lot Sizing
    # ============================================================
    story.append(P("4. MRP &amp; Lot Sizing", styles["h1"]))

    story.append(P("4.1 MRP Engine", styles["h2"]))
    story.append(P(
        "Το MRP engine υλοποιεί το κλασικό time-phased planning (Vollmann et al. "
        "2005). Για κάθε υλικό, παράγει έναν πίνακα ανά ημέρα στον horizon με:", styles["body"]
    ))
    mrp_cols = [
        ["Στήλη", "Σημασία"],
        ["period",              "Ημερομηνία"],
        ["gross_requirement",   "Προβλεπόμενη ζήτηση εκείνη την ημέρα"],
        ["scheduled_receipt",   "Ανοιχτές παραγγελίες (POs) που φτάνουν εκείνη την ημέρα"],
        ["planned_arrival_qty", "Προτεινόμενες παραγγελίες που φτάνουν εκείνη την ημέρα"],
        ["projected_on_hand",   "Προβλεπόμενο απόθεμα στο τέλος της ημέρας"],
        ["net_requirement",     "Έλλειμμα έναντι του safety stock που πρέπει να καλυφθεί"],
        ["planned_receipt",     "Ποσότητα που αποφασίζεται εκείνη την ημέρα (μετά το lot sizing)"],
        ["planned_release",     "Ημερομηνία έκδοσης παραγγελίας (άφιξη − lead time, όχι στο παρελθόν)"],
        ["planned_arrival",     "Ημερομηνία άφιξης (= period, ή σήμερα + LT αν η ανάγκη είναι εντός LT)"],
        ["below_safety",        "Σήμανση ημερών με απόθεμα κάτω από το safety stock"],
    ]
    story.append(make_table(mrp_cols, col_widths=[4.5*cm, 10.5*cm]))
    story.append(P(
        "<b>Επίγνωση lead time.</b> Ανάγκη που εμφανίζεται μέσα στο lead time δεν "
        "μπορεί να καλυφθεί εγκαίρως: η νωρίτερη δυνατή άφιξη νέας παραγγελίας είναι "
        "«σήμερα + LT». Το engine υπολογίζει το έλλειμμα που προβάλλεται σε εκείνη "
        "την ημερομηνία (αφού συνυπολογίσει όλες τις ενδιάμεσες παραλαβές και "
        "αναλώσεις), εκδίδει <b>μία</b> παραγγελία και την καταχωρεί στην ημερομηνία "
        "άφιξης. Έτσι δεν παράγονται πολλαπλές παραγγελίες για το ίδιο έλλειμμα σε "
        "διαδοχικές ημέρες ή διαδοχικές αναθεωρήσεις (rolling review) — η ίδια "
        "παραδοχή που κάνει και το SAP MRP για παραλαβές που δεν προλαβαίνουν. Οι "
        "ανοιχτές παραγγελίες με ημερομηνία στο παρελθόν θεωρούνται διαθέσιμες "
        "σήμερα (rescheduling exception).", styles["body"]
    ))

    story.append(P("4.2 Lot Sizing Πολιτικές", styles["h2"]))
    story.append(P(
        "Πέντε διαφορετικοί αλγόριθμοι, καθένας με τα δικά του trade-offs:", styles["body"]
    ))
    lot_table = [
        ["Κωδικός", "Όνομα", "Χρήση"],
        ["LFL", "Lot-for-Lot",                "Παραγγέλνουμε ακριβώς όσο χρειάζεται. Zero holding."],
        ["FOQ", "Fixed Order Quantity",       "Πολλαπλάσια σταθερής ποσότητας (MARC.BSTRF), τουλάχιστον MOQ."],
        ["EOQ", "Economic Order Quantity",    "Wilson formula. Ισορροπεί holding vs ordering cost."],
        ["POQ", "Periodic Order Quantity",    "Κάλυψη Τ* ημερών, όπου Τ* = EOQ / ημερήσια ζήτηση (7–60 ημ.)."],
        ["WW",  "Wagner-Whitin",              "Dynamic programming σε κυλιόμενο ορίζοντα· εκδίδεται η πρώτη παραγγελία της βέλτιστης λύσης."],
    ]
    story.append(make_table(lot_table, col_widths=[1.8*cm, 4*cm, 9.2*cm]))

    story.append(P("4.3 Wagner-Whitin Algorithm", styles["h2"]))
    story.append(P(
        "Ο πιο sophisticated αλγόριθμος του MRP. Λύνει το πρόβλημα: «δεδομένων "
        "Ν περιόδων με γνωστή ζήτηση, ποια συνδυασμός παραγγελιών ελαχιστοποιεί "
        "το συνολικό κόστος (setup + holding);». Το λύνει με dynamic programming "
        "σε O(N²) χρόνο.", styles["body"]
    ))
    story.append(code_block(
        "# Pseudocode\n"
        "f[0] = 0                                              \n"
        "for t = 1 to N:                                       \n"
        "    f[t] = min over s in [1..t] of:                   \n"
        "        f[s-1] + S + h × Σ(d[k] × (k-s)) for k in [s..t]\n"
        "\n"
        "όπου:\n"
        "  S   = setup cost ανά παραγγελία\n"
        "  h   = holding cost ανά μονάδα·περίοδο\n"
        "  d[k] = ζήτηση περιόδου k\n"
        "\n"
        "Reference: Wagner, H.M. & Whitin, T.M. (1958)\n"
        "  \"Dynamic version of the economic lot size model\"\n"
        "  Management Science, 5(1), 89-96.",
        styles["code"]
    ))
    story.append(PageBreak())

    # ============================================================
    # SECTION 5 — RULES
    # ============================================================
    story.append(P("5. Επιχειρησιακοί Κανόνες", styles["h1"]))

    story.append(P(
        "Οι κανόνες υλοποιούν την επιχειρησιακή γνώση που δεν αποτυπώνεται "
        "από καθαρά μαθηματικά μοντέλα. Δομούνται ως ξεχωριστές functions με "
        "decorator pattern, καθεμία με προτεραιότητα. Εκτελούνται σε σειρά "
        "αύξουσας προτεραιότητας πάνω σε κάθε proposal του MRP:", styles["body"]
    ))

    rules_table = [
        ["Rule", "Priority", "Λειτουργία"],
        ["R-DEAD-STOCK",       "1",  "Καταπνίγει προτάσεις για dead-stock υλικά (>365 ημ. χωρίς κίνηση)"],
        ["R-EXPEDITE",         "10", "Επισημαίνει urgent αν stock < 50% του safety stock"],
        ["R-SAFETY-BUFFER-A",  "20", "Προσθέτει 20% buffer στις A-class προτάσεις"],
        ["R-LONG-LEAD-BUFFER", "25", "Επιπλέον +1 ημέρα stock cover αν LT > 30 ημ."],
        ["R-MOQ-ENFORCE",      "30", "Στρογγυλοποίηση στο MOQ ή round-up σε fixed_lot_size"],
        ["R-CALENDAR-SHIFT",   "80", "Μετακίνηση proposals σε εργάσιμες ημέρες"],
        ["R-COST-ESTIMATE",    "90", "Υπολογισμός estimated_cost = qty × standard_cost"],
    ]
    story.append(make_table(rules_table, col_widths=[4*cm, 1.8*cm, 9.2*cm]))

    story.append(P("5.1 Rule Decorator Pattern", styles["h2"]))
    story.append(code_block(
        "@rule(\"R-EXPEDITE\", priority=10)\n"
        "def expedite_critical(proposal, material, beliefs, desires):\n"
        "    \"\"\"Mark proposal urgent if stock < 50% of safety stock.\"\"\"\n"
        "    current_stock = beliefs.current_stock.get(material.material_id, 0)\n"
        "    if material.safety_stock and current_stock < 0.5 * material.safety_stock:\n"
        "        proposal[\"expedite\"] = True\n"
        "        proposal[\"rule_triggered\"] = \"R-EXPEDITE\"\n"
        "    return proposal",
        styles["code"]
    ))

    story.append(P("5.2 Rules Engine με Disabled Rules Support", styles["h2"]))
    story.append(P(
        "Το RulesEngine δέχεται μια προαιρετική παράμετρο "
        "<font face='DejaVu-Mono'>disabled_rules</font> — ένα σύνολο rule names "
        "που πρέπει να παρακαμφθούν. Αυτό χρησιμοποιείται από το Rule Ablation "
        "Study (Ενότητα 8) για να μετρήσει τη συμβολή κάθε κανόνα.", styles["body"]
    ))
    story.append(code_block(
        "# Όλοι οι κανόνες ενεργοποιημένοι (default)\n"
        "engine = RulesEngine()\n"
        "\n"
        "# Απενεργοποίηση του R-EXPEDITE για ablation study\n"
        "engine = RulesEngine(disabled_rules={\"R-EXPEDITE\"})",
        styles["code"]
    ))
    story.append(PageBreak())

    # ============================================================
    # SECTION 6 — BACKTEST
    # ============================================================
    story.append(P("6. Αξιολόγηση (Backtest)", styles["h1"]))

    story.append(P(
        "Η αξιολόγηση του agent γίνεται μέσω συγκριτικού backtest As-Is vs "
        "To-Be πάνω στα ιστορικά δεδομένα. Πιο συγκεκριμένα:", styles["body"]
    ))
    backtest_list = [
        "<b>As-Is</b>: Αναπαράσταση του τι όντως συνέβη στο ιστορικό παράθυρο. "
        "Χρησιμοποιεί τα πραγματικά movements και τις παραγγελίες που έγιναν.",

        "<b>To-Be</b>: Προσομοίωση «τι θα είχε γίνει αν ο agent αποφάσιζε». "
        "Ο agent τρέχει σε review intervals (κάθε 7 ημέρες) και εκδίδει "
        "προτάσεις που \"φτάνουν\" μετά από lead time.",
    ]
    for b in backtest_list:
        story.append(P("• " + b, styles["body"]))

    story.append(P(
        "<b>Δίκαιη σύγκριση.</b> Και τα δύο σενάρια ξεκινούν από το ίδιο αρχικό "
        "απόθεμα (ανακατασκευή από το snapshot και τις κινήσεις) και από την ίδια "
        "pipeline παραγγελιών σε εξέλιξη (παραλαβές μέσα στο lead time από την "
        "έναρξη του παραθύρου, που προέρχονται από αποφάσεις πριν από αυτό). Η "
        "δυναμική του αποθέματος είναι ίδια (lost sales, χωρίς αρνητικό απόθεμα). "
        "Σε κάθε ημερομηνία αναθεώρησης ο agent βλέπει μόνο κινήσεις ≤ t "
        "(χωρίς look-ahead).", styles["body"]
    ))
    story.append(P(
        "<b>Βάση κόστους.</b> Όλα τα κόστη εκφράζονται για τη διάρκεια του παραθύρου: "
        "holding = μέση αξία αποθέματος × ετήσιο ποσοστό × ημέρες/365· stockout = "
        "χαμένο περιθώριο + premium επείγουσας προμήθειας εντός παραθύρου· ordering = "
        "πλήθος παραγγελιών × €50· TCO = άθροισμα των τριών. Το ετήσιο ισοδύναμο "
        "(× 365/ημέρες) αναφέρεται χωριστά και δεν πρέπει να αναχθεί ξανά σε ετήσια "
        "βάση.", styles["body"]
    ))

    story.append(P("6.1 Τρία Cost Scenarios", styles["h2"]))
    story.append(P(
        "Επειδή το πραγματικό holding rate μιας εταιρείας είναι άγνωστο, "
        "το backtest τρέχει σε 3 σενάρια κόστους:", styles["body"]
    ))
    scenarios_table = [
        ["Scenario", "Holding Rate", "Χρήση"],
        ["conservative", "~12%", "Stable industry, χαμηλά επιτόκια"],
        ["realistic",    "~20%", "Τυπικός Ευρωπαϊκός manufacturer (default)"],
        ["aggressive",   "~28%", "Tech / fashion / fast obsolescence"],
    ]
    story.append(make_table(scenarios_table, col_widths=[3.5*cm, 3.5*cm, 8*cm]))

    story.append(P("6.2 Decomposed Holding Cost", styles["h2"]))
    story.append(P(
        "Σύμφωνα με Silver-Pyke-Peterson (1998) και Vollmann et al. (2005), "
        "το holding rate αποτελείται από πέντε διακριτές συνιστώσες:", styles["body"]
    ))
    holding_breakdown = [
        ["Συνιστώσα", "Ορισμός", "Τυπική Τιμή"],
        ["Capital cost",   "Κόστος ευκαιρίας κεφαλαίου (WACC)",  "8-12%"],
        ["Warehouse",      "Αποθήκευση, χειρισμός, ενέργεια",    "3-5%"],
        ["Obsolescence",   "Risk-adjusted write-off",            "2-8%"],
        ["Insurance",      "Ασφάλεια αποθεμάτων",                "0.5-1.5%"],
        ["Shrinkage",      "Φθορά, κλοπή, ζημιά",                "1-2%"],
    ]
    story.append(make_table(holding_breakdown, col_widths=[3.5*cm, 7.5*cm, 4*cm]))

    story.append(P("6.3 Stockout Cost", styles["h2"]))
    story.append(P(
        "Το cost of stockout υπολογίζεται ως: <b>lost sales + expedite premium</b>. "
        "Το πρώτο εκφράζει το χαμένο gross margin (gross_margin_pct × unit_revenue "
        "× shortage_qty), και το δεύτερο το πρόσθετο κόστος urgent παραγγελιών. "
        "Η αναφορά είναι Stock &amp; Lambert (2001), Strategic Logistics Management.", styles["body"]
    ))

    story.append(P("6.4 Sensitivity Analysis", styles["h2"]))
    story.append(P(
        "Επιπλέον του base run, το backtest υποστηρίζει sensitivity analysis "
        "όπου διαταράσσονται ±20% τα: lead time, demand, holding rate. "
        "Έτσι ελέγχουμε αν τα αποτελέσματα είναι robust ή ευαίσθητα σε "
        "παραμέτρους:", styles["body"]
    ))
    story.append(code_block(
        "python scripts/run_validation.py --sensitivity",
        styles["code"]
    ))
    story.append(PageBreak())

    # ============================================================
    # SECTION 7 — BOOTSTRAP CI
    # ============================================================
    story.append(P("7. Bootstrap Confidence Intervals", styles["h1"]))

    story.append(P(callout_text_intro_bootstrap(), styles["callout"]))

    story.append(P("7.1 Το Πρόβλημα", styles["h2"]))
    story.append(P(
        "Όταν τρέχουμε ένα single backtest σε ένα παράθυρο 60 ημερών και "
        "βρίσκουμε «savings = €66K», αυτή είναι μία point estimate. "
        "Η κρίσιμη ερώτηση: πόσο εμπιστευόμαστε αυτό το νούμερο; "
        "Είναι αντιπροσωπευτικό; Μήπως είναι «τυχερό» παράθυρο;", styles["body"]
    ))

    story.append(P("7.2 Η Λύση: Bootstrap Sampling", styles["h2"]))
    story.append(P(
        "Αντί για ένα παράθυρο, τρέχουμε N=30+ τυχαία επιλεγμένα παράθυρα από "
        "όλο το διαθέσιμο ιστορικό. Κάθε παράθυρο παράγει ένα savings sample. "
        "Από την κατανομή των samples υπολογίζουμε:", styles["body"]
    ))
    bootstrap_outputs = [
        "<b>Στάδιο 1 — τυχαία παράθυρα (block subsampling):</b> N = 30 παράθυρα "
        "των 21 ημερών (seed 42) → δείγμα εξοικονομήσεων s₁…s₃₀",
        "<b>Στάδιο 2 — bootstrap του μέσου:</b> B = 2.000 επαναδειγματοληψίες με "
        "επανάθεση → 95% percentile CI του <i>μέσου</i> και bootstrap p-value "
        "(ποσοστό επαναδειγματοληψιών με μέσο ≤ 0)",
        "<b>Συμπληρωματικοί έλεγχοι:</b> t-CI του μέσου (df = 29), μονόπλευρος "
        "t-test, ακριβής έλεγχος προσήμου (distribution-free)",
        "<b>Διασπορά μεμονωμένου παραθύρου</b> (2,5–97,5 εκατοστημόρια των 30 τιμών) "
        "— δείχνει τι μπορεί να δώσει ένα παράθυρο, ΟΧΙ την αβεβαιότητα του μέσου",
        "<b>Significance verdict</b>: το CI του μέσου εξαιρεί το 0 ΚΑΙ p &lt; 0.05",
    ]
    for o in bootstrap_outputs:
        story.append(P("• " + o, styles["body"]))

    story.append(P("7.3 Αλγόριθμος", styles["h2"]))
    story.append(code_block(
        "function bootstrap_analysis(history_start, history_end, N=30, B=2000):\n"
        "    # Stage 1: random windows\n"
        "    samples = []\n"
        "    for i in 1..N:\n"
        "        w_start, w_end = random_window(\n"
        "            history_start, history_end, window_size=21)\n"
        "        asis_tco, tobe_tco = run_backtest(w_start, w_end)\n"
        "        samples.append(asis_tco - tobe_tco)\n"
        "\n"
        "    # Stage 2: bootstrap of the mean\n"
        "    means = []\n"
        "    for b in 1..B:\n"
        "        resample = draw N values from samples WITH replacement\n"
        "        means.append(average(resample))\n"
        "    ci_lower = percentile(means, 2.5)\n"
        "    ci_upper = percentile(means, 97.5)\n"
        "    p_value  = (count(means <= 0) + 1) / (B + 1)\n"
        "\n"
        "    # complementary: t-CI (df=N-1), one-sided t-test, exact sign test\n"
        "    return average(samples), ci_lower, ci_upper, p_value",
        styles["code"]
    ))

    story.append(P("7.4 Εκτέλεση", styles["h2"]))
    story.append(code_block(
        "python scripts/run_bootstrap.py                       # 30 samples\n"
        "python scripts/run_bootstrap.py --n-samples 100       # Στενότερα CIs\n"
        "python scripts/run_bootstrap.py --scenario aggressive\n"
        "python scripts/run_bootstrap.py --seed 42             # reproducibility",
        styles["code"]
    ))

    story.append(P("7.5 Παράδειγμα Output", styles["h2"]))
    story.append(code_block(
        "══════════════════════════════════════════════\n"
        "  BOOTSTRAP CONFIDENCE INTERVALS\n"
        "══════════════════════════════════════════════\n"
        "\n"
        "  Stage 1 - windows:   30 random windows x 21 days\n"
        "  Stage 2 - resamples: B = 2,000 (bootstrap of the mean)\n"
        "  Mean savings / window:               +EUR 3,073\n"
        "  Std deviation / std error of mean:   EUR 2,649 / EUR 484\n"
        "  95% CI of mean (bootstrap, B=2000):  [+EUR 2,148, +EUR 3,997]\n"
        "  95% CI of mean (t, df=29):           [+EUR 2,084, +EUR 4,062]\n"
        "  p-value bootstrap / t-test / sign:   0.0005 / <0.0001 / <0.0001\n"
        "  Windows positive:                    28 / 30\n"
        "  Significant?      [YES] (CI of the mean excludes 0, p < 0.05)\n"
        "  (synthetic data, seed 42 - real data gives different figures)",
        styles["code"]
    ))

    story.append(P("7.6 Defense-Ready Statement", styles["h2"]))
    story.append(P(
        "Όταν ο επιβλέπων ή η επιτροπή ρωτήσει: <i>«πώς ξέρουμε ότι δεν "
        "είναι τυχαίο;»</i>, η απάντηση είναι:", styles["body"]
    ))
    story.append(P(
        "<i>«Τρέξαμε 30 backtest σε τυχαία επιλεγμένα παράθυρα 21 ημερών από όλο "
        "το ιστορικό και εφαρμόσαμε bootstrap του μέσου με 2.000 επαναδειγματοληψίες. "
        "Το 95% διάστημα εμπιστοσύνης της μέσης εξοικονόμησης δεν περιλαμβάνει το "
        "μηδέν, ο t-test και ο έλεγχος προσήμου συμφωνούν (p &lt; 0,001) και η "
        "συντριπτική πλειονότητα των παραθύρων είναι θετική. Άρα η εξοικονόμηση "
        "είναι στατιστικά σημαντική και δεν οφείλεται σε ευνοϊκή περίοδο.»</i>",
        styles["callout"]
    ))

    story.append(P("7.7 Bιβλιογραφία", styles["h2"]))
    story.append(P(
        "• Efron, B. &amp; Tibshirani, R. (1993). <i>An Introduction to the "
        "Bootstrap.</i> CRC Press.", styles["body"]
    ))
    story.append(P(
        "• Bergmeir, C., Hyndman, R.J., Koo, B. (2018). \"A note on the "
        "validity of cross-validation for evaluating autoregressive time "
        "series prediction.\" <i>Computational Statistics &amp; Data "
        "Analysis</i>, 120, 70-83.", styles["body"]
    ))
    story.append(P(
        "• Künsch, H.R. (1989). \"The jackknife and the bootstrap for "
        "general stationary observations.\" <i>Annals of Statistics</i>, "
        "17(3), 1217-1241.", styles["body"]
    ))
    story.append(PageBreak())

    # ============================================================
    # SECTION 8 — RULE ABLATION
    # ============================================================
    story.append(P("8. Rule Ablation Study", styles["h1"]))

    story.append(P(callout_text_intro_ablation(), styles["callout"]))

    story.append(P("8.1 Το Πρόβλημα", styles["h2"]))
    story.append(P(
        "Έχουμε 7 rules στον agent. Παίζουν όλοι πραγματικό ρόλο, ή μήπως 1-2 "
        "κάνουν όλη τη δουλειά και οι υπόλοιποι είναι decorative; Χωρίς αυτή "
        "την ανάλυση, ένας skeptical reviewer μπορεί να αμφισβητήσει το design.", styles["body"]
    ))

    story.append(P("8.2 Μεθοδολογία: Leave-One-Out", styles["h2"]))
    story.append(P(
        "Standard στη ML interpretability literature (Lipton 2018). "
        "Τρέχουμε τον agent N+1 φορές:", styles["body"]
    ))
    loo_steps = [
        "<b>Baseline</b>: όλοι οι κανόνες ενεργοί",
        "<b>Ablation 1</b>: όλοι εκτός R-DEAD-STOCK",
        "<b>Ablation 2</b>: όλοι εκτός R-EXPEDITE",
        "...",
        "<b>Ablation 7</b>: όλοι εκτός R-COST-ESTIMATE",
    ]
    for s in loo_steps:
        story.append(P("• " + s, styles["body"]))
    story.append(P(
        "Για κάθε configuration μετράμε: service level, holding cost, "
        "stockout days, TCO. Η διαφορά από το baseline = συμβολή του rule.", styles["body"]
    ))

    story.append(P("8.3 Stress Test Mode", styles["h2"]))
    story.append(P(
        "Σε καλά τροφοδοτημένο σύστημα (αρχικό stock = 2× safety stock), οι "
        "rules έχουν περιορισμένη επίδραση γιατί δεν υπάρχει πίεση. "
        "Το <font face='DejaVu-Mono'>--stress-test</font> flag ξεκινά με "
        "αρχικό stock = 0.5× safety stock, αναγκάζοντας τους κανόνες να "
        "«δουλέψουν» και αποκαλύπτοντας τις συμβολές τους:", styles["body"]
    ))
    story.append(code_block(
        "python scripts/run_rule_ablation.py --window-days 60 --stress-test",
        styles["code"]
    ))

    story.append(P("8.4 Παράδειγμα Αποτελεσμάτων (Stress Mode)", styles["h2"]))
    abl_results = [
        ["Configuration", "Δ Service", "Δ TCO (€)"],
        ["BASELINE (all rules)",         "0.00 pp",   "0"],
        ["without R-SAFETY-BUFFER-A",    "0.00 pp",   "−69,782"],
        ["without R-LONG-LEAD-BUFFER",   "0.00 pp",   "−40,507"],
        ["without R-CALENDAR-SHIFT",     "0.00 pp",   "+3,335"],
        ["without R-EXPEDITE",           "0.00 pp",   "0"],
        ["without R-DEAD-STOCK",         "0.00 pp",   "0"],
        ["without R-MOQ-ENFORCE",        "0.00 pp",   "0"],
        ["without R-COST-ESTIMATE",      "0.00 pp",   "0"],
    ]
    story.append(make_table(abl_results, col_widths=[6*cm, 3*cm, 5*cm]))
    story.append(Spacer(1, 6))

    story.append(P("8.5 Ερμηνεία", styles["h2"]))
    story.append(P(
        "Πολύτιμη ανάλυση για τη ΔΕ — αποκαλύπτει thresholds και trade-offs:", styles["body"]
    ))
    interp_list = [
        "<b>R-SAFETY-BUFFER-A και R-LONG-LEAD-BUFFER</b> είναι κανόνες "
        "<i>conservative</i>: αυξάνουν το TCO κατά €110K επειδή κρατούν "
        "παραπάνω stock. Αν τους αφαιρέσεις, εξοικονομείς, αλλά αυξάνεις "
        "το ρίσκο stockout (το οποίο δεν φάνηκε σε αυτό το window, αλλά "
        "θα φαινόταν σε μεγαλύτερα).",

        "<b>R-CALENDAR-SHIFT</b> μετακινεί προτάσεις σε εργάσιμες ημέρες — "
        "μικρή θετική επίδραση στο TCO.",

        "<b>R-EXPEDITE, R-DEAD-STOCK, R-MOQ-ENFORCE, R-COST-ESTIMATE</b> είναι "
        "<i>conditional rules</i>: δεν ενεργοποιούνται πάντα. Στο τρέχον "
        "window δεν είχαν trigger, οπότε η αφαίρεσή τους δεν έχει επίδραση.",
    ]
    for i in interp_list:
        story.append(P("• " + i, styles["body"]))

    story.append(P("8.6 Bιβλιογραφία", styles["h2"]))
    story.append(P(
        "• Hooker, J.N. (1995). \"Testing heuristics: We have it all wrong.\" "
        "<i>Journal of Heuristics</i>, 1(1), 33-42.", styles["body"]
    ))
    story.append(P(
        "• Lipton, Z.C. (2018). \"The mythos of model interpretability.\" "
        "<i>Communications of the ACM</i>, 61(10), 36-43.", styles["body"]
    ))
    story.append(PageBreak())

    # ============================================================
    # SECTION 9 — FORECAST DASHBOARD
    # ============================================================
    story.append(P("9. Demand Forecast Dashboard", styles["h1"]))

    story.append(P(
        "Νέο tab «📈 Forecast» στο Streamlit dashboard. Δείχνει για κάθε υλικό:", styles["body"]
    ))
    forecast_features = [
        "Ιστορικό κατανάλωσης (90/180/365/730 ημέρες)",
        "Πρόβλεψη για τις επόμενες 14-90 ημέρες με 3 μεθόδους ταυτόχρονα",
        "Accuracy metrics μέσω walk-forward validation",
        "Auto-recommendation της καλύτερης μεθόδου ανά υλικό",
    ]
    for f in forecast_features:
        story.append(P("• " + f, styles["body"]))

    story.append(P("9.1 Forecasting Methods", styles["h2"]))
    methods_table = [
        ["Μέθοδος", "Τύπος", "Πότε Λειτουργεί Καλύτερα"],
        ["simple_average",
         "Flat-line at historical mean",
         "Stable demand, no trend"],
        ["moving_average",
         "Mean of last N days (default 30)",
         "Recent shifts in demand"],
        ["exponential_smoothing",
         "S(t) = α·X(t) + (1-α)·S(t-1)",
         "Smooth trends, recent emphasis"],
    ]
    story.append(make_table(methods_table, col_widths=[3.5*cm, 5*cm, 6.5*cm]))

    story.append(P("9.2 Walk-Forward Validation", styles["h2"]))
    story.append(P(
        "Standard για time-series evaluation (Bergmeir &amp; Benítez 2012). "
        "Αντί για random k-fold (που σπάει την time order), χρησιμοποιούμε "
        "rolling-origin splits:", styles["body"]
    ))
    story.append(code_block(
        "Fold 1: Train [day 0..60], Test [day 60..74]\n"
        "Fold 2: Train [day 14..74], Test [day 74..88]\n"
        "Fold 3: Train [day 28..88], Test [day 88..102]\n"
        "...\n"
        "(default: 5 folds, 60-day train, 14-day test)",
        styles["code"]
    ))

    story.append(P("9.3 Accuracy Metrics", styles["h2"]))
    metrics_table = [
        ["Metric", "Φόρμουλα", "Ερμηνεία"],
        ["MAE",   "mean(|actual − predicted|)",
         "Average error, same units as data"],
        ["RMSE",  "√mean((actual − predicted)²)",
         "Penalizes large errors more"],
        ["MAPE",  "mean(|actual − predicted| / |actual|) × 100",
         "Percentage error, scale-free"],
        ["Bias",  "mean(predicted − actual)",
         "Positive = over-forecast"],
    ]
    story.append(make_table(metrics_table, col_widths=[1.5*cm, 6.5*cm, 7*cm]))

    story.append(P("9.4 Best Method Selection", styles["h2"]))
    story.append(P(
        "Η καλύτερη μέθοδος ανά υλικό επιλέγεται με κριτήριο το χαμηλότερο MAPE. "
        "Σε υλικά με υψηλό CV (variability &gt; 1.0), όλες οι μέθοδοι έχουν "
        "δυσκολία και το MAPE είναι &gt; 50% — αυτό φαίνεται καθαρά στο dashboard "
        "και είναι honest reporting.", styles["body"]
    ))
    story.append(PageBreak())

    # ============================================================
    # SECTION 10 — COPILOT
    # ============================================================
    story.append(P("10. AI Copilot", styles["h1"]))

    story.append(P(
        "Tab «💬 AI Copilot» που επιτρέπει conversational interaction με τα "
        "δεδομένα του agent. Χρησιμοποιεί <b>τοπικό LLM μέσω Ollama</b> — "
        "εταιρικά δεδομένα δεν φεύγουν από το laptop.", styles["body"]
    ))

    story.append(P("10.1 Αρχιτεκτονική", styles["h2"]))
    story.append(code_block(
        "User question                  Streamlit chat UI\n"
        "    │                                  ▲\n"
        "    ▼                                  │\n"
        "┌────────────────────────────────────────────────┐\n"
        "│ Copilot Orchestrator                           │\n"
        "│  1. Send prompt + tools schema to Ollama       │\n"
        "│  2. If LLM asks for tool: execute & loop       │\n"
        "│  3. Otherwise: return text                     │\n"
        "└─────┬────────────────────────┬────────────────┘\n"
        "      │                        │\n"
        "      ▼                        ▼\n"
        "Ollama (local)         Tool functions (7)\n"
        "  llama3.1:8b            ↓\n"
        "                       SQLite DB",
        styles["code"]
    ))

    story.append(P("10.2 Διαθέσιμα Tools", styles["h2"]))
    tools_list = [
        ["Tool", "Τι Κάνει"],
        ["get_summary",                  "Συνολική εικόνα του συστήματος"],
        ["list_critical_proposals",      "Λίστα expedite items"],
        ["get_material_details",         "Πλήρες προφίλ ενός υλικού"],
        ["explain_proposal",             "Γιατί ο agent προτείνει X για το Υ"],
        ["search_proposals",             "Filter by ABC, expedite, rule"],
        ["get_top_materials_by_demand",  "Top-N κατά κατανάλωση"],
        ["get_abc_distribution",         "Κατανομή υλικών ανά ABC class"],
    ]
    story.append(make_table(tools_list, col_widths=[5*cm, 10*cm]))

    story.append(P("10.3 Παραδείγματα Χρήσης", styles["h2"]))
    examples_list = [
        "<i>«Δώσε μου μια σύνοψη»</i> → καλεί get_summary",
        "<i>«Ποια υλικά είναι κρίσιμα τώρα;»</i> → list_critical_proposals",
        "<i>«Γιατί προτείνεις 500 για το MAT00031;»</i> → explain_proposal",
        "<i>«Δείξε μου A-class items»</i> → search_proposals(abc='A')",
    ]
    for e in examples_list:
        story.append(P("• " + e, styles["body"]))

    story.append(P("10.4 Γιατί Ollama Αντί Cloud API;", styles["h2"]))
    ollama_table = [
        ["Πτυχή",            "Ollama (local)",         "Cloud API"],
        ["Data privacy",     "[YES] Local",            "[!] Sends to vendor"],
        ["Cost",             "Free",                   "~$0.20/1M tokens"],
        ["Reproducibility",  "[YES]",                  "Requires API keys"],
        ["Speed (CPU)",      "2-15s",                  "<1s"],
        ["Quality",          "Good (8B-70B)",          "Excellent (GPT-4)"],
    ]
    story.append(make_table(ollama_table, col_widths=[4*cm, 5.5*cm, 5.5*cm]))
    story.append(Spacer(1, 6))
    story.append(P(
        "Για διπλωματική, το Ollama είναι η σωστή επιλογή — defensible privacy "
        "position, fully reproducible, no operational cost.", styles["body"]
    ))
    story.append(PageBreak())

    # ============================================================
    # SECTION 11 — HOW TO RUN
    # ============================================================
    story.append(P("11. Πώς να Τρέξετε τον Κώδικα — Βήμα προς Βήμα", styles["h1"]))

    story.append(P("11.1 Προαπαιτούμενα", styles["h2"]))
    story.append(code_block(
        "# Python 3.10+\n"
        "python --version\n"
        "\n"
        "# Εικονικό περιβάλλον\n"
        "python -m venv .venv\n"
        ".venv\\Scripts\\activate     # Windows\n"
        "source .venv/bin/activate    # Linux/Mac\n"
        "\n"
        "# Εγκατάσταση dependencies\n"
        "pip install -r requirements.txt",
        styles["code"]
    ))

    story.append(P("11.2 Πλήρης Ροή (Synthetic Data)", styles["h2"]))
    story.append(code_block(
        "# 1. Sample data\n"
        "python scripts/generate_sample_data.py\n"
        "\n"
        "# 2. ETL\n"
        "python scripts/run_etl.py\n"
        "\n"
        "# 3. Agent\n"
        "python scripts/run_agent.py\n"
        "\n"
        "# 4. Dashboard\n"
        "streamlit run dashboard/app.py",
        styles["code"]
    ))

    story.append(P("11.3 Real SAP Data", styles["h2"]))
    story.append(code_block(
        "# 1. Εξαγωγή από SAP\n"
        "# Τρέξτε το ABAP πρόγραμμα ZMRP_AGENT_EXPORT στο GUI\n"
        "# Αποθήκευση των 6 CSV στο data/raw/\n"
        "\n"
        "# 2. Anonymization\n"
        "python -m src.data_layer.anonymization\n"
        "\n"
        "# 3. Συνέχιση όπως πριν\n"
        "python scripts/run_etl.py\n"
        "python scripts/run_agent.py\n"
        "streamlit run dashboard/app.py",
        styles["code"]
    ))

    story.append(P("11.4 Αξιολόγηση &amp; Στατιστική Ανάλυση", styles["h2"]))
    story.append(code_block(
        "# Backtest single scenario\n"
        "python scripts/run_validation.py --window-days 60\n"
        "\n"
        "# Σύγκριση 3 σεναρίων κόστους\n"
        "python scripts/run_validation.py --all-scenarios\n"
        "\n"
        "# Sensitivity analysis\n"
        "python scripts/run_validation.py --sensitivity\n"
        "\n"
        "# Bootstrap CI (30 random windows)\n"
        "python scripts/run_bootstrap.py\n"
        "\n"
        "# Rule ablation study\n"
        "python scripts/run_rule_ablation.py --stress-test",
        styles["code"]
    ))

    story.append(P("11.5 Tests", styles["h2"]))
    story.append(code_block(
        "# Όλα τα tests\n"
        "pytest\n"
        "\n"
        "# Με coverage report\n"
        "pytest --cov=src --cov-report=html\n"
        "\n"
        "# Συγκεκριμένο module\n"
        "pytest tests/test_bootstrap.py -v",
        styles["code"]
    ))
    story.append(PageBreak())

    # ============================================================
    # SECTION 12 — DEFENSE-READY POINTS
    # ============================================================
    story.append(P("12. Defense-Ready Σημεία Συζήτησης", styles["h1"]))

    story.append(P(
        "Παρακάτω οι πιο πιθανές ερωτήσεις από την επιτροπή και προτεινόμενες "
        "απαντήσεις. Όλες οι απαντήσεις στηρίζονται σε υλοποιημένα features.", styles["body"]
    ))

    qa_list = [
        ("Q: Πώς ξέρετε ότι η εξοικονόμηση δεν είναι τυχαία;",
         "A: Δύο στάδια: 30 τυχαία παράθυρα backtest και bootstrap του μέσου "
         "(B = 2.000). Το 95% CI του μέσου εξαιρεί το 0, ο t-test και ο "
         "ακριβής έλεγχος προσήμου συμφωνούν (p < 0,001). Τα ακριβή ποσά "
         "διαβάζονται από το bootstrap_report_summary.csv της τελικής "
         "εκτέλεσης. (Ενότητα 7)"),

        ("Q: Παίζουν όλοι οι 7 κανόνες πραγματικό ρόλο;",
         "A: Leave-one-out ablation study δείχνει ότι οι buffer rules "
         "(Safety, Long-lead) έχουν τη μεγαλύτερη επίδραση. Conditional "
         "rules (Expedite, Dead-stock) ενεργοποιούνται μόνο σε συγκεκριμένες "
         "συνθήκες — αυτό είναι by design. (Ενότητα 8)"),

        ("Q: Γιατί δεν χρησιμοποιείτε neural networks για forecasting;",
         "A: Σκόπιμη επιλογή. Με μικρές demand histories (180-365 ημ.) τα NNs "
         "overfit. Επίσης, ένα BDI agent χρειάζεται explainable forecasts. "
         "Συγκρίνουμε 3 statistical methods με walk-forward validation και "
         "διαλέγουμε αυτόματα τη βέλτιστη ανά υλικό. (Ενότητα 9)"),

        ("Q: Πώς αξιολογείτε τη forecasting accuracy;",
         "A: Walk-forward validation με 5 folds (rolling-origin). Metrics: "
         "MAE, RMSE, MAPE, Bias. Αναφορά: Bergmeir &amp; Benítez (2012)."),

        ("Q: Είναι ρεαλιστικό το cost model;",
         "A: Holding rate διασπασμένο σε 5 components (capital, warehouse, "
         "obsolescence, insurance, shrinkage) σύμφωνα με Silver-Pyke-Peterson "
         "(1998). Τρέχουμε σε 3 σενάρια (conservative/realistic/aggressive) "
         "και sensitivity analysis ±20%. (Ενότητα 6)"),

        ("Q: Πώς διασφαλίζετε τη privacy των εταιρικών δεδομένων;",
         "A: Deterministic pseudonymization όλων των IDs (material, plant, "
         "supplier) με MD5. AI Copilot τρέχει local με Ollama — τίποτα δεν "
         "φεύγει εκτός laptop. (Ενότητες 2.2 και 10.4)"),

        ("Q: Πώς αναπαράγονται τα αποτελέσματα;",
         "A: Όλο το pipeline είναι deterministic. Random seeds (default 42) "
         "για το bootstrap. 183 unit tests διασφαλίζουν ότι αλλαγές στον "
         "κώδικα δεν αλλοιώνουν αποτελέσματα. CSV exports σε κάθε βήμα."),

        ("Q: Γιατί BDI architecture και όχι reinforcement learning;",
         "A: Το πρόβλημα είναι rule-based με σαφή business logic. RL "
         "θα απαιτούσε εκπαίδευση σε εκατομμύρια episodes — όχι εφικτό με "
         "πραγματικά δεδομένα μικρού μεγέθους. BDI είναι interpretable, "
         "auditable, και έχει εδραιωμένη βιβλιογραφία (Rao &amp; Georgeff "
         "1995). (Ενότητα 3)"),

        ("Q: Πώς ενσωματώνεται με το πραγματικό SAP system;",
         "A: Read-only ABAP report (ZMRP_AGENT_EXPORT) εξάγει 6 πίνακες σε "
         "CSV. Καμία modification στο SAP. Σχεδιαστικά αποφάσισα να μην "
         "κάνω real-time integration για λόγους ασφαλείας — το offline "
         "model είναι production-safe και reproducible."),
    ]

    for q, a in qa_list:
        story.append(P("<b>" + q + "</b>", styles["body"]))
        story.append(P(a, styles["body"]))
        story.append(Spacer(1, 6))

    story.append(PageBreak())

    # ─── FINAL PAGE ───
    story.append(P("Επίλογος", styles["h1"]))
    story.append(P(
        "Το παρόν project περιέχει 183 unit tests, ~7,500 γραμμές κώδικα, "
        "και 12 διακριτές δυνατότητες που καλύπτουν όλες τις πτυχές ενός "
        "production-grade replenishment system. Από την εξαγωγή δεδομένων "
        "(ABAP) μέχρι την υπεράσπιση των αποτελεσμάτων (Bootstrap CI), "
        "κάθε σχεδιαστική απόφαση είναι τεκμηριωμένη και αναπαράξιμη.", styles["body"]
    ))
    story.append(P(
        "Το repository στο GitHub (private) έχει όλες τις εκδόσεις του "
        "κώδικα. Η ΔΕ μπορεί να αναφέρεται στα αντίστοιχα αρχεία ως:", styles["body"]
    ))
    story.append(code_block(
        "github.com/greltel/replenishment-agent/blob/main/src/agent/replenishment.py\n"
        "github.com/greltel/replenishment-agent/blob/main/scripts/run_bootstrap.py\n"
        "github.com/greltel/replenishment-agent/blob/main/src/utils/kpi.py",
        styles["code"]
    ))
    story.append(Spacer(1, 24))
    story.append(P(
        "<i>Παράρτημα Δ — Τεχνικός Οδηγός Υλοποίησης</i>",
        styles["subtitle"]
    ))
    story.append(P(
        "<i>Replenishment Agent v1.0 — Athens MBA Διπλωματική Εργασία</i>",
        styles["note"]
    ))

    return story


def callout_text_intro_bootstrap() -> str:
    return (
        "<b>Γιατί έχει σημασία:</b> Bootstrap CI είναι το #1 ερώτημα που "
        "θα κάνει η επιτροπή στην υπεράσπιση. Χωρίς αυτό, ένα νούμερο "
        "«31% savings» είναι just a number. Με αυτό, γίνεται defensible "
        "scientific claim με στατιστική στιβαρότητα."
    )


def callout_text_intro_ablation() -> str:
    return (
        "<b>Γιατί έχει σημασία:</b> Ablation studies είναι standard στη "
        "research literature. Αποδεικνύουν επιστημονικά ότι κάθε component "
        "ενός συστήματος συνεισφέρει μετρήσιμα στην απόδοση — όχι απλά "
        "ότι «έχουμε 7 rules»."
    )


# ============================================================
# Main
# ============================================================
def main():
    # Try to detect if we're in the project or running standalone
    script_dir = Path(__file__).resolve().parent
    # If we're in scripts/ folder, output to docs/
    if script_dir.name == "scripts":
        output_path = script_dir.parent / "docs" / "parartima_d_technical_guide.pdf"
    else:
        output_path = Path("parartima_d_technical_guide.pdf")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=1.8*cm, bottomMargin=1.8*cm,
        title="Παράρτημα Δ — Τεχνικός Οδηγός Υλοποίησης",
        author="George Drakos",
        subject="Athens MBA Διπλωματική Εργασία",
    )

    styles = make_styles()
    story = build_content(styles)
    doc.build(story)

    print(f"✅ PDF generated: {output_path}")
    print(f"   Size: {output_path.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
