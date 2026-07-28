# Nanaimo Bylaw Tracker — V0.13.1 Release Summary

## Scope

Added an optional cloud-runtime architecture that keeps the authored website on IIS while moving collection, JSON datasets, archived PDFs, extracted text, manifests, and status reporting to Cloudflare R2 and GitHub Actions.

## Cloud architecture

- Added a read-only Cloudflare Worker with a private R2 binding and a `workers.dev` deployment configuration.
- Added CORS, `GET`, `HEAD`, byte-range PDF support, caching, no directory listing, and secure response headers.
- Added scheduled and manual GitHub Actions collection using the existing Python collectors.
- Added content-aware R2 pull, publish, verification, archive-manifest, and collection-status tooling.
- Added a one-time migration command for uploading the existing IIS collection.
- Added a complete `CLOUD_SETUP.md` deployment guide and runtime-focused `.gitignore`.

## Website integration

- Added deployment-specific `cloud-config.js` and shared `cloud-data.js` URL/fetch handling.
- Converted all runtime JSON loaders to use cloud storage when enabled, with optional local fallback during migration.
- Converted runtime JSON links, extracted-text links, recorded archive checks, and archived PDF viewing to cloud-aware URLs.
- Updated the PDF viewer to permit only approved local archive paths or the configured Worker origin.
- Added cloud collection status and archive manifest links to the admin dashboard.
- Updated admin health and summary text to identify cloud mode and the latest cloud publish.
- Kept the service worker from caching deployment-specific cloud configuration.

## Collection behavior retained

- Existing archived PDFs are reused.
- Missing live copies and text are restored from previous cloud state in the collection runner.
- New PDF bodies are downloaded only for new or confirmed-changed sources.
- Duplicate PDF content inside the archive blocks publication.
- Unchanged R2 objects are skipped using SHA-256 metadata.
- Historical archive objects are not deleted by cloud publishing.

## Activation status

Production cloud mode is active at `https://nanaimo-bylaw-data.yardplots.workers.dev`. `cloud-config.js` has cloud loading enabled with local fallback disabled. Preserve the configured file during ordinary IIS upgrades.

## Same-version deployment cleanup

- Updated GitHub workflows to current GitHub-hosted action majors and fixed Ubuntu 24.04 runners.
- Added fail-fast validation for missing R2 secrets before installing collection dependencies.
- Replaced the deprecated `cloudflare/wrangler-action@v3` deployment step with `actions/setup-node@v6`, Node.js 24, and direct pinned `npx wrangler@4.114.0 deploy`.
- Pinned the local Worker development dependency and documented its Node.js requirement.
- Rewrote `CLOUD_SETUP.md` as an exact, ordered GitHub/R2/Worker activation guide that distinguishes the Worker API token from the R2 S3 access-key pair. It now configures the account `workers.dev` subdomain before the first non-interactive GitHub deployment.
- Kept the release version at V0.13.1.
- Updated the service worker to purge the prior same-version static cache and revalidate authored assets before using offline cache fallback.

## Release

- Version: **V0.13.1**
- Next code change: **V0.13.2**
- ZIP: `nanaimo-bylaw-tracker-v0.13.1.zip`

## Same-version cloud response cleanup

- Fixed service-worker caching so response bodies are cloned before asynchronous cache writes; this prevents `Response body is already used` errors.
- Fixed the R2 Worker so complete object reads return HTTP 200 and HTTP 206 is reserved for requests containing a real `Range` header.
- Cloud JSON remains network-first and is never stored in the static service-worker cache.

## Same-version GitHub deployment warning cleanup

- Removed `cloudflare/wrangler-action@v3`, which still declared the deprecated Node.js 20 action runtime.
- Added explicit Node.js 24 setup through `actions/setup-node@v6`.
- Kept Wrangler pinned at 4.114.0 and retained the existing Worker name, R2 binding, secrets, paths, concurrency, and deployment triggers.
- Added fail-fast validation for the Cloudflare deployment token and account ID.
- Disabled Wrangler telemetry during CI deployment.


## Same-version civic count cleanup

- Consolidated the homepage Council and committee loaders so each runtime dataset is requested once and shared across the dashboard and side panels.
- Changed the Council activity side panel from the raw combined civic-item count to the same Council/public-hearing classification used by the dashboard.
- Changed the side-panel document total to unique Council/public-hearing source documents rather than all civic documents.
- Changed the Council meetings card to exclude committee, board, commission, and panel meetings.
- Preserved dedicated committee counts and the combined civic-document total on the data overview page.
- Kept the release version at V0.13.1.
- Updated the service worker to purge the prior same-version static cache and revalidate authored assets before using offline cache fallback.
