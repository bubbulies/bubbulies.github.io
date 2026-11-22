#!/usr/bin/env python3
"""Build the bilingual (English/Arabic), tracker-free bubbulies website.

Standard library only. Reads PublicSite/ (publisher.json, content/*.json,
site.css, assets/) and writes a static site to docs/ for GitHub Pages
(main branch, /docs folder). Output is byte-for-byte reproducible: no
timestamps, randomness or environment-dependent values are written.

    python3 Tools/build_public_site.py            # build into docs/
    python3 Tools/build_public_site.py --output DIR
"""
from __future__ import annotations

import argparse
import copy
from datetime import date
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "PublicSite"
PAGE_IDS = ("home", "privacy", "terms", "support", "account-deletion", "credits")
LANGUAGES = ("en", "ar")
TOKENS = {"brand", "seller", "supportEmail", "effectiveDate", "minimumAge", "siteHost"}
CSP = "default-src 'none'; script-src 'none'; style-src 'self'; img-src 'self'; font-src 'self'; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"
WORLD_FILES = ("cloud-meadows", "candy-skies", "crystal-lagoon", "starlight-valley", "moonlight-kingdom")
MONTHS = {
    "en": ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"),
    "ar": ("يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"),
}
# Short, stable paths that redirect (without scripts) to the English pages.
SHORT_LINKS = ("privacy", "terms", "support", "account-deletion", "credits")


class ValidationError(ValueError):
    pass


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def esc(value):
    return html.escape(str(value), quote=True)


# ---------------------------------------------------------------- validation

PLACEHOLDER = re.compile(r"(?:\b(?:TODO|TBD|placeholder|lorem ipsum)\b|\[insert|\{\{[A-Z][A-Z_]+\}\})")


def valid_email(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}", value)) and not PLACEHOLDER.search(value)


def valid_https(value, allow_path=False):
    if not isinstance(value, str) or not value:
        return False
    parts = urlsplit(value)
    return (parts.scheme == "https" and bool(parts.hostname) and "." in parts.hostname and not parts.username
            and not parts.query and not parts.fragment and parts.port in (None, 443)
            and (allow_path or parts.path in ("", "/")) and not re.search(r"\s", value))


def validate_config(config):
    errors = []
    if config.get("schemaVersion") != 1:
        errors.append("publisher.schemaVersion must be 1")
    for field in ("brandName", "publisherName", "appStoreSeller", "hostingProvider"):
        value = config.get(field)
        if not isinstance(value, str) or not value.strip() or PLACEHOLDER.search(value):
            errors.append(f"publisher.{field} is required")
    if not valid_email(config.get("supportEmail")):
        errors.append("publisher.supportEmail must be a real email address")
    if not valid_https(config.get("baseUrl")):
        errors.append("publisher.baseUrl must be an https origin without path, query or fragment")
    try:
        date.fromisoformat(config.get("effectiveDate", ""))
    except (TypeError, ValueError):
        errors.append("publisher.effectiveDate must be YYYY-MM-DD")
    age = config.get("minimumAge")
    if isinstance(age, bool) or not isinstance(age, int) or not 4 <= age <= 18:
        errors.append("publisher.minimumAge must be an integer from 4 to 18")
    store = config.get("appStoreUrl", "")
    if store and not (valid_https(store, allow_path=True) and urlsplit(store).hostname == "apps.apple.com"
                      and re.fullmatch(r"/(?:[a-z]{2}/)?app/(?:[^/]+/)?id[0-9]+", urlsplit(store).path)):
        errors.append("publisher.appStoreUrl must be empty or an apps.apple.com listing URL")
    lines = config.get("appAdsTxt")
    if not isinstance(lines, list) or not lines:
        errors.append("publisher.appAdsTxt must list at least one authorized seller line")
    else:
        for line in lines:
            if not isinstance(line, str) or not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}, pub-[0-9]{16}, (?:DIRECT|RESELLER)(?:, [a-f0-9]{16})?", line):
                errors.append(f"publisher.appAdsTxt line is malformed: {line!r}")
    refs = config.get("references", [])
    if not isinstance(refs, list):
        errors.append("publisher.references must be a list")
    else:
        for ref in refs:
            if not isinstance(ref, dict) or not valid_https(ref.get("url"), allow_path=True) or not ref.get("en") or not ref.get("ar") \
                    or not set(ref.get("pages", [])) <= set(PAGE_IDS) or not ref.get("pages"):
                errors.append(f"publisher.references entry is malformed: {ref!r}")
    return errors


