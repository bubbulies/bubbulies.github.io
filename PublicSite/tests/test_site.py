"""Tests for the bubbulies public website build. Standard library only."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load("site_builder_under_test", "Tools/build_public_site.py")
verifier = load("site_verifier_under_test", "Tools/verify_public_export.py")
CONFIG = json.loads((ROOT / "PublicSite/publisher.json").read_text(encoding="utf-8"))
EMAIL = CONFIG["supportEmail"]


class BuiltSite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="bubbulies-site-test-")
        cls.out = Path(cls.tmp.name) / "docs"
        cls.report = builder.build_site(cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def page(self, relative):
        return (self.out / relative).read_text(encoding="utf-8")

    def all_html(self):
        return {p.relative_to(self.out).as_posix(): p.read_text(encoding="utf-8") for p in self.out.rglob("*.html")}

    def test_every_route_exists(self):
        for language in ("en", "ar"):
            for page_id in builder.PAGE_IDS:
                self.assertTrue((self.out / builder.route(language, page_id) / "index.html").is_file(), (language, page_id))
        for name in ("index.html", "404.html", ".nojekyll", "robots.txt", "sitemap.xml", "legal-documents.json", "app-ads.txt", "assets/site.css"):
            self.assertTrue((self.out / name).is_file(), name)
        for short in builder.SHORT_LINKS:
            self.assertIn(f'url=/en/{short}/', self.page(f"{short}/index.html"))

    def test_no_scripts_trackers_forms_or_remote_assets(self):
        for name, text in self.all_html().items():
            lowered = text.lower()
            for forbidden in ("<script", "<iframe", "<form", "<input", "<object", "<embed", " onload=", " onclick=", "google-analytics", "googletagmanager", "gtag(", "fonts.googleapis", "set-cookie", "document.cookie"):
                self.assertNotIn(forbidden, lowered, f"{forbidden} in {name}")
            for match in re.finditer(r'\b(?:src|srcset)="([^"]+)"', text):
                self.assertFalse(re.match(r"[a-z]+:|//", match.group(1)), f"remote asset {match.group(1)} in {name}")
            for match in re.finditer(r'<link rel="(?:stylesheet|icon|apple-touch-icon)"[^>]*href="([^"]+)"', text):
                self.assertFalse(re.match(r"[a-z]+:|//", match.group(1)), f"remote link {match.group(1)} in {name}")
            self.assertIn("script-src &#x27;none&#x27;", text, name)
        css = (self.out / "assets/site.css").read_text(encoding="utf-8")
        self.assertNotRegex(css, r"@import|url\(\s*['\"]?(?:https?:)?//")

    def test_language_and_direction(self):
        for page_id in builder.PAGE_IDS:
            self.assertIn('<html lang="en" dir="ltr">', self.page(builder.route("en", page_id) + "index.html"))
            self.assertIn('<html lang="ar" dir="rtl">', self.page(builder.route("ar", page_id) + "index.html"))

    def test_canonical_and_alternates(self):
        privacy = self.page("en/privacy/index.html")
        self.assertIn('<link rel="canonical" href="https://bubbulies.github.io/en/privacy/">', privacy)
        self.assertIn('hreflang="ar" href="https://bubbulies.github.io/ar/privacy/"', privacy)
        self.assertIn('hreflang="x-default"', privacy)

    def test_support_email_comes_from_one_place(self):
        docs_text = "\n".join(self.all_html().values())
        for page in ("privacy", "support", "account-deletion"):
            for language in ("en", "ar"):
                self.assertIn(f'href="mailto:{EMAIL}"', self.page(f"{language}/{page}/index.html"))
        emails = set(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z.]{2,}", docs_text))
        self.assertEqual(emails, {EMAIL})
        self.assertNotIn("bashtoash@gmail.com", docs_text)

    def test_app_ads_txt(self):
        self.assertEqual(self.page("app-ads.txt"), "google.com, pub-7804927976673782, DIRECT, f08c47fec0942fa0\n")

    def test_sitemap_and_robots(self):
        sitemap = self.page("sitemap.xml")
        self.assertEqual(sitemap.count("<loc>"), 13)
        self.assertIn("<loc>https://bubbulies.github.io/ar/account-deletion/</loc>", sitemap)
        self.assertIn("Sitemap: https://bubbulies.github.io/sitemap.xml", self.page("robots.txt"))

    def test_legal_bundle(self):
        bundle = json.loads(self.page("legal-documents.json"))
        self.assertEqual(len(bundle["documents"]), 12)
        self.assertEqual(bundle["supportEmail"], EMAIL)
        self.assertEqual(bundle["minimumAge"], 13)
        self.assertNotIn("{{", json.dumps(bundle, ensure_ascii=False))

    def test_effective_date_is_shown(self):
        self.assertIn('datetime="2026-11-23"', self.page("en/privacy/index.html"))
        self.assertIn("23 November 2026", self.page("en/terms/index.html"))
        self.assertIn("23 نوفمبر 2026", self.page("ar/privacy/index.html"))

    def test_privacy_policy_states_the_reviewed_facts(self):
        en = self.page("en/privacy/index.html")
        for fact in ("Firebase Authentication", "Sign in with Apple", "only your best score and best star rating",
                     "8 days", "top 50", "AdMob", "non-personalised ads", "User Messaging Platform",
                     "European Economic Area", "US states", "App Tracking Transparency", "App Check",
                     "Crashlytics", "off until you turn them on", "“male” or “female”", "never sent to us",
                     "aged 13 and over", "not directed at children under 13", "Remote Config", "GitHub Pages"):
            self.assertIn(fact, en, fact)
        ar = self.page("ar/privacy/index.html")
        for fact in ("8 أيام", "أفضل 50", "Google AdMob", "إعلانات غير مخصّصة", "13 عاماً", "«ذكر» أو «أنثى»", "App Check", "Crashlytics"):
            self.assertIn(fact, ar, fact)

    def test_deletion_and_terms_facts(self):
        deletion = self.page("en/account-deletion/index.html")
        for fact in ("Delete cloud account", "type DELETE", "Delete my bubbulies account", "within one month", "7 days"):
            self.assertIn(fact, deletion)
        self.assertIn("<ol>", deletion)
        terms = self.page("en/terms/index.html")
        self.assertIn("no real-money purchases", terms)
        self.assertIn("no cash value", terms)

    def test_credits_link_every_license(self):
        credits = self.page("en/credits/index.html")
        for path in (ROOT / "PublicSite/assets/licenses").glob("*.txt"):
            self.assertIn(f"assets/licenses/{path.name}", credits)

    def test_audit_counts(self):
        self.assertEqual(self.report["audit"]["htmlPages"], 12 + 2 + len(builder.SHORT_LINKS))

    def test_build_is_reproducible(self):
        with tempfile.TemporaryDirectory() as other:
            second = Path(other) / "docs"
            builder.build_site(second)
            first = {p.relative_to(self.out).as_posix(): p.read_bytes() for p in self.out.rglob("*") if p.is_file()}
            again = {p.relative_to(second).as_posix(): p.read_bytes() for p in second.rglob("*") if p.is_file()}
            self.assertEqual(first, again)


class Validation(unittest.TestCase):
    def content(self):
        return {lang: json.loads((ROOT / f"PublicSite/content/{lang}.json").read_text(encoding="utf-8")) for lang in ("en", "ar")}

    def test_committed_inputs_are_valid(self):
        self.assertEqual(builder.validate_config(CONFIG), [])
        self.assertEqual(builder.validate_content(self.content()), [])

    def test_translation_parity_is_enforced(self):
        content = self.content()
        content["ar"]["pages"]["privacy"]["sections"][0]["paragraphs"].pop()
        self.assertTrue(any("structure differs" in e for e in builder.validate_content(content)))

    def test_html_and_unknown_tokens_are_rejected(self):
        content = self.content()
        content["en"]["pages"]["terms"]["sections"][0]["paragraphs"][0] += " <script>x</script>"
        content["ar"]["pages"]["terms"]["sections"][0]["paragraphs"][0] += " {{bogus}}"
        errors = builder.validate_content(content)
        self.assertTrue(any("plain text" in e for e in errors))
        self.assertTrue(any("Unknown template tokens" in e for e in errors))

    def test_hardcoded_email_in_content_is_rejected(self):
        content = self.content()
        content["en"]["pages"]["support"]["sections"][0]["paragraphs"][0] = "Email someone@example.org"
        self.assertTrue(any("supportEmail" in e for e in builder.validate_content(content)))

    def test_bad_config_is_rejected(self):
        config = copy.deepcopy(CONFIG)
        config.update(supportEmail="not-an-email", baseUrl="http://bubbulies.github.io", appAdsTxt=["google.com pub-1"], minimumAge=3, appStoreUrl="https://example.org/app")
        errors = "\n".join(builder.validate_config(config))
        for field in ("supportEmail", "baseUrl", "appAdsTxt", "minimumAge", "appStoreUrl"):
            self.assertIn(field, errors)

    def test_audit_rejects_scripts_and_broken_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            (site / "index.html").write_text('<a href="missing/">x</a><script>alert(1)</script><img src="https://cdn.example.org/a.png">', encoding="utf-8")
            with self.assertRaises(builder.ValidationError) as caught:
                builder.audit_site(site)
            message = str(caught.exception)
            self.assertIn("broken link", message)
            self.assertIn("forbidden active content", message)
            self.assertIn("external resource", message)


class OneEditEmailChange(unittest.TestCase):
    def test_changing_publisher_email_updates_every_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / "PublicSite"
            shutil.copytree(ROOT / "PublicSite", site)
            config = json.loads((site / "publisher.json").read_text(encoding="utf-8"))
            config["supportEmail"] = "help@bubbulies-test.org"
            (site / "publisher.json").write_text(json.dumps(config), encoding="utf-8")
            original = builder.SITE
            builder.SITE = site
            try:
                out = Path(tmp) / "docs"
                builder.build_site(out)
            finally:
                builder.SITE = original
            text = "\n".join(p.read_text(encoding="utf-8") for p in out.rglob("*.html"))
            self.assertIn("help@bubbulies-test.org", text)
            self.assertNotIn(EMAIL, text)


class Repository(unittest.TestCase):
    def test_committed_repository_verifies(self):
        if not (ROOT / verifier.MANIFEST).is_file():
            self.skipTest("manifest not generated yet")
        result = verifier.verify(ROOT)
        self.assertTrue(result["reproducible"])

    def test_inventory_rejects_private_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "docs").mkdir()
            (Path(tmp) / "docs/GoogleService-Info.plist").write_text("x", encoding="utf-8")
            with self.assertRaises(verifier.ValidationError):
                verifier.inventory(tmp)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "docs").mkdir()
            (Path(tmp) / "docs/x.json").write_text('{"type": "service_' + 'account"}', encoding="utf-8")
            with self.assertRaises(verifier.ValidationError):
                verifier.inventory(tmp)


if __name__ == "__main__":
    unittest.main()
