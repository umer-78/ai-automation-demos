"""Search and link-preview metadata: every page gets its own tags, written server-side."""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app import seo
from app.main import create_app
from tests.conftest import make_settings

ROUTES_JSON = Path(__file__).resolve().parents[2] / "frontend" / "src" / "seo" / "routes.json"
TEMPLATE = """<!doctype html>
<html lang="en">
  <head>
    <!-- seo:start -->
    <title>placeholder</title>
    <!-- seo:end -->
    <link rel="icon" href="/favicon.svg" />
  </head>
  <body><div id="root"></div></body>
</html>
"""


def build_static(tmp_path: Path, routes: dict | None = None) -> tuple[Path, dict]:
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "assets" / "index-abc123.js").write_text("console.log('app')")
    (static / "index.html").write_text(TEMPLATE)
    (static / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    routes = routes or json.loads(ROUTES_JSON.read_text(encoding="utf-8"))
    (static / "seo-routes.json").write_text(json.dumps(routes))
    return static, routes


def client_for(tmp_path: Path, routes: dict | None = None, **settings) -> tuple[TestClient, dict]:
    static, routes = build_static(tmp_path, routes)
    app = create_app(make_settings(tmp_path, **settings), static_dir=static)
    return TestClient(app), routes


def meta(html: str, attr: str, key: str) -> str | None:
    m = re.search(rf'<meta {attr}="{re.escape(key)}" content="([^"]*)"', html)
    return m.group(1) if m else None


def test_every_page_gets_its_own_title_description_and_absolute_urls(tmp_path):
    client, routes = client_for(tmp_path, public_base_url="https://sales.example.com")
    with client:
        for route in routes["routes"]:
            r = client.get(route["path"])
            assert r.status_code == 200, route["path"]
            body = r.text
            assert f"<title>{route['title']}</title>" in body
            assert meta(body, "name", "description") == route["description"]
            assert f'<link rel="canonical" href="https://sales.example.com{route["path"]}" />' in body
            assert meta(body, "property", "og:url") == f"https://sales.example.com{route['path']}"
            assert meta(body, "property", "og:image") == "https://sales.example.com/og-image.png"
            assert meta(body, "name", "twitter:card") == "summary_large_image"
            assert body.count("<title>") == 1
            assert r.headers["cache-control"] == "no-cache"


def test_json_ld_is_valid_and_names_the_author(tmp_path):
    client, _ = client_for(tmp_path, public_base_url="https://sales.example.com")
    with client:
        body = client.get("/").text
    raw = re.search(r'<script type="application/ld\+json">(.*?)</script>', body, re.S).group(1)
    data = json.loads(raw)
    assert data["@type"] == "WebApplication"
    assert data["url"] == "https://sales.example.com/"
    assert data["author"]["name"] == "Umer"
    assert "https://github.com/umer-78" in data["author"]["sameAs"]


def test_query_strings_and_trailing_slashes_map_to_the_page(tmp_path):
    client, routes = client_for(tmp_path)
    leads = next(r for r in routes["routes"] if r["path"] == "/leads")
    with client:
        for path in ("/leads/", "/leads?sort=score"):
            r = client.get(path)
            assert r.status_code == 200
            assert f"<title>{leads['title']}</title>" in r.text


def test_unknown_paths_return_404_with_noindex_and_still_load_the_app(tmp_path):
    client, _ = client_for(tmp_path)
    with client:
        r = client.get("/definitely-not-a-page")
    assert r.status_code == 404
    assert meta(r.text, "name", "robots") == "noindex"
    assert 'rel="canonical"' not in r.text
    assert '<div id="root"></div>' in r.text


def test_metadata_is_escaped(tmp_path):
    hostile = {
        "site": "Demo",
        "image": "/og-image.png",
        "imageAlt": 'alt "quoted"',
        "jsonld": {"@type": "WebApplication", "name": "</script><script>alert(1)</script>"},
        "routes": [{"path": "/", "title": "<script>alert(1)</script>", "description": '" onload="alert(1)'}],
    }
    client, _ = client_for(tmp_path, routes=hostile)
    with client:
        body = client.get("/").text
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    assert 'content="&quot; onload=&quot;alert(1)"' in body
    raw = re.search(r'<script type="application/ld\+json">(.*?)</script>', body, re.S).group(1)
    assert json.loads(raw)["name"] == "</script><script>alert(1)</script>"


def test_robots_and_sitemap(tmp_path):
    client, routes = client_for(tmp_path, public_base_url="https://sales.example.com/")
    with client:
        robots = client.get("/robots.txt")
        sitemap = client.get("/sitemap.xml")
    assert robots.status_code == 200
    assert "Disallow: /api/" in robots.text
    assert "Sitemap: https://sales.example.com/sitemap.xml" in robots.text
    assert sitemap.status_code == 200
    assert sitemap.headers["content-type"].startswith("application/xml")
    for route in routes["routes"]:
        assert f"<loc>https://sales.example.com{route['path']}</loc>" in sitemap.text


def test_build_assets_are_cached_and_files_cannot_escape_the_build_folder(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("do not serve")
    client, _ = client_for(tmp_path)
    with client:
        asset = client.get("/assets/index-abc123.js")
        icon = client.get("/favicon.svg")
        sneaky = client.get("/..%2Fsecret.txt")
        api_404 = client.get("/api/does-not-exist")
    assert asset.status_code == 200
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert icon.status_code == 200 and "max-age=3600" in icon.headers["cache-control"]
    assert "do not serve" not in sneaky.text
    assert api_404.status_code == 404 and api_404.headers["content-type"].startswith("application/json")


def test_a_localhost_base_url_falls_back_to_the_real_host():
    assert seo.base_url_for("http://localhost:8000", "https://demo.onrender.com/", "demo.onrender.com") == "https://demo.onrender.com"
    assert seo.base_url_for("https://sales.example.com/", "https://demo.onrender.com/", "demo.onrender.com") == "https://sales.example.com"
    assert seo.base_url_for("http://localhost:8000", "http://localhost:8000/", "localhost") == "http://localhost:8000"


def test_robots_and_sitemap_work_without_a_frontend_build(tmp_path):
    app = create_app(make_settings(tmp_path), static_dir=tmp_path / "no-build")
    with TestClient(app) as client:
        assert client.get("/robots.txt").status_code == 200
        assert "<loc>http://testserver/</loc>" in client.get("/sitemap.xml").text


def test_head_requests_are_answered(tmp_path):
    client, _ = client_for(tmp_path)
    with client:
        assert client.head("/").status_code == 200
        assert client.head("/leads").status_code == 200
        assert client.head("/robots.txt").status_code == 200
        assert client.head("/no-such-page").status_code == 404