def section_shape(page):
    return [(s.get("id"), len(s.get("paragraphs", [])), len(s.get("items", []))) for s in page.get("sections", [])]


def validate_content(content):
    errors = []
    if set(content) != set(LANGUAGES):
        errors.append("Exactly English and Arabic content are required")
        return errors
    for language in LANGUAGES:
        locale = content[language]
        if set(locale.get("pages", {})) != set(PAGE_IDS):
            errors.append(f"{language}: all six pages are required")
            continue
        if len(locale.get("worlds", [])) != len(WORLD_FILES):
            errors.append(f"{language}: five world names are required")
        for page_id, page in locale["pages"].items():
            for field in ("title", "navTitle", "summary"):
                if not isinstance(page.get(field), str) or not page[field].strip():
                    errors.append(f"{language}/{page_id}: {field} is required")
            ids = []
            for section in page.get("sections", []):
                sid = section.get("id", "")
                ids.append(sid)
                if not re.fullmatch(r"[a-z][a-z0-9-]*", sid):
                    errors.append(f"{language}/{page_id}: unsafe section id {sid!r}")
                if not section.get("title") or not isinstance(section.get("paragraphs"), list) or not isinstance(section.get("items"), list) \
                        or not (section["paragraphs"] or section["items"]):
                    errors.append(f"{language}/{page_id}/{sid}: malformed or empty section")
            if not ids or len(ids) != len(set(ids)):
                errors.append(f"{language}/{page_id}: section ids must be present and unique")
    if not errors:
        if set(content["en"]["ui"]) != set(content["ar"]["ui"]):
            errors.append("English and Arabic UI keys differ")
        for page_id in PAGE_IDS:
            if section_shape(content["en"]["pages"][page_id]) != section_shape(content["ar"]["pages"][page_id]):
                errors.append(f"Translation structure differs on page {page_id}")
    raw = json.dumps(content, ensure_ascii=False)
    unknown = set(re.findall(r"\{\{(\w+)\}\}", raw)) - TOKENS
    if unknown:
        errors.append("Unknown template tokens: " + ", ".join(sorted(unknown)))
    if re.search(r"\{\{(?!\w+\}\})|(?<!\{)\{\w+\}\}", raw):
        errors.append("Malformed template token")
    if re.search(r"<\s*/?\s*[a-z]+[\s>/]", raw, re.I):
        errors.append("Content must be plain text, not HTML")
    if PLACEHOLDER.search(raw):
        errors.append("Content contains placeholder text")
    if "@" in raw.replace("{{supportEmail}}", ""):
        errors.append("Email addresses must come from publisher.supportEmail via {{supportEmail}}")
    return errors


# ---------------------------------------------------------------- content

def load_inputs():
    config = read_json(SITE / "publisher.json")
    content = {language: read_json(SITE / "content" / f"{language}.json") for language in LANGUAGES}
    errors = validate_config(config) + validate_content(content)
    if errors:
        raise ValidationError("\n".join(errors))
    return config, content


def format_date(iso, language):
    value = date.fromisoformat(iso)
    return f"{value.day} {MONTHS[language][value.month - 1]} {value.year}"


def token_values(config, language):
    return {
        "brand": config["brandName"],
        "seller": config["appStoreSeller"],
        "supportEmail": config["supportEmail"],
        "effectiveDate": format_date(config["effectiveDate"], language),
        "minimumAge": str(config["minimumAge"]),
        "siteHost": urlsplit(config["baseUrl"]).hostname,
    }


