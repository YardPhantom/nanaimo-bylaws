# Nanaimo Bylaw Tracker — Compact Handoff

## Current release

- Version: **V0.13.2**
- Next code change: **V0.13.3**
- Deployment path: `C:\inetpub\wwwroot\sites\nanaimo`
- Release ZIP: `nanaimo-bylaw-tracker-v0.13.2.zip`

## Purpose

Independent civic-information archive for publicly available City of Nanaimo bylaws, Council records, and committee, board, commission, and panel activity. Council decisions must remain clearly separated from advisory recommendations.

## Main pages

- `index.html` — homepage, live archive statistics, recent bylaw changes, Council and committee activity
- `bylaws/index.html`, `bylaws/detail.html` — searchable bylaw archive and detail pages
- `timeline.html` — chronological bylaw and civic-meeting activity
- `council/index.html` — Council meetings, documents, decisions, and extracted items
- `committees/index.html`, `committees/detail.html` — committee-group search and detail pages
- `pdf.html` — in-site viewer for approved local or configured cloud PDFs
- `account.html`, `watchlist.html` — Google account, cloud watchlist, preferences, and email alerts
- `categories.html`, `featured.html`, `about.html`, `privacy.html`, `data/index.html`, `sitemap.html`
- `admin/index.html` — intentionally unlinked operational dashboard with a client-side Google gate for `yardplots@gmail.com`, dataset health, copyable commands, quick actions, refresh, and sign-out

## Shared UI and performance

- `shared-header.js` / `shared-header.min.js` inject the same header on all authored pages.
- `shared-footer.js` / `shared-footer.min.js` inject the footer and visible version.
- `tools/verify_shared_header.py` verifies one correctly rooted shared header per authored page.
- Production pages use versioned minified CSS/JS, deferred scripts, IIS compression/caching, and `sw.js` static caching.
- Runtime JSON is loaded through `cloud-data.js`; production uses the configured Worker with local fallback disabled.
- Readable source CSS/JS files remain in releases for maintenance.

## Cloud runtime architecture

- `cloud-config.js` is deployment-specific and currently enables `https://nanaimo-bylaw-data.yardplots.workers.dev` with local fallback disabled.
- `cloud-data.js` / `cloud-data.min.js` provide one runtime URL and fetch layer across all pages.
- `cloud/worker/` contains a read-only Worker bound to private R2 storage. It supports GET, HEAD, OPTIONS, CORS, PDF byte ranges, cache headers, and no directory listing.
- `.github/workflows/cloud-collect.yml` runs the existing collectors at 6:17 a.m. and 6:17 p.m. America/Vancouver time and can also be run manually.
- `.github/workflows/deploy-data-worker.yml` deploys through Node.js 24 and direct pinned Wrangler 4.114.0; `cloudflare/wrangler-action@v3` is intentionally not used because of its deprecated Node.js 20 action runtime.
- `tools/cloud_sync.py` restores current R2 state, uploads changed objects by SHA-256, writes `archive-manifest.json`, publishes `collection-status.json` last, and never deletes historical archive objects.
- `CLOUD_SETUP.md` is the authoritative activation and migration guide.
- Once configured, preserve `cloud-config.js` during ordinary deployment upgrades.

## Collection commands

```powershell
python .\tools\collect_bylaws.py --download-pdfs
python .\tools\collect_council.py --download --years 2026
python .\tools\deduplicate_archive.py --apply
.\tools\collect-all.cmd
.\tools\verify-council.cmd
.\tools\verify-council.cmd --strict
```

Legacy Council-link repair:

```powershell
.\tools\repair-council-links.cmd
```

### Collector and archive behavior

- Both PDF collectors build a SHA-256 index of the existing archive before processing documents.
- Existing archived PDFs are reused and restored to missing live paths without downloading their bodies again.
- Remote `HEAD` validators are checked; a PDF body is downloaded only for a new source or when ETag, Last-Modified, final URL, or reliable content length proves a change.
- Missing `.txt` sidecars are restored from the archive or extracted from the local PDF. A changed PDF never reuses stale live text.
- New and changed content is stored once by SHA-256; same-content downloads resolve to the existing canonical archive path.
- `tools/deduplicate_archive.py --apply` safely consolidates pre-existing same-hash PDFs, rewrites JSON paths, merges sidecars, and aborts before deletion if any JSON file cannot be parsed.
- `collect-all.cmd` deduplicates first, runs both collectors, and fails if duplicate archive PDFs remain.
- Council collection still deduplicates meetings/documents, checkpoints every ten documents, resumes interrupted runs, and writes committee-group records to `data/committee-items.json` and `data/committee-index.json`.
- PDF pages, text size, OCR work, sentence chunks, and regex matching remain bounded to prevent pathological stalls.

## Firebase, admin, and Brevo

- Google is the only sign-in method.
- Root `firebase-config.js` must export `firebaseConfig`; it is deployment-specific and excluded from releases.
- Firestore stores private preferences, cloud watchlists, and one email-subscription document per UID.
- `admin/index.html` is hidden from navigation and checks for `yardplots@gmail.com`. Public cloud JSON/PDF records remain intentionally readable; operational credentials and private account data must remain protected.
- Brevo SMTP and Firebase Admin credentials remain server-side or in GitHub Actions secrets.
- Scheduled delivery runs after successful cloud collection and R2 verification.
- Subscription documents contain preferences and activation timestamps only; the sender resolves the address from Firebase Authentication.
- Delivery state uses a one-way recipient hash and event identifiers to suppress duplicates.
- `SUBSCRIPTION_SETUP.md` is the source of truth for secrets, Firestore rules, test mode, dry-run mode, and activation.

