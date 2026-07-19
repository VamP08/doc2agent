"""SSRF guard tests — offline."""
import pytest

from app.safety import TRUSTED_NETLOCS, UnsafeURLError, assert_public_url, trust_own_netloc


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://localhost:8000/",
        "http://10.0.0.5/internal",
        "http://192.168.1.1/router",
        "http://169.254.169.254/latest/meta-data",
        "ftp://example.com/file",
        "http:///nohost",
    ],
)
def test_blocked(url):
    with pytest.raises(UnsafeURLError):
        assert_public_url(url)


def test_trusted_self_host_allowed():
    trust_own_netloc("127.0.0.1:9999")
    try:
        assert_public_url("http://127.0.0.1:9999/demo/openapi.json")  # no raise
    finally:
        TRUSTED_NETLOCS.discard("127.0.0.1:9999")


def test_trust_is_scoped_to_exact_netloc():
    trust_own_netloc("127.0.0.1:9999")
    try:
        with pytest.raises(UnsafeURLError):
            assert_public_url("http://127.0.0.1:8888/other")
    finally:
        TRUSTED_NETLOCS.discard("127.0.0.1:9999")