def resolve(content, config):
    result = copy.deepcopy(content)

    def walk(value, values):
        if isinstance(value, str):
            return re.sub(r"\{\{(\w+)\}\}", lambda m: values[m.group(1)], value)
        if isinstance(value, list):
            return [walk(v, values) for v in value]
        if isinstance(value, dict):
            return {k: walk(v, values) for k, v in value.items()}
        return value

    for language in LANGUAGES:
        result[language] = walk(content[language], token_values(config, language))
    return result


# ---------------------------------------------------------------- rendering

def route(language, page_id):
    return f"{language}/" + ("" if page_id == "home" else page_id + "/")


def prefix(page_id):
    return "../" if page_id == "home" else "../../"


def text_html(value, email):
    """Escape plain text, then link the configured support address."""
    escaped = esc(value)
    if email:
        escaped = escaped.replace(esc(email), f'<a href="mailto:{quote(email, safe="@.+")}">{esc(email)}</a>')
    return escaped


def head(title, description, language, pre, canonical, alternates, robots="index, follow"):
    out = [
        "<!doctype html>",
        f'<html lang="{language}" dir="{"rtl" if language == "ar" else "ltr"}">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">',
        f'<meta http-equiv="Content-Security-Policy" content="{esc(CSP)}">',
        '<meta name="referrer" content="no-referrer">',
        '<meta name="color-scheme" content="light">',
        '<meta name="theme-color" content="#8fd0ff">',
        f'<meta name="robots" content="{robots}">',
        f"<title>{esc(title)}</title>",
        f'<meta name="description" content="{esc(description)}">',
        f'<link rel="icon" type="image/webp" href="{pre}assets/icon-64.webp">',
        f'<link rel="apple-touch-icon" href="{pre}assets/icon-180.webp">',
        f'<link rel="stylesheet" href="{pre}assets/site.css">',
    ]
    if canonical:
        out.append(f'<link rel="canonical" href="{esc(canonical)}">')
    for lang, url in alternates:
        out.append(f'<link rel="alternate" hreflang="{lang}" href="{esc(url)}">')
    out.append("</head>")
    return "\n".join(out)


def render_sections(page, email):
    parts = []
    for s in page["sections"]:
        paragraphs = "".join(f"<p>{text_html(p, email)}</p>" for p in s["paragraphs"])
        items = ""
        if s["items"]:
            tag = "ol" if s["id"] == "in-the-app" else "ul"
            items = f"<{tag}>" + "".join(f"<li>{text_html(i, email)}</li>" for i in s["items"]) + f"</{tag}>"
        parts.append(f'<section class="doc-section" id="{s["id"]}"><h2>{esc(s["title"])}</h2>{paragraphs}{items}</section>')
    return "\n".join(parts)


def header_html(locale, language, page_id, pre):
    ui, pages = locale["ui"], locale["pages"]
    other = "ar" if language == "en" else "en"
    nav = "".join(
        f'<a href="{pre + route(language, p)}"' + (' aria-current="page"' if p == page_id else "") + f'>{esc(pages[p]["navTitle"])}</a>'
        for p in PAGE_IDS)
    return (f'<header class="site-header"><div class="header-inner">'
            f'<a class="brand" href="{pre + route(language, "home")}"><img src="{pre}assets/icon-180.webp" width="44" height="44" alt=""><span lang="en" dir="ltr">bubbulies</span></a>'
            f'<nav aria-label="{esc(ui["navLabel"])}">{nav}</nav>'
            f'<a class="language-link" lang="{other}" hreflang="{other}" href="{pre + route(other, page_id)}">{esc(ui["languageLabel"])}</a>'
            f'</div></header>')


def footer_html(locale, language, config, pre):
    ui, pages = locale["ui"], locale["pages"]
    links = "".join(f'<a href="{pre + route(language, p)}">{esc(pages[p]["navTitle"])}</a>' for p in PAGE_IDS[1:])
    email = config["supportEmail"]
    return (f'<footer class="site-footer"><div class="footer-brand"><img src="{pre}assets/icon-64.webp" width="40" height="40" alt="">'
            f'<div><strong lang="en" dir="ltr">bubbulies</strong><p>{esc(ui["footer"])}</p>'
            f'<small>{esc(ui["footerSeller"])} {esc(config["appStoreSeller"])} · <a href="mailto:{quote(email, safe="@.+")}">{esc(email)}</a></small></div></div>'
            f'<nav aria-label="{esc(ui["allPages"])}">{links}</nav></footer>')


