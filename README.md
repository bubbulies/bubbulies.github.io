# bubbulies website

The public English and Arabic website for the iPhone game **bubbulies**: home, privacy policy, terms of use, support, account deletion and credits. Published with GitHub Pages at <https://bubbulies.github.io/>.

The site is plain HTML and CSS. It has no scripts, analytics, cookies, forms, web fonts or remote assets, and works the same in both languages (Arabic is right-to-left).

## Layout

| Path | What it is |
| --- | --- |
| `PublicSite/publisher.json` | Publisher facts in one place: support email, canonical URL, effective date, minimum age, App Store seller, App Store link, `app-ads.txt` lines, official reference links |
| `PublicSite/content/en.json`, `ar.json` | Page text. Plain text only, same sections in both languages. `{{supportEmail}}`, `{{seller}}`, `{{effectiveDate}}`, `{{minimumAge}}`, `{{siteHost}}` are filled from `publisher.json` |
| `PublicSite/site.css` | The stylesheet |
| `PublicSite/assets/` | WebP copies of the game's original icon, mascot and world art, `provenance.json`, and license notices |
| `PublicSite/tests/` | Unit tests |
| `Tools/build_public_site.py` | Builds `docs/` (standard library only, reproducible) |
| `Tools/verify_public_export.py` | Checks the file inventory and manifest, and that `docs/` rebuilds byte for byte |
| `Tools/test_public_site.py` | Runs the tests |
| `Tools/prepare_assets.py` | Occasional: regenerates the WebP art and license copies from the game repository using local Chrome |
| `docs/` | The generated site that GitHub Pages serves. Do not edit by hand |
| `docs/.well-known/apple-app-site-association`, `docs/i/` | Friend invitations: `https://bubbulies.github.io/i/<code>` opens the iPhone app (Universal Link for `appleAppIds` in `publisher.json`); without the app, GitHub Pages serves `404.html`, which explains the invitation, and `/i/` is a bilingual invitation page. Set `testFlightUrl` (a public TestFlight link) or `appStoreUrl` to show an install button |
| `PUBLICATION_MANIFEST.json` | SHA-256 of every reviewed file |

## Making a change

```sh
# 1. Edit PublicSite/ (e.g. change the support email in publisher.json)
python3 Tools/build_public_site.py                    # regenerate docs/
python3 Tools/test_public_site.py                     # tests
python3 Tools/verify_public_export.py --refresh-manifest   # record the reviewed change and verify
git add -A && git commit
```

When the app's data use changes, update `content/en.json` and `content/ar.json` together and move `effectiveDate` forward. When the App Store listing is live, put its `https://apps.apple.com/...` link in `appStoreUrl` and the home page will show a download button.

The GitHub Actions workflow (`.github/workflows/ci.yml`) runs the verification and tests on every push and pull request. It deploys nothing and uses no secrets.

See [PUBLISH.md](PUBLISH.md) for the first-time publishing steps.
