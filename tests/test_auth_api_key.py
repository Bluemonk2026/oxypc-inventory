from auth.api_key import VALID_SCOPES, _extract_bearer_token


def test_valid_scopes_includes_all_expected():
    expected = {
        "devices:read", "devices:write",
        "lots:read", "lots:write",
        "sales:read", "sales:write",
        "iqc:read", "iqc:write",
        "dealers:read",
        "spare_parts:read",
        "intelligence:read",
        "api_keys:manage",
    }
    assert expected.issubset(VALID_SCOPES)


def test_extract_bearer_token_valid():
    assert _extract_bearer_token("Bearer ok_live_abc123") == "ok_live_abc123"


def test_extract_bearer_token_missing():
    assert _extract_bearer_token("") is None
    assert _extract_bearer_token(None) is None


def test_extract_bearer_token_wrong_scheme():
    assert _extract_bearer_token("Basic dXNlcjpwYXNz") is None


def test_extract_bearer_token_strips_extra_spaces():
    token = _extract_bearer_token("Bearer  double-space")
    assert token == "double-space"
