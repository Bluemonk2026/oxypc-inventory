"""
Best-effort invoice PDF field extraction (Invoice Number, Date, Sender, Quantity,
Amount). PDF layouts vary, so results are heuristic and always editable by the user.
Tune the regexes to the real invoice format once a sample is available.
"""
import re
from decimal import Decimal, InvalidOperation


def _pdf_text(path: str) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(path)
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        return ""


def _find(patterns, text):
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            return m.group(1).strip()
    return None


def _to_int(v):
    if not v:
        return None
    try:
        return int(re.sub(r"[^0-9]", "", v))
    except (ValueError, TypeError):
        return None


def _to_decimal(v):
    if not v:
        return None
    try:
        return Decimal(v.replace(",", ""))
    except (InvalidOperation, AttributeError):
        return None


def extract_invoice_fields(path: str) -> dict:
    """Return {invoice_number, invoice_date, sender_name, quantity, amount, text_len}."""
    text = _pdf_text(path)

    invoice_number = _find([
        r"invoice\s*(?:no|number|#)\.?\s*[:#\-]?\s*([A-Za-z0-9/\-]{2,30})",
        r"\binv\.?\s*no\.?\s*[:#\-]?\s*([A-Za-z0-9/\-]{2,30})",
        r"bill\s*(?:no|number)\.?\s*[:#\-]?\s*([A-Za-z0-9/\-]{2,30})",
    ], text)

    invoice_date = _find([
        r"invoice\s*date\s*[:\-]?\s*([0-9]{1,2}[-/.][0-9]{1,2}[-/.][0-9]{2,4})",
        r"\bdate\s*[:\-]?\s*([0-9]{1,2}[-/.][0-9]{1,2}[-/.][0-9]{2,4})",
        r"\bdate\s*[:\-]?\s*([0-9]{4}[-/.][0-9]{1,2}[-/.][0-9]{1,2})",
        r"([0-9]{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+[0-9]{2,4})",
    ], text)

    amount = _find([
        r"grand\s*total\s*[:\-]?\s*(?:rs\.?|inr|₹)?\s*([0-9][0-9,]*\.?[0-9]*)",
        r"total\s*amount\s*[:\-]?\s*(?:rs\.?|inr|₹)?\s*([0-9][0-9,]*\.?[0-9]*)",
        r"\btotal\s*[:\-]?\s*(?:rs\.?|inr|₹)?\s*([0-9][0-9,]*\.[0-9]{2})",
        r"(?:rs\.?|inr|₹)\s*([0-9][0-9,]*\.[0-9]{2})",
    ], text)

    quantity = _find([
        r"total\s*(?:qty|quantity)\s*[:\-]?\s*([0-9]+)",
        r"\bquantity\s*[:\-]?\s*([0-9]+)",
        r"\bqty\.?\s*[:\-]?\s*([0-9]+)",
    ], text)

    lot_number = _find([
        r"lot\s*(?:no|number|#)\.?\s*[:#\-]?\s*([A-Za-z0-9/\-]{1,40})",
        r"\blot\s*[:#\-]\s*([A-Za-z0-9/\-]{1,40})",
    ], text)

    sender = _find([
        r"(?:sold\s*by|seller|supplier|vendor|from)\s*[:\-]?\s*([A-Za-z0-9 .,&'\-]{3,60})",
    ], text)
    if not sender:
        for line in text.splitlines():
            s = line.strip()
            low = s.lower()
            if len(s) >= 3 and not low.startswith((
                    "invoice", "tax", "gst", "date", "page", "bill", "original")):
                sender = s[:60]
                break

    return {
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "lot_number": lot_number,
        "sender_name": sender,
        "quantity": _to_int(quantity),
        "amount": _to_decimal(amount),
        "text_len": len(text),
    }
