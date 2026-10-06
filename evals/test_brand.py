"""Brand assets are served where browsers look for them."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_favicon_ico_served_at_root():
    r = client.get("/favicon.ico")
    assert r.status_code == 200
    assert r.content[:4] == b"\x00\x00\x01\x00"  # ICO header


def test_brand_assets_served():
    for name in ("favicon.svg", "apple-touch-icon.png", "site.webmanifest", "doc2agent-symbol.svg"):
        assert client.get(f"/static/brand/{name}").status_code == 200


def test_pages_link_the_icons():
    for page in ("/", "/monitor"):
        html = client.get(page).text
        assert 'rel="icon"' in html and "/static/brand/favicon.svg" in html


def test_pages_are_revalidated_after_a_deploy():
    for page in ("/", "/monitor"):
        assert client.get(page).headers["cache-control"] == "no-cache"


def test_link_previews_have_an_image():
    html = client.get("/").text
    assert (
        'property="og:image" content="https://doc2agent.onrender.com/static/brand/og.png"' in html
    )
    assert client.get("/static/brand/og.png").status_code == 200