```powershell
.\tools\test-brevo-smtp.cmd recipient@example.com
.\tools\send-subscription-updates.cmd --dry-run
```

## Data and classification rules

- Never present an accused person or advisory recommendation as a final Council decision.
- Use labels such as Committee recommendation, Committee motion, Received for information, and Referred to Council.
- Local `.ashx` and `.aspx` paths are invalid; collectors resolve or snapshot them to local PDFs.
- Local PDFs open through `pdf.html`; external City/eSCRIBE links remain official-source links.
- Public category name is `Transportation`; legacy `Transportation & Parking` records are normalized at display/filter time.

## Deployment exclusions

Ordinary release ZIPs must not overwrite:

- `data/bylaws.json`, `data/bylaws-summary.json`, `data/bylaw-relationships.json`, `data/change-log.json`
- `data/council-meetings.json`, `data/council-documents.json`, `data/council-items.json`
- `data/committee-items.json`, `data/committee-index.json`
- `data/council-discussions.json`, `data/council-change-log.json`, `data/council-verification.json`
- everything under `archive/` and `bylaws/pdf/`
- runtime meeting-date folders under `council/` (keep authored `council/index.html` and `council/list.js`)
- `firebase-config.js`, `runtime/subscription.env`, Firebase service-account JSON
- configured `cloud-config.js` after cloud activation
- databases, logs, caches, and temporary files

`data/featured.json` is authored release content and remains included.

## V0.12.7 admin dashboard

- Replaced the private copy of the public data page with an operational admin dashboard.
- Added a signed-in administrator card and direct sign-out control.
- Added refreshable runtime dataset health with required/optional status, modified time, and response size when server headers expose them.
- Added live totals for bylaws, categories, year range, Council documents, and committee items.
- Added copyable collection and verification commands, public-page quick actions, operational-file links, and a clear security-boundary notice.
- Improved unauthorized, unconfigured Firebase, loading, missing-file, mobile, and reduced-motion states.
- Updated all active asset/cache references and the visible site version to V0.12.7.

## V0.12.8 archive reuse and deduplication

- Added shared content-addressed archive helpers for SHA-256 indexing, canonical paths, safe live-file restoration, and remote validator comparison.
- Bylaw and Council collectors now reuse archived PDFs and repair missing text locally instead of downloading files again because a live PDF or text file is missing.
- Changed documents create one new archive PDF and force fresh text extraction; unchanged documents retain their existing archive path.
- Added a safe archive-deduplication command and integrated it before and after the combined collection workflow.
- Corrected the admin archive health state so IIS HTTP 403 directory-listing protection is shown as Protected rather than Unavailable.
- Added automated tests covering reuse, local text repair, changed PDFs, HTML validator changes, duplicate consolidation, sidecar migration, and invalid-JSON abort safety.

## V0.13.1 cloud runtime migration

- Added private R2 storage served through a read-only Worker on `workers.dev`.
- Added GitHub Actions scheduled collection using the same collectors and prior cloud state.
- Added SHA-256-aware cloud pull, publish, verification, archive manifest, and collection status.
- Converted all runtime data loaders, data links, extracted text, archive checks, and PDF viewing to the shared cloud-aware URL layer.
- Added cloud status and manifest information to the admin dashboard.
- Production cloud mode is active; IIS serves the authored site while Worker/R2 serves runtime data and archives.

## V0.13.1 same-version cloud deployment cleanup

- GitHub collection and Worker workflows use current action majors on Ubuntu 24.04.
- Collection fails fast when any required R2 secret is missing.
- Worker CI uses Node.js 24 and direct pinned `npx wrangler@4.114.0 deploy`; `cloudflare/wrangler-action@v3` is not used.
- `CLOUD_SETUP.md` contains the authoritative click-by-click order for creating the GitHub repository, private R2 bucket, R2 object credentials, Worker deployment token, GitHub secrets, final `workers.dev` URL, initial publish, and IIS activation. The account subdomain is configured before the first GitHub deploy.
- The project version remained V0.13.1; the next versioned feature was V0.13.2.

## Next recommended work

Confirm scheduled GitHub collections continue publishing fresh `collection-status.json` timestamps, preserve the active `cloud-config.js` during IIS upgrades, and use V0.13.3 for the next versioned feature release.

### V0.13.1 same-version cloud response cleanup

- `sw.js` clones cacheable responses synchronously before scheduling cache writes, avoiding consumed-body clone failures.
- The R2 Worker passes range options only for actual `Range` requests; full JSON and file responses return HTTP 200, while PDF/browser byte-range requests continue returning HTTP 206.


## V0.13.1 same-version civic count cleanup

- Homepage bylaw, Council-item, committee-item, and Council-document datasets are each fetched once and shared by all homepage counters.
- `Council activity` now displays Council/public-hearing items only, matching the dashboard Council card.
- Its document count now includes unique Council/public-hearing source documents only.
- `Council meetings indexed` excludes committee, board, commission, and panel meetings.
- Committee activity continues to use the dedicated committee dataset with the combined dataset as a fallback.
- Updated the service worker to purge the prior same-version static cache and revalidate authored assets before using offline cache fallback.

## V0.13.2 subscription delivery

- Connected subscription delivery to the cloud collection workflow.
- Added Brevo test, dry-run, send, and skip workflow modes.
- Fixed Firestore field validation so subscription settings can save under the supplied rules.
- Removed duplicate recipient-email storage from subscription documents.
- Added activation timestamps, historical-event suppression, per-recipient deduplication, category/type filtering, and daily/weekly accumulation.
- Added private aggregate delivery diagnostics and complete setup documentation.
- Next code change: V0.13.3.