def store_html(locale, config):
    ui = locale["ui"]
    if config.get("appStoreUrl"):
        return f'<a class="button button-pink" rel="noopener" href="{esc(config["appStoreUrl"])}">{esc(ui["appStore"])}</a>'
    return f'<span class="soon-pill">{esc(ui["comingSoon"])}</span>'


def render_home(locale, language, config, pre):
    ui, pages = locale["ui"], locale["pages"]
    page = pages["home"]
    email = config["supportEmail"]
    worlds = "".join(
        f'<figure class="world"><img src="{pre}assets/world-{name}.webp" width="390" height="844" alt="" loading="lazy"><figcaption>{esc(label)}</figcaption></figure>'
        for name, label in zip(WORLD_FILES, locale["worlds"]))
    facts = "".join(f"<li>{esc(ui[key])}</li>" for key in ("factLevels", "factWorlds", "factFree", "factBilingual"))
    cards = "".join(
        f'<a class="info-card" href="{pre + route(language, p)}"><h2>{esc(pages[p]["title"])}</h2><p>{esc(pages[p]["summary"])}</p>'
        f'<span class="read-more">{esc(ui["readMore"])} <span aria-hidden="true">{"←" if language == "ar" else "→"}</span></span></a>'
        for p in PAGE_IDS[1:])
    return (
        f'<main id="main">'
        f'<section class="hero"><div class="hero-copy">'
        f'<p class="eyebrow" lang="en" dir="ltr">bubbulies</p>'
        f'<h1>{esc(ui["tagline"])}</h1>'
        f'<p class="hero-summary">{esc(page["summary"])}</p>'
        f'<div class="hero-actions">{store_html(locale, config)}'
        f'<a class="button button-light" href="#privacy-at-a-glance">{esc(ui["privacyCta"])}</a>'
        f'<a class="button button-light" href="{pre + route(language, "support")}">{esc(ui["homeCta"])}</a></div>'
        f'</div><div class="hero-art" aria-hidden="true">'
        f'<div class="phone"><img class="phone-world" src="{pre}assets/world-cloud-meadows.webp" width="585" height="1266" alt="" fetchpriority="high">'
        f'<img class="phone-mascot" src="{pre}assets/mascot.webp" width="420" height="420" alt=""></div>'
        f'<span class="bubble b1"></span><span class="bubble b2"></span><span class="bubble b3"></span><span class="bubble b4"></span>'
        f'</div></section>'
        f'<ul class="fact-strip">{facts}</ul>'
        f'<section class="worlds" aria-label="{esc(ui["worldsLabel"])}"><h2 class="visually-hidden">{esc(ui["worldsLabel"])}</h2><div class="world-row">{worlds}</div></section>'
        f'<div class="home-content">{render_sections(page, email)}</div>'
        f'<section class="info-grid" aria-label="{esc(ui["allPages"])}">{cards}</section>'
        f'</main>')


