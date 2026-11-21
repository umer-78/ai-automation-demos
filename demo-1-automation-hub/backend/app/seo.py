"""Search and link-preview metadata for the dashboard pages.

The site is a single-page React app, so every route is served the same index.html. Before it
goes out, the block between the `<!-- seo:start -->` and `<!-- seo:end -->` markers is rewritten
with that page's title, description, canonical URL, Open Graph and Twitter tags and JSON-LD, all
with absolute URLs. Crawlers and link unfurlers that never run JavaScript see the right page.

The per-page text lives in the frontend (src/seo/routes.json) and is copied next to index.html at
build time as seo-routes.json, so there is one source for both sides.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse
from xml.sax.saxutils import escape as xml_escape

START = "<!-- seo:start -->"
END = "<!-- seo:end -->"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0"}


@dataclass(frozen=True)
class SeoConfig:
    site: str
    image: str
    image_alt: str
    routes: dict[str, dict]
    jsonld: dict = field(default_factory=dict)


def load(static_dir: Path) -> SeoConfig | None:
    path = static_dir / "seo-routes.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return SeoConfig(
        site=data["site"],
        image=data["image"],
        image_alt=data.get("imageAlt", ""),
        routes={r["path"]: r for r in data["routes"]},
        jsonld=data.get("jsonld", {}),
    )


def normalise(path: str) -> str:
    """'clients/' and '/clients' are the same page; the home page is '/'."""
    path = path.split("?", 1)[0].strip("/")
    return "/" if path in ("", "index.html") else f"/{path}"


def base_url_for(configured: str, request_base: str, request_host: str | None) -> str:
    """The public origin for absolute URLs.

    PUBLIC_BASE_URL wins, except when it still points at localhost while the request clearly came
    in through a real host name (a deploy where the variable was never set). Values are escaped
    wherever they are written, so the request's own host is safe to fall back on.
    """
    configured = configured.rstrip("/")
    configured_host = urlparse(configured).hostname or ""
    if configured and not (configured_host in LOCAL_HOSTS and (request_host or "") not in LOCAL_HOSTS):
        return configured
    return request_base.rstrip("/")


def _attr(value: str) -> str:
    return html.escape(value, quote=True)


def _script_json(data: dict) -> str:
    # JSON inside <script> must not be able to close the tag or open a comment
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def head_block(cfg: SeoConfig, path: str, base_url: str) -> tuple[str, bool]:
    route = cfg.routes.get(path)
    found = route is not None
    home = cfg.routes.get("/") or next(iter(cfg.routes.values()))
    title = route["title"] if route else f"Page not found | {cfg.site}"
    description = (route or home)["description"]
    url = f"{base_url}{path}"
    image = f"{base_url}{cfg.image}"
    tags = [
        f"<title>{html.escape(title)}</title>",
        f'<meta name="description" content="{_attr(description)}" />',
        f'<meta name="robots" content="{"index, follow" if found else "noindex"}" />',
    ]
    if found:
        tags.append(f'<link rel="canonical" href="{_attr(url)}" />')
    tags += [
        '<meta property="og:type" content="website" />',
        f'<meta property="og:site_name" content="{_attr(cfg.site)}" />',
        '<meta property="og:locale" content="en_US" />',
        f'<meta property="og:title" content="{_attr(title)}" />',
        f'<meta property="og:description" content="{_attr(description)}" />',
        f'<meta property="og:url" content="{_attr(url)}" />',
        f'<meta property="og:image" content="{_attr(image)}" />',
        '<meta property="og:image:width" content="1200" />',
        '<meta property="og:image:height" content="630" />',
        f'<meta property="og:image:alt" content="{_attr(cfg.image_alt)}" />',
        '<meta name="twitter:card" content="summary_large_image" />',
        f'<meta name="twitter:title" content="{_attr(title)}" />',
        f'<meta name="twitter:description" content="{_attr(description)}" />',
        f'<meta name="twitter:image" content="{_attr(image)}" />',
    ]
    if cfg.jsonld:
        ld = {**cfg.jsonld, "url": f"{base_url}/", "image": image}
        tags.append(f'<script type="application/ld+json">{_script_json(ld)}</script>')
    indent = "\n    "
    return f"{START}{indent}{indent.join(tags)}{indent}{END}", found


def render_index(template: str, cfg: SeoConfig | None, path: str, base_url: str) -> tuple[str, int]:
    """index.html for one route, and the HTTP status: 404 for paths that are not pages."""
    path = normalise(path)
    if cfg is None or START not in template or END not in template:
        return template, 200
    block, found = head_block(cfg, path, base_url)
    start = template.index(START)
    end = template.index(END) + len(END)
    return template[:start] + block + template[end:], 200 if found else 404


def robots_txt(base_url: str) -> str:
    return f"User-agent: *\nAllow: /\nDisallow: /api/\n\nSitemap: {base_url}/sitemap.xml\n"


def sitemap_xml(cfg: SeoConfig | None, base_url: str) -> str:
    paths = list(cfg.routes) if cfg else ["/"]
    rows = "".join(
        f"  <url><loc>{xml_escape(base_url + p)}</loc><changefreq>{'daily' if p == '/' else 'weekly'}</changefreq>"
        f"<priority>{'1.0' if p == '/' else '0.6'}</priority></url>\n"
        for p in paths
    )
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{rows}</urlset>\n'
