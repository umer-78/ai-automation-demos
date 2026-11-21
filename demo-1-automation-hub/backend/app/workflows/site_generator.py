"""Module C (stretch): AI website draft generator.

The model writes the inner HTML of four sections (hero, services, proof, call to action) using a
small class-based design system. Every section is sanitised (no scripts, no inline styles, no
event handlers, class allowlist) and wrapped in a trusted page shell with a palette derived from
the colour preference. Regenerating a section replaces only that block; the other sections are
copied byte for byte into the new version.
"""

from __future__ import annotations

import colorsys
import html
import re
import uuid
from typing import Any

import nh3
from sqlalchemy import select

from app.context import Context
from app.db import rows_to_dicts, site_drafts, utcnow
from app.services.automation_log import AutomationRun

SECTIONS = ("hero", "services", "proof", "cta")
SECTION_LABELS = {"hero": "Hero", "services": "Services", "proof": "Proof", "cta": "Call to action"}

ALLOWED_TAGS = {"div", "h1", "h2", "h3", "h4", "p", "span", "strong", "em", "ul", "ol", "li", "a", "blockquote", "figure", "figcaption", "br", "hr", "small"}
ALLOWED_CLASSES = {
    "container", "section-head", "eyebrow", "display", "lead", "muted", "small", "center",
    "btn", "btn-primary", "btn-ghost", "btn-row", "pills", "pill", "grid-2", "grid-3", "split",
    "card", "card-icon", "checklist", "stats", "stat", "stat-value", "stat-label", "quote",
    "quote-author", "placeholder", "panel", "kicker",
}
NAMED_COLOURS = {
    "teal": "#0d9488", "blue": "#2563eb", "navy": "#1e3a8a", "green": "#16a34a", "forest": "#166534",
    "emerald": "#059669", "mint": "#10b981", "red": "#dc2626", "burgundy": "#881337", "orange": "#ea580c",
    "amber": "#d97706", "yellow": "#ca8a04", "gold": "#b7791f", "purple": "#7c3aed", "violet": "#7c3aed",
    "indigo": "#4f46e5", "pink": "#db2777", "rose": "#e11d48", "coral": "#f0644f", "cyan": "#0891b2",
    "sky": "#0284c7", "brown": "#92400e", "black": "#111827", "charcoal": "#1f2937", "grey": "#475569",
    "gray": "#475569", "slate": "#334155", "lime": "#65a30d", "olive": "#4d7c0f",
}


class SiteError(RuntimeError):
    pass


# --------------------------------------------------------------------------- palette
def _hex_to_rgb(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return tuple(int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in rgb)


def _shift(hex_colour: str, *, lightness: float | None = None, hue: float = 0.0, sat: float | None = None) -> str:
    h, l, s = colorsys.rgb_to_hls(*_hex_to_rgb(hex_colour))
    h = (h + hue) % 1.0
    return _rgb_to_hex(colorsys.hls_to_rgb(h, lightness if lightness is not None else l, sat if sat is not None else s))


def palette_for(preference: str) -> dict[str, str]:
    pref = (preference or "").strip().lower()
    match = re.search(r"#(?:[0-9a-f]{6}|[0-9a-f]{3})\b", pref)
    base = match.group(0) if match else next((v for k, v in NAMED_COLOURS.items() if k in pref), "#0d9488")
    _, l, s = colorsys.rgb_to_hls(*_hex_to_rgb(base))
    primary = base if 0.25 <= l <= 0.55 else _shift(base, lightness=0.42)
    return {
        "primary": primary,
        "primary_dark": _shift(primary, lightness=max(0.12, l - 0.18) if 0.25 <= l <= 0.55 else 0.26),
        "primary_soft": _shift(primary, lightness=0.95, sat=min(1.0, s)),
        "accent": _shift(primary, hue=0.08, lightness=0.5),
        "ink": "#0f172a",
        "muted": "#64748b",
        "surface": "#ffffff",
        "canvas": _shift(primary, lightness=0.985, sat=0.4),
    }


# --------------------------------------------------------------------------- sanitising
def sanitize_section(fragment: str) -> str:
    cleaned = nh3.clean(
        fragment or "",
        tags=ALLOWED_TAGS,
        clean_content_tags={"script", "style", "iframe", "object", "embed", "noscript", "template", "svg", "math"},
        attributes={"a": {"href"}},
        allowed_classes={tag: ALLOWED_CLASSES for tag in ALLOWED_TAGS},
        url_schemes={"http", "https", "mailto", "tel"},
        link_rel="noopener noreferrer nofollow",
    )
    return cleaned.strip()


def _strip_tags(fragment: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment)).strip()