def render_document(locale, language, page_id, config, pre):
    ui, page = locale["ui"], locale["pages"][page_id]
    email = config["supportEmail"]
    toc = "".join(f'<li><a href="#{s["id"]}">{esc(s["title"])}</a></li>' for s in page["sections"])
    out = [
        f'<main id="main"><div class="page-intro"><p class="eyebrow">{esc(ui["allPages"])}</p><h1>{esc(page["title"])}</h1><p>{esc(page["summary"])}</p>'
        f'<p class="policy-meta"><span>{esc(ui["updated"])}: <time datetime="{config["effectiveDate"]}">{esc(format_date(config["effectiveDate"], language))}</time></span></p></div>'
        f'<div class="doc-layout"><aside class="contents"><h2>{esc(ui["toc"])}</h2><ol>{toc}</ol>'
        f'<img class="contents-mascot" src="{pre}assets/mascot.webp" width="420" height="420" alt="" loading="lazy"></aside>'
        f'<article class="document">{render_sections(page, email)}'
    ]
    if page_id in ("privacy", "support", "account-deletion"):
        out.append(f'<div class="contact-box"><a class="button button-pink" href="mailto:{quote(email, safe="@.+")}">{esc(ui["contact"])}</a>'
                   f'<span dir="ltr">{esc(email)}</span></div>')
    if page_id == "credits":
        licenses = sorted((SITE / "assets/licenses").glob("*.txt"))
        out.append(f'<section class="reference-links" id="license-notices"><h2>{esc(ui["licenses"])}</h2><ul>'
                   + "".join(f'<li><a href="{pre}assets/licenses/{quote(p.name)}" lang="en" dir="ltr">{esc(p.stem.replace("-LICENSE", "").replace("-", " "))}</a></li>' for p in licenses)
                   + "</ul></section>")
    refs = [r for r in config.get("references", []) if page_id in r["pages"]]
    if refs:
        out.append(f'<section class="reference-links" id="official-information"><h2>{esc(ui["references"])}</h2><ul>'
                   + "".join(f'<li><a href="{esc(r["url"])}" rel="noopener noreferrer">{esc(r[language])}</a></li>' for r in refs)
                   + "</ul></section>")
    out.append(f'<a class="back-top" href="#top">{esc(ui["backTop"])}</a></article></div></main>')
    return "".join(out)


def render_page(content, config, language, page_id):
    locale = content[language]
    ui, page = locale["ui"], locale["pages"][page_id]
    pre = prefix(page_id)
    base = config["baseUrl"].rstrip("/")
    title = f'{ui["brand"]} · {ui["tagline"]}' if page_id == "home" else f'{page["title"]} · {ui["brand"]}'
    alternates = [(lang, f"{base}/{route(lang, page_id)}") for lang in LANGUAGES] + [("x-default", f"{base}/{route('en', page_id)}")]
    body = render_home(locale, language, config, pre) if page_id == "home" else render_document(locale, language, page_id, config, pre)
    parts = [
        head(title, page["summary"], language, pre, f"{base}/{route(language, page_id)}", alternates),
        f'<body id="top" class="page-{page_id}">',
        f'<a class="skip-link" href="#main">{esc(ui["skip"])}</a>',
        header_html(locale, language, page_id, pre),
        body,
        footer_html(locale, language, config, pre),
        "</body>",
        "</html>",
    ]
    return "\n".join(parts) + "\n"


def render_entry(content, config, not_found=False):
    """Bilingual root page and 404. Root-relative links so the 404 works at any depth."""
    base = config["baseUrl"].rstrip("/")
    en, ar = content["en"], content["ar"]
    if not_found:
        title = f'{en["ui"]["notFoundTitle"]} · {ar["ui"]["notFoundTitle"]}'
        heading = (f'<h1><span lang="en" dir="ltr">{esc(en["ui"]["notFoundTitle"])}</span>'
                   f'<span lang="ar" dir="rtl">{esc(ar["ui"]["notFoundTitle"])}</span></h1>'
                   f'<p lang="en" dir="ltr">{esc(en["ui"]["notFoundText"])}</p><p lang="ar" dir="rtl">{esc(ar["ui"]["notFoundText"])}</p>')
        robots, canonical, alternates = "noindex", "", []
    else:
        title = f'bubbulies · {en["ui"]["tagline"]} · {ar["ui"]["tagline"]}'
        heading = (f'<h1><span lang="en" dir="ltr">{esc(en["ui"]["tagline"])}</span><span lang="ar" dir="rtl">{esc(ar["ui"]["tagline"])}</span></h1>'
                   f'<p lang="en" dir="ltr">{esc(en["pages"]["home"]["summary"])}</p><p lang="ar" dir="rtl">{esc(ar["pages"]["home"]["summary"])}</p>')
        robots, canonical = "index, follow", base + "/"
        alternates = [("en", f"{base}/en/"), ("ar", f"{base}/ar/"), ("x-default", base + "/")]
    links = []
    for page_id in PAGE_IDS[1:]:
        links.append(f'<li><a href="/en/{page_id}/" lang="en" dir="ltr">{esc(en["pages"][page_id]["title"])}</a>'
                     f'<a href="/ar/{page_id}/" lang="ar" dir="rtl">{esc(ar["pages"][page_id]["title"])}</a></li>')
    out = [
        head(title, en["pages"]["home"]["summary"], "en", "/", canonical, alternates, robots),
        '<body class="entry-body"><main class="entry-card" id="main">',
        '<img class="entry-mascot" src="/assets/mascot.webp" width="420" height="420" alt="">',
        '<p class="eyebrow">bubbulies</p>',
        heading,
        '<div class="hero-actions entry-actions"><a class="button button-pink" href="/en/" lang="en" dir="ltr">English</a>'
        '<a class="button button-pink" href="/ar/" lang="ar" dir="rtl">العربية</a></div>',
        '<ul class="entry-links">' + "".join(links) + "</ul>",
        "</main></body></html>",
    ]
    return "\n".join(out) + "\n"


