from models.api_key import APIKey

def test_generate_produces_ok_live_prefix():
    raw, hashed = APIKey.generate()
    assert raw.startswith("ok_live_")
    assert len(raw) == 72   # "ok_live_" (8) + 64 hex chars
    assert len(hashed) == 64  # SHA-256 hex digest

def test_hash_key_is_deterministic():
    raw = "ok_live_" + "a" * 64
    h1 = APIKey.hash_key(raw)
    h2 = APIKey.hash_key(raw)
    assert h1 == h2
    assert h1 != raw

def test_generate_always_unique():
    _, h1 = APIKey.generate()
    _, h2 = APIKey.generate()
    assert h1 != h2

def test_key_prefix_extraction():
    raw = "ok_live_abcdef123456789012345678901234567890123456789012345678901234"
    prefix = raw[:12]
    assert prefix.startswith("ok_live_")