# --------------------------------------------------------------------------- page shell
def assemble_page(inputs: dict[str, Any], sections: dict[str, str], *, version: int, title: str | None = None, description: str | None = None) -> str:
    p = palette_for(inputs.get("colour", ""))
    name = html.escape(inputs["business_name"])
    page_title = html.escape(title or f"{inputs['business_name']} | {inputs['industry']}")
    meta = html.escape(description or f"{inputs['business_name']}: {', '.join(inputs['services'])}.")
    body = "\n".join(
        f'<section id="{key}" class="nw-section nw-{key}" data-section="{key}"><div class="container">{sections[key]}</div></section>'
        for key in SECTIONS
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{page_title}</title>
<meta name="description" content="{meta}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Plus+Jakarta+Sans:wght@600;700;800&display=swap" rel="stylesheet">
<style>
:root{{--primary:{p['primary']};--primary-dark:{p['primary_dark']};--primary-soft:{p['primary_soft']};--accent:{p['accent']};--ink:{p['ink']};--muted:{p['muted']};--surface:{p['surface']};--canvas:{p['canvas']};--radius:18px}}
*{{box-sizing:border-box;margin:0;padding:0}}
html{{scroll-behavior:smooth}}
body{{font-family:Inter,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:var(--ink);background:var(--canvas);line-height:1.6;-webkit-font-smoothing:antialiased}}
a{{color:var(--primary);text-decoration:none}}
h1,h2,h3,h4{{font-family:'Plus Jakarta Sans',Inter,sans-serif;line-height:1.15;letter-spacing:-.02em}}
.container{{max-width:1120px;margin:0 auto;padding:0 24px}}
.nw-nav{{position:sticky;top:0;z-index:10;backdrop-filter:blur(12px);background:color-mix(in srgb,var(--surface) 82%,transparent);border-bottom:1px solid color-mix(in srgb,var(--ink) 8%,transparent)}}
.nw-nav .container{{display:flex;align-items:center;justify-content:space-between;height:68px}}
.nw-logo{{font-family:'Plus Jakarta Sans',sans-serif;font-weight:800;font-size:1.15rem;color:var(--ink);display:flex;gap:10px;align-items:center}}
.nw-logo i{{width:28px;height:28px;border-radius:9px;background:linear-gradient(135deg,var(--primary),var(--accent));display:inline-block}}
.nw-links{{display:flex;gap:28px;font-weight:500;font-size:.95rem}}
.nw-links a{{color:var(--muted)}}
.nw-section{{padding:96px 0}}
.nw-hero{{padding:120px 0 96px;background:radial-gradient(1200px 500px at 85% -10%,color-mix(in srgb,var(--accent) 28%,transparent),transparent 60%),radial-gradient(900px 500px at -10% 20%,var(--primary-soft),transparent 60%)}}
.nw-services{{background:var(--surface)}}
.nw-cta{{background:linear-gradient(135deg,var(--primary-dark),var(--primary));color:#fff}}
.nw-cta .lead,.nw-cta .muted,.nw-cta p{{color:color-mix(in srgb,#fff 82%,transparent)}}
.nw-cta .btn-primary{{background:#fff;color:var(--primary-dark)}}
.nw-cta .btn-ghost{{border-color:color-mix(in srgb,#fff 50%,transparent);color:#fff}}
.eyebrow,.kicker{{display:inline-block;font-size:.9rem;font-weight:600;letter-spacing:.01em;color:var(--primary);background:var(--primary-soft);padding:6px 12px;border-radius:999px;margin-bottom:18px}}
.nw-cta .eyebrow{{background:color-mix(in srgb,#fff 15%,transparent);color:#fff}}
.display{{font-size:clamp(2.4rem,5.4vw,4.2rem);font-weight:800;max-width:17ch;margin-bottom:20px}}
h2{{font-size:clamp(1.8rem,3.4vw,2.6rem);margin-bottom:14px}}
h3{{font-size:1.2rem;margin-bottom:8px}}
.lead{{font-size:1.2rem;color:var(--muted);max-width:60ch;margin-bottom:28px}}
.muted{{color:var(--muted)}} .small{{font-size:.875rem}} .center{{text-align:center;margin-left:auto;margin-right:auto}}
.section-head{{max-width:720px;margin-bottom:44px}}
.section-head.center .lead{{margin-left:auto;margin-right:auto}}
.btn{{display:inline-flex;align-items:center;gap:8px;padding:14px 26px;border-radius:999px;font-weight:600;border:1.5px solid transparent;transition:transform .2s,box-shadow .2s}}
.btn:hover{{transform:translateY(-2px)}}
.btn-primary{{background:var(--primary);color:#fff;box-shadow:0 10px 30px -10px var(--primary)}}
.btn-ghost{{border-color:color-mix(in srgb,var(--ink) 18%,transparent);color:var(--ink)}}
.btn-row{{display:flex;flex-wrap:wrap;gap:14px;margin-bottom:28px}}
.pills{{display:flex;flex-wrap:wrap;gap:10px;list-style:none}}
.pill{{padding:8px 14px;border-radius:999px;background:var(--surface);border:1px solid color-mix(in srgb,var(--ink) 10%,transparent);font-size:.9rem;font-weight:500}}
.grid-2,.grid-3,.stats{{display:grid;gap:22px}}
.grid-2{{grid-template-columns:repeat(2,minmax(0,1fr))}}
.grid-3{{grid-template-columns:repeat(3,minmax(0,1fr))}}
.stats{{grid-template-columns:repeat(3,minmax(0,1fr));margin-bottom:28px}}
.split{{display:grid;grid-template-columns:1.1fr .9fr;gap:48px;align-items:center}}
.card,.panel{{background:var(--surface);border:1px solid color-mix(in srgb,var(--ink) 8%,transparent);border-radius:var(--radius);padding:28px;box-shadow:0 1px 2px rgba(15,23,42,.04),0 12px 32px -18px rgba(15,23,42,.18)}}
.nw-services .card{{background:var(--canvas)}}
.card-icon{{display:inline-grid;place-items:center;width:48px;height:48px;border-radius:14px;background:var(--primary-soft);font-size:1.5rem;margin-bottom:16px}}
.checklist{{list-style:none;margin-top:14px;display:grid;gap:8px}}
.checklist li{{padding-left:26px;position:relative;color:var(--muted)}}
.checklist li::before{{content:"";position:absolute;left:0;top:.55em;width:14px;height:8px;border-left:2.5px solid var(--primary);border-bottom:2.5px solid var(--primary);transform:rotate(-45deg)}}
.stat{{background:var(--surface);border-radius:var(--radius);padding:24px;border:1px solid color-mix(in srgb,var(--ink) 8%,transparent)}}
.stat-value{{display:block;font-family:'Plus Jakarta Sans',sans-serif;font-size:2rem;font-weight:800;color:var(--primary)}}
.stat-label{{color:var(--muted);font-size:.95rem}}
.quote{{background:var(--surface);border-radius:var(--radius);padding:28px;border:1px solid color-mix(in srgb,var(--ink) 8%,transparent);font-size:1.05rem}}
.quote-author{{display:block;margin-top:14px;font-weight:600;color:var(--ink);font-size:.95rem}}
.placeholder{{background:#fff7d6;color:#7a5b00;border-radius:6px;padding:0 6px;font-size:.92em}}
.nw-footer{{padding:36px 0;color:var(--muted);font-size:.875rem;background:var(--surface);border-top:1px solid color-mix(in srgb,var(--ink) 8%,transparent)}}
.nw-footer .container{{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}}
@media (max-width:860px){{.grid-3,.stats,.grid-2,.split{{grid-template-columns:1fr}}.nw-links{{display:none}}.nw-section{{padding:72px 0}}}}
</style>
</head>
<body>
<header class="nw-nav"><div class="container"><a class="nw-logo" href="#hero"><i></i>{name}</a>
<nav class="nw-links"><a href="#services">Services</a><a href="#proof">Why us</a><a href="#cta">Contact</a></nav>
<a class="btn btn-primary" href="#cta">Get in touch</a></div></header>
<main>
{body}
</main>
<footer class="nw-footer"><div class="container"><span>&copy; {name}</span><span>Draft v{version} prepared by Northwind Digital. Replace highlighted placeholders before launch.</span></div></footer>
</body>
</html>
"""


# --------------------------------------------------------------------------- offline content
_ICONS = [
    (("clean", "whiten", "dental", "teeth", "smile"), "✨"),
    (("consult", "advice", "strategy", "plan"), "💬"),
    (("design", "brand", "web", "creative"), "🎨"),
    (("repair", "fix", "install", "build"), "🛠️"),
    (("train", "coach", "fitness", "class", "yoga"), "💪"),
    (("food", "meal", "cater", "bake", "coffee"), "🍽️"),
    (("legal", "law", "contract", "will"), "⚖️"),
    (("home", "property", "real estate", "house"), "🏡"),
    (("care", "health", "therapy", "clinic"), "🩺"),
    (("garden", "lawn", "landscape", "plant"), "🌿"),
    (("tax", "account", "book", "finance"), "📊"),
]


def _icon(text: str, i: int) -> str:
    low = text.lower()
    for keys, icon in _ICONS:
        if any(k in low for k in keys):
            return icon
    return ("⭐", "🚀", "🤝")[i % 3]


def _tone_words(tone: str) -> dict[str, str]:
    t = (tone or "").lower()
    if any(k in t for k in ("premium", "luxury", "elegant", "sophisticated")):
        return {"adj": "tailored", "promise": "an exceptional experience from the first call", "cta": "Book a private consultation"}
    if any(k in t for k in ("bold", "energetic", "fun", "playful")):
        return {"adj": "no-nonsense", "promise": "real results, fast", "cta": "Let's get started"}
    if any(k in t for k in ("professional", "corporate", "formal", "expert")):
        return {"adj": "expert", "promise": "dependable work and clear communication", "cta": "Request a consultation"}
    return {"adj": "friendly", "promise": "honest advice and work you can rely on", "cta": "Get a free quote"}


def offline_section(section: str, inputs: dict[str, Any], variant: int = 0) -> str:
    e = {k: html.escape(str(v)) for k, v in inputs.items() if isinstance(v, str)}
    services = [html.escape(s) for s in inputs["services"]]
    tw = _tone_words(inputs.get("tone", ""))
    name, industry = e["business_name"], e["industry"]
    if section == "hero":
        headlines = [
            f"{services[0]} done properly, by people who care",
            f"{tw['adj'].capitalize()} {industry.lower()} you can count on",
            f"{name}: {services[0].lower()}, {services[1].lower()} and more",
            f"The {industry.lower()} team your neighbours recommend",
        ]
        pills = "".join(f'<li class="pill">{s}</li>' for s in services)
        return (
            f'<span class="eyebrow">{industry}</span>'
            f'<h1 class="display">{headlines[variant % len(headlines)]}</h1>'
            f'<p class="lead">{name} offers {services[0].lower()}, {services[1].lower()} and {services[2].lower()} '
            f"with {tw['promise']}.</p>"
            f'<div class="btn-row"><a class="btn btn-primary" href="#cta">{tw["cta"]}</a>'
            f'<a class="btn btn-ghost" href="#services">See our services</a></div>'
            f'<ul class="pills">{pills}</ul>'
        )
    if section == "services":
        intros = [
            "Everything you need, handled by one team.",
            "Pick one service or combine them. Either way you get one point of contact.",
            "Straightforward services, clear pricing, no surprises.",
        ]
        cards = "".join(
            f'<div class="card"><span class="card-icon">{_icon(s, i)}</span><h3>{s}</h3>'
            f"<p class=\"muted\">{tw['adj'].capitalize()} {s.lower()} planned around your goals and timeline.</p>"
            f'<ul class="checklist"><li>Clear scope and fixed quote</li><li>Dedicated point of contact</li></ul></div>'
            for i, s in enumerate(services)
        )
        return (
            f'<div class="section-head"><span class="kicker">What we do</span><h2>Services at {name}</h2>'
            f'<p class="lead">{intros[variant % len(intros)]}</p></div><div class="grid-3">{cards}</div>'
        )
    if section == "proof":
        titles = ["Why clients choose us", f"Trusted by people who expect more from their {industry.lower()}", "Proof, not promises"]
        return (
            f'<div class="section-head"><span class="kicker">Proof</span><h2>{titles[variant % len(titles)]}</h2>'
            '<p class="lead">Swap the highlighted placeholders for real numbers and reviews before launch.</p></div>'
            '<div class="stats">'
            '<div class="stat"><span class="stat-value"><span class="placeholder">[Add rating]</span></span><span class="stat-label">Average Google rating</span></div>'
            '<div class="stat"><span class="stat-value"><span class="placeholder">[Add number]</span></span><span class="stat-label">Happy customers</span></div>'
            '<div class="stat"><span class="stat-value"><span class="placeholder">[Add years]</span></span><span class="stat-label">Years in business</span></div>'
            "</div><div class=\"grid-2\">"
            '<blockquote class="quote">"<span class="placeholder">[Paste a real customer review here]</span>"'
            '<span class="quote-author"><span class="placeholder">[Customer name]</span></span></blockquote>'
            '<blockquote class="quote">"<span class="placeholder">[Paste a second review here]</span>"'
            '<span class="quote-author"><span class="placeholder">[Customer name]</span></span></blockquote></div>'
        )
    if section == "cta":
        heads = ["Ready when you are", f"Let's talk about your {services[0].lower()}", "Get a clear plan and price this week"]
        return (
            f'<div class="split"><div><span class="eyebrow">Get in touch</span><h2>{heads[variant % len(heads)]}</h2>'
            f'<p class="lead">Tell us what you need and {name} will reply within one working day.</p>'
            f'<div class="btn-row"><a class="btn btn-primary" href="mailto:hello@example.com">{tw["cta"]}</a>'
            f'<a class="btn btn-ghost" href="tel:+10000000000">Call us</a></div></div>'
            '<div class="panel"><h3>Contact details</h3><p class="muted"><span class="placeholder">[Phone]</span><br>'
            '<span class="placeholder">[Email]</span><br><span class="placeholder">[Address and opening hours]</span></p></div></div>'
        )
    raise SiteError(f"unknown section '{section}'")


# --------------------------------------------------------------------------- AI content
DESIGN_GUIDE = (
    "Write inner HTML only (no <html>, <section>, <style>, <script>, inline styles or images). "
    "Allowed tags: div, h1, h2, h3, h4, p, span, strong, em, ul, ol, li, a, blockquote, br, hr, small. "
    "Use only these CSS classes: " + ", ".join(sorted(ALLOWED_CLASSES)) + ". "
    "Patterns: hero = span.eyebrow + h1.display + p.lead + div.btn-row (a.btn.btn-primary href='#cta', "
    "a.btn.btn-ghost href='#services') + ul.pills of li.pill. services = div.section-head (span.kicker, h2, "
    "p.lead) + div.grid-3 of div.card (span.card-icon with one emoji, h3, p.muted, ul.checklist). proof = "
    "div.section-head + div.stats of div.stat (span.stat-value, span.stat-label) + div.grid-2 of "
    "blockquote.quote with span.quote-author. cta = div.split with a text column (span.eyebrow, h2, p.lead, "
    "div.btn-row) and div.panel with contact details. Never invent statistics, awards, reviews, names, "
    "phone numbers or addresses: put them in span.placeholder like [Add Google rating]."
)

SITE_SCHEMA = {
    "type": "object",
    "properties": {
        "page_title": {"type": "string"},
        "meta_description": {"type": "string"},
        "hero": {"type": "string", "description": "Inner HTML of the hero section"},
        "services": {"type": "string", "description": "Inner HTML of the services section"},
        "proof": {"type": "string", "description": "Inner HTML of the proof section"},
        "cta": {"type": "string", "description": "Inner HTML of the call-to-action section"},
    },
    "required": ["page_title", "meta_description", "hero", "services", "proof", "cta"],
}
SECTION_SCHEMA = {
    "type": "object",
    "properties": {"html": {"type": "string", "description": "New inner HTML for the section"}},
    "required": ["html"],
}
SITE_SYSTEM = "You are a conversion-focused web designer and copywriter building one-page small-business websites. " + DESIGN_GUIDE


def _brief_lines(inputs: dict[str, Any]) -> str:
    return (
        f"Business name: {inputs['business_name']}\nIndustry: {inputs['industry']}\nTone: {inputs['tone']}\n"
        f"Three services: {', '.join(inputs['services'])}\nColour preference: {inputs['colour']}"
    )


# --------------------------------------------------------------------------- persistence
def _save_version(
    ctx: Context,
    *,
    group_id: str,
    inputs: dict[str, Any],
    sections: dict[str, str],
    version: int,
    generated_by: str,
    changed_section: str | None,
    title: str | None,
    description: str | None,
) -> dict[str, Any]:
    page = assemble_page(inputs, sections, version=version, title=title, description=description)
    path = f"sites/{group_id}/v{version}.html"
    url = ctx.storage.save_html(path, page)
    row = {
        "group_id": group_id,
        "client_id": inputs.get("client_id"),
        "business_name": inputs["business_name"],
        "inputs": {**inputs, "page_title": title, "meta_description": description},
        "sections": sections,
        "html": page,
        "html_url": url,
        "storage_path": path,
        "version": version,
        "changed_section": changed_section,
        "generated_by": generated_by,
        "created_at": utcnow(),
    }
    with ctx.engine.begin() as conn:
        result = conn.execute(site_drafts.insert().values(**row))
        row["id"] = result.inserted_primary_key[0]
    return row


def _public(row: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in row.items() if k != "html"}
    out["preview_url"] = f"/sites/{row['group_id']}/preview?v={row['version']}"
    out["palette"] = palette_for((row.get("inputs") or {}).get("colour", ""))
    if hasattr(out.get("created_at"), "isoformat"):
        out["created_at"] = out["created_at"].isoformat()
    return out


def generate_site(ctx: Context, inputs: dict[str, Any], *, source: str = "dashboard") -> dict[str, Any]:
    group_id = uuid.uuid4().hex[:12]
    with AutomationRun(ctx.engine, ctx.notifier, "site_draft_generate", source=source, client_id=inputs.get("client_id")) as run:
        title = description = None
        generated_by = "offline-template"
        if ctx.llm.live:
            result = ctx.llm.structured(
                system=SITE_SYSTEM,
                prompt=_brief_lines(inputs) + "\n\nWrite all four sections and return them with submit_site.",
                tool_name="submit_site",
                tool_description="Submit the one-page website sections.",
                schema=SITE_SCHEMA,
                max_tokens=6000,
            )
            data = result.data
            sections = {k: sanitize_section(str(data.get(k, ""))) for k in SECTIONS}
            for key in SECTIONS:  # never ship an empty block
                if len(_strip_tags(sections[key])) < 20:
                    sections[key] = offline_section(key, inputs)
            title, description = str(data.get("page_title") or "")[:120] or None, str(data.get("meta_description") or "")[:200] or None
            generated_by = "ai"
            run.step("ai_written", model=result.model, tokens=result.input_tokens + result.output_tokens)
        else:
            sections = {k: offline_section(k, inputs) for k in SECTIONS}
        row = _save_version(
            ctx, group_id=group_id, inputs=inputs, sections=sections, version=1,
            generated_by=generated_by, changed_section=None, title=title, description=description,
        )
        run.step("saved", storage=row["html_url"], version=1)
        run.set(group_id=group_id, business=inputs["business_name"], generated_by=generated_by)
    return _public(row)


def regenerate_section(ctx: Context, group_id: str, section: str, *, instruction: str = "", source: str = "dashboard") -> dict[str, Any]:
    if section not in SECTIONS:
        raise SiteError(f"section must be one of {', '.join(SECTIONS)}")
    latest = get_draft(ctx, group_id)
    if not latest:
        raise SiteError("draft not found")
    inputs = {k: v for k, v in latest["inputs"].items() if k not in ("page_title", "meta_description")}
    old_sections: dict[str, str] = dict(latest["sections"])
    version = int(latest["version"]) + 1
    with AutomationRun(ctx.engine, ctx.notifier, "site_draft_regenerate_section", source=source, client_id=latest.get("client_id")) as run:
        generated_by = latest["generated_by"]
        if ctx.llm.live:
            others = "\n".join(f"- {SECTION_LABELS[k]}: {_strip_tags(v)[:400]}" for k, v in old_sections.items() if k != section)
            prompt = (
                f"{_brief_lines(inputs)}\n\nRewrite ONLY the {SECTION_LABELS[section]} section. Keep the same business facts.\n"
                f"Other sections for context (do not repeat them):\n{others}\n\n"
                f"Current {SECTION_LABELS[section]} HTML:\n{old_sections[section]}\n\n"
                f"Instruction from the account manager: {instruction or 'Try a fresh angle and stronger copy.'}\n"
                "Return the new inner HTML with submit_section."
            )
            result = ctx.llm.structured(
                system=SITE_SYSTEM, prompt=prompt, tool_name="submit_section",
                tool_description="Submit the rewritten section.", schema=SECTION_SCHEMA, max_tokens=2500,
            )
            new_html = sanitize_section(str(result.data.get("html", "")))
            if len(_strip_tags(new_html)) < 20:
                raise SiteError("the model returned an empty section; nothing was changed")
            generated_by = "ai"
            run.step("ai_written", model=result.model, tokens=result.input_tokens + result.output_tokens)
        else:
            new_html = offline_section(section, inputs, variant=version - 1)
            if new_html == old_sections[section]:
                new_html = offline_section(section, inputs, variant=version)
        sections = {**old_sections, section: new_html}  # untouched sections are reused as-is
        row = _save_version(
            ctx, group_id=group_id, inputs=inputs, sections=sections, version=version, generated_by=generated_by,
            changed_section=section, title=latest["inputs"].get("page_title"), description=latest["inputs"].get("meta_description"),
        )
        run.step("saved", version=version, section=section)
        run.set(group_id=group_id, section=section, version=version)
    return _public(row)


def get_draft(ctx: Context, group_id: str, version: int | None = None) -> dict[str, Any] | None:
    stmt = select(site_drafts).where(site_drafts.c.group_id == group_id)
    stmt = stmt.where(site_drafts.c.version == version) if version else stmt.order_by(site_drafts.c.version.desc())
    with ctx.engine.connect() as conn:
        rows = rows_to_dicts(conn.execute(stmt.limit(1)))
    return rows[0] if rows else None


def list_drafts(ctx: Context) -> list[dict[str, Any]]:
    with ctx.engine.connect() as conn:
        rows = rows_to_dicts(conn.execute(select(site_drafts).order_by(site_drafts.c.id.desc()).limit(100)))
    latest: dict[str, dict[str, Any]] = {}
    versions: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        versions.setdefault(r["group_id"], []).append(
            {"version": r["version"], "changed_section": r["changed_section"], "created_at": r["created_at"], "html_url": r["html_url"]}
        )
        if r["group_id"] not in latest:
            latest[r["group_id"]] = r
    out = []
    for gid, r in latest.items():
        item = _public(r)
        item["versions"] = sorted(versions[gid], key=lambda v: v["version"])
        out.append(item)
    return out
