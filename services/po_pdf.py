"""Purchase Order PDF generator (fpdf2). Builds a downloadable PO document with
caller-selected sections. Mirrors the fpdf2 pattern used in routers/stress_api.py.

fpdf2 core fonts are latin-1 only, so text is sanitized and the rupee symbol is
rendered as "Rs " (U+20B9 is not encodable in latin-1). We avoid the deprecated
`ln=True` cell arg and use pdf.ln()/set_x() so X always resets to the left
margin (otherwise multi_cell can get a negative width and raise)."""
from datetime import datetime


def _s(x) -> str:
    """Sanitize any value to latin-1 so fpdf2 core fonts can render it."""
    return str("" if x is None else x).encode("latin-1", "replace").decode("latin-1")


def _rs(x) -> str:
    try:
        return "Rs " + f"{float(x or 0):,.2f}"
    except (TypeError, ValueError):
        return "Rs 0.00"


def build_po_pdf(*, po_number, po_date, company, contact, line_items,
                 payment_terms, delivery_terms, disclaimers, sections,
                 total_amount=0, offer_total=None):
    """Return PO PDF bytes.

    company:  dict (name/address/gstin/state/state_code/phone/email)
    contact:  CRMContact or None (the supplier / account)
    line_items: iterable with .item_name/.description/.quantity/.unit_price/.total_price
    payment_terms/delivery_terms/disclaimers: lists of TermsCondition
    sections: dict of bools — account, company, items, payment, delivery, conditions
    """
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_margins(15, 15, 15)
    LM = pdf.l_margin

    # ── Header band ───────────────────────────────────────────────────────────
    pdf.set_fill_color(31, 56, 100)   # brand navy
    pdf.rect(0, 0, 210, 26, "F")
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(255, 255, 255)
    pdf.set_y(7)
    pdf.cell(0, 8, "PURCHASE ORDER", align="C")
    pdf.ln(8)
    pdf.set_x(LM)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(210, 210, 210)
    pdf.cell(0, 6, _s(f"{po_number}   |   {po_date}"), align="C")
    pdf.ln(14)
    pdf.set_x(LM)
    pdf.set_text_color(0, 0, 0)

    def section_title(title):
        pdf.set_x(LM)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(31, 56, 100)
        pdf.cell(0, 6, _s(title))
        pdf.ln(6)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(LM, pdf.get_y(), 195, pdf.get_y())
        pdf.ln(1)
        pdf.set_text_color(0, 0, 0)

    def kv(label, value):
        pdf.set_x(LM)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(35, 6, _s(label), border=0)
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 6, _s(value), border=0)

    # ── Company details ───────────────────────────────────────────────────────
    if sections.get("company") and company:
        section_title("Company Details")
        kv("Company", company.get("name", ""))
        kv("Address", company.get("address", ""))
        if company.get("gstin"):
            kv("GSTIN", company.get("gstin", ""))
        state_line = ", ".join(filter(None, [company.get("state", ""), company.get("state_code", "")]))
        if state_line:
            kv("State", state_line)
        contact_line = "  ".join(filter(None, [company.get("phone", ""), company.get("email", "")]))
        if contact_line:
            kv("Contact", contact_line)
        pdf.ln(3)

    # ── Account / supplier details ────────────────────────────────────────────
    if sections.get("account") and contact is not None:
        section_title("Account Details (Supplier)")
        kv("Name", getattr(contact, "company_name", "") or "")
        if getattr(contact, "contact_person", None):
            kv("Contact Person", contact.contact_person)
        if getattr(contact, "gstin", None):
            kv("GSTIN", contact.gstin)
        addr = ", ".join(filter(None, [
            getattr(contact, "address", "") or "", getattr(contact, "city", "") or "",
            getattr(contact, "state", "") or "", getattr(contact, "pincode", "") or "",
        ]))
        if addr:
            kv("Address", addr)
        if getattr(contact, "phone", None):
            kv("Phone", contact.phone)
        pdf.ln(3)

    # ── Line items ────────────────────────────────────────────────────────────
    if sections.get("items"):
        section_title("Line Items")
        pdf.set_x(LM)
        pdf.set_fill_color(31, 56, 100)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(70, 7, "Item", border=0, fill=True)
        pdf.cell(50, 7, "Description", border=0, fill=True)
        pdf.cell(18, 7, "Qty", border=0, fill=True, align="R")
        pdf.cell(0, 7, "Total", border=0, fill=True, align="R")
        pdf.ln(7)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "", 9)
        idx = 0
        for li in line_items:
            fill = (245, 245, 245) if idx % 2 == 0 else (255, 255, 255)
            pdf.set_x(LM)
            pdf.set_fill_color(*fill)
            pdf.cell(70, 7, _s(getattr(li, "item_name", ""))[:40], border=0, fill=True)
            pdf.cell(50, 7, _s(getattr(li, "description", "") or "")[:28], border=0, fill=True)
            pdf.cell(18, 7, _s(getattr(li, "quantity", "")), border=0, fill=True, align="R")
            pdf.cell(0, 7, _rs(getattr(li, "total_price", 0)), border=0, fill=True, align="R")
            pdf.ln(7)
            idx += 1
        pdf.set_x(LM)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(138, 7, "Grand Total", align="R")
        pdf.cell(0, 7, _rs(total_amount), align="R")
        pdf.ln(7)
        if offer_total is not None:
            pdf.set_x(LM)
            pdf.cell(138, 7, "Offer Total", align="R")
            pdf.cell(0, 7, _rs(offer_total), align="R")
            pdf.ln(7)
        pdf.ln(3)

    # ── Terms sections (all active of each type, concatenated) ────────────────
    def terms_block(title, rows):
        if not rows:
            return
        section_title(title)
        for t in rows:
            pdf.set_x(LM)
            pdf.set_font("Helvetica", "B", 9)
            pdf.multi_cell(0, 5, _s(t.title))
            pdf.set_x(LM)
            pdf.set_font("Helvetica", "", 9)
            pdf.multi_cell(0, 5, _s(t.content))
            pdf.ln(1)
        pdf.ln(2)

    if sections.get("payment"):
        terms_block("Payment Terms", payment_terms)
    if sections.get("delivery"):
        terms_block("Delivery Terms", delivery_terms)
    if sections.get("conditions"):
        terms_block("Conditions", disclaimers)

    # ── Footer ────────────────────────────────────────────────────────────────
    pdf.ln(6)
    pdf.set_x(LM)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 5, _s(f"Generated by OxyPC Inventory - {datetime.now().strftime('%d %b %Y %H:%M')}"), align="C")

    return bytes(pdf.output())