def render_redirect(config, page_id):
    target = f'{config["baseUrl"].rstrip("/")}/en/{page_id}/'
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            f'<meta http-equiv="Content-Security-Policy" content="{esc(CSP)}">\n'
            f'<meta http-equiv="refresh" content="0; url=/en/{page_id}/">\n'
            f'<link rel="canonical" href="{esc(target)}">\n<meta name="robots" content="noindex">\n'
            f"<title>bubbulies</title>\n</head>\n<body><p><a href=\"/en/{page_id}/\">{esc(target)}</a></p></body>\n</html>\n")


# ---------------------------------------------------------------- audit

class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.refs, self.duplicates, self.forbidden = set(), [], [], []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("id"):
            if values["id"] in self.ids:
                self.duplicates.append(values["id"])
            self.ids.add(values["id"])
        for attr in ("href", "src", "srcset", "action", "data", "poster"):
            if attr in values:
                self.refs.append((tag, attr, values[attr] or "", values.get("rel", "")))
        if tag in ("script", "iframe", "form", "object", "embed", "frame", "frameset", "input", "button", "audio", "video", "base"):
            self.forbidden.append(tag)
        if any(k.lower().startswith("on") for k in values):
            self.forbidden.append("event-handler")
        if tag == "style" or "style" in values:
            self.forbidden.append("inline-style")
        if tag == "meta" and (values.get("http-equiv") or "").lower() == "set-cookie":
            self.forbidden.append("cookie")


def audit_site(directory):
    directory = Path(directory).resolve()
    parsers, errors, count = {}, [], 0
    for path in sorted(directory.rglob("*.html")):
        parser = PageParser()
        parser.feed(path.read_text(encoding="utf-8"))
        parsers[path] = parser
        rel = path.relative_to(directory)
        if parser.duplicates:
            errors.append(f"{rel}: duplicate ids {parser.duplicates}")
        if parser.forbidden:
            errors.append(f"{rel}: forbidden active content {sorted(set(parser.forbidden))}")
    for path, parser in parsers.items():
        rel = path.relative_to(directory)
        for tag, attr, url, rel_attr in parser.refs:
            count += 1
            if not url or url == "#" or "{{" in url or url.lower().startswith(("javascript:", "data:", "http:")):
                errors.append(f"{rel}: empty/unsafe link {url!r}")
                continue
            parts = urlsplit(url)
            if parts.scheme or parts.netloc:
                if attr != "href" or (tag == "link" and rel_attr not in ("canonical", "alternate")):
                    errors.append(f"{rel}: external resource {url}")
                if parts.scheme not in ("https", "mailto"):
                    errors.append(f"{rel}: unsupported scheme {url}")
                if re.search(r"(?:^|&)(?:utm_[^=]*|gclid|fbclid)=", parts.query, re.I):
                    errors.append(f"{rel}: tracking parameter {url}")
                continue
            local = unquote(parts.path)
            target = (directory / local.lstrip("/")).resolve() if local.startswith("/") else ((path.parent / local).resolve() if local else path)
            if not target.is_relative_to(directory):
                errors.append(f"{rel}: link escapes the site {url}")
                continue
            if target.is_dir():
                target = target / "index.html"
            if not target.exists():
                errors.append(f"{rel}: broken link {url}")
            elif parts.fragment and target in parsers and unquote(parts.fragment) not in parsers[target].ids:
                errors.append(f"{rel}: missing anchor {url}")
    for css in sorted(directory.rglob("*.css")):
        source = css.read_text(encoding="utf-8")
        if re.search(r"@import\b", source, re.I):
            errors.append(f"{css.name}: @import is not allowed")
        for match in re.finditer(r"url\(\s*([^)]*?)\s*\)", source, re.I):
            value = match.group(1).strip("\"'")
            if urlsplit(value).scheme or urlsplit(value).netloc:
                errors.append(f"{css.name}: external CSS resource {value}")
            elif not (css.parent / unquote(urlsplit(value).path)).resolve().is_file():
                errors.append(f"{css.name}: missing CSS resource {value}")
    if errors:
        raise ValidationError("\n".join(errors))
    return {"htmlPages": len(parsers), "checkedReferences": count}


