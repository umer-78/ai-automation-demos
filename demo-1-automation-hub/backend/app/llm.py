"""Claude integration plus a clearly labelled offline engine.

With ANTHROPIC_API_KEY set, every brief, summary and site comes from Claude (structured output via a
forced tool call, so the JSON is always valid). Without a key, or if Claude errors, the offline
engine runs instead and every result carries an `engine` label saying which one produced it.
"""
from __future__ import annotations

import html as html_lib
import re
from typing import Any

from .config import Settings

OFFLINE = "offline engine (no API key)"
SECTIONS = ["hero", "services", "proof", "cta"]


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = None

    @property
    def live(self) -> bool:
        return self.settings.live_model

    @property
    def label(self) -> str:
        return f"live Claude ({self.settings.claude_model})" if self.live else OFFLINE

    def _anthropic(self):
        if self._client is None:
            import anthropic  # imported lazily so the offline demo needs no key
            self._client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key, timeout=60.0, max_retries=2)
        return self._client

    def structured(self, system: str, prompt: str, tool: str, schema: dict, max_tokens: int = 1500) -> dict:
        resp = self._anthropic().messages.create(
            model=self.settings.claude_model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": prompt}],
            tools=[{"name": tool, "description": "Return the result in this exact structure.", "input_schema": schema}],
            tool_choice={"type": "tool", "name": tool},
        )
        for block in resp.content:
            if getattr(block, "type", "") == "tool_use" and block.name == tool:
                return dict(block.input)
        raise LLMError("Claude returned no structured output")

    # ---------- Module A: client brief ----------
    def write_brief(self, client: dict, service: str, website_text: str | None) -> tuple[dict, str]:
        if not self.live:
            return offline_brief(client, service), OFFLINE
        schema = {"type": "object", "required": ["audience", "tone", "quick_wins"], "properties": {
            "audience": {"type": "string", "description": "One sentence: who the client sells to."},
            "tone": {"type": "string", "description": "2-5 words describing the brand voice."},
            "quick_wins": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "string"},
                           "description": "Exactly 3 specific, actionable quick wins for this service in the first 30 days."}}}
        site = (website_text or "")[:4000] or "(website could not be read; use the industry and services only)"
        prompt = (f"Client: {client['name']}\nIndustry: {client.get('industry') or 'unknown'}\n"
                  f"Services bought: {', '.join(client.get('services') or [])}\nThis brief is for: {service}\n"
                  f"Website text:\n{site}\n\nWrite the onboarding brief.")
        data = self.structured("You are a senior strategist at a digital marketing agency. Be specific and concise; "
                               "never invent facts about the client that the inputs don't support.", prompt,
                               "client_brief", schema, 800)
        wins = [str(x) for x in data.get("quick_wins", [])][:3]
        if len(wins) != 3:
            raise LLMError("brief did not contain exactly 3 quick wins")
        return {"audience": str(data["audience"]), "tone": str(data["tone"]), "quick_wins": wins}, self.label

    # ---------- Module B: weekly summary ----------
    def weekly_summaries(self, numbers: list[dict]) -> tuple[dict[str, list[str]], str]:
        if not self.live:
            return {n["client_id"]: offline_summary(n) for n in numbers}, OFFLINE
        schema = {"type": "object", "required": ["clients"], "properties": {"clients": {"type": "array", "items": {
            "type": "object", "required": ["client_id", "sentences"], "properties": {
                "client_id": {"type": "string"},
                "sentences": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "string"}}}}}}}
        lines = []
        for n in numbers:
            alerts = ", ".join(f"{a['channel']} +{a['change_pct']}%" for a in n["alerts"]) or "none"
            lines.append(f"- client_id={n['client_id']} name={n['client']} spend_this_week=${n['cur_spend']} "
                         f"conversions_this_week={n['cur_conv']} cost_per_conversion_now=${n['cpa_now']} "
                         f"cost_per_conversion_last_week=${n['cpa_prev']} change={n['change_pct']}% alerts={alerts}")
        prompt = ("Write exactly 3 plain-English sentences per client for the account manager's weekly update. "
                  "Use only these numbers, name the cost per conversion change, and say what to do next if there "
                  "is an alert.\n" + "\n".join(lines))
        data = self.structured("You write short, factual weekly client updates for a marketing agency.", prompt,
                               "weekly_summaries", schema, 2000)
        out = {c["client_id"]: [str(s) for s in c["sentences"]][:3] for c in data.get("clients", [])}
        missing = [n["client_id"] for n in numbers if len(out.get(n["client_id"], [])) != 3]
        if missing:
            raise LLMError(f"summary missing for {missing}")
        return out, self.label

    # ---------- Module C: website draft ----------
    def generate_site(self, spec: dict) -> tuple[str, str]:
        if not self.live:
            return offline_site(spec, version=1), OFFLINE
        schema = {"type": "object", "required": ["html"], "properties": {"html": {"type": "string"}}}
        prompt = (f"Business: {spec['business_name']}\nIndustry: {spec['industry']}\nTone: {spec['tone']}\n"
                  f"Services: {', '.join(spec['services'])}\nBrand colour: {spec['colour']}\n\n"
                  "Write a complete one-page website as ONE HTML file with inline CSS only (no scripts, no external "
                  "assets). It must contain exactly four <section> elements with data-section=\"hero\", "
                  "\"services\", \"proof\" and \"cta\", in that order. The proof section must use placeholder "
                  "testimonials clearly marked as samples, never invented statistics.")
        data = self.structured("You are a senior web designer who writes clean, accessible, responsive HTML.", prompt,
                               "website", schema, 6000)
        page = str(data["html"])
        if not all(f'data-section="{s}"' in page for s in SECTIONS):
            raise LLMError("generated page is missing a section")
        return page, self.label

    def regenerate_section(self, spec: dict, section: str, current: str, instructions: str) -> tuple[str, str]:
        if not self.live:
            return extract_section(offline_site(spec, version=spec.get("version", 1)), section), OFFLINE
        schema = {"type": "object", "required": ["section_html"], "properties": {"section_html": {"type": "string"}}}
        prompt = (f"Rewrite only this <section data-section=\"{section}\"> for {spec['business_name']} "
                  f"({spec['industry']}, tone: {spec['tone']}, colour {spec['colour']}). Keep the same data-section "
                  f"attribute and the same CSS classes so it still fits the page. Make it clearly different from "
                  f"the current version. Extra instructions: {instructions or 'none'}.\n\nCurrent section:\n{current}")
        data = self.structured("You are a senior web designer. Return one <section> element only.", prompt,
                               "section", schema, 2500)
        new = str(data["section_html"]).strip()
        if f'data-section="{section}"' not in new or not new.startswith("<section"):
            raise LLMError("regenerated section is malformed")
        return new, self.label


