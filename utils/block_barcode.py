"""Scannable Code128 barcode label (4x2 inch, landscape) for a Block Tags
Block ID.

No barcode-rendering precedent existed anywhere in this codebase before this
(grepped — only plain-text Tag Numbers everywhere, never a rendered symbol).
python-barcode draws the Code128 as a PNG (needs Pillow, already a project
dependency via other image handling); reportlab — already used elsewhere in
this app for PDFs — lays that PNG into a fixed 4in x 2in landscape page
alongside the human-readable Block ID text.
"""
import io

import barcode
from barcode.writer import ImageWriter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

PAGE_WIDTH = 4 * inch
PAGE_HEIGHT = 2 * inch


def render_block_id_barcode_pdf(block_id: str) -> bytes:
    code128 = barcode.get("code128", block_id, writer=ImageWriter())
    png_buf = io.BytesIO()
    code128.write(png_buf, options={
        "module_height": 18.0, "font_size": 0, "text_distance": 0,
        "quiet_zone": 2.0, "write_text": False,
    })
    png_buf.seek(0)

    pdf_buf = io.BytesIO()
    c = canvas.Canvas(pdf_buf, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))

    title_y = PAGE_HEIGHT - 0.3 * inch
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(PAGE_WIDTH / 2, title_y, "Inventory Lifecycle")

    barcode_w = PAGE_WIDTH - 0.6 * inch
    barcode_h = 0.9 * inch
    barcode_y = title_y - 0.15 * inch - barcode_h
    c.drawImage(
        _as_image_reader(png_buf),
        0.3 * inch, barcode_y,
        width=barcode_w, height=barcode_h, preserveAspectRatio=True, anchor="c",
    )

    # Block IDs run ~19 chars (DDMMYYYY-CONTAINER-NNNN) — auto-shrink so a
    # longer container name (e.g. "CABINET") never overflows the page width.
    max_text_width = PAGE_WIDTH - 0.3 * inch
    font_size = 14
    while font_size > 6 and c.stringWidth(block_id, "Helvetica-Bold", font_size) > max_text_width:
        font_size -= 1
    c.setFont("Helvetica-Bold", font_size)
    c.drawCentredString(PAGE_WIDTH / 2, barcode_y - 0.25 * inch, block_id)

    c.showPage()
    c.save()
    pdf_buf.seek(0)
    return pdf_buf.read()


def _as_image_reader(png_buf: io.BytesIO):
    from reportlab.lib.utils import ImageReader
    return ImageReader(png_buf)
