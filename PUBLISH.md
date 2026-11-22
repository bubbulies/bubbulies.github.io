# Publishing bubbulies.github.io

The GitHub organization `bubbulies` exists. These steps create the repository, push this site and turn on GitHub Pages from `main` → `/docs`. Nothing here costs money.

## 1. Create the repository (once)

1. Open <https://github.com/organizations/bubbulies/repositories/new>.
2. Repository name: **`bubbulies.github.io`** (exactly this, so the site is served at `https://bubbulies.github.io/`).
3. Visibility: **Public** (GitHub Pages on a free organization needs a public repository).
4. Do **not** add a README, .gitignore or license, so the repository stays empty.
5. Click **Create repository**.

## 2. Push the site

From this folder (`~/bubbulies-site`):

```sh
cd ~/bubbulies-site
python3 Tools/verify_public_export.py      # must print "reproducible": true
python3 Tools/test_public_site.py          # must end with OK
git remote add origin https://github.com/bubbulies/bubbulies.github.io.git
git push -u origin main
```

(With SSH: `git remote add origin git@github.com:bubbulies/bubbulies.github.io.git`.)

## 3. Turn on GitHub Pages

1. Open <https://github.com/bubbulies/bubbulies.github.io/settings/pages>.
2. Under **Build and deployment**, set **Source** to **Deploy from a branch**.
3. Set **Branch** to **`main`** and the folder to **`/docs`**, then click **Save**.
4. Wait one or two minutes, then reload the page. It shows "Your site is live at https://bubbulies.github.io/".
5. Tick **Enforce HTTPS** if it is not already on.

The repository's **Actions** tab shows the "Public website checks" run. It only verifies and tests; Pages publishes `docs/` by itself.

## 4. Check the live site

Open each of these and confirm it loads:

- <https://bubbulies.github.io/> (language choice)
- <https://bubbulies.github.io/en/privacy/> and <https://bubbulies.github.io/ar/privacy/>
- <https://bubbulies.github.io/en/terms/>
- <https://bubbulies.github.io/en/support/>
- <https://bubbulies.github.io/en/account-deletion/>
- <https://bubbulies.github.io/app-ads.txt> shows exactly:
  `google.com, pub-7804927976673782, DIRECT, f08c47fec0942fa0`

## 5. Paste the URLs into App Store Connect

| App Store Connect field | URL |
| --- | --- |
| Privacy Policy URL (English localization) | `https://bubbulies.github.io/en/privacy/` |
| Privacy Policy URL (Arabic localization) | `https://bubbulies.github.io/ar/privacy/` |
| Support URL | `https://bubbulies.github.io/en/support/` (Arabic: `https://bubbulies.github.io/ar/support/`) |
| Marketing URL | `https://bubbulies.github.io/` |
| User Privacy Choices URL (optional) | `https://bubbulies.github.io/en/account-deletion/` |

For AdMob to verify `app-ads.txt`, the **Marketing URL** (developer website) on the App Store listing must be `https://bubbulies.github.io/`. AdMob crawls `https://bubbulies.github.io/app-ads.txt`. Verification can take up to a day after the listing is live.

## Later changes

Edit `PublicSite/`, then run:

```sh
python3 Tools/build_public_site.py
python3 Tools/test_public_site.py
python3 Tools/verify_public_export.py --refresh-manifest
git add -A && git commit -m "Describe the change" && git push
```

To change the support email, edit `supportEmail` in `PublicSite/publisher.json` (one place) and run the commands above.