# ---------------- offline engine (deterministic, labelled) ----------------

AUDIENCE = {
    "Food & Beverage": "local coffee drinkers and online subscribers within delivery range",
    "Legal": "founders and finance leads at small and mid-size businesses who need commercial counsel",
    "Beauty": "local customers aged 21-45 who book appointments online",
    "SaaS": "operations and finance leads at 50-500 person software companies",
    "Real Estate": "first-time buyers and renters searching within 25 km",
}
WINS = {
    "SEO": ["Fix the top 10 crawl errors and add schema markup to the main pages",
            "Publish one location or service page per core keyword cluster",
            "Set up a monthly rankings baseline the account manager reviews"],
    "Paid Ads": ["Split brand and non-brand campaigns so cost per conversion is readable",
                 "Add conversion tracking checks for every lead form",
                 "Move 15% of budget to the best ad group after two weeks of data"],
    "Web Design": ["Rewrite the hero around one clear offer and one call to action",
                   "Cut the homepage load time under 2.5 seconds",
                   "Add proof (logos, reviews) above the fold"],
}


def offline_brief(client: dict, service: str) -> dict:
    industry = client.get("industry") or ""
    audience = next((v for k, v in AUDIENCE.items() if k.lower() in industry.lower()),
                    f"the customers {client['name']} already serves in {industry or 'its market'}")
    tone = {"SEO": "clear and expert", "Paid Ads": "direct and data-led", "Web Design": "confident and on-brand"}.get(service, "clear")
    return {"audience": audience[0].upper() + audience[1:] + ".", "tone": tone, "quick_wins": WINS.get(service, WINS["SEO"])}


