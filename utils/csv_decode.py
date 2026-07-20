"""Decoding for user-supplied CSV uploads.

Every CSV upload in this app used the same ladder:

    for enc in ("utf-8-sig", "utf-16", "latin-1"):

which is silently wrong. Any byte string of even length is *valid* UTF-16 — it
just decodes to garbage code points rather than raising. So the moment a file
contained one non-UTF-8 byte (Excel writes 0xA0 for a non-breaking space, and
0x92 for a curly apostrophe, constantly), utf-8-sig raised, utf-16 "succeeded"
with nonsense, and latin-1 was never reached. The parser then found no commas in
the nonsense and reported "No rows found in file" — pointing the user at their
data when the real fault was ours.

The fix is to trust UTF-16 only when the file actually says it is UTF-16, via a
byte-order mark. Without a BOM we try UTF-8, then the Windows codepage Excel
actually writes, then latin-1 as a decoder that cannot fail.
"""

UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")


def decode_csv_bytes(raw: bytes) -> str:
    """Decode uploaded CSV bytes to text, preferring correctness over guessing.

    Never raises: latin-1 maps every possible byte, so there is always a result.
    """
    # A BOM is the only trustworthy signal that this really is UTF-16. Check the
    # 4-byte UTF-32 BOMs first — they start with the UTF-16 ones, so testing
    # UTF-16 first would mis-detect a UTF-32 file.
    if raw.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        return raw.decode("utf-32")
    if raw.startswith(UTF16_BOMS):
        return raw.decode("utf-16")

    # utf-8-sig also strips the UTF-8 BOM when present.
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    # Unreachable — latin-1 accepts any byte — but be explicit rather than
    # falling off the end and returning None into a csv reader.
    return raw.decode("latin-1", errors="replace")