# ---------------------------------------------------------------- build

def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_site(output_dir=ROOT / "docs"):
    config, raw_content = load_inputs()
    content = resolve(raw_content, config)
    output = Path(output_dir).resolve()
    if output in (ROOT.resolve(), SITE.resolve(), Path.home().resolve(), Path("/")):
        raise ValidationError("Output must be a dedicated site directory")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    assets = output / "assets"
    shutil.copytree(SITE / "assets", assets)
    shutil.copyfile(SITE / "site.css", assets / "site.css")
    base = config["baseUrl"].rstrip("/")
    for language in LANGUAGES:
        for page_id in PAGE_IDS:
            write(output / route(language, page_id) / "index.html", render_page(content, config, language, page_id))
    for page_id in SHORT_LINKS:
        write(output / page_id / "index.html", render_redirect(config, page_id))
    write(output / "index.html", render_entry(content, config))
    write(output / "404.html", render_entry(content, config, not_found=True))
    write(output / ".nojekyll", "")
    write(output / "app-ads.txt", "\n".join(config["appAdsTxt"]) + "\n")
    write(output / "robots.txt", f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n")
    urls = [f"{base}/"] + [f"{base}/{route(lang, p)}" for lang in LANGUAGES for p in PAGE_IDS]
    write(output / "sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
          + "".join(f"  <url><loc>{esc(u)}</loc><lastmod>{config['effectiveDate']}</lastmod></url>\n" for u in urls) + "</urlset>\n")
    documents = [{"id": page_id, "language": language, "url": f"{base}/{route(language, page_id)}",
                  "title": content[language]["pages"][page_id]["title"], "summary": content[language]["pages"][page_id]["summary"],
                  "sections": content[language]["pages"][page_id]["sections"]}
                 for language in LANGUAGES for page_id in PAGE_IDS]
    write(output / "legal-documents.json", json_text({
        "schemaVersion": 1, "app": config["brandName"], "publisherName": config["publisherName"],
        "appStoreSeller": config["appStoreSeller"], "supportEmail": config["supportEmail"],
        "effectiveDate": config["effectiveDate"], "minimumAge": config["minimumAge"], "baseUrl": base, "documents": documents}))
    audit = audit_site(output)
    return {"output": str(output.relative_to(ROOT)) if output.is_relative_to(ROOT) else str(output),
            "pages": len(LANGUAGES) * len(PAGE_IDS), "documents": len(documents), "audit": audit,
            "appStoreConnect": {"privacyPolicyUrl": f"{base}/en/privacy/", "privacyPolicyUrlArabic": f"{base}/ar/privacy/",
                                "supportUrl": f"{base}/en/support/", "marketingUrl": f"{base}/"}}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=ROOT / "docs")
    args = parser.parse_args()
    try:
        report = build_site(args.output)
    except (ValidationError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