def offline_summary(n: dict) -> list[str]:
    s1 = f"{n['client']} spent ${n['cur_spend']:,} this week for {n['cur_conv']:,} conversions."
    if n["cpa_now"] is None:
        return [s1, "There were no conversions this week, so cost per conversion can't be compared.",
                "Check tracking before changing budgets."]
    s2 = (f"Cost per conversion is ${n['cpa_now']:,.2f}, versus ${n['cpa_prev']:,.2f} last week "
          f"({n['change_pct']:+.1f}%)." if n["cpa_prev"] else f"Cost per conversion is ${n['cpa_now']:,.2f}.")
    if n["alerts"]:
        worst = max(n["alerts"], key=lambda a: a["change_pct"])
        s3 = (f"{worst['channel']} crossed the 25% alert line (+{worst['change_pct']}%), so review its bids "
              f"and search terms before the next budget cycle.")
    elif (n["change_pct"] or 0) < 0:
        s3 = "Efficiency improved, so there is room to scale the best-performing campaigns."
    else:
        s3 = "Performance is steady; keep the current plan and re-check next week."
    return [s1, s2, s3]


HEADLINES = ["{name}: {industry} done properly", "Grow faster with {name}", "{name}, built around your customers"]
CTAS = ["Book a free 20-minute call", "Get your quote this week", "Talk to our team today"]
SERVICE_HEADS = ["What we do", "How we help", "Services, start to finish"]
PROOF_HEADS = ["What clients say", "Why teams choose us", "In our clients' words"]
CTA_HEADS = ["Ready when you are", "Let's get started", "Your next step"]


def offline_site(spec: dict, version: int = 1) -> str:
    name, industry = html_lib.escape(spec["business_name"]), html_lib.escape(spec["industry"])
    tone, colour = html_lib.escape(spec["tone"]), spec.get("colour") or "#4f46e5"
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", colour):
        colour = "#4f46e5"
    v = (version - 1) % 3
    services = "".join(f"<li><h3>{html_lib.escape(s)}</h3><p>{tone.capitalize()} {html_lib.escape(s.lower())} "
                       f"for {industry} businesses.</p></li>" for s in spec["services"])
    head = HEADLINES[v].format(name=name, industry=industry)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name}</title><style>
body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:#0f172a;background:#fff}}
section{{padding:64px 8vw}} h1{{font-size:clamp(2rem,5vw,3.4rem);margin:0 0 16px}} h2{{font-size:1.8rem;margin:0 0 24px}}
.hero{{background:{colour};color:#fff}} .hero p{{font-size:1.2rem;max-width:42rem;opacity:.92}}
.btn{{display:inline-block;margin-top:24px;padding:14px 22px;border-radius:10px;background:#fff;color:{colour};font-weight:700;text-decoration:none}}
.services ul{{list-style:none;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:20px}}
.services li{{border:1px solid #e2e8f0;border-radius:14px;padding:20px}} .proof{{background:#f8fafc}}
.proof blockquote{{margin:0 0 16px;padding:16px 20px;border-left:4px solid {colour};background:#fff}}
.sample{{font-size:.8rem;color:#64748b}} .cta{{text-align:center}} .cta .btn{{background:{colour};color:#fff}}
</style></head><body>
<section class="hero" data-section="hero"><h1>{head}</h1><p>A {tone} {industry} partner. {name} helps customers get results without the guesswork.</p><a class="btn" href="#contact">{CTAS[v]}</a></section>
<section class="services" data-section="services"><h2>{SERVICE_HEADS[v]}</h2><ul>{services}</ul></section>
<section class="proof" data-section="proof"><h2>{PROOF_HEADS[v]}</h2><blockquote>"Replace this with a real client quote." <span class="sample">(sample testimonial)</span></blockquote><blockquote>"Replace this with a second real quote." <span class="sample">(sample testimonial)</span></blockquote></section>
<section class="cta" data-section="cta" id="contact"><h2>{CTA_HEADS[v]}</h2><p>Tell us what you need and we will reply within one business day.</p><a class="btn" href="mailto:hello@example.com">{CTAS[v]}</a></section>
</body></html>"""


def extract_section(page: str, section: str) -> str:
    m = re.search(rf'<section[^>]*data-section="{section}"[^>]*>.*?</section>', page, flags=re.S)
    if not m:
        raise LLMError(f"section {section} not found")
    return m.group(0)


def replace_section(page: str, section: str, new_html: str) -> str:
    current = extract_section(page, section)
    return page.replace(current, new_html, 1)


def as_text(brief: dict[str, Any]) -> str:
    return (f"Audience: {brief['audience']}\nTone: {brief['tone']}\nQuick wins:\n"
            + "\n".join(f"  {i + 1}. {w}" for i, w in enumerate(brief["quick_wins"])))
